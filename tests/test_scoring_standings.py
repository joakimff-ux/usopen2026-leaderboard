"""Tests for leaderboard totals and ordering during an active tournament."""

from __future__ import annotations

import unittest

from lib.scoring import build_team_standings


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

    def test_sorts_by_cumulative_total_before_all_rounds_are_complete(self):
        standings = self.standings(
            {
                "Higher score": [[72, 72, 72, 72, 72, 90, 91]],
                "Lower score": [[70, 70, 70, 70, 70, 90, 91]],
            }
        )

        self.assertEqual([item.team_name for item in standings], ["Lower score", "Higher score"])
        self.assertEqual(standings[0].tournament_total, 350)
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
        self.assertEqual(standings[0].tournament_total, 740)

    def test_no_completed_rounds_falls_back_to_team_name(self):
        standings = self.standings({"Zulu": [], "Alpha": []})

        self.assertEqual([item.team_name for item in standings], ["Alpha", "Zulu"])
        self.assertTrue(all(item.completed_rounds == 0 for item in standings))
        self.assertTrue(all(item.tournament_total is None for item in standings))


if __name__ == "__main__":
    unittest.main()
