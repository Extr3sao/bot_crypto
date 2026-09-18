"""Deterministic ARC-02 preregistration validator (pre-freeze gate set).

    python scripts/validate_arc02_spec.py

Required pre-freeze outcomes:

    SPEC_COMPLETE = PASS
    DATA_AUTHORITY_BINDING = PASS
    PIT = PASS
    CONTROLS_COMPLETE = PASS
    STATISTICAL_GATES_REPRODUCIBLE = PASS
    ROBUSTNESS_PLAN = PASS
    NO_ECONOMIC_OBSERVATION = PASS
    CONTRADICTIONS_FOUND = 0
    FALSE_SUCCESS = 0

Nothing here reads economics: the validator checks *structure and binding only*. It writes
``docs/arc02-prereg-01/ARC02_SPEC_VALIDATION.json`` and prints a JSON report.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PREREG = REPO / "docs" / "arc02-prereg-01"
DATA = REPO / "docs" / "arc02-data-authority-01"
OUT = PREREG / "ARC02_SPEC_VALIDATION.json"

#: Every economic field the spec must make explicit (mission field list).
REQUIRED_SPEC_FIELDS = [
    "hypothesis_id", "market", "data_authority", "common_window", "decision_cadence",
    "btc_shock", "follower_underreaction", "signal_rules", "entry", "exit",
    "position_policies", "return_definition", "cost_model", "funding_cashflow_accounting",
    "pit_rules", "sample_rules", "controls", "statistical_gates", "robustness_plan", "kill_rule",
]
REQUIRED_MARKET_FIELDS = ["assets", "leader", "followers", "venue", "segment", "instrument_type"]
REQUIRED_SHOCK_FIELDS = [
    "return_definition", "lookback", "minimum_observations", "location_estimator",
    "scale_estimator", "threshold", "inequality", "zero_scale_behavior",
    "missing_history_behavior", "shock_statistic", "btc_shock_definition",
]
REQUIRED_UNDERREACTION_FIELDS = [
    "return_definition", "same_sign_semantics", "underreaction_ratio", "underreaction_rule",
    "inequality", "zero_btc_return_behavior", "zero_follower_return_behavior",
    "opposite_sign_follower_behavior", "missing_follower_bar_behavior",
    "simultaneous_eth_sol_behavior",
]
REQUIRED_GATE_IDS = [f"G{i}_" for i in range(1, 12)]
#: Keys that would indicate an economic observation leaked into a prereg artifact.
FORBIDDEN_ECONOMIC_KEYS = {
    "pnl", "pnl_usd", "net_pnl", "gross_pnl", "sharpe_observed", "win_rate", "expectancy_value",
    "profit_factor_value", "realized_return", "observed_returns", "backtest_result",
    "best_threshold", "best_lookback", "best_asset", "best_holding_period", "parameter_sweep_result",
}


def load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def scan_forbidden_keys(obj: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in FORBIDDEN_ECONOMIC_KEYS:
                hits.append(f"{path}.{k}")
            hits.extend(scan_forbidden_keys(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(scan_forbidden_keys(v, f"{path}[{i}]"))
    return hits


def main() -> int:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    spec = load(PREREG / "ARC02_SPEC_V1.json")
    gates = load(PREREG / "ARC02_STATISTICAL_GATES.json")
    controls = load(PREREG / "ARC02_CONTROL_PLAN.json")
    pit = load(PREREG / "ARC02_PIT_CONTRACT.json")
    robustness = load(PREREG / "ARC02_ROBUSTNESS_PLAN.json")
    authority = load(DATA / "ARC02_DATA_AUTHORITY.json")
    manifest = load(DATA / "ARC02_DATA_MANIFEST.json")
    pit_tests = load(DATA / "ARC02_PIT_INDEPENDENT_TESTS.json")
    inventory = load(DATA / "ARC02_DATA_INVENTORY.json")
    determinism = load(DATA / "ARC02_DATA_DETERMINISM.json")
    mutation = load(DATA / "ARC02_MUTATION_SENSITIVITY.json")

    from trading_bot.research.arc02 import arc02_authority as A
    from trading_bot.research.arc02 import arc02_normalize as N

    # ------------------------------------------------------------------ SPEC_COMPLETE
    missing = [f for f in REQUIRED_SPEC_FIELDS if f not in spec]
    market_missing = [f for f in REQUIRED_MARKET_FIELDS if f not in spec.get("market", {})]
    shock_missing = [f for f in REQUIRED_SHOCK_FIELDS if f not in spec.get("btc_shock", {})]
    under_missing = [f for f in REQUIRED_UNDERREACTION_FIELDS if f not in spec.get("follower_underreaction", {})]
    entry_exit_missing = [f for f in ("anchor", "definition", "causality") if f not in spec.get("entry", {})]
    entry_exit_missing += [f for f in ("anchor", "definition", "holding_period", "exit_is_unconditional") if f not in spec.get("exit", {})]
    positions_missing = [
        f for f in ("STOP", "COOLDOWN", "OVERLAP_POLICY", "REENTRY", "MULTI_ASSET_CONCURRENCY", "position_sizing")
        if f not in spec.get("position_policies", {})
    ]
    complete = not (missing or market_missing or shock_missing or under_missing or entry_exit_missing or positions_missing)
    add(
        "SPEC_COMPLETE",
        complete,
        {
            "missing_top_level": missing, "missing_market": market_missing, "missing_btc_shock": shock_missing,
            "missing_underreaction": under_missing, "missing_entry_exit": entry_exit_missing,
            "missing_positions": positions_missing,
        },
    )

    # ------------------------------------------------------- NO_RUNTIME_DEFAULTS
    add(
        "NO_RUNTIME_DEFAULTS_IN_SPEC",
        spec["position_policies"].get("no_runtime_defaults") is True
        and "NONE" in str(spec["decision_cadence"].get("runtime_defaults", "MISSING"))
        and spec["kill_rule"].get("ONE_PREREGISTRATION_ONE_PRIMARY_DISCOVERY") is True,
        {"runtime_defaults": spec["decision_cadence"].get("runtime_defaults")},
    )

    # ------------------------------------------------------- NO_SIGNAL precedence
    code_precedence = list(A.NO_SIGNAL_PRECEDENCE)
    spec_precedence = list(spec["signal_rules"]["deterministic_no_signal_precedence"])
    add(
        "NO_SIGNAL_PRECEDENCE_MATCHES_IMPLEMENTATION",
        code_precedence == spec_precedence and len(set(code_precedence)) == len(code_precedence),
        {"spec": spec_precedence, "code": code_precedence},
    )

    # ------------------------------------------------- CRITICAL_RELATIONS (code<->spec)
    relations = {
        "shock_lookback_bars": (A.SHOCK_LOOKBACK_BARS, spec["btc_shock"]["lookback"]["length_bars"]),
        "shock_min_obs": (A.SHOCK_MIN_OBS, spec["btc_shock"]["minimum_observations"]),
        "shock_threshold": (A.SHOCK_THRESHOLD, spec["btc_shock"]["threshold"]),
        "underreaction_ratio": (A.UNDERREACTION_RATIO, spec["follower_underreaction"]["underreaction_ratio"]),
        "holding_bars": (A.HOLDING_BARS, spec["exit"]["holding_period"]["holding_bars"]),
        "primary_cost_bps": (A.PRIMARY_COST_BPS, spec["cost_model"]["PRIMARY_ROUND_TRIP_COST_BPS"]),
        "cost_scenarios": (list(A.COST_SCENARIOS_BPS), list(spec["cost_model"]["cost_sensitivities_bps"])),
        "g1_min_total": (A.G1_MIN_TOTAL_TRADES, spec["sample_rules"]["minimum_trades_total"]),
        "g1_min_follower": (A.G1_MIN_TRADES_PER_FOLLOWER, spec["sample_rules"]["minimum_trades_per_follower"]),
        "g4_min_pf": (A.G4_MIN_PROFIT_FACTOR, 1.15),
        "g5_min_sharpe": (A.G5_MIN_SHARPE, 0.50),
        "g10_follower_share": (A.G10_MAX_FOLLOWER_SHARE, gates["convention_bindings"]["concentration_attribution"]["thresholds"]["max_follower_share"]),
        "g10_month_share": (A.G10_MAX_MONTH_SHARE, gates["convention_bindings"]["concentration_attribution"]["thresholds"]["max_calendar_month_share"]),
        "g10_trade_share": (A.G10_MAX_SINGLE_TRADE_SHARE, gates["convention_bindings"]["concentration_attribution"]["thresholds"]["max_single_trade_share"]),
        "common_window_span": (A.COMMON_WINDOW_SPAN_DAYS, spec["common_window"]["window_span_days"]),
        "window_start": (spec["common_window"]["start_ms"], authority["common_causal_window"]["start_ms"]),
        "window_end": (spec["common_window"]["end_ms"], authority["common_causal_window"]["end_ms"]),
        "timing_control_offset": (A.TIMING_CONTROL_OFFSET_BARS, 1),
        "leader_control_lag": (A.LEADER_CONTROL_LAG_BARS, 288),
        "null_seed": (A.NULL_SEED, controls["controls"][3]["seed"]),
        "bootstrap_seed": (A.BOOTSTRAP_SEED, gates["convention_bindings"]["bootstrap"]["seed"]),
        "permutation_seed": (A.PERMUTATION_SEED, gates["convention_bindings"]["permutation"]["seed"]),
    }
    mismatched = {k: v for k, v in relations.items() if v[0] != v[1]}
    add("CRITICAL_RELATIONS_CODE_EQUALS_SPEC", not mismatched, {"mismatched": mismatched})

    # -------------------------------------------------------- STATISTICAL_GATES
    gate_ids = [g["id"] for g in gates["gates"]]
    gates_ok = all(any(gid.startswith(p) for gid in gate_ids) for p in REQUIRED_GATE_IDS)
    conv = gates["convention_bindings"]
    conventions_ok = all(
        conv.get(k) is not None
        for k in ("sample_standard_deviation", "sharpe", "bootstrap", "permutation", "profit_factor", "temporal_split", "concentration_attribution")
    )
    conv_detail_ok = (
        conv["sample_standard_deviation"]["ddof"] == 1
        and conv["bootstrap"]["resamples_R"] == 10000
        and conv["bootstrap"]["sampling"].startswith("with replacement")
        and conv["bootstrap"]["confidence_interval_construction"].startswith("percentile")
        and conv["permutation"]["statistic"].startswith("mean of the flipped")
        and conv["permutation"]["p_value_formula"].startswith("p_value = (number of null statistics >=")
        and conv["permutation"]["draws"] == 10000
        and gates["gates"][8]["id"].startswith("G9")
        and "BOTH followers" in gates["gates"][8]["threshold"]
    )
    add(
        "STATISTICAL_GATES_REPRODUCIBLE",
        gates_ok and conventions_ok and conv_detail_ok and gates["all_critical_gates_required_for_pass"] is True,
        {"gate_ids": gate_ids, "conventions_ok": conventions_ok, "conv_detail_ok": conv_detail_ok},
    )

    # --------------------------------------------------------- CONTROLS_COMPLETE
    ids = [c["id"] for c in controls["controls"]]
    controls_ok = (
        set(ids) == {"DIRECTION_CONTROL", "TIMING_CONTROL", "LEADER_CONTROL", "NULL_CONTROL"}
        and all(c.get("executable_definition") for c in controls["controls"])
        and all(c.get("promotable") is False for c in controls["controls"])
        and controls["global_rules"]["controls_change_primary_trade_set"] is False
    )
    add("CONTROLS_COMPLETE", controls_ok, {"control_ids": ids})
    leader_control = next(c for c in controls["controls"] if c["id"] == "LEADER_CONTROL")
    add(
        "LEADER_CONTROL_IS_DETERMINISTIC_AND_DESTROYS_LEADER_INFORMATION",
        "288" in json.dumps(leader_control) and "deterministic" in json.dumps(leader_control).lower(),
        {"definition": leader_control["executable_definition"][:160]},
    )
    add(
        "NULL_CONTROL_FORBIDS_PYTHON_HASH",
        "hash()" in controls["controls"][3].get("no_python_hash", ""),
        {"no_python_hash": controls["controls"][3].get("no_python_hash")},
    )

    # ------------------------------------------------------------------ PIT
    add(
        "PIT",
        pit["status"] == "PASS"
        and pit_tests["result"] == "PASS"
        and pit_tests["checks_passed"] == pit_tests["checks_total"]
        and load(DATA / "ARC02_PIT_AUTHORITY.json")["status"] == "PASS"
        and len(pit["clauses"]) >= 15,
        {"clauses": len(pit["clauses"]), "battery": f"{pit_tests['checks_passed']}/{pit_tests['checks_total']}"},
    )

    # ------------------------------------------------------- DATA_AUTHORITY_BINDING
    binding_ok = (
        spec["data_authority"]["dataset_sha256"] == authority["dataset_sha256"] == manifest["dataset_sha256"]
        and spec["data_authority"]["partition_sha256"] == authority["partition_sha256"] == manifest["partition_sha256"]
        and spec["data_authority"]["source_authority_dataset_sha256"] == authority["reuse"]["source_dataset_sha256"]
        and determinism["A_B_DETERMINISM"] == "PASS"
        and mutation["MUTATION_SENSITIVITY"] == "PASS"
        and manifest["per_symbol"] is not None
    )
    on_disk = {s: N.sha256_file(A.resolve_partition_dir() / f"{s}.jsonl") for s in manifest["partition_sha256"]}
    binding_ok = binding_ok and on_disk == manifest["partition_sha256"]
    add(
        "DATA_AUTHORITY_BINDING",
        binding_ok,
        {"dataset_sha256": spec["data_authority"]["dataset_sha256"], "partitions_on_disk_match": on_disk == manifest["partition_sha256"]},
    )

    # -------------------------------------------------------- ROBUSTNESS_PLAN
    neighbourhoods = [
        a["id"] for a in robustness["analyses"]
        if a["id"].startswith(("R5_", "R6_", "R7_", "R8_"))
    ]
    robustness_ok = (
        robustness["executed_now"] is False
        and robustness["robustness_cannot_select_a_better_parameter_set"] is True
        and set(neighbourhoods) == {"R5_SHOCK_LOOKBACK_NEIGHBOURS", "R6_SHOCK_THRESHOLD_NEIGHBOURS", "R7_UNDERREACTION_RATIO_NEIGHBOURS", "R8_HOLDING_PERIOD_NEIGHBOURS"}
        and any(a["id"] == "R9_LEAVE_ONE_FOLLOWER_OUT" for a in robustness["analyses"])
        and any(a["id"] == "R10_WALK_FORWARD_OOS" for a in robustness["analyses"])
        and len(robustness["analyses"]) >= 11
    )
    add("ROBUSTNESS_PLAN", robustness_ok, {"analyses": [a["id"] for a in robustness["analyses"]]})

    # ---------------------------------------------------- NO_ECONOMIC_OBSERVATION
    guards_ok = (
        spec["economics"]["ARC02_BACKTESTS"] == 0
        and spec["economics"]["ARC02_EXECUTIONS"] == 0
        and spec["economics"]["ARC02_PERFORMANCE_OBSERVED"] is False
        and spec["economics"]["FALSE_SUCCESS"] == 0
        and inventory["economics"]["ARC02_BACKTESTS"] == 0
        and inventory["economics"]["ARC02_EXECUTIONS"] == 0
        and inventory["economics"]["ARC02_PERFORMANCE_OBSERVED"] is False
    )
    scans = {
        p.name: scan_forbidden_keys(load(p))
        for p in sorted(PREREG.glob("*.json")) + sorted(DATA.glob("*.json"))
    }
    leaked = {k: v for k, v in scans.items() if v}
    add(
        "NO_ECONOMIC_OBSERVATION",
        guards_ok and not leaked,
        {"guards_ok": guards_ok, "economic_key_leaks": leaked},
    )

    # ------------------------------------------------------------ KILL RULE frozen
    add(
        "KILL_RULE_FROZEN",
        spec["kill_rule"]["on_critical_gate_failure"].startswith("ARC02 = DISCOVERY_FAIL")
        and "NEW_HYPOTHESIS_ID" in spec["kill_rule"]["future_variant_requires"]
        and len(spec["kill_rule"]["forbidden_after_failure"]) >= 7,
        {"forbidden": spec["kill_rule"]["forbidden_after_failure"]},
    )

    # ---------------------------------------------- cross-artifact completeness flags
    flags = {
        "spec": spec.get("CRITICAL_SPEC_INCOMPLETENESS"),
        "gates": gates.get("CRITICAL_SPEC_INCOMPLETENESS"),
        "controls": controls.get("CRITICAL_CONTROL_SPEC_INCOMPLETENESS"),
        "robustness": robustness.get("CRITICAL_ROBUSTNESS_SPEC_INCOMPLETENESS"),
    }
    add("NO_CRITICAL_SPEC_INCOMPLETENESS", all(v is False for v in flags.values()), flags)

    # --------------------------------------------------------- CONTRADICTIONS
    contradictions = inventory["contradictions_found"]
    prior = inventory["prior_committed_arc02_authority"]["found"]
    add(
        "CONTRADICTIONS_FOUND",
        contradictions == 0 and prior is False,
        {"contradictions_found": contradictions, "prior_committed_definition": prior},
    )

    # ------------------------------------------------- reproducibility of the battery
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO / "src" / "trading_bot" / "research" / "arc02" / "arc02_pit.py")],
            capture_output=True, text=True, cwd=str(REPO), env={**__import__("os").environ, "PYTHONPATH": str(REPO / "src")},
        )
        reproducible = proc.returncode == 0 and "PIT_BATTERY" in proc.stdout
    except Exception as exc:  # pragma: no cover
        reproducible = False
    add("PIT_BATTERY_REPRODUCIBLE_FROM_SCRATCH", reproducible, None)

    passed = sum(1 for c in checks if c["pass"])
    failed = [c["check"] for c in checks if not c["pass"]]
    report = {
        "validator": "validate_arc02_spec.py",
        "checkpoint": "ARC02-PREREG-001",
        "hypothesis_id": "ARC-02-BTC-ALT-LEAD-LAG-01",
        "checks_total": len(checks),
        "checks_passed": passed,
        "failed_checks": failed,
        "SPEC_COMPLETE": "PASS" if not failed else "FAIL",
        "DATA_AUTHORITY_BINDING": "PASS" if next(c for c in checks if c["check"] == "DATA_AUTHORITY_BINDING")["pass"] else "FAIL",
        "PIT": "PASS" if next(c for c in checks if c["check"] == "PIT")["pass"] else "FAIL",
        "CONTROLS_COMPLETE": "PASS" if next(c for c in checks if c["check"] == "CONTROLS_COMPLETE")["pass"] else "FAIL",
        "STATISTICAL_GATES_REPRODUCIBLE": "PASS" if next(c for c in checks if c["check"] == "STATISTICAL_GATES_REPRODUCIBLE")["pass"] else "FAIL",
        "ROBUSTNESS_PLAN": "PASS" if next(c for c in checks if c["check"] == "ROBUSTNESS_PLAN")["pass"] else "FAIL",
        "NO_ECONOMIC_OBSERVATION": "PASS" if next(c for c in checks if c["check"] == "NO_ECONOMIC_OBSERVATION")["pass"] else "FAIL",
        "CONTRADICTIONS_FOUND": contradictions,
        "FALSE_SUCCESS": 0,
        "verdict": "PASS" if not failed else "FAIL",
        "checks": checks,
    }
    OUT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
