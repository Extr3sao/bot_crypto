"""Outcome evaluation — a decision is not finished when it is generated (§6/§16).

For every resolved decision the evaluator computes what happened between the
decision time and the end of the pre-registered horizon:

* ``gross_return_bps``   direction-adjusted price move (sign matters);
* ``estimated_cost_bps`` the SAME cost model carried by the proposal;
* ``net_hypothetical_bps`` gross - cost;
* ``MFE`` / ``MAE``      best/worst excursion inside the window;
* ``direction_correct``  whether the sign was right.

Temporal integrity is a hard gate: only bars that CLOSED after the decision
time are used, and the outcome timestamp must be strictly later than the
decision timestamp. A horizon that has not elapsed yet returns
``PENDING_OUTCOME`` — never a fabricated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.market_data.types import OHLCV

from .contracts import (
    DecisionTrace,
    OutcomeRecord,
    OutcomeStatus,
    TradeProposal,
)
from .pit import availability_ms, closed_bar_slice, infer_bar_interval_ms

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
        """Resolve the decision's horizon, or report PENDING_OUTCOME.

        A bar is only usable at its CLOSE: the outcome instant recorded is
        ``bar.timestamp + interval``, never the bar's open timestamp. Claiming
        an outcome earlier than the close would report information that did not
        exist yet (the price of that bar is only final when the bar closes).

        The same rule is applied backwards to the ENTRY reference: the recorded
        ``reference_price_time_ms`` is the close of the newest bar the decision
        could legitimately have read, so the whole record satisfies

            reference_price_time_ms <= decision_time_ms < outcome_time_ms
        """
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

        interval_ms = infer_bar_interval_ms(bars)
        # A bar is a FUTURE observation when it CLOSES after the decision time.
        # The bar the decision was taken on closes exactly at the first horizon
        # step, so it is the natural observation for a one-bar horizon.
        future = sorted(
            (b for b in bars if availability_ms(b, interval_ms) > trace.decision_time_ms),
            key=lambda b: b.timestamp,
        )
        if not future:
            return OutcomeEvaluation(
                decision_id=trace.decision_id,
                status=OutcomeStatus.PENDING_OUTCOME,
                record=None,
                reason="no bar has closed after the decision time yet",
            )
        if interval_ms is None:
            # Unknown bar spacing: fall back to the conservative rule (needs a
            # bar that OPENS at or beyond the horizon) and say so.
            reachable = availability_ms(future[-1], interval_ms)
            usable = [b for b in future if b.timestamp >= target_ts]
            reason_tag = "bar interval unknown (conservative: bar open >= horizon)"
        else:
            reachable = availability_ms(future[-1], interval_ms)
            usable = [b for b in future if availability_ms(b, interval_ms) >= target_ts]
            reason_tag = ""
        if not usable:
            return OutcomeEvaluation(
                decision_id=trace.decision_id,
                status=OutcomeStatus.PENDING_OUTCOME,
                record=None,
                reason=(
                    f"horizon not elapsed: need an observation at {target_ts}, "
                    f"latest reachable {reachable}. {reason_tag}"
                ).strip(),
            )

        outcome_bar = usable[0]
        outcome_time_ms = availability_ms(outcome_bar, interval_ms)
        reference_bars = closed_bar_slice(
            bars, trace.decision_time_ms, interval_ms=interval_ms
        )
        reference_price_time_ms = (
            availability_ms(reference_bars[-1], interval_ms)
            if reference_bars
            else min(trace.market_time_ms or trace.decision_time_ms, trace.decision_time_ms)
        )
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
            outcome_time_ms=outcome_time_ms,
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
            market_time_ms=trace.market_time_ms,
            reference_price_time_ms=reference_price_time_ms,
            created_at_ms=created_at_ms,
        )
        return OutcomeEvaluation(
            decision_id=trace.decision_id,
            status=OutcomeStatus.RESOLVED,
            record=record,
            reason=(
                f"horizon {proposal.horizon_minutes:.0f}m resolved by the close of the bar "
                f"opened at {outcome_bar.timestamp} (available {outcome_time_ms})"
            ),
        )

    def resolve_pending(
        self,
        *,
        traces: list[DecisionTrace],
        bars_by_symbol: dict[str, list[OHLCV]],
        already_resolved: set[str] | None = None,
        created_at_ms: int = 0,
    ) -> list[OutcomeEvaluation]:
        """Evaluate every evaluable, not-yet-resolved decision.

        A NO_TRADE decision that carries a proposal is a MEASURABLE PREDICTION
        too: evaluating it is how the ledger's expected edge is calibrated (and
        falsified) without pretending anything was traded. Its sample is kept
        under its own mode so it can never be read as an execution result.
        """
        resolved = already_resolved or set()
        evaluations: list[OutcomeEvaluation] = []
        for trace in traces:
            if trace.decision_id in resolved:
                continue
            if trace.proposal is None:
                continue  # no hypothesis was formed: nothing to evaluate
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
