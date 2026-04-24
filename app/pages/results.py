"""
GW Results page.
Shows predicted vs actual points for the current GW and the previous 3,
so you can track how well the model performed week by week.
"""

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import html
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.data_loader import (
    get_latest_gw,
    get_predictor,
    load_features,
    load_teams,
)

dash.register_page(__name__, path="/results", name="GW Results")

INK    = "#14130f"
INK_3  = "#6e6c64"
ACCENT = "#3d7a52"
GOOD   = "#3d7452"
BAD    = "#b5553a"

RAW = ROOT / "data" / "raw"


# ── Data helpers ──────────────────────────────────────────────────────────────

def _build_comparison(predict_from_gw: int, actual_gw: int) -> pd.DataFrame:
    features  = load_features()
    predictor = get_predictor()
    teams = load_teams()[["id", "short_name"]].rename(
        columns={"id": "team", "short_name": "team_name"}
    )

    snap = features[features["round"] == predict_from_gw].copy()
    if snap.empty:
        return pd.DataFrame()

    snap["predicted_pts"] = predictor.predict(snap)

    gw_path = RAW / "fpl_gameweeks.parquet"
    if not gw_path.exists():
        return pd.DataFrame()

    actuals = pd.read_parquet(gw_path)
    actuals = actuals[actuals["round"] == actual_gw][["player_id", "total_points", "minutes"]]
    actuals = actuals.rename(columns={"total_points": "actual_pts"})

    df = snap.merge(actuals, on="player_id", how="inner")
    df = df.merge(teams, on="team", how="left")
    df = df.sort_values("predicted_pts", ascending=False).drop_duplicates("player_id")
    df["diff"] = df["actual_pts"] - df["predicted_pts"]
    df = df[df["minutes"] > 0]

    keep = ["player_id", "web_name", "position", "team_name",
            "predicted_pts", "actual_pts", "diff", "minutes"]
    return df[keep].sort_values("predicted_pts", ascending=False).reset_index(drop=True)


def _summary_kpis(df: pd.DataFrame) -> html.Div:
    if df.empty:
        return html.Div()

    mae      = df["diff"].abs().mean()
    within2  = (df["diff"].abs() <= 2).mean() * 100
    best_idx = df["diff"].abs().idxmin()
    miss_idx = df["diff"].abs().idxmax()
    best     = df.loc[best_idx]
    miss     = df.loc[miss_idx]

    return html.Div([
        html.Div([
            html.Div("MAE (holdout)", className="kpi-label"),
            html.Div([f"{mae:.2f}", html.Span("pts", className="unit")],
                     className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Within 2 pts", className="kpi-label"),
            html.Div([f"{within2:.0f}", html.Span("%", className="unit")],
                     className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Best call", className="kpi-label"),
            html.Div(best["web_name"], className="kpi-value serif-val"),
            html.Div(
                [html.Span(f"{best['diff']:+.1f} pts", className="up mono")],
                className="kpi-delta",
            ),
        ], className="kpi"),
        html.Div([
            html.Div("Biggest miss", className="kpi-label"),
            html.Div(miss["web_name"], className="kpi-value serif-val"),
            html.Div(
                [html.Span(f"{miss['diff']:+.1f} pts", className="down mono")],
                className="kpi-delta",
            ),
        ], className="kpi"),
    ], className="kpi-grid")


def _results_table(df: pd.DataFrame) -> html.Table:
    rows = []
    for i, (_, row) in enumerate(df.head(30).iterrows(), 1):
        diff     = row["diff"]
        diff_cls = "diff-good" if diff > 0 else ("diff-bad" if diff < -1 else "diff-mid")
        pos      = row["position"]

        rows.append(html.Tr([
            html.Td(i, className="mono rank-num"),
            html.Td(
                html.A(
                    row["web_name"],
                    href=f"/player/{int(row['player_id'])}",
                    style={"fontWeight": 500, "textDecoration": "none", "color": INK},
                )
            ),
            html.Td(html.Span(pos, className=f"pos-pill pos-{pos}")),
            html.Td(row.get("team_name", ""), style={"color": INK_3}),
            html.Td(f'{row["predicted_pts"]:.2f}', className="right mono",
                    style={"color": ACCENT}),
            html.Td(f'{row["actual_pts"]:.0f}', className="right mono",
                    style={"fontWeight": 600}),
            html.Td(f'{diff:+.2f}', className=f"right mono {diff_cls}"),
        ]))

    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"),
                html.Th("Player"),
                html.Th("Pos"),
                html.Th("Club"),
                html.Th("Predicted",  className="right"),
                html.Th("Actual",     className="right"),
                html.Th("Diff",       className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )


def _tab_content(predict_from_gw: int, actual_gw: int) -> html.Div:
    df = _build_comparison(predict_from_gw, actual_gw)

    if df.empty:
        return html.Div(
            dbc.Alert(f"No data available for GW {actual_gw}.", color="secondary"),
            style={"paddingTop": "16px"},
        )

    return html.Div([
        _summary_kpis(df),
        html.P(
            f"{len(df)} players who played  ·  sorted by predicted pts (top 30 shown)",
            style={"fontFamily": "var(--font-mono)", "fontSize": "10px",
                   "color": "var(--ink-3)", "marginBottom": "12px",
                   "letterSpacing": "0.04em"},
        ),
        html.Div([
            html.Div([
                html.Div(f"GW {actual_gw} — predicted vs actual", className="card-title"),
                html.Span(f"model trained on GW {predict_from_gw}", className="tag"),
            ], className="card-hd"),
            html.Div(_results_table(df), className="card-body flush"),
        ], className="card"),
    ])


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    latest_gw  = get_latest_gw()
    predict_gw = latest_gw + 1

    gw_pairs = [
        (predict_gw - 1 - i, predict_gw - i)
        for i in range(4)
    ]

    tabs = []
    for i, (from_gw, actual_gw) in enumerate(gw_pairs):
        label = f"GW {actual_gw}" + (" ← current" if i == 0 else "")
        tabs.append(dbc.Tab(
            _tab_content(from_gw, actual_gw),
            label=label,
            tab_id=f"tab-{actual_gw}",
        ))

    return html.Div([

        # ── Page header ──────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("History · GW Results", className="page-eyebrow"),
                html.H1("Model performance", className="page-title serif"),
                html.P(
                    "Predicted vs actual points — track how the XGBoost model performed "
                    "each week. Green diff = player outscored prediction.",
                    className="page-desc",
                ),
            ]),
        ], className="page-head"),

        # ── Tabs ─────────────────────────────────────────────
        dbc.Tabs(tabs, active_tab=f"tab-{predict_gw}"),

    ], className="page")
