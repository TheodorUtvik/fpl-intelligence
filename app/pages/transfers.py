"""
Transfer Advisor page.
User types in players they want to transfer out and gets ranked recommendations.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from app.data_loader import get_available_players, get_latest_gw, get_optimizer

dash.register_page(__name__, path="/transfers", name="Transfers")

INK    = "#14130f"
INK_3  = "#6e6c64"
ACCENT = "#3d7a52"
GOOD   = "#3d7452"
BAD    = "#b5553a"


def _results_table(transfers: list) -> html.Table:
    rows = []
    for i, t in enumerate(transfers[:15], 1):
        out_str = ", ".join(t["transfers_out"])
        in_str  = ", ".join(t["transfers_in"])
        net     = t["net_gain"]
        net_cls = "diff-good" if net > 0 else "diff-bad"

        rows.append(html.Tr([
            html.Td(i, className="mono rank-num"),
            html.Td(out_str, style={"color": BAD}),
            html.Td(f'{t["out_pts"]:.2f}',    className="right mono", style={"color": INK_3}),
            html.Td("→",                      style={"color": INK_3, "textAlign": "center"}),
            html.Td(in_str, style={"color": GOOD}),
            html.Td(f'{t["in_pts"]:.2f}',     className="right mono", style={"color": INK_3}),
            html.Td(f'{t["gross_gain"]:+.2f}', className="right mono"),
            html.Td(
                html.Span(
                    f'−{t["hit"]}' if t["hit"] > 0 else "Free",
                    className="tag " + ("warn" if t["hit"] > 0 else "accent"),
                )
            ),
            html.Td(f'{net:+.2f}', className=f"right mono {net_cls}"),
            html.Td(f'{t["cost_change"]:+.1f}m', className="right mono",
                    style={"color": INK_3}),
        ]))

    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"),
                html.Th("Transfer out"),
                html.Th("pts",   className="right"),
                html.Th(""),
                html.Th("Transfer in"),
                html.Th("pts",   className="right"),
                html.Th("Gross", className="right"),
                html.Th("Hit"),
                html.Th("Net",   className="right"),
                html.Th("£Δ",    className="right"),
            ])),
            html.Tbody(rows),
        ],
        className="data",
    )


layout = html.Div([

    # ── Page header ──────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Actions · Transfer Lab", className="page-eyebrow"),
            html.H1("Transfer Advisor", className="page-title serif"),
            html.P(
                "Enter the players currently in your squad to get ranked transfer "
                "recommendations, net of any hit penalty.",
                className="page-desc",
            ),
        ]),
    ], className="page-head"),

    # ── Input form ───────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div([
                html.Div("Your current squad", className="control-label"),
                dbc.Textarea(
                    id="transfers-squad-input",
                    placeholder="One player per line, e.g.\nKelleher\nN.Williams\nB.Fernandes\n...",
                    style={"height": "180px"},
                    className="form-control",
                ),
            ], style={"flex": "2 1 0"}),

            html.Div([
                html.Div([
                    html.Div("Free transfers", className="control-label"),
                    dbc.Select(
                        id="transfers-free",
                        options=[{"label": "1", "value": 1}, {"label": "2", "value": 2}],
                        value=1,
                    ),
                ], className="control-group"),
                html.Div([
                    html.Div("Bank (£m)", className="control-label"),
                    dbc.Input(
                        id="transfers-bank",
                        type="number", min=0, max=10, step=0.1, value=0.0,
                        className="form-control",
                    ),
                ], className="control-group"),
                html.Button(
                    "Find best transfers",
                    id="transfers-run-btn",
                    n_clicks=0,
                    className="btn-primary-custom",
                    style={"marginTop": "auto"},
                ),
                html.Div(id="transfers-error", style={"marginTop": "8px"}),
            ], style={"flex": "1 1 0", "display": "flex", "flexDirection": "column", "gap": "12px"}),

        ], style={"display": "flex", "gap": "20px", "alignItems": "flex-start"}),
    ], className="card card-body pad-lg", style={"marginBottom": "20px"}),

    # ── Results ──────────────────────────────────────────────
    dcc.Loading(
        id="transfers-loading",
        type="circle",
        color=ACCENT,
        children=html.Div(id="transfers-results"),
    ),

], className="page")


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

    import re
    names = [n.strip() for n in re.split(r"[\n,]+", squad_text) if n.strip()]
    if len(names) < 11:
        return None, dbc.Alert(
            f"Only {len(names)} players entered — need at least 11.", color="warning"
        )

    from rapidfuzz import process, fuzz
    players    = get_available_players()
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

    optimizer = get_optimizer()
    transfers = optimizer.recommend_transfers(
        current_squad_ids=squad_ids,
        players_df=players,
        free_transfers=int(free_transfers),
        bank=float(bank or 0),
    )

    profitable = [t for t in transfers if t["net_gain"] > 0]
    one_t = sum(1 for t in transfers if t["n_transfers"] == 1)
    two_t = sum(1 for t in transfers if t["n_transfers"] == 2)

    # Summary KPI strip
    summary = html.Div([
        html.Div([
            html.Div("Profitable transfers", className="kpi-label"),
            html.Div(str(len(profitable)), className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Best net gain", className="kpi-label"),
            html.Div(
                f'{transfers[0]["net_gain"]:+.2f}' if transfers else "—",
                className="kpi-value mono",
            ),
            html.Div([html.Span("pts")], className="kpi-delta"),
        ], className="kpi"),
        html.Div([
            html.Div("1-transfer options", className="kpi-label"),
            html.Div(str(one_t), className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("2-transfer options", className="kpi-label"),
            html.Div(str(two_t), className="kpi-value mono"),
        ], className="kpi"),
    ], className="kpi-grid")

    warning = dbc.Alert(
        f"Could not match: {', '.join(unmatched)} — excluded from squad.",
        color="warning",
    ) if unmatched else None

    table_card = html.Div([
        html.Div([
            html.Div("Top transfer recommendations", className="card-title"),
            html.Span(f"{len(transfers)} options evaluated", className="tag"),
        ], className="card-hd"),
        html.Div(
            _results_table(transfers),
            className="card-body flush",
        ),
    ], className="card")

    return html.Div([summary, warning or "", table_card]), None
