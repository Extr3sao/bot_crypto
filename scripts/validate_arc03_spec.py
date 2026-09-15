#!/usr/bin/env python
"""ARC-03 preregistration spec completeness validator.

Fails if ANY economic field required by the frozen ARC-03 contract is missing, null, empty,
or left to a runtime default. This is the programmatic `ARC03_SPEC_COMPLETE` gate: the
preregistration cannot be committed while any economic decision is implicit.

Checks performed:

1. schema/identity/economics fields present and correctly typed.
2. every required economic path exists, is non-null, and is non-empty.
3. no economic parameter resolves to a "runtime default" marker.
4. the frozen NO_SIGNAL precedence is exactly the frozen tuple, in order.
5. the four critical economic relations hold:
     participation shock  -> strict greater-than
     excursion record     -> strict greater-than
     exhaustion threshold -> 0.5 with strict greater-than
     cost sensitives      -> [0, 10, 20, 40] with primary 10
6. gates G1..G11 present, each with a frozen threshold and critical=true.
7. controls: DIRECTION/TIMING/PARTICIPATION/NULL present with an executable definition.
8. the kill rule forbids retuning and requires a new hypothesis id.
9. the statistic bindings (ddof, annualization, bootstrap, permutation, splits,
   concentration) are all explicitly stated - no estimator may be inherited by default.
10. cross-artifact consistency: the spec's contract file references exist on disk and the
    window/authority constants match the data authority artifacts.

Usage:
    python scripts/validate_arc03_spec.py [--spec PATH] [--json]
Exit code 0 => SPEC_COMPLETE = PASS, 2 => SPEC_COMPLETE = FAIL.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
DEFAULT_SPEC = ROOT / "docs" / "arc03-prereg-01" / "ARC03_SPEC_V1.json"

NO_SIGNAL_PRECEDENCE = [
    "OUTSIDE_COMMON_WINDOW",
    "REFERENCE_HISTORY_INCOMPLETE",
    "NO_PARTICIPATION_SHOCK",
    "NO_EXCURSION_RECORD",
    "NO_EXHAUSTION",
    "POSITION_ALREADY_OPEN",
    "INSUFFICIENT_FORWARD_PRICE_DATA",
]

#: Every economic field that must be explicitly frozen. Dotted paths into the spec.
REQUIRED_PATHS: list[str] = [
    # identity / economics
    "schema",
    "spec_version",
    "hypothesis_id",
    "checkpoint",
    "status_at_prereg",
    "builder_verifier_separation.final_state",
    "economics.ARC03_BACKTESTS",
    "economics.ARC03_EXECUTIONS",
    "economics.ARC03_PERFORMANCE_OBSERVED",
    "economics.FALSE_SUCCESS",
    # market
    "market.venue",
    "market.segment",
    "market.instrument_type",
    "market.quote_currency",
    "market.assets",
    "market.asset_selection_rule",
    "market.funding_schedule",
    # data authority
    "data_authority.authority_commit",
    "data_authority.dataset_sha256",
    "data_authority.partition_sha256.BTCUSDT",
    "data_authority.partition_sha256.ETHUSDT",
    "data_authority.partition_sha256.SOLUSDT",
    "data_authority.normalized_root",
    "data_authority.reader",
    "data_authority.funding_authority.role",
    "data_authority.funding_authority.identity_proof",
    "data_authority.funding_authority.partition_sha256.BTCUSDT",
    "data_authority.unadmitted_fields_forbidden",
    # window
    "common_window.derivation",
    "common_window.start_ms",
    "common_window.end_ms",
    "common_window.bound_semantics",
    "common_window.no_observation_outside_window",
    # cadence
    "decision_cadence.cadence",
    "decision_cadence.decision_time_definition",
    "decision_cadence.eligible_participation_window",
    "decision_cadence.eligible_reference_window",
    "decision_cadence.runtime_defaults",
    # participation shock
    "participation_shock.name",
    "participation_shock.type",
    "participation_shock.field",
    "participation_shock.rationale",
    "participation_shock.lookback.type",
    "participation_shock.lookback.length_days",
    "participation_shock.lookback.reference_slots",
    "participation_shock.lookback.strictly_trailing",
    "participation_shock.minimum_observations",
    "participation_shock.threshold.type",
    "participation_shock.threshold.inequality",
    "participation_shock.threshold.explicit",
    "participation_shock.participation_shock_definition",
    "participation_shock.zero_scale_behavior",
    # reversal condition
    "reversal_condition.name",
    "reversal_condition.components",
    "reversal_condition.why_this_identifies_transient_and_not_informational_participation",
    "reversal_condition.excursion_record.definition",
    "reversal_condition.excursion_record.inequality",
    "reversal_condition.excursion_record.minimum_observations",
    "reversal_condition.exhaustion.body_definition",
    "reversal_condition.exhaustion.up_push_rejected",
    "reversal_condition.exhaustion.down_push_rejected",
    "reversal_condition.exhaustion.threshold",
    "reversal_condition.exhaustion.inequality",
    "reversal_condition.exhaustion.degenerate_behavior",
    "reversal_condition.exhaustion.direction_semantics",
    # price context
    "price_context.PRICE_CONTEXT",
    "price_context.required_price_features",
    "price_context.required_price_features_role",
    "price_context.justification",
    # signal rules
    "signal_rules.SHORT_RULE",
    "signal_rules.LONG_RULE",
    "signal_rules.NO_SIGNAL_RULE",
    "signal_rules.direction_semantics",
    "signal_rules.deterministic_no_signal_precedence",
    "signal_rules.reason_code_rule",
    "signal_rules.insufficient_history",
    "signal_rules.missing_data",
    "signal_rules.no_discretionary_interpretation",
    # entry / exit / holding
    "entry.anchor",
    "entry.definition",
    "entry.causality",
    "entry.fills",
    "entry.entry_bar_must_be_inside_window",
    "exit.anchor",
    "exit.definition",
    "exit.exit_is_unconditional",
    "exit.early_exit",
    "exit.signal_invalidation_exit",
    "exit.take_profit",
    "exit.stop_loss",
    "exit.insufficient_forward_price_data",
    "exit.holding_period.PRIMARY_HOLDING_PERIOD",
    "exit.holding_period.holding_bars",
    "exit.holding_period.holding_ms",
    "exit.holding_period.alternate_primary_horizons",
    "exit.holding_period.selection_basis",
    "exit.holding_period.crosses_funding_settlements",
    # position policies
    "position_policies.STOP",
    "position_policies.COOLDOWN",
    "position_policies.OVERLAPPING_SIGNAL_POLICY",
    "position_policies.SAME_ASSET_REENTRY_POLICY",
    "position_policies.MULTI_ASSET_SIMULTANEOUS_POLICY",
    "position_policies.position_sizing",
    "position_policies.no_runtime_defaults",
    # returns / costs
    "return_definition.gross_trade_return",
    "return_definition.funding_cashflow_return",
    "return_definition.cost_return",
    "return_definition.net_trade_return",
    "return_definition.net_trade_return_ex_funding",
    "return_definition.accounting_identity",
    "cost_model.PRIMARY_ROUND_TRIP_COST_BPS",
    "cost_model.cost_sensitivities_bps",
    "cost_model.frozen_before_discovery",
    "cost_model.same_trade_set_required",
    "cost_model.funding_cashflow_is_not_a_cost",
    # funding accounting
    "funding_cashflow_accounting.signal_use",
    "funding_cashflow_accounting.execution_use",
    "funding_cashflow_accounting.crosses_settlement",
    "funding_cashflow_accounting.cashflow_rule",
    "funding_cashflow_accounting.settlement_count_is_never_assumed",
    "funding_cashflow_accounting.sign_convention",
    "funding_cashflow_accounting.boundary_semantics",
    "funding_cashflow_accounting.notional_basis",
    "funding_cashflow_accounting.no_double_counting",
    "funding_cashflow_accounting.ex_funding_gate_independence",
    # pit / sample
    "pit_rules.contract_file",
    "pit_rules.status",
    "pit_rules.future_mutation_invariance",
    "pit_rules.conflicting_duplicates_fail_closed",
    "sample_rules.minimum_reference_observations",
    "sample_rules.minimum_trades_total",
    "sample_rules.minimum_trades_per_asset",
    "sample_rules.insufficient_sample_policy",
    "sample_rules.minimum_N_chosen_before_results",
    # controls / gates / robustness / orthogonality / kill
    "controls.control_plan_file",
    "controls.frozen",
    "controls.controls_cannot_be_promoted",
    "controls.control_passes_all_critical_gates_consequence",
    "statistical_gates.gates_file",
    "statistical_gates.frozen",
    "statistical_gates.all_conventions_explicitly_bound",
    "robustness_plan.plan_file",
    "robustness_plan.frozen",
    "robustness_plan.executed_now",
    "robustness_plan.primary_parameters_immutable",
    "robustness_plan.robustness_cannot_select_a_better_parameter_set",
    "orthogonality.comparators",
    "orthogonality.stage_ordering",
    "orthogonality.max_abs_daily_pnl_correlation",
    "orthogonality.max_trade_time_jaccard_overlap",
    "orthogonality.rule",
    "kill_rule.ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY",
    "kill_rule.on_critical_gate_failure",
    "kill_rule.forbidden_after_failure",
    "kill_rule.future_variant_requires",
    #
    "forbidden_until_discovery_authorized",
    "limitations",
]

REQUIRED_GATE_IDS = [
    "G1_SAMPLE",
    "G2_NET_EXPECTANCY",
    "G3_NET_EXPECTANCY_EX_FUNDING",
    "G4_PROFIT_FACTOR",
    "G5_SHARPE",
    "G6_BOOTSTRAP",
    "G7_PERMUTATION",
    "G8_TEMPORAL_STABILITY",
    "G9_ASSET_STABILITY",
    "G10_CONCENTRATION",
    "G11_COST_SENSITIVITY",
]

REQUIRED_CONTROL_IDS = ["DIRECTION_CONTROL", "TIMING_CONTROL", "PARTICIPATION_CONTROL", "NULL_CONTROL"]

#: Every estimator convention that must be explicitly stated (ARC-01 ambiguity must not recur).
REQUIRED_GATE_CONVENTION_PATHS = [
    "convention_bindings.sample_standard_deviation.ddof",
    "convention_bindings.sharpe.definition",
    "convention_bindings.sharpe.annualization_factor",
    "convention_bindings.sharpe.trades_per_year",
    "convention_bindings.sharpe.window_span_days",
    "convention_bindings.sharpe.zero_variance_behavior",
    "convention_bindings.bootstrap.statistic",
    "convention_bindings.bootstrap.resampling_unit",
    "convention_bindings.bootstrap.sampling",
    "convention_bindings.bootstrap.construction",
    "convention_bindings.bootstrap.resamples_R",
    "convention_bindings.bootstrap.seed",
    "convention_bindings.bootstrap.rng",
    "convention_bindings.bootstrap.confidence",
    "convention_bindings.bootstrap.confidence_interval_construction",
    "convention_bindings.bootstrap.gate_rule",
    "convention_bindings.bootstrap.degenerate_guard",
    "convention_bindings.permutation.null_hypothesis",
    "convention_bindings.permutation.transform",
    "convention_bindings.permutation.statistic",
    "convention_bindings.permutation.draws",
    "convention_bindings.permutation.seed",
    "convention_bindings.permutation.sidedness",
    "convention_bindings.permutation.p_value_formula",
    "convention_bindings.permutation.threshold",
    "convention_bindings.permutation.degenerate_guard",
    "convention_bindings.profit_factor.definition",
    "convention_bindings.profit_factor.zero_loss_behavior",
    "convention_bindings.temporal_split.ordering",
    "convention_bindings.temporal_split.half_boundaries",
    "convention_bindings.temporal_split.quartile_boundaries",
    "convention_bindings.temporal_split.halves_rule",
    "convention_bindings.temporal_split.quartiles_rule",
    "convention_bindings.concentration_attribution.denominator",
    "convention_bindings.concentration_attribution.denominator_le_zero_behavior",
    "convention_bindings.concentration_attribution.max_asset_share",
    "convention_bindings.concentration_attribution.max_calendar_month_share",
    "convention_bindings.concentration_attribution.max_single_trade_share",
    "convention_bindings.concentration_attribution.thresholds",
    "convention_bindings.aggregation",
]

RUNTIME_DEFAULT_MARKERS = ("runtime default", "to be determined", "TBD", "unspecified", "default at runtime")

MISSING = object()


def dig(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return MISSING
            cur = cur[part]
        else:
            return MISSING
    return cur


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    spec_path = pathlib.Path(args.spec)
    failures: list[dict] = []
    checks: list[str] = []

    if not spec_path.exists():
        print(json.dumps({"ARC03_SPEC_COMPLETE": "FAIL", "reason": f"spec not found: {spec_path}"}))
        return 2

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    checks.append("spec_parsed")

    # 1 + 2: required paths present, non-null, non-empty
    for path in REQUIRED_PATHS:
        value = dig(spec, path)
        if value is MISSING:
            failures.append({"check": "required_field_missing", "path": path})
        elif is_empty(value):
            failures.append({"check": "required_field_empty", "path": path})
    checks.append("required_fields_present")

    # 3: no runtime-default marker in an economic string
    for path in REQUIRED_PATHS:
        value = dig(spec, path)
        if isinstance(value, str):
            low = value.lower()
            for marker in RUNTIME_DEFAULT_MARKERS:
                if marker.lower() in low and "none" not in low:
                    failures.append({"check": "runtime_default_marker", "path": path, "value": value[:160]})
    checks.append("no_runtime_defaults")

    # 4: precedence exactly the frozen tuple
    prec = dig(spec, "signal_rules.deterministic_no_signal_precedence")
    if prec != NO_SIGNAL_PRECEDENCE:
        failures.append({"check": "no_signal_precedence_mismatch", "got": prec, "expected": NO_SIGNAL_PRECEDENCE})
    checks.append("no_signal_precedence")

    # 5: critical economic relations
    if "STRICT_GREATER_THAN" not in str(dig(spec, "participation_shock.threshold.inequality")):
        failures.append({"check": "participation_inequality_not_strict"})
    if "STRICT_GREATER_THAN" not in str(dig(spec, "reversal_condition.excursion_record.inequality")):
        failures.append({"check": "excursion_inequality_not_strict"})
    if dig(spec, "reversal_condition.exhaustion.threshold") != 0.5:
        failures.append({"check": "exhaustion_threshold_not_half"})
    if not str(dig(spec, "reversal_condition.exhaustion.inequality")).startswith("STRICT_GREATER_THAN"):
        failures.append({"check": "exhaustion_inequality_not_strict"})
    if dig(spec, "cost_model.cost_sensitivities_bps") != [0, 10, 20, 40]:
        failures.append({"check": "cost_scenarios_mismatch"})
    if dig(spec, "cost_model.PRIMARY_ROUND_TRIP_COST_BPS") != 10:
        failures.append({"check": "primary_cost_not_10bps"})
    if dig(spec, "sample_rules.minimum_reference_observations") != dig(spec, "participation_shock.minimum_observations"):
        failures.append({"check": "reference_observation_minimum_inconsistent"})
    if str(dig(spec, "price_context.PRICE_CONTEXT")) != "NONE":
        failures.append({"check": "price_context_not_none"})
    checks.append("critical_relations")

    # 6: gates
    gates_doc = ROOT / "docs" / "arc03-prereg-01" / "ARC03_STATISTICAL_GATES.json"
    if not gates_doc.exists():
        failures.append({"check": "gates_file_missing", "path": str(gates_doc)})
    else:
        gates = json.loads(gates_doc.read_text(encoding="utf-8"))
        by_id = {g["id"]: g for g in gates.get("gates", [])}
        for gid in REQUIRED_GATE_IDS:
            g = by_id.get(gid)
            if g is None:
                failures.append({"check": "gate_missing", "gate": gid})
                continue
            if g.get("threshold") in (None, ""):
                failures.append({"check": "gate_threshold_missing", "gate": gid})
            if g.get("critical") is not True:
                failures.append({"check": "gate_not_critical", "gate": gid})
        for path in REQUIRED_GATE_CONVENTION_PATHS:
            value = dig(gates, path)
            if value is MISSING or is_empty(value):
                failures.append({"check": "gate_convention_missing", "path": path})
        if gates.get("CRITICAL_SPEC_INCOMPLETENESS") is not False:
            failures.append({"check": "CRITICAL_SPEC_INCOMPLETENESS_not_false"})
        if gates.get("all_critical_gates_required_for_pass") is not True:
            failures.append({"check": "all_critical_gates_required_not_true"})
    checks.append("gates_complete")

    # 7: controls
    control_doc = ROOT / "docs" / "arc03-prereg-01" / "ARC03_CONTROL_PLAN.json"
    if not control_doc.exists():
        failures.append({"check": "control_plan_missing", "path": str(control_doc)})
    else:
        cp = json.loads(control_doc.read_text(encoding="utf-8"))
        ids = {c["id"] for c in cp.get("controls", [])}
        for cid in REQUIRED_CONTROL_IDS:
            if cid not in ids:
                failures.append({"check": "control_missing", "control": cid})
        for c in cp.get("controls", []):
            if is_empty(c.get("executable_definition")):
                failures.append({"check": "control_definition_missing", "control": c.get("id")})
            if c.get("promotable") is not False:
                failures.append({"check": "control_promotable", "control": c.get("id")})
        consequence = cp.get("global_rules", {}).get("if_any_required_control_satisfies_ALL_critical_gates", "")
        if "DISCOVERY_FAIL" not in str(consequence):
            failures.append({"check": "control_pass_consequence_undefined"})
        if cp.get("global_rules", {}).get("controls_change_primary_trade_set") is not False:
            failures.append({"check": "control_may_change_primary_trade_set"})
    checks.append("controls_complete")

    # 8: kill rule
    forbidden = " ".join(str(x) for x in (dig(spec, "kill_rule.forbidden_after_failure") or []))
    for token in ("retuning", "deletion"):
        if token not in forbidden:
            failures.append({"check": "kill_rule_forbidden_incomplete", "missing_token": token})
    if dig(spec, "kill_rule.future_variant_requires") != ["NEW_HYPOTHESIS_ID", "NEW_PREREGISTRATION"]:
        failures.append({"check": "kill_rule_variant_requirement_mismatch"})
    if dig(spec, "kill_rule.ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY") is not True:
        failures.append({"check": "one_prereg_one_discovery_not_true"})
    checks.append("kill_rule_frozen")

    # 9: statistic bindings
    covered = {p.split(".", 1)[1] for p in REQUIRED_GATE_CONVENTION_PATHS}
    for required in ("sharpe", "bootstrap", "permutation", "temporal_split", "concentration_attribution", "profit_factor"):
        if not any(c == required or c.startswith(required + ".") for c in covered):
            failures.append({"check": "statistic_binding_missing", "binding": required})
    checks.append("statistic_bindings")

    # 10: cross-artifact references exist + constants agree
    for rel in ("pit_rules.contract_file", "controls.control_plan_file", "statistical_gates.gates_file", "robustness_plan.plan_file"):
        rel_path = dig(spec, rel)
        if isinstance(rel_path, str) and not (ROOT / rel_path).exists():
            failures.append({"check": "referenced_contract_missing", "path": rel_path})
    auth = ROOT / "docs" / "arc03-data-authority-01" / "ARC03_DATA_AUTHORITY.json"
    window = ROOT / "docs" / "arc03-data-authority-01" / "ARC03_COMMON_CAUSAL_WINDOW.json"
    if auth.exists():
        a = json.loads(auth.read_text(encoding="utf-8"))
        if a.get("dataset_sha256") != dig(spec, "data_authority.dataset_sha256"):
            failures.append({"check": "dataset_fingerprint_mismatch_with_authority"})
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            if a.get("partition_sha256", {}).get(sym) != dig(spec, f"data_authority.partition_sha256.{sym}"):
                failures.append({"check": "partition_sha_mismatch_with_authority", "symbol": sym})
    else:
        failures.append({"check": "data_authority_missing", "path": str(auth)})
    if window.exists():
        w = json.loads(window.read_text(encoding="utf-8"))
        if w.get("start_ms") != dig(spec, "common_window.start_ms"):
            failures.append({"check": "window_start_mismatch"})
        if w.get("end_ms") != dig(spec, "common_window.end_ms"):
            failures.append({"check": "window_end_mismatch"})
    else:
        failures.append({"check": "common_window_artifact_missing", "path": str(window)})
    checks.append("cross_artifact_consistency")

    # 11: economics guard must be untouched at prereg
    if dig(spec, "economics.ARC03_BACKTESTS") != 0:
        failures.append({"check": "backtests_not_zero"})
    if dig(spec, "economics.ARC03_EXECUTIONS") != 0:
        failures.append({"check": "executions_not_zero"})
    if dig(spec, "economics.ARC03_PERFORMANCE_OBSERVED") is not False:
        failures.append({"check": "performance_observed_not_false"})
    if dig(spec, "economics.FALSE_SUCCESS") != 0:
        failures.append({"check": "false_success_not_zero"})
    checks.append("economics_guard")

    verdict = "PASS" if not failures else "FAIL"
    record = {
        "schema": "ARC03_SPEC_COMPLETENESS/1.0.0",
        "spec": str(spec_path.relative_to(ROOT)).replace("\\", "/"),
        "checks_executed": checks,
        "required_field_count": len(REQUIRED_PATHS),
        "required_gate_count": len(REQUIRED_GATE_IDS),
        "required_control_count": len(REQUIRED_CONTROL_IDS),
        "failures": failures,
        "failure_count": len(failures),
        "ARC03_SPEC_COMPLETE": verdict,
    }
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(f"ARC03_SPEC_COMPLETE = {verdict}  ({len(checks)} checks, {len(failures)} failures)")
        for f in failures:
            print(f"  FAIL {f}")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
