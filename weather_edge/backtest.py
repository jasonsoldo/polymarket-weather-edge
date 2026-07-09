import json
from dataclasses import dataclass
from pathlib import Path

from .io import curve_to_dict
from .pnl_curve import BucketInput, build_pnl_curve
from .risk_manager import MarketState, RiskConfig, evaluate_trade_plan
from .simulator import simulate_settlement


@dataclass(frozen=True)
class BacktestSummary:
    scenarios: int
    traded: int
    blocked: int
    total_realized_pnl: float
    max_drawdown: float


def run_backtest(path: str, config: RiskConfig) -> tuple[BacktestSummary, list[dict]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = []
    equity = 0.0
    peak_equity = 0.0
    max_drawdown = 0.0
    traded = 0
    blocked = 0

    for scenario in data["scenarios"]:
        state = MarketState(**scenario["market"])
        buckets = [BucketInput(**bucket) for bucket in scenario["buckets"]]
        curve = build_pnl_curve(buckets, config.max_uncovered_probability)
        decision = evaluate_trade_plan(curve, state, config)
        sim = simulate_settlement(curve, decision, scenario["winning_bucket"])

        if sim.filled:
            traded += 1
            equity += sim.realized_pnl
        else:
            blocked += 1

        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, peak_equity - equity)
        results.append(
            {
                "market_id": state.market_id,
                "winning_bucket": scenario["winning_bucket"],
                "allowed": decision.allowed,
                "recommended_action": decision.recommended_action,
                "reasons": list(decision.reasons),
                "realized_pnl": sim.realized_pnl,
                "equity": equity,
                "curve": curve_to_dict(curve),
            }
        )

    summary = BacktestSummary(
        scenarios=len(data["scenarios"]),
        traded=traded,
        blocked=blocked,
        total_realized_pnl=equity,
        max_drawdown=max_drawdown,
    )
    return summary, results
