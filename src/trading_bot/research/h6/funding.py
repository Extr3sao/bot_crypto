"""P14 — funding policy contract from frozen H6 spec.

Frozen policy: EXCLUDED_WITH_LIMITATION with
funding_materiality_gate_before_promotion = true.

No funding feature becomes an H6 signal unless whitelist/spec explicitly
allows it. This module is intentionally minimal: it encodes the frozen
policy only.
"""

from __future__ import annotations

FUNDING_DISCOVERY_ACCOUNTING = "EXCLUDED_WITH_LIMITATION"
FUNDING_MATERIALITY_GATE_BEFORE_PROMOTION = True


class H6FundingNotAvailable(Exception):
    """Raised if runtime attempts to include funding before materiality gate."""


def funding_included_for_discovery() -> bool:
    return False
