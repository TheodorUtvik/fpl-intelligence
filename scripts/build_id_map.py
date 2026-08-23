#!/usr/bin/env python3
"""
Build the FPL <-> Understat player ID map for the current season.

Extracted from notebooks/02_understat_collection.ipynb so it can run
headlessly in CI or on demand, rather than requiring a manual notebook
run every time the map needs refreshing (new signings, promoted clubs,
season rollover).

Strategy
--------
- Build a full name for each FPL player from first_name + second_name.
- Normalise both sides (strip accents, unescape HTML entities, fold
  hyphens/apostrophes to spaces) and fuzzy-match with rapidfuzz, taking
  the higher of token_set_ratio and partial_ratio.
- Score >= 85  -> auto-match
- Score 70-84  -> flag for manual review
- Score < 70   -> no_match (usually a non-EPL player Understat tracks
  that FPL doesn't carry, or vice versa)
- MANUAL_OVERRIDES resolves known hard cases (nicknames, one-name
  players, legal-name mismatches) outright, before fuzzy matching runs.

Usage
-----
    python scripts/build_id_map.py [--season 2026]

Requires data/raw/fpl_players.parquet and data/raw/understat_players.parquet
to already exist (fetch them first via check_and_fetch_fpl.py / the
Understat fetch step of check_and_run_full_pipeline.py).

Writes data/processed/player_id_map.parquet and prints a summary,
including the `review` rows that need a human decision — check those
before relying on the map for high-ownership players.
"""

import argparse
import asyncio
import html
import logging
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.understat_client import UnderstatClient  # noqa: E402
from src.utils import current_season_start_year  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAW       = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

# Format: {understat_name: fpl_full_name}. Covers cases fuzzy matching
# can't resolve on its own — one-name players, nicknames vs legal names,
# and names with apostrophes that don't survive normalisation cleanly.
MANUAL_OVERRIDES = {
    "Alisson":              "Alisson Becker",
    "Casemiro":             "Carlos Henrique Casimiro",
    "Richarlison":          "Richarlison de Andrade",
    "Evanilson":            "Francisco Evanilson de Lima Barbosa",
    "Joelinton":            "Joelinton Cassio Apolinario de Lira",
    "Estêvão":              "Estevao Almeida de Oliveira Goncalves",
    "Rodri":                "Rodrigo Hernandez Cascante",
    "Gabriel":              "Gabriel dos Santos Magalhaes",
    "Thiago":               "Thiago Silva",
    "Murillo":              "Murillo Costa dos Santos",
    "Reinildo":             "Reinildo Mandava",
    "Toti":                 "Toti Gomes",
    "Rayan":                "Rayan Vito Simplicio Rocha",
    "André":                "Andre Trindade da Costa Neto",
    "Ben White":            "Benjamin White",
    "Matthew Cash":         "Matty Cash",
    "Valentino Livramento": "Tino Livramento",
    "Max Kilman":           "Maximilian Kilman",
    "Bruno Fernandes":      "Bruno Borges Fernandes",
    "Destiny Udogie":       "Iyenoma Udogie",
    "Amad Diallo Traore":   "Amad Diallo",
    "Pape Sarr":            "Pape Matar Sarr",
    "Tomas Soucek":         "Tomas Soucek",
    "Pedro Neto":           "Pedro Lomba Neto",
    "Diogo Dalot":          "Diogo Dalot Teixeira",
    "Alejandro Garnacho":   "Alejandro Garnacho Ferreyra",
    "Rodrigo Muniz":        "Rodrigo Muniz Carvalho",
    "Jun'ai Byfield":       "Jun'ai Byfield",
    "Nico O'Reilly":        "Nico O Reilly",
    "Matt O'Riley":         "Matt O Riley",
    "Jake O'Brien":         "Jake O Brien",
    "Luke O'Nien":          "Luke O Nien",
}


def normalize_name(name: str) -> str:
    """Lowercase, remove accents, replace hyphens/apostrophes with spaces."""
    if not isinstance(name, str):
        return ""
    name = html.unescape(name)
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.replace("-", " ").replace("'", " ")
    return name.lower().strip()


def build_id_map(fpl_players: pd.DataFrame, understat_players: pd.DataFrame) -> pd.DataFrame:
    """
    Match each Understat player to an FPL player by name.

    Returns a DataFrame with one row per Understat player: understat_id,
    understat_name, fpl_id, fpl_name, match_score, match_status.
    """
    fpl = fpl_players.copy()
    fpl["full_name"] = fpl["first_name"] + " " + fpl["second_name"]

    fpl_names_raw   = fpl["full_name"].tolist()
    fpl_name_to_id  = dict(zip(fpl["full_name"], fpl["id"]))
    fpl_names_norm  = [normalize_name(n) for n in fpl_names_raw]
    fpl_norm_to_raw = dict(zip(fpl_names_norm, fpl_names_raw))

    def best_match(u_name: str):
        u_norm = normalize_name(u_name)
        m_set  = process.extractOne(u_norm, fpl_names_norm, scorer=fuzz.token_set_ratio)
        m_part = process.extractOne(u_norm, fpl_names_norm, scorer=fuzz.partial_ratio)
        if m_set[1] >= m_part[1]:
            best_norm, score = m_set[0], m_set[1]
        else:
            best_norm, score = m_part[0], m_part[1]
        raw_name = fpl_norm_to_raw.get(best_norm, best_norm)
        fpl_id   = fpl_name_to_id.get(raw_name)
        return raw_name, fpl_id, score

    records = []
    for _, row in understat_players.iterrows():
        u_name = row["player_name"]
        u_id   = int(row["id"])

        if u_name in MANUAL_OVERRIDES:
            fpl_name = MANUAL_OVERRIDES[u_name]
            fpl_id   = fpl_name_to_id.get(fpl_name)
            score    = 100
            status   = "manual"
        else:
            fpl_name, fpl_id, score = best_match(u_name)
            if score >= 85:
                status = "auto"
            elif score >= 70:
                status = "review"
            else:
                status = "no_match"

        records.append({
            "understat_id":   u_id,
            "understat_name": u_name,
            "fpl_id":         fpl_id,
            "fpl_name":       fpl_name,
            "match_score":    score,
            "match_status":   status,
        })

    return pd.DataFrame(records)


async def _fetch_understat_players(season: str) -> pd.DataFrame:
    async with UnderstatClient() as client:
        return await client.get_league_players(season=season)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season", default=None,
        help="Season start year, e.g. 2026 (default: derived from the FPL API)",
    )
    args = parser.parse_args()

    fpl_path = RAW / "fpl_players.parquet"
    if not fpl_path.exists():
        log.error(f"{fpl_path} not found. Run check_and_fetch_fpl.py first.")
        sys.exit(1)
    fpl_players = pd.read_parquet(fpl_path)

    if args.season:
        season = args.season
    else:
        from src.data.fpl_client import FPLClient
        season = current_season_start_year(FPLClient().get_events())
    log.info(f"Building ID map for season {season}...")

    us_path = RAW / "understat_players.parquet"
    if us_path.exists():
        log.info(f"Using cached {us_path}")
        understat_players = pd.read_parquet(us_path)
    else:
        log.info("Fetching Understat season totals...")
        understat_players = asyncio.run(_fetch_understat_players(season))
        RAW.mkdir(parents=True, exist_ok=True)
        understat_players.to_parquet(us_path, index=False)

    id_map = build_id_map(fpl_players, understat_players)

    counts = id_map["match_status"].value_counts()
    log.info("=== Matching results ===")
    for status in ["auto", "manual", "review", "no_match"]:
        log.info(f"  {status:10s}: {counts.get(status, 0)}")

    review = id_map[id_map["match_status"] == "review"]
    if not review.empty:
        log.warning(f"{len(review)} players need manual review — check before relying on the map:")
        for _, r in review.sort_values("match_score", ascending=False).iterrows():
            log.warning(f"    {r['understat_name']!r} -> {r['fpl_name']!r} (score {r['match_score']})")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED / "player_id_map.parquet"
    id_map.to_parquet(out_path, index=False)
    log.info(f"Saved {out_path} ({len(id_map)} rows).")


if __name__ == "__main__":
    main()
