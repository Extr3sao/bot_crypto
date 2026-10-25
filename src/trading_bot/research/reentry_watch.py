"""RFC-044 — profitability reentry watch (economic governance infrastructure).

Executable encoding of the *reentry* mechanism RFC-044 is allowed to build while
``ALPHA_RESEARCH_FREEZE = ACTIVE``.  This module contains **no alpha, no strategy
class, no signal, no backtest, no portfolio model, no broker, no paper and no
live code** (§2/§58).  It only provides the deterministic governance primitives
shared by the RFC-044 runner and its independent verifier:

* the valid reentry event classes (§5) and the invalid non-events (§6),
* the source-quality rules (§11-§13) and the duplicate-family detector (§14),
* the cheapest-falsification / no-backtest kill-test contract (§15-§16),
* the expected-research-value ordering score (§17) and the critical gates (§18),
* the cycle budgets (§19-§21), the ``G_BUSINESS_REENTRY`` gate (§22-§23),
* the one-candidate ``REENTRY_LEASE`` with ``MAX_PARAMETER_VARIANTS = 1`` (§24-§27),
* the always-visible profit KPIs (§28) and the FALSE_SUCCESS triggers (§57).

The independent verifier re-derives the same invariants from the *written*
artifacts and never imports this module.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# --------------------------------------------------------------------------- #
# §7/§33 — the capital contract never moves on its own
# --------------------------------------------------------------------------- #

REFERENCE_CAPITAL_USDT = 200.0
CAPITAL_CONSTRAINT = "STRATEGY MUST FIT CAPITAL"
CAPITAL_IS_NOT_ALPHA = "MORE CAPITAL MULTIPLIES EDGE; IT DOES NOT CREATE EDGE"

# --------------------------------------------------------------------------- #
# §2/§45 — the freeze is not negotiable
# --------------------------------------------------------------------------- #

ALPHA_RESEARCH_FREEZE = "ACTIVE"
NEXT_ALPHA_RFC_ALLOWED = "NO"
RESEARCH_STATUS = "PAUSED"
ACTIVE_CANDIDATES = 0

# --------------------------------------------------------------------------- #
# §5 — only these event classes can reopen evaluation
# --------------------------------------------------------------------------- #

VALID_TRIGGER_TYPES: tuple[str, ...] = (
    "A_NEW_EXTERNAL_EVIDENCE",
    "B_NEW_STRUCTURAL_MECHANISM",
    "C_MATERIAL_CAPITAL_CHANGE",
    "D_MATERIAL_INSTRUMENT_OR_BROKER_CHANGE",
    "E_NEW_DATA_UNLOCKING_EXISTING_SUPPORTED_HYPOTHESIS",
)

TRIGGER_TYPE_DEFINITIONS: dict[str, str] = {
    "A_NEW_EXTERNAL_EVIDENCE": (
        "independent publication/replication of persistent post-publication "
        "risk-adjusted excess return"
    ),
    "B_NEW_STRUCTURAL_MECHANISM": (
        "new structural edge: institutional constraint, risk transfer, "
        "microstructure, forced flows, regulatory effect, structural carry or "
        "liquidity provision"
    ),
    "C_MATERIAL_CAPITAL_CHANGE": (
        "available capital changes materially from 200 USDT "
        "(CAPITAL_CHANGE_REVIEW; no arbitrary fixed amount)"
    ),
    "D_MATERIAL_INSTRUMENT_OR_BROKER_CHANGE": (
        "new fractional access, low-cost instrument, UCITS product, retail "
        "derivative or materially better cost structure"
    ),
    "E_NEW_DATA_UNLOCKING_EXISTING_SUPPORTED_HYPOTHESIS": (
        "new data, only if it unlocks an already economically supported "
        "hypothesis (data alone is never enough)"
    ),
}

# --------------------------------------------------------------------------- #
# §6 — these are never a new opportunity
# --------------------------------------------------------------------------- #

INVALID_EVENT_KINDS: tuple[str, ...] = (
    "new_indicator",
    "different_moving_average",
    "different_threshold",
    "different_crypto_symbol",
    "more_agents",
    "llm_prediction",
    "ml_on_old_features",
    "same_family_with_new_name",
    "parameter_tuning",
    "social_media_strategy_claim_alone",
)

# --------------------------------------------------------------------------- #
# §11-§13 — source quality, minimum evidence and post-publication survival
# --------------------------------------------------------------------------- #

SOURCE_QUALITY_LEVELS: tuple[str, ...] = ("A", "B", "C", "D")
SOURCE_QUALITY_MEANING: dict[str, str] = {
    "A": "peer-reviewed / strong independent replication",
    "B": "credible working paper / institutional research",
    "C": "credible implementation evidence",
    "D": "blog / social",
}
HIGH_QUALITY_SOURCES: tuple[str, ...] = ("A", "B")
LOW_QUALITY_SOURCES: tuple[str, ...] = ("C", "D")

MIN_INDEPENDENT_HIGH_QUALITY_SOURCES = 2

POST_PUBLICATION_CLASSES: tuple[str, ...] = (
    "SURVIVES",
    "WEAKENED",
    "DECAYED",
    "CONTRADICTORY",
    "UNKNOWN",
)
PREFERRED_POST_PUBLICATION = "SURVIVES"

# --------------------------------------------------------------------------- #
# §18 — critical gates: a low score is never compensated by a high total
# --------------------------------------------------------------------------- #

CRITICAL_GATE_THRESHOLDS: dict[str, int] = {
    "evidence": 3,
    "business_plausibility": 3,
    "capital_fit": 4,
    "tradability": 4,
    "data_feasibility": 3,
}

# --------------------------------------------------------------------------- #
# §19-§21/§25 — cycle budgets
# --------------------------------------------------------------------------- #

MAX_PENDING_OPPORTUNITIES = 10
MAX_DEEP_REVIEW = 2
MAX_AUTHORIZED_CANDIDATES = 1
MAX_PARAMETER_VARIANTS = 1

# --------------------------------------------------------------------------- #
# §22/§23 — the business reentry gate (normal outcome is FAIL)
# --------------------------------------------------------------------------- #

G_BUSINESS_REENTRY_CONDITIONS: tuple[str, ...] = (
    "VALID_TRIGGER",
    "MATERIALLY_NEW",
    "STRONG_EVIDENCE",
    "PRODUCT_FIT",
    "CAPITAL_FIT",
    "TRADABILITY",
    "DATA_FEASIBLE",
    "BENCHMARK_CASE",
    "CHEAP_FALSIFICATION_DEFINED",
)

# --------------------------------------------------------------------------- #
# §10 — the fields every opportunity in the inbox must declare
# --------------------------------------------------------------------------- #

OPPORTUNITY_FIELDS: tuple[str, ...] = (
    "OPPORTUNITY_ID",
    "DATE",
    "SOURCE",
    "CLAIM",
    "MECHANISM",
    "MARKET",
    "INSTRUMENT",
    "CAPITAL_REQUIREMENT",
    "EXPECTED_TURNOVER",
    "KNOWN_COSTS",
    "PRIMARY_BENCHMARK",
    "COUNTER_EVIDENCE",
    "TRIGGER_TYPE",
)

# --------------------------------------------------------------------------- #
# §24 — the one-candidate lease
# --------------------------------------------------------------------------- #

REENTRY_LEASE_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "trigger",
    "source_basis",
    "capital",
    "instrument",
    "primary_benchmark",
    "risk_matched_benchmark",
    "cost_model_requirement",
    "fastest_kill_test",
    "max_parameter_variants",
    "expires_on_completion",
)

# --------------------------------------------------------------------------- #
# §16 — a kill test never needs a backtest
# --------------------------------------------------------------------------- #

KILL_TEST_BASES: tuple[str, ...] = (
    "external_evidence",
    "arithmetic",
    "product_rules",
    "cost_estimates",
    "data_feasibility",
)

# --------------------------------------------------------------------------- #
# §26/§27 — future candidate contract and the no-runner-up rule
# --------------------------------------------------------------------------- #

CANDIDATE_STAGES: tuple[str, ...] = (
    "SOURCE SPEC",
    "REPRODUCTION",
    "DISCOVERY",
    "VALIDATION",
    "BUSINESS EDGE",
)
CANDIDATE_FAILURE_RULE = "STOP"
SECOND_BEST_POLICY = "PAUSE"

# --------------------------------------------------------------------------- #
# §30-§31 — effort and data cost
# --------------------------------------------------------------------------- #

RESEARCH_EFFORT_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")
DATA_COST_LEVELS: tuple[str, ...] = ("FREE", "LOW", "MEDIUM", "HIGH", "UNKNOWN")

# --------------------------------------------------------------------------- #
# §28/§48-§49 — profit KPIs stay visible and at zero
# --------------------------------------------------------------------------- #

PROFIT_KPIS: dict[str, int] = {
    "BUSINESS_VALIDATED_EDGE_COUNT": 0,
    "PAPER_CANDIDATE_COUNT": 0,
    "FORWARD_PROFITABLE_COUNT": 0,
    "LIVE_PROFITABLE_COUNT": 0,
    "REALIZED_TRADING_PNL": 0,
}

CURRENT_MILESTONE = "M0"
NEXT_ECONOMIC_MILESTONE = "BUSINESS_VALIDATED_EDGE 0 -> 1"

# §47 — the default when nothing new happened after RFC-042.
DEFAULT_NO_EVENT_DECISION = "NO_ACTION"
ALLOWED_DECISIONS: tuple[str, ...] = ("NO_ACTION", "ONE_REENTRY_CANDIDATE")

# --------------------------------------------------------------------------- #
# §41-§42 — no daemon, no schedule
# --------------------------------------------------------------------------- #

REENTRY_MODE = "EVENT_DRIVEN"
DAEMON_ALLOWED = False
SCHEDULED_ALPHA_SEARCH_ALLOWED = False

# --------------------------------------------------------------------------- #
# §57 — FALSE_SUCCESS triggers (target 0)
# --------------------------------------------------------------------------- #

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "idle_time_treated_as_event",
    "new_strategy_invented",
    "old_family_renamed",
    "weak_source_unlocks_research",
    "capital_constraint_ignored",
    "benchmark_missing",
    "strategy_implemented",
    "freeze_released_without_pass",
    "more_than_one_candidate_authorized",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_FAMILY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "based",
        "for",
        "in",
        "of",
        "on",
        "or",
        "strategy",
        "system",
        "the",
        "to",
        "trading",
        "with",
    }
)


def _family_tokens(text: object) -> frozenset[str]:
    """Normalise a family/mechanism description into comparable tokens."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
    return frozenset(tok for tok in cleaned.split() if tok and tok not in _FAMILY_STOPWORDS)


# --------------------------------------------------------------------------- #
# §5-§6 — trigger validity and non-events
# --------------------------------------------------------------------------- #


def is_valid_trigger(trigger: object) -> bool:
    """§5 — only the five declared event classes are valid triggers."""
    return str(trigger).strip().upper() in VALID_TRIGGER_TYPES


def is_invalid_event(kind: object) -> bool:
    """§6 — return True for the explicitly disallowed non-events."""
    return str(kind).strip().lower() in INVALID_EVENT_KINDS


# --------------------------------------------------------------------------- #
# §11-§13 — source quality and minimum evidence
# --------------------------------------------------------------------------- #


def source_quality_sufficient(qualities: Sequence[str]) -> bool:
    """§11 — a C/D-only basis is never enough to reopen research."""
    return any(str(q).strip().upper() in HIGH_QUALITY_SOURCES for q in qualities)


def minimum_evidence_met(sources: Sequence[Mapping[str, Any]]) -> bool:
    """§12-§13 — >=2 independent high-quality sources, or one strong source
    that provably survives post-publication."""
    high = [
        s
        for s in sources
        if str(s.get("quality", "")).strip().upper() in HIGH_QUALITY_SOURCES
    ]
    independent_high = [s for s in high if bool(s.get("independent", False))]
    if len(independent_high) >= MIN_INDEPENDENT_HIGH_QUALITY_SOURCES:
        return True
    survives = any(
        str(s.get("post_publication", "")).strip().upper() == PREFERRED_POST_PUBLICATION
        for s in high
    )
    return bool(high) and survives


# --------------------------------------------------------------------------- #
# §14 — duplicate family detector
# --------------------------------------------------------------------------- #


def detect_same_family_rehash(
    opportunity: Mapping[str, Any], archive_candidates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """§14 — a renamed rehash of an already-rejected family never reopens research."""
    candidate_text = opportunity.get("FAMILY") or opportunity.get("MECHANISM") or ""
    candidate_tokens = _family_tokens(candidate_text)
    matched: str | None = None
    if candidate_tokens:
        for entry in archive_candidates:
            if _family_tokens(entry.get("family", "")) == candidate_tokens:
                matched = str(entry.get("candidate_id", "UNKNOWN"))
                break
    return {
        "SAME_FAMILY_REHASH": matched is not None,
        "matched_candidate": matched,
        "note": (
            "normalized-token family equality against CANDIDATE_ARCHIVE; "
            "a rehash never reopens research"
        ),
    }


# --------------------------------------------------------------------------- #
# §10 — inbox validation
# --------------------------------------------------------------------------- #


def validate_opportunity(opportunity: Mapping[str, Any]) -> dict[str, Any]:
    """§10 — every inbox opportunity must declare the required fields and a
    valid trigger, and must not rest on a C/D-only source basis."""
    missing = [f for f in OPPORTUNITY_FIELDS if not str(opportunity.get(f, "")).strip()]
    trigger = str(opportunity.get("TRIGGER_TYPE", "")).strip().upper()
    valid_trigger = trigger in VALID_TRIGGER_TYPES
    quality = str(opportunity.get("SOURCE_QUALITY", "")).strip().upper()
    quality_ok = quality == "" or source_quality_sufficient([quality])
    return {
        "missing_fields": missing,
        "trigger": trigger,
        "valid_trigger": valid_trigger,
        "source_quality": quality,
        "source_quality_can_reopen": quality_ok,
        "is_valid": not missing and valid_trigger and quality_ok,
    }


def inbox_within_budget(pending_opportunities: int) -> bool:
    """§19 — cap the pending inbox so no infinite backlog is built."""
    return int(pending_opportunities) <= MAX_PENDING_OPPORTUNITIES


# --------------------------------------------------------------------------- #
# §17 — expected research value (ordering only)
# --------------------------------------------------------------------------- #


def score_research_value(scores: Mapping[str, float]) -> float:
    """§17 — EVIDENCE x BUSINESS_PLAUSIBILITY x PRODUCT_FIT x DATA_FEASIBILITY
    / IMPLEMENTATION_COST.  Ordinal only; never a probability of profit."""
    cost = float(scores.get("implementation_cost", 0.0))
    if cost <= 0:
        raise ValueError("implementation_cost must be positive")
    value = (
        float(scores.get("evidence", 0.0))
        * float(scores.get("business_plausibility", 0.0))
        * float(scores.get("product_fit", 0.0))
        * float(scores.get("data_feasibility", 0.0))
        / cost
    )
    return float(value)


# --------------------------------------------------------------------------- #
# §18 — critical gates
# --------------------------------------------------------------------------- #


def critical_gates(scores: Mapping[str, float]) -> dict[str, Any]:
    """§18 — any gate below its threshold eliminates the opportunity, and no
    total score can compensate for it."""
    failing = [
        name
        for name, threshold in CRITICAL_GATE_THRESHOLDS.items()
        if float(scores.get(name, 0.0)) < float(threshold)
    ]
    return {
        "thresholds": dict(CRITICAL_GATE_THRESHOLDS),
        "failing": failing,
        "passed": not failing,
    }


# --------------------------------------------------------------------------- #
# §30-§32 — effort, data cost and the economics sanity check
# --------------------------------------------------------------------------- #


def accept_research_effort(effort: object, marginal: bool) -> bool:
    """§30 — a marginal opportunity with HIGH effort is rejected."""
    return not (marginal and str(effort).strip().upper() == "HIGH")


def business_economics_sanity(potential_value: float, research_and_data_cost: float) -> bool:
    """§32 — never spend more investigating than the stage could justify."""
    return float(potential_value) > float(research_and_data_cost)


# --------------------------------------------------------------------------- #
# §22-§23 — the business reentry gate
# --------------------------------------------------------------------------- #


def business_reentry_gate(conditions: Mapping[str, bool]) -> dict[str, Any]:
    """§22 — PASS only when *every* G_BUSINESS_REENTRY condition holds.

    §23: the normal outcome is FAIL; the gate is not designed to produce
    candidates.
    """
    missing = [c for c in G_BUSINESS_REENTRY_CONDITIONS if not conditions.get(c, False)]
    return {
        "G_BUSINESS_REENTRY": "PASS" if not missing else "FAIL",
        "failing_conditions": missing,
    }


# --------------------------------------------------------------------------- #
# §24-§27 — the one-candidate lease
# --------------------------------------------------------------------------- #


def create_reentry_lease(**fields: Any) -> dict[str, Any]:
    """§24-§25 — build a REENTRY_LEASE.  ``max_parameter_variants`` is forced to
    1: the next strategy is a faithful reproduction, never an exploration."""
    lease = dict(fields)
    lease["max_parameter_variants"] = MAX_PARAMETER_VARIANTS
    lease["expires_on_completion"] = True
    if any(v is None or (isinstance(v, str) and not v.strip()) for v in lease.values()):
        raise ValueError("every REENTRY_LEASE field must be set")
    return lease


def authorize_candidates(leases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """§21 — at most one authorized candidate per cycle; there is no runner-up."""
    authorized: list[dict[str, Any]] = [dict(lease) for lease in leases]
    ok = len(authorized) <= MAX_AUTHORIZED_CANDIDATES
    return {
        "authorized_candidates": authorized[:MAX_AUTHORIZED_CANDIDATES] if ok else [],
        "count": len(authorized) if ok else 0,
        "authorized": len(authorized) == 1,
        "over_budget": not ok,
        "second_best_policy": SECOND_BEST_POLICY,
    }


# --------------------------------------------------------------------------- #
# §45-§47 — the current review result
# --------------------------------------------------------------------------- #


def reentry_decision(
    *, qualified_events: Sequence[Mapping[str, Any]], pending_opportunities: int = 0
) -> dict[str, Any]:
    """§45-§47 — with no qualified new event the result is ``NO_ACTION`` and the
    economic state is left untouched."""
    if not qualified_events:
        return {
            "decision": DEFAULT_NO_EVENT_DECISION,
            "G_BUSINESS_REENTRY": "NOT_EVALUATED",
            "authorized_candidate": "NONE",
            "next": "WAIT",
            "next_alpha_rfc_allowed": NEXT_ALPHA_RFC_ALLOWED,
            "pending_opportunities": int(pending_opportunities),
            "company_state_unchanged": True,
        }
    return {
        "decision": "ONE_REENTRY_CANDIDATE",
        "G_BUSINESS_REENTRY": "PASS",
        "authorized_candidate": "<pending review>",
        "next": "ONE_CANDIDATE_REPRODUCTION",
        "next_alpha_rfc_allowed": "ONE_CANDIDATE_ONLY",
        "pending_opportunities": int(pending_opportunities),
        "company_state_unchanged": False,
    }


# --------------------------------------------------------------------------- #
# §57 — FALSE_SUCCESS
# --------------------------------------------------------------------------- #


def false_success_count(claims: Mapping[str, bool]) -> int:
    """§57 — count only genuine governance bypasses or incorrect claims."""
    return sum(1 for t in FALSE_SUCCESS_TRIGGERS if claims.get(t, False))
