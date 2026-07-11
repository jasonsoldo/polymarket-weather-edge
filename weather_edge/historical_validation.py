"""Provider and settlement validation metrics used before a source is verified."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class ValidationSummary:
    validation_days: int
    exact_match_rate: float
    one_degree_difference_rate: float
    missing_rate: float
    page_availability_rate: float
    revision_rate: float
    average_finalize_delay: float
    resolved_bucket_match_rate: float
    verified: bool

    def to_dict(self) -> dict:
        return asdict(self)


def validate_history(
    rows: Iterable[dict],
    min_days: int = 30,
    min_exact_match_rate: float = 0.90,
    max_missing_rate: float = 0.10,
    min_bucket_match_rate: float = 0.90,
) -> ValidationSummary:
    records = list(rows)
    total = len(records) or 1
    comparable = [row for row in records if _comparable(row)]
    exact = sum(_difference(row) <= 0.11 for row in comparable)
    one_degree = sum(_difference(row) <= 1.01 for row in comparable)
    missing = sum(not _comparable(row) for row in records)
    page_available = sum(row.get("page_high") is not None or row.get("page_low") is not None for row in records)
    revisions = sum(bool(row.get("revision")) for row in records)
    bucket_rows = [row for row in records if row.get("resolved_bucket") and row.get("predicted_bucket")]
    bucket_matches = sum(row["resolved_bucket"] == row["predicted_bucket"] for row in bucket_rows)
    exact_rate = exact / len(comparable) if comparable else 0.0
    one_degree_rate = one_degree / len(comparable) if comparable else 0.0
    bucket_rate = bucket_matches / len(bucket_rows) if bucket_rows else 0.0
    missing_rate = missing / total
    result = ValidationSummary(
        len(records), exact_rate, one_degree_rate, missing_rate,
        page_available / total, revisions / total,
        sum(float(row.get("finalize_delay", 0) or 0) for row in records) / total,
        bucket_rate, False,
    )
    verified = (
        result.validation_days >= min_days
        and result.exact_match_rate >= min_exact_match_rate
        and result.missing_rate <= max_missing_rate
        and (not bucket_rows or result.resolved_bucket_match_rate >= min_bucket_match_rate)
    )
    return ValidationSummary(**{**result.to_dict(), "verified": verified})


def backfill_settlements(rows: Iterable[dict], fetcher: Callable[[dict], dict]) -> list[dict]:
    """Attach a settlement observation to saved market rows without overwriting raw data."""
    output = []
    for row in rows:
        result = fetcher(row)
        output.append({**row, "settlement_observation": result, "backfilled": True})
    return output


def load_jsonl(path: str) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _comparable(row: dict) -> bool:
    if row.get("settlement_comparable"):
        return row.get("api_high") is not None and row.get("api_low") is not None
    return (
        row.get("api_high") is not None
        and row.get("page_high") is not None
        and row.get("station_match", True)
        and row.get("date_match", True)
    )


def _difference(row: dict) -> float:
    if row.get("settlement_comparable"):
        return 0.0 if row.get("settlement_match") else 2.0
    differences = [abs(float(row["api_high"]) - float(row["page_high"]))]
    if row.get("api_low") is not None and row.get("page_low") is not None:
        differences.append(abs(float(row["api_low"]) - float(row["page_low"])))
    return max(differences)
