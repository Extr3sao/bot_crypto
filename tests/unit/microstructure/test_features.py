"""Tests for microstructure features + data types (§19-20, §64-65)."""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.features import (
    FEATURE_SPECS,
    flow_features,
    flow_imbalance,
    forward_return_bps,
    rolling_zscore,
)
from trading_bot.research.microstructure.types import MicroBar


def _bar(i: int, close: float, buy: float, vol: float = 10.0, trades: int = 5) -> MicroBar:
    return MicroBar(
        event_time=i * 300_000,
        available_at=i * 300_000 + 300_000,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=vol,
        quote_volume=close * vol,
        trades=trades,
        taker_buy_base=buy,
        taker_buy_quote=buy * close,
    )


# --- flow imbalance --------------------------------------------------------


def test_flow_imbalance_all_buy() -> None:
    assert flow_imbalance(_bar(0, 100.0, buy=10.0, vol=10.0)) == pytest.approx(1.0)


def test_flow_imbalance_all_sell() -> None:
    assert flow_imbalance(_bar(0, 100.0, buy=0.0, vol=10.0)) == pytest.approx(-1.0)


def test_flow_imbalance_balanced() -> None:
    assert flow_imbalance(_bar(0, 100.0, buy=5.0, vol=10.0)) == pytest.approx(0.0)


def test_flow_imbalance_zero_volume_is_neutral() -> None:
    assert flow_imbalance(_bar(0, 100.0, buy=0.0, vol=0.0)) == 0.0


# --- rolling z -------------------------------------------------------------


def test_rolling_zscore_warmup_none() -> None:
    out = rolling_zscore([1.0, 2.0, 3.0], window=3)
    assert out[0] is None
    assert out[1] is None
    assert out[2] is not None


def test_rolling_zscore_constant_series_zero() -> None:
    out = rolling_zscore([5.0] * 5, window=3)
    assert out[-1] == 0.0


def test_rolling_zscore_rejects_bad_window() -> None:
    with pytest.raises(ValueError):
        rolling_zscore([1.0, 2.0], window=1)


# --- forward return (no look-ahead) ---------------------------------------


def test_forward_return_basic() -> None:
    closes = [100.0, 101.0, 102.0]
    assert forward_return_bps(closes, 0, 1) == pytest.approx(100.0)


def test_forward_return_none_past_end() -> None:
    closes = [100.0, 101.0, 102.0]
    assert forward_return_bps(closes, 2, 1) is None


def test_forward_return_uses_future_only_at_decision_time() -> None:
    # purely functional: index i never reads indices < i
    closes = [100.0, 200.0, 50.0]
    r = forward_return_bps(closes, 1, 1)
    assert r == pytest.approx((50.0 / 200.0 - 1.0) * 10_000)


# --- flow_features alignment ----------------------------------------------


def test_flow_features_aligned_to_bars() -> None:
    bars = [_bar(i, 100.0 + i, buy=5.0) for i in range(30)]
    feats = flow_features(bars, lookback=20)
    for key, series in feats.items():
        assert len(series) == len(bars), key
    # warmup: flow_imbalance_z is None before window-1
    assert feats["flow_imbalance_z"][0] is None
    assert feats["flow_imbalance_z"][19] is not None


def test_feature_specs_have_provenance() -> None:
    for name, spec in FEATURE_SPECS.items():
        assert spec.source and spec.aggregation and spec.raw_fields, name


# --- MicroBar validation ---------------------------------------------------


def test_microbar_taker_buy_gt_volume_fails_closed() -> None:
    with pytest.raises(ValueError):
        _bar(0, 100.0, buy=20.0, vol=10.0)


def test_microbar_available_before_event_fails_closed() -> None:
    with pytest.raises(ValueError):
        MicroBar(
            event_time=1000, available_at=500, open=1, high=2, low=0.5, close=1,
            volume=1, quote_volume=1, trades=1, taker_buy_base=0.5, taker_buy_quote=0.5,
        )


def test_microbar_high_below_low_fails_closed() -> None:
    with pytest.raises(ValueError):
        MicroBar(
            event_time=0, available_at=1, open=1, high=0.5, low=1.0, close=1,
            volume=1, quote_volume=1, trades=1, taker_buy_base=0.5, taker_buy_quote=0.5,
        )


def test_microbar_negative_trades_fails_closed() -> None:
    with pytest.raises(ValueError):
        MicroBar(
            event_time=0, available_at=1, open=1, high=2, low=0.5, close=1,
            volume=1, quote_volume=1, trades=-1, taker_buy_base=0.5, taker_buy_quote=0.5,
        )
