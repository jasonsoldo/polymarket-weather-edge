from dataclasses import dataclass
from typing import Optional

from .pnl_curve import PnLCurve


@dataclass(frozen=True)
class RiskConfig:
    min_edge: float = 0.03
    min_liquidity: float = 10.0
    max_spread: float = 0.08
    min_confidence: float = 0.70
    max_position_per_market: float = 100.0
    max_position_per_bucket: float = 50.0
    max_total_exposure: float = 500.0
    max_order_size: float = 25.0
    max_loss_per_market: float = 50.0
    max_daily_loss: float = 100.0
    max_uncovered_probability: float = 0.08
    disagreement_threshold: float = 2.0
    stop_trading_near_settlement_minutes: int = 60
    safety_margin: float = 0.01


@dataclass(frozen=True)
class MarketState:
    market_id: str
    city: str
    date: str
    market_type: str
    settlement_source: str
    measurement_unit: str
    timezone: str
    target_station_or_data_source: str
    data_confidence: float
    forecast_disagreement: float
    time_to_settlement_minutes: int
    orderbook_stale: bool
    current_market_exposure: float = 0.0
    current_total_exposure: float = 0.0
    realized_daily_loss: float = 0.0


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    recommended_action: str
    reasons: tuple[str, ...]


def evaluate_trade_plan(
    curve: PnLCurve,
    state: MarketState,
    config: Optional[RiskConfig] = None,
) -> RiskDecision:
    config = config or RiskConfig()
    reasons = []

    _check_market_metadata(state, reasons)
    _check_market_state(state, config, reasons)
    _check_curve_risk(curve, config, reasons)
    _check_bought_buckets(curve, config, reasons)

    if reasons:
        return RiskDecision(
            allowed=False,
            recommended_action="block_new_position",
            reasons=tuple(reasons),
        )
    return RiskDecision(
        allowed=True,
        recommended_action="allow_with_limit_order_and_duplicate_guard",
        reasons=("risk checks passed",),
    )


def _check_market_metadata(state: MarketState, reasons: list[str]) -> None:
    required = {
        "market_id": state.market_id,
        "city": state.city,
        "date": state.date,
        "market_type": state.market_type,
        "settlement_source": state.settlement_source,
        "measurement_unit": state.measurement_unit,
        "timezone": state.timezone,
        "target_station_or_data_source": state.target_station_or_data_source,
    }
    for name, value in required.items():
        if not value:
            reasons.append(f"{name} is required")


def _check_market_state(
    state: MarketState,
    config: RiskConfig,
    reasons: list[str],
) -> None:
    if state.data_confidence < config.min_confidence:
        reasons.append("data confidence is below min_confidence")
    if state.forecast_disagreement > config.disagreement_threshold:
        reasons.append("weather data disagreement is above threshold")
    if state.orderbook_stale:
        reasons.append("orderbook is stale")
    if state.time_to_settlement_minutes < config.stop_trading_near_settlement_minutes:
        reasons.append("too close to settlement")
    if state.current_market_exposure > config.max_position_per_market:
        reasons.append("market exposure exceeds max_position_per_market")
    if state.current_total_exposure > config.max_total_exposure:
        reasons.append("total exposure exceeds max_total_exposure")
    if state.realized_daily_loss > config.max_daily_loss:
        reasons.append("daily loss exceeds max_daily_loss")


def _check_curve_risk(curve: PnLCurve, config: RiskConfig, reasons: list[str]) -> None:
    if curve.death_gaps:
        gaps = ", ".join(gap.bucket for gap in curve.death_gaps)
        reasons.append(f"death gap probability is too high: {gaps}")
    if curve.max_uncovered_probability > config.max_uncovered_probability:
        reasons.append("max uncovered bucket probability is too high")
    if abs(min(curve.worst_case_pnl, 0.0)) > config.max_loss_per_market:
        reasons.append("worst case loss exceeds max_loss_per_market")
    if curve.is_full_coverage and curve.sum_prices >= 1 - config.safety_margin:
        reasons.append("full coverage is not cheap enough to treat as near-arbitrage")


def _check_bought_buckets(
    curve: PnLCurve,
    config: RiskConfig,
    reasons: list[str],
) -> None:
    bought = [row for row in curve.rows if row.shares > 0]
    if not bought:
        reasons.append("no bucket shares were selected")
        return

    for row in bought:
        if row.edge <= config.min_edge:
            reasons.append(f"{row.bucket}: edge is below min_edge")
        if row.liquidity < config.min_liquidity:
            reasons.append(f"{row.bucket}: liquidity is below min_liquidity")
        if row.spread > config.max_spread:
            reasons.append(f"{row.bucket}: spread is above max_spread")
        if row.shares > config.max_order_size:
            reasons.append(f"{row.bucket}: order size exceeds max_order_size")
        if row.current_position + row.shares > config.max_position_per_bucket:
            reasons.append(f"{row.bucket}: bucket position exceeds max_position_per_bucket")
