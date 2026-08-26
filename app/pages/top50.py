"""
Top 50 page — sortable leaderboard of predicted scorers.
Includes a GW selector to browse historical prediction snapshots.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html

from app.components.club_badge import render_club_badge
from app.data_loader import (
    get_latest_gw,
    get_players_with_predictions,
    get_prediction_history_gws,
    load_predictions_for_gw,
)

dash.register_page(__name__, path="/top50", name="Top 50")

INK   = "#14130f"
INK_3 = "#6e6c64"
ACCENT = "#3d7a52"

POS_OPTIONS = [
    {"label": "All positions", "value": "ALL"},
    {"label": "GKP",           "value": "GKP"},
    {"label": "DEF",           "value": "DEF"},
    {"label": "MID",           "value": "MID"},
    {"label": "FWD",           "value": "FWD"},
]

_history_gws  = get_prediction_history_gws()
_current_pred = get_latest_gw() + 1

_gw_options = [
    {"label": f"GW {gw} (saved)", "value": gw}
    for gw in sorted(_history_gws, reverse=True)
]
if _current_pred not in _history_gws:
    _gw_options.insert(0, {"label": f"GW {_current_pred} (live)", "value": _current_pred})

_default_gw = _current_pred


layout = html.Div([

    # ── Page header ──────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Analysis · Leaderboard", className="page-eyebrow"),
            html.H1("Top 50 Players", className="page-title serif"),
            html.P(id="top50-subtitle", className="page-desc"),
        ]),
    ], className="page-head"),

    # ── Filters ──────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Gameweek", className="control-label"),
            dbc.Select(
                id="top50-gw-select",
                options=_gw_options,
                value=_default_gw,
            ),
        ], className="control-group"),
        html.Div([
            html.Div("Position", className="control-label"),
            dbc.Select(
                id="top50-pos-filter",
                options=POS_OPTIONS,
                value="ALL",
            ),
        ], className="control-group"),
        html.Div([
            html.Div("Sort by", className="control-label"),
            dbc.Select(
                id="top50-sort",
                options=[
                    {"label": "Predicted pts",       "value": "predicted_pts"},
                    {"label": "Value (pts / £m)",     "value": "pts_per_million"},
                    {"label": "Rolling form (3GW)",   "value": "rolling_pts_3gw"},
                ],
                value="predicted_pts",
            ),
        ], className="control-group"),
    ], className="controls-bar"),

    # ── Table card ───────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div(id="top50-card-title", className="card-title"),
            html.Span("click player name to drill in", className="tag"),
        ], className="card-hd"),
        html.Div(id="top50-table", className="card-body flush"),
    ], className="card"),

], className="page")


@callback(
    Output("top50-table", "children"),
    Output("top50-subtitle", "children"),
    Output("top50-card-title", "children"),
    Input("top50-gw-select", "value"),
    Input("top50-pos-filter", "value"),
    Input("top50-sort", "value"),
)
def update_table(selected_gw, pos_filter, sort_col):
    selected_gw = int(selected_gw)
    latest_gw   = get_latest_gw()
    predict_gw  = latest_gw + 1

    if selected_gw == predict_gw:
        df = get_players_with_predictions().copy()
        if df.empty:
            return (
                dbc.Alert(
                    "Predictions aren't ready yet. The model needs at least one "
                    "completed current-season gameweek of data.",
                    color="info",
                ),
                "",
                "-",
            )
        subtitle    = (
            f"Predicting GW {predict_gw}  ·  based on GW {latest_gw} data"
        )
        card_title  = f"Predicted scorers · GW {predict_gw}"
    else:
        try:
            df = load_predictions_for_gw(selected_gw)
            data_gw    = selected_gw - 1
            subtitle   = (
                f"GW {selected_gw} predictions (saved snapshot)  ·  "
                f"based on GW {data_gw} data"
            )
            card_title = f"Predicted scorers · GW {selected_gw} (snapshot)"
        except FileNotFoundError:
            return (
                dbc.Alert(f"No snapshot found for GW {selected_gw}.", color="warning"),
                "",
                "-",
            )

    if pos_filter != "ALL":
        df = df[df["position"] == pos_filter]

    df = df.sort_values(sort_col, ascending=False).head(50).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))

    rows = []
    for _, row in df.iterrows():
        pos  = row["position"]
        xg   = row.get("rolling_xg_3gw", 0) or 0
        xa   = row.get("rolling_xa_3gw", 0) or 0
        own  = row.get("ownership_pct", 0) or 0
        form = row.get("rolling_pts_3gw", 0) or 0
        ppm  = row.get("pts_per_million", None)

        rows.append(html.Tr([
            html.Td(int(row["rank"]), className="mono rank-num"),
            html.Td(
                html.A(
                    row["web_name"],
                    href=f"/player/{int(row['player_id'])}",
                    style={"fontWeight": 500, "textDecoration": "none", "color": INK},
                )
            ),
            html.Td(html.Span(pos, className=f"pos-pill pos-{pos}")),
            html.Td(render_club_badge(row.get("team_name", "")), style={"color": INK_3}),
            html.Td(f'£{row["now_cost"]:.1f}m', className="right mono",
                    style={"color": INK_3}),
            html.Td(f'{row["predicted_pts"]:.2f}', className="right mono",
                    style={"color": ACCENT, "fontWeight": 600}),
            html.Td(f'{ppm:.2f}' if ppm == ppm and ppm is not None else "-",
                    className="right mono"),
            html.Td(f'{form:.2f}', className="right mono"),
            html.Td(f'{xg:.2f}',  className="right mono"),
            html.Td(f'{xa:.2f}',  className="right mono"),
            html.Td(f'{own:.1f}%', className="right mono"),
        ]))

    table = html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"),
                html.Th("Player"),
                html.Th("Pos"),
                html.Th("Club"),
                html.Th("Cost",         className="right"),
                html.Th("Pred. pts",    className="right"),
                html.Th("pts / £m",     className="right"),
                html.Th("Form 3GW",     className="right"),
                html.Th("xG 3GW",       className="right"),
                html.Th("xA 3GW",       className="right"),
                html.Th("Owned",        className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )

    return table, subtitle, card_title
