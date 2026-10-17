"""oos_capture — append-only, atomic, resumable capture of a frozen holdout.

WP-EDGE-017/P0.1. WP-EDGE-016 published the holdout collector as "idempotent,
appends only new bars". The code did neither: ``_write_slice`` opened the slice
with ``w``, so every ``--capture`` truncated the file and rewrote it with
whatever the venue returned for one unpaginated ``limit=1000`` page. Two
consequences, both silent:

* bars captured by an earlier run that the current page no longer contained
  were destroyed — the file could only ever shrink back to one page;
* once the frozen window grew past one page, the fetch (anchored at the fixed
  freeze instant) would keep returning the *oldest* 1000 bars, so the newest
  hour was never seen at all while the history it re-fetched was rewritten.

This module is the contract that replaced it, kept out of the script so it can
be tested without a network:

* **append-only**: existing rows are read first and an incoming row never
  replaces them. A key that arrives with different content is a *conflict* —
  the first capture wins, and the conflict is returned and recorded, never
  silently dropped;
* **atomic**: the merged slice is written to a temporary file in the same
  directory and moved over the target with ``os.replace``, so a crash leaves
  either the old file or the new one, never half of each;
* **single-writer**: the read-merge-write transaction takes a sibling lock
  file first, so two overlapping captures serialise instead of one silently
  overwriting the rows the other just added. An atomic replace prevents a torn
  file; it does not prevent a lost update, which is why the lock exists;
* **resumable**: the next fetch starts at the newest bar the slice already
  holds for that symbol (plus one period), not at the freeze instant;
* **paginated**: a symbol is fetched page by page until the venue stops
  returning new bars, and a short page is confirmed by a second request before
  it is believed — a truncated retry is the exact failure the old code could
  not distinguish from "no more data";
* **closed only**: a bar whose close has not happened yet is not admitted, so a
  live current-hour candle can never enter the holdout.

The independent coverage ladder lives here too: it answers "how many expected
bars exist, how many were captured, how many were evaluated" from the slice and
the lane's own ledger, one row per (symbol, hour). WP-EDGE-016 reduced the whole
slice to ``{symbol: last_timestamp}``, which could only ever report one bar per
symbol, and then "checked" duplicates by comparing a dict's keys with their own
set.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PERIOD_MS_1H = 3_600_000

SCHEMA_VERSION = "EDGE17_OOS_CAPTURE_V1"


class CaptureIntegrityError(RuntimeError):
    """The slice on disk cannot be read as a slice; never guess our way past it."""


class CaptureLockTimeout(RuntimeError):
    """Another collector holds this slice; writing now would drop its bars."""


@dataclass(frozen=True, slots=True)
class MergeResult:
    """What merging one fetch into the existing slice did, auditable row by row."""

    rows: list[dict[str, Any]]
    added: int
    duplicates_identical: int
    conflicts: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def keys(self) -> list[tuple[str, int]]:
        return [row_key(row) for row in self.rows]


@dataclass(frozen=True, slots=True)
class SliceWrite:
    """What one locked read-merge-write transaction did to the slice."""

    path: Path
    merge: MergeResult
    rows_before: int
    sha256_before: str
    rows_after: int
    sha256_after: str
    bytes_written: int


@dataclass(frozen=True, slots=True)
class PaginationResult:
    """Bars a paginated fetch produced, and why it stopped."""

    rows: list[list[float]]
    pages: int
    stop_reason: str
    fetch_calls: int
    truncated: bool
    retried_short_pages: int


class _FetchProgressError(RuntimeError):
    """A page did not advance the cursor; retrying it would loop forever."""


def row_key(row: dict[str, Any]) -> tuple[str, int]:
    """The identity of a bar: venue-independent ``(symbol, open_ms)``."""
    return str(row["symbol"]), int(row["timestamp"])


def normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    """One canonical JSON shape, so two captures of the same bar hash equally."""
    return {
        "symbol": str(row["symbol"]),
        "timestamp": int(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


def row_from_ccxt(symbol: str, raw: Sequence[float]) -> dict[str, Any]:
    """A venue row (``[open_ms, o, h, l, c, v]``) as a slice row."""
    return normalise_row(
        {
            "symbol": symbol,
            "timestamp": int(raw[0]),
            "open": raw[1],
            "high": raw[2],
            "low": raw[3],
            "close": raw[4],
            "volume": raw[5],
        }
    )


def read_slice(path: Path) -> list[dict[str, Any]]:
    """Read the slice, or return ``[]`` when it does not exist yet.

    A line that is not a JSON object with the five OHLCV fields is a corrupt
    slice, not an empty one: raising is the only answer that does not lose
    evidence.
    """
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            rows.append(normalise_row(row))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CaptureIntegrityError(
                f"{path.name}:{number}: unreadable slice row: {exc}"
            ) from exc
    return rows


def merge_slice(
    existing: Iterable[dict[str, Any]], incoming: Iterable[dict[str, Any]]
) -> MergeResult:
    """Union of two slices, keyed by ``(symbol, open_ms)``; the first write wins.

    Order is deterministic (symbol, then open) so re-running an unchanged
    capture rewrites the same bytes, and an unchanged slice can be proven
    unchanged by its digest instead of by a promise.
    """
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for row in existing:
        merged[row_key(row)] = normalise_row(row)

    added = 0
    duplicates = 0
    conflicts: list[dict[str, Any]] = []
    for row in incoming:
        candidate = normalise_row(row)
        key = row_key(candidate)
        if key not in merged:
            merged[key] = candidate
            added += 1
            continue
        if merged[key] == candidate:
            duplicates += 1
            continue
        conflicts.append(
            {
                "symbol": key[0],
                "timestamp": key[1],
                "kept": merged[key],
                "rejected": candidate,
                "rule": "the first captured value of a bar is immutable",
            }
        )

    rows = [merged[key] for key in sorted(merged, key=lambda k: (k[0], k[1]))]
    return MergeResult(
        rows=rows, added=added, duplicates_identical=duplicates, conflicts=tuple(conflicts)
    )


def slice_sha256(rows: Sequence[dict[str, Any]]) -> str:
    """Digest of the canonical byte serialisation the writer produces."""
    payload = "".join(
        json.dumps(normalise_row(row), sort_keys=True) + "\n" for row in rows
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def write_slice_atomic(path: Path, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Write the whole slice atomically; report what landed on disk.

    ``os.replace`` is atomic on the same filesystem, which is why the temporary
    file is created next to the target rather than in the system temp dir. The
    handle is flushed and fsynced before the move so a power loss cannot leave a
    renamed-but-empty file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(normalise_row(row), sort_keys=True) + "\n" for row in rows)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return {
        "path": path.as_posix(),
        "rows": len(rows),
        "bytes": len(payload.encode()),
        "sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }


def lock_path_for(path: Path) -> Path:
    """The sibling lock of a slice: same directory, so it lives on the same volume."""
    return path.with_name(path.name + ".lock")


def _lock_age_s(lock_path: Path) -> float:
    """Seconds since the lock was taken; ``0`` when it is already gone."""
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except FileNotFoundError:
        return 0.0


@contextmanager
def slice_lock(
    path: Path,
    *,
    timeout_s: float = 30.0,
    stale_after_s: float = 600.0,
    poll_s: float = 0.05,
) -> Iterator[Path]:
    """Hold the slice's single-writer lock for the body of the block.

    ``O_CREAT|O_EXCL`` is atomic on every platform Python supports, so exactly
    one collector owns the slice. The lock is held only around read-merge-write
    — milliseconds — never across a network fetch, which is why a lock older
    than ``stale_after_s`` is a crashed writer and is reclaimed. A waiter that
    exceeds ``timeout_s`` raises instead of writing, because writing after the
    deadline would be exactly the lost update the lock exists to prevent.
    """
    lock_path = lock_path_for(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + float(timeout_s)
    while True:
        try:
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            age = _lock_age_s(lock_path)
            if age > float(stale_after_s):
                with suppress(FileNotFoundError):  # another waiter reclaimed it first
                    lock_path.unlink()
                continue
            if time.monotonic() >= deadline:
                raise CaptureLockTimeout(
                    f"{lock_path.name} has been held for {age:.1f}s; refusing to write "
                    "the slice while another collector owns it"
                ) from None
            time.sleep(float(poll_s))
            continue
        try:
            os.write(handle, f"{os.getpid()} {time.time():.3f}\n".encode())
            os.fsync(handle)
        except BaseException:
            # Do not leave a lock behind that the next collector would wait out:
            # this host runs at 99% disk, so a failed write is a real branch.
            os.close(handle)
            with suppress(OSError):
                lock_path.unlink()
            raise
        os.close(handle)
        break

    try:
        yield lock_path
    finally:
        with suppress(FileNotFoundError):
            lock_path.unlink()


def merge_and_write(
    path: Path,
    incoming: Iterable[dict[str, Any]],
    *,
    timeout_s: float = 30.0,
    stale_after_s: float = 600.0,
) -> SliceWrite:
    """The only supported way to add bars: lock, re-read, merge, replace atomically.

    Re-reading under the lock is the point. A collector that read the slice before
    a long fetch may hold a stale snapshot; merging that snapshot would erase every
    row a second collector wrote in the meantime. Here the merge is always against
    the bytes that are on disk while the lock is held.
    """
    incoming_rows = [normalise_row(row) for row in incoming]
    with slice_lock(path, timeout_s=timeout_s, stale_after_s=stale_after_s):
        existing = read_slice(path)
        merge = merge_slice(existing, incoming_rows)
        written = write_slice_atomic(path, merge.rows)
        return SliceWrite(
            path=path,
            merge=merge,
            rows_before=len(existing),
            sha256_before=slice_sha256(existing),
            rows_after=int(written["rows"]),
            sha256_after=str(written["sha256"]),
            bytes_written=int(written["bytes"]),
        )


def is_closed(open_ms: int, now_ms: int, period_ms: int = PERIOD_MS_1H) -> bool:
    """A bar is evidence only once the bar after it has started."""
    return int(open_ms) + int(period_ms) <= int(now_ms)


def closed_only(
    rows: Iterable[dict[str, Any]], *, now_ms: int, period_ms: int = PERIOD_MS_1H
) -> list[dict[str, Any]]:
    """Drop the still-forming current-hour bar, and say nothing else."""
    return [
        normalise_row(row) for row in rows if is_closed(int(row["timestamp"]), now_ms, period_ms)
    ]


def last_open_ms(rows: Iterable[dict[str, Any]], symbol: str) -> int | None:
    opens = [int(row["timestamp"]) for row in rows if str(row["symbol"]) == symbol]
    return max(opens) if opens else None


def next_since_ms(
    rows: Iterable[dict[str, Any]],
    symbol: str,
    *,
    floor_ms: int,
    period_ms: int = PERIOD_MS_1H,
) -> int:
    """Where the next fetch for ``symbol`` must start.

    The freeze instant on a cold slice; one period past the newest held bar on a
    warm one. This is the whole of "resumable": a collector that restarts fills
    the gap forward from what it already has instead of re-downloading (and,
    in the old code, overwriting) the history.
    """
    newest = last_open_ms(rows, symbol)
    if newest is None:
        return int(floor_ms)
    return max(int(floor_ms), newest + int(period_ms))


def paginate(
    fetch_page: Callable[[int, int], Sequence[Sequence[float]]],
    *,
    since_ms: int,
    end_ms: int,
    period_ms: int = PERIOD_MS_1H,
    page_limit: int = 1000,
    max_pages: int = 200,
    retry_short_pages: int = 1,
) -> PaginationResult:
    """Fetch ``[since_ms, end_ms)`` page by page until the venue has no more.

    ``fetch_page(since, limit)`` is the venue call. A page that returns fewer
    rows than asked for is *confirmed* with one more request before it is
    believed, because a truncated retry looks exactly like the end of history —
    the ambiguity that used to cost bars. No progress twice in a row is an
    error rather than a spin.
    """
    rows: dict[int, list[float]] = {}
    cursor = int(since_ms)
    pages = 0
    fetch_calls = 0
    retried = 0
    short_confirmations = 0
    stop_reason = "END_OF_WINDOW"
    truncated = False

    while cursor < end_ms:
        if pages >= max_pages:
            truncated = True
            stop_reason = "PAGE_LIMIT_REACHED"
            break
        batch = list(fetch_page(cursor, page_limit))
        fetch_calls += 1
        pages += 1

        opens = sorted(int(item[0]) for item in batch)
        for item in batch:
            open_ms = int(item[0])
            if since_ms <= open_ms < end_ms and open_ms not in rows:
                rows[open_ms] = list(item)

        if not opens:
            short_confirmations += 1
            if short_confirmations > retry_short_pages:
                stop_reason = "VENUE_EXHAUSTED"
                break
            continue

        newest = max(opens)
        next_cursor = newest + period_ms
        if next_cursor <= cursor:
            raise _FetchProgressError(
                f"page did not advance the cursor (asked from {cursor}, newest {newest})"
            )
        cursor = next_cursor

        if len(batch) < page_limit:
            short_confirmations += 1
            # only a confirmation that can actually fetch again is a retry; when
            # the cursor already reached the window there is nothing left to ask
            if short_confirmations <= retry_short_pages and cursor < end_ms:
                retried += 1
                continue
            stop_reason = "SHORT_PAGE_CONFIRMED"
            break
        short_confirmations = 0

    return PaginationResult(
        rows=[rows[key] for key in sorted(rows)],
        pages=pages,
        stop_reason=stop_reason,
        fetch_calls=fetch_calls,
        truncated=truncated,
        retried_short_pages=retried,
    )


# --------------------------------------------------------------------------------------
# independent coverage ladder
# --------------------------------------------------------------------------------------

STAGES: tuple[str, ...] = (
    "EXPECTED",
    "OBSERVED",
    "VALIDATED",
    "EVALUATED",
    "NO_SIGNAL",
    "PROPOSAL",
    "RISK_RESULT",
    "SIM_ORDER",
    "FILL",
    "RECONCILIATION",
)


def expected_closed_opens(freeze_ms: int, now_ms: int, period_ms: int = PERIOD_MS_1H) -> list[int]:
    """Every hourly bar that opened after the freeze and has already closed."""
    if freeze_ms <= 0:
        return []
    first = ((int(freeze_ms) // period_ms) + 1) * period_ms
    return [
        open_ms
        for open_ms in range(first, int(now_ms), period_ms)
        if is_closed(open_ms, now_ms, period_ms)
    ]


def coverage_ladder(
    *,
    symbols: Sequence[str],
    expected_opens: Sequence[int],
    slice_rows: Iterable[dict[str, Any]],
    lane_rows: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One row per (symbol, expected hour) with the furthest stage it reached.

    The slice is indexed by its full key, so a symbol holding thirty bars
    reports thirty OBSERVED rows. WP-EDGE-016 collapsed it to one timestamp per
    symbol, which made ``captured_bars_per_symbol`` a constant 1 and turned
    every earlier hour into a false MISSING.
    """
    slice_rows_list = list(slice_rows)
    observed_keys = {row_key(row) for row in slice_rows_list}
    lane = {(str(row["symbol"]), int(row["ts_ms"])): row for row in lane_rows}

    ladder: list[dict[str, Any]] = []
    for symbol in symbols:
        for open_ms in expected_opens:
            row: dict[str, Any] = {
                "symbol": symbol,
                "open_ms": int(open_ms),
                "expected_key": f"BINANCE_SPOT|{symbol}|1h|{int(open_ms)}",
                "stages": ["EXPECTED"],
                "missing": True,
            }
            if (symbol, int(open_ms)) in observed_keys:
                row["stages"].append("OBSERVED")
                row["missing"] = False
                row["captured_in"] = "OOS_PROSPECTIVE_1H.jsonl"
                entry = lane.get((symbol, int(open_ms)))
                if entry is not None:
                    row["stages"].append("VALIDATED")
                    for stage in entry.get("stages", []):
                        if stage in STAGES and stage not in row["stages"]:
                            row["stages"].append(stage)
                    if "PROPOSAL" not in entry.get("stages", []):
                        row["stages"].append("NO_SIGNAL")
            if row["missing"]:
                row["classified"] = "MISSING_NO_COLLECTOR"
            ladder.append(row)

    per_symbol: dict[str, dict[str, int]] = {
        symbol: {"expected": 0, "observed": 0, "evaluated": 0, "missing": 0} for symbol in symbols
    }
    for row in ladder:
        bucket = per_symbol[row["symbol"]]
        bucket["expected"] += 1
        bucket["observed"] += 0 if row["missing"] else 1
        bucket["evaluated"] += 1 if "EVALUATED" in row["stages"] else 0
        bucket["missing"] += 1 if row["missing"] else 0

    expected_keys = {(symbol, int(open_ms)) for symbol in symbols for open_ms in expected_opens}
    duplicates = len(slice_rows_list) - len(observed_keys)
    totals = {
        "expected_symbol_bars": len(expected_opens) * len(symbols),
        "observed_symbol_bars": sum(1 for row in ladder if not row["missing"]),
        "evaluated_symbol_bars": sum(1 for row in ladder if "EVALUATED" in row["stages"]),
        "bars_with_a_proposal": sum(1 for row in ladder if "PROPOSAL" in row["stages"]),
        "bars_with_a_fill": sum(1 for row in ladder if "FILL" in row["stages"]),
        "unexpected_symbol_bars": len(observed_keys - expected_keys),
        "duplicate_slice_rows": duplicates,
        "slice_rows": len(slice_rows_list),
        "per_symbol": per_symbol,
        "identity_holds": len(expected_opens) * len(symbols)
        == sum(1 for row in ladder if not row["missing"])
        + sum(1 for row in ladder if row["missing"]),
    }
    return ladder, totals


__all__ = [
    "STAGES",
    "CaptureIntegrityError",
    "CaptureLockTimeout",
    "MergeResult",
    "PaginationResult",
    "SliceWrite",
    "closed_only",
    "coverage_ladder",
    "expected_closed_opens",
    "is_closed",
    "last_open_ms",
    "lock_path_for",
    "merge_and_write",
    "merge_slice",
    "next_since_ms",
    "normalise_row",
    "paginate",
    "read_slice",
    "row_from_ccxt",
    "row_key",
    "slice_lock",
    "slice_sha256",
    "write_slice_atomic",
]
