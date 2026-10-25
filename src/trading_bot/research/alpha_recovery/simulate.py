"""Deterministic trade simulator for the ARP-002 experiments (research-only).

Contract (frozen before any result was read — §10):

* decisions read only already-closed bars; a setup computed at bar ``i`` is acted
  on at ``close[i]`` (``data_time <= decision_time``);
* **stop-first on intra-bar ambiguity** (if a bar spans both the stop and the
  target the stop is taken), so the simulator can never flatter a strategy;
* one position at a time, no pyramiding, no compounding;
* fixed notional (default 500 USD, matching the ARP-001 BASE ledger) so
  expectancy is directly comparable in basis points of notional;
* cost is a single round-trip figure (``cost_bps_rt``) applied to notional; the
  caller passes the authoritative COST_MODEL_V3 value (never hardcoded here);
* no random numbers, no wall-clock, no LLM arithmetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from trading_bot.market_data.types import OHLCV

__all__ = [
    "Position",
    "Setup",
    "SimulationResult",
    "Strategy",
    "Trade",
    "simulate",
]

BPS = 10000.0
MS_PER_MIN = 60_000


@dataclass(frozen=True, slots=True)
class Setup:
    """An entry candidate produced on a closed bar."""

    side: str  # "long" | "short"
    stop: float
    target: float | None
    rule: str
    max_hold_bars: int | None = None
    exit_on_session_end: bool = False


@dataclass(slots=True)
class Position:
    """An open position tracked by the simulator."""

    side: str
    entry: float
    stop: float
    target: float | None
    entry_index: int
    entry_ts: int
    rule: str
    mfe: float = 0.0
    mae: float = 0.0
    max_hold_bars: int | None = None
    exit_on_session_end: bool = False


@dataclass(frozen=True, slots=True)
class Trade:
    """One completed round-trip, in the BASE-ledger shape."""

    side: str
    entry_ts: int
    exit_ts: int
    duration_min: float
    entry: float
    exit: float
    reason: str
    mfe_pct: float
    mae_pct: float
    notional: float
    gross: float
    fees: float
    net: float
    rule: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "duration_min": self.duration_min,
            "entry": self.entry,
            "exit": self.exit,
            "reason": self.reason,
            "mfe_pct": self.mfe_pct,
            "mae_pct": self.mae_pct,
            "notional": self.notional,
            "gross": self.gross,
            "fees": self.fees,
            "net": self.net,
            "rule": self.rule,
        }


class Strategy(Protocol):
    """Single-asset deterministic strategy protocol."""

    warmup: int

    def prepare(self, bars: Sequence[OHLCV]) -> None: ...

    def entry(self, i: int) -> Setup | None: ...

    def exit_reason(self, i: int, pos: Position) -> str | None: ...


@dataclass(slots=True)
class SimulationResult:
    trades: list[Trade] = field(default_factory=list)
    eval_bars: int = 0


def _day_key(ts_ms: int) -> int:
    return ts_ms // 86_400_000


def _sign(side: str) -> float:
    return 1.0 if side == "long" else -1.0


def simulate(
    strategy: Strategy,
    bars: Sequence[OHLCV],
    *,
    cost_bps_rt: float,
    notional: float = 500.0,
    asset: str = "X",
    entry_delay_bars: int = 0,
) -> SimulationResult:
    """Run one strategy over one asset's closed bars.

    ``entry_delay_bars`` > 0 models execution latency (§16): a setup found at bar
    ``i`` is only filled at ``close[i + delay]`` while keeping its own stop/target
    levels. It can only make a strategy worse, never better.
    """
    del asset  # carried by the caller for reporting; not needed for the arithmetic
    strategy.prepare(bars)
    n = len(bars)
    trades: list[Trade] = []
    pos: Position | None = None
    pending: Setup | None = None
    pending_due = -1
    fee_usd = notional * cost_bps_rt / BPS
    eval_bars = 0

    def close_position(price: float, ts: int, reason: str, p: Position) -> None:
        gross = notional * (price / p.entry - 1.0) * _sign(p.side)
        net = gross - fee_usd
        trades.append(
            Trade(
                side=p.side,
                entry_ts=p.entry_ts,
                exit_ts=ts,
                duration_min=round((ts - p.entry_ts) / MS_PER_MIN, 1),
                entry=round(p.entry, 6),
                exit=round(price, 6),
                reason=reason,
                mfe_pct=round(p.mfe / p.entry * 100.0, 4),
                mae_pct=round(p.mae / p.entry * 100.0, 4),
                notional=round(notional, 2),
                gross=round(gross, 4),
                fees=round(fee_usd, 4),
                net=round(net, 4),
                rule=p.rule,
            )
        )

    start = max(strategy.warmup, 1)
    for i in range(start, n):
        bar = bars[i]
        eval_bars += 1
        ts, high, low, close = bar.timestamp, bar.high, bar.low, bar.close

        if pos is not None:
            # intrabar extremes -------------------------------------------------
            if pos.side == "long":
                pos.mfe = max(pos.mfe, high - pos.entry)
                pos.mae = max(pos.mae, pos.entry - low)
                stop_hit = low <= pos.stop
                target_hit = pos.target is not None and high >= pos.target
            else:
                pos.mfe = max(pos.mfe, pos.entry - low)
                pos.mae = max(pos.mae, high - pos.entry)
                stop_hit = high >= pos.stop
                target_hit = pos.target is not None and low <= pos.target
            if stop_hit:  # stop-first on ambiguity
                close_position(pos.stop, ts, "stop", pos)
                pos = None
            elif target_hit and pos.target is not None:
                close_position(pos.target, ts, "target", pos)
                pos = None
            else:
                reason: str | None = None
                if pos.max_hold_bars is not None and (i - pos.entry_index) >= pos.max_hold_bars:
                    reason = "window_expiry"
                elif (
                    pos.exit_on_session_end
                    and i + 1 < n
                    and _day_key(bars[i + 1].timestamp) != _day_key(ts)
                ):
                    reason = "session_end"
                else:
                    reason = strategy.exit_reason(i, pos)
                if reason is not None:
                    close_position(close, ts, reason, pos)
                    pos = None

        if pos is None and pending is not None and i >= pending_due:
            setup_p = pending
            pending = None
            pos = Position(
                side=setup_p.side,
                entry=close,
                stop=setup_p.stop,
                target=setup_p.target,
                entry_index=i,
                entry_ts=ts,
                rule=setup_p.rule,
                max_hold_bars=setup_p.max_hold_bars,
                exit_on_session_end=setup_p.exit_on_session_end,
            )

        if pos is None and pending is None and i < n - 1:
            setup = strategy.entry(i)
            if setup is not None and entry_delay_bars == 0:
                pos = Position(
                    side=setup.side,
                    entry=close,
                    stop=setup.stop,
                    target=setup.target,
                    entry_index=i,
                    entry_ts=ts,
                    rule=setup.rule,
                    max_hold_bars=setup.max_hold_bars,
                    exit_on_session_end=setup.exit_on_session_end,
                )
            elif setup is not None and i + entry_delay_bars <= n - 1:
                pending = setup
                pending_due = i + entry_delay_bars

    return SimulationResult(trades=trades, eval_bars=eval_bars)
