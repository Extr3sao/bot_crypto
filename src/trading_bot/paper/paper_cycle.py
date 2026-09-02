"""Canonical paper decision cycle (CP-PO-002, FASE 7B/7C/8A/8B).

One deterministic, fail-closed path per asset per cycle:

    PIT OHLCV → AssetAgent → AssetContext
    → StrategyRouter (canonical router, no local if/else)
    → AlphaFamily (existing research families)
    → SignalAdapter (the single conversion point)
    → CandidatePortfolio (consolidation, pre-risk)
    → RiskManager.check_signal (mandatory risk path)
    → PaperBroker.execute_signal (the only execution boundary)

Hard invariants (docs/ADR_STRATEGY_ROUTER_CONVERGENCE.md,
docs/PAPER_OPERATIONAL_CONTRACT_CONVERGENCE.md):
- No new paper position without a prior approved ``RiskCheck`` (FASE 8A).
- Router/strategy/adapter/risk/broker failure ⇒ zero orders (fail closed);
  every rejection is recorded with a reason (observable).
- Idempotency: the same intent (symbol, strategy, direction, bar) executes
  exactly once — the neutral ``IdempotencyGuard`` from ``execution/`` is
  reused (pure cloid bookkeeping, execution-mode agnostic).
- PIT safety: the context is built only from bars at or before the
  decision timestamp (trim happens here, defence in depth at the reader).
- The broker receives the risk-approved size/SL/TP: the signal handed to
  ``execute_signal`` is rebuilt with ``PositionSize`` values after
  approval (``Signal`` is frozen — no mutation).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.candidate_portfolio import TradeCandidate, build_portfolio
from trading_bot.paper.signal_adapter import AdapterError, alpha_signal_to_signal
from trading_bot.paper.snapshot_context import trim_to_pit
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import RouterDecision, StrategyRouter
from trading_bot.risk.manager import RiskManager

__all__ = [
    "CycleStageCounts",
    "PaperCycleEngine",
    "RouteOnlyEngine",
    "intent_cloid",
]


def intent_cloid(symbol: str, strategy_id: str, direction: str, bar_ts: int) -> str:
    """Stable intent identity for exactly-once paper execution.

    Built from the domain fields mandated by the CP-PO-002 contract:
    asset, strategy, timeframe-bar and direction. Same intent twice ⇒ same
    cloid ⇒ one execution.
    """
    payload = json.dumps(
        {"s": symbol, "st": strategy_id, "d": direction, "t": int(bar_ts)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "PAPER-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class CycleStageCounts:
    """Per-cycle observability counters (paper cycle observability)."""

    contexts_built: int = 0
    context_errors: int = 0
    router_no_trade: int = 0
    router_errors: int = 0
    signals_generated: int = 0
    strategy_errors: int = 0
    adapter_errors: int = 0
    duplicate_intents: int = 0
    risk_accepted: int = 0
    risk_rejected: int = 0
    risk_errors: int = 0
    orders_created: int = 0
    broker_errors: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contexts_built": self.contexts_built,
            "context_errors": self.context_errors,
            "router_no_trade": self.router_no_trade,
            "router_errors": self.router_errors,
            "signals_generated": self.signals_generated,
            "strategy_errors": self.strategy_errors,
            "adapter_errors": self.adapter_errors,
            "duplicate_intents": self.duplicate_intents,
            "risk_accepted": self.risk_accepted,
            "risk_rejected": self.risk_rejected,
            "risk_errors": self.risk_errors,
            "orders_created": self.orders_created,
            "broker_errors": self.broker_errors,
            "rejections": list(self.rejections),
        }


def _reject(counts: CycleStageCounts, symbol: str, stage: str, reason: str) -> dict[str, Any]:
    entry = {"symbol": symbol, "stage": stage, "reason": reason}
    counts.rejections.append(entry)
    return entry


def _pit_slice(bars: list[OHLCV], ts: int) -> list[OHLCV]:
    return trim_to_pit(bars, ts)


def _fingerprint(bars: list[OHLCV]) -> str:
    """Deterministic content hash of the PIT slice (provenance, N3).

    The context must carry a data fingerprint; for fetcher-sourced paper
    history the fingerprint IS the content hash of the exact bars used —
    same bars ⇒ same context ⇒ same decision.
    """
    payload = json.dumps(
        [[b.symbol, b.timestamp, b.open, b.high, b.low, b.close, b.volume] for b in bars],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class PaperCycleEngine:
    """Executes the canonical decision cycle for the scanned universe.

    Dependencies are canonical components only. No strategy selection
    happens here: the StrategyRouter decides, families generate, the
    SignalAdapter converts, risk approves, the broker executes.
    """

    def __init__(
        self,
        *,
        asset_registry: CryptoAssetAgentRegistry,
        router: StrategyRouter,
        strategy_map: dict[str, dict[str, Any]],
        families: dict[str, Any],  # family_name → AlphaFamily-like
        risk_manager: RiskManager,
        broker: Any,  # PaperBroker
        indicator_fn: Any | None = None,  # candles → dict[str, IndicatorResult]
        idempotency: IdempotencyGuard | None = None,
    ) -> None:
        self._registry = asset_registry
        self._router = router
        self._strategy_map = strategy_map
        self._families = families
        self._risk = risk_manager
        self._broker = broker
        self._indicator_fn = indicator_fn
        self._idempotency = idempotency or IdempotencyGuard()

    @property
    def idempotency(self) -> IdempotencyGuard:
        return self._idempotency

    @property
    def risk_manager(self) -> RiskManager:
        """Public accessor used by the runner to sync broker equity."""
        return self._risk

    def run_cycle_sync(
        self,
        history: dict[str, list[OHLCV]],
        decision_timestamps: dict[str, int],
    ) -> CycleStageCounts:
        """Run the canonical cycle synchronously for each symbol.

        ``history`` maps symbol → recent OHLCV series; the PIT slice
        (bars <= decision timestamp) is taken before any feature or
        context computation.
        """
        counts = CycleStageCounts()
        candidates: list[TradeCandidate] = []
        # (symbol, alpha, decision_ts) surviving routing
        routed: list[tuple[str, Any, int]] = []

        # -- FASE 7B: context + canonical routing ---------------------------
        for symbol in sorted(history):
            ts = int(decision_timestamps.get(symbol, 0))
            try:
                bars = _pit_slice(list(history.get(symbol, [])), ts)
                context = self._registry.build_context(
                    symbol.split("/")[0],
                    bars,
                    ts,
                    data_fingerprint=_fingerprint(bars),
                )
            except Exception as exc:  # context failure ⇒ no order
                counts.context_errors += 1
                _reject(counts, symbol, "context", f"{type(exc).__name__}: {exc}")
                continue
            counts.contexts_built += 1

            try:
                decision: RouterDecision = self._router.route(
                    context, context.market_regime, self._strategy_map
                )
            except Exception as exc:  # router failure ⇒ no order
                counts.router_errors += 1
                _reject(counts, symbol, "router", f"{type(exc).__name__}: {exc}")
                continue

            if decision.is_no_trade or not decision.strategy_id:
                counts.router_no_trade += 1
                _reject(counts, symbol, "router", f"NO_TRADE:{decision.no_trade_reason}")
                continue

            family = self._families.get(decision.family or "")
            if family is None:
                counts.strategy_errors += 1
                _reject(counts, symbol, "strategy", f"family_not_found:{decision.family}")
                continue

            wanted = (decision.direction or "ANY").upper()
            try:
                indicators = self._indicator_fn(bars) if self._indicator_fn is not None else {}
                alphas = family.generate(bars, indicators, None)
            except Exception as exc:  # strategy failure ⇒ no order
                counts.strategy_errors += 1
                _reject(counts, symbol, "strategy", f"{type(exc).__name__}: {exc}")
                continue

            counts.signals_generated += len(alphas)
            matching = [
                a
                for a in alphas
                if wanted == "ANY" or str(getattr(a, "direction", "")).upper() == wanted
            ]
            if not matching:
                _reject(counts, symbol, "strategy", f"no_alpha_in_direction:{wanted}")
                continue

            for alpha in matching:
                routed.append((symbol, alpha, ts))

        # -- FASE 7C: candidates → consolidation (pre-risk) ------------------
        for symbol, alpha, ts in routed:
            try:
                candidates.append(
                    TradeCandidate(
                        asset=symbol.split("/")[0],
                        strategy_id=str(getattr(alpha, "family", "") or "unknown"),
                        family=str(getattr(alpha, "family", "") or ""),
                        direction=str(getattr(alpha, "direction", "")).upper(),
                        timestamp=int(getattr(alpha, "timestamp", ts)),
                        score=float(getattr(alpha, "confidence", 0.0) or 0.0),
                        entry_reference=float(getattr(alpha, "entry_reference", 0.0) or 0.0),
                        structural_stop=getattr(alpha, "structural_stop", None),
                        regime=None,
                        expected_risk_pct=None,
                        correlation_group=symbol.split("/")[0],
                    )
                )
            except Exception as exc:  # invalid alpha ⇒ not a candidate
                counts.adapter_errors += 1
                _reject(counts, symbol, "candidate", f"{type(exc).__name__}: {exc}")

        portfolio = build_portfolio(candidates)

        # -- FASE 8A/8B: mandatory risk path → PaperBroker only --------------
        for cand in portfolio.candidates:
            symbol = f"{cand.asset}/USDT"
            alpha = next(
                (
                    a
                    for (sym, a, _ts) in routed
                    if sym == symbol
                    and str(getattr(a, "family", "")) == cand.family
                    and str(getattr(a, "direction", "")).upper() == cand.direction
                ),
                None,
            )
            if alpha is None:
                counts.risk_errors += 1
                _reject(counts, symbol, "risk", "candidate_without_alpha")
                continue

            cloid = intent_cloid(
                symbol, cand.strategy_id, cand.direction, int(getattr(alpha, "timestamp", 0))
            )
            if self._idempotency.is_duplicate(cloid):
                counts.duplicate_intents += 1
                _reject(counts, symbol, "idempotency", f"duplicate_intent:{cloid}")
                continue

            try:
                base_signal = alpha_signal_to_signal(alpha)
            except AdapterError as exc:
                counts.adapter_errors += 1
                _reject(counts, symbol, "adapter", str(exc))
                continue
            except Exception as exc:  # unexpected adaptation failure
                counts.adapter_errors += 1
                _reject(counts, symbol, "adapter", f"{type(exc).__name__}: {exc}")
                continue

            try:
                check = self._risk.check_signal(base_signal)
            except Exception as exc:  # risk engine failure ⇒ no order
                counts.risk_errors += 1
                _reject(counts, symbol, "risk", f"{type(exc).__name__}: {exc}")
                continue

            if not check.approved or check.position_size is None:
                counts.risk_rejected += 1
                _reject(counts, symbol, "risk", check.reason or "risk_rejected")
                continue
            counts.risk_accepted += 1
            size = check.position_size

            # Rebuild the frozen Signal with risk-approved values (no mutation).
            try:
                approved_signal = dataclasses.replace(
                    base_signal,
                    stop_loss_pct=size.stop_loss_pct,
                    take_profit_pct=size.take_profit_pct,
                    metadata={
                        **base_signal.metadata,
                        "notional_usdt": size.notional_usdt,
                        "cloid": cloid,
                        "risk_approved_by": "RiskManager",
                    },
                )
                result = self._broker.execute_signal(approved_signal)
            except Exception as exc:  # broker failure ⇒ no order
                counts.broker_errors += 1
                _reject(counts, symbol, "broker", f"{type(exc).__name__}: {exc}")
                continue

            if result is not None:
                counts.orders_created += 1
                self._idempotency.register(cloid)
            else:
                _reject(counts, symbol, "broker", "broker_returned_no_fill")

        return counts


class RouteOnlyEngine:
    """Context → Router only (no signal generation, no execution).

    Used by the runner when no families are configured: the canonical
    path still runs (context built, router consulted) and every NO_TRADE
    is observable, preserving fail-closed semantics.
    """

    def __init__(
        self,
        *,
        asset_registry: CryptoAssetAgentRegistry,
        router: StrategyRouter,
        strategy_map: dict[str, dict[str, Any]],
    ) -> None:
        self._registry = asset_registry
        self._router = router
        self._strategy_map = strategy_map

    def run_cycle_sync(
        self,
        history: dict[str, list[OHLCV]],
        decision_timestamps: dict[str, int],
    ) -> CycleStageCounts:
        counts = CycleStageCounts()
        for symbol in sorted(history):
            ts = int(decision_timestamps.get(symbol, 0))
            try:
                bars = _pit_slice(list(history.get(symbol, [])), ts)
                context = self._registry.build_context(
                    symbol.split("/")[0],
                    bars,
                    ts,
                    data_fingerprint=_fingerprint(bars),
                )
            except Exception as exc:
                counts.context_errors += 1
                _reject(counts, symbol, "context", f"{type(exc).__name__}: {exc}")
                continue
            counts.contexts_built += 1
            try:
                decision = self._router.route(context, context.market_regime, self._strategy_map)
            except Exception as exc:
                counts.router_errors += 1
                _reject(counts, symbol, "router", f"{type(exc).__name__}: {exc}")
                continue
            if decision.is_no_trade or not decision.strategy_id:
                counts.router_no_trade += 1
                _reject(counts, symbol, "router", f"NO_TRADE:{decision.no_trade_reason}")
        return counts
