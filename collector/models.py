"""Candle model shared by every provider."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Candle:
    """One OHLCV bar. `ts` is the bar's opening time in epoch seconds (UTC)."""
    symbol: str
    timeframe: str
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0

    def as_row(self) -> tuple:
        return (self.symbol, self.timeframe, self.ts,
                self.open, self.high, self.low, self.close,
                self.volume, self.amount)


@dataclass(frozen=True, slots=True)
class Gap:
    """A missing bar between two observed bars."""
    symbol: str
    timeframe: str
    start_ts: int
    end_ts: int
    missing: int

    def describe(self) -> str:
        from datetime import datetime, timezone
        f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
        return f"{self.symbol} {self.timeframe}: {self.missing} bars missing {f(self.start_ts)} -> {f(self.end_ts)}"


class ProviderError(RuntimeError):
    """Raised when an upstream feed refuses or returns junk."""
