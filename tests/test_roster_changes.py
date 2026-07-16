from __future__ import annotations

import unittest

from lib.roster_changes import (
    apply_roster_changes,
    build_change_pairs,
    changes_are_locked,
    save_roster_changes,
    round_two_is_finalized,
    validate_rosters,
)


class RosterChangeTests(unittest.TestCase):
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

    def test_saved_change_set_locks_editor_until_unlock(self):
        self.assertTrue(changes_are_locked({"id": "set-1", "is_locked": True}))
        self.assertFalse(changes_are_locked({"id": "set-1", "is_locked": False}))
        self.assertFalse(changes_are_locked(None))

    def test_locked_change_set_cannot_be_saved_again(self):
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["p8", "p2", "p3", "p4", "p5", "p6", "p7"]}
        with self.assertRaisesRegex(ValueError, "allerede gjennomført"):
            save_roster_changes(
                None,
                "tournament-1",
                original,
                selected,
                {f"p{index}" for index in range(1, 9)},
                {"id": "set-1", "is_locked": True},
                round_two_finalized=True,
            )

    def test_swaps_open_only_after_round_two_is_finalized(self):
        self.assertFalse(round_two_is_finalized([{"round": 2, "state": "OPEN"}]))
        self.assertTrue(round_two_is_finalized([{"round": 2, "state": "FINALIZED"}]))


if __name__ == "__main__":
    unittest.main()
