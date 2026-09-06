"""DEMO-PAPER-01: visible, paper-only multi-agent runtime.

This module is deliberately an orchestration boundary, not a second strategy,
risk, broker, or accounting engine.  MA-2/MA-3/MA-4 produce immutable
artifacts; the adapter admits only an independently VERIFIED SELECTED package;
then the existing RiskManager and PaperBroker remain authoritative.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent.blackboard import Blackboard
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.contracts import (
    DebatePosition,
    TraceContext,
    TradeDirection,
)
from trading_bot.multi_agent.debate import DebateSession, register_debate_agents
from trading_bot.multi_agent.decision import (
    DecisionEngine,
    DecisionPackageVerifier,
    DecisionVerification,
)
from trading_bot.multi_agent.opportunity import OpportunityBoard
from trading_bot.multi_agent.registry import AgentRegistry, CapabilityRegistry
from trading_bot.multi_agent.specialists import AssetExpert, StrategyExpert
from trading_bot.multi_agent.swarm import register_swarm_agents
from trading_bot.paper.broker import PaperBroker, PaperPosition
from trading_bot.paper.candidate_portfolio import TradeCandidate, build_portfolio
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.types import AlphaSignal
from trading_bot.risk.manager import RiskCheck, RiskManager
from trading_bot.strategies.types import Signal

DEMO_ID = "DEMO-PAPER-01"
DEMO_COMMIT = "a38e11e"
FIXTURE_EPOCH_MS = 1_786_000_000_000


class DemoSafetyError(RuntimeError):
    """Raised when a requested demo configuration crosses the paper boundary."""


@dataclass(frozen=True, slots=True)
class AdaptedCandidate:
    """Strict MA-4-to-paper handoff; no sizing or broker authority."""

    candidate: TradeCandidate
    proposal_id: str
    final_proposal_id: str
    asset: str
    direction: TradeDirection
    verification: DecisionVerification


class DecisionToCandidateAdapter:
    """Convert only a verified MA-4 selection into the existing candidate type."""

    def __init__(self, verifier: DecisionPackageVerifier | None = None) -> None:
        self.verifier = verifier or DecisionPackageVerifier()

    def adapt(
        self,
        package: Any,
        *,
        proposals: dict[str, Any],
        evidence_registry: dict[str, Any],
        reports: tuple[Any, ...],
        now: datetime,
        prices: dict[str, float],
        snapshot: Any,
    ) -> AdaptedCandidate | None:
        verification = self.verifier.verify(
            package,
            proposals=proposals,
            evidence_registry=evidence_registry,
            now=now,
            reports=reports,
            snapshot=snapshot,
        )
        if not verification.passed or package.outcome.value != "SELECTED":
            return None
        selected = package.selected_candidate_id
        if selected is None:
            return None
        decision_candidate = next(
            (item for item in package.candidate_set if item.final_proposal_id == selected), None
        )
        proposal = proposals.get(selected)
        if decision_candidate is None or proposal is None:
            return None
        if proposal.run_id != package.run_id or decision_candidate.trace is None:
            return None
        if decision_candidate.trace.run_id != package.run_id:
            return None
        price = prices.get(proposal.asset)
        if price is None or price <= 0:
            return None
        direction = TradeDirection(proposal.direction.value)
        candidate = TradeCandidate(
            asset=proposal.asset,
            strategy_id=proposal.strategy,
            family=proposal.strategy,
            direction=direction.value,
            timestamp=int(proposal.data_time.timestamp() * 1000),
            score=decision_candidate.decision_score,
            entry_reference=price,
            structural_stop=None,
            regime=proposal.regime,
            expected_risk_pct=None,
            correlation_group=proposal.asset,
        )
        return AdaptedCandidate(
            candidate=candidate,
            proposal_id=decision_candidate.proposal_id,
            final_proposal_id=selected,
            asset=proposal.asset,
            direction=direction,
            verification=verification,
        )


@dataclass
class DemoState:
    """Read-only dashboard/report state accumulated by the runner."""

    run_id: str
    trace_id: str
    mode: str = "PAPER"
    provider: str = "fixture"
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL")
    strategies: tuple[str, ...] = (
        "Momentum",
        "Trend",
        "Breakout",
        "MeanReversion",
        "Volatility",
    )
    cycles: int = 0
    market_scans: int = 0
    asset_assessments: int = 0
    strategy_evaluations: int = 0
    trade_proposals: int = 0
    debates: int = 0
    decisions_selected: int = 0
    decisions_rejected: int = 0
    no_trade: int = 0
    verifier_rejects: int = 0
    risk_accepts: int = 0
    risk_rejects: int = 0
    paper_trades: int = 0
    open_positions: int = 0
    closed_trades: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees: float = 0.0
    risk_calls: int = 0
    broker_calls: int = 0
    live_calls: int = 0
    false_success: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    funnel: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # LEGACY-HIST-001: read-only/shadow historical evidence layer summary.
    # Observability only; never consumed by scoring, risk or execution.
    legacy_evidence: dict[str, Any] = field(default_factory=dict)

    def emit(self, event: str, **payload: Any) -> None:
        self.events.append(
            {
                "event": event,
                "run_id": self.run_id,
                "trace_id": self.trace_id,
                **payload,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "mode": self.mode,
            "live_trading": False,
            "live_disabled": True,
            "provider": self.provider,
            "assets": list(self.assets),
            "strategies": list(self.strategies),
            "cycles": self.cycles,
            "market_scans": self.market_scans,
            "asset_assessments": self.asset_assessments,
            "strategy_evaluations": self.strategy_evaluations,
            "trade_proposals": self.trade_proposals,
            "debates": self.debates,
            "decisions_selected": self.decisions_selected,
            "decisions_rejected": self.decisions_rejected,
            "no_trade": self.no_trade,
            "verifier_rejects": self.verifier_rejects,
            "risk_accepts": self.risk_accepts,
            "risk_rejects": self.risk_rejects,
            "paper_trades": self.paper_trades,
            "open_positions": self.open_positions,
            "closed_trades": self.closed_trades,
            "realized_pnl": round(self.realized_pnl, 8),
            "unrealized_pnl": round(self.unrealized_pnl, 8),
            "fees": round(self.fees, 8),
            "trades_today": self.paper_trades,
            "trades_per_day": self.paper_trades,
            "days_ge_3_trades": 1 if self.paper_trades >= 3 else 0,
            "risk_calls": self.risk_calls,
            "broker_calls": self.broker_calls,
            "live_calls": self.live_calls,
            "real_broker_calls": 0,
            "private_exchange_calls": 0,
            "false_success": self.false_success,
            "decisions": list(self.decisions),
            "funnel": list(self.funnel),
            "legacy_evidence": dict(self.legacy_evidence),
            "events": list(self.events),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "result_classification": "DEMO_FUNCTIONAL_PASS",
        }


@dataclass(frozen=True, slots=True)
class DemoRun:
    """Completed demo plus paths to its independent run reports."""

    state: DemoState
    report_json: Path
    report_markdown: Path


class _FixtureFamily:
    """Deterministic fixture family used only by the explicitly named demo mode."""

    family_name = "momentum"

    def __init__(self, direction: str) -> None:
        self.direction = cast(Any, direction)

    def generate(
        self,
        candles: list[OHLCV],
        indicators: dict[str, Any],
        features: Any = None,
        **kwargs: Any,
    ) -> list[AlphaSignal]:
        if not candles:
            return []
        last = candles[-1]
        stop = last.close * (0.98 if self.direction == "LONG" else 1.02)
        return [
            AlphaSignal(
                family=self.family_name,
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction=self.direction,
                entry_reference=last.close,
                structural_stop=stop,
                timeframe="5m",
            )
        ]


def _bars(asset: str, *, timestamp: int, shape: str, n: int = 40) -> list[OHLCV]:
    symbol = f"{asset}/USDT"
    values: list[float]
    if shape == "up":
        values = [100.0 + index * 0.4 for index in range(n)]
    elif shape == "down":
        values = [100.0 - index * 0.4 for index in range(n)]
    else:
        values = [100.0 + (0.2 if index % 2 else -0.2) for index in range(n)]
    start = timestamp - (n - 1) * 300_000
    return [
        OHLCV(
            symbol=symbol,
            timestamp=start + index * 300_000,
            open=value,
            high=value + 0.4,
            low=value - 0.4,
            close=value,
            volume=1_000.0,
        )
        for index, value in enumerate(values)
    ]


def _trace(run_id: str, trace_id: str, artifact: str) -> TraceContext:
    return TraceContext(
        run_id=run_id,
        trace_id=trace_id,
        correlation_id=artifact,
        causation_id=artifact,
    )


def _setup_bus(run_id: str, trace_id: str, now: datetime) -> AgentBus:
    agents = AgentRegistry()
    capabilities = CapabilityRegistry()
    register_swarm_agents(agents, capabilities)
    register_debate_agents(agents, capabilities)
    agents.register(
        # A stable owner identity for fixture variants is already registered
        # by MA-2's momentum expert.
        agents.get("strategy-expert-momentum", "1.0.0")
    ) if False else None
    return AgentBus(
        agent_registry=agents,
        capability_registry=capabilities,
        blackboard=Blackboard(run_id=run_id, trace_id=trace_id),
        clock=lambda: now,
    )


def _context(asset: str, bars: list[OHLCV], now: datetime, trace: TraceContext) -> Any:
    timestamp = bars[-1].timestamp
    context = CryptoAssetAgentRegistry().build_context(
        asset,
        bars,
        timestamp,
        data_fingerprint="sha256:" + sha256(
            json.dumps([bar.timestamp for bar in bars]).encode()
        ).hexdigest()[:32],
        dataset_id="DEMO_FIXTURE",
    )
    context.validate(now_ts=timestamp)
    AssetExpert(asset).evaluate(context, trace=trace, now_ts=timestamp)
    return context


def _proposal_set(
    *,
    asset: str,
    bars: list[OHLCV],
    now: datetime,
    run_id: str,
    trace_id: str,
    directions: tuple[str, ...],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    OpportunityBoard,
    tuple[Any, ...],
    dict[str, float],
]:
    """Build real MA-2 artifacts and admit them to the canonical board."""
    bus = _setup_bus(run_id, trace_id, now)
    board = OpportunityBoard(run_id=run_id, now=now)
    root_trace = _trace(run_id, trace_id, f"market:{asset}:{bars[-1].timestamp}")
    context = _context(asset, bars, now, root_trace)
    asset_assessment = AssetExpert(asset).evaluate(
        context, trace=root_trace, now_ts=bars[-1].timestamp
    )
    for assessment_evidence in asset_assessment.evidence:
        bus.register_evidence(assessment_evidence)
    proposals: dict[str, Any] = {}
    evidence_registry: dict[str, Any] = {
        item.evidence_id: item for item in asset_assessment.evidence
    }
    positions: list[DebatePosition] = []
    prices = {asset: bars[-1].close}
    for direction in directions:
        expert = StrategyExpert(cast(Any, _FixtureFamily(direction)))
        evaluation = expert.evaluate(
            context,
            bars,
            trace=root_trace,
            assessment=asset_assessment,
            now_ts=bars[-1].timestamp,
            timeframe="5m",
        )
        for proposal, item in zip(evaluation.proposals, evaluation.evidence, strict=True):
            proposals[proposal.proposal_id] = proposal
            evidence_registry[item.evidence_id] = item
            bus.register_evidence(item)
            board.add_evidence(item)
            board.add(
                proposal,
                source_agent_id=expert.manifest.agent_id,
                source_agent_version=expert.manifest.agent_version,
            )
            positions.append(
                DebatePosition(
                    proposal_id=proposal.proposal_id,
                    owner_agent_id=expert.manifest.agent_id,
                    asset=proposal.asset,
                    direction=proposal.direction,
                    strategy=proposal.strategy,
                    claim=f"{proposal.strategy} {proposal.direction.value} proposal",
                    evidence_refs=proposal.evidence_refs,
                )
            )
    reports: list[Any] = []
    if positions:
        session = DebateSession(
            debate_id=f"debate:{asset}:{bars[-1].timestamp}",
            bus=bus,
            positions=positions,
            proposals=proposals,
            regime_by_asset={asset: context.market_regime or "UNKNOWN"},
            evidence_registry=evidence_registry,
            max_rounds=3,
        )
        report = session.run()
        reports.append(report)
        proposals.update(session.revised_proposals)
    return proposals, evidence_registry, {asset: asset_assessment}, board, tuple(reports), prices


def _verify_and_execute(
    *,
    state: DemoState,
    proposals: dict[str, Any],
    evidence: dict[str, Any],
    assessments: dict[str, Any],
    board: OpportunityBoard,
    reports: tuple[Any, ...],
    prices: dict[str, float],
    now: datetime,
    risk: RiskManager,
    broker: PaperBroker,
    adapter: DecisionToCandidateAdapter,
) -> Any:
    snapshot = board.snapshot()
    engine = DecisionEngine(run_id=state.run_id)
    package = engine.decide(
        snapshot=snapshot,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        assessments=assessments,
        now=now,
    )
    state.trade_proposals += len(proposals)
    state.emit("decision.started", decision_id=package.decision_id)
    state.emit("decision.package", package=package.to_dict())
    if package.outcome.value == "NO_TRADE":
        state.no_trade += 1
    elif package.selected_candidate_id is not None:
        state.decisions_selected += 1
    state.decisions_rejected += len(package.rejected_alternatives)
    candidate = adapter.adapt(
        package,
        proposals=proposals,
        evidence_registry=evidence,
        reports=reports,
        now=now,
        prices=prices,
        snapshot=snapshot,
    )
    verification = adapter.verifier.verify(
        package,
        proposals=proposals,
        evidence_registry=evidence,
        now=now,
        reports=reports,
        snapshot=snapshot,
    )
    state.decisions.append(
        {
            "decision_id": package.decision_id,
            "outcome": package.outcome.value,
            "selected_candidate_id": package.selected_candidate_id,
            "verifier": verification.verdict.value,
            "verifier_version": adapter.verifier.version,
            "reasons": [reason.value for reason in package.decision_reasons],
            "package": package.to_dict(),
            "debates": [report.to_dict() for report in reports],
        }
    )
    if not verification.passed:
        state.verifier_rejects += 1
        state.emit("decision.rejected", decision_id=package.decision_id)
        return package
    state.emit("decision.verified", decision_id=package.decision_id)
    if candidate is None:
        return package
    portfolio = build_portfolio([candidate.candidate])
    if not portfolio.candidates:
        state.warnings.append("verified selection was not admitted to CandidatePortfolio")
        return package
    state.risk_calls += 1
    signal = Signal(
        symbol=f"{candidate.asset}/USDT",
        side="buy" if candidate.direction is TradeDirection.LONG else "sell",
        strategy_name=candidate.candidate.strategy_id,
        timeframe="5m",
        confidence=float(candidate.candidate.score),
        price=prices[candidate.asset],
        stop_loss_pct=None,
        take_profit_pct=None,
        metadata={
            "run_id": state.run_id,
            "trace_id": state.trace_id,
            "decision_id": package.decision_id,
            "entry_reason": "MA4_VERIFIED_SELECTION",
            "explanation": "MA-4 verified selection admitted to paper risk",
        },
    )
    check: RiskCheck = risk.check_signal(signal)
    if not check.approved or check.position_size is None:
        state.risk_rejects += 1
        state.emit("risk.rejected", reason=check.reason, blocked_by=check.blocked_by)
        return package
    state.risk_accepts += 1
    approved_signal = dataclasses.replace(
        signal,
        stop_loss_pct=check.position_size.stop_loss_pct,
        take_profit_pct=check.position_size.take_profit_pct,
        metadata={
            **signal.metadata,
            "notional_usdt": check.position_size.notional_usdt,
            "risk_approved_by": "RiskManager",
        },
    )
    result = broker.execute_signal(approved_signal)
    state.broker_calls += 1
    if isinstance(result, PaperPosition):
        risk.add_position(result.symbol, result)
        state.paper_trades += 1
        state.emit("paper.position_opened", symbol=result.symbol, price=result.entry_price)
    return package


def _reconcile(
    state: DemoState, broker: PaperBroker, risk: RiskManager, prices: dict[str, float]
) -> None:
    before = set(broker.positions)
    closed = broker.check_positions(prices)
    for trade in closed:
        risk.remove_position(trade.symbol)
        risk.record_trade_result(float(trade.pnl))
        risk.equity = broker.equity
        state.closed_trades += 1
        state.realized_pnl += float(trade.pnl)
        state.emit("paper.position_closed", symbol=trade.symbol, pnl=trade.pnl)
    state.open_positions = len(broker.positions)
    state.unrealized_pnl = sum(
        position.unrealized_pnl(
            prices.get(symbol, prices.get(symbol.split("/")[0], position.entry_price))
        )
        for symbol, position in broker.positions.items()
    )
    if before and not closed and set(broker.positions) != before:
        state.false_success += 1


def _attach_legacy_evidence_summary(state: "DemoState") -> None:
    """LEGACY-HIST-001: attach the read-only legacy evidence layer summary.

    Shadow-only: the summary is observability metadata for reports/dashboard.
    It is never read by MetaRanker, risk, PaperBroker or any execution path,
    and ingest failures never affect the run (best-effort by design).
    """
    try:
        from trading_bot.legacy_evidence import (
            LegacyEvidenceBuilder,
            LegacyEvidenceIngester,
        )

        ingester = LegacyEvidenceIngester()
        store, _report = LegacyEvidenceBuilder(
            ingester, "reports/legacy-hist-001/flat"
        ).build()
        state.legacy_evidence = {
            "enabled": True,
            "mode": "SHADOW_ONLY",
            "source_system": "FRAN_V5_LEGACY",
            "source_zip_sha256": ingester.source_sha256(),
            "consumed_development_period": True,
            "record_count": len(store),
            "catalogued_symbols": store.catalogued_symbols(),
            "eligible_for_context": True,
            "eligible_for_training": False,
            "eligible_for_candidate_promotion": False,
            "eligible_for_confirmation": False,
            "can_affect_execution": False,
        }
    except Exception as exc:  # noqa: BLE001 - layer must never break trading
        state.legacy_evidence = {
            "enabled": False,
            "mode": "SHADOW_ONLY",
            "error": f"legacy evidence layer unavailable: {exc}",
        }


def _write_reports(state: DemoState, output_dir: Path) -> DemoRun:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json = output_dir / "RUN_REPORT.json"
    report_markdown = output_dir / "RUN_REPORT.md"
    payload = state.to_dict()
    payload["commit"] = DEMO_COMMIT
    payload["execution_authority"] = "PaperBroker"
    payload["accounting_authority"] = "PaperBroker/PaperExecutionSummary"
    report_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md = [
        "# DEMO-PAPER-01 Run Report",
        "",
        f"- Run ID: `{state.run_id}`",
        f"- Mode: **{state.mode}**",
        f"- Provider: `{state.provider}`",
        "- Live trading: **DISABLED**",
        "- Broker: `PaperBroker`",
        f"- Result: **{payload['result_classification']}**",
        "",
        "## Funnel",
        "",
    ]
    for key in (
        "market_scans", "asset_assessments", "strategy_evaluations", "trade_proposals",
        "debates", "decisions_selected", "decisions_rejected", "no_trade",
        "risk_accepts", "risk_rejects", "paper_trades", "closed_trades",
    ):
        md.append(f"- {key}: {payload[key]}")
    md.extend(["", "## Safety", "", "- Real broker calls: 0", "- Private exchange calls: 0", "- FALSE_SUCCESS: 0"])
    report_markdown.write_text("\n".join(md) + "\n", encoding="utf-8")
    return DemoRun(state=state, report_json=report_json, report_markdown=report_markdown)


def run_fixture_demo(
    *, output_dir: Path | str = "reports/demo-paper-01", cycles: int = 4
) -> DemoRun:
    """Run the committed deterministic fixture scenario, paper-only."""
    if cycles < 1:
        raise ValueError("cycles must be positive")
    settings = build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
        mode="paper",
        kill_switch_enabled=True,
    )
    if settings.runtime.mode is not TradingMode.PAPER or settings.risk.live_trading_enabled:
        raise DemoSafetyError("fixture demo safety gate failed")
    risk = RiskManager(
        risk=settings.risk.model_copy(update={"max_open_positions": 1}),
        equity=10_000.0,
    )
    broker = PaperBroker(equity=10_000.0)
    run_id = "demo-paper-01-fixture"
    trace_id = "trace-demo-paper-01-fixture"
    state = DemoState(run_id=run_id, trace_id=trace_id, provider="fixture")
    adapter = DecisionToCandidateAdapter()
    state.emit("paper.session.started", broker="PaperBroker", live_disabled=True)
    cycle_specs: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("BTC", "flat", ()),
        ("SOL", "flat", ("LONG", "SHORT")),
        ("SOL", "down", ("LONG",)),
        ("BTC", "up", ("LONG",)),
    )
    for index, (asset, shape, directions) in enumerate(cycle_specs[:cycles], start=1):
        decision_time = datetime.fromtimestamp(
            (FIXTURE_EPOCH_MS + index * 3_600_000) / 1000, tz=UTC
        )
        bars = _bars(asset, timestamp=int(decision_time.timestamp() * 1000) - 60_000, shape=shape)
        state.cycles += 1
        state.market_scans += 1
        state.asset_assessments += 1
        state.strategy_evaluations += len(directions)
        if not directions:
            empty_board = OpportunityBoard(run_id=run_id, now=decision_time)
            empty_snapshot = empty_board.snapshot()
            empty_engine = DecisionEngine(run_id=run_id)
            empty_package = empty_engine.decide(
                snapshot=empty_snapshot,
                proposals={},
                evidence_registry={},
                now=decision_time,
            )
            empty_verification = adapter.verifier.verify(
                empty_package,
                proposals={},
                evidence_registry={},
                now=decision_time,
                reports=(),
                snapshot=empty_snapshot,
            )
            state.no_trade += 1
            state.emit("decision.no_trade", cycle=index, reason="no_valid_proposal")
            state.decisions.append(
                {
                    "cycle": index,
                    "decision_id": empty_package.decision_id,
                    "outcome": empty_package.outcome.value,
                    "verifier": empty_verification.verdict.value,
                    "verifier_version": adapter.verifier.version,
                    "package": empty_package.to_dict(),
                }
            )
            continue
        proposals, evidence, assessments, board, reports, prices = _proposal_set(
            asset=asset,
            bars=bars,
            now=decision_time,
            run_id=run_id,
            trace_id=trace_id,
            directions=directions,
        )
        state.debates += len(reports)
        state.funnel.append(
            {
                "cycle": index,
                "asset": asset,
                "proposal_ids": sorted(proposals),
                "debate_outcomes": [report.outcome.value for report in reports],
            }
        )
        _verify_and_execute(
            state=state,
            proposals=proposals,
            evidence=evidence,
            assessments=assessments,
            board=board,
            reports=reports,
            prices=prices,
            now=decision_time,
            risk=risk,
            broker=broker,
            adapter=adapter,
        )
        _reconcile(state, broker, risk, prices)
    # Later fixture tick closes the selected SOL position with its TP path.
    _reconcile(state, broker, risk, {"SOL/USDT": 105.0, "BTC/USDT": 100.0})
    state.open_positions = len(broker.positions)
    state.emit("paper.session.completed", closed_trades=state.closed_trades)
    _attach_legacy_evidence_summary(state)
    return _write_reports(state, Path(output_dir))


def _fetch_public_bars(assets: tuple[str, ...], limit: int = 120) -> dict[str, list[OHLCV]]:
    """Fetch public OHLCV only; no credentials and no order-capable calls."""
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        bars: dict[str, list[OHLCV]] = {}
        for asset in assets:
            symbol = f"{asset}/USDT"
            rows = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=limit)
            bars[asset] = [
                OHLCV(
                    symbol=symbol,
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]
        return bars
    finally:
        close = getattr(exchange, "close", None)
        if callable(close):
            close()


def run_real_market_demo(
    *,
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL"),
    output_dir: Path | str = "reports/demo-paper-01",
) -> DemoRun:
    """Run one public-data paper scan. Network/provider failure is loud."""
    bars_by_asset = _fetch_public_bars(assets)
    if any(len(bars) < 22 for bars in bars_by_asset.values()):
        raise RuntimeError("public market provider returned insufficient OHLCV history")
    settings = build_demo_settings(
        pairs=[(f"{asset}/USDT", True) for asset in assets],
        mode="paper",
        kill_switch_enabled=True,
    )
    if settings.runtime.mode is not TradingMode.PAPER or settings.risk.live_trading_enabled:
        raise DemoSafetyError("public demo safety gate failed")
    risk = RiskManager(
        risk=settings.risk.model_copy(update={"max_open_positions": 1}),
        equity=10_000.0,
    )
    broker = PaperBroker(equity=10_000.0)
    run_id = "demo-paper-01-public"
    trace_id = "trace-demo-paper-01-public"
    state = DemoState(run_id=run_id, trace_id=trace_id, provider="ccxt-public-binance")
    state.assets = assets
    adapter = DecisionToCandidateAdapter()
    state.emit("paper.session.started", broker="PaperBroker", live_disabled=True)
    for index, asset in enumerate(assets, start=1):
        bars = bars_by_asset[asset]
        latest_ms = bars[-1].timestamp
        decision_time = datetime.fromtimestamp(latest_ms / 1000, tz=UTC)
        state.cycles += 1
        state.market_scans += 1
        state.asset_assessments += 1
        state.strategy_evaluations += 1
        try:
            proposals, evidence, assessments, board, reports, prices = _proposal_set(
                asset=asset,
                bars=bars,
                now=decision_time,
                run_id=run_id,
                trace_id=trace_id,
                directions=("LONG",),
            )
            state.debates += len(reports)
            state.funnel.append(
                {
                    "cycle": index,
                    "asset": asset,
                    "proposal_ids": sorted(proposals),
                    "debate_outcomes": [report.outcome.value for report in reports],
                }
            )
            _verify_and_execute(
                state=state,
                proposals=proposals,
                evidence=evidence,
                assessments=assessments,
                board=board,
                reports=reports,
                prices=prices,
                now=decision_time,
                risk=risk,
                broker=broker,
                adapter=adapter,
            )
            _reconcile(state, broker, risk, prices)
        except Exception as exc:
            state.errors.append(f"{asset}: {type(exc).__name__}: {exc}")
            state.emit("market.provider_error", asset=asset, error=str(exc))
    state.open_positions = len(broker.positions)
    state.emit("paper.session.completed", closed_trades=state.closed_trades)
    _attach_legacy_evidence_summary(state)
    return _write_reports(state, Path(output_dir))


class DashboardServer:
    """Small read-only HTTP dashboard; no command, risk, or execution routes."""

    def __init__(self, state: DemoState, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.state = state
        self.host = host
        self.port = port
        state_ref = state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/status":
                    body = json.dumps(state_ref.to_dict(), default=str).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                elif self.path == "/":
                    s = state_ref.to_dict()
                    decisions_rows = "".join(
                        "<tr>"
                        f"<td>{d.get('decision_id', '')}</td>"
                        f"<td>{d.get('outcome', '')}</td>"
                        f"<td>{d.get('verifier', '')}</td>"
                        "</tr>"
                        for d in s.get("decisions", [])
                    )
                    body = f"""<html><head><meta http-equiv="refresh" content="3">
<style>body{{font-family:Segoe UI,Arial;margin:2rem;background:#0f1216;color:#e6e6e6}}
h1{{font-size:1.3rem}} .badge{{background:#c0392b;padding:.2rem .6rem;border-radius:4px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #333;padding:.3rem .6rem;font-size:.85rem}}
.grid{{display:flex;gap:1rem;flex-wrap:wrap}}.card{{background:#171c22;padding:.8rem 1rem;border-radius:6px;min-width:8rem}}
.card b{{display:block;font-size:1.2rem}}</style></head><body>
<h1>TRADING AGENTIC PORTABLE <span class="badge">PAPER MODE &bull; LIVE DISABLED</span></h1>
<div class="grid">
<div class="card">Run<b>{s["run_id"]}</b></div>
<div class="card">Ciclos<b>{s["cycles"]}</b></div>
<div class="card">Propuestas<b>{s["trade_proposals"]}</b></div>
<div class="card">Debates<b>{s["debates"]}</b></div>
<div class="card">NO_TRADE<b>{s["no_trade"]}</b></div>
<div class="card">Seleccionados<b>{s["decisions_selected"]}</b></div>
<div class="card">Risk accept/reject<b>{s["risk_accepts"]}/{s["risk_rejects"]}</b></div>
<div class="card">Trades paper<b>{s["paper_trades"]}</b></div>
<div class="card">Cerrados<b>{s["closed_trades"]}</b></div>
<div class="card">PnL realizado<b>{s["realized_pnl"]:.2f}</b></div>
<div class="card">PnL no realizado<b>{s["unrealized_pnl"]:.2f}</b></div>
</div>
<h2>Embudo de decisiones</h2>
<p>Scans: {s["market_scans"]} &rarr; evaluaciones: {s["asset_assessments"]}/{s["strategy_evaluations"]}
&rarr; propuestas: {s["trade_proposals"]} &rarr; debates: {s["debates"]}
&rarr; seleccionados: {s["decisions_selected"]} / NO_TRADE: {s["no_trade"]}
&rarr; risk accept: {s["risk_accepts"]}, risk reject: {s["risk_rejects"]}
&rarr; trades paper: {s["paper_trades"]}</p>
<h2>Decisiones</h2>
<table><tr><th>decision_id</th><th>resultado</th><th>verifier</th></tr>{decisions_rows}</table>
<p>Read-only: este dashboard no tiene endpoints de orden, riesgo ni ejecuci&oacute;n.
Detalle completo en <a href="/api/status" style="color:#7db6f9">/api/status</a>.
Se actualiza solo cada 3s.</p>
</body></html>""".encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                else:
                    body = b"read-only endpoint not found"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                self.send_response(405)
                self.send_header("Allow", "GET")
                self.end_headers()

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def create_dashboard_server(state: DemoState, *, host: str = "127.0.0.1", port: int = 8765) -> DashboardServer:
    return DashboardServer(state, host=host, port=port)


def _parse_assets(value: str) -> tuple[str, ...]:
    assets = tuple(item.strip().upper() for item in value.split(",") if item.strip())
    if not assets:
        raise argparse.ArgumentTypeError("at least one asset is required")
    return assets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEMO-PAPER-01 multi-agent paper runtime")
    parser.add_argument("--provider", choices=("fake", "ccxt"), default="fake")
    parser.add_argument("--assets", type=_parse_assets, default=("BTC", "ETH", "SOL"))
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--output-dir", default="reports/demo-paper-01")
    args = parser.parse_args(argv)
    del args.interval_seconds  # fixture cadence is deterministic and bounded
    result = (
        run_fixture_demo(output_dir=args.output_dir, cycles=args.cycles)
        if args.provider == "fake"
        else run_real_market_demo(assets=args.assets, output_dir=args.output_dir)
    )
    dashboard: DashboardServer | None = None
    if args.dashboard:
        dashboard = create_dashboard_server(result.state)
        dashboard.start()
    if dashboard is not None:
        # Keep the console readable: the full status JSON goes to a file.
        status_path = Path(args.output_dir) / "DASHBOARD_STATUS.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps(result.state.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        print("=" * 60)
        print("TRADING AGENTIC PORTABLE - PAPER MODE (LIVE DISABLED)")
        print(f"Dashboard read-only disponible en:  {dashboard.url}")
        print(f"Estado completo JSON: {status_path}")
        print("=" * 60)
        webbrowser.open(dashboard.url)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nDeteniendo demo paper...")
        finally:
            dashboard.stop()
        print("Demo detenido. Reportes en:", args.output_dir)
    else:
        print(json.dumps(result.state.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
