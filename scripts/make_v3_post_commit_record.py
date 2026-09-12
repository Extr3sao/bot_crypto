"""H6 V3 post-commit record (spec 39) — non-self-referential.

Run AFTER the prereg freeze commit. Records the V3 commit, tree, parent,
timestamp and the sha256 (actual stored bytes) of each frozen artifact.
Writes docs/external-audit-01/oi-full-history-03/H6_V3_POST_COMMIT_RECORD.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
E3 = REPO / "docs/external-audit-01/oi-full-history-03"
FROZEN = [
    "docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json",
    "docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json",
    "docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json",
    "docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json",
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO).stdout.strip()


def main() -> int:
    commit = git("rev-parse", "HEAD")
    record = {
        "checkpoint": "H6-V3-REPAIR",
        "record": "H6_V3_POST_COMMIT_RECORD",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "parent": git("rev-parse", "HEAD~1"),
        "branch": git("branch", "--show-current"),
        "subject": git("log", "-1", "--format=%s"),
        "artifact_sha256": {f: sha256_file(REPO / f) for f in FROZEN},
        "dataset_sha256": json.loads((E3 / "H6_DATA_AUTHORITY_V3.json").read_text(encoding="utf-8"))["dataset_sha256"],
        "price_sha256": json.loads((REPO / "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json").read_text(encoding="utf-8"))["PRICE_AUTHORITY_SHA256_V2"],
        "freeze_verification": {
            f: git("diff", commit, "--", f) == "" for f in FROZEN
        },
        "governance": {
            "H6_EXECUTIONS": 0,
            "H6_BACKTESTS": 0,
            "PERFORMANCE_OBSERVED": False,
        },
        "note": "separate post-commit artifact; not referenced by (and does not alter) the frozen prereg files",
    }
    out = E3 / "H6_V3_POST_COMMIT_RECORD.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("commit", "tree", "parent", "subject")}, indent=2))
    print(json.dumps(record["artifact_sha256"], indent=2))
    print("freeze_verification all EMPTY:", all(record["freeze_verification"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
