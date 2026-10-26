"""RFC-043 — capital scale & profitability operating model (economic governance).

Executable encoding of the *economic operating model* RFC-043 is allowed to
build while ``ALPHA_RESEARCH_FREEZE = ACTIVE``.  This module contains **no
alpha, no strategy class, no signal, no order, no broker, no paper and no live
code** (§58).  It only provides the deterministic arithmetic and governance
primitives shared by the RFC-043 runner and its independent verifier:

* the objective function ``ABSOLUTE_NET_PROFIT = CAPITAL x NET_RETURN`` (§3-§4),
* capital scenarios (§6), net-return scenarios (§7) and the profit matrix (§8),
* the required-capital formula (§10) and the drawdown translation (§13),
* the capital ladder and the future ``G_CAPITAL_SCALE`` gate (§15/§18),
* contribution-vs-trading-PnL equity accounting (§19-§22),
* the M0-M8 milestone state machine (§25-§26) and the profit levels (§24),
* the RFC-043 FALSE_SUCCESS triggers (§56).

The independent verifier re-derives the same invariants from the *written*
artifacts and never imports this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# --------------------------------------------------------------------------- #
# §5 — the reference capital is a future canary, not income capital
# --------------------------------------------------------------------------- #

REFERENCE_INITIAL_CAPITAL_USDT = 200.0
ROLE_OF_REFERENCE_CAPITAL = "FUTURE_CANARY_CAPITAL"
NOT_ROLE_OF_REFERENCE_CAPITAL = "INCOME_GENERATING_CAPITAL"

# --------------------------------------------------------------------------- #
# §6/§7 — capital and net-return scenarios (illustrative, never forecasts)
# --------------------------------------------------------------------------- #

CAPITAL_SCENARIOS: tuple[float, ...] = (
    200.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
    10000.0,
    25000.0,
    50000.0,
    100000.0,
)

#: §51 — the capital rows the required profit table must display.
DISPLAY_CAPITAL_SCENARIOS: tuple[float, ...] = CAPITAL_SCENARIOS[:6]

RETURN_SCENARIOS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)

#: §7 — only ever labelled HIGH_RISK / NON_BASE_CASE.
HIGH_RISK_RETURN_SCENARIOS: tuple[float, ...] = (0.40, 0.50)

#: §52 — the rates used by the required-capital table.
REQUIRED_CAPITAL_RATES: tuple[float, ...] = (0.10, 0.15, 0.20)

PROFIT_TARGETS_USDT: tuple[float, ...] = (100.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0)

DRAWDOWN_SCENARIOS: tuple[float, ...] = (0.10, 0.20, 0.30, 0.50)

#: §14 — illustrative return/drawdown pairings; NO causal relation is claimed.
RISK_RETURN_SCENARIOS: tuple[tuple[float, float], ...] = (
    (0.10, 0.10),
    (0.15, 0.20),
    (0.20, 0.30),
    (0.30, 0.50),
)

#: §22 — illustrative monthly external contributions; none is assumed.
MONTHLY_CONTRIBUTION_SCENARIOS_USDT: tuple[float, ...] = (0.0, 25.0, 50.0, 100.0, 200.0)
MONTHS_PER_YEAR = 12

# --------------------------------------------------------------------------- #
# §12/§34/§35 — leverage, capital and the canonical business equation
# --------------------------------------------------------------------------- #

LEVERAGE_POLICY = "LEVERAGE_IS_NOT_A_CAPITAL_SUBSTITUTE"
FORBIDDEN_LEVERAGE_MULTIPLES: tuple[str, ...] = ("10x", "20x", "50x")
CAPITAL_IS_NOT_ALPHA = "MORE CAPITAL MULTIPLIES EDGE; IT DOES NOT CREATE EDGE"
REAL_PROFIT_EQUATION = (
    "REAL_PROFIT = VALIDATED_BUSINESS_EDGE x DEPLOYED_CAPITAL x TIME "
    "(subject to drawdown, cost, execution and regime uncertainty)"
)

# --------------------------------------------------------------------------- #
# §42-§43 — the profitability scoreboard stays visible and at zero
# --------------------------------------------------------------------------- #

REFERENCE_CAPITAL_TIER = "CANARY_DESIGN"

PROFIT_KPIS: dict[str, float] = {
    "BUSINESS_VALIDATED_EDGES": 0,
    "PAPER_CANDIDATES": 0,
    "FORWARD_PROFITABLE": 0,
    "LIVE_PROFITABLE": 0,
    "REALIZED_TRADING_PNL": 0,
}

LIVE_CAPITAL_AUTHORIZED_USDT = 0.0

# --------------------------------------------------------------------------- #
# §15 — capital ladder (conceptual; no tier is authorized)
# --------------------------------------------------------------------------- #

CAPITAL_TIERS: tuple[dict[str, Any], ...] = (
    {"tier": "TIER_0", "capital_usdt": 200.0, "label": "CANARY"},
    {"tier": "TIER_1", "capital_usdt": 500.0, "label": "FIRST_SCALE_REVIEW"},
    {"tier": "TIER_2", "capital_usdt": 1000.0, "label": "SMALL"},
    {"tier": "TIER_3", "capital_usdt": 2500.0, "label": "SMALL_PLUS"},
    {"tier": "TIER_4", "capital_usdt": 5000.0, "label": "MEDIUM"},
    {"tier": "TIER_5", "capital_usdt": 10000.0, "label": "MEDIUM_PLUS_AND_ABOVE"},
)

ANY_TIER_AUTHORIZED = False

# --------------------------------------------------------------------------- #
# §18 — the future capital-scale gate
# --------------------------------------------------------------------------- #

G_CAPITAL_SCALE_CONDITIONS: tuple[str, ...] = (
    "business_edge_still_valid",
    "paper_execution_pass",
    "forward_evidence_acceptable",
    "actual_costs_consistent",
    "no_major_reconciliation_defect",
    "drawdown_within_expected_envelope",
    "human_approval",
)

# --------------------------------------------------------------------------- #
# §24 — profit levels (no threshold is invented for the owner)
# --------------------------------------------------------------------------- #

PROFIT_LEVELS: dict[str, str] = {
    "LEVEL_A_PROOF_OF_PROFITABILITY": "REALIZED_NET_PNL > 0 after real costs",
    "LEVEL_B_ECONOMICALLY_NOTICEABLE": (
        "annual profit materially above execution and operational costs"
    ),
    "LEVEL_C_MEANINGFUL_INCOME_CONTRIBUTION": (
        "requires significantly larger capital; the 'meaningful' threshold is the "
        "owner's to set and is never invented here"
    ),
}

# --------------------------------------------------------------------------- #
# §25-§26 — the milestone state machine
# --------------------------------------------------------------------------- #

MILESTONES: tuple[str, ...] = (
    "M0",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "M8",
)

MILESTONE_MEANING: dict[str, str] = {
    "M0": "BUSINESS_EDGE = 0",
    "M1": "BUSINESS_EDGE = 1",
    "M2": "PAPER_EXECUTION = PASS",
    "M3": "FORWARD_EVIDENCE = PASS",
    "M4": "CANARY_DEPLOYED",
    "M5": "REALIZED_NET_PNL > 0",
    "M6": "CAPITAL_SCALE_1",
    "M7": "REPEATED_PROFITABILITY",
    "M8": "ECONOMICALLY_MEANINGFUL_PNL",
}

CURRENT_MILESTONE = "M0"

#: §36 — the official priority order; capital never moves first.
PRIORITY_ORDER: tuple[str, ...] = (
    "FIND BUSINESS EDGE",
    "VERIFY PAPER EXECUTION",
    "DEPLOY 200 USDT CANARY",
    "VERIFY REAL PNL",
    "SCALE CAPITAL",
)

#: §60 — the sequence the project measures itself against.
OFFICIAL_SEQUENCE: tuple[str, ...] = (
    "BUSINESS EDGE",
    "PAPER",
    "FORWARD",
    "200 USDT CANARY",
    "REALIZED NET PROFIT",
    "CAPITAL SCALE",
    "MEANINGFUL ABSOLUTE PROFIT",
)

OPERATING_QUESTIONS: tuple[str, ...] = (
    "DO WE HAVE EDGE?",
    "HOW MUCH CAPITAL CAN USE IT?",
    "HOW MUCH MONEY CAN IT REALISTICALLY PRODUCE?",
    "WHAT RISK DOES THAT REQUIRE?",
    "WHEN CAN WE SAFELY SCALE?",
)

# --------------------------------------------------------------------------- #
# §3-§4/§8-§13 — the arithmetic helpers (pure, deterministic)
# --------------------------------------------------------------------------- #


def annual_net_profit(capital_usdt: float, net_return: float) -> float:
    """§3 — ``ABSOLUTE_NET_PROFIT = CAPITAL x NET_RETURN`` (scenario maths)."""
    return float(capital_usdt) * float(net_return)


def monthly_profit_equivalent(annual_profit_usdt: float) -> float:
    """§9 — annual / 12, for magnitude only (no uniform timing is assumed)."""
    return float(annual_profit_usdt) / float(MONTHS_PER_YEAR)


def required_capital(target_annual_profit_usdt: float, net_return: float) -> float:
    """§10 — ``REQUIRED_CAPITAL = TARGET_ANNUAL_PROFIT / NET_RETURN``."""
    rate = float(net_return)
    if rate <= 0:
        raise ValueError(f"net_return must be positive: {net_return!r}")
    return float(target_annual_profit_usdt) / rate


def drawdown_loss(capital_usdt: float, drawdown: float) -> float:
    """§13 — translate a drawdown into absolute money."""
    return -abs(float(capital_usdt) * float(drawdown))


def ending_equity(
    *,
    starting_equity: float,
    external_contributions: float,
    trading_pnl: float,
    withdrawals: float,
) -> float:
    """§20 — ``ENDING = STARTING + CONTRIBUTIONS + TRADING_PNL - WITHDRAWALS``."""
    return (
        float(starting_equity)
        + float(external_contributions)
        + float(trading_pnl)
        - float(withdrawals)
    )


def realized_trading_pnl(
    *,
    ending_equity_value: float,
    starting_equity: float,
    external_contributions: float,
    withdrawals: float,
) -> float:
    """§21 — isolate true trading PnL, excluding any new deposit."""
    return (
        float(ending_equity_value)
        - float(starting_equity)
        - float(external_contributions)
        + float(withdrawals)
    )


def capital_tier_for(capital_usdt: float) -> str:
    """§15 — map a capital amount to its conceptual ladder tier."""
    capital = float(capital_usdt)
    tier = CAPITAL_TIERS[0]["tier"]
    for entry in CAPITAL_TIERS:
        if capital >= float(entry["capital_usdt"]):
            tier = entry["tier"]
    return str(tier)


def milestone_index(name: str) -> int:
    """§25 — ordered milestone index; raises on an unknown name."""
    if name not in MILESTONES:
        raise ValueError(f"unknown milestone: {name!r}")
    return MILESTONES.index(name)


def current_milestone(
    *,
    business_validated_edges: int,
    paper_execution_pass: bool,
    forward_evidence_pass: bool,
    canary_deployed: bool,
    realized_net_pnl_positive: bool,
    capital_scaled_once: bool,
    repeated_profitability: bool,
    economically_meaningful_pnl: bool,
) -> str:
    """§25-§26 — the furthest sequentially-reached milestone (never skipped)."""
    if int(business_validated_edges) < 1:
        return "M0"
    if not paper_execution_pass:
        return "M1"
    if not forward_evidence_pass:
        return "M2"
    if not canary_deployed:
        return "M3"
    if not realized_net_pnl_positive:
        return "M4"
    if not capital_scaled_once:
        return "M5"
    if not repeated_profitability:
        return "M6"
    if not economically_meaningful_pnl:
        return "M7"
    return "M8"


def profit_level(
    *,
    realized_net_pnl: float,
    annual_net_profit: float,
    execution_and_operational_costs: float,
    materially_larger_capital_deployed: bool,
) -> str:
    """§24 — A/B/C profit levels; never invents a 'meaningful' amount."""
    if float(realized_net_pnl) <= 0.0:
        return "NONE"
    if float(annual_net_profit) <= float(execution_and_operational_costs):
        return "LEVEL_A_PROOF_OF_PROFITABILITY"
    if not materially_larger_capital_deployed:
        return "LEVEL_B_ECONOMICALLY_NOTICEABLE"
    return "LEVEL_C_MEANINGFUL_INCOME_CONTRIBUTION"


def capital_scale_gate(conditions: Mapping[str, bool]) -> dict[str, Any]:
    """§18 — PASS only when *every* G_CAPITAL_SCALE condition holds."""
    missing = [c for c in G_CAPITAL_SCALE_CONDITIONS if not conditions.get(c, False)]
    return {
        "G_CAPITAL_SCALE": "PASS" if not missing else "FAIL",
        "failing_conditions": missing,
    }


def capital_scale_decision(
    *, conditions: Mapping[str, bool], current_milestone_name: str
) -> dict[str, Any]:
    """§17/§18/§36 — scaling needs the gate *and* a positive realized PnL (M5+)."""
    gate = capital_scale_gate(conditions)
    milestone_ok = milestone_index(current_milestone_name) >= milestone_index("M5")
    reasons = list(gate["failing_conditions"])
    if not milestone_ok:
        reasons.append("realized_net_pnl_not_positive")
    return {
        "capital_scale_authorized": bool(gate["G_CAPITAL_SCALE"] == "PASS" and milestone_ok),
        "G_CAPITAL_SCALE": gate["G_CAPITAL_SCALE"],
        "current_milestone": current_milestone_name,
        "failing_conditions": reasons,
    }


# --------------------------------------------------------------------------- #
# §56 — FALSE_SUCCESS triggers (target 0)
# --------------------------------------------------------------------------- #

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "scenario_called_forecast",
    "deposit_called_trading_profit",
    "capital_increase_treated_as_alpha",
    "leverage_proposed_to_solve_low_capital",
    "live_capital_authorized",
    "new_strategy_created",
    "research_freeze_released",
    "old_failed_candidate_promoted",
)


def false_success_count(claims: Mapping[str, bool]) -> int:
    """§56 — count only genuine incorrect claims or governance bypasses."""
    return sum(1 for t in FALSE_SUCCESS_TRIGGERS if claims.get(t, False))
