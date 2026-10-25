"""EDGE-INTRA-01R — the frozen intraday breakout, ENTERED on a resting limit at the level.

H2's diagnostic (`ENTRY_TIMING.json`) measured what the intraday book pays on the way
in: 236 of 290 DEV fills landed at or past 0.25 ATR above the level the signal itself
named in ``hard_invalidation``, and the minority that filled closest to the level was
the only one with a positive gross. The obvious reading is that the entry, not the stop
and not the cost model, is where the money goes, so the next artefact to build is an
entry that buys AT the level.

This module is that entry, and nothing else:

* the SIGNALS are the frozen EDGE-INTRA-01 signals, produced by the frozen candidate
  object itself (volume filter, 1h trend filter, level de-duplication, stop, target,
  cost gate) — the wrapper only re-reads what the frozen rule printed;
* the PLAN is a limit buy at the broken level, live for ``retest_expiry_bars`` bars of
  the 15m clock. Whether it fills is decided by the bars, never assumed: the simulator
  fills it only if a bar trades at or through the level, at the level price and never
  better, and publishes the orders that expired, that were cancelled by the plan's own
  invalidation, and that the risk budget refused;
* the stop, the target and the trailing rule are the frozen signal's, unchanged. The
  stop is NOT widened to make room for a deeper retest, because that would be a second
  change smuggled into the same experiment;
* the cost/R:R gate is re-stated at the planned price, because that is the entry the
  plan actually proposes. Entering at the level is strictly closer to the target and
  strictly farther from the stop than entering at the breakout close, so this gate can
  only admit MORE than the frozen one — the code is kept so the arm's gate is explicit
  and both readings are published next to each other.

Reusing the frozen signals is the point: the two arms differ in the execution of the
same plan, which is the only way the experiment isolates the entry price.
"""

from __future__ import annotations

from typing import Any

from .candidates import (
    FROZEN_PARAMS,
    CandidateSignal,
    ContextSeries,
    IntraBreakout,
    Outcome,
)
from .costs import CostPlane
from .data import OHLCVBar

__all__ = ["RETEST_PARAMS", "RetestEntry", "build_retest_variant"]

#: The only numbers this variant adds to the frozen ruleset. Declared here, before any
#: arm ran, and carried into the artefacts next to the frozen ``PARAMS_HASH``.
RETEST_PARAMS: dict[str, Any] = {
    "base_candidate": "edge_intra_01",
    "entry": "resting limit buy at the broken level (hard_invalidation)",
    "retest_expiry_bars": 8,
    "fill_rule": "a bar whose low reaches the level fills it, at the level, never better",
    "cancellation": "a close below the level cancels the plan; the window end cancels it",
}


class RetestEntry(IntraBreakout):
    """EDGE-INTRA-01R — the frozen ruleset with its entry moved to the level.

    Subclassing ``IntraBreakout`` rather than wrapping it: the frozen ``on_bar`` is
    called first and, when it prints a signal, the SAME signal is re-emitted with a
    planned limit entry and with the gate numbers restated at that price. A refusal or
    a quiet bar is passed through untouched, so the refusal funnel of the two arms is
    comparable line by line.
    """

    id = "edge_intra_01r"

    def __init__(self, *, expiry_bars: int | None = None) -> None:
        super().__init__(FROZEN_PARAMS["edge_intra_01"])
        self.expiry_bars = int(
            RETEST_PARAMS["retest_expiry_bars"] if expiry_bars is None else expiry_bars
        )

    def plan(
        self, signal: CandidateSignal, *, plane: CostPlane
    ) -> CandidateSignal | Outcome:
        """Turn a frozen signal into the plan: a limit entry at the level it broke."""
        level = signal.hard_invalidation
        target = signal.targets[0] if signal.targets else None
        if level is None or level <= 0 or target is None or target <= level:
            # The frozen rule named no level to return to (or no objective above it):
            # there is nothing to rest an order on, so the signal is left as it was
            # printed rather than re-interpreted.
            return signal
        stop_distance = level - signal.stop
        numbers, refusal = self.cost_gate(
            i=signal.bar_index,
            decision_ts=signal.decision_ts,
            close=level,
            objective=target,
            stop_distance=stop_distance,
            plane=plane,
            min_rr=float(self.params["min_rr"]),
        )
        if refusal is not None:
            refusal.detail["planned_entry"] = level
            return refusal
        assert numbers is not None
        atr = float(signal.evidence.get("atr") or 0.0)
        evidence = {
            **signal.evidence,
            "planned_entry": level,
            "retest_expiry_bars": self.expiry_bars,
            "breakout_entry_reference": signal.entry_reference,
            "breakout_distance_atr": (
                round((signal.entry_reference - level) / atr, 6) if atr > 0 else None
            ),
            "gate_at_breakout": {
                "risk_reward": signal.risk_reward,
                "expected_gross_bps": signal.expected_gross_bps,
                "expected_cost_bps": signal.expected_cost_bps,
                "expected_net_bps": signal.expected_net_bps,
            },
            "gate_at_limit": dict(numbers),
        }
        return CandidateSignal(
            candidate=self.id,
            symbol=signal.symbol,
            bar_index=signal.bar_index,
            decision_ts=signal.decision_ts,
            decision_timeframe=signal.decision_timeframe,
            entry_reference=level,
            direction=signal.direction,
            stop=signal.stop,
            targets=signal.targets,
            invalidations=signal.invalidations,
            risk_reward=numbers["risk_reward"],
            expected_gross_bps=numbers["expected_gross_bps"],
            expected_cost_bps=numbers["expected_cost_bps"],
            expected_net_bps=numbers["expected_net_bps"],
            regime=signal.regime,
            evidence=evidence,
            trailing_atr=signal.trailing_atr,
            trailing_atr_value=signal.trailing_atr_value,
            exit_ema_period=signal.exit_ema_period,
            hard_invalidation=level,
            entry_limit=level,
            limit_expiry_bars=self.expiry_bars,
        )

    def on_bar(
        self, bars: list[OHLCVBar], i: int, context: ContextSeries | None, plane: CostPlane
    ) -> Outcome:
        # The frozen ruleset decides; this class only re-states the entry it proposed.
        outcome = super().on_bar(bars, i, context, plane)
        if not isinstance(outcome, CandidateSignal):
            return outcome
        return self.plan(outcome, plane=plane)


def build_retest_variant() -> RetestEntry:
    """The one H6 variant object, with the frozen ruleset and the declared expiry."""
    return RetestEntry()
