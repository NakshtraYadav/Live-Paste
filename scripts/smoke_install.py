"""Exercise an installed wheel or standalone binary, with isolated home/data.

python scripts/smoke_install.py --python /path/to/clean/venv/bin/python
python scripts/smoke_install.py --binary /path/to/livepaste
"""
import argparse
import base64
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

import httpx
from pycrdt import Doc, Text
from websockets.sync.client import connect


def receive(ws, kind):
    for _ in range(40):
        value = json.loads(ws.recv(timeout=5))
        if value.get("type") == kind:
            return value
    raise AssertionError(f"No {kind} response")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--python")
    group.add_argument("--binary")
    args = parser.parse_args()
    command = [str(Path(args.binary).resolve())] if args.binary else [str(Path(args.python).resolve()), "-m", "livepaste"]
    # Do not resolve a venv interpreter symlink: doing so escapes its environment.
    if args.python: command = [os.path.abspath(args.python), "-m", "livepaste"]
    with tempfile.TemporaryDirectory(prefix="livepaste-install-smoke-") as directory:
        home = Path(directory)
        data = home / "custom data"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = dict(os.environ, HOME=directory, USERPROFILE=directory, LIVEPASTE_DATA_DIR=str(data), LIVEPASTE_SERVE_STATIC="1")
        for key in ("PYTHONPATH", "MONGO_URL", "REDIS_URL", "LIVEPASTE_REQUIRE_REDIS", "LIVEPASTE_EPHEMERAL"):
            env.pop(key, None)
        server = None
        try:
            with open(home / "server-output.log", "wb") as log:
                server = subprocess.Popen(command + ["start", "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(data), "--keep-data", "--no-update-check"], cwd=home, env=env, stdout=log, stderr=log)
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=10) as client:
                for _ in range(600):
                    if server.poll() is not None:
                        raise RuntimeError((home / "server-output.log").read_text())
                    try:
                        if client.get("/api/health").status_code == 200: break
                    except httpx.RequestError: pass
                    time.sleep(.1)
                else: raise AssertionError("Installed program never became healthy:\n" + (home / "server-output.log").read_text())
                assert client.get("/").status_code == 200
                worker = client.get("/runner-javascript.js")
                assert worker.status_code == 200 and "new Function" in worker.text
                assert "'unsafe-eval'" in worker.headers["content-security-policy"]
                assert "'unsafe-eval'" not in client.get("/").headers["content-security-policy"]
                p = client.post("/api/paste", json={"content":"installed base"}).json()
                auth = "lp-auth." + base64.urlsafe_b64encode(json.dumps({"token":p["editToken"],"clientId":"installed-owner"}).encode()).decode().rstrip("=")
                with connect(f"ws://127.0.0.1:{port}/api/ws/{p['slug']}", subprotocols=[auth]) as ws:
                    initial = receive(ws, "init")
                    document = Doc({"content":Text()})
                    for item in initial["yUpdatesB64"]: document.apply_update(base64.b64decode(item))
                    document["content"].insert(len(str(document["content"])), " and synced edit")
                    ws.send(json.dumps({"type":"sync","sheetId":"main","requestId":"installed-smoke","updateB64":base64.b64encode(document.get_update()).decode()}))
                    assert receive(ws,"sync-ack")["requestId"] == "installed-smoke"
                content = client.get(f"/api/paste/{p['slug']}").json()["content"]
                assert content == "installed base and synced edit"
                with connect(f"ws://127.0.0.1:{port}/api/ws/{p['slug']}?clientId=viewer") as ws:
                    assert receive(ws,"init")["canEdit"] is False
                    ws.send(json.dumps({"type":"s:open","sheetId":"main"}))
                    assert receive(ws,"s:state")["content"] == content
                payload = b"download integrity\x00\xff"
                file = client.post(f"/api/paste/{p['slug']}/file",data={"editToken":p["editToken"]},files={"file":("报告.bin",payload,"application/octet-stream")})
                assert file.status_code == 200, file.text
                url = file.json()["url"]
                assert client.get(url).content == payload
                partial = client.get(url,headers={"Range":"bytes=2-5"})
                assert partial.status_code == 206 and partial.content == payload[2:6]
                page = client.post(f"/api/paste/{p['slug']}/sheets", json={"editToken":p["editToken"],"content":"extra page"}).json()
                assert client.get(f"/api/paste/{p['slug']}/sheets/{page['sheetId']}").json()["content"] == "extra page"
                restarted = subprocess.run(command + ["restart"],cwd=home,env=env,capture_output=True,text=True,timeout=120)
                assert restarted.returncode == 0, restarted.stdout + restarted.stderr
                server.wait(timeout=10)
                assert client.get(f"/api/paste/{p['slug']}").json()["content"] == content
                assert client.get(url).content == payload
                print("Installed program passed: static assets, isolated runner policy, CRDT sync, viewer page reads, Unicode binary upload/download, ranges, custom-data restart and persistence.")
        finally:
            # Signal only processes recorded by this isolated test installation.
            record = home / ".livepaste/livepaste.pid.json"
            if record.exists():
                subprocess.run(command + ["stop"], cwd=home, env=env, capture_output=True, timeout=60)
            if server and server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
            for _ in range(50):
                if not record.exists(): break
                time.sleep(.1)


if __name__ == "__main__":
    main()
