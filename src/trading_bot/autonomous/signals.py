"""SignalEvent — the engine's decisions, made observable without inventing any (WP-SIGNAL-001).

The runtime already persists one `DecisionTrace` per asset per cycle, hash-chained,
with the proposal, the cost estimate, the risk review and the evidence. That file is
the authority. This module does **not** re-run a strategy, does not read market data
and does not decide anything: it *projects* the persisted decision into a signal
stream a human can watch, and refuses to emit a row it cannot ground in a trace.

Two consequences worth stating, because they are the difference between a signal
feed and a demo:

* **Every row points at the trace it came from** (`evidence_refs`), including the
  trace's `sequence` and `trace_hash`. A reader can walk back from the dashboard to
  the exact persisted decision and recompute the hash.
* **A row never claims a number it does not have.** When the decision held no
  proposal there is no gross edge and no cost, so those fields are `None` — never 0,
  which would read as "measured, and it was zero". `kind` separates the three states
  a naive feed conflates: `NO_ALPHA` (the strategies looked and found nothing),
  `NO_TRADE` (the engine decided not to trade), `OPERATIONAL_FAILURE` (a provider or
  a strategy broke — an incident, not a decision).

`source` is `REAL` only when the trace came from a run whose provider was live. The
`fake` provider produces a truthful stream too, marked `FAKE`, so a demo can never be
mistaken for a live signal.

Storage is append-only JSONL per run, `signals.jsonl`, idempotent on a deterministic
`signal_id`:

    signal_id = sha256(run_id | decision_id | strategy_id | stage | bar_close_ms | direction)[:32]

Restarting the runtime, replaying a cycle or projecting the same trace twice appends
nothing: the id is the identity. A projection that would produce the *same* id with a
*different* body is a conflict — recorded and not appended, because silently choosing
one of two disagreeing bodies is how a ledger starts lying.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "SIGNAL_SCHEMA_VERSION",
    "DataQuality",
    "SignalEvent",
    "SignalKind",
    "SignalLedger",
    "SignalPage",
    "SignalSource",
    "SignalStage",
    "project_trace",
    "signal_id_for",
]

SIGNAL_SCHEMA_VERSION = "signal-event-v1"
SIGNAL_FILE_NAME = "signals.jsonl"

#: Pagination is bounded at the API, not by the caller (§WP-SIGNAL-001).
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

#: Rows kept per generation and generations kept on disk. 20 000 rows is ~23 days of
#: three assets at one decision per 5m bar; older generations stay readable, and the
#: writer rotates instead of deleting, so the stream has a ceiling and no cliff.
DEFAULT_RETENTION_RECORDS = 20_000
DEFAULT_RETENTION_GENERATIONS = 3


class SignalStage(StrEnum):
    """Where the decision stopped (§WP-SIGNAL-001).

    CANDIDATE — a proposal existed and did not become an order;
    REJECTED  — the engine looked and produced no proposal at all;
    SHADOW    — a research observation: no order, ever;
    PAPER     — a paper order was actually created.
    """

    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"
    SHADOW = "SHADOW"
    PAPER = "PAPER"


class SignalKind(StrEnum):
    """What the row *is*, separately from where it stopped."""

    ALPHA = "ALPHA"
    NO_ALPHA = "NO_ALPHA"
    NO_TRADE = "NO_TRADE"
    OPERATIONAL_FAILURE = "OPERATIONAL_FAILURE"


class SignalSource(StrEnum):
    REAL = "REAL"
    FAKE = "FAKE"


class DataQuality(StrEnum):
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


class SignalLedgerError(RuntimeError):
    """A projection the ledger refuses to store."""


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _iso(ms: int | None) -> str | None:
    if not ms:
        return None
    seconds, millis = divmod(int(ms), 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}Z"


def signal_id_for(
    *,
    run_id: str,
    decision_id: str,
    strategy_id: str | None,
    stage: str,
    bar_close_ms: int | None,
    direction: str | None,
) -> str:
    """Deterministic identity: the same decision never yields two signal rows.

    The fields are the ones a re-projection could legitimately change only by
    describing a different event. `reason` is deliberately *not* part of the id: a
    wording change must not fork the stream, and if the body changes under a stable
    id the ledger reports a conflict instead of hiding it.
    """
    body = {
        "run_id": run_id,
        "decision_id": decision_id,
        "strategy_id": strategy_id or "",
        "stage": str(stage),
        "bar_close_ms": int(bar_close_ms or 0),
        "direction": (direction or "").upper(),
    }
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class SignalEvent:
    """One decision, as an auditable signal row."""

    signal_id: str
    run_id: str
    decision_id: str
    symbol: str
    venue: str | None
    timeframe: str | None
    strategy_id: str | None
    strategy_version: str | None
    bar_close_time_ms: int | None
    decision_time_ms: int
    direction: str | None
    stage: str
    kind: str
    reason: str
    gross_edge_bps: float | None
    estimated_cost_bps: float | None
    net_edge_bps: float | None
    risk_state: str | None
    data_quality: str
    source: str
    evidence_refs: tuple[dict[str, Any], ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()
    classification: str | None = None
    no_trade_kind: str | None = None
    errors: tuple[str, ...] = ()
    order_created: bool = False
    asset: str | None = None
    regime: str | None = None
    created_at_ms: int = 0
    schema_version: str = SIGNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.signal_id) != 32:
            raise ValueError("signal_id must be a 32-character digest")
        SignalStage(self.stage)
        SignalKind(self.kind)
        SignalSource(self.source)
        DataQuality(self.data_quality)
        if self.decision_time_ms <= 0:
            raise ValueError("a signal needs a decision time")
        # Data-time must never postdate the decision: that is look-ahead.
        if self.bar_close_time_ms is not None and self.bar_close_time_ms > self.decision_time_ms:
            raise ValueError(
                "point-in-time violation: bar close "
                f"{self.bar_close_time_ms} > decision {self.decision_time_ms}"
            )
        # A SHADOW row can never be an order, and a PAPER row must be one.
        if self.stage == SignalStage.SHADOW.value and self.order_created:
            raise ValueError("a SHADOW signal cannot have created an order")
        if self.stage == SignalStage.PAPER.value and not self.order_created:
            raise ValueError("a PAPER signal must have created an order")
        # Numbers require a strategy to belong to: an unowned edge is a fabrication.
        if self.strategy_id is None and any(
            value is not None
            for value in (self.gross_edge_bps, self.estimated_cost_bps, self.net_edge_bps)
        ):
            raise ValueError("edge/cost fields require a strategy_id")

    # -- serialization ------------------------------------------------------

    @property
    def bar_close_time_utc(self) -> str | None:
        return _iso(self.bar_close_time_ms)

    @property
    def decision_time_utc(self) -> str:
        assert _iso(self.decision_time_ms) is not None
        return str(_iso(self.decision_time_ms))

    @property
    def created_at_utc(self) -> str | None:
        return _iso(self.created_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "signal_id": self.signal_id,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "asset": self.asset,
            "symbol": self.symbol,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "bar_close_time_ms": self.bar_close_time_ms,
            "bar_close_time_utc": self.bar_close_time_utc,
            "decision_time_ms": self.decision_time_ms,
            "decision_time_utc": self.decision_time_utc,
            "direction": self.direction,
            "stage": self.stage,
            "kind": self.kind,
            "reason": self.reason,
            "gross_edge_bps": self.gross_edge_bps,
            "estimated_cost_bps": self.estimated_cost_bps,
            "net_edge_bps": self.net_edge_bps,
            "risk_state": self.risk_state,
            "data_quality": self.data_quality,
            "source": self.source,
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
            "candidates": [dict(row) for row in self.candidates],
            "classification": self.classification,
            "no_trade_kind": self.no_trade_kind,
            "errors": list(self.errors),
            "order_created": self.order_created,
            "regime": self.regime,
            "created_at_ms": self.created_at_ms,
            "created_at_utc": self.created_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SignalEvent:
        # Derived ISO forms and the ledger's own bookkeeping (``_sequence``) are
        # storage, not contract: a reader must be able to rebuild the event from
        # the row without knowing how the row was stored.
        data = {key: value for key, value in payload.items() if not key.startswith("_")}
        data.pop("schema_version", None)
        data.pop("bar_close_time_utc", None)
        data.pop("decision_time_utc", None)
        data.pop("created_at_utc", None)
        data["evidence_refs"] = tuple(data.get("evidence_refs") or ())
        data["candidates"] = tuple(data.get("candidates") or ())
        data["errors"] = tuple(data.get("errors") or ())
        return cls(**data)

    @property
    def content_hash(self) -> str:
        """The body a duplicate must agree with — projection time excluded.

        `created_at_ms` changes every time the same trace is projected again, so
        including it would turn every legitimate re-projection into a conflict.
        Everything that describes the *event* is included.
        """
        body = self.to_dict()
        for volatile in ("created_at_ms", "created_at_utc"):
            body.pop(volatile, None)
        return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# projection


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _strategy_version(proposal: dict[str, Any] | None) -> str | None:
    if not proposal:
        return None
    version = proposal.get("strategy_version")
    return None if version is None else str(version)


def _data_quality(
    trace: dict[str, Any], *, timeframe_ms: int | None
) -> DataQuality:
    """Judge the data the decision actually used, from the trace itself."""
    market_context = trace.get("market_context") or {}
    market_time_ms = market_context.get("market_time_ms")
    decision_time_ms = int(trace.get("decision_time_ms") or 0)
    if not market_time_ms:
        return DataQuality.MISSING
    lag_ms = decision_time_ms - int(market_time_ms)
    if lag_ms < 0:
        # The trace should never carry this; if it does, the row is not trustworthy.
        return DataQuality.UNVERIFIED
    if timeframe_ms and lag_ms > timeframe_ms:
        return DataQuality.STALE
    return DataQuality.OK


def _evidence_refs(trace: dict[str, Any], *, venue: str | None) -> tuple[dict[str, Any], ...]:
    """Every row points back at the exact persisted decision it came from."""
    refs: list[dict[str, Any]] = [
        {
            "kind": "decision_trace",
            "file": "traces.jsonl",
            "run_id": trace.get("run_id"),
            "decision_id": trace.get("decision_id"),
            "sequence": trace.get("sequence"),
            "trace_hash": trace.get("trace_hash"),
        }
    ]
    asset_context = trace.get("asset_context") or {}
    fingerprint = asset_context.get("data_fingerprint") or (
        trace.get("market_context") or {}
    ).get("data_fingerprint")
    if fingerprint:
        refs.append({"kind": "market_data", "data_fingerprint": str(fingerprint)})
    if venue:
        refs.append({"kind": "venue", "venue": venue})
    return tuple(refs)


def _candidate_rows(trace: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """The per-strategy consideration the trace already recorded (verbatim)."""
    rows: list[dict[str, Any]] = []
    for row in trace.get("strategies_considered") or ():
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "strategy_id": row.get("strategy_id"),
                "admission_status": row.get("admission_status"),
                "admitted_for_paper": row.get("admitted_for_paper"),
                "expected_gross_edge_bps": row.get("expected_gross_edge_bps"),
                "router_status": row.get("router_status"),
                "router_reason": row.get("router_reason"),
                "selected": bool(row.get("selected")),
            }
        )
    return tuple(rows)


def _kind_for(trace: dict[str, Any]) -> SignalKind:
    """Three states a naive feed conflates: no alpha, a decision, an incident.

    The vocabulary is the runtime's own (`classification` / `no_trade_kind` /
    `errors`), not a new one: an operational failure is a trace with errors and no
    NO_TRADE class, exactly as `run_cycle` counts it.
    """
    errors = trace.get("errors") or ()
    no_trade_kind = trace.get("no_trade_kind")
    classification = str(trace.get("classification") or "").upper()
    if errors and no_trade_kind is None:
        return SignalKind.OPERATIONAL_FAILURE
    if classification in {"NO_ALPHA", "UNKNOWN_STRATEGY"}:
        return SignalKind.NO_ALPHA
    if no_trade_kind is None:
        return SignalKind.OPERATIONAL_FAILURE
    return SignalKind.NO_TRADE


def project_trace(
    trace: Any,
    *,
    venue: str | None = None,
    timeframe: str | None = None,
    source: SignalSource | str = SignalSource.REAL,
    timeframe_ms: int | None = None,
    now_ms: int | None = None,
) -> SignalEvent:
    """Project one persisted `DecisionTrace` into exactly one signal row.

    `trace` is accepted as a `DecisionTrace` or as its persisted dict, because the
    verification path reads the JSONL directly and must not depend on the runtime's
    in-memory shape.
    """
    payload = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace)
    proposal = payload.get("proposal")
    strategy_id = None
    direction = None
    gross = cost = net = None
    strategy_version = _strategy_version(proposal)
    if proposal:
        strategy_id = None if proposal.get("strategy_id") is None else str(proposal["strategy_id"])
        direction = None if proposal.get("direction") is None else str(proposal["direction"])
        timeframe = timeframe or proposal.get("timeframe")
        gross = _float_or_none(proposal.get("expected_gross_edge_bps"))
        cost = _float_or_none(proposal.get("expected_cost_bps"))
        net = _float_or_none(proposal.get("expected_net_edge_bps"))
    else:
        selected = [row for row in payload.get("strategies_considered") or () if row.get("selected")]
        if len(selected) == 1:
            strategy_id = selected[0].get("strategy_id")

    mode = str(payload.get("mode") or "")
    order_created = bool(payload.get("order_created"))
    if mode == "TRADE_PAPER" and order_created:
        stage = SignalStage.PAPER
        kind = SignalKind.ALPHA
    elif mode == "SHADOW_TRADE":
        stage = SignalStage.SHADOW
        kind = SignalKind.ALPHA
    elif proposal is not None:
        stage = SignalStage.CANDIDATE
        kind = SignalKind.ALPHA
    else:
        stage = SignalStage.REJECTED
        kind = _kind_for(payload)

    decision_time_ms = int(payload.get("decision_time_ms") or 0)
    market_time_ms = (payload.get("market_context") or {}).get("market_time_ms")
    bar_close_ms = int(market_time_ms) if market_time_ms else None
    risk = payload.get("risk") or {}
    signal_id = signal_id_for(
        run_id=str(payload.get("run_id") or ""),
        decision_id=str(payload.get("decision_id") or ""),
        strategy_id=strategy_id,
        stage=stage.value,
        bar_close_ms=bar_close_ms,
        direction=direction,
    )
    return SignalEvent(
        signal_id=signal_id,
        run_id=str(payload.get("run_id") or ""),
        decision_id=str(payload.get("decision_id") or ""),
        asset=payload.get("asset"),
        symbol=str(payload.get("symbol") or ""),
        venue=venue,
        timeframe=timeframe,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        bar_close_time_ms=bar_close_ms,
        decision_time_ms=decision_time_ms,
        direction=direction,
        stage=stage.value,
        kind=kind.value,
        reason=str(payload.get("reason") or ""),
        gross_edge_bps=gross,
        estimated_cost_bps=cost,
        net_edge_bps=net,
        risk_state=None if not risk else risk.get("state"),
        data_quality=_data_quality(payload, timeframe_ms=timeframe_ms).value,
        source=SignalSource(source).value,
        evidence_refs=_evidence_refs(payload, venue=venue),
        candidates=_candidate_rows(payload),
        classification=payload.get("classification"),
        no_trade_kind=payload.get("no_trade_kind"),
        errors=tuple(payload.get("errors") or ()),
        order_created=order_created,
        regime=payload.get("regime"),
        created_at_ms=int(now_ms if now_ms is not None else time.time() * 1000),
    )


# --------------------------------------------------------------------------- #
# ledger


@dataclass(frozen=True, slots=True)
class SignalPage:
    events: tuple[SignalEvent, ...]
    limit: int
    total_matched: int
    next_cursor: int | None
    returned: int
    filters: dict[str, Any] = field(default_factory=dict)
    generated_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SIGNAL_SCHEMA_VERSION,
            "generated_at_ms": self.generated_at_ms,
            "generated_at_utc": _iso(self.generated_at_ms),
            "limit": self.limit,
            "returned": self.returned,
            "total_matched": self.total_matched,
            "next_cursor": self.next_cursor,
            "filters": self.filters,
            "events": [event.to_dict() for event in self.events],
        }


class SignalLedger:
    """Append-only, idempotent signal stream for one run directory."""

    def __init__(
        self,
        run_dir: Path | str,
        *,
        retention_records: int = DEFAULT_RETENTION_RECORDS,
        retention_generations: int = DEFAULT_RETENTION_GENERATIONS,
    ) -> None:
        self._dir = Path(run_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / SIGNAL_FILE_NAME
        self._retention_records = max(1, int(retention_records))
        self._retention_generations = max(1, int(retention_generations))
        self._ids: set[str] = set()
        self._hashes: dict[str, str] = {}
        self._sequence = 0
        self.appended = 0
        self.duplicates = 0
        self.conflicts: list[dict[str, Any]] = []
        self._load()

    # -- paths --------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def run_dir(self) -> Path:
        return self._dir

    def generation_path(self, index: int) -> Path:
        if index == 0:
            return self._path
        return self._dir / f"signals.{index}.jsonl"

    def generations(self) -> list[Path]:
        """Newest first: generation 0 is the live file."""
        out: list[Path] = []
        for index in range(self._retention_generations):
            path = self.generation_path(index)
            if path.exists():
                out.append(path)
        return out

    # -- loading ------------------------------------------------------------

    def _load(self) -> None:
        """Resume ids, hashes and the sequence from what is already on disk."""
        newest_first = self.generations()
        for path in reversed(newest_first):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    event = SignalEvent.from_dict(raw)
                except (ValueError, TypeError, KeyError):
                    # A damaged line is a finding for the verifier, never a crash
                    # that stops the stream.
                    continue
                self._ids.add(event.signal_id)
                self._hashes[event.signal_id] = event.content_hash
                self._sequence = max(self._sequence, int(raw.get("_sequence") or 0))

    def known_ids(self) -> set[str]:
        return set(self._ids)

    # -- writes -------------------------------------------------------------

    def append(self, event: SignalEvent, *, reason: str | None = None) -> bool:
        """Append one event. Returns True only when a row was actually written."""
        content = event.content_hash
        existing = self._hashes.get(event.signal_id)
        if existing is not None:
            self.duplicates += 1
            if existing != content:
                self.conflicts.append(
                    {
                        "signal_id": event.signal_id,
                        "decision_id": event.decision_id,
                        "existing_hash": existing,
                        "incoming_hash": content,
                        "detected_at_ms": int(time.time() * 1000),
                    }
                )
                raise SignalLedgerError(
                    f"signal_id {event.signal_id} already exists with a different body"
                )
            return False
        self._rotate_if_needed()
        self._sequence += 1
        row = {**event.to_dict(), "_sequence": self._sequence}
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(_canonical(row) + "\n")
        self._ids.add(event.signal_id)
        self._hashes[event.signal_id] = content
        self.appended += 1
        _ = reason
        return True

    def _rotate_if_needed(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "rb") as handle:
                lines = sum(1 for _ in handle)
        except OSError:
            return
        if lines < self._retention_records:
            return
        # Rotate, never delete: the newest generation moves down, the oldest is
        # dropped only when the declared budget of generations is spent.
        oldest = self.generation_path(self._retention_generations - 1)
        if oldest.exists():
            oldest.unlink()
        for index in range(self._retention_generations - 1, 0, -1):
            source = self.generation_path(index - 1)
            if source.exists():
                source.replace(self.generation_path(index))
        self._path.touch()

    def sync(
        self,
        traces: Iterable[Any],
        *,
        venue: str | None = None,
        timeframe: str | None = None,
        source: SignalSource | str = SignalSource.REAL,
        timeframe_ms: int | None = None,
        decision_ids: Sequence[str] | None = None,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        """Project traces into the stream, skipping ids already present.

        `decision_ids` narrows the projection to the decisions a cycle just made;
        without it the whole store is considered, which is what the runtime does on
        its first cycle after a restart so a crash cannot leave a hole.
        """
        wanted = None if decision_ids is None else set(decision_ids)
        appended = 0
        skipped = 0
        conflicts = 0
        for trace in traces:
            payload = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace)
            decision_id = str(payload.get("decision_id") or "")
            if wanted is not None and decision_id not in wanted:
                continue
            if not decision_id:
                continue
            event = project_trace(
                payload,
                venue=venue,
                timeframe=timeframe,
                source=source,
                timeframe_ms=timeframe_ms,
                now_ms=now_ms,
            )
            try:
                if self.append(event):
                    appended += 1
                else:
                    skipped += 1
            except SignalLedgerError:
                conflicts += 1
        return {
            "appended": appended,
            "skipped_duplicates": skipped,
            "conflicts": conflicts,
            "sequence": self._sequence,
        }

    # -- reads --------------------------------------------------------------

    def _raw_lines(self) -> Iterable[str]:
        """Every non-empty line, oldest generation first, including damaged ones.

        `iter_rows` skips a line it cannot parse so a reader never dies on a torn
        append; the verifier needs the opposite and reads the raw lines, because a
        malformed line that no one can see is a ledger that looks healthy.
        """
        for path in reversed(self.generations()):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield line

    def iter_rows(self) -> Iterable[dict[str, Any]]:
        """Every persisted row, oldest first, across the live generations."""
        for line in self._raw_lines():
            try:
                yield json.loads(line)
            except ValueError:
                continue

    def read(
        self,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: int | None = None,
        symbol: str | None = None,
        strategy: str | None = None,
        timeframe: str | None = None,
        stage: str | None = None,
        kind: str | None = None,
        since_ms: int | None = None,
    ) -> SignalPage:
        """Newest-first page, bounded, with a cursor that survives new arrivals.

        The cursor is the `_sequence` of the last row returned; the next page is
        every row with a strictly smaller sequence. Appending new rows therefore
        cannot make a page repeat or skip, which an offset cannot promise.
        """
        bounded = max(1, min(int(limit), MAX_PAGE_LIMIT))
        rows = list(self.iter_rows())
        matched: list[dict[str, Any]] = []
        for row in rows:
            if cursor is not None and int(row.get("_sequence") or 0) >= cursor:
                continue
            if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
                continue
            if strategy and row.get("strategy_id") != strategy:
                continue
            if timeframe and row.get("timeframe") != timeframe:
                continue
            if stage and str(row.get("stage") or "").upper() != stage.upper():
                continue
            if kind and str(row.get("kind") or "").upper() != kind.upper():
                continue
            if since_ms is not None and int(row.get("decision_time_ms") or 0) < since_ms:
                continue
            matched.append(row)
        matched.sort(key=lambda row: int(row.get("_sequence") or 0), reverse=True)
        page = matched[:bounded]
        next_cursor = int(page[-1].get("_sequence") or 0) if len(matched) > bounded else None
        events: list[SignalEvent] = []
        for row in page:
            try:
                events.append(SignalEvent.from_dict(row))
            except (ValueError, TypeError, KeyError):
                continue
        return SignalPage(
            events=tuple(events),
            limit=bounded,
            total_matched=len(matched),
            next_cursor=next_cursor,
            returned=len(events),
            filters={
                "symbol": symbol,
                "strategy": strategy,
                "timeframe": timeframe,
                "stage": stage,
                "kind": kind,
                "since_ms": since_ms,
                "cursor": cursor,
            },
            generated_at_ms=int(time.time() * 1000),
        )

    def verify(self) -> dict[str, Any]:
        """Independent structural check of the stream (used by the verifier)."""
        ids: dict[str, str] = {}
        duplicates: list[str] = []
        malformed = 0
        records = 0
        out_of_order: list[int] = []
        last_sequence = 0
        pit_violations: list[str] = []
        fabricated = 0
        shadow_orders = 0
        for line in self._raw_lines():
            records += 1
            try:
                row = json.loads(line)
                event = SignalEvent.from_dict(row)
            except (ValueError, TypeError, KeyError):
                malformed += 1
                continue
            if event.signal_id in ids:
                duplicates.append(event.signal_id)
            ids[event.signal_id] = event.content_hash
            sequence = int(row.get("_sequence") or 0)
            if sequence < last_sequence:
                out_of_order.append(sequence)
            last_sequence = max(last_sequence, sequence)
            if (
                event.bar_close_time_ms is not None
                and event.bar_close_time_ms > event.decision_time_ms
            ):
                pit_violations.append(event.signal_id)
            if event.strategy_id is None and any(
                value is not None
                for value in (event.gross_edge_bps, event.estimated_cost_bps, event.net_edge_bps)
            ):
                fabricated += 1
            if event.stage == SignalStage.SHADOW.value and event.order_created:
                shadow_orders += 1
        return {
            "ok": not duplicates and not malformed and not out_of_order
            and not pit_violations
            and not fabricated
            and not shadow_orders,
            "records": records,
            "unique_ids": len(ids),
            "duplicates": duplicates,
            "malformed": malformed,
            "out_of_order": out_of_order[:10],
            "pit_violations": pit_violations[:10],
            "fabricated_edges": fabricated,
            "shadow_orders": shadow_orders,
            "sequence_max": last_sequence,
            "generations": [str(path.name) for path in self.generations()],
            "retention": {
                "records_per_generation": self._retention_records,
                "generations": self._retention_generations,
            },
        }
