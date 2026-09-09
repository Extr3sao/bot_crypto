"""Shadow candidate capture — for the NEXT campaign runtime (Track B).

SHADOW-AND-LEGACY-VALIDATION-01. Persist every verified candidate that
reaches Risk so that REJECTED candidates can be evaluated later without
affecting PAPER. Nothing in this module is imported by the active POC01
runtime; capture is an opt-in side-branch for a future campaign version.

Flow (future):

    TradeProposal -> Debate -> Decision -> Verifier -> Risk
        |-- ACCEPT  -> normal PAPER path
        `-- REJECT  -> ShadowCandidateCapture only

Invariants:

- Immutable records (frozen dataclasses, JSONL append-only).
- Deterministic ``shadow_candidate_id`` derived from economic identity
  (decision + strategy + asset + direction + timeframe + decision time);
  wall clock may appear in metadata, never in identity.
- Labels make exclusion explicit: ``SHADOW_ONLY``, ``COUNTERFACTUAL``,
  ``EXCLUDED_FROM_PAPER_PNL``, ``EXCLUDED_FROM_PAPER_FREQUENCY``.
- No PaperBroker / PortfolioStore / RiskManager / campaign accounting
  imports or calls anywhere in this package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "SHADOW_LABELS",
    "ShadowCandidateCapture",
    "ShadowCandidateLedger",
]

SHADOW_LABELS: tuple[str, ...] = (
    "SHADOW_ONLY",
    "COUNTERFACTUAL",
    "EXCLUDED_FROM_PAPER_PNL",
    "EXCLUDED_FROM_PAPER_FREQUENCY",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowCandidateCapture:
    """Immutable capture of one verified candidate REJECTED by risk.

    Field set per checkpoint B1. ``decision_time`` is PIT metadata: the
    capture may only ever be resolved against market data at or after this
    timestamp (enforced by the outcome engine).
    """

    decision_id: str
    trace_id: str
    run_id: str
    asset: str
    direction: str  # LONG | SHORT
    strategy_id: str
    strategy_version: str
    timeframe: str
    proposal_ref: str
    decision_ref: str
    verifier_ref: str
    decision_time: str  # ISO-8601 UTC, PIT anchor
    decision_price: float
    entry_reference: float
    stop_loss: float
    take_profit: float
    invalidation: str
    regime_signature: str
    strategy_health_state: str
    portfolio_context_ref: str
    correlation_state: str
    risk_verdict: str  # e.g. REJECT
    risk_rejection_reason: str
    market_data_fingerprint: str
    cost_model_sha256: str
    labels: tuple[str, ...] = field(default_factory=lambda: tuple(SHADOW_LABELS))

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError(f"direction must be LONG|SHORT, got {self.direction!r}")
        if self.labels != tuple(SHADOW_LABELS):
            raise ValueError("shadow captures must carry the canonical SHADOW label set")
        if self.risk_verdict.upper() != "REJECT":
            raise ValueError("ShadowCandidateCapture records risk REJECTs only")

    @property
    def shadow_candidate_id(self) -> str:
        """Deterministic economic identity — same candidate, same id."""
        canonical = json.dumps(
            {
                "decision_id": self.decision_id,
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "asset": self.asset,
                "direction": self.direction,
                "timeframe": self.timeframe,
                "decision_time": self.decision_time,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"shadow:{_sha256(canonical)[:24]}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "shadow_candidate_id": self.shadow_candidate_id,
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "asset": self.asset,
            "direction": self.direction,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "timeframe": self.timeframe,
            "refs": {
                "proposal": self.proposal_ref,
                "decision": self.decision_ref,
                "verifier": self.verifier_ref,
            },
            "decision_time": self.decision_time,
            "decision_price": self.decision_price,
            "plan": {
                "entry_reference": self.entry_reference,
                "stop_loss": self.stop_loss,
                "take_profit": self.take_profit,
                "invalidation": self.invalidation,
            },
            "context": {
                "regime_signature": self.regime_signature,
                "strategy_health_state": self.strategy_health_state,
                "portfolio_context_ref": self.portfolio_context_ref,
                "correlation_state": self.correlation_state,
            },
            "risk": {
                "verdict": self.risk_verdict,
                "rejection_reason": self.risk_rejection_reason,
            },
            "fingerprints": {
                "market_data": self.market_data_fingerprint,
                "cost_model_sha256": self.cost_model_sha256,
            },
            "labels": list(self.labels),
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ShadowCandidateCapture:
        return cls(
            decision_id=payload["decision_id"],
            trace_id=payload["trace_id"],
            run_id=payload["run_id"],
            asset=payload["asset"],
            direction=payload["direction"],
            strategy_id=payload["strategy_id"],
            strategy_version=payload["strategy_version"],
            timeframe=payload["timeframe"],
            proposal_ref=payload["refs"]["proposal"],
            decision_ref=payload["refs"]["decision"],
            verifier_ref=payload["refs"]["verifier"],
            decision_time=payload["decision_time"],
            decision_price=float(payload["decision_price"]),
            entry_reference=float(payload["plan"]["entry_reference"]),
            stop_loss=float(payload["plan"]["stop_loss"]),
            take_profit=float(payload["plan"]["take_profit"]),
            invalidation=payload["plan"]["invalidation"],
            regime_signature=payload["context"]["regime_signature"],
            strategy_health_state=payload["context"]["strategy_health_state"],
            portfolio_context_ref=payload["context"]["portfolio_context_ref"],
            correlation_state=payload["context"]["correlation_state"],
            risk_verdict=payload["risk"]["verdict"],
            risk_rejection_reason=payload["risk"]["rejection_reason"],
            market_data_fingerprint=payload["fingerprints"]["market_data"],
            cost_model_sha256=payload["fingerprints"]["cost_model_sha256"],
        )


class ShadowCandidateLedger:
    """Append-only JSONL ledger of shadow captures (durable, immutable)."""

    def __init__(self) -> None:
        self._captures: list[ShadowCandidateCapture] = []
        self._ids: set[str] = set()

    def __len__(self) -> int:
        return len(self._captures)

    @property
    def captures(self) -> tuple[ShadowCandidateCapture, ...]:
        return tuple(self._captures)

    def record(self, capture: ShadowCandidateCapture) -> str:
        cid = capture.shadow_candidate_id
        if cid in self._ids:
            raise ValueError(f"duplicate shadow candidate id: {cid}")
        self._ids.add(cid)
        self._captures.append(capture)
        return cid

    def by_reason(self) -> dict[str, list[ShadowCandidateCapture]]:
        grouped: dict[str, list[ShadowCandidateCapture]] = {}
        for capture in self._captures:
            grouped.setdefault(capture.risk_rejection_reason, []).append(capture)
        return grouped

    # -- durability ---------------------------------------------------------

    def to_jsonl(self) -> str:
        return "".join(
            json.dumps(c.to_dict(), separators=(",", ":")) + "\n" for c in self._captures
        )

    def save(self, path: Path | str) -> None:
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> ShadowCandidateLedger:
        ledger = cls()
        p = Path(path)
        if not p.exists():
            return ledger
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ledger.record(ShadowCandidateCapture.from_dict(json.loads(line)))
        return ledger
