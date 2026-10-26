"""RFC-042 — business opportunity radar & re-entry decision governance.

Executable encoding of the *one-snapshot external-evidence screening run* that
RFC-042 is allowed to perform while ``ALPHA_RESEARCH_FREEZE = ACTIVE``.  This
module contains **no alpha, no strategy class, no signal, no order, no broker, no
paper and no live code** (§43/§45/§46).  It only provides the deterministic
governance primitives the RFC-042 runner and verifier share:

* the budget caps (max 8 screened, max 3 deep reviews, max 1 authorization, §6),
* the ten-dimension opportunity scorecard with non-compensable critical fails
  (§21-§22),
* the same-family rehash detector (§8),
* the default exclusions that may only be reopened with materially new evidence
  (§7),
* the ``G_BUSINESS_REENTRY`` decision rule (§26-§27),
* the single-candidate reentry lease (§41-§42) and the freeze transition (§40),
* the RFC-042 FALSE_SUCCESS triggers (§51).

The independent verifier re-derives the same invariants from the *written*
artifacts and never imports this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# §0/§49 — capital and profit KPIs stay visible and at zero
# --------------------------------------------------------------------------- #

REFERENCE_CAPITAL_USDT = 200.0

PROFIT_KPIS: dict[str, int] = {
    "BUSINESS_VALIDATED_EDGE_COUNT": 0,
    "PAPER_CANDIDATE_COUNT": 0,
    "FORWARD_PROFITABLE_COUNT": 0,
    "LIVE_PROFITABLE_COUNT": 0,
    "REALIZED_TRADING_PNL": 0,
}

# --------------------------------------------------------------------------- #
# §6 — search budget
# --------------------------------------------------------------------------- #

MAX_OPPORTUNITIES_SCREENED = 8
MAX_DEEP_REVIEWS = 3
MAX_REENTRY_CANDIDATES = 1

# --------------------------------------------------------------------------- #
# §4 — valid reentry triggers
# --------------------------------------------------------------------------- #

VALID_TRIGGERS: dict[str, str] = {
    "A": "new external evidence",
    "B": "new structural edge",
    "C": "capital change",
    "D": "broker or instrument change",
    "E": "new data unlocking an already supported hypothesis",
}

#: §4 — for RFC-042 the capital has not changed, so C is not prioritary.
PRIORITY_TRIGGERS: tuple[str, ...] = ("A", "B", "D")

# --------------------------------------------------------------------------- #
# §7 — families excluded by default (only MATERIALLY_NEW_EVIDENCE reopens them)
# --------------------------------------------------------------------------- #

EXCLUDED_FAMILIES: dict[str, str] = {
    "crypto_tsmom": "already has its own evidence (EXT-TSMOM-001/002/003)",
    "crypto_xmom": "already has its own evidence (EXT-XMOM-001)",
    "funding_carry": "already tested and rejected in Phase 1",
    "basis": "already tested and rejected in Phase 1",
    "positioning": "certified data but no reproducible net edge",
    "sc_trend_001": "SC-TREND-001 is VALIDATED_DEFENSIVE, not a profit engine",
    "sc_dualmom_002": "SC-DUALMOM-002 is REJECTED_BUSINESS_EDGE",
    "managed_futures_institutional_p1": "MF-TREND-001 fails product-fit for 200 USDT",
}

# --------------------------------------------------------------------------- #
# §8 — same-family rehash must be rejected, not renamed into a new idea
# --------------------------------------------------------------------------- #

#: Deterministic substitutions applied (repeatedly) before family comparison.
REHASH_NORMALISATIONS: tuple[tuple[str, str], ...] = (
    ("exponential moving average", "moving average"),
    ("simple moving average", "moving average"),
    ("ema", "moving average"),
    ("sma", "moving average"),
    ("relative strength", "momentum"),
    ("12 months", "lookback"),
    ("10 months", "lookback"),
    ("6 months", "lookback"),
    ("12 month", "lookback"),
    ("12m", "lookback"),
    ("10m", "lookback"),
    ("lookback window", "lookback"),
    ("threshold 1%", "threshold"),
    ("threshold 1", "threshold"),
    ("threshold 0%", "threshold"),
    ("threshold 0", "threshold"),
    ("btc", "crypto asset"),
    ("eth", "crypto asset"),
    ("sol", "crypto asset"),
    ("etf a", "etf instrument"),
    ("etf b", "etf instrument"),
    ("etf 1", "etf instrument"),
    ("etf 2", "etf instrument"),
)


def normalise_family(text: str) -> str:
    """§8 — collapse cosmetic substitutions into a comparable signature."""
    norm = " ".join(text.lower().replace("_", " ").replace("-", " ").split())
    changed = True
    while changed:
        changed = False
        for old, new in REHASH_NORMALISATIONS:
            if old in norm:
                norm = norm.replace(old, new)
                changed = True
    return norm


def is_same_family_rehash(original: str, proposed: str) -> bool:
    """§8 — True when *proposed* is only a renamed *original* family."""
    return normalise_family(original) == normalise_family(proposed)


# --------------------------------------------------------------------------- #
# §10-§11 — product fit and capital fit for 200 USDT
# --------------------------------------------------------------------------- #

CAPITAL_FIT_VALUES: tuple[str, ...] = ("PASS", "LIMITED", "FAIL")

#: §11 — FAIL removes an opportunity even with a spectacular academic Sharpe.
CAPITAL_FIT_ORDER: dict[str, int] = {"FAIL": 0, "LIMITED": 1, "PASS": 2}

# --------------------------------------------------------------------------- #
# §12 — accepted economic mechanisms
# --------------------------------------------------------------------------- #

MECHANISMS: tuple[str, ...] = (
    "behavioral",
    "risk premium",
    "forced flow",
    "institutional constraint",
    "liquidity premium",
    "structural carry",
    "regulatory",
    "slow capital",
    "other",
)

# --------------------------------------------------------------------------- #
# §13 — post-publication survival
# --------------------------------------------------------------------------- #

POST_PUBLICATION_VALUES: tuple[str, ...] = (
    "SURVIVES",
    "WEAKENED_BUT_PRESENT",
    "DECAYED",
    "CONTRADICTORY",
    "UNKNOWN",
)

# --------------------------------------------------------------------------- #
# §18 — implementation distance
# --------------------------------------------------------------------------- #

IMPLEMENTATION_DISTANCE_VALUES: tuple[str, ...] = (
    "RUNTIME_READY",
    "SMALL_INTEGRATION",
    "MEDIUM_INTEGRATION",
    "MAJOR_BUILD",
)

# --------------------------------------------------------------------------- #
# §19 — time to economic answer
# --------------------------------------------------------------------------- #

TIME_TO_ECONOMIC_ANSWER_VALUES: tuple[str, ...] = ("SHORT", "MEDIUM", "LONG")

# --------------------------------------------------------------------------- #
# §21-§22 — scorecard with non-compensable critical dimensions
# --------------------------------------------------------------------------- #

SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "external_evidence",
    "structural_mechanism",
    "post_publication_survival",
    "business_edge_plausibility",
    "capital_fit_200",
    "tradability",
    "data_feasibility",
    "cost_headroom",
    "implementation_distance",
    "research_expected_value",
)

#: §22 — below these thresholds an opportunity is removed regardless of total.
CRITICAL_THRESHOLDS: dict[str, int] = {
    "external_evidence": 3,
    "business_edge_plausibility": 3,
    "capital_fit_200": 4,
    "tradability": 4,
    "data_feasibility": 3,
}

MIN_SCORE = 0
MAX_SCORE = 5


def validate_scorecard(scores: Mapping[str, int]) -> None:
    """Raise ``ValueError`` for a missing dimension or an out-of-range score."""
    missing = [d for d in SCORECARD_DIMENSIONS if d not in scores]
    if missing:
        raise ValueError(f"scorecard missing dimensions: {missing}")
    for dim in SCORECARD_DIMENSIONS:
        value = scores[dim]
        if not isinstance(value, int) or not MIN_SCORE <= value <= MAX_SCORE:
            raise ValueError(f"scorecard score out of range for {dim!r}: {value!r}")


def total_score(scores: Mapping[str, int]) -> int:
    """Total score. A high total never authorizes reentry (§23)."""
    validate_scorecard(scores)
    return sum(int(scores[d]) for d in SCORECARD_DIMENSIONS)


def critical_fails(scores: Mapping[str, int]) -> tuple[str, ...]:
    """§22 — critical dimensions below threshold; not compensable by the total."""
    validate_scorecard(scores)
    return tuple(
        dim for dim, floor in CRITICAL_THRESHOLDS.items() if int(scores[dim]) < floor
    )


# --------------------------------------------------------------------------- #
# §16 — economic headroom classification
# --------------------------------------------------------------------------- #


def headroom_class(headroom: float | None) -> str:
    """§16 — >= 2.0 STRONG, 1.5-2.0 RESEARCHABLE, < 1.5 WEAK."""
    if headroom is None:
        return "UNKNOWN"
    if headroom >= 2.0:
        return "STRONG"
    if headroom >= 1.5:
        return "RESEARCHABLE"
    return "WEAK"


# --------------------------------------------------------------------------- #
# §6/§7/§8 — screening disposition
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Opportunity:
    """One externally-sourced opportunity considered by RFC-042."""

    opportunity_id: str
    title: str
    strategy_family: str
    mechanism: str
    trigger: str | None
    instrument: str
    capital_fit: str
    product_fit_200: str
    tradability: str
    data_feasibility: str
    post_publication: str
    implementation_distance: str
    time_to_economic_answer: str
    source_ids: tuple[str, ...]
    excluded_family_key: str | None = None
    materially_new_evidence: bool = False
    rehash_of: tuple[str, ...] = ()
    scores: Mapping[str, int] = field(default_factory=dict)


def disposition(opp: Opportunity) -> str:
    """§7/§8/§11 — deterministic pre- and post-screening disposition."""
    if opp.rehash_of:
        return "REJECTED_SAME_FAMILY_REHASH"
    if opp.excluded_family_key is not None and not opp.materially_new_evidence:
        return "EXCLUDED_BY_DEFAULT_WITHOUT_NEW_EVIDENCE"
    if opp.capital_fit == "FAIL" or opp.product_fit_200 == "FAIL":
        return "REJECTED_CAPITAL_FIT_200"
    if opp.scores:
        return "SCREENED"
    return "NOT_SCORED"


def rehash_rejected(opp: Opportunity, archive_families: Sequence[str]) -> bool:
    """§8 — True when the opportunity is only a renamed archived family."""
    return any(is_same_family_rehash(fam, opp.strategy_family) for fam in archive_families)


def screened(opps: Sequence[Opportunity]) -> tuple[Opportunity, ...]:
    """§6 — the screened set, after the hard cap of 8."""
    if len(opps) > MAX_OPPORTUNITIES_SCREENED:
        raise ValueError(
            f"opportunity universe exceeds MAX_OPPORTUNITIES_SCREENED="
            f"{MAX_OPPORTUNITIES_SCREENED}: {len(opps)}"
        )
    return tuple(o for o in opps if disposition(o) == "SCREENED")


def select_deep_reviews(
    opps: Sequence[Opportunity], *, limit: int = MAX_DEEP_REVIEWS
) -> tuple[str, ...]:
    """§23/§24 — highest total score first; deterministic tie-break.

    A high score only buys a DEEP_REVIEW, never a PASS.  Tie-break order is a
    higher cost-headroom score, then data feasibility, then opportunity id.
    """
    if limit > MAX_DEEP_REVIEWS:
        raise ValueError(f"limit exceeds MAX_DEEP_REVIEWS={MAX_DEEP_REVIEWS}")
    eligible = [o for o in screened(opps)]
    eligible.sort(
        key=lambda o: (
            -total_score(o.scores),
            -int(o.scores["cost_headroom"]),
            -int(o.scores["data_feasibility"]),
            o.opportunity_id,
        )
    )
    return tuple(o.opportunity_id for o in eligible[:limit])


# --------------------------------------------------------------------------- #
# §26-§27 — G_BUSINESS_REENTRY
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReentryVerdict:
    passed: bool
    failing: tuple[str, ...]
    trigger: str | None
    headroom: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "G_BUSINESS_REENTRY": "PASS" if self.passed else "FAIL",
            "trigger": self.trigger,
            "headroom": self.headroom,
            "failing_conditions": list(self.failing),
        }


def gate_business_reentry(
    *,
    trigger: str | None,
    materially_new_evidence: bool,
    credible_mechanism: bool,
    capital_fit: str,
    tradability_score: int,
    data_feasibility_score: int,
    headroom: float | None,
    benchmark_adjusted_value_credible: bool,
    fast_falsification_defined: bool,
    scores: Mapping[str, int],
    materially_better_than_archive: bool,
    no_critical_fail: bool | None = None,
) -> ReentryVerdict:
    """§26-§27 — PASS requires *all* conditions simultaneously.

    Anything missing means FAIL and the freeze stays ACTIVE (§28).  The gate
    never authorizes more than one candidate; the caller enforces §6's cap.
    """
    failing: list[str] = []
    if trigger not in VALID_TRIGGERS:
        failing.append("invalid_or_absent_trigger")
    if not materially_new_evidence:
        failing.append("no_new_or_material_evidence")
    if not credible_mechanism:
        failing.append("implausible_economic_mechanism")
    if capital_fit != "PASS":
        failing.append("capital_fit_200_not_pass")
    if tradability_score < CRITICAL_THRESHOLDS["tradability"]:
        failing.append("tradability_below_4")
    if data_feasibility_score < CRITICAL_THRESHOLDS["data_feasibility"]:
        failing.append("data_feasibility_below_3")
    if headroom_class(headroom) == "WEAK" or headroom is None:
        failing.append("insufficient_cost_headroom")
    if not benchmark_adjusted_value_credible:
        failing.append("no_credible_benchmark_adjusted_value")
    if not fast_falsification_defined:
        failing.append("no_fast_falsification_path")
    if not materially_better_than_archive:
        failing.append("not_materially_better_than_archived_candidates")

    fails = critical_fails(scores) if no_critical_fail is None else ()
    if no_critical_fail is False or fails:
        failing.append("critical_dimension_below_threshold")

    return ReentryVerdict(
        passed=not failing,
        failing=tuple(failing),
        trigger=trigger if failing or trigger in VALID_TRIGGERS else None,
        headroom=headroom_class(headroom),
    )


def authorize_single_candidate(passing: Sequence[str]) -> str | None:
    """§6/§29 — at most one candidate may ever be authorized."""
    if len(passing) > MAX_REENTRY_CANDIDATES:
        raise ValueError(
            f"more than MAX_REENTRY_CANDIDATES={MAX_REENTRY_CANDIDATES} "
            f"candidates would be authorized: {list(passing)}"
        )
    return passing[0] if passing else None


# --------------------------------------------------------------------------- #
# §40-§42 — freeze transition and the single reentry lease
# --------------------------------------------------------------------------- #


def freeze_transition(authorized_candidate: str | None) -> dict[str, Any]:
    """§40 — FAIL keeps the freeze; PASS releases it for *one* candidate only."""
    if authorized_candidate is None:
        return {
            "research_status": "PAUSED",
            "research_freeze": "ACTIVE",
            "next_alpha_rfc_allowed": False,
            "release_scope": "NONE",
        }
    return {
        "research_status": "REENTRY_APPROVED",
        "research_freeze": "RELEASED_FOR_ONE_CANDIDATE",
        "next_alpha_rfc_allowed": True,
        "release_scope": "ONE_CANDIDATE",
    }


def reentry_lease(
    *,
    candidate_id: str,
    source_basis: Sequence[str],
    capital_target: float,
    primary_benchmark: str,
    risk_matched_benchmark: str,
    max_parameter_variants: int,
    research_cycle_id: str,
) -> dict[str, Any]:
    """§41-§42 — one candidate, one reproduction, one validation cycle."""
    return {
        "candidate_id": candidate_id,
        "source_basis": list(source_basis),
        "capital_target": capital_target,
        "primary_benchmark": primary_benchmark,
        "risk_matched_benchmark": risk_matched_benchmark,
        "max_parameter_variants": max_parameter_variants,
        "research_cycle_id": research_cycle_id,
        "expires_on_completion": True,
    }


# --------------------------------------------------------------------------- #
# §51 — FALSE_SUCCESS triggers (target 0)
# --------------------------------------------------------------------------- #

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "old_rejected_family_renamed",
    "weak_source_treated_as_strong",
    "positive_return_treated_as_benchmark_edge",
    "product_fit_ignored",
    "capital_200_constraint_ignored",
    "paid_data_requirement_hidden",
    "internal_backtest_used_for_selection",
    "more_than_one_candidate_authorized",
    "strategy_implemented",
    "freeze_released_without_gate_pass",
)


def false_success_count(claims: Mapping[str, bool]) -> int:
    """§51 — count only genuine incorrect claims or bypasses."""
    return sum(1 for t in FALSE_SUCCESS_TRIGGERS if claims.get(t, False))
