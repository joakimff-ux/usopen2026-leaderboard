"""Tests for leaderboard totals and ordering during an active tournament."""

from __future__ import annotations

import unittest

from lib.scoring import build_team_standings, format_relative_score


def build_fixture(rounds_by_team: dict[str, list[list[int]]]):
    teams = []
    players = []
    team_players = []
    scores = []

    for team_index, (team_name, rounds) in enumerate(rounds_by_team.items(), start=1):
        team_id = f"team-{team_index}"
        teams.append({"id": team_id, "name": team_name})

        for player_index in range(7):
            player_id = f"{team_id}-player-{player_index + 1}"
            players.append(
                {
                    "id": player_id,
                    "name": f"{team_name} Player {player_index + 1}",
                    "tier": player_index + 1,
                }
            )
            team_players.append({"team_id": team_id, "player_id": player_id})

            for round_num, round_scores in enumerate(rounds, start=1):
                scores.append(
                    {
                        "player_id": player_id,
                        "round": round_num,
                        "strokes": round_scores[player_index],
                    }
                )

    return teams, players, team_players, scores


class LeaderboardStandingTests(unittest.TestCase):
    def standings(self, rounds_by_team: dict[str, list[list[int]]]):
        teams, players, team_players, scores = build_fixture(rounds_by_team)
        return build_team_standings(teams, players, team_players, scores)

    def swap_regression_standings(self, change_count: int):
        teams = [{"id": "team-1", "name": "Joakim"}]
        players = [
            {"id": f"p{index}", "name": f"Player {index}", "tier": index}
            for index in range(1, 11)
        ]
        team_players = [
            {"team_id": "team-1", "player_id": f"p{index}"}
            for index in range(1, 8)
        ]
        scores = [
            {
                "player_id": f"p{player_index}",
                "round": round_num,
                "strokes": (
                    60
                    if player_index >= 8
                    else 72
                    if player_index <= 5
                    else 80 + player_index
                ),
                "is_official": True,
            }
            for player_index in range(1, 11)
            for round_num in range(1, 5)
        ]
        changes = [
            {
                "team_id": "team-1",
                "old_player_id": f"p{index}",
                "new_player_id": f"p{index + 7}",
                "round_from": 3,
            }
            for index in range(1, change_count + 1)
        ]
        before = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            roster_change_rows=[],
        )[0]
        after = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            roster_change_rows=changes,
        )[0]
        return before, after

    def test_one_swap_does_not_change_round_one(self):
        before, after = self.swap_regression_standings(1)
        self.assertEqual(after.round_totals[1], before.round_totals[1])

    def test_three_swaps_do_not_change_round_two(self):
        before, after = self.swap_regression_standings(3)
        self.assertEqual(after.round_totals[2], before.round_totals[2])

    def test_incoming_players_first_count_from_round_three(self):
        _, after = self.swap_regression_standings(3)
        round_one_ids = {
            player.player_id
            for player in after.rounds[1].counting + after.rounds[1].dropped
        }
        round_three_ids = {
            player.player_id
            for player in after.rounds[3].counting + after.rounds[3].dropped
        }
        self.assertTrue({"p8", "p9", "p10"}.isdisjoint(round_one_ids))
        self.assertTrue({"p8", "p9", "p10"}.issubset(round_three_ids))

    def test_outgoing_players_still_count_in_rounds_one_and_two(self):
        _, after = self.swap_regression_standings(3)
        for round_num in (1, 2):
            round_ids = {
                player.player_id
                for player in (
                    after.rounds[round_num].counting
                    + after.rounds[round_num].dropped
                )
            }
            self.assertTrue({"p1", "p2", "p3"}.issubset(round_ids))

    def test_total_after_round_two_is_identical_before_and_after_swaps(self):
        before, after = self.swap_regression_standings(3)
        before_total = before.round_totals[1] + before.round_totals[2]
        after_total = after.round_totals[1] + after.round_totals[2]
        self.assertEqual(after_total, before_total)

    def test_sorts_by_cumulative_total_before_all_rounds_are_complete(self):
        standings = self.standings(
            {
                "Higher score": [[72, 72, 72, 72, 72, 90, 91]],
                "Lower score": [[70, 70, 70, 70, 70, 90, 91]],
            }
        )

        self.assertEqual([item.team_name for item in standings], ["Lower score", "Higher score"])
        self.assertEqual(standings[0].tournament_total, -10)
        self.assertEqual(standings[0].completed_rounds, 1)

    def test_team_with_more_completed_rounds_sorts_first(self):
        standings = self.standings(
            {
                "One round": [[68, 68, 68, 68, 68, 90, 91]],
                "Two rounds": [
                    [74, 74, 74, 74, 74, 90, 91],
                    [74, 74, 74, 74, 74, 90, 91],
                ],
            }
        )

        self.assertEqual(standings[0].team_name, "Two rounds")
        self.assertEqual(standings[0].completed_rounds, 2)
        self.assertEqual(standings[0].tournament_total, 20)

    def test_no_completed_rounds_falls_back_to_team_name(self):
        standings = self.standings({"Zulu": [], "Alpha": []})

        self.assertEqual([item.team_name for item in standings], ["Alpha", "Zulu"])
        self.assertTrue(all(item.completed_rounds == 0 for item in standings))
        self.assertTrue(all(item.tournament_total is None for item in standings))

    def test_five_best_relative_scores_count_and_two_worst_drop(self):
        standings = self.standings(
            {"Christine": [[69, 70, 72, 73, 74, 75, 76]]}
        )

        result = standings[0].rounds[1]
        self.assertEqual([player.strokes for player in result.counting], [-3, -2, 0, 1, 2])
        self.assertEqual([player.strokes for player in result.dropped], [3, 4])
        self.assertEqual(result.undecided, [])
        self.assertEqual(result.total, -2)

    def test_all_seven_equal_are_undecided_in_active_round(self):
        teams, players, team_players, _ = build_fixture({"Joakim": []})
        standing = build_team_standings(
            teams,
            players,
            team_players,
            [],
            live_states=[
                {
                    "player_id": player["id"],
                    "round": 1,
                    "round_score": 0,
                    "is_finished": False,
                }
                for player in players
            ],
        )[0]
        result = standing.rounds[1]

        self.assertEqual(result.counting, [])
        self.assertEqual(result.dropped, [])
        self.assertEqual(len(result.undecided), 7)
        self.assertEqual(result.total, 0)

    def test_three_players_tied_across_fifth_place_are_undecided(self):
        teams, players, team_players, _ = build_fixture({"Joakim": []})
        result = build_team_standings(
            teams,
            players,
            team_players,
            [],
            live_states=[
                {
                    "player_id": player["id"],
                    "round": 1,
                    "round_score": score,
                    "is_finished": False,
                }
                for player, score in zip(players, [-4, -3, -2, -1, 0, 0, 0])
            ],
        )[0].rounds[1]

        self.assertEqual([player.strokes for player in result.counting], [-4, -3, -2, -1])
        self.assertEqual(result.dropped, [])
        self.assertEqual([player.strokes for player in result.undecided], [0, 0, 0])
        self.assertEqual(result.total, -10)

    def test_previous_round_scores_do_not_resolve_active_round_tie(self):
        teams, players, team_players, scores = build_fixture(
            {"Joakim": [[66, 67, 68, 69, 70, 80, 81]]}
        )
        standing = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            live_states=[
                {
                    "player_id": player["id"],
                    "round": 2,
                    "round_score": 0,
                    "is_finished": False,
                }
                for player in players
            ],
        )[0]

        active_result = standing.rounds[2]
        self.assertEqual(active_result.counting, [])
        self.assertEqual(active_result.dropped, [])
        self.assertEqual(len(active_result.undecided), 7)
        self.assertEqual(active_result.total, 0)

    def test_reitan_tie_is_resolved_from_completed_round_two_only(self):
        names = [
            "Adam Scott",
            "Patrick Reed",
            "Rory McIlroy",
            "Chris Gotterup",
            "Kristoffer Reitan",
            "Min Woo Lee",
            "Viktor Hovland",
        ]
        players = [
            {"id": f"p{index}", "name": name, "tier": index}
            for index, name in enumerate(names, start=1)
        ]
        scores = [
            {
                "player_id": player["id"],
                "round": round_num,
                "strokes": strokes,
                "is_official": True,
            }
            for player, round_one, round_two in zip(
                players,
                [60, 61, 62, 63, 90, 64, 65],
                [66, 66, 67, 68, 71, 71, 74],
            )
            for round_num, strokes in ((1, round_one), (2, round_two))
        ]
        standing = build_team_standings(
            teams=[{"id": "joakim", "name": "Joakim"}],
            players=players,
            team_players=[
                {"team_id": "joakim", "player_id": player["id"]}
                for player in players
            ],
            scores=scores,
        )[0]
        round_two = standing.rounds[2]

        self.assertEqual(round_two.undecided, [])
        self.assertEqual(len(round_two.counting), 5)
        self.assertEqual(len(round_two.dropped), 2)
        self.assertIn("Kristoffer Reitan", [player.player_name for player in round_two.counting])
        self.assertIn("Min Woo Lee", [player.player_name for player in round_two.dropped])
        self.assertEqual(round_two.total, -22)

    def test_even_formats_as_e(self):
        self.assertEqual(format_relative_score(0), "E")
        self.assertEqual(format_relative_score(-10), "−10")
        self.assertEqual(format_relative_score(4), "+4")

    def test_active_round_uses_live_today_instead_of_absolute_strokes(self):
        teams, players, team_players, scores = build_fixture(
            {"Christine": [[74, 74, 74, 74, 74, 80, 81]]}
        )
        live_states = [
            {
                "player_id": player["id"],
                "round": 1,
                "round_score": score,
                "is_finished": False,
            }
            for player, score in zip(players, [-4, -3, -2, -1, 0, 1, 2])
        ]

        standings = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            live_states=live_states,
        )

        self.assertEqual(standings[0].round_totals[1], -10)

    def test_finished_round_uses_absolute_strokes_minus_course_par(self):
        teams, players, team_players, scores = build_fixture(
            {"Christine": [[69, 70, 71, 72, 73, 80, 81]]}
        )
        live_states = [
            {
                "player_id": player["id"],
                "round": 1,
                "round_score": -20,
                "is_finished": True,
            }
            for player in players
        ]

        standings = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            live_states=live_states,
            course_par=72,
        )

        self.assertEqual(standings[0].round_totals[1], -5)

    def test_relative_total_sums_multiple_rounds(self):
        standings = self.standings(
            {
                "Christine": [
                    [70, 70, 70, 70, 70, 80, 81],
                    [73, 73, 73, 73, 73, 80, 81],
                ]
            }
        )

        self.assertEqual(standings[0].round_totals, {1: -10, 2: 5, 3: None, 4: None})
        self.assertEqual(standings[0].tournament_total, -5)

    def test_christine_355_absolute_strokes_displays_minus_five(self):
        standings = self.standings(
            {"Christine": [[70, 71, 71, 71, 72, 80, 81]]}
        )

        self.assertEqual(sum([70, 71, 71, 71, 72]), 355)
        self.assertEqual(standings[0].round_totals[1], -5)

    def test_roster_change_uses_original_for_rounds_one_two_and_new_from_three(self):
        teams = [{"id": "team-1", "name": "Owner"}]
        players = [
            {"id": f"p{index}", "name": f"Player {index}", "tier": index}
            for index in range(1, 9)
        ]
        team_players = [
            {"team_id": "team-1", "player_id": f"p{index}"}
            for index in range(1, 8)
        ]
        scores = [
            {
                "player_id": f"p{player_index}",
                "round": round_num,
                "strokes": 62 if player_index == 8 else 72,
            }
            for player_index in range(1, 9)
            for round_num in range(1, 5)
        ]
        changes = [
            {
                "team_id": "team-1",
                "old_player_id": "p1",
                "new_player_id": "p8",
                "round_from": 3,
            }
        ]

        standing = build_team_standings(
            teams,
            players,
            team_players,
            scores,
            roster_change_rows=changes,
        )[0]

        round_one_ids = {
            result.player_id
            for result in standing.rounds[1].counting + standing.rounds[1].dropped
        }
        round_three_ids = {
            result.player_id
            for result in standing.rounds[3].counting + standing.rounds[3].dropped
        }
        self.assertIn("p1", round_one_ids)
        self.assertNotIn("p8", round_one_ids)
        self.assertIn("p8", round_three_ids)
        self.assertNotIn("p1", round_three_ids)
        self.assertEqual(standing.round_totals, {1: 0, 2: 0, 3: -10, 4: -10})
        self.assertEqual(standing.tournament_total, -20)
        self.assertEqual(standing.original_player_ids, tuple(f"p{i}" for i in range(1, 8)))
        self.assertEqual(
            set(standing.active_player_ids),
            {"p8", "p2", "p3", "p4", "p5", "p6", "p7"},
        )


if __name__ == "__main__":
    unittest.main()
