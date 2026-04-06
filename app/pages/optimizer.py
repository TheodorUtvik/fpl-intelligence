"""
Squad Optimizer page.
Runs the ILP solver on button click and renders the result as a pitch visual + table.
"""

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
from dash import Input, Output, State, callback, dcc, html

from app.data_loader import get_available_players, get_latest_gw, get_optimizer

dash.register_page(__name__, path="/optimizer", name="Optimizer")

GREEN  = "#00bc8c"
BLUE   = "#375a7f"
RED    = "#e74c3c"
ORANGE = "#fd7e14"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"
PITCH  = "#2d7a2d"

POS_COLOUR = {"GKP": ORANGE, "DEF": BLUE, "MID": GREEN, "FWD": RED}
POS_BADGE  = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}


# ── Pitch figure ─────────────────────────────────────────────────────────────

def _build_pitch_figure(squad_df, captain_name: str, vice_name: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        xaxis={"visible": False, "range": [0, 1]},
        yaxis={"visible": False, "range": [0, 1]},
        plot_bgcolor=PITCH,
        paper_bgcolor="#1a1a2e",
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        height=540,
        showlegend=False,
    )

    # Pitch markings
    fig.add_shape(type="rect", x0=0.04, y0=0.03, x1=0.96, y1=0.97,
                  line={"color": "white", "width": 2})
    fig.add_shape(type="line", x0=0.04, y0=0.5, x1=0.96, y1=0.5,
                  line={"color": "white", "width": 1.5})
    fig.add_shape(type="circle", x0=0.42, y0=0.43, x1=0.58, y1=0.57,
                  line={"color": "white", "width": 1.5})

    # Row y positions — kept away from pitch edges so labels don't overlap outline
    row_y = {"GKP": 0.13, "DEF": 0.35, "MID": 0.60, "FWD": 0.84}

    def row_xs(n: int) -> list:
        if n == 1:
            return [0.5]
        spacing = {2: (0.3, 0.7), 3: (0.2, 0.8), 4: (0.15, 0.85), 5: (0.1, 0.9)}
        lo, hi = spacing.get(n, (0.1, 0.9))
        return list(np.linspace(lo, hi, n))

    for pos, y in row_y.items():
        pos_players = squad_df[squad_df["position"] == pos].reset_index(drop=True)
        n = len(pos_players)
        if n == 0:
            continue
        xs = row_xs(n)

        for i, (_, player) in enumerate(pos_players.iterrows()):
            name      = player["web_name"]
            pts       = player["predicted_pts"]
            cost      = player["now_cost"]
            team_name = str(player.get("team_name", ""))
            color     = POS_COLOUR[pos]
            x         = xs[i]

            badge = " (C)" if name == captain_name else (" (V)" if name == vice_name else "")

            # Truncate long names so labels don't overflow into neighbours
            display_name = name if len(name) <= 11 else name[:10] + "."

            # Player dot
            fig.add_trace(go.Scatter(
                x=[x], y=[y],
                mode="markers",
                marker={"size": 30, "color": color, "line": {"color": "white", "width": 2}},
                hovertemplate=(
                    f"<b>{name}{badge}</b><br>"
                    f"Pred: {pts:.2f} pts<br>"
                    f"Cost: £{cost:.1f}m<extra></extra>"
                ),
            ))

            # Name label — sits just above the dot, no background box to avoid clipping
            fig.add_annotation(
                x=x, y=y + 0.055,
                text=f"<b>{display_name}{badge}</b>",
                showarrow=False,
                font={"color": TEXT, "size": 8.5},
                bgcolor="rgba(0,0,0,0.6)",
                borderpad=2,
                yanchor="bottom",
            )

            # Team · pts on a single line below the dot
            fig.add_annotation(
                x=x, y=y - 0.055,
                text=f"{team_name}  {pts:.1f}pts",
                showarrow=False,
                font={"color": "#ddd", "size": 8},
                yanchor="top",
            )

    return fig


# ── Squad table ───────────────────────────────────────────────────────────────

def _squad_table(squad_df, captain_name: str) -> dbc.Table:
    rows = []
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        pos_players = squad_df[squad_df["position"] == pos]
        for _, row in pos_players.iterrows():
            cap = " (C)" if row["web_name"] == captain_name else ""
            rows.append(html.Tr([
                html.Td(dbc.Badge(row["position"], color=POS_BADGE.get(row["position"], "secondary"))),
                html.Td(f'{row["web_name"]}{cap}',
                        style={"fontWeight": "bold" if cap else "normal", "color": TEXT}),
                html.Td(row.get("team_name", ""), style={"color": "#aaa"}),
                html.Td(f'£{row["now_cost"]:.1f}m', style={"color": "#aaa"}),
                html.Td(f'{row["predicted_pts"]:.2f}',
                        style={"color": GREEN, "fontWeight": "bold"}),
            ]))

    return dbc.Table(
        [
            html.Thead(html.Tr(
                [html.Th(h) for h in ["Pos", "Player", "Club", "Cost", "Pred. pts"]],
                style={"color": TEXT},
            )),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
        style={"backgroundColor": CARD},
    )


# ── Page layout ───────────────────────────────────────────────────────────────

layout = dbc.Container([

    dbc.Row(dbc.Col([
        html.H2("Squad Optimizer", className="fw-bold mb-0"),
        html.P(
            "Integer Linear Programming selects the best 15-man squad or starting XI "
            "within the £100m FPL budget.",
            className="text-muted",
        ),
        html.Hr(style={"borderColor": "#444"}),
    ])),

    # Controls
    dbc.Row([
        dbc.Col([
            html.Label("Squad type", className="text-muted mb-1"),
            dbc.RadioItems(
                id="opt-squad-type",
                options=[
                    {"label": "Full squad (15 players)", "value": "squad"},
                    {"label": "Starting XI (11 players)", "value": "xi"},
                ],
                value="squad",
                inline=True,
                className="mb-3",
            ),
            dbc.Button(
                "Optimise Squad",
                id="opt-run-btn",
                color="success",
                size="lg",
                n_clicks=0,
            ),
        ], md=8),
    ], className="mb-4"),

    # Loading wrapper around results
    dcc.Loading(
        id="opt-loading",
        type="circle",
        color=GREEN,
        children=html.Div(id="opt-results"),
    ),

], fluid=True, className="py-4 px-3")


# ── Callback ──────────────────────────────────────────────────────────────────

@callback(
    Output("opt-results", "children"),
    Input("opt-run-btn", "n_clicks"),
    State("opt-squad-type", "value"),
    prevent_initial_call=True,
)
def run_optimizer(n_clicks, squad_type):
    players = get_available_players()
    optimizer = get_optimizer()

    if squad_type == "xi":
        result = optimizer.select_starting_xi(players, budget=100.0)
        squad_df   = result.get("xi", result.get("squad"))
        formation  = result.get("formation", "")
        title_extra = f"  ·  Formation: {formation}"
    else:
        result = optimizer.select_squad(players, budget=100.0)
        squad_df   = result["squad"]
        title_extra = ""

    if result["status"] != "Optimal":
        return dbc.Alert("Optimisation failed — no feasible squad found.", color="danger")

    captain    = result["captain"]
    vice       = result["vice_captain"]
    total_cost = result["total_cost"]
    pred_total = result["predicted_total"]

    # Summary bar
    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Total cost", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(f"£{total_cost:.1f}m", style={"color": ORANGE, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Predicted total", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(f"{pred_total:.2f} pts", style={"color": GREEN, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Captain", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(captain, style={"color": TEXT, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Vice-captain", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(vice, style={"color": TEXT}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
    ], className="g-3 mb-4")

    # Pitch + table side by side
    pitch_and_table = dbc.Row([
        dbc.Col(
            dcc.Graph(
                figure=_build_pitch_figure(squad_df, captain, vice),
                config={"displayModeBar": False},
            ),
            md=6,
        ),
        dbc.Col([
            html.H5(
                f"{'15-man Squad' if squad_type == 'squad' else 'Starting XI'}{title_extra}",
                className="mb-3",
            ),
            _squad_table(squad_df, captain),
        ], md=6),
    ])

    return html.Div([summary, pitch_and_table])
