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
import hmac
import secrets
import logging
import asyncio
import mimetypes
from contextlib import asynccontextmanager
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
    Header,
    UploadFile,
    File,
    Form,
    Request,
)
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .storage import create_storage, FileTooLarge, PasteQuotaExceeded, now_utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("livepaste")

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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Modern lifespan handler (replaces the deprecated on_event hooks)."""
    global storage, _cleanup_task
    storage = create_storage()
    await storage.startup()
    if _is_ephemeral():
        # Covers force-kill: clear anything left over from a previous session
        await storage.purge_all()
    _cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
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


app = FastAPI(title="LivePaste", lifespan=_lifespan)
api_router = APIRouter(prefix="/api")

storage = None  # set on startup (see _lifespan)
_cleanup_task = None


# ---------------- Auth brute-force protection (v3.2.0) ----------------
#
# The view-password surfaces (REST unlock + WebSocket handshake) are
# unauthenticated oracles: without a cap, anyone can guess a locked paste's
# password forever. Failures are tracked per (client ip, slug); once the cap
# is hit, every attempt — even the correct password — is refused for the
# lockout window. A correct password clears the record so honest users who
# typo once are never locked out.

PW_MAX_FAILURES = 8
PW_LOCKOUT_S = 300  # 5 minutes

pw_failures: Dict[str, List[float]] = {}


def _pw_key(ip: str, slug: str) -> str:
    return f"{ip}::{slug}"


def _pw_blocked(ip: str, slug: str) -> bool:
    key = _pw_key(ip, slug)
    now = time.monotonic()
    fails = [t for t in pw_failures.get(key, []) if now - t < PW_LOCKOUT_S]
    if fails:
        pw_failures[key] = fails
    else:
        pw_failures.pop(key, None)
    return len(fails) >= PW_MAX_FAILURES


def _pw_record_failure(ip: str, slug: str) -> None:
    key = _pw_key(ip, slug)
    pw_failures.setdefault(key, []).append(time.monotonic())
    # opportunistic cleanup so the dict cannot grow without bound
    if len(pw_failures) > 4096:
        cutoff = time.monotonic() - PW_LOCKOUT_S
        for k in [k for k, v in pw_failures.items() if not v or v[-1] <= cutoff]:
            pw_failures.pop(k, None)


def _pw_clear(ip: str, slug: str) -> None:
    pw_failures.pop(_pw_key(ip, slug), None)


def ws_client_ip(websocket) -> str:
    fwd = websocket.headers.get("x-forwarded-for") if _TRUST_PROXY and hasattr(websocket, "headers") else None
    if fwd:
        return fwd.split(",")[0].strip()
    client = getattr(websocket, "client", None)
    return client.host if client else "unknown"

# ---------------- Constants ----------------
MAX_CONTENT_SIZE = 400_000  # ~400KB max paste size
MAX_SHEETS_PER_PASTE = 32
MAX_SHEET_NAME_LEN = 60
MAX_GRANTED_EDITORS = 50  # per-user edit permissions allowlist cap (v3.3.0)
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


# v3.5.1 (security): X-Forwarded-For is client-controllable. Trusting it by
# default let any caller rotate their apparent IP (defeating rate limits and
# brute-force lockouts). Only honor it behind a trusted proxy, opted in via
# LIVEPASTE_TRUST_PROXY=1 (a reverse proxy that OVERWRITES the header).
_TRUST_PROXY = os.environ.get("LIVEPASTE_TRUST_PROXY", "") in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") if _TRUST_PROXY else None
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def websocket_origin_allowed(websocket: WebSocket) -> bool:
    """Allow same-origin browsers or an explicitly configured frontend origin.

    Native clients often omit Origin, so a missing header remains supported.
    Wildcard CORS does not make arbitrary browser origins trustworthy: with the
    default wildcard setting, only the request Host's HTTP/HTTPS origins are
    accepted. Cross-origin frontend development/hosting must set CORS_ORIGINS.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    configured = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    if configured != ["*"]:
        return origin.rstrip("/") in configured
    host = websocket.headers.get("host", "")
    return origin.rstrip("/") in (f"http://{host}", f"https://{host}")


# ---------------- Models ----------------
class PasteCreate(BaseModel):
    content: str = ""
    customSlug: Optional[str] = None
    language: str = "plaintext"
    expiry: str = "never"  # 1h | 1d | 1w | never
    burnAfterViews: Optional[int] = None  # self-destruct after N distinct views
    password: Optional[str] = None  # view password (hashed before storage)


class RestoreBody(BaseModel):
    editToken: str
    content: str


class ForkBody(BaseModel):
    editToken: str = ""  # required unless the source paste is open (legacy)
    customSlug: Optional[str] = None
    expiry: str = "never"
    copyFiles: bool = True  # duplicate attachments into the fork


class SheetCreateBody(BaseModel):
    editToken: str
    name: str = ""
    content: str = ""
    language: str = "plaintext"


class SheetUpdateBody(BaseModel):
    editToken: str
    name: Optional[str] = None
    language: Optional[str] = None


class ReorderBody(BaseModel):
    editToken: str
    order: list  # sheet ids in the desired order, "main" first


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


def _allowed_editors(paste: dict) -> list:
    """ClientIds granted per-user edit permission (v3.3.0)."""
    return [e for e in (paste.get("editors") or []) if e]


def editor_capability(paste_token: str, client_id: str) -> str:
    """Derive a non-forgeable capability for a granted client identity.

    The raw clientId is public presence metadata, so it is never accepted as
    REST authorization by itself. The server derives this capability from the
    paste's secret owner token and delivers it only to the granted socket.
    """
    if not paste_token or not client_id:
        return ""
    digest = hmac.new(
        str(paste_token).encode(), str(client_id).encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def can_user_edit(
    paste: dict,
    edit_token: str = "",
    client_id: str = "",
    capability: str = "",
) -> bool:
    """Full edit-rights check used by REST, WebSocket and file endpoints.

    Legacy pastes remain open for compatibility. Token holders are owners.
    Granted editors must prove possession of the server-derived capability;
    a public clientId alone is deliberately insufficient.
    """
    token = paste.get("editToken")
    if not token:
        return True  # legacy paste — open to all
    if edit_token and secrets.compare_digest(str(edit_token), str(token)):
        return True
    if client_id and client_id in _allowed_editors(paste):
        expected = editor_capability(str(token), str(client_id))
        return bool(capability) and secrets.compare_digest(str(capability), expected)
    return False


def require_user_edit(
    paste: dict,
    edit_token: str = "",
    client_id: str = "",
    capability: str = "",
):
    if not can_user_edit(paste, edit_token, client_id, capability):
        raise HTTPException(status_code=403, detail="Edit permission required (read-only)")


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
    if body.burnAfterViews is not None:
        if not (1 <= body.burnAfterViews <= 10000):
            raise HTTPException(status_code=400, detail="burnAfterViews must be between 1 and 10000")
        paste["burnAfterViews"] = body.burnAfterViews
    if body.password:
        paste["passwordHash"] = hash_password(body.password[:200])
    await storage.insert_paste(paste)

    public = _redact_paste(paste)
    public["editToken"] = edit_token  # returned ONCE, at creation
    return public


try:
    import bcrypt as _bcrypt

    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover — fallback keeps tests running anywhere
    _HAS_BCRYPT = False


def hash_password(password: str) -> str:
    if _HAS_BCRYPT:
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    # Keep password protection strong even in minimal installs without the
    # optional bcrypt wheel. SHA-256 is retained below only for reading legacy
    # hashes; new hashes use a salted, deliberately expensive KDF available in
    # every supported Python build.
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return True
    if stored.startswith("pbkdf2$"):
        try:
            _, salt_b64, digest_b64 = stored.split("$", 2)
            salt = base64.b64decode(salt_b64, validate=True)
            expected = base64.b64decode(digest_b64, validate=True)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
            return secrets.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    if stored.startswith("sha256$"):
        # Legacy unsalted hashes remain readable so existing locked pastes do
        # not become inaccessible. New passwords never use this format.
        return secrets.compare_digest("sha256$" + hashlib.sha256(password.encode()).hexdigest(), stored)
    if _HAS_BCRYPT:
        try:
            return _bcrypt.checkpw(password.encode(), stored.encode())
        except ValueError:
            return False
    return False


def _redact_paste(paste: dict) -> dict:
    """Public paste view — never leaks the edit token, password hash or burner list."""
    return {
        k: v
        for k, v in paste.items()
        if k not in ("editToken", "passwordHash", "burnedBy", "editors")
    }


@api_router.get("/paste/{slug}")
async def get_paste(
    slug: str,
    count_view: bool = False,
    clientId: str = "",
    pw: str = "",
    view_password: Optional[str] = Header(None, alias="X-View-Password"),
):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    pw = pw or view_password or ""
    pw_hash = paste.get("passwordHash")
    if pw_hash and not check_password(pw, pw_hash):
        raise HTTPException(status_code=401, detail="Password required")
    if count_view:
        info = await storage.register_view(slug, clientId or "")
        if info:
            paste["views"] = info["views"]
            if info.get("shouldBurn"):
                # The triggering (Nth) reader still gets the content; everyone
                # after this finds the paste gone (404).
                await storage.purge_paste_files(slug)
                await storage.delete_paste(slug)
    return _redact_paste(paste)


@api_router.post("/paste/{slug}/password")
async def verify_paste_password(slug: str, body: dict, request: Request):
    """Check a view password without side effects (no view counted).

    Brute-force guarded: after 8 failed attempts from one IP, further
    attempts are refused for 5 minutes (429) — even the correct password.
    A correct password resets the counter.
    """
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    pw_hash = paste.get("passwordHash")
    if not pw_hash:
        return {"ok": True, "locked": False}
    ip = client_ip(request)
    if _pw_blocked(ip, slug):
        raise HTTPException(status_code=429, detail="Too many attempts — try again in a few minutes")
    provided = str(body.get("password") or "")
    if check_password(provided, pw_hash):
        _pw_clear(ip, slug)
        return {"ok": True, "locked": True}
    _pw_record_failure(ip, slug)
    return {"ok": False, "locked": True}


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


@api_router.post("/paste/{slug}/fork")
async def fork_paste(slug: str, body: ForkBody, request: Request):
    """Create a full independent copy of a paste — main content, language,
    extra pages, and (optionally) every attachment (v3.7.0).

    Auth: source edit token, or a granted editor clientId, or (view-only
    forks) an unlocked source. Locked sources require the view password so a
    fork cannot be used as a lock bypass.
    """
    ip = client_ip(request)
    if not limiter.allow(f"create:{ip}", limit=30, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many pastes created — try again later")

    src = await get_paste_doc(slug)
    if not src:
        raise HTTPException(status_code=404, detail="Paste not found or expired")

    pw_hash = src.get("passwordHash")
    is_editor = can_user_edit(
        src,
        body.editToken,
        request.query_params.get("clientId", ""),
        request.query_params.get("capability", ""),
    )
    if not is_editor:
        # Non-editors may fork an unlocked paste; locked ones must know the pw.
        if pw_hash and not check_password(request.query_params.get("pw", ""), pw_hash):
            raise HTTPException(status_code=403, detail="Edit token or view password required to fork")
        if body.copyFiles:
            # Copying someone's attachments is a content grab — editors only.
            body.copyFiles = False

    if body.expiry not in EXPIRY_MAP:
        raise HTTPException(status_code=400, detail="Invalid expiry option")
    if len(src.get("content", "")) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Source content too large to fork")

    new_slug = None
    if body.customSlug:
        candidate = body.customSlug.strip()
        if not SLUG_RE.match(candidate):
            raise HTTPException(status_code=400, detail="Custom link must be 3-64 chars: letters, numbers, hyphens, underscores")
        if candidate.lower() in RESERVED_SLUGS:
            raise HTTPException(status_code=400, detail="This link name is reserved, please choose another")
        if await storage.slug_exists(candidate):
            raise HTTPException(status_code=409, detail="This link is already taken, please choose another")
        new_slug = candidate
    else:
        for _ in range(10):
            candidate = gen_slug()
            if not await storage.slug_exists(candidate):
                new_slug = candidate
                break
        if not new_slug:
            raise HTTPException(status_code=500, detail="Could not generate unique link, try again")

    delta = EXPIRY_MAP[body.expiry]
    edit_token = new_edit_token()
    fork = {
        "slug": new_slug,
        "content": src.get("content", ""),
        "language": src.get("language", "plaintext"),
        "views": 0,
        "createdAt": now_utc().isoformat(),
        "updatedAt": now_utc().isoformat(),
        "expiresAt": (now_utc() + delta).isoformat() if delta else None,
        "rev": 0,
        "editToken": edit_token,
        "forkedFrom": slug,
    }
    await storage.insert_paste(fork)

    # Copy extra pages (sheets)
    copied_sheets = 0
    for sheet in await storage.list_sheets(slug):
        full = await storage.get_sheet(slug, sheet["sheetId"])
        if not full or len(full.get("content", "")) > MAX_CONTENT_SIZE:
            continue
        if await storage.count_sheets(new_slug) >= MAX_SHEETS_PER_PASTE:
            break
        sid = secrets.token_hex(6)
        await storage.insert_sheet(
            new_slug, sid, full["name"], full.get("content", ""),
            full.get("language", "plaintext"), full.get("position", 0), now_utc(),
        )
        copied_sheets += 1

    # Copy attachments (new ids so deletes never alias across pastes)
    copied_files = 0
    if body.copyFiles:
        for f in await storage.list_files(slug):
            try:
                if await storage.copy_file(f["id"], new_slug):
                    copied_files += 1
            except Exception as e:
                logger.warning(f"Fork file copy failed for {f['id']}: {e}")

    public = _redact_paste(fork)
    public["editToken"] = edit_token  # returned ONCE, at creation
    public["copiedSheets"] = copied_sheets
    public["copiedFiles"] = copied_files
    return public


@api_router.get("/paste/{slug}/sheets")
async def list_sheets(slug: str):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    sheets = await storage.list_sheets(slug)
    return {"sheets": _sheets_with_main(sheets)}


@api_router.get("/paste/{slug}/sheets/{sheet_id}")
async def get_sheet(
    slug: str,
    sheet_id: str,
    pw: str = "",
    view_password: Optional[str] = Header(None, alias="X-View-Password"),
):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    # v3.5.1 (security): locked pastes must authenticate on EVERY read path,
    # not just GET /paste/{slug} — this endpoint previously leaked sheet
    # content to anyone with the URL while the paste page showed a lock.
    pw = pw or view_password or ""
    pw_hash = paste.get("passwordHash")
    if pw_hash and not check_password(pw, pw_hash):
        raise HTTPException(status_code=401, detail="Password required")
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


@api_router.post("/paste/{slug}/sheets/reorder")
async def reorder_sheets(slug: str, body: ReorderBody):
    """Reorder pages by supplying the full sheet-id order (v3.9.0).
    "main" is always position 0; missing ids keep their relative order."""
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, body.editToken)

    existing = await storage.list_sheets(slug)
    existing_ids = [s["sheetId"] for s in existing]
    provided = [sid for sid in body.order if isinstance(sid, str)]
    # The stored sheets must appear exactly once; "main" is implicit first.
    if sorted(provided) != sorted(["main"] + existing_ids):
        raise HTTPException(status_code=400, detail='Order must contain "main" plus every current page id')
    if provided[0] != "main":
        raise HTTPException(status_code=400, detail='"main" must stay first')

    # Persist positions for the stored (non-main) sheets in their given order.
    await storage.reorder_sheets(slug, [sid for sid in provided if sid != "main"])
    await manager.broadcast(slug, {"type": "sheets-changed", "action": "reordered"})
    return {"ok": True, "order": provided}


@api_router.post("/paste/{slug}/sheets/{sheet_id}/duplicate")
async def duplicate_sheet(slug: str, sheet_id: str, body: SheetUpdateBody):
    """Duplicate a page — copy, name, language, content AND CRDT history
    (v3.8.0). The copy is inserted right after the source page."""
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_edit_token(paste, body.editToken)
    if await storage.count_sheets(slug) >= MAX_SHEETS_PER_PASTE:
        raise HTTPException(status_code=400, detail=f"Too many sheets (max {MAX_SHEETS_PER_PASTE})")

    if sheet_id == "main":
        src = {"name": "Page 1", "content": paste["content"], "language": paste["language"], "position": 0}
    else:
        src = await storage.get_sheet(slug, sheet_id)
        if not src:
            raise HTTPException(status_code=404, detail="Sheet not found")
    if len(src.get("content", "")) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Source page too large to duplicate")

    new_id = secrets.token_hex(6)
    existing = await storage.list_sheets(slug)
    # Insert directly after the source's position
    after = src.get("position", 0)
    # Positions may need compaction: shift everything below `after` down by 1
    all_positions = sorted(s.get("position", 0) for s in existing)
    def _next_free_pos():
        pos = after + 1
        while pos in all_positions:
            pos += 1
        return pos
    new_pos = _next_free_pos()

    base_name = _clean_sheet_name(f"{src['name']} copy", "Page copy")
    taken = {s["name"].lower() for s in existing}
    name = base_name
    n = 2
    while name.lower() in taken:
        name = f"{base_name} {n}"
        n += 1

    await storage.insert_sheet(
        slug, new_id, name, src.get("content", ""), src.get("language", "plaintext"),
        new_pos, now_utc(),
    )
    await storage.copy_sheet_ystate(slug, sheet_id, new_id)
    await manager.broadcast(
        slug,
        {"type": "sheets-changed", "action": "created", "sheetId": new_id, "name": name},
    )
    return {"sheetId": new_id, "name": name, "position": new_pos}


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
async def get_revision(
    slug: str,
    rev: int,
    pw: str = "",
    view_password: Optional[str] = Header(None, alias="X-View-Password"),
):
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    # v3.5.1 (security): same gate as sheets — revision content is paste
    # content and must not be readable around the lock screen.
    pw = pw or view_password or ""
    pw_hash = paste.get("passwordHash")
    if pw_hash and not check_password(pw, pw_hash):
        raise HTTPException(status_code=401, detail="Password required")
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
    except PasteQuotaExceeded as q:
        mb_used, mb_quota = q.used // (1024 * 1024), q.quota // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Paste storage quota full: {mb_used}MB of {mb_quota}MB used. Delete some files first.",
        )
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
async def upload_file(
    slug: str,
    file: UploadFile = File(...),
    request: Request = None,
    editToken: str = Form(""),
    clientId: str = Form(""),
    capability: str = Form(""),
):
    """Upload any file (max 100MB) attached to a paste."""
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_user_edit(paste, editToken, clientId, capability)
    return await _upload_file(slug, file, request)


@api_router.get("/file/{file_id}")
async def get_file(file_id: str):
    """Stream an uploaded file of any type."""
    return await _get_file(file_id)


@api_router.delete("/file/{file_id}")
async def delete_file(
    file_id: str,
    editToken: str = "",
    clientId: str = "",
    capability: str = "",
):
    """Delete an uploaded file. Requires edit rights on its paste."""
    rec = await storage.find_file(file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="File not found")
    paste = await get_paste_doc(rec.get("slug", ""))
    require_user_edit(paste or {}, editToken, clientId, capability)
    return await _delete_file(file_id)


# ---- Legacy image endpoints (kept for old clients / existing pastes) ----

@api_router.post("/paste/{slug}/image")
async def upload_image(
    slug: str,
    file: UploadFile = File(...),
    request: Request = None,
    editToken: str = Form(""),
    clientId: str = Form(""),
    capability: str = Form(""),
):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    paste = await get_paste_doc(slug)
    if not paste:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    require_user_edit(paste, editToken, clientId, capability)
    return await _upload_file(slug, file, request)


@api_router.get("/image/{image_id}")
async def get_image(image_id: str):
    return await _get_file(image_id)


@api_router.delete("/image/{image_id}")
async def delete_image(
    image_id: str,
    editToken: str = "",
    clientId: str = "",
    capability: str = "",
):
    """Legacy image-delete alias with the same authorization as /api/file.

    Older clients use this route, so it must not bypass the paste ownership
    check enforced by the canonical file endpoint.
    """
    rec = await storage.find_file(image_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="File not found")
    paste = await get_paste_doc(rec.get("slug", ""))
    require_user_edit(paste or {}, editToken, clientId, capability)
    return await _delete_file(image_id)


# ---------------- WebSocket room manager ----------------
PEER_TIMEOUT_SECONDS = 30  # presence entries older than this are treated as gone


class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self.editors: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    # ---- presence registry (clientId -> {meta, ts}) per room ----
    def peer_upsert(self, slug: str, ws: WebSocket, info: dict):
        now = time.time()
        cid = str(info.get("clientId") or "")
        if not cid:
            return
        room = self._peer_room(slug)
        entry = {
            "clientId": cid,
            "name": str(info.get("name") or "Guest")[:24],
            "color": str(info.get("color") or "#f43f5e")[:9],
            "initials": str(info.get("initials") or "?")[:2],
            "sheetId": str(info.get("sheetId") or "main")[:24],
            "ts": now,
        }
        room[cid] = entry

    def _peer_room(self, slug: str) -> Dict[str, dict]:
        if not hasattr(self, "_peers"):
            self._peers = {}
        return self._peers.setdefault(slug, {})

    def peers_snapshot(self, slug: str) -> List[dict]:
        room = self._peer_room(slug)
        now = time.time()
        return [v for v in room.values() if now - v["ts"] < PEER_TIMEOUT_SECONDS]

    def peer_remove_ws(self, slug: str, ws: WebSocket):
        cid = getattr(ws, "peerClientId", None)
        room = self._peer_room(slug)
        if cid and cid in room:
            del room[cid]

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

    async def set_editor(self, slug: str, ws: WebSocket, can_edit: bool):
        """Update one live socket's editor membership (v3.15.1).

        Permissions can change mid-session (owner grants/revokes edit); the
        room's editors set must follow, or send_to_editors keeps whispering to
        revoked users and ignores newly granted ones."""
        async with self.lock:
            eds = self.editors.setdefault(slug, set())
            if can_edit:
                eds.add(ws)
            else:
                eds.discard(ws)

    async def apply_editor_list(self, slug: str, editors: list, paste_token: str):
        """Recompute edit rights for EVERY socket in the room (v3.15.1).

        The grant/revoke handler must not just broadcast — each connection's
        server-side `canEdit` (a loop-local captured at handshake) would stay
        stale forever, so a granted editor's edits were still rejected with
        `read_only` while their UI showed unlocked. Every socket stores its
        auth token + presence clientId, so rights are recomputed here against
        the NEW allowlist and the editors set is kept in sync."""
        async with self.lock:
            room = self.rooms.get(slug) or set()
            eds = self.editors.setdefault(slug, set())
            for ws in room:
                ws.canEdit = can_user_edit(
                    {"editToken": paste_token, "editors": editors},
                    getattr(ws, "authToken", ""),
                    getattr(ws, "clientId", ""),
                    getattr(ws, "editorCapability", ""),
                )
                if ws.canEdit:
                    eds.add(ws)
                else:
                    eds.discard(ws)

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


async def _try_send(ws: WebSocket, payload: str) -> bool:
    """Best-effort send that never raises.

    A client can vanish at any moment between our sends (tab closed, network
    drop, navigation) — uvicorn raises ClientDisconnected / WebSocketDisconnect
    on the very next send. Handshake and broadcast sends must not crash the
    ASGI task for that; disconnects are the *normal* end of every socket.
    """
    try:
        await ws.send_text(payload)
        return True
    except Exception:
        return False


async def _try_close(ws: WebSocket, code: int) -> None:
    """Best-effort close that never raises (double-close raises otherwise)."""
    try:
        await ws.close(code=code)
    except Exception:
        return


def _websocket_auth(websocket: WebSocket):
    """Decode the optional lp-auth subprotocol without putting secrets in URLs."""
    for protocol in websocket.scope.get("subprotocols", []):
        if not protocol.startswith("lp-auth."):
            continue
        encoded = protocol[len("lp-auth."):]
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode())
            if isinstance(payload, dict):
                return payload, protocol
        except (ValueError, TypeError, UnicodeDecodeError):
            continue
    return {}, None


@app.websocket("/api/ws/{slug}")
async def ws_paste(websocket: WebSocket, slug: str):
    auth, auth_protocol = _websocket_auth(websocket)
    token = str(auth.get("token") or websocket.query_params.get("token") or "")
    pw = str(auth.get("password") or websocket.query_params.get("pw") or "")
    client_id = str(auth.get("clientId") or websocket.query_params.get("clientId") or "")
    capability = str(auth.get("capability") or websocket.query_params.get("capability") or "")

    await websocket.accept(subprotocol=auth_protocol)
    if not websocket_origin_allowed(websocket):
        await _try_send(websocket, json.dumps({"type": "error", "code": "origin_not_allowed", "message": "WebSocket origin is not allowed"}))
        await _try_close(websocket, 4403)
        return

    try:
        paste = await get_paste_doc(slug)
        if not paste:
            await _try_send(
                websocket,
                json.dumps({"type": "error", "code": "not_found", "message": "Paste not found or expired"}),
            )
            await _try_close(websocket, 4404)
            return

        pw_hash = paste.get("passwordHash")
        if pw_hash:
            # Same brute-force guard as the REST unlock endpoint.
            wip = ws_client_ip(websocket)
            if _pw_blocked(wip, slug):
                await _try_send(
                    websocket,
                    json.dumps({"type": "error", "code": "too_many_attempts", "message": "Too many password attempts — try again in a few minutes"}),
                )
                await _try_close(websocket, 4429)
                return
            if not check_password(pw, pw_hash):
                _pw_record_failure(wip, slug)
                await _try_send(
                    websocket,
                    json.dumps({"type": "error", "code": "password_required", "message": "This paste is locked"}),
                )
                await _try_close(websocket, 4401)
                return
            _pw_clear(wip, slug)

        # Burn-after-read: opening the room counts as a view. The triggering
        # (Nth) reader still receives the content; the paste is destroyed behind
        # them so later joiners get not_found.
        # v3.15.1: register_view counts UNIQUE viewers — a tab refresh or WS
        # reconnect no longer inflates the counter.
        burn_note = None
        view_info = await storage.register_view(slug, client_id)
        if view_info:
            if view_info.get("shouldBurn"):
                await storage.purge_paste_files(slug)
                await storage.delete_paste(slug)
            burn_note = view_info.get("burnAfterViews") or None
            # The paste doc was fetched before the view was registered; carry
            # the accurate, deduped count into the init payload.
            paste["views"] = view_info.get("views", paste.get("views", 0))

        stored = paste.get("editToken")
        is_owner = (not stored) or bool(token) and secrets.compare_digest(token, str(stored))
        # v3.3.0: per-user edit permissions — token holders (owners) can grant
        # edit rights to specific people by their presence clientId.
        can_edit = can_user_edit(paste, token, client_id, capability)
        # Carry auth on the socket so rights can be recomputed live when the
        # owner grants/revokes (see RoomManager.apply_editor_list).
        websocket.authToken = token
        websocket.clientId = client_id
        websocket.editorCapability = capability
        websocket.canEdit = can_edit

        await manager.join(slug, websocket, can_edit)
        joined = True

        init_msg = {
            "type": "init",
            "paste": _redact_paste(paste),
            "viewers": manager.viewer_count(slug),
            "canEdit": can_edit,
            "isOwner": is_owner,
            "editors": _allowed_editors(paste),
        }
        if client_id in _allowed_editors(paste) and stored:
            init_msg["editorCapability"] = editor_capability(str(stored), client_id)
        if burn_note:
            init_msg["burnAfterViews"] = burn_note
        yupdates = await storage.get_yupdates(slug)
        if yupdates:
            init_msg["yUpdatesB64"] = _yupdates_b64(yupdates)
        try:
            sheets = await storage.list_sheets(slug)
        except Exception:
            sheets = []
        init_msg["sheets"] = _sheets_with_main(sheets)
        # The client may vanish mid-handshake (fast navigation); that's normal.
        if not await _try_send(websocket, json.dumps(init_msg)):
            return
        await manager.broadcast(
            slug, {"type": "presence", "viewers": manager.viewer_count(slug)}, exclude=websocket
        )

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
            # v3.15.1: read the LIVE per-socket flag (refreshed by
            # apply_editor_list on grant/revoke), never a handshake-time local.
            if (
                mtype in ("edit", "yupdate", "language", "cursor")
                or (mtype or "").startswith("s:")
            ) and not getattr(websocket, "canEdit", False):
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
                # Live-cursor relay (editor only). The sender's identity rides
                # along; each receiver overlays the caret at the given offset.
                c = msg.get("c") or {}
                websocket.peerClientId = str(c.get("clientId") or "")[:24]
                manager.peer_upsert(
                    slug,
                    websocket,
                    {
                        "clientId": c.get("clientId"),
                        "name": c.get("name"),
                        "color": c.get("color"),
                        "initials": c.get("initials"),
                        "sheetId": c.get("sheetId"),
                    },
                )
                await manager.broadcast(
                    slug, {"type": "cursor", "c": c}, exclude=websocket
                )
                continue

            if mtype == "reaction":
                # Floating emoji reactions (v3.1.0): pure relay, editor-only.
                # The emoji + sender identity fan out to the whole room; every
                # client renders the bubble drifting up its own editor.
                r = msg.get("r") or {}
                if not getattr(websocket, "canEdit", False):
                    await websocket.send_text(
                        json.dumps({"type": "error", "code": "read_only", "message": "This link is read-only"})
                    )
                    continue
                emoji = str(r.get("emoji") or "")[:8]
                if not emoji:
                    continue
                await manager.broadcast(
                    slug,
                    {
                        "type": "reaction",
                        "r": {
                            "emoji": emoji,
                            "name": str(r.get("name") or "Guest")[:24],
                            "color": str(r.get("color") or "#35d0a5")[:16],
                            "x": max(0.0, min(1.0, float(r.get("x") or 0.5))),
                        },
                    },
                    exclude=websocket,
                )
                continue

            if mtype == "hello":
                # Presence handshake: register this peer, reply with everyone
                # else in the room, then announce the newcomer.
                info = msg.get("i") or {}
                websocket.peerClientId = str(info.get("clientId") or "")[:24]
                manager.peer_upsert(
                    slug,
                    websocket,
                    {
                        "clientId": info.get("clientId"),
                        "name": info.get("name"),
                        "color": info.get("color"),
                        "initials": info.get("initials"),
                        "sheetId": info.get("sheetId"),
                    },
                )
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "peers",
                            "p": manager.peers_snapshot(slug),
                            "viewers": manager.viewer_count(slug),
                        }
                    )
                )
                await manager.broadcast(
                    slug, {"type": "peer-joined", "p": info}, exclude=websocket
                )
                continue

            if mtype in ("grant-edit", "revoke-edit"):
                # v3.3.0: per-user edit permissions. Only token holders (or
                # legacy open pastes) may change the allowlist; every other
                # socket learns instantly via the editors broadcast.
                if not is_owner:
                    await websocket.send_text(
                        json.dumps(
                            {"type": "error", "code": "not_owner", "message": "Only the paste owner can change permissions"}
                        )
                    )
                    continue
                target = str(msg.get("clientId") or "")[:64]
                current = await get_paste_doc(slug)
                if not current:
                    await websocket.send_text(
                        json.dumps({"type": "error", "code": "expired", "message": "This paste has expired"})
                    )
                    await _try_close(websocket, 4410)
                    break
                editors = [e for e in _allowed_editors(current) if e != target]
                if mtype == "grant-edit":
                    if target and len(editors) < MAX_GRANTED_EDITORS:
                        editors.append(target)
                    else:
                        await websocket.send_text(
                            json.dumps({"type": "error", "code": "editors_full", "message": f"Too many editors (max {MAX_GRANTED_EDITORS})"})
                        )
                        continue
                await storage.update_editors(slug, editors)
                # A raw clientId is public metadata, so grant a derived
                # capability to the target socket and use it for live auth.
                target_capability = editor_capability(str(stored), target) if mtype == "grant-edit" else ""
                target_peer = None
                if target:
                    for peer in list(manager.rooms.get(slug, set())):
                        if getattr(peer, "clientId", "") == target:
                            target_peer = peer
                            peer.editorCapability = target_capability
                            break
                # v3.15.1 fix: refresh EVERY socket's live rights against the
                # new allowlist — the handshake-time value on the granted
                # peer's loop was previously stale, so its edits were rejected
                # with `read_only` even after the UI showed unlocked.
                await manager.apply_editor_list(slug, editors, stored)
                if target_peer is not None:
                    await _try_send(
                        target_peer,
                        json.dumps({"type": "editor-capability", "capability": target_capability}),
                    )
                await manager.broadcast(
                    slug, {"type": "editors", "editors": editors, "changed": target, "granted": mtype == "grant-edit"}
                )
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
        manager.peer_remove_ws(slug, websocket)
        cid = getattr(websocket, "peerClientId", None)
        count, _ = await manager.leave(slug, websocket)
        await manager.broadcast(slug, {"type": "presence", "viewers": count})
        if cid:
            await manager.broadcast(slug, {"type": "peer-left", "clientId": cid})


# ---------------- P2P LAN mode: y-webrtc signaling relay (v2.5.0) ----------------
#
# The signaling server is deliberately DUMB — it never touches document data.
# It only forwards y-webrtc's signaling envelopes between browsers that
# subscribed to the same topic ("lp:<slug>:<sheet>"), so peers can exchange
# SDP offers/answers and ICE candidates. After that, document sync flows
# DIRECTLY browser-to-browser over WebRTC data channels; the server is
# out of the data path entirely.

signaling_rooms: Dict[str, Set[WebSocket]] = {}
signaling_connections: Set[WebSocket] = set()
MAX_SIGNALING_CONNECTIONS = 512
MAX_SIGNALING_TOPICS_PER_CONNECTION = 16
MAX_SIGNALING_FRAME_BYTES = 64 * 1024
MAX_SIGNALING_PUBLISHES_PER_MINUTE = 120
SIGNALING_TOPIC_RE = re.compile(r"^lp:[a-zA-Z0-9_-]{3,64}:(?:main|[a-f0-9]{12})$")


async def _signaling_error(websocket: WebSocket, code: str, message: str):
    await _try_send(websocket, json.dumps({"type": "error", "code": code, "message": message}))


# NOTE: deliberately NOT /api/ws/signaling — that path would be shadowed by
# the /api/ws/{slug} paste route registered above it.
@app.websocket("/api/webrtc/signaling")
async def ws_signaling(websocket: WebSocket):
    """Bounded y-webrtc-compatible signaling relay.

    Signaling is not a document-data endpoint, but it is still an exposed
    relay. Bound topics, frames, publish rates, and connection count so one
    client cannot grow unbounded in-memory rooms or fan out oversized payloads.
    """
    try:
        await websocket.accept()
    except Exception:
        return  # client vanished during the upgrade handshake
    if not websocket_origin_allowed(websocket):
        await _signaling_error(websocket, "origin_not_allowed", "WebSocket origin is not allowed")
        await _try_close(websocket, 4403)
        return
    if len(signaling_connections) >= MAX_SIGNALING_CONNECTIONS:
        await _signaling_error(websocket, "capacity", "Signaling relay at capacity")
        await _try_close(websocket, 1013)
        return

    signaling_connections.add(websocket)
    topics: Set[str] = set()
    publish_window_started = time.monotonic()
    publish_count = 0
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > MAX_SIGNALING_FRAME_BYTES:
                await _signaling_error(websocket, "frame_too_large", "Signaling message is too large")
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                await _signaling_error(websocket, "invalid_json", "Signaling message must be valid JSON")
                continue
            if not isinstance(msg, dict):
                await _signaling_error(websocket, "invalid_message", "Signaling message must be an object")
                continue

            mtype = msg.get("type")
            if mtype == "subscribe":
                new_topics = msg.get("topics")
                if not isinstance(new_topics, list):
                    await _signaling_error(websocket, "invalid_topics", "topics must be an array")
                    continue
                requested = {t for t in new_topics if isinstance(t, str)}
                if len(requested) != len(new_topics) or any(not SIGNALING_TOPIC_RE.fullmatch(t) for t in requested):
                    await _signaling_error(websocket, "invalid_topic", "Invalid signaling topic")
                    continue
                if len(topics | requested) > MAX_SIGNALING_TOPICS_PER_CONNECTION:
                    await _signaling_error(websocket, "too_many_topics", "Too many signaling topics")
                    continue
                for topic in requested:
                    topics.add(topic)
                    signaling_rooms.setdefault(topic, set()).add(websocket)
                continue

            if mtype == "unsubscribe":
                remove = msg.get("topics")
                if isinstance(remove, list):
                    for topic in remove:
                        if topic in topics:
                            topics.discard(topic)
                            room = signaling_rooms.get(topic)
                            if room:
                                room.discard(websocket)
                                if not room:
                                    signaling_rooms.pop(topic, None)
                continue

            if mtype == "publish":
                now = time.monotonic()
                if now - publish_window_started >= 60:
                    publish_window_started, publish_count = now, 0
                publish_count += 1
                if publish_count > MAX_SIGNALING_PUBLISHES_PER_MINUTE:
                    await _signaling_error(websocket, "rate_limited", "Too many signaling messages")
                    continue

                topic = msg.get("topic")
                data = msg.get("data")
                if not (
                    isinstance(topic, str)
                    and SIGNALING_TOPIC_RE.fullmatch(topic)
                    and topic in topics
                    and isinstance(data, dict)
                ):
                    await _signaling_error(websocket, "invalid_publish", "Publish requires a subscribed valid topic and object data")
                    continue

                # Add from= so receivers can ignore their own echo. Keep the
                # caller's protocol identity for y-webrtc, but bound it.
                payload_data = {**data}
                sender = payload_data.get("from")
                payload_data["from"] = sender[:128] if isinstance(sender, str) else str(id(websocket))
                payload = {"type": "publish", "topic": topic, "data": payload_data}
                encoded = json.dumps(payload, separators=(",", ":"))
                if len(encoded.encode("utf-8")) > MAX_SIGNALING_FRAME_BYTES:
                    await _signaling_error(websocket, "frame_too_large", "Signaling message is too large")
                    continue

                dead = []
                for peer in list(signaling_rooms.get(topic, set())):
                    if peer is websocket:
                        continue  # client filters self-echo via data.from
                    try:
                        await peer.send_text(encoded)
                    except Exception:
                        dead.append(peer)
                for peer in dead:
                    signaling_connections.discard(peer)
                    for peer_topic in list(topics):
                        signaling_rooms.get(peer_topic, set()).discard(peer)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"signaling WS error: {e}")
    finally:
        signaling_connections.discard(websocket)
        for topic in topics:
            room = signaling_rooms.get(topic)
            if room:
                room.discard(websocket)
                if not room:
                    signaling_rooms.pop(topic, None)


app.include_router(api_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers on every response (v3.5.1).

    - X-Content-Type-Options: nosniff (defense in depth; file responses set it too)
    - Referrer-Policy: pastes often hold private URLs; don't leak them via Referer
    - X-Frame-Options / frame-ancestors: block clickjacking of the editor & lock screen
    - CSP: same-origin assets + the Pyodide CDN worker blob (v2.3.0 runnable pastes)
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=(), usb=()")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "worker-src 'self' blob:; connect-src 'self' wss: ws: https://cdn.jsdelivr.net; "
        "frame-ancestors 'self'",
    )
    return response


_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
_cors_wildcard = _cors_origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    # There are no cookie-based credentials today. Keep wildcard CORS valid
    # and non-credentialed by default; only an explicit origin allowlist may
    # opt into credentialed requests for future deployments.
    allow_credentials=not _cors_wildcard,
    allow_origins=_cors_origins,
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
        static_root = STATIC_DIR.resolve()
        try:
            inside_static = os.path.commonpath((str(candidate), str(static_root))) == str(static_root)
        except ValueError:
            inside_static = False
        if full_path and candidate.is_file() and inside_static:
            # /sw.js must ALWAYS be revalidated or updates never reach clients
            if full_path == "sw.js":
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            # everything else at the root is unhashed; revalidate each load
            return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        # v3.15.0: the HTML shell must never be served from a stale HTTP cache —
        # returning users kept loading an old bundle after a server update.
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )