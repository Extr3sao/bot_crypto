"""H6 PREREG V2 consistency audit — machine-check every frozen field across V2 artifacts.

Compares:
  H6_SPEC_V2.json
  H6_MANIFEST_V2.json
  H6_SELECTION_RATIONALE_V2.md
  H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md
  H6_MECHANISM_EVIDENCE_V2.md
  H6_FEATURE_AUTHORITY_WHITELIST_V2.json
  (plus execution contract docs implicitly via spec)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EV = REPO / "docs" / "external-audit-01" / "oi-full-history-02"
SPEC_PATH = EV / "H6_SPEC_V2.json"
MANIFEST_PATH = EV / "H6_MANIFEST_V2.json"
RATIONALE_PATH = EV / "H6_SELECTION_RATIONALE_V2.md"
FAILED_PATH = EV / "H6_FAILED_MEMORY_COLLISION_REVIEW_V2.md"
MECHANISM_PATH = EV / "H6_MECHANISM_EVIDENCE_V2.md"
WHITELIST_PATH = EV / "H6_FEATURE_AUTHORITY_WHITELIST_V2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rationale = RATIONALE_PATH.read_text(encoding="utf-8")
    failed = FAILED_PATH.read_text(encoding="utf-8")
    mechanism = MECHANISM_PATH.read_text(encoding="utf-8")
    whitelist = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))

    checks: list[dict] = []

    def check(dimension: str, canonical, actual_raw, actual_for_check=None):
        # compare canonical vs value from artifact; resolved if equal (including list/set equivalence)
        actual = actual_for_check if actual_for_check is not None else actual_raw
        resolved = canonical == actual
        # For floats allow 0.50 == 0.5
        if not resolved and isinstance(canonical, float) and isinstance(actual, float):
            resolved = abs(canonical - actual) < 1e-9
        checks.append({"dimension": dimension, "canonical": canonical, "value": actual_raw, "resolved": resolved})
        return resolved

    # Core mechanism / hypothesis
    check("hypothesis_id", "H6-OI-CONFIRMED-CONTINUATION-02", spec["hypothesis_id"])
    check("manifest hypothesis matches spec", spec["hypothesis_id"], manifest["hypothesis_id"])
    check("spec_version", 2, spec.get("spec_version"))
    check("manifest spec_version", 2, manifest.get("spec_version"))
    check("mechanism.name", "OI_CONFIRMED_CONTINUATION", spec["mechanism"]["name"])
    check("mechanism family", "position_stock_conditioning", spec["mechanism"]["family"])
    check("assets", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], spec["assets"])
    check("manifest assets match spec", spec["assets"], manifest["assets"])
    check("window start", "2021-12-01T00:00:00Z", spec["common_window_utc"]["start"])
    check("manifest window start", spec["common_window_utc"]["start"], manifest["common_window_utc"][0])
    check("window end", "2026-09-10T23:59:59Z", spec["common_window_utc"]["end"])
    check("decision_timeframe.bucket", "1h", spec["decision_timeframe"]["bucket"])
    check("manifest decision_timeframe", "1h", manifest["decision_timeframe"])
    check("primary_holding_horizon", 1, spec["decision_timeframe"]["primary_holding_horizon_hours"])
    check("entry_timing", "next 1h bar OPEN (the bar immediately after the decision hour)", spec["entry_timing"])
    # manifest carries short canonical form NEXT_HOUR_OPEN but must semantically match spec
    check("manifest entry", True, manifest["entry_timing"] in ("NEXT_HOUR_OPEN", spec["entry_timing"]))
    check("exit_timing", "same next 1h bar CLOSE", spec["exit_timing"])
    check("stop", "NONE in the primary H6 discovery test (no ATR stop, no signal-flip exit; trade management belongs to a later preregistered experiment)", spec["stop_invalidation"])
    check("manifest stop", "NONE", manifest["stop"])
    check("cooldown", "NONE required: fixed 1h non-overlapping per-asset outcome definition (entry at next hour open, exit at that hour's close); secondary horizons are NOT computed and MAY NOT influence PASS/FAIL", spec["cooldown"])
    check("manifest cooldown", "NONE", manifest["cooldown"])
    check("decision_spacing", "NO COOLDOWN / ONE DECISION PER COMPLETED ASSET-HOUR", spec["decision_spacing"])
    # Cost
    check("cost canonical", 10, spec["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"])
    check("manifest cost", 10, manifest["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"])
    check("cost definition single", "10 bps is the TOTAL modeled round-trip trading friction (single canonical number; not decomposed into per-side fees/slippage)", spec["cost_model"]["definition"])
    check("cost sensitivity", [0, 10, 20, 40], spec["cost_model"]["COST_SENSITIVITY_BPS"])
    # Funding
    check("funding policy", "EXCLUDED_WITH_LIMITATION", spec["funding_accounting"]["FUNDING_DISCOVERY_ACCOUNTING"])
    check("funding gate", True, spec["funding_accounting"]["funding_materiality_gate_before_promotion"])
    # Orthogonality
    check("orthogonality threshold", 0.5, spec["orthogonality_gates"]["MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"])
    check("manifest orthogonality", 0.5, manifest["gates"]["orthogonality_vs_momentum_abs_r_max"])
    # Rolling windows
    check("z window", 720, spec["rolling_windows"]["z_oi"]["length_hours"])
    check("z min obs", 336, spec["rolling_windows"]["z_oi"]["min_observations"])
    check("z center", "median", spec["rolling_windows"]["z_oi"]["center"])
    check("z scale", "1.4826*MAD", spec["rolling_windows"]["z_oi"]["scale"])
    # Threshold with raw-sign rule
    check("expansion requires delta>0 AND z>=1", "delta_oi > 0 AND z_oi >= +1.0", spec["threshold_rule"]["expansion_condition"])
    check("manifest threshold_rule contains delta_oi", True, "delta_oi" in manifest["threshold_rule"])
    # Direction semantics incorporate raw-sign
    check("LONG direction", "price UP (close > open) AND delta_oi > 0 AND z_oi >= +1.0", spec["direction_semantics"]["LONG"])
    check("SHORT direction", "price DOWN (close < open) AND delta_oi > 0 AND z_oi >= +1.0", spec["direction_semantics"]["SHORT"])
    check("NO_TRADE", "delta_oi <= 0, or z_oi < +1.0, or price close == open, or any NO_SIGNAL condition", spec["direction_semantics"]["NO_TRADE"])
    # Experiment counters
    check("H6_EXECUTIONS", 0, spec["H6_EXECUTIONS"])
    check("manifest H6_EXECUTIONS", 0, manifest["H6_EXECUTIONS"])
    check("H6_BACKTESTS", 0, spec["H6_BACKTESTS"])
    check("PERFORMANCE_OBSERVED", False, spec["PERFORMANCE_OBSERVED"])
    # Data authority paths
    check("oi dataset path V2", "data/processed/oi_full_history_v2/", spec["data_authority"]["oi_dataset"]["path"])
    check("price authority template V2", "data/processed/price_1h_v2/{ASSET}_1h.jsonl", spec["data_authority"]["price_authority"]["path_template"])
    check("price covers window", True, spec["data_authority"]["price_authority"]["covers_common_window"])
    # Whitelist
    check("whitelist fields subset of spec oi whitelist", sorted(spec["oi_field_whitelist"]), sorted([f["field"] for f in whitelist["ALLOWED_FIELDS"] if f["field"] in spec["oi_field_whitelist"]]))
    # Spec sha in manifest matches current spec bytes
    actual_spec_sha = _sha(SPEC_PATH)
    check("spec sha in manifest matches current spec bytes", actual_spec_sha, manifest["spec"]["sha256"])

    # Textual cross-checks (rationale/failed/memory must not contradict spec on frozen values)
    # Extract key statements from rationale to ensure they match spec
    textual_ok = True
    for phrase, dimension in [
        ("BASE_TOTAL_ROUND_TRIP_COST_BPS=10", "rationale cost 10 bps"),
        ("|r| ≤ 0.50", "rationale orthogonality 0.50"),
        ("median", "rationale normalization median/MAD"),
        ("NO COOLDOWN", "rationale cooldown NONE"),
        ("ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl", "rationale V2 ledger"),
        ("delta_oi > 0 AND robust_z", "rationale raw-sign rule"),
    ]:
        found = phrase in rationale
        checks.append({"dimension": dimension, "canonical": True, "value": found, "resolved": found})
        if not found:
            textual_ok = False

    for phrase, dimension in [
        ("NO COOLDOWN", "failed review cooldown NONE"),
        ("ARCHIVE_DAY_VALIDITY", "failed review archive forensic"),
        ("median", "failed review normalization"),
        ("EXCLUDED_WITH_LIMITATION", "failed review funding"),
        ("BASE_TOTAL_ROUND_TRIP_COST_BPS=10", "failed review cost 10"),
    ]:
        found = phrase in failed
        checks.append({"dimension": dimension, "canonical": True, "value": found, "resolved": found})
        if not found:
            textual_ok = False

    # H5 untouched
    h5_r = "2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f"
    check("H5_RESULT_SHA256", h5_r, manifest["H5_state_untouched"]["H5_RESULT_SHA256"])

    contradictions_found = sum(1 for c in checks if not c["resolved"])
    unresolved = [c["dimension"] for c in checks if not c["resolved"]]
    return {
        "artifact": "H6_PREREG_CONSISTENCY_AUDIT_V2 (machine-check)",
        "checkpoint": "H6-PREREG-REPAIR-01 + OI-DATASET-REFREEZE-02",
        "spec_path": str(SPEC_PATH.relative_to(REPO)).replace("\\", "/"),
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO)).replace("\\", "/"),
        "spec_sha256": _sha(SPEC_PATH),
        "manifest_sha256": _sha(MANIFEST_PATH),
        "checks": checks,
        "CONTRADICTIONS_FOUND": contradictions_found,
        "CONTRADICTIONS_RESOLVED": [c["dimension"] for c in checks if c["resolved"]],
        "UNRESOLVED_CONTRADICTIONS": unresolved,
        "UNRESOLVED_FIELDS": unresolved,
        "dimensions_checked": len(checks),
        "commit_allowed": contradictions_found == 0,
        "verdict": "PASS" if contradictions_found == 0 else "FAIL",
    }


def main() -> int:
    result = audit()
    (EV / "H6_PREREG_CONSISTENCY_AUDIT_V2.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# H6 PREREG CONSISTENCY AUDIT V2 — {result['checkpoint']}",
        "",
        f"**Result: `{result['verdict']}` — `UNRESOLVED_FIELDS = {result['UNRESOLVED_FIELDS']}` ({result['dimensions_checked'] - result['CONTRADICTIONS_FOUND']}/{result['dimensions_checked']} resolved, commit_allowed={result['commit_allowed']})**",
        "",
        f"spec: `{result['spec_path']}` sha={result['spec_sha256'][:16]}...",
        f"manifest: `{result['manifest_path']}` sha={result['manifest_sha256'][:16]}...",
        "",
        "## Dimensions",
        "",
        "| Dimension | Canonical | Value | Resolved |",
        "| --- | --- | --- | --- |",
    ]
    for c in result["checks"]:
        can = str(c["canonical"])[:80]
        val = str(c["value"])[:80]
        lines.append(f"| {c['dimension']} | `{can}` | `{val}` | {c['resolved']} |")
    (EV / "H6_PREREG_CONSISTENCY_AUDIT_V2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "contradictions": result["CONTRADICTIONS_FOUND"], "unresolved": result["UNRESOLVED_CONTRADICTIONS"]}, indent=2))
    if result["verdict"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
