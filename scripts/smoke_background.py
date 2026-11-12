"""Exercise single-instance background start, crash recovery, restart and stop."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import httpx

parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--python")
group.add_argument("--binary")
args = parser.parse_args()
command = [os.path.abspath(args.binary)] if args.binary else [os.path.abspath(args.python), "-m", "livepaste"]

with tempfile.TemporaryDirectory(prefix="livepaste-background-") as directory:
    home = Path(directory)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    env = dict(os.environ, HOME=directory, USERPROFILE=directory, LIVEPASTE_PORT=str(port), LIVEPASTE_DATA_DIR=str(home/"saved data"), LIVEPASTE_SERVE_STATIC="1")
    for key in ("PYTHONPATH", "MONGO_URL", "REDIS_URL", "LIVEPASTE_REQUIRE_REDIS", "LIVEPASTE_EPHEMERAL", "LIVEPASTE_SUPERVISED"):
        env.pop(key, None)
    def run(*arguments):
        result = subprocess.run(command + list(arguments), cwd=home, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result
    def launch():
        try: return json.loads((home/".livepaste/livepaste.pid.json").read_text())
        except (OSError, ValueError): return {}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}",timeout=3,trust_env=False) as client:
        try:
            run("background")
            first = launch()
            assert first["supervised"] and first["control_token"]
            paste = client.post("/api/paste",json={"content":"survives a process crash"}).json()
            run("background")
            assert launch()["pid"] == first["pid"], "Second launch started a competing server"
            # This PID was created by this test's isolated background worker.
            os.kill(first["pid"], signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
            until = time.monotonic() + 120
            while time.monotonic() < until:
                try:
                    if launch().get("pid") not in (None,first["pid"]) and client.get("/api/health").status_code == 200: break
                except httpx.RequestError: pass
                time.sleep(.2)
            else: raise AssertionError("Background worker did not recover the crashed server")
            assert client.get(f"/api/paste/{paste['slug']}").json()["content"] == "survives a process crash"
            recovered = launch()["pid"]
            run("restart")
            assert launch()["pid"] != recovered
            assert client.get(f"/api/paste/{paste['slug']}").json()["content"] == "survives a process crash"
            run("stop")
            assert not launch()
            assert "stopped" in run("status").stdout
            time.sleep(2)
            assert not launch(), "Stop unexpectedly restarted the server"
            print("Background program passed: duplicate launches, crash recovery, saved-data persistence, managed restart and graceful stop.")
        except BaseException:
            for name in ("server.log","background.log"):
                file = home/".livepaste"/name
                if file.exists(): print(file.read_text(errors="replace")[-10000:])
            raise
        finally:
            run("stop")
