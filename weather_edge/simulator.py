from dataclasses import dataclass

from .pnl_curve import PnLCurve
from .risk_manager import RiskDecision


@dataclass(frozen=True)
class SimulationResult:
    filled: bool
    realized_pnl: float
    winning_bucket: str
    reason: str


def simulate_settlement(
    curve: PnLCurve,
    decision: RiskDecision,
    winning_bucket: str,
) -> SimulationResult:
    if not decision.allowed:
        return SimulationResult(False, 0.0, winning_bucket, "blocked_by_risk_manager")

    for row in curve.rows:
        if row.bucket == winning_bucket:
            return SimulationResult(True, row.pnl_if_wins, winning_bucket, "settled")
    raise ValueError(f"winning bucket not found: {winning_bucket}")
