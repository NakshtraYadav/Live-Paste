"""LivePaste — share text & code on your local network in real time."""

from pathlib import Path
import sys


def _detect_version() -> str:
    # A baked version is authoritative only inside a frozen executable.
    if getattr(sys, "frozen", False):
        try:
            from ._version import __version__ as v
            return v
        except ImportError:
            pass
    # A checkout's VERSION belongs to this source, unlike unrelated installed metadata.
    root = Path(__file__).parent.parent
    if (root / "pyproject.toml").is_file() and (root / "VERSION").is_file():
        return (root / "VERSION").read_text().strip()
    # Installed package: read from package metadata
    try:
        from importlib.metadata import version

        return version("livepaste")
    except Exception:
        pass
    # Development checkout: read the VERSION file at the repo root
    try:
        return (Path(__file__).parent.parent / "VERSION").read_text().strip()
    except Exception:
        return "0.0.0"


__version__ = _detect_version()
