# LivePaste

> **Share text. Edit together. Instantly.**

LivePaste is an anonymous, real-time collaborative pastebin (dontpad-style). Create a paste, share the link, and everyone with the link can view and edit the content live — no accounts, no sign-up, no install.

**Version:** see [`VERSION`](./VERSION) · **Changes:** see [`CHANGELOG.md`](./CHANGELOG.md)

---

## Features

- **Instant live links** — random short slugs by default, or pick a custom slug (e.g. `/my-notes`)
- **Real-time collaboration** — edits broadcast to all connected clients in under a second via WebSockets
- **Syntax highlighting** — Prism-powered highlighting for Python, JavaScript, TypeScript, and many more languages
- **Inline images (Google Docs style)** — paste, drop, or upload screenshots and they render right at your cursor position in the document (up to 100 MB each, stored in GridFS), with hover controls to open, copy URL, or delete
- **Optional expiry** — auto-delete pastes after 1 hour, 1 day, 1 week, or keep forever
- **Live presence** — see how many people are viewing right now, plus total views
- **Editor niceties** — line numbers, status bar (lines / chars / size), copy content & copy link buttons
- **Dark mode** — toggle persisted across sessions
- **Anonymous by design** — no login, no tracking, just a link

## Install on Your Machine (macOS / Linux)

Run LivePaste locally and share pastes with everyone on your Wi-Fi — no accounts, no cloud, no database to install.

**One-line install** (interactive, animated):

```bash
curl -fsSL https://raw.githubusercontent.com/NakshtraYadav/Live-Paste/main/install.sh | bash
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

- Pastes and images are stored locally in `~/.livepaste` (SQLite + files — nothing else to install)
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
| Realtime   | Native WebSockets at `/api/ws/{slug}` with room broadcast  |
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
│   │   ├── components/    # InlineBlocksEditor (inline images), ThemeToggle, shadcn/ui
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
| `POST`   | `/api/paste`               | Create a paste. Body: `content`, `language`, optional `customSlug`, `expiry` (`1h` \| `1d` \| `1w` \| `never`) |
| `GET`    | `/api/paste/{slug}`        | Fetch a paste; `?count_view=true` increments the view counter               |
| `POST`   | `/api/paste/{slug}/image`  | Upload an image (multipart) attached to a paste                             |
| `GET`    | `/api/image/{image_id}`    | Stream an uploaded image                                                    |
| `DELETE` | `/api/image/{image_id}`    | Delete an uploaded image                                                    |

### WebSocket

| Endpoint         | Description                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| `/api/ws/{slug}` | Join a paste room. Receives edit broadcasts, presence (viewer count), and revision updates. Unknown slugs receive `{type: "error", code: "not_found"}`. |

### Limits & Rules

- Max paste size: **400 KB**
- Max image size: **100 MB**
- Reserved slugs (`api`, `ws`, `static`, `new`, `about`, …) cannot be claimed
- Custom slugs are validated; duplicates are rejected

## Getting Started (Development)

Services are managed by **supervisor** — backend on `0.0.0.0:8001`, frontend on `:3000`, MongoDB local.

```bash
# Install dependencies
cd backend && pip install -r requirements.txt
cd frontend && yarn install

# Restart services
sudo supervisorctl restart all
```

### Environment Variables

| File / Env       | Variable                 | Purpose                                                    |
| ---------------- | ------------------------ | ---------------------------------------------------------- |
| `backend/.env`   | `MONGO_URL`              | MongoDB connection string (hosted mode; omit for SQLite)   |
| `backend/.env`   | `DB_NAME`                | Database name (hosted mode)                                |
| `backend/.env`   | `CORS_ORIGINS`           | Allowed CORS origins                                       |
| `frontend/.env`  | `REACT_APP_BACKEND_URL`  | Backend URL baked into the build (omit for same-origin)    |
| runtime          | `LIVEPASTE_DATA_DIR`     | Local-mode data directory (default `~/.livepaste`)         |
| runtime          | `LIVEPASTE_PORT`         | Default port for `livepaste start`                         |
| runtime          | `LIVEPASTE_REPO`         | GitHub `owner/repo` used for update checks                 |

> Never hardcode URLs or ports — always use the environment variables above.

### Releasing a New Version

1. Bump the number in `VERSION` and add a `CHANGELOG.md` entry
2. Rebuild the bundled frontend so installs ship the latest UI:
   ```bash
   cd frontend && REACT_APP_BACKEND_URL="" yarn build
   rm -rf ../livepaste/static && cp -r build ../livepaste/static
   ```
3. Push to GitHub — every installed copy will see the update notice on next start

## How It Works

1. **Create a link** — paste your text or code, optionally pick a custom slug, syntax, and expiry.
2. **Share it** — send the URL to anyone; it opens straight in the browser.
3. **Edit live together** — every keystroke syncs to all connected viewers in real time; expired pastes are cleaned up automatically.

---

*Built with FastAPI · React · SQLite/MongoDB — made by Nakshtra Yadav*
