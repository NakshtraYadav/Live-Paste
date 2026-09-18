# LivePaste — Agent Workflow Guide

This file tells AI coding agents (Codebuff, Claude Code, Codex, Cursor, etc.)
how to work in this repository: what gstack rules to follow, and which commands
verify each layer of the stack.

> **Note:** the gstack checkout at `./gstack/` is local-only (gitignored). It is
> a reference for the skill definitions. To get the full interactive skill suite
> (`/review`, `/qa`, `/ship`, ...) in Claude Code, install it globally:
> `git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup`
> (requires [Bun](https://bun.sh)).

## gstack digest (v1.87.4.0 — regenerate/re-copy after upgrading gstack)

Behavioral rules from gstack (https://github.com/garrytan/gstack), compressed
for agent hosts without a full skill install. The full skills add workflows,
reviews, and evals on top of these rules.

### Ethos

- **Boil the Ocean** — AI makes completeness cheap, so do the complete thing: tests, edge cases, error paths. Shortcuts need an explicit, recorded decision.
- **Search Before Building** — know what exists before deciding what to build. Don't reinvent (tried-and-true); scrutinize the popular; prize first-principles insight above all.
- **User Sovereignty** — models recommend, the user decides. Cross-model agreement is signal, never permission. Ask before changing the user's stated direction.
- **Build for Yourself** — the specificity of a real problem beats the generality of a hypothetical one.

### The reuse ladder

Before writing new code, stop at the first rung that holds:
1. A helper, util, or pattern already in this repo.
2. The standard library.
3. A native platform feature (CSS over JS, DB constraint over app code).
4. An already-installed dependency — never add a new one for what a few lines cover.

Then build the complete version of what remains. Bug fixes hit root cause,
not symptom: one guard in the shared function beats a guard in every caller.

### Voice

Direct, concrete, builder-to-builder. Name the file, function, command, and
user-visible impact. Short paragraphs; end with what to do. No filler, no
corporate tone, no AI vocabulary.

---

## LivePaste workflow (how to apply gstack here)

LivePaste is an anonymous, real-time collaborative pastebin:
- **Frontend:** React + Vite (`frontend/`), Yjs CRDT over WebSocket, PWA/IndexedDB, WebRTC P2P mode.
- **Backend:** Python (`backend/` + `livepaste/`), FastAPI-style server, packaged via `pyproject.toml`, distributed as standalone binaries and pip.

### gstack skill mapping (when a full skill install is present)

| Task in LivePaste | gstack skill |
|---|---|
| New feature idea (e.g. "add code comments to pastes") | `/office-hours` then `/autoplan` |
| Architecture for CRDT/sync/P2P changes | `/plan-eng-review` |
| UI work on HomePage/PastePage, toolbar, palette | `/plan-design-review` or `/design-review` |
| Fix a sync/CRDT bug or flaky reconnect | `/investigate` |
| PR review before landing | `/review` |
| Browser QA of a running paste | `/qa` (open the local dev server first) |
| Ship a version bump + release | `/ship` |
| Security audit (we hold an audit bar: see `AUDIT.md`) | `/cso` |

### Verify commands (run before declaring any change done)

```bash
# Python backend tests (pytest, tests/ dir)
.venv/bin/python -m pytest tests/ -q

# Frontend tests (vitest)
cd frontend && yarn test

# Frontend production build (catches import/type errors)
cd frontend && yarn build

# Backend packaging sanity
.venv/bin/python -m py_compile livepaste/*.py
```

Verification order: backend tests → frontend tests → frontend build. All three
must pass for cross-cutting changes; the one matching your changed layer is the
minimum bar.

### House rules from the codebase

- Keep the anonymous, no-signup model: never add auth-gated flows by default.
- Security posture is documented in `AUDIT.md`; read the relevant section before
  touching edit-token, password-lock, or upload paths.
- Frontend changes must not break the offline/PWA mirror (IndexedDB) or the
  CRDT merge path — test at least one offline edit + reconnect scenario.
- Version bumps go through `VERSION` + `CHANGELOG.md` together.

## Full gstack

Clone https://github.com/garrytan/gstack and run `./setup` for the full
skill suite (reviews, ship, QA, evals). The digest above is generated — edit
scripts/gen-agents-digest.ts, not this file.
