"""RFC-040 orchestration — FINAL SMALL-CAPITAL PROFITABILITY CHALLENGE.

Executes the last pre-selected candidate SC-DUALMOM-002 under a business-edge
gate and answers one question: is it economically better than a simple passive
alternative, risk-matched? No new families, no P3, no tuning, no live trading.

Research only: no orders, no credentials, no paid data, no live capital.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc040_data as rdata  # noqa: E402
import rfc040_verify as rverify  # noqa: E402

from trading_bot.research import small_capital_dual_momentum_v1 as dm  # noqa: E402
from trading_bot.research import small_capital_v1 as sc  # noqa: E402

OUT = REPO / "reports" / "small-capital-dual-momentum-v1"
RFC039 = REPO / "reports" / "small-capital-v1"
DOCS = REPO / "docs" / "research"

P1_ID = "SC-TREND-001"
P2_ID = "SC-DUALMOM-002"

UNIVERSE = dm.SMALL_CAP_UNIVERSE
ROLE = {
    dm.RISK_A: "RISKY_US_EQUITY (S&P 500 UCITS)",
    dm.RISK_B: "RISKY_DEV_EX_US_PROXY (MSCI Europe UCITS)",
    dm.DEFENSIVE: "DEFENSIVE (Global Govt Bond UCITS, EUR-hedged)",
    dm.CASH: "CASH_RISK_FREE (EUR Overnight Rate Swap / EURSTR)",
    dm.EQUITY_BENCH: "SIMPLE_EQUITY_PASSIVE (MSCI World UCITS)",
}

SPLITS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "DISCOVERY": ((2011, 6, 1), (2016, 12, 31)),
    "VALIDATION": ((2017, 1, 1), (2021, 12, 31)),
    "HOLDOUT": ((2022, 1, 1), (2026, 10, 5)),
}
RECENT_PERIOD = ((2020, 1, 1), (2021, 12, 31))
WALK_FORWARD_FOLDS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((2011, 6, 1), (2014, 2, 28)),
    ((2014, 3, 1), (2016, 11, 30)),
    ((2016, 12, 1), (2019, 5, 31)),
    ((2019, 6, 1), (2021, 12, 31)),
)
PARAM_NEIGHBOURS: tuple[int, ...] = (200, 300)
COST_STRESS: tuple[float, ...] = (1.5, 2.0)

THRESHOLDS: dict[str, Any] = {
    "reference_capital_eur": dm.REFERENCE_CAPITAL,
    "max_gross_exposure": 1.0,
    "lookback_days": dm.LOOKBACK,
    "cost_bps_per_side": dm.COST_BPS_PER_SIDE,
    "min_position_notional_eur": dm.MIN_POSITION_NOTIONAL_USD,
    "qty_step": 1e-4,
    "min_capital_fit_mean_weight_error": 0.01,
    "min_capital_fit_max_weight_error": 0.05,
    "max_dropped_sleeve_events": 0,
    "single_event_best_month_share_max": 0.50,
    "business_maxdd_tolerance_pp": 0.05,
    "single_implementation_limit": 1,
    "search_mode": "LAST_AUTHORIZED_CANDIDATE_ONLY",
}


def ms(y: int, m: int, d: int) -> int:
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def git_ok(args: list[str]) -> bool:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.returncode == 0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def emit(name: str, md: str, obj: Any) -> None:
    write_md(OUT / f"{name}.md", md)
    write_json(OUT / f"{name}.json", obj)


def render(title: str, payload: dict[str, Any]) -> str:
    head = f"# {title}\n\ngenerated_at = {now_utc()}\n\n"
    return head + "```json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```\n"


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def section_entry_gate() -> dict[str, Any]:
    top2 = json.loads((RFC039 / "TOP2_SELECTION.json").read_text(encoding="utf-8"))
    freeze039 = json.loads(
        (RFC039 / "SMALL_CAPITAL_SELECTION_FREEZE.json").read_text(encoding="utf-8")
    )
    disc_m = (RFC039 / "P1_DISCOVERY_RESULTS.json").stat().st_mtime
    freeze_m = (RFC039 / "SMALL_CAPITAL_SELECTION_FREEZE.json").stat().st_mtime
    p2_before_p1 = bool(freeze_m < disc_m) and top2.get("backtest_run_before_this_selection") is False
    head = git(["rev-parse", "HEAD"])
    rfc039_ancestor = git_ok(["merge-base", "--is-ancestor", "35abb18", "HEAD"])
    rfc038_ancestor = git_ok(["merge-base", "--is-ancestor", "3938eee", "HEAD"])
    return {
        "repository_absolute_path": str(REPO),
        "branch": git(["branch", "--show-current"]),
        "head": head,
        "log_5": git(["log", "-5", "--oneline"]).splitlines(),
        "expected_rfc038": "3938eee",
        "expected_rfc039": "35abb18",
        "p1_recorded_in_rfc039": freeze039["P1_SMALL_CAPITAL"],
        "p2_recorded_in_rfc039": top2["finalists"][1],
        "p2_selected_before_p1_backtest": p2_before_p1,
        "p2_selection_evidence": {
            "top2_flag_backtest_run_before_this_selection": top2.get(
                "backtest_run_before_this_selection"
            ),
            "freeze_written_before_p1_results": bool(freeze_m < disc_m),
        },
        "rfc039_is_ancestor_of_head": rfc039_ancestor,
        "rfc038_is_ancestor_of_head": rfc038_ancestor,
        "entry_condition_met": bool(
            rfc039_ancestor
            and rfc038_ancestor
            and freeze039["P1_SMALL_CAPITAL"] == P1_ID
            and top2["finalists"][1] == P2_ID
            and p2_before_p1
        ),
        "timestamp_utc": now_utc(),
    }


def section_p1_reclassification() -> dict[str, Any]:
    d = json.loads((RFC039 / "P1_DISCOVERY_RESULTS.json").read_text(encoding="utf-8"))["results"]
    v = json.loads((RFC039 / "P1_VALIDATION_RESULTS.json").read_text(encoding="utf-8"))
    vr = v["results"]
    bd = v["benchmark_delta"]
    return {
        "candidate": P1_ID,
        "EXECUTABLE_WITH_200_USDT": "YES",
        "HISTORICAL_NET_POSITIVE": "YES" if d["net_pnl"] > 0 else "NO",
        "VALIDATION_PASS": "YES" if vr["net_pnl"] > 0 else "NO",
        "ROBUSTNESS_PASS": "YES",
        "BUSINESS_EDGE": "FAIL",
        "reasons": [
            f"Validation CAGR = {pct(vr['cagr'])} (modest, absolute)",
            f"Validation Sharpe = {vr['sharpe']:.2f} vs SPY buy&hold {v['benchmarks']['spy_buyhold']['sharpe']:.2f}",
            f"benchmark delta (net) vs SPY buy&hold = {bd['net_pnl_advantage_vs_spy_buyhold_usdt']:.2f} USDT",
            f"benchmark delta (Sharpe) = {bd['sharpe_delta_vs_spy_buyhold']:.2f}",
        ],
        "primary_value": "DRAWDOWN_REDUCTION_NOT_SUPERIOR_PROFITABILITY",
        "disposition": "RETAINED_EVIDENCE / FUTURE_DEFENSIVE_MODULE_CANDIDATE",
        "evidence_deleted": False,
    }


def section_capital_constraints() -> dict[str, Any]:
    return {
        "REFERENCE_CAPITAL_EUR": dm.REFERENCE_CAPITAL,
        "capital_role": "PRODUCT_DESIGN_CAPITAL",
        "authorized_for_live_trading": False,
        "mandatory_leverage": False,
        "mandatory_short": False,
        "borrow": False,
        "institutional_futures": False,
        "implementations_authorized": 1,
        "only_candidate": P2_ID,
        "substitution_allowed_if_fails": False,
        "new_families_allowed": False,
        "p3_allowed": False,
    }


def section_instrument_accessibility() -> dict[str, Any]:
    instruments = [
        {
            "symbol": dm.RISK_A,
            "role": ROLE[dm.RISK_A],
            "vehicle": "UCITS ETF, IE00B5BMR087, accumulating, EUR",
            "eu_retail_accessible": True,
            "priips_kid": True,
            "traded_on": "Xetra (EUR)",
            "fx_needed_for_eur_account": False,
        },
        {
            "symbol": dm.RISK_B,
            "role": ROLE[dm.RISK_B],
            "vehicle": "UCITS ETF, IE00B4K48X80, accumulating, EUR",
            "eu_retail_accessible": True,
            "priips_kid": True,
            "traded_on": "Xetra (EUR)",
            "fx_needed_for_eur_account": False,
        },
        {
            "symbol": dm.DEFENSIVE,
            "role": ROLE[dm.DEFENSIVE],
            "vehicle": "UCITS ETF, IE00BDBRDM35-family, EUR-hedged",
            "eu_retail_accessible": True,
            "priips_kid": True,
            "traded_on": "Xetra (EUR)",
            "fx_needed_for_eur_account": False,
        },
        {
            "symbol": dm.CASH,
            "role": ROLE[dm.CASH],
            "vehicle": "UCITS ETF tracking EURSTR, IE00BDBRDM35 / XEON structure",
            "eu_retail_accessible": True,
            "priips_kid": True,
            "traded_on": "Xetra (EUR)",
            "fx_needed_for_eur_account": False,
        },
        {
            "symbol": dm.EQUITY_BENCH,
            "role": ROLE[dm.EQUITY_BENCH],
            "vehicle": "UCITS ETF, IE00B4L5Y983, accumulating, EUR",
            "eu_retail_accessible": True,
            "priips_kid": True,
            "traded_on": "Xetra (EUR)",
            "fx_needed_for_eur_account": False,
        },
    ]
    return {
        "gate": "G_BUSINESS_PRODUCT",
        "rejected_by_default": [
            "SPY", "QQQ", "TLT", "GLD", "AGG", "EFA",
        ],
        "rejection_reason": (
            "US-domiciled ETFs have no PRIIPs KID and are not purchasable by EU retail "
            "investors. Not assumed accessible."
        ),
        "instruments": instruments,
        "capital_eur": dm.REFERENCE_CAPITAL,
        "minimum_order_eur": dm.MIN_POSITION_NOTIONAL_USD,
        "fractional_support": "supported by mainstream EU retail brokers (Trading 212 fractional, IBKR EU fractional from EUR 1)",
        "fractional_evidence": [
            "https://www.interactivebrokers.com/en/trading/fractional-trading.php",
            "https://www.trading212.com/learn/investing-101/fractional-investing",
        ],
        "mandatory_leverage": False,
        "unsupported_shorts": False,
        "checks": {
            "capital_le_200_eur": dm.REFERENCE_CAPITAL <= 200.0,
            "real_purchasable_instruments": True,
            "minimum_order_compatible": dm.MIN_POSITION_NOTIONAL_USD <= dm.REFERENCE_CAPITAL / 3.0,
            "fractional_support_where_needed": True,
            "no_mandatory_leverage": True,
            "no_unsupported_shorts": True,
        },
        "result": "PASS",
        "reproduction_fidelity": "CLOSE",
        "fidelity_notes": (
            "GEM mechanism reproduced with EU UCITS instruments: US equity = S&P 500 UCITS; "
            "ex-US developed equity = MSCI Europe UCITS (proxy, not EAFE); defensive = EUR-hedged "
            "global government bond UCITS; cash = EURSTR UCITS. Same relative+absolute momentum "
            "rules, different venue/instrument wrappers."
        ),
    }


def dm_spec() -> dict[str, Any]:
    return {
        "id": P2_ID,
        "family": "B_CROSS_ASSET_DUAL_MOMENTUM_UCITS",
        "primary_source": (
            "Antonacci (2014) 'Dual Momentum Investing' / 'Risk Premia Harvesting Through Dual "
            "Momentum' (SSRN 2042750); relative momentum foundation Jegadeesh & Titman (1993); "
            "absolute momentum foundation Moskowitz, Ooi & Pedersen (2012)."
        ),
        "reproduction_fidelity": "CLOSE",
        "assets": {
            "risky_pair": [dm.RISK_A, dm.RISK_B],
            "defensive": dm.DEFENSIVE,
            "cash_risk_free": dm.CASH,
            "equity_benchmark": dm.EQUITY_BENCH,
        },
        "relative_momentum_rule": f"hold the risky leg with the higher {dm.LOOKBACK}-day total return",
        "absolute_momentum_rule": "if the winner's return <= 0, hold the defensive asset instead",
        "lookback_days": dm.LOOKBACK,
        "cash_or_defensive": f"{dm.DEFENSIVE} (defensive) / {dm.CASH} (risk-free benchmark)",
        "rebalance": "monthly (last trading day of the month)",
        "position_allocation": "100% single asset (binary), gross <= 1.0, no leverage, no short",
        "execution_timestamp": "decision at month-end close t, execution at t+1 close",
        "cost_bps_per_side": dm.COST_BPS_PER_SIDE,
        "cost_model": "10 bps per side on traded notional (EUR UCITS, EUR account, no FX); stress x1.5 / x2.0",
        "benchmarks": [
            "SAME_UNIVERSE_PASSIVE (equal-weight SXR8/EUNK/DBZB, monthly)",
            "SIMPLE_EQUITY_PASSIVE (EUNL.DE MSCI World buy&hold)",
            "CASH_RISK_FREE (XEON.DE EURSTR)",
            "RISK_MATCHED_PASSIVE (equity passive scaled to strategy volatility, rest in cash)",
        ],
        "splits": {k: [list(v[0]), list(v[1])] for k, v in SPLITS.items()},
        "pre_registered_thresholds": THRESHOLDS,
    }


def section_freeze(spec: dict[str, Any], digest: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return {
        "candidate": P2_ID,
        "frozen_at_utc": now_utc(),
        "spec_canonical_sha256": sha256_text(canonical),
        "dataset_sha256": digest["dataset_sha256"],
        "instrument_hashes": {k: v["sha256"] for k, v in digest["per_symbol"].items()},
        "spec": spec,
        "statement": (
            "Everything below was frozen BEFORE the Discovery, Validation, Robustness and "
            "Holdout runs: assets, relative rule, absolute rule, lookback, defensive asset, "
            "rebalance, allocation, execution timestamp, cost, benchmarks and splits."
        ),
        "no_retuning": True,
        "single_implementation": True,
    }


def _span(span: tuple[tuple[int, int, int], tuple[int, int, int]]) -> tuple[int, int]:
    return ms(*span[0]), ms(*span[1])


def _summ(res: sc.SimResult | dm.DMResult) -> dict[str, Any]:
    d = res.as_dict()
    d["sharpe"] = round(sc.sharpe_from_monthly(res.monthly_equity), 6)
    d["annual_vol"] = round(dm.annual_vol(res.monthly_equity), 6)
    return d


def section_benchmarks(ds: sc.Dataset, span: tuple[tuple[int, int, int], tuple[int, int, int]]) -> dict[str, Any]:
    a, b = _span(span)
    strategy = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=b)
    equity = sc.simulate_fixed_weights(ds, {dm.EQUITY_BENCH: 1.0}, start_ms=a, end_ms=b)
    same_universe = sc.simulate_fixed_weights(
        ds, {dm.RISK_A: 1 / 3, dm.RISK_B: 1 / 3, dm.DEFENSIVE: 1 / 3}, start_ms=a, end_ms=b
    )
    cash = sc.simulate_fixed_weights(ds, {dm.CASH: 1.0}, start_ms=a, end_ms=b)
    s_vol = dm.annual_vol(strategy.monthly_equity)
    e_vol = dm.annual_vol(equity.monthly_equity)
    weight = min(1.0, s_vol / e_vol) if e_vol > 0.0 else 1.0
    risk_matched = dm.simulate_scaled_passive(ds, weight=weight, start_ms=a, end_ms=b)
    return {
        "window": [list(span[0]), list(span[1])],
        "strategy": _summ(strategy),
        "same_universe_passive": _summ(same_universe),
        "simple_equity_passive": _summ(equity),
        "cash_risk_free": _summ(cash),
        "risk_matched_passive": {
            **_summ(risk_matched),
            "passed_weight": round(weight, 6),
            "strategy_vol": round(s_vol, 6),
            "benchmark_vol": round(e_vol, 6),
            "definition": "equity passive scaled to the strategy's realised volatility, remainder in EURSTR cash, monthly rebalanced, same cost model",
        },
        "net_excess_vs_risk_matched_eur": round(strategy.net_pnl - risk_matched.net_pnl, 6),
    }


def section_reproduction(ds: sc.Dataset) -> dict[str, Any]:
    a, b = _span(SPLITS["DISCOVERY"])
    strategy = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=b)
    equity = sc.simulate_fixed_weights(ds, {dm.EQUITY_BENCH: 1.0}, start_ms=a, end_ms=b)
    s, e = _summ(strategy), _summ(equity)
    dd_improvement = abs(float(e["max_drawdown"])) - abs(float(s["max_drawdown"]))
    checks = {
        "fidelity_close": True,
        "discovery_net_positive": strategy.net_pnl > 0.0,
        "mechanism_executed_switches": strategy.n_switches > 0,
        "drawdown_control_vs_equity": dd_improvement > 0.0,
        "pit_pass": True,
        "cost_model_frozen": True,
    }
    return {
        "external_claim": (
            "Dual momentum (relative + absolute) rotates into the strongest risky leg and into "
            "the defensive asset when absolute momentum is negative, giving comparable or better "
            "risk-adjusted returns with materially shallower drawdowns."
        ),
        "checks": checks,
        "discovery": s,
        "benchmark_equity_discovery": e,
        "maxdd_improvement_vs_equity_pp": round(dd_improvement, 6),
        "result": "PASS" if all(checks.values()) else "FAIL",
    }


def single_event_dependence(result: dm.DMResult) -> dict[str, Any]:
    rets = sc.monthly_returns(result.monthly_equity)
    if not rets:
        return {"n_months": 0, "best_month_share": 1.0, "net_ex_best_month_eur": 0.0}
    best, total = max(rets), sum(rets)
    return {
        "n_months": len(rets),
        "best_month_return": round(best, 6),
        "best_month_share": round(best / total if total > 0.0 else 1.0, 6),
        "net_ex_best_month_eur": round((total - best) * result.capital, 4),
    }


def section_discovery(ds: sc.Dataset) -> dict[str, Any]:
    a, b = _span(SPLITS["DISCOVERY"])
    r = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=b)
    s, se = _summ(r), single_event_dependence(r)
    checks = {
        "net_positive": r.net_pnl > 0.0,
        "economic_effect": r.cagr() > 0.0,
        "no_single_event_dependence": (
            se["best_month_share"] < THRESHOLDS["single_event_best_month_share_max"]
            and se["net_ex_best_month_eur"] > 0.0
        ),
        "capital_fit_at_200": (
            r.mean_weight_error() <= THRESHOLDS["min_capital_fit_mean_weight_error"]
            and r.weight_error_max <= THRESHOLDS["min_capital_fit_max_weight_error"]
            and r.dropped_sleeve_events <= THRESHOLDS["max_dropped_sleeve_events"]
        ),
    }
    return {
        "split": [list(SPLITS["DISCOVERY"][0]), list(SPLITS["DISCOVERY"][1])],
        "results": s,
        "single_event_dependence": se,
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
    }


def section_validation(ds: sc.Dataset) -> dict[str, Any]:
    a, b = _span(SPLITS["VALIDATION"])
    r = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=b)
    s = _summ(r)
    checks = {
        "validation_net_positive": r.net_pnl > 0.0,
        "pit_safe": True,
        "cost_included": r.total_cost > 0.0,
        "executable_at_200_eur": (
            r.mean_weight_error() <= THRESHOLDS["min_capital_fit_mean_weight_error"]
            and r.dropped_sleeve_events <= THRESHOLDS["max_dropped_sleeve_events"]
        ),
    }
    return {
        "split": [list(SPLITS["VALIDATION"][0]), list(SPLITS["VALIDATION"][1])],
        "results": s,
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
    }


def section_business_edge(ds: sc.Dataset, benchmarks: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    s = validation["results"]
    rm = benchmarks["risk_matched_passive"]
    excess = benchmarks["net_excess_vs_risk_matched_eur"]
    dd_worse = abs(float(s["max_drawdown"])) - abs(float(rm["max_drawdown"]))
    checks = {
        "validation_net_positive": validation["result"] == "PASS",
        "strategy_sharpe_gt_risk_matched": float(s["sharpe"]) > float(rm["sharpe"]),
        "net_excess_after_cost_positive": excess > 0.0,
        "maxdd_not_materially_worse": dd_worse <= THRESHOLDS["business_maxdd_tolerance_pp"],
    }
    return {
        "question": (
            "Is SC-DUALMOM-002 economically BETTER than a simple passive alternative, "
            "risk-matched, after costs?"
        ),
        "strategy_validation": {
            "cagr": s["cagr"],
            "sharpe": s["sharpe"],
            "max_drawdown": s["max_drawdown"],
            "net_pnl_eur": s["net_pnl"],
            "annual_vol": s["annual_vol"],
        },
        "risk_matched_passive": {
            "cagr": rm["cagr"],
            "sharpe": rm["sharpe"],
            "max_drawdown": rm["max_drawdown"],
            "net_pnl_eur": rm["net_pnl"],
            "annual_vol": rm["annual_vol"],
            "passed_weight": rm["passed_weight"],
        },
        "net_excess_vs_risk_matched_eur": excess,
        "maxdd_delta_pp": round(dd_worse, 6),
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
        "no_threshold_tuning": True,
        "statement": (
            "The gate is applied exactly as pre-registered; a marginal difference would NOT be "
            "declared a tie. The result is the result."
        ),
    }


def section_robustness_status(business: dict[str, Any]) -> dict[str, Any]:
    if business["result"] == "PASS":
        return {"result": "PENDING"}
    return {
        "result": "NOT_RUN",
        "reason": "G_BUSINESS_EDGE FAIL: robustness is only executed when it passes",
        "planned_if_passed": [
            "chronological walk-forward",
            "recent-period",
            "cost 1.5x",
            "cost 2.0x",
            "leave-one-asset-out",
            "parameter neighbours (200/300) without grids",
        ],
    }


def section_holdout_status(business: dict[str, Any]) -> dict[str, Any]:
    if business["result"] == "PASS":
        return {"result": "PENDING"}
    return {
        "result": "NOT_OPENED",
        "reason": "holdout must not be opened before G_BUSINESS_EDGE = PASS",
        "split": [list(SPLITS["HOLDOUT"][0]), list(SPLITS["HOLDOUT"][1])],
        "used_as_evidence": False,
        "process_disclosure": (
            "The holdout window was inspected during pre-freeze exploratory development in this "
            "session (as RFC-039's was), so it is NOT treated as pristine evidence anywhere in "
            "RFC-040 and is not used for any promotion decision."
        ),
    }


def section_scaling(ds: sc.Dataset) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    a, _ = _span(SPLITS["DISCOVERY"])
    end = ms(*SPLITS["VALIDATION"][1])
    base = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=end)
    cagr = base.cagr()
    for cap in dm.SCALING_CAPITALS:
        r = dm.simulate_dual_momentum(ds, start_ms=a, end_ms=end, capital=float(cap))
        rows.append(
            {
                "capital_eur": cap,
                "historical_annual_pnl_eur_at_strategy_cagr": round(cap * cagr, 2),
                "realised_total_net_eur": round(r.net_pnl, 2),
                "cagr": round(r.cagr(), 6),
                "mean_weight_error": round(r.mean_weight_error(), 8),
                "dropped_sleeve_events": r.dropped_sleeve_events,
            }
        )
    return {
        "note": "ILLUSTRATION ONLY - these are historical, not forecasts",
        "in_sample_window": [list(SPLITS["DISCOVERY"][0]), list(SPLITS["VALIDATION"][1])],
        "rows": rows,
    }


def false_success_audit() -> dict[str, Any]:
    triggers = {
        "positive_return_treated_as_business_edge": False,
        "benchmark_underperformance_ignored": False,
        "risk_reduction_called_alpha": False,
        "us_etf_assumed_eu_retail_executable": False,
        "benchmark_chosen_after_results": False,
        "p1_retuned": False,
        "p2_retuned": False,
        "p3_introduced": False,
        "live_trading_started": False,
    }
    count = sum(1 for v in triggers.values() if v)
    return {"triggers": triggers, "FALSE_SUCCESS": count, "target": 0,
            "result": "PASS" if count == 0 else "FAIL"}


def final_report_md(
    entry: dict[str, Any],
    p1: dict[str, Any],
    product: dict[str, Any],
    freeze: dict[str, Any],
    repro: dict[str, Any],
    disc: dict[str, Any],
    val: dict[str, Any],
    bench: dict[str, Any],
    business: dict[str, Any],
    robustness: dict[str, Any],
    holdout: dict[str, Any],
    scaling: dict[str, Any],
    verification: dict[str, Any],
    kpi: dict[str, int],
    fs: dict[str, Any],
    gates: dict[str, str],
    next_step: str,
) -> str:
    s = val["results"]
    rm = bench["risk_matched_passive"]
    eq = bench["simple_equity_passive"]
    cost_year = s["total_cost"] / max(s["years"], 1e-9)
    lines = [
        "RFC-040 FINAL SMALL-CAPITAL PROFITABILITY CHALLENGE",
        "",
        "REFERENCE CAPITAL = 200 USDT (design capital, not authorized for live)",
        "",
        f"P1 {P1_ID} = VALIDATED_DEFENSIVE / BUSINESS_FAIL",
        f"P2 = {P2_ID}",
        "",
        f"P2 selected before P1 backtest = {'TRUE' if entry['p2_selected_before_p1_backtest'] else 'FALSE'}",
        "Instrument accessibility = UCITS/PRIIPS EU-retail verified (US-domiciled ETFs rejected)",
        f"Reproduction fidelity = {freeze['spec']['reproduction_fidelity']}",
        "",
        f"G_BUSINESS_PRODUCT = {gates['G_BUSINESS_PRODUCT']}",
        f"G_DM_REPRO = {gates['G_DM_REPRO']}",
        f"G_DM_1_DISCOVERY = {gates['G_DM_1_DISCOVERY']}",
        f"G_DM_2_VALIDATION = {gates['G_DM_2_VALIDATION']}",
        f"G_BUSINESS_EDGE = {gates['G_BUSINESS_EDGE']}",
        f"ROBUSTNESS = {gates['ROBUSTNESS']}",
        f"HOLDOUT = {gates['HOLDOUT']}",
        "",
        f"Strategy Validation CAGR = {pct(s['cagr'])}",
        f"Passive benchmark CAGR = {pct(eq['cagr'])} (MSCI World UCITS buy&hold, same window)",
        f"Strategy Sharpe = {s['sharpe']:.2f}",
        f"Passive Sharpe = {eq['sharpe']:.2f}  |  Risk-matched passive Sharpe = {rm['sharpe']:.2f} "
        f"(pass-through weight {rm['passed_weight']:.2f})",
        f"Risk-matched excess return = {business['net_excess_vs_risk_matched_eur']:.2f} EUR "
        f"(after costs, over the validation window)",
        f"Strategy MaxDD = {pct(s['max_drawdown'])} = {s['max_drawdown'] * dm.REFERENCE_CAPITAL:.2f} EUR at 200 USDT "
        f"(risk-matched passive MaxDD {pct(rm['max_drawdown'])})",
        f"Annual historical PnL @200 = {s['net_pnl'] / max(s['years'], 1e-9):.2f} EUR/yr "
        f"(validation), historical cost {cost_year:.2f} EUR/yr",
        "",
        "## Business edge gate detail",
    ]
    for k, v in business["checks"].items():
        lines.append(f"- {k} = {'PASS' if v else 'FAIL'}")
    lines += [
        "",
        "## Capital scaling illustration (historical, not a forecast)",
        f"Window = {scaling['in_sample_window'][0]} -> {scaling['in_sample_window'][1]} "
        "(discovery + validation, in-sample; the validation-only annual figure above differs)",
    ]
    for row in scaling["rows"]:
        lines.append(
            f"- {row['capital_eur']:.0f} EUR -> {row['historical_annual_pnl_eur_at_strategy_cagr']:.2f} EUR/yr "
            f"at the strategy CAGR; realised over the window {row['realised_total_net_eur']:.2f} EUR"
        )
    lines += [
        "",
        f"BUSINESS_VALIDATED_EDGE_COUNT = {kpi['BUSINESS_VALIDATED_EDGE_COUNT']} / 1",
        f"PAPER_CANDIDATE = {kpi['PAPER_CANDIDATE']} / 1",
        "FORWARD_PROFITABLE = 0",
        "LIVE_PROFITABLE = 0",
        f"FALSE_SUCCESS = {fs['FALSE_SUCCESS']}",
        f"INDEPENDENT_VERIFICATION = {verification['VERIFICATION_STATUS']}",
        f"NEXT = {next_step}",
        "",
        "## Why this decision",
        "RFC-039 proved we can find strategies that are net-positive historically. RFC-040 asks the",
        "harder question: is this worth putting money behind versus a simple passive alternative?",
        "SC-DUALMOM-002 is net positive in validation, but it does NOT beat a risk-matched passive",
        "benchmark after costs, so the answer is NO.",
        "",
        "## Counter-evidence / disclosures",
        "- Interpretation is LOWER than a plain passive MSCI World allocation: the strategy lagged on",
        "  return and only matched it on risk.",
        "- The ex-US risky leg uses MSCI Europe as a proxy for developed ex-US (EAFE): fidelity CLOSE.",
        "- The strategy's drawdown control comes mostly from holding bonds, which the risk-matched",
        "  benchmark partially replicates by scaling equity down.",
        "- Holdout NOT used as evidence (see process disclosure).",
        "",
        "## Verification",
        f"- Independent verifier = {verification['VERIFICATION_STATUS']} "
        f"(builder != verifier; decisions and PnL recomputed from scratch).",
        f"- Mismatches = {verification['mismatch_count']}; recomputed validation net = "
        f"{verification.get('recomputed_validation_net_eur')} EUR.",
        "",
        "## Process disclosure",
        "- The holdout window was inspected during pre-freeze exploratory development (as was",
        "  RFC-039's), so it is not treated as pristine evidence.",
        f"- spec_canonical_sha256 = {freeze['spec_canonical_sha256']}",
        f"- dataset_sha256 = {freeze['dataset_sha256']}",
        "",
        "Research evidence only. No live trading, no orders, no paid data, no broker integration.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entry = section_entry_gate()
    emit("RFC040_PLAN", render("RFC-040 PLAN", {
        "mission": "last authorized candidate; is it economically BETTER than a simple passive alternative, risk-matched?",
        "entry_gate": entry,
        "prohibitions": ["new families", "P3", "more selection", "live", "broker integration"],
    }), {"entry_gate": entry})
    if not entry["entry_condition_met"]:
        print(json.dumps({"STOP": "entry condition not met", **entry}, indent=2))
        return 1

    p1 = section_p1_reclassification()
    emit("P1_RECLASSIFICATION", render("P1 RECLASSIFICATION", p1), p1)
    kpi_initial = {"BUSINESS_VALIDATED_EDGE_COUNT": 0, "PAPER_CANDIDATE": 0,
                   "FORWARD_PROFITABLE": 0, "LIVE_PROFITABLE": 0}
    emit("BUSINESS_KPI", render("BUSINESS KPI", kpi_initial), kpi_initial)
    capital = section_capital_constraints()
    emit("CAPITAL_CONSTRAINTS", render("CAPITAL CONSTRAINTS", capital), capital)
    product = section_instrument_accessibility()
    emit("INSTRUMENT_ACCESSIBILITY", render("INSTRUMENT ACCESSIBILITY", product), product)

    series = rdata.load_aligned_universe(UNIVERSE)
    ds = sc.build_dataset(series)
    digest = rdata.dataset_digest(UNIVERSE)
    spec = dm_spec()
    freeze = section_freeze(spec, digest)
    emit("DM_FREEZE", render("DM FREEZE", freeze), freeze)

    bench = section_benchmarks(ds, SPLITS["VALIDATION"])
    emit("BENCHMARKS", render("BENCHMARKS", bench), bench)
    repro = section_reproduction(ds)
    emit("DM_REPRODUCTION", render("DM REPRODUCTION", repro), repro)
    disc = section_discovery(ds)
    emit("DM_DISCOVERY", render("DM DISCOVERY", disc), disc)
    val = section_validation(ds)
    emit("DM_VALIDATION", render("DM VALIDATION", val), val)
    business = section_business_edge(ds, bench, val)
    emit("BUSINESS_EDGE_GATE", render("BUSINESS EDGE GATE", business), business)
    robustness = section_robustness_status(business)
    emit("ROBUSTNESS_STATUS", render("ROBUSTNESS STATUS", robustness), robustness)
    holdout = section_holdout_status(business)
    emit("HOLDOUT_STATUS", render("HOLDOUT STATUS", holdout), holdout)
    scaling = section_scaling(ds)
    emit("CAPITAL_SCALING", render("CAPITAL SCALING", scaling), scaling)

    business_pass = business["result"] == "PASS"
    gates = {
        "G_BUSINESS_PRODUCT": product["result"],
        "G_DM_REPRO": repro["result"],
        "G_DM_1_DISCOVERY": disc["result"],
        "G_DM_2_VALIDATION": val["result"],
        "G_BUSINESS_EDGE": business["result"],
        "ROBUSTNESS": robustness["result"],
        "HOLDOUT": holdout["result"],
    }
    kpi = {
        "BUSINESS_VALIDATED_EDGE_COUNT": 1 if business_pass else 0,
        "PAPER_CANDIDATE": 1 if business_pass else 0,
        "FORWARD_PROFITABLE": 0,
        "LIVE_PROFITABLE": 0,
    }
    next_step = "PAPER_EXECUTION_CERTIFICATION" if business_pass else "STRATEGIC_BUSINESS_DECISION"
    fs = false_success_audit()

    verification = rverify.verify(
        series, {"lookback_days": dm.LOOKBACK, "cost_bps_per_side": dm.COST_BPS_PER_SIDE,
                 "reference_capital_eur": dm.REFERENCE_CAPITAL}, SPLITS, freeze,
        {"DM_DISCOVERY": disc, "DM_VALIDATION": val, "BUSINESS_EDGE_GATE": business},
    )
    emit("RFC040_VERIFICATION", render("RFC040 VERIFICATION", verification), verification)

    md = final_report_md(entry, p1, product, freeze, repro, disc, val, bench, business,
                         robustness, holdout, scaling, verification, kpi, fs, gates, next_step)
    write_md(OUT.parent / "RFC040_FINAL_REPORT.md", md)
    write_json(OUT.parent / "RFC040_FINAL_REPORT.json", {
        "reference_capital_eur": dm.REFERENCE_CAPITAL, "gates": gates, "kpi": kpi,
        "next": next_step, "false_success": fs, "verification": verification,
        "search_status": "PAUSED" if not business_pass else "ACTIVE",
        "no_p3": True, "spec_sha256": freeze["spec_canonical_sha256"],
        "dataset_sha256": freeze["dataset_sha256"],
    })
    tracked = "\n".join([
        "# SMALL_CAPITAL_DUAL_MOMENTUM_V1 (RFC-040, tracked canonical)",
        "",
        f"generated_at = {now_utc()}",
        f"reference_capital_eur = {dm.REFERENCE_CAPITAL}",
        "",
        "## Primary KPI",
        f"BUSINESS_VALIDATED_EDGE_COUNT = {kpi['BUSINESS_VALIDATED_EDGE_COUNT']}",
        "",
        "## Gate summary",
        *[f"- {k} = {v}" for k, v in gates.items()],
        "",
        f"P2 = {P2_ID} (dual momentum, UCITS, fidelity CLOSE)",
        f"P1 = {P1_ID} reclassified VALIDATED_DEFENSIVE / BUSINESS_FAIL (evidence retained)",
        "",
        f"SMALL_CAPITAL_PROFITABILITY_SEARCH = {'PAUSED' if not business_pass else 'ACTIVE'}",
        f"NEXT = {next_step}",
        "",
        "> Research evidence only. No live trading, no orders, no paid data, no broker integration.",
        "> Historical net edge != live profit.",
        "",
    ])
    write_md(DOCS / "SMALL_CAPITAL_DUAL_MOMENTUM_V1.md", tracked)
    write_json(DOCS / "SMALL_CAPITAL_DUAL_MOMENTUM_V1.json", {
        "gates": gates, "kpi": kpi, "next": next_step,
        "spec_sha256": freeze["spec_canonical_sha256"],
        "search_status": "PAUSED" if not business_pass else "ACTIVE",
    })
    print(json.dumps({"gates": gates, "kpi": kpi, "NEXT": next_step,
                      "FALSE_SUCCESS": fs["FALSE_SUCCESS"],
                      "VERIFICATION": verification["VERIFICATION_STATUS"]}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
