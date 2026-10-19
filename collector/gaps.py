"""Gap detection.

Naive logic (compare consecutive timestamps) reports fake gaps at every session
break — e.g. the 90-minute A-share lunch break looks like 91 missing bars.

So we build the *expected session calendar* first, then set-difference it with
what we actually stored, and group the holes into runs.

Presets:
    twenty_four_seven   crypto-style, every step expected
    a_share             09:30-11:30, 13:00-15:00 Asia/Shanghai, Mon-Fri
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import Gap

CST = timezone(timedelta(hours=8))
STEP_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1d": 86400}

# A-share sessions, in minutes from midnight
SESSIONS = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))


def _expected_a_share(lo: int, hi: int, step: int) -> list[int]:
    """Every bar open time that should exist in an A-share session, lo..hi."""
    start = datetime.fromtimestamp(lo, CST).date()
    end = datetime.fromtimestamp(hi, CST).date()
    out: list[int] = []
    day = start
    while day <= end:
        if day.weekday() < 5:                       # Mon-Fri only
            for s_open, s_close in SESSIONS:
                # bars are labelled by their CLOSE time: 09:31 ... 11:30, 13:01 ... 15:00
                t = datetime(day.year, day.month, day.day, tzinfo=CST) + timedelta(minutes=s_open)
                stop = t + timedelta(minutes=s_close - s_open)
                t += timedelta(seconds=step)
                while t <= stop:
                    ts = int(t.timestamp())
                    if lo <= ts <= hi:
                        out.append(ts)
                    t += timedelta(seconds=step)
        day += timedelta(days=1)
    return out


def find_gaps(timestamps: Iterable[int], timeframe: str,
              session: str = "twenty_four_seven",
              min_missing: int = 1) -> list[Gap]:
    step = STEP_SECONDS.get(timeframe)
    if step is None:
        raise ValueError(f"unknown timeframe {timeframe}")

    actual = sorted(set(timestamps))
    if not actual:
        return []

    if session == "a_share" and timeframe != "1d":
        expected = _expected_a_share(actual[0], actual[-1], step)
    elif session in ("a_share", "twenty_four_seven"):
        expected = list(range(actual[0], actual[-1] + step, step))
    else:
        raise ValueError("session must be 'a_share' or 'twenty_four_seven'")

    have = set(actual)
    missing = [t for t in expected if t not in have]

    # group consecutive missing bars into runs
    gaps: list[Gap] = []
    run_start = prev = None
    for t in missing:
        if run_start is None:
            run_start = prev = t
        elif t - prev == step:
            prev = t
        else:
            if (prev - run_start) // step + 1 >= min_missing:
                gaps.append(Gap("", timeframe, run_start, prev, int((prev - run_start) // step + 1)))
            run_start = prev = t
    if run_start is not None and (prev - run_start) // step + 1 >= min_missing:
        gaps.append(Gap("", timeframe, run_start, prev, int((prev - run_start) // step + 1)))
    return gaps


def summarize(gaps: list[Gap], total_bars: int) -> dict:
    missing = sum(g.missing for g in gaps)
    expected = total_bars + missing
    return {
        "gap_runs": len(gaps),
        "missing_bars": missing,
        "total_bars": total_bars,
        "completeness_pct": round(100.0 * total_bars / expected, 2) if expected else 100.0,
    }
