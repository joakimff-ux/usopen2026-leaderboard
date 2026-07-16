from __future__ import annotations

from pathlib import Path
import unittest

from lib.roster_changes import (
    apply_roster_changes,
    build_change_pairs,
    change_count_by_team,
    round_three_has_started,
    save_roster_changes,
    round_two_is_finalized,
    validate_rosters,
)


class FakeRpcQuery:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return type("Response", (), {"data": self.data})()


class FakeRpcClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return FakeRpcQuery("change-set-1")


class RosterChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")

    def test_admin_ui_uses_one_confirmed_save_for_all_teams(self):
        self.assertIn('"💾 Lagre alle bytter"', self.app_source)
        self.assertIn('@st.dialog("Bekreft spillerbytter")', self.app_source)
        self.assertIn('"Ja, gjennomfør bytter"', self.app_source)
        self.assertNotIn('"Lagre": True', self.app_source)
        self.assertNotIn("unlock_roster_changes", self.app_source)

    def test_admin_ui_shows_automatic_round_three_lock_message(self):
        self.assertIn(
            '"Byttevinduet er stengt. Runde 3 har startet."',
            self.app_source,
        )

    def test_duplicate_player_is_rejected(self):
        selected = {"team-1": ["p1", "p1", "p3", "p4", "p5", "p6", "p7"]}
        validation = validate_rosters(selected, {f"p{index}" for index in range(1, 9)})
        self.assertFalse(validation.is_valid)
        self.assertIn("team-1: Samme spiller kan ikke velges flere ganger.", validation.errors)

    def test_change_pairs_only_include_actual_replacements(self):
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["p8", "p2", "p3", "p4", "p5", "p6", "p7"]}
        self.assertEqual(
            build_change_pairs(original, selected),
            [{"team_id": "team-1", "old_player_id": "p1", "new_player_id": "p8"}],
        )

    def test_change_applies_from_round_three_only(self):
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        changes = [
            {
                "team_id": "team-1",
                "old_player_id": "p1",
                "new_player_id": "p8",
                "round_from": 3,
            }
        ]
        self.assertEqual(apply_roster_changes(original, changes, round_num=2), original)
        self.assertEqual(
            apply_roster_changes(original, changes, round_num=3)["team-1"],
            ["p8", "p2", "p3", "p4", "p5", "p6", "p7"],
        )

    def test_more_than_three_changes_on_one_team_is_rejected(self):
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["p8", "p9", "p10", "p11", "p5", "p6", "p7"]}
        validation = validate_rosters(
            selected,
            {f"p{index}" for index in range(1, 12)},
            original,
        )
        self.assertFalse(validation.is_valid)
        self.assertIn("team-1: Maks 3 spillerbytter er tillatt.", validation.errors)

    def test_change_counter_is_per_team(self):
        original = {
            "team-1": [f"p{index}" for index in range(1, 8)],
            "team-2": [f"q{index}" for index in range(1, 8)],
        }
        selected = {
            "team-1": ["p8", "p9", "p3", "p4", "p5", "p6", "p7"],
            "team-2": original["team-2"],
        }
        self.assertEqual(change_count_by_team(original, selected), {"team-1": 2, "team-2": 0})

    def test_all_changes_are_sent_in_one_atomic_rpc(self):
        client = FakeRpcClient()
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["p8", "p9", "p3", "p4", "p5", "p6", "p7"]}
        save_roster_changes(
            client,
            "tournament-1",
            original,
            selected,
            {f"p{index}" for index in range(1, 10)},
            round_two_finalized=True,
            round_three_started=False,
        )
        self.assertEqual(len(client.calls), 1)
        name, params = client.calls[0]
        self.assertEqual(name, "save_roster_changes_atomic")
        self.assertEqual(len(params["p_changes"]), 2)

    def test_swaps_open_only_after_round_two_is_finalized(self):
        self.assertFalse(round_two_is_finalized([{"round": 2, "state": "OPEN"}]))
        self.assertTrue(round_two_is_finalized([{"round": 2, "state": "FINALIZED"}]))

    def test_round_three_start_closes_window(self):
        self.assertTrue(round_three_has_started([{"round": 3}], []))
        self.assertTrue(
            round_three_has_started([], [{"round": 3, "hole": 1, "is_finished": False}])
        )
        self.assertFalse(
            round_three_has_started(
                [],
                [{"round": 3, "hole": None, "round_score": 0, "is_finished": False}],
            )
        )


if __name__ == "__main__":
    unittest.main()
