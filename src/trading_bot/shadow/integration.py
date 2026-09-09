"""Shadow Campaign V2 integration hook (Track D — preparation only).

POC01-RECOVERY-AND-EVIDENCE-01. The NEXT campaign runtime will call
:class:`ShadowCaptureHook` at its Risk decision point:

    verified candidate -> Risk
        |-- ACCEPT -> normal PAPER path (hook NOT invoked)
        `-- REJECT -> hook.on_risk_reject(...) -> ShadowCandidateCapture

Captures are then resolved PIT by :class:`ShadowOutcomeEngine` into
``ShadowTrade`` records for the D1 analysis target (per-reason metrics
conditioned by strategy/asset/regime/health/correlation).

Isolation contract (tested):

- PaperBroker calls from shadow: 0 (the hook performs no execution and
  holds no execution objects).
- PortfolioStore mutation from shadow: 0.
- RiskManager mutation from shadow: 0 (hook is observational).
- Paper PnL / frequency contamination: 0 (captures carry the canonical
  EXCLUDED_FROM_PAPER_* labels and never enter campaign accounting).

This module must NOT be imported by the POC01 runtime (same rule as the
rest of ``trading_bot.shadow``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_bot.execution.cost_model import ExecutionCostModel
from trading_bot.shadow.capture import ShadowCandidateCapture, ShadowCandidateLedger
from trading_bot.shadow.outcome import (
    ShadowBar,
    ShadowOutcomeEngine,
    ShadowOutcomeLedger,
    ShadowTrade,
)

__all__ = ["ShadowCaptureHook"]


class ShadowCaptureHook:
    """Ready-to-wire hook for the next campaign runtime's Risk REJECT arm."""

    def __init__(
        self,
        *,
        captures_path: Path | str,
        outcomes_path: Path | str | None = None,
        cost_model: ExecutionCostModel | None = None,
    ) -> None:
        self._captures_path = Path(captures_path)
        self._outcomes_path = Path(outcomes_path) if outcomes_path else None
        self.captures = ShadowCandidateLedger.load(self._captures_path)
        self._engine = ShadowOutcomeEngine(cost_model)
        self.outcomes = (
            ShadowOutcomeLedger.load(self._outcomes_path)
            if self._outcomes_path
            else ShadowOutcomeLedger()
        )

    # -- capture arm (called by the runtime on Risk REJECT) ------------------

    def on_risk_reject(self, ctx: dict[str, Any]) -> str:
        """Record one immutable capture from a risk-REJECT decision context.

        Required keys: decision_id, trace_id, run_id, asset, direction,
        strategy_id, strategy_version, timeframe, proposal_ref, decision_ref,
        verifier_ref, decision_time, decision_price, entry_reference,
        stop_loss, take_profit, invalidation, regime_signature,
        strategy_health_state, portfolio_context_ref, correlation_state,
        risk_rejection_reason, market_data_fingerprint, cost_model_sha256.
        """
        if str(ctx.get("risk_verdict", "REJECT")).upper() != "REJECT":
            raise ValueError("ShadowCaptureHook records REJECT decisions only")
        capture = ShadowCandidateCapture(
            decision_id=str(ctx["decision_id"]),
            trace_id=str(ctx["trace_id"]),
            run_id=str(ctx["run_id"]),
            asset=str(ctx["asset"]),
            direction=str(ctx["direction"]),
            strategy_id=str(ctx["strategy_id"]),
            strategy_version=str(ctx["strategy_version"]),
            timeframe=str(ctx["timeframe"]),
            proposal_ref=str(ctx["proposal_ref"]),
            decision_ref=str(ctx["decision_ref"]),
            verifier_ref=str(ctx["verifier_ref"]),
            decision_time=str(ctx["decision_time"]),
            decision_price=float(ctx["decision_price"]),
            entry_reference=float(ctx["entry_reference"]),
            stop_loss=float(ctx["stop_loss"]),
            take_profit=float(ctx["take_profit"]),
            invalidation=str(ctx["invalidation"]),
            regime_signature=str(ctx["regime_signature"]),
            strategy_health_state=str(ctx["strategy_health_state"]),
            portfolio_context_ref=str(ctx["portfolio_context_ref"]),
            correlation_state=str(ctx["correlation_state"]),
            risk_verdict="REJECT",
            risk_rejection_reason=str(ctx["risk_rejection_reason"]),
            market_data_fingerprint=str(ctx["market_data_fingerprint"]),
            cost_model_sha256=str(ctx["cost_model_sha256"]),
        )
        cid = self.captures.record(capture)
        self._captures_path.parent.mkdir(parents=True, exist_ok=True)
        self.captures.save(self._captures_path)
        return cid

    # -- resolution arm (PIT, separate process/cron in V2) --------------------

    def resolve_pending(
        self,
        bars_by_decision: dict[str, list[ShadowBar]],
        *,
        quantity_by_decision: dict[str, float] | None = None,
    ) -> list[ShadowTrade]:
        """Resolve captures with PIT bars; duplicates are ledger-guarded."""
        resolved: list[ShadowTrade] = []
        for capture in self.captures.captures:
            if capture.decision_id in bars_by_decision:
                bars = bars_by_decision[capture.decision_id]
                if not bars:
                    continue
                qty = (quantity_by_decision or {}).get(capture.decision_id, 1.0)
                trade = self._engine.resolve(capture, bars, quantity=qty)
                self.outcomes.record(trade)
                resolved.append(trade)
        if self._outcomes_path is not None and resolved:
            self._outcomes_path.parent.mkdir(parents=True, exist_ok=True)
            self.outcomes.save(self._outcomes_path)
        return resolved
