"""003M — el fill maker contra la cinta tiene que ser falsable, no decorativo.

Lo que se prueba aquí, y por qué:

* un precio **tocado** no es un fill: sin volumen agresor suficiente la orden no se cruza;
* la cola declarada no es adorno: con cola 1x hace falta el doble de volumen que nuestra
  propia orden para llenarla entera;
* la latencia importa: una operación anterior a que la orden llegue al venue no puede
  llenarla;
* el lado agresor no se puede confundir: un vendedor agresor llena una compra, nunca una
  venta;
* las salidas resuelven el minuto ambiguo con ``stop_first`` y el stop paga fricción.

Los tests construyen cintas sintéticas: no tocan red, ni artefactos, ni el experimento.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
for extra in (REPO / "scripts", REPO / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import exp_003m_fills as fills  # noqa: E402

START_US = 1_800_000_000_000_000
MINUTE_US = 60_000_000


def _trade(offset_s: float, price: float, qty: float, *, buy_aggressor: bool) -> tuple[int, float, float, bool]:
    """``buy_aggressor`` true means the buyer crossed: it can fill a resting sell."""

    return (START_US + int(offset_s * 1e6), price, qty, not buy_aggressor)


def _bars(rows: list[tuple[float, float, float, float]]) -> dict:
    stamps = [1_800_000_000_000 + index * 60_000 for index in range(len(rows))]
    array = np.asarray(rows, dtype=float)
    return {
        "stamps": stamps,
        "index": {stamp: position for position, stamp in enumerate(stamps)},
        "open": array[:, 0],
        "high": array[:, 1],
        "low": array[:, 2],
        "close": array[:, 3],
    }


def test_untouched_limit_is_a_miss_not_a_zero_fill() -> None:
    trades = [_trade(1, 100.50, 5.0, buy_aggressor=True)]
    result = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert result["fill_fraction"] == 0.0
    assert result["touched"] is False
    assert result["miss_reason"] == "NO_AGGRESSOR_AT_LIMIT"


def test_touch_without_enough_volume_never_fills() -> None:
    """A seller trades at our bid, but not enough of it to get through the queue."""

    trades = [_trade(1, 100.0, 0.4, buy_aggressor=False)]
    result = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=1.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert result["touched"] is True
    assert result["fill_fraction"] == 0.0
    assert result["miss_reason"] == "QUEUE_NEVER_REACHED"


def test_queue_one_requires_two_orders_of_aggressor_volume() -> None:
    trades = [
        _trade(1, 100.0, 1.0, buy_aggressor=False),
        _trade(2, 100.0, 0.5, buy_aggressor=False),
    ]
    partial = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=1.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert partial["fill_fraction"] == pytest.approx(0.5)
    #: The first trade is exactly the queue: it consumes it and leaves nothing for us, so
    #: our first filled unit is in the second trade, not the first.
    assert partial["fill_ts_us"] == START_US + 2_000_000

    full = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.5,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert full["fill_fraction"] == 1.0


def test_sells_are_filled_by_buy_aggressors_only() -> None:
    wrong_side = [_trade(1, 101.0, 10.0, buy_aggressor=False)]  # seller crossed: lifts nothing
    result = fills.tape_fill(
        wrong_side,
        side="sell",
        limit=101.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert result["fill_fraction"] == 0.0
    assert result["miss_reason"] == "NO_AGGRESSOR_AT_LIMIT"

    right_side = [_trade(1, 101.0, 2.0, buy_aggressor=True)]
    filled = fills.tape_fill(
        right_side,
        side="sell",
        limit=101.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert filled["fill_fraction"] == 1.0


def test_trades_before_the_order_arrives_cannot_fill_it() -> None:
    trades = [_trade(0.1, 100.0, 5.0, buy_aggressor=False)]
    result = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US + 500_000,  # 500 ms of latency
        horizon_us=5 * MINUTE_US,
    )
    assert result["fill_fraction"] == 0.0


def test_trades_after_the_horizon_cannot_fill_it() -> None:
    trades = [_trade(600, 100.0, 5.0, buy_aggressor=False)]
    result = fills.tape_fill(
        trades,
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=5 * MINUTE_US,
    )
    assert result["fill_fraction"] == 0.0
    assert result["horizon_seconds"] == 300.0


def test_limit_price_is_inclusive_for_both_sides() -> None:
    buy = fills.tape_fill(
        [_trade(1, 100.0, 2.0, buy_aggressor=False)],
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=MINUTE_US,
    )
    sell = fills.tape_fill(
        [_trade(1, 100.0, 2.0, buy_aggressor=True)],
        side="sell",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=0.0,
        start_us=START_US,
        horizon_us=MINUTE_US,
    )
    assert buy["fill_fraction"] == 1.0
    assert sell["fill_fraction"] == 1.0


def test_levels_are_set_from_the_fill_price() -> None:
    stop, target = fills.levels(100.0, "buy")
    assert stop == pytest.approx(99.5)
    assert target == pytest.approx(100.75)
    stop, target = fills.levels(100.0, "sell")
    assert stop == pytest.approx(100.5)
    assert target == pytest.approx(99.25)


def test_exit_prefers_the_stop_when_one_minute_holds_both_levels() -> None:
    bars = _bars(
        [
            (100.0, 100.2, 99.9, 100.0),
            (100.0, 101.0, 99.0, 100.0),  # both levels inside one minute
        ]
    )
    result = fills.exit_path(
        bars, side="buy", entry=100.0, start_index=1, end_index=1, stop_friction_bps=2.0
    )
    assert result["exit_reason"] == "stop_loss"
    assert result["exit_price"] == pytest.approx(99.5 / 1.0002)


def test_a_gap_through_the_stop_fills_at_the_open() -> None:
    bars = _bars([(100.0, 100.1, 99.9, 100.0), (98.0, 98.2, 97.9, 98.0)])
    result = fills.exit_path(
        bars, side="buy", entry=100.0, start_index=1, end_index=1, stop_friction_bps=0.0
    )
    assert result["exit_reason"] == "stop_loss"
    assert result["gapped"] is True
    assert result["exit_price"] == pytest.approx(98.0)


def test_target_is_paid_at_its_own_level_without_friction() -> None:
    bars = _bars([(100.0, 100.1, 99.9, 100.0), (100.0, 100.9, 99.9, 100.8)])
    result = fills.exit_path(
        bars, side="buy", entry=100.0, start_index=1, end_index=1, stop_friction_bps=5.0
    )
    assert result["exit_reason"] == "take_profit"
    assert result["exit_price"] == pytest.approx(100.75)


def test_aggregate_counts_misses_in_the_denominator() -> None:
    rows = [
        {"fill_fraction": 1.0, "status": "CLOSED", "net_usdt": 2.0, "gross_usdt": 3.0,
         "entry_fee_usdt": 0.5, "exit_fee_usdt": 0.5, "exit_reason": "take_profit",
         "miss_reason": None, "adverse_1m_bps": 1.0, "adverse_5m_bps": 1.0,
         "adverse_15m_bps": 1.0, "minutes_held": 10, "seconds_to_fill": 3.0, "gapped": False},
        {"fill_fraction": 0.0, "status": "MISS", "net_usdt": 0.0, "gross_usdt": 0.0,
         "entry_fee_usdt": 0.0, "exit_fee_usdt": 0.0, "exit_reason": None,
         "miss_reason": "NO_AGGRESSOR_AT_LIMIT", "adverse_1m_bps": None, "adverse_5m_bps": None,
         "adverse_15m_bps": None, "minutes_held": 0, "seconds_to_fill": None, "gapped": False},
    ]
    summary = fills.aggregate(rows, signals=2)
    assert summary["filled"] == 1
    assert summary["fill_rate"] == pytest.approx(0.5)
    assert summary["net_per_signal_usdt"] == pytest.approx(1.0)
    assert summary["net_per_fill_usdt"] == pytest.approx(2.0)
    assert summary["miss_reasons"] == {"NO_AGGRESSOR_AT_LIMIT": 1}


def test_negative_queue_multiple_is_rejected_by_the_engine() -> None:
    """A negative queue would be a free fill; the helper clamps it, and the design never asks."""

    result = fills.tape_fill(
        [_trade(1, 100.0, 1.0, buy_aggressor=False)],
        side="buy",
        limit=100.0,
        order_qty=1.0,
        queue_multiple=-3.0,
        start_us=START_US,
        horizon_us=MINUTE_US,
    )
    assert result["queue_ahead"] == 0.0
    assert result["fill_fraction"] == 1.0


def test_window_slice_takes_only_the_relevant_trades() -> None:
    trades = [_trade(offset, 100.0, 1.0, buy_aggressor=False) for offset in (0, 60, 600, 900)]
    stamps = [row[0] for row in trades]
    sliced = fills.window_slice(trades, stamps, START_US + 30_000_000, START_US + 700_000_000)
    assert [row[0] for row in sliced] == [trades[1][0], trades[2][0]]
