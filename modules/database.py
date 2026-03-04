"""
modules/database.py
===================
All SQLite read/write operations for the Islamic Instagram Bot.
"""

import sqlite3
import logging
from datetime import datetime
from config.settings import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                type                TEXT NOT NULL,
                content_ref         TEXT,
                instagram_post_id   TEXT,
                posted_at           DATETIME,
                status              TEXT DEFAULT 'pending',
                retry_count         INTEGER DEFAULT 0,
                error_message       TEXT
            );

            CREATE TABLE IF NOT EXISTS wird_progress (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                current_page    INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS recitation_progress (
                reciter_id      TEXT PRIMARY KEY,
                last_surah      INTEGER DEFAULT 1,
                last_ayah       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS templates (
                filename        TEXT PRIMARY KEY,
                last_used_at    DATETIME
            );

            CREATE TABLE IF NOT EXISTS adkar_tracker (
                type            TEXT PRIMARY KEY,
                current_index   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS hadith_tracker (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                last_hadith_id  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS token_tracker (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                last_refreshed  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Seed single-row tables on first run
        conn.execute(
            "INSERT OR IGNORE INTO wird_progress (id, current_page) VALUES (1, 1)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO adkar_tracker (type, current_index) VALUES ('sabah', 0)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO adkar_tracker (type, current_index) VALUES ('masae', 0)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO hadith_tracker (id, last_hadith_id) VALUES (1, 0)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO token_tracker (id, last_refreshed) VALUES (1, CURRENT_TIMESTAMP)"
        )
        conn.commit()
    logger.info("Database initialized at %s", DB_PATH)


# ── Wird progress ──────────────────────────────────────────────────────────────

def get_current_wird_page() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT current_page FROM wird_progress WHERE id = 1").fetchone()
        return row["current_page"] if row else 1


def advance_wird_page() -> int:
    """Increment page, wrapping 604 → 1. Returns new page number."""
    current = get_current_wird_page()
    next_page = (current % 604) + 1
    with get_connection() as conn:
        conn.execute(
            "UPDATE wird_progress SET current_page = ? WHERE id = 1", (next_page,)
        )
        conn.commit()
    return next_page


# ── Adkar rotation ─────────────────────────────────────────────────────────────

def get_adkar_index(adkar_type: str) -> int:
    """adkar_type: 'sabah' or 'masae'"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT current_index FROM adkar_tracker WHERE type = ?", (adkar_type,)
        ).fetchone()
        return row["current_index"] if row else 0


def advance_adkar_index(adkar_type: str, total: int) -> int:
    """Increment index mod total. Returns new index."""
    current = get_adkar_index(adkar_type)
    next_idx = (current + 1) % total
    with get_connection() as conn:
        conn.execute(
            "UPDATE adkar_tracker SET current_index = ? WHERE type = ?",
            (next_idx, adkar_type),
        )
        conn.commit()
    return next_idx


# ── Hadith rotation ────────────────────────────────────────────────────────────

def get_last_hadith_id() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT last_hadith_id FROM hadith_tracker WHERE id = 1").fetchone()
        return row["last_hadith_id"] if row else 0


def advance_hadith_id() -> int:
    current = get_last_hadith_id()
    next_id = current + 1
    with get_connection() as conn:
        conn.execute(
            "UPDATE hadith_tracker SET last_hadith_id = ? WHERE id = 1", (next_id,)
        )
        conn.commit()
    return next_id


# ── Recitation progress ────────────────────────────────────────────────────────

def get_recitation_progress(reciter_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_surah, last_ayah FROM recitation_progress WHERE reciter_id = ?",
            (reciter_id,),
        ).fetchone()
        if row:
            return {"last_surah": row["last_surah"], "last_ayah": row["last_ayah"]}
        return {"last_surah": 1, "last_ayah": 0}


def update_recitation_progress(reciter_id: str, surah: int, ayah: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO recitation_progress (reciter_id, last_surah, last_ayah)
               VALUES (?, ?, ?)
               ON CONFLICT(reciter_id) DO UPDATE SET last_surah=excluded.last_surah,
                                                      last_ayah=excluded.last_ayah""",
            (reciter_id, surah, ayah),
        )
        conn.commit()


# ── Template round-robin ───────────────────────────────────────────────────────

def get_next_template(available: list[str]) -> str:
    """Returns the template filename that was least-recently used."""
    if not available:
        raise ValueError("No templates available")
    with get_connection() as conn:
        placeholders = ",".join("?" * len(available))
        row = conn.execute(
            f"""SELECT filename FROM templates
                WHERE filename IN ({placeholders})
                ORDER BY last_used_at ASC NULLS FIRST
                LIMIT 1""",
            available,
        ).fetchone()
        chosen = row["filename"] if row else available[0]
        conn.execute(
            """INSERT INTO templates (filename, last_used_at) VALUES (?, ?)
               ON CONFLICT(filename) DO UPDATE SET last_used_at=excluded.last_used_at""",
            (chosen, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return chosen


# ── Post logging ───────────────────────────────────────────────────────────────

def log_post(
    post_type: str,
    content_ref: str,
    status: str = "pending",
    instagram_post_id: str = None,
    error_message: str = None,
) -> int:
    """Insert a new post record. Returns the new row id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO posts (type, content_ref, instagram_post_id, posted_at, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                post_type,
                content_ref,
                instagram_post_id,
                datetime.utcnow().isoformat(),
                status,
                error_message,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_post_status(
    post_id: int,
    status: str,
    instagram_post_id: str = None,
    error_message: str = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE posts
               SET status=?, instagram_post_id=?, error_message=?,
                   retry_count = retry_count + CASE WHEN ? = 'failed' THEN 1 ELSE 0 END
               WHERE id=?""",
            (status, instagram_post_id, error_message, status, post_id),
        )
        conn.commit()


def get_pending_retry_posts(max_retries: int = 3) -> list[dict]:
    """Return posts that failed and haven't exceeded max retry count."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE status = 'failed' AND retry_count < ?
               ORDER BY posted_at ASC""",
            (max_retries,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Token tracking ─────────────────────────────────────────────────────────────

def get_token_last_refreshed() -> datetime:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_refreshed FROM token_tracker WHERE id = 1"
        ).fetchone()
        if row:
            return datetime.fromisoformat(row["last_refreshed"])
        return datetime.utcnow()


def update_token_refresh_time() -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE token_tracker SET last_refreshed = ? WHERE id = 1",
            (datetime.utcnow().isoformat(),),
        )
        conn.commit()
