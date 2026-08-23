"""
Tests for src/features/engineer.py — specifically the data-leakage guards
documented in PREDICTION_DATA_INTEGRITY.md:

  - Rolling features must use shift(1): a round's own stats must never
    leak into its own rolling-average features.
  - The target (pts_next_gw) must come from the *next* round's points,
    via groupby(player_id).shift(-1).
  - GW1 rows are dropped (no prior-round history to build features from).
  - The final round per player is *kept* even though its target is null
    (that's the row inference predicts from) — only rows missing input
    features are dropped, never rows missing the target.
"""

import pandas as pd
import pytest

from src.features.engineer import FeatureEngineer

STAT_COLS = [
    "total_points", "minutes", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
    "yellow_cards", "red_cards", "saves", "bonus", "bps",
    "influence", "creativity", "threat", "ict_index",
    "xG", "xA", "shots", "key_passes", "npxG", "xGChain", "xGBuildup", "us_minutes",
]


def _build_dataset(points_a: list[int], points_b: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build a minimal but structurally valid (merged_df, fixtures_df) pair:
    two players on two different teams, one row per round, team 1 vs
    team 2 every round. `points_a`/`points_b` set each player's
    total_points per round (round numbers = 1..len(points)).
    """
    n_rounds = len(points_a)
    assert len(points_b) == n_rounds

    fixtures_rows = []
    for r in range(1, n_rounds + 2):  # one extra round so fdr_next resolves for the last real round
        home, away = (1, 2) if r % 2 == 1 else (2, 1)
        fixtures_rows.append({
            "event": r, "team_h": home, "team_a": away,
            "team_h_difficulty": 3, "team_a_difficulty": 3,
            "team_h_score": 1, "team_a_score": 0,
            "finished": r <= n_rounds,
            "kickoff_time": pd.Timestamp("2026-08-01", tz="UTC") + pd.Timedelta(days=7 * (r - 1)),
        })
    fixtures_df = pd.DataFrame(fixtures_rows)

    def _rows(player_id, web_name, team, points):
        rows = []
        for i, pts in enumerate(points):
            r = i + 1
            row = {
                "player_id": player_id, "web_name": web_name, "position": "MID", "team": team,
                "round": r,
                "kickoff_time": fixtures_df.loc[fixtures_df["event"] == r, "kickoff_time"].iloc[0],
                "total_points": pts, "minutes": 90,
                "value": 50, "selected": 1000, "now_cost": 50,
            }
            for col in STAT_COLS:
                row.setdefault(col, 0.0)
            rows.append(row)
        return rows

    merged_df = pd.DataFrame(_rows(1, "Player A", 1, points_a) + _rows(2, "Player B", 2, points_b))
    return merged_df, fixtures_df


def test_gw1_is_dropped():
    merged_df, fixtures_df = _build_dataset([2, 3, 4, 5], [1, 1, 1, 1])
    features = FeatureEngineer().fit_transform(merged_df, fixtures_df)
    assert 1 not in set(features["round"].unique())


def test_last_gw_kept_with_null_target():
    """The final round per player must stay in the output — with pts_next_gw
    null — so inference can predict from it. Only input-feature nulls
    (rolling_pts_3gw) drop a row, never target nulls."""
    merged_df, fixtures_df = _build_dataset([2, 3, 4, 5], [1, 1, 1, 1])
    features = FeatureEngineer().fit_transform(merged_df, fixtures_df)

    last_row = features[(features["player_id"] == 1) & (features["round"] == 4)]
    assert len(last_row) == 1
    assert last_row["pts_next_gw"].isna().all()


def test_rolling_pts_excludes_current_round():
    """A round's own total_points must never appear in that round's own
    rolling_pts_3gw — this is the core shift(1) leakage guard."""
    # Round 3 gets a deliberate outlier; if it leaked into its own rolling
    # feature the mean would jump far above what rounds 1-2 alone produce.
    merged_df, fixtures_df = _build_dataset([2, 3, 100, 5], [1, 1, 1, 1])
    features = FeatureEngineer().fit_transform(merged_df, fixtures_df)

    round3 = features[(features["player_id"] == 1) & (features["round"] == 3)].iloc[0]
    # mean(total_points at rounds 1,2) = mean(2, 3) = 2.5 — the 100 at
    # round 3 itself must be absent.
    assert round3["rolling_pts_3gw"] == pytest.approx(2.5)

    round4 = features[(features["player_id"] == 1) & (features["round"] == 4)].iloc[0]
    # By round 4, round 3's 100 is legitimately in the past and should show up.
    assert round4["rolling_pts_3gw"] == pytest.approx((2 + 3 + 100) / 3)


def test_target_is_next_rounds_points_not_current():
    merged_df, fixtures_df = _build_dataset([2, 3, 100, 5], [1, 1, 1, 1])
    features = FeatureEngineer().fit_transform(merged_df, fixtures_df)

    round2 = features[(features["player_id"] == 1) & (features["round"] == 2)].iloc[0]
    # pts_next_gw at round 2 must equal round 3's total_points (100),
    # not round 2's own (3).
    assert round2["pts_next_gw"] == pytest.approx(100.0)


def test_aggregate_player_round_collapses_duplicate_fixture_rows():
    """A blank/double-gameweek player can have two raw rows for the same
    (player_id, round) if their team played twice. These must collapse
    to exactly one row per (player_id, round) before any feature is built,
    per PREDICTION_DATA_INTEGRITY.md rule 5."""
    merged_df, fixtures_df = _build_dataset([2, 3, 4, 5], [1, 1, 1, 1])

    # Duplicate player 1's round-2 row (simulating a double gameweek fixture pair)
    dup = merged_df[(merged_df["player_id"] == 1) & (merged_df["round"] == 2)].copy()
    dup["total_points"] = 6  # second fixture's points
    merged_df = pd.concat([merged_df, dup], ignore_index=True)

    features = FeatureEngineer().fit_transform(merged_df, fixtures_df)
    round2_rows = features[(features["player_id"] == 1) & (features["round"] == 2)]
    assert len(round2_rows) == 1
