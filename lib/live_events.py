"""Live score change events derived from DataGolf sync diffs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from supabase import Client

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LIMIT = 20
COUNTING_SCORES = 5


@dataclass
class LiveEventsWriteResult:
    written: int = 0
    changes_detected: int = 0
    error: str | None = None


def format_relative_score(score: int) -> str:
    return "E" if score == 0 else (f"+{score}" if score > 0 else str(score))


def classify_score_change(delta: int) -> tuple[str, str]:
    """Return (label, icon) for a relative-to-par score change."""
    if delta <= -2:
        return "stor forbedring", "🔥"
    if delta == -1:
        return "birdie", "🐦"
    if delta == 1:
        return "bogey", "😬"
    if delta >= 2:
        return "dårlig utvikling", "⚠️"
    return "scoreendring", "⛳"


def build_score_change_text(old_score: int, new_score: int, delta: int) -> str:
    label, icon = classify_score_change(delta)
    if delta < 0:
        movement = f"går fra {format_relative_score(old_score)} til {format_relative_score(new_score)}"
    elif delta > 0:
        movement = f"faller til {format_relative_score(new_score)}"
    else:
        movement = f"holder {format_relative_score(new_score)}"
    return f"{icon} {label} – {movement}"


def format_supabase_error(exc: Exception) -> str:
    message = str(exc)
    code = getattr(exc, "code", None)
    if hasattr(exc, "message") and getattr(exc, "message", None):
        message = str(exc.message)
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], dict):
        payload = args[0]
        code = payload.get("code") or code
        message = payload.get("message") or message
    parts = [message]
    if code:
        parts.append(f"code={code}")
    return " | ".join(parts)


def roster_window_for_round(round_no: int) -> tuple[int, int]:
    if round_no <= 2:
        return 1, 2
    return 3, 4


def fetch_rostered_player_ids(client: Client, round_no: int) -> set[int]:
    active_from, active_to = roster_window_for_round(round_no)
    response = (
        client.table("team_players")
        .select("player_id, active_from_round, active_to_round")
        .eq("active_from_round", active_from)
        .eq("active_to_round", active_to)
        .execute()
    )
    return {
        int(row["player_id"])
        for row in response.data or []
        if row.get("player_id") is not None
    }


def player_counting_status(
    player_id: int,
    team_player_scores: list[tuple[int, str, int | None]],
    counting_scores: int = COUNTING_SCORES,
) -> str | None:
    """Return Teller/Droppes for a player among team round scores."""
    scored = [(pid, name, score) for pid, name, score in team_player_scores if score is not None]
    if not any(pid == player_id for pid, _, _ in scored):
        return None
    scored.sort(key=lambda item: item[2])
    counting_ids = {pid for pid, _, _ in scored[:counting_scores]}
    if player_id in counting_ids:
        return "Teller"
    return "Droppes"


def record_live_events(
    client: Client | None,
    score_rows: list[dict[str, Any]],
    db_players: list[dict[str, Any]],
    active_round: int | None,
) -> LiveEventsWriteResult:
    """Compare incoming scores with DB before upsert and append live events."""
    result = LiveEventsWriteResult()
    if client is None or not score_rows:
        logger.info("record_live_events: skipped (client=%s rows=%s)", client is not None, len(score_rows))
        return result

    player_names = {int(player["id"]): str(player["name"]) for player in db_players if player.get("id") is not None}
    player_ids = sorted({int(row["player_id"]) for row in score_rows})
    existing: dict[tuple[int, int], int] = {}

    logger.info(
        "record_live_events: comparing %s score rows for active_round=%s",
        len(score_rows),
        active_round,
    )
    try:
        response = (
            client.table("scores")
            .select("player_id, round_no, score")
            .in_("player_id", player_ids)
            .execute()
        )
        for row in response.data or []:
            existing[(int(row["player_id"]), int(row["round_no"]))] = int(row["score"])
    except Exception as exc:
        result.error = format_supabase_error(exc)
        logger.error("record_live_events: could not read existing scores: %s", result.error, exc_info=True)
        return result

    rostered_by_round: dict[int, set[int]] = {}
    events: list[dict[str, Any]] = []
    for row in score_rows:
        player_id = int(row["player_id"])
        round_no = int(row["round_no"])
        new_score = int(row["score"])

        if active_round is not None and round_no != active_round:
            continue

        if round_no not in rostered_by_round:
            rostered_by_round[round_no] = fetch_rostered_player_ids(client, round_no)
        if player_id not in rostered_by_round[round_no]:
            continue

        old_score = existing.get((player_id, round_no))
        if old_score is None or old_score == new_score:
            continue

        delta = new_score - old_score
        result.changes_detected += 1
        player_name = player_names.get(player_id, f"Spiller {player_id}")
        events.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "round_no": round_no,
                "old_score": old_score,
                "new_score": new_score,
                "change": delta,
                "event_text": build_score_change_text(old_score, new_score, delta),
            }
        )

    if not events:
        logger.info(
            "record_live_events: no changes detected (active_round=%s existing_keys=%s)",
            active_round,
            len(existing),
        )
        return result

    logger.info("record_live_events: inserting %s events", len(events))
    try:
        client.table("live_events").insert(events).execute()
        result.written = len(events)
        logger.info("record_live_events: wrote %s events", result.written)
    except Exception as exc:
        result.error = format_supabase_error(exc)
        logger.error("record_live_events: insert failed: %s", result.error, exc_info=True)
    return result


def count_live_events(client: Client | None) -> int:
    if client is None:
        return 0
    try:
        response = client.table("live_events").select("id", count="exact").execute()
        return int(response.count or 0)
    except Exception as exc:
        logger.warning("count_live_events failed: %s", format_supabase_error(exc))
        return 0


def fetch_recent_live_events(client: Client | None, limit: int = DEFAULT_EVENT_LIMIT) -> pd.DataFrame:
    if client is None:
        return pd.DataFrame()
    try:
        response = (
            client.table("live_events")
            .select(
                "id, player_id, player_name, round_no, old_score, new_score, change, event_text, created_at"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data or []
    except Exception as exc:
        logger.error("fetch_recent_live_events failed: %s", format_supabase_error(exc), exc_info=True)
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "id": row.get("id"),
                "player_id": int(row["player_id"]),
                "player_name": row.get("player_name") or f"Spiller {row['player_id']}",
                "round_no": int(row["round_no"]),
                "old_score": int(row["old_score"]),
                "new_score": int(row["new_score"]),
                "delta": int(row["change"]),
                "change": int(row["change"]),
                "event_text": row.get("event_text") or "",
                "created_at": row.get("created_at"),
            }
            for row in rows
        ]
    )


def fetch_recent_score_events(client: Client | None, limit: int = DEFAULT_EVENT_LIMIT) -> pd.DataFrame:
    return fetch_recent_live_events(client, limit=limit)


def build_live_events_display(
    events: pd.DataFrame,
    teams: pd.DataFrame,
    players: pd.DataFrame,
    links: pd.DataFrame,
    score_map: dict[tuple[int, int], int],
    *,
    get_team_player_ids: Callable[[pd.DataFrame, int, int], set[int]],
    rostered_player_ids: set[int] | None = None,
    limit: int = DEFAULT_EVENT_LIMIT,
) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    if rostered_player_ids is None:
        rostered_player_ids = set()
        for _, team in teams.iterrows():
            team_id = int(team.id)
            for round_no in (1, 2, 3, 4):
                rostered_player_ids.update(get_team_player_ids(links, team_id, round_no))

    player_names = {int(row.id): row["name"] for _, row in players.iterrows()}

    rows: list[dict[str, str]] = []
    for _, event in events.iterrows():
        player_id = int(event["player_id"])
        if player_id not in rostered_player_ids:
            continue

        round_no = int(event["round_no"])
        player_name = event.get("player_name") or player_names.get(player_id, f"Spiller {player_id}")
        old_score = int(event["old_score"])
        new_score = int(event["new_score"])
        delta = int(event.get("change", event.get("delta", new_score - old_score)))
        hendelse = event.get("event_text") or build_score_change_text(old_score, new_score, delta)

        affected_teams: list[str] = []
        status_parts: list[str] = []
        for _, team in teams.sort_values("name").iterrows():
            team_id = int(team.id)
            team_name = team["name"]
            roster_ids = get_team_player_ids(links, team_id, round_no)
            if player_id not in roster_ids:
                continue

            team_player_scores = []
            for pid in roster_ids:
                name = player_names.get(pid, f"Spiller {pid}")
                score = score_map.get((pid, round_no))
                team_player_scores.append((pid, name, score))

            status = player_counting_status(player_id, team_player_scores)
            affected_teams.append(team_name)
            if status:
                status_parts.append(f"{status} for {team_name}")

        if not affected_teams:
            continue

        rows.append(
            {
                "Spiller": player_name,
                "Hendelse": hendelse,
                "Scoreendring": (
                    f"{format_relative_score(old_score)} → {format_relative_score(new_score)}"
                ),
                "Påvirker lag": ", ".join(affected_teams),
                "Teller/Droppes": ", ".join(status_parts) if status_parts else "—",
            }
        )
        if len(rows) >= limit:
            break

    return pd.DataFrame(rows)
