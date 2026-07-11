import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.accounting import apply_fill, realized_pnl
from weather_edge.historical_validation import validate_history
from weather_edge.official_sources import fetch_configured_official
from weather_edge.position_manager import Position, load_positions, upsert_position
from weather_edge.settlement_backfill import backfill_resolutions


class OfficialSourcesAndAccountingTests(unittest.TestCase):
    def test_configured_source_rejects_wrong_date(self):
        with patch("weather_edge.official_sources.get_json", return_value={"date": "2026-07-11", "daily_high": 34, "daily_low": 29}):
            result = fetch_configured_official("JMA", "RJTT", "2026-07-12", "C", "https://example.test", "key")
        self.assertEqual(result.status, "source_mismatch")

    def test_history_requires_minimum_days_and_exact_matches(self):
        rows = [{"api_high": 30, "page_high": 30, "api_low": 20, "page_low": 20} for _ in range(30)]
        result = validate_history(rows)
        self.assertTrue(result.verified)
        self.assertEqual(result.exact_match_rate, 1.0)

    def test_fill_ledger_records_realized_sell_pnl_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders = str(Path(tmp) / "orders.sqlite")
            positions = str(Path(tmp) / "positions.sqlite")
            upsert_position(positions, Position("m", "t", "28C", 2, 0.40))
            self.assertAlmostEqual(apply_fill(orders, positions, "fill-1", "exchange-1", "client-1", "m", "t", "28C", "SELL", 0.70, 1), 0.30)
            self.assertEqual(load_positions(positions)[0].shares, 1)
            self.assertEqual(apply_fill(orders, positions, "fill-1", "exchange-1", "client-1", "m", "t", "28C", "SELL", 0.70, 1), 0.0)
            self.assertAlmostEqual(realized_pnl(orders), 0.30)

    def test_resolution_backfill_preserves_raw_market_and_adds_final_bucket(self):
        rows = backfill_resolutions([{"condition_id": "c1", "question": "weather"}], [{"condition_id": "c1", "resolved_bucket": "28C", "resolved_at": "2026-07-13"}])
        self.assertEqual(rows[0]["question"], "weather")
        self.assertEqual(rows[0]["resolved_bucket"], "28C")
        self.assertTrue(rows[0]["resolution_backfilled"])


if __name__ == "__main__":
    unittest.main()
