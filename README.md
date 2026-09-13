# LivePaste

> **Share text and files. Edit together. Instantly.**

LivePaste is an anonymous, real-time collaborative pastebin (dontpad-style). Create a paste, share the link, and everyone with the link can view it live — no accounts, no sign-up, no install. Hand out **edit links** to let people type along: edits sync conflict-free (CRDT) so simultaneous typing just works.

**Version:** see [`VERSION`](./VERSION) · **Changes:** see [`CHANGELOG.md`](./CHANGELOG.md)

---

## Features

- **Instant live links** — random short slugs by default, or pick a custom slug (e.g. `/my-notes`)
- **Edit vs. view links** — the link you share is read-only; a secret edit token (stored in your browser) controls who can change the paste. Share the edit link with people you trust.
- **True concurrent editing (CRDT)** — Yjs-powered sync over WebSockets: multiple people can type at once with no lost keystrokes
- **Multiple pages per paste** — a paste is a notebook: add named pages ("sheets"), each with its own content, language, and CRDT state; switch with a tab bar
- **Live cursors & presence avatars** — see everyone's caret moving in real time with colored name tags (Yjs Awareness-style), plus avatar chips for every connected viewer
- **Runnable pastes** — a Run button on JavaScript and Python blocks executes the code right in your browser (sandboxed JS worker; Python via Pyodide/WASM) and shows console output and the last expression value inline
- **Offline-first PWA** — LivePaste is installable and keeps working offline: the app shell is cached by a service worker, every paste is mirrored to IndexedDB, edits made offline queue up and auto-merge when you reconnect
- **Peer-to-peer LAN mode** — one click on the P2P toggle and document data flows browser-to-browser over WebRTC data channels; the server only brokers the handshake ("your data never touches the wire")
- **Voice & screen notes** — record your microphone or your screen (with mic mix) from the toolbar; recordings upload like any file and play inline
- **Inline media previews** — uploaded video, audio, and PDFs play right in the paste instead of showing a bare download card
- **Burn-after-read & password lock** — make a paste self-destruct after N distinct viewers, and/or require a password to open it (bcrypt-hashed; secrets never leak in any API payload)
- **QR code sharing** — "Show QR code" renders the paste URL as a QR for instant phone handoff
- **Slash commands** — type `/` at the start of a line for a Notion-style menu: date, divider, code block, attach file
- **Floating emoji reactions** — react with an emoji and it drifts up everyone's editor with your name and color
- **Revision history** — every edit is snapshotted (last 50); browse and restore from the History side panel
- **Syntax highlighting** — Prism-powered highlighting for Python, JavaScript, TypeScript, and many more languages
- **Inline images (Google Docs style)** — paste, drop, or upload screenshots and they render right at your cursor position in the document (up to 100 MB each), with hover controls to open, copy URL, or delete
- **Share any file — literally any** — PDFs, zips, videos, audio, spreadsheets, `.exe` binaries, ROMs, files with no extension, unicode/emoji names — every file type is accepted (up to 100 MB) and appears as a clean file card inline in the paste, with an extension badge plus open, download, copy URL, and delete controls
- **Optional expiry** — auto-delete pastes after 1 hour, 1 day, 1 week, or keep forever
- **Live presence** — see how many people are viewing right now, plus total views
- **Editor niceties** — line numbers, status bar (lines / chars / size), copy content & copy link buttons
- **Dark mode** — toggle persisted across sessions
- **Anonymous by design** — no login, no tracking, just a link
- **Self-updating with integrity** — `livepaste update` verifies SHA256 checksums, keeps the old binary for `livepaste rollback`, supports `--channel beta`, optional daily auto-update, and a dry-run `--check`. The web UI shows an update banner when a new release is out.

## Install on Your Machine (macOS / Linux)

Run LivePaste locally and share pastes with everyone on your Wi-Fi — no accounts, no cloud, no database to install.

**One-line install** (interactive, animated — **no Python needed** when a binary release exists):

```bash
curl -fsSL https://raw.githubusercontent.com/NakshtraYadav/Live-Paste/main/install.sh | bash
```

The installer automatically downloads the standalone app for your Mac (Apple Silicon or Intel) or Linux machine from [Releases](https://github.com/NakshtraYadav/Live-Paste/releases). If no binary exists for your platform it falls back to a Python install.

**Manual binary download** — grab the file for your machine from the [Releases page](https://github.com/NakshtraYadav/Live-Paste/releases), then:

```bash
chmod +x livepaste-macos-arm64 && ./livepaste-macos-arm64 start
```

**Or install with pip / pipx:**

```bash
pip install git+https://github.com/NakshtraYadav/Live-Paste.git
```

**Then start it:**

```bash
livepaste start
```

```
  ╭────────────────────────────────────────────────────╮
  │  ⚡ LivePaste v1.3.0  made by Nakshtra Yadav
  ├────────────────────────────────────────────────────┤
  │  Local:    http://localhost:8090
  │  Network:  http://192.168.1.23:8090  (share on your Wi-Fi)
  │  Data:     ~/.livepaste
  ╰────────────────────────────────────────────────────╯
```

- Pastes and files are stored locally in `~/.livepaste` (SQLite + files — nothing else to install)
- Anyone on your network can open the `Network` URL and collaborate live
- **Stay up to date:** LivePaste checks this repo's `VERSION` on startup and tells you when a new release is out — update any time with:

```bash
livepaste update
```

**CLI reference:**

| Command                              | Description                                    |
| ------------------------------------ | ---------------------------------------------- |
| `livepaste start`                     | Start the server (LAN-accessible by default)   |
| `livepaste start --port 9000`         | Use a custom port for this run                 |
| `livepaste start --keep-data`         | Keep pastes between sessions for this run      |
| `livepaste start --data-dir ~/pastes` | Store data somewhere else                      |
| `livepaste config`                    | Show settings (port, data-dir, keep-data)      |
| `livepaste config port 9000`          | Change the default port permanently            |
| `livepaste config keep-data on`       | Make pastes persistent by default              |
| `livepaste autostart enable`          | Start LivePaste automatically at login         |
| `livepaste autostart disable`         | Remove the login service                       |
| `livepaste update`                    | Update to the latest version from GitHub       |
| `livepaste version`                   | Show version + check for updates               |

**Temporary by design:** in local mode every session starts clean — when you stop the server (Ctrl+C), all pastes, links, and images are wiped. If it's ever force-closed, leftovers are cleared on the next startup. Prefer to keep your pastes? `livepaste config keep-data on`.

## Tech Stack

| Layer      | Technology                                                 |
| ---------- | ---------------------------------------------------------- |
| Frontend   | React 19, Tailwind CSS, shadcn/ui, Prism (highlighting)    |
| Backend    | FastAPI (Python), WebSockets, pluggable storage layer      |
| Storage    | Local mode: SQLite + files · Hosted mode: MongoDB + GridFS |
| Realtime   | Native WebSockets at `/api/ws/{slug}`, Yjs CRDT, optional y-webrtc P2P (signaling at `/api/webrtc/signaling`)  |
| Runtime    | Pyodide (in-browser Python), sandboxed JS worker, MediaRecorder, service worker + IndexedDB (offline)  |
| Packaging  | pip-installable `livepaste` CLI with bundled frontend      |

## Project Structure

```
/app
├── livepaste/             # Installable Python package
│   ├── core.py            # FastAPI app: REST + WebSocket + SPA serving
│   ├── storage.py         # Storage backends (SQLite local / MongoDB hosted)
│   ├── cli.py             # livepaste start / update / version
│   └── static/            # Bundled frontend build
├── backend/
│   ├── server.py          # Hosted-mode entrypoint (loads .env, exposes app)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/         # HomePage (create), PastePage (live editor)
│   │   ├── components/    # InlineBlocksEditor (inline images & files), ThemeToggle, shadcn/ui
│   │   └── hooks/         # useTheme, use-toast
│   └── package.json
├── install.sh             # Interactive installer (curl | bash)
├── pyproject.toml         # Package definition
├── VERSION                # Current release version (drives update checks)
├── CHANGELOG.md           # Release history
└── README.md
```

## API Reference

All backend routes are prefixed with `/api`.

### REST

| Method   | Endpoint                   | Description                                                                 |
| -------- | -------------------------- | --------------------------------------------------------------------------- |
| `GET`    | `/api/health`              | Health check                                                                |
| `POST`   | `/api/paste`               | Create a paste. Body: `content`, `language`, optional `customSlug`, `expiry` (`1h` \| `1d` \| `1w` \| `never`), `burnAfterViews` (int, self-destruct after N distinct viewers), `password` (view password) |
| `GET`    | `/api/paste/{slug}`        | Fetch a paste; `?count_view=true` increments the view counter               |
| `GET`    | `/api/version`             | Server version (drives the web update banner)                              |
| `POST`   | `/api/paste/{slug}/verify` | Check an edit token → `{canEdit}`                                          |
| `GET`    | `/api/paste/{slug}/revisions`      | List edit snapshots (rev, time, size)                      |
| `GET`    | `/api/paste/{slug}/revisions/{rev}`| Fetch one snapshot's content                               |
| `POST`   | `/api/paste/{slug}/restore`        | Restore content to a snapshot (body: `editToken`, `content`)|
| `POST`   | `/api/paste/{slug}/file`   | Upload **any** file (multipart) attached to a paste                         |
| `GET`    | `/api/file/{file_id}`      | Stream an uploaded file of any type                                         |
| `DELETE` | `/api/file/{file_id}`      | Delete an uploaded file                                                     |
| `POST`   | `/api/paste/{slug}/image`  | Legacy image-only upload (kept for compatibility, redirects to file storage) |
| `GET`    | `/api/image/{image_id}`    | Legacy alias of `/api/file/{id}` for existing pastes                        |
| `DELETE` | `/api/image/{image_id}`    | Legacy alias of `DELETE /api/file/{id}`                                     |

### WebSocket

| Endpoint         | Description                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| `/api/ws/{slug}` | Join a paste room (`?token=<editToken>` to edit, `?pw=<password>` for locked pastes, `?clientId=<id>` for burn-after-read dedup). Receives edit/CRDT broadcasts (per-sheet `s:yupdate`), presence, live cursors, reactions, revision restores. Unknown slugs receive `{type: "error", code: "not_found"}`; locked pastes `code: "password_required"`; write attempts from read-only connections `code: "read_only"`. |
| `/api/webrtc/signaling` | Dumb y-webrtc-compatible signaling relay (`subscribe`/`publish` on `lp:<slug>:<sheet>` topics) used by P2P LAN mode. Document data itself flows browser-to-browser, never through this endpoint. |

### Limits & Rules

- Max paste size: **400 KB**
- Max file size: **100 MB** per uploaded file — **no file type is ever rejected**; unknown extensions, executables, and extensionless files all work. Filenames are sanitized of path components/control chars only.
- Edit tokens and password hashes are redacted from every API/WebSocket payload; passwords are bcrypt-hashed
- Reserved slugs (`api`, `ws`, `static`, `new`, `about`, …) cannot be claimed
- Custom slugs are validated; duplicates are rejected
- Rate limits (per IP): 30 paste creations/hour, 60 uploads/hour
- Revisions: last **50** snapshots per paste

### Update system (CLI)

```bash
livepaste update --check        # dry run — is a new version out?
livepaste update                # download, verify SHA256, swap binary (.old kept)
livepaste rollback              # restore the previous binary
livepaste update --channel beta # track a pre-release branch/tag
livepaste config auto-update on # check + auto-apply daily in the background
```

Every GitHub Release ships a `SHA256SUMS` file (generated by CI); updates refuse to install on checksum mismatch. The web UI shows an "update available" banner by comparing `/api/version` with the latest GitHub release.

### Development

```bash
# backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest httpx
pytest tests/ -q                # offline suite, <1s
livepaste start                 # or: uvicorn livepaste.core:app --port 8090

# frontend (Vite)
cd frontend && yarn install
yarn dev                        # :3000, proxies /api to :8090
VITE_BACKEND_URL="" yarn build  # production bundle in build/
rm -rf livepaste/static && cp -r frontend/build livepaste/static
```

## Getting Started (Development)

See **Development** under [Update system (CLI)](#update-system-cli) above: a venv + `pip install -e .` for the backend and `yarn dev` for the Vite frontend are all you need. No supervisor, no MongoDB — local mode runs on SQLite out of the box.

### Environment Variables

| File / Env       | Variable                 | Purpose                                                    |
| ---------------- | ------------------------ | ---------------------------------------------------------- |
| `backend/.env`   | `MONGO_URL`              | MongoDB connection string (hosted mode; omit for SQLite)   |
| `backend/.env`   | `DB_NAME`                | Database name (hosted mode)                                |
| `backend/.env`   | `CORS_ORIGINS`           | Allowed CORS origins                                       |
| `frontend/.env`  | `VITE_BACKEND_URL`       | Backend URL baked into the build (omit for same-origin)    |
| runtime          | `LIVEPASTE_DATA_DIR`     | Local-mode data directory (default `~/.livepaste`)         |
| runtime          | `LIVEPASTE_PORT`         | Default port for `livepaste start`                         |
| runtime          | `LIVEPASTE_REPO`         | GitHub `owner/repo` used for update checks                 |

> Never hardcode URLs or ports — always use the environment variables above.

### Releasing a New Version

1. Bump the number in `VERSION` and add a `CHANGELOG.md` entry
2. Rebuild the bundled frontend so installs ship the latest UI:
   ```bash
   cd frontend && VITE_BACKEND_URL="" yarn build
   rm -rf ../livepaste/static && cp -r build ../livepaste/static
   ```
3. Push to GitHub — every installed copy will see the update notice on next start
4. **For standalone binaries:** create and push a tag — GitHub Actions builds macOS (arm64 + Intel) and Linux (x86_64 + arm64) executables and publishes a Release automatically:
   ```bash
   git tag v1.5.0 && git push origin v1.5.0
   ```
   (You can also trigger the "Build & Release binaries" workflow manually from the Actions tab.)

## How It Works

1. **Create a link** — paste your text or code, optionally pick a custom slug, syntax, expiry, burn-after-read, or password protection.
2. **Share it** — send the URL (or show the QR code); it opens straight in the browser. Read-only by default; edit links are minted at creation and stored in your browser.
3. **Edit live together** — every keystroke syncs to all connected viewers in real time via CRDT; cursors, presence, and reactions are shared; expired or burned pastes are cleaned up automatically.

---

*Built with FastAPI · React · SQLite/MongoDB — made by Nakshtra Yadav*
