import json
from pathlib import Path

from .pnl_curve import BucketInput
from .risk_manager import MarketState


def load_plan(path: str) -> tuple[MarketState, list[BucketInput]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    state = MarketState(**data["market"])
    buckets = [BucketInput(**bucket) for bucket in data["buckets"]]
    return state, buckets


def curve_to_dict(curve) -> dict:
    return {
        "structure": curve.structure,
        "total_cost": curve.total_cost,
        "expected_value": curve.expected_value,
        "worst_case_pnl": curve.worst_case_pnl,
        "best_case_pnl": curve.best_case_pnl,
        "sum_prices": curve.sum_prices,
        "max_uncovered_probability": curve.max_uncovered_probability,
        "death_gaps": [
            {
                "bucket": gap.bucket,
                "model_probability": gap.model_probability,
                "market_price": gap.market_price,
            }
            for gap in curve.death_gaps
        ],
        "rows": [
            {
                "bucket": row.bucket,
                "price": row.price,
                "shares": row.shares,
                "cost": row.cost,
                "model_probability": row.model_probability,
                "edge": row.edge,
                "liquidity": row.liquidity,
                "spread": row.spread,
                "current_position": row.current_position,
                "pnl_if_wins": row.pnl_if_wins,
            }
            for row in curve.rows
        ],
    }
