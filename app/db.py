"""
app/db.py

SQLite persistence for user team management.
Single-user now; schema multi-user-ready.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fpl.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    UNIQUE NOT NULL,
    email      TEXT    UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    player_id       INTEGER NOT NULL,
    purchase_price  REAL    NOT NULL,
    selling_price   REAL    NOT NULL,
    is_captain      INTEGER DEFAULT 0,
    is_vice_captain INTEGER DEFAULT 0,
    bench_order     INTEGER,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_meta (
    user_id        INTEGER PRIMARY KEY REFERENCES users(user_id),
    bank_balance   REAL    DEFAULT 0.0,
    free_transfers INTEGER DEFAULT 1,
    fpl_team_id    INTEGER,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_DEFAULT_USER = ("theodor", "theodor.utvik@gmail.com")


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (_DEFAULT_USER[0],)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (username, email) VALUES (?, ?)", _DEFAULT_USER
            )


def get_default_user_id() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM users WHERE username = ?", (_DEFAULT_USER[0],)
        ).fetchone()
        return int(row["user_id"]) if row else 1
