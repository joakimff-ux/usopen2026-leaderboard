import unittest

from lib.competition_data import (
    leaderboard_positions,
    load_competition_data,
    resolve_course_par,
)
from lib.scoring import format_relative_score


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


class NineTeamProductionDataSource(FakeProductionDataSource):
    TOTALS = {
        "Philip": -18,
        "Mats": -15,
        "Christine": -15,
        "Ulls": -15,
        "Lars": -14,
        "Johan": -13,
        "Steven": -13,
        "Joakim": -11,
        "Thomas": -10,
    }

    def __init__(self):
        self.teams = [
            {"id": f"team-{name.casefold()}", "name": name}
            for name in self.TOTALS
        ]
        self.players = []
        self.team_players = []
        self.scores = []
        self.live_states = []
        self.changes = []
        for team in self.teams:
            team_name = team["name"]
            team_total = self.TOTALS[team_name]
            for slot in range(1, 8):
                player_id = f"{team['id']}-p{slot}"
                self.players.append(
                    {"id": player_id, "name": f"{team_name} Player {slot}", "tier": slot}
                )
                self.team_players.append(
                    {"team_id": team["id"], "player_id": player_id}
                )
                r1_strokes = 70 + team_total if slot == 1 else (70 if slot <= 5 else 90)
                self.scores.extend(
                    [
                        {
                            "player_id": player_id,
                            "round": 1,
                            "strokes": r1_strokes,
                            "is_official": True,
                        },
                        {
                            "player_id": player_id,
                            "round": 2,
                            "strokes": 70 if slot <= 5 else 90,
                            "is_official": True,
                        },
                        {
                            "player_id": player_id,
                            "round": 3,
                            "strokes": 70,
                            "is_official": True,
                        },
                    ]
                )
                self.live_states.append(
                    {
                        "player_id": player_id,
                        "round": 3,
                        "round_score": 0,
                        "hole": None,
                        "is_finished": False,
                        "status": "ACTIVE",
                    }
                )


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

    def test_actual_app_path_sorts_all_nine_teams_and_rebuilds_positions(self):
        data = load_competition_data(
            object(),
            "the-open-2026",
            {"course_name": "Royal Birkdale"},
            data_source=NineTeamProductionDataSource(),
        )
        standings = data["standings"]

        self.assertEqual(
            [(item.team_name, item.tournament_total) for item in standings],
            [
                ("Philip", -18),
                ("Christine", -15),
                ("Mats", -15),
                ("Ulls", -15),
                ("Lars", -14),
                ("Johan", -13),
                ("Steven", -13),
                ("Joakim", -11),
                ("Thomas", -10),
            ],
        )
        self.assertEqual(leaderboard_positions(standings, 3), [1, 2, 2, 2, 5, 6, 6, 8, 9])
        self.assertTrue(all(item.round_totals[3] is None for item in standings))
        self.assertTrue(
            all(format_relative_score(item.round_totals[3]) == "\u2014" for item in standings)
        )

    def test_real_zero_and_minus_two_round_three_scores_affect_total_and_order(self):
        source = NineTeamProductionDataSource()
        selected = {"Philip": [0, 0, 0, 0, 0], "Mats": [-2, 0, 0, 0, 0]}
        for team_name, live_scores in selected.items():
            for slot, round_score in enumerate(live_scores, start=1):
                player_id = f"team-{team_name.casefold()}-p{slot}"
                state = next(
                    item for item in source.live_states if item["player_id"] == player_id
                )
                state["hole"] = slot
                state["round_score"] = round_score

        standings = load_competition_data(
            object(),
            "the-open-2026",
            {"course_name": "Royal Birkdale"},
            data_source=source,
        )["standings"]
        by_name = {item.team_name: item for item in standings}

        self.assertEqual(by_name["Philip"].round_totals[3], 0)
        self.assertEqual(format_relative_score(by_name["Philip"].round_totals[3]), "E")
        self.assertEqual(by_name["Philip"].tournament_total, -18)
        self.assertEqual(by_name["Mats"].round_totals[3], -2)
        self.assertEqual(by_name["Mats"].tournament_total, -17)
        self.assertLess(
            standings.index(by_name["Mats"]),
            standings.index(next(item for item in standings if item.team_name == "Christine")),
        )

    def test_one_started_player_produces_a_running_round_three_score(self):
        source = NineTeamProductionDataSource()
        state = next(
            item
            for item in source.live_states
            if item["player_id"] == "team-philip-p1"
        )
        state["hole"] = 3
        state["round_score"] = -2

        standings = load_competition_data(
            object(),
            "the-open-2026",
            {"course_name": "Royal Birkdale"},
            data_source=source,
        )["standings"]
        philip = next(item for item in standings if item.team_name == "Philip")

        self.assertEqual(philip.round_totals[3], -2)
        self.assertEqual(philip.tournament_total, -20)


if __name__ == "__main__":
    unittest.main()
