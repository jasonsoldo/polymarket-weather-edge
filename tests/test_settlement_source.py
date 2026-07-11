import unittest
import os
from unittest.mock import patch

from weather_edge.settlement_rules import SettlementRule
from weather_edge.settlement_source import fetch_settlement_observation, settlement_source_capability


class SettlementSourceTests(unittest.TestCase):
    def test_configured_cwa_official_adapter_reads_extremes(self):
        rule = _rule("CWA", "RCSS", "2020-07-10")
        old = {name: os.environ.get(name) for name in ("CWA_API_KEY", "CWA_SETTLEMENT_URL")}
        os.environ["CWA_API_KEY"] = "test-key"
        os.environ["CWA_SETTLEMENT_URL"] = "https://cwa.test/settlement"
        try:
            with patch("weather_edge.settlement_source.get_json", return_value={"data": [{"max_temp": 34.2, "min_temp": 26.1, "date": "2020-07-10"}]}):
                result = fetch_settlement_observation(rule)
            self.assertEqual(result.status, "available")
            self.assertEqual(result.max_temp, 34.2)
            self.assertEqual(settlement_source_capability(rule), "supported_official")
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_nws_requires_data_from_all_requested_stations(self):
        rule = _rule("NWS", "KNYC,KLGA", "2020-07-10")
        payload = {"features": [{"properties": {"temperature": {"value": 30}, "timestamp": "2020-07-10T12:00:00Z"}}]}
        with patch("weather_edge.settlement_source.get_json", side_effect=[payload, payload]):
            result = fetch_settlement_observation(rule)
        self.assertEqual(result.status, "available")
        self.assertEqual(result.max_temp, 30.0)
        self.assertEqual(result.station, "KNYC,KLGA")
    def test_wunderground_requires_adapter_before_verification(self):
        rule = _rule("Wunderground", "EGLC", "2020-07-10")

        result = fetch_settlement_observation(rule)

        self.assertEqual(settlement_source_capability(rule), "pending_wu_adapter")
        self.assertEqual(result.status, "pending_wu_adapter")

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
