"""RFC-029 — Structural low-turnover carry pivot: shared library.

READ-ONLY, RESEARCH-ONLY, PIT-SAFE BY CONSTRUCTION.

The RFC-028 conclusion was that the project does not need a *stronger* signal;
it needs a *strategy class* where the same transaction cost is amortized over
much longer holding periods.  RFC-029 therefore freezes the structure

    LONG SPOT (notional N) + SHORT PERPETUAL (notional N)

and varies the HOLDING STRUCTURE only, never the alpha.

PIT CONTRACT (§19, preserved from RFC-028)
    Decisions happen at funding payment times ``ts[i] = calc_time``.  A signal
    at ``i`` may only use payments strictly ``< i`` (``rate[i-K:i]``); the
    realized rate is used for OUTCOME accounting inside the holding window.

ECONOMIC IDENTITY (§26-§28, §42-§43)
    net_bps = funding + basis - cost
    basis   = spot_pnl + perp_pnl   (the net-of-hedge residual term)
    return_on_committed = (net_bps / 1e4) / COMMITTED_CAPITAL
    capital_days        = COMMITTED_CAPITAL * holding_days
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sprint028_lib as L
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "reports" / "structural-carry"

ASSETS = L.ASSETS
SRC_MS = L.SRC_MS
FUNDING_INTERVAL_MS = L.FUNDING_INTERVAL_MS

# ---- frozen cost / capital model (RFC-028 CARRY_COST_MODEL_V1) -------------
ROUND_TRIP_COST_BPS = L.ROUND_TRIP_COST_BPS  # 39.0 bps
SPOT_SIDE_BPS = L.SPOT_SIDE_BPS
PERP_SIDE_BPS = L.PERP_SIDE_BPS
COST_MODEL_V3_BPS = L.COST_MODEL_V3_BPS  # deliberately NOT used
PERP_LEVERAGE = L.PERP_LEVERAGE  # 3.0
COMMITTED_CAPITAL = L.COMMITTED_CAPITAL  # 1 + 1/3
SPLIT_FRACTIONS = L.SPLIT_FRACTIONS

HOLDOUT_ANALYTICS_READ = False

# ---- pre-registered long-horizon set (§10-§11) -----------------------------
HORIZON_PERIODS: dict[str, int] = {
    "7d": 21,
    "14d": 42,
    "21d": 63,
    "30d": 90,
    "45d": 135,
}
REFERENCE_HORIZON = "7d"  # RFC-028 reference (§65)
CORE_HORIZONS = ("14d", "21d", "30d", "45d")  # 4 core horizons
HORIZON_ORDER = ("7d", "14d", "21d", "30d", "45d")

# ---- pre-registered entry-policy constants (§12-§16) -----------------------
TRAILING_WINDOW = 21  # fixed 7d causal trailing window (periods)
PERSIST_N = 3  # one pre-registered persistence length
SAFETY_MARGIN_BPS = 10.0  # policy C pre-registered safety margin
BASIS_FLOOR_BPS = -75.0  # policy D frozen basis floor
MIN_HOLD_PERIODS = 21  # minimum hold before a regime/target exit (7d)
EXIT_C_MARGIN_BPS = 10.0  # policy/exit C pre-registered target margin
PERIODS_PER_DAY = 3  # 8h funding schedule

POLICIES = ("A_POSITIVE_REGIME", "B_PERSISTENCE", "C_ECONOMIC", "D_BASIS_SAFE")
POLICY_LABELS = {
    "A_POSITIVE_REGIME": "A unconditional positive trailing-funding regime",
    "B_PERSISTENCE": "B last N=3 realized payments positive (persistence)",
    "C_ECONOMIC": "C trailing estimate x periods > cost + 10 bps margin",
    "D_BASIS_SAFE": "D positive regime AND basis > -75 bps (basis-safe)",
}
EXIT_MODELS = ("A_FIXED_HOLD", "B_FUNDING_BREAK", "C_COST_RECOVERY")
PRIMARY_EXIT_MODEL = "A_FIXED_HOLD"

MIN_DISCOVERY_EPISODES = 8
MIN_VALIDATION_EPISODES = 6

# Allocation: 4 policies x 4 core horizons x 3 assets = 48 core cells (§17).
# The 7d row is the RFC-028 reference, recomputed for one policy only.
CORE_CELLS = len(POLICIES) * len(CORE_HORIZONS) * len(ASSETS)  # 48


# ---------------------------------------------------------------------------
# data assembly (reuses the RFC-028 epoch-normalized cache)
# ---------------------------------------------------------------------------


def _asset_series(asset: str) -> tuple[NDArray[Any], ...]:
    spot = L.load_spot(asset)
    perp = L.load_perp(asset)
    fund = L.load_funding(asset)
    gts = fund["funding_time_ms"].astype(np.int64)
    s_close = L._asof(spot["open_time_ms"].astype(np.int64) + SRC_MS, spot["close"], gts)
    p_close = L._asof(perp["open_time_ms"].astype(np.int64) + SRC_MS, perp["close"], gts)
    rate = np.asarray(fund["funding_rate"], dtype=np.float64) * 1e4
    basis = (p_close / s_close - 1.0) * 1e4
    return gts, s_close, p_close, rate, basis


@dataclass(frozen=True, slots=True)
class AssetPanel:
    asset: str
    ts: NDArray[Any]  # funding payment times (ms)
    spot: NDArray[Any]
    perp: NDArray[Any]
    basis: NDArray[Any]
    funding: NDArray[Any]  # realized rate in bps
    f_mean_w: NDArray[Any]  # strictly-past mean over TRAILING_WINDOW
    f_persist_n: NDArray[Any]  # strictly-past fraction positive over PERSIST_N

    def n(self) -> int:
        return int(self.ts.shape[0])


_PANEL_CACHE: dict[str, AssetPanel] = {}


def asset_panel(asset: str) -> AssetPanel:
    if asset not in _PANEL_CACHE:
        ts, s, p, r, b = _asset_series(asset)
        _PANEL_CACHE[asset] = AssetPanel(
            asset=asset,
            ts=ts,
            spot=s,
            perp=p,
            basis=b,
            funding=r,
            f_mean_w=L._mean_of_lag(r, TRAILING_WINDOW),
            f_persist_n=L._persist_of_lag(r, PERSIST_N),
        )
    return _PANEL_CACHE[asset]


def _prefix(x: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any]]:
    fin = np.isfinite(x)
    r0 = np.where(fin, x, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(r0)])
    cn = np.concatenate([[0], np.cumsum(~fin)])
    return cs, cn


def _fsum(cs: NDArray[Any], cn: NDArray[Any], a: int, b: int) -> float | None:
    """Sum x[a:b] (inclusive-exclusive); None if any datum in range is non-finite."""
    if b <= a:
        return 0.0
    if int(cn[b] - cn[a]) > 0:
        return None
    return float(cs[b] - cs[a])


# ---------------------------------------------------------------------------
# entry policies (§12-§16)
# ---------------------------------------------------------------------------


def entry_mask(panel: AssetPanel, policy: str, horizon_key: str) -> NDArray[Any]:
    if policy == "A_POSITIVE_REGIME":
        m = np.isfinite(panel.f_mean_w) & (panel.f_mean_w > 0.0)
    elif policy == "B_PERSISTENCE":
        m = np.isfinite(panel.f_persist_n) & (panel.f_persist_n >= 1.0)
    elif policy == "C_ECONOMIC":
        exp = panel.f_mean_w * float(HORIZON_PERIODS[horizon_key])
        m = np.isfinite(exp) & (exp > ROUND_TRIP_COST_BPS + SAFETY_MARGIN_BPS)
    elif policy == "D_BASIS_SAFE":
        m = (
            np.isfinite(panel.f_mean_w)
            & (panel.f_mean_w > 0.0)
            & np.isfinite(panel.basis)
            & (panel.basis > BASIS_FLOOR_BPS)
        )
    else:
        raise ValueError(f"unknown policy {policy}")
    return np.asarray(m, dtype=bool)


# ---------------------------------------------------------------------------
# simulation (non-overlapping, one active position per asset per strategy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trade029:
    asset: str
    policy: str
    horizon_key: str
    exit_model: str
    entry_idx: int
    exit_idx: int
    entry_ts: int
    exit_ts: int
    holding_periods: int
    funding_pnl_bps: float
    spot_pnl_bps: float
    perp_pnl_bps: float
    basis_pnl_bps: float
    cost_bps: float
    net_bps: float
    return_on_committed: float
    capital_days: float
    breakeven_periods: int | None


def _breakeven(
    panel: AssetPanel, i: int, j: int, cost: float, cs: NDArray[Any], cn: NDArray[Any]
) -> int | None:
    for k in range(i + 1, j + 1):
        fb = _fsum(cs, cn, i + 1, k + 1)
        if fb is None:
            continue
        bp = (panel.spot[k] / panel.spot[i] - panel.perp[k] / panel.perp[i]) * 1e4
        if np.isfinite(bp) and fb + bp > cost:
            return int(k - i)
    return None


def simulate(
    panel: AssetPanel,
    policy: str,
    horizon_key: str,
    exit_model: str = PRIMARY_EXIT_MODEL,
    lo: float = 0.0,
    hi: float = 1.0,
    cost: float = ROUND_TRIP_COST_BPS,
) -> list[Trade029]:
    """Non-overlapping event simulation; next entry only after the previous exit."""
    n = panel.n()
    a, b = int(n * lo), int(n * hi)
    h = HORIZON_PERIODS[horizon_key]
    mask = entry_mask(panel, policy, horizon_key)
    cs, cn = _prefix(panel.funding)
    trades: list[Trade029] = []
    i = a
    while i + h < b:
        if not mask[i]:
            i += 1
            continue
        j = i + h
        if exit_model == "B_FUNDING_BREAK":
            for k in range(i + MIN_HOLD_PERIODS, i + h + 1):
                fw = panel.f_mean_w[k] if k < n else np.nan
                if np.isfinite(fw) and fw <= 0.0:
                    j = k
                    break
        elif exit_model == "C_COST_RECOVERY":
            for k in range(i + MIN_HOLD_PERIODS, i + h + 1):
                fb = _fsum(cs, cn, i + 1, k + 1)
                if fb is None:
                    continue
                bp = (panel.spot[k] / panel.spot[i] - panel.perp[k] / panel.perp[i]) * 1e4
                if np.isfinite(bp) and (fb + bp) > cost + EXIT_C_MARGIN_BPS:
                    j = k
                    break
        elif exit_model != "A_FIXED_HOLD":
            raise ValueError(f"unknown exit model {exit_model}")
        if j >= b or j <= i:
            i += 1
            continue
        vals = (panel.spot[i], panel.spot[j], panel.perp[i], panel.perp[j])
        fsum = _fsum(cs, cn, i + 1, j + 1)
        if fsum is None or not all(np.isfinite(v) for v in vals):
            i += 1
            continue
        spot_pnl = (panel.spot[j] / panel.spot[i] - 1.0) * 1e4
        perp_pnl = -(panel.perp[j] / panel.perp[i] - 1.0) * 1e4
        basis_pnl = spot_pnl + perp_pnl
        net = spot_pnl + perp_pnl + fsum - cost
        hp = j - i
        trades.append(
            Trade029(
                asset=panel.asset,
                policy=policy,
                horizon_key=horizon_key,
                exit_model=exit_model,
                entry_idx=i,
                exit_idx=j,
                entry_ts=int(panel.ts[i]),
                exit_ts=int(panel.ts[j]),
                holding_periods=hp,
                funding_pnl_bps=fsum,
                spot_pnl_bps=spot_pnl,
                perp_pnl_bps=perp_pnl,
                basis_pnl_bps=basis_pnl,
                cost_bps=cost,
                net_bps=net,
                return_on_committed=(net / 1e4) / COMMITTED_CAPITAL,
                capital_days=COMMITTED_CAPITAL * (hp / PERIODS_PER_DAY),
                breakeven_periods=_breakeven(panel, i, j, cost, cs, cn),
            )
        )
        i = j + 1
    return trades


def simulate_portfolio(
    policy: str,
    horizon_key: str,
    exit_model: str = PRIMARY_EXIT_MODEL,
    lo: float = 0.0,
    hi: float = 1.0,
    cost: float = ROUND_TRIP_COST_BPS,
) -> list[Trade029]:
    out: list[Trade029] = []
    for asset in ASSETS:
        out.extend(simulate(asset_panel(asset), policy, horizon_key, exit_model, lo, hi, cost))
    return out


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _sharpe(x: NDArray[Any]) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or float(np.std(x)) == 0.0:
        return None
    return float(np.mean(x) / np.std(x) * math.sqrt(x.size))


def _max_drawdown(cum: NDArray[Any]) -> float:
    cum = np.asarray(cum, dtype=np.float64)
    if not cum.size:
        return 0.0
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum))


def aggregate(trades: list[Trade029]) -> dict[str, Any]:
    if not trades:
        return {"status": "NO_TRADES", "episodes": 0}
    net = np.array([t.net_bps for t in trades], dtype=np.float64)
    fund = np.array([t.funding_pnl_bps for t in trades], dtype=np.float64)
    basis = np.array([t.basis_pnl_bps for t in trades], dtype=np.float64)
    spot = np.array([t.spot_pnl_bps for t in trades], dtype=np.float64)
    cost = np.array([t.cost_bps for t in trades], dtype=np.float64)
    roc = np.array([t.return_on_committed for t in trades], dtype=np.float64)
    hp = np.array([t.holding_periods for t in trades], dtype=np.float64)
    active_days = float(np.sum(hp) / PERIODS_PER_DAY)
    capital_days = float(np.sum([t.capital_days for t in trades]))
    net_return = float(np.sum(net) / 1e4)
    wins = net[net > 0]
    losses = net[net <= 0]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    order = np.sort(net)[::-1]
    be_probs = [t.breakeven_periods for t in trades if t.breakeven_periods is not None]
    return {
        "status": "OK",
        "episodes": int(net.size),
        "active_days": round(active_days, 4),
        "mean_holding_days": round(float(np.mean(hp)) / PERIODS_PER_DAY, 4),
        "funding_pnl_bps": round(float(np.sum(fund)), 4),
        "basis_pnl_bps": round(float(np.sum(basis)), 4),
        "spot_pnl_bps": round(float(np.sum(spot)), 4),
        "cost_bps": round(float(np.sum(cost)), 4),
        "net_pnl_bps": round(float(np.sum(net)), 4),
        "net_expectancy_bps": round(float(np.mean(net)), 4),
        "mean_funding_bps": round(float(np.mean(fund)), 4),
        "mean_basis_bps": round(float(np.mean(basis)), 4),
        "mean_cost_bps": round(float(np.mean(cost)), 4),
        "net_return": round(net_return, 8),
        "mean_roc": round(float(np.mean(roc)), 8),
        "sum_roc": round(float(np.sum(roc)), 8),
        "capital_days": round(capital_days, 6),
        "return_per_capital_day": round(net_return / capital_days, 10)
        if capital_days > 0
        else None,
        "win_rate": round(float(np.mean(net > 0)), 4),
        "pf": round(gp / gl, 4) if gl > 0 else None,
        "sharpe": _sharpe(roc),
        "max_dd_bps": round(_max_drawdown(np.cumsum(net)), 4),
        "be_fraction": round(len(be_probs) / net.size, 4),
        "median_be_periods": float(np.median(be_probs)) if be_probs else None,
        "funding_share_of_gross": round(float(np.sum(fund) / (np.sum(fund) + np.sum(basis))), 6)
        if (np.sum(fund) + np.sum(basis)) != 0
        else None,
        "basis_share_of_gross": round(float(np.sum(basis) / (np.sum(fund) + np.sum(basis))), 6)
        if (np.sum(fund) + np.sum(basis)) != 0
        else None,
        "top1_share": round(float(order[0] / order.sum()), 6) if order.sum() != 0 else None,
        "top3_share": round(float(order[:3].sum() / order.sum()), 6) if order.sum() != 0 else None,
        "without_best_mean_bps": round(float(np.mean(np.sort(net)[:-1])), 4)
        if net.size > 1
        else None,
        "without_best3_mean_bps": round(float(np.mean(np.sort(net)[:-3])), 4)
        if net.size > 3
        else None,
    }


def per_asset(trades: list[Trade029]) -> dict[str, Any]:
    return {a: aggregate([t for t in trades if t.asset == a]) for a in ASSETS}


# ---------------------------------------------------------------------------
# funding persistence / survival / cumulative funding / break-even metrics
# ---------------------------------------------------------------------------


def fwd_funding(panel: AssetPanel, i: int, h: int) -> float | None:
    r = panel.funding
    if i + h >= panel.n():
        return None
    win = r[i + 1 : i + h + 1]
    if not np.all(np.isfinite(win)):
        return None
    return float(np.sum(win))


def trailing_mean_at(panel: AssetPanel, k: int, w: int = TRAILING_WINDOW) -> float | None:
    if k - w < 0 or k >= panel.n():
        return None
    win = panel.funding[k - w : k]
    if not np.all(np.isfinite(win)):
        return None
    return float(np.mean(win))


def _entry_indices(
    panel: AssetPanel, policy: str, horizon_key: str, lo: float, hi: float
) -> NDArray[Any]:
    """Non-overlapping entry indices (fully-available forward window inside split)."""
    n = panel.n()
    a, b = int(n * lo), int(n * hi)
    h = HORIZON_PERIODS[horizon_key]
    mask = entry_mask(panel, policy, horizon_key)
    out: list[int] = []
    i = a
    while i + h < b:
        if mask[i] and np.all(np.isfinite(panel.funding[i + 1 : i + h + 1])):
            out.append(i)
            i += h + 1
        else:
            i += 1
    return np.asarray(out, dtype=np.int64)


def cumulative_funding_distribution(
    policy: str, horizon_key: str, lo: float, hi: float
) -> dict[str, Any]:
    h = HORIZON_PERIODS[horizon_key]
    vals: list[float] = []
    for asset in ASSETS:
        p = asset_panel(asset)
        for i in _entry_indices(p, policy, horizon_key, lo, hi):
            v = fwd_funding(p, int(i), h)
            if v is not None:
                vals.append(v)
    if not vals:
        return {"status": "NO_DATA", "n": 0}
    arr = np.asarray(vals, dtype=np.float64)
    qs = np.percentile(arr, [10, 25, 50, 75, 90])
    return {
        "status": "OK",
        "n": int(arr.size),
        "p10": round(float(qs[0]), 4),
        "p25": round(float(qs[1]), 4),
        "median": round(float(qs[2]), 4),
        "mean": round(float(np.mean(arr)), 4),
        "p75": round(float(qs[3]), 4),
        "p90": round(float(qs[4]), 4),
        "cost_bps": ROUND_TRIP_COST_BPS,
        "prob_positive": round(float(np.mean(arr > 0.0)), 4),
        "prob_above_cost": round(float(np.mean(arr > ROUND_TRIP_COST_BPS)), 4),
    }


def survival_curve(policy: str, horizon_key: str, lo: float, hi: float) -> dict[str, Any]:
    """P(funding regime still positive after t days | entry), causal trailing mean."""
    days = (1, 3, 7, 14, 21, 30, 45)
    per_day: dict[int, Any] = {}
    entries_all: list[tuple[str, int]] = []
    for asset in ASSETS:
        p = asset_panel(asset)
        for i in _entry_indices(p, policy, horizon_key, lo, hi):
            entries_all.append((asset, int(i)))
    for d in days:
        k_off = d * PERIODS_PER_DAY
        pos = 0
        tot = 0
        for asset, i in entries_all:
            p = asset_panel(asset)
            tm = trailing_mean_at(p, i + k_off)
            if tm is None:
                continue
            tot += 1
            if tm > 0:
                pos += 1
        per_day[d] = {"n": tot, "p_positive": round(pos / tot, 4) if tot else None}
    return {
        "policy": policy,
        "horizon": horizon_key,
        "entries": len(entries_all),
        "survival": per_day,
    }


def persistence_profile(policy: str, horizon_key: str, lo: float, hi: float) -> dict[str, Any]:
    """Mean causal trailing funding at entry and at +1/3/7/14/21/30d, plus ratio."""
    days = (0, 1, 3, 7, 14, 21, 30)
    offsets: dict[int, list[float]] = {d: [] for d in days}
    for asset in ASSETS:
        p = asset_panel(asset)
        for i in _entry_indices(p, policy, horizon_key, lo, hi):
            for d in days:
                v = trailing_mean_at(p, int(i) + d * PERIODS_PER_DAY)
                if v is not None:
                    offsets[d].append(v)
    prof: dict[str, Any] = {}
    base = float(np.mean(offsets[0])) if offsets[0] else None
    for d in days:
        m = float(np.mean(offsets[d])) if offsets[d] else None
        prof[f"{d}d"] = {
            "mean_bps": round(m, 4) if m is not None else None,
            "ratio_to_entry": round(m / base, 4)
            if (m is not None and base is not None and base != 0)
            else None,
            "n": len(offsets[d]),
        }
    half_life: float | None = None
    if base and base > 0:
        for d in days:
            if offsets[d]:
                m = float(np.mean(offsets[d]))
                if m <= base / 2.0:
                    half_life = float(d)
                    break
    return {
        "policy": policy,
        "horizon": horizon_key,
        "entry_mean_bps": round(base, 4) if base is not None else None,
        "profile": prof,
        "half_life_days": half_life,
    }


def time_to_break_even(
    policy: str, horizon_key: str, lo: float, hi: float, cost: float = ROUND_TRIP_COST_BPS
) -> dict[str, Any]:
    """Distribution of first time cumulative realized carry > round-trip cost."""
    h = HORIZON_PERIODS[horizon_key]
    periods: list[float] = []
    censored = 0
    total = 0
    for asset in ASSETS:
        p = asset_panel(asset)
        cs, cn = _prefix(p.funding)
        for i in _entry_indices(p, policy, horizon_key, lo, hi):
            total += 1
            be = _breakeven(p, int(i), int(i) + h, cost, cs, cn)
            if be is None:
                censored += 1
            else:
                periods.append(float(be))
    if not periods:
        return {"status": "NO_DATA", "entries": total, "censored": censored}
    arr = np.asarray(periods, dtype=np.float64)
    qs = np.percentile(arr, [25, 50, 75, 90])
    return {
        "status": "OK",
        "entries": total,
        "censored": censored,
        "crossed": int(arr.size),
        "p25_periods": round(float(qs[0]), 3),
        "median_periods": round(float(qs[1]), 3),
        "p75_periods": round(float(qs[2]), 3),
        "p90_periods": round(float(qs[3]), 3),
        "p25_days": round(float(qs[0]) / PERIODS_PER_DAY, 3),
        "median_days": round(float(qs[1]) / PERIODS_PER_DAY, 3),
        "p75_days": round(float(qs[2]) / PERIODS_PER_DAY, 3),
        "p90_days": round(float(qs[3]) / PERIODS_PER_DAY, 3),
    }


def break_even_probability(policy: str, horizon_key: str, lo: float, hi: float) -> dict[str, Any]:
    """P(cumulative funding + basis > round-trip cost) per asset and pooled."""
    h = HORIZON_PERIODS[horizon_key]
    out: dict[str, Any] = {}
    pooled_hit = 0
    pooled_tot = 0
    for asset in ASSETS:
        p = asset_panel(asset)
        hit = tot = 0
        for i in _entry_indices(p, policy, horizon_key, lo, hi):
            ff = fwd_funding(p, int(i), h)
            if ff is None:
                continue
            bp = (p.spot[int(i) + h] / p.spot[int(i)] - p.perp[int(i) + h] / p.perp[int(i)]) * 1e4
            if not np.isfinite(bp):
                continue
            tot += 1
            if ff + bp > ROUND_TRIP_COST_BPS:
                hit += 1
        out[asset] = {"n": tot, "prob": round(hit / tot, 4) if tot else None}
        pooled_hit += hit
        pooled_tot += tot
    out["POOLED"] = {
        "n": pooled_tot,
        "prob": round(pooled_hit / pooled_tot, 4) if pooled_tot else None,
    }
    return out


def break_even_funding_bps(horizon_key: str) -> float:
    return ROUND_TRIP_COST_BPS / HORIZON_PERIODS[horizon_key]


def break_even_holding_days(mean_funding_bps_per_period: float) -> float | None:
    if not math.isfinite(mean_funding_bps_per_period) or mean_funding_bps_per_period <= 0:
        return None
    return (ROUND_TRIP_COST_BPS / mean_funding_bps_per_period) / PERIODS_PER_DAY
