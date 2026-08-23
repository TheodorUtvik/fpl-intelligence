"""
Tests for app/team_manager.py:
  - fetch_squad_from_fpl's error handling for the FPL picks endpoint
    (503 during GW rollover, 404 for a bad team ID, malformed JSON).
  - apply_transfer/undo_transfer round-trip against an isolated SQLite
    DB (never the real data/fpl.db).
"""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import app.db as db
import app.team_manager as tm


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch):
    """Point app.db at a throwaway SQLite file for the duration of the test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_fpl.db")
    db.init_db()
    return db.DEFAULT_USER_ID


class TestFetchSquadFromFpl:
    def _resp(self, status_code, json_value=None, json_raises=False):
        resp = Mock()
        resp.status_code = status_code
        if json_raises:
            resp.json.side_effect = ValueError("not JSON")
        else:
            resp.json.return_value = json_value
        resp.raise_for_status = Mock()
        return resp

    def test_503_raises_friendly_maintenance_message(self):
        with patch("app.team_manager.requests.get", return_value=self._resp(503)):
            with pytest.raises(RuntimeError, match="being updated"):
                tm.fetch_squad_from_fpl(12345, gw=1)

    def test_404_raises_friendly_not_found_message(self):
        with patch("app.team_manager.requests.get", return_value=self._resp(404)):
            with pytest.raises(RuntimeError, match="not found"):
                tm.fetch_squad_from_fpl(12345, gw=1)

    def test_non_json_response_raises_runtime_error(self):
        with patch("app.team_manager.requests.get", return_value=self._resp(200, json_raises=True)):
            with pytest.raises(RuntimeError, match="unexpected response"):
                tm.fetch_squad_from_fpl(12345, gw=1)

    def test_malformed_json_missing_picks_raises_runtime_error(self):
        resp = self._resp(200, json_value={"detail": "Not found."})
        with patch("app.team_manager.requests.get", return_value=resp):
            with pytest.raises(RuntimeError, match="Not found"):
                tm.fetch_squad_from_fpl(12345, gw=1)

    def test_success_returns_picks_and_bank(self):
        resp = self._resp(200, json_value={
            "picks": [{"element": 1, "position": 1}],
            "entry_history": {"bank": 15},
            "active_chip": None,
        })
        with patch("app.team_manager.requests.get", return_value=resp):
            data = tm.fetch_squad_from_fpl(12345, gw=1)
        assert data["picks"] == [{"element": 1, "position": 1}]
        assert data["bank"] == pytest.approx(1.5)  # tenths -> £m


class TestTransferRoundTrip:
    def test_apply_then_undo_restores_bank_and_free_transfers(self, isolated_db):
        user_id = isolated_db
        tm.save_team(
            picks=[
                {"player_id": 1, "purchase_price": 5.0, "selling_price": 5.0},
                {"player_id": 2, "purchase_price": 6.0, "selling_price": 6.0},
            ],
            bank=2.0, free_transfers=1, user_id=user_id,
        )

        result = tm.apply_transfer(out_player_id=1, in_player_id=99, in_player_cost=6.5, user_id=user_id)
        assert result["bank"] == pytest.approx(2.0 + 5.0 - 6.5)  # +selling price, -new cost
        assert result["free_transfers"] == 0

        team_after = tm.load_team(user_id)
        assert {p["player_id"] for p in team_after["players"]} == {99, 2}

        tm.undo_transfer(result["undo"], user_id=user_id)

        team_restored = tm.load_team(user_id)
        assert {p["player_id"] for p in team_restored["players"]} == {1, 2}
        assert team_restored["bank"] == pytest.approx(2.0)
        assert team_restored["free_transfers"] == 1

    def test_apply_transfer_never_takes_free_transfers_below_zero(self, isolated_db):
        user_id = isolated_db
        tm.save_team(
            picks=[{"player_id": 1, "purchase_price": 5.0, "selling_price": 5.0}],
            bank=0.0, free_transfers=0, user_id=user_id,
        )
        result = tm.apply_transfer(out_player_id=1, in_player_id=2, in_player_cost=5.0, user_id=user_id)
        assert result["free_transfers"] == 0

    def test_restore_original_squad_uses_snapshot(self, isolated_db):
        user_id = isolated_db
        original_picks = [{"player_id": 1, "purchase_price": 5.0, "selling_price": 5.0}]
        tm.save_team(picks=original_picks, bank=1.0, free_transfers=1,
                     user_id=user_id, is_original=True)

        tm.apply_transfer(out_player_id=1, in_player_id=2, in_player_cost=6.0, user_id=user_id)
        assert {p["player_id"] for p in tm.load_team(user_id)["players"]} == {2}

        tm.restore_original_squad(user_id=user_id)
        restored = tm.load_team(user_id)
        assert {p["player_id"] for p in restored["players"]} == {1}
        assert restored["bank"] == pytest.approx(1.0)
        assert restored["free_transfers"] == 1
