"""Hosted entrypoint (supervisor/uvicorn target).

The full application lives in the `livepaste` package at the repo root so it
can also be installed with pip and run locally via the `livepaste` CLI.
This wrapper loads the hosted environment (.env with MONGO_URL) and exposes
the same `app` object as before.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(Path(__file__).resolve().parent / ".env")

from livepaste.core import app  # noqa: E402,F401
