"""EDGE-01 simulator — deterministic, conservative, cost-decomposed.

What it does
------------
Walks a merged multi-asset timeline bar by bar. A signal printed at the close of
bar ``i`` is filled at the **open of bar ``i+1``**, never at the close it was
derived from, so the fill is one a real order could have received. Every trade is
sized by the project's own risk policy (``config/risk.yaml``: risk per trade, max
open positions, max total exposure, notional bounds) — the simulator never picks a
size, and a request the policy refuses is recorded as a refusal, not silently
dropped.

Conservative fills
------------------
* a gap through the stop fills at the **open**, not at the stop;
* when a bar's range touches both the stop and the target, the **stop** is
  assumed to have been hit first (no tick data exists to order them);
* a position still open at the last bar is closed at that bar's close and
  labelled ``end_of_data`` so it cannot look like a real exit.

Costs
-----
Fills carry the venue's price costs (spread/slippage/impact, half on each leg)
and fees are charged on both legs, so the per-trade cost reconciles with the
``CostPlane`` the trade was sized against. ``gross``, ``price_costs``, ``fees``
and ``net`` are recorded separately: a reader can always see where the money went
instead of trusting one number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .candidates import CandidateSignal, ContextSeries, Refusal, _Base
from .costs import CostPlane
from .data import OHLCVBar

__all__ = [
    "ASSET",
    "EXIT_REASONS",
    "PortfolioResult",
    "Position",
    "RiskPolicy",
    "run_portfolio",
]


#: Exit reasons a trade can carry. Anything else is a defect, not a category.
EXIT_REASONS: tuple[str, ...] = (
    "stop_loss",
    "target",
    "trailing_stop",
    "invalidation",
    "ema_invalidation",
    "end_of_data",
)

ASSET = "asset"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """The project's configured limits, read from ``config/risk.yaml``.

    Every number here is a field of the runtime's own risk config: the simulator
    does not get to choose a size, a cap or a cooldown, and a limit that blocks an
    entry is recorded as a refusal so the block is visible in the results.
    """

    risk_per_trade_pct: float
    max_open_positions: int
    max_total_exposure_pct: float
    max_asset_exposure_pct: float
    min_notional_usdt: float
    max_notional_usdt: float
    drawdown_halt_pct: float
    max_consecutive_losses: int
    consecutive_loss_cooldown_minutes: float
    max_trades_per_day: int
    start_equity: float = 10_000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_open_positions": self.max_open_positions,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "max_asset_exposure_pct": self.max_asset_exposure_pct,
            "min_notional_usdt": self.min_notional_usdt,
            "max_notional_usdt": self.max_notional_usdt,
            "drawdown_halt_pct": self.drawdown_halt_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "consecutive_loss_cooldown_minutes": self.consecutive_loss_cooldown_minutes,
            "max_trades_per_day": self.max_trades_per_day,
            "start_equity": self.start_equity,
        }


@dataclass(slots=True)
class Position:
    asset: str
    candidate: str
    signal_bar: int
    decision_ts: int
    entry_bar: int
    entry_ts: int
    entry_mid: float
    entry_fill: float
    qty: float
    notional: float
    initial_stop: float
    stop: float
    stop_distance: float
    targets: tuple[float, ...]
    hard_invalidation: float | None
    trailing_atr: float | None
    trailing_atr_value: float | None
    exit_ema_period: int | None
    regime: str
    expected_gross_bps: float
    expected_cost_bps: float
    planned_risk_usdt: float
    price_cost_half_bps: float
    fee_bps: float
    mae: float = 0.0
    mfe: float = 0.0
    scaled_out: bool = False


@dataclass(slots=True)
class PortfolioResult:
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    refusals: list[dict[str, Any]] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    bars_seen: int = 0
    per_asset_bars: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trades": len(self.trades),
            "refusals": len(self.refusals),
            "signals": len(self.signals),
            "bars_seen": self.bars_seen,
            "per_asset_bars": dict(self.per_asset_bars),
        }


def _merge_timeline(bars_by_asset: dict[str, list[OHLCVBar]]) -> list[int]:
    stamps: set[int] = set()
    for bars in bars_by_asset.values():
        stamps.update(b.ts for b in bars)
    return sorted(stamps)


def _index(bars: list[OHLCVBar]) -> dict[int, int]:
    return {b.ts: i for i, b in enumerate(bars)}


@dataclass(slots=True)
class _Gate:
    """Rolling state the configured limits are enforced against."""

    peak_equity: float
    day_key: int = -1
    trades_today: int = 0
    consecutive_losses: int = 0
    cooldown_until_ts: int = 0


def run_portfolio(
    *,
    candidate: _Base,
    bars_by_asset: dict[str, list[OHLCVBar]],
    plane: CostPlane,
    policy: RiskPolicy,
    context: ContextSeries | None = None,
    exit_ema: dict[str, list[float | None]] | None = None,
    window_start_ts: int | None = None,
    window_end_ts: int | None = None,
) -> PortfolioResult:
    """Simulate one candidate across assets on a shared clock.

    ``context`` is the higher timeframe a candidate needs (the 1h series for the
    intraday candidates); it is passed in rather than fetched, so the same object
    the tests pin is the one the simulation read.
    """
    idx_by_asset = {asset: _index(bars) for asset, bars in bars_by_asset.items()}
    timeline = _merge_timeline(bars_by_asset)
    if window_start_ts is not None:
        timeline = [ts for ts in timeline if ts >= window_start_ts]
    if window_end_ts is not None:
        timeline = [ts for ts in timeline if ts <= window_end_ts]

    # Where a position still open at the end of the WINDOW must be settled: the
    # last bar INSIDE the window. Settling at the last bar of the corpus instead
    # would price a 2023 decision with a 2026 close (DEF-EDGE01-08).
    last_in_window: dict[str, int] = {}
    for asset, bars in bars_by_asset.items():
        cursor = len(bars) - 1
        while cursor >= 0 and window_end_ts is not None and bars[cursor].ts > window_end_ts:
            cursor -= 1
        last_in_window[asset] = cursor

    for bars in bars_by_asset.values():
        candidate.prepare(bars)

    cash = policy.start_equity
    positions: dict[str, Position] = {}
    pending: list[CandidateSignal] = []
    result = PortfolioResult()
    marks: dict[str, float] = {}
    gate = _Gate(peak_equity=policy.start_equity)
    last_ts = timeline[-1] if timeline else None

    def _equity() -> float:
        return cash + sum(p.qty * marks.get(a, p.entry_mid) for a, p in positions.items())

    for ts in timeline:
        result.bars_seen += 1
        day = ts // 86_400_000
        if day != gate.day_key:
            gate.day_key = day
            gate.trades_today = 0
        # 0) every asset with a bar at ts refreshes its mark (no future reads)
        for asset in bars_by_asset:
            idx = idx_by_asset[asset].get(ts)
            if idx is not None:
                marks[asset] = bars_by_asset[asset][idx].close
                result.per_asset_bars[asset] = result.per_asset_bars.get(asset, 0) + 1

        # 1) execute the intents printed on the previous bar, at THIS bar's open.
        #    Opening a position PAYS for it (cash -= qty x fill); the trade's net
        #    is then the difference between what was paid and what came back, so
        #    the equity curve cannot double-count an open position
        #    (DEF-EDGE01-02).
        gate.peak_equity = max(gate.peak_equity, _equity())
        for signal in pending:
            cash += _fill(
                signal,
                ts,
                bars_by_asset,
                idx_by_asset,
                positions,
                result,
                policy,
                plane,
                marks,
                gate,
                _equity(),
            )
        pending = []

        # 2) mark, manage and exit open positions on this bar
        for asset in list(positions):
            idx = idx_by_asset.get(asset, {}).get(ts)
            if idx is None:
                continue
            pos = positions[asset]
            bar = bars_by_asset[asset][idx]
            exit_info = _manage(pos, bar, idx, exit_ema, plane)
            if exit_info is not None:
                reason, price = exit_info
                cash_delta, net = _close(pos, reason, price, bar.ts, idx, result, plane)
                cash += cash_delta
                positions.pop(asset, None)
                if net < 0:
                    gate.consecutive_losses += 1
                    if gate.consecutive_losses >= policy.max_consecutive_losses:
                        gate.cooldown_until_ts = bar.ts + int(
                            policy.consecutive_loss_cooldown_minutes * 60_000
                        )
                else:
                    gate.consecutive_losses = 0

        # 3) look for a new signal on this bar's close
        for asset, bars in bars_by_asset.items():
            idx = idx_by_asset[asset].get(ts)
            if idx is None:
                continue
            outcome = candidate.on_bar(bars, idx, context, plane)
            if outcome is None:
                continue
            if isinstance(outcome, Refusal):
                result.refusals.append(
                    {**outcome.to_dict(), "symbol": asset, "source": "candidate"}
                )
                continue
            signal = _bind(outcome, asset)
            result.signals.append(signal.to_dict())
            if asset not in positions:
                pending.append(signal)

        # 3b) at the last instant of the window, settle what is still open so the
        #     curve closes on the same book the trades describe. Settling after the
        #     curve was written would make final_equity and sum(net) disagree
        #     (DEF-EDGE01-08).
        if ts == last_ts:
            for asset, pos in list(positions.items()):
                settle_idx = last_in_window.get(asset, -1)
                if settle_idx < 0:  # pragma: no cover - no bar in the window, no entry
                    positions.pop(asset, None)
                    continue
                final = bars_by_asset[asset][settle_idx]
                cash_delta, _net = _close(
                    pos, "end_of_data", final.close, final.ts, settle_idx, result, plane
                )
                cash += cash_delta
                positions.pop(asset, None)

        # 4) mark the book
        equity = cash
        for asset, pos in positions.items():
            mark = marks.get(asset)
            if mark is not None:
                equity += pos.qty * mark
        result.equity_curve.append((ts, equity))

    if positions:  # pragma: no cover - the last instant always settles
        for asset, pos in list(positions.items()):
            settle_idx = last_in_window.get(asset, -1)
            if settle_idx < 0:
                positions.pop(asset, None)
                continue
            final = bars_by_asset[asset][settle_idx]
            cash_delta, _net = _close(
                pos, "end_of_data", final.close, final.ts, settle_idx, result, plane
            )
            cash += cash_delta
            positions.pop(asset, None)
        if result.equity_curve:
            result.equity_curve[-1] = (result.equity_curve[-1][0], cash)

    return result


def _bind(signal: CandidateSignal, asset: str) -> CandidateSignal:
    data = signal.to_dict()
    data["symbol"] = asset
    return CandidateSignal(
        candidate=signal.candidate,
        symbol=asset,
        bar_index=signal.bar_index,
        decision_ts=signal.decision_ts,
        decision_timeframe=signal.decision_timeframe,
        entry_reference=signal.entry_reference,
        direction=signal.direction,
        stop=signal.stop,
        targets=signal.targets,
        invalidations=signal.invalidations,
        risk_reward=signal.risk_reward,
        expected_gross_bps=signal.expected_gross_bps,
        expected_cost_bps=signal.expected_cost_bps,
        expected_net_bps=signal.expected_net_bps,
        regime=signal.regime,
        evidence=signal.evidence,
        trailing_atr=signal.trailing_atr,
        trailing_atr_value=signal.trailing_atr_value,
        exit_ema_period=signal.exit_ema_period,
        hard_invalidation=signal.hard_invalidation,
    )


def _fill(
    signal: CandidateSignal,
    ts: int,
    bars_by_asset: dict[str, list[OHLCVBar]],
    idx_by_asset: dict[str, dict[int, int]],
    positions: dict[str, Position],
    result: PortfolioResult,
    policy: RiskPolicy,
    plane: CostPlane,
    marks: dict[str, float],
    gate: _Gate,
    equity: float,
) -> float:
    """Fill one intent at the next bar's open, subject to the configured risk policy.

    Returns the cash delta: 0.0 for every refusal, ``-qty * entry_fill`` for a
    fill (the position is paid for), so the caller's book stays consistent.
    """
    asset = signal.symbol
    idx = idx_by_asset[asset].get(ts)
    if idx is None:
        return 0.0
    if asset in positions:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "position_already_open",
                "decision_ts": ts,
                "source": "risk",
            }
        )
        return 0.0
    if len(positions) >= policy.max_open_positions:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "risk_max_open_positions",
                "decision_ts": ts,
                "source": "risk",
            }
        )
        return 0.0
    if gate.trades_today >= policy.max_trades_per_day:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "risk_max_trades_per_day",
                "decision_ts": ts,
                "source": "risk",
            }
        )
        return 0.0
    if gate.cooldown_until_ts and ts < gate.cooldown_until_ts:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "risk_loss_cooldown",
                "decision_ts": ts,
                "source": "risk",
                "detail": {"cooldown_until_ts": gate.cooldown_until_ts},
            }
        )
        return 0.0
    if gate.peak_equity > 0:
        drawdown_pct = (gate.peak_equity - equity) / gate.peak_equity * 100.0
        if drawdown_pct >= policy.drawdown_halt_pct:
            result.refusals.append(
                {
                    "candidate": signal.candidate,
                    "symbol": asset,
                    "reason": "risk_drawdown_halt",
                    "decision_ts": ts,
                    "source": "risk",
                    "detail": {"drawdown_pct": round(drawdown_pct, 4)},
                }
            )
            return 0.0

    bar = bars_by_asset[asset][idx]
    mid = bar.open
    if mid <= 0:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "fill_price_invalid",
                "decision_ts": ts,
                "source": "risk",
            }
        )
        return 0.0
    entry_fill = mid * (1 + plane.spread_bps / 2 / 10_000 + plane.slippage_bps / 2 / 10_000
                        + plane.impact_bps / 2 / 10_000)

    stop_distance = entry_fill - signal.stop
    if stop_distance <= 0:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "stop_above_fill",
                "decision_ts": ts,
                "source": "risk",
            }
        )
        return 0.0

    risk_usdt = equity * policy.risk_per_trade_pct / 100.0
    qty = risk_usdt / stop_distance
    notional = qty * entry_fill
    if notional > policy.max_notional_usdt:
        notional = policy.max_notional_usdt
        qty = notional / entry_fill
    asset_cap = equity * policy.max_asset_exposure_pct / 100.0
    if notional > asset_cap:
        notional = asset_cap
        qty = notional / entry_fill
    exposure_cap = equity * policy.max_total_exposure_pct / 100.0
    open_notional = sum(p.qty * p.entry_fill for p in positions.values())
    if open_notional + notional > exposure_cap:
        allowed = exposure_cap - open_notional
        if allowed < policy.min_notional_usdt:
            result.refusals.append(
                {
                    "candidate": signal.candidate,
                    "symbol": asset,
                    "reason": "risk_exposure_cap",
                    "decision_ts": ts,
                    "source": "risk",
                    "detail": {
                        "open_notional": round(open_notional, 2),
                        "exposure_cap": round(exposure_cap, 2),
                    },
                }
            )
            return 0.0
        notional = allowed
        qty = notional / entry_fill
    if notional < policy.min_notional_usdt:
        result.refusals.append(
            {
                "candidate": signal.candidate,
                "symbol": asset,
                "reason": "risk_notional_below_minimum",
                "decision_ts": ts,
                "source": "risk",
                "detail": {"notional": round(notional, 4)},
            }
        )
        return 0.0

    positions[asset] = Position(
        asset=asset,
        candidate=signal.candidate,
        signal_bar=signal.bar_index,
        decision_ts=signal.decision_ts,
        entry_bar=idx,
        entry_ts=ts,
        entry_mid=mid,
        entry_fill=entry_fill,
        qty=qty,
        notional=notional,
        initial_stop=signal.stop,
        stop=signal.stop,
        stop_distance=stop_distance,
        targets=signal.targets,
        hard_invalidation=signal.hard_invalidation,
        trailing_atr=signal.trailing_atr,
        trailing_atr_value=signal.trailing_atr_value,
        exit_ema_period=signal.exit_ema_period,
        regime=signal.regime,
        expected_gross_bps=signal.expected_gross_bps,
        expected_cost_bps=signal.expected_cost_bps,
        planned_risk_usdt=risk_usdt,
        price_cost_half_bps=(plane.spread_bps + plane.slippage_bps + plane.impact_bps) / 2.0,
        fee_bps=plane.fee_bps,
    )
    gate.trades_today += 1
    return -entry_fill * qty  # the position is paid for out of cash


def _manage(
    pos: Position,
    bar: OHLCVBar,
    idx: int,
    exit_ema: dict[str, list[float | None]] | None,
    plane: CostPlane,
) -> tuple[str, float] | None:
    """Exits in priority order, with the conservative same-bar rule."""
    pos.mfe = max(pos.mfe, bar.high - pos.entry_mid)
    pos.mae = max(pos.mae, pos.entry_mid - bar.low)

    # a gap through the stop fills at the open
    if bar.open <= pos.stop:
        return _stop_label(pos), bar.open
    target = pos.targets[0] if pos.targets else None
    hit_stop = bar.low <= pos.stop
    hit_target = target is not None and bar.high >= target
    if hit_stop:  # the stop is assumed first when both are touched
        return _stop_label(pos), pos.stop
    if hit_target and target is not None and not pos.scaled_out:
        pos.scaled_out = True
        return "target", target

    # the bar has closed: structure/EMA invalidation and the trailing stop move
    if pos.exit_ema_period is not None and exit_ema is not None:
        series = exit_ema.get(pos.asset)
        if series is not None and idx < len(series):
            ema_value = series[idx]
            if ema_value is not None and bar.close < ema_value:
                return "ema_invalidation", bar.close
    if pos.hard_invalidation is not None and bar.close < pos.hard_invalidation:
        return "invalidation", bar.close
    if (
        pos.trailing_atr is not None
        and pos.trailing_atr_value is not None
        and bar.close > pos.entry_mid + pos.stop_distance
    ):
        candidate_stop = bar.close - pos.trailing_atr * pos.trailing_atr_value
        if candidate_stop > pos.stop:
            pos.stop = candidate_stop
    return None


def _stop_label(pos: Position) -> str:
    """A stop that has been trailed is a trailing stop, and is reported as one."""
    if pos.trailing_atr is not None and pos.stop > pos.initial_stop:
        return "trailing_stop"
    return "stop_loss"


def _close(
    pos: Position,
    reason: str,
    price: float,
    ts: int,
    idx: int,
    result: PortfolioResult,
    plane: CostPlane,
) -> tuple[float, float]:
    """Book the trade; return ``(cash_delta, net)``.

    ``cash_delta`` is what the exit puts back in the book (proceeds net of exit
    fees) and ``net`` is the trade's economic result, so that
    ``cash_delta + entry_cash_delta == net`` and the equity curve is a real P&L.
    """
    exit_fill = price * (
        1 - plane.spread_bps / 2 / 10_000 - plane.slippage_bps / 2 / 10_000
        - plane.impact_bps / 2 / 10_000
    )
    gross = (price - pos.entry_mid) * pos.qty
    entry_price_cost = (pos.entry_fill - pos.entry_mid) * pos.qty
    exit_price_cost = (price - exit_fill) * pos.qty
    price_costs = entry_price_cost + exit_price_cost
    fees = pos.notional * pos.fee_bps / 2 / 10_000 + exit_fill * pos.qty * pos.fee_bps / 2 / 10_000
    net = (exit_fill - pos.entry_fill) * pos.qty - fees
    duration_min = (ts - pos.entry_ts) / 60_000.0
    result.trades.append(
        {
            "candidate": pos.candidate,
            "asset": pos.asset,
            "side": "LONG",
            "signal_bar": pos.signal_bar,
            "decision_ts": pos.decision_ts,
            "entry_ts": pos.entry_ts,
            "exit_ts": ts,
            "entry_bar": pos.entry_bar,
            "exit_bar": idx,
            "duration_min": round(duration_min, 4),
            "entry_mid": round(pos.entry_mid, 8),
            "entry_fill": round(pos.entry_fill, 8),
            "exit_mid": round(price, 8),
            "exit_fill": round(exit_fill, 8),
            "qty": round(pos.qty, 10),
            "notional": round(pos.notional, 6),
            "stop_initial": round(pos.initial_stop, 8),
            "gross": round(gross, 8),
            "price_costs": round(price_costs, 8),
            "fees": round(fees, 8),
            "net": round(net, 8),
            "cost_bps_realised": round(
                (price_costs + fees) / pos.notional * 10_000.0, 6
            )
            if pos.notional
            else 0.0,
            "exit_reason": reason,
            "regime": pos.regime,
            "expected_gross_bps": round(pos.expected_gross_bps, 6),
            "expected_cost_bps": round(pos.expected_cost_bps, 6),
            "mae": round(pos.mae, 8),
            "mfe": round(pos.mfe, 8),
            "mae_bps": round(pos.mae / pos.entry_mid * 10_000.0, 6),
            "mfe_bps": round(pos.mfe / pos.entry_mid * 10_000.0, 6),
            "planned_risk_usdt": round(pos.planned_risk_usdt, 6),
        }
    )
    return exit_fill * pos.qty - fees, net


def buy_and_hold(
    *,
    bars: list[OHLCVBar],
    plane: CostPlane,
    start_equity: float,
    window_start_ts: int | None = None,
    window_end_ts: int | None = None,
) -> dict[str, Any]:
    """The comparison the RFC demands: same window, same cost plane, no signals."""
    window = [
        b
        for b in bars
        if (window_start_ts is None or b.ts >= window_start_ts)
        and (window_end_ts is None or b.ts <= window_end_ts)
    ]
    if len(window) < 2:
        return {"return_pct": None, "bars": len(window)}
    entry_mid = window[0].open
    exit_mid = window[-1].close
    entry_fill = entry_mid * (1 + plane.round_trip_bps / 2 / 10_000)
    exit_fill = exit_mid * (1 - plane.round_trip_bps / 2 / 10_000)
    ret_pct = (exit_fill / entry_fill - 1.0) * 100.0
    closes = [b.close for b in window]
    peak = closes[0]
    max_dd = 0.0
    for value in closes:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak * 100.0 if peak else 0.0)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]
    return {
        "bars": len(window),
        "first_ts": window[0].ts,
        "last_ts": window[-1].ts,
        "entry_mid": round(entry_mid, 8),
        "exit_mid": round(exit_mid, 8),
        "return_pct": round(ret_pct, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "sharpe_proxy": None,  # filled by the campaign, which knows bars per year
        "equity_final": round(start_equity * (1 + ret_pct / 100.0), 4),
        "_bar_returns": rets,
    }


def _sharpe(returns: list[float], n_bars: int, bars_per_year: float = 0.0) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / len(returns)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    factor = bars_per_year ** 0.5 if bars_per_year else 1.0
    return mean / sd * factor
