"""
Club badge rendering helper (logo + short code).
"""

from dash import html

TEAM_LOGO_FILES = {
    "ARS": "england_arsenal.football-logos.cc.svg",
    "AVL": "england_aston-villa.football-logos.cc.svg",
    "BHA": "england_brighton.football-logos.cc.svg",
    "BOU": "england_bournemouth.football-logos.cc.svg",
    "BRE": "england_brentford.football-logos.cc.svg",
    "BUR": "england_burnley.football-logos.cc.svg",
    "CHE": "england_chelsea.football-logos.cc.svg",
    "CRY": "england_crystal-palace.football-logos.cc.svg",
    "EVE": "england_everton.football-logos.cc.svg",
    "FUL": "england_fulham.football-logos.cc.svg",
    "LEE": "england_leeds-united.football-logos.cc.svg",
    "LIV": "england_liverpool.football-logos.cc.svg",
    "MCI": "england_manchester-city.football-logos.cc.svg",
    "MUN": "england_manchester-united.football-logos.cc.svg",
    "NEW": "england_newcastle.football-logos.cc.svg",
    "NFO": "england_nottingham-forest.football-logos.cc.svg",
    "SUN": "england_sunderland.football-logos.cc.svg",
    "TOT": "england_tottenham.football-logos.cc.svg",
    "WHU": "england_west-ham.football-logos.cc.svg",
    "WOL": "england_wolves.football-logos.cc.svg",
}


def render_club_badge(team_code: str | None) -> html.Span:
    code = (team_code or "").upper()
    logo = TEAM_LOGO_FILES.get(code)

    logo_child = (
        html.Img(
            src=f"/assets/logos/{logo}",
            alt=f"{code} logo",
            className="club-badge-img",
        )
        if logo
        else html.Span("", className="club-badge-img")
    )

    children = [
        html.Span(code or "—", className="club-badge-code"),
        html.Span(logo_child, className="club-badge-slot"),
    ]

    return html.Span(children, className="club-badge-wrap")
