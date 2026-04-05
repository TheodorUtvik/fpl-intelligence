import dash
import dash_bootstrap_components as dbc
from dash import html

dash.register_page(__name__, path="/", name="Home")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                [
                    html.H1("FPL Intelligence", className="display-4 fw-bold"),
                    html.P(
                        "ML-powered player predictions combined with linear programming "
                        "to build optimal Fantasy Premier League squads.",
                        className="lead",
                    ),
                    html.Hr(),
                ],
                width=10,
            )
        ),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Squad Optimizer", className="card-title"),
                                html.P(
                                    "Select the best 15-man squad within your budget "
                                    "using predicted points and ILP.",
                                    className="card-text",
                                ),
                                dbc.Button("Go to Optimizer", href="/optimizer", color="primary"),
                            ]
                        )
                    ),
                    width=4,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Transfer Advisor", className="card-title"),
                                html.P(
                                    "Enter your FPL manager ID to get optimal transfer "
                                    "recommendations for the next gameweek.",
                                    className="card-text",
                                ),
                                dbc.Button("Go to Transfers", href="/transfers", color="primary"),
                            ]
                        )
                    ),
                    width=4,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Top 50 Performers", className="card-title"),
                                html.P(
                                    "Browse predicted points, xG, xA, and value metrics "
                                    "across all Premier League players.",
                                    className="card-text",
                                ),
                                dbc.Button("View Top 50", href="/top50", color="primary"),
                            ]
                        )
                    ),
                    width=4,
                ),
            ],
            className="g-4",
        ),
        dbc.Row(
            dbc.Col(
                [
                    html.H3("How it works", className="mt-5"),
                    html.Ol(
                        [
                            html.Li("FPL API and Understat data are collected each gameweek."),
                            html.Li(
                                "Features are engineered from rolling form, xG/xA, fixture "
                                "difficulty, and price trends — strictly without data leakage."
                            ),
                            html.Li("An XGBoost model predicts next-gameweek points per player."),
                            html.Li(
                                "A PuLP Integer Linear Program selects the optimal squad "
                                "subject to FPL budget, position, and club constraints."
                            ),
                            html.Li("SHAP explains each player's prediction on their profile page."),
                        ]
                    ),
                ],
                width=10,
            )
        ),
    ],
    className="py-4",
)
