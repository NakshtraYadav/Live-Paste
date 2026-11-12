"""LivePaste command-line interface.

    livepaste start     Run the server (local + LAN access)
    livepaste update    Update to the latest version from GitHub
    livepaste rollback  List released versions / roll back to one
    livepaste restart   Restart a running server (applies pending updates)
    livepaste version   Show installed version
"""

import os
import sys
import json
import time
import signal
import socket
import argparse
import subprocess
import urllib.request
import platform

from . import __version__

AUTHOR = "Nakshtra Yadav"


def _is_windows():
    return platform.system() == "Windows"


def _command():
    return [sys.executable] if is_frozen() else [sys.executable, "-m", "livepaste"]


def _child_options():
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)} if _is_windows() else {"start_new_session": True}


def _safe_urlopen(req, timeout):
    """urllib opener restricted to http(s) schemes.

    Guards against file:/, ftp:/ and custom-scheme URLs (bandit B310 /
    CWE-22 class). All call sites in this module build https URLs from a
    fixed host, so this is defense in depth — the check is authoritative.
    """
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"URL scheme not allowed: {url!r}")
    # Scheme already validated above — this is the enforcement point.
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310

# ---------------------------------------------------------------------------
# Set this to your public GitHub repository ("owner/repo") once it exists.
# It can also be overridden at runtime:  export LIVEPASTE_REPO="owner/repo"
# ---------------------------------------------------------------------------
DEFAULT_REPO_SLUG = "NakshtraYadav/Live-Paste"

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".livepaste", "config")
HISTORY_PATH = os.path.join(os.path.expanduser("~"), ".livepaste", "history.json")
PID_PATH = os.path.join(os.path.expanduser("~"), ".livepaste", "livepaste.pid")
SERVER_LOG = os.path.join(os.path.expanduser("~"), ".livepaste", "server.log")

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
    if not channel or channel == "stable":
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{slug}/releases/latest", headers={"Accept": "application/vnd.github+json"})
            with _safe_urlopen(req, timeout=timeout) as response:
                tag = json.load(response).get("tag_name", "")
            value = tag.removeprefix("v") if hasattr(tag, "removeprefix") else tag.lstrip("v")
            return value if parse_version(value) else None
        except Exception:
            return None
    try:
        with _safe_urlopen(f"https://raw.githubusercontent.com/{slug}/{channel}/VERSION", timeout=timeout) as response:
            value = response.read().decode().strip()
        return value if parse_version(value) else None
    except Exception:
        return None


def fetch_release_asset(asset_name, timeout=300, tag=None):
    """Download a release asset. Without `tag` follows the 'latest' redirect;
    with `tag` (e.g. "v3.3.0") fetches that release's asset. Returns bytes."""
    slug = repo_slug()
    if tag:
        url = f"https://github.com/{slug}/releases/download/{tag}/{asset_name}"
    else:
        url = f"https://github.com/{slug}/releases/latest/download/{asset_name}"
    with _safe_urlopen(url, timeout=timeout) as resp:
        return resp.read()


def fetch_release_info(timeout=4):
    """List recent GitHub releases (falling back to git tags): [{tag, name,
    date, summary}].

    Powers `livepaste rollback --list` — users see every released version
    with a one-line summary and can roll back to any of them by tag.
    v3.16.0: when the repo publishes releases, use them; otherwise fall back
    to the git tag list (tag-pinned pip installs work from bare tags too).
    Best-effort: returns [] when offline.
    """
    slug = repo_slug()
    if slug.startswith("CHANGE_ME"):
        return []
    url = f"https://api.github.com/repos/{slug}/releases?per_page=20"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with _safe_urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        data = None
    if data:
        out = []
        for rel in data:
            body = (rel.get("body") or "").strip()
            summary = next((ln.strip().lstrip("#- *") for ln in body.splitlines() if ln.strip()), "")
            out.append(
                {
                    "tag": rel.get("tag_name") or "",
                    "name": rel.get("name") or "",
                    "date": (rel.get("published_at") or "")[:10],
                    "summary": summary[:110],
                }
            )
        return out
    # Fall back to plain git tags (repos without GitHub Releases objects)
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{slug}/tags?per_page=30",
            headers={"Accept": "application/vnd.github+json"},
        )
        with _safe_urlopen(req, timeout=timeout) as resp:
            tags = json.load(resp)
        return [
            {"tag": t.get("name") or "", "name": "", "date": "", "summary": "(git tag)"}
            for t in tags
            if (t.get("name") or "").startswith("v")
        ]
    except Exception:
        return []


# ---------------- version history ledger (v3.5.0) ----------------
def load_history():
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def record_history(version, action, summary="", tag=None):
    """Append a version-change entry: updates, rollbacks and installs.

    The ledger is what `livepaste rollback --list` shows for versions that
    were actually run on this machine, merged with the GitHub release list.
    """
    entry = {
        "version": str(version),
        "tag": tag or (f"v{version}" if version else None),
        "action": action,  # update | rollback | install
        "summary": (summary or "")[:160],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        hist = load_history()
        hist.insert(0, entry)
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "w") as f:
            json.dump(hist[:200], f, indent=1)
    except Exception:
        pass  # the ledger must never break an update
    return entry


def release_summary_for(version):
    """One-line summary for a version from its GitHub release notes."""
    for rel in fetch_release_info():
        if rel["tag"] in (f"v{version}", str(version)):
            return rel["summary"]
    return ""


def _print_progress(count, block_size, total):
    if total > 0:
        pct = min(100, count * block_size * 100 // total)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        sys.stdout.write(f"\r  {bar} {pct:3d}%")
        sys.stdout.flush()


def verify_checksum(data, asset_name, channel=None, tag=None):
    """Verify SHA256 against the release's SHA256SUMS file.

    Returns True when verified, False on mismatch, None when no checksum file
    was published (older releases) — in that case we proceed but warn.
    """
    import hashlib

    try:
        sums = fetch_release_asset("SHA256SUMS", timeout=30, tag=tag)
    except Exception:
        print("  ⚠  No SHA256SUMS published — refusing an unverified update")
        return False
    expected = None
    for line in sums.decode().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == asset_name:
            expected = parts[0].strip().lower()
            break
    if expected is None:
        print("  ⚠  Checksum missing — refusing an unverified update")
        return False
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

    # Persistent storage is the safe default. Ephemeral mode is an explicit
    # opt-in because startup purges can destroy a shared data directory.
    ephemeral = bool(args.ephemeral or (not args.keep_data and cfg.get("KEEP_DATA") == "0"))
    keep_data = not ephemeral
    if not os.environ.get("MONGO_URL"):
        os.environ["LIVEPASTE_EPHEMERAL"] = "1" if ephemeral else "0"

    effective_data_dir = os.environ.get("LIVEPASTE_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".livepaste")
    os.environ["LIVEPASTE_DATA_DIR"] = os.path.abspath(os.path.expanduser(effective_data_dir))
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
    if lan_ip and host in ("0.0.0.0", lan_ip):  # nosec B104 - comparison, not a bind
        print(f"  {TEAL}{BOLD}│{RESET}  Network:  {GREEN}http://{lan_ip}:{port}{RESET}  {DIM}(share on your Wi-Fi){RESET}")
    data_dir = os.environ.get("LIVEPASTE_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".livepaste")
    if not os.environ.get("MONGO_URL"):
        print(f"  {TEAL}{BOLD}│{RESET}  Data:     {DIM}{data_dir}{RESET}")
        if keep_data:
            print(f"  {TEAL}{BOLD}│{RESET}  Session:  {DIM}persistent (pastes are kept){RESET}")
        else:
            print(f"  {TEAL}{BOLD}│{RESET}  Session:  {DIM}EPHEMERAL — clears on exit/start (explicit opt-in){RESET}")
    print(f"  {TEAL}{BOLD}╰{line}╯{RESET}")
    print(f"  {DIM}Press Ctrl+C to stop.{RESET}")
    print()

    if not args.no_update_check:
        import threading
        def background_update_check():
            try:
                _auto_update_watchdog()
                check_for_update(quiet=True)
            except Exception:
                pass
        threading.Thread(target=background_update_check, daemon=True).start()

    import uvicorn
    from .core import app  # direct object import — works in frozen binaries too

    # Bind before recording ownership: a failed second start must not replace
    # the running server's launch record.
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError as exc:
            raise SystemExit(f"Could not start on {host}:{port}: {exc}")
        listener.listen(128)
        launch = {"pid": os.getpid(), "host": host, "port": port,
                  "data_dir": os.path.abspath(os.path.expanduser(data_dir)), "ephemeral": ephemeral,
                  "process_started": _process_started(os.getpid()),
                  "supervised": os.environ.get("LIVEPASTE_SUPERVISED") == "1"}
        import secrets
        launch["control_token"] = secrets.token_hex(24)
        os.makedirs(os.path.dirname(PID_PATH), exist_ok=True)
        _atomic_json(PID_PATH + ".json", launch)
        _atomic_json(PID_PATH + f".{port}.json", launch)
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))
        try:
            if _is_windows():
                # socket.fromfd (used by uvicorn's fd option) is Unix-only.
                # Pass the socket object, and use an authenticated local stop
                # file because Windows SIGTERM skips Python cleanup entirely.
                import threading
                server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
                finished = threading.Event()
                def watch_stop():
                    while not finished.wait(.2):
                        try:
                            with open(PID_PATH + f".{os.getpid()}.stop") as source:
                                requested = json.load(source)
                            if requested.get("token") == launch["control_token"]:
                                server.should_exit = True
                                return
                        except (OSError, ValueError):
                            pass
                watcher = threading.Thread(target=watch_stop, daemon=True)
                watcher.start()
                try:
                    server.run(sockets=[listener])
                finally:
                    finished.set()
                    watcher.join(timeout=1)
            else:
                uvicorn.run(app, fd=listener.fileno(), host=host, port=port, log_level="warning")
        finally:
            current = _read_launch()
            if current.get("pid") == os.getpid():
                for path in (PID_PATH, PID_PATH + ".json", PID_PATH + f".{port}.json"):
                    try: os.unlink(path)
                    except FileNotFoundError: pass
            try: os.unlink(PID_PATH + f".{os.getpid()}.stop")
            except FileNotFoundError: pass


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
    if system == "Windows" and arch == "x86_64":
        return "livepaste-windows-x86_64.exe"
    return None


def _staged_update_path():
    """Marker file naming a downloaded update waiting to be applied on restart."""
    return os.path.join(os.path.expanduser("~"), ".livepaste", "staged_update.json")


def mark_pending_restart(version, action="update", summary=""):
    """Remember that a new binary is on disk and the server should restart."""
    try:
        os.makedirs(os.path.dirname(_staged_update_path()), exist_ok=True)
        with open(_staged_update_path(), "w") as f:
            json.dump({"version": str(version), "action": action, "summary": (summary or "")[:160], "ts": time.time()}, f)
    except Exception:
        pass


def pop_pending_restart():
    try:
        with open(_staged_update_path()) as f:
            info = json.load(f)
        os.unlink(_staged_update_path())
        return info
    except Exception:
        return None


def _write_binary(target, data):
    """Atomically replace the binary at `target` with `data`."""
    import stat
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".livepaste-new-")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, os.stat(tmp_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _update_binary(latest, channel=None, assume_yes=False, tag=None):
    """Self-update a standalone binary from a GitHub release.

    With `tag` (e.g. "v3.3.0") installs that exact release; otherwise latest.
    Records the change in the version ledger and marks a pending restart so a
    running server can pick it up automatically.
    """
    asset = binary_asset_name()
    if not asset:
        print("✗ No prebuilt binary for this platform. Reinstall from GitHub instead.")
        sys.exit(1)
    target = os.path.realpath(sys.executable)
    label = tag or latest or "latest"
    if not assume_yes:
        answer = input(f"Update to v{label} ? [Y/n] ".replace("vlatest", "latest")).strip().lower()
        if answer and answer not in ("y", "yes"):
            print("Update cancelled.")
            return
    print(f"  Downloading v{label} …")
    if _is_windows():
        return _update_windows(tag or f"v{latest}")
    try:
        data = fetch_release_asset(asset, tag=tag or f"v{latest}")
    except Exception as e:
        print(f"\n✗ Download failed: {e}")
        sys.exit(1)
    verdict = verify_checksum(data, asset, channel, tag=tag or f"v{latest}")
    if verdict is False:
        sys.exit(1)
    backup_binary(target)
    try:
        _write_binary(target, data)
    except Exception as e:
        print(f"✗ Could not replace the binary: {e}")
        sys.exit(1)
    version = (tag or latest or "").lstrip("v")
    record_history(version, "update", summary=release_summary_for(version), tag=tag)
    mark_pending_restart(version, "update", release_summary_for(version))
    print(f"✓ Updated to v{version or label}. Previous version kept at {os.path.basename(target)}.old")
    print("  Restart `livepaste start` to use it — or run: livepaste restart")
    print("  Roll back anytime: livepaste rollback (add --list to see versions)")


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
    if not latest and (not channel or channel == "stable"):
        raise SystemExit("No published stable release is available. Your installation was not changed.")
    if latest_t and current_t and latest_t <= current_t and not args.force:
        print(f"Already on the latest version (v{__version__}).")
        return
    if is_frozen():
        _update_binary(latest, channel, assume_yes=args.yes)
        return
    target = f"git+https://github.com/{slug}.git"
    if channel and channel != "stable":
        target = f"git+https://github.com/{slug}.git@{channel}"
    elif latest:
        # v3.16.0: pin updates to the release TAG (not main HEAD) so pip
        # installs are symmetric with rollback — update lands exactly on the
        # released version, never on untagged drift.
        target = f"git+https://github.com/{slug}.git@v{latest}"
    print(f"Updating LivePaste from {target} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--force-reinstall", target]
    )
    if result.returncode == 0:
        if latest:
            record_history(latest, "update", release_summary_for(latest), tag=f"v{latest}")
        mark_pending_restart(latest or "?", "update", release_summary_for(latest or ""))
        print(f"✓ Updated successfully{f' to v{latest}' if latest else ''}. Restart `livepaste start` to use it — or run: livepaste restart")
    else:
        print("✗ Update failed — see pip output above.")
        sys.exit(result.returncode)


def _print_rollback_list():
    """Released versions + summaries, merged with this machine's install ledger.

    Works in every install mode — it is read-only (GitHub + local ledger).
    """
    print(f"  {BOLD}Released versions{RESET}  {DIM}({repo_slug()}){RESET}")
    hist = {h["version"]: h for h in load_history()}
    for rel in fetch_release_info():
        tag = rel["tag"]
        ver = tag.lstrip("v")
        ran = hist.get(ver)
        marker = ""
        if ver == __version__:
            marker = f"  {GREEN}← running{RESET}"
        elif ran:
            marker = f"  {DIM}(was installed {ran['ts']}){RESET}"
        print(f"  {BOLD}{tag}{RESET}  {DIM}{rel['date']}{RESET}{marker}")
        if rel["summary"]:
            print(f"      {rel['summary']}")
    if is_frozen():
        print(f"\n  {DIM}Install one: livepaste rollback v<version>{RESET}")
    else:
        print(f"\n  {DIM}Install one: livepaste rollback v<version>  (pip installs are switched in place){RESET}")


def _pip_prev_version_from_ledger():
    """Most recent OTHER version this machine has run (pip-mode default target)."""
    current = str(__version__)
    for entry in load_history():
        ver = str(entry.get("version") or "")
        if ver and ver != current:
            return ver
    return None


def _pip_install_tag(tag):
    """pip-install LivePaste pinned to a git tag in THIS environment.

    Returns the pip exit code. --no-deps keeps shared dependencies (fastapi,
    uvicorn, …) untouched — a rollback switches the app, not the stack.
    """
    target = f"git+https://github.com/{repo_slug()}.git@{tag}"
    print(f"  Installing LivePaste {tag} …")
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--force-reinstall", "--no-deps", target]
    ).returncode


def _is_editable_install():
    """True when running from a git checkout (pip install -e / direct run)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.isdir(os.path.join(repo_root, ".git"))


def cmd_rollback(args):
    """Roll back to a previous version — in ANY install mode (v3.16.0).

    Standalone binary:
    - `livepaste rollback`          → restore the .old binary (instant, offline)
    - `livepaste rollback v3.3.0`   → download + verify + install that exact tag

    pip / pipx installs:
    - `livepaste rollback`          → reinstall the previous version (from the
                                      local version ledger), right in this venv
    - `livepaste rollback v3.3.0`   → pip-install that exact git tag

    All modes:
    - `livepaste rollback --list`   → show released versions with summaries
    """
    # --list: read-only, works everywhere
    if getattr(args, "list", False):
        _print_rollback_list()
        return

    # ---------------- standalone binary mode ----------------
    if is_frozen():
        target = os.path.realpath(sys.executable)
        # rollback to a specific tag → same path as an update, but pinning the tag
        if _is_windows() and not getattr(args, "tag", None):
            raise SystemExit("Choose a released Windows installer: livepaste rollback v<version>")
        if getattr(args, "tag", None):
            tag = args.tag if args.tag.startswith("v") else f"v{args.tag}"
            current = f"v{__version__}"
            if tag == current:
                print(f"Already running {tag}.")
                return
            _update_binary(None, assume_yes=args.yes, tag=tag)
            if _is_windows():
                # The installer owns stop/swap/relaunch. A second concurrent
                # restart here would race its attempt to replace locked files.
                return
            record_history(__version__, "rollback", summary=f"rolled back from {tag}")
            if args.restart:
                cmd_restart(args)
            return

        # classic .old swap — instant and offline
        old = f"{target}.old"
        if not os.path.exists(old):
            print("No previous version found next to the binary.")
            print("Install a specific released version instead:")
            print("  livepaste rollback --list            # see versions")
            print("  livepaste rollback v3.3.0            # install that tag")
            sys.exit(1)
        import shutil
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".livepaste-rb-")
        with os.fdopen(tmp_fd, "wb") as out, open(old, "rb") as src:
            shutil.copyfileobj(src, out)
        os.chmod(tmp_path, os.stat(old).st_mode)
        os.replace(tmp_path, target)
        os.remove(old)
        record_history(__version__, "rollback", summary="restored .old binary")
        mark_pending_restart(__version__, "rollback", "restored previous binary")
        print("✓ Rolled back to the previous version. Restart `livepaste start` — or run: livepaste restart")
        return

    # ---------------- pip / pipx mode (v3.16.0: real rollback) ----------------
    if getattr(args, "tag", None):
        tag = args.tag if args.tag.startswith("v") else f"v{args.tag}"
        if tag == f"v{__version__}":
            print(f"Already running {tag}.")
            return
    else:
        prev = _pip_prev_version_from_ledger()
        if not prev:
            print("No previous version recorded on this machine yet.")
            print("Pick one explicitly:")
            print("  livepaste rollback --list            # see released versions")
            print("  livepaste rollback v3.3.0            # install that tag")
            sys.exit(1)
        tag = f"v{prev}"
        if tag == f"v{__version__}":
            print(f"Already running {tag}.")
            return
    if _is_editable_install():
        print("You are running from a git checkout, so there is nothing to roll back:")
        print("the code on disk IS the running code. To test another version:")
        print(f'  git checkout {tag or "v<version>"}   # in {repo_slug()}')
        return
    if not getattr(args, "yes", False):
        answer = input(f"Roll back to {tag} ? [Y/n] ").strip().lower()
        if answer and answer not in ("y", "yes"):
            print("Rollback cancelled.")
            return
    rc = _pip_install_tag(tag)
    if rc != 0:
        print("✗ Rollback failed — see pip output above.")
        sys.exit(rc)
    record_history(tag.lstrip("v"), "rollback", summary=f"pip rollback to {tag}")
    mark_pending_restart(tag.lstrip("v"), "rollback", f"pip rollback to {tag}")
    print(f"✓ Rolled back to {tag} in this environment.")
    print("  Restart `livepaste start` to use it — or run: livepaste restart")
    print("  (Any running server keeps the old code until it restarts.)")
    if getattr(args, "restart", False):
        cmd_restart(args)
    return


def _atomic_json(path, value):
    import tempfile
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".livepaste-state-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(value, out)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def _read_launch(port=None):
    try:
        with open(PID_PATH + (f".{port}.json" if port else ".json")) as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _process_started(pid):
    if _is_windows():
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle: return ""
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259: return ""
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)): return ""
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="], capture_output=True, text=True, timeout=5).stdout.strip()
        state, _, stamp = result.partition(" ")
        return "" if state.startswith("Z") else stamp.strip()
    except Exception:
        return ""


def _pid_is_livepaste(pid):
    try:
        import shlex
        if _is_windows():
            command = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}').CommandLine"], capture_output=True, text=True, timeout=10).stdout.strip()
            args = [arg.strip('"') for arg in shlex.split(command, posix=False)]
        else:
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout.strip()
            args = shlex.split(command)
        module = args[args.index("-m") + 1] if "-m" in args else ""
        import ntpath
        return (module == "livepaste" and "start" in args) or (module == "uvicorn" and "livepaste.core:app" in args) or (bool(args) and any(ntpath.basename(arg).lower() in ("livepaste", "livepaste.exe") for arg in args[:2]) and "start" in args)
    except (ValueError, IndexError, OSError):
        return False


def _clear_launch(launch):
    pid = launch.get("pid")
    for port in (None, launch.get("port")):
        if port is None and _read_launch().get("pid") != pid: continue
        if port is not None and _read_launch(port).get("pid") != pid: continue
        try: os.unlink(PID_PATH + (f".{port}.json" if port is not None else ".json"))
        except FileNotFoundError: pass
    try:
        with open(PID_PATH) as source: same = source.read().strip() == str(pid)
        if same: os.unlink(PID_PATH)
    except FileNotFoundError: pass
    try: os.unlink(PID_PATH + f".{pid}.stop")
    except FileNotFoundError: pass


def _stop_launch(launch):
    pid = launch.get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        raise RuntimeError("No verified server process to stop")
    stamp = launch.get("process_started")
    if not _pid_is_livepaste(pid) or (stamp and _process_started(pid) != stamp):
        return
    if _is_windows():
        if not launch.get("control_token"):
            raise RuntimeError("This legacy Windows process has no safe stop control; close its own terminal first")
        _atomic_json(PID_PATH + f".{pid}.stop", {"token": launch["control_token"]})
    else:
        os.kill(pid, signal.SIGTERM)
    for _ in range(200):
        if not _process_started(pid) or (stamp and _process_started(pid) != stamp):
            _clear_launch(launch)
            return
        time.sleep(.1)
    raise RuntimeError("The server did not stop; no replacement was started")


def _update_windows(tag):
    from pathlib import Path
    asset = "livepaste-windows-x86_64-setup.exe"
    data = fetch_release_asset(asset, tag=tag)
    if verify_checksum(data, asset, tag=tag) is False:
        raise SystemExit("Installer checksum verification failed")
    directory = Path.home() / ".livepaste" / "updates" / tag
    directory.mkdir(parents=True, exist_ok=True)
    installer = directory / asset
    installer.write_bytes(data)
    subprocess.Popen([str(installer), "/SILENT", "/NORESTART"], **_child_options())
    print(f"Verified {tag} installer started; it will preserve your data and restart LivePaste.")


def cmd_restart(args):
    cfg = read_config()
    explicit_port = getattr(args, "port", None)
    launch = _read_launch(explicit_port)
    port = int(getattr(args, "port", None) or launch.get("port") or os.environ.get("LIVEPASTE_PORT") or cfg.get("PORT") or 8090)
    host = launch.get("host") or "0.0.0.0"  # nosec B104 - LAN sharing is the documented default
    data_dir = launch.get("data_dir") or os.environ.get("LIVEPASTE_DATA_DIR") or cfg.get("DATA_DIR") or os.path.join(os.path.expanduser("~"), ".livepaste")
    pid = launch.get("pid")
    if not pid and not explicit_port:
        try:
            with open(PID_PATH) as source: pid = int(source.read().strip())
        except (OSError, ValueError): pid = None
    if pid and (not _pid_is_livepaste(pid) or (launch.get("process_started") and _process_started(pid) != launch["process_started"])):
        pid = None
    if pid == os.getpid():
        raise SystemExit("Refusing to restart this command's own process.")
    if pid:
        if _is_windows() or launch.get("supervised"):
            _stop_launch(launch)
            if launch.get("supervised"):
                from .desktop import wait_ready
                wait_ready(previous_pid=pid)
                pop_pending_restart()
                print(f"✓ Background server restarted on port {port}")
                return
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                try: os.kill(pid, 0)
                except OSError: break
                if not _pid_is_livepaste(pid): break
                time.sleep(0.1)
            else:
                raise SystemExit("The server did not stop; no new process was started.")
    else:
        # No ownership evidence: never terminate a process just because it uses
        # a port. A pending update may start an otherwise stopped server.
        if not os.path.exists(_staged_update_path()):
            print("No verified running LivePaste server found. Start one: livepaste start")
            return
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.dirname(SERVER_LOG), exist_ok=True)
    env = dict(os.environ, LIVEPASTE_DATA_DIR=data_dir)
    if is_frozen():
        # A replacement one-file process needs its own extraction directory;
        # the old bootloader removes its directory when the server exits.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (repo_root, env.get("PYTHONPATH"))))
    cmd = ([sys.executable] if is_frozen() else [sys.executable, "-m", "livepaste"]) + ["start", "--host", host, "--port", str(port), "--data-dir", data_dir, "--no-update-check"]
    cmd.append("--ephemeral" if launch.get("ephemeral", cfg.get("KEEP_DATA") == "0") else "--keep-data")
    with open(SERVER_LOG, "ab", buffering=0) as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env,
                                cwd=data_dir, **_child_options())
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit(f"The restarted server exited. See {SERVER_LOG}")
        try:
            address = "::1" if ":" in host else ("127.0.0.1" if host == "0.0.0.0" else host)  # nosec B104 - health probe uses loopback
            address = f"[{address}]" if ":" in address else address
            with _safe_urlopen(f"http://{address}:{port}/api/health", timeout=1) as response:
                if response.status == 200:
                    pop_pending_restart()
                    print(f"✓ Server restarted on {host}:{port} (pid {proc.pid})")
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise SystemExit(f"Restart did not become healthy. See {SERVER_LOG}")


def _auto_update_watchdog():
    """Background auto-update: download + verify + stage the binary, then swap
    in if the staged file has been stable for a day. Best-effort, never blocks."""
    try:
        if _is_windows() or not is_frozen() or read_config().get("AUTO_UPDATE") != "1":
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
        data = fetch_release_asset(asset, tag=f"v{latest}")
        if verify_checksum(data, asset, tag=f"v{latest}") is False:
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
        mark_pending_restart(latest, "update", release_summary_for(latest))
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
    if _is_windows():
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
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
    p_start.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0 = LAN accessible)")  # nosec B104 - LAN sharing is the product
    p_start.add_argument("--data-dir", default=None, help="Where to store pastes (default ~/.livepaste)")
    mode = p_start.add_mutually_exclusive_group()
    mode.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep pastes/images between sessions (default: persistent)",
    )
    mode.add_argument(
        "--ephemeral",
        action="store_true",
        help="Explicitly clear local pastes on startup and graceful exit",
    )
    p_start.add_argument("--no-update-check", action="store_true", help="Skip the GitHub update check")
    p_start.set_defaults(func=cmd_start)

    from . import desktop
    p_background = sub.add_parser("background", help="Run in the background and recover after crashes")
    p_background.add_argument("--open", action="store_true", help="Open the editor in your browser")
    p_background.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p_background.set_defaults(func=desktop.command_background)
    p_stop = sub.add_parser("stop", help="Stop this user's LivePaste server and background monitor")
    p_stop.set_defaults(func=desktop.command_stop)
    p_status = sub.add_parser("status", help="Show server and background monitor status")
    p_status.set_defaults(func=desktop.command_status)

    p_update = sub.add_parser("update", help="Update LivePaste from GitHub")
    p_update.add_argument("--force", action="store_true", help="Reinstall even if already up to date")
    p_update.add_argument("--check", action="store_true", help="Check for updates without installing")
    p_update.add_argument("--channel", default=None, help="Update channel: stable (default) or a branch/tag like beta")
    p_update.add_argument("-y", "--yes", action="store_true", help="Assume yes; skip the confirmation prompt")
    p_update.set_defaults(func=cmd_update)

    p_rollback = sub.add_parser("rollback", help="Roll back to a previous version (.old binary or a tagged release)")
    p_rollback.add_argument("tag", nargs="?", default=None, help="Install a specific released version, e.g. v3.3.0")
    p_rollback.add_argument("--list", action="store_true", help="List released versions with summaries")
    p_rollback.add_argument("-y", "--yes", action="store_true", help="Assume yes; skip the confirmation prompt")
    p_rollback.add_argument("--restart", action="store_true", help="Restart the server after rolling back")
    p_rollback.set_defaults(func=cmd_rollback)

    p_restart = sub.add_parser("restart", help="Restart the server, applying any pending update/rollback")
    p_restart.add_argument("--port", type=int, default=None, help="Port to restart on (default: configured or 8090)")
    p_restart.set_defaults(func=cmd_restart)

    p_config = sub.add_parser("config", help="View or change settings (port, data-dir, keep-data)")
    p_config.add_argument("key", nargs="?", help="Setting name: port | data-dir | keep-data | repo")
    p_config.add_argument("value", nargs="?", help="New value (omit to show current)")
    p_config.set_defaults(func=cmd_config)

    p_auto = sub.add_parser("autostart", help="Run LivePaste automatically at login")
    p_auto.add_argument("action", choices=["enable", "disable", "status"])
    p_auto.set_defaults(func=cmd_autostart)

    p_version = sub.add_parser("version", help="Show version and check for updates")
    p_version.set_defaults(func=cmd_version)

    args = parser.parse_args(["background", "--open"] if _is_windows() and len(sys.argv) == 1 else None)
    if not args.command:
        parser.print_help()
        sys.exit(0)
    # Auto-restart marker: when `start` launches and an update/rollback was
    # staged (e.g. by `livepaste update` or the auto-update watchdog), apply it
    # immediately instead of asking the user to restart manually.
    if args.command == "start":
        pending = pop_pending_restart()
        if pending:
            print(f"  ⬆  Applying {pending.get('action')} to v{pending.get('version')} — {pending.get('summary') or 'staged update'}")
    args.func(args)


if __name__ == "__main__":
    main()
