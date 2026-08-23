#!/usr/bin/env python3
"""
Stage 1 — FPL-only fetch.

Checks if the current FPL gameweek has finished and has not yet been
fetched. If so, fetches all FPL data and updates pipeline_state.json.
Exits cleanly with no changes if there is nothing to do.

Usage:
    python scripts/check_and_fetch_fpl.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.fpl_client import FPLClient
from src.utils import archive_season, current_season_start_year, season_label

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAW        = ROOT / "data" / "raw"
STATE_FILE = ROOT / "data" / "pipeline_state.json"


def set_gha_output(key: str, value: str) -> None:
    """Write a step output for GitHub Actions (no-op outside CI)."""
    gha_output = os.getenv("GITHUB_OUTPUT")
    if gha_output:
        with open(gha_output, "a") as fh:
            fh.write(f"{key}={value}\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        state.setdefault("season", None)
        return state
    return {"season": None, "fpl_fetched_gw": 0, "fpl_fetched_at": None, "full_pipeline_gw": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_finished_gw(events) -> int | None:
    """Return the most recently finished GW number, or None if none finished yet."""
    finished = events[events["finished"]]
    if finished.empty:
        return None
    return int(finished["id"].max())


def check_season_rollover(state: dict, events) -> tuple[dict, bool]:
    """
    Detect a season change (or first-run migration of an un-seasoned state
    file) and archive the previous season's data before resetting counters.
    Returns (possibly updated state, whether a rollover was performed).

    The caller must commit on a rollover even if no GW has finished yet
    this run — otherwise the archived files and reset state only exist on
    the CI runner's disk and are discarded when it's torn down.
    """
    new_season = current_season_start_year(events)
    if state.get("season") == new_season:
        return state, False

    old_label = season_label(state["season"]) if state.get("season") else "2025-26"
    log.info(
        f"Season change detected: {state.get('season')!r} -> {new_season!r} "
        f"({season_label(new_season)}). Archiving {old_label}..."
    )
    archive_season(ROOT, old_label)

    state = {"season": new_season, "fpl_fetched_gw": 0, "fpl_fetched_at": None, "full_pipeline_gw": 0}
    save_state(state)
    log.info(f"pipeline_state.json reset for season {season_label(new_season)}.")
    return state, True


def main() -> None:
    log.info("=== Stage 1: FPL completeness check ===")

    state  = load_state()
    client = FPLClient(request_delay=0.05)
    events = client.get_events()

    state, rolled_over = check_season_rollover(state, events)
    set_gha_output("rollover", "true" if rolled_over else "false")
    log.info(f"State: season={state['season']}, fpl_fetched_gw={state['fpl_fetched_gw']}, "
             f"full_pipeline_gw={state['full_pipeline_gw']}")

    finished_gw = get_finished_gw(events)

    if finished_gw is None:
        log.info("No finished GW found. Nothing to do.")
        set_gha_output("fetched", "false")
        sys.exit(0)

    if finished_gw <= state["fpl_fetched_gw"]:
        log.info(f"GW{finished_gw} already fetched. Nothing to do.")
        set_gha_output("fetched", "false")
        sys.exit(0)

    log.info(f"New finished GW detected: GW{finished_gw}. Fetching FPL data...")

    players  = client.get_players()
    teams    = client.get_teams()
    fixtures = client.get_fixtures()
    log.info(f"  Fetching GW history for {len(players)} players...")
    gw_df    = client.get_all_gameweeks(players["id"].tolist())

    RAW.mkdir(parents=True, exist_ok=True)
    players.to_parquet(RAW / "fpl_players.parquet",   index=False)
    teams.to_parquet(RAW / "fpl_teams.parquet",       index=False)
    fixtures.to_parquet(RAW / "fpl_fixtures.parquet", index=False)
    gw_df.to_parquet(RAW / "fpl_gameweeks.parquet",   index=False)
    log.info("  FPL data saved to data/raw/")

    state["fpl_fetched_gw"] = finished_gw
    state["fpl_fetched_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    log.info(f"  pipeline_state.json updated: fpl_fetched_gw={finished_gw}")
    set_gha_output("fetched", "true")
    log.info("Stage 1 complete.")


if __name__ == "__main__":
    main()
