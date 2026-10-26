"""RFC-040 tests: dual-momentum decisions, PIT, 200-EUR accounting, business gate.

Offline and deterministic: synthetic price series only, no network, no artifacts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc040_run as RUN  # noqa: E402
import rfc040_verify as VER  # noqa: E402

from trading_bot.research import small_capital_dual_momentum_v1 as dm  # noqa: E402
from trading_bot.research import small_capital_v1 as sc  # noqa: E402

_MS = 86_400_000


def _series(symbol: str, values: list[float], start_ms: int = 1_000_000_000_000) -> sc.PriceSeries:
    return sc.PriceSeries(
        symbol=symbol,
        dates_ms=tuple(start_ms + i * _MS for i in range(len(values))),
        closes=tuple(values),
    )


def _ramp(n: int, base: float, slope: float, wobble: float = 0.0, period: int = 30) -> list[float]:
    out = []
    for i in range(n):
        v = base + slope * i
        if wobble:
            v += wobble * (1.0 if (i // period) % 2 == 0 else -1.0)
        out.append(v)
    return out


def _dataset(n: int = 800, *, a_slope: float = 0.20, b_slope: float = 0.01) -> sc.Dataset:
    return sc.build_dataset(
        [
            _series(dm.RISK_A, _ramp(n, 100.0, a_slope, 2.0, 40)),
            _series(dm.RISK_B, _ramp(n, 100.0, b_slope, 1.0, 55)),
            _series(dm.DEFENSIVE, _ramp(n, 100.0, 0.005, 0.4, 70)),
            _series(dm.CASH, _ramp(n, 100.0, 0.001, 0.01, 90)),
            _series(dm.EQUITY_BENCH, _ramp(n, 100.0, 0.12, 2.0, 45)),
        ]
    )


# --- frozen configuration ---------------------------------------------------


def test_reference_capital_is_200_eur() -> None:
    assert dm.REFERENCE_CAPITAL == 200.0
    assert RUN.THRESHOLDS["reference_capital_eur"] == 200.0
    assert RUN.THRESHOLDS["max_gross_exposure"] == 1.0
    assert RUN.THRESHOLDS["single_implementation_limit"] == 1


def test_universe_is_ucits_and_roles_are_declared() -> None:
    assert dm.SMALL_CAP_UNIVERSE == (
        dm.RISK_A,
        dm.RISK_B,
        dm.DEFENSIVE,
        dm.CASH,
        dm.EQUITY_BENCH,
    )
    assert all(s.endswith((".DE", ".AS", ".L")) for s in dm.SMALL_CAP_UNIVERSE)
    product = RUN.section_instrument_accessibility()
    assert product["result"] == "PASS"
    assert all(i["eu_retail_accessible"] for i in product["instruments"])
    assert "SPY" in product["rejected_by_default"]


def test_no_us_domiciled_etf_is_used() -> None:
    banned = {"SPY", "QQQ", "TLT", "GLD", "AGG", "EFA"}
    assert not (banned & set(dm.SMALL_CAP_UNIVERSE))
    spec = RUN.dm_spec()
    assert spec["reproduction_fidelity"] == "CLOSE"


def test_freeze_hashes_and_single_candidate() -> None:
    spec = RUN.dm_spec()
    digest = {"dataset_sha256": "deadbeef", "per_symbol": {}}
    freeze = RUN.section_freeze(spec, digest)
    assert freeze["candidate"] == "SC-DUALMOM-002"
    assert len(freeze["spec_canonical_sha256"]) == 64
    assert freeze["no_retuning"] is True


def test_no_p3_is_authorized() -> None:
    capital = RUN.section_capital_constraints()
    assert capital["p3_allowed"] is False
    assert capital["new_families_allowed"] is False
    assert capital["substitution_allowed_if_fails"] is False
    assert capital["implementations_authorized"] == 1


# --- decisions --------------------------------------------------------------


def test_relative_momentum_picks_the_stronger_risky_leg() -> None:
    ds = _dataset()
    hold, diag = dm.dm_decision(ds, 400, lookback=100)
    assert hold == dm.RISK_A
    assert diag["rel_a"] > diag["rel_b"]


def test_absolute_momentum_goes_defensive_when_winner_is_negative() -> None:
    ds = sc.build_dataset(
        [
            _series(dm.RISK_A, _ramp(400, 200.0, -0.10, 1.0, 40)),
            _series(dm.RISK_B, _ramp(400, 200.0, -0.20, 1.0, 55)),
            _series(dm.DEFENSIVE, _ramp(400, 100.0, 0.005, 0.4, 70)),
            _series(dm.CASH, _ramp(400, 100.0, 0.001, 0.01, 90)),
            _series(dm.EQUITY_BENCH, _ramp(400, 100.0, 0.01, 1.0, 45)),
        ]
    )
    hold, diag = dm.dm_decision(ds, 399, lookback=100)
    assert hold == dm.DEFENSIVE
    assert diag["abs_winner"] <= 0.0


def test_warmup_is_defensive() -> None:
    ds = _dataset()
    hold, diag = dm.dm_decision(ds, 10, lookback=252)
    assert hold == dm.DEFENSIVE
    assert diag["reason"] == "warmup"


def test_decision_is_causal_no_lookahead() -> None:
    ds = _dataset()
    idx = 400
    before, _ = dm.dm_decision(ds, idx, lookback=100)
    mutated = dict(ds.closes)
    for sym in (dm.RISK_A, dm.RISK_B):
        arr = list(mutated[sym])
        for j in range(idx + 1, len(arr)):
            arr[j] = (arr[j] or 1.0) * 3.0
        mutated[sym] = tuple(arr)
    after, _ = dm.dm_decision(
        sc.Dataset(symbols=ds.symbols, dates_ms=ds.dates_ms, closes=mutated), idx, lookback=100
    )
    assert before == after


def test_forward_fill_never_back_fills() -> None:
    ds = sc.build_dataset(
        [
            _series("A", [1.0, 2.0, 3.0]),
            _series("B", [5.0, 6.0, 7.0]),
        ]
    )
    mutated = sc.Dataset(
        symbols=ds.symbols,
        dates_ms=ds.dates_ms,
        closes={"A": (1.0, None, 3.0), "B": ds.closes["B"]},
    )
    vf = dm.forward_filled_prices(mutated)
    assert vf["A"] == [1.0, 1.0, 3.0]
    assert vf["B"] == [5.0, 6.0, 7.0]


# --- accounting -------------------------------------------------------------


def test_capital_constraint_and_fractional_accounting_at_200() -> None:
    ds = _dataset()
    res = dm.simulate_dual_momentum(
        ds, start_ms=ds.dates_ms[300], end_ms=ds.dates_ms[-1], capital=200.0, lookback=100
    )
    assert res.n_rebalances > 0
    assert res.mean_weight_error() <= 0.01
    assert res.weight_error_max <= 0.05
    assert res.dropped_sleeve_events == 0
    assert res.n_switches >= 0


def test_cost_accounting_reconciles() -> None:
    ds = _dataset()
    res = dm.simulate_dual_momentum(
        ds, start_ms=ds.dates_ms[300], end_ms=ds.dates_ms[-1], capital=200.0, lookback=100
    )
    d = res.as_dict()
    assert res.total_cost > 0.0
    assert d["gross_pnl"] == pytest.approx(d["net_pnl"] + d["total_cost"], abs=1e-9)


def test_scaled_passive_rejects_leverage() -> None:
    ds = _dataset()
    with pytest.raises(ValueError):
        dm.simulate_scaled_passive(
            ds, weight=1.5, start_ms=ds.dates_ms[300], end_ms=ds.dates_ms[-1]
        )


def test_missing_required_symbol_fails_closed() -> None:
    ds = sc.build_dataset(
        [_series(dm.RISK_A, _ramp(400, 100.0, 0.1)), _series(dm.RISK_B, _ramp(400, 100.0, 0.05))]
    )
    with pytest.raises(ValueError):
        dm.simulate_dual_momentum(
            ds, start_ms=ds.dates_ms[300], end_ms=ds.dates_ms[-1], lookback=100
        )


# --- gates and search state -------------------------------------------------


def test_splits_are_disjoint_and_ordered() -> None:
    d, v, h = RUN.SPLITS["DISCOVERY"], RUN.SPLITS["VALIDATION"], RUN.SPLITS["HOLDOUT"]
    assert d[1] < v[0] < v[1] < h[0]


def test_benchmarks_are_predeclared() -> None:
    spec = RUN.dm_spec()
    names = " ".join(spec["benchmarks"])
    for needle in (
        "SAME_UNIVERSE_PASSIVE",
        "SIMPLE_EQUITY_PASSIVE",
        "CASH_RISK_FREE",
        "RISK_MATCHED_PASSIVE",
    ):
        assert needle in names


def test_p1_is_reclassified_business_fail() -> None:
    src = RUN.RFC039 / "P1_VALIDATION_RESULTS.json"
    if not src.exists():  # pragma: no cover - artifacts are gitignored
        pytest.skip("RFC-039 artifacts not present in this checkout")
    p1 = RUN.section_p1_reclassification()
    assert p1["candidate"] == RUN.P1_ID
    assert p1["BUSINESS_EDGE"] == "FAIL"
    assert p1["EXECUTABLE_WITH_200_USDT"] == "YES"
    assert p1["evidence_deleted"] is False


def test_business_gate_is_applied_and_not_tuned() -> None:
    src = RUN.OUT / "BUSINESS_EDGE_GATE.json"
    if not src.exists():  # pragma: no cover - artifacts are gitignored
        pytest.skip("RFC-040 artifacts not present in this checkout")
    gate = json.loads(src.read_text(encoding="utf-8"))
    assert gate["no_threshold_tuning"] is True
    checks = gate["checks"]
    # a marginal Sharpe difference must not be declared a tie
    assert checks["strategy_sharpe_gt_risk_matched"] == (
        gate["strategy_validation"]["sharpe"] > gate["risk_matched_passive"]["sharpe"]
    )


def test_search_is_paused_when_business_edge_fails() -> None:
    rep = RUN.OUT.parent / "RFC040_FINAL_REPORT.json"
    if not rep.exists():  # pragma: no cover - artifacts are gitignored
        pytest.skip("RFC-040 final report not present in this checkout")
    data = json.loads(rep.read_text(encoding="utf-8"))
    if data["gates"]["G_BUSINESS_EDGE"] == "FAIL":
        assert data["search_status"] == "PAUSED"
        assert data["next"] == "STRATEGIC_BUSINESS_DECISION"
        assert data["no_p3"] is True
        assert data["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0


def test_verifier_alignment_helper_is_deterministic() -> None:
    series = [
        _series(dm.RISK_A, _ramp(300, 100.0, 0.1)),
        _series(dm.RISK_B, _ramp(300, 100.0, 0.05)),
    ]
    axis1, table1 = VER._align(series)
    axis2, table2 = VER._align(series)
    assert axis1 == axis2
    assert table1 == table2
    assert len(axis1) == 300


def test_false_success_audit_is_clean() -> None:
    fs = RUN.false_success_audit()
    assert fs["FALSE_SUCCESS"] == 0
    assert fs["triggers"]["positive_return_treated_as_business_edge"] is False
    assert fs["triggers"]["risk_reduction_called_alpha"] is False
    assert fs["triggers"]["p3_introduced"] is False
