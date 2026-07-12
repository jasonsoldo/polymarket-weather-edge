"""Reconcile New York NWS daily values, Polymarket outcomes, and shadow PnL."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .history_store import save_settlement_observation
from .hko_finalizer import _finalize_shadow_decisions
from .nws_polymarket import closed_new_york_markets, compare_day
from .settlement_rules import SettlementRule
from .settlement_source import fetch_settlement_observation


SCHEMA = """
CREATE TABLE IF NOT EXISTS nws_market_resolutions (
    target_date TEXT NOT NULL, station TEXT NOT NULL, market_id TEXT NOT NULL,
    question TEXT NOT NULL, final_temperature REAL NOT NULL,
    expected_outcome TEXT, resolved_outcome TEXT, settlement_match INTEGER NOT NULL,
    resolved_at TEXT NOT NULL, raw_json TEXT NOT NULL,
    PRIMARY KEY (target_date, station, market_id)
);
"""


def yesterday_new_york() -> str:
    return (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()


def finalize_nws_day(target_date: str, history_db: str, station: str = "KLGA", pages: int = 5) -> dict:
    if target_date == "yesterday":
        target_date = yesterday_new_york()
    rule = SettlementRule("New York", target_date, "max_temp", "NWS", "F", "America/New_York", station, "nearest_integer", 1.0, (), ())
    observation = fetch_settlement_observation(rule)
    save_settlement_observation(history_db, "New York", target_date, observation.to_dict(), observation.observed_at)
    if observation.status != "available" or observation.max_temp is None:
        return {"target_date": target_date, "station": station, "status": observation.status, "reason": observation.reason, "markets_resolved": 0, "settlement_matches": 0, "shadow_finalized": 0}
    records = closed_new_york_markets(target_date, pages)
    comparisons = compare_day(observation.max_temp, records)
    resolved_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(history_db)) as conn:
        conn.executescript(SCHEMA)
        for item in comparisons:
            conn.execute("INSERT OR REPLACE INTO nws_market_resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (target_date, station, item["market_id"], item["question"], observation.max_temp, item["expected_outcome"], item["resolved_outcome"], int(item["settlement_match"]), resolved_at, json.dumps(item["market"], sort_keys=True)))
        before = _finalized_shadow_count(conn, target_date)
        _finalize_shadow_decisions(conn, target_date, records, resolved_at)
        after = _finalized_shadow_count(conn, target_date)
        conn.commit()
    return {"target_date": target_date, "station": station, "status": "finalized", "nws_high": observation.max_temp, "nws_low": observation.min_temp, "markets_resolved": len(comparisons), "settlement_matches": sum(item["settlement_match"] for item in comparisons), "shadow_finalized": after - before}


def nws_closure_status(history_db: str, station: str = "KLGA", min_days: int = 30, min_match_rate: float = 0.90) -> dict:
    status = {"station": station, "audit_days": 0, "markets_resolved": 0, "settlement_matches": 0, "match_rate": 0.0, "shadow_samples": 0, "shadow_finalized": 0, "shadow_hypothetical_pnl": 0.0, "station_verified": False, "settlement_verified": False}
    try:
        with closing(sqlite3.connect(history_db)) as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT COUNT(DISTINCT target_date), COUNT(*), COALESCE(SUM(settlement_match), 0) FROM nws_market_resolutions WHERE station = ?", (station,)).fetchone()
            status.update({"audit_days": int(row[0]), "markets_resolved": int(row[1]), "settlement_matches": int(row[2])})
            status["match_rate"] = status["settlement_matches"] / status["markets_resolved"] if status["markets_resolved"] else 0.0
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decisions'").fetchone():
                shadow = conn.execute("SELECT COUNT(*), SUM(CASE WHEN finalized_at IS NOT NULL THEN 1 ELSE 0 END), COALESCE(SUM(hypothetical_realized_pnl), 0) FROM shadow_decisions WHERE lower(event_slug) LIKE '%new-york%' OR lower(question) LIKE '%new york%'").fetchone()
                status.update({"shadow_samples": int(shadow[0]), "shadow_finalized": int(shadow[1] or 0), "shadow_hypothetical_pnl": float(shadow[2] or 0)})
    except sqlite3.Error:
        return status
    status["station_verified"] = status["audit_days"] >= min_days and status["match_rate"] >= min_match_rate
    configured = {item.strip().upper() for item in os.getenv("NWS_SETTLEMENT_VERIFIED_STATIONS", "").split(",") if item.strip()}
    status["settlement_verified"] = status["station_verified"] and station.upper() in configured
    return status


def _finalized_shadow_count(conn: sqlite3.Connection, target_date: str) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decisions'").fetchone():
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM shadow_decisions WHERE target_date = ? AND finalized_at IS NOT NULL", (target_date,)).fetchone()[0])
