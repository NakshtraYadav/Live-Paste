"""Build and exercise a wheel in a clean environment on any supported OS."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import venv

root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=root, check=True)
wheel = max((root / "dist").glob("livepaste-*.whl"), key=lambda item: item.stat().st_mtime)
with tempfile.TemporaryDirectory(prefix="livepaste-clean-") as directory:
    venv.create(directory, with_pip=True)
    python = Path(directory) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", str(wheel)], check=True)
    subprocess.run([sys.executable, str(root / "scripts/smoke_install.py"), "--python", str(python)], check=True)
    subprocess.run([sys.executable, str(root / "scripts/smoke_background.py"), "--python", str(python)], check=True)
