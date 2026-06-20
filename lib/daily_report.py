"""Deterministic Norwegian daily report generation for fantasy golf."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

DAYS = ["Dag 1", "Dag 2", "Dag 3", "Dag 4"]
TONES = ("Saklig", "Morsom", "Frekk", "Brutal")
COUNTING_LABEL = "✅ Teller"
DROPPED_LABEL = "❌ Droppes"
MIN_WORDS = 250
MAX_WORDS = 400

BANNED_PHRASES = (
    "spennende dag på banen",
    "solide prestasjoner",
    "interessant å følge utviklingen",
    "det blir spennende",
    "flere spillere leverte",
    "en actionfylt",
    "holdt fanen høyt",
)


FORBIDDEN_PLACEMENT_PHRASES = (
    "andreplass",
    "nr. 2",
    "nr 2",
    "nummer 2",
    "2. plass",
    "på 2. plass",
    "på andre",
    "tredjeplass",
    "nr. 3",
    "holder presset oppe",
)


@dataclass
class DailyReportData:
    round_no: int
    day_label: str
    top3: list[tuple[str, int]] = field(default_factory=list)
    score_groups: list[tuple[int, list[str]]] = field(default_factory=list)
    leaders: list[str] = field(default_factory=list)
    leader_score: int | None = None
    chasers: list[str] = field(default_factory=list)
    chaser_score: int | None = None
    chaser_gap: int | None = None
    mover: tuple[str, int] | None = None
    faller: tuple[str, int] | None = None
    best_day_teams: list[str] = field(default_factory=list)
    best_day_team: str | None = None
    best_day_score: int | None = None
    worst_day_teams: list[str] = field(default_factory=list)
    worst_day_team: str | None = None
    worst_day_score: int | None = None
    bottom_team: str | None = None
    bottom_score: int | None = None
    leader_gap: int | None = None
    top_helpers: list[tuple[str, int]] = field(default_factory=list)
    top_hurters: list[tuple[str, int]] = field(default_factory=list)
    day_heroes: list[tuple[str, int, str]] = field(default_factory=list)
    day_villains: list[tuple[str, int, str]] = field(default_factory=list)
    notable_drops: list[tuple[str, str, int]] = field(default_factory=list)
    avg_counting_score: float | None = None
    under_par_counting: int = 0
    has_day_scores: bool = False


def fmt_relative(score: int) -> str:
    if score == 0:
        return "E"
    return f"+{score}" if score > 0 else str(score)


def word_count(text: str) -> int:
    return len(text.split())


def pick_variant(options: list[str], key: str) -> str:
    if not options:
        return ""
    return options[hash(key) % len(options)]


def normalize_leaderboard_input(leaderboard: pd.DataFrame) -> pd.DataFrame:
    """Strip UI-only columns so standings never follow table row order."""
    if leaderboard.empty:
        return leaderboard
    lb = leaderboard.copy()
    for column in ("Plass", "plass"):
        if column in lb.columns:
            lb = lb.drop(columns=[column])
    return lb


def team_total_through_round(row: pd.Series, through_round: int) -> int | None:
    day_cols = [day for day in DAYS[:through_round] if day in row.index]
    day_values = [row[day] for day in day_cols if pd.notna(row.get(day))]
    if day_values:
        return int(sum(day_values))
    if "Totalt" in row.index and pd.notna(row.get("Totalt")):
        return int(row["Totalt"])
    return None


def group_teams_by_total_score(
    leaderboard: pd.DataFrame,
    through_round: int,
) -> list[tuple[int, list[str]]]:
    """Group teams with identical total score. Ignores Plass and row index."""
    lb = normalize_leaderboard_input(leaderboard)
    if lb.empty or "Lag" not in lb.columns:
        return []

    by_score: dict[int, list[str]] = {}
    for _, row in lb.iterrows():
        total = team_total_through_round(row, through_round)
        if total is None:
            continue
        by_score.setdefault(total, []).append(str(row["Lag"]))

    return [
        (score, sorted(teams))
        for score, teams in sorted(by_score.items(), key=lambda item: item[0])
    ]


def cumulative_ranking(leaderboard: pd.DataFrame, through_round: int) -> pd.DataFrame:
    groups = group_teams_by_total_score(leaderboard, through_round)
    if not groups:
        return pd.DataFrame(columns=["Lag", "cum", "plass"])

    rows: list[dict[str, Any]] = []
    rank = 1
    for score, teams in groups:
        for team in teams:
            rows.append({"Lag": team, "cum": score, "plass": rank})
        rank += len(teams)
    return pd.DataFrame(rows)


def format_team_list(teams: list[str]) -> str:
    if not teams:
        return ""
    if len(teams) == 1:
        return teams[0]
    if len(teams) == 2:
        return f"{teams[0]} og {teams[1]}"
    return ", ".join(teams[:-1]) + f" og {teams[-1]}"


def format_stroke_gap(gap: int) -> str:
    gap_words = {1: "ett", 2: "to", 3: "tre", 4: "fire"}
    return f"{gap_words.get(gap, str(gap))} slag"


def format_count_word(count: int) -> str:
    count_words = {2: "To", 3: "Tre", 4: "Fire", 5: "Fem"}
    return count_words.get(count, str(count))


def describe_leadership(leaders: list[str], score: int) -> str:
    names = format_team_list(leaders)
    score_text = fmt_relative(score)
    if len(leaders) == 1:
        return f"{names} leder alene på {score_text}"
    return f"{names} deler ledelsen på {score_text}"


def describe_chasers(chasers: list[str], gap: int) -> str:
    if not chasers:
        return ""
    names = format_team_list(chasers)
    gap_text = format_stroke_gap(gap)
    if len(chasers) == 1:
        return f"{names} følger {gap_text} bak"
    return f"{names} følger {gap_text} bak"


def populate_standings_fields(data: DailyReportData, groups: list[tuple[int, list[str]]]) -> None:
    if not groups:
        return

    data.score_groups = groups
    leader_score, leaders = groups[0]
    data.leader_score = leader_score
    data.leaders = leaders

    data.top3 = [
        (team, score)
        for score, teams in groups[:3]
        for team in teams
    ][:3]

    bottom_score, bottom_teams = groups[-1]
    data.bottom_team = bottom_teams[-1]
    data.bottom_score = bottom_score

    if len(groups) < 2:
        data.chasers = []
        data.chaser_score = None
        data.chaser_gap = None
        data.leader_gap = None
        return

    chaser_score, chasers = groups[1]
    data.chaser_score = chaser_score
    data.chasers = chasers
    data.chaser_gap = chaser_score - leader_score
    data.leader_gap = data.chaser_gap


def describe_top_score_groups(groups: list[tuple[int, list[str]]], limit: int = 3) -> str:
    if not groups:
        return ""
    parts: list[str] = []
    for score, teams in groups[:limit]:
        label = format_team_list(teams)
        parts.append(f"{label} ({fmt_relative(score)})")
    return ", ".join(parts)


def contains_forbidden_placement_text(body: str, leaders: list[str]) -> list[str]:
    lowered = body.lower()
    hits = [phrase for phrase in FORBIDDEN_PLACEMENT_PHRASES if phrase in lowered]
    if len(leaders) > 1:
        if "leder alene" in lowered:
            hits.append("leder alene")
        for co_leader in leaders[1:]:
            if f"{co_leader.lower()} jager" in lowered:
                hits.append(f"{co_leader} jager")
    return hits


def rank_movement(leaderboard: pd.DataFrame, round_no: int) -> pd.DataFrame:
    if round_no <= 1 or leaderboard.empty:
        return pd.DataFrame(columns=["Lag", "delta"])

    current = cumulative_ranking(leaderboard, round_no).set_index("Lag")["plass"]
    previous = cumulative_ranking(leaderboard, round_no - 1).set_index("Lag")["plass"]
    shared = current.index.intersection(previous.index)
    if shared.empty:
        return pd.DataFrame(columns=["Lag", "delta"])

    delta = previous.loc[shared] - current.loc[shared]
    return pd.DataFrame({"Lag": delta.index, "delta": delta.values.astype(int)})


def biggest_mover(leaderboard: pd.DataFrame, round_no: int) -> tuple[str, int] | None:
    movement = rank_movement(leaderboard, round_no)
    climbers = movement[movement["delta"] > 0]
    if climbers.empty:
        return None
    row = climbers.loc[climbers["delta"].idxmax()]
    return str(row.Lag), int(row.delta)


def biggest_faller(leaderboard: pd.DataFrame, round_no: int) -> tuple[str, int] | None:
    movement = rank_movement(leaderboard, round_no)
    fallers = movement[movement["delta"] < 0]
    if fallers.empty:
        return None
    row = fallers.loc[fallers["delta"].idxmin()]
    return str(row.Lag), int(abs(row.delta))


def analyze_daily_report(
    leaderboard: pd.DataFrame,
    details: pd.DataFrame,
    round_no: int,
) -> DailyReportData:
    day_label = DAYS[round_no - 1]
    data = DailyReportData(round_no=round_no, day_label=day_label)

    if leaderboard.empty:
        return data

    groups = group_teams_by_total_score(leaderboard, round_no)
    if groups:
        populate_standings_fields(data, groups)

    data.mover = biggest_mover(leaderboard, round_no)
    data.faller = biggest_faller(leaderboard, round_no)

    if day_label in leaderboard.columns:
        day_scores = normalize_leaderboard_input(leaderboard)[["Lag", day_label]].dropna()
        if not day_scores.empty:
            data.has_day_scores = True
            best_score = int(day_scores[day_label].min())
            worst_score = int(day_scores[day_label].max())
            data.best_day_score = best_score
            data.worst_day_score = worst_score
            data.best_day_teams = day_scores[day_scores[day_label] == best_score]["Lag"].astype(str).tolist()
            data.worst_day_teams = day_scores[day_scores[day_label] == worst_score]["Lag"].astype(str).tolist()
            data.best_day_team = data.best_day_teams[0]
            data.worst_day_team = data.worst_day_teams[0]

    if not details.empty and "Runde" in details.columns:
        day_details = details[details["Runde"] == round_no].copy()
        counting = day_details[day_details["Teller"] == COUNTING_LABEL].dropna(subset=["Score"])
        dropped = day_details[day_details["Teller"] == DROPPED_LABEL].dropna(subset=["Score"])

        if not counting.empty:
            helper_counts = counting.groupby("Spiller").size().sort_values(ascending=False)
            data.top_helpers = [
                (name, int(count)) for name, count in helper_counts.head(3).items()
            ]
            data.avg_counting_score = float(counting["Score"].mean())
            data.under_par_counting = int((counting["Score"] < 0).sum())

            heroes = counting.sort_values("Score", ascending=True).head(3)
            data.day_heroes = [
                (row.Spiller, int(row.Score), row.Lag) for _, row in heroes.iterrows()
            ]

        if not dropped.empty:
            hurter_counts = dropped.groupby("Spiller").size().sort_values(ascending=False)
            data.top_hurters = [
                (name, int(count)) for name, count in hurter_counts.head(3).items()
            ]
            villains = dropped.sort_values("Score", ascending=False).head(3)
            data.day_villains = [
                (row.Spiller, int(row.Score), row.Lag) for _, row in villains.iterrows()
            ]
            notable = dropped.sort_values("Score", ascending=False).head(3)
            data.notable_drops = [
                (row.Spiller, row.Lag, int(row.Score)) for _, row in notable.iterrows()
            ]

    return data


def _join_names(items: list[tuple[str, int]], suffix: str) -> str:
    if not items:
        return ""
    parts = []
    for name, count in items:
        parts.append(name if count == 1 else f"{name} ({count} {suffix})")
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} og {parts[1]}"
    return ", ".join(parts[:-1]) + f" og {parts[-1]}"


def _hero_line(heroes: list[tuple[str, int, str]]) -> str:
    if not heroes:
        return ""
    bits = [f"{player} ({fmt_relative(score)} for {team})" for player, score, team in heroes[:2]]
    return " og ".join(bits)


def _standings_summary(data: DailyReportData) -> str:
    if not data.leaders or data.leader_score is None:
        return ""

    parts = [describe_leadership(data.leaders, data.leader_score) + "."]
    if data.chasers and data.chaser_gap:
        parts.append(describe_chasers(data.chasers, data.chaser_gap) + ".")
    return " ".join(parts)


def _title(data: DailyReportData, tone: str) -> str:
    if not data.leaders:
        return f"{data.day_label} – dagsrapport"

    leader_label = format_team_list(data.leaders)
    tied = len(data.leaders) > 1
    pools = {
        "Saklig": [
            f"{data.day_label}: {leader_label} {'deler ledelsen' if tied else 'leder kupongen'}",
            f"{data.day_label} – status fra fantasy-bordet",
        ],
        "Morsom": [
            f"{data.day_label}: dødt løp i toppen" if tied else f"{data.day_label}: {leader_label} tror han eier dette",
            f"{data.day_label} – nok en dag med golf og dårlige unnskyldninger",
            f"{data.day_label}: {leader_label} på topp, resten på terapi" if not tied else f"{data.day_label}: alle leder, ingen tror det",
        ],
        "Frekk": [
            f"{data.day_label}: {leader_label} og illusjonen om kontroll",
            f"{data.day_label} – der fantasien møter virkeligheten (og tap)",
        ],
        "Brutal": [
            f"{data.day_label}: {leader_label} leder, mirakel eller mareritt?" if not tied else f"{data.day_label}: ingen eier toppen, alle later som",
            f"{data.day_label} – noen burde sjekke egne lagvalg",
        ],
    }
    return pick_variant(pools.get(tone, pools["Morsom"]), f"title-{data.day_label}-{leader_label}")


def _intro(data: DailyReportData, tone: str) -> str:
    if not data.leaders or data.leader_score is None:
        return f"{data.day_label} er ikke klar for oppsummering ennå. Noen må faktisk spille golf først."

    standings = _standings_summary(data)
    leader_label = format_team_list(data.leaders)
    leader_total = data.leader_score
    pools = {
        "Saklig": [
            (
                f"{data.day_label} er i boks. {standings} "
                f"Det er status etter {data.round_no} runde{'r' if data.round_no > 1 else ''} av fantasy-kupongen."
            ),
        ],
        "Morsom": [
            (
                f"{data.day_label} er ferdig, og vi har sett nok dårlige scorekort til å fylle en søppelkasse. "
                f"{standings} Ingen her innbiller seg at dette er over."
            ),
            (
                f"Enda en {data.day_label.lower()} med US Open i fantasy-format. "
                f"{standings} Resten later som de ikke bryr seg. Vi vet bedre."
            ),
        ],
        "Frekk": [
            (
                f"{data.day_label} er overstått. {standings} "
                f"Enten har de flaks, eller så har resten valgt spillere med eksistensiell krise på banen."
            ),
        ],
        "Brutal": [
            (
                f"{data.day_label}: {standings} "
                f"Gratulerer til {leader_label} – dere slår venner som tydeligvis trodde «gut feeling» var en strategi."
                if len(data.leaders) == 1
                else (
                    f"{data.day_label}: {standings} "
                    f"Ingen av dere eier toppen alene, men alle later som de hadde planen."
                )
            ),
        ],
    }
    return pick_variant(pools[tone], f"intro-{tone}-{leader_label}")


def _leader_duel(data: DailyReportData, tone: str) -> str:
    if not data.leaders or data.leader_score is None:
        return ""

    tied = len(data.leaders) > 1
    leader_label = format_team_list(data.leaders)
    score_text = fmt_relative(data.leader_score)

    if tone == "Saklig":
        base = describe_leadership(data.leaders, data.leader_score)
        if tied:
            base += ". Det er delt ledelse i toppen"
        if data.chasers and data.chaser_gap:
            base += f". {describe_chasers(data.chasers, data.chaser_gap)}"
        if data.mover and data.mover[0] not in data.leaders:
            base += f". {data.mover[0]} klatret {data.mover[1]} plass{'er' if data.mover[1] != 1 else ''} og presser på"
        if data.faller:
            team, places = data.faller
            base += f", mens {team} falt {places} plass{'er' if places != 1 else ''}"
        if len(data.score_groups) > 1:
            base += f" Topp tre scoregrupper: {describe_top_score_groups(data.score_groups)}."
        return base + "."

    if tone == "Morsom":
        if tied:
            base = (
                f"{leader_label} deler ledelsen på {score_text}. "
                f"Det er dødt løp i toppen mellom {leader_label}, og ingen vil innrømme at de er nervøse."
            )
        else:
            lines = [
                (
                    f"{leader_label} sitter alene på toppen med {score_text}, "
                    f"men det lukter ikke akkurat kontroll."
                ),
                (
                    f"{leader_label} klamrer seg til teten som en amatør på klubbmesterskapet "
                    f"({score_text} totalt)."
                ),
            ]
            base = pick_variant(lines, f"ld-m-{leader_label}")
        if data.chasers and data.chaser_gap:
            base += f" {describe_chasers(data.chasers, data.chaser_gap).capitalize()}."
        if data.mover:
            team, places = data.mover
            base += (
                f" Størst opptur: {team} (+{places}), som endelig fikk noen på laget til å møte opp."
            )
        return base

    if tone == "Frekk":
        if tied:
            base = (
                f"{leader_label} deler ledelsen på {score_text}. "
                f"Ingen av dem eier toppen alene, men alle oppfører seg som om de gjør det."
            )
        else:
            base = (
                f"{leader_label} leder alene på {score_text} og oppfører seg som om trofeet allerede står i stua."
            )
        if data.chasers and data.chaser_gap:
            chasers = format_team_list(data.chasers)
            base += (
                f" {chasers} ligger {format_stroke_gap(data.chaser_gap)} bak og burde slutte å stole på spillere "
                f"som tror US Open er en oppvarming."
            )
        if data.faller:
            team, places = data.faller
            base += f" {team} falt {places} plass{'er' if places != 1 else ''} og ser ut som de angrer draften allerede."
        return base

    if tied:
        base = (
            f"{leader_label} deler ledelsen på {score_text}. "
            f"Alle leder, ingen imponerer."
        )
    else:
        base = (
            f"{leader_label} leder alene ({score_text}). Ja, vi er også overrasket over at det holdt."
        )
    if data.chasers and data.chaser_gap:
        chasers = format_team_list(data.chasers)
        base += (
            f" {chasers} jager {format_stroke_gap(data.chaser_gap)} bak, "
            f"men med de lagene deres er det mer ønsketenkning enn strategi."
        )
    if data.mover and data.mover[0] in data.leaders:
        base += f" Og ja, {data.mover[0]} klatret også i dag. Irriterende effektivt."
    elif data.mover:
        base += f" {data.mover[0]} stjal noen plasser, men ingen er redde ennå."
    return base


def _day_winner(data: DailyReportData, tone: str) -> str:
    if not data.has_day_scores or not data.best_day_teams or data.best_day_score is None:
        return "Ingen dagsscore å kåre vinner fra ennå."

    best = fmt_relative(data.best_day_score)
    teams = format_team_list(data.best_day_teams)
    tied = len(data.best_day_teams) > 1

    pools = {
        "Saklig": [
            (
                f"Dagens beste lagscore: {teams} med {best}."
                + (" Delt dagens beste runde." if tied else " Det var dagens minste skade på kupongen.")
            ),
        ],
        "Morsom": [
            (
                f"Dagens vinner på banen (eller i hvert fall i fantasy): {teams} med {best}. "
                f"Endelig en dag der noen på laget faktisk bidro."
            ),
            (
                f"{teams} leverte dagens beste runde ({best}). "
                f"Resten av feltet tar notater, eller burde gjøre det."
            ),
        ],
        "Frekk": [
            f"{teams} vant dagen med {best}. De andre så på og håpet på cut.",
            f"Dagens king: {teams} ({best}). For en gangs skyld var det ikke bare flaks.",
        ],
        "Brutal": [
            (
                f"{teams} hadde dagens eneste presentable scorekort ({best}). "
                f"Resten av oss lever i fornektelse."
            ),
            (
                f"{teams} tok dagen med {best}. "
                f"Hvis du ikke er på den listen, var dagen din sannsynligvis pinlig."
            ),
        ],
    }
    text = pick_variant(pools[tone], f"win-{teams}-{best}")

    if data.day_heroes:
        hero = data.day_heroes[0]
        player, score, hero_team = hero
        if hero_team in data.best_day_teams:
            extras = {
                "Saklig": f" Stor bidragsyter: {player} ({fmt_relative(score)}).",
                "Morsom": f" {player} gjorde jobben sin ({fmt_relative(score)}). Hvem visste det?",
                "Frekk": f" {player} bar laget på ryggen ({fmt_relative(score)}). Helten ingen ventet.",
                "Brutal": f" Uten {player} ({fmt_relative(score)}) hadde {hero_team} vært middelmådig som resten.",
            }
            text += extras[tone]
    return text


def _day_disaster(data: DailyReportData, tone: str) -> str:
    if not data.has_day_scores or not data.worst_day_teams or data.worst_day_score is None:
        return ""

    if set(data.worst_day_teams) == set(data.best_day_teams):
        return ""

    worst = fmt_relative(data.worst_day_score)
    teams = format_team_list(data.worst_day_teams)

    pools = {
        "Saklig": [
            f"Dagens tyngste lagscore: {teams} med {worst}.",
        ],
        "Morsom": [
            f"Dagens katastrofe: {teams} ({worst}). Noen på det laget burde få ferie fra golf, eller fra fantasy.",
            f"{teams} leverte {worst} og beviste at håp alene ikke er en taktikk.",
        ],
        "Frekk": [
            f"{teams} tok en på trynet med {worst}. Draften deres lukter panikk.",
            f"Syndebukk-nummer én i dag: {teams} ({worst}). Selv ikke mamma trøster på det nivået.",
        ],
        "Brutal": [
            f"{teams} ({worst}). Trenger ikke birdies lenger – trenger et mindre mirakel.",
            f"{teams} lever fortsatt på håpet og tilfeldighetene ({worst}). Det går ikke bra. Det går aldri bra.",
        ],
    }
    text = pick_variant(pools[tone], f"dis-{teams}")

    if data.day_villains:
        villain = next(
            (v for v in data.day_villains if v[2] in data.worst_day_teams),
            data.day_villains[0],
        )
        player, score, _ = villain
        text += f" {player} leverte {fmt_relative(score)} som droppet score – klassisk."
    return text


def _key_players(data: DailyReportData, tone: str) -> str:
    chunks: list[str] = []

    if data.top_helpers:
        helpers = _join_names(data.top_helpers, "lag")
        helper_lines = {
            "Saklig": f"Varme spillere som tellte for flest lag: {helpers}.",
            "Morsom": f"På banen var {helpers} de som faktisk jobbet. Resten tok kaffepause.",
            "Frekk": f"{helpers} reddet dagen for flere lag. Uten dem hadde dette vært pinlig for alle.",
            "Brutal": f"{helpers} var eneste grunn til at noen av dere fortsatt har en kupong verdt å vise frem.",
        }
        chunks.append(helper_lines[tone])

    if data.top_hurters:
        hurters = _join_names(data.top_hurters, "dropp")
        cold_lines = {
            "Saklig": f"Kalde spillere som ble droppet oftest: {hurters}.",
            "Morsom": f"{hurters} var så kalde at flere lag måtte droppe dem fra tellende score.",
            "Frekk": f"{hurters} ødela kvelden for mange. Takk for ingenting.",
            "Brutal": f"{hurters} burde få en skriftlig advarsel for hvordan de saboterer fantasy-lag.",
        }
        chunks.append(cold_lines[tone])

    if data.day_heroes:
        hero_text = _hero_line(data.day_heroes)
        hero_lines = {
            "Saklig": f"Dagens beste tellende scorer: {hero_text}.",
            "Morsom": f"Heltene på banen: {hero_text}.",
            "Frekk": f"De som faktisk spilte golf i dag: {hero_text}.",
            "Brutal": f"Eneste spillere med verdighet i dag: {hero_text}.",
        }
        chunks.append(hero_lines[tone])

    if data.notable_drops:
        drop_bits = [
            f"{player} ({fmt_relative(score)} hos {team})"
            for player, team, score in data.notable_drops[:2]
        ]
        drop_lines = {
            "Saklig": f"Merkverdige dropp: {' og '.join(drop_bits)}.",
            "Morsom": f"Store dropp som gjorde vondt: {' og '.join(drop_bits)}.",
            "Frekk": f"Syndebukker på scorekortet: {' og '.join(drop_bits)}.",
            "Brutal": f"Spillere som burde sittet i bilen: {' og '.join(drop_bits)}.",
        }
        chunks.append(drop_lines[tone])

    if not chunks:
        return "Banen var stille i dag – eller ingen tellende scorer er registrert ennå."

    return " ".join(chunks)


def _winner_outlook(data: DailyReportData, tone: str) -> str:
    if not data.leaders or data.leader_score is None:
        return "For tidlig å spå vinner. Ingen data, ingen respekt."

    leader_label = format_team_list(data.leaders)
    leader_total = data.leader_score
    tied = len(data.leaders) > 1
    chasers = format_team_list(data.chasers) if data.chasers else None
    gap = data.chaser_gap

    if tone == "Saklig":
        if tied:
            return (
                f"{leader_label} deler toppen på {fmt_relative(leader_total)} og har like god sjanse til å vinne nå."
            )
        if chasers and gap is not None and gap <= 3:
            return (
                f"{leader_label} har best sjanse nå med {fmt_relative(leader_total)}. "
                f"{chasers} er bare {format_stroke_gap(gap)} bak og kan ta over med en sterk runde til."
            )
        return (
            f"{leader_label} har overtaket med {fmt_relative(leader_total)} og ser mest stabil ut akkurat nå. "
            f"Jaget må bli aggressivt for å ta igjen poengene."
        )

    if tone == "Morsom":
        if tied:
            return (
                f"Vinnerfavoritt? {leader_label} – de deler ledelsen og ingen vil gi seg. "
                f"Dette blir en tittelkamp, eller en lang krig om hvem som er minst dårlig."
            )
        if data.mover and data.mover[0] in data.leaders:
            return (
                f"{leader_label} leder og fikk momentum i dag. Farlig kombinasjon for resten, "
                f"med mindre laget deres fortsetter å sove."
            )
        if chasers and gap is not None and gap <= 4:
            return (
                f"{leader_label} er favoritt, men {chasers} er bare {format_stroke_gap(gap)} bak. "
                f"Det er fortsatt håp – tynt, men håp."
            )
        return (
            f"Om jeg skulle satset en kaffekopp: {leader_label}. "
            f"Ikke fordi de er geniale, men fordi de andre er mer kaotiske."
        )

    if tone == "Frekk":
        if tied:
            return (
                f"{leader_label} deler favorittstatus på {fmt_relative(leader_total)}. "
                f"Ingen har kontroll, alle later som de har det."
            )
        return (
            f"{leader_label} har best sjanse til å vinne nå. "
            f"Resten må enten bytte halve laget eller begynne å lyve om handicap."
        )

    if tied:
        return (
            f"Vinnerfavoritt? Alle i toppen: {leader_label}. "
            f"Ingen fortjener det mer enn de andre, men noen må tape til slutt."
        )
    return (
        f"Vinnerfavoritt: {leader_label}. Ikke fordi de fortjener det, "
        f"men fordi konkurrentene draftet som om de var fulle på treningsrunden."
    )


def _last_place_jab(data: DailyReportData, tone: str) -> str:
    if not data.bottom_team or not data.leaders:
        return ""

    if data.bottom_team in data.leaders:
        return ""

    bottom = data.bottom_team
    bottom_score = data.bottom_score

    pools = {
        "Saklig": [
            f"Til slutt: {bottom} ligger sist med {fmt_relative(bottom_score or 0)}. Det er fortsatt mulig å snu, men det krever mer enn flaks.",
        ],
        "Morsom": [
            f"Og til {bottom} på sisteplass ({fmt_relative(bottom_score or 0)}): vi heier på deg. "
            f"Men kanskje ta en ekstra kikk på laget før neste runde?",
            f"{bottom} er bakerst ({fmt_relative(bottom_score or 0)}). Ikke gi opp – eller gi opp, det er også en strategi.",
        ],
        "Frekk": [
            f"{bottom} ligger sist ({fmt_relative(bottom_score or 0)}). "
            f"Fantasy-golf er brutalt, men dette er ekstra brutalt.",
        ],
        "Brutal": [
            f"{bottom} ({fmt_relative(bottom_score or 0)}). Du er ikke ute av konkurransen. "
            f"Du er bare ute av realiteten.",
            f"Shoutout til {bottom} på bunn ({fmt_relative(bottom_score or 0)}): "
            f"takk for at noen måtte være eksempel på hvordan man ikke gjør det.",
        ],
    }
    return pick_variant(pools[tone], f"last-{bottom}")


def _assemble_sections(data: DailyReportData, tone: str) -> list[tuple[str, str]]:
    return [
        ("Kort intro", _intro(data, tone)),
        ("Lederduell", _leader_duel(data, tone)),
        ("Dagens vinner", _day_winner(data, tone)),
        ("Dagens katastrofe", _day_disaster(data, tone)),
        ("Viktigste spillere på banen", _key_players(data, tone)),
        ("Hvem har best sjanse til å vinne nå", _winner_outlook(data, tone)),
        ("Avsluttende stikk", _last_place_jab(data, tone)),
    ]


def _format_body(sections: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for heading, text in sections:
        text = text.strip()
        if not text:
            continue
        parts.append(f"{heading}\n{text}")
    return "\n\n".join(parts)


def _trim_to_word_limit(body: str, max_words: int = MAX_WORDS) -> str:
    if word_count(body) <= max_words:
        return body

    sections = body.split("\n\n")
    while sections and word_count("\n\n".join(sections)) > max_words:
        sections.pop()
    trimmed = "\n\n".join(sections).strip()
    if trimmed and word_count(trimmed) > max_words:
        words = trimmed.split()
        trimmed = " ".join(words[:max_words]).rstrip(".,;:") + "..."
    return trimmed


def _pad_to_word_minimum(body: str, data: DailyReportData, tone: str, min_words: int = MIN_WORDS) -> str:
    if word_count(body) >= min_words:
        return body

    extras: list[str] = []
    if data.faller and data.faller[0] not in body:
        team, places = data.faller
        extras.append(f"{team} mistet {places} plass{'er' if places != 1 else ''} i dag og må finne ny tro på livet.")

    if data.mover and data.mover[0] not in body:
        team, places = data.mover
        extras.append(f"{team} klatret {places} plass{'er' if places != 1 else ''} og skaper faktisk litt drama i kupongen.")

    if data.leader_gap is not None and data.leaders and data.chasers:
        leader_label = format_team_list(data.leaders)
        chasers = format_team_list(data.chasers)
        if str(data.leader_gap) not in body:
            extras.append(
                f"Avstanden mellom {leader_label} og {chasers} er {format_stroke_gap(data.leader_gap)}. "
                f"Liten nok til å skape paranoia, stor nok til å skape unnskyldninger."
            )

    if data.avg_counting_score is not None:
        avg = data.avg_counting_score
        if avg <= -0.5:
            extras.append("Tellende scorer var sterke i dag – banen var ikke gratis.")
        elif avg >= 0.5:
            extras.append("Det var en tung dag for tellende scorer. Mange over par.")

    if data.under_par_counting >= 6:
        extras.append(f"{data.under_par_counting} tellende scorer under par. Noen gjorde faktisk jobben sin.")

    for extra in extras:
        body = body + "\n\n" + extra
        if word_count(body) >= min_words:
            break

    if word_count(body) < min_words:
        tail = {
            "Saklig": (
                f"Oppsummert: {data.day_label} ga både bevegelser i tabellen og tydelige bidrag fra enkeltspillere. "
                f"Neste runde avgjør om lederen får ro i sjelen eller om jakten åpner seg."
            ),
            "Morsom": (
                f"Dette var {data.day_label.lower()} i fantasy-kupongen: litt golf, mye følelser, "
                f"og minst én deltaker som kommer til å skylde på DataGolf i morgen også."
            ),
            "Frekk": (
                f"Konklusjon etter {data.day_label.lower()}: noen spilte smart, noen spilte som om de hadde "
                f"ferie på banen, og alle later som de hadde sett dette komme."
            ),
            "Brutal": (
                f"Kort oppsummert {data.day_label.lower()}: dere er venner, men ingen her taper med verdighet. "
                f"Neste runde blir mer skade hvis dere ikke skjerper dere."
            ),
        }
        body = body + "\n\n" + tail.get(tone, tail["Morsom"])

    while word_count(body) < min_words and data.leaders:
        leader_label = format_team_list(data.leaders)
        filler = (
            f"{leader_label} {'deler fortsatt ledelsen' if len(data.leaders) > 1 else 'har fortsatt ledelsen'} "
            f"etter {data.day_label.lower()}, og resten av feltet har en runde til å gjøre noe med det – "
            f"eller fortsette å hengsle seg selv."
        )
        if filler in body:
            body = body + (
                f"\n\n{data.day_label} er omme, og tabellen forteller en tydelig historie: "
                f"noen leverer, andre håper på mirakler."
            )
            break
        body = body + "\n\n" + filler

    return body


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
    title = _title(data, tone)

    if not data.has_day_scores and not data.leaders:
        body = f"Ingen scorer er registrert for {data.day_label} ennå."
        return title, body

    sections = _assemble_sections(data, tone)
    body = _format_body(sections)
    body = _pad_to_word_minimum(body, data, tone)
    body = _trim_to_word_limit(body)

    lowered = body.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            body = body.replace(phrase, "noe annet skjedde")

    forbidden_hits = contains_forbidden_placement_text(body, data.leaders)
    if forbidden_hits:
        raise ValueError(
            "Dagsrapport brukte ugyldig plasseringstekst: "
            + ", ".join(sorted(set(forbidden_hits)))
        )

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
            {
                "Lag": "Thomas",
                "Dag": "Dag 2",
                "Runde": 2,
                "Spiller": "Scottie Scheffler",
                "Score": -2,
                "Teller": COUNTING_LABEL,
            },
            {
                "Lag": "Thomas",
                "Dag": "Dag 2",
                "Runde": 2,
                "Spiller": "Jon Rahm",
                "Score": 4,
                "Teller": DROPPED_LABEL,
            },
            {
                "Lag": "Lars",
                "Dag": "Dag 2",
                "Runde": 2,
                "Spiller": "Dustin Johnson",
                "Score": 6,
                "Teller": DROPPED_LABEL,
            },
            {
                "Lag": "Christine",
                "Dag": "Dag 2",
                "Runde": 2,
                "Spiller": "Scottie Scheffler",
                "Score": -1,
                "Teller": COUNTING_LABEL,
            },
        ]
    )

    title, body = generate_daily_report(leaderboard, details, 2, tone="Morsom")
    brutal_title, brutal_body = generate_daily_report(leaderboard, details, 2, tone="Brutal")
    mover = biggest_mover(leaderboard, 2)
    faller = biggest_faller(leaderboard, 2)
    words = word_count(body)

    checks = [
        {
            "name": "Leader mentioned",
            "passed": "Thomas" in body,
            "expected": "Thomas",
            "actual": body[:120],
        },
        {
            "name": "Biggest mover detected",
            "passed": mover == ("Thomas", 2),
            "expected": ("Thomas", 2),
            "actual": mover,
        },
        {
            "name": "Biggest faller detected",
            "passed": faller == ("Christine", 1),
            "expected": ("Christine", 1),
            "actual": faller,
        },
        {
            "name": "Structured sections present",
            "passed": "Lederduell" in body and "Dagens vinner" in body,
            "expected": "section headings",
            "actual": body[:200],
        },
        {
            "name": "Word count in range",
            "passed": MIN_WORDS <= words <= MAX_WORDS,
            "expected": f"{MIN_WORDS}-{MAX_WORDS}",
            "actual": words,
        },
        {
            "name": "Brutal tone differs",
            "passed": brutal_body != body,
            "expected": "different text",
            "actual": brutal_body[:80],
        },
        {
            "name": "No banned journalist clichés",
            "passed": not any(p in body.lower() for p in BANNED_PHRASES),
            "expected": "clean",
            "actual": body,
        },
    ]

    tied_two = pd.DataFrame(
        [
            {"Lag": "Anders", "Dag 1": -2},
            {"Lag": "Thomas", "Dag 1": -2},
            {"Lag": "Philip", "Dag 1": -1},
        ]
    )
    _, tied_body = generate_daily_report(tied_two, pd.DataFrame(), 1, tone="Saklig")
    checks.extend(
        [
            {
                "name": "Two-way tie shares leadership",
                "passed": "deler ledelsen" in tied_body and "Anders" in tied_body and "Thomas" in tied_body,
                "expected": "shared leadership wording",
                "actual": tied_body[:250],
            },
            {
                "name": "Tied leader not called second place",
                "passed": "andreplass" not in tied_body.lower() and "nr. 2" not in tied_body.lower(),
                "expected": "no false second place",
                "actual": tied_body,
            },
            {
                "name": "Chaser described by strokes",
                "passed": "Philip" in tied_body and "ett slag" in tied_body,
                "expected": "Philip one stroke behind",
                "actual": tied_body,
            },
        ]
    )

    tied_three = pd.DataFrame(
        [
            {"Lag": "Anders", "Dag 1": -5},
            {"Lag": "Thomas", "Dag 1": -5},
            {"Lag": "Philip", "Dag 1": -5},
        ]
    )
    _, three_way_body = generate_daily_report(tied_three, pd.DataFrame(), 1, tone="Saklig")
    checks.append(
        {
            "name": "Three-way tie at top",
            "passed": "Anders, Philip og Thomas deler ledelsen på -5" in three_way_body,
            "expected": "three teams share lead by name",
            "actual": three_way_body[:250],
        }
    )

    app_like_tie = pd.DataFrame(
        [
            {"Plass": 1, "Lag": "Anders", "Dag 1": -2, "Totalt": -2},
            {"Plass": 2, "Lag": "Thomas", "Dag 1": -2, "Totalt": -2},
        ]
    )
    app_title, app_body = generate_daily_report(app_like_tie, pd.DataFrame(), 1, tone="Morsom")
    checks.extend(
        [
            {
                "name": "App-like tied leaderboard shares lead",
                "passed": "Anders og Thomas deler ledelsen på -2" in app_body,
                "expected": "shared leadership from app dataframe",
                "actual": app_body,
            },
            {
                "name": "App-like tied leaderboard avoids row placement text",
                "passed": not contains_forbidden_placement_text(app_body, ["Anders", "Thomas"]),
                "expected": "no forbidden placement phrases",
                "actual": contains_forbidden_placement_text(app_body, ["Anders", "Thomas"]),
            },
        ]
    )

    solo_gap = pd.DataFrame(
        [
            {"Lag": "Anders", "Dag 1": -5},
            {"Lag": "Thomas", "Dag 1": -3},
        ]
    )
    _, solo_body = generate_daily_report(solo_gap, pd.DataFrame(), 1, tone="Saklig")
    checks.extend(
        [
            {
                "name": "Solo leader wording",
                "passed": "leder alene" in solo_body,
                "expected": "solo leader",
                "actual": solo_body[:200],
            },
            {
                "name": "Gap to chaser in strokes",
                "passed": "to slag" in solo_body and "Thomas" in solo_body,
                "expected": "two strokes behind",
                "actual": solo_body,
            },
        ]
    )

    ranked = cumulative_ranking(tied_two, 1)
    checks.append(
        {
            "name": "Competition ranking assigns shared rank",
            "passed": (
                int(ranked.loc[ranked.Lag == "Anders", "plass"].iloc[0])
                == int(ranked.loc[ranked.Lag == "Thomas", "plass"].iloc[0])
                == 1
                and int(ranked.loc[ranked.Lag == "Philip", "plass"].iloc[0]) == 3
            ),
            "expected": "1,1,3 ranks",
            "actual": ranked.to_dict("records"),
        }
    )
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "sample_title": title,
        "sample_body": body,
        "brutal_sample": brutal_body,
        "app_like_title": app_title,
        "app_like_body": app_body,
    }
