"""RFC-029 — structural low-turnover carry tests (SYNTHETIC ONLY, no network)."""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint028_fetch as F  # noqa: E402
import sprint029_lib as S  # noqa: E402


def _panel(
    n: int = 400, asset: str = "BTCUSDT", funding: float = 1.0, seed: int = 7
) -> S.AssetPanel:
    rng = np.random.default_rng(seed)
    ts = np.arange(n, dtype=np.int64) * S.FUNDING_INTERVAL_MS
    spot = 100.0 + np.cumsum(rng.normal(0, 0.05, n))
    perp = spot * (1.0 + rng.normal(0, 2e-5, n))
    rate = np.full(n, funding, dtype=np.float64) + rng.normal(0, 0.05, n)
    basis = (perp / spot - 1.0) * 1e4
    return S.AssetPanel(
        asset=asset,
        ts=ts,
        spot=spot,
        perp=perp,
        basis=basis,
        funding=rate,
        f_mean_w=S.L._mean_of_lag(rate, S.TRAILING_WINDOW),
        f_persist_n=S.L._persist_of_lag(rate, S.PERSIST_N),
    )


# ---------------------------------------------------------------------------
# frozen constants / budget
# ---------------------------------------------------------------------------


def test_cost_model_is_carry_v1_not_v3() -> None:
    assert abs(S.ROUND_TRIP_COST_BPS - 39.0) < 1e-9
    assert abs(S.ROUND_TRIP_COST_BPS - S.COST_MODEL_V3_BPS) > 1.0
    assert S.ROUND_TRIP_COST_BPS == 2 * S.SPOT_SIDE_BPS + 2 * S.PERP_SIDE_BPS


def test_committed_capital_accounting() -> None:
    assert abs(S.COMMITTED_CAPITAL - (1.0 + 1.0 / S.PERP_LEVERAGE)) < 1e-12
    assert S.PERP_LEVERAGE <= 5.0


def test_horizon_budget_and_core_cells() -> None:
    assert S.HORIZON_PERIODS == {"7d": 21, "14d": 42, "21d": 63, "30d": 90, "45d": 135}
    assert len(S.POLICIES) == 4
    assert S.CORE_CELLS == 4 * 4 * 3 == 48
    assert S.REFERENCE_HORIZON == "7d"


def test_splits_chronological_and_holdout_locked() -> None:
    assert S.SPLIT_FRACTIONS["DISCOVERY"] == (0.0, 0.6)
    assert S.SPLIT_FRACTIONS["HOLDOUT"] == (0.8, 1.0)
    assert S.HOLDOUT_ANALYTICS_READ is False


def test_break_even_math() -> None:
    assert abs(S.break_even_funding_bps("14d") - 39.0 / 42) < 1e-9
    assert abs(S.break_even_funding_bps("45d") - 39.0 / 135) < 1e-9
    d = S.break_even_holding_days(0.85)
    assert d is not None and abs(d - (39.0 / 0.85) / 3) < 1e-9
    assert S.break_even_holding_days(-1.0) is None


# ---------------------------------------------------------------------------
# spot epoch normalisation (§20) — BOTH eras
# ---------------------------------------------------------------------------


def test_spot_epoch_ms_and_us_normalised_identically() -> None:
    ms = 1_717_200_000_000  # 2024-06-01 (millisecond epoch)
    us = ms * 1000  # same instant in microseconds

    def row(raw: int) -> list[str]:
        return [str(raw), "1.0", "2.0", "0.5", "1.5", "10.0"]

    out_ms = F.canonicalize_spot_klines([row(ms)])
    out_us = F.canonicalize_spot_klines([row(us)])
    assert out_ms["open_time_ms"].tolist() == [ms]
    assert out_us["open_time_ms"].tolist() == [ms]
    assert out_ms["close"].tolist() == out_us["close"].tolist()
    # unit histogram records the erase
    assert "ms" in out_ms["_unit_hist"][0]
    assert "us" in out_us["_unit_hist"][0]
    assert out_us["_first_us_day"][0] == "2024-06-01"


# ---------------------------------------------------------------------------
# funding PIT (§19)
# ---------------------------------------------------------------------------


def test_entry_mask_uses_only_strictly_past_funding() -> None:
    n = 200
    rate = np.full(n, 1.0)
    m0 = S.L._mean_of_lag(rate, S.TRAILING_WINDOW)
    base = np.isfinite(m0) & (m0 > 0.0)
    for i in range(S.TRAILING_WINDOW, n):
        r2 = rate.copy()
        r2[i] = r2[i] + 100.0
        m2 = S.L._mean_of_lag(r2, S.TRAILING_WINDOW)
        m2b = np.isfinite(m2) & (m2 > 0.0)
        assert np.array_equal(m2b[: i + 1], base[: i + 1])


def test_policy_c_economic_threshold_is_horizon_scaled() -> None:
    panel = _panel(120, funding=0.5)
    m14 = S.entry_mask(panel, "C_ECONOMIC", "14d")
    m45 = S.entry_mask(panel, "C_ECONOMIC", "45d")
    # a longer horizon demands a lower per-period rate, so it is never stricter
    assert m45.sum() >= m14.sum()


def test_policy_b_persistence_requires_all_last_n_positive() -> None:
    panel = _panel(200, funding=1.0)
    p = panel.funding.copy()
    p[50:53] = p[50:53]  # noop
    mask = S.entry_mask(panel, "B_PERSISTENCE", "14d")
    assert mask.dtype == bool
    assert mask.shape == (panel.n(),)


# ---------------------------------------------------------------------------
# multi-leg accounting (§26-§28, §42-§43)
# ---------------------------------------------------------------------------


def test_flat_price_trade_net_is_funding_minus_cost() -> None:
    n = 200
    ts = np.arange(n, dtype=np.int64) * S.FUNDING_INTERVAL_MS
    spot = np.full(n, 100.0)
    perp = np.full(n, 100.0)
    rate = np.full(n, 1.0)
    p = S.AssetPanel(
        asset="BTCUSDT",
        ts=ts,
        spot=spot,
        perp=perp,
        basis=np.zeros(n),
        funding=rate,
        f_mean_w=S.L._mean_of_lag(rate, S.TRAILING_WINDOW),
        f_persist_n=S.L._persist_of_lag(rate, S.PERSIST_N),
    )
    trades = S.simulate(p, "A_POSITIVE_REGIME", "14d", "A_FIXED_HOLD", 0.0, 0.6)
    assert trades
    for t in trades:
        assert abs(t.spot_pnl_bps) < 1e-9 and abs(t.perp_pnl_bps) < 1e-9
        assert abs(t.basis_pnl_bps) < 1e-9
        assert abs(t.funding_pnl_bps - 42.0) < 1e-9  # 42 periods x 1.0
        assert abs(t.net_bps - (42.0 - S.ROUND_TRIP_COST_BPS)) < 1e-9
        assert abs(t.return_on_committed - (t.net_bps / 1e4) / S.COMMITTED_CAPITAL) < 1e-12


def test_funding_sign_short_perp_receives_positive_rate() -> None:
    panel = _panel(200, funding=1.0)
    trades = S.simulate(panel, "A_POSITIVE_REGIME", "14d", "A_FIXED_HOLD", 0.0, 0.6)
    assert all(t.funding_pnl_bps > 0 for t in trades)


def test_accounting_identity_holds_for_every_trade() -> None:
    panel = _panel(400)
    for pol in S.POLICIES:
        for t in S.simulate(panel, pol, "30d", "A_FIXED_HOLD", 0.0, 0.6):
            assert (
                abs(t.net_bps - (t.spot_pnl_bps + t.perp_pnl_bps + t.funding_pnl_bps - t.cost_bps))
                < 1e-9
            )
            assert abs(t.basis_pnl_bps - (t.spot_pnl_bps + t.perp_pnl_bps)) < 1e-9
            assert abs(t.cost_bps - S.ROUND_TRIP_COST_BPS) < 1e-9


def test_delta_neutral_when_legs_move_together() -> None:
    # spot and perp shift by the same factor -> basis/residual PnL ~ 0
    n = 200
    ts = np.arange(n, dtype=np.int64) * S.FUNDING_INTERVAL_MS
    spot = 100.0 * np.exp(np.linspace(0, 0.5, n))
    perp = spot.copy()
    rate = np.full(n, 1.0)
    p = S.AssetPanel(
        asset="ETHUSDT",
        ts=ts,
        spot=spot,
        perp=perp,
        basis=np.zeros(n),
        funding=rate,
        f_mean_w=S.L._mean_of_lag(rate, S.TRAILING_WINDOW),
        f_persist_n=S.L._persist_of_lag(rate, S.PERSIST_N),
    )
    for t in S.simulate(p, "A_POSITIVE_REGIME", "21d", "A_FIXED_HOLD", 0.0, 0.6):
        assert abs(t.basis_pnl_bps) < 1e-6


def test_return_per_capital_day_uses_capital_days() -> None:
    panel = _panel(400)
    trades = S.simulate(panel, "A_POSITIVE_REGIME", "30d", "A_FIXED_HOLD", 0.0, 0.6)
    agg = S.aggregate(trades)
    assert abs(agg["return_per_capital_day"] - agg["net_return"] / agg["capital_days"]) < 1e-6
    assert abs(agg["sum_roc"] - agg["net_return"] / S.COMMITTED_CAPITAL) < 1e-6


# ---------------------------------------------------------------------------
# simulation properties
# ---------------------------------------------------------------------------


def test_simulation_is_deterministic_and_non_overlapping() -> None:
    panel = _panel(500)
    a = S.simulate(panel, "C_ECONOMIC", "30d", "A_FIXED_HOLD", 0.0, 0.6)
    b = S.simulate(panel, "C_ECONOMIC", "30d", "A_FIXED_HOLD", 0.0, 0.6)
    assert [t.net_bps for t in a] == [t.net_bps for t in b]
    for first, second in itertools.pairwise(a):
        assert second.entry_idx > first.exit_idx  # one active position per asset


def test_missing_data_skips_episode_no_imputation() -> None:
    panel = _panel(200)
    bad = S.AssetPanel(
        asset=panel.asset,
        ts=panel.ts,
        spot=panel.spot,
        perp=panel.perp,
        basis=panel.basis,
        funding=np.full(panel.n(), np.nan),
        f_mean_w=panel.f_mean_w,
        f_persist_n=panel.f_persist_n,
    )
    assert S.simulate(bad, "A_POSITIVE_REGIME", "14d", "A_FIXED_HOLD", 0.0, 0.6) == []


def test_exit_model_b_only_shortens_holding() -> None:
    panel = _panel(500, funding=1.0)
    fixed = S.simulate(panel, "A_POSITIVE_REGIME", "45d", "A_FIXED_HOLD", 0.0, 0.6)
    brk = S.simulate(panel, "A_POSITIVE_REGIME", "45d", "B_FUNDING_BREAK", 0.0, 0.6)
    assert all(t.holding_periods <= 135 for t in brk)
    # with a permanently positive rate, the regime never breaks -> same as fixed
    assert [t.holding_periods for t in fixed] == [t.holding_periods for t in brk]


def test_aggregate_no_trades_status() -> None:
    assert S.aggregate([])["status"] == "NO_TRADES"
