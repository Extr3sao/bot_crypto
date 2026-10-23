"""Measure the real capture, choose a retention policy, report the capacity (§5-§11).

The question this answers is not "how much disk do we have" but "how long can
this run continuously under a policy that the disk can actually afford". It
refuses to guess:

* the raw rate comes from a real capture manifest, not from a projection;
* the aggregate rate comes from compacting one real window of real segments
  (hard-linked into scratch, so the measurement costs no disk space and the
  verified capture is never touched);
* the raw hot window is derived from free disk minus a reserve, so the disk
  guard keeps something to guard.

Usage::

    uv run python scripts/forward_storage_policy.py \\
        --root reports/microstructure-forward \\
        --out reports/microstructure-forward-storage-policy/CAPACITY_REPORT.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.forward.retention import (  # noqa: E402
    RAW_ROOT,
    RetentionPolicy,
    apply_retention,
    capacity_report,
    plan_retention,
    policy_for_host,
)
from trading_bot.research.forward.storage import load_manifest  # noqa: E402

BYTES_PER_GIB = 1024**3


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def load_capture_rates(root: Path) -> dict[str, Any]:
    """Raw throughput and rotation straight from the certified manifest."""
    manifest_dir = root / "manifest"
    manifests = sorted(manifest_dir.glob("*.json"))
    if not manifests:
        raise SystemExit(f"no manifest under {manifest_dir}")
    path = manifests[-1]
    manifest = load_manifest(path)
    duration = float(manifest.get("duration_seconds") or 0.0)
    if duration <= 0:
        raise SystemExit(f"{path} has no duration; cannot derive a rate")
    written = int(manifest.get("bytes_written") or 0)
    uncompressed = int(manifest.get("uncompressed_bytes_written") or 0)
    streams = sorted(
        f"{entry['market']}/{entry['symbol']}/{entry['event_type']}"
        for entry in manifest.get("streams", [])
    )
    return {
        "manifest": str(path.relative_to(REPO_ROOT)),
        "run_id": manifest.get("run_id"),
        "rotation_seconds": int(manifest.get("rotation_seconds") or 3600),
        "duration_seconds": duration,
        "bytes_written": written,
        "uncompressed_bytes_written": uncompressed,
        "compressed_bytes_per_day": written * 86_400 / duration,
        "uncompressed_bytes_per_day": uncompressed * 86_400 / duration,
        "compression_ratio": (uncompressed / written) if written else None,
        "streams": streams,
        "stream_count": len(streams),
        "row_count": sum(int(entry["events"]) for entry in manifest.get("streams", [])),
        "gaps": manifest.get("gaps", []),
        "stale_after_ms": manifest.get("stale_after_ms"),
    }


def hard_link_tree(root: Path, scratch: Path, segments: list[Path]) -> list[Path]:
    """Mirror segments into scratch with hard links: same bytes, no new space."""
    linked: list[Path] = []
    for source in segments:
        relative = source.relative_to(root)
        target = scratch / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        linked.append(target)
    return linked


def measure_aggregate_rate(
    root: Path,
    rates: dict[str, Any],
    *,
    scratch: Path | None = None,
) -> dict[str, Any]:
    """Compact one real window and turn its output size into a daily rate."""
    rotation = int(rates["rotation_seconds"])
    segments = sorted((root / RAW_ROOT).rglob("*.jsonl.gz"))
    if not segments:
        raise SystemExit(f"no raw segments under {root / RAW_ROOT}")

    # One rotation window, every stream: the streams are what an aggregate's size
    # actually scales with, so a single stream would not be a measurement.
    def window_of(path: Path) -> int:
        stamp = path.name.split(".")[0]
        date = path.parent.name
        moment = datetime.strptime(f"{date} {stamp}", "%Y-%m-%d %H%M%S").replace(tzinfo=UTC)
        return int(moment.timestamp() * 1000)

    windows: dict[int, list[Path]] = {}
    for path in segments:
        windows.setdefault(window_of(path), []).append(path)
    start = sorted(windows)[0]
    selected = windows[start]

    owned_scratch = scratch is None
    scratch = scratch or Path(tempfile.mkdtemp(prefix="forward-storage-policy-"))
    try:
        linked = hard_link_tree(root, scratch, selected)
        policy = RetentionPolicy(
            rotation_seconds=rotation,
            raw_hot_hours=0.0,  # measure only: never delete anything here
            sealed_grace_seconds=0,
        )
        # Files are hard-linked, so their mtime is the capture's: recent enough to
        # fail the grace check. Age the links, not the originals.
        old = time.time() - 86_400
        for path in linked:
            os.utime(path, (old, old))
        now_ms = int(time.time() * 1000) + 86_400_000
        plan = plan_retention(scratch, policy, str(rates["run_id"]), now_ms=now_ms)
        windows_planned = len(plan.compactable)
        run = apply_retention(
            scratch,
            policy,
            str(rates["run_id"]),
            allow_delete=False,
            gaps=rates["gaps"],
            now_ms=now_ms,
        )
        outputs: list[dict[str, Any]] = []
        total_bytes = 0
        total_rows = 0
        source_rows = 0
        source_bytes = 0
        for result in run.compacted:
            record = result.lineage
            output = scratch / record.output_path
            total_bytes += output.stat().st_size
            total_rows += record.output_rows
            source_rows += sum(source.rows for source in record.sources)
            source_bytes += sum(source.bytes for source in record.sources)
            outputs.append(
                {
                    "window_start_ms": record.window_start_ms,
                    "output_path": record.output_path,
                    "output_bytes": record.output_bytes,
                    "output_sha256": record.output_sha256,
                    "output_rows": record.output_rows,
                    "source_count": len(record.sources),
                    "source_rows": sum(source.rows for source in record.sources),
                    "lineage_id": record.lineage_id,
                    "lineage_loss_windows_applied": record.loss_windows_applied,
                }
            )
        declared_streams = int(rates["stream_count"])
        observed_streams = max(1, len(linked))
        scale = declared_streams / observed_streams
        windows_per_day = 86_400 / rotation
        aggregate_bytes_per_day = total_bytes * scale * windows_per_day
        return {
            "measured": True,
            "windows_compacted": len(run.compacted),
            "windows_planned": windows_planned,
            "window_start_ms": start,
            "window_rotation_seconds": rotation,
            "streams_in_window": observed_streams,
            "streams_declared": declared_streams,
            "scale_to_full_capture": scale,
            "windows_per_day": windows_per_day,
            "window_output_bytes": total_bytes,
            "window_output_rows": total_rows,
            "window_source_rows": source_rows,
            "window_source_bytes": source_bytes,
            "aggregate_bytes_per_day": aggregate_bytes_per_day,
            "aggregation_expansion": (total_bytes / source_bytes) if source_bytes else None,
            "refused": run.refused[:10],
            "outputs": outputs,
            "measured_at_ms": int(time.time() * 1000),
        }
    finally:
        if owned_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="reports/microstructure-forward")
    parser.add_argument(
        "--out", default="reports/microstructure-forward-storage-policy/CAPACITY_REPORT.json"
    )
    parser.add_argument("--reserve-mib", type=int, default=384)
    parser.add_argument("--target-days", type=int, default=7)
    parser.add_argument("--max-raw-hot-hours", type=float, default=24.0)
    parser.add_argument("--fill-fraction", type=float, default=0.5)
    parser.add_argument(
        "--reports-bytes-per-day",
        type=float,
        default=2e6,
        help="DECLARED assumption (operator-produced reports), not a measurement",
    )
    parser.add_argument(
        "--skip-measurement",
        action="store_true",
        help="reuse the aggregate rate already recorded in --out instead of compacting again",
    )
    args = parser.parse_args()

    root = (REPO_ROOT / args.root).resolve()
    out = (REPO_ROOT / args.out).resolve()
    rates = load_capture_rates(root)
    free = free_bytes(root)

    previous: dict[str, Any] = {}
    if out.exists():
        previous = json.loads(out.read_text(encoding="utf-8"))
    if args.skip_measurement and previous.get("aggregate_measurement"):
        measurement = previous["aggregate_measurement"]
    else:
        measurement = measure_aggregate_rate(root, rates)

    policy = policy_for_host(
        free_bytes=free,
        compressed_bytes_per_day=rates["compressed_bytes_per_day"],
        aggregate_bytes_per_day=measurement["aggregate_bytes_per_day"],
        reserve_bytes=args.reserve_mib * 1024 * 1024,
        target_operating_days=args.target_days,
        max_raw_hot_hours=args.max_raw_hot_hours,
        fill_fraction=args.fill_fraction,
    )
    capacity = capacity_report(
        free_bytes=free,
        policy=policy,
        compressed_bytes_per_day=rates["compressed_bytes_per_day"],
        aggregate_bytes_per_day=measurement["aggregate_bytes_per_day"],
        reports_bytes_per_day=args.reports_bytes_per_day,
    )

    payload: dict[str, Any] = {
        "generated_at_ms": int(time.time() * 1000),
        "root": str(root.relative_to(REPO_ROOT)),
        "raw_capture": rates,
        "aggregate_measurement": measurement,
        "policy": policy.as_dict(),
        "capacity": capacity.as_dict(),
        "assumptions": {
            "reserve_mib": args.reserve_mib,
            "fill_fraction": args.fill_fraction,
            "target_operating_days": args.target_days,
            "reports_bytes_per_day_declared": args.reports_bytes_per_day,
            "aggregate_rate_is_measured": True,
            "note": (
                "the raw rate comes from a real capture manifest; the aggregate rate "
                "comes from compacting one real window; the reports rate is a declared "
                "assumption for operator-produced artifacts"
            ),
        },
        "layers": {
            "raw": "segments/ (hot, bounded by the policy window)",
            "aggregated": "aggregated/ (1m/5m/15m/30m, retained indefinitely)",
            "reports": "reports/ (manifests, quality and verification, never deleted)",
        },
        "policy_probe": {
            "raw_hot_hours_evaluated": [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0],
            "results": [
                {
                    "raw_hot_hours": hours,
                    "verdict": capacity_report(
                        free_bytes=free,
                        policy=RetentionPolicy(
                            raw_hot_hours=hours,
                            reserve_bytes=args.reserve_mib * 1024 * 1024,
                            target_operating_days=args.target_days,
                        ),
                        compressed_bytes_per_day=rates["compressed_bytes_per_day"],
                        aggregate_bytes_per_day=measurement["aggregate_bytes_per_day"],
                        reports_bytes_per_day=args.reports_bytes_per_day,
                    ).verdict,
                    "raw_hot_steady_state_gb": round(
                        hours * rates["compressed_bytes_per_day"] / 24 / 1e9, 3
                    ),
                }
                for hours in (1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0)
            ],
        },
        "long_horizon_raw": (
            "Raw microstructure beyond the hot window is not retained on this host; "
            "long-horizon raw research requires EXTERNAL_STORAGE_REQUIRED."
        ),
        "commit": os.popen("git rev-parse HEAD").read().strip(),
        "raw_artifacts_hashed": [
            {"path": entry["output_path"], "sha256": entry["output_sha256"]}
            for entry in measurement.get("outputs", [])
        ][:5],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 78)
    print("STORAGE POLICY / CAPACITY")
    print("=" * 78)
    print(f"free disk            : {capacity.free_bytes / 1e9:.3f} GB")
    print(f"compressed raw       : {rates['compressed_bytes_per_day'] / 1e9:.3f} GB/day")
    print(f"uncompressed raw     : {rates['uncompressed_bytes_per_day'] / 1e9:.3f} GB/day")
    print(f"compression ratio    : {rates['compression_ratio']:.3f}x")
    print(f"aggregate rate       : {measurement['aggregate_bytes_per_day'] / 1e6:.3f} MB/day")
    print(f"raw hot window       : {policy.raw_hot_hours:.1f} h")
    print(f"raw steady state     : {capacity.raw_hot_steady_state_bytes / 1e9:.3f} GB")
    print(f"headroom             : {capacity.headroom_bytes / 1e9:.3f} GB")
    print(f"hours w/o compaction : {capacity.hours_until_guard_without_compaction:.2f}")
    print(f"estimated days       : {capacity.estimated_operating_days}")
    print(f"VERDICT              : {capacity.verdict}")
    print(f"report               : {out.relative_to(REPO_ROOT)}")
    if measurement.get("outputs"):
        print(f"aggregate hash       : {measurement['outputs'][0]['output_sha256']}")
    return 0 if capacity.verdict == "VIABLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
