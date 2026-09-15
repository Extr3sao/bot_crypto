#!/usr/bin/env python
"""ARC-03 preregistration verification (portable, read-only, fail-closed).

Proves two things without trusting any builder summary:

1. **POST_FREEZE_ARTIFACT_DRIFT = 0** - every frozen economic artifact is re-digested and
   compared against the digest recorded in ``ARC03_MANIFEST_V1.json``; the manifest and spec
   digests are compared against the ones recorded in ``ARC03_PREREG_VERIFICATION_PACKAGE.json``.
2. **SPEC_COMPLETE** - the frozen spec passes the programmatic completeness validator.

With ``--data-root`` it additionally re-hashes the certified participation partitions and the
reused funding partitions and compares them against the frozen fingerprints. A wrong or
incomplete data root FAILS CLOSED (exit 2) instead of being trusted. Without ``--data-root``
the drift and completeness checks still run, because those artifacts are git-tracked.

Exit codes: 0 = PASS, 2 = FAIL_CLOSED / drift detected.

Usage:
    python scripts/verify_arc03_prereg.py [--data-root ABS_PATH] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
PREREG = ROOT / "docs" / "arc03-prereg-01"
MANIFEST = PREREG / "ARC03_MANIFEST_V1.json"
PACKAGE = PREREG / "ARC03_PREREG_VERIFICATION_PACKAGE.json"
SPEC = PREREG / "ARC03_SPEC_V1.json"

PARTITION_RELPATH = pathlib.Path("data") / "processed" / "arc03_klines_5m"
FUNDING_RELPATH = pathlib.Path("data") / "processed" / "arc03_funding"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    failed: list[dict] = []
    checks: list[str] = []

    if not MANIFEST.exists() or not PACKAGE.exists() or not SPEC.exists():
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": "prereg artifacts missing"}))
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))

    # --- 1. frozen artifact drift ------------------------------------------------------
    drift: dict[str, dict] = {}
    for rel, expected in manifest["frozen_economic_artifacts"].items():
        path = ROOT / rel
        if not path.exists():
            drift[rel] = {"expected": expected, "actual": "MISSING"}
            continue
        actual = sha256_file(path)
        if actual != expected:
            drift[rel] = {"expected": expected, "actual": actual}
    if drift:
        failed.append({"check": "frozen_artifact_drift", "mismatches": drift})
    checks.append("frozen_artifact_digests")

    # --- 2. manifest + spec digests vs the package -------------------------------------
    manifest_sha = sha256_file(MANIFEST)
    if package.get("manifest_sha256") != manifest_sha:
        failed.append(
            {
                "check": "manifest_digest_mismatch",
                "expected": package.get("manifest_sha256"),
                "actual": manifest_sha,
            }
        )
    spec_sha = sha256_file(SPEC)
    if package.get("spec_sha256") != spec_sha:
        failed.append({"check": "spec_digest_mismatch", "expected": package.get("spec_sha256"), "actual": spec_sha})
    checks.append("manifest_and_spec_digests")

    # --- 3. bound implementation + bound authority drift -------------------------------
    for group in ("bound_implementation", "bound_data_authority_artifacts"):
        group_drift: dict[str, dict] = {}
        for rel, expected in manifest.get(group, {}).items():
            path = ROOT / rel
            if not path.exists():
                group_drift[rel] = {"expected": expected, "actual": "MISSING"}
                continue
            actual = sha256_file(path)
            if actual != expected:
                group_drift[rel] = {"expected": expected, "actual": actual}
        if group_drift:
            failed.append({"check": f"{group}_drift", "mismatches": group_drift})
        checks.append(group)

    # --- 4. spec completeness ----------------------------------------------------------
    proc = subprocess.run(
        [sys.executable, "scripts/validate_arc03_spec.py", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.stdout.strip().startswith("{"):
        spec_record = json.loads(proc.stdout)
    else:
        spec_record = {"ARC03_SPEC_COMPLETE": "FAIL", "raw": proc.stdout + proc.stderr}
    if spec_record.get("ARC03_SPEC_COMPLETE") != "PASS":
        failed.append({"check": "spec_incomplete", "detail": spec_record.get("failures")})
    checks.append("spec_completeness")

    # --- 5. economics guard ------------------------------------------------------------
    guard = package.get("economics", {})
    if guard.get("ARC03_BACKTESTS") != 0 or guard.get("ARC03_EXECUTIONS") != 0:
        failed.append({"check": "economic_execution_recorded_at_prereg", "guard": guard})
    if guard.get("ARC03_PERFORMANCE_OBSERVED") is not False:
        failed.append({"check": "performance_observed_at_prereg", "guard": guard})
    checks.append("economics_guard")

    # --- 6. optional portable data binding (fails closed) ------------------------------
    data_binding = None
    if args.data_root is not None:
        base = pathlib.Path(args.data_root)
        if not base.is_absolute():
            print(json.dumps({"verdict": "FAIL_CLOSED", "reason": "data root must be absolute"}))
            return 2
        mismatches: dict[str, str] = {}
        parts = base / PARTITION_RELPATH
        for symbol, expected in package["data_authority_binding"].items():
            if not symbol.endswith("USDT") or symbol.endswith("_SHA"):
                continue
            p = parts / f"{symbol}.jsonl"
            mismatches[symbol] = sha256_file(p) if p.exists() else "MISSING"
        expected_parts = {
            "BTCUSDT": package["data_authority_binding"]["BTC_PARTITION_SHA"],
            "ETHUSDT": package["data_authority_binding"]["ETH_PARTITION_SHA"],
            "SOLUSDT": package["data_authority_binding"]["SOL_PARTITION_SHA"],
        }
        bad = {k: v for k, v in mismatches.items() if v != expected_parts.get(k)}
        if bad:
            failed.append({"check": "participation_partition_mismatch", "mismatches": bad})

        fund = base / FUNDING_RELPATH
        fund_expected = package["data_authority_binding"]["funding_partition_sha256"]
        fund_actual = {}
        for symbol, expected in fund_expected.items():
            p = fund / f"{symbol}_funding.jsonl"
            actual = sha256_file(p) if p.exists() else "MISSING"
            fund_actual[symbol] = actual
        bad_fund = {k: v for k, v in fund_actual.items() if v != fund_expected.get(k)}
        if bad_fund:
            failed.append({"check": "funding_partition_mismatch", "mismatches": bad_fund})

        data_binding = {
            "data_root": str(base),
            "participation_partition_sha256": mismatches,
            "funding_partition_sha256": fund_actual,
            "matches_frozen_authority": not bad and not bad_fund,
        }
        checks.append("portable_data_binding")

    verdict = "PASS" if not failed else "FAIL_CLOSED"
    record = {
        "schema": "ARC03_PREREG_VERIFICATION/1.0.0",
        "checks_executed": checks,
        "spec_sha256": spec_sha,
        "manifest_sha256": manifest_sha,
        "frozen_artifacts_checked": len(manifest["frozen_economic_artifacts"]),
        "POST_FREEZE_ARTIFACT_DRIFT": 0 if not any(f["check"].endswith("drift") for f in failed) else len(failed),
        "SPEC_COMPLETE": spec_record.get("ARC03_SPEC_COMPLETE"),
        "data_binding": data_binding,
        "failures": failed,
        "verdict": verdict,
    }
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(f"verdict = {verdict}")
        print(f"  SPEC_COMPLETE = {record['SPEC_COMPLETE']}")
        print(f"  POST_FREEZE_ARTIFACT_DRIFT = {record['POST_FREEZE_ARTIFACT_DRIFT']}")
        for f in failed:
            print(f"  FAIL {f}")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
