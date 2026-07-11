"""Fill ledger and realized/unrealized PnL accounting."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .position_manager import Position, load_positions, reduce_position, upsert_position


SCHEMA = """
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    exchange_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    market_value REAL NOT NULL,
    cost_basis REAL NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def init_accounting_db(path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


def apply_fill(
    orders_db: str,
    positions_db: str,
    fill_id: str,
    exchange_order_id: str,
    client_order_id: str,
    market_id: str,
    token_id: str,
    bucket: str,
    side: str,
    price: float,
    size: float,
) -> float:
    init_accounting_db(orders_db)
    with sqlite3.connect(orders_db) as conn:
        if conn.execute("SELECT 1 FROM fills WHERE fill_id = ?", (fill_id,)).fetchone():
            return 0.0
    realized = 0.0
    if side.upper() == "SELL":
        position = next((item for item in load_positions(positions_db) if item.token_id == token_id and item.market_id == market_id), None)
        if position:
            filled = min(position.shares, size)
            realized = (float(price) - position.avg_price) * filled
            reduce_position(positions_db, market_id, token_id, filled)
            size = filled
    elif side.upper() == "BUY":
        upsert_position(positions_db, Position(market_id, token_id, bucket, size, float(price)))
    with sqlite3.connect(orders_db) as conn:
        conn.execute(
            "INSERT INTO fills (fill_id, exchange_order_id, client_order_id, market_id, token_id, bucket, side, price, size, realized_pnl, filled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fill_id, exchange_order_id, client_order_id, market_id, token_id, bucket, side.upper(), price, size, realized, datetime.now(timezone.utc).isoformat()),
        )
    return realized


def realized_pnl(orders_db: str) -> float:
    init_accounting_db(orders_db)
    with sqlite3.connect(orders_db) as conn:
        return float(conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM fills").fetchone()[0])
