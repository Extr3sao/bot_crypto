"""IndependentVerifier — BUILDER != VERIFIER, enforced inside the runtime (§7).

The verifier is a SEPARATE component from the decision path. It receives the
raw history, the exact slice the decision consumed, the proposal and the
inputs used to cost it, and then re-derives everything it can:

* the PIT slice must be EXACTLY the bars at or before the decision time
  (no future bar, no silently dropped bar);
* the round-trip cost is recomputed from COST_MODEL_V3 with the same inputs;
* the proposal arithmetic (gross - cost = net) is re-checked;
* the admission status is re-read from the ledger (never trusted from the
  proposal);
* TRADE_PAPER requires admitted-for-paper + a risk review that actually ran;
* SHADOW_TRADE must show zero orders.

Any failure ⇒ ``FAIL`` ⇒ the runtime fails closed to NO_TRADE. The verifier
never approves size, limits or leverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.microstructure.cost_model_v3 import LiquidityRegime, OrderType

from .admission_ledger import AdmissionLedger
from .contracts import (
    DecisionMode,
    TradeProposal,
    VerificationCheck,
    VerificationResult,
    VerifierVerdict,
)
from .costs import COST_MODEL_VERSION, CostEngine

__all__ = ["VERIFIER_VERSION", "IndependentVerifier", "VerificationRequest"]

VERIFIER_VERSION = "independent-verifier-v1"

#: Tolerance for recomputed-vs-declared values (float round-trip only).
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    """Everything the verifier needs, and nothing it can mutate."""

    run_id: str
    decision_id: str
    asset: str
    decision_time_ms: int
    declared_mode: DecisionMode
    raw_history: tuple[OHLCV, ...]
    used_bars: tuple[OHLCV, ...]
    window_end_ts: int
    context_fingerprint: str
    proposal: TradeProposal | None
    cost_inputs: dict[str, Any]
    risk_reviewed: bool
    orders_created: int
    shadow_marked: bool | None = None


class IndependentVerifier:
    """Deterministic, independent re-derivation of the decision packet."""

    def __init__(
        self,
        *,
        ledger: AdmissionLedger,
        cost_engine: CostEngine | None = None,
    ) -> None:
        self._ledger = ledger
        self._cost_engine = cost_engine or CostEngine()

    @property
    def version(self) -> str:
        return VERIFIER_VERSION

    def verify(self, request: VerificationRequest) -> VerificationResult:
        checks: list[VerificationCheck] = [
            self._check_pit_slice(request),
            self._check_context_fingerprint(request),
            self._check_mode_requirements(request),
            self._check_cost_recomputation(request),
            self._check_arithmetic(request),
            self._check_admission_recomputation(request),
            self._check_shadow_purity(request),
        ]
        failures = tuple(c.name for c in checks if not c.passed)
        return VerificationResult(
            decision_id=request.decision_id,
            verdict=VerifierVerdict.FAIL if failures else VerifierVerdict.PASS,
            checks=tuple(checks),
            failures=failures,
            verifier_version=VERIFIER_VERSION,
        )

    # -- individual checks --------------------------------------------------

    def _check_pit_slice(self, request: VerificationRequest) -> VerificationCheck:
        expected = [b.timestamp for b in request.raw_history if b.timestamp <= request.decision_time_ms]
        used = [b.timestamp for b in request.used_bars]
        if used and used != expected:
            return VerificationCheck(
                "pit_slice_exact",
                False,
                f"consumed bars are not the exact PIT slice (used={len(used)} expected={len(expected)})",
            )
        future = [ts for ts in used if ts > request.decision_time_ms]
        if future:
            return VerificationCheck(
                "pit_slice_exact",
                False,
                f"future bars consumed: {future[:3]}",
            )
        if request.window_end_ts > request.decision_time_ms:
            return VerificationCheck(
                "pit_slice_exact",
                False,
                f"window_end_ts {request.window_end_ts} > decision_ts {request.decision_time_ms}",
            )
        return VerificationCheck(
            "pit_slice_exact",
            True,
            f"{len(used)} bars, all <= decision_ts {request.decision_time_ms}",
        )

    def _check_context_fingerprint(self, request: VerificationRequest) -> VerificationCheck:
        if not request.context_fingerprint:
            return VerificationCheck("context_fingerprint", False, "missing data fingerprint")
        if request.proposal is not None and not request.proposal.context_fingerprint:
            return VerificationCheck(
                "context_fingerprint", False, "proposal has no context fingerprint"
            )
        if (
            request.proposal is not None
            and request.proposal.context_fingerprint
            and request.proposal.context_fingerprint != request.context_fingerprint
        ):
            return VerificationCheck(
                "context_fingerprint",
                False,
                "proposal fingerprint differs from the context fingerprint",
            )
        return VerificationCheck("context_fingerprint", True, request.context_fingerprint[:24])

    def _check_mode_requirements(self, request: VerificationRequest) -> VerificationCheck:
        if request.declared_mode is DecisionMode.TRADE_PAPER:
            if request.proposal is None:
                return VerificationCheck(
                    "paper_requires_proposal", False, "TRADE_PAPER without a proposal"
                )
            if not request.risk_reviewed:
                return VerificationCheck(
                    "paper_requires_proposal",
                    False,
                    "TRADE_PAPER without a deterministic risk review",
                )
            return VerificationCheck("paper_requires_proposal", True, "proposal + risk review present")
        return VerificationCheck(
            "paper_requires_proposal",
            True,
            f"not applicable for {request.declared_mode.value}",
        )

    def _check_cost_recomputation(self, request: VerificationRequest) -> VerificationCheck:
        proposal = request.proposal
        if proposal is None:
            return VerificationCheck("cost_model_applied", True, "no proposal to cost")
        if proposal.cost.cost_model_version != COST_MODEL_VERSION:
            return VerificationCheck(
                "cost_model_applied",
                False,
                f"unexpected cost model {proposal.cost.cost_model_version!r}",
            )
        if not proposal.cost.components:
            return VerificationCheck("cost_model_applied", False, "empty cost breakdown")
        inputs = request.cost_inputs
        if not inputs:
            return VerificationCheck(
                "cost_model_applied", False, "cost inputs missing: cannot re-derive"
            )
        recomputed = self._cost_engine.evaluate(
            size_usd=float(inputs["size_usd"]),
            horizon_minutes=float(inputs["horizon_minutes"]),
            spread_bps=None if inputs.get("spread_bps") is None else float(inputs["spread_bps"]),
            liquidity_regime=_as_regime(inputs.get("liquidity_regime", "normal")),
            volatility_bps=float(inputs.get("volatility_bps", 0.0) or 0.0),
            entry_order_type=_as_order_type(inputs.get("entry_order_type")),
            exit_order_type=_as_order_type(inputs.get("exit_order_type")),
        )
        if abs(recomputed.round_trip_bps - proposal.expected_cost_bps) > 1e-4:
            return VerificationCheck(
                "cost_model_applied",
                False,
                f"cost mismatch: recomputed {recomputed.round_trip_bps:.6f} != "
                f"declared {proposal.expected_cost_bps:.6f}",
            )
        return VerificationCheck(
            "cost_model_applied",
            True,
            f"{recomputed.round_trip_bps:.4f} bps re-derived ({recomputed.scenario_id})",
        )

    def _check_arithmetic(self, request: VerificationRequest) -> VerificationCheck:
        proposal = request.proposal
        if proposal is None:
            return VerificationCheck("proposal_arithmetic", True, "no proposal")
        expected = proposal.expected_gross_edge_bps - proposal.expected_cost_bps
        if abs(expected - proposal.expected_net_edge_bps) > _EPS:
            return VerificationCheck(
                "proposal_arithmetic",
                False,
                f"net {proposal.expected_net_edge_bps} != gross - cost {expected}",
            )
        if not proposal.evidence:
            return VerificationCheck("proposal_arithmetic", False, "proposal carries no evidence")
        return VerificationCheck("proposal_arithmetic", True, f"net={expected:.4f} bps")

    def _check_admission_recomputation(self, request: VerificationRequest) -> VerificationCheck:
        proposal = request.proposal
        if proposal is None:
            return VerificationCheck("admission_recomputed", True, "no proposal")
        actual = self._ledger.status_for(proposal.strategy_id)
        if actual is not proposal.admission_status:
            return VerificationCheck(
                "admission_recomputed",
                False,
                f"declared {proposal.admission_status.value} != ledger {actual.value}",
            )
        if request.declared_mode is DecisionMode.TRADE_PAPER and not self._ledger.is_paper_admitted(
            proposal.strategy_id
        ):
            return VerificationCheck(
                "admission_recomputed",
                False,
                f"{proposal.strategy_id} is not admitted for PAPER",
            )
        return VerificationCheck(
            "admission_recomputed", True, f"ledger says {actual.value} for {proposal.strategy_id}"
        )

    def _check_shadow_purity(self, request: VerificationRequest) -> VerificationCheck:
        if request.declared_mode is DecisionMode.SHADOW_TRADE:
            if request.orders_created != 0:
                return VerificationCheck(
                    "shadow_purity", False, f"SHADOW created {request.orders_created} order(s)"
                )
            if request.shadow_marked is False:
                return VerificationCheck("shadow_purity", False, "shadow decision not marked SHADOW")
            return VerificationCheck("shadow_purity", True, "shadow: 0 orders, marked SHADOW")
        if request.declared_mode is DecisionMode.NO_TRADE and request.orders_created != 0:
            return VerificationCheck(
                "shadow_purity", False, f"NO_TRADE created {request.orders_created} order(s)"
            )
        return VerificationCheck(
            "shadow_purity", True, f"not applicable for {request.declared_mode.value}"
        )


def _as_regime(value: Any) -> LiquidityRegime:
    text = str(value or "normal")
    if text not in ("deep", "normal", "thin"):
        raise ValueError(f"unknown liquidity regime {value!r}")
    return text  # type: ignore[return-value]


def _as_order_type(value: Any) -> OrderType | None:
    if value is None:
        return None
    text = str(value)
    if text not in ("market", "limit_post_only", "limit_ioc", "limit_gtc"):
        raise ValueError(f"unknown order type {value!r}")
    return text  # type: ignore[return-value]
