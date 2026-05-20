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
    user_id    INTEGER PRIMARY KEY,
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

# Fixed user_id so we always know which row is the test user.
# Switch DEFAULT_USER_ID to 1 (or a DB lookup) when real auth is added.
DEFAULT_USER_ID = 123

# GW37 squad from FPL team 11405847.
# bench_order: None = starter, 1-4 = bench slot.
_SEED_TEAM = [
    # Starters
    {"player_id":   1, "price": 6.2, "is_cap": 0, "is_vice": 0, "bench": None},  # Raya
    {"player_id":   5, "price": 7.3, "is_cap": 0, "is_vice": 0, "bench": None},  # Gabriel
    {"player_id": 373, "price": 6.0, "is_cap": 0, "is_vice": 0, "bench": None},  # Virgil
    {"player_id": 260, "price": 5.1, "is_cap": 0, "is_vice": 0, "bench": None},  # Guéhi
    {"player_id": 411, "price": 5.3, "is_cap": 0, "is_vice": 0, "bench": None},  # O'Reilly
    {"player_id": 449, "price": 10.4,"is_cap": 1, "is_vice": 0, "bench": None},  # B.Fernandes (C)
    {"player_id": 783, "price": 5.6, "is_cap": 0, "is_vice": 1, "bench": None},  # Groß (V)
    {"player_id": 450, "price": 8.1, "is_cap": 0, "is_vice": 0, "bench": None},  # Cunha
    {"player_id": 458, "price": 4.7, "is_cap": 0, "is_vice": 0, "bench": None},  # Mainoo
    {"player_id": 624, "price": 7.7, "is_cap": 0, "is_vice": 0, "bench": None},  # Bowen
    {"player_id": 430, "price": 14.7,"is_cap": 0, "is_vice": 0, "bench": None},  # Haaland
    # Bench
    {"player_id": 470, "price": 4.0, "is_cap": 0, "is_vice": 0, "bench": 1},    # Dúbravka
    {"player_id":  72, "price": 5.2, "is_cap": 0, "is_vice": 0, "bench": 2},    # Senesi
    {"player_id": 517, "price": 5.6, "is_cap": 0, "is_vice": 0, "bench": 3},    # Anderson
    {"player_id": 100, "price": 4.6, "is_cap": 0, "is_vice": 0, "bench": 4},    # Kroupi.Jr
]


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

        user_exists = conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (DEFAULT_USER_ID,)
        ).fetchone()
        if not user_exists:
            conn.execute(
                "INSERT INTO users (user_id, username, email) VALUES (?, ?, ?)",
                (DEFAULT_USER_ID, "theodor", "theodor.utvik@gmail.com"),
            )

        team_exists = conn.execute(
            "SELECT 1 FROM teams WHERE user_id = ?", (DEFAULT_USER_ID,)
        ).fetchone()
        if not team_exists:
            conn.executemany(
                """INSERT INTO teams
                   (user_id, player_id, purchase_price, selling_price,
                    is_captain, is_vice_captain, bench_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (DEFAULT_USER_ID, p["player_id"], p["price"], p["price"],
                     p["is_cap"], p["is_vice"], p["bench"])
                    for p in _SEED_TEAM
                ],
            )
            conn.execute(
                """INSERT INTO team_meta (user_id, bank_balance, free_transfers, fpl_team_id)
                   VALUES (?, ?, ?, ?)""",
                (DEFAULT_USER_ID, 3.5, 1, 11405847),
            )


def get_default_user_id() -> int:
    return DEFAULT_USER_ID
