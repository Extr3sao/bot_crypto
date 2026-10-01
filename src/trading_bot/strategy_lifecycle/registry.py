"""DynamicStrategyRegistry — the versioned source of truth (§15/§16/§24).

Holds descriptors, applies lifecycle decisions (re-checking the transition
graph), keeps append-only promotion/demotion history and emits the canonical
events. It also counts activation churn, because a system that constantly
flips strategies can overfit (§24).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from .contracts import (
    HealthState,
    LifecycleDecision,
    LifecycleState,
    StrategyDescriptor,
    StrategyEvent,
    StrategyEventType,
    assert_transition,
    event_for_state,
)

__all__ = ["REGISTRY_SCHEMA_VERSION", "ChurnMetrics", "DynamicStrategyRegistry"]

REGISTRY_SCHEMA_VERSION: Final[str] = "dynamic-strategy-registry-v1"

_ACTIVE_LINEAGE: Final[frozenset[LifecycleState]] = frozenset(
    {LifecycleState.ACTIVE, LifecycleState.DEGRADED, LifecycleState.THROTTLED}
)


@dataclass(frozen=True, slots=True)
class ChurnMetrics:
    """Activation churn (§24)."""

    activations: int = 0
    pauses: int = 0
    reactivations: int = 0
    promotions: int = 0
    reversals: int = 0
    time_active_ms: int = 0
    time_shadow_ms: int = 0
    transitions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "activations": self.activations,
            "pauses": self.pauses,
            "reactivations": self.reactivations,
            "promotions": self.promotions,
            "reversals": self.reversals,
            "time_active_ms": self.time_active_ms,
            "time_shadow_ms": self.time_shadow_ms,
            "transitions": self.transitions,
        }


@dataclass(frozen=True, slots=True)
class _HistoryEntry:
    from_state: LifecycleState
    to_state: LifecycleState
    timestamp_ms: int
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp_ms": self.timestamp_ms,
            "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class DynamicStrategyRegistry:
    """Versioned, append-only registry of strategies and their lifecycle."""

    _descriptors: dict[str, StrategyDescriptor] = field(default_factory=dict, repr=False)
    _versions: dict[str, list[StrategyDescriptor]] = field(default_factory=dict, repr=False)
    _history: dict[str, list[_HistoryEntry]] = field(default_factory=dict, repr=False)
    _events: list[StrategyEvent] = field(default_factory=list, repr=False)
    _churn: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)
    _state_since: dict[str, int] = field(default_factory=dict, repr=False)
    _degraded_streak: dict[str, int] = field(default_factory=dict, repr=False)
    _recovery_streak: dict[str, int] = field(default_factory=dict, repr=False)
    _last_activation_ms: dict[str, int] = field(default_factory=dict, repr=False)
    _last_demotion_ms: dict[str, int] = field(default_factory=dict, repr=False)
    _eligible_since_ms: dict[str, int] = field(default_factory=dict, repr=False)
    schema_version: str = REGISTRY_SCHEMA_VERSION

    # -- registration -------------------------------------------------------

    def register(self, descriptor: StrategyDescriptor) -> StrategyDescriptor:
        """Register (or update the descriptor of) a strategy version.

        Re-registering the same version without a state change is idempotent.
        A new state must go through :meth:`apply`, never through a silent
        re-register: registering does not promote.
        """
        sid = descriptor.strategy_id
        previous = self._descriptors.get(sid)
        if previous is None:
            self._descriptors[sid] = descriptor
            self._versions.setdefault(sid, []).append(descriptor)
            self._history.setdefault(sid, [])
            self._state_since[sid] = descriptor.updated_at_ms or descriptor.created_at_ms
            self._churn[sid] = {
                "activations": 0,
                "pauses": 0,
                "reactivations": 0,
                "promotions": 0,
                "reversals": 0,
                "time_active_ms": 0,
                "time_shadow_ms": 0,
                "transitions": 0,
            }
            self._emit(
                StrategyEventType.STRATEGY_REGISTERED,
                sid,
                descriptor.created_at_ms,
                None,
                descriptor.lifecycle_state,
            )
            return descriptor
        if previous.lifecycle_state is not descriptor.lifecycle_state:
            raise ValueError(
                f"{sid}: register() cannot change state "
                f"({previous.lifecycle_state.value} -> {descriptor.lifecycle_state.value}); "
                "use apply()"
            )
        self._descriptors[sid] = descriptor
        self._versions.setdefault(sid, []).append(descriptor)
        return descriptor

    # -- lifecycle application ----------------------------------------------

    def apply(self, decision: LifecycleDecision) -> StrategyDescriptor:
        """Apply (or refuse) a lifecycle decision, re-checking the graph."""
        sid = decision.strategy_id
        descriptor = self._descriptors.get(sid)
        if descriptor is None:
            raise KeyError(f"{sid} is not registered")
        current = descriptor.lifecycle_state
        # The decision is only valid against the state it was computed from.
        if decision.from_state is not current:
            raise ValueError(
                f"{sid}: decision is stale (computed from {decision.from_state.value}, "
                f"current is {current.value})"
            )
        target = decision.to_state
        if target is current:
            return descriptor
        assert_transition(sid, current, target, promotion=decision.promotion)

        now = decision.timestamp_ms
        self._bump_dwell(sid, current, now)
        updated = _replace_state(descriptor, target, now)
        self._descriptors[sid] = updated
        self._versions.setdefault(sid, []).append(updated)
        self._history.setdefault(sid, []).append(
            _HistoryEntry(current, target, now, decision.reason_codes, decision.evidence)
        )
        self._state_since[sid] = now
        self._update_counters(sid, current, target, now)

        event_type = event_for_state(target)
        if event_type is not None:
            self._emit(event_type, sid, now, current, target, decision.reason_codes, decision.evidence)
        elif target is not LifecycleState.VALIDATING:
            self._emit(
                StrategyEventType.STRATEGY_PROMOTION_REJECTED,
                sid,
                now,
                current,
                target,
                decision.reason_codes,
            )
        return updated

    def observe_health(self, strategy_id: str, health_state: HealthState) -> None:
        """Feed a health verdict so the controller's streaks are real and ordered."""
        if health_state in (HealthState.DEGRADED, HealthState.CRITICAL):
            self._degraded_streak[strategy_id] = self._degraded_streak.get(strategy_id, 0) + 1
            self._recovery_streak[strategy_id] = 0
        elif health_state is HealthState.HEALTHY:
            self._recovery_streak[strategy_id] = self._recovery_streak.get(strategy_id, 0) + 1
            self._degraded_streak[strategy_id] = 0
        else:  # WATCH / INSUFFICIENT_DATA reset both — no credit either way
            self._degraded_streak[strategy_id] = 0
            self._recovery_streak[strategy_id] = 0

    # -- reads ---------------------------------------------------------------

    def descriptor(self, strategy_id: str) -> StrategyDescriptor | None:
        return self._descriptors.get(strategy_id)

    def state_of(self, strategy_id: str) -> LifecycleState | None:
        d = self._descriptors.get(strategy_id)
        return None if d is None else d.lifecycle_state

    def strategy_ids(self) -> list[str]:
        return sorted(self._descriptors)

    def descriptors(self) -> list[StrategyDescriptor]:
        return [self._descriptors[sid] for sid in self.strategy_ids()]

    def by_state(self, state: LifecycleState) -> list[str]:
        return [sid for sid in self.strategy_ids() if self._descriptors[sid].lifecycle_state is state]

    def active_ids(self) -> list[str]:
        return [sid for sid in self.strategy_ids() if self._descriptors[sid].lifecycle_state is LifecycleState.ACTIVE]

    def version_history(self, strategy_id: str) -> list[StrategyDescriptor]:
        return list(self._versions.get(strategy_id, []))

    def history(self, strategy_id: str) -> list[dict[str, Any]]:
        return [h.to_dict() for h in self._history.get(strategy_id, [])]

    def events(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    def status_of(self, strategy_id: str) -> dict[str, Any] | None:
        d = self._descriptors.get(strategy_id)
        if d is None:
            return None
        return {
            "strategy_id": strategy_id,
            "strategy_version": d.strategy_version,
            "state": d.lifecycle_state.value,
            "state_since_ms": self._state_since.get(strategy_id, 0),
            "degraded_streak": self._degraded_streak.get(strategy_id, 0),
            "recovery_streak": self._recovery_streak.get(strategy_id, 0),
            "churn": dict(self._churn.get(strategy_id, {})),
        }

    def churn(self, strategy_id: str | None = None) -> dict[str, Any]:
        if strategy_id is not None:
            return ChurnMetrics(**_coerce(self._churn.get(strategy_id, {}))).to_dict()
        totals = {k: sum(c.get(k, 0) for c in self._churn.values()) for k in (
            "activations", "pauses", "reactivations", "promotions", "reversals",
            "time_active_ms", "time_shadow_ms", "transitions",
        )}
        return ChurnMetrics(**totals).to_dict()

    # -- helpers -------------------------------------------------------------

    def streaks(self, strategy_id: str) -> dict[str, int]:
        return {
            "degraded_streak": self._degraded_streak.get(strategy_id, 0),
            "recovery_streak": self._recovery_streak.get(strategy_id, 0),
            "last_activation_ms": self._last_activation_ms.get(strategy_id, 0),
            "last_demotion_ms": self._last_demotion_ms.get(strategy_id, 0),
            "eligible_since_ms": self._eligible_since_ms.get(strategy_id, 0),
        }

    def _update_counters(
        self,
        sid: str,
        current: LifecycleState,
        target: LifecycleState,
        now: int,
    ) -> None:
        churn = self._churn.setdefault(sid, {
            "activations": 0, "pauses": 0, "reactivations": 0,
            "promotions": 0, "reversals": 0, "time_active_ms": 0,
            "time_shadow_ms": 0, "transitions": 0,
        })
        churn["transitions"] += 1
        if target is LifecycleState.ACTIVE:
            churn["activations"] += 1
            self._last_activation_ms[sid] = now
        if target is LifecycleState.ELIGIBLE:
            self._eligible_since_ms[sid] = now
            churn["promotions"] += 1
        if current is LifecycleState.ELIGIBLE and target is LifecycleState.SHADOW:
            churn["reversals"] += 1
        if target is LifecycleState.PAUSED:
            churn["pauses"] += 1
            self._last_demotion_ms[sid] = now
        if current is LifecycleState.PAUSED and target is LifecycleState.SHADOW:
            churn["reactivations"] += 1
        if current in _ACTIVE_LINEAGE and target not in _ACTIVE_LINEAGE:
            self._last_demotion_ms[sid] = now

    def _bump_dwell(self, sid: str, state: LifecycleState, now: int) -> None:
        since = self._state_since.get(sid, now)
        elapsed = max(0, now - since)
        churn = self._churn.setdefault(sid, {
            "activations": 0, "pauses": 0, "reactivations": 0,
            "promotions": 0, "reversals": 0, "time_active_ms": 0,
            "time_shadow_ms": 0, "transitions": 0,
        })
        if state is LifecycleState.ACTIVE:
            churn["time_active_ms"] += elapsed
        if state is LifecycleState.SHADOW:
            churn["time_shadow_ms"] += elapsed

    def _emit(
        self,
        event_type: StrategyEventType,
        strategy_id: str,
        timestamp_ms: int,
        from_state: LifecycleState | None,
        to_state: LifecycleState | None,
        reason_codes: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
    ) -> None:
        self._events.append(
            StrategyEvent(
                event_type=event_type,
                strategy_id=strategy_id,
                timestamp_ms=timestamp_ms,
                from_state=from_state,
                to_state=to_state,
                reason_codes=reason_codes,
                evidence=evidence,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategies": {sid: d.to_dict() for sid, d in sorted(self._descriptors.items())},
            "status": {sid: self.status_of(sid) for sid in self.strategy_ids()},
            "history": {sid: self.history(sid) for sid in self.strategy_ids()},
            "events": self.events(),
            "churn": self.churn(),
        }


def _replace_state(
    descriptor: StrategyDescriptor, state: LifecycleState, now: int
) -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id=descriptor.strategy_id,
        strategy_version=descriptor.strategy_version,
        family=descriptor.family,
        assets=descriptor.assets,
        timeframes=descriptor.timeframes,
        supported_regimes=descriptor.supported_regimes,
        runtime_implementation=descriptor.runtime_implementation,
        deterministic=descriptor.deterministic,
        lifecycle_state=state,
        permissions=descriptor.permissions,
        validation_status=descriptor.validation_status,
        validation_evidence=descriptor.validation_evidence,
        provenance=descriptor.provenance,
        created_at_ms=descriptor.created_at_ms,
        updated_at_ms=now,
    )


def _coerce(raw: dict[str, int]) -> dict[str, int]:
    keys = (
        "activations", "pauses", "reactivations", "promotions", "reversals",
        "time_active_ms", "time_shadow_ms", "transitions",
    )
    return {k: int(raw.get(k, 0)) for k in keys}
