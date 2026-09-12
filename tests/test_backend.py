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

from livepaste.core import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Run startup/shutdown handlers
    with TestClient(app) as c:
        yield c


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
    )
    assert res.status_code == 200
    assert res.json()["name"] == "passwd"


def test_legacy_image_endpoint_still_image_only(client):
    p = _create(client, content="x")
    r = client.post(
        f"/api/paste/{p['slug']}/image",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
