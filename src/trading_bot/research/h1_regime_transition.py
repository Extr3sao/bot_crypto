"""H1-REGIME-TRANSITION-DISCOVERY-01 — core evaluation (frozen prereg).

Implements EXACTLY the preregistered spec
``docs/external-audit-01/h1-regime-transition-01/H1_SPEC.json``
(sha256 8baaff7d…, commit 3ad054d — the spec is the single authority).

This module is PURE research evaluation over public OHLCV:

- no RiskManager / PaperBroker / campaign mutation,
- no parameter tuning, no fallback thresholds,
- PIT-safe by construction: every decision at bar ``t`` consumes only
  bars with close_time <= decision time (entry uses the NEXT bar's open,
  which is the fill instant of the decision),
- one economic experiment; this file never fetches, never writes results
  (the runner script owns fetch + exactly-once marker + artifacts).

Frozen mechanics (do not modify without a NEW preregistration):

- regime state: canonical ``derive_market_regime_state`` over a trailing
  200-bar 1h window ending at the decision bar,
- qualifying transition: six-dim state key change AND (vol NORMAL/LOW →
  HIGH/EXTREME OR stress NORMAL → CORRECTION/SHOCK OR structure
  TREND/RANGE → TRANSITION),
- direction: CORRECTION/SHOCK → SHORT; BULL+BREAKOUT → LONG; else NO_TRADE,
- entry at open[t+1]; SL = entry -/+ ATR(14) (simple mean TR, bars t-13..t);
  time exit at close[t+12]; stop assumed first when both land in one bar,
- cost: 10 bps round trip charged in R via risk fraction ATR/entry.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Literal

from trading_bot.market_data.types import OHLCV
from trading_bot.research.regime_v2 import (
    MarketRegimeState,
    StressLevel,
    TrendDirection,
    VolatilityLevel,
    derive_market_regime_state,
    regime_transition_label,
)

# ---- frozen spec constants (mirrors of H1_SPEC.json; keep in sync) ----
STATE_WINDOW_BARS = 200
ATR_PERIOD = 14
HOLD_BARS = 12
COST_RT_BPS = 10.0
SLIPPAGE_SENSITIVITY_BPS: tuple[float, float] = (5.0, 20.0)
MIN_TOTAL_TRADES = 30
MIN_PRIMARY_CELL = 15
BOOTSTRAP_N = 2000
PERMUTATION_N = 1000
SEED = 20260910
PF_NET_MIN = 1.15
P_SHARPE_MIN = 0.90
PERM_P_MAX = 0.05
PROXY_ROC_PERIOD = 24
PROXY_ROC_THRESHOLD = 0.02
PROXY_OVERLAP_BARS = 3
REDUNDANT_OVERLAP = 0.6
REDUNDANT_CORR = 0.7

Direction = Literal["LONG", "SHORT"]
ResultClass = Literal[
    "DISCOVERY_PASS",
    "DISCOVERY_FAIL",
    "INSUFFICIENT_SAMPLE",
    "INSUFFICIENT_DATA",
    "REDUNDANT_CANDIDATE",
]

_SHIFT_SECONDS = 3_600_000  # 1h bar span in ms


def close_time(bar: OHLCV) -> int:
    """Close instant of a 1h bar (Binance openTime + span - 1ms)."""
    return bar.timestamp + _SHIFT_SECONDS - 1


def atr14(bars: tuple[OHLCV, ...]) -> float:
    """Simple mean true range over the trailing ``ATR_PERIOD`` bars.

    ``bars`` must be exactly the trailing completed bars ending at the
    decision bar (caller guarantees the PIT slice).
    """
    if len(bars) < 2:
        raise ValueError("atr14 requires at least 2 bars")
    from itertools import pairwise

    trs: list[float] = []
    for prev, cur in pairwise(bars):
        trs.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return sum(trs) / len(trs)


def _qualifies(prev: MarketRegimeState, curr: MarketRegimeState) -> bool:
    """Frozen qualifying-transition identity (A2)."""
    if prev.key() == curr.key():
        return False
    vol_up = prev.volatility in (VolatilityLevel.NORMAL, VolatilityLevel.LOW) and curr.volatility in (
        VolatilityLevel.HIGH,
        VolatilityLevel.EXTREME,
    )
    stress_up = prev.stress is StressLevel.NORMAL and curr.stress in (StressLevel.CORRECTION, StressLevel.SHOCK)
    to_transition = prev.market_structure.value in ("TREND", "RANGE") and curr.market_structure.value == "TRANSITION"
    return vol_up or stress_up or to_transition


def direction_for(state: MarketRegimeState) -> Direction | None:
    """Frozen deterministic direction rule. None => NO_TRADE."""
    if state.stress in (StressLevel.CORRECTION, StressLevel.SHOCK):
        return "SHORT"
    if state.trend_direction is TrendDirection.BULL and state.market_structure.value == "BREAKOUT":
        return "LONG"
    return None


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    """A qualifying regime transition detected at bar ``index``."""

    asset: str
    index: int  # bar index of the NEW-state bar t
    decision_time: int  # close_time of bar t
    from_key: str
    to_key: str
    label: str  # regime_transition_label(prev, curr)
    direction: Direction | None  # None => NO_TRADE opportunity
    tradeable: bool


@dataclass(frozen=True, slots=True)
class Trade:
    """One simulated trade (H1 or legacy proxy) in R multiples."""

    asset: str
    direction: Direction
    entry_index: int
    entry_ts: int
    exit_index: int
    exit_ts: int
    entry_price: float
    stop_price: float
    exit_price: float
    risk_frac: float  # ATR / entry
    gross_r: float
    net_r: float
    transition_label: str = ""
    kind: str = "H1"  # "H1" | "PROXY"


@dataclass(slots=True)
class Evaluation:
    """Per-asset intermediate results (pooled by the runner)."""

    asset: str
    n_bars: int
    transitions: list[TransitionEvent] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    proxy_trades: list[Trade] = field(default_factory=list)
    no_trade_opportunities: int = 0
    skipped_incomplete: int = 0  # transitions near data end (< HOLD_BARS left)
    skipped_open_position: int = 0  # cooldown: one position per asset


# ---------------------------------------------------------------------------
# Regime states + transitions
# ---------------------------------------------------------------------------


def derive_states(candles: tuple[OHLCV, ...], asset: str) -> list[MarketRegimeState]:
    """Canonical state for every bar t >= STATE_WINDOW_BARS (PIT windows)."""
    states: list[MarketRegimeState] = []
    for t in range(STATE_WINDOW_BARS, len(candles)):
        window = candles[t - STATE_WINDOW_BARS + 1 : t + 1]
        states.append(derive_market_regime_state(window))
    assert states[0].bar_ts == candles[STATE_WINDOW_BARS].timestamp, f"{asset}: state alignment"
    return states


def detect_transitions(
    candles: tuple[OHLCV, ...], states: list[MarketRegimeState], asset: str
) -> list[TransitionEvent]:
    """Qualifying transitions; direction comes ONLY from the new state."""
    events: list[TransitionEvent] = []
    for i in range(1, len(states)):
        prev, curr = states[i - 1], states[i]
        if not _qualifies(prev, curr):
            continue
        t = i + STATE_WINDOW_BARS  # absolute bar index of curr
        events.append(
            TransitionEvent(
                asset=asset,
                index=t,
                decision_time=close_time(candles[t]),
                from_key=prev.key(),
                to_key=curr.key(),
                label=regime_transition_label(prev, curr),
                direction=direction_for(curr),
                tradeable=direction_for(curr) is not None,
            )
        )
    return events


# ---------------------------------------------------------------------------
# Trade simulation (frozen entry/exit/cost)
# ---------------------------------------------------------------------------


def _simulate(
    candles: tuple[OHLCV, ...],
    asset: str,
    direction: Direction,
    entry_index: int,
    atr: float,
    kind: str,
    transition_label: str = "",
) -> Trade | None:
    """Simulate one trade from entry at open[entry_index]; None if incomplete."""
    last_index = len(candles) - 1
    exit_index = entry_index + HOLD_BARS - 1  # close of bar t+12 (t = entry-1)
    if exit_index > last_index:
        return None  # mechanical completeness: cannot complete frozen horizon
    entry = candles[entry_index].open
    stop = entry - atr if direction == "LONG" else entry + atr
    exit_price: float | None = None
    exit_at = exit_index
    for j in range(entry_index, exit_index + 1):
        bar = candles[j]
        hit_stop = bar.low <= stop if direction == "LONG" else bar.high >= stop
        if hit_stop:  # pessimistic: stop assumed first in any bar it touches
            exit_price = stop
            exit_at = j
            break
    if exit_price is None:
        exit_price = candles[exit_index].close
        exit_at = exit_index
    move = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
    risk_frac = atr / entry
    gross_r = move / atr
    cost_r = (COST_RT_BPS / 10_000.0) / risk_frac
    return Trade(
        asset=asset,
        direction=direction,
        entry_index=entry_index,
        entry_ts=candles[entry_index].timestamp,
        exit_index=exit_at,
        exit_ts=candles[exit_at].timestamp + _SHIFT_SECONDS - 1,
        entry_price=entry,
        stop_price=stop,
        exit_price=exit_price,
        risk_frac=risk_frac,
        gross_r=gross_r,
        net_r=gross_r - cost_r,
        transition_label=transition_label,
        kind=kind,
    )


def simulate_h1(
    candles: tuple[OHLCV, ...], events: list[TransitionEvent], asset: str
) -> tuple[list[Trade], int, int]:
    """Frozen H1 simulation: entry t+1, cooldown, incomplete-skip accounting."""
    trades: list[Trade] = []
    no_trade_opps = 0
    skipped_incomplete = 0
    skipped_open = 0
    busy_until = -1  # last holding bar index per asset (cooldown)
    for ev in events:
        if ev.direction is None:
            no_trade_opps += 1
            continue
        entry_index = ev.index + 1
        if entry_index > len(candles) - 1:
            skipped_incomplete += 1
            continue
        if ev.index <= busy_until:
            skipped_open += 1
            continue
        atr = atr14(candles[ev.index - ATR_PERIOD + 1 : ev.index + 1])
        trade = _simulate(
            candles, asset, ev.direction, entry_index, atr, "H1", ev.label
        )
        if trade is None:
            skipped_incomplete += 1
            continue
        trades.append(trade)
        busy_until = trade.exit_index
    return trades, skipped_incomplete, skipped_open


def legacy_proxy_signal(candles: tuple[OHLCV, ...], t: int) -> Direction | None:
    """Frozen proxy: ROC(24) breakout momentum, ±2% (same mechanics as H1)."""
    if t < PROXY_ROC_PERIOD:
        return None
    roc = candles[t].close / candles[t - PROXY_ROC_PERIOD].close - 1.0
    if roc > PROXY_ROC_THRESHOLD:
        return "LONG"
    if roc < -PROXY_ROC_THRESHOLD:
        return "SHORT"
    return None


def simulate_proxy(candles: tuple[OHLCV, ...], asset: str) -> list[Trade]:
    """Legacy proxy trades: identical entry/exit/cost mechanics as H1."""
    trades: list[Trade] = []
    busy_until = -1
    pending: tuple[int, Direction] | None = None  # (entry_index, direction)
    for t in range(STATE_WINDOW_BARS, len(candles) - 1):
        if pending is not None:
            entry_index, direction = pending
            pending = None
            if entry_index <= busy_until:
                continue
            atr = atr14(candles[entry_index - ATR_PERIOD : entry_index])
            trade = _simulate(candles, asset, direction, entry_index, atr, "PROXY")
            if trade is None:
                continue
            trades.append(trade)
            busy_until = trade.exit_index
            continue
        signal = legacy_proxy_signal(candles, t)
        if signal is not None and (t + 1) > busy_until:
            pending = (t + 1, signal)
    return trades


# ---------------------------------------------------------------------------
# Metrics + robustness (frozen formulas)
# ---------------------------------------------------------------------------


def sharpe(rs: list[float]) -> float:
    if len(rs) < 2:
        return 0.0
    sd = statistics.stdev(rs)
    if sd == 0:
        return 0.0
    return statistics.mean(rs) / sd


def bootstrap_sharpe(rs: list[float]) -> tuple[float, float, float, float]:
    """(sharpe, ci_low, ci_high, P(Sharpe>0)) with the frozen seed/N."""
    if len(rs) < 2:
        return 0.0, 0.0, 0.0, 0.0
    sd = statistics.stdev(rs)
    if sd == 0:  # degenerate zero-variance sequence: deterministic outcome
        mean = statistics.mean(rs)
        return 0.0, 0.0, 0.0, (1.0 if mean > 0 else 0.0)
    rng = random.Random(SEED)
    samples: list[float] = []
    for _ in range(BOOTSTRAP_N):
        draw = [rs[rng.randrange(len(rs))] for _ in range(len(rs))]
        samples.append(sharpe(draw))
    samples.sort()
    ci_low = samples[int(0.025 * BOOTSTRAP_N)]
    ci_high = samples[int(0.975 * BOOTSTRAP_N) - 1]
    p_gt0 = sum(1 for s in samples if s > 0) / BOOTSTRAP_N
    return statistics.mean(rs) / sd, ci_low, ci_high, p_gt0


def permutation_p(rs: list[float]) -> float:
    """Sign-flip permutation on the mean of R (frozen seed/N)."""
    if not rs:
        return 1.0
    obs = statistics.mean(rs)
    rng = random.Random(SEED)
    count = 0
    for _ in range(PERMUTATION_N):
        total = 0.0
        for r in rs:
            total += r if rng.random() < 0.5 else -r
        if total / len(rs) >= obs:
            count += 1
    return (count + 1) / (PERMUTATION_N + 1)


def max_drawdown_r(rs: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return abs(dd)


def mc_dd95(rs: list[float]) -> float:
    if not rs:
        return 0.0
    rng = random.Random(SEED)
    dds: list[float] = []
    for _ in range(BOOTSTRAP_N):
        seq = [rs[rng.randrange(len(rs))] for _ in range(len(rs))]
        dds.append(max_drawdown_r(seq))
    dds.sort()
    return dds[int(0.95 * BOOTSTRAP_N) - 1]


def profit_factor(rs: list[float]) -> float:
    wins = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def split_sign(rs: list[float], parts: int) -> list[int]:
    """Sign of mean net R per chronological part (+1/-1/0)."""
    if not rs:
        return [0] * parts
    out: list[int] = []
    size = len(rs) // parts
    for i in range(parts):
        chunk = rs[i * size : (i + 1) * size] if i < parts - 1 else rs[(parts - 1) * size :]
        m = statistics.mean(chunk) if chunk else 0.0
        out.append(1 if m > 0 else -1 if m < 0 else 0)
    return out


def compute_trade_metrics(trades: list[Trade], cost_bps: float = COST_RT_BPS) -> dict[str, object]:
    """B1 metrics over a trade list (net R recomputable at sensitivity bps).

    DEF-RESEARCH-COST-001 repair: the applied cost is ALWAYS the absolute
    ``cost_bps`` round trip — never a delta vs the 10 bps baseline applied
    to gross. Absolute semantics preserve the mathematical invariants
    NET = GROSS - COST and monotone non-increasing net in cost for a fixed
    trade set. The precomputed ``t.net_r`` equals the absolute formula at
    the default 10 bps, so the default path is numerically unchanged.
    """
    if cost_bps == COST_RT_BPS:
        net = [t.net_r for t in trades]
        gross = [t.gross_r for t in trades]
    else:
        net = [t.gross_r - (cost_bps / 10_000.0) / t.risk_frac for t in trades]
        gross = [t.gross_r for t in trades]
    if not net:
        return {"N": 0}
    s, lo, hi, p_gt0 = bootstrap_sharpe(net)
    return {
        "N": len(net),
        "gross_expectancy_R": statistics.mean(gross),
        "net_expectancy_R": statistics.mean(net),
        "PF_gross": profit_factor(gross),
        "PF_net": profit_factor(net),
        "Sharpe": s,
        "Sharpe_CI95": [lo, hi],
        "P_Sharpe_gt_0": p_gt0,
        "permutation_p": permutation_p(net),
        "win_rate": sum(1 for r in net if r > 0) / len(net),
        "max_drawdown_R": max_drawdown_r(net),
        "MC_DD95_R": mc_dd95(net),
        "cost_drag_R": statistics.mean(gross) - statistics.mean(net),
        "halves": split_sign(net, 2),
        "thirds": split_sign(net, 3),
        "walk_forward_last_third_net_R": (
            statistics.mean(net[2 * (len(net) // 3):]) if len(net) >= 3 else 0.0
        ),
    }


def classify(metrics: dict[str, object]) -> ResultClass:
    """Frozen acceptance thresholds (B4). Pure function of metrics."""
    n = int(metrics.get("N", 0))  # type: ignore[arg-type]
    if n < MIN_TOTAL_TRADES:
        return "INSUFFICIENT_SAMPLE"
    halves = metrics["halves"]
    thirds = metrics["thirds"]
    assert isinstance(halves, list) and isinstance(thirds, list)
    pass_all = (
        float(metrics["net_expectancy_R"]) > 0.0  # type: ignore[arg-type]
        and float(metrics["PF_net"]) > PF_NET_MIN  # type: ignore[arg-type]
        and float(metrics["P_Sharpe_gt_0"]) >= P_SHARPE_MIN  # type: ignore[arg-type]
        and float(metrics["permutation_p"]) <= PERM_P_MAX  # type: ignore[arg-type]
        and all(s == halves[0] for s in halves)
        and all(s == thirds[0] for s in thirds)
        and float(metrics["walk_forward_last_third_net_R"]) > 0.0  # type: ignore[arg-type]
    )
    return "DISCOVERY_PASS" if pass_all else "DISCOVERY_FAIL"


# ---------------------------------------------------------------------------
# Orthogonality (B2) + frequency (B3)
# ---------------------------------------------------------------------------


def orthogonality(h1_trades: list[Trade], proxy_trades: list[Trade]) -> dict[str, object]:
    """Frozen B2 comparison vs the legacy ROC proxy."""
    if not h1_trades:
        return {"overlap_trade_time": 0.0, "redundant": False, "note": "no H1 trades"}
    proxy_entries = [t.entry_index for t in proxy_trades]
    close = 0
    for h in h1_trades:
        if any(abs(h.entry_index - p) <= PROXY_OVERLAP_BARS for p in proxy_entries):
            close += 1
    overlap_trade_time = close / len(h1_trades)

    # daily aggregated net R where both traded
    def daily(trades: list[Trade]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in trades:
            day = t.exit_ts // 86_400_000
            out[day] = out.get(day, 0.0) + t.net_r
        return out

    d1, d2 = daily(h1_trades), daily(proxy_trades)
    common = sorted(set(d1) & set(d2))
    corr: float | None = None
    if len(common) >= 30:
        xs = [d1[d] for d in common]
        ys = [d2[d] for d in common]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=False))
        sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
        sy = math.sqrt(sum((b - my) ** 2 for b in ys))
        corr = cov / (sx * sy) if sx > 0 and sy > 0 else 0.0
    redundant = overlap_trade_time > REDUNDANT_OVERLAP and corr is not None and corr > REDUNDANT_CORR
    return {
        "overlap_trade_time": overlap_trade_time,
        "pnl_correlation_daily": corr,
        "common_days": len(common),
        "redundant": redundant,
    }


def frequency_value(
    events: list[TransitionEvent],
    h1_trades: list[Trade],
    proxy_trades: list[Trade],
    total_days: float,
) -> dict[str, float]:
    """Frozen B3 frequency metrics (report-only; never tuned)."""
    if total_days <= 0:
        return {}
    raw = len(events) / total_days
    qualifying = sum(1 for e in events if e.tradeable) / total_days
    proxy_entries = [t.entry_index for t in proxy_trades]
    incremental = sum(
        1
        for e in events
        if e.tradeable and not any(abs(e.index - p) <= PROXY_OVERLAP_BARS for p in proxy_entries)
    ) / total_days
    return {
        "raw_opportunities_per_day": raw,
        "qualifying_opportunities_per_day": qualifying,
        "incremental_opportunities_per_day": incremental,
    }
