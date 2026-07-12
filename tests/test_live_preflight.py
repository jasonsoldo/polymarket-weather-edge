import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.live_preflight import hong_kong_live_preflight
from weather_edge.risk_manager import RiskConfig
from weather_edge.strategy_config import StrategyConfig


class LivePreflightTests(unittest.TestCase):
    def test_fails_closed_without_settlement_evidence_and_kill_switch(self):
        strategy = StrategyConfig(execution_mode="live", live_trading_enabled=True)
        risk = RiskConfig(min_edge=0.10, min_liquidity=100, max_spread=0.03, min_confidence=0.85, max_position_per_market=3, max_position_per_bucket=1, max_total_exposure=5, max_order_size=1, max_loss_per_market=3, max_daily_loss=3, max_uncovered_probability=0.03, disagreement_threshold=1.5)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "true", "POLYMARKET_PRIVATE_KEY": "secret", "WEATHER_EDGE_KILL_SWITCH": "true"}), patch("weather_edge.live_preflight.importlib.util.find_spec", return_value=object()):
            result = hong_kong_live_preflight(strategy, risk, str(Path(tmp) / "history.sqlite"), str(Path(tmp) / "orders.sqlite"))
        self.assertFalse(result["ready"])
        self.assertIn("hong_kong_settlement_verified", result["failed_checks"])
        self.assertIn("kill_switch_off", result["failed_checks"])

    def test_micro_live_configs_stay_within_first_order_limits(self):
        from weather_edge.config import load_risk_config
        from weather_edge.strategy_config import load_strategy_config
        strategy = load_strategy_config("config/strategy.micro-live.json")
        risk = load_risk_config("config/risk.micro-live.json")
        self.assertEqual(strategy.execution_mode, "live")
        self.assertLessEqual(risk.max_order_size, 1.0)
        self.assertLessEqual(risk.max_daily_loss, 3.0)
        self.assertLessEqual(risk.max_total_exposure, 5.0)


if __name__ == "__main__":
    unittest.main()
