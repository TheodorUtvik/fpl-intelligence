#!/usr/bin/env python3
"""
Stage 2 — Full pipeline (Understat + merge + features + retrain).

Runs only when:
  1. Stage 1 has fetched a GW that Stage 2 hasn't processed yet.
  2. At least 48 hours have elapsed since Stage 1 ran (Understat update lag).

Exits cleanly with no changes if conditions are not met.

Usage:
    python scripts/check_and_run_full_pipeline.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STATE_FILE   = ROOT / "data" / "pipeline_state.json"
UNDERSTAT_DELAY_HOURS = 48


def set_gha_output(key: str, value: str) -> None:
    """Write a step output for GitHub Actions (no-op outside CI)."""
    gha_output = os.getenv("GITHUB_OUTPUT")
    if gha_output:
        with open(gha_output, "a") as fh:
            fh.write(f"{key}={value}\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"fpl_fetched_gw": 0, "fpl_fetched_at": None, "full_pipeline_gw": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main() -> None:
    log.info("=== Stage 2: Full pipeline check ===")

    state = load_state()
    fpl_gw  = state.get("fpl_fetched_gw", 0)
    full_gw = state.get("full_pipeline_gw", 0)
    fetched_at_str = state.get("fpl_fetched_at")

    log.info(f"State: fpl_fetched_gw={fpl_gw}, full_pipeline_gw={full_gw}, "
             f"fpl_fetched_at={fetched_at_str}")

    # Gate 1 — has Stage 1 processed a GW that Stage 2 hasn't?
    if fpl_gw <= full_gw:
        log.info("No new FPL data to process. Nothing to do.")
        set_gha_output("ran", "false")
        sys.exit(0)

    # Gate 2 — has 48 hours elapsed since Stage 1?
    if fetched_at_str is None:
        log.warning("fpl_fetched_at is missing. Cannot check delay. Skipping.")
        set_gha_output("ran", "false")
        sys.exit(0)

    fetched_at = datetime.fromisoformat(fetched_at_str)
    elapsed    = datetime.now(timezone.utc) - fetched_at
    remaining  = timedelta(hours=UNDERSTAT_DELAY_HOURS) - elapsed

    if elapsed < timedelta(hours=UNDERSTAT_DELAY_HOURS):
        log.info(
            f"Only {elapsed.total_seconds()/3600:.1f}h elapsed since FPL fetch. "
            f"Waiting for {UNDERSTAT_DELAY_HOURS}h Understat delay "
            f"({remaining.total_seconds()/3600:.1f}h remaining). Nothing to do."
        )
        set_gha_output("ran", "false")
        sys.exit(0)

    log.info(f"Both gates passed. Running full pipeline for GW{fpl_gw}...")

    # Import pipeline functions inline to keep startup fast on skip paths
    import asyncio
    import pandas as pd
    from src.data.understat_client import UnderstatClient
    from src.features.engineer import FeatureEngineer
    from src.models.predict import FPLPredictor

    PROCESSED   = ROOT / "data" / "processed"
    PREDICTIONS = ROOT / "data" / "predictions"
    RAW         = ROOT / "data" / "raw"
    MODELS      = ROOT / "models"

    # Load existing id_map
    id_map_path = PROCESSED / "player_id_map.parquet"
    if not id_map_path.exists():
        log.error("player_id_map.parquet not found. Run notebook 02 first.")
        sys.exit(1)
    id_map = pd.read_parquet(id_map_path)

    # ── Understat fetch ───────────────────────────────────────────────────────
    log.info("=== Fetching Understat data ===")
    confirmed     = id_map[id_map["match_status"].isin(["auto", "manual", "review"])]
    understat_ids = confirmed["understat_id"].dropna().astype(str).tolist()
    log.info(f"  {len(understat_ids)} mapped players to fetch...")

    async def _fetch():
        async with UnderstatClient(concurrency=10, request_delay=0.1) as client:
            us_players = await client.get_league_players(season="2025")
            us_matches = await client.get_all_player_matches(understat_ids, season_filter="2025")
        return us_players, us_matches

    us_players, us_matches = asyncio.run(_fetch())
    us_players.to_parquet(RAW / "understat_players.parquet", index=False)
    us_matches.to_parquet(RAW / "understat_matches.parquet", index=False)
    log.info(f"  Understat saved: {len(us_matches)} match rows.")

    # ── Merge ─────────────────────────────────────────────────────────────────
    log.info("=== Merging FPL + Understat ===")
    from scripts.refresh_pipeline import merge_data

    players_df = pd.read_parquet(RAW / "fpl_players.parquet")
    teams_df   = pd.read_parquet(RAW / "fpl_teams.parquet")
    gw_df      = pd.read_parquet(RAW / "fpl_gameweeks.parquet")
    fixtures   = pd.read_parquet(RAW / "fpl_fixtures.parquet")

    merged = merge_data(players_df, teams_df, gw_df, id_map, us_matches)
    merged.to_parquet(PROCESSED / "merged_players.parquet", index=False)

    # ── Features + Model ──────────────────────────────────────────────────────
    from scripts.refresh_pipeline import engineer_and_train
    engineer_and_train(merged, fixtures)

    # ── Update state ──────────────────────────────────────────────────────────
    state["full_pipeline_gw"] = fpl_gw
    save_state(state)
    log.info(f"pipeline_state.json updated: full_pipeline_gw={fpl_gw}")
    set_gha_output("ran", "true")
    log.info("Stage 2 complete.")


if __name__ == "__main__":
    main()
