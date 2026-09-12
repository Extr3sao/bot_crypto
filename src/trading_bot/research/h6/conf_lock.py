"""P20 — confirmation lock guard for CONF-EDGE-002-001 (V3: ledger-backed).

Before 2026-09-22T00:00:00Z, CONF-EDGE-002-001 must remain
consumed=false and executions=0. No performance inspection.

V3 repair: primary authority is CONFIRMATION_LEDGER_V2.jsonl (append-only),
not the absent static manifest docs/external-audit-01/confirmations/CONF-EDGE-002-001.json.
The reducer confirmation_state() derives authoritative state from ledger events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

CONFIRMATION_LOCK_UNTIL = datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc)
CONFIRMATION_ID = "CONF-EDGE-002-001"
# Legacy path (now considered invalid primary authority — kept for backwards compat check):
CONFIRMATION_MANIFEST_PATH = Path("docs/external-audit-01/confirmations/CONF-EDGE-002-001.json")
CONFIRMATION_LEDGER_PATH = Path("docs/external-audit-01/oi-full-history-02/CONFIRMATION_LEDGER_V2.jsonl")


class ConfirmationLockViolation(Exception):
    pass


def confirm_lock_status() -> dict:
    """Return authoritative confirmation status from ledger (primary) or manifest (legacy fallback).

    Primary authority: CONFIRMATION_LEDGER_V2.jsonl reduced via confirmation_state().
    If ledger is absent/invalid, fall back to legacy manifest but mark source accordingly
    so callers know authority is degraded.
    """
    # Primary: ledger-backed
    if CONFIRMATION_LEDGER_PATH.exists():
        from trading_bot.research.h6.confirmation_state import confirmation_state

        state = confirmation_state(CONFIRMATION_ID, CONFIRMATION_LEDGER_PATH)
        if state.state_valid:
            consumed_val: object = state.consumed
            executions_val: object = state.execution_count
            return {
                "confirmation_id": CONFIRMATION_ID,
                "consumed": consumed_val,
                "executions": executions_val,
                "locked_until": (state.locked_until or CONFIRMATION_LOCK_UNTIL).isoformat(),
                "source": "confirmation_ledger_v2",
                "ledger_state_valid": True,
                "last_event": state.last_event,
                "execution_count": state.execution_count,
            }
        return {
            "confirmation_id": CONFIRMATION_ID,
            "consumed": "UNKNOWN",
            "executions": "UNKNOWN",
            "locked_until": CONFIRMATION_LOCK_UNTIL.isoformat(),
            "source": "confirmation_ledger_v2_invalid",
            "ledger_error": state.error,
        }
    # Legacy fallback: manifest (now known absent, so this path returns missing_manifest)
    if not CONFIRMATION_MANIFEST_PATH.exists():
        return {
            "confirmation_id": CONFIRMATION_ID,
            "consumed": "UNKNOWN",
            "executions": "UNKNOWN",
            "locked_until": CONFIRMATION_LOCK_UNTIL.isoformat(),
            "source": "missing_manifest",
            "ledger_path": str(CONFIRMATION_LEDGER_PATH),
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
    # Ledger-backed path requires confirmation_ledger_v2 source
    if status.get("source") == "confirmation_ledger_v2_invalid":
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} ledger invalid: {status.get('ledger_error')}")
    if status["source"] == "missing_manifest":
        raise ConfirmationLockViolation(
            f"{CONFIRMATION_ID} ledger missing at {status.get('ledger_path')}; cannot verify lock — EXT-CONF-002 repair requires ledger-backed authority"
        )
    if status["consumed"] is not False:
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} consumed={status['consumed']}; expected false")
    if status["executions"] != 0:
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} executions={status['executions']}; expected 0")
    try:
        locked_until = datetime.fromisoformat(status["locked_until"])  # type: ignore[arg-type]
    except Exception as exc:
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} locked_until unparseable: {status['locked_until']}") from exc
    now = datetime.now(timezone.utc)
    if now >= locked_until:
        raise ConfirmationLockViolation(f"{CONFIRMATION_ID} lock expired at {locked_until}")
