"""
app/pages/my_team.py

My Team: football pitch with click-to-replace suggestions.

Architecture:
  - render_pitch   fires only on mt-refresh  → stable; no re-render on click
  - render_panel   fires on mt-selected      → only the side panel updates
  - clientside CB  fires on mt-selected      → adds/removes mt-selected CSS class
    (avoids a full server round-trip just to highlight a token)
"""
from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dcc, html

from app.data_loader import get_available_players, get_latest_gw, get_players_with_predictions

dash.register_page(__name__, path="/my-team", name="My Team")

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


def _build_pitch(starters: list[dict]) -> html.Div:
    """Render 11 starters on pitch. Selected state is applied client-side."""
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
            pid    = p["player_id"]
            name   = p["web_name"]
            pts    = p.get("predicted_pts", 0.0)
            tcode  = str(p.get("team_name", ""))[:3].upper()
            is_cap = bool(p.get("is_captain"))
            is_vc  = bool(p.get("is_vice_captain"))
            status = p.get("status", "a")
            delay  = 80 + idx * 90
            idx   += 1
            disp   = name if len(name) <= 11 else name[:10] + "."

            jersey_cls = "player-jersey"
            if is_cap:  jersey_cls += " captain"
            elif is_vc: jersey_cls += " vice"

            token_cls = "pitch-player enter mt-player"
            if status in ("i", "d", "s"):
                token_cls += " mt-status-warn"

            tokens.append(html.Button(
                [
                    html.Div(tcode, className=jersey_cls,
                             style={"background": fill, "color": txt}),
                    html.Div(disp, className="player-name"),
                    html.Div(f"{pts:.1f}", className="player-pts"),
                ],
                id={"type": "mt-token", "index": pid},
                className=token_cls,
                style={
                    "left": f"{xs[i]}%", "top": f"{y_pct}%",
                    "animationDelay": f"{delay}ms", "animationFillMode": "both",
                },
                n_clicks=0,
                **{"data-pid": str(pid)},
            ))

    lines = html.Div([
        html.Div(className="pl-border"),
        html.Div(className="pl-halfway"),
        html.Div(className="pl-circle"),
        html.Div(className="pl-pen-top"),
        html.Div(className="pl-pen-bot"),
    ])
    return html.Div([lines, *tokens], className="pitch-wrap")


def _build_bench(bench: list[dict]) -> html.Div:
    tokens = []
    for p in bench:
        pid    = p["player_id"]
        name   = p["web_name"]
        pts    = p.get("predicted_pts", 0.0)
        pos    = p["position"]
        tcode  = str(p.get("team_name", ""))[:3].upper()
        status = p.get("status", "a")
        fill   = POS_COLOUR[pos]
        txt    = POS_TEXT[pos]
        disp   = name if len(name) <= 11 else name[:10] + "."

        token_cls = "mt-bench-token"
        if status in ("i", "d", "s"):
            token_cls += " mt-status-warn"

        tokens.append(html.Button(
            [
                html.Div(pos, className="mt-pos-label"),
                html.Div(tcode, className="player-jersey",
                         style={"background": fill, "color": txt}),
                html.Div(disp, className="player-name"),
                html.Div(f"{pts:.1f}", className="player-pts"),
            ],
            id={"type": "mt-token", "index": pid},
            className=token_cls,
            n_clicks=0,
            **{"data-pid": str(pid)},
        ))

    return html.Div(
        [html.Div("Bench", className="bench-label"), html.Div(tokens, className="bench-strip")],
        className="bench-wrap",
    )


def _build_panel(
    selected: dict,
    suggestions: list[dict],
    bank: float,
    free_transfers: int,
    swap_section=None,
    reversal_pid: int | None = None,
) -> html.Div:
    hit      = free_transfers < 1
    pts_head = "Δpts (net)" if hit else "Δpts"

    rows = []
    for s in suggestions:
        is_reversal = s["player_id"] == reversal_pid
        dc   = s["cost_delta"]
        dp   = s["pts_delta"]
        dc_s = f"{'−' if dc < 0 else '+'}£{abs(dc):.1f}m"
        dp_s = f"{dp:+.1f}"
        dc_cl = "mt-delta-good" if dc <= 0 else "mt-delta-bad"
        dp_cl = "mt-delta-good" if dp > 0  else "mt-delta-bad"

        if is_reversal:
            btn_label = "↩ Undo"
            btn_cls   = "btn-apply btn-apply-undo"
        elif hit:
            btn_label = "Apply (−4)"
            btn_cls   = "btn-apply btn-apply-hit"
        else:
            btn_label = "Apply"
            btn_cls   = "btn-apply"

        rows.append(html.Div(
            [
                html.Div([
                    html.Div(s["web_name"],          className="sugg-name"),
                    html.Div(s.get("team_name", ""), className="sugg-team"),
                ], className="sugg-info"),
                html.Div(f"£{s['now_cost']:.1f}m",   className="sugg-cost mono"),
                html.Div(f"{s['predicted_pts']:.1f}", className="sugg-pts mono"),
                html.Div(dc_s, className=f"sugg-delta mono {dc_cl}"),
                html.Div(dp_s, className=f"sugg-delta mono {dp_cl}"),
                html.Button(
                    btn_label,
                    id={"type": "mt-apply-btn", "index": s["player_id"]},
                    className=btn_cls,
                    n_clicks=0,
                ),
            ],
            className="sugg-row",
        ))

    body = rows or [html.Div("No eligible replacements.",
                              style={"padding": "16px", "color": INK_3})]

    pos = selected.get("position", "")

    return html.Div(
        [
            html.Div(
                [
                    html.Div([
                        html.Div([
                            html.Span("Replacing ", className="panel-label"),
                            html.Span(selected["web_name"], className="panel-player"),
                            html.Span(f" · {pos}", className="panel-pos"),
                        ]),
                        html.Div([
                            html.Span(f"£{selected['now_cost']:.1f}m", className="mono"),
                            html.Span(" · "),
                            html.Span(f"£{bank:.1f}m in bank",
                                      className="mono", style={"color": ACCENT}),
                        ], className="panel-meta"),
                    ]),
                    html.Button("✕", id="mt-close-panel", className="panel-close", n_clicks=0),
                ],
                className="panel-hd",
            ),
            html.Div(
                [
                    swap_section,
                    html.Div(
                        [
                            html.Span("Player",  className="sugg-h-name"),
                            html.Span("Cost",    className="sugg-h-num mono"),
                            html.Span("xPts",    className="sugg-h-num mono"),
                            html.Span("Δ£",      className="sugg-h-num mono"),
                            html.Span(pts_head,  className="sugg-h-num mono"),
                            html.Span("",        className="sugg-h-btn"),
                        ],
                        className="sugg-header",
                    ),
                    *body,
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
                    "Find your team ID in the FPL website URL: ",
                    html.Br(),
                    html.Code("fantasy.premierleague.com/entry/",
                              style={"color": ACCENT}),
                    html.Code("XXXXXXX", style={"color": ACCENT, "fontWeight": 700}),
                    html.Code("/event/XX", style={"color": ACCENT}),
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
                            className="form-control no-spinner",
                        ),
                    ], className="control-group"),
                    html.Div([
                        html.Div("Free transfers", className="control-label"),
                        dbc.Input(
                            id="mt-ft-select",
                            type="number",
                            min=0, max=10, step=1, value=1,
                            className="form-control",
                            style={"width": "80px"},
                        ),
                    ], className="control-group"),
                    html.Button("Import team", id="mt-import-btn",
                                className="btn-primary-custom", n_clicks=0),
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
        dcc.Store(id="mt-selected",          data=None),
        dcc.Store(id="mt-click-relay",       data=None),
        dcc.Store(id="mt-close-relay",       data=None),
        dcc.Store(id="mt-refresh",           data=0),
        dcc.Store(id="mt-pending-xfer",      data=None),
        dcc.Store(id="mt-undo-stack",        data=[]),
        dcc.Store(id="mt-pts-delta",         data=0.0),
        dcc.Store(id="mt-xfer-open",        data=False),
        dcc.Store(id="mt-xfer-btn-relay",   data=None),
        dcc.Store(id="mt-xfer-close-relay", data=None),
        dcc.Store(id="mt-sel-dummy"),
        dcc.Store(id="mt-click-dummy"),
        dcc.Interval(id="mt-click-poll", interval=150, n_intervals=0),
        dcc.ConfirmDialog(id="mt-confirm", message=""),

        html.Div(
            [
                html.Div([
                    html.Div("Actions · My Team", className="page-eyebrow"),
                    html.H1("My Team", className="page-title serif"),
                    html.P(
                        "Click any player to see ranked replacements — budget, position, "
                        "and 3-per-club rules applied. Nothing changes until you confirm.",
                        className="page-desc",
                    ),
                ]),
            ],
            className="page-head",
        ),

        # KPI bar + re-import button
        html.Div(id="mt-kpi-bar"),

        # Two-column: pitch (fixed width) + panel (flexible)
        html.Div(
            [
                html.Div(id="mt-pitch-area", style={"flex": "0 0 400px", "minWidth": 0}),
                html.Div(id="mt-panel-area", style={"flex": "1 1 0",    "minWidth": 0}),
            ],
            style={"display": "flex", "gap": "16px", "alignItems": "flex-start"},
        ),

        # Best-transfers recommendation panel (shown/hidden via mt-xfer-open)
        html.Div(id="mt-xfer-rec-area"),
    ],
    className="page",
)


# ── Clientside callbacks ──────────────────────────────────────────────────────

# 1. Highlight the selected token using data-pid attribute (reliable in Dash 4 DOM)
dash.clientside_callback(
    """
    function(selected_id) {
        document.querySelectorAll('[data-pid]').forEach(function(el) {
            el.classList.remove('mt-selected');
        });
        if (selected_id !== null && selected_id !== undefined) {
            var el = document.querySelector('[data-pid="' + selected_id + '"]');
            if (el) el.classList.add('mt-selected');
        }
        return null;
    }
    """,
    Output("mt-sel-dummy", "data"),
    Input("mt-selected", "data"),
)

# 2. Attach a delegated click listener to the pitch area whenever the pitch re-renders.
#    Same-player click flashes the panel instead of deselecting.
dash.clientside_callback(
    """
    function(refresh) {
        window._mtClickPid = undefined;
        setTimeout(function() {
            var container = document.getElementById('mt-pitch-area');
            if (!container) return;
            if (container._mtClickBound) return;
            container._mtClickBound = true;
            container.addEventListener('click', function(e) {
                var el = e.target;
                while (el && el !== container) {
                    if (el.hasAttribute('data-pid')) {
                        var pid = parseInt(el.getAttribute('data-pid'), 10);
                        if (!isNaN(pid)) {
                            if (el.classList.contains('mt-selected')) {
                                var panel = document.querySelector('.replacement-panel');
                                if (panel) {
                                    panel.classList.remove('mt-panel-flash');
                                    void panel.offsetWidth;
                                    panel.classList.add('mt-panel-flash');
                                }
                            } else {
                                window._mtClickPid = pid;
                            }
                        }
                        return;
                    }
                    el = el.parentElement;
                }
            });
        }, 300);
        return null;
    }
    """,
    Output("mt-click-dummy", "data"),
    Input("mt-refresh", "data"),
)

# 4. Route close-button clicks through a relay store (primary output, no allow_duplicate)
#    so the single update_selected server callback can own mt-selected exclusively.
dash.clientside_callback(
    """
    function(n) {
        if (!n) return window.dash_clientside.no_update;
        return n;
    }
    """,
    Output("mt-close-relay", "data"),
    Input("mt-close-panel", "n_clicks"),
    prevent_initial_call=True,
)

# 5. Relay mt-xfer-btn (dynamic) → static store so toggle_xfer_panel has no dynamic Inputs.
dash.clientside_callback(
    """
    function(n) {
        if (!n) return window.dash_clientside.no_update;
        return n;
    }
    """,
    Output("mt-xfer-btn-relay", "data"),
    Input("mt-xfer-btn", "n_clicks"),
    prevent_initial_call=True,
)

# 6. Route xfer-rec close button through its own relay store.
dash.clientside_callback(
    """
    function(n) {
        if (!n) return window.dash_clientside.no_update;
        return n;
    }
    """,
    Output("mt-xfer-close-relay", "data"),
    Input("mt-xfer-close", "n_clicks"),
    prevent_initial_call=True,
)

# 3. Poll every 150 ms; when a click has been queued, push it to the relay store.
#    Writing to mt-click-relay (primary output, no allow_duplicate) guarantees that
#    the downstream server callback fires reliably in Dash 4.
dash.clientside_callback(
    """
    function(n) {
        if (window._mtClickPid === undefined || window._mtClickPid === null) {
            return window.dash_clientside.no_update;
        }
        var pid = window._mtClickPid;
        window._mtClickPid = undefined;
        return pid;
    }
    """,
    Output("mt-click-relay", "data"),
    Input("mt-click-poll", "n_intervals"),
    prevent_initial_call=True,
)


# ── Server callbacks ──────────────────────────────────────────────────────────

@callback(
    Output("mt-selected", "data"),   # sole writer — no allow_duplicate needed anywhere
    Input("mt-click-relay",  "data"),
    Input("mt-close-relay",  "data"),
    prevent_initial_call=True,
)
def update_selected(clicked_pid, close_signal):
    from dash import ctx
    trig = ctx.triggered_id
    if trig == "mt-click-relay":
        if clicked_pid is None:
            return dash.no_update
        return clicked_pid          # no toggle; X button or new player closes
    if trig == "mt-close-relay":
        if not close_signal:
            return dash.no_update
        return None
    return dash.no_update


def _load_enriched():
    """Load team from DB and enrich with prediction data. Returns (team, enriched) or (None, [])."""
    from app.team_manager import load_team
    team = load_team()
    if team is None:
        return None, []

    all_players = get_players_with_predictions()
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
        d["row_id"]          = p["id"]   # stable DB row id — used for positional sort
        enriched.append(d)

    return team, enriched


def _valid_bench_to_xi(enriched: list[dict], bench_p: dict) -> list[dict]:
    """XI players that bench_p can swap into without breaking the formation."""
    from collections import Counter
    starters   = [p for p in enriched if p["bench_order"] is None]
    bench_pos  = bench_p["position"]
    valid = []
    for xi in starters:
        new_pos = Counter(p["position"] for p in starters if p["player_id"] != xi["player_id"])
        new_pos[bench_pos] += 1
        if (new_pos["GKP"] == 1 and new_pos["DEF"] >= 3 and
                new_pos["MID"] >= 2 and new_pos["FWD"] >= 1):
            valid.append(xi)
    return valid


def _valid_xi_to_bench(enriched: list[dict], xi_p: dict) -> list[dict]:
    """Bench players that can validly replace xi_p in the XI."""
    from collections import Counter
    starters = [p for p in enriched if p["bench_order"] is None]
    bench    = sorted([p for p in enriched if p["bench_order"] is not None],
                      key=lambda p: p["bench_order"])
    valid = []
    for bp in bench:
        new_pos = Counter(p["position"] for p in starters if p["player_id"] != xi_p["player_id"])
        new_pos[bp["position"]] += 1
        if (new_pos["GKP"] == 1 and new_pos["DEF"] >= 3 and
                new_pos["MID"] >= 2 and new_pos["FWD"] >= 1):
            valid.append(bp)
    return valid


def _build_swap_section(
    title: str,
    players: list[dict],
    btn_label: str,
    selected_pts: float = 0.0,
    selected_is_bench: bool = False,
) -> html.Div | None:
    if not players:
        return None
    rows = []
    for p in players:
        fill = POS_COLOUR[p["position"]]
        txt  = POS_TEXT[p["position"]]
        pts  = p.get("predicted_pts", 0.0)
        bench_tag = (f"  bench #{p['bench_order']}" if p.get("bench_order") else "")

        # delta = incoming xi pts − outgoing xi pts
        if selected_is_bench:
            # selected (bench) goes into XI, p (XI) goes to bench
            delta = selected_pts - pts
        else:
            # p (bench) goes into XI, selected (XI) goes to bench
            delta = pts - selected_pts

        delta_s  = f"{delta:+.1f}"
        delta_cl = "mt-delta-good" if delta > 0 else "mt-delta-bad"

        rows.append(html.Div([
            html.Div(str(p.get("team_name", ""))[:3].upper(),
                     className="swap-jersey", style={"background": fill, "color": txt}),
            html.Div([
                html.Span(p["web_name"], className="swap-name"),
                html.Span(bench_tag,     className="swap-bench-tag"),
            ], className="swap-info"),
            html.Span(delta_s, className=f"swap-pts mono {delta_cl}"),
            html.Button(
                btn_label,
                id={"type": "mt-swap-btn", "index": p["player_id"]},
                className="btn-swap",
                n_clicks=0,
            ),
        ], className="swap-row"))

    return html.Div([
        html.Div(title, className="swap-section-title"),
        *rows,
    ], className="swap-section")


@callback(
    Output("mt-kpi-bar",    "children"),
    Output("mt-pitch-area", "children"),
    Input("mt-refresh", "data"),
    State("mt-undo-stack", "data"),
    State("mt-pts-delta",  "data"),
)
def render_pitch(refresh_count, undo_stack, pts_delta):
    team, enriched = _load_enriched()
    if team is None:
        return None, _import_form()

    starters = sorted(
        [p for p in enriched if p["bench_order"] is None],
        key=lambda p: (POS_ORDER.get(p["position"], 9), p.get("row_id", 0)),
    )
    bench = sorted(
        [p for p in enriched if p["bench_order"] is not None],
        key=lambda p: p["bench_order"],
    )

    bank           = team["bank"]
    free_transfers = team["free_transfers"]
    pred_xi = sum(
        p.get("predicted_pts", 0) * (2 if p["is_captain"] else 1)
        for p in starters
    )

    ft_cls = "mt-ft-good" if free_transfers > 0 else "mt-ft-none"
    delta  = pts_delta or 0.0

    kpi_bar = html.Div(
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
                [
                    html.Div(
                        [
                            html.Span("Transfer impact  ", className="mt-impact-label"),
                            html.Span(
                                f"{delta:+.1f}pts",
                                className="mt-impact-val "
                                          + ("mt-delta-good" if delta >= 0 else "mt-delta-bad"),
                            ),
                        ],
                        className="mt-impact",
                    ) if delta != 0.0 else None,
                    html.Div(
                        [
                            html.Button(
                                "↩ Undo", id="mt-undo-btn",
                                className="btn-secondary-custom mt-undo-btn",
                                n_clicks=0,
                            ) if undo_stack else None,
                            html.Button(
                                "⟲ Revert squad", id="mt-revert-btn",
                                className="btn-secondary-custom", n_clicks=0,
                            ) if team.get("has_original") else None,
                            html.Button(
                                "Best transfers", id="mt-xfer-btn",
                                className="btn-secondary-custom", n_clicks=0,
                            ),
                            html.Button(
                                "↺  Re-import", id="mt-reimport-btn",
                                className="btn-secondary-custom", n_clicks=0,
                            ),
                        ],
                        style={"display": "flex", "gap": "8px", "flexWrap": "wrap"},
                    ),
                ],
                style={
                    "display": "flex", "flexDirection": "column",
                    "justifyContent": "center", "alignItems": "flex-end",
                    "gap": "6px", "paddingLeft": "16px",
                },
            ),
        ],
        style={"display": "flex", "alignItems": "stretch", "marginBottom": "16px"},
    )

    pitch_area = html.Div([_build_pitch(starters), _build_bench(bench)])
    return kpi_bar, pitch_area


@callback(
    Output("mt-panel-area", "children"),
    Input("mt-selected",   "data"),
    Input("mt-refresh",    "data"),
    State("mt-undo-stack", "data"),
)
def render_panel(selected_id, _, undo_stack):
    if selected_id is None:
        return html.Div(
            "Click any player to see replacement suggestions or bench swaps.",
            className="panel-placeholder",
        )

    try:
        from app.team_manager import get_replacement_suggestions
        team, enriched = _load_enriched()
        if team is None:
            return html.Div(
                "Click any player to see replacement suggestions or bench swaps.",
                className="panel-placeholder",
            )

        sel_list = [p for p in enriched if p["player_id"] == selected_id]
        if not sel_list:
            return html.Div(
                "Click any player to see replacement suggestions or bench swaps.",
                className="panel-placeholder",
            )

        sel      = sel_list[0]
        is_bench = sel["bench_order"] is not None

        sel_pts = sel.get("predicted_pts", 0.0)
        if is_bench:
            swap_section = _build_swap_section(
                "Move into XI", _valid_bench_to_xi(enriched, sel), "↑ Into XI",
                selected_pts=sel_pts, selected_is_bench=True,
            )
        else:
            swap_section = _build_swap_section(
                "Move to bench", _valid_xi_to_bench(enriched, sel), "↓ To bench",
                selected_pts=sel_pts, selected_is_bench=False,
            )

        # Determine if any suggestion is a free reversal of the last transfer
        reversal_pid = None
        stack = undo_stack or []
        if stack and selected_id == stack[-1]["in_player_id"]:
            reversal_pid = stack[-1]["out_player_id"]

        squad_ids   = [p["player_id"] for p in enriched]
        avail       = get_available_players()
        suggestions = get_replacement_suggestions(
            player_id=selected_id,
            squad_player_ids=squad_ids,
            bank=team["bank"],
            players_df=avail,
            free_transfers=team["free_transfers"],
        )

        # Strip the -4 penalty from the reversal candidate's displayed pts_delta
        if reversal_pid and team["free_transfers"] < 1:
            suggestions = [
                {**s, "pts_delta": round(s["pts_delta"] + 4.0, 2)}
                if s["player_id"] == reversal_pid else s
                for s in suggestions
            ]

        return _build_panel(sel, suggestions, team["bank"], team["free_transfers"],
                            swap_section=swap_section, reversal_pid=reversal_pid)
    except Exception as exc:
        return html.Div(
            f"Error loading suggestions: {exc}",
            style={"padding": "16px", "color": "var(--bad)"},
        )



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

    in_pid  = tid["index"]
    all_p   = get_players_with_predictions()
    out_row = all_p[all_p["player_id"] == selected_id]
    in_row  = all_p[all_p["player_id"] == in_pid]
    if out_row.empty or in_row.empty:
        return dash.no_update, False, ""

    in_cost = float(in_row.iloc[0]["now_cost"])
    msg = (
        f"Transfer {out_row.iloc[0]['web_name']} → {in_row.iloc[0]['web_name']} "
        f"(£{in_cost:.1f}m). Confirm?"
    )
    return {"out": selected_id, "in": in_pid, "cost": in_cost}, True, msg


@callback(
    Output("mt-refresh", "data", allow_duplicate=True),
    Input({"type": "mt-swap-btn", "index": ALL}, "n_clicks"),
    State("mt-selected", "data"),
    State("mt-refresh",  "data"),
    prevent_initial_call=True,
)
def apply_swap(n_clicks_list, selected_id, refresh_count):
    from dash import ctx
    if not ctx.triggered or not any(n for n in n_clicks_list if n):
        return dash.no_update
    tid = ctx.triggered_id
    if not tid or selected_id is None:
        return dash.no_update

    target_pid = tid["index"]
    from app.team_manager import load_team, swap_positions, reassign_captaincy
    team = load_team()
    if not team:
        return dash.no_update

    sel_row    = next((p for p in team["players"] if p["player_id"] == selected_id), None)
    target_row = next((p for p in team["players"] if p["player_id"] == target_pid), None)
    if not sel_row or not target_row:
        return dash.no_update

    if sel_row["bench_order"] is not None and target_row["bench_order"] is None:
        swap_positions(bench_pid=selected_id, xi_pid=target_pid)
    elif sel_row["bench_order"] is None and target_row["bench_order"] is not None:
        swap_positions(bench_pid=target_pid, xi_pid=selected_id)
    else:
        return dash.no_update

    reassign_captaincy()
    return (refresh_count or 0) + 1


@callback(
    Output("mt-refresh",     "data", allow_duplicate=True),
    Output("mt-undo-stack",  "data"),
    Output("mt-pts-delta",   "data"),
    Input("mt-confirm",      "submit_n_clicks"),
    State("mt-pending-xfer", "data"),
    State("mt-refresh",      "data"),
    State("mt-undo-stack",   "data"),
    State("mt-pts-delta",    "data"),
    prevent_initial_call=True,
)
def confirm_transfer(submit_n, pending, refresh_count, undo_stack, pts_delta):
    if not submit_n or not pending:
        return dash.no_update, dash.no_update, dash.no_update

    stack = list(undo_stack or [])

    # Detect reversal: selecting the original player back → treat as undo, no extra hit
    if (stack and
            int(pending["in"]) == stack[-1]["out_player_id"] and
            int(pending["out"]) == stack[-1]["in_player_id"]):
        from app.team_manager import undo_transfer
        undo_info  = stack.pop()
        undo_transfer(undo_info)
        prev_delta = round((pts_delta or 0.0) - undo_info.get("pts_delta", 0.0), 2)
        return (refresh_count or 0) + 1, stack, prev_delta

    from app.team_manager import apply_transfer
    result = apply_transfer(
        out_player_id=int(pending["out"]),
        in_player_id=int(pending["in"]),
        in_player_cost=float(pending["cost"]),
    )
    undo = result["undo"]

    all_p   = get_players_with_predictions()
    out_row = all_p[all_p["player_id"] == pending["out"]]
    in_row  = all_p[all_p["player_id"] == pending["in"]]
    hit     = undo["old_ft"] < 1
    delta   = 0.0
    if not out_row.empty and not in_row.empty:
        delta = (float(in_row.iloc[0]["predicted_pts"])
                 - float(out_row.iloc[0]["predicted_pts"])
                 - (4.0 if hit else 0.0))
    undo["pts_delta"] = delta

    stack.append(undo)
    new_total = round((pts_delta or 0.0) + delta, 2)
    return (refresh_count or 0) + 1, stack, new_total


@callback(
    Output("mt-refresh",    "data", allow_duplicate=True),
    Output("mt-undo-stack", "data", allow_duplicate=True),
    Output("mt-pts-delta",  "data", allow_duplicate=True),
    Input("mt-undo-btn",    "n_clicks"),
    State("mt-undo-stack",  "data"),
    State("mt-refresh",     "data"),
    State("mt-pts-delta",   "data"),
    prevent_initial_call=True,
)
def undo_last_transfer(n_clicks, undo_stack, refresh_count, pts_delta):
    if not n_clicks or not undo_stack:
        return dash.no_update, dash.no_update, dash.no_update
    from app.team_manager import undo_transfer
    stack     = list(undo_stack)
    undo_info = stack.pop()
    undo_transfer(undo_info)
    prev_delta = round((pts_delta or 0.0) - undo_info.get("pts_delta", 0.0), 2)
    return (refresh_count or 0) + 1, stack, prev_delta


@callback(
    Output("mt-refresh",    "data",  allow_duplicate=True),
    Output("mt-import-err", "children"),
    Input("mt-import-btn",    "n_clicks"),
    State("mt-team-id-input", "value"),
    State("mt-ft-select",     "value"),
    State("mt-refresh",       "data"),
    prevent_initial_call=True,
)
def import_team(n_clicks, team_id, free_transfers, refresh_count):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not team_id:
        return dash.no_update, dbc.Alert("Enter your FPL team ID.", color="warning")

    team_id = int(team_id)
    from app.team_manager import fetch_squad_from_fpl, save_team
    try:
        gw   = get_latest_gw()
        data = fetch_squad_from_fpl(team_id, gw)
    except Exception as e:
        return dash.no_update, dbc.Alert(f"Could not fetch team: {e}", color="danger")

    if len(data["picks"]) != 15:
        return dash.no_update, dbc.Alert(
            f"Expected 15 players, got {len(data['picks'])}. Check your team ID.",
            color="danger",
        )

    all_p     = get_players_with_predictions()
    price_map = all_p.set_index("player_id")["now_cost"].to_dict()

    picks = []
    for pick in data["picks"]:
        pos_num   = pick["position"]
        bench_ord = (pos_num - 11) if pos_num > 11 else None
        price     = price_map.get(pick["element"], 0.0)
        picks.append({
            "player_id":       pick["element"],
            "purchase_price":  price,
            "selling_price":   price,
            "is_captain":      int(pick["is_captain"]),
            "is_vice_captain": int(pick["is_vice_captain"]),
            "bench_order":     bench_ord,
        })

    ft = int(free_transfers) if free_transfers is not None else 1
    save_team(picks=picks, bank=data["bank"], free_transfers=ft,
              fpl_team_id=team_id, is_original=True)
    return (refresh_count or 0) + 1, None


@callback(
    Output("mt-refresh",    "data", allow_duplicate=True),
    Output("mt-undo-stack", "data", allow_duplicate=True),
    Output("mt-pts-delta",  "data", allow_duplicate=True),
    Input("mt-revert-btn", "n_clicks"),
    State("mt-refresh",    "data"),
    prevent_initial_call=True,
)
def revert_to_original(n_clicks, refresh_count):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update
    from app.team_manager import restore_original_squad
    restore_original_squad()
    return (refresh_count or 0) + 1, [], 0.0


@callback(
    Output("mt-refresh",    "data", allow_duplicate=True),
    Output("mt-undo-stack", "data", allow_duplicate=True),
    Output("mt-pts-delta",  "data", allow_duplicate=True),
    Input("mt-reimport-btn", "n_clicks"),
    State("mt-refresh",      "data"),
    prevent_initial_call=True,
)
def reimport_team(n_clicks, refresh_count):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update
    from app.team_manager import delete_team
    delete_team()
    return (refresh_count or 0) + 1, [], 0.0


# ── Best-transfers recommendation ─────────────────────────────────────────────

def _build_xfer_rec_card(transfers: list) -> html.Div:
    profitable = [t for t in transfers if t["net_gain"] > 0]
    best       = transfers[0]["net_gain"] if transfers else 0.0
    one_t      = sum(1 for t in transfers if t["n_transfers"] == 1)
    two_t      = sum(1 for t in transfers if t["n_transfers"] == 2)

    kpi_strip = html.Div([
        html.Div([
            html.Div("Profitable", className="kpi-label"),
            html.Div(str(len(profitable)), className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("Best net gain", className="kpi-label"),
            html.Div(
                f"{best:+.1f}pts",
                className=f"kpi-value mono {'mt-delta-good' if best > 0 else 'mt-delta-bad'}",
            ),
        ], className="kpi"),
        html.Div([
            html.Div("1-transfer", className="kpi-label"),
            html.Div(str(one_t), className="kpi-value mono"),
        ], className="kpi"),
        html.Div([
            html.Div("2-transfer", className="kpi-label"),
            html.Div(str(two_t), className="kpi-value mono"),
        ], className="kpi"),
    ], className="kpi-grid", style={"marginBottom": "12px"})

    header = html.Div([
        html.Span("#",      className="xr-rank"),
        html.Span("Out",    className="xr-out"),
        html.Span("xPts",   className="xr-pts mono"),
        html.Span("",       className="xr-arrow"),
        html.Span("In",     className="xr-in"),
        html.Span("xPts",   className="xr-pts mono"),
        html.Span("Gross",  className="xr-gross mono"),
        html.Span("Hit",    className="xr-hit"),
        html.Span("Net",    className="xr-net mono"),
        html.Span("£Δ",     className="xr-cost mono"),
    ], className="xr-header")

    rows = []
    for i, t in enumerate(transfers[:15], 1):
        out_s  = " + ".join(t["transfers_out"])
        in_s   = " + ".join(t["transfers_in"])
        net    = t["net_gain"]
        hit    = t["hit"]
        net_cl = "mt-delta-good" if net > 0 else "mt-delta-bad"
        rows.append(html.Div([
            html.Span(str(i),                   className="xr-rank mono"),
            html.Span(out_s,                     className="xr-out"),
            html.Span(f"{t['out_pts']:.1f}",    className="xr-pts mono"),
            html.Span("→",                       className="xr-arrow"),
            html.Span(in_s,                      className="xr-in"),
            html.Span(f"{t['in_pts']:.1f}",     className="xr-pts mono"),
            html.Span(f"{t['gross_gain']:+.1f}", className="xr-gross mono"),
            html.Span(
                "Free" if hit == 0 else f"−{hit}",
                className="xr-hit " + ("xr-hit-free" if hit == 0 else "xr-hit-cost"),
            ),
            html.Span(f"{net:+.1f}", className=f"xr-net mono {net_cl}"),
            html.Span(f"{t['cost_change']:+.1f}m", className="xr-cost mono"),
        ], className="xr-row"))

    body = rows or [html.Div("No transfer options found.",
                              style={"padding": "12px 0", "color": INK_3})]

    return html.Div([
        html.Div([
            html.Div("Best transfers for your squad", className="card-title"),
            html.Button("✕", id="mt-xfer-close", className="panel-close", n_clicks=0),
        ], className="card-hd"),
        html.Div([kpi_strip, header, *body], className="card-body pad-lg"),
    ], className="card", style={"marginTop": "16px"})


@callback(
    Output("mt-xfer-open", "data"),
    Input("mt-xfer-btn-relay",   "data"),
    Input("mt-xfer-close-relay", "data"),
    State("mt-xfer-open",        "data"),
    prevent_initial_call=True,
)
def toggle_xfer_panel(btn_relay, close_relay, is_open):
    from dash import ctx
    trig = ctx.triggered_id
    if trig == "mt-xfer-btn-relay":
        if not btn_relay:
            return dash.no_update
        return not (is_open or False)
    if trig == "mt-xfer-close-relay":
        if not close_relay:
            return dash.no_update
        return False
    return dash.no_update


@callback(
    Output("mt-xfer-rec-area", "children"),
    Input("mt-xfer-open", "data"),
    Input("mt-refresh",   "data"),
)
def render_xfer_rec(is_open, _):
    if not is_open:
        return None
    from app.team_manager import load_team
    from app.data_loader import get_optimizer
    team = load_team()
    if not team:
        return html.Div("No team loaded.", style={"padding": "16px", "color": INK_3})
    squad_ids = [p["player_id"] for p in team["players"]]
    avail     = get_available_players()
    try:
        transfers = get_optimizer().recommend_transfers(
            current_squad_ids=squad_ids,
            players_df=avail,
            free_transfers=team["free_transfers"],
            bank=team["bank"],
        )
    except Exception as exc:
        return html.Div(f"Error: {exc}", style={"color": "var(--bad)", "padding": "16px"})
    return _build_xfer_rec_card(transfers)
