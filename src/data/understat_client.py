"""
Understat async client.

Wraps two Understat POST endpoints discovered via JS reverse-engineering:

  POST /main/getPlayersStats/          body: league=EPL&season=YYYY
    → season totals per player (xG, xA, shots, key_passes, etc.)

  POST /main/getPlayerMatches/{id}     no body required
    → match-by-match breakdown for one player across all seasons

Usage
-----
    import asyncio
    from src.data.understat_client import UnderstatClient

    # `season` is the season's start year (e.g. "2026" for 2026/27) — derive
    # it with src.utils.current_season_start_year() rather than hardcoding it.
    async def main(season: str):
        async with UnderstatClient() as client:
            players_df = await client.get_league_players(season=season)
            matches_df = await client.get_all_player_matches(
                players_df["id"].tolist(), season_filter=season
            )

    asyncio.run(main("2026"))
"""

import asyncio
import logging
import ssl
from typing import Optional

import aiohttp
import certifi
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://understat.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

# Columns to keep from season totals
PLAYER_COLS = [
    "id", "player_name",
    "games", "time",
    "goals", "xG",
    "assists", "xA",
    "shots", "key_passes",
    "npg", "npxG",
    "xGChain", "xGBuildup",
    "yellow_cards", "red_cards",
    "position", "team_title",
]

# Columns to keep from per-match history
MATCH_COLS = [
    "understat_id",   # added programmatically
    "date", "season",
    "h_team", "a_team",
    "h_goals", "a_goals",
    "goals", "xG",
    "assists", "xA",
    "shots", "key_passes",
    "npg", "npxG",
    "xGChain", "xGBuildup",
    "time",       # minutes played
    "position",
]


class UnderstatClient:
    """
    Async context manager wrapping the two Understat data endpoints.

    Parameters
    ----------
    concurrency : int
        Max simultaneous requests for the per-player match fetch loop.
    request_delay : float
        Seconds to sleep between individual requests (per worker).
    """

    def __init__(self, concurrency: int = 10, request_delay: float = 0.1):
        self.concurrency = concurrency
        self.delay = request_delay
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self):
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        self._session = aiohttp.ClientSession(connector=connector, headers=HEADERS)
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, data: Optional[dict] = None) -> dict:
        """POST with retry logic (up to 3 attempts, exponential backoff: 1s, 2s)."""
        url = f"{BASE_URL}/{path}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with self._session.post(url, data=data) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            except aiohttp.ClientError:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(
                    f"Request to {path} failed, retrying in {wait_time}s... "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_league_players(self, season: str) -> pd.DataFrame:
        """
        Return season totals for all EPL players.

        Parameters
        ----------
        season : str
            Season start year (e.g. "2025" for the 2025/26 season).

        Returns
        -------
        pd.DataFrame
            One row per player. Key columns: id, player_name, xG, xA,
            shots, key_passes, team_title, position.
        """
        logger.info(f"Fetching EPL player stats for season {season}...")
        payload = {"league": "EPL", "season": season}
        data = await self._post("main/getPlayersStats/", data=payload)
        players = data.get("players", [])

        df = pd.DataFrame(players)
        cols = [c for c in PLAYER_COLS if c in df.columns]
        df = df[cols].copy()

        # Cast numeric strings to float
        for col in ["xG", "xA", "npxG", "xGChain", "xGBuildup"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(f"  {len(df)} players returned.")
        return df

    async def get_player_matches(self, understat_id: int | str) -> pd.DataFrame:
        """
        Return match-by-match stats for a single player, across all seasons
        Understat has data for. Callers typically filter to one season via
        `get_all_player_matches`'s `season_filter` parameter.

        Parameters
        ----------
        understat_id : int | str
            Understat's internal player ID (from get_league_players).

        Returns
        -------
        pd.DataFrame
            One row per match. Empty DataFrame if the player has no data.
        """
        data = await self._post(f"main/getPlayerMatches/{understat_id}")
        matches = data.get("response", {}).get("matches", [])

        if not matches:
            return pd.DataFrame()

        df = pd.DataFrame(matches)
        df["understat_id"] = str(understat_id)
        cols = [c for c in MATCH_COLS if c in df.columns]
        df = df[cols].copy()

        # Cast numeric columns
        for col in ["goals", "xG", "assists", "xA", "shots", "key_passes",
                    "npg", "npxG", "xGChain", "xGBuildup", "time"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df

    async def get_all_player_matches(
        self,
        understat_ids: list,
        season_filter: str,
        log_every: int = 50,
    ) -> pd.DataFrame:
        """
        Fetch match-by-match stats for all players concurrently.

        Parameters
        ----------
        understat_ids : list
            List of Understat player IDs (strings or ints).
        season_filter : str
            Keep only matches from this season year (e.g. "2025").
        log_every : int
            Log progress every N players.

        Returns
        -------
        pd.DataFrame
            One row per player per match, filtered to season_filter.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        results = []
        total = len(understat_ids)

        async def fetch_one(pid, index):
            async with semaphore:
                try:
                    df = await self.get_player_matches(pid)
                    if not df.empty and season_filter:
                        df = df[df["season"] == season_filter]
                    await asyncio.sleep(self.delay)
                    return df
                except Exception as e:
                    logger.warning(f"  Skipped player {pid}: {e}")
                    return pd.DataFrame()

        tasks = [fetch_one(pid, i) for i, pid in enumerate(understat_ids)]

        for i, coro in enumerate(asyncio.as_completed(tasks)):
            df = await coro
            if not df.empty:
                results.append(df)
            if i % log_every == 0:
                logger.info(f"  {i}/{total} players fetched...")

        if not results:
            return pd.DataFrame()

        combined = pd.concat(results, ignore_index=True)
        logger.info(f"Done. {len(combined)} match rows for {total} players.")
        return combined
