"""ARP-005 ALPHA EXPANSION §8-§11 — minimum cross-sectional research infrastructure.

The legacy ``trading_bot.research.cross_sectional.CrossSectionalEngine`` (P19) is
audited in ``CROSS_SECTIONAL_AUDIT.md`` and classified ``BROKEN`` for research use
(orphan, no-op rank assignment, no asset-synchronization/staleness guard, no
tests). It is left untouched. This module implements the **minimum** contract the
experiments require, from scratch, in the research/legacy plane.

Contract (frozen before any result is read):

* **Synchronized universe.** A symbol is eligible only if its most recent bar at
  or before ``decision_time`` shares the *same* feature timestamp as every other
  eligible symbol. A lagging symbol is excluded, never ranked with a staler bar.
* **PIT-safe.** Only bars with ``timestamp <= decision_time`` are read; the
  feature window ends at the decision bar. ``feature_time <= decision_time`` is
  enforced in ``__post_init__`` (fail closed).
* **No future data / duplicates.** A future bar is never read; a duplicated bar
  timestamp excludes the symbol (the series is untrustworthy).
* **Missing / stale data.** Non-contiguous windows and stale series are excluded,
  never interpolated or forward-filled.
* **Deterministic universe and ties.** Eligibility requires an exact feature-
  timestamp match; ties are broken by symbol name, so the order is reproducible.
* **Minimum-universe rule.** Fewer than ``min_members`` eligible assets yields a
  *blocked* snapshot (empty ranking) rather than a guess.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from trading_bot.market_data.types import OHLCV

__all__ = [
    "FEATURES",
    "CrossSectionalError",
    "CrossSectionalSnapshot",
    "CrossSectionalSnapshotBuilder",
    "SnapshotRequest",
]

MS_PER_DAY = 86_400_000


class CrossSectionalError(Exception):
    """Raised when a snapshot violates the frozen PIT/synchronization contract."""


FeatureFn = Callable[[Sequence[OHLCV], int, int], "float | None"]


def _trailing_return(bars: Sequence[OHLCV], window: int, bar_tf_ms: int) -> float | None:
    """Simple return over a day-contiguous trailing window, else ``None``."""
    if window <= 0 or len(bars) <= window:
        return None
    end, start = bars[-1], bars[-1 - window]
    if end.timestamp - start.timestamp != window * bar_tf_ms:
        return None
    if start.close <= 0:
        return None
    return end.close / start.close - 1.0


def _realized_vol(bars: Sequence[OHLCV], window: int, bar_tf_ms: int) -> float | None:
    """Population stdev of the last ``window`` bar-over-bar returns, else ``None``."""
    if window <= 0 or len(bars) <= window:
        return None
    seg = bars[-window - 1 :]
    if seg[-1].timestamp - seg[0].timestamp != window * bar_tf_ms:
        return None
    rets: list[float] = []
    for i in range(1, len(seg)):
        prev = seg[i - 1].close
        if prev <= 0:
            return None
        rets.append(seg[i].close / prev - 1.0)
    if len(rets) != window:
        return None
    return statistics.pstdev(rets)


#: named ranking features (value is "higher == stronger" by default)
FEATURES: dict[str, FeatureFn] = {
    "trailing_return": _trailing_return,
    "realized_vol": _realized_vol,
}


@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    """A frozen description of one cross-sectional ranking decision."""

    decision_time: int
    ranking_feature: str
    ranking_window: int
    bar_tf_ms: int = MS_PER_DAY
    ascending: bool = False  # True => the smallest value ranks best


@dataclass(frozen=True, slots=True)
class CrossSectionalSnapshot:
    """A PIT-safe cross-sectional ranking at one decision timestamp (§10)."""

    decision_time: int
    assets: tuple[str, ...]
    feature_time: int
    ranking_feature: str
    ranking_window: int
    ranks: Mapping[str, int]
    eligible_assets: tuple[str, ...]
    excluded_assets: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]
    values: Mapping[str, float]
    min_members: int
    ascending: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if self.feature_time > self.decision_time:
            raise CrossSectionalError(
                f"feature_time {self.feature_time} is after decision_time {self.decision_time}"
            )
        if set(self.ranks) != set(self.eligible_assets):
            raise CrossSectionalError("ranks must cover exactly the eligible assets")
        if self.ranks:
            ordered = sorted(self.ranks.values())
            if ordered != list(range(1, len(ordered) + 1)):
                raise CrossSectionalError("ranks must be a 1..N permutation")

    @property
    def is_tradeable(self) -> bool:
        """True only when at least ``min_members`` assets were ranked."""
        return len(self.eligible_assets) >= self.min_members and bool(self.ranks)

    def ranking(self) -> tuple[str, ...]:
        """Eligible symbols ordered best -> worst (deterministic)."""
        if not self.ranks:
            return ()
        return tuple(sorted(self.ranks, key=lambda s: (self.ranks[s], s)))

    def leader(self) -> str | None:
        r = self.ranking()
        return r[0] if r else None

    def rank_of(self, symbol: str) -> int | None:
        return self.ranks.get(symbol)


class CrossSectionalSnapshotBuilder:
    """Builds fail-closed :class:`CrossSectionalSnapshot` values (research-only)."""

    def __init__(self, min_members: int = 2) -> None:
        if min_members < 2:
            raise ValueError("min_members must be >= 2")
        self.min_members = min_members

    def build(
        self,
        bars_by_symbol: Mapping[str, Sequence[OHLCV]],
        request: SnapshotRequest,
    ) -> CrossSectionalSnapshot:
        if request.ranking_feature not in FEATURES:
            raise CrossSectionalError(f"unknown ranking feature {request.ranking_feature!r}")
        feature_fn = FEATURES[request.ranking_feature]
        min_members = self.min_members
        assets = tuple(sorted(bars_by_symbol))

        excluded: dict[str, str] = {}
        survivors: dict[str, tuple[int, Sequence[OHLCV]]] = {}
        for symbol in assets:
            usable = [b for b in bars_by_symbol[symbol] if b.timestamp <= request.decision_time]
            if not usable:
                excluded[symbol] = "no_data"
                continue
            stamps = [b.timestamp for b in usable]
            if len(stamps) != len(set(stamps)):
                excluded[symbol] = "duplicate_bar"
                continue
            last = usable[-1].timestamp
            if last > request.decision_time:  # defensive; cannot happen after filter
                excluded[symbol] = "future_bar"
                continue
            if request.decision_time - last > request.bar_tf_ms:
                excluded[symbol] = "stale"
                continue
            survivors[symbol] = (last, usable)

        if not survivors:
            return self._blocked(request, assets, excluded, 0, "no_data")

        feature_time = max(last for last, _ in survivors.values())
        values: dict[str, float] = {}
        for symbol, (last, usable_bars) in sorted(survivors.items()):
            if last != feature_time:
                excluded[symbol] = "unsynchronized"
                continue
            value = feature_fn(usable_bars, request.ranking_window, request.bar_tf_ms)
            if value is None:
                excluded[symbol] = "insufficient_history"
                continue
            values[symbol] = value

        eligible = tuple(sorted(values))
        if len(eligible) < min_members:
            for symbol in eligible:
                excluded[symbol] = "insufficient_universe"
            return self._blocked(
                request, assets, excluded, min_members, "insufficient_universe", feature_time
            )

        ordered = sorted(eligible, key=lambda s: (values[s], s) if request.ascending else (-values[s], s))
        ranks = {symbol: i + 1 for i, symbol in enumerate(ordered)}
        return CrossSectionalSnapshot(
            decision_time=request.decision_time,
            assets=assets,
            feature_time=feature_time,
            ranking_feature=request.ranking_feature,
            ranking_window=request.ranking_window,
            ranks=ranks,
            eligible_assets=eligible,
            excluded_assets=tuple(sorted(excluded)),
            exclusion_reasons=dict(excluded),
            values=values,
            min_members=min_members,
            ascending=request.ascending,
        )

    def _blocked(
        self,
        request: SnapshotRequest,
        assets: tuple[str, ...],
        excluded: dict[str, str],
        min_members: int,
        reason: str,
        feature_time: int = 0,
    ) -> CrossSectionalSnapshot:
        # feature_time must never exceed decision_time; clamp defensively.
        safe_feature_time = min(feature_time, request.decision_time)
        return CrossSectionalSnapshot(
            decision_time=request.decision_time,
            assets=assets,
            feature_time=safe_feature_time,
            ranking_feature=request.ranking_feature,
            ranking_window=request.ranking_window,
            ranks={},
            eligible_assets=(),
            excluded_assets=tuple(sorted(excluded)),
            exclusion_reasons=dict(excluded),
            values={},
            min_members=min_members,
            ascending=request.ascending,
            blocked_reason=reason,
        )
