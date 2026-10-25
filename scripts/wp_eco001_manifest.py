"""Refresh the artefact manifest inside RUN_REPORT.json after a verification run.

The verifier writes ``INDEPENDENT_VERIFICATION.json`` *after* the manifest, so its
own hash cannot live inside the manifest without a circular dependency; it is
listed under ``artefacts_omitted`` with the reason instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

WP = Path(__file__).resolve().parents[1] / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001"


def main() -> int:
    path = WP / "RUN_REPORT.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    # Neither the verifier's output nor this manifest itself can carry a stable
    # hash inside the manifest: one is written later, the other is being written.
    skipped = {"INDEPENDENT_VERIFICATION.json", "RUN_REPORT.json"}
    artefacts = []
    for item in sorted(WP.glob("*")):
        if not item.is_file() or item.name in skipped:
            continue
        artefacts.append(
            {
                "path": item.as_posix(),
                "bytes": item.stat().st_size,
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
            }
        )
    report["artefacts"] = artefacts
    report["artefacts_omitted"] = [
        {
            "path": "INDEPENDENT_VERIFICATION.json",
            "why": "written by the verifier after this manifest; hash it from the file itself",
        },
        {
            "path": "RUN_REPORT.json",
            "why": "this manifest: a hash of itself inside itself is stale by construction",
        },
    ]
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest refreshed: {len(artefacts)} artefacts")
    for row in artefacts:
        print(f"  {row['path'].rsplit('/', 1)[-1]:<34} {row['bytes']:>7} {row['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
