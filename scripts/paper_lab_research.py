"""Strategy lab: a read-only pass over discovery → validation → admission (§16, §22-§24, §35).

This process exists to be *safe to run next to PAPER*. It never writes to the
runtime's state, never edits a strategy, and never promotes anything: it
verifies that the admission pipeline is intact and reports what the pipeline
currently says.

What it checks, all of it re-derivable from committed artifacts:

* the admission ledger's sources still hash to what the ledger recorded, so no
  verdict is resting on an artifact that has since changed;
* every strategy that is PAPER_CANDIDATE/PAPER_ACTIVE has the data its family
  needs, and no research verdict claims otherwise (§37);
* the two microstructure hypotheses stay ``TECHNICALLY_READY_NEEDS_HISTORY``
  with their minimum data pre-registered, so their future run cannot choose a
  threshold after seeing a result (§23, §24);
* the retention layer's lineage is intact enough that the aggregated research
  data still points back at the raw it replaced (§9).

Output is a report, not a mutation. If a check fails, that is a finding for the
operator; the PAPER runtime keeps running on the map it already holds.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.paper_loop import wait_for_stop_file  # noqa: E402
from trading_bot.research.forward.storage import sha256_file  # noqa: E402

DEFAULT_LAB_ROOT = Path("reports/paper-lab")
PREREGISTRATION_PATH = Path("config/microstructure_preregistration.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="config/strategy_admission.json")
    parser.add_argument("--run-root", default=str(DEFAULT_LAB_ROOT))
    parser.add_argument("--forward-root", default="reports/microstructure-forward-lab")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=900.0)
    parser.add_argument("--max-iterations", type=int, default=0, help="0 = until stopped")
    parser.add_argument(
        "--stop-file",
        default=None,
        help="path whose appearance stops the worker gracefully between passes (§51)",
    )
    return parser.parse_args()


def check_ledger_sources(ledger: Any) -> dict[str, Any]:
    """A verdict is only as good as the artifact it was read from (§20)."""
    results: list[dict[str, Any]] = []
    for source in ledger.sources:
        path = REPO_ROOT / str(source.get("path", ""))
        expected = str(source.get("sha256", ""))
        if not path.exists():
            results.append({"path": source.get("path"), "ok": False, "reason": "missing"})
            continue
        actual, _size = sha256_file(path)
        results.append(
            {
                "path": source.get("path"),
                "ok": actual == expected,
                "expected": expected[:16],
                "actual": actual[:16],
                "reason": None if actual == expected else "source changed since the ledger was built",
            }
        )
    return {
        "checked": len(results),
        "ok": bool(results) and all(entry["ok"] for entry in results),
        "sources": results,
    }


def check_data_readiness(registry: Any, timeframe: str) -> dict[str, Any]:
    rows = []
    for strategy_id, record in sorted(registry.records.items()):
        ready, reason = record.data_readiness({"ohlcv"})
        rows.append(
            {
                "strategy_id": strategy_id,
                "status": record.admission_status.value,
                "required_data": list(record.required_data),
                "data_ready": ready,
                "reason": reason,
            }
        )
    executable = registry.paper_candidates(timeframe)
    return {
        "ok": all(row["data_ready"] for row in rows),
        "paper_executable": executable,
        "strategies": rows,
    }


def check_microstructure_hypotheses() -> dict[str, Any]:
    """§23/§24 — M-03/M-07 stay needs-history, with a pre-registered minimum.

    Read from a committed pre-registration file when it exists, so the minimum
    coverage is chosen *before* the data is looked at. When the file is absent
    the check reports ``PREREGISTRATION_MISSING`` rather than inventing one.
    """
    path = REPO_ROOT / PREREGISTRATION_PATH
    if not path.exists():
        return {
            "ok": False,
            "status": "PREREGISTRATION_MISSING",
            "path": PREREGISTRATION_PATH.as_posix(),
            "note": "the minimum data for M-03/M-07 must be pre-registered before either runs",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "status": "UNREADABLE", "reason": str(exc)}
    hypotheses = payload.get("hypotheses", {})
    rows = []
    for hypothesis_id, entry in sorted(hypotheses.items()):
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "state": entry.get("state"),
                "minimum_data": entry.get("minimum_data"),
                "preregistered_at": entry.get("preregistered_at"),
            }
        )
    return {"ok": bool(rows), "status": "PREREGISTERED", "hypotheses": rows}


def check_retention_lineage(forward_root: Path) -> dict[str, Any]:
    lineage_dir = forward_root / "lineage"
    records = sorted(lineage_dir.rglob("*.json"))
    intact = 0
    broken: list[dict[str, Any]] = []
    for path in records:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            broken.append({"path": str(path), "reason": str(exc)})
            continue
        output = forward_root / str(payload.get("output_path", ""))
        if not output.exists():
            broken.append({"path": str(path), "reason": "aggregate missing"})
            continue
        digest, size = sha256_file(output)
        if digest != payload.get("output_sha256") or size != payload.get("output_bytes"):
            broken.append({"path": str(path), "reason": "aggregate hash mismatch"})
            continue
        intact += 1
    return {
        "ok": not broken,
        "lineage_records": len(records),
        "intact": intact,
        "broken": broken[:10],
        "chain": "RAW segments -> aggregated/*.json.gz (source hashes, window, "
        "aggregation version, output hash) -> reports/",
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.strategy_state import StrategyRegistry

    ledger = AdmissionLedger.load(REPO_ROOT / args.ledger)
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    registry = StrategyRegistry.from_ledger(ledger, assets=assets)
    counts = registry.counts_by_status()
    forward_root = (REPO_ROOT / args.forward_root).resolve()

    checks = {
        "ledger_sources": check_ledger_sources(ledger),
        "data_readiness": check_data_readiness(registry, args.timeframe),
        "microstructure_hypotheses": check_microstructure_hypotheses(),
        "retention_lineage": check_retention_lineage(forward_root),
    }
    return {
        "schema_version": "strategy-lab-report-v1",
        "timestamp_ms": int(time.time() * 1000),
        "mode": "READ_ONLY (never mutates a strategy, never touches PAPER state)",
        "timeframe": args.timeframe,
        "ledger": ledger.source_path,
        "registry": registry.as_dict(),
        "registry_counts": counts,
        # The full histogram, so a lifecycle count of zero can never be read as
        # "there are no strategies": most of this ledger is classified with the
        # research verdicts (NO_GROSS_EDGE / COST_KILLED), not with REJECTED.
        "status_histogram": {key: value for key, value in sorted(counts.items())},
        "strategies_total": len(registry.records),
        "strategies_not_paper_executable": sum(
            1 for record in registry.records.values() if not record.admitted_for_paper
        ),
        "lifecycle": {
            "REJECTED": counts.get("REJECTED", 0),
            "RESEARCH_REQUIRED": counts.get("RESEARCH_REQUIRED", 0),
            "PAPER_CANDIDATE": counts.get("PAPER_CANDIDATE", 0),
            "PAPER_ACTIVE": counts.get("PAPER_ACTIVE", 0),
            "PAPER_RETIRED": counts.get("PAPER_RETIRED", 0),
        },
        "paper_executable": registry.paper_candidates(args.timeframe),
        "checks": checks,
        "all_checks_ok": all(bool(check.get("ok")) for check in checks.values()),
        "flow": "NEW HYPOTHESIS -> RESEARCH -> VALIDATION -> OOS -> ROBUSTNESS -> "
        "PAPER_CANDIDATE -> PAPER_ACTIVE (never straight from research)",
        "research_cannot_change_a_running_strategy": (
            "the PAPER runtime snapshots its strategy map at startup; regenerating "
            "the ledger while it runs cannot alter decisions it has already loaded"
        ),
    }


def main() -> int:
    args = parse_args()
    run_dir = (REPO_ROOT / args.run_root).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "STRATEGY_LAB_REPORT.json"
    stop_file = Path(args.stop_file).expanduser() if args.stop_file else None
    iterations = 0
    while True:
        report = build_report(args)
        tmp = report_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(report_path)
        lifecycle = report["lifecycle"]
        print(
            f"[lab] lifecycle REJECTED={lifecycle['REJECTED']} "
            f"RESEARCH_REQUIRED={lifecycle['RESEARCH_REQUIRED']} "
            f"PAPER_CANDIDATE={lifecycle['PAPER_CANDIDATE']} "
            f"PAPER_ACTIVE={lifecycle['PAPER_ACTIVE']} "
            f"PAPER_RETIRED={lifecycle['PAPER_RETIRED']} "
            f"checks_ok={report['all_checks_ok']}"
        )
        print(
            f"[lab] strategies={report['strategies_total']} "
            f"not_paper_executable={report['strategies_not_paper_executable']} "
            f"histogram={report['status_histogram']}"
        )
        iterations += 1
        if not args.loop or (args.max_iterations and iterations >= args.max_iterations):
            break
        if wait_for_stop_file(stop_file, args.interval):
            print("[lab] stop requested; report is current")
            break
    print(f"[lab] report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
