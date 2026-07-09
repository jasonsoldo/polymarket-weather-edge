import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class StoredOrder:
    client_order_id: str
    market_id: str
    token_id: str
    bucket: str
    side: str
    price: float
    size: float
    status: str
    payload: dict

    def to_dict(self) -> dict:
        return asdict(self)


ORDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def init_orders_db(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(ORDER_SCHEMA)


def make_client_order_id(market_id: str, token_id: str, side: str, price: float, size: float) -> str:
    price_key = f"{price:.4f}"
    size_key = f"{size:.4f}"
    return f"{market_id}:{token_id}:{side}:{price_key}:{size_key}"


def has_recent_duplicate(path: str, client_order_id: str, window_seconds: int) -> bool:
    init_orders_db(path)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT created_at FROM orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
    if not row:
        return False
    created_at = _parse_sqlite_time(row[0])
    return created_at >= cutoff


def save_order(path: str, order: StoredOrder) -> None:
    init_orders_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders (
                client_order_id, market_id, token_id, bucket, side, price, size, status, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.client_order_id,
                order.market_id,
                order.token_id,
                order.bucket,
                order.side,
                order.price,
                order.size,
                order.status,
                json.dumps(order.payload, sort_keys=True),
            ),
        )


def _parse_sqlite_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
