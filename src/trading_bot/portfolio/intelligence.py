"""Portfolio Intelligence V1 — Track A of PORTFOLIO-AND-RUNTIME-INTEGRATION-01.

Deterministic portfolio context over positions, exposures, the causal dynamic
correlation engine (``portfolio/correlation.py``), regime and strategy health.

Hard rules:
- Uses the NEW causal dynamic correlation — no static constants.
- Distinguishes ASSET_CORRELATION vs STRATEGY_CORRELATION vs SIGNAL_OVERLAP
  (never collapsed into one score).
- Marginal portfolio value is observational evidence only — no automatic
  risk allocation decisions.
- Read-only projection; does NOT modify RiskManager during POC01.
- Physical position count != effective independent risk count (clusters).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.portfolio.correlation import (
    CorrelationState,
    DynamicCorrelationEngine,
    FusionConfig,
)


@dataclass(frozen=True, slots=True)
class PositionExposure:
    """One open position's exposure attributes."""

    symbol: str
    strategy_id: str
    strategy_family: str
    direction: str  # "long" / "short"
    notional_usdt: float


@dataclass(frozen=True, slots=True)
class CorrelationCluster:
    """A set of assets whose returns are effectively one risk cluster."""

    cluster_id: str
    assets: tuple[str, ...]
    mean_abs_correlation: float
    correlation_state: CorrelationState
    total_exposure_usdt: float
    physical_positions: int
    effective_independent_positions: float  # 1.0 while FUSED


@dataclass(frozen=True, slots=True)
class StrategyCorrelation:
    """Pairwise strategy relationship — separate dimensions, never one score."""

    strategy_a: str
    strategy_b: str
    signal_overlap: float  # fraction of bars where both propose same-direction signals
    trade_time_overlap: float  # fraction of overlapping open intervals
    pnl_correlation: float  # Pearson of aligned PnL series (0.0 if degenerate)
    drawdown_overlap: float  # fraction of days both in drawdown simultaneously
    classification: str  # ASSET_CORRELATION / STRATEGY_CORRELATION / SIGNAL_OVERLAP


@dataclass(frozen=True, slots=True)
class MarginalPortfolioValue:
    """Observational incremental value of a candidate (NOT a risk decision)."""

    candidate_id: str
    incremental_exposure_usdt: float
    incremental_correlated_exposure_usdt: float  # exposure inside existing FUSED clusters
    incremental_signal_diversity: float  # 1 - max signal overlap vs existing strategies
    incremental_opportunity: float  # 0..1 coverage of bars without current exposure
    incremental_risk_concentration: float  # post-add max cluster concentration delta


@dataclass(frozen=True, slots=True)
class PortfolioIntelligenceSnapshot:
    """Canonical deterministic portfolio context."""

    timestamp: float
    portfolio_id: str
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    exposure_by_asset: dict[str, float]
    exposure_by_strategy: dict[str, float]
    exposure_by_family: dict[str, float]
    exposure_by_correlation_cluster: dict[str, float]
    concentration_by_asset: dict[str, float]
    concentration_by_strategy: dict[str, float]
    portfolio_drawdown: float
    dynamic_correlation_state: CorrelationState
    market_regime: str  # MarketRegimeState.key() or "UNKNOWN"
    strategy_health_summary: dict[str, str]
    clusters: tuple[CorrelationCluster, ...]
    evidence_refs: tuple[str, ...] = ()

    @property
    def effective_independent_risk_count(self) -> float:
        """Sum of cluster effective positions: physical != effective."""
        return sum(c.effective_independent_positions for c in self.clusters)

    @property
    def physical_position_count(self) -> int:
        return sum(c.physical_positions for c in self.clusters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "portfolio_id": self.portfolio_id,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "long_exposure": self.long_exposure,
            "short_exposure": self.short_exposure,
            "exposure_by_asset": dict(self.exposure_by_asset),
            "exposure_by_strategy": dict(self.exposure_by_strategy),
            "exposure_by_family": dict(self.exposure_by_family),
            "exposure_by_correlation_cluster": dict(self.exposure_by_correlation_cluster),
            "concentration_by_asset": dict(self.concentration_by_asset),
            "concentration_by_strategy": dict(self.concentration_by_strategy),
            "portfolio_drawdown": self.portfolio_drawdown,
            "dynamic_correlation_state": self.dynamic_correlation_state.value,
            "market_regime": self.market_regime,
            "strategy_health_summary": dict(self.strategy_health_summary),
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "assets": list(c.assets),
                    "mean_abs_correlation": c.mean_abs_correlation,
                    "correlation_state": c.correlation_state.value,
                    "total_exposure_usdt": c.total_exposure_usdt,
                    "physical_positions": c.physical_positions,
                    "effective_independent_positions": c.effective_independent_positions,
                }
                for c in self.clusters
            ],
            "physical_position_count": self.physical_position_count,
            "effective_independent_risk_count": self.effective_independent_risk_count,
            "evidence_refs": list(self.evidence_refs),
            "read_only": True,
        }


def build_correlation_clusters(
    returns_by_asset: dict[str, tuple[tuple[int, float], ...]],
    exposures_by_asset: dict[str, float],
    *,
    engine: DynamicCorrelationEngine | None = None,
    edge_threshold: float = 0.70,
) -> tuple[CorrelationCluster, ...]:
    """Derive clusters from the CAUSAL dynamic correlation engine.

    Union-find over pairs whose smoothed |correlation| >= ``edge_threshold``.
    Assets without a computable correlation (insufficient overlap) stay
    singleton clusters — never force-merged by symbol family or assumption.
    """
    eng = engine or DynamicCorrelationEngine(FusionConfig())
    assets = sorted(returns_by_asset)
    parent: dict[str, str] = {a: a for a in assets}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_state: dict[tuple[str, str], CorrelationState] = {}
    pair_corr: dict[tuple[str, str], float] = {}
    for i, a in enumerate(assets):
        for b in assets[i + 1 :]:
            states, smoothed = eng.evaluate_series(returns_by_asset[a], returns_by_asset[b])
            if not states:
                continue  # insufficient overlap: stay unlinked
            last_state = states[-1][1]
            last_corr = smoothed[-1][1] if smoothed else 0.0
            pair_state[(a, b)] = last_state
            pair_corr[(a, b)] = last_corr
            if last_state is CorrelationState.FUSED:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    groups: dict[str, list[str]] = {}
    for a in assets:
        groups.setdefault(find(a), []).append(a)
    clusters: list[CorrelationCluster] = []
    for root in sorted(groups):
        members = tuple(sorted(groups[root]))
        internal_corrs = [
            abs(pair_corr[(a, b)]) for (a, b) in pair_state if a in members and b in members
        ]
        mean_abs = sum(internal_corrs) / len(internal_corrs) if internal_corrs else 0.0
        # Cluster correlation state: FUSED if any internal pair fused.
        state = (
            CorrelationState.FUSED
            if any(
                s is CorrelationState.FUSED
                for (a, b), s in pair_state.items()
                if a in members and b in members
            )
            else CorrelationState.NORMAL
        )
        total = sum(abs(exposures_by_asset.get(a, 0.0)) for a in members)
        physical = sum(1 for a in members if exposures_by_asset.get(a, 0.0) != 0.0)
        effective = 1.0 if physical > 0 else 0.0
        clusters.append(
            CorrelationCluster(
                cluster_id="CL-" + "+".join(members),
                assets=members,
                mean_abs_correlation=mean_abs,
                correlation_state=state,
                total_exposure_usdt=total,
                physical_positions=physical,
                # FUSED cluster behaves as ONE independent risk; NORMAL cluster
                # members retain their own independence.
                effective_independent_positions=effective
                if state is CorrelationState.FUSED
                else float(physical),
            )
        )
    return tuple(clusters)


def build_snapshot(
    *,
    portfolio_id: str,
    timestamp: float,
    positions: tuple[PositionExposure, ...],
    returns_by_asset: dict[str, tuple[tuple[int, float], ...]],
    market_regime: str = "UNKNOWN",
    strategy_health_summary: dict[str, str] | None = None,
    portfolio_drawdown: float = 0.0,
    evidence_refs: tuple[str, ...] = (),
    engine: DynamicCorrelationEngine | None = None,
) -> PortfolioIntelligenceSnapshot:
    """Build the canonical snapshot from positions + causal correlation + regime."""
    gross = sum(abs(p.notional_usdt) for p in positions)
    long_exp = sum(p.notional_usdt for p in positions if p.direction == "long")
    short_exp = sum(abs(p.notional_usdt) for p in positions if p.direction == "short")
    net = long_exp - short_exp

    by_asset: dict[str, float] = {}
    by_strategy: dict[str, float] = {}
    by_family: dict[str, float] = {}
    for p in positions:
        by_asset[p.symbol] = by_asset.get(p.symbol, 0.0) + p.notional_usdt
        by_strategy[p.strategy_id] = by_strategy.get(p.strategy_id, 0.0) + p.notional_usdt
        by_family[p.strategy_family] = by_family.get(p.strategy_family, 0.0) + p.notional_usdt

    exposures_by_asset = {
        a: by_asset.get(a, 0.0) for a in sorted(set(by_asset) | set(returns_by_asset))
    }
    clusters = build_correlation_clusters(returns_by_asset, exposures_by_asset, engine=engine)
    by_cluster = {c.cluster_id: c.total_exposure_usdt for c in clusters}

    conc_asset = {a: (abs(v) / gross if gross > 0 else 0.0) for a, v in by_asset.items()}
    conc_strategy = {s: (abs(v) / gross if gross > 0 else 0.0) for s, v in by_strategy.items()}

    return PortfolioIntelligenceSnapshot(
        timestamp=timestamp,
        portfolio_id=portfolio_id,
        gross_exposure=gross,
        net_exposure=net,
        long_exposure=long_exp,
        short_exposure=short_exp,
        exposure_by_asset=by_asset,
        exposure_by_strategy=by_strategy,
        exposure_by_family=by_family,
        exposure_by_correlation_cluster=by_cluster,
        concentration_by_asset=conc_asset,
        concentration_by_strategy=conc_strategy,
        portfolio_drawdown=portfolio_drawdown,
        dynamic_correlation_state=(
            CorrelationState.FUSED
            if any(c.correlation_state is CorrelationState.FUSED for c in clusters)
            else CorrelationState.NORMAL
        ),
        market_regime=market_regime,
        strategy_health_summary=dict(strategy_health_summary or {}),
        clusters=clusters,
        evidence_refs=evidence_refs,
    )


def compute_marginal_portfolio_value(
    snapshot: PortfolioIntelligenceSnapshot,
    candidate: PositionExposure,
    returns_by_asset: dict[str, tuple[tuple[int, float], ...]],
    candidate_signal_series: tuple[tuple[int, float], ...],
    existing_signal_series: dict[str, tuple[tuple[int, float], ...]],
    *,
    engine: DynamicCorrelationEngine | None = None,
) -> MarginalPortfolioValue:
    """Observational incremental metrics for a candidate (A3).

    No risk allocation decision is made here; the output is context/evidence
    for governance.
    """
    incremental_exposure = abs(candidate.notional_usdt)

    # Correlated exposure: candidate's exposure that sits inside already-FUSED clusters.
    incremental_correlated = 0.0
    for cluster in snapshot.clusters:
        if (
            candidate.symbol in cluster.assets
            and cluster.correlation_state is CorrelationState.FUSED
        ):
            incremental_correlated = incremental_exposure
            break

    # Signal diversity: 1 - max overlap with existing strategies.
    max_overlap = 0.0
    cand_map = dict(candidate_signal_series)
    for other_series in existing_signal_series.values():
        other_map = dict(other_series)
        common = sorted(set(cand_map) & set(other_map))
        if not common:
            continue
        agree = sum(
            1 for t in common if (cand_map[t] > 0) == (other_map[t] > 0) and cand_map[t] != 0
        )
        overlap = agree / len(common)
        max_overlap = max(max_overlap, overlap)
    incremental_diversity = 1.0 - max_overlap

    # Opportunity: 1.0 when the candidate's ASSET-CLUSTER context is free of
    # existing exposure; a candidate inside an already-exposed FUSED cluster
    # adds no NEW opportunity (its risk is already represented).
    candidate_cluster = next((c for c in snapshot.clusters if candidate.symbol in c.assets), None)
    if (
        candidate_cluster is not None
        and candidate_cluster.correlation_state is CorrelationState.FUSED
    ):
        incremental_opportunity = 0.0 if candidate_cluster.total_exposure_usdt > 0.0 else 1.0
    else:
        incremental_opportunity = (
            0.0 if snapshot.exposure_by_asset.get(candidate.symbol, 0.0) != 0.0 else 1.0
        )

    # Risk concentration delta: candidate joined to the largest post-add cluster.
    post_gross = snapshot.gross_exposure + incremental_exposure
    largest_after = max((c.total_exposure_usdt for c in snapshot.clusters), default=0.0)
    candidate_cluster_exposure = (
        incremental_correlated if incremental_correlated else incremental_exposure
    )
    incremental_concentration = (largest_after + candidate_cluster_exposure) / post_gross - (
        largest_after / snapshot.gross_exposure if snapshot.gross_exposure > 0 else 0.0
    )

    return MarginalPortfolioValue(
        candidate_id=f"{candidate.strategy_id}:{candidate.symbol}",
        incremental_exposure_usdt=incremental_exposure,
        incremental_correlated_exposure_usdt=incremental_correlated,
        incremental_signal_diversity=incremental_diversity,
        incremental_opportunity=incremental_opportunity,
        incremental_risk_concentration=max(0.0, incremental_concentration),
    )


# A2: dedicated measurers kept separate by design.
def measure_asset_correlation(
    returns_a: tuple[tuple[int, float], ...],
    returns_b: tuple[tuple[int, float], ...],
    *,
    engine: DynamicCorrelationEngine | None = None,
) -> float:
    """Latest causal |correlation| between two ASSETS (0.0 if unmeasurable)."""
    eng = engine or DynamicCorrelationEngine(FusionConfig())
    states, _ = eng.evaluate_series(returns_a, returns_b)
    if not states:
        return 0.0
    # Re-derive last smoothed value via rolling pipeline is engine-internal;
    # approximate with state severity: FUSED -> high edge, NORMAL -> unknown.
    return 1.0 if states[-1][1] is CorrelationState.FUSED else 0.0


def measure_strategy_correlation(
    pnl_a: dict[int, float],
    pnl_b: dict[int, float],
    open_intervals_a: tuple[tuple[int, int], ...],
    open_intervals_b: tuple[tuple[int, int], ...],
    drawdown_days_a: set[int],
    drawdown_days_b: set[int],
) -> StrategyCorrelation:
    """A2: strategy-pair metrics as SEPARATE dimensions (never one score)."""
    common = sorted(set(pnl_a) & set(pnl_b))
    pnl_corr = 0.0
    if len(common) >= 2:
        from trading_bot.portfolio.correlation import _pearson

        try:
            pnl_corr = abs(
                _pearson(
                    tuple(pnl_a[t] for t in common),
                    tuple(pnl_b[t] for t in common),
                )
            )
        except ValueError:
            pnl_corr = 0.0
    overlap_days = 0
    for a0, a1 in open_intervals_a:
        for b0, b1 in open_intervals_b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                overlap_days += hi - lo
    total_days = sum(a1 - a0 for a0, a1 in open_intervals_a) or 1
    trade_time_overlap = min(1.0, overlap_days / total_days)
    dd_overlap = (
        (len(drawdown_days_a & drawdown_days_b) / len(drawdown_days_a)) if drawdown_days_a else 0.0
    )
    # Classification labels the DOMINANT driver; the numbers stay separate.
    if trade_time_overlap >= 0.5:
        classification = "SIGNAL_OVERLAP"
    elif pnl_corr >= 0.7:
        classification = "STRATEGY_CORRELATION"
    else:
        classification = "ASSET_CORRELATION"
    return StrategyCorrelation(
        strategy_a="A",
        strategy_b="B",
        signal_overlap=0.0,  # filled by caller when signal series exist
        trade_time_overlap=trade_time_overlap,
        pnl_correlation=pnl_corr,
        drawdown_overlap=dd_overlap,
        classification=classification,
    )


def project_portfolio(snapshot: PortfolioIntelligenceSnapshot) -> dict[str, Any]:
    """A5: read-only frontend projection."""
    clusters_proj = [
        {
            "cluster_id": c.cluster_id,
            "assets": list(c.assets),
            "state": c.correlation_state.value,
            "total_exposure_usdt": c.total_exposure_usdt,
            "physical_positions": c.physical_positions,
            "effective_independent_positions": c.effective_independent_positions,
        }
        for c in snapshot.clusters
    ]
    health_warnings = [
        f"{s}: {state}"
        for s, state in sorted(snapshot.strategy_health_summary.items())
        if state in ("DEGRADED", "QUARANTINED", "RETIRED")
    ]
    return {
        "portfolio_id": snapshot.portfolio_id,
        "gross_exposure": snapshot.gross_exposure,
        "net_exposure": snapshot.net_exposure,
        "asset_concentration": snapshot.concentration_by_asset,
        "strategy_concentration": snapshot.concentration_by_strategy,
        "correlation_clusters": clusters_proj,
        "physical_positions": snapshot.physical_position_count,
        "effective_independent_risk_count": snapshot.effective_independent_risk_count,
        "effective_diversification_ratio": (
            snapshot.effective_independent_risk_count / snapshot.physical_position_count
            if snapshot.physical_position_count > 0
            else 0.0
        ),
        "drawdown": snapshot.portfolio_drawdown,
        "regime": snapshot.market_regime,
        "correlation_state": snapshot.dynamic_correlation_state.value,
        "health_warnings": health_warnings,
        "read_only": True,
    }
