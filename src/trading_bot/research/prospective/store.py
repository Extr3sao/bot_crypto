"""The append-only bar store, read as evidence rather than as a dataframe.

The store is JSONL, one record per bar, appended by the forward observer::

    {"ts": 1772323200000, "interval": "1h", "closed": true, "fetched_at_ms": 1791848391233, ...}

Two fields carry the whole provenance argument. ``ts`` is the bar's **open** instant; the bar
closes at ``ts + interval``. ``fetched_at_ms`` is when *this process* stored it. Their
difference is the lag, and the lag is the only thing in the file that distinguishes a bar that
was watched from a bar that was backfilled — a backfilled bar has a perfectly ordinary ``ts``
and a lag of days.

:func:`index_series` returns each bar's byte offset as well as its content. That is what makes
sealing possible: a day can be attested against an exact prefix of an exact file, so appending
tomorrow's bars leaves today's evidence untouched while rewriting today's bytes breaks it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LAG_BOUND_MS",
    "INTERVAL_MS",
    "Bar",
    "SeriesIndex",
    "StoreError",
    "index_series",
    "prefix_digest",
    "read_series",
]

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}

#: The lag bounds already frozen by WP-EDGE-04's coverage rule. A daily bar (or a 1h bar)
#: stored within this long of closing counts as observed; anything later is history.
DEFAULT_LAG_BOUND_MS: dict[str, int] = {
    "1m": 180_000,
    "5m": 600_000,
    "15m": 1_800_000,
    "1h": 7_200_000,
    "4h": 14_400_000,
}


class StoreError(RuntimeError):
    """The store cannot be read as evidence, so no statement about it may be made."""


@dataclass(frozen=True, slots=True)
class Bar:
    """One stored bar, with the two instants that matter and the lag between them."""

    asset: str
    interval: str
    open_ms: int
    close_ms: int
    fetched_at_ms: int
    closed: bool
    payload_sha256: str | None

    @property
    def lag_ms(self) -> int:
        """How long after the bar closed it was stored. Negative is impossible, not clamped."""
        return self.fetched_at_ms - self.close_ms

    def day(self) -> str:
        """UTC calendar day of the bar's *open*. A day holds exactly ``86400000/interval`` bars."""
        from datetime import UTC, datetime

        return datetime.fromtimestamp(self.open_ms / 1000, UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class SeriesIndex:
    """A whole series file, indexed: every bar plus the byte offset just past it."""

    interval: str
    asset: str
    path: Path
    bars: tuple[Bar, ...]
    byte_ends: tuple[int, ...]
    total_bytes: int

    def __post_init__(self) -> None:
        if len(self.bars) != len(self.byte_ends):
            raise StoreError("bars and byte offsets disagree")
        if self.total_bytes < 1:
            raise StoreError(f"{self.path} is empty; an empty series is not evidence")

    def day_end(self, day: str) -> int | None:
        """Byte offset just past the last bar whose open falls on ``day``, or ``None``.

        ``None`` means the series holds no bar for that day at all, which is different from
        holding a bar with a bad lag. The caller must not conflate the two.
        """
        found: int | None = None
        for end, bar in zip(self.byte_ends, self.bars, strict=True):
            if bar.day() == day:
                found = end
        return found

    def bars_on(self, day: str) -> tuple[Bar, ...]:
        return tuple(bar for bar in self.bars if bar.day() == day)


def _parse_line(raw: bytes, path: Path, line_number: int, asset: str, interval: str) -> Bar:
    try:
        record: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        # Failing closed is the point: a corrupt line could be the one bar that would have
        # made a backfilled day look prospective, or vice versa.
        raise StoreError(f"{path}:{line_number} is not JSON: {error}") from error
    if not isinstance(record, dict):
        raise StoreError(f"{path}:{line_number} is not an object")
    try:
        open_ms = int(record["ts"])
        fetched_at_ms = int(record["fetched_at_ms"])
    except (KeyError, TypeError, ValueError) as error:
        raise StoreError(f"{path}:{line_number} lacks ts/fetched_at_ms") from error
    declared_interval = str(record.get("interval") or interval)
    if declared_interval != interval:
        raise StoreError(
            f"{path}:{line_number} declares interval {declared_interval!r} inside a {interval!r} series"
        )
    if interval not in INTERVAL_MS:
        raise StoreError(f"unknown interval {interval!r}")
    span = INTERVAL_MS[interval]
    return Bar(
        asset=asset,
        interval=interval,
        open_ms=open_ms,
        close_ms=open_ms + span,
        fetched_at_ms=fetched_at_ms,
        closed=bool(record.get("closed", False)),
        payload_sha256=record.get("payload_sha256"),
    )


def read_series(path: Path, asset: str, interval: str) -> tuple[Bar, ...]:
    """Every bar in one series file, or :class:`StoreError`."""
    index = index_series(path, asset, interval)
    return index.bars


def index_series(path: Path, asset: str, interval: str) -> SeriesIndex:
    """Read one series file once, keeping each bar's byte offset.

    The file is read as bytes so that offsets refer to the file, not to a decoded string whose
    length in characters need not equal its length in bytes for a non-ASCII payload.
    """
    path = Path(path)
    if not path.is_file():
        raise StoreError(f"{path} does not exist")
    raw = path.read_bytes()
    bars: list[Bar] = []
    ends: list[int] = []
    offset = 0
    line_number = 0
    for line in raw.splitlines(keepends=True):
        line_number += 1
        stripped = line.strip()
        offset += len(line)
        if not stripped:
            continue
        bars.append(_parse_line(stripped, path, line_number, asset, interval))
        ends.append(offset)
    if not bars:
        raise StoreError(f"{path} holds no bars")
    return SeriesIndex(
        interval=interval,
        asset=asset,
        path=path,
        bars=tuple(bars),
        byte_ends=tuple(ends),
        total_bytes=len(raw),
    )


def prefix_digest(path: Path, byte_length: int) -> str:
    """sha256 of exactly the first ``byte_length`` bytes, refusing a file that shrank.

    Prefix rather than whole-file hashing is deliberate. The store grows every hour; a
    whole-file digest would make yesterday's attestation invalid today, and a format that
    invalidates its own evidence daily is one people learn to re-seal rather than to check.
    """
    path = Path(path)
    if byte_length < 0:
        raise StoreError("byte_length must be >= 0")
    with path.open("rb") as handle:
        payload = handle.read(byte_length)
    if len(payload) != byte_length:
        raise StoreError(
            f"{path} is {len(payload)} bytes but {byte_length} were attested: the store was truncated"
        )
    return hashlib.sha256(payload).hexdigest()
