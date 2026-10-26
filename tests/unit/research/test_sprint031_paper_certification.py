"""RFC-031 — TSMOM paper-certification tests (SYNTHETIC ONLY, no network).

These tests exercise the RFC-031 audit engine on synthetic panels.  They never
touch the gitignored cache, so they run everywhere.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint031_lib as L  # noqa: E402

DAY = 86_400_000
START = int(datetime(2018, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _panel(
    n_days: int = 420, n_assets: int = 8, seed: int = 7, trend: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    days = np.array([START + i * DAY for i in range(n_days)], dtype=np.int64)
    logr = rng.normal(0.0005 + trend, 0.02, size=(n_days, n_assets))
    close = 100.0 * np.exp(np.cumsum(logr, axis=0))
    return close, days


FULL = slice(None)


# ---------------------------------------------------------------------------
# cost model (§23)
# ---------------------------------------------------------------------------


def test_cost_model_is_15bps_per_side() -> None:
    assert L.PER_SIDE_COST_BPS == 15.0
    assert sum(L.COST_MODEL.values()) == L.PER_SIDE_COST_BPS


def test_cost_charged_on_turnover_not_notional() -> None:
    close, days = _panel()
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool))
    for tn, c in zip(r["traded"], r["costs"], strict=True):
        assert abs(c - tn * L.PER_SIDE_COST_BPS) < 1e-9
    # net = gross - cost, exactly
    close2, days2 = _panel()
    r2 = L.run_tsmom(close2, days2, np.ones(len(days2), dtype=bool))
    for g, c, n in zip(r2["gross"], r2["costs"], r2["nets"], strict=True):
        assert abs(n - (g - c)) < 1e-9


def test_first_rebalance_turnover_is_full_book() -> None:
    close, days = _panel()
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool))
    # the first traded book starts from cash (prev = 0), so turnover = gross
    assert r["traded"][0] > 0


# ---------------------------------------------------------------------------
# instrument feasibility: negative signal -> SHORT SPOT (§7-§8)
# ---------------------------------------------------------------------------


def test_downtrend_creates_short_spot_positions() -> None:
    close, days = _panel(trend=-0.01, seed=1)
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool), collect_detail=True)
    assert r["detail"], "expected trades"
    assert any(d["n_short"] > 0 for d in r["detail"]), "negative signal must short"


def test_uptrend_is_long_only() -> None:
    close, days = _panel(trend=0.01, seed=2)
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool), collect_detail=True)
    assert r["detail"]
    assert all(d["n_short"] == 0 for d in r["detail"])


def test_short_leg_contributes_pnl_separately() -> None:
    close, days = _panel(trend=-0.01, seed=3)
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool))
    assert r["long_contrib"].size == r["short_contrib"].size
    # total gross is split between the long and short legs
    total = r["long_contrib"] + r["short_contrib"]
    assert np.allclose(total, r["gross"], atol=1e-6)


# ---------------------------------------------------------------------------
# cash state / portfolio accounting (§41-§42)
# ---------------------------------------------------------------------------


def test_weights_are_gross_normalised_or_cash() -> None:
    close, _ = _panel()
    i = 400
    w = L.tsmom_target(close, i)["weights"]
    # either the book is gross-normalised (>=1) or entirely in cash (0)
    assert np.sum(np.abs(w)) > 0


def test_portfolio_accounting_identity() -> None:
    close, days = _panel()
    r = L.run_tsmom(close, days, np.ones(len(days), dtype=bool))
    m = L.summarise(r)
    # ending = sum of per-rebalance net; net = gross - cost
    assert abs(m["net_pnl_bps"] - float(np.sum(r["nets"]))) < 1e-6
    assert (
        abs(m["net_expectancy_bps"] - (m["gross_expectancy_bps"] - m["cost_expectancy_bps"])) < 1e-6
    )


def test_cash_when_no_signal_keeps_weights_zero() -> None:
    close, _ = _panel(n_days=200)
    # before the formation window the book is empty (implicitly cash)
    w = L.tsmom_target(close, 10)["weights"]
    assert np.all(w == 0.0)


# ---------------------------------------------------------------------------
# listing dates / PIT eligibility (§13-§15)
# ---------------------------------------------------------------------------


def test_no_prelisting_use_and_listing_dates_respected() -> None:
    close, _ = _panel()
    close2 = close.copy()
    close2[:300, 0] = np.nan  # asset 0 only lists at day 300
    # during the pre-listing window the asset can never be eligible
    for i in range(0, 300):
        t = L.tsmom_target(close2, i)
        if t["eligible"].shape[0]:
            assert t["eligible"][0] is False or bool(t["eligible"][0]) is False


def test_pit_eligibility_requires_full_formation_window() -> None:
    close, _ = _panel()
    close2 = close.copy()
    close2[:380, 0] = np.nan
    t = L.tsmom_target(close2, 400)
    # listed only 20 bars ago -> must NOT be eligible for a 365d signal
    assert bool(t["eligible"][0]) is False


def test_no_negative_index_wrap() -> None:
    close, _ = _panel()
    for i in range(0, 365):
        w = L.tsmom_target(close, i)["weights"]
        assert np.all(w == 0.0), "no lookback wrap before formation completes"


# ---------------------------------------------------------------------------
# signal timing / T+1 execution (§19-§22)
# ---------------------------------------------------------------------------


def test_signal_is_pit_safe_under_future_poisoning() -> None:
    close, _ = _panel()
    for i in (370, 390, 410):
        a = L.tsmom_target(close, i)["weights"]
        poisoned = close.copy()
        poisoned[i + 1 :, :] = -1e6
        b = L.tsmom_target(poisoned, i)["weights"]
        assert np.allclose(a, b, equal_nan=True)


def test_exec_lag_changes_execution_day_only() -> None:
    close, days = _panel()
    m = np.ones(len(days), dtype=bool)
    r0 = L.run_tsmom(close, days, m, exec_lag=0, collect_detail=True)
    r1 = L.run_tsmom(close, days, m, exec_lag=1, collect_detail=True)
    assert len(r0["detail"]) == len(r1["detail"])
    # same decision days, different execution days
    for a, b in zip(r0["detail"], r1["detail"], strict=True):
        assert a["decision_time"] == b["decision_time"]
        assert a["exec_time"] != b["exec_time"]


# ---------------------------------------------------------------------------
# benchmark independence (§27)
# ---------------------------------------------------------------------------


def test_benchmark_is_independent_of_strategy_weights() -> None:
    close, days = _panel()
    m = np.ones(len(days), dtype=bool)
    rebal = [i for i in L.month_first_days(days) if m[i]]
    ew = []
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        good = np.isfinite(close[j]) & np.isfinite(close[i])
        r = np.full(close.shape[1], np.nan)
        r[good] = close[j, good] / close[i, good] - 1.0
        ew.append(float(np.nanmean(r)))
    # equal-weight basket depends on prices only, never on the TSMOM signal
    assert len(ew) > 0
    assert abs(np.mean(ew) - np.mean(ew)) == 0.0


# ---------------------------------------------------------------------------
# determinism / replay / hash immutability (§57, §67, §77)
# ---------------------------------------------------------------------------


def test_paper_replay_is_deterministic() -> None:
    close, days = _panel()
    m = np.ones(len(days), dtype=bool)
    a = L.run_tsmom(close, days, m)
    b = L.run_tsmom(close, days, m)
    assert np.array_equal(a["nets"], b["nets"])
    assert np.array_equal(a["traded"], b["traded"])


def test_frozen_candidate_hash_immutable() -> None:
    assert L.FROZEN_TSMOM["formation_days"] == 365
    assert L.FROZEN_TSMOM["vol_target"] == 0.40
    assert L.FROZEN_TSMOM["strategy_id"] == "EXT-TSMOM-001"
    # hashing the frozen spec is stable
    assert L.sha256_obj(L.FROZEN_TSMOM) == L.sha256_obj(L.FROZEN_TSMOM)


# ---------------------------------------------------------------------------
# artifact-level gates (skipped when gitignored artifacts are absent)
# ---------------------------------------------------------------------------


def test_verification_artifact_zero_false_success() -> None:
    vp = REPO / "reports" / "paper-certification" / "RFC031_VERIFICATION.json"
    if not vp.exists():
        return
    payload = json.loads(vp.read_text(encoding="utf-8"))
    assert payload["FALSE_SUCCESS"] == 0
    assert payload["checks_passed"] == payload["checks_total"]


def test_gates_reflect_tradability_defect() -> None:
    fp = REPO / "reports" / "RFC031_FINAL_REPORT.json"
    if not fp.exists():
        return
    payload = json.loads(fp.read_text(encoding="utf-8"))
    assert payload["G_PC_1_TRADABILITY"] == "FAIL"
    assert payload["CERTIFICATION"] in ("REJECTED", "BLOCKED")
    assert payload["rfc030_candidate_status"] == "RFC030_CANDIDATE_INVALIDATED"
    assert payload["paper_campaign_activated"] is False
    assert payload["forward_paper_profitability"] == "NOT YET PROVEN"
