import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from weather_edge.accounting import realized_pnl
from weather_edge.hko_finalizer import _hko_day_complete, finalize_hko_day, finalize_hko_recent, hko_closure_status
from weather_edge.history_store import save_monitor_snapshot
from weather_edge.order_store import StoredOrder, save_order
from weather_edge.position_manager import Position, load_positions, upsert_position
from weather_edge.settlement_source import SettlementSourceResult


class HkoFinalizerTests(unittest.TestCase):
    def test_finalizes_dry_run_position_and_is_idempotent(self):
        observation = SettlementSourceResult("available", "Hong Kong Observatory", "HKO", "2026-07-10", 31.0, 26.0, "C", "2026-07-11", "official HKO open data")
        market = {
            "id": "market-31",
            "question": "Will the highest temperature in Hong Kong be 31°C on July 10?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "clobTokenIds": '["yes-token", "no-token"]',
        }
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            orders_db = str(Path(tmp) / "orders.sqlite")
            upsert_position(positions_db, Position("market-31", "yes-token", "31°C", 1.0, 0.4))
            save_order(orders_db, StoredOrder("dry-1", "market-31", "yes-token", "31°C", "BUY", 0.4, 1.0, "dry_run_filled", {}))

            save_monitor_snapshot(history_db, {
                "observed_at": "2026-07-10T00:00:00Z", "city": "Hong Kong", "target_date": "2026-07-10", "weather": {"confidence": 0.85, "disagreement": 0.5},
                "markets": [{"event_id": "event-1", "event_slug": "hk-high", "markets": [{"market_id": "market-31", "question": market["question"]}], "event_bucket_plan": {
                    "settlement_rule": {"market_type": "max_temp"}, "decision": {"recommended_action": "block_new_position", "reasons": ["shadow_only"]},
                    "orders": [], "curve": {"best_case_pnl": 0.6, "worst_case_pnl": -0.4},
                    "simulation_candidate": {"orders": [{"market_id": "market-31", "token_id": "yes-token", "bucket": "31C", "price": 0.4, "size": 1.0}], "curve": {"best_case_pnl": 0.6, "worst_case_pnl": -0.4}},
                }}],
            })
            with patch("weather_edge.hko_finalizer.fetch_settlement_observation", return_value=observation), patch(
                "weather_edge.hko_finalizer._closed_hko_markets", return_value=[{"event": {}, "market": market}]
            ):
                first = finalize_hko_day("2026-07-10", history_db, positions_db, orders_db)
                second = finalize_hko_day("2026-07-10", history_db, positions_db, orders_db)

            self.assertEqual(first["positions_settled"], 1)
            self.assertAlmostEqual(first["realized_pnl"], 0.6)
            self.assertEqual(second["positions_settled"], 0)
            self.assertEqual(load_positions(positions_db), [])
            self.assertAlmostEqual(realized_pnl(orders_db), 0.6)
            closure = hko_closure_status(history_db, orders_db)
            self.assertTrue(closure["settlement_audit_passed"])
            self.assertFalse(closure["settlement_verified"])
            self.assertEqual(closure["official_data_days"], 1)
            self.assertEqual(closure["audit_days"], 1)
            self.assertEqual(closure["final_daily_max"], 31.0)
            self.assertAlmostEqual(closure["shadow_realized_pnl"], 0.6)
            self.assertEqual((closure["shadow_samples"], closure["shadow_finalized"]), (1, 1))
            self.assertAlmostEqual(closure["shadow_hypothetical_pnl"], 0.6)
            self.assertEqual(closure["recent_shadow_reconciliations"][0]["final_temperature"], 31.0)
            self.assertAlmostEqual(closure["recent_shadow_reconciliations"][0]["hypothetical_realized_pnl"], 0.6)
            with closing(sqlite3.connect(history_db)) as conn:
                row = conn.execute("SELECT expected_outcome, resolved_outcome, settlement_match FROM hko_market_resolutions").fetchone()
            self.assertEqual(row, ("Yes", "Yes", 1))

    def test_closure_excludes_non_hong_kong_shadow_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            orders_db = str(Path(tmp) / "orders.sqlite")
            save_monitor_snapshot(history_db, {
                "observed_at": "2026-07-10T00:00:00Z", "city": "New York", "target_date": "2026-07-10", "weather": {},
                "markets": [{"event_id": "ny", "event_slug": "highest-temperature-in-new-york", "markets": [{"question": "Highest temperature in New York"}], "event_bucket_plan": {
                    "settlement_rule": {"market_type": "max_temp", "settlement_source": "NWS"}, "decision": {"recommended_action": "block_new_position", "reasons": []}, "orders": [], "curve": {}
                }}],
            })
            closure = hko_closure_status(history_db, orders_db)
        self.assertEqual(closure["shadow_samples"], 0)

    def test_does_not_settle_non_dry_run_position(self):
        observation = SettlementSourceResult("available", "Hong Kong Observatory", "HKO", "2026-07-10", 31.0, 26.0, "C", "2026-07-11", "official HKO open data")
        market = {"id": "market-31", "question": "Will the highest temperature in Hong Kong be 31°C on July 10?", "outcomes": ["Yes", "No"], "outcomePrices": [1, 0], "clobTokenIds": ["yes-token", "no-token"]}
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            orders_db = str(Path(tmp) / "orders.sqlite")
            upsert_position(positions_db, Position("market-31", "yes-token", "31°C", 1.0, 0.4))
            with patch("weather_edge.hko_finalizer.fetch_settlement_observation", return_value=observation), patch(
                "weather_edge.hko_finalizer._closed_hko_markets", return_value=[{"event": {}, "market": market}]
            ):
                result = finalize_hko_day("2026-07-10", history_db, positions_db, orders_db)
            self.assertEqual(result["positions_settled"], 0)
            self.assertEqual(len(load_positions(positions_db)), 1)

    def test_does_not_finalize_low_temperature_market(self):
        observation = SettlementSourceResult("available", "Hong Kong Observatory", "HKO", "2026-07-10", 31.0, 26.0, "C", "2026-07-11", "official HKO open data")
        market = {"id": "market-low", "question": "Will the lowest temperature in Hong Kong be 26°C on July 10?", "outcomes": ["Yes", "No"], "outcomePrices": [1, 0], "clobTokenIds": ["yes-token", "no-token"]}
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            orders_db = str(Path(tmp) / "orders.sqlite")
            upsert_position(positions_db, Position("market-low", "yes-token", "26°C", 1.0, 0.4))
            save_order(orders_db, StoredOrder("dry-low", "market-low", "yes-token", "26°C", "BUY", 0.4, 1.0, "dry_run_filled", {}))
            with patch("weather_edge.hko_finalizer.fetch_settlement_observation", return_value=observation), patch(
                "weather_edge.hko_finalizer._closed_hko_markets", return_value=[{"event": {}, "market": market}]
            ):
                result = finalize_hko_day("2026-07-10", history_db, positions_db, orders_db)
            self.assertEqual(result["markets_resolved"], 0)
            self.assertEqual(result["positions_settled"], 0)
            self.assertEqual(len(load_positions(positions_db)), 1)

    def test_recent_finalizer_retries_delayed_days(self):
        with patch("weather_edge.hko_finalizer.yesterday_hong_kong", return_value="2026-07-10"), patch(
            "weather_edge.hko_finalizer.finalize_hko_day",
            side_effect=lambda day, *_args: {"target_date": day, "status": "finalized" if day == "2026-07-09" else "unavailable", "markets_resolved": 1 if day == "2026-07-09" else 0, "positions_settled": 0, "realized_pnl": 0.0},
        ):
            result = finalize_hko_recent(3, "history.sqlite", "positions.sqlite", "orders.sqlite")
        self.assertEqual(result["available_days"], 1)
        self.assertEqual(result["pending_days"], 2)
        self.assertEqual([item["target_date"] for item in result["results"]], ["2026-07-10", "2026-07-09", "2026-07-08"])

    def test_recent_finalizer_prints_progress(self):
        output = StringIO()
        with patch("weather_edge.hko_finalizer.yesterday_hong_kong", return_value="2026-07-10"), patch(
            "weather_edge.hko_finalizer.finalize_hko_day", return_value={"status": "unavailable", "markets_resolved": 0, "positions_settled": 0, "realized_pnl": 0.0}
        ), redirect_stderr(output):
            finalize_hko_recent(1, "history.sqlite", "positions.sqlite", "orders.sqlite", progress=True)
        self.assertIn("[1/1] 2026-07-10 unavailable", output.getvalue())

    def test_hourly_retry_skips_completed_day_without_pending_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            with closing(sqlite3.connect(history_db)) as conn:
                conn.execute("CREATE TABLE hko_market_resolutions (target_date TEXT)")
                conn.execute("INSERT INTO hko_market_resolutions VALUES ('2026-07-10')")
                conn.execute("CREATE TABLE shadow_decisions (target_date TEXT, finalized_at TEXT, event_slug TEXT, question TEXT)")
                conn.commit()
            self.assertTrue(_hko_day_complete(history_db, "2026-07-10"))


if __name__ == "__main__":
    unittest.main()
