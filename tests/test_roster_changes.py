from __future__ import annotations

from pathlib import Path
import unittest

from lib.roster_changes import (
    apply_roster_changes,
    build_change_pairs,
    build_roster_editor_defaults,
    build_roster_change_pool,
    build_roster_slot_options,
    change_count_by_team,
    ROSTER_CHANGE_POOL_NAMES,
    save_roster_changes,
    validate_roster_change_pool,
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

    def test_admin_ui_uses_manual_persisted_window_control(self):
        self.assertIn('"🔓 Byttevindu"', self.app_source)
        self.assertIn('"Steng byttevindu"', self.app_source)
        self.assertIn('"Åpne byttevindu"', self.app_source)
        self.assertIn("db.set_roster_change_window", self.app_source)
        self.assertNotIn("round_two_is_finalized", self.app_source)
        self.assertNotIn("round_three_has_started", self.app_source)

    def test_admin_ui_has_operational_dashboard_and_quick_tools(self):
        for label in (
            '"Lag"',
            '"Ferdige"',
            '"Mangler"',
            '"Bytter brukt"',
            '"Søk i lag, eier eller spiller"',
            'f"**Hurtignavigasjon:',
            '"↩ Tilbakestill lag"',
        ):
            self.assertIn(label, self.app_source)

    def test_admin_ui_prevents_more_edits_after_three_changes(self):
        self.assertIn("lock_unchanged_slot", self.app_source)
        self.assertIn(
            '"Maks tre bytter er brukt. Uendrede spillervalg er låst."',
            self.app_source,
        )

    def test_admin_ui_shows_summary_and_csv_export(self):
        self.assertIn('heading="Sammendrag før lagring"', self.app_source)
        self.assertIn('"📥 Last ned bytter (CSV)"', self.app_source)
        self.assertIn(
            '["Lag", "OUT spiller", "IN spiller", "Tidspunkt", "Admin"]',
            self.app_source,
        )

    def test_saved_change_overview_shows_every_team_and_popularity(self):
        self.assertIn('st.markdown("### Bytteoversikt")', self.app_source)
        self.assertIn("for team in teams:", self.app_source)
        self.assertIn('st.markdown("**Mest populære inn:**")', self.app_source)
        self.assertIn('st.markdown("**Mest populære ut:**")', self.app_source)
        self.assertIn("incoming.most_common(3)", self.app_source)
        self.assertIn("outgoing.most_common(3)", self.app_source)

    def test_duplicate_player_is_rejected(self):
        selected = {"team-1": ["p1", "p1", "p3", "p4", "p5", "p6", "p7"]}
        validation = validate_rosters(selected, {f"p{index}" for index in range(1, 9)})
        self.assertFalse(validation.is_valid)
        self.assertIn("team-1: Samme spiller kan ikke velges flere ganger.", validation.errors)

    def test_editor_prefills_multiple_teams_with_their_actual_player_ids(self):
        teams = [
            {"id": "christine", "name": "Christine"},
            {"id": "joakim", "name": "Joakim"},
        ]
        players = [
            {"id": f"c{index}", "name": f"Christine Player {index}", "tier": index}
            for index in range(1, 8)
        ] + [
            {"id": f"j{index}", "name": f"Joakim Player {index}", "tier": index}
            for index in range(1, 8)
        ]
        links = [
            {"team_id": team_id, "player_id": f"{prefix}{index}"}
            for team_id, prefix in (("christine", "c"), ("joakim", "j"))
            for index in range(1, 8)
        ]

        defaults = build_roster_editor_defaults(teams, players, links, [])

        self.assertEqual(defaults.active_by_team["christine"], [f"c{i}" for i in range(1, 8)])
        self.assertEqual(defaults.active_by_team["joakim"], [f"j{i}" for i in range(1, 8)])
        self.assertTrue(defaults.is_valid)
        self.assertTrue(
            all(len(set(player_ids)) == 7 for player_ids in defaults.active_by_team.values())
        )

    def test_editor_prefills_from_latest_active_roster_changes(self):
        teams = [{"id": "joakim", "name": "Joakim"}]
        players = [
            {"id": f"p{index}", "name": f"Player {index}", "tier": index}
            for index in range(1, 9)
        ]
        links = [
            {"team_id": "joakim", "player_id": f"p{index}"}
            for index in range(1, 8)
        ]
        active_changes = [
            {
                "team_id": "joakim",
                "old_player_id": "p3",
                "new_player_id": "p8",
                "round_from": 3,
            }
        ]

        defaults = build_roster_editor_defaults(teams, players, links, active_changes)

        self.assertEqual(
            defaults.active_by_team["joakim"],
            ["p1", "p2", "p8", "p4", "p5", "p6", "p7"],
        )
        self.assertEqual(defaults.original_by_team["joakim"], [f"p{i}" for i in range(1, 8)])

    def test_missing_player_id_is_an_error_without_first_player_fallback(self):
        teams = [{"id": "joakim", "name": "Joakim"}]
        players = [
            {"id": f"p{index}", "name": f"Player {index}", "tier": index}
            for index in range(1, 9)
        ]
        links = [
            {"team_id": "joakim", "player_id": f"p{index}"}
            for index in range(2, 8)
        ]

        defaults = build_roster_editor_defaults(teams, players, links, [])

        self.assertFalse(defaults.is_valid)
        self.assertIn("joakim", defaults.errors_by_team)
        self.assertIn("Fant 6 av 7", defaults.errors_by_team["joakim"][0])
        self.assertNotIn("p1", defaults.active_by_team["joakim"])

    def test_admin_editor_uses_player_ids_and_never_name_keys(self):
        self.assertIn('editor_prefix = f"roster_editor_v2_', self.app_source)
        self.assertIn('options=roster_changes.build_roster_slot_options(', self.app_source)
        self.assertNotIn("player_id_by_name", self.app_source)

    def test_change_pool_contains_exactly_the_eleven_allowed_unique_players(self):
        names = list(ROSTER_CHANGE_POOL_NAMES)
        players = [
            {"id": f"p{index}", "name": name, "tier": 1}
            for index, name in enumerate(names, start=1)
        ]

        pool = build_roster_change_pool(players)

        self.assertTrue(pool.is_valid)
        self.assertEqual(len(pool.player_ids), 11)
        self.assertEqual(len(set(pool.player_ids)), 11)
        self.assertIn("Patrick Cantlay", names)
        self.assertNotIn("Patrick Cantley", names)

    def test_current_player_is_prefilled_alongside_restricted_change_pool(self):
        options = build_roster_slot_options(
            "current",
            ["pool-1", "pool-2", "current"],
            "original",
        )
        self.assertEqual(options, ["current", "original", "pool-1", "pool-2"])

    def test_player_outside_current_roster_and_change_pool_is_rejected(self):
        validation = validate_roster_change_pool(
            {"team-1": ["p1", "p2", "p3", "p4", "p5", "p6", "not-allowed"]},
            {"team-1": ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]},
            {"pool-1", "pool-2"},
        )
        self.assertFalse(validation.is_valid)
        self.assertIn("utenfor tillatt byttepool", validation.errors[0])

    def test_atomic_save_rejects_player_outside_change_pool(self):
        client = FakeRpcClient()
        current = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["not-allowed", *current["team-1"][1:]]}

        with self.assertRaisesRegex(ValueError, "utenfor tillatt byttepool"):
            save_roster_changes(
                client,
                "tournament-1",
                current,
                selected,
                {*current["team-1"], "not-allowed", "pool-1"},
                window_is_open=True,
                current_by_team=current,
                pool_player_ids={"pool-1"},
            )
        self.assertEqual(client.calls, [])

    def test_missing_change_pool_player_blocks_editor(self):
        players = [
            {"id": f"p{index}", "name": name, "tier": 1}
            for index, name in enumerate(ROSTER_CHANGE_POOL_NAMES[:-1], start=1)
        ]
        pool = build_roster_change_pool(players)
        self.assertFalse(pool.is_valid)
        self.assertIn("Sepp Straka", pool.errors[0])

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
            window_is_open=True,
        )
        self.assertEqual(len(client.calls), 1)
        name, params = client.calls[0]
        self.assertEqual(name, "save_roster_changes_atomic")
        self.assertEqual(len(params["p_changes"]), 2)

    def test_closed_manual_window_prevents_save(self):
        client = FakeRpcClient()
        original = {"team-1": [f"p{index}" for index in range(1, 8)]}
        selected = {"team-1": ["p8", "p2", "p3", "p4", "p5", "p6", "p7"]}
        with self.assertRaisesRegex(ValueError, "Byttevinduet er stengt"):
            save_roster_changes(
                client,
                "tournament-1",
                original,
                selected,
                {f"p{index}" for index in range(1, 9)},
                window_is_open=False,
            )
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
