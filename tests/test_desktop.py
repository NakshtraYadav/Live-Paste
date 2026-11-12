"""Windows lifecycle boundaries; real runtime tests also run on Windows CI."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from livepaste import autostart, cli, desktop


def test_windows_release_asset(monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cli.platform, "machine", lambda: "AMD64")
    assert cli.binary_asset_name() == "livepaste-windows-x86_64.exe"


@pytest.mark.parametrize("command,expected", [
    ('"C:\\Program Files\\LivePaste\\livepaste.exe" start --keep-data', True),
    ('"C:\\Users\\Test User\\python.exe" -m livepaste start', True),
    ('"C:\\Users\\Test User\\python.exe" -m otherapp start', False),
    ('"C:\\Program Files\\other.exe" start', False),
])
def test_windows_process_identity(monkeypatch, command, expected):
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=command))
    assert cli._pid_is_livepaste(12345) is expected


def test_windows_stop_uses_authenticated_local_control_not_terminate(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "PID_PATH", str(tmp_path / "livepaste.pid"))
    monkeypatch.setattr(cli, "_pid_is_livepaste", lambda pid: True)
    stamps = iter(["created", ""])
    monkeypatch.setattr(cli, "_process_started", lambda pid: next(stamps))
    kill = Mock()
    monkeypatch.setattr(cli.os, "kill", kill)
    atomic = Mock(wraps=cli._atomic_json)
    monkeypatch.setattr(cli, "_atomic_json", atomic)
    cli._stop_launch({"pid": 12345, "process_started": "created", "control_token": "private-control"})
    atomic.assert_called_once_with(str(tmp_path / "livepaste.pid.12345.stop"), {"token": "private-control"})
    kill.assert_not_called()


def test_stale_process_record_cannot_stop_reused_pid(monkeypatch):
    monkeypatch.setattr(cli, "_pid_is_livepaste", lambda pid: True)
    monkeypatch.setattr(cli, "_process_started", lambda pid: "other-process")
    kill = Mock()
    monkeypatch.setattr(cli.os, "kill", kill)
    cli._stop_launch({"pid": 12345, "process_started": "old-process"})
    kill.assert_not_called()


def test_windows_restart_does_not_probe_stopped_pid_with_posix_signals(monkeypatch, tmp_path):
    from contextlib import nullcontext
    launch = {"pid":12345,"process_started":"created","host":"127.0.0.1","port":8090,"data_dir":str(tmp_path)}
    monkeypatch.setattr(cli,"_is_windows",lambda:True)
    monkeypatch.setattr(cli,"_read_launch",lambda port=None:launch)
    monkeypatch.setattr(cli,"_pid_is_livepaste",lambda pid:True)
    monkeypatch.setattr(cli,"_process_started",lambda pid:"created")
    monkeypatch.setattr(cli,"_stop_launch",Mock())
    monkeypatch.setattr(cli,"SERVER_LOG",str(tmp_path/"server.log"))
    monkeypatch.setattr(cli,"read_config",lambda:{})
    monkeypatch.setattr(cli,"is_frozen",lambda:False)
    monkeypatch.setattr(cli,"pop_pending_restart",lambda:None)
    monkeypatch.setattr(cli,"_safe_urlopen",lambda *a,**k:nullcontext(SimpleNamespace(status=200)))
    monkeypatch.setattr(cli.subprocess,"Popen",Mock(return_value=SimpleNamespace(pid=98765,poll=lambda:None)))
    kill=Mock()
    monkeypatch.setattr(cli.os,"kill",kill)
    cli.cmd_restart(SimpleNamespace(port=None))
    kill.assert_not_called()


def test_duplicate_background_launch_reuses_monitor(monkeypatch):
    monkeypatch.setattr(desktop, "_read", lambda path: {"pid": 12345})
    monkeypatch.setattr(desktop, "_alive", lambda record: True)
    monkeypatch.setattr(desktop, "wait_ready", lambda: {})
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    monkeypatch.setattr(desktop.webbrowser, "open", Mock())
    desktop.command_background(SimpleNamespace(worker=False, open=True))
    popen.assert_not_called()
    desktop.webbrowser.open.assert_called_once()


def test_windows_update_launches_verified_installer_instead_of_swapping_running_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "fetch_release_asset", lambda asset, tag: b"installer")
    checks = Mock(return_value=True)
    monkeypatch.setattr(cli, "verify_checksum", checks)
    monkeypatch.setattr(cli, "_child_options", lambda: {})
    popen = Mock()
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    cli._update_windows("v4.0.0")
    checks.assert_called_once_with(b"installer", "livepaste-windows-x86_64-setup.exe", tag="v4.0.0")
    assert Path(popen.call_args.args[0][0]).read_bytes() == b"installer"


def test_windows_update_rejects_missing_or_wrong_checksum(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "fetch_release_asset", lambda asset, tag: b"tampered")
    monkeypatch.setattr(cli, "verify_checksum", lambda *a, **k: False)
    popen = Mock()
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    with pytest.raises(SystemExit): cli._update_windows("v4.0.0")
    popen.assert_not_called()


def test_windows_tagged_rollback_lets_installer_manage_restart(monkeypatch):
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "is_frozen", lambda: True)
    update = Mock()
    restart = Mock()
    monkeypatch.setattr(cli, "_update_binary", update)
    monkeypatch.setattr(cli, "cmd_restart", restart)
    cli.cmd_rollback(SimpleNamespace(tag="v3.0.0", list=False, yes=True, restart=True))
    update.assert_called_once_with(None, assume_yes=True, tag="v3.0.0")
    restart.assert_not_called()


def test_windows_login_launcher_quotes_paths_and_registers_current_user_only(monkeypatch, tmp_path):
    import sys
    from contextlib import nullcontext
    registry = {}
    class Registry:
        HKEY_CURRENT_USER = "current-user"
        KEY_SET_VALUE = 2
        REG_SZ = 1
        def CreateKey(self, root, path):
            assert root == self.HKEY_CURRENT_USER
            return nullcontext(path)
        def OpenKey(self, *args): return self.CreateKey(*args[:2])
        def SetValueEx(self, key, name, reserved, kind, value): registry[name] = (value, kind)
        def QueryValueEx(self, key, name): return registry[name]
        def DeleteValue(self, key, name): registry.pop(name)
    monkeypatch.setitem(sys.modules, "winreg", Registry())
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "Test User 报告")
    monkeypatch.setattr(cli, "_command", lambda: [r"C:\Program Files\LivePaste\livepaste.exe"])
    monkeypatch.setattr(autostart.platform, "system", lambda: "Windows")
    autostart.enable()
    script = autostart._windows_launcher().read_text(encoding="utf-16")
    assert '""C:\\Program Files\\LivePaste\\livepaste.exe"" background' in script
    assert "launch.vbs" in registry["LivePaste"][0]
    assert autostart.status() == "enabled"
    autostart.disable()
    assert not registry and not autostart._windows_launcher().exists()
