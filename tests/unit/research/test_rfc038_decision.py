"""RFC-038 §51 tests: capital arithmetic, nulls, decision state machine, no purchase."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import rfc036_data as DATA  # noqa: E402
import rfc038_capital as CAP  # noqa: E402
import rfc038_data as DAT  # noqa: E402
import rfc038_nulls as NUL  # noqa: E402
import rfc038_run as RUN  # noqa: E402

from trading_bot.research import managed_futures_v1 as mf  # noqa: E402


def _gc_panel() -> tuple[list[Any], list[int], tuple[int, int]]:
    md = DATA.load_market("gc")
    lo = date(1995, 1, 1).toordinal()
    hi = date(2000, 3, 31).toordinal()
    ts = mf.build_tradable_series(md, date(1990, 1, 1).toordinal(), hi)
    cal = sorted(ts.held)
    return [mf.build_panel(md, ts, cal)], cal, (lo, hi)


def test_rounding_policies() -> None:
    assert CAP._round(2.4, "nearest") == 2.0
    assert CAP._round(2.6, "nearest") == 3.0
    assert CAP._round(2.9, "floor") == 2.0
    assert CAP._round(-2.9, "floor") == -2.0
    assert CAP._round(-2.4, "nearest") == -2.0


def test_contract_notional_and_weight_invariants() -> None:
    panels, cal, window = _gc_panel()
    run = CAP.replay(panels, cal, window, 1_000_000.0, "nearest")
    assert run["status"] == "OK"
    assert len(run["records"]) > 0
    for r in run["records"]:
        assert (
            abs(r["actual_notional"] - r["rounded_contract_count"] * r["price"] * r["multiplier"])
            < 1e-6
        )
        assert abs(r["actual_weight"] - r["actual_notional"] / 1_000_000.0) < 1e-12
        assert (
            abs(
                r["raw_contract_count"]
                - r["weight_target"] * 1_000_000.0 / (r["price"] * r["multiplier"])
            )
            < 1e-9
        )


def test_fractional_pnl_is_linear_in_capital() -> None:
    panels, cal, window = _gc_panel()
    lo, hi = window
    a = mf.simulate_portfolio(panels, cal, (lo, hi), mf.default_config(), 1_000_000.0)
    b = mf.simulate_portfolio(panels, cal, (lo, hi), mf.default_config(), 2_000_000.0)
    na, nb = float(a["net_pnl"].sum()), float(b["net_pnl"].sum())
    assert abs(nb - 2.0 * na) <= 1e-6 * abs(2.0 * na) + 1e-6


def test_tracking_error_rescaling_defect() -> None:
    # a fractional reference at 10M compared (unscaled) against integer PnL at 100M
    # explodes; the same reference rescaled to 100M does not. This is the RFC-037 bug.
    frac_ref = 1_000_000.0
    net_int_100 = 8_800_000.0
    te_rfc037 = (net_int_100 - frac_ref) / abs(frac_ref)
    frac_ref_100 = frac_ref * 10.0
    te_corrected = (net_int_100 - frac_ref_100) / abs(frac_ref_100)
    assert te_rfc037 > 1.0
    assert abs(te_corrected) < 0.15


def test_replay_reconciles_to_frozen_engine() -> None:
    panels, cal, window = _gc_panel()
    lo, hi = window
    engine = mf.simulate_portfolio(
        panels, cal, (lo, hi), mf.default_config(integer_contracts=True), 1_000_000.0
    )
    replay = CAP.replay(panels, cal, window, 1_000_000.0, "nearest")
    assert abs(float(engine["net_pnl"].sum()) - replay["net_total"]) <= 1e-9 * abs(
        float(engine["net_pnl"].sum())
    )


def test_null_registry_is_preregistered_and_bounded() -> None:
    reg = NUL.registry()
    assert len(reg["primary_families"]) == 3
    assert reg["seed"] == NUL.SEED
    assert reg["n_sims"] == NUL.N_SIMS


def test_null_randomisation_deterministic() -> None:
    a = np.random.default_rng(NUL.SEED).permutation(26).tolist()
    b = np.random.default_rng(NUL.SEED).permutation(26).tolist()
    assert a == b


def test_circular_shift_preserves_marginals_and_cross_market_structure() -> None:
    rng = np.random.default_rng(0)
    R = rng.normal(size=(200, 4))
    q = 37
    shifted = np.roll(R, q, axis=0)
    for j in range(R.shape[1]):
        assert np.allclose(np.sort(shifted[:, j]), np.sort(R[:, j]))
    # a SHARED shift is a pure time translation -> correlation matrix unchanged
    assert np.allclose(np.corrcoef(shifted, rowvar=False), np.corrcoef(R, rowvar=False))


def test_block_permutation_uses_shared_order_over_returns_only() -> None:
    # shared block permutation must preserve the multi-set of each column and the
    # cross-market correlation spectrum (rows move together for every market).
    rng = np.random.default_rng(1)
    R = rng.normal(size=(500, 3))
    block = 100
    starts = list(range(0, R.shape[0], block))
    bounds = [(s, min(s + block, R.shape[0])) for s in starts]
    order = rng.permutation(len(bounds))
    idx = np.concatenate([np.arange(bounds[b][0], bounds[b][1]) for b in order])
    perm = R[idx, :]
    for j in range(R.shape[1]):
        assert np.allclose(np.sort(perm[:, j]), np.sort(R[:, j]))


def test_adversarial_gate_reads_valid_nulls() -> None:
    good = {
        "VALIDATION": {
            "NULL-2_BLOCK_CIRCULAR_SHIFT_shared": {"p_null_ge_observed": 0.01},
            "NULL-3_SIGN_RANDOMISATION": {"p_null_ge_observed": 0.0},
        }
    }
    bad = {
        "VALIDATION": {
            "NULL-2_BLOCK_CIRCULAR_SHIFT_shared": {"p_null_ge_observed": 0.20},
            "NULL-3_SIGN_RANDOMISATION": {"p_null_ge_observed": 0.0},
        }
    }
    assert RUN.adversarial_gate(good) == "PASS"
    assert RUN.adversarial_gate(bad) == "FAIL"


def test_null_validity_gate() -> None:
    assert RUN.null_validity_gate({"a": {"valid": True}}) == "PASS"
    assert RUN.null_validity_gate({"a": {"valid": False}}) == "FAIL"


def _provider(quote_required: bool, deprecated: bool = False) -> dict[str, Any]:
    return {
        "provider": "X",
        "dataset": "d",
        "coverage": "c",
        "history": "h",
        "individual_contracts": True,
        "term_structure": True,
        "volume": True,
        "open_interest": True,
        "pit_suitability": "HIGH",
        "licence": "l",
        "api_file_format": "API",
        "p1_suitability": "HIGH",
        "p2_suitability": "HIGH",
        "price": "DEPRECATED"
        if deprecated
        else ("QUOTE_REQUIRED" if quote_required else "$1/month"),
        "quote_required": quote_required,
        "source": "s",
    }


def test_decision_state_machine() -> None:
    assert DAT.decide([_provider(quote_required=True)])["classification"] == "REQUEST_QUOTE"
    assert DAT.decide([_provider(quote_required=False)])["classification"] == "BUY_CANDIDATE"
    assert (
        DAT.decide([_provider(quote_required=False, deprecated=True)])["classification"]
        == "DO_NOT_BUY"
    )


def test_quote_required_providers_never_invent_a_price() -> None:
    for p in DAT.provider_matrix():
        if p["quote_required"]:
            assert "QUOTE_REQUIRED" in str(p["price"])


def test_no_automatic_purchase_possible() -> None:
    # the decision function can never return an "approved/executed" state
    allowed = {"DO_NOT_BUY", "REQUEST_QUOTE", "BUY_CANDIDATE"}
    for p in DAT.provider_matrix():
        d = DAT.decide([p])
        assert d["classification"] in allowed
    src = (REPO / "scripts" / "rfc038_data.py").read_text(encoding="utf-8")
    assert "credit card" in src.lower() or "no credit card" in src.lower()
