"""RFC-048 §12 — adversarial tests and invariants for the futures risk engine.

Every case named in §12 of the RFC has a dedicated test below, addressed by the
numbering used in that section (case 1 … case 24). On top of that the file pins
four invariants that must hold for ANY input, plus the concurrency requirement
("los límites deben mantenerse incluso bajo concurrencia").

The tests drive the engine through its public surface
(``FuturesRiskEngine.decide``) with real fixtures derived from the venue payloads
in ``data/rfc048`` — no synthetic bracket tables and no mocked arithmetic.
"""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from trading_bot.risk.futures import (
    ContractType,
    Direction,
    InstrumentSpec,
    MaintenanceBracket,
    MarginLedger,
    PortfolioSnapshot,
    PositionMode,
    RejectionCode,
    RiskDecisionCode,
    RiskProposal,
    ScenarioRequest,
    load_instrument_registry,
)
from trading_bot.risk.futures.engine import FuturesRiskEngine, FuturesRiskPolicy
from trading_bot.risk.futures.margin import MarginModel, StressScenario

DATA = Path(__file__).resolve().parents[3] / "data" / "rfc048"

pytestmark = pytest.mark.unit

EQUITY = 200.0


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
    """Offline experimental policy; tests widen/close limits explicitly."""
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
        snapshot_id="SNAP-TEST",
        timestamp_ms=1_791_582_761_730,
        equity=EQUITY,
        free_margin=EQUITY,
        reserved_margin=0.0,
    )
    return replace(base, **overrides)


def make_proposal(market: dict[str, object], **overrides: object) -> RiskProposal:
    mark = float(market["mark_price"])  # type: ignore[arg-type]
    base = RiskProposal(
        run_id="run-rfc048",
        decision_id="dec-rfc048",
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
    engine = FuturesRiskEngine(
        spec=instrument, policy=policy or make_policy(), ledger=ledger
    )
    request = ScenarioRequest(
        proposal=proposal or make_proposal(market),
        snapshot=snapshot or make_snapshot(),
        market=market,
        funding_observations=funding_observations,
        funding_source_hash="funding-fixture",
        stress_scenarios=stress,
    )
    return engine.decide(request)


def codes(result: object) -> list[str]:
    return [r.value for r in result.decision.rejection_reasons]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# §12 case by case
# --------------------------------------------------------------------------


def test_case_01_insufficient_capital(instrument, market_payload, funding_observations) -> None:
    """1. Capital insuficiente — one hundredth of a USDT cannot fund a contract."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        snapshot=make_snapshot(equity=0.01, free_margin=0.01),
    )
    assert result.decision.decision in {RiskDecisionCode.NO_TRADE, RiskDecisionCode.RISK_VETO}
    assert result.decision.approved_notional == 0.0
    assert result.decision.quantity == 0.0


def test_case_02_insufficient_margin(instrument, market_payload, funding_observations) -> None:
    """2. Margen insuficiente — margin already reserved elsewhere."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        snapshot=make_snapshot(free_margin=0.0, reserved_margin=EQUITY),
    )
    assert result.decision.decision is RiskDecisionCode.NO_TRADE
    assert {"INSUFFICIENT_MARGIN", "EXPOSURE_LIMIT"} & set(codes(result))


def test_case_03_stop_too_close(instrument, market_payload, funding_observations) -> None:
    """3. Stop demasiado cercano — a stop one basis point away is refused."""
    market = dict(market_payload)
    mark = float(market["mark_price"])
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, stop_price=mark * (1 - 1e-6)),
    )
    assert RejectionCode.STOP_TOO_CLOSE.value in codes(result)


def test_case_04_stop_absent(instrument, market_payload, funding_observations) -> None:
    """4. Stop ausente — no invalidation price, no position."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, stop_price=None),
    )
    assert RejectionCode.STOP_MISSING.value in codes(result)
    assert result.decision.decision is RiskDecisionCode.RISK_VETO


def test_case_05_liquidation_before_stop(instrument, market_payload, funding_observations) -> None:
    """5. Liquidación anterior al stop — a 30 % stop at 5x is unreachable."""
    market = dict(market_payload)
    mark = float(market["mark_price"])
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, stop_price=mark * 0.70, requested_notional=400.0),
        policy=make_policy(risk_budget_pct=0.5),
    )
    assert result.decision.decision is RiskDecisionCode.RISK_VETO
    assert RejectionCode.LIQUIDATION_BEFORE_STOP.value in codes(result)


def test_case_06_severe_adverse_gap(instrument, market_payload, funding_observations) -> None:
    """6. Gap contrario severo — a gap past liquidation voids the stop."""
    gap = StressScenario(name="hard_gap_40pct", adverse_move_pct=0.40, bracket_shift=True)
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        stress=(gap,),
    )
    assert result.decision.decision is RiskDecisionCode.RISK_VETO
    assert RejectionCode.GAP_BEYOND_STOP.value in codes(result)
    assert RejectionCode.PARTIAL_LIQUIDATION_UNSUPPORTED.value in codes(result)


def test_case_07_adverse_funding_accumulated(instrument, market_payload, funding_observations) -> None:
    """7. Funding adverso acumulado — funding is charged, and it can kill the trade."""
    market = dict(market_payload)
    long_horizon = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, horizon_minutes=24.0 * 60.0 * 3),
    )
    # Either the funding charge is visible in the accounting, or the position was
    # refused because of it: neither outcome may be "free funding".
    details = long_horizon.detail  # type: ignore[attr-defined]
    if long_horizon.decision.decision in {  # type: ignore[attr-defined]
        RiskDecisionCode.APPROVE_SIMULATION,
        RiskDecisionCode.REDUCE_SIMULATED_SIZE,
    }:
        assert details["costs"]["funding_usdt"] > 0.0
        assert details["funding_context"]["settlements_in_horizon"] > 0
    else:
        assert {
            RejectionCode.RISK_BUDGET_EXCEEDED.value,
            RejectionCode.FEES_EXCEED_HORIZON_EDGE.value,
            RejectionCode.FUNDING_UNKNOWN.value,
            RejectionCode.COST_UNKNOWN.value,
        } & set(codes(long_horizon))


def test_case_08_maintenance_bracket_change(instrument) -> None:
    """8. Cambio de maintenance bracket — the worst touched bracket is charged.

    Driven at the margin-model level because the risk budget keeps a real
    position orders of magnitude below the 300 000 bracket boundary: the rule
    under test is "when the notional can cross a bracket, charge the worse one".
    """
    model = MarginModel(instrument)
    entry_notional = 297_000.0  # bracket 1, 3 000 below the cap
    stress_notional = entry_notional * 1.05  # bracket 2 on a 5 % adverse move

    entry_bracket = instrument.bracket_for(entry_notional)
    worst = model.spec.worst_bracket_for(entry_notional, stress_notional)
    assert entry_bracket.bracket_seq == 1
    assert worst.bracket_seq == 2
    assert worst.maintenance_margin_rate > entry_bracket.maintenance_margin_rate
    # the charged maintenance margin really is the worse of the two
    naive = instrument.bracket_for(stress_notional).maintenance_margin(stress_notional)
    assert worst.maintenance_margin(stress_notional) >= naive - 1e-9

    # A short of that size, on a 5 % adverse move, must report the shift.
    entry = 82_500.0
    result = model.assess(
        direction=Direction.SHORT,
        quantity=entry_notional / entry,
        entry_price=entry,
        wallet_balance=entry_notional,  # 1x, isolated
        market_price=entry,
        stress_scenarios=(StressScenario(name="bracket_shift", adverse_move_pct=0.05),),
    )
    assert result.known
    assert result.bracket_shifted is True
    assert any(row["bracket_seq"] >= 2 for row in result.stress_path)


def test_case_08b_engine_reports_bracket_shift_rows(
    instrument, market_payload, funding_observations
) -> None:
    """8b. The engine surfaces the same bracket evidence in its decision detail."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        stress=(
            StressScenario(
                name="bracket_probe",
                adverse_move_pct=0.04,
                bracket_shift=True,
            ),
        ),
    )
    detail = result.detail  # type: ignore[attr-defined]
    liquidation = detail["liquidation"]
    assert liquidation["status"] == "LIQUIDATION_RISK_KNOWN"
    assert liquidation["stress_path"]
    for row in liquidation["stress_path"]:
        assert row["bracket_seq"] >= 1
        assert row["liquidation_price"] is not None


def test_case_09_commissions_exceed_profit(instrument, market_payload, funding_observations) -> None:
    """9. Comisiones superiores al beneficio — a one-cent edge does not survive."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, expected_gross_edge_usdt=0.01),
    )
    assert result.decision.decision is RiskDecisionCode.NO_TRADE
    assert RejectionCode.FEES_EXCEED_HORIZON_EDGE.value in codes(result)


def test_case_10_below_minimum_notional(instrument, market_payload, funding_observations) -> None:
    """10. Orden inferior al mínimo permitido — the risk budget cannot buy a lot."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        snapshot=make_snapshot(equity=5.0, free_margin=5.0),
        proposal=make_proposal(market_payload, requested_notional=49.0),
    )
    assert result.decision.approved_notional == 0.0
    assert {
        RejectionCode.BELOW_MIN_NOTIONAL.value,
        RejectionCode.RISK_BUDGET_EXCEEDED.value,
    } & set(codes(result))


def test_case_11_invalid_quantity_step(instrument, market_payload, funding_observations) -> None:
    """11. Quantity step inválido — a zero step is an unsupported instrument."""
    broken = replace(instrument, quantity_step=0.0)
    result = run(
        instrument=broken,
        market=market_payload,
        funding_observations=funding_observations,
    )
    assert result.decision.decision is RiskDecisionCode.UNSUPPORTED_INSTRUMENT
    assert result.decision.approved_notional == 0.0


def test_case_12_stale_data(instrument, market_payload, funding_observations) -> None:
    """12. Datos stale — data older than the policy window is refused."""
    market = dict(market_payload)
    stale = make_proposal(
        market,
        data_timestamp_ms=int(market["data_timestamp_ms"]),
        decision_timestamp_ms=int(market["data_timestamp_ms"]) + 10 * 60 * 1000,
    )
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=stale,
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID
    assert RejectionCode.STALE_DATA.value in codes(result)


def test_case_13_future_timestamp(instrument, market_payload, funding_observations) -> None:
    """13. Timestamp futuro — data timestamped after the decision."""
    market = dict(market_payload)
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(
            market,
            data_timestamp_ms=int(market["data_timestamp_ms"]) + 5_000,
            decision_timestamp_ms=int(market["data_timestamp_ms"]) + 1_000,
        ),
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID
    assert RejectionCode.FUTURE_TIMESTAMP.value in codes(result)


def test_case_14_mark_price_absent(instrument, market_payload, funding_observations) -> None:
    """14. Mark price ausente — no mark, no liquidation model, no trade."""
    market = {"spread_bps": market_payload["spread_bps"], "depth": market_payload["depth"]}
    mark = float(market_payload["mark_price"])
    proposal = make_proposal(market_payload, mark_price=None)
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=proposal,
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID
    assert RejectionCode.MISSING_MARK_PRICE.value in codes(result)
    assert mark > 0  # the fixture really did carry a price; it was withheld


def test_case_15_incomplete_margin_model(instrument, market_payload, funding_observations) -> None:
    """15. Modelo de margen incompleto — an unknown liquidation fee is fatal."""
    # (a) the live path: the margin model reports LIQUIDATION_RISK_UNKNOWN
    no_fee = replace(instrument, liquidation_fee_rate=None)
    assessment = MarginModel(no_fee).assess(
        direction=Direction.LONG,
        quantity=0.001,
        entry_price=82_500.0,
        wallet_balance=16.5,
        market_price=81_000.0,
        stress_scenarios=(StressScenario(name="x", adverse_move_pct=0.01),),
    )
    assert assessment.status.value == "LIQUIDATION_RISK_UNKNOWN"
    assert RejectionCode.LIQUIDATION_RISK_UNKNOWN.value in [r.value for r in assessment.reasons]
    # (b) through the engine: the cost model reports the unknown component
    result = run(
        instrument=no_fee,
        market=market_payload,
        funding_observations=funding_observations,
    )
    assert result.decision.decision is RiskDecisionCode.NO_TRADE
    assert "liquidation_fee" in result.detail["costs"]["unknown_components"]  # type: ignore[attr-defined]


def test_case_16_correlated_positions(instrument, market_payload, funding_observations) -> None:
    """16. Posiciones correlacionadas — a shared correlation key is refused."""
    from trading_bot.risk.futures import PortfolioState

    existing = PortfolioState(
        instrument_id="BINANCE_USDM_ETHUSDT_PERP",
        asset="ETH",
        direction=Direction.LONG,
        quantity=1.0,
        entry_price=3_000.0,
        notional=3_000.0,
        reserved_margin=600.0,
        correlation_key="crypto_beta",
        strategy_id="sibling",
    )
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, correlation_key="crypto_beta"),
        snapshot=make_snapshot(
            equity=5_000.0,
            free_margin=4_400.0,
            reserved_margin=600.0,
            positions=(existing,),
        ),
    )
    assert RejectionCode.CORRELATED_POSITIONS.value in codes(result)


def test_case_17_simultaneous_decisions_same_collateral(
    instrument, market_payload, funding_observations
) -> None:
    """17. Dos decisiones simultáneas sobre el mismo collateral — atomic reservation."""
    ledger = MarginLedger(equity=EQUITY)
    engine = FuturesRiskEngine(spec=instrument, policy=make_policy(), ledger=ledger)
    approved: list[float] = []
    errors: list[BaseException] = []

    def attempt(index: int) -> None:
        try:
            request = ScenarioRequest(
                proposal=make_proposal(
                    market_payload,
                    decision_id=f"dec-{index}",
                    requested_leverage=5.0,
                    requested_notional=200.0,
                ),
                snapshot=make_snapshot(),
                market=market_payload,
                funding_observations=funding_observations,
            )
            decision = engine.decide(request).decision
            if decision.approved and decision.required_margin > 0:
                approved.append(decision.required_margin)
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert sum(approved) <= EQUITY + 1e-9
    assert ledger.reserved <= EQUITY + 1e-9
    assert abs(ledger.reserved - sum(approved)) < 1e-9


def test_case_18_agent_requests_excessive_leverage(
    instrument, market_payload, funding_observations
) -> None:
    """18. LLM solicitando leverage excesivo — the engine caps, it never obeys."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, requested_leverage=500.0),
    )
    decision = result.decision
    assert decision.effective_leverage <= make_policy().max_leverage
    assert decision.effective_leverage < decision.requested_leverage
    assert decision.approved_notional <= decision.requested_notional
    if decision.approved:
        assert decision.modeled_worst_loss <= decision.risk_budget + 1e-9


def test_case_19_short_with_unbounded_adverse_move(
    instrument, market_payload, funding_observations
) -> None:
    """19. Short con movimiento adverso ilimitado — a short's loss is modelled."""
    market = dict(market_payload)
    mark = float(market["mark_price"])
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(
            market,
            direction=Direction.SHORT,
            stop_price=mark * 1.005,
        ),
        stress=(StressScenario(name="short_squeeze_40pct", adverse_move_pct=0.40),),
    )
    assert result.decision.decision is RiskDecisionCode.RISK_VETO
    assert result.decision.approved_notional == 0.0
    assert RejectionCode.GAP_BEYOND_STOP.value in codes(result)


def test_case_20_loss_above_planned_margin(instrument, funding_observations) -> None:
    """20. Pérdida superior al margen previsto — the loss may not exceed the margin."""
    market = {
        "mark_price": 82_500.0,
        "spread_bps": 0.012,
        "depth": {"bids": [[82_500.0, 50.0]], "asks": [[82_500.0, 50.0]]},
        "data_timestamp_ms": 1_791_582_761_730,
    }
    # A gap reserve larger than the isolated margin makes the modelled worst loss
    # unfundable: the engine must refuse instead of assuming the margin covers it.
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, stop_price=82_500.0 * 0.995),
        policy=make_policy(risk_budget_pct=0.6, gap_reserve_pct=0.25),
    )
    assert result.decision.decision is RiskDecisionCode.RISK_VETO
    assert RejectionCode.LOSS_ABOVE_MARGIN.value in codes(result)
    assert result.decision.approved_notional == 0.0


def test_case_21_attempt_to_reach_live_routes(
    instrument, market_payload, funding_observations
) -> None:
    """21. Intento de acceder a rutas live — refused outright, never silently."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=funding_observations,
        proposal=make_proposal(market_payload, live_route_requested=True),
    )
    assert result.decision.decision is RiskDecisionCode.RISK_VETO
    assert codes(result) == [RejectionCode.LIVE_ROUTE_ATTEMPTED.value]
    assert result.decision.order_authorised is False


def test_case_22_partial_liquidation_not_implemented(instrument, market_payload) -> None:
    """22. Liquidación parcial no implementada — the engine says so when it bites."""
    result = run(
        instrument=instrument,
        market=market_payload,
        funding_observations=[],
        stress=(StressScenario(name="gap_50pct", adverse_move_pct=0.50),),
    )
    assert RejectionCode.PARTIAL_LIQUIDATION_UNSUPPORTED.value in codes(result)


def test_case_23_funding_unknown(instrument, market_payload) -> None:
    """23. Funding desconocido — a settled horizon with no history is not free."""
    market = dict(market_payload)
    result = run(
        instrument=instrument,
        market=market,
        funding_observations=[],
        proposal=make_proposal(market, horizon_minutes=24.0 * 60.0),
    )
    assert result.decision.decision is RiskDecisionCode.NO_TRADE
    assert {
        RejectionCode.FUNDING_UNKNOWN.value,
        RejectionCode.COST_UNKNOWN.value,
    } & set(codes(result))


def test_case_24_product_not_available(instrument, market_payload, funding_observations) -> None:
    """24. Venue o producto no disponible legalmente — and unsupported types."""
    blocked = replace(instrument, regulatory_eligibility_status="PRODUCT_NOT_AVAILABLE")
    result = run(
        instrument=blocked,
        market=market_payload,
        funding_observations=funding_observations,
    )
    assert result.decision.decision is RiskDecisionCode.DATA_INVALID
    assert RejectionCode.VENUE_OR_PRODUCT_NOT_ELIGIBLE.value in codes(result)

    quarterly = load_instrument_registry(DATA / "INSTRUMENTS.json").get(
        "BINANCE_USDM_BTCUSDT_261225"
    )
    unsupported = run(
        instrument=quarterly,
        market=market_payload,
        funding_observations=funding_observations,
    )
    assert unsupported.decision.decision is RiskDecisionCode.UNSUPPORTED_INSTRUMENT
    assert RejectionCode.CONTRACT_TYPE_NOT_IMPLEMENTED.value in codes(unsupported)


def test_inverse_perpetual_is_refused_by_name() -> None:
    """A coin-margined contract can never be priced with linear algebra."""
    inverse = load_instrument_registry(DATA / "INSTRUMENTS.json").get(
        "BINANCE_COINM_BTCUSD_PERP"
    )
    assert inverse.contract_type is ContractType.INVERSE_PERPETUAL
    with pytest.raises(Exception) as excinfo:
        inverse.ensure_usable(PositionMode.ISOLATED)
    assert "INSTRUMENT_NOT_SUPPORTED" in str(excinfo.value)
    assert "INVERSE_PERPETUAL" in str(excinfo.value)


def test_cross_margin_is_refused(instrument) -> None:
    """Cross margin is declared, then refused: its dependencies are unvalidated."""
    with pytest.raises(Exception) as excinfo:
        instrument.ensure_usable(PositionMode.CROSS)
    assert "CROSS" in str(excinfo.value)


# --------------------------------------------------------------------------
# invariants
# --------------------------------------------------------------------------


def test_rounding_never_increases_risk(instrument, market_payload, funding_observations) -> None:
    """§5 — lot rounding can only reduce: the modelled loss never exceeds budget."""
    for budget in (0.005, 0.01, 0.02):
        for stop_bps in (5.0, 12.0, 30.0):
            market = dict(market_payload)
            mark = float(market["mark_price"])
            result = run(
                instrument=instrument,
                market=market,
                funding_observations=funding_observations,
                proposal=make_proposal(market, stop_price=mark * (1 - stop_bps / 10_000.0)),
                policy=make_policy(risk_budget_pct=budget),
            )
            decision = result.decision
            if decision.approved:
                step = instrument.quantity_step
                assert abs(decision.quantity / step - round(decision.quantity / step)) < 1e-6
                assert decision.modeled_worst_loss <= decision.risk_budget + 1e-9


@hyp_settings(max_examples=40, deadline=None)
@given(
    slippage_bps=st.floats(min_value=0.0, max_value=25.0),
    gap_pct=st.floats(min_value=0.0, max_value=0.02),
)
def test_rising_adverse_cost_never_increases_size(slippage_bps: float, gap_pct: float) -> None:
    """§5 — a costlier, gappier assumption can never approve a bigger position."""
    instrument = load_instrument_registry(DATA / "INSTRUMENTS.json").get(
        "BINANCE_USDM_BTCUSDT_PERP"
    )
    market = json.loads((DATA / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))
    mark = float(market["mark_price"])
    funding = json.loads((DATA / "FUNDING_HISTORY.json").read_text(encoding="utf-8"))
    payload = {
        "mark_price": mark,
        "spread_bps": market["spread_bps"],
        "depth": {"bids": market["depth_bids"], "asks": market["depth_asks"]},
        "data_timestamp_ms": market["data_timestamp_ms"],
    }

    def approved_notional(policy: FuturesRiskPolicy) -> float:
        engine = FuturesRiskEngine(spec=instrument, policy=policy)
        request = ScenarioRequest(
            proposal=make_proposal(payload),
            snapshot=make_snapshot(),
            market=payload,
            funding_observations=list(funding["observations"]),
        )
        return engine.decide(request).decision.approved_notional

    tight = approved_notional(make_policy(slippage_bps=slippage_bps, gap_reserve_pct=gap_pct))
    looser = approved_notional(
        make_policy(
            slippage_bps=min(30.0, slippage_bps + 5.0),
            gap_reserve_pct=min(0.05, gap_pct + 0.005),
        )
    )
    assert looser <= tight + 1e-9


def test_reduced_size_never_increases_calculated_risk(
    instrument, market_payload, funding_observations
) -> None:
    """§12 — halving the request can never raise the modelled worst loss."""
    market = dict(market_payload)
    big = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, requested_notional=300.0),
    )
    small = run(
        instrument=instrument,
        market=market,
        funding_observations=funding_observations,
        proposal=make_proposal(market, requested_notional=60.0),
    )
    assert small.decision.approved_notional <= big.decision.approved_notional + 1e-9
    assert small.decision.modeled_worst_loss <= big.decision.modeled_worst_loss + 1e-9


def test_effective_leverage_never_exceeds_any_limit(instrument) -> None:
    """§6 — the admissible leverage is the minimum of every applicable limit."""
    market = json.loads((DATA / "MARKET_SNAPSHOT.json").read_text(encoding="utf-8"))
    payload = {
        "mark_price": market["mark_price"],
        "spread_bps": market["spread_bps"],
        "depth": {"bids": market["depth_bids"], "asks": market["depth_asks"]},
        "data_timestamp_ms": market["data_timestamp_ms"],
    }
    funding = json.loads((DATA / "FUNDING_HISTORY.json").read_text(encoding="utf-8"))
    for policy_cap in (1.0, 2.0, 3.0, 5.0):
        for requested in (1.0, 3.0, 9.0, 100.0):
            result = run(
                instrument=instrument,
                market=payload,
                funding_observations=list(funding["observations"]),
                proposal=make_proposal(payload, requested_leverage=requested),
                policy=make_policy(max_leverage=policy_cap),
            )
            decision = result.decision
            assert decision.effective_leverage <= policy_cap + 1e-9
            assert decision.effective_leverage <= requested + 1e-9
            if decision.approved:
                venue = instrument.leverage_ceiling_for(decision.approved_notional)
                assert decision.effective_leverage <= float(venue) + 1e-9


def test_engine_never_authorises_an_order(instrument, market_payload, funding_observations) -> None:
    """§11 — every verdict is simulation-only, whatever the input."""
    for overrides in (
        {},
        {"requested_leverage": 250.0},
        {"requested_notional": 10.0},
        {"stop_price": None},
    ):
        result = run(
            instrument=instrument,
            market=market_payload,
            funding_observations=funding_observations,
            proposal=make_proposal(market_payload, **overrides),
        )
        assert result.decision.order_authorised is False
        assert result.decision.decision in set(RiskDecisionCode)


def test_maintenance_ladder_matches_venue_continuity(instrument) -> None:
    """The ladder is only usable because it is continuous — pin that property."""
    assert instrument.margin_ladder_complete
    brackets: list[MaintenanceBracket] = list(instrument.maintenance_margin_brackets)
    assert brackets[0].notional_floor == 0.0
    for lower, upper in itertools.pairwise(brackets):
        # The subtraction term exists exactly to make the ladder continuous:
        # both sides of a boundary must price the same maintenance margin.
        at_boundary_lower = lower.maintenance_margin(lower.notional_cap)
        at_boundary_upper = upper.maintenance_margin(upper.notional_floor)
        assert abs(at_boundary_lower - at_boundary_upper) <= 1e-6 * max(
            1.0, at_boundary_lower
        )
