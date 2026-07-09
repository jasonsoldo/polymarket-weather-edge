import unittest

from weather_edge import BucketInput, MarketState, RiskConfig, build_pnl_curve, evaluate_trade_plan


class RiskManagerTests(unittest.TestCase):
    def test_allows_valid_plan_after_curve_checks(self):
        curve = build_pnl_curve(
            [
                BucketInput("31C", 0.05, 1, 0.09, liquidity=20, spread=0.02),
                BucketInput("32C", 0.24, 2, 0.30, liquidity=30, spread=0.03),
                BucketInput("33C", 0.30, 2, 0.38, liquidity=30, spread=0.03),
                BucketInput("34C", 0.18, 1, 0.22, liquidity=30, spread=0.03),
            ],
            max_uncovered_probability=0.08,
        )

        decision = evaluate_trade_plan(curve, _state(), RiskConfig(max_order_size=5))

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.recommended_action, "allow_with_limit_order_and_duplicate_guard")

    def test_blocks_death_gap_and_bad_market_state(self):
        curve = build_pnl_curve(
            [
                BucketInput("31C", 0.05, 1, 0.09, liquidity=20, spread=0.02),
                BucketInput("32C", 0.24, 0, 0.30, liquidity=30, spread=0.03),
                BucketInput("33C", 0.30, 2, 0.38, liquidity=30, spread=0.03),
            ],
            max_uncovered_probability=0.08,
        )
        state = _state(data_confidence=0.5, orderbook_stale=True)

        decision = evaluate_trade_plan(curve, state)

        self.assertFalse(decision.allowed)
        self.assertIn("data confidence is below min_confidence", decision.reasons)
        self.assertIn("orderbook is stale", decision.reasons)
        self.assertTrue(any("death gap" in reason for reason in decision.reasons))

    def test_blocks_low_edge_liquidity_spread_and_size(self):
        curve = build_pnl_curve(
            [
                BucketInput("33C", 0.30, 30, 0.31, liquidity=2, spread=0.12),
                BucketInput("34C", 0.20, 0, 0.01, liquidity=30, spread=0.03),
            ]
        )

        decision = evaluate_trade_plan(curve, _state(), RiskConfig(max_order_size=10))

        self.assertFalse(decision.allowed)
        self.assertIn("33C: edge is below min_edge", decision.reasons)
        self.assertIn("33C: liquidity is below min_liquidity", decision.reasons)
        self.assertIn("33C: spread is above max_spread", decision.reasons)
        self.assertIn("33C: order size exceeds max_order_size", decision.reasons)


def _state(**overrides):
    values = {
        "market_id": "market-1",
        "city": "New York",
        "date": "2026-07-10",
        "market_type": "max_temp",
        "settlement_source": "NWS Central Park",
        "measurement_unit": "F",
        "timezone": "America/New_York",
        "target_station_or_data_source": "KNYC",
        "data_confidence": 0.80,
        "forecast_disagreement": 1.0,
        "time_to_settlement_minutes": 180,
        "orderbook_stale": False,
    }
    values.update(overrides)
    return MarketState(**values)


if __name__ == "__main__":
    unittest.main()
