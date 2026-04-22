#!/usr/bin/env python3
"""
FPL Intelligence — Data Refresh Pipeline

Fetches the latest FPL + Understat data, re-merges, re-engineers features,
and retrains the model so the app always shows next-GW predictions.

Usage
-----
    python scripts/refresh_pipeline.py

Steps
-----
    1. Fetch latest FPL player / gameweek / fixture / team data
    2. Fetch latest Understat match data (re-uses existing player_id_map)
    3. Merge FPL + Understat on player × date
    4. Feature engineering  →  data/processed/features.parquet
    5. Retrain XGBoost model → models/

The player_id_map.parquet (built once in notebook 02 with manual overrides)
is never overwritten by this script. Re-run notebook 02 only if new players
need to be added to the id map.
"""

import asyncio
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.fpl_client import FPLClient
from src.data.understat_client import UnderstatClient
from src.features.engineer import FeatureEngineer
from src.models.predict import FPLPredictor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAW       = ROOT / "data" / "raw"
PROCESSED    = ROOT / "data" / "processed"
PREDICTIONS  = ROOT / "data" / "predictions"
MODELS       = ROOT / "models"


# ── Step 1: FPL ──────────────────────────────────────────────────────────────

def fetch_fpl() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch players, teams, fixtures and full GW history from the FPL API."""
    log.info("=== Step 1: Fetching FPL data ===")
    client = FPLClient(request_delay=0.05)

    players  = client.get_players()
    teams    = client.get_teams()
    fixtures = client.get_fixtures()

    player_ids = players["id"].tolist()
    log.info(f"  Fetching GW history for {len(player_ids)} players...")
    gw_df = client.get_all_gameweeks(player_ids)

    latest_gw = int(gw_df["round"].max()) if not gw_df.empty else "?"
    log.info(f"  Done — {len(players)} players, {len(gw_df)} GW rows, latest GW: {latest_gw}")
    return players, teams, fixtures, gw_df


# ── Step 2: Understat ────────────────────────────────────────────────────────

async def _fetch_understat_async(
    understat_ids: list,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    async with UnderstatClient(concurrency=10, request_delay=0.1) as client:
        season_players = await client.get_league_players(season="2025")
        matches = await client.get_all_player_matches(
            understat_ids, season_filter="2025"
        )
    return season_players, matches


def fetch_understat(id_map: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Re-fetch Understat match data for all confirmed players in id_map."""
    log.info("=== Step 2: Fetching Understat data ===")
    confirmed = id_map[id_map["match_status"].isin(["auto", "manual", "review"])]
    understat_ids = confirmed["understat_id"].dropna().astype(str).tolist()
    log.info(f"  {len(understat_ids)} mapped players to fetch...")

    season_players, matches = asyncio.run(_fetch_understat_async(understat_ids))
    log.info(f"  Season players: {len(season_players)}, Match rows: {len(matches)}")
    return season_players, matches


# ── Step 3: Merge ────────────────────────────────────────────────────────────

def merge_data(
    players_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    gw_df: pd.DataFrame,
    id_map: pd.DataFrame,
    us_matches: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge FPL gameweek rows with Understat match stats.

    Strategy
    --------
    - Map player_id → understat_id via id_map.
    - Aggregate Understat stats per (understat_id, match_date).
    - Left-join onto FPL rows by (understat_id, kickoff_date).
    - Attach current player metadata (web_name, position, team, now_cost).
    """
    log.info("=== Step 3: Merging FPL + Understat ===")

    # Player metadata snapshot (one row per player, current values)
    players_meta = players_df[["id", "web_name", "position", "team", "now_cost"]].rename(
        columns={"id": "player_id"}
    )
    team_name_map = dict(zip(teams_df["id"], teams_df["name"]))

    # Attach understat_id to each FPL GW row
    confirmed = id_map[id_map["match_status"].isin(["auto", "manual", "review"])][
        ["fpl_id", "understat_id"]
    ]
    gw_merged = gw_df.merge(
        confirmed, left_on="player_id", right_on="fpl_id", how="left"
    ).drop(columns=["fpl_id"])
    gw_merged["understat_id"] = (
        pd.to_numeric(gw_merged["understat_id"], errors="coerce").astype("Int64")
    )

    # Aggregate Understat: sum stats per player per match date
    us_matches = us_matches.copy()
    us_matches["date_only"] = pd.to_datetime(us_matches["date"]).dt.date
    us_agg = (
        us_matches
        .groupby(["understat_id", "date_only"], as_index=False)[
            ["xG", "xA", "shots", "key_passes", "npxG", "xGChain", "xGBuildup", "time"]
        ]
        .sum()
        .rename(columns={"time": "us_minutes"})
    )
    us_agg["understat_id"] = us_agg["understat_id"].astype("Int64")

    # Match by kickoff date
    gw_merged["kickoff_date"] = (
        pd.to_datetime(gw_merged["kickoff_time"], utc=True).dt.date
    )
    merged = gw_merged.merge(
        us_agg,
        left_on=["understat_id", "kickoff_date"],
        right_on=["understat_id", "date_only"],
        how="left",
    ).drop(columns=["kickoff_date", "date_only"])

    # Fill missing xG columns with 0
    xg_cols = ["xG", "xA", "shots", "key_passes", "npxG", "xGChain", "xGBuildup", "us_minutes"]
    for col in xg_cols:
        if col not in merged.columns:
            merged[col] = 0.0
        else:
            merged[col] = merged[col].fillna(0)

    # Attach player metadata
    merged = merged.merge(players_meta, on="player_id", how="left")
    merged["team_name"] = merged["team"].map(team_name_map)

    xg_cov = (merged["xG"] > 0).mean() * 100
    log.info(f"  Merged shape: {merged.shape}  |  xG coverage: {xg_cov:.1f}%")
    return merged


# ── Steps 4 + 5: Features + Model ────────────────────────────────────────────

def engineer_and_train(merged_df: pd.DataFrame, fixtures_df: pd.DataFrame) -> None:
    log.info("=== Step 4: Feature engineering ===")
    eng      = FeatureEngineer()
    features = eng.fit_transform(merged_df, fixtures_df)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    features.to_parquet(PROCESSED / "features.parquet", index=False)

    # Determine the latest *complete* GW (same threshold as the app)
    counts   = features.groupby("round").size()
    complete = counts[counts >= 650].index
    if complete.empty:
        log.warning("No complete GW found (threshold 650). Skipping prediction snapshot.")
        return
    latest_gw   = int(complete.max())
    predict_gw  = latest_gw + 1
    log.info(f"  Features saved: {features.shape}  |  latest complete GW: {latest_gw}  →  predicting GW {predict_gw}")

    log.info("=== Step 5: Retraining model ===")
    predictor = FPLPredictor(models_dir=MODELS)
    predictor.train(features)
    predictor.save()
    log.info("  Model saved.")

    log.info("=== Step 6: Saving prediction snapshot ===")
    snapshot_path = PREDICTIONS / f"gw{predict_gw}.parquet"
    if snapshot_path.exists():
        log.info(f"  Snapshot for GW{predict_gw} already exists — overwriting.")

    latest_df = features[features["round"] == latest_gw].copy()
    latest_df["predicted_pts"] = predictor.predict(latest_df)
    latest_df["predict_gw"]    = predict_gw

    PREDICTIONS.mkdir(parents=True, exist_ok=True)
    latest_df.to_parquet(snapshot_path, index=False)
    log.info(f"  Prediction snapshot saved → data/predictions/gw{predict_gw}.parquet ({len(latest_df)} players)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 60)
    log.info("FPL Intelligence — Data Refresh Pipeline")
    log.info("=" * 60)

    # Load existing id_map — never overwritten here
    id_map_path = PROCESSED / "player_id_map.parquet"
    if not id_map_path.exists():
        log.error("player_id_map.parquet not found. Run notebook 02 first.")
        sys.exit(1)
    id_map = pd.read_parquet(id_map_path)
    log.info(f"Loaded player_id_map: {len(id_map)} entries "
             f"({id_map['match_status'].value_counts().to_dict()})")

    # Step 1 — FPL
    players, teams, fixtures, gw_df = fetch_fpl()
    RAW.mkdir(parents=True, exist_ok=True)
    players.to_parquet(RAW / "fpl_players.parquet", index=False)
    teams.to_parquet(RAW / "fpl_teams.parquet", index=False)
    fixtures.to_parquet(RAW / "fpl_fixtures.parquet", index=False)
    gw_df.to_parquet(RAW / "fpl_gameweeks.parquet", index=False)
    log.info("  FPL data saved to data/raw/")

    # Step 2 — Understat
    us_players, us_matches = fetch_understat(id_map)
    us_players.to_parquet(RAW / "understat_players.parquet", index=False)
    us_matches.to_parquet(RAW / "understat_matches.parquet", index=False)
    log.info("  Understat data saved to data/raw/")

    # Step 3 — Merge
    merged = merge_data(players, teams, gw_df, id_map, us_matches)
    merged.to_parquet(PROCESSED / "merged_players.parquet", index=False)
    log.info("  Merged data saved to data/processed/")

    # Steps 4 + 5 — Features + Model
    engineer_and_train(merged, fixtures)

    log.info("=" * 60)
    log.info("Pipeline complete.")
    log.info("Restart the Dash app to serve fresh predictions.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
