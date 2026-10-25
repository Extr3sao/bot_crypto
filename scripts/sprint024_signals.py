"""RFC-024 — directional signals conditioned on reproducible volatility events.

Every generator is a PURE function of the bundle at bar ``i`` using bars ``<= i``
only (the shared ``_vol_shock`` detector and all context features are PIT). The
conditioning event is the volatility shock that RFC-023 proved carries
*reproducible magnitude* information (``vol_shock_continuation`` /
``vol_shock_reversion``). No new volatility detector is introduced here; the
detector is imported from the frozen Sprint 002 signal module.

Each function returns an int8 array aligned to the bar axis with values in
{-1, 0, +1}. Execution is handled by the engine at the OPEN of bar ``i + 1``.
The directional *question* (which sign) is the only thing that differs between
hypotheses: continuation, reversion, confirmation, relative strength, volume
participation and range location.

Cross-asset relative strength needs more than one series and is exposed
separately (``xsec_shock_signal``); it is consumed by the pipeline, not by the
single-asset engine.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import sprint002_signals as S
from numpy.typing import NDArray
from sprint002_lib import Bundle


def _empty(b: Bundle) -> NDArray[Any]:
    return np.zeros(len(b), dtype=np.int8)


def shock_event(b: Bundle) -> NDArray[Any]:
    """The RFC-023 reproducible volatility shock (imported, never redefined)."""
    return np.asarray(S._vol_shock(b), dtype=bool)


# ---------------------------------------------------------------------------
# A. PRE-EVENT TREND
# ---------------------------------------------------------------------------


def sig_shock_trend_continuation(b: Bundle) -> NDArray[Any]:
    """Shock aligned with the prevailing EMA trend -> continuation.

    Mechanism: a shock that agrees with the established trend is informed
    positioning, not a liquidity sweep.
    """
    sig = _empty(b)
    shock = shock_event(b)
    up = shock & (b.ret1 > 0) & (b.ema9 > b.ema21)
    dn = shock & (b.ret1 < 0) & (b.ema9 < b.ema21)
    sig[up] = 1
    sig[dn] = -1
    return sig


def sig_shock_trend_reversion(b: Bundle) -> NDArray[Any]:
    """Counter-trend shock inside an established trend -> reversion to trend.

    Mechanism: a down-shock while the trend is up is a liquidity grab; the trend
    resumes, so the trade goes WITH the trend, opposite to the shock bar.
    """
    sig = _empty(b)
    shock = shock_event(b)
    up = shock & (b.ret1 < 0) & (b.ema9 > b.ema21)
    dn = shock & (b.ret1 > 0) & (b.ema9 < b.ema21)
    sig[up] = 1
    sig[dn] = -1
    return sig


# ---------------------------------------------------------------------------
# B. POST-SHOCK PRICE RESPONSE
# ---------------------------------------------------------------------------


def sig_shock_confirm_followthrough(b: Bundle) -> NDArray[Any]:
    """Shock, then a confirming bar that continues beyond the shock close.

    Mechanism: a confirming follow-through bar filters absorbed/one-bar shocks
    and selects the ones with genuine flow; the trade joins after confirmation.
    Entry is at the OPEN of the bar after the confirming bar.
    """
    sig = _empty(b)
    shock = shock_event(b)
    c = b.bars.c
    for i in range(1, len(b)):
        if not bool(shock[i - 1]):
            continue
        r = float(b.ret1[i - 1])
        prev_c = float(c[i - 1])
        if not np.isfinite(r) or prev_c <= 0.0:
            continue
        if r > 0 and float(c[i]) > prev_c:
            sig[i] = 1
        elif r < 0 and float(c[i]) < prev_c:
            sig[i] = -1
    return sig


# ---------------------------------------------------------------------------
# C. MARKET RELATIVE STRENGTH (cross-asset)
# ---------------------------------------------------------------------------


def xsec_shock_signal(bundles: dict[str, Bundle], ret_w: int = 20) -> dict[str, NDArray[Any]]:
    """Shock on the strongest / weakest major -> continuation of relative strength.

    Ranked on the trailing ``ret[ret_w]`` at the shock bar (PIT). The shock asset
    is traded LONG when it is the strongest of the complex and SHORT when it is
    the weakest; the middle name is not traded.
    """
    ts_sets = [{int(t) for t in b.bars.ts} for b in bundles.values()]
    common = sorted(set.intersection(*ts_sets)) if ts_sets else []
    idx = {a: {int(t): k for k, t in enumerate(b.bars.ts)} for a, b in bundles.items()}
    out: dict[str, NDArray[Any]] = {a: _empty(b) for a, b in bundles.items()}
    for t in common:
        rets: list[tuple[str, float]] = []
        for a, b in bundles.items():
            k = idx[a][t]
            r = float(b.ret[ret_w][k])
            rets.append((a, r if np.isfinite(r) else float("-inf")))
        ranked = sorted(rets, key=lambda x: -x[1])
        for rank, (a, _r) in enumerate(ranked, start=1):
            k = idx[a][t]
            if not bool(shock_event(bundles[a])[k]):
                continue
            if rank == 1:
                out[a][k] = 1
            elif rank == len(ranked):
                out[a][k] = -1
    return out


# ---------------------------------------------------------------------------
# E. VOLATILITY + LIQUIDITY RESPONSE
# ---------------------------------------------------------------------------


def sig_shock_volume_continuation(b: Bundle, q: float = 0.90) -> NDArray[Any]:
    """Shock backed by abnormal participation (volume rank) -> continuation.

    Mechanism: a shock that also prints an unusually high volume percentile is
    real participation, not a thin-book print.
    """
    sig = _empty(b)
    shock = shock_event(b)
    vr = b.vol_rank[120]
    hot = np.isfinite(vr) & (vr >= q)
    up = shock & hot & (b.ret1 > 0)
    dn = shock & hot & (b.ret1 < 0)
    sig[up] = 1
    sig[dn] = -1
    return sig


# ---------------------------------------------------------------------------
# F. VOLATILITY + RANGE LOCATION
# ---------------------------------------------------------------------------


def sig_shock_range_location(
    b: Bundle, w: int = 60, hi: float = 0.75, lo: float = 0.25
) -> NDArray[Any]:
    """Shock at an extreme of the trailing range -> break into new territory.

    Mechanism: a shock arriving at the top/bottom quartile of the trailing range
    resolves range-bound liquidity and continues in the direction of the extreme.
    """
    sig = _empty(b)
    shock = shock_event(b)
    top = b.hh[w]
    bot = b.ll[w]
    span = top - bot
    pos = np.where(np.isfinite(span) & (span > 0), (b.bars.c - bot) / span, np.nan)
    up = shock & np.isfinite(pos) & (pos >= hi)
    dn = shock & np.isfinite(pos) & (pos <= lo)
    sig[up] = 1
    sig[dn] = -1
    return sig


SIG_FN: dict[str, Any] = {
    "shock_trend_continuation": sig_shock_trend_continuation,
    "shock_trend_reversion": sig_shock_trend_reversion,
    "shock_confirm_followthrough": sig_shock_confirm_followthrough,
    "shock_volume_continuation": sig_shock_volume_continuation,
    "shock_range_location": sig_shock_range_location,
}

XSEC_SIG = "shock_xsec_relative_strength"

__all__ = [
    "SIG_FN",
    "XSEC_SIG",
    "shock_event",
    "sig_shock_confirm_followthrough",
    "sig_shock_range_location",
    "sig_shock_trend_continuation",
    "sig_shock_trend_reversion",
    "sig_shock_volume_continuation",
    "xsec_shock_signal",
]
