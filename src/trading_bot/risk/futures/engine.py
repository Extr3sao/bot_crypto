"""Deterministic futures risk engine: proposal in, RiskDecision out (§5-§11).

Check order is fixed and fail-closed. Each gate can only make the outcome more
conservative; no gate can widen a limit another gate already applied.

1. contract capability        → UNSUPPORTED_INSTRUMENT / INSTRUMENT_NOT_SUPPORTED
2. market-data validity       → DATA_INVALID (stale, future timestamp, no mark)
3. cost completeness          → NO_TRADE (COST_UNKNOWN)
4. risk-bounded sizing        → NO_TRADE / RISK_VETO
5. margin ladder + venue cap  → RISK_VETO (LIQUIDATION_RISK_UNKNOWN)
6. liquidation vs stop        → RISK_VETO (LIQUIDATION_BEFORE_STOP …)
7. portfolio & margin reserve → NO_TRADE / RISK_VETO (shared collateral, exposure)
8. approve for SIMULATION only → APPROVE_SIMULATION / REDUCE_SIMULATED_SIZE

The requested leverage is an *input to be capped*, never an authorisation: the
effective leverage is the minimum of the request, the policy cap and the venue's
bracket ceiling, and the engine re-checks the liquidation geometry at that level.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Any

from .contracts import (
    CostStatus,
    Direction,
    InstrumentNotSupported,
    PositionMode,
    RejectionCode,
    RiskDecision,
    RiskDecisionCode,
)
from .costs import FuturesCostModel, funding_context
from .instruments import InstrumentSpec
from .margin import LiquidationAssessment, MarginModel, StressScenario
from .portfolio import MarginLedger, PortfolioSnapshot
from .sizing import risk_bounded_sizing

__all__ = ["FuturesRiskEngine", "FuturesRiskPolicy", "RiskProposal", "ScenarioRequest"]

POLICY_VERSION = "RFC048-FUTURES-RISK-POLICY-v1"


@dataclass(frozen=True, slots=True)
class FuturesRiskPolicy:
    """Offline experimental policy. Every value is a test assumption, not a live
    authorisation (RFC-048 §5)."""

    risk_budget_pct: float = 0.01
    max_leverage: float = 5.0
    min_liquidation_buffer_bps: float = 50.0
    gap_reserve_pct: float = 0.002
    stress_slippage_bps: float = 5.0
    slippage_bps: float = 1.0
    max_gross_exposure_pct: float = 1.0
    max_net_exposure_pct: float = 1.0
    max_concentration_pct: float = 0.6
    max_margin_utilization_pct: float = 0.5
    max_positions: int = 3
    max_data_age_ms: int = 5 * 60 * 1000
    min_stop_distance_bps: float = 5.0
    max_drawdown_pct: float = 5.0
    max_daily_loss_pct: float = 1.0
    max_consecutive_losses: int = 3
    funding_stress_settlements: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_budget_pct": self.risk_budget_pct,
            "max_leverage": self.max_leverage,
            "min_liquidation_buffer_bps": self.min_liquidation_buffer_bps,
            "gap_reserve_pct": self.gap_reserve_pct,
            "stress_slippage_bps": self.stress_slippage_bps,
            "slippage_bps": self.slippage_bps,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_net_exposure_pct": self.max_net_exposure_pct,
            "max_concentration_pct": self.max_concentration_pct,
            "max_margin_utilization_pct": self.max_margin_utilization_pct,
            "max_positions": self.max_positions,
            "max_data_age_ms": self.max_data_age_ms,
            "min_stop_distance_bps": self.min_stop_distance_bps,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "funding_stress_settlements": self.funding_stress_settlements,
        }


@dataclass(frozen=True, slots=True)
class RiskProposal:
    """What the agent plane may ask for. Note what is absent: no size in units of
    risk, no margin, no liquidation price, no authorisation."""

    run_id: str
    decision_id: str
    instrument_id: str
    direction: Direction
    entry_price: float
    stop_price: float | None
    requested_notional: float
    requested_leverage: float
    horizon_minutes: float
    data_timestamp_ms: int
    decision_timestamp_ms: int
    mark_price: float | None = None
    position_mode: PositionMode = PositionMode.ISOLATED
    strategy_id: str = ""
    correlation_key: str = ""
    requested_by: str = "agent"
    live_route_requested: bool = False
    #: Optional, and never inferred: if the caller states the gross edge it
    #: expects over the horizon, the engine refuses the trade when the round
    #: trip costs eat it (RFC-048 §8: a strategy must beat its own costs).
    expected_gross_edge_usdt: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "instrument_id": self.instrument_id,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "requested_notional": self.requested_notional,
            "requested_leverage": self.requested_leverage,
            "horizon_minutes": self.horizon_minutes,
            "data_timestamp_ms": self.data_timestamp_ms,
            "decision_timestamp_ms": self.decision_timestamp_ms,
            "mark_price": self.mark_price,
            "position_mode": self.position_mode.value,
            "strategy_id": self.strategy_id,
            "correlation_key": self.correlation_key,
            "requested_by": self.requested_by,
            "live_route_requested": self.live_route_requested,
            "expected_gross_edge_usdt": self.expected_gross_edge_usdt,
        }


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    """One offline scenario: a proposal plus a market snapshot and funding view."""

    proposal: RiskProposal
    snapshot: PortfolioSnapshot
    market: dict[str, Any]
    funding_observations: list[dict[str, Any]] = field(default_factory=list)
    funding_source_hash: str = ""
    stress_scenarios: tuple[StressScenario, ...] = ()


@dataclass(frozen=True, slots=True)
class EngineResult:
    """A decision plus everything the verifier needs to reproduce it."""

    decision: RiskDecision
    detail: dict[str, Any]


class FuturesRiskEngine:
    """Stateless decision core; the margin pool lives in the injected ledger."""

    def __init__(
        self,
        *,
        spec: InstrumentSpec,
        policy: FuturesRiskPolicy | None = None,
        ledger: MarginLedger | None = None,
    ) -> None:
        self._spec = spec
        self._policy = policy or FuturesRiskPolicy()
        self._ledger = ledger
        self._margin = MarginModel(spec)

    @property
    def policy(self) -> FuturesRiskPolicy:
        return self._policy

    @property
    def spec(self) -> InstrumentSpec:
        return self._spec

    # -- public API ----------------------------------------------------------

    def decide(self, request: ScenarioRequest) -> EngineResult:
        proposal = request.proposal
        policy = self._policy
        evidence: list[str] = []
        reasons: list[RejectionCode] = []

        if proposal.live_route_requested:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.LIVE_ROUTE_ATTEMPTED],
                ["the offline engine has no live route; the request is refused outright"],
                evidence,
            )

        # 0. numeric validity -----------------------------------------------------
        # Every number the engine reasons about must be real and finite. NaN is
        # the dangerous case: it defeats `<=`-style comparisons, so an
        # unvalidated NaN silently SATISFIES limits instead of failing them.
        # (RFC-048V DEF-048V-01: a NaN mark used to reach an approval.)
        numeric_reasons, numeric_notes = self._validate_numbers(request)
        if numeric_reasons:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.DATA_INVALID,
                numeric_reasons,
                numeric_notes,
                evidence,
            )

        # 1. contract capability -------------------------------------------------
        try:
            self._spec.ensure_usable(proposal.position_mode)
        except InstrumentNotSupported as exc:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.UNSUPPORTED_INSTRUMENT,
                [self._spec.unsupported_reason_code()],
                [exc.reason],
                evidence,
            )
        evidence.append(f"instrument={self._spec.instrument_id}@{self._spec.source_hash[:12]}")
        evidence.append(f"position_mode={proposal.position_mode.value}")

        # 2. market data validity ------------------------------------------------
        data_reasons, data_notes, age_ms = self._validate_data(request)
        if data_reasons:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.DATA_INVALID,
                data_reasons,
                data_notes,
                evidence,
            )
        evidence.append(f"data_age_ms={age_ms}")

        equity = request.snapshot.equity
        mark = proposal.mark_price or request.market.get("mark_price")
        entry = float(proposal.entry_price)
        risk_budget = equity * policy.risk_budget_pct
        evidence.append(
            f"risk_budget_usdt={risk_budget:.6f} (equity {equity} x {policy.risk_budget_pct})"
        )

        # 3. costs ---------------------------------------------------------------
        funding = funding_context(
            funding_observations=request.funding_observations,
            decision_timestamp_ms=proposal.decision_timestamp_ms,
            instrument=self._spec,
            horizon_minutes=proposal.horizon_minutes,
            source_hash=request.funding_source_hash,
        )
        cost_model = FuturesCostModel(self._spec, spread_bps=request.market.get("spread_bps"))
        requested_notional = max(float(proposal.requested_notional), self._spec.minimum_notional)

        def _costs_at(notional: float) -> Any:
            return cost_model.compute(
                notional=notional,
                direction=proposal.direction,
                horizon_minutes=proposal.horizon_minutes,
                funding=funding,
                depth=request.market.get("depth"),
                slippage_bps=policy.slippage_bps,
                stress_slippage_bps=policy.stress_slippage_bps,
            )

        sizing_costs = _costs_at(requested_notional)
        evidence.append(f"cost_status={sizing_costs.status.value}")
        if sizing_costs.status is CostStatus.COST_UNKNOWN:
            notes = [f"unknown cost components: {list(sizing_costs.unknown_components)}"]
            if "funding" in sizing_costs.unknown_components:
                reasons.append(RejectionCode.FUNDING_UNKNOWN)
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.NO_TRADE,
                [*reasons, RejectionCode.COST_UNKNOWN],
                notes,
                evidence,
                costs=sizing_costs,
            )

        # 4. sizing --------------------------------------------------------------
        sizing = risk_bounded_sizing(
            spec=self._spec,
            direction=proposal.direction,
            entry_price=entry,
            stop_price=proposal.stop_price,
            equity=equity,
            risk_budget=risk_budget,
            costs=sizing_costs,
            gap_reserve_pct=policy.gap_reserve_pct,
            requested_notional=float(proposal.requested_notional),
        )
        if not sizing.approved:
            code = (
                RiskDecisionCode.RISK_VETO
                if RejectionCode.STOP_MISSING in sizing.reasons
                or RejectionCode.RISK_BUDGET_EXCEEDED in sizing.reasons
                else RiskDecisionCode.NO_TRADE
            )
            return self._reject(
                proposal, request, code, list(sizing.reasons), list(sizing.notes), evidence
            )
        if sizing.quantity <= 0:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.NO_TRADE,
                [RejectionCode.INVALID_QUANTITY_STEP],
                ["quantity step produced a zero quantity"],
                evidence,
            )
        if proposal.stop_price is not None and abs(
            entry - proposal.stop_price
        ) / entry * 10_000.0 < (policy.min_stop_distance_bps):
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.STOP_TOO_CLOSE],
                [
                    f"stop distance {abs(entry - proposal.stop_price) / entry * 10_000.0:.4f} bps "
                    f"< policy minimum {policy.min_stop_distance_bps} bps"
                ],
                evidence,
            )

        # Costs are re-priced on the size that was actually approved: market
        # impact is not scale free, and the funding/liquidation terms charged
        # into the margin model must belong to the approved notional.
        sizing_costs = _costs_at(sizing.notional)
        if sizing_costs.status is CostStatus.COST_UNKNOWN:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.NO_TRADE,
                [RejectionCode.COST_UNKNOWN],
                [
                    f"unknown cost components at the approved size: {list(sizing_costs.unknown_components)}"
                ],
                evidence,
                sizing=sizing,
                costs=sizing_costs,
            )
        recheck = (
            sizing.notional * sizing.stop_distance_pct
            + sizing.notional * policy.gap_reserve_pct
            + sizing_costs.worst_case_cost_bps / 10_000.0 * sizing.notional
        )
        if recheck > risk_budget + 1e-9:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.RISK_BUDGET_EXCEEDED],
                [
                    f"re-pricing the approved size raised the worst-case loss to {recheck:.8f} "
                    f"> risk budget {risk_budget:.8f}"
                ],
                evidence,
                sizing=sizing,
                costs=sizing_costs,
            )

        # 4b. economic feasibility of the asked-for edge -------------------------
        if (
            proposal.expected_gross_edge_usdt is not None
            and proposal.expected_gross_edge_usdt <= sizing_costs.total_round_trip_usdt
        ):
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.NO_TRADE,
                [RejectionCode.FEES_EXCEED_HORIZON_EDGE],
                [
                    f"expected gross edge {proposal.expected_gross_edge_usdt:.8f} does not cover "
                    f"the round-trip cost {sizing_costs.total_round_trip_usdt:.8f}"
                ],
                evidence,
                sizing=sizing,
                costs=sizing_costs,
            )

        # 5. leverage + margin ---------------------------------------------------
        bracket = self._spec.bracket_for(sizing.notional)
        venue_ceiling = float(bracket.max_open_pos_leverage)
        requested_leverage = float(proposal.requested_leverage)
        if requested_leverage <= 0:
            requested_leverage = 1.0
        allowed_leverage = min(requested_leverage, policy.max_leverage, venue_ceiling)
        evidence.append(
            f"leverage_requested={requested_leverage} policy_cap={policy.max_leverage} "
            f"venue_ceiling={venue_ceiling} effective={allowed_leverage}"
        )
        initial_margin = self._margin.initial_margin(sizing.notional, allowed_leverage)
        maintenance, _ = self._margin.maintenance_margin(sizing.notional)
        evidence.append(
            f"initial_margin_usdt={initial_margin:.6f} maintenance_usdt={maintenance:.6f}"
        )

        # 5b. portfolio gate: hard limits refuse, soft limits SHRINK the size -------
        hard_reasons, hard_notes, cap = self._portfolio_gate(
            request=request,
            leverage=allowed_leverage,
            direction=proposal.direction,
            correlation_key=proposal.correlation_key,
        )
        if hard_reasons:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.NO_TRADE,
                hard_reasons,
                hard_notes,
                evidence,
                sizing=sizing,
                costs=sizing_costs,
                effective_leverage=allowed_leverage,
            )
        cap = min(cap, float(proposal.requested_notional))
        if cap < sizing.notional - 1e-9:
            clipped = self._spec.round_quantity_down(cap / entry)
            clipped_notional = clipped * entry
            if (
                clipped <= 0
                or (self._spec.quantity_min and clipped < self._spec.quantity_min)
                or clipped_notional < self._spec.minimum_notional
            ):
                return self._reject(
                    proposal,
                    request,
                    RiskDecisionCode.NO_TRADE,
                    [RejectionCode.EXPOSURE_LIMIT],
                    [
                        f"the portfolio allows at most {cap:.6f} of notional, below the venue "
                        f"minimum {self._spec.minimum_notional}"
                    ],
                    evidence,
                    sizing=sizing,
                    costs=sizing_costs,
                    effective_leverage=allowed_leverage,
                )
            evidence.append(
                f"portfolio_cap_clip={sizing.notional:.6f}->{clipped_notional:.6f} (cap {cap:.6f})"
            )
            sizing = replace(
                sizing,
                quantity=clipped,
                notional=clipped_notional,
                modeled_worst_loss=clipped_notional
                * (sizing.stop_distance_pct + policy.gap_reserve_pct)
                + clipped_notional * sizing_costs.worst_case_cost_bps / 10_000.0,
                gap_reserve_usdt=clipped_notional * policy.gap_reserve_pct,
                cost_usdt=clipped_notional * sizing_costs.worst_case_cost_bps / 10_000.0,
                notes=(*sizing.notes, "size clipped to the portfolio exposure limits"),
            )
            sizing_costs = _costs_at(sizing.notional)
            bracket = self._spec.bracket_for(sizing.notional)
            allowed_leverage = min(
                requested_leverage, policy.max_leverage, float(bracket.max_open_pos_leverage)
            )
            initial_margin = self._margin.initial_margin(sizing.notional, allowed_leverage)

        stress = request.stress_scenarios or (
            StressScenario(
                name="policy_default_adverse",
                adverse_move_pct=min(
                    0.05, max(sizing.stop_distance_pct + policy.gap_reserve_pct, 0.01)
                ),
                spread_widening_bps=policy.stress_slippage_bps,
                funding_settlements=policy.funding_stress_settlements,
                funding_rate=float(funding.adverse_rate or 0.0),
            ),
        )
        assessment = self._margin.assess(
            direction=proposal.direction,
            quantity=sizing.quantity,
            entry_price=entry,
            wallet_balance=initial_margin,
            market_price=mark,
            funding_owed_usdt=float(sizing_costs.funding_usdt),
            stress_scenarios=stress,
        )  # charges adverse funding + the venue liquidation fee before solving
        if not assessment.known:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                list(assessment.reasons) or [RejectionCode.LIQUIDATION_RISK_UNKNOWN],
                list(assessment.notes) or ["liquidation model incomplete"],
                evidence,
            )
        evidence.append(
            f"liquidation_price={assessment.liquidation_price} "
            f"buffer_bps={assessment.liquidation_buffer_bps}"
        )
        if assessment.liquidation_buffer_bps is None or (
            assessment.liquidation_buffer_bps < policy.min_liquidation_buffer_bps
        ):
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.LIQUIDATION_BUFFER_TOO_SMALL],
                [
                    f"liquidation buffer {assessment.liquidation_buffer_bps} bps below the "
                    f"policy minimum {policy.min_liquidation_buffer_bps} bps"
                ],
                evidence,
                assessment=assessment,
                sizing=sizing,
                costs=sizing_costs,
                effective_leverage=allowed_leverage,
            )
        if self._liquidation_precedes_stop(
            direction=proposal.direction,
            entry=entry,
            stop=proposal.stop_price,
            liquidation=assessment.liquidation_price,
        ):
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.LIQUIDATION_BEFORE_STOP],
                [
                    f"liquidation {assessment.liquidation_price} is reached before the stop "
                    f"{proposal.stop_price}: the stop cannot protect the position"
                ],
                evidence,
                assessment=assessment,
                sizing=sizing,
                costs=sizing_costs,
                effective_leverage=allowed_leverage,
            )
        if assessment.bracket_shifted:
            evidence.append("bracket_shift_tested=True")

        # 6a. the modelled loss must stay inside the isolated margin -------------
        if sizing.modeled_worst_loss > initial_margin + 1e-9:
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                [RejectionCode.LOSS_ABOVE_MARGIN],
                [
                    f"modelled worst loss {sizing.modeled_worst_loss:.8f} exceeds the isolated "
                    f"margin {initial_margin:.8f}: the gap reserve assumes a loss the margin "
                    "cannot fund"
                ],
                evidence,
                assessment=assessment,
                sizing=sizing,
                costs=sizing_costs,
                effective_leverage=allowed_leverage,
            )

        # 6b. a stress path that reaches liquidation voids the stop ------------
        breached = [
            row
            for row in assessment.stress_path
            if row["liquidation_price"] is not None
            and (
                row["mark_price"] <= row["liquidation_price"]
                if proposal.direction is Direction.LONG
                else row["mark_price"] >= row["liquidation_price"]
            )
        ]
        if breached:
            codes = [RejectionCode.GAP_BEYOND_STOP, RejectionCode.PARTIAL_LIQUIDATION_UNSUPPORTED]
            return self._reject(
                proposal,
                request,
                RiskDecisionCode.RISK_VETO,
                codes,
                [
                    "stress path "
                    f"{row['scenario']} moves the mark to {row['mark_price']} which is at or "
                    f"beyond the liquidation price {row['liquidation_price']}: the position "
                    "would be liquidated before the stop could execute, and partial "
                    "liquidation is not modelled"
                    for row in breached
                ],
                evidence,
                assessment=assessment,
                sizing=sizing,
                costs=sizing_costs,
                effective_leverage=allowed_leverage,
            )

        # 7. reserve margin atomically -------------------------------------------
        if self._ledger is not None:
            ok, granted, reason = self._ledger.try_reserve(
                initial_margin,
                decision_id=proposal.decision_id,
                collateral_group=f"ISOLATED:{self._spec.instrument_id}",
                # The declared utilisation ceiling is an AGGREGATE limit: it is
                # enforced by the ledger under its own lock, so two concurrent
                # decisions cannot each spend the same room against a stale
                # snapshot (RFC-048V DEF-048V-04).
                max_committed=self._policy.max_margin_utilization_pct * equity,
            )
            if not ok:
                return self._reject(
                    proposal,
                    request,
                    RiskDecisionCode.NO_TRADE,
                    [reason or RejectionCode.INSUFFICIENT_MARGIN],
                    ["free margin was consumed between the snapshot and the reservation"],
                    evidence,
                    assessment=assessment,
                    sizing=sizing,
                    costs=sizing_costs,
                    effective_leverage=allowed_leverage,
                )
            evidence.append(f"margin_reserved_usdt={granted:.6f}")
            snapshot = self._ledger.snapshot_of(request.snapshot, decision_id=proposal.decision_id)
        else:
            snapshot = request.snapshot

        # 8. verdict -------------------------------------------------------------
        reduced = (
            sizing.notional < float(proposal.requested_notional) - 1e-9
            or allowed_leverage < requested_leverage - 1e-9
        )
        decision_code = (
            RiskDecisionCode.REDUCE_SIMULATED_SIZE
            if reduced
            else RiskDecisionCode.APPROVE_SIMULATION
        )
        # Measured against the pre-reservation snapshot so the freshly reserved
        # margin is not counted twice.
        margin_utilization = (
            (request.snapshot.reserved_margin + initial_margin) / request.snapshot.equity * 100.0
            if request.snapshot.equity > 0
            else 100.0
        )
        decision = RiskDecision(
            decision_id=proposal.decision_id,
            run_id=proposal.run_id,
            instrument_id=self._spec.instrument_id,
            proposed_direction=proposal.direction,
            requested_notional=float(proposal.requested_notional),
            approved_notional=sizing.notional,
            requested_leverage=requested_leverage,
            effective_leverage=allowed_leverage,
            required_margin=initial_margin,
            risk_budget=risk_budget,
            modeled_worst_loss=sizing.modeled_worst_loss,
            liquidation_buffer_bps=assessment.liquidation_buffer_bps,
            fees_estimate=sizing_costs.entry_fee_usdt + sizing_costs.exit_fee_usdt,
            funding_estimate=sizing_costs.funding_expected_usdt,
            data_timestamp_ms=proposal.data_timestamp_ms,
            decision_timestamp_ms=proposal.decision_timestamp_ms,
            policy_version=POLICY_VERSION,
            decision=decision_code,
            rejection_reasons=(),
            evidence=tuple(evidence),
            quantity=sizing.quantity,
            entry_price=entry,
            stop_price=proposal.stop_price,
            liquidation_price=assessment.liquidation_price,
            maintenance_margin=assessment.maintenance_margin_entry,
            cost_status=sizing_costs.status,
            margin_utilization_pct=round(margin_utilization, 6),
            gross_exposure_after=snapshot.gross_exposure + sizing.notional,
            net_exposure_after=snapshot.net_exposure
            + (sizing.notional if proposal.direction is Direction.LONG else -sizing.notional),
            concentration_pct_after=round(
                (snapshot.exposure_by_asset().get(self._spec.base_asset, 0.0) + sizing.notional)
                / snapshot.equity
                * 100.0,
                6,
            )
            if snapshot.equity > 0
            else None,
            portfolio_snapshot_id=snapshot.snapshot_id,
            position_mode=proposal.position_mode,
            order_authorised=False,
        )
        return EngineResult(
            decision=decision,
            detail={
                "policy": policy.to_dict(),
                "instrument": self._spec.to_dict(),
                "sizing": sizing.to_dict(),
                "costs": sizing_costs.to_dict(),
                "funding_context": funding.to_dict(),
                "liquidation": assessment.to_dict(),
                "portfolio": snapshot.to_dict(),
                "proposal": proposal.to_dict(),
                "checks": [
                    "contract_capability",
                    "market_data_validity",
                    "cost_completeness",
                    "risk_budget_sizing",
                    "leverage_cap",
                    "liquidation_vs_stop",
                    "portfolio_aggregate",
                    "margin_reservation",
                ],
            },
        )

    # -- gates ---------------------------------------------------------------

    def _validate_numbers(self, request: ScenarioRequest) -> tuple[list[RejectionCode], list[str]]:
        """Refuse a request carrying any non-finite or impossible number.

        The checks are deliberately placed at the engine boundary (not only at
        the integrations): the engine is the deterministic authority, so it
        validates its own inputs. (RFC-048V DEF-048V-01/DEF-048V-06.)
        """
        proposal = request.proposal
        snapshot = request.snapshot
        market = request.market
        bad: list[str] = []

        def check(name: str, value: Any, *, positive: bool = True) -> None:
            if value is None:
                return
            try:
                number = float(value)
            except (TypeError, ValueError):
                bad.append(name)
                return
            if not math.isfinite(number) or (positive and number <= 0):
                bad.append(name)

        check("entry_price", proposal.entry_price)
        check("stop_price", proposal.stop_price)
        check("mark_price", proposal.mark_price)
        check("requested_notional", proposal.requested_notional)
        check("requested_leverage", proposal.requested_leverage)
        check("horizon_minutes", proposal.horizon_minutes)
        check("data_timestamp_ms", proposal.data_timestamp_ms)
        check("decision_timestamp_ms", proposal.decision_timestamp_ms)
        check("equity", snapshot.equity)
        check("free_margin", snapshot.free_margin, positive=False)
        check("reserved_margin", snapshot.reserved_margin, positive=False)
        check("snapshot_timestamp_ms", snapshot.timestamp_ms)
        check("daily_pnl", snapshot.daily_pnl, positive=False)
        check("drawdown_pct", snapshot.drawdown_pct, positive=False)
        check("consecutive_losses", snapshot.consecutive_losses, positive=False)
        for index, position in enumerate(snapshot.positions):
            check(f"positions[{index}].quantity", position.quantity, positive=False)
            check(f"positions[{index}].entry_price", position.entry_price)
            check(f"positions[{index}].notional", position.notional, positive=False)
            check(f"positions[{index}].reserved_margin", position.reserved_margin, positive=False)
        mark = proposal.mark_price if proposal.mark_price is not None else market.get("mark_price")
        check("market_mark_price", mark)
        spread = market.get("spread_bps")
        if spread is not None and not (
            isinstance(spread, (int, float))
            and not isinstance(spread, bool)
            and math.isfinite(float(spread))
        ):
            bad.append("spread_bps")
        for index, scenario in enumerate(request.stress_scenarios):
            if not math.isfinite(scenario.adverse_move_pct) or scenario.adverse_move_pct < 0:
                bad.append(f"stress[{index}].adverse_move_pct")
            if not math.isfinite(scenario.spread_widening_bps) or scenario.spread_widening_bps < 0:
                bad.append(f"stress[{index}].spread_widening_bps")
            if not math.isfinite(scenario.funding_rate):
                bad.append(f"stress[{index}].funding_rate")
            if scenario.funding_settlements < 0:
                bad.append(f"stress[{index}].funding_settlements")
        if not bad:
            return [], []
        return (
            [RejectionCode.INVALID_NUMERIC_INPUT],
            ["non-finite or out-of-range inputs: " + ", ".join(sorted(dict.fromkeys(bad)))],
        )

    def _validate_data(
        self, request: ScenarioRequest
    ) -> tuple[list[RejectionCode], list[str], int]:
        proposal = request.proposal
        reasons: list[RejectionCode] = []
        notes: list[str] = []
        age = proposal.decision_timestamp_ms - proposal.data_timestamp_ms
        if proposal.decision_timestamp_ms <= proposal.data_timestamp_ms:
            reasons.append(RejectionCode.FUTURE_TIMESTAMP)
            notes.append("the decision would use market data timestamped at or after itself")
        if age > self._policy.max_data_age_ms:
            reasons.append(RejectionCode.STALE_DATA)
            notes.append(f"data age {age} ms exceeds {self._policy.max_data_age_ms} ms")
        if not request.snapshot.provider_healthy:
            reasons.append(RejectionCode.PORTFOLIO_SNAPSHOT_STALE)
            notes.append("portfolio provider reported unhealthy")
        if request.snapshot.timestamp_ms > proposal.decision_timestamp_ms:
            reasons.append(RejectionCode.FUTURE_TIMESTAMP)
            notes.append("portfolio snapshot is timestamped after the decision")
        mark = proposal.mark_price or request.market.get("mark_price")
        if mark is None or float(mark) <= 0:
            reasons.append(RejectionCode.MISSING_MARK_PRICE)
            notes.append("mark price absent: liquidation cannot be separated from last/index")
        elif proposal.direction is Direction.LONG and float(mark) < proposal.entry_price * 0.5:
            reasons.append(RejectionCode.MISSING_MARK_PRICE)
            notes.append("mark price is implausible against the entry reference")
        if not self._spec.margin_ladder_complete:
            reasons.append(RejectionCode.INCOMPLETE_MARGIN_MODEL)
            notes.append("maintenance margin ladder incomplete")
        if self._spec.regulatory_eligibility_status == "PRODUCT_NOT_AVAILABLE":
            reasons.append(RejectionCode.VENUE_OR_PRODUCT_NOT_ELIGIBLE)
            notes.append("the product is not available in the operator's jurisdiction")
        return reasons, notes, age

    @staticmethod
    def _liquidation_precedes_stop(
        *, direction: Direction, entry: float, stop: float | None, liquidation: float | None
    ) -> bool:
        """True when liquidation is hit before the stop would be."""
        if stop is None or liquidation is None:
            return False
        if direction is Direction.LONG:
            return liquidation >= stop
        return liquidation <= stop

    def _portfolio_gate(
        self,
        *,
        request: ScenarioRequest,
        leverage: float,
        direction: Direction,
        correlation_key: str,
    ) -> tuple[list[RejectionCode], list[str], float]:
        """Hard portfolio limits (refuse) plus the maximum notional the book allows.

        Returns ``(reasons, notes, cap)``. A non-empty ``reasons`` means refuse;
        otherwise ``cap`` is the largest notional that satisfies every soft limit
        at the given leverage. The cap is a ceiling, never an allowance: the
        caller still keeps the smaller risk-bounded size.
        """
        snapshot = request.snapshot
        policy = self._policy
        reasons: list[RejectionCode] = []
        notes: list[str] = []
        equity = snapshot.equity
        if equity <= 0:
            return [RejectionCode.INSUFFICIENT_EQUITY], ["equity is not positive"], 0.0

        if snapshot.drawdown_pct >= policy.max_drawdown_pct:
            reasons.append(RejectionCode.EXPOSURE_LIMIT)
            notes.append(f"drawdown {snapshot.drawdown_pct}% >= {policy.max_drawdown_pct}%")
        if snapshot.daily_pnl < 0 and abs(snapshot.daily_pnl) >= equity * policy.max_daily_loss_pct:
            reasons.append(RejectionCode.EXPOSURE_LIMIT)
            notes.append("daily loss limit reached")
        if snapshot.consecutive_losses >= policy.max_consecutive_losses:
            reasons.append(RejectionCode.EXPOSURE_LIMIT)
            notes.append("consecutive-loss cooldown active")
        if len(snapshot.positions) >= policy.max_positions:
            reasons.append(RejectionCode.MAX_POSITIONS)
            notes.append(f"max positions reached ({policy.max_positions})")

        asset = self._spec.base_asset
        key = correlation_key or asset
        if correlation_key and snapshot.exposure_by_correlation().get(key, 0.0) > 0:
            reasons.append(RejectionCode.CORRELATED_POSITIONS)
            notes.append(f"an open position already shares correlation key {key!r}")

        if snapshot.margin_by_collateral_group() and any(
            group != "ISOLATED" for group in snapshot.margin_by_collateral_group()
        ):
            reasons.append(RejectionCode.SHARED_COLLATERAL_CONFLICT)
            notes.append("cross/shared collateral groups are not validated")
        if snapshot.reserved_margin > snapshot.equity + 1e-9:
            reasons.append(RejectionCode.SHARED_COLLATERAL_CONFLICT)
            notes.append("reserved margin already exceeds equity")
        if reasons:
            return reasons, notes, 0.0

        # -- soft limits: each one yields a notional ceiling ------------------
        caps: list[float] = []
        caps.append(max(equity * policy.max_gross_exposure_pct - snapshot.gross_exposure, 0.0))
        caps.append(
            max(
                equity * policy.max_concentration_pct
                - snapshot.exposure_by_asset().get(asset, 0.0),
                0.0,
            )
        )
        free = max(snapshot.free_margin, 0.0)
        caps.append(free * leverage)
        util_room = max(equity * policy.max_margin_utilization_pct - snapshot.reserved_margin, 0.0)
        caps.append(util_room * leverage)

        signed = 1.0 if direction is Direction.LONG else -1.0
        net_ceiling = equity * policy.max_net_exposure_pct
        # |net + signed*n| <= ceiling  →  n <= (ceiling*signed - net)*signed
        caps.append(max((net_ceiling * signed - snapshot.net_exposure) * signed, 0.0))

        return [], notes, max(min(caps), 0.0)

    # -- helpers -------------------------------------------------------------

    def _reject(
        self,
        proposal: RiskProposal,
        request: ScenarioRequest,
        code: RiskDecisionCode,
        reasons: list[RejectionCode],
        notes: list[str],
        evidence: list[str],
        *,
        assessment: LiquidationAssessment | None = None,
        sizing: Any = None,
        costs: Any = None,
        effective_leverage: float = 0.0,
    ) -> EngineResult:
        unique = list(dict.fromkeys(reasons))
        if not unique:
            unique = [RejectionCode.INSTRUMENT_NOT_SUPPORTED]
        equity = request.snapshot.equity
        decision = RiskDecision(
            decision_id=proposal.decision_id,
            run_id=proposal.run_id,
            instrument_id=self._spec.instrument_id,
            proposed_direction=proposal.direction,
            requested_notional=float(proposal.requested_notional),
            approved_notional=0.0,
            requested_leverage=float(proposal.requested_leverage),
            effective_leverage=effective_leverage,
            required_margin=0.0,
            risk_budget=equity * self._policy.risk_budget_pct,
            modeled_worst_loss=0.0,
            liquidation_buffer_bps=(
                assessment.liquidation_buffer_bps if assessment is not None else None
            ),
            fees_estimate=0.0,
            funding_estimate=0.0,
            data_timestamp_ms=proposal.data_timestamp_ms,
            decision_timestamp_ms=proposal.decision_timestamp_ms,
            policy_version=POLICY_VERSION,
            decision=code,
            rejection_reasons=tuple(unique),
            evidence=tuple([*evidence, *[f"gate_note: {n}" for n in notes]]),
            quantity=0.0,
            entry_price=float(proposal.entry_price),
            stop_price=proposal.stop_price,
            liquidation_price=(assessment.liquidation_price if assessment is not None else None),
            maintenance_margin=(
                assessment.maintenance_margin_entry if assessment is not None else 0.0
            ),
            cost_status=(costs.status if costs is not None else CostStatus.COST_UNKNOWN),
            gross_exposure_after=request.snapshot.gross_exposure,
            net_exposure_after=request.snapshot.net_exposure,
            portfolio_snapshot_id=request.snapshot.snapshot_id,
            position_mode=proposal.position_mode,
            order_authorised=False,
        )
        return EngineResult(
            decision=decision,
            detail={
                "policy": self._policy.to_dict(),
                "instrument": self._spec.to_dict(),
                "proposal": proposal.to_dict(),
                "rejection_notes": notes,
                "sizing": sizing.to_dict() if sizing is not None else None,
                "costs": costs.to_dict() if costs is not None else None,
                "liquidation": assessment.to_dict() if assessment is not None else None,
                "portfolio": request.snapshot.to_dict(),
                "checks": ["fail_closed"],
            },
        )


def now_ms() -> int:
    return int(time.time() * 1000)
