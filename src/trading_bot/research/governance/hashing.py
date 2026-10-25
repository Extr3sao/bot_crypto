"""ARP-008 §4,§5 — deterministic canonical hashing for experiment governance.

Everything the governance plane freezes (contract views, split definitions,
holdout descriptors, terminal records) is hashed through ONE canonical JSON
serialisation so a hash is reproducible byte-for-byte on any machine and can
never depend on dict insertion order. Research-only: nothing here is importable
by the trading runtime.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["canonical_hash", "canonical_json"]


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` to a canonical, order-independent JSON string."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def canonical_hash(obj: Any) -> str:
    """SHA-256 hex digest of :func:`canonical_json` (deterministic)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
