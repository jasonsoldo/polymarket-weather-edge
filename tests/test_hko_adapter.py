import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from weather_edge.settlement_sources.hko import fetch_hko_realtime


CURRENT_CSV = """Date time,Automatic Weather Station,Air Temperature(degree Celsius)\n202607111910,HK Observatory,31.4\n202607111910,King's Park,30.7\n"""
EXTREMES_CSV = """Date time,Automatic Weather Station,Maximum Air Temperature Since Midnight (degree Celsius),Minimum Air Temperature Since Midnight (degree Celsius)\n202607111910,HK Observatory,33.8,27.1\n202607111910,King's Park,34.0,27.5\n"""


class HkoAdapterTests(unittest.TestCase):
    def test_reads_hko_current_and_since_midnight_values(self):
        now = datetime(2026, 7, 11, 19, 20, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        with patch("weather_edge.settlement_sources.hko.get_text", side_effect=[CURRENT_CSV, EXTREMES_CSV]):
            result = fetch_hko_realtime("2026-07-11", now=now)

        self.assertEqual(result.current_temp, 31.4)
        self.assertEqual(result.max_temp_since_midnight, 33.8)
        self.assertEqual(result.min_temp_since_midnight, 27.1)
        self.assertEqual(result.station, "Hong Kong Observatory")
        self.assertEqual(result.station_id, "HKO")
        self.assertEqual(result.data_type, "real_time_observation")
        self.assertFalse(result.is_final)
        self.assertTrue(result.healthy)
        self.assertTrue(all(result.health.values()))

    def test_wrong_target_date_is_unhealthy(self):
        now = datetime(2026, 7, 11, 19, 20, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        with patch("weather_edge.settlement_sources.hko.get_text", side_effect=[CURRENT_CSV, EXTREMES_CSV]):
            result = fetch_hko_realtime("2026-07-10", now=now)

        self.assertFalse(result.healthy)
        self.assertFalse(result.health["target_date_match"])
        self.assertEqual(result.block_reason, "hko_adapter_unhealthy")

    def test_stale_timestamp_is_unhealthy(self):
        now = datetime(2026, 7, 11, 20, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        with patch("weather_edge.settlement_sources.hko.get_text", side_effect=[CURRENT_CSV, EXTREMES_CSV]):
            result = fetch_hko_realtime("2026-07-11", now=now)

        self.assertFalse(result.health["timestamp_fresh"])
        self.assertFalse(result.healthy)

    def test_missing_hko_station_is_unhealthy(self):
        current = CURRENT_CSV.replace("HK Observatory", "Happy Valley")
        extremes = EXTREMES_CSV.replace("HK Observatory", "Happy Valley")
        now = datetime(2026, 7, 11, 19, 20, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        with patch("weather_edge.settlement_sources.hko.get_text", side_effect=[current, extremes]):
            result = fetch_hko_realtime("2026-07-11", now=now)

        self.assertFalse(result.health["station_match"])
        self.assertFalse(result.health["required_fields_present"])
        self.assertFalse(result.healthy)


if __name__ == "__main__":
    unittest.main()
