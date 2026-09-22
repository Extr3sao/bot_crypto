"""LEGACY-RETRO-VALIDATION-01 — preregistered legacy strategy retro-validation.

SHADOW-AND-LEGACY-VALIDATION-01 (Track C). Evaluates the five legacy
runtime strategies (momentum, trend, breakout, mean_reversion, volatility)
under an EX-ANTE frozen protocol, before any results are observed:

- **C1**: :class:`LegacyRetroProtocol` freezes assets, timeframes,
  applicability, cost model, thresholds, minimum N, regime methodology and
  holdout policy. Its ``fingerprint`` (SHA-256 of the canonical JSON) must
  be recorded with results so any post-hoc change is detectable.
- **C2**: matrix Strategy x Asset x Timeframe x Regime with
  VALIDATED_CELL / FAILED_CELL / INSUFFICIENT_SAMPLE / NOT_APPLICABLE.
- **C3**: modern gates composed of existing stat-validation primitives
  (bootstrap Sharpe CI, P(Sharpe > 0), permutation significance). No single
  statistic can certify — all preregistered gates must pass together.
- **C4**: per valid cell, health baselines (expectancy, Sharpe, PF,
  drawdown, trade frequency) with sample N + window fingerprint + regime
  binding — never from active POC01 partial results.
- **C5**: evidence only. Nothing here touches POC01, RiskManager,
  PaperBroker, or any runtime authority.

Data is PIT: callers supply trade-return series; the harness never mutates,
reorders, or forward-fills observations.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from trading_bot.backtesting.stat_validation import (
    bootstrap_sharpe_ci,
    permutation_significance,
)

__all__ = [
    "LEGACY_STRATEGIES",
    "CellMetrics",
    "CellStatus",
    "CellVerdict",
    "HealthBaseline",
    "LegacyRetroHarness",
    "LegacyRetroProtocol",
    "protocol_fingerprint",
]

LEGACY_STRATEGIES: tuple[str, ...] = (
    "momentum",
    "trend",
    "breakout",
    "mean_reversion",
    "volatility",
)

#: Preregistered significance-test parameters (declared before execution).
PERMUTATION_ROUNDS = 500
STAT_SEED = 20260909
BOOTSTRAP_RESAMPLES = 500


class CellStatus:
    """Canonical cell classifications (C2)."""

    VALIDATED_CELL = "VALIDATED_CELL"
    FAILED_CELL = "FAILED_CELL"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (
            cls.VALIDATED_CELL,
            cls.FAILED_CELL,
            cls.INSUFFICIENT_SAMPLE,
            cls.NOT_APPLICABLE,
        )


@dataclass(frozen=True, slots=True)
class LegacyRetroProtocol:
    """EX-ANTE frozen protocol (C1). Immutable; fingerprint on demand."""

    name: str
    frozen_at_utc: str
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    applicability: dict[str, tuple[str, ...]]  # strategy -> assets it applies to
    directions: tuple[str, ...]
    commission_rate: float
    slippage_bps: float
    min_trades_per_cell: int
    min_sharpe: float
    min_expectancy: float
    max_pvalue: float
    confidence_level: float
    regime_method: str
    use_walk_forward: bool
    use_purged_cv: bool
    holdout_fraction: float
    holdout_policy: str
    acceptance_thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "name": self.name,
                "frozen_at_utc": self.frozen_at_utc,
                "assets": list(self.assets),
                "timeframes": list(self.timeframes),
                "applicability": {k: list(v) for k, v in sorted(self.applicability.items())},
                "directions": list(self.directions),
                "commission_rate": self.commission_rate,
                "slippage_bps": self.slippage_bps,
                "min_trades_per_cell": self.min_trades_per_cell,
                "min_sharpe": self.min_sharpe,
                "min_expectancy": self.min_expectancy,
                "max_pvalue": self.max_pvalue,
                "confidence_level": self.confidence_level,
                "regime_method": self.regime_method,
                "use_walk_forward": self.use_walk_forward,
                "use_purged_cv": self.use_purged_cv,
                "holdout_fraction": self.holdout_fraction,
                "holdout_policy": self.holdout_policy,
                "acceptance_thresholds": dict(sorted(self.acceptance_thresholds.items())),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def protocol_fingerprint(protocol: LegacyRetroProtocol) -> str:
    return protocol.fingerprint


@dataclass(frozen=True, slots=True)
class CellMetrics:
    """Backtest + statistical evidence for one matrix cell."""

    n_trades: int
    expectancy: float  # mean return per trade (decimal)
    profit_factor: float | None
    sharpe: float  # per-trade (non-annualized) Sharpe of the return series
    max_drawdown: float
    win_rate: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    prob_sharpe_gt0: float
    permutation_pvalue: float
    window_fingerprint: str


@dataclass(frozen=True, slots=True)
class CellVerdict:
    """One Strategy x Asset x Timeframe x Regime cell result."""

    strategy_id: str
    asset: str
    timeframe: str
    regime: str
    status: str
    metrics: CellMetrics | None
    reason: str
    regime_binding: str
    protocol_fingerprint: str


@dataclass(frozen=True, slots=True)
class HealthBaseline:
    """C4 — future health baseline bound to one valid cell."""

    strategy_id: str
    asset: str
    timeframe: str
    regime: str
    baseline_expectancy: float
    baseline_sharpe: float
    baseline_profit_factor: float | None  # None when no losses in window
    baseline_drawdown: float
    baseline_trade_frequency: float  # trades per 100 bars (set by caller)
    sample_n: int
    window_fingerprint: str
    protocol_fingerprint: str


def _window_fingerprint(returns: Sequence[float]) -> str:
    canonical = json.dumps([round(r, 10) for r in returns], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _per_trade_sharpe(rets: Sequence[float]) -> float:
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    std = math.sqrt(var)
    if std <= 0:
        return 0.0
    return mean / std


def _cell_metrics_from_returns(
    returns: Sequence[float],
    *,
    n_trades: int,
    confidence: float,
) -> CellMetrics:
    rets = tuple(returns)
    n = len(rets)
    mean = sum(rets) / n
    sharpe = _per_trade_sharpe(rets)
    gross_win = sum(r for r in rets if r > 0)
    gross_loss = sum(-r for r in rets if r < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    wins = sum(1 for r in rets if r > 0)

    # Equity-curve max drawdown (multiplicative, PIT order).
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

    ci = bootstrap_sharpe_ci(
        rets,
        resamples=BOOTSTRAP_RESAMPLES,
        confidence=confidence,
        seed=STAT_SEED,
        periods_per_year=1,  # per-trade returns: no annualization
    )
    perm = permutation_significance(
        rets,
        permutations=PERMUTATION_ROUNDS,
        seed=STAT_SEED,
        periods_per_year=1,
    )

    return CellMetrics(
        n_trades=n_trades,
        expectancy=mean,
        profit_factor=pf,
        sharpe=sharpe,
        max_drawdown=max_dd,
        win_rate=wins / n,
        sharpe_ci_low=ci.ci_lower,
        sharpe_ci_high=ci.ci_upper,
        prob_sharpe_gt0=ci.prob_sharpe_positive,
        permutation_pvalue=perm.p_value,
        window_fingerprint=_window_fingerprint(rets),
    )


class LegacyRetroHarness:
    """Deterministic, preregistered evaluation harness (C2/C3/C4)."""

    def __init__(self, protocol: LegacyRetroProtocol) -> None:
        self._protocol = protocol

    @property
    def protocol(self) -> LegacyRetroProtocol:
        return self._protocol

    def evaluate_cell(
        self,
        *,
        strategy_id: str,
        asset: str,
        timeframe: str,
        regime: str,
        trade_returns: Sequence[float],
        n_trades: int | None = None,
        regime_binding: str = "exact",
    ) -> CellVerdict:
        """Evaluate one cell from PIT trade returns under the frozen protocol.

        ``regime_binding`` must be ``exact`` or ``declared_fallback`` — a
        pre-declared broader regime class declared BEFORE seeing results.
        Opportunistic post-hoc merging is never accepted (the caller must
        label the binding used, and only pre-declared fallbacks are legal).
        """
        protocol = self._protocol
        fp = protocol.fingerprint

        def _verdict(status: str, reason: str, metrics: CellMetrics | None = None) -> CellVerdict:
            return CellVerdict(
                strategy_id=strategy_id,
                asset=asset,
                timeframe=timeframe,
                regime=regime,
                status=status,
                metrics=metrics,
                reason=reason,
                regime_binding=regime_binding,
                protocol_fingerprint=fp,
            )

        # Applicability: declared ex-ante, never inferred from results.
        applies = protocol.applicability.get(strategy_id)
        if applies is None or asset not in applies:
            return _verdict(
                CellStatus.NOT_APPLICABLE,
                "asset not in preregistered applicability for strategy",
            )
        if timeframe not in protocol.timeframes:
            return _verdict(CellStatus.NOT_APPLICABLE, "timeframe not in preregistered set")
        if regime_binding not in {"exact", "declared_fallback"}:
            return _verdict(
                CellStatus.NOT_APPLICABLE,
                "regime binding must be 'exact' or pre-declared 'declared_fallback'",
            )

        returns = list(trade_returns)
        if len(returns) < protocol.min_trades_per_cell:
            return _verdict(
                CellStatus.INSUFFICIENT_SAMPLE,
                f"n={len(returns)} < preregistered minimum {protocol.min_trades_per_cell}",
            )

        metrics = _cell_metrics_from_returns(
            returns,
            n_trades=n_trades if n_trades is not None else len(returns),
            confidence=protocol.confidence_level,
        )

        # No single statistic can certify: all gates must pass together.
        gates = {
            "expectancy": metrics.expectancy >= protocol.min_expectancy,
            "sharpe": metrics.sharpe >= protocol.min_sharpe,
            "ci_excludes_negative": (metrics.sharpe_ci_high > 0 and metrics.prob_sharpe_gt0 >= 0.5),
            "significance": metrics.permutation_pvalue < protocol.max_pvalue,
        }
        passed = all(gates.values())
        reason = (
            "all preregistered gates passed"
            if passed
            else "failed gates: " + ",".join(g for g, ok in gates.items() if not ok)
        )
        return _verdict(
            CellStatus.VALIDATED_CELL if passed else CellStatus.FAILED_CELL,
            reason,
            metrics,
        )

    def evaluate_matrix(
        self,
        cells: Iterable[dict[str, Any]],
        *,
        trade_returns_for: Callable[[dict[str, Any]], Sequence[float]],
    ) -> list[CellVerdict]:
        """Evaluate many cells; rows carry identity + regime binding."""
        verdicts: list[CellVerdict] = []
        for row in cells:
            verdicts.append(
                self.evaluate_cell(
                    strategy_id=row["strategy_id"],
                    asset=row["asset"],
                    timeframe=row["timeframe"],
                    regime=row["regime"],
                    trade_returns=trade_returns_for(row),
                    regime_binding=row.get("regime_binding", "exact"),
                )
            )
        return verdicts

    def baselines_from_valid_cells(
        self,
        verdicts: Sequence[CellVerdict],
        *,
        bars_per_cell: dict[tuple[str, str, str, str], int] | None = None,
    ) -> list[HealthBaseline]:
        """C4: baselines ONLY from VALIDATED cells (evidence-backed).

        ``bars_per_cell`` optionally supplies bar counts to compute the
        trade-frequency baseline (trades per 100 bars).
        """
        baselines: list[HealthBaseline] = []
        for v in verdicts:
            if v.status != CellStatus.VALIDATED_CELL or v.metrics is None:
                continue
            m = v.metrics
            key = (v.strategy_id, v.asset, v.timeframe, v.regime)
            freq = 0.0
            if bars_per_cell and bars_per_cell.get(key):
                freq = m.n_trades * 100.0 / bars_per_cell[key]
            baselines.append(
                HealthBaseline(
                    strategy_id=v.strategy_id,
                    asset=v.asset,
                    timeframe=v.timeframe,
                    regime=v.regime,
                    baseline_expectancy=m.expectancy,
                    baseline_sharpe=m.sharpe,
                    baseline_profit_factor=m.profit_factor,
                    baseline_drawdown=m.max_drawdown,
                    baseline_trade_frequency=freq,
                    sample_n=m.n_trades,
                    window_fingerprint=m.window_fingerprint,
                    protocol_fingerprint=v.protocol_fingerprint,
                )
            )
        return baselines
