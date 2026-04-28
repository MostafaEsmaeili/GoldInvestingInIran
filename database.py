import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def _conn():
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with _conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                weight_grams REAL NOT NULL,
                price_per_gram_toman REAL NOT NULL,
                total_cost_toman REAL NOT NULL,
                gold_usd_at_time REAL,
                usd_toman_at_time REAL,
                baseline_dollar_at_time REAL,
                intrinsic_value_at_time REAL,
                deviation_pct_at_time REAL,
                signal_at_time TEXT,
                notes TEXT,
                status TEXT DEFAULT 'holding'
            );

            CREATE TABLE IF NOT EXISTS market_cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # Safe migration: add column if the DB already existed without it
        cols = {r[1] for r in db.execute("PRAGMA table_info(trades)")}
        if "baseline_dollar_at_time" not in cols:
            db.execute("ALTER TABLE trades ADD COLUMN baseline_dollar_at_time REAL")


def cache_set(key: str, value):
    with _conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO market_cache (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.utcnow().isoformat())
        )


def cache_get(key: str, max_age_seconds: int = 300):
    with _conn() as db:
        row = db.execute(
            "SELECT value, updated_at FROM market_cache WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    updated = datetime.fromisoformat(row["updated_at"])
    age = (datetime.utcnow() - updated).total_seconds()
    if age > max_age_seconds:
        return None
    return json.loads(row["value"])


def record_trade(
    weight_grams: float,
    price_per_gram_toman: float,
    total_cost_toman: float,
    gold_usd_at_time: float = None,
    usd_toman_at_time: float = None,
    baseline_dollar_at_time: float = None,
    intrinsic_value_at_time: float = None,
    deviation_pct_at_time: float = None,
    signal_at_time: str = None,
    notes: str = "",
) -> int:
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO trades
               (timestamp, weight_grams, price_per_gram_toman, total_cost_toman,
                gold_usd_at_time, usd_toman_at_time, baseline_dollar_at_time,
                intrinsic_value_at_time, deviation_pct_at_time, signal_at_time, notes, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'holding')""",
            (
                datetime.now().isoformat(),
                weight_grams,
                price_per_gram_toman,
                total_cost_toman,
                gold_usd_at_time,
                usd_toman_at_time,
                baseline_dollar_at_time,
                intrinsic_value_at_time,
                deviation_pct_at_time,
                signal_at_time,
                notes,
            ),
        )
        return cur.lastrowid


def get_all_trades():
    with _conn() as db:
        rows = db.execute("SELECT * FROM trades ORDER BY timestamp DESC").fetchall()
    return [dict(r) for r in rows]


def update_trade_status(trade_id: int, status: str):
    with _conn() as db:
        db.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))


def get_portfolio_summary():
    with _conn() as db:
        rows = db.execute("SELECT * FROM trades WHERE status = 'holding'").fetchall()

    total_grams = sum(r["weight_grams"] for r in rows)
    total_cost  = sum(r["total_cost_toman"] for r in rows)
    avg_price   = total_cost / total_grams if total_grams else 0

    return {
        "total_grams":        round(total_grams, 2),
        "total_cost_toman":   round(total_cost),
        "avg_price_per_gram": round(avg_price),
        "trade_count":        len(rows),
    }
