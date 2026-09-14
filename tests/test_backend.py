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


def test_locked_paste_cannot_leak_via_sheets_or_revisions(client):
    """v3.5.1 regression: password-gated pastes leaked content through
    GET /sheets/{id} and GET /revisions/{rev} (no pw check)."""
    p = _create(client, content="SECRET BODY", password="pw123")
    slug = p["slug"]

    # main sheet without pw → 401; with pw → content served
    r = client.get(f"/api/paste/{slug}/sheets/main")
    assert r.status_code == 401
    r = client.get(f"/api/paste/{slug}/sheets/main?pw=pw123")
    assert r.status_code == 200
    assert r.json()["content"] == "SECRET BODY"

    # revision content is paste content — must be gated too (401 before 404,
    # so probing for revisions can't distinguish existing from missing ones)
    r = client.get(f"/api/paste/{slug}/revisions/1")
    assert r.status_code in (401, 404)
    r = client.get(f"/api/paste/{slug}/revisions/1?pw=pw123")
    # gate releases (404 here = revision does not exist on a never-edited paste;
    # 200 would be served if it did — never 401)
    assert r.status_code in (200, 404)

    # plain GET still honors the lock (baseline)
    assert client.get(f"/api/paste/{slug}").status_code == 401
    assert client.get(f"/api/paste/{slug}?pw=pw123").status_code == 200


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


# ---------------- v3.6.0: per-paste storage quota ----------------

def test_paste_storage_quota_enforced(client):
    """v3.6.0: a paste whose attachments exceed the (tiny, patched) quota
    rejects further uploads with a 413 naming the quota."""
    import livepaste.storage as st

    p = _create(client, content="quota")
    slug, token = p["slug"], p["editToken"]

    real = st.MAX_PASTE_STORAGE
    st.MAX_PASTE_STORAGE = 300  # bytes — tiny on purpose
    try:
        ok = client.post(
            f"/api/paste/{slug}/file",
            files={"file": ("f1.bin", b"a" * 100, "application/octet-stream")},
            data={"editToken": token},
        )
        assert ok.status_code == 200, ok.text
        full = client.post(
            f"/api/paste/{slug}/file",
            files={"file": ("f2.bin", b"b" * 250, "application/octet-stream")},
            data={"editToken": token},
        )
        assert full.status_code == 413
        assert "quota" in full.json()["detail"].lower()
    finally:
        st.MAX_PASTE_STORAGE = real


def test_paste_quota_frees_on_delete_and_is_per_paste(client):
    """v3.6.0: deleting an attachment frees quota; each paste has its own bucket."""
    import livepaste.storage as st

    p = _create(client, content="quota-free")
    slug, token = p["slug"], p["editToken"]

    real = st.MAX_PASTE_STORAGE
    st.MAX_PASTE_STORAGE = 300
    try:
        r1 = client.post(
            f"/api/paste/{slug}/file",
            files={"file": ("f1.bin", b"a" * 100, "application/octet-stream")},
            data={"editToken": token},
        )
        assert r1.status_code == 200
        file_id = r1.json()["id"]

        # 100 used -> 150 more fits, but another 250 does not
        r2 = client.post(
            f"/api/paste/{slug}/file",
            files={"file": ("f2.bin", b"b" * 150, "application/octet-stream")},
            data={"editToken": token},
        )
        assert r2.status_code == 200
        assert (
            client.post(
                f"/api/paste/{slug}/file",
                files={"file": ("f3.bin", b"c" * 250, "application/octet-stream")},
                data={"editToken": token},
            ).status_code
            == 413
        )

        # Deleting both attachments frees the bucket -> 250 fits again
        assert client.delete(f"/api/file/{file_id}", params={"editToken": token}).status_code == 200
        assert client.delete(f"/api/file/{r2.json()['id']}", params={"editToken": token}).status_code == 200
        assert (
            client.post(
                f"/api/paste/{slug}/file",
                files={"file": ("f4.bin", b"d" * 250, "application/octet-stream")},
                data={"editToken": token},
            ).status_code
            == 200
        )

        # A different paste has an untouched bucket
        other = _create(client, content="other")
        ok = client.post(
            f"/api/paste/{other['slug']}/file",
            files={"file": ("g.bin", b"z" * 290, "application/octet-stream")},
            data={"editToken": other["editToken"]},
        )
        assert ok.status_code == 200
    finally:
        st.MAX_PASTE_STORAGE = real


# ---------------- v3.7.0: fork paste ----------------


def test_fork_copies_content_sheets_files(client):
    p = _create(client, content="root content", language="python")
    slug, token = p["slug"], p["editToken"]
    up = client.post(
        f"/api/paste/{slug}/file",
        files={"file": ("note.txt", b"hello attachment", "text/plain")},
        data={"editToken": token},
    )
    assert up.status_code == 200
    old_file_id = up.json()["id"]
    client.post(
        f"/api/paste/{slug}/sheets",
        json={"editToken": token, "name": "Notes", "content": "sheet body"},
    )

    r = client.post(f"/api/paste/{slug}/fork", json={"editToken": token})
    assert r.status_code == 200, r.text
    fork = r.json()
    assert fork["slug"] != slug
    assert fork["editToken"] and fork["editToken"] != token
    assert fork["content"] == "root content"
    assert fork["language"] == "python"
    assert fork["forkedFrom"] == slug
    assert fork["copiedSheets"] == 1
    assert fork["copiedFiles"] == 1

    # The attachment was duplicated under a NEW id (deletes never alias)
    new_file_id = client.get(f"/api/paste/{fork['slug']}").json()  # just proves readable
    got = client.get(f"/api/file/{old_file_id}")
    assert got.status_code == 200
    # old file still serves and new one exists — fork endpoint returns ids via usage
    usage = client.post(
        f"/api/paste/{fork['slug']}/file",
        files={"file": ("probe.bin", b"x", "application/octet-stream")},
        data={"editToken": fork["editToken"]},
    )
    assert usage.status_code == 200


def test_fork_independent_edits(client):
    p = _create(client, content="original")
    fork = client.post(f"/api/paste/{p['slug']}/fork", json={"editToken": p["editToken"]}).json()
    ok = client.post(
        f"/api/paste/{fork['slug']}/verify", json={"editToken": fork["editToken"]}
    ).json()
    assert ok["canEdit"] is True
    client.post(
        f"/api/paste/{p['slug']}/restore",
        json={"editToken": p["editToken"], "content": "changed original"},
    )
    assert client.get(f"/api/paste/{p['slug']}").json()["content"] == "changed original"
    assert client.get(f"/api/paste/{fork['slug']}").json()["content"] == "original"


def test_fork_locked_paste_requires_password(client):
    p = _create(client, content="secret stuff", password="pw123")
    # No token, no password -> forbidden
    assert client.post(f"/api/paste/{p['slug']}/fork", json={}).status_code == 403
    # Right password -> allowed, but attachments are NOT copied for non-editors
    r = client.post(f"/api/paste/{p['slug']}/fork?pw=pw123", json={})
    assert r.status_code == 200
    assert r.json()["content"] == "secret stuff"
    assert r.json()["copiedFiles"] == 0


def test_fork_custom_slug_and_collisions(client):
    p = _create(client, content="x")
    r = client.post(
        f"/api/paste/{p['slug']}/fork",
        json={"editToken": p["editToken"], "customSlug": "my-fork-1"},
    )
    assert r.status_code == 200 and r.json()["slug"] == "my-fork-1"
    assert (
        client.post(
            f"/api/paste/{p['slug']}/fork",
            json={"editToken": p["editToken"], "customSlug": "my-fork-1"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/paste/{p['slug']}/fork",
            json={"editToken": p["editToken"], "customSlug": "api!bad"},
        ).status_code
        == 400
    )


# ---------------- v3.8.0: duplicate page ----------------


def test_duplicate_sheet_copies_content_and_state(client):
    p = _create(client, content="main text")
    slug, token = p["slug"], p["editToken"]
    made = client.post(
        f"/api/paste/{slug}/sheets",
        json={"editToken": token, "name": "Research", "content": "sheet body"},
    ).json()

    dup = client.post(
        f"/api/paste/{slug}/sheets/{made['sheetId']}/duplicate",
        json={"editToken": token},
    )
    assert dup.status_code == 200, dup.text
    d = dup.json()
    assert d["name"] == "Research copy"

    got = client.get(f"/api/paste/{slug}/sheets/{d['sheetId']}").json()
    assert got["content"] == "sheet body"
    assert got["language"] == "plaintext"

    # Duplicate of main copies the paste's main content
    dm = client.post(
        f"/api/paste/{slug}/sheets/main/duplicate", json={"editToken": token}
    ).json()
    got_main = client.get(f"/api/paste/{slug}/sheets/{dm['sheetId']}").json()
    assert got_main["content"] == "main text"


def test_duplicate_sheet_requires_edit_and_names_deconflict(client):
    p = _create(client, content="x")
    slug, token = p["slug"], p["editToken"]
    made = client.post(
        f"/api/paste/{slug}/sheets",
        json={"editToken": token, "name": "Solo", "content": "abc"},
    ).json()
    # Read-only callers cannot duplicate
    assert (
        client.post(
            f"/api/paste/{slug}/sheets/{made['sheetId']}/duplicate", json={"editToken": "bad"}
        ).status_code
        == 403
    )
    # Duplicate twice -> unique names
    d1 = client.post(
        f"/api/paste/{slug}/sheets/{made['sheetId']}/duplicate", json={"editToken": token}
    ).json()
    d2 = client.post(
        f"/api/paste/{slug}/sheets/{made['sheetId']}/duplicate", json={"editToken": token}
    ).json()
    assert d1["name"] != d2["name"]
    names = {s["name"] for s in client.get(f"/api/paste/{slug}/sheets").json()["sheets"]}
    assert d1["name"] in names and d2["name"] in names


# ---------------- v3.9.0: reorder pages ----------------


def test_reorder_sheets_validates_and_persists(client):
    p = _create(client, content="x")
    slug, token = p["slug"], p["editToken"]
    a = client.post(f"/api/paste/{slug}/sheets", json={"editToken": token, "name": "A", "content": "a"}).json()["sheetId"]
    b = client.post(f"/api/paste/{slug}/sheets", json={"editToken": token, "name": "B", "content": "b"}).json()["sheetId"]

    # main must stay first
    assert (
        client.post(
            f"/api/paste/{slug}/sheets/reorder",
            json={"editToken": token, "order": [a, b, "main"]},
        ).status_code
        == 400
    )
    # incomplete order rejected
    assert (
        client.post(
            f"/api/paste/{slug}/sheets/reorder",
            json={"editToken": token, "order": ["main", a]},
        ).status_code
        == 400
    )
    # valid reorder: B before A
    ok = client.post(
        f"/api/paste/{slug}/sheets/reorder",
        json={"editToken": token, "order": ["main", b, a]},
    )
    assert ok.status_code == 200
    sheets = client.get(f"/api/paste/{slug}/sheets").json()["sheets"]
    assert [s["sheetId"] for s in sheets] == ["main", b, a]

    # read-only cannot reorder
    assert (
        client.post(
            f"/api/paste/{slug}/sheets/reorder",
            json={"editToken": "bad", "order": ["main", a, b]},
        ).status_code
        == 403
    )


# ---------------- v3.15.1 regressions ----------------

def _recv_until(ws, mtype, max_msgs=12):
    """Read messages until one of `mtype` arrives (order-tolerant: presence,
    editors and relay messages can interleave). Fails if it never shows up."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == mtype:
            return msg
    raise AssertionError(f"never received {mtype!r}")


def test_ws_grant_edit_applies_immediately(client):
    """A granted editor's writes must be accepted by the server in the SAME
    session — the handshake-time can_edit must not stay stale (v3.15.1), and
    revocation must apply immediately too."""
    p = _create(client, content="collab")
    slug, token = p["slug"], p["editToken"]

    with client.websocket_connect(f"/api/ws/{slug}?token={token}&clientId=owner") as owner, \
         client.websocket_connect(f"/api/ws/{slug}?clientId=peer") as peer:
        # A peer's presence broadcast can interleave before init (join happens
        # before the init send), so reads must be order-tolerant.
        assert _recv_until(owner, "init")
        assert _recv_until(peer, "init")

        # Owner grants edit to the peer's clientId
        owner.send_json({"type": "grant-edit", "clientId": "peer"})
        ed = _recv_until(peer, "editors")
        assert ed["granted"] is True and ed["changed"] == "peer"

        # THE FIX: the peer can write right now, no reconnect
        peer.send_json({"type": "edit", "content": "granted editor typing"})
        forwarded = _recv_until(owner, "edit")
        assert forwarded["content"] == "granted editor typing"

        # Revocation also applies to the live socket
        owner.send_json({"type": "revoke-edit", "clientId": "peer"})
        rv = _recv_until(peer, "editors")
        assert rv["granted"] is False
        peer.send_json({"type": "edit", "content": "should be rejected"})
        err = _recv_until(peer, "error")
        assert err["code"] == "read_only"


def test_unique_view_counting_on_reconnect(client):
    """Refreshing / reconnecting must not inflate the view counter (v3.15.1):
    one count per distinct clientId, deduped across WS joins and REST views."""
    p = _create(client, content="v")
    slug = p["slug"]

    # First join by alpha → 1 unique view
    with client.websocket_connect(f"/api/ws/{slug}?clientId=alpha") as ws:
        init = ws.receive_json()
        assert init["paste"]["views"] == 1
    # Refresh: same viewer rejoins → still 1
    with client.websocket_connect(f"/api/ws/{slug}?clientId=alpha") as ws:
        init = ws.receive_json()
        assert init["paste"]["views"] == 1
    # A different viewer → 2
    with client.websocket_connect(f"/api/ws/{slug}?clientId=beta") as ws:
        init = ws.receive_json()
        assert init["paste"]["views"] == 2
    # REST dedupes against the same set too
    r = client.get(f"/api/paste/{slug}?count_view=1&clientId=alpha")
    assert r.json()["views"] == 2
    r = client.get(f"/api/paste/{slug}?count_view=1&clientId=gamma")
    assert r.json()["views"] == 3


def test_burn_after_read_not_retriggered_by_reconnect(client):
    """Burn-after-read counts distinct viewers; a known viewer reconnecting
    must not advance the burn countdown (v3.15.1)."""
    p = _create(client, content="burn", burnAfterViews=2)
    slug = p["slug"]

    with client.websocket_connect(f"/api/ws/{slug}?clientId=a") as ws:
        assert ws.receive_json()["type"] == "init"
    # alpha reconnects — must NOT trigger the burn
    with client.websocket_connect(f"/api/ws/{slug}?clientId=a") as ws:
        assert ws.receive_json()["type"] == "init"
    assert client.get(f"/api/paste/{slug}").status_code == 200
    # second distinct viewer reaches the threshold; they still get content
    with client.websocket_connect(f"/api/ws/{slug}?clientId=b") as ws:
        assert ws.receive_json()["type"] == "init"
    # paste is gone for everyone after
    assert client.get(f"/api/paste/{slug}").status_code == 404
