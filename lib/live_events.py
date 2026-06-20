"""Live score change events derived from sync diffs."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from supabase import Client

DEFAULT_EVENT_LIMIT = 20
COUNTING_SCORES = 5


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


def record_score_events(client: Client | None, score_rows: list[dict[str, Any]]) -> int:
    """Compare incoming scores with DB and append change events."""
    if client is None or not score_rows:
        return 0

    player_ids = sorted({int(row["player_id"]) for row in score_rows})
    existing: dict[tuple[int, int], int] = {}
    try:
        response = (
            client.table("scores")
            .select("player_id, round_no, score")
            .in_("player_id", player_ids)
            .execute()
        )
        for row in response.data or []:
            existing[(int(row["player_id"]), int(row["round_no"]))] = int(row["score"])
    except Exception:
        return 0

    events: list[dict[str, Any]] = []
    for row in score_rows:
        player_id = int(row["player_id"])
        round_no = int(row["round_no"])
        new_score = int(row["score"])
        old_score = existing.get((player_id, round_no))
        if old_score is None or old_score == new_score:
            continue
        events.append(
            {
                "player_id": player_id,
                "round_no": round_no,
                "old_score": old_score,
                "new_score": new_score,
                "delta": new_score - old_score,
            }
        )

    if not events:
        return 0

    try:
        client.table("score_events").insert(events).execute()
    except Exception:
        return 0
    return len(events)


def fetch_recent_score_events(client: Client | None, limit: int = DEFAULT_EVENT_LIMIT) -> pd.DataFrame:
    if client is None:
        return pd.DataFrame()
    try:
        response = (
            client.table("score_events")
            .select("id, player_id, round_no, old_score, new_score, delta, created_at, players(name)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data or []
    except Exception:
        return pd.DataFrame()

    parsed: list[dict[str, Any]] = []
    for row in rows:
        player_info = row.get("players") or {}
        player_name = player_info.get("name") if isinstance(player_info, dict) else None
        parsed.append(
            {
                "id": row.get("id"),
                "player_id": int(row["player_id"]),
                "player_name": player_name or f"Spiller {row['player_id']}",
                "round_no": int(row["round_no"]),
                "old_score": int(row["old_score"]),
                "new_score": int(row["new_score"]),
                "delta": int(row["delta"]),
                "created_at": row.get("created_at"),
            }
        )
    return pd.DataFrame(parsed)


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

    player_names = {
        int(row.id): row["name"] for _, row in players.iterrows()
    }

    rows: list[dict[str, str]] = []
    for _, event in events.iterrows():
        player_id = int(event["player_id"])
        if player_id not in rostered_player_ids:
            continue

        round_no = int(event["round_no"])
        player_name = event.get("player_name") or player_names.get(player_id, f"Spiller {player_id}")
        old_score = int(event["old_score"])
        new_score = int(event["new_score"])
        delta = int(event["delta"])

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

        hendelse = build_score_change_text(old_score, new_score, delta)
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
