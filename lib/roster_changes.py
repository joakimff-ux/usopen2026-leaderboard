"""Post-round-two roster changes without mutating the original roster."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROSTER_SIZE = 7
ROUND_FROM = 3
MAX_CHANGES_PER_TEAM = 3


@dataclass(frozen=True)
class RosterChangeValidation:
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RosterEditorDefaults:
    original_by_team: dict[str, list[str]]
    active_by_team: dict[str, list[str]]
    errors_by_team: dict[str, tuple[str, ...]]

    @property
    def is_valid(self) -> bool:
        return not self.errors_by_team


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


def build_roster_editor_defaults(
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    team_players: list[dict[str, Any]],
    active_change_rows: list[dict[str, Any]],
) -> RosterEditorDefaults:
    original_by_team = build_original_rosters(teams, players, team_players)
    active_by_team = apply_roster_changes(original_by_team, active_change_rows)
    valid_player_ids = {str(player["id"]) for player in players}
    errors_by_team: dict[str, tuple[str, ...]] = {}

    for team in teams:
        team_id = str(team["id"])
        player_ids = active_by_team.get(team_id, [])
        errors: list[str] = []
        if len(player_ids) != ROSTER_SIZE:
            errors.append(
                f"Fant {len(player_ids)} av {ROSTER_SIZE} gyldige spiller-ID-er i aktiv roster."
            )
        if len(set(player_ids)) != len(player_ids):
            errors.append("Aktiv roster inneholder samme spiller flere ganger.")
        unknown_ids = [player_id for player_id in player_ids if player_id not in valid_player_ids]
        if unknown_ids:
            errors.append(
                "Aktiv roster inneholder ukjente spiller-ID-er: " + ", ".join(unknown_ids)
            )
        if errors:
            errors_by_team[team_id] = tuple(errors)

    return RosterEditorDefaults(
        original_by_team=original_by_team,
        active_by_team=active_by_team,
        errors_by_team=errors_by_team,
    )


def validate_rosters(
    selected_by_team: dict[str, list[str]],
    valid_player_ids: set[str],
    original_by_team: dict[str, list[str]] | None = None,
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
        if original_by_team is not None:
            changes_used = len(set(original_by_team.get(team_id, [])) - set(player_ids))
            if changes_used > MAX_CHANGES_PER_TEAM:
                errors.append(
                    f"{team_id}: Maks {MAX_CHANGES_PER_TEAM} spillerbytter er tillatt."
                )
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


def change_count_by_team(
    original_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
) -> dict[str, int]:
    return {
        team_id: len(set(original_ids) - set(selected_by_team.get(team_id, original_ids)))
        for team_id, original_ids in original_by_team.items()
    }


def save_roster_changes(
    client: Any,
    tournament_id: str,
    original_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
    valid_player_ids: set[str],
    window_is_open: bool,
    changed_by: str = "admin",
) -> dict[str, Any]:
    if not window_is_open:
        raise ValueError("Byttevinduet er stengt.")
    validation = validate_rosters(selected_by_team, valid_player_ids, original_by_team)
    if not validation.is_valid:
        raise ValueError(" ".join(validation.errors))
    change_pairs = build_change_pairs(original_by_team, selected_by_team)

    rows = [
        {
            "team_id": pair["team_id"],
            "old_player_id": pair["old_player_id"],
            "new_player_id": pair["new_player_id"],
        }
        for pair in change_pairs
    ]
    response = (
        client.rpc(
            "save_roster_changes_atomic",
            {
                "p_tournament_id": tournament_id,
                "p_round_from": ROUND_FROM,
                "p_changed_by": changed_by,
                "p_changes": rows,
            },
        )
        .execute()
    )
    return {"id": response.data}
