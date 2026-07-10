import json
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
        aliases = [item.get("name", ""), *item.get("aliases", [])]
        for alias in aliases:
            if alias and alias.lower() in haystack:
                return item, alias
    return None, ""
