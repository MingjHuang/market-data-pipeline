"""CLI entry point.

    python -m collector.cli backfill --provider eastmoney --symbols 1.600519,0.000001 --tf 1m --bars 240
    python -m collector.cli gaps     --db data/market.db --session a_share --tf 1m
    python -m collector.cli export   --db data/market.db --out data/candles.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .gaps import find_gaps, summarize
from .models import ProviderError
from .providers.binance import BinanceProvider
from .providers.eastmoney import EastmoneyProvider
from .storage import SqliteStore

PROVIDERS = {"eastmoney": EastmoneyProvider, "binance": BinanceProvider}


def _provider(name: str):
    if name not in PROVIDERS:
        sys.exit(f"unknown provider '{name}', choose from {list(PROVIDERS)}")
    return PROVIDERS[name]()


def cmd_backfill(args) -> int:
    prov = _provider(args.provider)
    store = SqliteStore(args.db)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    total = 0
    for sym in symbols:
        remaining, end_ts, fetched = args.bars, None, 0
        while remaining > 0:
            n = min(remaining, prov.page_limit)
            try:
                bars = prov.fetch(sym, args.tf, n, end_ts=end_ts)
            except ProviderError as e:
                print(f"  [fail] {e}")
                break
            if not bars:
                break
            changed = store.upsert(bars)
            fetched += len(bars)
            total += changed
            print(f"  {sym} {args.tf}: +{len(bars)} bars (db rows touched {changed}, "
                  f"{store.count(sym, args.tf)} total)")
            remaining -= len(bars)
            if len(bars) < n:
                break
            end_ts = bars[0].ts - 1
            time.sleep(prov.min_interval)
        if fetched == 0:
            print(f"  [warn] {sym}: nothing stored")
    print(f"done: {total} row(s) affected across {len(symbols)} symbol(s) -> {args.db}")
    return 0


def cmd_gaps(args) -> int:
    store = SqliteStore(args.db)
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    if not symbols:
        import sqlite3
        with sqlite3.connect(args.db) as c:
            symbols = [r[0] for r in c.execute(
                "SELECT DISTINCT symbol FROM candles WHERE timeframe=?", (args.tf,))]
    rc = 0
    for sym in symbols:
        ts = store.timestamps(sym, args.tf)
        if not ts:
            print(f"{sym}: no data")
            continue
        gaps = find_gaps(ts, args.tf, session=args.session, min_missing=args.min_missing)
        s = summarize(gaps, len(ts))
        print(f"{sym} [{args.tf}/{args.session}] bars={s['total_bars']} "
              f"gap_runs={s['gap_runs']} missing={s['missing_bars']} "
              f"completeness={s['completeness_pct']}%")
        for g in gaps[:5]:
            print(f"   {g.describe()}")
        if gaps:
            rc = 1
    return rc


def cmd_export(args) -> int:
    store = SqliteStore(args.db)
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    n = store.export_csv(args.out, symbols, args.tf)
    print(f"exported {n} rows -> {args.out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="collector", description="Market data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backfill", help="pull historical bars into SQLite")
    b.add_argument("--provider", default="eastmoney", choices=list(PROVIDERS))
    b.add_argument("--symbols", required=True, help="comma separated, e.g. 1.600519,0.000001")
    b.add_argument("--tf", default="1m", choices=["1m", "5m", "15m", "30m", "60m", "1d"])
    b.add_argument("--bars", type=int, default=240)
    b.add_argument("--db", default="data/market.db")
    b.set_defaults(func=cmd_backfill)

    g = sub.add_parser("gaps", help="report missing bars")
    g.add_argument("--db", default="data/market.db")
    g.add_argument("--tf", default="1m")
    g.add_argument("--symbols", default=None)
    g.add_argument("--session", default="a_share", choices=["a_share", "twenty_four_seven"])
    g.add_argument("--min-missing", type=int, default=1)
    g.set_defaults(func=cmd_gaps)

    e = sub.add_parser("export", help="dump to CSV")
    e.add_argument("--db", default="data/market.db")
    e.add_argument("--out", default="data/candles.csv")
    e.add_argument("--tf", default=None)
    e.add_argument("--symbols", default=None)
    e.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
