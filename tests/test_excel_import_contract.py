from pathlib import Path
import unittest

from lib.excel_import import parse_workbook


class ExcelImportContractTests(unittest.TestCase):
    def test_the_open_workbook_matches_import_schema(self):
        workbook = Path(__file__).parents[1] / "data" / "The Open 2026 - Resultater.xlsx"
        parsed = parse_workbook(workbook)

        self.assertEqual(len(parsed.teams), 9)
        self.assertEqual(len(parsed.players), 44)
        self.assertEqual(set(parsed.team_roster_counts.values()), {7})
        self.assertEqual(sum(parsed.team_roster_counts.values()), 63)
        self.assertEqual(sum(len(player.scores) for player in parsed.players), 0)


if __name__ == "__main__":
    unittest.main()
