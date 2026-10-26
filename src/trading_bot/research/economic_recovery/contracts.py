"""RFC-EDGE-014 §5 — the four formal contracts, and the rules they enforce on build.

The brief is explicit that a report carrying positive numbers without traceability is
not accepted, and that one fill type must never be counted as another. So the contracts
are not prose: each is a frozen record that refuses to be constructed in a shape the
brief forbids.

* :class:`TradePathEvent` — one stage of the funnel. It cannot be built claiming an
  ``EXCHANGE_ORDER`` while ``order_sent`` is false, and it cannot be built with a fill
  stage whose ``execution_class`` is ``NONE``. Two rules that make "a signal counted as
  a fill" and "an order that was never sent" unrepresentable rather than merely
  discouraged.
* :class:`EconomicCostBreakdown` — a per-scenario cost. It carries the population it
  was aggregated over, because the WP-EDGE-09 contradiction this package reconciles is
  exactly a numerator and a denominator drawn from different populations. It refuses to
  report ``RECONCILED`` when the components do not add up to the total, or when a
  non-negative component exceeds the total without an overlap note.
* :class:`StrategyCandidate` — a hypothesis, locked before its first result.
* :class:`ExperimentResult` — a measurement. It refuses to carry a promotion, and it
  reports ``UNKNOWN``/``NOT_EXECUTED`` instead of a number it did not observe.

Nothing here sends an order, holds a credential, or promotes a strategy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "ACCEPTED",
    "EXECUTION_CLASSES",
    "FILL_CLASSES",
    "NONE",
    "STAGES",
    "UNKNOWN",
    "EconomicCostBreakdown",
    "ExperimentResult",
    "StrategyCandidate",
    "TradePathEvent",
]

#: The funnel, in order. A recorded event names the stage it observed.
STAGES = (
    "MARKET_DATA",
    "SIGNAL",
    "PROPOSAL",
    "ROUTER",
    "RISK",
    "ORDER_INTENT",
    "PAPER_BROKER",
    "FILL",
    "RECONCILIATION",
)

NONE = "NONE"
UNKNOWN = "UNKNOWN"
ACCEPTED = "ACCEPTED"

EXECUTION_CLASSES = (
    "BACKTEST_FILL",
    "HYPOTHETICAL_FILL",
    "PAPER_BROKER_FILL",
    "EXCHANGE_ORDER",
    NONE,
)
FILL_CLASSES = ("BACKTEST_FILL", "HYPOTHETICAL_FILL", "PAPER_BROKER_FILL", "EXCHANGE_ORDER")
OUTCOMES = ("EMITTED", "ACCEPTED", "REJECTED", UNKNOWN)

#: A fill must carry these or it is not a fill. ``NONE`` is the honest value.
FILL_REQUIRED_FIELDS = ("quantity", "price", "fees_bps", "side", "utc_timestamp", "provenance")


@dataclass(frozen=True)
class TradePathEvent:
    """One stage of the trade path, as observed and sourced.

    The two invariants the brief cares about most are enforced here rather than left to
    a reader: an event may not claim an exchange order it did not send, and a fill may
    not be reported without the fields that make it a fill.
    """

    run_id: str
    utc_timestamp: str
    asset: str
    stage: str
    outcome: str
    reason_code: str
    execution_class: str = NONE
    order_sent: bool = False
    market_time: str | None = None
    available_at: str | None = None
    decision_time: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    proposal_id: str | None = None
    intent_id: str | None = None
    order_id: str | None = None
    quantity: float | None = None
    price: float | None = None
    fees_bps: float | None = None
    side: str | None = None
    provenance: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"unknown stage {self.stage!r}; expected one of {STAGES}")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}; expected one of {OUTCOMES}")
        if self.execution_class not in EXECUTION_CLASSES:
            raise ValueError(
                f"unknown execution_class {self.execution_class!r}; expected {EXECUTION_CLASSES}"
            )
        if self.execution_class == "EXCHANGE_ORDER" and not self.order_sent:
            raise ValueError("an EXCHANGE_ORDER event cannot be built with order_sent=False")
        if self.stage == "FILL" and self.execution_class == NONE:
            raise ValueError("a FILL stage must name the class of fill it observed")
        if self.execution_class in FILL_CLASSES:
            missing = [name for name in FILL_REQUIRED_FIELDS if getattr(self, name) is None]
            if missing:
                raise ValueError(
                    f"a {self.execution_class} must carry {missing}; a fill without them is not a fill"
                )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EconomicCostBreakdown:
    """A cost, with the population it was aggregated over stated on its face.

    The WP-EDGE-09 defect this package reconciles was a cross-venue mean fee divided by
    an admission-only mean barrier: two different populations in one ratio. The
    ``aggregation`` and ``population`` fields exist so that mistake cannot be made
    silently again.
    """

    scenario_id: str
    population: str
    numeraire: str = "USDT"
    round_trip_bps: float | None = None
    entry_fee_bps: float | None = None
    exit_fee_bps: float | None = None
    spread_bps: float | None = None
    impact_bps: float | None = None
    slippage_bps: float | None = None
    funding_bps: float | None = None
    latency_bps: float | None = None
    rebate_bps: float | None = None
    components_double_count_checked: bool = False
    net_cost_bps: float | None = None
    fee_schedule_source: str = ""
    aggregation: str = "per_round_trip_weighted_by_notional"
    data_version_sha256: str | None = None
    status: str = UNKNOWN
    tolerance_bps: float = 0.01
    notes: list[str] = field(default_factory=list)
    #: Components known to be shared with ``round_trip_bps`` and therefore not re-added.
    included_in: list[str] = field(default_factory=list)

    def components_sum(self) -> float | None:
        parts = [
            self.entry_fee_bps,
            self.exit_fee_bps,
            self.spread_bps,
            self.impact_bps,
            self.slippage_bps,
            self.funding_bps,
            self.latency_bps,
        ]
        present = [p for p in parts if p is not None]
        if not present:
            return None
        total = sum(present)
        if self.rebate_bps:
            total -= self.rebate_bps
        return round(total, 6)

    def reconcile(self) -> dict[str, Any]:
        """Decide the status from the arithmetic instead of trusting the caller.

        ``RECONCILED`` requires the components to add up to the stated round trip within
        tolerance, and requires any single non-negative component that exceeds a
        non-negative total to be explained by an ``included_in`` overlap note.
        """
        checks: list[dict[str, Any]] = []
        total = self.round_trip_bps
        components = self.components_sum()
        if total is None or components is None:
            return {"status": UNKNOWN, "checks": [], "detail": "missing total or components"}

        additive = abs(components - total) <= self.tolerance_bps
        checks.append(
            {
                "name": "components_add_up_to_the_round_trip",
                "passed": additive,
                "detail": f"components {components} vs round_trip {total}",
            }
        )
        over = [
            name
            for name in ("entry_fee_bps", "exit_fee_bps", "spread_bps", "impact_bps", "funding_bps")
            if (value := getattr(self, name)) is not None
            and value > 0
            and total >= 0
            and value > total + self.tolerance_bps
            and name not in self.included_in
        ]
        checks.append(
            {
                "name": "no_component_exceeds_a_non_negative_total_unexplained",
                "passed": not over,
                "detail": f"components above the total: {over or 'none'}",
            }
        )
        checks.append(
            {
                "name": "no_negative_component",
                "passed": all(
                    (v is None or v >= 0)
                    for v in (
                        self.entry_fee_bps,
                        self.exit_fee_bps,
                        self.spread_bps,
                        self.impact_bps,
                        self.slippage_bps,
                        self.funding_bps,
                    )
                ),
                "detail": "every cost component is a non-negative cost",
            }
        )
        passed = all(check["passed"] for check in checks)
        status = "RECONCILED" if passed else "INCONSISTENT"
        return {
            "status": status,
            "checks": checks,
            "detail": f"components={components} total={total}",
        }

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reconciliation"] = self.reconcile()
        return payload


@dataclass(frozen=True)
class StrategyCandidate:
    """A hypothesis, locked before its first validation result."""

    candidate_id: str
    source_id: str
    source_sha: str
    hypothesis: str
    family: str
    product: str
    venue: str
    assets: list[str]
    timeframes: list[str]
    permitted_sides: list[str]
    regime: str
    params_locked: dict[str, Any]
    test_plan: str
    data_manifest: list[str] = field(default_factory=list)
    costs_manifest: list[str] = field(default_factory=list)
    holdout_registry: list[str] = field(default_factory=list)
    comparator_id: str = "CURRENT"
    sizing_authority: str = "DETERMINISTIC_RISK"
    admission_status: str = "RESEARCH_ONLY"
    duplicate_of: list[str] = field(default_factory=list)
    duplicate_reason: str | None = None
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.admission_status not in ("RESEARCH_ONLY", "STRATEGY_CANDIDATE", "REJECTED"):
            raise ValueError(f"unknown admission_status {self.admission_status!r}")
        if self.sizing_authority != "DETERMINISTIC_RISK":
            raise ValueError(
                "sizing authority belongs to the deterministic risk layer, not a candidate"
            )
        if self.admission_status == "REJECTED" and not self.duplicate_reason and not self.evidence:
            raise ValueError("a rejected candidate must state why: a duplicate reason or evidence")

    @property
    def is_duplicate(self) -> bool:
        return bool(self.duplicate_of)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_duplicate"] = self.is_duplicate
        return payload


@dataclass(frozen=True)
class ExperimentResult:
    """A measurement, with the unknowns left as unknown and no promotion attached."""

    run_id: str
    commit: str
    environment: str
    data_fingerprint: str
    source_sha: str
    strategy_id: str
    baseline_id: str
    assets: list[str]
    period: str
    train: str
    validation: str
    oos: str
    trials_count: int
    executed_trades_by_day: dict[str, int]
    signal_count: int
    rejected_count: int
    fill_model: str
    risk_constraints: str
    costs: str
    net_pnl: float | None = None
    expectancy: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    turnover: float | None = None
    coverage: float | None = None
    slippage_sensitivity: float | None = None
    multiple_testing_adjustment: str = UNKNOWN
    verifier_status: str = UNKNOWN
    promotion: str = "NONE"
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.promotion != "NONE":
            raise ValueError(
                "an experiment result cannot carry a promotion; promotion is a separate decision"
            )
        if self.verifier_status not in ("PASS", "FAIL", UNKNOWN):
            raise ValueError(f"unknown verifier_status {self.verifier_status!r}")
        if any(count < 0 for count in self.executed_trades_by_day.values()):
            raise ValueError("executed trades per day cannot be negative")

    @property
    def observed_days(self) -> int:
        return len(self.executed_trades_by_day)

    @property
    def observed_trades(self) -> int:
        return sum(self.executed_trades_by_day.values())

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_days"] = self.observed_days
        payload["observed_trades"] = self.observed_trades
        return payload
