import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    market_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    recommended_action TEXT NOT NULL,
    total_cost REAL NOT NULL,
    worst_case_pnl REAL NOT NULL,
    best_case_pnl REAL NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def init_db(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(SCHEMA)


def save_analysis(path: str, market_id: str, mode: str, curve: dict, decision: dict) -> None:
    init_db(path)
    payload = {"curve": curve, "decision": decision}
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO analyses (
                market_id, mode, allowed, recommended_action,
                total_cost, worst_case_pnl, best_case_pnl, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                mode,
                1 if decision["allowed"] else 0,
                decision["recommended_action"],
                curve["total_cost"],
                curve["worst_case_pnl"],
                curve["best_case_pnl"],
                json.dumps(payload, sort_keys=True),
            ),
        )
