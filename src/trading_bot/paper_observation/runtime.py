"""PAPER-OBSERVATION-CAMPAIGN-01 runtime.

Runs the certified DEMO-PAPER-01 chain (MA-2 swarm → opportunity board →
MA-3 debate → MA-4 decision → DecisionPackageVerifier-v3 → certified
DecisionToCandidateAdapter → RiskManager → PaperBroker → reconciliation)
under a durable campaign shell. This module NEVER modifies certified
behavior: strategy thresholds, MetaRanker, debate, decision rules, the
verifier, RiskManager limits, sizing, fees, and slippage are reused
unchanged. The frozen strategy universe is evaluated through the real
certified families (momentum, trend, breakout, mean_reversion, volatility).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import signal
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent.blackboard import Blackboard
from trading_bot.multi_agent.bus import AgentBus
from trading_bot.multi_agent.contracts import DebatePosition, TraceContext, TradeDirection
from trading_bot.multi_agent.debate import DebateSession, register_debate_agents
from trading_bot.multi_agent.decision import DecisionEngine
from trading_bot.multi_agent.opportunity import OpportunityBoard
from trading_bot.multi_agent.registry import AgentRegistry, CapabilityRegistry
from trading_bot.multi_agent.specialists import AssetExpert, StrategyExpert
from trading_bot.multi_agent.swarm import register_swarm_agents
from trading_bot.paper.broker import PaperBroker, PaperPosition
from trading_bot.paper.candidate_portfolio import build_portfolio
from trading_bot.paper_observation.state import (
    SCHEMA_VERSION,
    CampaignStateStore,
    DurableCampaignState,
    daily_report_payload,
    day_key,
    performance_metrics,
    utc_now_iso,
)
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.families import (
    BreakoutFamily,
    MeanReversionFamily,
    MomentumFamily,
    TrendFamily,
    VolatilityFamily,
)
from trading_bot.risk.manager import RiskManager
from trading_bot.strategies.types import Signal

CAMPAIGN_NAME = "paper-observation-01"
DEFAULT_OUTPUT_DIR = "reports/paper-observation-01"
STALE_AFTER_MS = 900_000  # mirrors AssetContext N5 staleness window
FUTURE_TOLERANCE_MS = 60_000
FIXTURE_EPOCH_MS = 1_786_000_000_000

FAMILIES: dict[str, Any] = {
    "momentum": MomentumFamily,
    "trend": TrendFamily,
    "breakout": BreakoutFamily,
    "mean_reversion": MeanReversionFamily,
    "volatility": VolatilityFamily,
}
_FAMILY_CACHE: dict[str, Any] = {}


class CampaignSafetyError(RuntimeError):
    """Raised when a requested campaign configuration crosses the paper boundary."""


class CampaignIdentityError(RuntimeError):
    """Raised when resume identity does not match durable campaign state."""


def _family(name: str) -> Any:
    if name not in _FAMILY_CACHE:
        _FAMILY_CACHE[name] = FAMILIES[name]()
    return _FAMILY_CACHE[name]


def campaign_id_from(name: str | None = None) -> str:
    """Stable campaign identity: derived from the name only, so ``--resume``
    finds the same campaign on a later day (the creation timestamp lives in
    ``campaign_start``, §5)."""
    base = (name or CAMPAIGN_NAME).strip() or CAMPAIGN_NAME
    slug = base.lower().replace(" ", "-")
    return f"poc01-{slug}-001"


def campaign_dir_for(output_dir: Path | str, campaign_id: str) -> Path:
    return Path(output_dir) / campaign_id


def implementation_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()[:12]
    except Exception:
        return ""


class _TrackedFamilies:
    """Counts per-strategy evaluations without altering family behavior."""

    def __init__(self, name: str, counters: dict[str, int]) -> None:
        self._inner = _family(name)
        self._name = name
        self._counters = counters

    @property
    def family_name(self) -> str:
        name: str = self._inner.family_name
        return name

    def generate(self, *args: Any, **kwargs: Any) -> list[Any]:
        self._counters[self._name] = self._counters.get(self._name, 0) + 1
        result: list[Any] = self._inner.generate(*args, **kwargs)
        return result


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
    return AgentBus(
        agent_registry=agents,
        capability_registry=capabilities,
        blackboard=Blackboard(run_id=run_id, trace_id=trace_id),
        clock=lambda: now,
    )


def _context(asset: str, bars: list[OHLCV], dataset_id: str) -> Any:
    from hashlib import sha256

    timestamp = bars[-1].timestamp
    context = CryptoAssetAgentRegistry().build_context(
        asset,
        bars,
        timestamp,
        data_fingerprint="sha256:"
        + sha256(json.dumps([b.timestamp for b in bars]).encode()).hexdigest()[:32],
        dataset_id=dataset_id,
    )
    context.validate(now_ts=timestamp)
    return context


def _data_health(bars: list[OHLCV]) -> dict[str, Any]:
    stamps = [b.timestamp for b in bars]
    duplicates = len(stamps) - len(set(stamps))
    gaps = sum(1 for a, b in zip(stamps, stamps[1:], strict=False) if b - a > 300_000)  # noqa: RUF007
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    future = sum(1 for t in stamps if t > now_ms + FUTURE_TOLERANCE_MS)
    return {
        "duplicate_candles": duplicates,
        "gaps": gaps,
        "future_timestamps": future,
        "last_market_timestamp": stamps[-1] if stamps else None,
    }


def _public_bars(assets: tuple[str, ...], *, limit: int = 150) -> dict[str, list[OHLCV]]:
    """Fetch public OHLCV only. Credentials are never read (§3/§31)."""
    import ccxt

    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            # Hard guarantee: no credentials attached, regardless of host env.
            "apiKey": "",
            "secret": "",
        }
    )
    try:
        bars: dict[str, list[OHLCV]] = {}
        for asset in assets:
            rows = exchange.fetch_ohlcv(f"{asset}/USDT", timeframe="5m", limit=limit)
            bars[asset] = [
                OHLCV(
                    symbol=f"{asset}/USDT",
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


def _fixture_bars(asset: str, cycle: int, *, shape: str = "up", n: int = 40) -> list[OHLCV]:
    """Deterministic fixture bars (tagged DEMO_FIXTURE, excluded from metrics)."""
    from trading_bot.demo.paper_multi_agent import _bars as demo_bars

    ts = FIXTURE_EPOCH_MS + cycle * 3_600_000 - 60_000
    return demo_bars(asset, timestamp=ts, shape=shape, n=n)


def _new_day() -> dict[str, Any]:
    return {
        "scans": 0, "proposals": 0, "debates": 0, "selected": 0, "no_trade": 0,
        "risk_accepts": 0, "risk_rejects": 0, "trades": 0, "closes": 0,
        "wins": 0, "losses": 0, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
        "fees": 0.0, "max_intraday_drawdown": 0.0, "data_health_events": 0,
        "runtime_errors": 0, "false_success": 0, "valid": True,
        "valid_duration_hours": 0.0,
    }


def _new_attr() -> dict[str, Any]:
    return {
        "assessments": 0, "evaluations": 0, "proposals": 0, "selected": 0,
        "risk_accepted": 0, "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0,
    }


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 6) if den else None


def _false_success_audit(state: DurableCampaignState) -> int:
    count = 0
    if state.funnel.get("PAPER_OPEN", 0) > state.funnel.get("RISK_ACCEPT", 0):
        count += 1  # opens without risk acceptance
    if state.risk_metrics["accepts"] > state.funnel.get("CANDIDATE_ADMITTED", 0):
        count += 1  # risk accepted without admitted candidate
    if state.realized_pnl and not state.closed_trades:
        count += 1  # realized PnL without closed trades
    return count


def _position_to_dict(
    pos: PaperPosition, *, decision_id: str, strategy: str, regime: str
) -> dict[str, Any]:
    return {
        "symbol": pos.symbol,
        "side": pos.side,
        "entry_price": pos.entry_price,
        "quantity": pos.quantity,
        "notional_usdt": pos.notional_usdt,
        "stop_loss_pct": pos.stop_loss_pct,
        "take_profit_pct": pos.take_profit_pct,
        "opened_at_ms": int(pos.opened_at * 1000),
        "entry_commission": pos.entry_commission,
        "decision_id": decision_id,
        "strategy": strategy,
        "regime": regime,
    }


def _position_from_dict(d: dict[str, Any]) -> PaperPosition:
    return PaperPosition(
        symbol=d["symbol"],
        side=d["side"],
        entry_price=d["entry_price"],
        quantity=d["quantity"],
        notional_usdt=d["notional_usdt"],
        stop_loss_pct=d["stop_loss_pct"],
        take_profit_pct=d["take_profit_pct"],
        opened_at=d["opened_at_ms"] / 1000,
        entry_commission=d.get("entry_commission", 0.0),
    )


class CampaignRuntime:
    """Durable, resumable PAPER campaign over the certified multi-agent chain."""

    def __init__(
        self,
        *,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        campaign_name: str | None = None,
        provider: str = "ccxt",
        assets: tuple[str, ...] = ("BTC", "ETH", "SOL"),
        strategies: tuple[str, ...] = tuple(FAMILIES),
    ) -> None:
        self.campaign_id = campaign_id_from(campaign_name)
        self.campaign_dir = campaign_dir_for(output_dir, self.campaign_id)
        self.store = CampaignStateStore(self.campaign_dir)
        self.provider = provider
        self.assets = assets
        self.strategies = strategies
        self.stop_requested = False
        self.state: DurableCampaignState | None = None

    # -- lifecycle ---------------------------------------------------------

    def install_signal_handlers(self) -> None:
        def handler(signum: int, frame: Any) -> None:
            self.stop_requested = True

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)

    def request_stop(self) -> None:
        self.stop_requested = True

    def _require_paper(self) -> None:
        settings = build_demo_settings(
            pairs=[(f"{a}/USDT", True) for a in self.assets],
            mode="paper",
            kill_switch_enabled=True,
        )
        if settings.runtime.mode is not TradingMode.PAPER or settings.risk.live_trading_enabled:
            raise CampaignSafetyError("campaign safety gate failed: PAPER mode with live disabled required")

    @property
    def dataset_id(self) -> str:
        return "REAL_PUBLIC_MARKET" if self.provider.startswith("ccxt") else "DEMO_FIXTURE"

    def new_campaign(self) -> DurableCampaignState:
        self._require_paper()
        state = DurableCampaignState(
            campaign_id=self.campaign_id,
            campaign_start=utc_now_iso(),
            campaign_status="ACTIVE",
            implementation_commit=implementation_commit(),
            provider=self.provider,
            assets=self.assets,
            strategies=self.strategies,
            run_id=f"{self.campaign_id}-run1".lower(),
            trace_id=f"trace-{self.campaign_id.lower()}",
        )
        self.state = state
        self._persist()
        return state

    def load_for_resume(self) -> DurableCampaignState:
        if not self.store.exists():
            raise CampaignIdentityError(f"no durable state at {self.store.path}")
        state = self.store.load()
        if state.campaign_id != self.campaign_id:
            raise CampaignIdentityError(
                f"campaign id mismatch: durable={state.campaign_id} requested={self.campaign_id}"
            )
        if tuple(state.assets) != tuple(self.assets):
            raise CampaignIdentityError("asset universe mismatch")
        if tuple(state.strategies) != tuple(self.strategies):
            raise CampaignIdentityError("strategy universe mismatch")
        current = implementation_commit()
        if state.implementation_commit and current and state.implementation_commit != current:
            raise CampaignIdentityError(
                f"implementation commit drift: durable={state.implementation_commit} current={current}"
            )
        if state.campaign_status not in ("ACTIVE", "STOPPED", "PAUSED"):
            raise CampaignIdentityError(f"cannot resume campaign in status {state.campaign_status}")
        state.campaign_status = "ACTIVE"
        state.heartbeat["campaign_state"] = "ACTIVE"
        state.heartbeat["resumed_at"] = utc_now_iso()
        self.state = state
        return state

    # -- broker / risk rehydration (§7) ------------------------------------

    def _rehydrate(self, state: DurableCampaignState) -> tuple[RiskManager, PaperBroker]:
        settings = build_demo_settings(
            pairs=[(f"{a}/USDT", True) for a in self.assets],
            mode="paper",
            kill_switch_enabled=True,
        )
        # Same certified-demo risk baseline: single concurrent paper position.
        # This configures the frozen RiskManager; it does not modify it.
        risk = RiskManager(
            risk=settings.risk.model_copy(update={"max_open_positions": 1}),
            equity=state.equity,
        )
        for trade in state.closed_trades:
            risk.record_trade_result(float(trade["pnl"]))
        for pos in state.open_positions:
            risk.add_position(pos["symbol"], object())
        risk.equity = state.equity
        broker = PaperBroker(equity=state.equity)
        for pos in state.open_positions:
            broker._positions[pos["symbol"]] = _position_from_dict(pos)
        return risk, broker

    def _reconcile_symbol(
        self,
        state: DurableCampaignState,
        risk: RiskManager,
        broker: PaperBroker,
        symbol: str,
        price: float,
    ) -> list[dict[str, Any]]:
        """Canonical close path for one symbol at the current market price.

        Runs before evaluation (resume recovery: TP/SL hit while the process
        was down) and after opens, so reconciliation never depends on the
        current cycle's decision outcome.
        """
        closed_out: list[dict[str, Any]] = []
        if symbol not in broker.positions:
            return closed_out
        closed = broker.check_positions({symbol: price})
        meta_by_symbol = {p["symbol"]: p for p in state.open_positions}
        for trade in closed:
            risk.remove_position(trade.symbol)
            risk.record_trade_result(float(trade.pnl))
            risk.equity = broker.equity
            close_id = f"{trade.symbol}:close:{int(trade.closed_at * 1000)}"
            state.mark_fill(close_id)
            state.bump("PAPER_CLOSE")
            pnl = float(trade.pnl)
            fees = float(getattr(trade, "entry_commission", 0.0)) + float(
                getattr(trade, "exit_commission", 0.0)
            )
            meta = meta_by_symbol.get(trade.symbol, {})
            entry = {
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_price": float(trade.entry_price),
                "exit_price": float(trade.exit_price),
                "pnl": pnl,
                "fees": fees,
                "exit_reason": trade.exit_reason,
                "closed_at_ms": int(trade.closed_at * 1000),
                "strategy": meta.get("strategy", "unknown"),
                "asset": trade.symbol.split("/")[0],
                "regime": meta.get("regime", "UNKNOWN"),
                "decision_id": meta.get("decision_id", ""),
            }
            state.closed_trades.append(entry)
            state.realized_pnl = round(state.realized_pnl + pnl, 8)
            state.fees = round(state.fees + fees, 8)
            close_day = state.daily.setdefault(day_key(int(trade.closed_at * 1000)), _new_day())
            close_day["closes"] += 1
            close_day["realized_pnl"] = round(close_day["realized_pnl"] + pnl, 8)
            close_day["fees"] = round(close_day["fees"] + fees, 8)
            close_day["wins" if pnl > 0 else "losses"] += 1
            for attr in (
                state.by_asset.setdefault(entry["asset"], _new_attr()),
                state.by_strategy.setdefault(entry["strategy"], _new_attr()),
                state.by_regime.setdefault(entry["regime"], _new_attr()),
            ):
                attr["net_pnl"] = round(attr["net_pnl"] + pnl, 8)
                attr["wins" if pnl > 0 else "losses"] += 1
        if closed:
            state.heartbeat["last_reconciliation_success"] = utc_now_iso()
            state.open_positions = [p for p in state.open_positions if p["symbol"] in broker.positions]
            state.equity = broker.equity
            closed_out = [
                {
                    "symbol": t.symbol,
                    "pnl": float(t.pnl),
                    "exit_reason": t.exit_reason,
                }
                for t in closed
            ]
        return closed_out

    def _persist(self) -> None:
        assert self.state is not None
        self.state.heartbeat["last_persistence_success"] = utc_now_iso()
        self.store.save(self.state)

    # -- one observation cycle ---------------------------------------------

    def run_cycle(
        self,
        *,
        bars_by_asset: dict[str, list[OHLCV]],
        risk: RiskManager,
        broker: PaperBroker,
        now: datetime,
    ) -> dict[str, Any]:
        state = self.state
        assert state is not None
        summary: dict[str, Any] = {"assets": {}, "health": {}}
        evaluation_counts: dict[str, int] = {}
        now_ms = int(now.timestamp() * 1000)

        for asset in self.assets:
            bars = bars_by_asset[asset]
            latest_ms = bars[-1].timestamp
            decision_time = datetime.fromtimestamp(latest_ms / 1000, tz=UTC)
            day = state.daily.setdefault(day_key(latest_ms), _new_day())

            # PIT invariant: market_data_time <= decision_time <= execution_time
            if latest_ms > now_ms + FUTURE_TOLERANCE_MS:
                state.bump_reason("FUTURE_DATA_REJECTED")
                state.data_health["future_events"] += 1
                day["data_health_events"] += 1
                summary["assets"][asset] = "FUTURE_DATA_REJECTED"
                continue
            if latest_ms < now_ms - STALE_AFTER_MS and self.provider.startswith("ccxt"):
                state.bump_reason("STALE_DATA_NO_TRADE")
                state.data_health["stale_events"] += 1
                day["data_health_events"] += 1
                summary["assets"][asset] = "STALE_DATA_NO_TRADE"
                continue

            # resume recovery: reconcile open positions on this symbol before
            # any decision logic, so TP/SL hits during downtime are captured.
            closed_before = self._reconcile_symbol(
                state, risk, broker, f"{asset}/USDT", bars[-1].close
            )
            if closed_before:
                summary["assets"][asset] = "RECONCILED_BEFORE_DECISION"

            fingerprint = f"{asset}:{latest_ms}"
            if state.seen_data_fingerprint(fingerprint):
                state.bump_reason("DUPLICATE_MARKET_EVENT")
                summary["assets"][asset] = "DUPLICATE_MARKET_EVENT_SKIPPED"
                continue

            state.bump("MARKET_SCANS")
            day["scans"] += 1
            asset_attr = state.by_asset.setdefault(asset, _new_attr())
            asset_attr["assessments"] += 1

            try:
                proposals, evidence, assessment, board, reports, prices = self._evaluate(
                    asset=asset, bars=bars, decision_time=decision_time,
                    evaluation_counts=evaluation_counts,
                )
            except Exception as exc:
                state.bump_reason("PROVIDER_FAILURE")
                state.data_health["provider_failures"] += 1
                state.errors.append(f"{asset}: {type(exc).__name__}: {exc}")
                day["runtime_errors"] += 1
                summary["assets"][asset] = f"ERROR:{type(exc).__name__}"
                continue

            day["proposals"] += len(proposals)
            asset_attr["proposals"] += len(proposals)
            regime = str(getattr(assessment, "regime", None) or getattr(assessment, "market_regime", None) or "UNKNOWN")
            regime_attr = state.by_regime.setdefault(regime, _new_attr())
            regime_attr["proposals"] += len(proposals)
            health = _data_health(bars)
            summary["health"][asset] = health
            if health["duplicate_candles"] or health["gaps"] or health["future_timestamps"]:
                day["data_health_events"] += health["duplicate_candles"] + health["gaps"] + health["future_timestamps"]
            state.last_market_timestamp = latest_ms
            state.last_successful_scan_time = utc_now_iso()
            state.heartbeat["last_scan_time"] = state.last_successful_scan_time
            state.processed_data_fingerprints.append(fingerprint)

            if not proposals:
                state.bump("NO_TRADE")
                state.bump_reason("NO_PROPOSAL")
                day["no_trade"] += 1
                summary["assets"][asset] = "NO_TRADE:NO_PROPOSAL"
                continue

            state.bump("TRADE_PROPOSALS")
            engine = DecisionEngine(run_id=state.run_id)
            package = engine.decide(
                snapshot=board.snapshot(),
                proposals=proposals,
                evidence_registry=evidence,
                reports=reports,
                assessments={asset: assessment},
                now=decision_time,
            )
            decision_id = package.decision_id
            if state.seen_decision(decision_id):
                state.bump_reason("DUPLICATE_DECISION_SKIPPED")
                summary["assets"][asset] = "DUPLICATE_DECISION_SKIPPED"
                continue

            self._record_debate_metrics(reports, day)

            if package.outcome.value == "NO_TRADE":
                state.bump("NO_TRADE")
                state.decision_metrics["no_trade"] += 1
                day["no_trade"] += 1
                if not reports or reports[0].outcome.value != "UNRESOLVED":
                    state.bump_reason("INSUFFICIENT_EVIDENCE")
                state.mark_decision(decision_id)
                summary["assets"][asset] = "NO_TRADE"
                continue

            if package.outcome.value == "SELECTED" and package.selected_candidate_id is not None:
                state.bump("DECISION_SELECTED")
                state.decision_metrics["selected"] += 1
                day["selected"] += 1
                asset_attr["selected"] += 1
                regime_attr["selected"] += 1
                if package.rejected_alternatives:
                    state.bump("DECISION_REJECTED")
                    state.decision_metrics["rejected"] += len(package.rejected_alternatives)

            from trading_bot.multi_agent.decision import DecisionPackageVerifier

            snapshot = board.snapshot()
            verdict = DecisionPackageVerifier().verify(
                package,
                proposals=proposals,
                evidence_registry=evidence,
                now=decision_time,
                reports=reports,
                snapshot=snapshot,
            )
            if not verdict.passed:
                state.bump("VERIFIER_REJECTED")
                state.decision_metrics["verifier_rejected"] += 1
                state.bump_reason("VERIFIER_REJECTED_NATURAL_OUTPUT")
                # Naturally generated verifier rejection = operational defect (§22)
                failed = [name for name, status, _ in verdict.checks if status != "PASS"]
                state.errors.append(
                    f"verifier_rejected_natural_output decision_id={decision_id} checks={failed}"
                )
                state.warnings.append(
                    "upstream engine/verifier contract gap under multi-proposal agreement; "
                    "certified modules frozen - surfaced, not repaired"
                )
                state.mark_decision(decision_id)
                summary["assets"][asset] = "VERIFIER_REJECTED"
                continue
            state.bump("VERIFIER_VERIFIED")
            state.decision_metrics["verifier_verified"] += 1

            from trading_bot.demo.paper_multi_agent import DecisionToCandidateAdapter

            candidate = DecisionToCandidateAdapter().adapt(
                package,
                proposals=proposals,
                evidence_registry=evidence,
                reports=reports,
                now=decision_time,
                prices=prices,
                snapshot=snapshot,
            )
            if candidate is None:
                state.bump_reason("ADAPTER_NOT_ADMITTED")
                state.mark_decision(decision_id)
                summary["assets"][asset] = "ADAPTER_NOT_ADMITTED"
                continue
            state.bump("CANDIDATE_ADMITTED")
            portfolio = build_portfolio([candidate.candidate])
            if not portfolio.candidates:
                state.bump_reason("PORTFOLIO_CONSTRAINT")
                state.mark_decision(decision_id)
                summary["assets"][asset] = "PORTFOLIO_REJECTED"
                continue

            # ---- risk authority: certified RiskManager only ----
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
                    "campaign_id": state.campaign_id,
                    "run_id": state.run_id,
                    "trace_id": state.trace_id,
                    "decision_id": decision_id,
                    "entry_reason": "POC01_VERIFIED_SELECTION",
                },
            )
            state.bump("RISK_CALLS")
            check = risk.check_signal(signal)
            if not check.approved or check.position_size is None:
                state.bump("RISK_REJECT")
                state.risk_metrics["rejects"] += 1
                day["risk_rejects"] += 1
                reason = str(check.blocked_by or check.reason or "RISK_LIMIT").upper().replace(" ", "_")
                state.bump_reason(reason)
                state.risk_metrics["reason_distribution"][reason] = (
                    state.risk_metrics["reason_distribution"].get(reason, 0) + 1
                )
                state.mark_decision(decision_id)
                summary["assets"][asset] = f"RISK_REJECT:{reason}"
                continue
            state.bump("RISK_ACCEPT")
            state.risk_metrics["accepts"] += 1
            day["risk_accepts"] += 1
            asset_attr["risk_accepted"] += 1
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
            state.bump("BROKER_CALLS")
            if isinstance(result, PaperPosition):
                risk.add_position(result.symbol, result)
                order_id = f"{decision_id}:open"
                state.mark_order(order_id)
                state.mark_fill(order_id)
                state.bump("PAPER_OPEN")
                day["trades"] += 1
                asset_attr["trades"] += 1
                regime_attr["trades"] += 1
                state.open_positions.append(
                    _position_to_dict(
                        result,
                        decision_id=decision_id,
                        strategy=candidate.candidate.strategy_id,
                        regime=regime,
                    )
                )
                state.risk_metrics["max_simultaneous_positions"] = max(
                    int(state.risk_metrics["max_simultaneous_positions"]), len(broker.positions)
                )
                exposure: dict[str, Any] = state.risk_metrics["asset_exposure"]
                exposure[result.symbol] = round(
                    exposure.get(result.symbol, 0.0) + float(result.notional_usdt), 8
                )
                summary["assets"][asset] = "PAPER_OPEN"
                # immediate reconciliation: entry price may already satisfy TP/SL
                self._reconcile_symbol(
                    state, risk, broker, result.symbol, prices[result.symbol.split("/")[0]]
                )

            state.equity = broker.equity
            state.unrealized_pnl = round(
                sum(
                    p.unrealized_pnl(prices.get(sym, p.entry_price))
                    for sym, p in broker.positions.items()
                ),
                8,
            )
            day["unrealized_pnl"] = state.unrealized_pnl
            state.mark_decision(decision_id)
            summary["assets"][asset] = summary["assets"].get(asset, "PROCESSED")

        state.risk_metrics["avg_simultaneous_positions"] = round(
            (float(state.risk_metrics["avg_simultaneous_positions"]) + len(broker.positions)) / 2, 6
        )
        for name, count in evaluation_counts.items():
            state.by_strategy.setdefault(name, _new_attr())["evaluations"] += count
        state.heartbeat["last_successful_decision_cycle"] = int(
            state.heartbeat.get("last_successful_decision_cycle", 0)
        ) + 1
        return summary

    def _evaluate(
        self,
        *,
        asset: str,
        bars: list[OHLCV],
        decision_time: datetime,
        evaluation_counts: dict[str, int],
    ) -> tuple[dict[str, Any], dict[str, Any], Any, OpportunityBoard, tuple[Any, ...], dict[str, float]]:
        state = self.state
        assert state is not None
        bus = _setup_bus(state.run_id, state.trace_id, decision_time)
        board = OpportunityBoard(run_id=state.run_id, now=decision_time)
        root_trace = _trace(state.run_id, state.trace_id, f"market:{asset}:{bars[-1].timestamp}")
        context = _context(asset, bars, self.dataset_id)
        assessment = AssetExpert(asset).evaluate(context, trace=root_trace, now_ts=bars[-1].timestamp)
        proposals: dict[str, Any] = {}
        evidence_registry: dict[str, Any] = {i.evidence_id: i for i in assessment.evidence}
        positions: list[DebatePosition] = []
        prices = {asset: bars[-1].close}
        for item in assessment.evidence:
            bus.register_evidence(item)

        for strategy in self.strategies:
            expert = StrategyExpert(_TrackedFamilies(strategy, evaluation_counts))
            evaluation = expert.evaluate(
                context,
                bars,
                trace=root_trace,
                assessment=assessment,
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
        return proposals, evidence_registry, assessment, board, tuple(reports), prices

    def _record_debate_metrics(self, reports: tuple[Any, ...], day: dict[str, Any]) -> None:
        state = self.state
        assert state is not None
        if not reports:
            return
        report = reports[0]
        state.bump("DEBATES")
        day["debates"] += 1
        dm = state.debate_metrics
        dm["debates"] += 1
        dm["critiques"] += len(report.critiques)
        dm["revisions"] += len(report.revisions)
        state.bump("CRITIQUES")
        state.bump("REVISIONS")
        outcome = report.outcome.value
        if outcome in ("SUPPORTED", "REVISED"):
            dm["resolved"] += 1
            state.bump("DEBATE_RESOLVED")
        else:
            dm["unresolved"] += 1
            state.bump("DEBATE_UNRESOLVED")
            state.bump_reason("UNRESOLVED_CONFLICT")
        dm["counter_evidence"] += len(getattr(report, "counter_evidence", []) or [])
        dm["material_dissent"] += len(getattr(report, "unresolved_conflicts", []) or [])

    # -- bounded session ------------------------------------------------------

    def run_bounded_session(self, *, cycles: int = 1, interval_seconds: float = 0.0) -> dict[str, Any]:
        """Run up to ``cycles`` observation cycles; safe-stop between cycles."""
        self.install_signal_handlers()
        if self.state is None:
            if self.store.exists():
                self.load_for_resume()
            else:
                self.new_campaign()
        state = self.state
        assert state is not None
        session_entry: dict[str, Any] = {
            "started_at": utc_now_iso(),
            "cycles": 0,
            "stopped_early": False,
        }
        summaries: list[dict[str, Any]] = []
        try:
            for cycle in range(1, cycles + 1):
                if self.stop_requested:
                    session_entry["stopped_early"] = True
                    break
                now = datetime.now(UTC)
                try:
                    if self.provider.startswith("ccxt"):
                        bars = _public_bars(self.assets)
                    else:
                        bars = {
                            asset: _fixture_bars(asset, cycle, shape="up" if cycle % 2 else "flat")
                            for asset in self.assets
                        }
                except Exception as exc:
                    state.bump_reason("PROVIDER_FAILURE")
                    state.data_health["provider_failures"] += 1
                    state.errors.append(f"provider: {type(exc).__name__}: {exc}")
                    state.heartbeat["provider_status"] = "STALE"
                    self._persist()
                    continue
                risk, broker = self._rehydrate(state)
                summary = self.run_cycle(bars_by_asset=bars, risk=risk, broker=broker, now=now)
                summaries.append(summary)
                session_entry["cycles"] += 1
                self._persist()
                self.write_reports()
                if interval_seconds > 0 and cycle < cycles and not self.stop_requested:
                    time.sleep(interval_seconds)
        finally:
            session_entry["ended_at"] = utc_now_iso()
            state.runs.append(session_entry)
            status = "STOPPED" if self.stop_requested else state.campaign_status
            state.campaign_status = "ACTIVE" if not self.stop_requested else status
            self._persist()
            self.write_reports()
        return {"session": session_entry, "cycles": summaries}

    # -- stop / reports -------------------------------------------------------

    def safe_stop(self, *, status: str = "STOPPED") -> None:
        state = self.state
        assert state is not None
        state.campaign_status = status
        state.heartbeat["campaign_state"] = status
        state.heartbeat["stopped_at"] = utc_now_iso()
        self._persist()
        self.write_reports()

    def write_reports(self) -> None:
        state = self.state
        assert state is not None
        for day, entry in sorted(state.daily.items()):
            payload = daily_report_payload(campaign_id=state.campaign_id, day=day, day_entry=entry)
            day_dir = self.campaign_dir / day
            day_dir.mkdir(parents=True, exist_ok=True)
            (day_dir / "DAILY_REPORT.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
            )
            (day_dir / "DAILY_REPORT.md").write_text(
                "\n".join(
                    [
                        f"# POC01 Daily Report — {state.campaign_id} — {day}",
                        "",
                        f"- market scans: {payload['market_scans']}",
                        f"- proposals: {payload['proposals']}",
                        f"- debates: {payload['debates']}",
                        f"- selected: {payload['selected']}",
                        f"- NO_TRADE: {payload['no_trade']}",
                        f"- risk accepts/rejects: {payload['risk_accepts']}/{payload['risk_rejects']}",
                        f"- paper opens/closes: {payload['paper_opens']}/{payload['paper_closes']}",
                        f"- wins/losses: {payload['wins']}/{payload['losses']}",
                        f"- realized PnL: {payload['realized_pnl']}",
                        f"- trades/day: {payload['trades_per_day']} (>=3: {payload['day_ge_3']})",
                        f"- FALSE_SUCCESS: {payload['false_success']}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        perf = performance_metrics(
            initial_equity=state.initial_equity,
            equity=state.equity,
            closed_trades=state.closed_trades,
            realized_pnl=state.realized_pnl,
            unrealized_pnl=state.unrealized_pnl,
            fees=state.fees,
        )
        valid_days = [d for d, e in state.daily.items() if e.get("valid", True)]
        days_ge_3 = sum(1 for d in valid_days if state.daily[d].get("trades", 0) >= 3)
        funnel_ranked = dict(sorted(state.funnel.items(), key=lambda kv: -kv[1]))
        reasons_ranked = dict(sorted(state.reasons.items(), key=lambda kv: -kv[1]))
        conversions = {
            "scan_to_proposal": _ratio(state.funnel.get("TRADE_PROPOSALS", 0), state.funnel.get("MARKET_SCANS", 0)),
            "proposal_to_selected": _ratio(state.funnel.get("DECISION_SELECTED", 0), state.funnel.get("TRADE_PROPOSALS", 0)),
            "selected_to_risk_accepted": _ratio(state.funnel.get("RISK_ACCEPT", 0), state.funnel.get("DECISION_SELECTED", 0)),
            "risk_accepted_to_trade": _ratio(state.funnel.get("PAPER_OPEN", 0), state.funnel.get("RISK_ACCEPT", 0)),
        }
        measurable = {k: v for k, v in conversions.items() if v is not None}
        bottleneck = min(measurable, key=lambda k: measurable[k]) if measurable else None
        payload = {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": state.campaign_id,
            "campaign_status": state.campaign_status,
            "campaign_start": state.campaign_start,
            "data_tag": self.dataset_id,
            "fixture_excluded_from_poc01_performance": not self.provider.startswith("ccxt"),
            "provider": state.provider,
            "implementation_commit": state.implementation_commit,
            "assets": list(state.assets),
            "strategies": list(state.strategies),
            "heartbeat": state.heartbeat,
            "funnel": funnel_ranked,
            "reason_frequency": reasons_ranked,
            "debate_metrics": state.debate_metrics,
            "decision_metrics": state.decision_metrics,
            "risk_metrics": {
                **state.risk_metrics,
                "rejection_rate": _ratio(
                    state.risk_metrics["rejects"],
                    state.risk_metrics["accepts"] + state.risk_metrics["rejects"],
                ),
            },
            "performance": perf,
            "frequency": {
                "trades_per_day_by_day": {d: e.get("trades", 0) for d, e in sorted(state.daily.items())},
                "valid_days": len(valid_days),
                "days_ge_3": days_ge_3,
                "percent_days_ge_3": round(days_ge_3 / len(valid_days) * 100, 4) if valid_days else 0.0,
                "note": "target 7/7 days >=3; average>=3 does NOT imply target PASS; KPI observational only",
            },
            "attribution": {
                "by_asset": state.by_asset,
                "by_strategy": state.by_strategy,
                "by_regime": state.by_regime,
            },
            "bottleneck": {"conversions": conversions, "PRIMARY_FREQUENCY_BOTTLENECK": bottleneck},
            "data_health": state.data_health,
            "errors": state.errors,
            "warnings": state.warnings,
            "false_success": _false_success_audit(state),
            "live_calls": 0,
            "real_broker_calls": 0,
            "private_exchange_calls": 0,
        }
        self.campaign_dir.mkdir(parents=True, exist_ok=True)
        (self.campaign_dir / "CAMPAIGN_REPORT.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        (self.campaign_dir / "CAMPAIGN_REPORT.md").write_text(
            "\n".join(
                [
                    f"# POC01 Campaign Report — {state.campaign_id}",
                    "",
                    f"- status: **{state.campaign_status}**",
                    "- mode: **PAPER — LIVE DISABLED**",
                    f"- data: **{self.dataset_id}**",
                    f"- valid days: {len(valid_days)} / target 7",
                    f"- days >=3 trades: {days_ge_3}",
                    f"- net PnL: {perf['net_pnl']} ({perf['sample_status']})",
                    f"- funnel: {funnel_ranked}",
                    f"- top rejection reasons: {list(reasons_ranked.items())[:5]}",
                    f"- PRIMARY_FREQUENCY_BOTTLENECK: {bottleneck}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# read-only campaign dashboard (§27-29)
# ---------------------------------------------------------------------------


def create_campaign_dashboard(runtime: CampaignRuntime, *, host: str = "127.0.0.1", port: int = 8766) -> Any:
    state_holder: dict[str, Any] = {}

    def refresh() -> dict[str, Any]:
        state = runtime.state
        if state is None:
            return {"error": "no campaign state loaded"}
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_entry = state.daily.get(today, _new_day())
        payload = {
            "mode": "PAPER",
            "data": runtime.dataset_id,
            "live_disabled": True,
            "campaign_id": state.campaign_id,
            "campaign_state": state.campaign_status,
            "campaign_start": state.campaign_start,
            "elapsed_hours": round(
                (datetime.now(UTC) - datetime.fromisoformat(state.campaign_start)).total_seconds() / 3600, 4
            ),
            "valid_days": sum(1 for e in state.daily.values() if e.get("valid", True)),
            "last_market_update": state.last_market_timestamp,
            "runtime_health": state.heartbeat,
            "today": {
                "market_scans": today_entry["scans"],
                "proposals": today_entry["proposals"],
                "debates": today_entry["debates"],
                "selected": today_entry["selected"],
                "no_trade": today_entry["no_trade"],
                "risk_accepts": today_entry["risk_accepts"],
                "risk_rejects": today_entry["risk_rejects"],
                "paper_trades": today_entry["trades"],
                "realized_pnl": today_entry["realized_pnl"],
                "unrealized_pnl": today_entry["unrealized_pnl"],
                "trades_today": today_entry["trades"],
                "ge_3_target_status": "MET" if today_entry["trades"] >= 3 else "NOT_MET (informational only)",
            },
            "funnel": state.funnel,
            "frequency": {
                "trades_by_day": {d: e.get("trades", 0) for d, e in sorted(state.daily.items())},
                "days_ge_3": sum(1 for e in state.daily.values() if e.get("trades", 0) >= 3),
            },
            "performance": {
                "net_pnl": state.realized_pnl,
                "unrealized_pnl": state.unrealized_pnl,
                "win_rate": _ratio(
                    sum(1 for t in state.closed_trades if float(t["pnl"]) > 0), len(state.closed_trades)
                ),
                "profit_factor": None,
                "note": "canonical numbers from CAMPAIGN_REPORT.json performance block",
            },
            "pnl_by_asset": {k: v.get("net_pnl", 0.0) for k, v in state.by_asset.items()},
            "pnl_by_strategy": {k: v.get("net_pnl", 0.0) for k, v in state.by_strategy.items()},
            "risk_rejection_reasons": state.risk_metrics["reason_distribution"],
            "errors": state.errors,
        }
        state_holder["last"] = payload
        return payload

    refresh()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/api/campaign"):
                body = json.dumps(refresh(), indent=2, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.refresh = refresh  # type: ignore[attr-defined]

    class CampaignDashboard:
        """Thin lifecycle wrapper: read-only, no control endpoints."""

        @property
        def url(self) -> str:
            return f"http://{host}:{server.server_port}/api/campaign"

        def start(self) -> None:
            server._thread = threading.Thread(target=server.serve_forever, daemon=True)  # type: ignore[attr-defined]
            server._thread.start()  # type: ignore[attr-defined]

        def stop(self) -> None:
            server.shutdown()
            server.server_close()

        @property
        def port(self) -> int:
            return server.server_port

    return CampaignDashboard()


# ---------------------------------------------------------------------------
# CLI (§32)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="POC01 paper observation campaign")
    parser.add_argument("command", choices=("run", "resume", "status", "stop", "report"), nargs="?", default="run")
    parser.add_argument("--campaign-name", default=CAMPAIGN_NAME)
    parser.add_argument("--provider", choices=("ccxt", "fake"), default="ccxt")
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    assets = tuple(a.strip().upper() for a in args.assets.split(",") if a.strip())
    runtime = CampaignRuntime(
        output_dir=args.output_dir,
        campaign_name=args.campaign_name,
        provider=args.provider,
        assets=assets,
    )
    import time as _time

    if args.command == "status":
        runtime.load_for_resume()
        assert runtime.state is not None
        print(
            json.dumps(
                {
                    "campaign_id": runtime.state.campaign_id,
                    "status": runtime.state.campaign_status,
                    "heartbeat": runtime.state.heartbeat,
                    "realized_pnl": runtime.state.realized_pnl,
                    "open_positions": len(runtime.state.open_positions),
                },
                indent=2,
                default=str,
            )
        )
        return 0

    if args.command == "stop":
        runtime.load_for_resume()
        runtime.safe_stop(status="STOPPED")
        print(f"campaign {runtime.campaign_id} stopped safely")
        return 0

    if args.command == "report":
        runtime.load_for_resume()
        runtime.write_reports()
        print(f"reports written to {runtime.campaign_dir}")
        return 0

    if args.command == "resume":
        runtime.load_for_resume()
    else:
        if runtime.store.exists():
            print(f"durable state already exists for {runtime.campaign_id}; use `resume`")
            return 2
        runtime.new_campaign()

    server = create_campaign_dashboard(runtime) if args.dashboard else None
    try:
        result = runtime.run_bounded_session(cycles=args.cycles, interval_seconds=args.interval_seconds)
        print(json.dumps({"campaign_id": runtime.campaign_id, "session": result["session"]}, indent=2, default=str))
        if server is not None:
            print(f"Campaign dashboard (read-only): http://127.0.0.1:{server.port}/api/campaign")
            print("Press Ctrl+C to stop safely...")
            try:
                while not runtime.stop_requested:
                    _time.sleep(0.5)
            except KeyboardInterrupt:
                runtime.request_stop()
        runtime.safe_stop(status="STOPPED" if runtime.stop_requested else "PAUSED")
        return 0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
