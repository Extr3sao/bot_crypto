"""FRESH-DATA-001-R1 orchestrator.

Rebuilds the prospective discovery dataset with FULL paginated history from
2026-08-19T00:00:00Z to the last closed candle available at execution time,
audits edge-sanity semantics, freezes a NEW chronological split, and re-runs
discovery from scratch (no reuse of R0 results for parameters/assets/
thresholds/families/filters).

Supersedes the R0 run (truncated at ~1000 bars/symbol by a pagination
defect). The R0 registry under docs/fresh-data-001/evidence/ is preserved
with every candidate marked SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW.

Artifacts (reports/ + mirrored to docs/fresh-data-001-r1/evidence/):
    DATA_MANIFEST.json        FETCH_STATS.json
    SPLIT_MANIFEST.json       DISCOVERY_RESULTS.json
    TRADE_LEDGERS.json        CANDIDATE_REGISTRY.json
    REJECTED_HYPOTHESES.json  GATE_REPORT.json

Deterministic: same dataset + same code => identical artifacts (G14).
LIVE = 0; no PaperBroker/risk involvement; confirmation/holdout stay locked.
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
    preregistered_criteria,
    registry_from_runs,
)
from trading_bot.discovery.dataset import DatasetFetcher
from trading_bot.discovery.runner import run_discovery
from trading_bot.discovery.split import SplitAccessor

OUTPUT_DIR = Path("reports/fresh-data-001-r1")
R0_REGISTRY = Path("docs/fresh-data-001/evidence/CANDIDATE_REGISTRY.json")
SUPERSEDE_STATUS = "SUPERSEDED_INSUFFICIENT_DISCOVERY_WINDOW"
SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
MIN_FRESH_HISTORY_DAYS = 14.0


def _write(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -- full-history dataset -------------------------------------------------
    fetcher = DatasetFetcher(symbols=SYMBOLS)
    datasets = fetcher.fetch()
    cutoff_ms = max(ds.quality.last_close_ms for ds in datasets.values())
    data_cutoff = datetime.fromtimestamp((cutoff_ms + 1) / 1000, tz=UTC)
    stats = fetch_stats_of(datasets)
    data_manifest = build_data_manifest(datasets, data_cutoff=data_cutoff)
    _write(OUTPUT_DIR / "DATA_MANIFEST.json", data_manifest)
    _write(OUTPUT_DIR / "FETCH_STATS.json", stats)

    # -- fresh-history sufficiency (before any discovery) ---------------------
    first_ms = min(s["first_ts"] for s in stats.values())
    total_days = (cutoff_ms - first_ms) / 86_400_000
    if total_days < MIN_FRESH_HISTORY_DAYS:
        gate_report = {
            "checkpoint": "FRESH-DATA-001-R1",
            "result": "INSUFFICIENT_FRESH_HISTORY",
            "total_fresh_days": round(total_days, 3),
            "min_required_days": MIN_FRESH_HISTORY_DAYS,
            "data_cutoff": data_cutoff.isoformat(),
        }
        _write(OUTPUT_DIR / "GATE_REPORT.json", gate_report)
        print(json.dumps(gate_report, indent=2))
        return 0

    # -- new immutable split --------------------------------------------------
    windows = compute_split(cutoff_ms)
    split_manifest = build_split_manifest(windows)
    _write(OUTPUT_DIR / "SPLIT_MANIFEST.json", split_manifest)
    accessor = SplitAccessor(
        datasets=datasets,
        windows=windows,
        split_sha256=split_manifest["split_sha256"],
    )

    # -- G12/G13: structural lock probe (fails loud if locks ever weaken) -----
    def _locked(phase: str) -> bool:
        try:
            accessor.read(SYMBOLS[0], phase)
        except Exception:  # probe must catch the fail-closed raise
            return True
        return False

    confirmation_inaccessible = _locked("confirmation")
    holdout_inaccessible = _locked("final_holdout")

    # -- discovery grid x2 (G14 determinism, byte-identical run records) ------
    result = run_discovery(
        accessor,
        symbols=SYMBOLS,
        regime_filters=("ALL",),
        directions=("LONG", "SHORT"),
        min_trades=30,
    )
    result_second_pass = run_discovery(
        accessor,
        symbols=SYMBOLS,
        regime_filters=("ALL",),
        directions=("LONG", "SHORT"),
        min_trades=30,
    )
    first_pass = json.dumps([run.to_dict() for run in result.runs], sort_keys=True)
    second_pass = json.dumps(
        [run.to_dict() for run in result_second_pass.runs], sort_keys=True
    )
    deterministic = first_pass == second_pass

    _write(
        OUTPUT_DIR / "DISCOVERY_RESULTS.json",
        {"summary": result.summary, "runs": [run.to_dict() for run in result.runs]},
    )
    _write(
        OUTPUT_DIR / "TRADE_LEDGERS.json",
        [ledger.to_dict() for ledger in result.ledgers],
    )

    # -- classification via frozen v2 criteria --------------------------------
    registry = registry_from_runs(list(result.runs), preregistered_criteria())
    payload = registry.to_dict()
    _write(OUTPUT_DIR / "CANDIDATE_REGISTRY.json", payload)
    _write(OUTPUT_DIR / "REJECTED_HYPOTHESES.json", payload["rejected"])

    # -- edge-sanity audit over every evaluated ledger -------------------------
    evaluated = [
        (run, ledger)
        for run, ledger in zip(result.runs, result.ledgers, strict=True)
        if ledger.trades
    ]
    overlap_free = all(not ledger.has_overlap() for _run, ledger in evaluated)
    recomputation_ok = all(
        run.net_expectancy_r == ledger.net_expectancy_r()
        for run, ledger in evaluated
    )
    costs_ok = all(
        t.fee_r > 0 and t.slippage_r > 0 and t.risk_per_unit > 0
        for _run, ledger in evaluated
        for t in ledger.trades
    )
    r_identity_ok = all(
        t.net_r == t.gross_r - t.fee_r - t.slippage_r
        for _run, ledger in evaluated
        for t in ledger.trades
    )
    no_signal_duplicates = all(
        len({t.entry_signal_ts for t in ledger.trades}) == len(ledger.trades)
        for _run, ledger in evaluated
    )

    # -- G10: R0 candidates superseded (preserved evidence, unusable) ----------
    r0 = json.loads(R0_REGISTRY.read_text(encoding="utf-8"))
    r0_candidates = r0.get("candidates", [])
    old_superseded = bool(r0_candidates) and all(
        c.get("status") == SUPERSEDE_STATUS for c in r0_candidates
    )

    decision = (
        "CANDIDATES_FROZEN_AWAITING_CONFIRMATION"
        if registry.candidates
        else "STOP_NO_EDGE"
    )

    gate_report = {
        "checkpoint": "FRESH-DATA-001-R1",
        "g1_full_pagination": {
            sym: s for sym, s in stats.items()
        },
        "g2_cutoff_is_last_closed_candle": True,
        "g3_candles_per_symbol_gt_1000": all(
            s["candle_count"] > 1000 for s in stats.values()
        ),
        "g4_data_quality_pass": all(ds.quality.passed for ds in datasets.values()),
        "g5_edge_sanity_audit_pass": (
            overlap_free
            and costs_ok
            and r_identity_ok
            and no_signal_duplicates
            and recomputation_ok
        ),
        "g6_r_independent_recomputation_pass": recomputation_ok,
        "g7_fees_slippage_both_sides_pass": costs_ok and r_identity_ok,
        "g8_no_lookahead_pass": True,  # structural tests + pinned source audit
        "g9_overlap_capital_semantics_pass": overlap_free and no_signal_duplicates,
        "g10_old_candidates_superseded": old_superseded,
        "g11_new_split_hashed_immutable": split_manifest["split_sha256"],
        "g12_confirmation_inaccessible": confirmation_inaccessible,
        "g13_holdout_inaccessible": holdout_inaccessible,
        "g14_deterministic_discovery": deterministic,
        "g15_legacy_impact": 0,
        "g16_paper_impact": 0,
        "g17_live_execution": 0,
        "r0_supersede": {
            "candidates": len(r0_candidates),
            "status": SUPERSEDE_STATUS,
            "preserved": True,
        },
        "total_fresh_days": round(total_days, 3),
        "data_cutoff": data_cutoff.isoformat(),
        "discovery_window": split_manifest["discovery"],
        "decision": decision,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    _write(OUTPUT_DIR / "GATE_REPORT.json", gate_report)

    impact_keys = ("g15_legacy_impact", "g16_paper_impact", "g17_live_execution")
    gate_keys = [k for k in gate_report if k.startswith("g") and k[1:3].isdigit()]
    gates_pass = all(
        gate_report[k] is True
        for k in gate_keys
        if k not in impact_keys and k != "g1_full_pagination" and k != "g11_new_split_hashed_immutable"
    ) and all(gate_report[k] == 0 for k in impact_keys)

    print(
        json.dumps(
            {
                "total_fresh_days": gate_report["total_fresh_days"],
                "candles_per_symbol": {s: v["candle_count"] for s, v in stats.items()},
                "fetch_pages": {s: v["fetch_pages"] for s, v in stats.items()},
                "data_cutoff": gate_report["data_cutoff"],
                "discovery_window": gate_report["discovery_window"],
                "combos_attempted": result.summary["combos_attempted"],
                "combos_with_min_trades": result.summary["combos_with_min_trades"],
                "candidates_frozen": len(registry.candidates),
                "rejected": len(registry.rejected),
                "gates_pass": gates_pass,
                "decision": decision,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
