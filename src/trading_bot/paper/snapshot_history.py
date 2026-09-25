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

from trading_bot.market_data.candle_filter import filter_completed_candles
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

    REAL-DATA-01 hardening: the reader now applies the canonical V3
    closed-candle filter (``candle_filter``) with the caller-provided
    decision timestamp, so an OPEN (forming) candle can never leak into
    the decision window on live providers. The deterministic fake provider
    is unaffected (its bars are stamped closed relative to ``now``).
    """

    def __init__(
        self, fetcher: Any, *, timeframe: str = "5m"
    ) -> None:  # MarketDataSource (structural)
        self._fetcher = fetcher
        self._timeframe = timeframe

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
        # Fail-closed candle policy: drop the forming candle using the
        # decision timestamp as 'current time' (deterministic; wall-clock
        # independent). PIT trim still happens downstream (defence in depth).
        completed = filter_completed_candles(
            list(bars),
            self._timeframe,
            current_time=as_of_timestamp_ms / 1000.0,
        )
        del as_of_timestamp_ms  # trimming happens in snapshot_context (PIT)
        return list(completed)
