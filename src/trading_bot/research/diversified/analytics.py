"""ARP-006 DIVERSIFIED ALPHA SEARCH §17,§18,§24,§25 — analytics helpers.

Pure, deterministic. No I/O. Reuses the frozen ARP-002 ``Trade`` shape and the
runtime :class:`~trading_bot.research.regime.RegimeEngine` (the existing
deterministic regime model) so ARP-006's numbers are comparable to earlier phases.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from trading_bot.market_data.types import OHLCV
from trading_bot.research.regime import RegimeEngine

__all__ = [
    "TradeLike",
    "breadth_summary",
    "concentration_by_asset_and_period",
    "pnl_by_asset",
    "pnl_by_year",
    "regime_by_day",
    "top_period_share",
    "universe_size_distribution",
]


class TradeLike(Protocol):
    """The subset of a completed trade the analytics need."""

    net: float
    gross: float
    fees: float
    entry_ts: int
    exit_ts: int
    reason: str
    symbol: str


def _year(ts_ms: int) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).year


def pnl_by_year(trades: Sequence[TradeLike]) -> dict[str, float]:
    out: dict[int, float] = defaultdict(float)
    for t in trades:
        out[_year(t.exit_ts)] += t.net
    return {str(y): round(v, 2) for y, v in sorted(out.items())}


def pnl_by_asset(trades: Sequence[TradeLike]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for t in trades:
        out[t.symbol] += t.net
    return {s: round(v, 2) for s, v in sorted(out.items())}


def _share_by_key(trades: Sequence[TradeLike], key_fn: Any) -> dict[str, float]:
    """Share of total *positive* net attributable to the top bucket of ``key_fn``."""
    pos = [t for t in trades if t.net > 0]
    total = sum(t.net for t in pos)
    if total <= 0:
        return {}
    by: dict[str, float] = defaultdict(float)
    for t in pos:
        by[str(key_fn(t))] += t.net
    top = max(by.values())
    return {"top_share": round(top / total, 4), "keys": len(by)}


def top_period_share(trades: Sequence[TradeLike]) -> dict[str, float]:
    return _share_by_key(trades, lambda t: _year(t.exit_ts))


def concentration_by_asset_and_period(trades: Sequence[TradeLike]) -> dict[str, Any]:
    """§17 concentration surface: trade share + asset/period dominance."""
    nets = [t.net for t in trades]
    pos = sorted((n for n in nets if n > 0), reverse=True)
    total_pos = sum(pos)
    pos_net = [t.net for t in trades if t.net > 0]
    total_pos_net = sum(pos_net)
    asset = _share_by_key(trades, lambda t: t.symbol)
    period = top_period_share(trades)
    return {
        "trades": len(trades),
        "top1_trade_share": round(pos[0] / total_pos, 4) if pos and total_pos > 0 else None,
        "top5_trade_share": round(sum(pos[:5]) / total_pos, 4) if pos and total_pos > 0 else None,
        "top_asset_share": asset.get("top_share"),
        "distinct_assets": asset.get("keys", 0),
        "top_period_share": period.get("top_share"),
        "distinct_periods": period.get("keys", 0),
        "positive_net_usd": round(total_pos_net, 2),
    }


def breadth_summary(universe_sizes: Sequence[int]) -> dict[str, Any]:
    if not universe_sizes:
        return {"min": 0, "median": 0.0, "max": 0, "observations": 0}
    return {
        "observations": len(universe_sizes),
        "min": int(min(universe_sizes)),
        "median": float(statistics.median(universe_sizes)),
        "max": int(max(universe_sizes)),
        "mean": round(statistics.fmean(universe_sizes), 2),
    }


def universe_size_distribution(sizes_by_split: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    return {split: breadth_summary(sizes) for split, sizes in sizes_by_split.items()}


def regime_by_day(benchmark_daily: Sequence[OHLCV], *, lookback: int = 60) -> dict[int, str]:
    """Map each benchmark day to its deterministic primary regime (§25).

    The regime is computed from a trailing window that ends at that day (only
    closed bars), so the label is PIT-safe. ``MIXED``/``TRENDING``/``RANGING``
    primary labels are preserved; the report groups them under a stable taxonomy.
    """
    engine = RegimeEngine()
    days: list[int] = []
    out: dict[int, str] = {}
    for i in range(len(benchmark_daily)):
        if i + 1 < lookback:
            continue
        window = list(benchmark_daily[i + 1 - lookback : i + 1])
        snap = engine.detect(window)
        primary = snap.primary_regime or "UNKNOWN"
        if snap.is_active("BULL"):
            primary = "BULL"
        elif snap.is_active("BEAR"):
            primary = "BEAR"
        elif snap.is_active("HIGH_VOL"):
            primary = "HIGH_VOL"
        elif snap.is_active("LOW_VOL"):
            primary = "LOW_VOL"
        out[benchmark_daily[i].timestamp] = primary
        days.append(benchmark_daily[i].timestamp)
    return out


def regime_pnl(trades: Sequence[TradeLike], regime_by_day_map: Mapping[int, str]) -> dict[str, Any]:
    """Net PnL and trade counts grouped by the entry day's regime."""
    day_ms = 86_400_000
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        day = (t.entry_ts // day_ms) * day_ms
        regime = regime_by_day_map.get(day, "UNKNOWN")
        buckets[regime].append(t.net)
    return {
        regime: {
            "trades": len(v),
            "net_usd": round(sum(v), 2),
            "expectancy_net_bps": round(sum(v) / len(v) / 500.0 * 10_000.0, 3) if v else None,
        }
        for regime, v in sorted(buckets.items())
    }


def exit_mix(trades: Sequence[TradeLike]) -> dict[str, int]:
    return dict(Counter(t.reason for t in trades))
