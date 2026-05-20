"""
app/pages/my_team.py

My Team: football pitch with click-to-replace suggestions.
Click any player to see ranked replacements (same position, budget-aware,
3-per-club cap). No change is applied until you explicitly confirm.
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dcc, html

from app.data_loader import get_available_players, get_latest_gw, get_players_with_predictions

dash.register_page(__name__, path="/my-team", name="My Team")

# ── Design constants ──────────────────────────────────────────────────────────
POS_COLOUR = {"GKP": "#c8a84a", "DEF": "#4a6fb5", "MID": "#3d7a52", "FWD": "#b5553a"}
POS_TEXT   = {"GKP": "#14130f", "DEF": "#fff",    "MID": "#fff",    "FWD": "#fff"}
POS_ORDER  = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
ACCENT     = "#3d7a52"
INK_3      = "#6e6c64"


# ── Pitch helpers ─────────────────────────────────────────────────────────────

def _row_xs_pct(n: int) -> list[float]:
    if n == 1:
        return [50.0]
    margins = {2: (25.0, 75.0), 3: (18.0, 82.0), 4: (12.0, 88.0), 5: (8.0, 92.0)}
    lo, hi = margins.get(n, (8.0, 92.0))
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _build_pitch(starters: list[dict], selected_id: int | None) -> html.Div:
    row_y = {"FWD": 13, "MID": 38, "DEF": 63, "GKP": 86}
    tokens = []
    idx = 0

    for pos in ["GKP", "DEF", "MID", "FWD"]:
        group = [p for p in starters if p["position"] == pos]
        n = len(group)
        if not n:
            continue

        xs    = _row_xs_pct(n)
        y_pct = row_y[pos]
        fill  = POS_COLOUR[pos]
        txt   = POS_TEXT[pos]

        for i, p in enumerate(group):
            pid       = p["player_id"]
            name      = p["web_name"]
            pts       = p.get("predicted_pts", 0.0)
            team_code = str(p.get("team_name", ""))[:3].upper()
            is_cap    = bool(p.get("is_captain"))
            is_vice   = bool(p.get("is_vice_captain"))
            status    = p.get("status", "a")
            is_sel    = pid == selected_id

            delay = 80 + idx * 90
            idx  += 1
            disp  = name if len(name) <= 11 else name[:10] + "."

            jersey_cls = "player-jersey"
            if is_cap:    jersey_cls += " captain"
            elif is_vice: jersey_cls += " vice"

            token_cls = "pitch-player enter mt-player"
            if is_sel:                  token_cls += " mt-selected"
            if status in ("i", "d", "s"): token_cls += " mt-status-warn"

            tokens.append(html.Div(
                [
                    html.Div(team_code, className=jersey_cls,
                             style={"background": fill, "color": txt}),
                    html.Div(disp, className="player-name"),
                    html.Div(f"{pts:.1f}", className="player-pts"),
                ],
                id={"type": "mt-token", "index": pid},
                className=token_cls,
                style={
                    "left":              f"{xs[i]}%",
                    "top":               f"{y_pct}%",
                    "animationDelay":    f"{delay}ms",
                    "animationFillMode": "both",
                },
                n_clicks=0,
            ))

    lines = html.Div([
        html.Div(className="pl-border"),
        html.Div(className="pl-halfway"),
        html.Div(className="pl-circle"),
        html.Div(className="pl-pen-top"),
        html.Div(className="pl-pen-bot"),
    ])
    return html.Div([lines, *tokens], className="pitch-wrap")


def _build_bench(bench: list[dict], selected_id: int | None) -> html.Div:
    tokens = []
    for p in bench:
        pid       = p["player_id"]
        name      = p["web_name"]
        pts       = p.get("predicted_pts", 0.0)
        pos       = p["position"]
        team_code = str(p.get("team_name", ""))[:3].upper()
        is_sel    = pid == selected_id
        status    = p.get("status", "a")
        fill      = POS_COLOUR[pos]
        txt       = POS_TEXT[pos]
        disp      = name if len(name) <= 11 else name[:10] + "."

        token_cls = "mt-bench-token"
        if is_sel:                  token_cls += " mt-selected"
        if status in ("i", "d", "s"): token_cls += " mt-status-warn"

        tokens.append(html.Div(
            [
                html.Div(team_code, className="player-jersey",
                         style={"background": fill, "color": txt}),
                html.Div(disp, className="player-name"),
                html.Div(f"{pts:.1f}", className="player-pts"),
            ],
            id={"type": "mt-token", "index": pid},
            className=token_cls,
            n_clicks=0,
        ))

    return html.Div(
        [
            html.Div("Bench", className="bench-label"),
            html.Div(tokens, className="bench-strip"),
        ],
        className="bench-wrap",
    )


def _build_panel(
    selected: dict,
    suggestions: list[dict],
    bank: float,
    free_transfers: int,
) -> html.Div:
    hit = free_transfers < 1

    rows = []
    for s in suggestions:
        dc   = s["cost_delta"]
        dp   = s["pts_delta"]
        dc_s = f"{'−' if dc < 0 else '+'}£{abs(dc):.1f}m"
        dp_s = f"{dp:+.1f}"
        dc_cl = "mt-delta-good" if dc <= 0 else "mt-delta-bad"
        dp_cl = "mt-delta-good" if dp > 0  else "mt-delta-bad"

        rows.append(html.Div(
            [
                html.Div([
                    html.Div(s["web_name"],          className="sugg-name"),
                    html.Div(s.get("team_name", ""), className="sugg-team"),
                ], className="sugg-info"),
                html.Div(f"£{s['now_cost']:.1f}m",     className="sugg-cost mono"),
                html.Div(f"{s['predicted_pts']:.1f}",   className="sugg-pts mono"),
                html.Div(dc_s, className=f"sugg-delta mono {dc_cl}"),
                html.Div(dp_s, className=f"sugg-delta mono {dp_cl}"),
                html.Button(
                    "Apply" if not hit else "Apply (−4)",
                    id={"type": "mt-apply-btn", "index": s["player_id"]},
                    className="btn-apply" + (" btn-apply-hit" if hit else ""),
                    n_clicks=0,
                ),
            ],
            className="sugg-row",
        ))

    body_children = rows or [
        html.Div("No eligible replacements found.",
                 style={"padding": "16px", "color": INK_3})
    ]

    return html.Div(
        [
            html.Div(
                [
                    html.Div([
                        html.Div([
                            html.Span("Replacing ", className="panel-label"),
                            html.Span(selected["web_name"], className="panel-player"),
                        ]),
                        html.Div(
                            [
                                html.Span(f"£{selected['now_cost']:.1f}m", className="mono"),
                                html.Span(" · "),
                                html.Span(f"£{bank:.1f}m in bank",
                                          className="mono", style={"color": ACCENT}),
                            ],
                            className="panel-meta",
                        ),
                    ]),
                    html.Button("✕", id="mt-close-panel", className="panel-close", n_clicks=0),
                ],
                className="panel-hd",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Player",  className="sugg-h-name"),
                            html.Span("Cost",    className="sugg-h-num mono"),
                            html.Span("Pts",     className="sugg-h-num mono"),
                            html.Span("Δ£",      className="sugg-h-num mono"),
                            html.Span("Δpts",    className="sugg-h-num mono"),
                            html.Span("",        className="sugg-h-btn"),
                        ],
                        className="sugg-header",
                    ),
                    *body_children,
                ],
                className="panel-body",
            ),
        ],
        className="replacement-panel",
    )


def _import_form() -> html.Div:
    return html.Div(
        [
            html.Div("Import your squad", className="setup-title"),
            html.P(
                [
                    "Enter your FPL team ID to auto-load your 15-man squad. "
                    "Find it in the URL when viewing your team on the FPL website: ",
                    html.Br(),
                    html.Span(
                        "fantasy.premierleague.com/entry/",
                        className="mono",
                        style={"color": ACCENT},
                    ),
                    html.Span("XXXXXXX", className="mono",
                              style={"color": ACCENT, "fontWeight": 700}),
                    html.Span("/event/XX", className="mono", style={"color": ACCENT}),
                ],
                className="setup-desc",
            ),
            html.Div(
                [
                    html.Div([
                        html.Div("FPL Team ID", className="control-label"),
                        dbc.Input(
                            id="mt-team-id-input",
                            type="number",
                            min=1,
                            placeholder="e.g. 11405847",
                            className="form-control",
                        ),
                    ], className="control-group"),
                    html.Div([
                        html.Div("Free transfers", className="control-label"),
                        dbc.Input(
                            id="mt-ft-select",
                            type="number",
                            min=0,
                            max=10,
                            step=1,
                            value=1,
                            className="form-control",
                            style={"width": "80px"},
                        ),
                    ], className="control-group"),
                    html.Button(
                        "Import team",
                        id="mt-import-btn",
                        className="btn-primary-custom",
                        n_clicks=0,
                    ),
                    html.Div(id="mt-import-err"),
                ],
                className="setup-controls",
            ),
        ],
        className="card card-body pad-lg setup-card",
    )


# ── Layout ────────────────────────────────────────────────────────────────────

layout = html.Div(
    [
        dcc.Store(id="mt-selected",     data=None),
        dcc.Store(id="mt-refresh",      data=0),
        dcc.Store(id="mt-pending-xfer", data=None),
        dcc.ConfirmDialog(id="mt-confirm", message=""),

        html.Div(
            [
                html.Div([
                    html.Div("Actions · My Team", className="page-eyebrow"),
                    html.H1("My Team", className="page-title serif"),
                    html.P(
                        "Click any player on the pitch to see ranked replacements. "
                        "Suggestions follow FPL rules — budget, position, 3-per-club. "
                        "No change is applied until you confirm.",
                        className="page-desc",
                    ),
                ]),
            ],
            className="page-head",
        ),

        html.Div(id="mt-body"),
    ],
    className="page",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("mt-body", "children"),
    Input("mt-refresh",  "data"),
    Input("mt-selected", "data"),
)
def render_body(_, selected_id):
    from app.team_manager import load_team, get_replacement_suggestions

    team = load_team()
    if team is None:
        return _import_form()

    all_players = get_players_with_predictions()
    avail       = get_available_players()

    enriched = []
    for p in team["players"]:
        pid = p["player_id"]
        row = all_players[all_players["player_id"] == pid]
        if row.empty:
            continue
        d = row.iloc[0].to_dict()
        d["is_captain"]      = bool(p["is_captain"])
        d["is_vice_captain"] = bool(p["is_vice_captain"])
        d["bench_order"]     = p["bench_order"]
        d["selling_price"]   = p["selling_price"]
        enriched.append(d)

    starters = sorted(
        [p for p in enriched if p["bench_order"] is None],
        key=lambda p: (POS_ORDER[p["position"]], -p.get("predicted_pts", 0)),
    )
    bench = sorted(
        [p for p in enriched if p["bench_order"] is not None],
        key=lambda p: p["bench_order"],
    )

    bank           = team["bank"]
    free_transfers = team["free_transfers"]
    squad_ids      = [p["player_id"] for p in enriched]

    pred_xi = sum(
        p.get("predicted_pts", 0) * (2 if p["is_captain"] else 1)
        for p in starters
    )

    ft_cls = "mt-ft-good" if free_transfers > 0 else "mt-ft-none"

    kpi_strip = html.Div(
        [
            html.Div(
                [
                    html.Div([
                        html.Div("Bank", className="kpi-label"),
                        html.Div([f"£{bank:.1f}", html.Span("m", className="unit")],
                                 className="kpi-value mono"),
                    ], className="kpi"),
                    html.Div([
                        html.Div("Free transfers", className="kpi-label"),
                        html.Div(str(free_transfers), className=f"kpi-value mono {ft_cls}"),
                    ], className="kpi"),
                    html.Div([
                        html.Div("Expected GW pts", className="kpi-label"),
                        html.Div([f"{pred_xi:.1f}", html.Span("pts", className="unit")],
                                 className="kpi-value mono"),
                    ], className="kpi"),
                    html.Div([
                        html.Div("Predicting", className="kpi-label"),
                        html.Div(f"GW {get_latest_gw() + 1}", className="kpi-value mono"),
                    ], className="kpi"),
                ],
                className="kpi-grid",
                style={"flex": "1", "marginBottom": 0},
            ),
            html.Div(
                html.Button(
                    "↺  Re-import",
                    id="mt-reimport-btn",
                    className="btn-secondary-custom",
                    n_clicks=0,
                ),
                style={"display": "flex", "alignItems": "center", "paddingLeft": "12px"},
            ),
        ],
        style={"display": "flex", "alignItems": "stretch", "marginBottom": "20px"},
    )

    pitch_col = html.Div(
        [_build_pitch(starters, selected_id), _build_bench(bench, selected_id)],
        style={"flex": "1 1 0", "minWidth": 0},
    )

    if selected_id is not None:
        sel_list = [p for p in enriched if p["player_id"] == selected_id]
        if sel_list:
            suggestions = get_replacement_suggestions(
                player_id=selected_id,
                squad_player_ids=squad_ids,
                bank=bank,
                players_df=avail,
            )
            panel_div = html.Div(
                _build_panel(sel_list[0], suggestions, bank, free_transfers),
                style={"flex": "0 0 360px"},
            )
        else:
            panel_div = html.Div(style={"display": "none"})
    else:
        panel_div = html.Div(style={"display": "none"})

    main = html.Div(
        [pitch_col, panel_div],
        style={"display": "flex", "gap": "18px", "alignItems": "flex-start"},
    )
    return html.Div([kpi_strip, main])


@callback(
    Output("mt-selected", "data"),
    Input({"type": "mt-token", "index": ALL}, "n_clicks"),
    State("mt-selected", "data"),
    prevent_initial_call=True,
)
def on_player_click(n_clicks_list, current):
    from dash import ctx
    if not ctx.triggered or not any(n for n in n_clicks_list if n):
        return current
    tid = ctx.triggered_id
    if not tid:
        return current
    clicked = tid["index"]
    return None if clicked == current else clicked


@callback(
    Output("mt-selected", "data", allow_duplicate=True),
    Input("mt-close-panel", "n_clicks"),
    prevent_initial_call=True,
)
def close_panel(_):
    return None


@callback(
    Output("mt-pending-xfer", "data"),
    Output("mt-confirm",      "displayed"),
    Output("mt-confirm",      "message"),
    Input({"type": "mt-apply-btn", "index": ALL}, "n_clicks"),
    State("mt-selected", "data"),
    prevent_initial_call=True,
)
def stage_transfer(n_clicks_list, selected_id):
    from dash import ctx
    if not ctx.triggered or not any(n for n in n_clicks_list if n):
        return dash.no_update, False, ""
    tid = ctx.triggered_id
    if not tid or selected_id is None:
        return dash.no_update, False, ""

    in_pid     = tid["index"]
    all_p      = get_players_with_predictions()
    out_row    = all_p[all_p["player_id"] == selected_id]
    in_row     = all_p[all_p["player_id"] == in_pid]
    if out_row.empty or in_row.empty:
        return dash.no_update, False, ""

    out_name = out_row.iloc[0]["web_name"]
    in_name  = in_row.iloc[0]["web_name"]
    in_cost  = float(in_row.iloc[0]["now_cost"])
    msg = f"Transfer {out_name} → {in_name} (£{in_cost:.1f}m). Confirm?"

    return {"out": selected_id, "in": in_pid, "cost": in_cost}, True, msg


@callback(
    Output("mt-refresh",  "data",  allow_duplicate=True),
    Output("mt-selected", "data",  allow_duplicate=True),
    Input("mt-confirm",   "submit_n_clicks"),
    State("mt-pending-xfer", "data"),
    State("mt-refresh",      "data"),
    prevent_initial_call=True,
)
def confirm_transfer(submit_n, pending, refresh_count):
    if not submit_n or not pending:
        return dash.no_update, dash.no_update
    from app.team_manager import apply_transfer
    apply_transfer(
        out_player_id=int(pending["out"]),
        in_player_id=int(pending["in"]),
        in_player_cost=float(pending["cost"]),
    )
    return (refresh_count or 0) + 1, None


@callback(
    Output("mt-refresh",   "data",  allow_duplicate=True),
    Output("mt-import-err", "children"),
    Input("mt-import-btn",    "n_clicks"),
    State("mt-team-id-input", "value"),
    State("mt-ft-select",     "value"),
    State("mt-refresh",       "data"),
    prevent_initial_call=True,
)
def import_team(_, team_id, free_transfers, refresh_count):
    if not team_id:
        return dash.no_update, dbc.Alert("Enter your FPL team ID.", color="warning")

    team_id = int(team_id)
    if team_id < 1000:
        return dash.no_update, dbc.Alert(
            "That doesn't look like a valid FPL team ID (should be a large number, "
            "e.g. 11405847). Find yours in the URL on the FPL website.",
            color="warning",
        )

    from app.team_manager import fetch_squad_from_fpl, save_team
    try:
        gw   = get_latest_gw()
        data = fetch_squad_from_fpl(team_id, gw)
    except Exception as e:
        return dash.no_update, dbc.Alert(f"Could not fetch team: {e}", color="danger")

    if len(data["picks"]) != 15:
        return dash.no_update, dbc.Alert(
            f"Unexpected response from FPL (got {len(data['picks'])} players instead of 15). "
            "Double-check your team ID.",
            color="danger",
        )

    all_p = get_players_with_predictions()
    price_map = all_p.set_index("player_id")["now_cost"].to_dict()

    picks = []
    for pick in data["picks"]:
        pos_num   = pick["position"]
        bench_ord = (pos_num - 11) if pos_num > 11 else None
        # FPL public picks endpoint omits price fields; fall back to current market price
        price = price_map.get(pick["element"], 0.0)
        picks.append({
            "player_id":       pick["element"],
            "purchase_price":  price,
            "selling_price":   price,
            "is_captain":      int(pick["is_captain"]),
            "is_vice_captain": int(pick["is_vice_captain"]),
            "bench_order":     bench_ord,
        })

    save_team(
        picks=picks,
        bank=data["bank"],
        free_transfers=int(free_transfers),
        fpl_team_id=int(team_id),
    )
    return (refresh_count or 0) + 1, None


@callback(
    Output("mt-refresh",     "data", allow_duplicate=True),
    Input("mt-reimport-btn", "n_clicks"),
    State("mt-refresh",      "data"),
    prevent_initial_call=True,
)
def reimport_team(_, refresh_count):
    from app.team_manager import delete_team
    delete_team()
    return (refresh_count or 0) + 1
