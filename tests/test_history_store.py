import tempfile
import unittest
from pathlib import Path

from weather_edge.history_store import save_monitor_snapshot, snapshot_count


class HistoryStoreTests(unittest.TestCase):
    def test_saves_monitor_snapshot_for_future_backtests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "history.sqlite")
            save_monitor_snapshot(path, {"observed_at": "2026-07-10T00:00:00Z", "city": "London", "target_date": "2026-07-10", "markets": []})
            self.assertEqual(snapshot_count(path), 1)
