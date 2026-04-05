import dash
from dash import html

dash.register_page(__name__, path="/player/<player_id>", name="Player")


def layout(player_id=None):
    return html.Div(
        [
            html.H2(f"Player Profile — ID {player_id}"),
            html.P("Coming in Phase 7 — xG/xA trends, predicted vs actual, SHAP waterfall."),
        ]
    )
