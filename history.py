"""Per-account critique history, persisted to a SQLite file on disk.

Meant to live on a Railway Volume (a persistent mount that survives deploys
and restarts — an ordinary local disk write everywhere else, including local
dev). The mount path comes from `DATA_DIR` (defaults to `./data`, created if
missing); Railway's own docs call the conventional mount path `/data`.

One row per finished critique, scoped to the signed-in user's email — no
cross-account access, enforced by every read/delete requiring the caller's
email to match the row's.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "history.db"


@contextmanager
def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create the table (and enable WAL for better concurrent access under
    gunicorn's threaded worker) if this is the first run. Safe to call on
    every server start."""
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source TEXT NOT NULL,
                note TEXT,
                audience TEXT,
                goals TEXT,
                markdown TEXT NOT NULL,
                annotated_image TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses (user_email, id DESC)")


def save_analysis(user_email, source_type, source, note, audience, goals, markdown, annotated_image):
    """Store one finished critique for `user_email`. Returns the new row id."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses
                (user_email, created_at, source_type, source, note, audience, goals, markdown, annotated_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_email,
                datetime.now(timezone.utc).isoformat(),
                source_type,
                source,
                note or None,
                audience or None,
                goals or None,
                markdown,
                annotated_image or None,
            ),
        )
        return cur.lastrowid


def list_analyses(user_email):
    """Return this user's past analyses, newest first, without the full
    markdown/image (kept light for a list view — fetch one row's full
    content with `get_analysis`)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source_type, source
            FROM analyses
            WHERE user_email = ?
            ORDER BY id DESC
            """,
            (user_email,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_analysis(user_email, analysis_id):
    """Return one full record if it belongs to `user_email`, else None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ? AND user_email = ?",
            (analysis_id, user_email),
        ).fetchone()
        return dict(row) if row else None
