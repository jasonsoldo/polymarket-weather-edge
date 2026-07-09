import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.monitor import build_live_snapshot, run_live_monitor_loop
from weather_edge.weather_sources import WeatherSnapshot


class MonitorLoopTests(unittest.TestCase):
    def test_monitor_snapshot_marks_no_trade_when_weather_confidence_is_bad(self):
        weather = WeatherSnapshot(
            city="New York",
            latitude=40.7128,
            longitude=-74.006,
            target_date="2026-07-10",
            forecasts=(),
            disagreement=3.9,
            confidence=0.65,
        )

        with patch("weather_edge.monitor.fetch_weather_markets", return_value=[]), patch(
            "weather_edge.monitor.fetch_weather_snapshot", return_value=weather
        ):
            snapshot = build_live_snapshot("New York", 40.7128, -74.006, "2026-07-10")

        self.assertEqual(snapshot["recommended_action"], "NO_TRADE")
        self.assertEqual(snapshot["blocked_by"], "data_disagreement")
        self.assertIn("weather data disagreement too high", snapshot["risk_reasons"])
        self.assertIn("confidence below min_confidence", snapshot["risk_reasons"])
        self.assertEqual(snapshot["threshold"]["max_allowed_weather_disagreement"], 2.0)

    def test_monitor_loop_writes_jsonl_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "live_monitor.jsonl"
            snapshot = {
                "observed_at": "2026-07-09T00:00:00+00:00",
                "city": "New York",
                "target_date": "2026-07-10",
                "markets_found": 0,
                "markets": [],
                "weather": {},
                "notes": ["read_only_snapshot"],
            }

            with patch("weather_edge.monitor.build_live_snapshot", return_value=snapshot), patch("weather_edge.monitor.time.sleep"):
                runs = run_live_monitor_loop(
                    "New York",
                    40.7128,
                    -74.0060,
                    "2026-07-10",
                    str(output),
                    interval_seconds=1,
                    max_runs=2,
                )

            self.assertEqual(runs, 2)
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["city"], "New York")

    def test_monitor_loop_rejects_zero_interval(self):
        with self.assertRaisesRegex(ValueError, "interval_seconds"):
            run_live_monitor_loop("New York", 40.7, -74.0, "2026-07-10", "unused.jsonl", interval_seconds=0, max_runs=1)
