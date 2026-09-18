"""ARC-02 preregistration tests: structure, binding, precedence and the economic guard.

These tests never read an economic result. They assert that the frozen artifacts exist, are
internally consistent, agree with the implementation constants, and record zero economic
execution.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from trading_bot.research.arc02 import arc02_authority as A
from trading_bot.research.arc02.arc02_pit import run_battery

REPO = pathlib.Path(__file__).resolve().parents[3]
PREREG = REPO / "docs" / "arc02-prereg-01"
DATA = REPO / "docs" / "arc02-data-authority-01"

REQUIRED = [
    "ARC02_SPEC_V1.json", "ARC02_MANIFEST_V1.json", "ARC02_PREREGISTRATION.md",
    "ARC02_MECHANISM_AUTHORITY.md", "ARC02_SELECTION_RATIONALE.md", "ARC02_PIT_CONTRACT.json",
    "ARC02_CONTROL_PLAN.json", "ARC02_STATISTICAL_GATES.json", "ARC02_ROBUSTNESS_PLAN.json",
    "ARC02_FAILED_MEMORY_COLLISION_REVIEW.md", "ARC02_PREREG_VERIFICATION_PACKAGE.json",
    "ARC02_RESUME_STATE.json",
]


def load(name: str) -> dict:
    return json.loads((PREREG / name).read_text(encoding="utf-8"))


def load_data(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", REQUIRED)
def test_prereg_artifact_exists(name: str) -> None:
    assert (PREREG / name).exists()


def test_hypothesis_identity_is_consistent_across_artifacts() -> None:
    ids = {load(n)["hypothesis_id"] for n in ("ARC02_SPEC_V1.json", "ARC02_STATISTICAL_GATES.json", "ARC02_CONTROL_PLAN.json", "ARC02_PIT_CONTRACT.json", "ARC02_ROBUSTNESS_PLAN.json")}
    assert ids == {"ARC-02-BTC-ALT-LEAD-LAG-01"}
    assert load_data("ARC02_DATA_AUTHORITY.json")["hypothesis_id"] == "ARC-02-BTC-ALT-LEAD-LAG-01"


def test_economics_guard_is_zero() -> None:
    spec = load("ARC02_SPEC_V1.json")
    assert spec["economics"] == {"ARC02_BACKTESTS": 0, "ARC02_EXECUTIONS": 0, "ARC02_PERFORMANCE_OBSERVED": False, "FALSE_SUCCESS": 0}
    assert spec["status_at_prereg"] == "PREREGISTERED_NOT_EXECUTED"
    assert load("ARC02_MANIFEST_V1.json")["economics_guards_at_freeze"]["ARC02_EXECUTIONS"] == 0
    assert load_data("ARC02_DATA_INVENTORY.json")["economics"]["ARC02_BACKTESTS"] == 0


def test_no_forbidden_economic_key_anywhere_in_the_artifacts() -> None:
    forbidden = {"pnl", "net_pnl", "win_rate", "realized_return", "observed_returns", "best_threshold", "best_lookback", "best_asset"}
    for path in list(PREREG.glob("*.json")) + list(DATA.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        for key in forbidden:
            assert f'"{key}"' not in text, f"{key} leaked into {path.name}"


def test_spec_constants_equal_implementation_constants() -> None:
    spec = load("ARC02_SPEC_V1.json")
    assert spec["btc_shock"]["lookback"]["length_bars"] == A.SHOCK_LOOKBACK_BARS == 288
    assert spec["btc_shock"]["minimum_observations"] == A.SHOCK_MIN_OBS == 288
    assert spec["btc_shock"]["threshold"] == A.SHOCK_THRESHOLD == 3.0
    assert spec["follower_underreaction"]["underreaction_ratio"] == A.UNDERREACTION_RATIO == 0.5
    assert spec["exit"]["holding_period"]["holding_bars"] == A.HOLDING_BARS == 1
    assert spec["cost_model"]["PRIMARY_ROUND_TRIP_COST_BPS"] == A.PRIMARY_COST_BPS == 10
    assert spec["cost_model"]["cost_sensitivities_bps"] == list(A.COST_SCENARIOS_BPS) == [0, 10, 20, 40]
    assert spec["common_window"]["start_ms"] == 1600066800000
    assert spec["common_window"]["end_ms"] == 1788220500000
    assert spec["common_window"]["window_span_days"] == A.COMMON_WINDOW_SPAN_DAYS


def test_strict_inequalities_are_frozen() -> None:
    spec = load("ARC02_SPEC_V1.json")
    assert spec["btc_shock"]["inequality"].startswith("STRICT_GREATER_THAN")
    assert spec["follower_underreaction"]["inequality"].startswith("STRICT_LESS_THAN")
    assert A.SHOCK_INEQUALITY == "STRICT_GREATER_THAN"
    assert A.UNDERREACTION_INEQUALITY == "STRICT_LESS_THAN"


def test_no_signal_precedence_matches_code_and_is_total() -> None:
    spec = load("ARC02_SPEC_V1.json")
    assert spec["signal_rules"]["deterministic_no_signal_precedence"] == list(A.NO_SIGNAL_PRECEDENCE)
    assert A.NO_SIGNAL_PRECEDENCE[0] == "OUTSIDE_COMMON_WINDOW"
    assert A.NO_SIGNAL_PRECEDENCE[-1] == "INSUFFICIENT_FORWARD_PRICE_DATA"
    assert len(set(A.NO_SIGNAL_PRECEDENCE)) == len(A.NO_SIGNAL_PRECEDENCE)


def test_gates_are_complete_critical_and_convention_bound() -> None:
    gates = load("ARC02_STATISTICAL_GATES.json")
    ids = [g["id"] for g in gates["gates"]]
    assert len(ids) == 11 and all(g["critical"] is True for g in gates["gates"])
    assert any(i.startswith("G9_") for i in ids)
    g9 = next(g for g in gates["gates"] if g["id"].startswith("G9_"))
    assert "BOTH followers" in g9["threshold"]
    conv = gates["convention_bindings"]
    assert conv["sample_standard_deviation"]["ddof"] == 1
    assert conv["bootstrap"]["resamples_R"] == 10000 and conv["bootstrap"]["seed"] == 20260915
    assert conv["permutation"]["draws"] == 10000 and conv["permutation"]["threshold"] == "p_value <= 0.05"
    assert conv["concentration_attribution"]["thresholds"]["max_follower_share"] == 0.70


def test_four_controls_are_frozen_and_not_promotable() -> None:
    controls = load("ARC02_CONTROL_PLAN.json")
    ids = [c["id"] for c in controls["controls"]]
    assert set(ids) == {"DIRECTION_CONTROL", "TIMING_CONTROL", "LEADER_CONTROL", "NULL_CONTROL"}
    assert all(c["promotable"] is False and c["executable_definition"] for c in controls["controls"])
    assert controls["global_rules"]["controls_change_primary_trade_set"] is False
    assert controls["global_rules"]["controls_never_become_strategies"] is True
    null = next(c for c in controls["controls"] if c["id"] == "NULL_CONTROL")
    assert null["seed"] == 20260915 and "Python hash()" in null["no_python_hash"]


def test_leader_control_is_a_lagged_deterministic_substitution() -> None:
    controls = load("ARC02_CONTROL_PLAN.json")
    leader = next(c for c in controls["controls"] if c["id"] == "LEADER_CONTROL")
    assert str(A.LEADER_CONTROL_LAG_BARS) in json.dumps(leader)
    assert "unchanged" in leader and "deterministic" in leader["executable_definition"].lower()
    assert A.LEADER_CONTROL_LAG_BARS == A.SHOCK_LOOKBACK_BARS


def test_timing_control_offset_is_the_holding_period() -> None:
    assert A.TIMING_CONTROL_OFFSET_BARS == A.HOLDING_BARS == 1


def test_kill_rule_is_frozen() -> None:
    kill = load("ARC02_SPEC_V1.json")["kill_rule"]
    assert kill["ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY"] is True
    assert set(kill["future_variant_requires"]) == {"NEW_HYPOTHESIS_ID", "NEW_PREREGISTRATION"}
    assert "underreaction-ratio retune" in kill["forbidden_after_failure"]


def test_robustness_plan_is_frozen_and_unexecuted() -> None:
    plan = load("ARC02_ROBUSTNESS_PLAN.json")
    assert plan["executed_now"] is False
    assert plan["robustness_cannot_select_a_better_parameter_set"] is True
    assert any(a["id"] == "R10_WALK_FORWARD_OOS" for a in plan["analyses"])
    assert plan["analyses"][-1]["id"] == "R11_CONCENTRATION_ANALYSIS" or any(a["id"] == "R11_CONCENTRATION_ANALYSIS" for a in plan["analyses"])


def test_pit_battery_passes_and_contract_binds_it() -> None:
    battery = run_battery()
    assert all(c["pass"] for c in battery)
    contract = load("ARC02_PIT_CONTRACT.json")
    assert contract["status"] == "PASS" and len(contract["clauses"]) >= 15
    recorded = load_data("ARC02_PIT_INDEPENDENT_TESTS.json")
    assert recorded["result"] == "PASS" and recorded["checks_passed"] == recorded["checks_total"]


def test_data_authority_binding_matches_spec() -> None:
    spec = load("ARC02_SPEC_V1.json")["data_authority"]
    authority = load_data("ARC02_DATA_AUTHORITY.json")
    manifest = load_data("ARC02_DATA_MANIFEST.json")
    assert spec["dataset_sha256"] == authority["dataset_sha256"] == manifest["dataset_sha256"]
    assert spec["partition_sha256"] == authority["partition_sha256"] == manifest["partition_sha256"]
    assert spec["source_authority_dataset_sha256"] == authority["reuse"]["source_dataset_sha256"]
    assert authority["reuse"]["download_required"] is False


def test_determinism_and_mutation_evidence_recorded() -> None:
    assert load_data("ARC02_DATA_DETERMINISM.json")["A_B_DETERMINISM"] == "PASS"
    mutation = load_data("ARC02_MUTATION_SENSITIVITY.json")
    assert mutation["MUTATION_SENSITIVITY"] == "PASS"
    assert mutation["fingerprint_changed"] is True and mutation["canonical_authority_untouched"] is True


def test_manifest_freezes_every_economic_artifact() -> None:
    manifest = load("ARC02_MANIFEST_V1.json")
    frozen = manifest["frozen_economic_artifacts"]
    assert all(v["sha256"] for v in frozen.values())
    for required in ("docs/arc02-prereg-01/ARC02_SPEC_V1.json", "docs/arc02-prereg-01/ARC02_STATISTICAL_GATES.json", "src/trading_bot/research/arc02/arc02_authority.py"):
        assert required in frozen
    assert manifest["freeze_rules"]["no_economic_artifact_may_change_after_this_manifest"] is True


def test_collision_review_addresses_every_required_comparator() -> None:
    text = (PREREG / "ARC02_FAILED_MEMORY_COLLISION_REVIEW.md").read_text(encoding="utf-8")
    for comparator in ("H1", "H3", "H5", "H6", "ARC-01", "ARC-03"):
        assert comparator in text
    assert "MEDIUM" in text and "POST_HOC_LEAD_ONLY" in text
