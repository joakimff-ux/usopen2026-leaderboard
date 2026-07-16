from pathlib import Path
import re
import unittest


class SchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (Path(__file__).parents[1] / "schema.sql").read_text(encoding="utf-8")

    def test_schema_creates_exact_expected_tables(self):
        tables = set(re.findall(r"create table\s+([a-z_]+)", self.sql, flags=re.IGNORECASE))
        self.assertEqual(
            tables,
            {
                "tournaments",
                "teams",
                "players",
                "team_players",
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
        self.assertIn("revoke insert, update, delete", self.sql.lower())
        self.assertIn("revoke all on admin_audit_log", self.sql.lower())


if __name__ == "__main__":
    unittest.main()
