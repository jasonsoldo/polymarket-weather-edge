import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.monitor import run_live_monitor_loop


class MonitorLoopTests(unittest.TestCase):
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
