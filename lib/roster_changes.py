"""Post-round-two roster changes without mutating the original roster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


ROSTER_SIZE = 7
ROUND_FROM = 3


@dataclass(frozen=True)
class RosterChangeValidation:
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def build_original_rosters(
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    team_players: list[dict[str, Any]],
) -> dict[str, list[str]]:
    players_by_id = {str(player["id"]): player for player in players}
    rosters = {str(team["id"]): [] for team in teams}
    for link in team_players:
        team_id = str(link["team_id"])
        player_id = str(link["player_id"])
        if team_id in rosters and player_id in players_by_id:
            rosters[team_id].append(player_id)
    for player_ids in rosters.values():
        player_ids.sort(
            key=lambda player_id: (
                int(players_by_id[player_id].get("tier", 999)),
                str(players_by_id[player_id].get("name") or ""),
            )
        )
    return rosters


def validate_rosters(
    selected_by_team: dict[str, list[str]],
    valid_player_ids: set[str],
) -> RosterChangeValidation:
    errors: list[str] = []
    for team_id, player_ids in selected_by_team.items():
        if len(player_ids) != ROSTER_SIZE:
            errors.append(f"{team_id}: Nøyaktig 7 spillere må velges.")
            continue
        if len(set(player_ids)) != len(player_ids):
            errors.append(f"{team_id}: Samme spiller kan ikke velges flere ganger.")
        if any(player_id not in valid_player_ids for player_id in player_ids):
            errors.append(f"{team_id}: Ett eller flere spillervalg finnes ikke i turneringen.")
    return RosterChangeValidation(tuple(errors))


def apply_roster_changes(
    original_by_team: dict[str, list[str]],
    change_rows: list[dict[str, Any]],
    round_num: int = ROUND_FROM,
) -> dict[str, list[str]]:
    effective = {team_id: list(player_ids) for team_id, player_ids in original_by_team.items()}
    for row in change_rows:
        if int(row.get("round_from", ROUND_FROM)) > round_num:
            continue
        team_id = str(row["team_id"])
        old_player_id = str(row["old_player_id"])
        new_player_id = str(row["new_player_id"])
        player_ids = effective.get(team_id)
        if player_ids is None or old_player_id not in player_ids:
            continue
        if new_player_id in player_ids:
            continue
        player_ids[player_ids.index(old_player_id)] = new_player_id
    return effective


def build_change_pairs(
    original_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for team_id, original_ids in original_by_team.items():
        selected_ids = selected_by_team.get(team_id, original_ids)
        selected_set = set(selected_ids)
        original_set = set(original_ids)
        outgoing = [player_id for player_id in original_ids if player_id not in selected_set]
        incoming = [player_id for player_id in selected_ids if player_id not in original_set]
        if len(outgoing) != len(incoming):
            raise ValueError(f"Ugyldig bytteoppsett for lag {team_id}.")
        changes.extend(
            {
                "team_id": team_id,
                "old_player_id": old_player_id,
                "new_player_id": new_player_id,
            }
            for old_player_id, new_player_id in zip(outgoing, incoming)
        )
    return changes


def rosters_differ(
    current_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
) -> bool:
    return any(
        set(selected_by_team.get(team_id, [])) != set(current_ids)
        for team_id, current_ids in current_by_team.items()
    )


def changes_are_locked(active_change_set: dict[str, Any] | None) -> bool:
    return bool(active_change_set and active_change_set.get("is_locked"))


def round_two_is_finalized(tournament_rounds: list[dict[str, Any]]) -> bool:
    return any(
        int(row.get("round", 0)) == 2 and str(row.get("state") or "").upper() == "FINALIZED"
        for row in tournament_rounds
    )


def save_roster_changes(
    client: Any,
    tournament_id: str,
    original_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
    valid_player_ids: set[str],
    active_change_set: dict[str, Any] | None,
    round_two_finalized: bool,
    changed_by: str = "admin",
) -> dict[str, Any]:
    if changes_are_locked(active_change_set):
        raise ValueError("Bytter er allerede gjennomført.")
    if not round_two_finalized:
        raise ValueError("Bytter kan først lagres etter at runde 2 er ferdig.")
    validation = validate_rosters(selected_by_team, valid_player_ids)
    if not validation.is_valid:
        raise ValueError(" ".join(validation.errors))
    change_pairs = build_change_pairs(original_by_team, selected_by_team)
    if not change_pairs:
        raise ValueError("Ingen spillerbytter er valgt.")

    created = (
        client.table("roster_change_sets")
        .insert(
            {
                "tournament_id": tournament_id,
                "round_from": ROUND_FROM,
                "is_active": False,
                "is_locked": True,
                "created_by": changed_by,
            }
        )
        .execute()
        .data[0]
    )
    change_set_id = str(created["id"])
    rows = [
        {
            "change_set_id": change_set_id,
            "tournament_id": tournament_id,
            "team_id": pair["team_id"],
            "round_from": ROUND_FROM,
            "old_player_id": pair["old_player_id"],
            "new_player_id": pair["new_player_id"],
            "changed_by": changed_by,
        }
        for pair in change_pairs
    ]

    old_change_set_id = str(active_change_set["id"]) if active_change_set else None
    old_deactivated = False
    try:
        client.table("roster_changes").insert(rows).execute()
        if old_change_set_id:
            (
                client.table("roster_change_sets")
                .update({"is_active": False})
                .eq("id", old_change_set_id)
                .execute()
            )
            old_deactivated = True
        saved = (
            client.table("roster_change_sets")
            .update({"is_active": True})
            .eq("id", change_set_id)
            .execute()
            .data[0]
        )
        return saved
    except Exception:
        if old_change_set_id and old_deactivated:
            client.table("roster_change_sets").update({"is_active": True}).eq(
                "id", old_change_set_id
            ).execute()
        client.table("roster_change_sets").delete().eq("id", change_set_id).execute()
        raise


def unlock_roster_changes(
    client: Any,
    active_change_set: dict[str, Any],
    changed_by: str = "admin",
) -> dict[str, Any]:
    if not changes_are_locked(active_change_set):
        raise ValueError("Byttene er allerede låst opp.")
    response = (
        client.table("roster_change_sets")
        .update(
            {
                "is_locked": False,
                "unlocked_at": datetime.now(timezone.utc).isoformat(),
                "unlocked_by": changed_by,
            }
        )
        .eq("id", active_change_set["id"])
        .execute()
    )
    return response.data[0]
