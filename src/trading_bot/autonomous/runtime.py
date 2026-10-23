"""Autonomous PAPER/SHADOW runtime — the full executable path (§2/§13).

One cycle, per asset:

    REAL PUBLIC MARKET DATA → validation → MarketContext/AssetContext →
    Regime → StrategyRegistry/StrategyRouter → TradeProposal →
    multi-agent review → IndependentVerifier → DecisionEngine →
    deterministic Risk → TRADE_PAPER / SHADOW_TRADE / NO_TRADE →
    DecisionTrace → reconciliation → outcome evaluation → performance update

Composition rules:

* the scanner, the PIT history reader, the asset registry, the router, the
  families, the RiskManager and the PaperBroker are the CANONICAL components
  of the paper runtime — this module adds the decision/verification/learning
  layer, it does not replace any of them;
* I/O happens once per cycle (ingest phase). Everything after that is a
  deterministic function of the ingested, already-PIT-sliced data;
* no order can be created without passing the admission ledger, the verifier
  and the deterministic RiskManager, in that order;
* SHADOW_TRADE never touches the broker.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.signal_adapter import AdapterError, alpha_signal_to_signal
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import RouterGates, StrategyRouter
from trading_bot.strategy_lifecycle.portfolio import (
    PortfolioProposal,
    StrategyPortfolioManager,
)
from trading_bot.strategy_lifecycle.runtime_bridge import (
    LifecycleRoutingAdapter,
    StrategyRoutingComparison,
    StrategyRoutingMode,
    coerce_routing_mode,
)

from .admission_ledger import AdmissionLedger
from .agents import AgentRegistry, ReviewInputs, default_agent_registry
from .contracts import (
    AgentMessage,
    CostBreakdown,
    DecisionMode,
    DecisionTrace,
    EdgeEvidence,
    NoTradeKind,
    OutcomeStatus,
    RiskReview,
    RiskState,
    RiskVerdict,
    RuntimeFailureKind,
    TradeProposal,
    VerificationResult,
    VerifierVerdict,
)
from .costs import COST_MODEL_VERSION, CostEngine
from .decision import DecisionEngine, DecisionRequest
from .experience import StrategyPerformanceStore
from .outcomes import OutcomeEvaluator
from .pit import closed_bar_slice, infer_bar_interval_ms
from .trace import DecisionTraceStore
from .verifier import IndependentVerifier, VerificationRequest

__all__ = [
    "RUNTIME_VERSION",
    "AssetCycleReport",
    "AutonomousPaperRuntime",
    "CycleReport",
    "RunSummary",
]

RUNTIME_VERSION = "autonomous-paper-runtime-v1"

_MS_PER_MINUTE = 60_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fingerprint(bars: Sequence[OHLCV]) -> str:
    payload = json.dumps(
        [[b.symbol, b.timestamp, b.open, b.high, b.low, b.close, b.volume] for b in bars],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class AssetCycleReport:
    """Observable result of one asset in one cycle."""

    asset: str
    symbol: str
    regime: str | None
    market_time_ms: int
    decision_time_ms: int
    strategies_considered: tuple[str, ...]
    strategy_selected: str | None
    mode: DecisionMode
    reason: str
    classification: str
    expected_gross_edge_bps: float | None
    expected_cost_bps: float | None
    expected_net_edge_bps: float | None
    verifier_verdict: str
    risk_verdict: str
    decision_id: str
    trace_persisted: bool
    order_created: bool
    #: Honest NO_TRADE class (None when this row is not a NO_TRADE decision).
    no_trade_kind: str | None = None
    #: Operational failure kind — never a NO_TRADE decision, never a hypothesis.
    failure_kind: str | None = None
    #: Observability of the deterministic risk review (`RiskState`).
    risk_state: str = RiskState.NOT_APPLICABLE.value
    risk_evaluated: bool = False
    risk_rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "symbol": self.symbol,
            "regime": self.regime,
            "market_time_ms": self.market_time_ms,
            "decision_time_ms": self.decision_time_ms,
            "strategies_considered": list(self.strategies_considered),
            "strategy_selected": self.strategy_selected,
            "mode": self.mode.value,
            "reason": self.reason,
            "classification": self.classification,
            "no_trade_kind": self.no_trade_kind,
            "failure_kind": self.failure_kind,
            "expected_gross_edge_bps": self.expected_gross_edge_bps,
            "expected_cost_bps": self.expected_cost_bps,
            "expected_net_edge_bps": self.expected_net_edge_bps,
            "verifier_verdict": self.verifier_verdict,
            "risk_verdict": self.risk_verdict,
            "risk_state": self.risk_state,
            "risk_evaluated": self.risk_evaluated,
            "risk_rule": self.risk_rule,
            "decision_id": self.decision_id,
            "trace_persisted": self.trace_persisted,
            "order_created": self.order_created,
        }


@dataclass(frozen=True, slots=True)
class CycleReport:
    cycle: int
    session_id: str
    started_at_ms: int
    ended_at_ms: int
    assets: tuple[AssetCycleReport, ...]
    paper_trades: int
    shadow_trades: int
    no_trades: int
    orders_created: int
    traces_persisted: int
    outcomes_resolved: int
    outcomes_pending: int
    performance_updates: int
    broker_fills_closed: int
    errors: tuple[str, ...] = ()
    no_trade_kinds: dict[str, int] = field(default_factory=dict)
    risk_states: dict[str, int] = field(default_factory=dict)
    runtime_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "session_id": self.session_id,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "assets": [a.to_dict() for a in self.assets],
            "paper_trades": self.paper_trades,
            "shadow_trades": self.shadow_trades,
            "no_trades": self.no_trades,
            "no_trade_kinds": dict(self.no_trade_kinds),
            "risk_states": dict(self.risk_states),
            "runtime_failures": self.runtime_failures,
            "orders_created": self.orders_created,
            "traces_persisted": self.traces_persisted,
            "outcomes_resolved": self.outcomes_resolved,
            "outcomes_pending": self.outcomes_pending,
            "performance_updates": self.performance_updates,
            "broker_fills_closed": self.broker_fills_closed,
            "errors": list(self.errors),
        }


@dataclass
class RunSummary:
    """Aggregate of a whole run (one-shot or bounded loop)."""

    run_id: str
    environment: str
    commit: str
    mode: str
    assets: tuple[str, ...]
    timeframe: str
    cycles: int
    started_at_ms: int
    ended_at_ms: int
    cycle_reports: list[CycleReport] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    performance: list[dict[str, Any]] = field(default_factory=list)
    chain: dict[str, Any] = field(default_factory=dict)
    #: Decisions that formed a hypothesis but whose horizon is still unobserved
    #: when the run ended. DISTINCT by decision_id: a decision remains pending
    #: across cycles, so summing per-cycle counters would overstate it.
    pending_decision_ids: tuple[str, ...] = ()
    #: Aggregate of replaying every persisted decision from the trace alone.
    replay: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    production_actions: int = 0

    def totals(self) -> dict[str, int]:
        kinds: dict[str, int] = {kind.value: 0 for kind in NoTradeKind}
        states: dict[str, int] = {state.value: 0 for state in RiskState}
        for cycle in self.cycle_reports:
            for name, count in cycle.no_trade_kinds.items():
                kinds[name] = kinds.get(name, 0) + count
            for name, count in cycle.risk_states.items():
                states[name] = states.get(name, 0) + count
        totals = {
            "asset_cycle_evaluations": sum(len(c.assets) for c in self.cycle_reports),
            "paper_trades": sum(c.paper_trades for c in self.cycle_reports),
            "shadow_trades": sum(c.shadow_trades for c in self.cycle_reports),
            "no_trades": sum(c.no_trades for c in self.cycle_reports),
            "runtime_failures": sum(c.runtime_failures for c in self.cycle_reports),
            "orders_created": sum(c.orders_created for c in self.cycle_reports),
            "traces_persisted": sum(c.traces_persisted for c in self.cycle_reports),
            "outcomes_resolved": sum(c.outcomes_resolved for c in self.cycle_reports),
            "outcomes_pending": len(set(self.pending_decision_ids)),
            "performance_updates": sum(c.performance_updates for c in self.cycle_reports),
        }
        totals.update({f"no_trade_{key}": value for key, value in kinds.items()})
        totals.update({f"risk_{key}": value for key, value in states.items()})
        return totals

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "runtime_version": RUNTIME_VERSION,
            "environment": self.environment,
            "commit": self.commit,
            "mode": self.mode,
            "assets": list(self.assets),
            "timeframe": self.timeframe,
            "cycles": self.cycles,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "totals": self.totals(),
            "cycles_detail": [c.to_dict() for c in self.cycle_reports],
            "executions": self.executions,
            "outcomes": self.outcomes,
            "pending_decision_ids": list(self.pending_decision_ids),
            "performance": self.performance,
            "trace_chain": self.chain,
            "replay": self.replay,
            "errors": self.errors,
            "production_actions": self.production_actions,
        }


class AutonomousPaperRuntime:
    """Runs the autonomous decision loop over the configured assets."""

    def __init__(
        self,
        *,
        settings: Any,
        scanner_factory: Callable[[], Any],
        history_reader: Any,
        broker: Any,
        risk_manager: Any,
        families: dict[str, Any],
        strategy_map: dict[str, dict[str, Any]],
        ledger: AdmissionLedger,
        run_dir: Path | str,
        assets: Sequence[str],
        timeframe: str = "5m",
        horizon_minutes: float = 25.0,
        size_usd: float = 1_000.0,
        lookback_bars: int = 120,
        shadow_evaluation_enabled: bool = True,
        environment: str = "paper",
        cost_engine: CostEngine | None = None,
        agents: AgentRegistry | None = None,
        verifier: IndependentVerifier | None = None,
        decision_engine: DecisionEngine | None = None,
        performance_path: Path | str | None = None,
        idempotency: IdempotencyGuard | None = None,
        now_fn: Callable[[], int] | None = None,
        routing_mode: StrategyRoutingMode | str = StrategyRoutingMode.LEGACY,
        lifecycle_ecosystem: Any | None = None,
    ) -> None:
        self._settings = settings
        self._scanner_factory = scanner_factory
        self._history_reader = history_reader
        self._broker = broker
        self._risk = risk_manager
        self._families = dict(families)
        self._strategy_spec = dict(strategy_map)
        self._ledger = ledger
        self._assets = tuple(a.upper() for a in assets)
        self._timeframe = timeframe
        self._horizon_minutes = horizon_minutes
        self._size_usd = size_usd
        self._lookback_bars = lookback_bars
        self._shadow_enabled = shadow_evaluation_enabled
        self._environment = environment
        self._now = now_fn or _now_ms
        self._cost = cost_engine or CostEngine()
        self._agents = agents or default_agent_registry()
        self._verifier = verifier or IndependentVerifier(ledger=ledger, cost_engine=self._cost)
        self._decision_engine = decision_engine or DecisionEngine()
        self._registry_obj = CryptoAssetAgentRegistry()
        self._idempotency = idempotency or IdempotencyGuard()

        run_dir = Path(run_dir)
        self._run_dir = run_dir
        self._trace_store = DecisionTraceStore(run_dir)
        self._performance = StrategyPerformanceStore(
            Path(performance_path) if performance_path is not None else run_dir / "performance.json"
        )
        self._outcomes = OutcomeEvaluator()
        self._log = structlog.get_logger("autonomous_runtime")
        self._executions: list[dict[str, Any]] = []

        # WP-STRAT-07 — the lifecycle plane is now reachable from the hot loop.
        # LEGACY is the default and leaves behaviour byte-for-byte unchanged.
        self._routing_mode = coerce_routing_mode(routing_mode)
        self._lifecycle_eco = lifecycle_ecosystem
        override: dict[str, str] = {}
        if lifecycle_ecosystem is not None:
            build = getattr(lifecycle_ecosystem, "lifecycle_map", None)
            if callable(build):
                try:
                    override = {str(k): str(v) for k, v in dict(build()).items()}
                except Exception:  # a broken snapshot must not invent eligibility
                    override = {}
        policy_version = "strategy-routing-bridge-v1"
        if lifecycle_ecosystem is not None:
            policy_version = str(
                getattr(lifecycle_ecosystem, "version", policy_version) or policy_version
            )
        self._routing_adapter = LifecycleRoutingAdapter(
            registry_version="admission-ledger",
            policy_version=policy_version,
            lifecycle_override=override,
        )
        self._routing_comparisons: list[StrategyRoutingComparison] = []
        self._routing_comparisons_path = run_dir / "routing_comparisons.jsonl"
        # §12 — portfolio conflict arbitration, fed the REAL risk budgets so it
        # can only reduce what risk already permits.
        risk_cfg = getattr(self._risk, "risk", None)
        self._portfolio = StrategyPortfolioManager(
            equity=float(getattr(self._risk, "equity", 10_000.0) or 10_000.0),
            max_asset_exposure_pct=float(getattr(risk_cfg, "max_asset_exposure_pct", 10.0)),
            max_total_exposure_pct=float(getattr(risk_cfg, "max_total_exposure_pct", 25.0)),
        )

    # -- public API ---------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def trace_store(self) -> DecisionTraceStore:
        return self._trace_store

    @property
    def performance_store(self) -> StrategyPerformanceStore:
        return self._performance

    @property
    def routing_mode(self) -> StrategyRoutingMode:
        return self._routing_mode

    @property
    def routing_comparisons(self) -> tuple[StrategyRoutingComparison, ...]:
        return tuple(self._routing_comparisons)

    def _persist_routing_comparison(self, comparison: StrategyRoutingComparison) -> None:
        """Append one comparison row to the run's evidence file (best effort)."""
        try:
            self._routing_comparisons_path.parent.mkdir(parents=True, exist_ok=True)
            with self._routing_comparisons_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(comparison.to_dict(), sort_keys=True) + "\n")
        except Exception as exc:  # evidence must never abort a cycle
            self._log.warning("autonomous.routing_comparison.persist_failed", error=str(exc))

    def agent_capabilities(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._agents.capabilities()]

    async def run(
        self,
        *,
        cycles: int = 1,
        interval_seconds: float = 0.0,
        run_id: str | None = None,
    ) -> RunSummary:
        """Bounded loop (``cycles=1`` is ONE_SHOT). Never an infinite loop."""
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        run_id = run_id or f"autonomous-paper-{uuid4().hex[:12]}"
        started = self._now()
        summary = RunSummary(
            run_id=run_id,
            environment=self._environment,
            commit=_git_commit(),
            mode=getattr(self._settings.runtime.mode, "value", str(self._settings.runtime.mode)),
            assets=self._assets,
            timeframe=self._timeframe,
            cycles=cycles,
            started_at_ms=started,
            ended_at_ms=started,
        )
        for index in range(1, cycles + 1):
            try:
                report = await self.run_cycle(cycle=index)
            except Exception as exc:  # a cycle failure is visible, never silent
                summary.errors.append(f"cycle {index}: {type(exc).__name__}: {exc}")
                self._log.error("autonomous.cycle.failed", cycle=index, error=str(exc))
                continue
            # Per-cycle errors are folded in by ``finalize_summary``; keeping them
            # out of ``errors`` here would be needed only if two code paths
            # produced the summary, and that is exactly what we removed.
            summary.cycle_reports.append(report)
            self._log.info("autonomous.cycle.completed", **report.to_dict())
            if interval_seconds > 0 and index < cycles:
                import asyncio

                await asyncio.sleep(interval_seconds)

        return self.finalize_summary(
            run_id=run_id,
            started_at_ms=started,
            cycle_reports=summary.cycle_reports,
            errors=summary.errors,
        )

    def finalize_summary(
        self,
        *,
        run_id: str,
        started_at_ms: int,
        cycle_reports: list[CycleReport],
        errors: list[str] | None = None,
    ) -> RunSummary:
        """Close a run from the cycles it actually completed (§13, §48).

        ``run()`` uses this, and so does a continuous loop that drives
        ``run_cycle`` itself: a report written by a different code path from the
        one that produced the cycles would not be evidence of anything.
        """
        summary = RunSummary(
            run_id=run_id,
            environment=self._environment,
            commit=_git_commit(),
            mode=getattr(self._settings.runtime.mode, "value", str(self._settings.runtime.mode)),
            assets=self._assets,
            timeframe=self._timeframe,
            cycles=len(cycle_reports),
            started_at_ms=started_at_ms,
            ended_at_ms=self._now(),
        )
        summary.cycle_reports.extend(cycle_reports)
        summary.errors.extend(errors or [])
        for report in cycle_reports:
            summary.errors.extend(report.errors)
        summary.executions = list(self._executions)
        summary.outcomes = [o.to_dict() for o in self._trace_store.read_outcomes()]
        summary.pending_decision_ids = self._pending_decision_ids()
        summary.performance = [p.to_dict() for p in self._performance.all_cells()]
        summary.chain = self._trace_store.verify_chain().to_dict()
        summary.replay = self._replay_all()
        return summary

    def _pending_decision_ids(self) -> tuple[str, ...]:
        """Decisions that formed a hypothesis and still have no outcome."""
        resolved = {o.decision_id for o in self._trace_store.read_outcomes()}
        pending = {
            t.decision_id for t in self._trace_store.read() if t.proposal is not None
        } - resolved
        return tuple(sorted(pending))

    def _replay_all(self) -> dict[str, Any]:
        """Replay every persisted decision from the trace alone (§17).

        Runs at the end of every bounded run so REPLAY is evidenced on real
        data instead of only in tests. No market data is consulted. The status
        of every decision is reported (FULL / PARTIAL / NOT_AVAILABLE) so a
        partial replay can never be presented as a full one.
        """
        attempted = 0
        failures: list[dict[str, Any]] = []
        statuses: dict[str, int] = {}
        for trace in self._trace_store.read():
            attempted += 1
            try:
                result = self._trace_store.replay(trace.decision_id)
            except KeyError as exc:  # pragma: no cover - defensive
                failures.append({"decision_id": trace.decision_id, "error": str(exc)})
                statuses["NOT_AVAILABLE"] = statuses.get("NOT_AVAILABLE", 0) + 1
                continue
            status = result.status.value
            statuses[status] = statuses.get(status, 0) + 1
            if not result.ok:
                failures.append(
                    {
                        "decision_id": trace.decision_id,
                        "status": status,
                        "failed_checks": [c.name for c in result.checks if not c.passed],
                    }
                )
        return {
            "attempted": attempted,
            "ok": attempted - len(failures),
            "failed": len(failures),
            "statuses": statuses,
            "failures": failures,
            "market_data_accessed": False,
        }

    async def run_cycle(self, *, cycle: int) -> CycleReport:
        """One full cycle: ingest once, then decide deterministically."""
        session_id = uuid4().hex[:16]
        started = self._now()
        errors: list[str] = []

        scanner = self._scanner_factory()
        snapshots = await scanner.run()
        snap_by_symbol = {str(getattr(s, "symbol", "")): s for s in snapshots}

        # DEF-RISK-EXPOSURE-001 / DEF-RISK-INERT-002 — hand the live paper book to
        # the risk engine BEFORE any decision. The autonomous runtime reconciles
        # with the broker directly and never called ``add_position``, so
        # ``RiskManager.open_positions`` stayed empty and both the
        # ``max_open_positions`` gate and the per-asset exposure clamp were
        # inert. The broker is the single source of truth for open positions.
        self._sync_risk_positions()

        raw_history: dict[str, list[OHLCV]] = {}
        used_bars: dict[str, list[OHLCV]] = {}
        decisions_ts: dict[str, int] = {}
        sessions_started_ms = started
        for symbol, snap in snap_by_symbol.items():
            if not getattr(snap, "active", False):
                continue
            snap_ts = int(getattr(snap, "timestamp", 0) or 0)
            try:
                bars = list(
                    await self._history_reader.get_ohlcv(
                        symbol, as_of_timestamp_ms=snap_ts, lookback_bars=self._lookback_bars
                    )
                )
            except Exception as exc:  # provider failure ⇒ no orders (fail closed)
                errors.append(f"{symbol}: history_error {type(exc).__name__}: {exc}")
                continue
            raw_history[symbol] = bars
            decision_ts = min(snap_ts, sessions_started_ms) or snap_ts
            decisions_ts[symbol] = decision_ts
            # PIT slice by bar CLOSE: a bar opened just before the decision but
            # still forming is future information and must not be used.
            used_bars[symbol] = closed_bar_slice(
                bars, decision_ts, interval_ms=infer_bar_interval_ms(bars)
            )

        assets: list[AssetCycleReport] = []
        for asset in self._assets:
            symbol = f"{asset}/USDT"
            row = self._evaluate_asset(
                session_id=session_id,
                asset=asset,
                symbol=symbol,
                snap=snap_by_symbol.get(symbol),
                raw_bars=raw_history.get(symbol, []),
                bars=used_bars.get(symbol, []),
                decision_time_ms=decisions_ts.get(symbol, sessions_started_ms),
                errors=errors,
            )
            assets.append(row)

        fills_closed = self._reconcile(session_id, snapshots, errors)
        resolved, pending, updates = self._process_outcomes(
            raw_history, decisions_ts, session_started_ms=sessions_started_ms
        )

        # A row with an operational failure is NOT a NO_TRADE decision: it is
        # counted separately so an outage can never be read as "we decided not
        # to trade" (§4).
        kinds: dict[str, int] = {}
        for asset_row in assets:
            if asset_row.no_trade_kind is not None:
                kinds[asset_row.no_trade_kind] = kinds.get(asset_row.no_trade_kind, 0) + 1
        states: dict[str, int] = {}
        for asset_row in assets:
            states[asset_row.risk_state] = states.get(asset_row.risk_state, 0) + 1

        return CycleReport(
            cycle=cycle,
            session_id=session_id,
            started_at_ms=started,
            ended_at_ms=self._now(),
            assets=tuple(assets),
            paper_trades=sum(1 for a in assets if a.mode is DecisionMode.TRADE_PAPER),
            shadow_trades=sum(1 for a in assets if a.mode is DecisionMode.SHADOW_TRADE),
            no_trades=sum(1 for a in assets if a.no_trade_kind is not None),
            orders_created=sum(1 for a in assets if a.order_created),
            traces_persisted=sum(1 for a in assets if a.trace_persisted),
            outcomes_resolved=resolved,
            outcomes_pending=pending,
            performance_updates=updates,
            broker_fills_closed=fills_closed,
            errors=tuple(errors),
            no_trade_kinds=kinds,
            risk_states=states,
            runtime_failures=sum(1 for a in assets if a.failure_kind is not None),
        )

    # -- one asset ----------------------------------------------------------

    def _evaluate_asset(
        self,
        *,
        session_id: str,
        asset: str,
        symbol: str,
        snap: Any | None,
        raw_bars: list[OHLCV],
        bars: list[OHLCV],
        decision_time_ms: int,
        errors: list[str],
    ) -> AssetCycleReport:
        decision_id = f"{session_id}-{asset}"
        observed_ms = int(getattr(snap, "timestamp", 0) or 0) if snap else 0
        # The trace's market time is the newest market timestamp the decision
        # MAY have used: the observation instant can postdate the decision
        # instant by the fetch latency, never the other way round (PIT).
        market_time_ms = min(observed_ms, decision_time_ms) if observed_ms else 0
        market_context: dict[str, Any] = {
            "symbol": symbol,
            "active": bool(getattr(snap, "active", False)) if snap else False,
            "last_price": getattr(snap, "last_price", None) if snap else None,
            "spread_bps": getattr(snap, "spread_bps", None) if snap else None,
            "volume_24h_usdt": getattr(snap, "volume_24h_usdt", None) if snap else None,
            "rank_score": getattr(snap, "rank_score", None) if snap else None,
            "rejection_reason": getattr(snap, "rejection_reason", None) if snap else None,
            "scanner_timestamp_ms": observed_ms,
            "market_time_ms": market_time_ms,
        }
        fingerprint = _fingerprint(bars)
        strategies_considered = tuple(sorted(self._strategy_spec))

        if snap is None:
            return self._terminal(
                session_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                market_time_ms=market_time_ms,
                decision_time_ms=decision_time_ms,
                mode=DecisionMode.NO_TRADE,
                reason="no_snapshot_for_symbol",
                classification="NO_MARKET_DATA",
                market_context=market_context,
                strategies_considered=strategies_considered,
                no_trade_kind=NoTradeKind.NO_TRADE_DATA.value,
            )

        context: Any | None = None
        context_error: str | None = None
        try:
            context = self._registry_obj.build_context(
                asset, bars, decision_time_ms, data_fingerprint=fingerprint
            )
        except Exception as exc:
            context_error = f"{type(exc).__name__}: {exc}"
            errors.append(f"{symbol}: context_error {context_error}")

        if context is None:
            # A provider outage is an INCIDENT, not a trading decision: it is
            # reported as a runtime failure and excluded from the NO_TRADE
            # hypothesis counts. Anything else is a genuine data no-decision.
            failure = self._failure_kind(errors, symbol)
            return self._terminal(
                session_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                market_time_ms=market_time_ms,
                decision_time_ms=decision_time_ms,
                mode=DecisionMode.NO_TRADE,
                reason=f"context_error:{context_error}",
                classification="CONTEXT_ERROR",
                market_context=market_context,
                strategies_considered=strategies_considered,
                no_trade_kind=(None if failure is not None else NoTradeKind.NO_TRADE_DATA.value),
                failure_kind=failure,
            )

        regime = getattr(context, "market_regime", None)
        strategy_map = self._strategy_map_for(asset=asset, regime=regime)
        # §38/DEF-AUTO-3 — the freshness gate is budgeted from THIS run's
        # timeframe, so a 30m context is not judged by a 15-minute rule.
        router = StrategyRouter(
            gates=RouterGates(require_confirmed=False, timeframe=self._timeframe)
        )

        # WP-STRAT-07 (§4/§5) — the lifecycle-aware plane runs alongside the
        # legacy router. SHADOW records it only; LIFECYCLE lets the eligible set
        # gate which strategies may emit an executable proposal. A bridge
        # failure fails CLOSED in LIFECYCLE mode (no eligible strategy), never
        # open. The context here is a single, temporally coherent snapshot
        # (data_time <= decision_time), so there is no cross-plane look-ahead.
        lifecycle_selection: Any | None = None
        verdict_by_id: dict[str, str] = {}
        allowed_ids: frozenset[str] | None = None
        if self._routing_mode is not StrategyRoutingMode.LEGACY:
            try:
                lifecycle_selection, _lifecycle_map = self._routing_adapter.select(
                    router,
                    context=context,
                    regime=regime,
                    strategy_map=strategy_map,
                    ledger=self._ledger,
                )
                verdict_by_id = {
                    item.strategy_id: item.verdict for item in lifecycle_selection.routed
                }
            except Exception as exc:
                errors.append(f"{symbol}: routing_bridge_error {type(exc).__name__}: {exc}")
                lifecycle_selection = None
            if self._routing_mode is StrategyRoutingMode.LIFECYCLE:
                allowed_ids = (
                    frozenset(lifecycle_selection.selected)
                    if lifecycle_selection is not None
                    else frozenset()
                )

        # The router is consulted PER CANDIDATE, in the ranked order derived
        # from the admission ledger (measured gross edge) plus bounded
        # experience. First candidate that passes the router gates AND emits a
        # preregistered alpha wins; a strategy that emits nothing is NOT a
        # candidate and is recorded as such (never silently dropped).
        considered_rows: list[dict[str, Any]] = []
        emitting: list[tuple[float, str, Any, Any]] = []
        for strategy_id, spec in strategy_map.items():
            routed = router.route(context, regime, {strategy_id: spec})
            row: dict[str, Any] = {
                "strategy_id": strategy_id,
                "admission_status": self._ledger.status_for(strategy_id).value,
                "admitted_for_paper": self._ledger.is_paper_admitted(strategy_id),
                "expected_gross_edge_bps": self._ledger.expected_gross_edge_bps(strategy_id),
                "router_status": "SELECTED",
                "router_reason": None,
                "emitted_alpha": False,
                "selected": False,
                "lifecycle_verdict": verdict_by_id.get(strategy_id),
            }
            if allowed_ids is not None and strategy_id not in allowed_ids:
                # LIFECYCLE: the lifecycle-aware plane did not select this
                # strategy, so it may not produce an executable proposal. The
                # refusal is named, never silently dropped.
                row["router_status"] = "REJECTED"
                row["router_reason"] = "lifecycle_excluded:" + verdict_by_id.get(
                    strategy_id, "NOT_SELECTED"
                )
                considered_rows.append(row)
                continue
            if routed.is_no_trade or not routed.strategy_id:
                row["router_status"] = "REJECTED"
                row["router_reason"] = routed.no_trade_reason
                considered_rows.append(row)
                continue
            family = self._families.get(str(routed.family or ""))
            alpha = (
                self._generate_alpha(
                    family=family,
                    bars=bars,
                    direction=routed.direction,
                    errors=errors,
                    symbol=symbol,
                )
                if family is not None
                else None
            )
            if alpha is None:
                row["router_status"] = "NOT_APPLICABLE"
                row["router_reason"] = (
                    f"no_alpha_in_direction:{routed.direction or 'ANY'}"
                    if family is not None
                    else f"family_not_found:{routed.family}"
                )
                considered_rows.append(row)
                continue
            row["emitted_alpha"] = True
            considered_rows.append(row)
            emitting.append(
                (
                    self._ledger.expected_gross_edge_bps(strategy_id) or -999.0,
                    strategy_id,
                    alpha,
                    routed,
                )
            )

        # §12 — portfolio conflict arbitration (LIFECYCLE mode only, §13). It can
        # ONLY reduce: same-asset / same-direction duplicates and anything that
        # would breach the real per-asset/total exposure budgets are dropped
        # before the deterministic winner is chosen. ``expected_net_edge_bps``
        # carries the ledger's expected gross edge purely as an ordering
        # tie-break — the manager never sizes; the RiskManager stays the final
        # authority.
        portfolio_rejected: dict[str, str] = {}
        if self._routing_mode is StrategyRoutingMode.LIFECYCLE and len(emitting) > 1:
            proposals = [
                PortfolioProposal(
                    strategy_id=sid,
                    asset=asset,
                    direction=str(getattr(routed, "direction", "") or "UNKNOWN"),
                    notional_usdt=self._size_usd,
                    expected_net_edge_bps=float(edge),
                    regime=regime,
                )
                for edge, sid, _alpha, routed in emitting
            ]
            portfolio_decision = self._portfolio.arbitrate(proposals, timestamp_ms=decision_time_ms)
            accepted_ids = set(portfolio_decision.accepted_proposals)
            for _edge, sid, _alpha, _routed in emitting:
                if sid not in accepted_ids:
                    portfolio_rejected[sid] = "PORTFOLIO_CONFLICT"
            emitting = [item for item in emitting if item[1] in accepted_ids]

        # Selection rule (deterministic, pre-registered): among the candidates
        # that passed the router AND emitted an alpha, take the one with the
        # highest expected gross edge. Every candidate's outcome is recorded.
        selected: tuple[str, Any, Any] | None = None
        if emitting:
            emitting.sort(key=lambda item: (-item[0], item[1]))
            _gross, best_id, best_alpha, best_routed = emitting[0]
            for row in considered_rows:
                if row["strategy_id"] == best_id:
                    row["selected"] = True
            selected = (best_id, best_alpha, best_routed)

        if self._routing_mode is not StrategyRoutingMode.LEGACY:
            # Record the same-context comparison (§6). In SHADOW mode the legacy
            # winner is the untouched legacy result; in LIFECYCLE mode it is the
            # winner within the enforced set.
            legacy_selected = (selected[0],) if selected is not None else ()
            try:
                comparison = self._routing_adapter.compare(
                    router,
                    run_id=session_id,
                    context=context,
                    regime=regime,
                    strategy_map=strategy_map,
                    ledger=self._ledger,
                    legacy_selected=legacy_selected,
                    decision_time_ms=decision_time_ms,
                    asset=asset,
                    timeframe=self._timeframe,
                    mode=self._routing_mode,
                    portfolio_rejected=portfolio_rejected,
                )
                self._routing_comparisons.append(comparison)
                self._persist_routing_comparison(comparison)
            except Exception as exc:  # evidence must never abort the decision
                errors.append(f"{symbol}: routing_compare_error {type(exc).__name__}: {exc}")

        if selected is None:
            failure = self._failure_kind(errors, symbol)
            return self._terminal(
                session_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                market_time_ms=market_time_ms,
                decision_time_ms=decision_time_ms,
                mode=DecisionMode.NO_TRADE,
                reason="no_candidate_emitted_an_alpha",
                classification="NO_ALPHA",
                market_context=market_context,
                strategies_considered=strategies_considered,
                asset_context=_safe_context(context),
                regime=regime,
                considered_rows=considered_rows,
                no_trade_kind=(
                    None if failure is not None else NoTradeKind.NO_TRADE_STRATEGIC.value
                ),
                failure_kind=failure,
            )

        routed_strategy_id, alpha, routed = selected
        admission = self._ledger.entry(routed_strategy_id)
        proposal = self._build_proposal(
            session_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            alpha=alpha,
            strategy_id=routed_strategy_id,
            regime=regime,
            decision_time_ms=decision_time_ms,
            market_time_ms=market_time_ms,
            spread_bps=getattr(snap, "spread_bps", None),
            context_fingerprint=getattr(context, "data_fingerprint", fingerprint),
            errors=errors,
        )
        if proposal is None:
            return self._terminal(
                session_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                market_time_ms=market_time_ms,
                decision_time_ms=decision_time_ms,
                mode=DecisionMode.NO_TRADE,
                reason="no_measured_gross_edge_in_ledger",
                classification="UNKNOWN_STRATEGY",
                market_context=market_context,
                strategies_considered=strategies_considered,
                asset_context=_safe_context(context),
                regime=regime,
                strategy_selected=routed_strategy_id,
                considered_rows=considered_rows,
                no_trade_kind=NoTradeKind.NO_TRADE_STRATEGIC.value,
            )

        reviews = self._agents.review(
            ReviewInputs(
                run_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                decision_time_ms=decision_time_ms,
                regime=regime,
                bars_in_window=len(bars),
                data_quality=dict(getattr(context, "data_quality", {}) or {}),
                data_fingerprint=getattr(context, "data_fingerprint", fingerprint),
                window_end_ts=int(getattr(context, "window_end_ts", 0) or 0),
                context_issues=(),
                admission=admission,
                proposal=proposal,
                performance=self._performance.get(
                    strategy_id=proposal.strategy_id,
                    asset=asset,
                    regime=regime or "UNKNOWN",
                    timeframe=self._timeframe,
                ),
            )
        )

        # 1) intent (pure pre-classification), 2) deterministic risk ONLY for
        # an intent that could order, 3) independent verification of that
        # intent, 4) final decision with both results attached.
        packet = DecisionRequest(
            run_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            regime=regime,
            admission=admission,
            proposal=proposal,
            verification=VerificationResult(
                decision_id=decision_id, verdict=VerifierVerdict.NOT_RUN
            ),
            risk=RiskReview(verdict=RiskVerdict.NOT_APPLICABLE),
            agent_messages=reviews,
            shadow_evaluation_enabled=self._shadow_enabled,
        )
        intent = self._decision_engine.intend(packet)

        risk_review = self._risk_review(
            intent=intent,
            alpha=alpha,
            proposal=proposal,
            decision_id=decision_id,
            symbol=symbol,
        )
        verification = self._verifier.verify(
            VerificationRequest(
                run_id=session_id,
                decision_id=decision_id,
                asset=asset,
                decision_time_ms=decision_time_ms,
                declared_mode=intent.mode,
                raw_history=tuple(raw_bars),
                used_bars=tuple(bars),
                window_end_ts=int(getattr(context, "window_end_ts", 0) or 0),
                context_fingerprint=getattr(context, "data_fingerprint", fingerprint),
                proposal=proposal,
                cost_inputs=self._cost_inputs(snap),
                risk_reviewed=risk_review.evaluated,
                orders_created=0,
                shadow_marked=intent.is_shadow,
            )
        )
        final = self._decision_engine.decide(
            DecisionRequest(
                run_id=session_id,
                decision_id=decision_id,
                asset=asset,
                symbol=symbol,
                market_time_ms=market_time_ms,
                decision_time_ms=decision_time_ms,
                regime=regime,
                admission=admission,
                proposal=proposal,
                verification=verification,
                risk=risk_review,
                agent_messages=reviews,
                shadow_evaluation_enabled=self._shadow_enabled,
            )
        )

        order_created = False
        if final.mode is DecisionMode.TRADE_PAPER:
            order_created = self._execute_paper(
                session_id=session_id,
                decision_id=decision_id,
                symbol=symbol,
                asset=asset,
                strategy_id=proposal.strategy_id,
                alpha=alpha,
                proposal=proposal,
                risk_review=risk_review,
                errors=errors,
            )
        elif final.order_authorised:
            raise AssertionError("only TRADE_PAPER may authorise an order")

        final_kind = final.no_trade_kind
        trace = self._persist_trace(
            session_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            decision=final,
            classification=final.classification,
            no_trade_kind=None if final_kind is None else final_kind.value,
            regime=regime,
            market_context=market_context,
            asset_context=_safe_context(context),
            proposal=proposal,
            reviews=reviews,
            verification=verification,
            risk_review=risk_review,
            strategies_considered=strategies_considered,
            strategy_selected=proposal.strategy_id,
            considered_rows=considered_rows,
            router_trace=tuple(routed.trace),
            order_created=order_created,
            orders_created=1 if order_created else 0,
            errors=tuple(e for e in errors if e.startswith(symbol)),
        )
        return AssetCycleReport(
            asset=asset,
            symbol=symbol,
            regime=regime,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            strategies_considered=strategies_considered,
            strategy_selected=proposal.strategy_id,
            mode=final.mode,
            reason=final.reason,
            classification=final.classification,
            expected_gross_edge_bps=proposal.expected_gross_edge_bps,
            expected_cost_bps=proposal.expected_cost_bps,
            expected_net_edge_bps=proposal.expected_net_edge_bps,
            verifier_verdict=verification.verdict.value,
            risk_verdict=risk_review.verdict.value,
            decision_id=decision_id,
            trace_persisted=trace is not None,
            order_created=order_created,
            no_trade_kind=None if final_kind is None else final_kind.value,
            risk_state=risk_review.state.value,
            risk_evaluated=risk_review.evaluated,
            risk_rule=risk_review.rule,
        )

    # -- helpers ------------------------------------------------------------

    def _strategy_map_for(self, *, asset: str, regime: str | None) -> dict[str, dict[str, Any]]:
        """Admission-backed strategy map with experience-based ordering.

        Ordering is the tie-break the router uses, so it is built from the
        ledger's measured gross edge and then nudged (bounded) by realised
        outcomes. The map never marks a strategy CONFIRMED for paper: the
        admission decision belongs to the ledger and the DecisionEngine.

        Only the entries measured on THIS run's timeframe are eligible: a
        timeframe nobody researched has no expected edge to propose from.
        """
        rows: list[tuple[float, str, dict[str, Any]]] = []
        eligible = self._ledger.entries_for_timeframe(self._timeframe)
        for strategy_id, spec in self._strategy_spec.items():
            if strategy_id not in eligible:
                continue
            entry = self._ledger.entry(strategy_id)
            priority = self._performance.selection_priority(
                strategy_id=strategy_id,
                asset=asset,
                regime=regime or "UNKNOWN",
                timeframe=self._timeframe,
            )
            key = (entry.expected_gross_edge_bps or -999.0) + priority
            rows.append(
                (
                    key,
                    strategy_id,
                    {
                        **spec,
                        # §17/§19 — the lifecycle state the ledger holds. This
                        # used to be a literal "CONFIRMED"/"RESEARCH_ONLY" pair,
                        # which meant the router read a string the ledger never
                        # said (DEF-AUTO-4).
                        "status": entry.status.value,
                        "priority": priority,
                    },
                )
            )
        rows.sort(key=lambda r: (-r[0], r[1]))
        return {strategy_id: spec for _key, strategy_id, spec in rows}

    def _generate_alpha(
        self,
        *,
        family: Any,
        bars: list[OHLCV],
        direction: str | None,
        errors: list[str],
        symbol: str,
    ) -> Any | None:
        """Run the family with ITS OWN preregistered indicator precompute.

        An empty indicator dict is passed on purpose: each family computes the
        indicator set it was preregistered with (``_compute_indicators``),
        instead of failing closed against a partial shared dict.
        """
        wanted = (direction or "ANY").upper()
        try:
            alphas = family.generate(bars, {}, None)
        except Exception as exc:
            errors.append(f"{symbol}: strategy_error {type(exc).__name__}: {exc}")
            return None
        matching = [
            a
            for a in alphas
            if wanted == "ANY" or str(getattr(a, "direction", "")).upper() == wanted
        ]
        if not matching:
            return None
        return max(matching, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))

    def _build_proposal(
        self,
        *,
        session_id: str,
        decision_id: str,
        asset: str,
        symbol: str,
        alpha: Any,
        strategy_id: str,
        regime: str | None,
        decision_time_ms: int,
        market_time_ms: int,
        spread_bps: float | None,
        context_fingerprint: str,
        errors: list[str],
    ) -> TradeProposal | None:
        entry = self._ledger.entry(strategy_id)
        gross = entry.expected_gross_edge_bps
        evidence = entry.edge_evidence
        if gross is None or evidence is None:
            return None
        cost: CostBreakdown = self._cost.evaluate(
            size_usd=self._size_usd,
            horizon_minutes=self._horizon_minutes,
            spread_bps=None if spread_bps is None else float(spread_bps),
            created_at_ms=self._now(),
        )
        direction = str(getattr(alpha, "direction", "")).upper()
        structural_stop = getattr(alpha, "effective_stop", None) or getattr(
            alpha, "structural_stop", None
        )
        proposal = TradeProposal(
            run_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            strategy_id=strategy_id,
            # DEF-PROV-001: this used to carry ``str(entry.timeframe)`` (e.g.
            # "5m") — a timeframe is NOT a strategy version, and the value
            # travelled into every ShadowTradeDecision and persisted trace, so
            # "which version of this strategy produced this" was unanswerable.
            # Use the same ``<family>@<timeframe>`` convention the registry
            # assigns, so the trace, the registry and the ledger name one thing.
            strategy_version=f"{entry.family}@{entry.timeframe}",
            family=str(getattr(alpha, "family", strategy_id)),
            direction=direction,
            timeframe=str(getattr(alpha, "timeframe", self._timeframe)),
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            entry_reference=float(getattr(alpha, "entry_reference", 0.0) or 0.0),
            structural_stop=None if structural_stop is None else float(structural_stop),
            horizon_minutes=self._horizon_minutes,
            expected_gross_edge_bps=float(gross),
            expected_cost_bps=cost.round_trip_bps,
            expected_net_edge_bps=float(gross) - cost.round_trip_bps,
            cost=cost,
            edge_evidence=EdgeEvidence(
                source_doc=evidence.source_doc,
                metric=evidence.metric,
                value_bps=evidence.value_bps,
                knowledge=evidence.knowledge,
                sample_trades=evidence.sample_trades,
                note=evidence.note,
                evidence_class=evidence.evidence_class,
                period=evidence.period,
                timeframe=evidence.timeframe,
                status=evidence.status,
            ),
            admission_status=entry.status,
            regime=regime,
            confidence=float(getattr(alpha, "confidence", 0.0) or 0.0),
            evidence=(
                f"admission_ledger:{self._ledger.source_path}",
                f"edge_evidence:{evidence.source_doc}#{evidence.metric}",
                f"cost_model:{COST_MODEL_VERSION}:{cost.scenario_id}",
                f"spread:{cost.spread_bps:.4f}bps[{cost.spread_knowledge}]",
            ),
            counter_evidence=(entry.rationale,),
            context_fingerprint=context_fingerprint,
        )
        return proposal

    @staticmethod
    def _failure_kind(errors: list[str], symbol: str) -> str | None:
        """Operational failure recorded for ``symbol``, if any (§4).

        A provider outage or an exploding strategy is an incident: it must not
        be filed as a NO_TRADE decision, because no decision was taken.
        """
        prefix = f"{symbol}: "
        for error in errors:
            if not error.startswith(prefix):
                continue
            remainder = error[len(prefix) :]
            if remainder.startswith("history_error"):
                return RuntimeFailureKind.PROVIDER_FAILURE.value
            if remainder.startswith("strategy_error"):
                return RuntimeFailureKind.INTERNAL_ERROR.value
            if remainder.startswith("broker_error"):
                return RuntimeFailureKind.INTERNAL_ERROR.value
            if remainder.startswith("adapter_error"):
                return RuntimeFailureKind.ADAPTER_FAILURE.value
            if remainder.startswith("invalid_data"):
                return RuntimeFailureKind.INVALID_DATA.value
        return None

    def _risk_review(
        self,
        *,
        intent: Any,
        alpha: Any,
        proposal: TradeProposal,
        decision_id: str,
        symbol: str,
    ) -> RiskReview:
        """Run the deterministic risk engine for EVERY packet with a proposal.

        The SAME canonical ``RiskManager.check_signal`` used by the PAPER path
        is consulted — never a second, shadow-specific risk engine. What
        changes with the mode is only the BINDINGNESS of the verdict:

        * ``TRADE_PAPER``  → binding; PASS/ADJUST is required to authorise;
        * ``SHADOW_TRADE`` → advisory; it can neither authorise nor block;
        * ``NO_TRADE``     → advisory; recorded so risk stays observable even
          when no trade happens (§12).

        ``evaluated`` is True only when the engine really ran, so a verdict
        nobody produced can never be reported as an approval.
        """
        binding = intent.mode is DecisionMode.TRADE_PAPER
        inputs: dict[str, Any] = {
            "decision_id": decision_id,
            "symbol": symbol,
            "strategy_id": proposal.strategy_id,
            "side": "buy" if proposal.direction == "LONG" else "sell",
            "entry_reference": proposal.entry_reference,
            "horizon_minutes": proposal.horizon_minutes,
            "requested_mode": intent.mode.value,
            "advisory": not binding,
            "kill_switch_enabled": bool(
                getattr(getattr(self._risk, "risk", None), "kill_switch_enabled", False)
            ),
            "equity": float(getattr(self._risk, "equity", 0.0) or 0.0),
            "open_positions": len(getattr(self._risk, "open_positions", {}) or {}),
            "trades_today": int(getattr(self._risk, "trades_today", 0) or 0),
            "consecutive_losses": int(getattr(self._risk, "consecutive_losses", 0) or 0),
        }
        if binding and not self._ledger.is_paper_admitted(proposal.strategy_id):
            return RiskReview(
                verdict=RiskVerdict.VETO,
                reason=f"strategy {proposal.strategy_id} is not admitted for PAPER",
                rule="admission_ledger",
                inputs=inputs,
            )
        try:
            signal = alpha_signal_to_signal(alpha)
        except AdapterError as exc:
            return RiskReview(
                verdict=RiskVerdict.VETO,
                reason=f"adapter_error:{exc}",
                advisory=not binding,
                rule="signal_adapter",
                inputs=inputs,
            )
        check = self._risk.check_signal(signal)
        inputs["blocked_by"] = check.blocked_by
        if not check.approved:
            return RiskReview(
                verdict=RiskVerdict.VETO,
                reason=check.reason or "risk_rejected",
                advisory=not binding,
                evaluated=True,
                rule=check.blocked_by or "risk_check",
                inputs=inputs,
            )
        size = check.position_size
        if size is None or size.notional_usdt <= 0:
            return RiskReview(
                verdict=RiskVerdict.VETO,
                reason="risk_produced_no_position_size",
                advisory=not binding,
                evaluated=True,
                rule="position_sizing",
                inputs=inputs,
            )
        inputs["notional_usdt"] = float(size.notional_usdt)
        inputs["quantity"] = float(size.quantity)
        inputs["stop_loss_pct"] = float(size.stop_loss_pct)
        inputs["take_profit_pct"] = float(size.take_profit_pct)
        return RiskReview(
            verdict=RiskVerdict.PASS,
            reason="risk_approved",
            notional_usdt=float(size.notional_usdt),
            advisory=not binding,
            evaluated=True,
            rule="all_limits_pass",
            inputs=inputs,
        )

    def _execute_paper(
        self,
        *,
        session_id: str,
        decision_id: str,
        symbol: str,
        asset: str,
        strategy_id: str,
        alpha: Any,
        proposal: TradeProposal,
        risk_review: RiskReview,
        errors: list[str],
    ) -> bool:
        """Execute a PAPER order — the only place the broker is called."""
        # Defence in depth: re-assert admission immediately before execution.
        if not self._ledger.is_paper_admitted(strategy_id):
            errors.append(f"{symbol}: refusal_paper_not_admitted:{strategy_id}")
            return False
        cloid = f"PAPER-AUTO-{proposal.context_fingerprint[:12]}-{strategy_id}-{decision_id[-6:]}"
        if self._idempotency.is_duplicate(cloid):
            errors.append(f"{symbol}: duplicate_intent:{cloid}")
            return False
        try:
            signal = alpha_signal_to_signal(alpha)
            check = self._risk.check_signal(signal)
            if not check.approved or check.position_size is None:
                errors.append(f"{symbol}: risk_recheck_rejected:{check.reason}")
                return False
            size = check.position_size
            approved = dataclasses.replace(
                signal,
                stop_loss_pct=size.stop_loss_pct,
                take_profit_pct=size.take_profit_pct,
                metadata={
                    **signal.metadata,
                    "notional_usdt": size.notional_usdt,
                    "cloid": cloid,
                    "risk_approved_by": "RiskManager",
                    "decision_id": decision_id,
                },
            )
            result = self._broker.execute_signal(approved)
        except Exception as exc:  # broker failure ⇒ no order, loud and recorded
            errors.append(f"{symbol}: broker_error {type(exc).__name__}: {exc}")
            return False
        if result is None:
            errors.append(f"{symbol}: broker_returned_no_fill")
            return False
        self._idempotency.register(cloid)
        self._executions.append(
            {
                "run_id": session_id,
                "decision_id": decision_id,
                "asset": asset,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "mode": DecisionMode.TRADE_PAPER.value,
                "notional_usdt": risk_review.notional_usdt,
                "cloid": cloid,
            }
        )
        # DEF-VERIFY-012: the book was synced once per cycle, before the asset
        # loop, so a position opened by asset 1 was invisible to asset 2 in the
        # SAME cycle. Re-adopt the broker book immediately after a fill so every
        # later decision sees the real exposure (still the broker as authority).
        self._sync_risk_positions()
        return True

    def _terminal(
        self,
        *,
        session_id: str,
        decision_id: str,
        asset: str,
        symbol: str,
        market_time_ms: int,
        decision_time_ms: int,
        mode: DecisionMode,
        reason: str,
        classification: str,
        market_context: dict[str, Any],
        strategies_considered: tuple[str, ...],
        asset_context: dict[str, Any] | None = None,
        regime: str | None = None,
        strategy_selected: str | None = None,
        considered_rows: list[dict[str, Any]] | None = None,
        router_trace: tuple[str, ...] = (),
        no_trade_kind: str | None = None,
        failure_kind: str | None = None,
    ) -> AssetCycleReport:
        """Terminal NO_TRADE with a persisted trace (every decision is recorded)."""
        risk_review = RiskReview(
            verdict=RiskVerdict.NOT_APPLICABLE,
            reason="no proposal: nothing to review",
            source="RiskManager.not_invoked",
        )
        trace = self._persist_trace(
            session_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            decision=_TerminalDecision(mode=mode, reason=reason, classification=classification),
            classification=classification,
            no_trade_kind=no_trade_kind,
            regime=regime,
            market_context=market_context,
            asset_context=asset_context or {},
            proposal=None,
            reviews=(),
            verification=VerificationResult(
                decision_id=decision_id,
                verdict=VerifierVerdict.NOT_RUN,
                failures=(),
                verifier_version=self._verifier.version,
            ),
            risk_review=risk_review,
            strategies_considered=strategies_considered,
            strategy_selected=strategy_selected,
            considered_rows=considered_rows,
            router_trace=router_trace,
            order_created=False,
            orders_created=0,
            errors=(),
        )
        return AssetCycleReport(
            asset=asset,
            symbol=symbol,
            regime=regime,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            strategies_considered=strategies_considered,
            strategy_selected=strategy_selected,
            mode=mode,
            reason=reason,
            classification=classification,
            expected_gross_edge_bps=None,
            expected_cost_bps=None,
            expected_net_edge_bps=None,
            verifier_verdict=VerifierVerdict.NOT_RUN.value,
            risk_verdict=RiskVerdict.NOT_APPLICABLE.value,
            decision_id=decision_id,
            trace_persisted=trace is not None,
            order_created=False,
            no_trade_kind=no_trade_kind,
            failure_kind=failure_kind,
            risk_state=risk_review.state.value,
            risk_evaluated=risk_review.evaluated,
            risk_rule=risk_review.rule,
        )

    def _persist_trace(
        self,
        *,
        session_id: str,
        decision_id: str,
        asset: str,
        symbol: str,
        market_time_ms: int,
        decision_time_ms: int,
        decision: Any,
        classification: str,
        no_trade_kind: str | None,
        regime: str | None,
        market_context: dict[str, Any],
        asset_context: dict[str, Any],
        proposal: TradeProposal | None,
        reviews: tuple[AgentMessage, ...],
        verification: VerificationResult,
        risk_review: RiskReview,
        strategies_considered: tuple[str, ...],
        strategy_selected: str | None,
        considered_rows: list[dict[str, Any]] | None,
        router_trace: tuple[str, ...],
        order_created: bool,
        orders_created: int,
        errors: tuple[str, ...],
    ) -> DecisionTrace | None:
        considered = tuple(
            considered_rows
            if considered_rows is not None
            else (
                {
                    "strategy_id": sid,
                    "admission_status": self._ledger.status_for(sid).value,
                    "admitted_for_paper": self._ledger.is_paper_admitted(sid),
                    "expected_gross_edge_bps": self._ledger.expected_gross_edge_bps(sid),
                    "router_status": "NOT_EVALUATED",
                    "router_reason": None,
                    "selected": sid == strategy_selected,
                }
                for sid in strategies_considered
            )
        )
        trace = DecisionTrace(
            run_id=session_id,
            decision_id=decision_id,
            asset=asset,
            symbol=symbol,
            market_time_ms=market_time_ms,
            decision_time_ms=decision_time_ms,
            mode=decision.mode,
            reason=decision.reason,
            classification=classification,
            regime=regime,
            strategies_considered=considered,
            market_context={**market_context, "router_trace": list(router_trace)},
            asset_context=asset_context,
            proposal=None if proposal is None else proposal.to_dict(),
            agent_messages=tuple(m.to_dict() for m in reviews),
            evidence=() if proposal is None else proposal.evidence,
            counter_evidence=() if proposal is None else proposal.counter_evidence,
            verification=verification.to_dict(),
            risk=risk_review.to_dict(),
            shadow=None if getattr(decision, "shadow", None) is None else decision.shadow.to_dict(),
            cost_model_version=COST_MODEL_VERSION,
            order_created=order_created,
            orders_created=orders_created,
            no_trade_kind=no_trade_kind,
            errors=errors,
            created_at_ms=self._now(),
        )
        try:
            self._trace_store.append(trace)
        except Exception as exc:  # persistence failure is loud, never silent
            self._log.error("autonomous.trace.persist_failed", error=str(exc))
            return None
        return trace

    def _cost_inputs(self, snap: Any) -> dict[str, Any]:
        return {
            "size_usd": self._size_usd,
            "horizon_minutes": self._horizon_minutes,
            "spread_bps": getattr(snap, "spread_bps", None),
            "liquidity_regime": "normal",
            "volatility_bps": 0.0,
            "entry_order_type": "market",
            "exit_order_type": "market",
        }

    # -- post-cycle stages ---------------------------------------------------

    def _sync_risk_positions(self) -> None:
        """Adopt the broker's open book into the risk engine (fail-safe)."""
        try:
            positions = dict(getattr(self._broker, "positions", {}) or {})
        except Exception:  # pragma: no cover - defensive: a broken book sync
            return  # must never abort a cycle; exposure is then measured as 0
        sync = getattr(self._risk, "sync_open_positions", None)
        if callable(sync):
            sync(positions)

    def _reconcile(self, session_id: str, snapshots: list[Any], errors: list[str]) -> int:
        """Reconcile the paper book and feed the delta into the risk engine."""
        try:
            summary = self._broker.reconcile_session(session_id, snapshots, self._settings.risk)
        except Exception as exc:
            errors.append(f"reconcile_error {type(exc).__name__}: {exc}")
            return 0
        new_trades = list(getattr(summary, "new_closed_trades", []) or [])
        for trade in new_trades:
            try:
                self._risk.record_trade_result(float(trade.pnl))
            except (TypeError, ValueError) as exc:
                errors.append(f"risk_record_failed {exc}")
        return len(new_trades)

    def _process_outcomes(
        self,
        raw_history: dict[str, list[OHLCV]],
        decisions_ts: dict[str, int],
        *,
        session_started_ms: int,
    ) -> tuple[int, int, int]:
        """Resolve any decision whose horizon is now observable, then learn."""
        existing = self._trace_store.read_outcomes()
        resolved_ids = {o.decision_id for o in existing}
        seen_keys = {o.outcome_key for o in existing}
        traces = self._trace_store.read()
        bars_by_symbol: dict[str, list[OHLCV]] = {
            symbol: list(bars) for symbol, bars in raw_history.items()
        }
        for symbol, ts in decisions_ts.items():
            bars_by_symbol.setdefault(symbol, [])
            _ = ts
        evaluations = self._outcomes.resolve_pending(
            traces=traces,
            bars_by_symbol=bars_by_symbol,
            already_resolved=resolved_ids,
            created_at_ms=session_started_ms,
        )
        resolved = 0
        pending = 0
        updates = 0
        for evaluation in evaluations:
            if evaluation.status is OutcomeStatus.PENDING_OUTCOME:
                pending += 1
                continue
            record = evaluation.record
            if record is None:
                continue
            if record.outcome_key in seen_keys:
                continue  # idempotent: decision + horizon ⇒ exactly one outcome
            self._trace_store.append_outcome(record)
            seen_keys.add(record.outcome_key)
            resolved += 1
            cell = self._performance.update_from_outcome(record, timeframe=self._timeframe)
            self._log.info(
                "autonomous.outcome.resolved",
                decision_id=record.decision_id,
                mode=record.mode.value,
                net_bps=round(record.net_hypothetical_bps, 4),
                sample_size=cell.sample_size,
            )
            updates += 1
        return resolved, pending, updates


@dataclasses.dataclass(frozen=True, slots=True)
class _TerminalDecision:
    """Minimal decision shape for terminal NO_TRADE traces."""

    mode: DecisionMode
    reason: str
    classification: str
    shadow: None = None
    order_authorised: bool = False


def _safe_context(context: Any) -> dict[str, Any]:
    try:
        return dict(context.to_dict())
    except Exception:
        return {"unserialisable_context": type(context).__name__}


def _git_commit() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"
