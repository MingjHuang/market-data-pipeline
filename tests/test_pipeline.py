"""Offline smoke tests — no network, no API keys. Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from collector.gaps import STEP_SECONDS, find_gaps, summarize
from collector.models import Candle
from collector.storage import SqliteStore

CST = timezone(timedelta(hours=8))


def _candle(ts: int, close: float = 10.0) -> Candle:
    return Candle("TEST", "1m", ts, 10.0, 10.1, 9.9, close, 100.0, 1000.0)


def _session_ts(day: str, hhmm: str) -> int:
    return int(datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=CST).timestamp())


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.store = SqliteStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_is_idempotent(self):
        bars = [_candle(1_700_000_000 + i * 60) for i in range(10)]
        self.store.upsert(bars)
        self.assertEqual(self.store.count("TEST", "1m"), 10)
        self.store.upsert(bars)                       # same batch again
        self.assertEqual(self.store.count("TEST", "1m"), 10, "re-ingest must not duplicate")

    def test_upsert_revises_values(self):
        self.store.upsert([_candle(1_700_000_000, close=10.0)])
        self.store.upsert([_candle(1_700_000_000, close=11.5)])
        self.assertEqual(self.store.count("TEST", "1m"), 1)
        self.assertEqual(self.store.timestamps("TEST", "1m"), [1_700_000_000])

    def test_export_rows(self):
        self.store.upsert([_candle(1_700_000_000 + i * 60) for i in range(5)])
        out = os.path.join(self.tmp.name, "o.csv")
        self.assertEqual(self.store.export_csv(out), 5)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(len(f.read().strip().splitlines()), 6)   # header + 5


class TestGaps(unittest.TestCase):
    def test_no_gap_when_complete(self):
        day = "2026-10-16"
        ts = [_session_ts(day, f"09:{m:02d}") for m in range(31, 60)]
        ts += [_session_ts(day, f"10:{m:02d}") for m in range(0, 60)]
        ts += [_session_ts(day, f"11:{m:02d}") for m in range(0, 31)]
        self.assertEqual(find_gaps(ts, "1m", session="a_share"), [])

    def test_lunch_break_is_not_a_gap(self):
        day = "2026-10-16"
        morning = [_session_ts(day, f"{h:02d}:{m:02d}")
                   for h, lo, hi in ((9, 31, 60), (10, 0, 60), (11, 0, 31)) for m in range(lo, hi)]
        afternoon = [_session_ts(day, f"{h:02d}:{m:02d}")
                     for h, lo, hi in ((13, 1, 60), (14, 0, 60), (15, 0, 1)) for m in range(lo, hi)]
        gaps = find_gaps(morning + afternoon, "1m", session="a_share")
        self.assertEqual(gaps, [], "the 11:30-13:00 break must not be reported")

    def test_real_gap_is_detected(self):
        day = "2026-10-16"
        ts = [_session_ts(day, f"10:{m:02d}") for m in range(0, 20)]
        ts += [_session_ts(day, f"10:{m:02d}") for m in range(24, 40)]   # 10:20-10:23 missing
        gaps = find_gaps(ts, "1m", session="a_share")
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing, 4)

    def test_summarize_completeness(self):
        s = summarize([], 240)
        self.assertEqual(s["completeness_pct"], 100.0)

    def test_unknown_timeframe_raises(self):
        with self.assertRaises(ValueError):
            find_gaps([1, 2], "7m")

    def test_step_table_covers_cli_choices(self):
        for tf in ("1m", "5m", "15m", "30m", "60m", "1d"):
            self.assertIn(tf, STEP_SECONDS)


if __name__ == "__main__":
    unittest.main()
