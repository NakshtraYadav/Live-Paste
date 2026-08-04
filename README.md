# LivePaste

> **Share text. Edit together. Instantly.**

LivePaste is an anonymous, real-time collaborative pastebin (dontpad-style). Create a paste, share the link, and everyone with the link can view and edit the content live — no accounts, no sign-up, no install.

**Version:** see [`VERSION`](./VERSION) · **Changes:** see [`CHANGELOG.md`](./CHANGELOG.md)

---

## Features

- **Instant live links** — random short slugs by default, or pick a custom slug (e.g. `/my-notes`)
- **Real-time collaboration** — edits broadcast to all connected clients in under a second via WebSockets
- **Syntax highlighting** — Prism-powered highlighting for Python, JavaScript, TypeScript, and many more languages
- **Image support** — paste or upload screenshots/images inline (up to 100 MB each, stored in GridFS)
- **Optional expiry** — auto-delete pastes after 1 hour, 1 day, 1 week, or keep forever
- **Live presence** — see how many people are viewing right now, plus total views
- **Editor niceties** — line numbers, status bar (lines / chars / size), copy content & copy link buttons
- **Dark mode** — toggle persisted across sessions
- **Anonymous by design** — no login, no tracking, just a link

## Tech Stack

| Layer      | Technology                                                |
| ---------- | --------------------------------------------------------- |
| Frontend   | React 19, Tailwind CSS, shadcn/ui, Prism (highlighting)   |
| Backend    | FastAPI (Python), WebSockets, Motor (async MongoDB)       |
| Database   | MongoDB (pastes) + GridFS (images)                        |
| Realtime   | Native WebSockets at `/api/ws/{slug}` with room broadcast |

## Project Structure

```
/app
├── backend/
│   ├── server.py          # FastAPI app: REST + WebSocket + GridFS images
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/         # HomePage (create), PastePage (live editor)
│   │   ├── components/    # ThemeToggle, shadcn/ui components
│   │   └── hooks/         # useTheme, use-toast
│   └── package.json
├── scripts/
│   └── ws_poc_test.py     # External WebSocket connectivity test
├── VERSION                # Current release version
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

| File            | Variable                | Purpose                                  |
| --------------- | ----------------------- | ---------------------------------------- |
| `backend/.env`  | `MONGO_URL`             | MongoDB connection string                |
| `backend/.env`  | `DB_NAME`               | Database name                            |
| `backend/.env`  | `CORS_ORIGINS`          | Allowed CORS origins                     |
| `frontend/.env` | `REACT_APP_BACKEND_URL` | Public backend URL used for API/WS calls |

> Never hardcode URLs or ports — always use the environment variables above.

## Testing

- **Backend API tests:** `python backend_test.py`
- **WebSocket POC (external connectivity):** `python scripts/ws_poc_test.py`
- Full test history and protocol: [`test_result.md`](./test_result.md)

## How It Works

1. **Create a link** — paste your text or code, optionally pick a custom slug, syntax, and expiry.
2. **Share it** — send the URL to anyone; it opens straight in the browser.
3. **Edit live together** — every keystroke syncs to all connected viewers in real time; expired pastes are cleaned up automatically.

---

*Built with FastAPI · React · MongoDB*
