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

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB (any file type)
MAX_REVISIONS_PER_PASTE = 50  # snapshot cap; oldest pruned
MAX_PASTE_STORAGE = 500 * 1024 * 1024  # per-paste attachments quota (all files summed)


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


class FileTooLarge(Exception):
    """A single upload exceeded MAX_FILE_SIZE."""


class PasteQuotaExceeded(Exception):
    """The paste's total attachment storage would exceed MAX_PASTE_STORAGE."""

    def __init__(self, used: int, quota: int):
        super().__init__(f"quota {quota} exceeded (used {used})")
        self.used = used
        self.quota = quota
    pass


# Backwards-compatible alias
ImageTooLarge = FileTooLarge


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
        await self.db.revisions.create_index("slug", unique=True)
        await self.db.ystate.create_index("slug", unique=True)
        await self.db.sheets.create_index([("slug", 1), ("sheetId", 1)], unique=True)
        await self.db.ystate_sheets.create_index([("slug", 1), ("sheetId", 1)], unique=True)

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
            "editToken": doc.get("editToken"),
            "editors": doc.get("editors") or [],
            "burnAfterViews": doc.get("burnAfterViews"),
            "passwordHash": doc.get("passwordHash"),
            "burnedBy": doc.get("burnedBy") or [],
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
        await self.db.revisions.delete_one({"slug": slug})
        await self.db.ystate.delete_one({"slug": slug})
        await self.db.sheets.delete_many({"slug": slug})
        await self.db.ystate_sheets.delete_many({"slug": slug})

    async def update_editors(self, slug: str, editors: list):
        """Replace the per-user edit-permission allowlist (v3.3.0)."""
        clean = [str(e)[:64] for e in editors if e][:200]
        await self.db.pastes.update_one(
            {"slug": slug}, {"$set": {"editors": clean}}
        )

    async def increment_views(self, slug: str):
        await self.db.pastes.update_one({"slug": slug}, {"$inc": {"views": 1}})

    async def register_view(self, slug: str, client_id: str):
        """Mongo twin of SQLiteStorage.register_view (see there)."""
        doc = await self.db.pastes.find_one(
            {"slug": slug}, {"burnAfterViews": 1, "burnedBy": 1, "views": 1}
        )
        if not doc:
            return None
        burn_after = doc.get("burnAfterViews") or 0
        burners = doc.get("burnedBy") or []
        if burn_after and client_id and client_id not in burners:
            burners = burners + [client_id]
            await self.db.pastes.update_one(
                {"slug": slug}, {"$set": {"burnedBy": burners[-2000:]}}
            )
        await self.db.pastes.update_one({"slug": slug}, {"$inc": {"views": 1}})
        return {
            "views": doc.get("views", 0) + 1,
            "burnAfterViews": burn_after,
            "burners": len(burners),
            "shouldBurn": bool(burn_after and len(burners) >= burn_after),
        }

    async def update_password(self, slug: str, password_hash):
        await self.db.pastes.update_one(
            {"slug": slug}, {"$set": {"passwordHash": password_hash}}
        )

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

    # ---- files (any type; historically "images" — GridFS bucket kept for compatibility) ----
    async def paste_usage(self, slug: str) -> int:
        """Total attachment bytes stored for a paste (per-paste quota, v3.6.0)."""
        from bson.int64 import Int64

        pipeline = [
            {"$match": {"metadata.slug": slug}},
            {"$group": {"_id": None, "total": {"$sum": "$length"}}},
        ]
        rows = await self.db["images.files"].find(pipeline).to_list(1)
        return int(rows[0]["total"]) if rows else 0

    async def save_file(self, slug: str, filename: str, content_type: str, file):
        grid_in = self.images_bucket.open_upload_stream(
            filename,
            metadata={
                "slug": slug,
                "contentType": content_type,
                "uploadedAt": now_utc().isoformat(),
            },
        )
        size = 0
        used = await self.paste_usage(slug)
        try:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    await grid_in.abort()
                    raise FileTooLarge()
                if used + size > MAX_PASTE_STORAGE:
                    await grid_in.abort()
                    raise PasteQuotaExceeded(used + size, MAX_PASTE_STORAGE)
                await grid_in.write(chunk)
            await grid_in.close()
        except FileTooLarge:
            raise
        except PasteQuotaExceeded:
            raise
        except Exception:
            try:
                await grid_in.abort()
            except Exception:
                pass
            raise
        return str(grid_in._id), size

    # Legacy alias
    save_image = save_file

    async def open_file(self, file_id: str):
        from bson import ObjectId

        try:
            oid = ObjectId(file_id)
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

        return content_type, stream.length, iterator(), stream.filename

    async def delete_file(self, file_id: str) -> bool:
        from bson import ObjectId

        try:
            oid = ObjectId(file_id)
            await self.images_bucket.delete(oid)
            return True
        except Exception:
            return False

    async def find_file(self, file_id: str):
        """Metadata lookup (slug) used to authorize file deletes (v3.3.0)."""
        from bson import ObjectId

        try:
            docs = await self.images_bucket.find({"_id": ObjectId(file_id)}).to_list(1)
            return docs[0] if docs else None
        except Exception:
            return None

    async def list_files(self, slug: str):
        """Attachment metadata for a paste (used by fork/export — v3.7.0)."""
        rows = await self.db["images.files"].find(
            {"metadata.slug": slug}, {"_id": 1, "filename": 1, "length": 1, "metadata.contentType": 1}
        ).to_list(1000)
        return [
            {
                "id": str(r["_id"]),
                "name": r.get("filename", "file"),
                "contentType": (r.get("metadata") or {}).get("contentType"),
                "size": r.get("length", 0),
            }
            for r in rows
        ]

    async def copy_file(self, file_id: str, new_slug: str):
        """Duplicate an attachment under a new id for a forked paste (v3.7.0)."""
        from bson import ObjectId

        try:
            oid = ObjectId(file_id)
            stream = await self.images_bucket.open_download_stream(oid)
        except Exception:
            return None
        metadata = stream.metadata or {}
        grid_in = self.images_bucket.open_upload_stream(
            stream.filename or "file",
            metadata={
                "slug": new_slug,
                "contentType": metadata.get("contentType", "application/octet-stream"),
                "uploadedAt": now_utc().isoformat(),
            },
        )
        try:
            while True:
                chunk = await stream.readchunk()
                if not chunk:
                    break
                await grid_in.write(chunk)
            await grid_in.close()
        except Exception:
            try:
                await grid_in.abort()
            except Exception:
                pass
            raise
        return str(grid_in._id)

    # Legacy alias
    delete_image = delete_file

    async def purge_paste_files(self, slug: str):
        try:
            cursor = self.images_bucket.find({"metadata.slug": slug})
            async for f in cursor:
                try:
                    await self.images_bucket.delete(f._id)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Image purge failed for {slug}: {e}")

    # ---- sheets (multiple pages per paste) ----
    async def list_sheets(self, slug: str):
        cursor = self.db.sheets.find({"slug": slug}).sort("position", 1)
        return [
            {"sheetId": d["sheetId"], "name": d["name"], "position": d.get("position", 0)}
            async for d in cursor
        ]

    async def get_sheet(self, slug: str, sheet_id: str):
        d = await self.db.sheets.find_one({"slug": slug, "sheetId": sheet_id})
        if not d:
            return None
        return {
            "sheetId": d["sheetId"],
            "name": d["name"],
            "content": d.get("content", ""),
            "language": d.get("language", "plaintext"),
            "position": d.get("position", 0),
        }

    async def insert_sheet(self, slug: str, sheet_id: str, name: str, content: str,
                           language: str, position: int, created_at):
        await self.db.sheets.insert_one(
            {
                "slug": slug,
                "sheetId": sheet_id,
                "name": name,
                "content": content,
                "language": language,
                "position": position,
                "createdAt": _parse_dt(created_at),
            }
        )

    async def rename_sheet(self, slug: str, sheet_id: str, name: str):
        await self.db.sheets.update_one(
            {"slug": slug, "sheetId": sheet_id}, {"$set": {"name": name}}
        )

    async def update_sheet_language(self, slug: str, sheet_id: str, language: str):
        await self.db.sheets.update_one(
            {"slug": slug, "sheetId": sheet_id}, {"$set": {"language": language}}
        )

    async def update_sheet_content(self, slug: str, sheet_id: str, content: str):
        await self.db.sheets.update_one(
            {"slug": slug, "sheetId": sheet_id}, {"$set": {"content": content}}
        )

    async def reorder_sheets(self, slug: str, sheet_ids: list):
        for pos, sid in enumerate(sheet_ids):
            await self.db.sheets.update_one(
                {"slug": slug, "sheetId": sid}, {"$set": {"position": pos}}
            )

    async def delete_sheet(self, slug: str, sheet_id: str):
        await self.db.sheets.delete_one({"slug": slug, "sheetId": sheet_id})
        await self.db.ystate_sheets.delete_one({"slug": slug, "sheetId": sheet_id})

    async def count_sheets(self, slug: str) -> int:
        return await self.db.sheets.count_documents({"slug": slug})

    # ---- CRDT state for sheets ----
    async def get_sheet_yupdates(self, slug: str, sheet_id: str):
        d = await self.db.ystate_sheets.find_one({"slug": slug, "sheetId": sheet_id})
        return (d or {}).get("updates", [])

    async def append_sheet_yupdate(self, slug: str, sheet_id: str, update: bytes):
        await self.db.ystate_sheets.update_one(
            {"slug": slug, "sheetId": sheet_id},
            {"$push": {"updates": {"$each": [update], "$slice": -1000}}},
            upsert=True,
        )

    async def clear_sheet_ystate(self, slug: str, sheet_id: str):
        await self.db.ystate_sheets.delete_one({"slug": slug, "sheetId": sheet_id})

    async def purge_expired(self):
        # Mongo TTL index handles paste expiry; purge orphaned files lazily.
        return

    # ---- revisions (Mongo: capped child docs) ----
    async def append_revision(self, slug: str, content: str, updated_at) -> int:
        current = await self.db.pastes.find_one({"slug": slug}, {"rev": 1})
        rev = (current.get("rev", 0) if current else 0) + 1
        await self.db.revisions.update_one(
            {"slug": slug},
            {
                "$push": {
                    "snapshots": {
                        "$each": [{"rev": rev, "content": content, "created_at": _iso(updated_at)}],
                        "$slice": -MAX_REVISIONS_PER_PASTE,
                    }
                }
            },
            upsert=True,
        )
        return rev

    async def list_revisions(self, slug: str):
        doc = await self.db.revisions.find_one({"slug": slug})
        return (doc or {}).get("snapshots", [])

    async def get_revision(self, slug: str, rev: int):
        doc = await self.db.revisions.find_one(
            {"slug": slug, "snapshots.rev": rev}, {"snapshots.$": 1}
        )
        snaps = (doc or {}).get("snapshots", [])
        return snaps[0] if snaps else None

    # ---- CRDT (Yjs) state: ordered list of composable updates ----
    MAX_YUPDATES_STORED = 1000

    async def get_yupdates(self, slug: str):
        doc = await self.db.ystate.find_one({"slug": slug})
        return (doc or {}).get("updates", [])

    async def append_yupdate(self, slug: str, update: bytes):
        await self.db.ystate.update_one(
            {"slug": slug},
            {"$push": {"updates": {"$each": [update], "$slice": -self.MAX_YUPDATES_STORED}}},
            upsert=True,
        )

    async def clear_ystate(self, slug: str):
        await self.db.ystate.delete_one({"slug": slug})

    async def purge_all(self):
        # Never wipe hosted data — ephemeral mode is a local (SQLite) feature.
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
                rev INTEGER NOT NULL DEFAULT 0,
                edit_token TEXT,
                editors TEXT,
                burn_after_views INTEGER,
                password_hash TEXT,
                burned_by TEXT
            )"""
        )
        # Migration for pre-v2.8 databases
        for col, ddl in (
            ("burn_after_views", "ALTER TABLE pastes ADD COLUMN burn_after_views INTEGER"),
            ("password_hash", "ALTER TABLE pastes ADD COLUMN password_hash TEXT"),
            ("burned_by", "ALTER TABLE pastes ADD COLUMN burned_by TEXT"),
            ("editors", "ALTER TABLE pastes ADD COLUMN editors TEXT"),
        ):
            try:
                await self._conn.execute(ddl)
            except Exception:
                pass  # column already exists
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
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS revisions (
                slug TEXT NOT NULL,
                rev INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (slug, rev)
            )"""
        )
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS ystate (
                slug TEXT NOT NULL,
                idx INTEGER NOT NULL,
                "update" BLOB NOT NULL,
                PRIMARY KEY (slug, idx)
            )"""
        )
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS sheets (
                slug TEXT NOT NULL,
                sheet_id TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'plaintext',
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (slug, sheet_id)
            )"""
        )
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS ystate_sheets (
                slug TEXT NOT NULL,
                sheet_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                "update" BLOB NOT NULL,
                PRIMARY KEY (slug, sheet_id, idx)
            )"""
        )
        # Migrations for databases created before v2.0
        cur = await self._conn.execute("PRAGMA table_info(pastes)")
        cols = {row[1] for row in await cur.fetchall()}
        if "edit_token" not in cols:
            await self._conn.execute("ALTER TABLE pastes ADD COLUMN edit_token TEXT")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revisions_slug ON revisions(slug, rev DESC)"
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
            "editToken": row["edit_token"],
            "editors": (row["editors"] or "").split(",") if row["editors"] else [],
            "burnAfterViews": row["burn_after_views"],
            "passwordHash": row["password_hash"],
            "burnedBy": (row["burned_by"] or "").split(",") if row["burned_by"] else [],
        }

    async def update_editors(self, slug: str, editors: list):
        """Replace the per-user edit-permission allowlist (v3.3.0)."""
        clean = [str(e)[:64] for e in editors if e][:200]
        async with self._lock:
            await self._conn.execute(
                "UPDATE pastes SET editors = ? WHERE slug = ?",
                (",".join(clean), slug),
            )
            await self._conn.commit()

    async def slug_exists(self, slug: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute("SELECT 1 FROM pastes WHERE slug = ?", (slug,))
            return await cur.fetchone() is not None

    async def insert_paste(self, paste: dict):
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO pastes (slug, content, language, views, created_at, updated_at, expires_at, rev, edit_token, editors, burn_after_views, password_hash, burned_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paste["slug"],
                    paste["content"],
                    paste["language"],
                    paste.get("views", 0),
                    _iso(paste["createdAt"]),
                    _iso(paste["updatedAt"]),
                    _iso(paste["expiresAt"]),
                    paste.get("rev", 0),
                    paste.get("editToken"),
                    ",".join(paste.get("editors") or []),
                    paste.get("burnAfterViews"),
                    paste.get("passwordHash"),
                    ",".join(paste.get("burnedBy") or []),
                ),
            )
            await self._conn.commit()

    async def delete_paste(self, slug: str):
        async with self._lock:
            await self._conn.execute("DELETE FROM pastes WHERE slug = ?", (slug,))
            await self._conn.execute("DELETE FROM revisions WHERE slug = ?", (slug,))
            await self._conn.execute("DELETE FROM ystate WHERE slug = ?", (slug,))
            await self._conn.execute("DELETE FROM sheets WHERE slug = ?", (slug,))
            await self._conn.execute("DELETE FROM ystate_sheets WHERE slug = ?", (slug,))
            await self._conn.commit()

    async def increment_views(self, slug: str):
        async with self._lock:
            await self._conn.execute("UPDATE pastes SET views = views + 1 WHERE slug = ?", (slug,))
            await self._conn.commit()

    async def register_view(self, slug: str, client_id: str):
        """Count a view; for burn-after-read pastes also record unique burners.

        Returns None when the paste is gone, else a dict with `shouldBurn`
        (True once the number of distinct viewers reached burnAfterViews).
        """
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT burn_after_views, burned_by, views FROM pastes WHERE slug = ?", (slug,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            burn_after = row["burn_after_views"] or 0
            burners = (row["burned_by"] or "").split(",") if row["burned_by"] else []
            if burn_after and client_id and client_id not in burners:
                burners.append(client_id)
                await self._conn.execute(
                    "UPDATE pastes SET burned_by = ? WHERE slug = ?",
                    (",".join(burners[:2000]), slug),
                )
            await self._conn.execute("UPDATE pastes SET views = views + 1 WHERE slug = ?", (slug,))
            await self._conn.commit()
            return {
                "views": row["views"] + 1,
                "burnAfterViews": burn_after,
                "burners": len(burners),
                "shouldBurn": bool(burn_after and len(burners) >= burn_after),
            }

    async def update_password(self, slug: str, password_hash):
        async with self._lock:
            await self._conn.execute(
                "UPDATE pastes SET password_hash = ? WHERE slug = ?", (password_hash, slug)
            )
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

    # ---- files (any type; stored on disk, 24-hex ids compatible with the frontend) ----
    async def paste_usage(self, slug: str) -> int:
        """Total attachment bytes stored for a paste (per-paste quota, v3.6.0)."""
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT COALESCE(SUM(size), 0) FROM images WHERE slug = ?", (slug,)
            )
            row = await cur.fetchone()
        return int(row[0] or 0) if row else 0

    async def save_file(self, slug: str, filename: str, content_type: str, file):
        file_id = uuid.uuid4().hex[:24]
        path = self.images_dir / file_id
        size = 0
        used = await self.paste_usage(slug)
        try:
            with open(path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_SIZE:
                        raise FileTooLarge()
                    if used + size > MAX_PASTE_STORAGE:
                        raise PasteQuotaExceeded(used + size, MAX_PASTE_STORAGE)
                    out.write(chunk)
        except FileTooLarge:
            path.unlink(missing_ok=True)
            raise
        except PasteQuotaExceeded:
            path.unlink(missing_ok=True)
            raise
        except Exception:
            path.unlink(missing_ok=True)
            raise

        async with self._lock:
            await self._conn.execute(
                "INSERT INTO images (id, slug, name, content_type, size, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (file_id, slug, filename, content_type, size, now_utc().isoformat()),
            )
            await self._conn.commit()
        return file_id, size

    # Legacy alias
    save_image = save_file

    async def open_file(self, file_id: str):
        async with self._lock:
            cur = await self._conn.execute("SELECT * FROM images WHERE id = ?", (file_id,))
            row = await cur.fetchone()
        if not row:
            return None
        path = self.images_dir / file_id
        if not path.exists():
            return None

        async def iterator():
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return row["content_type"], row["size"], iterator(), row["name"]

    async def delete_file(self, file_id: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute("SELECT 1 FROM images WHERE id = ?", (file_id,))
            exists = await cur.fetchone() is not None
            if exists:
                await self._conn.execute("DELETE FROM images WHERE id = ?", (file_id,))
                await self._conn.commit()
        (self.images_dir / file_id).unlink(missing_ok=True)
        return exists

    async def find_file(self, file_id: str):
        """Metadata lookup (slug) used to authorize file deletes (v3.3.0)."""
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT id, slug FROM images WHERE id = ?", (file_id,)
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_files(self, slug: str):
        """Attachment metadata for a paste (used by fork/export — v3.7.0)."""
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT id, name, content_type, size FROM images WHERE slug = ? ORDER BY uploaded_at ASC",
                (slug,),
            )
            return [
                {"id": r["id"], "name": r["name"], "contentType": r["content_type"], "size": r["size"]}
                for r in await cur.fetchall()
            ]

    async def copy_file(self, file_id: str, new_slug: str):
        """Duplicate an attachment under a new id for a forked paste (v3.7.0).
        Returns the new file id, or None when the source is missing."""
        async with self._lock:
            cur = await self._conn.execute("SELECT * FROM images WHERE id = ?", (file_id,))
            row = await cur.fetchone()
        if not row:
            return None
        src = self.images_dir / file_id
        if not src.exists():
            return None
        new_id = uuid.uuid4().hex[:24]
        (self.images_dir / new_id).write_bytes(src.read_bytes())
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO images (id, slug, name, content_type, size, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id, new_slug, row["name"], row["content_type"], row["size"], now_utc().isoformat()),
            )
            await self._conn.commit()
        return new_id

    # Legacy alias
    delete_image = delete_file

    async def purge_paste_files(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute("SELECT id FROM images WHERE slug = ?", (slug,))
            rows = await cur.fetchall()
            await self._conn.execute("DELETE FROM images WHERE slug = ?", (slug,))
            await self._conn.commit()
        for row in rows:
            (self.images_dir / row["id"]).unlink(missing_ok=True)

    # ---- revisions (snapshot history, capped per paste) ----
    async def append_revision(self, slug: str, content: str, updated_at) -> int:
        async with self._lock:
            cur = await self._conn.execute("SELECT rev FROM pastes WHERE slug = ?", (slug,))
            row = await cur.fetchone()
            rev = (row["rev"] if row else 0) + 1
            await self._conn.execute(
                "INSERT OR REPLACE INTO revisions (slug, rev, content, created_at) VALUES (?, ?, ?, ?)",
                (slug, rev, content, _iso(updated_at)),
            )
            # Prune: keep only the newest MAX_REVISIONS_PER_PASTE snapshots
            await self._conn.execute(
                """DELETE FROM revisions WHERE slug = ? AND rev NOT IN (
                    SELECT rev FROM revisions WHERE slug = ? ORDER BY rev DESC LIMIT ?
                )""",
                (slug, slug, MAX_REVISIONS_PER_PASTE),
            )
            await self._conn.commit()
        return rev

    async def list_revisions(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT rev, content, created_at FROM revisions WHERE slug = ? ORDER BY rev DESC",
                (slug,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_revision(self, slug: str, rev: int):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT rev, content, created_at FROM revisions WHERE slug = ? AND rev = ?",
                (slug, rev),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    # ---- CRDT (Yjs) state: ordered list of composable updates ----
    # Each stored blob is ONE valid Yjs update. Clients apply them in order —
    # Yjs updates are commutative, so ordered replay converges without needing
    # a server-side merge library.
    MAX_YUPDATES_STORED = 1000

    async def get_yupdates(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute(
                'SELECT "update" FROM ystate WHERE slug = ? ORDER BY idx ASC', (slug,)
            )
            return [r["update"] for r in await cur.fetchall()]

    async def append_yupdate(self, slug: str, update: bytes):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 FROM ystate WHERE slug = ?", (slug,)
            )
            idx = (await cur.fetchone())[0]
            if idx >= self.MAX_YUPDATES_STORED:
                # Compact: drop the oldest half (clients recover via full sync)
                await self._conn.execute(
                    "DELETE FROM ystate WHERE slug = ? AND idx < ?", (slug, idx // 2)
                )
                cur = await self._conn.execute(
                    "SELECT COALESCE(MAX(idx), -1) + 1 FROM ystate WHERE slug = ?", (slug,)
                )
                idx = (await cur.fetchone())[0]
            await self._conn.execute(
                'INSERT INTO ystate (slug, idx, "update") VALUES (?, ?, ?)', (slug, idx, update)
            )
            await self._conn.commit()

    async def clear_ystate(self, slug: str):
        async with self._lock:
            await self._conn.execute("DELETE FROM ystate WHERE slug = ?", (slug,))
            await self._conn.commit()

    # ---- sheets (multiple pages per paste) ----
    async def list_sheets(self, slug: str):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT sheet_id, name, position FROM sheets WHERE slug = ? ORDER BY position ASC, created_at ASC",
                (slug,),
            )
            return [
                {"sheetId": r["sheet_id"], "name": r["name"], "position": r["position"]}
                for r in await cur.fetchall()
            ]

    async def get_sheet(self, slug: str, sheet_id: str):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT * FROM sheets WHERE slug = ? AND sheet_id = ?", (slug, sheet_id)
            )
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "sheetId": row["sheet_id"],
            "name": row["name"],
            "content": row["content"],
            "language": row["language"],
            "position": row["position"],
        }

    async def insert_sheet(self, slug: str, sheet_id: str, name: str, content: str,
                           language: str, position: int, created_at):
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO sheets (slug, sheet_id, name, content, language, position, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (slug, sheet_id, name, content, language, position, _iso(created_at)),
            )
            await self._conn.commit()

    async def rename_sheet(self, slug: str, sheet_id: str, name: str):
        async with self._lock:
            await self._conn.execute(
                "UPDATE sheets SET name = ? WHERE slug = ? AND sheet_id = ?", (name, slug, sheet_id)
            )
            await self._conn.commit()

    async def update_sheet_language(self, slug: str, sheet_id: str, language: str):
        async with self._lock:
            await self._conn.execute(
                "UPDATE sheets SET language = ? WHERE slug = ? AND sheet_id = ?",
                (language, slug, sheet_id),
            )
            await self._conn.commit()

    async def update_sheet_content(self, slug: str, sheet_id: str, content: str):
        async with self._lock:
            await self._conn.execute(
                "UPDATE sheets SET content = ? WHERE slug = ? AND sheet_id = ?",
                (content, slug, sheet_id),
            )
            await self._conn.commit()

    async def reorder_sheets(self, slug: str, sheet_ids: list):
        async with self._lock:
            for pos, sid in enumerate(sheet_ids):
                await self._conn.execute(
                    "UPDATE sheets SET position = ? WHERE slug = ? AND sheet_id = ?",
                    (pos, slug, sid),
                )
            await self._conn.commit()

    async def delete_sheet(self, slug: str, sheet_id: str):
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM sheets WHERE slug = ? AND sheet_id = ?", (slug, sheet_id)
            )
            await self._conn.execute(
                "DELETE FROM ystate_sheets WHERE slug = ? AND sheet_id = ?",
                (slug, sheet_id),
            )
            await self._conn.commit()

    async def count_sheets(self, slug: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT COUNT(*) AS n FROM sheets WHERE slug = ?", (slug,)
            )
            return (await cur.fetchone())["n"]

    # ---- CRDT state for sheets (ordered update lists) ----
    async def get_sheet_yupdates(self, slug: str, sheet_id: str):
        async with self._lock:
            cur = await self._conn.execute(
                'SELECT "update" FROM ystate_sheets WHERE slug = ? AND sheet_id = ? ORDER BY idx ASC',
                (slug, sheet_id),
            )
            return [r["update"] for r in await cur.fetchall()]

    async def append_sheet_yupdate(self, slug: str, sheet_id: str, update: bytes):
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 FROM ystate_sheets WHERE slug = ? AND sheet_id = ?",
                (slug, sheet_id),
            )
            idx = (await cur.fetchone())[0]
            if idx >= self.MAX_YUPDATES_STORED:
                await self._conn.execute(
                    "DELETE FROM ystate_sheets WHERE slug = ? AND sheet_id = ? AND idx < ?",
                    (slug, sheet_id, idx // 2),
                )
                cur = await self._conn.execute(
                    "SELECT COALESCE(MAX(idx), -1) + 1 FROM ystate_sheets WHERE slug = ? AND sheet_id = ?",
                    (slug, sheet_id),
                )
                idx = (await cur.fetchone())[0]
            await self._conn.execute(
                'INSERT INTO ystate_sheets (slug, sheet_id, idx, "update") VALUES (?, ?, ?, ?)',
                (slug, sheet_id, idx, update),
            )
            await self._conn.commit()

    async def clear_sheet_ystate(self, slug: str, sheet_id: str):
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM ystate_sheets WHERE slug = ? AND sheet_id = ?", (slug, sheet_id)
            )
            await self._conn.commit()

    async def purge_expired(self):
        """Delete expired pastes and their images (SQLite has no TTL index)."""
        now = now_utc().isoformat()
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT slug FROM pastes WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
            )
            slugs = [row["slug"] for row in await cur.fetchall()]
        for slug in slugs:
            await self.purge_paste_files(slug)
            await self.delete_paste(slug)
        if slugs:
            logger.info(f"Purged {len(slugs)} expired paste(s)")

    async def purge_all(self):
        """Wipe every paste and image (ephemeral/session mode)."""
        async with self._lock:
            cur = await self._conn.execute("SELECT COUNT(*) AS n FROM pastes")
            n = (await cur.fetchone())["n"]
            await self._conn.execute("DELETE FROM pastes")
            await self._conn.execute("DELETE FROM images")
            await self._conn.execute("DELETE FROM sheets")
            await self._conn.execute("DELETE FROM ystate_sheets")
            await self._conn.commit()
        removed = 0
        try:
            for f in self.images_dir.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
                    removed += 1
        except FileNotFoundError:
            pass
        if n or removed:
            logger.info(f"Session cleanup: removed {n} paste(s) and {removed} image file(s)")
        return n


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
