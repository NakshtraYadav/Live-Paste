"""Known-bug specifications, separate from the normal passing test suite.

Run: .venv/bin/python -m pytest audit/2026-11-12/test_reproductions.py -q -rx
Each strict xfail is a demonstrated defect, not a skipped investigation.
Remove the corresponding marker when repairing that defect.
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


@pytest.mark.xfail(strict=True, reason="B01: handshake discloses a granted editor's capability to an impersonator")
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


@pytest.mark.xfail(strict=True, reason="B03: s:open reads are included in the write-only authorization gate")
def test_viewer_can_request_sheet_sync_state(client):
    p = create(client)
    with client.websocket_connect(f"/api/ws/{p['slug']}") as viewer:
        until(viewer, "init")
        viewer.send_json({"type": "s:open", "sheetId": "main"})
        assert viewer.receive_json()["type"] == "s:state"


@pytest.mark.xfail(strict=True, reason="B04: full-text backups erase the CRDT dependency chain")
def test_full_text_backup_preserves_crdt_history(client):
    p = create(client)
    with client.websocket_connect(f"/api/ws/{p['slug']}?token={p['editToken']}") as ws:
        until(ws, "init")
        ws.send_json({"type": "yupdate", "updateB64": base64.b64encode(b"example-update").decode()})
        ws.send_json({"type": "edit", "content": "saved text"})
        ws.send_json({"type": "ping"})
        until(ws, "pong")
        assert client.portal.call(core.storage.get_yupdates, p["slug"])


@pytest.mark.xfail(strict=True, reason="B08: REST content reads bypass password lockout")
def test_rest_password_guesses_are_limited(client):
    p = create(client, password="correct")
    statuses = [client.get(f"/api/paste/{p['slug']}", params={"pw": "wrong"}).status_code for _ in range(10)]
    assert 429 in statuses, statuses


@pytest.mark.xfail(strict=True, reason="B09: password creation silently truncates at 200 characters")
def test_long_password_round_trips(client):
    password = "p" * 201
    p = create(client, password=password)
    assert client.get(f"/api/paste/{p['slug']}", headers={"X-View-Password": password}).status_code == 200


@pytest.mark.xfail(strict=True, reason="B10: sheet names are readable without the paste password")
def test_locked_paste_hides_sheet_names(client):
    p = create(client, password="correct")
    response = client.post(f"/api/paste/{p['slug']}/sheets", json={"editToken": p["editToken"], "name": "Private project name"})
    assert response.status_code == 200
    assert client.get(f"/api/paste/{p['slug']}/sheets").status_code == 401


@pytest.mark.xfail(strict=True, reason="B11: anonymous reads increment views but never trigger burn")
def test_burn_counts_anonymous_reads(client):
    p = create(client, content="disposable", burnAfterViews=1)
    url = f"/api/paste/{p['slug']}?count_view=true"
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 404


@pytest.mark.xfail(strict=True, reason="B12: ephemeral purge leaves main Yjs state and revision history behind")
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


@pytest.mark.xfail(strict=True, reason="B13: an admitted socket can store CRDT updates after paste expiry")
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
    monkeypatch.setattr(cli, "pop_pending_restart", lambda: {"version": "3.18.0"} if pending else None)
    monkeypatch.setattr(cli, "PID_PATH", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(cli, "SERVER_LOG", str(tmp_path / "server.log"))
    monkeypatch.setattr(cli, "is_frozen", lambda: False)
    monkeypatch.delenv("LIVEPASTE_DATA_DIR", raising=False)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.setattr(cli.os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    kill = Mock()
    popen = Mock(return_value=SimpleNamespace(pid=987654))
    monkeypatch.setattr(cli.os, "kill", kill)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=lsof, returncode=0))
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "_safe_urlopen", lambda *a, **k: nullcontext(SimpleNamespace(status=200)))
    cli.cmd_restart(Namespace(port=None))
    return kill, popen


@pytest.mark.xfail(strict=True, reason="B14: restart defaults to port 8000 while start uses 8090")
def test_restart_uses_start_default_port(monkeypatch, tmp_path):
    _, popen = mock_restart(monkeypatch, tmp_path)
    cmd = popen.call_args.args[0]
    assert cmd[cmd.index("--port") + 1] == "8090"


@pytest.mark.xfail(strict=True, reason="B14: restart switches the default storage directory to ~/.livepaste/data")
def test_restart_uses_start_default_data_dir(monkeypatch, tmp_path):
    _, popen = mock_restart(monkeypatch, tmp_path)
    assert popen.call_args.kwargs["env"]["LIVEPASTE_DATA_DIR"] == str(tmp_path / ".livepaste")


@pytest.mark.xfail(strict=True, reason="B15: restart kills unrelated port users without checking their identity")
def test_restart_never_kills_an_unrelated_port_user(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_pid_is_livepaste", lambda pid: False)
    kill, _ = mock_restart(monkeypatch, tmp_path, pending=False, lsof="87654\n")
    kill.assert_not_called()


@pytest.mark.xfail(strict=True, reason="B16: --keep-data is ignored when KEEP_DATA=0 is configured")
def test_explicit_keep_data_overrides_legacy_config(monkeypatch):
    import uvicorn
    monkeypatch.setattr(cli, "read_config", lambda: {"KEEP_DATA": "0"})
    monkeypatch.setattr(cli, "get_lan_ip", lambda: None)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.setenv("LIVEPASTE_EPHEMERAL", "0")
    monkeypatch.setattr(uvicorn, "run", Mock())
    cli.cmd_start(Namespace(data_dir=None, ephemeral=False, keep_data=True, host="127.0.0.1", port=18191, no_update_check=True))
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
