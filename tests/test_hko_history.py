import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.hko_history import collect_hko_history, import_hko_history
from weather_edge.history_store import history_summary
from weather_edge.settlement_source import SettlementSourceResult


class HkoHistoryTests(unittest.TestCase):
    def test_collects_daily_hko_rows_without_fabricating_comparison_values(self):
        result = SettlementSourceResult("available", "Hong Kong Observatory", "HKO", "2026-06-01", 32.1, 27.0, "C", "2026-06-02T00:00:00+08:00", "official")
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "hko.jsonl")
            with patch("weather_edge.hko_history.fetch_settlement_observation", return_value=result):
                summary = collect_hko_history("2026-06-01", "2026-06-01", output, 0)
            self.assertEqual(summary["collected"], 1)
            row = Path(output).read_text(encoding="utf-8").strip()
            self.assertIn('"api_high": 32.1', row)
            self.assertNotIn('"page_high"', row)

    def test_imports_existing_history_rows_into_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hko.jsonl"
            db = str(Path(tmp) / "history.sqlite")
            source.write_text('{"date":"2025-06-01","api_high":31.2,"api_low":24.9,"unit":"C","status":"available","station":"HKO"}\n', encoding="utf-8")
            result = import_hko_history(str(source), db)
            counts = history_summary(db)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(counts["settlement_observations"], 1)


if __name__ == "__main__":
    unittest.main()
