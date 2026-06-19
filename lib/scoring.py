"""Fantasy golf scoring calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlayerRoundResult:
    player_id: str
    player_name: str
    tier: int
    strokes: int | None
    counts: bool
    dropped: bool


@dataclass
class TeamRoundResult:
    round_num: int
    total: int | None
    counting: list[PlayerRoundResult]
    dropped: list[PlayerRoundResult]
    missing_scores: list[PlayerRoundResult]


@dataclass
class TeamStanding:
    team_id: str
    team_name: str
    round_totals: dict[int, int | None]
    tournament_total: int | None
    rounds: dict[int, TeamRoundResult]


def _split_counting_and_dropped(
    player_results: list[PlayerRoundResult],
    counting_scores: int,
    dropped_scores: int,
) -> tuple[list[PlayerRoundResult], list[PlayerRoundResult], int | None]:
    scored = [result for result in player_results if result.strokes is not None]
    missing = [result for result in player_results if result.strokes is None]

    if len(scored) < counting_scores:
        for result in missing:
            result.dropped = True
        return [], missing, None

    scored.sort(key=lambda item: item.strokes)
    counting = scored[:counting_scores]
    dropped = scored[counting_scores : counting_scores + dropped_scores] + missing

    for result in counting:
        result.counts = True
    for result in dropped:
        result.dropped = True

    total = sum(result.strokes for result in counting if result.strokes is not None)
    return counting, dropped, total


def build_team_round_result(
    roster_players: list[dict[str, Any]],
    scores_by_player_round: dict[tuple[str, int], int],
    round_num: int,
    counting_scores: int,
    dropped_scores: int,
) -> TeamRoundResult:
    player_results = [
        PlayerRoundResult(
            player_id=player["id"],
            player_name=player["name"],
            tier=player["tier"],
            strokes=scores_by_player_round.get((player["id"], round_num)),
        )
        for player in roster_players
    ]

    counting, dropped, total = _split_counting_and_dropped(
        player_results,
        counting_scores=counting_scores,
        dropped_scores=dropped_scores,
    )

    return TeamRoundResult(
        round_num=round_num,
        total=total,
        counting=counting,
        dropped=dropped,
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
) -> list[TeamStanding]:
    players_by_id = {player["id"]: player for player in players}
    roster_by_team: dict[str, list[dict[str, Any]]] = {team["id"]: [] for team in teams}

    for link in team_players:
        player = players_by_id.get(link["player_id"])
        if player:
            roster_by_team.setdefault(link["team_id"], []).append(player)

    scores_by_player_round = {
        (score["player_id"], score["round"]): score["strokes"] for score in scores
    }

    standings: list[TeamStanding] = []
    for team in teams:
        roster_players = sorted(
            roster_by_team.get(team["id"], []),
            key=lambda player: (player["tier"], player["name"]),
        )
        round_results: dict[int, TeamRoundResult] = {}
        round_totals: dict[int, int | None] = {}

        for round_num in range(1, num_rounds + 1):
            round_result = build_team_round_result(
                roster_players=roster_players,
                scores_by_player_round=scores_by_player_round,
                round_num=round_num,
                counting_scores=counting_scores,
                dropped_scores=dropped_scores,
            )
            round_results[round_num] = round_result
            round_totals[round_num] = round_result.total

        complete_rounds = [total for total in round_totals.values() if total is not None]
        tournament_total = sum(complete_rounds) if len(complete_rounds) == num_rounds else None

        standings.append(
            TeamStanding(
                team_id=team["id"],
                team_name=team["name"],
                round_totals=round_totals,
                tournament_total=tournament_total,
                rounds=round_results,
            )
        )

    standings.sort(
        key=lambda item: (
            item.tournament_total is None,
            item.tournament_total if item.tournament_total is not None else 999999,
            item.team_name,
        )
    )
    return standings
