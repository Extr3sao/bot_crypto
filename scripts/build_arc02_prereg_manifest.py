"""ARC-02 preregistration manifest builder.

Freezes the digest of every preregistration artifact and of the data-authority binding,
so post-freeze drift is detectable by anyone (including an independent verifier).

    python scripts/build_arc02_prereg_manifest.py
    python scripts/build_arc02_prereg_manifest.py --check     # drift check only

The manifest is DETERMINISTIC: it contains no runtime clock reading and no machine-specific
absolute path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PREREG_DIR = REPO / "docs" / "arc02-prereg-01"
DATA_DIR = REPO / "docs" / "arc02-data-authority-01"
MANIFEST_PATH = PREREG_DIR / "ARC02_MANIFEST_V1.json"
PREREGISTERED_UTC = "2026-09-19"

#: Frozen economic artifacts: these MAY NOT change after the freeze.
FROZEN_ECONOMIC = [
    "docs/arc02-prereg-01/ARC02_SPEC_V1.json",
    "docs/arc02-prereg-01/ARC02_STATISTICAL_GATES.json",
    "docs/arc02-prereg-01/ARC02_CONTROL_PLAN.json",
    "docs/arc02-prereg-01/ARC02_PIT_CONTRACT.json",
    "docs/arc02-prereg-01/ARC02_ROBUSTNESS_PLAN.json",
    "docs/arc02-prereg-01/ARC02_MECHANISM_AUTHORITY.md",
    "docs/arc02-prereg-01/ARC02_SELECTION_RATIONALE.md",
    "docs/arc02-prereg-01/ARC02_FAILED_MEMORY_COLLISION_REVIEW.md",
    "docs/arc02-prereg-01/ARC02_PREREGISTRATION.md",
    "docs/arc02-data-authority-01/ARC02_DATA_AUTHORITY.json",
    "docs/arc02-data-authority-01/ARC02_DATA_MANIFEST.json",
    "docs/arc02-data-authority-01/ARC02_DATASET_FINGERPRINT.json",
    "docs/arc02-data-authority-01/ARC02_COMMON_CAUSAL_WINDOW.json",
    "docs/arc02-data-authority-01/ARC02_PIT_AUTHORITY.json",
    "docs/arc02-data-authority-01/ARC02_PIT_INDEPENDENT_TESTS.json",
    "src/trading_bot/research/arc02/arc02_authority.py",
    "src/trading_bot/research/arc02/arc02_normalize.py",
    "src/trading_bot/research/arc02/arc02_funding.py",
    "src/trading_bot/research/arc02/arc02_pit.py",
]

#: Non-economic bookkeeping artifacts: these MAY be added/updated after the freeze.
MUTABLE_AFTER_FREEZE = [
    "docs/arc02-prereg-01/ARC02_MANIFEST_V1.json",
    "docs/arc02-prereg-01/ARC02_PREREG_VERIFICATION_PACKAGE.json",
    "docs/arc02-prereg-01/ARC02_RESUME_STATE.json",
    "docs/arc02-prereg-01/ARC02_PREREG_COMMIT_POINTER.json",
    "docs/arc02-prereg-01/RUN_REPORT.json",
    "docs/arc02-prereg-01/RUN_REPORT.md",
    "docs/arc02-data-authority-01/ARC02_PORTABLE_DATA_VERIFICATION.json",
    "docs/arc02-data-authority-01/ARC02_DATA_INVENTORY.json",
    "docs/arc02-data-authority-01/ARC02_DATA_DETERMINISM.json",
    "docs/arc02-data-authority-01/ARC02_MUTATION_SENSITIVITY.json",
    "docs/arc02-data-authority-01/ARC02_REUSE_ASSESSMENT.json",
    "docs/arc02-data-authority-01/ARC02_RAW_LEDGER.jsonl",
    "docs/arc02-data-authority-01/ARC02_DATA_QUALITY_LEDGER.jsonl",
    "docs/arc02-data-authority-01/ARC02_SOURCE_REGISTRY.md",
]


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_map(rel_paths: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rel in rel_paths:
        path = REPO / rel
        out[rel] = {
            "sha256": sha256_file(path) if path.exists() else None,
            "size_bytes": path.stat().st_size if path.exists() else None,
        }
    return out


def aggregate(digests: dict[str, Any]) -> str:
    payload = json.dumps(
        {k: v["sha256"] for k, v in sorted(digests.items())}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build() -> dict[str, Any]:
    frozen = digest_map(FROZEN_ECONOMIC)
    mutable = digest_map(MUTABLE_AFTER_FREEZE)
    authority = json.loads((DATA_DIR / "ARC02_DATA_AUTHORITY.json").read_text(encoding="utf-8"))
    spec = json.loads((PREREG_DIR / "ARC02_SPEC_V1.json").read_text(encoding="utf-8"))
    missing = [k for k, v in frozen.items() if v["sha256"] is None]
    if missing:
        raise SystemExit(f"FAIL_CLOSED: frozen artifact(s) missing: {missing}")
    return {
        "schema": "ARC02_MANIFEST/1.0.0",
        "checkpoint": "ARC02-PREREG-001",
        "hypothesis_id": "ARC-02-BTC-ALT-LEAD-LAG-01",
        "preregistered_utc": PREREGISTERED_UTC,
        "status": "FROZEN_PENDING_INDEPENDENT_PREREG_VERIFICATION",
        "frozen_economic_artifacts": frozen,
        "frozen_economic_aggregate_sha256": aggregate(frozen),
        "post_freeze_mutable_bookkeeping_artifacts": mutable,
        "data_binding": {
            "dataset_sha256": authority["dataset_sha256"],
            "partition_sha256": authority["partition_sha256"],
            "source_authority_dataset_sha256": authority["reuse"]["source_dataset_sha256"],
            "common_window": [authority["common_causal_window"]["start_ms"], authority["common_causal_window"]["end_ms"]],
            "authority_role": authority["authority_role"],
        },
        "economics_guards_at_freeze": {
            "ARC02_BACKTESTS": 0,
            "ARC02_EXECUTIONS": 0,
            "ARC02_PERFORMANCE_OBSERVED": False,
            "FALSE_SUCCESS": 0,
        },
        "spec_digest_reference": {
            "ARC02_SPEC_V1.json": frozen["docs/arc02-prereg-01/ARC02_SPEC_V1.json"]["sha256"],
            "spec_version": spec["spec_version"],
            "CRITICAL_SPEC_INCOMPLETENESS": spec["CRITICAL_SPEC_INCOMPLETENESS"],
        },
        "freeze_rules": {
            "no_economic_artifact_may_change_after_this_manifest": True,
            "no_runtime_default_may_define_economic_behaviour": True,
            "drift_detection": "recompute the frozen_economic_artifacts digests and compare to this manifest; any mismatch is POST_FREEZE_ARTIFACT_DRIFT > 0 and invalidates the experiment",
        },
    }


def check() -> int:
    if not MANIFEST_PATH.exists():
        print("FAIL_CLOSED: no manifest")
        return 2
    recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    observed = digest_map(FROZEN_ECONOMIC)
    drift = {
        rel: {"recorded": recorded["frozen_economic_artifacts"].get(rel, {}).get("sha256"), "observed": v["sha256"]}
        for rel, v in observed.items()
        if recorded["frozen_economic_artifacts"].get(rel, {}).get("sha256") != v["sha256"]
    }
    agg = aggregate(observed)
    print(
        json.dumps(
            {
                "POST_FREEZE_ARTIFACT_DRIFT": len(drift),
                "drifted": drift,
                "frozen_economic_aggregate_sha256": agg,
                "recorded_aggregate_sha256": recorded["frozen_economic_aggregate_sha256"],
                "aggregate_match": agg == recorded["frozen_economic_aggregate_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not drift and agg == recorded["frozen_economic_aggregate_sha256"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        return check()
    manifest = build()
    MANIFEST_PATH.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(
        json.dumps(
            {
                "manifest": str(MANIFEST_PATH.relative_to(REPO)).replace("\\", "/"),
                "frozen_artifacts": len(manifest["frozen_economic_artifacts"]),
                "frozen_economic_aggregate_sha256": manifest["frozen_economic_aggregate_sha256"],
                "dataset_sha256": manifest["data_binding"]["dataset_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
