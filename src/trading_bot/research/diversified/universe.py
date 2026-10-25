"""ARP-006 DIVERSIFIED ALPHA SEARCH §2-§9 — the PIT dynamic asset universe.

Research-only, deterministic, fail-closed. Nothing here can size, risk-check,
execute or promote anything; no runtime module imports it.

The universe at decision time ``T`` may use **only** information available at or
before ``T``. An asset that trades today is never assumed to have existed
historically: eligibility is derived from the symbol's own PIT listing time and its
own closed bars. Two explicit exclusion surfaces are produced:

* :class:`DynamicAssetUniverse` — the full universe audit at ``T`` (listing state,
  history, liquidity, data quality), and
* :meth:`DynamicAssetUniverse.snapshot` — the fail-closed *synchronized* subset once
  only assets whose latest usable bar shares the same feature timestamp survive.

Every exclusion is named; nothing is interpolated or forward-filled.
"""

from __future__ import annotations

import bisect
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .data import MS_PER_DAY, SURVIVORSHIP_LIMITATION, DailyBar

__all__ = [
    "DynamicAssetUniverse",
    "UniverseConfig",
    "UniverseError",
    "UniverseSnapshot",
]

UNIVERSE_VERSION = "ARP-006-UNIVERSE-v1"


class UniverseError(Exception):
    """Raised when a snapshot would violate the frozen PIT contract."""


@dataclass(frozen=True, slots=True)
class UniverseConfig:
    """Frozen, pre-declared universe-eligibility rule (never tuned on results)."""

    min_history_days: int = 60
    liquidity_lookback_days: int = 30
    min_median_quote_volume: float = 1_000_000.0
    max_gap_ratio: float = 0.05
    max_stale_days: int = 2
    bar_ms: int = MS_PER_DAY


#: frozen, documented reasons (used verbatim in the exclusion audit)
EXC_NOT_LISTED = "not_yet_listed"
EXC_NO_DATA = "no_data"
EXC_DUPLICATE_BAR = "duplicate_bar"
EXC_INSUFFICIENT_HISTORY = "insufficient_history"
EXC_LIQUIDITY = "liquidity_below_floor"
EXC_GAP_RATIO = "data_quality_gap_ratio"
EXC_STALE = "stale_last_bar"
EXC_UNSYNCHRONIZED = "unsynchronized_feature_time"


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """A PIT-safe universe state at one decision timestamp (§5)."""

    decision_time: int
    eligible_assets: tuple[str, ...]
    excluded_assets: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]
    listing_state: Mapping[str, str]
    history_available: Mapping[str, int]
    liquidity_metric: Mapping[str, float]
    liquidity_timestamp: Mapping[str, int]
    universe_version: str
    data_fingerprint: str
    feature_time: int = 0
    synchronized: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        if self.feature_time > self.decision_time:
            raise UniverseError(
                f"feature_time {self.feature_time} is after decision_time {self.decision_time}"
            )
        if set(self.eligible_assets) & set(self.excluded_assets):
            raise UniverseError("an asset cannot be both eligible and excluded")

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_time": self.decision_time,
            "feature_time": self.feature_time,
            "eligible_assets": list(self.eligible_assets),
            "eligible_count": len(self.eligible_assets),
            "excluded_assets": list(self.excluded_assets),
            "exclusion_reasons": dict(self.exclusion_reasons),
            "listing_state": dict(self.listing_state),
            "history_available": dict(self.history_available),
            "liquidity_metric": dict(self.liquidity_metric),
            "liquidity_timestamp": dict(self.liquidity_timestamp),
            "universe_version": self.universe_version,
            "data_fingerprint": self.data_fingerprint,
            "synchronized": self.synchronized,
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class DynamicAssetUniverse:
    """Builds fail-closed :class:`UniverseSnapshot` values from a daily corpus.

    ``bars_by_symbol`` must map each symbol to its *complete* daily bars. The
    constructor sorts and de-duplicates defensively so a caller cannot silently
    feed an unsorted or duplicated series.
    """

    bars_by_symbol: Mapping[str, Sequence[DailyBar]]
    listing_time: Mapping[str, int]
    data_fingerprint: str
    config: UniverseConfig = field(default_factory=UniverseConfig)
    universe_version: str = UNIVERSE_VERSION
    survivorship_limitation: str = SURVIVORSHIP_LIMITATION

    def __post_init__(self) -> None:
        self._index: dict[str, dict[int, DailyBar]] = {}
        self._stamps: dict[str, list[int]] = {}
        for symbol, bars in self.bars_by_symbol.items():
            ordered = sorted(bars, key=lambda b: b.timestamp)
            self._index[symbol] = {b.timestamp: b for b in ordered}
            self._stamps[symbol] = [b.timestamp for b in ordered]
        self._symbols: tuple[str, ...] = tuple(sorted(self.bars_by_symbol))

    # ------------------------------------------------------------------ helpers

    def _count_at(self, symbol: str, decision_time: int) -> int:
        """Number of bars with ``timestamp <= decision_time`` (bisect O(log n))."""
        return bisect.bisect_right(self._stamps[symbol], decision_time)

    def _median_quote_volume(self, symbol: str, decision_time: int) -> tuple[float, int]:
        """Trailing rolling median quote volume over *closed* bars at or before T."""
        lookback = self.config.liquidity_lookback_days
        index = self._index[symbol]
        stamps = self._stamps[symbol]
        count = self._count_at(symbol, decision_time)
        lo = max(0, count - lookback)
        window = stamps[lo:count]
        if not window:
            return 0.0, 0
        vols = [index[ts].quote_volume for ts in window]
        return float(statistics.median(vols)), window[-1]

    # ------------------------------------------------------------------ snapshot

    def snapshot(self, decision_time: int) -> UniverseSnapshot:
        """Audit the universe at ``decision_time`` and fail closed on synchronization."""
        cfg = self.config
        listing_state: dict[str, str] = {}
        history_available: dict[str, int] = {}
        liquidity_metric: dict[str, float] = {}
        liquidity_timestamp: dict[str, int] = {}
        excluded: dict[str, str] = {}

        for symbol in self._symbols:
            listed_at = self.listing_time.get(symbol, 0)
            if listed_at > decision_time:
                listing_state[symbol] = "NOT_YET_LISTED"
                history_available[symbol] = 0
                excluded[symbol] = EXC_NOT_LISTED
                continue
            listing_state[symbol] = "LISTED"
            stamps = self._stamps[symbol]
            count = bisect.bisect_right(stamps, decision_time)
            history_available[symbol] = count
            if count == 0:
                excluded[symbol] = EXC_NO_DATA
                continue
            if len(stamps) != len(set(stamps)):
                excluded[symbol] = EXC_DUPLICATE_BAR
                continue
            if count < cfg.min_history_days:
                excluded[symbol] = EXC_INSUFFICIENT_HISTORY
                continue
            last = stamps[count - 1]
            # data quality: gap ratio over the asset's own usable span
            span = (last - stamps[0]) // cfg.bar_ms + 1
            if span > 0 and (span - count) / span > cfg.max_gap_ratio:
                excluded[symbol] = EXC_GAP_RATIO
                continue
            # PIT liquidity floor
            median_vol, vol_ts = self._median_quote_volume(symbol, decision_time)
            liquidity_metric[symbol] = median_vol
            liquidity_timestamp[symbol] = vol_ts
            if median_vol < cfg.min_median_quote_volume:
                excluded[symbol] = EXC_LIQUIDITY
                continue
            if (decision_time - last) // cfg.bar_ms > cfg.max_stale_days:
                excluded[symbol] = EXC_STALE
                continue

        candidates = [s for s in self._symbols if s not in excluded]
        if not candidates:
            return UniverseSnapshot(
                decision_time=decision_time,
                eligible_assets=(),
                excluded_assets=tuple(sorted(excluded)),
                exclusion_reasons=dict(excluded),
                listing_state=listing_state,
                history_available=history_available,
                liquidity_metric=liquidity_metric,
                liquidity_timestamp=liquidity_timestamp,
                universe_version=self.universe_version,
                data_fingerprint=self.data_fingerprint,
                feature_time=min(decision_time, 0),
                synchronized=True,
                blocked_reason="no_eligible_assets",
            )

        # §9 synchronization: only assets sharing the max (most recent) usable bar.
        feature_time = max(self._stamps[s][self._count_at(s, decision_time) - 1] for s in candidates)
        eligible: list[str] = []
        for symbol in candidates:
            last = self._stamps[symbol][self._count_at(symbol, decision_time) - 1]
            if last != feature_time:
                excluded[symbol] = EXC_UNSYNCHRONIZED
                continue
            eligible.append(symbol)

        return UniverseSnapshot(
            decision_time=decision_time,
            eligible_assets=tuple(sorted(eligible)),
            excluded_assets=tuple(sorted(excluded)),
            exclusion_reasons=dict(excluded),
            listing_state=listing_state,
            history_available=history_available,
            liquidity_metric=liquidity_metric,
            liquidity_timestamp=liquidity_timestamp,
            universe_version=self.universe_version,
            data_fingerprint=self.data_fingerprint,
            feature_time=feature_time,
            synchronized=True,
        )

    # ------------------------------------------------------------------ census

    def size_series(self, decision_times: Sequence[int]) -> list[int]:
        """Eligible-asset count at each decision time (for the §6 size distribution)."""
        return [len(self.snapshot(t).eligible_assets) for t in decision_times]
