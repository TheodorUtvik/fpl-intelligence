"""
app/data_loader.py

Centralised, cached data loading for all Dash pages.
All heavy I/O and model inference happens once at startup.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

# Allow imports from project root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.predict import FPLPredictor  # noqa: E402
from src.models.optimize import FPLOptimizer  # noqa: E402

PROCESSED   = ROOT / "data" / "processed"
PREDICTIONS = ROOT / "data" / "predictions"
RAW         = ROOT / "data" / "raw"
MODELS      = ROOT / "models"

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POS_ORDER    = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


@lru_cache(maxsize=1)
def load_features() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "features.parquet")


@lru_cache(maxsize=1)
def load_fpl_players() -> pd.DataFrame:
    df = pd.read_parquet(RAW / "fpl_players.parquet")
    df["position"] = df["element_type"].map(POSITION_MAP)
    return df


@lru_cache(maxsize=1)
def load_fixtures() -> pd.DataFrame:
    return pd.read_parquet(RAW / "fpl_fixtures.parquet")


@lru_cache(maxsize=1)
def load_teams() -> pd.DataFrame:
    return pd.read_parquet(RAW / "fpl_teams.parquet")


@lru_cache(maxsize=1)
def get_predictor() -> FPLPredictor:
    p = FPLPredictor(models_dir=MODELS)
    p.load()
    return p


@lru_cache(maxsize=1)
def get_optimizer() -> FPLOptimizer:
    return FPLOptimizer(budget=100.0)


@lru_cache(maxsize=1)
def get_latest_gw() -> int:
    """
    Returns the latest gameweek that has enough data to be considered complete.
    Threshold of 650 players ensures partial GWs (mid-week, still in progress)
    are ignored — the app stays on the last fully-played GW instead of
    showing predictions derived from incomplete data.
    """
    features = load_features()
    counts = features.groupby("round").size()
    complete = counts[counts >= 650].index
    return int(complete.max())


@lru_cache(maxsize=1)
def get_players_with_predictions() -> pd.DataFrame:
    """
    Returns the full player pool for the latest complete GW,
    including predicted points and metadata.
    """
    features  = load_features()
    fpl       = load_fpl_players()
    predictor = get_predictor()
    latest_gw = get_latest_gw()

    latest_df = features[features["round"] == latest_gw].copy()
    latest_df["predicted_pts"] = predictor.predict(latest_df)

    fpl_meta = fpl[["id", "web_name", "position", "team", "status", "now_cost"]].rename(
        columns={"id": "player_id"}
    )

    pool = latest_df[["player_id", "value", "predicted_pts",
                       "rolling_pts_3gw", "rolling_xg_3gw", "rolling_xa_3gw",
                       "ownership_pct", "fdr_next"]].copy()
    pool.rename(columns={"value": "now_cost"}, inplace=True)
    pool = pool.merge(fpl_meta[["player_id", "web_name", "position", "team", "status"]],
                      on="player_id", how="left")
    pool = pool.dropna(subset=["now_cost", "position", "predicted_pts"])
    pool = pool[pool["now_cost"] > 0]

    # Load team names
    teams = load_teams()[["id", "short_name"]].rename(columns={"id": "team", "short_name": "team_name"})
    pool = pool.merge(teams, on="team", how="left")

    pool["pts_per_million"] = pool["predicted_pts"] / pool["now_cost"]
    pool["pos_order"] = pool["position"].map(POS_ORDER)

    return pool.reset_index(drop=True)


def get_prediction_history_gws() -> list[int]:
    """
    Return a sorted list of GW numbers for which a prediction snapshot exists
    in data/predictions/.
    """
    if not PREDICTIONS.exists():
        return []
    gws = []
    for f in PREDICTIONS.glob("gw*.parquet"):
        try:
            gws.append(int(f.stem.replace("gw", "")))
        except ValueError:
            pass
    return sorted(gws)


def load_predictions_for_gw(predict_gw: int) -> pd.DataFrame:
    """
    Load a saved prediction snapshot for a specific GW.
    Attaches team_name and pts_per_million for display.
    """
    path = PREDICTIONS / f"gw{predict_gw}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No prediction snapshot for GW{predict_gw}")

    df = pd.read_parquet(path)
    teams = load_teams()[["id", "short_name"]].rename(
        columns={"id": "team", "short_name": "team_name"}
    )
    df = df.merge(teams, on="team", how="left")

    fpl_meta = load_fpl_players()[["id", "web_name", "status"]].rename(
        columns={"id": "player_id"}
    )
    if "web_name" not in df.columns:
        df = df.merge(fpl_meta, on="player_id", how="left")

    df = df.rename(columns={"value": "now_cost"}) if "value" in df.columns and "now_cost" not in df.columns else df
    df["pts_per_million"] = df["predicted_pts"] / df["now_cost"].replace(0, float("nan"))
    df["pos_order"] = df["position"].map(POS_ORDER)
    return df.reset_index(drop=True)


def get_features_for_player(player_id: int) -> pd.DataFrame:
    """Return all feature rows for a single player, sorted by round."""
    features = load_features()
    return features[features["player_id"] == player_id].sort_values("round").reset_index(drop=True)


@lru_cache(maxsize=1)
def get_available_players() -> pd.DataFrame:
    pool = get_players_with_predictions()
    avail = pool[pool["status"] == "a"].copy()
    if avail["position"].value_counts().get("GKP", 0) < 2:
        return pool
    return avail
