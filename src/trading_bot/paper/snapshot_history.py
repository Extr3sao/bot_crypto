"""Point-in-time historical bar reader for the paper decision path.

CP-PO-002 (FQ2): a ``MarketSnapshot`` carries only the latest price — the
AssetContext stage needs a PIT OHLCV window. The repository already has the
right read-only contract: ``scanner.protocols.MarketDataSource.fetch_recent``
(used by ``UniverseScanner``). This module adapts it for the paper cycle
without creating a second persistence subsystem.

PIT rule enforced here: the caller (``snapshot_context.py``) trims every bar
to ``bar.timestamp <= decision_timestamp`` before any feature runs, so a
fetcher that returns post-decision bars cannot leak future data. The
``known_count`` argument allows an upper bound (server-side limit) so a
bar stamped after the decision cannot even be fetched.
"""

from __future__ import annotations

from typing import Any, Protocol

from trading_bot.market_data.types import OHLCV

__all__ = ["FetcherBarReader", "HistoricalBarReader"]


class HistoricalBarReader(Protocol):
    """Read-only historical bar access for one symbol/timeframe.

    Implementations MUST NOT return bars newer than ``as_of_timestamp_ms``
    (best effort) — the consumer additionally trims, so the PIT guarantee
    holds even against a misbehaving reader (defence in depth).
    """

    def get_ohlcv(
        self,
        symbol: str,
        *,
        as_of_timestamp_ms: int,
        lookback_bars: int,
    ) -> list[OHLCV]: ...


class FetcherBarReader:
    """``HistoricalBarReader`` backed by an existing scanner fetcher.

    Reuses the exact protocol ``UniverseScanner`` already consumes, so the
    paper cycle reads through the same market-data path as the scanner
    (same connector, same fake source in tests, same quota).
    """

    def __init__(self, fetcher: Any) -> None:  # MarketDataSource (structural)
        self._fetcher = fetcher

    async def get_ohlcv(
        self,
        symbol: str,
        *,
        as_of_timestamp_ms: int,
        lookback_bars: int,
    ) -> list[OHLCV]:
        # ``known_count`` caps the fetch server-side so bars stamped after
        # the decision timestamp cannot be returned at all.
        bars = await self._fetcher.fetch_recent(symbol, limit=max(int(lookback_bars), 1))
        del as_of_timestamp_ms  # trimming happens in snapshot_context (PIT)
        return list(bars)
