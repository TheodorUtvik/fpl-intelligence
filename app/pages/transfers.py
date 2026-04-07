"""
Transfer Advisor page.
User types in players they want to transfer out and gets ranked recommendations.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from app.data_loader import get_available_players, get_latest_gw, get_optimizer

dash.register_page(__name__, path="/transfers", name="Transfers")

GREEN  = "#00bc8c"
RED    = "#e74c3c"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"


def _results_table(transfers: list) -> html.Div:
    rows = []
    for i, t in enumerate(transfers[:15], 1):
        out_str = ", ".join(t["transfers_out"])
        in_str  = ", ".join(t["transfers_in"])
        net     = t["net_gain"]
        colour  = GREEN if net > 0 else RED

        rows.append(html.Tr([
            html.Td(i, style={"color": "#aaa", "width": "32px"}),
            html.Td(out_str, style={"color": RED}),
            html.Td(f'{t["out_pts"]:.2f}', style={"color": "#aaa"}),
            html.Td("→", style={"color": "#aaa"}),
            html.Td(in_str, style={"color": GREEN}),
            html.Td(f'{t["in_pts"]:.2f}', style={"color": "#aaa"}),
            html.Td(f'{t["gross_gain"]:+.2f}', style={"color": TEXT}),
            html.Td(
                dbc.Badge(f'−{t["hit"]}', color="danger") if t["hit"] > 0
                else dbc.Badge("Free", color="success")
            ),
            html.Td(
                f'{net:+.2f}',
                style={"color": colour, "fontWeight": "bold"},
            ),
            html.Td(f'{t["cost_change"]:+.1f}m', style={"color": "#aaa"}),
        ]))

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"), html.Th("Transfer out"), html.Th("pts"),
                html.Th(""), html.Th("Transfer in"), html.Th("pts"),
                html.Th("Gross"), html.Th("Hit"), html.Th("Net"), html.Th("£Δ"),
            ], style={"color": TEXT})),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
        style={"backgroundColor": CARD},
    )


layout = dbc.Container([

    dbc.Row(dbc.Col([
        html.H2("Transfer Advisor", className="fw-bold mb-0"),
        html.P(
            "Enter the players currently in your squad to get ranked transfer recommendations.",
            className="text-muted",
        ),
        html.Hr(style={"borderColor": "#444"}),
    ])),

    dbc.Row([
        dbc.Col([
            html.Label("Your current squad (one player per line or comma-separated)",
                       className="text-muted mb-1"),
            dbc.Textarea(
                id="transfers-squad-input",
                placeholder=(
                    "e.g.\nKelleher\nN.Williams\nB.Fernandes\n..."
                ),
                style={"backgroundColor": "#333", "color": TEXT,
                       "border": "1px solid #555", "height": "180px"},
            ),
        ], md=5),
        dbc.Col([
            dbc.Row([
                dbc.Col([
                    html.Label("Free transfers", className="text-muted mb-1"),
                    dbc.Select(
                        id="transfers-free",
                        options=[{"label": "1", "value": 1},
                                 {"label": "2", "value": 2}],
                        value=1,
                    ),
                ], xs=6),
                dbc.Col([
                    html.Label("Bank (£m)", className="text-muted mb-1"),
                    dbc.Input(
                        id="transfers-bank",
                        type="number", min=0, max=10, step=0.1, value=0.0,
                        style={"backgroundColor": "#333", "color": TEXT,
                               "border": "1px solid #555"},
                    ),
                ], xs=6),
            ], className="mb-3"),
            html.Br(),
            dbc.Button(
                "Find Best Transfers",
                id="transfers-run-btn",
                color="success",
                size="lg",
                n_clicks=0,
                className="mt-2",
            ),
            html.Div(id="transfers-error", className="mt-2"),
        ], md=4),
    ], className="mb-4"),

    dcc.Loading(
        id="transfers-loading",
        type="circle",
        color=GREEN,
        children=html.Div(id="transfers-results"),
    ),

], fluid=True, className="py-4 px-3")


@callback(
    Output("transfers-results", "children"),
    Output("transfers-error", "children"),
    Input("transfers-run-btn", "n_clicks"),
    State("transfers-squad-input", "value"),
    State("transfers-free", "value"),
    State("transfers-bank", "value"),
    prevent_initial_call=True,
)
def run_transfers(n_clicks, squad_text, free_transfers, bank):
    if not squad_text or not squad_text.strip():
        return None, dbc.Alert("Please enter your current squad.", color="warning")

    # Parse input — split on newlines or commas
    import re
    names = [n.strip() for n in re.split(r"[\n,]+", squad_text) if n.strip()]
    if len(names) < 11:
        return None, dbc.Alert(
            f"Only {len(names)} players entered — need at least 11.", color="warning"
        )

    # Match names to player IDs via fuzzy lookup
    from rapidfuzz import process, fuzz
    players = get_available_players()
    name_to_id = dict(zip(players["web_name"].str.lower(), players["player_id"]))
    all_names  = players["web_name"].tolist()

    squad_ids = []
    unmatched = []
    for name in names:
        match = process.extractOne(name.lower(), name_to_id.keys(),
                                   scorer=fuzz.token_set_ratio)
        if match and match[1] >= 70:
            squad_ids.append(name_to_id[match[0]])
        else:
            # Try against display names directly
            m2 = process.extractOne(name, all_names, scorer=fuzz.token_set_ratio)
            if m2 and m2[1] >= 70:
                pid = players[players["web_name"] == m2[0]]["player_id"].iloc[0]
                squad_ids.append(int(pid))
            else:
                unmatched.append(name)

    if len(squad_ids) < 11:
        return None, dbc.Alert(
            f"Could not match: {', '.join(unmatched)}. "
            "Check spelling — use the short name shown in the Top 50 table.",
            color="warning",
        )

    optimizer  = get_optimizer()
    transfers  = optimizer.recommend_transfers(
        current_squad_ids=squad_ids,
        players_df=players,
        free_transfers=int(free_transfers),
        bank=float(bank or 0),
    )

    profitable = [t for t in transfers if t["net_gain"] > 0]
    one_t = sum(1 for t in transfers if t["n_transfers"] == 1)
    two_t = sum(1 for t in transfers if t["n_transfers"] == 2)

    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Profitable transfers", className="text-muted mb-1",
                   style={"fontSize": "0.8rem"}),
            html.H4(len(profitable), style={"color": GREEN, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Best net gain", className="text-muted mb-1",
                   style={"fontSize": "0.8rem"}),
            html.H4(
                f'{transfers[0]["net_gain"]:+.2f} pts' if transfers else "—",
                style={"color": GREEN, "fontWeight": "bold"},
            ),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("1-transfer options", className="text-muted mb-1",
                   style={"fontSize": "0.8rem"}),
            html.H4(one_t, style={"color": TEXT}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("2-transfer options", className="text-muted mb-1",
                   style={"fontSize": "0.8rem"}),
            html.H4(two_t, style={"color": TEXT}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
    ], className="g-3 mb-4")

    if unmatched:
        warning = dbc.Alert(
            f"Could not match: {', '.join(unmatched)} — excluded from squad.",
            color="warning", className="mb-3",
        )
    else:
        warning = None

    return html.Div([
        summary,
        warning or "",
        html.H5("Top transfer recommendations", className="mb-3"),
        _results_table(transfers),
    ]), None
