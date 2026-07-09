import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather_edge.order_store import has_recent_duplicate
from weather_edge.position_manager import load_positions
from weather_edge.risk_manager import RiskConfig, RiskDecision
from weather_edge.live_pipeline import run_live_dry_run
from weather_edge.strategy_config import StrategyConfig, load_strategy_config
from weather_edge.strategy_planner import PlannedOrder
from weather_edge.trade_executor import execute_trade_plan
from weather_edge.weather_sources import WeatherSnapshot


class TradeExecutionTests(unittest.TestCase):
    def test_dry_run_records_order_and_position_without_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders_db = str(Path(tmp) / "orders.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            plan = _allowed_plan()

            results = execute_trade_plan(plan, StrategyConfig(), orders_db, positions_db)

            self.assertEqual(results[0].status, "dry_run_filled")
            self.assertEqual(results[0].filled_size, 2.0)
            self.assertTrue(has_recent_duplicate(orders_db, results[0].client_order_id, 3600))
            positions = load_positions(positions_db)
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].shares, 2.0)

    def test_duplicate_order_guard_blocks_second_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders_db = str(Path(tmp) / "orders.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            plan = _allowed_plan()

            first = execute_trade_plan(plan, StrategyConfig(), orders_db, positions_db)
            second = execute_trade_plan(plan, StrategyConfig(), orders_db, positions_db)

            self.assertEqual(first[0].status, "dry_run_filled")
            self.assertEqual(second[0].status, "duplicate_blocked")

    def test_private_key_alone_does_not_enable_live_trading(self):
        with tempfile.TemporaryDirectory() as tmp:
            orders_db = str(Path(tmp) / "orders.sqlite")
            positions_db = str(Path(tmp) / "positions.sqlite")
            os.environ["POLYMARKET_PRIVATE_KEY"] = "fake"
            os.environ.pop("LIVE_TRADING_ENABLED", None)
            try:
                strategy = StrategyConfig(execution_mode="live", live_trading_enabled=True)
                results = execute_trade_plan(_allowed_plan(), strategy, orders_db, positions_db)
            finally:
                os.environ.pop("POLYMARKET_PRIVATE_KEY", None)

            self.assertEqual(results[0].status, "rejected")
            self.assertEqual(results[0].reason, "LIVE_TRADING_ENABLED_env_not_true")

    def test_strategy_config_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.json"
            path.write_text('{"execution_mode": "dry_run", "surprise": true}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown strategy config"):
                load_strategy_config(str(path))

    def test_live_dry_run_blocks_before_buy_when_weather_confidence_is_bad(self):
        weather = WeatherSnapshot(
            city="New York",
            latitude=40.7128,
            longitude=-74.006,
            target_date="2026-07-10",
            forecasts=(),
            disagreement=6.3,
            confidence=0.25,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("weather_edge.live_pipeline.fetch_weather_snapshot", return_value=weather), patch(
                "weather_edge.live_pipeline.fetch_weather_markets"
            ) as fetch_markets:
                result = run_live_dry_run(
                    "New York",
                    40.7128,
                    -74.006,
                    "2026-07-10",
                    StrategyConfig(),
                    RiskConfig(),
                    str(Path(tmp) / "orders.sqlite"),
                    str(Path(tmp) / "positions.sqlite"),
                )

        fetch_markets.assert_not_called()
        self.assertEqual(result["recommended_action"], "NO_TRADE")
        self.assertEqual(result["blocked_by"], "data_disagreement")
        self.assertIn("weather data disagreement too high", result["risk_reasons"])
        self.assertIn("confidence below min_confidence", result["risk_reasons"])
        self.assertEqual(result["results"], [])


def _allowed_plan():
    order = PlannedOrder(
        market_id="market-1",
        token_id="token-1",
        bucket="88F",
        side="BUY",
        price=0.30,
        size=2.0,
        edge=0.08,
        reason="positive_model_edge",
    )
    decision = RiskDecision(True, "allow_with_limit_order_and_duplicate_guard", ("risk checks passed",))
    return SimpleNamespace(decision=decision, orders=(order,))
