"""
Top 50 page — sortable leaderboard of predicted scorers.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dash_table, html

from app.data_loader import get_latest_gw, get_players_with_predictions

dash.register_page(__name__, path="/top50", name="Top 50")

GREEN  = "#00bc8c"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"

POS_OPTIONS = [
    {"label": "All positions", "value": "ALL"},
    {"label": "GKP", "value": "GKP"},
    {"label": "DEF", "value": "DEF"},
    {"label": "MID", "value": "MID"},
    {"label": "FWD", "value": "FWD"},
]

layout = dbc.Container([

    dbc.Row(dbc.Col([
        html.H2("Top 50 Players", className="fw-bold mb-0"),
        html.P(
            f"Predicting GW {get_latest_gw() + 1}  ·  based on GW {get_latest_gw()} data. "
            "Click any player name to view their full profile.",
            className="text-muted",
        ),
        html.Hr(style={"borderColor": "#444"}),
    ])),

    # Filters
    dbc.Row([
        dbc.Col([
            html.Label("Position", className="text-muted mb-1"),
            dbc.Select(
                id="top50-pos-filter",
                options=POS_OPTIONS,
                value="ALL",
            ),
        ], xs=6, md=3),
        dbc.Col([
            html.Label("Sort by", className="text-muted mb-1"),
            dbc.Select(
                id="top50-sort",
                options=[
                    {"label": "Predicted pts", "value": "predicted_pts"},
                    {"label": "Value (pts / £m)", "value": "pts_per_million"},
                    {"label": "Rolling form (3GW)", "value": "rolling_pts_3gw"},
                ],
                value="predicted_pts",
            ),
        ], xs=6, md=3),
    ], className="mb-3"),

    # Table
    html.Div(id="top50-table"),

], fluid=True, className="py-4 px-3")


@callback(
    Output("top50-table", "children"),
    Input("top50-pos-filter", "value"),
    Input("top50-sort", "value"),
)
def update_table(pos_filter, sort_col):
    df = get_players_with_predictions().copy()

    if pos_filter != "ALL":
        df = df[df["position"] == pos_filter]

    df = df.sort_values(sort_col, ascending=False).head(50).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))

    rows = []
    for _, row in df.iterrows():
        pos_colour = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}
        xg   = row.get("rolling_xg_3gw", 0) or 0
        xa   = row.get("rolling_xa_3gw", 0) or 0
        own  = row.get("ownership_pct", 0) or 0
        form = row.get("rolling_pts_3gw", 0) or 0

        rows.append(html.Tr([
            html.Td(int(row["rank"]), style={"color": "#aaa", "width": "40px"}),
            html.Td(
                html.A(
                    row["web_name"],
                    href=f"/player/{int(row['player_id'])}",
                    style={"color": GREEN, "fontWeight": "bold", "textDecoration": "none"},
                )
            ),
            html.Td(dbc.Badge(row["position"],
                              color=pos_colour.get(row["position"], "secondary"))),
            html.Td(row.get("team_name", ""), style={"color": "#aaa"}),
            html.Td(f'£{row["now_cost"]:.1f}m', style={"color": "#aaa"}),
            html.Td(
                f'{row["predicted_pts"]:.2f}',
                style={"color": GREEN, "fontWeight": "bold"},
            ),
            html.Td(f'{row["pts_per_million"]:.2f}'),
            html.Td(f'{form:.2f}'),
            html.Td(f'{xg:.2f}'),
            html.Td(f'{xa:.2f}'),
            html.Td(f'{own:.1f}%'),
        ]))

    table = dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"), html.Th("Player"), html.Th("Pos"),
                html.Th("Club"), html.Th("Cost"),
                html.Th("Pred. pts"), html.Th("pts/£m"),
                html.Th("Form (3GW)"), html.Th("xG (3GW)"),
                html.Th("xA (3GW)"), html.Th("Owned"),
            ], style={"color": TEXT})),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
        style={"backgroundColor": CARD},
    )

    return table
