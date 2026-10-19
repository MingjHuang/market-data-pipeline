# market-data-pipeline

Pluggable OHLCV collector: pull historical candles from multiple venues, store them
idempotently in SQLite, audit the result for missing bars, export to CSV.

Built for the kind of work where "did we actually get every bar?" matters — backtesting,
signal research, broker-feed comparison. Naive collectors quietly lose bars on restarts
and rate limits; this one makes the holes visible and refillable.

```
collector/            package
├── models.py         Candle / Gap value objects
├── providers/        venue adapters, one file each
│   ├── base.py       Provider protocol (the only contract the pipeline knows)
│   ├── eastmoney.py  Eastmoney (A-share / HK / US / index), no API key
│   └── binance.py    Binance public klines, no API key
├── storage.py        SQLite upsert + CSV export
├── gaps.py           session-aware gap audit
└── cli.py            backfill / gaps / export
tests/                9 offline tests, no network required
```

## Quick start

```bash
python -m collector.cli backfill --provider eastmoney \
    --symbols 1.600519,0.000001 --tf 1m --bars 240
```

```
  1.600519 1m: +240 bars (db rows touched 240, 240 total)
  0.000001 1m: +240 bars (db rows touched 240, 240 total)
done: 480 row(s) affected across 2 symbol(s) -> data/market.db
```

```bash
python -m collector.cli gaps --db data/market.db --tf 1m --session a_share
```

```
0.000001 [1m/a_share] bars=240 gap_runs=0 missing=0 completeness=100.0%
1.600519 [1m/a_share] bars=240 gap_runs=0 missing=0 completeness=100.0%
```

```bash
python -m collector.cli export --db data/market.db --out data/candles.csv --tf 1m
```

```
symbol,timeframe,ts,open,high,low,close,volume,amount
0.000001,1m,1792114260,11.41,11.45,11.36,11.41,44094.0,50300897.0
```

`ts` is the bar's **open** time in epoch seconds (UTC); A-share minute bars are
labelled by close time upstream (09:31 … 11:30, 13:01 … 15:00) and normalised on ingest.

## Design decisions

**Session-aware gap audit, not `diff(ts) > step`.**
The obvious implementation reports 91 missing bars every day at 11:30 for A-share data,
because it treats the lunch break as a hole. This builds the *expected* session calendar
(weekday × two sessions × step) and set-differences it against what was stored, so a
report of "0 gaps" is meaningful and a real hole is unambiguous. Covered by
`test_lunch_break_is_not_a_gap`.

**Idempotent upsert keyed on `(symbol, timeframe, ts)`.**
Re-running a backfill — after a crash, a rate limit, or simply by accident — must not
duplicate rows or silently drop the newest revision. Re-ingesting the same 240 bars
leaves the table at 240 rows; re-ingesting with corrected values updates in place.

**Provider protocol instead of provider-specific branches.**
Storage, gap audit, CLI and export import only `providers.base.Provider`. Adding a venue
is one file; nothing downstream changes. The two shipped adapters differ completely —
one REST/JSON with `secid` identifiers and a `Referer` requirement, one with `endTime`
paging and millisecond timestamps — which is the point: the seam holds.

**Backoff and pacing belong to the adapter.**
`min_interval` and `retries` live next to the venue that needs them (Eastmoney tolerates
~3 req/s; Binance weight-limits per minute). The collector just sleeps `min_interval`
between pages rather than hard-coding anyone's limits.

**Paging backwards by `end_ts` = first_bar.ts - 1.**
Lets you request N bars older than anything you already hold, so a backfill resumes from
the oldest stored bar instead of re-downloading history.

## Adding a venue

```python
# collector/providers/myvenue.py
from ..models import Candle

class MyVenueProvider:
    name = "myvenue"
    page_limit = 500
    min_interval = 0.5

    def fetch(self, symbol, timeframe, limit, end_ts=None):
        raw = ...                                    # your HTTP/websocket call
        return [Candle(symbol=symbol, timeframe=timeframe, ts=bar["t"],
                       open=bar["o"], high=bar["h"], low=bar["l"],
                       close=bar["c"], volume=bar["v"])
                for bar in raw]
```

Register it in `providers/__init__.py` + `cli.PROVIDERS` and it is available as
`--provider myvenue`. Broker OTC feeds (synthetic quote streams that only exist inside a
proprietary terminal) fit the same interface — the adapter holds the session handling,
the pipeline stays untouched.

## Tests

```bash
python -m unittest discover -s tests -v
# Ran 9 tests ... OK
```

Offline by design: gap detection, upsert semantics and CSV export are all exercised
against a temp database, so the suite runs on a machine with no market access.

## Limits / roadmap

- No scheduled live streaming yet — `backfill` is pull-based; a `stream` subcommand
  using each venue's websocket is the next step.
- A-share holidays are not modelled (weekends only). A trading-calendar file would make
  completeness exact across holidays.
- Timestamps normalise to UTC epoch; downstream consumers get one convention, not one
  per venue.

MIT licensed.
