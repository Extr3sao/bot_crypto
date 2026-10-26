"""WP-TDM-016 — independent verifier: recompute every published claim.

BUILDER != VERIFIER. This script imports nothing from the audit, decision or
evidence runners; it reads the artifacts they wrote *and* the raw research
inputs they claim to derive from, recomputes the numbers with its own code, and
refuses the run when a published number cannot be reproduced.

It also proves it is not vacuous: ``--mutations`` tampers in-memory copies of
the artifacts (inflated gross, promoted ledger status, lowered cost line,
shifted threshold, altered net, flipped verdict, ...) and requires the same
checks to catch each one. ``false_success`` counts the mutations that slipped
through; anything above zero retires the verdict.

Usage:
    uv run python scripts/tdm16_verify.py \
        --out evidence/tdm/wp-tdm-16-paper-admission/VERIFY.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS = {
    "ledger": "config/strategy_admission.json",
    "explorer": "data/recovery/COST_BARRIER_EXPLORER.json",
    "matrix": "docs/STRATEGY_ADMISSION_MATRIX.json",
    "discovery": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
    "audit": "evidence/tdm/wp-tdm-16-paper-admission/ADMISSION_AUDIT.json",
    "cycle": "evidence/tdm/wp-tdm-16-paper-admission/PAPER_CYCLE_EVIDENCE.json",
    "decision": "evidence/tdm/wp-tdm-16-paper-admission/ECONOMIC_DECISION.json",
    "next": "evidence/tdm/wp-tdm-16-paper-admission/NEXT_EXPERIMENT.json",
    "final": "evidence/tdm/wp-tdm-16-paper-admission/FINAL_REPORT.json",
}

VERIFY_SCHEMA_VERSION = "wp-tdm-16-verify-v1"
TOL = 1e-6

World = dict[str, Any]


def _load_world(repo_root: Path = REPO_ROOT) -> World:
    world: World = {}
    for key, rel in ARTIFACTS.items():
        path = repo_root / rel
        world[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return world


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strategies(world: World) -> dict[str, Any]:
    return {
        k: v
        for k, v in (world["ledger"].get("strategies") or {}).items()
        if not k.startswith("_")
    }


def _cells(world: World) -> dict[str, Any]:
    return {str(c.get("cell_id")): c for c in (world["explorer"].get("cells") or [])}


def _measured_rt(world: World) -> float:
    frontier = (world["explorer"].get("reachability") or {}).get("frontier") or {}
    row = frontier.get("cheapest_line_observed_only") or frontier.get("cheapest_line_taker") or {}
    return float(row.get("round_trip_bps") or 0.0)


def _futures_maker(world: World) -> dict[str, Any]:
    for row in world["explorer"].get("venue_grid") or []:
        if (
            str(row.get("scenario_id", "")) == "BINANCE_USDM_PERP_MAKER"
            and str(row.get("order_mode")) == "maker"
            and float(row.get("size_usd") or 0.0) == 200.0
            and str(row.get("liquidity_regime")) == "deep"
        ):
            return row
    return {}


def _known_fees(world: World) -> float:
    row = _futures_maker(world)
    return round(
        sum(
            float(c.get("value_bps") or 0.0)
            for c in (row.get("components") or [])
            if str(c.get("knowledge")) == "KNOWN"
        ),
        6,
    )


def _best_gross(world: World) -> tuple[str, float]:
    cells = _cells(world)
    if not cells:
        return "", 0.0
    cell_id, cell = max(cells.items(), key=lambda kv: float(kv[1].get("zero_cost_gross_bps") or 0.0))
    return cell_id, float(cell.get("zero_cost_gross_bps") or 0.0)


def _rule_status(world: World, family: str, gross: float) -> str:
    """The builder's rule, reimplemented here (never imported)."""
    candidates = set(world["matrix"].get("paper_candidates") or [])
    if family in candidates and gross > 0:
        return "PAPER_CANDIDATE"
    if gross > 0:
        return "COST_KILLED"
    return "NO_GROSS_EDGE"


def _add(
    checks: list[dict[str, Any]], cid: str, description: str, passed: bool, observed: Any
) -> None:
    checks.append(
        {"id": cid, "description": description, "passed": bool(passed), "observed": observed}
    )


def check_all(world: World) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    strategies = _strategies(world)
    cells = _cells(world)
    audit = world["audit"]
    cycle = world["cycle"]
    decision = world["decision"]
    nxt = world["next"]

    # -- WP-016A: the audit ---------------------------------------------------
    _add(checks, "V01", "the ledger enumerates 24 strategies", len(strategies) == 24, len(strategies))
    admitted = [sid for sid, e in strategies.items() if e.get("admitted_for_paper")]
    _add(checks, "V02", "no strategy is admitted for PAPER", admitted == [], admitted)

    recorded = {s["path"]: s["sha256"] for s in (world["ledger"].get("_sources") or [])}
    actual = {rel: _sha256(REPO_ROOT / rel) for rel in recorded if (REPO_ROOT / rel).exists()}
    _add(
        checks,
        "V03",
        "the ledger's recorded source hashes still match the files on disk",
        bool(recorded) and recorded == actual,
        {"recorded": recorded, "actual": actual},
    )

    _add(
        checks,
        "V04",
        "the pre-registered matrix lists no paper candidates",
        (world["matrix"].get("paper_candidates") or []) == [],
        world["matrix"].get("paper_candidates"),
    )

    mismatches: list[str] = []
    for sid, entry in strategies.items():
        expected = _rule_status(
            world, str(entry.get("family") or ""), float(entry.get("expected_gross_edge_bps") or 0.0)
        )
        if expected != str(entry.get("status")):
            mismatches.append(f"{sid}: ledger={entry.get('status')} rule={expected}")
        if bool(entry.get("admitted_for_paper")) != (expected == "PAPER_CANDIDATE"):
            mismatches.append(f"{sid}: admitted flag disagrees with the rule")
    _add(
        checks,
        "V05",
        "the published rule reproduces every ledger status and admitted flag",
        mismatches == [],
        mismatches,
    )

    _add(
        checks,
        "V06",
        "the explorer publishes one cell per ledger strategy",
        set(cells) == set(strategies) and len(cells) == 24,
        {"cells": len(cells), "ledger": len(strategies)},
    )

    best_id, best_gross = _best_gross(world)
    _add(
        checks,
        "V07",
        "the audit's best cell and gross match the explorer",
        audit.get("frontier", {}).get("max_gross_cell") == best_id
        and abs(float(audit.get("frontier", {}).get("max_gross_bps") or 0.0) - best_gross) <= TOL,
        {"explorer": [best_id, best_gross], "audit": audit.get("frontier", {})},
    )

    measured = _measured_rt(world)
    maker = _futures_maker(world)
    maker_rt = float(maker.get("round_trip_bps") or 0.0)
    _add(
        checks,
        "V08",
        "the audit's cost lines match the explorer frontier",
        abs(float(audit.get("frontier", {}).get("cheapest_measured_rt_bps") or 0.0) - measured)
        <= TOL
        and abs(
            float(audit.get("frontier", {}).get("assumed_futures_maker_rt_bps") or 0.0) - maker_rt
        )
        <= TOL,
        {"measured": measured, "assumed_futures_maker": maker_rt},
    )

    clearing_measured = [
        sid for sid, cell in cells.items() if float(cell.get("zero_cost_gross_bps") or 0.0) > measured
    ]
    clearing_maker = [
        sid for sid, cell in cells.items() if float(cell.get("zero_cost_gross_bps") or 0.0) > maker_rt
    ]
    _add(
        checks,
        "V09",
        "no cell clears the cheapest measured cost line (recomputed)",
        clearing_measured == [],
        clearing_measured,
    )
    _add(
        checks,
        "V10",
        "no cell clears the assumed futures-maker line (recomputed)",
        clearing_maker == [],
        clearing_maker,
    )

    positive = sum(1 for e in strategies.values() if float(e.get("expected_gross_edge_bps") or 0.0) > 0)
    unproven = sum(
        1 for e in strategies.values() if int((e.get("edge_evidence") or {}).get("sample_trades") or 0) == 0
    )
    pop = audit.get("population") or {}
    _add(
        checks,
        "V11",
        "the audit population counts are the ones the artifacts imply",
        pop.get("strategies") == len(strategies)
        and pop.get("gross_positive") == positive
        and pop.get("gross_negative") == len(strategies) - positive
        and pop.get("ledger_sample_unproven") == unproven,
        {
            "audit": [pop.get("strategies"), pop.get("gross_positive"), pop.get("gross_negative"), pop.get("ledger_sample_unproven")],
            "recomputed": [len(strategies), positive, len(strategies) - positive, unproven],
        },
    )

    bound_errors: list[str] = []
    for row in audit.get("strategies") or []:
        cell = cells.get(str(row.get("strategy_id")))
        if cell is None:
            bound_errors.append(f"{row.get('strategy_id')}: no explorer cell")
            continue
        gross = float(cell.get("zero_cost_gross_bps") or 0.0)
        if abs(float(row.get("net_upper_bound_measured_bps") or 0.0) - (gross - measured)) > TOL:
            bound_errors.append(f"{row.get('strategy_id')}: measured bound")
        if abs(float(row.get("net_upper_bound_assumed_futures_maker_bps") or 0.0) - (gross - maker_rt)) > TOL:
            bound_errors.append(f"{row.get('strategy_id')}: maker bound")
    _add(
        checks,
        "V12",
        "every per-strategy arithmetic bound equals gross minus the published cost line",
        bound_errors == [],
        bound_errors,
    )

    cause_errors: list[str] = []
    for row in audit.get("strategies") or []:
        causes = row.get("rejection_causes") or []
        gross = float(row.get("gross_bps") or 0.0)
        if gross <= 0 and causes != ["NO_GROSS_EDGE"]:
            cause_errors.append(f"{row.get('strategy_id')}: negative gross with causes {causes}")
        if gross > 0 and causes[:1] != ["GROSS_BELOW_CHEAPEST_MEASURED_LINE"]:
            cause_errors.append(f"{row.get('strategy_id')}: positive gross without cost cause")
    _add(
        checks,
        "V13",
        "each rejection cause follows from the cell's own gross",
        cause_errors == [],
        cause_errors,
    )

    audit_checks = audit.get("checks") or []
    recomputed_failed = sum(1 for c in audit_checks if not c.get("passed"))
    _add(
        checks,
        "V14",
        "the audit's own check tallies are honest",
        audit.get("checks_total") == len(audit_checks)
        and audit.get("checks_failed") == recomputed_failed
        and recomputed_failed == 0,
        {
            "declared": [audit.get("checks_total"), audit.get("checks_failed")],
            "recomputed": [len(audit_checks), recomputed_failed],
        },
    )

    divergences = audit.get("gross_divergences") or []
    _add(
        checks,
        "V15",
        "ledger/explorer gross divergences change neither sign nor cost side",
        all(not d.get("changes_sign") and not d.get("changes_cost_side") for d in divergences),
        [(d.get("strategy_id"), d.get("delta_bps"), d.get("class")) for d in divergences],
    )

    # -- WP-016B: the cycle ---------------------------------------------------
    traces = cycle.get("traces") or {}
    cycle_trace = traces.get("cycle") or {}
    cost_trace = traces.get("cost_line") or {}
    blocked_trace = traces.get("fail_closed") or {}
    tests = cycle.get("tests") or []

    _add(
        checks,
        "V16",
        "the cycle evidence is labelled TEST_ONLY, artifact and every trace",
        cycle.get("label") == "TEST_ONLY"
        and all(t.get("label") == "TEST_ONLY" for t in traces.values()),
        {"artifact": cycle.get("label"), "traces": [t.get("label") for t in traces.values()]},
    )
    _add(
        checks,
        "V17",
        "all TEST_ONLY integration tests ran and passed",
        len(tests) >= 3 and all(t.get("outcome") == "passed" for t in tests),
        [(t.get("name"), t.get("outcome")) for t in tests],
    )
    _add(
        checks,
        "V18",
        "the evidence run exited 0 and its own checks are all green",
        (cycle.get("scope") or {}).get("pytest_exit_code") == 0
        and cycle.get("checks_failed") == 0
        and cycle.get("verified") is True,
        {
            "exit": (cycle.get("scope") or {}).get("pytest_exit_code"),
            "failed": cycle.get("checks_failed"),
            "verified": cycle.get("verified"),
        },
    )

    net_error = abs(
        float(cycle_trace.get("net_pnl_usd") or 0.0)
        - (float(cycle_trace.get("gross_pnl_usd") or 0.0) - float(cycle_trace.get("fees_usd") or 0.0))
    )
    _add(
        checks,
        "V19",
        "the cycle's net PnL is gross minus the commissions it paid",
        cycle_trace != {} and net_error <= 1e-9,
        net_error,
    )
    _add(
        checks,
        "V20",
        "one order, one fill, one close, and equity equals initial plus net PnL",
        cycle_trace.get("orders_created") == 1
        and cycle_trace.get("fills_opened") == 1
        and cycle_trace.get("fills_closed") == 1
        and abs(
            float(cycle_trace.get("equity_after") or 0.0)
            - (10_000.0 + float(cycle_trace.get("net_pnl_usd") or 0.0))
        )
        <= 1e-6,
        {
            k: cycle_trace.get(k)
            for k in ("orders_created", "fills_opened", "fills_closed", "equity_after", "net_pnl_usd")
        },
    )
    _add(
        checks,
        "V21",
        "the restart reconciles RECOVERED and the same intent places no second order",
        cycle_trace.get("reconciliation_status") == "RECOVERED"
        and cycle_trace.get("duplicate_orders_after_restart") == 0,
        {
            "status": cycle_trace.get("reconciliation_status"),
            "duplicate_orders": cycle_trace.get("duplicate_orders_after_restart"),
        },
    )
    _add(
        checks,
        "V22",
        "the cost-line fixture closed two round trips, one per exit kind, with fees paid",
        cost_trace.get("round_trips") == 2
        and sorted(cost_trace.get("exit_reasons") or []) == ["stop_loss", "take_profit"]
        and float(cost_trace.get("fees_usd") or 0.0) > 0.0,
        {
            "round_trips": cost_trace.get("round_trips"),
            "exits": cost_trace.get("exit_reasons"),
            "fees": cost_trace.get("fees_usd"),
        },
    )
    _add(
        checks,
        "V23",
        "a refused order leaves zero orders and reconciles CONSISTENT",
        blocked_trace.get("orders_created") == 0
        and blocked_trace.get("reconciliation_status") == "CONSISTENT"
        and float(blocked_trace.get("equity") or 0.0) == 10_000.0,
        blocked_trace,
    )

    # -- WP-016C: the decision ------------------------------------------------
    _add(
        checks,
        "V24",
        "the decision is ECONOMIC_BLOCKED with zero admitted strategies",
        decision.get("decision") == "ECONOMIC_BLOCKED"
        and (decision.get("admission") or {}).get("admitted") == 0,
        {"decision": decision.get("decision"), "admitted": (decision.get("admission") or {}).get("admitted")},
    )
    _add(
        checks,
        "V25",
        "no PAPER order was placed against real market data, and no LIVE order exists",
        (decision.get("paper_run_with_real_market_data") or {}).get("orders") == 0
        and (decision.get("paper_run_with_real_market_data") or {}).get("live_orders") == 0
        and (decision.get("paper_run_with_real_market_data") or {}).get("attempted") is False,
        decision.get("paper_run_with_real_market_data"),
    )

    known_fees = _known_fees(world)
    budget = round(best_gross - known_fees, 6)
    econ = decision.get("economics") or {}
    _add(
        checks,
        "V26",
        "the breakeven execution budget is recomputed from the explorer's own components",
        abs(float(econ.get("breakeven_execution_cost_bps") or 0.0) - budget) <= TOL
        and abs(float(econ.get("best_gross_bps") or 0.0) - best_gross) <= TOL
        and abs(float(econ.get("known_fees_bps") or 0.0) - known_fees) <= TOL,
        {"recomputed": budget, "decision": econ.get("breakeven_execution_cost_bps")},
    )

    threshold = float((nxt.get("threshold") or {}).get("breakeven_execution_cost_bps") or 0.0)
    gates = nxt.get("gates") or {}
    _add(
        checks,
        "V27",
        "the pre-registered experiment uses the same threshold, gates and kill switch",
        abs(threshold - budget) <= TOL
        and len(gates) == 9
        and "4.912" in str(gates.get("G3_execution_cost"))
        and bool(nxt.get("kill_switch"))
        and int((nxt.get("verification_minimum") or {}).get("mutations") or 0) >= 8,
        {"threshold": threshold, "gates": len(gates), "kill_switch": bool(nxt.get("kill_switch"))},
    )

    # -- the published report cannot drift from the artifacts -----------------
    final = world["final"] or {}
    _add(
        checks,
        "V28",
        "FINAL_REPORT.json repeats the verified numbers, not its own",
        final.get("admitted") == 0
        and final.get("decision") == decision.get("decision")
        and abs(float(final.get("breakeven_execution_cost_bps") or 0.0) - budget) <= TOL
        and final.get("tests_passed") == len(tests)
        and final.get("verify_checks_failed") == 0,
        {
            "admitted": final.get("admitted"),
            "decision": final.get("decision"),
            "threshold": final.get("breakeven_execution_cost_bps"),
            "tests": final.get("tests_passed"),
            "checks_failed": final.get("verify_checks_failed"),
        },
    )

    # -- no live path, no credentials ---------------------------------------
    live_hits: list[str] = []
    # `LIVE_ORDER` deliberately does not match the JSON field `live_orders`:
    # the field is the *count* of live orders (zero), which is the opposite of
    # a marker that one exists.
    pattern = re.compile(
        r"(api[_-]?secret\s*[:=]|api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{12,}|LIVE_ORDER)",
        re.I,
    )
    for rel in ARTIFACTS.values():
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            live_hits.append(rel)
    _add(
        checks,
        "V29",
        "no credential and no live-order marker appears in the artifacts",
        live_hits == [],
        live_hits,
    )

    return checks


# -- mutations ---------------------------------------------------------------


def _mutate(world: World, name: str) -> World:
    w = copy.deepcopy(world)
    if name == "inflate_best_gross":
        for row in w["audit"]["strategies"]:
            if row["strategy_id"] == w["audit"]["frontier"]["max_gross_cell"]:
                row["gross_bps_explorer"] = float(row["gross_bps_explorer"]) + 1.0
                row["gross_bps"] = float(row["gross_bps"]) + 1.0
        w["audit"]["frontier"]["max_gross_bps"] = (
            float(w["audit"]["frontier"]["max_gross_bps"]) + 1.0
        )
    elif name == "promote_ledger_status":
        first = sorted(_strategies(w))[0]
        w["ledger"]["strategies"][first]["status"] = "PAPER_CANDIDATE"
        w["ledger"]["strategies"][first]["admitted_for_paper"] = True
    elif name == "drop_explorer_cell":
        w["explorer"]["cells"] = w["explorer"]["cells"][:-1]
    elif name == "lower_measured_line":
        w["explorer"]["reachability"]["frontier"]["cheapest_line_observed_only"][
            "round_trip_bps"
        ] = 5.0
    elif name == "shift_threshold":
        w["next"]["threshold"]["breakeven_execution_cost_bps"] = 9.0
    elif name == "fail_a_test":
        w["cycle"]["tests"][0]["outcome"] = "failed"
    elif name == "alter_cycle_net":
        w["cycle"]["traces"]["cycle"]["net_pnl_usd"] = (
            float(w["cycle"]["traces"]["cycle"]["net_pnl_usd"]) + 1.0
        )
    elif name == "flip_decision":
        w["decision"]["decision"] = "ECONOMIC_CANDIDATE"
    elif name == "overstate_population":
        w["audit"]["population"]["ledger_sample_unproven"] = 0
    elif name == "erase_divergence_warning":
        for d in w["audit"]["gross_divergences"]:
            d["changes_cost_side"] = True
    elif name == "report_drift":
        w["final"]["breakeven_execution_cost_bps"] = 1.0
    elif name == "hide_failed_check":
        w["cycle"]["checks_failed"] = 0
        w["cycle"]["verified"] = True
        w["cycle"]["scope"]["pytest_exit_code"] = 1
    else:  # pragma: no cover - programming error
        raise ValueError(f"unknown mutation {name}")
    return w


MUTATIONS = (
    "inflate_best_gross",
    "promote_ledger_status",
    "drop_explorer_cell",
    "lower_measured_line",
    "shift_threshold",
    "fail_a_test",
    "alter_cycle_net",
    "flip_decision",
    "overstate_population",
    "erase_divergence_warning",
    "report_drift",
    "hide_failed_check",
)


def run_mutations(world: World) -> list[dict[str, Any]]:
    baseline = check_all(world)
    baseline_failed = {c["id"] for c in baseline if not c["passed"]}
    out: list[dict[str, Any]] = []
    for name in MUTATIONS:
        mutated = check_all(_mutate(world, name))
        caught = sorted({c["id"] for c in mutated if not c["passed"]} - baseline_failed)
        out.append({"mutation": name, "detected": bool(caught), "caught_by": caught})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="evidence/tdm/wp-tdm-16-paper-admission/VERIFY.json"
    )
    args = parser.parse_args(argv)

    world = _load_world()
    checks = check_all(world)
    mutations = run_mutations(world)
    false_success = sum(1 for m in mutations if not m["detected"])
    failed = [c for c in checks if not c["passed"]]

    verify: dict[str, Any] = {
        "artifact": "WP-TDM-016 · independent verification",
        "schema_version": VERIFY_SCHEMA_VERSION,
        "verifier": "scripts/tdm16_verify.py",
        "independence": (
            "imports none of the builders (audit, decision, evidence); reads the artifacts and "
            "the raw research inputs, and recomputes each claim with its own code"
        ),
        "artifacts": {
            rel: {"sha256": _sha256(REPO_ROOT / rel)} if (REPO_ROOT / rel).exists() else {"missing": True}
            for rel in ARTIFACTS.values()
        },
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "mutations": mutations,
        "mutations_total": len(mutations),
        "false_success": false_success,
        "status": "VERIFIED" if not failed and false_success == 0 else "NOT_VERIFIED",
    }
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(verify, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"wrote {args.out}: {len(checks) - len(failed)}/{len(checks)} checks, "
        f"mutations {len(mutations) - false_success}/{len(mutations)}, "
        f"false_success={false_success}, status={verify['status']}"
    )
    for c in failed:
        print(f"  FAIL {c['id']}: {c['description']} -> {json.dumps(c['observed'], default=str)[:300]}")
    for m in mutations:
        if not m["detected"]:
            print(f"  UNDETECTED mutation: {m['mutation']}")
    return 0 if verify["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
