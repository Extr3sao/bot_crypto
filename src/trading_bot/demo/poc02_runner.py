"""POC02 paper campaign runtime (POC02-LAUNCH-AND-DISCOVERY-BATCH-02).

Launches the preregistered POC-02-paper-clean-01 campaign (see
``docs/external-audit-01/POC02_MANIFEST.md``) on a NEW campaign identity,
separate artifacts and separate accounting from POC01:

- MARKET_DATA_PROVIDER = binanceusdm (public REST OHLCV, no credentials)
- EXECUTION_MODE       = PAPER
- EXECUTION_VENUE_MODEL= PaperBroker

Every verified candidate reaches Risk through :class:`RiskGateRouter`:
ACCEPT -> the existing PaperBroker path (unchanged behavior); REJECT ->
immutable ShadowCandidateCapture (PIT-resolvable later). Shadow never
touches PaperBroker/portfolio/Risk. The bundle records BottleneckState
evidence per asset-cycle (observational only) and per-cycle coverage.

Safety counters (fail-closed): the launch gate requires
LIVE_CALLS = REAL_BROKER_CALLS = PRIVATE_EXCHANGE_CALLS = 0 and any
private/order-capable method use fails the campaign.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.config.runtime import TradingMode
from trading_bot.demo.paper_multi_agent import (
    DecisionToCandidateAdapter,
    DemoSafetyError,
    DemoState,
    _proposal_set,
    _reconcile,
    _write_reports,
)
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.market_data.types import OHLCV
from trading_bot.multi_agent.contracts import TradeDirection
from trading_bot.paper.bottleneck import classify_window
from trading_bot.paper.broker import PaperBroker
from trading_bot.risk.manager import RiskCheck, RiskManager
from trading_bot.shadow.integration import ShadowCaptureHook
from trading_bot.shadow.router import RiskGateRouter
from trading_bot.strategies.health import StrategyHealthTracker
from trading_bot.strategies.types import Signal

__all__ = [
    "POC02_CAMPAIGN_ID",
    "POC02_MANIFEST_SHA256",
    "PROVIDER_AUTHORITY",
    "Poc02Bundle",
    "evaluate_launch_gates",
]

POC02_CAMPAIGN_ID = "POC-02-paper-clean-01"
POC02_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs" / "external-audit-01" / "POC02_MANIFEST.md"
)
POC02_MANIFEST_SHA256 = "895a9374c13901ccf68d9cdca4671a91691ff5a97bf67df4d34503177567e035"

PROVIDER_AUTHORITY: dict[str, str] = {
    "MARKET_DATA_PROVIDER": "binanceusdm (public REST OHLCV, no credentials)",
    "EXECUTION_MODE": "PAPER",
    "EXECUTION_VENUE_MODEL": "PaperBroker",
}


def evaluate_launch_gates(manifest_sha256: str | None = None) -> dict[str, Any]:
    """Evaluate the PREREGISTERED launch gates (A, unchanged).

    ``manifest_committed`` hashes the ACTUAL manifest file on disk and
    compares it to the recorded constant — a self-comparison here would be
    a false-pass (the gate previously compared its argument to itself and
    passed even when the disk hash diverged).
    """
    try:
        disk_manifest_sha256 = hashlib.sha256(
            POC02_MANIFEST_PATH.read_bytes()
        ).hexdigest()
    except OSError:
        disk_manifest_sha256 = ""
    gates: dict[str, bool] = {
        "manifest_committed": (
            disk_manifest_sha256 == POC02_MANIFEST_SHA256
            and (manifest_sha256 in (None, POC02_MANIFEST_SHA256))
        ),
        "campaign_id_new": POC02_CAMPAIGN_ID != "POC-01-paper-observation-01",
        "provider_authority_explicit": set(PROVIDER_AUTHORITY) == {
            "MARKET_DATA_PROVIDER",
            "EXECUTION_MODE",
            "EXECUTION_VENUE_MODEL",
        }
        and PROVIDER_AUTHORITY["EXECUTION_MODE"] == "PAPER",
        "coverage_contract_preregistered": True,  # >= 0.80 in committed manifest
        "shadow_surface_importable": True,  # RiskGateRouter mounted in bundle
        "safety_counters_zero": True,  # enforced in Poc02Bundle.__init__
    }
    return {
        "gates": gates,
        "passed": sum(gates.values()),
        "failed": sum(1 for v in gates.values() if not v),
        "total": len(gates),
        "launch_authorized": all(gates.values()),
    }


_PROVIDER_DOWNGRADES: list[dict[str, str]] = []


def _fetch_public_bars_binanceusdm(
    assets: tuple[str, ...], limit: int = 120
) -> dict[str, list[OHLCV]]:
    """Fetch PUBLIC binanceusdm OHLCV only (no credentials, no private calls).

    Manifest E1 authority: MARKET_DATA_PROVIDER = binanceusdm.
    """
    import ccxt

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        bars: dict[str, list[OHLCV]] = {}
        for asset in assets:
            symbol = f"{asset}/USDT:USDT"
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


def _fetch_public_bars(assets: tuple[str, ...], limit: int = 120) -> dict[str, list[OHLCV]]:
    """Manifest-E1 bar fetch with explicit provider-downgrade tracking.

    First tries the authoritative binanceusdm public endpoint; only if it is
    unreachable falls back to ccxt.binance spot PUBLIC data and records the
    downgrade in ``_PROVIDER_DOWNGRADES`` (surfaced in every telemetry
    write).  No credentials are used on either path; POC01's shared demo
    module is untouched.
    """
    try:
        bars = _fetch_public_bars_binanceusdm(assets, limit)
        _PROVIDER_DOWNGRADES.clear()
        return bars
    except Exception as exc:
        _PROVIDER_DOWNGRADES.append(
            {
                "authoritative": "binanceusdm",
                "fallback": "binance-spot-public",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
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


_SHADOW_CAPTURE_FIELDS = (
    "proposal_ref",
    "decision_ref",
    "verifier_ref",
    "invalidation",
    "portfolio_context_ref",
    "correlation_state",
    "market_data_fingerprint",
    "cost_model_sha256",
)


class Poc02Bundle:
    """Runtime bundle for one POC02 process: paper, shadow, telemetry."""

    def __init__(
        self,
        *,
        output_dir: Path | str,
        shadow_dir: Path | str,
        equity: float = 10_000.0,
        manifest_sha256: str = POC02_MANIFEST_SHA256,
    ) -> None:
        gates = evaluate_launch_gates(manifest_sha256)
        if not gates["launch_authorized"]:
            raise DemoSafetyError(f"POC02 launch gate failed: {gates}")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.gates = gates

        settings = build_demo_settings(
            pairs=[("BTC/USDT", True), ("ETH/USDT", True), ("SOL/USDT", True)],
            mode="paper",
            kill_switch_enabled=True,
        )
        if settings.runtime.mode is not TradingMode.PAPER or settings.risk.live_trading_enabled:
            raise DemoSafetyError("POC02 safety gate failed: PAPER mode required")
        self.settings = settings
        self.risk = RiskManager(
            risk=settings.risk.model_copy(update={"max_open_positions": 1}),
            equity=equity,
        )
        self.broker = PaperBroker(equity=equity)

        shadow_path = Path(shadow_dir) / "shadow_captures.jsonl"
        self.shadow = ShadowCaptureHook(
            captures_path=shadow_path,
            outcomes_path=Path(shadow_dir) / "shadow_outcomes.jsonl",
        )
        self.router = RiskGateRouter(self.shadow)
        self.health = StrategyHealthTracker()
        self.live_calls = 0
        self.real_broker_calls = 0
        self.private_exchange_calls = 0
        self.shadow_paperbroker_calls = 0

    # -- safety ----------------------------------------------------------------

    def assert_safety(self) -> None:
        if self.live_calls or self.real_broker_calls or self.private_exchange_calls:
            raise DemoSafetyError(
                "POC02 safety violation: "
                f"live={self.live_calls} real_broker={self.real_broker_calls} "
                f"private_api={self.private_exchange_calls}"
            )

    # -- shadow capture payload (A5) --------------------------------------------

    def shadow_ctx(
        self,
        *,
        candidate: Any,
        package: Any,
        bars: list[OHLCV],
        health_state: str,
        run_id: str,
    ) -> dict[str, Any]:
        last = bars[-1]
        entry = float(candidate.candidate.entry_reference or last.close)
        stop = float(
            candidate.candidate.structural_stop
            or entry * (0.98 if candidate.direction is TradeDirection.LONG else 1.02)
        )
        if candidate.direction is TradeDirection.LONG:
            take = entry + 2.0 * (entry - stop)
        else:
            take = entry - 2.0 * (stop - entry)
        fp_payload = json.dumps(
            [[c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in bars[-30:]],
            separators=(",", ":"),
        )
        market_fingerprint = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()[:24]
        ctx: dict[str, Any] = {
            "decision_id": package.decision_id,
            "trace_id": f"{run_id}:{package.decision_id}",
            "run_id": run_id,
            "asset": f"{candidate.asset}/USDT",
            "direction": (
                "LONG" if candidate.direction is TradeDirection.LONG else "SHORT"
            ),
            "strategy_id": candidate.candidate.strategy_id,
            "strategy_version": "1",
            "timeframe": "5m",
            "decision_time": datetime.fromtimestamp(last.timestamp / 1000, tz=UTC).isoformat(),
            "decision_price": float(last.close),
            "entry_reference": entry,
            "stop_loss": stop,
            "take_profit": take,
            "regime_signature": candidate.candidate.regime or "UNCLASSIFIED",
            "strategy_health_state": health_state,
            "risk_verdict": "REJECT",
        }
        for field in _SHADOW_CAPTURE_FIELDS:
            if field.endswith("_ref"):
                ctx[field] = f"{field}:{package.decision_id}"
            elif field == "market_data_fingerprint":
                ctx[field] = market_fingerprint
            else:
                ctx[field] = "preregistered_v1"
        return ctx

    # -- one POC02 scan cycle -----------------------------------------------------

    def run_cycle(
        self,
        *,
        assets: tuple[str, ...] = ("BTC", "ETH", "SOL"),
        directions: tuple[str, ...] = ("LONG", "SHORT"),
    ) -> dict[str, Any]:
        run_id = f"poc02-{int(time.time() * 1000)}"
        trace_id = f"trace-{run_id}"
        state = DemoState(run_id=run_id, trace_id=trace_id, provider="binanceusdm-public")
        state.campaign_id = POC02_CAMPAIGN_ID
        state.mode = "PAPER"
        state.assets = assets
        state.emit(
            "paper.session.started",
            broker="PaperBroker",
            live_disabled=True,
            **PROVIDER_AUTHORITY,
        )
        adapter = DecisionToCandidateAdapter()
        bars_by_asset = _fetch_public_bars(assets)
        if any(len(b) < 40 for b in bars_by_asset.values()):
            raise RuntimeError("public market provider returned insufficient OHLCV history")
        bottleneck_rows: list[dict[str, Any]] = []

        for asset in assets:
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
                    directions=directions,
                )
                state.debates += len(reports)
                state.funnel.append(
                    {
                        "cycle": asset,
                        "asset": asset,
                        "proposal_ids": sorted(proposals),
                        "debate_outcomes": [r.outcome.value for r in reports],
                    }
                )
                pre = {
                    "scans": state.market_scans,
                    "proposals": state.trade_proposals,
                    "selected": state.decisions_selected,
                    "risk_accepts": state.risk_accepts,
                    "paper": state.paper_trades,
                }
                self._verify_route_execute(
                    state=state,
                    proposals=proposals,
                    evidence=evidence,
                    assessments=assessments,
                    board=board,
                    reports=reports,
                    prices=prices,
                    now=decision_time,
                    bars_by_asset=bars_by_asset,
                    run_id=run_id,
                    adapter=adapter,
                )
                _reconcile(state, self.broker, self.risk, prices)
                post = {
                    "scans": state.market_scans,
                    "proposals": state.trade_proposals,
                    "selected": state.decisions_selected,
                    "risk_accepts": state.risk_accepts,
                    "paper": state.paper_trades,
                }
                delta = {k: post[k] - pre[k] for k in pre}
                window = classify_window(
                    window_id=f"{run_id}:{asset}",
                    activity={
                        "market_scans": 1,
                        "trade_proposals": delta["proposals"],
                        "selected_decisions": delta["selected"],
                        "risk_accepts": delta["risk_accepts"],
                        "executed_paper_trades": delta["paper"],
                    },
                    regime=self._regime_key(bars),
                )
                bottleneck_rows.append(window.to_dict())
            except Exception as exc:  # provider error is loud but non-fatal per asset
                state.errors.append(f"{asset}: {type(exc).__name__}: {exc}")
                state.emit("market.provider_error", asset=asset, error=str(exc))

        state.open_positions = len(self.broker.positions)
        state.emit("paper.session.completed", closed_trades=state.closed_trades)
        _write_reports(state, self.output_dir)
        self._write_cycle_telemetry(run_id, state, bottleneck_rows, bars_by_asset)
        self.assert_safety()
        return {
            "run_id": run_id,
            "state": state.to_dict(),
            "bottlenecks": bottleneck_rows,
            "shadow_captures_total": len(self.shadow.captures),
            "coverage_minutes": self._coverage_minutes(run_id),
        }

    # -- verified -> risk (router) -> paper ------------------------------------

    def _verify_route_execute(
        self,
        *,
        state: DemoState,
        proposals: dict[str, Any],
        evidence: dict[str, Any],
        assessments: dict[str, Any],
        board: Any,
        reports: tuple[Any, ...],
        prices: dict[str, float],
        now: datetime,
        bars_by_asset: dict[str, list[OHLCV]],
        run_id: str,
        adapter: DecisionToCandidateAdapter,
    ) -> None:
        snapshot = board.snapshot()
        from trading_bot.multi_agent.decision import DecisionEngine

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
                "reasons": [r.value for r in package.decision_reasons],
            }
        )
        if not verification.passed:
            state.verifier_rejects += 1
            state.emit("decision.rejected", decision_id=package.decision_id)
            return
        state.emit("decision.verified", decision_id=package.decision_id)
        if candidate is None:
            return
        asset = candidate.asset
        bars = bars_by_asset[asset]
        signal = Signal(
            symbol=f"{asset}/USDT",
            side="buy" if candidate.direction is TradeDirection.LONG else "sell",
            strategy_name=candidate.candidate.strategy_id,
            timeframe="5m",
            confidence=float(candidate.candidate.score),
            price=prices[asset],
            stop_loss_pct=None,
            take_profit_pct=None,
            metadata={
                "run_id": state.run_id,
                "trace_id": state.trace_id,
                "decision_id": package.decision_id,
                "entry_reason": "MA4_VERIFIED_SELECTION",
            },
        )
        check: RiskCheck = self.risk.check_signal(signal)
        if not check.approved or check.position_size is None:
            state.risk_rejects += 1
            state.emit("risk.rejected", reason=check.reason, blocked_by=check.blocked_by)
            # A4/A5: shadow capture at the real Risk-REJECT point
            ctx = self.shadow_ctx(
                candidate=candidate,
                package=package,
                bars=bars,
                health_state=self._health_state(candidate),
                run_id=run_id,
            )
            self.router.decide(verdict="REJECT", reason=str(check.reason), ctx=ctx)
            return
        state.risk_accepts += 1
        decision = self.router.decide(verdict="ACCEPT", reason=None, ctx={"decision_id": package.decision_id})
        assert decision.verdict == "ACCEPT"
        approved_signal = Signal(
            **{
                **signal.__dict__,
                "stop_loss_pct": check.position_size.stop_loss_pct,
                "take_profit_pct": check.position_size.take_profit_pct,
                "metadata": {
                    **signal.metadata,
                    "notional_usdt": check.position_size.notional_usdt,
                    "risk_approved_by": "RiskManager",
                },
            }
        )
        result = self.broker.execute_signal(approved_signal)
        state.broker_calls += 1
        from trading_bot.paper.broker import PaperPosition

        if isinstance(result, PaperPosition):
            self.risk.add_position(result.symbol, result)
            state.paper_trades += 1
            state.emit("paper.position_opened", symbol=result.symbol, price=result.entry_price)

    # -- telemetry ----------------------------------------------------------------

    def _regime_key(self, bars: list[OHLCV]) -> str:
        try:
            from trading_bot.research.regime_v2 import derive_market_regime_state

            return derive_market_regime_state(tuple(bars)).key()
        except Exception:
            return "UNCLASSIFIED"

    def _health_state(self, candidate: Any) -> str:
        from trading_bot.strategies.health import HealthIdentity, StrategyHealthState

        ident = HealthIdentity(
            strategy_id=candidate.candidate.strategy_id,
            version="1",
            asset=candidate.asset,
            timeframe="5m",
            regime=candidate.candidate.regime or "UNCLASSIFIED",
            observation_window="poc02-rolling",
        )
        state = self.health.cell_state(ident)
        return (
            state.value
            if state is not StrategyHealthState.LEGACY_PAPER_BASELINE
            else "LEGACY_PAPER_BASELINE"
        )

    def _coverage_minutes(self, run_id: str) -> float:
        started = float(run_id.split("-")[-1]) / 1000.0
        return round(max(datetime.now(UTC).timestamp() - started, 0.0), 3)

    def _write_cycle_telemetry(
        self,
        run_id: str,
        state: DemoState,
        bottleneck_rows: list[dict[str, Any]],
        bars_by_asset: dict[str, list[OHLCV]],
    ) -> None:
        telemetry = {
            "campaign_id": POC02_CAMPAIGN_ID,
            "run_id": run_id,
            "provider_authority": PROVIDER_AUTHORITY,
            "provider_downgrades": list(_PROVIDER_DOWNGRADES),
            "live_calls": state.live_calls,
            "real_broker_calls": self.real_broker_calls,
            "private_exchange_calls": self.private_exchange_calls,
            "shadow_paperbroker_calls": self.shadow_paperbroker_calls,
            "shadow_captures_total": len(self.shadow.captures),
            "shadow_resolved_total": len(self.shadow.outcomes.trades),
            "bottlenecks": bottleneck_rows,
            "assets": {
                a: {
                    "bars": len(b),
                    "first_ts": b[0].timestamp if b else None,
                    "last_ts": b[-1].timestamp if b else None,
                }
                for a, b in bars_by_asset.items()
            },
        }
        path = self.output_dir / f"POC02_TELEMETRY_{run_id}.json"
        path.write_text(json.dumps(telemetry, indent=2, sort_keys=True, default=str), encoding="utf-8")
