"""Fail-closed validation for real public OHLCV data (G-7).

A real-data PAPER decision is only as trustworthy as the bars it consumed.
This module turns the G-7 requirements into one deterministic check:

* every bar is closed at the decision instant (``bar_open + timeframe <= decision``);
* timestamps are positive, unique, ascending and on the timeframe grid (no gaps);
* OHLCV values are finite and internally consistent;
* the newest closed bar is inside a documented freshness budget;
* the exact bars that were validated have a content hash.

The result is a value object, never an exception: callers persist the verdict
(``OK`` / ``STALE`` / ``INCOMPLETE`` / ``DUPLICATE`` / ``OUT_OF_ORDER`` /
``FUTURE`` / ``GAP`` / ``BAD_OHLCV`` / ``EMPTY``) and refuse to decide when it
is not ``OK``.  Keeping validation separate from fetching means a provider
adapter cannot accidentally certify its own output.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from trading_bot.market_data.timeframe import TIMEFRAME_SECONDS
from trading_bot.market_data.types import OHLCV

__all__ = [
    "DEFAULT_FRESHNESS_BARS",
    "MarketDataValidation",
    "bar_content_hash",
    "timeframe_ms",
    "validate_closed_bars",
]

#: A decision may use the previous closed bar while the current one forms.
#: The runtime's RouterGates uses the same 1.5-bar convention.
DEFAULT_FRESHNESS_BARS = 1.5

_STATUS_PRIORITY = {
    "OK": 0,
    "EMPTY": 1,
    "INCOMPLETE": 2,
    "STALE": 3,
    "GAP": 4,
    "FUTURE": 5,
    "OUT_OF_ORDER": 6,
    "DUPLICATE": 7,
    "BAD_OHLCV": 8,
}


def timeframe_ms(timeframe: str) -> int:
    """Milliseconds in ``timeframe`` (fail closed on unknown values)."""
    seconds = TIMEFRAME_SECONDS.get(timeframe.lower())
    if seconds is None:
        raise ValueError(f"unknown timeframe {timeframe!r}; known: {sorted(TIMEFRAME_SECONDS)}")
    return seconds * 1000


def bar_content_hash(bars: list[OHLCV]) -> str:
    """Stable SHA-256 of the exact OHLCV rows (no timestamps of capture)."""
    payload = json.dumps(
        [
            [
                b.symbol,
                int(b.timestamp),
                float(b.open),
                float(b.high),
                float(b.low),
                float(b.close),
                float(b.volume),
            ]
            for b in bars
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MarketDataValidation:
    """Outcome of validating one symbol/timeframe at one decision instant."""

    provider: str
    asset: str
    symbol: str
    timeframe: str
    decision_time_ms: int
    received_at_ms: int
    data_time_ms: int
    data_close_ms: int
    freshness_ms: int
    data_hash: str
    bar_count: int
    validation_status: str
    issues: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.validation_status == "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "asset": self.asset,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_time_ms": self.decision_time_ms,
            "received_at_ms": self.received_at_ms,
            "data_time_ms": self.data_time_ms,
            "data_close_ms": self.data_close_ms,
            "freshness_ms": self.freshness_ms,
            "data_hash": self.data_hash,
            "bar_count": self.bar_count,
            "validation_status": self.validation_status,
            "issues": list(self.issues),
        }


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _worst(status: str, candidate: str) -> str:
    return candidate if _STATUS_PRIORITY[candidate] > _STATUS_PRIORITY[status] else status


def validate_closed_bars(
    bars: list[OHLCV],
    *,
    provider: str,
    asset: str,
    symbol: str,
    timeframe: str,
    decision_time_ms: int,
    received_at_ms: int,
    min_bars: int = 1,
    freshness_bars: float = DEFAULT_FRESHNESS_BARS,
) -> MarketDataValidation:
    """Validate a closed-bar window without repairing it.

    No sorting, de-duplication or gap filling happens here.  A malformed
    window is reported and the caller must not trade on it.
    """
    tf_ms = timeframe_ms(timeframe)
    issues: list[dict[str, Any]] = []
    status = "OK"
    seen: set[int] = set()
    previous_ts: int | None = None

    if not bars:
        status = _worst(status, "EMPTY")
        issues.append(_issue("EMPTY", "provider returned no bars"))
    if len(bars) < min_bars:
        status = _worst(status, "INCOMPLETE")
        issues.append(
            _issue(
                "INCOMPLETE",
                f"received {len(bars)} bars, need at least {min_bars}",
            )
        )

    for index, bar in enumerate(bars):
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(math.isfinite(float(value)) for value in values):
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} has a non-finite value"))
            continue
        if bar.timestamp <= 0:
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} has non-positive timestamp"))
        if float(bar.high) < float(bar.low):
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} has high < low"))
        if float(bar.high) < max(float(bar.open), float(bar.close)):
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} high is below body"))
        if float(bar.low) > min(float(bar.open), float(bar.close)):
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} low is above body"))
        if float(bar.volume) < 0:
            status = _worst(status, "BAD_OHLCV")
            issues.append(_issue("BAD_OHLCV", f"bar {index} has negative volume"))

        timestamp = int(bar.timestamp)
        if timestamp in seen:
            status = _worst(status, "DUPLICATE")
            issues.append(_issue("DUPLICATE", f"timestamp {timestamp} appears more than once"))
        seen.add(timestamp)

        if previous_ts is not None and timestamp <= previous_ts:
            status = _worst(status, "OUT_OF_ORDER")
            issues.append(_issue("OUT_OF_ORDER", f"timestamp {timestamp} follows {previous_ts}"))
        previous_ts = timestamp

        if timestamp + tf_ms > decision_time_ms:
            status = _worst(status, "FUTURE")
            issues.append(
                _issue(
                    "FUTURE",
                    f"bar {timestamp} closes at {timestamp + tf_ms}, after decision {decision_time_ms}",
                )
            )

    ordered = sorted(bars, key=lambda b: int(b.timestamp))
    for left, right in pairwise(ordered):
        delta = int(right.timestamp) - int(left.timestamp)
        if delta != tf_ms:
            status = _worst(status, "GAP")
            issues.append(
                _issue(
                    "GAP",
                    f"expected {tf_ms} ms between {left.timestamp} and {right.timestamp}, got {delta}",
                )
            )

    last = ordered[-1] if ordered else None
    data_time_ms = int(last.timestamp) if last is not None else 0
    data_close_ms = data_time_ms + tf_ms if last is not None else 0
    freshness_ms = int(decision_time_ms) - data_close_ms if last is not None else 0
    budget_ms = int(tf_ms * freshness_bars)
    if last is not None and freshness_ms > budget_ms:
        status = _worst(status, "STALE")
        issues.append(
            _issue(
                "STALE",
                f"last closed bar is {freshness_ms} ms old; budget {budget_ms} ms",
            )
        )

    return MarketDataValidation(
        provider=provider,
        asset=asset,
        symbol=symbol,
        timeframe=timeframe,
        decision_time_ms=int(decision_time_ms),
        received_at_ms=int(received_at_ms),
        data_time_ms=data_time_ms,
        data_close_ms=data_close_ms,
        freshness_ms=freshness_ms,
        data_hash=bar_content_hash(ordered),
        bar_count=len(bars),
        validation_status=status,
        issues=tuple(issues),
    )
