import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html

from app.components.sidebar import BREADCRUMBS, build_sidebar
from app.db import init_db

init_db()

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)

server = app.server  # expose Flask server for Gunicorn

app.layout = html.Div(
    [
        dcc.Location(id="url"),

        html.Div(
            [
                # Sidebar — built once at startup; active state managed by clientside callback
                build_sidebar(),

                # Main area: sticky topbar + routed page content
                html.Div(
                    [
                        html.Div(id="topbar"),
                        dash.page_container,
                    ],
                    className="main",
                ),
            ],
            className="app",
        ),
    ],
    id="app-root",
    **{"data-theme": "light"},
)


# ── Active nav-item highlighting ─────────────────────────────────────────────
app.clientside_callback(
    """
    function(pathname) {
        const map = {
            '/':           'nav-home',
            '/top50':      'nav-top50',
            '/optimizer':  'nav-optimizer',
            '/my-team':    'nav-my-team',
            '/results':    'nav-results',
        };
        const base   = 'nav-item';
        const active = 'nav-item active';
        let best = null;
        let bestLen = 0;
        for (const [path, id] of Object.entries(map)) {
            if (pathname && pathname.startsWith(path) && path.length > bestLen) {
                best    = id;
                bestLen = path.length;
            }
        }
        const ids = ['nav-home', 'nav-top50', 'nav-optimizer', 'nav-my-team', 'nav-results'];
        return ids.map(id => id === best ? active : base);
    }
    """,
    [
        Output("nav-home",      "className"),
        Output("nav-top50",     "className"),
        Output("nav-optimizer", "className"),
        Output("nav-my-team",   "className"),
        Output("nav-results",   "className"),
    ],
    Input("url", "pathname"),
)


# ── Topbar breadcrumbs ────────────────────────────────────────────────────────
@app.callback(Output("topbar", "children"), Input("url", "pathname"))
def update_topbar(pathname):
    from app.data_loader import get_latest_gw
    latest_gw  = get_latest_gw()
    predict_gw = latest_gw + 1
    warming_up = latest_gw == 0

    section, page = BREADCRUMBS.get(pathname or "/", ("Actions", (pathname or "").lstrip("/")))

    crumb_parts = [html.Span("FPL Intelligence")]
    if section:
        crumb_parts += [
            html.Span(" / ", className="sep"),
            html.Span(section),
        ]
    crumb_parts += [
        html.Span(" / ", className="sep"),
        html.Span(page, className="cur"),
    ]

    return html.Div(
        [
            html.Div(crumb_parts, className="breadcrumb"),
            html.Div(
                [
                    html.Div(
                        [html.Span(className="pulse"),
                         "season warming up" if warming_up else f"GW {latest_gw} data"],
                        className="status-chip",
                    ),
                    html.Span("" if warming_up else f"predicting GW {predict_gw}"),
                ],
                className="topbar-right",
            ),
        ],
        className="topbar",
    )


# ── Theme toggle ─────────────────────────────────────────────────────────────
app.clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return window.dash_clientside.no_update;
        const root = document.getElementById('app-root');
        const cur  = root.getAttribute('data-theme') || 'light';
        const next = cur === 'light' ? 'dark' : 'light';
        root.setAttribute('data-theme', next);
        return next === 'dark' ? '☀ Light' : '◑ Dark';
    }
    """,
    Output("theme-toggle", "children"),
    Input("theme-toggle", "n_clicks"),
)


if __name__ == "__main__":
    app.run(debug=True)
