"""Confirmation ledger state reducer — EXT-CONF-002 repair.

Single source of future confirmation state: ConfirmationExecutionLedger (CONFIRMATION_LEDGER_V2.jsonl).

All future confirmation state reads derive from ledger events. No hard-coded consumed=false.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_EVENT_TYPES = frozenset({"CREATED", "STARTED", "COMPLETED", "FAILED", "CONSUMED", "LOCK_CHECK"})
REQUIRED_FIELDS = frozenset({"confirmation_id", "event_type", "attempt_id", "timestamp", "commit", "dataset", "spec", "status"})


@dataclass(frozen=True, slots=True)
class ConfirmationState:
    confirmation_id: str
    created: bool
    locked_until: datetime | None
    started_attempts: int
    completed_attempts: int
    failed_attempts: int
    consumed: bool
    execution_count: int  # number of STARTED events
    last_event: dict[str, Any] | None
    state_valid: bool
    error: str | None = None


def _parse_ts(ts: str) -> datetime:
    # Accept both "2026-09-12T00:00:00Z" and ISO with +00:00
    s = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def load_ledger_events(ledger_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not ledger_path.exists():
        return events
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def validate_event(event: dict[str, Any]) -> str | None:
    for f in REQUIRED_FIELDS:
        if f not in event:
            return f"missing field {f}"
    if event["event_type"] not in VALID_EVENT_TYPES:
        return f"invalid event_type {event['event_type']}"
    # validate attempt_id non-empty
    if not str(event["attempt_id"]).strip():
        return "empty attempt_id"
    # validate timestamp parseable
    try:
        _parse_ts(str(event["timestamp"]))
    except Exception:
        return f"unparseable timestamp {event['timestamp']}"
    # validate status non-empty
    if not str(event["status"]).strip():
        return "empty status"
    return None


def confirmation_state(confirmation_id: str, ledger_path: Path) -> ConfirmationState:
    events = [e for e in load_ledger_events(ledger_path) if str(e.get("confirmation_id")) == confirmation_id]
    error: str | None = None
    # Validate ordering and exactly-once guards
    seen_attempts: set[str] = set()
    created = False
    started = 0
    completed = 0
    failed = 0
    consumed = False
    last: dict[str, Any] | None = None
    locked_until: datetime | None = None
    state_valid = True
    for ev in events:
        err = validate_event(ev)
        if err:
            state_valid = False
            error = err
            break
        aid = str(ev["attempt_id"])
        if aid in seen_attempts and ev["event_type"] != "LOCK_CHECK":
            # LOCK_CHECK may reuse same attempt for lock verification; others require unique attempt_id
            state_valid = False
            error = f"duplicate attempt_id {aid} for {ev['event_type']}"
            break
        seen_attempts.add(aid)
        et = str(ev["event_type"])
        if et == "CREATED":
            created = True
        elif et == "STARTED":
            started += 1
            if consumed:
                state_valid = False
                error = "STARTED after CONSUMED"
                break
        elif et == "COMPLETED":
            completed += 1
        elif et == "FAILED":
            failed += 1
        elif et == "CONSUMED":
            if consumed:
                state_valid = False
                error = "duplicate CONSUMED"
                break
            consumed = True
        elif et == "LOCK_CHECK":
            # Extract locked_until from status if present
            st = str(ev.get("status", ""))
            if "LOCKED_UNTIL_" in st:
                try:
                    ts_str = st.split("LOCKED_UNTIL_")[1].split("_")[0]
                    # ts_str like 2026-09-22T00:00:00Z
                    locked_until = _parse_ts(ts_str)
                except Exception:
                    pass
        last = ev
    # If still valid, derive locked_until fallback from CONFIRMATION_LOCK_UNTIL constant
    if locked_until is None:
        from trading_bot.research.h6.conf_lock import CONFIRMATION_LOCK_UNTIL

        locked_until = CONFIRMATION_LOCK_UNTIL
    return ConfirmationState(
        confirmation_id=confirmation_id,
        created=created,
        locked_until=locked_until,
        started_attempts=started,
        completed_attempts=completed,
        failed_attempts=failed,
        consumed=consumed,
        execution_count=started,
        last_event=last,
        state_valid=state_valid,
        error=error,
    )
