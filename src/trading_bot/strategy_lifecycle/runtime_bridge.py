"""Runtime bridge — make the lifecycle plane reachable from the PAPER runtime.

WP-STRAT-07. The dynamic plane (registry/health/lifecycle/selector) existed but
was only reachable from scripts and tests; the hot PAPER loop still used the
legacy single-winner ``StrategyRouter.route``. This module is the seam:

* it defines the three routing modes (``LEGACY`` / ``SHADOW`` / ``LIFECYCLE``);
* it maps the runtime's own admission vocabulary onto the dynamic lifecycle
  vocabulary, so the lifecycle plane can only ever *restrict* what the ledger
  already admitted — it can never widen execution;
* it produces a ``StrategyRoutingComparison`` recording, for the same context,
  what the legacy router chose and what the lifecycle-aware selector would have
  chosen, with every refusal named.

No LIVE mode exists. The selector is delegated to the router (duck-typed as
``Any``), so this module keeps the research package's dependency direction and
imports nothing from it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from .contracts import LifecycleState

__all__ = [
    "ADMISSION_TO_LIFECYCLE",
    "ROUTING_BRIDGE_SCHEMA_VERSION",
    "LifecycleRoutingAdapter",
    "StrategyRoutingComparison",
    "StrategyRoutingMode",
    "lifecycle_state_for_admission",
]

ROUTING_BRIDGE_SCHEMA_VERSION: Final[str] = "strategy-routing-bridge-v1"


class StrategyRoutingMode(StrEnum):
    """How the runtime consults the strategy plane (§4/§5).

    * ``LEGACY``    — the historical ``route()`` path only; behaviour unchanged.
    * ``SHADOW``    — ``LEGACY`` execution, plus a recorded comparison against
                      the lifecycle-aware selection. Never affects execution.
    * ``LIFECYCLE`` — PAPER only: the lifecycle-aware eligible set gates which
                      strategies may produce an executable proposal.

    There is deliberately no LIVE member; PAPER can never promote itself.
    """

    LEGACY = "LEGACY"
    SHADOW = "SHADOW"
    LIFECYCLE = "LIFECYCLE"


def coerce_routing_mode(mode: StrategyRoutingMode | str) -> StrategyRoutingMode:
    """Parse a mode from a string or enum; fail closed on anything unknown."""
    if isinstance(mode, StrategyRoutingMode):
        return mode
    try:
        return StrategyRoutingMode(str(mode).upper())
    except ValueError as exc:
        raise ValueError(
            f"unknown strategy routing mode {mode!r}; "
            f"expected one of {[m.value for m in StrategyRoutingMode]}"
        ) from exc


#: The runtime's admission vocabulary → the dynamic lifecycle vocabulary.
#:
#: Only ``PAPER_ACTIVE`` maps to ``ACTIVE`` (the one state the lifecycle-aware
#: router selects). Every other admission status maps to a state that does NOT
#: route, so the dynamic plane can only ever shrink the legacy eligible set —
#: it can never authorise a strategy the ledger did not admit. ``PAPER_CANDIDATE``
#: (a legacy executable state) maps to ``SHADOW``: still evaluated, never
#: executable under ``LIFECYCLE`` mode.
ADMISSION_TO_LIFECYCLE: dict[str, str] = {
    "PAPER_ACTIVE": LifecycleState.ACTIVE.value,
    "PAPER_CANDIDATE": LifecycleState.SHADOW.value,
    "PAPER_RETIRED": LifecycleState.RETIRED.value,
    "REJECTED": LifecycleState.RETIRED.value,
    "COST_KILLED": LifecycleState.PAUSED.value,
    "NO_GROSS_EDGE": LifecycleState.PAUSED.value,
    "RESEARCH_REQUIRED": LifecycleState.DISCOVERED.value,
    "RESEARCH_CANDIDATE": LifecycleState.CANDIDATE.value,
    "UNKNOWN": LifecycleState.DISCOVERED.value,
}


def lifecycle_state_for_admission(status: Any) -> str:
    """Map an ``AdmissionStatus`` (or its string) to a lifecycle state value.

    Unknown values fail closed to ``DISCOVERED`` (a state that does not route).
    """
    name = str(getattr(status, "value", status)).upper()
    return ADMISSION_TO_LIFECYCLE.get(name, LifecycleState.DISCOVERED.value)


@dataclass(frozen=True, slots=True)
class StrategyRoutingComparison:
    """Same-context legacy vs lifecycle-aware routing decision (§6).

    This is the evidence artifact of ``SHADOW`` mode: for one asset at one
    decision time it records what each plane selected, every refusal the
    lifecycle plane named, and the differences between the two.
    """

    run_id: str
    decision_time_ms: int
    asset: str
    timeframe: str
    regime: str | None
    legacy_selected: tuple[str, ...]
    lifecycle_selected: tuple[str, ...]
    lifecycle_rejected: dict[str, str]
    differences: tuple[str, ...]
    reason_codes: tuple[str, ...]
    registry_version: str
    policy_version: str
    config_hash: str
    #: §12 — strategies dropped by portfolio conflict arbitration (can only reduce).
    portfolio_rejected: dict[str, str] = field(default_factory=dict)
    schema_version: str = ROUTING_BRIDGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "decision_time_ms": self.decision_time_ms,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "legacy": {"selected": list(self.legacy_selected)},
            "lifecycle": {
                "selected": list(self.lifecycle_selected),
                "rejected": dict(self.lifecycle_rejected),
            },
            "differences": list(self.differences),
            "reason_codes": list(self.reason_codes),
            "portfolio_rejected": dict(self.portfolio_rejected),
            "registry_version": self.registry_version,
            "policy_version": self.policy_version,
            "config_hash": self.config_hash,
        }


def _config_hash(*, mode: str, strategy_map: dict[str, Any], lifecycle: dict[str, str]) -> str:
    """Deterministic fingerprint of the routing inputs (§14 provenance)."""
    payload = {
        "mode": mode,
        "strategies": sorted(strategy_map),
        "lifecycle": {k: lifecycle[k] for k in sorted(lifecycle)},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class LifecycleRoutingAdapter:
    """Builds the lifecycle/health inputs and records the comparison.

    ``lifecycle_override`` lets a loaded, persisted ``DynamicStrategyEcosystem``
    supply the authoritative dynamic states; where it has no entry the adapter
    falls back to the ledger's own admission status. It never invents an ACTIVE
    state that neither source asserts.
    """

    registry_version: str = "admission-ledger"
    policy_version: str = ROUTING_BRIDGE_SCHEMA_VERSION
    lifecycle_override: dict[str, str] = field(default_factory=dict)

    def lifecycle_map(
        self, strategy_map: dict[str, Any], ledger: Any
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        for sid in strategy_map:
            override = self.lifecycle_override.get(sid)
            if override is not None:
                out[sid] = str(override).upper()
            else:
                status_for = getattr(ledger, "status_for", None)
                status = status_for(sid) if callable(status_for) else "UNKNOWN"
                out[sid] = lifecycle_state_for_admission(status)
        return out

    def select(
        self,
        router: Any,
        *,
        context: Any,
        regime: str | None,
        strategy_map: dict[str, Any],
        ledger: Any,
        health: dict[str, str] | None = None,
        performance: dict[str, float] | None = None,
        risk_blocked: frozenset[str] | set[str] = frozenset(),
        portfolio_rejected: frozenset[str] | set[str] = frozenset(),
    ) -> tuple[Any, dict[str, str]]:
        """Delegate to the router's lifecycle-aware selector."""
        lifecycle = self.lifecycle_map(strategy_map, ledger)
        selection = router.select_eligible_strategies(
            context,
            regime,
            strategy_map,
            lifecycle=lifecycle,
            health=health,
            performance=performance,
            risk_blocked=risk_blocked,
            portfolio_rejected=portfolio_rejected,
        )
        return selection, lifecycle

    def compare(
        self,
        router: Any,
        *,
        run_id: str,
        context: Any,
        regime: str | None,
        strategy_map: dict[str, Any],
        ledger: Any,
        legacy_selected: tuple[str, ...],
        decision_time_ms: int,
        asset: str,
        timeframe: str,
        mode: StrategyRoutingMode,
        health: dict[str, str] | None = None,
        performance: dict[str, float] | None = None,
        portfolio_rejected: dict[str, str] | None = None,
    ) -> StrategyRoutingComparison:
        selection, lifecycle = self.select(
            router,
            context=context,
            regime=regime,
            strategy_map=strategy_map,
            ledger=ledger,
            health=health,
            performance=performance,
        )
        lifecycle_selected = tuple(selection.selected)
        rejected: dict[str, str] = {}
        for item in selection.routed:
            if item.verdict != "SELECTED":
                rejected[item.strategy_id] = item.verdict

        differences: list[str] = []
        legacy_set = set(legacy_selected)
        lifecycle_set = set(lifecycle_selected)
        for sid in sorted(lifecycle_set - legacy_set):
            differences.append(f"LIFECYCLE_ONLY:{sid}")
        for sid in sorted(legacy_set - lifecycle_set):
            differences.append(f"LEGACY_ONLY:{sid}")
        if not differences:
            differences.append("AGREE")

        reason_codes = tuple(sorted({f"{sid}:{verdict}" for sid, verdict in rejected.items()}))

        return StrategyRoutingComparison(
            run_id=run_id,
            decision_time_ms=decision_time_ms,
            asset=asset,
            timeframe=timeframe,
            regime=regime,
            legacy_selected=tuple(sorted(legacy_set)),
            lifecycle_selected=tuple(sorted(lifecycle_set)),
            lifecycle_rejected=rejected,
            differences=tuple(differences),
            reason_codes=reason_codes,
            registry_version=self.registry_version,
            policy_version=self.policy_version,
            config_hash=_config_hash(
                mode=mode.value, strategy_map=strategy_map, lifecycle=lifecycle
            ),
            portfolio_rejected=dict(portfolio_rejected or {}),
        )
