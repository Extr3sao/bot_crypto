"""POST-FREEZE: generate the non-economic H6 V4 runtime authority binding.

Prereg-commit circularity, resolved cleanly:

* PRE-FREEZE  — no binding exists, so ``runtime_authority.current_binding()`` raises and
  the runtime is UNBOUND_PRE_FREEZE / fail-closed. No hash is invented.
* FREEZE      — commit ``[H6-V4-04]`` contains only the frozen economic artifacts.
* POST-FREEZE — this script records the now-existing prereg commit and the hashes of the
  frozen artifacts. It is NON-ECONOMIC and it never mutates a frozen artifact.

Fails closed: refuses to run if the frozen artifacts are missing, or if any artifact is
untracked/dirty, or if the prereg commit does not actually contain all four artifacts.

No economics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "external-audit-01" / "h6-v4-repair"
BINDING = OUT / "H6_RUNTIME_AUTHORITY_BINDING_V4.json"

SCHEMA_VERSION = "H6-RUNTIME-AUTHORITY-BINDING-V1"
GENERATION = "H6-V4"
REL = "docs/external-audit-01/h6-v4-repair"

ARTIFACTS = {
    "spec": f"{REL}/H6_SPEC_V4.json",
    "manifest": f"{REL}/H6_MANIFEST_V4.json",
    "whitelist": f"{REL}/H6_FEATURE_AUTHORITY_WHITELIST_V4.json",
    "data_authority": f"{REL}/H6_DATA_AUTHORITY_V4.json",
}

REPORT_PATH = (
    "docs/external-audit-01/h6-external-verification-v4/"
    "H6_EXTERNAL_VERIFICATION_V4_REPORT.json"
)


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blob_id(commit: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "rev-parse", f"{commit}:{rel}"], cwd=str(REPO), capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg-commit", default=None,
                    help="freeze commit containing the four artifacts (default: HEAD)")
    args = ap.parse_args()

    prereg = args.prereg_commit or _git("rev-parse", "HEAD")

    # Frozen artifacts must exist and be clean (committed, not modified in the worktree).
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", *ARTIFACTS.values()],
        cwd=str(REPO), capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(f"refusing to bind: frozen artifacts are dirty:\n{dirty}")

    blobs: dict[str, str] = {}
    for label, rel in ARTIFACTS.items():
        blob = _blob_id(prereg, rel)
        if blob is None:
            raise SystemExit(f"refusing to bind: {rel} is not present in prereg commit {prereg}")
        blobs[label] = blob

    hashes = {label: _sha256(REPO / rel) for label, rel in ARTIFACTS.items()}
    da = json.loads((REPO / ARTIFACTS["data_authority"]).read_text(encoding="utf-8"))

    # Cross-check: worktree bytes must equal the committed bytes.
    for label, rel in ARTIFACTS.items():
        committed = subprocess.run(
            ["git", "show", f"{prereg}:{rel}"], cwd=str(REPO), capture_output=True
        ).stdout
        if hashlib.sha256(committed).hexdigest() != hashes[label]:
            raise SystemExit(f"refusing to bind: {rel} worktree bytes != committed bytes")

    binding = {
        "schema_version": SCHEMA_VERSION,
        "generation": GENERATION,
        "prereg_commit": prereg,
        "spec_path": ARTIFACTS["spec"],
        "spec_sha256": hashes["spec"],
        "manifest_path": ARTIFACTS["manifest"],
        "manifest_sha256": hashes["manifest"],
        "whitelist_path": ARTIFACTS["whitelist"],
        "whitelist_sha256": hashes["whitelist"],
        "data_authority_path": ARTIFACTS["data_authority"],
        "data_authority_sha256": hashes["data_authority"],
        "expected_external_verifier_report_path": REPORT_PATH,
        "dataset_sha256": da["dataset_sha256"],
        "economics_inspected": False,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "NON-ECONOMIC. Generated post-freeze; binds the runtime to the prereg commit "
            "without modifying any frozen economic artifact."
        ),
    }
    BINDING.write_text(json.dumps(binding, indent=1) + "\n", encoding="utf-8")

    audit = {
        "artifact": "H6_V4_AUTHORITY_BINDING_AUDIT",
        "generation": GENERATION,
        "prereg_commit": prereg,
        "binding_path": str(BINDING.relative_to(REPO)).replace("\\", "/"),
        "frozen_artifacts": [
            {
                "label": label,
                "path": rel,
                "prereg_blob_id": blobs[label],
                "worktree_sha256": hashes[label],
                "committed_sha256_matches_worktree": True,
            }
            for label, rel in ARTIFACTS.items()
        ],
        "H6_BACKTESTS": 0,
        "H6_EXECUTIONS": 0,
        "PERFORMANCE_OBSERVED": False,
    }
    (OUT / "H6_V4_AUTHORITY_BINDING_AUDIT.json").write_text(
        json.dumps(audit, indent=1) + "\n", encoding="utf-8"
    )

    print("prereg_commit      =", prereg)
    print("binding            =", BINDING.relative_to(REPO))
    for label, rel in ARTIFACTS.items():
        print(f"  {label:15s} blob={blobs[label][:12]} sha256={hashes[label][:16]}…")
    print("dataset_sha256     =", da["dataset_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
