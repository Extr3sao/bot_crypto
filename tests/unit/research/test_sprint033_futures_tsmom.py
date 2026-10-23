"""RFC-033 tests: executable long/short perp TSMOM (EXT-TSMOM-003).

All synthetic -- no network, no real cache -- so they run in CI and pin the
economic invariants the RFC depends on: futures listing semantics, long/short
mapping (no neutralisation), T+1 execution, funding sign & accounting, turnover,
cost, margin safety, PIT / future poisoning, split & holdout isolation and the
reusable certification gate ordering.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint033_lib as L  # noqa: E402

from trading_bot.research.certification_gate import (  # noqa: E402
    MANDATORY_GATES,
    GateStatus,
    evaluate_promotion,
)

_DAY = 86_400_000
_START = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000)


def _days(n: int) -> np.ndarray:
    return _START + np.arange(n, dtype=np.int64) * _DAY


def _matrix(cols: list[np.ndarray]) -> np.ndarray:
    return np.column_stack(cols).astype(np.float64)


def _funding_book(
    n_syms: int, rates_by_sym: dict[int, list[float]], first_ms: int = _START
) -> L.FundingBook:
    fb = L.FundingBook([f"S{i}USDT" for i in range(n_syms)])
    for j in range(n_syms):
        rates = rates_by_sym.get(j, [])
        t = np.array([first_ms + (k + 1) * _DAY // 3 for k in range(len(rates))], dtype=np.int64)
        fb.t[j] = t
        fb.cum[j] = np.concatenate([[0.0], np.cumsum(rates)]) if rates else np.zeros(1)
        fb.n_events[j] = len(rates)
    return fb


# ---------------------------------------------------------------------------
# listing / PIT
# ---------------------------------------------------------------------------


def test_listing_dates_and_first_index() -> None:
    days = _days(10)
    raw = {
        "AAAUSDT": {
            "open_time_ms": days,
            "close": np.arange(10.0) + 100.0,
            "open": np.arange(10.0) + 100.0,
        },
        "BBBUSDT": {
            "open_time_ms": days[5:],
            "close": np.arange(5.0) + 50.0,
            "open": np.arange(5.0) + 50.0,
        },
    }
    listing = L.listing_dates(raw)
    assert listing["AAAUSDT"] == "2020-01-01"
    assert listing["BBBUSDT"] == "2020-01-06"
    cal = L.build_calendar(raw)
    syms = ["AAAUSDT", "BBBUSDT"]
    close = L.build_matrix(raw, syms, cal, "close")
    fi = L.first_index(close)
    assert fi[0] == 0
    assert fi[1] == 5
    assert np.isnan(close[0, 1])  # no pre-listing observation


def test_no_prelisting_weight() -> None:
    a = np.zeros((40, 2))
    a[:, 0] = 100.0 * (1.01 ** np.arange(40))
    a[:, 1] = 100.0
    a[:30, 1] = np.nan  # second asset lists late
    i = 35
    tgt = L.tsmom_perp_target(a, i, formation=5, vol_lookback=3)
    assert tgt["weights"][1] == 0.0  # cannot hold before listing


def test_split_and_holdout_isolation() -> None:
    days = _days(int(6.5 * 365))
    d = L.split_mask(days, "DISCOVERY")
    v = L.split_mask(days, "VALIDATION")
    h = L.split_mask(days, "HOLDOUT")
    assert not (d & v).any()
    assert not (d & h).any()
    assert not (v & h).any()
    # chronological ordering
    assert d.nonzero()[0].max() < v.nonzero()[0].min() < h.nonzero()[0].min()
    assert (d | v | h).sum() > 0


# ---------------------------------------------------------------------------
# signal -> long/short mapping
# ---------------------------------------------------------------------------


def test_long_short_mapping_no_neutralisation() -> None:
    n = 30
    rng = np.random.default_rng(3)
    noise = rng.normal(0.0, 0.004, n)  # non-zero vol so the book is not scaled away
    up = 100.0 * np.cumprod(1.0 + 0.02 + noise)
    down = 100.0 * np.cumprod(1.0 - 0.02 + noise)
    close = _matrix([up, down])
    tgt = L.tsmom_perp_target(close, n - 1, formation=5, vol_lookback=3)
    assert tgt["weights"][0] > 0  # uptrend -> long
    assert tgt["weights"][1] < 0  # downtrend -> short (NOT neutralised)
    assert tgt["n_short"] == 1


def test_flat_signal_is_not_traded() -> None:
    n = 30
    flat = np.full(n, 100.0)
    close = _matrix([flat])
    tgt = L.tsmom_perp_target(close, n - 1, formation=5, vol_lookback=3)
    assert tgt["weights"][0] == 0.0  # zero-momentum -> zero weight


def test_gross_leverage_capped() -> None:
    n = 30
    # tiny vol -> raw scale clipped at 4 on many assets -> desired gross far above 1
    rng = np.random.default_rng(5)
    cols = [100.0 * np.cumprod(1.0 + 0.02 + rng.normal(0.0, 0.0005, n)) for _ in range(6)]
    close = _matrix(cols)
    tgt = L.tsmom_perp_target(close, n - 1, formation=5, vol_lookback=3)
    assert tgt["desired_gross"] > 1.0
    assert tgt["actual_gross"] <= 1.0 + 1e-12


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


def _panel(n: int = 130, syms: int = 4) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    days = _days(n)
    rng = np.random.default_rng(7)
    close = np.empty((n, syms))
    for j in range(syms):
        drift = 0.01 if j % 2 == 0 else -0.012
        close[:, j] = 100.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.01, n))
    # open is NOT a constant multiple of close, so T+1 open != co-timed close
    open_ = close * (1.0 + rng.normal(0.0, 0.02, (n, syms)))
    return days, close, open_


def test_t_plus_1_uses_next_open() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.03
    low = open_ * 0.97
    fb = _funding_book(4, {})
    full = np.ones(days.shape[0], dtype=bool)
    nxt = L.run_tsmom003(
        close, open_, high, low, days, fb, full, exec_mode="next_open", formation=5, vol_lookback=3
    )
    cot = L.run_tsmom003(
        close, open_, high, low, days, fb, full, exec_mode="cotimed", formation=5, vol_lookback=3
    )
    assert nxt["nets"].size == cot["nets"].size > 0
    assert not np.allclose(nxt["nets"], cot["nets"])


# ---------------------------------------------------------------------------
# funding
# ---------------------------------------------------------------------------


def test_funding_sign_long_pays_short_receives() -> None:
    long_only = np.array([[1.0]])
    fb = _funding_book(1, {0: [0.001, 0.001, 0.001]})
    t_left, t_right = _START, _START + 2 * _DAY
    total = fb.window_sum(0, t_left, t_right)
    assert total == pytest.approx(0.003)  # three events inside the window
    # long weight +1 with positive funding -> pays -> negative cashflow
    assert -float(long_only[0, 0] * total) < 0
    # short weight -1 with positive funding -> receives -> positive cashflow
    assert -float((-1.0) * total) > 0


def test_funding_enters_net_and_accounting_identity() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.03
    low = open_ * 0.97
    rates = [0.0005] * 200
    fb = _funding_book(4, {j: rates for j in range(4)})
    full = np.ones(days.shape[0], dtype=bool)
    r = L.run_tsmom003(close, open_, high, low, days, fb, full, formation=5, vol_lookback=3)
    identity = r["nets"] - (r["price"] + r["funding"] - r["costs"])
    assert np.max(np.abs(identity)) <= 1e-9
    assert np.any(r["funding"] != 0.0)  # funding is actually charged


def test_funding_scale_is_separate_from_cost() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.03
    low = open_ * 0.97
    fb = _funding_book(4, {j: [0.0007] * 200 for j in range(4)})
    full = np.ones(days.shape[0], dtype=bool)
    base = L.run_tsmom003(close, open_, high, low, days, fb, full, formation=5, vol_lookback=3)
    stressed = L.run_tsmom003(
        close, open_, high, low, days, fb, full, formation=5, vol_lookback=3, funding_scale=2.0
    )
    assert np.allclose(stressed["costs"], base["costs"])  # costs unchanged
    assert not np.allclose(stressed["funding"], base["funding"])  # funding scaled


# ---------------------------------------------------------------------------
# turnover / cost
# ---------------------------------------------------------------------------


def test_turnover_and_cost_reconciliation() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.03
    low = open_ * 0.97
    fb = _funding_book(4, {})
    full = np.ones(days.shape[0], dtype=bool)
    per_side = L.PER_SIDE_COST_BPS
    r = L.run_tsmom003(close, open_, high, low, days, fb, full, formation=5, vol_lookback=3)
    assert np.allclose(r["costs"], r["traded"] * per_side)
    double = L.run_tsmom003(
        close, open_, high, low, days, fb, full, formation=5, vol_lookback=3, cost_mult=2.0
    )
    assert np.allclose(double["costs"], r["costs"] * 2.0)


# ---------------------------------------------------------------------------
# margin / liquidation
# ---------------------------------------------------------------------------


def test_margin_uses_signed_adverse_excursion() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.10  # sharp adverse for shorts
    low = open_ * 0.90
    fb = _funding_book(4, {})
    full = np.ones(days.shape[0], dtype=bool)
    r = L.run_tsmom003(close, open_, high, low, days, fb, full, formation=5, vol_lookback=3)
    assert (r["worst_adverse"] <= 0).all()  # adverse excursions are losses
    assert float(np.min(r["worst_adverse"])) < 0.0


def test_margin_safe_at_one_x_gross() -> None:
    days, close, open_ = _panel()
    high = open_ * 1.03
    low = open_ * 0.97
    fb = _funding_book(4, {})
    full = np.ones(days.shape[0], dtype=bool)
    r = L.run_tsmom003(close, open_, high, low, days, fb, full, formation=5, vol_lookback=3)
    worst = float(np.min(r["worst_adverse"]))
    equity_after = 1.0 + worst
    maintenance_floor = 0.02 * 1.0  # 2% of 1x gross
    assert equity_after > maintenance_floor


# ---------------------------------------------------------------------------
# future poisoning (PIT)
# ---------------------------------------------------------------------------


def test_future_poisoning_pre_t_weights_identical() -> None:
    n = 500
    rng = np.random.default_rng(11)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.02, (n, 3)), axis=0)
    cutoff = 460
    pre = [i for i in L.month_first_days(_days(n)) if 365 <= i < cutoff]
    assert pre  # there is at least one decision day
    base = {i: L.tsmom_perp_target(close, i)["weights"] for i in pre}
    poisoned = close.copy()
    poisoned[cutoff:] = poisoned[cutoff:] * 5.0
    after = {i: L.tsmom_perp_target(poisoned, i)["weights"] for i in pre}
    for i in pre:
        assert np.max(np.abs(base[i] - after[i])) <= 1e-12


# ---------------------------------------------------------------------------
# certification gate ordering (reused from RFC-032)
# ---------------------------------------------------------------------------


def test_gate_missing_is_not_pass() -> None:
    res = evaluate_promotion({"G_VALIDATION": GateStatus.PASS})
    assert res.promotable is False
    assert set(res.blocking_gates) == set(MANDATORY_GATES) - {"G_VALIDATION"}


def test_later_pass_cannot_compensate_earlier_fail() -> None:
    gates = {g: GateStatus.PASS for g in MANDATORY_GATES}
    gates["G_VALIDATION"] = GateStatus.FAIL
    res = evaluate_promotion(gates)
    assert res.promotable is False
    assert "G_VALIDATION" in res.blocking_gates


def test_all_gates_pass_is_promotable() -> None:
    gates = {g: GateStatus.PASS for g in MANDATORY_GATES}
    assert evaluate_promotion(gates).promotable is True
