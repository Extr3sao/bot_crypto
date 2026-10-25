"""RFC-030 — two-leg execution & accounting contract tests (§41/§42).

These tests are the RFC-030 acceptance surface. They exercise the *actual*
research/PAPER target (``trading_bot.research.pair``), not a parallel stand-in, so
``TEST_TARGET == RUNTIME_TARGET`` (§36).

Adversarial coverage (§42): long fills/short fails, short fills/long fails,
partial legs, borrow disappears, future-dated cost, beta exactly at / above /
below tolerance, leg imbalance, both-legs-partial, and accounting invariants.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.pair import (  # noqa: E402
    EXP_ARP_023_LONG_INSTRUMENT,
    EXP_ARP_023_SHORT_INSTRUMENT,
    CostKnowledge,
    FailurePolicy,
    FillConfig,
    InstrumentSubstitutionError,
    InstrumentType,
    LegInstrumentContract,
    PairAccountingError,
    PairCostModelV1,
    PairExecutionPlan,
    PairExecutionStatus,
    PairLedger,
    PairSimulator,
    PairTradeProposal,
    ShortLegCost,
    Side,
    beta_book,
    beta_gate,
    require_same_instrument,
    through_origin_beta,
)
from trading_bot.research.pair.beta import beta_diagnostic  # noqa: E402

COST_RT_BPS = 23.559016994374947
MS_PER_DAY = 86_400_000
DECISION = 1_600_000_000_000


def _proposal(long_notional: float = 500.0, short_notional: float = 500.0) -> PairTradeProposal:
    return PairTradeProposal(
        proposal_id="P1",
        strategy_id="H-MKTNEUTRAL-RELVAL-001",
        decision_time=DECISION,
        long_leg=EXP_ARP_023_LONG_INSTRUMENT,
        short_leg=EXP_ARP_023_SHORT_INSTRUMENT,
        long_target_notional=long_notional,
        short_target_notional=short_notional,
        expected_beta=0.0,
        beta_tolerance=0.10,
    )


def _plan(proposal: PairTradeProposal | None = None) -> PairExecutionPlan:
    return PairExecutionPlan(
        execution_id="E1",
        proposal=proposal or _proposal(),
        execution_sequence=("LONG", "SHORT"),
        long_target_qty=5.0,
        short_target_qty=5.0,
        expected_fees=0.0,
        expected_spread=0.0,
        expected_slippage=0.0,
        borrow_requirement=500.0,
        funding_assumption=0.0,
        maximum_allowed_leg_imbalance=5.0,
        timeout_ms=60_000,
        failure_policy=FailurePolicy.ABORT_PAIR,
    )


def _short_cost(
    borrow_rate: float | None = 5.0,
    *,
    source_timestamp: int = DECISION - MS_PER_DAY,
    availability_timestamp: int = DECISION - MS_PER_DAY,
) -> ShortLegCost:
    return ShortLegCost(
        instrument_id=EXP_ARP_023_SHORT_INSTRUMENT.instrument_id,
        borrow_rate=borrow_rate,
        fees=0.5,
        spread_cost=0.1,
        slippage_cost=0.05,
        source="TEST",
        source_timestamp=source_timestamp,
        availability_timestamp=availability_timestamp,
    )


def _model() -> PairCostModelV1:
    return PairCostModelV1(long_cost_bps=COST_RT_BPS)


def _sim() -> PairSimulator:
    return PairSimulator(_model())


# --------------------------------------------------------------------- §7/§8


def test_instrument_contract_has_all_required_fields() -> None:
    d = EXP_ARP_023_LONG_INSTRUMENT.as_dict()
    for field in (
        "instrument_id",
        "asset",
        "venue",
        "instrument_type",
        "side",
        "quote_currency",
        "contract_multiplier",
        "price_increment",
        "quantity_increment",
        "minimum_notional",
        "shortable",
        "borrow_required",
        "funding_applicable",
        "basis_applicable",
        "data_source",
        "cost_source",
    ):
        assert field in d


def test_instrument_substitution_is_refused() -> None:
    perp = LegInstrumentContract(
        instrument_id="BINANCE-PERP-USDT-SHORT",
        asset=EXP_ARP_023_SHORT_INSTRUMENT.asset,
        venue="BINANCE",
        instrument_type=InstrumentType.PERPETUAL,
        side=Side.SHORT,
        quote_currency="USDT",
        contract_multiplier=1.0,
        price_increment=1e-8,
        quantity_increment=1e-8,
        minimum_notional=5.0,
        shortable=False,
        borrow_required=False,
        funding_applicable=True,
        basis_applicable=True,
        data_source="perp",
        cost_source="PERP_FUNDING",
    )
    with pytest.raises(InstrumentSubstitutionError):
        require_same_instrument(EXP_ARP_023_SHORT_INSTRUMENT, perp)


def test_short_instrument_declares_borrow_and_no_cost_source() -> None:
    assert EXP_ARP_023_SHORT_INSTRUMENT.borrow_required is True
    assert EXP_ARP_023_SHORT_INSTRUMENT.shortable is True
    assert EXP_ARP_023_SHORT_INSTRUMENT.has_authoritative_cost is False
    assert EXP_ARP_023_SHORT_INSTRUMENT.instrument_type is InstrumentType.MARGIN_SPOT


# ------------------------------------------------------------- §13/§12/§16/§17


def test_uncosted_short_leg_fails_closed_never_zero() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=None,
    )
    assert result.status is PairExecutionStatus.PAIR_FAILED
    assert result.fail_closed is True
    assert result.cost.blocked_reason == "SHORT_LEG_UNCOSTED"
    assert result.cost.total_pair_cost is None
    assert result.ledger_entry is None
    # the fills are still represented (observable), but no pair is recorded
    assert result.short_fill.filled is True


def test_missing_borrow_rate_is_unknown_not_zero() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(borrow_rate=None),
    )
    assert result.status is PairExecutionStatus.PAIR_FAILED
    assert result.cost.borrow is None
    assert result.cost.economically_executable is False


def test_both_legs_pay_costs_independently() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(),
        holding_days=7.0,
    )
    entry = result.ledger_entry
    assert entry is not None
    # long leg priced by COST_MODEL_V3 rate; short leg by its own components
    assert entry.long_cost == pytest.approx(500.0 * COST_RT_BPS / 10_000.0)
    assert entry.short_cost == pytest.approx(0.5 + 0.1 + 0.05 + 1.75)
    assert entry.borrow_cost == pytest.approx(5.0 * 7.0 * 500.0 / 10_000.0)
    # costs are not collapsed into a single round-trip on the whole basket
    assert entry.total_cost > entry.long_cost


def test_short_cost_availability_after_decision_is_refused() -> None:
    with pytest.raises(ValueError, match="not PIT-safe"):
        _model().price_pair(
            long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
            short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
            long_notional=500.0,
            short_notional=500.0,
            holding_days=7.0,
            horizon_minutes=10_080.0,
            short_leg_cost=_short_cost(
                availability_timestamp=DECISION + 10 * MS_PER_DAY,
            ),
            decision_time=DECISION,
        )


# ------------------------------------------------------------- §25/§26/§28/§29


def test_long_fills_short_fails_fails_closed() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(short_available=False),
    )
    assert result.status is PairExecutionStatus.LONG_FILLED_SHORT_PENDING
    assert result.fail_closed is True
    assert result.ledger_entry is None


def test_short_fills_long_fails_fails_closed() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(long_available=False),
    )
    assert result.status is PairExecutionStatus.SHORT_FILLED_LONG_PENDING
    assert result.fail_closed is True


def test_partial_long_is_not_a_filled_pair() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(long_fill_ratio=0.5),
    )
    assert result.status is PairExecutionStatus.PARTIAL_LONG
    assert result.status.is_filled is False
    assert result.ledger_entry is None


def test_partial_short_is_not_a_filled_pair() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(short_fill_ratio=0.25),
    )
    assert result.status is PairExecutionStatus.PARTIAL_SHORT
    assert result.status.is_filled is False


def test_both_partial_is_pair_failed() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(long_fill_ratio=0.5, short_fill_ratio=0.5),
    )
    assert result.status is PairExecutionStatus.PAIR_FAILED


def test_leg_delay_creates_temporary_net_exposure() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(long_delay_ms=0, short_delay_ms=250),
        short_leg_cost=_short_cost(),
    )
    assert result.leg_delay_ms == 250
    assert result.temporary_net_exposure != 0.0


def test_one_leg_never_enters_the_ledger() -> None:
    ledger = PairLedger(initial_capital=10_000.0)
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(short_available=False),
    )
    assert result.ledger_entry is None
    assert ledger.n_pairs == 0


def test_leg_imbalance_beyond_tolerance_fails_the_pair() -> None:
    # both legs fully fill, but the *targets* leave a residual imbalance of 50,
    # far above the plan's 1.0 tolerance -> the pair must fail closed.
    proposal = _proposal(long_notional=500.0, short_notional=450.0)
    plan = PairExecutionPlan(
        execution_id="E2",
        proposal=proposal,
        execution_sequence=("LONG", "SHORT"),
        long_target_qty=5.0,
        short_target_qty=4.5,
        expected_fees=0.0,
        expected_spread=0.0,
        expected_slippage=0.0,
        borrow_requirement=450.0,
        funding_assumption=0.0,
        maximum_allowed_leg_imbalance=1.0,
        timeout_ms=60_000,
        failure_policy=FailurePolicy.ABORT_PAIR,
    )
    result = _sim().execute(
        plan,
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(),
    )
    assert result.long_fill.filled is True
    assert result.short_fill.filled is True
    assert result.status is PairExecutionStatus.PAIR_FAILED
    assert result.reason == "LEG_IMBALANCE_EXCEEDS_TOLERANCE"
    assert result.fail_closed is True


# ------------------------------------------------------------------ §20/§21/§30


def test_gross_and_net_exposure_are_reported_separately() -> None:
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(),
    )
    entry = result.ledger_entry
    assert entry is not None
    assert entry.gross_exposure == pytest.approx(1000.0)
    assert entry.net_exposure == pytest.approx(0.0, abs=1e-9)


def test_pair_ledger_reconciles_pnl_and_equity() -> None:
    ledger = PairLedger(initial_capital=10_000.0)
    for i in range(3):
        result = _sim().execute(
            _plan(),
            long_entry_ref=100.0,
            long_exit_ref=105.0 + i,
            short_entry_ref=100.0,
            short_exit_ref=95.0 - i,
            short_leg_cost=_short_cost(),
        )
        assert result.ledger_entry is not None
        ledger.append(result.ledger_entry)
    assert ledger.reconcile_pnl() == pytest.approx(0.0, abs=1e-6)
    assert ledger.reconcile_equity() == pytest.approx(0.0, abs=1e-6)
    assert ledger.total_pair_net_pnl == pytest.approx(
        ledger.total_pair_gross_pnl - ledger.total_costs + ledger.total_basis
    )


def test_ledger_refuses_a_one_leg_entry() -> None:
    ledger = PairLedger(initial_capital=10_000.0)
    result = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(short_available=False),
    )
    # craft an entry-like object from a partial by reusing a valid one is not
    # possible; the guard is exercised via the status check
    assert result.ledger_entry is None
    with pytest.raises(PairAccountingError):
        # a full-fill entry with a non-filled status must be rejected
        good = _sim().execute(
            _plan(),
            long_entry_ref=100.0,
            long_exit_ref=105.0,
            short_entry_ref=100.0,
            short_exit_ref=95.0,
            short_leg_cost=_short_cost(),
        ).ledger_entry
        assert good is not None
        import dataclasses

        ledger.append(dataclasses.replace(good, status=PairExecutionStatus.PARTIAL_LONG))


def test_accounting_invariant_detects_inconsistent_entry() -> None:
    good = (
        _sim()
        .execute(
            _plan(),
            long_entry_ref=100.0,
            long_exit_ref=105.0,
            short_entry_ref=100.0,
            short_exit_ref=95.0,
            short_leg_cost=_short_cost(),
        )
        .ledger_entry
    )
    assert good is not None
    import dataclasses

    with pytest.raises(PairAccountingError):
        dataclasses.replace(good, borrow_cost=good.borrow_cost + 1.0)


def test_determinism_same_inputs_same_result() -> None:
    a = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(),
    )
    b = _sim().execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=105.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        short_leg_cost=_short_cost(),
    )
    assert a.as_dict() == b.as_dict()


# ------------------------------------------------------------------- §22/§23/§24


def test_through_origin_beta_matches_manual_slope() -> None:
    market = [0.01, -0.02, 0.03, 0.005]
    returns = [0.02, -0.04, 0.06, 0.01]
    assert through_origin_beta(returns, market) == pytest.approx(2.0)


def test_through_origin_beta_fails_closed_on_zero_variance() -> None:
    with pytest.raises(ValueError):
        through_origin_beta([0.01, 0.02], [0.0, 0.0])


def test_beta_gate_boundary_and_signs() -> None:
    assert beta_gate(0.10, 0.10).passes is True
    assert beta_gate(-0.10, 0.10).passes is True
    assert beta_gate(0.100001, 0.10).passes is False
    assert beta_gate(-0.100001, 0.10).passes is False
    assert beta_gate(0.0, 0.10, computed=False).action == "FLAT"
    assert beta_gate(0.2, 0.10).reason == "REJECT_BETA"


def test_beta_book_uses_signed_weights() -> None:
    ts = [0, MS_PER_DAY, 2 * MS_PER_DAY]
    market = {0: 100.0, MS_PER_DAY: 110.0, 2 * MS_PER_DAY: 99.0}
    # long name with beta 1, short name with beta 1 -> net beta 0
    closes = {
        "A": {0: 100.0, MS_PER_DAY: 110.0, 2 * MS_PER_DAY: 99.0},
        "B": {0: 50.0, MS_PER_DAY: 55.0, 2 * MS_PER_DAY: 49.5},
    }
    result = beta_book({"A": 0.5, "B": -0.5}, closes, market, ts)
    assert result.computed is True
    assert result.beta_book == pytest.approx(0.0, abs=1e-9)


def test_beta_book_fails_closed_on_missing_bar() -> None:
    ts = [0, MS_PER_DAY, 2 * MS_PER_DAY]
    market = {0: 100.0, MS_PER_DAY: 110.0, 2 * MS_PER_DAY: 99.0}
    closes = {"A": {0: 100.0, MS_PER_DAY: 110.0}}  # missing the last bar
    result = beta_book({"A": 1.0}, closes, market, ts)
    assert result.computed is False
    assert result.blocked_reason.startswith("name_beta_window_incomplete")


def test_beta_diagnostic_is_evidence_only_and_deterministic() -> None:
    # synthetic upward-drifting corpus; BTC present
    symbols = ["BTCUSDT"] + [f"S{i:02d}" for i in range(24)]
    closes: dict[str, dict[int, float]] = {}
    for idx, sym in enumerate(symbols):
        series: dict[int, float] = {}
        price = 100.0 + idx
        for d in range(200):
            ts = d * MS_PER_DAY
            price *= 1.0 + 0.002 * ((idx % 3) - 1)
            series[ts] = price
        closes[sym] = series
    times = [d * MS_PER_DAY for d in range(120, 200, 7)]
    diag = beta_diagnostic(closes, times, top_k=5, min_members=20, formation_days=30)
    assert diag.n_books == len(times)
    assert diag.n_computed + diag.n_blocked == len(times)
    assert 0.0 <= diag.fraction_within_tolerance <= 1.0
    diag2 = beta_diagnostic(closes, times, top_k=5, min_members=20, formation_days=30)
    assert diag.as_dict() == diag2.as_dict()


def test_cost_knowledge_classes_are_explicit() -> None:
    model = _model()
    breakdown = model.price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
        long_notional=500.0,
        short_notional=500.0,
        holding_days=7.0,
        horizon_minutes=10_080.0,
        short_leg_cost=_short_cost(),
        decision_time=DECISION,
    )
    assert breakdown.long_knowledge is CostKnowledge.CONFIGURED
    assert breakdown.short_knowledge is CostKnowledge.OBSERVED
    assert breakdown.economically_executable is True
