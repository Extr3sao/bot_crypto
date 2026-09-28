"""Outcome evaluation — a decision is not finished when it is generated (§6/§16).

For every resolved decision the evaluator computes what happened between the
decision time and the end of the pre-registered horizon:

* ``gross_return_bps``   direction-adjusted price move (sign matters);
* ``estimated_cost_bps`` the SAME cost model carried by the proposal;
* ``net_hypothetical_bps`` gross - cost;
* ``MFE`` / ``MAE``      best/worst excursion inside the window;
* ``direction_correct``  whether the sign was right.

Temporal integrity is a hard gate: only bars with ``timestamp >
decision_time_ms`` are used, and the outcome timestamp must be strictly
later than the decision timestamp. A horizon that has not elapsed yet
returns ``PENDING_OUTCOME`` — never a fabricated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.market_data.types import OHLCV

from .contracts import (
    DecisionMode,
    DecisionTrace,
    OutcomeRecord,
    OutcomeStatus,
    TradeProposal,
)

__all__ = ["OUTCOME_EVALUATOR_VERSION", "OutcomeEvaluation", "OutcomeEvaluator"]

OUTCOME_EVALUATOR_VERSION = "outcome-evaluator-v1"

_MS_PER_MINUTE = 60_000


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    decision_id: str
    status: OutcomeStatus
    record: OutcomeRecord | None
    reason: str

    @property
    def resolved(self) -> bool:
        return self.status is OutcomeStatus.RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "status": self.status.value,
            "reason": self.reason,
            "record": None if self.record is None else self.record.to_dict(),
        }


class OutcomeEvaluator:
    """Evaluate one persisted decision against later, PIT-safe market data."""

    def __init__(self, *, version: str = OUTCOME_EVALUATOR_VERSION) -> None:
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def evaluate(
        self,
        *,
        trace: DecisionTrace,
        bars: tuple[OHLCV, ...] | list[OHLCV],
        created_at_ms: int = 0,
    ) -> OutcomeEvaluation:
        """Resolve the decision's horizon, or report PENDING_OUTCOME."""
        if trace.proposal is None:
            return OutcomeEvaluation(
                decision_id=trace.decision_id,
                status=OutcomeStatus.NOT_APPLICABLE,
                record=None,
                reason="decision carried no proposal",
            )
        proposal = TradeProposal.from_dict(trace.proposal)
        horizon_ms = round(proposal.horizon_minutes * _MS_PER_MINUTE)
        target_ts = trace.decision_time_ms + horizon_ms

        future = sorted(
            (b for b in bars if b.timestamp > trace.decision_time_ms), key=lambda b: b.timestamp
        )
        if not future:
            return OutcomeEvaluation(
                decision_id=trace.decision_id,
                status=OutcomeStatus.PENDING_OUTCOME,
                record=None,
                reason="no bar strictly after the decision time yet",
            )
        if future[-1].timestamp < target_ts:
            return OutcomeEvaluation(
                decision_id=trace.decision_id,
                status=OutcomeStatus.PENDING_OUTCOME,
                record=None,
                reason=(
                    f"horizon not elapsed: need bar at {target_ts}, "
                    f"latest available {future[-1].timestamp}"
                ),
            )

        outcome_bar = next(b for b in future if b.timestamp >= target_ts)
        window = [b for b in future if b.timestamp <= outcome_bar.timestamp]
        entry = proposal.entry_reference
        sign = 1.0 if proposal.direction == "LONG" else -1.0
        gross_bps = sign * (outcome_bar.close - entry) / entry * 10_000.0

        excursions = [sign * (b.high - entry) / entry * 10_000.0 for b in window]
        adverse = [sign * (b.low - entry) / entry * 10_000.0 for b in window]
        mfe_bps = max(excursions)
        mae_bps = min(adverse)

        estimated_cost_bps = proposal.expected_cost_bps
        record = OutcomeRecord(
            run_id=trace.run_id,
            decision_id=trace.decision_id,
            asset=trace.asset,
            symbol=trace.symbol,
            strategy_id=proposal.strategy_id,
            mode=trace.mode,
            direction=proposal.direction,
            decision_time_ms=trace.decision_time_ms,
            outcome_time_ms=outcome_bar.timestamp,
            horizon_minutes=proposal.horizon_minutes,
            entry_reference=entry,
            outcome_price=outcome_bar.close,
            gross_return_bps=gross_bps,
            estimated_cost_bps=estimated_cost_bps,
            net_hypothetical_bps=gross_bps - estimated_cost_bps,
            mfe_bps=mfe_bps,
            mae_bps=mae_bps,
            direction_correct=gross_bps > 0,
            regime=trace.regime,
            data_complete=True,
            status=OutcomeStatus.RESOLVED,
            bars_observed=len(window),
            created_at_ms=created_at_ms,
        )
        return OutcomeEvaluation(
            decision_id=trace.decision_id,
            status=OutcomeStatus.RESOLVED,
            record=record,
            reason=f"horizon {proposal.horizon_minutes:.0f}m resolved at {outcome_bar.timestamp}",
        )

    def resolve_pending(
        self,
        *,
        traces: list[DecisionTrace],
        bars_by_symbol: dict[str, list[OHLCV]],
        already_resolved: set[str] | None = None,
        created_at_ms: int = 0,
    ) -> list[OutcomeEvaluation]:
        """Evaluate every evaluable, not-yet-resolved decision."""
        resolved = already_resolved or set()
        evaluations: list[OutcomeEvaluation] = []
        for trace in traces:
            if trace.decision_id in resolved:
                continue
            if trace.mode is DecisionMode.NO_TRADE:
                continue  # nothing to evaluate: no hypothetical position was taken
            bars = bars_by_symbol.get(trace.symbol)
            if bars is None:
                evaluations.append(
                    OutcomeEvaluation(
                        decision_id=trace.decision_id,
                        status=OutcomeStatus.PENDING_OUTCOME,
                        record=None,
                        reason="no market data for this symbol in this cycle",
                    )
                )
                continue
            evaluations.append(
                self.evaluate(trace=trace, bars=bars, created_at_ms=created_at_ms)
            )
        return evaluations
