"""SMALL_CAPITAL_DUAL_MOMENTUM_V1 (RFC-040) — SC-DUALMOM-002.

Frozen implementation of the second (and last) pre-selected small-capital
candidate: a Dual Momentum / Global Equities Momentum style rotation expressed
with **EU-retail-accessible UCITS ETFs** quoted in EUR (no FX for a EUR account).

Rules frozen before any result (§Freeze):

* risky pair        RISK_A = SXR8.DE (S&P 500 UCITS) vs RISK_B = EUNK.DE (MSCI Europe UCITS)
* defensive asset   DEFENSIVE = DBZB.DE (Global Government Bond UCITS, EUR-hedged)
* risk-free / cash  CASH = XEON.DE (EUR Overnight Rate Swap, tracks €STR)
* equity benchmark  EQUITY_BENCH = EUNL.DE (MSCI World UCITS)
* relative momentum: hold the risky leg with the higher ``lookback`` return;
* absolute momentum: if that winner's ``lookback`` return <= 0, hold DEFENSIVE;
* lookback          = 252 trading days (~12 months);
* allocation        = 100% single asset (binary), gross <= 1.0, no leverage, no short;
* rebalance         = monthly, decision at month-end close t, execution at t+1 close;
* cost              = 10 bps per side on traded notional, stressed x1.5 / x2.0;
* accounting        = fractional notional (quantity step 1e-4), min notional 1 USD.

Research only: no orders, no credentials, no paid data, no live capital.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from trading_bot.research.small_capital_v1 import (
    Dataset,
    _round_qty,
    max_drawdown,
    month_end_indices,
    monthly_returns,
    sharpe_from_monthly,
)

__all__ = [
    "CASH",
    "COST_BPS_PER_SIDE",
    "DEFENSIVE",
    "EQUITY_BENCH",
    "LOOKBACK",
    "REFERENCE_CAPITAL",
    "RISK_A",
    "RISK_B",
    "SMALL_CAP_UNIVERSE",
    "annual_vol",
    "dm_decision",
    "forward_filled_prices",
    "simulate_dual_momentum",
    "simulate_scaled_passive",
]

REFERENCE_CAPITAL: float = 200.0  # product-design capital (not live capital)
SCALING_CAPITALS: tuple[float, ...] = (200.0, 500.0, 1_000.0, 5_000.0, 10_000.0)

RISK_A = "SXR8.DE"
RISK_B = "EUNK.DE"
DEFENSIVE = "DBZB.DE"
CASH = "XEON.DE"
EQUITY_BENCH = "EUNL.DE"

SMALL_CAP_UNIVERSE: tuple[str, ...] = (RISK_A, RISK_B, DEFENSIVE, CASH, EQUITY_BENCH)

LOOKBACK: int = 252
COST_BPS_PER_SIDE: float = 10.0
MIN_POSITION_NOTIONAL_USD: float = 1.0
MAX_GROSS_EXPOSURE: float = 1.0

_MS_PER_DAY: int = 86_400_000


@dataclass(slots=True)
class DMResult:
    """Frozen output of one SC-DUALMOM-002 simulation."""

    capital: float
    dates_ms: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    monthly_equity: list[float] = field(default_factory=list)
    monthly_dates_ms: list[int] = field(default_factory=list)
    holdings: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    traded_notional: float = 0.0
    n_rebalances: int = 0
    n_switches: int = 0
    weight_error_sum: float = 0.0
    weight_error_max: float = 0.0
    weight_error_n: int = 0
    dropped_sleeve_events: int = 0
    n_in_defensive: int = 0

    @property
    def final_equity(self) -> float:
        return self.equity[-1] if self.equity else self.capital

    @property
    def net_pnl(self) -> float:
        return self.final_equity - self.capital

    def years(self) -> float:
        if len(self.dates_ms) < 2:
            return 0.0
        return (self.dates_ms[-1] - self.dates_ms[0]) / (365.25 * _MS_PER_DAY)

    def cagr(self) -> float:
        y, cap0 = self.years(), self.capital
        if y <= 0.0 or cap0 <= 0.0:
            return 0.0
        ratio = self.final_equity / cap0
        if ratio <= 0.0:
            return -1.0
        return float(ratio ** (1.0 / y)) - 1.0

    def annual_turnover(self) -> float:
        y = self.years()
        if y <= 0.0 or not self.monthly_equity:
            return 0.0
        avg = sum(self.monthly_equity) / len(self.monthly_equity)
        return self.traded_notional / (avg * y) if avg > 0.0 else 0.0

    def mean_weight_error(self) -> float:
        return self.weight_error_sum / self.weight_error_n if self.weight_error_n else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital": self.capital,
            "net_pnl": round(self.net_pnl, 6),
            "gross_pnl": round(self.net_pnl + self.total_cost, 6),
            "total_cost": round(self.total_cost, 6),
            "cagr": round(self.cagr(), 8),
            "sharpe": round(sharpe_from_monthly(self.monthly_equity), 6),
            "max_drawdown": round(max_drawdown(self.equity), 8),
            "annual_turnover": round(self.annual_turnover(), 6),
            "n_rebalances": self.n_rebalances,
            "n_switches": self.n_switches,
            "years": round(self.years(), 4),
            "pct_months_in_defensive": round(
                self.n_in_defensive / self.n_rebalances if self.n_rebalances else 0.0, 6
            ),
            "mean_weight_error": round(self.mean_weight_error(), 8),
            "max_weight_error": round(self.weight_error_max, 8),
            "dropped_sleeve_events": self.dropped_sleeve_events,
        }


def forward_filled_prices(ds: Dataset) -> dict[str, list[float | None]]:
    """Last known close per symbol and axis index (PIT valuation, never back-filled).

    Signals always read the RAW closes; only valuation/execution uses the last
    known price, so a holiday that differs between venues can never zero out a
    held position.
    """
    out: dict[str, list[float | None]] = {}
    for sym in ds.symbols:
        series: list[float | None] = []
        last: float | None = None
        for v in ds.closes[sym]:
            if v is not None:
                last = v
            series.append(last)
        out[sym] = series
    return out


def annual_vol(monthly_equity: list[float]) -> float:
    """Annualised volatility of monthly marks."""
    rets = monthly_returns(monthly_equity)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(12.0)


def dm_decision(ds: Dataset, idx: int, *, lookback: int = LOOKBACK) -> tuple[str, dict[str, Any]]:
    """Frozen Dual Momentum decision at index ``idx``.

    Returns the chosen symbol plus the relative/absolute momentum diagnostics.
    Uses only closes up to and including ``idx`` (PIT).
    """
    if idx < lookback:
        return DEFENSIVE, {"reason": "warmup"}
    ra = ds.closes[RISK_A][idx]
    rb = ds.closes[RISK_B][idx]
    ra0 = ds.closes[RISK_A][idx - lookback]
    rb0 = ds.closes[RISK_B][idx - lookback]
    if ra is None or rb is None or ra0 is None or rb0 is None:
        return DEFENSIVE, {"reason": "missing_data"}
    ret_a = ra / ra0 - 1.0
    ret_b = rb / rb0 - 1.0
    winner = RISK_A if ret_a >= ret_b else RISK_B
    winner_ret = ret_a if winner == RISK_A else ret_b
    if winner_ret > 0.0:
        return winner, {"rel_a": ret_a, "rel_b": ret_b, "abs_winner": winner_ret}
    return DEFENSIVE, {"rel_a": ret_a, "rel_b": ret_b, "abs_winner": winner_ret}


def simulate_dual_momentum(
    ds: Dataset,
    *,
    start_ms: int,
    end_ms: int,
    capital: float = REFERENCE_CAPITAL,
    lookback: int = LOOKBACK,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
    min_position_notional: float = MIN_POSITION_NOTIONAL_USD,
) -> DMResult:
    """Simulate SC-DUALMOM-002 on ``[start_ms, end_ms]`` with ``capital`` EUR."""
    if capital <= 0.0:
        raise ValueError("capital must be > 0")
    if cost_bps_per_side < 0.0:
        raise ValueError("cost must be >= 0")
    for sym in (RISK_A, RISK_B, DEFENSIVE, CASH):
        if sym not in ds.symbols:
            raise ValueError(f"dataset missing required symbol {sym}")
    dates = ds.dates_ms
    keep = [i for i, ts in enumerate(dates) if start_ms <= ts <= end_ms]
    if len(keep) < 2:
        raise ValueError("range too short for simulation")
    lo, hi = keep[0], keep[-1]
    me_all = month_end_indices(dates)
    me = [i for i in me_all if lo <= i < hi]
    cost_rate = cost_bps_per_side / 10_000.0
    vf = forward_filled_prices(ds)

    cash = capital
    qty: dict[str, float] = dict.fromkeys(ds.symbols, 0.0)
    res = DMResult(capital=capital)
    last_hold = ""

    for gi in range(lo, hi + 1):
        if gi in {i + 1 for i in me} and me:
            px = {s: vf[s][gi] for s in ds.symbols}
            equity = cash + sum(qty[s] * (px[s] or 0.0) for s in ds.symbols)
            dec = max((i for i in me if i < gi), default=None)
            if dec is not None and equity > 0.0:
                hold, _ = dm_decision(ds, dec, lookback=lookback)
                target_qty: dict[str, float] = dict.fromkeys(ds.symbols, 0.0)
                price = px.get(hold)
                if price is not None and price > 0.0:
                    q = _round_qty(equity / price)
                    if q * price >= min_position_notional:
                        target_qty[hold] = q
                else:
                    # no usable price yet: keep the current book unchanged
                    target_qty = {s: qty[s] for s in ds.symbols}
                traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in ds.symbols)
                cost = traded * cost_rate
                invested = sum(target_qty[s] * (px[s] or 0.0) for s in ds.symbols)
                if invested + cost > equity:
                    scale = (equity - cost) / invested if invested > 0.0 else 0.0
                    target_qty = {s: _round_qty(target_qty[s] * scale) for s in ds.symbols}
                    traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in ds.symbols)
                    cost = traded * cost_rate
                    invested = sum(target_qty[s] * (px[s] or 0.0) for s in ds.symbols)
                if hold != last_hold and last_hold:
                    res.n_switches += 1
                last_hold = hold
                res.holdings.append(hold)
                if hold == DEFENSIVE:
                    res.n_in_defensive += 1
                for s in ds.symbols:
                    actual_w = target_qty[s] * (px[s] or 0.0) / equity
                    err = abs(actual_w - (1.0 if s == hold else 0.0))
                    res.weight_error_sum += err
                    res.weight_error_max = max(res.weight_error_max, err)
                    res.weight_error_n += 1
                    if s == hold and target_qty[s] == 0.0:
                        res.dropped_sleeve_events += 1
                qty = target_qty
                cash = equity - invested - cost
                res.total_cost += cost
                res.traded_notional += traded
                res.n_rebalances += 1
        res.dates_ms.append(dates[gi])
        res.equity.append(cash + sum(qty[s] * (vf[s][gi] or 0.0) for s in ds.symbols))

    for mi in [i for i in me_all if lo <= i <= hi]:
        res.monthly_dates_ms.append(dates[mi])
        res.monthly_equity.append(res.equity[mi - lo])
    return res


def simulate_scaled_passive(
    ds: Dataset,
    *,
    weight: float,
    start_ms: int,
    end_ms: int,
    capital: float = REFERENCE_CAPITAL,
    cost_bps_per_side: float = COST_BPS_PER_SIDE,
) -> DMResult:
    """Risk-matched passive: ``weight`` in the equity benchmark, rest in CASH.

    Monthly rebalanced, fractional accounting, same cost model. ``weight`` is
    capped at 1.0 (no leverage is ever allowed).
    """
    if not 0.0 <= weight <= 1.0:
        raise ValueError("weight must be in [0, 1] (no leverage)")
    return _simulate_fixed_pair(
        ds,
        heavy=EQUITY_BENCH,
        light=CASH,
        weight=weight,
        start_ms=start_ms,
        end_ms=end_ms,
        capital=capital,
        cost_bps_per_side=cost_bps_per_side,
    )


def _simulate_fixed_pair(
    ds: Dataset,
    *,
    heavy: str,
    light: str,
    weight: float,
    start_ms: int,
    end_ms: int,
    capital: float,
    cost_bps_per_side: float,
) -> DMResult:
    dates = ds.dates_ms
    keep = [i for i, ts in enumerate(dates) if start_ms <= ts <= end_ms]
    lo, hi = keep[0], keep[-1]
    me_all = month_end_indices(dates)
    me = [i for i in me_all if lo <= i < hi]
    cost_rate = cost_bps_per_side / 10_000.0
    vf = forward_filled_prices(ds)
    cash = capital
    qty: dict[str, float] = dict.fromkeys(ds.symbols, 0.0)
    res = DMResult(capital=capital)
    for gi in range(lo, hi + 1):
        if gi in {i + 1 for i in me} and me:
            px = {s: vf[s][gi] for s in ds.symbols}
            equity = cash + sum(qty[s] * (px[s] or 0.0) for s in ds.symbols)
            target_qty: dict[str, float] = dict.fromkeys(ds.symbols, 0.0)
            for sym, w in ((heavy, weight), (light, 1.0 - weight)):
                price = px.get(sym)
                if price is None or w <= 0.0:
                    continue
                q = _round_qty(w * equity / price)
                if q * price >= MIN_POSITION_NOTIONAL_USD:
                    target_qty[sym] = q
            traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in ds.symbols)
            cost = traded * cost_rate
            invested = sum(target_qty[s] * (px[s] or 0.0) for s in ds.symbols)
            if invested + cost > equity and invested > 0.0:
                scale = (equity - cost) / invested
                target_qty = {s: _round_qty(target_qty[s] * scale) for s in ds.symbols}
                traded = sum(abs(target_qty[s] - qty[s]) * (px[s] or 0.0) for s in ds.symbols)
                cost = traded * cost_rate
                invested = sum(target_qty[s] * (px[s] or 0.0) for s in ds.symbols)
            qty = target_qty
            cash = equity - invested - cost
            res.total_cost += cost
            res.traded_notional += traded
            res.n_rebalances += 1
        res.dates_ms.append(dates[gi])
        res.equity.append(cash + sum(qty[s] * (vf[s][gi] or 0.0) for s in ds.symbols))
    for mi in [i for i in me_all if lo <= i <= hi]:
        res.monthly_dates_ms.append(dates[mi])
        res.monthly_equity.append(res.equity[mi - lo])
    return res
