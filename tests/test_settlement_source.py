import unittest
from unittest.mock import patch

from weather_edge.settlement_rules import SettlementRule
from weather_edge.settlement_source import fetch_settlement_observation, settlement_source_capability


class SettlementSourceTests(unittest.TestCase):
    def test_wunderground_is_explicitly_unsupported(self):
        rule = _rule("Wunderground", "EGLC", "2020-07-10")

        result = fetch_settlement_observation(rule)

        self.assertEqual(settlement_source_capability(rule), "unsupported_no_official_api")
        self.assertEqual(result.status, "unsupported_no_official_api")

    def test_hko_reads_official_daily_max_and_min(self):
        rule = _rule("Hong Kong Observatory", "HKO", "2020-07-10")
        responses = [
            {"fields": ["Day", "HKO"], "data": [["10", "31.2"]]},
            {"fields": ["Day", "HKO"], "data": [["10", "26.1"]]},
        ]
        with patch("weather_edge.settlement_source.get_json", side_effect=responses):
            result = fetch_settlement_observation(rule)

        self.assertEqual(result.status, "available")
        self.assertAlmostEqual(result.max_temp, 31.2)
        self.assertAlmostEqual(result.min_temp, 26.1)

    def test_nws_reads_station_observations(self):
        rule = _rule("NWS", "KNYC", "2020-07-10")
        payload = {"features": [
            {"properties": {"temperature": {"value": 20.0}, "timestamp": "2020-07-10T12:00:00Z"}},
            {"properties": {"temperature": {"value": 25.0}, "timestamp": "2020-07-10T18:00:00Z"}},
        ]}
        with patch("weather_edge.settlement_source.get_json", return_value=payload):
            result = fetch_settlement_observation(rule)

        self.assertEqual(result.status, "available")
        self.assertEqual(result.max_temp, 25.0)
        self.assertEqual(result.min_temp, 20.0)


def _rule(source, station, target_date):
    return SettlementRule("Test", target_date, "max_temp", source, "C", "UTC", station, "nearest_integer", 1.0, (), ())
