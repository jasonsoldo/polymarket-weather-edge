import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    city TEXT NOT NULL,
    target_date TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_target ON monitor_snapshots(target_date, observed_at);
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


def snapshot_count(path: str) -> int:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        return int(conn.execute("SELECT COUNT(*) FROM monitor_snapshots").fetchone()[0])
