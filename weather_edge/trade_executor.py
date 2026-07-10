import os
from dataclasses import asdict, dataclass

from .order_store import StoredOrder, has_recent_duplicate, make_client_order_id, save_order
from .position_manager import Position, reduce_position, upsert_position
from .strategy_config import StrategyConfig
from .strategy_planner import PlannedOrder, TradePlan


BUY = "BUY"


@dataclass(frozen=True)
class ExecutionResult:
    client_order_id: str
    token_id: str
    bucket: str
    requested_size: float
    filled_size: float
    price: float
    status: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def execute_trade_plan(
    plan: TradePlan,
    strategy: StrategyConfig,
    orders_db: str,
    positions_db: str,
) -> list[ExecutionResult]:
    if not plan.decision.allowed:
        return [
            ExecutionResult(
                client_order_id="",
                token_id="",
                bucket="",
                requested_size=0.0,
                filled_size=0.0,
                price=0.0,
                status="blocked",
                reason="; ".join(plan.decision.reasons),
            )
        ]

    results = []
    for order in plan.orders:
        result = _execute_order(order, strategy, orders_db, positions_db)
        results.append(result)
    return results


def _execute_order(
    order: PlannedOrder,
    strategy: StrategyConfig,
    orders_db: str,
    positions_db: str,
) -> ExecutionResult:
    client_order_id = make_client_order_id(order.market_id, order.token_id, order.side, order.price, order.size)
    if has_recent_duplicate(orders_db, client_order_id, strategy.duplicate_order_window_seconds):
        return ExecutionResult(client_order_id, order.token_id, order.bucket, order.size, 0.0, order.price, "duplicate_blocked", "duplicate_order_guard")

    if strategy.execution_mode != "live":
        return _record_dry_run(order, strategy, orders_db, positions_db, client_order_id)

    if not strategy.live_trading_enabled:
        return _record_rejected(order, orders_db, client_order_id, "live_trading_enabled_false")
    if os.environ.get("LIVE_TRADING_ENABLED") != "true":
        return _record_rejected(order, orders_db, client_order_id, "LIVE_TRADING_ENABLED_env_not_true")
    if not os.environ.get(strategy.private_key_env):
        return _record_rejected(order, orders_db, client_order_id, f"{strategy.private_key_env}_missing")

    try:
        response = _post_live_order(order, strategy)
    except Exception as exc:
        return _record_rejected(order, orders_db, client_order_id, f"live_order_failed:{exc}")

    save_order(
        orders_db,
        StoredOrder(client_order_id, order.market_id, order.token_id, order.bucket, order.side, order.price, order.size, "live_submitted", {"order": order.to_dict(), "response": response}),
    )
    return ExecutionResult(client_order_id, order.token_id, order.bucket, order.size, 0.0, order.price, "live_submitted", "submitted_to_polymarket_clob")


def _record_dry_run(
    order: PlannedOrder,
    strategy: StrategyConfig,
    orders_db: str,
    positions_db: str,
    client_order_id: str,
) -> ExecutionResult:
    filled = order.size * strategy.dry_run_fill_ratio
    save_order(
        orders_db,
        StoredOrder(client_order_id, order.market_id, order.token_id, order.bucket, order.side, order.price, order.size, "dry_run_filled", order.to_dict()),
    )
    if filled > 0 and order.side == BUY:
        upsert_position(positions_db, Position(order.market_id, order.token_id, order.bucket, filled, order.price))
    elif filled > 0 and order.side == "SELL":
        filled = reduce_position(positions_db, order.market_id, order.token_id, filled)
    return ExecutionResult(client_order_id, order.token_id, order.bucket, order.size, filled, order.price, "dry_run_filled", "simulation_only_no_order_sent")


def _record_rejected(order: PlannedOrder, orders_db: str, client_order_id: str, reason: str) -> ExecutionResult:
    save_order(
        orders_db,
        StoredOrder(client_order_id, order.market_id, order.token_id, order.bucket, order.side, order.price, order.size, "rejected", {"order": order.to_dict(), "reason": reason}),
    )
    return ExecutionResult(client_order_id, order.token_id, order.bucket, order.size, 0.0, order.price, "rejected", reason)


def _post_live_order(order: PlannedOrder, strategy: StrategyConfig) -> dict:
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.constants import POLYGON
    except ImportError as exc:
        raise RuntimeError("py-clob-client is not installed") from exc

    private_key = os.environ[strategy.private_key_env]
    client = ClobClient("https://clob.polymarket.com", key=private_key, chain_id=POLYGON)
    client.set_api_creds(client.create_or_derive_api_creds())
    order_args = OrderArgs(price=order.price, size=order.size, side=order.side, token_id=order.token_id)
    signed_order = client.create_order(order_args)
    response = client.post_order(signed_order)
    return response if isinstance(response, dict) else {"response": str(response)}
