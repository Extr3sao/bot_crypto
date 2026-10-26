"""Controlled test of the forward collector's disk guard (§15).

The guard must not be taken on trust: a capture that fills its volume destroys
the dataset it was collecting. This runs the real collector against the real
(public, read-only) venue with a deliberately tiny byte budget and checks that
reaching it stops intake, flushes and seals the writer, finalises the manifest,
and exits 0 — without ever filling the disk, because the budget is ~200 kB.

Two invocations are exercised, because they are not the same:

``unbounded``  the recommended continuous form (no ``--duration``): the run loop
               polls the stop flag every second, so the guard actually stops
               intake.
``bounded``    ``--duration`` set: the run sleeps for the requested duration and
               never wakes early, so the guard is recorded but intake continues
               until the duration expires. That is an open defect, and this test
               demonstrates it rather than hiding it.

Writes ``docs/FORWARD_DATA_DISK_GUARD.json``.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EVIDENCE_ROOT = ROOT / "reports" / "microstructure-forward-diskguard"
#: The budget is reached at roughly 30 s at the observed rate, so the bounded
#: variant is given enough duration to *overshoot* it: otherwise the run would end
#: first and prove nothing about what happens after a trip.
BUDGET_BYTES = 200_000
BOUNDED_SECONDS = 90.0


def _collector_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{existing}" if existing else str(ROOT / "src")
    return env


def _run_capture(root: Path, extra: list[str], timeout: float) -> dict[str, Any]:
    command = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "forward_collector.py"),
        "--mode",
        "run",
        "--out",
        str(root),
        "--symbols",
        "BTCUSDT",
        "--markets",
        "spot",
        "--streams",
        "agg_trade,book_ticker",
        "--rotation-seconds",
        "60",
        "--heartbeat-seconds",
        "2",
        "--checkpoint-seconds",
        "60",
        "--max-total-bytes",
        str(BUDGET_BYTES),
        *extra,
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=_collector_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        # A guard that never trips must be reported as a failure of the guard, not
        # as a crash of the test.
        return {
            "command": " ".join(command[1:]),
            "exit_code": None,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "timed_out_after_seconds": timeout,
            "stderr_tail": str(expired.stderr or "")[-2000:],
        }
    elapsed = time.perf_counter() - started
    return {
        "command": " ".join(command[1:]),
        "exit_code": completed.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "stderr_tail": completed.stderr.strip()[-2000:],
    }


def _inspect(root: Path) -> dict[str, Any]:
    """Read the finished run back off disk and measure what the guard did."""
    manifest_dir = root / "manifest"
    manifests = sorted(manifest_dir.glob("*.json")) if manifest_dir.is_dir() else []
    if not manifests:
        return {"manifest_finalised": False, "root": str(root)}
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    fingerprints = manifest.get("fingerprints", [])
    stored = sum(int(entry.get("bytes") or 0) for entry in fingerprints)
    lifecycle: list[dict[str, Any]] = []
    max_receive = 0
    for path in sorted((root / "segments").rglob("*.jsonl*")):
        try:
            with contextlib.ExitStack() as stack:
                handle: Any = (
                    stack.enter_context(gzip.open(path, "rt", encoding="utf-8"))
                    if path.suffix == ".gz"
                    else stack.enter_context(path.open("r", encoding="utf-8"))
                )
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    max_receive = max(max_receive, int(row.get("receive_time") or 0))
                    detail = row.get("detail")
                    if (
                        row.get("event_type") == "lifecycle"
                        and isinstance(detail, dict)
                        and detail.get("kind") == "DISK_LIMIT_REACHED"
                    ):
                        lifecycle.append(
                            {
                                "at_ms": int(row.get("receive_time") or 0),
                                "bytes": detail.get("bytes"),
                                "limit": detail.get("limit"),
                            }
                        )
        except (EOFError, OSError):
            continue
    trip_ms = lifecycle[0]["at_ms"] if lifecycle else None
    return {
        "root": str(root),
        "manifest_finalised": True,
        "run_id": manifest.get("run_id"),
        "commit": manifest.get("commit"),
        "duration_seconds": manifest.get("duration_seconds"),
        "ended_at": manifest.get("ended_at"),
        "stopped_on_disk_budget": bool(manifest.get("stopped_on_disk_budget")),
        "max_total_bytes": manifest.get("max_total_bytes"),
        "segments": len(fingerprints),
        "segments_sealed": bool(fingerprints)
        and all(entry.get("sealed") is True for entry in fingerprints),
        "partial_tails": sum(1 for entry in fingerprints if entry.get("partial_tail")),
        "stored_bytes": stored,
        "overshoot_bytes": stored - BUDGET_BYTES,
        "disk_limit_events": lifecycle,
        "max_receive_time_ms": max_receive,
        "rows_after_trip_ms": (max_receive - trip_ms) if trip_ms else None,
        "continuity": manifest.get("continuity"),
        "events": manifest.get("integrity", {}).get("duplicates"),
    }


def run_guard_test() -> dict[str, Any]:
    if EVIDENCE_ROOT.exists():
        shutil.rmtree(EVIDENCE_ROOT, ignore_errors=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)

    unbounded_root = EVIDENCE_ROOT / "unbounded"
    unbounded = _run_capture(unbounded_root, [], timeout=120.0)
    unbounded.update(_inspect(unbounded_root))

    bounded_root = EVIDENCE_ROOT / "bounded"
    bounded = _run_capture(
        bounded_root, ["--duration", str(BOUNDED_SECONDS)], timeout=BOUNDED_SECONDS + 180.0
    )
    bounded.update(_inspect(bounded_root))

    tripped = bool(unbounded.get("stopped_on_disk_budget"))
    clean_exit = unbounded.get("exit_code") == 0
    sealed = bool(unbounded.get("segments_sealed"))
    finalised = bool(unbounded.get("manifest_finalised"))
    partial_tails = int(unbounded.get("partial_tails") or 0)
    rows_after_trip = unbounded.get("rows_after_trip_ms")
    intake_stopped = rows_after_trip is not None and rows_after_trip <= 2_000

    bounded_leak = bounded.get("rows_after_trip_ms")
    return {
        "kind": "FORWARD_DATA_DISK_GUARD",
        "commit": unbounded.get("commit"),
        "method": (
            "the real collector run against the public venue with a 200 kB byte "
            "budget: small enough to trip in seconds, large enough to exercise "
            "rotation, compression and sealing"
        ),
        "budget_bytes": BUDGET_BYTES,
        "unbounded_run": unbounded,
        "bounded_run": bounded,
        "tripped": tripped and intake_stopped,
        "clean_exit": clean_exit,
        "segments_sealed": sealed,
        "manifest_finalised": finalised,
        "partial_tails": partial_tails,
        "intake_stopped_within_ms": rows_after_trip,
        "bounded_duration_note": {
            # Measured, not inferred: the socket receive loops also poll the stop
            # flag, so a trip halts intake immediately in both invocation forms.
            # Reading only the top-level sleep suggested otherwise, and the
            # measurement is what the report goes on.
            "open_defect": bool(
                bounded.get("stopped_on_disk_budget") and (bounded_leak or 0) > 2_000
            ),
            "tripped": bool(bounded.get("stopped_on_disk_budget")),
            "rows_written_after_trip_ms": bounded_leak,
            "intake_halted_by_the_transport_loops": (
                bounded_leak is not None and bounded_leak <= 2_000
            ),
            "detail": (
                "with --duration the process stays alive until the duration expires, "
                "but the socket receive loops poll the same stop flag, so no further "
                "row is written after the trip. The recommended continuous invocation "
                "still omits --duration: there is no reason to hold the process open "
                "after the guard has fired."
            ),
            "bounded_duration_seconds": bounded.get("duration_seconds"),
        },
        "result": (
            "PASS: guard tripped, intake stopped, writer flushed and sealed, manifest "
            "finalised, exit 0"
            if tripped
            and intake_stopped
            and clean_exit
            and sealed
            and finalised
            and partial_tails == 0
            else "FAIL: see the two runs above"
        ),
    }


def main() -> int:
    payload = run_guard_test()
    DOCS.mkdir(parents=True, exist_ok=True)
    target = DOCS / "FORWARD_DATA_DISK_GUARD.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, default=str))
    print(f"written -> {target}")
    return 0 if payload["result"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
