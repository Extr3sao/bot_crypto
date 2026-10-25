"""Retention driver: compact what is due, and delete raw only under pressure (§5-§11).

Compaction always runs — the aggregate is the long-term record, so making it is
never optional. Deletion is *demand driven*: it happens only when the disk is
below a threshold the operator derived from the capacity report. That is the
disk guard's job done properly: reclaim space that has already been replaced,
instead of stopping a capture that was filling the disk.

    uv run python scripts/forward_retention.py \
        --root reports/microstructure-forward-lab \
        --run-id <run-id> \
        --raw-hot-hours 2 --rotation-seconds 900 \
        --delete-when-free-below 1200000000 \
        --loop --interval 600
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.paper_loop import wait_for_stop_file  # noqa: E402
from trading_bot.research.forward.preservation import PreservationPolicy  # noqa: E402
from trading_bot.research.forward.retention import (  # noqa: E402
    RetentionPolicy,
    apply_retention,
    plan_retention,
    tier_plan,
)
from trading_bot.research.forward.storage import latest_run_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="reports/microstructure-forward-lab")
    parser.add_argument(
        "--data-root",
        default=None,
        help=("§16 — alias for --root, so the policy can be pointed at another volume"),
    )
    parser.add_argument("--run-id", default=None, help="default: the newest run in --root")
    parser.add_argument("--rotation-seconds", type=int, default=900)
    parser.add_argument("--raw-hot-hours", type=float, default=2.0)
    parser.add_argument("--sealed-grace-seconds", type=int, default=1800)
    parser.add_argument("--reserve-mib", type=int, default=384)
    parser.add_argument(
        "--delete-when-free-below",
        type=int,
        default=0,
        help="bytes; 0 disables deletion entirely (report/compact only)",
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what retention would retain/compact/delete/reclaim, touch nothing",
    )
    parser.add_argument("--interval", type=float, default=600.0)
    parser.add_argument("--max-iterations", type=int, default=0, help="0 = until stopped")
    parser.add_argument(
        "--stop-file",
        default=None,
        help="path whose appearance stops the worker gracefully between passes (§51)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="JSON report path (default <root>/reports/RETENTION_REPORT.json)",
    )
    parser.add_argument(
        "--no-preserve-m03",
        action="store_true",
        help="do not require M-03 to survive compaction before raw is deleted",
    )
    parser.add_argument(
        "--no-preserve-m07",
        action="store_true",
        help="do not require M-07 to survive compaction before raw is deleted",
    )
    parser.add_argument(
        "--m03-min-resolution-minutes",
        type=int,
        default=1,
        help=(
            "resolution M-03 must be measurable at after deletion; 0 asks for "
            "quote-level microstructure, which no compact tier preserves, so raw "
            "is retained"
        ),
    )
    parser.add_argument(
        "--m07-min-resolution-minutes",
        type=int,
        default=1,
        help="resolution M-07 must be measurable at after deletion",
    )
    return parser.parse_args()


def _preservation(args: argparse.Namespace) -> PreservationPolicy:
    """Defaults are the safe ones, so a partial namespace still preserves data."""
    return PreservationPolicy(
        require_m03=not getattr(args, "no_preserve_m03", False),
        require_m07=not getattr(args, "no_preserve_m07", False),
        m03_min_resolution_minutes=int(getattr(args, "m03_min_resolution_minutes", 1)),
        m07_min_resolution_minutes=int(getattr(args, "m07_min_resolution_minutes", 1)),
    )


def _policy(args: argparse.Namespace) -> RetentionPolicy:
    return RetentionPolicy(
        rotation_seconds=args.rotation_seconds,
        raw_hot_hours=args.raw_hot_hours,
        sealed_grace_seconds=args.sealed_grace_seconds,
        reserve_bytes=args.reserve_mib * 1024 * 1024,
    )


def _segment_bytes(paths: list[Path], root: Path) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:  # pragma: no cover - the file vanished under us
            continue
    return total


def dry_run_once(args: argparse.Namespace, run_id: str, root: Path) -> dict[str, Any]:
    """§5 — say exactly what would happen, and change nothing on disk.

    This is the safety report an operator reads *before* letting retention delete
    anything: how much raw would be retained, which windows would be compacted,
    which segments would become eligible, and how much space that would reclaim.
    """
    policy = _policy(args)
    free = shutil.disk_usage(root if root.exists() else REPO_ROOT).free
    allow_delete = args.delete_when_free_below > 0 and free < args.delete_when_free_below
    plan = plan_retention(root, policy, run_id)
    deletable_bytes = _segment_bytes([path for path, _why in plan.deletable], root)
    compactable_sources = [path for _start, _end, files in plan.compactable for path in files]
    would_compact_bytes = _segment_bytes(compactable_sources, root)
    return {
        "timestamp_ms": int(time.time() * 1000),
        "dry_run": True,
        "root": str(root.relative_to(REPO_ROOT)) if root.is_relative_to(REPO_ROOT) else str(root),
        "run_id": run_id,
        "policy": policy.as_dict(),
        "free_bytes": free,
        "delete_threshold_bytes": args.delete_when_free_below,
        "deletion_would_be_enabled": allow_delete,
        "would_retain_raw_segments": len(plan.retained_raw),
        "would_retain_raw_bytes": _segment_bytes(plan.retained_raw, root),
        "would_compact_windows": len(plan.compactable),
        "would_compact_segments": len(compactable_sources),
        "would_compact_bytes": would_compact_bytes,
        "would_delete_segments": len(plan.deletable),
        "would_reclaim_bytes": deletable_bytes,
        "tiers": [spec.as_dict() for spec in tier_plan(policy)],
        "preservation_policy": _preservation(args).as_dict(),
        "would_skip": plan.skipped[:50],
        "deletable": [
            {"path": path.relative_to(root).as_posix(), "lineage_id": why}
            for path, why in plan.deletable[:200]
        ],
        "no_blind_deletion": (
            "a segment is only ever listed as deletable when a lineage record "
            "naming every source hash exists AND the aggregate still re-hashes "
            "to the hash that record stored"
        ),
        "dry_run_changed_nothing": True,
    }


def run_once(args: argparse.Namespace, run_id: str, root: Path) -> dict[str, Any]:
    policy = _policy(args)
    free = shutil.disk_usage(root if root.exists() else REPO_ROOT).free
    allow_delete = args.delete_when_free_below > 0 and free < args.delete_when_free_below
    plan = plan_retention(root, policy, run_id)
    preservation = _preservation(args)
    outcome = apply_retention(
        root,
        policy,
        run_id,
        allow_delete=allow_delete,
        gaps=_manifest_gaps(root, run_id),
        preservation=preservation,
    )
    report = {
        "timestamp_ms": int(time.time() * 1000),
        "root": str(root.relative_to(REPO_ROOT)) if root.is_relative_to(REPO_ROOT) else str(root),
        "run_id": run_id,
        "policy": policy.as_dict(),
        "tiers": [spec.as_dict() for spec in tier_plan(policy)],
        "preservation_policy": preservation.as_dict(),
        "free_bytes": free,
        "delete_threshold_bytes": args.delete_when_free_below,
        "deletion_enabled": allow_delete,
        "planned_compactable_windows": len(plan.compactable),
        "planned_deletable_segments": len(plan.deletable),
        "retained_raw_segments": len(plan.retained_raw),
        "result": outcome.as_dict(),
        "compacted": len(outcome.compacted),
        "deleted": len(outcome.deleted),
        "freed_bytes": outcome.freed_bytes,
        "no_blind_deletion": (
            "raw is removed only after a lineage record naming every source hash "
            "exists and the aggregate still re-hashes to what it recorded"
        ),
    }
    return report


def _manifest_gaps(root: Path, run_id: str) -> list[dict[str, Any]]:
    """Declared data loss, so a bucket overlapping a hole is never "complete"."""
    path = root / "manifest" / f"{run_id}.json"
    if not path.exists():
        candidates = sorted((root / "manifest").glob("*.json"))
        if not candidates:
            return []
        path = candidates[-1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    gaps = payload.get("gaps")
    return gaps if isinstance(gaps, list) else []


def main() -> int:
    args = parse_args()
    if args.data_root:
        args.root = args.data_root
    root = (REPO_ROOT / args.root).resolve()
    stop_file = Path(args.stop_file).expanduser() if args.stop_file else None
    run_id = ""
    # Under --loop this is a long-lived worker, so a capture that has not created
    # its root yet is a reason to wait rather than to exit. Exiting here used to
    # lose the compaction worker for the whole run on the very first pass, which
    # is exactly when a small volume needs it.
    while not run_id:
        root = (REPO_ROOT / args.root).resolve()
        candidate = (args.run_id or latest_run_id(root)) if root.exists() else None
        run_id = str(candidate) if candidate else ""
        if run_id:
            break
        if not args.loop:
            print("[retention] no capture to maintain under the root; nothing to do")
            return 0
        print(f"[retention] waiting for a capture under {root}")
        if wait_for_stop_file(stop_file, min(args.interval, 60.0)):
            print("[retention] stop requested while waiting for a capture")
            return 0
    report_path = Path(args.report) if args.report else root / "reports" / "RETENTION_REPORT.json"
    iterations = 0
    last: dict[str, Any] = {}
    while True:
        last = dry_run_once(args, run_id, root) if args.dry_run else run_once(args, run_id, root)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(last, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(report_path)
        if args.dry_run:
            print(
                f"[retention:dry-run] free={last['free_bytes'] / 1e6:.1f}MB "
                f"retain={last['would_retain_raw_segments']} "
                f"compact={last['would_compact_segments']} "
                f"delete={last['would_delete_segments']} "
                f"reclaim={last['would_reclaim_bytes'] / 1e6:.1f}MB"
            )
        else:
            print(
                f"[retention] free={last['free_bytes'] / 1e6:.1f}MB "
                f"compacted={last['compacted']} deleted={last['deleted']} "
                f"freed={last['freed_bytes'] / 1e6:.1f}MB"
            )
        iterations += 1
        if not args.loop or (args.max_iterations and iterations >= args.max_iterations):
            break
        if wait_for_stop_file(stop_file, args.interval):
            print("[retention] stop requested; report is current")
            break
    print(f"[retention] report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
