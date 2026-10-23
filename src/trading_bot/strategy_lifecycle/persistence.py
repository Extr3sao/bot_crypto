"""Lifecycle persistence — restart-safe, atomic, fail-closed (GATE STRAT-PERSIST-003).

Closes **DEF-VERIFY-010**: the dynamic plane (registry + contextual performance
store) is pure in-memory, so a restart loses every lifecycle state, observation,
event and churn counter.

Design (PERSISTENCE CONTRACT):

* **One authority.** The persisted *materialised state* is the registry
  descriptors (+ their append-only history/events) and the raw observations in
  the contextual store. Health, cells, churn and streaks are **derived /
  recomputable** — never a second source of truth.
* **Event log + materialised state.** Every transition is reconstructable: the
  registry keeps an append-only per-strategy history and a global event log, and
  the snapshot additionally carries an audit ``event_log`` projection with the
  mandated fields (``event_id``, ``run_id``, ``strategy_id``, ``from_state``,
  ``to_state``, ``reason``, ``evidence_ids``, ``timestamp``, ``schema_version``,
  ``commit_sha``).
* **Atomic.** Writes go to a sibling temp file and are swapped in with
  ``os.replace`` — never a partial state, never "memory says ACTIVE, disk says
  SHADOW".
* **Schema-versioned + integrity-checked.** A JSON body plus a SHA-256 checksum
  over the canonical body. Unknown newer schema, checksum mismatch, missing
  mandatory field, invalid enum, or descriptor/history inconsistency are all
  refused (**fail closed**). Corrupt state is never defaulted to ACTIVE/ELIGIBLE.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .contracts import LifecycleState
from .ecosystem import DynamicStrategyEcosystem
from .performance import ContextualPerformanceStore
from .registry import DynamicStrategyRegistry

__all__ = [
    "LIFECYCLE_PERSISTENCE_SCHEMA_VERSION",
    "LifecycleCorruptionError",
    "LifecyclePersistenceError",
    "LifecycleSchemaVersionError",
    "ecosystem_state_hash",
    "load_ecosystem",
    "replay_lifecycle",
    "restore_ecosystem",
    "save_ecosystem",
    "snapshot_ecosystem",
]

LIFECYCLE_PERSISTENCE_SCHEMA_VERSION: Final[str] = "strategy-lifecycle-persistence-v1"


class LifecyclePersistenceError(RuntimeError):
    """Base class for a persistence refusal."""


class LifecycleSchemaVersionError(LifecyclePersistenceError):
    """The persisted schema version is unknown or newer than this build."""


class LifecycleCorruptionError(LifecyclePersistenceError):
    """The persisted state is missing, malformed or internally inconsistent."""


# --------------------------------------------------------------------------- #
# Canonical serialization + integrity
# --------------------------------------------------------------------------- #


def _default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable")


def _canonical(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_default
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Audit event-log projection (§2)
# --------------------------------------------------------------------------- #


def _event_log(
    registry: DynamicStrategyRegistry, *, run_id: str, commit_sha: str
) -> list[dict[str, Any]]:
    """Derive the mandated audit rows from the registry's append-only events."""
    descriptors = {sid: registry.descriptor(sid) for sid in registry.strategy_ids()}
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(registry.events()):
        sid = str(event.get("strategy_id", ""))
        desc = descriptors.get(sid)
        rows.append(
            {
                "event_id": f"{run_id}:{index}",
                "run_id": run_id,
                "strategy_id": sid,
                "strategy_version": desc.strategy_version if desc else "",
                "from_state": event.get("from_state"),
                "to_state": event.get("to_state"),
                "reason": list(event.get("reason_codes", [])),
                "evidence_ids": list(event.get("evidence", [])),
                "timestamp": int(event.get("timestamp_ms", 0)),
                "schema_version": LIFECYCLE_PERSISTENCE_SCHEMA_VERSION,
                "commit_sha": commit_sha,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# Snapshot / restore
# --------------------------------------------------------------------------- #


def snapshot_ecosystem(
    eco: DynamicStrategyEcosystem,
    *,
    run_id: str = "",
    commit_sha: str = "",
    persisted_at_ms: int = 0,
) -> dict[str, Any]:
    """Build the authoritative, integrity-stamped snapshot (no side effects)."""
    body: dict[str, Any] = {
        "schema_version": LIFECYCLE_PERSISTENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "commit_sha": commit_sha,
        "persisted_at_ms": int(persisted_at_ms),
        "registry": eco.registry.to_state(),
        "performance": eco.performance.to_state(),
        "health": dict(eco._health),
        "event_log": _event_log(eco.registry, run_id=run_id, commit_sha=commit_sha),
    }
    checksum = _sha256(_canonical(body))
    return {**body, "checksum": checksum}


def _verify(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LifecycleCorruptionError("persisted lifecycle state is not an object")
    version = payload.get("schema_version")
    if version is None:
        raise LifecycleCorruptionError("persisted lifecycle state has no schema_version")
    if version != LIFECYCLE_PERSISTENCE_SCHEMA_VERSION:
        raise LifecycleSchemaVersionError(
            f"refusing persisted schema_version {version!r}; this build understands "
            f"{LIFECYCLE_PERSISTENCE_SCHEMA_VERSION!r}"
        )
    checksum = payload.get("checksum")
    if not isinstance(checksum, str) or not checksum:
        raise LifecycleCorruptionError("persisted lifecycle state has no checksum")
    body = {k: v for k, v in payload.items() if k != "checksum"}
    if _sha256(_canonical(body)) != checksum:
        raise LifecycleCorruptionError("persisted lifecycle state failed its checksum")
    for key in ("registry", "performance"):
        if not isinstance(payload.get(key), dict):
            raise LifecycleCorruptionError(f"persisted lifecycle state is missing {key!r}")
    return payload


def _verify_history_chain(registry: DynamicStrategyRegistry) -> None:
    """The materialised state must agree with its own append-only history."""
    for sid in registry.strategy_ids():
        history = registry.history(sid)
        chain_state: LifecycleState | None = None
        for entry in history:
            src = LifecycleState(entry["from_state"])
            dst = LifecycleState(entry["to_state"])
            if chain_state is not None and src is not chain_state:
                raise LifecycleCorruptionError(
                    f"{sid}: history is not a chain ({chain_state.value} -> {src.value})"
                )
            chain_state = dst
        current = registry.state_of(sid)
        if chain_state is not None and chain_state is not current:
            raise LifecycleCorruptionError(
                f"{sid}: materialised state {current} disagrees with history {chain_state}"
            )


def restore_ecosystem(eco: DynamicStrategyEcosystem, payload: Any) -> None:
    """Validate and apply a persisted snapshot. Fail closed on any problem."""
    verified = _verify(payload)
    try:
        registry = DynamicStrategyRegistry.from_state(verified["registry"])
        performance = ContextualPerformanceStore.from_state(verified["performance"])
    except LifecyclePersistenceError:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise LifecycleCorruptionError(f"persisted lifecycle state is malformed: {exc}") from exc
    _verify_history_chain(registry)

    eco.registry = registry
    eco.performance = performance
    health = verified.get("health")
    if isinstance(health, dict):
        eco._health = {str(k): str(v) for k, v in health.items()}


# --------------------------------------------------------------------------- #
# Atomic file I/O
# --------------------------------------------------------------------------- #


def save_ecosystem(
    path: Path,
    eco: DynamicStrategyEcosystem,
    *,
    run_id: str = "",
    commit_sha: str = "",
    persisted_at_ms: int = 0,
) -> Path:
    """Atomically persist the snapshot. A partial write is impossible."""
    payload = snapshot_ecosystem(
        eco, run_id=run_id, commit_sha=commit_sha, persisted_at_ms=persisted_at_ms
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(_canonical(payload) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem
    return path


def load_ecosystem(path: Path, eco: DynamicStrategyEcosystem) -> dict[str, Any]:
    """Read and restore a snapshot. A missing/corrupt file raises."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LifecyclePersistenceError(f"no persisted lifecycle state at {path}") from exc
    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LifecycleCorruptionError(
            f"persisted lifecycle state is not valid JSON: {exc}"
        ) from exc
    restore_ecosystem(eco, payload)
    return payload


# --------------------------------------------------------------------------- #
# Deterministic state hash + replay (§7)
# --------------------------------------------------------------------------- #


def ecosystem_state_hash(eco: DynamicStrategyEcosystem) -> str:
    """Hash of the *authoritative* state only (descriptors + observations)."""
    body = {
        "registry": eco.registry.to_state(),
        "performance": eco.performance.to_state(),
    }
    return _sha256(_canonical(body))


def replay_lifecycle(
    start_state: LifecycleState,
    history: Iterable[dict[str, Any]],
) -> LifecycleState:
    """Reconstruct a strategy's state by replaying its history from ``start_state``.

    Deterministic: given the same start state and the same ordered history, the
    result is identical. A broken chain raises rather than guessing.
    """
    state = start_state
    for entry in history:
        src = LifecycleState(entry["from_state"])
        if src is not state:
            raise LifecycleCorruptionError(
                f"replay: history row starts at {src.value} but the replayed state is {state.value}"
            )
        state = LifecycleState(entry["to_state"])
    return state
