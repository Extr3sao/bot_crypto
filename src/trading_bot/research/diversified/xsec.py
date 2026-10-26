"""ARP-006 DIVERSIFIED ALPHA SEARCH §14-§16 — broader-universe cross-sectional factors.

New experiment identities (the universe materially changes, so EXP-ARP-013/014/015
may **not** be re-run — see §1 and §14):

* ``EXP-ARP-016`` ``H-XSEC-MOM-LONG-002``  cross-sectional momentum (broad universe);
* ``EXP-ARP-017`` ``H-XSEC-REV-002``       cross-sectional reversal (broad universe);
* ``EXP-ARP-018`` ``H-XSEC-LOWVOL-002``    cross-sectional low-volatility (broad universe).

The rotation reuses the frozen, fail-closed
:class:`~trading_bot.research.alpha_expansion.xsec.CrossSectionalSnapshotBuilder`
for ranking synchronization, and gates the candidate set through the PIT
:class:`~trading_bot.research.diversified.universe.DynamicAssetUniverse` first
(listing / history / liquidity / data-quality). Every episode is charged one
ROUND-TRIP cost; the strategy rebalances infrequently so the holding horizon clears
COST_MODEL_V3 by construction. Deterministic: no RNG, no wall-clock.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV
from trading_bot.research.alpha_expansion.strategies import Trade
from trading_bot.research.alpha_expansion.xsec import (
    CrossSectionalSnapshotBuilder,
    SnapshotRequest,
)

from .data import MS_PER_DAY, DailyBar
from .universe import DynamicAssetUniverse, UniverseConfig

__all__ = [
    "XsecUniverseConfig",
    "simulate_universe_xsec",
    "xsec_universe_configs",
]

BPS = 10_000.0


@dataclass(frozen=True, slots=True)
class XsecUniverseConfig:
    """Frozen parameters for one broader-universe cross-sectional rotation."""

    ranking_feature: str
    ranking_window: int
    ascending: bool
    rebalance_days: int
    max_hold_days: int
    min_members: int = 5
    entry_delay_days: int = 0


def xsec_universe_configs() -> dict[str, XsecUniverseConfig]:
    """The three NEW frozen configurations (round values, never tuned on results)."""
    return {
        "EXP-ARP-016": XsecUniverseConfig("trailing_return", 90, False, 5, 30),
        "EXP-ARP-017": XsecUniverseConfig("trailing_return", 7, True, 3, 7),
        "EXP-ARP-018": XsecUniverseConfig("realized_vol", 60, True, 10, 30),
    }


def _to_ohlcv(bars: Sequence[DailyBar]) -> list[OHLCV]:
    return [
        OHLCV(
            symbol=b.symbol, timestamp=b.timestamp, open=b.open, high=b.high,
            low=b.low, close=b.close, volume=b.volume,
        )
        for b in bars
    ]


def simulate_universe_xsec(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    listing_time: Mapping[str, int],
    data_fingerprint: str,
    *,
    config: XsecUniverseConfig,
    cost_bps_rt: float,
    universe_config: UniverseConfig | None = None,
    notional: float = 500.0,
    subset: Sequence[str] | None = None,
) -> tuple[list[Trade], dict[str, int]]:
    """Long-only rotation into the cross-sectional factor leader.

    Returns ``(trades, eligible_count_by_decision)``. ``subset`` restricts the
    corpus (leave-one-asset-out / subset robustness) without changing parameters.
    """
    universe_config = universe_config or UniverseConfig()
    symbols = sorted(subset) if subset is not None else sorted(bars_by_symbol)
    corpus = {s: bars_by_symbol[s] for s in symbols}
    listing = {s: listing_time.get(s, 0) for s in symbols}
    uverse = DynamicAssetUniverse(
        corpus, listing, data_fingerprint, universe_config
    )
    builder = CrossSectionalSnapshotBuilder(min_members=config.min_members)
    index: dict[str, dict[int, DailyBar]] = {
        s: {b.timestamp: b for b in bars} for s, bars in corpus.items()
    }
    if not index:
        return [], {}
    # precompute sorted timestamps + OHLCV once (avoid re-deriving per snapshot)
    stamps: dict[str, list[int]] = {s: [b.timestamp for b in corpus[s]] for s in corpus}
    ohlcv: dict[str, list[OHLCV]] = {s: _to_ohlcv(corpus[s]) for s in corpus}
    calendar = sorted({ts for d in index.values() for ts in d})
    if len(calendar) < 2:
        return [], {}

    fee_usd = notional * cost_bps_rt / BPS
    trades: list[Trade] = []
    eligible_counts: dict[str, int] = {}

    held: str | None = None
    entry_price = 0.0
    entry_ts = 0
    peak = 0.0
    trough = 0.0
    last_rebalance = -10**9
    cap_excluded: str | None = None

    def close(sym: str, exit_price: float, exit_ts: int, reason: str) -> None:
        gross = notional * (exit_price / entry_price - 1.0)
        trades.append(
            Trade(
                side="long", entry_ts=entry_ts, exit_ts=exit_ts,
                entry=round(entry_price, 6), exit=round(exit_price, 6), reason=reason,
                rule=f"xsec2_{sym}", symbol=sym, notional=round(notional, 2),
                gross=round(gross, 4), fees=round(fee_usd, 4), net=round(gross - fee_usd, 4),
                mfe_pct=round((peak - entry_price) / entry_price * 100.0, 4),
                mae_pct=round((entry_price - trough) / entry_price * 100.0, 4),
                duration_min=round((exit_ts - entry_ts) / 60_000.0, 1),
            )
        )

    delay = config.entry_delay_days
    for i in range(len(calendar) - 1):
        day = calendar[i]
        fill_i = i + 1 + delay
        if fill_i >= len(calendar):
            break
        fill_day = calendar[fill_i]
        fill_open = {s: index[s][fill_day].open for s in index if fill_day in index[s]}

        if held is not None and day in index[held]:
            bar = index[held][day]
            peak = max(peak, bar.high)
            trough = min(trough, bar.low)

        do_rebalance = (i - last_rebalance) >= config.rebalance_days
        need_snapshot = do_rebalance or held is None
        snap = None
        if need_snapshot:
            u_snap = uverse.snapshot(day + MS_PER_DAY)
            eligible_counts[str(day + MS_PER_DAY)] = len(u_snap.eligible_assets)
            eligible = u_snap.eligible_assets
            if eligible:
                trimmed = {
                    s: ohlcv[s][: bisect.bisect_right(stamps[s], day)] for s in eligible
                }
                snap = builder.build(
                    trimmed,
                    SnapshotRequest(
                        decision_time=day + MS_PER_DAY,
                        ranking_feature=config.ranking_feature,
                        ranking_window=config.ranking_window,
                        bar_tf_ms=MS_PER_DAY,
                        ascending=config.ascending,
                    ),
                )
            last_rebalance = i

        if held is not None:
            if fill_day not in index[held]:
                continue  # cannot fill the rotation; stay put, no look-ahead
            days_held = (day - entry_ts) // MS_PER_DAY
            still_leader = snap is not None and snap.is_tradeable and snap.leader() == held
            leader = snap.leader() if snap is not None and snap.is_tradeable else None
            cap_hit = days_held >= config.max_hold_days
            if need_snapshot and (cap_hit or (snap is not None and snap.is_tradeable and not still_leader)):
                close(held, fill_open[held], fill_day, "rotate" if not cap_hit else "window_expiry")
                exited = held
                held = None
                if cap_hit and still_leader:
                    cap_excluded = exited
                if leader is not None and leader != cap_excluded and fill_day in index[leader]:
                    held, entry_price, entry_ts = leader, fill_open[leader], fill_day
                    peak = trough = entry_price
                continue
            continue

        if snap is not None and snap.is_tradeable:
            leader = snap.leader()
            if cap_excluded is not None and leader != cap_excluded:
                cap_excluded = None
            if leader is not None and leader != cap_excluded and fill_day in index[leader]:
                held, entry_price, entry_ts = leader, fill_open[leader], fill_day
                peak = trough = entry_price

    if held is not None:
        last_day = calendar[-1]
        if last_day in index[held]:
            close(held, index[held][last_day].close, last_day, "window_expiry")

    return trades, eligible_counts
