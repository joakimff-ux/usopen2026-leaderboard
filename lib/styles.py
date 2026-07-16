"""The Open-inspired Streamlit presentation layer."""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import streamlit as st

from lib import time_display
from lib.scoring import format_relative_score


NAVY = "#061f38"
GOLD = "#d7a21d"
CREAM = "#f7f1e5"


GOLF_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600&family=Inter:wght@400;500;600;700&display=swap');

:root {
    --navy: #061f38;
    --navy-soft: #0b3153;
    --cream: #f7f1e5;
    --cream-deep: #eee3cf;
    --gold: #d7a21d;
    --gold-soft: #f4c64d;
    --ink: #071f38;
    --muted: #6f6a61;
    --white: #fffdf8;
}

html, body, [class*="css"], .stApp {
    font-family: 'Inter', sans-serif;
    color: var(--ink);
}

.stApp {
    background:
        radial-gradient(circle at 72% 12%, rgba(215,162,29,.08), transparent 23rem),
        linear-gradient(135deg, #fbf8f1 0%, var(--cream) 55%, #f0e7d7 100%);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { color: var(--navy); }

.main .block-container {
    padding: 1rem 2rem 3rem;
    max-width: 1500px;
}

h1, h2, h3, .the-open-serif {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    color: var(--navy);
}

/* Sidebar */
section[data-testid="stSidebar"], div[data-testid="stSidebar"] {
    background:
        radial-gradient(circle at 12% 28%, rgba(215,162,29,.10), transparent 18rem),
        linear-gradient(180deg, #041a30 0%, #062843 100%);
    border-right: 1px solid rgba(215,162,29,.55);
}

section[data-testid="stSidebar"] *, div[data-testid="stSidebar"] * { color: #fffaf0; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"], div[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 1.2rem; }

.sidebar-brand {
    text-align: center;
    padding: .8rem .35rem 1.7rem;
    margin-bottom: 1.1rem;
    border-bottom: 1px solid rgba(255,255,255,.20);
}
.sidebar-brand .claret { font-size: 2.25rem; line-height: 1; color: var(--gold); }
.sidebar-brand .open-wordmark {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-weight: 700;
    font-size: 2.25rem;
    letter-spacing: .05em;
    line-height: 1;
}
.sidebar-brand .edition {
    color: var(--gold-soft);
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 1rem;
    letter-spacing: .12em;
    margin-top: .55rem;
}
.sidebar-brand .fantasy { margin-top: 1.2rem; font-size: .75rem; letter-spacing: .18em; text-transform: uppercase; }

section[data-testid="stSidebar"] div[role="radiogroup"], div[data-testid="stSidebar"] div[role="radiogroup"] { gap: .5rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] label, div[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding: .7rem .9rem;
    border-radius: 10px;
    transition: all .2s ease;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover, div[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: rgba(255,255,255,.09); }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked), div[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(135deg, var(--gold-soft), #efa919);
    box-shadow: 0 8px 24px rgba(0,0,0,.24);
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) *, div[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) * { color: var(--navy) !important; font-weight: 700; }

/* Hero */
.hero-banner {
    min-height: 310px;
    border-radius: 20px;
    margin-bottom: 1.25rem;
    padding: 2rem 2.2rem;
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    border: 1px solid rgba(215,162,29,.55);
    box-shadow: 0 18px 45px rgba(6,31,56,.18);
    background-size: cover;
    background-position: center;
}
.hero-banner::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, rgba(247,241,229,.98) 0%, rgba(247,241,229,.90) 27%, rgba(247,241,229,.22) 60%, rgba(6,31,56,.08) 100%);
}
.hero-content { position: relative; z-index: 2; max-width: 650px; }
.hero-kicker {
    color: #8b6500;
    text-transform: uppercase;
    letter-spacing: .16em;
    font-weight: 700;
    font-size: .78rem;
    margin-bottom: .35rem;
}
.hero-banner h1 {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(3.4rem, 7vw, 6.3rem);
    margin: 0;
    line-height: .88;
    color: var(--navy);
    text-shadow: 0 1px 0 rgba(255,255,255,.7);
}
.hero-rule { width: 180px; height: 2px; background: linear-gradient(90deg,var(--gold),transparent); margin: 1.15rem 0 .9rem; }
.hero-banner p { margin: 0; color: var(--navy); font-family: 'Cormorant Garamond', Georgia, serif; font-size: 1.35rem; font-weight: 600; }
.live-badge {
    position: absolute;
    z-index: 3;
    top: 1.2rem;
    right: 1.3rem;
    background: rgba(6,31,56,.92);
    color: #fff;
    border: 1px solid rgba(215,162,29,.65);
    border-radius: 999px;
    padding: .48rem .8rem;
    font-size: .76rem;
    font-weight: 700;
    letter-spacing: .05em;
    box-shadow: 0 8px 22px rgba(0,0,0,.22);
}
.live-dot { display:inline-block; width:.55rem; height:.55rem; background:#43bd68; border-radius:50%; margin-right:.4rem; box-shadow:0 0 0 4px rgba(67,189,104,.15); }

/* Cards */
.stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.9rem; margin:1rem 0 1.15rem; }
.stat-card {
    background: rgba(255,253,248,.94);
    border: 1px solid rgba(184,151,75,.28);
    border-radius: 15px;
    padding: 1rem 1.05rem;
    min-height: 105px;
    display:flex;
    align-items:center;
    gap:.9rem;
    box-shadow: 0 10px 25px rgba(39,31,16,.08);
}
.stat-card.prize { background:linear-gradient(135deg,#06243f,#0a3151); border-color:var(--gold); }
.stat-icon { font-size:1.8rem; width:2.4rem; text-align:center; }
.stat-card .label { color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.09em; font-weight:700; }
.stat-card .value { color:var(--navy); font-family:'Cormorant Garamond',Georgia,serif; font-size:2rem; font-weight:700; line-height:1; margin-top:.22rem; }
.stat-card.prize .label { color:#f5ead5; }
.stat-card.prize .value { color:var(--gold-soft); }

.rules-banner {
    display:flex;
    align-items:center;
    gap:1rem;
    background:linear-gradient(90deg,#fff9e9,#f6ead0);
    border:1px solid rgba(215,162,29,.35);
    border-radius:14px;
    padding:.85rem 1.2rem;
    margin:1rem 0 1.25rem;
    box-shadow:0 7px 18px rgba(80,55,10,.06);
}
.rules-icon { width:2.2rem; height:2.2rem; border-radius:50%; background:var(--navy); color:white; display:grid; place-items:center; font-family:Georgia,serif; font-weight:bold; }
.rules-copy { font-family:'Cormorant Garamond',Georgia,serif; font-size:1.12rem; line-height:1.25; color:var(--navy); }
.rules-swap { margin-left:auto; color:#8a6507; font-weight:700; white-space:nowrap; }

/* Leaderboard */
.leaderboard-shell { overflow-x:auto; border-radius:15px; border:1px solid rgba(184,151,75,.25); box-shadow:0 12px 30px rgba(6,31,56,.10); background:rgba(255,253,248,.95); }
.leaderboard-table { width:100%; border-collapse:collapse; min-width:760px; }
.leaderboard-table th { background:var(--navy); color:#fff; padding:.9rem 1rem; text-align:left; font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; }
.leaderboard-table th:not(:nth-child(2)), .leaderboard-table td:not(:nth-child(2)) { text-align:center; }
.leaderboard-table td { padding:.85rem 1rem; border-bottom:1px solid #e5dbc8; color:var(--navy); }
.leaderboard-table tbody tr:hover { background:#fff8e9; }
.leaderboard-table tbody tr:last-child td { border-bottom:0; }
.team-name { font-family:'Cormorant Garamond',Georgia,serif; font-size:1.25rem; font-weight:700; }
.team-link { color:var(--navy); text-decoration:none; display:inline-flex; align-items:center; gap:.45rem; border-bottom:1px solid transparent; }
.team-link:hover { color:#9a7000; border-bottom-color:var(--gold); }
.team-link.active { color:#9a7000; }
.team-link .chevron { color:var(--gold); font-family:'Inter',sans-serif; font-size:.78rem; }
.total-score { color:#a47500; font-family:'Cormorant Garamond',Georgia,serif; font-size:1.35rem; font-weight:700; }
.rank-medal { display:inline-grid; place-items:center; width:2rem; height:2rem; border-radius:50%; font-weight:800; background:#eee6d8; }
.rank-medal.gold { background:linear-gradient(135deg,#ffe27b,#d99b06); }
.rank-medal.silver { background:linear-gradient(135deg,#f6f6f6,#aeb7be); }
.rank-medal.bronze { background:linear-gradient(135deg,#e0ad65,#996020); color:#fff; }

/* Live feed */
.live-feed { margin-top:1.6rem; }
.live-feed-heading { display:flex; align-items:center; gap:.65rem; margin:0 0 .85rem; }
.live-feed-heading h2 { margin:0; font-size:2rem; }
.live-feed-pulse { width:.65rem; height:.65rem; border-radius:50%; background:#3db967; box-shadow:0 0 0 5px rgba(61,185,103,.14); }
.live-feed-list { display:grid; gap:.65rem; }
.live-event {
    display:grid;
    grid-template-columns:2.65rem minmax(0,1fr) auto;
    align-items:center;
    gap:.85rem;
    background:rgba(255,253,248,.96);
    border:1px solid #e5d9c4;
    border-left:5px solid var(--event-color,#9b8f7c);
    border-radius:13px;
    padding:.8rem 1rem;
    box-shadow:0 7px 18px rgba(6,31,56,.07);
}
.live-event.eagle { --event-color:#d7a21d; }
.live-event.birdie { --event-color:#269b55; }
.live-event.bogey { --event-color:#d34a45; }
.live-event.double-bogey-plus { --event-color:#7d1720; }
.live-event.round-complete { --event-color:#0b416b; }
.live-event.status { --event-color:#a06b12; }
.live-event-icon { width:2.45rem; height:2.45rem; border-radius:50%; display:grid; place-items:center; background:color-mix(in srgb,var(--event-color) 13%,white); font-size:1.15rem; }
.live-event-title { color:var(--navy); font-family:'Cormorant Garamond',Georgia,serif; font-weight:700; font-size:1.18rem; line-height:1.1; }
.live-event-meta { color:#655f56; font-size:.82rem; margin-top:.28rem; }
.live-event-time { color:#80600b; font-size:.74rem; font-weight:700; white-space:nowrap; }
.live-feed-empty { background:rgba(255,253,248,.75); border:1px dashed #cdbb98; border-radius:13px; padding:1rem; color:#746a5c; }

/* Inline team preview */
.team-preview {
    margin:1rem 0 1.35rem;
    background:rgba(255,253,248,.98);
    border:1px solid rgba(215,162,29,.48);
    border-radius:16px;
    overflow:hidden;
    box-shadow:0 14px 32px rgba(6,31,56,.12);
}
.team-preview-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; padding:1rem 1.2rem; background:linear-gradient(135deg,#06243f,#0a3151); }
.team-preview-kicker { color:var(--gold-soft); text-transform:uppercase; letter-spacing:.11em; font-size:.68rem; font-weight:700; }
.team-preview-head h2 { color:#fffaf0; margin:.15rem 0 0; font-size:2rem; }
.team-preview-summary { color:#ead8ae; font-size:.78rem; text-align:right; }
.team-preview-scroll { overflow-x:auto; }
.team-preview-table { width:100%; border-collapse:collapse; min-width:920px; }
.team-preview-table th { background:#eee3cf; color:var(--navy); padding:.65rem .7rem; font-size:.66rem; text-transform:uppercase; letter-spacing:.07em; text-align:center; }
.team-preview-table th:nth-child(2), .team-preview-table td:nth-child(2) { text-align:left; }
.team-preview-table td { padding:.72rem .7rem; border-top:1px solid #e7dcc9; text-align:center; color:var(--navy); font-size:.82rem; }
.team-preview-table tr.counting { background:linear-gradient(90deg,rgba(44,154,86,.10),rgba(215,162,29,.06)); border-left:4px solid #35a35d; }
.team-preview-table tr.dropped { background:#f2eee6; opacity:.66; border-left:4px solid #aaa08f; }
.team-preview-table tr.pending { border-left:4px solid #d1b973; }
.preview-player { font-family:'Cormorant Garamond',Georgia,serif; font-size:1.08rem; font-weight:700; }
.selection-badge, .status-badge { display:inline-block; border-radius:999px; padding:.25rem .5rem; font-size:.62rem; font-weight:800; letter-spacing:.04em; white-space:nowrap; }
.selection-badge.counting { color:#145d32; background:#dcefe2; border:1px solid #8fc6a1; }
.selection-badge.dropped { color:#6f675b; background:#e5dfd4; border:1px solid #c9c0b1; }
.selection-badge.pending { color:#755900; background:#f6ecc9; border:1px solid #dec777; }
.status-badge.active { color:#155d34; background:#dff1e5; }
.status-badge.cut, .status-badge.wd, .status-badge.dq { color:#fff; background:#8c2630; }

/* Native Streamlit elements */
[data-testid="stDataFrame"], [data-testid="stForm"], [data-testid="stExpander"] {
    border-radius:14px;
    overflow:hidden;
    box-shadow:0 8px 22px rgba(6,31,56,.07);
}
.stButton > button, .stFormSubmitButton > button {
    border-radius:10px;
    border:1px solid #c28b00;
    background:linear-gradient(135deg,var(--gold-soft),#eaa817);
    color:var(--navy);
    font-weight:700;
}
.stButton > button:hover, .stFormSubmitButton > button:hover { border-color:var(--navy); color:var(--navy); }
[data-baseweb="tab-list"] { gap:.35rem; }
[data-baseweb="tab"] { border-radius:9px 9px 0 0; }
div[data-testid="stMetric"] { background:#fffdf8; border:1px solid #e6d8bd; border-radius:12px; padding:.7rem; }

@media (max-width: 900px) {
    .main .block-container { padding: .7rem 1rem 2rem; }
    .hero-banner { min-height:260px; padding:1.4rem; background-position:65% center; }
    .hero-banner::after { background:linear-gradient(90deg,rgba(247,241,229,.97),rgba(247,241,229,.75) 58%,rgba(6,31,56,.10)); }
    .hero-banner h1 { font-size:clamp(3rem,14vw,5rem); }
    .live-badge { top:.75rem; right:.75rem; }
    .stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .rules-banner { align-items:flex-start; flex-wrap:wrap; }
    .rules-swap { margin-left:3.2rem; }
}

@media (max-width: 520px) {
    .hero-banner { min-height:235px; border-radius:14px; }
    .hero-banner p { font-size:1.05rem; max-width:75%; }
    .stat-grid { grid-template-columns:1fr 1fr; gap:.55rem; }
    .stat-card { min-height:88px; padding:.75rem; gap:.45rem; }
    .stat-icon { font-size:1.35rem; width:1.7rem; }
    .stat-card .value { font-size:1.45rem; }
    .stat-card .label { font-size:.62rem; }
    .rules-swap { margin-left:0; width:100%; }
    .live-event { grid-template-columns:2.25rem minmax(0,1fr); padding:.75rem; gap:.65rem; }
    .live-event-icon { width:2.1rem; height:2.1rem; }
    .live-event-time { grid-column:2; }
    .live-event-title { font-size:1.05rem; }
    .team-preview-head { align-items:flex-start; flex-direction:column; }
    .team-preview-summary { text-align:left; }
    .team-preview-scroll { overflow:visible; }
    .team-preview-table, .team-preview-table tbody { display:block; min-width:0; }
    .team-preview-table thead { display:none; }
    .team-preview-table tr { display:grid; grid-template-columns:1fr 1fr; margin:.65rem; border:1px solid #ded3c1; border-left-width:4px; border-radius:11px; overflow:hidden; }
    .team-preview-table td { display:flex; justify-content:space-between; align-items:center; gap:.5rem; padding:.52rem .62rem; text-align:right !important; border-top:1px solid #e7dcc9; }
    .team-preview-table td::before { content:attr(data-label); color:#756b5c; font-family:'Inter',sans-serif; font-size:.58rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }
    .team-preview-table td:nth-child(2) { grid-column:1 / -1; }
}
</style>
"""


def _hero_data_uri() -> str:
    image_path = Path(__file__).parents[1] / "data" / "royal-birkdale-hero.png"
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def inject_styles() -> None:
    st.markdown(GOLF_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="claret">♛</div>
            <div class="open-wordmark">THE OPEN</div>
            <div class="edition">ROYAL BIRKDALE · 2026</div>
            <div class="fantasy">Fantasy Golf</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str) -> None:
    image_uri = _hero_data_uri()
    background = f"background-image:url('{image_uri}');" if image_uri else ""
    updated = time_display.current_oslo_time()
    st.markdown(
        f"""
        <div class="hero-banner" style="{background}">
            <div class="live-badge"><span class="live-dot"></span>LIVE &nbsp;·&nbsp; {updated}</div>
            <div class="hero-content">
                <div class="hero-kicker">The Open 2026 Kupongen</div>
                <h1>{escape(title)}</h1>
                <div class="hero-rule"></div>
                <p>{escape(subtitle)}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_cards(items: list[tuple[str, str]]) -> None:
    icons = {"Lag": "♜", "Runder": "⚑", "1. plass": "🏆", "2. plass": "🥈"}
    cards = "".join(
        f'<div class="stat-card {"prize" if "plass" in label else ""}">'
        f'<div class="stat-icon">{icons.get(label, "◆")}</div>'
        f'<div><div class="label">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        '</div>'
        for label, value in items
    )
    st.markdown(f'<div class="stat-grid">{cards}</div>', unsafe_allow_html=True)


def render_rules_banner() -> None:
    st.markdown(
        """
        <div class="rules-banner">
            <div class="rules-icon">i</div>
            <div class="rules-copy">De 5 beste scorene teller hver dag.<br>De 2 dårligste droppes.</div>
            <div class="rules-swap">3 mulige bytter etter dag 2</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_leaderboard_table(rows: list[dict[str, str | int | bool]]) -> None:
    medals = {1: ("🥇", "gold"), 2: ("🥈", "silver"), 3: ("🥉", "bronze")}
    body: list[str] = []
    for row in rows:
        rank = int(row["Rank"])
        symbol, css_class = medals.get(rank, (str(rank), ""))
        is_selected = bool(row.get("Selected"))
        href = escape(str(row.get("Preview href") or "?"), quote=True)
        active_class = " active" if is_selected else ""
        body.append(
            f'<tr><td><span class="rank-medal {css_class}">{symbol}</span></td>'
            f'<td class="team-name"><a class="team-link{active_class}" href="{href}" target="_self">'
            f'{escape(str(row["Team"]))}<span class="chevron">{"▲" if is_selected else "▼"}</span></a></td>'
            f'<td>{escape(str(row["Round 1"]))}</td><td>{escape(str(row["Round 2"]))}</td>'
            f'<td>{escape(str(row["Round 3"]))}</td><td>{escape(str(row["Round 4"]))}</td>'
            f'<td><span class="total-score">{escape(str(row["Total"]))}</span></td></tr>'
        )
    table_html = (
        '<div class="leaderboard-shell"><table class="leaderboard-table">'
        '<thead><tr><th>Pos</th><th>Lag</th><th>Runde 1</th><th>Runde 2</th>'
        '<th>Runde 3</th><th>Runde 4</th><th>Total</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)


def render_team_preview(
    team_name: str,
    active_round: int,
    tournament_total: int | None,
    rows: list[dict],
) -> None:
    def score(value: object) -> str:
        return format_relative_score(None if value is None else int(value))

    body: list[str] = []
    for row in rows:
        selection = str(row["selection"]).lower()
        selection_label = {
            "counting": "Teller",
            "dropped": "Droppes",
            "pending": "Ikke avgjort",
        }.get(selection, selection)
        status = str(row.get("status") or "ACTIVE").upper()
        round_scores = row["round_scores"]
        body.append(
            f'<tr class="{selection}">'
            f'<td data-label="Tier">{escape(str(row["tier"]))}</td>'
            f'<td data-label="Spiller" class="preview-player">{escape(str(row["player_name"]))}</td>'
            f'<td data-label="R1">{escape(score(round_scores.get(1)))}</td>'
            f'<td data-label="R2">{escape(score(round_scores.get(2)))}</td>'
            f'<td data-label="R3">{escape(score(round_scores.get(3)))}</td>'
            f'<td data-label="R4">{escape(score(round_scores.get(4)))}</td>'
            f'<td data-label="Total">{escape(score(row.get("running_total")))}</td>'
            f'<td data-label="Hull">{escape(str(row.get("hole_status") or "—"))}</td>'
            f'<td data-label="Status"><span class="status-badge {status.lower()}">{escape(status)}</span></td>'
            f'<td data-label="Aktiv runde"><span class="selection-badge {selection}">{escape(selection_label)}</span></td>'
            '</tr>'
        )

    st.markdown(
        '<section class="team-preview">'
        '<header class="team-preview-head"><div>'
        '<div class="team-preview-kicker">Rask lagvisning</div>'
        f'<h2>{escape(team_name)}</h2></div>'
        f'<div class="team-preview-summary">Aktiv runde: {active_round}<br>'
        f'Løpende lagtotal: {escape(score(tournament_total))}<br>Klikk navnet igjen for å lukke</div></header>'
        '<div class="team-preview-scroll"><table class="team-preview-table">'
        '<thead><tr><th>Tier</th><th>Spiller</th><th>R1</th><th>R2</th><th>R3</th><th>R4</th>'
        '<th>Total</th><th>Hull</th><th>Status</th><th>Aktiv runde</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></section>',
        unsafe_allow_html=True,
    )


def _relative_score(value: object) -> str:
    if value is None:
        return "—"
    score = int(value)
    if score == 0:
        return "E"
    return f"+{score}" if score > 0 else f"−{abs(score)}"


def _event_time(value: object) -> str:
    return time_display.format_oslo_time(value)


def render_live_feed(
    events: list[dict],
    affected_teams: dict[str, list[str]],
) -> None:
    labels = {
        "EAGLE": ("🟡", "Eagle", "eagle"),
        "BIRDIE": ("🟢", "Birdie", "birdie"),
        "BOGEY": ("🔴", "Bogey", "bogey"),
        "DOUBLE_BOGEY_PLUS": ("🟥", "Dobbelbogey eller verre", "double-bogey-plus"),
        "ROUND_COMPLETE": ("🏁", "Ferdig med runden", "round-complete"),
        "CUT": ("✂️", "CUT", "status"),
        "WD": ("↩️", "WD", "status"),
        "DQ": ("⚠️", "DQ", "status"),
    }
    cards: list[str] = []
    for event in events:
        player_id = str(event.get("player_id") or "")
        teams = affected_teams.get(player_id, [])
        if not teams:
            continue
        event_type = str(event.get("event_type") or "")
        icon, label, css_class = labels.get(event_type, ("•", event_type, "status"))
        player = event.get("players") or {}
        player_name = player.get("name") if isinstance(player, dict) else None
        player_name = str(player_name or "Ukjent spiller")
        hole = event.get("hole")
        if hole is not None:
            title = f"{label} – {player_name} på hull {hole}"
            hole_detail = f"{_relative_score(event.get('hole_score'))} på hullet · "
        else:
            title = f"{label} – {player_name}"
            hole_detail = ""
        team_text = " og ".join(teams) if len(teams) <= 2 else ", ".join(teams[:-1]) + f" og {teams[-1]}"
        meta = (
            f"{hole_detail}Nå {_relative_score(event.get('round_score'))} for runden"
            f" · Påvirker {team_text}"
        )
        cards.append(
            f'<article class="live-event {css_class}">'
            f'<div class="live-event-icon">{icon}</div>'
            f'<div><div class="live-event-title">{escape(title)}</div>'
            f'<div class="live-event-meta">{escape(meta)}</div></div>'
            f'<time class="live-event-time">{escape(_event_time(event.get("created_at")))}</time>'
            '</article>'
        )

    content = "".join(cards) if cards else '<div class="live-feed-empty">Ingen nye scorehendelser ennå.</div>'
    st.markdown(
        '<section class="live-feed">'
        '<div class="live-feed-heading"><span class="live-feed-pulse"></span><h2>Live fra banen</h2></div>'
        f'<div class="live-feed-list">{content}</div></section>',
        unsafe_allow_html=True,
    )
