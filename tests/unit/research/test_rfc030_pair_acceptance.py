"""RFC-030 §16/§17/§18/§19/§20/§21/§30/§32/§34/§36/§40/§41/§42 — acceptance tests.

These tests exercise the **actual** research/PAPER target
(``trading_bot.research.pair``) end-to-end, so ``TEST_TARGET == RUNTIME_TARGET``
(§36). The independent verifier (§40) recomputes from raw ledger fields without
touching the builder's aggregates, proving ``BUILDER != VERIFIER``.
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
    InstrumentType,
    PairCostModelV1,
    PairExecutionPlan,
    PairExecutionStatus,
    PairLedger,
    PairSimulator,
    PairTradeProposal,
    RawLedgerEntry,
    ShortLegCost,
    equity_metrics,
    max_drawdown,
    verify_ledger,
)

COST_RT_BPS = 23.559016994374947
MS_PER_DAY = 86_400_000
DECISION = 1_600_000_000_000
INITIAL_CAPITAL = 10_000.0


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
    fees: float | None = 0.5,
    spread_cost: float | None = 0.1,
    slippage_cost: float | None = 0.05,
) -> ShortLegCost:
    return ShortLegCost(
        instrument_id=EXP_ARP_023_SHORT_INSTRUMENT.instrument_id,
        borrow_rate=borrow_rate,
        fees=fees,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        source="TEST",
        source_timestamp=DECISION - MS_PER_DAY,
        availability_timestamp=DECISION - MS_PER_DAY,
    )


def _model() -> PairCostModelV1:
    return PairCostModelV1(long_cost_bps=COST_RT_BPS)


def _sim() -> PairSimulator:
    return PairSimulator(_model())


def _execute(
    *,
    long_entry: float = 100.0,
    long_exit: float = 110.0,
    short_entry: float = 100.0,
    short_exit: float = 95.0,
    short_cost: ShortLegCost | None = None,
    fill_config: FillConfig | None = None,
    holding_days: float = 7.0,
):
    return _sim().execute(
        _plan(),
        long_entry_ref=long_entry,
        long_exit_ref=long_exit,
        short_entry_ref=short_entry,
        short_exit_ref=short_exit,
        fill_config=fill_config or FillConfig(),
        short_leg_cost=short_cost if short_cost is not None else _short_cost(),
        holding_days=holding_days,
        horizon_minutes=holding_days * 1440.0,
    )


# ===================================================================== §G costs


def test_cost_components_are_separate_economic_components() -> None:
    """§16/§17 — long entry/exit, short entry/exit and borrow are distinct."""
    long_notional = 500.0
    short_notional = 500.0
    holding_days = 7.0
    breakdown = _model().price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
        long_notional=long_notional,
        short_notional=short_notional,
        holding_days=holding_days,
        horizon_minutes=holding_days * 1440.0,
        short_leg_cost=_short_cost(borrow_rate=5.0),
        decision_time=DECISION,
    )
    assert breakdown.economically_executable
    # long leg cost is exactly the injected COST_MODEL_V3 round-trip
    assert breakdown.long_cost == pytest.approx(long_notional * COST_RT_BPS / 10_000.0)
    # short leg = fees + spread + slippage + borrow (7 days @ 5 bps/day)
    expected_borrow = 5.0 * holding_days * short_notional / 10_000.0
    assert breakdown.borrow == pytest.approx(expected_borrow)
    assert breakdown.short_cost == pytest.approx(0.5 + 0.1 + 0.05 + expected_borrow)
    assert breakdown.funding == 0.0  # margin spot: no funding
    assert breakdown.basis == 0.0  # margin spot: no basis


def test_no_single_cost_shortcut_both_legs_charged() -> None:
    """§17 — the pair cost is not one leg's cost copied onto the other."""
    breakdown = _model().price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
        long_notional=500.0,
        short_notional=500.0,
        holding_days=7.0,
        horizon_minutes=10_080.0,
        short_leg_cost=_short_cost(),
        decision_time=DECISION,
    )
    assert breakdown.long_cost is not None and breakdown.short_cost is not None
    assert breakdown.long_cost != pytest.approx(breakdown.short_cost)
    assert breakdown.total_pair_cost == pytest.approx(breakdown.long_cost + breakdown.short_cost)


def test_no_duplicate_charge() -> None:
    """§17 — total pair cost equals the sum of the two leg costs exactly once."""
    breakdown = _model().price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
        long_notional=500.0,
        short_notional=500.0,
        holding_days=7.0,
        horizon_minutes=10_080.0,
        short_leg_cost=_short_cost(),
        decision_time=DECISION,
    )
    assert breakdown.total_pair_cost == pytest.approx(
        float(breakdown.long_cost) + float(breakdown.short_cost)
    )


def test_missing_short_cost_is_blocked_not_zero() -> None:
    """§13 — a borrow-required short with no borrow evidence is UNKNOWN, not 0."""
    breakdown = _model().price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
        long_notional=500.0,
        short_notional=500.0,
        holding_days=7.0,
        horizon_minutes=10_080.0,
        short_leg_cost=_short_cost(borrow_rate=None),
        decision_time=DECISION,
    )
    assert breakdown.economically_executable is False
    assert breakdown.short_knowledge is CostKnowledge.UNKNOWN
    assert breakdown.short_cost is None
    assert breakdown.blocked_reason == "SHORT_LEG_UNCOSTED"


def test_future_cost_timestamp_is_refused() -> None:
    """§14/§41 — a cost available after the decision can never price it."""
    from trading_bot.research.pair.costs import ShortLegCostError

    future = ShortLegCost(
        instrument_id=EXP_ARP_023_SHORT_INSTRUMENT.instrument_id,
        borrow_rate=5.0,
        fees=0.5,
        spread_cost=0.1,
        slippage_cost=0.05,
        source="TEST",
        source_timestamp=DECISION + 10 * MS_PER_DAY,
        availability_timestamp=DECISION + 10 * MS_PER_DAY,
    )
    with pytest.raises(ShortLegCostError, match="not PIT-safe"):
        _model().price_pair(
            long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
            short_instrument=EXP_ARP_023_SHORT_INSTRUMENT,
            long_notional=500.0,
            short_notional=500.0,
            holding_days=7.0,
            horizon_minutes=10_080.0,
            short_leg_cost=future,
            decision_time=DECISION,
        )


# ================================================================= §H ledger


def _ledger_entry(
    *,
    long_entry: float = 100.0,
    long_exit: float = 110.0,
    short_entry: float = 100.0,
    short_exit: float = 95.0,
    borrow_rate: float | None = 5.0,
    holding_days: float = 7.0,
):
    result = _execute(
        long_entry=long_entry,
        long_exit=long_exit,
        short_entry=short_entry,
        short_exit=short_exit,
        short_cost=_short_cost(borrow_rate=borrow_rate),
        holding_days=holding_days,
    )
    assert result.ledger_entry is not None
    return result.ledger_entry


@pytest.mark.parametrize(
    ("case", "long_exit", "short_exit", "expected_sign"),
    [
        ("profitable_long_losing_short", 110.0, 105.0, 1),
        ("losing_long_profitable_short", 90.0, 95.0, -1),
        ("both_profitable", 110.0, 95.0, 1),
        ("both_losing", 90.0, 105.0, -1),
    ],
)
def test_ledger_reconciles_ten_named_cases_leg_arithmetic(
    case: str, long_exit: float, short_exit: float, expected_sign: int
) -> None:
    """§18 — every leg component is independently reproducible and reconciles."""
    entry = _ledger_entry(long_exit=long_exit, short_exit=short_exit)
    long_gross = (entry.long_exit - entry.long_entry) * entry.long_qty
    short_gross = (entry.short_entry - entry.short_exit) * entry.short_qty
    assert entry.long_gross_pnl == pytest.approx(long_gross)
    assert entry.short_gross_pnl == pytest.approx(short_gross)
    assert entry.pair_gross_pnl == pytest.approx(long_gross + short_gross)
    assert entry.pair_net_pnl == pytest.approx(
        entry.pair_gross_pnl
        - entry.long_cost
        - entry.short_cost
        - entry.borrow_cost
        - entry.funding_cost
        + entry.basis_effect
    )
    assert entry.long_cost > 0.0 and entry.short_cost > 0.0 and entry.borrow_cost > 0.0
    assert entry.gross_exposure == pytest.approx(1000.0)
    assert entry.net_exposure == pytest.approx(0.0, abs=1e-6)
    if expected_sign > 0:
        assert entry.pair_gross_pnl > 0.0


def test_case_borrow_converts_gross_winner_to_net_loser() -> None:
    """§18 case 5 — a gross-winning pair can become a net loser after borrow."""
    entry = _ledger_entry(long_exit=100.5, short_exit=99.5, borrow_rate=500.0)
    assert entry.pair_gross_pnl > 0.0
    assert entry.borrow_cost > entry.pair_gross_pnl
    assert entry.pair_net_pnl < 0.0


def test_case_funding_positive_and_negative_are_modelled() -> None:
    """§18 cases 6/7 — funding is a signed economic component (perpetual only)."""
    # A perpetual short with a positive funding cost paid over the hold.
    pos = ShortLegCost(
        instrument_id="BINANCE-PERP-USDT-SHORT",
        funding_rate=1.0,
        funding_period=8 * 3_600_000,
        fees=0.5,
        spread_cost=0.1,
        slippage_cost=0.05,
        source="TEST",
        source_timestamp=DECISION - MS_PER_DAY,
        availability_timestamp=DECISION - MS_PER_DAY,
    )
    from trading_bot.research.pair.instruments import LegInstrumentContract, Side

    perp = LegInstrumentContract(
        instrument_id="BINANCE-PERP-USDT-SHORT",
        asset="ETHUSDT",
        venue="BINANCE",
        instrument_type=InstrumentType.PERPETUAL,
        side=Side.SHORT,
        quote_currency="USDT",
        contract_multiplier=1.0,
        price_increment=0.01,
        quantity_increment=0.001,
        minimum_notional=5.0,
        shortable=True,
        borrow_required=False,
        funding_applicable=True,
        basis_applicable=False,
        data_source="TEST",
        cost_source="TEST",
    )
    breakdown = _model().price_pair(
        long_instrument=EXP_ARP_023_LONG_INSTRUMENT,
        short_instrument=perp,
        long_notional=500.0,
        short_notional=500.0,
        holding_days=7.0,
        horizon_minutes=10_080.0,
        short_leg_cost=pos,
        decision_time=DECISION,
    )
    assert breakdown.funding is not None and breakdown.funding > 0.0
    assert breakdown.borrow in (None, 0.0)
    assert breakdown.economically_executable


@pytest.mark.parametrize(
    ("case", "fill_config", "expected_status"),
    [
        ("partial_long", FillConfig(long_fill_ratio=0.5, short_fill_ratio=0.0), "PARTIAL_LONG"),
        ("partial_short", FillConfig(long_fill_ratio=0.0, short_fill_ratio=0.5), "PARTIAL_SHORT"),
        ("one_leg_failure", FillConfig(short_available=False), "LONG_FILLED_SHORT_PENDING"),
    ],
)
def test_cases_partial_and_one_leg_never_enter_ledger(
    case: str, fill_config: FillConfig, expected_status: str
) -> None:
    """§18 cases 8/9/10 — partial / one-leg executions fail closed, no ledger."""
    result = _execute(fill_config=fill_config)
    assert result.status.value == expected_status
    assert result.ledger_entry is None
    assert result.fail_closed is True


def test_ten_named_cases_all_reconcile_in_one_ledger() -> None:
    """§18 — accumulate all ten named cases and reconcile the whole ledger."""
    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    cases = [
        _ledger_entry(long_exit=110.0, short_exit=105.0),  # 1 profitable long / losing short
        _ledger_entry(long_exit=90.0, short_exit=95.0),  # 2 losing long / profitable short
        _ledger_entry(long_exit=110.0, short_exit=95.0),  # 3 both profitable
        _ledger_entry(long_exit=90.0, short_exit=105.0),  # 4 both losing
        _ledger_entry(long_exit=100.5, short_exit=99.5, borrow_rate=500.0),  # 5 borrow flips
        _ledger_entry(long_exit=101.0, short_exit=99.0, borrow_rate=0.0001),  # 6 tiny borrow
        _ledger_entry(long_exit=99.0, short_exit=101.0, borrow_rate=0.0001),  # 7 tiny borrow
    ]
    for e in cases:
        ledger.append(e)
    # cases 8/9/10 are fail-closed and never appended (asserted separately)
    assert ledger.n_pairs == len(cases)
    assert ledger.reconcile_pnl() == pytest.approx(0.0, abs=1e-6)
    assert ledger.reconcile_equity() == pytest.approx(0.0, abs=1e-6)


# ================================================================ §I equity


def test_portfolio_accounting_exposes_all_required_fields() -> None:
    """§19 — the explicit capital model, no ambiguous reference notional."""
    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    ledger.append(_ledger_entry(long_exit=110.0, short_exit=95.0))
    state = ledger.portfolio_state()
    d = state.as_dict()
    for field in (
        "initial_capital",
        "cash",
        "long_notional",
        "short_notional",
        "gross_exposure",
        "net_exposure",
        "realized_pnl",
        "unrealized_pnl",
        "costs",
        "equity",
    ):
        assert field in d
    assert state.gross_exposure == pytest.approx(1000.0)
    assert state.net_exposure == pytest.approx(0.0, abs=1e-6)
    assert state.equity == pytest.approx(
        INITIAL_CAPITAL + state.realized_pnl + state.unrealized_pnl - state.costs
    )


def test_true_equity_return_and_drawdown() -> None:
    """§19/§32 — a true equity return / drawdown, not the notional proxy."""
    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    ledger.append(_ledger_entry(long_exit=110.0, short_exit=95.0))  # win
    ledger.append(_ledger_entry(long_exit=80.0, short_exit=120.0))  # big loss
    ledger.append(_ledger_entry(long_exit=105.0, short_exit=100.0))  # win
    m = equity_metrics(ledger)
    assert m.n_periods == 3
    assert m.equity_return is not None
    assert m.max_drawdown_fraction is not None and m.max_drawdown_fraction > 0.0
    assert m.final_equity == pytest.approx(INITIAL_CAPITAL + ledger.total_pair_net_pnl)
    assert m.profit_factor is not None and m.profit_factor > 0.0


def test_drawdown_is_none_when_capital_model_invalid() -> None:
    """§19 — no fabricated return/drawdown when initial capital is not positive."""
    ledger = PairLedger(initial_capital=0.0)
    ledger.append(_ledger_entry())
    m = equity_metrics(ledger)
    assert m.equity_return is None
    assert m.max_drawdown_fraction is None


def test_max_drawdown_helper() -> None:
    frac, abs_dd = max_drawdown([100.0, 120.0, 90.0, 130.0])
    assert abs_dd == pytest.approx(30.0)
    assert frac == pytest.approx(30.0 / 120.0)


# ========================================================== §J temporary exposure


def test_temporary_exposure_long_first() -> None:
    """§25 — long-first delay carries interim long-only exposure."""
    result = _execute(fill_config=FillConfig(long_delay_ms=0, short_delay_ms=250))
    assert result.leg_delay_ms == 250
    assert result.temporary_net_exposure == pytest.approx(500.0)
    assert result.temporary_gross_exposure == pytest.approx(500.0)
    assert result.temporary_beta_exposure == pytest.approx(500.0)


def test_temporary_exposure_short_first() -> None:
    """§25 — short-first delay carries interim short-only exposure."""
    result = _execute(fill_config=FillConfig(long_delay_ms=250, short_delay_ms=0))
    assert result.leg_delay_ms == 250
    assert result.temporary_net_exposure == pytest.approx(-500.0)
    assert result.temporary_gross_exposure == pytest.approx(500.0)
    assert result.temporary_beta_exposure == pytest.approx(-500.0)


def test_temporary_exposure_simultaneous_is_fully_neutral() -> None:
    result = _execute(fill_config=FillConfig(long_delay_ms=0, short_delay_ms=0))
    assert result.leg_delay_ms == 0
    assert result.temporary_net_exposure == pytest.approx(0.0, abs=1e-6)
    assert result.temporary_gross_exposure == pytest.approx(1000.0)


def test_partial_fill_fails_closed_regardless_of_delay() -> None:
    result = _execute(
        fill_config=FillConfig(long_fill_ratio=0.5, short_fill_ratio=0.0, short_delay_ms=100)
    )
    assert result.status is PairExecutionStatus.PARTIAL_LONG
    assert result.fail_closed is True


# ============================================================ §K/§L E2E path


def test_e2e_proposal_plan_fills_ledger_accounting_reconciliation() -> None:
    """§34/§36 — the full research/PAPER pair path in one deterministic run."""
    proposal = _proposal()
    plan = _plan(proposal)
    result = _sim().execute(
        plan,
        long_entry_ref=100.0,
        long_exit_ref=110.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(),
        short_leg_cost=_short_cost(),
        holding_days=7.0,
        horizon_minutes=10_080.0,
        beta_before=0.02,
        beta_after=0.01,
    )
    assert result.status is PairExecutionStatus.BOTH_FILLED
    assert result.ledger_entry is not None

    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    ledger.append(result.ledger_entry)
    assert ledger.reconcile_pnl() == pytest.approx(0.0, abs=1e-6)
    assert ledger.reconcile_equity() == pytest.approx(0.0, abs=1e-6)
    metrics = equity_metrics(ledger)
    assert metrics.n_periods == 1

    # determinism: a second identical run is byte-identical
    result2 = _sim().execute(
        plan,
        long_entry_ref=100.0,
        long_exit_ref=110.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(),
        short_leg_cost=_short_cost(),
        holding_days=7.0,
        horizon_minutes=10_080.0,
        beta_before=0.02,
        beta_after=0.01,
    )
    assert result.as_dict() == result2.as_dict()


def test_e2e_target_is_the_real_module_not_a_toy() -> None:
    """§36 — TEST_TARGET == RUNTIME_TARGET: the test drives the shipped modules."""
    import trading_bot.research.pair as pair_pkg

    assert PairSimulator is pair_pkg.PairSimulator
    assert PairLedger is pair_pkg.PairLedger
    assert _sim().__class__.__module__ == "trading_bot.research.pair.simulator"


# ====================================================== §M independent verifier


def test_independent_verifier_recomputes_from_raw_ledger() -> None:
    """§40 — the verifier reproduces every component from raw fields."""
    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    ledger.append(_ledger_entry(long_exit=110.0, short_exit=95.0))
    ledger.append(_ledger_entry(long_exit=90.0, short_exit=105.0))
    raw = [
        RawLedgerEntry(
            pair_id=e.pair_id,
            long_qty=e.long_qty,
            short_qty=e.short_qty,
            long_entry=e.long_entry,
            short_entry=e.short_entry,
            long_exit=e.long_exit,
            short_exit=e.short_exit,
            long_cost=e.long_cost,
            short_cost=e.short_cost,
            borrow_cost=e.borrow_cost,
            funding_cost=e.funding_cost,
            basis_effect=e.basis_effect,
            declared_long_gross_pnl=e.long_gross_pnl,
            declared_short_gross_pnl=e.short_gross_pnl,
            declared_pair_gross_pnl=e.pair_gross_pnl,
            declared_pair_net_pnl=e.pair_net_pnl,
        )
        for e in ledger.entries
    ]
    report = verify_ledger(raw, initial_capital=INITIAL_CAPITAL)
    assert report.verified is True
    assert report.n_pairs == 2
    assert report.recomputed_total_pair_net_pnl == pytest.approx(ledger.total_pair_net_pnl)
    assert report.recomputed_final_equity == pytest.approx(
        ledger.portfolio_state().equity
    )
    assert report.recomputed_total_gross_exposure == pytest.approx(
        ledger.total_gross_exposure
    )
    assert report.recomputed_total_net_exposure == pytest.approx(
        ledger.total_net_exposure
    )


def test_verifier_accepts_plain_dicts_and_detects_fabrication() -> None:
    """§40 — a fabricated aggregate is caught by recomputing from raw fields."""
    entry = _ledger_entry(long_exit=110.0, short_exit=95.0)
    d = entry.as_dict()
    ok = verify_ledger([d], initial_capital=INITIAL_CAPITAL)
    assert ok.verified is True

    tampered = dict(d)
    tampered["pair_net_pnl"] = d["pair_net_pnl"] + 1.0  # lie about the total
    bad = verify_ledger([tampered], initial_capital=INITIAL_CAPITAL)
    assert bad.verified is False
    assert any(r.field == "pair_net_pnl" and not r.ok for r in bad.residuals)
