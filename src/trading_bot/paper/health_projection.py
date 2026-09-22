"""Strategy Health frontend projection — Track F.

Read-only projection contract for a future health dashboard. NO trading
controls, NO mutation endpoints, NO activation logic: this is a pure
serializer over the Track B model. An actual polished UI is a following
checkpoint; this contract pins the payload shape now so the frontend and the
runtime can evolve against a stable schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.strategies.health import (
    HealthIdentity,
    StrategyHealthSnapshot,
    StrategyHealthState,
)


@dataclass(frozen=True, slots=True)
class HealthProjectionRow:
    """One read-only health row for the frontend."""

    strategy: str
    version: str
    asset: str
    timeframe: str
    regime: str
    observation_window: str
    health_state: str
    rolling_expectancy: float
    baseline_expectancy: float
    rolling_sharpe: float
    baseline_sharpe: float
    profit_factor: float
    drawdown: float
    sample_size: int
    last_transition: str
    reason: str
    next_gate: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "observation_window": self.observation_window,
            "health_state": self.health_state,
            "metrics": {
                "rolling_expectancy": self.rolling_expectancy,
                "baseline_expectancy": self.baseline_expectancy,
                "rolling_sharpe": self.rolling_sharpe,
                "baseline_sharpe": self.baseline_sharpe,
                "profit_factor": self.profit_factor,
                "drawdown": self.drawdown,
                "sample_size": self.sample_size,
            },
            "transition": {
                "last": self.last_transition,
                "reason": self.reason,
                "next_gate": self.next_gate,
            },
            "read_only": True,
        }


def project_health_row(
    identity: HealthIdentity,
    snapshot: StrategyHealthSnapshot,
    state: StrategyHealthState,
    *,
    last_transition: str = "",
    reason: str = "",
) -> HealthProjectionRow:
    """Project a health cell into the frontend contract.

    ``next_gate`` is derived deterministically from the state: what must
    happen before the cell can change state again (hysteresis gates /
    revalidation / governance). It is INFORMATIONAL ONLY — it does not grant
    or perform any action.
    """
    next_gates: dict[str, str] = {
        StrategyHealthState.HEALTHY.value: "degraded_signals x2 consecutive windows -> DEGRADED proposal",
        StrategyHealthState.MONITORING.value: "degraded_signals x2 consecutive windows -> DEGRADED proposal",
        StrategyHealthState.DEGRADED.value: "clean_metrics x2 consecutive windows -> MONITORING proposal",
        StrategyHealthState.QUARANTINED.value: "research -> validation -> revalidation -> MONITORING proposal",
        StrategyHealthState.RETIRED.value: "terminal; re-admission requires full admission path",
        StrategyHealthState.LEGACY_PAPER_BASELINE.value: "instrumentation required -> MONITORING proposal",
        StrategyHealthState.INSUFFICIENT_EVIDENCE.value: "sample_size >= snapshot threshold -> MONITORING/DEGRADED verdict",
    }
    return HealthProjectionRow(
        strategy=identity.strategy_id,
        version=identity.version,
        asset=identity.asset,
        timeframe=identity.timeframe,
        regime=identity.regime,
        observation_window=identity.observation_window,
        health_state=state.value,
        rolling_expectancy=snapshot.rolling_expectancy,
        baseline_expectancy=snapshot.baseline_expectancy,
        rolling_sharpe=snapshot.rolling_sharpe,
        baseline_sharpe=snapshot.baseline_sharpe,
        profit_factor=snapshot.profit_factor,
        drawdown=snapshot.drawdown,
        sample_size=snapshot.sample_size,
        last_transition=last_transition,
        reason=reason,
        next_gate=next_gates.get(state.value, "unknown"),
    )


def project_health_table(
    rows: tuple[tuple[HealthIdentity, StrategyHealthSnapshot, StrategyHealthState, str, str], ...],
) -> tuple[dict[str, Any], ...]:
    """Project many cells; pure, deterministic ordering by (strategy, asset, timeframe, regime)."""
    projected = [
        project_health_row(identity, snapshot, state, last_transition=last, reason=reason).to_dict()
        for identity, snapshot, state, last, reason in rows
    ]
    projected.sort(
        key=lambda row: (
            str(row["strategy"]),
            str(row["asset"]),
            str(row["timeframe"]),
            str(row["regime"]),
        )
    )
    return tuple(projected)
