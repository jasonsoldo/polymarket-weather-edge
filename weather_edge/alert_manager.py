import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def emit_alerts(snapshot: dict, output_path: str, webhook_env: str = "WEATHER_EDGE_ALERT_WEBHOOK") -> list[dict]:
    alerts = _alerts(snapshot)
    if not alerts:
        return []
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for alert in alerts:
            handle.write(json.dumps(alert, sort_keys=True) + "\n")
    webhook = os.environ.get(webhook_env, "")
    if webhook:
        for alert in alerts:
            _post_with_retry(webhook, alert)
    return alerts


def _alerts(snapshot: dict) -> list[dict]:
    events = []
    if snapshot.get("recommended_action") == "NO_TRADE":
        events.append(_alert("NO_TRADE", snapshot.get("risk_reasons", []), snapshot))
    for city in snapshot.get("cities", [snapshot]):
        for market in city.get("markets", []):
            plan = market.get("event_bucket_plan") or {}
            decision = plan.get("decision") or {}
            if decision.get("allowed") is False:
                events.append(_alert("TRADE_BLOCKED", decision.get("reasons", []), city, market.get("event_slug", "")))
            observation = market.get("settlement_observation") or {}
            if observation.get("status") in {"unsupported_no_official_api", "unavailable"}:
                events.append(_alert("SETTLEMENT_SOURCE", [observation.get("status", "")], city, market.get("event_slug", "")))
    return events


def _alert(kind: str, reasons, snapshot: dict, event_slug: str = "") -> dict:
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "city": snapshot.get("city", ""),
        "event_slug": event_slug,
        "reasons": list(reasons),
    }


def _post_with_retry(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    last_error = None
    attempts = max(1, int(os.environ.get("WEATHER_EDGE_ALERT_RETRIES", "3")))
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=10):
                return
        except OSError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"alert webhook failed: {last_error}")
