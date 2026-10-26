"""One command to run the PAPER lab (§50-§52).

    uv run python scripts/start_paper_lab.py --duration-hours 2

Starts, in this order, under one portable supervisor:

    PAPER runtime      (critical)  scripts/autonomous_paper.py --continuous
    COLLECTOR          (critical)  scripts/forward_collector.py --mode run
    RETENTION          (maintenance) scripts/forward_retention.py --loop
    STRATEGY LAB       (maintenance) scripts/paper_lab_research.py --loop

PAPER and the collector are separate processes with separate failure domains:
neither can take the other down, and the supervisor restarts them independently
with backoff, giving up loudly (``FAILED``) if one is crash-looping rather than
retrying forever (§26-§29).

Stopping is `Ctrl-C`, or writing ``STOP`` into the run directory, or running
this script again with ``--stop <run-dir>``: all three flush state and finalise
manifests before exiting (§51). Nothing here can reach LIVE: every child is
either read-only market data or the PAPER broker.

WP-9B — **disk budget preflight (§10)**: before anything is started, the window
declared by ``--duration-hours`` is costed at the measured capture rate, at the
declared stress multiple, and against both the collector's own valve and the free
space this host really has. The first 24 h window stopped after 4.16 h because it
was launched with an 800 MB valve while its measured rate was 192 MB/h: the two
numbers were never compared, and the comparison is arithmetic rather than physics.
A window whose valve cannot pay for itself is `INCOHERENT_BUDGET` and is refused
unless ``--autoscale-collector-budget`` raises the valve explicitly (the decision
is recorded in `LAB_PLAN.json`); a window this host cannot pay for is
`INSUFFICIENT_FREE_SPACE` and is refused outright, because disk size is not a
preference — point ``--data-root`` at another volume instead. Exit code 4 means the
preflight refused; nothing was started.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.observability import latest_lab_run  # noqa: E402
from trading_bot.autonomous.paper_loop import STOP_FILE_NAME, StopController  # noqa: E402
from trading_bot.autonomous.supervisor import (  # noqa: E402
    DiskThresholds,
    ManagedProcess,
    Supervisor,
    disk_free_bytes,
)
from trading_bot.research.disk_budget import (  # noqa: E402
    DECLARED_FALLBACK_BYTES_PER_HOUR,
    REFUSED_STATES,
    free_bytes,
    plan_window,
)
from trading_bot.research.forward.outcome import EXIT_FAILED  # noqa: E402

#: The measured rate and overhead the cost plane of the preflight reads, produced by
#: ``scripts/wp9_disk_budget_audit.py``. A measurement with a named source, not a
#: constant living in the launcher.
DISK_AUDIT_PATH = Path("data/recovery/wp9/WP9_DISK_BUDGET_AUDIT.json")

#: The preflight refused and started nothing (§10, WP-9B).
EXIT_DISK_PREFLIGHT = 4

#: A new run id cannot write into a capture root another run owns (§28), so the
#: launch is refused before a single child exists.
EXIT_CAPTURE_ROOT_CONFLICT = 5

DEFAULT_LAB_ROOT = Path("reports/paper-lab")
DEFAULT_FORWARD_ROOT = Path("reports/microstructure-forward-lab")
DEFAULT_PAPER_ROOT = Path("reports/autonomous-paper")
#: Kept under the measured 0.716 GB steady state for a 2 h raw window so the
#: collector's own disk guard is never the thing that stops a run (§10).
DEFAULT_COLLECTOR_MAX_BYTES = 1_100_000_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--lab-root", default=str(DEFAULT_LAB_ROOT))
    parser.add_argument("--forward-root", default=str(DEFAULT_FORWARD_ROOT))
    parser.add_argument(
        "--data-root",
        default=None,
        help=(
            "§16 — where capture data lives. Alias for --forward-root: point it at "
            "another volume and the collector, retention, lineage and reports follow"
        ),
    )
    parser.add_argument("--paper-root", default=str(DEFAULT_PAPER_ROOT))
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--paper-interval", type=float, default=60.0)
    parser.add_argument(
        "--paper-cadence",
        dest="paper_cadence",
        choices=["interval", "bar-close"],
        default="interval",
        help=(
            "WP-STRAT-09 — forwarded to the PAPER child as --cadence. 'interval' is "
            "the default (unchanged); 'bar-close' aligns each cycle to a sealed "
            "bar's close without widening the freshness budget."
        ),
    )
    parser.add_argument(
        "--paper-settlement-seconds",
        dest="paper_settlement_seconds",
        type=float,
        default=5.0,
        help="WP-STRAT-09 — forwarded as --bar-close-settlement-seconds.",
    )
    parser.add_argument("--provider", choices=["ccxt", "fake"], default="ccxt")
    parser.add_argument(
        "--routing-mode",
        dest="routing_mode",
        choices=["LEGACY", "SHADOW", "LIFECYCLE"],
        default="LEGACY",
        help=(
            "WP-STRAT-07 — forwarded to the PAPER child as --strategy-routing-mode. "
            "LEGACY is the default (unchanged). SHADOW records the lifecycle-aware "
            "selection without affecting execution."
        ),
    )
    parser.add_argument(
        "--no-analyst",
        action="store_true",
        help=(
            "WP-SIGNAL-002 — do not start the read-only AI analyst sidecar. The stream "
            "and the dashboard do not depend on it; its failure domain is its own"
        ),
    )
    parser.add_argument(
        "--analyst-interval",
        type=float,
        default=60.0,
        help="seconds between analyst passes (each pass is bounded by --analyst-limit)",
    )
    parser.add_argument(
        "--analyst-limit",
        type=int,
        default=5,
        help="signals one analyst pass may examine (bounds latency and spend per pass)",
    )
    parser.add_argument(
        "--analyst-budget-per-hour",
        type=int,
        default=60,
        help="durable hourly cap on provider calls, read from the analysis ledger",
    )
    parser.add_argument("--rotation-seconds", type=int, default=900)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument(
        "--duration-hours",
        type=float,
        default=0.0,
        help="0 = until stopped; >0 stops the whole lab after this long",
    )
    parser.add_argument(
        "--collector-max-bytes",
        type=int,
        default=DEFAULT_COLLECTOR_MAX_BYTES,
        help="collector's own disk guard (the last barrier, §10)",
    )
    parser.add_argument("--raw-hot-hours", type=float, default=2.0)
    parser.add_argument(
        "--sealed-grace-seconds",
        type=int,
        default=1800,
        help="how long a sealed segment must be quiet before it may be compacted",
    )
    parser.add_argument(
        "--stop-grace-seconds",
        type=float,
        default=120.0,
        help=(
            "how long a child may take to finalise itself after being asked to "
            "stop, before the supervisor kills it (§51)"
        ),
    )
    parser.add_argument(
        "--delete-when-free-below",
        type=int,
        default=0,
        help="0 = compact but never delete; bytes = delete proven raw under this much free disk",
    )
    parser.add_argument("--stop", default=None, help="write STOP into this run dir and exit")
    parser.add_argument(
        "--restart",
        action="store_true",
        help=(
            "stop the named (or newest) run cleanly, wait for its children to exit, "
            "then start again with the same run id and --resume (§28)"
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the operator status of the lab and exit (§26)",
    )
    parser.add_argument("--disk-warning-gb", type=float, default=1.5)
    parser.add_argument("--disk-critical-gb", type=float, default=0.8)
    parser.add_argument("--disk-stop-gb", type=float, default=0.3)
    parser.add_argument(
        "--disk-reserve-gb",
        type=float,
        default=2.0,
        help=(
            "WP-9B — free space the preflight will not spend. The 0.3/0.8/1.5 GB levels are "
            "walls the supervisor reacts at; this is the space the host keeps for itself and "
            "for the other writers on the same volume."
        ),
    )
    parser.add_argument(
        "--expected-bytes-per-hour",
        type=float,
        default=None,
        help=(
            "WP-9B — capture rate for the disk preflight. Default: the measured rate in "
            f"{DISK_AUDIT_PATH}, else the declared conservative fallback "
            f"({DECLARED_FALLBACK_BYTES_PER_HOUR} B/h). The plan always names which it used."
        ),
    )
    parser.add_argument(
        "--disk-stress-multiplier",
        type=float,
        default=1.5,
        help="WP-9B — the preflight costs the window at this multiple of the measured rate",
    )
    parser.add_argument(
        "--autoscale-collector-budget",
        action="store_true",
        help=(
            "WP-9B — raise --collector-max-bytes to what the declared window needs at the "
            "stress rate instead of refusing. Explicit, and recorded in LAB_PLAN.json."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return parser.parse_args(argv)


def resolve_capture_measurement(args: argparse.Namespace) -> tuple[float | None, float, str]:
    """The rate the preflight costs the window at, and where that rate came from.

    Three sources, in order, each one named in the plan so a reader can disagree with the
    number rather than wonder where it came from: the operator's own declaration, the
    measurement published by the disk audit, and the declared conservative fallback.
    """
    if args.expected_bytes_per_hour is not None:
        return (
            float(args.expected_bytes_per_hour),
            0.0,
            "operator: --expected-bytes-per-hour",
        )
    path = REPO_ROOT / DISK_AUDIT_PATH
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
        rate = float(audit["measurement"]["rates"]["planning_rate_bytes_per_hour"])
        overhead = float(audit["components"]["overhead_bytes_per_hour"] or 0.0)
        windows = audit.get("windows") or {}
        measured_on = ", ".join(
            str(windows[key]["run_id"]) for key in ("sealed", "unsealed") if key in windows
        )
        return (
            rate,
            overhead,
            f"measured by scripts/wp9_disk_budget_audit.py on {measured_on or 'the audited windows'}",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return (
            None,
            0.0,
            f"{DECLARED_FALLBACK_BYTES_PER_HOUR} B/h declared fallback: {DISK_AUDIT_PATH} "
            f"is unavailable ({type(exc).__name__})",
        )


def disk_preflight(args: argparse.Namespace) -> tuple[dict[str, Any], int | None]:
    """Cost the declared window before starting anything (§10, WP-9B).

    Returns the plan section for `LAB_PLAN.json` and, when the run must not start, the
    exit code to return with it.
    """
    rate, overhead, source = resolve_capture_measurement(args)
    plan = plan_window(
        hours=args.duration_hours,
        collector_max_bytes=args.collector_max_bytes,
        free=free_bytes(REPO_ROOT),
        rate_bytes_per_hour=rate,
        rate_source=source,
        overhead_bytes_per_hour=overhead,
        stress_multiplier=args.disk_stress_multiplier,
        reserve_bytes=int(args.disk_reserve_gb * 1e9),
        autoscale=args.autoscale_collector_budget,
    )
    if plan.autoscaled:
        # The one repair the preflight may make, and it is not silent: the valve the
        # collector child will actually be given is the autoscaled one.
        args.collector_max_bytes = plan.collector_max_bytes
    section = {
        **plan.as_dict(),
        "preflight": (
            "costed before any child starts; the defect that stopped the first 24 h window "
            "was two numbers that were never compared"
        ),
        "refused": plan.state in REFUSED_STATES,
        "exit_code_when_refused": EXIT_DISK_PREFLIGHT,
    }
    return section, (EXIT_DISK_PREFLIGHT if plan.state in REFUSED_STATES else None)


def disk_thresholds(args: argparse.Namespace) -> DiskThresholds:
    """§20 — the levels, declared on the command line instead of hardcoded."""
    return DiskThresholds(
        warning_bytes=int(args.disk_warning_gb * 1e9),
        critical_bytes=int(args.disk_critical_gb * 1e9),
        stop_bytes=int(args.disk_stop_gb * 1e9),
    )


def collector_resumes(forward_root: Path, run_id: str) -> bool:
    """True when this run id already owns a capture root: a restart, not a start.

    A segment's path is a pure function of the window it covers, so the writer
    refuses to append to a window another capture wrote — deliberately, because
    that would fuse two captures into one fingerprint. A restart that does not
    say ``--resume`` therefore stops being able to write the moment it reaches a
    minute it already captured, and only the manifest, read later, would show a
    capture that died of its own past. Saying it here is what makes "restart the
    lab with the same run id" mean "continue the capture" (§51).
    """
    return (forward_root / "state" / f"{run_id}.json").exists()


def capture_root_conflict(forward_root: Path, run_id: str) -> str | None:
    """Why this run id may not write into this capture root, or ``None`` when it may.

    A segment's path is a function of the window it covers, not of the run that wrote
    it, so ``SegmentWriter`` refuses to append into a segment another capture already
    owns ("one dataset root belongs to one run"). That refusal is right, but it used
    to happen *inside* the collector: the lab started, the critical child crash-looped
    three times and the supervisor published ``DEGRADED`` for a fact nobody had been
    told before launch. The same fact is knowable before the first child exists — and
    the two ways out (``--resume`` the owner, or point ``--data-root`` at a fresh
    directory) can only be chosen by the operator, so it is decided here instead of
    discovered later.
    """
    if (forward_root / "state" / f"{run_id}.json").exists():
        # A restart of the run that owns the root: the collector appends to its past
        # on purpose, and ``--resume`` is what tells it so.
        return None
    owned: list[str] = []
    segments = forward_root / "segments"
    if segments.exists():
        owned.extend(str(path.relative_to(forward_root)) for path in segments.rglob("*.jsonl.gz"))
    manifests = forward_root / "manifest"
    if manifests.exists():
        owned.extend(
            f"manifest/{path.name}"
            for path in manifests.glob("*.json")
            if path.stem != run_id
        )
    state = forward_root / "state"
    if state.exists():
        owned.extend(
            f"state/{path.name}"
            for path in state.glob("*.json")
            if path.stem != run_id
        )
    if not owned:
        return None
    return (
        f"{forward_root} already holds a capture from another run "
        f"({len(owned)} artefact(s), e.g. {owned[0]}); one dataset root belongs to one "
        f"run. Start {run_id!r} with --data-root <fresh directory>, or --resume the run "
        f"that owns this root."
    )


def child_stop_files(args: argparse.Namespace, run_id: str, run_dir: Path) -> dict[str, Path]:
    """Where each child is asked to stop, so it can finalise instead of dying.

    A supervisor's ``terminate()`` on Windows is a hard kill: no sealing, no
    manifest, half-written segments. Every child that has cleanup to run is
    therefore stopped through a file it polls, and this is the one place that
    says which file belongs to which child (§51).
    """
    forward_root = (REPO_ROOT / args.forward_root).resolve()
    return {
        # PAPER already watches STOP inside its own run directory.
        "paper": (REPO_ROOT / args.paper_root).resolve() / run_id / STOP_FILE_NAME,
        # The collector watches a file next to the resume state it writes.
        "collector": forward_root / "state" / f"{run_id}.stop",
        # Maintenance workers ask between passes.
        "retention": run_dir / f"{STOP_FILE_NAME}.retention",
        "strategy_lab": run_dir / f"{STOP_FILE_NAME}.strategy_lab",
        "analyst": run_dir / f"{STOP_FILE_NAME}.analyst",
    }


def build_specs(
    args: argparse.Namespace, run_id: str, lab_dir: Path, stop_files: dict[str, Path]
) -> list[ManagedProcess]:
    python = sys.executable
    paper_run_root = REPO_ROOT / args.paper_root
    forward_root = (REPO_ROOT / args.forward_root).resolve()
    resume = collector_resumes(forward_root, run_id)
    return [
        ManagedProcess(
            name="paper",
            command=[
                python,
                str(REPO_ROOT / "scripts" / "autonomous_paper.py"),
                "--continuous",
                "--interval",
                str(args.paper_interval),
                "--cadence",
                args.paper_cadence,
                "--bar-close-settlement-seconds",
                str(args.paper_settlement_seconds),
                "--assets",
                args.assets,
                "--timeframe",
                args.timeframe,
                "--provider",
                args.provider,
                "--run-id",
                run_id,
                "--run-root",
                str(paper_run_root),
                "--state-path",
                str(lab_dir / "paper_state.json"),
                "--strategy-routing-mode",
                args.routing_mode,
            ],
            cwd=REPO_ROOT,
            critical=True,
            max_restarts=3,
            env={"PYTHONUNBUFFERED": "1"},
            stop_file=stop_files["paper"],
        ),
        ManagedProcess(
            name="collector",
            command=[
                python,
                str(REPO_ROOT / "scripts" / "forward_collector.py"),
                "--mode",
                "run",
                "--symbols",
                args.symbols,
                "--markets",
                "spot,perp",
                "--data-root",
                str(forward_root),
                "--run-id",
                run_id,
                *(["--resume"] if resume else []),
                "--rotation-seconds",
                str(args.rotation_seconds),
                "--heartbeat-seconds",
                "60",
                "--max-total-bytes",
                str(args.collector_max_bytes),
                # §20 — the host-free-space barrier, above the supervisor's STOP
                # level, so the capture stops before the level has to be acted on.
                "--min-free-bytes",
                str(int(args.disk_stop_gb * 1e9) + 100_000_000),
                "--stop-file",
                str(stop_files["collector"]),
            ],
            cwd=REPO_ROOT,
            critical=True,
            max_restarts=3,
            env={"PYTHONUNBUFFERED": "1"},
            stop_file=stop_files["collector"],
            # §2/§3 — the capture's own failure exit code, so the supervisor's
            # report quotes the contract instead of assuming "1".
            failure_exit_code=EXIT_FAILED,
            # §22 — the capture is what fills the volume, so it is the child the
            # storage guard stops. PAPER is not.
            stop_on_storage_guard=True,
        ),
        ManagedProcess(
            name="retention",
            command=[
                python,
                str(REPO_ROOT / "scripts" / "forward_retention.py"),
                "--root",
                str(forward_root),
                "--run-id",
                run_id,
                "--rotation-seconds",
                str(args.rotation_seconds),
                "--raw-hot-hours",
                str(args.raw_hot_hours),
                "--sealed-grace-seconds",
                str(args.sealed_grace_seconds),
                "--delete-when-free-below",
                str(args.delete_when_free_below),
                "--loop",
                "--interval",
                "300",
                "--stop-file",
                str(stop_files["retention"]),
            ],
            cwd=REPO_ROOT,
            critical=False,
            max_restarts=2,
            env={"PYTHONUNBUFFERED": "1"},
            stop_file=stop_files["retention"],
        ),
        ManagedProcess(
            name="strategy_lab",
            command=[
                python,
                str(REPO_ROOT / "scripts" / "paper_lab_research.py"),
                "--run-root",
                str(lab_dir),
                "--forward-root",
                str(args.forward_root),
                "--timeframe",
                args.timeframe,
                "--assets",
                args.assets,
                "--loop",
                "--interval",
                "900",
                "--stop-file",
                str(stop_files["strategy_lab"]),
            ],
            cwd=REPO_ROOT,
            critical=False,
            max_restarts=2,
            env={"PYTHONUNBUFFERED": "1"},
            stop_file=stop_files["strategy_lab"],
        ),
        *(
            []
            if getattr(args, "no_analyst", False)
            else [
                ManagedProcess(
                    name="analyst",
                    command=[
                        python,
                        str(REPO_ROOT / "scripts" / "ai_signal_analyst.py"),
                        "--run-root",
                        args.paper_root,
                        "--run-id",
                        run_id,
                        "--loop",
                        "--interval",
                        str(args.analyst_interval),
                        "--limit-per-pass",
                        str(args.analyst_limit),
                        "--budget-per-hour",
                        str(args.analyst_budget_per_hour),
                        "--stop-file",
                        str(stop_files["analyst"]),
                    ],
                    cwd=REPO_ROOT,
                    critical=False,
                    max_restarts=2,
                    env={"PYTHONUNBUFFERED": "1"},
                    stop_file=stop_files["analyst"],
                )
            ]
        ),
    ]


def capability_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """What this launch may actually do, per layer, before anything starts.

    The economic block (0 admitted strategies) must not stop the signal plane: an
    ingestion or projection failure and an admission refusal are different facts,
    and collapsing them is how "BLOCKED" turns into "nothing to watch". Each layer
    is reported with the reason it holds, and the admission verdict is read from
    the tracked ledger rather than asserted here.
    """
    ledger_path = REPO_ROOT / "config" / "strategy_admission.json"
    layers: dict[str, dict[str, Any]] = {
        "LIVE": {
            "state": "DISABLED",
            "reason": "no live path exists: every child is read-only market data or PAPER",
        }
    }
    admitted: list[str] = []
    strategies = 0
    ledger_error: str | None = None
    try:
        from trading_bot.autonomous.admission_ledger import AdmissionLedger

        ledger = AdmissionLedger.load(ledger_path)
        strategies = len(ledger.strategy_ids())
        admitted = list(ledger.paper_candidates())
    except Exception as exc:  # a missing ledger is a finding, not a crash
        ledger_error = f"{type(exc).__name__}: {exc}"
    layers["INGEST"] = {
        "state": "ENABLED",
        "reason": "read-only market data via the configured provider",
    }
    layers["SIGNALS"] = {
        "state": "ENABLED",
        "reason": (
            "projection of the persisted decision traces; independent of admission, "
            "so REJECTED/NO_ALPHA rows are produced with 0 admitted strategies"
        ),
    }
    layers["SHADOW"] = {
        "state": "ENABLED",
        "reason": "SHADOW records an observation and can never create an order",
    }
    layers["PAPER_ORDER"] = {
        "state": "ENABLED" if admitted else "BLOCKED",
        "reason": (
            f"admitted for paper: {', '.join(admitted)}"
            if admitted
            else (
                f"the admission ledger admits none of its {strategies} strategies for paper "
                f"({ledger_error or 'gate not met'})"
            )
        ),
    }
    layers["ANALYST"] = {
        "state": "ENABLED" if not getattr(args, "no_analyst", False) else "DISABLED",
        "reason": (
            "read-only sidecar; records NOT_CONFIGURED when no provider key is present"
            if not getattr(args, "no_analyst", False)
            else "disabled by --no-analyst"
        ),
    }
    return {
        "strategy_count": strategies,
        "admitted_for_paper": admitted,
        "paper_order_enabled": bool(admitted),
        "layers": layers,
        "ledger": str(ledger_path.relative_to(REPO_ROOT)),
        "ledger_error": ledger_error,
    }


def print_status(args: argparse.Namespace) -> int:
    """§26 — one command that answers "what is happening right now"."""
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "paper_lab_status.py"),
        "--lab-root",
        str(args.lab_root),
        "--paper-root",
        str(args.paper_root),
    ]
    if args.run_id:
        command += ["--run-id", args.run_id]
    completed = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
    return completed.returncode


def stop_lab(run_dir: Path) -> None:
    """Ask a running lab to stop, the same way an operator would (§27)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / STOP_FILE_NAME).write_text(
        f"stop requested at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n",
        encoding="utf-8",
    )


def wait_for_stop(run_dir: Path, *, timeout: float) -> dict[str, Any]:
    """Wait until the supervisor has recorded that its children are done (§28).

    Read from the heartbeat rather than from the process table: the heartbeat is
    what the restart is allowed to leave behind, and a stale one means the lab is
    gone whether or not a PID still exists.
    """
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = json.loads((run_dir / "SYSTEM_HEARTBEAT.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = {}
        processes = last.get("processes") or {}
        if processes and all(
            entry.get("state") != "RUNNING" for entry in processes.values()
        ):
            return last
        time.sleep(1.0)
    return last


def wait_for_supervisor_exit(heartbeat: dict[str, Any], *, timeout: float = 60.0) -> bool:
    """Wait until the *report writer* is gone, not just its children.

    D-09: the children finishing is not the previous window being finished with —
    the supervisor writes `LAB_RUN_REPORT.json` after them, and archiving while it
    is still writing would race the writer. The heartbeat publishes its own pid for
    exactly this. An older heartbeat has no pid: then there is nothing to wait for
    and the caller archives what it finds, rather than inventing a wait it cannot
    observe.
    """
    from trading_bot.autonomous.observability import process_alive

    pid = heartbeat.get("supervisor_pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if process_alive(pid) is not True:
            return True
        time.sleep(0.5)
    return False


#: The files a window leaves behind, by who wrote them.
WINDOW_LAB_FILES = (
    "LAB_RUN_REPORT.json",
    "LAB_RUN_REPORT.md",
    "LAB_RUN_SNAPSHOT.json",
    "SYSTEM_HEARTBEAT.json",
    "STRATEGY_LAB_REPORT.json",
    "STRATEGY_LAB_REPORT.md",
)
WINDOW_PAPER_FILES = (
    "heartbeat.jsonl",
    "heartbeat.json",
    "PAPER_RUN.json",
    "AI_ANALYST_HEARTBEAT.json",
    # The per-run summary is rewritten by the next window's finalise, so the
    # closed window's copy is what keeps it: cycle detail survives in the
    # append-only traces either way, but a report that existed should not vanish.
    "RUN_REPORT.json",
    "RUN_REPORT.md",
    "PAPER_DAILY_REPORT.json",
    "PAPER_DAILY_REPORT.md",
)
#: Copied, never moved: the new window overwrites them, and a refused launch must
#: not be able to delete the previous window's provenance.
WINDOW_PAPER_COPIES = (
    "PAPER_RUN.json",
    "AI_ANALYST_HEARTBEAT.json",
    "RUN_REPORT.json",
    "RUN_REPORT.md",
    "PAPER_DAILY_REPORT.json",
    "PAPER_DAILY_REPORT.md",
)
WINDOWS_DIRNAME = "windows"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _window_id(lab_run_dir: Path) -> str:
    """A stable name for the window being closed, and one that cannot collide."""
    ended_ms: int | None = None
    try:
        report = json.loads((lab_run_dir / "LAB_RUN_REPORT.json").read_text(encoding="utf-8"))
        ended = report.get("ended_at_ms")
        ended_ms = int(ended) if isinstance(ended, int) else None
    except (OSError, ValueError, TypeError):
        ended_ms = None
    stamp = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ended_ms / 1000))
        if ended_ms
        else time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    )
    base = f"{stamp}"
    candidate = base
    suffix = 1
    while (lab_run_dir / WINDOWS_DIRNAME / candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def read_window_index(lab_run_dir: Path) -> list[dict[str, Any]]:
    """The windows this run id has already closed, newest last."""
    path = lab_run_dir / WINDOWS_DIRNAME / "INDEX.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    windows = payload.get("windows") if isinstance(payload, dict) else None
    return [entry for entry in windows or [] if isinstance(entry, dict)]


def archive_previous_window(
    *,
    lab_run_dir: Path,
    paper_run_dir: Path,
    reason: str = "restart",
) -> dict[str, Any] | None:
    """Archive the window a restart is about to overwrite (D-09).

    A restart reuses the run id, so the files that describe the finished window
    are the same files the new one writes: `LAB_RUN_REPORT.json` was overwritten
    and `heartbeat.jsonl` was appended to with cycle numbers starting again at 1,
    which fused two windows into one unreadable journal. Nothing is deleted here:
    the window's reports move into `windows/<window_id>/`, the PAPER journal moves
    with them, and a manifest records every file's sha256 so the archive can be
    checked later without trusting this function.
    """
    lab_files = [(lab_run_dir / name, "move") for name in WINDOW_LAB_FILES]
    paper_files = [
        (
            paper_run_dir / name,
            "copy" if name in WINDOW_PAPER_COPIES else "move",
        )
        for name in WINDOW_PAPER_FILES
    ]
    present = [(path, action) for path, action in lab_files + paper_files if path.is_file()]
    if not present:
        return None
    window_id = _window_id(lab_run_dir)
    target = lab_run_dir / WINDOWS_DIRNAME / window_id
    target.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for path, action in present:
        archived = target / path.name
        entries.append(
            {
                "name": path.name,
                "source": str(path),
                "action": action,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
        if action == "move":
            shutil.move(str(path), str(archived))
        else:
            shutil.copy2(str(path), str(archived))
    previous: dict[str, Any] = {}
    try:
        previous = json.loads((target / "LAB_RUN_REPORT.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    manifest = {
        "schema_version": "lab-window-v1",
        "window_id": window_id,
        "reason": reason,
        "archived_at_ms": int(time.time() * 1000),
        "lab_run_dir": str(lab_run_dir),
        "paper_run_dir": str(paper_run_dir),
        "previous_final_state": previous.get("final_state"),
        "previous_stop_reason": previous.get("stop_reason"),
        "previous_stop_verdict": (previous.get("stop_report") or {}).get("verdict"),
        "previous_duration_seconds": previous.get("duration_seconds"),
        "files": entries,
        "note": (
            "a restart reuses the run id, so the closed window is preserved here "
            "instead of being overwritten; nothing was deleted"
        ),
    }
    manifest_path = target / "WINDOW_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    index_path = lab_run_dir / WINDOWS_DIRNAME / "INDEX.json"
    index = {"schema_version": "lab-windows-v1", "windows": read_window_index(lab_run_dir)}
    index["windows"].append(
        {
            "window_id": window_id,
            "archived_at_ms": manifest["archived_at_ms"],
            "reason": reason,
            "manifest": str(manifest_path.relative_to(lab_run_dir)),
            "final_state": manifest["previous_final_state"],
            "stop_reason": manifest["previous_stop_reason"],
            "stop_verdict": manifest["previous_stop_verdict"],
            "files": len(entries),
        }
    )
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, index_path)
    manifest["path"] = str(target)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main() -> int:
    args = parse_args()
    if args.data_root:
        args.forward_root = args.data_root
    if args.status:
        return print_status(args)
    lab_dir = (REPO_ROOT / args.lab_root).resolve()
    if args.restart:
        target = (
            lab_dir / args.run_id
            if args.run_id
            else (latest_lab_run(lab_dir) or lab_dir / "paper-lab-unknown")
        )
        print(f"[lab] restart requested for {target}")
        stop_lab(target)
        heartbeat = wait_for_stop(target, timeout=args.stop_grace_seconds + 60.0)
        print(f"[lab] previous run settled: {heartbeat.get('state') or 'no heartbeat'}")
        settled = wait_for_supervisor_exit(heartbeat)
        print(
            "[lab] previous supervisor exited"
            if settled
            else "[lab] previous supervisor pid unknown or still present; archiving anyway"
        )
        args.run_id = target.name
        archived = archive_previous_window(
            lab_run_dir=target,
            paper_run_dir=(REPO_ROOT / args.paper_root).resolve() / target.name,
        )
        if archived is None:
            print(f"[lab] nothing to archive under {target} (no previous window files)")
        else:
            print(
                f"[lab] previous window archived: {archived['path']} "
                f"({len(archived['files'])} files)"
            )
    if args.stop:
        target = (
            Path(args.stop)
            if Path(args.stop).is_absolute()
            else (REPO_ROOT / args.stop).resolve()
        )
        stop_lab(target)
        print(f"[lab] STOP written to {target / STOP_FILE_NAME}")
        return 0

    run_id = args.run_id or f"paper-lab-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    run_dir = lab_dir / run_id
    stop_files = child_stop_files(args, run_id, run_dir)
    forward_root = (REPO_ROOT / args.forward_root).resolve()
    capture_conflict = capture_root_conflict(forward_root, run_id)
    # §10/WP-9B — cost the window before the children exist, so an autoscaled valve is
    # the valve the collector is actually launched with.
    disk_budget, refused = disk_preflight(args)
    capabilities = capability_preflight(args)
    specs = build_specs(args, run_id, run_dir, stop_files)

    plan = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "duration_hours": args.duration_hours,
        "free_disk_bytes": disk_free_bytes(REPO_ROOT),
        "processes": [spec.to_dict() for spec in specs],
        "capabilities": capabilities,
        "isolation": (
            "paper and collector are separate processes; the supervisor restarts "
            "each independently and neither shares state with the other"
        ),
        "retention": {
            "raw_hot_hours": args.raw_hot_hours,
            "sealed_grace_seconds": args.sealed_grace_seconds,
            "delete_when_free_below": args.delete_when_free_below,
            "deletion_enabled": args.delete_when_free_below > 0,
            "preservation": (
                "raw is deleted only after M-03 and M-07 are shown to survive "
                "compaction at the preregistered resolution"
            ),
        },
        "disk": {
            "thresholds": disk_thresholds(args).as_dict(),
            "budget": disk_budget,
            "storage_guard": (
                "at the STOP level the collector is asked to stop gracefully; PAPER "
                "is not touched"
            ),
        },
        "collector_resume": collector_resumes(
            (REPO_ROOT / args.forward_root).resolve(), run_id
        ),
        "windows": {
            "archive_dir": str(run_dir / WINDOWS_DIRNAME),
            "previous": read_window_index(run_dir),
            "rule": (
                "a restart archives the closed window (reports, snapshot, system "
                "heartbeat and the PAPER journal) under windows/<window_id>/ "
                "before the new window writes anything"
            ),
        },
        "graceful_stop": {
            "stop_grace_seconds": args.stop_grace_seconds,
            "stop_files": {name: str(path) for name, path in stop_files.items()},
            "method": (
                "the supervisor writes each child's stop file, waits for it to seal and "
                "finalise, and only then terminates the ones that did not exit"
            ),
        },
        "capture_root": {
            "path": str(forward_root),
            "conflict": capture_conflict,
            "exit_code_when_refused": EXIT_CAPTURE_ROOT_CONFLICT,
        },
        "no_live_path": (
            "children are read-only market data plus the PAPER broker; no child "
            "holds execution credentials"
        ),
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        if capture_conflict:
            print(f"[lab] capture root REFUSED: {capture_conflict}", file=sys.stderr)
        if refused:
            print(
                f"[lab] disk preflight REFUSED: {disk_budget['state']} — "
                + "; ".join(disk_budget["reasons"]),
                file=sys.stderr,
            )
        return refused or (EXIT_CAPTURE_ROOT_CONFLICT if capture_conflict else 0)

    if capture_conflict:
        # Nothing has been created yet: no run directory, no child, no crash-loop for
        # the supervisor to report as a mystery. The refusal names both ways out.
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "capture_root": str(forward_root),
                    "conflict": capture_conflict,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"[lab] capture root REFUSED: {capture_conflict}", file=sys.stderr)
        return EXIT_CAPTURE_ROOT_CONFLICT

    if refused:
        # Nothing has been created yet: no run directory, no child, no partial capture
        # that would look like an experiment. The refusal names the arithmetic.
        print(
            json.dumps({"run_id": run_id, "disk_budget": disk_budget}, indent=2, ensure_ascii=False)
        )
        print(
            f"[lab] disk preflight REFUSED ({disk_budget['state']}): "
            + "; ".join(disk_budget["reasons"]),
            file=sys.stderr,
        )
        return refused

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "LAB_PLAN.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    paper_run_root = (REPO_ROOT / args.paper_root).resolve()
    supervisor = Supervisor.build(
        run_dir,
        specs,
        heartbeat_seconds=args.heartbeat_seconds,
        disk_thresholds=disk_thresholds(args),
        child_heartbeats={
            # PAPER writes its heartbeat inside its own run directory (which is
            # named after the lab run); the collector publishes its live state
            # while it runs and replaces it atomically, because the manifest only
            # exists once the capture has finalised.
            "paper": paper_run_root / run_id / "heartbeat.json",
            "collector": (REPO_ROOT / args.forward_root).resolve() / "state" / f"{run_id}.json",
        },
    )
    stop = StopController(run_dir=run_dir)
    stop.clear_stop_file()
    stop.install()

    print(f"[lab] run id      : {run_id}")
    print(f"[lab] run dir     : {run_dir}")
    print(f"[lab] free disk   : {disk_free_bytes(REPO_ROOT) / 1e9:.3f} GB")
    print(f"[lab] duration    : {'until stopped' if not args.duration_hours else f'{args.duration_hours} h'}")
    print(f"[lab] stop with   : Ctrl-C, or write STOP into {run_dir}")
    print(f"[lab] graceful    : {args.stop_grace_seconds:.0f}s to finalise before a kill")
    print(f"[lab] capabilities: {json.dumps(capabilities['layers'], ensure_ascii=False)}")
    for spec in specs:
        print(f"[lab]   {spec.name:<13} critical={spec.critical} :: {' '.join(spec.command[:3])} ...")

    supervisor.start_all()
    events: list[dict[str, Any]] = []

    def on_event(event: dict[str, Any]) -> None:
        event = {**event, "timestamp_ms": int(time.time() * 1000)}
        events.append(event)
        print(f"[supervisor] {event}")

    supervisor_error: str | None = None
    interrupted = False
    try:
        final = supervisor.supervise_forever(
            stop_requested=lambda: stop.stopped,
            on_event=on_event,
            max_seconds=(args.duration_hours * 3600.0) if args.duration_hours else None,
            stop_grace_seconds=args.stop_grace_seconds,
        )
    except BaseException as exc:  # the report must survive the crash too
        # A supervisor that dies must still leave evidence: an unexplained dead
        # lab is worse than a lab that says why it died.
        interrupted = isinstance(exc, KeyboardInterrupt)
        supervisor_error = (
            None if interrupted else f"{type(exc).__name__}: {exc}"
        )
        if supervisor_error:
            events.append({"event": "SUPERVISOR_ERROR", "reason": supervisor_error})
            print(f"[lab] supervisor error: {supervisor_error}", file=sys.stderr)
        final = {}
    finally:
        final = {**supervisor.status(), **final}

    state = final.get("state")
    stop_report = final.get("stop_report") or {}
    failed_on_stop = [
        name
        for name in stop_report.get("failed_children", [])
        + stop_report.get("escalated", [])
    ]

    report = {
        "schema_version": "paper-lab-run-report-v1",
        "run_id": run_id,
        "started_at_ms": supervisor.started_at_ms,
        "ended_at_ms": int(time.time() * 1000),
        "duration_seconds": round(time.time() - supervisor.started_at_ms / 1000, 3),
        "configured_duration_hours": args.duration_hours,
        "stop_reason": resolve_stop_reason(
            reason=stop.reason,
            stop_file=run_dir / STOP_FILE_NAME,
            configured_duration_hours=args.duration_hours,
        ),
        "final_state": state,
        "processes": final.get("processes", {}),
        "supervisor_events": events,
        "supervisor_error": supervisor_error,
        "stop_report": stop_report,
        "disk_free_bytes": disk_free_bytes(REPO_ROOT),
        "disk": final.get("disk"),
        "configuration": {
            "collector_max_bytes": args.collector_max_bytes,
            "raw_hot_hours": args.raw_hot_hours,
            "delete_when_free_below": args.delete_when_free_below,
            "rotation_seconds": args.rotation_seconds,
            "sealed_grace_seconds": args.sealed_grace_seconds,
            "disk_thresholds": disk_thresholds(args).as_dict(),
            "forward_root": args.forward_root,
            "data_root_is_forward_root": True,
        },
        "plan": plan,
        "previous_windows": read_window_index(run_dir),
    }
    report_path = run_dir / "LAB_RUN_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path = run_dir / "LAB_RUN_REPORT.md"
    md_path.write_text(render_report(report), encoding="utf-8")
    write_system_daily_report(args, run_dir)
    # §24 — the operational snapshot is evidence, not a scrollback buffer.
    snapshot = {
        "schema_version": "paper-lab-run-snapshot-v1",
        "run_id": run_id,
        "captured_at_ms": int(time.time() * 1000),
        "duration_seconds": report["duration_seconds"],
        "stop_reason": report["stop_reason"],
        "final_state": state,
        "processes": final.get("processes", {}),
        "stop_report": stop_report,
        "supervisor_error": supervisor_error,
        "interrupted": interrupted,
        "disk": final.get("disk"),
        "supervisor_events": events,
    }
    snapshot_path = run_dir / "LAB_RUN_SNAPSHOT.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[lab] final state : {state}")
    print(f"[lab] report      : {report_path}")
    print(f"[lab] report      : {md_path}")
    print(f"[lab] snapshot    : {snapshot_path}")
    if stop_report:
        print(f"[lab] stop verdict: {stop_report.get('verdict')} {failed_on_stop or ''}")
    if interrupted:
        return 130
    if supervisor_error or state == "FAILED" or failed_on_stop:
        return 1
    return 0


def resolve_stop_reason(
    *,
    reason: str | None,
    stop_file: Path,
    configured_duration_hours: float,
) -> str:
    """Which exit this was, checked against the evidence rather than assumed.

    A STOP file is honoured by the loop the same way the operator's Ctrl-C is, so
    a duration-limited run that was stopped early must not be reported as having
    reached its duration.
    """
    if reason:
        return reason
    if stop_file.exists():
        return "STOP file"
    if configured_duration_hours:
        return "duration reached"
    return "STOP file"


def write_system_daily_report(args: argparse.Namespace, run_dir: Path) -> None:
    """§47 — fold PAPER + collector + strategy lab into one report at shutdown.

    Best effort on purpose: a missing report is a finding the operator can read
    in the next report, and must never turn a clean shutdown into a failure.
    """
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "system_daily_report.py"),
        "--lab-run-dir",
        str(run_dir),
        "--forward-root",
        str(args.forward_root),
        "--forward-run-id",
        run_dir.name,
        "--lab-report",
        str(run_dir / "STRATEGY_LAB_REPORT.json"),
    ]
    try:
        completed = subprocess.run(
            command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[lab] system daily report skipped: {type(exc).__name__}: {exc}")
        return
    for line in (completed.stdout or "").splitlines():
        print(line)
    if completed.returncode != 0:
        print(f"[lab] system daily report failed: {(completed.stderr or '').strip()[-500:]}")


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"# PAPER LAB RUN — {report['run_id']}",
        "",
        "```text",
        f"final state : {report['final_state']}",
        f"duration    : {report['duration_seconds']} s",
        f"stop reason : {report['stop_reason']}",
        f"disk free   : {report['disk_free_bytes'] / 1e9:.3f} GB",
        "```",
        "",
        "## Processes",
        "",
        "| process | critical | state | restarts | exit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, runtime in sorted(report["processes"].items()):
        lines.append(
            f"| {name} | {runtime['critical']} | {runtime['state']} | "
            f"{runtime['restarts']} | {runtime['exit_code']} |"
        )
    lines.append("")
    if report["supervisor_events"]:
        lines.append("## Supervision events")
        lines.append("")
        for event in report["supervisor_events"][:100]:
            lines.append(f"- `{event.get('event')}` {event.get('process')} {event.get('reason') or ''}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
