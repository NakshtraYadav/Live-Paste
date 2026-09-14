# Changelog

All notable changes to **LivePaste** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.4.0] - 2026-09-14

### Fixed
- **New pages no longer inherit the previous page's text.** A page switch
  inside the 120 ms CRDT coalescing window re-labeled page-1 edits onto the
  new page, and the doc-swap race seeded fresh pages with the outgoing
  page's content — and relayed it to the server for that sheet. Updates now
  carry the sheet they were typed on from queue time, content refs reset
  before any await during a switch, and `s:state` no longer seeds a blank
  page unless the stored text is actually non-empty. Verified end-to-end:
  page 1 and page 2 now hold strictly their own text.
- **QR code no longer overlaps the toolbar.** It renders as a centered modal
  overlay card (click the backdrop to dismiss) instead of a cramped inline
  block that collided with dropdowns, badges, and the editor gutter.
- **Renaming yourself updates everywhere instantly** — the new name is
  re-announced over the presence channel the moment it's set, so avatar
  chips and cursor name tags change live on every peer's screen instead of
  waiting for the next keystroke.
- **Recording works on mobile browsers.** iOS Safari (which can't produce
  webm) now records via `audio/mp4`, Firefox via `audio/ogg`; screen capture
  on browsers without `getDisplayMedia` returns a clean "not supported"
  message instead of failing silently; a mic track ending (unplugged, OS
  revocation) now finishes a voice note cleanly — previously only the screen
  video track was watched, so dead-mic recordings produced empty files.
  Failure toasts explain permission denials instead of nothing happening.
- **Reconnect after a server restart no longer dead-ends.** When the server
  comes back without the paste (ephemeral/local mode wipes data on restart),
  the "nothing at this link" screen now detects a locally saved offline copy
  and offers "Restore local copy as new paste" with one click.

### Changed
- **P2P mode now follows the active page**: the WebRTC topic re-attaches on
  every sheet switch, so peers sync the page they are actually on. Data
  channels are per-page (`lp:<slug>:<sheet>`), pairs still discover each
  other through the self-hosted signaling relay.
- **Service worker cache version is now bumped with every release**
  (`lp-v3.4.0`), so installed PWA clients pick up new bundles immediately
  instead of pinning an old app shell (the root cause of "my changes don't
  show up" during this release's testing).
- Run documentation: `yarn build` must be followed by copying `frontend/build`
  → `livepaste/static`; the server serves the bundled copy.

---

## [3.3.0] - 2026-09-14

### Added
- **Per-user edit permissions.** The paste owner no longer needs to share the
  secret edit link to let someone in: click any peer's presence avatar to
  **grant edit access** — their editor unlocks instantly, live, with a green
  ✎ badge on the avatar. Click again to revoke; the change fans out to the
  whole room over the existing WebSocket (`grant-edit`/`revoke-edit` →
  `editors` broadcast), and revoked users are demoted to read-only on the
  spot. The allowlist (up to 50 clientIds) persists server-side and is
  re-applied on every reconnect — no link sharing needed.
- The `init` message now carries `isOwner` and the current editors list so
  the UI knows who may manage permissions.

### Security
- **Closed an enforcement gap**: file/image upload and file deletion were
  only gated in the frontend — the REST endpoints accepted unauthenticated
  writes. Uploads (`POST /file`, `/image`) and deletes (`DELETE /file/{id}`)
  now require edit rights (edit token **or** granted clientId) server-side,
  verified by new tests.

### Tests
- New regression tests for upload/delete authorization and the grant →
  upload → revoke flow (31 total).

---

## [3.2.0] - 2026-09-14

### Added
- **Brute-force protection on password unlock.** Failed password attempts are
  counted per IP + paste; 8 wrong tries locks unlock attempts for that paste
  for 5 minutes (REST returns 429 with `Retry-After`; the WebSocket rejects
  with `code 4004 too_many_attempts`). The unlock screen and socket reconnect
  both surface a friendly "too many attempts" message.
- **Connection cap on the P2P signaling relay** (32 concurrent signal
  connections per paste topic) so a runaway tab can't pin the server.
- **GitHub Actions CI** (`.github/workflows/ci.yml`): every push and pull
  request now runs the offline pytest suite on Python 3.9/3.12 — server
  regressions (like the handshake deadlock this release fixes) are caught
  before they ship.
- Six new tests: brute-force lockout on `/verify`, lockout reset by a correct
  password, WS rejection after lockout, unlimited lockout for pastes without
  a password, and limiter isolation between tests.

### Changed
- FastAPI app lifecycle migrated from the deprecated `@app.on_event` handlers
  to a modern lifespan context manager (deprecation warnings dropped 5 → 1).
- In-memory limiters (rate limits + lockouts) are now exposed for test resets,
  and the test suite resets them per test so the creation rate limit budget
  is never consumed by test volume.

### Fixed
- `_try_close` also awaited its coroutine now — same bug class as the 3.1.1
  `_try_send` fix; found by a deprecation-warning audit of the disconnect path.

---

## [3.1.1] - 2026-09-13

### Fixed
- **WebSocket handshake crash on fast navigation** (the reported
  `ClientDisconnected` / `ConnectionClosedOK (1001)` traceback): a client that
  closed the tab before the server finished sending `init` crashed the ASGI
  task with an unhandled `WebSocketDisconnect`, and — worse — skipped room
  cleanup, leaving a dead socket counted as a viewer forever. The entire
  handshake (paste lookup, password gate, burn-after-read, init send) now runs
  inside guarded error handling with best-effort sends (`_try_send`/
  `_try_close`), and the `finally` cleanup (presence + peer-left broadcast)
  always runs.
- **Hardened the P2P signaling endpoint** the same way: a client vanishing
  during the upgrade handshake no longer surfaces an error; per-topic rooms
  are always cleaned up.
- **Frontend closes the socket on `pagehide`/`beforeunload`** with code 1001,
  telling the server *before* browser teardown instead of racing it — removes
  the mid-handshake window where the 1001 noise originated.
- **Test-suite regression fix**: the new disconnect tests initially deadlocked
  the suite (a server helper shipped without awaiting its coroutine — caught
  by the tests themselves, never released). All 27 offline tests pass in <1s.

### Added
- Two regression tests: a client vanishing mid-handshake must not leak its
  room slot (viewer count returns to baseline), and broadcasting to a room
  with vanished peers must not crash the editor.
- README refreshed: full feature list for v2.2–v3.1 (pages, live cursors,
  runnable pastes, offline PWA, P2P LAN mode, recordings, media previews,
  burn/password, QR, slash commands, reactions), new API surface
  (`/api/webrtc/signaling`, WS `pw`/`clientId` params, burn/password create
  options), and corrected dev docs (Vite env var, no supervisor).

---

## [3.1.0] - 2026-09

### Added
- **Floating emoji reactions.** A smiley button in the toolbar opens an emoji
  bar (🎉 ❤️ 😂 🔥 👍 👀 🚀 ✨); picked reactions drift up the editor as
  bubbles tagged with the sender's name and presence color — pure Google-Docs
  delight, relayed through the existing WebSocket to everyone in the room.

---

## [3.0.0] - 2026-09

### Added
- **Slash commands.** Type `/` at the start of any line for a Notion-style
  command menu: **Date** (today's date), **Divider**, **Code block** (fenced,
  with cursor placed inside), and **Attach file** (opens the file picker wired
  to the any-file uploader). Type-to-filter, ↑/↓ to navigate, Enter to apply,
  Esc to dismiss.

---

## [2.9.0] - 2026-09

### Added
- **QR code sharing.** "Show QR code" in the Share menu renders the paste's
  URL as a crisp SVG QR right in the toolbar — scan with a phone and you're
  in the paste. Perfect pairing with P2P LAN mode for demos.

---

## [2.8.0] - 2026-09

### Added
- **Burn-after-read.** Set "views before self-destruct" at creation (1–10000);
  once that many *distinct* viewers have opened the paste it is destroyed —
  files and CRDT state included. The triggering reader still gets the content;
  everyone after finds it gone. Repeat views from the same client don't count
  (per-client id via the presence identity), and a flame badge shows on paste
  pages that will burn.
- **Password lock.** Optionally require a view password at creation. Hashed
  server-side (bcrypt when available, SHA-256 fallback — the hash never leaves
  the server, `passwordHash` is stripped from every API/WS payload). Locked
  links show an unlock screen; the password is kept session-only in memory and
  sent as a WS query param, never persisted.

### Security
- REST `GET /paste/{slug}` and the WebSocket `init` payload now both pass
  through a strict redaction filter (`editToken`, `passwordHash`, `burnedBy`
  can no longer leak).

---

## [2.7.0] - 2026-09

### Added
- **Inline media previews.** Video, audio and PDF attachments now render
  playable/previewable inline instead of a bare download card:
  - `<video>` player for mp4/webm/mov/mkv with native controls
  - `<audio>` player for mp3/wav/ogg/m4a/flac/aac above the file card
  - Embedded PDF viewer (`<object>` with iframe fallback) at 480px height
  - Download/copy/delete actions unchanged; images preview as before.

---

## [2.6.0] - 2026-09

### Added
- **Voice & screen notes.** A "Record" button in the paste toolbar captures
  your microphone or your screen (+ mic) with MediaRecorder and attaches the
  result to the paste like any other file — turning LivePaste into an async
  standup / feedback tool.
  - Live REC indicator with elapsed time; click to stop & attach.
  - Screen notes optionally mix in microphone audio; the browser's own
    "Stop sharing" button ends the recording cleanly.
  - Streams are always fully released on cancel/navigation (no stuck capture
    indicators), recordings upload as `audio/webm` via the regular 100MB any-file
    endpoint and sync to every viewer.

---

## [2.5.0] - 2026-09

### Added
- **Peer-to-peer LAN mode (y-webrtc).** A one-click "P2P" toggle in the paste
  toolbar switches on browser-to-browser sync: document updates flow directly
  over WebRTC data channels, while the LivePaste server only brokers the
  initial handshake — data never touches the wire.
  - Ships its own dumb signaling relay (`/api/webrtc/signaling`) that speaks the
    y-webrtc wire protocol (subscribe/publish over topics, no third-party
    signaling servers, signaling scoped to `lp:<slug>:<sheet>` topics).
  - The provider attaches to the same Y.Doc the server CRDT sync uses, so P2P
    and server sync run concurrently — Yjs merges idempotently; peers show in
    the toggle badge (`2 peers`), with a `connecting` state meanwhile.
  - Falls back gracefully: same-browser tabs also sync via BroadcastChannel,
    and everything still syncs through the server when P2P is off.

---

## [2.4.0] - 2026-09

### Added
- **Offline-first pastes (PWA).** LivePaste is now an installable app that works
  without a connection:
  - Service worker caches the app shell (cache-first with background revalidate)
    and falls back to cached API reads when the network is gone; writes and
    WebSockets are never intercepted.
  - Web app manifest + favicon — "Install LivePaste" from the browser menu.
  - Every paste's Y.Doc is mirrored into IndexedDB, so edits survive reloads and
    connectivity loss and auto-merge when the socket returns.
  - Offline cold start: if the server is unreachable, the editor hydrates from
    the local IndexedDB copy and keeps accepting edits (queued CRDT updates
    drain on reconnect, plus a 10s recovery poll).
  - "Offline — edits will sync" toolbar badge with a live online/offline signal.

---

## [2.3.0] - 2026-09

### Added
- **Runnable pastes — "Run" buttons on code blocks.** JavaScript runs in a
  dedicated sandboxed Web Worker (5s timeout, captured console, no timers/DOM
  access); Python runs on Pyodide (CPython 3.12 via WebAssembly), loaded
  lazily from the CDN on first run and cached by the browser afterwards.
  - Output panel renders inline under the executed block: console lines, the
    last expression's value (REPL-style `⇒` for JS, repr for Python), and
    error/timeout states.
  - The Run button appears only when the sheet language is runnable or the
    block's code plausibly is (sniffed automatically for plaintext sheets).

---

## [2.2.0] - 2026-09

### Added
- **Live cursors + presence avatars (Google-Docs-style collaboration).** Everyone
  in a paste room now sees who else is there: colored avatar chips in the toolbar
  (click your own to rename), and remote carets with name tags rendered live in
  the editor as peers type, plus remote selection highlights.
  - Presence runs over the existing WebSocket protocol: a `hello` handshake
    registers each participant, the server answers with the current peer list,
    announces joins/leaves, and prunes stale entries; cursors are relayed
    editor-to-editor with per-tab identities (random id, stable palette color,
    display name persisted per browser).
  - Cursor offsets are per-sheet, so remote carets re-scope when you switch
    pages; read-only visitors can see presence but never broadcast cursors.
  - Idle heartbeats keep your entry fresh while present but not typing;
    stale cursors fade after 15s, stale presence after 30s.

---

## [2.1.1] - 2026-09

### Fixed
- **New pastes open in edit mode for their creator** — the edit token was being returned by the API but never saved, so every freshly created link appeared read-only to the person who just made it. Creation now stores the token immediately; a fresh visit without the token is still read-only.
- The token helpers moved to `frontend/src/lib/editToken.js` so the home page and paste page share one source of truth.

### Changed
- The toolbar's two separate copy buttons are replaced by a single **Share** menu offering both link types with descriptions: "Copy view-only link" (anyone can read & copy) and "Copy edit link" (anyone with it can edit).

---

## [2.1.0] - 2026-09

### Added
- **Multiple pages/sheets per paste** — one link now holds a whole set of pages. A tab bar above the editor lets you add pages (`+ Page`), switch between them, rename with double-click, and delete non-primary pages. Each page keeps its own content, syntax language, and CRDT state.
- Sheet-aware real-time sync — CRDT updates relay per sheet (`s:yupdate`), background pages keep receiving updates while you work on another one, and new joiners pull a sheet's stored state on open (`s:open` → `s:state`). Full-text fallback per sheet (`s:edit`) included.
- New REST endpoints: `GET /paste/{slug}/sheets`, `GET /paste/{slug}/sheets/{id}`, `POST /paste/{slug}/sheets`, `PATCH /paste/{slug}/sheets/{id}` (rename/language), `DELETE /paste/{slug}/sheets/{id}` — all writes token-gated like the rest of the API.
- The original document is always available as the **"Page 1"** (`main`) sheet and cannot be deleted, so existing links behave exactly as before.
- Storage: new `sheets` + `ystate_sheets` tables (SQLite) and collections (MongoDB) with automatic migration of existing databases.

---

## [2.0.0] - 2026-09

### Added
- **True concurrent editing (CRDT)** — typing is now synced with [Yjs](https://github.com/yjs/yjs) over the existing WebSocket protocol (`yupdate` relay), so two people can type at the same time without clobbering each other. The server stores an ordered list of composable Yjs updates per paste (no merge library required) and replays them to new joiners; full-text edits remain as a periodic backup channel.
- **Edit links vs. view links** — every new paste gets a secret **edit token** at creation (stored in the creator's `localStorage`, returned once). The plain link is now **read-only**; share `?edit=<token>` links to grant editing. Writes (REST restore, WS `edit`/`yupdate`/`language`) require the token; legacy pastes created before 2.0 stay open to preserve existing links. The creator sees an "Edit link" button in the toolbar; viewers see a read-only banner and can't upload, delete files, or change the language.
- **Revision history** — every edit snapshots the paste (capped at 50 revisions). New endpoints `GET /api/paste/{slug}/revisions` and `GET /api/paste/{slug}/revisions/{rev}`, plus `POST /api/paste/{slug}/restore` (token-gated) with a live "restore" broadcast. The web UI gets a **History side panel** with one-click restore.
- **Web update banner** — new `GET /api/version`; the UI compares it with the latest GitHub release and shows a dismissible "update available — what's new" banner with a link to the release notes.
- **Hardened update system (CLI)** — `livepaste update` now verifies SHA256 checksums against the release's `SHA256SUMS` (published by CI), keeps the previous binary as `.old`, and adds `livepaste rollback`; `--check` dry-run, `-y` non-interactive mode, `--channel beta` for pre-releases, a daily background auto-update (`livepaste config auto-update on`), and a download progress bar.
- **Offline test suite** — `tests/` with pytest + FastAPI TestClient on a temp SQLite dir (16 tests, ~0.5s, no network): edit tokens, read-only enforcement, revision restore, CRDT relay + replay state, any-file round-trips (`.exe`, `.vyb`, extensionless, unicode, empty), path-flattening, legacy image rule.
- **Rate limiting** — fixed-window per-IP limits on paste creation (30/h) and uploads (60/h) to blunt abuse on hosted deployments.

### Changed
- **Frontend migrated from CRA/react-scripts to Vite** — production build is ~10× faster (~1s vs ~9s); dev server proxies `/api` to `livepaste start`. Build env var renamed `REACT_APP_BACKEND_URL` → `VITE_BACKEND_URL`.
- The WebSocket `init` message now includes `canEdit` and (when present) the paste's accumulated CRDT updates.
- CI release workflow publishes `SHA256SUMS` alongside the binaries.

### Compatibility
- Old links keep working: pastes without an edit token remain editable by anyone; the plain `/api/image/*` endpoints and single-URL sharing behave as before.

---

## [1.6.0] - 2026-09

### Added
- **Share any file type** — upload, paste, or drop any file (PDF, zip, video, audio, Office docs, code archives…) up to 100 MB and it appears inline in the paste as a clean file card with open, download, copy-URL, and delete controls.
- New `/api/paste/{slug}/file` (upload), `/api/file/{id}` (stream), and `DELETE /api/file/{id}` endpoints; files still flow through the same GridFS (hosted) or on-disk (local) storage as images.
- **No file type is ever rejected** — executables (`.exe`, `.apk`, `.deb`), unknown extensions (`.vyb`, `.xyz123`), extensionless files, unicode/emoji names, and zero-byte files all upload and download byte-perfect. Filenames are sanitized (path components/control chars stripped) and downloads use RFC 5987 headers so unicode names survive.
- Executables and other non-previewable types download with `Content-Disposition: attachment`; HTML/XML/SVG are forced to download too (never render on our origin) alongside a `nosniff` header.
- File cards now show an uppercase extension badge (PDF, EXE, VYB, BIN…) color-coded by category.
- Images by extension (`.png`, `.jpg`, `.svg`, …) render as inline previews even when inserted via the file endpoint.

### Changed
- "Add image" toolbar button is now "Add file" with a paperclip icon; the file picker, clipboard paste handler, and drag-and-drop zone all accept any file type.
- File deletion cleans up through one shared endpoint; deleting a token also deletes the stored file when no references remain.

### Compatibility
- All `/api/image/*` endpoints keep working for existing pastes and old clients; legacy image tokens still render as image previews.

---

## [1.5.0] - 2025-07

### Added
- **Standalone binaries — no Python required.** A GitHub Actions workflow (`.github/workflows/release.yml`) builds single-file executables for macOS (Apple Silicon + Intel) and Linux (x86_64 + arm64) whenever a `v*` tag is pushed, and attaches them to a GitHub Release.
- **Binary-first installer** — `install.sh` now detects your OS/CPU and downloads the prebuilt app when a release exists (nothing to install), falling back to the pip method otherwise.
- **Binary self-update** — `livepaste update` inside a standalone install downloads the newest binary from GitHub Releases and replaces itself in place.
- Version is baked into binaries at build time (`livepaste/_version.py`, generated by CI).

### Changed
- The server is now launched with a direct app import (frozen-binary compatible); autostart services use the binary path when running as a standalone app.

---

## [1.4.0] - 2025-07

### Added
- **Autostart at login** — `livepaste autostart enable|disable|status` installs a macOS LaunchAgent (launchd) or Linux systemd user service; the installer also offers it as a prompt.
- **Persistent settings** — `livepaste config` to view/change `port`, `data-dir`, `keep-data`, and `repo` any time after installation (stored in `~/.livepaste/config`).
- **Custom install location** — the installer now asks where LivePaste should live (default `~/.livepaste`).
- **Temporary sessions by default (local mode)** — all pastes, links, and images are wiped on graceful exit; if the app is force-killed, leftovers are cleared automatically on the next startup. Opt out with `livepaste start --keep-data` or `livepaste config keep-data on`. Hosted MongoDB deployments are never affected.
- `python -m livepaste` module entrypoint (used by the autostart services).

### Changed
- Startup banner now shows the session mode (temporary vs persistent).

---

## [1.3.0] - 2025-07

### Added
- **Installable local app** — LivePaste is now a pip-installable package with a `livepaste` CLI (`start`, `update`, `version`). Runs entirely on your machine, no cloud services required.
- **Zero-setup local storage** — automatically uses SQLite + on-disk image files (`~/.livepaste`) when no MongoDB is configured; hosted deployments with `MONGO_URL` keep using MongoDB.
- **LAN sharing out of the box** — the server binds to `0.0.0.0` and prints both `Local` and `Network` URLs so anyone on the same Wi-Fi can open pastes.
- **Bundled frontend** — the built React app ships inside the package and is served by FastAPI itself (one process, one port).
- **Self-update from GitHub** — startup checks the repo's `VERSION` file and notifies when a newer release exists; `livepaste update` upgrades in one command.
- **Interactive animated installer** (`install.sh`) — ASCII banner, step-by-step spinners, port prompt, and an optional immediate launch; safe non-interactive mode for `curl | bash`.

### Changed
- Backend re-architected into the `livepaste` package with a pluggable storage layer (MongoDB / SQLite); `backend/server.py` is now a thin hosted-mode entrypoint.
- Frontend falls back to same-origin API/WebSocket URLs when no backend URL is configured at build time (self-hosted mode).

---

## [1.2.0] - 2025-07

### Added
- **Inline images (Google Docs style)** — pasted, dropped, or uploaded images now render as actual images at the exact spot in the document where they were inserted, instead of appearing in an attachments strip.
- **Hover controls on inline images** — open full size, copy image URL, and delete, shown on mouse-over of each image.
- **Keyboard editing around images** — Backspace at the start of a line deletes the image above it; Delete at the end of a line removes the image below; arrow keys move the caret across images.
- **Click-to-type zones** — slim insert zones between adjacent images and at document edges let you place the caret anywhere.
- **Automatic file cleanup** — deleting an image (button or Backspace) also removes the stored file from GridFS when no references remain.

### Changed
- Editor re-architected as a block-based document (`InlineBlocksEditor`): text segments keep Prism syntax highlighting and continuous line numbers, image token lines render as inline image blocks. The underlying content format and real-time sync protocol are unchanged.

### Removed
- Bottom "Images (N)" attachments strip — superseded by inline rendering.

---

## [1.1.0] - 2025-07

### Added
- **Image support** — paste (Ctrl/Cmd+V) or upload screenshots and images directly into a paste; stored in MongoDB GridFS (up to 100 MB per image) with inline previews and one-click deletion.
- **Line numbers** in the editor gutter, kept in sync with scrolling and wrapping.
- **Status bar** showing live line count, character count, and paste size metrics.
- Image API endpoints: `POST /api/paste/{slug}/image`, `GET /api/image/{image_id}`, `DELETE /api/image/{image_id}` (streamed responses).

### Changed
- Editor layout refined to accommodate the gutter and status bar without breaking syntax-highlight overlay alignment.

---

## [1.0.0] - 2025-07

### Added
- **Anonymous live pastes** — create a paste with no account and share a single URL; everyone with the link can view and edit together.
- **Real-time collaborative editing** over WebSockets (`/api/ws/{slug}`) with room-based broadcast and revision tracking.
- **Random short slugs** by default, with optional **custom slugs** (validated, reserved names protected, duplicates rejected).
- **Optional expiry** — 1 hour / 1 day / 1 week / never, enforced server-side with automatic cleanup of expired pastes.
- **Syntax highlighting** (Prism) for many languages — Python, JavaScript/Node, TypeScript, and more — with a language selector.
- **Live presence** — see how many viewers are currently connected, plus a total view counter.
- **Copy link** and **copy content** one-click actions.
- **Dark mode** toggle persisted to `localStorage`.
- Content size cap of 400 KB per paste.
- REST API: `GET /api/health`, `POST /api/paste`, `GET /api/paste/{slug}`.
- MongoDB persistence (Motor async driver) — pastes survive refreshes and reconnects.
- WebSocket POC test script (`scripts/ws_poc_test.py`) validating external `wss://` connectivity through ingress (13/13 checks passed).

[1.3.0]: #130---2025-07
[1.2.0]: #120---2025-07
[1.1.0]: #110---2025-07
[1.0.0]: #100---2025-07
