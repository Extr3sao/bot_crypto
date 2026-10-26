"""Build EVIDENCE_MANIFEST.json for RFC-TAP-CI-003.

This is the authoring step: it records the digest of every artefact the report
rests on. It is deliberately *not* run by the verifier, so a verifier that hashes
whatever it finds cannot silently bless a rewritten file: the manifest is the
claim, and `verify_report.py` checks the claim against the tree.

The manifest does not hash itself or INDEPENDENT_VERIFICATION.json (which is an
output of the verification); the verification records their digests instead.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1]
ROOT = REPORT.parents[2]

CODE = (
    "scripts/active_economic_audit.py",
    "tests/unit/research/test_cost_barrier_gate.py",
    "tests/unit/research/test_cost_barrier_ci_parity.py",
    "tests/unit/research/test_recovery_ci_parity.py",
    ".github/workflows/cost-barrier-gate.yml",
    ".github/workflows/recovery-determinism.yml",
)

DATA = (
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.md",
    "data/recovery/COST_BARRIER_EXPLORER.json",
    "data/recovery/COST_BARRIER_EXPLORER.md",
    "data/recovery/COST_BARRIER_VERIFICATION.json",
    "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json",
    "data/recovery/wp7/evidence/COST_BARRIER.json",
    "data/recovery/wp7/evidence/INPUT_EVIDENCE.json",
    "data/recovery/wp7/evidence/PRODUCER_PINS.json",
    "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json",
    "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.md",
    "data/recovery/INDEPENDENT_VERIFICATION.json",
)

EVIDENCE = (
    "evidence/pytest_final.txt",
    "evidence/audit_check.json",
    "evidence/evidence_bundle.json",
    "evidence/gate_report.json",
    "evidence/cost_barrier_verify.json",
    "evidence/recovery_verify.json",
    "evidence/ci_runs.json",
    "evidence/certification_local_run.log",
    "evidence/gate_console.txt",
    "evidence/evidence_console.txt",
)

REPORT_DOCS = (
    "BASELINE.md",
    "CHANGELOG.md",
    "TEST_RESULTS.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(root: Path, rel: str) -> dict[str, object]:
    path = root / rel
    data = path.read_bytes()
    return {
        "path": rel,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha256_lf": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest(),
    }


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main() -> int:
    report_rel = REPORT.relative_to(ROOT).as_posix()
    groups = {
        "code_and_workflows": [entry(ROOT, rel) for rel in CODE],
        "published_artefacts": [entry(ROOT, rel) for rel in DATA],
        # every path is stored relative to the repository root, so a verifier has one
        # base to resolve against and cannot silently look in the wrong directory
        "run_evidence": [entry(ROOT, f"{report_rel}/{rel}") for rel in EVIDENCE],
        "report_documents": [entry(ROOT, f"{report_rel}/{rel}") for rel in REPORT_DOCS],
    }
    manifest = {
        "artifact": "RFC_TAP_CI_003_EVIDENCE_MANIFEST",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_commit": "a83ac16532f2a8b5ea131b25910d4b57abf9fe0e",
        "tested_commit": "63950a7295d7659fffe894e49d6fa5624d1280a2",
        "head_when_built": git("rev-parse", "HEAD"),
        "convention": (
            "sha256 over the bytes on disk; sha256_lf over the same bytes with CRLF "
            "normalised to LF, so a checkout that rewrites line endings is not mistaken "
            "for changed content"
        ),
        "groups": groups,
        "self_reference": {
            "excluded": ["EVIDENCE_MANIFEST.json", "INDEPENDENT_VERIFICATION.json"],
            "why": (
                "a manifest cannot contain its own digest; the verification records the "
                "digest of this manifest and of FINAL_REPORT.{json,md} instead"
            ),
        },
        "files_total": sum(len(rows) for rows in groups.values()),
    }
    out = REPORT / "EVIDENCE_MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)} ({manifest['files_total']} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
