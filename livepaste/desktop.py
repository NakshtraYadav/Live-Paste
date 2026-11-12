"""Per-user background runner with crash recovery and a single-instance lock."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser


def _path(name):
    return Path.home() / ".livepaste" / name


def _read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _alive(record):
    from .cli import _process_started
    pid = record.get("pid")
    return isinstance(pid, int) and bool(record.get("process_started")) and _process_started(pid) == record["process_started"]


def _base_url():
    from .cli import read_config
    port = int(os.environ.get("LIVEPASTE_PORT") or read_config().get("PORT") or 8090)
    return f"http://127.0.0.1:{port}"


def _healthy():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(_base_url() + "/api/health", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def wait_ready(previous_pid=None, timeout=75):
    from .cli import _read_launch
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        launch = _read_launch()
        if launch.get("pid") != previous_pid and _alive(launch) and _healthy():
            return launch
        time.sleep(.2)
    raise RuntimeError(f"LivePaste did not become ready. See {_path('server.log')}")


def _environment():
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (root, env.get("PYTHONPATH"))))
    return env


def command_background(args):
    from .cli import _command, _child_options, _read_launch
    if args.worker:
        return _worker()
    directory = _path("")
    directory.mkdir(parents=True, exist_ok=True)
    if not _alive(_read(_path("background.json"))):
        if _alive(_read_launch()):
            print("LivePaste is already running in a terminal. Stop it before enabling the background monitor.")
            if args.open: webbrowser.open(_base_url())
            return
        with _path("background.log").open("ab") as log:
            subprocess.Popen(_command() + ["background", "--worker"], cwd=directory,
                             env=_environment(), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, **_child_options())
    wait_ready()
    if args.open: webbrowser.open(_base_url())
    print(f"LivePaste is running in the background: {_base_url()}")


def _lock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _worker():
    from .cli import _atomic_json, _command, _child_options, _process_started, _read_launch, _stop_launch
    import secrets
    directory = _path("")
    directory.mkdir(parents=True, exist_ok=True)
    # OS locks are released after crashes, unlike stale PID files.
    with _path("background.lock").open("a+b") as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b"0"); lock.flush()
        try: _lock(lock)
        except OSError: return
        if _alive(_read_launch()): return
        record = {"pid": os.getpid(), "process_started": _process_started(os.getpid()), "token": secrets.token_hex(24)}
        _atomic_json(str(_path("background.json")), record)
        child = None
        backoff = 1
        next_start = 0
        started = 0
        failed_checks = 0
        try:
            with _path("server.log").open("ab", buffering=0) as log:
                while True:
                    if _read(_path("background.stop")).get("token") == record["token"]:
                        break
                    now = time.monotonic()
                    if child is None or child.poll() is not None:
                        if child is not None:
                            if now - started > 60: backoff = 1
                            next_start = now + backoff
                            backoff = min(backoff * 2, 30)
                            child = None
                        if now >= next_start:
                            env = _environment()
                            env["LIVEPASTE_SUPERVISED"] = "1"
                            child = subprocess.Popen(_command() + ["start", "--keep-data", "--no-update-check"],
                                cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, **_child_options())
                            started = now
                            failed_checks = 0
                    elif now - started > 75:
                        failed_checks = 0 if _healthy() else failed_checks + 1
                        if failed_checks >= 5:
                            launch = _read_launch()
                            if launch.get("supervised") and _alive(launch): _stop_launch(launch)
                            child.wait(timeout=30)
                    time.sleep(1)
        finally:
            launch = _read_launch()
            stopped = launch.get("supervised") and _alive(launch)
            if stopped: _stop_launch(launch)
            if child is not None:
                if child.poll() is None and not stopped:
                    # This Popen is owned by this monitor, including failed
                    # startup before any server launch record was written.
                    child.terminate()
                try: child.wait(timeout=30)
                except subprocess.TimeoutExpired: pass
            if _read(_path("background.json")).get("token") == record["token"]:
                _path("background.json").unlink(missing_ok=True)
                _path("background.stop").unlink(missing_ok=True)


def command_stop(_args=None):
    from .cli import _atomic_json, _read_launch, _stop_launch
    record = _read(_path("background.json"))
    if _alive(record):
        _atomic_json(str(_path("background.stop")), {"token": record["token"]})
        for _ in range(400):
            if not _alive(record): break
            time.sleep(.1)
        else: raise RuntimeError("Background monitor did not stop; see background.log")
    launch = _read_launch()
    if _alive(launch): _stop_launch(launch)
    print("LivePaste stopped. Your saved pastes and files are kept.")


def command_status(_args=None):
    from .cli import _read_launch
    launch = _read_launch()
    running = _alive(launch) and _healthy()
    monitor = _alive(_read(_path("background.json")))
    print(f"Server: {'running' if running else 'stopped'} | Background monitor: {'running' if monitor else 'stopped'}")
    if running: print(_base_url())
