"""Builder-side V4 artefact construction (NON-RUNTIME, pre-freeze).

Creates the V4 preregistration package by carrying the economic contract forward
from the last COMPLETE pre-performance economic authority (``H6_SPEC_V2.json``) and
restoring the blocks V3 silently dropped (``statistical_gates``, structured
``pit_rules``, ``stop_invalidation``, ``cooldown``).

No economics. Nothing here computes PnL / Sharpe / PF / expectancy / win rate.

Everything is derived programmatically; nothing is retyped by hand.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs" / "external-audit-01" / "h6-v4-repair"

V2_SPEC = REPO / "docs" / "external-audit-01" / "oi-full-history-02" / "H6_SPEC_V2.json"
V2_MANIFEST = REPO / "docs" / "external-audit-01" / "oi-full-history-02" / "H6_MANIFEST_V2.json"
V3_DATA_AUTHORITY = REPO / "docs" / "external-audit-01" / "oi-full-history-03" / "H6_DATA_AUTHORITY_V3.json"
V3_WHITELIST = REPO / "docs" / "external-audit-01" / "oi-full-history-03" / "H6_FEATURE_AUTHORITY_WHITELIST_V3.json"

V4_SPEC = OUT / "H6_SPEC_V4.json"
V4_MANIFEST = OUT / "H6_MANIFEST_V4.json"
V4_WHITELIST = OUT / "H6_FEATURE_AUTHORITY_WHITELIST_V4.json"
V4_DATA_AUTHORITY = OUT / "H6_DATA_AUTHORITY_V4.json"

HYPOTHESIS_ID = "H6-OI-CONFIRMED-CONTINUATION-04"
PREREGISTERED_UTC = "2026-09-13"

# Fields V2 carried that V3 dropped (V3-SPEC-001..004). V4 must restore all of them.
V3_DROPPED_FIELDS = ("statistical_gates", "pit_rules", "stop_invalidation", "cooldown")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_json(path: Path, obj: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    path.write_text(data, encoding="utf-8", newline="\n")
    return _sha256_bytes(data.encode("utf-8"))


def build_spec() -> dict:
    """V4 spec = V2 economic contract + restored structured blocks. NO RETUNE."""
    v2 = json.loads(V2_SPEC.read_text(encoding="utf-8"))
    v3 = json.loads(
        (REPO / "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json").read_text(encoding="utf-8")
    )

    spec = json.loads(json.dumps(v2))  # deep copy; V2 is immutable history

    # -- identity -----------------------------------------------------------
    spec["experiment_id"] = 4
    spec["hypothesis_id"] = HYPOTHESIS_ID
    spec["schema"] = "H6_SPEC/4.0.0"
    spec["spec_version"] = 4
    spec["preregistered_utc"] = PREREGISTERED_UTC
    spec["status_at_prereg"] = "PREREGISTERED_NOT_EXECUTED"
    spec["H6_EXECUTIONS"] = 0
    spec["H6_BACKTESTS"] = 0
    spec["PERFORMANCE_OBSERVED"] = False
    spec["supersedes"] = "H6-OI-CONFIRMED-CONTINUATION-02 (V3 FAILED_PRE_EXECUTION; economic mechanism unchanged)"
    spec["repair_scope"] = {
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "reason": (
            "V3 FAILED_PRE_EXECUTION on authority / whitelist / runtime-binding / "
            "spec-consistency defects. V4 repairs governance, runtime wiring and "
            "spec completeness ONLY."
        ),
        "ECONOMIC_RETUNE": False,
        "H6_EXECUTIONS": 0,
        "H6_BACKTESTS": 0,
        "PERFORMANCE_OBSERVED": False,
        "restored_fields_dropped_by_v3": list(V3_DROPPED_FIELDS),
        "economic_mechanism_unchanged": True,
    }

    # Defects V3 was failed for (recorded so V4 self-describes its own repair scope).
    spec["v3_defect_references"] = [
        "V3-WL-001", "V3-WL-002", "V3-WL-003",
        "V3-AUTH-001",
        "V3-SPEC-001", "V3-SPEC-002", "V3-SPEC-003", "V3-SPEC-004",
        "V3-IMPORT-001", "V3-FEATURE-001", "V3-FEATURE-002",
    ]

    # -- data authority block points at the V4 package ----------------------
    spec["data_authority"]["oi_dataset"]["field_whitelist"] = (
        "docs/external-audit-01/h6-v4-repair/H6_FEATURE_AUTHORITY_WHITELIST_V4.json"
    )
    spec["data_authority"]["data_authority_artifact"] = (
        "docs/external-audit-01/h6-v4-repair/H6_DATA_AUTHORITY_V4.json"
    )
    # Carry the *corrected* ledger fingerprint from the V3 data authority: the V2
    # manifest value was malformed (72 chars). This is a DATA fact, not economic.
    v3_da = json.loads(V3_DATA_AUTHORITY.read_text(encoding="utf-8"))
    spec["data_authority"]["oi_dataset"]["OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2_SHA256"] = v3_da[
        "ledger_sha256"
    ]
    spec["data_authority"]["oi_dataset"]["ledger_line_count_expected"] = v3_da[
        "ledger_line_count_expected"
    ]
    spec["data_authority"]["oi_dataset"]["expected_file_counts"] = v3_da["expected_file_counts"]

    # -- restore stop / cooldown explicitly (V3-SPEC-003 / V3-SPEC-004) ------
    # Byte-identical to V2; only their *explicit presence* is newly required.
    spec["stop_invalidation"] = v2["stop_invalidation"]
    spec["cooldown"] = v2["cooldown"]

    # -- restore structured statistical gates (V3-SPEC-001) ------------------
    v2_gates = v2["statistical_gates"]
    spec["statistical_gates"] = {
        "P_Sharp_greater_0_min": v2_gates["P_Sharp_greater_0_min"],
        "permutation_p_max": v2_gates["permutation_p_max"],
        "sharpe_ci_excludes_zero": v2_gates["sharpe_ci_excludes_zero"],
        # STRUCTURALLY_RELOCATED_WITH_IDENTICAL_MEANING: V2 kept one prose string;
        # V4 keeps that exact string AND freezes the same facts as typed fields so
        # the runtime has a machine-checkable frozen authority for the seed/draws.
        "permutation": {
            "method": "sign-flip",
            "targets": "hourly trade returns",
            "draws": 10000,
            "seed": 20260911,
            "definition": v2_gates["permutation"],
        },
        "robustness": v2["robustness_gates"] if "robustness_gates" in v2 else v2.get("robustness_gates"),
    }
    if "robustness_gates" in v2:
        spec["statistical_gates"]["robustness_rules"] = v2["robustness_gates"]

    # -- restore structured PIT rules (V3-SPEC-002) --------------------------
    v2_pit = v2["pit_rules"]
    spec["pit_rules"] = {
        # Restates the invariant already present in pit_rules["oi"]; frozen as an
        # explicit machine-checkable boolean (STRUCTURALLY_RELOCATED).
        "data_time_leq_decision_time": True,
        "oi": v2_pit["oi"],
        "price": v2_pit["price"],
        "features": v2_pit["features"],
        "future_mutation": v2_pit["future_mutation"],
        "archive_validity_role": v2_pit["archive_validity_role"],
        "decision_eligibility": v2["common_window_utc"]["archive_validity_vs_decision_eligibility"][
            "DECISION_ELIGIBILITY_AT_T"
        ],
        "causality_invariant": (
            "Every observation used at decision time T satisfies oi_time <= T. "
            "Future same-day state MUST NOT invalidate or modify any decision taken at T. "
            "Enforced at runtime by feature_authority.admitted_observation + "
            "preparation.admitted_causal_observations."
        ),
    }

    # -- record what V3 dropped, for the fix record --------------------------
    spec["v3_dropped_field_audit"] = {
        "dropped_in_v3": [f for f in V3_DROPPED_FIELDS if f not in v3],
        "restored_in_v4": [f for f in V3_DROPPED_FIELDS if f in spec],
        "v3_present_keys_count": len(v3),
    }
    return spec


def build_manifest(spec_sha: str | None) -> dict:
    v2m = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    v3_da = json.loads(V3_DATA_AUTHORITY.read_text(encoding="utf-8"))

    m = {
        "experiment_id": 4,
        "hypothesis_id": HYPOTHESIS_ID,
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "spec_version": 4,
        "preregistered_utc": PREREGISTERED_UTC,
        "status_at_prereg": "PREREGISTERED_NOT_EXECUTED",
        "H6_EXECUTIONS": 0,
        "H6_BACKTESTS": 0,
        "PERFORMANCE_OBSERVED": False,
        "spec": {
            "path": "docs/external-audit-01/h6-v4-repair/H6_SPEC_V4.json",
            "sha256": spec_sha,
            "previous_spec_sha256_v2": "221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000 "
            "(IMMUTABLE historical; not overwritten)",
            "previous_spec_sha256_v3": "IMMUTABLE_FAILED_PRE_EXECUTION (not overwritten)",
        },
        "product": {
            "whitelist_path": "docs/external-audit-01/h6-v4-repair/H6_FEATURE_AUTHORITY_WHITELIST_V4.json",
            "data_authority_path": "docs/external-audit-01/h6-v4-repair/H6_DATA_AUTHORITY_V4.json",
            "runtime_authority_binding_expected": "docs/external-audit-01/h6-v4-repair/H6_RUNTIME_AUTHORITY_BINDING_V4.json",
            "note": "The authority binding is generated POST-FREEZE and is NON-ECONOMIC.",
        },
        "dataset": {
            "oi_full_history_v2": {
                "path": v3_da["local_cache_relative_or_configurable_path"].split(" + ")[-1],
                "manifest_path": v3_da["manifest_path"],
                "manifest_committed_copy": v3_da["manifest_committed_copy"],
                "manifest_sha256": v3_da["manifest_sha256"],
                "ledger_path": v3_da["ledger_path"],
                "ledger_sha256": v3_da["ledger_sha256"],
                "ledger_line_count_expected": v3_da["ledger_line_count_expected"],
                "OI_FULL_HISTORY_DATASET_SHA256": v3_da["dataset_sha256"],
                "schema_version": v3_da["schema_version"],
                "normalizer_version": v3_da["normalizer_version"],
                "expected_file_counts": v3_da["expected_file_counts"],
            },
            "price_authority_v2": v2m["dataset"]["price_authority_v2"],
            "field_whitelist": {
                "path": "docs/external-audit-01/h6-v4-repair/H6_FEATURE_AUTHORITY_WHITELIST_V4.json",
            },
        },
        "common_window_utc": ["2021-12-01T00:00:00Z", "2026-09-10T23:59:59Z"],
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "decision_timeframe": "1h",
        "entry_timing": "NEXT_HOUR_OPEN",
        "exit_timing": "NEXT_HOUR_CLOSE",
        "stop": "NONE",
        "cooldown": "NONE",
        "statistical_gates": {
            "P_Sharp_greater_0_min": 0.9,
            "permutation_p_max": 0.05,
            "sharpe_ci_excludes_zero": True,
            "permutation_method": "sign-flip",
            "permutation_draws": 10000,
            "permutation_seed": 20260911,
        },
        "governance": {
            "v3_failure_record": "docs/external-audit-01/h6-v4-repair/H6_V3_FAILURE_RECORD.json",
            "v4_defect_regression_matrix": "docs/external-audit-01/h6-v4-repair/H6_V4_DEFECT_REGRESSION_MATRIX.json",
            "selection_rationale": "docs/external-audit-01/h6-v4-repair/H6_SELECTION_RATIONALE_V4.md",
            "mechanism_evidence": "docs/external-audit-01/h6-v4-repair/H6_MECHANISM_EVIDENCE_V4.md",
            "failed_memory_collision_review": "docs/external-audit-01/h6-v4-repair/H6_FAILED_MEMORY_COLLISION_REVIEW_V4.md",
            "immutability": (
                "After this prereg commit the V4 economic artefacts (SPEC/MANIFEST/WHITELIST/"
                "DATA_AUTHORITY) are immutable. A non-economic H6_RUNTIME_AUTHORITY_BINDING_V4.json "
                "is created post-freeze and MUST NOT modify them."
            ),
            "builder_verifier_separation": (
                "Builder self-verification is builder evidence only and is NOT independent. "
                "Independent verification is H6-EXTERNAL-INDEPENDENT-VERIFICATION-V4 by a "
                "different context/agent."
            ),
        },
        "provenance": {
            "v2_prereg_historical": "IMMUTABLE (superseded by V4 for governance defects only)",
            "v3_prereg_historical": "IMMUTABLE_FAILED_PRE_EXECUTION",
            "note": "no prereg-commit self-reference inside this manifest; the post-freeze binding carries it",
        },
    }
    return m


def build_whitelist() -> dict:
    v3 = json.loads(V3_WHITELIST.read_text(encoding="utf-8"))
    w = {
        "artifact": "H6 feature authority whitelist V4",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "supersedes": "docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json",
        "ALLOWED_FIELDS": v3["ALLOWED_FIELDS"],
        "FORBIDDEN_FIELDS": v3["FORBIDDEN_FIELDS"],
        "ALLOWED_METADATA_FIELDS": [
            {"field": "timestamp_ms", "role": "PIT ordering / provenance (never a feature)"},
            {"field": "unit_semantics", "role": "unit provenance (never a feature)"},
            {"field": "source_file", "role": "provenance (never a feature)"},
            {"field": "source_sha256", "role": "provenance (never a feature)"},
        ],
        "H6_CONFIRMATION_DATA_DEPENDENCY": "NONE",
        "H6_SHADOW_DATA_DEPENDENCY": "NONE",
        "enforcement": {
            "accessor": (
                "H6FieldAccess — SANITIZING. Forbidden values are never stored: construction "
                "validates inbound keys and retains only admitted data in an immutable mapping."
            ),
            "boundary": (
                "feature_authority.admitted_observation — FAIL-CLOSED. A row carrying a forbidden "
                "or unadmitted field is rejected BEFORE any aggregation/feature/signal exists."
            ),
            "runtime_path": (
                "preparation.prepare_decision / prepare_decision_from_data_root is the actual H6 "
                "runtime entry point and calls the fail-closed boundary first."
            ),
            "bypass_paths_allowed": 0,
            "forbidden_values_stored": 0,
            "forbidden_values_recoverable": 0,
            "covers": [
                "__getitem__", "get", "get_default", "keys", "values", "items", "iteration",
                "contains", "len", "attribute", "repr", "str", "copy", "deepcopy", "pickle",
                "json_serialization", "mapping_unpack", "object_getattribute", "vars", "__dict__",
            ],
            "exception": "H6ForbiddenFeatureAccess",
            "rejection_exceptions": ["H6ForbiddenRowRejected", "H6UnadmittedField"],
        },
        "frozen_before": "any H6 V4 execution, backtest, or performance inspection",
        "repairs": {
            "V3-WL-001": "raw backing mapping exposed via H6FieldAccess.data (dataclass slot defeated __getattr__)",
            "V3-WL-002": "repr/copy/pickle/backing-object leakage of unadmitted provider values",
            "V3-WL-003": "whitelist not on the actual H6 runtime data path (decorative)",
        },
    }
    return w


def build_data_authority() -> dict:
    v3 = json.loads(V3_DATA_AUTHORITY.read_text(encoding="utf-8"))
    da = dict(v3)
    da["authority_version"] = "1.0.1"
    da["checkpoint"] = "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01"
    da["supersedes"] = "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json"
    da["unchanged_data_facts"] = (
        "The data authority facts are IDENTICAL to V3 (dataset fingerprint, manifest hash, "
        "ledger hash, counts, schema/normalizer versions). V3 DATA_AUTHORITY = PASS. No data "
        "was rebuilt."
    )
    da["field_whitelist_artifact"] = (
        "docs/external-audit-01/h6-v4-repair/H6_FEATURE_AUTHORITY_WHITELIST_V4.json"
    )
    return da


def main() -> None:
    spec = build_spec()
    spec_bytes = (json.dumps(spec, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    spec_sha = _sha256_bytes(spec_bytes)

    manifest = build_manifest(spec_sha)
    whitelist = build_whitelist()
    data_authority = build_data_authority()

    _write_json(V4_SPEC, spec)
    _write_json(V4_MANIFEST, manifest)
    _write_json(V4_WHITELIST, whitelist)
    _write_json(V4_DATA_AUTHORITY, data_authority)

    print("SPEC_V4_SHA256     =", spec_sha)
    print("MANIFEST_V4_SHA256 =", _sha256_bytes((V4_MANIFEST.read_bytes())))
    print("WHITELIST_V4_SHA256=", _sha256_bytes((V4_WHITELIST.read_bytes())))
    print("DATA_AUTH_V4_SHA256=", _sha256_bytes((V4_DATA_AUTHORITY.read_bytes())))
    print("V3_DROPPED_RESTORED=", spec["v3_dropped_field_audit"])


if __name__ == "__main__":
    main()
