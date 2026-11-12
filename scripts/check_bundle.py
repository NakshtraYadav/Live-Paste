"""Fail if any shipped asset differs from the freshly built frontend."""
from pathlib import Path
root = Path(__file__).resolve().parent.parent
built, shipped = root / "frontend/build", root / "livepaste/static"
def files(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
if not built.is_dir() or files(built) != files(shipped):
    raise SystemExit("Bundled frontend is stale. Run yarn --cwd frontend sync and commit the complete bundle.")
print("Bundled frontend matches every built asset.")
