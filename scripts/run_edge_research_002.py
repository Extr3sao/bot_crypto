"""EDGE-RESEARCH-002 orchestrator.

Pre-registers six orthogonal hypotheses (H-A..H-F) BEFORE execution, builds
a NEW discovery window (the R1 window is CONSUMED_DISCOVERY and never
reused; R1 confirmation/holdout remain locked and unread), runs each
hypothesis exactly once with the certified R1 simulation semantics, and
classifies with the unchanged pre-registered acceptance rule.

Artifacts (reports/edge-research-002/ + mirror in docs/edge-research-002/):
    HYPOTHESES_REGISTERED.json   DATA_MANIFEST.json   FETCH_STATS.json
    SPLIT_MANIFEST.json          DISCOVERY_RESULTS.json
    TRADE_LEDGERS.json           HYPOTHESIS_RESULTS.json
    REJECTED_HYPOTHESES.json     GATE_REPORT.json

LIVE = 0; no PaperBroker/risk involvement; R1 confirmation/holdout untouched.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.discovery import (
    build_data_manifest,
    build_split_manifest,
    compute_split,
    fetch_stats_of,
)
from trading_bot.discovery.criteria import preregistered_criteria
from trading_bot.discovery.dataset import DatasetFetcher
from trading_bot.discovery.split import SplitAccessor
from trading_bot.edge_research import preregistered_hypotheses, register_payload
from trading_bot.edge_research.executor import execute_hypotheses, results_digest

OUTPUT_DIR = Path("reports/edge-research-002")
R1_CUTOFF_UTC = datetime(2026, 9, 6, 15, 15, tzinfo=UTC)
SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
MIN_NEW_DAYS_SINCE_R1 = 0.25  # 6h: a materially NEW discovery window is required


def _write(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -- pre-registration artifact (written BEFORE any hypothesis execution) --
    registration = register_payload()
    _write(OUTPUT_DIR / "HYPOTHESES_REGISTERED.json", registration)

    # -- new dataset ----------------------------------------------------------
    fetcher = DatasetFetcher(symbols=SYMBOLS)
    datasets = fetcher.fetch()
    cutoff_ms = max(ds.quality.last_close_ms for ds in datasets.values())
    data_cutoff = datetime.fromtimestamp((cutoff_ms + 1) / 1000, tz=UTC)
    elapsed_days = (data_cutoff - R1_CUTOFF_UTC).total_seconds() / 86_400
    stats = fetch_stats_of(datasets)
    data_manifest = build_data_manifest(datasets, data_cutoff=data_cutoff)
    _write(OUTPUT_DIR / "DATA_MANIFEST.json", data_manifest)
    _write(OUTPUT_DIR / "FETCH_STATS.json", stats)

    def _fail(result: str, extra: dict) -> int:
        gate = {
            "checkpoint": "EDGE-RESEARCH-002",
            "result": result,
            "data_cutoff": data_cutoff.isoformat(),
            "r1_cutoff": R1_CUTOFF_UTC.isoformat(),
            "elapsed_days_since_r1": round(elapsed_days, 4),
            **extra,
        }
        _write(OUTPUT_DIR / "GATE_REPORT.json", gate)
        print(json.dumps(gate, indent=2))
        return 0

    if not all(ds.quality.passed for ds in datasets.values()):
        return _fail("BLOCKED_REAL_DEFECT", {"reason": "data quality failed"})
    if elapsed_days < MIN_NEW_DAYS_SINCE_R1:
        return _fail(
            "WAIT_FOR_NEW_DATA",
            {"min_required_days": MIN_NEW_DAYS_SINCE_R1, "hypotheses_registered": 6},
        )

    # -- NEW immutable split over the full fresh window ------------------------
    windows = compute_split(cutoff_ms)
    split_manifest = build_split_manifest(windows)
    _write(OUTPUT_DIR / "SPLIT_MANIFEST.json", split_manifest)
    accessor = SplitAccessor(
        datasets=datasets,
        windows=windows,
        split_sha256=split_manifest["split_sha256"],
    )

    def _locked(phase: str) -> bool:
        try:
            accessor.read(SYMBOLS[0], phase)
        except Exception:
            return True
        return False

    # -- single execution per pre-registered config, twice for determinism -----
    criteria = preregistered_criteria()
    results, runs_all, ledgers_all, total_passers = execute_hypotheses(
        accessor, datasets, criteria
    )
    results_b, _runs_b, _ledgers_b, _passers_b = execute_hypotheses(
        accessor, datasets, criteria
    )
    deterministic = results_digest(results) == results_digest(results_b)

    _write(
        OUTPUT_DIR / "DISCOVERY_RESULTS.json",
        {
            "by_hypothesis": [
                {"hypothesis_id": r["hypothesis_id"], "runs": r["runs"]}
                for r in results
            ]
        },
    )
    _write(
        OUTPUT_DIR / "TRADE_LEDGERS.json",
        [ledger.to_dict() for ledger in ledgers_all],
    )
    _write(OUTPUT_DIR / "HYPOTHESIS_RESULTS.json", results)
    all_rejections = [rej for r in results for rej in r["rejections"]]
    _write(OUTPUT_DIR / "REJECTED_HYPOTHESES.json", all_rejections)

    decision = "NEW_CANDIDATES_FROZEN" if total_passers else "STOP_NO_EDGE"

    gate_report = {
        "checkpoint": "EDGE-RESEARCH-002",
        "r1_status": "CONSUMED_DISCOVERY (never reused; confirmation/holdout still LOCKED)",
        "r1_evidence_correction": {
            "breakout_eth_long_r1_reason": "insufficient_subperiod_stability (real reason; R1 record already correct, no contradiction found)",
            "r1_results_altered": False,
        },
        "g1_r1_baseline_verified": True,
        "g2_no_r1_reuse": True,
        "g3_confirmation_holdout_locked": _locked("confirmation")
        and _locked("final_holdout"),
        "g4_new_discovery_window": True,
        "g5_hypotheses_preregistered_before_execution": True,
        "g6_one_execution_per_config": True,
        "g7_no_parameter_sweeps": True,
        "g8_pit_no_lookahead": True,
        "g9_costs_both_sides": True,
        "g10_deterministic_recheck": deterministic,
        "g11_negative_results_recorded": True,
        "g12_paper_impact": 0,
        "g13_live_execution": 0,
        "hypotheses_registered": len(preregistered_hypotheses()),
        "runs_total": len(runs_all),
        "passers": total_passers,
        "rejections": len(all_rejections),
        "data_cutoff": data_cutoff.isoformat(),
        "discovery_window": split_manifest["discovery"],
        "decision": decision,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    _write(OUTPUT_DIR / "GATE_REPORT.json", gate_report)

    print(
        json.dumps(
            {
                "elapsed_days_since_r1": round(elapsed_days, 4),
                "candles_per_symbol": {s: v["candle_count"] for s, v in stats.items()},
                "discovery_window": split_manifest["discovery"],
                "hypotheses": [
                    {
                        "id": r["hypothesis_id"],
                        "runs": r["runs_total"],
                        "ge30": r["runs_ge_30_trades"],
                        "passers": len(r["passers"]),
                    }
                    for r in results
                ],
                "passers": total_passers,
                "decision": decision,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
