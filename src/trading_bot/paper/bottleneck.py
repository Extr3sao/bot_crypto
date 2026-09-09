"""Observational bottleneck state model (Track F).

POC02-LAUNCH-AND-DISCOVERY-BATCH-02. POC01 showed two distinct phases:

- PHASE A: many candidates -> high Risk rejection;
- PHASE B: scans -> zero proposals -> NO_SIGNAL.

:class:`BottleneckState` makes the per-window collapse point explicit.
STRICTLY OBSERVATIONAL: it never gates, blocks, or routes anything —
it is evidence for later analysis (regime x bottleneck concentration).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BottleneckState",
    "BottleneckWindow",
    "classify_window",
    "regime_bottleneck_table",
]


class BottleneckState:
    """Canonical funnel collapse points (observational labels only)."""

    NO_SIGNAL = "NO_SIGNAL"  # scans ran, zero proposals
    STRATEGY_FILTER = "STRATEGY_FILTER"  # signals fired, strategies filtered them
    AGENT_FILTER = "AGENT_FILTER"  # proposals existed, none selected
    VERIFIER_FILTER = "VERIFIER_FILTER"  # selected, verifier rejected
    RISK_COOLDOWN = "RISK_COOLDOWN"  # risk rejected on consecutive-loss cooldown
    RISK_POSITIONS = "RISK_POSITIONS"  # risk rejected on MAX_POSITIONS / exposure
    EXECUTION = "EXECUTION"  # risk approved, paper execution failed
    NONE = "NONE"  # a trade opened; no collapse this window

    ALL: tuple[str, ...] = (
        NO_SIGNAL,
        STRATEGY_FILTER,
        AGENT_FILTER,
        VERIFIER_FILTER,
        RISK_COOLDOWN,
        RISK_POSITIONS,
        EXECUTION,
        NONE,
    )


@dataclass(frozen=True, slots=True)
class BottleneckWindow:
    """One observed window (e.g. one cycle or one day)."""

    window_id: str
    regime: str | None
    bottleneck: str
    counts: dict[str, int]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "regime": self.regime,
            "bottleneck": self.bottleneck,
            "counts": dict(self.counts),
            "reason": self.reason,
        }


def classify_window(
    *,
    window_id: str,
    activity: Mapping[str, Any],
    regime: str | None = None,
) -> BottleneckWindow:
    """Classify one window's bottleneck from recorded counts (no inference).

    Accepted keys (daily-report activity payload): market_scans,
    trade_proposals, selected_decisions, verifier_rejects, risk_accepts,
    risk_rejects, risk_rejects_by_reason (dict), executed_paper_trades,
    broker_errors.

    Decision order is the funnel order; the first gate with zero throughput
    while its upstream was productive is the bottleneck. When both NO_SIGNAL
    and risk-rejections are present in the same window, NO_SIGNAL wins only
    if there were no proposals at all (PHASE B); otherwise the recorded risk
    bucket is used (PHASE A). Nothing here is trading authority.
    """
    scans = int(activity.get("market_scans", 0) or 0)
    proposals = int(activity.get("trade_proposals", 0) or 0)
    selected = int(activity.get("selected_decisions", 0) or 0)
    verifier_rejects = int(activity.get("verifier_rejects", 0) or 0)
    risk_accepts = int(activity.get("risk_accepts", 0) or 0)
    risk_rejects = int(activity.get("risk_rejects", 0) or 0)
    paper = int(activity.get("executed_paper_trades", 0) or 0)
    broker_errors = int(activity.get("broker_errors", 0) or 0)
    by_reason = dict(activity.get("risk_rejects_by_reason") or {})
    counts = {
        "scans": scans,
        "proposals": proposals,
        "selected": selected,
        "verifier_rejects": verifier_rejects,
        "risk_accepts": risk_accepts,
        "risk_rejects": risk_rejects,
        "paper": paper,
        "broker_errors": broker_errors,
    }

    if scans == 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.NONE,
            counts=counts,
            reason="no scans recorded (window not observed)",
        )
    if proposals == 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.NO_SIGNAL,
            counts=counts,
            reason="scans produced zero proposals (PHASE B collapse)",
        )
    if selected == 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.AGENT_FILTER,
            counts=counts,
            reason="proposals existed but none selected",
        )
    if verifier_rejects > 0 and risk_accepts == 0 and risk_rejects == 0 and paper == 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.VERIFIER_FILTER,
            counts=counts,
            reason="selected candidate rejected by MA-4 verifier",
        )
    if risk_rejects > 0:
        cooldown = int(by_reason.get("CONSECUTIVE_LOSS_COOLDOWN", 0) or 0)
        positions = int(
            by_reason.get("MAX_POSITIONS", 0)
            + by_reason.get("MAX_ASSET_EXPOSURE", 0)
            + by_reason.get("MAX_TOTAL_EXPOSURE", 0)
            or 0
        )
        if cooldown > 0 and cooldown >= positions:
            return BottleneckWindow(
                window_id=window_id,
                regime=regime,
                bottleneck=BottleneckState.RISK_COOLDOWN,
                counts=counts,
                reason="risk rejections dominated by consecutive-loss cooldown",
            )
        if positions > 0:
            return BottleneckWindow(
                window_id=window_id,
                regime=regime,
                bottleneck=BottleneckState.RISK_POSITIONS,
                counts=counts,
                reason="risk rejections dominated by position/exposure limits",
            )
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.RISK_COOLDOWN,
            counts=counts,
            reason="risk rejections recorded without a persisted reason split (default bucket)",
        )
    if broker_errors > 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.EXECUTION,
            counts=counts,
            reason="risk approved but paper execution reported errors",
        )
    if paper > 0 or risk_accepts > 0:
        return BottleneckWindow(
            window_id=window_id,
            regime=regime,
            bottleneck=BottleneckState.NONE,
            counts=counts,
            reason="funnel flowed to paper without collapse",
        )
    return BottleneckWindow(
        window_id=window_id,
        regime=regime,
        bottleneck=BottleneckState.STRATEGY_FILTER,
        counts=counts,
        reason="signals/strategies produced proposals downstream but none reached risk",
    )


def regime_bottleneck_table(
    windows: Iterable[BottleneckWindow],
) -> dict[str, dict[str, int]]:
    """Regime x bottleneck concentration (observational only)."""
    table: dict[str, dict[str, int]] = {}
    for w in windows:
        regime = w.regime or "UNCLASSIFIED"
        row = table.setdefault(regime, dict.fromkeys(BottleneckState.ALL, 0))
        row[w.bottleneck] = row.get(w.bottleneck, 0) + 1
    return table
