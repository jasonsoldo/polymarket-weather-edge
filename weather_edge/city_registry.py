import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).parent.parent / "config" / "cities.json"

def load_city_registry(path=REGISTRY_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if item.get("enabled", True)] if isinstance(data, list) else []

def match_city(text, registry=None):
    haystack = (text or "").lower()
    for item in registry or load_city_registry():
        aliases = sorted([item.get("name", ""), *item.get("aliases", [])], key=len, reverse=True)
        for alias in aliases:
            if alias and re.search(r"(?<![a-z0-9])" + re.escape(alias.lower()) + r"(?![a-z0-9])", haystack):
                return item, alias
    return None, ""
