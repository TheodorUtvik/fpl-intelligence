"""
app/team_manager.py

Business logic for My Team: fetch from FPL API, persist to SQLite,
generate replacement suggestions.
"""
from __future__ import annotations

import pandas as pd
import requests

from app.db import get_conn, get_default_user_id

_FPL_PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
_MAX_PER_TEAM  = 3


def fetch_squad_from_fpl(team_id: int, gw: int) -> dict:
    """Fetch squad from the public FPL picks endpoint — no auth required."""
    url  = _FPL_PICKS_URL.format(team_id=team_id, gw=gw)
    resp = requests.get(url, timeout=10, headers={"User-Agent": "fpl-intelligence/1.0"})
    if resp.status_code == 503:
        raise RuntimeError("FPL servers are currently being updated. Try again in a few minutes.")
    if resp.status_code == 404:
        raise RuntimeError(f"Team ID {team_id} not found. Check your team ID and try again.")
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError("FPL API returned an unexpected response. Try again later.")
    if isinstance(data, str):
        raise RuntimeError(f"FPL API: {data}")
    if "picks" not in data or "entry_history" not in data:
        detail = data.get("detail", "Unexpected API response")
        raise RuntimeError(f"FPL API: {detail}")
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
            "SELECT bank_balance, free_transfers, fpl_team_id, original_squad_json FROM team_meta WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        rows = conn.execute(
            """SELECT id, player_id, purchase_price, selling_price,
                      is_captain, is_vice_captain, bench_order
               FROM teams WHERE user_id = ?
               ORDER BY bench_order IS NOT NULL, bench_order, id""",
            (user_id,),
        ).fetchall()
    if not rows:
        return None
    return {
        "players":        [dict(r) for r in rows],
        "bank":           float(meta["bank_balance"])   if meta else 0.0,
        "free_transfers": int(meta["free_transfers"])   if meta else 1,
        "fpl_team_id":    meta["fpl_team_id"]           if meta else None,
        "has_original":   bool(meta and meta["original_squad_json"]),
    }


def save_team(
    picks: list[dict],
    bank: float,
    free_transfers: int,
    fpl_team_id: int | None = None,
    user_id: int | None = None,
    is_original: bool = False,
) -> None:
    """Replace the user's current team in DB with new picks.
    When is_original=True, also snapshot the squad as the baseline for revert.
    """
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
        if is_original:
            import json
            conn.execute(
                """UPDATE team_meta
                   SET original_squad_json = ?, original_bank = ?, original_ft = ?
                   WHERE user_id = ?""",
                (json.dumps(picks), float(bank), int(free_transfers), user_id),
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
    free_transfers: int = 1,
) -> list[dict]:
    """
    Return ranked replacements for one squad slot.
    Filters: same position, 3-per-team cap, available status.
    No budget cap — callers can see any player regardless of cost.
    When free_transfers < 1 the -4pt hit is factored into pts_delta and sort order.
    """
    from collections import Counter

    from app.data_loader import get_players_with_predictions

    all_players = get_players_with_predictions()

    # Use full player pool so injured squad members don't evade team-count tracking
    current_row = all_players[all_players["player_id"] == player_id]
    if current_row.empty:
        return []
    current = current_row.iloc[0]

    pos          = current["position"]
    current_cost = float(current["now_cost"])

    squad_team_map = all_players.set_index("player_id")["team"].to_dict()
    remaining      = [pid for pid in squad_player_ids if pid != player_id]
    team_counts    = Counter(
        squad_team_map[pid] for pid in remaining if pid in squad_team_map
    )

    candidates = players_df[
        (players_df["position"] == pos)
        & (~players_df["player_id"].isin(squad_player_ids))
        & (players_df["status"] == "a")
    ].copy()

    candidates = candidates[
        candidates["team"].map(lambda t: team_counts.get(t, 0)) < _MAX_PER_TEAM
    ].copy()

    hit = free_transfers < 1
    candidates["cost_delta"] = candidates["now_cost"] - current_cost
    candidates["pts_delta"]  = (
        candidates["predicted_pts"] - float(current["predicted_pts"]) - (4.0 if hit else 0.0)
    )

    keep = [
        "player_id", "web_name", "team_name", "now_cost",
        "predicted_pts", "cost_delta", "pts_delta", "status", "fdr_next",
    ]
    return (
        candidates.sort_values("pts_delta", ascending=False)
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
    Returns updated {bank, free_transfers, undo} where undo holds everything
    needed to reverse the transfer.
    """
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT bank_balance, free_transfers FROM team_meta WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        out_row = conn.execute(
            """SELECT purchase_price, selling_price, is_captain, is_vice_captain, bench_order
               FROM teams WHERE user_id = ? AND player_id = ?""",
            (user_id, out_player_id),
        ).fetchone()
        if not meta or not out_row:
            raise ValueError("Team not found in DB")

        old_bank      = float(meta["bank_balance"])
        old_ft        = int(meta["free_transfers"])
        selling_price = float(out_row["selling_price"])

        new_bank = round(old_bank + selling_price - in_player_cost, 1)
        new_ft   = max(0, old_ft - 1)

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
    return {
        "bank":           new_bank,
        "free_transfers": new_ft,
        "undo": {
            "out_player_id":      out_player_id,
            "in_player_id":       in_player_id,
            "out_purchase_price": float(out_row["purchase_price"]),
            "out_selling_price":  selling_price,
            "is_captain":         out_row["is_captain"],
            "is_vice_captain":    out_row["is_vice_captain"],
            "bench_order":        out_row["bench_order"],
            "old_bank":           old_bank,
            "old_ft":             old_ft,
        },
    }


def swap_positions(bench_pid: int, xi_pid: int, user_id: int | None = None) -> None:
    """Swap a bench player into the XI and a starter to that bench slot. No FT cost."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        bench_row = conn.execute(
            "SELECT bench_order FROM teams WHERE user_id=? AND player_id=?",
            (user_id, bench_pid),
        ).fetchone()
        if not bench_row or bench_row["bench_order"] is None:
            raise ValueError(f"Player {bench_pid} is not on the bench")
        bench_slot = bench_row["bench_order"]
        conn.execute(
            "UPDATE teams SET bench_order=NULL WHERE user_id=? AND player_id=?",
            (user_id, bench_pid),
        )
        conn.execute(
            "UPDATE teams SET bench_order=? WHERE user_id=? AND player_id=?",
            (bench_slot, user_id, xi_pid),
        )


def reassign_captaincy(user_id: int | None = None) -> None:
    """If the captain or VC is on the bench, auto-assign to highest-predicted XI players."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        xi_rows = conn.execute(
            "SELECT player_id, is_captain, is_vice_captain FROM teams WHERE user_id=? AND bench_order IS NULL",
            (user_id,),
        ).fetchall()

        has_cap = any(r["is_captain"]      for r in xi_rows)
        has_vc  = any(r["is_vice_captain"] for r in xi_rows)
        if has_cap and has_vc:
            return

        from app.data_loader import get_players_with_predictions
        all_players = get_players_with_predictions()
        xi_pids = [r["player_id"] for r in xi_rows]
        xi_pred = (
            all_players[all_players["player_id"].isin(xi_pids)]
            .sort_values("predicted_pts", ascending=False)
        )
        if xi_pred.empty:
            return

        new_cap_pid = int(xi_pred.iloc[0]["player_id"])
        new_vc_pid  = int(xi_pred.iloc[1]["player_id"]) if len(xi_pred) > 1 else None

        conn.execute(
            "UPDATE teams SET is_captain=0, is_vice_captain=0 WHERE user_id=?", (user_id,)
        )
        conn.execute(
            "UPDATE teams SET is_captain=1 WHERE user_id=? AND player_id=?",
            (user_id, new_cap_pid),
        )
        if new_vc_pid:
            conn.execute(
                "UPDATE teams SET is_vice_captain=1 WHERE user_id=? AND player_id=?",
                (user_id, new_vc_pid),
            )


def restore_original_squad(user_id: int | None = None) -> None:
    """Restore the squad to the snapshot saved at import time."""
    import json
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        meta = conn.execute(
            "SELECT original_squad_json, original_bank, original_ft, fpl_team_id FROM team_meta WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not meta or not meta["original_squad_json"]:
            raise ValueError("No original squad snapshot found")
        picks       = json.loads(meta["original_squad_json"])
        orig_bank   = float(meta["original_bank"])
        orig_ft     = int(meta["original_ft"])
        fpl_team_id = meta["fpl_team_id"]
    # is_original=False so the snapshot columns are left intact for future reverts
    save_team(picks=picks, bank=orig_bank, free_transfers=orig_ft,
              fpl_team_id=fpl_team_id, user_id=user_id, is_original=False)


def undo_transfer(undo_info: dict, user_id: int | None = None) -> None:
    """Reverse the last applied transfer using saved undo snapshot."""
    if user_id is None:
        user_id = get_default_user_id()
    with get_conn() as conn:
        conn.execute(
            """UPDATE teams
               SET player_id=?, purchase_price=?, selling_price=?,
                   is_captain=?, is_vice_captain=?, bench_order=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE user_id=? AND player_id=?""",
            (
                undo_info["out_player_id"],
                undo_info["out_purchase_price"],
                undo_info["out_selling_price"],
                undo_info["is_captain"],
                undo_info["is_vice_captain"],
                undo_info.get("bench_order"),
                user_id,
                undo_info["in_player_id"],
            ),
        )
        conn.execute(
            """UPDATE team_meta
               SET bank_balance=?, free_transfers=?, updated_at=CURRENT_TIMESTAMP
               WHERE user_id=?""",
            (undo_info["old_bank"], undo_info["old_ft"], user_id),
        )
