"""
Shared utilities for season detection, GW-completeness thresholds, and
season-rollover archiving. Used by both the CI pipeline scripts and the
Dash app so a season transition only needs to be handled in one place.
"""

import logging
import shutil
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Files moved into data/archive/{label}/ on a season rollover.
_ARCHIVE_GROUPS = [
    ("data/raw", [
        "fpl_players.parquet", "fpl_teams.parquet",
        "fpl_fixtures.parquet", "fpl_gameweeks.parquet",
        "understat_players.parquet", "understat_matches.parquet",
    ]),
    ("data/processed", [
        "features.parquet", "merged_players.parquet", "player_id_map.parquet",
    ]),
    ("models", [
        "xgboost_model.json", "shap_explainer.pkl",
        "feature_cols.json", "best_params.json",
    ]),
]


def current_season_start_year(events: pd.DataFrame) -> str:
    """
    Derive the current season's start year from gameweek 1's deadline.

    GW1's date is fixed for the whole season and doesn't move as later
    gameweeks are played, so this is stable to call at any point in the
    season. Matches the bare-year format Understat's `season` API
    parameter expects (e.g. "2026" for the 2026/27 season).
    """
    gw1 = events.sort_values("id").iloc[0]
    return str(pd.to_datetime(gw1["deadline_time"]).year)


def season_label(start_year: str) -> str:
    """Human-readable season label, e.g. "2026" -> "2026-27"."""
    y = int(start_year)
    return f"{y}-{str(y + 1)[2:]}"


def completeness_threshold(counts: pd.Series, frac: float = 0.85, floor: int = 100) -> int:
    """
    Minimum per-round row count for a gameweek to be considered "complete"
    (fully processed by the FPL API, not a partial/in-progress GW).

    Scales with the actual per-season player pool by taking a fraction of
    the median round size seen so far, rather than a constant tuned to one
    season's player count (which breaks the moment the pool size changes).
    `floor` is a sanity minimum so a single, still-partial round can't
    trivially pass just because there's nothing yet to compare it against.
    """
    if counts.empty:
        return floor
    return max(int(counts.median() * frac), floor)


def archive_season(root: Path, label: str) -> bool:
    """
    Move all season-scoped data/model artefacts into data/archive/{label}/
    ahead of a new season's first fetch. Idempotent: a no-op if that
    archive directory already exists, so it's safe to call unconditionally
    on every pipeline run.

    Returns True if archiving was performed, False if skipped.
    """
    archive_dir = root / "data" / "archive" / label
    if archive_dir.exists():
        logger.info(f"Archive for season {label} already exists — skipping.")
        return False

    moved_any = False

    for rel_dir, filenames in _ARCHIVE_GROUPS:
        src_dir = root / rel_dir
        dst_dir = archive_dir / Path(rel_dir).name
        names = list(filenames)
        if src_dir.name == "models":
            names += [p.name for p in src_dir.glob("*.png")]
        for name in names:
            src = src_dir / name
            if src.exists():
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst_dir / name))
                moved_any = True

    # Prediction snapshots have variable filenames (gw{N}.parquet)
    pred_src = root / "data" / "predictions"
    pred_dst = archive_dir / "predictions"
    if pred_src.exists():
        for f in pred_src.glob("gw*.parquet"):
            pred_dst.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(pred_dst / f.name))
            moved_any = True

    if moved_any:
        logger.info(f"Archived season {label} -> data/archive/{label}/")
    else:
        logger.info(f"Season {label} rollover detected but nothing to archive.")
    return moved_any
