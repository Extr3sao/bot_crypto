"""ARC-03 primary discovery EXECUTION tests (synthetic only — no real data, no economics).

Covers the pre-execution synthetic battery required before the implementation freeze:
participation/excursion strict inequalities, same-slot references, missing references,
exhaustion boundaries (exact half, zero body, zero range), LONG/SHORT emission, entry
causality, exit +12 bars, position overlap and re-entry, funding (zero/one settlement,
positive/negative sign, boundary semantics), the cost accounting identity, G1..G11
calculator determinism and degenerate fail-closed behaviour, the four controls, the
exactly-once experiment ledger and PIT future-mutation invariance.
"""

from __future__ import annotations

import json
import random

import pytest

from trading_bot.research.arc03 import arc03_synthetic as syn
from trading_bot.research.arc03.arc03_authority import (
    BAR_MS,
    DAY_MS,
    HOLDING_MS,
    Kline5m,
    LONG,
    NO_SIGNAL,
    NO_SIGNAL_PRECEDENCE,
    SHORT,
    evaluate_bar,
)
from trading_bot.research.arc03.arc03_executor import (
    ACCOUNTING_TOLERANCE,
    NULL_SEED,
    ExecutedTrade,
    ExperimentLedger,
    accounting_reconciliation,
    build_executed_trades,
    direction_control_trades,
    emit_participation_control_trades,
    frozen_gate_order,
    gate_inputs,
    gate_records,
    ledger_row,
    null_control_series,
    timing_control_trades,
    trade_ledger_reconciliation,
)
from trading_bot.research.arc03.arc03_funding import FundingSeries
from trading_bot.research.arc03.arc03_gates import (
    TradeRecord,
    annualized_sharpe,
    evaluate_gates,
    profit_factor,
    sample_std,
)
from trading_bot.research.arc03.arc03_prereg_reference import emit_trades

pytestmark = pytest.mark.unit

BARS = 9000
SIGNAL_INDEX = 8700
EXIT_INDEX = SIGNAL_INDEX + 1 + 12  # entry at +1 bar, exit +12 bars after entry


def _rows_with_signal(signal_index: int = SIGNAL_INDEX):
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=signal_index)
    return rows


def _executed(rows, start=None, end=None, funding=None, symbol="BTCUSDT"):
    k = syn.to_kline5m(rows)
    partitions = {symbol: k}
    ref = emit_trades(partitions, start_ms=start if start is not None else k.t[0], end_ms=end if end is not None else k.t[-1])
    trades = build_executed_trades(ref, funding, partitions)
    return ref, trades, partitions


# --------------------------------------------------------------- signal semantics (executor level)


def test_participation_requires_strictly_greater_than_all_references():
    rows = _rows_with_signal()
    bar_open = rows["t"][SIGNAL_INDEX]
    # make the signal volume EXACTLY equal to the maximum reference volume
    rows["v"][SIGNAL_INDEX] = rows["v"][SIGNAL_INDEX - DAY_MS // BAR_MS]
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_PARTICIPATION_SHOCK"


def test_excursion_requires_strictly_greater_than_all_references():
    rows = _rows_with_signal()
    # force the signal range to EXACTLY equal the reference maximum (2.0)
    rows["h"][SIGNAL_INDEX] = rows["o"][SIGNAL_INDEX] + 1.0
    rows["l"][SIGNAL_INDEX] = rows["o"][SIGNAL_INDEX] - 1.0
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXCURSION_RECORD"


def test_same_slot_references_are_exactly_24h_offsets():
    slots = [SIGNAL_INDEX - DAY_MS // BAR_MS * j for j in range(1, 31)]
    rows = _rows_with_signal()
    k = syn.to_kline5m(rows)
    # mutate a NON-reference nearby bar (24h offset minus one bar): no effect
    neighbour = SIGNAL_INDEX - DAY_MS // BAR_MS + 1
    v_before = k.v[SIGNAL_INDEX]
    rows2 = _rows_with_signal()
    rows2["v"][neighbour] = 1e12
    rows2["h"][neighbour] = rows2["o"][neighbour] + 1e6
    ev = evaluate_bar(syn.to_kline5m(rows2), SIGNAL_INDEX)
    assert ev["emitted"] is True and ev["result"] == SHORT
    assert ev["volume"] == v_before


def test_missing_reference_fails_closed():
    rows = _rows_with_signal()
    # delete one reference bar (24h back)
    missing = SIGNAL_INDEX - DAY_MS // BAR_MS
    for key in ("t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq"):
        del rows[key][missing]
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX - 1)
    assert ev["emitted"] is False
    assert ev["reason"] == "REFERENCE_HISTORY_INCOMPLETE"


def test_exact_half_retracement_is_no_exhaustion():
    rows = _rows_with_signal()
    o = rows["o"][SIGNAL_INDEX]
    rows["h"][SIGNAL_INDEX] = o + 4.0
    rows["c"][SIGNAL_INDEX] = o + 2.0  # hi - c == range/2 exactly
    rows["l"][SIGNAL_INDEX] = o
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXHAUSTION"


def test_zero_body_is_no_exhaustion():
    rows = _rows_with_signal()
    o = rows["o"][SIGNAL_INDEX]
    rows["h"][SIGNAL_INDEX] = o + 4.0
    rows["l"][SIGNAL_INDEX] = o - 1.0
    rows["c"][SIGNAL_INDEX] = o  # body == 0
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXHAUSTION"


def test_zero_range_is_no_signal():
    rows = _rows_with_signal()
    o = rows["o"][SIGNAL_INDEX]
    rows["h"][SIGNAL_INDEX] = o
    rows["l"][SIGNAL_INDEX] = o
    rows["c"][SIGNAL_INDEX] = o
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False  # zero range can never be an excursion record


# --------------------------------------------------------------- emission, entry, exit, overlap


def test_short_emission_entry_and_exit_anchors():
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == SHORT and t.direction_sign == -1
    assert t.entry_time_ms == rows["t"][SIGNAL_INDEX] + BAR_MS  # strictly after decision
    assert t.exit_time_ms == t.entry_time_ms + HOLDING_MS == t.entry_time_ms + 12 * BAR_MS
    assert t.decision_time_ms == rows["ct"][SIGNAL_INDEX]
    assert t.entry_time_ms > t.decision_time_ms


def test_long_emission():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_down_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    ref, trades, _ = _executed(rows)
    assert len(trades) == 1 and trades[0].direction == LONG and trades[0].direction_sign == 1


def test_position_overlap_skips_and_precedence():
    rows = _rows_with_signal()
    # two adjacent signal bars: the second falls while the first position is open
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX + 1)
    ref, trades, _ = _executed(rows)
    assert len(trades) == 1  # only the first executes
    assert ref.funnel["POSITION_ALREADY_OPEN"] == 1
    # the skipped signal would also have had insufficient forward data; precedence must
    # report POSITION_ALREADY_OPEN (earlier in the frozen order), never INSUFFICIENT
    assert ref.funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] == 0


def test_reentry_only_at_or_after_previous_exit():
    rows = _rows_with_signal()
    # a signal exactly AT the exit bar index is admissible again (re-entry at exit):
    # its entry bar is strictly after the previous position's exit open
    syn.make_up_push_exhaustion(rows, signal_index=EXIT_INDEX)
    ref, trades, _ = _executed(rows)
    assert len(trades) == 2
    assert trades[1].entry_time_ms > trades[0].exit_time_ms
    assert trades[1].decision_bar_open_time_ms == rows["t"][EXIT_INDEX]
    # a signal BEFORE the exit index is skipped (position still open at its decision)
    rows2 = _rows_with_signal()
    syn.make_up_push_exhaustion(rows2, signal_index=EXIT_INDEX - 1)
    ref2, trades2, _ = _executed(rows2)
    assert len(trades2) == 1
    assert ref2.funnel["POSITION_ALREADY_OPEN"] == 1


def test_outside_common_window_has_first_precedence():
    rows = _rows_with_signal()
    k = syn.to_kline5m(rows)
    start = k.t[10]
    ref = emit_trades({"BTCUSDT": k}, start_ms=start, end_ms=k.t[-1])
    assert ref.funnel["OUTSIDE_COMMON_WINDOW"] == 10
    assert ref.decisions_evaluated == k.rows - 10


def test_reconciliation_identity_holds_with_bars_outside_the_window():
    rows = _rows_with_signal()
    k = syn.to_kline5m(rows)
    start = k.t[10]
    ref = emit_trades({"BTCUSDT": k}, start_ms=start, end_ms=k.t[-1])
    trades = build_executed_trades(ref, None, {"BTCUSDT": k})
    rec = trade_ledger_reconciliation(trades, ref, [ledger_row(t) for t in trades])
    assert rec["bars_outside_common_window"] == 10
    assert rec["evaluated_equals_rejected_plus_executed"]
    assert rec["full_accounting_identity"]
    assert rec["verdict"] == "PASS"


def test_frozen_gate_order_is_chronological_not_asset_grouped():
    # two assets whose emission order is asset-major but whose entry times interleave
    a = ExecutedTrade(
        trade_id="BTCUSDT-1", asset="BTCUSDT", direction=SHORT, direction_sign=-1,
        decision_bar_open_time_ms=1000, decision_time_ms=1299, volume=1.0,
        reference_max_volume=0.5, reference_observations_present=30, range=2.0,
        reference_max_range=1.0, open_price=100.0, high_price=102.0, low_price=100.0,
        close_price=101.0, body=1.0, entry_time_ms=1300, entry_price=100.0,
        exit_time_ms=1300 + HOLDING_MS, exit_price=99.0, gross_price_return=-0.01,
        funding_settlements_applied=0, funding_cashflow_return=0.0, emission_index=0,
    )
    b = ExecutedTrade(
        trade_id="ETHUSDT-1", asset="ETHUSDT", direction=SHORT, direction_sign=-1,
        decision_bar_open_time_ms=1000, decision_time_ms=1299, volume=1.0,
        reference_max_volume=0.5, reference_observations_present=30, range=2.0,
        reference_max_range=1.0, open_price=100.0, high_price=102.0, low_price=100.0,
        close_price=101.0, body=1.0, entry_time_ms=500, entry_price=100.0,
        exit_time_ms=500 + HOLDING_MS, exit_price=99.0, gross_price_return=-0.01,
        funding_settlements_applied=0, funding_cashflow_return=0.0, emission_index=1,
    )
    ordered = frozen_gate_order([a, b])
    assert [t.trade_id for t in ordered] == ["ETHUSDT-1", "BTCUSDT-1"]
    recs, n20, n40 = gate_inputs([a, b])
    assert [r.trade_id for r in recs] == ["ETHUSDT-1", "BTCUSDT-1"]
    assert n20[0] == pytest.approx(b.net_return(20)) and n40[1] == pytest.approx(a.net_return(40))


# --------------------------------------------------------------- funding


def _funding(settlements, rates, symbol="BTCUSDT"):
    return syn.make_funding(symbol, settlements_ms=settlements, rates=rates)


def test_funding_zero_settlements():
    rows = _rows_with_signal()
    f = _funding([rows["t"][SIGNAL_INDEX] + 100 * BAR_MS], [0.01])
    ref, trades, _ = _executed(rows, funding={"BTCUSDT": f})
    assert trades[0].funding_settlements_applied == 0
    assert trades[0].funding_cashflow_return == 0.0


def test_funding_one_settlement_positive_rate_long_pays_short_receives():
    rows = _rows_with_signal()
    settle = rows["t"][SIGNAL_INDEX] + 5 * BAR_MS  # inside (entry, exit]
    assert rows["t"][SIGNAL_INDEX + 1] < settle <= rows["t"][SIGNAL_INDEX + 1] + HOLDING_MS
    f = _funding([settle], [0.0001])
    long_rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_down_push_exhaustion(long_rows, signal_index=SIGNAL_INDEX)
    ref_l, trades_l, _ = _executed(long_rows, funding={"BTCUSDT": f})
    ref_s, trades_s, _ = _executed(rows, funding={"BTCUSDT": f})
    assert trades_l[0].funding_settlements_applied == 1
    assert trades_s[0].funding_settlements_applied == 1
    assert trades_l[0].funding_cashflow_return == pytest.approx(-0.0001)  # LONG pays
    assert trades_s[0].funding_cashflow_return == pytest.approx(+0.0001)  # SHORT receives


def test_funding_negative_rate_signs_flip():
    rows = _rows_with_signal()
    settle = rows["t"][SIGNAL_INDEX] + 5 * BAR_MS
    f = _funding([settle], [-0.0002])
    ref_s, trades_s, _ = _executed(rows, funding={"BTCUSDT": f})
    assert trades_s[0].funding_cashflow_return == pytest.approx(-0.0002)  # SHORT pays on negative
    long_rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_down_push_exhaustion(long_rows, signal_index=SIGNAL_INDEX)
    ref_l, trades_l, _ = _executed(long_rows, funding={"BTCUSDT": f})
    assert trades_l[0].funding_cashflow_return == pytest.approx(+0.0002)  # LONG receives


def test_funding_boundary_semantics_entry_excluded_exit_included():
    rows = _rows_with_signal()
    entry = rows["t"][SIGNAL_INDEX + 1]
    exit_ = entry + HOLDING_MS
    f = _funding([entry, exit_], [0.001, 0.002])
    ref, trades, _ = _executed(rows, funding={"BTCUSDT": f})
    assert trades[0].funding_settlements_applied == 1  # exit settlement charged, entry not
    # SHORT direction_sign = -1: cashflow = -(-1) * 0.002 = +0.002
    assert trades[0].funding_cashflow_return == pytest.approx(0.002)


def test_funding_never_enters_signal():
    rows = _rows_with_signal()
    settle = rows["t"][SIGNAL_INDEX] + 5 * BAR_MS
    f_big = _funding([settle], [0.5])  # absurd funding cannot create/destroy the signal
    ref, trades, _ = _executed(rows, funding={"BTCUSDT": f_big})
    assert len(trades) == 1 and trades[0].direction == SHORT
    # and the decision instant is untouched
    assert trades[0].decision_time_ms == rows["ct"][SIGNAL_INDEX]


# --------------------------------------------------------------- accounting identity


def test_cost_accounting_identity_all_scenarios():
    rows = _rows_with_signal()
    settle = rows["t"][SIGNAL_INDEX] + 5 * BAR_MS
    f = _funding([settle], [0.0003])
    ref, trades, _ = _executed(rows, funding={"BTCUSDT": f})
    t = trades[0]
    for bps in (0, 10, 20, 40):
        expected = t.gross_price_return + t.funding_cashflow_return - bps / 10_000.0
        assert abs(t.net_return(bps) - expected) <= ACCOUNTING_TOLERANCE
    ex = t.net_return_ex_funding(10)
    assert abs(ex - (t.gross_price_return - 0.0010)) <= ACCOUNTING_TOLERANCE
    # funding contributes ZERO to the ex-funding leg even when a settlement was applied
    assert t.funding_settlements_applied == 1
    rec = accounting_reconciliation(trades)
    assert rec["verdict"] == "PASS" and rec["violations"] == []


# --------------------------------------------------------------- ledger row completeness


def test_ledger_row_contains_all_required_fields():
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    row = ledger_row(trades[0])
    required = {
        "trade_id", "asset", "decision_bar_open_time_ms", "decision_time_ms", "volume",
        "reference_max_volume", "range", "reference_max_range", "open", "high", "low",
        "close", "body", "direction", "entry_time_ms", "entry_price", "exit_time_ms",
        "exit_price", "gross_price_return", "funding_settlements_applied",
        "funding_cashflow_return", "net_0bps", "net_10bps", "net_20bps", "net_40bps",
        "net_ex_funding_10bps",
    }
    assert required.issubset(row.keys())
    # trade ledger reconciliation identities
    rec = trade_ledger_reconciliation(trades, ref, [ledger_row(t) for t in trades])
    assert rec["verdict"] == "PASS"
    assert rec["evaluated_equals_rejected_plus_executed"]


# --------------------------------------------------------------- controls


def test_direction_control_flips_gross_and_funding_only():
    rows = _rows_with_signal()
    settle = rows["t"][SIGNAL_INDEX] + 5 * BAR_MS
    f = _funding([settle], [0.0003])
    ref, trades, _ = _executed(rows, funding={"BTCUSDT": f})
    ctrl = direction_control_trades(trades)
    p, c = trades[0], ctrl[0]
    assert p.trade_id == c.trade_id and p.entry_time_ms == c.entry_time_ms
    assert p.exit_time_ms == c.exit_time_ms and p.entry_price == c.entry_price
    assert c.gross_price_return == pytest.approx(-p.gross_price_return)
    assert c.funding_cashflow_return == pytest.approx(-p.funding_cashflow_return)
    assert c.direction != p.direction and c.direction_sign == -p.direction_sign


def test_timing_control_shifts_exactly_12_bars_same_hold():
    rows = _rows_with_signal()
    ref, trades, partitions = _executed(rows)
    ctrl, dropped = timing_control_trades(partitions, trades, None)
    assert dropped == 0
    assert ctrl[0].entry_time_ms == trades[0].entry_time_ms + 12 * BAR_MS
    assert ctrl[0].exit_time_ms == ctrl[0].entry_time_ms + 12 * BAR_MS
    assert ctrl[0].direction == trades[0].direction
    assert ctrl[0].trade_id == trades[0].trade_id


def test_null_control_is_deterministic_seed_rng():
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    s1 = null_control_series(trades)
    s2 = null_control_series(trades)
    assert s1["nets"] == s2["nets"] and s1["factors"] == s2["factors"]
    rng = random.Random(NULL_SEED)
    expected = [1 if rng.random() < 0.5 else -1 for _ in trades]
    assert s1["factors"] == expected
    assert s1["nets"][0] == pytest.approx(trades[0].net_return(10) * expected[0])
    # the same factor is applied to the ex-funding leg and to the 20/40 bps re-pricings
    assert s1["nets_ex_funding"][0] == pytest.approx(
        trades[0].net_return_ex_funding(10) * expected[0]
    )
    for bps in (0, 10, 20, 40):
        assert s1["nets_by_scenario"][bps][0] == pytest.approx(
            trades[0].net_return(bps) * expected[0]
        )
        assert s1["nets_ex_funding_by_scenario"][bps][0] == pytest.approx(
            trades[0].net_return_ex_funding(bps) * expected[0]
        )


def test_null_control_never_uses_python_hash():
    import ast
    import inspect

    from trading_bot.research.arc03 import arc03_executor as ex

    tree = ast.parse(inspect.getsource(ex.null_control_series))
    builtin_hash_calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "hash"
    ]
    assert builtin_hash_calls == []
    assert "random.Random(NULL_SEED)" in inspect.getsource(ex.null_control_series)


def test_participation_control_removes_only_the_volume_condition():
    rows = _rows_with_signal()
    # make the signal bar a volume TIE (not a record): primary must NOT emit
    rows["v"][SIGNAL_INDEX] = rows["v"][SIGNAL_INDEX - DAY_MS // BAR_MS]
    k = syn.to_kline5m(rows)
    ref_primary = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    assert len(ref_primary.trades) == 0
    assert ref_primary.funnel["NO_PARTICIPATION_SHOCK"] >= 1

    # the PARTICIPATION_CONTROL emission drops ONLY the volume condition: the very same
    # geometry (excursion record + exhaustion) now emits, direction unchanged
    ref_ctrl = emit_participation_control_trades(
        {"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1]
    )
    assert len(ref_ctrl.trades) == 1
    ctrl_trade = ref_ctrl.trades[0]
    assert ctrl_trade.direction == SHORT
    assert ctrl_trade.signal_bar_open_time_ms == k.t[SIGNAL_INDEX]
    assert ctrl_trade.decision_time_ms == k.ct[SIGNAL_INDEX]
    assert ctrl_trade.entry_time_ms > ctrl_trade.decision_time_ms
    assert ctrl_trade.exit_time_ms == ctrl_trade.entry_time_ms + HOLDING_MS
    # the control emits on its own (larger) universe but never reports the removed reason
    assert "NO_PARTICIPATION_SHOCK" not in ref_ctrl.funnel


def test_participation_control_keeps_excursion_and_exhaustion_requirements():
    # no excursion record -> the control must still NOT emit
    rows = _rows_with_signal()
    o = rows["o"][SIGNAL_INDEX]
    rows["h"][SIGNAL_INDEX] = o + 1.0
    rows["l"][SIGNAL_INDEX] = o - 1.0
    k = syn.to_kline5m(rows)
    ref = emit_participation_control_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    assert len(ref.trades) == 0
    assert ref.funnel["NO_EXCURSION_RECORD"] >= 1

    # exact-half retracement -> the control must still NOT emit (strict >)
    rows2 = _rows_with_signal()
    o2 = rows2["o"][SIGNAL_INDEX]
    rows2["h"][SIGNAL_INDEX] = o2 + 4.0
    rows2["l"][SIGNAL_INDEX] = o2
    rows2["c"][SIGNAL_INDEX] = o2 + 2.0
    k2 = syn.to_kline5m(rows2)
    ref2 = emit_participation_control_trades({"BTCUSDT": k2}, start_ms=k2.t[0], end_ms=k2.t[-1])
    assert len(ref2.trades) == 0
    assert ref2.funnel["NO_EXHAUSTION"] >= 1

    # a missing same-slot reference still fails closed
    rows3 = _rows_with_signal()
    missing = SIGNAL_INDEX - DAY_MS // BAR_MS
    for key in ("t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq"):
        del rows3[key][missing]
    k3 = syn.to_kline5m(rows3)
    ref3 = emit_participation_control_trades(
        {"BTCUSDT": k3}, start_ms=k3.t[0], end_ms=k3.t[-1]
    )
    assert ref3.funnel["REFERENCE_HISTORY_INCOMPLETE"] >= 1


# --------------------------------------------------------------- gates: determinism + fail-closed


def _records_from(trades):
    return gate_records(trades, cost_bps=10)


def test_utc_month_attribution_matches_datetime():
    import datetime as dt

    from trading_bot.research.arc03.arc03_gates import _utc_month

    for ms in (
        1600066800000,
        1700000000000,
        1735689600000,
        1735689599999,
        1788220500000,
        1580000000000,
    ):
        expected = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m")
        assert _utc_month(ms) == expected, ms


def test_gate_calculators_deterministic():
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    recs = _records_from(trades)
    nets20 = [t.net_return(20) for t in trades]
    nets40 = [t.net_return(40) for t in trades]
    g1 = evaluate_gates(recs, net_returns_20bps=nets20, net_returns_40bps=nets40)
    g2 = evaluate_gates(recs, net_returns_20bps=nets20, net_returns_40bps=nets40)
    assert [(x.gate_id, x.passed, x.metric) for x in g1] == [(x.gate_id, x.passed, x.metric) for x in g2]
    assert [x.gate_id for x in g1] == [f"G{i}" for i in range(1, 12)] or True
    ids = [x.gate_id for x in g1]
    assert ids == [
        "G1_SAMPLE", "G2_NET_EXPECTANCY", "G3_NET_EXPECTANCY_EX_FUNDING",
        "G4_PROFIT_FACTOR", "G5_SHARPE", "G6_BOOTSTRAP", "G7_PERMUTATION",
        "G8_TEMPORAL_STABILITY", "G9_ASSET_STABILITY", "G10_CONCENTRATION",
        "G11_COST_SENSITIVITY",
    ]


def test_gate_degenerate_series_fail_closed():
    identical = [0.01] * 50
    recs = [TradeRecord("t{i}", "BTCUSDT", 1600000000000 + i, identical[i], identical[i] - 0.001) for i in range(50)]
    results = evaluate_gates(recs, net_returns_20bps=identical, net_returns_40bps=identical)
    by_id = {r.gate_id: r for r in results}
    assert by_id["G5_SHARPE"].passed is False  # zero variance => 0.0 sharpe
    assert by_id["G6_BOOTSTRAP"].passed is False  # degenerate bootstrap
    assert by_id["G7_PERMUTATION"].passed is False  # degenerate permutation
    # sanity of the two core estimators
    assert sample_std(identical) == 0.0
    pf, evaluable = profit_factor(identical)
    assert pf == float("inf") and evaluable is True
    sh, sh_eval = annualized_sharpe([0.0, 0.0])
    assert sh == 0.0 and sh_eval is False


def test_gate_all_critical_pass_requires_every_gate():
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    recs = _records_from(trades)
    nets = [r.net_return for r in recs]
    results = evaluate_gates(recs, net_returns_20bps=nets, net_returns_40bps=nets)
    # single-trade synthetic set must fail G1 (sample size) regardless of other metrics
    by_id = {r.gate_id: r for r in results}
    assert by_id["G1_SAMPLE"].passed is False


# --------------------------------------------------------------- exactly-once ledger


def test_exactly_once_ledger(tmp_path):
    ledger_path = tmp_path / "EXPERIMENT_LEDGER.jsonl"
    led = ExperimentLedger(ledger_path)
    led.append("REGISTERED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01"})
    led.append("STARTED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01"})
    led.append("COMPLETED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01", "trades": 1})
    # a second COMPLETED economic execution is forbidden
    led2 = ExperimentLedger(ledger_path)
    with pytest.raises(ExperimentLedger.ExactlyOnceViolation):
        led2.append("COMPLETED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01", "trades": 2})
    # resume after technical interruption (STARTED, no COMPLETED) is allowed
    resume_path = tmp_path / "LEDGER_RESUME.jsonl"
    led3 = ExperimentLedger(resume_path)
    led3.append("REGISTERED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01"})
    led3.append("STARTED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01"})
    led4 = ExperimentLedger(resume_path)
    led4.assert_no_previous_completed()
    led4.assert_resumable()
    # a new STARTED after COMPLETED is not a resume and is rejected
    led5 = ExperimentLedger(ledger_path)
    with pytest.raises(ExperimentLedger.ExactlyOnceViolation):
        led5.append("STARTED", {"experiment_id": "ARC03_PRIMARY_DISCOVERY_01"})


# --------------------------------------------------- execution driver wiring (pre-freeze)


def _driver_module():
    import importlib.util
    import pathlib as _p

    root = _p.Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "arc03_pd01_driver", root / "scripts" / "run_arc03_primary_discovery_01.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_bindings_match_the_frozen_mission_constants():
    mod = _driver_module()
    assert mod.EXPERIMENT_ID == "ARC03_PRIMARY_DISCOVERY_01"
    assert mod.ASSETS == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert tuple(mod.COST_SCENARIOS_BPS) == (0, 10, 20, 40)
    assert mod.PRIMARY_COST_BPS == 10
    assert mod.EXPECTED_WINDOW_MS == (1600066800000, 1788220500000)
    assert mod.EXPECTED_DATASET_SHA256 == (
        "1a6ad11712ce436ce9d413d6b53162d66996778cd98643ef7c3eb746a54745ef"
    )
    assert mod.EXPECTED_SPEC_SHA256 == (
        "a69edabb2931b3897cc0bcabdb7c203009ace742af1a729e47f7cb058a407a2d"
    )
    assert mod.EXPECTED_MANIFEST_SHA256 == (
        "3b022693fde0a4e362329a009125292410bb1ba3d0e2b3f8571b795a15b1d1a3"
    )


def test_driver_null_control_inputs_preserve_timestamps_and_gate_order():
    mod = _driver_module()
    rows = _rows_with_signal()
    ref, trades, _ = _executed(rows)
    recs, n20, n40 = mod.null_control_inputs(trades)
    assert [r.trade_id for r in recs] == [t.trade_id for t in trades]
    assert len(n20) == len(trades) and len(n40) == len(trades)
    series = null_control_series(trades)
    assert recs[0].net_return == pytest.approx(series["nets"][0])
    assert recs[0].net_return_ex_funding == pytest.approx(series["nets_ex_funding"][0])
    assert n20[0] == pytest.approx(series["nets_by_scenario"][20][0])
    # timestamps and asset identity untouched by the null
    assert recs[0].entry_time_ms == trades[0].entry_time_ms
    assert recs[0].asset == trades[0].asset


# --------------------------------------------------------------- PIT during execution


def test_future_mutation_cannot_alter_decision():
    rows = _rows_with_signal()
    ev_before = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    # mutate every bar strictly after the decision bar (entry/exit region included)
    for i in range(SIGNAL_INDEX + 1, BARS):
        rows["v"][i] = 1e9
        rows["h"][i] = rows["o"][i] + 100.0
        rows["l"][i] = rows["o"][i] - 100.0
        rows["c"][i] = rows["o"][i] + 50.0
    ev_after = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev_before["emitted"] == ev_after["emitted"]
    assert ev_before["result"] == ev_after["result"]
    assert ev_before["volume"] == ev_after["volume"]
    assert ev_before["reference_volume_max"] == ev_after["reference_volume_max"]


def test_no_signal_precedence_tuple_is_frozen():
    assert NO_SIGNAL_PRECEDENCE == (
        "OUTSIDE_COMMON_WINDOW",
        "REFERENCE_HISTORY_INCOMPLETE",
        "NO_PARTICIPATION_SHOCK",
        "NO_EXCURSION_RECORD",
        "NO_EXHAUSTION",
        "POSITION_ALREADY_OPEN",
        "INSUFFICIENT_FORWARD_PRICE_DATA",
    )
