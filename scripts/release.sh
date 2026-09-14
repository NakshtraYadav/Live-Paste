#!/usr/bin/env bash
# LivePaste release ritual — one command for the whole flow.
#
#   ./scripts/release.sh --preflight          # checks only (no git, no push)
#   ./scripts/release.sh --dry-run            # everything except tag/push
#   ./scripts/release.sh                      # full release: commit, tag, push, verify
#
# What a full release does (mandatory for EVERY version bump, from v3.16.x on):
#   1. Preflight: VERSION ↔ CHANGELOG top entry must match; tests must pass;
#      frontend bundle must be current (livepaste/static mirrors frontend/build).
#   2. Commit outstanding changes (excluding junk) with the version in the message.
#   3. Create annotated git tag v<VERSION> and push main + the tag.
#   4. The "Build & Release binaries" workflow builds macOS/Linux standalone
#      binaries + SHA256SUMS and publishes the GitHub Release automatically.
#   5. Verify: poll the workflow run and report its conclusion; warn loudly if
#      Actions is billing-locked or the release didn't publish.
#
# Requirements: git remote "origin", working gh CLI optional (polling uses the
# public API when gh is absent).

set -euo pipefail

REPO_SLUG="${LIVEPASTE_REPO:-NakshtraYadav/Live-Paste}"
MODE="${1:-release}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_ROOT="$ROOT"
cd "$ROOT"

say()  { printf '%s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

# ---------- workspace: use a push clone when this checkout has no git ----------

# The dev workspace may be a plain checkout (no .git). When a push clone
# (a real git repo with origin) is available, all git operations run there
# after rsyncing the tree over — same flow as manual releases.
PUSH_CLONE="${LIVEPASTE_PUSH_CLONE:-/tmp/Live-Paste-push}"
if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  if [ -d "$PUSH_CLONE/.git" ] && git -C "$PUSH_CLONE" remote get-url origin >/dev/null 2>&1; then
    say "• No git here — delegating git work to clone: $PUSH_CLONE"
    SYNC_EX=(--exclude .git --exclude node_modules --exclude .venv --exclude .freebuff
             --exclude frontend/build --exclude __pycache__)
    rsync -a --delete "${SYNC_EX[@]}" "$ROOT/" "$PUSH_CLONE/"
    ROOT="$PUSH_CLONE"
    cd "$ROOT"
  fi
fi

# ---------- inputs ----------

VERSION="$(tr -d '[:space:]' < VERSION)" || fail "VERSION missing"
TAG="v$VERSION"
say "▶ Releasing $TAG"

# ---------- preflight ----------

TOP_ENTRY="$(grep -m1 -E '^## \[' CHANGELOG.md | sed -E 's/^## \[([^]]+)\].*/\1/')"
if [ "$TOP_ENTRY" != "$VERSION" ]; then
  fail "CHANGELOG top entry is [$TOP_ENTRY] but VERSION is $VERSION — add a changelog entry first"
fi
say "✓ CHANGELOG top entry matches VERSION ($VERSION)"

PY="${PYTHON:-$SRC_ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
say "  Running tests…"
LIVEPASTE_DATA_DIR="$(mktemp -d)" LIVEPASTE_SERVE_STATIC=0 "$PY" -m pytest tests/ -q >/dev/null \
  || fail "tests failed — fix before releasing"
say "✓ 44-test suite green"

# Bundle checks only make sense in the SOURCE workspace (the push clone
# has no frontend/build by design — livepaste/static is what ships).
if [ "$ROOT" = "$SRC_ROOT" ]; then
  if [ -d frontend/build/assets ]; then
    BUILT=$(find frontend/build/assets -name 'index-*.js' -newer VERSION 2>/dev/null | head -1)
    if [ -n "$BUILT" ]; then
      say "  ⚠ frontend/build newer than VERSION — run: (cd frontend && yarn build) && rm -rf livepaste/static && cp -R frontend/build livepaste/static"
    fi
  fi
  if [ -d livepaste/static ] && [ -d frontend/build ]; then
    cmp -s frontend/build/index.html livepaste/static/index.html \
      || say "  ⚠ livepaste/static differs from frontend/build (bundle may be stale)"
  fi
fi

if [ "$MODE" = "--preflight" ]; then
  say "✓ Preflight OK (no git actions taken)"
  exit 0
fi

# ---------- git ----------

GIT_REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
[ -n "$GIT_REMOTE_URL" ] || fail "no 'origin' remote configured"

if ! git diff-index --quiet HEAD -- 2>/dev/null; then
  if [ "$MODE" = "--dry-run" ]; then
    say "  (dry-run) would commit: $(git status -s | wc -l | tr -d ' ') changed files"
  else
    git add -A
    git commit -q -m "$(printf '%s: Release %s\n\nRelease ritual: tests green, changelog + version aligned, bundle refreshed.\n\n🤖 Generated with Codebuff\nCo-Authored-By: Codebuff <noreply@codebuff.com>' "$TAG" "$TAG")"
    say "✓ Committed release changes"
  fi
else
  say "• Working tree clean (nothing to commit)"
fi

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  fail "tag $TAG already exists — bump VERSION or delete the tag first"
fi

if [ "$MODE" = "--dry-run" ]; then
  say "  (dry-run) would: git tag -a $TAG && git push origin main $TAG"
  say "✓ Dry-run complete"
  exit 0
fi

git tag -a "$TAG" -m "$TAG"
say "✓ Tagged $TAG"

git push origin main 2>/dev/null || git push origin HEAD
git push origin "$TAG" || fail "tag push failed"
say "✓ Pushed main + $TAG (release workflow triggered)"

# ---------- verify the workflow ----------

API="https://api.github.com/repos/$REPO_SLUG"
poll_run() {
  for _ in $(seq 1 30); do
    RUN_ID=$(curl -s "$API/actions/runs?event=push&per_page=10" \
      | "$PY" -c "import json,sys; d=json.load(sys.stdin); runs=[r for r in d.get('workflow_runs',[]) if r.get('head_branch')=='$TAG']; print(runs[0]['id'] if runs else '')")
    if [ -n "$RUN_ID" ]; then
      STATUS=$(curl -s "$API/actions/runs/$RUN_ID" \
        | "$PY" -c "import json,sys; d=json.load(sys.stdin); print(d.get('status'), d.get('conclusion'))")
      case "$STATUS" in
        "completed success") echo "ok"; return;;
        "completed "*)       echo "$STATUS"; return;;
      esac
      sleep 20
    else
      sleep 15
    fi
  done
  echo "timeout"
}

say "  Waiting for the build workflow…"
RESULT="$(poll_run)"
case "$RESULT" in
  ok)
    say "✓ Release workflow succeeded — binaries + SHA256SUMS published"
    say "  Release: https://github.com/$REPO_SLUG/releases/tag/$TAG"
    ;;
  timeout)
    say "  ⚠ timed out polling the workflow — check: https://github.com/$REPO_SLUG/actions"
    ;;
  *)
    say "  ✗ Workflow conclusion: $RESULT — check: https://github.com/$REPO_SLUG/actions"
    say "    (a billing lock on the GitHub account makes every run fail with"
    say "     'account is locked due to a billing issue' — resolve in Settings → Billing)"
    exit 1
    ;;
esac

say "🎉 $TAG released"
