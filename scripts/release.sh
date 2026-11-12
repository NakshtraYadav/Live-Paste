#!/usr/bin/env bash
# Validate locally; publish only an already-reviewed, clean main commit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="${1:---preflight}"
case "$MODE" in --preflight|--dry-run|--publish) ;; *) echo "Usage: $0 [--preflight|--dry-run|--publish]" >&2; exit 2;; esac
PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
NODE="${NODE:-$(command -v node)}"
YARN="$(command -v yarn)"
VERSION="$(tr -d '[:space:]' < VERSION)"
TAG="v$VERSION"
TOP="$(sed -nE 's/^## \[([^]]+)\].*/\1/p' CHANGELOG.md | head -1)"
[ "$TOP" = "$VERSION" ] || { echo "VERSION and CHANGELOG disagree" >&2; exit 1; }
"$PY" -m pytest tests/ -q
"$NODE" "$YARN" --cwd frontend test
"$NODE" "$YARN" --cwd frontend build
"$PY" scripts/check_bundle.py
"$PY" -m py_compile livepaste/*.py
[ "$MODE" != "--preflight" ] || { echo "Preflight passed; no Git or publishing actions taken."; exit 0; }
git rev-parse --git-dir >/dev/null
[ -z "$(git status --porcelain)" ] || { echo "Commit and review the intended changes before publishing." >&2; exit 1; }
[ "$(git branch --show-current)" = "main" ] || { echo "Publish from the reviewed main branch." >&2; exit 1; }
! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || { echo "Tag already exists: $TAG" >&2; exit 1; }
[ "$MODE" != "--dry-run" ] || { echo "Would tag and atomically push main and $TAG."; exit 0; }
git tag -a "$TAG" -m "$TAG"
git push --atomic origin main "$TAG"
echo "Tag pushed. Release is complete only after all platform builds pass and assets publish."
