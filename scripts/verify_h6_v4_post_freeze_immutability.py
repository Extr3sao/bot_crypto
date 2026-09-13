"""H6 V4 post-freeze immutability proof.

For each frozen economic artifact, proves that the committed bytes at the prereg commit
are identical to the committed bytes at the current HEAD, using BOTH Git blob IDs and an
independent SHA256 of the bytes Git reports.

Required for a valid freeze: DRIFT = false for all four artifacts.

No economics.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "external-audit-01" / "h6-v4-repair"
BINDING = OUT / "H6_RUNTIME_AUTHORITY_BINDING_V4.json"
REL = "docs/external-audit-01/h6-v4-repair"

ARTIFACTS = (
    f"{REL}/H6_SPEC_V4.json",
    f"{REL}/H6_MANIFEST_V4.json",
    f"{REL}/H6_FEATURE_AUTHORITY_WHITELIST_V4.json",
    f"{REL}/H6_DATA_AUTHORITY_V4.json",
)


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def _blob(commit: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "rev-parse", f"{commit}:{rel}"], cwd=str(REPO), capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else None


def _sha256_at(commit: str, rel: str) -> str | None:
    out = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=str(REPO), capture_output=True)
    return hashlib.sha256(out.stdout).hexdigest() if out.returncode == 0 else None


def main() -> int:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    prereg = binding["prereg_commit"]
    head = _git("rev-parse", "HEAD")

    diff = _git("diff", "--name-only", f"{prereg}..HEAD", "--", *ARTIFACTS)

    rows = []
    for rel in ARTIFACTS:
        b_pre, b_head = _blob(prereg, rel), _blob(head, rel)
        s_pre, s_head = _sha256_at(prereg, rel), _sha256_at(head, rel)
        rows.append({
            "path": rel,
            "prereg_blob_id": b_pre,
            "head_blob_id": b_head,
            "blob_ids_equal": b_pre == b_head,
            "prereg_sha256": s_pre,
            "head_sha256": s_head,
            "byte_hashes_equal": s_pre == s_head,
            "DRIFT": not (b_pre == b_head and s_pre == s_head),
        })

    drift = [r["path"] for r in rows if r["DRIFT"]]
    report = {
        "artifact": "H6_V4_POST_FREEZE_IMMUTABILITY",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prereg_commit": prereg,
        "head_commit": head,
        "git_diff_prereg_to_head": diff or "(empty)",
        "diff_is_empty": diff == "",
        "frozen_artifacts": rows,
        "POST_FREEZE_ARTIFACT_DRIFT": len(drift),
        "drift_paths": drift,
        "status": "PASS" if (not drift and diff == "") else "FAIL",
        "H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False,
    }
    (OUT / "H6_V4_POST_FREEZE_IMMUTABILITY.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )

    print(f"prereg_commit = {prereg}")
    print(f"head_commit   = {head}")
    print(f"git diff      = {'(empty)' if diff == '' else diff}")
    for r in rows:
        print(f"  {'DRIFT' if r['DRIFT'] else 'ok   '} {r['path'].split('/')[-1]:40s} blob={str(r['prereg_blob_id'])[:12]}")
    print(f"POST_FREEZE_ARTIFACT_DRIFT = {report['POST_FREEZE_ARTIFACT_DRIFT']}")
    print(f"status = {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
