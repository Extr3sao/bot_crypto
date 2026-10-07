"""CAP-004 — heartbeat, campaign status, daily rollup and checkpoints.

Unattended running is only trustworthy if the run can be observed and its
milestones are immutable:

* **Heartbeat** — a small, atomically replaced file that says whether the runner
  is alive, when it last sealed / settled / scored / verified, and what it is
  waiting for.  An absent or stale heartbeat must read as "not running", never as
  "probably fine".
* **Status** — the campaign dashboard at ``reports/cap004/``: age, every
  population counted separately, checkpoint progress, the next slot, the next
  maturity, the analyst's direction mix, errors and chain status.
* **Cycle journal** — an append-only, hash-chained stream of *compact* cycle
  events (CAP-004C).  One event per supervised invocation: counts, deltas, chain
  and drift status, verifier result, error codes.  It never embeds the campaign
  state, the ledger records or the daily report: the earlier full-snapshot
  journal did, which made each cycle's record an order of magnitude larger than
  the run before it and consumed several GiB per day.
* **Daily rollup** — per UTC day: decisions sealed, outcomes matured, evaluations
  completed, failures, drift and verification.  Derived from the ledger plus the
  cycle journal, so it is reproducible rather than remembered.  Bounded by
  construction: it aggregates the day's events instead of embedding them.
* **Checkpoints** — ``CHECKPOINT_020/050/100`` are written **once per population**.
  Both the file and its markdown mirror carry ``decision_set_hash``; a later run
  that finds a different population under the same checkpoint reports
  ``CHECKPOINT_CONFLICT`` instead of silently rewriting history.

Reports live under ``reports/`` (regenerable, gitignored); checkpoints live under
``evidence/real_decisions/checkpoints/`` because they are evidence.  No status
vocabulary here contains a promotional word.

Storage contract (CAP-004C): every write here is bounded.  The journal grows
*linearly* with the number of cycles (≈0.7 KiB each), is segmented by size with a
per-segment digest manifest, and is read back with a hard per-line byte cap so a
single corrupt or legacy line can never again exhaust memory in the middle of a
real cycle.  The daily projection is O(1) per cycle, not O(cycles that day).

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import agentic_contracts as ac
from trading_bot.research import alpha_scorecard as asc
from trading_bot.research import decision_outcomes as do

__all__ = [
    "CHECKPOINT_DIRNAME",
    "CHECKPOINT_JSON_VERSION",
    "CYCLE_EVENT_KEYS",
    "CYCLE_GENESIS_HASH",
    "CYCLE_JOURNAL_FILENAME",
    "CYCLE_JOURNAL_VERSION",
    "CYCLE_SEGMENT_DIRNAME",
    "CYCLE_SEGMENT_MAX_BYTES",
    "DAILY_CYCLE_TAIL",
    "DAILY_REPORT_VERSION",
    "HEARTBEAT_FILENAME",
    "MAX_JOURNAL_LINE_BYTES",
    "build_checkpoint_payload",
    "checkpoint_decision_set_hash",
    "checkpoint_decision_set_hash_from_records",
    "checkpoint_dir",
    "checkpoint_md",
    "cycle_event",
    "cycle_journal_segments",
    "daily_report",
    "heartbeat_age_seconds",
    "heartbeat_payload",
    "read_checkpoint",
    "read_cycle_journal",
    "read_heartbeat",
    "render_status_md",
    "rotate_cycle_journal",
    "status_payload",
    "utc_day",
    "verify_cycle_chain",
    "write_checkpoint",
    "write_cycle_record",
    "write_daily_report",
    "write_heartbeat",
    "write_json_atomic",
]

HEARTBEAT_FILENAME = "heartbeat.json"
CHECKPOINT_DIRNAME = "checkpoints"
CYCLE_JOURNAL_FILENAME = "cycles.jsonl"
CYCLE_SEGMENT_DIRNAME = "cycles_segments"
CYCLE_JOURNAL_VERSION = "CAP004_CYCLE_EVENT_V1"
DAILY_REPORT_VERSION = "CAP004_DAILY_PROJECTION_V2"
CHECKPOINT_JSON_VERSION = "CAMPAIGN_CHECKPOINT_V1"

#: Hard cap on a single journal line.  A line larger than this is skipped and
#: counted, never materialised: the legacy full-snapshot journal reached GiB per
#: line and a single ``readlines`` on it aborted a real campaign cycle.
MAX_JOURNAL_LINE_BYTES = 256 * 1024

#: The active journal is rolled into a numbered segment once it passes this size.
#: 4 MiB ≈ 6000 cycles ≈ 60 days at the 15-minute cadence.
CYCLE_SEGMENT_MAX_BYTES = 4 * 1024 * 1024

#: A closed segment is never modified; its digest is recorded in the manifest.
CYCLE_SEGMENT_MANIFEST = "manifest.json"

#: The compact event is the whole journal contract (CAP-004C §8).
CYCLE_EVENT_KEYS = (
    "event_version",
    "cycle",
    "campaign_id",
    "day",
    "started_at",
    "started_at_utc",
    "finished_at",
    "finished_at_utc",
    "actions_due",
    "actions_completed",
    "sealed_count_delta",
    "settled_count_delta",
    "evaluated_count_delta",
    "population",
    "chain_status",
    "drift_status",
    "verifier_result",
    "error_codes",
    "previous_event_hash",
    "event_hash",
)

#: Bounded daily projection: the tail is kept for forensics, the day is counted.
DAILY_CYCLE_TAIL = 8
DAILY_FAILURES_TAIL = 50

#: Chain seed for the compact cycle journal (the journal is derived, but its
#: internal chain makes an accidental edit or truncation visible).
CYCLE_GENESIS_HASH = hashlib.sha256(b"CAP004_CYCLE_EVENT_GENESIS").hexdigest()


# --------------------------------------------------------------------------- #
# §1 — atomic writes
# --------------------------------------------------------------------------- #


def write_json_atomic(path: Path, payload: Any) -> Path:
    """Write via a temp file + replace, so a crash never leaves a half report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return path


def utc_day(moment: int) -> str:
    return dt.datetime.fromtimestamp(int(moment), dt.UTC).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# §2 — heartbeat
# --------------------------------------------------------------------------- #


def heartbeat_payload(
    *,
    campaign_id: str,
    campaign_version: str,
    now: int,
    process_status: str,
    counters: Mapping[str, Any],
    cycle: int,
    interval_seconds: int,
    next_decision_slot: int,
    next_maturity: int | None,
    last_successful_seal: int | None = None,
    last_successful_settle: int | None = None,
    last_successful_score: int | None = None,
    last_successful_verify: int | None = None,
    errors: Sequence[Mapping[str, Any]] = (),
    modes_completed: Sequence[str] = (),
    disk: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The liveness record: what the runner is, and what it is waiting for.

    ``disk`` carries the storage state measured *before* this cycle's work, so
    liveness and headroom are read from the same file.
    """
    return {
        "campaign_id": campaign_id,
        "campaign_version": campaign_version,
        "timestamp": int(now),
        "timestamp_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "process_status": process_status,
        "cycle": int(cycle),
        "interval_seconds": int(interval_seconds),
        "modes_completed": list(modes_completed),
        "last_successful_seal": last_successful_seal,
        "last_successful_settle": last_successful_settle,
        "last_successful_score": last_successful_score,
        "last_successful_verify": last_successful_verify,
        "next_decision_slot": int(next_decision_slot),
        "next_decision_slot_utc": dt.datetime.fromtimestamp(
            int(next_decision_slot), dt.UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "next_maturity": next_maturity,
        "pending_maturities": int(counters.get("pending_decisions", 0)),
        "matured_unsettled": int(counters.get("matured_unsettled", 0)),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "errors": [dict(item) for item in errors],
        "disk": dict(disk) if disk else None,
        "disk_free_bytes": (disk or {}).get("free_bytes"),
        "disk_status": (disk or {}).get("status"),
    }


def write_heartbeat(root: Path, payload: Mapping[str, Any]) -> Path:
    return write_json_atomic(Path(root) / HEARTBEAT_FILENAME, payload)


def read_heartbeat(root: Path) -> dict[str, Any] | None:
    path = Path(root) / HEARTBEAT_FILENAME
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def heartbeat_age_seconds(payload: Mapping[str, Any] | None, *, now: int) -> int | None:
    if payload is None or payload.get("timestamp") is None:
        return None
    return int(now) - int(payload["timestamp"])


# --------------------------------------------------------------------------- #
# §3 — cycle journal: compact, hash-chained, segmented, bounded to read
# --------------------------------------------------------------------------- #


def _iter_journal_lines(path: Path, *, max_line_bytes: int) -> Iterator[tuple[bytes, bool]]:
    """Yield ``(line, oversized)`` pairs without ever holding a huge line.

    DEF-CAMPAIGN-STORAGE-001: the reader used to be ``path.read_text()`` plus a
    ``splitlines()``, so one multi-GiB line (which the old writer produced every
    cycle) aborted a real settlement cycle with ``MemoryError``.  This generator
    streams in fixed-size chunks, keeps at most ``max_line_bytes`` in memory, and
    *discards* the remainder of an oversized line while flagging it.
    """
    chunk_size = 1 << 20
    buffer = bytearray()
    oversized = False
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            start = 0
            while True:
                cut = chunk.find(b"\n", start)
                if cut < 0:
                    if not oversized:
                        buffer.extend(chunk[start:])
                        if len(buffer) > max_line_bytes:
                            oversized = True
                            buffer.clear()
                    break
                piece = chunk[start:cut]
                if oversized:
                    yield b"", True
                    oversized = False
                    buffer.clear()
                else:
                    buffer.extend(piece)
                    yield bytes(buffer), False
                    buffer.clear()
                start = cut + 1
    if oversized:
        yield b"", True
    elif buffer.strip():
        yield bytes(buffer), False


def journal_line_limit(limit: int | None) -> int | None:
    """Normalise a tail limit (``None`` = keep everything)."""
    if limit is None:
        return None
    return max(int(limit), 0)


def cycle_journal_segments(root: Path) -> list[Path]:
    """Closed segments in chain order (their names are zero-padded sequence IDs)."""
    directory = Path(root) / CYCLE_SEGMENT_DIRNAME
    if not directory.is_dir():
        return []
    return sorted(entry for entry in directory.glob("cycles-*.jsonl") if entry.is_file())


def _read_journal_file(
    path: Path,
    *,
    kept: deque[dict[str, Any]],
    limit: int | None,
    stats: dict[str, int],
    day: str | None = None,
) -> None:
    if not path.is_file():
        return
    for raw, oversized in _iter_journal_lines(path, max_line_bytes=MAX_JOURNAL_LINE_BYTES):
        if oversized:
            stats["oversized_lines"] += 1
            continue
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            stats["unparsable_lines"] += 1
            continue
        stats["lines"] += 1
        if day is not None and str(entry.get("day")) != day:
            stats["filtered_lines"] += 1
            continue
        # ``deque(maxlen=…)`` does the bounding: ``maxlen=0`` keeps nothing and
        # ``maxlen=None`` keeps everything, with no branch to get wrong here.
        kept.append(entry)


def read_cycle_journal(
    root: Path, *, limit: int | None = None, day: str | None = None
) -> list[dict[str, Any]]:
    """Read the compact cycle journal (closed segments, then the active file).

    ``limit`` keeps only the LAST ``limit`` events and ``day`` keeps only one UTC
    day; both filter while streaming, so neither scales the memory used with the
    size of the log on disk.
    """
    tail = journal_line_limit(limit)
    kept: deque[dict[str, Any]] = deque(maxlen=tail)
    stats = {"lines": 0, "oversized_lines": 0, "unparsable_lines": 0, "filtered_lines": 0}
    for segment in cycle_journal_segments(root):
        _read_journal_file(segment, kept=kept, limit=tail, stats=stats, day=day)
    _read_journal_file(
        Path(root) / CYCLE_JOURNAL_FILENAME, kept=kept, limit=tail, stats=stats, day=day
    )
    return list(kept)


def journal_read_diagnostics(
    root: Path, *, day: str | None = None
) -> dict[str, int]:
    """Counters of what a bounded read had to skip (forensics, never silent)."""
    stats = {"lines": 0, "oversized_lines": 0, "unparsable_lines": 0, "filtered_lines": 0}
    kept: deque[dict[str, Any]] = deque(maxlen=0)
    for segment in cycle_journal_segments(root):
        _read_journal_file(segment, kept=kept, limit=0, stats=stats, day=day)
    _read_journal_file(
        Path(root) / CYCLE_JOURNAL_FILENAME, kept=kept, limit=0, stats=stats, day=day
    )
    return stats


def _last_event(root: Path) -> dict[str, Any] | None:
    events = read_cycle_journal(root, limit=1)
    return events[-1] if events else None


def _delta(current: Any, previous: Any) -> int | None:
    if current is None:
        return None
    if previous is None:
        return int(current)
    return int(current) - int(previous)


def _phase_map(record: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """A sub-object of a cycle result, or an empty mapping when absent."""
    value = record.get(key)
    return value if isinstance(value, Mapping) else {}


def _verifier_result(record: Mapping[str, Any]) -> Any:
    verify = record.get("verify")
    if not isinstance(verify, Mapping):
        return "SKIPPED"
    return {
        "status": verify.get("status"),
        "passed": verify.get("passed"),
        "total": verify.get("total"),
        "mismatches": verify.get("mismatches"),
        "false_success": verify.get("false_success"),
    }


def _action_outcomes(record: Mapping[str, Any], mode: str) -> bool | None:
    """Whether a due action actually ran this cycle (``None`` = not attempted)."""
    if mode not in (record.get("modes") or []):
        return None
    phase = record.get(mode)
    if not isinstance(phase, Mapping):
        return None
    for key in ("sealed", "settled", "evaluated"):
        value = phase.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return len(value) > 0
        if isinstance(value, int):
            return value > 0
    skipped = phase.get("skipped")
    if skipped is not None:
        return False
    return None


def cycle_event(
    record: Mapping[str, Any],
    *,
    previous_hash: str,
    previous_population: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a full in-memory cycle result onto the compact journal contract.

    The full result legitimately carries the counters, the heartbeat and the daily
    rollup for this cycle's own consumers; none of that belongs in the journal,
    which is an *event* stream.  Everything here is a scalar or a tiny list.
    """
    population = dict(record.get("counters") or {})
    previous = dict(previous_population or {})
    seal = _phase_map(record, "seal")
    settle = _phase_map(record, "settle")
    chain = _phase_map(record, "chain")
    drift = _phase_map(record, "drift")
    errors = [dict(item) for item in (record.get("errors") or [])]
    modes = [str(item) for item in (record.get("modes") or [])]
    finished = record.get("finished_at")
    event: dict[str, Any] = {
        "event_version": CYCLE_JOURNAL_VERSION,
        "cycle": int(record.get("cycle", 0)),
        "campaign_id": record.get("campaign_id"),
        "day": record.get("day"),
        "started_at": record.get("started_at"),
        "started_at_utc": record.get("started_at_utc"),
        "finished_at": finished,
        "finished_at_utc": (
            dt.datetime.fromtimestamp(int(finished), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if finished is not None
            else None
        ),
        "actions_due": modes,
        "actions_completed": {
            mode: _action_outcomes(record, mode) for mode in modes
        },
        "sealed_count_delta": len(seal.get("sealed") or []),
        "settled_count_delta": len(settle.get("settled") or []),
        "evaluated_count_delta": _delta(
            population.get("evaluated_decisions"), previous.get("evaluated_decisions")
        ),
        "population": {
            key: population.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "matured_unsettled",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "chain_status": record.get("campaign_status_chain") or (chain.get("status")),
        "drift_status": drift.get("status"),
        "verifier_result": _verifier_result(record),
        "error_codes": [str(item.get("code")) for item in errors],
        "previous_event_hash": previous_hash,
    }
    event["event_hash"] = ac.payload_digest(event)
    return event


def rotate_cycle_journal(root: Path, *, force: bool = False) -> dict[str, Any]:
    """Roll the active journal into a numbered, hashed segment when it is large.

    Atomic by construction: the active file is renamed (never truncated and never
    rewritten), so a crash leaves either the old active journal or a complete
    segment.  The manifest records the segment's own ``event_hash`` range and its
    SHA-256, which is what makes the chain auditable across files.
    """
    root = Path(root)
    active = root / CYCLE_JOURNAL_FILENAME
    if not active.is_file():
        return {"status": "NO_JOURNAL", "path": str(active)}
    size = active.stat().st_size
    if not force and size < CYCLE_SEGMENT_MAX_BYTES:
        return {"status": "NOT_DUE", "bytes": size, "threshold": CYCLE_SEGMENT_MAX_BYTES}
    if active.stat().st_size == 0:
        return {"status": "EMPTY", "path": str(active)}

    directory = root / CYCLE_SEGMENT_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    sequence = len(cycle_journal_segments(root)) + 1
    target = directory / f"cycles-{sequence:06d}.jsonl"
    digest = hashlib.sha256()
    first_cycle: int | None = None
    last_cycle: int | None = None
    first_hash: str | None = None
    last_hash: str | None = None
    records = 0
    # Pass 1 — digest and record count, in fixed-size chunks (bounded memory).
    with active.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            records += chunk.count(b"\n")
    # Pass 2 — the segment's chain range, again line-by-line and bounded.
    for raw, oversized in _iter_journal_lines(active, max_line_bytes=MAX_JOURNAL_LINE_BYTES):
        if oversized or not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        first_cycle = int(entry.get("cycle", 0)) if first_cycle is None else first_cycle
        last_cycle = int(entry.get("cycle", 0))
        first_hash = first_hash or entry.get("event_hash")
        last_hash = entry.get("event_hash")
    os.replace(active, target)
    manifest_path = directory / CYCLE_SEGMENT_MANIFEST
    manifest = read_segment_manifest(root)
    manifest["segments"] = [
        entry for entry in manifest.get("segments", []) if entry.get("segment") != target.name
    ] + [
        {
            "segment": target.name,
            "records": records,
            "bytes": int(target.stat().st_size),
            "first_cycle": first_cycle,
            "last_cycle": last_cycle,
            "first_event_hash": first_hash,
            "last_event_hash": last_hash,
            "sha256": digest.hexdigest(),
        }
    ]
    manifest["segments"].sort(key=lambda item: str(item["segment"]))
    manifest["segment_version"] = CYCLE_JOURNAL_VERSION
    manifest["segment_max_bytes"] = CYCLE_SEGMENT_MAX_BYTES
    write_json_atomic(manifest_path, manifest)
    return {
        "status": "ROTATED",
        "segment": str(target),
        "records": records,
        "bytes": int(target.stat().st_size),
        "sha256": digest.hexdigest(),
    }


def read_segment_manifest(root: Path) -> dict[str, Any]:
    path = Path(root) / CYCLE_SEGMENT_DIRNAME / CYCLE_SEGMENT_MANIFEST
    if not path.is_file():
        return {"segment_version": CYCLE_JOURNAL_VERSION, "segments": []}
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def append_journal_line(path: Path, payload: Mapping[str, Any]) -> None:
    """Append one compact event.  Flush + fsync so a crash cannot lose the tail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_cycle_record(root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    """Append one COMPACT cycle event to the journal (never the full result).

    The record handed in is the runner's full in-memory cycle result; it is
    projected onto :data:`CYCLE_EVENT_KEYS` before it touches the disk.  The hash
    chain and the size-driven segmentation keep the log auditable and bounded.
    """
    root = Path(root)
    previous = _last_event(root)
    event = cycle_event(
        record,
        previous_hash=str((previous or {}).get("event_hash") or CYCLE_GENESIS_HASH),
        previous_population=(previous or {}).get("population"),
    )
    append_journal_line(root / CYCLE_JOURNAL_FILENAME, event)
    rotation = rotate_cycle_journal(root)
    return {"event": event, "rotation": rotation}


def verify_cycle_chain(root: Path) -> dict[str, Any]:
    """Re-derive the journal's own chain, across closed segments and the active file."""
    previous = CYCLE_GENESIS_HASH
    events = 0
    for path in [*cycle_journal_segments(Path(root)), Path(root) / CYCLE_JOURNAL_FILENAME]:
        if not path.is_file():
            continue
        for raw, oversized in _iter_journal_lines(path, max_line_bytes=MAX_JOURNAL_LINE_BYTES):
            if oversized or not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                return {
                    "status": "BROKEN",
                    "reason": "unparsable journal line",
                    "file": str(path),
                    "events": events + 1,
                }
            if str(entry.get("previous_event_hash")) != previous:
                return {
                    "status": "BROKEN",
                    "reason": "previous_event_hash does not match the prior event_hash",
                    "file": str(path),
                    "cycle": entry.get("cycle"),
                    "events": events + 1,
                }
            body = {key: value for key, value in entry.items() if key != "event_hash"}
            if str(entry.get("event_hash")) != ac.payload_digest(body):
                return {
                    "status": "BROKEN",
                    "reason": "event_hash does not re-derive from the event body",
                    "file": str(path),
                    "cycle": entry.get("cycle"),
                    "events": events + 1,
                }
            previous = str(entry["event_hash"])
            events += 1
    return {"status": "INTACT", "events": events, "head": previous}


# --------------------------------------------------------------------------- #
# §4 — campaign status
# --------------------------------------------------------------------------- #


def status_payload(
    *,
    manifest: Mapping[str, Any],
    counters: Mapping[str, Any],
    scorecard: Mapping[str, Any],
    drift: Mapping[str, Any],
    model_drift: Mapping[str, Any],
    raw_evidence: Mapping[str, Any],
    chain: Mapping[str, Any],
    status: str,
    now: int,
    next_decision_slot: int | None = None,
    errors: Sequence[Mapping[str, Any]] = (),
    heartbeat: Mapping[str, Any] | None = None,
    disk: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The campaign dashboard payload (requirement: no single denominator)."""
    states = counters.get("decision_states") or []
    maturity_times = [
        int(item["maturity_time"]) for item in states if item["maturity"] != "MATURED"
    ]
    evaluated = int(counters.get("evaluated_decisions", 0))
    reached = [point for point in asc.CHECKPOINTS if evaluated >= point]
    campaign_start = int(manifest.get("campaign_start", now))
    return {
        "campaign_id": manifest.get("campaign_id"),
        "campaign_version": manifest.get("campaign_version"),
        "campaign_status": status,
        "as_of": int(now),
        "as_of_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campaign_age_seconds": int(now) - campaign_start,
        "campaign_age_days": round((int(now) - campaign_start) / 86_400, 3),
        "population": {
            "sealed_decisions": counters.get("sealed_decisions"),
            "pending_decisions": counters.get("pending_decisions"),
            "matured_decisions": counters.get("matured_decisions"),
            "matured_unsettled": counters.get("matured_unsettled"),
            "settled_outcomes": counters.get("settled_outcomes"),
            "evaluated_decisions": counters.get("evaluated_decisions"),
            "verified_evaluations": counters.get("verified_evaluations"),
        },
        "denominator_note": (
            "sealed, matured, settled and evaluated are different populations; none of them is "
            "the campaign total"
        ),
        "analyst_distribution": {
            "LONG": counters.get("long_count"),
            "SHORT": counters.get("short_count"),
            "NO_TRADE": counters.get("no_trade_count"),
        },
        # Canonical counter names, so a consumer never has to translate the
        # display distribution back to the machine vocabulary.
        "direction_counts": {
            "long_count": counters.get("long_count"),
            "short_count": counters.get("short_count"),
            "no_trade_count": counters.get("no_trade_count"),
        },
        "cohorts": counters.get("by_cohort"),
        "by_asset": counters.get("by_asset"),
        "by_horizon": counters.get("by_horizon"),
        "checkpoint_progress": {
            "checkpoints": list(asc.CHECKPOINTS),
            "checkpoint_reached": max(reached) if reached else 0,
            "next_checkpoint": scorecard.get("sample", {}).get("next_checkpoint"),
            "min_evaluable_decisions": asc.MIN_EVALUABLE_DECISIONS,
        },
        "next_decision_slot": next_decision_slot,
        "next_maturity": min(maturity_times) if maturity_times else None,
        "next_maturity_utc": (
            dt.datetime.fromtimestamp(min(maturity_times), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if maturity_times
            else None
        ),
        "chain_status": chain.get("status"),
        "chain_broken": chain.get("broken"),
        "provenance_status": (
            "COMPLETE" if model_drift.get("status") == "NO_DRIFT" else str(model_drift.get("status"))
        ),
        "drift_status": drift.get("status"),
        "drift_knobs": drift.get("drifted"),
        "model_drift": model_drift,
        "raw_evidence_status": raw_evidence.get("status"),
        "raw_evidence_counts": raw_evidence.get("counts"),
        "primary_metric": manifest.get("primary_metric"),
        "g_agentic_edge": scorecard.get("gate"),
        "alpha_claimed": scorecard.get("alpha_claimed"),
        "profitability_status": scorecard.get("profitability_status"),
        "trades_authorized": ac.TRADES_AUTHORIZED,
        "economic_state_note": "docs/research/ECONOMIC_STATE.json is never written by the campaign",
        "heartbeat_age_seconds": heartbeat_age_seconds(heartbeat, now=now),
        "errors": [dict(item) for item in errors],
        "disk_free_bytes": (disk or {}).get("free_bytes"),
        "disk_status": (disk or {}).get("status"),
        "storage": dict(disk) if disk else None,
    }


def render_status_md(payload: Mapping[str, Any], *, metrics: Mapping[str, Any]) -> str:
    """A one-screen markdown view of the campaign."""
    population = payload.get("population") or {}
    ages = payload.get("campaign_age_days")
    lines = [
        f"# Campaign status — {payload.get('campaign_id')}",
        "",
        f"- status: **{payload.get('campaign_status')}**",
        f"- age: {ages} days",
        f"- as of: {payload.get('as_of_utc')}",
        f"- chain: {payload.get('chain_status')}   drift: {payload.get('drift_status')}",
        f"- raw evidence: {payload.get('raw_evidence_status')}",
        "",
        "## Population (never one denominator)",
        "",
        "| population | count |",
        "| --- | --- |",
    ]
    for key, value in population.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Analyst distribution",
            "",
            "| direction | count |",
            "| --- | --- |",
        ]
    )
    for key, value in (payload.get("analyst_distribution") or {}).items():
        lines.append(f"| {key} | {value} |")
    progress = payload.get("checkpoint_progress") or {}
    lines.extend(
        [
            "",
            "## Progress",
            "",
            f"- checkpoints: {progress.get('checkpoints')}",
            f"- reached: {progress.get('checkpoint_reached')}",
            f"- next: {progress.get('next_checkpoint')}",
            f"- floor for any edge verdict: {progress.get('min_evaluable_decisions')}",
            f"- next decision slot: {payload.get('next_decision_slot')}",
            f"- next maturity: {payload.get('next_maturity_utc')}",
            "",
            "## G_AGENTIC_EDGE",
            "",
            f"- {(payload.get('g_agentic_edge') or {}).get('status')} "
            f"({(payload.get('g_agentic_edge') or {}).get('conclusion')})",
            f"- alpha claimed: {payload.get('alpha_claimed')}",
            f"- profitability: {payload.get('profitability_status')}",
            f"- trades authorized: {payload.get('trades_authorized')}",
            "",
            "## Diagnostics (not the primary metric)",
            "",
            f"- net mean: {(metrics.get('net') or {}).get('mean')}",
            f"- net median: {(metrics.get('net') or {}).get('median')}",
            f"- direction accuracy: {metrics.get('direction_accuracy')}",
            f"- per-decision sharpe: {(metrics.get('net') or {}).get('per_decision_sharpe')} "
            f"({(metrics.get('net') or {}).get('sharpe_status')})",
            f"- sample warnings: {metrics.get('sample_warnings')}",
            "",
        ]
    )
    errors = payload.get("errors") or []
    lines.append("## Errors")
    lines.append("")
    if errors:
        for item in errors:
            lines.append(f"- {item}")
    else:
        lines.append("- none recorded this cycle")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# §5 — daily rollup
# --------------------------------------------------------------------------- #


def daily_report(
    *,
    day: str,
    ledger: Any,
    cycles: Sequence[Mapping[str, Any]],
    chain: Mapping[str, Any],
    drift: Mapping[str, Any],
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per UTC day: what was sealed, what matured, what was evaluated, what failed.

    Bounded projection (CAP-004C): the day is *aggregated*, never embedded.  The
    previous version copied every cycle of the day into ``cycles``, so the file
    grew quadratically within the day (its own writer was the largest thing it
    wrote).  A bounded tail plus the failure codes keeps the forensics without the
    amplification.
    """
    decisions = ledger.decisions()
    outcomes = ledger.outcomes()
    evaluations = ledger.evaluations()
    day_cycles = [dict(item) for item in cycles if str(item.get("day")) == day]
    failures = [
        {
            "cycle": item.get("cycle"),
            "at": item.get("finished_at") or item.get("started_at"),
            "error_codes": list(item.get("error_codes") or []),
        }
        for item in day_cycles
        if item.get("error_codes")
    ]
    settled_keys = {(str(item["decision_id"]), str(item["horizon"])) for item in outcomes}
    matured_today = [
        item
        for item in decisions
        if utc_day(int(item["decision_time"]) + do.HORIZON_SECONDS[str(item["horizon"])]) == day
    ]
    tail = day_cycles[-DAILY_CYCLE_TAIL:]
    deltas = {
        "sealed": sum(int(item.get("sealed_count_delta") or 0) for item in day_cycles),
        "settled": sum(int(item.get("settled_count_delta") or 0) for item in day_cycles),
    }
    return {
        "report_version": DAILY_REPORT_VERSION,
        "day": day,
        "decisions_sealed": len(
            [item for item in decisions if utc_day(int(item["decision_time"])) == day]
        ),
        "outcomes_matured": len(
            [item for item in outcomes if utc_day(int(item["exit_close_time"])) == day]
        ),
        "evaluations_completed": len(
            [item for item in evaluations if utc_day(int(item["evaluation_time"])) == day]
        ),
        "matured_today": len(matured_today),
        "matured_unsettled": len(
            [
                item
                for item in matured_today
                if (str(item["decision_id"]), str(item["horizon"])) not in settled_keys
            ]
        ),
        "cycle_count": len(day_cycles),
        # The projection is written before the cycle that produced it journals its
        # own event, so it describes the cycles already on record.  The lag is
        # declared rather than hidden, and it is bounded by exactly one cycle.
        "projection_lag_cycles": 1,
        "projection_lag_note": (
            "cycle_count counts the compact events journaled when this projection was "
            "written; the running cycle adds its own event immediately afterwards"
        ),
        "cycle_deltas": deltas,
        "cycles_tail": tail,
        "cycles_omitted": max(0, len(day_cycles) - len(tail)),
        "failure_count": len(failures),
        "failures": failures[-DAILY_FAILURES_TAIL:],
        "drift": {"status": drift.get("status"), "drifted": drift.get("drifted")},
        "verification": verification,
        "chain_status": chain.get("status"),
        "projection_note": (
            "derived projection: aggregates the compact cycle journal of this UTC day; "
            "regenerable from reports/cap004 (segments + active journal), never a source of truth"
        ),
    }


def write_daily_report(root: Path, payload: Mapping[str, Any]) -> Path:
    day = str(payload.get("day"))
    return write_json_atomic(Path(root) / "daily" / f"{day}.json", payload)


# --------------------------------------------------------------------------- #
# §6 — checkpoints
# --------------------------------------------------------------------------- #


def checkpoint_decision_set_hash(performances: Sequence[do.DecisionPerformance]) -> str:
    """Identifies the population a checkpoint describes.

    A sorted list of ``[decision_id, outcome_hash, evaluation_hash]`` triples, so
    the digest is order-independent but duplicate-sensitive — a checkpoint can
    never claim the same population twice.
    """
    return ac.payload_digest(
        sorted(
            [item.decision_id, item.outcome_hash, item.evaluation_hash]
            for item in performances
        )
    )


def checkpoint_decision_set_hash_from_records(entries: Sequence[Mapping[str, Any]]) -> str:
    """Same digest, computed from raw evaluation dicts (verifier-side helper)."""
    return ac.payload_digest(
        sorted(
            [
                str(item["decision_id"]),
                str(item["outcome_hash"]),
                str(item["evaluation_hash"]),
            ]
            for item in entries
        )
    )


def checkpoint_json_path(root: Path, checkpoint: int) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.json"


def checkpoint_md_path(root: Path, checkpoint: int) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME / f"CHECKPOINT_{checkpoint:03d}.md"


def read_checkpoint(root: Path, checkpoint: int) -> dict[str, Any] | None:
    path = checkpoint_json_path(root, checkpoint)
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def build_checkpoint_payload(
    *,
    checkpoint: int,
    performances: Sequence[do.DecisionPerformance],
    scorecard: Mapping[str, Any],
    metrics: Mapping[str, Any],
    no_trade: Mapping[str, Any],
    counters: Mapping[str, Any],
    drift: Mapping[str, Any],
    model_drift: Mapping[str, Any],
    now: int,
    errors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """A checkpoint's content: A/B/C/D, populations, selectivity, drift, errors."""
    return {
        "checkpoint_version": CHECKPOINT_JSON_VERSION,
        "checkpoint": checkpoint,
        "created_at": int(now),
        "created_at_utc": dt.datetime.fromtimestamp(int(now), dt.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "decision_set_hash": checkpoint_decision_set_hash(performances),
        "n_evaluated": len(performances),
        "population": {
            key: counters.get(key)
            for key in (
                "sealed_decisions",
                "pending_decisions",
                "matured_decisions",
                "matured_unsettled",
                "settled_outcomes",
                "evaluated_decisions",
                "verified_evaluations",
            )
        },
        "cohorts": counters.get("by_cohort"),
        "analyst_vs_baselines": {
            "agent": scorecard.get("agent"),
            "comparators": scorecard.get("comparators"),
            "incremental_edges": scorecard.get("incremental_edges"),
        },
        "direction_accuracy": metrics.get("direction_accuracy"),
        "net_performance": metrics.get("net"),
        "no_trade": {
            "rate": (metrics.get("distribution") or {}).get("no_trade_rate"),
            "count": (metrics.get("distribution") or {}).get("no_trade_count"),
            "selectivity": no_trade,
        },
        "confidence_buckets": metrics.get("confidence_buckets"),
        "per_asset": metrics.get("per_asset"),
        "sample_warnings": metrics.get("sample_warnings"),
        "gate": scorecard.get("gate"),
        "edge_verdict": (
            "NOT_PERMITTED_BELOW_SAMPLE_FLOOR"
            if int(scorecard.get("n_decisions_evaluated", 0)) < asc.MIN_EVALUABLE_DECISIONS
            else "PERMITTED_AT_OR_ABOVE_SAMPLE_FLOOR"
        ),
        "drift": {"status": drift.get("status"), "drifted": drift.get("drifted")},
        "model_drift": {"status": model_drift.get("status")},
        "errors": [dict(item) for item in errors],
        "is_diagnostic_only": True,
    }


def checkpoint_md(payload: Mapping[str, Any]) -> str:
    edges = payload.get("incremental_edges") or {}
    lines = [
        f"# CHECKPOINT_{int(payload['checkpoint']):03d}",
        "",
        f"- created: {payload.get('created_at_utc')}",
        f"- population: {payload.get('n_evaluated')} evaluated",
        f"- decision_set_hash: `{payload.get('decision_set_hash')}`",
        f"- edge verdict: {payload.get('edge_verdict')}",
        f"- gate: {(payload.get('gate') or {}).get('status')}",
        "",
        "## Incremental edges (A vs comparators)",
        "",
        "| comparator | edge |",
        "| --- | --- |",
    ]
    for key, value in edges.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Populations",
            "",
            "| population | count |",
            "| --- | --- |",
        ]
    )
    for key, value in (payload.get("population") or {}).items():
        lines.append(f"| {key} | {value} |")
    selectivity = (payload.get("no_trade") or {}).get("selectivity") or {}
    lines.extend(
        [
            "",
            "## NO_TRADE selectivity",
            "",
            f"- status: {selectivity.get('status')}",
            f"- rate: {(payload.get('no_trade') or {}).get('rate')}",
            f"- no_trade bad-window rate: {selectivity.get('no_trade_bad_window_rate')}",
            f"- base bad-window rate: {selectivity.get('base_bad_window_rate')}",
            f"- lift: {selectivity.get('selectivity_lift')}",
            f"- avoided loss: {selectivity.get('total_avoided_loss')}",
            f"- missed gain: {selectivity.get('total_missed_gain')}",
            "",
            "Diagnostic only. The primary metric is unchanged and no profitability is claimed.",
            "",
        ]
    )
    return "\n".join(lines)


def write_checkpoint(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Write a checkpoint exactly once for its population."""
    checkpoint = int(payload["checkpoint"])
    path = checkpoint_json_path(root, checkpoint)
    existing = read_checkpoint(root, checkpoint)
    if existing is not None:
        same = existing.get("decision_set_hash") == payload.get("decision_set_hash")
        return {
            "status": "ALREADY_EXISTS" if same else "CHECKPOINT_CONFLICT",
            "path": str(path),
            "checkpoint": checkpoint,
            "decision_set_hash": payload.get("decision_set_hash"),
            "existing_decision_set_hash": existing.get("decision_set_hash"),
        }
    write_json_atomic(path, payload)
    checkpoint_md_path(root, checkpoint).write_text(checkpoint_md(payload), encoding="utf-8")
    return {
        "status": "CREATED",
        "path": str(path),
        "checkpoint": checkpoint,
        "decision_set_hash": payload.get("decision_set_hash"),
    }


def checkpoint_dir(root: Path) -> Path:
    return Path(root) / CHECKPOINT_DIRNAME
