from dataclasses import dataclass


@dataclass(frozen=True)
class BucketInput:
    bucket: str
    price: float
    shares: float
    model_probability: float
    liquidity: float = 0.0
    spread: float = 0.0
    current_position: float = 0.0


@dataclass(frozen=True)
class BucketPnL:
    bucket: str
    price: float
    shares: float
    cost: float
    model_probability: float
    edge: float
    liquidity: float
    spread: float
    current_position: float
    pnl_if_wins: float


@dataclass(frozen=True)
class DeathGap:
    bucket: str
    model_probability: float
    market_price: float


@dataclass(frozen=True)
class PnLCurve:
    rows: tuple[BucketPnL, ...]
    total_cost: float
    expected_value: float
    worst_case_pnl: float
    best_case_pnl: float
    sum_prices: float
    death_gaps: tuple[DeathGap, ...]
    max_uncovered_probability: float

    @property
    def is_full_coverage(self) -> bool:
        return all(row.shares > 0 for row in self.rows)

    @property
    def structure(self) -> str:
        if self.is_full_coverage:
            return "full_coverage"
        bought = [row for row in self.rows if row.shares > 0]
        if not bought:
            return "no_position"
        if len(bought) == 1:
            return "main_only"
        return "multi_bucket_dutching_with_tail_or_neighbor_protection"


def build_pnl_curve(
    buckets: list[BucketInput],
    max_uncovered_probability: float = 0.08,
) -> PnLCurve:
    if not buckets:
        raise ValueError("at least one bucket is required")
    if max_uncovered_probability < 0 or max_uncovered_probability > 1:
        raise ValueError("max_uncovered_probability must be between 0 and 1")

    total_cost = 0.0
    sum_prices = 0.0
    for bucket in buckets:
        _validate_bucket(bucket)
        total_cost += bucket.price * bucket.shares
        sum_prices += bucket.price

    rows = []
    death_gaps = []
    for bucket in buckets:
        cost = bucket.price * bucket.shares
        pnl_if_wins = bucket.shares - total_cost
        edge = bucket.model_probability - bucket.price
        row = BucketPnL(
            bucket=bucket.bucket,
            price=bucket.price,
            shares=bucket.shares,
            cost=cost,
            model_probability=bucket.model_probability,
            edge=edge,
            liquidity=bucket.liquidity,
            spread=bucket.spread,
            current_position=bucket.current_position,
            pnl_if_wins=pnl_if_wins,
        )
        rows.append(row)
        if bucket.shares == 0 and bucket.model_probability > max_uncovered_probability:
            death_gaps.append(
                DeathGap(
                    bucket=bucket.bucket,
                    model_probability=bucket.model_probability,
                    market_price=bucket.price,
                )
            )

    expected_value = sum(row.model_probability * row.pnl_if_wins for row in rows)
    max_gap = max(
        (row.model_probability for row in rows if row.shares == 0),
        default=0.0,
    )
    pnl_values = [row.pnl_if_wins for row in rows]
    return PnLCurve(
        rows=tuple(rows),
        total_cost=total_cost,
        expected_value=expected_value,
        worst_case_pnl=min(pnl_values),
        best_case_pnl=max(pnl_values),
        sum_prices=sum_prices,
        death_gaps=tuple(death_gaps),
        max_uncovered_probability=max_gap,
    )


def _validate_bucket(bucket: BucketInput) -> None:
    if not bucket.bucket:
        raise ValueError("bucket name is required")
    if bucket.price < 0 or bucket.price > 1:
        raise ValueError(f"{bucket.bucket}: price must be between 0 and 1")
    if bucket.shares < 0:
        raise ValueError(f"{bucket.bucket}: shares must not be negative")
    if bucket.model_probability < 0 or bucket.model_probability > 1:
        raise ValueError(f"{bucket.bucket}: model_probability must be between 0 and 1")
    if bucket.liquidity < 0:
        raise ValueError(f"{bucket.bucket}: liquidity must not be negative")
    if bucket.spread < 0:
        raise ValueError(f"{bucket.bucket}: spread must not be negative")
    if bucket.current_position < 0:
        raise ValueError(f"{bucket.bucket}: current_position must not be negative")
