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
from app.components.warming_up import warming_up_alert

dash.register_page(__name__, path="/", name="Home")

# ── Design palette (matches CSS variables) ───────────────────────────────────
BG_ELEV  = "#fbf9f3"
BG_INSET = "#efeadd"
INK      = "#14130f"
INK_3    = "#6e6c64"
RULE     = "#d6d1c2"
CHART_GRID = "#e0daca"
ACCENT   = "#3d7a52"          # approx oklch(0.56 0.14 150)
GOOD     = "#3d7452"
BAD      = "#b5553a"

POS_COLOR = {
    "GKP": "#c8a84a",
    "DEF": "#4a6fb5",
    "MID": "#3d7a52",
    "FWD": "#b5553a",
}


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _chart_layout(**kwargs):
    """Base Plotly layout matching the design system."""
    base = dict(
        plot_bgcolor  = BG_INSET,
        paper_bgcolor = BG_ELEV,
        font          = dict(color=INK, family="JetBrains Mono, monospace", size=11),
        margin        = dict(t=10, b=10, l=10, r=10),
        xaxis         = dict(gridcolor=CHART_GRID, showgrid=True, zeroline=False,
                             linecolor=RULE, tickfont=dict(size=10, color=INK_3)),
        yaxis         = dict(gridcolor=CHART_GRID, showgrid=True, zeroline=False,
                             linecolor=RULE, tickfont=dict(size=10, color=INK_3)),
        showlegend    = False,
    )
    base.update(kwargs)
    return base


def _avg_pts_by_position(players_df) -> go.Figure:
    pos_stats = (
        players_df.groupby("position")["predicted_pts"]
        .mean()
        .reindex(["GKP", "DEF", "MID", "FWD"])
    )
    fig = go.Figure(go.Bar(
        x=pos_stats.index.tolist(),
        y=pos_stats.values.round(2),
        marker_color=[POS_COLOR[p] for p in ["GKP", "DEF", "MID", "FWD"]],
        text=[f"{v:.2f}" for v in pos_stats.values],
        textposition="outside",
        textfont=dict(color=INK, size=11),
    ))
    fig.update_layout(**_chart_layout(
        height=200,
        yaxis=dict(title="avg predicted pts", gridcolor=CHART_GRID,
                   showgrid=True, zeroline=False, tickfont=dict(size=10, color=INK_3)),
    ))
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
        marker_color=ACCENT,
        text=top_val["pts_per_million"].round(2).tolist(),
        textposition="outside",
        textfont=dict(color=INK, size=11),
    ))
    fig.update_layout(**_chart_layout(
        height=280,
        xaxis=dict(title="pts / £m", gridcolor=CHART_GRID,
                   showgrid=True, zeroline=False, tickfont=dict(size=10, color=INK_3)),
        yaxis=dict(gridcolor=CHART_GRID, showgrid=True, zeroline=False,
                   autorange="reversed", tickfont=dict(size=10, color=INK_3)),
    ))
    return fig


# ── Table helper ─────────────────────────────────────────────────────────────

def _top_scorers_table(players_df, predict_gw: int) -> html.Table:
    top = players_df.sort_values("predicted_pts", ascending=False).head(10)
    rows = []
    for i, (_, row) in enumerate(top.iterrows(), 1):
        pos = row["position"]
        rows.append(html.Tr([
            html.Td(i, className="mono", style={"color": INK_3, "width": "32px"}),
            html.Td(
                html.A(
                    row["web_name"],
                    href=f"/player/{int(row['player_id'])}",
                    style={"fontWeight": 500, "textDecoration": "none", "color": INK},
                )
            ),
            html.Td(html.Span(pos, className=f"pos-pill pos-{pos}")),
            html.Td(row.get("team_name", ""), style={"color": INK_3}),
            html.Td(f'£{row["now_cost"]:.1f}m', className="right mono",
                    style={"color": INK_3}),
            html.Td(f'{row["predicted_pts"]:.2f}', className="right mono",
                    style={"color": ACCENT, "fontWeight": 600}),
        ]))

    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"),
                html.Th("Player"),
                html.Th("Pos"),
                html.Th("Club"),
                html.Th("Cost", className="right"),
                html.Th(f"GW {predict_gw} ŷ", className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    players    = get_players_with_predictions()
    latest_gw  = get_latest_gw()
    predict_gw = latest_gw + 1

    if players.empty:
        return warming_up_alert("Home dashboard")

    n_total  = len(players)
    n_avail  = len(get_available_players())
    played   = players[players["rolling_pts_3gw"] > 0]
    xg_cov   = (played["rolling_xg_3gw"] > 0).mean() if len(played) > 0 else 0
    top_pick = players.sort_values("predicted_pts", ascending=False).iloc[0]

    return html.Div([

        # ── Page header ──────────────────────────────────────
        html.Div([
            html.Div([
                html.Div(
                    f"Gameweek {predict_gw} · Pre-deadline briefing",
                    className="page-eyebrow",
                ),
                html.H1("The model has opinions this week.", className="page-title serif"),
                html.P(
                    f"XGBoost predictions for every eligible player, filtered through a PuLP ILP "
                    f"that finds the optimal squad under FPL's £100m budget and 3-per-club cap.",
                    className="page-desc",
                ),
            ]),
            html.Div([
                html.Span(f"{n_total} players scored"),
                html.Span([
                    "predicting ", html.Strong(f"GW {predict_gw}"),
                ]),
                html.Span([
                    "based on ", html.Strong(f"GW {latest_gw}"), " data",
                ]),
            ], className="page-head-meta"),
        ], className="page-head"),

        # ── KPI grid ─────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Predicting for", className="kpi-label"),
                html.Div(f"GW {predict_gw}", className="kpi-value mono"),
                html.Div(
                    [html.Span(f"based on GW {latest_gw} data")],
                    className="kpi-delta",
                ),
            ], className="kpi"),
            html.Div([
                html.Div("Top pick", className="kpi-label"),
                html.Div(top_pick["web_name"], className="kpi-value serif-val"),
                html.Div(
                    [html.Span(f"{top_pick['predicted_pts']:.1f} pts predicted", className="mono")],
                    className="kpi-delta",
                ),
            ], className="kpi"),
            html.Div([
                html.Div("Available players", className="kpi-label"),
                html.Div(str(n_avail), className="kpi-value mono"),
                html.Div(
                    [html.Span(f"of {n_total} tracked")],
                    className="kpi-delta",
                ),
            ], className="kpi"),
            html.Div([
                html.Div("xG coverage", className="kpi-label"),
                html.Div([
                    f"{xg_cov:.0%}",
                    html.Span("players", className="unit"),
                ], className="kpi-value mono"),
                html.Div(
                    [html.Span("with Understat data")],
                    className="kpi-delta",
                ),
            ], className="kpi"),
        ], className="kpi-grid"),

        # ── Top scorers + charts ──────────────────────────────
        html.Div([

            # Left: top 10 table
            html.Div([
                html.Div([
                    html.Div(f"Top 10 predicted · GW {predict_gw}", className="card-title"),
                    html.Span("xgboost", className="tag accent"),
                ], className="card-hd"),
                html.Div(
                    _top_scorers_table(players, predict_gw),
                    className="card-body flush",
                ),
            ], className="card", style={"flex": "1 1 0"}),

            # Right: two charts stacked
            html.Div([
                html.Div([
                    html.Div([
                        html.Div("Avg predicted pts by position", className="card-title"),
                    ], className="card-hd"),
                    html.Div(
                        dcc.Graph(
                            figure=_avg_pts_by_position(players),
                            config={"displayModeBar": False},
                        ),
                        className="card-body",
                        style={"padding": "12px 8px"},
                    ),
                ], className="card"),

                html.Div([
                    html.Div([
                        html.Div("Best value · pts / £m", className="card-title"),
                        html.Span("pred pts > 2", className="tag"),
                    ], className="card-hd"),
                    html.Div(
                        dcc.Graph(
                            figure=_top_value_chart(players),
                            config={"displayModeBar": False},
                        ),
                        className="card-body",
                        style={"padding": "12px 8px"},
                    ),
                ], className="card"),

            ], style={"flex": "1 1 0", "display": "flex", "flexDirection": "column", "gap": "0"}),

        ], style={"display": "flex", "gap": "18px", "alignItems": "flex-start"}),

        # ── CTA banner ───────────────────────────────────────
        html.Div([
            html.Div([
                html.Div(
                    f"Top pick this week: {top_pick['web_name']}",
                    className="cta-banner-title",
                ),
                html.Div(
                    f"{top_pick['position']}  ·  "
                    f"£{top_pick['now_cost']:.1f}m  ·  "
                    f"{top_pick['predicted_pts']:.2f} predicted pts",
                    className="cta-banner-sub",
                ),
            ]),
            html.A(
                "Build optimal squad →",
                href="/optimizer",
                className="btn-primary-custom",
            ),
        ], className="cta-banner"),

    ], className="page")
