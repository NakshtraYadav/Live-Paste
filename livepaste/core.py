"""LivePaste FastAPI application.

Works in two modes (picked automatically by livepaste.storage.create_storage):
  - Hosted mode : MongoDB (MONGO_URL set)
  - Local mode  : SQLite + files on disk, and serves the bundled frontend
                  so `livepaste start` gives a complete app on one port.
"""

import os
import re
import json
import random
import string
import logging
import asyncio
import mimetypes
import unicodedata
from urllib.parse import quote
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Set

from fastapi import (
    FastAPI,
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    UploadFile,
    File,
)
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .storage import create_storage, FileTooLarge, now_utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("livepaste")

app = FastAPI(title="LivePaste")
api_router = APIRouter(prefix="/api")

storage = None  # set on startup
_cleanup_task = None

# ---------------- Constants ----------------
MAX_CONTENT_SIZE = 400_000  # ~400KB max paste size
RESERVED_SLUGS = {
    "api", "ws", "static", "assets", "favicon.ico", "robots.txt",
    "index.html", "manifest.json", "new", "about",
}
SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")
EXPIRY_MAP = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None,
}
STATIC_DIR = Path(__file__).parent / "static"


# ---------------- Helpers ----------------
def gen_slug(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


def sanitize_filename(name: Optional[str]) -> str:
    """Accept ANY filename — executables, no extension, unicode, emoji.

    Only strips path components and non-printable control characters so the
    name is safe to store and return in HTTP headers. Extension and type are
    never used to accept/reject a file.
    """
    name = (name or "file").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = name.strip().lstrip(".") or "file"  # avoid hidden/empty names
    return name[:255]


# Content types that must download instead of rendering on our origin
_UNSAFE_INLINE_TYPES = ("html", "xml", "xhtml", "svg")


def _content_disposition(content_type: str, filename: str) -> str:
    ctype = (content_type or "").lower()
    forced_download = any(t in ctype for t in _UNSAFE_INLINE_TYPES)
    dtype = "attachment" if forced_download else "inline"
    ascii_name = filename.encode("ascii", "ignore").decode().strip() or "file"
    return f'{dtype}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def is_expired(paste: dict) -> bool:
    exp = paste.get("expiresAt")
    if exp is None:
        return False
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < now_utc()


async def get_paste_doc(slug: str):
    paste = await storage.find_paste(slug)
    if paste and is_expired(paste):
        await storage.delete_paste(slug)
        await storage.purge_paste_files(slug)
        return None
    return paste


# ---------------- Models ----------------
class PasteCreate(BaseModel):
    content: str = ""
    customSlug: Optional[str] = None
    language: str = "plaintext"
    expiry: str = "never"  # 1h | 1d | 1w | never


# ---------------- REST endpoints ----------------
@api_router.get("/health")
async def health():
    return {"status": "ok", "time": now_utc().isoformat()}


@api_router.post("/paste")
async def create_paste(body: PasteCreate):
    if len(body.content) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Content too large (max 400KB)")
    if body.expiry not in EXPIRY_MAP:
        raise HTTPException(status_code=400, detail="Invalid expiry option")

    slug = None
    if body.customSlug:
        candidate = body.customSlug.strip()
        if not SLUG_RE.match(candidate):
            raise HTTPException(
                status_code=400,
                detail="Custom link must be 3-64 chars: letters, numbers, hyphens, underscores",
            )
        if candidate.lower() in RESERVED_SLUGS:
            raise HTTPException(status_code=400, detail="This link name is reserved, please choose another")
        existing = await get_paste_doc(candidate)
        if existing:
            raise HTTPException(status_code=409, detail="This link is already taken, please choose another")
        slug = candidate
    else:
        for _ in range(10):
            candidate = gen_slug()
            if not await storage.slug_exists(candidate):
                slug = candidate
                break
        if not slug:
            raise HTTPException(status_code=500, detail="Could not generate unique link, try again")

    delta = EXPIRY_MAP[body.expiry]
    expires_at = (now_utc() + delta) if delta else None

    paste = {
        "slug": slug,
        "content": body.content,
        "language": body.language or "plaintext",
        "views": 0,
        "createdAt": now_utc().isoformat(),
        "updatedAt": now_utc().isoformat(),
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "rev": 0,
    }
    await storage.insert_paste(paste)
    return paste


@api_router.get("/paste/{slug}")
async def get_paste(slug: str, count_view: bool = False):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    if count_view:
        await storage.increment_views(slug)
        paste["views"] = paste.get("views", 0) + 1
    return paste


# ---------------- File endpoints (any file type) ----------------
async def _upload_file(slug: str, file: UploadFile):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")

    filename = sanitize_filename(file.filename)
    # Trust the browser's type when present; otherwise guess from the
    # extension (works for .exe, .deb, .apk, ...) and fall back to a generic
    # binary type. The type is NEVER used to reject an upload.
    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        file_id, size = await storage.save_file(slug, filename, content_type, file)
    except FileTooLarge:
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")
    except Exception as e:
        logger.error(f"File upload failed for {slug}: {e}")
        raise HTTPException(status_code=500, detail="File upload failed, please try again")

    return {
        "id": file_id,
        "url": f"/api/file/{file_id}",
        "name": filename,
        "size": size,
        "contentType": content_type,
    }


async def _get_file(file_id: str):
    result = await storage.open_file(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="File not found")
    content_type, length, iterator, filename = result
    return StreamingResponse(
        iterator,
        media_type=content_type or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Length": str(length),
            "Content-Disposition": _content_disposition(content_type or "", filename or "file"),
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _delete_file(file_id: str):
    ok = await storage.delete_file(file_id)
    if not ok:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True}


@api_router.post("/paste/{slug}/file")
async def upload_file(slug: str, file: UploadFile = File(...)):
    """Upload any file (max 100MB) attached to a paste."""
    return await _upload_file(slug, file)


@api_router.get("/file/{file_id}")
async def get_file(file_id: str):
    """Stream an uploaded file of any type."""
    return await _get_file(file_id)


@api_router.delete("/file/{file_id}")
async def delete_file(file_id: str):
    return await _delete_file(file_id)


# ---- Legacy image endpoints (kept for old clients / existing pastes) ----

@api_router.post("/paste/{slug}/image")
async def upload_image(slug: str, file: UploadFile = File(...)):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    return await _upload_file(slug, file)


@api_router.get("/image/{image_id}")
async def get_image(image_id: str):
    return await _get_file(image_id)


@api_router.delete("/image/{image_id}")
async def delete_image(image_id: str):
    return await _delete_file(image_id)


# ---------------- WebSocket room manager ----------------
class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def join(self, slug: str, ws: WebSocket):
        async with self.lock:
            self.rooms.setdefault(slug, set()).add(ws)
            return len(self.rooms[slug])

    async def leave(self, slug: str, ws: WebSocket):
        async with self.lock:
            conns = self.rooms.get(slug)
            if conns and ws in conns:
                conns.remove(ws)
            count = len(conns) if conns else 0
            if conns is not None and not conns:
                del self.rooms[slug]
            return count

    def viewer_count(self, slug: str) -> int:
        return len(self.rooms.get(slug, set()))

    async def broadcast(self, slug: str, message: dict, exclude: Optional[WebSocket] = None):
        conns = list(self.rooms.get(slug, set()))
        data = json.dumps(message)
        for conn in conns:
            if conn is exclude:
                continue
            try:
                await conn.send_text(data)
            except Exception:
                pass


manager = RoomManager()


@app.websocket("/api/ws/{slug}")
async def ws_paste(websocket: WebSocket, slug: str):
    await websocket.accept()

    paste = await get_paste_doc(slug)
    if not paste:
        await websocket.send_text(
            json.dumps({"type": "error", "code": "not_found", "message": "Paste not found or expired"})
        )
        await websocket.close(code=4404)
        return

    await manager.join(slug, websocket)

    await websocket.send_text(
        json.dumps({"type": "init", "paste": paste, "viewers": manager.viewer_count(slug)})
    )
    await manager.broadcast(
        slug, {"type": "presence", "viewers": manager.viewer_count(slug)}, exclude=websocket
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")

            if mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if mtype == "edit":
                content = msg.get("content", "")
                if len(content) > MAX_CONTENT_SIZE:
                    await websocket.send_text(
                        json.dumps({"type": "error", "code": "too_large", "message": "Content too large (max 400KB)"})
                    )
                    continue
                current = await get_paste_doc(slug)
                if not current:
                    await websocket.send_text(
                        json.dumps({"type": "error", "code": "expired", "message": "This paste has expired"})
                    )
                    await websocket.close(code=4410)
                    break
                new_rev = current.get("rev", 0) + 1
                updated_at = now_utc()
                await storage.update_content(slug, content, updated_at, new_rev)
                await manager.broadcast(
                    slug,
                    {"type": "edit", "content": content, "rev": new_rev, "updatedAt": updated_at.isoformat()},
                    exclude=websocket,
                )
                continue

            if mtype == "language":
                lang = msg.get("language", "plaintext")
                await storage.update_language(slug, lang, now_utc())
                await manager.broadcast(slug, {"type": "language", "language": lang}, exclude=websocket)
                continue

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS error on {slug}: {e}")
    finally:
        count = await manager.leave(slug, websocket)
        await manager.broadcast(slug, {"type": "presence", "viewers": count})


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Bundled frontend (local mode) ----------------
if (STATIC_DIR / "index.html").exists() and os.environ.get("LIVEPASTE_SERVE_STATIC", "1") != "0":
    if (STATIC_DIR / "static").exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR / "static"), name="spa-static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (STATIC_DIR / full_path).resolve()
        # direct asset files at the root of the build (favicon, manifest, ...)
        if (
            full_path
            and candidate.is_file()
            and str(candidate).startswith(str(STATIC_DIR.resolve()))
        ):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")


# ---------------- Lifecycle ----------------
async def _cleanup_loop():
    while True:
        try:
            await storage.purge_expired()
        except Exception as e:
            logger.warning(f"Expiry cleanup failed: {e}")
        await asyncio.sleep(600)  # every 10 minutes


def _is_ephemeral() -> bool:
    """Session mode: only honored in local (SQLite) mode, set by the CLI."""
    from .storage import SQLiteStorage

    return (
        os.environ.get("LIVEPASTE_EPHEMERAL", "0") == "1"
        and isinstance(storage, SQLiteStorage)
    )


@app.on_event("startup")
async def on_startup():
    global storage, _cleanup_task
    storage = create_storage()
    await storage.startup()
    if _is_ephemeral():
        # Covers force-kill: clear anything left over from a previous session
        await storage.purge_all()
    _cleanup_task = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def on_shutdown():
    if _cleanup_task:
        _cleanup_task.cancel()
    if storage:
        if _is_ephemeral():
            # Peaceful exit: wipe this session's pastes and images
            try:
                await storage.purge_all()
            except Exception as e:
                logger.warning(f"Session cleanup on shutdown failed: {e}")
        await storage.shutdown()
