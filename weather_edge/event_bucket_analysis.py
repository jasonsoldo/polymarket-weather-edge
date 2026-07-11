from dataclasses import dataclass
from typing import Optional

from .bucket_probability import build_probability_model, bucket_model_probability
from .market_scanner import WeatherMarket
from .orderbook import BookSummary
from .pnl_curve import BucketInput, PnLCurve, build_pnl_curve
from .position_manager import Position
from .risk_manager import MarketState, RiskConfig, RiskDecision, evaluate_trade_plan
from .settlement_source import settlement_source_capability, settlement_status_allows_scoring
from .settlement_rules import BucketSpec, SettlementRule, normalize_bucket_sequence, parse_settlement_rule
from .strategy_config import StrategyConfig
from .strategy_planner import PlannedOrder
from .weather_sources import WeatherSnapshot


@dataclass(frozen=True)
class EventTradePlan:
    event_id: str
    event_slug: str
    settlement_rule: SettlementRule
    settlement_source_status: str
    forecast_model: object
    probability_sum: float
    bucket_set_complete: bool
    completeness_reasons: tuple[str, ...]
    orders: tuple[PlannedOrder, ...]
    curve: PnLCurve
    decision: RiskDecision
    simulation_candidate: Optional[dict]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_slug": self.event_slug,
            "city": self.settlement_rule.city,
            "date": self.settlement_rule.date,
            "market_type": self.settlement_rule.market_type,
            "settlement_rule": self.settlement_rule.to_dict(),
            "settlement_source_status": self.settlement_source_status,
            "forecast_model": self.forecast_model.to_dict(),
            "probability_sum": self.probability_sum,
            "bucket_set_complete": self.bucket_set_complete,
            "completeness_reasons": list(self.completeness_reasons),
            "orders": [order.to_dict() for order in self.orders],
            "curve": _curve_to_dict(self.curve),
            "simulation_candidate": self.simulation_candidate,
            "decision": {
                "allowed": self.decision.allowed,
                "recommended_action": self.decision.recommended_action,
                "reasons": list(self.decision.reasons),
            },
        }


def group_event_markets(markets: list[WeatherMarket]) -> list[list[WeatherMarket]]:
    groups: dict[tuple[str, str], list[WeatherMarket]] = {}
    for market in markets:
        key = (market.event_id or market.event_slug, market.market_type_guess)
        groups.setdefault(key, []).append(market)
    return list(groups.values())


def build_event_trade_plan(
    markets: list[WeatherMarket],
    weather: WeatherSnapshot,
    strategy: StrategyConfig,
    risk: RiskConfig,
    books: Optional[dict[str, BookSummary]] = None,
    positions: Optional[list[Position]] = None,
    current_total_exposure: float = 0.0,
) -> EventTradePlan:
    if not markets:
        raise ValueError("at least one market is required")
    books = books or {}
    positions = positions or []
    parsed = [(market, parse_settlement_rule(market)) for market in markets]
    event_buckets = normalize_bucket_sequence(tuple(item[1].buckets[0] for item in parsed if len(item[1].buckets) == 1))
    parsed = [(market, SettlementRule(**{**rule.__dict__, "buckets": (event_buckets[index],)}) if index < len(event_buckets) and len(rule.buckets) == 1 else rule) for index, (market, rule) in enumerate(parsed)]
    event_rounding = "interval" if len(event_buckets) == len(parsed) and len(event_buckets) > 1 else None
    rule = parsed[0][1]
    completeness_reasons = _completeness_reasons(parsed)
    model = build_probability_model(rule, weather)
    source_status = settlement_source_capability(rule)
    bucket_rows = []
    for market, market_rule in parsed:
        if len(market_rule.buckets) != 1:
            completeness_reasons.append(f"{market.market_id}: expected one temperature bucket")
            continue
        bucket = market_rule.buckets[0]
        yes_index = _yes_index(market)
        if yes_index is None:
            completeness_reasons.append(f"{market.market_id}: Yes outcome is required")
            continue
        token_id = market.token_ids[yes_index] if yes_index < len(market.token_ids) else ""
        if not token_id:
            completeness_reasons.append(f"{market.market_id}: Yes token is required")
            continue
        market_price = market.outcome_prices[yes_index] if yes_index < len(market.outcome_prices) else 0.0
        bucket_rows.append((market, bucket, token_id, market_price, bucket_model_probability(bucket, model, event_rounding or rule.rounding_rule)))

    complete = not completeness_reasons and _has_both_tails([row[1] for row in bucket_rows])
    if not _has_both_tails([row[1] for row in bucket_rows]):
        completeness_reasons.append("bucket set is missing a lower or upper tail")
    probability_sum = sum(row[4] for row in bucket_rows)
    if probability_sum < 0.98:
        complete = False
        completeness_reasons.append("bucket probabilities do not cover the full temperature distribution")

    selected = _select_orders(bucket_rows, strategy, books) if complete and not rule.reasons else []
    if not bucket_rows:
        raise ValueError("no usable Yes bucket markets")
    curve = _build_curve(bucket_rows, selected, books, positions, risk)
    state = MarketState(
        market_id=markets[0].event_id or markets[0].event_slug,
        city=rule.city,
        date=rule.date,
        market_type=rule.market_type,
        settlement_source=rule.settlement_source,
        measurement_unit=rule.measurement_unit,
        timezone=rule.timezone,
        target_station_or_data_source=rule.target_station_or_data_source,
        data_confidence=model.confidence,
        forecast_disagreement=model.disagreement or 0.0,
        time_to_settlement_minutes=9999,
        orderbook_stale=not books or any(token_id not in books for _, _, token_id, _, _ in bucket_rows),
        current_market_exposure=sum(item.shares * item.avg_price for item in positions),
        current_total_exposure=current_total_exposure,
    )
    decision = evaluate_trade_plan(curve, state, risk)
    if not complete or rule.reasons or not settlement_status_allows_scoring(source_status):
        reasons = list(decision.reasons) + list(rule.reasons) + list(dict.fromkeys(completeness_reasons))
        if not settlement_status_allows_scoring(source_status):
            reasons.append(source_status)
        decision = RiskDecision(False, "block_new_position", tuple(dict.fromkeys(reasons)))
    simulation_candidate = _build_simulation_candidate(bucket_rows, selected, strategy, books, positions, risk, state)
    return EventTradePlan(
        markets[0].event_id,
        markets[0].event_slug,
        rule,
        source_status,
        model,
        probability_sum,
        complete,
        tuple(dict.fromkeys(completeness_reasons)),
        tuple(selected),
        curve,
        decision,
        simulation_candidate,
    )


def _completeness_reasons(parsed: list[tuple[WeatherMarket, SettlementRule]]) -> list[str]:
    rules = [rule for _, rule in parsed]
    first = rules[0]
    reasons = []
    for field in ("city", "date", "market_type", "settlement_source", "measurement_unit", "timezone"):
        if any(getattr(rule, field) != getattr(first, field) for rule in rules[1:]):
            reasons.append(f"inconsistent {field} across event buckets")
    return reasons


def _has_both_tails(buckets: list[BucketSpec]) -> bool:
    return bool(buckets) and any(bucket.lower is None for bucket in buckets) and any(bucket.upper is None for bucket in buckets)


def _yes_index(market: WeatherMarket) -> Optional[int]:
    for index, outcome in enumerate(market.outcomes):
        if outcome.strip().lower() == "yes":
            return index
    return None


def _select_orders(rows, strategy: StrategyConfig, books: dict[str, BookSummary]) -> list[PlannedOrder]:
    selected = []
    for market, bucket, token_id, market_price, probability in sorted(rows, key=lambda row: row[4], reverse=True):
        if len(selected) >= strategy.max_buckets_to_buy:
            break
        book = books.get(token_id)
        price = _market_price(market_price, book)
        edge = probability - price
        if price <= 0 or edge < strategy.min_order_edge:
            continue
        size = strategy.main_bucket_shares if not selected else (
            strategy.neighbor_bucket_shares if probability >= strategy.min_tail_probability else strategy.tail_bucket_shares
        )
        selected.append(PlannedOrder(market.market_id, token_id, bucket.label, "BUY", price, size, edge, "positive_event_bucket_edge"))
    return selected


def _build_simulation_candidate(rows, selected, strategy, books, positions, risk, state) -> Optional[dict]:
    selected_ids = {order.token_id for order in selected}
    protective = [row for row in rows if row[2] not in selected_ids and row[4] > risk.max_uncovered_probability]
    if not protective:
        return None
    hypothetical = list(selected)
    for market, bucket, token_id, market_price, probability in sorted(protective, key=lambda row: row[4], reverse=True):
        price = _market_price(market_price, books.get(token_id))
        hypothetical.append(PlannedOrder(
            market.market_id, token_id, bucket.label, "BUY", price,
            strategy.neighbor_bucket_shares, probability - price, "simulation_coverage_protection",
        ))
    curve = _build_curve(rows, hypothetical, books, positions, risk)
    decision = evaluate_trade_plan(curve, state, risk)
    return {
        "recommended_action": "SIMULATE_ONLY",
        "executable": False,
        "reason": "hypothetical protection for high-probability uncovered buckets",
        "orders": [{**order.to_dict(), "side": "SIMULATE_BUY"} for order in hypothetical],
        "curve": _curve_to_dict(curve),
        "not_executable_reasons": list(decision.reasons),
    }


def _build_curve(rows, orders, books, positions, risk) -> PnLCurve:
    inputs = []
    for market, bucket, token_id, market_price, probability in rows:
        book = books.get(token_id)
        order = next((item for item in orders if item.token_id == token_id), None)
        inputs.append(BucketInput(
            bucket=bucket.label,
            price=order.price if order else _market_price(market_price, book),
            shares=order.size if order else 0.0,
            model_probability=probability,
            liquidity=book.ask_size if book else 0.0,
            spread=book.spread if book and book.spread is not None else 1.0,
            current_position=sum(item.shares for item in positions if item.token_id == token_id),
        ))
    return build_pnl_curve(inputs, risk.max_uncovered_probability)


def _market_price(fallback: float, book: Optional[BookSummary]) -> float:
    return book.best_ask if book and book.best_ask is not None else fallback


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
