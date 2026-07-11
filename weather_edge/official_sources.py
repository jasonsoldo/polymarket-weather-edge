"""Strict, configurable adapters for rule-specified official sources.

The adapter never substitutes a different provider.  A market is accepted only
when the response contains the requested date and station (when supplied).
"""

import os
from dataclasses import asdict, dataclass
from typing import Optional

from .http_client import get_json


@dataclass(frozen=True)
class OfficialObservation:
    provider: str
    station: str
    target_date: str
    daily_high: Optional[float]
    daily_low: Optional[float]
    unit: str
    observed_at: str
    status: str
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_configured_official(
    provider: str,
    station: str,
    target_date: str,
    unit: str,
    endpoint: str = "",
    api_key: str = "",
) -> OfficialObservation:
    prefix = provider.upper().replace(" ", "")
    endpoint = endpoint or os.getenv(f"{prefix}_SETTLEMENT_URL", "")
    api_key = api_key or os.getenv(f"{prefix}_API_KEY", "")
    if not endpoint or not api_key:
        return OfficialObservation(provider, station, target_date, None, None, unit, "", "pending", "official endpoint and API key are required")
    endpoint = endpoint.replace("{date}", target_date).replace("{station}", station)
    params = {"station": station, "date": target_date, "target_date": target_date}
    headers = {"User-Agent": "WeatherEdge/1.0"}
    if prefix == "METOFFICE":
        headers["apikey"] = api_key
    else:
        params["apiKey"] = api_key
    try:
        payload = get_json(endpoint, params, headers=headers)
        high, low, observed_at, response_date, response_station, response_unit = extract_observation(payload)
    except (RuntimeError, TypeError, ValueError) as exc:
        return OfficialObservation(provider, station, target_date, None, None, unit, "", "unavailable", str(exc))
    if response_date and not str(response_date).startswith(target_date):
        return OfficialObservation(provider, station, target_date, None, None, unit, str(observed_at or ""), "source_mismatch", "response date does not match target date")
    if response_station and station and str(response_station).upper() != station.upper():
        return OfficialObservation(provider, station, target_date, None, None, unit, str(observed_at or ""), "source_mismatch", "response station does not match target station")
    if response_unit and _unit(response_unit) != _unit(unit):
        return OfficialObservation(provider, station, target_date, None, None, unit, str(observed_at or ""), "source_mismatch", "response unit does not match requested unit")
    if high is None and low is None:
        return OfficialObservation(provider, station, target_date, None, None, unit, str(observed_at or ""), "unavailable", "response contains no daily temperature")
    return OfficialObservation(provider, station, target_date, high, low, unit, str(observed_at or target_date), "available", "")


def extract_observation(payload: dict) -> tuple[Optional[float], Optional[float], str, str, str]:
    high = low = None
    observed_at = response_date = response_station = response_unit = ""

    def visit(value):
        nonlocal high, low, observed_at, response_date, response_station, response_unit
        if isinstance(value, dict):
            lower = {str(key).lower(): item for key, item in value.items()}
            for key, item in lower.items():
                text = str(item)
                if not response_date and (key in {"date", "target_date", "forecastdate", "observationdate"} or key.endswith("date")):
                    response_date = text
                if not response_station and key in {"station", "station_id", "stationid", "icao", "stationcode"}:
                    response_station = text
                if not response_unit and key in {"unit", "units", "temperature_unit"}:
                    response_unit = text
                if not observed_at and ("updated" in key or "observed" in key or key in {"timestamp", "time"}):
                    observed_at = text
                if isinstance(item, (int, float, str)):
                    try:
                        number = float(item)
                    except (TypeError, ValueError):
                        continue
                    if any(token in key for token in ("maxt", "max_temp", "maximum", "daily_high", "high_temp")):
                        high = number if high is None else max(high, number)
                    if any(token in key for token in ("mint", "min_temp", "minimum", "daily_low", "low_temp")):
                        low = number if low is None else min(low, number)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return high, low, observed_at, response_date, response_station, response_unit


def _unit(value: str) -> str:
    text = str(value).upper().replace("°", "")
    return "F" if text.startswith("F") else "C" if text.startswith("C") else text
