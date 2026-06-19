"""Golf-themed Streamlit styling."""

from __future__ import annotations

import streamlit as st

GOLF_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Playfair+Display:wght@700&display=swap');

:root {
    --fairway: #1f4d2a;
    --fairway-dark: #163820;
    --rough: #2d6a3e;
    --sand: #f3e9d2;
    --gold: #c9a227;
    --card: #ffffff;
    --muted: #5f6f65;
}

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.main .block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1100px;
}

.hero-banner {
    background: linear-gradient(135deg, var(--fairway-dark) 0%, var(--fairway) 55%, var(--rough) 100%);
    color: white;
    border-radius: 18px;
    padding: 1.4rem 1.5rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 10px 30px rgba(22, 56, 32, 0.18);
}

.hero-banner h1 {
    font-family: 'Playfair Display', serif;
    font-size: clamp(1.6rem, 4vw, 2.4rem);
    margin: 0 0 0.35rem 0;
    line-height: 1.15;
}

.hero-banner p {
    margin: 0;
    color: #e8f3ea;
    font-size: 0.98rem;
}

.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.8rem;
    margin: 1rem 0 1.2rem 0;
}

.stat-card {
    background: var(--card);
    border: 1px solid #d9e7dc;
    border-radius: 14px;
    padding: 0.9rem 1rem;
    box-shadow: 0 4px 14px rgba(31, 77, 42, 0.06);
}

.stat-card .label {
    color: var(--muted);
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.stat-card .value {
    color: var(--fairway-dark);
    font-size: 1.45rem;
    font-weight: 700;
    margin-top: 0.2rem;
}

.leaderboard-table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 6px 18px rgba(31, 77, 42, 0.08);
}

.leaderboard-table th,
.leaderboard-table td {
    padding: 0.75rem 0.8rem;
    border-bottom: 1px solid #e6efe8;
    text-align: left;
    font-size: 0.95rem;
}

.leaderboard-table th {
    background: #edf5ef;
    color: var(--fairway-dark);
    font-weight: 700;
}

.leaderboard-table tr:last-child td {
    border-bottom: none;
}

.rank-pill {
    display: inline-block;
    min-width: 2rem;
    text-align: center;
    background: var(--sand);
    color: var(--fairway-dark);
    border-radius: 999px;
    padding: 0.15rem 0.55rem;
    font-weight: 700;
}

.rank-pill.leader {
    background: var(--gold);
    color: #1f1a05;
}

.player-chip {
    display: inline-block;
    background: #edf5ef;
    color: var(--fairway-dark);
    border-radius: 999px;
    padding: 0.2rem 0.65rem;
    margin: 0.15rem 0.25rem 0.15rem 0;
    font-size: 0.86rem;
}

.player-chip.counting {
    background: #dff1e4;
    border: 1px solid #9fc9ab;
}

.player-chip.dropped {
    background: #f8f1f1;
    color: #7a4b4b;
    border: 1px solid #e2c7c7;
    text-decoration: line-through;
}

.section-card {
    background: white;
    border: 1px solid #dbe8df;
    border-radius: 16px;
    padding: 1rem 1.1rem;
    margin-bottom: 1rem;
}

.section-card h3 {
    margin-top: 0;
    color: var(--fairway-dark);
}

.mobile-note {
    color: var(--muted);
    font-size: 0.88rem;
}

div[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f7fbf8 0%, #eef5f0 100%);
}

@media (max-width: 768px) {
    .main .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
    }

    .leaderboard-table th,
    .leaderboard-table td {
        padding: 0.55rem 0.45rem;
        font-size: 0.84rem;
    }
}
</style>
"""


def inject_styles() -> None:
    st.markdown(GOLF_CSS, unsafe_allow_html=True)


def render_hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hero-banner">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_cards(items: list[tuple[str, str]]) -> None:
    cards = "".join(
        f"""
        <div class="stat-card">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
        </div>
        """
        for label, value in items
    )
    st.markdown(f'<div class="stat-grid">{cards}</div>', unsafe_allow_html=True)
