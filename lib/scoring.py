"""Fantasy golf scoring calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib import roster_changes


# A completed round must always expose exactly five counting and two dropped
# players. Equal round scores are ordered by normalized display name, then
# player_id as a final uniqueness guard. No previous-round or tournament total
# participates in this tie-break.
COMPLETED_ROUND_TIE_BREAK = "round score, player name, player_id"


@dataclass
class PlayerRoundResult:
    player_id: str
    player_name: str
    tier: int
    strokes: int | None
    counts: bool = False
    dropped: bool = False
    status: str | None = None
    score_kind: str = "ACTUAL"


@dataclass
class TeamRoundResult:
    round_num: int
    total: int | None
    counting: list[PlayerRoundResult]
    dropped: list[PlayerRoundResult]
    undecided: list[PlayerRoundResult]
    missing_scores: list[PlayerRoundResult]


@dataclass
class TeamStanding:
    team_id: str
    team_name: str
    round_totals: dict[int, int | None]
    tournament_total: int | None
    completed_rounds: int
    rounds: dict[int, TeamRoundResult]
    original_player_ids: tuple[str, ...] = ()
    active_player_ids: tuple[str, ...] = ()


def format_relative_score(value: int | None) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "E"
    return f"+{value}" if value > 0 else f"−{abs(value)}"


def _split_counting_and_dropped(
    player_results: list[PlayerRoundResult],
    counting_scores: int,
    dropped_scores: int,
    penalty_score: int | None = None,
    mark_cutoff_ties_undecided: bool = False,
    resolve_completed_ties: bool = False,
) -> tuple[
    list[PlayerRoundResult],
    list[PlayerRoundResult],
    list[PlayerRoundResult],
    int | None,
]:
    scored = [result for result in player_results if result.strokes is not None]
    missing = [result for result in player_results if result.strokes is None]

    if len(scored) < counting_scores:
        needed = counting_scores - len(scored)
        eligible_for_penalty = [
            result for result in missing if result.status in {"CUT", "WD", "DQ"}
        ]
        if resolve_completed_ties:
            eligible_for_penalty.sort(
                key=lambda item: (item.player_name.casefold(), item.player_id)
            )
        if penalty_score is not None and len(eligible_for_penalty) >= needed:
            penalty_results = eligible_for_penalty[:needed]
            for result in penalty_results:
                result.strokes = penalty_score
                result.score_kind = "PENALTY"
            combined = scored + penalty_results
            combined.sort(
                key=lambda item: (
                    item.strokes if item.strokes is not None else 999999,
                    item.player_name.casefold() if resolve_completed_ties else "",
                    item.player_id if resolve_completed_ties else "",
                )
            )
            for result in combined:
                result.counts = True
            dropped = [result for result in player_results if result not in combined]
            for result in dropped:
                result.dropped = True
            return combined, dropped, [], sum(
                result.strokes for result in combined if result.strokes is not None
            )
        for result in missing:
            result.dropped = True
        return [], missing, [], None

    scored.sort(
        key=lambda item: (
            item.strokes,
            item.player_name.casefold() if resolve_completed_ties else "",
            item.player_id if resolve_completed_ties else "",
        )
    )
    total = sum(
        result.strokes
        for result in scored[:counting_scores]
        if result.strokes is not None
    )
    if mark_cutoff_ties_undecided:
        cutoff_score = scored[counting_scores - 1].strokes
        definitely_counting = [result for result in scored if result.strokes < cutoff_score]
        tied_at_cutoff = [result for result in scored if result.strokes == cutoff_score]
        remaining_counting_places = counting_scores - len(definitely_counting)
        if len(tied_at_cutoff) > remaining_counting_places:
            definitely_dropped = [result for result in scored if result.strokes > cutoff_score]
            dropped = definitely_dropped + missing
            for result in definitely_counting:
                result.counts = True
            for result in dropped:
                result.dropped = True
            return definitely_counting, dropped, tied_at_cutoff, total

    counting = scored[:counting_scores]
    dropped = scored[counting_scores : counting_scores + dropped_scores] + missing

    for result in counting:
        result.counts = True
    for result in dropped:
        result.dropped = True

    return counting, dropped, [], total


def build_team_round_result(
    roster_players: list[dict[str, Any]],
    scores_by_player_round: dict[tuple[str, int], int],
    round_num: int,
    counting_scores: int,
    dropped_scores: int,
    statuses_by_player_round: dict[tuple[str, int], str] | None = None,
    penalty_score: int | None = None,
    mark_cutoff_ties_undecided: bool = False,
    resolve_completed_ties: bool = False,
) -> TeamRoundResult:
    statuses = statuses_by_player_round or {}
    player_results = [
        PlayerRoundResult(
            player_id=player["id"],
            player_name=player["name"],
            tier=player["tier"],
            strokes=scores_by_player_round.get((player["id"], round_num)),
            status=statuses.get((player["id"], round_num)),
        )
        for player in roster_players
    ]

    counting, dropped, undecided, total = _split_counting_and_dropped(
        player_results,
        counting_scores=counting_scores,
        dropped_scores=dropped_scores,
        penalty_score=penalty_score,
        mark_cutoff_ties_undecided=mark_cutoff_ties_undecided,
        resolve_completed_ties=resolve_completed_ties,
    )

    return TeamRoundResult(
        round_num=round_num,
        total=total,
        counting=counting,
        dropped=dropped,
        undecided=undecided,
        missing_scores=[result for result in player_results if result.strokes is None],
    )


def build_team_standings(
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    team_players: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    num_rounds: int = 4,
    counting_scores: int = 5,
    dropped_scores: int = 2,
    player_status_events: list[dict[str, Any]] | None = None,
    tournament_rounds: list[dict[str, Any]] | None = None,
    live_states: list[dict[str, Any]] | None = None,
    roster_change_rows: list[dict[str, Any]] | None = None,
    course_par: int = 72,
) -> list[TeamStanding]:
    players_by_id = {str(player["id"]): player for player in players}
    roster_by_team: dict[str, list[dict[str, Any]]] = {
        str(team["id"]): [] for team in teams
    }

    for link in team_players:
        player = players_by_id.get(str(link["player_id"]))
        if player:
            roster_by_team.setdefault(str(link["team_id"]), []).append(player)

    scores_by_player_round = {
        (str(score["player_id"]), int(score["round"])): int(score["strokes"]) - course_par
        for score in scores
        if score.get("is_official", True)
    }
    official_score_keys = set(scores_by_player_round)
    for state in live_states or []:
        if state.get("round_score") is None or state.get("is_finished"):
            continue
        scores_by_player_round[(str(state["player_id"]), int(state["round"]))] = int(
            state["round_score"]
        )
    events_by_player: dict[str, list[dict[str, Any]]] = {}
    for event in player_status_events or []:
        events_by_player.setdefault(event["player_id"], []).append(event)

    statuses_by_player_round: dict[tuple[str, int], str] = {}
    for player in players:
        events = sorted(
            events_by_player.get(player["id"], []),
            key=lambda event: str(event.get("created_at") or ""),
        )
        for round_num in range(1, num_rounds + 1):
            current_status: str | None = None
            for event in events:
                if int(event["effective_round"]) <= round_num:
                    current_status = str(event["status"]).upper()
            if current_status and current_status != "ACTIVE":
                statuses_by_player_round[(player["id"], round_num)] = current_status

    penalty_score_by_round = {
        int(round_row["round"]): int(round_row["penalty_score"]) - course_par
        for round_row in tournament_rounds or []
        if round_row.get("state") == "FINALIZED" and round_row.get("penalty_score") is not None
    }
    live_rounds = [
        int(state["round"])
        for state in live_states or []
        if state.get("round") is not None
    ]
    score_rounds = [
        int(score["round"])
        for score in scores
        if score.get("round") is not None
    ]
    active_round = max([*live_rounds, *score_rounds] or [1])
    finalized_rounds = {
        int(round_row["round"])
        for round_row in tournament_rounds or []
        if str(round_row.get("state") or "").upper() == "FINALIZED"
    }

    standings: list[TeamStanding] = []
    for team in teams:
        team_id = str(team["id"])
        original_roster_players = sorted(
            roster_by_team.get(team_id, []),
            key=lambda player: (player["tier"], player["name"]),
        )
        original_ids = [str(player["id"]) for player in original_roster_players]
        active_ids = roster_changes.roster_for_scoring_round(
            {team_id: original_ids},
            roster_change_rows or [],
            round_num=roster_changes.ROUND_FROM,
        )[team_id]
        round_results: dict[int, TeamRoundResult] = {}
        round_totals: dict[int, int | None] = {}

        for round_num in range(1, num_rounds + 1):
            effective_ids = roster_changes.roster_for_scoring_round(
                {team_id: original_ids},
                roster_change_rows or [],
                round_num=round_num,
            )[team_id]
            roster_players = [
                players_by_id[player_id]
                for player_id in effective_ids
                if player_id in players_by_id
            ]
            has_complete_official_roster = bool(effective_ids) and all(
                (player_id, round_num) in official_score_keys
                for player_id in effective_ids
            )
            round_is_complete = (
                round_num in finalized_rounds
                or round_num < active_round
                or has_complete_official_roster
            )
            round_result = build_team_round_result(
                roster_players=roster_players,
                scores_by_player_round=scores_by_player_round,
                round_num=round_num,
                counting_scores=counting_scores,
                dropped_scores=dropped_scores,
                statuses_by_player_round=statuses_by_player_round,
                penalty_score=penalty_score_by_round.get(round_num),
                mark_cutoff_ties_undecided=(
                    round_num == active_round and not round_is_complete
                ),
                resolve_completed_ties=round_is_complete,
            )
            round_results[round_num] = round_result
            round_totals[round_num] = round_result.total

        complete_rounds = [total for total in round_totals.values() if total is not None]
        completed_rounds = len(complete_rounds)
        tournament_total = sum(complete_rounds) if complete_rounds else None

        standings.append(
            TeamStanding(
                team_id=team["id"],
                team_name=team["name"],
                round_totals=round_totals,
                tournament_total=tournament_total,
                completed_rounds=completed_rounds,
                rounds=round_results,
                original_player_ids=tuple(original_ids),
                active_player_ids=tuple(active_ids),
            )
        )

    standings.sort(
        key=lambda item: (
            -item.completed_rounds,
            item.tournament_total is None,
            item.tournament_total if item.tournament_total is not None else 999999,
            item.team_name,
        )
    )
    return standings
