import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .http_client import get_json


GAMMA_API = "https://gamma-api.polymarket.com"
MAX_KEYSET_LIMIT = 100
WEATHER_TAG_SLUGS = ("weather",)
WEATHER_TAG_NAMES = ("weather",)
WEATHER_PATTERNS = (
    r"\bweather\b",
    r"\btemperature\b",
    r"\bhigh temp\b",
    r"\blow temp\b",
    r"\bdegrees?\b",
    r"\bfahrenheit\b",
    r"\bcelsius\b",
    r"\brain\b",
    r"\bsnow\b",
)


@dataclass(frozen=True)
class GammaTag:
    id: str
    label: str
    slug: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WeatherMarket:
    event_id: str
    event_slug: str
    event_title: str
    market_id: str
    condition_id: str
    market_slug: str
    question: str
    description: str
    end_date: str
    active: bool
    closed: bool
    outcomes: tuple[str, ...]
    outcome_prices: tuple[float, ...]
    token_ids: tuple[str, ...]
    resolution_source: str
    tags: tuple[str, ...]
    city_guess: str
    discovery_source: str

    def to_dict(self) -> dict:
        return asdict(self)


def discover_weather_tags() -> list[GammaTag]:
    tags = get_json(f"{GAMMA_API}/tags")
    if not isinstance(tags, list):
        raise RuntimeError("unexpected Gamma tags response")

    matches = []
    for tag in tags:
        parsed = GammaTag(
            id=str(tag.get("id") or ""),
            label=str(tag.get("label") or tag.get("name") or ""),
            slug=str(tag.get("slug") or ""),
        )
        label = parsed.label.lower()
        slug = parsed.slug.lower()
        if any(name in label for name in WEATHER_TAG_NAMES) or any(slug_name in slug for slug_name in WEATHER_TAG_SLUGS):
            matches.append(parsed)
    return matches


def fetch_weather_markets(
    limit: int = 100,
    city: str = "",
    tag_id: str = "",
    slug: str = "",
    query: str = "",
    pages: int = 3,
) -> list[WeatherMarket]:
    if slug:
        return [
            market
            for market in fetch_markets_by_slug(slug)
            if _is_weather_market(market, city, allow_query=query)
        ][:limit]

    discovered_tag_id = tag_id or _first_weather_tag_id()
    markets = []
    if discovered_tag_id:
        markets.extend(
            _iter_event_markets(
                pages=pages,
                limit=min(limit, MAX_KEYSET_LIMIT),
                tag_id=discovered_tag_id,
                discovery_source=f"events_keyset_tag_{discovered_tag_id}",
            )
        )

    if len(markets) < limit:
        markets.extend(
            _iter_event_markets(
                pages=pages,
                limit=min(limit, MAX_KEYSET_LIMIT),
                tag_id="",
                discovery_source="events_keyset_text_filter",
            )
        )

    filtered = []
    seen = set()
    for market in markets:
        if market.market_id in seen:
            continue
        seen.add(market.market_id)
        if _is_weather_market(market, city, allow_query=query):
            filtered.append(market)
        if len(filtered) >= limit:
            break
    return filtered


def fetch_markets_by_slug(slug: str) -> list[WeatherMarket]:
    events = get_json(f"{GAMMA_API}/events/slug/{slug}")
    if isinstance(events, dict):
        event_list = [events]
    elif isinstance(events, list):
        event_list = events
    else:
        event_list = []

    markets = []
    for event in event_list:
        for market in event.get("markets") or []:
            parsed = _parse_market(event, market, "event_slug")
            if parsed:
                markets.append(parsed)
    if markets:
        return markets

    market = get_json(f"{GAMMA_API}/markets/slug/{slug}")
    if isinstance(market, dict):
        parsed = _parse_market({}, market, "market_slug")
        return [parsed] if parsed else []
    return []


def _iter_event_markets(
    pages: int,
    limit: int,
    tag_id: str,
    discovery_source: str,
) -> list[WeatherMarket]:
    markets = []
    cursor = ""
    for _page in range(max(1, pages)):
        params = {
            "active": "true",
            "closed": "false",
            "limit": max(1, min(limit, MAX_KEYSET_LIMIT)),
        }
        if cursor:
            params["after_cursor"] = cursor
        if tag_id:
            params["tag_id"] = tag_id
            params["related_tags"] = "true"

        response = get_json(f"{GAMMA_API}/events/keyset", params)
        if isinstance(response, dict):
            events = response.get("events") or response.get("data") or []
            cursor = str(response.get("next_cursor") or "")
        elif isinstance(response, list):
            events = response
            cursor = ""
        else:
            raise RuntimeError("unexpected Gamma events keyset response")

        for event in events:
            for market in event.get("markets") or []:
                parsed = _parse_market(event, market, discovery_source)
                if parsed:
                    markets.append(parsed)
        if not cursor:
            break
    return markets


def _parse_market(event: dict[str, Any], market: dict[str, Any], discovery_source: str) -> Optional[WeatherMarket]:
    outcomes = tuple(str(item) for item in _jsonish_list(market.get("outcomes")))
    prices = tuple(_to_float(item) for item in _jsonish_list(market.get("outcomePrices")))
    token_ids = tuple(str(item) for item in _jsonish_list(market.get("clobTokenIds")))
    if not outcomes:
        return None

    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    return WeatherMarket(
        event_id=str(event.get("id") or market.get("eventId") or ""),
        event_slug=str(event.get("slug") or ""),
        event_title=str(event.get("title") or event.get("question") or ""),
        market_id=str(market.get("id") or condition_id),
        condition_id=condition_id,
        market_slug=str(market.get("slug") or ""),
        question=str(market.get("question") or ""),
        description=str(market.get("description") or event.get("description") or ""),
        end_date=str(market.get("endDate") or event.get("endDate") or ""),
        active=bool(market.get("active", event.get("active", False))),
        closed=bool(market.get("closed", event.get("closed", False))),
        outcomes=outcomes,
        outcome_prices=prices,
        token_ids=token_ids,
        resolution_source=str(market.get("resolutionSource") or event.get("resolutionSource") or ""),
        tags=tuple(_tag_names(event, market)),
        city_guess=_guess_city(event, market),
        discovery_source=discovery_source,
    )


def _first_weather_tag_id() -> str:
    try:
        tags = discover_weather_tags()
    except RuntimeError:
        return ""
    return tags[0].id if tags else ""


def _is_weather_market(market: WeatherMarket, city: str, allow_query: str = "") -> bool:
    if not market.active or market.closed:
        return False
    haystack = " ".join(
        [
            market.event_title,
            market.question,
            market.description,
            market.event_slug,
            market.market_slug,
            " ".join(market.tags),
        ]
    ).lower()
    if city and city.lower() not in haystack:
        return False
    if allow_query and allow_query.lower() not in haystack:
        return False
    return any(re.search(pattern, haystack) for pattern in WEATHER_PATTERNS)


def _guess_city(event: dict[str, Any], market: dict[str, Any]) -> str:
    text = str(market.get("question") or event.get("title") or "")
    for prefix in (" in ", " for "):
        if prefix in text:
            return text.split(prefix, 1)[1].split("?")[0].split(" on ")[0].strip()
    return ""


def _tag_names(event: dict[str, Any], market: dict[str, Any]) -> list[str]:
    raw_tags = []
    for source in (event, market):
        raw_tags.extend(source.get("tags") or [])
    names = []
    for tag in raw_tags:
        if isinstance(tag, dict):
            names.append(str(tag.get("label") or tag.get("name") or tag.get("slug") or ""))
        else:
            names.append(str(tag))
    return [name for name in names if name]


def _jsonish_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
