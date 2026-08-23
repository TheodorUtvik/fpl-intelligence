"""
Tests for src/models/optimize.py — the ILP squad/XI selector must
actually respect FPL's real constraints, not just "run without crashing".
"""

import pandas as pd
import pytest

from src.models.optimize import (
    MAX_PER_CLUB,
    POSITION_COUNTS,
    STARTING_XI,
    FPLOptimizer,
)


def _player_pool() -> pd.DataFrame:
    """
    A synthetic pool with enough depth per position, spread across 6 teams
    (so a 15-man squad — 3 per team max — is actually reachable), and cheap
    enough overall that a feasible squad exists comfortably under £100m.
    """
    rows = []
    pid = 1
    teams = list(range(1, 7))
    counts = {"GKP": 6, "DEF": 12, "MID": 12, "FWD": 8}
    base_cost = {"GKP": 4.5, "DEF": 4.5, "MID": 5.5, "FWD": 5.5}
    for pos, n in counts.items():
        for i in range(n):
            rows.append({
                "player_id": pid,
                "web_name": f"{pos}{i}",
                "position": pos,
                "team": teams[i % len(teams)],
                "now_cost": base_cost[pos] + (i % 4) * 0.5,
                "predicted_pts": 2.0 + (i % 7) * 0.7,
                "status": "a",
            })
            pid += 1
    return pd.DataFrame(rows)


def test_select_squad_respects_all_constraints():
    players = _player_pool()
    result = FPLOptimizer(budget=100.0).select_squad(players)

    assert result["status"] == "Optimal"
    squad = result["squad"]
    assert len(squad) == 15
    assert squad["now_cost"].sum() <= 100.0 + 1e-6

    for pos, count in POSITION_COUNTS.items():
        assert (squad["position"] == pos).sum() == count

    team_counts = squad["team"].value_counts()
    assert (team_counts <= MAX_PER_CLUB).all()

    assert squad["is_captain"].sum() == 1
    captain_pts = squad.loc[squad["is_captain"], "predicted_pts"].iloc[0]
    expected_total = squad["predicted_pts"].sum() + captain_pts  # captain counts double
    assert result["predicted_total"] == pytest.approx(expected_total, abs=0.01)


def test_select_starting_xi_respects_formation_and_size():
    players = _player_pool()
    result = FPLOptimizer(budget=100.0).select_starting_xi(players)

    assert result["status"] == "Optimal"
    xi = result["xi"]
    assert len(xi) == STARTING_XI
    assert xi["now_cost"].sum() <= 100.0 + 1e-6

    n_gkp = (xi["position"] == "GKP").sum()
    n_def = (xi["position"] == "DEF").sum()
    n_mid = (xi["position"] == "MID").sum()
    n_fwd = (xi["position"] == "FWD").sum()
    assert n_gkp == 1
    assert 3 <= n_def <= 5
    assert 2 <= n_mid <= 5
    assert 1 <= n_fwd <= 3
    assert n_gkp + n_def + n_mid + n_fwd == STARTING_XI

    team_counts = xi["team"].value_counts()
    assert (team_counts <= MAX_PER_CLUB).all()
    assert result["formation"] == f"{n_def}-{n_mid}-{n_fwd}"


def test_select_squad_infeasible_budget_does_not_crash():
    players = _player_pool()
    result = FPLOptimizer(budget=1.0).select_squad(players)

    assert result["status"] == "Infeasible"
    assert result["squad"].empty
