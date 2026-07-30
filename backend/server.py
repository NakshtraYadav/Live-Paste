from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId
import os
import re
import json
import random
import string
import logging
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, Dict, Set
from datetime import datetime, timezone, timedelta

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
images_bucket = AsyncIOMotorGridFSBucket(db, bucket_name="images")

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------- Constants ----------------
MAX_CONTENT_SIZE = 400_000  # ~400KB max paste size
MAX_IMAGE_SIZE = 100 * 1024 * 1024  # 100MB max per image
RESERVED_SLUGS = {"api", "ws", "static", "assets", "favicon.ico", "robots.txt", "index.html", "manifest.json", "new", "about"}
SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")
EXPIRY_MAP = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None,
}

# ---------------- Helpers ----------------

def now_utc():
    return datetime.now(timezone.utc)


def gen_slug(length: int = 7) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=length))


def serialize_paste(doc: dict) -> dict:
    """Convert Mongo doc to JSON-safe dict."""
    if not doc:
        return None
    out = {
        "slug": doc["slug"],
        "content": doc.get("content", ""),
        "language": doc.get("language", "plaintext"),
        "views": doc.get("views", 0),
        "createdAt": doc["createdAt"].isoformat() if isinstance(doc.get("createdAt"), datetime) else doc.get("createdAt"),
        "updatedAt": doc["updatedAt"].isoformat() if isinstance(doc.get("updatedAt"), datetime) else doc.get("updatedAt"),
        "expiresAt": doc["expiresAt"].isoformat() if isinstance(doc.get("expiresAt"), datetime) else doc.get("expiresAt"),
        "rev": doc.get("rev", 0),
    }
    return out


def is_expired(doc: dict) -> bool:
    exp = doc.get("expiresAt")
    if exp is None:
        return False
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < now_utc()


async def purge_paste_images(slug: str):
    """Delete all GridFS images attached to a paste."""
    try:
        cursor = images_bucket.find({"metadata.slug": slug})
        async for f in cursor:
            try:
                await images_bucket.delete(f._id)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Image purge failed for {slug}: {e}")


async def get_paste_doc(slug: str):
    doc = await db.pastes.find_one({"slug": slug})
    if doc and is_expired(doc):
        await db.pastes.delete_one({"slug": slug})
        await purge_paste_images(slug)
        return None
    return doc


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
            raise HTTPException(status_code=400, detail="Custom link must be 3-64 chars: letters, numbers, hyphens, underscores")
        if candidate.lower() in RESERVED_SLUGS:
            raise HTTPException(status_code=400, detail="This link name is reserved, please choose another")
        existing = await get_paste_doc(candidate)
        if existing:
            raise HTTPException(status_code=409, detail="This link is already taken, please choose another")
        slug = candidate
    else:
        for _ in range(10):
            candidate = gen_slug()
            if not await db.pastes.find_one({"slug": candidate}):
                slug = candidate
                break
        if not slug:
            raise HTTPException(status_code=500, detail="Could not generate unique link, try again")

    delta = EXPIRY_MAP[body.expiry]
    expires_at = (now_utc() + delta) if delta else None

    doc = {
        "slug": slug,
        "content": body.content,
        "language": body.language or "plaintext",
        "views": 0,
        "createdAt": now_utc(),
        "updatedAt": now_utc(),
        "expiresAt": expires_at,
        "rev": 0,
    }
    await db.pastes.insert_one(doc)
    return serialize_paste(doc)


@api_router.get("/paste/{slug}")
async def get_paste(slug: str, count_view: bool = False):
    doc = await get_paste_doc(slug)
    if not doc:
        raise HTTPException(status_code=404, detail="Paste not found or expired")
    if count_view:
        await db.pastes.update_one({"slug": slug}, {"$inc": {"views": 1}})
        doc["views"] = doc.get("views", 0) + 1
    return serialize_paste(doc)


# ---------------- Image endpoints (GridFS) ----------------
@api_router.post("/paste/{slug}/image")
async def upload_image(slug: str, file: UploadFile = File(...)):
    doc = await get_paste_doc(slug)
    if not doc:
        raise HTTPException(status_code=404, detail="Paste not found or expired")

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    filename = file.filename or "image"
    grid_in = images_bucket.open_upload_stream(
        filename,
        metadata={
            "slug": slug,
            "contentType": content_type,
            "uploadedAt": now_utc().isoformat(),
        },
    )
    size = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_IMAGE_SIZE:
                await grid_in.abort()
                raise HTTPException(status_code=413, detail="Image too large (max 100MB)")
            await grid_in.write(chunk)
        await grid_in.close()
    except HTTPException:
        raise
    except Exception as e:
        try:
            await grid_in.abort()
        except Exception:
            pass
        logger.error(f"Image upload failed for {slug}: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed, please try again")

    image_id = str(grid_in._id)
    return {
        "id": image_id,
        "url": f"/api/image/{image_id}",
        "name": filename,
        "size": size,
        "contentType": content_type,
    }


@api_router.get("/image/{image_id}")
async def get_image(image_id: str):
    try:
        oid = ObjectId(image_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        stream = await images_bucket.open_download_stream(oid)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

    content_type = (stream.metadata or {}).get("contentType", "application/octet-stream")

    async def iterator():
        while True:
            chunk = await stream.readchunk()
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        iterator(),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Length": str(stream.length),
        },
    )


@api_router.delete("/image/{image_id}")
async def delete_image(image_id: str):
    try:
        oid = ObjectId(image_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        await images_bucket.delete(oid)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


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

    doc = await get_paste_doc(slug)
    if not doc:
        await websocket.send_text(json.dumps({"type": "error", "code": "not_found", "message": "Paste not found or expired"}))
        await websocket.close(code=4404)
        return

    await manager.join(slug, websocket)

    # Send initial state
    await websocket.send_text(json.dumps({
        "type": "init",
        "paste": serialize_paste(doc),
        "viewers": manager.viewer_count(slug),
    }))
    # Notify others of presence
    await manager.broadcast(slug, {"type": "presence", "viewers": manager.viewer_count(slug)}, exclude=websocket)

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
                    await websocket.send_text(json.dumps({"type": "error", "code": "too_large", "message": "Content too large (max 400KB)"}))
                    continue
                current = await get_paste_doc(slug)
                if not current:
                    await websocket.send_text(json.dumps({"type": "error", "code": "expired", "message": "This paste has expired"}))
                    await websocket.close(code=4410)
                    break
                new_rev = current.get("rev", 0) + 1
                updated_at = now_utc()
                await db.pastes.update_one(
                    {"slug": slug},
                    {"$set": {"content": content, "updatedAt": updated_at, "rev": new_rev}},
                )
                await manager.broadcast(slug, {
                    "type": "edit",
                    "content": content,
                    "rev": new_rev,
                    "updatedAt": updated_at.isoformat(),
                }, exclude=websocket)
                continue

            if mtype == "language":
                lang = msg.get("language", "plaintext")
                await db.pastes.update_one({"slug": slug}, {"$set": {"language": lang, "updatedAt": now_utc()}})
                await manager.broadcast(slug, {"type": "language", "language": lang}, exclude=websocket)
                continue

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS error on {slug}: {e}")
    finally:
        count = await manager.leave(slug, websocket)
        await manager.broadcast(slug, {"type": "presence", "viewers": count})


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def ensure_indexes():
    await db.pastes.create_index("slug", unique=True)
    # TTL index for automatic cleanup of expired pastes
    await db.pastes.create_index("expiresAt", expireAfterSeconds=0)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
