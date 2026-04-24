"""
Sidebar navigation component.
Static HTML — active state applied via clientside callback in app.py.
"""

from dash import html

from app.data_loader import get_latest_gw

NAV_ROUTES = {
    "nav-home":      ("/",          "Overview"),
    "nav-top50":     ("/top50",     "Top 50"),
    "nav-optimizer": ("/optimizer", "Optimizer"),
    "nav-transfers": ("/transfers", "Transfers"),
    "nav-results":   ("/results",   "GW Results"),
}

# Map from pathname to (section, page_label)
BREADCRUMBS = {
    "/":           ("Analysis",  "Overview"),
    "/top50":      ("Analysis",  "Top 50"),
    "/optimizer":  ("Actions",   "Optimizer"),
    "/transfers":  ("Actions",   "Transfers"),
    "/results":    ("History",   "GW Results"),
}


def build_sidebar() -> html.Div:
    latest_gw  = get_latest_gw()
    predict_gw = latest_gw + 1

    return html.Div([
        # ── Brand ────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Span(className="dot"),
                "FPL.INTEL",
            ], className="brand-mark"),
            html.Div(f"GW {predict_gw} · predicting", className="brand-sub"),
        ], className="sidebar-brand"),

        # ── Analysis section ─────────────────────────────────
        html.Div("Analysis", className="sidebar-section"),
        html.Nav([
            html.A("Overview",  href="/",      className="nav-item", id="nav-home"),
            html.A("Top 50",    href="/top50", className="nav-item", id="nav-top50"),
        ], className="sidebar-nav"),

        # ── Actions section ──────────────────────────────────
        html.Div("Actions", className="sidebar-section"),
        html.Nav([
            html.A("Optimizer", href="/optimizer", className="nav-item", id="nav-optimizer"),
            html.A("Transfers", href="/transfers", className="nav-item", id="nav-transfers"),
        ], className="sidebar-nav"),

        # ── History section ──────────────────────────────────
        html.Div("History", className="sidebar-section"),
        html.Nav([
            html.A("GW Results", href="/results", className="nav-item", id="nav-results"),
        ], className="sidebar-nav"),

        # ── Footer ───────────────────────────────────────────
        html.Div([
            html.Div([
                html.Span("model"),
                html.Span("XGBoost"),
            ], className="sidebar-meta"),
            html.Div([
                html.Span("GW data"),
                html.Span(f"GW {latest_gw}"),
            ], className="sidebar-meta"),
            html.Button(
                "◑ Dark",
                id="theme-toggle",
                className="theme-toggle",
                n_clicks=0,
            ),
        ], className="sidebar-foot"),

    ], className="sidebar")
