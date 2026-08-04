"""Storage backends for LivePaste.

Two interchangeable backends:
  - MongoStorage   : used when MONGO_URL is configured (hosted/cloud mode)
  - SQLiteStorage  : zero-dependency local mode (SQLite + files on disk),
                     used automatically when MONGO_URL is not set.

Both expose the same async interface consumed by livepaste.core.
"""

import os
import uuid
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("livepaste.storage")

MAX_IMAGE_SIZE = 100 * 1024 * 1024  # 100MB


def now_utc():
    return datetime.now(timezone.utc)


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ImageTooLarge(Exception):
    pass


# --------------------------------------------------------------------------
# MongoDB backend (hosted mode)
# --------------------------------------------------------------------------
class MongoStorage:
    def __init__(self, mongo_url: str, db_name: str):
        from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

        self.client = AsyncIOMotorClient(mongo_url)
        self.db = self.client[db_name]
        self.images_bucket = AsyncIOMotorGridFSBucket(self.db, bucket_name="images")

    async def startup(self):
        await self.db.pastes.create_index("slug", unique=True)
        await self.db.pastes.create_index("expiresAt", expireAfterSeconds=0)

    async def shutdown(self):
        self.client.close()

    # ---- pastes ----
    async def find_paste(self, slug: str):
        doc = await self.db.pastes.find_one({"slug": slug})
        if not doc:
            return None
        return {
            "slug": doc["slug"],
            "content": doc.get("content", ""),
            "language": doc.get("language", "plaintext"),
            "views": doc.get("views", 0),
            "createdAt": _iso(doc.get("createdAt")),
            "updatedAt": _iso(doc.get("updatedAt")),
            "expiresAt": _iso(doc.get("expiresAt")),
            "rev": doc.get("rev", 0),
        }

    async def slug_exists(self, slug: str) -> bool:
        return await self.db.pastes.find_one({"slug": slug}) is not None

    async def insert_paste(self, paste: dict):
        doc = dict(paste)
        doc["createdAt"] = _parse_dt(doc["createdAt"])
        doc["updatedAt"] = _parse_dt(doc["updatedAt"])
        doc["expiresAt"] = _parse_dt(doc["expiresAt"])
        await self.db.pastes.insert_one(doc)

    async def delete_paste(self, slug: str):
        await self.db.pastes.delete_one({"slug": slug})

    async def increment_views(self, slug: str):
        await self.db.pastes.update_one({"slug": slug}, {"$inc": {"views": 1}})

    async def update_content(self, slug: str, content: str, updated_at, rev: int):
        await self.db.pastes.update_one(
            {"slug": slug},
            {"$set": {"content": content, "updatedAt": _parse_dt(updated_at), "rev": rev}},
        )

    async def update_language(self, slug: str, language: str, updated_at):
        await self.db.pastes.update_one(
            {"slug": slug},
            {"$set": {"language": language, "updatedAt": _parse_dt(updated_at)}},
        )

    # ---- images ----
    async def save_image(self, slug: str, filename: str, content_type: str, file):
        grid_in = self.images_bucket.open_upload_stream(
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
                    raise ImageTooLarge()
                await grid_in.write(chunk)
            await grid_in.close()
        except ImageTooLarge:
            raise
        except Exception:
            try:
                await grid_in.abort()
            except Exception:
                pass
            raise
        return str(grid_in._id), size

    async def open_image(self, image_id: str):
        from bson import ObjectId

        try:
            oid = ObjectId(image_id)
            stream = await self.images_bucket.open_download_stream(oid)
        except Exception:
            return None

        content_type = (stream.metadata or {}).get("contentType", "application/octet-stream")

        async def iterator():
            while True:
                chunk = await stream.readchunk()
                if not chunk:
                    break
                yield chunk

        return content_type, stream.length, iterator()

    async def delete_image(self, image_id: str) -> bool:
        from bson import ObjectId

        try:
            oid = ObjectId(image_id)
            await self.images_bucket.delete(oid)
            return True
        except Exception:
            return False

    async def purge_paste_images(self, slug: str):
        try:
            cursor = self.images_bucket.find({"metadata.slug": slug})
            async for f in cursor:
                try:
                    await self.images_bucket.delete(f._id)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Image purge failed for {slug}: {e}")

    async def purge_expired(self):
        # Mongo TTL index handles paste expiry; purge orphaned images lazily.
        return


# --------------------------------------------------------------------------
# SQLite backend (local mode — no external database needed)
# --------------------------------------------------------------------------
class SQLiteStorage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.db_path = self.data_dir / "livepaste.db"
        self._conn = None
        self._lock = asyncio.Lock()

    async def startup(self):
        import aiosqlite

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS pastes (
                slug TEXT PRIMARY KEY,
                content TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'plaintext',
                views INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                rev INTEGER NOT NULL DEFAULT 0
            )"""
        )
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL
            )"""
        )
        await self._conn.commit()

    async def shutdown(self):
        if self._conn:
            await self._conn.close()

    # ---- pastes ----
    async def find_paste(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute("SELECT * FROM pastes WHERE slug = ?", (slug,))
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "slug": row["slug"],
            "content": row["content"],
            "language": row["language"],
            "views": row["views"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "expiresAt": row["expires_at"],
            "rev": row["rev"],
        }

    async def slug_exists(self, slug: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute("SELECT 1 FROM pastes WHERE slug = ?", (slug,))
            return await cur.fetchone() is not None

    async def insert_paste(self, paste: dict):
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO pastes (slug, content, language, views, created_at, updated_at, expires_at, rev)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paste["slug"],
                    paste["content"],
                    paste["language"],
                    paste.get("views", 0),
                    _iso(paste["createdAt"]),
                    _iso(paste["updatedAt"]),
                    _iso(paste["expiresAt"]),
                    paste.get("rev", 0),
                ),
            )
            await self._conn.commit()

    async def delete_paste(self, slug: str):
        async with self._lock:
            await self._conn.execute("DELETE FROM pastes WHERE slug = ?", (slug,))
            await self._conn.commit()

    async def increment_views(self, slug: str):
        async with self._lock:
            await self._conn.execute("UPDATE pastes SET views = views + 1 WHERE slug = ?", (slug,))
            await self._conn.commit()

    async def update_content(self, slug: str, content: str, updated_at, rev: int):
        async with self._lock:
            await self._conn.execute(
                "UPDATE pastes SET content = ?, updated_at = ?, rev = ? WHERE slug = ?",
                (content, _iso(updated_at), rev, slug),
            )
            await self._conn.commit()

    async def update_language(self, slug: str, language: str, updated_at):
        async with self._lock:
            await self._conn.execute(
                "UPDATE pastes SET language = ?, updated_at = ? WHERE slug = ?",
                (language, _iso(updated_at), slug),
            )
            await self._conn.commit()

    # ---- images (files on disk, 24-hex ids compatible with the frontend) ----
    async def save_image(self, slug: str, filename: str, content_type: str, file):
        image_id = uuid.uuid4().hex[:24]
        path = self.images_dir / image_id
        size = 0
        try:
            with open(path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_IMAGE_SIZE:
                        raise ImageTooLarge()
                    out.write(chunk)
        except ImageTooLarge:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            raise

        async with self._lock:
            await self._conn.execute(
                "INSERT INTO images (id, slug, name, content_type, size, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (image_id, slug, filename, content_type, size, now_utc().isoformat()),
            )
            await self._conn.commit()
        return image_id, size

    async def open_image(self, image_id: str):
        async with self._lock:
            cur = await self._conn.execute("SELECT * FROM images WHERE id = ?", (image_id,))
            row = await cur.fetchone()
        if not row:
            return None
        path = self.images_dir / image_id
        if not path.exists():
            return None

        async def iterator():
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return row["content_type"], row["size"], iterator()

    async def delete_image(self, image_id: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute("SELECT 1 FROM images WHERE id = ?", (image_id,))
            exists = await cur.fetchone() is not None
            if exists:
                await self._conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
                await self._conn.commit()
        (self.images_dir / image_id).unlink(missing_ok=True)
        return exists

    async def purge_paste_images(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute("SELECT id FROM images WHERE slug = ?", (slug,))
            rows = await cur.fetchall()
            await self._conn.execute("DELETE FROM images WHERE slug = ?", (slug,))
            await self._conn.commit()
        for row in rows:
            (self.images_dir / row["id"]).unlink(missing_ok=True)

    async def purge_expired(self):
        """Delete expired pastes and their images (SQLite has no TTL index)."""
        now = now_utc().isoformat()
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT slug FROM pastes WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
            )
            slugs = [row["slug"] for row in await cur.fetchall()]
        for slug in slugs:
            await self.purge_paste_images(slug)
            await self.delete_paste(slug)
        if slugs:
            logger.info(f"Purged {len(slugs)} expired paste(s)")


def create_storage():
    """Pick the backend from the environment.

    MONGO_URL set   -> MongoStorage (hosted mode)
    otherwise       -> SQLiteStorage in LIVEPASTE_DATA_DIR (default ~/.livepaste)
    """
    mongo_url = os.environ.get("MONGO_URL")
    if mongo_url:
        db_name = os.environ.get("DB_NAME", "livepaste")
        logger.info("Storage: MongoDB (hosted mode)")
        return MongoStorage(mongo_url, db_name)

    data_dir = Path(os.environ.get("LIVEPASTE_DATA_DIR", Path.home() / ".livepaste"))
    logger.info(f"Storage: SQLite (local mode) at {data_dir}")
    return SQLiteStorage(data_dir)
