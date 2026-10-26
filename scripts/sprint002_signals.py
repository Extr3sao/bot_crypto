"""RFC-022 Sprint 002 - PIT-safe signal generators.

Every generator returns an int8 array aligned to the bar axis with values in
{-1, 0, +1} decided at the CLOSE of bar i using bars <= i only. Execution is
handled by sprint002_lib.run_spec at the OPEN of bar i+1, so no generator ever
reads a future bar.

Cross-asset hypotheses (cross_sectional_rs, lead_lag) need more than one series
and are exposed separately; they are consumed by the pipeline, not by run_spec.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from sprint002_lib import Bundle, rolling_mean, rolling_rank_pct, shift1


def _empty(b: Bundle) -> NDArray[Any]:
    return np.zeros(len(b), dtype=np.int8)


# ---------------------------------------------------------------------------
# P0
# ---------------------------------------------------------------------------


def sig_compression_breakout(b: Bundle, rank_w: int = 120, level_w: int = 40, q: float = 0.20) -> NDArray[Any]:
    sig = _empty(b)
    comp = b.rank_atr[rank_w] <= q
    lvl_up = shift1(b.hh[level_w])
    lvl_lo = shift1(b.ll[level_w])
    long_ = comp & np.isfinite(lvl_up) & (b.bars.c > lvl_up)
    short = comp & np.isfinite(lvl_lo) & (b.bars.c < lvl_lo)
    sig[long_] = 1
    sig[short] = -1
    return sig


def _squeeze_count(b: Bundle) -> NDArray[Any]:
    """Consecutive bars with Bollinger inside Keltner, ending at each bar."""
    inside = (b.bb_up < b.kc_up) & (b.bb_lo > b.kc_lo)
    out = np.zeros(len(b), dtype=np.int32)
    run = 0
    for i in range(len(b)):
        run = run + 1 if bool(inside[i]) else 0
        out[i] = run
    return out


def sig_squeeze_magnitude(b: Bundle, min_bars: int = 6, width_q: float = 0.25) -> NDArray[Any]:
    sig = _empty(b)
    cnt = _squeeze_count(b)
    width = (b.bb_up - b.bb_lo) / b.bars.c
    wr = rolling_rank_pct(width, 120)
    active = np.zeros(len(b), dtype=bool)
    active[1:] = cnt[:-1] >= min_bars
    tight = np.isfinite(wr) & (wr <= width_q)
    long_ = active & tight & (b.bars.c > b.bb_up)
    short = active & tight & (b.bars.c < b.bb_lo)
    sig[long_] = 1
    sig[short] = -1
    return sig


def sig_vol_contraction_expansion(b: Bundle, rank_w: int = 120, q: float = 0.20) -> NDArray[Any]:
    sig = _empty(b)
    low = b.rank_rv[rank_w] <= q
    rising = np.zeros(len(b), dtype=bool)
    rising[1:] = b.rv20[1:] > b.rv20[:-1]
    up = low & rising & (b.ema9 > b.ema21)
    dn = low & rising & (b.ema9 < b.ema21)
    sig[up] = 1
    sig[dn] = -1
    return sig


# ---------------------------------------------------------------------------
# P1
# ---------------------------------------------------------------------------


def sig_pullback_continuation(
    b: Bundle, touch_w: int = 5, rsi_cap: float = 60.0
) -> NDArray[Any]:
    sig = _empty(b)
    c = b.bars.c
    lo = b.bars.lo
    hi = b.bars.h
    touched_up = np.zeros(len(b), dtype=bool)
    touched_dn = np.zeros(len(b), dtype=bool)
    for i in range(touch_w, len(b)):
        touched_up[i] = bool(np.any(lo[i - touch_w + 1 : i + 1] <= b.ema21[i - touch_w + 1 : i + 1]))
        touched_dn[i] = bool(np.any(hi[i - touch_w + 1 : i + 1] >= b.ema21[i - touch_w + 1 : i + 1]))
    reclaim_up = (c > b.ema9) & (shift1(c) <= shift1(b.ema9))
    reclaim_dn = (c < b.ema9) & (shift1(c) >= shift1(b.ema9))
    up = (b.ema21 > b.ema50) & (b.ema9 > b.ema21) & touched_up & reclaim_up & (b.rsi14 < rsi_cap)
    dn = (b.ema21 < b.ema50) & (b.ema9 < b.ema21) & touched_dn & reclaim_dn & (b.rsi14 > (100.0 - rsi_cap))
    sig[up] = 1
    sig[dn] = -1
    return sig


def sig_breakout_retest(
    b: Bundle, level_w: int = 60, form_gap: int = 21, retest_w: int = 10, tol: float = 0.001
) -> NDArray[Any]:
    sig = _empty(b)
    c = b.bars.c
    lo = b.bars.lo
    hi = b.bars.h
    lvl_up = np.full(len(b), np.nan, dtype=np.float64)
    lvl_lo = np.full(len(b), np.nan, dtype=np.float64)
    lvl_up[form_gap:] = shift1(b.hh[level_w])[form_gap:]
    lvl_lo[form_gap:] = shift1(b.ll[level_w])[form_gap:]
    pending_up: int | None = None
    pending_dn: int | None = None
    for i in range(len(b)):
        if pending_up is not None:
            lvl = float(lvl_up[i])
            if i - pending_up > retest_w:
                pending_up = None
            elif np.isfinite(lvl) and lo[i] <= lvl * (1.0 + tol) and c[i] > lvl:
                sig[i] = 1
                pending_up = None
        if pending_dn is not None:
            lvl = float(lvl_lo[i])
            if i - pending_dn > retest_w:
                pending_dn = None
            elif np.isfinite(lvl) and hi[i] >= lvl * (1.0 - tol) and c[i] < lvl:
                sig[i] = -1
                pending_dn = None
        if sig[i] == 0:
            if np.isfinite(lvl_up[i]) and c[i] > lvl_up[i]:
                pending_up = i
            if np.isfinite(lvl_lo[i]) and c[i] < lvl_lo[i]:
                pending_dn = i
    return sig


def sig_regime_momentum(b: Bundle, ret_w: int = 20, vol_q: float = 0.70) -> NDArray[Any]:
    sig = _empty(b)
    vr = b.vol_rank[120]
    up = (b.ret[ret_w] > 0) & (vr >= vol_q) & (b.bars.c > b.ema21)
    dn = (b.ret[ret_w] < 0) & (vr >= vol_q) & (b.bars.c < b.ema21)
    sig[up] = 1
    sig[dn] = -1
    return sig


def _vol_shock(b: Bundle, rank_w: int = 240, rank_q: float = 0.70, mult: float = 2.5) -> NDArray[Any]:
    """Volatility shock = an unusually large single-bar move relative to its own
    trailing baseline, confirmed by a high ATR percentile.

    The baseline uses bars strictly BEFORE i (shift1), and the ATR percentile
    is PIT, so nothing here reads a future bar. A shock measured on the smoothed
    Wilder ATR itself would be structurally impossible (ATR is an average); the
    shock must be measured on realised per-bar movement.
    """
    abs_ret = np.abs(b.ret1)
    base = shift1(rolling_mean(abs_ret, 20))
    big_bar = np.isfinite(base) & (base > 0) & (abs_ret >= mult * base)
    return np.asarray(big_bar & (b.rank_atr[rank_w] >= rank_q), dtype=bool)


def sig_vol_shock_continuation(b: Bundle) -> NDArray[Any]:
    sig = _empty(b)
    shock = _vol_shock(b)
    up = shock & (b.ret1 > 0)
    dn = shock & (b.ret1 < 0)
    sig[up] = 1
    sig[dn] = -1
    return sig


def sig_vol_shock_reversion(b: Bundle) -> NDArray[Any]:
    sig = _empty(b)
    shock = _vol_shock(b)
    up = shock & (b.ret1 < 0)
    dn = shock & (b.ret1 > 0)
    sig[up] = 1
    sig[dn] = -1
    return sig


def sig_volume_expansion(b: Bundle, vol_q: float = 0.90) -> NDArray[Any]:
    sig = _empty(b)
    vr = b.vol_rank[120]
    up = (vr >= vol_q) & (b.ret1 > 0)
    dn = (vr >= vol_q) & (b.ret1 < 0)
    sig[up] = 1
    sig[dn] = -1
    return sig


def sig_session_conditioning(
    b: Bundle, start_hour: int = 13, end_hour: int = 21, ret_w: int = 5
) -> NDArray[Any]:
    sig = _empty(b)
    hour = ((b.bars.ts // 3_600_000) % 24).astype(np.int64)
    in_session = (hour >= start_hour) & (hour < end_hour)
    up = in_session & (b.ret[ret_w] > 0)
    dn = in_session & (b.ret[ret_w] < 0)
    sig[up] = 1
    sig[dn] = -1
    return sig


# ---------------------------------------------------------------------------
# cross-asset: lead-lag
# ---------------------------------------------------------------------------


def sig_lead_lag(leader: Bundle, follower: Bundle, lag_bars: int, threshold: float = 0.0) -> NDArray[Any]:
    """Follower signal driven by the LEADER's bar at t - lag (never a future bar).

    The leader and follower are aligned on the union of their timestamps; a
    follower bar only receives a signal when the leader has a bar exactly
    ``lag_bars`` earlier, so no interpolation and no forward join is used.
    """
    sig = _empty(follower)
    lead_ts = leader.bars.ts
    lead_ret = leader.ret1
    pos = {int(t): k for k, t in enumerate(lead_ts)}
    tf_ms = follower.tf_min * 60_000
    for i in range(len(follower)):
        t = int(follower.bars.ts[i])
        k = pos.get(t - lag_bars * int(tf_ms))
        if k is None:
            continue
        r = float(lead_ret[k])
        if not np.isfinite(r) or abs(r) <= threshold:
            continue
        sig[i] = 1 if r > 0 else -1
    return sig


# ---------------------------------------------------------------------------
# cross-sectional relative strength (two legs)
# ---------------------------------------------------------------------------


def cross_sectional_ranks(bundles: dict[str, Bundle], ret_w: int = 40) -> dict[str, NDArray[Any]]:
    """Per-asset rank (1 = strongest) of the trailing return, aligned by timestamp."""
    ts_sets = [{int(t) for t in b.bars.ts} for b in bundles.values()]
    common = sorted(set.intersection(*ts_sets)) if ts_sets else []
    idx = {
        a: {int(t): k for k, t in enumerate(b.bars.ts)} for a, b in bundles.items()
    }
    ranks: dict[str, NDArray[Any]] = {
        a: np.full(len(b.bars.ts), np.nan, dtype=np.float64) for a, b in bundles.items()
    }
    for t in common:
        vals: list[tuple[str, float]] = []
        for a, b in bundles.items():
            k = idx[a][t]
            r = float(b.ret[ret_w][k])
            if np.isfinite(r):
                vals.append((a, r))
        if len(vals) < len(bundles):
            continue
        vals.sort(key=lambda x: -x[1])
        for rank, (a, _r) in enumerate(vals, start=1):
            ranks[a][idx[a][t]] = float(rank)
    return ranks


__all__ = [
    "cross_sectional_ranks",
    "sig_breakout_retest",
    "sig_compression_breakout",
    "sig_lead_lag",
    "sig_pullback_continuation",
    "sig_regime_momentum",
    "sig_session_conditioning",
    "sig_squeeze_magnitude",
    "sig_vol_contraction_expansion",
    "sig_vol_shock_continuation",
    "sig_vol_shock_reversion",
    "sig_volume_expansion",
]
