"""ARC-01 preregistration tests (checkpoint ARC01-PREREG-001).

These tests are non-economic: they assert structure, bindings, PIT invariance and
rule semantics on IN-MEMORY synthetic fixtures only. No dataset is loaded, and no
return, PnL, Sharpe, profit factor or expectancy is ever computed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot.research.arc01 import prereg_reference as ref

REPO = Path(__file__).resolve().parents[3]
PREREG_DIR = REPO / "docs" / "arc01-prereg-01"


def _load_json(name: str) -> dict:
    return json.loads((PREREG_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spec() -> dict:
    return _load_json("ARC01_SPEC_V1.json")


@pytest.fixture()
def decision_time() -> int:
    step = 8 * 3_600_000
    base = 1_700_000_000_000
    return base - (base % step) + step * 40


def _window_series(decision_time: int, n: int = 183, current: float | None = None) -> list[tuple[int, float]]:
    step = 8 * 3_600_000
    series = [(decision_time - (n - 1 - i) * step, 0.0001 + 0.0001 * (i % 3)) for i in range(n)]
    if current is not None:
        series[-1] = (decision_time, current)
    return series


# --------------------------------------------------------------------------
# Artifact presence and JSON validity
# --------------------------------------------------------------------------
REQUIRED_ARTIFACTS = (
    "ARC01_SPEC_V1.json",
    "ARC01_MANIFEST_V1.json",
    "ARC01_PREREGISTRATION.md",
    "ARC01_MECHANISM_EVIDENCE.md",
    "ARC01_SELECTION_RATIONALE.md",
    "ARC01_PIT_CONTRACT.json",
    "ARC01_CONTROL_PLAN.json",
    "ARC01_STATISTICAL_GATES.json",
    "ARC01_ROBUSTNESS_PLAN.json",
    "ARC01_FAILED_MEMORY_COLLISION_REVIEW.md",
    "ARC01_PREREG_VERIFICATION_PACKAGE.json",
    "RUN_REPORT.json",
    "RUN_REPORT.md",
)


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_ARTIFACTS)
def test_required_artifact_present_and_valid(name: str) -> None:
    path = PREREG_DIR / name
    assert path.exists(), f"missing frozen artifact {name}"
    if name.endswith(".json"):
        json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Frozen economic parameters
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_assets_and_market_frozen(spec: dict) -> None:
    assert spec["market"]["assets"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert spec["market"]["venue"] == "Binance"
    assert "USDT-margined perpetual" in spec["market"]["segment"]


@pytest.mark.unit
def test_common_window_matches_authority_intersection(spec: dict) -> None:
    cw = spec["common_window"]
    assert (cw["start_ms"], cw["end_ms"]) == (ref.COMMON_WINDOW_START_MS, ref.COMMON_WINDOW_END_MS)
    assert cw["start_utc"] == "2021-12-01T00:00:00Z"
    assert cw["end_utc"] == "2026-09-10T23:00:00Z"


@pytest.mark.unit
def test_funding_transform_frozen(spec: dict) -> None:
    ft = spec["funding_transform"]
    assert ft["type"] == "ROBUST_Z_SCORE"
    assert ft["lookback"]["length_days"] == 60
    assert ft["minimum_observations"] == ref.FUNDING_MIN_OBSERVATIONS == 90
    assert ft["location_estimator"] == "MEDIAN of the window funding rates"
    assert ft["mad_multiplier"] == ref.MAD_SCALE
    assert ft["threshold"]["positive"] == ref.FUNDING_Z_POSITIVE_THRESHOLD == 2.0
    assert ft["threshold"]["negative"] == ref.FUNDING_Z_NEGATIVE_THRESHOLD == -2.0
    assert "INCLUSIVE" in ft["threshold"]["inequality"]


@pytest.mark.unit
def test_oi_confirmation_frozen(spec: dict) -> None:
    oi = spec["oi_transform"]
    assert oi["lookback"]["length_hours"] == 24
    assert oi["threshold"]["type"] == "SIGN"
    assert oi["threshold"]["value"] == 0.0
    assert "STRICT" in oi["threshold"]["inequality"].upper()
    assert "NO_SIGNAL" in oi["contraction_behavior"] and "NEVER" in oi["contraction_behavior"].upper()
    assert oi["magnitude_gate"].startswith("NONE")


@pytest.mark.unit
def test_price_context_is_none(spec: dict) -> None:
    assert spec["price_context"]["PRICE_CONTEXT"] == "NONE"
    assert spec["price_context"]["required_price_features"] == []


@pytest.mark.unit
def test_policies_and_holding_frozen(spec: dict) -> None:
    assert spec["exit"]["holding_period"]["PRIMARY_HOLDING_PERIOD"] == "exactly 72 hours (3 days)"
    assert spec["exit"]["holding_period"]["holding_bars"] == 72
    assert ref.HOLDING_MS == 72 * 3_600_000
    assert spec["position_policies"]["STOP"] == "NONE"
    assert spec["position_policies"]["COOLDOWN"] == "NONE"
    assert spec["position_policies"]["OVERLAPPING_SIGNAL_POLICY"].startswith("SKIP")


@pytest.mark.unit
def test_cost_model_frozen(spec: dict) -> None:
    assert spec["cost_model"]["PRIMARY_ROUND_TRIP_COST_BPS"] == 10
    assert spec["cost_model"]["cost_sensitivities_bps"] == [0, 10, 20, 40]


@pytest.mark.unit
def test_funding_cashflow_crosses_settlements_and_separated(spec: dict) -> None:
    cash = spec["funding_cashflow_accounting"]
    assert cash["no_double_counting"] is True
    assert "YES" in cash["crosses_settlement"]
    assert cash["signal_information_vs_execution_cashflow"] == "SEPARATED BY CONSTRUCTION"


# --------------------------------------------------------------------------
# Data binding
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_data_authority_binding_exact(spec: dict) -> None:
    da = spec["data_authority"]
    assert da["authority_commit"] == "6e42dd9d4c19800925fd555999686d1e2b4ef47e"
    assert da["dataset_sha256"] == "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"
    assert da["partition_sha256"] == {
        "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
        "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
        "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
    }
    assert da["oi_authority"]["oi_full_history_dataset_sha256_v2"] == "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"
    assert da["price_authority"]["price_authority_sha256_v2"] == "e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168"


@pytest.mark.unit
def test_no_economic_observation_flags(spec: dict) -> None:
    econ = spec["economics"]
    assert econ == {"ARC01_BACKTESTS": 0, "ARC01_EXECUTIONS": 0, "ARC01_PERFORMANCE_OBSERVED": False, "FALSE_SUCCESS": 0}
    assert _load_json("RUN_REPORT.json")["economics"]["ARC01_PERFORMANCE_OBSERVED"] is False


# --------------------------------------------------------------------------
# Controls / gates / robustness / kill rule
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_four_controls_frozen() -> None:
    plan = _load_json("ARC01_CONTROL_PLAN.json")
    ids = {c["id"] for c in plan["controls"]}
    assert ids == {"DIRECTION_CONTROL", "TIMING_CONTROL", "OI_CONTROL", "NULL_CONTROL"}
    assert plan["controls_cannot_be_promoted"] is True


@pytest.mark.unit
def test_statistical_gates_frozen() -> None:
    gates = _load_json("ARC01_STATISTICAL_GATES.json")
    ids = {g["id"] for g in gates["critical_gates"]}
    assert ids == {
        "G1_SAMPLE",
        "G2_NET_EXPECTANCY",
        "G3_NET_EXPECTANCY_EX_FUNDING",
        "G4_PROFIT_FACTOR",
        "G5_SHARPE",
        "G6_SHARPE_UNCERTAINTY",
        "G7_PERMUTATION",
        "G8_TEMPORAL_STABILITY",
        "G9_ASSET_STABILITY",
        "G10_CONCENTRATION",
        "G11_COST_SENSITIVITY",
    }
    assert gates["no_single_metric_sufficient"] is True
    assert gates["primary_cost_bps"] == 10
    assert [s["cost_bps_round_trip"] for s in gates["frozen_evaluation_scenarios"]] == [0, 10, 20, 40]


@pytest.mark.unit
def test_robustness_plan_frozen_not_executed() -> None:
    plan = _load_json("ARC01_ROBUSTNESS_PLAN.json")
    assert plan["executed_now"] is False
    ids = {r["id"] for r in plan["robustness_analyses"]}
    assert {"R1_TIME_SPLITS", "R2_ASSET_SPLITS", "R3_REGIME_SPLITS", "R4_COST_SENSITIVITY", "R5_PARAMETER_NEIGHBOURHOOD", "R6_CONCENTRATION", "R7_SIGNAL_COUNT_STABILITY"} == ids


@pytest.mark.unit
def test_kill_rule_frozen(spec: dict) -> None:
    kill = spec["kill_rule"]
    assert kill["ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY"] is True
    assert "DISCOVERY_FAIL" in kill["on_critical_gate_failure"]
    assert "NEW_HYPOTHESIS_ID" in kill["future_variant_requires"]
    assert "threshold retuning" in kill["forbidden_after_failure"]


# --------------------------------------------------------------------------
# Rule semantics (synthetic fixtures, no data)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_threshold_boundary_is_inclusive() -> None:
    assert ref.decide_direction(2.0) == ref.SHORT
    assert ref.decide_direction(-2.0) == ref.LONG
    assert ref.decide_direction(1.9999999999999998) is None
    assert ref.decide_direction(-1.9999999999999998) is None


@pytest.mark.unit
def test_funding_extreme_direction_and_short_semantics(decision_time: int) -> None:
    series = _window_series(decision_time, current=0.01)
    state = ref.funding_extreme(series, decision_time)
    assert state["status"] == "OK"
    assert float(state["z"]) > 2.0  # type: ignore[arg-type]
    decision = ref.evaluate_decision(
        decision_time_ms=decision_time,
        funding_observations=series,
        oi_now=(decision_time, 3_000_000.0),
        oi_ref=(decision_time - 86_400_000, 2_000_000.0),
    )
    assert decision["result"] == ref.SHORT

    negative = _window_series(decision_time, current=-0.01)
    neg_decision = ref.evaluate_decision(
        decision_time_ms=decision_time,
        funding_observations=negative,
        oi_now=(decision_time, 3_000_000.0),
        oi_ref=(decision_time - 86_400_000, 2_000_000.0),
    )
    assert neg_decision["result"] == ref.LONG


@pytest.mark.unit
def test_mad_zero_fallback_and_degenerate_scale(decision_time: int) -> None:
    step = 8 * 3_600_000
    flat = [(decision_time - (183 - 1 - i) * step, 0.0001) for i in range(183)]
    assert ref.funding_extreme(flat, decision_time)["status"] == "SCALE_NONPOSITIVE"
    with_outlier = flat[:-1] + [(decision_time, 0.0101)]
    state = ref.funding_extreme(with_outlier, decision_time)
    assert state["status"] == "OK" and state["mad_fallback_used"] is True


@pytest.mark.unit
def test_insufficient_history_fails_closed(decision_time: int) -> None:
    short = _window_series(decision_time)[-10:]
    assert ref.funding_extreme(short, decision_time)["status"] == "INSUFFICIENT_FUNDING_HISTORY"


@pytest.mark.unit
def test_oi_neutral_and_contraction_never_confirm(decision_time: int) -> None:
    ref_point = (decision_time - 86_400_000, 2_000_000.0)
    assert ref.oi_change_24h((decision_time, 2_000_000.0), ref_point, decision_time)["oi_change_24h"] == 0.0
    assert float(ref.oi_change_24h((decision_time, 1_900_000.0), ref_point, decision_time)["oi_change_24h"]) < 0  # type: ignore[arg-type]
    series = _window_series(decision_time, current=0.01)
    decision = ref.evaluate_decision(
        decision_time_ms=decision_time,
        funding_observations=series,
        oi_now=(decision_time, 2_000_000.0),
        oi_ref=ref_point,
    )
    assert decision["result"] == ref.NO_SIGNAL
    assert decision["reason"] == "OI_NOT_EXPANDING"


@pytest.mark.unit
def test_oi_staleness_fails_closed(decision_time: int) -> None:
    assert ref.oi_change_24h((decision_time - 900_000, 3_000_000.0), (decision_time - 86_400_000, 2_000_000.0), decision_time)["status"] == "OI_MISSING_OR_STALE"
    assert ref.oi_change_24h((decision_time, 3_000_000.0), (decision_time - 86_400_000, 0.0), decision_time)["status"] == "OI_REFERENCE_INVALID"


@pytest.mark.unit
def test_outside_window_precedence_first_match(decision_time: int) -> None:
    decision = ref.evaluate_decision(
        decision_time_ms=ref.COMMON_WINDOW_END_MS + 1,
        funding_observations=_window_series(decision_time)[-10:],
        oi_now=None,
        oi_ref=None,
    )
    assert decision["reason"] == "OUTSIDE_COMMON_WINDOW"


@pytest.mark.unit
def test_forward_data_guard_suppresses_signal(decision_time: int) -> None:
    decision = ref.evaluate_decision(
        decision_time_ms=ref.COMMON_WINDOW_END_MS,
        funding_observations=_window_series(decision_time, current=0.01),
        oi_now=(ref.COMMON_WINDOW_END_MS, 3_000_000.0),
        oi_ref=(ref.COMMON_WINDOW_END_MS - 86_400_000, 2_000_000.0),
        exit_bar_open_time_ms=ref.COMMON_WINDOW_END_MS + 3_600_000,
        entry_bar_open_time_ms=ref.COMMON_WINDOW_END_MS + 3_600_000,
    )
    assert decision["result"] == ref.NO_SIGNAL
    assert "INSUFFICIENT_FORWARD_PRICE_DATA" in decision["all_reasons"]


@pytest.mark.unit
def test_entry_anchor_must_be_strictly_after_decision(decision_time: int) -> None:
    with pytest.raises(ValueError):
        ref.evaluate_decision(
            decision_time_ms=decision_time,
            funding_observations=_window_series(decision_time, current=0.01),
            oi_now=(decision_time, 3_000_000.0),
            oi_ref=(decision_time - 86_400_000, 2_000_000.0),
            entry_bar_open_time_ms=decision_time,
        )


# --------------------------------------------------------------------------
# PIT adversarial invariance
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_future_mutation_after_t_is_invisible(decision_time: int) -> None:
    series = _window_series(decision_time, current=0.01)
    baseline = ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=series, oi_now=(decision_time, 3_000_000.0), oi_ref=(decision_time - 86_400_000, 2_000_000.0))
    mutated = series + [(decision_time + 8 * 3_600_000, 99.0)]
    assert ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=mutated, oi_now=(decision_time, 3_000_000.0), oi_ref=(decision_time - 86_400_000, 2_000_000.0)) == baseline


@pytest.mark.unit
def test_past_eligible_mutation_changes_state(decision_time: int) -> None:
    series = _window_series(decision_time, current=0.01)
    baseline = ref.funding_extreme(series, decision_time)
    mutated = [(t, r + 0.0009 if t < decision_time else r) for t, r in series]
    assert ref.funding_extreme(mutated, decision_time)["z"] != baseline["z"]


@pytest.mark.unit
def test_information_and_cashflow_windows_are_disjoint(decision_time: int) -> None:
    series = _window_series(decision_time, current=0.01)
    info_max = max(t for t, _ in ref.funding_window(series, decision_time))
    entry_time = decision_time + 3_600_000
    assert info_max <= decision_time < entry_time
    assert ref.funding_cashflow_return(-1, [0.0001, 0.0001]) > 0
    assert ref.funding_cashflow_return(1, [0.0001, 0.0001]) < 0


@pytest.mark.unit
def test_null_control_direction_is_deterministic() -> None:
    a = ref.null_direction("ETHUSDT", 1_700_000_000_000)
    assert a == ref.null_direction("ETHUSDT", 1_700_000_000_000)
    assert a in (ref.LONG, ref.SHORT)


# --------------------------------------------------------------------------
# Validator (the programmatic completeness gate)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_validator_passes_all_gates() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/verify_arc01_prereg.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=300,
    )
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "PASS", [g for g in payload["gates"] if not g["ok"]]
    assert payload["ARC01_SPEC_COMPLETE"] == "PASS"
    assert payload["CONTRADICTIONS_FOUND"] == 0
    assert payload["FALSE_SUCCESS"] == 0
    assert payload["gates_failed"] == 0
    assert result.returncode == 0


@pytest.mark.unit
def test_validator_detects_missing_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The completeness gate must fail if any required economic field is dropped."""
    spec_path = PREREG_DIR / "ARC01_SPEC_V1.json"
    original = json.loads(spec_path.read_text(encoding="utf-8"))

    spec_mod = importlib.util.spec_from_file_location("verify_arc01_prereg", str(REPO / "scripts/verify_arc01_prereg.py"))
    assert spec_mod and spec_mod.loader
    module = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(module)

    broken = json.loads(json.dumps(original))
    del broken["exit"]["holding_period"]
    verifier = module.Verifier()
    module.check_spec_completeness(verifier, broken)
    gate = next(g for g in verifier.gates if g["gate"] == "ARC01_SPEC_COMPLETE")
    assert gate["ok"] is False
    assert "holding" in gate["detail"]

    verifier_ok = module.Verifier()
    module.check_spec_completeness(verifier_ok, original)
    assert next(g for g in verifier_ok.gates if g["gate"] == "ARC01_SPEC_COMPLETE")["ok"] is True


@pytest.mark.unit
def test_validator_detects_numeric_performance_value(tmp_path: Path) -> None:
    spec_mod = importlib.util.spec_from_file_location("verify_arc01_prereg_2", str(REPO / "scripts/verify_arc01_prereg.py"))
    assert spec_mod and spec_mod.loader
    module = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(module)

    violated = {"result": {"sharpe": 1.23}}
    found = module.walk_numeric_leaf_keys(violated)
    assert found and found[0][0] == "result.sharpe"
    assert module.walk_numeric_leaf_keys({"gates": [{"metric": "annualized net Sharpe", "requirement": ">= 0.50"}]}) == []


# --------------------------------------------------------------------------
# No real-data signal generation at prereg time
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_reference_module_is_pure_and_has_no_io() -> None:
    source = (REPO / "src" / "trading_bot" / "research" / "arc01" / "prereg_reference.py").read_text(encoding="utf-8")
    for forbidden in ("read_text", "json.load", "Path(", "pandas", "import numpy", "open(\"", "funding_reader"):
        assert forbidden not in source, f"reference module must stay pure: found {forbidden!r}"
