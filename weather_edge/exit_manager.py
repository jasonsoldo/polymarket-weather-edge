from dataclasses import asdict, dataclass

from .orderbook import BookSummary
from .position_manager import Position
from .risk_manager import RiskDecision
from .strategy_planner import PlannedOrder


@dataclass(frozen=True)
class ExitPlan:
    market_id: str
    orders: tuple[PlannedOrder, ...]
    decision: RiskDecision

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "orders": [asdict(order) for order in self.orders],
            "decision": asdict(self.decision),
        }


def build_protective_exit_plan(positions: list[Position], books: dict[str, BookSummary], reason: str) -> ExitPlan:
    orders = []
    blocked = []
    for position in positions:
        book = books.get(position.token_id)
        if not book or book.best_bid is None or book.best_bid <= 0:
            blocked.append(f"{position.bucket}: no executable bid")
            continue
        orders.append(PlannedOrder(position.market_id, position.token_id, position.bucket, "SELL", book.best_bid, position.shares, 0.0, reason))
    reasons = tuple(blocked) if blocked else (reason,)
    decision = RiskDecision(bool(orders), "exit_positions" if orders else "cannot_exit_without_bid", reasons)
    return ExitPlan(positions[0].market_id if positions else "", tuple(orders), decision)
