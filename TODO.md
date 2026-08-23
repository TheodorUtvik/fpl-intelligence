# FPL Intelligence — TODO

Items deferred from active development. Kept here so nothing gets lost.

---

## ✅ Done: xG coverage-based Understat trigger (alternative to 48h delay)

Implemented as `src/utils.understat_ready_for_gw()`, used by
`scripts/check_and_run_full_pipeline.py`. Checks raw Understat match row
count (scaled to the GW's actual fixture count, so blank/double GWs don't
need a special case) rather than xG coverage. The 48h delay is now a
floor, not the whole gate — readiness is checked after it, with a 96h
hard deadline that proceeds anyway rather than stalling forever. Retry
is free: if not ready, `full_pipeline_gw` just doesn't advance, so the
next scheduled run retries automatically with no extra flag file needed.

---

## Creative automations (not yet implemented)

### 1. Pre-deadline captain/transfer digest email

Fire **Friday ~18:00 UTC** (before Saturday deadlines) via GitHub Actions.

Script would:
- Pull top 5 captain picks with predicted pts from the current prediction snapshot
- Pull top 3 single-transfer recommendations for a configurable squad
- Format into a plain-text or HTML email
- Send via a free transactional email service (Resend, Mailgun, SendGrid free tier)

Config needed: recipient email address stored as a GitHub secret.

Stretch: make it configurable per team — pass your squad IDs in a config file and get
personalised transfer suggestions.

### 2. Automatic GW review report committed to repo

Fire Monday morning after Stage 1 FPL fetch (actual GW points now available).

Script would replicate the logic in `notebooks/07_gw_review.ipynb` as a standalone
Python script:
- Load GW N predictions (from `data/predictions/gwN.parquet`)
- Load actual GW N points (from fresh `fpl_gameweeks.parquet`)
- Compute MAE, within-2pts %, Pearson r
- Write `reports/gw{N}_review.json` with summary stats
- Optionally write a `reports/gw{N}_review.md` human-readable summary

Builds up a season-long record of model performance, browsable on GitHub.

### 3. Player status / injury alert

Fire **daily 09:00 UTC** via a lightweight GitHub Actions workflow (~2 min).

Script would:
- Fetch FPL bootstrap `elements[]` → check `status` field (a=available, d=doubtful, i=injured)
- Compare against previous day's status (stored in `data/player_status_cache.json`)
- If any top-50 predicted player changed status → send email alert or post GitHub issue

Most useful mid-week when injury news breaks before the transfer deadline.

### 4. Price change monitoring

FPL player prices change overnight based on ownership. Fire **daily 08:00 UTC**.

Script would:
- Fetch current `now_cost` from FPL bootstrap
- Compare against cached prices from previous day
- Alert on price rises/falls for players above a predicted_pts threshold

Useful for transfer timing — buy a player before their price rises.

---

## Feature improvements (model)

- **Opponent defensive strength** — rolling goals conceded (home/away split) as a feature.
  Partially implemented in `FeatureEngineer._fixture_features()` via `opp_goals_conceded_avg`
  but could be split into home/away versions.

- **Player availability** — `chance_of_playing_next_round` from FPL API as a feature.
  FPL exposes this as a percentage (0, 25, 50, 75, 100). Currently only `status` (a/d/i)
  is used as a filter, not as a model feature.

- **Expand Understat id_map** — re-run `notebooks/02_understat_collection.ipynb` at the
  start of each season to pick up new signings and extend xG coverage beyond the current
  ~65-70% theoretical maximum.

---

## App improvements

- **Budget slider on Optimizer page** — allow users to set a budget below £100m.
  Currently hardcoded. ILP already supports a `budget` parameter.

- **Bench boost / free hit chip support** — Optimizer could have a chip selector
  that adjusts constraints (e.g. bench boost scores all 15 players).

- **Deployment on Render** — Phase 8. App is Gunicorn-ready (`server = app.server`
  in `app/app.py`, `Procfile` exists). Needs environment variable config for paths.
