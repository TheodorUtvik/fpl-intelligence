import dash
from dash import html

dash.register_page(__name__, path="/optimizer", name="Optimizer")

layout = html.Div(
    [
        html.H2("Squad Optimizer"),
        html.P("Coming in Phase 6 — LP optimizer + pitch graphic."),
    ]
)
