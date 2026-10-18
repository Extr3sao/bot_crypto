"""Point-in-time ``MarketSnapshot`` — one causal view an analyser may consume.

The contract is deliberately narrow, because the failure it prevents is wide:

    bar.open < bar.close_boundary <= snapshot.available_at_ms
             <= decision_ms <= model_request <= paper_fill

A snapshot is built **only** from bars that had already closed at
``decision_ms``.  It carries the boundary it is usable from, a content hash and
a per-timeframe gap list, so a consumer (and an independent verifier) can check
causality instead of trusting the caller.

Higher timeframes are the sharp edge: a 4h bar opened at 12:00 is not knowable
at 13:00 even though its open price is.  ``build_market_snapshot`` keeps the bar
only when ``open + tf <= decision_ms``; ``gate_snapshot`` then refuses the whole
snapshot while the slowest timeframe has not closed.  Fail closed: an analyser
that cannot be proven causal does not run.

Read-only: this module reads ``OHLCVStore`` and never writes market data, risk,
orders or the ledger.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise
from trading_bot.market_data.timeframe_store import TimeframeStore
from trading_bot.market_data.types import OHLCV

__all__ = [
    "GateReason",
    "MarketSnapshot",
    "Quote",
    "SnapshotGateResult",
    "SnapshotUnavailable",
    "TimeframeSlice",
    "build_market_snapshot",
    "gate_snapshot",
]

GateReason = Literal[
    "OK",
    "NOT_YET_AVAILABLE",
    "STALE_TIMEFRAME",
    "INSUFFICIENT_HISTORY",
    "NO_EXECUTABLE_PRICE",
]


class SnapshotUnavailable(RuntimeError):
    """A timeframe has no closed bar at ``decision_ms`` — nothing may be built."""

    def __init__(self, symbol: str, timeframe: str, reason: str) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.reason = reason
        super().__init__(f"snapshot unavailable for {symbol} {timeframe}: {reason}")


@dataclass(frozen=True, slots=True)
class Quote:
    """The last observable price, with the instant it was observed.

    ``observed_at_ms`` is when *we* saw it, not when the exchange says it traded.
    A quote older than the analysis it justifies is not executable.
    """

    bid: float
    ask: float
    observed_at_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class TimeframeSlice:
    timeframe: str
    bars: tuple[OHLCV, ...]
    gap_open_ms: tuple[int, ...]

    @property
    def last_open_ms(self) -> int:
        return int(self.bars[-1].timestamp)

    @property
    def close_boundary_ms(self) -> int:
        return self.last_open_ms + timeframe_seconds_or_raise(self.timeframe) * 1_000

    def content_hash(self) -> str:
        payload = [
            [
                int(r.timestamp),
                float(r.open),
                float(r.high),
                float(r.low),
                float(r.close),
                float(r.volume),
            ]
            for r in self.bars
        ]
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    source_id: str
    symbol: str
    decision_ms: int
    built_at_ms: int
    slices: dict[str, TimeframeSlice]
    content_hash: str
    quote: Quote | None = None

    @property
    def available_at_ms(self) -> int:
        """Instant from which every slice is knowable (the latest close)."""
        return max(s.close_boundary_ms for s in self.slices.values())

    @property
    def snapshot_id(self) -> str:
        return f"{self.symbol}:{self.decision_ms}:{self.content_hash[:16]}"

    @property
    def timeframes(self) -> tuple[str, ...]:
        return tuple(self.slices)

    def bars(self, timeframe: str) -> tuple[OHLCV, ...]:
        return self.slices[timeframe].bars

    def staleness_ms(self, at_ms: int) -> dict[str, int]:
        return {tf: int(at_ms) - sl.close_boundary_ms for tf, sl in self.slices.items()}

    def age_ms(self, at_ms: int) -> int:
        return int(at_ms) - self.available_at_ms

    def executable_price(
        self, at_ms: int, *, max_quote_age_ms: int = 60_000
    ) -> tuple[float, int] | None:
        """Mid price usable at ``at_ms``, or ``None`` when the quote is stale.

        ``None`` is the honest answer for "the model responded after the last
        tick": the caller must wait for a new quote instead of filling at a price
        that is no longer there.
        """
        if self.quote is None:
            return None
        age = int(at_ms) - int(self.quote.observed_at_ms)
        if age < 0 or age > max_quote_age_ms:
            return None
        return (self.quote.mid, self.quote.observed_at_ms)

    def to_json(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_id": self.source_id,
            "symbol": self.symbol,
            "decision_ms": self.decision_ms,
            "built_at_ms": self.built_at_ms,
            "available_at_ms": self.available_at_ms,
            "content_hash": self.content_hash,
            "quote": (
                {
                    "bid": self.quote.bid,
                    "ask": self.quote.ask,
                    "observed_at_ms": self.quote.observed_at_ms,
                }
                if self.quote is not None
                else None
            ),
            "timeframes": {
                tf: {
                    "bars": len(sl.bars),
                    "first_open_ms": int(sl.bars[0].timestamp),
                    "last_open_ms": sl.last_open_ms,
                    "close_boundary_ms": sl.close_boundary_ms,
                    "gaps": list(sl.gap_open_ms),
                    "content_hash": sl.content_hash(),
                }
                for tf, sl in self.slices.items()
            },
        }


@dataclass(frozen=True, slots=True)
class SnapshotGateResult:
    usable: bool
    reason: GateReason
    detail: str
    retry_at_ms: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "reason": self.reason,
            "detail": self.detail,
            "retry_at_ms": self.retry_at_ms,
        }


def _closed_only(rows: Iterable[OHLCV], timeframe: str, decision_ms: int) -> list[OHLCV]:
    bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
    kept = [row for row in rows if int(row.timestamp) + bar_ms <= decision_ms]
    kept.sort(key=lambda row: int(row.timestamp))
    return kept


def _gaps(rows: Sequence[OHLCV], timeframe: str) -> tuple[int, ...]:
    if len(rows) < 2:
        return ()
    bar_ms = timeframe_seconds_or_raise(timeframe) * 1_000
    present = {int(r.timestamp) for r in rows}
    first = int(rows[0].timestamp)
    last = int(rows[-1].timestamp)
    return tuple(ts for ts in range(first, last + bar_ms, bar_ms) if ts not in present)


def build_market_snapshot(
    store: TimeframeStore,
    *,
    symbol: str,
    timeframes: Sequence[str],
    decision_ms: int,
    source_id: str = "binance_public_ccxt",
    bars_per_timeframe: int = 300,
    now_ms: int | None = None,
    quote: Quote | None = None,
) -> MarketSnapshot:
    """Read the store and freeze the causal view available at ``decision_ms``.

    Raises ``SnapshotUnavailable`` when a requested timeframe has fewer than two
    closed bars: a one-bar slice cannot prove order, and zero bars prove nothing.
    """
    if not timeframes:
        raise ValueError("at least one timeframe is required")
    if bars_per_timeframe < 2:
        raise ValueError("bars_per_timeframe must be >= 2")
    slices: dict[str, TimeframeSlice] = {}
    for tf in timeframes:
        rows = store.tail(symbol, tf, bars_per_timeframe)
        closed = _closed_only(rows, tf, decision_ms)[-bars_per_timeframe:]
        if len(closed) < 2:
            raise SnapshotUnavailable(
                symbol,
                tf,
                f"only {len(closed)} closed bar(s) at decision_ms={decision_ms}",
            )
        slices[tf] = TimeframeSlice(
            timeframe=tf,
            bars=tuple(closed),
            gap_open_ms=_gaps(closed, tf),
        )

    built_at = int(now_ms if now_ms is not None else decision_ms)
    material = json.dumps(
        {
            "source": source_id,
            "symbol": symbol,
            "decision_ms": int(decision_ms),
            "slices": {tf: sl.content_hash() for tf, sl in slices.items()},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return MarketSnapshot(
        source_id=source_id,
        symbol=symbol,
        decision_ms=int(decision_ms),
        built_at_ms=built_at,
        slices=slices,
        content_hash=hashlib.sha256(material).hexdigest(),
        quote=quote,
    )


def gate_snapshot(
    snapshot: MarketSnapshot,
    *,
    at_ms: int,
    max_age_ms: int | None = 4 * 3_600_000,
    max_quote_age_ms: int = 60_000,
    require_quote: bool = False,
) -> SnapshotGateResult:
    """Decide whether ``snapshot`` may feed an analysis at ``at_ms``.

    Order matters: availability first (a future bar is a look-ahead bug, not a
    stale bar), then freshness, then the executable price.
    """
    at = int(at_ms)
    if at < snapshot.available_at_ms:
        return SnapshotGateResult(
            usable=False,
            reason="NOT_YET_AVAILABLE",
            detail=(f"snapshot is available at {snapshot.available_at_ms}, requested at {at}"),
            retry_at_ms=snapshot.available_at_ms,
        )
    if max_age_ms is not None:
        # Freshness is additive to the bar's own duration, not absolute: a 1d
        # bar is *always* almost 24h old at its newest, and calling that stale
        # would make daily context impossible to use.  ``max_age_ms`` is how
        # long we tolerate *beyond* one bar.
        for tf, idle in snapshot.staleness_ms(at).items():
            bar_ms = timeframe_seconds_or_raise(tf) * 1_000
            if idle > max_age_ms + bar_ms:
                return SnapshotGateResult(
                    usable=False,
                    reason="STALE_TIMEFRAME",
                    detail=(
                        f"{tf} last closed {idle} ms before the decision "
                        f"(limit {max_age_ms + bar_ms} ms)"
                    ),
                    retry_at_ms=at,
                )
    if require_quote and snapshot.executable_price(at, max_quote_age_ms=max_quote_age_ms) is None:
        return SnapshotGateResult(
            usable=False,
            reason="NO_EXECUTABLE_PRICE",
            detail="no quote observed within the executable window",
            retry_at_ms=at,
        )
    return SnapshotGateResult(usable=True, reason="OK", detail="causal snapshot", retry_at_ms=None)


def with_quote(snapshot: MarketSnapshot, quote: Quote | None) -> MarketSnapshot:
    """Attach (or clear) the observable price without rebuilding the bars."""
    return replace(snapshot, quote=quote)
