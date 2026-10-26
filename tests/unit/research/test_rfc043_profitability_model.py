"""RFC-043 tests — capital scale & profitability operating model (§57).

Deterministic only: profit matrix, required-capital formula, drawdown matrix,
contribution accounting, milestone state machine, capital-scale gate, no-live
rule and no-alpha rule.  No strategy, no backtest, no market data.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import profitability_model as PM  # noqa: E402

# --------------------------------------------------------------------------- #
# §8/§9 — profit matrix and monthly equivalent
# --------------------------------------------------------------------------- #


def test_profit_matrix_is_capital_times_net_return() -> None:
    assert PM.annual_net_profit(200.0, 0.10) == pytest.approx(20.0)
    assert PM.annual_net_profit(200.0, 0.20) == pytest.approx(40.0)
    assert PM.annual_net_profit(1000.0, 0.20) == pytest.approx(200.0)
    assert PM.annual_net_profit(10000.0, 0.20) == pytest.approx(2000.0)
    assert PM.annual_net_profit(500.0, 0.05) == pytest.approx(25.0)


def test_monthly_equivalent_is_annual_over_twelve() -> None:
    assert PM.monthly_profit_equivalent(20.0) == pytest.approx(20.0 / 12.0)
    assert PM.monthly_profit_equivalent(2000.0) == pytest.approx(2000.0 / 12.0)


def test_capital_and_return_scenarios_are_complete() -> None:
    assert PM.CAPITAL_SCENARIOS == (200.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 25000.0, 50000.0, 100000.0)
    assert PM.CAPITAL_SCENARIOS[:6] == PM.DISPLAY_CAPITAL_SCENARIOS
    assert PM.RETURN_SCENARIOS == (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
    assert PM.HIGH_RISK_RETURN_SCENARIOS == (0.40, 0.50)


# --------------------------------------------------------------------------- #
# §10 — required-capital formula
# --------------------------------------------------------------------------- #


def test_required_capital_formula() -> None:
    assert PM.required_capital(1000.0, 0.10) == pytest.approx(10000.0)
    assert PM.required_capital(1000.0, 0.20) == pytest.approx(5000.0)
    assert PM.required_capital(100.0, 0.20) == pytest.approx(500.0)
    assert PM.required_capital(2500.0, 0.15) == pytest.approx(2500.0 / 0.15)


def test_required_capital_rejects_non_positive_return() -> None:
    with pytest.raises(ValueError):
        PM.required_capital(1000.0, 0.0)
    with pytest.raises(ValueError):
        PM.required_capital(1000.0, -0.05)


def test_required_capital_rates_are_declared() -> None:
    assert PM.REQUIRED_CAPITAL_RATES == (0.10, 0.15, 0.20)
    assert PM.PROFIT_TARGETS_USDT == (100.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0)


# --------------------------------------------------------------------------- #
# §13 — drawdown translation into money
# --------------------------------------------------------------------------- #


def test_drawdown_translation_at_200() -> None:
    assert PM.drawdown_loss(200.0, 0.10) == pytest.approx(-20.0)
    assert PM.drawdown_loss(200.0, 0.20) == pytest.approx(-40.0)
    assert PM.drawdown_loss(200.0, 0.30) == pytest.approx(-60.0)
    assert PM.drawdown_loss(200.0, 0.50) == pytest.approx(-100.0)


def test_drawdown_is_always_a_loss() -> None:
    assert PM.DRAWDOWN_SCENARIOS == (0.10, 0.20, 0.30, 0.50)
    assert all(PM.drawdown_loss(1000.0, dd) < 0 for dd in PM.DRAWDOWN_SCENARIOS)


# --------------------------------------------------------------------------- #
# §19-§22 — contribution vs trading PnL accounting
# --------------------------------------------------------------------------- #


def test_equity_identity() -> None:
    ending = PM.ending_equity(
        starting_equity=200.0,
        external_contributions=500.0,
        trading_pnl=30.0,
        withdrawals=100.0,
    )
    assert ending == pytest.approx(630.0)


def test_realized_trading_pnl_excludes_deposits() -> None:
    ending = PM.ending_equity(
        starting_equity=200.0,
        external_contributions=500.0,
        trading_pnl=30.0,
        withdrawals=0.0,
    )
    realized = PM.realized_trading_pnl(
        ending_equity_value=ending,
        starting_equity=200.0,
        external_contributions=500.0,
        withdrawals=0.0,
    )
    assert realized == pytest.approx(30.0)


def test_deposit_alone_creates_no_trading_profit() -> None:
    ending = PM.ending_equity(
        starting_equity=200.0,
        external_contributions=1000.0,
        trading_pnl=0.0,
        withdrawals=0.0,
    )
    realized = PM.realized_trading_pnl(
        ending_equity_value=ending,
        starting_equity=200.0,
        external_contributions=1000.0,
        withdrawals=0.0,
    )
    assert realized == pytest.approx(0.0)


def test_contribution_scenarios_are_declared() -> None:
    assert PM.MONTHLY_CONTRIBUTION_SCENARIOS_USDT == (0.0, 25.0, 50.0, 100.0, 200.0)
    assert PM.MONTHS_PER_YEAR == 12


# --------------------------------------------------------------------------- #
# §25-§26 — milestone state machine
# --------------------------------------------------------------------------- #


def zeros() -> dict[str, Any]:
    return {
        "business_validated_edges": 0,
        "paper_execution_pass": False,
        "forward_evidence_pass": False,
        "canary_deployed": False,
        "realized_net_pnl_positive": False,
        "capital_scaled_once": False,
        "repeated_profitability": False,
        "economically_meaningful_pnl": False,
    }


def test_no_edge_means_m0() -> None:
    assert PM.current_milestone(**zeros()) == "M0"
    assert PM.CURRENT_MILESTONE == "M0"


def test_milestones_are_sequential_and_never_skipped() -> None:
    facts = zeros()
    facts["business_validated_edges"] = 1
    assert PM.current_milestone(**facts) == "M1"
    facts["paper_execution_pass"] = True
    assert PM.current_milestone(**facts) == "M2"
    facts["forward_evidence_pass"] = True
    assert PM.current_milestone(**facts) == "M3"
    facts["canary_deployed"] = True
    assert PM.current_milestone(**facts) == "M4"
    facts["realized_net_pnl_positive"] = True
    assert PM.current_milestone(**facts) == "M5"
    facts["capital_scaled_once"] = True
    assert PM.current_milestone(**facts) == "M6"
    facts["repeated_profitability"] = True
    assert PM.current_milestone(**facts) == "M7"
    facts["economically_meaningful_pnl"] = True
    assert PM.current_milestone(**facts) == "M8"


def test_milestone_sequence_and_index() -> None:
    assert PM.MILESTONES == ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
    assert PM.milestone_index("M0") == 0
    assert PM.milestone_index("M5") == 5
    with pytest.raises(ValueError):
        PM.milestone_index("M9")


# --------------------------------------------------------------------------- #
# §18/§36 — capital-scale gate and no-live rule
# --------------------------------------------------------------------------- #


def test_capital_scale_gate_requires_every_condition() -> None:
    assert PM.capital_scale_gate(dict.fromkeys(PM.G_CAPITAL_SCALE_CONDITIONS, True))[
        "G_CAPITAL_SCALE"
    ] == "PASS"
    partial = dict.fromkeys(PM.G_CAPITAL_SCALE_CONDITIONS, True)
    partial["human_approval"] = False
    gate = PM.capital_scale_gate(partial)
    assert gate["G_CAPITAL_SCALE"] == "FAIL"
    assert "human_approval" in gate["failing_conditions"]


def test_capital_scale_needs_gate_and_realized_pnl() -> None:
    all_true = dict.fromkeys(PM.G_CAPITAL_SCALE_CONDITIONS, True)
    blocked = PM.capital_scale_decision(conditions=all_true, current_milestone_name="M0")
    assert blocked["capital_scale_authorized"] is False
    assert "realized_net_pnl_not_positive" in blocked["failing_conditions"]
    allowed = PM.capital_scale_decision(conditions=all_true, current_milestone_name="M5")
    assert allowed["capital_scale_authorized"] is True


def test_capital_scale_gate_has_seven_conditions() -> None:
    assert len(PM.G_CAPITAL_SCALE_CONDITIONS) == 7
    assert "human_approval" in PM.G_CAPITAL_SCALE_CONDITIONS


def test_no_live_capital_is_authorized() -> None:
    assert PM.LIVE_CAPITAL_AUTHORIZED_USDT == 0.0
    assert PM.PROFIT_KPIS["REALIZED_TRADING_PNL"] == 0
    assert PM.REFERENCE_CAPITAL_TIER == "CANARY_DESIGN"


# --------------------------------------------------------------------------- #
# §12/§15/§34 — leverage policy, tiers, capital is not alpha
# --------------------------------------------------------------------------- #


def test_leverage_is_not_a_capital_substitute() -> None:
    assert PM.LEVERAGE_POLICY == "LEVERAGE_IS_NOT_A_CAPITAL_SUBSTITUTE"
    assert PM.FORBIDDEN_LEVERAGE_MULTIPLES == ("10x", "20x", "50x")
    assert PM.CAPITAL_IS_NOT_ALPHA.startswith("MORE CAPITAL MULTIPLIES EDGE")


def test_capital_tier_ladder() -> None:
    assert PM.capital_tier_for(200.0) == "TIER_0"
    assert PM.capital_tier_for(500.0) == "TIER_1"
    assert PM.capital_tier_for(9999.0) == "TIER_4"
    assert PM.capital_tier_for(10000.0) == "TIER_5"
    assert PM.capital_tier_for(1_000_000.0) == "TIER_5"
    assert PM.ANY_TIER_AUTHORIZED is False


# --------------------------------------------------------------------------- #
# §24 — profit levels
# --------------------------------------------------------------------------- #


def test_profit_levels_do_not_invent_a_threshold() -> None:
    assert PM.profit_level(
        realized_net_pnl=0.0,
        annual_net_profit=0.0,
        execution_and_operational_costs=0.0,
        materially_larger_capital_deployed=False,
    ) == "NONE"
    assert PM.profit_level(
        realized_net_pnl=40.0,
        annual_net_profit=40.0,
        execution_and_operational_costs=100.0,
        materially_larger_capital_deployed=False,
    ) == "LEVEL_A_PROOF_OF_PROFITABILITY"
    assert PM.profit_level(
        realized_net_pnl=5000.0,
        annual_net_profit=5000.0,
        execution_and_operational_costs=500.0,
        materially_larger_capital_deployed=False,
    ) == "LEVEL_B_ECONOMICALLY_NOTICEABLE"
    assert PM.profit_level(
        realized_net_pnl=5000.0,
        annual_net_profit=5000.0,
        execution_and_operational_costs=500.0,
        materially_larger_capital_deployed=True,
    ) == "LEVEL_C_MEANINGFUL_INCOME_CONTRIBUTION"


# --------------------------------------------------------------------------- #
# §42/§56 — KPIs and FALSE_SUCCESS
# --------------------------------------------------------------------------- #


def test_profit_kpis_are_zero_and_reference_is_200() -> None:
    assert PM.REFERENCE_INITIAL_CAPITAL_USDT == 200.0
    assert PM.ROLE_OF_REFERENCE_CAPITAL == "FUTURE_CANARY_CAPITAL"
    assert all(v == 0 for v in PM.PROFIT_KPIS.values())


def test_false_success_counts_only_true_claims() -> None:
    assert PM.false_success_count({}) == 0
    assert PM.false_success_count({"leverage_proposed_to_solve_low_capital": True}) == 1
    assert PM.false_success_count(dict.fromkeys(PM.FALSE_SUCCESS_TRIGGERS, True)) == len(
        PM.FALSE_SUCCESS_TRIGGERS
    )


# --------------------------------------------------------------------------- #
# §2/§58 — no strategy artifact, no new alpha
# --------------------------------------------------------------------------- #


def test_module_exposes_no_executable_trading_constructs() -> None:
    source = (REPO / "src" / "trading_bot" / "research" / "profitability_model.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        r"^\s*class\s+\w*(Strategy|Signal|Portfolio|Backtest|Broker|OrderBook|ExecutionEngine)",
        r"^\s*def\s+(backtest|run_backtest|simulate|place_order|submit_order|generate_signal)\b",
    )
    for pattern in forbidden:
        assert not re.findall(pattern, source, flags=re.MULTILINE)


# --------------------------------------------------------------------------- #
# artifacts (present after `scripts/rfc043_run.py` + `rfc043_verify.py`)
# --------------------------------------------------------------------------- #

OUT = REPO / "reports" / "profitability-operating-model"
HAS_ARTIFACTS = (OUT / "CAPITAL_RETURN_MATRIX.json").exists()


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-043 artifacts not generated in this checkout")
def test_artifacts_record_the_operating_model() -> None:
    model = json.loads(
        (REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json").read_text(encoding="utf-8")
    )
    assert model["current_milestone"] == "M0"
    assert model["capital_scale_authorized"] is False
    assert model["role_of_200_usdt"] == "FUTURE_CANARY_CAPITAL"
    assert model["any_tier_authorized"] is False


@pytest.mark.skipif(not HAS_ARTIFACTS, reason="RFC-043 artifacts not generated in this checkout")
def test_final_report_shape_and_first_line() -> None:
    report = json.loads((REPO / "reports" / "RFC043_FINAL_REPORT.json").read_text(encoding="utf-8"))
    assert report["current_milestone"] == "M0"
    assert report["business_validated_edges"] == 0
    assert report["live_capital_authorized"] == 0
    assert report["alpha_research_freeze"] == "ACTIVE"
    assert report["next_alpha_rfc_allowed"] == "NO"
    assert report["capital_scale_authorized"] == "NO"
    assert report["next"] == "WAIT FOR BUSINESS EDGE"
    first_line = (REPO / "reports" / "RFC043_FINAL_REPORT.md").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "RFC-043 CAPITAL SCALE & PROFITABILITY OPERATING MODEL"
