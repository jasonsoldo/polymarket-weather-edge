import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.nws_history import collect_nws_history
from weather_edge.settlement_source import SettlementSourceResult


class NwsHistoryTests(unittest.TestCase):
    def test_collects_new_york_history_with_explicit_station_and_timezone(self):
        result = SettlementSourceResult("available", "NWS", "KLGA", "2020-07-10", 77.0, 68.0, "F", "2020-07-11T03:50:00Z", "official NWS observations")
        with tempfile.TemporaryDirectory() as directory, patch("weather_edge.nws_history.fetch_settlement_observation", return_value=result) as fetch:
            output = str(Path(directory) / "nws.jsonl")
            summary = collect_nws_history("2020-07-10", "2020-07-10", output)

            rule = fetch.call_args.args[0]
            self.assertEqual(rule.city, "New York")
            self.assertEqual(rule.target_station_or_data_source, "KLGA")
            self.assertEqual(rule.timezone, "America/New_York")
            self.assertEqual(rule.measurement_unit, "F")
            self.assertEqual(summary["collected"], 1)
            self.assertIn('"api_high": 77.0', Path(output).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
