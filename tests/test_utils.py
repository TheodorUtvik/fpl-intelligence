"""Tests for src/utils.py — season detection, GW-completeness thresholds,
Understat readiness, and season-archive plumbing."""

from pathlib import Path

import pandas as pd
import pytest

from src.utils import (
    archive_season,
    completeness_threshold,
    current_season_start_year,
    season_label,
    understat_ready_for_gw,
)


def _events(deadlines: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "id": range(1, len(deadlines) + 1),
        "deadline_time": deadlines,
    })


def test_current_season_start_year_uses_gw1_deadline():
    events = _events(["2026-08-21T17:30:00Z", "2026-08-29T14:00:00Z", "2027-01-01T15:00:00Z"])
    assert current_season_start_year(events) == "2026"


def test_current_season_start_year_ignores_row_order():
    # GW1's deadline is what matters, not the first row physically
    events = _events(["2026-08-29T14:00:00Z", "2026-08-21T17:30:00Z"])
    events["id"] = [2, 1]
    assert current_season_start_year(events) == "2026"


def test_season_label_formats_correctly():
    assert season_label("2026") == "2026-27"
    assert season_label("2025") == "2025-26"


@pytest.mark.parametrize("counts,expected", [
    ([], 100),                  # empty -> floor
    ([50], 100),                # single low round -> floor (0.85*50=42) wins
    ([800, 820, 810], 688),     # 0.85 * median(810) = 688.5 -> int() truncates to 688
])
def test_completeness_threshold_scales_with_pool_size(counts, expected):
    assert completeness_threshold(pd.Series(counts)) == expected


def test_completeness_threshold_never_below_floor():
    # A tiny pool (e.g. a blank gameweek) must not produce a near-zero threshold
    assert completeness_threshold(pd.Series([10, 12, 11]), floor=100) == 100


def test_completeness_threshold_single_complete_round_passes_itself():
    # The very first round of a season has nothing to compare against yet —
    # it must not be excluded just because it's alone in the series.
    counts = pd.Series([600])
    threshold = completeness_threshold(counts)
    assert 600 >= threshold


class TestUnderstatReadiness:
    def _fixtures(self, event: int = 1) -> pd.DataFrame:
        return pd.DataFrame({
            "event": [event, event, event],
            "kickoff_time": [
                "2026-08-22T14:00:00Z", "2026-08-22T16:30:00Z", "2026-08-23T15:00:00Z",
            ],
        })

    def test_not_ready_with_too_few_rows(self):
        fixtures = self._fixtures()
        matches = pd.DataFrame({"date": ["2026-08-22 14:00:00"] * 10})
        assert understat_ready_for_gw(matches, fixtures, 1) is False

    def test_ready_with_enough_rows(self):
        fixtures = self._fixtures()
        matches = pd.DataFrame({"date": ["2026-08-22 14:00:00"] * 70})
        assert understat_ready_for_gw(matches, fixtures, 1) is True

    def test_blank_gameweek_is_always_ready(self):
        fixtures = self._fixtures(event=1)
        matches = pd.DataFrame({"date": []})
        assert understat_ready_for_gw(matches, fixtures, gw=99) is True

    def test_rows_before_kickoff_dont_count(self):
        fixtures = self._fixtures()
        stale = pd.DataFrame({"date": ["2026-08-01 14:00:00"] * 70})
        assert understat_ready_for_gw(stale, fixtures, 1) is False


class TestArchiveSeason:
    def test_moves_files_into_archive(self, tmp_path: Path):
        (tmp_path / "data" / "raw").mkdir(parents=True)
        (tmp_path / "data" / "raw" / "fpl_players.parquet").write_bytes(b"x")
        (tmp_path / "models").mkdir()
        (tmp_path / "models" / "xgboost_model.json").write_text("{}")

        moved = archive_season(tmp_path, "2025-26")

        assert moved is True
        assert (tmp_path / "data" / "archive" / "2025-26" / "raw" / "fpl_players.parquet").exists()
        assert (tmp_path / "data" / "archive" / "2025-26" / "models" / "xgboost_model.json").exists()
        assert not (tmp_path / "data" / "raw" / "fpl_players.parquet").exists()

    def test_idempotent_when_already_archived(self, tmp_path: Path):
        (tmp_path / "data" / "archive" / "2025-26").mkdir(parents=True)
        assert archive_season(tmp_path, "2025-26") is False

    def test_no_op_when_nothing_to_archive(self, tmp_path: Path):
        assert archive_season(tmp_path, "2025-26") is False
