"""Storage policy: RAW hot, AGGREGATED research, REPORTS forever (§5-§11).

The host cannot hold the raw capture rate indefinitely, so "run continuously"
is a statement about the *policy*, not about the disk: raw data is hot and
bounded, derived data is small and kept, and nothing is ever deleted until the
thing that replaced it has been proven to exist.

Three layers, three retention rules
-----------------------------------

``segments/``   RAW HOT. Whatever the capture is writing now plus a bounded
                window behind it, chosen so the steady state fits the host with
                room for the disk guard to stay the *last* barrier.
``aggregated/`` AGGREGATED RESEARCH. Raw is never discarded before it has been
                folded into 1m buckets and the 5m/15m/30m roll-ups, at which
                point the aggregate is the long-term record and is kept.
``reports/``    REPORTS AND MANIFESTS. Never deleted: they are what makes the
                other two auditable.

No blind deletion
-----------------

A raw segment is deleted only after, in order: it is proven sealed; the window
it belongs to has been aggregated; the aggregate has been fingerprinted; a
lineage record names every source segment by hash; the window has been marked
compacted; and — re-checked at the moment of deletion — the aggregate still
hashes to what the lineage recorded. Any failure leaves the raw file in place,
because a segment we cannot account for is worth more than disk space.

Lineage is written inside the aggregate as well as beside it, so an aggregate
travelling alone still names the segments and hashes it came from (§9).
"""

from __future__ import annotations

import gzip
import json
import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from trading_bot.research.forward.aggregation import (
    AGGREGATION_VERSION,
    BASE_TIMEFRAME_MINUTES,
    HIGHER_TIMEFRAMES_MINUTES,
    aggregate_dataset,
)
from trading_bot.research.forward.contract import RawEvent, parse_event
from trading_bot.research.forward.preservation import (
    PRESERVED,
    PreservationPolicy,
    PreservationReport,
    preservation_for_window,
)
from trading_bot.research.forward.storage import (
    StorageError,
    iter_segment_rows,
    save_json,
    sha256_file,
)

__all__ = [
    "AGGREGATED_ROOT",
    "COMPACTION_MARKED",
    "COMPACTION_ROOT",
    "LINEAGE_ROOT",
    "LOSSLESS",
    "LOSSY",
    "PRESERVATION_ROOT",
    "RAW_ROOT",
    "REPORT_ROOT",
    "RETENTION_POLICY_VERSION",
    "CompactionResult",
    "LineageRecord",
    "RetentionPlan",
    "RetentionPolicy",
    "SourceSegment",
    "TierSpec",
    "apply_retention",
    "capacity_report",
    "compact_window",
    "lineage_id_for",
    "plan_retention",
    "tier_plan",
    "verify_sealed_segment",
]

RETENTION_POLICY_VERSION: Final[str] = "FORWARD-RETENTION-V1"

#: §5 — the three layers are three directories, so a reader can tell at a glance
#: which retention rule applies to what it is looking at.
RAW_ROOT: Final[str] = "segments"
AGGREGATED_ROOT: Final[str] = "aggregated"
LINEAGE_ROOT: Final[str] = "lineage"
COMPACTION_ROOT: Final[str] = "compaction"
REPORT_ROOT: Final[str] = "reports"
PRESERVATION_ROOT: Final[str] = "preservation"

COMPACTION_MARKED: Final[str] = "COMPACTED"

LOSSLESS: Final[str] = "LOSSLESS"
LOSSY: Final[str] = "LOSSY"


#: §9/§10 — the tiers, what each one is, and whether it can rebuild the tier
#: below it. "Compact" is not one thing: a tier that keeps every row (gzip is
#: lossless) and a tier that keeps per-minute means are not interchangeable, and
#: calling both "compressed" is how a lossy step gets mistaken for a safe one.
@dataclass(frozen=True, slots=True)
class TierSpec:
    tier: str
    layer: str
    kind: str
    resolution: str
    retention: str
    serves: tuple[str, ...]
    measured_share_of_bytes: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "layer": self.layer,
            "kind": self.kind,
            "resolution": self.resolution,
            "retention": self.retention,
            "serves": list(self.serves),
            "measured_share_of_bytes": self.measured_share_of_bytes,
        }


def tier_plan(policy: RetentionPolicy) -> tuple[TierSpec, ...]:
    """The retention tiers as one auditable table (§9, §10, §14).

    ``measured_share_of_bytes`` comes from the certification capture, where the
    quote streams (``book_ticker``) were ~70 % of written bytes while ``depth_diff``
    ~27 %, while trades, open interest and checkpoints together were under 2 %.
    That is the fact the policy is built on: the expensive part of this capture is
    also the part that cannot be regenerated.
    """
    return (
        TierSpec(
            tier="TIER 0",
            layer=RAW_ROOT,
            kind=LOSSLESS,
            resolution="every event",
            retention=f"{policy.raw_hot_hours} h behind the writer, then compacted",
            serves=(
                "replay",
                "M-03 at quote level",
                "any hypothesis not yet preregistered",
            ),
            measured_share_of_bytes=1.0,
        ),
        TierSpec(
            tier="TIER 1",
            layer=AGGREGATED_ROOT,
            kind=LOSSY,
            resolution=(
                f"{BASE_TIMEFRAME_MINUTES} m buckets + "
                + "/".join(str(m) for m in HIGHER_TIMEFRAMES_MINUTES)
                + " m roll-ups"
            ),
            retention="indefinite (the long-term record)",
            serves=("M-03 at 1/5 m", "M-07 at 5/15/30 m"),
            # Measured, not assumed: 37.21 MB of raw segments compacted to 0.08 MB
            # of aggregates on the head-certification capture (0.2 %), with
            # lineage adding ~8 KB per compacted window.
            measured_share_of_bytes=0.0022,
        ),
        TierSpec(
            tier="TIER 2",
            layer=LINEAGE_ROOT,
            kind=LOSSLESS,
            resolution="one record per compacted window",
            retention="indefinite",
            serves=("auditability of every deletion",),
        ),
        TierSpec(
            tier="TIER 3",
            layer=REPORT_ROOT,
            kind=LOSSY,
            resolution="per run",
            retention="indefinite",
            serves=("quality", "readiness", "capacity"),
        ),
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """The retention contract, explicit and versioned (§7, §11)."""

    version: str = RETENTION_POLICY_VERSION
    #: Must match the capture's rotation, or every window boundary is a lie.
    rotation_seconds: int = 900
    #: RAW retention: how far behind the writer raw data is kept. Chosen from
    #: measured throughput and the disk actually available, never invented.
    raw_hot_hours: float = 4.0
    #: A segment is only a compaction candidate once it has been quiet this long,
    #: which is what makes "sealed" checkable rather than assumed.
    sealed_grace_seconds: int = 1800
    aggregate_timeframes_minutes: tuple[int, ...] = (
        BASE_TIMEFRAME_MINUTES,
        *HIGHER_TIMEFRAMES_MINUTES,
    )
    #: ``None`` means "retain indefinitely" — the default for derived data.
    aggregate_retention_days: int | None = None
    report_retention_days: int | None = None
    #: Space the policy refuses to spend, so the disk guard keeps something to
    #: guard. The guard is the last barrier, not the only one (§10).
    reserve_bytes: int = 512 * 1024 * 1024
    #: Retain at least this much aggregate history before the target-days check.
    target_operating_days: int = 7

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rotation_seconds": self.rotation_seconds,
            "raw_hot_hours": self.raw_hot_hours,
            "sealed_grace_seconds": self.sealed_grace_seconds,
            "aggregate_timeframes_minutes": list(self.aggregate_timeframes_minutes),
            "aggregate_retention_days": self.aggregate_retention_days,
            "report_retention_days": self.report_retention_days,
            "reserve_bytes": self.reserve_bytes,
            "target_operating_days": self.target_operating_days,
            "raw_retention": (
                f"RAW HOT: {self.raw_hot_hours} h behind the writer, then compacted"
            ),
            "aggregate_retention": (
                "indefinite"
                if self.aggregate_retention_days is None
                else f"{self.aggregate_retention_days} days"
            ),
            "report_retention": (
                "indefinite" if self.report_retention_days is None else "bounded"
            ),
        }


# ------------------------------------------------------------------------ lineage
@dataclass(frozen=True, slots=True)
class SourceSegment:
    """One raw segment that an aggregate was built from (§9)."""

    path: str
    sha256: str
    rows: int
    bytes: int
    stream: str
    first_receive_time: int | None
    last_receive_time: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "rows": self.rows,
            "bytes": self.bytes,
            "stream": self.stream,
            "first_receive_time": self.first_receive_time,
            "last_receive_time": self.last_receive_time,
        }


@dataclass(frozen=True, slots=True)
class LineageRecord:
    """RAW -> AGGREGATE, provable after the raw is gone (§9)."""

    lineage_id: str
    policy_version: str
    aggregation_version: str
    run_id: str
    window_start_ms: int
    window_end_ms: int
    timeframes_minutes: tuple[int, ...]
    output_path: str
    output_sha256: str
    output_bytes: int
    output_rows: int
    sources: tuple[SourceSegment, ...]
    loss_windows_applied: bool
    created_at_ms: int = field(default_factory=_now_ms)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "policy_version": self.policy_version,
            "aggregation_version": self.aggregation_version,
            "run_id": self.run_id,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "window_start_iso": _iso(self.window_start_ms),
            "window_end_iso": _iso(self.window_end_ms),
            "timeframes_minutes": list(self.timeframes_minutes),
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "output_bytes": self.output_bytes,
            "output_rows": self.output_rows,
            "source_count": len(self.sources),
            "source_row_count": sum(source.rows for source in self.sources),
            "sources": [source.as_dict() for source in self.sources],
            "loss_windows_applied": self.loss_windows_applied,
            "created_at_ms": self.created_at_ms,
            "created_at_iso": _iso(self.created_at_ms),
        }


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def lineage_id_for(policy: RetentionPolicy, run_id: str, window_start_ms: int) -> str:
    return f"{policy.version}|{run_id}|{window_start_ms}"


def lineage_path(root: Path, run_id: str, window_start_ms: int) -> Path:
    return Path(root) / LINEAGE_ROOT / run_id / f"{window_start_ms}.json"


def aggregate_path(root: Path, run_id: str, window_start_ms: int, window_end_ms: int) -> Path:
    return (
        Path(root)
        / AGGREGATED_ROOT
        / run_id
        / f"{window_start_ms}-{window_end_ms}.json.gz"
    )


# ------------------------------------------------------------------- sealing/plan


def _window_of(relative: str, rotation_seconds: int) -> tuple[int, int]:
    """Recover a segment's window from its own path.

    The path is ``segments/<source>/<market>/<symbol>/<event_type>/<date>/<HHMMSS>``
    and the filename *is* the bucket start, so the window is a pure function of
    the path — the same property that makes the dataset auditable at all.
    """
    parts = relative.split("/")
    if len(parts) != 7 or parts[0] != RAW_ROOT:
        raise StorageError(f"unexpected segment path shape: {relative!r}")
    date_part, stamp = parts[5], parts[6].split(".")[0]
    try:
        moment = datetime.strptime(f"{date_part} {stamp}", "%Y-%m-%d %H%M%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise StorageError(f"segment filename is not a rotation bucket: {relative!r}") from exc
    start = int(moment.timestamp() * 1000)
    width = rotation_seconds * 1000
    if start % width:
        raise StorageError(
            f"segment {relative!r} is not aligned to a {rotation_seconds}s rotation; "
            "the policy rotation does not match the capture's"
        )
    return start, start + width


def verify_sealed_segment(
    path: Path, *, grace_seconds: int, now_ms: int
) -> tuple[bool, str]:
    """Prove a segment is finished, instead of assuming it (§8).

    Three independent checks: the file has been quiet for the grace period, the
    gzip stream reads to a clean end, and no row is a partial tail. A live
    segment fails the first; a truncated one fails the second or third.
    """
    try:
        age_ms = now_ms - int(os.stat(path).st_mtime * 1000)
    except OSError as exc:
        return False, f"unreadable: {exc}"
    if age_ms < grace_seconds * 1000:
        return False, f"still warm: {age_ms // 1000}s < grace {grace_seconds}s"
    rows = 0
    try:
        for row, partial_tail in iter_segment_rows(path):
            if partial_tail:
                return False, "partial tail"
            if row is None:
                return False, "unparseable row"
            rows += 1
    except (OSError, gzip.BadGzipFile, EOFError) as exc:
        return False, f"truncated gzip: {type(exc).__name__}"
    return True, f"sealed, {rows} rows"


def _iter_raw_segments(root: Path) -> Iterator[Path]:
    base = Path(root) / RAW_ROOT
    if not base.exists():
        return
    for path in sorted(base.rglob("*.jsonl*")):
        if path.is_file():
            yield path


@dataclass(slots=True)
class RetentionPlan:
    """What the policy *would* do, computed before it does anything."""

    policy: RetentionPolicy
    run_id: str
    compactable: list[tuple[int, int, list[Path]]] = field(default_factory=list)
    deletable: list[tuple[Path, str]] = field(default_factory=list)
    retained_raw: list[Path] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.as_dict(),
            "run_id": self.run_id,
            "compactable_windows": [start for start, _end, _files in self.compactable],
            "deletable_segments": [str(path) for path, _why in self.deletable],
            "retained_raw_count": len(self.retained_raw),
            "skipped": self.skipped[:50],
        }


def _load_lineage(root: Path, run_id: str, window_start_ms: int) -> LineageRecord | None:
    path = lineage_path(root, run_id, window_start_ms)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = tuple(
        SourceSegment(
            path=str(entry["path"]),
            sha256=str(entry["sha256"]),
            rows=int(entry["rows"]),
            bytes=int(entry["bytes"]),
            stream=str(entry["stream"]),
            first_receive_time=entry.get("first_receive_time"),
            last_receive_time=entry.get("last_receive_time"),
        )
        for entry in payload.get("sources", [])
    )
    return LineageRecord(
        lineage_id=str(payload["lineage_id"]),
        policy_version=str(payload["policy_version"]),
        aggregation_version=str(payload["aggregation_version"]),
        run_id=str(payload["run_id"]),
        window_start_ms=int(payload["window_start_ms"]),
        window_end_ms=int(payload["window_end_ms"]),
        timeframes_minutes=tuple(int(m) for m in payload["timeframes_minutes"]),
        output_path=str(payload["output_path"]),
        output_sha256=str(payload["output_sha256"]),
        output_bytes=int(payload["output_bytes"]),
        output_rows=int(payload["output_rows"]),
        sources=sources,
        loss_windows_applied=bool(payload.get("loss_windows_applied", False)),
        created_at_ms=int(payload.get("created_at_ms", 0)),
    )


def plan_retention(
    root: Path | str,
    policy: RetentionPolicy,
    run_id: str,
    *,
    now_ms: int | None = None,
) -> RetentionPlan:
    """Decide what is compactable and what is deletable, without touching disk."""
    base = Path(root)
    now = _now_ms() if now_ms is None else now_ms
    plan = RetentionPlan(policy=policy, run_id=run_id)
    windows: dict[int, list[Path]] = {}
    for path in _iter_raw_segments(base):
        relative = path.relative_to(base).as_posix()
        try:
            start, _end = _window_of(relative, policy.rotation_seconds)
        except StorageError as exc:
            plan.skipped.append({"path": relative, "reason": str(exc)})
            continue
        windows.setdefault(start, []).append(path)

    cutoff_ms = now - int(policy.raw_hot_hours * 3_600_000)
    for start in sorted(windows):
        files = windows[start]
        end = start + policy.rotation_seconds * 1000
        lineage = _load_lineage(base, run_id, start)
        if end > cutoff_ms:
            plan.retained_raw.extend(files)
            continue
        # Already aggregated: the aggregate must still match before the raw goes.
        if lineage is not None:
            ok, reason = _aggregate_matches(base, lineage)
            if ok:
                plan.deletable.extend((path, lineage.lineage_id) for path in files)
            else:
                plan.skipped.append({"window_start_ms": start, "reason": f"aggregate {reason}"})
                plan.retained_raw.extend(files)
            continue
        sealed: list[Path] = []
        for path in files:
            ok, reason = verify_sealed_segment(
                path, grace_seconds=policy.sealed_grace_seconds, now_ms=now
            )
            if ok:
                sealed.append(path)
            else:
                plan.skipped.append(
                    {"path": path.relative_to(base).as_posix(), "reason": reason}
                )
                plan.retained_raw.append(path)
        if sealed:
            plan.compactable.append((start, end, sealed))
    return plan


def _aggregate_matches(root: Path, lineage: LineageRecord) -> tuple[bool, str]:
    """Re-hash the aggregate from disk; the raw may only go if it is intact."""
    output = root / lineage.output_path
    if not output.exists():
        return False, "missing on disk"
    digest, size = sha256_file(output)
    if digest != lineage.output_sha256:
        return False, f"hash changed ({digest[:12]} != {lineage.output_sha256[:12]})"
    if size != lineage.output_bytes:
        return False, f"size changed ({size} != {lineage.output_bytes})"
    return True, "matches lineage"


# -------------------------------------------------------------------- compaction


def _write_gzip_json(path: Path, payload: Any) -> tuple[str, int]:
    """Deterministic, atomic gzip JSON: fixed mtime so the hash is reproducible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode(
        "utf-8"
    )
    with (
        tmp.open("wb") as handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0, compresslevel=6) as gz,
    ):
        gz.write(raw)
    os.replace(tmp, path)
    return sha256_file(path)


def _window_source(
    root: Path, segment_paths: list[Path]
) -> Iterator[RawEvent]:
    """Stream a window's raw rows as events, one segment at a time (§34)."""
    for path in segment_paths:
        for row, partial_tail in iter_segment_rows(path):
            if partial_tail or row is None:
                raise StorageError(
                    f"{path} is not cleanly readable; refusing to aggregate a truncated segment"
                )
            yield parse_event(row)


def window_sources(
    root: Path, policy: RetentionPolicy, segment_paths: list[Path]
) -> tuple[SourceSegment, ...]:
    """Fingerprint every source segment, with its stream key from the path."""
    base = Path(root)
    sources: list[SourceSegment] = []
    for path in sorted(segment_paths):
        relative = path.relative_to(base).as_posix()
        parts = relative.split("/")
        digest, size = sha256_file(path)
        rows = 0
        first_receive: int | None = None
        last_receive: int | None = None
        for row, partial_tail in iter_segment_rows(path):
            if partial_tail:
                raise StorageError(f"{relative}: partial tail while fingerprinting")
            if row is None:
                raise StorageError(f"{relative}: unparseable row while fingerprinting")
            rows += 1
            stamp = row.get("receive_time")
            if isinstance(stamp, int):
                first_receive = stamp if first_receive is None else min(first_receive, stamp)
                last_receive = stamp if last_receive is None else max(last_receive, stamp)
        sources.append(
            SourceSegment(
                path=relative,
                sha256=digest,
                rows=rows,
                bytes=size,
                stream=f"{parts[2]}/{parts[3]}/{parts[4]}",
                first_receive_time=first_receive,
                last_receive_time=last_receive,
            )
        )
    return tuple(sources)


def _loss_windows(
    gaps: Iterable[dict[str, Any]] | None,
) -> dict[str, list[tuple[int, int]]]:
    windows: dict[str, list[tuple[int, int]]] = {}
    for gap in gaps or []:
        if not gap.get("data_lost"):
            continue
        key = f"{gap.get('market')}/{gap.get('symbol')}"
        start, end = gap.get("start_ms"), gap.get("end_ms")
        if isinstance(start, int) and isinstance(end, int):
            windows.setdefault(key, []).append((start, end))
    return windows


@dataclass(frozen=True, slots=True)
class CompactionResult:
    window_start_ms: int
    window_end_ms: int
    lineage: LineageRecord
    already_present: bool
    sources_compacted: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "already_present": self.already_present,
            "lineage": self.lineage.as_dict(),
            "sources_compacted": list(self.sources_compacted),
        }


def compact_window(
    root: Path | str,
    policy: RetentionPolicy,
    run_id: str,
    window_start_ms: int,
    window_end_ms: int,
    segment_paths: list[Path],
    *,
    gaps: Iterable[dict[str, Any]] | None = None,
    now_ms: int | None = None,
) -> CompactionResult:
    """RAW -> verify sealed -> aggregate -> fingerprint -> lineage -> mark (§8).

    Idempotent: a window that already has a lineage record whose aggregate still
    matches is returned unchanged rather than recomputed, so a crash between the
    aggregate and the marker is repaired on the next pass.
    """
    base = Path(root)
    existing = _load_lineage(base, run_id, window_start_ms)
    if existing is not None:
        ok, reason = _aggregate_matches(base, existing)
        if ok:
            return CompactionResult(
                window_start_ms, window_end_ms, existing, True, tuple()
            )
        raise StorageError(
            f"window {window_start_ms} has a lineage record whose aggregate {reason}; "
            "refusing to overwrite evidence"
        )

    now = _now_ms() if now_ms is None else now_ms
    for path in segment_paths:
        ok, reason = verify_sealed_segment(
            path, grace_seconds=policy.sealed_grace_seconds, now_ms=now
        )
        if not ok:
            raise StorageError(f"refusing to compact unsealed segment {path.name}: {reason}")

    sources = window_sources(base, policy, segment_paths)
    loss = _loss_windows(gaps)
    window: dict[str, tuple[int, int]] = {}
    for source in sources:
        if source.first_receive_time is None or source.last_receive_time is None:
            continue
        key = "/".join(source.stream.split("/")[:2])
        current = window.get(key)
        lower = source.first_receive_time
        upper = source.last_receive_time
        if current is None:
            window[key] = (lower, upper)
        else:
            window[key] = (min(current[0], lower), max(current[1], upper))

    dataset = aggregate_dataset(
        lambda: _window_source(base, segment_paths),
        run_id=run_id,
        intervals=policy.aggregate_timeframes_minutes,
        loss_windows=loss,
        window=window,
    )
    aggregate = dataset.as_dict()
    output_rows = sum(
        len(values)
        for group in (
            aggregate["trades"],
            aggregate["book"],
            aggregate["open_interest"],
            aggregate["derived"],
        )
        for values in group.values()
    )

    lineage_id = lineage_id_for(policy, run_id, window_start_ms)
    output = aggregate_path(base, run_id, window_start_ms, window_end_ms)
    relative_output = output.relative_to(base).as_posix()
    envelope = {
        "lineage_id": lineage_id,
        "policy_version": policy.version,
        "aggregation_version": AGGREGATION_VERSION,
        "run_id": run_id,
        "window_start_ms": window_start_ms,
        "window_end_ms": window_end_ms,
        "lineage_path": lineage_path(base, run_id, window_start_ms).relative_to(base).as_posix(),
        "sources": [source.as_dict() for source in sources],
        "aggregation": aggregate,
    }
    output_sha256, output_bytes = _write_gzip_json(output, envelope)

    record = LineageRecord(
        lineage_id=lineage_id,
        policy_version=policy.version,
        aggregation_version=AGGREGATION_VERSION,
        run_id=run_id,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        timeframes_minutes=policy.aggregate_timeframes_minutes,
        output_path=relative_output,
        output_sha256=output_sha256,
        output_bytes=output_bytes,
        output_rows=output_rows,
        sources=sources,
        loss_windows_applied=bool(loss),
    )
    save_json(lineage_path(base, run_id, window_start_ms), record.as_dict())
    _mark_compacted(base, run_id, record)
    return CompactionResult(
        window_start_ms,
        window_end_ms,
        record,
        False,
        tuple(source.path for source in sources),
    )


def _mark_compacted(root: Path, run_id: str, record: LineageRecord) -> None:
    """Append the marker that makes a raw window *eligible* for deletion (§8)."""
    marker_dir = root / COMPACTION_ROOT
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{run_id}.jsonl"
    line = json.dumps(
        {
            "status": COMPACTION_MARKED,
            "lineage_id": record.lineage_id,
            "window_start_ms": record.window_start_ms,
            "window_end_ms": record.window_end_ms,
            "output_path": record.output_path,
            "output_sha256": record.output_sha256,
            "output_rows": record.output_rows,
            "source_paths": [source.path for source in record.sources],
            "marked_at_ms": _now_ms(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with marker.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def read_compaction_markers(root: Path | str, run_id: str) -> list[dict[str, Any]]:
    path = Path(root) / COMPACTION_ROOT / f"{run_id}.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@dataclass(slots=True)
class RetentionRun:
    """One pass of the policy over the dataset root."""

    compacted: list[CompactionResult] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)
    freed_bytes: int = 0
    #: §11/§12 — the preservation verdict for every window a deletion was
    #: considered for. A deletion nobody can show was safe is not a policy.
    preservation: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "compacted_windows": [result.as_dict() for result in self.compacted],
            "deleted_segments": self.deleted,
            "refused": self.refused[:50],
            "freed_bytes": self.freed_bytes,
            "preservation": self.preservation,
        }


def apply_retention(
    root: Path | str,
    policy: RetentionPolicy,
    run_id: str,
    *,
    allow_delete: bool = False,
    gaps: Iterable[dict[str, Any]] | None = None,
    now_ms: int | None = None,
    preservation: PreservationPolicy | None = None,
) -> RetentionRun:
    """Compact what is due and, only with ``allow_delete``, remove proven raw.

    Deletion is opt-in because the disk guard exists precisely so that nothing
    has to be deleted speculatively: the guard stops a capture that is filling
    the disk, and this function reclaims space that has already been replaced.
    """
    base = Path(root)
    plan = plan_retention(base, policy, run_id, now_ms=now_ms)
    run = RetentionRun()
    for start, end, files in plan.compactable:
        try:
            run.compacted.append(
                compact_window(
                    base, policy, run_id, start, end, files, gaps=gaps, now_ms=now_ms
                )
            )
        except StorageError as exc:
            run.refused.append({"window_start_ms": start, "reason": str(exc)})

    if not allow_delete:
        return run

    # Re-plan: a window compacted in this pass is deletable in the same pass, but
    # only through the same verification path, so the check cannot be bypassed.
    refreshed = plan_retention(base, policy, run_id, now_ms=now_ms)
    # A window that was compacted but is *not* deletable must say why: silence is
    # how a retention pass turns into a disk-full incident nobody can explain.
    for entry in refreshed.skipped:
        if str(entry.get("reason", "")).startswith("aggregate "):
            run.refused.append(entry)
    # §12 — the raw rows of a window are still on disk here, which is the only
    # moment at which the preservation question can be answered: derive the
    # hypothesis from raw, derive it from the compact artifact, compare, and only
    # then decide. Answered once per window, and written down beside the lineage.
    window_files: dict[int, list[Path]] = {}
    preservation_seen: dict[int, PreservationReport] = {}
    if preservation is not None:
        for candidate in _iter_raw_segments(base):
            try:
                candidate_start, _candidate_end = _window_of(
                    candidate.relative_to(base).as_posix(), policy.rotation_seconds
                )
            except StorageError:  # pragma: no cover - already reported by the plan
                continue
            window_files.setdefault(candidate_start, []).append(candidate)

    for path, lineage_id in refreshed.deletable:
        relative = path.relative_to(base).as_posix()
        window_start, window_end = _window_of(relative, policy.rotation_seconds)
        record = _load_lineage(base, run_id, window_start)
        if record is None or record.lineage_id != lineage_id:
            run.refused.append({"path": relative, "reason": "no matching lineage"})
            continue
        ok, reason = _aggregate_matches(base, record)
        if not ok:
            run.refused.append({"path": str(path), "reason": f"aggregate {reason}"})
            continue
        if preservation is not None:
            report = preservation_seen.get(window_start)
            if report is None:
                report = preservation_for_window(
                    base,
                    run_id,
                    window_start,
                    sorted(window_files.get(window_start, [])),
                    policy=preservation,
                )
                preservation_seen[window_start] = report
                run.preservation.append(report.as_dict())
                save_json(
                    base / PRESERVATION_ROOT / run_id / f"{window_start}.json",
                    report.as_dict(),
                )
            if not report.deletion_allowed:
                run.refused.append(
                    {
                        "path": relative,
                        "window_start_ms": window_start,
                        "window_end_ms": window_end,
                        "reason": ", ".join(
                            f"{name}: {verdict}" for name, verdict in report.verdicts.items()
                            if verdict != PRESERVED
                        )
                        or "preservation refused deletion",
                    }
                )
                continue
        size = path.stat().st_size
        try:
            path.unlink()
        except OSError as exc:
            run.refused.append({"path": str(path), "reason": f"unlink failed: {exc}"})
            continue
        run.deleted.append(relative)
        run.freed_bytes += size
    return run


# ---------------------------------------------------------------------- capacity


@dataclass(frozen=True, slots=True)
class CapacityReport:
    """The honest arithmetic behind the retention choice (§11)."""

    free_bytes: int
    reserve_bytes: int
    compressed_bytes_per_day: float
    aggregate_bytes_per_day: float
    raw_hot_hours: float
    raw_hot_steady_state_bytes: float
    headroom_bytes: float
    hours_until_guard_without_compaction: float
    estimated_operating_days: float | None
    verdict: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "free_bytes": self.free_bytes,
            "free_gb": round(self.free_bytes / 1e9, 3),
            "reserve_bytes": self.reserve_bytes,
            "reserve_gb": round(self.reserve_bytes / 1e9, 3),
            "compressed_bytes_per_day": self.compressed_bytes_per_day,
            "compressed_gb_per_day": round(self.compressed_bytes_per_day / 1e9, 3),
            "aggregate_bytes_per_day": self.aggregate_bytes_per_day,
            "aggregate_mb_per_day": round(self.aggregate_bytes_per_day / 1e6, 3),
            "raw_hot_hours": self.raw_hot_hours,
            "raw_hot_steady_state_bytes": self.raw_hot_steady_state_bytes,
            "raw_hot_steady_state_gb": round(self.raw_hot_steady_state_bytes / 1e9, 3),
            "headroom_bytes": self.headroom_bytes,
            "headroom_gb": round(self.headroom_bytes / 1e9, 3),
            "hours_until_guard_without_compaction": self.hours_until_guard_without_compaction,
            "estimated_operating_days": self.estimated_operating_days,
            "verdict": self.verdict,
        }


VIABLE: Final[str] = "VIABLE"
EXTERNAL_STORAGE_REQUIRED: Final[str] = "EXTERNAL_STORAGE_REQUIRED"


def capacity_report(
    *,
    free_bytes: int,
    policy: RetentionPolicy,
    compressed_bytes_per_day: float,
    aggregate_bytes_per_day: float = 0.0,
    reports_bytes_per_day: float = 0.0,
) -> CapacityReport:
    """Can the host hold this policy for the target number of days?

    Raw is *bounded* by the hot window, so steady state is
    ``hot_hours * hourly_rate`` and only the aggregates grow with time. The
    question is therefore whether that steady state fits with the reserve left
    over, and how long the collector survives if compaction ever stalls.
    """
    per_hour = compressed_bytes_per_day / 24.0
    raw_hot = per_hour * policy.raw_hot_hours
    headroom = free_bytes - policy.reserve_bytes - raw_hot
    hours_to_guard = max(0.0, (free_bytes - policy.reserve_bytes - raw_hot) / per_hour) if per_hour else 0.0
    daily_growth = aggregate_bytes_per_day + reports_bytes_per_day
    if headroom <= 0:
        days: float | None = 0.0
    elif daily_growth <= 0:
        days = None
    else:
        days = headroom / daily_growth
    viable = headroom > 0 and (days is None or days >= policy.target_operating_days)
    return CapacityReport(
        free_bytes=free_bytes,
        reserve_bytes=policy.reserve_bytes,
        compressed_bytes_per_day=compressed_bytes_per_day,
        aggregate_bytes_per_day=aggregate_bytes_per_day,
        raw_hot_hours=policy.raw_hot_hours,
        raw_hot_steady_state_bytes=raw_hot,
        headroom_bytes=headroom,
        hours_until_guard_without_compaction=hours_to_guard,
        estimated_operating_days=days,
        verdict=VIABLE if viable else EXTERNAL_STORAGE_REQUIRED,
    )


def policy_for_host(
    *,
    free_bytes: int,
    compressed_bytes_per_day: float,
    aggregate_bytes_per_day: float = 0.0,
    reserve_bytes: int = 512 * 1024 * 1024,
    target_operating_days: int = 7,
    max_raw_hot_hours: float = 24.0,
    fill_fraction: float = 0.5,
) -> RetentionPolicy:
    """Choose the raw hot window from real capacity, not from ambition.

    In descending order of priority: the reserve stays out of the budget, the
    aggregates' own growth is paid for up front, and the raw window may only take
    ``fill_fraction`` of what remains. Capping at half the spare space is what
    turns "the window fits exactly" into "the window fits and the disk guard
    still has somewhere to stand" — the difference between a policy that survives
    a stalled compaction and one that deadlocks against it.

    There is no floor below one hour: if one hour cannot be afforded the window
    is one hour and the capacity report says ``EXTERNAL_STORAGE_REQUIRED``. The
    policy never pretends the disk is bigger than it is.

    ``fill_fraction`` must be in ``(0, 1]``; ``1.0`` reproduces the aggressive
    "use everything that fits" choice and is only appropriate for a dedicated
    volume.
    """
    if not 0.0 < fill_fraction <= 1.0:
        raise ValueError(f"fill_fraction must be in (0, 1], got {fill_fraction}")
    per_hour = compressed_bytes_per_day / 24.0
    daily_growth = aggregate_bytes_per_day
    room = free_bytes - reserve_bytes - (daily_growth * target_operating_days)
    hours = 0.0 if (room <= 0 or per_hour <= 0) else (room * fill_fraction) / per_hour
    hours = max(1.0, min(float(max_raw_hot_hours), float(int(hours))))
    return RetentionPolicy(
        raw_hot_hours=hours,
        reserve_bytes=reserve_bytes,
        target_operating_days=target_operating_days,
    )


