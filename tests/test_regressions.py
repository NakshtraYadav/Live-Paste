"""Regression specifications for the November 2026 reliability repairs.

Run: .venv/bin/python -m pytest tests/test_regressions.py -q
These assertions must all pass.
All application data is temporary; restart/process calls are mocked.
"""
import base64
import os
import tempfile
from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["LIVEPASTE_DATA_DIR"] = tempfile.mkdtemp(prefix="lp-bug-audit-")
os.environ["LIVEPASTE_SERVE_STATIC"] = "0"

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from livepaste import cli, core
from pycrdt import Doc, Text


@pytest.fixture
def client():
    core.limiter.events.clear()
    core.pw_failures.clear()
    with TestClient(core.app) as c:
        yield c


def create(client, **kwargs):
    response = client.post("/api/paste", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def until(ws, kind):
    for _ in range(30):
        message = ws.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"No {kind} response")


def test_granted_identity_does_not_disclose_capability(client):
    p = create(client)
    client.portal.call(core.storage.update_editors, p["slug"], ["public-peer-id"])
    with client.websocket_connect(f"/api/ws/{p['slug']}?clientId=public-peer-id") as attacker:
        init = until(attacker, "init")
        assert init["canEdit"] is False
        stolen = init.get("editorCapability", "")
    # Prove the disclosure actually enables a second unauthenticated connection.
    if stolen:
        with client.websocket_connect(f"/api/ws/{p['slug']}?clientId=public-peer-id&capability={stolen}") as attacker:
            assert until(attacker, "init")["canEdit"] is False
    assert not stolen


def test_viewer_can_request_sheet_sync_state(client):
    p = create(client)
    with client.websocket_connect(f"/api/ws/{p['slug']}") as viewer:
        until(viewer, "init")
        viewer.send_json({"type": "s:open", "sheetId": "main"})
        assert viewer.receive_json()["type"] == "s:state"


def test_full_text_backup_preserves_crdt_history(client):
    p = create(client)
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        until(ws, "init")
        ws.send_json({"type": "yupdate", "updateB64": base64.b64encode(Doc({"content": Text("saved text")}).get_update()).decode()})
        ws.send_json({"type": "edit", "content": "saved text"})
        ws.send_json({"type": "ping"})
        until(ws, "pong")
        assert client.portal.call(core.storage.get_yupdates, p["slug"])


def test_rest_password_guesses_are_limited(client):
    p = create(client, password="correct")
    statuses = [client.get(f"/api/paste/{p['slug']}", params={"pw": "wrong"}).status_code for _ in range(10)]
    assert 429 in statuses, statuses


def test_long_password_round_trips(client):
    password = "p" * 201
    p = create(client, password=password)
    assert client.get(f"/api/paste/{p['slug']}", headers={"X-View-Password": password}).status_code == 200


def test_locked_paste_hides_sheet_names(client):
    p = create(client, password="correct")
    response = client.post(f"/api/paste/{p['slug']}/sheets", json={"editToken": p["editToken"], "name": "Private project name"})
    assert response.status_code == 200
    assert client.get(f"/api/paste/{p['slug']}/sheets").status_code == 401


def test_burn_counts_anonymous_reads(client):
    p = create(client, content="disposable", burnAfterViews=1)
    url = f"/api/paste/{p['slug']}?count_view=true"
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 404


def test_purge_all_clears_history(client):
    p = create(client)
    client.portal.call(core.storage.append_yupdate, p["slug"], b"private update")
    from livepaste.storage import now_utc
    client.portal.call(core.storage.append_revision, p["slug"], "private revision", now_utc())
    client.portal.call(core.storage.purge_all)
    remaining = {
        "updates": client.portal.call(core.storage.get_yupdates, p["slug"]),
        "revisions": client.portal.call(core.storage.list_revisions, p["slug"]),
    }
    assert remaining == {"updates": [], "revisions": []}


def test_expired_socket_cannot_write_updates(client):
    p = create(client)
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        until(ws, "init")
        async def expire():
            await core.storage._conn.execute("UPDATE pastes SET expires_at = ? WHERE slug = ?", ("2000-01-01T00:00:00+00:00", p["slug"]))
            await core.storage._conn.commit()
        client.portal.call(expire)
        ws.send_json({"type": "yupdate", "updateB64": "YWJj"})
        ws.send_json({"type": "ping"})
        try:
            until(ws, "pong")
        except WebSocketDisconnect:
            pass
        assert not client.portal.call(core.storage.get_yupdates, p["slug"])


def mock_restart(monkeypatch, tmp_path, *, pending=True, lsof=""):
    monkeypatch.setattr(cli, "read_config", lambda: {})
    monkeypatch.setattr(cli, "_read_launch", lambda port=None: {})
    staged = tmp_path / "pending.json"
    if pending: staged.write_text("{}")
    monkeypatch.setattr(cli, "_staged_update_path", lambda: str(staged))
    monkeypatch.setattr(cli, "pop_pending_restart", lambda: {"version": "3.18.0"} if pending else None)
    monkeypatch.setattr(cli, "PID_PATH", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(cli, "SERVER_LOG", str(tmp_path / "server.log"))
    monkeypatch.setattr(cli, "is_frozen", lambda: False)
    monkeypatch.delenv("LIVEPASTE_DATA_DIR", raising=False)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.setattr(cli.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    kill = Mock()
    popen = Mock(return_value=SimpleNamespace(pid=987654, poll=lambda: None))
    monkeypatch.setattr(cli.os, "kill", kill)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=lsof, returncode=0))
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "_safe_urlopen", lambda *a, **k: nullcontext(SimpleNamespace(status=200)))
    cli.cmd_restart(Namespace(port=None))
    return kill, popen


def test_restart_uses_start_default_port(monkeypatch, tmp_path):
    _, popen = mock_restart(monkeypatch, tmp_path)
    cmd = popen.call_args.args[0]
    assert cmd[cmd.index("--port") + 1] == "8090"


def test_restart_uses_start_default_data_dir(monkeypatch, tmp_path):
    _, popen = mock_restart(monkeypatch, tmp_path)
    assert popen.call_args.kwargs["env"]["LIVEPASTE_DATA_DIR"] == str(tmp_path / ".livepaste")


def test_restart_never_kills_an_unrelated_port_user(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_pid_is_livepaste", lambda pid: False)
    kill, _ = mock_restart(monkeypatch, tmp_path, pending=False, lsof="87654\n")
    kill.assert_not_called()


def test_explicit_keep_data_overrides_legacy_config(monkeypatch, tmp_path):
    import uvicorn
    monkeypatch.setattr(cli, "_is_windows", lambda: False)
    monkeypatch.setattr(cli, "PID_PATH", str(tmp_path / "server.pid"))
    monkeypatch.setattr(cli, "read_config", lambda: {"KEEP_DATA": "0"})
    monkeypatch.setattr(cli, "get_lan_ip", lambda: None)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.setenv("LIVEPASTE_EPHEMERAL", "0")
    monkeypatch.setattr(uvicorn, "run", Mock())
    cli.cmd_start(Namespace(data_dir=None, ephemeral=False, keep_data=True, host="127.0.0.1", port=0, no_update_check=True))
    assert os.environ["LIVEPASTE_EPHEMERAL"] == "0"


def test_file_upload_download_round_trip(client):
    """Passing control: storage and HTTP download return the original bytes."""
    p = create(client)
    data = b"LivePaste audit file\x00\xff"
    response = client.post(f"/api/paste/{p['slug']}/file", data={"editToken": p["editToken"]}, files={"file": ("audit.bin", data, "application/octet-stream")})
    assert response.status_code == 200
    downloaded = client.get(response.json()["url"])
    assert downloaded.status_code == 200
    assert downloaded.content == data



def test_grant_survives_reconnect_only_with_original_identity_and_capability(client):
    p = create(client)
    path = f"/api/ws/{p['slug']}"
    with client.websocket_connect(f"{path}?token={p['editToken']}&clientId=owner") as owner, client.websocket_connect(f"{path}?clientId=peer") as peer:
        until(owner, "init")
        initial = until(peer, "init")
        assert "p2pKey" not in initial
        owner.send_json({"type": "grant-edit", "clientId": "peer"})
        secret = until(peer, "editor-capability")["capability"]
        permission = until(peer, "permissions")
        assert permission["canEdit"] and permission["p2pKey"]
    with client.websocket_connect(f"{path}?clientId=peer&capability={secret}") as peer:
        assert until(peer, "init")["canEdit"] is True
    with client.websocket_connect(f"{path}?clientId=peer") as impersonator:
        init = until(impersonator, "init")
        assert init["canEdit"] is False and "editorCapability" not in init and "p2pKey" not in init
    assert "p2pKey" not in client.get(f"/api/paste/{p['slug']}").json()


def test_concurrent_documents_merge_restore_and_replay_without_duplicate_initial_text(client):
    p = create(client, content="base")
    path = f"/api/ws/{p['slug']}?token={p['editToken']}"
    with client.websocket_connect(path) as a, client.websocket_connect(path) as b:
        state_a, state_b = until(a, "init"), until(b, "init")
        docs = []
        for state in (state_a, state_b):
            doc = Doc({"content": Text()})
            for update in state["yUpdatesB64"]: doc.apply_update(base64.b64decode(update))
            docs.append(doc)
        docs[0]["content"].insert(4, " A")
        docs[1]["content"].insert(4, " B")
        for ws, doc, request_id in ((a, docs[0], "a"), (b, docs[1], "b")):
            ws.send_json({"type": "sync", "sheetId": "main", "requestId": request_id, "updateB64": base64.b64encode(doc.get_update()).decode()})
            assert until(ws, "sync-ack")["requestId"] == request_id
    text = client.get(f"/api/paste/{p['slug']}").json()["content"]
    assert text in ("base A B", "base B A")
    assert client.post(f"/api/paste/{p['slug']}/restore", json={"editToken": p["editToken"], "content": "restored"}).status_code == 200
    with client.websocket_connect(path) as fresh:
        state = until(fresh, "init")
        replay = Doc({"content": Text()})
        for update in state["yUpdatesB64"]: replay.apply_update(base64.b64decode(update))
        assert str(replay["content"]) == "restored"


@pytest.mark.parametrize("range_value,status,expected", [("bytes=2-4",206,b"234"),("bytes=-3",206,b"789"),("bytes=30-",416,None)])
def test_download_ranges(client, range_value, status, expected):
    p = create(client)
    upload = client.post(f"/api/paste/{p['slug']}/file", data={"editToken":p["editToken"]}, files={"file":("unicode-报告.bin",b"0123456789","application/octet-stream")})
    response = client.get(upload.json()["url"], headers={"Range":range_value})
    assert response.status_code == status
    if expected is not None: assert response.content == expected
    assert "public" not in response.headers.get("cache-control", "")


def test_legacy_incomplete_history_recovers_backup_and_archives_original_bytes(client):
    p = create(client, content="last durable backup")
    client.portal.call(core.storage.append_yupdate, p["slug"], b"invalid legacy history")
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        initial = until(ws,"init")
        assert initial["paste"]["content"] == "last durable backup"
        assert len(initial["epoch"]) == 32
        doc = Doc({"content":Text()})
        for update in initial["yUpdatesB64"]: doc.apply_update(base64.b64decode(update))
        assert str(doc["content"]) == "last durable backup"
    async def archived():
        cursor = await core.storage._conn.execute("SELECT payload FROM document_recovery WHERE slug = ?", (p["slug"],))
        return await cursor.fetchone()
    assert base64.b64encode(b"invalid legacy history").decode() in client.portal.call(archived)[0]


def test_document_identity_changes_when_a_slug_is_reused(client):
    p = create(client, customSlug="reuse-epoch", content="old")
    old = client.portal.call(core.document_epoch, p["slug"])
    client.portal.call(core.storage.delete_paste, p["slug"])
    create(client, customSlug="reuse-epoch", content="new")
    assert client.portal.call(core.document_epoch, p["slug"]) != old


def test_state_vector_acknowledges_only_missing_updates(client):
    p = create(client, content="x" * 300)
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        initial = until(ws,"init")
        doc = Doc({"content":Text()})
        for item in initial["yUpdatesB64"]: doc.apply_update(base64.b64decode(item))
        doc["content"].insert(300,"!")
        ws.send_json({"type":"sync","sheetId":"main","requestId":"diff","epoch":initial["epoch"],"stateVectorB64":base64.b64encode(doc.get_state()).decode(),"updateB64":base64.b64encode(doc.get_update(base64.b64decode(initial["stateVectorB64"]))).decode()})
        ack = until(ws,"sync-ack")
        assert len(base64.b64decode(ack["yUpdatesB64"][0])) < 20
        assert ack["content"] == "x" * 300 + "!"


def test_source_version_ignores_stale_frozen_build_metadata(monkeypatch):
    import sys
    import livepaste
    monkeypatch.setattr(sys,"frozen",False,raising=False)
    monkeypatch.setitem(sys.modules,"livepaste._version",SimpleNamespace(__version__="0.0.1"))
    assert livepaste._detect_version() == (Path(__file__).resolve().parents[1]/"VERSION").read_text().strip()
