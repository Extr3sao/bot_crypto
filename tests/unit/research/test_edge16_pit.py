"""WP-EDGE-016 — point-in-time tests that fail on the WP-EDGE-015 code.

The defect these pin down was measured before it was repaired: every exit test in
the families read the **current** bar's close and filled at that same bar's
**open**, a price that had already happened before the close existed. 100 % of the
published exits were filled that way.

So the tests here are not "the new code runs". They are:

* the indicators the streaming machine keeps agree with the vectorised ones;
* the rules fire on exactly the same signal bars as before (the repair is the
  fill instant, not a different strategy);
* the fill instant moves by exactly one bar, and no further;
* ``audit_trade`` reports the old rows as violations, so the audit that passes on
  the new rows is not vacuous;
* a truncated prefix reproduces the full run up to that point — late bars cannot
  retroactively change earlier decisions;
* the streaming use of the machine (one bar at a time, as the paper lane does it)
  produces the same trades as running it to completion.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from trading_bot.research.economic_recovery import alpha15 as A
from trading_bot.research.economic_recovery.experiments import Bar, load_ohlcv
from trading_bot.research.economic_recovery.pit15 import (
    Atr,
    Ema,
    PercentileRank,
    RollingExtreme,
    RollingStdev,
    RollingSum,
    audit_trade,
    machine_for,
)

REPO = Path(__file__).resolve().parents[3]
SERIES = {
    symbol: load_ohlcv(REPO / "data" / "edge07" / "holdout-1h" / f"{symbol}_holdout2026.json")[
        -2000:
    ]
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
}

EXPLOIT = "exit filled at or before its own signal bar"


def _index_of(bars: list[Bar], ts_ms: int) -> int:
    return next(index for index, bar in enumerate(bars) if bar.ts_ms == ts_ms)


# --- 1. the streaming indicators agree with the vectorised ones -------------------------


def test_incremental_indicators_reproduce_the_vectorised_ones() -> None:
    bars = SERIES["BTCUSDT"]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]

    for span in (20, 48, 200):
        sma, stdev = RollingSum(span), RollingStdev(span)
        ema = Ema(span)
        want_sma, want_stdev, want_ema = (
            A._sma(closes, span),
            A._stdev(closes, span),
            A._ema(closes, span),
        )
        for index, bar in enumerate(bars):
            got_sma, got_stdev, got_ema = (
                sma.update(bar.close),
                stdev.update(bar.close),
                ema.update(bar.close),
            )
            for got, want, label in (
                (got_sma, want_sma[index], f"sma{span}"),
                (got_stdev, want_stdev[index], f"stdev{span}"),
                (got_ema, want_ema[index], f"ema{span}"),
            ):
                if want is None:
                    assert got is None, f"{label} at {index} should be undefined"
                else:
                    assert got is not None and math.isclose(
                        got, want, rel_tol=0, abs_tol=1e-9
                    ), f"{label} at {index}: {got} != {want}"

    atr, rank = Atr(24), PercentileRank(720)
    atr_series = A._atr(bars, 24)
    rank_series = A._percentile_rank(atr_series, 720)
    for index, bar in enumerate(bars):
        got_atr, want_atr = atr.update(bar), atr_series[index]
        if want_atr is None:
            assert got_atr is None
        else:
            assert got_atr is not None and math.isclose(got_atr, want_atr, rel_tol=0, abs_tol=1e-9)
        got_rank = rank.update(None if got_atr is None else got_atr)
        want_rank = rank_series[index]
        if want_rank is None:
            assert got_rank is None
        else:
            assert got_rank is not None and math.isclose(got_rank, want_rank, rel_tol=0, abs_tol=1e-9)

    for span, biggest in ((168, True), (168, False)):
        values = [bar.high for bar in bars] if biggest else [bar.low for bar in bars]
        twin = A._rolling_max(values, span) if biggest else A._rolling_min(values, span)
        extreme = RollingExtreme(span, biggest=biggest)
        for index, _bar in enumerate(bars):
            got, want = extreme.update(values[index]), twin[index]
            assert got == want

    from statistics import median

    from trading_bot.research.economic_recovery.pit15 import VolumeMedian

    volume_machine = VolumeMedian(168)
    for index, bar in enumerate(bars[:1001]):
        got = volume_machine.update(bar.volume)
        want = median(volumes[max(0, index - 168 + 1) : index + 1]) if index > 0 else None
        if want is None:
            assert got is None
        else:
            assert got == pytest.approx(want), f"volume median at {index}"


# --- 2. the rules fire on the same signal bars; only the fill moves ---------------------


@pytest.mark.parametrize("symbol", sorted(SERIES))
@pytest.mark.parametrize("family_name", sorted(A.PRE_PIT_RUNNERS))
def test_the_repair_moves_the_exit_fill_by_exactly_one_bar(family_name: str, symbol: str) -> None:
    bars = SERIES[symbol]
    family = A.FAMILY_BY_NAME[family_name]
    old = A.PRE_PIT_RUNNERS[family_name](bars, family.parameters)
    new = A.family_trades(family, bars)

    by_entry: dict[int, dict] = {trade["entry_fill_index"]: trade for trade in new}
    matched = 0
    for old_trade in old:
        entry_index = _index_of(bars, old_trade["entry_ts_ms"])
        exit_index = _index_of(bars, old_trade["exit_ts_ms"])
        candidate = by_entry.get(entry_index)
        if candidate is None:
            continue
        assert candidate["exit_signal_index"] in (exit_index, exit_index + 1), (
            f"{family_name}/{symbol}: the signal moved, not just the fill"
        )
        if candidate["exit_signal_index"] == exit_index:
            assert candidate["exit_fill_index"] == exit_index + 1, (
                f"{family_name}/{symbol}: an exit signal at bar {exit_index} must fill at "
                f"{exit_index + 1}, got {candidate['exit_fill_index']}"
            )
        matched += 1
    assert matched, f"{family_name}/{symbol}: no trade matched, the comparison proved nothing"


def test_every_pre_pit_exit_is_a_violation_of_the_contract() -> None:
    """The audit that passes on the new rows must fail on the old ones."""
    bars = SERIES["BTCUSDT"]
    family = A.FAMILY_BY_NAME["vol_regime_breakout"]
    old = A.PRE_PIT_RUNNERS["vol_regime_breakout"](bars, family.parameters)
    assert old, "the pre-PIT rule produced nothing to audit"
    for old_trade in old:
        exit_index = _index_of(bars, old_trade["exit_ts_ms"])
        fabricated = {
            "entry_ts_ms": old_trade["entry_ts_ms"],
            "exit_ts_ms": old_trade["exit_ts_ms"],
            "entry_data_available_ms": old_trade["entry_ts_ms"],
            "exit_data_available_ms": old_trade["exit_ts_ms"],
            "entry_earliest_fill_ms": old_trade["entry_ts_ms"],
            "exit_earliest_fill_ms": old_trade["exit_ts_ms"],
            "entry_fill_index": _index_of(bars, old_trade["entry_ts_ms"]),
            "exit_fill_index": exit_index,
            "exit_signal_index": exit_index,
            "entry_signal_index": _index_of(bars, old_trade["entry_ts_ms"]) - 1,
            "is_mark": False,
            "exit_rule": "PRE_PIT_SAME_BAR",
        }
        violations = audit_trade(fabricated)
        assert any(EXPLOIT in item for item in violations), (
            "the old same-bar close-to-open exit must be reported as a violation"
        )


def test_no_pit_violation_survives_in_the_repaired_rules() -> None:
    for symbol in sorted(SERIES):
        for family in A.SINGLE_ASSET_FAMILIES:
            trades = A.family_trades(family, SERIES[symbol])
            assert trades, f"{family.name}/{symbol} produced no trades at all"
            for trade in trades:
                assert audit_trade(trade) == [], (family.name, symbol, audit_trade(trade))


# --- 3. truncation invariance: late bars cannot rewrite earlier decisions ---------------


@pytest.mark.parametrize("family_name", sorted(A.PRE_PIT_RUNNERS))
def test_a_truncated_prefix_reproduces_the_full_run_up_to_that_point(family_name: str) -> None:
    bars = SERIES["BTCUSDT"]
    family = A.FAMILY_BY_NAME[family_name]
    full = A.family_trades(family, bars)
    for cut in (1500, 1750, 1900):
        prefix = A.family_trades(family, bars[:cut])
        closed = [trade for trade in prefix if not trade["is_mark"]]
        assert [trade["exit_fill_index"] for trade in closed] == [
            trade["exit_fill_index"] for trade in full if trade["exit_fill_index"] < cut
        ], f"{family_name}: the prefix disagrees with the full run at cut {cut}"
        assert len(prefix) - len(closed) <= 1, "at most one position can be open at the end"


# --- 4. the machine is the same object the lane drives ---------------------------------


def test_streaming_the_machine_one_bar_at_a_time_reproduces_the_batch_run() -> None:
    bars = SERIES["ETHUSDT"]
    for family in A.SINGLE_ASSET_FAMILIES:
        machine = machine_for(family.name, family.parameters)
        streamed: list[tuple[str, int]] = []
        in_position = False
        pending = None
        for index, bar in enumerate(bars):
            # the lane's usage pattern: resolve the fill first, tell the machine about
            # it, then let the machine see the bar that has just closed
            if pending is not None and pending.fill_index == index:
                machine.notify_fill(pending.kind, index, bar.open)
                in_position = pending.kind == "ENTRY"
                pending = None
            decision = machine.on_closed_bar(index, bar, in_position=in_position)
            if decision is not None:
                streamed.append((decision.kind, decision.signal_index))
                pending = decision if decision.fill_index < len(bars) else None
        batch = A.family_trades(family, bars)
        expected: list[tuple[str, int]] = []
        for trade in batch:
            expected.append(("ENTRY", int(trade["entry_signal_index"])))
            expected.append(("EXIT", int(trade["exit_signal_index"])))
        # the streaming view resolves no prices, but must agree on the signals
        assert streamed == expected, (
            f"{family.name}: the streaming machine and the batch driver disagree"
        )
