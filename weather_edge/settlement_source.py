import os
from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional

from .http_client import get_json
from .settlement_rules import SettlementRule


HKO_OPEN_DATA_API = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php"
NWS_API = "https://api.weather.gov"


@dataclass(frozen=True)
class SettlementSourceResult:
    status: str
    source: str
    station: str
    target_date: str
    max_temp: Optional[float]
    min_temp: Optional[float]
    unit: str
    observed_at: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def settlement_source_capability(rule: SettlementRule) -> str:
    source = rule.settlement_source.lower()
    if "hong kong observatory" in source:
        return "supported_official"
    if "nws" in source or "national weather service" in source or "noaa" in source:
        return "supported_official"
    if "wunderground" in source or "weather underground" in source:
        return "unsupported_no_official_api"
    if "weatherapi" in source or "weather api" in source:
        return "supported_official" if __import__("os").getenv("WEATHERAPI_KEY") else "pending"
    if "accuweather" in source:
        return "supported_official" if __import__("os").getenv("ACCUWEATHER_API_KEY") else "pending"
    if any(name in source for name in ("meteostat", "met office", "jma", "kma", "cwa")):
        prefix = _provider_prefix(source)
        return "supported_official" if os.getenv(f"{prefix}_API_KEY") and os.getenv(f"{prefix}_SETTLEMENT_URL") else "pending"
    return "unsupported_settlement_source"


def fetch_settlement_observation(rule: SettlementRule) -> SettlementSourceResult:
    capability = settlement_source_capability(rule)
    if capability != "supported_official":
        return SettlementSourceResult(capability, rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "official adapter unavailable")
    if rule.date >= date.today().isoformat():
        return SettlementSourceResult("pending", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "settlement day is not complete")
    if "hong kong observatory" in rule.settlement_source.lower():
        return _fetch_hko(rule)
    if any(name in rule.settlement_source.lower() for name in ("met office", "jma", "kma", "cwa", "meteostat")):
        return _fetch_configured_official(rule)
    return _fetch_nws(rule)


def _provider_prefix(source: str) -> str:
    source = source.lower()
    if "met office" in source:
        return "METOFFICE"
    if "meteostat" in source:
        return "METEOSTAT"
    if "jma" in source:
        return "JMA"
    if "kma" in source:
        return "KMA"
    return "CWA"


def _fetch_configured_official(rule: SettlementRule) -> SettlementSourceResult:
    prefix = _provider_prefix(rule.settlement_source)
    endpoint = os.getenv(f"{prefix}_SETTLEMENT_URL", "")
    key = os.getenv(f"{prefix}_API_KEY", "")
    if not endpoint or not key:
        return SettlementSourceResult("pending", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "official adapter requires API key and settlement URL")
    try:
        endpoint = endpoint.replace("{date}", rule.date).replace("{station}", rule.target_station_or_data_source).replace("{city}", rule.city)
        params = {"station": rule.target_station_or_data_source, "date": rule.date, "target_date": rule.date}
        headers = {}
        if prefix == "METOFFICE":
            headers["apikey"] = key
        else:
            params["apiKey"] = key
        payload = get_json(endpoint, params, headers=headers)
        maximum, minimum, observed_at = _extract_extremes(payload)
        if maximum is None and minimum is None:
            return SettlementSourceResult("unavailable", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", f"{prefix} response contained no temperature extremes")
        return SettlementSourceResult("available", rule.settlement_source, rule.target_station_or_data_source, rule.date, maximum, minimum, rule.measurement_unit, observed_at or rule.date, f"official {prefix} configured adapter")
    except RuntimeError as exc:
        return SettlementSourceResult("unavailable", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", str(exc))


def _extract_extremes(payload):
    maximum = minimum = None
    observed_at = ""
    def visit(value):
        nonlocal maximum, minimum, observed_at
        if isinstance(value, dict):
            keys = {str(k).lower(): v for k, v in value.items()}
            for key, item in keys.items():
                if isinstance(item, (int, float, str)):
                    try:
                        number = float(item)
                    except (TypeError, ValueError):
                        continue
                    if any(token in key for token in ("maxt", "max_temp", "maximum", "high")):
                        maximum = number if maximum is None else max(maximum, number)
                    if any(token in key for token in ("mint", "min_temp", "minimum", "low")):
                        minimum = number if minimum is None else min(minimum, number)
                    if "time" in key or "date" in key:
                        observed_at = str(item)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(payload)
    return maximum, minimum, observed_at


def _fetch_hko(rule: SettlementRule) -> SettlementSourceResult:
    year, month, _day = rule.date.split("-")
    params = {"lang": "en", "rformat": "json", "station": "HKO", "year": year, "month": str(int(month))}
    maximum = _hko_daily_value("CLMMAXT", params, rule.date)
    minimum = _hko_daily_value("CLMMINT", params, rule.date)
    if maximum is None and minimum is None:
        return SettlementSourceResult("unavailable", rule.settlement_source, "HKO", rule.date, None, None, "C", "", "official HKO daily observation unavailable")
    return SettlementSourceResult("available", rule.settlement_source, "HKO", rule.date, maximum, minimum, "C", rule.date, "official HKO open data")


def _hko_daily_value(data_type: str, params: dict, target_date: str) -> Optional[float]:
    payload = get_json(HKO_OPEN_DATA_API, {"dataType": data_type, **params})
    fields = [str(field).lower() for field in payload.get("fields") or []]
    for row in payload.get("data") or []:
        values = list(row) if isinstance(row, (list, tuple)) else []
        if not values:
            continue
        if target_date[-2:] not in {str(value).zfill(2) for value in values[:2]}:
            continue
        for value in reversed(values):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _fetch_nws(rule: SettlementRule) -> SettlementSourceResult:
    station = rule.target_station_or_data_source.upper()
    if not station.startswith("K"):
        return SettlementSourceResult("unavailable", rule.settlement_source, station, rule.date, None, None, rule.measurement_unit, "", "NWS station identifier is required")
    payload = get_json(f"{NWS_API}/stations/{station}/observations", {"start": f"{rule.date}T00:00:00+00:00", "end": f"{rule.date}T23:59:59+00:00"})
    values = []
    observed_at = ""
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        value = ((properties.get("temperature") or {}).get("value"))
        if value is not None:
            values.append(float(value))
            observed_at = str(properties.get("timestamp") or observed_at)
    if not values:
        return SettlementSourceResult("unavailable", rule.settlement_source, station, rule.date, None, None, "C", "", "official NWS observations unavailable")
    return SettlementSourceResult("available", rule.settlement_source, station, rule.date, max(values), min(values), "C", observed_at, "official NWS observations")
