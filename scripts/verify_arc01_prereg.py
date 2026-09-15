"""ARC-01 preregistration validator (read-only, portable, deterministic).

Purpose (checkpoint ARC01-PREREG-001): fail closed if ANY economic field, binding,
PIT rule, control, gate, robustness-plan entry or immutability condition of the frozen
ARC-01 preregistration is missing, inconsistent or contradicted.

It performs NO economic computation: no returns, PnL, Sharpe, Sortino, profit factor,
expectancy or win rate is ever computed on real data. It recomputes only DATA HASHES
(binding), JSON structure, cross-artifact consistency, and executes the PURE decision
functions on IN-MEMORY synthetic fixtures to test the PIT contract adversarially.

Usage:
  python scripts/verify_arc01_prereg.py [--json] [--skip-hash-integrity]
  python scripts/verify_arc01_prereg.py --emit-hashes      # bootstrap: print artifact hashes

Exit code 0 iff every gate passes (ARC01_PREREG_VERIFICATION = PASS).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PREREG_DIR = REPO / "docs" / "arc01-prereg-01"

sys.path.insert(0, str(REPO / "src"))
from trading_bot.research.arc01 import prereg_reference as ref  # noqa: E402

# --------------------------------------------------------------------------
# Frozen bindings required by the ARC-01 mission (must be reproduced exactly)
# --------------------------------------------------------------------------
EXPECTED_AUTHORITY_COMMIT = "6e42dd9d4c19800925fd555999686d1e2b4ef47e"
EXPECTED_DATASET_SHA256 = "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"
EXPECTED_PARTITION_SHA256 = {
    "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
    "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
    "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
}
EXPECTED_COMMON_WINDOW = {"start_ms": 1_638_316_800_000, "end_ms": 1_789_081_200_000}
EXPECTED_COST_BPS = 10
EXPECTED_SENSITIVITIES = [0, 10, 20, 40]
EXPECTED_HOLDING_MS = 72 * 3_600_000
EXPECTED_FUNDING_THRESHOLD = {"positive": 2.0, "negative": -2.0}
EXPECTED_INCLUSIVE_THRESHOLD = True

ARTIFACT_FILES = {
    "spec": "ARC01_SPEC_V1.json",
    "pit_contract": "ARC01_PIT_CONTRACT.json",
    "control_plan": "ARC01_CONTROL_PLAN.json",
    "statistical_gates": "ARC01_STATISTICAL_GATES.json",
    "robustness_plan": "ARC01_ROBUSTNESS_PLAN.json",
    "manifest": "ARC01_MANIFEST_V1.json",
    "verification_package": "ARC01_PREREG_VERIFICATION_PACKAGE.json",
    "run_report_json": "RUN_REPORT.json",
}
MARKDOWN_FILES = {
    "preregistration": "ARC01_PREREGISTRATION.md",
    "mechanism_evidence": "ARC01_MECHANISM_EVIDENCE.md",
    "selection_rationale": "ARC01_SELECTION_RATIONALE.md",
    "failed_memory_collision_review": "ARC01_FAILED_MEMORY_COLLISION_REVIEW.md",
    "run_report_md": "RUN_REPORT.md",
}
FROZEN_CONTENT_ARTIFACTS = [
    "ARC01_SPEC_V1.json",
    "ARC01_PIT_CONTRACT.json",
    "ARC01_CONTROL_PLAN.json",
    "ARC01_STATISTICAL_GATES.json",
    "ARC01_ROBUSTNESS_PLAN.json",
    "ARC01_PREREGISTRATION.md",
    "ARC01_MECHANISM_EVIDENCE.md",
    "ARC01_SELECTION_RATIONALE.md",
    "ARC01_FAILED_MEMORY_COLLISION_REVIEW.md",
]

# Every economic field the mission requires to be EXPLICIT (no implicit value).
REQUIRED_SPEC_FIELDS: dict[str, list[str]] = {
    "hypothesis_id": ["hypothesis_id"],
    "assets": ["market.assets"],
    "market": ["market.venue", "market.segment", "market.instrument_type", "market.quote_currency"],
    "data_authority": [
        "data_authority.authority_commit",
        "data_authority.funding_authority.reader",
        "data_authority.oi_authority.reader",
        "data_authority.price_authority.row_format",
    ],
    "dataset_fingerprint": [
        "data_authority.dataset_sha256",
        "data_authority.partition_sha256",
        "data_authority.oi_authority.oi_full_history_dataset_sha256_v2",
        "data_authority.price_authority.price_authority_sha256_v2",
    ],
    "common_window": [
        "common_window.start_ms",
        "common_window.end_ms",
        "common_window.start_utc",
        "common_window.end_utc",
        "common_window.bound_semantics",
    ],
    "decision_cadence": [
        "decision_cadence.cadence",
        "decision_cadence.decision_time_definition",
        "decision_cadence.eligible_funding_observation",
        "decision_cadence.eligible_oi_window",
        "decision_cadence.eligible_price_window",
    ],
    "funding_transform": [
        "funding_transform.name",
        "funding_transform.type",
        "funding_transform.value_at_decision",
        "funding_transform.z_definition",
        "funding_transform.location_estimator",
        "funding_transform.scale_estimator",
        "funding_transform.mad_multiplier",
        "funding_transform.mad_zero_behavior",
    ],
    "funding_lookback": [
        "funding_transform.lookback.length_days",
        "funding_transform.lookback.interval",
        "funding_transform.lookback.strictly_trailing",
        "funding_transform.minimum_observations",
    ],
    "funding_threshold": [
        "funding_transform.threshold.positive",
        "funding_transform.threshold.negative",
        "funding_transform.threshold.inequality",
    ],
    "oi_transform": [
        "oi_transform.name",
        "oi_transform.type",
        "oi_transform.oi_now.definition",
        "oi_transform.oi_now.staleness_rule",
        "oi_transform.oi_reference.definition",
        "oi_transform.expansion_definition",
        "oi_transform.crowding_definition",
        "oi_transform.neutral_behavior",
        "oi_transform.contraction_behavior",
    ],
    "oi_lookback": [
        "oi_transform.lookback.length_hours",
        "oi_transform.lookback.length_ms",
        "oi_transform.minimum_observations",
    ],
    "oi_threshold": ["oi_transform.threshold.type", "oi_transform.threshold.value", "oi_transform.threshold.inequality"],
    "price_context": ["price_context.PRICE_CONTEXT", "price_context.justification"],
    "LONG": ["signal_rules.LONG_RULE"],
    "SHORT": ["signal_rules.SHORT_RULE"],
    "NO_SIGNAL": [
        "signal_rules.NO_SIGNAL_RULE",
        "signal_rules.deterministic_no_signal_precedence",
        "signal_rules.insufficient_history",
        "signal_rules.mad_zero",
        "signal_rules.conflicting_conditions",
        "signal_rules.stale_data",
        "signal_rules.missing_data",
    ],
    "entry": ["entry.anchor", "entry.definition", "entry.causality"],
    "exit": ["exit.anchor", "exit.definition", "exit.early_exit", "exit.signal_invalidation_exit"],
    "holding": ["exit.holding_period.PRIMARY_HOLDING_PERIOD", "exit.holding_period.holding_bars"],
    "stop": ["position_policies.STOP"],
    "cooldown": ["position_policies.COOLDOWN"],
    "overlap": [
        "position_policies.OVERLAPPING_SIGNAL_POLICY",
        "position_policies.SAME_ASSET_REENTRY_POLICY",
        "position_policies.MULTI_ASSET_SIMULTANEOUS_POLICY",
    ],
    "cost_model": [
        "cost_model.PRIMARY_ROUND_TRIP_COST_BPS",
        "cost_model.cost_sensitivities_bps",
        "cost_model.sensitivity_role",
    ],
    "funding_cashflow": [
        "funding_cashflow_accounting.signal_information_vs_execution_cashflow",
        "funding_cashflow_accounting.signal_use",
        "funding_cashflow_accounting.execution_use",
        "funding_cashflow_accounting.cashflow_rule",
        "funding_cashflow_accounting.sign_convention",
        "funding_cashflow_accounting.no_double_counting",
    ],
    "PIT": [
        "pit_rules.funding_time_le_decision_time",
        "pit_rules.funding_availability_time_le_decision_time",
        "pit_rules.oi_time_le_decision_time",
        "pit_rules.price_time_le_decision_time",
        "pit_rules.completed_windows_only",
        "pit_rules.contract_file",
    ],
    "sample_rules": [
        "sample_rules.minimum_funding_observations",
        "sample_rules.minimum_oi_observations",
        "sample_rules.minimum_trades_per_asset",
        "sample_rules.minimum_total_trades",
        "sample_rules.insufficient_sample_policy",
    ],
    "controls": ["controls.control_plan_file", "controls.frozen", "controls.controls_cannot_be_promoted"],
    "statistical_gates": ["statistical_gates.gates_file", "statistical_gates.frozen", "statistical_gates.no_single_metric_sufficient"],
    "robustness_gates": ["robustness_plan.plan_file", "robustness_plan.frozen", "robustness_plan.executed_now"],
    "orthogonality": [
        "orthogonality.comparators",
        "orthogonality.max_abs_daily_pnl_correlation",
        "orthogonality.max_trade_time_jaccard_overlap",
    ],
    "kill_rule": [
        "kill_rule.ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY",
        "kill_rule.on_critical_gate_failure",
        "kill_rule.forbidden_after_failure",
        "kill_rule.future_variant_requires",
    ],
}

REQUIRED_CONTROL_IDS = ("DIRECTION_CONTROL", "TIMING_CONTROL", "OI_CONTROL", "NULL_CONTROL")
REQUIRED_CRITICAL_GATE_IDS = (
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
)
REQUIRED_ROBUSTNESS_IDS = ("R1_TIME_SPLITS", "R2_ASSET_SPLITS", "R3_REGIME_SPLITS", "R4_COST_SENSITIVITY", "R5_PARAMETER_NEIGHBOURHOOD", "R6_CONCENTRATION", "R7_SIGNAL_COUNT_STABILITY")
FORBIDDEN_NUMERIC_METRIC_KEYS = {
    "pnl",
    "net_pnl",
    "gross_pnl",
    "sharpe",
    "net_sharpe",
    "sortino",
    "profit_factor",
    "profit_factor_net",
    "expectancy",
    "net_expectancy",
    "gross_expectancy",
    "win_rate",
    "max_drawdown",
    "returns",
    "cagr",
    "total_return",
    "sharpe_ci",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def walk_numeric_leaf_keys(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and str(k).lower() in FORBIDDEN_NUMERIC_METRIC_KEYS:
                found.append((here, v))
            else:
                found.extend(walk_numeric_leaf_keys(v, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(walk_numeric_leaf_keys(v, f"{path}[{i}]"))
    return found


class Verifier:
    def __init__(self) -> None:
        self.gates: list[dict[str, Any]] = []
        self.contradictions: list[str] = []

    def gate(self, name: str, ok: bool, detail: str = "") -> bool:
        self.gates.append({"gate": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def contradict(self, message: str) -> None:
        self.contradictions.append(message)


def load_artifacts(v: Verifier) -> tuple[dict[str, Any], dict[str, str]]:
    docs: dict[str, Any] = {}
    json_ok = True
    details: list[str] = []
    for key, fname in ARTIFACT_FILES.items():
        p = PREREG_DIR / fname
        if not p.exists():
            json_ok = False
            details.append(f"MISSING:{fname}")
            continue
        try:
            docs[key] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            json_ok = False
            details.append(f"INVALID_JSON:{fname}:{exc}")
    v.gate("json_validation", json_ok, "; ".join(details) or f"{len(docs)} JSON artifacts parsed")
    text_present = {k: (PREREG_DIR / f).exists() for k, f in MARKDOWN_FILES.items()}
    v.gate("markdown_artifacts_present", all(text_present.values()), json.dumps(text_present))
    return docs, {k: str(PREREG_DIR / f) for k, f in {**ARTIFACT_FILES, **MARKDOWN_FILES}.items()}


def check_spec_completeness(v: Verifier, spec: dict[str, Any]) -> None:
    missing: list[str] = []
    for field, paths in REQUIRED_SPEC_FIELDS.items():
        for dotted in paths:
            value = get_path(spec, dotted)
            if value is None or value == "" or value == [] or value == {}:
                missing.append(f"{field}:{dotted}")
    v.gate("ARC01_SPEC_COMPLETE", not missing, ("missing=" + ", ".join(missing)) if missing else f"{sum(len(p) for p in REQUIRED_SPEC_FIELDS.values())} required fields explicit")
    v.gate("economic_parameters_frozen", spec.get("status_at_prereg") == "PREREGISTERED_NOT_EXECUTED", f"status_at_prereg={spec.get('status_at_prereg')}")


def check_data_binding(v: Verifier, spec: dict[str, Any]) -> None:
    da = spec.get("data_authority", {})
    ok = True
    details: list[str] = []
    if da.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        ok = False
        details.append(f"authority_commit={da.get('authority_commit')}")
    if da.get("dataset_sha256") != EXPECTED_DATASET_SHA256:
        ok = False
        details.append(f"dataset_sha256={da.get('dataset_sha256')}")
    parts = da.get("partition_sha256", {}) or {}
    for sym, expected in EXPECTED_PARTITION_SHA256.items():
        if parts.get(sym) != expected:
            ok = False
            details.append(f"partition[{sym}] mismatch")
    v.gate("DATA_AUTHORITY_BINDING", ok, "; ".join(details) or "authority commit + dataset + 3 partition SHAs bound exactly")

    # Recompute funding partition hashes from disk when the data is present (binding, not authority adjudication).
    data_dir = REPO / "data" / "processed" / "arc01_funding"
    recomputed: dict[str, str] = {}
    hash_ok = True
    for sym, expected in EXPECTED_PARTITION_SHA256.items():
        p = data_dir / f"{sym}_funding.jsonl"
        if p.exists():
            actual = sha256_file(p)
            recomputed[sym] = actual
            if actual != expected:
                hash_ok = False
        else:
            recomputed[sym] = "NOT_PRESENT_LOCALLY"
    if recomputed and all(value != "NOT_PRESENT_LOCALLY" for value in recomputed.values()):
        v.gate("funding_partition_sha_recomputed", hash_ok, json.dumps(recomputed))
    else:
        v.gate("funding_partition_sha_recomputed", True, "SKIPPED (partitions not present in this tree; binding remains record-level)")

    # Bind the reused OI/price authority digests to their committed manifests (records, not re-derivation).
    fingerprint_doc = REPO / "docs" / "arc01-data-authority-01" / "ARC01_DATASET_FINGERPRINT.json"
    if fingerprint_doc.exists():
        fp = json.loads(fingerprint_doc.read_text(encoding="utf-8"))
        same = fp.get("dataset_sha256") == EXPECTED_DATASET_SHA256 and fp.get("partition_sha256") == EXPECTED_PARTITION_SHA256
        v.gate("dataset_fingerprint_matches_certified_record", same, "docs/arc01-data-authority-01/ARC01_DATASET_FINGERPRINT.json")
    else:
        v.gate("dataset_fingerprint_matches_certified_record", True, "SKIPPED (certified fingerprint artifact not in this tree)")

    oi_manifest = REPO / "docs" / "external-audit-01" / "oi-full-history-02" / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    if oi_manifest.exists():
        oi = json.loads(oi_manifest.read_text(encoding="utf-8"))
        declared = oi.get("dataset_sha256") or oi.get("OI_FULL_HISTORY_DATASET_SHA256_V2")
        binds = declared == da.get("oi_authority", {}).get("oi_full_history_dataset_sha256_v2")
        v.gate("oi_authority_binding", binds, f"declared={declared}")
    else:
        v.gate("oi_authority_binding", True, "SKIPPED (OI manifest not in this tree)")

    price_manifest = REPO / "docs" / "external-audit-01" / "oi-full-history-02" / "PRICE_1H_AUTHORITY_V2_MANIFEST.json"
    if price_manifest.exists():
        pm = json.loads(price_manifest.read_text(encoding="utf-8"))
        declared_price = pm.get("price_authority_sha256") or pm.get("PRICE_AUTHORITY_SHA256_V2") or pm.get("summary", {}).get("price_authority_sha256_v2")
        binds = declared_price == da.get("price_authority", {}).get("price_authority_sha256_v2")
        v.gate("price_authority_binding", binds, f"declared={declared_price}")
    else:
        v.gate("price_authority_binding", True, "SKIPPED (price manifest not in this tree)")


def check_pit_contract(v: Verifier, docs: dict[str, Any]) -> None:
    pit = docs.get("pit_contract", {})
    inv = pit.get("invariants", {})
    required = [
        "funding_time_le_decision_time",
        "funding_availability_time_le_decision_time",
        "oi_time_le_decision_time",
        "price_time_le_decision_time",
        "completed_windows_only",
        "future_mutation_invariance",
        "past_eligible_mutation_detection",
        "archive_completeness_non_retroactivity",
        "no_conflicting_duplicate",
        "stale_data_policy",
        "missing_data_policy",
    ]
    missing = [k for k in required if k not in inv]
    v.gate("PIT_CONTRACT", not missing and pit.get("status") == "PASS", f"missing={missing} status={pit.get('status')}")
    spec = docs.get("spec", {})
    v.gate(
        "PIT_INVARIANTS_FROZEN_IN_SPEC",
        all(bool(get_path(spec, f"pit_rules.{k}")) for k in (
            "funding_time_le_decision_time",
            "funding_availability_time_le_decision_time",
            "oi_time_le_decision_time",
            "price_time_le_decision_time",
            "completed_windows_only",
        )),
        "spec.pit_rules",
    )


def check_controls(v: Verifier, docs: dict[str, Any]) -> None:
    controls = docs.get("control_plan", {})
    ids = {c.get("id") for c in controls.get("controls", [])}
    missing = [c for c in REQUIRED_CONTROL_IDS if c not in ids]
    ok = not missing
    for control in controls.get("controls", []):
        for key in ("id", "definition", "falsification_target", "required_outcome"):
            if not control.get(key):
                ok = False
                missing.append(f"{control.get('id')}:{key}")
    v.gate("CONTROL_PLAN", ok, ("missing=" + ", ".join(missing)) if missing else f"4 controls frozen: {sorted(ids)}")
    v.gate("CONTROLS_NOT_PROMOTABLE", bool(controls.get("controls_cannot_be_promoted")) and bool(controls.get("controls_are_not_alternate_strategies")), "")


def check_statistical_gates(v: Verifier, docs: dict[str, Any]) -> None:
    gates = docs.get("statistical_gates", {})
    ids = {g.get("id") for g in gates.get("critical_gates", [])}
    missing = [g for g in REQUIRED_CRITICAL_GATE_IDS if g not in ids]
    ok = not missing and gates.get("no_single_metric_sufficient") is True
    for g in gates.get("critical_gates", []):
        if not g.get("metric") or not g.get("requirement"):
            ok = False
            missing.append(f"{g.get('id')}:incomplete")
    scenarios = [s.get("cost_bps_round_trip") for s in gates.get("frozen_evaluation_scenarios", [])]
    if scenarios != EXPECTED_SENSITIVITIES:
        ok = False
        missing.append(f"scenarios={scenarios}")
    if gates.get("primary_cost_bps") != EXPECTED_COST_BPS:
        ok = False
        missing.append("primary_cost_bps")
    v.gate("STATISTICAL_GATES", ok and not missing, ("missing=" + ", ".join(missing)) if missing else "11 critical gates + 4 frozen cost scenarios")


def check_robustness(v: Verifier, docs: dict[str, Any]) -> None:
    plan = docs.get("robustness_plan", {})
    ids = {r.get("id") for r in plan.get("robustness_analyses", [])}
    missing = [r for r in REQUIRED_ROBUSTNESS_IDS if r not in ids]
    ok = not missing and plan.get("executed_now") is False and bool(plan.get("primary_parameters_immutable"))
    v.gate("ROBUSTNESS_PLAN", ok, ("missing=" + ", ".join(missing)) if missing else "R1..R7 frozen, not executed")


def check_no_economic_observation(v: Verifier, docs: dict[str, Any]) -> None:
    spec = docs.get("spec", {})
    econ = spec.get("economics", {})
    ok = (
        econ.get("ARC01_BACKTESTS") == 0
        and econ.get("ARC01_EXECUTIONS") == 0
        and econ.get("ARC01_PERFORMANCE_OBSERVED") is False
        and econ.get("FALSE_SUCCESS") == 0
    )
    v.gate("NO_ECONOMIC_OBSERVATION", ok, json.dumps(econ))

    violations: list[str] = []
    for key, doc in docs.items():
        for path, value in walk_numeric_leaf_keys(doc):
            violations.append(f"{key}:{path}={value}")
    v.gate("FORBIDDEN_ECONOMIC_VALUES_ABSENT", not violations, ", ".join(violations) if violations else "no numeric performance metric recorded in any artifact")

    run_report = docs.get("run_report_json", {})
    rr_econ = run_report.get("economics", {})
    v.gate(
        "RUN_REPORT_ECONOMICS_CONSISTENT",
        rr_econ.get("ARC01_BACKTESTS") == 0
        and rr_econ.get("ARC01_EXECUTIONS") == 0
        and rr_econ.get("ARC01_PERFORMANCE_OBSERVED") is False,
        json.dumps(rr_econ),
    )


def check_cross_artifact_consistency(v: Verifier, docs: dict[str, Any]) -> None:
    spec = docs.get("spec", {})
    cw = spec.get("common_window", {})
    if cw.get("start_ms") != EXPECTED_COMMON_WINDOW["start_ms"] or cw.get("end_ms") != EXPECTED_COMMON_WINDOW["end_ms"]:
        v.contradict(f"common_window mismatch: {cw.get('start_ms')}..{cw.get('end_ms')}")
    if ref.COMMON_WINDOW_START_MS != EXPECTED_COMMON_WINDOW["start_ms"] or ref.COMMON_WINDOW_END_MS != EXPECTED_COMMON_WINDOW["end_ms"]:
        v.contradict("spec vs implementation common window disagreement")

    thr = spec.get("funding_transform", {}).get("threshold", {})
    if thr.get("positive") != EXPECTED_FUNDING_THRESHOLD["positive"] or thr.get("negative") != EXPECTED_FUNDING_THRESHOLD["negative"]:
        v.contradict(f"funding threshold mismatch: {thr}")
    if ref.FUNDING_Z_POSITIVE_THRESHOLD != EXPECTED_FUNDING_THRESHOLD["positive"] or ref.FUNDING_Z_NEGATIVE_THRESHOLD != EXPECTED_FUNDING_THRESHOLD["negative"]:
        v.contradict("spec vs implementation funding threshold disagreement")

    if spec.get("cost_model", {}).get("PRIMARY_ROUND_TRIP_COST_BPS") != EXPECTED_COST_BPS:
        v.contradict("primary cost mismatch")
    if spec.get("cost_model", {}).get("cost_sensitivities_bps") != EXPECTED_SENSITIVITIES:
        v.contradict("cost sensitivity scenario mismatch")

    if ref.HOLDING_MS != EXPECTED_HOLDING_MS:
        v.contradict("implementation holding period mismatch")
    if "72" not in str(spec.get("exit", {}).get("holding_period", {}).get("PRIMARY_HOLDING_PERIOD", "")):
        v.contradict("spec holding period is not the frozen 72h")
    if spec.get("exit", {}).get("holding_period", {}).get("holding_bars") != 72:
        v.contradict("spec holding_bars != 72")

    cash = spec.get("funding_cashflow_accounting", {})
    if cash.get("crosses_settlement") != "YES - the frozen 72h holding period necessarily crosses at least 9 provider settlements" and "YES" not in str(cash.get("crosses_settlement", "")):
        v.contradict("funding cashflow does not declare settlement crossing for a 72h hold")
    if cash.get("no_double_counting") is not True:
        v.contradict("no_double_counting not asserted")

    if spec.get("price_context", {}).get("PRICE_CONTEXT") not in ("NONE",):
        # PRICE_CONTEXT may only be a frozen explicit decision; if not NONE the required features must be enumerated.
        if not spec.get("price_context", {}).get("required_price_features"):
            v.contradict("price context not frozen explicitly")

    if spec.get("position_policies", {}).get("STOP") is None or spec.get("position_policies", {}).get("COOLDOWN") is None:
        v.contradict("STOP/COOLDOWN not explicit (runtime default risk)")

    sample = spec.get("sample_rules", {})
    gates = docs.get("statistical_gates", {})
    g1 = next((g for g in gates.get("critical_gates", []) if g.get("id") == "G1_SAMPLE"), {})
    requirement = str(g1.get("requirement", ""))
    if f"{sample.get('minimum_total_trades')}" not in requirement or f"{sample.get('minimum_trades_per_asset')}" not in requirement:
        v.contradict(f"sample rules vs G1_SAMPLE disagreement: {requirement}")

    pit_gate = next((g for g in gates.get("critical_gates", []) if g.get("id") == "G3_NET_EXPECTANCY_EX_FUNDING"), None)
    if pit_gate is None:
        v.contradict("ex-funding expectancy gate missing while funding cashflow is applied")

    v.gate("CONTRADICTIONS_FOUND", not v.contradictions, ("; ".join(v.contradictions)) if v.contradictions else "0 contradictions across spec/PIT/controls/gates/robustness/implementation")


def check_adversarial_pit(v: Verifier) -> None:
    """Adversarial PIT + rule-semantics tests on IN-MEMORY synthetic fixtures (no dataset, no returns)."""
    step = 8 * 3_600_000
    decision_time = 1_700_000_000_000 - (1_700_000_000_000 % step) + step * 40  # settled instant well inside window
    n = 183
    base = [(decision_time - (n - 1 - i) * step, 0.0001 + 0.0001 * (i % 3)) for i in range(n)]
    oi_now = (decision_time, 3_000_000.0)
    oi_ref = (decision_time - 86_400_000, 2_000_000.0)

    # 1. Non-vacuous baseline: the same inputs must give the same state.
    first = ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=base, oi_now=oi_now, oi_ref=oi_ref)
    second = ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=base, oi_now=oi_now, oi_ref=oi_ref)
    non_vacuous = first == second and first["z_funding"] is not None
    v.gate("PIT_BASELINE_NON_VACUOUS", non_vacuous, f"z={first['z_funding']} status={first['funding_status']}")

    # 2. Future mutation (strictly after T) must not change the decision state at T.
    mutated_future = base + [(decision_time + step, 99.0), (decision_time + 2 * step, -99.0)]
    after_future = ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=mutated_future, oi_now=oi_now, oi_ref=oi_ref)
    v.gate("PIT_FUTURE_MUTATION_AFTER_T", after_future == first, "state at T is byte-identical under post-T funding mutation")

    # 3. Past eligible mutation must CHANGE the decision state at T (detectability).
    mutated_past = [(t, (r + 0.0009 if t < decision_time else r)) for (t, r) in base]
    after_past = ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=mutated_past, oi_now=oi_now, oi_ref=oi_ref)
    v.gate("PIT_PAST_ELIGIBLE_MUTATION_DETECTED", after_past["z_funding"] != first["z_funding"], "past-window mutation changes FEATURE_STATE_AT_T")

    # 4. Inclusive threshold semantics (exact, no float derivation).
    boundary_ok = (
        ref.decide_direction(2.0) == ref.SHORT
        and ref.decide_direction(-2.0) == ref.LONG
        and ref.decide_direction(1.9999999999999998) is None
        and ref.decide_direction(-1.9999999999999998) is None
    )
    v.gate("THRESHOLD_BOUNDARY_INCLUSIVE", boundary_ok, "z >= +2.0 -> SHORT, z <= -2.0 -> LONG, inclusive")

    # 5. MAD == 0 fallback and degenerate scale fail-closed.
    flat = [(decision_time - (n - 1 - i) * step, 0.0001) for i in range(n)]
    flat_state = ref.funding_extreme(flat, decision_time)
    v.gate("MAD_ZERO_FAILS_CLOSED", flat_state["status"] == "SCALE_NONPOSITIVE", f"status={flat_state['status']}")

    mad_zero_levels = flat[:-1] + [(decision_time, 0.0101)]
    mixed = ref.funding_extreme(mad_zero_levels, decision_time)
    v.gate(
        "MAD_ZERO_STDEV_FALLBACK",
        mixed["status"] == "OK" and mixed.get("mad_fallback_used") is True and float(mixed["z"]) > 2.0,  # type: ignore[arg-type]
        f"status={mixed['status']} scale_estimator={mixed['scale_estimator']}",
    )

    # 6. Insufficient funding history fails closed.
    short_hist = base[-10:]
    v.gate("INSUFFICIENT_FUNDING_HISTORY_FAILS_CLOSED", ref.funding_extreme(short_hist, decision_time)["status"] == "INSUFFICIENT_FUNDING_HISTORY", "")

    # 7. OI rules: strict expansion, neutral and contraction fail closed, staleness fails closed.
    expansion = ref.oi_change_24h(oi_now, oi_ref, decision_time)
    neutral = ref.oi_change_24h((decision_time, 2_000_000.0), oi_ref, decision_time)["oi_change_24h"]
    contraction = ref.oi_change_24h((decision_time, 1_500_000.0), oi_ref, decision_time)["oi_change_24h"]
    stale = ref.oi_change_24h((decision_time - 901_000, 3_000_000.0), oi_ref, decision_time)["status"]
    bad_ref = ref.oi_change_24h(oi_now, (decision_time - 86_400_000, 0.0), decision_time)["status"]
    v.gate(
        "OI_CONFIRMATION_SEMANTICS",
        float(expansion["oi_change_24h"]) > 0  # type: ignore[arg-type]
        and neutral == 0.0
        and float(contraction) < 0  # type: ignore[arg-type]
        and stale == "OI_MISSING_OR_STALE"
        and bad_ref == "OI_REFERENCE_INVALID",
        f"expansion={expansion['oi_change_24h']} neutral={neutral} contraction={contraction} stale={stale} bad_ref={bad_ref}",
    )

    # 8. NO_SIGNAL precedence is deterministic and first-match.
    precedence_state = ref.evaluate_decision(
        decision_time_ms=EXPECTED_COMMON_WINDOW["end_ms"] + 1,
        funding_observations=short_hist,
        oi_now=None,
        oi_ref=None,
    )
    v.gate(
        "NO_SIGNAL_PRECEDENCE_FIRST_MATCH",
        precedence_state["result"] == ref.NO_SIGNAL and precedence_state["reason"] == "OUTSIDE_COMMON_WINDOW",
        f"reason={precedence_state['reason']}",
    )
    v.gate(
        "PIT_ENTRY_STRICTLY_AFTER_DECISION",
        _expect_raises(lambda: ref.evaluate_decision(decision_time_ms=decision_time, funding_observations=base, oi_now=oi_now, oi_ref=oi_ref, entry_bar_open_time_ms=decision_time)),
        "entry anchor at or before decision_time is rejected",
    )

    # 9. Forward-data guard: an exit beyond the window end suppresses the signal.
    late = ref.evaluate_decision(
        decision_time_ms=ref.COMMON_WINDOW_END_MS,
        funding_observations=base,
        oi_now=(ref.COMMON_WINDOW_END_MS, 3_000_000.0),
        oi_ref=(ref.COMMON_WINDOW_END_MS - 86_400_000, 2_000_000.0),
        exit_bar_open_time_ms=ref.COMMON_WINDOW_END_MS + 3_600_000,
        entry_bar_open_time_ms=ref.COMMON_WINDOW_END_MS + 3_600_000,
    )
    v.gate(
        "FORWARD_DATA_GUARD",
        late["result"] == ref.NO_SIGNAL and "INSUFFICIENT_FORWARD_PRICE_DATA" in late["all_reasons"],
        f"reasons={late['all_reasons']}",
    )

    # 10. Funding cashflow: sign convention and window disjointness (no double counting).
    short_receives = ref.funding_cashflow_return(-1, [0.0001, 0.0001])
    long_pays = ref.funding_cashflow_return(1, [0.0001, 0.0001])
    info_max = max(t for t, _ in ref.funding_window(base, decision_time))
    cash_min = decision_time + 3_600_000  # first possible settlement strictly after a 1h-later entry
    v.gate(
        "FUNDING_CASHFLOW_SIGN_AND_DISJOINT",
        short_receives > 0 and long_pays < 0 and info_max <= decision_time < cash_min,
        f"short={short_receives} long={long_pays} info_max={info_max} cash_min={cash_min}",
    )

    # 11. Null control determinism.
    n1 = ref.null_direction("BTCUSDT", decision_time)
    n2 = ref.null_direction("BTCUSDT", decision_time)
    n3 = ref.null_direction("BTCUSDT", decision_time + 1)
    v.gate("NULL_CONTROL_DETERMINISTIC", n1 == n2 and n1 in (ref.LONG, ref.SHORT) and n3 in (ref.LONG, ref.SHORT), f"{n1}/{n2}/{n3}")


def _expect_raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:  # pragma: no cover - defensive
        return False
    return False


def check_hash_integrity(v: Verifier, docs: dict[str, Any]) -> None:
    manifest = docs.get("manifest", {})
    package = docs.get("verification_package", {})
    declared = manifest.get("artifact_sha256", {}) or {}
    mismatches: list[str] = []
    for fname in FROZEN_CONTENT_ARTIFACTS:
        p = PREREG_DIR / fname
        if not p.exists():
            mismatches.append(f"MISSING:{fname}")
            continue
        actual = sha256_file(p)
        if declared.get(fname) != actual:
            mismatches.append(f"{fname}: declared={declared.get(fname)} actual={actual}")
    v.gate("MANIFEST_ARTIFACT_INTEGRITY", not mismatches, ("; ".join(mismatches)) if mismatches else f"{len(FROZEN_CONTENT_ARTIFACTS)} artifacts hash-matched")
    v.gate("POST_FREEZE_ARTIFACT_DRIFT", not mismatches, "0 drift between frozen artifacts and manifest commitments")

    pkg_declared = package.get("artifact_sha256", {}) or {}
    pkg_mismatch: list[str] = []
    for fname in FROZEN_CONTENT_ARTIFACTS + ["ARC01_MANIFEST_V1.json", "RUN_REPORT.json", "RUN_REPORT.md"]:
        p = PREREG_DIR / fname
        if not p.exists():
            pkg_mismatch.append(f"MISSING:{fname}")
            continue
        actual = sha256_file(p)
        if pkg_declared.get(fname) != actual:
            pkg_mismatch.append(f"{fname}")
    for rel in ("scripts/verify_arc01_prereg.py", "src/trading_bot/research/arc01/prereg_reference.py", "tests/unit/research/test_arc01_preregistration.py"):
        p = REPO / rel
        if p.exists() and package.get("tooling_sha256", {}).get(rel) != sha256_file(p):
            pkg_mismatch.append(rel)
    v.gate("VERIFICATION_PACKAGE_INTEGRITY", not pkg_mismatch, ("; ".join(pkg_mismatch)) if pkg_mismatch else "package commitments match working tree")

    manifest_self_hash = manifest.get("manifest_self_hash_recorded", manifest.get("pointer_semantics", {}).get("manifest_self_hash_recorded"))
    if manifest_self_hash is not False:
        v.contradict("manifest must not attempt to record its own hash (self-reference)")
    no_circular = (
        manifest_self_hash is False
        and package.get("self_hash_recorded") is False
        and manifest.get("prereg_commit") is None
        and manifest.get("pointer_semantics", {}).get("report_commit", "MISSING") is None
    )
    v.gate("NO_CIRCULAR_SELF_REFERENCE", bool(no_circular), "authority_commit / generated_from_commit / report_commit=null semantics respected")


def emit_hashes() -> dict[str, Any]:
    out: dict[str, Any] = {"frozen_artifacts": {}, "package_artifacts": {}, "tooling": {}}
    for fname in FROZEN_CONTENT_ARTIFACTS:
        p = PREREG_DIR / fname
        if p.exists():
            out["frozen_artifacts"][fname] = sha256_file(p)
    for fname in FROZEN_CONTENT_ARTIFACTS + ["ARC01_MANIFEST_V1.json", "RUN_REPORT.json", "RUN_REPORT.md"]:
        p = PREREG_DIR / fname
        if p.exists():
            out["package_artifacts"][fname] = sha256_file(p)
    for rel in ("scripts/verify_arc01_prereg.py", "src/trading_bot/research/arc01/prereg_reference.py", "tests/unit/research/test_arc01_preregistration.py"):
        p = REPO / rel
        if p.exists():
            out["tooling"][rel] = sha256_file(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ARC-01 preregistration validator")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--skip-hash-integrity", action="store_true", help="bootstrap phase: skip manifest/package hash gates")
    ap.add_argument("--emit-hashes", action="store_true", help="print artifact hashes for manifest bootstrap and exit")
    args = ap.parse_args(argv)

    if args.emit_hashes:
        print(json.dumps(emit_hashes(), indent=2, sort_keys=True))
        return 0

    v = Verifier()
    docs, _ = load_artifacts(v)
    if "spec" in docs:
        check_spec_completeness(v, docs["spec"])
        check_data_binding(v, docs["spec"])
        check_no_economic_observation(v, docs)
    else:
        v.gate("ARC01_SPEC_COMPLETE", False, "spec artifact missing")
    check_pit_contract(v, docs)
    check_controls(v, docs)
    check_statistical_gates(v, docs)
    check_robustness(v, docs)
    check_cross_artifact_consistency(v, docs)
    check_adversarial_pit(v)
    if not args.skip_hash_integrity:
        check_hash_integrity(v, docs)

    failed = [g for g in v.gates if not g["ok"]]
    result = {
        "checkpoint": "ARC01-PREREG-001",
        "verifier": "scripts/verify_arc01_prereg.py",
        "verifier_role": "BUILDER_CROSSCHECK (NOT independent verification)",
        "ARC01_SPEC_COMPLETE": "PASS" if all(g["ok"] for g in v.gates if g["gate"] == "ARC01_SPEC_COMPLETE") else "FAIL",
        "gates": v.gates,
        "gates_total": len(v.gates),
        "gates_failed": len(failed),
        "CONTRADICTIONS_FOUND": len(v.contradictions),
        "FALSE_SUCCESS": 0 if not failed else 1,
        "verdict": "PASS" if not failed else "FAIL",
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for g in v.gates:
            print(f"[{'PASS' if g['ok'] else 'FAIL'}] {g['gate']}" + (f" — {g['detail']}" if g["detail"] else ""))
        print(f"\nARC01_SPEC_COMPLETE={result['ARC01_SPEC_COMPLETE']} gates={result['gates_total']} failed={result['gates_failed']} CONTRADICTIONS_FOUND={result['CONTRADICTIONS_FOUND']} verdict={result['verdict']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
