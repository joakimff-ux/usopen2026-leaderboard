"""Supabase database helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st
from supabase import Client, create_client


def get_supabase_read_client() -> Client | None:
    """Public read-only client governed by Supabase RLS SELECT policies."""
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def get_supabase_write_client() -> Client | None:
    """Server-only privileged client. Never expose this key in UI or logs."""
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def get_supabase_client() -> Client | None:
    """Backward-compatible alias for public read operations."""
    return get_supabase_read_client()


def get_supabase_client_from_config(url: str, key: str) -> Client:
    return create_client(url, key)


def tournament_display_title(tournament: dict[str, Any]) -> str:
    return str(tournament.get("display_title") or tournament.get("name") or "Fantasy Golf")


def tournament_subtitle(tournament: dict[str, Any]) -> str:
    parts: list[str] = []
    course = tournament.get("course_name")
    if course:
        parts.append(str(course))
    start = tournament.get("start_date")
    end = tournament.get("end_date")
    if start and end:
        parts.append(f"{start} – {end}")
    elif tournament.get("year"):
        parts.append(str(tournament["year"]))
    parts.append("lowest total score wins")
    return " · ".join(parts)


def list_tournaments(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("tournaments")
        .select("*")
        .order("year")
        .order("name")
        .execute()
    )
    return response.data or []


def get_active_tournament(client: Client) -> dict[str, Any] | None:
    response = (
        client.table("tournaments")
        .select("*")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def set_active_tournament(client: Client, tournament_id: str) -> dict[str, Any] | None:
    """Mark one tournament active. All others are set inactive."""
    client.table("tournaments").update({"is_active": False}).eq("is_active", True).execute()
    response = (
        client.table("tournaments")
        .update({"is_active": True})
        .eq("id", tournament_id)
        .execute()
    )
    return response.data[0] if response.data else None


def event_name_matches(expected: str | None, actual: str | None) -> bool:
    """Return True only when both configured event names match exactly."""
    if not expected or not actual:
        return False
    expected_norm = " ".join(expected.casefold().split())
    actual_norm = " ".join(actual.casefold().split())
    return expected_norm == actual_norm


def fetch_teams(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("teams")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return response.data or []


def fetch_players(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("players")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("tier")
        .order("name")
        .execute()
    )
    return response.data or []


def fetch_team_players(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    teams = fetch_teams(client, tournament_id)
    if not teams:
        return []

    team_ids = [team["id"] for team in teams]
    response = (
        client.table("team_players")
        .select("id, team_id, player_id, teams(name), players(name, tier)")
        .in_("team_id", team_ids)
        .execute()
    )
    return response.data or []


def fetch_scores(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    players = fetch_players(client, tournament_id)
    if not players:
        return []

    player_ids = [player["id"] for player in players]
    response = (
        client.table("scores")
        .select("*")
        .in_("player_id", player_ids)
        .execute()
    )
    return response.data or []


def fetch_player_status_events(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    players = fetch_players(client, tournament_id)
    if not players:
        return []
    player_ids = [player["id"] for player in players]
    response = (
        client.table("player_status_events")
        .select("*")
        .in_("player_id", player_ids)
        .order("created_at")
        .execute()
    )
    return response.data or []


def fetch_live_player_states(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("live_player_states")
        .select("*")
        .eq("tournament_id", tournament_id)
        .execute()
    )
    return response.data or []


def fetch_live_feed_events(
    client: Client,
    tournament_id: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    response = (
        client.table("live_feed_events")
        .select("*, players(name)")
        .eq("tournament_id", tournament_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def fetch_tournament_rounds(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("tournament_rounds")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("round")
        .execute()
    )
    return response.data or []


def reset_tournament_data(client: Client, tournament_id: str) -> None:
    teams = fetch_teams(client, tournament_id)
    players = fetch_players(client, tournament_id)

    team_ids = [team["id"] for team in teams]
    player_ids = [player["id"] for player in players]

    if player_ids:
        client.table("scores").delete().in_("player_id", player_ids).execute()
    if team_ids:
        client.table("team_players").delete().in_("team_id", team_ids).execute()
    if player_ids:
        client.table("players").delete().in_("id", player_ids).execute()
    if team_ids:
        client.table("teams").delete().in_("id", team_ids).execute()
    client.table("tournament_rounds").update(
        {
            "state": "OPEN",
            "official_worst_score": None,
            "penalty_score": None,
            "frozen_at": None,
            "is_override": False,
            "override_reason": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("tournament_id", tournament_id).execute()
    write_admin_audit(
        client,
        action="TOURNAMENT_DATA_RESET",
        entity_type="tournament",
        entity_id=tournament_id,
        details={"teams": len(team_ids), "players": len(player_ids)},
    )


def add_team(client: Client, tournament_id: str, name: str) -> dict[str, Any]:
    response = client.table("teams").insert({"tournament_id": tournament_id, "name": name.strip()}).execute()
    return response.data[0]


def remove_team(client: Client, team_id: str) -> None:
    client.table("team_players").delete().eq("team_id", team_id).execute()
    client.table("teams").delete().eq("id", team_id).execute()


def add_player(client: Client, tournament_id: str, name: str, tier: int) -> dict[str, Any]:
    response = (
        client.table("players")
        .insert({"tournament_id": tournament_id, "name": name.strip(), "tier": tier})
        .execute()
    )
    return response.data[0]


def remove_player(client: Client, player_id: str) -> None:
    client.table("scores").delete().eq("player_id", player_id).execute()
    client.table("team_players").delete().eq("player_id", player_id).execute()
    client.table("players").delete().eq("id", player_id).execute()


def set_team_roster(client: Client, team_id: str, player_ids: list[str]) -> None:
    client.table("team_players").delete().eq("team_id", team_id).execute()
    if player_ids:
        rows = [{"team_id": team_id, "player_id": player_id} for player_id in player_ids]
        client.table("team_players").insert(rows).execute()


def upsert_score(client: Client, player_id: str, round_num: int, strokes: int) -> None:
    client.table("scores").upsert(
        {
            "player_id": player_id,
            "round": round_num,
            "strokes": strokes,
            "source": "ADMIN",
            "is_official": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="player_id,round",
    ).execute()


def delete_score(client: Client, player_id: str, round_num: int) -> None:
    client.table("scores").delete().eq("player_id", player_id).eq("round", round_num).execute()


def write_admin_audit(
    client: Client,
    action: str,
    entity_type: str,
    entity_id: str | None,
    details: dict[str, Any],
) -> None:
    client.table("admin_audit_log").insert(
        {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
        }
    ).execute()


def add_player_status_event(
    client: Client,
    player_id: str,
    effective_round: int,
    status: str,
    source: str = "ADMIN",
    note: str | None = None,
) -> dict[str, Any]:
    normalized_status = status.strip().upper()
    normalized_source = source.strip().upper()
    if normalized_status not in {"ACTIVE", "CUT", "WD", "DQ"}:
        raise ValueError(f"Unsupported player status: {status}")
    if normalized_source not in {"DATAGOLF", "ADMIN"}:
        raise ValueError(f"Unsupported status source: {source}")
    if not 1 <= int(effective_round) <= 4:
        raise ValueError("Effective round must be between 1 and 4.")
    if normalized_status == "CUT" and int(effective_round) != 3:
        raise ValueError("CUT must take effect from round 3 so round 1 and 2 scores are retained.")
    row = {
        "player_id": player_id,
        "effective_round": int(effective_round),
        "status": normalized_status,
        "source": normalized_source,
        "note": note.strip() if note else None,
    }
    response = client.table("player_status_events").insert(row).execute()
    inserted = response.data[0]
    if normalized_source == "ADMIN":
        write_admin_audit(
            client,
            action="PLAYER_STATUS_OVERRIDE",
            entity_type="player",
            entity_id=player_id,
            details=row,
        )
    return inserted


def freeze_round_penalty(
    client: Client,
    tournament: dict[str, Any],
    round_num: int,
    override_score: int | None = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    """Freeze a round penalty from official completed scores or override it."""
    tournament_id = str(tournament["id"])
    round_rows = fetch_tournament_rounds(client, tournament_id)
    existing = next((row for row in round_rows if row["round"] == round_num), None)
    if existing and existing.get("state") == "FINALIZED" and override_score is None:
        raise ValueError("Round penalty is already frozen. Use an explicit admin override.")

    official_scores = [
        score["strokes"]
        for score in fetch_scores(client, tournament_id)
        if score["round"] == round_num and score.get("is_official", True)
    ]
    if not official_scores:
        raise ValueError("Cannot freeze penalty before official completed round scores exist.")

    worst_score = max(official_scores)
    configured_penalty = int(tournament.get("missing_score_penalty", 2))
    is_override = override_score is not None
    if is_override and not (override_reason or "").strip():
        raise ValueError("A visible reason is required for a penalty override.")
    penalty_score = int(override_score) if is_override else worst_score + configured_penalty
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "tournament_id": tournament_id,
        "round": round_num,
        "state": "FINALIZED",
        "official_worst_score": worst_score,
        "missing_score_penalty": configured_penalty,
        "penalty_score": penalty_score,
        "frozen_at": now,
        "is_override": is_override,
        "override_reason": override_reason.strip() if is_override and override_reason else None,
        "updated_at": now,
    }
    response = (
        client.table("tournament_rounds")
        .upsert(row, on_conflict="tournament_id,round")
        .execute()
    )
    saved = response.data[0]
    write_admin_audit(
        client,
        action="ROUND_PENALTY_OVERRIDE" if is_override else "ROUND_PENALTY_FROZEN",
        entity_type="tournament_round",
        entity_id=str(saved.get("id") or ""),
        details=row,
    )
    return saved


def fetch_admin_audit(client: Client, limit: int = 100) -> list[dict[str, Any]]:
    response = (
        client.table("admin_audit_log")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []
