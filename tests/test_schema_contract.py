from pathlib import Path
import re
import unittest


class SchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (Path(__file__).parents[1] / "schema.sql").read_text(encoding="utf-8")
        cls.atomic_roster_migration = (
            Path(__file__).parents[1]
            / "migrations"
            / "006_atomic_roster_change_window.sql"
        ).read_text(encoding="utf-8")

    def test_schema_creates_exact_expected_tables(self):
        tables = set(re.findall(r"create table\s+([a-z_]+)", self.sql, flags=re.IGNORECASE))
        self.assertEqual(
            tables,
            {
                "tournaments",
                "teams",
                "players",
                "team_players",
                "roster_change_sets",
                "roster_changes",
                "scores",
                "player_status_events",
                "live_player_states",
                "live_feed_events",
                "tournament_rounds",
                "admin_audit_log",
            },
        )

    def test_schema_seeds_the_open_active_with_default_penalty(self):
        self.assertIn("'The Open 2026'", self.sql)
        self.assertIn("'The Open Championship'", self.sql)
        self.assertIn("'Royal Birkdale'", self.sql)
        self.assertIn("missing_score_penalty", self.sql)
        self.assertRegex(self.sql, r"(?s)'The Open 2026'.*?2026.*?true")

    def test_public_roles_are_read_only_and_audit_is_private(self):
        self.assertIn("grant select on tournaments", self.sql.lower())
        self.assertIn("public_read_live_player_states", self.sql.lower())
        self.assertIn("public_read_roster_changes", self.sql.lower())
        self.assertIn("revoke insert, update, delete", self.sql.lower())
        self.assertIn("revoke all on admin_audit_log", self.sql.lower())

    def test_roster_changes_are_round_three_only_and_preserve_original_roster(self):
        self.assertRegex(self.sql, r"round_from\s+int\s+not null\s+default 3")
        self.assertIn("check (round_from = 3)", self.sql)
        self.assertIn("old_player_id", self.sql)
        self.assertIn("new_player_id", self.sql)
        self.assertNotRegex(
            self.sql.lower(),
            r"(?s)create table roster_changes.*?delete from team_players",
        )

    def test_roster_changes_use_one_service_role_only_database_transaction(self):
        sql = self.atomic_roster_migration.lower()
        self.assertIn("create or replace function save_roster_changes_atomic", sql)
        self.assertIn("security definer", sql)
        self.assertIn("having count(*) > 3", sql)
        self.assertIn("round = 3", sql)
        self.assertIn("update roster_change_sets", sql)
        self.assertIn("insert into roster_changes", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)


if __name__ == "__main__":
    unittest.main()
