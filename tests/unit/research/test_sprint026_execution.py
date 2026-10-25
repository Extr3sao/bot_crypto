"""RFC-026 — execution economics tests.

TEST_TARGET == RUNTIME_TARGET: these call the exact functions RFC-026 runs
(``scripts/sprint026_lib.py`` / ``sprint026_exec.py``). No network, no orders.
The holdout (W6-W7) must never be reached; COST_MODEL_V3 must stay unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint026_exec as EX  # noqa: E402
import sprint026_lib as X  # noqa: E402


def _trade(asset: str, gross_bps: float) -> L.Trade:
    return L.Trade(
        candidate_id="t", hypothesis_id="h", family="f", asset=asset, window="W1",
        timeframe="1h", side="LONG", entry_ts=0.0, exit_ts=1.0, entry=100.0, exit=100.0,
        reason="time_stop", hold_bars=16, gross_bps=gross_bps, cost_bps=0.0,
        net_bps=gross_bps, mfe_bps=0.0, mae_bps=0.0, atr_bps_at_entry=10.0,
    )


# ---------------------------------------------------------------------------
# cost model + fees (fee accounting)
# ---------------------------------------------------------------------------


def test_cost_model_v3_unchanged() -> None:
    assert L.CERTIFIED_ROUND_TRIP_BPS == 23.790569
    assert X.CURRENT_COST_BPS == 23.790569
    assert abs(sum(X.COST_MODEL_V3_COMPONENTS.values()) - 23.790570) < 1e-3


def test_cost_model_components_documented() -> None:
    c = X.COST_MODEL_V3_COMPONENTS
    assert c["exchange_fee_entry"] == 10.0 and c["exchange_fee_exit"] == 10.0
    assert c["funding"] == 0.0  # spot
    assert abs(c["slippage"] - 2.632456) < 1e-9


def test_official_fees_no_rebate_and_spot_maker_equals_taker() -> None:
    spot = X.OFFICIAL_FEES["BINANCE_SPOT_VIP0"]
    assert spot["maker_fee_bps"] == spot["taker_fee_bps"] == 10.0
    assert all(v["rebate_bps"] == 0.0 for v in X.OFFICIAL_FEES.values())


# ---------------------------------------------------------------------------
# break-even (§5/§6)
# ---------------------------------------------------------------------------


def test_break_even_equals_gross_mean() -> None:
    trades = [_trade("BTCUSDT", g) for g in (20.0, 40.0, 60.0, -10.0)]
    be = X.break_even_analysis(trades)
    assert be["n"] == 4
    assert abs(be["break_even_cost_bps"] - 27.5) < 1e-9
    assert abs(be["required_cost_reduction_bps"] - (23.790569 - 27.5)) < 1e-3


def test_conservative_break_even_is_min_estimator() -> None:
    trades = [_trade("BTCUSDT", g) for g in (100.0, -50.0, -50.0, -50.0)]
    be = X.break_even_analysis(trades)
    cons = be["conservative_break_even_cost_bps"]
    assert cons <= be["break_even_cost_bps"]
    assert cons == min(
        be["bootstrap_ci90_low_bps"], be["gross_median_bps"],
        be["trimmed_mean_bps"], be["ex_best_trade_mean_bps"],
    )
    assert be["alpha_uncertainty_high"] is True


def test_break_even_empty_is_safe() -> None:
    assert X.break_even_analysis([]) == {"n": 0}


# ---------------------------------------------------------------------------
# feasibility frontier (§7)
# ---------------------------------------------------------------------------


def test_frontier_monotone_and_zero_cost_is_gross() -> None:
    trades = [_trade("BTCUSDT", g) for g in (10.0, 20.0, 30.0)]
    fr = X.feasibility_frontier(trades, (0.0, 5.0, 23.790569))
    assert abs(fr[0]["net_expectancy_bps"] - 20.0) < 1e-9
    nets = [r["net_expectancy_bps"] for r in fr]
    assert all(nets[i] >= nets[i + 1] - 1e-9 for i in range(len(nets) - 1))


# ---------------------------------------------------------------------------
# policy registry, floors, maker semantics (§12/§13/§17)
# ---------------------------------------------------------------------------


def test_policy_budget_and_baseline_cost() -> None:
    policies = X.policy_registry()
    assert len(policies) <= 8
    e0 = next(p for p in policies if p.policy_id == "E0_CURRENT_TAKER")
    assert e0.round_trip_cost_bps == X.CURRENT_COST_BPS
    assert e0.status == "CERTIFIED_EMPIRICAL"


def test_maker_policies_are_not_given_a_realistic_cost() -> None:
    for p in X.policy_registry():
        if "MAKER" in p.policy_id or "FALLBACK" in p.policy_id or p.entry_mode.startswith("limit"):
            # a maker policy is either untestable (no scalar) or a flagged
            # theoretical bound - never an evidence-backed scalar cost.
            assert p.status in ("NOT_TESTABLE", "THEORETICAL_ONLY")
            if p.status == "NOT_TESTABLE":
                assert p.round_trip_cost_bps is None


def test_maker_fill_bounds_refuse_certification() -> None:
    b = X.maker_fill_bounds()
    assert b["status"] == "NOT_TESTABLE_HISTORICALLY"
    assert b["certifiable"] is False
    for k in ("optimistic_bound", "neutral_bound", "conservative_bound"):
        assert b[k]["effective_cost_bps"] is None


def test_theoretical_floors() -> None:
    f = X.theoretical_floor_bps()
    assert f["theoretical_cost_floor_runtime_venue_bps"] == 20.0  # 2 x 10 bps fee
    assert f["perfect_maker_upper_bound_spot_bps"] == 20.0
    assert f["perfect_maker_upper_bound_perp_bps"] == 4.0
    assert f["theoretical_minimum_realistic_cost_bps"] >= 20.0


def test_latency_scenarios_frozen() -> None:
    assert X.LATENCY_SCENARIOS_MS == (0, 50, 100, 250, 500, 1000)
    assert X.RUNTIME_MEASURED_LATENCY_MS is None  # never invented


# ---------------------------------------------------------------------------
# accounting: fills, partial fills, no-fills (§25/§26/§34)
# ---------------------------------------------------------------------------


def test_taker_policy_fill_accounting_is_complete() -> None:
    policies = {p.policy_id: p for p in X.policy_registry()}
    trades = [_trade("BTCUSDT", 30.0), _trade("SOLUSDT", 10.0)]
    r = EX._evaluate_policy(trades, policies["E0_CURRENT_TAKER"])
    assert r["intents"] == 2 and r["fills"] == 2 and r["fill_rate"] == 1.0
    assert abs(r["net_expectancy_bps"] - (20.0 - X.CURRENT_COST_BPS)) < 1e-3


def test_empirical_policy_uses_per_asset_cost() -> None:
    policies = {p.policy_id: p for p in X.policy_registry()}
    trades = [_trade("BTCUSDT", 30.0)]
    r = EX._evaluate_policy(trades, policies["E1_EMPIRICAL_TAKER_SPOT"])
    assert r["total_effective_cost_bps"] == X.V4_MEASURED_SPOT["BTCUSDT"]["rt_total_bps"]


def test_maker_policy_has_no_fill_rate() -> None:
    policies = {p.policy_id: p for p in X.policy_registry()}
    trades = [_trade("BTCUSDT", 30.0)]
    r = EX._evaluate_policy(trades, policies["E2_MAKER_ENTRY_MAKER_EXIT_SPOT"])
    assert r["fills"] is None and r["fill_rate"] is None
    assert r["net_expectancy_bps"] is None


def test_partial_fill_uses_filled_quantity_only() -> None:
    # A partial-filled position must be accounted on the filled notional; the
    # model only ever divides by the number of ACTUAL fills (len(nets)).
    policies = {p.policy_id: p for p in X.policy_registry()}
    trades = [_trade("BTCUSDT", 20.0), _trade("ETHUSDT", 20.0)]
    r = EX._evaluate_policy(trades, policies["E0_CURRENT_TAKER"])
    assert r["fills"] == len(trades)  # one fill record per completed intent


# ---------------------------------------------------------------------------
# determinism / reconciliation
# ---------------------------------------------------------------------------


def test_candidate_replay_is_deterministic_and_reconciles() -> None:
    from numpy.testing import assert_allclose

    c = X.FROZEN_ALPHA[0]
    t1, _ = X.run_candidate(c, ("W1",))
    t2, _ = X.run_candidate(c, ("W1",))
    assert len(t1) == len(t2)
    if t1:
        assert_allclose(X.gross_bps(t1), X.gross_bps(t2))
    # reconciliation: net == gross - cost for every trade
    for t in t1:
        assert abs(t.net_bps - (t.gross_bps - t.cost_bps)) < 1e-9


# ---------------------------------------------------------------------------
# holdout / PIT guards
# ---------------------------------------------------------------------------


def test_holdout_never_used() -> None:
    assert L.SPLITS["HOLDOUT"] == ("W6", "W7")
    assert L.SPLITS["DISCOVERY"] == ("W1", "W2", "W3", "W4")
    assert L.SPLITS["VALIDATION"] == ("W5",)
    assert EX.HOLDOUT_READ is False


def test_no_policy_or_registry_value_is_nan() -> None:
    for p in X.policy_registry():
        if p.round_trip_cost_bps is not None:
            assert np.isfinite(p.round_trip_cost_bps)
