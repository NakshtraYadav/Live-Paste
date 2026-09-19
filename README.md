# LivePaste

> **Share text and files. Edit together. Instantly.**

LivePaste is an anonymous, real-time collaborative pastebin (dontpad-style). Create a paste, share the link, and everyone with the link can view it live — no accounts, no sign-up, no install. Hand out **edit links** to let people type along: edits sync conflict-free (CRDT) so simultaneous typing just works.

- **Version:** see [`VERSION`](./VERSION) — currently **3.18.0**
- **Release history:** [`CHANGELOG.md`](./CHANGELOG.md)
- **Security audit:** [`AUDIT.md`](./AUDIT.md) (full-stack review and remediation plan) · [`SECURITY_AUDIT_REPORT.md`](./SECURITY_AUDIT_REPORT.md) (empirical v3.17.0 audit with live-probe evidence)
- **Contributing:** [`CONTRIBUTING.md`](./CONTRIBUTING.md)

---

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Feature guide](#feature-guide)
  - [Pages, sharing & privacy](#pages-sharing--privacy)
  - [Editing & collaboration](#editing--collaboration)
  - [Files & media](#files--media)
  - [Offline, P2P & installable app](#offline-p2p--installable-app)
  - [Productivity](#productivity)
- [Self-hosting (CLI)](#self-hosting-cli)
- [Update & rollback system](#update--rollback-system)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [API reference](#api-reference)
- [Security model](#security-model)
- [Development](#development)
- [Releasing a new version](#releasing-a-new-version)

---

## Features

**Core**
- **Instant live links** — random short slugs by default, or pick a custom slug (`/my-notes`)
- **True concurrent editing (CRDT)** — Yjs sync over WebSockets: multiple people type at once with no lost keystrokes
- **Live cursors & presence avatars** — everyone's caret and a colored name tag, Google Docs style
- **Revision history** — every edit snapshotted (last 50), browsable side panel with per-revision diff and one-click restore
- **Syntax highlighting** — Prism-powered highlighting for dozens of languages
- **Dark mode**, line numbers, and a live status bar (lines / chars / size)

**Sharing & privacy**
- **Edit vs. view links** — the link you share is read-only; a secret edit token (stored only in your browser) controls who can edit. Per-user edit grants use server-derived capabilities rather than trusting a public browser ID; click a peer's avatar to grant or revoke their edit rights live. Edit-link and file-upload actions resolve the current capability at action time, so creators remain authorized while the first connection is settling
- **Password lock** — bcrypt-hashed view passwords; the lock applies to every read path (REST, sheets, revisions, WebSocket)
- **Burn-after-read** — paste self-destructs after N distinct viewers
- **Optional expiry** — auto-delete after 1 hour / 1 day / 1 week, or keep forever
- **QR sharing** — scan with a phone to jump straight into the paste
- **Freeze (owner read-only)** — lock a paste so even editors can't change it

**Files & media**
- **Share any file — literally any** — PDFs, zips, videos, `.exe` binaries, files with no extension, unicode/emoji names. Every type accepted (up to 100 MB each, 500 MB per paste), rendered as clean inline cards
- **Inline images** — paste, drop, or upload screenshots; they render right at the cursor with hover controls
- **Video / audio / PDF previews** — play inline instead of a bare download card
- **Voice & screen notes (experimental)** — record mic or screen where the browser supports MediaRecorder; uploads behave like any file, with browser/MIME support varying by platform

**Offline, P2P & installable**
- **Offline-first PWA (supported shell; advanced sync experimental)** — production builds register the service worker and cache the shell; paste data mirrors to IndexedDB, while offline conflict/recovery behavior remains under active browser validation
- **Peer-to-peer LAN mode (experimental)** — document data can flow browser-to-browser over WebRTC; the server brokers the handshake and the normal CRDT path remains the fallback
- **Recovery after server restart** — if an ephemeral server wipes data, the browser offers to restore your local copy

**Productivity**
- **Multiple pages per paste** — a notebook of named sheets, each with its own content, language, and CRDT state; duplicate and reorder pages
- **Runnable pastes (best-effort client-side execution)** — Run button on JavaScript and Python blocks (worker/Pyodide) with structured error output; this is not a server security sandbox
- **Markdown preview** — safe, sanitized rendered preview of markdown pastes
- **Sandboxed HTML preview** — HTML pastes render live in a locked-down iframe
- **Find & replace** (⌘/Ctrl+H) with match count and case toggle
- **Command palette** (⌘/Ctrl+K) — every page, edit, view, and share action from one search box
- **Slash commands** — `/` at line start for a Notion-style insert menu
- **Floating emoji reactions** — react and it drifts up everyone's editor with your name and color
- **Auto language detection** — sensible defaults from content shape

## Support maturity

Core sharing, edit authorization, WebSocket collaboration, files, sheets, password protection, expiry, revisions, and sanitized previews are supported for controlled LAN/self-host use. Offline recovery, P2P, recording, and runnable-code integrations remain experimental or browser-dependent; see [`FEATURE_AUDIT_REPORT.md`](./FEATURE_AUDIT_REPORT.md) and [`PROJECT_PLAN.md`](./PROJECT_PLAN.md) for acceptance criteria and current limitations.

## Quick start

**One-line install** (no Python needed when a binary release exists):

```bash
curl -fsSL https://raw.githubusercontent.com/NakshtraYadav/Live-Paste/main/install.sh | bash
```

Or grab a standalone binary from [Releases](https://github.com/NakshtraYadav/Live-Paste/releases) (`chmod +x livepaste-macos-arm64 && ./livepaste-macos-arm64 start`), or install with pip:

```bash
pip install git+https://github.com/NakshtraYadav/Live-Paste.git
livepaste start
```

```
  ╭────────────────────────────────────────────────────╮
  │  ⚡ LivePaste  made by Nakshtra Yadav
  ├────────────────────────────────────────────────────┤
  │  Local:    http://localhost:8090
  │  Network:  http://192.168.1.23:8090  (share on your Wi-Fi)
  │  Data:     ~/.livepaste
  ╰────────────────────────────────────────────────────╯
```

Open the URL, type, share the link. That's it.

**Persistent by default:** local sessions keep pastes across restarts. For a disposable session, use `livepaste start --ephemeral`; it explicitly clears local data on startup and graceful exit.

## Feature guide

### Pages, sharing & privacy

| Action | How |
| --- | --- |
| Create a paste | Home page → type → **Create live link** |
| Add / duplicate / reorder pages | `+` next to the page tabs; hover a tab for actions; arrows reorder |
| Share read-only link | **Share** menu → *Copy view link* |
| Share edit access | **Share** menu → *Copy edit link* (creator only; works on LAN HTTP too) |
| Grant a specific person edit | Click their presence avatar → *Grant edit* (click again to revoke) |
| Password-protect | Set *View password* at creation; readers unlock once per session |
| Burn after read | Set *Views before self-destruct* at creation |
| Show QR code | **Share** menu → *Show QR code* |
| Freeze a paste | Owner read-only toggle (blocks edits for everyone, incl. you) |

### Editing & collaboration

- **Live cursors & avatars** — ride the same WebSocket as edits (Yjs Awareness); names are editable via the avatar menu.
- **Revisions** — the **History** button opens the side panel: every snapshot with time, size, **Diff** against current, and **Restore**. CRDT edits compact server-side so history stays meaningful (throttled full-text backups, identical snapshots skipped).
- **Reactions** — the smiley button floats an emoji up everyone's screen.

### Files & media

- Drop files anywhere on the editor, paste from clipboard, or use **Add file**.
- Every file type is accepted — unknown extensions and binaries included. Filenames are sanitized; untrusted types (HTML/SVG) download as attachments rather than render, so stored files can't XSS the app.
- Per-paste storage quota: **500 MB** of attachments; the server answers `413` with used/quota details when exceeded.

### Offline, P2P & installable app

- LivePaste is a **PWA**: install it from the browser menu; the service worker caches the shell (`cache-version` bumps each release so updates propagate).
- Edits mirror into **IndexedDB**; go offline, keep typing, and changes merge when the connection returns.
- **P2P mode** (shield toggle in the toolbar, experimental): peers on the same network can sync over WebRTC data channels, with per-sheet signaling topics; the normal server CRDT path remains available as fallback.

### Productivity

- **⌘/Ctrl+K** — command palette: add/duplicate pages, find & replace, previews, history, copy links, fork.
- **⌘/Ctrl+H** — find & replace with match count, case toggle, replace-all.
- **Markdown / HTML preview** — toggle from the toolbar; both render safely (DOMPurify / sandboxed iframe).
- **Run blocks** (best effort, client-side only) — for JS and Python code blocks; output shows inline. This is not a server security sandbox and should not be treated as safe execution of hostile code.

## Self-hosting (CLI)

| Command | Description |
| --- | --- |
| `livepaste start` | Start the server (LAN-accessible by default) |
| `livepaste start --port 9000` | Custom port for this run |
| `livepaste start --ephemeral` | Explicitly clear local pastes on startup and graceful exit |
| `livepaste start --data-dir ~/pastes` | Store data somewhere else |
| `livepaste config` | Show settings (port, data-dir, keep-data) |
| `livepaste config port 9000` | Change the default port permanently |
| `livepaste start --keep-data` | Compatibility alias for persistent storage |
| `livepaste autostart enable` | Start LivePaste automatically at login |
| `livepaste autostart disable` | Remove the login service |
| `livepaste restart` | Restart the running server safely (verified pid, detached relaunch) |
| `livepaste status` | Show whether the server is running |

## Update & rollback system

```bash
livepaste update --check          # dry run — is a new version out?
livepaste update                  # download, verify SHA256, swap binary (.old kept)
livepaste update --channel beta   # track a pre-release channel
livepaste config auto-update on   # check + auto-apply daily in the background
livepaste rollback                # restore the previous version
livepaste rollback --list         # show released versions (with summaries) + install history
livepaste rollback <tag>          # roll back to a specific tagged release
livepaste restart                 # restart after update/rollback, fully detached
```

- Every GitHub Release ships a `SHA256SUMS` file (generated by CI); binary updates refuse to install on checksum mismatch.
- The old binary is kept as `.old`; install history (tags + summaries) is recorded locally so `rollback <tag>` can target any past release.
- **Works in every install mode:** standalone binaries swap the `.old` binary or fetch a pinned tag; **pip/pipx installs are switched in place** (bare `rollback` reinstalls the previous version from the local ledger, `rollback v3.x.y` installs that exact git tag — `--no-deps`, so shared dependencies never move). `update` in pip mode pins to the release tag, so update and rollback are symmetric.
- Running from a git checkout? There's nothing to roll back — the code on disk *is* the running code; the CLI says so and suggests `git checkout v<version>`.
- `livepaste update` offers to restart the server automatically when the binary changed; the relaunch is detached and verified.
- The web UI shows an "update available" banner comparing `/api/version` with the latest GitHub release.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite, Tailwind CSS, shadcn/ui, Prism, cmdk, marked + DOMPurify |
| Backend | FastAPI (Python), WebSockets, pluggable storage layer |
| Storage | Local mode: SQLite + files · Hosted mode: MongoDB + GridFS |
| Realtime | Native WebSockets at `/api/ws/{slug}`, Yjs CRDT, optional y-webrtc P2P (signaling at `/api/webrtc/signaling`) |
| Runtime | Pyodide (in-browser Python), sandboxed JS worker, MediaRecorder, service worker + IndexedDB (offline) |
| Packaging | pip-installable `livepaste` CLI with bundled frontend; standalone binaries via GitHub Actions |

## Project structure

```
/
├── livepaste/             # Installable Python package
│   ├── core.py            # FastAPI app: REST + WebSocket + SPA serving
│   ├── storage.py         # Storage backends (SQLite local / MongoDB hosted)
│   ├── cli.py             # start / update / rollback / restart / config / autostart
│   └── static/            # Bundled frontend build (served by the server)
├── backend/
│   ├── server.py          # Hosted-mode entrypoint (loads .env, exposes app)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/         # HomePage (create), PastePage (live editor)
│   │   ├── components/    # InlineBlocksEditor, MarkdownView, DiffView, shadcn/ui
│   │   ├── hooks/         # useCollab, useOfflineDoc, useP2P, useRecorder, useTheme
│   │   └── lib/           # identity, edit-token store, constants
│   └── package.json
├── tests/                 # Offline pytest suite (TestClient + temp SQLite, <1s)
├── install.sh             # Interactive installer (curl | bash)
├── pyproject.toml         # Package definition
├── VERSION                # Current release version (drives update checks)
├── CHANGELOG.md           # Release history
├── AUDIT.md               # Security audit report
└── README.md
```

## API reference

All routes are prefixed with `/api`.

### REST

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/version` | Server version (drives the web update banner) |
| `POST` | `/api/paste` | Create a paste. Body: `content`, `language`, optional `customSlug`, `expiry` (`1h`\|`1d`\|`1w`\|`never`), `burnAfterViews`, `password` |
| `GET` | `/api/paste/{slug}` | Fetch a paste; `?count_view=true` increments views; `?pw=` for locked pastes |
| `POST` | `/api/paste/{slug}/verify` | Check an edit token → `{canEdit}` |
| `GET` | `/api/paste/{slug}/sheets` | List pages |
| `POST` | `/api/paste/{slug}/sheets` | Add a page (body: `editToken`, `content`, `name`) |
| `GET` | `/api/paste/{slug}/sheets/{id}` | Fetch one page's content (`?pw=` for locked pastes) |
| `PATCH` | `/api/paste/{slug}/sheets/{id}` | Rename a page |
| `DELETE` | `/api/paste/{slug}/sheets/{id}` | Delete a page |
| `POST` | `/api/paste/{slug}/sheets/{id}/duplicate` | Duplicate a page incl. CRDT state |
| `POST` | `/api/paste/{slug}/reorder` | Reorder pages (body: `editToken`, `order`) |
| `GET` | `/api/paste/{slug}/revisions` | List edit snapshots (rev, time, size) |
| `GET` | `/api/paste/{slug}/revisions/{rev}` | Fetch one snapshot's content (`?pw=` for locked pastes) |
| `POST` | `/api/paste/{slug}/restore` | Restore content to a snapshot (body: `editToken`, `content`) |
| `POST` | `/api/paste/{slug}/fork` | Full copy of the paste (content, pages, attachments) → new slug |
| `POST` | `/api/paste/{slug}/file` | Upload **any** file (multipart); enforces the per-paste quota |
| `GET` | `/api/file/{file_id}` | Stream an uploaded file of any type |
| `DELETE` | `/api/file/{file_id}` | Delete an uploaded file (requires edit rights) |
| `POST` | `/api/paste/{slug}/image` | Legacy image-only upload (kept for compatibility) |
| `GET` / `DELETE` | `/api/image/{image_id}` | Legacy aliases of the file endpoints |

### WebSocket

| Endpoint | Description |
| --- | --- |
| `/api/ws/{slug}` | Join a paste room. Query: `?token=<editToken>` to edit, `?pw=<password>` for locked pastes, `?clientId=<id>` for burn dedup. Receives edit/CRDT broadcasts (per-sheet `s:yupdate`), presence, live cursors, reactions, revision restores. Error codes: `not_found`, `password_required`, `read_only`, `too_many_attempts`. |
| `/api/webrtc/signaling` | y-webrtc-compatible signaling relay (`subscribe`/`publish` on `lp:<slug>:<sheet>` topics) for P2P LAN mode. Document data flows browser-to-browser, never through this endpoint. |

### Limits & rules

- Max paste size: **400 KB**; max file size: **100 MB** per file; **500 MB** attachments per paste
- No file type is ever rejected; untrusted types download instead of render
- Reserved slugs (`api`, `ws`, `static`, `new`, `about`, …) cannot be claimed; custom slugs validated, duplicates rejected
- Rate limits (per IP): 30 paste creations/hour, 60 uploads/hour — `X-Forwarded-For` is honored only when `LIVEPASTE_TRUST_PROXY=1`
- View counts are **unique viewers** (per client id): tab refreshes and WebSocket reconnects never inflate the counter
- P2P signaling is bounded to **16 topics per connection**, **64KB frames**, and **120 publishes/minute** per connection
- WebSocket connections validate browser `Origin`; cross-origin frontends must be listed in `CORS_ORIGINS`
- New clients send WebSocket credentials through the negotiated `lp-auth` subprotocol; legacy query-string credentials remain temporarily supported for compatibility
- WebSocket admission is capped at **64 connections per IP**, shared through Redis when configured, with cleanup on disconnect
- Each paste is capped at **256 active viewers/connections** to protect room broadcast and memory capacity
- Revisions: last **50** snapshots per paste

## Security model

- Edit tokens and password hashes are redacted from every API/WebSocket payload; new edit links use URL fragments so tokens are not sent to servers, while new clients transport view passwords through headers/subprotocols and passwords remain enforced on **every** read path (paste, sheets, revisions, WebSocket)
- Uploads and deletes require server-side edit authorization (not just frontend gating); creators use the edit token and granted peers use server-derived capabilities, while the UI resolves the current credential at action time to avoid handshake races
- Filenames sanitized; untrusted file types served as forced attachments; strict Content-Security-Policy (no `unsafe-inline` scripts), `nosniff`, `X-Frame-Options: SAMEORIGIN`, tight `Referrer-Policy`
- `X-Forwarded-For` trusted only behind an explicit `LIVEPASTE_TRUST_PROXY=1` (prevents rate-limit spoofing)
- Locked pastes: brute-force lockout on password attempts (`too_many_attempts`)
- See [`AUDIT.md`](./AUDIT.md) for the full audit that drove these fixes

## Development

```bash
# backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest httpx
pytest tests/ -q                # offline suite (50 tests, ~10s, no network)

# Security checks (also run in GitHub Actions)
pip-audit
bandit -r livepaste backend -ll -ii

# frontend (Vite)
cd frontend && yarn install
yarn dev                        # :3000, proxies /api to :8090
yarn build                      # production bundle in build/
rm -rf ../livepaste/static && cp -r build ../livepaste/static
```

Run a local server against the built bundle:

```bash
LIVEPASTE_DATA_DIR=/tmp/lp-live ./.venv/bin/uvicorn livepaste.core:app --port 8090
```

### Environment variables

| Variable | Purpose |
| --- | --- |
| `MONGO_URL`, `DB_NAME` | Hosted mode (MongoDB); omit for SQLite |
| `REDIS_URL` | Optional shared rate-limit and password-lockout backend for multi-worker/hosted deployments |
| `LIVEPASTE_REQUIRE_REDIS` | Reserved deployment policy flag for fail-closed Redis enforcement |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) |
| `VITE_BACKEND_URL` | Backend URL baked into the frontend build (omit for same-origin) |
| `LIVEPASTE_DATA_DIR` | Local-mode data directory (default `~/.livepaste`) |
| `LIVEPASTE_PORT` | Default port for `livepaste start` |
| `LIVEPASTE_REPO` | GitHub `owner/repo` used for update checks |
| `LIVEPASTE_TRUST_PROXY` | Set to `1` only behind a proxy that overwrites `X-Forwarded-For` |
| `LIVEPASTE_SERVE_STATIC` | Set to `0` to disable bundled-frontend serving (API-only/dev) |

## Releasing a new version

**From v3.16.1 on, every version bump is released** — tags, standalone binaries, and GitHub Releases all ship together so rollback history keeps growing. The whole ritual is one command:

```bash
./scripts/release.sh --preflight   # checks only (changelog ↔ version ↔ tests ↔ bundle)
./scripts/release.sh --dry-run     # everything except commit/tag/push
./scripts/release.sh               # full: commit → tag v<VERSION> → push → verify workflow
```

The script refuses to release unless: the `CHANGELOG.md` top entry matches `VERSION`, the offline test suite is green, and the bundled frontend is current. After pushing the tag it polls the **Build & Release binaries** workflow and reports whether binaries + SHA256SUMS were published.

Manual equivalent:

1. Bump `VERSION`, add a `CHANGELOG.md` entry (top section must match), update `README.md` where behavior changed
2. Rebuild the bundled frontend so installs ship the latest UI:
   ```bash
   cd frontend && VITE_BACKEND_URL="" yarn build
   rm -rf ../livepaste/static && cp -r build ../livepaste/static
   ```
3. Bump `CACHE_VERSION` in `frontend/public/sw.js` — or installed PWAs keep serving the old shell
4. Commit, tag, and push — the release workflow builds macOS (arm64 + Intel) and Linux (x86_64 + arm64) executables, generates `SHA256SUMS`, and publishes the GitHub Release automatically:
   ```bash
   git tag v<VERSION> && git push origin main v<VERSION>
   ```

## How it works

1. **Create a link** — paste text or code, optionally pick a custom slug, syntax, expiry, burn-after-read, or password protection.
2. **Share it** — send the URL (or show the QR code); it opens straight in the browser. Read-only by default; edit links are minted at creation and stored in your browser.
3. **Edit live together** — every keystroke syncs to all connected viewers in real time via CRDT; cursors, presence, and reactions are shared; expired or burned pastes are cleaned up automatically.

---

*Built with FastAPI · React · SQLite/MongoDB — made by Nakshtra Yadav*
