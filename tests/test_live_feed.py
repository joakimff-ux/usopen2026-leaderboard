import unittest

from lib.live_feed import LiveSnapshot, build_events, group_affected_teams


def _snapshot(hole=7, score=-1, **changes):
    values = {
        "player_id": "player-1",
        "player_name": "Rory McIlroy",
        "round": 1,
        "hole": hole,
        "is_finished": False,
        "round_score": score,
        "status": "ACTIVE",
        "end_hole": 18,
        "source_updated_at": "2026-07-16 12:00 UTC",
    }
    values.update(changes)
    return LiveSnapshot(**values)


class LiveFeedTests(unittest.TestCase):
    def test_new_birdie(self):
        events = build_events("tournament-1", _snapshot(), _snapshot(hole=8, score=-2))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "BIRDIE")
        self.assertEqual(events[0]["hole"], 8)
        self.assertEqual(events[0]["hole_score"], -1)
        self.assertEqual(events[0]["round_score"], -2)

    def test_new_bogey(self):
        events = build_events("tournament-1", _snapshot(), _snapshot(hole=8, score=0))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "BOGEY")
        self.assertEqual(events[0]["hole_score"], 1)

    def test_unchanged_score_and_hole_creates_no_event(self):
        self.assertEqual(build_events("tournament-1", _snapshot(), _snapshot()), [])

    def test_same_player_on_multiple_teams_is_grouped_under_one_event(self):
        roster = [
            {"player_id": "player-1", "teams": {"name": "Joakim"}},
            {"player_id": "player-1", "teams": {"name": "Thomas"}},
            {"player_id": "player-1", "teams": {"name": "Joakim"}},
        ]
        teams = group_affected_teams(roster)
        events = build_events("tournament-1", _snapshot(), _snapshot(hole=8, score=-2))
        self.assertEqual(len(events), 1)
        self.assertEqual(teams["player-1"], ["Joakim", "Thomas"])

    def test_repeated_transition_has_stable_dedupe_key(self):
        first = build_events("tournament-1", _snapshot(), _snapshot(hole=8, score=-2))
        repeated = build_events("tournament-1", _snapshot(), _snapshot(hole=8, score=-2))
        self.assertEqual(first[0]["dedupe_key"], repeated[0]["dedupe_key"])

    def test_skipped_holes_do_not_invent_an_event(self):
        self.assertEqual(
            build_events("tournament-1", _snapshot(), _snapshot(hole=10, score=-3)),
            [],
        )

    def test_round_complete_and_terminal_status(self):
        current = _snapshot(hole=None, score=-2, is_finished=True, status="WD")
        events = build_events("tournament-1", _snapshot(hole=18, score=-2), current)
        self.assertEqual(
            [event["event_type"] for event in events],
            ["ROUND_COMPLETE", "WD"],
        )


if __name__ == "__main__":
    unittest.main()
