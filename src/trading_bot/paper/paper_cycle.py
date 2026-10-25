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

from trading_bot.autonomous.hot_stop import HotStopGate
from trading_bot.config.risk import DefensiveBlocks
from trading_bot.execution.idempotency import IdempotencyGuard
from trading_bot.market_data.types import OHLCV
from trading_bot.paper.candidate_portfolio import TradeCandidate, build_portfolio
from trading_bot.paper.signal_adapter import AdapterError, alpha_signal_to_signal
from trading_bot.paper.snapshot_context import trim_to_pit
from trading_bot.research.asset_intelligence.registry import CryptoAssetAgentRegistry
from trading_bot.research.strategy_router import RouterDecision, StrategyRouter
from trading_bot.risk.defensive_blocks import BlockVerdict, MarketConditions, evaluate_blocks
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
    router_invocations: int = 0
    router_no_trade: int = 0
    router_errors: int = 0
    strategy_invocations: int = 0
    signals_generated: int = 0
    strategy_errors: int = 0
    adapter_errors: int = 0
    bar_close_skips: int = 0
    duplicate_intents: int = 0
    risk_accepted: int = 0
    risk_rejected: int = 0
    risk_errors: int = 0
    orders_created: int = 0
    broker_errors: int = 0
    #: G-4: entries refused because the runtime stop was engaged. Reductions are
    #: not counted here: they are allowed while stopped (a stop must not trap the
    #: book). Published so an operator can tell "no signal" from "stopped".
    hot_stop_blocked: int = 0
    #: DEF-RUN-015: an exit is not an entry. ``exits_requested`` counts the exit
    #: evaluations this cycle produced, ``exits_closed`` how many actually closed a book
    #: position, ``reversals_refused`` an opposite signal the broker refused, and
    #: ``same_side_skips`` a signal whose side was already held.
    exits_requested: int = 0
    exits_closed: int = 0
    reversals_refused: int = 0
    same_side_skips: int = 0
    #: WP-EDGE-017/P0.4: one count per defensive block that fired (by block id).
    defensive_blocks: dict[str, int] = field(default_factory=dict)
    rejections: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contexts_built": self.contexts_built,
            "context_errors": self.context_errors,
            "router_invocations": self.router_invocations,
            "router_no_trade": self.router_no_trade,
            "router_errors": self.router_errors,
            "strategy_invocations": self.strategy_invocations,
            "signals_generated": self.signals_generated,
            "strategy_errors": self.strategy_errors,
            "adapter_errors": self.adapter_errors,
            "bar_close_skips": self.bar_close_skips,
            "duplicate_intents": self.duplicate_intents,
            "risk_accepted": self.risk_accepted,
            "risk_rejected": self.risk_rejected,
            "risk_errors": self.risk_errors,
            "orders_created": self.orders_created,
            "broker_errors": self.broker_errors,
            "hot_stop_blocked": self.hot_stop_blocked,
            "exits_requested": self.exits_requested,
            "exits_closed": self.exits_closed,
            "reversals_refused": self.reversals_refused,
            "same_side_skips": self.same_side_skips,
            "defensive_blocks": dict(self.defensive_blocks),
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

    BAR_CLOSE gate (BURN-IN-V2): ema_crossover and the other committed
    families are pure functions of the PIT bar window (verified audit:
    same closed candles + unchanged risk state ⇒ same alphas). When the
    relevant state has NOT changed since the last evaluation for the same
    latest-closed-candle, the strategy stage is skipped and the cycle
    records ``bar_close_skips`` — Risk only sees meaningful proposals.
    Relevant state = risk counters that can flip a decision (kill switch,
    cooldown, daily loss, trade count) plus portfolio occupancy (open
    positions change the broker same-side outcome) and cycle freshness
    (a NEW snapshot timestamp means new market data may have arrived).
    The execution idempotency layer is untouched and remains the final
    safety barrier.
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
        # WP-EDGE-017/P0.4: the four declared defensive blocks. ``None`` keeps the
        # historical behaviour for callers that have not opted in; the paper
        # launcher always supplies the policy from config/risk.yaml.
        defensive_blocks: DefensiveBlocks | None = None,
        # G-4: the operator stop, at the same boundary the autonomous runtime
        # uses. ``None`` is an embedding/test caller; the paper launcher always
        # supplies a gate. A gate cannot be bypassed by a strategy or a signal.
        hot_stop: HotStopGate | None = None,
    ) -> None:
        self._registry = asset_registry
        self._router = router
        self._strategy_map = strategy_map
        self._families = families
        self._risk = risk_manager
        self._broker = broker
        self._indicator_fn = indicator_fn
        self._idempotency = idempotency or IdempotencyGuard()
        self._defensive_blocks = defensive_blocks
        self._hot_stop = hot_stop
        # BAR_CLOSE gate state (BURN-IN-V2): per symbol, the (bar_ts, state
        # version) already evaluated. State version bumps when anything that
        # could legitimately change a decision happens (risk counters,
        # portfolio occupancy, kill switch, reconciliation restore).
        self._bar_gate: dict[str, tuple[int, int, tuple[float, int, int, float, bool]]] = {}
        self._state_version = 0

    @property
    def idempotency(self) -> IdempotencyGuard:
        return self._idempotency

    @property
    def risk_manager(self) -> RiskManager:
        """Public accessor used by the runner to sync broker equity."""
        return self._risk

    @property
    def hot_stop(self) -> HotStopGate | None:
        """The operator-stop boundary, when the composed route supplied one."""
        return self._hot_stop

    def _process_stop_active(self) -> bool:
        """The boot-time process authority, fail closed on an unreadable switch."""
        if self._hot_stop is None:
            return False
        try:
            return bool(getattr(self._hot_stop.kill_switch, "is_active", False))
        except Exception:
            return True

    def _hot_stop_verdict(self) -> str | None:
        """Why a new entry is refused, or ``None`` when it may dispatch.

        The marker (polled here and again under the boundary lock) is named
        separately from the boot-time process switch so the evidence says which
        authority refused. An exception is a refusal, never permission.
        """
        if self._hot_stop is None:
            return None
        try:
            if self._hot_stop.engaged or self._hot_stop.poll():
                return f"marker:{self._hot_stop.engaged_reason or 'engaged'}"
        except Exception:
            return "marker:unreadable"
        if self._process_stop_active():
            return "process"
        return None

    def pending_intents(self) -> list[str]:
        """Snapshot of the intent ledger (durable persistence, GAP-R1)."""
        return sorted(self._idempotency.sent_cloids)

    # -- BAR_CLOSE gate (BURN-IN-V2) ------------------------------------------

    def bump_state_version(self, reason: str) -> None:
        """Force re-evaluation for all symbols (legitimate state change).

        Called by the runner when something that can legitimately change a
        decision happens between cycles: a position closed (portfolio
        changed), risk counters moved (cooldown expiry, daily reset,
        kill-switch flip), reconciliation restored state, or a manual
        reset. The gate must never mask these.
        """
        self._state_version += 1
        self._log_state_bump(reason)

    def _log_state_bump(self, reason: str) -> None:
        import structlog

        structlog.get_logger("paper_cycle").info(
            "paper.bar_gate.state_bumped", reason=reason, version=self._state_version
        )

    def _bar_gate_allows(self, symbol: str, bars: list[OHLCV]) -> bool:
        """True when strategy evaluation is REQUIRED for this symbol.

        Skip only when ALL hold:
        - same latest-closed-candle timestamp as the last evaluation;
        - unchanged relevant state version (risk/portfolio/kill switch);
        - the risk engine's snapshot is unchanged since that evaluation
          (equity, open-position count, trades_today, daily pnl).

        Anything else (new candle, state bump, restored book, counter
        movement) ⇒ evaluate. Fail-open: unknown symbol ⇒ evaluate.
        """
        if not bars:
            return True
        latest_bar_ts = bars[-1].timestamp
        risk_sig = self._risk_signature()
        key = (latest_bar_ts, self._state_version, risk_sig)
        if self._bar_gate.get(symbol) == key:
            return False
        self._bar_gate[symbol] = key
        return True

    def _risk_signature(self) -> tuple[float, int, int, float, bool]:
        """Fingerprint of risk state that can flip a decision."""
        r = self._risk
        return (
            round(float(getattr(r, "equity", 0.0)), 6),
            len(getattr(r, "open_positions", {}) or {}),
            int(getattr(r, "trades_today", 0)),
            round(float(getattr(r, "daily_pnl", 0.0)), 6),
            bool(getattr(r, "kill_switch_active", False)),
        )

    def _defensive_verdict(
        self, symbol: str, conditions: dict[str, MarketConditions] | None
    ) -> BlockVerdict | None:
        """Evaluate the declared blocks, failing closed if their inputs are absent."""
        if self._defensive_blocks is None:
            return None
        return evaluate_blocks(self._defensive_blocks, (conditions or {}).get(symbol))

    def run_cycle_sync(
        self,
        history: dict[str, list[OHLCV]],
        decision_timestamps: dict[str, int],
        conditions: dict[str, MarketConditions] | None = None,
    ) -> CycleStageCounts:
        """Run the canonical cycle synchronously for each symbol.

        ``history`` maps symbol → recent OHLCV series; the PIT slice
        (bars <= decision timestamp) is taken before any feature or
        context computation. ``conditions`` carries the measured market
        context the defensive blocks need; a symbol absent from it is blocked
        (``market_conditions_unknown``), never waved through.
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
            counts.router_invocations += 1

            if decision.is_no_trade or not decision.strategy_id:
                counts.router_no_trade += 1
                _reject(counts, symbol, "router", f"NO_TRADE:{decision.no_trade_reason}")
                continue

            # -- BAR_CLOSE gate: skip redundant same-bar evaluation --------
            # AFTER routing (router+context stay observable every cycle) but
            # BEFORE family generation/risk/broker (where churn lives).
            if not self._bar_gate_allows(symbol, bars):
                counts.bar_close_skips += 1
                _reject(counts, symbol, "bar_gate", "same_bar_unchanged_state")
                continue

            family = self._families.get(decision.family or "")
            if family is None:
                counts.strategy_errors += 1
                _reject(counts, symbol, "strategy", f"family_not_found:{decision.family}")
                continue
            counts.strategy_invocations += 1

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

            # Idempotency first: exactly-once is about the intent, and it must keep its
            # meaning (a repeated intent is a duplicate, not a new position signal).
            cloid = intent_cloid(
                symbol, cand.strategy_id, cand.direction, int(getattr(alpha, "timestamp", 0))
            )
            if self._idempotency.is_duplicate(cloid):
                counts.duplicate_intents += 1
                _reject(counts, symbol, "idempotency", f"duplicate_intent:{cloid}")
                continue

            # -- DEF-RUN-015: occupancy is resolved BEFORE the entry gates ----------
            #
            # A gate that blocks an exit is a bug, not a policy (``max_open_positions``
            # rejecting the very signal that would free a slot is the clearest case). So
            # the position is inspected here: same side is a skip, the opposite side is an
            # exit *request* — never an entry, and never a reversal.
            held = self._broker.positions.get(symbol)
            if held is not None:
                held_side = str(getattr(held, "side", ""))
                wanted_side = "buy" if cand.direction.upper() == "LONG" else "sell"
                if held_side == wanted_side:
                    counts.same_side_skips += 1
                    _reject(counts, symbol, "position", "same_side_already_open")
                    continue
                counts.exits_requested += 1
                exit_price = float(cand.entry_reference or 0.0)
                if exit_price <= 0:
                    _reject(counts, symbol, "exit", "EXIT_WITHOUT_PRICE")
                    continue
                try:
                    closed = self._broker.close_position(
                        symbol, exit_price, "OPPOSITE_SIGNAL_EXIT_EVALUATION"
                    )
                except Exception as exc:  # broker failure ⇒ no order, loud and recorded
                    counts.broker_errors += 1
                    _reject(counts, symbol, "broker", f"{type(exc).__name__}: {exc}")
                    continue
                if closed is None:
                    _reject(counts, symbol, "exit", "exit_requested_no_position")
                    continue
                counts.exits_closed += 1
                _reject(counts, symbol, "exit", "CLOSED_ON_OPPOSITE_SIGNAL")
                #: The book changed: the next cycle must re-evaluate, not skip on the
                #: bar gate.
                self.bump_state_version("position_closed:opposite_signal")
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

            verdict = self._defensive_verdict(symbol, conditions)
            if verdict is not None and verdict.blocked:
                counts.risk_rejected += 1
                key = verdict.blocked_by or "defensive_block"
                counts.defensive_blocks[key] = counts.defensive_blocks.get(key, 0) + 1
                _reject(
                    counts,
                    symbol,
                    "defensive_block",
                    f"{key}: {verdict.reason or 'blocked'}",
                )
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
                # G-4 — the same boundary the autonomous runtime uses. The lock
                # is held across the broker call, so an operator engagement cannot
                # ACK while this dispatch is in flight. A marker written before the
                # call refuses it; a process switch (KILL_SWITCH_ENV) refuses it
                # even when there is no marker. Reductions never reach this block:
                # the exit path above is deliberately outside the stop.
                if self._hot_stop is None:
                    result = self._broker.execute_signal(approved_signal)
                else:
                    refusal = self._hot_stop_verdict()
                    if refusal is not None:
                        counts.hot_stop_blocked += 1
                        _reject(
                            counts,
                            symbol,
                            "hot_stop",
                            f"kill_switch_active:{refusal}",
                        )
                        continue
                    with self._hot_stop.order_boundary() as allowed:
                        if not allowed:
                            counts.hot_stop_blocked += 1
                            reason = self._hot_stop.engaged_reason or "marker"
                            _reject(
                                counts,
                                symbol,
                                "hot_stop",
                                f"kill_switch_active:marker:{reason}",
                            )
                            continue
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
        conditions: dict[str, Any] | None = None,
    ) -> CycleStageCounts:
        """Route-only path: it places no orders, so there are no blocks to apply.

        ``conditions`` is accepted so the caller uses one signature for both
        engines; nothing here can trade, so nothing here is blocked.
        """
        del conditions
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
            counts.router_invocations += 1
            if decision.is_no_trade or not decision.strategy_id:
                counts.router_no_trade += 1
                _reject(counts, symbol, "router", f"NO_TRADE:{decision.no_trade_reason}")
        return counts
