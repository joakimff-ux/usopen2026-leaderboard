from __future__ import annotations

import types
import unittest

from lib.participant_admin import create_participant, validate_participant


def sample_players():
    return [
        {"id": f"p{tier}", "name": f"Player {tier}", "tier": tier}
        for tier in range(1, 8)
    ]


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    def delete(self):
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        if self.table == "teams":
            row = dict(self.payload)
            row["id"] = "new-team"
            self.client.rows[self.table].append(row)
            return types.SimpleNamespace(data=[row])
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        self.client.rows[self.table].extend(rows)
        return types.SimpleNamespace(data=rows)


class FakeClient:
    def __init__(self):
        self.rows = {"teams": [], "team_players": [], "admin_audit_log": []}

    def table(self, name):
        return FakeQuery(self, name)


class ParticipantAdminTests(unittest.TestCase):
    def test_duplicate_name_is_rejected_case_insensitively(self):
        result = validate_participant(
            " joakim ",
            [f"p{tier}" for tier in range(1, 8)],
            sample_players(),
            [{"id": "existing", "name": "Joakim"}],
        )
        self.assertFalse(result.is_valid)
        self.assertIn("Deltakernavnet finnes allerede.", result.errors)

    def test_wrong_player_count_is_rejected(self):
        result = validate_participant(
            "Ny deltaker",
            [f"p{tier}" for tier in range(1, 7)],
            sample_players(),
            [],
        )
        self.assertFalse(result.is_valid)
        self.assertIn("Nøyaktig 7 spillere må velges.", result.errors)

    def test_successful_creation_writes_team_roster_and_audit(self):
        client = FakeClient()
        selected = [f"p{tier}" for tier in range(1, 8)]
        team = create_participant(
            client,
            "tournament-1",
            "Ny deltaker",
            selected,
            sample_players(),
            [],
        )
        self.assertEqual(team["id"], "new-team")
        self.assertEqual(len(client.rows["teams"]), 1)
        self.assertEqual(len(client.rows["team_players"]), 7)
        self.assertEqual(
            {(row["team_id"], row["player_id"]) for row in client.rows["team_players"]},
            {("new-team", player_id) for player_id in selected},
        )
        self.assertEqual(client.rows["admin_audit_log"][0]["action"], "PARTICIPANT_CREATED")


if __name__ == "__main__":
    unittest.main()
