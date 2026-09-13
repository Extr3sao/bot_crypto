"""V4 — H6 execution harness, hard-gated on external verification.

V4 repair for V3-AUTH-001. V3 pinned ``PREREG_COMMIT`` / ``SPEC_SHA256`` /
``MANIFEST_SHA256`` to the **superseded, failed V1 preregistration** and read a V1
report path. Consequences were both bad directions:

* a legitimate V3 report would have been rejected with ``H6PreregMismatch``, so the gate
  could never be enabled through the legitimate path;
* a report carrying the V1 hashes with ``PASS`` would have satisfied the gate while a
  different generation was the live freeze.

V4 holds no hash literals at all. Every expected value comes from the single versioned
runtime authority binding. If the binding does not exist, or any artifact does not match
its bound hash, or the report is absent / malformed / not PASS / bound to a different
generation — execution stays disabled.

``can_execute_h6()`` returns ``False`` unless a real, correctly-bound external
verification PASS exists. This audit creates no such report.

No economics. Real economic execution is impossible from this module.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.h6 import runtime_authority as RA
from trading_bot.research.h6.external_verifier_report import read_external_report


class H6ExternalVerificationRequired(Exception):
    """Raised when H6 execution is attempted before external verification."""


class H6PreregMismatch(Exception):
    """Raised when the external verifier report does not match the bound V4 authority."""


REQUIRED_REPORT_KEYS = ("prereg_commit", "spec_sha256", "manifest_sha256", "dataset_sha256")


def expected_authority() -> dict[str, str]:
    """The authority the runtime expects, or an empty dict while unbound."""
    b = RA.load_binding()
    if b is None:
        return {}
    return {
        "prereg_commit": b.prereg_commit,
        "spec_sha256": b.spec_sha256,
        "manifest_sha256": b.manifest_sha256,
        "dataset_sha256": b.dataset_sha256,
        "whitelist_sha256": b.whitelist_sha256,
        "data_authority_sha256": b.data_authority_sha256,
        "generation": b.generation,
    }


def evaluate_report(report: dict[str, Any] | None) -> tuple[bool, str]:
    """Pure gate logic. Returns (may_execute, reason). Never raises for bad input."""
    if report is None:
        return False, "REPORT_MISSING_OR_MALFORMED"
    if not isinstance(report, dict):
        return False, "REPORT_MALFORMED"
    if str(report.get("FINAL_VERDICT", "")) != "PASS":
        return False, "VERDICT_NOT_PASS"

    binding = RA.load_binding()
    if binding is None:
        return False, "RUNTIME_AUTHORITY_UNBOUND"

    # Reject reports that are not bound to THIS generation.
    report_generation = report.get("generation") or report.get("checkpoint")
    if report_generation is not None and str(report_generation) != binding.generation:
        return False, f"GENERATION_MISMATCH ({report_generation!r} != {binding.generation!r})"

    missing = [k for k in REQUIRED_REPORT_KEYS if report.get(k) is None]
    if missing:
        return False, "REPORT_MISSING_KEYS: " + ",".join(missing)

    expected = expected_authority()
    for key in REQUIRED_REPORT_KEYS:
        if str(report.get(key)) != expected[key]:
            return False, f"{key.upper()}_MISMATCH"

    # The bound artifacts must still be present and byte-identical.
    for label, rec in binding.verify_artifacts_present_and_matching().items():
        if not rec.get("match"):
            return False, f"BOUND_ARTIFACT_MISMATCH: {label}"

    return True, "AUTHORIZED"


def _verify_external_report(report: dict[str, Any]) -> None:
    ok, reason = evaluate_report(report)
    if ok:
        return
    if reason.startswith(("SPEC_", "MANIFEST_", "DATASET_", "PREREG_", "GENERATION_", "WHITELIST_", "DATA_AUTHORITY_")):
        raise H6PreregMismatch(f"external report authority mismatch: {reason}")
    raise H6ExternalVerificationRequired(f"H6_EXTERNAL_VERIFICATION_REQUIRED: {reason}")


def can_execute_h6() -> bool:
    """True ONLY for a real, correctly-bound external verification PASS."""
    return evaluate_report(read_external_report())[0]


def gate_status() -> dict[str, Any]:
    """Diagnostics. Safe to call at any time."""
    report = read_external_report()
    ok, reason = evaluate_report(report)
    return {
        "can_execute_h6": ok,
        "reason": reason,
        "binding": RA.binding_status(),
        "report_path": str(RA.expected_external_verifier_report_path()),
        "report_present": report is not None,
        "report_verdict": (report or {}).get("FINAL_VERDICT"),
        "expected": expected_authority(),
    }


def run_h6_dry_run() -> dict[str, Any]:
    """Dry-run only. Raises if the gate is not satisfied."""
    report = read_external_report()
    if report is None:
        raise H6ExternalVerificationRequired(
            "H6_EXTERNAL_VERIFICATION_REQUIRED: real execution disabled"
        )
    _verify_external_report(report)
    binding = RA.current_binding()
    return {
        "status": "H6_EXECUTION_ENABLED_ONLY_AFTER_EXTERNAL_VERIFICATION_PASS",
        "prereg_commit": binding.prereg_commit,
        "generation": binding.generation,
        "gated": True,
    }
