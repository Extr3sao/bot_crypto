"""ARP-005 PATH B — minimal PIT-safe cross-sectional ranking (research-only).

ARP-004's audit classified ``trading_bot.research.cross_sectional.CrossSectionalEngine``
as ``ORPHAN`` (zero callers, no-op ``_assign_ranks`` so ``rank``/``percentile`` are
always ``None``, no asset-synchronization or staleness guard, no tests). EXP-ARP-009
therefore needs a **minimum reproducible** cross-sectional ranker. This module
implements that minimum from scratch — it does **not** repair or adopt the legacy
engine, whose P19 API stays untouched (research/legacy contract).

Contract (frozen before any result is read):

* **Asset synchronization.** A symbol participates in a snapshot only if it has a
  daily bar whose timestamp is *exactly* the rebalance timestamp. A lagging symbol
  is excluded and reported, never silently ranked with a staler bar.
* **PIT-safe.** Only bars with ``ts <= timestamp`` are read; the metric window ends
  at the decision bar. No future membership, no future returns, no future rank.
* **No future data.** ``as_of[symbol]`` records the exact bar timestamp used.
* **Missing data.** Non-contiguous daily windows are excluded, never interpolated.
* **Deterministic ties.** The ranking is sorted by ``(-value, symbol)`` so ties are
  broken by symbol name and the order is reproducible.
* **Reproducible.** Pure function of the supplied bars; no clock, no RNG.

No runtime module imports this package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

__all__ = ["CrossSectionalRanker", "RankedUniverse", "trailing_return"]

MS_PER_DAY = 86_400_000


def trailing_return(bars: Sequence[OHLCV], lookback_days: int) -> float | None:
    """Simple return ``close[-1] / close[-1-lookback] - 1`` over contiguous days.

    Returns ``None`` unless the trailing window is a full, day-contiguous run
    ending at the last bar (so a data gap can never shorten or shift the window).
    """
    if lookback_days <= 0 or len(bars) <= lookback_days:
        return None
    end = bars[-1]
    start = bars[-1 - lookback_days]
    if end.timestamp - start.timestamp != lookback_days * MS_PER_DAY:
        return None
    if start.close <= 0:
        return None
    return end.close / start.close - 1.0


@dataclass(frozen=True, slots=True)
class RankedUniverse:
    """A PIT-safe cross-sectional ranking at one rebalance timestamp."""

    timestamp: int
    lookback_days: int
    metric_name: str
    members: tuple[str, ...]
    as_of: Mapping[str, int]
    values: Mapping[str, float]
    ranking: tuple[str, ...]
    stale_excluded: tuple[str, ...]

    def leader(self) -> str | None:
        return self.ranking[0] if self.ranking else None

    def rank_of(self, symbol: str) -> int | None:
        try:
            return self.ranking.index(symbol) + 1
        except ValueError:
            return None


class CrossSectionalRanker:
    """Minimal, deterministic, PIT-safe cross-sectional ranker (research-only)."""

    def __init__(self, min_members: int = 2) -> None:
        if min_members < 2:
            raise ValueError("min_members must be >= 2")
        self.min_members = min_members

    def rank(
        self,
        bars_by_symbol: Mapping[str, Sequence[OHLCV]],
        timestamp: int,
        lookback_days: int,
    ) -> RankedUniverse:
        """Rank the synchronized members by trailing ``lookback_days`` return.

        A symbol participates only when its last closed bar is *exactly* at
        ``timestamp`` and a day-contiguous ``lookback_days`` window is available.
        """
        as_of: dict[str, int] = {}
        values: dict[str, float] = {}
        excluded: list[str] = []
        for symbol in sorted(bars_by_symbol):
            bars = bars_by_symbol[symbol]
            usable = [b for b in bars if b.timestamp <= timestamp]
            if not usable or usable[-1].timestamp != timestamp:
                excluded.append(symbol)  # stale or absent at the rebalance time
                continue
            ret = trailing_return(usable, lookback_days)
            if ret is None:
                excluded.append(symbol)  # not enough contiguous history
                continue
            as_of[symbol] = usable[-1].timestamp
            values[symbol] = ret

        members = tuple(sorted(values))
        if len(members) < self.min_members:
            return RankedUniverse(
                timestamp=timestamp,
                lookback_days=lookback_days,
                metric_name="trailing_return",
                members=members,
                as_of=as_of,
                values=values,
                ranking=(),
                stale_excluded=tuple(excluded),
            )

        ranking = tuple(sorted(members, key=lambda s: (-values[s], s)))
        return RankedUniverse(
            timestamp=timestamp,
            lookback_days=lookback_days,
            metric_name="trailing_return",
            members=members,
            as_of=as_of,
            values=values,
            ranking=ranking,
            stale_excluded=tuple(excluded),
        )
