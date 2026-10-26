"""DecisionEngine — the single authority for TRADE_PAPER / SHADOW_TRADE / NO_TRADE (§3).

Decision order (first match wins, fail closed):

1. an agent VETO            → NO_TRADE (``AGENT_VETO``)
2. verifier not PASS        → NO_TRADE (``VERIFIER_FAIL``)
3. no proposal              → NO_TRADE (``NO_PROPOSAL``)
4. strategy unknown         → NO_TRADE (``UNKNOWN_STRATEGY``)
5. deterministic risk VETO  → NO_TRADE (``RISK_VETO``)
6. gross edge <= 0          → NO_TRADE (``NO_GROSS_EDGE``)
7. net edge > 0 AND admitted → TRADE_PAPER
8. otherwise                → SHADOW_TRADE (``COST_KILLED`` / ``NOT_ADMITTED``)

Rule 7 is the ONLY path that authorises an order, and it requires a formal
PAPER_CANDIDATE admission plus a verifier PASS. A strategy that is not
admitted can never reach it, no matter how good its numbers look: the
research candidate is observed in SHADOW instead, so the system keeps
learning without pretending that an unproven edge is tradeable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args

from trading_bot.scanner.types import RejectionReason

from .contracts import (
    AdmissionEntry,
    AdmissionStatus,
    AgentMessage,
    DecisionMode,
    NoTradeKind,
    ReviewType,
    RiskReview,
    RiskVerdict,
    ShadowTradeDecision,
    TradeProposal,
    VerificationResult,
)

__all__ = [
    "CLASSIFICATIONS",
    "DECISION_ENGINE_VERSION",
    "NO_TRADE_KINDS",
    "UNIVERSE_FILTERED",
    "UNIVERSE_REJECTION_REASONS",
    "DecisionEngine",
    "DecisionRequest",
    "DecisionResult",
    "classification_for_scanner_rejection",
    "no_trade_kind_for",
    "unclassified_scanner_rejections",
]

DECISION_ENGINE_VERSION = "decision-engine-v1"

#: Classifications a decision can carry (machine-readable, non-narrative).
CLASSIFICATIONS = (
    "AGENT_VETO",
    "CONTEXT_ERROR",
    "COST_KILLED",
    "NO_ALPHA",
    "NO_GROSS_EDGE",
    "NO_MARKET_DATA",
    "NO_PROPOSAL",
    "NOT_ADMITTED",
    "PAPER_ADMITTED",
    "RISK_VETO",
    "UNIVERSE_FILTERED",
    "UNKNOWN_STRATEGY",
    "VERIFIER_FAIL",
)

#: Classifications that mean "this is not a trading decision today" — the
#: strategy itself is the reason, so the record stays a measurable
#: NO_TRADE_STRATEGIC hypothesis.
_STRATEGIC_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "COST_KILLED",
        "NO_ALPHA",
        "NO_GROSS_EDGE",
        "NO_PROPOSAL",
        "NOT_ADMITTED",
        "UNKNOWN_STRATEGY",
    }
)

#: Classifications whose cause is the DATA, not the strategy.
_DATA_CLASSIFICATIONS: frozenset[str] = frozenset({"CONTEXT_ERROR", "NO_MARKET_DATA"})

#: Classification for an asset the scanner's deterministic universe filters left
#: inactive (DEF-WP00-01). The cause is the market SELECTION, not the data: the
#: runtime never handed the asset to a strategy, so filing it under the data
#: classes reported a deliberate exclusion as an inability to read the market.
UNIVERSE_FILTERED = "UNIVERSE_FILTERED"
_UNIVERSE_CLASSIFICATIONS: frozenset[str] = frozenset({UNIVERSE_FILTERED})

#: Classifications where two independent reviewers disagreed with the packet.
_CONFLICT_CLASSIFICATIONS: frozenset[str] = frozenset({"AGENT_VETO", "VERIFIER_FAIL"})

#: Every classification a NO_TRADE may carry (see ``no_trade_kind_for``).
NO_TRADE_KINDS: frozenset[str] = (
    _STRATEGIC_CLASSIFICATIONS
    | _DATA_CLASSIFICATIONS
    | _UNIVERSE_CLASSIFICATIONS
    | _CONFLICT_CLASSIFICATIONS
    | {"RISK_VETO"}
)

#: Scanner rejections whose cause is the market SELECTION: each one is a frozen,
#: deterministic filter (liquidity, spread, volatility envelope, whitelist,
#: custom bounds), and none of them is a data failure. The list mirrors the
#: closed ``RejectionReason`` catalogue; a reason added there without being
#: classified here fails ``unclassified_scanner_rejections``.
UNIVERSE_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        "not_whitelisted",
        "volume_below_threshold",
        "volume_below_threshold_for_live_min_10M",
        "spread_above_threshold",
        "atr_out_of_range",
        "price_below_threshold",
    }
)

#: Scanner rejections whose cause IS the data: the scanner could not build the
#: history it needs, so the runtime genuinely could not decide. This is the one
#: reason in the catalogue that stays a DATA no-decision.
_DATA_REJECTION_REASONS: frozenset[str] = frozenset({"insufficient_history"})


def unclassified_scanner_rejections() -> frozenset[str]:
    """Scanner rejection reasons this taxonomy does not classify (ought to be ∅).

    The scanner publishes its reasons as a closed ``Literal``, so adding one
    there must be a deliberate decision here: whether it describes a selection
    or a data shortfall changes how the NO_TRADE is reported. Leaving it out
    would default it silently, which is exactly what this function forbids.
    """
    return (
        frozenset(get_args(RejectionReason))
        - UNIVERSE_REJECTION_REASONS
        - _DATA_REJECTION_REASONS
    )


def classification_for_scanner_rejection(reason: str | None) -> str:
    """Name the honest classification for an asset the scanner left inactive.

    Only an unreadable-history rejection is a data no-decision; every other
    catalogue reason is a selection decision. A reason outside the catalogue
    (another adapter, a hand-built snapshot) defaults to the selection class
    because that is the fact the runtime actually knows — the scanner said the
    asset is not in the tradable universe — and the raw string stays visible in
    the decision's ``reason``.
    """
    if reason in _DATA_REJECTION_REASONS:
        return "NO_MARKET_DATA"
    return UNIVERSE_FILTERED


def no_trade_kind_for(classification: str) -> NoTradeKind:
    """Map a NO_TRADE classification onto its honest kind (§4).

    Risk, data, universe and conflict are separated from the strategic ("the
    edge does not survive cost") class so a reader can never confuse "we chose
    not to trade" with "we could not decide".
    """
    if classification == "RISK_VETO":
        return NoTradeKind.NO_TRADE_RISK
    if classification in _CONFLICT_CLASSIFICATIONS:
        return NoTradeKind.NO_TRADE_CONFLICT
    if classification in _UNIVERSE_CLASSIFICATIONS:
        return NoTradeKind.NO_TRADE_UNIVERSE
    if classification in _DATA_CLASSIFICATIONS:
        return NoTradeKind.NO_TRADE_DATA
    if classification in _STRATEGIC_CLASSIFICATIONS:
        return NoTradeKind.NO_TRADE_STRATEGIC
    raise ValueError(f"classification {classification!r} is not a NO_TRADE classification")


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    run_id: str
    decision_id: str
    asset: str
    symbol: str
    market_time_ms: int
    decision_time_ms: int
    regime: str | None
    admission: AdmissionEntry
    proposal: TradeProposal | None
    verification: VerificationResult
    risk: RiskReview
    agent_messages: tuple[AgentMessage, ...] = ()
    shadow_evaluation_enabled: bool = True
    no_proposal_reason: str = "router_no_trade"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    mode: DecisionMode
    reason: str
    classification: str
    order_authorised: bool
    shadow: ShadowTradeDecision | None = None
    notional_usdt: float | None = None

    @property
    def is_shadow(self) -> bool:
        return self.mode is DecisionMode.SHADOW_TRADE

    @property
    def is_no_trade(self) -> bool:
        return self.mode is DecisionMode.NO_TRADE

    @property
    def no_trade_kind(self) -> NoTradeKind | None:
        """The honest kind of a NO_TRADE; ``None`` for every other mode."""
        if self.mode is not DecisionMode.NO_TRADE:
            return None
        return no_trade_kind_for(self.classification)

    def to_dict(self) -> dict[str, Any]:
        kind = self.no_trade_kind
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "classification": self.classification,
            "no_trade_kind": None if kind is None else kind.value,
            "order_authorised": self.order_authorised,
            "shadow": None if self.shadow is None else self.shadow.to_dict(),
            "notional_usdt": self.notional_usdt,
        }


class DecisionEngine:
    """Pure decision function: no I/O, no state, no side effects."""

    def __init__(self, *, version: str = DECISION_ENGINE_VERSION) -> None:
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def intend(self, request: DecisionRequest) -> DecisionResult:
        """What this packet WOULD be if risk and verification could pass.

        The runtime needs this because the deterministic risk engine must only
        be invoked when an order could actually follow, and the verifier must
        audit the mode that is really being attempted. ``intend`` is a pure
        pre-classification: it never authorises anything (``order_authorised``
        is always False) and ``decide`` still has the final say.
        """
        vetoes = [m for m in request.agent_messages if m.review_type is ReviewType.VETO]
        if vetoes:
            agents = ",".join(m.agent_id for m in vetoes)
            return self._no_trade(f"agent_veto:{agents}", "AGENT_VETO")
        if request.proposal is None:
            return self._no_trade(request.no_proposal_reason, "NO_PROPOSAL")
        if request.admission.status is AdmissionStatus.UNKNOWN:
            return self._no_trade(
                f"strategy_unknown_to_ledger:{request.proposal.strategy_id}", "UNKNOWN_STRATEGY"
            )
        proposal = request.proposal
        if proposal.expected_gross_edge_bps <= 0:
            return self._no_trade(
                f"gross_edge_not_positive:{proposal.expected_gross_edge_bps:.4f}bps",
                "NO_GROSS_EDGE",
            )
        if request.admission.admitted_for_paper and proposal.expected_net_edge_bps > 0:
            return DecisionResult(
                mode=DecisionMode.TRADE_PAPER,
                reason="admitted_candidate_with_positive_net_edge(intent)",
                classification="PAPER_ADMITTED",
                order_authorised=False,
            )
        classification = "COST_KILLED" if proposal.expected_net_edge_bps <= 0 else "NOT_ADMITTED"
        if not request.shadow_evaluation_enabled:
            return self._no_trade(f"{classification.lower()}_and_shadow_disabled", classification)
        return DecisionResult(
            mode=DecisionMode.SHADOW_TRADE,
            reason=(
                f"gross {proposal.expected_gross_edge_bps:.3f}bps vs cost "
                f"{proposal.expected_cost_bps:.3f}bps"
            ),
            classification=classification,
            order_authorised=False,
            shadow=self._shadow(request),
        )

    def decide(self, request: DecisionRequest) -> DecisionResult:
        self._reject_advisory_risk_on_an_order(request)
        vetoes = [m for m in request.agent_messages if m.review_type is ReviewType.VETO]
        if vetoes:
            agents = ",".join(m.agent_id for m in vetoes)
            return self._no_trade(f"agent_veto:{agents}", "AGENT_VETO")
        if not request.verification.passed:
            failures = ",".join(request.verification.failures) or request.verification.verdict.value
            return self._no_trade(f"verifier:{failures}", "VERIFIER_FAIL")
        if request.proposal is None:
            return self._no_trade(request.no_proposal_reason, "NO_PROPOSAL")
        if request.admission.status is AdmissionStatus.UNKNOWN:
            return self._no_trade(
                f"strategy_unknown_to_ledger:{request.proposal.strategy_id}", "UNKNOWN_STRATEGY"
            )
        # Only a BINDING risk veto blocks. An advisory verdict (recorded for a
        # decision that cannot order) never changes the outcome.
        if request.risk.verdict is RiskVerdict.VETO and not request.risk.advisory:
            return self._no_trade(f"risk_veto:{request.risk.reason}", "RISK_VETO")

        proposal = request.proposal
        if proposal.expected_gross_edge_bps <= 0:
            return self._no_trade(
                f"gross_edge_not_positive:{proposal.expected_gross_edge_bps:.4f}bps",
                "NO_GROSS_EDGE",
            )

        admitted = request.admission.admitted_for_paper
        net_positive = proposal.expected_net_edge_bps > 0

        if admitted and net_positive and request.risk.verdict in (
            RiskVerdict.PASS,
            RiskVerdict.ADJUST,
        ):
            return DecisionResult(
                mode=DecisionMode.TRADE_PAPER,
                reason=(
                    "admitted_candidate_with_positive_net_edge"
                    if request.risk.verdict is RiskVerdict.PASS
                    else f"admitted_candidate_risk_adjusted:{request.risk.reason}"
                ),
                classification="PAPER_ADMITTED",
                order_authorised=True,
                notional_usdt=request.risk.notional_usdt,
            )

        classification = "COST_KILLED" if not net_positive else "NOT_ADMITTED"
        if admitted and net_positive:
            # admitted + net positive but risk did not pass: fail closed.
            return self._no_trade(f"risk_not_pass:{request.risk.verdict.value}", "RISK_VETO")

        if not request.shadow_evaluation_enabled:
            return self._no_trade(
                f"{classification.lower()}_and_shadow_disabled", classification
            )

        return DecisionResult(
            mode=DecisionMode.SHADOW_TRADE,
            reason=(
                f"gross {proposal.expected_gross_edge_bps:.3f}bps vs cost "
                f"{proposal.expected_cost_bps:.3f}bps"
            ),
            classification=classification,
            order_authorised=False,
            shadow=self._shadow(request),
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _reject_advisory_risk_on_an_order(request: DecisionRequest) -> None:
        """Fail closed if an advisory review could sit on an authorising packet.

        An advisory review is only ever legal where no order can follow. If the
        packet is order-authorising (positive net edge on an admitted candidate)
        the review MUST be binding, otherwise the risk gate would be bypassable
        by simply marking it advisory.
        """
        proposal = request.proposal
        if not request.risk.advisory or proposal is None:
            return
        order_authorising = (
            request.admission.admitted_for_paper
            and proposal.expected_gross_edge_bps > 0
            and proposal.expected_net_edge_bps > 0
        )
        if order_authorising:
            raise ValueError(
                "advisory risk review cannot accompany an order-authorising packet"
            )

    def _no_trade(self, reason: str, classification: str) -> DecisionResult:
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"unknown classification {classification!r}")
        return DecisionResult(
            mode=DecisionMode.NO_TRADE,
            reason=reason,
            classification=classification,
            order_authorised=False,
        )

    def _shadow(self, request: DecisionRequest) -> ShadowTradeDecision:
        proposal = request.proposal
        assert proposal is not None  # guarded by the caller
        return ShadowTradeDecision(
            run_id=request.run_id,
            decision_id=request.decision_id,
            timestamp_ms=request.decision_time_ms,
            asset=request.asset,
            strategy_id=proposal.strategy_id,
            strategy_version=proposal.strategy_version,
            direction=proposal.direction,
            hypothetical_entry=proposal.entry_reference,
            expected_edge_bps=proposal.expected_gross_edge_bps,
            expected_cost_bps=proposal.expected_cost_bps,
            expected_net_edge_bps=proposal.expected_net_edge_bps,
            regime=request.regime,
            evidence=proposal.evidence,
            counter_evidence=proposal.counter_evidence,
            confidence=proposal.confidence,
            rejection_reason=(
                f"admission={request.admission.status.value}; "
                f"classification={'COST_KILLED' if proposal.expected_net_edge_bps <= 0 else 'NOT_ADMITTED'}"
            ),
            admission_status=request.admission.status,
            decision_time_ms=request.decision_time_ms,
        )
