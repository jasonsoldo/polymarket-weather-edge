from dataclasses import asdict, dataclass

from .bucket_probability import BucketProbabilityCurve
from .market_scanner import WeatherMarket
from .orderbook import BookSummary
from .pnl_curve import BucketInput, PnLCurve, build_pnl_curve
from .position_manager import Position
from .risk_manager import MarketState, RiskConfig, RiskDecision, evaluate_trade_plan
from .settlement_rules import SettlementRule
from .strategy_config import StrategyConfig


@dataclass(frozen=True)
class PlannedOrder:
    market_id: str
    token_id: str
    bucket: str
    side: str
    price: float
    size: float
    edge: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TradePlan:
    market_id: str
    orders: tuple[PlannedOrder, ...]
    curve: PnLCurve
    decision: RiskDecision

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "orders": [order.to_dict() for order in self.orders],
            "curve": _curve_to_dict(self.curve),
            "decision": {
                "allowed": self.decision.allowed,
                "recommended_action": self.decision.recommended_action,
                "reasons": list(self.decision.reasons),
            },
        }


def build_trade_plan(
    market: WeatherMarket,
    rule: SettlementRule,
    probability_curve: BucketProbabilityCurve,
    books: dict[str, BookSummary],
    positions: list[Position],
    strategy: StrategyConfig,
    risk: RiskConfig,
    current_total_exposure: float = 0.0,
) -> TradePlan:
    orders = _select_orders(market, probability_curve, books, strategy)
    buckets = []
    for index, prob in enumerate(probability_curve.buckets):
        token_id = market.token_ids[index] if index < len(market.token_ids) else ""
        book = books.get(token_id)
        order = next((item for item in orders if item.token_id == token_id), None)
        current_position = _position_size(positions, token_id)
        price = order.price if order else _market_price(prob.market_price, book)
        liquidity = _liquidity(book)
        spread = book.spread if book and book.spread is not None else 1.0
        buckets.append(
            BucketInput(
                bucket=prob.bucket,
                price=price,
                shares=order.size if order else 0.0,
                model_probability=prob.model_probability,
                liquidity=liquidity,
                spread=spread,
                current_position=current_position,
            )
        )

    curve = build_pnl_curve(buckets, risk.max_uncovered_probability)
    state = MarketState(
        market_id=market.market_id,
        city=rule.city,
        date=rule.date,
        market_type=rule.market_type,
        settlement_source=rule.settlement_source,
        measurement_unit=rule.measurement_unit,
        timezone=rule.timezone,
        target_station_or_data_source=rule.target_station_or_data_source,
        data_confidence=probability_curve.model.confidence,
        forecast_disagreement=probability_curve.model.disagreement or 0.0,
        time_to_settlement_minutes=9999,
        orderbook_stale=_orderbook_stale(books),
        current_market_exposure=sum(position.shares * position.avg_price for position in positions),
        current_total_exposure=current_total_exposure,
        realized_daily_loss=0.0,
    )
    decision = evaluate_trade_plan(curve, state, risk)
    return TradePlan(market.market_id, tuple(orders), curve, decision)


def _select_orders(
    market: WeatherMarket,
    probability_curve: BucketProbabilityCurve,
    books: dict[str, BookSummary],
    strategy: StrategyConfig,
) -> list[PlannedOrder]:
    ranked = sorted(probability_curve.buckets, key=lambda item: item.model_probability, reverse=True)
    selected = []
    for prob in ranked:
        if len(selected) >= strategy.max_buckets_to_buy:
            break
        if prob.edge < strategy.min_order_edge:
            continue
        index = list(probability_curve.buckets).index(prob)
        if index >= len(market.token_ids):
            continue
        token_id = market.token_ids[index]
        book = books.get(token_id)
        price = _market_price(prob.market_price, book)
        if price <= 0:
            continue
        selected.append(
            PlannedOrder(
                market_id=market.market_id,
                token_id=token_id,
                bucket=prob.bucket,
                side="BUY",
                price=price,
                size=_size_for_rank(len(selected), prob.model_probability, strategy),
                edge=prob.model_probability - price,
                reason="positive_model_edge",
            )
        )
    return selected


def _size_for_rank(rank: int, probability: float, strategy: StrategyConfig) -> float:
    if rank == 0:
        return strategy.main_bucket_shares
    if probability >= strategy.min_tail_probability:
        return strategy.neighbor_bucket_shares
    return strategy.tail_bucket_shares


def _market_price(fallback: float, book) -> float:
    if book and book.best_ask is not None:
        return book.best_ask
    return fallback


def _liquidity(book) -> float:
    if not book:
        return 0.0
    return book.ask_size


def _position_size(positions: list[Position], token_id: str) -> float:
    return sum(position.shares for position in positions if position.token_id == token_id)


def _orderbook_stale(books: dict[str, BookSummary]) -> bool:
    if not books:
        return True
    return any(not book.raw_timestamp and not book.book_hash for book in books.values())


def _curve_to_dict(curve: PnLCurve) -> dict:
    return {
        "structure": curve.structure,
        "total_cost": curve.total_cost,
        "expected_value": curve.expected_value,
        "worst_case_pnl": curve.worst_case_pnl,
        "best_case_pnl": curve.best_case_pnl,
        "sum_prices": curve.sum_prices,
        "max_uncovered_probability": curve.max_uncovered_probability,
        "death_gaps": [gap.__dict__ for gap in curve.death_gaps],
        "rows": [row.__dict__ for row in curve.rows],
    }
