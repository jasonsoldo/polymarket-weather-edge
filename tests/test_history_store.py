import tempfile
import unittest
from pathlib import Path

from weather_edge.history_store import calibration_summary, history_summary, save_monitor_snapshot, save_settlement_observation, snapshot_count


class HistoryStoreTests(unittest.TestCase):
    def test_saves_monitor_snapshot_for_future_backtests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "history.sqlite")
            save_monitor_snapshot(path, {"observed_at": "2026-07-10T00:00:00Z", "city": "London", "target_date": "2026-07-10", "markets": []})
            self.assertEqual(snapshot_count(path), 1)

    def test_normalizes_forecasts_markets_buckets_and_settlements(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "history.sqlite")
            snapshot = {"observed_at": "2026-07-10T00:00:00Z", "city": "Hong Kong", "target_date": "2026-07-10", "weather": {"forecasts": [{"source": "open_meteo", "max_temp": 31, "min_temp": 26, "unit": "C"}]}, "markets": [{"event_id": "e", "event_slug": "event", "markets": [{"market_id": "m", "question": "temperature", "outcome_prices": [0.4], "token_ids": ["t"]}], "event_bucket_plan": {"curve": {"rows": [{"bucket": "31C", "price": 0.4, "model_probability": 0.5, "edge": 0.1, "liquidity": 10, "spread": 0.01, "current_position": 0, "pnl_if_wins": 1}]}}}]}
            save_monitor_snapshot(path, snapshot)
            save_settlement_observation(path, "Hong Kong", "2026-07-10", {"source": "Hong Kong Observatory", "station": "HKO", "max_temp": 32, "min_temp": 27, "unit": "C", "status": "available"})
            counts = history_summary(path)
            report = calibration_summary(path)
        self.assertEqual((counts["forecast_observations"], counts["market_observations"], counts["bucket_observations"], counts["settlement_observations"]), (1, 1, 1, 1))
        self.assertEqual(report[0]["samples"], 1)

    def test_records_hong_kong_high_temperature_shadow_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "history.sqlite")
            save_monitor_snapshot(path, {
                "observed_at": "2026-07-10T00:00:00Z", "city": "Hong Kong", "target_date": "2026-07-10", "weather": {"confidence": 0.85, "disagreement": 0.5},
                "markets": [{"event_id": "e", "event_slug": "hk-high", "markets": [{"market_id": "m", "question": "Will the highest temperature in Hong Kong be 31C?"}], "event_bucket_plan": {
                    "settlement_rule": {"market_type": "highest_temperature"}, "decision": {"recommended_action": "block_new_position", "reasons": ["shadow_only"]},
                    "simulation_candidate": {"orders": [{"market_id": "m", "price": 0.4, "size": 2}], "curve": {"best_case_pnl": 1.2, "worst_case_pnl": -0.8}},
                }}],
            })
            counts = history_summary(path)
        self.assertEqual(counts["shadow_decisions"], 1)
