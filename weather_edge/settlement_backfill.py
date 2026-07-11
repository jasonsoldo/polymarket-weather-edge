"""Offline, auditable backfill of final Polymarket resolutions."""

import json
from pathlib import Path


def backfill_resolutions(rows: list[dict], resolutions: list[dict]) -> list[dict]:
    lookup = {
        str(item.get("condition_id") or item.get("market_id") or item.get("event_slug")): item
        for item in resolutions
    }
    output = []
    for row in rows:
        key = str(row.get("condition_id") or row.get("market_id") or row.get("event_slug"))
        resolution = lookup.get(key)
        if not resolution:
            output.append(row)
            continue
        output.append({
            **row,
            "resolved_bucket": resolution.get("resolved_bucket"),
            "resolved_outcome": resolution.get("resolved_outcome"),
            "resolved_at": resolution.get("resolved_at", ""),
            "resolution_source": resolution.get("resolution_source", "Polymarket"),
            "resolution_backfilled": True,
        })
    return output


def read_jsonl(path: str) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
