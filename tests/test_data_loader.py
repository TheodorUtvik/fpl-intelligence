"""
Tests for app/data_loader.py's cold-start behaviour: when a season has
just rolled over and none of data/raw, data/processed, or models/ exist
yet, every loader must degrade gracefully (empty DataFrame / None / 0)
rather than raise — see the crash points fixed in the app cold-start work.
"""
from pathlib import Path

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
