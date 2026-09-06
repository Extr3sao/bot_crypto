"""FRESH-DATA-001-R1: supersede the R0 candidate registry.

Marks every candidate in docs/fresh-data-001/evidence/CANDIDATE_REGISTRY.json
as SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW. The records are preserved as
historical evidence (never deleted); the supersede status is a hard
exclusion: the selection path refuses to consume any record whose status is
not FROZEN_AWAITING_CONFIRMATION, so old candidates can never be promoted.

Idempotent: running twice produces no further change.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REGISTRY_PATH = Path("docs/fresh-data-001/evidence/CANDIDATE_REGISTRY.json")
SUPERSEDE_STATUS = "SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW"
NEW_SCHEMA = "candidate-registry-v2-superseded"


def supersede_registry() -> dict:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = False
    for candidate in registry.get("candidates", []):
        if candidate.get("status") != SUPERSEDE_STATUS:
            candidate["status"] = SUPERSEDE_STATUS
            candidate["superseded_at"] = datetime.now(tz=UTC).isoformat()
            candidate["superseded_reason"] = (
                "R0 discovery window truncated at ~1000 bars/symbol (pagination defect); "
                "insufficient discovery history; edge magnitudes (+2R/+3R per trade) "
                "require semantics revalidation under R1"
            )
            changed = True
    if changed:
        registry["schema_version"] = NEW_SCHEMA
        registry["superseded_by"] = "FRESH-DATA-001-R1"
    return registry


def main() -> int:
    registry = supersede_registry()
    candidates = registry.get("candidates", [])
    statuses = {c.get("status") for c in candidates}
    if candidates and statuses != {SUPERSEDE_STATUS}:
        print(f"FAIL: not all candidates superseded: {statuses}", file=sys.stderr)
        return 1
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "candidates_superseded": len(candidates),
                "status": SUPERSEDE_STATUS if candidates else "NO_CANDIDATES",
                "schema_version": registry.get("schema_version"),
                "preserved": True,
                "selection_usable": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
