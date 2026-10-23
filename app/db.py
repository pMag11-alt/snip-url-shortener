"""SQLite persistence layer.

Each request gets its own short-lived connection, which keeps the code simple
and is plenty fast for SQLite. The schema is created on startup if missing.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    target_url  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS clicks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id     INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    clicked_at  TEXT    NOT NULL,
    referrer    TEXT    NOT NULL,
    browser     TEXT    NOT NULL,
    device      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clicks_link_time ON clicks (link_id, clicked_at);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def connect(db_path: str) -> sqlite3.Connection:
    # FastAPI may run a dependency and its endpoint on different worker
    # threads, so the same-thread check is disabled. A connection is still
    # only ever used by one request at a time.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
