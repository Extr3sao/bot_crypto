"""ALPHA-003 — the cross-asset frame must be point-in-time strict and gap-honest.

These tests are written against the failure modes that would manufacture an edge out of
nothing: a leader that reads a bar the target had not seen, a window that silently spans a
missing bar, a context bar that had not closed, a timestamp grid that quietly slides, and a
future observation that leaks backwards into the past.
"""

from __future__ import annotations

import bisect
import random
import statistics

import pytest

from trading_bot.research import alpha003_features as af

PERIOD = 5 * 60 * 1000
HOUR = 60 * 60 * 1000
T0 = 1_700_000_000_000


def bars_from_returns(
    returns: list[float],
    *,
    t0: int = T0,
    period: int = PERIOD,
    start: float = 100.0,
    spread: float = 0.0004,
) -> list[list[float]]:
    """Contiguous OHLCV bars whose closes follow the given returns."""
    out: list[list[float]] = []
    price = start
    previous = start
    for index, value in enumerate(returns):
        price = price * (1.0 + value)
        open_, close = previous, price
        high = max(open_, close) * (1.0 + spread)
        low = min(open_, close) * (1.0 - spread)
        out.append([t0 + index * period, open_, high, low, close, 1.0])
        previous = price
    return out


def random_returns(n: int, seed: int, sigma: float = 0.001) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def test_period_ms() -> None:
    assert af.period_ms("5m") == PERIOD
    assert af.period_ms("15m") == 15 * 60 * 1000
    assert af.period_ms("1h") == HOUR
    with pytest.raises(ValueError):
        af.period_ms("3m")


def test_frame_rows_are_the_universe_intersection() -> None:
    bars = {
        "BTCUSDT": bars_from_returns(random_returns(300, 1)),
        "ETHUSDT": bars_from_returns(random_returns(280, 2)),
        "SOLUSDT": bars_from_returns(random_returns(260, 3)),
    }
    frame = af.build_frame(timeframe="5m", bars_by_symbol=bars, windows=(1, 2))
    assert len(frame) == 260
    assert [row["bar_open_ms"] for row in frame] == [T0 + index * PERIOD for index in range(260)]


def test_timestamp_drift_shrinks_the_grid_and_never_misaligns() -> None:
    """A symbol on a shifted grid cannot silently join the frame at the wrong instant."""
    aligned = bars_from_returns(random_returns(200, 1))
    drifted = bars_from_returns(random_returns(200, 2), t0=T0 + PERIOD)
    frame = af.build_frame(
        timeframe="5m",
        bars_by_symbol={"BTCUSDT": aligned, "ETHUSDT": drifted},
        windows=(1, 2),
    )
    assert len(frame) == 199
    opens = {int(bar[0]) for bar in aligned} & {int(bar[0]) for bar in drifted}
    assert all(row["bar_open_ms"] in opens for row in frame)


def test_disjoint_grids_produce_no_frame() -> None:
    frame = af.build_frame(
        timeframe="5m",
        bars_by_symbol={
            "BTCUSDT": bars_from_returns(random_returns(50, 1)),
            "ETHUSDT": bars_from_returns(random_returns(50, 2), t0=T0 + 500 * PERIOD),
        },
        windows=(1, 2),
    )
    assert frame == []


def test_a_missing_bar_makes_the_window_undefined_never_forward_filled() -> None:
    bars = bars_from_returns(random_returns(100, 5))
    holed = [bar for index, bar in enumerate(bars) if index != 60]
    frame_without = af.build_frame(
        timeframe="5m", bars_by_symbol={"BTCUSDT": bars, "SOLUSDT": bars}, windows=(1,)
    )
    frame_with = af.build_frame(
        timeframe="5m", bars_by_symbol={"BTCUSDT": holed, "SOLUSDT": holed}, windows=(1,)
    )
    # the bar at index 60 is gone entirely, so the grid loses it
    assert len(frame_with) == 99
    with_by_open = {row["bar_open_ms"]: row for row in frame_with}
    # the window that would span the hole is undefined rather than spanning it
    spanning_open = T0 + 61 * PERIOD
    assert with_by_open[spanning_open]["ret1_SOLUSDT"] is None
    assert with_by_open[spanning_open]["market_ret1"] is None
    # and the un-holed frame has it defined
    without_by_open = {row["bar_open_ms"]: row for row in frame_without}
    assert without_by_open[spanning_open]["ret1_SOLUSDT"] is not None


def test_future_bars_do_not_move_the_past() -> None:
    """Causality, stated as a property of the builder rather than of one number.

    Bars from index 151 on are rewritten.  Row 150's *features* read bars up to 150 only,
    but its forward return is the label and legitimately reads bar 151, so the untouched
    range ends at row 149.
    """
    bars = bars_from_returns(random_returns(200, 9))
    base = af.build_frame(timeframe="5m", bars_by_symbol={"BTCUSDT": bars}, windows=(1, 2))
    mutated = [list(bar) for bar in bars]
    for index in range(151, 200):
        mutated[index][4] = float(mutated[index][4]) * 1.5
        mutated[index][2] = max(float(mutated[index][2]), float(mutated[index][4]))
    changed = af.build_frame(timeframe="5m", bars_by_symbol={"BTCUSDT": mutated}, windows=(1, 2))
    assert base[:150] == changed[:150]
    # and row 150's features are unchanged too, only its forward label moved
    features_only = {
        key: value for key, value in changed[150].items() if not key.startswith("fwd_")
    }
    assert {
        key: value for key, value in base[150].items() if not key.startswith("fwd_")
    } == features_only
    assert base[150]["fwd_BTCUSDT"] != changed[150]["fwd_BTCUSDT"]


def test_the_leader_window_ends_before_the_decision_for_lag_two() -> None:
    bars = bars_from_returns(random_returns(120, 11))
    closes = [float(bar[4]) for bar in bars]
    frame = af.build_frame(
        timeframe="5m", bars_by_symbol={"BTCUSDT": bars, "SOLUSDT": bars}, windows=(1, 2)
    )
    assert frame[0]["ret1_BTCUSDT"] is None
    assert frame[0]["ret2_BTCUSDT"] is None
    for index, row in enumerate(frame):
        assert row["decision_ms"] == row["bar_open_ms"] + PERIOD
        if index == 0:
            continue
        assert row["ret1_BTCUSDT"] == pytest.approx(closes[index] / closes[index - 1] - 1.0)
        if index < 2:
            assert row["ret2_BTCUSDT"] is None
            continue
        assert row["ret2_BTCUSDT"] == pytest.approx(closes[index] / closes[index - 2] - 1.0)


def test_point_in_time_invariant_holds_for_every_row() -> None:
    bars = {
        name: bars_from_returns(random_returns(150, seed))
        for seed, name in enumerate(["a", "b", "c"])
    }
    for row in af.build_frame(timeframe="5m", bars_by_symbol=bars, windows=(1, 2)):
        assert row["point_in_time_ok"] is True
        assert row["available_ms"] <= row["decision_ms"]


# --------------------------------------------------------------------------- #
# the context regime is read from a closed bar only
# --------------------------------------------------------------------------- #


def _expected_regime(bars: list[list[float]], decision_ms: int, step: int) -> float | None:
    """An independent recomputation: newest context bar that had closed, then trailing vol."""
    opens = [int(bar[0]) for bar in bars]
    closes = [float(bar[4]) for bar in bars]
    index = bisect.bisect_right(opens, decision_ms - step) - 1
    if index < 0:
        return None
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, index + 1) if closes[i - 1] > 0.0]
    if len(returns) < af.MIN_VOL_REGIME_OBSERVATIONS:
        return None
    trailing = returns[-af.VOL_REGIME_BASELINE_WINDOW :]
    short = trailing[-af.VOL_REGIME_SHORT_WINDOW :]
    short_vol = statistics.pstdev(short) if len(short) > 1 else 0.0
    baseline_vol = statistics.pstdev(trailing) if len(trailing) > 1 else 0.0
    if short_vol <= 0.0 or baseline_vol <= 0.0:
        return None
    return 1.0 if short_vol > baseline_vol else -1.0


def test_context_regime_never_reads_an_unclosed_bar() -> None:
    # alternating calm / turbulent 1h blocks so the regime actually flips
    rng = random.Random(23)
    context: list[float] = []
    for block in range(40):
        sigma = 0.001 if block % 2 == 0 else 0.01
        context.extend(rng.gauss(0.0, sigma) for _ in range(10))
    context_bars = bars_from_returns(context, period=HOUR, spread=0.0002)
    entry_bars = bars_from_returns(random_returns(12 * len(context), 31))
    frame = af.build_frame(
        timeframe="5m",
        bars_by_symbol={"SOLUSDT": entry_bars},
        windows=(1,),
        regime_bars_by_symbol={"SOLUSDT": context_bars},
    )
    observed = [row["vol_regime_SOLUSDT"] for row in frame]
    assert any(value is not None for value in observed)
    for row in frame:
        expected = _expected_regime(context_bars, int(row["decision_ms"]), HOUR)
        assert row["vol_regime_SOLUSDT"] == expected


# --------------------------------------------------------------------------- #
# the derived cell row
# --------------------------------------------------------------------------- #


def test_cell_row_derivations() -> None:
    bars = bars_from_returns(random_returns(200, 41))
    frame = af.build_frame(
        timeframe="5m",
        bars_by_symbol={"BTCUSDT": bars, "SOLUSDT": bars, "XRPUSDT": bars},
        windows=(1, 2),
    )
    row = frame[100]
    cell = af.cell_row(row, target="SOLUSDT", leader="BTCUSDT", lag=2)
    assert cell["leader_ret_z"] == pytest.approx(row["ret2_BTCUSDT"] / row["atr_pct_BTCUSDT"])
    assert cell["target_ret_z"] == pytest.approx(row["ret2_SOLUSDT"] / row["atr_pct_SOLUSDT"])
    assert cell["target_mom_z"] == pytest.approx(row["ret12_SOLUSDT"] / row["atr_pct_SOLUSDT"])
    assert cell["market_ret_z"] == pytest.approx(row["market_ret12"] / row["atr_pct_SOLUSDT"])
    target_mom = cell["target_mom_z"]
    market = cell["market_ret_z"]
    assert target_mom is not None and market is not None
    assert cell["relative_z"] == pytest.approx(target_mom - market)


def test_cell_row_without_a_leader_has_no_pair_features() -> None:
    bars = bars_from_returns(random_returns(120, 43))
    frame = af.build_frame(timeframe="5m", bars_by_symbol={"SOLUSDT": bars}, windows=(1, 2))
    cell = af.cell_row(frame[80], target="SOLUSDT")
    assert cell["leader_ret_z"] is None
    assert cell["target_ret_z"] is None
    target_mom = cell["target_mom_z"]
    market = cell["market_ret_z"]
    assert target_mom is not None and market is not None
    assert cell["relative_z"] == pytest.approx(target_mom - market)


def test_forward_return_is_the_next_bar() -> None:
    bars = bars_from_returns(random_returns(80, 47))
    closes = [float(bar[4]) for bar in bars]
    frame = af.build_frame(timeframe="5m", bars_by_symbol={"SOLUSDT": bars}, windows=(1,))
    for index, row in enumerate(frame[:-1]):
        assert af.forward_return_for(row, "SOLUSDT") == pytest.approx(
            closes[index + 1] / closes[index] - 1.0
        )
    assert af.forward_return_for(frame[-1], "SOLUSDT") is None


# --------------------------------------------------------------------------- #
# adversarial inputs
# --------------------------------------------------------------------------- #


def test_a_flat_symbol_has_no_defined_features_rather_than_zero() -> None:
    flat = [[T0 + index * PERIOD, 100.0, 100.0, 100.0, 100.0, 1.0] for index in range(80)]
    frame = af.build_frame(timeframe="5m", bars_by_symbol={"SOLUSDT": flat}, windows=(1,))
    row = frame[-1]
    assert row["atr_pct_SOLUSDT"] is None
    cell = af.cell_row(row, target="SOLUSDT")
    assert cell["target_mom_z"] is None
    assert cell["relative_z"] is None


def test_an_extreme_but_finite_outlier_is_used_not_sanitised() -> None:
    returns = random_returns(150, 53)
    returns[100] = 0.35  # a 35% bar: large, but a real observation
    bars = {name: bars_from_returns(returns) for name in ("BTCUSDT", "SOLUSDT")}
    frame = af.build_frame(timeframe="5m", bars_by_symbol=bars, windows=(1, 2))
    row = frame[100]
    cell = af.cell_row(row, target="SOLUSDT", leader="BTCUSDT", lag=1)
    assert cell["target_ret_z"] is not None
    assert cell["target_ret_z"] == cell["target_ret_z"]  # finite
    assert cell["target_ret_z"] > 5.0


def test_a_symbol_absent_from_the_frame_yields_undefined_features_not_a_number() -> None:
    """A missing symbol must never be read as 0.0 — the honest answer is 'undefined'."""
    bars = bars_from_returns(random_returns(100, 59))
    frame = af.build_frame(timeframe="5m", bars_by_symbol={"BTCUSDT": bars}, windows=(1,))
    cell = af.cell_row(frame[60], target="SOLUSDT")
    assert cell["target_mom_z"] is None
    assert cell["market_ret_z"] is None
    assert cell["relative_z"] is None
