import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weather_edge import BucketInput, MarketState, RiskConfig, build_pnl_curve, evaluate_trade_plan


def main() -> None:
    buckets = [
        BucketInput("31C", 0.05, 1, 0.09, liquidity=20, spread=0.02),
        BucketInput("32C", 0.24, 2, 0.30, liquidity=30, spread=0.03),
        BucketInput("33C", 0.30, 2, 0.38, liquidity=30, spread=0.03),
        BucketInput("34C", 0.18, 1, 0.22, liquidity=30, spread=0.03),
    ]
    config = RiskConfig(max_order_size=5)
    curve = build_pnl_curve(
        buckets,
        max_uncovered_probability=config.max_uncovered_probability,
    )
    state = MarketState(
        market_id="market-1",
        city="New York",
        date="2026-07-10",
        market_type="max_temp",
        settlement_source="NWS Central Park",
        measurement_unit="F",
        timezone="America/New_York",
        target_station_or_data_source="KNYC",
        data_confidence=0.80,
        forecast_disagreement=1.0,
        time_to_settlement_minutes=180,
        orderbook_stale=False,
    )
    decision = evaluate_trade_plan(curve, state, config)

    print("Bucket | Price | Shares | Cost | Model Probability | Edge | PnL if wins")
    for row in curve.rows:
        print(
            f"{row.bucket} | {row.price:.2f} | {row.shares:.2f} | "
            f"{row.cost:.2f} | {row.model_probability:.2f} | "
            f"{row.edge:.2f} | {row.pnl_if_wins:.2f}"
        )
    print(f"total_cost={curve.total_cost:.2f}")
    print(f"structure={curve.structure}")
    print(f"death_gaps={[gap.bucket for gap in curve.death_gaps]}")
    print(f"allowed={decision.allowed}")
    print(f"recommended_action={decision.recommended_action}")
    print(f"reasons={list(decision.reasons)}")


if __name__ == "__main__":
    main()
