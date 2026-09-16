# Contributing to LivePaste

Thanks for your interest in improving LivePaste! This guide covers the
development setup, conventions, and release flow.

## Development setup

**Backend** (Python 3.9+):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest httpx   # test deps
```

**Frontend** (Node 20+):

```bash
cd frontend
yarn install
yarn start        # Vite dev server on :3000, proxying /api to :8090
```

Run the live server + tests:

```bash
livepaste start --port 8090        # or: uvicorn livepaste.core:app --port 8090
pytest tests/ -q                   # offline backend suite (no network)
cd frontend && yarn test           # frontend tests (vitest)
```

## Architecture in 60 seconds

```
livepaste/
├── core.py      # FastAPI app: REST + WebSocket + SPA serving
├── storage.py   # SQLite (local) / MongoDB (hosted), same async interface
├── cli.py       # livepaste start | update | rollback | config | autostart
└── static/      # bundled frontend build (vite build → copied here)

frontend/src/
├── pages/       # HomePage (create), PastePage (live editor)
├── components/  # InlineBlocksEditor (block model: text + file cards)
└── hooks/       # useCollab (Yjs CRDT over the WebSocket), useTheme
```

Key concepts:

- **Edit tokens** — pastes carry a secret `editToken`; writes (REST + WS)
  require it. Viewers get read-only rooms. Tokens live in the creator's
  `localStorage`; `#edit=<token>` fragment links hand them to other devices without sending the token to the server. Legacy `?edit=` links remain supported for compatibility.
- **CRDT** — `yupdate` messages relay Yjs binary diffs; the server stores them
  as an ordered list (Yjs updates are commutative, so ordered replay
  converges). Full-text `edit` messages remain the persistence fallback.
- **Revisions** — every edit appends a snapshot (capped at 50), restorable via
  `POST /api/paste/{slug}/restore`.

## Conventions

- Keep `parse -> join` in `InlineBlocksEditor` **lossless** — file tokens are
  plain markdown lines so pastes stay plain-text portable.
- Any storage change must land in **both** backends (SQLite + Mongo) and keep
  the existing method names working.
- Never reject a file by type or name — sanitize only (see
  `sanitize_filename`).
- Backend changes need a pytest; wire-level changes need a case in
  `tests/test_backend.py`.

## Releasing

1. Bump `VERSION` and add a `CHANGELOG.md` entry.
2. Rebuild the bundled frontend:
   ```bash
   cd frontend && VITE_BACKEND_URL="" yarn build
   rm -rf ../livepaste/static && cp -r build ../livepaste/static
   ```
3. Commit, then tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
   — GitHub Actions builds macOS/Linux binaries, generates `SHA256SUMS`,
   and publishes the Release.

## Code of conduct

Be kind. Assume good faith. Security issues: please open a private security
advisory rather than a public issue.
