"""Run LivePaste automatically at login (macOS launchd / Linux systemd)."""

import os
import sys
import platform
import subprocess
from pathlib import Path

LABEL = "com.nakshtrayadav.livepaste"


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "livepaste.service"


def _log_path() -> Path:
    return Path(os.environ.get("LIVEPASTE_DATA_DIR", Path.home() / ".livepaste")) / "livepaste.log"


def _program_args():
    if getattr(sys, "frozen", False):
        # Standalone binary: sys.executable IS the livepaste binary
        return [sys.executable, "start", "--no-update-check"]
    # Run via the exact interpreter this CLI lives in (works inside the venv)
    return [sys.executable, "-m", "livepaste", "start", "--no-update-check"]


def enable() -> str:
    system = platform.system()
    if system == "Darwin":
        return _enable_macos()
    if system == "Linux":
        return _enable_linux()
    raise RuntimeError(f"Autostart is not supported on {system} yet.")


def disable() -> str:
    system = platform.system()
    if system == "Darwin":
        return _disable_macos()
    if system == "Linux":
        return _disable_linux()
    raise RuntimeError(f"Autostart is not supported on {system} yet.")


def status() -> str:
    system = platform.system()
    if system == "Darwin":
        if not _plist_path().exists():
            return "disabled"
        try:
            out = subprocess.run(
                ["launchctl", "list"], capture_output=True, text=True, timeout=10
            ).stdout
            return "enabled (running)" if LABEL in out else "enabled (not loaded)"
        except Exception:
            return "enabled"
    if system == "Linux":
        if not _unit_path().exists():
            return "disabled"
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-enabled", "livepaste.service"],
                capture_output=True, text=True, timeout=10,
            )
            return f"enabled ({r.stdout.strip() or 'unknown'})"
        except Exception:
            return "enabled"
    return "unsupported"


# ----------------------------- macOS (launchd) -----------------------------
def _enable_macos() -> str:
    args = _program_args()
    args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>
"""
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist)
    # Reload if it was already registered, then load
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    r = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
    if r.returncode != 0 and r.stderr.strip():
        raise RuntimeError(f"launchctl load failed: {r.stderr.strip()}")
    return f"LaunchAgent installed at {path}\nLivePaste will start automatically when you log in."


def _disable_macos() -> str:
    path = _plist_path()
    if path.exists():
        subprocess.run(["launchctl", "unload", "-w", str(path)], capture_output=True)
        path.unlink()
        return "Autostart disabled and LaunchAgent removed."
    return "Autostart was not enabled."


# ----------------------------- Linux (systemd) -----------------------------
def _enable_linux() -> str:
    unit = f"""[Unit]
Description=LivePaste — local network paste sharing
After=network.target

[Service]
ExecStart={' '.join(_program_args())}
Restart=on-failure

[Install]
WantedBy=default.target
"""
    path = _unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=15)
        r = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "livepaste.service"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return (
                f"Service file written to {path}, but systemd could not enable it "
                f"({r.stderr.strip() or 'no user session'}). Enable it manually with:\n"
                "  systemctl --user enable --now livepaste.service"
            )
    except FileNotFoundError:
        return (
            f"Service file written to {path}, but systemctl was not found. "
            "Enable it with your init system, or start LivePaste manually."
        )
    return f"systemd user service installed at {path}\nLivePaste will start automatically when you log in."


def _disable_linux() -> str:
    path = _unit_path()
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "livepaste.service"],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass
    if path.exists():
        path.unlink()
        return "Autostart disabled and service removed."
    return "Autostart was not enabled."
