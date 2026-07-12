import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from weather_edge.history_store import save_monitor_snapshot
from weather_edge.nws_finalizer import finalize_nws_day, nws_closure_status
from weather_edge.settlement_source import SettlementSourceResult


class NwsFinalizerTests(unittest.TestCase):
    def test_reconciles_market_and_shadow_pnl(self):
        observation = SettlementSourceResult("available", "NWS", "KLGA", "2026-07-10", 85.0, 70.0, "F", "2026-07-11T03:50:00Z", "official NWS observations")
        market = {"id": "market-85", "question": "Will the highest temperature in New York be 85°F on July 10?", "outcomes": ["Yes", "No"], "outcomePrices": [1, 0]}
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            save_monitor_snapshot(history_db, {"observed_at": "2026-07-10T18:00:00Z", "city": "New York", "target_date": "2026-07-10", "weather": {"confidence": 0.9, "disagreement": 1.0}, "markets": [{"event_id": "event-ny", "event_slug": "highest-temperature-in-new-york-on-july-10-2026", "markets": [{"market_id": "market-85", "question": market["question"]}], "event_bucket_plan": {"settlement_rule": {"market_type": "max_temp", "settlement_source": "NWS"}, "decision": {"recommended_action": "block_new_position", "reasons": ["shadow_only"]}, "simulation_candidate": {"orders": [{"market_id": "market-85", "price": 0.4, "size": 2.0}], "curve": {"best_case_pnl": 1.2, "worst_case_pnl": -0.8}}}}]})
            with patch("weather_edge.nws_finalizer.fetch_settlement_observation", return_value=observation), patch("weather_edge.nws_finalizer.closed_new_york_markets", return_value=[{"event": {}, "market": market}]):
                result = finalize_nws_day("2026-07-10", history_db)
            with closing(sqlite3.connect(history_db)) as conn:
                shadow = conn.execute("SELECT final_market_result, hypothetical_realized_pnl, finalized_at FROM shadow_decisions").fetchone()
                resolution = conn.execute("SELECT expected_outcome, resolved_outcome, settlement_match FROM nws_market_resolutions").fetchone()
        self.assertEqual(result["settlement_matches"], 1)
        self.assertEqual(resolution, ("Yes", "Yes", 1))
        self.assertAlmostEqual(shadow[1], 1.2)
        self.assertTrue(shadow[2])

    def test_station_requires_thirty_matching_days_and_explicit_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_db = str(Path(tmp) / "history.sqlite")
            from weather_edge.nws_finalizer import SCHEMA
            with closing(sqlite3.connect(history_db)) as conn:
                conn.executescript(SCHEMA)
                for day in range(1, 31):
                    conn.execute("INSERT INTO nws_market_resolutions VALUES (?, 'KLGA', ?, 'question', 80, 'Yes', 'Yes', 1, 'now', '{}')", (f"2026-06-{day:02d}", f"m-{day}"))
                conn.commit()
            with patch.dict("os.environ", {"NWS_SETTLEMENT_VERIFIED_STATIONS": "KLGA"}):
                status = nws_closure_status(history_db)
        self.assertTrue(status["station_verified"])
        self.assertTrue(status["settlement_verified"])
        self.assertEqual(status["match_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
