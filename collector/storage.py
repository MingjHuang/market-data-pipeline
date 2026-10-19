"""SQLite storage: idempotent upsert, so re-running never duplicates or loses bars."""
from __future__ import annotations

import csv
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Sequence

from .models import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol    TEXT    NOT NULL,
    timeframe TEXT    NOT NULL,
    ts        INTEGER NOT NULL,   -- bar open time, epoch seconds UTC
    open      REAL    NOT NULL,
    high      REAL    NOT NULL,
    low       REAL    NOT NULL,
    close     REAL    NOT NULL,
    volume    REAL    NOT NULL DEFAULT 0,
    amount    REAL    NOT NULL DEFAULT 0,
    ingested  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (symbol, timeframe, ts)
);
CREATE INDEX IF NOT EXISTS idx_ts ON candles (ts);
"""


class SqliteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)
            c.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def upsert(self, candles: Iterable[Candle]) -> int:
        rows = [c.as_row() for c in candles]
        if not rows:
            return 0
        with closing(self._conn()) as c:
            before = c.total_changes
            c.executemany(
                """INSERT INTO candles (symbol, timeframe, ts, open, high, low, close, volume, amount)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol, timeframe, ts) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume, amount=excluded.amount""",
                rows)
            c.commit()
            return c.total_changes - before

    def timestamps(self, symbol: str, timeframe: str) -> list[int]:
        with closing(self._conn()) as c:
            cur = c.execute("SELECT ts FROM candles WHERE symbol=? AND timeframe=? ORDER BY ts",
                            (symbol, timeframe))
            return [r[0] for r in cur.fetchall()]

    def count(self, symbol: str, timeframe: str) -> int:
        with closing(self._conn()) as c:
            return c.execute("SELECT COUNT(*) FROM candles WHERE symbol=? AND timeframe=?",
                             (symbol, timeframe)).fetchone()[0]

    def export_csv(self, path: str | Path,
                   symbols: Sequence[str] | None = None,
                   timeframe: str | None = None) -> int:
        sql = "SELECT symbol, timeframe, ts, open, high, low, close, volume, amount FROM candles"
        where, args = [], []
        if symbols:
            where.append(f"symbol IN ({','.join('?' * len(symbols))})")
            args += list(symbols)
        if timeframe:
            where.append("timeframe = ?")
            args.append(timeframe)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY symbol, ts"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c, open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "timeframe", "ts", "open", "high", "low", "close", "volume", "amount"])
            n = 0
            for row in c.execute(sql, args):
                w.writerow(row)
                n += 1
        return n
