# Prediction Data Integrity

This document defines how FPL Intelligence prevents leaking future or partial gameweek data into model training.

## Problem Summary

- Predictions for GW `N+1` are generated from feature rows at GW `N`.
- If training also uses GW `N` rows, their target (`pts_next_gw`) comes from GW `N+1` actual points.
- When GW `N+1` is still partial, those targets are incomplete/noisy and can bias the model.

## Integrity Rules

1. **Completion gate**  
   A GW is considered complete only if feature row count for that GW is `>= 650`.

2. **Prediction GW selection**  
   `latest_complete_gw = max(round with count >= 650)`  
   `predict_gw = latest_complete_gw + 1`

3. **Hard train/inference split (leakage guard)**  
   - Train only on `round < latest_complete_gw`
   - Predict only from rows where `round == latest_complete_gw`
   - Never train on the same round used for current inference

4. **One player = one row in app/optimizer pools**  
   Duplicate rows for the same `player_id` are collapsed to one latest-state row before squad optimization or page rendering.

5. **One player-round = one feature row**  
   Before rolling features/targets, merged rows are collapsed to exactly one row per (`player_id`, `round`).  
   This prevents fixture-join row multiplication from inflating targets or model weights.

6. **Target construction on canonical rows**  
   `pts_next_gw` is computed with `groupby(player_id).shift(-1)` on the canonical one-row-per-round feature table.

## Where This Is Enforced

- Leakage-safe training split:
  - `scripts/refresh_pipeline.py`
- Target generation safety:
  - `src/features/engineer.py`
- Player-round canonicalization safety:
  - `src/features/engineer.py`
- Player-level dedupe for app + optimizer:
  - `app/data_loader.py`
  - `src/models/optimize.py`

## Operational Notes

- Stage 1 can fetch FPL GW data as soon as FPL marks a GW as finished.
- Stage 2 waits 48 hours (Understat lag policy) before full rebuild by default.
- A manual full refresh can still be run with `python3 scripts/refresh_pipeline.py`.
- For code-only rebuilds without API calls, run `python3 scripts/rebuild_from_local_data.py`.
- After new artifacts are written, restart/redeploy Dash so cached loaders pick up updated files.
