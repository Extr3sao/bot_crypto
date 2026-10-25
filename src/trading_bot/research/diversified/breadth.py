"""ARP-011 EXP-ARP-019 — trend-breadth / market-regime allocation.

Frozen mechanism ``H-BREADTH-REGIME-001`` (``PROJECT_DERIVED_VARIANT``), the
pre-registration in ``docs/research/post_oos_recovery/experiments/EXP-ARP-019/``.

Frozen rule (never tuned on results):

1. ``B_t = share{ asset in PIT-eligible universe : close_t > SMA50_t }`` on
   closed bars only.
2. Eligible universe = PIT-safe :class:`DynamicAssetUniverse`; require
   ``members >= min_members``.
3. Long an equal-weight basket of the eligible universe when ``B_t >= 0.55``;
   flat when ``B_t <= 0.45``; inside the band hold the prior state (hysteresis).
4. Enter/exit at the **next** open (no same-bar fill).
5. One basket position at a time; fixed total notional 500 USD; no compounding;
   a single round-trip cost per basket rebalance (distributed across
   constituents proportionally, so the basket total is one round-trip).

The signal is a *single cross-sectional statistic* (the breadth aggregate), not a
per-asset rule and not asset selection — the traded object is the whole basket.

PIT contract: SMA and breadth read closed bars at or before the decision close;
the fill is the next open. ``max_hold_days`` is honoured as a hard safety cap on
a long episode. Research-only, deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.research.alpha_expansion.strategies import Trade

from .data import MS_PER_DAY, DailyBar
from .universe import DynamicAssetUniverse, UniverseConfig

__all__ = [
    "BreadthConfig",
    "BreadthRecord",
    "breadth_config",
    "breadth_of_day",
    "simulate_breadth_regime",
]

BPS = 10_000.0


@dataclass(frozen=True, slots=True)
class BreadthConfig:
    """Frozen parameters of the breadth gate."""

    lookback_days: int = 50
    entry_breadth: float = 0.55
    exit_breadth: float = 0.45
    min_members: int = 5
    max_hold_days: int = 30
    entry_delay_days: int = 0


@dataclass(frozen=True, slots=True)
class BreadthRecord:
    """Replayable breadth evidence for one decision (§7)."""

    decision_ts: int
    eligible: int
    positive: int
    negative: int
    breadth: float | None
    state: str
    allocation: str
    excluded: int

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_ts": self.decision_ts,
            "eligible": self.eligible,
            "positive": self.positive,
            "negative": self.negative,
            "breadth": None if self.breadth is None else round(self.breadth, 6),
            "state": self.state,
            "allocation": self.allocation,
            "excluded": self.excluded,
        }


def breadth_config(**overrides: object) -> BreadthConfig:
    """Build the frozen config; ``overrides`` exist only for robustness."""
    base: dict[str, object] = {
        "lookback_days": 50,
        "entry_breadth": 0.55,
        "exit_breadth": 0.45,
        "min_members": 5,
        "max_hold_days": 30,
    }
    base.update(overrides)
    return BreadthConfig(**base)  # type: ignore[arg-type]


def _sma_ok(index: Mapping[int, DailyBar], day: int, lookback: int) -> tuple[bool, float]:
    """Trailing SMA over exact closed bars ending at ``day`` (or ``(False, 0)``)."""
    total = 0.0
    for k in range(lookback):
        bar = index.get(day - (lookback - 1 - k) * MS_PER_DAY)
        if bar is None:
            return False, 0.0
        total += bar.close
    return True, total / lookback


def breadth_of_day(
    index_by_symbol: Mapping[str, Mapping[int, DailyBar]],
    day: int,
    eligible: Sequence[str],
    lookback: int,
) -> tuple[int, int]:
    """``(positive, evaluated)`` for the eligible set at ``day`` (PIT-safe)."""
    positive = 0
    evaluated = 0
    for symbol in eligible:
        index = index_by_symbol.get(symbol)
        if index is None:
            continue
        ok, sma = _sma_ok(index, day, lookback)
        if not ok:
            continue
        bar = index.get(day)
        if bar is None:
            continue
        evaluated += 1
        if bar.close > sma:
            positive += 1
    return positive, evaluated


def simulate_breadth_regime(
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    listing_time: Mapping[str, int],
    data_fingerprint: str,
    *,
    config: BreadthConfig,
    cost_bps_rt: float,
    universe_config: UniverseConfig | None = None,
    notional: float = 500.0,
    subset: Sequence[str] | None = None,
) -> tuple[list[Trade], list[BreadthRecord], dict[str, object]]:
    """Run the frozen breadth gate. Returns ``(trades, records, audit)``.

    Trades are emitted per constituent for attribution, each carrying its share
    of the single round-trip cost, so the basket total is one round-trip on the
    fixed notional.
    """
    universe_config = universe_config or UniverseConfig()
    symbols = sorted(subset) if subset is not None else sorted(bars_by_symbol)
    corpus = {s: bars_by_symbol[s] for s in symbols}
    listing = {s: listing_time.get(s, 0) for s in symbols}
    uverse = DynamicAssetUniverse(corpus, listing, data_fingerprint, universe_config)
    index_by_sym: dict[str, dict[int, DailyBar]] = {
        s: {b.timestamp: b for b in bars} for s, bars in corpus.items()
    }
    calendar = sorted({ts for d in index_by_sym.values() for ts in d})
    if len(calendar) < 2:
        return [], [], {"decisions": 0}

    trades: list[Trade] = []
    records: list[BreadthRecord] = []
    state = "FLAT"
    basket: dict[str, tuple[float, float]] = {}  # symbol -> (entry_price, alloc)
    entry_day = 0
    long_days = flat_days = blocked_days = 0

    def exit_price(symbol: str, fill_day: int) -> float | None:
        index = index_by_sym[symbol]
        bar = index.get(fill_day)
        if bar is not None:
            return bar.open
        past = [ts for ts in index if ts <= fill_day]
        if not past:
            return None
        return index[max(past)].close

    def close_basket(fill_day: int, reason: str) -> None:
        for symbol, (entry_price, alloc) in basket.items():
            px = exit_price(symbol, fill_day)
            if px is None or entry_price <= 0:
                continue
            gross = alloc * (px / entry_price - 1.0)
            fee = alloc * cost_bps_rt / BPS
            trades.append(
                Trade(
                    side="long",
                    entry_ts=entry_day,
                    exit_ts=fill_day,
                    entry=round(entry_price, 6),
                    exit=round(px, 6),
                    reason=reason,
                    rule=f"breadth_{symbol}",
                    symbol=symbol,
                    notional=round(alloc, 6),
                    gross=round(gross, 6),
                    fees=round(fee, 6),
                    net=round(gross - fee, 6),
                )
            )

    for i, day in enumerate(calendar):
        fill_i = i + 1 + config.entry_delay_days
        if fill_i >= len(calendar):
            break
        fill_day = calendar[fill_i]
        snapshot = uverse.snapshot(day + MS_PER_DAY)
        eligible = snapshot.eligible_assets
        excluded = len(snapshot.excluded_assets)

        if len(eligible) < config.min_members:
            blocked_days += 1
            records.append(
                BreadthRecord(
                    day + MS_PER_DAY,
                    len(eligible),
                    0,
                    0,
                    None,
                    state,
                    "basket" if state == "LONG" else "flat",
                    excluded,
                )
            )
            continue

        positive, evaluated = breadth_of_day(index_by_sym, day, eligible, config.lookback_days)
        if evaluated < config.min_members:
            blocked_days += 1
            records.append(
                BreadthRecord(
                    day + MS_PER_DAY,
                    len(eligible),
                    positive,
                    0,
                    None,
                    state,
                    "basket" if state == "LONG" else "flat",
                    excluded,
                )
            )
            continue
        breadth = positive / evaluated

        target = state
        if state == "FLAT" and breadth >= config.entry_breadth:
            target = "LONG"
        elif state == "LONG" and breadth <= config.exit_breadth:
            target = "FLAT"
        forced = False
        if state == "LONG" and (day - entry_day) // MS_PER_DAY >= config.max_hold_days:
            target = "FLAT"
            forced = True

        reason = (
            "regime_exit" if state == "LONG" and breadth <= config.exit_breadth else "window_expiry"
        )

        if target != state:
            if state == "LONG":
                close_basket(fill_day, reason)
                basket = {}
            if target == "LONG":
                fillable = [s for s in eligible if index_by_sym[s].get(fill_day) is not None]
                if len(fillable) >= config.min_members:
                    alloc = notional / len(fillable)
                    basket = {
                        s: (index_by_sym[s][fill_day].open, alloc)
                        for s in fillable
                        if index_by_sym[s][fill_day].open > 0.0
                    }
                    entry_day = fill_day
                    state = "LONG"
                else:
                    state = "FLAT"
                    target = "FLAT"
            else:
                state = "FLAT"
            _ = forced

        if state == "LONG":
            long_days += 1
        else:
            flat_days += 1
        records.append(
            BreadthRecord(
                day + MS_PER_DAY,
                len(eligible),
                positive,
                evaluated - positive,
                breadth,
                state,
                "basket" if state == "LONG" else "flat",
                excluded,
            )
        )

    if basket:
        close_basket(calendar[-1], "end_of_sample")
        basket = {}

    audit: dict[str, object] = {
        "decisions": len(records),
        "long_days": long_days,
        "flat_days": flat_days,
        "blocked_days": blocked_days,
        "trades": len(trades),
    }
    return trades, records, audit
