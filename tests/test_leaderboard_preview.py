import unittest

from lib.leaderboard_preview import (
    active_round_number,
    build_preview_rows,
    preview_href,
    toggle_preview_team,
)
from lib.scoring import build_team_standings


class LeaderboardPreviewTests(unittest.TestCase):
    def setUp(self):
        self.players = [
            {"id": f"p{tier}", "name": f"Spiller {tier}", "tier": tier}
            for tier in range(1, 8)
        ]
        self.scores = [
            {
                "player_id": f"p{tier}",
                "round": 1,
                "strokes": 69 + tier,
                "is_official": True,
            }
            for tier in range(1, 8)
        ]
        standings = build_team_standings(
            teams=[{"id": "team-a", "name": "Joakim"}],
            players=self.players,
            team_players=[
                {"team_id": "team-a", "player_id": player["id"]}
                for player in self.players
            ],
            scores=self.scores,
        )
        self.standing = standings[0]

    def test_click_opens_preview(self):
        self.assertEqual(toggle_preview_team(None, "team-a"), "team-a")
        self.assertEqual(preview_href(None, "team-a"), "?team=team-a")

    def test_clicking_same_team_closes_preview(self):
        self.assertIsNone(toggle_preview_team("team-a", "team-a"))
        self.assertEqual(preview_href("team-a", "team-a"), "?")

    def test_clicking_other_team_switches_preview(self):
        self.assertEqual(toggle_preview_team("team-a", "team-b"), "team-b")
        self.assertEqual(preview_href("team-a", "team-b"), "?team=team-b")

    def test_preview_shows_five_counting_and_two_dropped(self):
        rows = build_preview_rows(self.standing, active_round=1)
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            len([row for row in rows if row["selection"] == "COUNTING"]),
            5,
        )
        self.assertEqual(
            len([row for row in rows if row["selection"] == "DROPPED"]),
            2,
        )

    def test_preview_includes_tier_scores_total_hole_and_status(self):
        states = [
            {
                "player_id": "p1",
                "round": 1,
                "hole": 8,
                "is_finished": False,
                "status": "ACTIVE",
            },
            {
                "player_id": "p6",
                "round": 1,
                "hole": None,
                "is_finished": False,
                "status": "WD",
            },
        ]
        rows = build_preview_rows(self.standing, active_round=1, live_states=states)
        first = next(row for row in rows if row["player_id"] == "p1")
        withdrawn = next(row for row in rows if row["player_id"] == "p6")
        self.assertEqual(first["tier"], 1)
        self.assertEqual(first["round_scores"][1], -2)
        self.assertEqual(first["running_total"], -2)
        self.assertEqual(first["hole_status"], "Hull 8")
        self.assertEqual(first["status"], "ACTIVE")
        self.assertEqual(withdrawn["status"], "WD")

    def test_live_state_selects_active_round(self):
        states = [{"player_id": "p1", "round": 2}]
        self.assertEqual(active_round_number(self.scores, states), 2)

    def test_empty_round_is_pending_not_seven_dropped(self):
        empty_standing = build_team_standings(
            teams=[{"id": "team-a", "name": "Joakim"}],
            players=self.players,
            team_players=[
                {"team_id": "team-a", "player_id": player["id"]}
                for player in self.players
            ],
            scores=[],
        )[0]
        rows = build_preview_rows(empty_standing, active_round=1)
        self.assertEqual(
            len([row for row in rows if row["selection"] == "PENDING"]),
            7,
        )


if __name__ == "__main__":
    unittest.main()
