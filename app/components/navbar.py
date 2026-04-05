import dash_bootstrap_components as dbc

navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("Home", href="/")),
        dbc.NavItem(dbc.NavLink("Optimizer", href="/optimizer")),
        dbc.NavItem(dbc.NavLink("Transfers", href="/transfers")),
        dbc.NavItem(dbc.NavLink("Top 50", href="/top50")),
    ],
    brand="FPL Intelligence",
    brand_href="/",
    color="primary",
    dark=True,
    className="mb-4",
)
