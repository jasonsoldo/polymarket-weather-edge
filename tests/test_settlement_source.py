import unittest
import os
from unittest.mock import patch

from weather_edge.settlement_rules import SettlementRule
from weather_edge.settlement_source import _hko_date_matches, _hko_row_matches, _nws_utc_day_window, fetch_settlement_observation, settlement_source_capability


class SettlementSourceTests(unittest.TestCase):
    def test_hko_history_accepts_full_and_short_date_formats(self):
        self.assertTrue(_hko_date_matches("2026-06-01", "2026-06-01"))
        self.assertTrue(_hko_date_matches("01/06", "2026-06-01"))
        self.assertTrue(_hko_date_matches("1", "2026-06-01"))
        self.assertFalse(_hko_date_matches("02", "2026-06-01"))

    def test_hko_history_accepts_year_month_day_columns(self):
        self.assertTrue(_hko_row_matches([2026, 6, 1, 32.1], ["year", "month", "day", "hko"], "2026-06-01"))
        self.assertTrue(_hko_row_matches([2026, 6, 1, 32.1], ["年/year", "月/month", "日/day", "數值/value"], "2026-06-01"))
        self.assertFalse(_hko_row_matches([2026, 6, 2, 32.1], ["year", "month", "day", "hko"], "2026-06-01"))

    def test_hko_history_retries_without_month_when_month_query_is_empty(self):
        empty = {"fields": ["年/year", "月/month", "日/day", "數值/value"], "data": []}
        yearly = {"fields": ["年/year", "月/month", "日/day", "數值/value"], "data": [[2026, 6, 1, 32.1]]}
        with patch("weather_edge.settlement_source.get_json", side_effect=[empty, yearly]):
            from weather_edge.settlement_source import _hko_daily_value
            self.assertEqual(_hko_daily_value("CLMMAXT", {"year": "2026", "month": "6"}, "2026-06-01"), 32.1)

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

        self.assertEqual(settlement_source_capability(rule), "pending_hko_settlement_validation")
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

    def test_nws_uses_market_local_calendar_day(self):
        start, end = _nws_utc_day_window("2020-07-10", "America/New_York")
        self.assertEqual(start, "2020-07-10T04:00:00+00:00")
        self.assertEqual(end, "2020-07-11T03:59:59.999999+00:00")

    def test_nws_converts_observations_to_market_unit(self):
        rule = SettlementRule("New York", "2020-07-10", "max_temp", "NWS", "F", "America/New_York", "KNYC", "nearest_integer", 1.0, (), ())
        payload = {"features": [
            {"properties": {"temperature": {"value": 20.0}, "timestamp": "2020-07-10T12:00:00Z"}},
            {"properties": {"temperature": {"value": 25.0}, "timestamp": "2020-07-10T18:00:00Z"}},
        ]}
        with patch("weather_edge.settlement_source.get_json", return_value=payload) as request:
            result = fetch_settlement_observation(rule)

        self.assertEqual(result.unit, "F")
        self.assertEqual(result.max_temp, 77.0)
        self.assertEqual(result.min_temp, 68.0)
        self.assertEqual(request.call_args.args[1]["start"], "2020-07-10T04:00:00+00:00")

    def test_nws_is_pending_until_station_validation(self):
        rule = SettlementRule("New York", "2020-07-10", "max_temp", "NWS", "F", "America/New_York", "KNYC", "nearest_integer", 1.0, (), ())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NWS_SETTLEMENT_VERIFIED_STATIONS", None)
            self.assertEqual(settlement_source_capability(rule), "pending_nws_settlement_validation")


def _rule(source, station, target_date):
    return SettlementRule("Test", target_date, "max_temp", source, "C", "UTC", station, "nearest_integer", 1.0, (), ())
