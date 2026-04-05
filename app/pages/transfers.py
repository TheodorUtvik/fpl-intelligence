import dash
from dash import html

dash.register_page(__name__, path="/transfers", name="Transfers")

layout = html.Div(
    [
        html.H2("Transfer Advisor"),
        html.P("Coming in Phase 6 — transfer recommendations based on predicted points."),
    ]
)
