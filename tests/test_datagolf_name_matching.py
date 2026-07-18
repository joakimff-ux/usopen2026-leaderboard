"""Tests for DataGolf's documented surname-first player names."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


# Keep this unit test independent of installed Streamlit/Supabase packages.
streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: None
sys.modules.setdefault("supabase", supabase_stub)

from lib import datagolf_sync  # noqa: E402
from lib.datagolf_sync import (  # noqa: E402
    PLAYER_NAME_ALIASES,
    build_exact_player_lookup,
    build_player_id_lookup,
    build_player_lookup,
    match_database_player,
    normalize_name,
    run_name_matching_test,
)
from lib.roster_changes import ROSTER_CHANGE_POOL_NAMES  # noqa: E402


class DataGolfNameMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = [
            {"id": "1", "name": "Scottie Scheffler", "tier": 1},
            {"id": "2", "name": "Si Woo Kim", "tier": 3},
            {"id": "3", "name": "Ludvig Aberg", "tier": 2},
            {"id": "4", "name": "Nicolai Hojgaard", "tier": 6},
        ]
        self.lookup = build_player_lookup(self.players)

    def test_matches_documented_last_first_format(self):
        self.assertEqual(
            match_database_player("Scheffler, Scottie", self.lookup),
            self.players[0],
        )

    def test_matches_hyphenated_given_name(self):
        self.assertEqual(
            match_database_player("Kim, Si-Woo", self.lookup),
            self.players[1],
        )

    def test_matches_diacritics_without_fuzzy_matching(self):
        self.assertEqual(
            match_database_player("Åberg, Ludvig", self.lookup),
            self.players[2],
        )
        self.assertEqual(
            match_database_player("Højgaard, Nicolai", self.lookup),
            self.players[3],
        )

    def test_preserves_support_for_local_first_last_format(self):
        self.assertEqual(normalize_name(" Scottie   Scheffler "), "scottie scheffler")

    def test_normalizes_norwegian_letters_accents_periods_case_and_spacing(self):
        self.assertEqual(
            normalize_name("  HÅKON.  SÆTHER  THORBJØRNSEN  "),
            "hakon saether thorbjornsen",
        )
        self.assertEqual(normalize_name("José María"), "jose maria")

    def test_exact_name_takes_priority_over_normalized_name(self):
        norwegian = {"id": "no", "name": "Michael Thorbjørnsen", "tier": 2}
        ascii_name = {"id": "ascii", "name": "Michael Thorbjornsen", "tier": 2}
        players = [norwegian, ascii_name]
        self.assertEqual(
            match_database_player(
                "Michael Thorbjørnsen",
                build_player_lookup(players),
                exact_player_lookup=build_exact_player_lookup(players),
            ),
            norwegian,
        )

    def test_normalized_name_takes_priority_over_alias(self):
        player = {"id": "michael", "name": "Michael Thorbjørnsen", "tier": 2}
        with patch.object(datagolf_sync.logger, "warning") as warning:
            matched = match_database_player(
                "  MICHAEL THORBJORNsen. ",
                build_player_lookup([player]),
                exact_player_lookup=build_exact_player_lookup([player]),
            )
        self.assertEqual(matched, player)
        warning.assert_not_called()

    def test_thorbjornsen_and_cam_aliases_are_registered(self):
        self.assertEqual(
            PLAYER_NAME_ALIASES["Michael Thorbjørnsen"],
            "Michael Thorbjornsen",
        )
        self.assertEqual(
            PLAYER_NAME_ALIASES["Micheal Thorbjornsen"],
            "Michael Thorbjornsen",
        )
        self.assertEqual(PLAYER_NAME_ALIASES["Cam Smith"], "Cameron Smith")

    def test_does_not_guess_a_different_player(self):
        self.assertIsNone(match_database_player("Rahm, Jon", self.lookup))

    def test_required_aliases_match_only_after_direct_name_fails(self):
        alias_players = [
            {"id": str(index), "name": local_name, "tier": index}
            for index, local_name in enumerate(PLAYER_NAME_ALIASES, start=1)
        ]
        lookup = build_player_lookup(alias_players)
        for datagolf_name in set(PLAYER_NAME_ALIASES.values()):
            with self.subTest(datagolf_name=datagolf_name):
                matched = match_database_player(datagolf_name, lookup)
                valid_local_names = {
                    local_name
                    for local_name, canonical_name in PLAYER_NAME_ALIASES.items()
                    if canonical_name == datagolf_name
                }
                self.assertIsNotNone(matched)
                self.assertIn(matched["name"], valid_local_names)

    def test_alias_use_is_logged(self):
        player = {"id": "cam", "name": "Cam Smith", "tier": 2}
        with patch.object(datagolf_sync.logger, "warning") as warning:
            self.assertEqual(
                match_database_player("Cameron Smith", build_player_lookup([player])),
                player,
            )
        warning.assert_called_once_with(
            "Matched alias: %s -> %s",
            "Cam Smith",
            "Cameron Smith",
        )

    def test_direct_name_match_takes_priority_over_alias(self):
        local_alias = {"id": "cam", "name": "Cam Smith", "tier": 2}
        direct = {"id": "cameron", "name": "Cameron Smith", "tier": 2}
        with patch.object(datagolf_sync.logger, "warning") as warning:
            matched = match_database_player(
                "Cameron Smith",
                build_player_lookup([local_alias, direct]),
            )
        self.assertEqual(matched, direct)
        warning.assert_not_called()

    def test_all_roster_change_pool_names_match_datagolf_directly(self):
        players = [
            {"id": f"pool-{index}", "name": name, "tier": 1}
            for index, name in enumerate(ROSTER_CHANGE_POOL_NAMES, start=1)
        ]
        exact_lookup = build_exact_player_lookup(players)
        normalized_lookup = build_player_lookup(players)

        for player in players:
            with self.subTest(name=player["name"]):
                matched = match_database_player(
                    player["name"],
                    normalized_lookup,
                    exact_player_lookup=exact_lookup,
                )
                self.assertEqual(matched, player)

    def test_datagolf_id_takes_priority_when_available(self):
        id_match = {
            "id": "cam",
            "name": "Cam Smith",
            "tier": 2,
            "datagolf_id": 123,
        }
        name_match = {"id": "scottie", "name": "Scottie Scheffler", "tier": 1}
        players = [id_match, name_match]
        self.assertEqual(
            match_database_player(
                "Scottie Scheffler",
                build_player_lookup(players),
                datagolf_id="123",
                player_id_lookup=build_player_id_lookup(players),
            ),
            id_match,
        )

    def test_cli_name_matching_check_uses_datagolf_format(self):
        self.assertTrue(run_name_matching_test()["passed"])


if __name__ == "__main__":
    unittest.main()
