"""P20 — confirmation lock guard for CONF-EDGE-002-001.

Before 2026-09-22T00:00:00Z, CONF-EDGE-002-001 must remain
consumed=false and executions=0. No performance inspection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIRMATION_LOCK_UNTIL = datetime(2026, 9, 22, 0, 0, 0, tzinfo=UTC)
CONFIRMATION_ID = "CONF-EDGE-002-001"
CONFIRMATION_MANIFEST_PATH = Path("docs/external-audit-01/confirmations/CONF-EDGE-002-001.json")


class ConfirmationLockViolation(Exception):
    pass


def confirm_lock_status() -> dict[str, Any]:
    """Return authoritative confirmation status from manifest."""
    if not CONFIRMATION_MANIFEST_PATH.exists():
        return {
            "confirmation_id": CONFIRMATION_ID,
            "consumed": "UNKNOWN",
            "executions": "UNKNOWN",
            "locked_until": CONFIRMATION_LOCK_UNTIL.isoformat(),
            "source": "missing_manifest",
        }
    import json

    manifest = json.loads(CONFIRMATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "confirmation_id": CONFIRMATION_ID,
        "consumed": manifest.get("consumed"),
        "executions": manifest.get("executions"),
        "locked_until": manifest.get("locked_until"),
        "source": "manifest",
    }


def assert_confirmation_locked() -> None:
    status = confirm_lock_status()
    if status["source"] == "missing_manifest":
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} manifest missing; cannot verify lock")
    if status["consumed"] is not False:
        raise ConfirmationLockViolation(
            f"{CONFIRMATION_ID} consumed={status['consumed']}; expected false"
        )
    if status["executions"] != 0:
        raise ConfirmationLockViolation(
            f"{CONFIRMATION_ID} executions={status['executions']}; expected 0"
        )
    try:
        locked_until = datetime.fromisoformat(status["locked_until"])
    except Exception as exc:
        raise ConfirmationLockViolation(
            f"{CONFIRMATION_ID} locked_until unparseable: {status['locked_until']}"
        ) from exc
    now = datetime.now(UTC)
    if now >= locked_until:
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} lock expired at {locked_until}")
