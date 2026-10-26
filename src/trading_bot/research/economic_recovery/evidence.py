"""RFC-EDGE-014 — declared paths, anchored on the repository root.

The first defect WP-EDGE-04R closed in this campaign was a probe that resolved its
declared paths against the caller's working directory, so the same command gave one
verdict from the repository root and another from anywhere else. This recovery
package inherits that lesson: every path a script touches is resolved here, against
the checkout the module was loaded from, never against ``os.getcwd()``.

It also inherits the rule that makes the audit checkable. The artefacts this package
reads in order to *reconcile* WP-EDGE-09 (the cost gates, the experiment ledger, the
real-decision ledger) are treated as immutable primary sources: they are read, hashed
and cited, never rewritten. A reconciliation that edits the document it is auditing
proves nothing, so the EDGE-09 originals stay byte-for-byte as they were published and
this package publishes its own versioned supersession alongside them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_STATE_ROOT",
    "REPORTS",
    "REPO_ROOT",
    "coerce_float",
    "iso_from_ms",
    "now_utc",
    "read_json",
    "repo_path",
    "sha256_file",
    "write_json",
    "write_text",
]

REPO_ROOT = Path(__file__).resolve().parents[4]

REPORTS = REPO_ROOT / "reports" / "economic-recovery" / "RFC-EDGE-014"
DEFAULT_STATE_ROOT = REPO_ROOT / "data" / "economic-recovery" / "edge14"

#: The published WP-EDGE-09 package. Read-only primary source for WP-EDGE-14B.
EDGE09_REPORTS = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-09"
EDGE09_GATES = EDGE09_REPORTS / "gates" / "COST_LIQUIDITY_CAPACITY.json"
EDGE09_EXPERIMENTS = EDGE09_REPORTS / "experiments" / "EXPERIMENTS.json"
EDGE09_FINAL_REPORT = EDGE09_REPORTS / "FINAL_REPORT.md"
EDGE09_FEASIBILITY = EDGE09_REPORTS / "ECONOMIC_FEASIBILITY_REPORT.md"

#: The real-decision ledger (CAP-004). Read-only primary source for WP-EDGE-14A.
REAL_DECISIONS = REPO_ROOT / "evidence" / "real_decisions"


def repo_path(value: str | Path) -> Path:
    """Resolve a declared path against the repository root, never against the cwd."""
    candidate = Path(value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_from_ms(instant_ms: int | float | None) -> str | None:
    if instant_ms is None:
        return None
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coerce_float(value: Any) -> float | None:
    """Numbers in the ledger are numbers; a string that is not one becomes None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
