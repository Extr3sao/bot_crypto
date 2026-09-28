"""DecisionTrace persistence and replay (§5, §17).

Storage is append-only JSONL, one file per run:

    reports/autonomous-paper/<run_id>/traces.jsonl
    reports/autonomous-paper/<run_id>/outcomes.jsonl

Every trace carries a hash chain (``prev_hash`` → ``trace_hash``) so a
tampered or truncated ledger is detectable. Replay reconstructs the decision
from the persisted record ONLY: it never re-reads market data, so it cannot
introduce future information into a past decision. The reconstruction also
re-checks the invariants that make a decision valid (PIT ordering, shadow
purity, proposal round-trip, outcome strictly after the decision).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    DecisionMode,
    DecisionTrace,
    OutcomeRecord,
    ReplayStatus,
    TradeProposal,
    VerificationCheck,
)

__all__ = [
    "ChainVerification",
    "DecisionTraceStore",
    "ReplayResult",
    "canonical_json",
    "trace_hash",
]

_GENESIS = "genesis"


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON used for hashing (sorted keys, no spaces)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def trace_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of the trace body with ``trace_hash`` removed."""
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    records: int
    broken_at: int | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "records": self.records,
            "broken_at": self.broken_at,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Result of replaying one persisted decision (no market-data access)."""

    decision_id: str
    run_id: str
    mode: DecisionMode
    reconstruction: dict[str, Any]
    checks: tuple[VerificationCheck, ...]
    outcome: OutcomeRecord | None = None

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def status(self) -> ReplayStatus:
        """Honest replay coverage (never claim FULL without the outcome)."""
        if not self.ok:
            return ReplayStatus.NOT_AVAILABLE
        return ReplayStatus.FULL if self.outcome is not None else ReplayStatus.PARTIAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "mode": self.mode.value,
            "ok": self.ok,
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
            "reconstruction": self.reconstruction,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
        }


class DecisionTraceStore:
    """Append-only, hash-chained decision ledger (+ outcomes) for one run."""

    def __init__(self, run_dir: Path | str) -> None:
        self._dir = Path(run_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._trace_path = self._dir / "traces.jsonl"
        self._outcome_path = self._dir / "outcomes.jsonl"
        self._sequence = 0
        self._prev_hash = _GENESIS
        self._load_tail()

    # -- paths --------------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        return self._dir

    @property
    def trace_path(self) -> Path:
        return self._trace_path

    @property
    def outcome_path(self) -> Path:
        return self._outcome_path

    def _load_tail(self) -> None:
        """Resume the chain from the existing file (append-safe)."""
        if not self._trace_path.exists():
            return
        last: dict[str, Any] | None = None
        for line in self._trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = json.loads(line)
        if last is not None:
            self._sequence = int(last.get("sequence", 0))
            self._prev_hash = str(last.get("trace_hash", _GENESIS))

    # -- writes -------------------------------------------------------------

    def append(self, trace: DecisionTrace) -> DecisionTrace:
        """Append one trace, sealing it into the chain."""
        raw = trace.to_dict()
        raw["sequence"] = self._sequence + 1
        raw["prev_hash"] = self._prev_hash
        raw["trace_hash"] = trace_hash(raw)
        sealed = DecisionTrace.from_dict(raw)
        with open(self._trace_path, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(raw) + "\n")
        self._sequence = int(raw["sequence"])
        self._prev_hash = str(raw["trace_hash"])
        return sealed

    def append_outcome(self, outcome: OutcomeRecord) -> OutcomeRecord:
        """Append one outcome, IDEMPOTENT on ``decision_id + horizon``.

        Reprocessing the same decision, horizon and market data must not create
        a second outcome: the stored record wins and is returned unchanged.
        """
        existing = {o.outcome_key: o for o in self.read_outcomes()}
        duplicate = existing.get(outcome.outcome_key)
        if duplicate is not None:
            return duplicate
        with open(self._outcome_path, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(outcome.to_dict()) + "\n")
        return outcome

    def outcome_keys(self) -> set[str]:
        """Stable identities (``decision_id@horizon``) already persisted."""
        return {o.outcome_key for o in self.read_outcomes()}

    def resolved_decision_ids(self) -> set[str]:
        """Decision ids that already have an outcome (never re-resolved)."""
        return {o.decision_id for o in self.read_outcomes()}

    # -- reads --------------------------------------------------------------

    def read(self) -> list[DecisionTrace]:
        if not self._trace_path.exists():
            return []
        traces: list[DecisionTrace] = []
        for line in self._trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                traces.append(DecisionTrace.from_dict(json.loads(line)))
        return traces

    def read_outcomes(self) -> list[OutcomeRecord]:
        if not self._outcome_path.exists():
            return []
        outcomes: list[OutcomeRecord] = []
        for line in self._outcome_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                outcomes.append(OutcomeRecord.from_dict(json.loads(line)))
        return outcomes

    def get(self, decision_id: str) -> DecisionTrace | None:
        return next((t for t in self.read() if t.decision_id == decision_id), None)

    def verify_chain(self) -> ChainVerification:
        """Recompute every hash and link; report the first break."""
        prev = _GENESIS
        count = 0
        for line in (
            self._trace_path.read_text(encoding="utf-8").splitlines()
            if self._trace_path.exists()
            else []
        ):
            if not line.strip():
                continue
            raw = json.loads(line)
            count += 1
            if raw.get("prev_hash") != prev:
                return ChainVerification(
                    ok=False,
                    records=count,
                    broken_at=int(raw.get("sequence", count)),
                    detail="prev_hash does not match the previous record",
                )
            if trace_hash(raw) != raw.get("trace_hash"):
                return ChainVerification(
                    ok=False,
                    records=count,
                    broken_at=int(raw.get("sequence", count)),
                    detail="trace_hash does not match the record body",
                )
            prev = str(raw["trace_hash"])
        return ChainVerification(ok=True, records=count, detail="hash chain intact")

    # -- replay -------------------------------------------------------------

    def replay(self, decision_id: str) -> ReplayResult:
        """Rebuild one decision from the persisted record alone (§17)."""
        trace = self.get(decision_id)
        if trace is None:
            raise KeyError(f"decision {decision_id!r} not found in {self._trace_path}")
        outcome = next((o for o in self.read_outcomes() if o.decision_id == decision_id), None)
        checks: list[VerificationCheck] = []

        checks.append(
            VerificationCheck(
                "pit_ordering",
                trace.decision_time_ms >= trace.market_time_ms,
                f"market_ts={trace.market_time_ms} decision_ts={trace.decision_time_ms}",
            )
        )
        checks.append(
            VerificationCheck(
                "trace_hash",
                trace_hash(trace.to_dict()) == trace.trace_hash,
                f"sequence={trace.sequence}",
            )
        )
        checks.append(
            VerificationCheck(
                "shadow_purity",
                not (trace.mode is DecisionMode.SHADOW_TRADE and trace.order_created),
                f"mode={trace.mode.value} orders={trace.orders_created}",
            )
        )
        proposal_ok = True
        if trace.proposal is not None:
            rebuilt = TradeProposal.from_dict(trace.proposal)
            proposal_ok = rebuilt.to_dict() == trace.proposal
        checks.append(
            VerificationCheck(
                "proposal_round_trip",
                proposal_ok,
                "proposal rebuilt from its persisted form" if trace.proposal else "no proposal",
            )
        )
        outcome_ok = True
        if outcome is not None:
            outcome_ok = outcome.outcome_time_ms > outcome.decision_time_ms
        checks.append(
            VerificationCheck(
                "outcome_after_decision",
                outcome_ok,
                "no outcome yet" if outcome is None else f"outcome_ts={outcome.outcome_time_ms}",
            )
        )

        reconstruction: dict[str, Any] = {
            "market_context": trace.market_context,
            "asset_context": trace.asset_context,
            "regime": trace.regime,
            "strategies_considered": [dict(s) for s in trace.strategies_considered],
            "candidate": None if trace.proposal is None else trace.proposal.get("strategy_id"),
            "timeframe": None if trace.proposal is None else trace.proposal.get("timeframe"),
            "proposal": trace.proposal,
            "cost_estimate": None if trace.proposal is None else trace.proposal.get("cost"),
            "agent_messages": [dict(m) for m in trace.agent_messages],
            "evidence": list(trace.evidence),
            "counter_evidence": list(trace.counter_evidence),
            "decision": {
                "mode": trace.mode.value,
                "reason": trace.reason,
                "classification": trace.classification,
                "no_trade_kind": trace.no_trade_kind,
            },
            "verification": trace.verification,
            "risk": trace.risk,
            "shadow": trace.shadow,
            "execution_mode": trace.mode.value,
            "order_created": trace.order_created,
            "cost_model_version": trace.cost_model_version,
            "outcome": None if outcome is None else outcome.to_dict(),
        }
        return ReplayResult(
            decision_id=decision_id,
            run_id=trace.run_id,
            mode=trace.mode,
            reconstruction=reconstruction,
            checks=tuple(checks),
            outcome=outcome,
        )
