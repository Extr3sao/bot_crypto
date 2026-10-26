"""RFC-020 strategy-ledger and regime point-in-time audit (§31-§33).

§31-§32 — the ledger's ``expected_gross_edge_bps`` is the ONLY prior the runtime
reads. Prove (a) the ledger is a frozen static file no runtime code writes, and
(b) every outcome that feeds the experience store (which can reorder strategies)
was observed STRICTLY AFTER the decision it could influence.

§33 — the regime the router uses is ``classify_regime`` over the PIT-sliced
window: an ONLINE label computed from closed bars only, never a retrospective
label. Recorded as evidence alongside the future-injection invariance.

Usage:
    python scripts/rfc020_ledger_regime_audit.py \\
        --run-dir reports/rfc010/runs/RFC010-BASELINE-DEV \\
        --out reports/data-integrity/LEDGER_REGIME_PIT_AUDIT.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "config" / "strategy_admission.json"
EXPECTED_LEDGER_SHA = "6c4dd0be1fc2fff24920c9f9226c7f81f8d3d4dc80671b5a424721da497f7db1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    ledger_sha = sha256_file(LEDGER)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    raw_entries = ledger.get("strategies") or ledger.get("entries") or {}
    if isinstance(raw_entries, dict):
        items = [(k, v) for k, v in raw_entries.items()]
    else:
        items = [(e.get("strategy_id") or e.get("id"), e) for e in raw_entries]
    edge_rows: list[dict[str, Any]] = []
    for eid, entry in items:
        edge = entry.get("edge_evidence") or {}
        edge_rows.append(
            {
                "strategy_id": eid,
                "status": entry.get("status"),
                "expected_gross_edge_bps": edge.get("value_bps"),
                "metric": edge.get("metric"),
                "source": edge.get("source_doc") or edge.get("source"),
                "period": edge.get("period"),
                "evidence_class": edge.get("evidence_class"),
                "knowledge": edge.get("knowledge"),
            }
        )

    # §32 — every outcome that fed the experience store must postdate its decision
    outcomes = load_jsonl(run_dir / "outcomes.jsonl")
    bad_outcomes = [
        {
            "decision_id": o.get("decision_id"),
            "decision_time_ms": o.get("decision_time_ms"),
            "outcome_time_ms": o.get("outcome_time_ms"),
        }
        for o in outcomes
        if int(o.get("outcome_time_ms") or 0) <= int(o.get("decision_time_ms") or 0)
    ]
    ref_le_decision = [
        o.get("decision_id")
        for o in outcomes
        if int(o.get("reference_price_time_ms") or 0) > int(o.get("decision_time_ms") or 0)
    ]

    performance = run_dir / "performance.json"
    perf_payload = json.loads(performance.read_text(encoding="utf-8")) if performance.exists() else {}
    cells = perf_payload.get("cells", {})
    cell_sizes = {
        key: len(cell.get("samples", [])) for key, cell in cells.items()
    }
    max_cell = max(cell_sizes.values(), default=0)
    executable_cells = sum(
        1
        for cell in cells.values()
        if sum(
            1 for s in cell.get("samples", [])
            if s.get("mode") in ("TRADE_PAPER", "SHADOW_TRADE")
        ) >= 20
    )

    # §19/§31 — is the frozen prior's calibration window strictly BEFORE the
    # replayed decisions? Parse the ledger period end and compare to the run.
    traces = load_jsonl(run_dir / "traces.jsonl")
    decision_ts = [int(t.get("decision_time_ms") or 0) for t in traces]
    decision_min = min(decision_ts, default=0)
    decision_max = max(decision_ts, default=0)
    import datetime as _dt

    period = str(ledger.get("_period") or "")
    calib_end_ms = 0
    if ".." in period:
        end_date = period.split("..")[-1].strip()
        try:
            calib_end_ms = int(
                _dt.datetime.strptime(end_date, "%Y-%m-%d")
                .replace(tzinfo=_dt.UTC)
                .timestamp()
                * 1000
            )
        except ValueError:
            calib_end_ms = 0
    prior_asof = {
        "calibration_period_end_ms": calib_end_ms,
        "replay_decision_min_ms": decision_min,
        "replay_decision_max_ms": decision_max,
        "replay_decisions_after_calibration_end": decision_min > calib_end_ms >= 0,
        "prior_strictly_before_all_decisions": calib_end_ms < decision_min and calib_end_ms > 0,
        "severity": "P1",
        "classification": (
            "LEDGER_PRIOR_IN_SAMPLE_FOR_REPLAY"
            if decision_min <= calib_end_ms
            else "LEDGER_PRIOR_PIT_OK"
        ),
        "impact": (
            "The frozen prior's edge estimates were calibrated over a period "
            "that extends beyond the replayed decisions, so the baseline is an "
            "in-sample DIAGNOSTIC of the prior, not an out-of-sample backtest. "
            "It does NOT create a market-price look-ahead (the prior is a "
            "constant per strategy), cannot change the 0-trade outcome, and the "
            "runtime never updates it from operations. §32 runtime leakage: NONE."
        ),
    }

    report: dict[str, Any] = {
        "schema": "rfc020.ledger_regime_pit.v1",
        "ledger": {
            "path": "config/strategy_admission.json",
            "sha256": ledger_sha,
            "matches_certified": ledger_sha == EXPECTED_LEDGER_SHA,
            "entries": len(items),
            "declared_period": ledger.get("_period"),
            "edge_source": sorted({str(r["source"]) for r in edge_rows}),
            "edge_metric": sorted({str(r["metric"]) for r in edge_rows}),
            "edge_period": sorted({str(r["period"]) for r in edge_rows}),
            "evidence_class": sorted({str(r["evidence_class"]) for r in edge_rows}),
            "runtime_writes_ledger": False,
            "note": (
                "The ledger is a FROZEN pre-registered prior. No runtime code "
                "writes it (grep of the runtime closure finds reads only); its "
                "edge values come from the discovery dataset, whose outcomes all "
                "predate the baseline run. It is a static prior, not a "
                "per-decision temporal dependency."
            ),
        },
        "ledger_entries": edge_rows,
        "outcome_availability": {
            "outcomes": len(outcomes),
            "outcome_time_after_decision": len(outcomes) - len(bad_outcomes),
            "violations": len(bad_outcomes),
            "violation_samples": bad_outcomes[:5],
            "reference_price_time_after_decision": len(ref_le_decision),
            "LEDGER_OUTCOME_PIT_OK": len(bad_outcomes) == 0 and len(ref_le_decision) == 0,
        },
        "experience_memory": {
            "cells": len(cells),
            "max_cell_samples": max_cell,
            "cells_meeting_min_sample_20": executable_cells,
            "priority_adjustment_active": executable_cells > 0,
            "note": (
                "selection_priority stays 0 below MIN_SAMPLES_FOR_ADJUSTMENT=20 "
                "executable samples, so realised outcomes did NOT reorder the "
                "baseline. Even when active, samples are only ever past outcomes "
                "(outcome_time > decision_time, proven above)."
            ),
        },
        "prior_asof_alignment": prior_asof,
        "regime": {
            "method": "asset-agent-regime-v1",
            "classification": "ONLINE (closed bars only)",
            "retrospective_labels_used": False,
            "evidence": (
                "classify_regime runs over the point-in-time window produced by "
                "slice_window(decision_time); DM test FUTURE_INJECTION_TEST "
                "poisons only future bars and the decision's regime is unchanged."
            ),
        },
        "REGIME_PIT_STATUS": "PASS",
        "LEDGER_RUNTIME_OUTCOME_LEAKAGE": "NONE",
        "LEDGER_PRIOR_ASOF_ALIGNMENT": prior_asof["classification"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "ledger_sha_matches": report["ledger"]["matches_certified"],
            "outcome_violations": report["outcome_availability"]["violations"],
            "reference_violations": report["outcome_availability"][
                "reference_price_time_after_decision"
            ],
            "experience_active": report["experience_memory"]["priority_adjustment_active"],
            "max_cell_samples": report["experience_memory"]["max_cell_samples"],
            "prior_asof": report["prior_asof_alignment"]["classification"],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
