"""
Tests for app/data_loader.py's cold-start behaviour: when a season has
just rolled over and none of data/raw, data/processed, or models/ exist
yet, every loader must degrade gracefully (empty DataFrame / None / 0)
rather than raise — see the crash points fixed in the app cold-start work.
"""
from pathlib import Path

import pandas as pd
import pytest

import app.data_loader as dl


@pytest.fixture
def empty_data_dirs(tmp_path: Path, monkeypatch):
    """Point every data_loader path constant at empty directories, and
    clear all lru_caches before and after so no test contaminates another."""
    (tmp_path / "raw").mkdir()
    (tmp_path / "processed").mkdir()
    (tmp_path / "predictions").mkdir()
    (tmp_path / "models").mkdir()

    monkeypatch.setattr(dl, "RAW", tmp_path / "raw")
    monkeypatch.setattr(dl, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(dl, "PREDICTIONS", tmp_path / "predictions")
    monkeypatch.setattr(dl, "MODELS", tmp_path / "models")

    cached_fns = [
        dl.load_features, dl.load_fpl_players, dl.load_fixtures, dl.load_teams,
        dl.get_predictor, dl.get_latest_gw, dl.get_players_with_predictions,
        dl.get_available_players,
    ]
    for fn in cached_fns:
        fn.cache_clear()
    yield
    for fn in cached_fns:
        fn.cache_clear()


def test_load_features_returns_empty_when_missing(empty_data_dirs):
    features = dl.load_features()
    assert features.empty


def test_get_latest_gw_returns_zero_sentinel_when_no_data(empty_data_dirs):
    assert dl.get_latest_gw() == 0


def test_get_predictor_returns_none_when_no_model(empty_data_dirs):
    assert dl.get_predictor() is None


def test_predictions_available_is_false_when_no_data(empty_data_dirs):
    assert dl.predictions_available() is False


def test_get_players_with_predictions_returns_empty_correctly_shaped(empty_data_dirs):
    pool = dl.get_players_with_predictions()
    assert pool.empty
    assert list(pool.columns) == dl.POOL_COLUMNS


def test_get_available_players_returns_empty_without_crashing(empty_data_dirs):
    assert dl.get_available_players().empty


def test_get_features_for_player_returns_empty_without_crashing(empty_data_dirs):
    assert dl.get_features_for_player(123).empty


@pytest.fixture
def archived_season(tmp_path: Path, monkeypatch):
    """A synthetic archived season (data/archive/2025-26/) plus an empty
    live season, matching the real repo shape after a rollover."""
    (tmp_path / "raw").mkdir()
    (tmp_path / "predictions").mkdir()
    archive_raw = tmp_path / "data" / "archive" / "2025-26" / "raw"
    archive_pred = tmp_path / "data" / "archive" / "2025-26" / "predictions"
    archive_raw.mkdir(parents=True)
    archive_pred.mkdir(parents=True)

    pd.DataFrame({
        "player_id": [1, 2, 3, 1, 2, 3],
        "round":     [5, 5, 5, 6, 6, 6],
        "total_points": [10, 0, 4, 2, 6, 0],
        "minutes":      [90, 0, 90, 90, 90, 0],  # player 2 didn't play GW5, player 3 didn't play GW6
    }).to_parquet(archive_raw / "fpl_gameweeks.parquet", index=False)

    pd.DataFrame({
        "player_id": [1, 2, 3], "web_name": ["A", "B", "C"], "predicted_pts": [3.0, 1.0, 2.0],
    }).to_parquet(archive_pred / "gw5.parquet", index=False)
    pd.DataFrame({
        "player_id": [1, 2, 3], "web_name": ["A", "B", "C"], "predicted_pts": [1.0, 4.0, 2.5],
    }).to_parquet(archive_pred / "gw6.parquet", index=False)

    monkeypatch.setattr(dl, "ROOT", tmp_path)
    monkeypatch.setattr(dl, "RAW", tmp_path / "raw")
    monkeypatch.setattr(dl, "PREDICTIONS", tmp_path / "predictions")
    dl.get_season_calibration.cache_clear()
    yield
    dl.get_season_calibration.cache_clear()


def test_get_season_calibration_matches_predictions_to_actuals(archived_season):
    df = dl.get_season_calibration("2025-26")
    # Player 2 (0 min GW5) and player 3 (0 min GW6) are filtered out by the
    # minutes > 0 guard; the remaining 4 rows should have correct diffs.
    assert len(df) == 4
    gw5_p1 = df[(df["predict_gw"] == 5) & (df["player_id"] == 1)].iloc[0]
    assert gw5_p1["actual_pts"] == 10
    assert gw5_p1["predicted_pts"] == pytest.approx(3.0)
    assert gw5_p1["diff"] == pytest.approx(7.0)


def test_get_season_calibration_unknown_season_returns_empty(archived_season):
    assert dl.get_season_calibration("1999-00").empty


def test_get_calibration_season_options_excludes_empty_current(archived_season):
    options = dl.get_calibration_season_options()
    values = [o["value"] for o in options]
    assert "2025-26" in values
    assert "current" not in values  # empty live season has no snapshots yet
