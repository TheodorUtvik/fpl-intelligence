"""
Player profile page — /player/<player_id>
Shows GW-by-GW form, xG/xA trends, and SHAP feature contributions.
"""

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from app.data_loader import (
    get_features_for_player,
    get_latest_gw,
    get_players_with_predictions,
    get_predictor,
    load_features,
)

dash.register_page(__name__, path="/player/<player_id>", name="Player")

GREEN  = "#00bc8c"
BLUE   = "#375a7f"
RED    = "#e74c3c"
ORANGE = "#fd7e14"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"

POS_BADGE = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}


def _form_chart(history: "pd.DataFrame") -> go.Figure:
    fig = go.Figure()

    # Actual points bars
    fig.add_trace(go.Bar(
        x=history["round"], y=history["pts_next_gw"],
        name="Actual pts",
        marker_color=BLUE,
        opacity=0.7,
    ))

    # Rolling 3GW form line
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_pts_3gw"],
        name="3GW rolling avg",
        line={"color": GREEN, "width": 2},
        mode="lines",
    ))

    fig.update_layout(
        plot_bgcolor=CARD, paper_bgcolor=CARD, font_color=TEXT,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={"title": "Gameweek", "gridcolor": "#444"},
        yaxis={"title": "Points", "gridcolor": "#444"},
        legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": TEXT}},
        height=260,
        barmode="overlay",
    )
    return fig


def _xg_chart(history: "pd.DataFrame") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_xg_3gw"],
        name="xG (3GW)", line={"color": GREEN, "width": 2}, mode="lines+markers",
    ))
    fig.add_trace(go.Scatter(
        x=history["round"], y=history["rolling_xa_3gw"],
        name="xA (3GW)", line={"color": ORANGE, "width": 2, "dash": "dot"},
        mode="lines+markers",
    ))
    fig.update_layout(
        plot_bgcolor=CARD, paper_bgcolor=CARD, font_color=TEXT,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={"title": "Gameweek", "gridcolor": "#444"},
        yaxis={"title": "xG / xA", "gridcolor": "#444"},
        legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": TEXT}},
        height=220,
    )
    return fig


def _shap_chart(player_row: "pd.Series", predictor) -> go.Figure:
    """Horizontal bar chart of SHAP values for the player's latest GW snapshot."""
    import pandas as pd
    import numpy as np

    feature_cols = predictor.feature_cols
    X = pd.DataFrame([player_row[feature_cols].values], columns=feature_cols)
    shap_vals = predictor.explain(X)

    # shap_vals shape: (1, n_features)
    vals   = shap_vals[0]
    labels = feature_cols
    order  = np.argsort(np.abs(vals))[-12:]  # top 12 by magnitude

    top_vals   = vals[order]
    top_labels = [labels[i] for i in order]
    colours    = [GREEN if v > 0 else RED for v in top_vals]

    fig = go.Figure(go.Bar(
        x=top_vals, y=top_labels,
        orientation="h",
        marker_color=colours,
    ))
    fig.add_vline(x=0, line_color="white", line_width=1)
    fig.update_layout(
        plot_bgcolor=CARD, paper_bgcolor=CARD, font_color=TEXT,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={"title": "SHAP contribution", "gridcolor": "#444"},
        yaxis={"gridcolor": "#444"},
        height=320,
    )
    return fig


def layout(player_id=None):
    if player_id is None:
        return dbc.Container(dbc.Alert("No player ID provided.", color="warning"))

    try:
        pid = int(player_id)
    except (ValueError, TypeError):
        return dbc.Container(dbc.Alert("Invalid player ID.", color="danger"))

    # Load data
    features  = load_features()
    players   = get_players_with_predictions()
    predictor = get_predictor()
    latest_gw = get_latest_gw()

    player_features = features[features["player_id"] == pid].sort_values("round")
    player_meta     = players[players["player_id"] == pid]

    if player_features.empty or player_meta.empty:
        return dbc.Container(dbc.Alert(f"Player {pid} not found.", color="warning"))

    meta          = player_meta.iloc[0]
    name          = meta["web_name"]
    position      = meta["position"]
    team          = meta.get("team_name", "")
    cost          = meta["now_cost"]
    pred_pts      = meta["predicted_pts"]
    ownership     = meta.get("ownership_pct", 0) or 0
    pts_per_m     = meta.get("pts_per_million", 0) or 0
    latest_row    = player_features[player_features["round"] == latest_gw]

    # Charts
    form_fig  = _form_chart(player_features)
    xg_fig    = _xg_chart(player_features)

    shap_section = []
    if not latest_row.empty:
        try:
            shap_fig = _shap_chart(latest_row.iloc[0], predictor)
            shap_section = [
                html.H5("What's driving this prediction (SHAP)", className="mt-4 mb-2"),
                html.P(
                    "Green = pushed prediction up  ·  Red = pushed prediction down",
                    className="text-muted", style={"fontSize": "0.8rem"},
                ),
                dcc.Graph(figure=shap_fig, config={"displayModeBar": False}),
            ]
        except Exception:
            shap_section = [dbc.Alert("SHAP explanation unavailable.", color="secondary")]

    return dbc.Container([

        # Back link
        html.A("← Back to Top 50", href="/top50",
               style={"color": GREEN, "textDecoration": "none", "fontSize": "0.9rem"}),

        html.Hr(style={"borderColor": "#444", "marginTop": "0.5rem"}),

        # Header
        dbc.Row([
            dbc.Col([
                html.H2(name, className="fw-bold mb-1"),
                html.Span(dbc.Badge(position, color=POS_BADGE.get(position, "secondary"),
                                    className="me-2")),
                html.Span(team, style={"color": "#aaa"}),
            ], md=6),
            dbc.Col(
                dbc.Row([
                    dbc.Col(dbc.Card(dbc.CardBody([
                        html.P("Predicted pts", className="text-muted mb-1",
                               style={"fontSize": "0.8rem"}),
                        html.H4(f"{pred_pts:.2f}", style={"color": GREEN, "fontWeight": "bold"}),
                    ]), style={"backgroundColor": CARD}), xs=6, md=3),
                    dbc.Col(dbc.Card(dbc.CardBody([
                        html.P("Cost", className="text-muted mb-1",
                               style={"fontSize": "0.8rem"}),
                        html.H4(f"£{cost:.1f}m", style={"color": ORANGE}),
                    ]), style={"backgroundColor": CARD}), xs=6, md=3),
                    dbc.Col(dbc.Card(dbc.CardBody([
                        html.P("pts / £m", className="text-muted mb-1",
                               style={"fontSize": "0.8rem"}),
                        html.H4(f"{pts_per_m:.2f}", style={"color": TEXT}),
                    ]), style={"backgroundColor": CARD}), xs=6, md=3),
                    dbc.Col(dbc.Card(dbc.CardBody([
                        html.P("Owned by", className="text-muted mb-1",
                               style={"fontSize": "0.8rem"}),
                        html.H4(f"{ownership:.1f}%", style={"color": TEXT}),
                    ]), style={"backgroundColor": CARD}), xs=6, md=3),
                ], className="g-2"),
                md=6,
            ),
        ], className="mb-4"),

        # Form chart
        html.H5("Points per gameweek", className="mb-2"),
        dcc.Graph(figure=form_fig, config={"displayModeBar": False}),

        # xG/xA chart
        html.H5("xG & xA rolling 3GW average", className="mt-4 mb-2"),
        dcc.Graph(figure=xg_fig, config={"displayModeBar": False}),

        # SHAP chart
        *shap_section,

    ], fluid=True, className="py-4 px-3")
