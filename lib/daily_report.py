"""Deterministic Norwegian daily report generation for fantasy golf."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

DAYS = ["Dag 1", "Dag 2", "Dag 3", "Dag 4"]
TONES = ("Kort", "Morsom", "Seriøs")
COUNTING_LABEL = "✅ Teller"
DROPPED_LABEL = "❌ Droppes"


@dataclass
class DailyReportData:
    round_no: int
    day_label: str
    top3: list[tuple[str, int]] = field(default_factory=list)
    mover: tuple[str, int] | None = None
    best_day_team: str | None = None
    best_day_score: int | None = None
    worst_day_team: str | None = None
    worst_day_score: int | None = None
    top_helpers: list[tuple[str, int]] = field(default_factory=list)
    top_hurters: list[tuple[str, int]] = field(default_factory=list)
    notable_drops: list[tuple[str, str, int]] = field(default_factory=list)
    avg_counting_score: float | None = None
    under_par_counting: int = 0
    has_day_scores: bool = False


def fmt_relative(score: int) -> str:
    if score == 0:
        return "E"
    return f"{score:+d}" if score > 0 else str(score)


def cumulative_ranking(leaderboard: pd.DataFrame, through_round: int) -> pd.DataFrame:
    day_cols = DAYS[:through_round]
    available = [col for col in day_cols if col in leaderboard.columns]
    if not available:
        return pd.DataFrame(columns=["Lag", "cum", "rank"])

    ranked = leaderboard[["Lag", *available]].copy()
    ranked["cum"] = ranked[available].sum(axis=1, min_count=1)
    ranked = ranked.dropna(subset=["cum"]).sort_values("cum", ascending=True).reset_index(drop=True)
    ranked["rank"] = range(1, len(ranked) + 1)
    return ranked[["Lag", "cum", "rank"]]


def biggest_mover(leaderboard: pd.DataFrame, round_no: int) -> tuple[str, int] | None:
    if round_no <= 1 or leaderboard.empty:
        return None

    current = cumulative_ranking(leaderboard, round_no).set_index("Lag")["rank"]
    previous = cumulative_ranking(leaderboard, round_no - 1).set_index("Lag")["rank"]
    shared = current.index.intersection(previous.index)
    if shared.empty:
        return None

    movement = previous.loc[shared] - current.loc[shared]
    movement = movement[movement > 0]
    if movement.empty:
        return None

    team = movement.idxmax()
    return team, int(movement.max())


def analyze_daily_report(
    leaderboard: pd.DataFrame,
    details: pd.DataFrame,
    round_no: int,
) -> DailyReportData:
    day_label = DAYS[round_no - 1]
    data = DailyReportData(round_no=round_no, day_label=day_label)

    if leaderboard.empty:
        return data

    ranked = cumulative_ranking(leaderboard, round_no)
    if not ranked.empty:
        data.top3 = [
            (row.Lag, int(row.cum))
            for _, row in ranked.head(3).iterrows()
        ]

    data.mover = biggest_mover(leaderboard, round_no)

    if day_label in leaderboard.columns:
        day_scores = leaderboard[["Lag", day_label]].dropna()
        if not day_scores.empty:
            data.has_day_scores = True
            best_idx = day_scores[day_label].idxmin()
            worst_idx = day_scores[day_label].idxmax()
            data.best_day_team = day_scores.loc[best_idx, "Lag"]
            data.best_day_score = int(day_scores.loc[best_idx, day_label])
            data.worst_day_team = day_scores.loc[worst_idx, "Lag"]
            data.worst_day_score = int(day_scores.loc[worst_idx, day_label])

    if not details.empty and "Runde" in details.columns:
        day_details = details[details["Runde"] == round_no].copy()
        counting = day_details[day_details["Teller"] == COUNTING_LABEL].dropna(subset=["Score"])
        dropped = day_details[day_details["Teller"] == DROPPED_LABEL].dropna(subset=["Score"])

        if not counting.empty:
            helper_counts = counting.groupby("Spiller").size().sort_values(ascending=False)
            data.top_helpers = [
                (name, int(count))
                for name, count in helper_counts.head(3).items()
            ]
            data.avg_counting_score = float(counting["Score"].mean())
            data.under_par_counting = int((counting["Score"] < 0).sum())

        if not dropped.empty:
            hurter_counts = dropped.groupby("Spiller").size().sort_values(ascending=False)
            data.top_hurters = [
                (name, int(count))
                for name, count in hurter_counts.head(3).items()
            ]
            notable = dropped.sort_values("Score", ascending=False).head(3)
            data.notable_drops = [
                (row.Spiller, row.Lag, int(row.Score))
                for _, row in notable.iterrows()
            ]

    return data


def _join_names(items: list[tuple[str, int]], suffix: str) -> str:
    if not items:
        return ""
    parts = []
    for name, count in items:
        if count == 1:
            parts.append(name)
        else:
            parts.append(f"{name} ({count} {suffix})")
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} og {parts[1]}"
    return ", ".join(parts[:-1]) + f" og {parts[-1]}"


def _leader_sentence(data: DailyReportData, tone: str) -> str:
    if not data.top3:
        return f"{data.day_label} er ikke klar for oppsummering ennå."

    leader, leader_total = data.top3[0]
    second = data.top3[1][0] if len(data.top3) > 1 else None
    third = data.top3[2][0] if len(data.top3) > 2 else None

    if tone == "Seriøs":
        base = (
            f"{data.day_label} er ferdigspilt, og {leader} leder turneringen "
            f"med {fmt_relative(leader_total)} totalt."
        )
        if second and third:
            return base + f" {second} ligger på andreplass, mens {third} er tredje."
        if second:
            return base + f" {second} følger på andreplass."
        return base

    if tone == "Morsom":
        base = (
            f"{data.day_label} er i boks, og {leader} har tatt over førersetet "
            f"med {fmt_relative(leader_total)} totalt."
        )
        if second and third:
            return base + f" {second} holder presset oppe på andreplass, mens {third} fortsatt er med i kampen."
        if second:
            return base + f" {second} henger rett bak og holder liv i jakten."
        return base

    base = f"{data.day_label}: {leader} leder ({fmt_relative(leader_total)})."
    if second:
        base += f" {second} er nr. 2"
        if third:
            base += f", {third} nr. 3."
        else:
            base += "."
    return base


def _mover_sentence(data: DailyReportData, tone: str) -> str:
    if not data.mover:
        return ""
    team, places = data.mover
    if tone == "Seriøs":
        return f" Størst fremgang siden forrige runde: {team} (+{places} plasseringer)."
    if tone == "Morsom":
        return f" Størst opptur siden forrige runde? {team}, som klatret {places} plasser."
    return f" Størst mover: {team} (+{places})."


def _day_score_sentence(data: DailyReportData, tone: str) -> str:
    if not data.has_day_scores or data.best_day_team is None or data.worst_day_team is None:
        return ""
    best = fmt_relative(data.best_day_score or 0)
    worst = fmt_relative(data.worst_day_score or 0)
    if data.best_day_team == data.worst_day_team:
        return ""

    if tone == "Seriøs":
        return (
            f" Dagens beste lagscore kom fra {data.best_day_team} ({best}), "
            f"mens {data.worst_day_team} fikk den tyngste dagen ({worst})."
        )
    if tone == "Morsom":
        return (
            f" Dagens beste lagscore kom fra {data.best_day_team} ({best}), "
            f"mens {data.worst_day_team} fikk en tyngre dag ({worst})."
        )
    return f" Beste dag: {data.best_day_team} ({best}). Tyngst: {data.worst_day_team} ({worst})."


def _player_sentence(data: DailyReportData, tone: str) -> str:
    chunks: list[str] = []
    if data.top_helpers:
        helpers = _join_names(data.top_helpers, "lag")
        if tone == "Seriøs":
            chunks.append(f"Spillere som tellte for flest lag: {helpers}.")
        elif tone == "Morsom":
            chunks.append(f"Flest lag fikk hjelp av {helpers}.")
        else:
            chunks.append(f"Teller oftest: {helpers}.")

    if data.top_hurters:
        hurters = _join_names(data.top_hurters, "dropp")
        if tone == "Seriøs":
            chunks.append(f"Spillere som ble droppet oftest: {hurters}.")
        elif tone == "Morsom":
            chunks.append(f"Flere lag måtte droppe {hurters}.")
        else:
            chunks.append(f"Droppet oftest: {hurters}.")

    if data.notable_drops:
        drop_bits = [
            f"{player} ({fmt_relative(score)} for {team})"
            for player, team, score in data.notable_drops[:2]
        ]
        joined = " og ".join(drop_bits)
        if tone == "Seriøs":
            chunks.append(f"Merkverdige dropp: {joined}.")
        elif tone == "Morsom":
            chunks.append(f"Noen store navn ble droppet fra tellende score, blant annet {joined}.")
        else:
            chunks.append(f"Store dropp: {joined}.")

    return " ".join(chunks)


def _course_sentence(data: DailyReportData, tone: str) -> str:
    if data.avg_counting_score is None:
        return ""

    avg = data.avg_counting_score
    if avg <= -1:
        mood = "tough" if tone == "Seriøs" else "tung"
        if tone == "Morsom":
            return " Banen slo hardt tilbake, og det var få enkle scorer i tellende lagscore."
        if tone == "Seriøs":
            return " Scorenivået tyder på en krevende dag på banen."
        return " Krevende dag på banen."

    if avg >= 1:
        if tone == "Morsom":
            return " Det var en scorevennlig dag for mange lag, med flere tellende scorer over par."
        if tone == "Seriøs":
            return " Dagens scorer tyder på gode scoringmuligheter for flere lag."
        return " Relativt scorevennlig dag."

    if data.under_par_counting >= 8:
        if tone == "Morsom":
            return " Flere lag fikk god hjelp av spillere som leverte under par."
        if tone == "Seriøs":
            return " Flere tellende scorer kom under par."
        return " Mange under-par-tellere."

    if tone == "Kort":
        return ""
    if tone == "Morsom":
        return " Det var en jevn dag der de små forskjellene i tellende score avgjorde."
    return " Dagens nivå var jevnt mellom lagene."


def generate_daily_report(
    leaderboard: pd.DataFrame,
    details: pd.DataFrame,
    round_no: int,
    tone: str = "Morsom",
) -> tuple[str, str]:
    """Return (title, body) for the selected round and tone."""
    if tone not in TONES:
        tone = "Morsom"

    data = analyze_daily_report(leaderboard, details, round_no)
    title = f"{data.day_label} – dagsrapport"

    if not data.has_day_scores and not data.top3:
        body = f"Ingen scorer er registrert for {data.day_label} ennå."
        return title, body

    parts = [
        _leader_sentence(data, tone).strip(),
        _mover_sentence(data, tone).strip(),
        _day_score_sentence(data, tone).strip(),
        _player_sentence(data, tone).strip(),
        _course_sentence(data, tone).strip(),
    ]
    body = " ".join(part for part in parts if part).strip()

    if tone == "Kort" and len(body) > 420:
        body = body[:417].rstrip() + "..."

    return title, body


def run_daily_report_test() -> dict[str, Any]:
    leaderboard = pd.DataFrame(
        [
            {"Lag": "Thomas", "Dag 1": 6, "Dag 2": 1, "Totalt": 7},
            {"Lag": "Christine", "Dag 1": 4, "Dag 2": 4, "Totalt": 8},
            {"Lag": "Philip", "Dag 1": 5, "Dag 2": 4, "Totalt": 9},
            {"Lag": "Lars", "Dag 1": 8, "Dag 2": 7, "Totalt": 15},
        ]
    )
    details = pd.DataFrame(
        [
            {"Lag": "Thomas", "Dag": "Dag 2", "Runde": 2, "Spiller": "Scottie Scheffler", "Score": -2, "Teller": COUNTING_LABEL},
            {"Lag": "Thomas", "Dag": "Dag 2", "Runde": 2, "Spiller": "Jon Rahm", "Score": 4, "Teller": DROPPED_LABEL},
            {"Lag": "Lars", "Dag": "Dag 2", "Runde": 2, "Spiller": "Dustin Johnson", "Score": 6, "Teller": DROPPED_LABEL},
            {"Lag": "Christine", "Dag": "Dag 2", "Runde": 2, "Spiller": "Scottie Scheffler", "Score": -1, "Teller": COUNTING_LABEL},
        ]
    )

    title, body = generate_daily_report(leaderboard, details, 2, tone="Morsom")
    mover = biggest_mover(leaderboard, 2)
    checks = [
        {
            "name": "Title for Dag 2",
            "passed": title == "Dag 2 – dagsrapport",
            "expected": "Dag 2 – dagsrapport",
            "actual": title,
        },
        {
            "name": "Leader mentioned",
            "passed": "Thomas" in body,
            "expected": "Thomas",
            "actual": body,
        },
        {
            "name": "Biggest mover detected",
            "passed": mover == ("Thomas", 2),
            "expected": ("Thomas", 2),
            "actual": mover,
        },
        {
            "name": "Report mentions best and worst day",
            "passed": "Thomas" in body and "Lars" in body,
            "expected": "Thomas and Lars",
            "actual": body,
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "sample_body": body,
    }
