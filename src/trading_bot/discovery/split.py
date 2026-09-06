"""Immutable chronological split: DISCOVERY / CONFIRMATION / FINAL_HOLDOUT.

Once built, the split is content-hashed and access-controlled:
- DISCOVERY code paths can only read the DISCOVERY window.
- Reading CONFIRMATION or FINAL_HOLDOUT during discovery raises
  :class:`SplitAccessError` (fail-closed, G5/G6).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_bot.market_data.types import OHLCV

from .dataset import SymbolDataset, _ms

SPLIT_SCHEMA_VERSION = "fresh-split-v1"


class SplitAccessError(PermissionError):
    """Raised when a locked window is read before its phase is authorized."""


@dataclass(frozen=True, slots=True)
class SplitWindows:
    discovery_start: datetime
    discovery_end_exclusive: datetime
    confirmation_end_exclusive: datetime
    holdout_end_exclusive: datetime

    @property
    def confirmation_start(self) -> datetime:
        return self.discovery_end_exclusive

    @property
    def holdout_start(self) -> datetime:
        return self.confirmation_end_exclusive

    @property
    def discovery_range(self) -> tuple[datetime, datetime]:
        return (self.discovery_start, self.discovery_end_exclusive)

    @property
    def confirmation_range(self) -> tuple[datetime, datetime]:
        return (self.confirmation_start, self.confirmation_end_exclusive)

    @property
    def holdout_range(self) -> tuple[datetime, datetime]:
        return (self.holdout_start, self.holdout_end_exclusive)


def compute_split(last_close_ms: int) -> SplitWindows:
    """60/20/20 chronological split anchored at FRESH_START.

    The discovery slice is the first ~60% of closed fresh data; confirmation
    the next ~20%; final holdout the last ~20%. Boundaries are deterministic
    given the cutoff.
    """
    from .dataset import FRESH_START_UTC

    start_ms = _ms(FRESH_START_UTC)
    total = last_close_ms - start_ms
    discovery_end = start_ms + int(total * 0.60)
    confirmation_end = start_ms + int(total * 0.80)
    return SplitWindows(
        discovery_start=FRESH_START_UTC,
        discovery_end_exclusive=datetime.fromtimestamp(discovery_end / 1000, tz=UTC),
        confirmation_end_exclusive=datetime.fromtimestamp(confirmation_end / 1000, tz=UTC),
        holdout_end_exclusive=datetime.fromtimestamp((last_close_ms + 1) / 1000, tz=UTC),
    )


def build_split_manifest(windows: SplitWindows) -> dict[str, Any]:
    body = {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "fractions": {"discovery": 0.60, "confirmation": 0.20, "final_holdout": 0.20},
        "discovery": [windows.discovery_start.isoformat(), windows.discovery_end_exclusive.isoformat()],
        "confirmation": [windows.confirmation_start.isoformat(), windows.confirmation_end_exclusive.isoformat()],
        "final_holdout": [windows.holdout_start.isoformat(), windows.holdout_end_exclusive.isoformat()],
        "locked_after_freeze": True,
    }
    body["split_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return body


@dataclass(frozen=True, slots=True)
class SplitAccessor:
    """The ONLY sanctioned way to read candles for a given phase.

    ``read`` enforces phase boundaries: discovery-phase reads outside the
    discovery window (and any confirmation/holdout read while
    ``holdout_unlocked=False``) fail closed.
    """

    datasets: dict[str, SymbolDataset]
    windows: SplitWindows
    split_sha256: str
    holdout_unlocked: bool = False  # permanent False in FRESH-DATA-001

    def read(self, symbol: str, phase: str) -> list[OHLCV]:
        dataset = self.datasets.get(symbol)
        if dataset is None:
            raise KeyError(symbol)
        if phase == "discovery":
            start, end = self.windows.discovery_range
        elif phase == "confirmation":
            raise SplitAccessError(
                "CONFIRMATION window is LOCKED: may not be read during discovery"
            )
        elif phase == "final_holdout":
            raise SplitAccessError(
                "FINAL_HOLDOUT window is LOCKED: may not be read in this checkpoint"
            )
        else:
            raise ValueError(f"unknown phase: {phase}")
        start_ms, end_ms = _ms(start), _ms(end)
        return [
            c
            for c in dataset.candles
            if start_ms <= c.timestamp < end_ms
        ]

    def discovery_candles(self, symbol: str) -> list[OHLCV]:
        return self.read(symbol, "discovery")


def slice_candles_strict(candles: list[OHLCV], start: datetime, end: datetime) -> list[OHLCV]:
    """Strict chronological slice helper (used by the runner, discovery only)."""
    start_ms, end_ms = _ms(start), _ms(end)
    return [c for c in candles if start_ms <= c.timestamp < end_ms]
