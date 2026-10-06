"""RFC-043 orchestration — CAPITAL SCALE & PROFITABILITY OPERATING MODEL.

A purely-economic modelling run while ``ALPHA_RESEARCH_FREEZE = ACTIVE``.  It
turns "we want to make money" into a quantified capital + return + risk plan:
the capital x net-return profit matrix (§8), the required-capital table (§10),
the drawdown translation (§13), the capital ladder and the future
``G_CAPITAL_SCALE`` gate (§15/§18), contribution-vs-trading-PnL accounting
(§19-§22) and the M0-M8 milestone state machine (§25-§26).

No alpha, no strategy, no signal, no backtest, no parameter search, no broker,
no paper run, no live order and no paid data (§2).  Nothing here authorizes
live capital, scales a tier, releases the research freeze or promotes an old
failed candidate (§17/§37/§38/§56).

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import profitability_model as pf  # noqa: E402

OUT = REPO / "reports" / "profitability-operating-model"
REPORTS = REPO / "reports"
DOCS = REPO / "docs" / "research"

#: §1 — expected repository state entering RFC-043 (verified, never assumed).
EXPECTED_ANCESTORS: dict[str, str] = {
    "RFC-041": "1437f46",
    "RFC-042": "03ce3f1",
}

#: §2 — hard governance rule the run must never break.
HARD_RULE = "ALPHA_RESEARCH_FREEZE = ACTIVE"
NEXT_ALPHA_RFC_ALLOWED = "NO"

#: §54/§56 — phrases that would turn a scenario into a claimed forecast.
FORBIDDEN_FORECAST_PHRASES: tuple[str, ...] = (
    "guaranteed profit",
    "guaranteed return",
    "guaranteed annual",
    "expected guaranteed",
    "will definitely earn",
    "assured profit",
    "risk-free profit",
)

NOT_ALLOWED: tuple[str, ...] = (
    "new strategy",
    "new signal",
    "new backtest",
    "parameter search",
    "broker live integration",
    "paper run",
    "live order",
    "extreme leverage",
    "capital contribution by the system",
)

# --------------------------------------------------------------------------- #
# §29-§33 — archived-candidate review across capital scales (real evidence only)
# --------------------------------------------------------------------------- #

#: §31 — MF-TREND-001 product fit across scales (evidence from RFC-036/038).
MF_PRODUCT_FIT_BY_SCALE: tuple[dict[str, str], ...] = (
    {"scale": "200 USDT", "product_fit": "NO"},
    {"scale": "1,000 USDT", "product_fit": "NO"},
    {"scale": "10,000 USDT", "product_fit": "NO"},
    {"scale": "100,000 USDT", "product_fit": "LIKELY_STILL_NO_UNDER_CURRENT_IMPLEMENTATION"},
    {"scale": "multi-million USDT", "product_fit": "REVIEW"},
)

CANDIDATE_CAPITAL_REVIEW: tuple[dict[str, Any], ...] = (
    {
        "candidate_id": "MF-TREND-001",
        "family": "diversified managed-futures trend",
        "capital_fit_at_200": "FAIL_FOR_200",
        "capital_requirement": "INSTITUTIONAL",
        "business_edge": "EXECUTABLE_VALIDATED_EDGE (net Sharpe 1.14)",
        "product_fit_by_scale": MF_PRODUCT_FIT_BY_SCALE,
        "does_more_capital_help": "PARTIALLY: capital is the binding constraint, but the "
        "implementation itself is not retail-product-fit",
        "reentry_condition": "MATERIAL CAPITAL CHANGE (trigger C) or an economically "
        "equivalent small-capital implementation",
        "note": "evidence from RFC-036/RFC-038; no new threshold is invented",
    },
    {
        "candidate_id": "SC-TREND-001",
        "family": "multi-asset absolute momentum (ETF)",
        "capital_fit_at_200": "PASS_AT_200",
        "capital_requirement": "SMALL",
        "business_edge": "FAIL (risk-adjusted return below a passive benchmark)",
        "product_fit_by_scale": (),
        "does_more_capital_help": "NO: a larger capital multiplies the same weak edge; it "
        "does not fix a benchmark-relative shortfall",
        "reentry_condition": "only as a defensive overlay once a profit engine exists",
        "note": "VALIDATED_DEFENSIVE; more capital never repairs a business-edge failure",
    },
    {
        "candidate_id": "SC-DUALMOM-002",
        "family": "dual momentum / GEM (ETF)",
        "capital_fit_at_200": "PASS_AT_200",
        "capital_requirement": "SMALL",
        "business_edge": "FAIL (excess risk-matched return < 0)",
        "product_fit_by_scale": (),
        "does_more_capital_help": "NO: reopening it on capital growth alone is forbidden",
        "reentry_condition": "NEW EXTERNAL EVIDENCE or NEW STRUCTURAL EDGE (triggers A/B) only",
        "note": "REJECTED_BUSINESS_EDGE; capital growth does not reopen it",
    },
    {
        "candidate_id": "SC-CANDIDATE-003",
        "family": "(would-be small-capital candidate)",
        "capital_fit_at_200": "NOT_AUTHORIZED",
        "capital_requirement": "NONE",
        "business_edge": "NONE (never created)",
        "product_fit_by_scale": (),
        "does_more_capital_help": "NO: requires G_BUSINESS_REENTRY = PASS first",
        "reentry_condition": "G_BUSINESS_REENTRY = PASS",
        "note": "NOT_AUTHORIZED",
    },
)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _render_value(value: Any, indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                out.append(f"{pad}- **{key}**:")
                out.extend(_render_value(item, indent + 1))
            else:
                out.append(f"{pad}- **{key}**: {item}")
        return out
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, sub in item.items():
                    marker = f"{pad}- " if first else f"{pad}  "
                    if isinstance(sub, (dict, list)):
                        out.append(f"{marker}**{key}**:")
                        out.extend(_render_value(sub, indent + 1))
                    else:
                        out.append(f"{marker}**{key}**: {sub}")
                    first = False
            else:
                out.append(f"{pad}- {item}")
        return out
    out.append(f"{pad}{value}")
    return out


def render(title: str, payload: Any) -> str:
    lines = [f"# {title}", ""]
    lines.extend(_render_value(payload, 0))
    lines.append("")
    return "\n".join(lines)


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a real markdown table (required by §51-§52)."""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def fmt_money(value: float) -> str:
    """Deterministic money formatting: integers stay integer, else 2 decimals."""
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


# --------------------------------------------------------------------------- #
# entry gate
# --------------------------------------------------------------------------- #


def _is_ancestor(rev: str, head: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rev, head],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def entry_gate() -> dict[str, Any]:
    head = git(["rev-parse", "HEAD"])
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    ancestors = {name: _is_ancestor(rev, head) for name, rev in EXPECTED_ANCESTORS.items()}
    state = json.loads((DOCS / "ECONOMIC_STATE.json").read_text(encoding="utf-8"))
    freeze = state["alpha_research_freeze"]
    edge_count = int(state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"])
    hard_rule_ok = freeze == "ACTIVE" and edge_count == 0
    return {
        "repository": str(REPO),
        "branch": branch,
        "head": head,
        "source_commit": git(["rev-parse", EXPECTED_ANCESTORS["RFC-042"]]),
        "git_log_15": git(["log", "-15", "--oneline"]).splitlines(),
        "git_status_short": git(["status", "--short"]).splitlines(),
        "expected_ancestors": EXPECTED_ANCESTORS,
        "ancestors_present": ancestors,
        "documents_read": [
            "docs/research/ECONOMIC_STATE.json",
            "docs/research/FINAL_BUSINESS_DECISION.md",
            "docs/research/BUSINESS_REENTRY_POLICY.md",
            "docs/research/ECONOMIC_SCOREBOARD.md",
            "docs/research/CANDIDATE_ARCHIVE.md",
        ],
        "alpha_research_freeze": freeze,
        "business_validated_edge_count": edge_count,
        "hard_rule": HARD_RULE,
        "hard_rule_ok": hard_rule_ok,
        "entry_condition_met": hard_rule_ok and all(ancestors.values()),
    }


# --------------------------------------------------------------------------- #
# matrices (§8, §10, §13, §14, §22)
# --------------------------------------------------------------------------- #


def capital_return_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capital in pf.CAPITAL_SCENARIOS:
        row: dict[str, Any] = {
            "capital_usdt": capital,
            "annual_net_profit": {},
            "monthly_equivalent": {},
        }
        for rate in pf.RETURN_SCENARIOS:
            annual = pf.annual_net_profit(capital, rate)
            row["annual_net_profit"][f"{rate:.0%}"] = annual
            row["monthly_equivalent"][f"{rate:.0%}"] = pf.monthly_profit_equivalent(annual)
        rows.append(row)
    return rows


def high_risk_return_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capital in pf.CAPITAL_SCENARIOS:
        rows.append(
            {
                "capital_usdt": capital,
                "annual_net_profit": {
                    f"{rate:.0%}": pf.annual_net_profit(capital, rate)
                    for rate in pf.HIGH_RISK_RETURN_SCENARIOS
                },
                "classification": "HIGH_RISK / NON_BASE_CASE",
            }
        )
    return rows


def profit_target_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in pf.PROFIT_TARGETS_USDT:
        rows.append(
            {
                "target_annual_profit_usdt": target,
                "required_capital": {
                    f"{rate:.0%}": pf.required_capital(target, rate)
                    for rate in pf.REQUIRED_CAPITAL_RATES
                },
            }
        )
    return rows


def drawdown_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capital in pf.CAPITAL_SCENARIOS:
        rows.append(
            {
                "capital_usdt": capital,
                "loss_usdt": {
                    f"{dd:.0%}": pf.drawdown_loss(capital, dd) for dd in pf.DRAWDOWN_SCENARIOS
                },
            }
        )
    return rows


def risk_return_matrix() -> list[dict[str, Any]]:
    return [
        {
            "annual_net_return": rate,
            "max_drawdown": dd,
            "note": "illustrative pairing only; no causal relation is claimed",
        }
        for rate, dd in pf.RISK_RETURN_SCENARIOS
    ]


def contribution_scenarios() -> list[dict[str, Any]]:
    """§19-§22 — deposits are never trading PnL; trading growth stays zero."""
    start = pf.REFERENCE_INITIAL_CAPITAL_USDT
    rows: list[dict[str, Any]] = []
    for monthly in pf.MONTHLY_CONTRIBUTION_SCENARIOS_USDT:
        contributions = monthly * pf.MONTHS_PER_YEAR
        trading_pnl = 0.0  # no validated edge => no trading growth is assumed (§54)
        withdrawals = 0.0
        ending = pf.ending_equity(
            starting_equity=start,
            external_contributions=contributions,
            trading_pnl=trading_pnl,
            withdrawals=withdrawals,
        )
        rows.append(
            {
                "monthly_contribution_usdt": monthly,
                "annual_external_contributions_usdt": contributions,
                "growth_from_contributions_usdt": contributions,
                "growth_from_trading_usdt": trading_pnl,
                "starting_equity_usdt": start,
                "ending_equity_usdt": ending,
                "withdrawals_usdt": withdrawals,
                "realized_trading_pnl_usdt": pf.realized_trading_pnl(
                    ending_equity_value=ending,
                    starting_equity=start,
                    external_contributions=contributions,
                    withdrawals=withdrawals,
                ),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #


def build_plan(entry: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "title": "CAPITAL SCALE & PROFITABILITY OPERATING MODEL",
        "mission": (
            "Turn 'we want to make money' into a quantified capital + return + risk "
            "plan: what 200 USDT can prove, what it can earn under different return "
            "scenarios, how much capital various absolute profit targets require, and "
            "when capital may or may not scale."
        ),
        "absolute_net_profit": "ABSOLUTE_NET_PROFIT = CAPITAL x NET_RETURN",
        "net_return_definition": (
            "NET_RETURN = gross strategy return - fees - spread - slippage - financing "
            "(tax excluded from system economics)"
        ),
        "profitability_definition": (
            "PROFITABILITY = NET_RETURN + CAPITAL + TIME + RISK + COST "
            "(a high return is not by itself a good business)"
        ),
        "reference_capital": {
            "reference_initial_capital_usdt": pf.REFERENCE_INITIAL_CAPITAL_USDT,
            "role": pf.ROLE_OF_REFERENCE_CAPITAL,
            "not_role": pf.NOT_ROLE_OF_REFERENCE_CAPITAL,
        },
        "hard_rule": HARD_RULE,
        "next_alpha_rfc_allowed": NEXT_ALPHA_RFC_ALLOWED,
        "not_allowed": list(NOT_ALLOWED),
        "capital_scenarios": list(pf.CAPITAL_SCENARIOS),
        "return_scenarios": {
            "base": [f"{r:.0%}" for r in pf.RETURN_SCENARIOS],
            "high_risk_non_base_case": [f"{r:.0%}" for r in pf.HIGH_RISK_RETURN_SCENARIOS],
        },
        "leverage_policy": pf.LEVERAGE_POLICY,
        "forbidden_leverage": list(pf.FORBIDDEN_LEVERAGE_MULTIPLES),
        "capital_is_not_alpha": pf.CAPITAL_IS_NOT_ALPHA,
        "real_profit_equation": pf.REAL_PROFIT_EQUATION,
        "priority_order": list(pf.PRIORITY_ORDER),
        "official_sequence": list(pf.OFFICIAL_SEQUENCE),
        "operating_questions": list(pf.OPERATING_QUESTIONS),
        "entry_gate": entry,
    }


def build_model_payload(generated_at: str) -> dict[str, Any]:
    """§46-§47 — the main PROFITABILITY_OPERATING_MODEL document payload."""
    current = pf.current_milestone(
        business_validated_edges=0,
        paper_execution_pass=False,
        forward_evidence_pass=False,
        canary_deployed=False,
        realized_net_pnl_positive=False,
        capital_scaled_once=False,
        repeated_profitability=False,
        economically_meaningful_pnl=False,
    )
    scale = pf.capital_scale_decision(
        conditions=dict.fromkeys(pf.G_CAPITAL_SCALE_CONDITIONS, False),
        current_milestone_name=current,
    )
    return {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "title": "PROFITABILITY OPERATING MODEL",
        "reference_capital_usdt": pf.REFERENCE_INITIAL_CAPITAL_USDT,
        "role_of_200_usdt": pf.ROLE_OF_REFERENCE_CAPITAL,
        "current_milestone": current,
        "capital_scale_authorized": scale["capital_scale_authorized"],
        "answers": {
            "what_can_200_usdt_prove": (
                "It can prove real order, fill, fee, spread, quantity rounding, "
                "reconciliation and PnL behaviour of a strategy that already cleared "
                "the business-edge gate. It cannot prove statistical alpha."
            ),
            "what_can_200_usdt_earn": (
                "A small absolute amount: at a 20% net annual return it is 40 USDT/year, "
                "i.e. about 3.33 USDT/month. These are scenarios, never forecasts."
            ),
            "how_much_capital_for_targets": (
                "Dividing the target by the net return: e.g. 1,000 USDT/year needs 10,000 "
                "USDT at a 10% net return but 5,000 USDT at a 20% net return."
            ),
            "when_can_capital_scale": (
                "Only after G_CAPITAL_SCALE = PASS and a positive realized trading PnL, "
                "with evidence and explicit human approval - never automatically."
            ),
            "when_must_capital_not_scale": (
                "Whenever the business edge is unproven, paper execution has not passed, "
                "or realized costs do not match assumptions - which is the case today."
            ),
            "what_counts_as_real_trading_profit": (
                "REALIZED_TRADING_PNL after real costs, excluding any external deposit; "
                "ending_equity = starting + contributions + trading_pnl - withdrawals."
            ),
        },
        "canary_purpose": (
            "200 USDT exists to check actual order, fill, fee, spread, quantity "
            "rounding, reconciliation and PnL of an already-validated edge; never to "
            "prove statistical alpha."
        ),
        "benchmark_alternative": (
            "Any future strategy must also be compared against DO_NOT_TRADE / a "
            "passive alternative, because capital deployed in trading carries an "
            "opportunity cost."
        ),
        "business_edge_requirement": (
            "RFC-041 requirement stands unchanged: NET POSITIVE + BENCHMARK-ADJUSTED "
            "VALUE + EXECUTABLE + ROBUST. It is never relaxed to trade sooner."
        ),
        "trigger_c_capital_change": (
            "A material capital change (trigger C) only opens a PRODUCT_FIT_REVIEW for "
            "archived candidates; it never approves a strategy by itself."
        ),
        "next_action_policy": {
            "trigger": (
                "ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT "
                "CHANGE reopens evaluation"
            ),
            "no_periodic_rfc": "No RFC-044/RFC-045 merely because time passes",
            "opportunity_watch": (
                "human process: NEW EVIDENCE -> BUSINESS_REENTRY_CHECKLIST (no daemon, "
                "no new infrastructure)"
            ),
        },
        "profitability_definition": (
            "PROFITABILITY = NET_RETURN + CAPITAL + TIME + RISK + COST"
        ),
        "real_profit_equation": pf.REAL_PROFIT_EQUATION,
        "capital_tiers": [dict(t) for t in pf.CAPITAL_TIERS],
        "any_tier_authorized": pf.ANY_TIER_AUTHORIZED,
        "capital_scale_gate_conditions": list(pf.G_CAPITAL_SCALE_CONDITIONS),
        "milestones": [
            {"milestone": m, "meaning": pf.MILESTONE_MEANING[m]} for m in pf.MILESTONES
        ],
        "profit_levels": dict(pf.PROFIT_LEVELS),
        "leverage_policy": pf.LEVERAGE_POLICY,
        "priority_order": list(pf.PRIORITY_ORDER),
        "official_sequence": list(pf.OFFICIAL_SEQUENCE),
        "operating_questions": list(pf.OPERATING_QUESTIONS),
        "next": "WAIT FOR BUSINESS EDGE",
    }


def build_scoreboard(generated_at: str) -> dict[str, Any]:
    """§42-§43 — tracked profitability operating scoreboard."""
    return {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "reference_capital": int(pf.REFERENCE_INITIAL_CAPITAL_USDT),
        "business_validated_edges": int(pf.PROFIT_KPIS["BUSINESS_VALIDATED_EDGES"]),
        "paper_candidates": int(pf.PROFIT_KPIS["PAPER_CANDIDATES"]),
        "forward_profitable": int(pf.PROFIT_KPIS["FORWARD_PROFITABLE"]),
        "live_profitable": int(pf.PROFIT_KPIS["LIVE_PROFITABLE"]),
        "realized_trading_pnl": int(pf.PROFIT_KPIS["REALIZED_TRADING_PNL"]),
        "current_milestone": pf.CURRENT_MILESTONE,
        "research_freeze": "ACTIVE",
        "capital_tier": pf.REFERENCE_CAPITAL_TIER,
        "live_capital_authorized": int(pf.LIVE_CAPITAL_AUTHORIZED_USDT),
    }


# --------------------------------------------------------------------------- #
# markdown documents with real tables (§51-§52)
# --------------------------------------------------------------------------- #


def capital_profit_matrix_md(payload: dict[str, Any]) -> str:
    rates = [f"{r:.0%}" for r in pf.RETURN_SCENARIOS]
    lines = [
        "# RFC-043 CAPITAL PROFIT MATRIX",
        "",
        "Illustrative scenario arithmetic, not a forecast:",
        "annual net profit = capital x net annual return.",
        "",
        "## Annual net profit (USDT) - §51",
        "",
        *md_table(
            ["Capital (USDT)", *rates],
            [
                [
                    fmt_money(row["capital_usdt"]),
                    *[fmt_money(row["annual_net_profit"][r]) for r in rates],
                ]
                for row in payload["capital_return_matrix"]
            ],
        ),
        "",
        "## Monthly profit equivalent (USDT/month) - §9 (magnitude only)",
        "",
        *md_table(
            ["Capital (USDT)", *rates],
            [
                [
                    fmt_money(row["capital_usdt"]),
                    *[fmt_money(row["monthly_equivalent"][r]) for r in rates],
                ]
                for row in payload["capital_return_matrix"]
            ],
        ),
        "",
        "## High-risk / non-base-case returns - §7",
        "",
        *md_table(
            ["Capital (USDT)", "40%", "50%"],
            [
                [
                    fmt_money(row["capital_usdt"]),
                    fmt_money(row["annual_net_profit"]["40%"]),
                    fmt_money(row["annual_net_profit"]["50%"]),
                ]
                for row in payload["high_risk_return_matrix"]
            ],
        ),
        "",
        "## Drawdown translation (USDT lost) - §13",
        "",
        *md_table(
            ["Capital (USDT)", "10%", "20%", "30%", "50%"],
            [
                [
                    fmt_money(row["capital_usdt"]),
                    *[fmt_money(row["loss_usdt"][k]) for k in ("10%", "20%", "30%", "50%")],
                ]
                for row in payload["drawdown_matrix"]
            ],
        ),
        "",
        "Every profit table is accompanied by the drawdown translation above.",
        "No figure here is guaranteed, expected or forecast.",
        "",
    ]
    return "\n".join(lines)


def profit_target_md(payload: dict[str, Any]) -> str:
    rates = [f"{r:.0%}" for r in pf.REQUIRED_CAPITAL_RATES]
    lines = [
        "# RFC-043 PROFIT TARGET MATRIX",
        "",
        "REQUIRED_CAPITAL = TARGET_ANNUAL_PROFIT / NET_RETURN. Illustrative only.",
        "",
        "## Required capital (USDT) - §52",
        "",
        *md_table(
            ["Target annual profit (USDT)", *rates],
            [
                [
                    fmt_money(row["target_annual_profit_usdt"]),
                    *[fmt_money(row["required_capital"][r]) for r in rates],
                ]
                for row in payload["profit_target_matrix"]
            ],
        ),
        "",
        "Small capital plus a reasonable return yields a small absolute profit.",
        "This is not a problem to solve with extreme leverage.",
        "",
    ]
    return "\n".join(lines)


def contributions_md(payload: dict[str, Any]) -> str:
    lines = [
        "# RFC-043 CAPITAL CONTRIBUTION SCENARIOS",
        "",
        "External contributions are never counted as trading profit (§19-§21).",
        "Trading growth is held at zero because no business edge exists yet; no",
        "deposit is assumed and no return is forecast (§22-§23).",
        "",
        *md_table(
            [
                "Monthly contribution (USDT)",
                "Annual contributions",
                "Growth from contributions",
                "Growth from trading",
                "Ending equity",
                "Realized trading PnL",
            ],
            [
                [
                    fmt_money(row["monthly_contribution_usdt"]),
                    fmt_money(row["annual_external_contributions_usdt"]),
                    fmt_money(row["growth_from_contributions_usdt"]),
                    fmt_money(row["growth_from_trading_usdt"]),
                    fmt_money(row["ending_equity_usdt"]),
                    fmt_money(row["realized_trading_pnl_usdt"]),
                ]
                for row in payload["rows"]
            ],
        ),
        "",
        "Equity identity: ENDING = STARTING + CONTRIBUTIONS + TRADING_PNL - WITHDRAWALS.",
        "No compounding to millions over decades is presented (§23).",
        "",
    ]
    return "\n".join(lines)


def tiers_md(payload: dict[str, Any]) -> str:
    lines = [
        "# RFC-043 CAPITAL TIER MODEL",
        "",
        "Conceptual ladder. No tier is authorized; scaling is not automatic (§15-§17).",
        "",
        *md_table(
            ["Tier", "Capital (USDT)", "Label", "Authorized"],
            [
                [
                    entry["tier"],
                    fmt_money(entry["capital_usdt"]),
                    entry["label"],
                    "NO",
                ]
                for entry in payload["capital_tiers"]
            ],
        ),
        "",
        "## G_CAPITAL_SCALE (future) - §18",
        "",
        *[f"- {c}" for c in payload["capital_scale_gate_conditions"]],
        "",
        "Scaling also requires a positive realized trading PnL (M5+). Research freeze",
        "stays ACTIVE and no tier is authorized today.",
        "",
    ]
    return "\n".join(lines)


def candidate_review_md(payload: dict[str, Any]) -> str:
    lines = ["# RFC-043 CANDIDATE CAPITAL REVIEW", "", "Capital growth never approves a strategy (§29-§34).", ""]
    for row in payload["rows"]:
        lines.append(f"## {row['candidate_id']} — {row['family']}")
        lines.append("")
        lines.append(f"- Capital fit at 200 USDT: {row['capital_fit_at_200']}")
        lines.append(f"- Capital requirement: {row['capital_requirement']}")
        lines.append(f"- Business edge: {row['business_edge']}")
        lines.append(f"- Does more capital help: {row['does_more_capital_help']}")
        lines.append(f"- Reentry condition: {row['reentry_condition']}")
        lines.append(f"- Note: {row['note']}")
        if row["product_fit_by_scale"]:
            lines.append("")
            lines.append("Product fit by scale (§31):")
            lines.append("")
            lines.extend(
                md_table(
                    ["Scale", "Product fit"],
                    [[s["scale"], s["product_fit"]] for s in row["product_fit_by_scale"]],
                )
            )
        lines.append("")
    lines.append("MORE CAPITAL MULTIPLIES EDGE; IT DOES NOT CREATE EDGE.")
    lines.append("")
    return "\n".join(lines)


def milestones_md(payload: dict[str, Any]) -> str:
    lines = [
        "# RFC-043 PROFITABILITY MILESTONES",
        "",
        f"Current milestone: {payload['current_milestone']} (§26).",
        "",
        *md_table(
            ["Milestone", "Meaning", "Reached"],
            [
                [m["milestone"], m["meaning"], "YES" if m["milestone"] == "M0" else "NO"]
                for m in payload["milestones"]
            ],
        ),
        "",
        "## Profit levels - §24",
        "",
        *[f"- **{k}**: {v}" for k, v in payload["profit_levels"].items()],
        "",
        "Milestones are sequential; none is advanced fictitiously.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# final report (§49-§50)
# --------------------------------------------------------------------------- #


def build_final_report(
    entry: dict[str, Any],
    scoreboard: dict[str, Any],
    scale: dict[str, Any],
    false_success: dict[str, Any],
    generated_at: str,
    verification: str,
) -> dict[str, Any]:
    return {
        "title": "RFC-043 CAPITAL SCALE & PROFITABILITY OPERATING MODEL",
        "generated_at": generated_at,
        "reference_capital_usdt": pf.REFERENCE_INITIAL_CAPITAL_USDT,
        "current_milestone": scoreboard["current_milestone"],
        "business_validated_edges": scoreboard["business_validated_edges"],
        "paper_candidates": scoreboard["paper_candidates"],
        "forward_profitable": scoreboard["forward_profitable"],
        "live_profitable": scoreboard["live_profitable"],
        "realized_trading_pnl": scoreboard["realized_trading_pnl"],
        "live_capital_authorized": scoreboard["live_capital_authorized"],
        "role_of_200_usdt": "FUTURE CANARY",
        "alpha_research_freeze": entry["alpha_research_freeze"],
        "next_alpha_rfc_allowed": NEXT_ALPHA_RFC_ALLOWED,
        "capital_scale_authorized": "NO" if not scale["capital_scale_authorized"] else "YES",
        "capital_tier": scoreboard["capital_tier"],
        "leverage_policy": pf.LEVERAGE_POLICY,
        "false_success": false_success["FALSE_SUCCESS"],
        "independent_verification": verification,
        "next": "WAIT FOR BUSINESS EDGE",
        "source_commit": entry["source_commit"],
        "final_commit": "",
    }


def final_report_md(
    report: dict[str, Any], capital_matrix: dict[str, Any], profit_targets: dict[str, Any]
) -> str:
    lines = [
        "RFC-043 CAPITAL SCALE & PROFITABILITY OPERATING MODEL",
        "",
        f"REFERENCE CAPITAL = {int(report['reference_capital_usdt'])} USDT",
        "",
        f"CURRENT MILESTONE = {report['current_milestone']}",
        "",
        f"BUSINESS VALIDATED EDGES = {report['business_validated_edges']}",
        "",
        f"PAPER CANDIDATES = {report['paper_candidates']}",
        "",
        f"FORWARD PROFITABLE = {report['forward_profitable']}",
        "",
        f"LIVE PROFITABLE = {report['live_profitable']}",
        "",
        f"REALIZED TRADING PNL = {report['realized_trading_pnl']}",
        "",
        f"LIVE CAPITAL AUTHORIZED = {report['live_capital_authorized']}",
        "",
        f"ROLE OF 200 USDT = {report['role_of_200_usdt']}",
        "",
        f"ALPHA RESEARCH FREEZE = {report['alpha_research_freeze']}",
        "",
        f"NEXT ALPHA RFC ALLOWED = {report['next_alpha_rfc_allowed']}",
        "",
        f"CAPITAL SCALE AUTHORIZED = {report['capital_scale_authorized']}",
        "",
        f"NEXT = {report['next']}",
        "",
        f"LEVERAGE POLICY = {report['leverage_policy']}",
        "",
        f"FALSE_SUCCESS = {report['false_success']}",
        "",
        f"INDEPENDENT VERIFICATION = {report['independent_verification']}",
        "",
        "## Annual net profit matrix (§51) — scenario arithmetic, not a forecast",
        "",
        *md_table(
            ["Capital (USDT)", "5%", "10%", "15%", "20%", "30%"],
            [
                [
                    fmt_money(row["capital_usdt"]),
                    fmt_money(row["annual_net_profit"]["5%"]),
                    fmt_money(row["annual_net_profit"]["10%"]),
                    fmt_money(row["annual_net_profit"]["15%"]),
                    fmt_money(row["annual_net_profit"]["20%"]),
                    fmt_money(row["annual_net_profit"]["30%"]),
                ]
                for row in capital_matrix["capital_return_matrix"]
                if float(row["capital_usdt"]) in pf.DISPLAY_CAPITAL_SCENARIOS
            ],
        ),
        "",
        "Every profit figure is accompanied by the drawdown translation to money",
        "(see CAPITAL_RETURN_MATRIX / DRAWDOWN_MATRIX); no figure is guaranteed.",
        "",
        "## Required capital for a profit target (§52)",
        "",
        *md_table(
            ["Target annual profit (USDT)", "@10%", "@15%", "@20%"],
            [
                [
                    fmt_money(row["target_annual_profit_usdt"]),
                    fmt_money(row["required_capital"]["10%"]),
                    fmt_money(row["required_capital"]["15%"]),
                    fmt_money(row["required_capital"]["20%"]),
                ]
                for row in profit_targets["profit_target_matrix"]
            ],
        ),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def false_success_audit(scale: dict[str, Any], report_language: str) -> dict[str, Any]:
    claims = {
        "scenario_called_forecast": any(
            phrase in report_language for phrase in FORBIDDEN_FORECAST_PHRASES
        ),
        "deposit_called_trading_profit": False,
        "capital_increase_treated_as_alpha": False,
        "leverage_proposed_to_solve_low_capital": False,
        "live_capital_authorized": float(pf.LIVE_CAPITAL_AUTHORIZED_USDT) > 0.0,
        "new_strategy_created": False,
        "research_freeze_released": False,
        "old_failed_candidate_promoted": False,
    }
    return {
        "triggers": list(pf.FALSE_SUCCESS_TRIGGERS),
        "claims": claims,
        "FALSE_SUCCESS": pf.false_success_count(claims),
        "capital_scale_authorized": scale["capital_scale_authorized"],
    }


def main() -> int:
    generated_at = now_utc()
    entry = entry_gate()
    if not entry["entry_condition_met"]:
        print(
            json.dumps(
                {
                    "ENTRY_GATE": "FAIL",
                    "reason": "hard rule §2 or ancestor check failed",
                    "entry_gate": entry,
                },
                indent=2,
            )
        )
        return 2

    current = pf.current_milestone(
        business_validated_edges=entry["business_validated_edge_count"],
        paper_execution_pass=False,
        forward_evidence_pass=False,
        canary_deployed=False,
        realized_net_pnl_positive=False,
        capital_scaled_once=False,
        repeated_profitability=False,
        economically_meaningful_pnl=False,
    )
    scale = pf.capital_scale_decision(
        conditions=dict.fromkeys(pf.G_CAPITAL_SCALE_CONDITIONS, False),
        current_milestone_name=current,
    )
    scoreboard = build_scoreboard(generated_at)

    capital_matrix = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "reference_capital_usdt": pf.REFERENCE_INITIAL_CAPITAL_USDT,
        "capital_return_matrix": capital_return_matrix(),
        "high_risk_return_matrix": high_risk_return_matrix(),
        "drawdown_matrix": drawdown_matrix(),
        "risk_return_matrix": risk_return_matrix(),
        "note": "scenarios, never forecasts",
    }
    profit_targets = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "required_capital_rates": [f"{r:.0%}" for r in pf.REQUIRED_CAPITAL_RATES],
        "profit_target_matrix": profit_target_matrix(),
    }
    drawdown = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "drawdown_scenarios": [f"{d:.0%}" for d in pf.DRAWDOWN_SCENARIOS],
        "drawdown_matrix": drawdown_matrix(),
        "risk_return_matrix": risk_return_matrix(),
        "note": "every profit table is accompanied by capital-loss translation",
    }
    contributions = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "starting_equity_usdt": pf.REFERENCE_INITIAL_CAPITAL_USDT,
        "equity_identity": "ENDING = STARTING + CONTRIBUTIONS + TRADING_PNL - WITHDRAWALS",
        "rows": contribution_scenarios(),
        "note": "deposits are never trading profit; trading growth stays zero without an edge",
    }
    tiers = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "capital_tiers": [dict(t) for t in pf.CAPITAL_TIERS],
        "any_tier_authorized": pf.ANY_TIER_AUTHORIZED,
        "capital_scale_gate_conditions": list(pf.G_CAPITAL_SCALE_CONDITIONS),
        "capital_scale_decision": scale,
        "leverage_policy": pf.LEVERAGE_POLICY,
        "note": "no automatic scale; each step needs evidence, risk decision and human approval",
    }
    candidate_review = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "capital_is_not_alpha": pf.CAPITAL_IS_NOT_ALPHA,
        "rows": [dict(r) for r in CANDIDATE_CAPITAL_REVIEW],
        "note": "capital growth triggers a PRODUCT_FIT_REVIEW, never an automatic approval",
    }
    milestones = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "current_milestone": current,
        "milestones": [{"milestone": m, "meaning": pf.MILESTONE_MEANING[m]} for m in pf.MILESTONES],
        "profit_levels": dict(pf.PROFIT_LEVELS),
        "official_sequence": list(pf.OFFICIAL_SEQUENCE),
        "priority_order": list(pf.PRIORITY_ORDER),
    }
    model = build_model_payload(generated_at)

    write_json(OUT / "RFC043_PLAN.json", build_plan(entry, generated_at))
    write_md(
        OUT / "RFC043_PLAN.md",
        render("RFC-043 PLAN — CAPITAL SCALE & PROFITABILITY OPERATING MODEL", build_plan(entry, generated_at)),
    )

    write_json(OUT / "CAPITAL_RETURN_MATRIX.json", capital_matrix)
    write_md(OUT / "CAPITAL_RETURN_MATRIX.md", capital_profit_matrix_md(capital_matrix))

    write_json(OUT / "PROFIT_TARGET_MATRIX.json", profit_targets)
    write_md(OUT / "PROFIT_TARGET_MATRIX.md", profit_target_md(profit_targets))

    write_json(OUT / "DRAWDOWN_MATRIX.json", drawdown)
    write_md(
        OUT / "DRAWDOWN_MATRIX.md",
        render("RFC-043 DRAWDOWN MATRIX", drawdown),
    )

    write_json(OUT / "CAPITAL_CONTRIBUTION_SCENARIOS.json", contributions)
    write_md(OUT / "CAPITAL_CONTRIBUTION_SCENARIOS.md", contributions_md(contributions))

    write_json(OUT / "CAPITAL_TIER_MODEL.json", tiers)
    write_md(OUT / "CAPITAL_TIER_MODEL.md", tiers_md(tiers))

    write_json(OUT / "CANDIDATE_CAPITAL_REVIEW.json", candidate_review)
    write_md(OUT / "CANDIDATE_CAPITAL_REVIEW.md", candidate_review_md(candidate_review))

    write_json(OUT / "PROFITABILITY_MILESTONES.json", milestones)
    write_md(OUT / "PROFITABILITY_MILESTONES.md", milestones_md(milestones))

    verification_doc = {
        "rfc": "RFC-043",
        "generated_at": generated_at,
        "VERIFICATION_STATUS": "PENDING",
        "mismatch_count": None,
        "false_success": 0,
    }
    write_json(OUT / "RFC043_VERIFICATION.json", verification_doc)
    write_md(OUT / "RFC043_VERIFICATION.md", render("RFC-043 VERIFICATION", verification_doc))

    # -- tracked canonical documents (§42/§44/§45/§46) ------------------------- #
    write_json(DOCS / "PROFITABILITY_OPERATING_SCOREBOARD.json", scoreboard)
    write_md(
        DOCS / "PROFITABILITY_OPERATING_SCOREBOARD.md",
        render("PROFITABILITY OPERATING SCOREBOARD", scoreboard),
    )

    write_json(DOCS / "CAPITAL_PROFIT_MATRIX.json", capital_matrix)
    write_md(DOCS / "CAPITAL_PROFIT_MATRIX.md", capital_profit_matrix_md(capital_matrix))

    write_json(DOCS / "CAPITAL_SCALE_PLAN.json", {**tiers, **milestones})
    write_md(
        DOCS / "CAPITAL_SCALE_PLAN.md",
        render("CAPITAL SCALE PLAN", {**tiers, **milestones}),
    )

    write_json(DOCS / "PROFITABILITY_OPERATING_MODEL.json", model)
    write_md(
        DOCS / "PROFITABILITY_OPERATING_MODEL.md",
        render("PROFITABILITY OPERATING MODEL", model),
    )

    pending_report = build_final_report(
        entry, scoreboard, scale, {"FALSE_SUCCESS": 0}, generated_at, "PENDING"
    )
    report_language = " ".join(
        [
            final_report_md(pending_report, capital_matrix, profit_targets),
            render("model", model),
            capital_profit_matrix_md(capital_matrix),
        ]
    ).lower()
    false_success = false_success_audit(scale, report_language)

    report = build_final_report(entry, scoreboard, scale, false_success, generated_at, "PENDING")
    write_json(REPORTS / "RFC043_FINAL_REPORT.json", report)
    write_md(REPORTS / "RFC043_FINAL_REPORT.md", final_report_md(report, capital_matrix, profit_targets))

    print(
        json.dumps(
            {
                "entry_condition_met": entry["entry_condition_met"],
                "current_milestone": current,
                "capital_scale_authorized": scale["capital_scale_authorized"],
                "next_alpha_rfc_allowed": NEXT_ALPHA_RFC_ALLOWED,
                "FALSE_SUCCESS": false_success["FALSE_SUCCESS"],
                "next": "WAIT FOR BUSINESS EDGE",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
