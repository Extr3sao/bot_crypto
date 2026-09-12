"""P19 helper — detect external verifier report if present."""

from __future__ import annotations

from pathlib import Path

REPORT_PATH = Path(
    "docs/external-audit-01/oi-full-history-01/H6_EXTERNAL_VERIFIER_REPORT.json"
)


def external_report_exists() -> bool:
    return REPORT_PATH.exists()


def read_external_verdict() -> str | None:
    if not REPORT_PATH.exists():
        return None
    import json
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return report.get("FINAL_VERDICT")
