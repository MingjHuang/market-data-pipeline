"""Binance public kline adapter — shows how little it takes to add a venue.

Same interface as EastmoneyProvider; `collector.cli` needs no changes.
Public endpoint, no API key. (Reachable from most networks; if your ISP
blocks api.binance.com the CLI will report a clean ProviderError.)
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Sequence

from ..models import Candle, ProviderError

BASE = "https://api.binance.com/api/v3/klines"
TF_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
          "60m": "1h", "1d": "1d"}


class BinanceProvider:
    name = "binance"
    page_limit = 1000
    min_interval = 0.25

    def __init__(self, timeout: float = 12.0, retries: int = 3):
        self.timeout = timeout
        self.retries = retries

    def fetch(self, symbol: str, timeframe: str, limit: int,
              end_ts: int | None = None) -> Sequence[Candle]:
        if timeframe not in TF_MAP:
            raise ValueError(f"unsupported timeframe {timeframe}; use {list(TF_MAP)}")
        params = {"symbol": symbol.upper(), "interval": TF_MAP[timeframe],
                  "limit": min(limit, self.page_limit)}
        if end_ts:
            params["endTime"] = end_ts * 1000 - 1
        url = f"{BASE}?{urllib.parse.urlencode(params)}"

        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "market-data-pipeline/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    rows = json.loads(r.read().decode())
                break
            except Exception as e:                       # noqa: BLE001
                last = e
                time.sleep(0.8 * (2 ** attempt))
        else:
            raise ProviderError(f"{self.name}: {symbol} unreachable ({last})")

        return [Candle(symbol=symbol.upper(), timeframe=timeframe,
                       ts=int(r[0]) // 1000,
                       open=float(r[1]), high=float(r[2]),
                       low=float(r[3]), close=float(r[4]),
                       volume=float(r[5]), amount=float(r[7]))
                for r in rows]
