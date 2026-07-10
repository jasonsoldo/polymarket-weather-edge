import unittest

from weather_edge.settlement_sources.wunderground import parse_wunderground_payload
from weather_edge.settlement_sources.wunderground_browser import parse_wunderground_html


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


if __name__ == "__main__":
    unittest.main()
