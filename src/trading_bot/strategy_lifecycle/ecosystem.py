"""DynamicStrategyEcosystem — the composition root for the dynamic plane.

Wires registry + performance + health + lifecycle + portfolio + champion
together so an experiment, a report or a test can drive them without glue code.
It performs NO execution and holds NO risk authority: the only thing it can
hand back is eligibility and lifecycle decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from .champion import ChallengerEvaluation, ChampionChallenger, ComparisonResult
from .config import DEFAULT_HEALTH_POLICY, DEFAULT_LIFECYCLE_POLICY, HealthPolicy, LifecyclePolicy
from .contracts import (
    ContextKey,
    HealthReport,
    LifecycleDecision,
    PerformanceCell,
    PortfolioDecision,
    StrategyDescriptor,
)
from .health import HealthInputs, StrategyHealthMonitor
from .lifecycle import ControllerInputs, StrategyLifecycleController
from .performance import ContextualPerformanceStore, PerformanceObservation
from .portfolio import PortfolioProposal, StrategyPortfolioManager
from .registry import DynamicStrategyRegistry

__all__ = ["ECOSYSTEM_VERSION", "DynamicStrategyEcosystem"]

ECOSYSTEM_VERSION: Final[str] = "dynamic-strategy-ecosystem-v1"


@dataclass(slots=True)
class DynamicStrategyEcosystem:
    """Deterministic composition of the dynamic strategy components."""

    registry: DynamicStrategyRegistry = field(default_factory=DynamicStrategyRegistry)
    performance: ContextualPerformanceStore = field(default_factory=ContextualPerformanceStore)
    lifecycle_policy: LifecyclePolicy = DEFAULT_LIFECYCLE_POLICY
    health_policy: HealthPolicy = DEFAULT_HEALTH_POLICY
    monitor: StrategyHealthMonitor | None = None
    controller: StrategyLifecycleController | None = None
    portfolio: StrategyPortfolioManager | None = None
    champion: ChampionChallenger | None = None
    _health: dict[str, str] = field(default_factory=dict, repr=False)
    version: str = ECOSYSTEM_VERSION

    def __post_init__(self) -> None:
        # DEF-VERIFY-004: windowing is owned by the ContextualPerformanceStore
        # (single owner). HealthPolicy no longer carries a duplicate, inert
        # `windows` field, so health resolution cannot silently disagree with
        # the configured window sizes.
        if self.monitor is None:
            self.monitor = StrategyHealthMonitor(policy=self.health_policy)
        if self.controller is None:
            self.controller = StrategyLifecycleController(policy=self.lifecycle_policy)
        if self.portfolio is None:
            self.portfolio = StrategyPortfolioManager()
        if self.champion is None:
            self.champion = ChampionChallenger()

    # -- registration / observation ----------------------------------------

    def register(self, descriptor: StrategyDescriptor) -> StrategyDescriptor:
        return self.registry.register(descriptor)

    def observe(self, observation: PerformanceObservation) -> PerformanceObservation:
        return self.performance.record(observation)

    # -- health / lifecycle -------------------------------------------------

    def health_for(
        self,
        *,
        strategy_id: str,
        asset: str,
        timeframe: str,
        regime: str,
        now_ms: int,
        bar_count: int | None = None,
        baseline_slippage_bps: float | None = None,
        max_pairwise_correlation: float | None = None,
    ) -> HealthReport:
        key = ContextKey(strategy_id, asset, timeframe, regime)
        cells = self.performance.cells(key)
        obs = self.performance.observations(key)
        inputs = HealthInputs(
            context=key,
            cells=cells,
            now_ms=now_ms,
            bar_count=bar_count,
            net_series=tuple(o.net_bps for o in obs),
            baseline_slippage_bps=baseline_slippage_bps,
            max_pairwise_correlation=max_pairwise_correlation,
        )
        assert self.monitor is not None
        report = self.monitor.evaluate(inputs)
        self.registry.observe_health(strategy_id, report.health_state)
        self._health[strategy_id] = report.health_state.value
        return report

    def lifecycle_decision(
        self,
        *,
        strategy_id: str,
        asset: str,
        timeframe: str,
        regime: str,
        now_ms: int,
        verification_passed: bool = False,
        advisory_proposed_state: str | None = None,
    ) -> LifecycleDecision:
        descriptor = self.registry.descriptor(strategy_id)
        if descriptor is None:
            raise KeyError(f"{strategy_id} is not registered")
        key = ContextKey(strategy_id, asset, timeframe, regime)
        cells = self.performance.cells(key)
        regime_cell = self.performance.cell(key, "medium")
        streaks = self.registry.streaks(strategy_id)
        inputs = ControllerInputs(
            descriptor=descriptor,
            context=key,
            cells=cells,
            health=self.health_for(
                strategy_id=strategy_id,
                asset=asset,
                timeframe=timeframe,
                regime=regime,
                now_ms=now_ms,
            ),
            now_ms=now_ms,
            regime_cell=regime_cell,
            verification_passed=verification_passed,
            degraded_streak=streaks["degraded_streak"],
            recovery_streak=streaks["recovery_streak"],
            last_activation_ms=streaks["last_activation_ms"],
            eligible_since_ms=streaks["eligible_since_ms"],
            last_demotion_ms=streaks["last_demotion_ms"],
            advisory_proposed_state=advisory_proposed_state,
        )
        assert self.controller is not None
        decision = self.controller.evaluate(inputs)
        if decision.changed:
            self.registry.apply(decision)
        return decision

    # -- champion / challenger ---------------------------------------------

    def compare_champion(
        self,
        *,
        asset: str,
        timeframe: str,
        regime: str,
        champion_id: str,
        challenger_ids: list[str],
        now_ms: int,
    ) -> ComparisonResult:
        key = ContextKey(champion_id, asset, timeframe, regime)
        champ_cell = self.performance.cell(key, "medium")
        champ = ChallengerEvaluation(
            strategy_id=champion_id,
            sample_count=champ_cell.sample_count,
            net_expectancy_bps=champ_cell.net_expectancy_bps,
            profit_factor=champ_cell.profit_factor,
            max_drawdown_bps=champ_cell.max_drawdown_bps,
            window_net_bps=self._window_sums(champion_id, asset, timeframe, regime),
        )
        challengers = []
        for cid in challenger_ids:
            ckey = ContextKey(cid, asset, timeframe, regime)
            cell = self.performance.cell(ckey, "medium")
            challengers.append(
                ChallengerEvaluation(
                    strategy_id=cid,
                    sample_count=cell.sample_count,
                    net_expectancy_bps=cell.net_expectancy_bps,
                    profit_factor=cell.profit_factor,
                    max_drawdown_bps=cell.max_drawdown_bps,
                    window_net_bps=self._window_sums(cid, asset, timeframe, regime),
                )
            )
        assert self.champion is not None
        return self.champion.compare(
            context=key,
            champion=champ,
            challengers=challengers,
            timestamp_ms=now_ms,
        )

    def _window_sums(
        self, strategy_id: str, asset: str, timeframe: str, regime: str
    ) -> tuple[float, ...]:
        key = ContextKey(strategy_id, asset, timeframe, regime)
        obs = self.performance.observations(key)
        if not obs:
            return ()
        size = max(1, self.performance.window_size("short"))
        parts: list[float] = []
        for i in range(0, len(obs), size):
            parts.append(sum(o.net_bps for o in obs[i : i + size]))
        return tuple(parts)

    # -- routing ------------------------------------------------------------

    def lifecycle_map(self, strategy_ids: list[str] | None = None) -> dict[str, str]:
        ids = strategy_ids if strategy_ids is not None else self.registry.strategy_ids()
        out: dict[str, str] = {}
        for sid in ids:
            state = self.registry.state_of(sid)
            if state is not None:
                out[sid] = state.value
        return out

    def select_eligible(
        self,
        router: Any,
        *,
        context: Any,
        regime: str | None,
        strategy_map: dict[str, dict[str, Any]],
        asset: str | None = None,
        timeframe: str | None = None,
        regime_key: str | None = None,
        min_expectancy_bps: float | None = None,
        risk_blocked: frozenset[str] | set[str] = frozenset(),
        portfolio_rejected: frozenset[str] | set[str] = frozenset(),
    ) -> Any:
        """Delegate to :meth:`StrategyRouter.select_eligible_strategies`."""
        lifecycle = self.lifecycle_map(list(strategy_map))
        health: dict[str, str] = {}
        performance: dict[str, float] = {}
        asset = str(asset or getattr(context, "asset", "") or "")
        timeframe = str(timeframe or getattr(context, "timeframe", "") or "")
        regime_key = str(regime_key or (regime or ""))
        for sid in strategy_map:
            key = ContextKey(sid, asset, timeframe, regime_key)
            cell: PerformanceCell = self.performance.cell(key, "medium")
            if cell.sample_count:
                performance[sid] = cell.net_expectancy_bps
            if sid in self._health:
                health[sid] = self._health[sid]
        return router.select_eligible_strategies(
            context,
            regime,
            strategy_map,
            lifecycle=lifecycle,
            health=health,
            performance=performance,
            min_expectancy_bps=min_expectancy_bps,
            risk_blocked=risk_blocked,
            portfolio_rejected=portfolio_rejected,
        )

    # -- portfolio ----------------------------------------------------------

    def arbitrate(
        self, proposals: list[PortfolioProposal], *, timestamp_ms: int = 0
    ) -> PortfolioDecision:
        assert self.portfolio is not None
        return self.portfolio.arbitrate(proposals, timestamp_ms=timestamp_ms)

    # -- snapshots ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "registry": self.registry.as_dict(),
            "churn": self.registry.churn(),
        }
