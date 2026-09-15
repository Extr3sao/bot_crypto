"""ARC-03 preregistration contract tests (performance-blind).

Exercises the FROZEN ARC-03 semantics on synthetic fixtures: the participation / excursion /
exhaustion conditions, the deterministic NO_SIGNAL precedence, strictly causal entry and exit,
the funding cashflow boundary and sign conventions, and the accounting identity.

No real economic quantity is computed in this file: no return on real data, no PnL, no
signal-return statistics.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from dataclasses import replace

from trading_bot.research.arc03 import arc03_synthetic as syn
from trading_bot.research.arc03.arc03_authority import (
    BAR_MS,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    HOLDING_BARS,
    HOLDING_MS,
    LONG,
    NO_SIGNAL,
    NO_SIGNAL_PRECEDENCE,
    NULL_SEED,
    PERMUTATION_ALPHA,
    PERMUTATION_DRAWS,
    PRIMARY_COST_BPS,
    SHORT,
    evaluate_bar,
)
from trading_bot.research.arc03.arc03_prereg_reference import emit_trades, trade_returns

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[3]
SPEC_PATH = REPO / "docs" / "arc03-prereg-01" / "ARC03_SPEC_V1.json"

BARS = 9000
SIGNAL_INDEX = 8700


def _short_fixture():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    return syn.to_kline5m(rows), rows


def _long_fixture():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_down_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    return syn.to_kline5m(rows), rows


# --- 1. directional semantics ---------------------------------------------------------


def test_up_push_exhaustion_is_short():
    k, _ = _short_fixture()
    ev = evaluate_bar(k, SIGNAL_INDEX)
    assert ev["emitted"] is True
    assert ev["result"] == SHORT


def test_down_push_exhaustion_is_long():
    k, _ = _long_fixture()
    ev = evaluate_bar(k, SIGNAL_INDEX)
    assert ev["emitted"] is True
    assert ev["result"] == LONG


def test_direction_is_contrarian_to_the_rejected_push():
    k_up, _ = _short_fixture()
    k_dn, _ = _long_fixture()
    assert evaluate_bar(k_up, SIGNAL_INDEX)["result"] == SHORT   # up-push rejected -> short
    assert evaluate_bar(k_dn, SIGNAL_INDEX)["result"] == LONG    # down-push rejected -> long


# --- 2. condition boundaries ----------------------------------------------------------


def test_no_participation_shock_when_volume_not_a_record():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    rows["v"][SIGNAL_INDEX] = 99.0  # below the 100.0 reference maximum
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_PARTICIPATION_SHOCK"


def test_participation_shock_is_strictly_greater_than():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    rows["v"][SIGNAL_INDEX] = 100.0  # exactly the reference maximum -> NOT a record
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_PARTICIPATION_SHOCK"


def test_no_excursion_record():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    # flatten the signal bar's range to exactly the reference range -> not a record
    rows["h"][SIGNAL_INDEX] = 101.0
    rows["l"][SIGNAL_INDEX] = 99.0
    rows["c"][SIGNAL_INDEX] = 100.5
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXCURSION_RECORD"


def test_exhaustion_requires_strictly_more_than_half():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    # range = 4.0, half = 2.0; close exactly at 100.0 gives (high - close) == 2.0 -> NOT exhaustion
    rows["c"][SIGNAL_INDEX] = 100.0
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXHAUSTION"


def test_no_exhaustion_on_zero_body():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    rows["c"][SIGNAL_INDEX] = rows["o"][SIGNAL_INDEX]
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)
    assert ev["emitted"] is False
    assert ev["reason"] == "NO_EXHAUSTION"


def test_reference_history_incomplete_when_a_slot_is_missing():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    assert evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX)["reference_observations_present"] == 30

    # drop one reference bar (the same 5m slot 1 day earlier) from the partition entirely
    drop_at = rows["t"][SIGNAL_INDEX] - 86400000
    j = rows["t"].index(drop_at)
    for key in ("t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq"):
        rows[key].pop(j)
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX - 1)
    assert ev["emitted"] is False
    assert ev["reason"] == "REFERENCE_HISTORY_INCOMPLETE"
    assert ev["reference_observations_present"] == 29


def test_reference_precedence_beats_participation():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    # remove the 1-day-ago slot so the reference set is incomplete
    missing = rows["t"][SIGNAL_INDEX] - 86400000
    j = rows["t"].index(missing)
    for key in ("t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq"):
        rows[key].pop(j)
    ev = evaluate_bar(syn.to_kline5m(rows), SIGNAL_INDEX - 1)
    assert ev["emitted"] is False
    assert ev["reason"] == "REFERENCE_HISTORY_INCOMPLETE"


def test_precedence_tuple_is_exactly_frozen():
    assert list(NO_SIGNAL_PRECEDENCE) == [
        "OUTSIDE_COMMON_WINDOW",
        "REFERENCE_HISTORY_INCOMPLETE",
        "NO_PARTICIPATION_SHOCK",
        "NO_EXCURSION_RECORD",
        "NO_EXHAUSTION",
        "POSITION_ALREADY_OPEN",
        "INSUFFICIENT_FORWARD_PRICE_DATA",
    ]


# --- 3. entry / exit causality --------------------------------------------------------


def test_entry_is_the_next_bar_open_and_never_same_bar():
    k, rows = _short_fixture()
    res = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    assert len(res.trades) == 1
    tr = res.trades[0]
    signal_open = rows["t"][SIGNAL_INDEX]
    assert tr.decision_time_ms == signal_open + BAR_MS - 1
    assert tr.entry_time_ms == signal_open + BAR_MS
    assert tr.entry_time_ms > tr.decision_time_ms


def test_exit_is_exactly_twelve_bars_after_entry():
    k, _ = _short_fixture()
    res = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    tr = res.trades[0]
    assert tr.exit_time_ms == tr.entry_time_ms + HOLDING_MS
    assert HOLDING_BARS == 12
    assert HOLDING_MS == 12 * BAR_MS == 3600000


def test_outside_common_window_is_not_evaluated():
    k, _ = _short_fixture()
    start = k.t[SIGNAL_INDEX + 100]
    res = emit_trades({"BTCUSDT": k}, start_ms=start, end_ms=k.t[-1])
    assert res.funnel["OUTSIDE_COMMON_WINDOW"] == SIGNAL_INDEX + 100
    assert len(res.trades) == 0


def test_insufficient_forward_price_data_censors_the_tail():
    k, _ = _short_fixture()
    end = k.t[SIGNAL_INDEX] + BAR_MS  # exit anchor would exceed this
    res = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=end)
    assert len(res.trades) == 0
    assert res.funnel["INSUFFICIENT_FORWARD_PRICE_DATA"] == 1


def test_position_already_open_is_skipped_and_reentry_allowed_after_exit():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    def plant_signal(idx: int) -> None:
        bar = rows["t"][idx]
        for off in syn.reference_slot_offsets():
            j = rows["t"].index(bar - off)
            rows["v"][j] = 100.0
            rows["h"][j] = 101.0   # reference range = 2.0
            rows["l"][j] = 99.0
            rows["c"][j] = 100.0
        rows["o"][idx] = 100.0
        rows["h"][idx] = 103.0    # signal range = 4.0 > 2.0 -> excursion record
        rows["l"][idx] = 99.0
        rows["c"][idx] = 100.9    # body > 0 and (high - close) = 2.1 > 2.0 -> exhaustion
        rows["v"][idx] = 500.0    # volume record

    # a second signal 6 bars later, inside the first 12-bar hold -> must be skipped
    second = SIGNAL_INDEX + 6
    plant_signal(second)

    # a third signal at the first exit bar -> must be emitted
    third = SIGNAL_INDEX + 13
    plant_signal(third)

    k = syn.to_kline5m(rows)
    res = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    emitted_bars = [t.signal_bar_open_time_ms for t in res.trades]
    assert rows["t"][SIGNAL_INDEX] in emitted_bars
    assert rows["t"][second] not in emitted_bars
    assert rows["t"][third] in emitted_bars
    assert res.funnel["POSITION_ALREADY_OPEN"] >= 1


# --- 4. no unadmitted field -----------------------------------------------------------


def test_signal_is_independent_of_unadmitted_fields():
    k_a, rows_a = _short_fixture()
    k_b, rows_b = _short_fixture()
    for key in ("qv", "n", "tb", "tq"):
        rows_b[key] = [0.0] * len(rows_b[key])
    ev_a = evaluate_bar(k_a, SIGNAL_INDEX)
    ev_b = evaluate_bar(syn.to_kline5m(rows_b), SIGNAL_INDEX)
    for key in ("result", "reason", "emitted", "participation_shock", "excursion_record", "wick_fraction"):
        assert ev_a[key] == ev_b[key]


# --- 5. funding cashflow --------------------------------------------------------------


def test_funding_sign_convention_long_pays_short_receives():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    k = syn.to_kline5m(rows)
    res = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1])
    tr = res.trades[0]
    settlement = tr.entry_time_ms + 1800000  # strictly inside (entry, exit]
    series = syn.make_funding("BTCUSDT", settlements_ms=[settlement], rates=[0.0001])

    long_like = trade_returns(replace(tr, direction=LONG, direction_sign=1), cost_bps=0, funding=series)
    short_like = trade_returns(replace(tr, direction=SHORT, direction_sign=-1), cost_bps=0, funding=series)
    assert long_like["funding_cashflow_return"] == pytest.approx(-0.0001)
    assert short_like["funding_cashflow_return"] == pytest.approx(0.0001)


def test_funding_boundary_entry_excluded_exit_included():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    k = syn.to_kline5m(rows)
    tr = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1]).trades[0]
    series = syn.make_funding(
        "BTCUSDT",
        settlements_ms=[tr.entry_time_ms, tr.exit_time_ms],
        rates=[0.0001, 0.0001],
    )
    out = trade_returns(tr, cost_bps=0, funding=series)
    assert out["funding_settlements_applied"] == 1


def test_funding_settlement_count_is_never_hardcoded():
    """A 2h schedule puts more settlements inside a 60-minute window than an 8h one."""
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    k = syn.to_kline5m(rows)
    tr = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1]).trades[0]

    eight_h = syn.make_funding("BTCUSDT", settlements_ms=[tr.entry_time_ms + 1800000], rates=[0.0001])
    two_h = syn.make_funding(
        "BTCUSDT",
        settlements_ms=[tr.entry_time_ms + 900000, tr.entry_time_ms + 1800000, tr.entry_time_ms + 2700000],
        rates=[0.0001, 0.0001, 0.0001],
    )
    assert trade_returns(tr, cost_bps=0, funding=eight_h)["funding_settlements_applied"] == 1
    assert trade_returns(tr, cost_bps=0, funding=two_h)["funding_settlements_applied"] == 3


def test_accounting_identity_and_ex_funding_independence():
    rows = syn.build_partition("BTCUSDT", bars=BARS)
    syn.make_up_push_exhaustion(rows, signal_index=SIGNAL_INDEX)
    k = syn.to_kline5m(rows)
    tr = emit_trades({"BTCUSDT": k}, start_ms=k.t[0], end_ms=k.t[-1]).trades[0]
    series = syn.make_funding(
        "BTCUSDT", settlements_ms=[tr.entry_time_ms + 1800000], rates=[0.0001]
    )
    out = trade_returns(tr, cost_bps=PRIMARY_COST_BPS, funding=series)
    assert out["net_trade_return"] == pytest.approx(
        out["gross_price_return"] + out["funding_cashflow_return"] - out["cost_return"]
    )
    assert out["net_trade_return_ex_funding"] == pytest.approx(
        out["gross_price_return"] - out["cost_return"]
    )
    # ex-funding contains ZERO funding contribution
    assert out["net_trade_return_ex_funding"] == pytest.approx(
        out["net_trade_return"] - out["funding_cashflow_return"]
    )


# --- 6. frozen constants --------------------------------------------------------------


def test_frozen_economic_constants():
    assert HOLDING_BARS == 12
    assert PRIMARY_COST_BPS == 10
    assert BOOTSTRAP_RESAMPLES == 10000
    assert PERMUTATION_DRAWS == 10000
    assert BOOTSTRAP_SEED == 20260915
    assert NULL_SEED == 20260915
    assert PERMUTATION_ALPHA == 0.05


def test_cost_scenarios_frozen():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["cost_model"]["cost_sensitivities_bps"] == [0, 10, 20, 40]
    assert spec["cost_model"]["PRIMARY_ROUND_TRIP_COST_BPS"] == 10


def test_price_context_is_none_and_no_extra_filter():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["price_context"]["PRICE_CONTEXT"] == "NONE"
    assert spec["price_context"]["required_price_features_role"] == "definitional_only"


# --- 7. real funding authority reuse identity ---------------------------------------


def test_funding_reuse_identity_against_certified_authority():
    """The ARC-03 funding partitions must be byte-identical to the certified ARC-01 ones."""
    from trading_bot.research.arc03.arc03_funding import load_funding, resolve_funding_dir

    base = resolve_funding_dir()
    if not base.exists():
        pytest.skip("funding partitions not materialised in this checkout")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        series = load_funding(symbol)
        assert series.matches_arc01_authority is True, symbol
        assert series.rows > 0


def test_partitions_match_frozen_fingerprint_when_present():
    """If the participation partitions are materialised, their digests must match the spec."""
    from trading_bot.research.arc03.arc03_authority import load_partition, resolve_partition_dir

    base = resolve_partition_dir()
    if not (base / "BTCUSDT.jsonl").exists():
        pytest.skip("ARC-03 partitions not materialised in this checkout")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    for symbol, expected in spec["data_authority"]["partition_sha256"].items():
        assert load_partition(symbol).sha256 == expected, symbol


# --- 8. spec completeness -------------------------------------------------------------


def test_spec_validator_reports_pass():
    proc = subprocess.run(
        [sys.executable, "scripts/validate_arc03_spec.py", "--json"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    record = json.loads(proc.stdout)
    assert record["ARC03_SPEC_COMPLETE"] == "PASS"
    assert record["failure_count"] == 0


def test_no_real_economic_observation_claim_in_spec():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["economics"]["ARC03_BACKTESTS"] == 0
    assert spec["economics"]["ARC03_EXECUTIONS"] == 0
    assert spec["economics"]["ARC03_PERFORMANCE_OBSERVED"] is False
    assert spec["economics"]["FALSE_SUCCESS"] == 0
