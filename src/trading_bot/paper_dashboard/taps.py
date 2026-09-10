"""Taps — pass-through wrappers that observe the canonical paper runtime.

The taps are the ONLY coupling between the trading loop and the dashboard.
Design rules (PHASE UI-01):

- Wrap, never modify: every wrapped object delegates to the real
  component and publishes an observability event afterwards. The
  decision logic itself (StrategyRouter, PaperCycleEngine, PaperBroker)
  is untouched — each tap is a transparent decorator.
- Publish must never raise: observability failures are contained.
- No execution surface: the taps expose zero methods that place,
  modify or cancel orders. They are read-only observers.
"""

from __future__ import annotations

import contextlib
from typing import Any

from .events import DashboardEventBus


class _TapBase:
    """Shared containment: a broken bus never breaks the trading loop."""

    def __init__(self, bus: DashboardEventBus | None) -> None:
        self._bus = bus

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(event_type, payload)
        except Exception:
            return


class ObservedBroker(_TapBase):
    """Read-only observability wrapper around PaperBroker.

    Delegates every call to the real broker. Intercepts only the
    execution results to emit ``position_opened`` / ``position_closed``
    / ``sl_triggered`` / ``tp_triggered`` events for the dashboard.
    """

    def __init__(self, broker: Any, bus: DashboardEventBus | None = None) -> None:
        super().__init__(bus)
        self._broker = broker

    def __getattr__(self, name: str) -> Any:
        # Anything not explicitly wrapped is delegated untouched.
        return getattr(self._broker, name)

    def execute_signal(self, signal: Any) -> Any:
        result = self._broker.execute_signal(signal)
        try:
            if result is None:
                self._publish(
                    "signal_rejected",
                    {
                        "symbol": getattr(signal, "symbol", None),
                        "stage": "broker",
                        "reason": "broker_returned_no_fill",
                    },
                )
            elif hasattr(result, "entry_price") and hasattr(result, "symbol"):
                event_type = "position_opened"
                if hasattr(result, "exit_reason"):
                    event_type = "position_closed"
                self._publish(
                    event_type,
                    {
                        "symbol": getattr(result, "symbol", None),
                        "side": getattr(result, "side", None),
                        "entry_price": getattr(result, "entry_price", None),
                        "exit_price": getattr(result, "exit_price", None),
                        "quantity": getattr(result, "quantity", None),
                        "stop_loss_pct": getattr(result, "stop_loss_pct", None),
                        "take_profit_pct": getattr(result, "take_profit_pct", None),
                        "strategy": getattr(signal, "strategy_name", None),
                        "opened_at": getattr(result, "opened_at", None),
                        "closed_at": getattr(result, "closed_at", None),
                        "pnl": getattr(result, "pnl", None),
                        "exit_reason": getattr(result, "exit_reason", None),
                    },
                )
        except Exception:
            pass
        return result

    def check_positions(self, prices: dict[str, float]) -> list[Any]:
        closed: list[Any] = list(self._broker.check_positions(prices))
        self._emit_exit_events(closed)
        return closed

    def check_positions_ohlc(
        self, candles: dict[str, tuple[float, float, float, float]], **kwargs: Any
    ) -> list[Any]:
        closed: list[Any] = list(self._broker.check_positions_ohlc(candles, **kwargs))
        self._emit_exit_events(closed)
        return closed

    def _emit_exit_events(self, closed: list[Any]) -> None:
        for trade in closed or []:
            try:
                reason = str(getattr(trade, "exit_reason", ""))
                event = {
                    "take_profit": "tp_triggered",
                    "stop_loss": "sl_triggered",
                }.get(reason, "position_closed")
                pnl = getattr(trade, "pnl", 0.0) or 0.0
                entry = getattr(trade, "entry_price", 0.0) or 0.0
                exit_p = getattr(trade, "exit_price", 0.0) or 0.0
                side = getattr(trade, "side", "buy")
                pnl_pct = (
                    (exit_p / entry - 1.0) * 100.0 * (1.0 if side == "buy" else -1.0)
                    if entry and exit_p
                    else 0.0
                )
                self._publish(
                    event,
                    {
                        "symbol": getattr(trade, "symbol", None),
                        "side": side,
                        "entry_price": entry,
                        "exit_price": exit_p,
                        "quantity": getattr(trade, "quantity", None),
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "exit_reason": reason,
                        "opened_at": getattr(trade, "opened_at", None),
                        "closed_at": getattr(trade, "closed_at", None),
                    },
                )
            except Exception:
                continue


class ObservedRouter(_TapBase):
    """Observability wrapper around the canonical StrategyRouter.

    The router is a pure resolver, so wrapping it is transparent: the
    engine receives bit-identical decisions while the dashboard observes
    every per-asset routing outcome (WHY TRADE / WHY NO TRADE).
    """

    def __init__(self, router: Any, bus: DashboardEventBus | None = None) -> None:
        super().__init__(bus)
        self._router = router

    def route(self, context: Any, regime: Any, strategy_map: Any) -> Any:
        decision = self._router.route(context, regime, strategy_map)
        try:
            asset = str(getattr(decision, "asset", "?"))
            symbol = asset if "/" in asset else f"{asset}/USDT"
            effective_regime = regime or getattr(context, "market_regime", None)
            if decision.is_no_trade or not decision.strategy_id:
                self._publish(
                    "signal_rejected",
                    {
                        "symbol": symbol,
                        "stage": "router",
                        "reason": f"NO_TRADE:{getattr(decision, 'no_trade_reason', None)}",
                        "regime": effective_regime,
                    },
                )
            else:
                self._publish(
                    "context_built",
                    {
                        "symbol": symbol,
                        "regime": effective_regime,
                        "timestamp": getattr(decision, "timestamp", None),
                    },
                )
                self._publish(
                    "strategy_selected",
                    {
                        "symbol": symbol,
                        "strategy": decision.strategy_id,
                        "family": getattr(decision, "family", None),
                        "direction": getattr(decision, "direction", None),
                        "regime": effective_regime,
                    },
                )
        except Exception:
            pass
        return decision


class ObservedEngine(_TapBase):
    """Observability wrapper around PaperCycleEngine.run_cycle_sync.

    Delegates to the real engine (the certified decision path is NOT
    re-implemented) and translates the resulting CycleStageCounts into
    per-cycle aggregate events (risk outcomes, order counts).
    """

    def __init__(self, engine: Any, bus: DashboardEventBus | None = None) -> None:
        super().__init__(bus)
        self._engine = engine

    def run_cycle_sync(
        self,
        history: dict[str, list[Any]],
        decision_timestamps: dict[str, int],
    ) -> Any:
        counts = self._engine.run_cycle_sync(history, decision_timestamps)
        with contextlib.suppress(Exception):
            self._emit_from_counts(counts)
        return counts

    def _emit_from_counts(self, counts: Any) -> None:
        # Risk/adapter/broker rejections from the canonical counters.
        rejections = list(getattr(counts, "rejections", []) or [])
        for rej in rejections:
            stage = rej.get("stage")
            if stage == "risk":
                self._publish(
                    "risk_rejected",
                    {"symbol": rej.get("symbol"), "reason": rej.get("reason")},
                )
            elif stage in ("adapter", "candidate", "broker", "idempotency", "strategy"):
                self._publish(
                    "signal_rejected",
                    {"symbol": rej.get("symbol"), "stage": stage, "reason": rej.get("reason")},
                )
        risk_accepted = int(getattr(counts, "risk_accepted", 0) or 0)
        if risk_accepted:
            self._publish("risk_accepted", {"count": risk_accepted})
        self._publish(
            "cycle_completed",
            {
                "contexts_built": getattr(counts, "contexts_built", 0),
                "signals_generated": getattr(counts, "signals_generated", 0),
                "risk_accepted": getattr(counts, "risk_accepted", 0),
                "risk_rejected": getattr(counts, "risk_rejected", 0),
                "orders_created": getattr(counts, "orders_created", 0),
                "router_no_trade": getattr(counts, "router_no_trade", 0),
            },
        )


__all__ = ["ObservedBroker", "ObservedEngine", "ObservedRouter"]
