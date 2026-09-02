"""Hash utility for event journal integrity — SHA-256 hash-chain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID


def compute_event_hash(
    event_id: UUID,
    timestamp: datetime,
    ticket_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    previous_hash: str,
) -> str:
    """Compute SHA-256 hash of an event for hash-chain integrity.

    The hash includes all event fields plus the previous hash,
    ensuring any modification to the chain is detectable.
    """
    # Normalize payload to string (sorted keys for determinism)
    payload_str = json.dumps(payload, sort_keys=True, default=str)

    # Build hash input
    hash_input = f"{event_id}|{timestamp.isoformat()}|{ticket_id}|{event_type}|{actor}|{payload_str}|{previous_hash}"

    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def verify_hash_chain(events: list[dict[str, Any]]) -> tuple[bool, str]:
    """Verify the integrity of a hash-chained event sequence.

    Returns (is_valid, error_message).
    """
    previous_hash = ""

    for i, event in enumerate(events):
        expected_hash = compute_event_hash(
            event_id=event.get("event_id", ""),
            timestamp=event.get("timestamp", datetime.utcnow()),
            ticket_id=event.get("ticket_id", ""),
            event_type=event.get("event_type", ""),
            actor=event.get("actor", ""),
            payload=event.get("payload", {}),
            previous_hash=previous_hash,
        )

        actual_hash = event.get("event_hash", "")

        if actual_hash != expected_hash:
            return False, f"Hash mismatch at event {i}: expected {expected_hash[:16]}..., got {actual_hash[:16]}..."

        if event.get("previous_hash", "") != previous_hash:
            return False, f"Chain break at event {i}: expected previous_hash {previous_hash[:16]}..., got {event.get('previous_hash', '')[:16]}..."

        previous_hash = actual_hash

    return True, ""
