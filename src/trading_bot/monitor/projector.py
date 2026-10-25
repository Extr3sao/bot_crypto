"""Project persisted PAPER artifacts into normalised events — read-only.

Source of truth, in order:

1. ``<run_dir>/traces.jsonl`` — one hash-chained :class:`DecisionTrace` per decision;
2. ``<run_dir>/RUN_REPORT.json`` — ``executions[]`` (paper fills) and run metadata;
3. ``<run_dir>/PAPER_RUN.json`` — pid/mode/registry at startup (venue, timeframe);
4. ``<run_dir>/heartbeat.json`` — liveness of the producing process.

The projector **never imports the decision engine, the verifier, the risk manager
or the broker**. It reads files and maps fields. That is what makes REQ-TDM-001
(method parity) true by construction rather than by assertion.

Nothing here writes to a run directory.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, uuid5

from trading_bot.autonomous.contracts import DecisionMode, DecisionTrace
from trading_bot.autonomous.trace import trace_hash

from .contracts import (
    DecisionStatus,
    EventType,
    ReasonCode,
    TradingDecisionEventV1,
    iso_utc,
    reason_for,
)

__all__ = [
    "MAX_ARTIFACT_BYTES",
    "RunArtifacts",
    "RunProjection",
    "discover_runs",
    "load_run",
    "project_run",
]

#: A run artifact larger than this is refused rather than parsed (DoS guard).
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
#: Maximum events returned for one run in a single projection pass.
MAX_EVENTS_PER_RUN = 50_000

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_VENUE_RE = re.compile(r"^[a-zA-Z]+:(?P<venue>[A-Za-z0-9_]+)$")


class ArtifactError(RuntimeError):
    """An artifact is missing, oversized or unparsable."""


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ArtifactError(f"{path.name} exceeds {MAX_ARTIFACT_BYTES} bytes")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"{path.name} unreadable: {exc}") from exc
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True, slots=True)
class RawTraceRow:
    """One line of ``traces.jsonl`` plus the integrity verdict for it."""

    raw: dict[str, Any]
    trace: DecisionTrace | None
    chain_ok: bool
    error: str | None = None


@dataclass(slots=True)
class RunArtifacts:
    """Everything the monitor may read about one run — and nothing else."""

    run_id: str
    runtime_run_id: str
    run_dir: Path
    rows: tuple[RawTraceRow, ...]
    executions: tuple[dict[str, Any], ...]
    run_report: dict[str, Any] | None
    descriptor: dict[str, Any] | None
    heartbeat: dict[str, Any] | None
    chain: dict[str, Any]
    venue: str
    timeframe: str
    commit: str | None
    mode: str
    environment: str
    artifact_digests: dict[str, str] = field(default_factory=dict)

    @property
    def valid_traces(self) -> tuple[DecisionTrace, ...]:
        return tuple(r.trace for r in self.rows if r.trace is not None)


@dataclass(frozen=True, slots=True)
class RunProjection:
    """The projected stream for one run, plus the integrity facts behind it."""

    run_id: str
    events: tuple[TradingDecisionEventV1, ...]
    chain: dict[str, Any]
    invalid_records: int
    duplicate_decision_ids: tuple[str, ...]
    artifact_digests: dict[str, str]
    venue: str
    timeframe: str
    commit: str | None
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "chain": self.chain,
            "invalid_records": self.invalid_records,
            "duplicate_decision_ids": list(self.duplicate_decision_ids),
            "artifact_digests": dict(self.artifact_digests),
            "venue": self.venue,
            "timeframe": self.timeframe,
            "commit": self.commit,
            "mode": self.mode,
        }


# ---------------------------------------------------------------------------
# discovery & loading
# ---------------------------------------------------------------------------


def discover_runs(root: Path | str) -> list[Path]:
    """Every directory under *root* that contains a ``traces.jsonl``."""
    base = Path(root)
    if not base.exists():
        return []
    found = [
        child
        for child in base.iterdir()
        if child.is_dir() and (child / "traces.jsonl").exists()
    ]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _venue_from_environment(run_report: dict[str, Any] | None, descriptor: dict[str, Any] | None) -> str:
    """Venue comes from the run environment (``ccxt:binance``) — never invented."""
    for source in (run_report, descriptor):
        if not source:
            continue
        environment = str(source.get("environment") or "")
        match = _VENUE_RE.match(environment)
        if match:
            return match.group("venue").upper()
        provider = str(source.get("provider") or "")
        if provider and provider != "fake":
            return provider.upper()
    return "UNKNOWN"


def load_run(run_dir: Path | str) -> RunArtifacts:
    """Read one run directory. Never creates or mutates anything."""
    directory = Path(run_dir)
    if not directory.is_dir():
        raise ArtifactError(f"run directory not found: {directory}")
    trace_path = directory / "traces.jsonl"
    if not trace_path.exists():
        raise ArtifactError(f"missing traces.jsonl in {directory}")
    if trace_path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ArtifactError("traces.jsonl too large")

    run_report = _read_json(directory / "RUN_REPORT.json")
    descriptor = _read_json(directory / "PAPER_RUN.json")
    heartbeat = _read_json(directory / "heartbeat.json")

    rows: list[RawTraceRow] = []
    previous_hash = "genesis"
    chain_ok = True
    chain_broken_at: int | None = None
    chain_detail = "hash chain intact"
    for index, line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append(RawTraceRow({}, None, False, f"invalid json at line {index}: {exc}"))
            continue
        if not isinstance(raw, dict):
            rows.append(RawTraceRow({}, None, False, f"line {index} is not an object"))
            continue
        line_ok = True
        line_error: str | None = None
        if raw.get("prev_hash") != previous_hash:
            line_ok = False
            line_error = "prev_hash mismatch"
        elif trace_hash(raw) != raw.get("trace_hash"):
            line_ok = False
            line_error = "trace_hash mismatch"
        if not line_ok and chain_ok:
            chain_ok = False
            chain_broken_at = int(raw.get("sequence") or index)
            chain_detail = line_error or "chain broken"
        previous_hash = str(raw.get("trace_hash") or previous_hash)

        trace: DecisionTrace | None
        try:
            trace = DecisionTrace.from_dict(raw)
        except Exception as exc:  # a corrupt row must not kill the whole view
            trace = None
            line_error = f"{type(exc).__name__}: {exc}"
        rows.append(RawTraceRow(raw, trace, line_ok and trace is not None, line_error))

    executions: tuple[dict[str, Any], ...] = ()
    if run_report:
        raw_executions = run_report.get("executions") or []
        if isinstance(raw_executions, list):
            executions = tuple(e for e in raw_executions if isinstance(e, dict))

    # Identity: the *directory* is what every endpoint can address and what the
    # operator sees in the run root. The runtime's own run_id is kept next to it
    # so a disagreeing artifact is visible instead of silently renaming the run.
    runtime_run_id = str(
        (run_report or {}).get("run_id")
        or (descriptor or {}).get("run_id")
        or (rows[0].raw.get("run_id") if rows else None)
        or directory.name
    )
    run_id = directory.name
    timeframe = str(
        (run_report or {}).get("timeframe")
        or (descriptor or {}).get("timeframe")
        or _first_timeframe(rows)
        or "UNKNOWN"
    )
    digests = {
        name: digest
        for name in ("traces.jsonl", "RUN_REPORT.json", "PAPER_RUN.json", "heartbeat.json")
        if (digest := _sha256(directory / name)) is not None
    }
    return RunArtifacts(
        run_id=run_id,
        runtime_run_id=runtime_run_id,
        run_dir=directory,
        rows=tuple(rows),
        executions=executions,
        run_report=run_report,
        descriptor=descriptor,
        heartbeat=heartbeat,
        chain={
            "ok": chain_ok,
            "records": len(rows),
            "broken_at": chain_broken_at,
            "detail": chain_detail,
        },
        venue=_venue_from_environment(run_report, descriptor),
        timeframe=timeframe,
        commit=(run_report or {}).get("commit") or (descriptor or {}).get("commit"),
        mode=str((run_report or {}).get("mode") or (descriptor or {}).get("mode") or "PAPER"),
        environment=str((run_report or {}).get("environment") or ""),
        artifact_digests=digests,
    )


def _first_timeframe(rows: list[RawTraceRow]) -> str | None:
    for row in rows:
        proposal = row.raw.get("proposal")
        if isinstance(proposal, dict) and proposal.get("timeframe"):
            return str(proposal["timeframe"])
    return None


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------


def _event_id(run_id: str, decision_id: str, kind: str, discriminator: str = "") -> str:
    """Deterministic, re-projection-stable uuid5 (dedupe across reconnects)."""
    key = f"tdm://{run_id}/{decision_id}/{kind}/{discriminator}"
    return str(uuid5(NAMESPACE_URL, key))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _risk_reasons(risk: dict[str, Any]) -> list[ReasonCode]:
    reasons: list[ReasonCode] = []
    verdict = str(risk.get("verdict") or "NOT_APPLICABLE").upper()
    evaluated = bool(risk.get("risk_evaluated"))
    advisory = bool(risk.get("advisory"))
    # ``RiskReview.to_dict`` names the field ``risk_rule``; accept both so the
    # projector cannot silently lose the rule when a contract is renamed.
    rule = risk.get("risk_rule") or risk.get("rule")
    if not evaluated:
        reasons.append(reason_for("RISK_NOT_EVALUATED", evidence_ref="trace.risk.risk_evaluated"))
    elif verdict == "VETO":
        reasons.append(
            reason_for(
                "RISK_VETO",
                threshold=None,
                evidence_ref=f"trace.risk.risk_rule={rule or 'risk_check'}",
                component="risk_engine",
            )
        )
    elif advisory:
        reasons.append(
            reason_for("RISK_ADVISORY_PASS", evidence_ref=f"trace.risk.risk_rule={rule or 'risk'}")
        )
    else:
        reasons.append(
            reason_for("RISK_BINDING_PASS", evidence_ref=f"trace.risk.risk_rule={rule or 'risk'}")
        )
    return reasons


def _verification_reasons(verification: dict[str, Any]) -> list[ReasonCode]:
    verdict = str(verification.get("verdict") or "NOT_RUN").upper()
    failures = tuple(str(f) for f in (verification.get("failures") or ()))
    if verdict == "NOT_RUN":
        return [reason_for("VERIFIER_NOT_RUN", evidence_ref="trace.verification.verdict")]
    if failures:
        return [
            reason_for(
                "VERIFIER_FAIL",
                evidence_ref="trace.verification.failures",
                counter_evidence=failures[:8],
            )
        ]
    return []


def _classification_reasons(
    trace: DecisionTrace, proposal: dict[str, Any] | None
) -> list[ReasonCode]:
    classification = trace.classification
    gross = _number((proposal or {}).get("expected_gross_edge_bps"))
    net = _number((proposal or {}).get("expected_net_edge_bps"))
    cost = _number((proposal or {}).get("expected_cost_bps"))
    reasons: list[ReasonCode] = []
    if classification == "NO_GROSS_EDGE":
        reasons.append(
            reason_for(
                "NO_GROSS_EDGE",
                measured_value=gross,
                threshold=0.0,
                unit="bps",
                evidence_ref="trace.proposal.expected_gross_edge_bps",
            )
        )
    elif classification in {"COST_KILLED", "PAPER_ADMITTED", "NOT_ADMITTED"}:
        reasons.append(
            reason_for(
                classification,
                measured_value=net,
                threshold=0.0,
                unit="bps",
                evidence_ref="trace.proposal.expected_net_edge_bps",
            )
        )
        if cost is not None and gross is not None:
            reasons.append(
                reason_for(
                    "COST_EXCEEDS_GROSS",
                    measured_value=cost,
                    threshold=gross,
                    unit="bps",
                    evidence_ref="trace.proposal.expected_cost_bps",
                    severity="INFO",
                )
            )
    elif classification == "AGENT_VETO":
        vetoes = tuple(
            str(m.get("agent_id"))
            for m in trace.agent_messages
            if str(m.get("review_type")).upper() == "VETO"
        )
        reasons.append(
            reason_for(
                "AGENT_VETO",
                dissenting_agents=vetoes,
                evidence_ref="trace.agent_messages[review_type=VETO]",
            )
        )
    elif (
        classification == "RISK_VETO"
        and trace.risk.get("risk_evaluated")
        and str(trace.risk.get("verdict") or "").upper() == "VETO"
    ):
        pass  # attributed by ``_risk_reasons`` with the rule that fired
    elif classification == "VERIFIER_FAIL" and (trace.verification.get("failures") or ()):
        pass  # attributed by ``_verification_reasons`` with the failed checks
    else:
        reasons.append(reason_for(classification, evidence_ref="trace.classification"))
    return reasons


def _summary_for(
    *,
    status: DecisionStatus,
    trace: DecisionTrace,
    execution: dict[str, Any] | None,
) -> str:
    base = f"{trace.classification}: {trace.reason}"
    if status is DecisionStatus.NO_TRADE:
        return f"NO_TRADE · {base}"
    if status is DecisionStatus.SHADOW_OBSERVED:
        return f"SHADOW sin ejecución · {base}"
    if status is DecisionStatus.ACCEPTED_NOT_EXECUTED:
        return f"Aceptada para ejecución · {base}"
    if status is DecisionStatus.EXECUTED_PAPER:
        notional = execution.get("notional_usdt") if execution else None
        suffix = f" · {notional} USDT" if notional is not None else ""
        return f"Ejecutada en PAPER{suffix} · {base}"
    if status is DecisionStatus.EXECUTION_FAILED:
        return f"Aceptada, ejecución fallida · {base}"
    return base


def _decision_status_for(
    trace: DecisionTrace, execution: dict[str, Any] | None
) -> DecisionStatus:
    if trace.mode is DecisionMode.NO_TRADE:
        return DecisionStatus.NO_TRADE
    if trace.mode is DecisionMode.SHADOW_TRADE:
        return DecisionStatus.SHADOW_OBSERVED
    # TRADE_PAPER
    if execution is not None:
        return DecisionStatus.EXECUTED_PAPER
    if trace.errors:
        return DecisionStatus.EXECUTION_FAILED
    return DecisionStatus.ACCEPTED_NOT_EXECUTED


class _EventCommon(TypedDict):
    """Fields every event of one trace shares (excluding the per-event strategy)."""

    run_id: str
    sequence: int
    symbol: str
    timeframe: str
    mode: str
    venue: str
    signal_direction: str | None
    source_commit: str | None
    source_sequence: int
    trace_hash: str | None
    verification: str
    risk_gate: str
    confidence: float | None
    observed_market_time: str | None
    observed_market_time_ms: int | None
    decision_time: str
    decision_time_ms: int
    emitted_at: str
    evidence_refs: tuple[str, ...]


def _price_from(trace: DecisionTrace) -> tuple[float | None, str]:
    proposal = trace.proposal or {}
    entry = _number(proposal.get("entry_reference"))
    if entry is not None:
        return entry, "PROPOSAL_ENTRY_REFERENCE"
    last = _number(trace.market_context.get("last_price"))
    if last is not None:
        return last, "MARKET_CONTEXT_LAST_PRICE"
    return None, "NOT_RECORDED"


def project_run(artifacts: RunArtifacts) -> RunProjection:
    """Map one run's artifacts onto the normalised event stream."""
    executions_by_decision: dict[str, dict[str, Any]] = {}
    for execution_row in artifacts.executions:
        decision_id = str(execution_row.get("decision_id") or "")
        if decision_id:
            executions_by_decision.setdefault(decision_id, execution_row)

    seen_decision_ids: dict[str, int] = {}
    duplicates: list[str] = []
    staged: list[tuple[int, int, int, TradingDecisionEventV1]] = []
    invalid = 0

    for row_index, row in enumerate(artifacts.rows):
        trace = row.trace
        # A row whose hash does not verify is not evidence, even when it parses:
        # it is reported as a pipeline defect instead of being projected.
        if trace is None or not row.chain_ok:
            invalid += 1
            raw = row.raw
            row_error = str(row.error or "record failed integrity validation")[:180]
            decision_id = str(raw.get("decision_id") or f"invalid-{row_index + 1}")
            decision_ms = int(raw.get("decision_time_ms") or raw.get("created_at_ms") or 0)
            staged.append(
                (
                    decision_ms,
                    int(raw.get("sequence") or row_index + 1),
                    99,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, decision_id, "invalid", str(row_index)),
                        run_id=artifacts.run_id,
                        sequence=1,  # assigned below
                        decision_id=decision_id,
                        event_type=EventType.PIPELINE_ERROR,
                        decision_status=DecisionStatus.UNDECIDED,
                        symbol=str(raw.get("symbol") or "UNKNOWN"),
                        timeframe=str((raw.get("proposal") or {}).get("timeframe") or artifacts.timeframe),
                        mode=str(raw.get("mode") or artifacts.mode),
                        observed_market_time=iso_utc(raw.get("market_time_ms")),
                        # the row is not evidence: never assert its timestamps
                        observed_market_time_ms=None,
                        decision_time=iso_utc(decision_ms) or "",
                        decision_time_ms=decision_ms,
                        emitted_at=iso_utc(decision_ms) or "",
                        reason_codes=(
                            ReasonCode(
                                code="TRACE_RECORD_INVALID",
                                short_text="El registro de traza no supera la validación del contrato.",
                                component="monitor",
                                severity="ERROR",
                                evidence_ref=row_error,
                            ),
                        ),
                        reason_summary=f"Registro inválido en traces.jsonl: {row_error}",
                        source_component="monitor",
                        source_commit=artifacts.commit,
                        severity="ERROR",
                        extra={"trace_row_error": row_error},
                    ),
                )
            )
            continue

        seen_decision_ids[trace.decision_id] = seen_decision_ids.get(trace.decision_id, 0) + 1
        if seen_decision_ids[trace.decision_id] == 2:
            duplicates.append(trace.decision_id)

        # -- point-in-time guard, independent of the runtime's own check ----
        if trace.market_time_ms > trace.decision_time_ms:
            invalid += 1
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    0,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "pit"),
                        run_id=artifacts.run_id,
                        sequence=1,
                        decision_id=trace.decision_id,
                        event_type=EventType.SYSTEM_DATA_STALE,
                        decision_status=DecisionStatus.UNDECIDED,
                        symbol=trace.symbol,
                        timeframe=artifacts.timeframe,
                        mode=trace.mode.value,
                        observed_market_time=iso_utc(trace.market_time_ms),
                        observed_market_time_ms=None,  # invalid by definition
                        decision_time=iso_utc(trace.decision_time_ms) or "",
                        decision_time_ms=trace.decision_time_ms,
                        emitted_at=iso_utc(trace.created_at_ms) or "",
                        reason_codes=(
                            reason_for(
                                "INVALID_TEMPORAL_EVIDENCE",
                                evidence_ref="trace.market_time_ms",
                                component="monitor",
                            ),
                        ),
                        reason_summary=(
                            "Evidencia temporal inválida: mercado observado después de la decisión."
                        ),
                        source_component="monitor",
                        source_commit=artifacts.commit,
                        severity="CRITICAL",
                    ),
                )
            )
            continue

        proposal = trace.proposal or {}
        strategy_id = proposal.get("strategy_id") or next(
            (str(r.get("strategy_id")) for r in trace.strategies_considered if r.get("selected")),
            None,
        )
        direction = proposal.get("direction")
        # Typed, so the checker validates every ``**common`` expansion instead of
        # accepting an untyped mapping. ``strategy_id`` is passed per event because
        # a signal row may name a different strategy than the routed decision.
        common: _EventCommon = {
            "run_id": artifacts.run_id,
            "sequence": 1,  # replaced by the stream position after ordering
            "symbol": trace.symbol,
            "timeframe": str(proposal.get("timeframe") or artifacts.timeframe),
            "mode": trace.mode.value,
            "venue": artifacts.venue,
            "signal_direction": direction,
            "source_commit": artifacts.commit,
            "source_sequence": trace.sequence,
            "trace_hash": trace.trace_hash,
            "verification": str(trace.verification.get("verdict") or "NOT_RUN"),
            "risk_gate": _risk_gate(trace.risk),
            "confidence": _number(proposal.get("confidence")),
            "observed_market_time": iso_utc(trace.market_time_ms),
            "observed_market_time_ms": trace.market_time_ms,
            "decision_time": iso_utc(trace.decision_time_ms) or "",
            "decision_time_ms": trace.decision_time_ms,
            "emitted_at": iso_utc(trace.created_at_ms) or "",
            "evidence_refs": (
                f"evidence://runs/{artifacts.run_id}/{trace.decision_id}",
                *trace.evidence,
            ),
        }

        # 1) signals — only for strategy rows that really reported emitted_alpha
        for signal_index, considered in enumerate(trace.strategies_considered):
            if not considered.get("emitted_alpha"):
                continue
            row_strategy = str(considered.get("strategy_id") or "UNKNOWN")
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    1 + signal_index,
                    TradingDecisionEventV1(
                        event_id=_event_id(
                            artifacts.run_id, trace.decision_id, "signal", row_strategy
                        ),
                        decision_id=trace.decision_id,
                        event_type=EventType.SIGNAL_DETECTED,
                        decision_status=DecisionStatus.SIGNAL_ONLY,
                        reason_codes=(
                            ReasonCode(
                                code="STRATEGY_EMITTED_ALPHA",
                                short_text="La familia emitió una señal alpha evaluable.",
                                component="strategy_router",
                                severity="INFO",
                                measured_value=_number(considered.get("expected_gross_edge_bps")),
                                unit="bps",
                                evidence_ref=(
                                    "trace.strategies_considered"
                                    f"[strategy_id={row_strategy}].emitted_alpha"
                                ),
                            ),
                        ),
                        reason_summary=(
                            f"Señal de {row_strategy}"
                            f" ({considered.get('router_status') or 'ROUTED'})"
                        ),
                        source_component="strategy_router",
                        price_observed=_number(trace.market_context.get("last_price")),
                        price_source="MARKET_CONTEXT_LAST_PRICE",
                        **common,
                        strategy_id=row_strategy,
                    ),
                )
            )

        # 2) proposal
        if trace.proposal is not None:
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    40,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "proposal"),
                        decision_id=trace.decision_id,
                        event_type=EventType.PROPOSAL_CREATED,
                        decision_status=DecisionStatus.SIGNAL_ONLY,
                        reason_codes=(
                            ReasonCode(
                                code="PROPOSAL_FROM_ROUTER",
                                short_text=(
                                    "El router construyó una propuesta con borde y coste estimados."
                                ),
                                component="runtime",
                                severity="INFO",
                                measured_value=_number(proposal.get("expected_gross_edge_bps")),
                                unit="bps",
                                evidence_ref="trace.proposal",
                            ),
                        ),
                        reason_summary=(
                            f"Propuesta {proposal.get('direction')} "
                            f"gross={proposal.get('expected_gross_edge_bps')}bps "
                            f"cost={proposal.get('expected_cost_bps')}bps"
                        ),
                        proposal_id=f"prop:{trace.decision_id}",
                        source_component="runtime",
                        price_observed=_number(proposal.get("entry_reference")),
                        price_source="PROPOSAL_ENTRY_REFERENCE",
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )

        # 3) decision / execution
        execution = executions_by_decision.get(trace.decision_id)
        status = _decision_status_for(trace, execution)
        price, price_source = _price_from(trace)
        classification_reasons = _classification_reasons(trace, trace.proposal)
        risk_reasons = _risk_reasons(trace.risk)
        verification_reasons = _verification_reasons(trace.verification)
        base_reasons = (*classification_reasons, *verification_reasons, *risk_reasons)

        if status is DecisionStatus.EXECUTED_PAPER:
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    45,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "accepted"),
                        decision_id=trace.decision_id,
                        event_type=EventType.DECISION_ACCEPTED,
                        decision_status=DecisionStatus.ACCEPTED_NOT_EXECUTED,
                        reason_codes=(
                            *base_reasons,
                            reason_for(
                                "ORDER_SUBMITTED_NOT_RECORDED",
                                evidence_ref="runtime._execute_paper",
                            ),
                        ),
                        reason_summary=_summary_for(
                            status=DecisionStatus.ACCEPTED_NOT_EXECUTED,
                            trace=trace,
                            execution=None,
                        ),
                        proposal_id=f"prop:{trace.decision_id}",
                        source_component="decision_engine",
                        price_observed=price,
                        price_source=price_source,
                        severity="INFO",
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )
            staged.append(
                (
                    trace.created_at_ms,
                    trace.sequence,
                    70,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "fill"),
                        decision_id=trace.decision_id,
                        event_type=EventType.ORDER_FILLED,
                        decision_status=DecisionStatus.EXECUTED_PAPER,
                        reason_codes=(
                            reason_for(
                                "PAPER_FILL",
                                evidence_ref="RUN_REPORT.json.executions",
                                component="paper_broker",
                            ),
                            reason_for(
                                "FILL_PRICE_NOT_RECORDED",
                                evidence_ref="RUN_REPORT.json.executions (no price field)",
                            ),
                        ),
                        reason_summary=_summary_for(
                            status=DecisionStatus.EXECUTED_PAPER,
                            trace=trace,
                            execution=execution,
                        ),
                        proposal_id=f"prop:{trace.decision_id}",
                        source_component="paper_broker",
                        price_observed=price,
                        price_source=price_source,
                        extra={
                            "cloid": (execution or {}).get("cloid"),
                            "notional_usdt": (execution or {}).get("notional_usdt"),
                            "fill_price": None,
                        },
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )
        elif status is DecisionStatus.EXECUTION_FAILED:
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    45,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "accepted"),
                        decision_id=trace.decision_id,
                        event_type=EventType.DECISION_ACCEPTED,
                        decision_status=DecisionStatus.ACCEPTED_NOT_EXECUTED,
                        reason_codes=base_reasons,
                        reason_summary=_summary_for(
                            status=DecisionStatus.ACCEPTED_NOT_EXECUTED,
                            trace=trace,
                            execution=None,
                        ),
                        proposal_id=f"prop:{trace.decision_id}",
                        source_component="decision_engine",
                        price_observed=price,
                        price_source=price_source,
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )
            staged.append(
                (
                    trace.created_at_ms,
                    trace.sequence,
                    72,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "rejected"),
                        decision_id=trace.decision_id,
                        event_type=EventType.ORDER_REJECTED,
                        decision_status=DecisionStatus.EXECUTION_FAILED,
                        reason_codes=(
                            reason_for(
                                "RUNTIME_ERROR",
                                evidence_ref="trace.errors",
                                severity="ERROR",
                            ),
                        ),
                        reason_summary=f"Aceptada, ejecución fallida: {'; '.join(trace.errors)[:200]}",
                        proposal_id=f"prop:{trace.decision_id}",
                        source_component="paper_broker",
                        price_observed=price,
                        price_source=price_source,
                        severity="ERROR",
                        extra={"errors": list(trace.errors)},
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )
        else:
            event_type = (
                EventType.DECISION_ACCEPTED
                if status is DecisionStatus.ACCEPTED_NOT_EXECUTED
                else EventType.DECISION_REJECTED
            )
            reasons = list(base_reasons)
            if not reasons:
                reasons.append(
                    reason_for("REASON_UNAVAILABLE", evidence_ref="trace.classification")
                )
            staged.append(
                (
                    trace.decision_time_ms,
                    trace.sequence,
                    50,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "decision"),
                        decision_id=trace.decision_id,
                        event_type=event_type,
                        decision_status=status,
                        reason_codes=tuple(reasons),
                        reason_summary=_summary_for(status=status, trace=trace, execution=None),
                        proposal_id=(
                            f"prop:{trace.decision_id}" if trace.proposal is not None else None
                        ),
                        source_component=(
                            "risk_engine"
                            if trace.classification == "RISK_VETO"
                            else "decision_engine"
                        ),
                        price_observed=price,
                        price_source=price_source,
                        severity=(
                            "WARN"
                            if trace.classification in {"RISK_VETO", "VERIFIER_FAIL", "AGENT_VETO"}
                            else "INFO"
                        ),
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )

        # 4) runtime errors are always surfaced, whatever the decision was
        if trace.errors and status is not DecisionStatus.EXECUTION_FAILED:
            staged.append(
                (
                    trace.created_at_ms,
                    trace.sequence,
                    90,
                    TradingDecisionEventV1(
                        event_id=_event_id(artifacts.run_id, trace.decision_id, "error"),
                        decision_id=trace.decision_id,
                        event_type=EventType.PIPELINE_ERROR,
                        decision_status=status,
                        reason_codes=(
                            reason_for("RUNTIME_ERROR", evidence_ref="trace.errors", severity="ERROR"),
                        ),
                        reason_summary=f"Errores del ciclo: {'; '.join(trace.errors)[:200]}",
                        source_component="runtime",
                        severity="ERROR",
                        price_observed=price,
                        price_source=price_source,
                        extra={"errors": list(trace.errors)},
                        **common,
                        strategy_id=strategy_id,
                    ),
                )
            )

    # deterministic ordering: decision time, trace sequence, intra-trace order
    staged.sort(key=lambda item: (item[0], item[1], item[2]))
    if len(staged) > MAX_EVENTS_PER_RUN:
        raise ArtifactError(f"projection exceeds {MAX_EVENTS_PER_RUN} events")

    events: list[TradingDecisionEventV1] = []
    for index, (_, _, _, event) in enumerate(staged, start=1):
        events.append(_with_sequence(event, index))

    return RunProjection(
        run_id=artifacts.run_id,
        events=tuple(events),
        chain=artifacts.chain,
        invalid_records=invalid,
        duplicate_decision_ids=tuple(sorted(set(duplicates))),
        artifact_digests=artifacts.artifact_digests,
        venue=artifacts.venue,
        timeframe=artifacts.timeframe,
        commit=artifacts.commit,
        mode=artifacts.mode,
    )


def _risk_gate(risk: dict[str, Any]) -> str:
    if not risk.get("risk_evaluated"):
        return "NOT_EVALUATED"
    verdict = str(risk.get("verdict") or "NOT_APPLICABLE").upper()
    if verdict == "VETO":
        return "VETO"
    if verdict in {"PASS", "ADJUST"}:
        return "ADVISORY_PASS" if risk.get("advisory") else "PASS"
    return verdict or "UNKNOWN"


def _with_sequence(event: TradingDecisionEventV1, sequence: int) -> TradingDecisionEventV1:
    """Re-seal an event with its stream sequence (dataclass is frozen)."""
    payload = event.to_dict()
    payload["sequence"] = sequence
    return TradingDecisionEventV1.from_dict(payload)
