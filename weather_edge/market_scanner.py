import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Optional

from .http_client import get_json
from .city_registry import load_city_registry, match_city


GAMMA_API = "https://gamma-api.polymarket.com"
MAX_KEYSET_LIMIT = 100
WEATHER_TAG_SLUGS = ("weather",)
WEATHER_TAG_NAMES = ("weather",)
TEMPERATURE_SEARCH_QUERIES = ("temperature",)
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
STRICT_TEMPERATURE_KEYWORDS = (
    "temperature",
    "high temperature",
    "low temperature",
    "highest temperature",
    "lowest temperature",
    "hottest",
    "coldest",
    "degrees",
    "°f",
    "°c",
    "daily high",
    "daily low",
    "what will the high be",
    "what will the low be",
)
EXCLUDED_BROAD_MARKET_KEYWORDS = (
    "global temperature index",
    "hottest year on record",
    "arctic sea ice",
    "sea ice extent",
    "measles",
    "earthquake",
    "government shutdown",
    "climate change",
    "heat wave",
    "politics",
    "election",
    "pandemic",
    "disease",
)
BROAD_WEATHER_ALLOWED_KEYWORDS = (
    "global temperature index",
    "hottest year on record",
    "arctic sea ice",
    "sea ice extent",
    "climate change",
    "earthquake",
)
ALWAYS_EXCLUDED_KEYWORDS = (
    "measles",
    "government shutdown",
    "politics",
    "election",
    "pandemic",
    "disease",
)
CITY_ALIASES = {
    "new york": ("new york", "nyc", "manhattan", "central park", "knyc", "lga", "jfk"),
    "chicago": ("chicago", "ord", "mdw", "kord", "midway"),
    "austin": ("austin", "kaus"),
    "miami": ("miami", "kmia"),
    "los angeles": ("los angeles", "la ", "lax", "klax", "downtown los angeles"),
    "hong kong": ("hong kong", "hko", "hong kong observatory"),
}
LAST_SCAN_STATS = {}


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
    is_temperature_market: bool
    excluded_reason: str
    matched_keywords: tuple[str, ...]
    city_match_score: int
    market_type_guess: str
    discovered_city: str = ""
    normalized_city: str = ""
    matched_alias: str = ""
    station_code: str = ""
    city_registry_status: str = "discovered_unregistered"
    discovery_confidence: float = 0.0

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
    include_broad_weather: bool = False,
    max_pages: int = 5,
    scan_all_pages: bool = False,
) -> list[WeatherMarket]:
    global LAST_SCAN_STATS
    LAST_SCAN_STATS = {"markets_scanned": 0, "pages_scanned": 0, "excluded_markets": 0, "scan_completed": False}
    page_limit = min(max_pages, 100) if scan_all_pages else max(1, pages)
    if slug:
        return [
            _with_filter_metadata(market, city)
            for market in fetch_markets_by_slug(slug)
            if _include_market(market, city, query, include_broad_weather)
        ][:limit]

    markets = []
    for search_query in _search_queries(city, query):
        markets.extend(_iter_public_search_markets(search_query, pages=page_limit, limit=min(limit, MAX_KEYSET_LIMIT)))

    discovered_tag_id = tag_id or _first_weather_tag_id()
    if discovered_tag_id:
        markets.extend(
            _iter_event_markets(
                pages=page_limit,
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
    if len(markets) < limit:
        markets.extend(_iter_offset_event_markets(pages=page_limit, limit=min(limit, MAX_KEYSET_LIMIT)))

    filtered = []
    seen = set()
    LAST_SCAN_STATS["markets_scanned"] = len(markets)
    LAST_SCAN_STATS["pages_scanned"] = page_limit
    for market in markets:
        key = (market.condition_id or market.event_id, market.market_id)
        if key in seen:
            continue
        seen.add(key)
        if _include_market(market, city, query, include_broad_weather):
            filtered.append(_with_filter_metadata(market, city))
        else:
            LAST_SCAN_STATS["excluded_markets"] += 1
        if len(filtered) >= limit:
            break
    LAST_SCAN_STATS["scan_completed"] = True
    return filtered

def get_last_scan_stats():
    return dict(LAST_SCAN_STATS)


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


def _iter_offset_event_markets(pages: int, limit: int) -> list[WeatherMarket]:
    markets = []
    for page in range(max(1, pages)):
        try:
            response = get_json(
                f"{GAMMA_API}/events",
                {
                    "active": "true",
                    "closed": "false",
                    "limit": max(1, min(limit, MAX_KEYSET_LIMIT)),
                    "offset": page * max(1, min(limit, MAX_KEYSET_LIMIT)),
                },
            )
        except RuntimeError:
            break
        events = response if isinstance(response, list) else []
        for event in events:
            for market in event.get("markets") or []:
                parsed = _parse_market(event, market, "events_offset")
                if parsed:
                    markets.append(parsed)
        if len(events) < limit:
            break
    return markets


def _iter_public_search_markets(query: str, pages: int, limit: int) -> list[WeatherMarket]:
    markets = []
    for page in range(1, max(1, pages) + 1):
        try:
            response = get_json(
                f"{GAMMA_API}/public-search",
                {
                    "q": query,
                    "events_status": "active",
                    "limit_per_type": max(1, min(limit, MAX_KEYSET_LIMIT)),
                    "page": page,
                },
            )
        except RuntimeError:
            break
        events = response.get("events") if isinstance(response, dict) else []
        if not events:
            break
        for event in events:
            for market in event.get("markets") or []:
                parsed = _parse_market(event, market, f"public_search:{query}")
                if parsed:
                    markets.append(parsed)
    return markets


def _parse_market(event: dict[str, Any], market: dict[str, Any], discovery_source: str) -> Optional[WeatherMarket]:
    outcomes = tuple(str(item) for item in _jsonish_list(market.get("outcomes")))
    prices = tuple(_to_float(item) for item in _jsonish_list(market.get("outcomePrices")))
    token_ids = tuple(str(item) for item in _jsonish_list(market.get("clobTokenIds")))
    if not outcomes:
        return None

    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    base = {
        "event_title": str(event.get("title") or event.get("question") or ""),
        "question": str(market.get("question") or ""),
        "description": str(market.get("description") or event.get("description") or ""),
        "event_slug": str(event.get("slug") or ""),
        "market_slug": str(market.get("slug") or ""),
        "tags": tuple(_tag_names(event, market)),
    }
    analysis = _analyze_market_text(base, "")
    discovered_city, alias = _discover_city(base, event, market)
    registry, _ = match_city(" ".join((discovered_city, alias)), load_city_registry())
    station = _station_code(base, event, market)
    return WeatherMarket(
        event_id=str(event.get("id") or market.get("eventId") or ""),
        event_slug=base["event_slug"],
        event_title=base["event_title"],
        market_id=str(market.get("id") or condition_id),
        condition_id=condition_id,
        market_slug=base["market_slug"],
        question=base["question"],
        description=base["description"],
        end_date=str(market.get("endDate") or event.get("endDate") or ""),
        active=bool(market.get("active", event.get("active", False))),
        closed=bool(market.get("closed", event.get("closed", False))),
        outcomes=outcomes,
        outcome_prices=prices,
        token_ids=token_ids,
        resolution_source=str(market.get("resolutionSource") or event.get("resolutionSource") or ""),
        tags=base["tags"],
        city_guess=_guess_city(event, market),
        discovery_source=discovery_source,
        is_temperature_market=analysis["is_temperature_market"],
        excluded_reason=analysis["excluded_reason"],
        matched_keywords=tuple(analysis["matched_keywords"]),
        city_match_score=analysis["city_match_score"],
        market_type_guess=analysis["market_type_guess"],
        discovered_city=discovered_city,
        normalized_city=registry.get("name", discovered_city) if registry else discovered_city,
        matched_alias=alias,
        station_code=station,
        city_registry_status="registered" if registry else "discovered_unregistered",
        discovery_confidence=1.0 if registry else (0.75 if discovered_city else 0.0),
    )


def _first_weather_tag_id() -> str:
    try:
        tags = discover_weather_tags()
    except RuntimeError:
        return ""
    return tags[0].id if tags else ""


def _include_market(market: WeatherMarket, city: str, query: str, include_broad_weather: bool) -> bool:
    if not market.active or market.closed:
        return False
    analysis = _analyze_market_text(
        {
            "event_title": market.event_title,
            "question": market.question,
            "description": market.description,
            "event_slug": market.event_slug,
            "market_slug": market.market_slug,
            "tags": market.tags,
        },
        city,
    )
    if query and query.lower() not in _market_haystack(market):
        return False
    if include_broad_weather:
        return _is_broad_weather_market(market)
    return analysis["is_temperature_market"] and not analysis["excluded_reason"] and (not city or analysis["city_match_score"] > 0)


def _with_filter_metadata(market: WeatherMarket, city: str) -> WeatherMarket:
    analysis = _analyze_market_text(
        {
            "event_title": market.event_title,
            "question": market.question,
            "description": market.description,
            "event_slug": market.event_slug,
            "market_slug": market.market_slug,
            "tags": market.tags,
        },
        city,
    )
    return replace(
        market,
        is_temperature_market=analysis["is_temperature_market"],
        excluded_reason=analysis["excluded_reason"],
        matched_keywords=tuple(analysis["matched_keywords"]),
        city_match_score=analysis["city_match_score"],
        market_type_guess=analysis["market_type_guess"],
    )


def _is_broad_weather_market(market: WeatherMarket) -> bool:
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
    if any(keyword in haystack for keyword in ALWAYS_EXCLUDED_KEYWORDS):
        return False
    return any(re.search(pattern, haystack) for pattern in WEATHER_PATTERNS) or any(
        keyword in haystack for keyword in BROAD_WEATHER_ALLOWED_KEYWORDS
    )


def _analyze_market_text(parts: dict, city: str) -> dict:
    haystack = _parts_haystack(parts)
    matched = [keyword for keyword in STRICT_TEMPERATURE_KEYWORDS if keyword in haystack]
    excluded = next((keyword for keyword in EXCLUDED_BROAD_MARKET_KEYWORDS if keyword in haystack), "")
    city_score = _city_match_score(haystack, city)
    market_type = _market_type_guess(haystack, tuple(parts.get("tags") or ()))
    is_temperature = bool(matched) and market_type != "non_temperature"
    return {
        "is_temperature_market": is_temperature,
        "excluded_reason": excluded,
        "matched_keywords": matched,
        "city_match_score": city_score,
        "market_type_guess": market_type,
    }


def _market_haystack(market: WeatherMarket) -> str:
    return _parts_haystack(
        {
            "event_title": market.event_title,
            "question": market.question,
            "description": market.description,
            "event_slug": market.event_slug,
            "market_slug": market.market_slug,
            "tags": market.tags,
        }
    )


def _parts_haystack(parts: dict) -> str:
    return " ".join(
        [
            str(parts.get("event_title") or ""),
            str(parts.get("question") or ""),
            str(parts.get("description") or ""),
            str(parts.get("event_slug") or ""),
            str(parts.get("market_slug") or ""),
            " ".join(str(tag) for tag in parts.get("tags") or ()),
        ]
    ).lower()


def _city_match_score(haystack: str, city: str) -> int:
    if not city:
        return 0
    aliases = CITY_ALIASES.get(city.lower(), (city.lower(),))
    score = 0
    for alias in aliases:
        if alias.strip() and alias in haystack:
            score += 2 if alias == city.lower() else 1
    return score


def _market_type_guess(haystack: str, tags: tuple[str, ...]) -> str:
    if any(keyword in haystack for keyword in EXCLUDED_BROAD_MARKET_KEYWORDS):
        return "non_temperature"
    if (
        "low temperature" in haystack
        or "lowest temperature" in haystack
        or "daily low" in haystack
        or "what will the low be" in haystack
        or "coldest" in haystack
    ):
        return "low_temp"
    if (
        "high temperature" in haystack
        or "highest temperature" in haystack
        or "daily high" in haystack
        or "what will the high be" in haystack
        or "hottest" in haystack
    ):
        return "high_temp"
    if "temperature" in haystack or "degrees" in haystack or "°f" in haystack or "°c" in haystack:
        if "range" in haystack or "-" in haystack:
            return "range_bucket"
        return "exact_bucket"
    return "non_temperature"


def _guess_city(event: dict[str, Any], market: dict[str, Any]) -> str:
    text = str(event.get("title") or market.get("question") or "")
    for prefix in (" in ", " for "):
        index = text.lower().find(prefix)
        if index >= 0:
            city = text[index + len(prefix) :]
            city = re.split(r"\s+(?:on|by|be|will|before|after)\b|\?", city, maxsplit=1, flags=re.IGNORECASE)[0]
            return _clean_city_name(city)
    return ""


def _clean_city_name(city: str) -> str:
    cleaned = re.sub(r"\s+(?:China|中国|UK|United Kingdom|Japan|Korea|Taiwan|Hong Kong)$", "", city.strip(), flags=re.IGNORECASE)
    return cleaned.strip(" ,-/")

def _discover_city(parts, event, market):
    registry = load_city_registry()
    guessed = _guess_city(event, market)
    item, alias = match_city(guessed, registry)
    if item:
        return item["name"], alias
    item, alias = match_city(_parts_haystack(parts), registry)
    if item:
        return item["name"], alias
    return guessed, guessed

def _station_code(parts, event, market):
    text = " ".join(str(parts.get(k) or "") for k in ("event_title", "question", "description", "event_slug", "market_slug"))
    codes = re.findall(r"\b[A-Z]{3,5}\b", text)
    known = {code for item in load_city_registry() for code in item.get("candidate_stations", [])}
    return next((code for code in codes if code in known), "")


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


def _search_queries(city: str, query: str) -> tuple[str, ...]:
    if query:
        return (query,)
    if city:
        aliases = CITY_ALIASES.get(city.lower(), (city.lower(),))
        queries = [f"{city} temperature"]
        queries.extend(f"{alias} temperature" for alias in aliases[:3] if alias.strip())
        return tuple(dict.fromkeys(queries))
    queries = list(TEMPERATURE_SEARCH_QUERIES)
    return tuple(dict.fromkeys(queries))
