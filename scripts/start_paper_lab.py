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
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.paper_loop import STOP_FILE_NAME, StopController  # noqa: E402
from trading_bot.autonomous.supervisor import (  # noqa: E402
    ManagedProcess,
    Supervisor,
    disk_free_bytes,
)

DEFAULT_LAB_ROOT = Path("reports/paper-lab")
DEFAULT_FORWARD_ROOT = Path("reports/microstructure-forward-lab")
DEFAULT_PAPER_ROOT = Path("reports/autonomous-paper")
#: Kept under the measured 0.716 GB steady state for a 2 h raw window so the
#: collector's own disk guard is never the thing that stops a run (§10).
DEFAULT_COLLECTOR_MAX_BYTES = 1_100_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--lab-root", default=str(DEFAULT_LAB_ROOT))
    parser.add_argument("--forward-root", default=str(DEFAULT_FORWARD_ROOT))
    parser.add_argument("--paper-root", default=str(DEFAULT_PAPER_ROOT))
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--paper-interval", type=float, default=60.0)
    parser.add_argument("--provider", choices=["ccxt", "fake"], default="ccxt")
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
        "--delete-when-free-below",
        type=int,
        default=0,
        help="0 = compact but never delete; bytes = delete proven raw under this much free disk",
    )
    parser.add_argument("--stop", default=None, help="write STOP into this run dir and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return parser.parse_args()


def build_specs(args: argparse.Namespace, run_id: str, lab_dir: Path) -> list[ManagedProcess]:
    python = sys.executable
    paper_run_root = REPO_ROOT / args.paper_root
    forward_root = (REPO_ROOT / args.forward_root).resolve()
    return [
        ManagedProcess(
            name="paper",
            command=[
                python,
                str(REPO_ROOT / "scripts" / "autonomous_paper.py"),
                "--continuous",
                "--interval",
                str(args.paper_interval),
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
            ],
            cwd=REPO_ROOT,
            critical=True,
            max_restarts=3,
            env={"PYTHONUNBUFFERED": "1"},
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
                "--out",
                str(forward_root),
                "--run-id",
                run_id,
                "--rotation-seconds",
                str(args.rotation_seconds),
                "--heartbeat-seconds",
                "60",
                "--max-total-bytes",
                str(args.collector_max_bytes),
            ],
            cwd=REPO_ROOT,
            critical=True,
            max_restarts=3,
            env={"PYTHONUNBUFFERED": "1"},
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
            ],
            cwd=REPO_ROOT,
            critical=False,
            max_restarts=2,
            env={"PYTHONUNBUFFERED": "1"},
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
            ],
            cwd=REPO_ROOT,
            critical=False,
            max_restarts=2,
            env={"PYTHONUNBUFFERED": "1"},
        ),
    ]


def main() -> int:
    args = parse_args()
    lab_dir = (REPO_ROOT / args.lab_root).resolve()
    if args.stop:
        target = (REPO_ROOT / args.stop).resolve() if not Path(args.stop).is_absolute() else Path(args.stop)
        target.mkdir(parents=True, exist_ok=True)
        (target / STOP_FILE_NAME).write_text(
            f"stop requested at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n",
            encoding="utf-8",
        )
        print(f"[lab] STOP written to {target / STOP_FILE_NAME}")
        return 0

    run_id = args.run_id or f"paper-lab-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    run_dir = lab_dir / run_id
    specs = build_specs(args, run_id, run_dir)

    plan = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "duration_hours": args.duration_hours,
        "free_disk_bytes": disk_free_bytes(REPO_ROOT),
        "processes": [spec.to_dict() for spec in specs],
        "isolation": (
            "paper and collector are separate processes; the supervisor restarts "
            "each independently and neither shares state with the other"
        ),
        "retention": {
            "raw_hot_hours": args.raw_hot_hours,
            "sealed_grace_seconds": args.sealed_grace_seconds,
            "delete_when_free_below": args.delete_when_free_below,
            "deletion_enabled": args.delete_when_free_below > 0,
        },
        "no_live_path": (
            "children are read-only market data plus the PAPER broker; no child "
            "holds execution credentials"
        ),
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "LAB_PLAN.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    paper_run_root = (REPO_ROOT / args.paper_root).resolve()
    supervisor = Supervisor.build(
        run_dir,
        specs,
        heartbeat_seconds=args.heartbeat_seconds,
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
    for spec in specs:
        print(f"[lab]   {spec.name:<13} critical={spec.critical} :: {' '.join(spec.command[:3])} ...")

    supervisor.start_all()
    events: list[dict[str, Any]] = []

    def on_event(event: dict[str, Any]) -> None:
        event = {**event, "timestamp_ms": int(time.time() * 1000)}
        events.append(event)
        print(f"[supervisor] {event}")

    try:
        final = supervisor.supervise_forever(
            stop_requested=lambda: stop.stopped,
            on_event=on_event,
            max_seconds=(args.duration_hours * 3600.0) if args.duration_hours else None,
        )
    finally:
        final = supervisor.status()

    state = final.get("state")

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
        "disk_free_bytes": disk_free_bytes(REPO_ROOT),
        "plan": plan,
    }
    report_path = run_dir / "LAB_RUN_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path = run_dir / "LAB_RUN_REPORT.md"
    md_path.write_text(render_report(report), encoding="utf-8")
    write_system_daily_report(args, run_dir)
    print(f"[lab] final state : {state}")
    print(f"[lab] report      : {report_path}")
    print(f"[lab] report      : {md_path}")
    return 0 if state in ("HEALTHY", "DEGRADED") else 1


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
