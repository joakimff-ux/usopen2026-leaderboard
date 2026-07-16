"""Build stable fantasy-relevant events from consecutive DataGolf snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


VISIBLE_HOLE_EVENTS = {
    "EAGLE",
    "BIRDIE",
    "BOGEY",
    "DOUBLE_BOGEY_PLUS",
}
VISIBLE_STATUSES = {"CUT", "WD", "DQ"}


@dataclass(frozen=True)
class LiveSnapshot:
    player_id: str
    player_name: str
    round: int
    hole: int | None
    is_finished: bool
    round_score: int | None
    status: str | None
    end_hole: int | None = None
    source_updated_at: str | None = None


def parse_relative_score(value: Any) -> int | None:
    """Parse DataGolf's documented `today` score relative to par."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().upper()
        if not cleaned or cleaned == "-":
            return None
        if cleaned in {"E", "EVEN"}:
            return 0
        value = cleaned.replace("+", "", 1)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_hole(value: Any) -> tuple[int | None, bool]:
    """Return the latest completed hole and whether the round is finished."""
    if isinstance(value, str) and value.strip().upper() in {"F", "FIN", "FINAL"}:
        return None, True
    try:
        hole = int(value)
    except (TypeError, ValueError):
        return None, False
    if 1 <= hole <= 18:
        return hole, False
    return None, False


def classify_hole(delta_to_par: int) -> str | None:
    if delta_to_par <= -2:
        return "EAGLE"
    if delta_to_par == -1:
        return "BIRDIE"
    if delta_to_par == 1:
        return "BOGEY"
    if delta_to_par >= 2:
        return "DOUBLE_BOGEY_PLUS"
    return None


def _next_hole(previous_hole: int | None, current_hole: int | None) -> bool:
    if previous_hole is None or current_hole is None:
        return False
    return current_hole == (previous_hole % 18) + 1


def _dedupe_key(
    tournament_id: str,
    snapshot: LiveSnapshot,
    event_type: str,
    hole: int | None,
) -> str:
    raw = "|".join(
        [
            tournament_id,
            snapshot.player_id,
            str(snapshot.round),
            str(hole or ""),
            event_type,
            str(snapshot.round_score if snapshot.round_score is not None else ""),
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _event_row(
    tournament_id: str,
    snapshot: LiveSnapshot,
    event_type: str,
    hole: int | None = None,
    hole_score: int | None = None,
) -> dict[str, Any]:
    return {
        "tournament_id": tournament_id,
        "player_id": snapshot.player_id,
        "round": snapshot.round,
        "hole": hole,
        "event_type": event_type,
        "hole_score": hole_score,
        "round_score": snapshot.round_score,
        "source_updated_at": snapshot.source_updated_at,
        "dedupe_key": _dedupe_key(tournament_id, snapshot, event_type, hole),
    }


def build_events(
    tournament_id: str,
    previous: LiveSnapshot | None,
    current: LiveSnapshot,
) -> list[dict[str, Any]]:
    """Create events only from a real transition after an established baseline."""
    if previous is None or previous.round != current.round:
        return []

    events: list[dict[str, Any]] = []
    completed_hole: int | None = None
    advanced_one_hole = _next_hole(previous.hole, current.hole)

    if advanced_one_hole:
        completed_hole = current.hole
    elif current.is_finished and not previous.is_finished:
        end_hole = current.end_hole or 18
        if previous.hole == (end_hole - 1 or 18):
            completed_hole = end_hole

    if (
        completed_hole is not None
        and previous.round_score is not None
        and current.round_score is not None
    ):
        hole_score = current.round_score - previous.round_score
        event_type = classify_hole(hole_score)
        if event_type in VISIBLE_HOLE_EVENTS:
            events.append(
                _event_row(
                    tournament_id,
                    current,
                    event_type,
                    hole=completed_hole,
                    hole_score=hole_score,
                )
            )

    if current.is_finished and not previous.is_finished:
        events.append(_event_row(tournament_id, current, "ROUND_COMPLETE"))

    current_status = (current.status or "").upper()
    previous_status = (previous.status or "").upper()
    if current_status in VISIBLE_STATUSES and current_status != previous_status:
        events.append(_event_row(tournament_id, current, current_status))

    return events


def state_row(tournament_id: str, snapshot: LiveSnapshot) -> dict[str, Any]:
    return {
        "tournament_id": tournament_id,
        "player_id": snapshot.player_id,
        "round": snapshot.round,
        "hole": snapshot.hole,
        "is_finished": snapshot.is_finished,
        "round_score": snapshot.round_score,
        "status": (snapshot.status or "ACTIVE").upper(),
        "source_updated_at": snapshot.source_updated_at,
    }


def group_affected_teams(roster_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group every affected team under one player event."""
    grouped: dict[str, set[str]] = {}
    for row in roster_rows:
        team = row.get("teams") or {}
        team_name = team.get("name") if isinstance(team, dict) else None
        player_id = str(row.get("player_id") or "")
        if player_id and team_name:
            grouped.setdefault(player_id, set()).add(str(team_name))
    return {
        player_id: sorted(names, key=str.casefold)
        for player_id, names in grouped.items()
    }
