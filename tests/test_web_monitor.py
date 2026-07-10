import tempfile
import unittest
from pathlib import Path

from weather_edge.web_monitor import read_recent_snapshots, render_dashboard


class WebMonitorTests(unittest.TestCase):
    def test_read_recent_snapshots_reads_jsonl_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live_monitor.jsonl"
            path.write_text(
                '{"observed_at":"one","recommended_action":"WATCH"}\n'
                '{"observed_at":"two","recommended_action":"NO_TRADE"}\n',
                encoding="utf-8",
            )

            snapshots = read_recent_snapshots(str(path), limit=1)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["observed_at"], "two")
        self.assertEqual(snapshots[0]["recommended_action"], "NO_TRADE")

    def test_render_dashboard_shows_weather_risk_and_market_status(self):
        snapshot = {
            "city": "New York",
            "target_date": "2026-07-10",
            "recommended_action": "NO_TRADE",
            "blocked_by": "data_disagreement",
            "risk_reasons": ["NO_TRADE", "weather data disagreement too high"],
            "weather": {"disagreement": 3.9, "confidence": 0.65},
            "markets_found": 0,
            "markets": [],
        }

        html = render_dashboard(snapshot, [snapshot])

        self.assertIn("WeatherEdge Monitor", html)
        self.assertIn("NO_TRADE", html)
        self.assertIn("data_disagreement", html)
        self.assertIn("No strict city temperature markets found", html)

    def test_render_dashboard_shows_all_cities_table(self):
        snapshot = {
            "mode": "all_cities",
            "target_date": "2026-07-10",
            "recommended_action": "NO_TRADE",
            "cities_monitored": 2,
            "markets_found": 0,
            "strict_markets_found": 0,
            "strict_markets": [],
            "cities": [
                {
                    "city": "New York",
                    "recommended_action": "NO_TRADE",
                    "markets_found": 0,
                    "weather": {"disagreement": 3.9, "confidence": 0.65},
                    "risk_reasons": ["NO_TRADE"],
                },
                {
                    "city": "Chicago",
                    "recommended_action": "NO_MARKET",
                    "markets_found": 0,
                    "weather": {"disagreement": 0.5, "confidence": 0.9},
                    "risk_reasons": ["no strict city temperature markets found"],
                },
            ],
        }

        html = render_dashboard(snapshot, [snapshot])

        self.assertIn("WeatherEdge All Cities Monitor", html)
        self.assertIn("New York", html)
        self.assertIn("Chicago", html)
        self.assertIn("Global Strict Temperature Markets", html)


if __name__ == "__main__":
    unittest.main()
