"""LivePaste command-line interface.

    livepaste start     Run the server (local + LAN access)
    livepaste update    Update to the latest version from GitHub
    livepaste version   Show installed version
"""

import os
import sys
import json
import socket
import argparse
import subprocess
import urllib.request

from . import __version__

AUTHOR = "Nakshtra Yadav"

# ---------------------------------------------------------------------------
# Set this to your public GitHub repository ("owner/repo") once it exists.
# It can also be overridden at runtime:  export LIVEPASTE_REPO="owner/repo"
# ---------------------------------------------------------------------------
DEFAULT_REPO_SLUG = "NakshtraYadav/Live-Paste"

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".livepaste", "config")

# ANSI styling (disabled when stdout is not a terminal)
if sys.stdout.isatty():
    TEAL, DIM, BOLD, GREEN, RESET = (
        "\033[38;5;37m", "\033[2m", "\033[1m", "\033[38;5;42m", "\033[0m",
    )
else:
    TEAL = DIM = BOLD = GREEN = RESET = ""


def read_config():
    """Read simple KEY=VALUE pairs written by install.sh (optional)."""
    cfg = {}
    try:
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except Exception:
        pass
    return cfg


def write_config(updates: dict):
    cfg = read_config()
    cfg.update(updates)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        for k, v in cfg.items():
            f.write(f"{k}={v}\n")
    return cfg


def repo_slug():
    return os.environ.get("LIVEPASTE_REPO") or read_config().get("REPO") or DEFAULT_REPO_SLUG


def get_lan_ip():
    """Best-effort detection of this machine's LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))  # no packets actually sent (UDP connect)
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def parse_version(v):
    try:
        return tuple(int(p) for p in v.strip().split("."))
    except Exception:
        return None


def fetch_latest_version(timeout=3, channel=None):
    slug = repo_slug()
    if slug.startswith("CHANGE_ME"):
        return None
    ref = channel if channel and channel != "stable" else None
    branches = (ref, "main", "master") if ref else ("main", "master")
    for branch in branches:
        url = f"https://raw.githubusercontent.com/{slug}/{branch}/VERSION"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    return None


def fetch_release_asset(asset_name, timeout=300):
    """Download a release asset (follows 'latest' redirect). Returns bytes."""
    slug = repo_slug()
    url = f"https://github.com/{slug}/releases/latest/download/{asset_name}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def _print_progress(count, block_size, total):
    if total > 0:
        pct = min(100, count * block_size * 100 // total)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        sys.stdout.write(f"\r  {bar} {pct:3d}%")
        sys.stdout.flush()


def verify_checksum(data, asset_name, channel=None):
    """Verify SHA256 against the release's SHA256SUMS file.

    Returns True when verified, False on mismatch, None when no checksum file
    was published (older releases) — in that case we proceed but warn.
    """
    import hashlib

    try:
        sums = fetch_release_asset("SHA256SUMS", timeout=30)
    except Exception:
        print("  ⚠  No SHA256SUMS published for this release — skipping verification")
        return None
    expected = None
    for line in sums.decode().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == asset_name:
            expected = parts[0].strip().lower()
            break
    if expected is None:
        print("  ⚠  Checksum for this asset missing from SHA256SUMS — skipping verification")
        return None
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        print("\n  ✗ CHECKSUM MISMATCH — download corrupted or tampered. Aborting.")
        print(f"    expected {expected}")
        print(f"    actual   {actual}")
        return False
    print("\r  ✓ SHA256 verified" + " " * 30)
    return True


def backup_binary(target: str) -> str:
    """Copy the current binary to <target>.old for `livepaste rollback`."""
    import shutil

    old = f"{target}.old"
    try:
        shutil.copy2(target, old)
    except Exception:
        pass
    return old


def check_for_update(quiet=False):
    latest = fetch_latest_version()
    if not latest:
        return None
    current_t, latest_t = parse_version(__version__), parse_version(latest)
    if current_t and latest_t and latest_t > current_t:
        print()
        print(f"  ⬆  Update available: v{__version__} → v{latest}")
        print("     Run:  livepaste update")
        print()
        return latest
    if not quiet:
        print(f"  ✓  You are on the latest version (v{__version__})")
    return None


def cmd_start(args):
    cfg = read_config()
    if args.data_dir:
        os.environ["LIVEPASTE_DATA_DIR"] = args.data_dir
    elif cfg.get("DATA_DIR"):
        os.environ.setdefault("LIVEPASTE_DATA_DIR", cfg["DATA_DIR"])

    # Session mode: temporary by default in local mode — pastes/images are
    # wiped on graceful exit AND on the next start (covers force-kills).
    keep_data = args.keep_data or cfg.get("KEEP_DATA") == "1"
    if not os.environ.get("MONGO_URL"):
        os.environ["LIVEPASTE_EPHEMERAL"] = "0" if keep_data else "1"

    host = args.host
    port = args.port

    lan_ip = get_lan_ip()
    width = 52
    line = "─" * width

    print()
    print(f"  {TEAL}{BOLD}╭{line}╮{RESET}")
    print(f"  {TEAL}{BOLD}│{RESET}  {BOLD}⚡ LivePaste v{__version__}{RESET}  {DIM}made by {AUTHOR}{RESET}")
    print(f"  {TEAL}{BOLD}├{line}┤{RESET}")
    print(f"  {TEAL}{BOLD}│{RESET}  Local:    {GREEN}http://localhost:{port}{RESET}")
    if lan_ip and host in ("0.0.0.0", lan_ip):
        print(f"  {TEAL}{BOLD}│{RESET}  Network:  {GREEN}http://{lan_ip}:{port}{RESET}  {DIM}(share on your Wi-Fi){RESET}")
    data_dir = os.environ.get("LIVEPASTE_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".livepaste")
    if not os.environ.get("MONGO_URL"):
        print(f"  {TEAL}{BOLD}│{RESET}  Data:     {DIM}{data_dir}{RESET}")
        if keep_data:
            print(f"  {TEAL}{BOLD}│{RESET}  Session:  {DIM}persistent (pastes are kept){RESET}")
        else:
            print(f"  {TEAL}{BOLD}│{RESET}  Session:  {DIM}temporary — clears on exit (--keep-data to keep){RESET}")
    print(f"  {TEAL}{BOLD}╰{line}╯{RESET}")
    print(f"  {DIM}Press Ctrl+C to stop.{RESET}")
    print()

    if not args.no_update_check:
        try:
            _auto_update_watchdog()
        except Exception:
            pass
        try:
            check_for_update(quiet=True)
        except Exception:
            pass

    import uvicorn
    from .core import app  # direct object import — works in frozen binaries too

    uvicorn.run(app, host=host, port=port, log_level="warning")


def is_frozen() -> bool:
    """True when running as a standalone (PyInstaller) binary."""
    return bool(getattr(sys, "frozen", False))


def binary_asset_name():
    """Release asset name for this OS/CPU, or None if unsupported."""
    import platform

    system = platform.system()
    machine = platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    if not arch:
        return None
    if system == "Darwin":
        return f"livepaste-macos-{arch}"
    if system == "Linux":
        return f"livepaste-linux-{arch}"
    return None


def _update_binary(latest, channel=None, assume_yes=False):
    """Self-update a standalone binary from the latest GitHub release."""
    import stat
    import tempfile

    asset = binary_asset_name()
    if not asset:
        print("✗ No prebuilt binary for this platform. Reinstall from GitHub instead.")
        sys.exit(1)
    target = os.path.realpath(sys.executable)
    if not assume_yes:
        answer = input(f"Update to v{latest or 'latest'}? [Y/n] ").strip().lower()
        if answer and answer not in ("y", "yes"):
            print("Update cancelled.")
            return
    print(f"  Downloading v{latest or 'latest'} …")
    try:
        data = fetch_release_asset(asset)
    except Exception as e:
        print(f"\n✗ Download failed: {e}")
        sys.exit(1)
    verdict = verify_checksum(data, asset, channel)
    if verdict is False:
        sys.exit(1)
    backup_binary(target)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".livepaste-new-")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, os.stat(tmp_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp_path, target)
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        print(f"✗ Could not replace the binary: {e}")
        sys.exit(1)
    print(f"✓ Updated to v{latest or 'latest'}. Previous version kept at {os.path.basename(target)}.old")
    print("  Restart `livepaste start` to use it. Roll back anytime: livepaste rollback")


def cmd_update(args):
    slug = repo_slug()
    if slug.startswith("CHANGE_ME"):
        print("No GitHub repository configured yet.")
        print('Set it with:  export LIVEPASTE_REPO="owner/repo"')
        sys.exit(1)
    channel = args.channel or read_config().get("CHANNEL")
    latest = fetch_latest_version(channel=channel)
    current_t = parse_version(__version__)
    latest_t = parse_version(latest) if latest else None
    if args.check:
        if not latest:
            print("Could not reach GitHub to check for updates.")
            sys.exit(1)
        if latest_t and current_t and latest_t > current_t:
            print(f"Update available: v{__version__} → v{latest}")
            sys.exit(0)
        print(f"Up to date (v{__version__}{f', channel: {channel}' if channel else ''}).")
        sys.exit(0)
    if latest_t and current_t and latest_t <= current_t and not args.force:
        print(f"Already on the latest version (v{__version__}).")
        return
    if is_frozen():
        _update_binary(latest, channel, assume_yes=args.yes)
        return
    target = f"git+https://github.com/{slug}.git"
    if channel and channel != "stable":
        target = f"git+https://github.com/{slug}.git@{channel}"
    print(f"Updating LivePaste from {target} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", target]
    )
    if result.returncode == 0:
        print(f"✓ Updated successfully{f' to v{latest}' if latest else ''}. Restart `livepaste start` to use it.")
    else:
        print("✗ Update failed — see pip output above.")
        sys.exit(result.returncode)


def cmd_rollback(args):
    if not is_frozen():
        print("Rollback is for standalone binary installs. pip users: reinstall a pinned version:")
        print(f'  pip install "git+https://github.com/{repo_slug()}.git@v<version>"')
        sys.exit(1)
    target = os.path.realpath(sys.executable)
    old = f"{target}.old"
    if not os.path.exists(old):
        print("No previous version found (nothing rolled back yet).")
        sys.exit(1)
    import shutil
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".livepaste-rb-")
    with os.fdopen(tmp_fd, "wb") as out, open(old, "rb") as src:
        shutil.copyfileobj(src, out)
    os.chmod(tmp_path, os.stat(old).st_mode)
    os.replace(tmp_path, target)
    os.remove(old)
    print("✓ Rolled back to the previous version. Restart `livepaste start`.")


def _auto_update_watchdog():
    """Background auto-update: download + verify + stage the binary, then swap
    in if the staged file has been stable for a day. Best-effort, never blocks."""
    try:
        if not is_frozen() or read_config().get("AUTO_UPDATE") != "1":
            return
        marker = os.path.join(os.path.expanduser("~"), ".livepaste", "last_autoupdate")
        if os.path.exists(marker):
            import time as _t

            if _t.time() - os.path.getmtime(marker) < 86400:
                return  # checked within the last day
        latest = fetch_latest_version(timeout=3)
        current_t, latest_t = parse_version(__version__), parse_version(latest) if latest else None
        if not latest_t or not current_t or latest_t <= current_t:
            return
        asset = binary_asset_name()
        if not asset:
            return
        data = fetch_release_asset(asset)
        if verify_checksum(data, asset) is False:
            return
        target = os.path.realpath(sys.executable)
        backup_binary(target)
        import stat as _stat
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".livepaste-auto-")
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, os.stat(tmp_path).st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)
        os.replace(tmp_path, target)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as f:
            f.write(latest)
        print(f"  ⬆  Auto-updated to v{latest} — takes effect on next restart.")
    except Exception:
        pass  # auto-update must never break startup


def cmd_version(args):
    print(f"livepaste v{__version__}  {DIM}— made by {AUTHOR}{RESET}")
    try:
        check_for_update(quiet=False)
    except Exception:
        pass


CONFIG_KEYS = {
    "port": ("PORT", lambda v: str(int(v))),
    "data-dir": ("DATA_DIR", lambda v: os.path.abspath(os.path.expanduser(v))),
    "keep-data": ("KEEP_DATA", lambda v: "1" if v.lower() in ("on", "1", "true", "yes") else "0"),
    "repo": ("REPO", str),
    "channel": ("CHANNEL", str),
    "auto-update": ("AUTO_UPDATE", lambda v: "1" if v.lower() in ("on", "1", "true", "yes") else "0"),
}


def cmd_config(args):
    if not args.key:
        cfg = read_config()
        print(f"  {BOLD}LivePaste configuration{RESET}  {DIM}({CONFIG_PATH}){RESET}")
        for label, (key, _) in CONFIG_KEYS.items():
            val = cfg.get(key, "")
            print(f"    {label:<10} {val or DIM + '(default)' + RESET}")
        print(f"\n  Change with:  {BOLD}livepaste config <key> <value>{RESET}   (keys: {', '.join(CONFIG_KEYS)})")
        return
    key = args.key.lower()
    if key not in CONFIG_KEYS:
        print(f"Unknown key '{args.key}'. Valid keys: {', '.join(CONFIG_KEYS)}")
        sys.exit(1)
    if args.value is None:
        val = read_config().get(CONFIG_KEYS[key][0], "")
        print(val or "(default)")
        return
    cfg_key, normalize = CONFIG_KEYS[key]
    try:
        value = normalize(args.value)
    except Exception:
        print(f"Invalid value for {key}: {args.value}")
        sys.exit(1)
    write_config({cfg_key: value})
    print(f"{GREEN}✓{RESET} {key} set to {BOLD}{value}{RESET}")
    if key == "port":
        print(f"  Takes effect the next time you run {BOLD}livepaste start{RESET}.")


def cmd_autostart(args):
    from . import autostart

    try:
        if args.action == "enable":
            print(autostart.enable())
        elif args.action == "disable":
            print(autostart.disable())
        else:
            print(f"Autostart: {autostart.status()}")
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="livepaste",
        description=f"LivePaste — share text & code on your local network in real time. Made by {AUTHOR}.",
    )
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Start the LivePaste server")
    p_start.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LIVEPASTE_PORT") or read_config().get("PORT") or 8090),
    )
    p_start.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0 = LAN accessible)")
    p_start.add_argument("--data-dir", default=None, help="Where to store pastes (default ~/.livepaste)")
    p_start.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep pastes/images between sessions (default: cleared on exit)",
    )
    p_start.add_argument("--no-update-check", action="store_true", help="Skip the GitHub update check")
    p_start.set_defaults(func=cmd_start)

    p_update = sub.add_parser("update", help="Update LivePaste from GitHub")
    p_update.add_argument("--force", action="store_true", help="Reinstall even if already up to date")
    p_update.add_argument("--check", action="store_true", help="Check for updates without installing")
    p_update.add_argument("--channel", default=None, help="Update channel: stable (default) or a branch/tag like beta")
    p_update.add_argument("-y", "--yes", action="store_true", help="Assume yes; skip the confirmation prompt")
    p_update.set_defaults(func=cmd_update)

    p_rollback = sub.add_parser("rollback", help="Restore the previous binary version")
    p_rollback.set_defaults(func=cmd_rollback)

    p_config = sub.add_parser("config", help="View or change settings (port, data-dir, keep-data)")
    p_config.add_argument("key", nargs="?", help="Setting name: port | data-dir | keep-data | repo")
    p_config.add_argument("value", nargs="?", help="New value (omit to show current)")
    p_config.set_defaults(func=cmd_config)

    p_auto = sub.add_parser("autostart", help="Run LivePaste automatically at login")
    p_auto.add_argument("action", choices=["enable", "disable", "status"])
    p_auto.set_defaults(func=cmd_autostart)

    p_version = sub.add_parser("version", help="Show version and check for updates")
    p_version.set_defaults(func=cmd_version)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
