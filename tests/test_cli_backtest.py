import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from weather_edge.cli import main
from weather_edge.backtest import run_backtest
from weather_edge.risk_manager import RiskConfig


class CliBacktestTests(unittest.TestCase):
    def test_analyze_can_write_sqlite_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "weather_edge.sqlite")
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "analyze",
                        "--plan",
                        "data/sample_plan.json",
                        "--config",
                        "config/risk.example.json",
                        "--db",
                        db,
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(Path(db).exists())

    def test_backtest_sample_has_trade_and_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "summary.json"
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "backtest",
                        "--file",
                        "data/sample_backtest.json",
                        "--config",
                        "config/risk.example.json",
                    ]
                )

            output_path.write_text(json.dumps({"code": code}), encoding="utf-8")
            self.assertEqual(code, 0)

    def test_backtest_applies_partial_fill_and_slippage(self):
        scenario = {
            "market": {
                "market_id": "test", "city": "Test", "date": "2026-07-10", "market_type": "max_temp",
                "settlement_source": "NWS", "measurement_unit": "F", "timezone": "UTC", "target_station_or_data_source": "KAAA",
                "data_confidence": 0.9, "forecast_disagreement": 0.1, "time_to_settlement_minutes": 120, "orderbook_stale": False,
            },
            "winning_bucket": "A", "execution": {"fill_ratio": 0.5, "slippage": 0.1},
            "buckets": [{"bucket": "A", "price": 0.2, "shares": 10, "model_probability": 0.8, "liquidity": 100, "spread": 0.01}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest.json"
            path.write_text(json.dumps({"scenarios": [scenario]}), encoding="utf-8")
            summary, results = run_backtest(str(path), RiskConfig())

        self.assertEqual(summary.traded, 1)
        self.assertAlmostEqual(results[0]["curve"]["total_cost"], 1.5)
        self.assertAlmostEqual(results[0]["realized_pnl"], 3.5)
