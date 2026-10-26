"""RFC-041 — business research freeze & re-entry governance.

Canonical, executable encoding of the project's *business truth* after the
RFC-010B → RFC-040 research line.  This module contains **no new alpha**, no
strategy, no backtest, no broker, no paper and no live code (§0/§73).  It only
records:

* the canonical KPI model separating statistical / historical net / executable
  / business edge / paper / forward / live (§4/§5),
* the seven-condition ``BUSINESS_EDGE`` definition (§6),
* the benchmark pre-declaration requirement (§7),
* the candidate disposition registry for every relevant candidate (§9-§20),
* the phase/status/capital state (§21-§24),
* the ``G_BUSINESS_REENTRY`` contract, scorecard, budget and failure rule
  (§27-§39),
* the paper/live admission rules (§48-§49),
* the proven / not-proven / lessons separations (§44-§46).

The pure functions here are the source of truth for the RFC-041 artifacts under
``reports/business-freeze/`` and the tracked documentation under
``docs/research/``.  The independent verifier re-derives the same invariants
without importing this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# --------------------------------------------------------------------------- #
# §23/§50/§58-§60 — capital, decision identity, schema
# --------------------------------------------------------------------------- #

REFERENCE_INITIAL_CAPITAL_USDT = 200.0
LIVE_CAPITAL_AUTHORIZED = 0
DECISION_ID = "BUSINESS-FREEZE-2026-001"
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# §4 — the evidence ladder (the distinctions that must never re-mix)
# --------------------------------------------------------------------------- #

EVIDENCE_LADDER: tuple[str, ...] = (
    "NO_EDGE",
    "STATISTICAL_HISTORICAL_EFFECT",
    "HISTORICAL_NET_EDGE",
    "EXECUTABLE_VALIDATED_EDGE",
    "BUSINESS_VALIDATED_EDGE",
)

#: Stages beyond the historical ladder that a candidate must still earn.
POST_BUSINESS_STAGES: tuple[str, ...] = (
    "PAPER_EVIDENCE",
    "FORWARD_EVIDENCE",
    "LIVE_PROFIT",
)


def evidence_rank(level: str) -> int:
    """Return the ordinal position of ``level`` on the evidence ladder."""
    try:
        return EVIDENCE_LADDER.index(level)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"unknown evidence level: {level!r}") from exc


# --------------------------------------------------------------------------- #
# §5 — canonical KPI model
# --------------------------------------------------------------------------- #

KPI_PRIMARY = "BUSINESS_VALIDATED_EDGE_COUNT"

KPI_NAMES: tuple[str, ...] = (
    "HISTORICAL_NET_EDGE_COUNT",
    "EXECUTABLE_VALIDATED_EDGE_COUNT",
    "BUSINESS_VALIDATED_EDGE_COUNT",
    "ROBUST_BUSINESS_EDGE_COUNT",
    "PAPER_CANDIDATE_COUNT",
    "FORWARD_PROFITABLE_COUNT",
    "LIVE_PROFITABLE_COUNT",
)

#: The zero-tolerance KPIs that gate paper/live promotion.
BUSINESS_KPI_NAMES: tuple[str, ...] = (
    "BUSINESS_VALIDATED_EDGE_COUNT",
    "PAPER_CANDIDATE_COUNT",
    "FORWARD_PROFITABLE_COUNT",
    "LIVE_PROFITABLE_COUNT",
)

# --------------------------------------------------------------------------- #
# §6 — BUSINESS_EDGE needs strictly more than net > 0
# --------------------------------------------------------------------------- #

BUSINESS_EDGE_CONDITIONS: tuple[str, ...] = (
    "realistic_costs_included",
    "practical_tradability",
    "product_fit_for_intended_capital",
    "chronological_validation_pass",
    "risk_adjusted_value_vs_passive_benchmark",
    "net_excess_vs_risk_matched_positive",
    "robustness_pass",
)

# --------------------------------------------------------------------------- #
# §7 — benchmarks must be declared before the backtest
# --------------------------------------------------------------------------- #

REQUIRED_BENCHMARKS: tuple[str, ...] = (
    "PRIMARY_PASSIVE_BENCHMARK",
    "RISK_MATCHED_BENCHMARK",
)

BENCHMARK_RULES: tuple[str, ...] = (
    "declare_both_benchmarks_before_backtest",
    "no_benchmark_mining",
    "no_post_result_benchmark_selection",
)


def business_edge_status(conditions: Mapping[str, bool]) -> str:
    """§6 — BUSINESS_EDGE = PASS only when all seven conditions hold.

    A missing condition is a FAIL (never silently ignored).
    """
    missing = [c for c in BUSINESS_EDGE_CONDITIONS if c not in conditions]
    if missing:
        return "FAIL"
    return "PASS" if all(bool(conditions[c]) for c in BUSINESS_EDGE_CONDITIONS) else "FAIL"


def benchmark_declaration_ok(
    primary: str | None, risk_matched: str | None, *, chosen_after_results: bool
) -> bool:
    """§7 — both benchmarks present and not chosen after results."""
    return bool(primary and risk_matched) and not chosen_after_results


# --------------------------------------------------------------------------- #
# §9-§20 — canonical candidate disposition registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CandidateDisposition:
    """One candidate in the RFC-041 canonical registry (§9-§20, §53)."""

    candidate_id: str
    family: str
    instrument: str
    capital_fit: str
    best_result: str
    failure_gate: str
    final_status: str
    evidence_level: str
    disposition_class: str
    product_fit_200: str
    evidence_retained: bool
    reentry_condition: str

    @property
    def historical_net_edge(self) -> bool:
        return evidence_rank(self.evidence_level) >= evidence_rank("HISTORICAL_NET_EDGE")

    @property
    def executable_validated_edge(self) -> bool:
        return evidence_rank(self.evidence_level) >= evidence_rank("EXECUTABLE_VALIDATED_EDGE")

    @property
    def business_edge(self) -> bool:
        return evidence_rank(self.evidence_level) >= evidence_rank("BUSINESS_VALIDATED_EDGE")


CANDIDATE_DISPOSITIONS: tuple[CandidateDisposition, ...] = (
    CandidateDisposition(
        candidate_id="EXT-TSMOM-001",
        family="time-series momentum / trend",
        instrument="30 USDT spot pairs",
        capital_fit="PASS",
        best_result="discovery +118.15 bps / validation +51.33 bps net",
        failure_gate="G_TRADABILITY",
        final_status="INVALIDATED_TRADABILITY",
        evidence_level="HISTORICAL_NET_EDGE",
        disposition_class="CLOSED_INVALIDATED",
        product_fit_200="IRRELEVANT_NOT_TRADABLE",
        evidence_retained=True,
        reentry_condition="NONE (never reopen)",
    ),
    CandidateDisposition(
        candidate_id="EXT-TSMOM-002",
        family="executable TSMOM (long/cash + T+1)",
        instrument="30 USDT spot pairs",
        capital_fit="PASS",
        best_result="executable mean net +636.74 bps/month discovery, median 0.0, recent -109.83",
        failure_gate="G_REM_1_VALIDATION",
        final_status="REJECTED_HISTORICAL_PLAUSIBILITY",
        evidence_level="STATISTICAL_HISTORICAL_EFFECT",
        disposition_class="CLOSED_REJECTED",
        product_fit_200="IRRELEVANT_NO_EDGE",
        evidence_retained=True,
        reentry_condition="NEW EXTERNAL EVIDENCE (RFC-041 trigger A) only",
    ),
    CandidateDisposition(
        candidate_id="EXT-TSMOM-003",
        family="executable futures TSMOM (long/short perp)",
        instrument="115 USDT-M perpetual futures",
        capital_fit="PASS",
        best_result="discovery +447.98 bps/month; validation -563.80 bps/month",
        failure_gate="G_PERP_2_VALIDATION",
        final_status="REJECTED_VALIDATION",
        evidence_level="STATISTICAL_HISTORICAL_EFFECT",
        disposition_class="CLOSED_REJECTED",
        product_fit_200="IRRELEVANT_VALIDATION_FAIL",
        evidence_retained=True,
        reentry_condition="NEW EXTERNAL EVIDENCE (trigger A) only",
    ),
    CandidateDisposition(
        candidate_id="EXT-XMOM-001",
        family="cross-sectional momentum",
        instrument="30 USDT spot pairs",
        capital_fit="PASS",
        best_result="discovery +96.42 bps / validation +14.99 bps net",
        failure_gate="G_ROBUSTNESS",
        final_status="REJECTED_ROBUSTNESS",
        evidence_level="HISTORICAL_NET_EDGE",
        disposition_class="CLOSED_REJECTED",
        product_fit_200="IRRELEVANT_ROBUSTNESS_FAIL",
        evidence_retained=True,
        reentry_condition="NEW EXTERNAL EVIDENCE (trigger A) only",
    ),
    CandidateDisposition(
        candidate_id="MF-TREND-001",
        family="diversified managed-futures trend",
        instrument="26 individual futures contract chains",
        capital_fit="FAIL_FOR_200",
        best_result="historical discovery +17.88M / validation +12.70M at $10M; net Sharpe 1.14",
        failure_gate="PRODUCT_FIT_200 + MODERN_VALIDATION_DATA_BLOCKED",
        final_status="RESEARCH_ASSET",
        evidence_level="EXECUTABLE_VALIDATED_EDGE",
        disposition_class="NOT_CURRENT_PRODUCT",
        product_fit_200="FAIL",
        evidence_retained=True,
        reentry_condition="MATERIAL CAPITAL CHANGE (trigger C) or an economically equivalent small-capital implementation",
    ),
    CandidateDisposition(
        candidate_id="SC-TREND-001",
        family="multi-asset absolute momentum (ETF)",
        instrument="6 US ETFs (SPY/EFA/IEF/VNQ/GLD/DBC)",
        capital_fit="PASS_AT_200",
        best_result="discovery +81.02 USDT / validation +36.00 USDT net; validation Sharpe 0.52",
        failure_gate="G_BUSINESS_EDGE (risk-adjusted < passive)",
        final_status="VALIDATED_DEFENSIVE",
        evidence_level="EXECUTABLE_VALIDATED_EDGE",
        disposition_class="FUTURE_DEFENSIVE_OVERLAY_CANDIDATE",
        product_fit_200="PASS",
        evidence_retained=True,
        reentry_condition="only as a defensive overlay once a profit engine exists (never a primary strategy)",
    ),
    CandidateDisposition(
        candidate_id="SC-DUALMOM-002",
        family="dual momentum / GEM (ETF)",
        instrument="EU-retail UCITS ETFs (EUR)",
        capital_fit="PASS_AT_200",
        best_result="discovery +145.84 EUR / validation +106.93 EUR net; validation Sharpe 0.73",
        failure_gate="G_BUSINESS_EDGE (CAGR & Sharpe < risk-matched passive; excess < 0)",
        final_status="REJECTED_BUSINESS_EDGE",
        evidence_level="EXECUTABLE_VALIDATED_EDGE",
        disposition_class="CLOSED_REJECTED",
        product_fit_200="PASS",
        evidence_retained=True,
        reentry_condition="NEW EXTERNAL EVIDENCE or NEW STRUCTURAL EDGE (triggers A/B) only",
    ),
    CandidateDisposition(
        candidate_id="SC-CANDIDATE-003",
        family="(would-be small-capital candidate)",
        instrument="n/a",
        capital_fit="n/a",
        best_result="none (never created)",
        failure_gate="NOT_AUTHORIZED",
        final_status="NOT_AUTHORIZED",
        evidence_level="NO_EDGE",
        disposition_class="NOT_CREATED",
        product_fit_200="NO_EVIDENCE",
        evidence_retained=False,
        reentry_condition="requires a PASS on G_BUSINESS_REENTRY first",
    ),
)


def disposition_by_id() -> dict[str, CandidateDisposition]:
    return {c.candidate_id: c for c in CANDIDATE_DISPOSITIONS}


def canonical_candidate_statuses() -> dict[str, str]:
    """Map candidate_id -> canonical final status (verifier/test surface)."""
    return {c.candidate_id: c.final_status for c in CANDIDATE_DISPOSITIONS}


def active_candidate_count() -> int:
    """§10-§20/§57 — no candidate with a failed gate remains active."""
    return sum(1 for c in CANDIDATE_DISPOSITIONS if c.business_edge and c.evidence_retained)


def kpi_counts(
    candidates: Sequence[CandidateDisposition] = CANDIDATE_DISPOSITIONS,
) -> dict[str, int]:
    """§5 — compute the canonical KPI model from the disposition registry."""

    def ge(c: CandidateDisposition, level: str) -> bool:
        return evidence_rank(c.evidence_level) >= evidence_rank(level)

    return {
        "HISTORICAL_NET_EDGE_COUNT": sum(ge(c, "HISTORICAL_NET_EDGE") for c in candidates),
        "EXECUTABLE_VALIDATED_EDGE_COUNT": sum(
            ge(c, "EXECUTABLE_VALIDATED_EDGE") for c in candidates
        ),
        "BUSINESS_VALIDATED_EDGE_COUNT": sum(ge(c, "BUSINESS_VALIDATED_EDGE") for c in candidates),
        "ROBUST_BUSINESS_EDGE_COUNT": 0,
        "PAPER_CANDIDATE_COUNT": 0,
        "FORWARD_PROFITABLE_COUNT": 0,
        "LIVE_PROFITABLE_COUNT": 0,
    }


# --------------------------------------------------------------------------- #
# §21-§24 — phase, status and capital state
# --------------------------------------------------------------------------- #

PHASE_STATUS: dict[str, str] = {
    "PHASE_1_INTERNAL_CRYPTO_ALPHA": "CLOSED",
    "PHASE_2A_INSTITUTIONAL_MULTI_ASSET": "ARCHIVED_NOT_PRODUCT_FIT",
    "PHASE_2B_SMALL_CAPITAL": "PAUSED",
}

PLATFORM_STATUS = "RESEARCH_CAPABLE"
PROFITABILITY_STATUS = "NO_BUSINESS_VALIDATED_EDGE"
RESEARCH_STATUS = "PAUSED"
PAPER_STATUS = "NOT_AUTHORIZED"
LIVE_STATUS = "NOT_AUTHORIZED"
ALPHA_RESEARCH_FREEZE = "ACTIVE"
CURRENT_DECISION = "WAIT_FOR_REENTRY_QUALIFIED_BUSINESS_OPPORTUNITY"

CAPITAL_PRINCIPLE = "STRATEGY MUST FIT CAPITAL"
ANTI_PRINCIPLE = "CAPITAL MUST NOT BE FORCED TO FIT STRATEGY"

#: §25 — prohibited while the freeze is active.
FREEZE_PROHIBITIONS: tuple[str, ...] = (
    "NEW ALPHA RFC",
    "NEW STRATEGY IMPLEMENTATION",
    "PARAMETER SEARCH",
    "INDICATOR SEARCH",
    "BROKER INTEGRATION",
    "PAPER RUN",
    "LIVE RUN",
)

#: §42 — engineering freeze; only these may proceed.
ENGINEERING_FREEZE_ALLOWANCES: tuple[str, ...] = (
    "bug",
    "security",
    "data integrity",
    "critical maintenance",
)


# --------------------------------------------------------------------------- #
# §27-§33 — G_BUSINESS_REENTRY contract
# --------------------------------------------------------------------------- #


class ReentryTrigger(StrEnum):
    A_NEW_EXTERNAL_EVIDENCE = "A"
    B_NEW_STRUCTURAL_EDGE = "B"
    C_CAPITAL_CHANGE = "C"
    D_BROKER_OR_INSTRUMENT_CHANGE = "D"
    E_NEW_DATA = "E"


REENTRY_TRIGGERS: dict[str, str] = {
    "A": "new external evidence: independent publication/replication of persistent post-publication risk-adjusted excess return",
    "B": "new structural edge: institutional constraint, risk transfer, microstructure, forced flows, regulatory effect, structural carry or liquidity provision",
    "C": "capital change: available capital changes materially from 200 USDT (CAPITAL_CHANGE_REVIEW, no arbitrary fixed amount)",
    "D": "broker/instrument change: new fractional access, low-cost instrument, UCITS product, retail derivative or materially better cost structure",
    "E": "new data: only if it unlocks an already economically supported hypothesis (data alone is never enough)",
}

STRUCTURAL_MECHANISMS: tuple[str, ...] = (
    "institutional_constraint",
    "risk_transfer",
    "market_microstructure",
    "forced_flows",
    "regulatory_effect",
    "structural_carry",
    "liquidity_provision",
)

REENTRY_REJECT_CONDITIONS: tuple[str, ...] = (
    "new RSI variation",
    "different moving average",
    "different threshold",
    "another crypto pair",
    "more LLM agents",
    "new sentiment source",
    "adding ML to old features",
    "parameter optimization",
    "same strategy with renamed rules",
)

#: Lexical forms used to detect a reject-condition-only proposal (§33).
_REJECT_LEXICON: tuple[str, ...] = (
    "rsi",
    "moving average",
    "different threshold",
    "threshold",
    "crypto pair",
    "llm",
    "agent",
    "sentiment",
    "machine learning",
    "ml on old features",
    "parameter optimization",
    "parameter optimisation",
    "optimization",
    "optimisation",
    "renamed rules",
    "rename",
)


def is_reject_condition(text: str) -> bool:
    """§33 — a proposal resting only on one of these never reopens research."""
    norm = text.strip().lower()
    return any(needle in norm for needle in _REJECT_LEXICON)


REENTRY_SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "external_evidence",
    "economic_mechanism",
    "post_publication_survival",
    "product_fit",
    "capital_fit",
    "data_feasibility",
    "tradability",
    "cost_headroom",
    "benchmark_adjusted_evidence",
    "implementation_cost",
)

#: Dimensions whose weakness alone blocks admission (§34/§35).
REENTRY_CRITICAL_DIMENSIONS: tuple[str, ...] = (
    "external_evidence",
    "economic_mechanism",
    "product_fit",
    "capital_fit",
    "benchmark_adjusted_evidence",
)

#: §37 — maximum budget once a reentry is authorized.
REENTRY_BUDGET: dict[str, int] = {
    "MAX_FAMILIES": 3,
    "MAX_FINALISTS": 2,
    "MAX_IMPLEMENTED": 1,
}


@dataclass(frozen=True, slots=True)
class ReentryDecision:
    passed: bool
    fired_triggers: tuple[str, ...]
    failing: tuple[str, ...]
    scorecard: str


def scorecard_decision(scores: Mapping[str, int]) -> str:
    """§34/§35 — no critical dimension may be <= 1; all dims must be present."""
    for dim in REENTRY_SCORECARD_DIMENSIONS:
        if dim not in scores:
            return "REJECT_MISSING_DIMENSION"
    if any(scores[d] <= 1 for d in REENTRY_SCORECARD_DIMENSIONS):
        return "REJECT"
    if all(scores[d] >= 3 for d in REENTRY_CRITICAL_DIMENSIONS):
        return "PROCEED"
    return "ADMISSION_REVIEW"


def reentry_gate(proposal: Mapping[str, Any]) -> ReentryDecision:
    """§27-§36 — the only way to reopen alpha research.

    ``proposal`` keys: ``triggers`` (mapping of A-E → bool), ``reject_conditions``
    (sequence of strings), ``evidence_strong_enough`` (bool), ``product_fit``
    ("PASS"/"FAIL"), ``expected_beats_benchmark`` (bool) and ``scores`` (mapping
    of the ten scorecard dimensions → int).
    """
    triggers = proposal.get("triggers", {}) or {}
    fired = tuple(str(t) for t, on in triggers.items() if on)
    failing: list[str] = []

    if not fired:
        failing.append("no_valid_trigger")
    if any(is_reject_condition(str(c)) for c in (proposal.get("reject_conditions") or [])):
        failing.append("reject_condition_present")
    if not proposal.get("evidence_strong_enough", False):
        failing.append("evidence_not_strong_enough")
    if str(proposal.get("product_fit", "")).upper() == "FAIL":
        failing.append("product_fit_fail")
    if not proposal.get("expected_beats_benchmark", False):
        failing.append("no_defensible_benchmark_case")

    scorecard = scorecard_decision(proposal.get("scores", {}) or {})
    if scorecard.startswith("REJECT"):
        failing.append(f"scorecard:{scorecard.lower()}")

    return ReentryDecision(
        passed=not failing,
        fired_triggers=fired,
        failing=tuple(failing),
        scorecard=scorecard,
    )


def budget_ok(families: int, finalists: int, implemented: int) -> bool:
    """§37 — a reentry cycle may not exceed the frozen research budget."""
    return (
        families <= REENTRY_BUDGET["MAX_FAMILIES"]
        and finalists <= REENTRY_BUDGET["MAX_FINALISTS"]
        and implemented <= REENTRY_BUDGET["MAX_IMPLEMENTED"]
    )


def second_implementation_allowed(single_implemented_failed_business_edge: bool) -> bool:
    """§38 — a failed single implementation pauses again; no automatic second run."""
    return not single_implemented_failed_business_edge


def alpha_rfc_allowed(freeze_active: bool, reentry_passed: bool) -> bool:
    """§25/§66 — no new alpha RFC while frozen; only after a reentry PASS."""
    return (not freeze_active) and bool(reentry_passed)


# --------------------------------------------------------------------------- #
# §48-§49 — paper / live admission
# --------------------------------------------------------------------------- #


def paper_admission_allowed(business_edge_pass: bool) -> bool:
    """§48 — a positive validation net is NOT enough for paper."""
    return bool(business_edge_pass)


def live_admission_allowed(
    *,
    paper_execution_pass: bool,
    forward_evidence: bool,
    risk_approval: bool,
    human_capital_approval: bool,
) -> bool:
    """§49 — live authorization is never automatic."""
    return all((paper_execution_pass, forward_evidence, risk_approval, human_capital_approval))


def canary_capital_role() -> dict[str, Any]:
    """§50 — the 200 USDT is future canary capital only, not used now."""
    return {
        "reference_initial_capital_usdt": REFERENCE_INITIAL_CAPITAL_USDT,
        "role": "FUTURE_LIVE_CANARY_CAPITAL",
        "usable_now": False,
        "eligible_only_when": "CANARY_ELIGIBLE",
    }


# --------------------------------------------------------------------------- #
# §44-§47 — proven / not-proven / lessons / value chain
# --------------------------------------------------------------------------- #

PROVEN: tuple[str, ...] = (
    "runtime can research deterministically",
    "lookahead protections work",
    "cost accounting works",
    "false positives have been detected",
    "external strategies can be reproduced",
    "product-fit can be tested",
    "risk-matched business gates work",
)

NOT_PROVEN: tuple[str, ...] = (
    "business edge",
    "forward profitability",
    "live profitability",
    "capital scalability",
    "repeatable real-money alpha",
)

LESSONS: tuple[str, ...] = (
    "POSITIVE BACKTEST != BUSINESS EDGE",
    "BUSINESS EDGE != LIVE PROFIT",
)

VALUE_CHAIN: tuple[str, ...] = (
    "EXTERNAL EVIDENCE",
    "PRODUCT FIT",
    "REPRODUCTION",
    "DISCOVERY",
    "VALIDATION",
    "BENCHMARK EDGE",
    "ROBUSTNESS",
    "PAPER CERTIFICATION",
    "FORWARD PAPER",
    "CANARY",
    "LIVE",
)

PRODUCT_METRICS: tuple[str, ...] = (
    "minimum_viable_capital",
    "expected_turnover",
    "expected_costs",
    "historical_cagr",
    "historical_sharpe",
    "max_drawdown",
    "benchmark_cagr",
    "benchmark_sharpe",
    "risk_matched_excess_return",
    "illustrative_pnl_at_reference_capital",
)

PLATFORM_CAPABILITIES: tuple[str, ...] = (
    "PIT validation",
    "cost modeling",
    "strategy reproduction",
    "candidate rejection",
    "independent verification",
    "business-edge testing",
)

# --------------------------------------------------------------------------- #
# §71 — FALSE_SUCCESS triggers (target 0)
# --------------------------------------------------------------------------- #

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "historical_positive_called_business_edge",
    "validated_defensive_called_profit_engine",
    "dual_momentum_promoted_despite_benchmark_failure",
    "mf_trend_called_product_fit_for_200",
    "paper_candidate_left_active",
    "live_readiness_implied",
    "new_p3_created",
    "next_alpha_rfc_enabled",
    "tests_used_as_profitability_evidence",
)


def false_success_count(claims: Mapping[str, bool]) -> int:
    """§71 — count only genuine incorrect claims/bypasses, never a strategy loss."""
    return sum(1 for t in FALSE_SUCCESS_TRIGGERS if claims.get(t, False))


# --------------------------------------------------------------------------- #
# §61 — stale status audit
# --------------------------------------------------------------------------- #

#: Each entry documents a tracked claim that RFC-041 marks SUPERSEDED.
STALE_STATUS_ENTRIES: tuple[dict[str, str], ...] = (
    {
        "source": "docs/research/MANAGED_FUTURES_TREND_V1.md",
        "stale_claim": "NEXT = PAPER_CANDIDATE_CERTIFICATION / 'Executable validated edges = 1 / 1'",
        "superseded_by": "RFC-037/RFC-038 -> RFC-041 (MF-TREND-001 = RESEARCH_ASSET / NOT_CURRENT_PRODUCT)",
        "reason": "modern validation is DATA_BLOCKED and product-fit for 200 USDT FAILS",
    },
    {
        "source": "docs/research/MANAGED_FUTURES_TREND_V1.json",
        "stale_claim": "next = PAPER_CANDIDATE_CERTIFICATION",
        "superseded_by": "RFC-041 CANDIDATE_ARCHIVE / FINAL_BUSINESS_DECISION",
        "reason": "no paper path without BUSINESS_EDGE = PASS",
    },
    {
        "source": "docs/research/SMALL_CAPITAL_STRATEGY_V1.md",
        "stale_claim": "PAPER_ELIGIBILITY = PAPER_CERTIFICATION_ELIGIBLE / NEXT = SMALL_CAPITAL_PAPER_CERTIFICATION",
        "superseded_by": "RFC-040 -> RFC-041 (SC-TREND-001 = VALIDATED_DEFENSIVE / BUSINESS_FAIL)",
        "reason": "risk-adjusted performance is below the passive alternative",
    },
    {
        "source": "docs/research/SMALL_CAPITAL_STRATEGY_V1.json",
        "stale_claim": "PAPER_ELIGIBILITY = PAPER_CERTIFICATION_ELIGIBLE; NEXT = SMALL_CAPITAL_PAPER_CERTIFICATION",
        "superseded_by": "RFC-040 -> RFC-041",
        "reason": "no paper candidate survives the business-edge gate",
    },
    {
        "source": "docs/research/SMALL_CAPITAL_DUAL_MOMENTUM_V1.md",
        "stale_claim": "NEXT = STRATEGIC_BUSINESS_DECISION",
        "superseded_by": "RFC-041 (SC-DUALMOM-002 = REJECTED_BUSINESS_EDGE)",
        "reason": "the strategic business decision was taken: freeze, no reentry",
    },
    {
        "source": "docs/research/SMALL_CAPITAL_DUAL_MOMENTUM_V1.json",
        "stale_claim": "next = STRATEGIC_BUSINESS_DECISION",
        "superseded_by": "RFC-041",
        "reason": "resolved into ALPHA_RESEARCH_FREEZE = ACTIVE",
    },
    {
        "source": "docs/research/STRATEGIC_PROFITABILITY_PLAN_V2.json",
        "stale_claim": "next_alpha_rfc_allowed = true / phase_2_status = REENTRY_APPROVED",
        "superseded_by": "RFC-041 (ALPHA_RESEARCH_FREEZE = ACTIVE; next_alpha_rfc_allowed = false)",
        "reason": "Phase 2B closed with no business edge; the reentry contract now governs reopening",
    },
    {
        "source": "docs/research/PROJECT_ECONOMIC_STATUS.md|json",
        "stale_claim": "as_of_commit = 38b9700 (RFC-033); superseded_by pointer absent",
        "superseded_by": "RFC-041 ECONOMIC_STATE.json (decision BUSINESS-FREEZE-2026-001)",
        "reason": "single canonical machine-readable state now lives in ECONOMIC_STATE.json",
    },
    {
        "source": "docs/research/WHERE_WE_ARE.md",
        "stale_claim": "as_of_commit = 38b9700 (RFC-034 view)",
        "superseded_by": "RFC-041 FINAL_BUSINESS_DECISION",
        "reason": "now includes RFC-036..RFC-040 evidence and the business freeze",
    },
)


def stale_status_audit() -> dict[str, Any]:
    return {
        "entries": list(STALE_STATUS_ENTRIES),
        "entry_count": len(STALE_STATUS_ENTRIES),
        "policy": "mark SUPERSEDED, never delete history; canonical state is UPDATED",
    }


# --------------------------------------------------------------------------- #
# §58-§59 — single canonical machine-readable state
# --------------------------------------------------------------------------- #


def economic_state(
    *, source_commit: str, updated_at: str, kpi: Mapping[str, int] | None = None
) -> dict[str, Any]:
    """§58-§60 — the one canonical state object future RFCs must read."""
    counts = dict(kpi) if kpi is not None else kpi_counts()
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": updated_at,
        "source_commit": source_commit,
        "decision_id": DECISION_ID,
        "rfc": "RFC-041",
        "reference_initial_capital_usdt": REFERENCE_INITIAL_CAPITAL_USDT,
        "live_capital_authorized": LIVE_CAPITAL_AUTHORIZED,
        "platform_status": PLATFORM_STATUS,
        "profitability_status": PROFITABILITY_STATUS,
        "research_status": RESEARCH_STATUS,
        "paper_status": PAPER_STATUS,
        "live_status": LIVE_STATUS,
        "alpha_research_freeze": ALPHA_RESEARCH_FREEZE,
        "phase_status": dict(PHASE_STATUS),
        "kpi": counts,
        "primary_kpi": KPI_PRIMARY,
        "active_candidates": active_candidate_count(),
        "candidate_statuses": canonical_candidate_statuses(),
        "current_decision": CURRENT_DECISION,
        "next_alpha_rfc_allowed": alpha_rfc_allowed(True, False),
        "capital_principle": CAPITAL_PRINCIPLE,
    }
