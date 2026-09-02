"""Cross-Sectional Support (P19).

Enables strategies that use the ENTIRE universe simultaneously:
- Relative momentum: compare assets against each other
- Rank: rank assets by metric
- Dispersion: measure spread across universe
- Top/bottom quantile selection

P19 contract:
- Cross-sectional analysis at time T uses ONLY data available at time T.
- No lookahead: rankings use past data, not future data.
- Multiple assets processed in a single chronological pass.
- LONG and SHORT can select from different quantiles.

Design:
- CrossSectionalEngine is standalone — families query it for rankings.
- Each metric is computed independently (no coupling).
- Results are descriptive features, not operational rules (P7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from trading_bot.market_data.types import OHLCV

# ---------------------------------------------------------------------------
# Cross-Sectional Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetMetric:
    """A single asset's cross-sectional metric at a point in time."""

    symbol: str
    timestamp: int
    metric_name: str
    value: float
    rank: int | None = None  # 1 = highest
    percentile: float | None = None  # 0.0 - 1.0


@dataclass(frozen=True, slots=True)
class CrossSectionalSnapshot:
    """Result of cross-sectional analysis at a single timestamp."""

    timestamp: int
    universe_size: int
    metrics: dict[str, list[AssetMetric]]  # metric_name -> [per-asset values]
    rankings: dict[str, list[str]]  # metric_name -> [symbols ranked best to worst]
    dispersion: dict[str, float]  # metric_name -> dispersion value

    def get_rank(self, metric_name: str, symbol: str) -> int | None:
        """Get rank of a symbol for a metric (1 = best)."""
        ranking = self.rankings.get(metric_name, [])
        try:
            return ranking.index(symbol) + 1
        except ValueError:
            return None

    def get_percentile(self, metric_name: str, symbol: str) -> float | None:
        """Get percentile of a symbol for a metric (1.0 = top)."""
        ranking = self.rankings.get(metric_name, [])
        if not ranking or symbol not in ranking:
            return None
        rank = ranking.index(symbol) + 1
        return 1.0 - (rank - 1) / max(1, len(ranking) - 1) if len(ranking) > 1 else 1.0


# ---------------------------------------------------------------------------
# Quantile Selection
# ---------------------------------------------------------------------------

QuantileSide = Literal["TOP", "BOTTOM"]


@dataclass(frozen=True, slots=True)
class QuantileSelection:
    """Result of quantile-based selection."""

    metric_name: str
    side: QuantileSide
    quantile_pct: float  # e.g. 0.2 = top 20% or bottom 20%
    selected: list[str]  # symbols in the quantile
    timestamp: int


# ---------------------------------------------------------------------------
# Cross-Sectional Engine
# ---------------------------------------------------------------------------


class CrossSectionalEngine:
    """Cross-sectional analysis engine (P19).

    Computes metrics across the entire universe at each timestamp.
    Families query this for rankings, quantiles, and dispersion.

    P19 contract:
    - Uses ONLY data available at the timestamp.
    - No lookahead: uses past data only.
    - Multiple metrics computed independently.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("cross_sectional")

    def analyze(
        self,
        candles_by_symbol: dict[str, list[OHLCV]],
        timestamp: int,
        lookback: int = 20,
    ) -> CrossSectionalSnapshot:
        """Compute cross-sectional metrics for all symbols at a timestamp.

        Args:
            candles_by_symbol: {symbol: [candles in chronological order]}
            timestamp: current timestamp to analyze
            lookback: how many past candles to use per symbol

        Returns:
            CrossSectionalSnapshot with metrics, rankings, dispersion
        """
        # Build per-symbol lookback windows (NO lookahead)
        lookbacks: dict[str, list[OHLCV]] = {}
        for symbol, candles in candles_by_symbol.items():
            window = [c for c in candles if c.timestamp <= timestamp][-lookback:]
            if len(window) >= 2:
                lookbacks[symbol] = window

        if not lookbacks:
            return CrossSectionalSnapshot(
                timestamp=timestamp,
                universe_size=0,
                metrics={},
                rankings={},
                dispersion={},
            )

        universe_size = len(lookbacks)

        # Compute metrics for each symbol
        momentum_metrics = self._compute_momentum(lookbacks, timestamp)
        returns_metrics = self._compute_returns(lookbacks, timestamp)
        volatility_metrics = self._compute_volatility(lookbacks, timestamp)
        volume_metrics = self._compute_volume_ratio(lookbacks, timestamp)

        all_metrics: dict[str, list[AssetMetric]] = {
            "momentum": momentum_metrics,
            "returns": returns_metrics,
            "volatility": volatility_metrics,
            "volume_ratio": volume_metrics,
        }

        # Build rankings
        rankings: dict[str, list[str]] = {}
        for name, metric_list in all_metrics.items():
            sorted_assets = sorted(metric_list, key=lambda m: m.value, reverse=True)
            rankings[name] = [m.symbol for m in sorted_assets]

        # Compute rankings and percentiles on metric lists
        for _name, metric_list in all_metrics.items():
            self._assign_ranks(metric_list, universe_size)

        # Compute dispersion
        dispersion: dict[str, float] = {}
        for name, metric_list in all_metrics.items():
            values = [m.value for m in metric_list]
            dispersion[name] = self._compute_dispersion(values)

        return CrossSectionalSnapshot(
            timestamp=timestamp,
            universe_size=universe_size,
            metrics=all_metrics,
            rankings=rankings,
            dispersion=dispersion,
        )

    def select_quantile(
        self,
        snapshot: CrossSectionalSnapshot,
        metric_name: str,
        side: QuantileSide,
        quantile_pct: float = 0.2,
    ) -> QuantileSelection:
        """Select top or bottom quantile of assets by metric.

        Args:
            snapshot: cross-sectional snapshot
            metric_name: which metric to use
            side: TOP or BOTTOM
            quantile_pct: fraction of universe to select (0.2 = 20%)

        Returns:
            QuantileSelection with selected symbols
        """
        ranking = snapshot.rankings.get(metric_name, [])
        n_select = max(1, int(len(ranking) * quantile_pct))

        if side == "TOP":
            selected = ranking[:n_select]
        else:
            selected = ranking[-n_select:] if n_select <= len(ranking) else ranking

        return QuantileSelection(
            metric_name=metric_name,
            side=side,
            quantile_pct=quantile_pct,
            selected=selected,
            timestamp=snapshot.timestamp,
        )

    def compute_relative_momentum(
        self,
        candles_by_symbol: dict[str, list[OHLCV]],
        timestamp: int,
        short_lookback: int = 5,
        long_lookback: int = 20,
    ) -> dict[str, float]:
        """Compute relative momentum (short vs long) for all symbols.

        Relative momentum = short_return / long_return
        Positive = outperforming, Negative = underperforming.

        Uses only data available at `timestamp` (no lookahead).
        """
        result: dict[str, float] = {}

        for symbol, candles in candles_by_symbol.items():
            window = [c for c in candles if c.timestamp <= timestamp]
            if len(window) < long_lookback:
                continue

            short_window = window[-short_lookback:]
            long_window = window[-long_lookback:]

            short_return = (short_window[-1].close - short_window[0].open) / short_window[0].open if short_window[0].open > 0 else 0.0
            long_return = (long_window[-1].close - long_window[0].open) / long_window[0].open if long_window[0].open > 0 else 0.0

            if abs(long_return) > 1e-10:
                result[symbol] = short_return / long_return
            else:
                result[symbol] = 0.0

        return result

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

    def _compute_momentum(
        self,
        lookbacks: dict[str, list[OHLCV]],
        timestamp: int,
    ) -> list[AssetMetric]:
        """Compute momentum (return over lookback) for each symbol."""
        metrics: list[AssetMetric] = []
        for symbol, candles in lookbacks.items():
            if len(candles) < 2:
                continue
            start_price = candles[0].open
            end_price = candles[-1].close
            momentum = (end_price - start_price) / start_price if start_price > 0 else 0.0
            metrics.append(AssetMetric(
                symbol=symbol,
                timestamp=timestamp,
                metric_name="momentum",
                value=momentum,
            ))
        return metrics

    def _compute_returns(
        self,
        lookbacks: dict[str, list[OHLCV]],
        timestamp: int,
    ) -> list[AssetMetric]:
        """Compute latest bar return for each symbol."""
        metrics: list[AssetMetric] = []
        for symbol, candles in lookbacks.items():
            if len(candles) < 1:
                continue
            c = candles[-1]
            ret = (c.close - c.open) / c.open if c.open > 0 else 0.0
            metrics.append(AssetMetric(
                symbol=symbol,
                timestamp=timestamp,
                metric_name="returns",
                value=ret,
            ))
        return metrics

    def _compute_volatility(
        self,
        lookbacks: dict[str, list[OHLCV]],
        timestamp: int,
    ) -> list[AssetMetric]:
        """Compute volatility (std of returns) for each symbol."""
        metrics: list[AssetMetric] = []
        for symbol, candles in lookbacks.items():
            if len(candles) < 3:
                continue
            returns = []
            for i in range(1, len(candles)):
                if candles[i - 1].close > 0:
                    returns.append((candles[i].close - candles[i - 1].close) / candles[i - 1].close)
            if len(returns) < 2:
                continue
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            vol = variance ** 0.5
            metrics.append(AssetMetric(
                symbol=symbol,
                timestamp=timestamp,
                metric_name="volatility",
                value=vol,
            ))
        return metrics

    def _compute_volume_ratio(
        self,
        lookbacks: dict[str, list[OHLCV]],
        timestamp: int,
    ) -> list[AssetMetric]:
        """Compute volume ratio (latest vs average) for each symbol."""
        metrics: list[AssetMetric] = []
        for symbol, candles in lookbacks.items():
            if len(candles) < 3:
                continue
            avg_vol = sum(c.volume for c in candles[:-1]) / max(1, len(candles) - 1)
            latest_vol = candles[-1].volume
            ratio = latest_vol / avg_vol if avg_vol > 0 else 1.0
            metrics.append(AssetMetric(
                symbol=symbol,
                timestamp=timestamp,
                metric_name="volume_ratio",
                value=ratio,
            ))
        return metrics

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assign_ranks(self, metrics: list[AssetMetric], universe_size: int) -> None:
        """Assign ranks and percentiles to metric list.

        Rankings are computed from sorted order in the caller.
        Frozen dataclass prevents in-place rank assignment.
        The caller uses the rankings dict for symbol order.
        """
        # No-op: rankings are built in analyze() via sorted order

    def _compute_dispersion(self, values: list[float]) -> float:
        """Compute dispersion (coefficient of variation) of values."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        if abs(mean) < 1e-10:
            return 0.0
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        result: float = (variance ** 0.5) / abs(mean)
        return result


__all__ = [
    "AssetMetric",
    "CrossSectionalEngine",
    "CrossSectionalSnapshot",
    "QuantileSelection",
    "QuantileSide",
]
