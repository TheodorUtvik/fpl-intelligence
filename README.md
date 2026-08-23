# FPL Intelligence

[![CI](https://github.com/TheodorUtvik/fpl-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/TheodorUtvik/fpl-intelligence/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)

An end-to-end data science application for Fantasy Premier League.

Machine learning predicts player points using historical FPL and underlying stats (xG/xA from Understat). Those predictions feed into a Linear Programming optimizer that selects the best squad and recommends transfers under real FPL constraints. Results are surfaced through an interactive Dash dashboard.

---

## What it does

- **Collects data** from the FPL unofficial API (points, minutes, ICT, fixtures) and Understat (xG, xA, shots, key passes) using an async aiohttp client
- **Engineers features** from rolling windows, fixture difficulty, price trends, and underlying performance metrics — strictly without data leakage
- **Trains an XGBoost regressor** to predict next-gameweek points per player, validated with `TimeSeriesSplit` (MAE 0.75, R² 0.61)
- **Optimises squad selection** using Integer Linear Programming (PuLP/CBC) subject to FPL budget, position, and club constraints
- **Advises transfers** given a manager's current squad, available free transfers, and bank
- **Explains predictions** with SHAP waterfall charts per player
- **Serves everything** through a multi-page Dash app with a pitch graphic, sortable tables, and player profiles

---

## Tech stack

| Layer | Tools |
|---|---|
| Data collection | FPL API, Understat, aiohttp, rapidfuzz |
| Processing | pandas, numpy, pyarrow |
| ML | XGBoost, scikit-learn, SHAP, Optuna |
| Optimisation | PuLP (CBC solver) |
| Dashboard | Dash, Plotly, dash-bootstrap-components |
| Deployment | Gunicorn, Render |

---

## Project structure

```
fpl-intelligence/
├── data/
│   ├── raw/                    # Parquet files from FPL API and Understat
│   └── processed/              # Merged and feature-engineered datasets
├── notebooks/
│   ├── 01_fpl_data_collection.ipynb
│   ├── 02_understat_collection.ipynb
│   ├── 03_feature_engineering.ipynb
│   ├── 04_modelling.ipynb
│   ├── 05_optimizer.ipynb
│   └── 06_hyperparameter_tuning.ipynb
├── src/
│   ├── data/
│   │   ├── fpl_client.py       # FPL API async wrapper
│   │   └── understat_client.py # Understat async client (reverse-engineered POST API)
│   ├── features/
│   │   └── engineer.py         # Feature engineering pipeline
│   └── models/
│       ├── predict.py          # XGBoost training and inference
│       └── optimize.py         # PuLP ILP squad optimizer + transfer advisor
├── app/
│   ├── app.py                  # Dash app entry point (Flask server exposed for Gunicorn)
│   ├── data_loader.py          # Cached data loading shared across pages
│   ├── assets/
│   │   └── style.css
│   ├── components/
│   │   └── navbar.py
│   └── pages/
│       ├── home.py             # Dashboard overview with KPIs and charts
│       ├── optimizer.py        # Squad optimizer with pitch visual
│       ├── transfers.py        # Transfer advisor with free-text squad input
│       ├── top50.py            # Sortable leaderboard with player links
│       └── player.py           # Player profile with form, xG/xA and SHAP charts
├── models/                     # Saved model artefacts (gitignored)
├── Procfile                    # Gunicorn entry point for Render
├── requirements.txt
└── README.md
```

---

## Setup

```bash
git clone https://github.com/TheodorUtvik/fpl-intelligence.git
cd fpl-intelligence
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Run the notebooks in order

```
notebooks/01 → 02 → 03 → 04 → 05 → 06
```

Each notebook saves its outputs as parquet files consumed by the next. The model artefacts (`xgboost_model.json`, `shap_explainer.pkl`, `feature_cols.json`) are saved to `models/`.

### Run the dashboard

```bash
python -m app.app
# Open http://127.0.0.1:8050
```

### Run the tests

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

---

## Model performance

| Metric | Value |
|---|---|
| Model | XGBoost regressor |
| MAE (test set, GW27–30) | **0.75 pts** |
| R² (test set) | **0.61** |
| Baseline MAE (rolling 3GW avg) | 1.00 pts |
| Improvement vs baseline | **25%** |
| xG coverage (players with minutes) | ~70% |

The test set uses a strict time-based holdout (future gameweeks never seen during training) via `TimeSeriesSplit`.

---

## Optimizer constraints

The ILP selects a squad satisfying:
- Budget ≤ £100m
- Exactly 2 GKP, 5 DEF, 5 MID, 3 FWD (full squad) — or valid formation for starting XI
- Maximum 3 players per club
- Captain selected as highest predicted scorer

---

## Roadmap

- [x] Phase 1 — Environment and project setup
- [x] Phase 2 — Data collection (FPL API + Understat)
- [x] Phase 3 — Feature engineering
- [x] Phase 4 — Modelling (XGBoost + SHAP)
- [x] Phase 5 — Hyperparameter tuning (Optuna)
- [x] Phase 6 — LP optimizer (PuLP)
- [x] Phase 7 — Dash dashboard
- [ ] Phase 8 — Deployment (Render)
- [ ] Phase 9 — Backtesting

---

## Known limitations and future improvements

- Only one season of data (2024/25) — adding historical seasons could improve generalisation but risks stale player form
- xG coverage ~70% — some player names do not fuzzy-match between FPL and Understat
- Model does not account for opponent defensive strength (home/away) — planned feature
- Player availability probability (`chance_of_playing_next_round`) not yet used as a feature — planned
- Budget slider on optimizer not yet implemented
