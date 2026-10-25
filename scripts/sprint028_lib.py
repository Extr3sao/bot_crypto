"""RFC-028 — Market-neutral carry / relative-value edge discovery: shared library.

READ-ONLY, RESEARCH-ONLY, PIT-SAFE BY CONSTRUCTION.

This module answers a single question: *can a LONG SPOT + SHORT PERPETUAL
position earn a reproducible NET edge from funding + basis after every cost?*

STRUCTURE (§4-§5)
    LONG SPOT  (notional N)
    SHORT PERP (notional N)   -> approximately delta neutral

PIT CONTRACT (§6-§7)
    Funding rows carry ``observation_time_ms``, ``period_end_ms`` (payment),
    ``known_time_ms`` and ``available_time_ms``.  At a decision time ``T`` the
    signal may only use funding rows with ``payment_time < T`` (strictly), so
    the rate paid exactly at ``T`` is never used to *enter* at ``T``.  The
    realized rate is used for OUTCOME accounting inside a holding window.

ACCOUNTING (§13-§15)
    net = spot_pnl + perp_pnl + funding_pnl - (spot costs + perp costs).
    ``spot_pnl + perp_pnl`` is the basis/residual term; it must not dominate.

COST (§16-§18)
    CARRY_COST_MODEL_V1 is built from the *actual four leg transactions*
    (spot entry/exit, perp entry/exit) with conservative official public
    all-taker fees plus half-spread and impact.  COST_MODEL_V3 (23.790569 bps)
    is deliberately NOT reused as the carry cost.
"""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
CARRY_DIR = REPO / "reports" / "carry"
CACHE_DIR = CARRY_DIR / "cache"
POS_CACHE_DIR = REPO / "reports" / "positioning-data" / "cache"
OUT_DIR = CARRY_DIR

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# RFC-027 legacy control only — NOT the carry cost (§16).
COST_MODEL_V3_BPS = 23.790569

ROOT_NOTIONAL = 1.0  # per unit notional per leg (PnL reported in bps)
PERP_LEVERAGE = 3.0  # conservative; liquidation economically remote (§32-§33)
SPOT_LEG_CAPITAL = 1.0  # spot bought outright
PERP_LEG_CAPITAL = 1.0 / PERP_LEVERAGE
COMMITTED_CAPITAL = SPOT_LEG_CAPITAL + PERP_LEG_CAPITAL  # §31

SRC_MS = 5 * 60 * 1000  # 5m source grid
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000  # 8h funding schedule

# Holding horizons expressed in FUNDING PERIODS (§9).
HORIZON_PERIODS: dict[str, int] = {
    "8h": 1,
    "16h": 2,
    "24h": 3,
    "48h": 6,
    "72h": 9,
    "7d": 21,
}
HORIZON_ORDER = ("8h", "16h", "24h", "48h", "72h", "7d")

# ---------------------------------------------------------------------------
# CARRY_COST_MODEL_V1 (§16-§18) — conservative official public all-taker tiers.
# ---------------------------------------------------------------------------
CARRY_COST_MODEL_V1: dict[str, float] = {
    "spot_fee_bps": 10.0,  # Binance spot taker 0.10% (no BNB discount)
    "spot_half_spread_bps": 2.0,  # crossing half-spread, conservative
    "spot_impact_bps": 1.0,  # small-size market impact
    "perp_fee_bps": 5.0,  # USDⓈ-M perp taker 0.05%
    "perp_half_spread_bps": 1.0,
    "perp_impact_bps": 0.5,
}
SPOT_SIDE_BPS = (
    CARRY_COST_MODEL_V1["spot_fee_bps"]
    + CARRY_COST_MODEL_V1["spot_half_spread_bps"]
    + CARRY_COST_MODEL_V1["spot_impact_bps"]
)
PERP_SIDE_BPS = (
    CARRY_COST_MODEL_V1["perp_fee_bps"]
    + CARRY_COST_MODEL_V1["perp_half_spread_bps"]
    + CARRY_COST_MODEL_V1["perp_impact_bps"]
)
ROUND_TRIP_COST_BPS = 2.0 * SPOT_SIDE_BPS + 2.0 * PERP_SIDE_BPS  # 39.0 bps

# Trailing funding window (periods) used by the persistence signal (§21).
FUNDING_MEAN_K = 3

# Fractional chronological splits (§12).  Frozen, never shuffled.
SPLIT_FRACTIONS = {"DISCOVERY": (0.0, 0.6), "VALIDATION": (0.6, 0.8), "HOLDOUT": (0.8, 1.0)}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

HOLDOUT_ANALYTICS_READ = False


# ---------------------------------------------------------------------------
# raw canonical loaders
# ---------------------------------------------------------------------------


def _npz(path: Path) -> dict[str, NDArray[Any]]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def load_spot(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(CACHE_DIR / f"spot_{asset}.npz")


def load_funding(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(CACHE_DIR / f"funding_{asset}.npz")


def load_perp(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(POS_CACHE_DIR / f"klines_{asset}.npz")


def load_metrics(asset: str) -> dict[str, NDArray[Any]]:
    return _npz(POS_CACHE_DIR / f"metrics_{asset}.npz")


# ---------------------------------------------------------------------------
# as-of join + rolling primitives
# ---------------------------------------------------------------------------


def _asof(times: NDArray[Any], values: NDArray[Any], decisions: NDArray[Any]) -> NDArray[Any]:
    """Backward / as-of join: latest value with time <= decision (ms)."""
    order = np.argsort(times, kind="mergesort")
    t = times[order].tolist()
    v = values[order]
    out = np.full(decisions.shape, np.nan, dtype=np.float64)
    for k, d in enumerate(decisions.tolist()):
        i = bisect.bisect_right(t, int(d)) - 1
        if i >= 0:
            x = v[i]
            if np.isfinite(x):
                out[k] = x
    return out


def _rolling_mean(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w)
    cnt = finite.sum(axis=1)
    tot = np.where(finite, w, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n - 1 :] = np.where(cnt == n, tot / cnt, np.nan)
    return out


def _rolling_std(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w).sum(axis=1)
    out[n - 1 :] = np.where(finite == n, np.nanstd(w, axis=1), np.nan)
    return out


def _shift(x: NDArray[Any], k: int) -> NDArray[Any]:
    """x shifted right by k (value at i-k), NaN filled."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if k <= 0:
        return x.copy()
    if x.shape[0] > k:
        out[k:] = x[:-k]
    return out


def _mean_of_lag(x: NDArray[Any], k: int) -> NDArray[Any]:
    """Trailing mean over x[i-k .. i-1] (strictly past, excludes x[i])."""
    return _shift(_rolling_mean(x, k), 1)


def _persist_of_lag(x: NDArray[Any], k: int) -> NDArray[Any]:
    """Fraction of x[i-k .. i-1] strictly positive (strictly past)."""
    pos = np.where(np.isfinite(x), (x > 0).astype(np.float64), np.nan)
    m = _rolling_mean(pos, k)
    return _shift(m, 1)


# ---------------------------------------------------------------------------
# carry panel
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CarryPanel:
    """A pooled, PIT-safe carry decision panel (one row per funding period)."""

    ts: NDArray[Any]  # decision time = funding payment time (ms)
    asset: NDArray[Any]
    spot: NDArray[Any]
    perp: NDArray[Any]
    basis: NDArray[Any]  # (perp/spot - 1) * 1e4 bps
    funding: NDArray[Any]  # realized rate paid AT ts (bps)
    features: dict[str, NDArray[Any]]
    fwd_funding: dict[int, NDArray[Any]]  # sum of next h realized rates (bps)
    fwd_basis_pnl: dict[int, NDArray[Any]]  # basis/residual PnL over h (bps)

    def __len__(self) -> int:
        return int(self.ts.shape[0])


def _asset_carry(asset: str) -> dict[str, Any]:
    spot = load_spot(asset)
    perp = load_perp(asset)
    fund = load_funding(asset)
    metr = load_metrics(asset)

    gts = fund["funding_time_ms"].astype(np.int64)
    n = gts.shape[0]

    # 5m bars CLOSED at or before each decision time (as-of, strictly backward).
    s_close_t = spot["open_time_ms"].astype(np.int64) + SRC_MS
    p_close_t = perp["open_time_ms"].astype(np.int64) + SRC_MS
    s_close = _asof(s_close_t, spot["close"], gts)
    p_close = _asof(p_close_t, perp["close"], gts)

    basis = (p_close / s_close - 1.0) * 1e4  # bps
    rate_bps = np.asarray(fund["funding_rate"], dtype=np.float64) * 1e4

    # trailing funding features (strictly past: never the rate paid at ts)
    f_mean_k = _mean_of_lag(rate_bps, FUNDING_MEAN_K)
    f_mean_9 = _mean_of_lag(rate_bps, 9)
    f_mean_21 = _mean_of_lag(rate_bps, 21)
    f_persist_k = _persist_of_lag(rate_bps, FUNDING_MEAN_K)
    f_last = _shift(rate_bps, 1)

    # trailing basis
    b_mean_k = _shift(_rolling_mean(basis, FUNDING_MEAN_K), 1)
    b_last = _shift(basis, 1)

    # trailing realized volatility from the 5m perp closes (24h = 288 bars)
    kts = perp["open_time_ms"].astype(np.int64)
    kc = perp["close"].astype(np.float64)
    ret5 = np.full(kc.shape, np.nan, dtype=np.float64)
    ret5[1:] = kc[1:] / kc[:-1] - 1.0
    rv5 = _rolling_std(ret5, 288)
    vol_real = _asof(kts + SRC_MS, rv5, gts) * 1e4
    vol_z = _zscore(vol_real, 63)

    # positioning context (OI / crowding) as-of
    avail = metr["available_time_ms"].astype(np.int64)
    oi = _asof(avail, metr["sum_open_interest"], gts)
    oi_chg = np.full(oi.shape, np.nan, dtype=np.float64)
    prev = _shift(oi, 3)  # 24h ago (3 periods)
    with np.errstate(invalid="ignore", divide="ignore"):
        oi_chg = np.where(prev > 0, oi / prev - 1.0, np.nan)
    ls_global = _asof(avail, metr["count_long_short_ratio"], gts)
    crowd = np.where(np.isfinite(ls_global), ls_global, np.nan)
    crowd_z = _zscore(crowd, 63)

    feats: dict[str, NDArray[Any]] = {
        "f_mean_k": f_mean_k,
        "f_mean_9": f_mean_9,
        "f_mean_21": f_mean_21,
        "f_persist_k": f_persist_k,
        "f_last": f_last,
        "basis": basis,
        "basis_mean_k": b_mean_k,
        "basis_last": b_last,
        "vol_real": vol_real,
        "vol_z": vol_z,
        "oi_chg": oi_chg,
        "crowd": crowd,
        "crowd_z": crowd_z,
    }

    fwd_funding: dict[int, NDArray[Any]] = {}
    fwd_basis: dict[int, NDArray[Any]] = {}
    for h in sorted(set(HORIZON_PERIODS.values())):
        ff = np.full(n, np.nan, dtype=np.float64)
        fb = np.full(n, np.nan, dtype=np.float64)
        for i in range(n):
            j = i + h
            if j >= n:
                break
            ff[i] = float(np.nansum(rate_bps[i + 1 : j + 1]))
            fb[i] = float((s_close[j] / s_close[i] - p_close[j] / p_close[i]) * 1e4)
        fwd_funding[h] = ff
        fwd_basis[h] = fb

    return {
        "asset": asset,
        "ts": gts,
        "spot": s_close,
        "perp": p_close,
        "basis": basis,
        "funding": rate_bps,
        "features": feats,
        "fwd_funding": fwd_funding,
        "fwd_basis_pnl": fwd_basis,
    }


def _zscore(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(w).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mu = np.nanmean(w, axis=1)
        sd = np.nanstd(w, axis=1)
        good = (finite == n) & (sd > 0)
        out[n - 1 :] = np.where(good, (x[n - 1 :] - mu) / sd, np.nan)
    return out


FEATURE_NAMES = (
    "f_mean_k",
    "f_mean_9",
    "f_mean_21",
    "f_persist_k",
    "f_last",
    "basis",
    "basis_mean_k",
    "basis_last",
    "vol_real",
    "vol_z",
    "oi_chg",
    "crowd",
    "crowd_z",
)


def build_carry_panel(upto: str = "VALIDATION") -> CarryPanel:
    """Build the pooled carry panel, truncated at a split boundary (§12)."""
    per_asset: list[dict[str, Any]] = []
    for ai, asset in enumerate(ASSETS):
        a = _asset_carry(asset)
        n = len(a["ts"])
        cut = n
        if upto == "DISCOVERY":
            cut = int(n * SPLIT_FRACTIONS["DISCOVERY"][1])
        elif upto == "VALIDATION":
            cut = int(n * SPLIT_FRACTIONS["VALIDATION"][1])
        sub = dict(a)
        sub["ts"] = a["ts"][:cut]
        sub["spot"] = a["spot"][:cut]
        sub["perp"] = a["perp"][:cut]
        sub["basis"] = a["basis"][:cut]
        sub["funding"] = a["funding"][:cut]
        sub["features"] = {k: v[:cut] for k, v in a["features"].items()}
        sub["fwd_funding"] = {h: v[:cut] for h, v in a["fwd_funding"].items()}
        sub["fwd_basis_pnl"] = {h: v[:cut] for h, v in a["fwd_basis_pnl"].items()}
        sub["asset_idx"] = np.full(cut, ai, dtype=np.int64)
        per_asset.append(sub)

    feats = {
        name: np.concatenate([a["features"][name] for a in per_asset]) for name in FEATURE_NAMES
    }
    fwd_f = {
        h: np.concatenate([a["fwd_funding"][h] for a in per_asset])
        for h in per_asset[0]["fwd_funding"]
    }
    fwd_b = {
        h: np.concatenate([a["fwd_basis_pnl"][h] for a in per_asset])
        for h in per_asset[0]["fwd_basis_pnl"]
    }
    return CarryPanel(
        ts=np.concatenate([a["ts"] for a in per_asset]),
        asset=np.concatenate([a["asset_idx"] for a in per_asset]),
        spot=np.concatenate([a["spot"] for a in per_asset]),
        perp=np.concatenate([a["perp"] for a in per_asset]),
        basis=np.concatenate([a["basis"] for a in per_asset]),
        funding=np.concatenate([a["funding"] for a in per_asset]),
        features=feats,
        fwd_funding=fwd_f,
        fwd_basis_pnl=fwd_b,
    )


def split_masks(panel: CarryPanel) -> dict[str, NDArray[Any]]:
    """Per-asset fractional chronological split masks (never shuffled)."""
    n = len(panel)
    m_disc = np.zeros(n, dtype=bool)
    m_val = np.zeros(n, dtype=bool)
    m_hold = np.zeros(n, dtype=bool)
    for ai in range(len(ASSETS)):
        idx = np.where(panel.asset == ai)[0]
        if not idx.size:
            continue
        m = idx.size
        d0, d1 = SPLIT_FRACTIONS["DISCOVERY"]
        v0, v1 = SPLIT_FRACTIONS["VALIDATION"]
        h0, h1 = SPLIT_FRACTIONS["HOLDOUT"]
        m_disc[idx[int(m * d0) : int(m * d1)]] = True
        m_val[idx[int(m * v0) : int(m * v1)]] = True
        m_hold[idx[int(m * h0) : int(m * h1)]] = True
    return {"DISCOVERY": m_disc, "VALIDATION": m_val, "HOLDOUT": m_hold}


# ---------------------------------------------------------------------------
# multi-leg accounting (§13-§15)
# ---------------------------------------------------------------------------


def carry_trade(
    spot0: float,
    spot1: float,
    perp0: float,
    perp1: float,
    funding_sum_bps: float,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, float]:
    """Account a single LONG SPOT + SHORT PERP round trip in bps of notional."""
    spot_ret = spot1 / spot0 - 1.0
    perp_ret = perp1 / perp0 - 1.0
    spot_pnl = spot_ret * 1e4
    perp_pnl = -perp_ret * 1e4
    basis_pnl = spot_pnl + perp_pnl
    net = spot_pnl + perp_pnl + funding_sum_bps - cost_bps
    committed = COMMITTED_CAPITAL
    return {
        "spot_pnl_bps": spot_pnl,
        "perp_pnl_bps": perp_pnl,
        "basis_pnl_bps": basis_pnl,
        "funding_pnl_bps": funding_sum_bps,
        "cost_bps": cost_bps,
        "net_bps": net,
        "return_on_committed": (net / 1e4) / committed,
    }


def residual_delta(spot0: float, perp0: float) -> float:
    """Initial net delta of equal (unit) notional legs (should be ~0)."""
    # 1 unit spot long + 1 unit perp short => notional delta = (spot0 - perp0)/spot0
    return (spot0 - perp0) / spot0


# ---------------------------------------------------------------------------
# event-driven strategy simulation (non-overlapping, PIT-clean)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trade:
    asset: int
    entry_idx: int
    exit_idx: int
    entry_ts: int
    exit_ts: int
    funding_pnl_bps: float
    basis_pnl_bps: float
    spot_pnl_bps: float
    perp_pnl_bps: float
    cost_bps: float
    net_bps: float


def simulate_candidate(
    panel: CarryPanel,
    mask: NDArray[Any],
    entry_signal: NDArray[Any],
    horizon_key: str,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any]:
    """Non-overlapping event simulation of one pre-registered candidate.

    ``entry_signal`` must be a boolean array (True = open at that period).
    Trades are opened while flat and held exactly ``h`` periods.  All inputs
    are PIT-safe by construction (signal computed from strictly-past data).
    """
    h = HORIZON_PERIODS[horizon_key]
    trades: list[Trade] = []
    for ai in range(len(ASSETS)):
        idx = np.where((panel.asset == ai) & mask)[0]
        if not idx.size:
            continue
        seg_start, seg_end = int(idx[0]), int(idx[-1]) + 1
        i = seg_start
        while i + h < seg_end:
            if not mask[i] or not bool(entry_signal[i]):
                i += 1
                continue
            j = i + h
            if not mask[j]:
                i += 1
                continue
            vals = (
                panel.spot[i],
                panel.spot[j],
                panel.perp[i],
                panel.perp[j],
                panel.fwd_funding[h][i],
            )
            if not all(np.isfinite(v) for v in vals):
                i += 1  # missing datum excludes the observation — no imputation (§12)
                continue
            acc = carry_trade(
                panel.spot[i],
                panel.spot[j],
                panel.perp[i],
                panel.perp[j],
                panel.fwd_funding[h][i],
                cost_bps,
            )
            trades.append(
                Trade(
                    asset=ai,
                    entry_idx=i,
                    exit_idx=j,
                    entry_ts=int(panel.ts[i]),
                    exit_ts=int(panel.ts[j]),
                    funding_pnl_bps=acc["funding_pnl_bps"],
                    basis_pnl_bps=acc["basis_pnl_bps"],
                    spot_pnl_bps=acc["spot_pnl_bps"],
                    perp_pnl_bps=acc["perp_pnl_bps"],
                    cost_bps=acc["cost_bps"],
                    net_bps=acc["net_bps"],
                )
            )
            i = j + 1  # non-overlapping: next entry after this exit
    nets = np.array([t.net_bps for t in trades], dtype=np.float64)
    if nets.size == 0:
        return {"status": "NO_TRADES", "trades": 0}
    fund = np.array([t.funding_pnl_bps for t in trades], dtype=np.float64)
    basis = np.array([t.basis_pnl_bps for t in trades], dtype=np.float64)
    cost = np.array([t.cost_bps for t in trades], dtype=np.float64)
    roc = nets / 1e4 / COMMITTED_CAPITAL
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else None
    sharpe = _sharpe(roc)
    sortino = _sortino(roc)
    dd = _max_drawdown(np.cumsum(nets))
    order = np.sort(nets)[::-1]
    return {
        "status": "OK",
        "trades": int(nets.size),
        "holding_periods": h,
        "holding_hours": h * 8,
        "mean_funding_bps": float(np.mean(fund)),
        "sum_funding_bps": float(np.sum(fund)),
        "mean_basis_bps": float(np.mean(basis)),
        "sum_basis_bps": float(np.sum(basis)),
        "mean_cost_bps": float(np.mean(cost)),
        "sum_cost_bps": float(np.sum(cost)),
        "net_expectancy_bps": float(np.mean(nets)),
        "net_pnl_bps": float(np.sum(nets)),
        "gross_expectancy_bps": float(np.mean(fund + basis)),
        "win_rate": float(np.mean(nets > 0)),
        "pf": pf,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd_bps": dd,
        "mean_roc": float(np.mean(roc)),
        "sum_roc": float(np.sum(roc)),
        "top1_share": float(order[0] / order.sum()) if order.sum() != 0 else None,
        "top3_share": float(order[:3].sum() / order.sum()) if order.sum() != 0 else None,
        "without_best_mean": float(np.mean(np.sort(nets)[:-1])) if nets.size > 1 else None,
        "funding_share_of_gross": float(np.sum(fund) / (np.sum(fund) + np.sum(basis)))
        if (np.sum(fund) + np.sum(basis)) != 0
        else None,
        "trades_list": trades,
    }


def _sharpe(x: NDArray[Any]) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or np.std(x) == 0:
        return None
    return float(np.mean(x) / np.std(x) * math.sqrt(x.size))


def _sortino(x: NDArray[Any]) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    downside = x[x < 0]
    if downside.size == 0 or np.std(downside) == 0:
        return None
    return float(np.mean(x) / np.std(downside) * math.sqrt(x.size))


def _max_drawdown(cum: NDArray[Any]) -> float:
    cum = np.asarray(cum, dtype=np.float64)
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum)) if cum.size else 0.0


# ---------------------------------------------------------------------------
# statistics primitives
# ---------------------------------------------------------------------------


def _rank(x: NDArray[Any]) -> NDArray[Any]:
    v = np.asarray(x, dtype=np.float64)
    n = v.shape[0]
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64)
    sx = v[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            avg = float((ranks[order[i]] + ranks[order[j]]) / 2.0)
            for kk in range(i, j + 1):
                ranks[order[kk]] = avg
        i = j + 1
    return ranks


def spearman_ic(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 50:
        return None
    rx, ry = _rank(x[m]), _rank(y[m])
    if float(np.std(rx)) == 0.0 or float(np.std(ry)) == 0.0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def quantile_spread(sig: NDArray[Any], fwd: NDArray[Any], q: int = 5) -> dict[str, Any]:
    x = np.asarray(sig, dtype=np.float64)
    y = np.asarray(fwd, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.shape[0]
    if n < q * 20:
        return {"status": "N/A", "n": int(n)}
    order = np.argsort(x, kind="mergesort")
    ys = y[order]
    size = n // q
    means = [float(np.mean(ys[kk * size : (kk + 1) * size])) for kk in range(q)]
    steps = sum(1 for kk in range(q - 1) if means[kk + 1] >= means[kk]) / (q - 1)
    mono = steps if steps >= 0.5 else steps - 1.0
    return {
        "status": "OK",
        "n": int(n),
        "quantile_means_bps": [round(v, 4) for v in means],
        "top_minus_bottom_bps": round(means[-1] - means[0], 4),
        "monotonicity": round(mono, 3),
    }


# ---------------------------------------------------------------------------
# break-even metrics (§38-§39)
# ---------------------------------------------------------------------------


def break_even_funding_bps(horizon_key: str) -> float:
    """Minimum per-period funding rate (bps) for the trade to break even."""
    return ROUND_TRIP_COST_BPS / HORIZON_PERIODS[horizon_key]


def break_even_holding_periods(mean_funding_bps_per_period: float) -> float | None:
    if not math.isfinite(mean_funding_bps_per_period) or mean_funding_bps_per_period <= 0:
        return None
    return ROUND_TRIP_COST_BPS / mean_funding_bps_per_period


def break_even_holding_hours(mean_funding_bps_per_period: float) -> float | None:
    p = break_even_holding_periods(mean_funding_bps_per_period)
    return None if p is None else p * 8.0


# ---------------------------------------------------------------------------
# writers / hashing
# ---------------------------------------------------------------------------


def sha256_obj(obj: Any) -> str:
    import hashlib

    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
