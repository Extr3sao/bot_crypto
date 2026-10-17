"""RFC-048V — independent falsification regressions.

Every test in this file exists because a counterexample was actually FOUND
against the RFC-048 engine (commit ``19b1a0b``). The defect identifiers match
``data/rfc048/ADVERSARIAL_FINDINGS.json``; the original pre-fix behaviour is
recorded there and is reproducible from git, so nothing is hidden.

The unifying finding is DEF-048V-01: a non-finite number is not a data point.
NaN defeats every ``<=``-style comparison, so an unvalidated NaN used to
SATISFY limits (a NaN mark path reached an approval, and a NaN leverage reached
an approval carrying a NaN margin). The same class crashed the engine in other
paths (DEF-048V-02: NaN reached ``int()`` in the quantity rounding).

The properties at the bottom are the general form of the same idea: whatever
the number, the engine either refuses or returns a budget-respecting decision —
it never raises and it never approves something it cannot bound.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from trading_bot.autonomous.contracts import AdmissionStatus, EdgeEvidence
from trading_bot.autonomous.decision import DecisionEngine, DecisionMode
from trading_bot.risk.futures import (
    Direction,
    InstrumentSpec,
    MarginLedger,
    PortfolioSnapshot,
    RejectionCode,
    RiskDecisionCode,
    RiskProposal,
    ScenarioRequest,
    load_instrument_registry,
)
from trading_bot.risk.futures.engine import FuturesRiskEngine, FuturesRiskPolicy
from trading_bot.risk.futures.integration import (
    build_decision_request_from_review,
    run_engine_through_runtime,
    safe_review,
)
from trading_bot.risk.futures.margin import LiquidationStatus, MarginModel, StressScenario

DATA = Path(__file__).resolve().parents[3] / "data" / "rfc048"

pytestmark = pytest.mark.unit

EQUITY = 200.0
HOSTILE = (float("nan"), float("inf"), float("-inf"))


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def instrument() -> InstrumentSpec:
    return load_instrument_registry(DATA / "INSTRUMENTS.json").get("BINANCE_USDM_BTCUSDT_PERP")


@pytest.fixture(scope="module")
def market_payload() -> dict[str, object]:
    snapshot = json.loads((DATA / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))
    return {
        "mark_price": snapshot["mark_price"],
        "spread_bps": snapshot["spread_bps"],
        "depth": {"bids": snapshot["depth_bids"], "asks": snapshot["depth_asks"]},
        "data_timestamp_ms": snapshot["data_timestamp_ms"],
    }


@pytest.fixture(scope="module")
def funding_observations() -> list[dict[str, object]]:
    payload = json.loads((DATA / "FUNDING_HISTORY.json").read_text(encoding="utf-8"))
    return list(payload["observations"])


def make_policy(**overrides: object) -> FuturesRiskPolicy:
    base = FuturesRiskPolicy(
        risk_budget_pct=0.01,
        max_leverage=5.0,
        max_gross_exposure_pct=5.0,
        max_net_exposure_pct=5.0,
        max_concentration_pct=5.0,
        max_margin_utilization_pct=1.0,
    )
    return replace(base, **overrides)


def make_snapshot(**overrides: object) -> PortfolioSnapshot:
    base = PortfolioSnapshot(
        snapshot_id="SNAP-FALSIFY",
        timestamp_ms=1_791_582_761_730,
        equity=EQUITY,
        free_margin=EQUITY,
        reserved_margin=0.0,
    )
    return replace(base, **overrides)


def make_proposal(market: dict[str, object], **overrides: object) -> RiskProposal:
    mark = float(market["mark_price"])  # type: ignore[arg-type]
    base = RiskProposal(
        run_id="run-falsify",
        decision_id="dec-falsify",
        instrument_id="BINANCE_USDM_BTCUSDT_PERP",
        direction=Direction.LONG,
        entry_price=mark,
        stop_price=mark * 0.995,
        requested_notional=400.0,
        requested_leverage=5.0,
        horizon_minutes=60.0,
        data_timestamp_ms=int(market["data_timestamp_ms"]),  # type: ignore[arg-type]
        decision_timestamp_ms=int(market["data_timestamp_ms"]) + 1_000,  # type: ignore[arg-type]
        mark_price=mark,
        strategy_id="probe",
        correlation_key="btc",
    )
    return replace(base, **overrides)


def run(
    *,
    instrument: InstrumentSpec,
    market: dict[str, object],
    funding_observations: list[dict[str, object]],
    proposal: RiskProposal | None = None,
    snapshot: PortfolioSnapshot | None = None,
    policy: FuturesRiskPolicy | None = None,
    ledger: MarginLedger | None = None,
    stress: tuple[StressScenario, ...] = (),
) -> object:
    engine = FuturesRiskEngine(spec=instrument, policy=policy or make_policy(), ledger=ledger)
    return engine.decide(
        ScenarioRequest(
            proposal=proposal or make_proposal(market),
            snapshot=snapshot or make_snapshot(),
            market=market,
            funding_observations=funding_observations,
            funding_source_hash="funding-fixture",
            stress_scenarios=stress,
        )
    )


def codes(result: object) -> list[str]:
    return [r.value for r in result.decision.rejection_reasons]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# DEF-048V-01 — a non-finite input must be refused, never approved
# --------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize(
    "field",
    [
        "entry_price",
        "stop_price",
        "mark_price",
        "requested_notional",
        "requested_leverage",
        "horizon_minutes",
    ],
)
def test_non_finite_proposal_fields_are_refused(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    field: str,
    hostile: float,
) -> None:
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, **{field: hostile}),
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID  # type: ignore[attr-defined]
    assert RejectionCode.INVALID_NUMERIC_INPUT.value in codes(result)
    assert result.decision.approved_notional == 0.0  # type: ignore[attr-defined]


@pytest.mark.parametrize("hostile", HOSTILE)
def test_non_finite_snapshot_state_is_refused(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    hostile: float,
) -> None:
    """A NaN risk-limit input used to silently satisfy every limit comparison."""
    for field in ("equity", "drawdown_pct", "daily_pnl", "free_margin", "reserved_margin"):
        result = run(
            instrument=instrument,
            market=market_payload,
            funding_observations=funding_observations,
            snapshot=make_snapshot(**{field: hostile}),
        )
        assert result.decision.decision is RiskDecisionCode.DATA_INVALID, field  # type: ignore[attr-defined]
        assert RejectionCode.INVALID_NUMERIC_INPUT.value in codes(result), field


def test_non_finite_open_position_is_refused(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """A NaN exposure used to defeat the gross/concentration ceilings."""
    from trading_bot.risk.futures import PortfolioState

    position = PortfolioState(
        instrument_id="BINANCE_USDM_ETHUSDT_PERP",
        asset="ETH",
        direction=Direction.LONG,
        quantity=1.0,
        entry_price=3_000.0,
        notional=float("nan"),
        reserved_margin=0.0,
    )
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        snapshot=make_snapshot(positions=(position,)),
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID  # type: ignore[attr-defined]
    assert RejectionCode.INVALID_NUMERIC_INPUT.value in codes(result)


def test_non_finite_spread_is_refused(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """A NaN spread used to reach ``int()`` and crash the engine."""
    market = dict(market_payload)
    market["spread_bps"] = float("nan")
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID  # type: ignore[attr-defined]
    assert RejectionCode.INVALID_NUMERIC_INPUT.value in codes(result)


def test_non_finite_mark_is_not_silently_treated_as_present(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, mark_price=float("nan")),
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID  # type: ignore[attr-defined]
    assert result.decision.decision is not RiskDecisionCode.APPROVE_SIMULATION  # type: ignore[attr-defined]


def test_non_finite_depth_price_makes_the_cost_unknown(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    market = dict(market_payload)
    mark = float(market_payload["mark_price"])  # type: ignore[arg-type]
    market["depth"] = {
        "bids": [[mark * 0.999, float("nan")]],
        "asks": market_payload["depth"]["asks"],
    }  # type: ignore[index]
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
    )
    assert RejectionCode.COST_UNKNOWN.value in codes(result)
    assert result.decision.approved_notional == 0.0  # type: ignore[attr-defined]


def test_non_finite_funding_observation_makes_funding_unknown(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """A settlement inside the horizon with a corrupt rate is not a free period."""
    poisoned = [dict(o, funding_rate=float("nan")) for o in funding_observations]
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=poisoned,
        proposal=make_proposal(market_payload, horizon_minutes=540.0),
    )
    assert RejectionCode.FUNDING_UNKNOWN.value in codes(result)
    assert result.decision.approved_notional == 0.0  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# DEF-048V-06 — an unmodelable stress path is NOT "no stress"
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    [
        StressScenario(name="nan_move", adverse_move_pct=float("nan")),
        StressScenario(name="inf_move", adverse_move_pct=float("inf")),
        StressScenario(name="nan_spread", adverse_move_pct=0.02, spread_widening_bps=float("nan")),
        StressScenario(name="nan_funding", adverse_move_pct=0.02, funding_rate=float("nan")),
        StressScenario(name="negative_move", adverse_move_pct=-0.02),
    ],
)
def test_unmodelable_stress_is_refused_by_the_engine(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    scenario: StressScenario,
) -> None:
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        stress=(scenario,),
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID  # type: ignore[attr-defined]
    assert RejectionCode.INVALID_NUMERIC_INPUT.value in codes(result)


def test_unmodelable_stress_blocks_the_margin_model_directly(
    instrument: InstrumentSpec,
) -> None:
    """Defence in depth: the model itself refuses a stress it cannot evaluate."""
    model = MarginModel(instrument)
    assessment = model.assess(
        direction=Direction.LONG,
        quantity=0.001,
        entry_price=82_500.0,
        wallet_balance=82.5,
        market_price=82_500.0,
        funding_owed_usdt=0.0,
        stress_scenarios=(StressScenario(name="nan_move", adverse_move_pct=float("nan")),),
    )
    assert assessment.status is LiquidationStatus.LIQUIDATION_RISK_UNKNOWN
    assert RejectionCode.LIQUIDATION_RISK_UNKNOWN in assessment.reasons


# --------------------------------------------------------------------------
# DEF-048V-02 — hostile numbers may never crash the engine
# --------------------------------------------------------------------------


def test_hostile_input_matrix_never_raises(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """Whatever is fed in, ``decide`` returns a decision — never an exception."""
    from trading_bot.risk.futures import PortfolioState

    scenarios: list[dict[str, object]] = []
    for hostile in HOSTILE:
        for field in (
            "entry_price",
            "stop_price",
            "mark_price",
            "requested_notional",
            "requested_leverage",
            "horizon_minutes",
        ):
            scenarios.append({"proposal": make_proposal(market_payload, **{field: hostile})})
        for field in ("equity", "free_margin", "reserved_margin", "drawdown_pct", "daily_pnl"):
            scenarios.append({"snapshot": make_snapshot(**{field: hostile})})
        scenarios.append({"market": {**market_payload, "spread_bps": hostile}})
        scenarios.append(
            {
                "stress": (
                    StressScenario(name="hostile", adverse_move_pct=hostile),
                    StressScenario(
                        name="hostile_funding", adverse_move_pct=0.02, funding_rate=hostile
                    ),
                )
            }
        )
        scenarios.append(
            {
                "market": {
                    **market_payload,
                    "depth": {"bids": [[float("nan"), 1.0]], "asks": [[float("nan"), 1.0]]},
                }
            }
        )
    scenarios.append(
        {
            "snapshot": make_snapshot(
                positions=(
                    PortfolioState(
                        instrument_id="X",
                        asset="ETH",
                        direction=Direction.LONG,
                        quantity=float("nan"),
                        entry_price=3_000.0,
                        notional=float("nan"),
                        reserved_margin=float("nan"),
                    ),
                )
            )
        }
    )
    for fields in scenarios:
        result = run(
            instrument=instrument,
            market=fields.get("market", market_payload),  # type: ignore[arg-type]
            funding_observations=funding_observations,
            proposal=fields.get("proposal"),  # type: ignore[arg-type]
            snapshot=fields.get("snapshot"),  # type: ignore[arg-type]
            stress=fields.get("stress", ()),  # type: ignore[arg-type]
        )
        decision = result.decision  # type: ignore[attr-defined]
        assert decision.order_authorised is False
        if not decision.approved:
            assert decision.rejection_reasons, fields


def test_liquidation_respects_the_maintenance_floor(instrument: InstrumentSpec) -> None:
    """DEF-048V-08: the closed form must not extrapolate maintenance below zero.

    Found by the numeric-root cross-check at the deepest bracket: the linear
    solve returned a non-positive price there, which understated the liquidation
    price for a long (i.e. overstated the buffer). The two independent methods
    must agree once the zero floor of ``max(notional*rate - cum, 0)`` is honoured.
    """
    from trading_bot.risk.futures.margin import MarginModel
    from trading_bot.risk.futures_falsification import independent_liquidation_price

    model = MarginModel(instrument)
    entry = 82_500.0
    notional = 999_999.99
    quantity = notional / entry
    bracket = instrument.bracket_for(notional * 1.0)
    safety = notional * 0.0005
    builder_price = model.liquidation_price(
        direction=Direction.LONG,
        quantity=quantity,
        entry_price=entry,
        wallet_balance=notional,  # 1x isolated
        bracket_rate=bracket.maintenance_margin_rate,
        cum_maintenance_amount=bracket.cum_maintenance_amount,
        adverse_terms_usdt=safety,
    )
    independent_price = independent_liquidation_price(
        direction="LONG",
        quantity=quantity,
        entry=entry,
        wallet_balance=notional,
        bracket_rate=bracket.maintenance_margin_rate,
        cum_maintenance=bracket.cum_maintenance_amount,
        adverse_terms=safety,
    )
    assert builder_price is not None and independent_price is not None
    assert builder_price == pytest.approx(independent_price, abs=1e-6)
    # The floored branch gives a strictly positive price here; the old code said 0.0.
    assert builder_price > 0.0


# --------------------------------------------------------------------------
# DEF-048V-03/04/05 — the ledger must not double-count or absorb NaN
# --------------------------------------------------------------------------


def test_repeated_decision_id_is_idempotent(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """A retry of the SAME decision must not reserve the margin twice."""
    ledger = MarginLedger(equity=EQUITY)
    proposal = make_proposal(market_payload, decision_id="retry-1")
    first = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=proposal,
        ledger=ledger,
    )
    reserved_once = ledger.reserved
    second = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=proposal,
        ledger=ledger,
    )
    assert first.decision.approved and second.decision.approved  # type: ignore[attr-defined]
    assert ledger.reserved == pytest.approx(reserved_once, abs=1e-12)
    assert ledger.free == pytest.approx(EQUITY - reserved_once, abs=1e-9)
    # A LARGER amount for the same decision id is a conflict, not a top-up.
    ok, granted, reason = ledger.try_reserve(
        reserved_once * 2, decision_id="retry-1", collateral_group="ISOLATED:X"
    )
    assert not ok and granted == 0.0
    assert reason is RejectionCode.SHARED_COLLATERAL_CONFLICT
    # Releasing the decision frees its margin exactly once.
    assert ledger.release("retry-1") == pytest.approx(reserved_once, abs=1e-12)
    assert ledger.reserved == 0.0


def test_aggregate_margin_utilization_holds_under_concurrency(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
) -> None:
    """The declared utilisation ceiling is aggregate, not per-snapshot."""
    policy = make_policy(max_margin_utilization_pct=0.5)
    ledger = MarginLedger(equity=EQUITY)
    engine = FuturesRiskEngine(spec=instrument, policy=policy, ledger=ledger)
    approved: list[float] = []
    refusals: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            outcome = engine.decide(
                ScenarioRequest(
                    proposal=make_proposal(
                        market_payload,
                        decision_id=f"conc-{index}",
                        requested_notional=400.0,
                        requested_leverage=1.0,
                    ),
                    snapshot=make_snapshot(),
                    market=market_payload,
                    funding_observations=funding_observations,
                )
            )
            with lock:
                if outcome.decision.approved:
                    approved.append(outcome.decision.required_margin)
                else:
                    refusals.append(",".join(r.value for r in outcome.decision.rejection_reasons))
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    ceiling = policy.max_margin_utilization_pct * EQUITY
    assert sum(approved) <= ceiling + 1e-9
    assert ledger.reserved <= ceiling + 1e-9
    assert abs(ledger.reserved - sum(approved)) < 1e-9
    assert refusals, "the ceiling must refuse at least one of the eight requests"
    assert all(RejectionCode.MARGIN_UTILIZATION_LIMIT.value in row for row in refusals)


def test_ledger_refuses_non_finite_amounts() -> None:
    ledger = MarginLedger(equity=EQUITY)
    for hostile in HOSTILE:
        ok, granted, reason = ledger.try_reserve(hostile, decision_id=f"nan-{hostile}")
        assert not ok and granted == 0.0
        assert reason is RejectionCode.INVALID_NUMERIC_INPUT
    assert math.isfinite(ledger.reserved)
    assert ledger.reserved == 0.0
    assert ledger.free == EQUITY


# --------------------------------------------------------------------------
# fail-safe boundary: an engine error is a BINDING veto, never a crash
# --------------------------------------------------------------------------


def _error_review_request():
    review = safe_review(lambda: (_ for _ in ()).throw(RuntimeError("engine exploded")))
    request = build_decision_request_from_review(
        review=review,
        stop_price=82_087.5,
        cost_scenario_id="falsify-error",
        size_usd_hint=82.5,
        strategy_id="rfc048_offline_probe",
        run_id="run-falsify",
        decision_id="dec-falsify",
        asset="BTC",
        symbol="BTCUSDT",
        direction="LONG",
        entry_reference=82_500.0,
        expected_gross_edge_bps=40.0,
        expected_cost_bps=12.0,
        market_time_ms=1_791_582_761_730,
        holistic_time_ms=1_791_582_762_730,
        admission_status=AdmissionStatus.RESEARCH_REQUIRED,
        admitted_for_paper=False,
    )
    return review, request


def test_engine_error_becomes_a_binding_veto() -> None:
    review, request = _error_review_request()
    assert review.verdict.value == "VETO"
    assert review.advisory is False
    assert review.evaluated is False
    assert review.rule == "futures_engine_fail_safe"
    result = DecisionEngine().decide(request)
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "RISK_VETO"
    assert result.order_authorised is False


def test_engine_error_cannot_be_laundered_into_an_order() -> None:
    """Even an admitted, positive-edge packet is refused on an engine error."""
    _, request = _error_review_request()
    admitting = replace(
        request,
        admission=replace(
            request.admission,
            status=AdmissionStatus.PAPER_CANDIDATE,
            admitted_for_paper=True,
            edge_evidence=EdgeEvidence(
                source_doc="data/rfc048/RFC048_SYNTHETIC_EDGE.md",
                metric="synthetic_probe_edge_bps",
                value_bps=40.0,
                knowledge="ASSUMPTION",
                sample_trades=0,
                evidence_class="ASSUMPTION",
                status="NOT_A_TRADING_SIGNAL",
            ),
        ),
    )

    def explode():
        raise ValueError("bad")

    result = run_engine_through_runtime(
        evaluate=explode,
        build=lambda review: replace(admitting, risk=review),
    )
    assert result.mode is DecisionMode.NO_TRADE
    assert result.classification == "RISK_VETO"
    assert result.order_authorised is False
    assert result.notional_usdt is None


# --------------------------------------------------------------------------
# properties — the general form of the invariants
# --------------------------------------------------------------------------


def test_round_quantity_down_refuses_a_quotient_that_overflows(
    instrument: InstrumentSpec,
) -> None:
    """A finite size with a tiny entry can give an infinite quotient.

    The property suite found this as an ``OverflowError`` from ``int(inf)`` in
    the risk plane (entry 2.1e-302, quantity about 4.7e307). The documented
    contract is that an unrepresentable size becomes a refusal, never a crash.
    """
    assert instrument.round_quantity_down(1e308) == 0.0
    step = instrument.quantity_step
    assert instrument.round_quantity_down(step * 3) == pytest.approx(step * 3)


@hyp_settings(max_examples=1000, deadline=None)
@given(
    entry=st.one_of(
        st.floats(allow_nan=True, allow_infinity=True),
        st.floats(min_value=1e-6, max_value=1e9, allow_nan=False, allow_infinity=False),
    ),
    stop_fraction=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    notional=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    leverage=st.floats(min_value=-100.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    horizon=st.floats(min_value=-100.0, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    equity=st.floats(min_value=-1e4, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_property_engine_never_raises_and_never_approves_unbounded(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    entry: float,
    stop_fraction: float,
    notional: float,
    leverage: float,
    horizon: float,
    equity: float,
) -> None:
    proposal = make_proposal(
        market_payload,
        entry_price=entry,
        stop_price=entry * (1.0 - stop_fraction),
        requested_notional=notional,
        requested_leverage=leverage,
        horizon_minutes=horizon,
    )
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=proposal,
        snapshot=make_snapshot(equity=equity, free_margin=max(equity, 0.0)),
    )
    decision = result.decision  # type: ignore[attr-defined]
    assert decision.order_authorised is False
    if decision.approved:
        assert math.isfinite(decision.modeled_worst_loss)
        assert decision.modeled_worst_loss <= decision.risk_budget + 1e-9
        assert math.isfinite(decision.required_margin)
        assert decision.required_margin > 0
        assert decision.approved_notional >= instrument.minimum_notional - 1e-9
        assert (
            decision.approved_notional
            <= max(decision.requested_notional, instrument.minimum_notional) + 1e-6
        )
        assert decision.liquidation_buffer_bps is not None
        assert decision.liquidation_buffer_bps >= make_policy().min_liquidation_buffer_bps - 1e-9
    else:
        assert decision.rejection_reasons
        assert decision.approved_notional == 0.0


@hyp_settings(max_examples=1000, deadline=None)
@given(
    spread=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    bump=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    risk_budget_pct=st.floats(
        min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False
    ),
)
def test_property_higher_cost_never_increases_the_approved_size(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    spread: float,
    bump: float,
    risk_budget_pct: float,
) -> None:
    policy = make_policy(risk_budget_pct=risk_budget_pct)
    cheap_market = {**market_payload, "spread_bps": spread}
    dear_market = {**market_payload, "spread_bps": spread + bump}
    cheap = run(
        instrument=instrument,
        market=cheap_market,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, requested_notional=5_000.0),
        policy=policy,
    )
    dear = run(
        instrument=instrument,
        market=dear_market,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, requested_notional=5_000.0),
        policy=policy,
    )
    assert (
        dear.decision.approved_notional  # type: ignore[attr-defined]
        <= cheap.decision.approved_notional + 1e-9  # type: ignore[attr-defined]
    )


@hyp_settings(max_examples=1000, deadline=None)
@given(
    stop_bps=st.floats(min_value=1.0, max_value=2_000.0, allow_nan=False, allow_infinity=False),
    risk_budget_pct=st.floats(
        min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False
    ),
    direction=st.sampled_from([Direction.LONG, Direction.SHORT]),
)
def test_property_approved_risk_stays_inside_the_declared_budget(
    instrument: InstrumentSpec,
    market_payload: dict[str, object],
    funding_observations: list[dict[str, object]],
    stop_bps: float,
    risk_budget_pct: float,
    direction: Direction,
) -> None:
    mark = float(market_payload["mark_price"])  # type: ignore[arg-type]
    offset = mark * stop_bps / 10_000.0
    proposal = make_proposal(
        market_payload,
        direction=direction,
        stop_price=mark - offset if direction is Direction.LONG else mark + offset,
        requested_notional=5_000.0,
        requested_leverage=5.0,
    )
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=proposal,
        policy=make_policy(risk_budget_pct=risk_budget_pct, max_gross_exposure_pct=5.0),
    )
    decision = result.decision  # type: ignore[attr-defined]
    assert decision.order_authorised is False
    assert decision.risk_budget == pytest.approx(EQUITY * risk_budget_pct, rel=1e-12)
    if decision.approved:
        assert decision.modeled_worst_loss <= decision.risk_budget + 1e-9
        assert decision.effective_leverage <= max(make_policy().max_leverage, 1e-9) + 1e-12
