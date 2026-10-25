"""Cross-asset flow panel tests (MICROSTRUCTURE-EDGE-V2).

Two things are being protected here, in this order:

1. **No future information.** A cross-asset signal may only use a bar whose own
   availability is at or before the decision instant; a negative lag is a hard
   error, not a silent skip.
2. **No invented observations.** A panel slice exists only when every asset has
   a complete bar on the same clock; a partially aggregated or partial bucket is
   dropped, never extrapolated.
"""

from __future__ import annotations

import pytest

from trading_bot.research.microstructure.flow_panel import (
    MINUTE_MS,
    OI_UNCHANGED,
    PanelAlignmentError,
    PanelBar,
    PanelSlice,
    aggregate_minutes_to_bars,
    build_panel,
    conditional_stats,
    cross_sectional_flow,
    flow_impulse_series,
    information_content,
    oi_price_state,
    parse_minute_row,
    pit_lead_lag,
    quantile_table,
    spearman,
    summarize_panel,
    trade_stats,
)


def _minute_row(
    symbol: str,
    minute_ms: int,
    *,
    buy: float = 6.0,
    sell: float = 4.0,
    n_trades: int = 10,
    close: float = 100.0,
    large_buy: float = 1.0,
    large_sell: float = 0.5,
    min_interarrival_ms: int | None = 12,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "minute_ms": minute_ms,
        "n_trades": n_trades,
        "buy_vol": buy,
        "sell_vol": sell,
        "buy_quote": buy * close,
        "sell_quote": sell * close,
        "sum_qty_sq": 1.25,
        "large_buy_vol": large_buy,
        "large_sell_vol": large_sell,
        "first_price": close - 0.5,
        "last_price": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "max_trade_qty": 0.75,
        "min_interarrival_ms": min_interarrival_ms,
        "available_at": minute_ms + MINUTE_MS + 1,
    }


def _bar(symbol: str, open_ms: int, buy: float, sell: float, close: float = 100.0) -> PanelBar:
    return PanelBar(
        symbol=symbol,
        open_time_ms=open_ms,
        available_at_ms=open_ms + 5 * MINUTE_MS + 1,
        close=close,
        buy_volume=buy,
        sell_volume=sell,
        n_trades=10,
        large_buy_volume=1.0,
        large_sell_volume=0.5,
        min_interarrival_ms=12,
        vwap=close,
    )


# --- parsing / minute rows -------------------------------------------------


def test_parse_minute_row_roundtrip() -> None:
    row = parse_minute_row(_minute_row("BTCUSDT", 1_000_000))
    assert row.symbol == "BTCUSDT"
    assert row.minute_ms == 1_000_000
    assert row.total_volume == pytest.approx(10.0)
    assert row.available_at_ms == 1_000_000 + MINUTE_MS + 1


def test_parse_minute_row_fails_closed_on_missing_field() -> None:
    raw = _minute_row("BTCUSDT", 1_000_000)
    del raw["buy_vol"]
    with pytest.raises(ValueError, match="buy_vol"):
        parse_minute_row(raw)


def test_parse_minute_row_rejects_non_numeric() -> None:
    raw = _minute_row("BTCUSDT", 1_000_000)
    raw["last_price"] = "not-a-price"
    with pytest.raises(ValueError, match="last_price"):
        parse_minute_row(raw)


def test_minute_row_rejects_last_price_outside_range() -> None:
    raw = _minute_row("BTCUSDT", 1_000_000)
    raw["last_price"] = 500.0
    with pytest.raises(ValueError, match="outside"):
        parse_minute_row(raw)


def test_minute_row_rejects_availability_at_or_before_event() -> None:
    raw = _minute_row("BTCUSDT", 1_000_000)
    raw["available_at"] = 1_000_000
    with pytest.raises(ValueError, match="available_at"):
        parse_minute_row(raw)


# --- aggregation -----------------------------------------------------------


def test_aggregation_requires_complete_buckets() -> None:
    # 1_600_000_200_000 is an exact 5-minute multiple of the UTC grid.
    day_open = 1_600_000_200_000
    rows = [parse_minute_row(_minute_row("BTCUSDT", day_open + k * MINUTE_MS)) for k in range(5)]
    bars = aggregate_minutes_to_bars(rows)
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open_time_ms == day_open
    assert bar.available_at_ms == day_open + 5 * MINUTE_MS + 1
    assert bar.buy_volume == pytest.approx(30.0)
    assert bar.sell_volume == pytest.approx(20.0)
    assert bar.n_trades == 50
    assert bar.flow_imbalance == pytest.approx(0.2)
    assert bar.close == pytest.approx(100.0)


def test_aggregation_drops_incomplete_bucket() -> None:
    day_open = 1_600_000_200_000
    rows = [parse_minute_row(_minute_row("BTCUSDT", day_open + k * MINUTE_MS)) for k in range(4)]
    assert aggregate_minutes_to_bars(rows) == []


def test_aggregation_drops_bucket_with_an_internal_hole() -> None:
    day_open = 1_600_000_200_000
    minutes = [0, 1, 3, 4]
    rows = [parse_minute_row(_minute_row("BTCUSDT", day_open + k * MINUTE_MS)) for k in minutes]
    assert aggregate_minutes_to_bars(rows) == []


def test_aggregation_rejects_duplicate_minutes() -> None:
    day_open = 1_600_000_200_000
    rows = [
        parse_minute_row(_minute_row("BTCUSDT", day_open)),
        parse_minute_row(_minute_row("BTCUSDT", day_open)),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_minutes_to_bars(rows)


def test_aggregation_rejects_mixed_symbols() -> None:
    day_open = 1_600_000_200_000
    rows = [
        parse_minute_row(_minute_row("BTCUSDT", day_open)),
        parse_minute_row(_minute_row("ETHUSDT", day_open + MINUTE_MS)),
    ]
    with pytest.raises(ValueError, match="one symbol"):
        aggregate_minutes_to_bars(rows)


def test_aggregation_of_empty_input() -> None:
    assert aggregate_minutes_to_bars([]) == []


def test_aggregation_ignores_minutes_off_the_utc_grid() -> None:
    # A series which is complete but shifted off the bar grid must not silently
    # become a bar: the alignment is part of the contract.
    off_grid = 1_600_000_000_000
    rows = [parse_minute_row(_minute_row("BTCUSDT", off_grid + k * MINUTE_MS)) for k in range(5)]
    assert aggregate_minutes_to_bars(rows) == []


def test_bar_rejects_availability_before_open() -> None:
    with pytest.raises(ValueError, match="available_at_ms"):
        PanelBar(
            symbol="BTCUSDT",
            open_time_ms=1_000,
            available_at_ms=1_000,
            close=100.0,
            buy_volume=1.0,
            sell_volume=1.0,
            n_trades=2,
            large_buy_volume=0.0,
            large_sell_volume=0.0,
            min_interarrival_ms=None,
            vwap=None,
        )


def test_flow_imbalance_is_zero_without_volume() -> None:
    bar = _bar("BTCUSDT", 1_000, buy=0.0, sell=0.0)
    assert bar.flow_imbalance == 0.0


# --- panel alignment -------------------------------------------------------


def test_build_panel_intersects_clocks() -> None:
    base = 1_600_000_000_000
    bars = {
        "BTCUSDT": [
            _bar("BTCUSDT", base, 6.0, 4.0),
            _bar("BTCUSDT", base + 5 * MINUTE_MS, 6.0, 4.0),
        ],
        "ETHUSDT": [_bar("ETHUSDT", base, 3.0, 7.0)],
        "SOLUSDT": [_bar("SOLUSDT", base, 5.0, 5.0)],
    }
    panel = build_panel(bars, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    assert len(panel) == 1
    assert panel[0].symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert panel[0].decision_time_ms == base + 5 * MINUTE_MS + 1


def test_build_panel_requires_two_symbols() -> None:
    with pytest.raises(ValueError, match="at least two symbols"):
        build_panel({"BTCUSDT": []})


def test_build_panel_rejects_missing_symbol() -> None:
    with pytest.raises(KeyError, match="SOLUSDT"):
        build_panel({"BTCUSDT": [], "ETHUSDT": []}, symbols=["BTCUSDT", "SOLUSDT"])


def test_panel_slice_rejects_mixed_availability() -> None:
    base = 1_600_000_000_000
    good = _bar("BTCUSDT", base, 6.0, 4.0)
    skewed = PanelBar(
        symbol="ETHUSDT",
        open_time_ms=base,
        available_at_ms=base + 5 * MINUTE_MS + 2,
        close=100.0,
        buy_volume=3.0,
        sell_volume=7.0,
        n_trades=10,
        large_buy_volume=0.0,
        large_sell_volume=0.0,
        min_interarrival_ms=None,
        vwap=100.0,
    )
    with pytest.raises(PanelAlignmentError, match="availability"):
        PanelSlice(open_time_ms=base, decision_time_ms=good.available_at_ms, bars=(good, skewed))


def test_panel_slice_rejects_duplicate_symbol() -> None:
    base = 1_600_000_000_000
    with pytest.raises(PanelAlignmentError, match="duplicate symbol"):
        PanelSlice(
            open_time_ms=base,
            decision_time_ms=base + 5 * MINUTE_MS + 1,
            bars=(_bar("BTCUSDT", base, 6.0, 4.0), _bar("BTCUSDT", base, 3.0, 7.0)),
        )


def test_summarize_panel_reports_gaps() -> None:
    base = 1_600_000_000_000
    step = 5 * MINUTE_MS
    bars = {
        "BTCUSDT": [_bar("BTCUSDT", base + i * step, 6.0, 4.0) for i in (0, 1, 3)],
        "ETHUSDT": [_bar("ETHUSDT", base + i * step, 3.0, 7.0) for i in (0, 1, 3)],
    }
    panel = build_panel(bars, symbols=["BTCUSDT", "ETHUSDT"])
    summary = summarize_panel(panel)
    assert summary.slices == 3
    assert summary.max_gap_ms == 2 * step
    assert summary.duplicate_timestamps == 0
    assert summary.as_dict()["symbols"] == ["BTCUSDT", "ETHUSDT"]


def test_summarize_panel_of_empty_panel() -> None:
    summary = summarize_panel([])
    assert summary.slices == 0
    assert summary.first_decision_time_ms is None
    assert summary.as_dict()["slices"] == 0


# --- point-in-time lead/lag ------------------------------------------------


def _panel_for_lead_lag() -> list[PanelSlice]:
    base = 1_600_000_000_000
    step = 5 * MINUTE_MS
    bars = {
        "BTCUSDT": [_bar("BTCUSDT", base + i * step, 6.0, 4.0) for i in range(3)],
        "ETHUSDT": [_bar("ETHUSDT", base + i * step, 3.0, 7.0) for i in range(3)],
        "SOLUSDT": [_bar("SOLUSDT", base + i * step, 5.0, 5.0) for i in range(3)],
    }
    return build_panel(bars, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])


def test_pit_lead_lag_lag_zero_is_contemporaneous() -> None:
    panel = _panel_for_lead_lag()
    pairs = pit_lead_lag(panel, panel, source_symbol="BTCUSDT", lag=0)
    assert [j for j, _i, _v in pairs] == [0, 1, 2]
    assert all(v == pytest.approx(0.2) for _j, _i, v in pairs)


def test_pit_lead_lag_lag_one_uses_previous_bar() -> None:
    panel = _panel_for_lead_lag()
    pairs = pit_lead_lag(panel, panel, source_symbol="BTCUSDT", lag=1)
    assert [(j, i) for j, i, _v in pairs] == [(1, 0), (2, 1)]
    for j, i, _v in pairs:
        assert panel[i].decision_time_ms <= panel[j].decision_time_ms


def test_pit_lead_lag_rejects_negative_lag() -> None:
    panel = _panel_for_lead_lag()
    with pytest.raises(PanelAlignmentError, match="after the decision"):
        pit_lead_lag(panel, panel, source_symbol="BTCUSDT", lag=-1)


def test_pit_lead_lag_rejects_unknown_source_symbol() -> None:
    panel = _panel_for_lead_lag()
    with pytest.raises(KeyError, match="XRPUSDT"):
        pit_lead_lag(panel, panel, source_symbol="XRPUSDT", lag=0)


def test_pit_lead_lag_with_empty_panels() -> None:
    assert pit_lead_lag([], [], source_symbol="BTCUSDT", lag=1) == []


# --- cross-sectional flow --------------------------------------------------


def test_cross_sectional_flow_is_mean_centred() -> None:
    base = 1_600_000_000_000
    bars = {
        # flows: BTC +0.2, ETH -0.4, SOL +0.0 -> mean -1/15, dispersion > 0
        "BTCUSDT": [_bar("BTCUSDT", base, 6.0, 4.0)],
        "ETHUSDT": [_bar("ETHUSDT", base, 3.0, 7.0)],
        "SOLUSDT": [_bar("SOLUSDT", base, 5.0, 5.0)],
    }
    panel = build_panel(bars, symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    cs = cross_sectional_flow(panel)
    deviations = [cs[s][0] for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    assert sum(deviations) == pytest.approx(0.0)
    assert cs["__dispersion__"][0] > 0.0
    assert cs["BTCUSDT"][0] > 0.0 > cs["ETHUSDT"][0]


def test_cross_sectional_flow_of_empty_panel() -> None:
    assert cross_sectional_flow([]) == {}


# --- flow impulse ----------------------------------------------------------


def test_flow_impulse_is_a_difference_not_a_level() -> None:
    # A constant (even extreme) level has no impulse at all: once the window is
    # warm the value is exactly 0.0, not a small positive number.
    assert flow_impulse_series([0.9] * 6, window=3) == [None, None, None, 0.0, 0.0, 0.0]
    # A jump produces a positive impulse that flips sign once the baseline
    # catches up: this is what separates M-02 from M-01.
    flows = [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.5]
    impulse = flow_impulse_series(flows, window=3)
    assert impulse[:3] == [None, None, None]
    assert impulse[3] == pytest.approx(0.0)
    assert impulse[4] is not None and impulse[4] > 0.0
    assert impulse[5] is not None and impulse[5] < 0.0


def test_flow_impulse_requires_window_of_at_least_two() -> None:
    with pytest.raises(ValueError, match="window"):
        flow_impulse_series([1.0, 2.0], window=1)


def test_flow_impulse_all_none_when_sample_too_short() -> None:
    assert flow_impulse_series([0.1, 0.2], window=5) == [None, None]


# --- open-interest states --------------------------------------------------


def test_oi_price_state_quadrants() -> None:
    assert oi_price_state(5.0, 1.0) == "PRICE_UP_OI_UP"
    assert oi_price_state(5.0, -1.0) == "PRICE_UP_OI_DOWN"
    assert oi_price_state(-5.0, 1.0) == "PRICE_DOWN_OI_UP"
    assert oi_price_state(-5.0, -1.0) == "PRICE_DOWN_OI_DOWN"


def test_oi_price_state_zero_change_is_not_forced_into_a_quadrant() -> None:
    assert oi_price_state(0.0, 1.0) == OI_UNCHANGED
    assert oi_price_state(3.0, 0.0) == OI_UNCHANGED


# --- statistics ------------------------------------------------------------


def test_spearman_is_one_for_monotone_increasing() -> None:
    assert spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0)
    assert spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_spearman_handles_ties_without_dividing_by_zero() -> None:
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0
    assert spearman([1.0, 1.0, 2.0, 2.0], [1.0, 2.0, 3.0, 4.0]) > 0.0


def test_spearman_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="equal-length"):
        spearman([1.0, 2.0, 3.0], [1.0, 2.0])


def test_quantile_table_reports_insufficient_data() -> None:
    table = quantile_table([1.0, 2.0], [1.0, 2.0], buckets=5)
    assert table["status"] == "INSUFFICIENT_DATA"
    assert table["top_minus_bottom_bps"] is None


def test_quantile_table_detects_a_perfect_relationship() -> None:
    xs = [float(i) for i in range(100)]
    ys = [x * 2.0 for x in xs]
    table = quantile_table(xs, ys, buckets=5)
    assert table["status"] == "OK"
    top_bottom = table["top_minus_bottom_bps"]
    monotone = table["monotone_score"]
    buckets = table["buckets"]
    assert isinstance(top_bottom, float) and top_bottom > 0.0
    assert isinstance(monotone, float) and monotone == pytest.approx(1.0)
    assert isinstance(buckets, list) and len(buckets) == 5


def test_conditional_stats_of_empty_group() -> None:
    stats = conditional_stats({"PRICE_UP_OI_UP": []})
    assert stats["PRICE_UP_OI_UP"]["n"] == 0


def test_conditional_stats_reports_dispersion() -> None:
    stats = conditional_stats({"PRICE_UP_OI_UP": [1.0, 3.0, 5.0]})
    assert stats["PRICE_UP_OI_UP"]["n"] == 3
    assert stats["PRICE_UP_OI_UP"]["mean_bps"] == pytest.approx(3.0)
    assert stats["PRICE_UP_OI_UP"]["share_positive"] == pytest.approx(1.0)


def test_trade_stats_of_empty_series() -> None:
    assert trade_stats([]) == {"n": 0}


def test_trade_stats_reports_drawdown_and_pf() -> None:
    stats = trade_stats([10.0, -5.0, -5.0])
    assert stats["n"] == 3
    assert stats["win_rate"] == pytest.approx(0.3333)
    assert stats["pf"] == pytest.approx(1.0)
    assert stats["max_dd_bps"] == pytest.approx(10.0)


def test_information_content_requires_a_minimum_sample() -> None:
    ic = information_content([float(i) for i in range(10)], [float(i) for i in range(10)])
    assert ic["status"] == "INSUFFICIENT_DATA"
    assert ic["ic_spearman"] is None


def test_information_content_labels_a_real_relationship() -> None:
    n = 200
    xs = [float(i) for i in range(n)]
    ys = [x + (1.0 if i % 3 == 0 else 0.0) for i, x in enumerate(xs)]
    ic = information_content(xs, ys)
    assert ic["status"] == "HAS_INFORMATION"
    coefficient = ic["ic_spearman"]
    assert isinstance(coefficient, float) and coefficient > 0.9


def test_information_content_labels_noise_as_no_information() -> None:
    n = 200
    xs = [float(i) for i in range(n)]
    ys = [0.0 if i % 2 == 0 else 1.0 for i in range(n)]
    ic = information_content(xs, ys)
    assert ic["status"] == "NO_INFORMATION"


def test_information_content_skips_none_pairs() -> None:
    ic = information_content([None, None, 1.0], [1.0, 2.0, 3.0])
    assert ic["n"] == 1
    assert ic["status"] == "INSUFFICIENT_DATA"
