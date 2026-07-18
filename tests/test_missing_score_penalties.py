import unittest

from lib.scoring import build_team_standings


def _standings(scores, events, finalized_rounds=(1, 2, 3, 4), penalty=84):
    players = [
        {"id": f"p{number}", "name": f"Player {number}", "tier": number}
        for number in range(1, 8)
    ]
    rounds = [
        {"round": round_num, "state": "FINALIZED", "penalty_score": penalty}
        for round_num in finalized_rounds
    ]
    return build_team_standings(
        teams=[{"id": "t1", "name": "Team"}],
        players=players,
        team_players=[{"team_id": "t1", "player_id": player["id"]} for player in players],
        scores=[
            {"player_id": player_id, "round": round_num, "strokes": strokes, "is_official": True}
            for player_id, round_num, strokes in scores
        ],
        player_status_events=events,
        tournament_rounds=rounds,
    )[0]


def _event(player_id, status, effective_round, created_at="2026-07-17T18:00:00Z"):
    return {
        "player_id": player_id,
        "status": status,
        "effective_round": effective_round,
        "created_at": created_at,
    }


class MissingScorePenaltyTests(unittest.TestCase):
    def test_cut_keeps_rounds_one_and_two_and_penalizes_only_missed_weekend_rounds(self):
        scores = []
        for round_num in (1, 2):
            scores.extend((f"p{number}", round_num, 70 + number) for number in range(1, 8))
        for round_num in (3, 4):
            scores.extend((f"p{number}", round_num, 70 + number) for number in range(1, 5))
        standing = _standings(scores, [_event("p5", "CUT", 3)])

        self.assertEqual(standing.rounds[1].total, 5)
        self.assertEqual(standing.rounds[2].total, 5)
        self.assertEqual(standing.rounds[3].total, 14)
        self.assertEqual(standing.rounds[4].total, 14)
        self.assertEqual(standing.rounds[3].counting[-1].score_kind, "PENALTY")
        self.assertEqual(standing.rounds[3].counting[-1].status, "CUT")

    def test_wd_before_round_gets_penalty_when_round_is_frozen(self):
        scores = [(f"p{number}", 2, 70 + number) for number in range(1, 5)]
        standing = _standings(scores, [_event("p5", "WD", 2)])
        penalties = [item for item in standing.rounds[2].counting if item.score_kind == "PENALTY"]
        self.assertEqual(len(penalties), 1)
        self.assertEqual(penalties[0].status, "WD")

    def test_wd_mid_round_keeps_official_score_then_penalizes_later_round(self):
        scores = [(f"p{number}", 2, 70 + number) for number in range(1, 8)]
        scores.extend((f"p{number}", 3, 70 + number) for number in range(1, 5))
        standing = _standings(scores, [_event("p5", "WD", 2)])
        p5_round_two = next(item for item in standing.rounds[2].counting if item.player_id == "p5")
        self.assertEqual(p5_round_two.strokes, 3)
        self.assertEqual(p5_round_two.score_kind, "ACTUAL")
        self.assertTrue(any(item.status == "WD" and item.score_kind == "PENALTY" for item in standing.rounds[3].counting))

    def test_dq_without_official_score_gets_penalty(self):
        scores = [(f"p{number}", 1, 70 + number) for number in range(1, 5)]
        standing = _standings(scores, [_event("p6", "DQ", 1)])
        penalty = next(item for item in standing.rounds[1].counting if item.score_kind == "PENALTY")
        self.assertEqual(penalty.status, "DQ")
        self.assertEqual(penalty.strokes, 12)

    def test_delayed_datagolf_data_without_status_never_gets_penalty(self):
        scores = [(f"p{number}", 1, 70 + number) for number in range(1, 5)]
        standing = _standings(scores, [])
        self.assertIsNone(standing.rounds[1].total)
        self.assertFalse(any(item.score_kind == "PENALTY" for item in standing.rounds[1].counting))

    def test_live_partial_total_does_not_use_unfrozen_penalty(self):
        scores = [(f"p{number}", 3, 70 + number) for number in range(1, 5)]
        standing = _standings(scores, [_event("p5", "CUT", 3)], finalized_rounds=(1, 2, 4))
        self.assertEqual(standing.rounds[3].total, 2)
        self.assertFalse(
            any(item.score_kind == "PENALTY" for item in standing.rounds[3].counting)
        )

    def test_four_actual_scores_fill_exactly_one_place_with_penalty(self):
        scores = [(f"p{number}", 3, 70 + number) for number in range(1, 5)]
        events = [_event("p5", "CUT", 3), _event("p6", "CUT", 3), _event("p7", "CUT", 3)]
        standing = _standings(scores, events)
        penalties = [item for item in standing.rounds[3].counting if item.score_kind == "PENALTY"]
        self.assertEqual(len(standing.rounds[3].counting), 5)
        self.assertEqual(len(penalties), 1)

    def test_three_actual_scores_fill_exactly_two_places_with_penalty(self):
        scores = [(f"p{number}", 3, 70 + number) for number in range(1, 4)]
        events = [_event(f"p{number}", "CUT", 3) for number in range(4, 8)]
        standing = _standings(scores, events)
        penalties = [item for item in standing.rounds[3].counting if item.score_kind == "PENALTY"]
        self.assertEqual(len(standing.rounds[3].counting), 5)
        self.assertEqual(len(penalties), 2)


if __name__ == "__main__":
    unittest.main()
