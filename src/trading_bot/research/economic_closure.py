"""RFC-034 — profitability-research closure & re-entry governance.

Canonical, executable encoding of the project's *frozen economic truth* after the
RFC-010B → RFC-033 research line ended.  This module deliberately contains **no
new alpha, indicator, agent, market, execution optimisation, strategy family or
dataset** (§0).  It only records:

* the frozen economic marker (§1),
* the platform status separated from the economic status (§2),
* the economic-research ledger over RFC-010B … RFC-033 (§4/§5),
* the canonical candidate registry with each candidate's final status (§6/§7),
* the re-entry policy, headroom classes and admission scorecard (§18-§29),
* the verification-vs-economic separation contract (§36-§40).

The pure functions here are the source of truth for the RFC-034 artifacts
generated under ``reports/strategy-closure/`` and the tracked documentation under
``docs/research/``.  The independent verifier re-derives the same invariants
without importing this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from trading_bot.research.certification_gate import (
    MANDATORY_GATES,
    evaluate_promotion,
)

# --------------------------------------------------------------------------- #
# §1/§2 — official current project status (frozen)
# --------------------------------------------------------------------------- #

PLATFORM_STATUS = "RESEARCH_CAPABLE"
ECONOMIC_STATUS = "NO_VALIDATED_EXECUTABLE_EDGE"
PROFITABILITY_RESEARCH_STATUS = "PAUSED"
CURRENT_DECISION = "PAUSE_TRADING_PROJECT"
NEXT_ALPHA_RFC_ALLOWED = False

PAUSE_REASON = (
    "NO STRATEGY HAS DEMONSTRATED EXECUTABLE, VALIDATED, ROBUST, NET POSITIVE EDGE"
)


@dataclass(frozen=True, slots=True)
class EconomicMarker:
    """§1 — the frozen economic marker.  All zeros except the statistical effect."""

    statistical_historical_effect: int
    executable_validated_net_edge: int
    robust_executable_net_edge: int
    executable_holdout_pass: int
    certified_paper_candidate: int
    forward_paper_profitable: int
    live_profitable: int

    @property
    def all_execution_zeros(self) -> bool:
        return (
            self.executable_validated_net_edge == 0
            and self.robust_executable_net_edge == 0
            and self.executable_holdout_pass == 0
            and self.certified_paper_candidate == 0
            and self.forward_paper_profitable == 0
            and self.live_profitable == 0
        )


ECONOMIC_MARKER = EconomicMarker(
    statistical_historical_effect=1,
    executable_validated_net_edge=0,
    robust_executable_net_edge=0,
    executable_holdout_pass=0,
    certified_paper_candidate=0,
    forward_paper_profitable=0,
    live_profitable=0,
)

# --------------------------------------------------------------------------- #
# §10 — architecture status (absence of edge != architecture failure)
# --------------------------------------------------------------------------- #

ARCHITECTURE_STATUS: dict[str, str] = {
    "data_pit": "mature",
    "research_pipeline": "mature",
    "cost_accounting": "mature",
    "independent_verify": "mature",
    "strategy_promotion": "mature",
    "economic_alpha": "unresolved",
}

# --------------------------------------------------------------------------- #
# §4/§5 — economic research ledger
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One row of the economic-research ledger (§4/§5)."""

    rfc: str
    family: str
    hypothesis: str
    data: str
    assets: str
    timeframe: str
    gross_edge: str
    cost: str
    net_edge: str
    sample_size: str
    discovery: str
    validation: str
    walk_forward: str
    robustness: str
    holdout: str
    tradability: str
    pit: str
    classification: str
    rejection_reason: str
    economic_lesson: str


LEDGER: tuple[LedgerRow, ...] = (
    LedgerRow(
        rfc="RFC-010B",
        family="live baseline / runtime authority",
        hypothesis="The certified runtime under the frozen configuration has no edge",
        data="certified runtime traces (1533 proposals)",
        assets="BTC, ETH, SOL",
        timeframe="5m/15m/30m/1h",
        gross_edge="mean -3.54 bps (max +1.49)",
        cost="23.790569 bps round-trip",
        net_edge="mean -27.33 bps (all negative)",
        sample_size="1533 proposals / 586 cycles",
        discovery="n/a",
        validation="n/a",
        walk_forward="n/a",
        robustness="n/a",
        holdout="n/a",
        tradability="n/a",
        pit="PASS",
        classification="ZT-4 ZERO_TRADE (valid)",
        rejection_reason="gross_edge < cost on 1533/1533 proposals",
        economic_lesson="The frozen strategy set generates no gross edge at 5m; zero-trade is a real economic result.",
    ),
    LedgerRow(
        rfc="RFC-020",
        family="point-in-time data integrity certification",
        hypothesis="Market data and temporal semantics are PIT-safe before any economics",
        data="84 dataset files / 285393 rows",
        assets="BTC, ETH, SOL",
        timeframe="5m base",
        gross_edge="n/a (data certification)",
        cost="n/a",
        net_edge="n/a",
        sample_size="15 data sources audited",
        discovery="n/a",
        validation="n/a",
        walk_forward="n/a",
        robustness="n/a",
        holdout="n/a",
        tradability="n/a",
        pit="PASS (ledger prior P1, remediated RFC-021)",
        classification="G2_DATA_PIT_CERTIFIED PARTIAL",
        rejection_reason="not an alpha test; market-data PIT PASS, ledger-prior P1 open",
        economic_lesson="Data/infra integrity must be certified before economics; ledger-prior PIT was a real governance defect.",
    ),
    LedgerRow(
        rfc="RFC-021",
        family="edge discovery sprint 001",
        hypothesis="Existing productive families create net edge at the certified cost",
        data="certified PIT dataset",
        assets="BTC, ETH, SOL",
        timeframe="5m/15m/30m/1h",
        gross_edge="best volatility@30m +19.78 bps",
        cost="23.790569 bps",
        net_edge="best -4.01 bps",
        sample_size="18 experiments / 108 trades (best)",
        discovery="REJECTED (18/18 net <= 0)",
        validation="NOT_REACHED",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="UNSPENT",
        tradability="n/a (net already <= 0)",
        pit="PASS",
        classification="REJECTED_DISCOVERY",
        rejection_reason="net expectancy <= 0 for 18/18; edge/cost < 1.0",
        economic_lesson="No existing family clears the 23.79 bps cost; the binding constraint is cost-to-edge ratio.",
    ),
    LedgerRow(
        rfc="RFC-022",
        family="edge discovery sprint 002 (volatility events)",
        hypothesis="Volatility-shock events produce tradable net edge",
        data="certified PIT dataset",
        assets="BTC, ETH, SOL",
        timeframe="15m/30m/1h/2h",
        gross_edge="best discovery net +16.0652 bps (squeeze_magnitude@30m)",
        cost="23.790569 bps",
        net_edge="discovery +16.07 bps; validation 0/2 positive",
        sample_size="106 experiments",
        discovery="2 winners",
        validation="0 passes",
        walk_forward="NOT_REACHED",
        robustness="0/2",
        holdout="UNSPENT",
        tradability="n/a",
        pit="PASS",
        classification="REJECTED_GENERALIZATION",
        rejection_reason="multiple testing / winner's curse",
        economic_lesson="A discovery winner among 106 attempts is indistinguishable from luck.",
    ),
    LedgerRow(
        rfc="RFC-023",
        family="generalization diagnosis & signal information audit",
        hypothesis="The sprint-002 winner generalizes (diagnose why it did not)",
        data="certified PIT dataset",
        assets="BTC, ETH, SOL",
        timeframe="15m/30m/1h/2h",
        gross_edge="best-of-106 null median +7.944 bps",
        cost="23.790569 bps",
        net_edge="n/a",
        sample_size="106 attempts / 200 permutation draws",
        discovery="n/a",
        validation="n/a",
        walk_forward="n/a",
        robustness="n/a",
        holdout="UNSPENT",
        tradability="n/a",
        pit="PASS",
        classification="GENERALIZATION_DIAGNOSED",
        rejection_reason="primary cause MULTIPLE_TESTING (p=0.29 best-of-null)",
        economic_lesson="0/28 directional cells; only reproducible information is volatility magnitude, not direction.",
    ),
    LedgerRow(
        rfc="RFC-024",
        family="directional signal discovery on volatility events",
        hypothesis="Direction conditional on a detectable volatility event is tradable",
        data="certified PIT dataset (vol-shock events)",
        assets="BTC, ETH, SOL",
        timeframe="30m/1h",
        gross_edge="not material",
        cost="23.790569 bps",
        net_edge="n/a",
        sample_size="6 frozen hypotheses",
        discovery="FAIL_DIRECTION",
        validation="NOT_REACHED",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="UNSPENT",
        tradability="n/a",
        pit="PASS",
        classification="VOLATILITY_ONLY",
        rejection_reason="magnitude detected, direction not",
        economic_lesson="Volatility information exists but magnitude information != directional tradable edge.",
    ),
    LedgerRow(
        rfc="RFC-025",
        family="orthogonal edge discovery (basis / positioning / flow)",
        hypothesis="Orthogonal (non-price) information creates net edge after cost",
        data="funding/basis/taker-flow (PIT)",
        assets="BTC, ETH, SOL",
        timeframe="1h",
        gross_edge="family IC null p 0.136 ALL / 0.028 VOL",
        cost="23.790569 bps",
        net_edge="0 net>0 with sufficient sample",
        sample_size="60 variants (15 with n>=50)",
        discovery="3 net>0 (all n<50)",
        validation="FAIL",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="UNSPENT",
        tradability="n/a",
        pit="PASS",
        classification="C (orthogonal info, not tradable after cost)",
        rejection_reason="orthogonal information exists but no net edge survives cost",
        economic_lesson="Orthogonality alone is insufficient; gross edge does not generalize economically.",
    ),
    LedgerRow(
        rfc="RFC-026",
        family="execution economics",
        hypothesis="Realistic execution optimisation can monetise the RFC-025 signal",
        data="microstructure window",
        assets="BTC, ETH, SOL",
        timeframe="1h",
        gross_edge="n/a",
        cost="current 23.790569 bps; break-even 20.7298 bps",
        net_edge="best -3.0608 bps",
        sample_size="execution micro window",
        discovery="FAIL",
        validation="NOT_REACHED",
        walk_forward="NOT_REACHED",
        robustness="FAIL",
        holdout="UNSPENT",
        tradability="FAIL",
        pit="PARTIAL",
        classification="EX-A WORLD_B",
        rejection_reason="signal too weak to survive realistic execution",
        economic_lesson="Execution optimisation cannot rescue a weak alpha (12.87% cost reduction would still lose).",
    ),
    LedgerRow(
        rfc="RFC-027",
        family="historical positioning edge discovery",
        hypothesis="Positioning data (OI/liquidations/flow) carries directional edge",
        data="30.2 months positioning data (PIT)",
        assets="BTC, ETH, SOL",
        timeframe="intraday",
        gross_edge="best +14.8841 bps",
        cost="23.790569 bps",
        net_edge="best -8.9064 bps",
        sample_size="110 variants",
        discovery="net<=0",
        validation="FAIL",
        walk_forward="0/4",
        robustness="FAIL",
        holdout="UNSPENT",
        tradability="FAIL",
        pit="PASS",
        classification="POS-C",
        rejection_reason="COST_KILLED (edge/cost 0.63)",
        economic_lesson="Positioning information PASS, directional economics FAIL; orthogonal info is not enough.",
    ),
    LedgerRow(
        rfc="RFC-028",
        family="market-neutral carry & basis",
        hypothesis="LONG SPOT / SHORT PERP carry creates net edge after two-leg cost",
        data="31.0 months funding/basis (PIT)",
        assets="BTC, ETH, SOL",
        timeframe="7d hold",
        gross_edge="funding 1508.67 bps; basis 17.25 bps (discovery)",
        cost="1170.0 bps total (39 bps round-trip)",
        net_edge="discovery expectancy +11.8638 bps; validation FAIL",
        sample_size="30 trades (discovery)",
        discovery="PASS",
        validation="FAIL (0 trades)",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="NOT_OPENED",
        tradability="n/a",
        pit="PASS",
        classification="CARRY-C",
        rejection_reason="broad carry ~-38 bps/trade; only rare high-funding 7d holds positive in discovery",
        economic_lesson="Funding is highly predictable but its magnitude is far below the two-leg cost.",
    ),
    LedgerRow(
        rfc="RFC-029",
        family="structural low-turnover carry",
        hypothesis="Long holds (14-45d) amortise the cost into a validated net edge",
        data="funding/basis (PIT)",
        assets="BTC, ETH, SOL",
        timeframe="45d hold",
        gross_edge="funding 3370.8755 bps; basis 8.6526 bps (discovery)",
        cost="1248.0 bps (discovery)",
        net_edge="discovery expectancy 66.6103 bps/episode; validation FAIL",
        sample_size="32 episodes (discovery)",
        discovery="PASS",
        validation="FAIL (NEGATIVE_NET)",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="NOT_OPENED",
        tradability="n/a",
        pit="PASS",
        classification="STRUCT-C",
        rejection_reason="funding regime compression makes every validation cell net negative",
        economic_lesson="Structural carry worked in discovery but failed validation: the funding process decays below cost.",
    ),
    LedgerRow(
        rfc="RFC-030",
        family="external alpha reproduction (TSMOM / XMOM)",
        hypothesis="Externally documented crypto momentum edges survive realistic cost",
        data="30 USDT spot pairs, 3165 days",
        assets="30 USDT spot pairs",
        timeframe="1 month / 1 week",
        gross_edge="EXT-TSMOM-001 123.787 bps; EXT-XMOM-001 141.686 bps",
        cost="5.637 bps (EXT-TSMOM-001)",
        net_edge="EXT-TSMOM-001 118.15 bps discovery / 51.33 validation; EXT-XMOM-001 96.42 / 14.99",
        sample_size="91 trades (EXT-TSMOM-001)",
        discovery="PASS (both)",
        validation="PASS (both)",
        walk_forward="NOT_REACHED",
        robustness="EXT-TSMOM-001 PASS / EXT-XMOM-001 FAIL",
        holdout="PASS (both)",
        tradability="NOT_CERTIFIED",
        pit="SIGNAL_PIT_PASS",
        classification="REPRODUCED (XRIO); paper labels later invalidated",
        rejection_reason="reproduction faithful, but executability/robustness decide survival",
        economic_lesson="Faithful reproduction is necessary but not sufficient; the executable form and robustness decide.",
    ),
    LedgerRow(
        rfc="RFC-031",
        family="TSMOM paper-candidate certification",
        hypothesis="EXT-TSMOM-001 is a certifiable paper candidate",
        data="30 USDT spot pairs",
        assets="30 USDT spot pairs",
        timeframe="1 month",
        gross_edge="+118.15 bps discovery",
        cost="5.637 bps base; 49.03 bps at 1.5x",
        net_edge="validation 51.33 bps, but tradability/economic gates FAIL",
        sample_size="91 trades",
        discovery="PASS",
        validation="PASS",
        walk_forward="NOT_REACHED",
        robustness="PASS",
        holdout="PASS",
        tradability="FAIL (unsupported spot shorts P0 + same-close execution)",
        pit="SIGNAL_PIT_PASS / EXECUTION_SEMANTICS_DEFECT",
        classification="REJECTED / INVALIDATED_TRADABILITY",
        rejection_reason="TRADABILITY_DEFECT: unsupported spot shorts + same-close execution",
        economic_lesson="A validated statistical edge is worthless if the instruments cannot execute it.",
    ),
    LedgerRow(
        rfc="RFC-032",
        family="executable TSMOM remediation (EXT-TSMOM-002)",
        hypothesis="Long-or-cash spot + T+1 preserves the TSMOM edge",
        data="30 USDT spot pairs",
        assets="30 USDT spot pairs",
        timeframe="1 month",
        gross_edge="historical mean net 636.743 bps/month",
        cost="realistic spot cost with T+1",
        net_edge="median 0.0 bps; recent 12m -109.833 bps/month",
        sample_size="monthly rebalances",
        discovery="PASS",
        validation="FAIL (G_REM_1)",
        walk_forward="NOT_REACHED",
        robustness="NOT_REACHED",
        holdout="NOT_OPENED",
        tradability="PASS (long/cash, T+1)",
        pit="PASS",
        classification="REJECTED_HISTORICAL_PLAUSIBILITY",
        rejection_reason="the executable version does not preserve the historical economic edge",
        economic_lesson="Making a strategy executable can destroy its recent economics; median 0 with negative recent era.",
    ),
    LedgerRow(
        rfc="RFC-033",
        family="executable futures TSMOM (EXT-TSMOM-003)",
        hypothesis="Native long/short perpetual futures restore the TSMOM edge",
        data="115 USDT-M perpetuals, 2465 days",
        assets="115 USDT-M perpetual futures",
        timeframe="1 month",
        gross_edge="price PnL 12974.95 bps; funding -4540.69 bps",
        cost="257.92 bps",
        net_edge="discovery +447.98 bps/month; validation -563.80 bps/month",
        sample_size="68 monthly rebalances / 115 symbols",
        discovery="PASS",
        validation="FAIL (G_PERP_2)",
        walk_forward="N/A",
        robustness="NOT_REACHED",
        holdout="None",
        tradability="PASS",
        pit="PASS",
        classification="REJECTED_VALIDATION",
        rejection_reason="native short leg destroyed in the 2023-24 alt rally; validation net negative",
        economic_lesson="The natural long/short futures implementation fails Validation; the TSMOM line is closed.",
    ),
)

# --------------------------------------------------------------------------- #
# §6/§7 — canonical candidate registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Candidate:
    """One candidate in the canonical registry (§6/§7)."""

    candidate_id: str
    family: str
    status: str
    invalidation_reason: str
    validation_status: str
    robustness_status: str
    holdout_status: str
    tradability_status: str
    evidence_status: str
    gates: Mapping[str, str]

    @property
    def promotable(self) -> bool:
        """PROMOTABLE = AND(mandatory gates) via the RFC-032 certification gate."""
        return bool(evaluate_promotion(self.gates).promotable)

    @property
    def blocking_gates(self) -> tuple[str, ...]:
        return evaluate_promotion(self.gates).blocking_gates


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        candidate_id="EXT-TSMOM-001",
        family="time-series momentum / trend",
        status="INVALIDATED_TRADABILITY",
        invalidation_reason=(
            "unsupported spot shorts (P0) + same-close execution (RFC-031)"
        ),
        validation_status="PASS",
        robustness_status="PASS",
        holdout_status="PASS",
        tradability_status="FAIL",
        evidence_status="SUPERSEDED_BY RFC-031 (RFC-030 HOLDOUT_PASS withdrawn)",
        gates={
            "G_VALIDATION": "PASS",
            "G_ROBUSTNESS": "PASS",
            "G_HOLDOUT": "PASS",
            "G_TRADABILITY": "FAIL",
            "G_INDEPENDENT_VERIFICATION": "PASS",
        },
    ),
    Candidate(
        candidate_id="EXT-TSMOM-002",
        family="executable TSMOM (long/cash + T+1)",
        status="REJECTED_HISTORICAL_PLAUSIBILITY",
        invalidation_reason="G_REM_1 FAIL: executable version does not preserve the edge",
        validation_status="FAIL",
        robustness_status="NOT_REACHED",
        holdout_status="NOT_OPENED",
        tradability_status="PASS",
        evidence_status="DIAGNOSTIC_ONLY (RFC-032)",
        gates={
            "G_VALIDATION": "FAIL",
            "G_ROBUSTNESS": "NOT_REACHED",
            "G_HOLDOUT": "NOT_REACHED",
            "G_TRADABILITY": "PASS",
            "G_INDEPENDENT_VERIFICATION": "PASS",
        },
    ),
    Candidate(
        candidate_id="EXT-TSMOM-003",
        family="executable futures TSMOM (long/short perp)",
        status="REJECTED_VALIDATION",
        invalidation_reason="G_PERP_2 FAIL: validation net -563.80 bps/month",
        validation_status="FAIL",
        robustness_status="NOT_REACHED",
        holdout_status="NOT_OPENED",
        tradability_status="PASS",
        evidence_status="REJECTED (RFC-033)",
        gates={
            "G_VALIDATION": "FAIL",
            "G_ROBUSTNESS": "NOT_REACHED",
            "G_HOLDOUT": "NOT_REACHED",
            "G_TRADABILITY": "PASS",
            "G_INDEPENDENT_VERIFICATION": "PASS",
        },
    ),
    Candidate(
        candidate_id="EXT-XMOM-001",
        family="cross-sectional momentum",
        status="REJECTED_ROBUSTNESS",
        invalidation_reason="G_ROBUST FAIL (RFC-030); never certified as a paper candidate",
        validation_status="PASS",
        robustness_status="FAIL",
        holdout_status="PASS",
        tradability_status="NOT_REACHED",
        evidence_status="SUPERSEDED_BY canonical registry (RFC-030 paper label withdrawn)",
        gates={
            "G_VALIDATION": "PASS",
            "G_ROBUSTNESS": "FAIL",
            "G_HOLDOUT": "PASS",
            "G_TRADABILITY": "NOT_REACHED",
            "G_INDEPENDENT_VERIFICATION": "NOT_REACHED",
        },
    ),
)

#: RFC-030 labelled these as paper candidates; the canonical status supersedes it.
SUPERSEDED_CLAIMS: tuple[dict[str, str], ...] = (
    {
        "source": "RFC-030 FINAL REPORT ('PAPER CANDIDATES = [EXT-TSMOM-001, EXT-XMOM-001]')",
        "superseded_by": "canonical CANDIDATE_REGISTRY + RFC-031/RFC-032/RFC-033",
        "reason": "EXT-TSMOM-001 failed tradability (RFC-031); EXT-XMOM-001 failed robustness (RFC-030)",
    },
    {
        "source": "RFC-031 ('VALIDATED HISTORICAL EDGE = YES / ROBUST HISTORICAL EDGE = YES')",
        "superseded_by": "PROJECT_ECONOMIC_STATUS (executable_validated_net_edge = 0)",
        "reason": "statistical historical edge != executable validated net edge",
    },
)

# --------------------------------------------------------------------------- #
# §17 — no automatic next alpha RFC
# --------------------------------------------------------------------------- #

#: The next action is not an RFC number; it is a re-entry-qualified opportunity.

# --------------------------------------------------------------------------- #
# §18-§23 — re-entry policy, headroom classes
# --------------------------------------------------------------------------- #

REENTRY_STATES: tuple[str, ...] = (
    "PAUSED",
    "EXTERNAL_OPPORTUNITY_FOUND",
    "ADMISSION_REVIEW",
    "APPROVED_FOR_RESEARCH",
    "REPRODUCTION",
)

REENTRY_START_SOURCES: tuple[str, ...] = (
    "EXTERNAL_EVIDENCE",
    "NEW_STRUCTURAL_DATA_OR_MARKET_MECHANISM",
)

VALID_REOPEN_TRIGGERS: tuple[str, ...] = (
    "new peer-reviewed anomaly",
    "new independent replication",
    "new accessible dataset",
    "new instrument capability",
    "new market structural mechanism",
    "material cost regime change",
)

INVALID_REOPEN_TRIGGERS: tuple[str, ...] = (
    "we have time",
    "maybe RSI works differently",
    "add more AI agents",
    "try more thresholds",
    "increase leverage",
    "reduce assumed fees",
    "change holdout",
    "different random seed",
)

#: Ordered (upper_bound_exclusive, class) headroom classes (§22).
HEADROOM_CLASSES: tuple[tuple[float, str], ...] = (
    (1.0, "REJECT"),
    (1.25, "TOO_THIN"),
    (1.5, "WEAK"),
    (2.0, "POTENTIALLY_RESEARCHABLE"),
    (float("inf"), "STRONG_HEADROOM"),
)

REENTRY_MIN_EVIDENCE_SOURCES = 2
REENTRY_CREDIBLE_SOURCE_TYPES: tuple[str, ...] = (
    "peer-reviewed paper",
    "credible working paper",
    "exchange research",
    "independent replication",
    "real audited experiment",
)

#: §30 — new-hypothesis budget once research reopens.
MAX_STRATEGIES = 2
MAX_CORE_VARIANTS_PER_STRATEGY = 3

#: §34 — canonical gate order; no later gate compensates an earlier one.
GATE_ORDER: tuple[str, ...] = (
    "DATA",
    "REPRODUCTION",
    "DISCOVERY",
    "VALIDATION",
    "ROBUSTNESS",
    "HOLDOUT",
    "CERTIFICATION",
    "PAPER",
    "FORWARD_EVIDENCE",
    "CANARY",
    "LIVE",
)


def classify_headroom(ratio: float) -> str:
    """§22 — classify HEADROOM_RATIO = expected gross edge / realistic cost."""
    if ratio < 0:
        raise ValueError("headroom ratio must be non-negative")
    for upper, name in HEADROOM_CLASSES:
        if ratio < upper:
            return name
    return "STRONG_HEADROOM"  # unreachable, kept for exhaustiveness


# --------------------------------------------------------------------------- #
# §28/§29 — alpha admission scorecard
# --------------------------------------------------------------------------- #

SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "evidence_strength",
    "economic_headroom",
    "data_feasibility",
    "tradability",
    "orthogonality",
    "implementation_cost",
    "independent_replication",
)

#: Dimensions whose weakness alone blocks admission (§29).
CRITICAL_DIMENSIONS: tuple[str, ...] = (
    "evidence_strength",
    "tradability",
    "data_feasibility",
)


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    decision: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


def admission_decision(scores: Mapping[str, int]) -> AdmissionDecision:
    """§29 — no critical dimension may be <= 1; critical dims must be strong."""
    for dim in SCORECARD_DIMENSIONS:
        value = scores.get(dim)
        if value is None:
            return AdmissionDecision("REJECT_MISSING_DIMENSION", (f"missing:{dim}",))
    reasons: list[str] = []
    for dim in CRITICAL_DIMENSIONS:
        if scores[dim] <= 1:
            reasons.append(f"critical_dimension_too_weak:{dim}={scores[dim]}")
    for dim in SCORECARD_DIMENSIONS:
        if scores[dim] <= 1 and dim not in CRITICAL_DIMENSIONS:
            reasons.append(f"weak_dimension:{dim}={scores[dim]}")
    if reasons:
        return AdmissionDecision("REJECT", tuple(reasons))
    if all(scores[dim] >= 3 for dim in CRITICAL_DIMENSIONS):
        return AdmissionDecision("APPROVED_FOR_RESEARCH", ())
    return AdmissionDecision("ADMISSION_REVIEW", ())


def is_valid_reopen_trigger(text: str) -> bool:
    """§42/§43 — valid triggers reopen; the invalid list never does."""
    norm = text.strip().lower()
    if any(bad in norm for bad in INVALID_REOPEN_TRIGGERS):
        return False
    return any(good in norm for good in VALID_REOPEN_TRIGGERS)


# --------------------------------------------------------------------------- #
# §36-§40 — verification semantics vs economic result
# --------------------------------------------------------------------------- #


class VerificationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class EconomicResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"


@dataclass(frozen=True, slots=True)
class VerifierChecks:
    """§37/§38 — verifier checks count only reproduction/hash/PIT/accounting/contract.

    A legitimate strategy loss is *not* a failed verifier check.
    """

    reproduction_exact: bool
    hashes_match: bool
    pit_ok: bool
    accounting_reconciled: bool
    contract_ok: bool

    def failed(self) -> tuple[str, ...]:
        out: list[str] = []
        if not self.reproduction_exact:
            out.append("reproduction_mismatch")
        if not self.hashes_match:
            out.append("hash_mismatch")
        if not self.pit_ok:
            out.append("pit_violation")
        if not self.accounting_reconciled:
            out.append("accounting_mismatch")
        if not self.contract_ok:
            out.append("contract_violation")
        return tuple(out)

    @property
    def status(self) -> VerificationStatus:
        return VerificationStatus.PASS if not self.failed() else VerificationStatus.FAIL


#: §78 — FALSE_SUCCESS triggers.  A legitimate strategy loss is NOT one of them.
FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "invalidated_candidate_remains_promotable",
    "failed_strategy_listed_as_validated",
    "paper_candidate_without_mandatory_gates",
    "economic_gate_confused_with_verifier_failure",
    "project_marked_ready_or_profitable",
    "future_alpha_loop_left_automatically_enabled",
)


@dataclass(frozen=True, slots=True)
class ClosureClaim:
    """A project-level claim checked against the frozen truth (§78)."""

    invalidated_candidate_promotable: bool = False
    failed_strategy_marked_validated: bool = False
    paper_candidate_without_gates: bool = False
    economic_gate_confused_with_verifier_failure: bool = False
    project_marked_ready_or_profitable: bool = False
    future_alpha_loop_auto_enabled: bool = False

    def false_success(self) -> tuple[str, ...]:
        fired: list[str] = []
        if self.invalidated_candidate_promotable:
            fired.append("invalidated_candidate_remains_promotable")
        if self.failed_strategy_marked_validated:
            fired.append("failed_strategy_listed_as_validated")
        if self.paper_candidate_without_gates:
            fired.append("paper_candidate_without_mandatory_gates")
        if self.economic_gate_confused_with_verifier_failure:
            fired.append("economic_gate_confused_with_verifier_failure")
        if self.project_marked_ready_or_profitable:
            fired.append("project_marked_ready_or_profitable")
        if self.future_alpha_loop_auto_enabled:
            fired.append("future_alpha_loop_left_automatically_enabled")
        return tuple(fired)


def regression_verification_and_economic(
    *, reproduction_exact: bool, validation_status: str
) -> dict[str, Any]:
    """§39 — independent reproduction + negative Validation = VERIFICATION PASS,
    VALIDATION FAIL, and FALSE_SUCCESS = 0 (a legitimate strategy loss).
    """
    checks = VerifierChecks(
        reproduction_exact=reproduction_exact,
        hashes_match=True,
        pit_ok=True,
        accounting_reconciled=True,
        contract_ok=True,
    )
    claim = ClosureClaim()
    return {
        "verification_status": checks.status.value,
        "economic_result": str(validation_status).upper(),
        "false_success": len(claim.false_success()),
    }


def canonical_candidates() -> dict[str, str]:
    """Map candidate_id -> canonical final status (for the verifier/tests)."""
    return {c.candidate_id: c.status for c in CANDIDATES}


def active_candidate_count() -> int:
    """§7 — no candidate with a failed mandatory gate remains active/promotable."""
    return sum(1 for c in CANDIDATES if c.promotable)


def mandatory_gate_names() -> tuple[str, ...]:
    return MANDATORY_GATES
