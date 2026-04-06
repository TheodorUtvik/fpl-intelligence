"""
Home page — overview dashboard.
"""

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from app.data_loader import (
    get_available_players,
    get_latest_gw,
    get_players_with_predictions,
)

dash.register_page(__name__, path="/", name="Home")

BLUE   = "#375a7f"
GREEN  = "#00bc8c"
RED    = "#e74c3c"
ORANGE = "#fd7e14"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"

POS_COLOUR = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}


def _kpi_card(title: str, value: str, colour: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.P(title, className="text-muted mb-1", style={"fontSize": "0.85rem"}),
                html.H3(value, style={"color": colour, "fontWeight": "bold"}),
            ]),
            style={"backgroundColor": CARD, "border": f"1px solid {colour}"},
        ),
        xs=12, sm=6, md=3,
    )


def _top_scorers_table(players_df) -> dbc.Table:
    top = players_df.sort_values("predicted_pts", ascending=False).head(10)
    rows = [
        html.Tr([
            html.Td(i, style={"color": TEXT, "width": "32px"}),
            html.Td(row["web_name"], style={"color": TEXT, "fontWeight": "bold"}),
            html.Td(dbc.Badge(row["position"], color=POS_COLOUR.get(row["position"], "secondary"))),
            html.Td(row.get("team_name", ""), style={"color": "#aaa"}),
            html.Td(f'£{row["now_cost"]:.1f}m', style={"color": "#aaa"}),
            html.Td(f'{row["predicted_pts"]:.2f}', style={"color": GREEN, "fontWeight": "bold"}),
        ])
        for i, (_, row) in enumerate(top.iterrows(), 1)
    ]
    return dbc.Table(
        [
            html.Thead(html.Tr(
                [html.Th(h) for h in ["#", "Player", "Pos", "Club", "Cost", "Pred. pts"]],
                style={"color": TEXT},
            )),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
        style={"backgroundColor": CARD},
    )


def _avg_pts_by_position(players_df) -> go.Figure:
    pos_stats = (
        players_df.groupby("position")["predicted_pts"]
        .mean()
        .reindex(["GKP", "DEF", "MID", "FWD"])
    )
    fig = go.Figure(go.Bar(
        x=pos_stats.index.tolist(),
        y=pos_stats.values.round(2),
        marker_color=[ORANGE, BLUE, GREEN, RED],
        text=pos_stats.values.round(2),
        textposition="outside",
        textfont={"color": TEXT},
    ))
    fig.update_layout(
        plot_bgcolor=CARD, paper_bgcolor=CARD, font_color=TEXT,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={"gridcolor": "#444"},
        yaxis={"gridcolor": "#444", "title": "Avg predicted pts"},
        height=200, showlegend=False,
    )
    return fig


def _top_value_chart(players_df) -> go.Figure:
    top_val = (
        players_df[players_df["predicted_pts"] > 2]
        .sort_values("pts_per_million", ascending=False)
        .head(10)
    )
    fig = go.Figure(go.Bar(
        y=top_val["web_name"].tolist(),
        x=top_val["pts_per_million"].round(2).tolist(),
        orientation="h",
        marker_color=GREEN,
        text=top_val["pts_per_million"].round(2).tolist(),
        textposition="outside",
        textfont={"color": TEXT},
    ))
    fig.update_layout(
        plot_bgcolor=CARD, paper_bgcolor=CARD, font_color=TEXT,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={"gridcolor": "#444", "title": "pts / £m"},
        yaxis={"gridcolor": "#444", "autorange": "reversed"},
        height=280,
    )
    return fig


def layout():
    players   = get_players_with_predictions()
    latest_gw = get_latest_gw()

    n_total  = len(players)
    n_avail  = len(get_available_players())
    xg_cov   = (players["rolling_xg_3gw"] > 0).mean()
    top_pick = players.sort_values("predicted_pts", ascending=False).iloc[0]

    return dbc.Container([

        # Header
        dbc.Row(dbc.Col([
            html.H1("FPL Intelligence", className="fw-bold mb-0"),
            html.P(
                f"Gameweek {latest_gw} predictions  ·  XGBoost + ILP squad optimisation",
                className="text-muted mt-1",
            ),
            html.Hr(style={"borderColor": "#444"}),
        ]), className="mb-2"),

        # KPI cards
        dbc.Row([
            _kpi_card("Current Gameweek",  f"GW {latest_gw}", BLUE),
            _kpi_card("Players Tracked",   str(n_total),      GREEN),
            _kpi_card("Available Players", str(n_avail),      ORANGE),
            _kpi_card("xG Coverage",       f"{xg_cov:.0%}",   RED),
        ], className="g-3 mb-4"),

        # Top scorers + charts
        dbc.Row([
            dbc.Col([
                html.H5("Top 10 predicted scorers this GW", className="mb-3"),
                _top_scorers_table(players),
            ], md=6),
            dbc.Col([
                html.H5("Avg predicted pts by position"),
                dcc.Graph(figure=_avg_pts_by_position(players),
                          config={"displayModeBar": False}),
                html.H5("Best value players (pts / £m)", className="mt-3"),
                dcc.Graph(figure=_top_value_chart(players),
                          config={"displayModeBar": False}),
            ], md=6),
        ], className="mb-4"),

        # CTA banner
        dbc.Row(dbc.Col(
            dbc.Card(
                dbc.CardBody(dbc.Row([
                    dbc.Col([
                        html.H5(
                            f"Top pick this week: {top_pick['web_name']}",
                            style={"color": GREEN, "fontWeight": "bold"},
                        ),
                        html.P(
                            f"{top_pick['position']}  ·  "
                            f"£{top_pick['now_cost']:.1f}m  ·  "
                            f"{top_pick['predicted_pts']:.2f} predicted pts",
                            className="text-muted mb-0",
                        ),
                    ], md=8),
                    dbc.Col(
                        dbc.Button("Build Optimal Squad →", href="/optimizer",
                                   color="success", size="lg"),
                        md=4,
                        className="d-flex align-items-center justify-content-end",
                    ),
                ])),
                style={"backgroundColor": CARD, "border": f"1px solid {GREEN}"},
            ),
        )),

    ], fluid=True, className="py-4 px-3")
