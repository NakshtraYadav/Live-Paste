"""LivePaste — share text & code on your local network in real time."""

from pathlib import Path


def _detect_version() -> str:
    # Standalone binary: version baked in at build time by the CI workflow
    try:
        from ._version import __version__ as v

        return v
    except ImportError:
        pass
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
