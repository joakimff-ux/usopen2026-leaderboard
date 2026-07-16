"""Presentation helpers for the inline leaderboard team preview."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from lib.scoring import TeamStanding


def toggle_preview_team(current_team_id: str | None, clicked_team_id: str) -> str | None:
    """Open, close, or switch the inline preview."""
    return None if current_team_id == clicked_team_id else clicked_team_id


def preview_href(current_team_id: str | None, clicked_team_id: str) -> str:
    target = toggle_preview_team(current_team_id, clicked_team_id)
    return "?" if target is None else f"?team={quote(target, safe='')}"


def active_round_number(
    scores: list[dict[str, Any]],
    live_states: list[dict[str, Any]],
    num_rounds: int = 4,
) -> int:
    live_rounds = [int(row["round"]) for row in live_states if row.get("round") is not None]
    if live_rounds:
        return min(max(live_rounds), num_rounds)
    score_rounds = [int(row["round"]) for row in scores if row.get("round") is not None]
    if score_rounds:
        return min(max(score_rounds), num_rounds)
    return 1


def build_preview_rows(
    standing: TeamStanding,
    active_round: int,
    live_states: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project existing scoring results into seven display rows without recalculation."""
    states_by_player_round = {
        (str(row["player_id"]), int(row["round"])): row
        for row in live_states or []
    }
    active_result = standing.rounds[active_round]
    counting_ids = {result.player_id for result in active_result.counting}
    dropped_ids = {result.player_id for result in active_result.dropped}
    if active_result.total is None or not counting_ids:
        # The scoring engine cannot decide the daily five before enough real
        # scores (or explicit frozen penalties) exist. Do not label all seven
        # missing players as dropped in the presentation.
        counting_ids = set()
        dropped_ids = set()

    players: dict[str, Any] = {}
    for round_result in standing.rounds.values():
        for result in [
            *round_result.counting,
            *round_result.dropped,
            *round_result.missing_scores,
        ]:
            players[result.player_id] = result

    rows: list[dict[str, Any]] = []
    for player_id, player in sorted(
        players.items(),
        key=lambda item: (item[1].tier, item[1].player_name),
    ):
        round_scores: dict[int, int | None] = {}
        statuses: list[str] = []
        for round_num, round_result in standing.rounds.items():
            all_results = [
                *round_result.counting,
                *round_result.dropped,
                *round_result.missing_scores,
            ]
            round_player = next(
                (result for result in all_results if result.player_id == player_id),
                None,
            )
            round_scores[round_num] = round_player.strokes if round_player else None
            if round_player and round_player.status:
                statuses.append(round_player.status)

        live_state = states_by_player_round.get((player_id, active_round), {})
        live_status = str(live_state.get("status") or "").upper()
        status = live_status if live_status in {"CUT", "WD", "DQ"} else (
            statuses[-1] if statuses else "ACTIVE"
        )
        hole = live_state.get("hole")
        if live_state.get("is_finished"):
            hole_status = "F"
        elif hole is not None:
            hole_status = f"Hull {hole}"
        else:
            hole_status = "—"

        completed_scores = [score for score in round_scores.values() if score is not None]
        rows.append(
            {
                "player_id": player_id,
                "player_name": player.player_name,
                "tier": player.tier,
                "round_scores": round_scores,
                "running_total": sum(completed_scores) if completed_scores else None,
                "hole_status": hole_status,
                "status": status,
                "selection": (
                    "COUNTING"
                    if player_id in counting_ids
                    else "DROPPED"
                    if player_id in dropped_ids
                    else "PENDING"
                ),
            }
        )
    return rows
