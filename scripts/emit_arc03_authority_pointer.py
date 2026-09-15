#!/usr/bin/env python
"""Emit the ARC-03 data-authority commit pointer (non-circular commit semantics).

The manifest cannot contain the SHA of the commit that introduces it, so this artifact —
written *after* that commit — records the commit identity and the Git blob OIDs of the
frozen authority artifacts. Nothing here changes the frozen dataset digest.

Semantics (same convention as the ARC-01 data authority):
    generated_from_commit : the base the authority was generated from
    authority_commit      : the commit that introduced the frozen authority artifacts
    report_commit         : the commit that carries this pointer (null when unknown)

Usage:
    python scripts/emit_arc03_authority_pointer.py --authority-commit <sha>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "arc03-data-authority-01"

ARTIFACTS = [
    "ARC03_DATA_MANIFEST.json",
    "ARC03_DATASET_FINGERPRINT.json",
    "ARC03_DATA_AUTHORITY.json",
    "ARC03_DATA_QUALITY_LEDGER.jsonl",
    "ARC03_RAW_LEDGER.jsonl",
    "ARC03_COMMON_CAUSAL_WINDOW.json",
    "ARC03_PIT_AUTHORITY.json",
    "ARC03_PIT_INDEPENDENT_TESTS.json",
    "ARC03_DATA_DETERMINISM.json",
    "ARC03_MUTATION_SENSITIVITY.json",
    "ARC03_PROVIDER_COVERAGE.json",
    "ARC03_PROVIDER_COVERAGE_SUPPLEMENT.json",
    "ARC03_DATA_INVENTORY.json",
    "ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json",
    "ARC03_BASE_SELECTION.json",
    "ARC03_MECHANISM_AUTHORITY.md",
    "ARC03_SOURCE_REGISTRY.md",
]


def git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return out.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authority-commit", required=True)
    args = ap.parse_args()

    commit = args.authority_commit
    manifest = json.loads((DOCS / "ARC03_DATA_MANIFEST.json").read_text(encoding="utf-8"))
    blobs = {}
    for name in ARTIFACTS:
        rel = f"docs/arc03-data-authority-01/{name}"
        oid = git("rev-parse", f"{commit}:{rel}")
        blobs[name] = {
            "blob_oid": oid or None,
            "present_at_authority_commit": bool(oid),
            "sha256": None,
        }
    pointer = {
        "checkpoint": "ARC03-DATA-002",
        "generated_from_commit": manifest.get("generated_from_commit"),
        "authority_commit": commit,
        "report_commit": None,
        "authority_commit_subject": git("log", "-1", "--format=%s", commit),
        "frozen_identity": {
            "dataset_sha256": manifest["dataset_sha256"],
            "raw_files_sha256": manifest["raw_files_sha256"],
            "daily_supplements_sha256": manifest["daily_supplements_sha256"],
            "partition_sha256": manifest["partition_sha256"],
            "schema_version": manifest["schema_version"],
            "normalizer_version": manifest["normalizer_version"],
        },
        "artifact_blobs": blobs,
        "family": manifest["family"],
        "assets": list(manifest["partition_sha256"].keys()),
        "note": (
            "ARCO3_DATA_MANIFEST.json deliberately records authority_commit = null and "
            "report_commit = null: a commit cannot contain its own SHA. This pointer carries "
            "the commit identity without altering the frozen dataset digest."
        ),
        "arc03_backtests": 0,
        "arc03_executions": 0,
        "arc03_performance_observed": False,
    }
    (DOCS / "ARC03_AUTHORITY_COMMIT_POINTER.json").write_bytes(
        (json.dumps(pointer, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(json.dumps({"authority_commit": commit, "artifacts": len(blobs)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
