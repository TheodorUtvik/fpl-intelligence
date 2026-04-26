#!/usr/bin/env python3
"""
Rebuild merged data, features, model and prediction snapshot from local parquet files.

This script does NOT call external APIs. It is intended for fast local rebuilds after
code changes (feature engineering, leakage guards, optimizer fixes) when raw data is
already present in `data/raw/`.

Usage:
    python3 scripts/rebuild_from_local_data.py
"""

import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.refresh_pipeline import merge_data, engineer_and_train

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"


def _require(path: Path, label: str) -> None:
    if not path.exists():
        log.error(f"Missing required {label}: {path}")
        sys.exit(1)


def main() -> None:
    log.info("=== Local rebuild (no network) ===")

    players_path = RAW / "fpl_players.parquet"
    teams_path = RAW / "fpl_teams.parquet"
    fixtures_path = RAW / "fpl_fixtures.parquet"
    gw_path = RAW / "fpl_gameweeks.parquet"
    us_matches_path = RAW / "understat_matches.parquet"
    id_map_path = PROCESSED / "player_id_map.parquet"

    _require(players_path, "FPL players parquet")
    _require(teams_path, "FPL teams parquet")
    _require(fixtures_path, "FPL fixtures parquet")
    _require(gw_path, "FPL gameweeks parquet")
    _require(us_matches_path, "Understat matches parquet")
    _require(id_map_path, "player_id_map parquet")

    players = pd.read_parquet(players_path)
    teams = pd.read_parquet(teams_path)
    fixtures = pd.read_parquet(fixtures_path)
    gw_df = pd.read_parquet(gw_path)
    us_matches = pd.read_parquet(us_matches_path)
    id_map = pd.read_parquet(id_map_path)

    log.info("Merging local FPL + Understat files...")
    merged = merge_data(players, teams, gw_df, id_map, us_matches)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(PROCESSED / "merged_players.parquet", index=False)
    log.info(f"Merged saved: {PROCESSED / 'merged_players.parquet'}")

    log.info("Rebuilding features/model/predictions from merged data...")
    engineer_and_train(merged, fixtures)
    log.info("Local rebuild complete.")


if __name__ == "__main__":
    main()
