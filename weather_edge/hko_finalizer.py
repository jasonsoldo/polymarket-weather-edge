"""Finalize Hong Kong simulation positions from HKO and Polymarket results."""

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .accounting import init_accounting_db
from .history_store import save_settlement_observation
from .hko_polymarket_backfill import _closed_hko_markets, _expected_outcome, _json_list, _resolved_outcome
from .position_manager import load_positions, reduce_position
from .order_store import init_orders_db
from .settlement_source import fetch_settlement_observation
from .settlement_rules import SettlementRule


RESOLUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS hko_market_resolutions (
    target_date TEXT NOT NULL, market_id TEXT NOT NULL, question TEXT NOT NULL,
    metric TEXT NOT NULL, final_temperature REAL NOT NULL,
    expected_outcome TEXT, resolved_outcome TEXT, settlement_match INTEGER NOT NULL,
    resolved_at TEXT NOT NULL, raw_json TEXT NOT NULL,
    PRIMARY KEY (target_date, market_id)
);
"""

SIMULATION_SETTLEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_settlements (
    settlement_id TEXT PRIMARY KEY, target_date TEXT NOT NULL,
    market_id TEXT NOT NULL, token_id TEXT NOT NULL, bucket TEXT NOT NULL,
    purchased_outcome TEXT NOT NULL, resolved_outcome TEXT NOT NULL,
    final_temperature REAL NOT NULL, shares REAL NOT NULL, avg_price REAL NOT NULL,
    cost REAL NOT NULL, payout REAL NOT NULL, realized_pnl REAL NOT NULL,
    settled_at TEXT NOT NULL, source TEXT NOT NULL
);
"""


def yesterday_hong_kong() -> str:
    return (datetime.now(ZoneInfo("Asia/Hong_Kong")).date() - timedelta(days=1)).isoformat()


def finalize_hko_day(target_date: str, history_db: str, positions_db: str, orders_db: str, pages: int = 5) -> dict:
    if target_date == "yesterday":
        target_date = yesterday_hong_kong()
    rule = SettlementRule("Hong Kong", target_date, "temperature", "Hong Kong Observatory", "C", "Asia/Hong_Kong", "HKO", "nearest_tenth", 1.0, (), ())
    observation = fetch_settlement_observation(rule)
    save_settlement_observation(history_db, "Hong Kong", target_date, observation.to_dict(), observation.observed_at)
    if observation.status != "available":
        return {"target_date": target_date, "status": observation.status, "reason": observation.reason, "markets_resolved": 0, "positions_settled": 0, "realized_pnl": 0.0}

    records = _closed_hko_markets(target_date, pages)
    positions = load_positions(positions_db)
    positions_by_market = {}
    for position in positions:
        positions_by_market.setdefault(position.market_id, []).append(position)

    init_accounting_db(orders_db)
    init_orders_db(orders_db)
    with closing(sqlite3.connect(history_db)) as history, closing(sqlite3.connect(orders_db)) as orders:
        history.executescript(RESOLUTION_SCHEMA)
        orders.executescript(SIMULATION_SETTLEMENT_SCHEMA)
        resolved_count = matched_count = settled_count = 0
        total_pnl = 0.0
        winning_buckets = []
        resolved_at = datetime.now(timezone.utc).isoformat()
        for record in records:
            market = record["market"]
            market_id = str(market.get("id") or market.get("market_id") or "")
            question = str(market.get("question") or "")
            resolved_outcome = _resolved_outcome(market)
            if not market_id or not resolved_outcome:
                continue
            if "highest temperature" not in question.lower() and "high temperature" not in question.lower():
                continue
            metric = "high"
            final_temperature = observation.max_temp
            if final_temperature is None:
                continue
            expected_outcome = _expected_outcome(question, final_temperature)
            settlement_match = bool(expected_outcome and expected_outcome == resolved_outcome)
            resolved_at = datetime.now(timezone.utc).isoformat()
            history.execute(
                "INSERT OR REPLACE INTO hko_market_resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (target_date, market_id, question, metric, final_temperature, expected_outcome, resolved_outcome, int(settlement_match), resolved_at, json.dumps(market, sort_keys=True)),
            )
            resolved_count += 1
            matched_count += int(settlement_match)
            if resolved_outcome == "Yes":
                winning_buckets.append(question)

            outcomes = [str(value) for value in _json_list(market.get("outcomes"))]
            token_ids = [str(value) for value in _json_list(market.get("clobTokenIds"))]
            for position in positions_by_market.get(market_id, []):
                if not _is_dry_run_position(orders, position.market_id, position.token_id):
                    continue
                try:
                    purchased_outcome = outcomes[token_ids.index(position.token_id)]
                except (ValueError, IndexError):
                    continue
                settlement_id = f"hko:{target_date}:{position.market_id}:{position.token_id}"
                if orders.execute("SELECT 1 FROM simulation_settlements WHERE settlement_id = ?", (settlement_id,)).fetchone():
                    continue
                cost = position.shares * position.avg_price
                payout = position.shares if purchased_outcome == resolved_outcome else 0.0
                pnl = payout - cost
                orders.execute(
                    "INSERT INTO simulation_settlements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (settlement_id, target_date, position.market_id, position.token_id, position.bucket, purchased_outcome, resolved_outcome, final_temperature, position.shares, position.avg_price, cost, payout, pnl, resolved_at, "HKO + Polymarket"),
                )
                reduce_position(positions_db, position.market_id, position.token_id, position.shares)
                settled_count += 1
                total_pnl += pnl
        _finalize_shadow_decisions(history, target_date, records, resolved_at)
        history.commit()
        orders.commit()
    return {
        "target_date": target_date,
        "status": "finalized",
        "hko_high": observation.max_temp,
        "hko_low": observation.min_temp,
        "markets_resolved": resolved_count,
        "settlement_matches": matched_count,
        "winning_buckets": winning_buckets,
        "positions_settled": settled_count,
        "realized_pnl": total_pnl,
    }


def finalize_hko_recent(lookback_days: int, history_db: str, positions_db: str, orders_db: str, pages: int = 5, progress: bool = False) -> dict:
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    end = date.fromisoformat(yesterday_hong_kong())
    results = []
    for offset in range(lookback_days):
        target_date = (end - timedelta(days=offset)).isoformat()
        result = {"target_date": target_date, "status": "already_finalized", "markets_resolved": 0, "positions_settled": 0, "realized_pnl": 0.0} if _hko_day_complete(history_db, target_date) else finalize_hko_day(target_date, history_db, positions_db, orders_db, pages)
        results.append(result)
        if progress:
            print(f"[{offset + 1}/{lookback_days}] {target_date} {result.get('status', 'unknown')}", file=sys.stderr, flush=True)
    return {
        "lookback_days": lookback_days,
        "available_days": sum(item.get("status") in {"finalized", "already_finalized"} for item in results),
        "pending_days": sum(item.get("status") not in {"finalized", "already_finalized"} for item in results),
        "markets_resolved": sum(item.get("markets_resolved", 0) for item in results),
        "positions_settled": sum(item.get("positions_settled", 0) for item in results),
        "realized_pnl": sum(item.get("realized_pnl", 0.0) for item in results),
        "results": results,
    }


def _hko_day_complete(history_db: str, target_date: str) -> bool:
    try:
        with closing(sqlite3.connect(history_db)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hko_market_resolutions'").fetchone():
                return False
            resolved = int(conn.execute("SELECT COUNT(*) FROM hko_market_resolutions WHERE target_date = ?", (target_date,)).fetchone()[0])
            if not resolved:
                return False
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decisions'").fetchone():
                return True
            pending = int(conn.execute("""SELECT COUNT(*) FROM shadow_decisions WHERE target_date = ? AND finalized_at IS NULL
                                           AND (lower(event_slug) LIKE '%hong-kong%' OR lower(question) LIKE '%hong kong%')""", (target_date,)).fetchone()[0])
            return pending == 0
    except sqlite3.Error:
        return False


def _is_dry_run_position(conn: sqlite3.Connection, market_id: str, token_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM orders WHERE market_id = ? AND token_id = ? AND status = 'dry_run_filled' LIMIT 1",
        (market_id, token_id),
    ).fetchone()
    return bool(row)


def _finalize_shadow_decisions(conn: sqlite3.Connection, target_date: str, records: list[dict], finalized_at: str) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decisions'").fetchone():
        return
    resolutions = {str(item["market"].get("id") or ""): _resolved_outcome(item["market"]) for item in records}
    rows = conn.execute("SELECT decision_id, payload_json FROM shadow_decisions WHERE target_date = ? AND finalized_at IS NULL", (target_date,)).fetchall()
    for decision_id, payload_json in rows:
        payload = json.loads(payload_json)
        plan = payload.get("plan") or {}
        candidate = plan.get("simulation_candidate") or {}
        orders = candidate.get("orders") or plan.get("orders") or []
        cost = payout = 0.0
        used = {}
        for order in orders:
            market_id = str(order.get("market_id") or "")
            resolved = resolutions.get(market_id)
            if not resolved:
                continue
            size = float(order.get("size") or 0)
            cost += size * float(order.get("price") or 0)
            payout += size if resolved == "Yes" else 0.0
            used[market_id] = resolved
        if not used:
            continue
        conn.execute(
            "UPDATE shadow_decisions SET final_market_result = ?, hypothetical_realized_pnl = ?, finalized_at = ? WHERE decision_id = ?",
            (json.dumps(used, sort_keys=True), payout - cost, finalized_at, decision_id),
        )


def hko_closure_status(history_db: str, orders_db: str) -> dict:
    status = {"settlement_verified": False, "settlement_audit_passed": False, "historical_validation_ready": False, "official_data_days": 0, "audit_days": 0, "last_final_date": "", "final_daily_max": None, "markets_resolved": 0, "settlement_matches": 0, "winning_buckets": [], "shadow_samples": 0, "shadow_finalized": 0, "shadow_hypothetical_pnl": 0.0, "shadow_realized_pnl": 0.0, "last_finalized_at": "", "recent_shadow_reconciliations": [], "requirements": {}}
    try:
        with closing(sqlite3.connect(history_db)) as conn:
            row = conn.execute(
                "SELECT target_date, max_temp, recorded_at FROM settlement_observations WHERE city = 'Hong Kong' AND status = 'available' ORDER BY target_date DESC, id DESC LIMIT 1"
            ).fetchone()
            if row:
                status.update({"last_final_date": row[0], "final_daily_max": row[1], "last_finalized_at": row[2]})
            status["official_data_days"] = int(conn.execute("SELECT COUNT(DISTINCT target_date) FROM settlement_observations WHERE city = 'Hong Kong' AND status = 'available'").fetchone()[0])
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hko_market_resolutions'").fetchone():
                rows = conn.execute(
                    "SELECT question, resolved_outcome, settlement_match FROM hko_market_resolutions WHERE target_date = ?",
                    (status["last_final_date"],),
                ).fetchall()
                status["markets_resolved"] = len(rows)
                status["settlement_matches"] = sum(int(item[2]) for item in rows)
                status["winning_buckets"] = [item[0] for item in rows if item[1] == "Yes"]
                status["settlement_audit_passed"] = bool(rows) and status["settlement_matches"] == len(rows)
                status["audit_days"] = int(conn.execute("SELECT COUNT(*) FROM (SELECT target_date FROM hko_market_resolutions GROUP BY target_date HAVING COUNT(*) > 0 AND SUM(settlement_match) = COUNT(*))").fetchone()[0])
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decisions'").fetchone():
                shadow = conn.execute("""SELECT COUNT(*), SUM(CASE WHEN finalized_at IS NOT NULL THEN 1 ELSE 0 END), COALESCE(SUM(hypothetical_realized_pnl), 0)
                                         FROM shadow_decisions
                                         WHERE lower(event_slug) LIKE '%hong-kong%' OR lower(question) LIKE '%hong kong%'""").fetchone()
                status.update({"shadow_samples": int(shadow[0]), "shadow_finalized": int(shadow[1] or 0), "shadow_hypothetical_pnl": float(shadow[2] or 0)})
                recent = conn.execute(
                    """SELECT d.target_date, d.event_slug, d.recommended_action,
                              d.hypothetical_realized_pnl, d.finalized_at,
                              (SELECT s.max_temp FROM settlement_observations s
                               WHERE s.city = 'Hong Kong' AND s.target_date = d.target_date AND s.status = 'available'
                               ORDER BY s.id DESC LIMIT 1)
                       FROM shadow_decisions d WHERE d.finalized_at IS NOT NULL
                         AND (lower(d.event_slug) LIKE '%hong-kong%' OR lower(d.question) LIKE '%hong kong%')
                       ORDER BY d.finalized_at DESC LIMIT 10"""
                ).fetchall()
                status["recent_shadow_reconciliations"] = [
                    {"target_date": item[0], "event_slug": item[1], "recommended_action": item[2], "hypothetical_realized_pnl": item[3], "finalized_at": item[4], "final_temperature": item[5]}
                    for item in recent
                ]
            status["requirements"] = {
                "official_data_days": {"actual": status["official_data_days"], "required": 30, "passed": status["official_data_days"] >= 30},
                "matching_market_audit_days": {"actual": status["audit_days"], "required": 30, "passed": status["audit_days"] >= 30},
                "finalized_shadow_samples": {"actual": status["shadow_finalized"], "required": 7, "passed": status["shadow_finalized"] >= 7},
                "explicit_live_approval": {"actual": os.getenv("HKO_SETTLEMENT_VERIFIED", "false").lower() == "true", "required": True, "passed": os.getenv("HKO_SETTLEMENT_VERIFIED", "false").lower() == "true"},
            }
            status["historical_validation_ready"] = all(item["passed"] for key, item in status["requirements"].items() if key != "explicit_live_approval")
            status["settlement_verified"] = all(item["passed"] for item in status["requirements"].values())
    except sqlite3.Error:
        pass
    try:
        with closing(sqlite3.connect(orders_db)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='simulation_settlements'").fetchone():
                status["shadow_realized_pnl"] = float(conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM simulation_settlements").fetchone()[0])
    except sqlite3.Error:
        pass
    return status
