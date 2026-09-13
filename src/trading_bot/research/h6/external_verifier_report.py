"""V4 — external verifier report locator.

V4 repairs two V3 defects at once:

* V3-AUTH-001 — the report path was hard-coded to the superseded **V1** folder
  (``oi-full-history-01``), so a legitimate V3/V4 report could never satisfy the gate
  while a V1-keyed report could.
* the V3 path was a bare **relative** ``Path``, so the gate's outcome depended on the
  process working directory.

The location now comes from the single versioned runtime authority binding and is
resolved against the repository root, never the CWD. Before a binding exists the
runtime stays fail-closed (``can_execute_h6() == False``).

No economics.
"""

from __future__ import annotations

import json
from pathlib import Path

from trading_bot.research.h6.runtime_authority import expected_external_verifier_report_path

V4_REPORT_RELATIVE_PATH = (
    "docs/external-audit-01/h6-external-verification-v4/"
    "H6_EXTERNAL_VERIFICATION_V4_REPORT.json"
)


def report_path() -> Path:
    """Repo-root-resolved external verification report path (CWD-independent)."""
    return expected_external_verifier_report_path()


def external_report_exists() -> bool:
    return report_path().exists()


def read_external_report() -> dict | None:
    """Return the parsed report, or None if absent/unreadable (fail closed)."""
    p = report_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_external_verdict() -> str | None:
    """Return the report's FINAL_VERDICT, or None when absent/malformed."""
    report = read_external_report()
    if report is None:
        return None
    verdict = report.get("FINAL_VERDICT")
    return str(verdict) if verdict is not None else None


__all__ = [
    "V4_REPORT_RELATIVE_PATH",
    "external_report_exists",
    "read_external_report",
    "read_external_verdict",
    "report_path",
]
