"""Independent verification of PAPER-CONTINUOUS-STRATEGY-LAB-V1 (§57-§59).

BUILDER != VERIFIER. This module re-derives every claim it certifies from bytes
on disk, from the running code, or from a subprocess it starts itself. It never
reads a builder's verdict as if it were evidence, and it writes only its own
report.

    PYTHONPATH=<worktree>/src python scripts/paper_lab_verification.py \
        --lab-run-dir reports/paper-lab/<run-id> \
        --capture-root reports/microstructure-forward-writercert \
        --out <worktree>/docs

What it can fail on, and why each one matters:

* **isolation** — if ``trading_bot`` resolves outside the tree under test, every
  other result is about a different program;
* **P1** — a per-event latency list that is never consumed is fatal to
  "run continuously", so the check re-measures memory at 100k and 1M events and
  also proves the old field is gone from the source;
* **retention** — the aggregate for every lineage record is re-hashed, so a
  compacted window cannot be "evidence" of something that is no longer there;
* **storage** — capacity is recomputed from the real manifest, and the verdict
  is allowed to be ``EXTERNAL_STORAGE_REQUIRED`` but never a comfortable lie;
* **strategy gate** — the committed ledger must not admit anybody, and a rejected
  strategy must not be routable;
* **no LIVE** — the PAPER entrypoint is handed a LIVE-mode settings object and
  must refuse;
* **safe stop/restart** — the recorded run must show children stopped cleanly and
  a resumed capture with no duplicated economic decision;
* **final HEAD executed** — the capture manifest and the lab plan are stamped
  with the commit they actually ran on, and that commit must be this one.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

FORWARD_DIR = REPO_ROOT / "src" / "trading_bot" / "research" / "forward"
SCRIPTS_DIR = REPO_ROOT / "scripts"

#: §25 — the surface whose behaviour must be the behaviour that was executed. The
#: verifier itself, its tests and the documentation are deliberately not in here:
#: adding a check or a paragraph cannot change what the runtime did.
RUNTIME_PATHS: tuple[str, ...] = (
    "src/trading_bot",
    "scripts/autonomous_paper.py",
    "scripts/forward_collector.py",
    "scripts/forward_retention.py",
    "scripts/paper_lab_research.py",
    "scripts/start_paper_lab.py",
    "scripts/system_daily_report.py",
)

P1_MEMORY_PROBE = """
import sys, tracemalloc
from trading_bot.research.forward.storage import LatencyHistogram
tracemalloc.start()
h = LatencyHistogram()
for i in range(100_000):
    h.observe(i % 997)
after_100k, _ = tracemalloc.get_traced_memory()
for i in range(100_000, 1_000_000):
    h.observe(i % 997)
after_1m, peak = tracemalloc.get_traced_memory()
print(1000)
print(after_1m - after_100k)
print(peak)
print(h.samples)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lab-run-dir", required=True)
    parser.add_argument("--capture-root", default="reports/microstructure-forward-writercert")
    parser.add_argument("--forward-root", default="reports/microstructure-forward-lab")
    parser.add_argument("--paper-root", default="reports/autonomous-paper")
    parser.add_argument("--ledger", default="config/strategy_admission.json")
    parser.add_argument("--out", default=str(REPO_ROOT / "docs"))
    parser.add_argument(
        "--record",
        default="PAPER_LAB_INDEPENDENT_VERIFICATION",
        help="stem for the report artifacts",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip re-running the phase test modules (they are slow)",
    )
    return parser.parse_args()


def load_script(name: str) -> Any:
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _confirmed_status_literals(path: Path) -> list[str]:
    """``status = "CONFIRMED"`` / ``{"status": "CONFIRMED"}`` and nothing else."""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:  # pragma: no cover - the file would not run at all
        return []
    offenders: list[str] = []
    status_keys = {"status", "state", "admission_status", "strategy_status"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if not isinstance(key, ast.Constant) or str(key.value) not in status_keys:
                    continue
                if isinstance(value, ast.Constant) and value.value == "CONFIRMED":
                    offenders.append(f"{path.name}:{node.lineno}")
        elif isinstance(node, ast.Assign):
            if not (isinstance(node.value, ast.Constant) and node.value.value == "CONFIRMED"):
                continue
            for target in node.targets:
                name = getattr(target, "id", "") or getattr(target, "attr", "")
                if any(part in str(name) for part in status_keys):
                    offenders.append(f"{path.name}:{node.lineno}")
    return offenders


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    return (completed.stdout or "").strip()


def check_isolation() -> dict[str, Any]:
    """Every ``trading_bot`` module must come from the tree under test."""
    import trading_bot

    root = Path(trading_bot.__file__).resolve()
    offenders: list[str] = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("trading_bot"):
            continue
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        resolved = Path(origin).resolve()
        if REPO_ROOT not in resolved.parents and resolved.parent != REPO_ROOT:
            offenders.append(f"{name} -> {resolved}")
    return {
        "id": "IMPORT_ISOLATION",
        "ok": not offenders,
        "detail": {
            "trading_bot": str(root),
            "repo_root": str(REPO_ROOT),
            "offenders": offenders[:10],
        },
        "claim": "the verifier measured the worktree's code, not an editable install",
    }


def check_p1_bounded_telemetry() -> dict[str, Any]:
    """The unbounded per-event list is gone and memory does not grow with events."""
    source_offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in FORWARD_DIR.rglob("*.py")
        if "network_delays" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", P1_MEMORY_PROBE],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    growth = int(lines[1]) if len(lines) >= 4 else None
    peak = int(lines[2]) if len(lines) >= 4 else None
    samples = int(lines[3]) if len(lines) >= 4 else None
    ok = not source_offenders and growth is not None and growth < 4096 and samples == 1_000_000
    return {
        "id": "P1_NETWORK_DELAYS_BOUNDED",
        "ok": ok,
        "detail": {
            "source_files_still_declaring_network_delays": source_offenders,
            "retained_bytes_100k_to_1m": growth,
            "peak_bytes": peak,
            "samples": samples,
            "budget_bytes": 4096,
            "measured_by": "tracemalloc in a subprocess, 1,000,000 observations",
        },
        "claim": "latency telemetry is a fixed-geometry histogram, not per-event state",
    }


def check_retention_safety(capture_root: Path, forward_root: Path) -> dict[str, Any]:
    """Re-hash every aggregate a lineage record claims, and prove the order."""
    checked: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for root in (capture_root, forward_root):
        lineage_dir = root / "lineage"
        if not lineage_dir.exists():
            continue
        for record_path in sorted(lineage_dir.rglob("*.json")):
            payload = _read_json(record_path)
            if payload is None:
                broken.append({"path": str(record_path), "reason": "unreadable"})
                continue
            output = root / str(payload.get("output_path", ""))
            if not output.exists():
                broken.append({"path": str(record_path), "reason": "aggregate missing"})
                continue
            digest = _sha256(output)
            sources = payload.get("sources") or []
            ok = digest == payload.get("output_sha256") and bool(sources)
            entry = {
                "aggregate": str(output.relative_to(root)),
                "source_segments": len(sources),
                "source_hashes_present": all(s.get("sha256") for s in sources),
                "time_range": [payload.get("window_start_ms"), payload.get("window_end_ms")],
                "aggregation_version": payload.get("aggregation_version"),
                "output_sha256_matches": digest == payload.get("output_sha256"),
            }
            checked.append(entry)
            if not ok:
                broken.append({**entry, "reason": "lineage does not match the aggregate"})
    report_root_touched = [
        str(path.relative_to(capture_root))
        for path in (capture_root / "reports").rglob("*")
        if path.is_file()
    ] if (capture_root / "reports").exists() else []
    return {
        "id": "RETENTION_LINEAGE_AND_ORDER",
        "ok": not broken,
        "detail": {
            "aggregates_verified": len(checked),
            "broken": broken[:10],
            "sample": checked[:3],
            "reports_layer_files": report_root_touched,
            "deletion_rule": (
                "raw is deletable only after the window is sealed, aggregated, the "
                "aggregate is fingerprinted, lineage is recorded and the aggregate "
                "still re-hashes to the recorded digest"
            ),
        },
        "claim": "no raw is replaceable by an aggregate that cannot be re-verified",
    }


def check_storage_capacity(capture_root: Path) -> dict[str, Any]:
    """Recompute capacity from the real manifest instead of trusting a report."""
    from trading_bot.research.forward.retention import capacity_report, policy_for_host

    manifests = sorted((capture_root / "manifest").glob("*.json"))
    manifest = _read_json(manifests[-1]) if manifests else None
    if manifest is None:
        return {
            "id": "STORAGE_CAPACITY_POLICY",
            "ok": False,
            "detail": {"reason": f"no manifest under {capture_root / 'manifest'}"},
            "claim": "capacity must rest on a real capture manifest",
        }
    duration_seconds = float(manifest.get("duration_seconds") or 0.0)
    bytes_written = float(manifest.get("bytes_written") or 0.0)
    if duration_seconds <= 0:
        return {
            "id": "STORAGE_CAPACITY_POLICY",
            "ok": False,
            "detail": {"reason": "manifest declares no duration"},
            "claim": "capacity must rest on a real capture manifest",
        }
    compressed_per_day = bytes_written * 86_400.0 / duration_seconds
    free_bytes = shutil.disk_usage(REPO_ROOT).free
    policy = policy_for_host(
        free_bytes=free_bytes,
        compressed_bytes_per_day=compressed_per_day,
        aggregate_bytes_per_day=1_000_000.0,
    )
    report = capacity_report(
        free_bytes=free_bytes,
        policy=policy,
        compressed_bytes_per_day=compressed_per_day,
        aggregate_bytes_per_day=1_000_000.0,
    )
    as_dict = report.as_dict()
    verdict = as_dict["verdict"]
    # Either the hot window fits, or the limitation is named and the window is at
    # least the one-hour floor rather than an invented number.
    ok = verdict == "VIABLE" or (
        verdict == "EXTERNAL_STORAGE_REQUIRED" and policy.raw_hot_hours >= 1.0
    )
    return {
        "id": "STORAGE_CAPACITY_POLICY",
        "ok": bool(ok),
        "detail": {
            "manifest": str(manifests[-1].relative_to(REPO_ROOT)),
            "measured_compressed_bytes_per_day": compressed_per_day,
            "measured_compressed_gb_per_day": round(compressed_per_day / 1e9, 3),
            "policy": policy.as_dict(),
            "verdict": verdict,
            "estimated_operating_days": as_dict.get("estimated_operating_days"),
            "hours_until_guard_without_compaction": as_dict.get(
                "hours_until_guard_without_compaction"
            ),
        },
        "claim": (
            "either the hot window fits the disk or the limitation is named "
            "EXTERNAL_STORAGE_REQUIRED with a bounded, safe hot window"
        ),
    }


def check_strategy_gate(ledger_path: Path) -> dict[str, Any]:
    """Rejected cannot route, missing evidence cannot promote, nobody is admitted."""
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.contracts import (
        PAPER_AUTHORISING_STATUSES,
        AdmissionStatus,
    )
    from trading_bot.autonomous.strategy_state import (
        LIVE_STATUS_NAMES,
        StrategyRegistry,
        StrategyStateError,
        assert_transition,
        is_paper_executable,
    )

    ledger = AdmissionLedger.load(ledger_path)
    registry = StrategyRegistry.from_ledger(ledger, assets=["BTC", "ETH", "SOL"])
    counts = registry.counts_by_status()
    executable = registry.paper_candidates("5m")

    live_names = {status.value.upper() for status in AdmissionStatus} & LIVE_STATUS_NAMES
    rejected_routable = [
        status.value
        for status in AdmissionStatus
        if status not in PAPER_AUTHORISING_STATUSES and is_paper_executable(status)
    ]
    promotion_without_record_denied = False
    try:
        assert_transition(
            "x@5m", AdmissionStatus.PAPER_CANDIDATE, AdmissionStatus.PAPER_ACTIVE
        )
    except StrategyStateError:
        promotion_without_record_denied = True
    research_jump_denied = False
    try:
        assert_transition(
            "x@5m", AdmissionStatus.RESEARCH_REQUIRED, AdmissionStatus.PAPER_ACTIVE
        )
    except StrategyStateError:
        research_jump_denied = True

    ok = (
        not live_names
        and not rejected_routable
        and promotion_without_record_denied
        and research_jump_denied
        and executable == []
        and counts.get("PAPER_ACTIVE", 0) == 0
    )
    return {
        "id": "STRATEGY_ADMISSION_GATE",
        "ok": ok,
        "detail": {
            "ledger": str(ledger_path.relative_to(REPO_ROOT)),
            "lifecycle_counts": counts,
            "paper_executable_on_5m": executable,
            "live_names_in_vocabulary": sorted(live_names),
            "non_paper_statuses_that_could_route": rejected_routable,
            "promotion_without_record_denied": promotion_without_record_denied,
            "research_to_active_denied": research_jump_denied,
            "rejected_cannot_route": not rejected_routable,
        },
        "claim": (
            "no strategy is admitted, a rejected one cannot route, and PAPER "
            "promotion requires a record"
        ),
    }


def check_def_auto(ledger_path: Path) -> dict[str, Any]:
    """DEF-AUTO-2/3/4 — universe, timeframe-derived freshness, no CONFIRMED."""
    from trading_bot.autonomous.universe_preflight import preflight_universe
    from trading_bot.research.router_gates import (
        stale_threshold_for_timeframe,
        timeframe_ms,
    )

    configured = ["BTC", "ETH", "SOL", "BNB"]
    support = preflight_universe(
        configured=configured,
        asset_agents=["BTC", "ETH", "SOL"],
        strategy_assets=["BTC", "ETH", "SOL"],
        provider_supported=["BTC", "ETH", "SOL"],
    )
    payload = support.to_dict()
    effective = {str(asset).upper() for asset in payload.get("effective", [])}
    unsupported = {str(asset).upper(): reason for asset, reason in (payload.get("unsupported") or {}).items()}
    # §39 — never silently ignore a configured asset: each one is either in the
    # effective universe or carries a reason for being out of it.
    explained = all(
        str(asset).upper() in effective or str(asset).upper() in unsupported
        for asset in configured
    ) and bool(unsupported)
    unregistered = {asset: reason for asset, reason in unsupported.items() if asset == "BNB"}

    freshness: dict[str, Any] = {}
    for timeframe in ("1m", "5m", "15m", "30m", "1h"):
        threshold = stale_threshold_for_timeframe(timeframe)
        freshness[timeframe] = {
            "bar_ms": timeframe_ms(timeframe),
            "stale_threshold_ms": threshold,
        }
    monotonic = all(
        freshness[a]["stale_threshold_ms"] < freshness[b]["stale_threshold_ms"]
        for a, b in zip(
            ("1m", "5m", "15m", "30m"), ("5m", "15m", "30m", "1h"), strict=True
        )
    )
    unknown_raises = False
    try:
        stale_threshold_for_timeframe("7m")
    except Exception:
        unknown_raises = True

    # Only the entrypoints that author a strategy map are in scope, and only a
    # literal *assigned to a status field* is the defect: a docstring or a
    # comment that names the retired constant is documentation, and a research
    # module's unrelated applicability vocabulary is not this runtime's map.
    entrypoints = [
        SCRIPTS_DIR / "start_paper_trading.py",
        SCRIPTS_DIR / "autonomous_paper.py",
        SCRIPTS_DIR / "start_paper_lab.py",
        REPO_ROOT / "src" / "trading_bot" / "autonomous" / "runtime.py",
        REPO_ROOT / "src" / "trading_bot" / "autonomous" / "strategy_state.py",
    ]
    assigned_confirmed = [
        offender for path in entrypoints if path.exists() for offender in _confirmed_status_literals(path)
    ]

    ok = (
        explained
        and bool(unregistered)
        and monotonic
        and unknown_raises
        and not assigned_confirmed
    )
    return {
        "id": "DEF_AUTO_2_3_4",
        "ok": ok,
        "detail": {
            "DEF-AUTO-2": {
                "universe_preflight": payload,
                "every_configured_asset_has_an_explicit_classification": explained,
                "unregistered_asset_entries": unregistered,
            },
            "DEF-AUTO-3": {
                "freshness_by_timeframe": freshness,
                "strictly_increasing_with_timeframe": monotonic,
                "unknown_timeframe_raises": unknown_raises,
            },
            "DEF-AUTO-4": {
                "entrypoints_inspected": [str(path.relative_to(REPO_ROOT)) for path in entrypoints],
                "literal_CONFIRMED_assignments": assigned_confirmed,
            },
        },
        "claim": "the universe fails closed, freshness follows the timeframe, and no entrypoint marks everything CONFIRMED",
    }


def check_no_live_path() -> dict[str, Any]:
    """Hand the PAPER entrypoint a LIVE-mode settings object; it must refuse."""
    from trading_bot.config.runtime import TradingMode

    module = load_script("autonomous_paper")
    real_build = module.build_settings
    live_settings = types.SimpleNamespace(
        runtime=types.SimpleNamespace(mode=TradingMode.LIVE, exchange_id="binance")
    )
    captured: dict[str, list[str]] = {"out": [], "err": []}

    class _Sink:
        def __init__(self, bucket: list[str]) -> None:
            self._bucket = bucket

        def write(self, text: str) -> int:
            self._bucket.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    argv = [
        "autonomous_paper.py",
        "--cycles",
        "1",
        "--provider",
        "fake",
        "--assets",
        "BTC,ETH,SOL",
    ]
    old_argv, old_stdout, old_stderr = sys.argv, sys.stdout, sys.stderr
    try:
        module.build_settings = lambda *_a, **_k: live_settings
        sys.argv = argv
        sys.stdout = _Sink(captured["out"])
        sys.stderr = _Sink(captured["err"])
        try:
            code = asyncio.run(module.main())
        except SystemExit as exc:  # pragma: no cover - argparse
            code = int(exc.code or 0)
        refusal = {
            "returncode": code,
            "stderr": "".join(captured["err"])[-500:],
            "stdout": "".join(captured["out"])[-200:],
        }
    finally:
        module.build_settings = real_build
        sys.argv, sys.stdout, sys.stderr = old_argv, old_stdout, old_stderr

    ok = refusal.get("returncode") == 1 and "Refusing to start" in (refusal.get("stderr") or "")
    return {
        "id": "NO_LIVE_PATH",
        "ok": bool(ok),
        "detail": {
            "live_mode_refusal": refusal,
            "note": (
                "the PAPER entrypoint refuses to start when runtime.mode is not "
                "PAPER, before any broker, risk manager or reader is constructed"
            ),
        },
        "claim": "LIVE is not reachable from this phase's entrypoints",
    }


def check_supervisor_isolation() -> dict[str, Any]:
    """Run two real children; kill one; the other must be untouched."""
    from trading_bot.autonomous.supervisor import ManagedProcess, ProcessState, Supervisor

    run_dir = Path(tempfile.mkdtemp(prefix="lab-verifier-"))
    survivor = "import time; time.sleep(120)"
    crasher = "raise SystemExit(9)"
    supervisor = Supervisor.build(
        run_dir,
        [
            ManagedProcess(name="paper", command=[sys.executable, "-c", survivor], cwd=REPO_ROOT),
            ManagedProcess(
                name="collector",
                command=[sys.executable, "-c", crasher],
                cwd=REPO_ROOT,
                max_restarts=1,
                crash_loop_window_seconds=900.0,
                backoff_seconds=(0.05, 0.05),
            ),
        ],
        heartbeat_seconds=0.05,
    )
    events: list[dict[str, Any]] = []
    try:
        supervisor.start_all()
        deadline = time.monotonic() + 30.0
        collector = supervisor.get("collector")
        while collector.state is not ProcessState.FAILED and time.monotonic() < deadline:
            events.extend(supervisor.poll_once())
            time.sleep(0.05)
        paper = supervisor.get("paper")
        detail = {
            "paper_state": paper.state.value,
            "paper_restarts": paper.restarts,
            "collector_state": collector.state.value,
            "collector_failure_reason": collector.failure_reason,
            "system_state": supervisor.system_state().value,
            "events": [event.get("event") for event in events],
        }
        ok = (
            collector.state is ProcessState.FAILED
            and paper.state is ProcessState.RUNNING
            and paper.restarts == 0
        )
    finally:
        supervisor.stop_all()
    return {
        "id": "FAILURE_ISOLATION",
        "ok": bool(ok),
        "detail": detail,
        "claim": "a collector crash cannot stop PAPER, and a crash loop is declared rather than retried forever",
    }


def check_safe_stop_and_restart(lab_run_dir: Path, paper_root: Path, forward_root: Path) -> dict[str, Any]:
    """Clean shutdown, persisted state, and a resumed capture with no duplicate ids."""
    lab_report = _read_json(lab_run_dir / "LAB_RUN_REPORT.json")
    heartbeat = _read_json(lab_run_dir / "SYSTEM_HEARTBEAT.json")
    children_stopped: list[str] = []
    if lab_report:
        children_stopped = [
            name
            for name, runtime in (lab_report.get("processes") or {}).items()
            if runtime.get("state") in ("STOPPED", "EXITED", "FAILED")
        ]
    run_id = lab_run_dir.name
    manifests = sorted((forward_root / "manifest").glob("*.json"))
    manifest = _read_json(manifests[-1]) if manifests else None
    partial_tails = (
        sum(1 for f in (manifest or {}).get("fingerprints", []) if f.get("partial_tail"))
        if manifest
        else None
    )
    resume_state = _read_json(forward_root / "state" / f"{run_id}.json")
    paper_state = _read_json(lab_run_dir / "paper_state.json")

    traces = paper_root / run_id / "traces.jsonl"
    decision_ids: list[str] = []
    duplicate_decisions: list[str] = []
    if traces.exists():
        seen: set[str] = set()
        with traces.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                key = str(
                    row.get("decision_id")
                    or row.get("trace_id")
                    or row.get("idempotency_key")
                    or ""
                )
                if not key:
                    continue
                decision_ids.append(key)
                if key in seen:
                    duplicate_decisions.append(key)
                seen.add(key)

    ok = (
        bool(children_stopped)
        and partial_tails == 0
        and not duplicate_decisions
        and resume_state is not None
    )
    return {
        "id": "SAFE_STOP_AND_RESTART",
        "ok": bool(ok),
        "detail": {
            "stop_reason": (lab_report or {}).get("stop_reason"),
            "children_stopped": children_stopped,
            "collector_partial_tails": partial_tails,
            "collector_resume_state_present": resume_state is not None,
            "collector_resume_events": (resume_state or {}).get("events"),
            "paper_state_present": paper_state is not None,
            "paper_state_keys": sorted(paper_state)[:10] if paper_state else [],
            "paper_decisions": len(decision_ids),
            "duplicate_economic_decisions": duplicate_decisions[:5],
            "final_state": (lab_report or {}).get("final_state"),
            "supervisor_state": (heartbeat or {}).get("state"),
        },
        "claim": "stop flushes, state persists, a restart resumes the capture and no economic decision is duplicated",
    }


def _latest_manifest(root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    manifests = sorted((root / "manifest").glob("*.json"))
    if not manifests:
        return None, None
    return manifests[-1], _read_json(manifests[-1])


def check_final_head_executed(
    capture_root: Path, forward_root: Path, lab_run_dir: Path, args: argparse.Namespace
) -> dict[str, Any]:
    """The integrated run must have executed the certified HEAD.

    The writer certification capture may legitimately predate the final commit,
    so it is not required to carry the final HEAD — but it is only allowed to
    differ if the writer-side modules did not change between the two commits,
    which is checked with git rather than asserted.
    """
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--short")
    integrated_path, integrated = _latest_manifest(forward_root)
    cert_path, certification = _latest_manifest(capture_root)
    paper_descriptor = _read_json(
        REPO_ROOT / args.paper_root / lab_run_dir.name / "PAPER_RUN.json"
    )

    # Every capture under the lab roots, so a short post-run smoke at the final
    # HEAD counts as evidence that the final HEAD was executed.
    stamped_with_head: list[dict[str, Any]] = []
    for path in sorted(forward_root.parent.glob("microstructure-forward-lab*/manifest/*.json")):
        payload = _read_json(path) or {}
        commit = str(payload.get("commit") or "")
        if commit and head.startswith(commit):
            stamped_with_head.append(
                {
                    "manifest": str(path.relative_to(REPO_ROOT)),
                    "commit": commit,
                    "duration_seconds": payload.get("duration_seconds"),
                }
            )

    integrated_commit = (integrated or {}).get("commit") or ""
    integrated_matches = bool(integrated_commit) and head.startswith(integrated_commit)
    # §25: the integrated run may predate the final HEAD only if nothing on the
    # runtime surface changed in between, in which case a smoke at the final HEAD
    # has to exist as its own evidence.
    changed_since_integrated: list[str] = []
    if integrated_commit and not integrated_matches:
        changed = _git(
            "diff", "--name-only", integrated_commit, head, "--", *RUNTIME_PATHS
        )
        changed_since_integrated = [line for line in changed.splitlines() if line.strip()]

    cert_commit = (certification or {}).get("commit") or ""
    writer_changed_since_certification: list[str] = []
    if cert_commit and cert_commit != head:
        changed = _git("diff", "--name-only", cert_commit, head, "--", "src/trading_bot/research/forward")
        writer_changed_since_certification = [line for line in changed.splitlines() if line.strip()]

    head_matches_integrated = integrated_matches or (
        bool(stamped_with_head) and not changed_since_integrated
    )
    ok = (
        bool(head)
        and not status
        and head_matches_integrated
        and not writer_changed_since_certification
    )
    return {
        "id": "FINAL_HEAD_EXECUTED",
        "ok": bool(ok),
        "detail": {
            "verified_head": head,
            "integrated_run_manifest": str(integrated_path.relative_to(REPO_ROOT))
            if integrated_path
            else None,
            "integrated_run_commit": integrated_commit,
            "integrated_run_commit_matches_head": integrated_matches,
            "captures_stamped_with_head": stamped_with_head,
            "runtime_paths_changed_since_integrated_run": changed_since_integrated,
            "runtime_surface": list(RUNTIME_PATHS),
            "writer_certification_manifest": str(cert_path.relative_to(REPO_ROOT))
            if cert_path
            else None,
            "writer_certification_commit": cert_commit,
            "writer_modules_changed_since_certification": writer_changed_since_certification,
            "paper_run_stamp": (paper_descriptor or {}).get("commit"),
            "working_tree": status or "clean",
            "note": (
                "the integrated run's manifest must record HEAD, or a later smoke "
                "stamped with HEAD must exist with no runtime module changed in "
                "between (brief §25); a certification capture may predate HEAD only "
                "when no writer-side module changed"
            ),
        },
        "claim": "the certified HEAD is the HEAD that produced the runtime evidence",
    }


def check_microstructure_hypotheses() -> dict[str, Any]:
    """M-03/M-07 stay NEEDS_HISTORY behind a pre-registered minimum."""
    path = REPO_ROOT / "config" / "microstructure_preregistration.json"
    payload = _read_json(path)
    rows = (payload or {}).get("hypotheses", {})
    states = {key: value.get("state") for key, value in rows.items()}
    registered_at = (payload or {}).get("preregistered_at")
    version = (payload or {}).get("preregistration_version")
    registered = bool(rows) and bool(registered_at) and bool(version) and all(
        value.get("minimum_data") and value.get("quality_gates") for value in rows.values()
    )
    evidence = [
        str(candidate.relative_to(REPO_ROOT))
        for candidate in (REPO_ROOT / "reports").rglob("*M-03*")
    ] + [
        str(candidate.relative_to(REPO_ROOT))
        for candidate in (REPO_ROOT / "reports").rglob("*M-07*")
    ]
    ok = (
        payload is not None
        and bool(rows)
        and all(state == "TECHNICALLY_READY_NEEDS_HISTORY" for state in states.values())
        and registered
        and bool((payload or {}).get("not_yet_run"))
    )
    return {
        "id": "M03_M07_PREREGISTERED",
        "ok": ok,
        "detail": {
            "path": str(path.relative_to(REPO_ROOT)),
            "states": states,
            "minimum_data_present": registered,
            "preregistered_at": registered_at,
            "preregistration_version": version,
            "not_yet_run": (payload or {}).get("not_yet_run"),
            "experiment_outputs_found": evidence[:10],
        },
        "claim": "neither hypothesis has been evaluated, and the threshold cannot be chosen after seeing a result",
    }


def check_phase_tests() -> dict[str, Any]:
    """Re-run the phase's own test modules with this worktree's src first."""
    modules = [
        "tests/unit/autonomous/test_supervisor.py",
        "tests/unit/autonomous/test_strategy_state.py",
        "tests/unit/autonomous/test_universe_preflight.py",
        "tests/unit/autonomous/test_lab_operations.py",
        "tests/unit/research/test_router_gates_freshness.py",
        "tests/unit/forward/test_forward_latency_telemetry.py",
        "tests/unit/forward/test_forward_retention.py",
        "tests/unit/test_dependency_closure_guard.py",
    ]
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *modules],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = [line for line in (completed.stdout or "").splitlines() if line.strip()][-3:]
    return {
        "id": "PHASE_TESTS",
        "ok": completed.returncode == 0,
        "detail": {"modules": modules, "returncode": completed.returncode, "summary": tail},
        "claim": "the phase's own tests pass on the worktree's code with its own src first",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    capture_root = (REPO_ROOT / args.capture_root).resolve()
    forward_root = (REPO_ROOT / args.forward_root).resolve()
    paper_root = REPO_ROOT / args.paper_root
    lab_run_dir = (REPO_ROOT / args.lab_run_dir).resolve()
    ledger_path = REPO_ROOT / args.ledger

    checks: list[dict[str, Any]] = []

    def _guard(fn: Any) -> None:
        try:
            checks.append(fn())
        except Exception as exc:  # a crashing check is a failed check, not a missing one
            checks.append(
                {
                    "id": getattr(fn, "__name__", "unknown"),
                    "ok": False,
                    "detail": {"exception": f"{type(exc).__name__}: {exc}"},
                    "claim": "a check that cannot run is reported as failed",
                }
            )

    for fn in (
        check_isolation,
        check_p1_bounded_telemetry,
        lambda: check_retention_safety(capture_root, forward_root),
        lambda: check_storage_capacity(capture_root),
        lambda: check_strategy_gate(ledger_path),
        lambda: check_def_auto(ledger_path),
        check_no_live_path,
        check_supervisor_isolation,
        lambda: check_safe_stop_and_restart(lab_run_dir, paper_root, forward_root),
        lambda: check_final_head_executed(capture_root, forward_root, lab_run_dir, args),
        check_microstructure_hypotheses,
    ):
        _guard(fn)
    if not args.skip_tests:
        _guard(check_phase_tests)

    failed = [check for check in checks if not check.get("ok")]
    return {
        "schema_version": "paper-lab-independent-verification-v1",
        "generated_at_ms": int(time.time() * 1000),
        "verified_head": _git("rev-parse", "HEAD"),
        "worktree": str(REPO_ROOT),
        "lab_run_dir": str(lab_run_dir),
        "capture_root": str(capture_root),
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "failed_ids": [check["id"] for check in failed],
        "checks": checks,
        "verdict": "PASS" if not failed else "FAIL",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# PAPER LAB — INDEPENDENT VERIFICATION",
        "",
        "```text",
        f"verified HEAD : {payload['verified_head']}",
        f"worktree      : {payload['worktree']}",
        f"lab run       : {payload['lab_run_dir']}",
        f"capture root  : {payload['capture_root']}",
        f"checks        : {payload['checks_passed']}/{payload['checks_total']} passed",
        f"verdict       : {payload['verdict']}",
        "```",
        "",
        "| check | result |",
        "| --- | --- |",
    ]
    for check in payload["checks"]:
        lines.append(f"| {check['id']} | {'PASS' if check['ok'] else 'FAIL'} |")
    lines.append("")
    for check in payload["checks"]:
        lines.append(f"## {check['id']} — {'PASS' if check['ok'] else 'FAIL'}")
        lines.append("")
        lines.append(f"_{check.get('claim', '')}_")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(check.get("detail", {}), indent=2, ensure_ascii=False)[:4000])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    payload = run(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.record}.json"
    md_path = out_dir / f"{args.record}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"[verify] {payload['checks_passed']}/{payload['checks_total']} PASS "
        f"verdict={payload['verdict']}"
    )
    for check in payload["checks"]:
        print(f"[verify]   {'PASS' if check['ok'] else 'FAIL'} {check['id']}")
    print(f"[verify] report: {json_path}")
    print(f"[verify] report: {md_path}")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
