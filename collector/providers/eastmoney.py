"""Eastmoney (东方财富) public kline adapter.

No API key required. Covers A-share / HK / US / index / futures via `secid`:
    1.600519  -> Shanghai 600519
    0.000001  -> Shenzhen 000001
    116.00700 -> Hong Kong 00700
    105.AAPL  -> NASDAQ AAPL
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Sequence

from ..models import Candle, ProviderError

BASE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
CST = timezone(timedelta(hours=8))

# timeframe -> (eastmoney klt code, seconds per bar)
TF_MAP = {"1m": (1, 60), "5m": (5, 300), "15m": (15, 900),
          "30m": (30, 1800), "60m": (60, 3600), "1d": (101, 86400)}


class EastmoneyProvider:
    name = "eastmoney"
    page_limit = 1000
    min_interval = 0.35

    def __init__(self, timeout: float = 15.0, retries: int = 3):
        self.timeout = timeout
        self.retries = retries

    def _get(self, symbol: str, klt: int, limit: int, end: str) -> dict:
        params = {
            "secid": symbol, "klt": klt, "fqt": 1, "lmt": limit, "end": end,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        url = f"{BASE}?{urllib.parse.urlencode(params)}"
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; market-data-pipeline/1.0)",
                    "Referer": "https://quote.eastmoney.com/",
                })
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e:                       # noqa: BLE001 - upstream is flaky
                last = e
                time.sleep(0.8 * (2 ** attempt))
        raise ProviderError(f"{self.name}: {symbol} failed after {self.retries} tries ({last})")

    def fetch(self, symbol: str, timeframe: str, limit: int,
              end_ts: int | None = None) -> Sequence[Candle]:
        if timeframe not in TF_MAP:
            raise ValueError(f"unsupported timeframe {timeframe}; use {list(TF_MAP)}")
        klt, bar_seconds = TF_MAP[timeframe]
        end = "20500101"
        if end_ts:
            end = datetime.fromtimestamp(end_ts, CST).strftime("%Y%m%d")

        payload = self._get(symbol, klt, min(limit, self.page_limit), end)
        data = payload.get("data") or {}
        raw = data.get("klines") or []
        if not raw:
            raise ProviderError(f"{self.name}: no data for {symbol} {timeframe} "
                                f"(check the secid, e.g. 1.600519 for SH)")

        out: list[Candle] = []
        for line in raw:
            p = line.split(",")
            if len(p) < 7:
                continue
            ts = int(datetime.strptime(p[0], "%Y-%m-%d %H:%M").replace(tzinfo=CST).timestamp())
            out.append(Candle(
                symbol=symbol, timeframe=timeframe, ts=ts,
                open=float(p[1]), close=float(p[2]),
                high=float(p[3]), low=float(p[4]),
                volume=float(p[5]), amount=float(p[6]),
            ))
        out.sort(key=lambda c: c.ts)
        return out[-limit:]
