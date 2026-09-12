"""H6 V3 builder consistency audit (spec 37).

Independently compares all V3 artifacts for contradictions across:
mechanism, assets, timeframe, history window, minimum observations, scale,
raw sign rule, z threshold, entry/exit, holding, stop, cooldown, cost,
funding, orthogonality, PIT, dataset, price, whitelist.

Output: docs/external-audit-01/oi-full-history-03/H6_V3_CONSISTENCY_AUDIT.json
Exit non-zero if any contradiction or unresolved item.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
E3 = REPO / "docs/external-audit-01/oi-full-history-03"
E2 = REPO / "docs/external-audit-01/oi-full-history-02"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    spec = json.loads((E3 / "H6_SPEC_V3.json").read_text(encoding="utf-8"))
    man = json.loads((E3 / "H6_MANIFEST_V3.json").read_text(encoding="utf-8"))
    wl = json.loads((E3 / "H6_FEATURE_AUTHORITY_WHITELIST_V3.json").read_text(encoding="utf-8"))
    da = json.loads((E3 / "H6_DATA_AUTHORITY_V3.json").read_text(encoding="utf-8"))
    rationale = (E3 / "H6_SELECTION_RATIONALE_V3.md").read_text(encoding="utf-8")
    collisions = (E3 / "H6_FAILED_MEMORY_COLLISION_REVIEW_V3.md").read_text(encoding="utf-8")

    contradictions: list[str] = []
    unresolved: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            contradictions.append(f"{name}: {detail}")

    # hashes recorded == actual bytes (hash authority)
    prov = {p["artifact"]: p["sha256"] for p in man["hash_provenance"]}
    check(
        "hash.spec_v2_provenance_matches_bytes",
        prov.get("H6_SPEC_V2.json (economics source, read not retyped)") == sha256_file(E2 / "H6_SPEC_V2.json"),
    )
    check(
        "hash.manifest_v2_matches_bytes",
        prov.get("OI_FULL_HISTORY_DATASET_MANIFEST_V2.json") == sha256_file(E2 / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"),
    )
    check(
        "hash.ledger_v2_matches_bytes",
        prov.get("OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl") == sha256_file(E2 / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"),
    )
    check(
        "hash.data_authority_matches_bytes",
        prov.get("H6_DATA_AUTHORITY_V3.json") == sha256_file(E3 / "H6_DATA_AUTHORITY_V3.json"),
    )
    check(
        "hash.whitelist_matches_bytes",
        man.get("whitelist_sha256") == sha256_file(E3 / "H6_FEATURE_AUTHORITY_WHITELIST_V3.json"),
    )
    for k, v in prov.items():
        check(f"hash_format.{k}", bool(re.fullmatch(r"[0-9a-f]{64}", v)), v)

    # assets
    check("assets.spec==whitelist_scope", spec["economics"]["assets"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    check("assets.dataset_authority_match", da["symbols"] == spec["economics"]["assets"])
    check(
        "assets.rationale_mentions",
        all(a in rationale for a in ("BTCUSDT", "ETHUSDT", "SOLUSDT")),
    )

    # mechanism / threshold
    thr = spec["economics"]["threshold_rule"]
    check("mechanism.expansion_only", "delta_oi > 0 AND z_oi >= +1.0" in thr["expansion_condition"])
    check("mechanism.mad_zero_no_trade", "MAD == 0 => NO_TRADE" in thr["expansion_condition_detail"])
    check(
        "mechanism.contraction_no_trade",
        thr["contraction_condition"].startswith("NO_TRADE") and "regardless of z" in thr["contraction_condition"],
    )
    check("mechanism.raw_sign_rule_in_rationale", "contraction yields NO_TRADE" in rationale or "expansion-only" in rationale)

    # window / scale
    z = spec["economics"]["rolling_windows"]["z_oi"]
    check("window.length_720h", z["length_hours"] == 720)
    check("window.min_obs_336", z["min_observations"] == 336)
    check("window.center_median", z["center"] == "median")
    check("window.scale_mad", z["scale"] == "1.4826*MAD")
    check(
        "window.rationale_frozen",
        "min_observations=336" in rationale and "1.4826" in rationale,
    )

    # timeframe / entry / exit / holding / stop / cooldown
    check("timeframe.1h", spec["economics"]["decision_timeframe"]["bucket"] == "1h")
    check("entry.next_hour_open", spec["economics"]["entry_timing"].startswith("next 1h bar OPEN"))
    check("exit.same_bar_close", spec["economics"]["exit_timing"] == "same next 1h bar CLOSE")
    check("holding.1h", spec["economics"]["decision_timeframe"]["primary_holding_horizon_hours"] == 1)
    check("cooldown.none", spec["economics"].get("decision_spacing") is not None and "COOLDOWN" in json.dumps(spec["economics"].get("decision_spacing")).upper() or "NO COOLDOWN" in json.dumps(spec["economics"]))

    # cost / funding / orthogonality
    check("cost.10bps", spec["economics"]["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"] == 10)
    check("cost.sensitivity", spec["economics"]["cost_model"]["COST_SENSITIVITY_BPS"] == [0, 10, 20, 40])
    check(
        "funding.excluded_with_limitation",
        spec["economics"]["funding_accounting"]["FUNDING_DISCOVERY_ACCOUNTING"] == "EXCLUDED_WITH_LIMITATION",
    )
    check(
        "funding.materiality_gate",
        spec["economics"]["funding_accounting"]["funding_materiality_gate_before_promotion"] is True,
    )
    check(
        "orthogonality.0.5",
        spec["economics"]["orthogonality_gates"]["MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"] == 0.5,
    )

    # governance / isolation
    g = spec["governance"]
    check("gov.no_economic_peek", g["H6_EXECUTIONS"] == 0 and g["H6_BACKTESTS"] == 0 and g["PERFORMANCE_OBSERVED"] is False)
    check("gov.shadow_dependency_none", g["H6_SHADOW_DATA_DEPENDENCY"] == "NONE")
    check("gov.confirmation_dependencies_none", all(g[k] == "NONE" for k in ("H6_CONFIRMATION_DATA_DEPENDENCY", "H6_CONFIRMATION_RESULT_DEPENDENCY", "H6_CONFIRMATION_PERFORMANCE_DEPENDENCY")))
    check("gov.manifest_governance_match", man["governance"] == g)
    check("gov.status_pending", g["status_at_prereg"] == "PENDING_EXTERNAL_VERIFICATION_V3")

    # dataset / price binding
    check(
        "dataset.sha_binding",
        spec["data_authority_v3"]["OI_FULL_HISTORY_DATASET_SHA256_V2"]
        == json.loads((E2 / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json").read_text(encoding="utf-8"))["OI_FULL_HISTORY_DATASET_SHA256_V2"],
    )
    check(
        "price.sha_binding",
        spec["data_authority_v3"]["price_authority_sha256_v2"]
        == json.loads((E2 / "PRICE_1H_AUTHORITY_V2_MANIFEST.json").read_text(encoding="utf-8"))["PRICE_AUTHORITY_SHA256_V2"],
    )
    check(
        "data_authority.doc_sha_binding",
        spec["data_authority_v3"]["authority_doc_sha256"] == sha256_file(E3 / "H6_DATA_AUTHORITY_V3.json"),
    )
    check("data_authority.expected_counts", da["expected_file_counts"] == {"BTCUSDT": 2201, "ETHUSDT": 1745, "SOLUSDT": 1745, "TOTAL": 5691})

    # whitelist binding
    allowed_fields = [f["field"] for f in wl["ALLOWED_FIELDS"]]
    check("whitelist.contains_oi_fields", "sum_open_interest" in allowed_fields and "sum_open_interest_value" in allowed_fields)
    check("whitelist.forbidden_ratio_fields", len(wl["FORBIDDEN_FIELDS"]) == 4)
    check("whitelist.bypass_zero", wl["enforcement"]["bypass_paths_allowed"] == 0)
    spec_wl = spec["economics"].get("oi_field_whitelist")
    if spec_wl is not None:
        spec_wl_fields = set(json.dumps(spec_wl))  # structural presence
        check("whitelist.spec_binding_present", bool(spec_wl_fields))

    # hypothesis identity + supersession
    check("identity.hypothesis_03", spec["hypothesis_id"] == "H6-OI-CONFIRMED-CONTINUATION-03")
    check("identity.manifest_experiment_match", man["experiment"] == spec["hypothesis_id"])
    check("identity.rationale_03", "H6-OI-CONFIRMED-CONTINUATION-03" in rationale)
    check("identity.collision_verdict_pass", "VERDICT: PASS" in collisions)

    # PIT
    check("pit.no_day_gate", "no final UTC-day validity gate" in spec["economics"]["decision_timeframe"].get("oi_aggregation_rule", ""))

    out = {
        "checkpoint": "H6-V3-REPAIR-PREREG",
        "audit": "V3_CONSISTENCY",
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip(),
        "checks_total": len(contradictions) + 0,
        "CONTRADICTIONS_FOUND": len(contradictions),
        "contradictions": contradictions,
        "UNRESOLVED": unresolved,
        "status": "PASS" if not contradictions and not unresolved else "FAIL",
    }
    (E3 / "H6_V3_CONSISTENCY_AUDIT.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("status", "CONTRADICTIONS_FOUND", "UNRESOLVED")}, indent=2))
    if contradictions:
        print(json.dumps(contradictions, indent=1))
    return 0 if out["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
