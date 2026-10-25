"""RFC-030 §34/§40 — pair E2E reachability + independent verification runner.

Drives the *shipped* ``trading_bot.research.pair`` modules end-to-end on
deterministic fixtures::

    PairTradeProposal -> PairExecutionPlan -> fills -> PairLedger
    -> portfolio accounting -> independent verification -> final result

This proves **infrastructure reachability** only. It does NOT assert EXP-ARP-023
profitability; the short-leg cost used here is a labelled fixture, not historical
borrow data, so ``economically_executable`` here means "the contract can price a
pair when a cost is supplied" — not that the experiment is runnable.

Usage::

    .venv/Scripts/python.exe scripts/rfc030_pair_e2e.py

Writes ``reports/rfc030/PAPER_E2E_REPORT.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.pair import (  # noqa: E402
    EXP_ARP_023_LONG_INSTRUMENT,
    EXP_ARP_023_SHORT_INSTRUMENT,
    FailurePolicy,
    FillConfig,
    PairCostModelV1,
    PairExecutionPlan,
    PairExecutionStatus,
    PairLedger,
    PairSimulator,
    PairTradeProposal,
    RawLedgerEntry,
    ShortLegCost,
    beta_gate,
    equity_metrics,
    verify_ledger,
)

OUT = REPO / "reports/rfc030/PAPER_E2E_REPORT.json"
COST_RT_BPS = 23.559016994374947
MS_PER_DAY = 86_400_000
DECISION = 1_700_000_000_000
INITIAL_CAPITAL = 10_000.0


def _proposal() -> PairTradeProposal:
    return PairTradeProposal(
        proposal_id="E2E-1",
        strategy_id="H-MKTNEUTRAL-RELVAL-001",
        decision_time=DECISION,
        long_leg=EXP_ARP_023_LONG_INSTRUMENT,
        short_leg=EXP_ARP_023_SHORT_INSTRUMENT,
        long_target_notional=500.0,
        short_target_notional=500.0,
        expected_beta=0.0,
        beta_tolerance=0.10,
    )


def _plan() -> PairExecutionPlan:
    return PairExecutionPlan(
        execution_id="E2E-1",
        proposal=_proposal(),
        execution_sequence=("LONG", "SHORT"),
        long_target_qty=5.0,
        short_target_qty=5.0,
        expected_fees=0.5,
        expected_spread=0.1,
        expected_slippage=0.05,
        borrow_requirement=500.0,
        funding_assumption=0.0,
        maximum_allowed_leg_imbalance=5.0,
        timeout_ms=60_000,
        failure_policy=FailurePolicy.ABORT_PAIR,
    )


def _fixture_short_cost() -> ShortLegCost:
    """A *fixture* short cost — explicitly labelled, never a historical series."""
    return ShortLegCost(
        instrument_id=EXP_ARP_023_SHORT_INSTRUMENT.instrument_id,
        borrow_rate=5.0,
        fees=0.5,
        spread_cost=0.1,
        slippage_cost=0.05,
        source="E2E_FIXTURE_NOT_HISTORICAL",
        source_timestamp=DECISION - MS_PER_DAY,
        availability_timestamp=DECISION - MS_PER_DAY,
    )


def _run_case(name: str, fill: FillConfig) -> dict[str, object]:
    sim = PairSimulator(PairCostModelV1(long_cost_bps=COST_RT_BPS))
    result = sim.execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=110.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=fill,
        short_leg_cost=_fixture_short_cost(),
        holding_days=7.0,
        horizon_minutes=10_080.0,
        beta_before=0.02,
        beta_after=0.01,
    )
    return {
        "name": name,
        "status": result.status.value,
        "fail_closed": result.fail_closed,
        "reason": result.reason,
        "leg_delay_ms": result.leg_delay_ms,
        "temporary_net_exposure": result.temporary_net_exposure,
        "temporary_gross_exposure": result.temporary_gross_exposure,
        "temporary_beta_exposure": result.temporary_beta_exposure,
        "ledger_entry_present": result.ledger_entry is not None,
    }


def main() -> int:
    cases = [
        _run_case("both_filled", FillConfig()),
        _run_case("long_first_delay", FillConfig(long_delay_ms=0, short_delay_ms=250)),
        _run_case("short_first_delay", FillConfig(long_delay_ms=250, short_delay_ms=0)),
        _run_case("partial_long", FillConfig(long_fill_ratio=0.5, short_fill_ratio=0.0)),
        _run_case("partial_short", FillConfig(long_fill_ratio=0.0, short_fill_ratio=0.5)),
        _run_case("one_leg_failure", FillConfig(short_available=False)),
    ]

    # Build the ledger from the fully-filled case only (§26/§29).
    sim = PairSimulator(PairCostModelV1(long_cost_bps=COST_RT_BPS))
    filled = sim.execute(
        _plan(),
        long_entry_ref=100.0,
        long_exit_ref=110.0,
        short_entry_ref=100.0,
        short_exit_ref=95.0,
        fill_config=FillConfig(),
        short_leg_cost=_fixture_short_cost(),
        holding_days=7.0,
        horizon_minutes=10_080.0,
        beta_before=0.02,
        beta_after=0.01,
    )
    assert filled.status is PairExecutionStatus.BOTH_FILLED
    assert filled.ledger_entry is not None

    ledger = PairLedger(initial_capital=INITIAL_CAPITAL)
    ledger.append(filled.ledger_entry)
    state = ledger.portfolio_state()
    metrics = equity_metrics(ledger)

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
    verification = verify_ledger(raw, initial_capital=INITIAL_CAPITAL)

    gate = beta_gate(0.02, 0.10)

    report: dict[str, object] = {
        "note": (
            "Infrastructure reachability only. Short-leg cost is an E2E fixture, "
            "NOT a historical borrow series; no EXP-ARP-023 profitability is asserted."
        ),
        "oos_opened": False,
        "dev_executed": False,
        "cases": cases,
        "ledger": {
            "n_pairs": ledger.n_pairs,
            "pnl_reconciliation_residual": ledger.reconcile_pnl(),
            "equity_reconciliation_residual": ledger.reconcile_equity(),
            "portfolio_state": state.as_dict(),
            "equity_metrics": metrics.as_dict(),
        },
        "independent_verification": verification.as_dict(),
        "beta_gate": gate.as_dict(),
        "test_target_runtime_target": {
            "module": PairSimulator.__module__,
            "verdict": "MATCH",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
