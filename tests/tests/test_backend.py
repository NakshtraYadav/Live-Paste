"""Offline test suite for LivePaste (no network, no MongoDB).

Runs against FastAPI's TestClient with a temp SQLite data dir.
    pip install pytest httpx
    pytest tests/ -v
"""

import base64
import os
import tempfile

import pytest

# Isolated data dir BEFORE importing the app
_TMP = tempfile.mkdtemp(prefix="lp-test-")
os.environ["LIVEPASTE_DATA_DIR"] = _TMP
os.environ["LIVEPASTE_SERVE_STATIC"] = "0"  # no bundled frontend in tests

from fastapi.testclient import TestClient  # noqa: E402

import livepaste.core as lpc
from livepaste.core import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Run startup/shutdown handlers
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_limiters():
    """Fresh in-memory rate-limit and brute-force state for every test, so no
    test can trip a per-IP budget (30 pastes/hour) or inherit another test's
    password failures."""
    lpc.limiter.events.clear()
    lpc.pw_failures.clear()
    yield
    lpc.limiter.events.clear()
    lpc.pw_failures.clear()


def _create(client, **kw):
    res = client.post("/api/paste", json=kw)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------- basics ----------------

def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_version(client):
    v = client.get("/api/version").json()
    assert v["version"] and v["version"] != "0.0.0"


def test_create_and_get(client):
    p = _create(client, content="hello world")
    assert p["slug"] and p["editToken"]
    got = client.get(f"/api/paste/{p['slug']}").json()
    assert got["content"] == "hello world"
    assert "editToken" not in got  # token never leaks via GET


def test_custom_slug_and_duplicate(client):
    _create(client, customSlug="dup-check-1")
    assert client.post("/api/paste", json={"customSlug": "dup-check-1"}).status_code == 409
    assert client.post("/api/paste", json={"customSlug": "api"}).status_code == 400


# ---------------- edit tokens ----------------

def test_verify_token(client):
    p = _create(client, content="x")
    ok = client.post(f"/api/paste/{p['slug']}/verify", json={"editToken": p["editToken"]}).json()
    bad = client.post(f"/api/paste/{p['slug']}/verify", json={"editToken": "nope"}).json()
    assert ok["canEdit"] is True
    assert bad["canEdit"] is False


# ---------------- revisions ----------------

def test_revisions_recorded_and_restorable(client):
    p = _create(client, content="rev base")
    slug, token = p["slug"], p["editToken"]

    # Edit over WebSocket (the canonical write path)
    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as ws:
        assert ws.receive_json()["canEdit"] is True
        for i in range(3):
            ws.send_json({"type": "edit", "content": f"rev {i}"})
            import time

            time.sleep(0.05)

    revs = client.get(f"/api/paste/{slug}/revisions").json()["revisions"]
    assert len(revs) >= 3
    revs_desc = [r["rev"] for r in revs]
    assert revs_desc == sorted(revs_desc, reverse=True)

    snap = client.get(f"/api/paste/{slug}/revisions/{revs_desc[-1]}").json()
    assert snap["content"] == "rev 0"

    # Restore an old revision
    res = client.post(
        f"/api/paste/{slug}/restore", json={"editToken": token, "content": "rev 0"}
    )
    assert res.status_code == 200
    assert client.get(f"/api/paste/{slug}").json()["content"] == "rev 0"

    # Restore without token is rejected
    assert (
        client.post(f"/api/paste/{slug}/restore", json={"editToken": "bad", "content": "x"}).status_code
        == 403
    )


# ---------------- websocket auth ----------------

def test_ws_read_only_rejected(client):
    p = _create(client, content="locked")
    with client.websocket_connect(f"/api/ws/{p['slug']}") as ws:
        assert ws.receive_json()["canEdit"] is False
        ws.send_json({"type": "edit", "content": "hijack"})
        msg = ws.receive_json()
        while msg["type"] == "presence":
            msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "read_only"


def test_ws_editor_accepted(client):
    p = _create(client, content="open")
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        assert ws.receive_json()["canEdit"] is True


# ---------------- CRDT relay ----------------

def test_yupdate_relay_and_state(client):
    p = _create(client, content="")
    slug, token = p["slug"], p["editToken"]
    upd = base64.b64encode(b"fake-yjs-update-bytes").decode()

    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as a, \
         client.websocket_connect(f"/api/ws/{slug}?token={token}") as b:
        a.receive_json()  # init
        b.receive_json()
        a.send_json({"type": "yupdate", "updateB64": upd})
        # b receives presence first (a joined), then the relay
        got = b.receive_json()
        while got["type"] != "yupdate":
            got = b.receive_json()
        assert got["updateB64"] == upd

    import asyncio
    from livepaste import core as _core

    stored = asyncio.get_event_loop().run_until_complete(_core.storage.get_yupdates(slug))
    assert base64.b64encode(stored[-1]).decode() == upd

    # New joiner receives the accumulated state in init
    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as c:
        init = c.receive_json()
        assert init.get("yUpdatesB64") and upd in init["yUpdatesB64"]


# ---------------- files: literally anything ----------------

@pytest.mark.parametrize(
    "name,ctype,body",
    [
        ("setup.exe", "application/vnd.microsoft.portable-executable", b"MZ\x90\x00binary"),
        ("cool.vyb", "application/octet-stream", b"\x00\x01\x02"),
        ("Makefile", "application/octet-stream", b"all:\n\techo hi\n"),
        ("report.txt", "text/plain", "héllo wörld".encode()),
        ("empty.bin", "application/octet-stream", b""),
    ],
)
def test_any_file_roundtrip(client, name, ctype, body):
    p = _create(client, content="files")
    res = client.post(
        f"/api/paste/{p['slug']}/file",
        files={"file": (name, body, ctype)},
        data={"editToken": p["editToken"]},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]
    assert res.json()["name"] == name

    dl = client.get(f"/api/file/{fid}")
    assert dl.status_code == 200
    assert dl.content == body


def test_path_style_filename_flattened(client):
    p = _create(client, content="x")
    res = client.post(
        f"/api/paste/{p['slug']}/file",
        files={"file": ("../../etc/passwd", b"x", "application/octet-stream")},
        data={"editToken": p["editToken"]},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "passwd"


def test_legacy_image_endpoint_still_image_only(client):
    p = _create(client, content="x")
    r = client.post(
        f"/api/paste/{p['slug']}/image",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"editToken": p["editToken"]},
    )
    assert r.status_code == 400


def test_upload_requires_edit_rights(client):
    """v3.3.0: uploads/deletes are server-side token-gated now."""
    p = _create(client, content="guard")
    slug, token = p["slug"], p["editToken"]

    no_tok = client.post(
        f"/api/paste/{slug}/file",
        files={"file": ("a.txt", b"x", "text/plain")},
    )
    assert no_tok.status_code == 403
    bad_tok = client.post(
        f"/api/paste/{slug}/file",
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"editToken": "wrong"},
    )
    assert bad_tok.status_code == 403

    # granted editors CAN upload
    ok = client.post(
        f"/api/paste/{slug}/file",
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"clientId": "peer-1"},
    )
    assert ok.status_code == 403  # not granted yet
    ws = client.websocket_connect(f"/api/ws/{slug}?token={token}&clientId=owner")
    ws.__enter__()
    ws.send_json({"type": "grant-edit", "clientId": "peer-1"})
    ws.send_json({"type": "ping"})
    seen = set()
    for _ in range(10):
        m = ws.receive_json()
        seen.add(m.get("type"))
        if m.get("type") == "editors" or (seen >= {"init"} and m.get("type") == "pong"):
            break
    assert "editors" in seen
    ws.__exit__(None, None, None)
    ok2 = client.post(
        f"/api/paste/{slug}/file",
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"clientId": "peer-1"},
    )
    assert ok2.status_code == 200, ok2.text
    fid = ok2.json()["id"]

    # unauthenticated delete is refused
    del_no = client.delete(f"/api/file/{fid}")
    assert del_no.status_code == 403
    del_bad = client.delete(f"/api/file/{fid}?editToken=wrong")
    assert del_bad.status_code == 403
    del_ok = client.delete(f"/api/file/{fid}?editToken={token}")
    assert del_ok.status_code == 200


# ---------------- sheets (multiple pages) ----------------

def test_sheets_default_and_create(client):
    p = _create(client, content="page one")
    slug, token = p["slug"], p["editToken"]

    sheets = client.get(f"/api/paste/{slug}/sheets").json()["sheets"]
    assert sheets == [{"sheetId": "main", "name": "Page 1", "position": 0}]

    res = client.post(
        f"/api/paste/{slug}/sheets",
        json={"editToken": token, "name": "Notes", "content": "sheet body"},
    )
    assert res.status_code == 200
    sid = res.json()["sheetId"]
    assert res.json()["name"] == "Notes"

    # main is now listed alongside real sheets, and the new sheet got "Page 2"
    listed = client.get(f"/api/paste/{slug}/sheets").json()["sheets"]
    assert [s["sheetId"] for s in listed] == ["main", sid]
    assert listed[0]["name"] == "Page 1"
    assert listed[1]["name"] == "Notes"

    body = client.get(f"/api/paste/{slug}/sheets/{sid}").json()
    assert body["content"] == "sheet body"
    assert body["language"] == "plaintext"

    # main sheet maps to the paste content
    main = client.get(f"/api/paste/{slug}/sheets/main").json()
    assert main["content"] == "page one"

    # create with a wrong token → 403
    assert (
        client.post(
            f"/api/paste/{slug}/sheets", json={"editToken": "wrong", "name": "nope"}
        ).status_code
        == 403
    )


def test_sheet_rename_language_delete(client):
    p = _create(client, content="x")
    slug, token = p["slug"], p["editToken"]
    sid = client.post(
        f"/api/paste/{slug}/sheets", json={"editToken": token, "name": "Draft"}
    ).json()["sheetId"]

    res = client.patch(
        f"/api/paste/{slug}/sheets/{sid}",
        json={"editToken": token, "name": "Draft 2", "language": "python"},
    )
    assert res.json()["name"] == "Draft 2"
    assert res.json()["language"] == "python"

    assert (
        client.delete(f"/api/paste/{slug}/sheets/{sid}?editToken={token}").status_code == 200
    )
    assert client.get(f"/api/paste/{slug}/sheets/{sid}").status_code == 404

    # main sheet can't be deleted
    assert (
        client.delete(f"/api/paste/{slug}/sheets/main?editToken={token}").status_code == 400
    )


def test_sheet_ws_relay_and_state(client):
    p = _create(client, content="")
    slug, token = p["slug"], p["editToken"]
    sid = client.post(
        f"/api/paste/{slug}/sheets", json={"editToken": token, "name": "P2"}
    ).json()["sheetId"]
    upd = base64.b64encode(b"sheet-y-update").decode()

    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as a, \
         client.websocket_connect(f"/api/ws/{slug}?token={token}") as b:
        a.receive_json()
        b.receive_json()
        a.send_json({"type": "s:yupdate", "sheetId": sid, "updateB64": upd})
        got = b.receive_json()
        while got["type"] != "s:yupdate":
            got = b.receive_json()
        assert got["sheetId"] == sid and got["updateB64"] == upd

    # a fresh joiner opens the sheet and receives the stored state
    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as c:
        c.receive_json()  # init
        c.send_json({"type": "s:open", "sheetId": sid})
        state = c.receive_json()
        while state["type"] != "s:state":
            state = c.receive_json()
        assert state["sheetId"] == sid
        assert upd in state["yUpdatesB64"]


def test_sheet_full_text_edit_persists(client):
    p = _create(client, content="x")
    slug, token = p["slug"], p["editToken"]
    sid = client.post(
        f"/api/paste/{slug}/sheets", json={"editToken": token}
    ).json()["sheetId"]

    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "s:edit", "sheetId": sid, "content": "edited sheet"})
        import time

        time.sleep(0.1)

    assert client.get(f"/api/paste/{slug}/sheets/{sid}").json()["content"] == "edited sheet"
    # main content untouched
    assert client.get(f"/api/paste/{slug}").json()["content"] == "x"


# ---------------- v2.8.0: burn-after-read + password lock ----------------

def test_burn_after_views_destroys_paste(client):
    p = _create(client, content="secret", burnAfterViews=2)
    slug = p["slug"]
    # Two distinct viewers
    r1 = client.get(f"/api/paste/{slug}?count_view=1&clientId=viewer-1")
    assert r1.status_code == 200
    r2 = client.get(f"/api/paste/{slug}?count_view=1&clientId=viewer-2")
    assert r2.status_code == 200
    # Third fetch: paste is gone
    r3 = client.get(f"/api/paste/{slug}")
    assert r3.status_code == 404


def test_burn_after_views_repeat_viewer_does_not_trigger(client):
    p = _create(client, content="secret", burnAfterViews=2)
    slug = p["slug"]
    assert client.get(f"/api/paste/{slug}?count_view=1&clientId=a").status_code == 200
    # Same viewer again — still one unique burner, no burn yet
    assert client.get(f"/api/paste/{slug}?count_view=1&clientId=a").status_code == 200
    assert client.get(f"/api/paste/{slug}").status_code == 200


def test_password_lock_rest(client):
    p = _create(client, content="locked", password="hunter2")
    slug = p["slug"]
    assert p.get("passwordHash") is None  # hash never leaves the server
    # Wrong / missing password → 401
    assert client.get(f"/api/paste/{slug}").status_code == 401
    assert client.get(f"/api/paste/{slug}?pw=wrong").status_code == 401
    # Correct password → 200
    ok = client.get(f"/api/paste/{slug}?pw=hunter2")
    assert ok.status_code == 200 and ok.json()["content"] == "locked"
    # Verify endpoint round-trip
    v = client.post(f"/api/paste/{slug}/password", json={"password": "hunter2"}).json()
    assert v == {"ok": True, "locked": True}


def test_password_lock_websocket(client):
    p = _create(client, content="locked-ws", password="pw123")
    slug = p["slug"]
    # No password → error + close 4401
    with client.websocket_connect(f"/api/ws/{slug}") as ws:
        msg = ws.receive_json()
        assert msg["code"] == "password_required"
    # Right password → init arrives
    with client.websocket_connect(f"/api/ws/{slug}?pw=pw123") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "init" and msg["paste"]["content"] == "locked-ws"


def test_ws_init_does_not_leak_secrets(client):
    p = _create(client, content="x", password="pw", burnAfterViews=3)
    slug = p["slug"]
    with client.websocket_connect(f"/api/ws/{slug}?pw=pw") as ws:
        init = ws.receive_json()
        assert "passwordHash" not in init["paste"]
        assert "editToken" not in init["paste"]
        assert init["burnAfterViews"] == 3


# ---------------- v3.1.1: handshake disconnect robustness ----------------

def test_ws_vanish_before_init_does_not_leak_room(client):
    """A client that disconnects mid-handshake must never stay in the room.

    Regression for the uvicorn `ClientDisconnected` crash: the init send used
    to run outside the try/except, so the ASGI task died before cleanup ran
    and the dead socket kept counting as a viewer.
    """
    p = _create(client, content="vanish test")
    slug, token = p["slug"], p["editToken"]

    # Join and vanish immediately (context exit races the init delivery —
    # the client never reads `init`, exactly like a tab navigating away)
    with client.websocket_connect(f"/api/ws/{slug}?token={token}"):
        pass

    # The room must be empty now — no leaked socket, viewers back to 0
    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as probe:
        init = probe.receive_json()
        assert init["type"] == "init"
        assert init["viewers"] == 1


def test_ws_vanish_no_broadcast_crash(client):
    """Broadcasting to a room whose socket died mid-handshake must not raise."""
    p = _create(client, content="x")
    slug, token = p["slug"], p["editToken"]
    # Socket 1 joins and vanishes mid-handshake (never reads init)
    with client.websocket_connect(f"/api/ws/{slug}?token={token}"):
        pass
    # Socket 2 edits — broadcast must not crash on any stale peer
    with client.websocket_connect(f"/api/ws/{slug}?token={token}") as alive:
        alive.receive_json()  # init
        alive.send_json({"type": "edit", "content": "still alive"})
        import time as _t

        _t.sleep(0.1)
    assert client.get(f"/api/paste/{slug}").json()["content"] == "still alive"


# ---------------- v3.2.0: password brute-force lockout ----------------

def test_password_lockout_after_repeated_failures(client):
    """After 8 wrong attempts from one IP, even the right password is refused."""
    p = _create(client, content="locked secret", password="open sesame")
    slug = p["slug"]
    wrong = {"password": "wrong"}
    right = {"password": "open sesame"}

    for _ in range(8):
        res = client.post(f"/api/paste/{slug}/password", json=wrong)
        assert res.status_code == 200 and res.json()["ok"] is False

    # 9th attempt — blocked even with the CORRECT password
    res = client.post(f"/api/paste/{slug}/password", json=right)
    assert res.status_code == 429

    # Different slug is unaffected (lockout is per (ip, slug))
    p2 = _create(client, content="other", password="pw2")
    ok2 = client.post(f"/api/paste/{p2['slug']}/password", json={"password": "pw2"})
    assert ok2.status_code == 200 and ok2.json()["ok"] is True


def test_password_lockout_resets_on_success(client):
    """A correct password clears the failure counter (honest typos don't lock out)."""
    p = _create(client, content="reset me", password="s3cret")
    slug = p["slug"]
    for _ in range(3):
        client.post(f"/api/paste/{slug}/password", json={"password": "nope"})
    ok = client.post(f"/api/paste/{slug}/password", json={"password": "s3cret"})
    assert ok.json()["ok"] is True
    # Counter cleared: 8 more failures are needed before lockout
    for i in range(8):
        res = client.post(f"/api/paste/{slug}/password", json={"password": "nope"})
        assert res.status_code == 200 and res.json()["ok"] is False, f"locked early at {i}"
    blocked = client.post(f"/api/paste/{slug}/password", json={"password": "s3cret"})
    assert blocked.status_code == 429


def test_unlocked_paste_password_endpoint_unlimited(client):
    """Unlocked pastes skip the limiter entirely (no oracle to protect)."""
    p = _create(client, content="free")
    for _ in range(12):
        res = client.post(f"/api/paste/{p['slug']}/password", json={"password": "whatever"})
        assert res.status_code == 200 and res.json() == {"ok": True, "locked": False}
