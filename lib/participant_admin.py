"""Validation and persistence for post-import fantasy participants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_TIERS = tuple(range(1, 8))


@dataclass(frozen=True)
class ParticipantValidation:
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_participant(
    name: str,
    selected_player_ids: list[str],
    players: list[dict[str, Any]],
    existing_teams: list[dict[str, Any]],
    exclude_team_id: str | None = None,
) -> ParticipantValidation:
    errors: list[str] = []
    cleaned_name = name.strip()
    if not cleaned_name:
        errors.append("Deltakernavn må fylles ut.")

    duplicate_name = any(
        team.get("id") != exclude_team_id
        and _normalized_name(str(team.get("name") or "")) == _normalized_name(cleaned_name)
        for team in existing_teams
    )
    if cleaned_name and duplicate_name:
        errors.append("Deltakernavnet finnes allerede.")

    if len(selected_player_ids) != 7:
        errors.append("Nøyaktig 7 spillere må velges.")
    if len(set(selected_player_ids)) != len(selected_player_ids):
        errors.append("Samme spiller kan ikke velges flere ganger.")

    players_by_id = {str(player["id"]): player for player in players}
    unknown_ids = [player_id for player_id in selected_player_ids if player_id not in players_by_id]
    if unknown_ids:
        errors.append("Ett eller flere spillervalg finnes ikke i aktiv turnering.")

    tier_counts = {tier: 0 for tier in REQUIRED_TIERS}
    for player_id in set(selected_player_ids):
        player = players_by_id.get(player_id)
        if player and int(player["tier"]) in tier_counts:
            tier_counts[int(player["tier"])] += 1
    if any(tier_counts[tier] != 1 for tier in REQUIRED_TIERS):
        errors.append("Tierregelen krever nøyaktig én spiller fra hver av tier 1–7.")

    return ParticipantValidation(tuple(errors))


def create_participant(
    client: Any,
    tournament_id: str,
    name: str,
    selected_player_ids: list[str],
    players: list[dict[str, Any]],
    existing_teams: list[dict[str, Any]],
) -> dict[str, Any]:
    validation = validate_participant(name, selected_player_ids, players, existing_teams)
    if not validation.is_valid:
        raise ValueError(" ".join(validation.errors))

    cleaned_name = name.strip()
    response = client.table("teams").insert(
        {"tournament_id": tournament_id, "name": cleaned_name}
    ).execute()
    team = response.data[0]
    try:
        roster_rows = [
            {"team_id": team["id"], "player_id": player_id}
            for player_id in selected_player_ids
        ]
        client.table("team_players").insert(roster_rows).execute()
        client.table("admin_audit_log").insert(
            {
                "action": "PARTICIPANT_CREATED",
                "entity_type": "team",
                "entity_id": team["id"],
                "details": {"name": cleaned_name, "player_ids": selected_player_ids},
            }
        ).execute()
    except Exception:
        client.table("teams").delete().eq("id", team["id"]).execute()
        raise
    return team


def update_participant(
    client: Any,
    team: dict[str, Any],
    name: str,
    selected_player_ids: list[str],
    players: list[dict[str, Any]],
    existing_teams: list[dict[str, Any]],
    current_player_ids: list[str],
    scores_registered: bool,
) -> dict[str, Any]:
    if scores_registered:
        raise ValueError("Redigering er låst fordi første score er registrert.")
    validation = validate_participant(
        name,
        selected_player_ids,
        players,
        existing_teams,
        exclude_team_id=str(team["id"]),
    )
    if not validation.is_valid:
        raise ValueError(" ".join(validation.errors))

    cleaned_name = name.strip()
    old_name = str(team["name"])
    try:
        updated = (
            client.table("teams")
            .update({"name": cleaned_name})
            .eq("id", team["id"])
            .execute()
            .data[0]
        )
        client.table("team_players").delete().eq("team_id", team["id"]).execute()
        client.table("team_players").insert(
            [
                {"team_id": team["id"], "player_id": player_id}
                for player_id in selected_player_ids
            ]
        ).execute()
        client.table("admin_audit_log").insert(
            {
                "action": "PARTICIPANT_UPDATED",
                "entity_type": "team",
                "entity_id": team["id"],
                "details": {"name": cleaned_name, "player_ids": selected_player_ids},
            }
        ).execute()
        return updated
    except Exception:
        client.table("teams").update({"name": old_name}).eq("id", team["id"]).execute()
        client.table("team_players").delete().eq("team_id", team["id"]).execute()
        if current_player_ids:
            client.table("team_players").insert(
                [
                    {"team_id": team["id"], "player_id": player_id}
                    for player_id in current_player_ids
                ]
            ).execute()
        raise


def created_participant_ids(audit_rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row["entity_id"])
        for row in audit_rows
        if row.get("action") == "PARTICIPANT_CREATED" and row.get("entity_id")
    }
