import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from lib.time_display import format_oslo_time, to_oslo_datetime


class OsloTimeDisplayTests(unittest.TestCase):
    def test_summer_time_uses_utc_plus_two(self):
        timestamp = datetime(2026, 7, 16, 8, 57, tzinfo=timezone.utc)
        self.assertEqual(format_oslo_time(timestamp), "10:57")
        self.assertEqual(to_oslo_datetime(timestamp).utcoffset().total_seconds(), 7200)

    def test_winter_time_uses_utc_plus_one(self):
        timestamp = datetime(2026, 1, 16, 9, 57, tzinfo=timezone.utc)
        self.assertEqual(format_oslo_time(timestamp), "10:57")
        self.assertEqual(to_oslo_datetime(timestamp).utcoffset().total_seconds(), 3600)

    def test_timezone_aware_oslo_value_is_not_treated_as_utc(self):
        timestamp = datetime(2026, 7, 16, 10, 57, tzinfo=ZoneInfo("Europe/Oslo"))
        self.assertEqual(format_oslo_time(timestamp), "10:57")

    def test_naive_database_value_is_interpreted_as_utc(self):
        timestamp = datetime(2026, 7, 16, 8, 57)
        self.assertEqual(format_oslo_time(timestamp), "10:57")

    def test_iso_utc_timestamp_uses_the_same_conversion(self):
        self.assertEqual(format_oslo_time("2026-07-16T08:57:00Z"), "10:57")


if __name__ == "__main__":
    unittest.main()
