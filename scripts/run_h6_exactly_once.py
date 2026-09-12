"""P15 + P16 — H6 exactly-once runner hard-gated on external verification.

Execution is impossible until ALL guards pass. No --force or
environment bypass. This script is prepared for the future economic
checkpoint; in this preparation checkpoint it must not run real H6.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading_bot.research.h6.execution_harness import (
    H6ExternalVerificationRequired,
    run_h6_dry_run,
)

EXTERNAL_VERIFIER_REPORT_PATH = ROOT / "docs/external-audit-01/oi-full-history-01/H6_EXTERNAL_VERIFIER_REPORT.json"

def main() -> None:
    if not EXTERNAL_VERIFIER_REPORT_PATH.exists():
        raise H6ExternalVerificationRequired(
            "H6_EXTERNAL_VERIFICATION_REQUIRED: no external verifier report; real execution blocked"
        )
    try:
        outcome = run_h6_dry_run()
    except H6ExternalVerificationRequired as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print("H6 dry-run gate outcome:", outcome)
    raise SystemExit(0)

if __name__ == "__main__":
    main()
