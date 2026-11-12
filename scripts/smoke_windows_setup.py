"""Run on a disposable Windows runner: install, upgrade, sign-in launch, uninstall."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import winreg
import httpx

installer = str(Path(sys.argv[1]).resolve())
run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,run_key) as key:
        winreg.QueryValueEx(key,"LivePaste")
except FileNotFoundError:
    pass
else:
    raise SystemExit("Run this installer smoke test on a disposable Windows account without an existing LivePaste startup entry")

with tempfile.TemporaryDirectory(prefix="livepaste-setup-") as directory:
    home = Path(directory)
    app = home/"Installed Program"
    data = home/"Saved Data"
    (home/".livepaste").mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]
    (home/".livepaste/config").write_text(f"PORT={port}\nDATA_DIR={data}\nKEEP_DATA=1\n")
    env = dict(os.environ,HOME=directory,USERPROFILE=directory)
    for name in ("PYTHONPATH","LIVEPASTE_DATA_DIR","LIVEPASTE_PORT","MONGO_URL","REDIS_URL","LIVEPASTE_REQUIRE_REDIS","LIVEPASTE_EPHEMERAL","LIVEPASTE_SUPERVISED"):
        env.pop(name,None)
    def execute(command):
        result = subprocess.run(command,env=env,cwd=home,capture_output=True,text=True,encoding="utf-8",timeout=180)
        assert result.returncode == 0, result.stdout+result.stderr
    def install():
        execute([installer,"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART",f"/DIR={app}",f"/LOG={home/'setup.log'}"])
    def ready(client):
        for _ in range(400):
            try:
                if client.get("/api/health").status_code == 200: return
            except httpx.RequestError: pass
            time.sleep(.2)
        raise AssertionError("Installed background server did not start")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}",timeout=3,trust_env=False) as client:
        try:
            install(); ready(client)
            assert client.get("/api/version").json()["version"] == Path(__file__).resolve().parents[1].joinpath("VERSION").read_text().strip()
            p=client.post("/api/paste",json={"content":"installer upgrade keeps this paste"}).json()
            uploaded=client.post(f"/api/paste/{p['slug']}/file",data={"editToken":p["editToken"]},files={"file":("报告.bin",b"setup\x00\xff","application/octet-stream")}).json()
            install(); ready(client)
            assert client.get(f"/api/paste/{p['slug']}").json()["content"] == "installer upgrade keeps this paste"
            assert client.get(uploaded["url"]).content == b"setup\x00\xff"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,run_key) as key:
                startup,_kind=winreg.QueryValueEx(key,"LivePaste")
                assert "launch.vbs" in startup
            execute([str(app/"livepaste.exe"),"stop"])
            # Exercise precisely the startup script registered for sign-in.
            execute([str(Path(os.environ["SystemRoot"])/"System32/wscript.exe"),"//B","//Nologo",str(home/".livepaste/launch.vbs")])
            ready(client)
            execute([str(app/"unins000.exe"),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"])
            assert (data/"livepaste.db").exists(), "Uninstall removed the user's saved database"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,run_key) as key:
                try: winreg.QueryValueEx(key,"LivePaste")
                except FileNotFoundError: pass
                else: raise AssertionError("Uninstall left the sign-in entry enabled")
            print("Windows setup passed: one-click install, background startup, upgrade with file persistence, sign-in launcher, uninstall and data retention.")
        except BaseException:
            for file in (home/"setup.log",home/".livepaste/server.log",home/".livepaste/background.log"):
                if file.exists(): print(file.read_text(errors="replace")[-15000:])
            raise
        finally:
            if (app/"livepaste.exe").exists():
                execute([str(app/"livepaste.exe"),"autostart","disable"])
                execute([str(app/"livepaste.exe"),"stop"])
