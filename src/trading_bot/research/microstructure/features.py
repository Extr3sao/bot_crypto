"""Point-in-time microstructure features (§19-20, §32).

A deliberately small, economically interpretable feature set (well under the
20-feature budget). Every feature documents its raw fields, aggregation and
availability window so provenance is auditable (§19).

Availability rule: a feature at index ``i`` uses only bars with index <= ``i``
whose ``available_at <= bars[i].available_at``. No feature may read bar
``i+1`` or a same-timestamp bar that closes later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .types import MicroBar

__all__ = [
    "FEATURE_SPECS",
    "FeatureSpec",
    "flow_features",
    "forward_return_bps",
    "rolling_zscore",
]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Provenance record for a feature (§19)."""

    feature_id: str
    family: str
    source: str
    raw_fields: tuple[str, ...]
    aggregation: str
    window: int
    availability: str


FEATURE_SPECS: dict[str, FeatureSpec] = {
    "flow_imbalance": FeatureSpec(
        feature_id="flow_imbalance",
        family="M-01/ORDER_FLOW",
        source="binance_spot_klines",
        raw_fields=("volume", "taker_buy_base"),
        aggregation="(taker_buy_base - taker_sell_base) / volume, in [-1, 1]",
        window=1,
        availability="bar close",
    ),
    "flow_imbalance_z": FeatureSpec(
        feature_id="flow_imbalance_z",
        family="M-01/ORDER_FLOW",
        source="binance_spot_klines",
        raw_fields=("volume", "taker_buy_base"),
        aggregation="rolling z-score of flow_imbalance",
        window=20,
        availability="bar close",
    ),
    "avg_trade_size": FeatureSpec(
        feature_id="avg_trade_size",
        family="M-01/ORDER_FLOW",
        source="binance_spot_klines",
        raw_fields=("volume", "trades"),
        aggregation="volume / trades",
        window=1,
        availability="bar close",
    ),
    "ret_mom_bps": FeatureSpec(
        feature_id="ret_mom_bps",
        family="M-03/FLOW_BREAKOUT",
        source="binance_spot_klines",
        raw_fields=("close",),
        aggregation="close[i]/close[i-window] - 1, in bps",
        window=12,
        availability="bar close",
    ),
    "realized_vol_bps": FeatureSpec(
        feature_id="realized_vol_bps",
        family="M-03/FLOW_BREAKOUT",
        source="binance_spot_klines",
        raw_fields=("close",),
        aggregation="std of 1-bar returns over window, in bps",
        window=20,
        availability="bar close",
    ),
    "range_bps": FeatureSpec(
        feature_id="range_bps",
        family="M-03/FLOW_BREAKOUT",
        source="binance_spot_klines",
        raw_fields=("high", "low", "close"),
        aggregation="(high - low) / close, in bps",
        window=1,
        availability="bar close",
    ),
    "funding_rate": FeatureSpec(
        feature_id="funding_rate",
        family="M-04/FUNDING",
        source="binance_usdm_fundingRate",
        raw_fields=("fundingRate",),
        aggregation="last realised funding rate as-of decision time",
        window=1,
        availability="fundingTime",
    ),
    "funding_z": FeatureSpec(
        feature_id="funding_z",
        family="M-04/FUNDING",
        source="binance_usdm_fundingRate",
        raw_fields=("fundingRate",),
        aggregation="rolling z-score of realised funding",
        window=21,
        availability="fundingTime",
    ),
    "premium": FeatureSpec(
        feature_id="premium",
        family="M-05/PREMIUM",
        source="binance_usdm_premiumIndexKlines",
        raw_fields=("markPrice", "indexPrice"),
        aggregation="(mark - index) / index as-of decision time",
        window=1,
        availability="interval close",
    ),
    "premium_z": FeatureSpec(
        feature_id="premium_z",
        family="M-05/PREMIUM",
        source="binance_usdm_premiumIndexKlines",
        raw_fields=("markPrice", "indexPrice"),
        aggregation="rolling z-score of premium",
        window=21,
        availability="interval close",
    ),
    "oi_change_z": FeatureSpec(
        feature_id="oi_change_z",
        family="M-06/OI",
        source="binance_usdm_openInterestHist",
        raw_fields=("sumOpenInterest",),
        aggregation="rolling z-score of pct OI change",
        window=21,
        availability="timestamp",
    ),
    "basis_bps": FeatureSpec(
        feature_id="basis_bps",
        family="M-05/BASIS",
        source="binance_usdm_basis",
        raw_fields=("futuresPrice", "indexPrice"),
        aggregation="(futures - index) / index, in bps",
        window=1,
        availability="timestamp",
    ),
}


def rolling_zscore(values: list[float], window: int) -> list[float | None]:
    """Rolling z-score; ``None`` until ``window`` observations exist."""
    if window <= 1:
        raise ValueError("window must be > 1")
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        w = values[i + 1 - window : i + 1]
        mean = sum(w) / window
        var = sum((x - mean) ** 2 for x in w) / window
        sd = math.sqrt(var)
        out.append((values[i] - mean) / sd if sd > 0 else 0.0)
    return out


def flow_imbalance(bar: MicroBar) -> float:
    """Aggressive-flow imbalance in [-1, 1].

    taker_buy_base is aggressive *buy* volume; the remainder of total volume
    is aggressive *sell* volume.
    """
    if bar.volume <= 0.0:
        return 0.0
    sell = bar.volume - bar.taker_buy_base
    return (bar.taker_buy_base - sell) / bar.volume


def forward_return_bps(closes: list[float], i: int, horizon: int) -> float | None:
    """Forward return from close[i] to close[i+horizon], in bps.

    Returns ``None`` when the horizon extends past the sample.
    """
    j = i + horizon
    if j >= len(closes) or closes[i] <= 0.0:
        return None
    return (closes[j] / closes[i] - 1.0) * 10_000.0


def flow_features(bars: list[MicroBar], lookback: int = 20) -> dict[str, list[float | None]]:
    """Compute PIT-safe OHLCV+flow features over a bar series.

    Each returned list is aligned index-for-index with ``bars``. Values are
    ``None`` during the warm-up where the trailing window is incomplete.
    """
    n = len(bars)
    fi = [flow_imbalance(b) for b in bars]
    fi_z = rolling_zscore(fi, lookback)

    avg_size: list[float | None] = []
    for b in bars:
        avg_size.append(b.volume / b.trades if b.trades > 0 else None)

    ret_mom: list[float | None] = []
    for i in range(n):
        if i < 12:
            ret_mom.append(None)
        else:
            ret_mom.append((bars[i].close / bars[i - 12].close - 1.0) * 10_000.0)

    realized_vol: list[float | None] = []
    rets = [0.0] + [
        (bars[i].close / bars[i - 1].close - 1.0) * 10_000.0 for i in range(1, n)
    ]
    for i in range(n):
        if i + 1 < lookback:
            realized_vol.append(None)
        else:
            w = rets[i + 1 - lookback : i + 1]
            mu = sum(w) / len(w)
            realized_vol.append(math.sqrt(sum((x - mu) ** 2 for x in w) / len(w)))

    range_bps: list[float | None] = [
        (b.high - b.low) / b.close * 10_000.0 if b.close > 0 else None for b in bars
    ]

    return {
        "flow_imbalance": list(fi),
        "flow_imbalance_z": fi_z,
        "avg_trade_size": avg_size,
        "ret_mom_bps": ret_mom,
        "realized_vol_bps": realized_vol,
        "range_bps": range_bps,
    }
