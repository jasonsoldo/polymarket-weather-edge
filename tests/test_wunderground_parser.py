import unittest

from weather_edge.settlement_sources.wunderground import parse_wunderground_payload
from weather_edge.settlement_sources.wunderground_browser import _history_url, parse_wunderground_html


class WundergroundParserTests(unittest.TestCase):
    def test_parses_api_daily_summary(self):
        result = parse_wunderground_payload(
            {"station": "ZBAA", "date": "2026-07-10", "daily_high": 31.2, "daily_low": 22.4, "unit": "C"},
            "ZBAA", "2026-07-10", "C",
        )
        self.assertEqual((result.daily_high, result.daily_low, result.unit), (31.2, 22.4, "C"))

    def test_parses_rendered_summary_and_rejects_missing_data(self):
        html = "<main><h2>Daily Observations</h2><span>High 86 °F</span><span>Low 71 °F</span></main>"
        result = parse_wunderground_html(html, "ZBAA", "2026-07-10", "F")
        self.assertEqual((result.daily_high, result.daily_low), (86.0, 71.0))
        missing = parse_wunderground_html("<main>Daily Observations</main>", "ZBAA", "2026-07-10", "F")
        self.assertEqual(missing.status, "wu_unavailable")

    def test_converts_display_unit_to_requested_unit(self):
        result = parse_wunderground_html("<span>High 30 °C</span><span>Low 20 °C</span>", "ZBAA", "2026-07-10", "F")
        self.assertEqual(result.status, "wu_browser_supported")
        self.assertAlmostEqual(result.daily_high, 86.0)

    def test_does_not_treat_unrelated_numbers_as_low_temperature(self):
        result = parse_wunderground_html("<span>High 86 °F</span><span>Low 70 °F</span><span>Humidity 16%</span>", "EGLC", "2026-07-01", "C")
        self.assertAlmostEqual(result.daily_low, (70 - 32) * 5 / 9)

    def test_parses_only_summary_high_and_low(self):
        html = '<div class="summary-title">Summary</div><div>Temperature (°F) High Temp 84 74 -- Low Temp 70 57 --</div><div class="observation-title">Daily Observations</div><div>High 96 °F Low 40 °F</div>'
        result = parse_wunderground_html(html, "EGLC", "2026-06-11", "C")
        self.assertAlmostEqual(result.daily_high, (84 - 32) * 5 / 9)
        self.assertAlmostEqual(result.daily_low, (70 - 32) * 5 / 9)

    def test_rejects_wrong_selected_date(self):
        html = '<option selected="selected">January</option><option selected="selected">1</option><option selected="selected">2026</option><div>High 84 °F Low 70 °F</div>'
        result = parse_wunderground_html(html, "EGLC", "2026-06-11", "C")
        self.assertEqual(result.status, "wu_source_mismatch")

    def test_builds_wunderground_history_path(self):
        self.assertEqual(_history_url("https://www.wunderground.com/history/daily/gb/london/EGLC?date=2026-06-11", "2026-06-12"), "https://www.wunderground.com/history/daily/gb/london/EGLC/date/2026-6-12")


if __name__ == "__main__":
    unittest.main()
