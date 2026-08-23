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
from src.utils import completeness_threshold  # noqa: E402

PROCESSED   = ROOT / "data" / "processed"
PREDICTIONS = ROOT / "data" / "predictions"
RAW         = ROOT / "data" / "raw"
MODELS      = ROOT / "models"

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POS_ORDER    = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}

# Columns returned by get_players_with_predictions() — kept as a constant
# so the cold-start empty-DataFrame fallback has the same shape callers expect.
POOL_COLUMNS = [
    "player_id", "now_cost", "predicted_pts", "games_played",
    "rolling_pts_3gw", "rolling_xg_3gw", "rolling_xa_3gw",
    "ownership_pct", "fdr_next", "web_name", "position", "team",
    "status", "team_name", "pts_per_million", "pos_order",
]


@lru_cache(maxsize=1)
def load_features() -> pd.DataFrame:
    """Returns an empty DataFrame if features.parquet doesn't exist yet
    (e.g. right after a season rollover, before Stage 2 has run)."""
    path = PROCESSED / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


@lru_cache(maxsize=1)
def load_fpl_players() -> pd.DataFrame:
    path = RAW / "fpl_players.parquet"
    if not path.exists():
        return pd.DataFrame(columns=[
            "id", "web_name", "position", "team", "status", "now_cost", "element_type",
        ])
    df = pd.read_parquet(path)
    df["position"] = df["element_type"].map(POSITION_MAP)
    return df


@lru_cache(maxsize=1)
def load_fixtures() -> pd.DataFrame:
    path = RAW / "fpl_fixtures.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


@lru_cache(maxsize=1)
def load_teams() -> pd.DataFrame:
    path = RAW / "fpl_teams.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["id", "name", "short_name"])
    return pd.read_parquet(path)


@lru_cache(maxsize=1)
def get_predictor() -> FPLPredictor | None:
    """
    Returns the trained predictor, or None if no model has been trained
    yet for the current season (e.g. right after a season rollover, before
    enough gameweeks have accrued to train on). Callers must check for
    None rather than assuming a model is always available.
    """
    p = FPLPredictor(models_dir=MODELS)
    try:
        p.load()
    except FileNotFoundError:
        return None
    return p


@lru_cache(maxsize=1)
def get_optimizer() -> FPLOptimizer:
    return FPLOptimizer(budget=100.0)


@lru_cache(maxsize=1)
def get_latest_gw() -> int:
    """
    Returns the latest gameweek that has enough data to be considered
    complete, or 0 if no complete gameweek exists yet (season just
    started, or features haven't been built). Callers should treat 0 as
    "no predictions available yet" rather than a real gameweek number.
    """
    features = load_features()
    if features.empty or "round" not in features.columns:
        return 0
    counts = features.groupby("round").size()
    threshold = completeness_threshold(counts)
    complete = counts[counts >= threshold].index
    if complete.empty:
        return 0
    return int(complete.max())


def predictions_available() -> bool:
    """True once there's at least one complete current-season GW and a trained model."""
    return get_latest_gw() > 0 and get_predictor() is not None


@lru_cache(maxsize=1)
def get_players_with_predictions() -> pd.DataFrame:
    """
    Returns the full player pool for the latest complete GW, including
    predicted points and metadata. Returns an empty DataFrame (with the
    usual columns) if no complete GW or trained model exists yet —
    callers should check `.empty` and show a "season warming up" state.
    """
    latest_gw = get_latest_gw()
    predictor = get_predictor()
    if latest_gw == 0 or predictor is None:
        return pd.DataFrame(columns=POOL_COLUMNS)

    features  = load_features()
    fpl       = load_fpl_players()

    latest_df = features[features["round"] == latest_gw].copy()
    latest_df["predicted_pts"] = predictor.predict(latest_df)
    if "games_played" in latest_df.columns:
        latest_df = (
            latest_df
            .sort_values(["player_id", "games_played", "predicted_pts"])
            .drop_duplicates(subset=["player_id"], keep="last")
        )
    else:
        latest_df = (
            latest_df
            .sort_values(["player_id", "predicted_pts"])
            .drop_duplicates(subset=["player_id"], keep="last")
        )

    fpl_meta = fpl[["id", "web_name", "position", "team", "status", "now_cost"]].rename(
        columns={"id": "player_id"}
    )

    pool = latest_df[["player_id", "value", "predicted_pts", "games_played",
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
    if "games_played" in df.columns:
        df = (
            df
            .sort_values(["player_id", "games_played", "predicted_pts"])
            .drop_duplicates(subset=["player_id"], keep="last")
            .reset_index(drop=True)
        )
    else:
        df = (
            df
            .sort_values(["player_id", "predicted_pts"])
            .drop_duplicates(subset=["player_id"], keep="last")
            .reset_index(drop=True)
        )
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
    if features.empty:
        return features
    return features[features["player_id"] == player_id].sort_values("round").reset_index(drop=True)


@lru_cache(maxsize=1)
def get_available_players() -> pd.DataFrame:
    pool = get_players_with_predictions()
    if pool.empty:
        return pool
    avail = pool[pool["status"] == "a"].copy()
    if avail["position"].value_counts().get("GKP", 0) < 2:
        return pool
    return avail
