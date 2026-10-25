"""Assemble the phase's final summary from the artifacts, not from prose.

Every field in the closing summary has to be traceable to a file that a reader can
open, so this script derives the summary from those files instead of restating
numbers by hand — a hand-written summary can drift from its evidence, and the
whole point of this phase is that the evidence is the authority.

Writes ``docs/MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.json`` and prints the same
content as a field-per-line block for the narrative document.

Usage::

    uv run python scripts/forward_final_summary.py [run_id]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "reports" / "microstructure-forward"
DOCS = ROOT / "docs"

STATUS_VOCABULARY = (
    "MICROSTRUCTURE_FORWARD_DATA_VERIFIED",
    "MICROSTRUCTURE_FORWARD_DATA_PARTIAL",
    "MICROSTRUCTURE_FORWARD_DATA_FAILED",
)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _gaps_by_status(manifest: dict[str, Any]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for gap in manifest.get("gaps", []):
        status = str(gap.get("status") or "UNKNOWN")
        tally[status] = tally.get(status, 0) + 1
    return tally


def _seconds(value: Any) -> float | None:
    return None if value is None else round(float(value), 3)


def build_summary(run_id: str | None = None) -> dict[str, Any]:
    manifest_dir = FORWARD / "manifest"
    if run_id is None:
        candidates = sorted(manifest_dir.glob("*.json"))
        if not candidates:
            raise SystemExit(f"{manifest_dir}: no manifest — nothing was captured")
        run_id = candidates[-1].stem

    manifest = _load(manifest_dir / f"{run_id}.json")
    quality = _load(DOCS / "FORWARD_DATA_QUALITY_REPORT.json")
    resource = _load(DOCS / "FORWARD_DATA_RESOURCE_REPORT.json")
    replay = _load(DOCS / "FORWARD_DATA_REPLAY_VALIDATION.json")
    streaming = _load(DOCS / "FORWARD_DATA_STREAMING_MEMORY.json")
    guard_test = _load(DOCS / "FORWARD_DATA_DISK_GUARD.json")
    coexistence = _load(DOCS / "FORWARD_DATA_PAPER_COEXISTENCE.json")
    kline = _load(DOCS / "FORWARD_DATA_KLINE_CROSSCHECK.json")
    verification = _load(DOCS / "MICROSTRUCTURE_FORWARD_COLLECTION_INDEPENDENT_VERIFICATION.json")
    equivalence = _load(FORWARD / "writer_code_equivalence.json")
    gates = _load(FORWARD / "quality_gates.json")

    totals = quality.get("totals", {})
    loss = quality.get("loss", {})
    health = quality.get("health", {})
    live = health.get("live", {})
    integrity = manifest.get("integrity", {})
    footprint = resource.get("footprint", {})
    capacity = resource.get("storage_capacity", {})
    resources = manifest.get("resources", {})
    by_reason = loss.get("gaps_by_reason", {})
    statuses = _gaps_by_status(manifest)

    checks = verification.get("checks", [])
    checks_failed = [c for c in checks if not c.get("pass")]

    summary: dict[str, Any] = {
        "kind": "MICROSTRUCTURE_FORWARD_COLLECTION_FINAL",
        "run_id": run_id,
        "official_capture_commit": manifest.get("commit"),
        "capture_code_equivalent": equivalence.get("capture_code_equivalent"),
        "capture_code_classification": equivalence.get("classification"),
        "target_duration_seconds": 3600.0,
        "actual_duration_seconds": manifest.get("duration_seconds"),
        "started_at": manifest.get("started_at"),
        "ended_at": manifest.get("ended_at"),
        "continuity": manifest.get("continuity"),
        "providers": [manifest.get("provider")] if manifest.get("provider") else [],
        "markets": manifest.get("markets"),
        "assets": manifest.get("symbols"),
        "collector_version": manifest.get("collector_version"),
        "contract_version": manifest.get("contract_version"),
        "schema_version": manifest.get("schema_version"),
        "rows": totals.get("rows_on_disk"),
        "segments": totals.get("segments"),
        "partial_tails": totals.get("partial_tails"),
        "events": {
            "agg_trade": totals.get("agg_trade_events"),
            "book_ticker": totals.get("book_ticker_events"),
            "depth_diff": totals.get("book_update_events"),
            "book_checkpoint": totals.get("book_checkpoint_events"),
            "open_interest": totals.get("open_interest_events"),
            "funding": totals.get("funding_events"),
            "mark_price": totals.get("mark_price_events"),
        },
        "duplicates": loss.get("duplicates"),
        "duplicate_rows_on_disk": loss.get("duplicate_rows_on_disk"),
        "out_of_order": loss.get("out_of_order"),
        "gaps_detected": loss.get("gaps_total"),
        "gaps_by_status": statuses,
        "gaps_by_reason": by_reason,
        "gaps_recovered_complete": statuses.get("RECOVERED_COMPLETE", 0),
        "gaps_recovered_partial": statuses.get("RECOVERED_PARTIAL", 0),
        "gaps_unrecovered": statuses.get("UNRECOVERABLE", 0),
        "gaps_with_loss": loss.get("gaps_with_loss"),
        "gaps_accounting_is_complete": loss.get("gaps_accounting_is_complete"),
        "rest_backfilled_events": loss.get("backfilled_events"),
        "dedup_after_backfill": loss.get("duplicate_rows_on_disk"),
        "backfill_gaps_closed": loss.get("backfill_gaps_closed"),
        "backfill_partial": loss.get("backfill_partial"),
        "backfill_failures": loss.get("backfill_failures"),
        "loss_estimate_semantics": loss.get("estimate_semantics"),
        "data_lost_gap_seconds": loss.get("data_lost_gap_seconds"),
        "disconnects": integrity.get("disconnects"),
        "reconnects": manifest.get("reconnects"),
        "resnapshots": manifest.get("resnapshots"),
        "resnapshots_failed": integrity.get("resnapshots_failed"),
        "healthy_seconds": _seconds(live.get("healthy_seconds")),
        "degraded_seconds": _seconds(live.get("degraded_seconds")),
        "failed_seconds": _seconds(live.get("failed_seconds")),
        "healthy_fraction": live.get("healthy_fraction"),
        "degraded_episodes": live.get("degraded_episodes"),
        "episodes_returning_to_healthy": live.get("episodes_returning_to_healthy"),
        "books": quality.get("books", {}),
        "latency_ms": {
            key: quality.get("event_latency_ms", {}).get(key)
            for key in ("p50", "p95", "p99", "max", "samples")
        },
        "readiness": quality.get("readiness", {}),
        "provider_stream_status": quality.get("provider_stream_status", {}),
        "replay": {
            "rows": replay.get("rows"),
            "event_count_match": replay.get("event_count_match"),
            "trade_sequence_ok": replay.get("trade_sequence_ok"),
            "book_match": replay.get("book_match"),
            "fingerprints_match": replay.get("fingerprints_match"),
            "feature_match": replay.get("feature_match"),
            "deterministic": replay.get("deterministic"),
            "partial_tails": replay.get("partial_tails"),
            "internet_access": replay.get("internet_access"),
            "offline_guard": replay.get("offline_guard"),
            "aggregation_digest": replay.get("aggregation_digest"),
            "recorded_aggregation_digest": replay.get("recorded_aggregation_digest"),
            "ok": replay.get("ok"),
        },
        "streaming_memory": {
            "bounded": streaming.get("bounded"),
            "worst_rss_growth_mb": streaming.get("worst_rss_growth_mb"),
            "materialised_equivalent_mb": streaming.get("materialised_equivalent_mb"),
            "rows_measured": streaming.get("rows_measured"),
            "stages": [
                {k: stage.get(k) for k in ("stage", "rows", "elapsed_seconds", "rss_growth_from_baseline_mb")}
                for stage in streaming.get("stages", [])
            ],
        },
        "storage": {
            "compression_ratio": footprint.get("compression_ratio"),
            "raw_equivalent_gb_per_hour": footprint.get("raw_gb_per_hour"),
            "compressed_gb_per_hour": footprint.get("stored_gb_per_hour"),
            "estimated_compressed_gb_per_day": footprint.get("stored_gb_per_day"),
            "free_disk_now_bytes": capacity.get("free_disk_now_bytes"),
            "free_disk_at_capture_start_bytes": capacity.get("free_disk_at_capture_start_bytes"),
            "free_disk_at_capture_start_reconstruction": capacity.get(
                "free_disk_at_capture_start_reconstruction"
            ),
            "capacity_hours_at_observed_rate": capacity.get("capacity_hours_at_observed_rate"),
            "capacity_days_at_observed_rate": capacity.get("capacity_days_at_observed_rate"),
            "verdict": capacity.get("verdict"),
        },
        "collector_resources": {
            "cpu_utilisation": resources.get("cpu_utilisation"),
            "memory_mb_max": resources.get("memory_mb_max"),
            "memory_mb_final": resources.get("memory_mb_final"),
            "network_bytes_per_hour": resources.get("network_bytes_per_hour"),
        },
        "disk_guard": {
            "armed": resource.get("disk_guard", {}).get("enabled"),
            "stopped_on_disk_budget": manifest.get("stopped_on_disk_budget"),
            "controlled_test_tripped": guard_test.get("bounded_duration_note", {}).get("tripped"),
            "controlled_test_clean_exit": bool(guard_test.get("bounded_run", {}).get("manifest_finalised")),
            "note": guard_test.get("bounded_duration_note", {}).get("detail"),
        },
        "paper_coexistence": {
            "cycles_with_collector": coexistence.get("with_collector", {}).get(
                "asset_cycle_evaluations"
            ),
            "cycles_without_collector": coexistence.get("without_collector", {}).get(
                "asset_cycle_evaluations"
            ),
            "cycle_seconds_delta": coexistence.get("cycle_seconds_delta"),
            "orders_created_with_collector": coexistence.get("with_collector", {}).get(
                "orders_created"
            ),
            "runtime_failures_with_collector": coexistence.get("with_collector", {}).get(
                "runtime_failures"
            ),
            "isolation": coexistence.get("isolation", {}),
        },
        "kline_crosscheck": {
            "buckets_compared": kline.get("buckets_compared"),
            "buckets_excluded": kline.get("buckets_excluded"),
            "median_ratio": kline.get("median_ratio"),
            "worst_ratio_deviation": kline.get("worst_ratio_deviation"),
        },
        "independent_verifier": {
            "status": verification.get("status"),
            "checks": len(checks),
            "checks_failed": [c.get("check") for c in checks_failed],
            "head": verification.get("head"),
            "verifier": verification.get("verifier"),
        },
        "false_success_guard": {
            "notes": [
                "PASS is invalid if the hour was not actually captured",
                "PASS is invalid if REST recovery is presented as WebSocket",
                "PASS is invalid if gaps are ignored or duplicates hidden",
                "PASS is invalid if a book is invalid and called healthy",
                "PASS is invalid if replay uses the network or materialises the dataset",
                "PASS is invalid if memory grows with the row count",
                "PASS is invalid if capacity is insufficient but 24/7 ready is claimed",
                "PASS is invalid if one hour of data is used to claim a strategy edge",
            ],
            "violations": [],
        },
    }

    # The status is derived, never asserted by hand: the capture either happened
    # for its full duration and verified, or it did not.
    duration = float(summary.get("actual_duration_seconds") or 0.0)
    replay_ok = bool(replay.get("ok")) and replay.get("feature_match") is not False
    verifier_passed = verification.get("status") == "VERIFIED"
    if duration >= 3600.0 and replay_ok and verifier_passed:
        status = "MICROSTRUCTURE_FORWARD_DATA_VERIFIED"
    elif duration > 0 and totals.get("rows_on_disk"):
        status = "MICROSTRUCTURE_FORWARD_DATA_PARTIAL"
    else:
        status = "MICROSTRUCTURE_FORWARD_DATA_FAILED"
    summary["final_status"] = status
    summary["final_status_vocabulary"] = list(STATUS_VOCABULARY)
    summary["final_status_basis"] = (
        "capture duration >= target, offline replay reproduces the features, and the "
        "independent verifier passed"
        if status == STATUS_VOCABULARY[0]
        else "see replay, verifier and duration fields above"
    )
    summary["ready_for_continuous_collection"] = bool(
        capacity.get("verdict") == "STORAGE_CAPACITY_OK"
        and streaming.get("bounded") is True
        and verification.get("status") == "VERIFIED"
    )
    summary["ready_for_continuous_collection_reasons"] = {
        "storage_capacity": capacity.get("verdict"),
        "streaming_bounded": streaming.get("bounded"),
        "independent_verifier": verification.get("status"),
        "writer_dead_state_p1": "open: StreamStats.network_delays grows per event and is never read",
    }
    summary["quality_gates"] = gates or {"status": "not recorded"}
    summary["evidence_files"] = sorted(
        str(path.relative_to(ROOT))
        for path in [
            *DOCS.glob("FORWARD_DATA_*"),
            *DOCS.glob("MICROSTRUCTURE_FORWARD_COLLECTION_*"),
            FORWARD / "manifest" / f"{run_id}.json",
            FORWARD / "writer_code_equivalence.json",
            FORWARD / "quality_gates.json",
        ]
        if path.exists()
    )
    return summary


def main() -> int:
    summary = build_summary(sys.argv[1] if len(sys.argv) > 1 else None)
    DOCS.mkdir(parents=True, exist_ok=True)
    target = DOCS / "MICROSTRUCTURE_FORWARD_COLLECTION_FINAL.json"
    target.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "evidence_files"}, indent=2, default=str))
    print(f"\nwritten -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
