import unittest
from pathlib import Path

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

    def test_stale_live_state_does_not_override_newer_score_round(self):
        scores = [{"player_id": "p1", "round": 2}]
        states = [{"player_id": "p1", "round": 1}]
        self.assertEqual(active_round_number(scores, states), 2)

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

    def test_all_equal_active_scores_are_pending(self):
        standing = build_team_standings(
            teams=[{"id": "team-a", "name": "Joakim"}],
            players=self.players,
            team_players=[
                {"team_id": "team-a", "player_id": player["id"]}
                for player in self.players
            ],
            scores=[
                {
                    "player_id": player["id"],
                    "round": 1,
                    "strokes": 72,
                    "is_official": True,
                }
                for player in self.players
            ],
        )[0]

        rows = build_preview_rows(standing, active_round=1)
        self.assertTrue(all(row["selection"] == "PENDING" for row in rows))

    def test_three_way_cutoff_tie_marks_only_affected_players_pending(self):
        strokes = [68, 69, 70, 71, 72, 72, 72]
        standing = build_team_standings(
            teams=[{"id": "team-a", "name": "Joakim"}],
            players=self.players,
            team_players=[
                {"team_id": "team-a", "player_id": player["id"]}
                for player in self.players
            ],
            scores=[
                {
                    "player_id": player["id"],
                    "round": 1,
                    "strokes": score,
                    "is_official": True,
                }
                for player, score in zip(self.players, strokes)
            ],
        )[0]

        rows = build_preview_rows(standing, active_round=1)
        self.assertEqual(sum(row["selection"] == "COUNTING" for row in rows), 4)
        self.assertEqual(sum(row["selection"] == "DROPPED" for row in rows), 0)
        self.assertEqual(sum(row["selection"] == "PENDING" for row in rows), 3)

    def test_team_detail_renders_undecided_results(self):
        app_source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertIn("for player in round_result.undecided", app_source)
        self.assertIn('st.markdown("**Ikke avgjort**")', app_source)

    def test_philip_swaps_show_team_specific_inactive_and_active_rows(self):
        players = [
            {"id": "hovland", "name": "Viktor Hovland", "tier": 1},
            {"id": "cam", "name": "Cam Smith", "tier": 2},
            *[
                {"id": f"base-{index}", "name": f"Base {index}", "tier": index + 2}
                for index in range(1, 6)
            ],
            {"id": "detry", "name": "Thomas Detry", "tier": 2},
            {"id": "morikawa", "name": "Collin Morikawa", "tier": 1},
        ]
        original_ids = ["hovland", "cam", *[f"base-{index}" for index in range(1, 6)]]
        scores = [
            {
                "player_id": player["id"],
                "round": round_num,
                "strokes": 72,
                "is_official": True,
            }
            for player in players
            for round_num in range(1, 5)
        ]
        changes = [
            {
                "team_id": "philip",
                "old_player_id": "hovland",
                "new_player_id": "morikawa",
                "round_from": 3,
            },
            {
                "team_id": "philip",
                "old_player_id": "cam",
                "new_player_id": "detry",
                "round_from": 3,
            },
        ]
        standing = build_team_standings(
            teams=[{"id": "philip", "name": "Philip"}],
            players=players,
            team_players=[
                {"team_id": "philip", "player_id": player_id}
                for player_id in original_ids
            ],
            scores=scores,
            roster_change_rows=changes,
        )[0]

        rows = build_preview_rows(standing, active_round=3)
        hovland = next(row for row in rows if row["player_id"] == "hovland")
        cam = next(row for row in rows if row["player_id"] == "cam")
        morikawa = next(row for row in rows if row["player_id"] == "morikawa")
        detry = next(row for row in rows if row["player_id"] == "detry")

        for outgoing in (hovland, cam):
            self.assertEqual(outgoing["status"], "INACTIVE")
            self.assertEqual(outgoing["selection"], "INACTIVE")
            self.assertEqual(outgoing["round_scores"][1], 0)
            self.assertEqual(outgoing["round_scores"][2], 0)
            self.assertIsNone(outgoing["round_scores"][3])
            self.assertIsNone(outgoing["round_scores"][4])
        for incoming in (morikawa, detry):
            self.assertEqual(incoming["status"], "ACTIVE")
            self.assertEqual(incoming["roster_note"], "Byttet inn fra R3")
            self.assertIsNone(incoming["round_scores"][1])
            self.assertIsNone(incoming["round_scores"][2])
            self.assertEqual(incoming["round_scores"][3], 0)
            self.assertEqual(incoming["round_scores"][4], 0)

    def test_team_detail_uses_the_same_roster_status_overview(self):
        app_source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        team_detail_source = app_source.split("def page_team_detail", 1)[1].split(
            "def page_admin", 1
        )[0]
        self.assertIn("leaderboard_preview.build_preview_rows", team_detail_source)
        self.assertIn("styles.render_team_preview", team_detail_source)


if __name__ == "__main__":
    unittest.main()
