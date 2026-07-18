"""Shared production data path for leaderboard and team detail."""

from __future__ import annotations

from typing import Any

from lib import scoring


COURSE_PAR_BY_NAME = {
    "royal birkdale": 70,
}


def resolve_course_par(tournament_rules: dict[str, Any]) -> int:
    """Use an explicit tournament par, then a known-course rule, then 72."""
    configured = tournament_rules.get("course_par")
    if configured is not None:
        return int(configured)
    course_name = " ".join(
        str(tournament_rules.get("course_name") or "").casefold().split()
    )
    return COURSE_PAR_BY_NAME.get(course_name, 72)


def leaderboard_positions(
    standings: list[scoring.TeamStanding],
    active_round: int,
) -> list[int]:
    """Return competition ranks after total and active-round sorting."""
    positions: list[int] = []
    previous_key: tuple[int | None, int | None] | None = None
    current_position = 0
    for index, standing in enumerate(standings, start=1):
        rank_key = (
            standing.tournament_total,
            standing.round_totals.get(active_round),
        )
        if index == 1 or rank_key != previous_key:
            current_position = index
        positions.append(current_position)
        previous_key = rank_key
    return positions


def load_competition_data(
    client: Any,
    tournament_id: str,
    tournament_rules: dict[str, Any],
    data_source: Any | None = None,
) -> dict[str, Any]:
    """Load and calculate the exact dataset rendered by all score views."""
    if data_source is None:
        from lib import db as data_source

    teams = data_source.fetch_teams(client, tournament_id)
    players = data_source.fetch_players(client, tournament_id)
    team_players = data_source.fetch_team_players(client, tournament_id)
    scores = data_source.fetch_scores(client, tournament_id)
    status_events = data_source.fetch_player_status_events(client, tournament_id)
    tournament_rounds = data_source.fetch_tournament_rounds(client, tournament_id)
    try:
        roster_change_rows = data_source.fetch_active_roster_changes(client, tournament_id)
    except Exception:
        roster_change_rows = []
    try:
        live_states = data_source.fetch_live_player_states(client, tournament_id)
    except Exception:
        live_states = []

    standings = scoring.build_team_standings(
        teams=teams,
        players=players,
        team_players=team_players,
        scores=scores,
        num_rounds=tournament_rules.get("num_rounds", 4),
        counting_scores=tournament_rules.get("counting_scores", 5),
        dropped_scores=tournament_rules.get("dropped_scores", 2),
        player_status_events=status_events,
        tournament_rounds=tournament_rounds,
        live_states=live_states,
        roster_change_rows=roster_change_rows,
        course_par=resolve_course_par(tournament_rules),
    )
    return {
        "teams": teams,
        "players": players,
        "team_players": team_players,
        "scores": scores,
        "status_events": status_events,
        "tournament_rounds": tournament_rounds,
        "live_states": live_states,
        "roster_changes": roster_change_rows,
        "standings": standings,
    }
