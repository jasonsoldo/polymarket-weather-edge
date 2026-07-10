import re
from dataclasses import asdict, dataclass
from typing import Optional

from .market_scanner import WeatherMarket
from .city_registry import load_city_registry


@dataclass(frozen=True)
class BucketSpec:
    label: str
    lower: Optional[float]
    upper: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SettlementRule:
    city: str
    date: str
    market_type: str
    settlement_source: str
    measurement_unit: str
    timezone: str
    target_station_or_data_source: str
    rounding_rule: str
    confidence: float
    reasons: tuple[str, ...]
    buckets: tuple[BucketSpec, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["buckets"] = [bucket.to_dict() for bucket in self.buckets]
        return data


def parse_settlement_rule(market: WeatherMarket) -> SettlementRule:
    text = " ".join([market.event_title, market.question, market.description, market.resolution_source])
    lower_text = text.lower()
    unit = _parse_unit(text)
    market_type = _parse_market_type(lower_text, market.market_type_guess)
    source = _parse_source(text, market.resolution_source)
    city = market.normalized_city or market.city_guess or _parse_city(market.question)
    timezone = _parse_timezone(text, city)
    station = market.station_code or _parse_station(text, source)
    rounding = _parse_rounding(lower_text)
    date = _parse_date(market.question, market.end_date)
    buckets = _parse_market_buckets(market)
    reasons = _rule_reasons(city, date, market_type, source, unit, timezone, station, buckets)
    confidence = max(0.0, 1.0 - 0.12 * len(reasons))
    return SettlementRule(
        city=city,
        date=date,
        market_type=market_type,
        settlement_source=source,
        measurement_unit=unit,
        timezone=timezone,
        target_station_or_data_source=station,
        rounding_rule=rounding,
        confidence=confidence,
        reasons=tuple(reasons),
        buckets=buckets,
    )


def parse_bucket(label: str) -> BucketSpec:
    cleaned = label.strip()
    normalized = cleaned.lower().replace("°", "").replace(",", "")
    range_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:-|to)\s*(-?\d+(?:\.\d+)?)", normalized)
    if range_match:
        lower = float(range_match.group(1))
        upper = float(range_match.group(2))
        return BucketSpec(cleaned, min(lower, upper), max(lower, upper))

    numbers = [float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", normalized)]
    if not numbers:
        return BucketSpec(cleaned, None, None)

    if "below" in normalized or "or less" in normalized or "under" in normalized:
        return BucketSpec(cleaned, None, numbers[0])
    if "above" in normalized or "higher" in normalized or "or more" in normalized or normalized.endswith("+"):
        return BucketSpec(cleaned, numbers[0], None)
    return BucketSpec(cleaned, numbers[0], numbers[0])


def _parse_unit(text: str) -> str:
    lower = text.lower()
    if "°f" in lower or "ºf" in lower or re.search(r"\d\s*f\b", lower):
        return "F"
    if "°c" in lower or "ºc" in lower or re.search(r"\d\s*c\b", lower):
        return "C"
    if "fahrenheit" in lower or "°f" in lower or re.search(r"\bf\b", text):
        return "F"
    if "celsius" in lower or "°c" in lower or re.search(r"\bc\b", text):
        return "C"
    return ""


def _parse_market_type(lower_text: str, market_type_guess: str = "") -> str:
    if market_type_guess == "high_temp":
        return "max_temp"
    if market_type_guess == "low_temp":
        return "min_temp"
    if " high " in f" {lower_text} " or "maximum" in lower_text or "max temp" in lower_text:
        return "max_temp"
    if " low " in f" {lower_text} " or "minimum" in lower_text or "min temp" in lower_text:
        return "min_temp"
    return "temperature"


def _parse_source(text: str, resolution_source: str) -> str:
    if resolution_source:
        return resolution_source.strip()
    lower = text.lower()
    if "national weather service" in lower or "nws" in lower:
        return "NWS"
    if "noaa" in lower:
        return "NOAA"
    if "open-meteo" in lower:
        return "Open-Meteo"
    if "hong kong observatory" in lower:
        return "Hong Kong Observatory"
    if "wunderground.com" in lower or "weather underground" in lower:
        return "Weather Underground"
    if "met office" in lower or "metoffice" in lower:
        return "Met Office"
    if "japan meteorological agency" in lower or re.search(r"\bjma\b", lower):
        return "JMA"
    if "korea meteorological administration" in lower or re.search(r"\bkma\b", lower):
        return "KMA"
    if "central weather administration" in lower or re.search(r"\bcwa\b", lower):
        return "CWA"
    return ""


def _parse_timezone(text: str, city: str = "") -> str:
    lower = text.lower()
    if " et" in lower or " eastern time" in lower:
        return "America/New_York"
    if " ct" in lower or " central time" in lower:
        return "America/Chicago"
    if " mt" in lower or " mountain time" in lower:
        return "America/Denver"
    if " pt" in lower or " pacific time" in lower:
        return "America/Los_Angeles"
    if "hong kong" in lower or " hkt" in lower:
        return "Asia/Hong_Kong"
    normalized = city.strip().lower()
    for item in load_city_registry():
        names = [str(item.get("name", "")), *(str(alias) for alias in item.get("aliases", []))]
        if normalized in {name.lower() for name in names}:
            return str(item.get("timezone") or "")
    return ""


def _parse_station(text: str, source: str) -> str:
    station = re.search(r"(?:/|\b)([A-Z]{4})(?:\b|/)", text)
    if station:
        return station.group(1)
    named_station = re.search(r"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3}) (?:station|weather station)", text)
    if named_station:
        return named_station.group(1)
    if source:
        return source
    return ""


def _parse_rounding(lower_text: str) -> str:
    if "one decimal place" in lower_text or "nearest tenth" in lower_text:
        return "nearest_tenth"
    if "nearest whole" in lower_text or "rounded to the nearest" in lower_text:
        return "nearest_integer"
    if "floor" in lower_text or "round down" in lower_text:
        return "floor"
    if "ceil" in lower_text or "round up" in lower_text:
        return "ceil"
    return "nearest_integer"


def _parse_market_buckets(market: WeatherMarket) -> tuple[BucketSpec, ...]:
    """Polymarket temperature events are commonly one Yes/No market per bucket."""
    if len(market.outcomes) == 2 and {item.lower() for item in market.outcomes} == {"yes", "no"}:
        label = _bucket_label_from_question(market.question)
        if label:
            bucket = parse_bucket(label)
            if bucket.lower is not None or bucket.upper is not None:
                return (bucket,)
    return tuple(parse_bucket(label) for label in market.outcomes)


def _bucket_label_from_question(question: str) -> str:
    match = re.search(
        r"\b(?:be|of)\s+(-?\d+(?:\.\d+)?\s*(?:°|º)?\s*[CF](?:\s+or\s+(?:below|less|more|higher))?)",
        question,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _parse_city(question: str) -> str:
    for prefix in (" in ", " for "):
        if prefix in question:
            return question.split(prefix, 1)[1].split("?")[0].split(" on ")[0].strip()
    return ""


def _parse_date(question: str, end_date: str) -> str:
    if end_date:
        return end_date[:10]
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
    return match.group(1) if match else ""


def _rule_reasons(
    city: str,
    date: str,
    market_type: str,
    source: str,
    unit: str,
    timezone: str,
    station: str,
    buckets: tuple[BucketSpec, ...],
) -> list[str]:
    reasons = []
    if not city:
        reasons.append("city_not_parsed")
    if not date:
        reasons.append("date_not_parsed")
    if market_type == "temperature":
        reasons.append("market_type_not_specific")
    if not source:
        reasons.append("settlement_source_not_parsed")
    if not unit:
        reasons.append("unit_not_parsed")
    if not timezone:
        reasons.append("timezone_not_parsed")
    if not station:
        reasons.append("station_or_data_source_not_parsed")
    if not buckets or any(bucket.lower is None and bucket.upper is None for bucket in buckets):
        reasons.append("bucket_bounds_not_fully_parsed")
    return reasons
