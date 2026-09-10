"""In-memory, read-only projection of the PAPER runtime."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    timestamp: float = 0.0
    runtime_status: str = "STOPPED"
    mode: str = "paper"
    equity: float = 0.0
    initial_equity: float = 0.0
    cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    drawdown_pct: float = 0.0
    cycles: int = 0
    assets_scanned: int = 0
    contexts_built: int = 0
    signals_generated: int = 0
    risk_accepted: int = 0
    risk_rejected: int = 0
    router_no_trade: int = 0
    orders_created: int = 0
    positions_open: int = 0
    positions_closed: int = 0
    trades_today: int = 0
    wins: int = 0
    losses: int = 0
    open_positions: tuple[dict[str, Any], ...] = ()
    recent_trades: tuple[dict[str, Any], ...] = ()
    recent_signals: tuple[dict[str, Any], ...] = ()
    recent_risk_decisions: tuple[dict[str, Any], ...] = ()
    recent_events: tuple[dict[str, Any], ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    strategies: tuple[dict[str, Any], ...] = ()
    equity_curve: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return round(self.wins / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["win_rate"] = self.win_rate
        for name in (
            "open_positions",
            "recent_trades",
            "recent_signals",
            "recent_risk_decisions",
            "recent_events",
            "assets",
            "strategies",
            "equity_curve",
            "errors",
        ):
            data[name] = list(data[name])
        for name in ("equity", "initial_equity", "cash", "realized_pnl", "unrealized_pnl"):
            data[name] = round(data[name], 4)
        data["drawdown_pct"] = round(data["drawdown_pct"], 2)
        return data


def _day_start() -> float:
    now = time.localtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))


class DashboardStore:
    """Thread-safe presentation cache; it never writes canonical trading state."""

    def __init__(self, *, now_fn: Any = time.time) -> None:
        self._lock = threading.RLock()
        self._now_fn = now_fn
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._signals: deque[dict[str, Any]] = deque(maxlen=100)
        self._risk: deque[dict[str, Any]] = deque(maxlen=100)
        self._trades: deque[dict[str, Any]] = deque(maxlen=200)
        self._positions: dict[str, dict[str, Any]] = {}
        self._prices: dict[str, float] = {}
        self._regimes: dict[str, Any] = {}
        self._strategies: dict[str, Any] = {}
        self._directions: dict[str, Any] = {}
        self._daily_trades: dict[str, int] = {}
        self._daily_pnl: dict[str, float] = {}
        self._strategy_stats: dict[str, dict[str, Any]] = {}
        self._curve: deque[dict[str, Any]] = deque(maxlen=500)
        self._counters = {
            key: 0
            for key in (
                "contexts_built",
                "signals_generated",
                "risk_accepted",
                "risk_rejected",
                "router_no_trade",
                "orders_created",
                "assets_scanned",
            )
        }
        self._cycles = self._wins = self._losses = 0
        self._equity = self._initial = self._realized = 0.0
        self._mode = "paper"
        self._running = False
        self._degraded = False
        self._errors: list[str] = []

    def handle_event(self, event: Any) -> None:
        try:
            typ, payload = event.type, dict(event.payload or {})
            with self._lock:
                self._events.append({"type": typ, "timestamp": event.timestamp, **payload})
                handler = getattr(self, f"_event_{typ}", None)
                if handler:
                    handler(payload)
        except Exception:
            return

    def _event_cycle_completed(self, p: dict[str, Any]) -> None:
        self._cycles += 1
        for key in self._counters:
            if key != "assets_scanned":
                self._counters[key] += int(p.get(key) or 0)

    def _event_context_built(self, p: dict[str, Any]) -> None:
        symbol = str(p.get("symbol") or "?")
        self._regimes[symbol] = p.get("regime")
        self._counters["contexts_built"] += 1

    def _event_strategy_selected(self, p: dict[str, Any]) -> None:
        symbol = str(p.get("symbol") or "?")
        self._strategies[symbol] = p.get("strategy")
        self._directions[symbol] = p.get("direction")

    def _event_signal_rejected(self, p: dict[str, Any]) -> None:
        item = {
            "symbol": str(p.get("symbol") or "?"),
            "stage": p.get("stage") or "unknown",
            "reason": p.get("reason"),
            "timestamp": self._now_fn(),
        }
        self._signals.append(item)
        if p.get("regime"):
            self._regimes[item["symbol"]] = p["regime"]

    def _event_risk_rejected(self, p: dict[str, Any]) -> None:
        item = {
            "symbol": str(p.get("symbol") or "?"),
            "decision": "REJECT",
            "reason": p.get("reason"),
            "timestamp": self._now_fn(),
        }
        self._risk.append(item)
        self._signals.append({**item, "stage": "risk"})

    def _event_risk_accepted(self, p: dict[str, Any]) -> None:
        self._risk.append(
            {
                "symbol": p.get("symbol"),
                "decision": "ACCEPT",
                "reason": p.get("reason"),
                "count": p.get("count"),
                "timestamp": self._now_fn(),
            }
        )

    @staticmethod
    def _stop_price(side: str, entry: float, pct: float, take_profit: bool) -> float:
        if not entry:
            return 0.0
        direction = 1 if (side == "buy") == take_profit else -1
        return round(entry * (1 + direction * pct / 100), 8)

    def _event_position_opened(self, p: dict[str, Any]) -> None:
        symbol = str(p.get("symbol") or "?")
        entry = float(p.get("entry_price") or 0)
        side = str(p.get("side") or "buy")
        self._positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "strategy": p.get("strategy") or self._strategies.get(symbol),
            "entry_price": entry,
            "quantity": float(p.get("quantity") or 0),
            "stop_loss_price": self._stop_price(
                side, entry, float(p.get("stop_loss_pct") or 0), False
            ),
            "take_profit_price": self._stop_price(
                side, entry, float(p.get("take_profit_pct") or 0), True
            ),
            "opened_at": float(p.get("opened_at") or self._now_fn()),
        }

    def _event_position_closed(self, p: dict[str, Any]) -> None:
        self._record_trade(p)

    def _event_sl_triggered(self, p: dict[str, Any]) -> None:
        self._record_trade(p)

    def _event_tp_triggered(self, p: dict[str, Any]) -> None:
        self._record_trade(p)

    def _record_trade(self, p: dict[str, Any]) -> None:
        symbol = str(p.get("symbol") or "?")
        pos = self._positions.pop(symbol, None)
        pnl = float(p.get("pnl") or 0)
        entry = float(p.get("entry_price") or (pos or {}).get("entry_price") or 0)
        closed = float(p.get("closed_at") or self._now_fn())
        opened = float(p.get("opened_at") or (pos or {}).get("opened_at") or 0)
        trade = {
            "symbol": symbol,
            "side": p.get("side") or (pos or {}).get("side") or "buy",
            "strategy": p.get("strategy") or (pos or {}).get("strategy") or "unknown",
            "entry_price": entry or None,
            "exit_price": float(p.get("exit_price") or 0) or None,
            "quantity": float(p.get("quantity") or (pos or {}).get("quantity") or 0),
            "pnl": round(pnl, 4),
            "pnl_pct": round(
                (
                    (float(p.get("exit_price") or 0) / entry - 1)
                    * 100
                    * (1 if (p.get("side") or (pos or {}).get("side") or "buy") == "buy" else -1)
                )
                if entry and p.get("exit_price")
                else 0,
                3,
            ),
            "exit_reason": p.get("exit_reason") or "signal",
            "opened_at": opened or None,
            "closed_at": closed,
            "duration_s": closed - opened if opened else None,
        }
        self._trades.append(trade)
        self._daily_trades[symbol] = self._daily_trades.get(symbol, 0) + 1
        self._daily_pnl[symbol] = self._daily_pnl.get(symbol, 0) + pnl
        if pnl > 0:
            self._wins += 1
        elif pnl < 0:
            self._losses += 1
        stats = self._strategy_stats.setdefault(
            str(trade["strategy"]),
            {
                "signals": 0,
                "accepted": 0,
                "rejected": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
            },
        )
        stats["accepted"] += 1
        stats["pnl"] += pnl
        if pnl > 0:
            stats["wins"] += 1
        elif pnl < 0:
            stats["losses"] += 1

    def _event_runtime_error(self, p: dict[str, Any]) -> None:
        self._errors.append(str(p.get("message") or p.get("reason") or "runtime error"))

    def sync_runtime(
        self,
        *,
        broker: Any | None = None,
        orchestrator_status: dict[str, Any] | None = None,
        running: bool | None = None,
        last_errors: list[str] | None = None,
    ) -> None:
        try:
            with self._lock:
                core = getattr(broker, "_broker", broker) if broker is not None else None
                if core is not None:
                    self._equity = float(getattr(core, "equity", 0) or 0)
                    if self._initial <= 0 and self._equity > 0:
                        self._initial = self._equity
                    positions = getattr(core, "positions", {}) or {}
                    self._positions = {
                        symbol: {
                            "symbol": symbol,
                            "side": getattr(pos, "side", "buy"),
                            "strategy": getattr(pos, "strategy", None),
                            "entry_price": float(getattr(pos, "entry_price", 0)),
                            "quantity": float(getattr(pos, "quantity", 0)),
                            "stop_loss_price": float(getattr(pos, "stop_loss_price", 0)),
                            "take_profit_price": float(getattr(pos, "take_profit_price", 0)),
                            "opened_at": float(getattr(pos, "opened_at", 0)),
                        }
                        for symbol, pos in positions.items()
                    }
                    closed = getattr(core, "_closed_trades", []) or []
                    self._realized = sum(float(getattr(t, "pnl", 0)) for t in closed)
                    self._curve.append({"t": self._now_fn(), "equity": round(self._equity, 4)})
                if orchestrator_status:
                    self._mode = str(orchestrator_status.get("mode") or self._mode)
                    self._degraded = bool(orchestrator_status.get("kill_switch_active"))
                if running is not None:
                    self._running = bool(running)
                if last_errors:
                    self._errors = list(last_errors)[-50:]
        except Exception:
            return

    def update_prices(self, prices: dict[str, float]) -> None:
        try:
            with self._lock:
                self._prices.update(prices)
        except Exception:
            return

    def snapshot(self) -> DashboardSnapshot:
        try:
            with self._lock:
                now = self._now_fn()
                open_positions: list[dict[str, Any]] = []
                unrealized = 0.0
                for symbol, pos in self._positions.items():
                    current = self._prices.get(symbol)
                    entry = float(pos.get("entry_price") or 0)
                    qty = float(pos.get("quantity") or 0)
                    upnl = (
                        (current - entry) * qty * (1 if pos.get("side") == "buy" else -1)
                        if current and entry and qty
                        else 0.0
                    )
                    unrealized += upnl
                    open_positions.append(
                        {
                            **pos,
                            "current_price": current,
                            "unrealized_pnl": round(upnl, 4),
                            "duration_s": now - float(pos.get("opened_at") or now),
                        }
                    )
                symbols = (
                    set(self._prices)
                    | set(self._positions)
                    | set(self._regimes)
                    | {str(x.get("symbol")) for x in self._signals}
                )
                assets = tuple(
                    {
                        "symbol": s,
                        "price": self._prices.get(s),
                        "regime": self._regimes.get(s),
                        "strategy": self._strategies.get(s),
                        "direction": self._directions.get(s),
                        "open_position": s in self._positions,
                        "daily_trades": self._daily_trades.get(s, 0),
                        "daily_pnl": round(self._daily_pnl.get(s, 0), 4),
                    }
                    for s in sorted(symbols)
                )
                status = (
                    "DEGRADED"
                    if self._degraded
                    else "RUNNING"
                    if self._running
                    else "ERROR"
                    if self._errors
                    else "STOPPED"
                )
                trades_today = sum(
                    1 for t in self._trades if float(t.get("closed_at") or 0) >= _day_start()
                )
                peak = max((float(p["equity"]) for p in self._curve), default=0)
                drawdown = max(0, (peak - self._equity) / peak * 100) if peak else 0
                return DashboardSnapshot(
                    timestamp=now,
                    runtime_status=status,
                    mode=self._mode,
                    equity=self._equity,
                    initial_equity=self._initial,
                    cash=max(
                        0,
                        self._equity
                        - sum(
                            float(p.get("entry_price") or 0) * float(p.get("quantity") or 0)
                            for p in open_positions
                        ),
                    ),
                    realized_pnl=self._realized,
                    unrealized_pnl=unrealized,
                    drawdown_pct=drawdown,
                    cycles=self._cycles,
                    **self._counters,
                    positions_open=len(open_positions),
                    positions_closed=len(self._trades),
                    trades_today=trades_today,
                    wins=self._wins,
                    losses=self._losses,
                    open_positions=tuple(open_positions),
                    recent_trades=tuple(reversed(self._trades)),
                    recent_signals=tuple(reversed(self._signals)),
                    recent_risk_decisions=tuple(reversed(self._risk)),
                    recent_events=tuple(self._events),
                    assets=assets,
                    strategies=tuple(
                        {"strategy": name, **stats}
                        for name, stats in sorted(self._strategy_stats.items())
                    ),
                    equity_curve=tuple(self._curve),
                    errors=tuple(self._errors[-10:]),
                )
        except Exception:
            return DashboardSnapshot(timestamp=self._now_fn())


__all__ = ["DashboardSnapshot", "DashboardStore"]
