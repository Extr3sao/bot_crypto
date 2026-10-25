"""SMALL_CAPITAL_V1 (RFC-039) — 200-USDT product-fit research core.

This module is the frozen implementation of candidate ``SC-TREND-001``
(multi-asset absolute momentum / tactical trend, long-or-cash) plus the
fractional small-capital accounting used to evaluate whether it is executable
with a reference capital of **200 USDT**.

It is deliberately self-contained: it does *not* import the managed-futures
engine (RFC-036) nor the runtime execution path. It is research-only and never
places an order.

Design rules frozen before any result was observed (§41-§46, §64-§66):

* universe  = 6 liquid, divisible US-listed ETF sleeves (one per asset class);
* signal    = close > SMA(200 trading days) ~= Faber's 10-month SMA (CLOSE);
* weights   = fixed 1/N sleeve weights, an OFF sleeve sits in cash (Faber TAA);
* rebalance = monthly, decision at month-end close, execution at the NEXT
  trading day's close (T+1; no same-close ambiguity);
* cash      = 0% return (base case, §63);
* cost      = 10 bps per side on traded notional, stressed 1.5x/2.0x;
* accounts  = fractional by notional (quantity rounded to 1e-4), minimum
  position notional 1 USD, gross exposure capped at 1.0 (no leverage).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "COST_BPS_PER_SIDE",
    "DEFAULT_UNIVERSE",
    "MIN_POSITION_NOTIONAL_USD",
    "QTY_STEP",
    "REFERENCE_CAPITAL",
    "SMA_WINDOW",
    "Dataset",
    "PriceSeries",
    "SimResult",
    "build_dataset",
    "max_drawdown",
    "month_end_indices",
    "monthly_returns",
    "precompute_sma",
    "sharpe_from_monthly",
    "simulate_absolute_momentum",
    "simulate_fixed_weights",
    "sma",
    "target_sleeve_weights",
]

# ---------------------------------------------------------------------------
# Frozen configuration (§41, §43, §46)
# ---------------------------------------------------------------------------

REFERENCE_CAPITAL: float = 200.0  # product-design capital (not live capital)
SCALING_CAPITALS: tuple[float, ...] = (200.0, 500.0, 1_000.0, 5_000.0, 10_000.0)

DEFAULT_UNIVERSE: tuple[str, ...] = ("SPY", "EFA", "IEF", "VNQ", "GLD", "DBC")

SMA_WINDOW: int = 200  # ~10 months of trading days (Faber)
COST_BPS_PER_SIDE: float = 10.0
QTY_STEP: float = 0.0001  # fractional share precision
MIN_POSITION_NOTIONAL_USD: float = 1.0
MAX_GROSS_EXPOSURE: float = 1.0

_MS_PER_DAY: int = 86_400_000


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriceSeries:
    """One symbol's ascending daily adjusted-close series."""

    symbol: str
    dates_ms: tuple[int, ...]
    closes: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.dates_ms) != len(self.closes):
            raise ValueError(f"{self.symbol}: dates/closes length mismatch")
        for a, b in zip(self.dates_ms, self.dates_ms[1:], strict=False):
            if b <= a:
                raise ValueError(f"{self.symbol}: dates must be strictly ascending")
        for c in self.closes:
            if c <= 0.0:
                raise ValueError(f"{self.symbol}: non-positive adjusted close")


@dataclass(frozen=True, slots=True)
class Dataset:
    """Symbols aligned on a common ascending trading-date axis.

    ``closes[s][i]`` is ``None`` when symbol ``s`` had no observation on the
    union date ``dates_ms[i]`` (e.g. before inception).
    """

    symbols: tuple[str, ...]
    dates_ms: tuple[int, ...]
    closes: dict[str, tuple[float | None, ...]]

    def index_of(self, ts_ms: int) -> int:
        lo, hi = 0, len(self.dates_ms) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.dates_ms[mid] == ts_ms:
                return mid
            if self.dates_ms[mid] < ts_ms:
                lo = mid + 1
            else:
                hi = mid - 1
        raise KeyError(f"date {ts_ms} not in dataset axis")

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "n_dates": len(self.dates_ms),
            "first_date_ms": self.dates_ms[0],
            "last_date_ms": self.dates_ms[-1],
        }


def build_dataset(series: list[PriceSeries]) -> Dataset:
    """Align several price series on the union of their trading dates."""
    if not series:
        raise ValueError("at least one price series is required")
    symbols = tuple(s.symbol for s in series)
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate symbols in dataset")
    axis = sorted({ts for s in series for ts in s.dates_ms})
    aligned: dict[str, tuple[float | None, ...]] = {}
    for s in series:
        lookup = dict(zip(s.dates_ms, s.closes, strict=True))
        aligned[s.symbol] = tuple(lookup.get(ts) for ts in axis)
    return Dataset(symbols=symbols, dates_ms=tuple(axis), closes=aligned)


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------


def sma(values: list[float | None] | tuple[float | None, ...], window: int) -> list[float | None]:
    """Simple moving average; ``None`` until a full window of real points exists.

    A missing observation breaks the window (we never fill prints): the output
    stays ``None`` until ``window`` consecutive real points are available.
    """
    if window <= 0:
        raise ValueError("window must be > 0")
    out: list[float | None] = [None] * len(values)
    recent: deque[tuple[int, float]] = deque()
    running = 0.0
    for i, v in enumerate(values):
        if v is not None:
            recent.append((i, v))
            running += v
        while recent and recent[0][0] <= i - window:
            _, old = recent.popleft()
            running -= old
        if len(recent) == window:
            out[i] = running / float(window)
    return out


def precompute_sma(
    dataset: Dataset, window: int = SMA_WINDOW
) -> dict[str, list[float | None]]:
    """Compute the SMA of every symbol once (O(N) per symbol)."""
    return {sym: sma(dataset.closes[sym], window) for sym in dataset.symbols}


def month_end_indices(dates_ms: tuple[int, ...]) -> list[int]:
    """Indices of the last trading day of each calendar month."""
    if not dates_ms:
        return []
    out: list[int] = []
    for i in range(len(dates_ms)):
        if i == len(dates_ms) - 1:
            out.append(i)
            continue
        if _utc_year_month(dates_ms[i]) != _utc_year_month(dates_ms[i + 1]):
            out.append(i)
    return out


def _utc_year_month(ts_ms: int) -> tuple[int, int]:
    days = ts_ms // _MS_PER_DAY
    year = 1970
    while True:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        ylen = 366 if leap else 365
        if days >= ylen:
            days -= ylen
            year += 1
            continue
        break
    month_lengths = (31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    month = 1
    for mlen in month_lengths:
        if days < mlen:
            break
        days -= mlen
        month += 1
    return year, month


def target_sleeve_weights(
    dataset: Dataset,
    idx: int,
    *,
    smas: dict[str, list[float | None]] | None = None,
    n_sleeves: int | None = None,
) -> dict[str, float]:
    """Faber-TAA weights at decision index ``idx``.

    Each of the ``N`` sleeves carries a fixed ``1/N`` weight when its asset
    trades above its moving average; an OFF sleeve holds cash instead.
    """
    n = n_sleeves if n_sleeves is not None else len(dataset.symbols)
    if n <= 0:
        raise ValueError("n_sleeves must be > 0")
    tables = smas if smas is not None else precompute_sma(dataset)
    sleeve = 1.0 / float(n)
    weights: dict[str, float] = {}
    for sym in dataset.symbols:
        arr = tables[sym]
        if idx >= len(arr):
            weights[sym] = 0.0
            continue
        latest = dataset.closes[sym][idx]
        ma = arr[idx]
        weights[sym] = sleeve if (latest is not None and ma is not None and latest > ma) else 0.0
    gross = sum(weights.values())
    if gross > MAX_GROSS_EXPOSURE + 1e-9:
        raise ValueError(f"gross exposure {gross} exceeds MAX_GROSS_EXPOSURE")
    return weights


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SimResult:
    """Frozen output of one 200-USDT portfolio simulation run."""

    capital: float
    dates_ms: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    monthly_equity: list[float] = field(default_factory=list)
    monthly_dates_ms: list[int] = field(default_factory=list)
    gross_pnl: float = 0.0
    total_cost: float = 0.0
    traded_notional: float = 0.0
    n_rebalances: int = 0
    n_trades: int = 0
    avg_cash_weight: float = 0.0
    avg_gross_weight: float = 0.0
    weight_error_sum: float = 0.0
    weight_error_max: float = 0.0
    weight_error_n: int = 0
    max_positions_held: int = 0
    mean_positions_held: float = 0.0
    dropped_sleeve_events: int = 0
    max_cash_remainder: float = 0.0

    @property
    def final_equity(self) -> float:
        return self.equity[-1] if self.equity else self.capital

    @property
    def net_pnl(self) -> float:
        return self.final_equity - self.capital

    @property
    def net_return(self) -> float:
        return self.net_pnl / self.capital

    def years(self) -> float:
        if len(self.dates_ms) < 2:
            return 0.0
        return (self.dates_ms[-1] - self.dates_ms[0]) / (365.25 * _MS_PER_DAY)

    def cagr(self) -> float:
        y = self.years()
        if y <= 0.0 or self.capital <= 0.0:
            return 0.0
        ratio = self.final_equity / self.capital
        if ratio <= 0.0:
            return -1.0
        return float(ratio ** (1.0 / y)) - 1.0

    def annual_turnover(self) -> float:
        y = self.years()
        if y <= 0.0 or not self.monthly_equity:
            return 0.0
        avg = sum(self.monthly_equity) / len(self.monthly_equity)
        if avg <= 0.0:
            return 0.0
        return self.traded_notional / (avg * y)

    def mean_weight_error(self) -> float:
        return self.weight_error_sum / self.weight_error_n if self.weight_error_n else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital": self.capital,
            "net_pnl": round(self.net_pnl, 6),
            "net_return": round(self.net_return, 8),
            "gross_pnl": round(self.gross_pnl, 6),
            "total_cost": round(self.total_cost, 6),
            "cagr": round(self.cagr(), 8),
            "max_drawdown": round(max_drawdown(self.equity), 8),
            "annual_turnover": round(self.annual_turnover(), 6),
            "n_rebalances": self.n_rebalances,
            "n_trades": self.n_trades,
            "years": round(self.years(), 4),
            "avg_cash_weight": round(self.avg_cash_weight, 6),
            "avg_gross_weight": round(self.avg_gross_weight, 6),
            "mean_weight_error": round(self.mean_weight_error(), 8),
            "max_weight_error": round(self.weight_error_max, 8),
            "max_positions_held": self.max_positions_held,
            "mean_positions_held": round(self.mean_positions_held, 4),
            "dropped_sleeve_events": self.dropped_sleeve_events,
            "max_cash_remainder": round(self.max_cash_remainder, 6),
        }


def max_drawdown(equity: list[float]) -> float:
    """Maximum peak-to-trough drawdown (negative fraction)."""
    peak = -math.inf
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0.0:
            worst = min(worst, v / peak - 1.0)
    return worst


def _round_qty(qty: float) -> float:
    return math.floor(qty / QTY_STEP + 1e-9) * QTY_STEP if qty > 0 else 0.0


def simulate_absolute_momentum(
    dataset: Dataset,
    *,
    start_ms: int,
    end_ms: int,
    capital: float = REFERENCE_CAPITAL,
    window: int = SMA_WINDOW,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
    min_position_notional: float = MIN_POSITION_NOTIONAL_USD,
) -> SimResult:
    """Simulate SC-TREND-001 on ``[start_ms, end_ms]`` with ``capital`` USD.

    Monthly decision at the last trading day of a month, execution at the next
    trading day's close, fractional notional accounting, gross cap 1.0.
    """
    if capital <= 0.0:
        raise ValueError("capital must be > 0")
    if cost_bps_per_side < 0.0:
        raise ValueError("cost must be >= 0")
    dates = dataset.dates_ms
    # restrict the axis to the requested range
    keep = [i for i, ts in enumerate(dates) if start_ms <= ts <= end_ms]
    if len(keep) < 2:
        raise ValueError("range too short for simulation")
    lo, hi = keep[0], keep[-1]
    axis = dates[lo : hi + 1]

    # month-end rebalance points measured on the full axis, mapped to local
    me_all = month_end_indices(dates)
    me = [i for i in me_all if lo <= i < hi]  # need a next day for execution

    cost_rate = cost_bps_per_side / 10_000.0
    smas = precompute_sma(dataset, window)
    cash = capital
    qty: dict[str, float] = dict.fromkeys(dataset.symbols, 0.0)

    result = SimResult(capital=capital)
    trade_days = sorted({min(i + 1, hi) for i in me})
    trade_day_set = set(trade_days)
    cash_w_sum = 0.0
    gross_w_sum = 0.0
    n_marks = 0

    for gi in range(lo, hi + 1):
        if gi in trade_day_set and me:
            # rebalance using this day's close as the execution price
            px: dict[str, float] = {}
            for sym in dataset.symbols:
                v = dataset.closes[sym][gi]
                if v is not None:
                    px[sym] = v
            equity = cash + sum(qty[s] * px.get(s, 0.0) for s in dataset.symbols)
            # the decision index is the previous month-end before gi
            dec = max((i for i in me if i < gi), default=None)
            if dec is not None and equity > 0.0:
                weights = target_sleeve_weights(dataset, dec, smas=smas)
                target_qty: dict[str, float] = {}
                for sym in dataset.symbols:
                    price = px.get(sym)
                    if price is None or weights.get(sym, 0.0) <= 0.0:
                        target_qty[sym] = 0.0
                        continue
                    ideal_notional = weights[sym] * equity
                    q = _round_qty(ideal_notional / price)
                    if q * price < min_position_notional:
                        q = 0.0
                    target_qty[sym] = q
                traded = sum(
                    abs(target_qty[s] - qty[s]) * px.get(s, 0.0) for s in dataset.symbols
                )
                cost = traded * cost_rate
                invested = sum(target_qty[s] * px.get(s, 0.0) for s in dataset.symbols)
                if invested + cost > equity:
                    scale = (equity - cost) / invested if invested > 0.0 else 0.0
                    target_qty = {s: _round_qty(target_qty[s] * scale) for s in dataset.symbols}
                    traded = sum(
                        abs(target_qty[s] - qty[s]) * px.get(s, 0.0) for s in dataset.symbols
                    )
                    cost = traded * cost_rate
                    invested = sum(target_qty[s] * px.get(s, 0.0) for s in dataset.symbols)
                n_changed = sum(
                    1 for s in dataset.symbols if abs(target_qty[s] - qty[s]) > 1e-12
                )
                held = sum(1 for s in dataset.symbols if target_qty[s] > 0.0)
                result.max_positions_held = max(result.max_positions_held, held)
                result.mean_positions_held += (held - result.mean_positions_held) / (
                    result.n_rebalances + 1
                )
                for s in dataset.symbols:
                    actual_w = target_qty[s] * px.get(s, 0.0) / equity
                    err = abs(actual_w - weights.get(s, 0.0))
                    result.weight_error_sum += err
                    result.weight_error_max = max(result.weight_error_max, err)
                    result.weight_error_n += 1
                    if weights.get(s, 0.0) > 0.0 and target_qty[s] == 0.0:
                        result.dropped_sleeve_events += 1
                qty = target_qty
                cash = equity - invested - cost
                result.max_cash_remainder = max(result.max_cash_remainder, cash)
                result.total_cost += cost
                result.traded_notional += traded
                result.n_rebalances += 1
                result.n_trades += n_changed
        equity_now = cash + sum(qty[s] * (dataset.closes[s][gi] or 0.0) for s in dataset.symbols)
        result.dates_ms.append(axis[gi - lo])
        result.equity.append(equity_now)
        if equity_now > 0.0:
            gross_notional = sum(
                qty[s] * (dataset.closes[s][gi] or 0.0) for s in dataset.symbols
            )
            cash_w_sum += max(0.0, 1.0 - gross_notional / equity_now)
            gross_w_sum += gross_notional / equity_now
            n_marks += 1

    # monthly equity marks (for Sharpe / turnover base)
    me_local = [i for i in me_all if lo <= i <= hi]
    for mi in me_local:
        result.monthly_dates_ms.append(dates[mi])
        result.monthly_equity.append(result.equity[mi - lo])

    result.gross_pnl = result.net_pnl + result.total_cost
    if n_marks:
        result.avg_cash_weight = cash_w_sum / n_marks
        result.avg_gross_weight = gross_w_sum / n_marks
    return result


def simulate_fixed_weights(
    dataset: Dataset,
    weights: dict[str, float],
    *,
    start_ms: int,
    end_ms: int,
    capital: float = REFERENCE_CAPITAL,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
) -> SimResult:
    """Benchmark helper: monthly-rebalanced fixed weights (no signal)."""
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError("fixed weights must sum to 1.0")
    dates = dataset.dates_ms
    keep = [i for i, ts in enumerate(dates) if start_ms <= ts <= end_ms]
    if len(keep) < 2:
        raise ValueError("range too short for simulation")
    lo, hi = keep[0], keep[-1]
    axis = dates[lo : hi + 1]
    me_all = month_end_indices(dates)
    me = [i for i in me_all if lo <= i < hi]
    cost_rate = cost_bps_per_side / 10_000.0
    cash = capital
    qty: dict[str, float] = dict.fromkeys(dataset.symbols, 0.0)
    result = SimResult(capital=capital)
    trade_days = sorted({min(i + 1, hi) for i in me})
    trade_day_set = set(trade_days)
    for gi in range(lo, hi + 1):
        if gi in trade_day_set and me:
            px = {s: dataset.closes[s][gi] for s in dataset.symbols}
            equity = cash + sum(qty[s] * (px[s] or 0.0) for s in dataset.symbols)
            target_qty: dict[str, float] = {}
            for s in dataset.symbols:
                price = px.get(s)
                w = weights.get(s, 0.0)
                if price is None or w <= 0.0:
                    target_qty[s] = 0.0
                    continue
                target_qty[s] = _round_qty(w * equity / price)
            traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in dataset.symbols)
            cost = traded * cost_rate
            invested = sum(target_qty[s] * (px[s] or 0.0) for s in dataset.symbols)
            if invested + cost > equity and invested > 0.0:
                scale = (equity - cost) / invested
                target_qty = {s: _round_qty(target_qty[s] * scale) for s in dataset.symbols}
                traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in dataset.symbols)
                cost = traded * cost_rate
                invested = sum(target_qty[s] * (px[s] or 0.0) for s in dataset.symbols)
            qty = target_qty
            cash = equity - invested - cost
            result.total_cost += cost
            result.traded_notional += traded
            result.n_rebalances += 1
        equity_now = cash + sum(qty[s] * (dataset.closes[s][gi] or 0.0) for s in dataset.symbols)
        result.dates_ms.append(axis[gi - lo])
        result.equity.append(equity_now)
    for mi in [i for i in me_all if lo <= i <= hi]:
        result.monthly_dates_ms.append(dates[mi])
        result.monthly_equity.append(result.equity[mi - lo])
    result.gross_pnl = result.net_pnl + result.total_cost
    return result


def sharpe_from_monthly(monthly_equity: list[float]) -> float:
    """Annualised Sharpe of monthly equity marks (cash return 0, rf = 0)."""
    if len(monthly_equity) < 3:
        return 0.0
    rets = [
        monthly_equity[i] / monthly_equity[i - 1] - 1.0
        for i in range(1, len(monthly_equity))
        if monthly_equity[i - 1] > 0.0
    ]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd <= 0.0:
        return 0.0
    return (mean / sd) * math.sqrt(12.0)


def monthly_returns(monthly_equity: list[float]) -> list[float]:
    return [
        monthly_equity[i] / monthly_equity[i - 1] - 1.0
        for i in range(1, len(monthly_equity))
        if monthly_equity[i - 1] > 0.0
    ]
