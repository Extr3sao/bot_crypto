"""ARP-005 ALPHA EXPANSION §13-§19 — cross-sectional factor rotation strategies.

Three orthogonal, cost-compatible mechanisms on the expanded 1d corpus, all using
the §10 :class:`~trading_bot.research.alpha_expansion.xsec.CrossSectionalSnapshot`
contract:

* ``EXP-ARP-013`` ``H-XSEC-MOM-LONG-001``  — momentum (rank by trailing return);
* ``EXP-ARP-014`` ``H-XSEC-REV-001``       — short-horizon reversal (inverse return);
* ``EXP-ARP-015`` ``H-XSEC-LOWVOL-001``    — low-volatility factor (rank by realized vol).

Distinct *mechanisms* (momentum / reversal / low-vol), not variants of one entry:
momentum buys strength, reversal buys weakness, low-vol buys calm. Each rebalances
infrequently, so the holding horizon clears COST_MODEL_V3 by construction.

PIT contract: the ranking decision for day ``D`` reads only bars at ``<= D`` and is
executed at day ``D+1``'s open; the snapshot is therefore built with
``decision_time = D+1`` and a series trimmed to ``<= D`` (``feature_time < D+1``).
The simulator is deterministic (no RNG, no wall-clock).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

from .xsec import CrossSectionalSnapshotBuilder, SnapshotRequest

__all__ = [
    "RotationConfig",
    "SimulationResult",
    "Trade",
    "rotation_configs",
    "simulate_xsec_rotation",
]

BPS = 10_000.0
MS_PER_DAY = 86_400_000


@dataclass(frozen=True, slots=True)
class RotationConfig:
    """Frozen parameters for one cross-sectional factor rotation."""

    ranking_feature: str
    ranking_window: int
    ascending: bool
    rebalance_days: int
    max_hold_days: int
    min_members: int = 2
    entry_delay_days: int = 0  # execution latency (robustness only; can only hurt)


@dataclass(frozen=True, slots=True)
class Trade:
    """One completed rotation episode (BASE-ledger shape, research-only)."""

    side: str
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    reason: str
    rule: str
    symbol: str
    notional: float
    gross: float
    fees: float
    net: float
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    duration_min: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "side": self.side, "entry_ts": self.entry_ts, "exit_ts": self.exit_ts,
            "entry": self.entry, "exit": self.exit, "reason": self.reason, "rule": self.rule,
            "symbol": self.symbol, "notional": self.notional, "gross": self.gross,
            "fees": self.fees, "net": self.net, "mfe_pct": self.mfe_pct,
            "mae_pct": self.mae_pct, "duration_min": self.duration_min,
        }


@dataclass(slots=True)
class SimulationResult:
    trades: list[Trade]
    eval_days: int


def rotation_configs() -> dict[str, RotationConfig]:
    """The three frozen factor configurations (round values, never tuned)."""
    return {
        "EXP-ARP-013": RotationConfig("trailing_return", 90, False, 5, 30),
        "EXP-ARP-014": RotationConfig("trailing_return", 7, True, 3, 7),
        "EXP-ARP-015": RotationConfig("realized_vol", 60, True, 10, 30),
    }


def simulate_xsec_rotation(
    daily_by_symbol: Mapping[str, Sequence[OHLCV]],
    *,
    config: RotationConfig,
    cost_bps_rt: float,
    notional: float = 500.0,
) -> SimulationResult:
    """Long-only rotation into the cross-sectional factor leader.

    The calendar is the intersection of every symbol's daily timestamps, so no
    asset is ever ranked on a stale bar. A rotation closes the current holding and
    opens the new leader at the same next open; ``max_hold_days`` force-exits and
    excludes re-entry into that name until the leader changes. One round-trip cost
    is charged per completed episode.
    """
    builder = CrossSectionalSnapshotBuilder(min_members=config.min_members)
    index: dict[str, dict[int, OHLCV]] = {
        s: {b.timestamp: b for b in bars} for s, bars in daily_by_symbol.items()
    }
    if not index:
        return SimulationResult(trades=[], eval_days=0)
    calendar = sorted(set.intersection(*(set(d) for d in index.values())))
    fee_usd = notional * cost_bps_rt / BPS
    trades: list[Trade] = []

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
                rule=f"xsec_{sym}", symbol=sym, notional=round(notional, 2),
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
        fill_open = {s: index[s][fill_day].open for s in index}

        # mark-to-market extremes while holding (uses the completed day bar)
        if held is not None:
            bar = index[held][day]
            peak = max(peak, bar.high)
            trough = min(trough, bar.low)

        do_rebalance = (i - last_rebalance) >= config.rebalance_days
        need_snapshot = do_rebalance or held is None
        if need_snapshot:
            trimmed = {s: [b for b in daily_by_symbol[s] if b.timestamp <= day] for s in index}
            snap = builder.build(
                trimmed,
                SnapshotRequest(
                    # the decision instant is the moment `day` completes; the fill
                    # (possibly delayed) happens at fill_day's open, still later
                    decision_time=day + MS_PER_DAY,
                    ranking_feature=config.ranking_feature,
                    ranking_window=config.ranking_window,
                    bar_tf_ms=MS_PER_DAY,
                    ascending=config.ascending,
                ),
            )
            last_rebalance = i
        else:
            snap = None

        if held is not None:
            days_held = (day - entry_ts) // MS_PER_DAY
            leader = snap.leader() if snap is not None and snap.is_tradeable else None
            still_leader = snap is not None and snap.is_tradeable and snap.leader() == held
            cap_hit = days_held >= config.max_hold_days
            if need_snapshot and (cap_hit or (snap is not None and snap.is_tradeable and not still_leader)):
                close(held, fill_open[held], fill_day, "rotate" if not cap_hit else "window_expiry")
                exited = held
                held = None
                if cap_hit and still_leader:
                    cap_excluded = exited
                if leader is not None and leader != cap_excluded:
                    held, entry_price, entry_ts = leader, fill_open[leader], fill_day
                    peak = trough = entry_price
                continue
            continue

        # flat: enter the leader at the fill open
        if snap is not None and snap.is_tradeable:
            leader = snap.leader()
            if cap_excluded is not None and leader != cap_excluded:
                cap_excluded = None
            if leader is not None and leader != cap_excluded:
                held, entry_price, entry_ts = leader, fill_open[leader], fill_day
                peak = trough = entry_price

    if held is not None:
        last_day = calendar[-1]
        close(held, index[held][last_day].close, last_day, "window_expiry")

    return SimulationResult(trades=trades, eval_days=len(calendar))
