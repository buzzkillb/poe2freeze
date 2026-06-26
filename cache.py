"""
SQLite-backed price cache.
"""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    base TEXT,
    name TEXT,
    chaos_value REAL,
    divine_value REAL,
    exalted_value REAL,
    listing_count INTEGER,
    detail_json TEXT,
    fetched_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prices_expires ON prices(expires_at);
CREATE INDEX IF NOT EXISTS idx_prices_kind ON prices(kind);

CREATE TABLE IF NOT EXISTS currency_pairs (
    pair TEXT PRIMARY KEY,
    chaos_per_unit REAL NOT NULL,
    fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    status INTEGER,
    latency_ms INTEGER,
    ts INTEGER NOT NULL
);
"""


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def init_db():
    with get_db() as db:
        db.executescript(_SCHEMA)
        db.commit()


def cache_price(
    key: str,
    kind: str,
    chaos: Optional[float] = None,
    divine: Optional[float] = None,
    exalted: Optional[float] = None,
    listing_count: int = 0,
    detail: Dict = None,
    ttl_seconds: int = 1800,
    base: Optional[str] = None,
    name: Optional[str] = None,
):
    if detail is None:
        detail = {}
    if exalted is None and chaos is not None:
        exalted = chaos
    if exalted is None and divine is not None:
        exalted = divine
    now = int(time.time())
    expires = now + ttl_seconds
    detail_json = _safe_json(detail)
    with get_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO prices
            (key, kind, base, name, chaos_value, divine_value, exalted_value,
             listing_count, detail_json, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                kind,
                base,
                name,
                chaos,
                divine,
                exalted,
                listing_count,
                detail_json,
                now,
                expires,
            ),
        )
        db.commit()


def get_price(key: str) -> Optional[Dict]:
    now = int(time.time())
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM prices WHERE key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()
    if not row:
        return None
    return _row_to_price(row)


def find_price_by_name(name: str, kind: str = None) -> Optional[Dict]:
    now = int(time.time())
    with get_db() as db:
        if kind:
            row = db.execute(
                "SELECT * FROM prices WHERE name = ? AND kind = ? AND expires_at > ? ORDER BY fetched_at DESC LIMIT 1",
                (name, kind, now),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM prices WHERE name = ? AND expires_at > ? ORDER BY fetched_at DESC LIMIT 1",
                (name, now),
            ).fetchone()
    if not row:
        return None
    return _row_to_price(row)


def _row_to_price(row: sqlite3.Row) -> Dict:
    detail = _safe_json_load(row["detail_json"]) if row["detail_json"] else {}
    return {
        "key": row["key"],
        "kind": row["kind"],
        "base": row["base"],
        "name": row["name"],
        "chaos": row["chaos_value"],
        "divine": row["divine_value"],
        "exalted": row["exalted_value"],
        "listing_count": row["listing_count"],
        "fetched_at": row["fetched_at"],
        "age_seconds": int(time.time()) - row["fetched_at"],
        "detail": detail,
    }


def store_currency_pair(have: str, want: str, chaos_per_unit: float):
    pair = f"{have}|{want}"
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO currency_pairs (pair, chaos_per_unit, fetched_at) VALUES (?, ?, ?)",
            (pair, chaos_per_unit, int(time.time())),
        )
        db.commit()


def get_currency_pair(have: str, want: str) -> Optional[float]:
    pair = f"{have}|{want}"
    with get_db() as db:
        row = db.execute(
            "SELECT chaos_per_unit FROM currency_pairs WHERE pair = ? ORDER BY fetched_at DESC LIMIT 1",
            (pair,),
        ).fetchone()
    return row["chaos_per_unit"] if row else None


def log_request(endpoint: str, status: int, latency_ms: int):
    with get_db() as db:
        db.execute(
            "INSERT INTO request_log (endpoint, status, latency_ms, ts) VALUES (?, ?, ?, ?)",
            (endpoint, status, latency_ms, int(time.time())),
        )
        db.commit()


def _safe_json(d) -> str:
    import json
    try:
        return json.dumps(d, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _safe_json_load(s: str) -> Dict:
    import json
    try:
        return json.loads(s)
    except Exception:
        return {}