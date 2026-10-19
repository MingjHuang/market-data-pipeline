"""Provider interface. Add a new venue by implementing this and registering it.

The rest of the pipeline (storage, gap detection, CLI, export) never imports a
concrete provider, so swapping feeds is a one-line change.
"""
from typing import Protocol, Sequence, runtime_checkable

from ..models import Candle


@runtime_checkable
class Provider(Protocol):
    name: str
    #: how many bars one request can return; the collector pages backwards by this
    page_limit: int
    #: minimum seconds between requests, to stay under the venue's rate limit
    min_interval: float

    def fetch(self, symbol: str, timeframe: str, limit: int,
              end_ts: int | None = None) -> Sequence[Candle]:
        """Return up to `limit` bars, newest last. `end_ts` pages backwards."""
        ...
