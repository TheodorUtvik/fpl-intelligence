"""
Squad Optimizer page.
Runs the ILP solver on button click and renders the result as a pitch visual + table.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html  # dcc kept for dcc.Loading

from app.data_loader import get_available_players, get_latest_gw, get_optimizer

dash.register_page(__name__, path="/optimizer", name="Optimizer")

# ── Design palette ────────────────────────────────────────────────────────────
INK    = "#14130f"
INK_3  = "#6e6c64"
ACCENT = "#3d7a52"

# Position fill colors  (light text except GKP)
POS_COLOUR    = {"GKP": "#c8a84a", "DEF": "#4a6fb5", "MID": "#3d7a52", "FWD": "#b5553a"}
POS_TEXT      = {"GKP": "#14130f", "DEF": "#fff",    "MID": "#fff",    "FWD": "#fff"}


# ── HTML / CSS pitch with staggered animation ─────────────────────────────────

def _row_xs_pct(n: int) -> list[float]:
    """Return n evenly-spaced x positions as percentages of pitch width."""
    if n == 1:
        return [50.0]
    margins = {2: (25.0, 75.0), 3: (18.0, 82.0),
               4: (12.0, 88.0), 5: (8.0,  92.0)}
    lo, hi = margins.get(n, (8.0, 92.0))
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _build_html_pitch(squad_df, captain_name: str, vice_name: str) -> html.Div:
    """
    Pure HTML/CSS pitch with staggered player-land animation.

    Each token gets `animation-delay: {80 + idx*90}ms`.  The CSS fill-mode
    'both' keeps every token invisible at opacity:0 (from the keyframe 0%)
    until its delay fires — that's the cascade effect described in the design.
    """
    # y% from top: FWD at top (attacking), GKP at bottom
    row_y = {"FWD": 13, "MID": 38, "DEF": 63, "GKP": 86}

    player_tokens = []
    idx = 0

    for pos in ["FWD", "MID", "DEF", "GKP"]:
        pos_players = squad_df[squad_df["position"] == pos].reset_index(drop=True)
        n = len(pos_players)
        if n == 0:
            continue

        xs    = _row_xs_pct(n)
        y_pct = row_y[pos]
        fill  = POS_COLOUR[pos]
        txt   = POS_TEXT[pos]

        for i, (_, p) in enumerate(pos_players.iterrows()):
            name    = p["web_name"]
            pts     = p["predicted_pts"]
            team    = str(p.get("team_name", ""))[:3].upper()
            is_cap  = (name == captain_name)
            is_vice = (name == vice_name)

            delay      = 80 + idx * 90   # ms — first player at 80ms, then +90ms each
            idx       += 1

            jersey_cls = "player-jersey" + (" captain" if is_cap else " vice" if is_vice else "")
            disp_name  = name if len(name) <= 11 else name[:10] + "."

            player_tokens.append(html.Div([
                html.Div(
                    team,
                    className=jersey_cls,
                    style={"background": fill, "color": txt},
                ),
                html.Div(disp_name, className="player-name"),
                html.Div(f"{pts:.1f}", className="player-pts"),
            ], className="pitch-player enter", style={
                "left":              f"{xs[i]}%",
                "top":               f"{y_pct}%",
                "animationDelay":    f"{delay}ms",
                "animationFillMode": "both",   # stays at opacity:0 during delay
            }))

    # ── Pitch line overlays ────────────────────────────────────────────────
    lines = html.Div([
        html.Div(className="pl-border"),    # outer rectangle
        html.Div(className="pl-halfway"),   # halfway line
        html.Div(className="pl-circle"),    # centre circle
        html.Div(className="pl-pen-top"),   # top penalty area
        html.Div(className="pl-pen-bot"),   # bottom penalty area
    ])

    return html.Div([lines, *player_tokens], className="pitch-wrap")


# ── Squad table ───────────────────────────────────────────────────────────────

def _squad_table(squad_df, captain_name: str) -> html.Table:
    rows = []
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        pos_players = squad_df[squad_df["position"] == pos]
        for _, row in pos_players.iterrows():
            name = row["web_name"]
            cap  = " (C)" if name == captain_name else ""
            rows.append(html.Tr([
                html.Td(html.Span(pos, className=f"pos-pill pos-{pos}")),
                html.Td(
                    f"{name}{cap}",
                    style={"fontWeight": 500 if cap else "normal"},
                ),
                html.Td(row.get("team_name", ""), style={"color": INK_3}),
                html.Td(f'£{row["now_cost"]:.1f}m', className="right mono",
                        style={"color": INK_3}),
                html.Td(f'{row["predicted_pts"]:.2f}', className="right mono",
                        style={"color": ACCENT, "fontWeight": 600}),
            ]))

    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th("Pos"), html.Th("Player"), html.Th("Club"),
                html.Th("Cost", className="right"),
                html.Th("Pred. pts", className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )


# ── Page layout ───────────────────────────────────────────────────────────────

layout = html.Div([

    # ── Page header ──────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Actions · Optimizer", className="page-eyebrow"),
            html.H1("Squad Optimizer", className="page-title serif"),
            html.P(
                "Integer Linear Programming selects the best 15-man squad or starting XI "
                "within the £100m FPL budget and 3-per-club cap.",
                className="page-desc",
            ),
        ]),
        html.Div([
            html.Span([
                "predicting ",
                html.Strong(f"GW {get_latest_gw() + 1}"),
            ]),
            html.Span([
                "based on GW ", html.Strong(str(get_latest_gw())), " data",
            ]),
        ], className="page-head-meta"),
    ], className="page-head"),

    # ── Controls ─────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Squad type", className="control-label"),
            dbc.RadioItems(
                id="opt-squad-type",
                options=[
                    {"label": "Full squad (15)", "value": "squad"},
                    {"label": "Starting XI (11)", "value": "xi"},
                ],
                value="squad",
                inline=True,
            ),
        ], className="control-group"),
        html.Button(
            "Run optimizer",
            id="opt-run-btn",
            n_clicks=0,
            className="btn-primary-custom",
            style={"alignSelf": "flex-end"},
        ),
    ], className="controls-bar"),

    # ── Results ──────────────────────────────────────────────
    dcc.Loading(
        id="opt-loading",
        type="circle",
        color=ACCENT,
        children=html.Div(id="opt-results"),
    ),

], className="page")


# ── Callback ─────────────────────────────────────────────────────────────────

@callback(
    Output("opt-results", "children"),
    Input("opt-run-btn", "n_clicks"),
    State("opt-squad-type", "value"),
    prevent_initial_call=True,
)
def run_optimizer(n_clicks, squad_type):
    players   = get_available_players()
    optimizer = get_optimizer()

    if squad_type == "xi":
        result      = optimizer.select_starting_xi(players, budget=100.0)
        squad_df    = result.get("xi", result.get("squad"))
        title_extra = f"  ·  Formation: {result.get('formation', '')}"
    else:
        result      = optimizer.select_squad(players, budget=100.0)
        squad_df    = result["squad"]
        title_extra = ""

    if result["status"] != "Optimal":
        return dbc.Alert("Optimisation failed — no feasible squad found.", color="danger")

    captain    = result["captain"]
    vice       = result["vice_captain"]
    total_cost = result["total_cost"]
    pred_total = result["predicted_total"]

    # KPI summary
    summary = html.Div([
        html.Div([
            html.Div("Total cost", className="kpi-label"),
            html.Div([f"£{total_cost:.1f}", html.Span("m", className="unit")],
                     className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Predicted total", className="kpi-label"),
            html.Div([f"{pred_total:.1f}", html.Span("pts", className="unit")],
                     className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Captain", className="kpi-label"),
            html.Div(captain, className="kpi-value serif-val"),
        ], className="kpi"),
        html.Div([
            html.Div("Vice-captain", className="kpi-label"),
            html.Div(vice, className="kpi-value serif-val"),
        ], className="kpi"),
    ], className="squad-summary-grid", style={"marginBottom": "20px"})

    # Pitch + table
    squad_label = "15-man Squad" if squad_type == "squad" else f"Starting XI{title_extra}"

    pitch_and_table = html.Div([
        # HTML/CSS animated pitch — flex: 1 side
        html.Div(
            _build_html_pitch(squad_df, captain, vice),
            style={"flex": "1 1 0", "minWidth": 0},
        ),

        # Squad table — flex: 1 side
        html.Div([
            html.Div([
                html.Div(squad_label, className="card-title"),
                html.Span(
                    f"£{total_cost:.1f}m total · {pred_total:.1f} pred pts",
                    className="tag",
                ),
            ], className="card-hd"),
            html.Div(
                _squad_table(squad_df, captain),
                className="card-body flush",
            ),
        ], className="card", style={"flex": "1 1 0"}),

    ], style={"display": "flex", "gap": "18px", "alignItems": "flex-start"})

    return html.Div([summary, pitch_and_table])
