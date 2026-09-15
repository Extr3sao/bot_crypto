"""Deterministic synthetic ARC-01 authorities for pre-execution testing.

These fixtures exist so the frozen discovery implementation can be exercised end-to-end
(decisions, positions, funding cashflow, cost scenarios, gates, controls, reconciliation)
**before** any real economic execution, and without touching the certified authorities.

They are NOT the data authority and are never used by the real run: every value is a pure
closed-form function of the timestamp, so the fixtures are byte-stable across processes.
"""

from __future__ import annotations

import math

from trading_bot.research.arc01.arc01_authority import FundingSeries, Series

SYNTHETIC_BASE_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
FIVE_MIN_MS = 300_000


def _funding_rate(t_ms: int, base_ms: int, spike_every: int = 11) -> float:
    """Deterministic funding rate with periodic extreme settlements.

    The periodic spikes are what the robust-z transform must flag as extremes; the sign
    alternates so both the LONG and the SHORT rule are exercised.
    """
    idx = (t_ms - (base_ms - 70 * DAY_MS)) // (8 * HOUR_MS)
    phase = (t_ms // (8 * HOUR_MS)) % spike_every
    wobble = 0.00012 * math.sin(idx * 0.7)
    if phase == 0:
        return 0.0060 + wobble
    if phase == 5:
        return -0.0060 + wobble
    return 0.00010 * math.sin(idx * 1.3) + 0.00003


def _oi_value(t_ms: int, base_ms: int, base: float = 50_000.0) -> float:
    """Deterministic OI stock with expanding and contracting 24h regimes."""
    day = (t_ms - base_ms) / DAY_MS
    cyc = math.sin(2.0 * math.pi * day / 10.0)
    trend = 0.002 * day
    return base * (1.0 + 0.05 * cyc + trend)


def _price_open(t_ms: int, base_ms: int, base: float = 30_000.0) -> float:
    """Deterministic 1h open price (pure function of the bar open time)."""
    hours = (t_ms - base_ms) / HOUR_MS
    return base * (1.0 + 0.08 * math.sin(2.0 * math.pi * hours / 240.0) + 0.01 * math.sin(hours * 0.37))


def build_synthetic_asset(
    asset: str,
    *,
    base_ms: int = SYNTHETIC_BASE_MS,
    history_days: int = 70,
    window_days: int = 55,
    spike_every: int = 11,
) -> tuple[FundingSeries, Series, Series, int, int]:
    """Return (funding, oi, price, window_start_ms, window_end_ms) for one asset."""
    window_start = base_ms
    window_end = base_ms + window_days * DAY_MS
    f_start = base_ms - history_days * DAY_MS
    f_end = window_end

    ts: list[int] = []
    rates: list[float] = []
    intervals: list[int] = []
    t = f_start
    while t <= f_end:
        ts.append(t + 4)  # provider millisecond jitter, mirroring the certified authority
        rates.append(round(_funding_rate(t, base_ms, spike_every), 10))
        intervals.append(8)
        t += 8 * HOUR_MS
    funding = FundingSeries(asset, tuple(ts), tuple(rates), tuple(intervals), "synthetic", "synthetic://funding", len(ts))

    oi_ts: list[int] = []
    oi_val: list[float] = []
    t = f_start
    while t <= window_end:
        oi_ts.append(t)
        oi_val.append(_oi_value(t, base_ms))
        t += FIVE_MIN_MS
    oi = Series(asset, tuple(oi_ts), tuple(oi_val), "synthetic", "synthetic://oi", len(oi_ts))

    p_ts: list[int] = []
    p_open: list[float] = []
    t = window_start
    while t <= window_end:
        p_ts.append(t)
        p_open.append(_price_open(t, base_ms))
        t += HOUR_MS
    price = Series(asset, tuple(p_ts), tuple(p_open), "synthetic", "synthetic://price", len(p_ts))
    return funding, oi, price, window_start, window_end


def synthetic_authorities(
    assets: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    **kwargs: object,
) -> tuple[dict[str, FundingSeries], dict[str, Series], dict[str, Series]]:
    """Three synthetic assets with identical structure (for whole-pipeline smoke tests)."""
    funding: dict[str, FundingSeries] = {}
    oi: dict[str, Series] = {}
    price: dict[str, Series] = {}
    for a in assets:
        f, o, p, _, _ = build_synthetic_asset(a, **kwargs)  # type: ignore[arg-type]
        funding[a] = f
        oi[a] = o
        price[a] = p
    return funding, oi, price


def synthetic_window(**kwargs: object) -> tuple[int, int]:
    _, _, _, start, end = build_synthetic_asset("BTCUSDT", **kwargs)  # type: ignore[arg-type]
    return start, end


__all__ = [
    "SYNTHETIC_BASE_MS",
    "build_synthetic_asset",
    "synthetic_authorities",
    "synthetic_window",
]
