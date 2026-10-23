"""StrategyHealthMonitor — deterministic degradation detection (§8).

The monitor compares a strategy's CURRENT rolling window against its own LONG
baseline (and against absolute floors) and emits a structured
:class:`HealthReport` with explicit flags. It never decides a state — the
:class:`~trading_bot.strategy_lifecycle.lifecycle.StrategyLifecycleController`
does, from policy. No LLM touches the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .config import DEFAULT_HEALTH_POLICY, HealthPolicy
from .contracts import (
    ContextKey,
    HealthReport,
    HealthState,
    PerformanceCell,
)

__all__ = ["HEALTH_MONITOR_VERSION", "Flag", "StrategyHealthMonitor"]

HEALTH_MONITOR_VERSION: Final[str] = "strategy-health-monitor-v1"

_EPS: Final[float] = 1e-9

#: Flag weights used to fold flags into a 0..1 score.
_FLAG_WEIGHTS: Final[dict[str, float]] = {
    "expectancy_decay": 0.25,
    "drawdown_deterioration": 0.2,
    "profit_factor_deterioration": 0.2,
    "hit_rate_drift": 0.1,
    "signal_frequency_drift": 0.1,
    "slippage_deterioration": 0.1,
    "cost_sensitivity": 0.15,
    "regime_mismatch": 0.2,
    "loss_clustering": 0.15,
    "abnormal_inactivity": 0.15,
    "abnormal_signal_explosion": 0.15,
    "correlation_increase": 0.1,
}


class Flag:
    """Canonical degradation-flag names (string constants)."""

    EXPECTANCY_DECAY = "expectancy_decay"
    DRAWDOWN_DETERIORATION = "drawdown_deterioration"
    PROFIT_FACTOR_DETERIORATION = "profit_factor_deterioration"
    HIT_RATE_DRIFT = "hit_rate_drift"
    SIGNAL_FREQUENCY_DRIFT = "signal_frequency_drift"
    SLIPPAGE_DETERIORATION = "slippage_deterioration"
    COST_SENSITIVITY = "cost_sensitivity"
    REGIME_MISMATCH = "regime_mismatch"
    LOSS_CLUSTERING = "loss_clustering"
    CORRELATION_INCREASE = "correlation_increase"
    ABNORMAL_INACTIVITY = "abnormal_inactivity"
    ABNORMAL_SIGNAL_EXPLOSION = "abnormal_signal_explosion"


@dataclass(frozen=True, slots=True)
class HealthInputs:
    """Everything the monitor needs for one cell, all deterministic."""

    context: ContextKey
    cells: dict[str, PerformanceCell]
    now_ms: int = 0
    #: Number of bars elapsed in the working window, when known (frequency
    #: drift + inactivity rules need a denominator that is not the trade count).
    bar_count: int | None = None
    #: Net-bps series of the working window in chronological order (loss clustering).
    net_series: tuple[float, ...] = ()
    #: Baseline slippage (bps) to compare against ``current.slippage_bps``.
    baseline_slippage_bps: float | None = None
    #: Pairwise correlation of this strategy's net returns against the rest of
    #: the active book (portfolio-level; supplied by the portfolio manager).
    max_pairwise_correlation: float | None = None


@dataclass(frozen=True, slots=True)
class StrategyHealthMonitor:
    """Deterministic health evaluator (§8)."""

    policy: HealthPolicy = DEFAULT_HEALTH_POLICY
    version: str = HEALTH_MONITOR_VERSION

    def evaluate(self, inputs: HealthInputs) -> HealthReport:
        cells = inputs.cells
        short = cells.get("short")
        medium: PerformanceCell | None = cells.get("medium") or short
        if medium is None:
            return self._report(
                inputs, HealthState.INSUFFICIENT_DATA, 0.0, (), {}, {}, "no window data"
            )
        long: PerformanceCell = cells.get("long") or medium

        baseline = {
            "net_expectancy_bps": long.net_expectancy_bps if long else 0.0,
            "profit_factor": (long.profit_factor if long and long.profit_factor else 0.0),
            "hit_rate": long.hit_rate if long else 0.0,
            "max_drawdown_bps": long.max_drawdown_bps if long else 0.0,
            "slippage_bps": inputs.baseline_slippage_bps or 0.0,
        }
        current = {
            "net_expectancy_bps": medium.net_expectancy_bps,
            "profit_factor": medium.profit_factor if medium.profit_factor else 0.0,
            "hit_rate": medium.hit_rate,
            "max_drawdown_bps": medium.max_drawdown_bps,
            "cost_bps": medium.cost_bps,
            "gross_expectancy_bps": medium.gross_expectancy_bps,
        }
        metrics = {
            "sample_count": float(medium.sample_count),
            "net_expectancy_bps": medium.net_expectancy_bps,
            "profit_factor": current["profit_factor"],
            "hit_rate": medium.hit_rate,
            "max_drawdown_bps": medium.max_drawdown_bps,
            "cost_bps": medium.cost_bps,
            "positive_windows": float(medium.positive_windows),
            "window_count": float(medium.window_count),
        }

        # INSUFFICIENT_DATA is a first-class verdict: too few samples is never
        # "healthy" (§8, §29).
        if medium.sample_count < self.policy.min_samples:
            # Inactivity is still detectable with too few samples: a strategy
            # that emitted nothing across a full window is flagged, not merely
            # "unproven".
            early_flags: tuple[str, ...] = ()
            if (
                inputs.bar_count
                and inputs.bar_count >= self.policy.inactivity_samples
                and medium.sample_count == 0
            ):
                early_flags = (Flag.ABNORMAL_INACTIVITY,)
            return self._report(
                inputs,
                HealthState.INSUFFICIENT_DATA,
                0.0,
                early_flags,
                metrics,
                baseline,
                f"only {medium.sample_count} samples < min {self.policy.min_samples}",
            )

        flags: list[str] = []
        evidence: list[str] = []

        # Expectancy decay
        base_exp = baseline["net_expectancy_bps"]
        if base_exp > 0 and current["net_expectancy_bps"] < base_exp * (
            1.0 - self.policy.expectancy_decay_frac
        ):
            flags.append(Flag.EXPECTANCY_DECAY)
            evidence.append(
                f"expectancy {current['net_expectancy_bps']:.2f} < "
                f"{base_exp * (1 - self.policy.expectancy_decay_frac):.2f}"
            )

        # Profit-factor floor and deterioration
        pf = current["profit_factor"]
        base_pf = baseline["profit_factor"]
        if pf < self.policy.min_profit_factor:
            flags.append(Flag.PROFIT_FACTOR_DETERIORATION)
            evidence.append(f"profit_factor {pf:.2f} < floor {self.policy.min_profit_factor}")
        elif base_pf > 0 and pf < base_pf * (1.0 - self.policy.profit_factor_decay_frac):
            flags.append(Flag.PROFIT_FACTOR_DETERIORATION)
            evidence.append(f"profit_factor {pf:.2f} decayed from {base_pf:.2f}")

        # Hit-rate drift
        base_hr = baseline["hit_rate"]
        if (
            base_hr > 0
            and abs(current["hit_rate"] - base_hr) > self.policy.hit_rate_drift_frac * base_hr
        ):
            flags.append(Flag.HIT_RATE_DRIFT)
            evidence.append(f"hit_rate {current['hit_rate']:.2f} vs baseline {base_hr:.2f}")

        # Drawdown deterioration
        dd_delta = current["max_drawdown_bps"] - baseline["max_drawdown_bps"]
        if dd_delta > self.policy.drawdown_worsen_bps:
            flags.append(Flag.DRAWDOWN_DETERIORATION)
            evidence.append(f"drawdown +{dd_delta:.1f}bps vs baseline")

        # Cost sensitivity: cost eats most of the gross edge
        gross = current["gross_expectancy_bps"]
        if gross > 0 and (current["cost_bps"] / (gross + _EPS)) > self.policy.cost_sensitivity_frac:
            flags.append(Flag.COST_SENSITIVITY)
            evidence.append(
                f"cost {current['cost_bps']:.2f}bps is "
                f"{current['cost_bps'] / (gross + _EPS) * 100:.0f}% of gross edge"
            )

        # Slippage deterioration
        if (
            inputs.baseline_slippage_bps is not None
            and medium.slippage_bps is not None
            and medium.slippage_bps - inputs.baseline_slippage_bps > self.policy.slippage_worsen_bps
        ):
            flags.append(Flag.SLIPPAGE_DETERIORATION)
            evidence.append("slippage above baseline budget")

        # Regime mismatch: this cell is negative while the strategy is positive overall
        if medium.net_expectancy_bps < 0 <= long.net_expectancy_bps and long.sample_count > 0:
            flags.append(Flag.REGIME_MISMATCH)
            evidence.append(
                f"negative expectancy in regime {inputs.context.regime} "
                f"({medium.net_expectancy_bps:.2f}) despite long-window {long.net_expectancy_bps:.2f}"
            )

        # Loss clustering
        if self._loss_cluster(inputs.net_series) >= self.policy.loss_cluster_len:
            flags.append(Flag.LOSS_CLUSTERING)
            evidence.append(f"{self._loss_cluster(inputs.net_series)} consecutive losses")

        # Signal frequency drift / explosion, only when a bar denominator is known
        if inputs.bar_count and inputs.bar_count > 0:
            rate = medium.sample_count / inputs.bar_count
            base_rate = (
                long.sample_count / max(inputs.bar_count, long.sample_count) if long else rate
            )
            if base_rate > 0 and rate > base_rate * self.policy.signal_explosion_multiple:
                flags.append(Flag.ABNORMAL_SIGNAL_EXPLOSION)
                evidence.append(f"signal rate {rate:.3f} vs baseline {base_rate:.3f}")
            elif base_rate > 0 and rate < base_rate * (
                1.0 - self.policy.signal_frequency_drift_frac
            ):
                flags.append(Flag.SIGNAL_FREQUENCY_DRIFT)
                evidence.append(f"signal rate {rate:.3f} fell from {base_rate:.3f}")

        # Abnormal inactivity
        if (
            inputs.bar_count
            and inputs.bar_count >= self.policy.inactivity_samples
            and medium.sample_count == 0
        ):
            flags.append(Flag.ABNORMAL_INACTIVITY)
            evidence.append(f"no signals in {inputs.bar_count} bars")

        # Correlation increase
        if (
            inputs.max_pairwise_correlation is not None
            and inputs.max_pairwise_correlation >= self.policy.correlation_flag_threshold
        ):
            flags.append(Flag.CORRELATION_INCREASE)
            evidence.append(f"max pairwise correlation {inputs.max_pairwise_correlation:.2f}")

        score = max(0.0, 1.0 - sum(_FLAG_WEIGHTS.get(f, 0.1) for f in flags))
        state = self._state_for(score, current, flags)
        return self._report(inputs, state, score, tuple(flags), metrics, baseline, tuple(evidence))

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _loss_cluster(series: tuple[float, ...]) -> int:
        worst = 0
        run = 0
        for value in series:
            if value < 0:
                run += 1
                worst = max(worst, run)
            else:
                run = 0
        return worst

    def _state_for(self, score: float, current: dict[str, float], flags: list[str]) -> HealthState:
        pf = current["profit_factor"]
        exp = current["net_expectancy_bps"]
        if pf < self.policy.min_profit_factor and exp < 0:
            return HealthState.CRITICAL
        if score < 0.3:
            return HealthState.CRITICAL
        if score < 0.6 or Flag.DRAWDOWN_DETERIORATION in flags:
            return HealthState.DEGRADED
        if score < 0.85 or flags:
            return HealthState.WATCH
        return HealthState.HEALTHY

    def _report(
        self,
        inputs: HealthInputs,
        state: HealthState,
        score: float,
        flags: tuple[str, ...],
        metrics: dict[str, float],
        baseline: dict[str, float],
        evidence: Any,
    ) -> HealthReport:
        ev = evidence if isinstance(evidence, tuple) else (str(evidence),)
        return HealthReport(
            strategy_id=inputs.context.strategy_id,
            context=inputs.context,
            health_state=state,
            score=score,
            metrics=metrics,
            baseline=baseline,
            current={
                k: metrics.get(k, 0.0)
                for k in ("net_expectancy_bps", "profit_factor", "max_drawdown_bps")
            },
            degradation_flags=flags,
            evidence=ev,
            window="medium",
            timestamp_ms=inputs.now_ms,
        )
