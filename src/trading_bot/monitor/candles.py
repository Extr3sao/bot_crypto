"""Read-only candle read model for the monitor.

The runtime does **not** persist the OHLCV window it decided on (it keeps only
``market_time_ms`` in the trace — see ``GAP-TDM-05``). The monitor therefore
reads public candles through the dependency the project already ships (``ccxt``)
and labels every bar with its source and ingestion time.

Point-in-time rule (RFC §4.3): the API accepts ``as_of`` (the decision time) and
drops every bar whose **close** is later than that instant. A candle that had not
closed yet could not have been observed, so it must never reach a decision view.

Offline behaviour: :class:`CandleUnavailable` is raised, the API answers
``503 CANDLES_UNAVAILABLE`` and the UI states that candles are unavailable. No
synthetic bars are ever generated outside tests, and test bars are labelled
``SIMULATED_FIXTURE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

__all__ = [
    "ALLOWED_TIMEFRAMES",
    "Bar",
    "CandleSource",
    "CandleUnavailable",
    "CcxtCandleSource",
    "StaticCandleSource",
    "timeframe_ms",
    "validate_timeframe",
]

#: Timeframes the monitor will serve. Anything else is a 400, not a silent pass-through.
ALLOWED_TIMEFRAMES: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

MAX_BARS_PER_REQUEST = 1_500


class CandleUnavailable(RuntimeError):
    """No candle source could answer (offline host, unsupported venue, error)."""


def timeframe_ms(timeframe: str) -> int:
    try:
        return ALLOWED_TIMEFRAMES[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported timeframe {timeframe!r}") from exc


def validate_timeframe(timeframe: str) -> str:
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise ValueError(
            f"unsupported timeframe {timeframe!r}; allowed: {', '.join(ALLOWED_TIMEFRAMES)}"
        )
    return timeframe


@dataclass(frozen=True, slots=True)
class Bar:
    """One candle, with the metadata the RFC requires every bar to declare."""

    time_ms: int  # bar open time
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str
    symbol: str
    venue: str
    is_closed: bool
    source: str
    ingested_at: str

    @property
    def close_time_ms(self) -> int:
        return self.time_ms + timeframe_ms(self.timeframe)

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time_ms // 1000,  # Lightweight Charts wants seconds
            "bar_open_time_ms": self.time_ms,
            "bar_close_time_ms": self.close_time_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "symbol": self.symbol,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "is_closed": self.is_closed,
            "source": self.source,
            "ingested_at": self.ingested_at,
        }


class CandleSource(Protocol):
    """Minimal read-only interface. Implementations must never place an order."""

    name: str

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        as_of_ms: int | None = None,
    ) -> list[Bar]: ...


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(slots=True)
class CcxtCandleSource:
    """Public OHLCV through the project's existing ``ccxt`` dependency."""

    exchange_id: str = "binance"
    name: str = "ccxt"
    fixture: bool = False

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        as_of_ms: int | None = None,
    ) -> list[Bar]:
        validate_timeframe(timeframe)
        limit = max(1, min(int(limit), MAX_BARS_PER_REQUEST))
        ingested = _now_iso()
        try:
            import ccxt  # local import: the monitor must import even without ccxt at hand
        except Exception as exc:  # pragma: no cover - environment dependent
            raise CandleUnavailable(f"ccxt not importable: {exc}") from exc
        exchange_cls = getattr(ccxt, self.exchange_id, None)
        if exchange_cls is None:
            raise CandleUnavailable(f"unknown exchange id {self.exchange_id!r}")
        exchange = exchange_cls({"enableRateLimit": True})
        try:
            if hasattr(exchange, "load_markets"):
                exchange.load_markets()
            raw = exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=start_ms,
                limit=limit,
            )
        except Exception as exc:
            raise CandleUnavailable(
                f"{self.exchange_id} fetch_ohlcv failed for {symbol}: {exc}"
            ) from exc

        width = timeframe_ms(timeframe)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        bars: list[Bar] = []
        for row in raw or []:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            open_ms = int(row[0])
            close_ms = open_ms + width
            if end_ms is not None and open_ms > end_ms:
                continue
            if as_of_ms is not None and close_ms > as_of_ms:
                # point-in-time: a bar that closes after the decision is not observable
                continue
            bars.append(
                Bar(
                    time_ms=open_ms,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    timeframe=timeframe,
                    symbol=symbol,
                    venue=self.exchange_id.upper(),
                    is_closed=close_ms <= now_ms,
                    source=f"ccxt:{self.exchange_id}:fetch_ohlcv",
                    ingested_at=ingested,
                )
            )
        bars.sort(key=lambda b: b.time_ms)
        return bars


@dataclass(slots=True)
class StaticCandleSource:
    """Deterministic bars for tests and replay. Always labelled as a fixture."""

    bars_by_symbol: dict[str, list[Bar]]
    name: str = "static-fixture"
    fixture: bool = True

    def fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        as_of_ms: int | None = None,
    ) -> list[Bar]:
        validate_timeframe(timeframe)
        limit = max(1, min(int(limit), MAX_BARS_PER_REQUEST))
        series = [b for b in self.bars_by_symbol.get(symbol, []) if b.timeframe == timeframe]
        if start_ms is not None:
            series = [b for b in series if b.time_ms >= start_ms]
        if end_ms is not None:
            series = [b for b in series if b.time_ms <= end_ms]
        if as_of_ms is not None:
            series = [b for b in series if b.close_time_ms <= as_of_ms]
        return series[-limit:]
