import unittest

from lib.datagolf_sync import extract_player_status


class DataGolfStatusDetectionTests(unittest.TestCase):
    def test_only_explicit_terminal_statuses_are_recognized(self):
        self.assertEqual(extract_player_status({"current_pos": "CUT"}), "CUT")
        self.assertEqual(extract_player_status({"status": "wd"}), "WD")
        self.assertEqual(extract_player_status({"position": " DQ "}), "DQ")

    def test_missing_normal_and_unknown_values_do_not_create_status(self):
        self.assertIsNone(extract_player_status({}))
        self.assertIsNone(extract_player_status({"current_pos": "T18"}))
        self.assertIsNone(extract_player_status({"status": ""}))


if __name__ == "__main__":
    unittest.main()
