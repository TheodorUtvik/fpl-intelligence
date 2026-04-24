"""
Player profile page — /player/<player_id>
Shows GW-by-GW form, xG/xA trends, and SHAP feature contributions.
"""

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from app.data_loader import (
    get_latest_gw,
    get_players_with_predictions,
    get_predictor,
    load_features,
)

dash.register_page(__name__, path="/player/<player_id>", name="Player")

BG_ELEV    = "#fbf9f3"
BG_INSET   = "#efeadd"
INK        = "#14130f"
INK_3      = "#6e6c64"
CHART_GRID = "#e0daca"
RULE       = "#d6d1c2"
ACCENT     = "#3d7a52"
GOOD       = "#3d7452"
BAD        = "#b5553a"
WARN       = "#c8a84a"

POS_BADGE = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}


def _chart_base(**kwargs):
    base = dict(
        plot_bgcolor  = BG_INSET,
        paper_bgcolor = BG_ELEV,
        font          = dict(color=INK, family="JetBrains Mono, monospace", size=11),
        margin        = dict(t=10, b=10, l=10, r=10),
        xaxis         = dict(gridcolor=CHART_GRID, linecolor=RULE,
                             tickfont=dict(size=10, color=INK_3)),
        yaxis         = dict(gridcolor=CHART_GRID, linecolor=RULE,
                             tickfont=dict(size=10, color=INK_3)),
        legend        = dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK_3, size=10)),
    )
    base.update(kwargs)
    return base


def _form_chart(history) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=history["round"], y=history["pts_next_gw"],
        name="Actual pts",
        marker_color="#4a6fb5",
        opacity=0.65,
    ))
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_pts_3gw"],
        name="3GW avg",
        line={"color": ACCENT, "width": 2},
        mode="lines",
    ))
    fig.update_layout(**_chart_base(
        height=260,
        barmode="overlay",
        xaxis=dict(title="Gameweek", gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
        yaxis=dict(title="Points", gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
    ))
    return fig


def _xg_chart(history) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_xg_3gw"],
        name="xG (3GW)",
        line={"color": ACCENT, "width": 2},
        mode="lines+markers",
        marker=dict(size=5),
    ))
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_xa_3gw"],
        name="xA (3GW)",
        line={"color": WARN, "width": 2, "dash": "dot"},
        mode="lines+markers",
        marker=dict(size=5),
    ))
    fig.update_layout(**_chart_base(
        height=220,
        xaxis=dict(title="Gameweek", gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
        yaxis=dict(title="xG / xA", gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
    ))
    return fig


def _shap_chart(player_row, predictor) -> go.Figure:
    import numpy as np
    import pandas as pd

    feature_cols = predictor.feature_cols
    X            = pd.DataFrame([player_row[feature_cols].values], columns=feature_cols)
    shap_vals    = predictor.explain(X)
    vals         = shap_vals[0]
    order        = np.argsort(np.abs(vals))[-12:]
    top_vals     = vals[order]
    top_labels   = [feature_cols[i] for i in order]
    colours      = [ACCENT if v > 0 else BAD for v in top_vals]

    fig = go.Figure(go.Bar(
        x=top_vals, y=top_labels,
        orientation="h",
        marker_color=colours,
    ))
    fig.add_vline(x=0, line_color=RULE, line_width=1)
    fig.update_layout(**_chart_base(
        height=320,
        xaxis=dict(title="SHAP contribution", gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
        yaxis=dict(gridcolor=CHART_GRID, linecolor=RULE,
                   tickfont=dict(size=10, color=INK_3)),
    ))
    return fig


def layout(player_id=None):
    if player_id is None:
        return html.Div(
            dbc.Alert("No player ID provided.", color="warning"),
            className="page",
        )

    try:
        pid = int(player_id)
    except (ValueError, TypeError):
        return html.Div(
            dbc.Alert("Invalid player ID.", color="danger"),
            className="page",
        )

    features  = load_features()
    players   = get_players_with_predictions()
    predictor = get_predictor()
    latest_gw = get_latest_gw()

    player_features = features[features["player_id"] == pid].sort_values("round")
    player_meta     = players[players["player_id"] == pid]

    if player_features.empty or player_meta.empty:
        return html.Div(
            dbc.Alert(f"Player {pid} not found.", color="warning"),
            className="page",
        )

    meta       = player_meta.iloc[0]
    name       = meta["web_name"]
    position   = meta["position"]
    team       = meta.get("team_name", "")
    cost       = meta["now_cost"]
    pred_pts   = meta["predicted_pts"]
    ownership  = meta.get("ownership_pct", 0) or 0
    pts_per_m  = meta.get("pts_per_million", 0) or 0
    latest_row = player_features[player_features["round"] == latest_gw]

    form_fig = _form_chart(player_features)
    xg_fig   = _xg_chart(player_features)

    shap_content = None
    if not latest_row.empty:
        try:
            shap_fig     = _shap_chart(latest_row.iloc[0], predictor)
            shap_content = html.Div([
                html.Div([
                    html.Div("Feature contributions · SHAP (TreeExplainer)", className="card-title"),
                    html.Span("green = pushes prediction up", className="tag accent"),
                ], className="card-hd"),
                html.Div(
                    dcc.Graph(figure=shap_fig, config={"displayModeBar": False}),
                    className="card-body",
                    style={"padding": "12px 8px"},
                ),
            ], className="card")
        except Exception:
            shap_content = dbc.Alert("SHAP explanation unavailable.", color="secondary")

    return html.Div([

        # ── Page header ──────────────────────────────────────
        html.Div([
            html.Div([
                html.A(
                    "← Top 50",
                    href="/top50",
                    style={"fontFamily": "var(--font-mono)", "fontSize": "11px",
                           "color": "var(--ink-3)", "textDecoration": "none",
                           "letterSpacing": "0.04em", "marginBottom": "8px",
                           "display": "block"},
                ),
                html.Div(
                    f"{position} · {team}",
                    className="page-eyebrow",
                ),
                html.H1(name, className="page-title serif"),
            ]),
            html.Div([
                html.Span(html.Span(position, className=f"pos-pill pos-{position}")),
                html.Span([
                    "predicted ", html.Strong(f"{pred_pts:.2f} pts"),
                ], style={"fontFamily": "var(--font-mono)", "fontSize": "11px",
                          "color": "var(--ink-3)"}),
            ], style={"display": "flex", "flexDirection": "column",
                      "gap": "6px", "alignItems": "flex-end"}),
        ], className="page-head"),

        # ── KPI strip ────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Predicted pts", className="kpi-label"),
                html.Div([f"{pred_pts:.2f}", html.Span("pts", className="unit")],
                         className="kpi-value mono"),
            ], className="kpi"),
            html.Div([
                html.Div("Cost", className="kpi-label"),
                html.Div([f"£{cost:.1f}", html.Span("m", className="unit")],
                         className="kpi-value mono"),
            ], className="kpi"),
            html.Div([
                html.Div("pts / £m", className="kpi-label"),
                html.Div(f"{pts_per_m:.2f}", className="kpi-value mono"),
            ], className="kpi"),
            html.Div([
                html.Div("Ownership", className="kpi-label"),
                html.Div([f"{ownership:.1f}", html.Span("%", className="unit")],
                         className="kpi-value mono"),
            ], className="kpi"),
        ], className="kpi-grid"),

        # ── Form chart ───────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Points per gameweek", className="card-title"),
                html.Span("bars = actual · line = 3GW rolling avg", className="tag"),
            ], className="card-hd"),
            html.Div(
                dcc.Graph(figure=form_fig, config={"displayModeBar": False}),
                className="card-body",
                style={"padding": "12px 8px"},
            ),
        ], className="card"),

        # ── xG/xA chart ──────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("xG & xA rolling 3GW average", className="card-title"),
                html.Span("Understat", className="tag"),
            ], className="card-hd"),
            html.Div(
                dcc.Graph(figure=xg_fig, config={"displayModeBar": False}),
                className="card-body",
                style={"padding": "12px 8px"},
            ),
        ], className="card"),

        # ── SHAP chart ───────────────────────────────────────
        shap_content or "",

    ], className="page")
