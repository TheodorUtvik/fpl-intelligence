"""
GW Results page.
Shows predicted vs actual points for the current GW and the previous 3,
so you can track how well the model performed week by week.
"""

import sys
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.components.club_badge import render_club_badge
from app.data_loader import (
    get_calibration_season_options,
    get_latest_gw,
    get_predictor,
    get_season_calibration,
    load_features,
    load_teams,
)

dash.register_page(__name__, path="/results", name="GW Results")

INK    = "#14130f"
INK_3  = "#6e6c64"
ACCENT = "#3d7a52"
GOOD   = "#3d7452"
BAD    = "#b5553a"
RULE   = "#d6d1c2"

RAW = ROOT / "data" / "raw"


# ── Data helpers ──────────────────────────────────────────────────────────────

def _build_comparison(predict_from_gw: int, actual_gw: int) -> pd.DataFrame:
    features  = load_features()
    predictor = get_predictor()
    if features.empty or predictor is None:
        return pd.DataFrame()

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

    top20 = df.head(20).copy()
    mae      = df["diff"].abs().mean()
    within2  = (df["diff"].abs() <= 2).mean() * 100
    best_idx = top20["diff"].abs().idxmin()
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
            html.Div("Best call (top 20)", className="kpi-label"),
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
            html.Td(render_club_badge(row.get("team_name", "")), style={"color": INK_3}),
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
                html.Div(f"GW {actual_gw}: predicted vs actual", className="card-title"),
                html.Span(f"model trained on GW {predict_from_gw}", className="tag"),
            ], className="card-hd"),
            html.Div(_results_table(df), className="card-body flush"),
        ], className="card"),
    ])


# ── Season calibration ───────────────────────────────────────────────────────

def _calibration_kpis(df: pd.DataFrame) -> html.Div:
    mae     = df["diff"].abs().mean()
    within2 = (df["diff"].abs() <= 2).mean() * 100
    corr    = df["predicted_pts"].corr(df["actual_pts"])
    n_gws   = df["predict_gw"].nunique()

    return html.Div([
        html.Div([
            html.Div("MAE (all snapshots)", className="kpi-label"),
            html.Div([f"{mae:.2f}", html.Span("pts", className="unit")], className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Within 2 pts", className="kpi-label"),
            html.Div([f"{within2:.0f}", html.Span("%", className="unit")], className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Correlation (r)", className="kpi-label"),
            html.Div(f"{corr:.2f}" if corr == corr else "-", className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Gameweeks covered", className="kpi-label"),
            html.Div(str(n_gws), className="kpi-value mono"),
        ], className="kpi"),
    ], className="kpi-grid")


def _calibration_scatter(df: pd.DataFrame) -> go.Figure:
    lo = min(df["predicted_pts"].min(), df["actual_pts"].min(), 0)
    hi = max(df["predicted_pts"].max(), df["actual_pts"].max())

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["predicted_pts"], y=df["actual_pts"], mode="markers",
        marker=dict(color=ACCENT, size=6, opacity=0.45),
        hovertext=df.get("web_name"), hoverinfo="text+x+y",
        name="Player-gameweeks",
    ))
    fig.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines",
        line=dict(color=INK_3, dash="dash", width=1),
        name="Perfect prediction", hoverinfo="skip",
    ))
    fig.update_layout(
        height=340, margin=dict(l=40, r=20, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(title="Predicted pts", gridcolor=RULE, zeroline=False),
        yaxis=dict(title="Actual pts", gridcolor=RULE, zeroline=False),
        font=dict(color=INK_3, size=11),
    )
    return fig


def _calibration_mae_by_gw(df: pd.DataFrame) -> go.Figure:
    per_gw = df.groupby("predict_gw")["diff"].apply(lambda s: s.abs().mean()).sort_index()
    fig = go.Figure(go.Bar(
        x=[f"GW{g}" for g in per_gw.index], y=per_gw.values,
        marker_color=ACCENT,
    ))
    fig.update_layout(
        height=260, margin=dict(l=40, r=20, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor=RULE), yaxis=dict(title="MAE (pts)", gridcolor=RULE, zeroline=False),
        font=dict(color=INK_3, size=11),
    )
    return fig


def _worst_misses_table(df: pd.DataFrame, n: int = 15) -> html.Table:
    worst = df.reindex(df["diff"].abs().sort_values(ascending=False).index).head(n)
    rows = []
    for i, (_, row) in enumerate(worst.iterrows(), 1):
        diff = row["diff"]
        diff_cls = "diff-good" if diff > 0 else ("diff-bad" if diff < -1 else "diff-mid")
        name = row.get("web_name", row["player_id"])
        link = (
            html.A(name, href=f"/player/{int(row['player_id'])}",
                   style={"fontWeight": 500, "textDecoration": "none", "color": INK})
        )
        rows.append(html.Tr([
            html.Td(i, className="mono rank-num"),
            html.Td(f"GW{int(row['predict_gw'])}", className="mono"),
            html.Td(link),
            html.Td(f'{row["predicted_pts"]:.2f}', className="right mono", style={"color": ACCENT}),
            html.Td(f'{row["actual_pts"]:.0f}', className="right mono", style={"fontWeight": 600}),
            html.Td(f'{diff:+.2f}', className=f"right mono {diff_cls}"),
        ]))
    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"), html.Th("GW"), html.Th("Player"),
                html.Th("Predicted", className="right"), html.Th("Actual", className="right"),
                html.Th("Diff", className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )


@callback(
    Output("results-calibration-body", "children"),
    Input("results-season-select", "value"),
)
def update_calibration(season_key):
    if not season_key:
        return dbc.Alert("No prediction history available yet for any season.", color="secondary")

    df = get_season_calibration(season_key)
    if df.empty:
        return dbc.Alert(f"No usable prediction snapshots found for {season_key}.", color="secondary")

    return html.Div([
        _calibration_kpis(df),
        html.Div([
            html.Div([
                html.Div([
                    html.Div("Predicted vs actual", className="card-title"),
                    html.Span(f"{len(df)} player-gameweeks", className="tag"),
                ], className="card-hd"),
                dcc.Graph(figure=_calibration_scatter(df), config={"displayModeBar": False}),
            ], className="card", style={"flex": "1"}),
            html.Div([
                html.Div([
                    html.Div("MAE by gameweek", className="card-title"),
                ], className="card-hd"),
                dcc.Graph(figure=_calibration_mae_by_gw(df), config={"displayModeBar": False}),
            ], className="card", style={"flex": "1"}),
        ], style={"display": "flex", "gap": "16px", "marginTop": "16px", "marginBottom": "16px"}),
        html.Div([
            html.Div([
                html.Div("Biggest misses", className="card-title"),
                html.Span("honest calibration: where the model was wrong, not just where it was right",
                           className="tag"),
            ], className="card-hd"),
            html.Div(_worst_misses_table(df), className="card-body flush"),
        ], className="card"),
    ])


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    latest_gw   = get_latest_gw()
    predict_gw  = latest_gw + 1
    season_opts = get_calibration_season_options()
    default_season = season_opts[0]["value"] if season_opts else None

    if latest_gw > 0:
        gw_pairs = [(predict_gw - 1 - i, predict_gw - i) for i in range(4)]
        tabs = [
            dbc.Tab(
                _tab_content(from_gw, actual_gw),
                label=f"GW {actual_gw}" + (" ← current" if i == 0 else ""),
                tab_id=f"tab-{actual_gw}",
            )
            for i, (from_gw, actual_gw) in enumerate(gw_pairs)
        ]
        recent_section = dbc.Tabs(tabs, active_tab=f"tab-{predict_gw}")
    else:
        recent_section = dbc.Alert(
            "No current-season gameweeks yet. See season calibration below for prior seasons.",
            color="info",
        )

    return html.Div([

        # ── Page header ──────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("History · GW Results", className="page-eyebrow"),
                html.H1("Model performance", className="page-title serif"),
                html.P(
                    "Predicted vs actual points. Track how the XGBoost model performed "
                    "each week. Green diff = player outscored prediction.",
                    className="page-desc",
                ),
            ]),
        ], className="page-head"),

        # ── Season calibration ────────────────────────────────
        html.Div([
            html.Div("Season calibration", className="card-title", style={"marginBottom": "8px"}),
            html.Div([
                html.Div("Season", className="control-label"),
                dbc.Select(id="results-season-select", options=season_opts, value=default_season),
            ], className="control-group", style={"maxWidth": "260px", "marginBottom": "12px"}),
            html.Div(id="results-calibration-body"),
        ], style={"marginBottom": "28px"}),

        # ── Recent gameweeks ───────────────────────────────────
        html.Div("Recent gameweeks", className="card-title", style={"marginBottom": "8px"}),
        recent_section,

    ], className="page")
