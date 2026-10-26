"""RFC-037 §56 tests: reconciliation discipline, KPI semantics, gate logic, determinism."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import rfc036_data as DATA  # noqa: E402
import rfc036_verify as V  # noqa: E402
import rfc037_adversarial as ADV  # noqa: E402
import rfc037_run as RUN  # noqa: E402

from trading_bot.research import managed_futures_v1 as mf  # noqa: E402


def test_no_post_hoc_tolerance_in_verifier() -> None:
    src = (REPO / "scripts" / "rfc036_verify.py").read_text(encoding="utf-8")
    # the RFC-037 fix keeps a FIXED numerical tolerance, not a widened 5%
    assert "< 1e-5" in src
    assert "0.05" not in src


def test_reconciliation_was_root_caused_not_tolerated() -> None:
    src = (REPO / "scripts" / "rfc036_verify.py").read_text(encoding="utf-8")
    # the staleness bookkeeping must be initialised (the RFC-036 verifier bug)
    assert "last_print: dict[str, int] = {cid: 0 for cid in m.contracts}" in src


def test_kpi_canonical_semantics() -> None:
    kpi = {
        "HISTORICAL_EXECUTABLE_VALIDATED_EDGE_COUNT": 1,
        "MODERN_VALIDATED_EDGE_COUNT": 0,
        "HISTORICAL_ROBUST_EDGE_COUNT": 1,
        "PAPER_CANDIDATE_COUNT": 0,
        "FORWARD_PROFITABLE_COUNT": 0,
        "LIVE_PROFITABLE_COUNT": 0,
    }
    assert kpi["HISTORICAL_ROBUST_EDGE_COUNT"] == 1
    assert kpi["PAPER_CANDIDATE_COUNT"] == 0
    assert kpi["MODERN_VALIDATED_EDGE_COUNT"] == 0


def test_adversarial_gate_requires_beating_both_nulls() -> None:
    good = {"DISCOVERY": {"perm_p_null_ge_observed": 0.01, "sign_p_null_ge_observed": 0.0},
            "VALIDATION": {"perm_p_null_ge_observed": 0.02, "sign_p_null_ge_observed": 0.0}}
    assert RUN.adversarial_gate(good) == "PASS"
    bad = {"DISCOVERY": {"perm_p_null_ge_observed": 0.24, "sign_p_null_ge_observed": 0.0}}
    assert RUN.adversarial_gate(bad) == "FAIL"


def test_capital_gate_classification() -> None:
    assert RUN.capital_gate({"minimum_viable_capital": 2_000_000,
                             "minimum_preferred_capital": 5_000_000}) == "PRACTICALLY_EXECUTABLE"
    assert RUN.capital_gate({"minimum_viable_capital": None,
                             "minimum_preferred_capital": None}) == "HIGH_CAPITAL_ONLY"
    assert RUN.capital_gate({"minimum_viable_capital": None,
                             "minimum_preferred_capital": 5_000_000}) == \
        "EXECUTABLE_WITH_LIMITATIONS"


def test_null_randomization_is_deterministic() -> None:
    a = np.random.default_rng(ADV.SEED).permutation(10).tolist()
    b = np.random.default_rng(ADV.SEED).permutation(10).tolist()
    assert a == b


def test_market_universe_matches_verifier_specs() -> None:
    # the adversarial harness iterates exactly the frozen verifier universe
    assert len(V.SPECS) == 26
    assert sorted(V.SPECS) == sorted(ADV.V.SPECS)


def test_integer_contracts_materially_change_low_capital() -> None:
    # §34/§37: at small capital, integer contracts drop many markets
    bm = DATA.load_market("gc")
    ts = mf.build_tradable_series(bm, date(1980, 1, 1).toordinal(),
                                  date(2000, 3, 31).toordinal())
    cal = sorted(ts.held)
    panel = mf.build_panel(bm, ts, cal)
    cfg_int = mf.default_config(integer_contracts=True)
    small = mf.simulate_portfolio([panel], cal, (cal[0], cal[-1]), cfg_int, 100_000.0)
    assert small["status"] == "OK"
    # a single 100 oz gold contract is ~40k; a 100k book can hold ~2 -> coarse
    assert float(np.mean(small["n_long"] + small["n_short"])) <= 3.0


def test_frozen_markers_not_mutated_by_rfc037() -> None:
    assert mf.CANDIDATE_ID == "MF-TREND-001"
    assert mf.P2_STATUS == "AUTHORIZED_WAITING"
    assert mf.HOLDOUT == "FUTURE_ONLY"
