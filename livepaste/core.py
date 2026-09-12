"""LivePaste FastAPI application.

Works in two modes (picked automatically by livepaste.storage.create_storage):
  - Hosted mode : MongoDB (MONGO_URL set)
  - Local mode  : SQLite + files on disk, and serves the bundled frontend
                  so `livepaste start` gives a complete app on one port.

v2.0 additions:
  - Edit tokens: creating a paste returns a secret `editToken`; writes (REST
    and WebSocket) require it. Viewers without it get a read-only room.
  - Revision history: every edit snapshot is stored (capped) and restorable.
  - CRDT sync: Yjs update relay for conflict-free concurrent editing.
  - /api/version for the web update banner; simple in-memory rate limiting.
"""

import os
import re
import json
import time
import base64
import random
import string
import hashlib
import secrets
import logging
import asyncio
import mimetypes
from urllib.parse import quote
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Set, List

from fastapi import (
    FastAPI,
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    UploadFile,
    File,
    Request,
)
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
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
MAX_SHEETS_PER_PASTE = 32
MAX_SHEET_NAME_LEN = 60
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


def new_edit_token() -> str:
    return secrets.token_urlsafe(24)


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


# ---------------- Rate limiting (simple in-memory, per IP) ----------------
class RateLimiter:
    """Fixed-window limiter. Generous defaults: protects against abuse, not users."""

    def __init__(self):
        self.events: Dict[str, List[float]] = {}

    def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.monotonic()
        bucket = [t for t in self.events.get(key, []) if now - t < window_s]
        if len(bucket) >= limit:
            self.events[key] = bucket
            return False
        bucket.append(now)
        self.events[key] = bucket
        # opportunistic cleanup
        if len(self.events) > 4096:
            cutoff = now - 3600
            self.events = {k: v for k, v in self.events.items() if v and v[-1] > cutoff}
        return True


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------- Models ----------------
class PasteCreate(BaseModel):
    content: str = ""
    customSlug: Optional[str] = None
    language: str = "plaintext"
    expiry: str = "never"  # 1h | 1d | 1w | never


class RestoreBody(BaseModel):
    editToken: str
    content: str


class SheetCreateBody(BaseModel):
    editToken: str
    name: str = ""
    content: str = ""
    language: str = "plaintext"


class SheetUpdateBody(BaseModel):
    editToken: str
    name: Optional[str] = None
    language: Optional[str] = None


def _yupdates_b64(updates: List[bytes]) -> List[str]:
    return [base64.b64encode(u).decode() for u in updates]


def _clean_sheet_name(name: Optional[str], fallback: str) -> str:
    name = (name or "").strip()
    return (name[:MAX_SHEET_NAME_LEN] or fallback)


def require_edit_token(paste: dict, provided: Optional[str]):
    """Raise 403 unless `provided` matches the paste's edit token.

    Legacy pastes created before edit tokens have none — they stay open
    (anyone can edit) to preserve existing links' behavior.
    """
    token = paste.get("editToken")
    if not token:
        return
    if not provided or not secrets.compare_digest(str(provided), str(token)):
        raise HTTPException(status_code=403, detail="Edit token required (read-only link)")


# ---------------- REST endpoints ----------------
@api_router.get("/health")
async def health():
    return {"status": "ok", "time": now_utc().isoformat()}


@api_router.get("/version")
async def version_info():
    """Current server version — the web UI compares this with the latest
    GitHub release to show the update banner."""
    return {"version": __version__}


@api_router.post("/paste")
async def create_paste(body: PasteCreate, request: Request):
    ip = client_ip(request)
    if not limiter.allow(f"create:{ip}", limit=30, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many pastes created — try again later")
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
    edit_token = new_edit_token()

    paste = {
        "slug": slug,
        "content": body.content,
        "language": body.language or "plaintext",
        "views": 0,
        "createdAt": now_utc().isoformat(),
        "updatedAt": now_utc().isoformat(),
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "rev": 0,
        "editToken": edit_token,
    }
    await storage.insert_paste(paste)

    public = {k: v for k, v in paste.items() if k != "editToken"}
    public["editToken"] = edit_token  # returned ONCE, at creation
    return public


@api_router.get("/paste/{slug}")
async def get_paste(slug: str, count_view: bool = False):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    if count_view:
        await storage.increment_views(slug)
        paste["views"] = paste.get("views", 0) + 1
    public = {k: v for k, v in paste.items() if k != "editToken"}
    return public


@api_router.post("/paste/{slug}/verify")
async def verify_edit_token(slug: str, body: dict):
    """Check an edit token without side effects. Used by the web UI to
    decide edit vs read-only mode."""
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    token = paste.get("editToken")
    if not token:
        return {"canEdit": True, "legacy": True}
    provided = body.get("editToken") or ""
    return {"canEdit": bool(provided) and secrets.compare_digest(str(provided), str(token))}


@api_router.post("/paste/{slug}/restore")
async def restore_revision(slug: str, body: RestoreBody):
    """Restore paste content to a previous snapshot (requires edit token)."""
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, body.editToken)
    if len(body.content) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Content too large (max 400KB)")

    updated_at = now_utc()
    new_rev = await storage.append_revision(slug, body.content, updated_at)
    await storage.update_content(slug, body.content, updated_at, new_rev)
    # CRDT state is stale after a restore: clear it so clients re-sync
    # from the restored plain text on their next edit.
    await storage.clear_ystate(slug)
    await manager.broadcast(
        slug,
        {
            "type": "restore",
            "content": body.content,
            "rev": new_rev,
        },
    )
    return {"ok": True, "rev": new_rev}


# ---------------- Sheets (multiple pages per paste) ----------------
def _sheets_with_main(sheets):
    """Every paste implicitly has sheet "main" (its original document).
    Make sure it is always present in listings, sorted first."""
    rest = sorted(
        (s for s in sheets if s["sheetId"] != "main"),
        key=lambda s: s.get("position", 0),
    )
    return [{"sheetId": "main", "name": "Page 1", "position": 0}] + rest


@api_router.get("/paste/{slug}/sheets")
async def list_sheets(slug: str):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    sheets = await storage.list_sheets(slug)
    return {"sheets": _sheets_with_main(sheets)}


@api_router.get("/paste/{slug}/sheets/{sheet_id}")
async def get_sheet(slug: str, sheet_id: str):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    if sheet_id == "main":
        return {"sheetId": "main", "name": "Page 1", "content": paste["content"], "language": paste["language"], "position": 0}
    sheet = await storage.get_sheet(slug, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return sheet


@api_router.post("/paste/{slug}/sheets")
async def create_sheet(slug: str, body: SheetCreateBody):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, body.editToken)
    if len(body.content) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Content too large (max 400KB)")
    if await storage.count_sheets(slug) >= MAX_SHEETS_PER_PASTE:
        raise HTTPException(status_code=400, detail=f"Too many sheets (max {MAX_SHEETS_PER_PASTE})")

    sheet_id = secrets.token_hex(6)
    existing = await storage.list_sheets(slug)
    # "main" occupies position 0 as "Page 1", so stored sheets start at 1 → "Page 2"
    n = len(existing) + 1
    name = _clean_sheet_name(body.name, f"Page {n + 1}")
    existing_names = {s["name"].lower() for s in existing}
    existing_names.add("page 1")
    if name.lower() in existing_names:
        name = f"{name} {n + 1}"

    await storage.insert_sheet(
        slug, sheet_id, name, body.content, body.language or "plaintext", n, now_utc()
    )
    await manager.broadcast(
        slug,
        {"type": "sheets-changed", "action": "created", "sheetId": sheet_id, "name": name},
    )
    return {"sheetId": sheet_id, "name": name, "position": n}


@api_router.patch("/paste/{slug}/sheets/{sheet_id}")
async def update_sheet(slug: str, sheet_id: str, body: SheetUpdateBody):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, body.editToken)
    if sheet_id == "main":
        raise HTTPException(status_code=400, detail="The first page cannot be renamed here")
    if not await storage.get_sheet(slug, sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found")

    if body.name is not None:
        await storage.rename_sheet(slug, sheet_id, _clean_sheet_name(body.name, "Page"))
    if body.language is not None:
        await storage.update_sheet_language(slug, sheet_id, body.language)
    await manager.broadcast(
        slug,
        {"type": "sheets-changed", "action": "updated", "sheetId": sheet_id},
    )
    sheet = await storage.get_sheet(slug, sheet_id)
    return {"sheetId": sheet_id, "name": sheet["name"], "language": sheet["language"]}


@api_router.delete("/paste/{slug}/sheets/{sheet_id}")
async def delete_sheet(slug: str, sheet_id: str, editToken: str = ""):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, editToken)
    if sheet_id == "main":
        raise HTTPException(status_code=400, detail="The first page cannot be deleted")
    if not await storage.get_sheet(slug, sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found")

    await storage.delete_sheet(slug, sheet_id)
    await manager.broadcast(
        slug,
        {"type": "sheets-changed", "action": "deleted", "sheetId": sheet_id},
    )
    return {"ok": True}


# ---------------- Revisions ----------------
@api_router.get("/paste/{slug}/revisions")
async def list_revisions(slug: str):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    revs = await storage.list_revisions(slug)
    return {"revisions": [{"rev": r["rev"], "createdAt": r["created_at"], "size": len(r["content"])} for r in revs]}


@api_router.get("/paste/{slug}/revisions/{rev}")
async def get_revision(slug: str, rev: int):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    r = await storage.get_revision(slug, rev)
    if not r:
        raise HTTPException(status_code=404, detail="Revision not found")
    return {"rev": r["rev"], "content": r["content"], "createdAt": r["created_at"]}


# ---------------- File endpoints (any file type) ----------------
async def _upload_file(slug: str, file: UploadFile, request: Request):
    ip = client_ip(request)
    if not limiter.allow(f"upload:{ip}", limit=60, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many uploads — try again later")
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

    await manager.broadcast(slug, {"type": "files-changed"})
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
async def upload_file(slug: str, file: UploadFile = File(...), request: Request = None):
    """Upload any file (max 100MB) attached to a paste."""
    return await _upload_file(slug, file, request)


@api_router.get("/file/{file_id}")
async def get_file(file_id: str):
    """Stream an uploaded file of any type."""
    return await _get_file(file_id)


@api_router.delete("/file/{file_id}")
async def delete_file(file_id: str):
    return await _delete_file(file_id)


# ---- Legacy image endpoints (kept for old clients / existing pastes) ----

@api_router.post("/paste/{slug}/image")
async def upload_image(slug: str, file: UploadFile = File(...), request: Request = None):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    return await _upload_file(slug, file, request)


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
        self.editors: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def join(self, slug: str, ws: WebSocket, can_edit: bool):
        async with self.lock:
            self.rooms.setdefault(slug, set()).add(ws)
            if can_edit:
                self.editors.setdefault(slug, set()).add(ws)
            return len(self.rooms[slug]), len(self.editors.get(slug, set()))

    async def leave(self, slug: str, ws: WebSocket):
        async with self.lock:
            conns = self.rooms.get(slug)
            if conns and ws in conns:
                conns.remove(ws)
            eds = self.editors.get(slug)
            if eds and ws in eds:
                eds.remove(ws)
            count = len(conns) if conns else 0
            if conns is not None and not conns:
                self.rooms.pop(slug, None)
            if eds is not None and not eds:
                self.editors.pop(slug, None)
            return count, len(self.editors.get(slug, set()))

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

    async def send_to_editors(self, slug: str, message: dict, exclude: Optional[WebSocket] = None):
        eds = list(self.editors.get(slug, set()))
        data = json.dumps(message)
        for conn in eds:
            if conn is exclude:
                continue
            try:
                await conn.send_text(data)
            except Exception:
                pass


manager = RoomManager()

MAX_YUPDATE_SIZE = 512 * 1024  # single Yjs update cap


@app.websocket("/api/ws/{slug}")
async def ws_paste(websocket: WebSocket, slug: str):
    token = websocket.query_params.get("token") or ""

    await websocket.accept()

    paste = await get_paste_doc(slug)
    if not paste:
        await websocket.send_text(
            json.dumps({"type": "error", "code": "not_found", "message": "Paste not found or expired"})
        )
        await websocket.close(code=4404)
        return

    stored = paste.get("editToken")
    can_edit = (not stored) or bool(token) and secrets.compare_digest(token, str(stored))

    await manager.join(slug, websocket, can_edit)

    init_msg = {
        "type": "init",
        "paste": {k: v for k, v in paste.items() if k != "editToken"},
        "viewers": manager.viewer_count(slug),
        "canEdit": can_edit,
    }
    yupdates = await storage.get_yupdates(slug)
    if yupdates:
        init_msg["yUpdatesB64"] = _yupdates_b64(yupdates)
    try:
        sheets = await storage.list_sheets(slug)
    except Exception:
        sheets = []
    init_msg["sheets"] = _sheets_with_main(sheets)
    await websocket.send_text(json.dumps(init_msg))
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

            # ---- writes require edit rights ----
            if (
                mtype in ("edit", "yupdate", "language", "cursor")
                or (mtype or "").startswith("s:")
            ) and not can_edit:
                await websocket.send_text(
                    json.dumps({"type": "error", "code": "read_only", "message": "This link is read-only"})
                )
                continue

            # ---- sheet open: send a sheet's stored CRDT state to this client ----
            if mtype == "s:open":
                sid = str(msg.get("sheetId") or "")
                if not re.match(r"^(main|[a-f0-9]{12})$", sid):
                    continue
                payload = {"type": "s:state", "sheetId": sid}
                if sid == "main":
                    supdates = await storage.get_yupdates(slug)
                else:
                    supdates = await storage.get_sheet_yupdates(slug, sid)
                if supdates:
                    payload["yUpdatesB64"] = _yupdates_b64(supdates)
                await websocket.send_text(json.dumps(payload))
                continue

            # ---- sheet-scoped CRDT relay ----
            if mtype == "s:yupdate":
                sid = str(msg.get("sheetId") or "")
                if not re.match(r"^(main|[a-f0-9]{12})$", sid):
                    continue
                try:
                    update = base64.b64decode(msg.get("updateB64") or "")
                except Exception:
                    continue
                if not update or len(update) > MAX_YUPDATE_SIZE:
                    continue
                if sid == "main":
                    await storage.append_yupdate(slug, update)
                else:
                    await storage.append_sheet_yupdate(slug, sid, update)
                await manager.broadcast(
                    slug,
                    {"type": "s:yupdate", "sheetId": sid, "updateB64": base64.b64encode(update).decode()},
                    exclude=websocket,
                )
                continue

            # ---- sheet-scoped full-text edit (backup channel / non-CRDT clients) ----
            if mtype == "s:edit":
                sid = str(msg.get("sheetId") or "")
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
                if sid == "main":
                    updated_at = now_utc()
                    new_rev = await storage.append_revision(slug, content, updated_at)
                    await storage.update_content(slug, content, updated_at, new_rev)
                    await storage.clear_ystate(slug)
                else:
                    if not await storage.get_sheet(slug, sid):
                        continue
                    await storage.update_sheet_content(slug, sid, content)
                    await storage.clear_sheet_ystate(slug, sid)
                await manager.broadcast(
                    slug,
                    {"type": "s:edit", "sheetId": sid, "content": content, "updatedAt": now_utc().isoformat()},
                    exclude=websocket,
                )
                continue

            # ---- sheet language ----
            if mtype == "s:language":
                sid = str(msg.get("sheetId") or "")
                lang = msg.get("language", "plaintext")
                if sid == "main":
                    await storage.update_language(slug, lang, now_utc())
                else:
                    if not await storage.get_sheet(slug, sid):
                        continue
                    await storage.update_sheet_language(slug, sid, lang)
                await manager.broadcast(
                    slug, {"type": "s:language", "sheetId": sid, "language": lang}, exclude=websocket
                )
                continue

            if mtype == "yupdate":
                # CRDT relay: store the update and fan it out. Each update is a
                # valid standalone Yjs diff — clients apply them in order.
                try:
                    update = base64.b64decode(msg.get("updateB64") or "")
                except Exception:
                    continue
                if not update or len(update) > MAX_YUPDATE_SIZE:
                    continue
                await storage.append_yupdate(slug, update)
                await manager.broadcast(
                    slug,
                    {"type": "yupdate", "updateB64": base64.b64encode(update).decode()},
                    exclude=websocket,
                )
                continue

            if mtype == "cursor":
                # Awareness relay (selection color/name) — not persisted
                await manager.broadcast(slug, {"type": "cursor", "c": msg.get("c")}, exclude=websocket)
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
                updated_at = now_utc()
                new_rev = await storage.append_revision(slug, content, updated_at)
                await storage.update_content(slug, content, updated_at, new_rev)
                # Plain-text edits and CRDT state are two views of the same doc;
                # a full-text edit invalidates pending CRDT diffs.
                await storage.clear_ystate(slug)
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
        count, _ = await manager.leave(slug, websocket)
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
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="spa-assets")

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
            # Peaceful exit: wipe this session's pastes and files
            try:
                await storage.purge_all()
            except Exception as e:
                logger.warning(f"Session cleanup on shutdown failed: {e}")
        await storage.shutdown()
