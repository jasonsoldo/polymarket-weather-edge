from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ValidationResult:
    validation_days: int
    exact_match_rate: float
    one_degree_difference_rate: float
    missing_rate: float
    page_availability_rate: float
    revision_rate: float
    average_finalize_delay: float
    verified: bool

    def to_dict(self): return asdict(self)


def validate_history(rows, min_days=30, min_exact_match_rate=0.9, max_missing_rate=0.1):
    rows = list(rows)
    total = len(rows) or 1
    comparable = [r for r in rows if r.get("api_high") is not None and r.get("page_high") is not None and r.get("station_match", True) and r.get("date_match", True)]
    exact = sum(abs(r["api_high"] - r["page_high"]) < 0.11 for r in comparable)
    one_degree = sum(abs(r["api_high"] - r["page_high"]) <= 1.01 for r in comparable)
    missing = sum(r.get("api_high") is None or r.get("page_high") is None or not r.get("station_match", True) or not r.get("date_match", True) for r in rows)
    page_available = sum(r.get("page_high") is not None for r in rows)
    revisions = sum(bool(r.get("revision")) for r in rows)
    exact_rate = exact / len(comparable) if comparable else 0.0
    missing_rate = missing / total
    result = ValidationResult(len(rows), exact_rate, one_degree / len(comparable) if comparable else 0.0, missing_rate, page_available / total, revisions / total, sum(float(r.get("finalize_delay", 0)) for r in rows) / total, False)
    return ValidationResult(**{**result.to_dict(), "verified": len(rows) >= min_days and exact_rate >= min_exact_match_rate and missing_rate <= max_missing_rate})


def save_validation_state(path, station, result):
    import json
    from pathlib import Path
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    payload[station.upper()] = result.to_dict()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
