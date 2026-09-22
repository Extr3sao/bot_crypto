"""StrategyRegimeEligibility — Track B of PORTFOLIO-AND-RUNTIME-INTEGRATION-01.

Deterministic EVIDENCE model binding a strategy cell (strategy x version x
asset x timeframe) to a regime signature with performance metrics and status.
It is input for FUTURE StrategyRouter decisions — not an adaptive/LLM decision
surface — and must NOT be activated in frozen POC01.

Regime signatures use the canonical six dimensions from
``research/regime_v2.py``. To avoid thousands of micro-regimes, signatures
aggregate by DECLARED dimension subsets only:

- ``exact``:     all six dimensions
- ``structure``: market_structure + stress + correlation_regime (pre-declared fallback)
- ``direction``: trend_direction + volatility (pre-declared fallback)

Backoff order is pre-declared: exact -> structure -> direction -> global.
Merging after seeing results is impossible by construction: the fallback
chain is fixed in code and never data-driven.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from trading_bot.research.regime_v2 import MarketRegimeState


class SignatureLevel(StrEnum):
    EXACT = "EXACT"
    STRUCTURE = "STRUCTURE"
    DIRECTION = "DIRECTION"
    GLOBAL = "GLOBAL"


# Pre-declared fallback chain (RE-04): fixed order, never opportunistic.
FALLBACK_CHAIN: tuple[SignatureLevel, ...] = (
    SignatureLevel.EXACT,
    SignatureLevel.STRUCTURE,
    SignatureLevel.DIRECTION,
    SignatureLevel.GLOBAL,
)


def regime_signature(state: MarketRegimeState, level: SignatureLevel) -> str:
    """Deterministic signature for a regime at an aggregation level."""
    if level is SignatureLevel.EXACT:
        return state.key()
    if level is SignatureLevel.STRUCTURE:
        return f"S:{state.market_structure.value}|{state.stress.value}|{state.correlation_regime.value}"
    if level is SignatureLevel.DIRECTION:
        return f"D:{state.trend_direction.value}|{state.volatility.value}"
    return "GLOBAL"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SHADOW_ONLY = "SHADOW_ONLY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EligibilityMetrics:
    """Performance metrics bound to one regime cell (RE-02)."""

    n: int
    expectancy: float
    profit_factor: float
    sharpe: float
    drawdown: float
    cost_adjusted_expectancy: float
    health_state: str  # StrategyHealthState value
    admission_evidence: bool  # stat/admission evidence present (Track E gates passed)


@dataclass(frozen=True, slots=True)
class StrategyRegimeEligibility:
    """Evidence record for one strategy x regime cell."""

    strategy_id: str
    version: str
    asset: str
    timeframe: str
    regime_signature: str
    signature_level: SignatureLevel
    metrics: EligibilityMetrics
    status: EligibilityStatus
    basis: str  # which pre-declared rule produced the status

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime_signature": self.regime_signature,
            "signature_level": self.signature_level.value,
            "metrics": {
                "n": self.metrics.n,
                "expectancy": self.metrics.expectancy,
                "profit_factor": self.metrics.profit_factor,
                "sharpe": self.metrics.sharpe,
                "drawdown": self.metrics.drawdown,
                "cost_adjusted_expectancy": self.metrics.cost_adjusted_expectancy,
                "health_state": self.metrics.health_state,
                "admission_evidence": self.metrics.admission_evidence,
            },
            "status": self.status.value,
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class EligibilityThresholds:
    """Deterministic thresholds; identical for every strategy (fairness)."""

    min_eligible_n: int = 30
    min_shadow_n: int = 10
    min_expectancy: float = 0.0
    min_profit_factor: float = 1.0
    max_drawdown: float = 0.20
    quarantine_states: frozenset[str] = frozenset({"QUARANTINED", "RETIRED"})


def _status_for_metrics(
    metrics: EligibilityMetrics,
    t: EligibilityThresholds,
) -> tuple[EligibilityStatus, str]:
    """Deterministic status rules (fail-closed, RE-03)."""
    if metrics.n >= t.min_eligible_n:
        if metrics.health_state in t.quarantine_states:
            return (
                EligibilityStatus.NOT_ELIGIBLE,
                f"health_state={metrics.health_state} overrides metrics",
            )
        if (
            metrics.expectancy >= t.min_expectancy
            and metrics.profit_factor >= t.min_profit_factor
            and metrics.drawdown <= t.max_drawdown
        ):
            if metrics.admission_evidence:
                return (
                    EligibilityStatus.ELIGIBLE,
                    f"n>={t.min_eligible_n} and metrics pass and admission evidence present",
                )
            return (
                EligibilityStatus.SHADOW_ONLY,
                f"n>={t.min_eligible_n} and metrics pass but no admission evidence",
            )
        return EligibilityStatus.NOT_ELIGIBLE, f"n>={t.min_eligible_n} but metrics fail thresholds"
    if metrics.n >= t.min_shadow_n:
        return (
            EligibilityStatus.SHADOW_ONLY,
            f"{t.min_shadow_n} <= n < {t.min_eligible_n} -> shadow only",
        )
    return EligibilityStatus.INSUFFICIENT_EVIDENCE, f"n={metrics.n} < {t.min_shadow_n}"


def evaluate_regime_eligibility(
    *,
    strategy_id: str,
    version: str,
    asset: str,
    timeframe: str,
    regime: MarketRegimeState,
    metrics_by_level: dict[SignatureLevel, EligibilityMetrics],
    thresholds: EligibilityThresholds | None = None,
) -> StrategyRegimeEligibility:
    """Evaluate eligibility walking the PRE-DECLARED fallback chain.

    ``metrics_by_level`` maps an aggregation level to the metrics collected
    AT that level. The function tries EXACT first; if the exact-regime sample
    is insufficient it falls back to STRUCTURE, then DIRECTION, then GLOBAL —
    in that fixed order. The chosen level is recorded in ``basis``; merging
    after seeing results cannot happen because the chain is static.
    """
    t = thresholds or EligibilityThresholds()
    for level in FALLBACK_CHAIN:
        metrics = metrics_by_level.get(level)
        if metrics is None:
            continue  # level never collected: skip to next pre-declared level
        status, basis = _status_for_metrics(metrics, t)
        if status is EligibilityStatus.INSUFFICIENT_EVIDENCE and level is not SignatureLevel.GLOBAL:
            continue  # insufficient at this level -> declared fallback
        return StrategyRegimeEligibility(
            strategy_id=strategy_id,
            version=version,
            asset=asset,
            timeframe=timeframe,
            regime_signature=regime_signature(regime, level),
            signature_level=level,
            metrics=metrics,
            status=status,
            basis=f"level={level.value}: {basis}",
        )
    # No level had any data at all: fail closed on the exact signature.
    empty = EligibilityMetrics(
        n=0,
        expectancy=0.0,
        profit_factor=0.0,
        sharpe=0.0,
        drawdown=0.0,
        cost_adjusted_expectancy=0.0,
        health_state="UNKNOWN",
        admission_evidence=False,
    )
    return StrategyRegimeEligibility(
        strategy_id=strategy_id,
        version=version,
        asset=asset,
        timeframe=timeframe,
        regime_signature=regime_signature(regime, SignatureLevel.EXACT),
        signature_level=SignatureLevel.EXACT,
        metrics=empty,
        status=EligibilityStatus.INSUFFICIENT_EVIDENCE,
        basis="no metrics collected at any pre-declared level",
    )
