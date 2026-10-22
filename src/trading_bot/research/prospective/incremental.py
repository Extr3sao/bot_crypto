"""Incremental, sharded, write-once capture over the forward store.

WP-051-02F proved that the phase-2 extractor can publish a dataset from the forward store and that
an independent verifier can re-read it. It also proved the ceiling: that extractor selects every
bar of a window at once, ignores ``coverage_required``, and refuses to rewrite its target, so a
capture taken on the first day of a ninety-day window freezes fourteen bars of a two-thousand-bar
promise for ever (``DEF-02F-01``).

This module is the mechanism that removes the ceiling without touching phase 2. It does not
replace the extractor and it does not re-open the phase-2 datasets; it adds a second, separate
way of acquiring the same kind of evidence:

* **one shard per UTC day and slice.** A day is captured when every bar the declaration expects
  for it has closed. The shard holds the store's own lines, verbatim, so a shard row and a store
  row are the same bytes and the comparison is an equality of bytes rather than of numbers.
* **write once, never regenerate.** A shard is written to a temporary file, flushed and renamed;
  the manifest is written last, so a shard exists when — and only when — its manifest does. A
  second capture of the same day is idempotent: identical bytes are reported as already held,
  different bytes are refused as a conflict instead of overwriting evidence.
* **the declaration is the denominator.** Expected bars come from the declared window and the
  declared timeframe, never from the data that happens to be on disk. Coverage is
  ``admissible_bars / declared_bars`` and it can be incomplete for ever without ever becoming a
  pass.
* **admissibility is decided per day, from the lag.** ``fetched_at_ms - (ts + interval)`` is the
  only field that separates a bar that was watched from a bar that was backfilled. A day holding
  one late, negative-lag or future bar is written — the bytes are real — but it is marked
  inadmissible and excluded from the consolidated dataset and from the numerator.
* **rehearsal is not coverage.** The mechanism can be exercised on historical store bytes under a
  declared rehearsal window. Everything it writes is stamped ``prospective: false`` and
  ``counts_toward_coverage: false``, and the phase's own coverage stays exactly where it was.

Research only: reads local files, writes local files, makes no network call, places no order.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The repository this module belongs to, so that manifests name paths a reader can find
#: without knowing which directory the capturing process happened to run in.
REPO = Path(__file__).resolve().parents[4]

from trading_bot.research.prospective.store import (  # noqa: E402
    INTERVAL_MS,
    Bar,
    SeriesIndex,
    StoreError,
    index_series,
)

__all__ = [
    "COVERAGE_BELOW_DECLARED",
    "COVERAGE_COMPLETE",
    "COVERAGE_PENDING",
    "COVERAGE_PENDING_WINDOW_OPEN",
    "CaptureError",
    "Consolidation",
    "Declaration",
    "DeclarationError",
    "Entry",
    "Plan",
    "ShardConflict",
    "capture_plan",
    "consolidate",
    "coverage_status",
    "day_opens",
    "expected_opens",
    "load_declaration",
    "read_state",
    "recover_partials",
    "shard_days",
    "shard_paths",
    "state_path",
    "utc_day",
    "write_state",
]

SCHEMA_VERSION = "1.0"

#: Where the scheduler's own memory lives, relative to the capture root. The state file is the
#: watermark that makes a repetition cheap and a resume possible; it is not evidence, and the
#: verifier never reads it.
STATE_DIR = "state"
STATE_FILE = "scheduler.json"
LOCK_FILE = "capture.lock"
CONSOLIDATED_DIR = "consolidated"

#: The coverage vocabulary. ``COVERAGE_COMPLETE`` is the only word that may accompany a pass, and
#: it is reachable only when the numerator equals the declared denominator exactly.
COVERAGE_PENDING_WINDOW_OPEN = "PENDING_WINDOW_OPEN"
COVERAGE_PENDING = "PENDING"
COVERAGE_BELOW_DECLARED = "BELOW_DECLARED"
COVERAGE_COMPLETE = "COVERAGE_COMPLETE"

#: Shard states, as recorded in ``state/scheduler.json`` per slice.
SHARD_CAPTURED = "CAPTURED"
SHARD_ALREADY_HELD = "ALREADY_HELD"
SHARD_CONFLICT = "CONFLICT"
SHARD_NOT_DUE = "NOT_DUE"
SHARD_INCOMPLETE = "INCOMPLETE_DAY"
SHARD_REFUSED = "REFUSED"

#: Defect codes. Each one names a *different* lie a shard could be telling, so that a reader can
#: tell an interrupted write from a hand-edited line.
DEFECT_GAP = "GAP_IN_DAY"
DEFECT_MISSING_DAY = "MISSING_DAY"
DEFECT_DUPLICATE = "DUPLICATE_OPEN"
DEFECT_FUTURE = "FUTURE_BAR"
DEFECT_NEGATIVE_LAG = "NEGATIVE_LAG"
DEFECT_LATE = "LAG_OVER_BOUND"
DEFECT_UNCLOSED = "BAR_NOT_CLOSED_AT_CAPTURE"
DEFECT_SHARD_DIGEST = "SHARD_DIGEST_MISMATCH"
DEFECT_SHARD_MANIFEST = "SHARD_MANIFEST_UNREADABLE"
DEFECT_SOURCE_DIVERGED = "SOURCE_BYTES_DIVERGED"
DEFECT_PREMATURE = "SHARD_BEFORE_DAY_CLOSE"
DEFECT_ROW_NOT_IN_STORE = "ROW_NOT_IN_STORE"
DEFECT_REHEARSAL_IN_COVERAGE = "REHEARSAL_COUNTED_AS_COVERAGE"


class DeclarationError(RuntimeError):
    """The declaration cannot be read as a contract, so nothing may be captured under it."""


class CaptureError(RuntimeError):
    """The capture cannot be performed without inventing a rule, so it is not performed."""


class ShardConflict(CaptureError):
    """A shard for this day exists and holds different bytes. Overwriting would be a rewrite."""


# --------------------------------------------------------------------------- #
# instants
# --------------------------------------------------------------------------- #


def iso(ms: int) -> str:
    """An instant, in the one format this package writes and the verifier parses."""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_ms(value: object, field_name: str) -> int:
    """Parse an ISO-8601 instant, refusing one without a zone."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise DeclarationError(f"{field_name} is not an ISO timestamp: {value!r}") from error
    if moment.tzinfo is None:
        raise DeclarationError(f"{field_name} is naive; a window without a zone is not a window")
    return int(moment.astimezone(UTC).timestamp() * 1000)


def utc_day(open_ms: int) -> str:
    """The UTC calendar day of a bar's *open*, which is the shard key."""
    return datetime.fromtimestamp(open_ms / 1000, UTC).strftime("%Y-%m-%d")


def day_start_ms(day: str) -> int:
    moment = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    return int(moment.timestamp() * 1000)


def expected_opens(start_ms: int, end_ms: int, interval_ms: int) -> tuple[int, ...]:
    """Every bar open the window expects, on the epoch grid.

    The grid is the store's own: a 1h bar opens on a whole hour of UTC. Deriving the expectation
    from the window and the interval — rather than from the bars that happen to exist — is what
    keeps a missing bar missing instead of invisible.
    """
    if end_ms <= start_ms:
        raise CaptureError("the window ends before it starts")
    first = -(-start_ms // interval_ms) * interval_ms
    return tuple(range(first, end_ms, interval_ms))


def shard_days(start_ms: int, end_ms: int, interval_ms: int) -> tuple[str, ...]:
    """The UTC days the window touches, in order, derived from the grid."""
    days: list[str] = []
    for open_ms in expected_opens(start_ms, end_ms, interval_ms):
        day = utc_day(open_ms)
        if not days or days[-1] != day:
            days.append(day)
    return tuple(days)


def day_opens(day: str, interval_ms: int) -> tuple[int, ...]:
    """Every grid open inside one UTC day. A whole day of 1h bars is twenty-four openings."""
    start = day_start_ms(day)
    return tuple(range(start, start + 86_400_000, interval_ms))


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Entry:
    """One slice of the acquisition contract: one dataset, one asset, one timeframe."""

    dataset_id: str
    asset: str
    interval: str
    timeframe: str
    source: Path
    period_start_ms: int
    period_end_ms: int
    lag_bound_ms: int
    coverage_required: float
    declared_rows: int
    shard_root: Path
    generator_command: str

    @property
    def label(self) -> str:
        return f"{self.interval}:{self.asset}"

    @property
    def interval_ms(self) -> int:
        return INTERVAL_MS[self.interval]

    @property
    def declared_days(self) -> int:
        return len(shard_days(self.period_start_ms, self.period_end_ms, self.interval_ms))

    def with_window(self, start_ms: int, end_ms: int, shard_root: Path) -> Entry:
        """The same slice, asset and lag bound over the rehearsal's own window.

        The window is taken as given and is *not* clamped to the phase's period: a rehearsal is by
        construction a stretch of the store the phase window does not cover, and clamping would
        make it either empty or a leak. The declaration refuses an overlap instead.
        """
        if end_ms <= start_ms:
            raise CaptureError("the rehearsal window ends before it starts")
        return Entry(
            dataset_id=self.dataset_id,
            asset=self.asset,
            interval=self.interval,
            timeframe=self.timeframe,
            source=self.source,
            period_start_ms=start_ms,
            period_end_ms=end_ms,
            lag_bound_ms=self.lag_bound_ms,
            coverage_required=self.coverage_required,
            declared_rows=len(expected_opens(start_ms, end_ms, self.interval_ms)),
            shard_root=shard_root,
            generator_command=self.generator_command,
        )


@dataclass(frozen=True, slots=True)
class Rehearsal:
    """A declared, bounded, non-prospective window used to exercise the mechanism.

    It is in the declaration rather than in a command-line flag so that a rehearsal is a
    preregistered act with a start, an end and a denominator — and so that a reader can see, in
    the contract itself, that it does not count.
    """

    start_ms: int
    end_ms: int
    counts_toward_coverage: bool
    shard_root: Path
    note: str


@dataclass(frozen=True, slots=True)
class Declaration:
    """The acquisition contract, parsed and resolved to paths that exist."""

    path: Path
    sha256: str
    declaration_id: str
    effective_from_ms: int
    window_start_ms: int
    window_end_ms: int
    entries: tuple[Entry, ...]
    rehearsal: Rehearsal | None
    lag_policy: dict[str, Any]
    shard_granularity: str
    raw: dict[str, Any]

    def slice_labels(self) -> tuple[str, ...]:
        return tuple(entry.label for entry in self.entries)

    def entry(self, label: str) -> Entry:
        for candidate in self.entries:
            if candidate.label == label:
                return candidate
        raise DeclarationError(f"{label!r} is not declared; declared slices are {list(self.slice_labels())}")


def _require(document: dict[str, Any], key: str, context: str) -> Any:
    if key not in document or document[key] in (None, ""):
        raise DeclarationError(f"{context} is missing {key!r}")
    return document[key]


def load_declaration(path: Path) -> Declaration:
    """Read one declaration and refuse anything that is not a complete contract.

    The refusals are the contract: an entry without a lag bound would let a backfilled bar pass
    as prospectively observed, and a declaration without a denominator would let coverage be
    computed from whatever was captured.
    """
    path = Path(path)
    if not path.is_file():
        raise DeclarationError(f"{path} does not exist; there is no declared acquisition contract")
    raw_bytes = path.read_bytes()
    try:
        document: Any = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DeclarationError(f"{path} is not UTF-8 JSON: {error}") from error
    if not isinstance(document, dict):
        raise DeclarationError(f"{path} is not an object")
    window = _require(document, "capture_window", str(path))
    if not isinstance(window, dict):
        raise DeclarationError(f"{path}: capture_window is not an object")
    window_start = parse_ms(_require(window, "start_utc", "capture_window"), "capture_window.start_utc")
    window_end = parse_ms(_require(window, "end_utc", "capture_window"), "capture_window.end_utc")
    if window_end <= window_start:
        raise DeclarationError(f"{path}: the declared window ends before it starts")
    effective = parse_ms(_require(document, "effective_from_utc", str(path)), "effective_from_utc")
    policy = document.get("lag_policy") or {}
    if not isinstance(policy, dict) or not policy.get("definition"):
        raise DeclarationError(f"{path}: lag_policy must define the lag it enforces")
    granularity = str(document.get("shard_policy", {}).get("granularity") or "")
    if granularity != "UTC_DAY":
        raise DeclarationError(
            f"{path}: shard granularity {granularity or 'absent'!r} is not supported; this "
            "implementation shards by UTC day and will not pretend otherwise"
        )
    shard_root = (path.parents[2] / str(document.get("shard_root") or "data/exp004a/phase3")).resolve()

    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise DeclarationError(f"{path} declares no entries")
    entries: list[Entry] = []
    seen: set[str] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise DeclarationError(f"{path}: an entry is not an object")
        ctx = str(item.get("dataset_id") or "an entry")
        interval = str(_require(item, "timeframe", ctx))
        if interval not in INTERVAL_MS:
            raise DeclarationError(
                f"{ctx} declares timeframe {interval!r}, which is not a bar series this "
                "implementation can shard. Refusing rather than inventing a shard rule."
            )
        asset = str(_require(item, "asset", ctx))
        label = f"{interval}:{asset}"
        if label in seen:
            raise DeclarationError(f"{ctx} repeats the slice {label}")
        seen.add(label)
        start = parse_ms(item.get("period_start_utc") or window["start_utc"], f"{ctx}.period_start_utc")
        end = parse_ms(item.get("period_end_utc") or window["end_utc"], f"{ctx}.period_end_utc")
        parameters = item.get("generator_parameters") or {}
        declared_rows = int(item.get("row_count") or len(expected_opens(start, end, INTERVAL_MS[interval])))
        entries.append(
            Entry(
                dataset_id=str(_require(item, "dataset_id", ctx)),
                asset=asset,
                interval=interval,
                timeframe=interval,
                source=(path.parents[2] / str(_require(item, "source_path", ctx))).resolve(),
                period_start_ms=start,
                period_end_ms=end,
                lag_bound_ms=int(
                    parameters.get("lag_bound_ms")
                    or item.get("lag_bound_ms")
                    or 0
                )
                or 0,
                coverage_required=float(
                    parameters.get("coverage_required") or item.get("coverage_required") or 0.0
                ),
                declared_rows=declared_rows,
                shard_root=shard_root,
                generator_command=str(item.get("generator_command") or ""),
            )
        )
    for entry in entries:
        if entry.lag_bound_ms <= 0:
            raise DeclarationError(
                f"{entry.dataset_id} declares no positive lag bound; without one a backfilled "
                "bar would be indistinguishable from an observed one"
            )
        if entry.period_start_ms < window_start or entry.period_end_ms > window_end:
            raise DeclarationError(
                f"{entry.dataset_id} leaves the declared capture window; a slice may cut the "
                "window short, never extend it"
            )
        if entry.declared_rows != len(
            expected_opens(entry.period_start_ms, entry.period_end_ms, entry.interval_ms)
        ):
            raise DeclarationError(
                f"{entry.dataset_id} declares {entry.declared_rows} rows but its window and "
                f"timeframe contain "
                f"{len(expected_opens(entry.period_start_ms, entry.period_end_ms, entry.interval_ms))}. "
                "The denominator is not negotiable."
            )

    rehearsal: Rehearsal | None = None
    rehearsal_doc = document.get("rehearsal")
    if isinstance(rehearsal_doc, dict):
        rehearsal = Rehearsal(
            start_ms=parse_ms(
                _require(rehearsal_doc, "start_utc", "rehearsal"), "rehearsal.start_utc"
            ),
            end_ms=parse_ms(_require(rehearsal_doc, "end_utc", "rehearsal"), "rehearsal.end_utc"),
            counts_toward_coverage=bool(rehearsal_doc.get("counts_toward_coverage", False)),
            shard_root=(path.parents[2] / str(rehearsal_doc.get("shard_root"))).resolve()
            if rehearsal_doc.get("shard_root")
            else shard_root / "rehearsal",
            note=str(rehearsal_doc.get("note") or ""),
        )
        if rehearsal.counts_toward_coverage:
            raise DeclarationError(
                "the rehearsal may not count toward coverage: a rehearsal is historical store "
                "bytes and cannot be prospective evidence for this window"
            )
        if rehearsal.end_ms <= rehearsal.start_ms:
            raise DeclarationError("the rehearsal window ends before it starts")
        if rehearsal.start_ms < window_end and window_start < rehearsal.end_ms:
            raise DeclarationError(
                "the rehearsal window overlaps the capture window; the two must not share an "
                "instant, so that no rehearsal byte can ever be read as a phase observation"
            )

    return Declaration(
        path=path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        declaration_id=str(_require(document, "declaration_id", str(path))),
        effective_from_ms=effective,
        window_start_ms=window_start,
        window_end_ms=window_end,
        entries=tuple(entries),
        rehearsal=rehearsal,
        lag_policy=policy,
        shard_granularity=granularity,
        raw=document,
    )


def resolve_window(
    declaration: Declaration, *, rehearsal: bool
) -> tuple[tuple[Entry, ...], int, int, bool]:
    """The entries to capture, their window, and whether they count toward coverage."""
    if not rehearsal:
        return (
            declaration.entries,
            declaration.window_start_ms,
            declaration.window_end_ms,
            True,
        )
    if declaration.rehearsal is None:
        raise CaptureError("this declaration defines no rehearsal window, so there is none to run")
    start = declaration.rehearsal.start_ms
    end = declaration.rehearsal.end_ms
    entries = tuple(
        entry.with_window(start, end, declaration.rehearsal.shard_root)
        for entry in declaration.entries
    )
    return entries, start, end, False


# --------------------------------------------------------------------------- #
# shard paths
# --------------------------------------------------------------------------- #


def slice_dir(root: Path, entry: Entry) -> Path:
    """Shards of one slice, under a name derived from the entry rather than from a filename."""
    return root / f"{entry.interval}_{entry.asset}"


def shard_paths(entry: Entry, day: str) -> tuple[Path, Path]:
    base = slice_dir(entry.shard_root, entry) / day
    return base.with_suffix(".jsonl"), base.with_suffix(".MANIFEST.json")


def state_path(root: Path) -> Path:
    return root / STATE_DIR / STATE_FILE


def lock_path(root: Path) -> Path:
    return root / STATE_DIR / LOCK_FILE


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Plan:
    """One day of one slice, and what may be done with it."""

    entry: Entry
    day: str
    action: str
    reason: str
    opens: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()
    unclosed: tuple[int, ...] = ()
    existing_sha256: str | None = None

    @property
    def captures(self) -> bool:
        return self.action == SHARD_CAPTURED


@dataclass
class PlanSummary:
    plans: list[Plan] = field(default_factory=list)

    def of(self, action: str) -> list[Plan]:
        return [plan for plan in self.plans if plan.action == action]

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for plan in self.plans:
            counts[plan.action] = counts.get(plan.action, 0) + 1
        return counts


def _index_for(entry: Entry, cache: dict[Path, SeriesIndex]) -> SeriesIndex:
    if entry.source not in cache:
        try:
            cache[entry.source] = index_series(entry.source, entry.asset, entry.interval)
        except StoreError as error:
            raise CaptureError(f"{entry.source} cannot be indexed: {error}") from error
    return cache[entry.source]


def _manifest_sha256(manifest_path: Path) -> str | None:
    document = _read_json(manifest_path)
    if not isinstance(document, dict):
        return None
    value = document.get("sha256")
    return str(value) if value else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def capture_plan(
    entries: tuple[Entry, ...] | list[Entry],
    *,
    at_ms: int,
    window_start_ms: int,
    window_end_ms: int,
) -> PlanSummary:
    """Decide, for every day of every slice, whether it may be captured now.

    Nothing is written here. The decision is made from three things and only three: the expected
    grid, the store's own bytes, and the clock. A day whose last expected bar has not closed is
    ``INCOMPLETE_DAY``; a day whose bars are not all in the store is ``NOT_DUE`` with the missing
    opens named; a day already captured is ``ALREADY_HELD`` or ``CONFLICT``, never overwritten.
    """
    summary = PlanSummary()
    cache: dict[Path, SeriesIndex] = {}
    for entry in entries:
        index = _index_for(entry, cache)
        present = {bar.open_ms: bar for bar in index.bars}
        for day in shard_days(entry.period_start_ms, entry.period_end_ms, entry.interval_ms):
            opens = tuple(
                open_ms
                for open_ms in day_opens(day, entry.interval_ms)
                if entry.period_start_ms <= open_ms < entry.period_end_ms
            )
            unclosed = tuple(
                open_ms
                for open_ms in opens
                if open_ms + entry.interval_ms > at_ms
                or (open_ms in present and not present[open_ms].closed)
            )
            if unclosed:
                # The day is not over yet. Publishing it now would create a shard that a later
                # capture must either extend — a rewrite — or abandon.
                summary.plans.append(
                    Plan(entry, day, SHARD_INCOMPLETE, "bars have not closed yet", opens, unclosed=unclosed)
                )
                continue
            missing = tuple(open_ms for open_ms in opens if open_ms not in present)
            data_path, manifest_path = shard_paths(entry, day)
            if manifest_path.is_file():
                held = _manifest_sha256(manifest_path)
                if data_path.is_file() and held == hashlib.sha256(data_path.read_bytes()).hexdigest():
                    summary.plans.append(
                        Plan(entry, day, SHARD_ALREADY_HELD, "already captured", opens, existing_sha256=held)
                    )
                else:
                    summary.plans.append(
                        Plan(entry, day, SHARD_CONFLICT, "manifest and payload disagree", opens)
                    )
                continue
            if data_path.is_file():
                # A payload without a manifest is an interrupted write, or a hand-placed file.
                # It is not evidence and it is not silently adopted: it is reported.
                summary.plans.append(
                    Plan(entry, day, SHARD_CONFLICT, "payload exists without a manifest", opens)
                )
                continue
            if missing:
                summary.plans.append(
                    Plan(entry, day, SHARD_NOT_DUE, f"{len(missing)} bar(s) not in the store", opens, missing=missing)
                )
                continue
            summary.plans.append(Plan(entry, day, SHARD_CAPTURED, "due", opens))
    return summary


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class WrittenShard:
    entry: Entry
    day: str
    data_path: Path
    manifest_path: Path
    manifest: dict[str, Any]


def _bar_payload(
    index: SeriesIndex, opens: tuple[int, ...]
) -> tuple[bytes, list[Bar], int]:
    """The store's own lines for the selected opens, byte for byte, in open order.

    The third value is the offset just past the last selected line: the exact prefix of the store
    that this shard was taken from. A later append leaves that prefix intact, which is what lets
    tomorrow's shard be added without invalidating today's attestation.
    """
    raw = index.path.read_bytes()
    positions = {bar.open_ms: position for position, bar in enumerate(index.bars)}
    missing = [open_ms for open_ms in opens if open_ms not in positions]
    if missing:
        raise CaptureError(f"{len(missing)} bar(s) are absent from {index.path.name}")
    chunks: list[bytes] = []
    bars: list[Bar] = []
    prefix_bytes = 0
    for open_ms in opens:
        position = positions[open_ms]
        start = index.byte_ends[position - 1] if position else 0
        chunk = raw[start : index.byte_ends[position]]
        if not chunks:
            chunk = chunk.lstrip(b"\r\n")
        if not chunk.endswith(b"\n"):
            chunk += b"\n"
        chunks.append(chunk)
        bars.append(index.bars[position])
        prefix_bytes = index.byte_ends[position]
    return b"".join(chunks), bars, prefix_bytes


def shard_defects(bars: list[Bar], *, at_ms: int, lag_bound_ms: int) -> list[dict[str, Any]]:
    """Every way a day's bars can fail the temporal policy, named individually.

    A day is admissible when no bar is future, none was stored before it closed, none was stored
    later than the bound allows, and all of them are closed. The list is returned rather than a
    boolean so that the manifest says *why* a day was quarantined.
    """
    defects: list[dict[str, Any]] = []
    for bar in bars:
        if bar.open_ms >= at_ms:
            defects.append(
                {"code": DEFECT_FUTURE, "open_utc": iso(bar.open_ms), "detail": "opens at or after the capture instant"}
            )
        if not bar.closed:
            defects.append(
                {"code": DEFECT_UNCLOSED, "open_utc": iso(bar.open_ms), "detail": "not closed at capture"}
            )
        if bar.lag_ms < 0:
            defects.append(
                {
                    "code": DEFECT_NEGATIVE_LAG,
                    "open_utc": iso(bar.open_ms),
                    "lag_ms": bar.lag_ms,
                    "detail": "stored before the bar closed; the timestamp cannot be what it claims",
                }
            )
        elif bar.lag_ms > lag_bound_ms:
            defects.append(
                {
                    "code": DEFECT_LATE,
                    "open_utc": iso(bar.open_ms),
                    "lag_ms": bar.lag_ms,
                    "bound_ms": lag_bound_ms,
                    "detail": "stored later than the declared lag bound; this is a backfilled bar",
                }
            )
    return defects


def write_shard(
    entry: Entry,
    plan: Plan,
    *,
    index: SeriesIndex,
    declaration: Declaration,
    at_ms: int,
    capture_id: str,
    prospective: bool,
    counts_toward_coverage: bool,
    generator: dict[str, Any],
) -> WrittenShard:
    """Write one shard atomically and return its manifest.

    Order matters and is the crash argument: the payload is written and fsynced to a temporary
    name, then the manifest, then the payload is renamed into place, then the manifest is renamed.
    A process that dies at any point leaves either nothing, a temporary file that
    :func:`recover_partials` names and removes, or a complete pair. It can never leave a shard
    whose manifest describes different bytes.
    """
    opens = plan.opens
    payload, bars, prefix_bytes = _bar_payload(index, opens)
    if [bar.open_ms for bar in bars] != list(opens):
        raise CaptureError(f"{plan.day}: the store's bar order is not the declared grid order")
    defects = shard_defects(bars, at_ms=at_ms, lag_bound_ms=entry.lag_bound_ms)
    lags = [bar.lag_ms for bar in bars]
    data_path, manifest_path = shard_paths(entry, plan.day)
    if manifest_path.exists() or data_path.exists():
        raise ShardConflict(f"{data_path} already exists; a shard is written once")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    raw = index.path.read_bytes()
    last_close = max(bar.close_ms for bar in bars)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "shard_id": f"{entry.label}@{plan.day}",
        "slice": entry.label,
        "dataset_id": entry.dataset_id,
        "asset": entry.asset,
        "interval": entry.interval,
        "day": plan.day,
        "declaration": {
            "path": relative(declaration.path),
            "declaration_id": declaration.declaration_id,
            "sha256": declaration.sha256,
            "effective_from_utc": iso(declaration.effective_from_ms),
        },
        "period": {
            "start_utc": iso(entry.period_start_ms),
            "end_utc": iso(entry.period_end_ms),
            "fencepost": "period_start_utc <= bar open < period_end_utc",
        },
        "opens": {
            "count": len(opens),
            "expected": len(opens),
            "first_utc": iso(bars[0].open_ms),
            "last_utc": iso(bars[-1].open_ms),
        },
        "row_count": len(bars),
        "bytes": len(payload),
        "sha256": _sha256(payload),
        "first_open_utc": iso(bars[0].open_ms),
        "last_open_utc": iso(bars[-1].open_ms),
        "last_close_utc": iso(last_close),
        "source": {
            "path": relative(index.path),
            "bars_in_source": len(index.bars),
            "total_bytes_at_read": index.total_bytes,
            "sha256_at_read": _sha256(raw),
            "prefix_bytes": prefix_bytes,
            "prefix_sha256": _sha256(raw[:prefix_bytes]),
        },
        "lag": {
            "bound_ms": entry.lag_bound_ms,
            "max_ms": max(lags),
            "min_ms": min(lags),
            "over_bound": sum(1 for defect in defects if defect["code"] == DEFECT_LATE),
            "negative": sum(1 for defect in defects if defect["code"] == DEFECT_NEGATIVE_LAG),
            "definition": str(declaration.lag_policy.get("definition") or ""),
        },
        "admissible": not defects,
        "defects": defects,
        "prospective": prospective,
        "counts_toward_coverage": counts_toward_coverage,
        "captured_at_utc": iso(at_ms),
        "day_closed_at_utc": iso(last_close),
        "capture": {"id": capture_id, "generator": generator},
        "note": (
            "Lines are the forward store's own bytes for this day, in open order. The manifest was "
            "written by the builder; it says what the builder did and not that the shard is right."
        ),
    }
    temporary = data_path.with_name(data_path.name + ".part")
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".part")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with temporary_manifest.open("wb") as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, data_path)
        os.replace(temporary_manifest, manifest_path)
    except BaseException:
        for leftover in (temporary, temporary_manifest):
            leftover.unlink(missing_ok=True)
        raise
    return WrittenShard(entry, plan.day, data_path, manifest_path, manifest)


def recover_partials(root: Path) -> list[str]:
    """Remove and name the temporary files an interrupted capture left behind.

    A ``*.part`` file was never renamed, so it was never a shard and no manifest ever described
    it. Removing it is not deleting evidence; leaving it would make the next plan see a conflict
    that never existed. What was removed is returned so the run report can say so.
    """
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for path in sorted(root.rglob("*.part")):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(relative(path))
    return removed


# --------------------------------------------------------------------------- #
# consolidation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SliceConsolidation:
    entry: Entry
    days: tuple[str, ...]
    shards: tuple[str, ...]
    quarantined: tuple[str, ...]
    rows: int
    declared_rows: int
    payload: bytes
    defects: tuple[dict[str, Any], ...]
    status: str

    @property
    def fraction(self) -> float:
        return self.rows / self.declared_rows if self.declared_rows else 0.0


@dataclass(frozen=True, slots=True)
class Consolidation:
    at_ms: int
    prospective: bool
    counts_toward_coverage: bool
    slices: tuple[SliceConsolidation, ...]
    declared_rows: int
    admissible_rows: int
    required_fraction: float
    status: str
    defects: tuple[dict[str, Any], ...]

    @property
    def fraction(self) -> float:
        return self.admissible_rows / self.declared_rows if self.declared_rows else 0.0


def coverage_status(
    *,
    admissible_rows: int,
    declared_rows: int,
    required_fraction: float,
    defects: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    at_ms: int,
    window_start_ms: int,
) -> str:
    """The one function that decides whether coverage may be called complete.

    Completeness is exact: every declared bar, admissible, with no defect anywhere. The declared
    ``coverage_required`` is a floor for adjudication, not a licence to certify a short dataset as
    the long one the declaration describes, so ``fraction >= required`` alone is ``BELOW_DECLARED``.
    """
    if at_ms < window_start_ms:
        return COVERAGE_PENDING_WINDOW_OPEN
    if defects:
        return COVERAGE_BELOW_DECLARED
    if declared_rows <= 0:
        return COVERAGE_PENDING
    if admissible_rows <= 0:
        return COVERAGE_PENDING
    if admissible_rows == declared_rows:
        return COVERAGE_COMPLETE
    if admissible_rows / declared_rows >= required_fraction:
        # Enough to adjudicate, not enough to certify: the word is the strict one.
        return COVERAGE_BELOW_DECLARED
    return COVERAGE_BELOW_DECLARED


def _load_shard(
    entry: Entry, day: str
) -> tuple[bytes, dict[str, Any], list[dict[str, Any]], list[tuple[int, bytes]]]:
    """Read one shard, checking its digest against its own manifest.

    A shard whose bytes no longer hash to what its manifest said is not evidence; it is reported
    as a defect and excluded. The function still returns the rows so that the report can name the
    offending instants, but the caller must not put them in a dataset.
    """
    data_path, manifest_path = shard_paths(entry, day)
    document = _read_json(manifest_path)
    if not isinstance(document, dict):
        return b"", {}, [{"code": DEFECT_SHARD_MANIFEST, "day": day, "detail": "manifest unreadable"}], []
    payload = data_path.read_bytes() if data_path.is_file() else b""
    defects: list[dict[str, Any]] = []
    if not payload:
        defects.append({"code": DEFECT_SHARD_MANIFEST, "day": day, "detail": "payload missing"})
    elif _sha256(payload) != document.get("sha256"):
        defects.append(
            {
                "code": DEFECT_SHARD_DIGEST,
                "day": day,
                "detail": f"payload hashes to {_sha256(payload)[:16]}, manifest says {str(document.get('sha256'))[:16]}",
            }
        )
    rows: list[tuple[int, bytes]] = []
    for line in payload.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
            open_ms = int(record["ts"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            defects.append(
                {"code": DEFECT_SHARD_MANIFEST, "day": day, "detail": "a row is not a bar record"}
            )
            continue
        rows.append((open_ms, line if line.endswith(b"\n") else line + b"\n"))
    return payload, document, defects, rows


def consolidate(
    entries: tuple[Entry, ...] | list[Entry],
    *,
    at_ms: int,
    prospective: bool,
    counts_toward_coverage: bool,
    window_start_ms: int,
) -> Consolidation:
    """Rebuild the dataset from the shards and say, in words, everything wrong with it.

    The output is a pure function of the shard bytes: no timestamp is written into the
    consolidated payload, the days are visited in order and the bars inside a day by open. Two
    consolidations of the same shards are therefore byte-identical, which is what makes the
    consolidated digest worth recording.
    """
    slices: list[SliceConsolidation] = []
    all_defects: list[dict[str, Any]] = []
    declared_total = 0
    admissible_total = 0
    required = 0.0
    for entry in entries:
        declared_total += entry.declared_rows
        required = max(required, entry.coverage_required)
        defects: list[dict[str, Any]] = []
        days = shard_days(entry.period_start_ms, entry.period_end_ms, entry.interval_ms)
        captured: list[str] = []
        quarantined: list[str] = []
        chunks: list[bytes] = []
        rows = 0
        seen: set[int] = set()
        for day in days:
            if not shard_paths(entry, day)[1].is_file():
                # A day that has fully elapsed and was never captured is a hole in the record.
                day_end = max(day_opens(day, entry.interval_ms)) + entry.interval_ms
                if day_end <= at_ms:
                    defects.append(
                        {
                            "code": DEFECT_MISSING_DAY,
                            "slice": entry.label,
                            "day": day,
                            "detail": "the day closed and no shard holds it",
                        }
                    )
                continue
            _, document, shard_defects_found, shard_rows = _load_shard(entry, day)
            defects.extend(shard_defects_found)
            if shard_defects_found:
                continue
            if document.get("admissible") is not True:
                quarantined.append(day)
                for defect in document.get("defects") or []:
                    defects.append({"code": defect.get("code"), "slice": entry.label, "day": day, **defect})
                continue
            if document.get("counts_toward_coverage") is True and not counts_toward_coverage:
                defects.append(
                    {
                        "code": DEFECT_REHEARSAL_IN_COVERAGE,
                        "slice": entry.label,
                        "day": day,
                        "detail": "a shard claims to count toward coverage inside a rehearsal",
                    }
                )
                continue
            expected = {
                open_ms
                for open_ms in day_opens(day, entry.interval_ms)
                if entry.period_start_ms <= open_ms < entry.period_end_ms
            }
            present = {open_ms for open_ms, _ in shard_rows}
            holes = sorted(expected - present)
            extra = sorted(present - expected)
            for open_ms in holes:
                defects.append(
                    {
                        "code": DEFECT_GAP,
                        "slice": entry.label,
                        "day": day,
                        "open_utc": iso(open_ms),
                        "detail": "expected bar absent from the shard",
                    }
                )
            for open_ms in extra:
                defects.append(
                    {
                        "code": DEFECT_ROW_NOT_IN_STORE if open_ms not in expected else DEFECT_DUPLICATE,
                        "slice": entry.label,
                        "day": day,
                        "open_utc": iso(open_ms),
                        "detail": "the shard holds a bar the declared grid does not contain",
                    }
                )
            for open_ms, line in sorted(shard_rows):
                if open_ms in seen:
                    defects.append(
                        {
                            "code": DEFECT_DUPLICATE,
                            "slice": entry.label,
                            "day": day,
                            "open_utc": iso(open_ms),
                            "detail": "the open instant already appears in an earlier day",
                        }
                    )
                    continue
                seen.add(open_ms)
                chunks.append(line)
                rows += 1
            captured.append(day)
        status = coverage_status(
            admissible_rows=rows,
            declared_rows=entry.declared_rows,
            required_fraction=entry.coverage_required,
            defects=defects,
            at_ms=at_ms,
            window_start_ms=window_start_ms,
        )
        admissible_total += rows
        all_defects.extend(defects)
        slices.append(
            SliceConsolidation(
                entry=entry,
                days=tuple(captured),
                shards=tuple(captured) + tuple(quarantined),
                quarantined=tuple(quarantined),
                rows=rows,
                declared_rows=entry.declared_rows,
                payload=b"".join(chunks),
                defects=tuple(defects),
                status=status,
            )
        )
    status = coverage_status(
        admissible_rows=admissible_total,
        declared_rows=declared_total,
        required_fraction=required,
        defects=all_defects,
        at_ms=at_ms,
        window_start_ms=window_start_ms,
    )
    return Consolidation(
        at_ms=at_ms,
        prospective=prospective,
        counts_toward_coverage=counts_toward_coverage,
        slices=tuple(slices),
        declared_rows=declared_total,
        admissible_rows=admissible_total,
        required_fraction=required,
        status=status,
        defects=tuple(all_defects),
    )


# --------------------------------------------------------------------------- #
# scheduler state
# --------------------------------------------------------------------------- #


def read_state(root: Path) -> dict[str, Any]:
    document = _read_json(state_path(root))
    return document if isinstance(document, dict) else {}


def write_state(root: Path, payload: dict[str, Any]) -> Path:
    """Write the scheduler's memory atomically. It is a watermark, not evidence."""
    target = state_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.write_bytes(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    os.replace(temporary, target)
    return target


def relative(path: Path) -> str:
    """A path as recorded in a manifest: repository-relative when it is inside the repository."""
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()
