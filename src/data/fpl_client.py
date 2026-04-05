"""
FPL API client.

Wraps the three endpoints used by this project:
  - /bootstrap-static/      → players, teams, gameweek metadata
  - /fixtures/              → all fixtures + FDR
  - /element-summary/{id}/  → per-player gameweek history

Usage
-----
    from src.data.fpl_client import FPLClient

    client = FPLClient()
    players_df = client.get_players()
    gw_df      = client.get_all_gameweeks(players_df["id"].tolist())
    fixtures_df = client.get_fixtures()
"""

import time
import logging
from typing import Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# Columns to keep from the bootstrap elements array
PLAYER_COLS = [
    "id", "first_name", "second_name", "web_name",
    "element_type",         # 1=GKP 2=DEF 3=MID 4=FWD
    "team",
    "now_cost",             # price × 10 → divided to £m on load
    "selected_by_percent",
    "total_points",
    "minutes",
    "goals_scored", "assists", "clean_sheets", "bonus",
    "ict_index",
    "form",
    "status",               # a=available d=doubtful i=injured s=suspended u=unavailable
]

# Columns to keep from element-summary history
GW_COLS = [
    "player_id", "round",
    "total_points",
    "minutes", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
    "yellow_cards", "red_cards", "saves", "bonus", "bps",
    "influence", "creativity", "threat", "ict_index",
    "value",        # price at this GW × 10
    "selected",     # ownership count at this GW
    "was_home",
    "opponent_team",
    "kickoff_time",
]

# Columns to keep from fixtures
FIXTURE_COLS = [
    "id", "event",
    "team_h", "team_a",
    "team_h_difficulty", "team_a_difficulty",
    "team_h_score", "team_a_score",
    "finished", "kickoff_time",
]

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


class FPLClient:
    BASE_URL = "https://fantasy.premierleague.com/api/"

    def __init__(self, request_delay: float = 0.05):
        """
        Parameters
        ----------
        request_delay : float
            Seconds to sleep between per-player requests (default 50ms).
        """
        self.delay = request_delay
        self._bootstrap_cache: Optional[dict] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, endpoint: str) -> dict:
        url = f"{self.BASE_URL}{endpoint}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _bootstrap(self) -> dict:
        """Fetch and cache bootstrap-static so we only hit it once."""
        if self._bootstrap_cache is None:
            logger.info("Fetching bootstrap-static...")
            self._bootstrap_cache = self._get("bootstrap-static/")
        return self._bootstrap_cache

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_players(self) -> pd.DataFrame:
        """
        Return one row per player with current-season snapshot columns.
        Price is converted from tenths to £m (e.g. 65 → 6.5).
        A human-readable 'position' column is added.
        """
        elements = self._bootstrap()["elements"]
        df = pd.DataFrame(elements)[PLAYER_COLS].copy()
        df["now_cost"] = df["now_cost"] / 10
        df["position"] = df["element_type"].map(POSITION_MAP)
        return df

    def get_teams(self) -> pd.DataFrame:
        """Return team ID → name mapping."""
        teams = self._bootstrap()["teams"]
        return pd.DataFrame(teams)[["id", "name", "short_name"]]

    def get_events(self) -> pd.DataFrame:
        """Return gameweek metadata (deadlines, scores, current/next flags)."""
        events = self._bootstrap()["events"]
        cols = [
            "id", "name", "deadline_time", "finished",
            "is_current", "is_next",
            "average_entry_score", "highest_score",
        ]
        return pd.DataFrame(events)[cols]

    def get_current_gameweek(self) -> Optional[int]:
        """Return the current gameweek number, or None if between seasons."""
        events = self.get_events()
        current = events.loc[events["is_current"], "id"]
        return int(current.iloc[0]) if not current.empty else None

    def get_fixtures(self) -> pd.DataFrame:
        """
        Return all fixtures for the season with FDR ratings.
        """
        raw = self._get("fixtures/")
        df = pd.DataFrame(raw)
        cols = [c for c in FIXTURE_COLS if c in df.columns]
        return df[cols].copy()

    def get_player_history(self, player_id: int) -> pd.DataFrame:
        """
        Return gameweek-by-gameweek history for a single player.
        Returns an empty DataFrame if the player has no history yet.
        """
        raw = self._get(f"element-summary/{player_id}/")
        history = raw.get("history", [])
        if not history:
            return pd.DataFrame()

        df = pd.DataFrame(history)
        df["player_id"] = player_id
        cols = [c for c in GW_COLS if c in df.columns]
        df = df[cols].copy()
        df["value"] = df["value"] / 10
        return df

    def get_all_gameweeks(
        self,
        player_ids: list[int],
        log_every: int = 50,
    ) -> pd.DataFrame:
        """
        Fetch gameweek history for every player in player_ids.

        Parameters
        ----------
        player_ids : list[int]
            List of FPL player element IDs.
        log_every : int
            Log progress every N players.

        Returns
        -------
        pd.DataFrame
            One row per player per gameweek, ~23k rows for a full season.
        """
        records = []
        total = len(player_ids)

        for i, pid in enumerate(player_ids):
            try:
                df = self.get_player_history(pid)
                if not df.empty:
                    records.append(df)
            except requests.HTTPError as e:
                logger.warning(f"Skipped player {pid}: {e}")

            if i % log_every == 0:
                logger.info(f"  {i}/{total} players fetched...")

            time.sleep(self.delay)

        if not records:
            return pd.DataFrame()

        result = pd.concat(records, ignore_index=True)
        logger.info(f"Done. {len(result)} gameweek rows for {total} players.")
        return result
