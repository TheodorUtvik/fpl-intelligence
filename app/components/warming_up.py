"""
Shared "season warming up" placeholder — shown wherever a page depends on
get_players_with_predictions()/get_latest_gw() and no complete gameweek or
trained model exists yet (typically right after a season rollover).
"""

import dash_bootstrap_components as dbc
from dash import html


def warming_up_alert(context: str = "Predictions") -> html.Div:
    return html.Div(
        dbc.Alert(
            [
                html.Strong(f"{context} aren't ready yet. "),
                "The model needs at least one completed current-season gameweek "
                "of data before it can predict reliably. Check back after GW1 "
                "results are in.",
            ],
            color="info",
        ),
        className="page",
    )
