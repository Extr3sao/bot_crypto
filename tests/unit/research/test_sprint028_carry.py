"""RFC-028 — market-neutral carry tests (SYNTHETIC ONLY, no network/cache)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import sprint028_lib as L  # noqa: E402
import sprint028_signals as SG  # noqa: E402


def _panel(n_per_asset: int = 600, seed: int = 11) -> L.CarryPanel:
    rng = np.random.default_rng(seed)
    n = n_per_asset * len(L.ASSETS)
    asset = np.repeat(np.arange(len(L.ASSETS)), n_per_asset)
    ts = np.tile(np.arange(n_per_asset, dtype=np.int64) * L.FUNDING_INTERVAL_MS, len(L.ASSETS))
    spot = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    perp = spot * (1.0 + rng.normal(0, 1e-4, n))
    basis = (perp / spot - 1.0) * 1e4
    funding = rng.normal(0.8, 0.5, n)
    feats = {name: rng.normal(size=n) for name in L.FEATURE_NAMES}
    feats["basis"] = basis
    feats["f_mean_k"] = funding
    fwd_f = {h: rng.normal(size=n) * 10 for h in sorted(set(L.HORIZON_PERIODS.values()))}
    fwd_b = {h: rng.normal(size=n) * 5 for h in sorted(set(L.HORIZON_PERIODS.values()))}
    return L.CarryPanel(
        ts=ts,
        asset=asset,
        spot=spot,
        perp=perp,
        basis=basis,
        funding=funding,
        features=feats,
        fwd_funding=fwd_f,
        fwd_basis_pnl=fwd_b,
    )


# ---------------------------------------------------------------------------
# frozen constants
# ---------------------------------------------------------------------------


def test_carry_cost_model_not_v3() -> None:
    assert abs(L.ROUND_TRIP_COST_BPS - 39.0) < 1e-9
    assert abs(L.ROUND_TRIP_COST_BPS - L.COST_MODEL_V3_BPS) > 1.0
    assert L.ROUND_TRIP_COST_BPS == 2 * L.SPOT_SIDE_BPS + 2 * L.PERP_SIDE_BPS


def test_committed_capital_accounting() -> None:
    assert abs(L.COMMITTED_CAPITAL - (L.SPOT_LEG_CAPITAL + L.PERP_LEG_CAPITAL)) < 1e-12
    assert L.PERP_LEVERAGE <= 5.0


def test_splits_chronological_and_holdout_not_loaded() -> None:
    assert L.SPLIT_FRACTIONS["DISCOVERY"] == (0.0, 0.6)
    assert L.SPLIT_FRACTIONS["VALIDATION"] == (0.6, 0.8)
    assert L.SPLIT_FRACTIONS["HOLDOUT"] == (0.8, 1.0)
    assert L.HOLDOUT_ANALYTICS_READ is False


def test_hypothesis_and_variant_budget() -> None:
    assert len(SG.HYPOTHESES) == 13
    variants = SG.build_variants()
    assert len(variants) == 13 * len(L.HORIZON_ORDER)
    assert len({v.variant_id for v in variants}) == len(variants)


def test_break_even_math() -> None:
    assert abs(L.break_even_funding_bps("8h") - 39.0) < 1e-9
    assert abs(L.break_even_funding_bps("7d") - 39.0 / 21) < 1e-9
    p = L.break_even_holding_periods(1.0)
    assert p is not None and abs(p - 39.0) < 1e-9
    assert L.break_even_holding_periods(-0.1) is None


# ---------------------------------------------------------------------------
# funding PIT
# ---------------------------------------------------------------------------


def test_shift_and_mean_are_strictly_past() -> None:
    x = np.arange(10, dtype=np.float64)
    assert np.isnan(L._shift(x, 1)[0])
    assert L._shift(x, 1)[5] == 4.0
    m = L._mean_of_lag(x, 3)
    assert np.all(np.isnan(m[:3]))
    assert m[3] == np.mean([0.0, 1.0, 2.0])
    assert m[5] == np.mean([2.0, 3.0, 4.0])


def test_persist_is_strictly_past() -> None:
    x = np.array([1.0, 1.0, 1.0, -1.0, 1.0])
    p = L._persist_of_lag(x, 3)
    assert p[4] == 2.0 / 3.0
    assert np.isnan(p[2])


def test_entry_signal_uses_only_trailing_features() -> None:
    panel = _panel(50)
    v = SG.build_variants()[0]
    s = SG.entry_signal(v, panel, "RULE_POS", 1)
    assert s.dtype == bool
    assert s.shape == (len(panel),)


# ---------------------------------------------------------------------------
# multi-leg accounting
# ---------------------------------------------------------------------------


def test_carry_trade_reconciles_exactly() -> None:
    acc = L.carry_trade(
        spot0=100.0, spot1=101.0, perp0=100.5, perp1=100.4, funding_sum_bps=10.0, cost_bps=39.0
    )
    assert (
        abs(
            acc["net_bps"]
            - (acc["spot_pnl_bps"] + acc["perp_pnl_bps"] + acc["funding_pnl_bps"] - acc["cost_bps"])
        )
        < 1e-9
    )
    assert abs(acc["basis_pnl_bps"] - (acc["spot_pnl_bps"] + acc["perp_pnl_bps"])) < 1e-9


def test_funding_payment_sign_short_perp_receives_positive() -> None:
    acc = L.carry_trade(100.0, 100.0, 100.0, 100.0, funding_sum_bps=5.0)
    assert acc["funding_pnl_bps"] == 5.0
    assert acc["net_bps"] == 5.0 - L.ROUND_TRIP_COST_BPS


def test_spot_and_perp_legs_offset_when_prices_move_together() -> None:
    acc = L.carry_trade(100.0, 110.0, 100.0, 110.0, funding_sum_bps=0.0, cost_bps=0.0)
    assert abs(acc["spot_pnl_bps"] + acc["perp_pnl_bps"]) < 1e-9


def test_residual_delta_zero_for_equal_notional() -> None:
    assert abs(L.residual_delta(100.0, 100.0)) < 1e-12


def test_return_on_committed_capital_uses_full_denominator() -> None:
    acc = L.carry_trade(100.0, 100.0, 100.0, 100.0, funding_sum_bps=39.0, cost_bps=0.0)
    assert abs(acc["return_on_committed"] - (39.0 / 1e4) / L.COMMITTED_CAPITAL) < 1e-12


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------


def test_simulate_is_deterministic_and_non_overlapping() -> None:
    panel = _panel(400)
    mask = np.ones(len(panel), dtype=bool)
    sig = np.ones(len(panel), dtype=bool)
    a = L.simulate_candidate(panel, mask, sig, "24h")
    b = L.simulate_candidate(panel, mask, sig, "24h")
    a.pop("trades_list")
    b.pop("trades_list")
    assert a == b
    assert a["trades"] > 0
    assert a["holding_periods"] == 3


def test_simulate_skips_missing_data_no_imputation() -> None:
    panel = _panel(300)
    bad = L.CarryPanel(
        ts=panel.ts,
        asset=panel.asset,
        spot=panel.spot,
        perp=panel.perp,
        basis=panel.basis,
        funding=panel.funding,
        features=panel.features,
        fwd_funding={h: np.full_like(v, np.nan) for h, v in panel.fwd_funding.items()},
        fwd_basis_pnl=panel.fwd_basis_pnl,
    )
    r = L.simulate_candidate(
        bad, np.ones(len(bad), dtype=bool), np.ones(len(bad), dtype=bool), "8h"
    )
    assert r["status"] == "NO_TRADES"


def test_split_masks_disjoint_and_cover() -> None:
    panel = _panel(100)
    m = L.split_masks(panel)
    total = m["DISCOVERY"].sum() + m["VALIDATION"].sum() + m["HOLDOUT"].sum()
    assert total == len(panel)
    assert not np.any(m["DISCOVERY"] & m["VALIDATION"])
    assert not np.any(m["VALIDATION"] & m["HOLDOUT"])
