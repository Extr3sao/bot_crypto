"""Forward dataset storage: rotation, fingerprints, manifest, resume (§20-§24).

Layout — deliberately boring, portable and append-only::

    <root>/
      segments/<source>/<market>/<symbol>/<event_type>/<UTC date>/<HHMMSS>.jsonl
      manifest/<run_id>.json
      state/<run_id>.json
      reports/...

The file name is the **rotation bucket start** in UTC, so a segment path is a
pure function of its own metadata: given an event you can compute where it must
live, and given a path you know exactly which window it covers. That is what
makes the dataset auditable after the fact.

Design commitments:

* ``append-safe`` — one JSON object per line, written and flushed as a whole
  line. A crash can only ever leave a trailing partial line, which readers
  detect and report as ``partial_tail`` instead of silently ignoring (§30).
* ``restartable`` — ``state/<run_id>.json`` records where each stream stopped;
  a resume re-opens the same segments and records the interruption as a
  *documented gap* rather than pretending the run never stopped (§24, §27).
* ``auditable`` — every sealed segment gets a fingerprint
  (``row_count``, first/last event time, ``sha256``, ``schema_version``, bytes).
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
from bisect import bisect_left
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from trading_bot.research.forward.contract import (
    BACKFILL_ORIGIN,
    EventType,
    RawEvent,
    Transport,
    parse_event,
)
from trading_bot.research.forward.outcome import (
    FAILURE_STORAGE,
    CaptureOutcome,
    CaptureStatus,
    classify_capture,
)
from trading_bot.research.forward.resources import percentile_from_histogram

__all__ = [
    "CONTINUITY_CONTINUOUS",
    "CONTINUITY_INCOMPLETE",
    "DEFAULT_ROOT",
    "GAP_RECOVERED_COMPLETE",
    "GAP_RECOVERED_PARTIAL",
    "GAP_STATUSES",
    "GAP_UNRECOVERABLE",
    "LATENCY_LADDER_MS",
    "LATENCY_STEP",
    "GapRecord",
    "LatencyHistogram",
    "RunManifest",
    "SegmentFingerprint",
    "SegmentWriter",
    "StreamManifest",
    "StreamStats",
    "classify_gaps",
    "format_utc",
    "gap_class",
    "is_compressed_segment",
    "iter_segment_records",
    "iter_segment_rows",
    "load_json",
    "load_manifest",
    "load_resume_state",
    "manifest_outcome",
    "merge_latency_histograms",
    "read_segment",
    "rotation_bucket_start",
    "save_json",
    "save_resume_state",
    "segment_relative_path",
    "segment_suffix",
    "sha256_bytes",
    "sha256_file",
    "stream_key_from_path",
]

DEFAULT_ROOT: Final[str] = "reports/microstructure-forward"
CONTINUITY_CONTINUOUS: Final[str] = "CONTINUOUS_DATA"
CONTINUITY_INCOMPLETE: Final[str] = "INCOMPLETE_DATA"

#: Global (non per-symbol) streams live under this sentinel symbol directory.
GLOBAL_SYMBOL: Final[str] = "_GLOBAL"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    """Streaming sha256 plus byte size, so a 2 GB segment never lands in RAM."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def format_utc(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def rotation_bucket_start(ms: int, rotation_seconds: int) -> int:
    """Start (ms) of the deterministic rotation bucket containing ``ms``."""
    if rotation_seconds <= 0:
        raise ValueError("rotation_seconds must be > 0")
    width = rotation_seconds * 1000
    return (ms // width) * width


def segment_relative_path(
    source: str,
    market: str,
    symbol: str,
    event_type: EventType,
    bucket_start_ms: int,
    *,
    compressed: bool = True,
) -> str:
    """Deterministic path for a segment. Pure function of its own window."""
    moment = datetime.fromtimestamp(bucket_start_ms / 1000, tz=UTC)
    stamp = moment.strftime("%H%M%S")
    filename = f"{stamp}.jsonl.gz" if compressed else f"{stamp}.jsonl"
    return "/".join(
        (
            "segments",
            source,
            market,
            symbol,
            event_type.value,
            moment.strftime("%Y-%m-%d"),
            filename,
        )
    )


def segment_suffix(compressed: bool) -> str:
    return ".jsonl.gz" if compressed else ".jsonl"


def is_compressed_segment(path: Path) -> bool:
    return path.suffix == ".gz"


def _open_segment_text(path: Path) -> Any:
    """Text-mode reader for a plain or gzip segment."""
    if is_compressed_segment(path):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _open_segment_append(path: Path, compresslevel: int) -> Any:
    """Text-mode appender. gzip append starts a fresh member per open()."""
    if is_compressed_segment(path):
        return gzip.open(path, "at", compresslevel=compresslevel, encoding="utf-8", newline="\n")
    return path.open("a", encoding="utf-8", newline="\n")


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, path)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------- gaps
#: §2 — the only three places a gap can land.
GAP_RECOVERED_COMPLETE: Final[str] = "RECOVERED_COMPLETE"
GAP_RECOVERED_PARTIAL: Final[str] = "RECOVERED_PARTIAL"
GAP_UNRECOVERABLE: Final[str] = "UNRECOVERABLE"
GAP_STATUSES: Final[tuple[str, ...]] = (
    GAP_RECOVERED_COMPLETE,
    GAP_RECOVERED_PARTIAL,
    GAP_UNRECOVERABLE,
)


@dataclass(frozen=True, slots=True)
class GapRecord:
    """A hole in the capture, with an honest description of how it arose."""

    market: str
    symbol: str
    event_type: str
    start_ms: int
    end_ms: int
    reason: str
    #: True only when the data in this window was actually restored (the public
    #: aggregate-trade index is the one source that can do it). A reconnect that
    #: merely reopened the socket is *not* recovery, and calling it so would be
    #: the false continuity §27 forbids.
    recovered: bool
    data_lost: bool = True
    estimated_lost_events: int | None = None
    #: Events restored by a backfill, so recovery is auditable, not asserted.
    recovered_events: int = 0
    #: Stable identifier so a gap can be followed across its lifecycle events.
    gap_id: str = ""
    detail: str | None = None

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def status(self) -> str:
        """§2 — where this gap ended up: recovered, partial, or unrecoverable."""
        if self.recovered:
            return GAP_RECOVERED_COMPLETE
        if self.recovered_events > 0:
            return GAP_RECOVERED_PARTIAL
        return GAP_UNRECOVERABLE

    @property
    def remaining_missing(self) -> int | None:
        """How much of the hole is still a hole, when the size was measurable."""
        if self.estimated_lost_events is None:
            return None
        return max(0, self.estimated_lost_events - self.recovered_events)

    def resolve(
        self, *, recovered: bool, recovered_events: int, detail: str | None = None
    ) -> GapRecord:
        """Return this gap after a recovery attempt, preserving detected size."""
        return replace(
            self,
            recovered=recovered,
            recovered_events=recovered_events,
            data_lost=not recovered,
            detail=detail if detail is not None else self.detail,
        )

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["duration_ms"] = self.duration_ms
        payload["status"] = self.status
        payload["remaining_missing"] = self.remaining_missing
        return payload


# ------------------------------------------------------------------- fingerprints
#: The event type whose holes the public index can walk forward. Every other
#: stream is websocket-only, so a hole in it is lost for good.
BACKFILLABLE_EVENT_TYPE: Final[str] = "agg_trade"


def gap_class(gap: GapRecord) -> str:
    """D-10 — what can still be done about this hole, in one word.

    ``RECOVERED`` and ``PARTIAL`` are outcomes the backfill already produced.
    ``RECOVERABLE`` is a hole the provider's trade index can still be walked
    through (aggregate trades, not yet resolved). ``UNRECOVERABLE`` is everything
    else — including a trade hole whose backfill ran and came back empty — and it
    is a claim about the *source*, not about our effort.
    """
    if gap.recovered:
        return "RECOVERED"
    if gap.recovered_events > 0:
        return "PARTIAL"
    if gap.event_type == BACKFILLABLE_EVENT_TYPE and gap.detail is None:
        return "RECOVERABLE"
    return "UNRECOVERABLE"


def classify_gaps(gaps: Sequence[GapRecord]) -> dict[str, Any]:
    """Group a run's holes by what can be done about them (D-10).

    A count alone (``gaps: 34``) cannot be acted on: an operator needs to know how
    much of the loss is still recoverable, how much is gone, and why. This is the
    same policy the collector applies, read back from the records rather than
    re-decided in a report.
    """
    by_class: dict[str, int] = {"RECOVERED": 0, "PARTIAL": 0, "RECOVERABLE": 0, "UNRECOVERABLE": 0}
    seconds_by_class: dict[str, float] = {key: 0.0 for key in by_class}
    by_reason: dict[str, int] = {}
    by_event_type: dict[str, int] = {}
    lost_ids: list[str] = []
    for gap in gaps:
        label = gap_class(gap)
        by_class[label] = by_class.get(label, 0) + 1
        if gap.data_lost:
            seconds_by_class[label] = seconds_by_class.get(label, 0.0) + gap.duration_ms / 1000.0
        by_reason[gap.reason] = by_reason.get(gap.reason, 0) + 1
        by_event_type[gap.event_type] = by_event_type.get(gap.event_type, 0) + 1
        if label == "UNRECOVERABLE" and len(lost_ids) < 50:
            lost_ids.append(gap.gap_id)
    return {
        "total": len(gaps),
        "by_class": by_class,
        "lost_seconds_by_class": {key: round(value, 3) for key, value in seconds_by_class.items()},
        "by_reason": dict(sorted(by_reason.items())),
        "by_event_type": dict(sorted(by_event_type.items())),
        "unrecoverable_gap_ids": lost_ids,
        "unrecoverable_gap_ids_truncated": max(0, by_class.get("UNRECOVERABLE", 0) - len(lost_ids)),
        "policy": (
            f"a {BACKFILLABLE_EVENT_TYPE} hole is recoverable while its backfill has "
            "not been attempted; every other stream is websocket-only and a hole in "
            "it is unrecoverable"
        ),
    }


@dataclass(frozen=True, slots=True)
class SegmentFingerprint:
    """§23 — the identity of one partition of the dataset."""

    path: str
    row_count: int
    first_event_time: int | None
    last_event_time: int | None
    first_receive_time: int | None
    last_receive_time: int | None
    sha256: str
    bytes: int
    schema_version: str
    sealed: bool
    partial_tail: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_segment(path: Path, *, strict: bool = False) -> tuple[list[RawEvent], bool]:
    """Read a JSONL segment.

    Returns ``(events, partial_tail)``. A trailing line that does not parse is
    reported rather than dropped — a truncated write must be visible in the
    quality report, not laundered into a clean dataset. With ``strict=True`` it
    raises instead, which is what replay uses.
    """
    events: list[RawEvent] = []
    partial_tail = False
    handle = _open_segment_text(path)
    try:
        for lineno, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError("segment row is not a JSON object")
                events.append(parse_event(payload))
            except Exception as exc:
                partial_tail = True
                if strict:
                    raise ValueError(f"{path}:{lineno} unreadable row: {exc}") from exc
    except (EOFError, gzip.BadGzipFile, OSError):
        # A truncated final gzip member (crash mid-flush) is a partial tail, not
        # a reason to discard the complete members before it.
        partial_tail = True
        if strict:
            raise
    finally:
        handle.close()
    return events, partial_tail


def iter_segment_rows(path: Path) -> Iterator[tuple[dict[str, Any] | None, bool]]:
    """Yield a segment's rows one at a time, so memory stays bounded (§34).

    A forward hour of one busy stream is a single segment of ~10^6 rows, so any
    reader that materialises a segment cannot analyse a real capture. This is
    the streaming counterpart of :func:`iter_segment_records`: each item is
    ``(row, partial_tail)`` and the flag only ever becomes true on the final
    item, when a truncated tail or a live gzip member was reached.
    """
    handle = _open_segment_text(path)
    try:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                yield None, True
                return
            if not isinstance(payload, dict):
                yield None, True
                return
            yield payload, False
    except (EOFError, gzip.BadGzipFile, OSError):
        # A truncated final member is a partial tail, not a reason to discard
        # the complete members (or rows) before it.
        yield None, True
        return
    finally:
        handle.close()


def iter_segment_records(path: Path) -> tuple[list[dict[str, Any]], bool]:
    """Raw JSON objects (no contract rehydration) plus a ``partial_tail`` flag."""
    rows: list[dict[str, Any]] = []
    partial_tail = False
    handle = _open_segment_text(path)
    try:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                partial_tail = True
    except (EOFError, gzip.BadGzipFile, OSError):
        partial_tail = True
    finally:
        handle.close()
    return rows, partial_tail


def fingerprint_segment(path: Path, root: Path, *, sealed: bool) -> SegmentFingerprint:
    rows, partial_tail = iter_segment_records(path)
    digest, size = sha256_file(path)
    event_times: list[int] = [
        t for t in (r.get("exchange_event_time") for r in rows) if isinstance(t, int)
    ]
    receive_times: list[int] = [
        t for t in (r.get("receive_time") for r in rows) if isinstance(t, int)
    ]
    schema_versions: set[str] = {
        s for s in (r.get("schema_version") for r in rows) if isinstance(s, str)
    }
    return SegmentFingerprint(
        path=path.relative_to(root).as_posix(),
        row_count=len(rows),
        first_event_time=min(event_times) if event_times else None,
        last_event_time=max(event_times) if event_times else None,
        first_receive_time=min(receive_times) if receive_times else None,
        last_receive_time=max(receive_times) if receive_times else None,
        sha256=digest,
        bytes=size,
        schema_version=(
            next(iter(schema_versions))
            if len(schema_versions) == 1
            else f"MIXED:{sorted(schema_versions)}"
        ),
        sealed=sealed,
        partial_tail=partial_tail,
    )


# ------------------------------------------------------------------ segment writer
@dataclass(slots=True)
class _OpenSegment:
    handle: Any
    path: Path
    relative: str
    bucket_start: int = 0
    rows: int = 0
    bytes: int = 0
    first_event_time: int | None = None
    last_event_time: int | None = None
    first_receive_time: int | None = None
    last_receive_time: int | None = None
    dirty_since_fsync: int = 0


class SegmentWriter:
    """Append-only writer with deterministic rotation.

    One open handle per (source, market, symbol, event_type, bucket). Handles are
    flushed on every write by default so that a hard kill loses at most the line
    being written, and fsynced periodically so the on-disk dataset is durable
    without paying a syscall per event.
    """

    def __init__(
        self,
        root: Path,
        rotation_seconds: int = 3600,
        *,
        run_id: str = "UNSET",
        allow_existing_segments: bool = False,
        flush_every: int = 1,
        fsync_every: int = 500,
        source: str = "binance",
        compress: bool = True,
        compresslevel: int = 6,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id
        #: A segment's path is a pure function of the window it covers, so a run
        #: that is not resuming must not append to rows another run wrote: that
        #: would silently fuse two captures into one file (and one fingerprint).
        self.allow_existing_segments = allow_existing_segments
        self._written_paths: set[str] = set()
        self.rotation_seconds = rotation_seconds
        self.flush_every = max(1, flush_every)
        self.fsync_every = max(1, fsync_every)
        self.source = source
        # Compression is not a nicety here: JSON records compress ~10x, and a
        # capture that cannot run for days is not a forward dataset (§37, §43).
        self.compress = compress
        self.compresslevel = compresslevel
        self._open: dict[str, _OpenSegment] = {}
        self._sealed: list[SegmentFingerprint] = []
        self.total_bytes = 0
        self.total_rows = 0
        self._unflushed = 0
        self._seq = 0

    # ------------------------------------------------------------------ writing
    def write(self, event: RawEvent) -> str:
        self._seq += 1
        event = replace(event, write_seq=self._seq)
        key = self._key(event)
        bucket = rotation_bucket_start(event.receive_time, self.rotation_seconds)
        segment = self._open.get(key)
        if segment is not None and segment.bucket_start != bucket:
            # The path of a segment is a function of the window it covers, so a
            # segment may never hold an event from a later bucket. Rotating here
            # (not only on a timer) is what keeps that property true.
            self._seal(key)
            segment = None
        if segment is None:
            segment = self._open_segment(event, bucket)
        line = event.to_json()
        try:
            segment.handle.write(line + "\n")
        except (OSError, ValueError) as exc:  # pragma: no cover - disk failure path
            raise StorageError(f"failed to append to {segment.path}: {exc}") from exc
        segment.rows += 1
        segment.bytes += len(line.encode("utf-8")) + 1
        segment.dirty_since_fsync += 1
        segment.first_event_time = _min_opt(segment.first_event_time, event.exchange_event_time)
        segment.last_event_time = _max_opt(segment.last_event_time, event.exchange_event_time)
        segment.first_receive_time = _min_opt(segment.first_receive_time, event.receive_time)
        segment.last_receive_time = _max_opt(segment.last_receive_time, event.receive_time)
        self.total_rows += 1
        self._unflushed += 1
        if self._unflushed >= self.flush_every:
            self.flush()
        if segment.dirty_since_fsync >= self.fsync_every:
            self._fsync(segment)
        return key

    def _key(self, event: RawEvent) -> str:
        symbol = event.symbol if event.event_type not in _GLOBAL_EVENTS else GLOBAL_SYMBOL
        return f"{event.market.value}|{symbol}|{event.event_type.value}"

    def _open_segment(self, event: RawEvent, bucket: int) -> _OpenSegment:
        symbol = event.symbol if event.event_type not in _GLOBAL_EVENTS else GLOBAL_SYMBOL
        relative = segment_relative_path(
            self.source,
            event.market.value,
            symbol,
            event.event_type,
            bucket,
            compressed=self.compress,
        )
        path = self.root / relative
        if path.exists() and relative not in self._written_paths:
            if not self.allow_existing_segments:
                raise StorageError(
                    f"{path} already holds rows from an earlier capture; one dataset root "
                    f"belongs to one run (root={self.root}, run={self.run_id}). Write to a "
                    f"fresh --out, or --resume the run that owns this root."
                )
            self._written_paths.add(relative)
        self._written_paths.add(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = _open_segment_append(path, self.compresslevel)
        segment = _OpenSegment(
            handle=handle, path=path, relative=relative, bucket_start=bucket
        )
        self._open[self._key(event)] = segment
        return segment

    @staticmethod
    def _fsync(segment: _OpenSegment) -> None:
        segment.handle.flush()
        with contextlib.suppress(OSError):  # pragma: no cover - best effort durability
            os.fsync(segment.handle.fileno())
        segment.dirty_since_fsync = 0

    def flush(self) -> None:
        # ``GzipFile.flush`` uses Z_SYNC_FLUSH, so a sync-flushed member is
        # decodable up to that point even before the member is closed.
        for segment in self._open.values():
            segment.handle.flush()
        self._unflushed = 0

    def rotate(self, now_ms: int) -> None:
        """Close any open segment whose bucket no longer contains ``now_ms``.

        ``write`` already rotates on bucket change; this is the safety net that
        seals a stream which simply stopped producing events, so an idle segment
        is not left open (and therefore not left unfingerprinted) for hours.
        """
        current = rotation_bucket_start(now_ms, self.rotation_seconds)
        for key in [key for key, seg in self._open.items() if seg.bucket_start != current]:
            self._seal(key)

    def _seal(self, key: str) -> None:
        segment = self._open.pop(key)
        _close_segment(segment)
        self.total_bytes += segment.bytes
        self._sealed.append(fingerprint_segment(segment.path, self.root, sealed=True))

    def close(self) -> None:
        """Flush, fsync and fingerprint everything still open."""
        for key in list(self._open):
            self._seal(key)
        self.flush()

    # -------------------------------------------------------------- introspection
    @property
    def sealed_fingerprints(self) -> list[SegmentFingerprint]:
        return list(self._sealed)

    def open_segments(self) -> list[str]:
        return sorted(self._open)

    def fingerprints(self) -> list[SegmentFingerprint]:
        """Sealed fingerprints plus live, non-destructive ones for open segments.

        Open segments are flushed first so the hash matches the bytes on disk;
        they are marked ``sealed=False`` so a reader knows the file may still
        grow.
        """
        self.flush()
        live = [
            fingerprint_segment(segment.path, self.root, sealed=False)
            for segment in self._open.values()
        ]
        return sorted(self._sealed + live, key=lambda f: f.path)


def _close_segment(segment: _OpenSegment) -> None:
    """Close the handle (writing any gzip trailer) and fsync the finished file."""
    with contextlib.suppress(OSError, ValueError):
        segment.handle.flush()
        os.fsync(segment.handle.fileno())
    with contextlib.suppress(OSError, ValueError):
        segment.handle.close()
    # The gzip trailer is only written by close(), so durability has to be
    # asserted on the closed file rather than on the stream handle.
    with contextlib.suppress(OSError):
        fd = os.open(segment.path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _min_opt(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else min(current, value)


def _max_opt(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else max(current, value)


class StorageError(RuntimeError):
    """Raised when persistence itself fails. Always fatal to the collector."""


_GLOBAL_EVENTS: Final[frozenset[EventType]] = frozenset(
    {
        EventType.HEARTBEAT,
        EventType.GAP,
        EventType.VIOLATION,
        EventType.LIFECYCLE,
    }
)


# --------------------------------------------------------------------- statistics
#: Latency histogram geometry (§2). The per-stream latency state used to be a
#: ``list[int]`` that grew by one entry per observed event and was never read: an
#: unbounded writer-side allocation that made continuous operation impossible.
#: It is replaced by a *fixed* geometric ladder, so the writer keeps a constant
#: number of counters per stream no matter how many events arrive, while still
#: answering p50/p95/p99 to within one ladder step.
LATENCY_STEP: Final[float] = 1.05
LATENCY_CEILING_MS: Final[int] = 600_000


def _latency_ladder() -> tuple[int, ...]:
    values: list[int] = []
    current = 1.0
    while current < LATENCY_CEILING_MS:
        value = round(current)
        if not values or value > values[-1]:
            values.append(value)
        current *= LATENCY_STEP
    if not values or values[-1] < LATENCY_CEILING_MS:
        values.append(LATENCY_CEILING_MS)
    return tuple(values)


#: Upper bound (inclusive) of each strictly positive latency bucket, ascending.
LATENCY_LADDER_MS: Final[tuple[int, ...]] = _latency_ladder()

#: Bucket 0 absorbs every non-positive delay; one bucket per ladder rung follows;
#: the trailing bucket is the overflow (delays above the ceiling).
LATENCY_BUCKETS: Final[int] = len(LATENCY_LADDER_MS) + 2


def _is_backfilled(event: RawEvent) -> bool:
    """A recovered row's delay is the width of an outage, not network latency."""
    detail = event.detail
    return isinstance(detail, dict) and detail.get("origin") == BACKFILL_ORIGIN


@dataclass(slots=True)
class LatencyHistogram:
    """Bounded-memory latency distribution (§2, P1).

    Memory is ``LATENCY_BUCKETS`` integer counters *by construction* — it does not
    depend on how many events were observed. Bucket 0 holds non-positive delays
    (venue clock ahead of ours), then one bucket per ladder rung, then an overflow
    bucket. Quantiles are nearest-rank over the rungs and are bucket upper bounds,
    i.e. accurate to within :data:`LATENCY_STEP`.
    """

    counts: list[int] = field(default_factory=lambda: [0] * LATENCY_BUCKETS)
    samples: int = 0
    total_ms: int = 0
    min_ms: int | None = None
    max_ms: int | None = None

    def __post_init__(self) -> None:
        if len(self.counts) != LATENCY_BUCKETS:
            raise StorageError(
                f"latency histogram must hold exactly {LATENCY_BUCKETS} buckets, "
                f"got {len(self.counts)}"
            )

    def observe(self, delay_ms: int) -> None:
        self.counts[self._bucket(delay_ms)] += 1
        self.samples += 1
        self.total_ms += delay_ms
        if self.min_ms is None or delay_ms < self.min_ms:
            self.min_ms = delay_ms
        if self.max_ms is None or delay_ms > self.max_ms:
            self.max_ms = delay_ms

    @staticmethod
    def _bucket(delay_ms: int) -> int:
        if delay_ms <= 0:
            return 0
        return bisect_left(LATENCY_LADDER_MS, delay_ms) + 1

    def _upper_bound(self, index: int) -> float:
        if index == 0:
            return 0.0
        if index > len(LATENCY_LADDER_MS):
            # Reporting the observed maximum keeps the overflow bucket honest
            # instead of pretending its bound is the ceiling it exceeded.
            return float(self.max_ms) if self.max_ms is not None else float(LATENCY_CEILING_MS)
        return float(LATENCY_LADDER_MS[index - 1])

    def distribution(self) -> dict[int, int]:
        """Sparse ``upper bound -> count`` view; keys are bucket bounds, not samples."""
        out: dict[int, int] = {}
        for index, count in enumerate(self.counts):
            if count:
                bound = int(self._upper_bound(index))
                out[bound] = out.get(bound, 0) + count
        return out

    def merge_from(self, other: LatencyHistogram) -> None:
        """Fold another histogram in without materialising any sample (§2)."""
        if len(other.counts) != len(self.counts):
            raise StorageError("cannot merge latency histograms of different geometry")
        for index, count in enumerate(other.counts):
            self.counts[index] += count
        self.samples += other.samples
        self.total_ms += other.total_ms
        if other.min_ms is not None and (self.min_ms is None or other.min_ms < self.min_ms):
            self.min_ms = other.min_ms
        if other.max_ms is not None and (self.max_ms is None or other.max_ms > self.max_ms):
            self.max_ms = other.max_ms

    def quantile(self, fraction: float) -> float | None:
        """Nearest-rank percentile over the buckets, using the report's own semantics."""
        return percentile_from_histogram(self.distribution(), fraction)

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": round(self.total_ms / self.samples, 3) if self.samples else None,
            "p50_ms": self.quantile(0.50),
            "p95_ms": self.quantile(0.95),
            "p99_ms": self.quantile(0.99),
            "buckets": len(self.counts),
            "resolution_ratio": LATENCY_STEP,
            "counts": {str(key): value for key, value in sorted(self.distribution().items())},
            "note": (
                "fixed geometric histogram: memory is constant in the number of "
                f"events; quantiles are bucket upper bounds (<= {int((LATENCY_STEP - 1) * 100)}% "
                "step); recovered (backfilled) rows are excluded"
            ),
        }


def merge_latency_histograms(histograms: Iterable[LatencyHistogram]) -> LatencyHistogram:
    """Fold many stream histograms into one telemetry line, in bounded memory."""
    merged = LatencyHistogram()
    for histogram in histograms:
        merged.merge_from(histogram)
    return merged


@dataclass(slots=True)
class StreamStats:
    """Per-(market, symbol, event_type) counters feeding the manifest."""

    market: str
    symbol: str
    event_type: str
    transport: str
    lossless: bool = False
    events: int = 0
    first_receive_time: int | None = None
    last_receive_time: int | None = None
    first_event_time: int | None = None
    last_event_time: int | None = None
    duplicates: int = 0
    out_of_order: int = 0
    sequence_gaps: int = 0
    malformed: int = 0
    #: §2 — was an unbounded ``list[int]``; now a fixed-size histogram.
    latency: LatencyHistogram = field(default_factory=LatencyHistogram)
    clock_violations: int = 0

    def observe(self, event: RawEvent) -> None:
        self.events += 1
        self.first_receive_time = _min_opt(self.first_receive_time, event.receive_time)
        self.last_receive_time = _max_opt(self.last_receive_time, event.receive_time)
        self.first_event_time = _min_opt(self.first_event_time, event.exchange_event_time)
        self.last_event_time = _max_opt(self.last_event_time, event.exchange_event_time)
        delay = event.network_delay_ms
        if delay is not None and not _is_backfilled(event):
            self.latency.observe(delay)

    def as_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "symbol": self.symbol,
            "event_type": self.event_type,
            "transport": self.transport,
            "lossless": self.lossless,
            "events": self.events,
            "first_receive_time": self.first_receive_time,
            "last_receive_time": self.last_receive_time,
            "first_event_time": self.first_event_time,
            "last_event_time": self.last_event_time,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "sequence_gaps": self.sequence_gaps,
            "malformed": self.malformed,
            "clock_violations": self.clock_violations,
            "network_delay_ms": self.latency.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class StreamManifest:
    """§22 — one entry of the run manifest, per stream."""

    market: str
    symbol: str
    event_type: str
    transport: str
    lossless: bool
    events: int
    bytes: int
    first_receive_time: int | None
    last_receive_time: int | None
    gaps: int
    gap_seconds: float
    unrecovered_gap_seconds: float
    duplicates: int
    out_of_order: int
    sequence_gaps: int
    malformed: int
    reconnects: int
    resnapshots: int
    #: §2 — writer-side latency telemetry at the final HEAD: bounded histogram
    #: summary (p50/p95/p99, samples, resolution) instead of a per-event list.
    network_delay_ms: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunManifest:
    """§22/§27 — the auditable description of one capture run."""

    run_id: str
    collector_version: str
    contract_version: str
    schema_version: str
    provider: str
    market: str
    commit: str
    symbols: list[str]
    markets: list[str]
    started_at: str
    ended_at: str | None
    duration_seconds: float
    rotation_seconds: int
    continuity: str
    #: Book reconstruction parameters. Recorded because replay must use the same
    #: values to be able to reproduce the live book byte for byte.
    depth_n: int = 10
    stale_after_ms: int = 5_000
    streams: list[StreamManifest] = field(default_factory=list)
    provider_stream_status: dict[str, Any] = field(default_factory=dict)
    gaps: list[GapRecord] = field(default_factory=list)
    reconnects: int = 0
    resnapshots: int = 0
    bytes_written: int = 0
    uncompressed_bytes_written: int = 0
    disk_bytes_per_hour: float = 0.0
    #: §8/§9 — the disk budget the capture ran under, and whether it was hit. A
    #: guard nobody can audit from the manifest is not a guard.
    max_total_bytes: int | None = None
    stopped_on_disk_budget: bool = False
    #: §20 — whether the host-free-space guard is what ended the run. Both guard
    #: stops are CONTROLLED_STOP, and both say which guard fired.
    stopped_on_min_free: bool = False
    #: §51 — why the capture ended: ``duration reached``, ``stop file``,
    #: ``disk budget``, ``storage failure`` or ``signal``. A stop that has to be
    #: inferred from the absence of a manifest is what this field replaces.
    stop_reason: str | None = None
    #: §2 — COMPLETE | CONTROLLED_STOP | FAILED. The same verdict the process
    #: exit code carries, so an operator reading either sees the same thing.
    status: str = "COMPLETE"
    #: §2/§3 — why it failed, when it did. ``None`` on a clean or controlled end.
    failure_kind: str | None = None
    failure_reason: str | None = None
    fingerprints: list[SegmentFingerprint] = field(default_factory=list)
    resources: dict[str, Any] = field(default_factory=dict)
    book_health: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] = field(default_factory=dict)
    heartbeat_count: int = 0
    degradation_events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Gaps carry a derived ``duration_ms`` that ``asdict`` cannot see.
        payload["gaps"] = [gap.as_dict() for gap in self.gaps]
        # D-10 — the manifest a resumed capture leaves behind classifies its own
        # holes instead of only counting them. Derived here, on the read side, so
        # the capture entry point whose bytes produced the certified dataset does
        # not have to change to gain a diagnosis (see CAPTURE_CRITICAL_PATHS).
        payload["gaps_classification"] = classify_gaps(self.gaps)
        payload["exit_code"] = self.outcome().exit_code
        return payload

    def outcome(self) -> CaptureOutcome:
        """The run's verdict, read back from what the run recorded (§2)."""
        return CaptureOutcome(
            status=CaptureStatus(self.status),
            kind=self.failure_kind,
            reason=self.failure_reason,
            stop_reason=self.stop_reason,
        )

    @property
    def exit_code(self) -> int:
        """What the process that wrote this manifest must exit with."""
        return self.outcome().exit_code

    def save(self, root: Path) -> Path:
        path = Path(root) / "manifest" / f"{self.run_id}.json"
        save_json(path, self.as_dict())
        return path


def load_manifest(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise StorageError(f"{path}: manifest is not a JSON object")
    for key in ("run_id", "contract_version", "schema_version", "streams"):
        if key not in payload:
            raise StorageError(f"{path}: manifest missing required key {key!r}")
    return payload


def manifest_outcome(payload: dict[str, Any]) -> CaptureOutcome:
    """Read a manifest's verdict, including manifests written before §2 existed.

    §52 — a verifier may only read artifacts that were produced under test. An
    older manifest has no ``status``, so its outcome is derived from the fields
    it does have (``integrity.failures``, ``stop_reason``) through the same
    classifier the writer uses: no second opinion, one policy.
    """
    if payload.get("status"):
        return CaptureOutcome(
            status=CaptureStatus(str(payload["status"])),
            kind=payload.get("failure_kind"),
            reason=payload.get("failure_reason"),
            stop_reason=payload.get("stop_reason"),
        )
    integrity = payload.get("integrity") or {}
    failures = integrity.get("failures")
    clock_violations = int(integrity.get("clock_violations") or 0)
    book_failed = tuple(
        key
        for key, state in (payload.get("book_health") or {}).items()
        if isinstance(state, dict) and state.get("health") == "FAILED"
    )
    return classify_capture(
        stop_reason=payload.get("stop_reason"),
        fatal_kind=FAILURE_STORAGE if failures else None,
        fatal_reason=str(failures) if failures else None,
        clock_violations=clock_violations,
        book_failed_streams=book_failed,
    )


# ---------------------------------------------------------------------- resume
def save_resume_state(root: Path, run_id: str, payload: dict[str, Any]) -> Path:
    path = Path(root) / "state" / f"{run_id}.json"
    save_json(path, payload)
    return path


def load_resume_state(root: Path, run_id: str) -> dict[str, Any] | None:
    path = Path(root) / "state" / f"{run_id}.json"
    if not path.exists():
        return None
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise StorageError(f"{path}: resume state is not a JSON object")
    return payload


def latest_run_id(root: Path) -> str | None:
    """Most recent run whose resume state exists (used by ``--resume``)."""
    state_dir = Path(root) / "state"
    if not state_dir.is_dir():
        return None
    candidates = sorted(state_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    return candidates[-1].stem


def transport_for(event_type: EventType) -> Transport:
    from trading_bot.research.forward.contract import TRANSPORT_BY_EVENT_TYPE

    return TRANSPORT_BY_EVENT_TYPE[event_type]


def stream_key_from_path(path: str) -> tuple[str, str, str]:
    """Recover ``(market, symbol, event_type)`` from a segment path.

    The path is the single source of truth for where a datum lives, so the
    manifest can be rebuilt from disk alone.
    """
    parts = path.split("/")
    if len(parts) != 7 or parts[0] != "segments":
        raise StorageError(f"unexpected segment path shape: {path!r}")
    return parts[2], parts[3], parts[4]
