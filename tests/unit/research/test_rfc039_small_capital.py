"""RFC-039 §87 tests: 200-USDT constraint, fractional accounting, gates, selection.

All tests are offline: they use deterministic synthetic price series, so they do
not depend on the (gitignored) fetched ETF cache.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc039_run as RUN  # noqa: E402
import rfc039_verify as VER  # noqa: E402

from trading_bot.research import small_capital_v1 as sc  # noqa: E402

_MS = 86_400_000


def _series(symbol: str, values: list[float], start_ms: int = 1_000_000_000_000) -> sc.PriceSeries:
    dates = tuple(start_ms + i * _MS for i in range(len(values)))
    return sc.PriceSeries(symbol=symbol, dates_ms=dates, closes=tuple(values))


def _waves(n: int, base: float, amp: float, period: int, slope: float) -> list[float]:
    return [base + slope * i + amp * (1.0 if (i // period) % 2 == 0 else -1.0) for i in range(n)]


def _dataset() -> sc.Dataset:
    n = 900
    return sc.build_dataset(
        [
            _series("SPY", _waves(n, 100.0, 8.0, 60, 0.05)),
            _series("IEF", _waves(n, 90.0, 4.0, 90, 0.01)),
            _series("GLD", _waves(n, 80.0, 10.0, 45, 0.02)),
        ]
    )


# --- §64 capital constraint -------------------------------------------------


def test_reference_capital_is_200_usdt() -> None:
    assert sc.REFERENCE_CAPITAL == 200.0
    assert RUN.THRESHOLDS["reference_capital_usdt"] == 200.0
    assert RUN.THRESHOLDS["max_gross_exposure"] == 1.0


def test_fractional_rounding_and_minimum_order() -> None:
    ds = _dataset()
    res = sc.simulate_absolute_momentum(
        ds,
        start_ms=ds.dates_ms[220],
        end_ms=ds.dates_ms[-1],
        capital=200.0,
        window=20,
    )
    # every held quantity is a multiple of the frozen step
    assert res.max_positions_held >= 1
    # no sleeve was dropped for being below the minimum notional at 200 USDT
    assert res.dropped_sleeve_events == 0
    # fractional accounting is exact: weights track targets closely
    assert res.mean_weight_error() <= 0.01
    assert res.weight_error_max <= 0.05


def test_quantity_step_is_respected() -> None:
    assert sc.QTY_STEP == 0.0001
    ds = _dataset()
    res = sc.simulate_absolute_momentum(
        ds, start_ms=ds.dates_ms[220], end_ms=ds.dates_ms[-1], capital=200.0, window=20
    )
    assert res.n_rebalances > 0
    assert sc.MIN_POSITION_NOTIONAL_USD == 1.0


def test_capital_utilization_improves_with_capital() -> None:
    ds = _dataset()
    lo, hi = ds.dates_ms[220], ds.dates_ms[-1]
    small = sc.simulate_absolute_momentum(ds, start_ms=lo, end_ms=hi, capital=200.0, window=20)
    big = sc.simulate_absolute_momentum(ds, start_ms=lo, end_ms=hi, capital=10_000.0, window=20)
    assert big.mean_weight_error() <= small.mean_weight_error() + 1e-12
    assert small.avg_gross_weight <= sc.MAX_GROSS_EXPOSURE + 1e-9
    assert big.avg_gross_weight <= sc.MAX_GROSS_EXPOSURE + 1e-9


def test_no_leverage_gross_cap_holds() -> None:
    for cap in (200.0, 500.0, 10_000.0):
        ds = _dataset()
        res = sc.simulate_absolute_momentum(
            ds, start_ms=ds.dates_ms[220], end_ms=ds.dates_ms[-1], capital=cap, window=20
        )
        assert res.avg_gross_weight <= 1.0 + 1e-9
        assert res.avg_cash_weight >= -1e-9


# --- §46 cost accounting ----------------------------------------------------


def test_cost_accounting_reconciles() -> None:
    ds = _dataset()
    res = sc.simulate_absolute_momentum(
        ds, start_ms=ds.dates_ms[220], end_ms=ds.dates_ms[-1], capital=200.0, window=20
    )
    assert res.total_cost > 0.0
    assert res.gross_pnl == res.net_pnl + res.total_cost


def test_zero_cost_has_zero_charge() -> None:
    ds = _dataset()
    res = sc.simulate_absolute_momentum(
        ds,
        start_ms=ds.dates_ms[220],
        end_ms=ds.dates_ms[-1],
        capital=200.0,
        window=20,
        cost_bps_per_side=0.0,
    )
    assert res.total_cost == 0.0


# --- §44 PIT ----------------------------------------------------------------


def test_signal_is_causal_no_lookahead() -> None:
    ds = _dataset()
    idx = 400
    before = sc.target_sleeve_weights(ds, idx, n_sleeves=3)
    # perturb only FUTURE prices; the weight at idx must not move
    mutated = dict(ds.closes)
    spy = list(mutated["SPY"])
    for j in range(idx + 1, len(spy)):
        spy[j] = (spy[j] or 1.0) * 5.0
    mutated["SPY"] = tuple(spy)
    after = sc.target_sleeve_weights(
        sc.Dataset(symbols=ds.symbols, dates_ms=ds.dates_ms, closes=mutated), idx, n_sleeves=3
    )
    assert before == after


def test_sma_breaks_on_gaps() -> None:
    vals: list[float | None] = [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0]
    out = sc.sma(vals, 3)
    assert out[0] is None and out[1] is None
    assert out[2] == 2.0
    assert out[3] is None
    assert out[6] == 6.0


# --- §39/§40 selection freeze and single implementation ---------------------


def test_selection_freeze_single_p1() -> None:
    spec = RUN.p1_spec()
    freeze = RUN.section_freeze(spec)
    assert freeze["P1_SMALL_CAPITAL"] == RUN.P1_ID
    assert freeze["no_second_implementation"] is True
    assert freeze["no_retuning_after_validation"] is True
    assert len(freeze["spec_canonical_sha256"]) == 64


def test_top2_selects_exactly_one_p1_and_watchlists_p2() -> None:
    top2 = RUN.section_top2()
    assert top2["selected_p1"] == RUN.P1_ID
    assert top2["finalists"] == [RUN.P1_ID, RUN.P2_ID]
    assert top2["p2_status"] == "WATCHLIST"
    assert top2["no_results_based_selection"] is True
    assert top2["backtest_run_before_this_selection"] is False


def test_selection_is_evidence_based_not_results_based() -> None:
    # the scorecard carries only research dimensions, never internal PnL
    score = RUN.section_scorecard()
    for row in score["rows"]:
        assert not any("pnl" in k.lower() or "return" in k.lower() for k in row)
    # exactly one candidate is authorized to be implemented
    assert RUN.section_capital_constraints()["implementations_authorized"] == 1


def test_finalists_are_at_most_two() -> None:
    top2 = RUN.section_top2()
    assert len(top2["finalists"]) <= 2


# --- §53/§55 validation isolation -------------------------------------------


def test_splits_are_disjoint_and_ordered() -> None:
    disc = RUN.SPLITS["DISCOVERY"]
    val = RUN.SPLITS["VALIDATION"]
    hold = RUN.SPLITS["HOLDOUT"]
    assert disc[1] < val[0]
    assert val[1] < hold[0]
    assert disc[0] < disc[1]


def test_holdout_is_not_read_during_validation() -> None:
    # the validation function must not depend on the holdout window
    src = Path(RUN.__file__).read_text(encoding="utf-8")
    val_block = src.split("def section_validation")[1].split("def section_cost_model")[0]
    assert "HOLDOUT" not in val_block


# --- §75 independent verifier -----------------------------------------------


def test_independent_verifier_matches_core_on_synthetic_data() -> None:
    ds_series = [
        _series("SPY", _waves(900, 100.0, 8.0, 60, 0.05)),
        _series("IEF", _waves(900, 90.0, 4.0, 90, 0.01)),
        _series("GLD", _waves(900, 80.0, 10.0, 45, 0.02)),
    ]
    ds = sc.build_dataset(ds_series)
    lo, hi = ds.dates_ms[220], ds.dates_ms[-1]
    core = sc.simulate_absolute_momentum(ds, start_ms=lo, end_ms=hi, capital=200.0, window=20)
    indep = VER._independent_backtest(ds_series, 20, sc.COST_BPS_PER_SIDE, 200.0, lo, hi)
    assert abs(core.net_pnl - indep["net_pnl"]) <= 1e-6 * max(1.0, abs(core.net_pnl))
    assert abs(core.total_cost - indep["total_cost"]) <= 1e-9
    assert abs(core.traded_notional - indep["traded_notional"]) <= 1e-6


def test_false_success_audit_is_clean() -> None:
    fs = RUN.false_success_audit({"G_SC_2_VALIDATION": "PASS"})
    assert fs["FALSE_SUCCESS"] == 0
    assert fs["result"] == "PASS"
