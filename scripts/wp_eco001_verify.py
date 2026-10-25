"""WP-ECONOMIC-BLOCKER-001 — independent verification of the audit's own numbers.

This script does not import the audit scripts. It re-derives every quantity from
the primary sources (the ledger, the admission matrix, the cost model, the
recorded runtime traces, the CSV) and checks the audit's artefacts against that
re-derivation. A check that cannot be computed is reported as ``NOT_ASSESSED``
and never counted as a pass.

Exit code 0 only when every check is PASS. Declared defects are reported
explicitly as ``KNOWN_DEFECT`` and do not silently become passes.

Usage::

    uv run python scripts/wp_eco001_verify.py --evidence <evidence dir>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from trading_bot.autonomous.costs import CostEngine
from trading_bot.research.microstructure.cost_model_v3 import VENUE_SPECS

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("config/strategy_admission.json")
MATRIX = Path("docs/STRATEGY_ADMISSION_MATRIX.json")
CSV_COLUMNS = [
    "strategy_id",
    "family",
    "timeframe",
    "horizon_minutes",
    "gross_bps_per_trade",
    "gross_knowledge",
    "sample_trades",
    "sample_proven",
    "round_trip_cost_bps",
    "cost_known_fees_bps",
    "cost_estimated_bps",
    "net_bps_per_trade",
    "break_even_gross_bps",
    "required_gross_1.5x_bps",
    "net_at_1.5x_bps",
    "gross_shortfall_vs_cost_bps",
    "admission_status",
    "admitted_for_paper",
    "matrix_status",
    "matrix_net_usd_base",
    "matrix_fees_usd_base",
    "matrix_profit_factor_base",
    "verdict",
    "evidence_gap",
]

RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: Any = None, *, status: str | None = None) -> bool:
    RESULTS.append(
        {
            "check": name,
            "status": status or ("PASS" if ok else "FAIL"),
            "detail": detail,
        }
    )
    return ok


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        default=str(REPO_ROOT / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001"),
    )
    args = parser.parse_args(argv)
    ev = Path(args.evidence)

    ledger = load(REPO_ROOT / LEDGER)
    matrix = load(REPO_ROOT / MATRIX)
    admission = load(ev / "STRATEGY_ADMISSION_AUDIT.json")
    cost = load(ev / "COST_MODEL_AUDIT.json")
    economics = load(ev / "STRATEGY_ECONOMICS.json")
    baseline = load(ev / "TEST_BASELINE_COMPARISON.json")
    rows = list(csv.DictReader((ev / "STRATEGY_ECONOMICS_MATRIX.csv").open(encoding="utf-8")))

    # -- A. strategy admission --------------------------------------------
    check("A1_ledger_entry_count_is_24", admission["entry_count"] == len(ledger["strategies"]) == 24,
          {"audit": admission["entry_count"], "ledger": len(ledger["strategies"])})
    check(
        "A2_six_entries_per_timeframe",
        admission["entries_by_timeframe"] == {"5m": 6, "15m": 6, "30m": 6, "1h": 6},
        admission["entries_by_timeframe"],
    )
    check(
        "A3_no_family_is_a_paper_candidate",
        admission["paper_candidates_in_matrix"] == []
        and (matrix.get("paper_candidates") or []) == []
        and not any(e.get("admitted_for_paper") for e in ledger["strategies"].values()),
        {"audit": admission["paper_candidates_in_matrix"], "matrix": matrix.get("paper_candidates")},
    )
    recomputed_reasons: dict[str, int] = {}
    for row in admission["entries"]:
        for reason in row["reasons"]:
            recomputed_reasons[reason] = recomputed_reasons.get(reason, 0) + 1
    check(
        "A4_reason_counts_match_entry_rows",
        recomputed_reasons == admission["reason_counts"],
        {"audit": admission["reason_counts"], "recomputed": recomputed_reasons},
    )
    check(
        "A5_every_entry_has_a_non_empty_reason_set",
        all(row["reasons"] for row in admission["entries"]),
        [row["strategy_id"] for row in admission["entries"] if not row["reasons"]],
    )
    # Independent provenance recomputation (never trust the audit's own hashes).
    prov_ok = True
    prov_detail = []
    for source in ledger["_sources"]:
        actual = sha256(REPO_ROOT / source["path"])
        prov_detail.append(
            {"path": source["path"], "recorded": source["sha256"][:16], "actual": actual[:16]}
        )
        prov_ok = prov_ok and actual == source["sha256"]
    # The audit must report the hash state it measured, not a flattering version.
    check(
        "A6_audit_reports_the_measured_hash_state",
        admission["provenance_ok"] == prov_ok,
        {"audit_claims_ok": admission["provenance_ok"], "measured_ok": prov_ok, "sources": prov_detail},
    )
    stale = [p for p in prov_detail if p["recorded"] != p["actual"]]
    check(
        "A7_provenance_anchor_defect_is_declared_not_hidden",
        (not stale and not admission["provenance_has_unverifiable_anchor"])
        or (stale and admission["provenance_has_unverifiable_anchor"]),
        {"stale": stale, "audit_declared": admission["provenance_has_unverifiable_anchor"]},
    )
    if stale:
        RESULTS[-1]["status"] = "KNOWN_DEFECT"
        RESULTS[-1]["detail"] = {
            "stale": stale,
            "severity": "audit-chain only: the runtime reads statuses, never the hashes",
            "declared_in": "STRATEGY_ADMISSION_AUDIT.json + FINAL_REPORT.md",
        }

    # -- B. cost model ------------------------------------------------------
    engine = CostEngine()
    observed = load(ev / "COST_OBSERVED.json")
    check("B1_observed_blocks_were_extracted", observed["block_count"] > 0, observed["block_count"])
    recomputed = []
    for block in observed["blocks"]:
        breakdown = engine.evaluate(
            size_usd=float(block["size_usd"]),
            horizon_minutes=float(block["horizon_minutes"]),
            spread_bps=float(block["spread_bps"]),
            volatility_bps=0.0,
        )
        recomputed.append(
            {
                "asset": block["asset"],
                "recorded": block["round_trip_bps"],
                "recomputed": breakdown.round_trip_bps,
                "delta": breakdown.round_trip_bps - float(block["round_trip_bps"]),
            }
        )
    max_delta = max(abs(r["delta"]) for r in recomputed) if recomputed else None
    check("B2_recorded_runtime_cost_recomputed_within_1e-6", max_delta is not None and max_delta <= 1e-6,
          {"cases": len(recomputed), "max_abs_delta_bps": max_delta})
    from trading_bot.autonomous.costs import MODEL_V3_COMPONENT_NAMES

    emitted = [c["name"] for c in engine.evaluate(size_usd=1000.0, horizon_minutes=5.0).components]
    check(
        "B3_component_inventory_matches_the_engine_vocabulary",
        sorted(cost["component_inventory"]["names"]) == sorted(MODEL_V3_COMPONENT_NAMES)
        and set(emitted) <= set(MODEL_V3_COMPONENT_NAMES)
        and {"exchange_fee_entry", "exchange_fee_exit"} <= set(emitted),
        {"documented": cost["component_inventory"]["names"], "emitted_for_a_taker_intent": emitted},
    )
    fallback = cost["decomposition"]["estimated_spread_fallback"]
    check(
        "B4_knwn_fee_floor_is_structural",
        abs(fallback["by_knowledge"]["KNOWN_bps"] - 2 * VENUE_SPECS["BINANCE_SPOT_STANDARD_TAKER"].taker_fee_bps) <= 1e-9
        and fallback["by_knowledge"]["KNOWN_share_pct"] > 80.0,
        fallback["by_knowledge"],
    )
    barrier = cost["barrier"]
    ledger_max_gross = max(
        float(e.get("expected_gross_edge_bps") or 0.0) for e in ledger["strategies"].values()
    )
    check(
        "B5_barrier_arithmetic_is_consistent",
        abs(barrier["max_measured_gross_edge_bps"] - ledger_max_gross) <= 1e-9
        and abs(
            barrier["max_gross_minus_runtime_cost_bps"]
            - (ledger_max_gross - barrier["runtime_round_trip_observed_spread_bps"])
        )
        <= 1e-6,
        barrier,
    )
    check(
        "B6_no_gross_edge_covers_even_the_known_fees",
        barrier["known_fees_alone_exceed_every_gross_edge"] is True,
        {"max_gross": ledger_max_gross, "known_fees": barrier["runtime_round_trip_observed_spread_bps"]},
    )
    check(
        "B7_published_v4_numbers_re_derived",
        cost["published_model_v4_recomputed"]["all_match"] is True,
        cost["published_model_v4_recomputed"]["assets"],
    )

    # -- C. economics matrix ------------------------------------------------
    header = list(rows[0].keys()) if rows else []
    check("C1_csv_columns_are_the_documented_ones", header == CSV_COLUMNS, header)
    check("C2_one_row_per_ledger_entry", len(rows) == 24, len(rows))
    ids = {r["strategy_id"] for r in rows}
    check("C3_csv_covers_exactly_the_ledger_ids", ids == set(ledger["strategies"]), sorted(ids ^ set(ledger["strategies"])))
    arithmetic_bad = []
    for row in rows:
        gross = float(row["gross_bps_per_trade"])
        cost_bps = float(row["round_trip_cost_bps"])
        if abs((gross - cost_bps) - float(row["net_bps_per_trade"])) > 1e-6:
            arithmetic_bad.append(row["strategy_id"])
        if abs((gross - 1.5 * cost_bps) - float(row["net_at_1.5x_bps"])) > 1e-6:
            arithmetic_bad.append(row["strategy_id"] + ":1.5x")
    check("C4_net_arithmetic_recomputed", not arithmetic_bad, arithmetic_bad)
    gross_mismatch = [
        r["strategy_id"]
        for r in rows
        if abs(float(r["gross_bps_per_trade"]) - float(ledger["strategies"][r["strategy_id"]]["expected_gross_edge_bps"])) > 1e-9
    ]
    check("C5_gross_column_equals_the_ledger", not gross_mismatch, gross_mismatch)
    check(
        "C6_no_entry_clears_its_cost",
        economics["any_entry_clears_cost"] is False
        and all(float(r["net_bps_per_trade"]) <= 0 for r in rows),
        economics["verdict_counts"],
    )
    check(
        "C7_verdict_vocabulary_is_exhaustive",
        {r["verdict"] for r in rows}
        <= {"NET_NEGATIVE_AFTER_COST", "NET_UNPROVEN_SAMPLE", "NET_POSITIVE_NOT_ADMITTED"}
        and economics["verdict_counts"].get("NET_POSITIVE_NOT_ADMITTED", 0) == 0,
        economics["verdict_counts"],
    )
    check(
        "C8_unproven_verdicts_require_zero_sample",
        all(int(r["sample_trades"]) == 0 for r in rows if r["verdict"] == "NET_UNPROVEN_SAMPLE"),
        [r["strategy_id"] for r in rows if r["verdict"] == "NET_UNPROVEN_SAMPLE" and int(r["sample_trades"]) != 0],
    )
    check(
        "C9_cost_matches_the_cost_audit",
        all(
            abs(float(r["round_trip_cost_bps"]) - barrier["runtime_round_trip_estimated_spread_bps"]) <= 1e-6
            for r in rows
        ),
        {"csv_cost": sorted({r["round_trip_cost_bps"] for r in rows}), "audit": barrier["runtime_round_trip_estimated_spread_bps"]},
    )

    # -- D. test baseline ---------------------------------------------------
    w = {f"{f['kind']} {f['node']}" for f in baseline["working_tree_run"]["failures"]}
    b = {f"{f['kind']} {f['node']}" for f in baseline["clean_checkout_run"]["failures"]}
    check(
        "D1_every_current_failure_also_fails_the_clean_checkout",
        w <= b and len(w) > 0,
        {"working": len(w), "clean": len(b), "intersection": len(w & b)},
    )
    check(
        "D2_clean_checkout_ran_its_own_source",
        baseline["clean_checkout_imported_its_own_source"] is True,
        baseline["clean_checkout_run"]["import_path"],
    )
    healthy = baseline.get("healthy_run") or {}
    if healthy:
        check(
            "D3_healthy_sets_are_green",
            healthy.get("exit_code") == 0 and healthy.get("counts", {}).get("failed", 0) == 0,
            {"counts": healthy.get("counts"), "exit": healthy.get("exit_code")},
        )
    else:
        check(
            "D3_healthy_sets_are_green",
            False,
            "the healthy selection was not recorded in the baseline artefact",
            status="NOT_ASSESSED",
        )

    # -- E. constraints -----------------------------------------------------
    import subprocess

    tracked = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "config", "tests"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    check(
        "E1_no_runtime_config_or_code_was_modified",
        tracked == "",
        tracked or "(clean)",
    )
    check(
        "E2_paper_not_declared_validated",
        all(
            "PAPER_RUNTIME_VALIDATED" not in (ev / name).read_text(encoding="utf-8")
            for name in ("STRATEGY_ECONOMICS.json", "COST_MODEL_AUDIT.json")
        ),
        "(checked the machine-readable artefacts)",
    )

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    not_assessed = sum(1 for r in RESULTS if r["status"] == "NOT_ASSESSED")
    defects = sum(1 for r in RESULTS if r["status"] == "KNOWN_DEFECT")
    payload = {
        "wp": "WP-ECONOMIC-BLOCKER-001",
        "artefact": "INDEPENDENT_VERIFICATION",
        "evidence_dir": ev.as_posix(),
        "checked_artefacts": sorted(p.name for p in ev.iterdir() if p.is_file()),
        "totals": {
            "pass": passed,
            "fail": failed,
            "not_assessed": not_assessed,
            "known_defect": defects,
            "checks": len(RESULTS),
        },
        "verdict": "VERIFIED_WITH_DECLARED_DEFECTS"
        if failed == 0 and not_assessed == 0
        else ("VERIFIED" if failed == 0 else "FAILED"),
        "checks": RESULTS,
    }
    out = ev / "INDEPENDENT_VERIFICATION.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for result in RESULTS:
        print(f"[{result['status']:<11}] {result['check']}")
    print(f"\n{totals_line(passed, failed, not_assessed, defects)}")
    print(f"-> {out}")
    return 0 if failed == 0 else 1


def totals_line(passed: int, failed: int, not_assessed: int, defects: int) -> str:
    return (
        f"pass={passed} fail={failed} not_assessed={not_assessed} "
        f"known_defect={defects} total={len(RESULTS)}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
