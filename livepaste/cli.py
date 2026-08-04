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


def fetch_latest_version(timeout=3):
    slug = repo_slug()
    if slug.startswith("CHANGE_ME"):
        return None
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{slug}/{branch}/VERSION"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    return None


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
            check_for_update(quiet=True)
        except Exception:
            pass

    import uvicorn

    uvicorn.run("livepaste.core:app", host=host, port=port, log_level="warning")


def cmd_update(args):
    slug = repo_slug()
    if slug.startswith("CHANGE_ME"):
        print("No GitHub repository configured yet.")
        print('Set it with:  export LIVEPASTE_REPO="owner/repo"')
        sys.exit(1)
    latest = fetch_latest_version()
    current_t = parse_version(__version__)
    latest_t = parse_version(latest) if latest else None
    if latest_t and current_t and latest_t <= current_t and not args.force:
        print(f"Already on the latest version (v{__version__}).")
        return
    target = f"git+https://github.com/{slug}.git"
    print(f"Updating LivePaste from {target} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", target]
    )
    if result.returncode == 0:
        print(f"✓ Updated successfully{f' to v{latest}' if latest else ''}. Restart `livepaste start` to use it.")
    else:
        print("✗ Update failed — see pip output above.")
        sys.exit(result.returncode)


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
    p_update.set_defaults(func=cmd_update)

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
