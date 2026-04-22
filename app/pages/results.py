"""
GW Results page.
Shows predicted vs actual points for the current GW and the previous 3,
so you can track how well the model performed week by week.
"""

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, callback, html
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.data_loader import (
    get_latest_gw,
    get_predictor,
    load_features,
    load_teams,
)

dash.register_page(__name__, path="/results", name="GW Results")

GREEN  = "#00bc8c"
RED    = "#e74c3c"
CARD   = "#2d2d2d"
TEXT   = "#ffffff"
ORANGE = "#fd7e14"
BLUE   = "#375a7f"

RAW = ROOT / "data" / "raw"

POS_BADGE = {"GKP": "warning", "DEF": "primary", "MID": "success", "FWD": "danger"}


# ── Data helpers ──────────────────────────────────────────────────────────────

def _build_comparison(predict_from_gw: int, actual_gw: int) -> pd.DataFrame:
    """
    Use the model on features from `predict_from_gw` and compare to
    actual points scored in `actual_gw`.
    """
    features  = load_features()
    predictor = get_predictor()
    teams = load_teams()[["id", "short_name"]].rename(
        columns={"id": "team", "short_name": "team_name"}
    )

    snap = features[features["round"] == predict_from_gw].copy()
    if snap.empty:
        return pd.DataFrame()

    snap["predicted_pts"] = predictor.predict(snap)

    # Actual points from the raw FPL gameweeks file
    gw_path = RAW / "fpl_gameweeks.parquet"
    if not gw_path.exists():
        return pd.DataFrame()

    actuals = pd.read_parquet(gw_path)
    actuals = actuals[actuals["round"] == actual_gw][["player_id", "total_points", "minutes"]]
    actuals = actuals.rename(columns={"total_points": "actual_pts"})

    # features already contains web_name and position — just add team_name and actuals
    df = snap.merge(actuals, on="player_id", how="inner")
    df = df.merge(teams, on="team", how="left")

    # In double GWs a player can have two feature rows — keep the one with
    # the highest predicted_pts (most recent fixture data)
    df = df.sort_values("predicted_pts", ascending=False).drop_duplicates("player_id")

    df["diff"] = df["actual_pts"] - df["predicted_pts"]
    df = df[df["minutes"] > 0]  # only players who actually played

    keep = ["player_id", "web_name", "position", "team_name",
            "predicted_pts", "actual_pts", "diff", "minutes"]
    return df[keep].sort_values("predicted_pts", ascending=False).reset_index(drop=True)


def _summary_cards(df: pd.DataFrame) -> dbc.Row:
    if df.empty:
        return dbc.Row()

    mae      = df["diff"].abs().mean()
    within2  = (df["diff"].abs() <= 2).mean() * 100
    best_idx = df["diff"].abs().idxmin()
    miss_idx = df["diff"].abs().idxmax()

    best = df.loc[best_idx]
    miss = df.loc[miss_idx]

    return dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("MAE", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(f"{mae:.2f} pts", style={"color": ORANGE, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Within 2 pts", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(f"{within2:.0f}%", style={"color": GREEN, "fontWeight": "bold"}),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Best call", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(
                f"{best['web_name']}  {best['diff']:+.1f}",
                style={"color": GREEN, "fontWeight": "bold", "fontSize": "1rem"},
            ),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P("Biggest miss", className="text-muted mb-1", style={"fontSize": "0.8rem"}),
            html.H4(
                f"{miss['web_name']}  {miss['diff']:+.1f}",
                style={"color": RED, "fontWeight": "bold", "fontSize": "1rem"},
            ),
        ]), style={"backgroundColor": CARD}), xs=6, md=3),
    ], className="g-3 mb-3")


def _results_table(df: pd.DataFrame) -> dbc.Table:
    rows = []
    for i, (_, row) in enumerate(df.head(30).iterrows(), 1):
        diff    = row["diff"]
        colour  = GREEN if diff > 0 else (RED if diff < -1 else "#aaa")

        rows.append(html.Tr([
            html.Td(i, style={"color": "#aaa", "width": "32px"}),
            html.Td(
                html.A(
                    row["web_name"],
                    href=f"/player/{int(row['player_id'])}",
                    style={"color": TEXT, "fontWeight": "bold", "textDecoration": "none"},
                )
            ),
            html.Td(dbc.Badge(row["position"],
                              color=POS_BADGE.get(row["position"], "secondary"))),
            html.Td(row.get("team_name", ""), style={"color": "#aaa"}),
            html.Td(f'{row["predicted_pts"]:.2f}', style={"color": BLUE}),
            html.Td(f'{row["actual_pts"]:.0f}',    style={"color": TEXT, "fontWeight": "bold"}),
            html.Td(
                f'{diff:+.2f}',
                style={"color": colour, "fontWeight": "bold"},
            ),
        ]))

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("#"), html.Th("Player"), html.Th("Pos"), html.Th("Club"),
                html.Th("Predicted"), html.Th("Actual"), html.Th("Diff"),
            ], style={"color": TEXT})),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
        style={"backgroundColor": CARD},
    )


def _tab_content(predict_from_gw: int, actual_gw: int, label: str) -> dbc.Tab:
    df = _build_comparison(predict_from_gw, actual_gw)

    if df.empty:
        body = dbc.Alert(
            f"No data available for GW {actual_gw}.", color="secondary"
        )
    else:
        body = html.Div([
            _summary_cards(df),
            html.P(
                f"{len(df)} players who played  ·  "
                f"sorted by predicted pts (top 30 shown)",
                className="text-muted mb-2",
                style={"fontSize": "0.8rem"},
            ),
            _results_table(df),
        ])

    return dbc.Tab(body, label=label, tab_id=f"tab-{actual_gw}")


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    latest_gw   = get_latest_gw()
    predict_gw  = latest_gw + 1

    # Build tabs: current GW + 3 previous
    gw_pairs = [
        (predict_gw - 1 - i, predict_gw - i)
        for i in range(4)
    ]

    tabs = []
    for i, (from_gw, actual_gw) in enumerate(gw_pairs):
        label = f"GW {actual_gw}" + (" (current)" if i == 0 else "")
        tabs.append(_tab_content(from_gw, actual_gw, label))

    return dbc.Container([

        dbc.Row(dbc.Col([
            html.H2("GW Results", className="fw-bold mb-0"),
            html.P(
                "Predicted vs actual points — how the model performed each week. "
                "Green diff = player outscored prediction, red = underperformed.",
                className="text-muted",
            ),
            html.Hr(style={"borderColor": "#444"}),
        ])),

        dbc.Tabs(tabs, active_tab=f"tab-{predict_gw}"),

    ], fluid=True, className="py-4 px-3")
