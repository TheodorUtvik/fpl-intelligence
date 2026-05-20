"""
app/team_manager.py

Business logic for My Team: fetch from FPL API, persist to SQLite,
generate replacement suggestions.
"""
from __future__ import annotations

import requests
import pandas as pd

from app.db import get_conn, get_default_user_id

_FPL_PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
_MAX_PER_TEAM  = 3


def fetch_squad_from_fpl(team_id: int, gw: int) -> dict:
    """Fetch squad from the public FPL picks endpoint — no auth required."""
    url  = _FPL_PICKS_URL.format(team_id=team_id, gw=gw)
    resp = requests.get(url, timeout=10, headers={"User-Agent": "fpl-intelligence/1.0"})
    resp.raise_for_status()
    data = resp.json()
    hist = data["entry_history"]
    return {
        "picks":       data["picks"],
        "bank":        hist["bank"] / 10,
        "active_chip": data.get("active_chip"),
    }


def load_team(user_id: int | None = None) -> dict | None:
    """Return saved team from DB, or None if no team exists for this user."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT bank_balance, free_transfers, fpl_team_id FROM team_meta WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        rows = conn.execute(
            """SELECT player_id, purchase_price, selling_price,
                      is_captain, is_vice_captain, bench_order
               FROM teams WHERE user_id = ?
               ORDER BY bench_order IS NOT NULL, bench_order, player_id""",
            (user_id,),
        ).fetchall()
    if not rows:
        return None
    return {
        "players":        [dict(r) for r in rows],
        "bank":           float(meta["bank_balance"])   if meta else 0.0,
        "free_transfers": int(meta["free_transfers"])   if meta else 1,
        "fpl_team_id":    meta["fpl_team_id"]           if meta else None,
    }


def save_team(
    picks: list[dict],
    bank: float,
    free_transfers: int,
    fpl_team_id: int | None = None,
    user_id: int | None = None,
) -> None:
    """Replace the user's current team in DB with new picks."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        conn.execute("DELETE FROM teams WHERE user_id = ?", (user_id,))
        conn.executemany(
            """INSERT INTO teams
               (user_id, player_id, purchase_price, selling_price,
                is_captain, is_vice_captain, bench_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    user_id,
                    p["player_id"],
                    float(p["purchase_price"]),
                    float(p["selling_price"]),
                    int(p.get("is_captain", 0)),
                    int(p.get("is_vice_captain", 0)),
                    p.get("bench_order"),
                )
                for p in picks
            ],
        )
        conn.execute(
            """INSERT INTO team_meta (user_id, bank_balance, free_transfers, fpl_team_id, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
                   bank_balance   = excluded.bank_balance,
                   free_transfers = excluded.free_transfers,
                   fpl_team_id    = excluded.fpl_team_id,
                   updated_at     = excluded.updated_at""",
            (user_id, float(bank), int(free_transfers), fpl_team_id),
        )


def delete_team(user_id: int | None = None) -> None:
    """Remove a user's team from DB (triggers re-import flow in UI)."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        conn.execute("DELETE FROM teams    WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM team_meta WHERE user_id = ?", (user_id,))


def get_replacement_suggestions(
    player_id: int,
    squad_player_ids: list[int],
    bank: float,
    players_df: pd.DataFrame,
) -> list[dict]:
    """
    Return ranked replacements for one squad slot.
    Filters: same position, budget, 3-per-team cap, available status.
    """
    current_row = players_df[players_df["player_id"] == player_id]
    if current_row.empty:
        return []
    current = current_row.iloc[0]

    pos          = current["position"]
    current_cost = float(current["now_cost"])
    budget_cap   = current_cost + bank

    others      = players_df[players_df["player_id"].isin(
        [pid for pid in squad_player_ids if pid != player_id]
    )]
    team_counts = others["team"].value_counts().to_dict()

    candidates = players_df[
        (players_df["position"] == pos)
        & (~players_df["player_id"].isin(squad_player_ids))
        & (players_df["now_cost"] <= budget_cap)
        & (players_df["status"] == "a")
    ].copy()

    candidates = candidates[
        candidates["team"].map(lambda t: team_counts.get(t, 0)) < _MAX_PER_TEAM
    ].copy()

    candidates["cost_delta"] = candidates["now_cost"] - current_cost
    candidates["pts_delta"]  = candidates["predicted_pts"] - float(current["predicted_pts"])

    keep = [
        "player_id", "web_name", "team_name", "now_cost",
        "predicted_pts", "cost_delta", "pts_delta", "status", "fdr_next",
    ]
    return (
        candidates.sort_values("predicted_pts", ascending=False)
        .head(15)[keep]
        .to_dict(orient="records")
    )


def apply_transfer(
    out_player_id:  int,
    in_player_id:   int,
    in_player_cost: float,
    user_id: int | None = None,
) -> dict:
    """
    Apply a transfer in DB: swap players, adjust bank, decrement free transfers.
    Returns updated {bank, free_transfers}.
    """
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT bank_balance, free_transfers FROM team_meta WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        out_row = conn.execute(
            "SELECT selling_price FROM teams WHERE user_id = ? AND player_id = ?",
            (user_id, out_player_id),
        ).fetchone()
        if not meta or not out_row:
            raise ValueError("Team not found in DB")

        selling_price = float(out_row["selling_price"])
        new_bank = round(float(meta["bank_balance"]) + selling_price - in_player_cost, 1)
        new_ft   = max(0, int(meta["free_transfers"]) - 1)

        conn.execute(
            """UPDATE teams
               SET player_id=?, purchase_price=?, selling_price=?, updated_at=CURRENT_TIMESTAMP
               WHERE user_id=? AND player_id=?""",
            (in_player_id, in_player_cost, in_player_cost, user_id, out_player_id),
        )
        conn.execute(
            """UPDATE team_meta
               SET bank_balance=?, free_transfers=?, updated_at=CURRENT_TIMESTAMP
               WHERE user_id=?""",
            (new_bank, new_ft, user_id),
        )
    return {"bank": new_bank, "free_transfers": new_ft}
