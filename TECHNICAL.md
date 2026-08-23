# Technical Documentation

Deep-dive on the architecture, data pipeline, modelling decisions, and optimiser formulation.

---

## Table of contents

1. [Data sources](#1-data-sources)
2. [Data collection](#2-data-collection)
3. [Feature engineering](#3-feature-engineering)
4. [Machine learning model](#4-machine-learning-model)
5. [Hyperparameter tuning](#5-hyperparameter-tuning)
6. [LP optimiser](#6-lp-optimiser)
7. [Dashboard architecture](#7-dashboard-architecture)
8. [Known limitations](#8-known-limitations)

---

## 1. Data sources

### FPL API (unofficial)

The FPL API is an unauthenticated REST API served by the Premier League. No API key is required.

| Endpoint | Data |
|---|---|
| `/api/bootstrap-static/` | All players, teams, gameweek metadata, ICT index, ownership |
| `/api/fixtures/` | All fixtures with FDR ratings |
| `/api/element-summary/{id}/` | Per-player gameweek-by-gameweek history |

Player prices are returned as integers (e.g. `65` = £6.5m). All prices are divided by 10 in the data pipeline.

### Understat

Understat provides expected goals (xG) and expected assists (xA) modelled from shot quality. Their public site is a JavaScript SPA — there is no officially documented API.

The POST API was reverse-engineered by inspecting the `player.min.js` bundle, which revealed two endpoints:

| Endpoint | Method | Parameters |
|---|---|---|
| `/main/getPlayersStats/` | POST | `league=EPL&season=YYYY` (season start year, derived via `src/utils.current_season_start_year()`) |
| `/main/getPlayerMatches/{id}` | POST | (no body required) |

The async client (`src/data/understat_client.py`) uses `aiohttp` with `asyncio.Semaphore(10)` for concurrency control and SSL certificates from `certifi` (required on macOS Python 3.12 which does not trust system certificates for aiohttp connections).

### Name matching (FPL ↔ Understat)

FPL uses short display names (`"Salah"`, `"Trent"`) while Understat uses full legal names (`"Mohamed Salah"`, `"Trent Alexander-Arnold"`). Exact string matching is not possible.

**Matching strategy:**

1. Normalise both name sets: strip accents (NFD decomposition), decode HTML entities, replace hyphens and apostrophes with spaces, lowercase
2. Apply `rapidfuzz.fuzz.token_set_ratio` — handles subset matching (e.g. `"alisson"` matches `"alisson becker"` at 100%)
3. Apply `rapidfuzz.fuzz.partial_ratio` as a fallback
4. Take the higher score from the two scorers
5. Score ≥ 85 → auto-match; 70–84 → manual review; < 70 → no match
6. ~25 known hard cases have manual overrides (e.g. `"Rodri"` → `"Rodrigo Hernandez Cascante"`, `"Ben White"` → `"Benjamin White"`)

This achieves ~70% xG coverage for players with recorded minutes, up from 25% with a simple threshold-only approach.

---

## 2. Data collection

### FPL client (`src/data/fpl_client.py`)

```
FPLClient
├── get_players()         → bootstrap players list
├── get_teams()           → team metadata
├── get_events()          → gameweek deadlines
├── get_current_gameweek()
├── get_fixtures()        → all season fixtures with FDR
└── get_all_gameweeks()   → per-player GW history (parallel requests)
```

The bootstrap response is cached on the instance to avoid re-fetching for multiple calls within a session.

### Understat client (`src/data/understat_client.py`)

```
UnderstatClient (async context manager)
├── get_league_players(season)         → season totals for all EPL players
├── get_player_matches(understat_id)   → match-by-match xG/xA
└── get_all_player_matches(ids)        → concurrent fetch with semaphore
```

### Saved files

All data is saved as Parquet via pyarrow for efficient columnar storage.

| File | Location | Rows | Description |
|---|---|---|---|
| `fpl_players.parquet` | `data/raw/` | 825 | Player metadata and season totals |
| `fpl_gameweeks.parquet` | `data/raw/` | ~24k | Per-player per-GW history |
| `fpl_fixtures.parquet` | `data/raw/` | 380 | All season fixtures |
| `fpl_teams.parquet` | `data/raw/` | 20 | Team metadata |
| `understat_players.parquet` | `data/raw/` | 521 | Understat season totals |
| `understat_matches.parquet` | `data/raw/` | ~10k | Match-by-match xG/xA |
| `player_id_map.parquet` | `data/processed/` | 521 | FPL ↔ Understat ID mapping |
| `merged_players.parquet` | `data/processed/` | ~24k | Merged FPL + Understat |
| `features.parquet` | `data/processed/` | ~22k | Final feature matrix |

---

## 3. Feature engineering

All features are engineered in `src/features/engineer.py` with a strict **no-leakage rule**: every rolling window uses `.shift(1).rolling(window)` to ensure only past gameweeks inform each row. The target variable (`pts_next_gw`) is also shifted forward.

### Feature groups

**Form features** (rolling averages over 3 and 5 GWs)
- `rolling_pts_3gw`, `rolling_pts_5gw`
- `rolling_minutes_3gw`, `rolling_minutes_5gw`
- `minutes_consistency` — std dev of minutes (rotation risk proxy)
- `blank_gw_flag` — 1 if predicted minutes ≈ 0
- `form_streak` — consecutive GWs above rolling average

**Underlying performance (xG/xA)**
- `rolling_xg_3gw`, `rolling_xg_5gw`
- `rolling_xa_3gw`, `rolling_xa_5gw`
- `xg_overperformance` — actual goals minus xG (finishing luck)
- `shots_per_90`, `key_passes_per_90`

**Fixture features**
- `fdr_next` — FPL fixture difficulty rating for next GW (1=easy, 5=hard)
- `fdr_next3` — average FDR over next 3 GWs
- `is_home_next` — 1 if home fixture next GW
- `opp_goals_conceded_avg` — opponent's rolling goals conceded (5 GW)
- `has_fixture` — 1 if the player has a fixture scheduled

**Value and ownership**
- `value` — current price in £m
- `price_change_3gw` — price change over last 3 GWs
- `pts_per_million` — rolling pts / price (value metric)
- `ownership_pct` — % of FPL managers owning the player
- `ownership_change_3gw` — ownership delta (momentum indicator)
- `is_differential` — 1 if ownership < 5%

**Positional dummies**
- `is_gkp`, `is_def`, `is_mid`, `is_fwd`

### Target

`pts_next_gw` — actual FPL points scored in the following gameweek. Computed with `.shift(-1)` per player, with the final GW dropped (no future data available).

### Validation

After engineering, the feature matrix is validated for:
- Zero null values (any remaining nulls fail the pipeline)
- No rows from GW1 (insufficient rolling history)
- Correct row count against the merged dataset

---

## 4. Machine learning model

### Model selection

Three models were benchmarked on a time-based train/test split (GW2–26 train, GW27–30 test):

| Model | MAE | R² |
|---|---|---|
| Naive baseline (rolling 3GW avg) | 1.004 | 0.159 |
| Linear Regression | ~1.00 | ~0.15 |
| Random Forest | 1.001 | ~0.30 |
| **XGBoost (default)** | **0.752** | **0.612** |

XGBoost was selected for its 25% improvement over the naive baseline and strong handling of tabular data with mixed feature types.

### Cross-validation

`TimeSeriesSplit(n_splits=5)` is used throughout. Data is **never shuffled** — FPL points are a time series and shuffling would cause future data to leak into training folds.

### SHAP explainability

A `TreeExplainer` is fitted on the training set and saved alongside the model. Top features by mean absolute SHAP value:

1. `blank_gw_flag` — strongest signal; players with no fixture score ~0
2. `rolling_minutes_3gw` — recent playing time predicts future playing time
3. `ownership_pct` — highly owned players tend to be the consistent scorers
4. `rolling_pts_3gw` — recent form
5. `rolling_xg_3gw` — underlying chance creation

### Saved artefacts

| File | Description |
|---|---|
| `models/xgboost_model.json` | Trained XGBoost model |
| `models/shap_explainer.pkl` | TreeExplainer fitted on training data |
| `models/feature_cols.json` | Ordered list of feature column names |
| `models/best_params.json` | Hyperparameters used at inference time |

---

## 5. Hyperparameter tuning

Optuna with a TPE sampler was run for 100 trials minimising MAE on `TimeSeriesSplit` CV. The tuned model performed **worse** (MAE 0.96) than the XGBoost defaults (MAE 0.75).

**Diagnosis:** Optuna found a degenerate shallow model (`n_estimators=101`, `max_depth=3`, `min_child_weight=17`) that was overfitting the CV folds. With only one season of data (~22k rows, ~30 distinct gameweeks), the CV folds are small enough that Bayesian optimisation over-tunes to noise.

**Resolution:** `best_params.json` was manually restored to XGBoost defaults (`n_estimators=400`, `max_depth=5`, `learning_rate=0.05`). The tuning notebook is preserved for reference.

---

## 6. LP optimiser

The optimiser (`src/models/optimize.py`) formulates squad selection as an Integer Linear Programme solved by the CBC solver via PuLP.

### Decision variables

- `x[p] ∈ {0, 1}` — player p is in the squad
- `c[p] ∈ {0, 1}` — player p is captain

### Objective

Maximise predicted points, with captain counting double:

```
max Σ predicted_pts[p] * x[p] + Σ predicted_pts[p] * c[p]
```

### Constraints (full squad)

```
Σ now_cost[p] * x[p]  ≤  100.0              (budget)
Σ x[p]                = 15                  (squad size)
Σ x[p] for GKP        = 2
Σ x[p] for DEF        = 5
Σ x[p] for MID        = 5
Σ x[p] for FWD        = 3
Σ x[p] for team t     ≤ 3  ∀ t             (club limit)
Σ c[p]                = 1                  (one captain)
c[p]                  ≤ x[p]  ∀ p          (captain must be in squad)
```

### Starting XI variant

`select_starting_xi()` uses the same formulation with modified constraints:

```
Σ x[p]           = 11
Σ x[p] for GKP   = 1
Σ x[p] for DEF   ∈ [3, 5]
Σ x[p] for MID   ∈ [2, 5]
Σ x[p] for FWD   ∈ [1, 3]
```

The formation string (e.g. `"4-3-3"`) is derived from the DEF/MID/FWD counts of the solution.

### Transfer advisor

`recommend_transfers()` evaluates all valid 1- and 2-player swaps from the current squad:

- Swaps must be position-neutral (DEF for DEF, etc.)
- Cost of incoming player(s) ≤ sell price of outgoing + bank
- Resulting squad must not exceed 3 players from any club
- Hit = max(0, n_transfers − free_transfers) × 4
- Net gain = (pts_in − pts_out) − hit

Results are sorted by net gain descending.

---

## 7. Dashboard architecture

### Multi-page Dash

The app uses `dash.register_page()` (Dash 2.x multi-page pattern). All pages are auto-discovered from `app/pages/`. Page routing is handled by `dash.page_container` in `app/app.py`.

### Data loading

`app/data_loader.py` uses `functools.lru_cache(maxsize=1)` to load parquet files and run model inference once at startup. All pages call these cached functions — no re-reading on every callback.

### Pages

| Route | File | Description |
|---|---|---|
| `/` | `home.py` | KPI cards, top 10 table, position breakdown, value chart |
| `/optimizer` | `optimizer.py` | ILP solver callback, Plotly pitch visual, squad table |
| `/top50` | `top50.py` | Sortable leaderboard, position filter, player links |
| `/transfers` | `transfers.py` | Free-text squad input, fuzzy match to IDs, transfer table |
| `/player/<id>` | `player.py` | Form chart, xG/xA trend, SHAP waterfall |

### Pitch visualisation

The pitch is rendered as a Plotly `go.Figure` with:
- `go.Scatter` markers for player dots (colour-coded by position)
- `fig.add_shape` for pitch outline, halfway line, centre circle
- `fig.add_annotation` for name labels and team/pts below each dot
- Row x-positions spaced proportionally to match the FPL app layout

### Callbacks

All heavy callbacks (optimizer, transfer advisor) are wrapped in `dcc.Loading` to show a spinner. The ILP solver runs synchronously in the callback — CBC solves a 400-player problem in under 1 second.

---

## 8. Known limitations

| Limitation | Impact | Planned fix |
|---|---|---|
| Single season of data | XGBoost generalises to one season's patterns only | N/A — multi-season data risks stale player form |
| xG coverage ~70% | ~30% of players have zero xG features | Improve name matching or supplement with alternative source |
| No opponent defensive strength feature | Missing a key factor for fixture difficulty | Add rolling goals conceded per opponent, home/away split |
| `chance_of_playing_next_round` not used | Rotation risk not captured beyond minutes consistency | Add as a feature in `engineer.py` |
| Transfer advisor runs all combinations | O(n²) for 2-transfer suggestions, can be slow with large pools | Cap pool size or add position pre-filtering |
| No live data refresh | Dashboard shows the latest collected GW, not live | Add a refresh button that re-runs notebooks 01–03 |
