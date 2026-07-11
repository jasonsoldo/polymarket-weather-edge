import math
from dataclasses import asdict, dataclass
from typing import Optional

from .market_scanner import WeatherMarket
from .settlement_rules import BucketSpec, SettlementRule
from .weather_sources import WeatherSnapshot


@dataclass(frozen=True)
class ProbabilityModel:
    mean: float
    standard_deviation: float
    source_count: int
    disagreement: Optional[float]
    confidence: float
    target_temperature_type: str
    observation_floor: Optional[float]
    dynamic_update: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BucketProbability:
    bucket: str
    lower: Optional[float]
    upper: Optional[float]
    model_probability: float
    market_price: float
    edge: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BucketProbabilityCurve:
    model: ProbabilityModel
    buckets: tuple[BucketProbability, ...]
    probability_sum: float

    def to_dict(self) -> dict:
        return {
            "model": self.model.to_dict(),
            "probability_sum": self.probability_sum,
            "buckets": [bucket.to_dict() for bucket in self.buckets],
        }


def build_bucket_probabilities(
    rule: SettlementRule,
    weather: WeatherSnapshot,
    market: WeatherMarket,
) -> BucketProbabilityCurve:
    model = build_probability_model(rule, weather)

    raw_probs = [bucket_model_probability(bucket, model, rule.rounding_rule) for bucket in rule.buckets]
    total = sum(raw_probs)
    normalized = [prob / total for prob in raw_probs] if total > 0 else raw_probs
    rows = []
    for index, bucket in enumerate(rule.buckets):
        market_price = market.outcome_prices[index] if index < len(market.outcome_prices) else 0.0
        probability = normalized[index] if index < len(normalized) else 0.0
        rows.append(
            BucketProbability(
                bucket=bucket.label,
                lower=bucket.lower,
                upper=bucket.upper,
                model_probability=probability,
                market_price=market_price,
                edge=probability - market_price,
            )
        )
    return BucketProbabilityCurve(
        model=model,
        buckets=tuple(rows),
        probability_sum=sum(row.model_probability for row in rows),
    )


def build_probability_model(rule: SettlementRule, weather: WeatherSnapshot) -> ProbabilityModel:
    values = _forecast_values(rule, weather)
    if not values:
        raise ValueError("no forecast values available for market type")
    mean = sum(values) / len(values)
    observation_floor = _observation_floor(rule, weather)
    return ProbabilityModel(
        mean=mean,
        standard_deviation=_stddev(rule, weather, values),
        source_count=len(values),
        disagreement=weather.disagreement,
        confidence=min(rule.confidence, weather.confidence),
        target_temperature_type=rule.market_type,
        observation_floor=observation_floor,
        dynamic_update=observation_floor is not None,
    )


def bucket_model_probability(bucket: BucketSpec, model: ProbabilityModel, rounding_rule: str) -> float:
    if model.observation_floor is None:
        return _bucket_probability(bucket, model.mean, model.standard_deviation, rounding_rule)
    return _conditional_bucket_probability(bucket, model.mean, model.standard_deviation, rounding_rule, model.observation_floor)


def _forecast_values(rule: SettlementRule, weather: WeatherSnapshot) -> list[float]:
    values = []
    for forecast in weather.forecasts:
        value = forecast.min_temp if rule.market_type == "min_temp" else forecast.max_temp
        if value is not None:
            values.append(_convert_temperature(float(value), forecast.unit, rule.measurement_unit))
    return values


def _stddev(rule: SettlementRule, weather: WeatherSnapshot, values: list[float]) -> float:
    if len(values) >= 2:
        mean = sum(values) / len(values)
        sample = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    else:
        sample = 0.0
    disagreement = weather.disagreement or 0.0
    if rule.measurement_unit.upper().startswith("C"):
        disagreement /= 1.8
    disagreement_component = disagreement / 2.0
    confidence_penalty = max(0.0, 0.80 - min(rule.confidence, weather.confidence)) * 2.0
    return max(1.0, sample, disagreement_component, confidence_penalty)


def _observation_floor(rule: SettlementRule, weather: WeatherSnapshot) -> Optional[float]:
    observation = weather.hko_observation or {}
    if rule.city != "Hong Kong" or rule.market_type != "max_temp" or not observation.get("healthy"):
        return None
    value = observation.get("max_temp_since_midnight")
    if value is None:
        return None
    return _convert_temperature(float(value), observation.get("unit", "C"), rule.measurement_unit)


def _conditional_bucket_probability(bucket: BucketSpec, mean: float, stddev: float, rounding_rule: str, floor: float) -> float:
    lower, upper = _rounded_bounds(bucket, rounding_rule)
    if upper is not None and upper <= floor:
        return 0.0
    effective_lower = floor if lower is None else max(lower, floor)
    denominator = max(1e-12, 1.0 - _normal_cdf(floor, mean, stddev))
    if upper is None:
        numerator = 1.0 - _normal_cdf(effective_lower, mean, stddev)
    else:
        numerator = max(0.0, _normal_cdf(upper, mean, stddev) - _normal_cdf(effective_lower, mean, stddev))
    return min(1.0, numerator / denominator)


def _bucket_probability(
    bucket: BucketSpec,
    mean: float,
    stddev: float,
    rounding_rule: str,
) -> float:
    lower, upper = _rounded_bounds(bucket, rounding_rule)
    if lower is None and upper is None:
        return 0.0
    if lower is None:
        return _normal_cdf(upper, mean, stddev)
    if upper is None:
        return 1.0 - _normal_cdf(lower, mean, stddev)
    return max(0.0, _normal_cdf(upper, mean, stddev) - _normal_cdf(lower, mean, stddev))


def _rounded_bounds(bucket: BucketSpec, rounding_rule: str) -> tuple[Optional[float], Optional[float]]:
    if rounding_rule == "interval":
        return bucket.lower, bucket.upper
    if bucket.lower is not None and bucket.upper is not None and bucket.lower != bucket.upper:
        return bucket.lower, bucket.upper
    if rounding_rule == "nearest_tenth" and (bucket.lower is None or bucket.upper is None):
        return bucket.lower, bucket.upper
    if rounding_rule == "floor":
        lower = bucket.lower
        upper = None if bucket.upper is None else bucket.upper + 1.0
    elif rounding_rule == "ceil":
        lower = None if bucket.lower is None else bucket.lower - 1.0
        upper = bucket.upper
    elif rounding_rule == "nearest_tenth":
        lower = None if bucket.lower is None else bucket.lower - 0.05
        upper = None if bucket.upper is None else bucket.upper + 0.05
    else:
        lower = None if bucket.lower is None else bucket.lower - 0.5
        upper = None if bucket.upper is None else bucket.upper + 0.5
    return lower, upper


def _normal_cdf(value: float, mean: float, stddev: float) -> float:
    z = (value - mean) / (stddev * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def _convert_temperature(value: float, source_unit: str, target_unit: str) -> float:
    source = source_unit.upper().replace("°", "")
    target = target_unit.upper().replace("°", "")
    if not target or source == target:
        return value
    if source.startswith("F") and target.startswith("C"):
        return (value - 32.0) * 5.0 / 9.0
    if source.startswith("C") and target.startswith("F"):
        return value * 9.0 / 5.0 + 32.0
    return value
