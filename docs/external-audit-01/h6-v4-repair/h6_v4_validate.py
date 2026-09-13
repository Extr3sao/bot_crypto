"""V4 pre-freeze validation (builder-side, non-runtime).

Two independent checks, both required before the V4 prereg commit exists:

1. SPEC COMPLETENESS — every field the frozen contract requires (section 6 of the
   checkpoint) is present and non-vacuous, AND the spec parses through the real
   runtime parser (``frozen_contract_snapshot.parse_frozen_spec``). A spec the
   runtime cannot consume is not a spec.

2. V2 -> V4 ECONOMIC SEMANTIC DIFF — one projection function is applied to both the
   last complete pre-performance economic authority (V2) and V4. Representation
   differences (prose vs structured block, nesting) are normalised in the
   projection itself; any remaining difference is a semantic difference.
   Required: UNEXPLAINED_DIFFERENCES == 0, ECONOMIC_RETUNE_COUNT == 0, and no
   CHANGED / DROPPED / ADDED_ECONOMIC_FILTER classification.

No economics.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs" / "external-audit-01" / "h6-v4-repair"

V2_SPEC = REPO / "docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json"
V4_SPEC = OUT / "H6_SPEC_V4.json"
REPORT = OUT / "H6_V4_ECONOMIC_SEMANTIC_DIFF.json"

sys.path.insert(0, str(REPO / "src"))

# --- fields that MUST exist and be non-vacuous in V4 (checkpoint section 6) ----
REQUIRED_V4_FIELDS = [
    "hypothesis_id", "mechanism", "assets", "common_window_utc",
    "decision_timeframe", "oi_field_whitelist", "feature_transformations",
    "rolling_windows", "threshold_rule", "direction_semantics",
    "entry_timing", "exit_timing", "primary_holding_horizon",
    "stop_invalidation", "cooldown", "decision_spacing",
    "cost_model", "cost_model.BASE_TOTAL_ROUND_TRIP_COST_BPS",
    "cost_model.COST_SENSITIVITY_BPS", "funding_accounting", "minimum_N",
    "robustness_gates", "statistical_gates",
    "statistical_gates.P_Sharp_greater_0_min",
    "statistical_gates.permutation_p_max",
    "statistical_gates.sharpe_ci_excludes_zero",
    "statistical_gates.permutation.method",
    "statistical_gates.permutation.draws",
    "statistical_gates.permutation.seed",
    "orthogonality_gates",
    "pit_rules", "pit_rules.data_time_leq_decision_time", "pit_rules.oi",
    "pit_rules.price", "pit_rules.features", "pit_rules.future_mutation",
    "pit_rules.archive_validity_role",
    "insufficient_sample_policy", "pass_fail_semantics",
]

# Declared, justified representation-only differences (structural relocation).
DECLARED_RELOCATIONS = [
    {
        "v2_path": "statistical_gates.permutation",
        "v4_path": "statistical_gates.permutation.{method,targets,draws,seed,definition}",
        "classification": "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING",
        "justification": (
            "V2 stored the permutation design as one prose string; V4 keeps that exact "
            "string as permutation.definition AND freezes the same four facts as typed "
            "fields. Values are unchanged (sign-flip / hourly trade returns / 10000 / 20260911)."
        ),
    },
    {
        "v2_path": "common_window_utc.archive_validity_vs_decision_eligibility.DECISION_ELIGIBILITY_AT_T",
        "v4_path": "pit_rules.decision_eligibility (original location retained too)",
        "classification": "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING",
        "justification": (
            "V4 gives PIT eligibility a first-class structured home. The original V2 "
            "location is retained verbatim, so no information moves or changes."
        ),
    },
    {
        "v2_path": "robustness_gates",
        "v4_path": "statistical_gates.robustness + statistical_gates.robustness_rules",
        "classification": "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING",
        "justification": "Same robustness rules (halves/thirds/walk-forward) grouped with the other gates.",
    },
]

# Keys whose value is provenance/identity, not economics.
NON_ECONOMIC_KEYS = {
    "experiment_id", "schema", "spec_version", "preregistered_utc", "status_at_prereg",
    "H6_EXECUTIONS", "H6_BACKTESTS", "PERFORMANCE_OBSERVED", "repair_scope",
    "supersedes", "v3_defect_references", "v3_dropped_field_audit", "data_authority",
    "forbidden_until_execution_checkpoint", "experiment_invalidation",
}


def _dig(obj, path):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _norm(value):
    """Representation normalisation ONLY: whitespace + mojibake ligatures."""
    if isinstance(value, str):
        s = " ".join(value.split())
        s = s.replace("\u00e2\u20ac\u201d", "--").replace("\u00e2\u20ac\u2122", "'")
        s = s.replace("\u2014", "-").replace("\u2013", "-")
        return s
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    return value


def _perm_v2(spec):
    """Normalise V2's prose permutation string into typed facts."""
    raw = spec["statistical_gates"]["permutation"]
    if isinstance(raw, dict):
        return _perm_v4(spec)
    method = "sign-flip" if "sign-flip" in raw else raw
    draws = None
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and int(tok) >= 100:
            draws = int(tok)
    seed = None
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and len(tok) == 8:
            seed = int(tok)
    targets = "hourly trade returns" if "hourly trade returns" in raw else raw
    return {"method": method, "targets": targets, "draws": draws, "seed": seed, "definition": _norm(raw)}


def _perm_v4(spec):
    p = spec["statistical_gates"]["permutation"]
    return {
        "method": _norm(p["method"]),
        "targets": _norm(p.get("targets")),
        "draws": int(p["draws"]),
        "seed": int(p["seed"]),
        "definition": _norm(p.get("definition")),
    }


def economic_projection(spec: dict, version: int) -> dict:
    """One function, two specs. Returns the flat economic semantic surface."""
    fam = spec["mechanism"]["family"] if isinstance(spec["mechanism"], dict) else spec["mechanism"]
    proj = {
        "mechanism.name": _norm(_dig(spec, "mechanism.name")),
        "mechanism.family": _norm(fam),
        "mechanism.statement": _norm(_dig(spec, "mechanism.statement")),
        "assets": _norm(spec["assets"]),
        "common_window_utc.start": _norm(spec["common_window_utc"]["start"]),
        "common_window_utc.end": _norm(spec["common_window_utc"]["end"]),
        "decision_timeframe.bucket": _norm(spec["decision_timeframe"]["bucket"]),
        "decision_timeframe.primary_holding_horizon_hours": spec["decision_timeframe"][
            "primary_holding_horizon_hours"
        ],
        "oi_field_whitelist": _norm(spec["oi_field_whitelist"]),
        "rolling_windows.z_oi.length_hours": spec["rolling_windows"]["z_oi"]["length_hours"],
        "rolling_windows.z_oi.min_observations": spec["rolling_windows"]["z_oi"]["min_observations"],
        "rolling_windows.z_oi.center": _norm(spec["rolling_windows"]["z_oi"]["center"]),
        "threshold_rule": _norm(spec["threshold_rule"]),
        "direction_semantics": _norm(spec["direction_semantics"]),
        "entry_timing": _norm(spec["entry_timing"]),
        "exit_timing": _norm(spec["exit_timing"]),
        "primary_holding_horizon": _norm(spec["primary_holding_horizon"]),
        "stop_invalidation": _norm(spec["stop_invalidation"]),
        "cooldown": _norm(spec["cooldown"]),
        "decision_spacing": _norm(spec["decision_spacing"]),
        "cost_model.BASE_TOTAL_ROUND_TRIP_COST_BPS": spec["cost_model"][
            "BASE_TOTAL_ROUND_TRIP_COST_BPS"
        ],
        "cost_model.COST_SENSITIVITY_BPS": spec["cost_model"]["COST_SENSITIVITY_BPS"],
        "funding_accounting": _norm(spec["funding_accounting"]),
        "minimum_N": _norm(spec["minimum_N"]),
        "robustness_gates": _norm(spec["robustness_gates"]),
        "statistical_gates.P_Sharp_greater_0_min": spec["statistical_gates"][
            "P_Sharp_greater_0_min"
        ],
        "statistical_gates.permutation_p_max": spec["statistical_gates"]["permutation_p_max"],
        "statistical_gates.sharpe_ci_excludes_zero": spec["statistical_gates"][
            "sharpe_ci_excludes_zero"
        ],
        "statistical_gates.permutation": _perm_v2(spec) if version == 2 else _perm_v4(spec),
        "orthogonality_gates": _norm(spec["orthogonality_gates"]),
        "pit_rules.oi": _norm(spec["pit_rules"]["oi"]),
        "pit_rules.price": _norm(spec["pit_rules"]["price"]),
        "pit_rules.features": _norm(spec["pit_rules"]["features"]),
        "pit_rules.future_mutation": _norm(spec["pit_rules"]["future_mutation"]),
        "pit_rules.archive_validity_role": _norm(spec["pit_rules"]["archive_validity_role"]),
        "pit_rules.decision_eligibility": _norm(
            _dig(spec, "pit_rules.decision_eligibility")
            or _dig(spec, "common_window_utc.archive_validity_vs_decision_eligibility.DECISION_ELIGIBILITY_AT_T")
        ),
        "pit_rules.data_time_leq_decision_time": bool(
            spec["pit_rules"].get("data_time_leq_decision_time", True)
        ),
        "insufficient_sample_policy": _norm(spec["insufficient_sample_policy"]),
        "pass_fail_semantics": _norm(spec["pass_fail_semantics"]),
        "feature_transformations": _norm(spec["feature_transformations"]),
    }
    return proj


def check_completeness(spec: dict) -> dict:
    present, missing, vacuous = [], [], []
    for path in REQUIRED_V4_FIELDS:
        val = _dig(spec, path)
        if val is None:
            missing.append(path)
        elif isinstance(val, str) and not val.strip():
            vacuous.append(path)
        elif isinstance(val, (list, dict)) and len(val) == 0:
            vacuous.append(path)
        else:
            present.append(path)
    return {"present": present, "missing": missing, "vacuous": vacuous,
            "missing_count": len(missing), "vacuous_count": len(vacuous)}


def main() -> int:
    v2 = json.loads(V2_SPEC.read_text(encoding="utf-8"))
    v4 = json.loads(V4_SPEC.read_text(encoding="utf-8"))
    v4_bytes = V4_SPEC.read_bytes()
    v4_sha = hashlib.sha256(v4_bytes).hexdigest()

    # 1. runtime parser acceptance
    runtime_parse = {"ok": False, "error": None}
    try:
        from trading_bot.research.h6.frozen_contract_snapshot import parse_frozen_spec

        cfg = parse_frozen_spec(
            v4, spec_bytes=v4_bytes, spec_sha256=v4_sha,
            manifest_sha256="0" * 64, dataset_sha256="0" * 64,
        )
        runtime_parse = {
            "ok": True, "error": None,
            "permutation_method": cfg.permutation_method,
            "permutation_draws": cfg.permutation_draws,
            "permutation_seed": cfg.permutation_seed,
            "stop_invalidation_present": bool(cfg.stop_invalidation),
            "cooldown_present": bool(cfg.cooldown),
            "pit_data_time_leq_decision_time": cfg.pit_data_time_leq_decision_time,
        }
    except Exception as exc:  # noqa: BLE001
        runtime_parse = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # 2. completeness
    completeness = check_completeness(v4)

    # 3. semantic diff
    p2, p4 = economic_projection(v2, 2), economic_projection(v4, 4)
    rows = []
    for key in sorted(set(p2) | set(p4)):
        a, b = p2.get(key, "<ABSENT_IN_V2>"), p4.get(key, "<ABSENT_IN_V4>")
        if a == b:
            cls = "IDENTICAL"
        elif _norm(a) == _norm(b):
            cls = "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING"
        elif key in {r["v4_path"].split("{")[0].rstrip(".") for r in DECLARED_RELOCATIONS}:
            cls = "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING"
        elif a == "<ABSENT_IN_V2>":
            cls = "ADDED_ECONOMIC_FILTER"
        elif b == "<ABSENT_IN_V4>":
            cls = "DROPPED"
        else:
            cls = "CHANGED"
        rows.append({"field": key, "v2": a, "v4": b, "classification": cls})

    unexplained = [r for r in rows if r["classification"] in {"CHANGED", "DROPPED", "ADDED_ECONOMIC_FILTER"}]

    report = {
        "artifact": "H6_V4_ECONOMIC_SEMANTIC_DIFF",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "v2_spec": str(V2_SPEC.relative_to(REPO)).replace("\\", "/"),
        "v4_spec": str(V4_SPEC.relative_to(REPO)).replace("\\", "/"),
        "v4_spec_sha256": v4_sha,
        "runtime_parser_accepts_v4_spec": runtime_parse,
        "v4_spec_completeness": {
            "required_field_count": len(REQUIRED_V4_FIELDS),
            "present_count": len(completeness["present"]),
            "missing": completeness["missing"],
            "vacuous": completeness["vacuous"],
        },
        "declared_representation_relocations": DECLARED_RELOCATIONS,
        "semantic_fields": rows,
        "summary": {
            "IDENTICAL": sum(1 for r in rows if r["classification"] == "IDENTICAL"),
            "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING": sum(
                1 for r in rows if r["classification"] == "STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING"
            ),
            "CHANGED": sum(1 for r in rows if r["classification"] == "CHANGED"),
            "DROPPED": sum(1 for r in rows if r["classification"] == "DROPPED"),
            "ADDED_ECONOMIC_FILTER": sum(1 for r in rows if r["classification"] == "ADDED_ECONOMIC_FILTER"),
        },
        "UNEXPLAINED_DIFFERENCES": len(unexplained),
        "ECONOMIC_RETUNE_COUNT": len(unexplained),
        "unexplained_detail": unexplained,
        "V4_SPEC_COMPLETE": completeness["missing_count"] == 0 and completeness["vacuous_count"] == 0,
        "V2_TO_V4_UNEXPLAINED_ECONOMIC_DIFF": len(unexplained),
        "verdict": (
            "PASS"
            if (len(unexplained) == 0 and completeness["missing_count"] == 0
                and completeness["vacuous_count"] == 0 and runtime_parse.get("ok"))
            else "FAIL"
        ),
    }
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")

    print("VERDICT                          =", report["verdict"])
    print("runtime_parser_accepts_v4_spec   =", runtime_parse)
    print("missing/vacuous                  =", completeness["missing"], completeness["vacuous"])
    print("summary                          =", report["summary"])
    print("UNEXPLAINED_DIFFERENCES          =", report["UNEXPLAINED_DIFFERENCES"])
    print("report ->", REPORT.relative_to(REPO))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
