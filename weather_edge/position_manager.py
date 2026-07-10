import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Position:
    market_id: str
    token_id: str
    bucket: str
    shares: float
    avg_price: float

    def to_dict(self) -> dict:
        return asdict(self)


POSITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    shares REAL NOT NULL,
    avg_price REAL NOT NULL,
    PRIMARY KEY (market_id, token_id)
);
"""


def init_positions_db(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(POSITION_SCHEMA)


def load_positions(path: str) -> list[Position]:
    init_positions_db(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT market_id, token_id, bucket, shares, avg_price FROM positions"
        ).fetchall()
    return [Position(*row) for row in rows]


def positions_for_market(path: str, market_id: str) -> list[Position]:
    return [position for position in load_positions(path) if position.market_id == market_id]


def total_exposure(path: str) -> float:
    return sum(position.shares * position.avg_price for position in load_positions(path))


def upsert_position(path: str, position: Position) -> None:
    init_positions_db(path)
    existing = None
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT shares, avg_price FROM positions WHERE market_id = ? AND token_id = ?",
            (position.market_id, position.token_id),
        ).fetchone()
        if row:
            existing = row
        if existing:
            old_shares, old_avg = existing
            new_shares = old_shares + position.shares
            new_avg = ((old_shares * old_avg) + (position.shares * position.avg_price)) / new_shares
            conn.execute(
                "UPDATE positions SET shares = ?, avg_price = ?, bucket = ? WHERE market_id = ? AND token_id = ?",
                (new_shares, new_avg, position.bucket, position.market_id, position.token_id),
            )
        else:
            conn.execute(
                "INSERT INTO positions (market_id, token_id, bucket, shares, avg_price) VALUES (?, ?, ?, ?, ?)",
                (position.market_id, position.token_id, position.bucket, position.shares, position.avg_price),
            )


def reduce_position(path: str, market_id: str, token_id: str, shares: float) -> float:
    if shares <= 0:
        return 0.0
    init_positions_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT shares FROM positions WHERE market_id = ? AND token_id = ?", (market_id, token_id)
        ).fetchone()
        if not row:
            return 0.0
        filled = min(float(row[0]), shares)
        remaining = float(row[0]) - filled
        if remaining <= 0:
            conn.execute("DELETE FROM positions WHERE market_id = ? AND token_id = ?", (market_id, token_id))
        else:
            conn.execute("UPDATE positions SET shares = ? WHERE market_id = ? AND token_id = ?", (remaining, market_id, token_id))
    return filled
