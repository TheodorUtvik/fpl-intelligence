# FPL Intelligence

An end-to-end data science application for Fantasy Premier League.

Machine learning predicts player points using historical FPL and underlying stats (xG/xA from Understat). Those predictions feed into a Linear Programming optimizer that selects the best squad and recommends transfers under real FPL constraints. Results are surfaced through an interactive Dash dashboard.

---

## What it does

- **Collects data** from the FPL official API (points, minutes, ICT, fixtures) and Understat (xG, xA, shots, key passes)
- **Engineers features** from rolling windows, fixture difficulty, price trends, and underlying performance metrics — strictly without data leakage
- **Trains an XGBoost regressor** to predict next-gameweek points per player, validated with `TimeSeriesSplit`
- **Optimises squad selection** using Integer Linear Programming (PuLP) subject to FPL budget, position, and club constraints
- **Advises transfers** given a manager's current squad, available free transfers, and active chips
- **Explains predictions** with SHAP waterfall charts per player
- **Serves everything** through a multi-page Dash app with a pitch graphic, sortable tables, and player profiles

---

## Tech stack

| Layer | Tools |
|---|---|
| Data collection | FPL API, Understat, aiohttp, rapidfuzz |
| Processing | pandas, numpy, pyarrow |
| ML | XGBoost, scikit-learn, SHAP, Optuna |
| Optimisation | PuLP (ILP) |
| Dashboard | Dash, Plotly, dash-bootstrap-components, mplsoccer |
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
│   │   ├── fpl_client.py       # FPL API wrapper
│   │   └── understat_client.py # Understat async client
│   ├── features/
│   │   └── engineer.py         # Feature engineering pipeline
│   ├── models/
│   │   ├── predict.py          # XGBoost training and inference
│   │   └── optimize.py         # PuLP LP optimizer
│   └── utils.py
├── app/
│   ├── app.py                  # Dash app entry point
│   ├── assets/
│   │   └── style.css
│   ├── components/
│   │   ├── navbar.py
│   │   └── pitch.py            # Pitch graphic component
│   └── pages/
│       ├── home.py
│       ├── optimizer.py        # Squad optimizer page
│       ├── transfers.py        # Transfer advisor page
│       ├── top50.py            # Top performers table
│       └── player.py           # Player profile + SHAP
├── requirements.txt
└── README.md
```

---

## Setup

```bash
git clone https://github.com/theodorsjetnanutvik/fpl-intelligence.git
cd fpl-intelligence
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Roadmap

- [x] Phase 1 — Environment and project setup
- [x] Phase 2 — Data collection (FPL API + Understat)
- [ ] Phase 3 — Feature engineering
- [ ] Phase 4 — Modelling (XGBoost + SHAP)
- [ ] Phase 5 — Hyperparameter tuning (Optuna)
- [ ] Phase 6 — LP optimizer (PuLP)
- [ ] Phase 7 — Dash dashboard
- [ ] Phase 8 — Deployment (Render)
- [ ] Phase 9 — Backtesting

---

## Key learning outcomes

1. End-to-end ML pipeline with time-series validation
2. Real-world dataset joining with fuzzy name matching
3. Feature engineering without data leakage
4. XGBoost regression + SHAP explainability
5. Integer Linear Programming with PuLP
6. Combining prediction with optimisation
7. Dash callback architecture (transferable to React mental model)
8. Deploying a Python web app with Gunicorn on Render
9. Async Python for API data collection
