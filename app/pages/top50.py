import dash
from dash import html

dash.register_page(__name__, path="/top50", name="Top 50")

layout = html.Div(
    [
        html.H2("Top 50 Performers"),
        html.P("Coming in Phase 7 — sortable DataTable with predicted points and underlying stats."),
    ]
)
