# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app (dev)
python -m app.app                        # http://127.0.0.1:8050

# Run the full data + ML pipeline manually
python scripts/refresh_pipeline.py

# Production server
gunicorn app.app:server
```

No test suite, linter, or formatter is configured.

## Architecture Overview

This is a Fantasy Premier League analytics dashboard. There are two independent layers: a **data/ML pipeline** (run via scripts/CI) and a **Dash web app** (served at runtime).

### Data & ML Pipeline

Raw data flows through four stages, each producing Parquet artifacts:

```
FPL API + Understat API
  → data/raw/fpl_*.parquet + understat_*.parquet          (scripts/check_and_fetch_fpl.py)
  → data/processed/merged_players.parquet                 (name-matched via rapidfuzz)
  → data/processed/features.parquet                       (src/features/engineer.py)
  → models/xgboost_model.json + shap_explainer.pkl        (src/models/predict.py)
  → data/predictions/gw{N}.parquet                        (prediction snapshot per GW)
```

Key engineering rules in `src/features/engineer.py`: all rolling features use `.shift(1)` to prevent leakage. The target is `pts_next_gw` (`.shift(-1)` per player). GW1 rows and the final GW per player are dropped.

The XGBoost model and SHAP explainer are **lazy-imported** in `src/models/predict.py` to avoid slowing app startup.

CI runs both stages daily via `.github/workflows/refresh_fpl.yml` and `refresh_full.yml`, auto-committing artifacts when data or model changes.

### Dash App

**Entry point:** `app/app.py` — registers all pages (`use_pages=True`), builds the sidebar layout, and exposes `server` for Gunicorn.

**Cached data access:** `app/data_loader.py` is the single source of truth for all pages. Every heavy function (`load_features`, `get_predictor`, `get_players_with_predictions`, etc.) is wrapped in `@lru_cache(maxsize=1)` and computed once at startup. Pages import from here, never from `src/` directly.

**Pages** (`app/pages/`): `home`, `optimizer`, `transfers`, `top50`, `player`, `my_team`, `results`. Each calls `dash.register_page(__name__, path=...)`.

**SQLite persistence** (`app/db.py`, `app/team_manager.py`): team state is stored in `data/fpl.db` with three tables — `users`, `teams` (15 rows per user, `bench_order=NULL` means starter), `team_meta`. `DEFAULT_USER_ID = 123` (single-user mode). Schema is multi-user ready. Business logic lives in `team_manager.py`; `db.py` only handles schema init and the `get_conn()` context manager.

## My Team Page — Callback Architecture

`app/pages/my_team.py` has the most complex callback wiring. Key rules:

**Single writer per store.** `mt-selected` has exactly one server-side writer (`update_selected`). This avoids the Dash 4 bug where `allow_duplicate=True` callbacks writing `no_update` produce `dc[namespace][function_name] is not a function` errors in the browser.

**Relay pattern for clicks.** Clicking a player token fires a JS delegated event listener (not Dash's `n_clicks`). The listener sets `window._mtClickPid`. A `dcc.Interval` (150 ms) polls it and writes to `mt-click-relay`. The close button uses a separate `mt-close-relay`. The single `update_selected` server callback reads both relays and writes `mt-selected`.

**Dynamically rendered components fire callbacks on appearance.** When `render_pitch` adds components like `mt-reimport-btn` or `mt-undo-btn` to the DOM, Dash 4 fires their callbacks with `n_clicks=0` even with `prevent_initial_call=True`. Every callback whose Input component is dynamically rendered must guard with `if not n_clicks: return dash.no_update`.

**Stable pitch layout.** Starters are sorted by `(position_order, row_id)` where `row_id` is the DB `teams.id` column. This is stable across transfers because `apply_transfer` does an `UPDATE` (not DELETE+INSERT), preserving the row `id`. Never sort starters by `predicted_pts` — it causes the whole position row to reshuffle on every transfer.

**Undo stack.** `mt-undo-stack` is a list (most recent last). `confirm_transfer` pushes; `undo_last_transfer` pops. Each entry contains the full pre-transfer snapshot needed to reverse it (player IDs, prices, FT count, bank balance, pts delta).

## Squad Optimizer

`src/models/optimize.py` uses PuLP + CBC to solve a binary ILP: maximise predicted pts subject to budget (£100m), squad size (15), positional quotas (2 GKP / 5 DEF / 5 MID / 3 FWD), max 3 per club, and captain selection (captain counts 2×). Solves in under 1 second for ~400 players.

## Design System

All styling is in `app/assets/custom.css`. The file uses CSS custom properties (`--ink`, `--accent`, `--bg-elev`, etc.) with `[data-theme='dark']` overrides. Colours are in `oklch()`. Font stack: Inter (body), JetBrains Mono (`font-mono`), Instrument Serif (`font-serif`). Do not add inline styles for colours or typography — use the existing tokens.
