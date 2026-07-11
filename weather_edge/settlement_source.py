import os
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional

from .http_client import get_json
from .official_sources import extract_observation
from .settlement_rules import SettlementRule
from .settlement_sources.wunderground import fetch_wunderground_api
from .settlement_sources.wunderground_browser import fetch_wunderground_browser


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


def settlement_status_allows_scoring(status: str) -> bool:
    return status in {"supported_official", "official_api_supported", "official_source_verified", "wu_verified"}


def settlement_source_capability(rule: SettlementRule) -> str:
    source = rule.settlement_source.lower()
    if "hong kong observatory" in source:
        return "supported_official"
    if "nws" in source or "national weather service" in source or "noaa" in source:
        return "supported_official"
    if "wunderground" in source or "weather underground" in source:
        verified = _verified_wu_stations()
        return "wu_verified" if rule.target_station_or_data_source.upper() in verified else ("wu_api_supported" if os.getenv("WU_API_KEY") and os.getenv("WU_API_URL") else "pending_wu_adapter")
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
    if "wunderground" in rule.settlement_source.lower() or "weather underground" in rule.settlement_source.lower():
        result = fetch_wunderground_api(rule.target_station_or_data_source, rule.date, rule.measurement_unit, rule.settlement_source)
        if result.status in {"pending_wu_adapter", "wu_unavailable"} and os.getenv("WU_BROWSER_ENABLED", "false").lower() == "true":
            template = os.getenv("WU_HISTORY_URL_TEMPLATE", "https://www.wunderground.com/history/daily/{station}/{date}")
            url = template.replace("{station}", rule.target_station_or_data_source).replace("{date}", rule.date)
            result = fetch_wunderground_browser(url, rule.target_station_or_data_source, rule.date, rule.measurement_unit)
        return SettlementSourceResult(result.status, rule.settlement_source, result.station, result.date, result.daily_high, result.daily_low, result.unit, result.updated_at, result.reason)
    if capability != "supported_official":
        return SettlementSourceResult(capability, rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "official adapter unavailable")
    if rule.date >= date.today().isoformat():
        return SettlementSourceResult("pending", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "settlement day is not complete")
    if "hong kong observatory" in rule.settlement_source.lower():
        return _fetch_hko(rule)
    if any(name in rule.settlement_source.lower() for name in ("met office", "jma", "kma", "cwa", "meteostat")):
        return _fetch_configured_official(rule)
    return _fetch_nws(rule)


def _verified_wu_stations() -> set[str]:
    path = os.getenv("WU_VALIDATION_FILE", "data/wunderground_validation.json")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return {station.upper() for station, result in payload.items() if result.get("verified") is True}
    except (OSError, ValueError, AttributeError):
        return set()



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
        return SettlementSourceResult("pending", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "official endpoint and API key are required")
    endpoint = endpoint.replace("{date}", rule.date).replace("{station}", rule.target_station_or_data_source).replace("{city}", rule.city)
    params = {"station": rule.target_station_or_data_source, "date": rule.date, "target_date": rule.date}
    headers = {"User-Agent": "WeatherEdge/1.0"}
    if prefix == "METOFFICE":
        headers["apikey"] = key
    else:
        params["apiKey"] = key
    try:
        payload = get_json(endpoint, params, headers=headers)
        maximum, minimum, observed_at, response_date, response_station, response_unit = extract_observation(payload)
        if response_date and not str(response_date).startswith(rule.date):
            return SettlementSourceResult("source_mismatch", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, str(observed_at or ""), "response date does not match target date")
        if response_station and str(response_station).upper() != rule.target_station_or_data_source.upper():
            return SettlementSourceResult("source_mismatch", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, str(observed_at or ""), "response station does not match target station")
        if response_unit and response_unit.upper().replace("°", "")[0] != rule.measurement_unit.upper().replace("°", "")[0]:
            return SettlementSourceResult("source_mismatch", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, str(observed_at or ""), "response unit does not match requested unit")
        if maximum is None and minimum is None:
            return SettlementSourceResult("unavailable", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", f"{prefix} response contained no temperature extremes")
        return SettlementSourceResult("available", rule.settlement_source, rule.target_station_or_data_source, rule.date, maximum, minimum, rule.measurement_unit, str(observed_at or rule.date), f"official {prefix} configured adapter")
    except (RuntimeError, TypeError, ValueError) as exc:
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
    if not payload.get("data") and "month" in params:
        fallback = {key: value for key, value in params.items() if key != "month"}
        payload = get_json(HKO_OPEN_DATA_API, {"dataType": data_type, **fallback})
    fields = [str(field).strip().lower() for field in payload.get("fields") or []]
    for row in payload.get("data") or []:
        values = list(row) if isinstance(row, (list, tuple)) else []
        if not values:
            continue
        if not _hko_row_matches(values, fields, target_date):
            continue
        value_indexes = [index for index, field in enumerate(fields) if "value" in field or "數值" in field]
        candidates = [values[index] for index in value_indexes if index < len(values)] or list(reversed(values))
        for value in candidates:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _hko_row_matches(values, fields: list[str], target_date: str) -> bool:
    year_index = next((index for index, field in enumerate(fields) if "year" in field or field == "yyyy"), None)
    month_index = next((index for index, field in enumerate(fields) if "month" in field or field == "mm"), None)
    day_index = next((index for index, field in enumerate(fields) if "day" in field or field in {"dd", "date"}), None)
    if year_index is not None and month_index is not None and day_index is not None:
        year, month, day = target_date.split("-")
        return all(index < len(values) and str(values[index]).zfill(2 if index != year_index else 4) == expected for index, expected in ((year_index, year), (month_index, month), (day_index, day)))
    return _hko_date_matches(values[0], target_date)


def _hko_date_matches(value, target_date: str) -> bool:
    text = str(value).strip()
    year, month, day = target_date.split("-")
    normalized = text.replace("/", "-")
    if normalized == target_date or normalized.endswith(f"-{month}-{day}"):
        return True
    if text in {day, str(int(day))}:
        return True
    return text in {f"{day}/{month}", f"{month}/{day}", f"{day}-{month}", f"{month}-{day}"}


def _fetch_nws(rule: SettlementRule) -> SettlementSourceResult:
    stations = [item.strip().upper() for item in rule.target_station_or_data_source.replace("|", ",").split(",") if item.strip()]
    if not stations or any(not station.startswith("K") for station in stations):
        return SettlementSourceResult("unavailable", rule.settlement_source, rule.target_station_or_data_source, rule.date, None, None, rule.measurement_unit, "", "NWS station identifier is required")
    all_values = []
    observed_at = ""
    for station in stations:
        try:
            payload = get_json(f"{NWS_API}/stations/{station}/observations", {"start": f"{rule.date}T00:00:00+00:00", "end": f"{rule.date}T23:59:59+00:00"})
        except RuntimeError as exc:
            return SettlementSourceResult("unavailable", rule.settlement_source, ",".join(stations), rule.date, None, None, "C", "", f"NWS {station} request failed: {exc}")
        values = []
        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            value = ((properties.get("temperature") or {}).get("value"))
            if value is not None:
                values.append(float(value))
                observed_at = str(properties.get("timestamp") or observed_at)
        if not values:
            return SettlementSourceResult("unavailable", rule.settlement_source, ",".join(stations), rule.date, None, None, "C", "", f"official NWS observations unavailable for {station}")
        all_values.extend(values)
    return SettlementSourceResult("available", rule.settlement_source, ",".join(stations), rule.date, max(all_values), min(all_values), "C", observed_at, "official NWS observations; all requested stations returned data")
