import unittest

from lib.competition_data import load_competition_data, resolve_course_par


class FakeProductionDataSource:
    def __init__(self):
        self.teams = [{"id": "team-joakim", "name": "Joakim"}]
        self.players = [
            {"id": f"p{index}", "name": f"Player {index}", "tier": index}
            for index in range(1, 10)
        ]
        self.team_players = [
            {"team_id": "team-joakim", "player_id": f"p{index}"}
            for index in range(1, 8)
        ]
        round_one = [69, 70, 70, 71, 71, 78, 79]
        round_two = [66, 66, 67, 68, 71, 71, 74]
        self.scores = [
            {
                "player_id": f"p{index}",
                "round": round_num,
                "strokes": strokes,
                "is_official": True,
            }
            for round_num, values in ((1, round_one), (2, round_two))
            for index, strokes in enumerate(values, start=1)
        ]
        self.scores.extend(
            {
                "player_id": player_id,
                "round": round_num,
                "strokes": strokes,
                "is_official": True,
            }
            for player_id, round_num, strokes in (
                ("p8", 1, 60),
                ("p8", 2, 60),
                ("p9", 1, 61),
                ("p9", 2, 61),
            )
        )
        self.live_states = [
            {
                "player_id": f"p{index}",
                "round": 2,
                "round_score": relative,
                "hole": 18 if index < 7 else None,
                "is_finished": False,
                "status": "ACTIVE" if index < 7 else "CUT",
            }
            for index, relative in enumerate([-4, -4, -3, -2, 1, 1, 0], start=1)
        ]
        self.changes = [
            {
                "team_id": "team-joakim",
                "old_player_id": "p6",
                "new_player_id": "p8",
                "round_from": 3,
            },
            {
                "team_id": "team-joakim",
                "old_player_id": "p7",
                "new_player_id": "p9",
                "round_from": 3,
            },
        ]

    def fetch_teams(self, client, tournament_id):
        return self.teams

    def fetch_players(self, client, tournament_id):
        return self.players

    def fetch_team_players(self, client, tournament_id):
        return self.team_players

    def fetch_scores(self, client, tournament_id):
        return self.scores

    def fetch_player_status_events(self, client, tournament_id):
        return []

    def fetch_tournament_rounds(self, client, tournament_id):
        return []

    def fetch_active_roster_changes(self, client, tournament_id):
        return self.changes

    def fetch_live_player_states(self, client, tournament_id):
        return self.live_states


class ProductionLeaderboardPathTests(unittest.TestCase):
    def test_royal_birkdale_uses_par_70(self):
        self.assertEqual(resolve_course_par({"course_name": "Royal Birkdale"}), 70)

    def test_actual_app_data_path_freezes_rounds_one_and_two(self):
        source = FakeProductionDataSource()
        data = load_competition_data(
            object(),
            "the-open-2026",
            {
                "course_name": "Royal Birkdale",
                "num_rounds": 4,
                "counting_scores": 5,
                "dropped_scores": 2,
            },
            data_source=source,
        )

        standing = data["standings"][0]
        self.assertEqual(standing.round_totals[1], 1)
        self.assertEqual(standing.round_totals[2], -12)
        self.assertEqual(
            {result.player_id for result in standing.rounds[1].counting + standing.rounds[1].dropped},
            {f"p{index}" for index in range(1, 8)},
        )
        self.assertEqual(
            {result.player_id for result in standing.rounds[2].counting + standing.rounds[2].dropped},
            {f"p{index}" for index in range(1, 8)},
        )
        self.assertNotIn("p8", standing.original_player_ids)
        self.assertIn("p8", standing.active_player_ids)

        source.changes = []
        before_swaps = load_competition_data(
            object(),
            "the-open-2026",
            {"course_name": "Royal Birkdale"},
            data_source=source,
        )["standings"][0]
        self.assertEqual(standing.round_totals[1], before_swaps.round_totals[1])
        self.assertEqual(standing.round_totals[2], before_swaps.round_totals[2])


if __name__ == "__main__":
    unittest.main()
