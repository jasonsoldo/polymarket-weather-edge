from dataclasses import asdict, dataclass

from .orderbook import BookSummary, fetch_book_summary
from .position_manager import Position, load_positions


@dataclass(frozen=True)
class PositionValuation:
    market_id: str
    token_id: str
    bucket: str
    shares: float
    cost_basis: float
    mark_price: float
    market_value: float
    unrealized_pnl: float
    stale: bool

    def to_dict(self) -> dict:
        return asdict(self)


def value_positions(positions: list[Position], books: dict[str, BookSummary]) -> list[PositionValuation]:
    rows = []
    for position in positions:
        book = books.get(position.token_id)
        mark = book.best_bid if book and book.best_bid is not None else 0.0
        cost = position.shares * position.avg_price
        value = position.shares * mark
        rows.append(PositionValuation(position.market_id, position.token_id, position.bucket, position.shares, cost, mark, value, value - cost, not bool(book and book.raw_timestamp)))
    return rows


def portfolio_snapshot(positions_db: str) -> dict:
    positions = load_positions(positions_db)
    books = {}
    for position in positions:
        try:
            books[position.token_id] = fetch_book_summary(position.token_id)
        except RuntimeError:
            continue
    rows = value_positions(positions, books)
    return {
        "positions": [row.to_dict() for row in rows],
        "cost_basis": sum(row.cost_basis for row in rows),
        "market_value": sum(row.market_value for row in rows),
        "unrealized_pnl": sum(row.unrealized_pnl for row in rows),
        "stale_positions": sum(1 for row in rows if row.stale),
    }
