"""Tests for DataGolf's documented surname-first player names."""

from __future__ import annotations

import sys
import types
import unittest


# Keep this unit test independent of installed Streamlit/Supabase packages.
streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: None
sys.modules.setdefault("supabase", supabase_stub)

from lib.datagolf_sync import (  # noqa: E402
    build_player_lookup,
    match_database_player,
    normalize_name,
    run_name_matching_test,
)


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

    def test_does_not_guess_a_different_player(self):
        self.assertIsNone(match_database_player("Rahm, Jon", self.lookup))

    def test_cli_name_matching_check_uses_datagolf_format(self):
        self.assertTrue(run_name_matching_test()["passed"])


if __name__ == "__main__":
    unittest.main()
