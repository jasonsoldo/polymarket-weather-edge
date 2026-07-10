import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.alert_manager import emit_alerts
from weather_edge.orderbook import BookSummary
from weather_edge.portfolio import value_positions
from weather_edge.position_manager import Position, load_positions, upsert_position
from weather_edge.strategy_config import StrategyConfig
from weather_edge.strategy_planner import PlannedOrder
from weather_edge.trade_executor import _record_dry_run


class PortfolioAndAlertsTests(unittest.TestCase):
    def test_bid_marked_unrealized_pnl_and_dry_run_sell(self):
        position = Position("m", "t", "27C", 5, 0.4)
        book = BookSummary("t", "m", 0.6, 0.61, 0.01, 5, 5, 1, 0.01, False, "h", "now")
        valuation = value_positions([position], {"t": book})[0]
        self.assertAlmostEqual(valuation.unrealized_pnl, 1.0)

        with tempfile.TemporaryDirectory() as tmp:
            positions_db = str(Path(tmp) / "positions.sqlite")
            orders_db = str(Path(tmp) / "orders.sqlite")
            upsert_position(positions_db, position)
            order = PlannedOrder("m", "t", "27C", "SELL", 0.6, 3, 0.0, "protective_exit")
            result = _record_dry_run(order, StrategyConfig(), orders_db, positions_db, "sell-1")
            self.assertEqual(result.filled_size, 3)
            self.assertEqual(load_positions(positions_db)[0].shares, 2)

    def test_alerts_write_no_trade_and_settlement_source_events(self):
        snapshot = {"recommended_action": "NO_TRADE", "risk_reasons": ["weather data disagreement too high"], "cities": [{"city": "London", "markets": [{"event_slug": "london", "event_bucket_plan": {"decision": {"allowed": False, "reasons": ["unsupported_no_official_api"]}}, "settlement_observation": {"status": "unsupported_no_official_api"}}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "alerts.jsonl")
            alerts = emit_alerts(snapshot, path)
            self.assertEqual(len(alerts), 3)
            self.assertEqual(len(Path(path).read_text(encoding="utf-8").splitlines()), 3)
