"""
ClipKeeper — Database module.
SQLite storage for clipboard history with filesystem image storage,
categories, collections, settings, and export/import.
"""

import base64
import binascii
import json
import os
import sqlite3
import time
from typing import Optional


DATA_DIR = os.path.expanduser("~/.local/share/clipkeeper")
DB_PATH = os.path.join(DATA_DIR, "history.db")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")


class Database:
    """SQLite database for storing clipboard history."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        os.makedirs(IMAGES_DIR, exist_ok=True)
        self.db_path = db_path
        self.images_dir = IMAGES_DIR
        self.backups_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(self.backups_dir, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._migrate()
        self._create_indexes()

    def _create_tables(self):
        """Create tables only — indexes are created after migration."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT NOT NULL,
                category TEXT DEFAULT 'text',
                content_subtype TEXT,
                text_content TEXT,
                image_path TEXT,
                image_width INTEGER,
                image_height INTEGER,
                thumb_path TEXT,
                preview TEXT,
                metadata_json TEXT,
                content_hash TEXT UNIQUE,
                favorite BOOLEAN DEFAULT 0,
                pinned BOOLEAN DEFAULT 0,
                is_snippet BOOLEAN DEFAULT 0,
                is_sensitive BOOLEAN DEFAULT 0,
                use_count INTEGER DEFAULT 1,
                used_at REAL DEFAULT (strftime('%s', 'now')),
                created_at REAL DEFAULT (strftime('%s', 'now')),
                collection_id INTEGER
            );
        """)
        
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                icon TEXT DEFAULT '📁',
                color TEXT DEFAULT '#3584e4',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def _create_indexes(self):
        """Create indexes AFTER migration has added all columns."""
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_clips_used_at ON clips(used_at DESC);
            CREATE INDEX IF NOT EXISTS idx_clips_pinned ON clips(pinned DESC);
            CREATE INDEX IF NOT EXISTS idx_clips_category ON clips(category);
            CREATE INDEX IF NOT EXISTS idx_clips_hash ON clips(content_hash);
            CREATE INDEX IF NOT EXISTS idx_clips_favorite ON clips(favorite DESC);
        """)
        self.conn.commit()

    def _migrate(self):
        """Handle schema migrations from older versions."""
        cursor = self.conn.execute("PRAGMA table_info(clips)")
        columns = {row[1] for row in cursor.fetchall()}

        # 1. First, handle renames if old column names exist
        renames = {
            "last_used_at": "used_at",
            "is_favorite": "favorite",
            "is_pinned": "pinned",
        }
        for old_col, new_col in renames.items():
            if old_col in columns and new_col not in columns:
                try:
                    self.conn.execute(f"ALTER TABLE clips RENAME COLUMN {old_col} TO {new_col}")
                    columns.remove(old_col)
                    columns.add(new_col)
                    print(f"[Database] Migrated column {old_col} -> {new_col}")
                except sqlite3.OperationalError:
                    pass

        # 2. Add missing columns
        migrations = {
            "category": "ALTER TABLE clips ADD COLUMN category TEXT DEFAULT 'text'",
            "content_subtype": "ALTER TABLE clips ADD COLUMN content_subtype TEXT",
            "image_path": "ALTER TABLE clips ADD COLUMN image_path TEXT",
            "image_width": "ALTER TABLE clips ADD COLUMN image_width INTEGER",
            "image_height": "ALTER TABLE clips ADD COLUMN image_height INTEGER",
            "thumb_path": "ALTER TABLE clips ADD COLUMN thumb_path TEXT",
            "metadata_json": "ALTER TABLE clips ADD COLUMN metadata_json TEXT",
            "favorite": "ALTER TABLE clips ADD COLUMN favorite INTEGER DEFAULT 0",
            "pinned": "ALTER TABLE clips ADD COLUMN pinned INTEGER DEFAULT 0",
            "is_sensitive": "ALTER TABLE clips ADD COLUMN is_sensitive INTEGER DEFAULT 0",
            "use_count": "ALTER TABLE clips ADD COLUMN use_count INTEGER DEFAULT 1",
            "is_snippet": "ALTER TABLE clips ADD COLUMN is_snippet INTEGER DEFAULT 0",
            "used_at": "ALTER TABLE clips ADD COLUMN used_at REAL",
            "collection_id": "ALTER TABLE clips ADD COLUMN collection_id INTEGER",
        }

        for col, sql in migrations.items():
            if col not in columns:
                try:
                    self.conn.execute(sql)
                    print(f"[Database] Added column {col}")
                except sqlite3.OperationalError:
                    pass

        # Migrate old image_data to filesystem
        if "image_data" in columns:
            self._migrate_images()

        # Normalize legacy timestamp/text values to REAL unix timestamps.
        self.conn.executescript(
            """
            UPDATE clips
            SET created_at = CAST(strftime('%s', created_at) AS REAL)
            WHERE typeof(created_at) = 'text' AND created_at LIKE '____-__-__%';

            UPDATE clips
            SET used_at = CAST(strftime('%s', used_at) AS REAL)
            WHERE typeof(used_at) = 'text' AND used_at LIKE '____-__-__%';

            UPDATE clips
            SET created_at = CAST(created_at AS REAL)
            WHERE typeof(created_at) = 'text' AND created_at GLOB '[0-9]*';

            UPDATE clips
            SET used_at = CAST(used_at AS REAL)
            WHERE typeof(used_at) = 'text' AND used_at GLOB '[0-9]*';

            UPDATE clips
            SET used_at = created_at
            WHERE used_at IS NULL;
            """
        )

        self.conn.commit()

    def _migrate_images(self):
        """Migrate BLOB images to filesystem."""
        try:
            rows = self.conn.execute(
                "SELECT id, image_data, content_hash FROM clips WHERE image_data IS NOT NULL"
            ).fetchall()
            for row in rows:
                if row["image_data"] and row["content_hash"]:
                    img_path = os.path.join(self.images_dir, f"{row['content_hash']}.png")
                    with open(img_path, "wb") as f:
                        f.write(row["image_data"])
                    self.conn.execute(
                        "UPDATE clips SET image_path = ? WHERE id = ?",
                        (img_path, row["id"]),
                    )
        except Exception as e:
            print(f"[ClipKeeper] Image migration error: {e}")

    # --- Clips CRUD ---

    def add_clip(
        self,
        content_type: str,
        content_hash: str,
        preview: str,
        category: str = "text",
        content_subtype: Optional[str] = None,
        text_content: Optional[str] = None,
        image_path: Optional[str] = None,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None,
        thumb_path: Optional[str] = None,
        metadata: Optional[dict] = None,
        is_sensitive: bool = False,
    ) -> Optional[int]:
        """Add a new clip to the database."""
        try:
            metadata_json = json.dumps(metadata) if metadata else None
            now = time.time()
            
            cursor = self.conn.execute(
                """
                INSERT INTO clips (
                    content_type, category, content_subtype,
                    text_content, image_path, thumb_path,
                    preview, metadata_json, content_hash,
                    image_width, image_height, is_sensitive,
                    used_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_type,
                    category,
                    content_subtype,
                    text_content,
                    image_path,
                    thumb_path,
                    preview,
                    metadata_json,
                    content_hash,
                    image_width,
                    image_height,
                    is_sensitive,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            self._auto_cleanup(self._max_history_limit())
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate content hash -> update used_at
            # We also might want to check if sensitive status changed? 
            # E.g. content was updated? No, hash is same.
            self.conn.execute(
                "UPDATE clips SET used_at = ?, use_count = use_count + 1 WHERE content_hash = ?",
                (time.time(), content_hash),
            )
            self.conn.commit()
            
            # Fetch the ID
            row = self.conn.execute(
                "SELECT id FROM clips WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            return row["id"] if row else None

    def get_clips(
        self,
        search: Optional[str] = None,
        category: Optional[str] = None,
        favorites_only: bool = False,
        snippets_only: bool = False,
        collection_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """Get clips with optional filtering."""
        conditions = []
        params = []

        if search:
            conditions.append("(text_content LIKE ? OR preview LIKE ?)")
            pattern = f"%{search}%"
            params.extend([pattern, pattern])

        if category and category != "all":
            conditions.append("category = ?")
            params.append(category)

        if favorites_only:
            conditions.append("favorite = 1")

        if snippets_only:
            conditions.append("is_snippet = 1")

        if collection_id is not None:
            conditions.append("collection_id = ?")
            params.append(collection_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT id, content_type, category, content_subtype, text_content,
                   image_path, thumb_path, image_width, image_height,
                   preview, metadata_json, pinned, favorite, is_snippet, is_sensitive, collection_id,
                   created_at, used_at, use_count, content_hash
            FROM clips
            {where}
            ORDER BY pinned DESC, used_at DESC
            LIMIT ?
        """
        params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def get_clip_by_id(self, clip_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """SELECT id, content_type, category, content_subtype, text_content,
                      image_path, thumb_path, image_width, image_height,
                      preview, metadata_json, pinned, favorite, is_snippet, is_sensitive, collection_id,
                      created_at, used_at, use_count, content_hash
               FROM clips WHERE id = ?""",
            (clip_id,),
        ).fetchone()

    def delete_clip(self, clip_id: int):
        """Delete a clip and its image files."""
        clip = self.get_clip_by_id(clip_id)
        if clip:
            for path_field in ("image_path", "thumb_path"):
                path = clip[path_field]
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        self.conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self.conn.commit()

    def toggle_pin(self, clip_id: int) -> bool:
        row = self.conn.execute("SELECT pinned FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not row:
            return False
        new_state = 0 if row["pinned"] else 1
        self.conn.execute("UPDATE clips SET pinned = ? WHERE id = ?", (new_state, clip_id))
        self.conn.commit()
        return bool(new_state)

    def toggle_snippet(self, clip_id: int) -> bool:
        row = self.conn.execute("SELECT is_snippet FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not row:
            return False
        new_state = 0 if row["is_snippet"] else 1
        self.conn.execute("UPDATE clips SET is_snippet = ? WHERE id = ?", (new_state, clip_id))
        self.conn.commit()
        return bool(new_state)

    def toggle_favorite(self, clip_id: int) -> bool:
        row = self.conn.execute("SELECT favorite FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not row:
            return False
        new_state = 0 if row["favorite"] else 1
        self.conn.execute("UPDATE clips SET favorite = ? WHERE id = ?", (new_state, clip_id))
        self.conn.commit()
        return bool(new_state)

    def set_collection(self, clip_id: int, collection_id: Optional[int]):
        self.conn.execute(
            "UPDATE clips SET collection_id = ? WHERE id = ?", (collection_id, clip_id)
        )
        self.conn.commit()

    def update_used_at(self, clip_id: int):
        self.conn.execute(
            "UPDATE clips SET used_at = ?, use_count = use_count + 1 WHERE id = ?",
            (time.time(), clip_id),
        )
        self.conn.commit()

    def update_metadata(self, clip_id: int, metadata: dict):
        """Update metadata for a clip (e.g., page title for URLs)."""
        existing = self.get_clip_by_id(clip_id)
        if existing:
            old_meta = json.loads(existing["metadata_json"]) if existing["metadata_json"] else {}
            old_meta.update(metadata)
            self.conn.execute(
                "UPDATE clips SET metadata_json = ? WHERE id = ?",
                (json.dumps(old_meta), clip_id),
            )
            self.conn.commit()

    def update_clip_text(self, clip_id: int, new_text: str):
        """Update the text content of a clip."""
        # We also need to update the hash and preview
        from .utils import compute_hash, truncate_text
        new_hash = compute_hash(new_text)
        new_preview = truncate_text(new_text, 120)
        
        try:
            self.conn.execute(
                """UPDATE clips 
                   SET text_content = ?, content_hash = ?, preview = ? 
                   WHERE id = ?""",
                (new_text, new_hash, new_preview, clip_id),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Hash collision (content already exists elsewhere)?
            # In this case, we might want to just delete this clip and point to the other one?
            # For simplicity, let's just fail or ignore hash constraint if we could
            # But we have UNIQUE(content_hash).
            # If we edit to something that exists, we should probably merge. 
            # But that's complex. Let's just return False for now.
            return False

    def clear_unpinned(self):
        """Delete all unpinned, non-favorite clips and their images."""
        clips = self.conn.execute(
            "SELECT image_path, thumb_path FROM clips WHERE pinned = 0 AND favorite = 0"
        ).fetchall()
        for clip in clips:
            for path_field in ("image_path", "thumb_path"):
                path = clip[path_field]
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        self.conn.execute("DELETE FROM clips WHERE pinned = 0 AND favorite = 0")
        self.conn.commit()

    # --- Collections ---

    def create_collection(self, name: str, icon: str = "📁", color: str = "#3584e4") -> int:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO collections (name, icon, color, created_at) VALUES (?, ?, ?, ?)",
            (name, icon, color, time.time()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_collections(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM collections ORDER BY name"
        ).fetchall()

    def delete_collection(self, collection_id: int):
        self.conn.execute(
            "UPDATE clips SET collection_id = NULL WHERE collection_id = ?", (collection_id,)
        )
        self.conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        self.conn.commit()

    # --- Settings ---

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def get_all_settings(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    # --- Stats ---

    def get_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) as c FROM clips").fetchone()["c"]
        pinned = self.conn.execute("SELECT COUNT(*) as c FROM clips WHERE pinned = 1").fetchone()["c"]
        favorites = self.conn.execute("SELECT COUNT(*) as c FROM clips WHERE favorite = 1").fetchone()["c"]
        images = self.conn.execute("SELECT COUNT(*) as c FROM clips WHERE content_type = 'image'").fetchone()["c"]
        categories = self.conn.execute(
            "SELECT category, COUNT(*) as c FROM clips GROUP BY category"
        ).fetchall()
        return {
            "total": total, "pinned": pinned, "favorites": favorites,
            "images": images,
            "categories": {row["category"]: row["c"] for row in categories},
        }

    # --- Export / Import ---

    def export_to_json(self, filepath: str):
        """Export clips/settings/collections to JSON with embedded image bytes."""
        collections = [dict(row) for row in self.get_collections()]
        collection_names = {row["id"]: row["name"] for row in collections}
        clips = self.conn.execute(
            """SELECT id, content_type, category, content_subtype, text_content,
                      image_path, thumb_path, image_width, image_height, preview, metadata_json,
                      pinned, favorite, is_snippet, is_sensitive, created_at, used_at, use_count,
                      content_hash, collection_id
               FROM clips ORDER BY created_at"""
        ).fetchall()

        serialized_clips = []
        for row in clips:
            clip = dict(row)
            clip["collection_name"] = collection_names.get(clip.get("collection_id"))

            image_path = clip.get("image_path")
            thumb_path = clip.get("thumb_path")
            clip["image_data_b64"] = self._read_file_b64(image_path)
            clip["thumb_data_b64"] = self._read_file_b64(thumb_path)
            serialized_clips.append(clip)

        data = {
            "version": 2,
            "exported_at": time.time(),
            "clips": serialized_clips,
            "collections": collections,
            "settings": self.get_all_settings(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_from_json(self, filepath: str) -> int:
        """Import clips from JSON. Returns number of imported clips."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        settings_data = data.get("settings")
        if isinstance(settings_data, dict):
            for key, value in settings_data.items():
                self.set_setting(str(key), str(value))

        collection_name_to_id: dict[str, int] = {}
        for collection in data.get("collections", []):
            name = str(collection.get("name", "")).strip()
            if not name:
                continue
            icon = str(collection.get("icon", "📁"))
            color = str(collection.get("color", "#3584e4"))
            created_at = self._to_float(collection.get("created_at"), time.time())

            self.conn.execute(
                "INSERT OR IGNORE INTO collections (name, icon, color, created_at) VALUES (?, ?, ?, ?)",
                (name, icon, color, created_at),
            )
            self.conn.execute(
                "UPDATE collections SET icon = ?, color = ?, created_at = ? WHERE name = ?",
                (icon, color, created_at, name),
            )
            row = self.conn.execute(
                "SELECT id FROM collections WHERE name = ?",
                (name,),
            ).fetchone()
            if row:
                collection_name_to_id[name] = row["id"]

        self.conn.commit()

        count = 0
        for clip in data.get("clips", []):
            image_bytes = self._decode_b64(clip.get("image_data_b64"))
            if image_bytes is None:
                src_image = clip.get("image_path")
                if src_image and os.path.exists(src_image):
                    try:
                        with open(src_image, "rb") as f:
                            image_bytes = f.read()
                    except OSError:
                        image_bytes = None

            text_content = clip.get("text_content")
            content_hash = clip.get("content_hash")
            if not content_hash:
                if text_content:
                    from .utils import compute_hash
                    content_hash = compute_hash(text_content)
                elif image_bytes:
                    from .utils import compute_hash
                    content_hash = compute_hash(image_bytes)
                else:
                    continue

            existing = self.conn.execute(
                "SELECT id FROM clips WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing:
                continue

            metadata = {}
            raw_metadata = clip.get("metadata_json")
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
            elif isinstance(raw_metadata, str) and raw_metadata:
                try:
                    metadata = json.loads(raw_metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}

            image_path = None
            thumb_path = None
            if image_bytes:
                from .utils import save_image_to_file
                image_path, thumb_path = save_image_to_file(
                    image_bytes,
                    content_hash,
                )
                thumb_bytes = self._decode_b64(clip.get("thumb_data_b64"))
                if thumb_bytes and thumb_path:
                    try:
                        with open(thumb_path, "wb") as f:
                            f.write(thumb_bytes)
                    except OSError:
                        pass

            clip_id = self.add_clip(
                content_type=clip.get("content_type", "text"),
                content_hash=content_hash,
                preview=clip.get("preview") or "",
                category=clip.get("category", "text"),
                content_subtype=clip.get("content_subtype"),
                text_content=text_content,
                image_path=image_path,
                image_width=clip.get("image_width"),
                image_height=clip.get("image_height"),
                thumb_path=thumb_path,
                metadata=metadata or None,
                is_sensitive=self._to_bool(clip.get("is_sensitive", 0)),
            )
            if clip_id is None:
                continue

            collection_id = None
            collection_name = clip.get("collection_name")
            if collection_name in collection_name_to_id:
                collection_id = collection_name_to_id[collection_name]
            elif clip.get("collection_id") is not None:
                candidate_id = self._to_int(clip.get("collection_id"))
                if candidate_id is not None:
                    row = self.conn.execute(
                        "SELECT id FROM collections WHERE id = ?",
                        (candidate_id,),
                    ).fetchone()
                    collection_id = row["id"] if row else None

            created_at = self._to_float(clip.get("created_at"), time.time())
            used_at = self._to_float(clip.get("used_at"), created_at)
            use_count = max(1, self._to_int(clip.get("use_count"), 1))
            pinned = 1 if self._to_bool(clip.get("pinned", 0)) else 0
            favorite = 1 if self._to_bool(clip.get("favorite", 0)) else 0
            is_snippet = 1 if self._to_bool(clip.get("is_snippet", 0)) else 0
            is_sensitive = 1 if self._to_bool(clip.get("is_sensitive", 0)) else 0

            self.conn.execute(
                """
                UPDATE clips
                SET pinned = ?, favorite = ?, is_snippet = ?, is_sensitive = ?,
                    use_count = ?, created_at = ?, used_at = ?, collection_id = ?
                WHERE id = ?
                """,
                (
                    pinned,
                    favorite,
                    is_snippet,
                    is_sensitive,
                    use_count,
                    created_at,
                    used_at,
                    collection_id,
                    clip_id,
                ),
            )
            count += 1

        self.conn.commit()
        self._auto_cleanup(self._max_history_limit())
        return count

    def create_backup(self, backup_dir: Optional[str] = None, keep_files: int = 30) -> str:
        """Create a timestamped JSON backup and prune old backup files."""
        target_dir = os.path.expanduser(backup_dir or self.backups_dir)
        os.makedirs(target_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        millis = int((time.time() % 1) * 1000)
        backup_path = os.path.join(
            target_dir, f"clipkeeper_backup_{timestamp}_{millis:03d}.json"
        )
        if os.path.exists(backup_path):
            backup_path = os.path.join(
                target_dir, f"clipkeeper_backup_{timestamp}_{millis:03d}_{os.getpid()}.json"
            )
        self.export_to_json(backup_path)
        self._cleanup_backups(target_dir, keep_files)
        return backup_path

    # --- Cleanup ---

    def _auto_cleanup(self, max_items: int = 500):
        count = self.conn.execute(
            "SELECT COUNT(*) as c FROM clips WHERE pinned = 0 AND favorite = 0"
        ).fetchone()["c"]
        if count > max_items:
            clips_to_delete = self.conn.execute(
                """SELECT id, image_path, thumb_path FROM clips
                   WHERE pinned = 0 AND favorite = 0
                   ORDER BY used_at ASC LIMIT ?""",
                (count - max_items,),
            ).fetchall()
            for clip in clips_to_delete:
                for path_field in ("image_path", "thumb_path"):
                    path = clip[path_field]
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
            self.conn.execute(
                """DELETE FROM clips WHERE id IN (
                       SELECT id FROM clips WHERE pinned = 0 AND favorite = 0
                       ORDER BY used_at ASC LIMIT ?)""",
                (count - max_items,),
            )
            self.conn.commit()

    def _cleanup_backups(self, backup_dir: str, keep_files: int):
        try:
            keep = max(1, int(keep_files))
        except (TypeError, ValueError):
            keep = 30

        entries = []
        try:
            for name in os.listdir(backup_dir):
                if not name.startswith("clipkeeper_backup_") or not name.endswith(".json"):
                    continue
                path = os.path.join(backup_dir, name)
                if os.path.isfile(path):
                    entries.append((os.path.getmtime(path), path))
        except OSError:
            return

        entries.sort(reverse=True)
        for _, path in entries[keep:]:
            try:
                os.remove(path)
            except OSError:
                pass

    def close(self):
        self.conn.close()

    def _max_history_limit(self) -> int:
        try:
            value = int(self.get_setting("max_history", "500"))
        except (TypeError, ValueError):
            value = 500
        return max(1, value)

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @staticmethod
    def _to_int(value, default: Optional[int] = None) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _read_file_b64(path: Optional[str]) -> Optional[str]:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return None

    @staticmethod
    def _decode_b64(value: Optional[str]) -> Optional[bytes]:
        if not value:
            return None
        try:
            return base64.b64decode(value)
        except (binascii.Error, ValueError, TypeError):
            return None
