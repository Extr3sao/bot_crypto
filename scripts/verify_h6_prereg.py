"""H6 prereg SELF-verification (OI-FULL-HISTORY-FREEZE-01 Track Q).

Independently reloads the frozen prereg artifacts and recomputes every
invariant with its OWN logic (no imports from the builder's normalizer).
This is SELF-verification by the builder agent; it is NOT independent
certification (see H6_EXTERNAL_VERIFIER_PACKAGE).

Emits: docs/external-audit-01/oi-full-history-01/H6_SELF_VERIFICATION.json
Exit code 0 iff verdict PASS.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIR = REPO / "docs" / "external-audit-01" / "oi-full-history-01"
LEDGER = REPO / "data" / "processed" / "oi_full_history" / "OI_DAY_VALIDITY_LEDGER.jsonl"
DATASET_MANIFEST = REPO / "data" / "processed" / "oi_full_history" / "OI_FULL_HISTORY_DATASET_MANIFEST.json"

FROZEN_DATASET_SHA256 = "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"
H5_RESULT_SHA = "2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f"
H5_MANIFEST_SHA = "29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(results: list[dict[str, object]], name: str, ok: bool, detail: str = "") -> None:
    results.append({"check": name, "ok": bool(ok), "detail": detail})


def main() -> int:
    results: list[dict[str, object]] = []

    # ---- artifacts exist ----
    spec_p, man_p = DIR / "H6_SPEC.json", DIR / "H6_MANIFEST.json"
    rec_p = DIR / "H6_PREREG_COMMIT_RECORD.json"
    for p in (spec_p, man_p, rec_p, DIR / "H6_FEATURE_AUTHORITY_WHITELIST.json",
              DIR / "H6_FAILED_MEMORY_COLLISION_REVIEW.md", DIR / "H6_MECHANISM_EVIDENCE.md",
              DIR / "H6_PREREG_CONSISTENCY_AUDIT.json", LEDGER, DATASET_MANIFEST):
        check(results, f"artifact_exists:{p.name}", p.exists())

    spec = json.loads(spec_p.read_text(encoding="utf-8"))
    man = json.loads(man_p.read_text(encoding="utf-8"))
    rec = json.loads(rec_p.read_text(encoding="utf-8"))
    audit = json.loads((DIR / "H6_PREREG_CONSISTENCY_AUDIT.json").read_text(encoding="utf-8"))

    # ---- hashes recomputed ----
    spec_sha = sha256(spec_p)
    man_sha = sha256(man_p)
    check(results, "manifest.spec_sha256_matches_spec_bytes", man["spec"]["sha256"] == spec_sha, spec_sha)
    check(results, "commit_record.spec_sha_matches", rec["spec_blob_sha256"] == spec_sha)
    check(results, "commit_record.manifest_sha_matches", rec["manifest_blob_sha256"] == man_sha)
    check(results, "commit_record.whitelist_sha_matches",
          rec["whitelist_sha256"] == sha256(DIR / "H6_FEATURE_AUTHORITY_WHITELIST.json"))
    dman_sha = sha256(DATASET_MANIFEST)
    check(results, "commit_record.oi_dataset_manifest_sha_matches", rec["oi_dataset_manifest_sha256"] == dman_sha)
    ledger_sha = sha256(LEDGER)
    check(results, "commit_record.ledger_sha_matches", rec["validity_ledger_evidence_sha256"] == sha256(DIR / "OI_DAY_VALIDITY_LEDGER.evidence.jsonl"))

    # dataset canonical fingerprint recomputed from ledger (independent implementation)
    ledger = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    dm = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    files = [
        {k: e.get(k) for k in ("symbol", "day", "raw_source_sha256", "normalized_sha256", "rows", "dataset_fingerprint", "classification")}
        for e in sorted(ledger, key=lambda e: (str(e["symbol"]), str(e["day"])))
    ]
    fp = hashlib.sha256(json.dumps(
        {"schema_version": dm["schema_version"], "normalizer_version": dm["normalizer_version"], "files": files},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    check(results, "dataset_fingerprint_recomputed_matches_frozen", fp == FROZEN_DATASET_SHA256, fp)
    check(results, "manifest_dataset_sha_matches_frozen", man["dataset"]["oi_full_history"]["OI_FULL_HISTORY_DATASET_SHA256"] == FROZEN_DATASET_SHA256)

    # prereg commit immutability
    commit = rec["H6_PREREG_COMMIT"]
    for label, path in (("spec", spec_p), ("manifest", man_p)):
        out = subprocess.run(["git", "diff", commit, "--", str(path)], capture_output=True, text=True).stdout
        check(results, f"git_diff_empty_since_prereg:{label}", out == "")
    tree_now = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip()
    check(results, "commit_record.tree_is_ancestor_identity",
          subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], capture_output=True).returncode == 0)

    # ---- canonical semantics (single values, mirrored in manifest) ----
    check(results, "experiment_id_is_1", spec["experiment_id"] == 1 and man["experiment_id"] == 1)
    check(results, "hypothesis_id_consistent", spec["hypothesis_id"] == man["hypothesis_id"] == "H6-OI-POSITION-STOCK-01")
    check(results, "assets_consistent", spec["assets"] == man["assets"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    check(results, "window_consistent",
          spec["common_window_utc"]["start"] == man["common_window_utc"][0] == "2021-12-01T00:00:00Z"
          and spec["common_window_utc"]["end"] == man["common_window_utc"][1] == "2026-09-10T23:59:59Z")
    check(results, "decision_timeframe_1h", spec["decision_timeframe"]["bucket"] == "1h" and man["decision_timeframe"] == "1h")
    check(results, "horizon_1h", spec["decision_timeframe"]["primary_holding_horizon_hours"] == 1)
    check(results, "entry_next_hour_open", spec["entry_timing"].startswith("next 1h bar OPEN") and man["entry_timing"] == "NEXT_HOUR_OPEN")
    check(results, "exit_same_hour_close", spec["exit_timing"].startswith("same next 1h bar CLOSE") and man["exit_timing"] == "NEXT_HOUR_CLOSE")
    check(results, "stop_none", spec["stop_invalidation"].startswith("NONE") and man["stop"] == "NONE")
    check(results, "cooldown_none", spec["cooldown"].startswith("NONE") and man["cooldown"] == "NONE")
    check(results, "expansion_only", spec["threshold_rule"]["expansion_condition"] == "z_oi >= +1.0"
          and spec["threshold_rule"]["contraction_condition"].startswith("NOT USED"))
    check(results, "robust_z_mad_definition",
          spec["rolling_windows"]["z_oi"]["center"] == "median"
          and spec["rolling_windows"]["z_oi"]["scale"] == "1.4826*MAD"
          and spec["rolling_windows"]["z_oi"]["length_hours"] == 720
          and spec["rolling_windows"]["z_oi"]["min_observations"] == 336)
    check(results, "cost_single_canonical_10bps", spec["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"] == 10
          and man["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"] == 10
          and spec["cost_model"]["COST_SENSITIVITY_BPS"] == [0, 10, 20, 40])
    check(results, "funding_excluded_with_limitation",
          spec["funding_accounting"]["FUNDING_DISCOVERY_ACCOUNTING"] == "EXCLUDED_WITH_LIMITATION"
          and spec["funding_accounting"]["funding_materiality_gate_before_promotion"] is True)
    check(results, "orthogonality_0p50_single",
          spec["orthogonality_gates"]["MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"] == 0.50
          and man["gates"]["orthogonality_vs_momentum_abs_r_max"] == 0.50)
    check(results, "h5_comparator_honest",
          spec["orthogonality_gates"]["H5_PNL_CORRELATION"].startswith("NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE"))
    check(results, "minimum_N_frozen",
          spec["minimum_N"]["per_asset_trades"] == 30 and spec["minimum_N"]["pooled_trades"] == 100
          and man["gates"]["minimum_N"] == {"per_asset": 30, "pooled": 100})
    check(results, "statistical_gates_frozen",
          spec["statistical_gates"]["P_Sharp_greater_0_min"] == 0.90
          and spec["statistical_gates"]["permutation_p_max"] == 0.05
          and spec["statistical_gates"]["sharpe_ci_excludes_zero"] is True)
    check(results, "robustness_gates_frozen",
          spec["robustness_gates"] == [
              "halves consistency: sign of net expectancy must agree across first/second half of the common window",
              "thirds consistency: at least 2 of 3 thirds positive net expectancy",
              "walk-forward: rolling 3-fold forward evaluation must not have all folds negative",
          ])

    # ---- causal eligibility (P0-B/H) frozen in spec ----
    av = spec["common_window_utc"]["archive_validity_vs_decision_eligibility"]
    check(results, "causal_eligibility_frozen",
          "DECISION_ELIGIBILITY_AT_T" in av and "data_time <= T" in av["DECISION_ELIGIBILITY_AT_T"]
          and "NOT directly control" in av["ARCHIVE_DAY_VALIDITY"])
    check(results, "twelve_snapshot_rule_in_spec", "12 distinct 5m OI snapshots" in json.dumps(spec))
    check(results, "future_gap_invariant_in_spec", "gap strictly AFTER T must not alter eligibility" in json.dumps(spec))

    # ---- field whitelist ----
    wl = json.loads((DIR / "H6_FEATURE_AUTHORITY_WHITELIST.json").read_text(encoding="utf-8"))
    allowed = {f["field"] for f in wl["ALLOWED_FIELDS"]}
    forbidden = set(wl["FORBIDDEN_FIELDS_FOR_H6"])
    check(results, "whitelist_contains_oi_fields", {"sum_open_interest", "sum_open_interest_value"} <= allowed)
    check(results, "whitelist_excludes_ratio_fields", not (allowed & forbidden) and len(forbidden) == 4)
    check(results, "spec_forbidden_matches_whitelist", set(spec["data_authority"]["forbidden_fields"]) == forbidden)

    # ---- consistency audit ----
    check(results, "consistency_audit_pass", audit["commit_allowed"] is True and audit["UNRESOLVED_FIELDS"] == [])

    # ---- no performance observed / counters zero ----
    def _zero(v: object) -> bool:
        return v == 0 or v is False
    check(results, "no_execution_counters", _zero(spec["H6_EXECUTIONS"]) and _zero(spec["H6_BACKTESTS"])
          and spec["PERFORMANCE_OBSERVED"] is False and man["H6_EXECUTIONS"] == 0
          and man["H6_BACKTESTS"] == 0 and man["PERFORMANCE_OBSERVED"] is False)
    forbidden_keys = ("result", "returns", "sharpe_realized", "expectancy_realized", "trades", "equity", "pnl")
    spec_keys = {k.lower() for k in spec}
    check(results, "no_performance_fields_in_spec", not (spec_keys & set(forbidden_keys)))
    check(results, "status_at_prereg", spec["status_at_prereg"] == "PREREGISTERED_NOT_EXECUTED" and man["status_at_prereg"] == "PREREGISTERED_NOT_EXECUTED")
    check(results, "no_sweep_language", "NO parameter sweep" in json.dumps(spec) and "NO_PARAMETER_SWEEP" in json.dumps(man))

    # ---- failed-memory review + mechanism evidence present and PASS ----
    review = (DIR / "H6_FAILED_MEMORY_COLLISION_REVIEW.md").read_text(encoding="utf-8")
    check(results, "collision_review_pass", "H6_FAILED_MEMORY_COLLISION_REVIEW = PASS" in review or "`PASS`" in review)
    mech = (DIR / "H6_MECHANISM_EVIDENCE.md").read_text(encoding="utf-8")
    check(results, "mechanism_evidence_tiers", "OFFICIAL_EXCHANGE_DOC" in mech and "No claim of profitability" in mech)

    # ---- H5 immutable ----
    h5r = REPO / "docs/external-audit-01/h5-orderflow-imbalance-01/H5_RESULT.json"
    h5m = REPO / "docs/external-audit-01/h5-orderflow-imbalance-01/H5_MANIFEST.json"
    check(results, "h5_result_unchanged", sha256(h5r) == H5_RESULT_SHA)
    check(results, "h5_manifest_unchanged", sha256(h5m) == H5_MANIFEST_SHA)

    # ---- price authority ----
    for asset in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        p = REPO / f"docs/external-audit-01/h1-regime-transition-01/dataset/{asset}_1h.jsonl"
        ok = p.exists()
        if ok:
            last = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
            ok = int(last[0]) == 1788912000000
        check(results, f"price_authority_covers_window:{asset}", ok)

    failed = [r for r in results if not r["ok"]]
    verdict = "PASS" if not failed else "FAIL"
    out = {
        "artifact": "H6_SELF_VERIFICATION (Track Q) — builder self-verification, NOT independent certification",
        "generated_utc": "2026-09-11",
        "H6_SELF_VERIFICATION": verdict,
        "H6_INDEPENDENT_VERIFICATION": "PENDING_EXTERNAL_VERIFIER",
        "prereg_commit": commit,
        "spec_sha256": spec_sha,
        "manifest_sha256": man_sha,
        "dataset_sha256": FROZEN_DATASET_SHA256,
        "ledger_sha256": ledger_sha,
        "checks_total": len(results),
        "checks_failed": len(failed),
        "checks": results,
    }
    (DIR / "H6_SELF_VERIFICATION.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"H6_SELF_VERIFICATION={verdict} ({len(results) - len(failed)}/{len(results)} checks passed)")
    for r in failed:
        print("  FAIL:", r["check"], "-", r.get("detail", ""))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
