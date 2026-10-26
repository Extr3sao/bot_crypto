"""RFC-032 — EXT-TSMOM-002 remediation tests (SYNTHETIC ONLY, no network).

These tests exercise the RFC-032 long-or-cash + T+1 engine and the reusable
certification gate on synthetic panels.  They never touch the gitignored cache.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint032_lib as L  # noqa: E402

from trading_bot.research.certification_gate import (  # noqa: E402
    GateStatus,
    check_execution_timing,
    check_gate_order,
    check_instrument_feasible,
    check_no_unsupported_short_spot,
    evaluate_promotion,
)

DAY = 86_400_000
START = int(datetime(2018, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _panel(n_days: int = 800, n_assets: int = 8, seed: int = 7,
           trend: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    days = np.array([START + i * DAY for i in range(n_days)], dtype=np.int64)
    logr = rng.normal(0.0005 + trend, 0.02, size=(n_days, n_assets))
    close = 100.0 * np.exp(np.cumsum(logr, axis=0))
    # open is an independent series (NOT the previous close) so that T+1 open
    # execution is genuinely different from the same-close fill.
    open_ = close * (1.0 + rng.normal(0.0, 0.005, size=close.shape))
    return close, open_, days


def _downtrend(n_days: int = 800, n_assets: int = 6) -> tuple[np.ndarray, np.ndarray,
                                                              np.ndarray]:
    days = np.array([START + i * DAY for i in range(n_days)], dtype=np.int64)
    close = 100.0 * np.exp(-0.02 * np.arange(n_days))[:, None] * np.ones((1, n_assets))
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return close, open_, days


def _full(days: np.ndarray) -> np.ndarray:
    return np.ones(len(days), dtype=bool)


# ---------------------------------------------------------------------------
# §22 cost model
# ---------------------------------------------------------------------------

def test_cost_model_is_15bps_per_side() -> None:
    assert L.PER_SIDE_COST_BPS == 15.0
    assert sum(L.COST_MODEL.values()) == L.PER_SIDE_COST_BPS


def test_cost_charged_on_turnover() -> None:
    close, open_, days = _panel()
    r = L.run_tsmom002(close, open_, days, _full(days))
    for tn, c in zip(r["traded"], r["costs"], strict=True):
        assert abs(c - tn * L.PER_SIDE_COST_BPS) < 1e-9
    for g, c, n in zip(r["gross"], r["costs"], r["nets"], strict=True):
        assert abs(n - (g - c)) < 1e-9


# ---------------------------------------------------------------------------
# §4/§64 R1: negative signal -> CASH (never a negative quantity)
# ---------------------------------------------------------------------------

def test_downtrend_is_all_cash_no_shorts() -> None:
    close, open_, days = _downtrend()
    r = L.run_tsmom002(close, open_, days, _full(days), collect_detail=True)
    assert r["detail"], "expected monthly observations"
    for d in r["detail"]:
        assert d["n_long"] == 0
        assert d["invested_capital"] == 0.0
        assert d["gross_bps"] == 0.0
    assert np.all(np.asarray(r["gross"]) == 0.0)


def test_negative_signal_maps_to_zero_weight() -> None:
    close, _, days = _downtrend()
    for i in L.month_first_days(days):
        if i - 365 < 0:
            continue
        t = L.tsmom_long_cash_target(close, i)
        assert np.all(t["weights"] >= 0.0)
        assert np.all(t["weights"] == 0.0)


def test_negative_signal_asset_is_cash_while_positive_stays_long() -> None:
    rng = np.random.default_rng(42)
    n = 800
    days = np.array([START + i * DAY for i in range(n)], dtype=np.int64)
    up = 0.004 + rng.normal(0.0, 0.02, size=n)
    dn = -0.004 + rng.normal(0.0, 0.02, size=n)
    close = np.column_stack([100.0 * np.exp(np.cumsum(up)),
                             100.0 * np.exp(np.cumsum(dn))])
    i = next(k for k in L.month_first_days(days) if k - 365 >= 0)
    t = L.tsmom_long_cash_target(close, i)
    assert t["signal"][0] > 0 and t["weights"][0] > 0    # uptrend -> long
    assert t["signal"][1] < 0 and t["weights"][1] == 0.0  # downtrend -> cash


def test_no_short_spot_positions_up_and_down() -> None:
    for trend in (-0.01, 0.0, 0.01):
        close, open_, days = _panel(trend=trend, seed=11)
        r = L.run_tsmom002(close, open_, days, _full(days))
        for i in L.month_first_days(days):
            if i - 365 < 0:
                continue
            w = L.tsmom_long_cash_target(close, i)["weights"]
            assert np.all(w >= -1e-12)
        assert np.all(np.asarray(r["net_exposure"]) >= -1e-9)


# ---------------------------------------------------------------------------
# §24 portfolio constraint
# ---------------------------------------------------------------------------

def test_long_book_never_leverages() -> None:
    close, _, days = _panel(trend=0.005, seed=3)
    for i in L.month_first_days(days):
        if i - 365 < 0:
            continue
        w = L.tsmom_long_cash_target(close, i)["weights"]
        assert float(np.sum(w)) <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# §20 R2: T+1 execution at the next OPEN
# ---------------------------------------------------------------------------

def test_execution_uses_next_open_not_same_close() -> None:
    close, open_, days = _panel(seed=5)
    mask = _full(days)
    r = L.run_tsmom002(close, open_, days, mask, exec_mode="next_open")
    rebal = [i for i in L.month_first_days(days) if mask[i]]
    # first usable rebalance with a next one
    k = next(idx for idx in range(len(rebal) - 1) if rebal[idx] - 365 >= 0)
    i, j = rebal[k], rebal[k + 1]
    e0, e1 = i + 1, j + 1
    w = L.tsmom_long_cash_target(close, i)["weights"]
    good = np.isfinite(open_[e1]) & np.isfinite(open_[e0])
    ret = np.zeros(close.shape[1])
    ret[good] = open_[e1, good] / open_[e0, good] - 1.0
    expected = float(np.nansum(w * ret) * 1e4)
    assert abs(float(r["gross"][0]) - expected) < 1e-9
    # and it differs from filling at the same close
    cot = L.run_tsmom002(close, open_, days, mask, exec_mode="cotimed")
    assert abs(float(cot["gross"][0]) - expected) > 1e-12


# ---------------------------------------------------------------------------
# §25 listing dates / PIT eligibility
# ---------------------------------------------------------------------------

def test_pre_listing_asset_is_ineligible() -> None:
    close, _, days = _panel(n_assets=5, seed=9)
    close2 = close.copy()
    close2[:500, 0] = np.nan          # asset 0 lists late
    for i in L.month_first_days(days):
        if 365 <= i < 500:
            t = L.tsmom_long_cash_target(close2, i)
            assert not bool(t["eligible"][0])
            assert t["weights"][0] == 0.0


# ---------------------------------------------------------------------------
# §28 future poisoning
# ---------------------------------------------------------------------------

def test_future_poisoning_does_not_change_past_weights() -> None:
    close, _, days = _panel(seed=13)
    cutoff = 600
    c2 = close.copy()
    c2[cutoff:] *= 5.0
    for i in L.month_first_days(days):
        if i >= cutoff:
            break
        if i - 365 < 0:
            continue
        a = L.tsmom_long_cash_target(close, i)["weights"]
        b = L.tsmom_long_cash_target(c2, i)["weights"]
        assert np.allclose(a, b, atol=1e-12)


# ---------------------------------------------------------------------------
# §23 cash accounting
# ---------------------------------------------------------------------------

def test_cash_month_has_zero_gross() -> None:
    close, open_, days = _downtrend()
    r = L.run_tsmom002(close, open_, days, _full(days))
    assert r["nets"].size > 0
    assert np.all(np.asarray(r["gross"]) == 0.0)
    # book starts and stays empty -> no turnover, no cost
    assert np.all(np.asarray(r["traded"]) == 0.0)


# ---------------------------------------------------------------------------
# determinism / replay
# ---------------------------------------------------------------------------

def test_replay_is_deterministic() -> None:
    close, open_, days = _panel(seed=21)
    mask = _full(days)
    a = L.run_tsmom002(close, open_, days, mask)
    b = L.run_tsmom002(close, open_, days, mask)
    assert np.allclose(a["nets"], b["nets"], atol=0.0)


# ---------------------------------------------------------------------------
# candidate hashing (§7, §35)
# ---------------------------------------------------------------------------

def test_candidate_hash_is_stable_and_sensitive() -> None:
    base = {"candidate_id": L.CANDIDATE_ID, "vol_target": 0.40}
    assert L.sha256_obj(base) == L.sha256_obj(dict(base))
    assert L.sha256_obj(base) != L.sha256_obj({**base, "vol_target": 0.41})
    assert L.FROZEN_TSMOM_002["executable_field"] == "open"


# ---------------------------------------------------------------------------
# §66/§67 evidence labelling + forward boundary
# ---------------------------------------------------------------------------

def test_historical_evidence_label_is_not_validation_or_holdout() -> None:
    assert L.EVIDENCE_CLASS_HISTORICAL == "HISTORICAL_DIAGNOSTIC"
    assert L.EVIDENCE_CLASS_HISTORICAL not in ("VALIDATION", "HOLDOUT")


def test_forward_boundary_excludes_past_data() -> None:
    start = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    assert L.is_forward_evidence(start, start) is True
    assert L.is_forward_evidence(start - 1, start) is False
    assert L.is_forward_evidence(start + DAY, start) is True


# ---------------------------------------------------------------------------
# §61-§63 reusable certification gate + regressions
# ---------------------------------------------------------------------------

def test_promotable_only_when_all_mandatory_gates_pass() -> None:
    gates = {g: GateStatus.PASS for g in (
        "G_VALIDATION", "G_ROBUSTNESS", "G_HOLDOUT", "G_TRADABILITY",
        "G_INDEPENDENT_VERIFICATION")}
    result = evaluate_promotion(gates)
    assert result.promotable is True
    assert result.blocking_gates == ()


def test_xmom_regression_robustness_fail_holdout_pass() -> None:
    # RFC-030 defect: XMOM had G_ROBUSTNESS=FAIL but G_HOLDOUT=PASS and was
    # nevertheless reported as a paper candidate.
    gates = {
        "G_VALIDATION": GateStatus.PASS,
        "G_ROBUSTNESS": GateStatus.FAIL,
        "G_HOLDOUT": GateStatus.PASS,
        "G_TRADABILITY": GateStatus.PASS,
        "G_INDEPENDENT_VERIFICATION": GateStatus.PASS,
    }
    result = evaluate_promotion(gates)
    assert result.promotable is False
    assert "G_ROBUSTNESS" in result.blocking_gates
    assert check_gate_order(gates).passed is False


def test_tsmom001_regression_unsupported_short_spot() -> None:
    short_check = check_no_unsupported_short_spot(negative_weight_count=47,
                                                  borrow_evidence_present=False)
    assert short_check.passed is False
    instrument = check_instrument_feasible({"LONG_SPOT": True, "SHORT_SPOT": True})
    assert instrument.passed is False
    # tradability therefore FAILs and the candidate cannot be promotable
    gates = {g: GateStatus.PASS for g in (
        "G_VALIDATION", "G_ROBUSTNESS", "G_HOLDOUT", "G_TRADABILITY",
        "G_INDEPENDENT_VERIFICATION")}
    gates["G_TRADABILITY"] = GateStatus.FAIL
    assert evaluate_promotion(gates).promotable is False


def test_missing_gate_blocks_promotion() -> None:
    result = evaluate_promotion({"G_VALIDATION": GateStatus.PASS})
    assert result.promotable is False
    assert "G_ROBUSTNESS" in result.blocking_gates


def test_execution_timing_requires_t_plus_1() -> None:
    assert check_execution_timing(10, 11, require_t_plus_1=True).passed is True
    assert check_execution_timing(10, 10, require_t_plus_1=True).passed is False
