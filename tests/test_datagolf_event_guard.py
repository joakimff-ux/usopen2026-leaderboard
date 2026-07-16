"""Tests for the fail-closed DataGolf event guard."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


# Keep this unit test independent of installed Streamlit/Supabase packages.
streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: None
sys.modules.setdefault("supabase", supabase_stub)

from lib.datagolf_sync import sync_live_scores  # noqa: E402


class FakeScoresTable:
    def __init__(self) -> None:
        self.rows = None

    def upsert(self, rows, on_conflict):
        self.rows = rows
        self.on_conflict = on_conflict
        return self

    def execute(self):
        return types.SimpleNamespace(data=self.rows)


class FakeClient:
    def __init__(self) -> None:
        self.table_calls: list[str] = []
        self.scores = FakeScoresTable()

    def table(self, name: str):
        self.table_calls.append(name)
        if name != "scores":
            raise AssertionError(f"Unexpected table access: {name}")
        return self.scores


class DataGolfEventGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.tournament = {
            "id": "tournament-1",
            "name": "The Open 2026",
            "datagolf_event_name": "The Open Championship",
        }

    def run_sync(self, payload):
        with patch("lib.datagolf_sync.fetch_live_tournament_data", return_value=payload), patch(
            "lib.datagolf_sync.fetch_players",
            return_value=[{"id": "player-1", "name": "Scottie Scheffler", "tier": 1}],
        ), patch(
            "lib.datagolf_sync.fetch_team_players",
            return_value=[],
        ):
            return sync_live_scores(self.client, self.tournament, api_key="test-key")

    def test_blocks_mismatched_event_before_database_write(self):
        result = self.run_sync(
            {
                "info": {"event_name": "U.S. Open", "current_round": 1},
                "data": [{"player_name": "Scottie Scheffler", "R1": 70}],
            }
        )

        self.assertFalse(result.success)
        self.assertIn("does not match", result.error or "")
        self.assertEqual(self.client.table_calls, [])

    def test_blocks_missing_received_event_before_database_write(self):
        result = self.run_sync(
            {"data": [{"player_name": "Scottie Scheffler", "R1": 70}]}
        )

        self.assertFalse(result.success)
        self.assertIn("did not include an event name", result.error or "")
        self.assertEqual(self.client.table_calls, [])

    def test_blocks_missing_configured_event_before_database_write(self):
        self.tournament["datagolf_event_name"] = None
        result = self.run_sync(
            {
                "info": {"event_name": "The Open Championship", "current_round": 1},
                "data": [{"player_name": "Scottie Scheffler", "R1": 70}],
            }
        )

        self.assertFalse(result.success)
        self.assertIn("no datagolf_event_name configured", result.error or "")
        self.assertEqual(self.client.table_calls, [])

    def test_matching_event_allows_score_write(self):
        result = self.run_sync(
            {
                "info": {"event_name": "  the   open championship ", "current_round": 1},
                "data": [{"player_name": "Scottie Scheffler", "R1": 70}],
            }
        )

        self.assertTrue(result.success)
        self.assertEqual(self.client.table_calls, ["scores"])
        self.assertEqual(
            self.client.scores.rows,
            [
                {
                    "player_id": "player-1",
                    "round": 1,
                    "strokes": 70,
                    "source": "DATAGOLF",
                    "is_official": True,
                    "updated_at": result.synced_at.isoformat(),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
