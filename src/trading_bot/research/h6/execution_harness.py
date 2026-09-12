"""P15 — H6 execution harness hard-gated on external verification.

Real economic execution is impossible until ALL prerequisites are met.
This module is intentionally defensive: if any gate fails, it raises
H6_EXTERNAL_VERIFICATION_REQUIRED and does NOT run economic code.
"""

from __future__ import annotations

from pathlib import Path

from trading_bot.research.h6.external_verifier_report import (
    REPORT_PATH,
    external_report_exists,
    read_external_verdict,
)

PREREG_COMMIT = "e683e04e5df39d0f2f5feb6097664536b93cc636"
SPEC_SHA256 = "f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148"
MANIFEST_SHA256 = "345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc"
DATASET_SHA256 = "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"


class H6ExternalVerificationRequired(Exception):
    """Raised when H6 execution is attempted before external verification."""


class H6PreregMismatch(Exception):
    """Raised when external verifier report does not match frozen artifacts."""


def _verify_external_report(report: dict) -> None:
    verdict = read_external_verdict()
    if verdict != "PASS":
        raise H6ExternalVerificationRequired(
            "H6_EXTERNAL_VERIFICATION_REQUIRED: external verdict != PASS"
        )
    if report.get("prereg_commit") != PREREG_COMMIT:
        raise H6PreregMismatch("external report prereg_commit mismatch")
    if report.get("spec_sha256") != SPEC_SHA256:
        raise H6PreregMismatch("external report spec_sha256 mismatch")
    if report.get("manifest_sha256") != MANIFEST_SHA256:
        raise H6PreregMismatch("external report manifest_sha256 mismatch")
    if report.get("dataset_sha256") != DATASET_SHA256:
        raise H6PreregMismatch("external report dataset_sha256 mismatch")


def can_execute_h6() -> bool:
    """Return True only if external verification is PASS and hashes match."""
    if not external_report_exists():
        return False
    try:
        report = _read_external_report()
        _verify_external_report(report)
        return True
    except (H6ExternalVerificationRequired, H6PreregMismatch):
        return False


def _read_external_report() -> dict:
    import json
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def run_h6_dry_run() -> dict:
    """Dry-run only. Raises H6ExternalVerificationRequired if gated off."""
    if not can_execute_h6():
        raise H6ExternalVerificationRequired(
            "H6_EXTERNAL_VERIFICATION_REQUIRED: real execution disabled"
        )
    return {
        "status": "H6_EXECUTION_ENABLED_ONLY_AFTER_EXTERNAL_VERIFICATION_PASS",
        "prereg_commit": PREREG_COMMIT,
        "gated": True,
    }
