import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL, city TEXT NOT NULL, target_date TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL, city TEXT NOT NULL, target_date TEXT NOT NULL,
    source TEXT NOT NULL, max_temp REAL, min_temp REAL, unit TEXT, updated_at TEXT,
    model TEXT, station_or_grid TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL, city TEXT NOT NULL, target_date TEXT NOT NULL,
    event_id TEXT, event_slug TEXT, market_id TEXT, condition_id TEXT, market_slug TEXT,
    question TEXT, end_date TEXT, outcome_prices_json TEXT NOT NULL, token_ids_json TEXT NOT NULL,
    settlement_source TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bucket_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL, city TEXT NOT NULL, target_date TEXT NOT NULL,
    event_id TEXT, event_slug TEXT, bucket TEXT, price REAL, model_probability REAL,
    edge REAL, liquidity REAL, spread REAL, current_position REAL, pnl_if_wins REAL
);
CREATE TABLE IF NOT EXISTS settlement_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL, city TEXT NOT NULL, target_date TEXT NOT NULL,
    source TEXT NOT NULL, station TEXT, max_temp REAL, min_temp REAL, unit TEXT,
    status TEXT NOT NULL, reason TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hko_realtime_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL, target_date TEXT NOT NULL, observation_time TEXT,
    current_temp REAL, max_temp_since_midnight REAL, min_temp_since_midnight REAL,
    unit TEXT, healthy INTEGER NOT NULL, is_final INTEGER NOT NULL,
    raw_payload_hash TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_decisions (
    decision_id TEXT PRIMARY KEY, decision_time TEXT NOT NULL,
    event_id TEXT NOT NULL, event_slug TEXT NOT NULL, target_date TEXT NOT NULL,
    question TEXT NOT NULL, weather_confidence REAL, data_disagreement REAL,
    planned_size REAL NOT NULL, planned_cost REAL NOT NULL,
    expected_best_pnl REAL, maximum_loss REAL, recommended_action TEXT NOT NULL,
    block_reason TEXT, payload_json TEXT NOT NULL,
    final_market_result TEXT, hypothetical_realized_pnl REAL, finalized_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_target ON monitor_snapshots(target_date, observed_at);
CREATE INDEX IF NOT EXISTS idx_forecast_lookup ON forecast_observations(city, target_date, source, observed_at);
CREATE INDEX IF NOT EXISTS idx_market_lookup ON market_observations(event_id, market_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_bucket_lookup ON bucket_observations(event_id, bucket, observed_at);
CREATE INDEX IF NOT EXISTS idx_settlement_lookup ON settlement_observations(city, target_date, source, recorded_at);
"""


def save_monitor_snapshot(path: str, snapshot: dict) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO monitor_snapshots (observed_at, city, target_date, payload_json) VALUES (?, ?, ?, ?)",
            (snapshot.get("observed_at", ""), snapshot.get("city", snapshot.get("mode", "")), snapshot.get("target_date", ""), json.dumps(snapshot, sort_keys=True)),
        )
        for city_snapshot in _city_snapshots(snapshot):
            _save_city_snapshot(conn, city_snapshot, snapshot.get("observed_at", ""))


def save_settlement_observation(path: str, city: str, target_date: str, observation: dict, recorded_at: str = "") -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        _insert_settlement(conn, recorded_at or observation.get("observed_at", target_date), city, target_date, observation)


def history_summary(path: str) -> dict:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        names = ("monitor_snapshots", "forecast_observations", "market_observations", "bucket_observations", "settlement_observations", "hko_realtime_observations", "shadow_decisions")
        return {name: int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in names}


def calibration_summary(path: str) -> list[dict]:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            """
            SELECT f.city, f.source, COUNT(*) AS samples,
                   AVG(f.max_temp - s.max_temp) AS high_bias,
                   AVG(ABS(f.max_temp - s.max_temp)) AS high_mae,
                   AVG(f.min_temp - s.min_temp) AS low_bias,
                   AVG(ABS(f.min_temp - s.min_temp)) AS low_mae
            FROM forecast_observations f
            JOIN settlement_observations s
              ON s.city = f.city AND s.target_date = f.target_date
            WHERE f.max_temp IS NOT NULL AND f.min_temp IS NOT NULL
              AND s.max_temp IS NOT NULL AND s.min_temp IS NOT NULL
              AND s.status = 'available'
            GROUP BY f.city, f.source
            ORDER BY samples DESC, f.city, f.source
            """
        ).fetchall()
    keys = ("city", "source", "samples", "high_bias", "high_mae", "low_bias", "low_mae")
    return [dict(zip(keys, row)) for row in rows]


def snapshot_count(path: str) -> int:
    return history_summary(path)["monitor_snapshots"]


def _city_snapshots(snapshot: dict) -> list[dict]:
    return snapshot.get("cities") if snapshot.get("mode") == "all_cities" else [snapshot]


def _save_city_snapshot(conn, snapshot: dict, fallback_observed_at: str) -> None:
    observed_at = snapshot.get("observed_at", fallback_observed_at)
    city, target_date = snapshot.get("city", ""), snapshot.get("target_date", "")
    hko = (snapshot.get("weather") or {}).get("hko_observation")
    if city == "Hong Kong" and hko:
        conn.execute(
            "INSERT INTO hko_realtime_observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (observed_at, target_date, hko.get("observation_time", ""), hko.get("current_temp"), hko.get("max_temp_since_midnight"), hko.get("min_temp_since_midnight"), hko.get("unit", ""), int(bool(hko.get("healthy"))), int(bool(hko.get("is_final"))), hko.get("raw_payload_hash", ""), json.dumps(hko, sort_keys=True)),
        )
    for forecast in (snapshot.get("weather") or {}).get("forecasts") or []:
        conn.execute(
            "INSERT INTO forecast_observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (observed_at, city, target_date, forecast.get("source", ""), forecast.get("max_temp"), forecast.get("min_temp"), forecast.get("unit", ""), forecast.get("updated_at", ""), forecast.get("model", ""), forecast.get("station_or_grid", ""), json.dumps(forecast, sort_keys=True)),
        )
    for event in snapshot.get("markets") or []:
        plan = event.get("event_bucket_plan") or {}
        for market in event.get("markets") or []:
            conn.execute(
                "INSERT INTO market_observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (observed_at, city, target_date, event.get("event_id", ""), event.get("event_slug", ""), market.get("market_id", ""), market.get("condition_id", ""), market.get("market_slug", ""), market.get("question", ""), market.get("end_date", ""), json.dumps(market.get("outcome_prices", [])), json.dumps(market.get("token_ids", [])), market.get("resolution_source", ""), json.dumps(market, sort_keys=True)),
            )
        for bucket in (plan.get("curve") or {}).get("rows") or []:
            conn.execute(
                "INSERT INTO bucket_observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (observed_at, city, target_date, event.get("event_id", ""), event.get("event_slug", ""), bucket.get("bucket", ""), bucket.get("price"), bucket.get("model_probability"), bucket.get("edge"), bucket.get("liquidity"), bucket.get("spread"), bucket.get("current_position"), bucket.get("pnl_if_wins")),
            )
        if event.get("settlement_observation"):
            _insert_settlement(conn, observed_at, city, target_date, event["settlement_observation"])
        if city == "Hong Kong" and (plan.get("settlement_rule") or {}).get("market_type") in {"max_temp", "highest_temperature"}:
            _insert_shadow_decision(conn, observed_at, target_date, event, plan, snapshot.get("weather") or {})


def _insert_settlement(conn, recorded_at: str, city: str, target_date: str, observation: dict) -> None:
    conn.execute(
        "INSERT INTO settlement_observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (recorded_at, city, target_date, observation.get("source", observation.get("settlement_source", "")), observation.get("station", observation.get("target_station_or_data_source", "")), observation.get("max_temp", observation.get("daily_high")), observation.get("min_temp", observation.get("daily_low")), observation.get("unit", ""), observation.get("status", ""), observation.get("reason", ""), json.dumps(observation, sort_keys=True)),
    )


def _insert_shadow_decision(conn, observed_at: str, target_date: str, event: dict, plan: dict, weather: dict) -> None:
    decision = plan.get("decision") or {}
    candidate = plan.get("simulation_candidate") or {}
    orders = candidate.get("orders") or plan.get("orders") or []
    curve = candidate.get("curve") or plan.get("curve") or {}
    markets = event.get("markets") or []
    event_id = str(event.get("event_id") or plan.get("event_id") or event.get("event_slug") or "")
    decision_id = f"{observed_at}:{event_id}"
    planned_size = sum(float(order.get("size") or 0) for order in orders)
    planned_cost = sum(float(order.get("size") or 0) * float(order.get("price") or 0) for order in orders)
    reasons = decision.get("reasons") or []
    payload = {"event": event, "plan": plan, "weather": weather}
    conn.execute(
        "INSERT OR IGNORE INTO shadow_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
        (decision_id, observed_at, event_id, str(event.get("event_slug") or plan.get("event_slug") or ""), target_date, str((markets[0] if markets else {}).get("question") or ""), weather.get("confidence"), weather.get("disagreement"), planned_size, planned_cost, curve.get("best_case_pnl"), abs(float(curve.get("worst_case_pnl") or 0)), str(decision.get("recommended_action") or "NO_TRADE"), "; ".join(str(reason) for reason in reasons), json.dumps(payload, sort_keys=True)),
    )
