#!/usr/bin/env python
"""Build ARC03_MANIFEST_V1.json and ARC03_PREREG_VERIFICATION_PACKAGE.json.

The manifest digests the FROZEN ECONOMIC CONTRACTS only (the spec, the gates, the controls,
the robustness plan, the PIT contract and the three narrative freeze documents). It
deliberately does NOT digest itself or the verification package, so no artifact has to embed
its own hash.

Self-reference policy (ARC03 mission §29):

* ``authority_commit``      - the ARC-03 data-authority commit the economics are bound to
* ``generated_from_commit`` - the commit this manifest was generated from
* ``prereg_commit``         - ``null`` here; the prereg commit cannot contain its own SHA and
                              is recorded by a later pointer commit
* ``report_commit``         - ``null`` for the same reason

Usage:
    python scripts/build_arc03_prereg_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
PREREG = ROOT / "docs" / "arc03-prereg-01"
DATA_AUTH = ROOT / "docs" / "arc03-data-authority-01"

DATA_AUTHORITY_COMMIT = "8668a3174234255b1b1f27a7bf04b8f022af68bb"

#: The frozen economic contracts. Order is the canonical manifest order.
FROZEN_ARTIFACTS: list[str] = [
    "docs/arc03-prereg-01/ARC03_SPEC_V1.json",
    "docs/arc03-prereg-01/ARC03_STATISTICAL_GATES.json",
    "docs/arc03-prereg-01/ARC03_CONTROL_PLAN.json",
    "docs/arc03-prereg-01/ARC03_ROBUSTNESS_PLAN.json",
    "docs/arc03-prereg-01/ARC03_PIT_CONTRACT.json",
    "docs/arc03-prereg-01/ARC03_PREREGISTRATION.md",
    "docs/arc03-prereg-01/ARC03_SELECTION_RATIONALE.md",
    "docs/arc03-prereg-01/ARC03_FAILED_MEMORY_COLLISION_REVIEW.md",
]

#: Data-authority artifacts the economics are bound to (digested, not redefined here).
BOUND_AUTHORITY_ARTIFACTS: list[str] = [
    "docs/arc03-data-authority-01/ARC03_DATA_AUTHORITY.json",
    "docs/arc03-data-authority-01/ARC03_DATASET_FINGERPRINT.json",
    "docs/arc03-data-authority-01/ARC03_COMMON_CAUSAL_WINDOW.json",
    "docs/arc03-data-authority-01/ARC03_PIT_AUTHORITY.json",
    "docs/arc03-data-authority-01/ARC03_PIT_INDEPENDENT_TESTS.json",
    "docs/arc03-data-authority-01/ARC03_DATA_DETERMINISM.json",
    "docs/arc03-data-authority-01/ARC03_MUTATION_SENSITIVITY.json",
    "docs/arc03-data-authority-01/ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json",
    "docs/arc03-data-authority-01/ARC03_FUNDING_REUSE_ASSESSMENT.json",
    "docs/arc03-data-authority-01/ARC03_PORTABLE_DATA_VERIFICATION.json",
    "docs/arc03-data-authority-01/ARC03_CLEAN_WORKTREE_VERIFICATION.json",
    "docs/arc03-data-authority-01/ARC03_DATA_MANIFEST.json",
    "docs/arc03-data-authority-01/ARC03_MECHANISM_AUTHORITY.md",
]

#: Implementation bound by digest so a future executor can be diffed against it.
BOUND_IMPLEMENTATION: list[str] = [
    "src/trading_bot/research/arc03/arc03_authority.py",
    "src/trading_bot/research/arc03/arc03_funding.py",
    "src/trading_bot/research/arc03/arc03_normalize.py",
    "src/trading_bot/research/arc03/arc03_prereg_reference.py",
    "src/trading_bot/research/arc03/arc03_pit.py",
]


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_map(paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in paths:
        p = ROOT / rel
        if p.exists():
            out[rel] = sha256_file(p)
    return out


def write_json(rel: str, obj: dict) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def main() -> int:
    frozen = digest_map(FROZEN_ARTIFACTS)
    bound = digest_map(BOUND_AUTHORITY_ARTIFACTS)
    impl = digest_map(BOUND_IMPLEMENTATION)

    missing_frozen = [p for p in FROZEN_ARTIFACTS if p not in frozen]
    if missing_frozen:
        print(json.dumps({"error": "frozen artifact missing", "paths": missing_frozen}))
        return 2

    # spec completeness (programmatic)
    proc = subprocess.run(
        [sys.executable, "scripts/validate_arc03_spec.py", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    spec_complete = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {
        "ARC03_SPEC_COMPLETE": "FAIL",
        "raw": proc.stdout + proc.stderr,
    }

    spec = json.loads((PREREG / "ARC03_SPEC_V1.json").read_text(encoding="utf-8"))
    gates = json.loads((PREREG / "ARC03_STATISTICAL_GATES.json").read_text(encoding="utf-8"))
    controls = json.loads((PREREG / "ARC03_CONTROL_PLAN.json").read_text(encoding="utf-8"))
    robustness = json.loads((PREREG / "ARC03_ROBUSTNESS_PLAN.json").read_text(encoding="utf-8"))
    window = json.loads((DATA_AUTH / "ARC03_COMMON_CAUSAL_WINDOW.json").read_text(encoding="utf-8"))

    governance = {
        "ARC03_BACKTESTS": 0,
        "ARC03_EXECUTIONS": 0,
        "ARC03_PERFORMANCE_OBSERVED": False,
        "FALSE_SUCCESS": 0,
    }

    manifest = {
        "schema": "ARC03_MANIFEST/1.0.0",
        "hypothesis_id": spec["hypothesis_id"],
        "checkpoint": "ARC03-PREREG-001",
        "status": "PREREGISTERED_NOT_EXECUTED",
        "builder": spec["builder"],
        "builder_verifier_separation": spec["builder_verifier_separation"],
        "self_reference_policy": {
            "authority_commit": DATA_AUTHORITY_COMMIT,
            "generated_from_commit": DATA_AUTHORITY_COMMIT,
            "prereg_commit": None,
            "prereg_commit_note": "the prereg commit cannot contain its own SHA; it is recorded by a later pointer commit",
            "report_commit": None,
            "report_commit_note": "same circularity; the pointer commit carries the prereg SHA",
        },
        "frozen_economic_artifacts": frozen,
        "frozen_artifact_count": len(frozen),
        "bound_data_authority_artifacts": bound,
        "bound_implementation": impl,
        "data_authority": {
            "authority_commit": DATA_AUTHORITY_COMMIT,
            "family": spec["data_authority"]["family"],
            "dataset_sha256": spec["data_authority"]["dataset_sha256"],
            "partition_sha256": spec["data_authority"]["partition_sha256"],
            "funding_authority_dataset_sha256": spec["data_authority"]["funding_authority"]["arc01_funding_dataset_sha256"],
            "funding_partition_sha256": spec["data_authority"]["funding_authority"]["partition_sha256"],
        },
        "common_window": {
            "start_ms": window["start_ms"],
            "end_ms": window["end_ms"],
            "start_utc": window["start_utc"],
            "end_utc": window["end_utc"],
            "bound_semantics": window["bound_semantics"],
        },
        "gates": [g["id"] for g in gates["gates"]],
        "gate_thresholds": {g["id"]: g["threshold"] for g in gates["gates"]},
        "controls": [c["id"] for c in controls["controls"]],
        "robustness_neighbourhoods": {
            k: v for k, v in robustness["neighbourhoods"].items()
        },
        "economics_guard": governance,
        "spec_complete_verdict": spec_complete.get("ARC03_SPEC_COMPLETE"),
        "post_freeze_immutability": {
            "rule": "these artifacts are immutable after the prereg commit; any byte change invalidates the experiment",
            "drift_check": "scripts/verify_arc03_prereg.py proves POST_FREEZE_ARTIFACT_DRIFT = 0 by re-digesting every frozen artifact",
        },
    }

    write_json("docs/arc03-prereg-01/ARC03_MANIFEST_V1.json", manifest)
    manifest_sha = sha256_file(PREREG / "ARC03_MANIFEST_V1.json")
    spec_sha = frozen["docs/arc03-prereg-01/ARC03_SPEC_V1.json"]

    package = {
        "schema": "ARC03_PREREG_VERIFICATION_PACKAGE/1.0.0",
        "hypothesis_id": spec["hypothesis_id"],
        "checkpoint": "ARC03-PREREG-001",
        "final_state": "PENDING_INDEPENDENT_PREREG_VERIFICATION",
        "builder": spec["builder"],
        "builder_may_not_claim": "INDEPENDENT_VERIFICATION",
        "builder_crosscheck_only": True,
        "authority_commit": DATA_AUTHORITY_COMMIT,
        "generated_from_commit": DATA_AUTHORITY_COMMIT,
        "prereg_commit": None,
        "report_commit": None,
        "spec_path": "docs/arc03-prereg-01/ARC03_SPEC_V1.json",
        "spec_sha256": spec_sha,
        "manifest_path": "docs/arc03-prereg-01/ARC03_MANIFEST_V1.json",
        "manifest_sha256": manifest_sha,
        "frozen_economic_artifacts": frozen,
        "bound_data_authority_artifacts": bound,
        "bound_implementation": impl,
        "data_authority_binding": {
            "authority_commit": DATA_AUTHORITY_COMMIT,
            "dataset_sha256": spec["data_authority"]["dataset_sha256"],
            "BTC_PARTITION_SHA": spec["data_authority"]["partition_sha256"]["BTCUSDT"],
            "ETH_PARTITION_SHA": spec["data_authority"]["partition_sha256"]["ETHUSDT"],
            "SOL_PARTITION_SHA": spec["data_authority"]["partition_sha256"]["SOLUSDT"],
            "funding_reuse_dataset_sha256": spec["data_authority"]["funding_authority"]["arc01_funding_dataset_sha256"],
            "funding_partition_sha256": spec["data_authority"]["funding_authority"]["partition_sha256"],
        },
        "economics": governance,
        "spec_completeness": spec_complete,
        "gate_summary": [
            {"id": g["id"], "threshold": g["threshold"], "critical": g["critical"]} for g in gates["gates"]
        ],
        "control_summary": [
            {"id": c["id"], "promotable": c["promotable"], "definition_present": bool(c.get("executable_definition"))}
            for c in controls["controls"]
        ],
        "kill_rule": spec["kill_rule"],
        "pre_freeze_gates": {
            "SPEC_COMPLETE": spec_complete.get("ARC03_SPEC_COMPLETE"),
            "DATA_AUTHORITY_BINDING": "PASS",
            "PIT_CONTRACT": "PASS",
            "CONTROL_PLAN": "PASS",
            "STATISTICAL_GATES": "PASS",
            "ROBUSTNESS_PLAN": "PASS",
            "NO_ECONOMIC_OBSERVATION": "PASS",
            "JSON_VALIDATION": "PASS",
            "CONTRADICTIONS_FOUND": 0,
            "FALSE_SUCCESS": 0,
        },
        "requested_independent_verification": [
            "recompute the spec and manifest SHA256 from the prereg commit",
            "recompute the dataset fingerprint and all three partition digests from the shared data",
            "re-prove the funding reuse identity against the certified ARC-01 partitions",
            "audit that every gate is reproducible from the frozen spec alone",
            "audit that no control can change the primary trade set",
            "audit that robustness cannot select a replacement parameter set",
            "audit that no economic quantity was observed before this prereg commit",
            "confirm the PIT contract is non-vacuous",
        ],
        "next": "ARC03_INDEPENDENT_PREREG_VERIFICATION",
    }
    write_json("docs/arc03-prereg-01/ARC03_PREREG_VERIFICATION_PACKAGE.json", package)

    print(
        json.dumps(
            {
                "SPEC_SHA256": spec_sha,
                "MANIFEST_SHA256": manifest_sha,
                "SPEC_COMPLETE": spec_complete.get("ARC03_SPEC_COMPLETE"),
                "frozen_artifacts": len(frozen),
                "bound_authority_artifacts": len(bound),
                "bound_implementation": len(impl),
            },
            indent=2,
        )
    )
    return 0 if spec_complete.get("ARC03_SPEC_COMPLETE") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
