"""Strategy lifecycle and registry contract (§17, §19, §20, §36, §37, §41, §44).

The registry answers three questions, and only these three:

    1. Which strategies exist, and what do they need?   (§36, §37)
    2. What state is each one in?                        (§17)
    3. May this one execute PAPER right now?             (§18, §19)

Nothing in this module can promote a strategy into PAPER: transitions are a
closed graph checked edge by edge, and the one edge that matters —
``PAPER_CANDIDATE → PAPER_ACTIVE`` — additionally requires a
:class:`PromotionRecord` that names the evidence, the commit and the dataset it
was decided on. ``LIVE`` is not in the vocabulary, so no transition can reach
it even by accident (§46).

The runtime consumes :meth:`StrategyRegistry.strategy_map`, whose ``status``
field is the *real* lifecycle state — never a legacy ``CONFIRMED`` constant
(§19, DEF-AUTO-4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

from .admission_ledger import AdmissionLedger
from .contracts import (
    PAPER_AUTHORISING_STATUSES,
    PAPER_PROMOTABLE_STATUSES,
    AdmissionEntry,
    AdmissionStatus,
)

__all__ = [
    "AVAILABLE_PAPER_DATA",
    "DEFAULT_DATA_REQUIREMENTS",
    "FAMILY_DATA_REQUIREMENTS",
    "LIFECYCLE_STATES",
    "LIVE_STATUS_NAMES",
    "STATE_TRANSITIONS",
    "PromotionRecord",
    "StrategyRecord",
    "StrategyRegistry",
    "StrategyStateError",
    "allowed_transitions",
    "assert_transition",
    "can_transition",
    "is_paper_executable",
]

REGISTRY_SCHEMA_VERSION: Final[str] = "strategy-registry-v1"


class StrategyStateError(RuntimeError):
    """Raised when a lifecycle transition is not authorised."""


#: §17 — the operational states, in lifecycle order.
LIFECYCLE_STATES: Final[tuple[AdmissionStatus, ...]] = (
    AdmissionStatus.RESEARCH_REQUIRED,
    AdmissionStatus.PAPER_CANDIDATE,
    AdmissionStatus.PAPER_ACTIVE,
    AdmissionStatus.PAPER_RETIRED,
    AdmissionStatus.REJECTED,
)

#: §46 — the names that must never appear as a reachable state. The check is on
#: the *name*, so adding a live status has to break this assertion loudly rather
#: than quietly become reachable.
LIVE_STATUS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "LIVE",
        "LIVE_ACTIVE",
        "LIVE_CANDIDATE",
        "PRODUCTION",
        "PRODUCTION_ACTIVE",
        "REAL",
        "REAL_MONEY",
    }
)

#: §17/§21 — the complete transition graph. An edge that is not here does not
#: exist; there is no wildcard and no "any -> any" escape hatch.
STATE_TRANSITIONS: Final[dict[AdmissionStatus, frozenset[AdmissionStatus]]] = {
    # Research has not produced enough evidence yet. It may be re-researched
    # forever, become a candidate when every deterministic gate passes, or be
    # closed as rejected.
    AdmissionStatus.RESEARCH_REQUIRED: frozenset(
        {
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.PAPER_CANDIDATE,
            AdmissionStatus.REJECTED,
        }
    ),
    # A candidate is admitted for PAPER. It may be promoted explicitly, sent
    # back to research (broken evidence), or rejected.
    AdmissionStatus.PAPER_CANDIDATE: frozenset(
        {
            AdmissionStatus.PAPER_CANDIDATE,
            AdmissionStatus.PAPER_ACTIVE,
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.REJECTED,
        }
    ),
    # An active strategy may be retired, or sent back to research when its
    # evidence no longer holds. It may NOT quietly become a candidate again:
    # losing PAPER is not a promotion, and reactivating requires the same
    # admission path as the first time.
    AdmissionStatus.PAPER_ACTIVE: frozenset(
        {
            AdmissionStatus.PAPER_ACTIVE,
            AdmissionStatus.PAPER_RETIRED,
            AdmissionStatus.RESEARCH_REQUIRED,
        }
    ),
    # A retired strategy keeps its history and goes back to research to earn a
    # new admission. It can never jump straight back to active.
    AdmissionStatus.PAPER_RETIRED: frozenset(
        {
            AdmissionStatus.PAPER_RETIRED,
            AdmissionStatus.RESEARCH_REQUIRED,
        }
    ),
    # Rejected is terminal for this evidence set; re-opening means new research.
    AdmissionStatus.REJECTED: frozenset(
        {
            AdmissionStatus.REJECTED,
            AdmissionStatus.RESEARCH_REQUIRED,
        }
    ),
    # Verdict-less statuses behave like "needs research" for transition purposes.
    AdmissionStatus.UNKNOWN: frozenset(
        {
            AdmissionStatus.UNKNOWN,
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.REJECTED,
        }
    ),
    AdmissionStatus.RESEARCH_CANDIDATE: frozenset(
        {
            AdmissionStatus.RESEARCH_CANDIDATE,
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.PAPER_CANDIDATE,
            AdmissionStatus.REJECTED,
        }
    ),
    AdmissionStatus.COST_KILLED: frozenset(
        {
            AdmissionStatus.COST_KILLED,
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.REJECTED,
        }
    ),
    AdmissionStatus.NO_GROSS_EDGE: frozenset(
        {
            AdmissionStatus.NO_GROSS_EDGE,
            AdmissionStatus.RESEARCH_REQUIRED,
            AdmissionStatus.REJECTED,
        }
    ),
}


def _assert_no_live_state() -> None:
    """Fail closed at import time if a live state is ever added to the vocabulary."""
    offenders = sorted(
        status.value for status in AdmissionStatus if status.value.upper() in LIVE_STATUS_NAMES
    )
    if offenders:
        raise StrategyStateError(
            f"LIVE must not be reachable from the PAPER runtime: {offenders}"
        )
    for source, targets in STATE_TRANSITIONS.items():
        for target in targets:
            if target.value.upper() in LIVE_STATUS_NAMES:
                raise StrategyStateError(f"transition {source.value} -> {target.value} reaches LIVE")


_assert_no_live_state()


def allowed_transitions(status: AdmissionStatus) -> frozenset[AdmissionStatus]:
    """Targets an authorised state change may reach (``{status}`` = stay put)."""
    return STATE_TRANSITIONS.get(status, frozenset({status}))


def can_transition(source: AdmissionStatus, target: AdmissionStatus) -> bool:
    return target in allowed_transitions(source)


def is_paper_executable(status: AdmissionStatus) -> bool:
    """May a strategy in this state place PAPER orders? (§18)"""
    return status in PAPER_AUTHORISING_STATUSES


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """§41 — the audit trail for the one transition that needs a decision.

    ``PAPER_CANDIDATE → PAPER_ACTIVE`` is the only promotion in the system, and
    it is never inferred from a number: somebody (or some deterministic gate)
    has to produce this record, and the record has to name the evidence, the
    commit and the dataset behind the decision.
    """

    promotion_id: str
    strategy_id: str
    from_status: AdmissionStatus
    to_status: AdmissionStatus
    evidence: tuple[str, ...]
    commit: str
    dataset: str
    decision: str
    decided_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self) -> None:
        if self.from_status not in PAPER_PROMOTABLE_STATUSES:
            raise ValueError(
                f"promotion must start from one of "
                f"{sorted(s.value for s in PAPER_PROMOTABLE_STATUSES)}, "
                f"got {self.from_status.value}"
            )
        if self.to_status is not AdmissionStatus.PAPER_ACTIVE:
            raise ValueError(f"promotion target must be PAPER_ACTIVE, got {self.to_status.value}")
        if not self.evidence:
            raise ValueError("promotion requires at least one evidence reference")
        if not self.commit:
            raise ValueError("promotion must name the commit it was decided on")
        if not self.dataset:
            raise ValueError("promotion must name the dataset it was decided on")

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "strategy_id": self.strategy_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "evidence": list(self.evidence),
            "commit": self.commit,
            "dataset": self.dataset,
            "decision": self.decision,
            "decided_at_ms": self.decided_at_ms,
        }


def assert_transition(
    strategy_id: str,
    source: AdmissionStatus,
    target: AdmissionStatus,
    *,
    promotion: PromotionRecord | None = None,
) -> None:
    """Authorise (or refuse) one lifecycle move, loudly."""
    if not can_transition(source, target):
        raise StrategyStateError(
            f"{strategy_id}: transition {source.value} -> {target.value} is not authorised "
            f"(allowed: {sorted(s.value for s in allowed_transitions(source))})"
        )
    if source in PAPER_PROMOTABLE_STATUSES and target is AdmissionStatus.PAPER_ACTIVE:
        if promotion is None:
            raise StrategyStateError(
                f"{strategy_id}: {source.value} -> PAPER_ACTIVE requires a PromotionRecord"
            )
        if promotion.strategy_id != strategy_id:
            raise StrategyStateError(
                f"{strategy_id}: promotion record belongs to {promotion.strategy_id}"
            )


# ------------------------------------------------------------------------- data
#: §12 — what the PAPER runtime can actually consume today: public OHLCV bars.
AVAILABLE_PAPER_DATA: Final[frozenset[str]] = frozenset({"ohlcv"})

#: §36/§37 — per-family data requirements. The committed alpha families reason
#: over OHLCV only; anything that needs microstructure must say so here, and it
#: then cannot activate until the collector's data readiness covers it.
FAMILY_DATA_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {
    "ema_crossover": ("ohlcv",),
    "momentum": ("ohlcv",),
    "breakout": ("ohlcv",),
    "trend": ("ohlcv",),
    "mean_reversion": ("ohlcv",),
    "volatility": ("ohlcv",),
}

DEFAULT_DATA_REQUIREMENTS: Final[tuple[str, ...]] = ("ohlcv",)

#: Features each family computes for itself, recorded so a strategy's inputs are
#: explicit rather than implied by its name.
FAMILY_FEATURE_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {
    "ema_crossover": ("ema_fast", "ema_slow"),
    "momentum": ("momentum_lookback",),
    "breakout": ("donchian_high", "donchian_low"),
    "trend": ("trend_slope",),
    "mean_reversion": ("zscore", "rolling_mean"),
    "volatility": ("atr", "realized_vol"),
}


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    """§36 — everything a strategy must be able to state about itself."""

    strategy_id: str
    version: str
    family: str
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    required_data: tuple[str, ...]
    required_features: tuple[str, ...]
    admission_status: AdmissionStatus
    evidence_ids: tuple[str, ...]
    expected_gross_edge_bps: float | None = None
    admitted_for_paper: bool = False
    schema_version: str = REGISTRY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "family": self.family,
            "assets": list(self.assets),
            "timeframes": list(self.timeframes),
            "required_data": list(self.required_data),
            "required_features": list(self.required_features),
            "admission_status": self.admission_status.value,
            "evidence_ids": list(self.evidence_ids),
            "expected_gross_edge_bps": self.expected_gross_edge_bps,
            "admitted_for_paper": self.admitted_for_paper,
            "schema_version": self.schema_version,
        }

    def data_readiness(self, available: frozenset[str] | set[str]) -> tuple[bool, str]:
        """§37 — fail closed when the data a strategy needs does not exist."""
        missing = sorted(set(self.required_data) - set(available))
        if missing:
            return False, f"missing required data: {missing}"
        return True, "data requirements satisfied"

    def paper_executable(
        self, available: frozenset[str] | set[str] = AVAILABLE_PAPER_DATA
    ) -> tuple[bool, str]:
        """Authorised *and* fed: two independent reasons to refuse."""
        if not is_paper_executable(self.admission_status):
            return False, f"status {self.admission_status.value} does not authorise PAPER"
        if not self.admitted_for_paper:
            return False, "not admitted for paper by the admission ledger"
        return self.data_readiness(available)

    def registry_spec(self, *, priority: float = 0.0) -> dict[str, Any]:
        """The runtime's strategy_map entry.

        ``status`` is the lifecycle state, never a legacy ``CONFIRMED``/``
        ``RESEARCH_ONLY`` constant: the router and every trace read the same
        vocabulary the ledger does (DEF-AUTO-4).
        """
        return {
            "family": self.family,
            "regimes": [],
            "direction": "BOTH",
            "enabled": True,
            "status": self.admission_status.value,
            "priority": priority,
        }


@dataclass(frozen=True, slots=True)
class StrategyRegistry:
    """The immutable view of every known strategy, built from the ledger."""

    records: dict[str, StrategyRecord]
    source: str
    ledger_sources: tuple[dict[str, str], ...] = ()
    schema_version: str = REGISTRY_SCHEMA_VERSION

    # -- construction -------------------------------------------------------

    @classmethod
    def from_ledger(
        cls,
        ledger: AdmissionLedger,
        *,
        assets: tuple[str, ...] | list[str] = (),
        available_data: frozenset[str] = AVAILABLE_PAPER_DATA,
    ) -> StrategyRegistry:
        asset_list = tuple(dict.fromkeys(str(a).upper() for a in assets))
        records: dict[str, StrategyRecord] = {}
        for strategy_id, entry in sorted(ledger.entries().items()):
            records[strategy_id] = _record_for(
                strategy_id, entry, assets=asset_list, ledger=ledger
            )
        registry = cls(
            records=records,
            source=ledger.source_path,
            ledger_sources=tuple(ledger.sources),
        )
        registry.assert_consistent(available_data)
        return registry

    # -- invariants ---------------------------------------------------------

    def assert_consistent(self, available_data: frozenset[str] = AVAILABLE_PAPER_DATA) -> None:
        """Refuse a registry whose contents contradict the lifecycle."""
        for strategy_id, record in self.records.items():
            status = record.admission_status
            if status is AdmissionStatus.PAPER_ACTIVE and not is_paper_executable(status):
                raise StrategyStateError(f"{strategy_id}: PAPER_ACTIVE is not paper-executable")
            if status in (AdmissionStatus.PAPER_ACTIVE, AdmissionStatus.PAPER_CANDIDATE):
                ready, reason = record.data_readiness(available_data)
                if not ready:
                    raise StrategyStateError(
                        f"{strategy_id}: {status.value} requires data it cannot get ({reason})"
                    )

    # -- queries ------------------------------------------------------------

    def strategy_ids(self) -> list[str]:
        return sorted(self.records)

    def record(self, strategy_id: str) -> StrategyRecord | None:
        return self.records.get(strategy_id)

    def by_status(self, status: AdmissionStatus) -> dict[str, StrategyRecord]:
        return {
            sid: record
            for sid, record in sorted(self.records.items())
            if record.admission_status is status
        }

    def counts_by_status(self) -> dict[str, int]:
        counts = {status.value: 0 for status in AdmissionStatus}
        for record in self.records.values():
            counts[record.admission_status.value] += 1
        return counts

    def for_timeframe(self, timeframe: str) -> dict[str, StrategyRecord]:
        return {
            sid: record
            for sid, record in sorted(self.records.items())
            if timeframe in record.timeframes
        }

    def paper_candidates(self, timeframe: str | None = None) -> list[str]:
        return sorted(
            sid
            for sid, record in self.records.items()
            if (timeframe is None or timeframe in record.timeframes)
            and record.paper_executable()[0]
        )

    def refusals(
        self, timeframe: str | None = None, available: frozenset[str] = AVAILABLE_PAPER_DATA
    ) -> list[dict[str, Any]]:
        """Why each non-executable strategy cannot trade — never silently empty."""
        out: list[dict[str, Any]] = []
        for sid, record in sorted(self.records.items()):
            if timeframe is not None and timeframe not in record.timeframes:
                continue
            ok, reason = record.paper_executable(available)
            if not ok:
                out.append(
                    {
                        "strategy_id": sid,
                        "status": record.admission_status.value,
                        "reason": reason,
                    }
                )
        return out

    def strategy_map(
        self,
        timeframe: str,
        *,
        priorities: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """The runtime's strategy map for one timeframe, from real state."""
        priorities = priorities or {}
        return {
            sid: record.registry_spec(priority=float(priorities.get(sid, 0.0)))
            for sid, record in self.for_timeframe(timeframe).items()
        }

    def paper_activations(self, timeframe: str) -> dict[str, StrategyRecord]:
        return {
            sid: record
            for sid, record in self.for_timeframe(timeframe).items()
            if record.paper_executable()[0]
        }

    def describe(self, timeframe: str) -> list[str]:
        """Operator-facing summary: the states, and why nothing can trade.

        Shared by the entrypoints so a legacy and a canonical launcher cannot
        disagree about what the ledger says.
        """
        counts = self.counts_by_status()
        states = " ".join(
            f"{state}={counts[state]}" for state in sorted(counts) if counts[state]
        )
        lines = [
            f"[registry] {states or 'no strategies'}",
            f"[registry] paper-executable on {timeframe}: "
            f"{self.paper_candidates(timeframe) or 'NONE'}",
        ]
        for refusal in self.refusals(timeframe):
            lines.append(
                f"[registry]   refused {refusal['strategy_id']}: "
                f"{refusal['status']} — {refusal['reason']}"
            )
        return lines

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "ledger_sources": list(self.ledger_sources),
            "counts": self.counts_by_status(),
            "lifecycle_states": [status.value for status in LIFECYCLE_STATES],
            "strategies": {sid: record.to_dict() for sid, record in sorted(self.records.items())},
        }


def _record_for(
    strategy_id: str,
    entry: AdmissionEntry,
    *,
    assets: tuple[str, ...],
    ledger: AdmissionLedger,
) -> StrategyRecord:
    family = entry.family
    evidence = ledger.evidence_ids(strategy_id)
    return StrategyRecord(
        strategy_id=strategy_id,
        version=f"{family}@{entry.timeframe}",
        family=family,
        assets=assets,
        timeframes=(entry.timeframe,),
        required_data=FAMILY_DATA_REQUIREMENTS.get(family, DEFAULT_DATA_REQUIREMENTS),
        required_features=FAMILY_FEATURE_REQUIREMENTS.get(family, ()),
        admission_status=entry.status,
        evidence_ids=evidence,
        expected_gross_edge_bps=entry.expected_gross_edge_bps,
        admitted_for_paper=entry.admitted_for_paper,
    )
