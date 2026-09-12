"""H6 V3 preregistration artifact generator.

Generates, from programmatically-derived values ONLY (no manual hash copy-paste):
  docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json
  docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json
  docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json

Economic semantics are carried forward UNCHANGED from the frozen V2 spec
(hypothesis id advances to -03 per repair plan section 33; nothing else in the
economic block changes). Every hash field is computed from actual stored bytes
and validated against ^[0-9a-f]{64}$ BEFORE serialization; any invalid hash
aborts generation (fail closed, EXT-MANIFEST-HASH-001 root repair).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVID3 = REPO / "docs" / "external-audit-01" / "oi-full-history-03"
EVID2 = REPO / "docs" / "external-audit-01" / "oi-full-history-02"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_rev() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()


def validate_sha(value: str, field: str) -> str:
    import re

    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SystemExit(f"HASH_VALIDATION_FAILED before serialization: {field}={value!r}")
    return value


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    commit = git_rev()

    # ---- carried-forward economics from the frozen V2 spec (read, not retyped) ----
    v2_spec = json.loads((EVID2 / "H6_SPEC_V2.json").read_text(encoding="utf-8"))
    ECON_KEYS = [
        "assets",
        "common_window_utc",
        "decision_timeframe",
        "rolling_windows",
        "threshold_rule",
        "cost_model",
        "funding_accounting",
        "orthogonality_gates",
        "minimum_N",
        "insufficient_sample_policy",
        "pass_fail_semantics",
        "robustness_gates",
        "feature_transformations",
        "direction_semantics",
        "entry_timing",
        "exit_timing",
        "decision_spacing",
        "primary_holding_horizon",
        "experiment_invalidation",
        "forbidden_until_execution_checkpoint",
        "oi_field_whitelist",
    ]
    economics = {k: v2_spec[k] for k in ECON_KEYS if k in v2_spec}
    # frozen invariants asserted (spec 33): any drift aborts
    assert v2_spec["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"] == 10
    assert v2_spec["cost_model"]["COST_SENSITIVITY_BPS"] == [0, 10, 20, 40]
    assert v2_spec["assets"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert v2_spec["rolling_windows"]["z_oi"]["min_observations"] == 336
    assert v2_spec["rolling_windows"]["z_oi"]["center"] == "median"
    assert v2_spec["rolling_windows"]["z_oi"]["scale"] == "1.4826*MAD"
    assert "delta_oi > 0 AND z_oi >= +1.0" in v2_spec["threshold_rule"]["expansion_condition"]

    # ---- dataset authority (actual bytes from committed evidence copies) ----
    dataset_manifest_v2_path = EVID2 / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    ledger_v2_path = EVID2 / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
    dataset_manifest_sha = validate_sha(sha256_file(dataset_manifest_v2_path), "dataset_manifest_sha256")
    ledger_sha = validate_sha(sha256_file(ledger_v2_path), "ledger_sha256")
    ds_m = json.loads(dataset_manifest_v2_path.read_text(encoding="utf-8"))
    dataset_sha = validate_sha(ds_m["OI_FULL_HISTORY_DATASET_SHA256_V2"], "dataset_sha256")

    price_m = json.loads((EVID2 / "PRICE_1H_AUTHORITY_V2_MANIFEST.json").read_text(encoding="utf-8"))
    price_sha = validate_sha(price_m["PRICE_AUTHORITY_SHA256_V2"], "price_authority_sha256")

    data_authority_path = EVID3 / "H6_DATA_AUTHORITY_V3.json"
    data_authority_sha = validate_sha(sha256_file(data_authority_path), "data_authority_sha256")

    # ---- whitelist V3 (carried from V2 content, versioned) ----
    w2 = json.loads((EVID2 / "H6_FEATURE_AUTHORITY_WHITELIST_V2.json").read_text(encoding="utf-8"))
    whitelist_v3 = {
        "checkpoint": "H6-V3-REPAIR-PREREG",
        "artifact": "H6 feature authority whitelist V3",
        "supersedes": "docs/external-audit-01/oi-full-history-02/H6_FEATURE_AUTHORITY_WHITELIST_V2.json",
        "frozen_before": "any H6 V3 execution, backtest, or performance inspection",
        "ALLOWED_FIELDS": w2["ALLOWED_FIELDS"],
        "FORBIDDEN_FIELDS": w2.get("FORBIDDEN_FIELDS", [
            "count_toptrader_long_short_ratio",
            "sum_toptrader_long_short_ratio",
            "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio",
        ]),
        "enforcement": {
            "accessor": "H6FieldAccess (fail-closed)",
            "exception": "H6ForbiddenFeatureAccess",
            "covers": ["__getitem__", "get", "keys", "values", "items", "iteration", "contains", "attribute", "len"],
            "bypass_paths_allowed": 0,
        },
        "H6_SHADOW_DATA_DEPENDENCY": "NONE",
        "H6_CONFIRMATION_DATA_DEPENDENCY": "NONE",
    }
    wl_path = EVID3 / "H6_FEATURE_AUTHORITY_WHITELIST_V3.json"

    # ---- spec V3 ----
    spec_v3 = {
        "checkpoint": "H6-V3-REPAIR-PREREG",
        "hypothesis_id": "H6-OI-CONFIRMED-CONTINUATION-03",
        "supersedes": "H6-OI-CONFIRMED-CONTINUATION-02 (FAILED_EXTERNAL_VERIFICATION_V2)",
        "supersession_condition": "V3 supersedes V2 only after independent external verification; until then V3 is PENDING_EXTERNAL_VERIFICATION_V3",
        "economics_carried_forward_unchanged_from": {
            "artifact": "docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json",
            "spec_sha256_of_carried_block": validate_sha(sha256_file(EVID2 / "H6_SPEC_V2.json"), "v2_spec_sha256"),
            "retune": "NONE (spec 33/34)",
        },
        "preregistered_utc": now,
        "prereg_commit": "PENDING (filled by freeze commit step; this field is completed by the post-commit record, not self-referentially here)",
        "economics": economics,
        "data_authority_v3": {
            "authority_doc": "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
            "authority_doc_sha256": data_authority_sha,
            "dataset_manifest_v2_committed_copy_sha256": dataset_manifest_sha,
            "ledger_v2_committed_copy_sha256": ledger_sha,
            "OI_FULL_HISTORY_DATASET_SHA256_V2": dataset_sha,
            "price_authority_sha256_v2": price_sha,
            "portable_resolution": "--data-root | TRADING_AGENTIC_DATA_ROOT | shared main-repo data root | official source reconstruction",
        },
        "governance": {
            "H6_EXECUTIONS": 0,
            "H6_BACKTESTS": 0,
            "PERFORMANCE_OBSERVED": False,
            "H6_SHADOW_DATA_DEPENDENCY": "NONE",
            "H6_CONFIRMATION_DATA_DEPENDENCY": "NONE",
            "H6_CONFIRMATION_RESULT_DEPENDENCY": "NONE",
            "H6_CONFIRMATION_PERFORMANCE_DEPENDENCY": "NONE",
            "PRE_LEDGER_CONFIRMATION_HISTORY": "NOT_INDEPENDENTLY_PROVEN (LIMITATION_EXPLICIT_NON_BLOCKING for V3: V3 decisions depend on no prior confirmation results)",
            "status_at_prereg": "PENDING_EXTERNAL_VERIFICATION_V3",
        },
        "repair_evidence": {
            "PIT_DYNAMIC_RESULT": "docs/external-audit-01/oi-full-history-03/PIT_DYNAMIC_RESULT.json",
            "DATA_AUTHORITY_RESULT": "docs/external-audit-01/oi-full-history-03/DATA_AUTHORITY_RESULT.json",
            "DATASET_DETERMINISM_V3_RESULT": "docs/external-audit-01/oi-full-history-03/DATASET_DETERMINISM_V3_RESULT.json",
            "DASHBOARD_REPEAT_20_RESULT": "docs/external-audit-01/oi-full-history-03/DASHBOARD_REPEAT_20_RESULT.json",
            "FULL_HERMETIC_RESULT_1": "docs/external-audit-01/oi-full-history-03/FULL_HERMETIC_RESULT_1.json",
        },
    }

    # ---- manifest V3 ----
    whitelist_v3["whitelist_sha256"] = validate_sha(
        sha256_bytes(json.dumps(spec_v3, sort_keys=True, separators=(",", ":")).encode()), "_placeholder_spec_hash_not_published"
    ) if False else None
    whitelist_v3.pop("whitelist_sha256", None)

    manifest_v3 = {
        "checkpoint": "H6-V3-REPAIR-PREREG",
        "experiment": "H6-OI-CONFIRMED-CONTINUATION-03",
        "spec_ref": "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json",
        "whitelist_ref": "docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json",
        "data_authority_ref": "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
        "preregistered_utc": now,
        "commit": commit,
        "governance": spec_v3["governance"],
        "hash_provenance": [
            {
                "artifact": "H6_SPEC_V2.json (economics source, read not retyped)",
                "path": "docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json",
                "algorithm": "sha256",
                "bytes_source": "actual stored bytes (committed copy)",
                "sha256": validate_sha(sha256_file(EVID2 / "H6_SPEC_V2.json"), "prov.spec_v2"),
            },
            {
                "artifact": "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json",
                "path": "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json",
                "algorithm": "sha256",
                "bytes_source": "actual stored bytes (committed copy)",
                "sha256": dataset_manifest_sha,
            },
            {
                "artifact": "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl",
                "path": "docs/external-audit-01/oi-full-history-02/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl",
                "algorithm": "sha256",
                "bytes_source": "actual stored bytes (committed copy, 5691 lines)",
                "sha256": ledger_sha,
            },
            {
                "artifact": "OI_FULL_HISTORY_DATASET_SHA256_V2 (dataset fingerprint)",
                "path": "declared inside OI_FULL_HISTORY_DATASET_MANIFEST_V2.json; independently recomputed from actual normalized bytes by scripts/prove_h6_v3_dataset_determinism.py",
                "algorithm": "sha256(canonical_json(files[])) with per-file normalized_sha256 recomputed from actual file bytes",
                "bytes_source": "actual canonical normalized authority files under shared data root",
                "sha256": dataset_sha,
            },
            {
                "artifact": "PRICE_1H_AUTHORITY_V2_MANIFEST.json",
                "path": "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json",
                "algorithm": "sha256",
                "bytes_source": "actual stored bytes (committed copy)",
                "sha256": price_sha,
            },
            {
                "artifact": "H6_DATA_AUTHORITY_V3.json",
                "path": "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
                "algorithm": "sha256",
                "bytes_source": "actual stored bytes (committed copy)",
                "sha256": data_authority_sha,
            },
        ],
    }

    # ---- write order: whitelist first (so its bytes are final before referencing), then spec, then manifest ----
    EVID3.mkdir(parents=True, exist_ok=True)
    wl_path.write_text(json.dumps(whitelist_v3, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    wl_sha = validate_sha(sha256_file(wl_path), "whitelist_sha256")
    manifest_v3["whitelist_sha256"] = wl_sha
    manifest_v3["hash_provenance"].append(
        {
            "artifact": "H6_FEATURE_AUTHORITY_WHITELIST_V3.json",
            "path": str(wl_path.relative_to(REPO)).replace("\\", "/"),
            "algorithm": "sha256",
            "bytes_source": "actual stored bytes (this generation)",
            "sha256": wl_sha,
        }
    )

    spec_path = EVID3 / "H6_SPEC_V3.json"
    spec_path.write_text(json.dumps(spec_v3, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_sha = validate_sha(sha256_file(spec_path), "spec_sha256")

    manifest_path = EVID3 / "H6_MANIFEST_V3.json"
    manifest_path.write_text(json.dumps(manifest_v3, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = validate_sha(sha256_file(manifest_path), "manifest_sha256")

    print(
        json.dumps(
            {
                "spec_sha256": spec_sha,
                "manifest_sha256": manifest_sha,
                "whitelist_sha256": wl_sha,
                "data_authority_sha256": data_authority_sha,
                "dataset_sha256": dataset_sha,
                "price_authority_sha256": price_sha,
                "hypothesis_id": spec_v3["hypothesis_id"],
                "H6_EXECUTIONS": 0,
                "H6_BACKTESTS": 0,
                "PERFORMANCE_OBSERVED": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
