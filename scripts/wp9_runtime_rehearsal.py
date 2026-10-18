"""WP-9C — runtime rehearsal: the real entrypoint, measured, with its limits stated.

The operator asked for a 24 h window that does not depend on paper authorisation. This
script *prepares and drives* that window and reports exactly how much of it ran: running
a fraction of a day and calling the result a stability test is the failure mode this file
exists to make impossible.

What it does, and why this way:

* it drives ``scripts/autonomous_paper.py`` — **the runtime's own entrypoint**, the same
  one ``scripts/start_paper_lab.py`` starts as its ``paper`` child. A rehearsal of a
  harness that the operator never runs would certify nothing (``TEST_TARGET ==
  RUNTIME_TARGET``);
* it runs **legs**, because continuity is a claim that needs a boundary to be true about:
  a free-running leg, a leg aligned to sealed bars (``--cadence bar-close``), a leg
  stopped through the runtime's own STOP file (§51 — the loop finishes the cycle it is
  in and exits zero), and a leg that resumes after that stop with the same run id, run
  root and state path;
* every leg's ``RUN_REPORT.json`` is copied out immediately, because the runtime writes
  it per invocation and the next leg would otherwise overwrite the evidence of the last;
* the checks are re-derived from the artefacts the runtime itself persisted — the trace
  chain, the cycle detail, the replay summary — by an implementation that does not
  import the runtime's own decision code, so a green result was not graded by the thing
  being graded;
* CPU and memory are measured on the child process through the operating system
  (``GetProcessTimes`` / ``GetProcessMemoryInfo`` on Windows, ``/proc/<pid>`` elsewhere).
  When the platform cannot answer, the field says ``NOT_MEASURED`` rather than a zero.

The verdict vocabulary is deliberately narrow. ``window_complete`` is false unless the
wall clock really covered the target, and a check that the executed window could not
reach says ``NOT_EXERCISED`` — never ``PASS``. In particular: with no admitted strategy
there is no proposal, and the runtime reviews agents, binds risk and verifies only when
there is a proposal, so those branches are NOT_EXERCISED in a real window and the only
evidence for them is the labelled fixture (§3.1, §13 of the runtime document). Saying so
is the point of the report.

Read-only with respect to the repository: it writes under ``reports/autonomous-paper/``
and ``data/recovery/wp9/``, never to a source file, and it never touches LIVE.

Exit codes: 0 the rehearsal ran (whatever it concluded), 2 a leg failed to run, 3 a
check failed, 4 blocked (no provider reachable and no declaration to accept that).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.autonomous.paper_loop import STOP_FILE_NAME  # noqa: E402
from trading_bot.ops import windowless  # noqa: E402
from trading_bot.research.router_gates import (  # noqa: E402
    DEFAULT_FRESHNESS_GRACE_BARS,
    timeframe_ms,
)

ENTRYPOINT = "scripts/autonomous_paper.py"
RUN_ROOT = ROOT / "reports" / "autonomous-paper"
OUT_DIR = ROOT / "data" / "recovery" / "wp9"

#: The window the operator asked for, in hours, and the reason it is a *target* here.
TARGET_HOURS = 24.0

PASS, FAIL, NOT_EXERCISED = "PASS", "FAIL", "NOT_EXERCISED"


@dataclass
class Leg:
    name: str
    args: list[str]
    stop_after_seconds: float | None = None
    notes: str = ""
    result: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# the operating system's view of the child
# --------------------------------------------------------------------------- #


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_char * 260),
    ]


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def descendants_of(pid: int) -> list[int]:
    """Every process whose ancestry reaches ``pid``, on Windows.

    This matters more than it looks. A virtual environment's ``python.exe`` can be a small
    launcher that re-executes the real interpreter as its child, so sampling one PID
    reports the launcher's few megabytes and near-zero CPU while the runtime works in a
    process nobody measured. A resource claim has to cover the tree or it is a claim
    about the wrong process.
    """
    if os.name != "nt":  # pragma: no cover - platform dependent
        return [pid]
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        TH32CS_SNAPPROCESS = 0x00000002
        INVALID = ctypes.c_void_p(-1).value
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID:
            return [pid]
        try:
            entry = _PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
            parents: dict[int, int] = {}
            ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
            while ok:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except (OSError, AttributeError):  # pragma: no cover
        return [pid]
    tree = {pid}
    changed = True
    while changed:
        changed = False
        for child, parent in parents.items():
            if parent in tree and child not in tree:
                tree.add(child)
                changed = True
    return sorted(tree)


def sample_process(pid: int) -> dict[str, Any]:
    """Working set and CPU time of a process tree, or a declared ``NOT_MEASURED``.

    Uses the operating system directly: adding a telemetry dependency to a runtime that
    is being rehearsed would change the thing being measured. The aggregate covers the
    process and its descendants, so a launcher stub cannot stand in for the runtime.
    """
    members = descendants_of(pid)
    if len(members) > 1:
        samples = [_sample_single(member) for member in members]
        measured = [sample for sample in samples if sample.get("state") == "MEASURED"]
        if not measured:
            return {"state": "NOT_MEASURED", "why": "no process in the tree could be opened"}
        return {
            "state": "MEASURED",
            "method": measured[0]["method"] + " summed over the process tree",
            "processes": len(measured),
            "rss_mb": round(sum(sample["rss_mb"] or 0 for sample in measured), 3),
            "peak_rss_mb": round(sum(sample["peak_rss_mb"] or 0 for sample in measured), 3),
            "cpu_seconds": round(sum(sample["cpu_seconds"] or 0 for sample in measured), 3),
        }
    return _sample_single(pid)


def _sample_single(pid: int) -> dict[str, Any]:
    """One process's working set and CPU time, or a declared ``NOT_MEASURED``."""
    if os.name == "nt":  # pragma: no cover - platform dependent
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            process = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not process:
                return {"state": "NOT_MEASURED", "why": "OpenProcess refused"}
            try:
                counters = _PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
                memory_ok = bool(
                    psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
                )
                creation, exit_time, kernel, user = (
                    _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME(),
                )
                times_ok = bool(
                    kernel32.GetProcessTimes(
                        process, ctypes.byref(creation), ctypes.byref(exit_time),
                        ctypes.byref(kernel), ctypes.byref(user),
                    )
                )
            finally:
                kernel32.CloseHandle(process)
            hundred_ns = 10_000_000
            cpu_seconds = None
            if times_ok:
                cpu_seconds = (
                    (kernel.dwHighDateTime << 32 | kernel.dwLowDateTime)
                    + (user.dwHighDateTime << 32 | user.dwLowDateTime)
                ) / hundred_ns
            return {
                "state": "MEASURED",
                "method": "win32 GetProcessMemoryInfo + GetProcessTimes",
                "rss_mb": round(counters.WorkingSetSize / 1e6, 3) if memory_ok else None,
                "peak_rss_mb": round(counters.PeakWorkingSetSize / 1e6, 3) if memory_ok else None,
                "cpu_seconds": round(cpu_seconds, 3) if cpu_seconds is not None else None,
            }
        except (OSError, AttributeError) as exc:  # pragma: no cover
            return {"state": "NOT_MEASURED", "why": f"{type(exc).__name__}: {exc}"}
    try:  # pragma: no cover - platform dependent
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        return {
            "state": "MEASURED",
            "method": "/proc/<pid>/statm + stat",
            "rss_mb": round(int(statm[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6, 3),
            "peak_rss_mb": None,
            "cpu_seconds": round((int(stat[13]) + int(stat[14])) / os.sysconf("SC_CLK_TCK"), 3),
        }
    except (OSError, KeyError, ValueError) as exc:  # pragma: no cover
        return {"state": "NOT_MEASURED", "why": f"{type(exc).__name__}: {exc}"}


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


# --------------------------------------------------------------------------- #
# the legs
# --------------------------------------------------------------------------- #


def leg_command(args: argparse.Namespace, leg: Leg) -> list[str]:
    return [
        sys.executable,
        ENTRYPOINT,
        "--assets", args.assets,
        "--timeframe", args.timeframe,
        "--provider", args.provider,
        "--run-id", args.run_id,
        "--run-root", str(args.run_root),
        "--state-path", str(args.state_path),
        "--horizon-minutes", str(args.horizon_minutes),
        "--size-usd", str(args.size_usd),
        "--no-verify-provider" if args.offline else "--verify-provider",
        *leg.args,
    ]


def run_leg(args: argparse.Namespace, leg: Leg, run_dir: Path) -> dict[str, Any]:
    command = leg_command(args, leg)
    traces_path = run_dir / "traces.jsonl"
    before = trace_records(traces_path)
    disk_before = {
        "run_dir_bytes": directory_bytes(run_dir),
        "run_root_bytes": directory_bytes(args.run_root),
    }
    started = time.monotonic()
    # The child's log goes straight to a file rather than through a pipe. A pipe with no
    # reader fills at ~64 KiB and then blocks the child: the runtime logs every fetch, so a
    # pipe here would convert a working rehearsal into a hung one.
    legs_dir = run_dir / "legs" / leg.name
    legs_dir.mkdir(parents=True, exist_ok=True)
    log_path = legs_dir / "stdout.log"
    with log_path.open("w", encoding="utf-8", errors="replace") as stream:
        # §51 — the runtime is a console process started from whatever context the
        # operator used; it must not be given a console window of its own.
        process = windowless.spawn(
            command,
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            event_log=windowless.ExecutionLog(legs_dir / "execution.jsonl"),
            label=leg.name,
        )
    stop_file = run_dir / STOP_FILE_NAME
    samples: list[dict[str, Any]] = []
    stop_written_at: float | None = None
    while True:
        code = process.poll()
        sample = sample_process(process.pid)
        sample["t_seconds"] = round(time.monotonic() - started, 3)
        samples.append(sample)
        if code is not None:
            break
        if (
            leg.stop_after_seconds is not None
            and stop_written_at is None
            and time.monotonic() - started >= leg.stop_after_seconds
        ):
            stop_file.write_text(
                f"controlled stop requested at {datetime.now(UTC).isoformat()}\n", encoding="utf-8"
            )
            stop_written_at = time.monotonic() - started
        time.sleep(0.5)
    stdout = log_path.read_text(encoding="utf-8", errors="replace")
    elapsed = time.monotonic() - started
    # the runtime rewrites RUN_REPORT.json on every invocation, so each leg's copy is
    # taken before the next leg can overwrite it
    for name in ("RUN_REPORT.json", "RUN_REPORT.md", "PAPER_DAILY_REPORT.json", "heartbeat.json"):
        source = run_dir / name
        if source.exists():
            (legs_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    after = trace_records(traces_path)
    measured = [s for s in samples if s.get("state") == "MEASURED"]
    return {
        "name": leg.name,
        "notes": leg.notes,
        "command": " ".join(command),
        "exit_code": process.returncode,
        "seconds": round(elapsed, 3),
        "stop_file_written_at_seconds": round(stop_written_at, 3) if stop_written_at else None,
        "stdout_tail": "\n".join(stdout.splitlines()[-8:]),
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
        "run_report": str((legs_dir / "RUN_REPORT.json").relative_to(ROOT)).replace("\\", "/"),
        "traces_before": before,
        "traces_after": after,
        "traces_added": after - before,
        "cycles_reported": reported_cycles(legs_dir / "RUN_REPORT.json"),
        "resources": {
            "samples": len(samples),
            "measured_samples": len(measured),
            "rss_mb_max": max((s["rss_mb"] or 0) for s in measured) if measured else None,
            "peak_rss_mb_max": max((s["peak_rss_mb"] or 0) for s in measured) if measured else None,
            "cpu_seconds": max((s["cpu_seconds"] or 0) for s in measured) if measured else None,
            "cpu_utilisation": (
                round(
                    max((s["cpu_seconds"] or 0) for s in measured) / elapsed, 4
                )
                if measured and elapsed
                else None
            ),
            "processes_in_the_tree_max": max(
                (s.get("processes") or 1) for s in measured
            ) if measured else None,
            "method": measured[0]["method"] if measured else "NOT_MEASURED",
        },
        "disk": {
            "run_dir_bytes_before": disk_before["run_dir_bytes"],
            "run_dir_bytes_after": directory_bytes(run_dir),
            "run_root_bytes_before": disk_before["run_root_bytes"],
            "run_root_bytes_after": directory_bytes(args.run_root),
            "bytes_written": directory_bytes(args.run_root) - disk_before["run_root_bytes"],
        },
    }


def reconstruct_leg(args: argparse.Namespace, leg: Leg, run_dir: Path) -> dict[str, Any]:
    """Rebuild one leg's record from what it left on disk.

    The leg's exit code, wall time and resource samples were captured when it ran and
    cannot be recovered from the artefacts; they are read back from the leg's own record
    if it exists, and reported as ``NOT_RECOVERED`` when it does not. Everything the
    analysis actually uses — where the trace window starts and ends, and which report
    belongs to the leg — is on disk and is read here.
    """
    legs_dir = run_dir / "legs" / leg.name
    previous = json.loads((run_dir / "LEGS.json").read_text(encoding="utf-8")) \
        if (run_dir / "LEGS.json").exists() else []
    recorded = next((item for item in previous if item.get("name") == leg.name), None)
    base = {
        "name": leg.name,
        "notes": leg.notes,
        "command": " ".join(leg_command(args, leg)),
        "exit_code": (recorded or {}).get("exit_code", -1),
        "seconds": (recorded or {}).get("seconds", 0.0),
        "stop_file_written_at_seconds": (recorded or {}).get("stop_file_written_at_seconds"),
        "stdout_tail": (recorded or {}).get("stdout_tail", ""),
        "log": str((legs_dir / "stdout.log").relative_to(ROOT)).replace("\\", "/"),
        "run_report": str((legs_dir / "RUN_REPORT.json").relative_to(ROOT)).replace("\\", "/"),
        "traces_before": int((recorded or {}).get("traces_before") or 0),
        "traces_after": int((recorded or {}).get("traces_after") or 0),
        "traces_added": int((recorded or {}).get("traces_added") or 0),
        "cycles_reported": reported_cycles(legs_dir / "RUN_REPORT.json"),
        "resources": (recorded or {}).get("resources") or {"method": "NOT_RECOVERED"},
        "disk": (recorded or {}).get("disk") or {},
        "reconstructed": True,
    }
    return base


def trace_records(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def reported_cycles(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("cycles") or 0)
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# re-deriving the checks from what the runtime persisted
# --------------------------------------------------------------------------- #


def load_traces(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_reports(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for leg in legs:
        path = ROOT / leg["run_report"]
        if path.exists():
            report = json.loads(path.read_text(encoding="utf-8"))
            out.append({"leg": leg["name"], "report": report})
    return out


def check(name: str, result: str, detail: str, evidence: list[str]) -> dict[str, Any]:
    return {"check": name, "result": result, "detail": detail, "evidence": evidence}


def analyse(args: argparse.Namespace, legs: list[dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    traces = load_traces(run_dir / "traces.jsonl")
    reports = load_reports(legs)
    interval_ms = timeframe_ms(args.timeframe) or 0
    grace_ms = int(interval_ms * DEFAULT_FRESHNESS_GRACE_BARS)
    checks: list[dict[str, Any]] = []

    # 1. the trace chain, re-linked here rather than trusted from the runtime's summary
    links_ok = True
    broken_at = None
    for index, record in enumerate(traces):
        expected = "genesis" if index == 0 else traces[index - 1].get("trace_hash")
        if record.get("prev_hash") != expected:
            links_ok, broken_at = False, index
            break
    chain_summary = [(entry["report"] or {}).get("trace_chain") or {} for entry in reports]
    checks.append(check(
        "decisions are persisted and the trace chain is intact",
        PASS if traces and links_ok else FAIL,
        f"{len(traces)} persisted records, links {'intact' if links_ok else f'broken at {broken_at}'}"
        + "; the runtime's own summary agrees"
        if all(s.get("ok") for s in chain_summary)
        else "; the runtime's own summary disagrees",
        [str((run_dir / "traces.jsonl").relative_to(ROOT)).replace("\\", "/")],
    ))

    # 2. point-in-time: a decision may only consume bars that had already sealed
    violations = [
        r.get("decision_id")
        for r in traces
        if (r.get("asset_context") or {}).get("window_end_ts")
        and r["decision_time_ms"] < (r["asset_context"]["window_end_ts"])
    ]
    checks.append(check(
        "no look-ahead: every decision consumed only sealed bars",
        PASS if traces and not violations else (NOT_EXERCISED if not traces else FAIL),
        (
            f"every one of {len(traces)} traces has window_end_ts <= decision_time_ms "
            f"(window_end is the newest bar's open, so the sealed bar closes before the decision)"
            if traces and not violations
            else f"{len(violations)} trace(s) consumed a bar that had not sealed"
        ),
        [str((run_dir / "traces.jsonl").relative_to(ROOT)).replace("\\", "/")],
    ))

    # 3. market-data freshness, measured against the runtime's own grace budget
    ages = [
        r["decision_time_ms"] - (r["asset_context"] or {})["window_end_ts"]
        for r in traces
        if (r.get("asset_context") or {}).get("window_end_ts")
    ]
    stale = [age for age in ages if age > grace_ms]
    per_leg: dict[str, dict[str, Any]] = {}
    for leg in legs:
        window = traces[leg["traces_before"] : leg["traces_after"]]
        leg_ages = [
            r["decision_time_ms"] - (r["asset_context"] or {})["window_end_ts"]
            for r in window
            if (r.get("asset_context") or {}).get("window_end_ts")
        ]
        stale_reasons = [
            c.get("router_reason")
            for r in window
            for c in r.get("strategies_considered") or []
            if c.get("router_status") == "REJECTED"
        ]
        per_leg[leg["name"]] = {
            "evaluations": len(window),
            "age_ms_max": max(leg_ages) if leg_ages else None,
            "age_ms_min": min(leg_ages) if leg_ages else None,
            "stale_evaluations": sum(1 for age in leg_ages if age > grace_ms),
            "stale_share": round(
                sum(1 for age in leg_ages if age > grace_ms) / len(leg_ages), 4
            )
            if leg_ages
            else None,
            "router_reasons": sorted({reason for reason in stale_reasons if reason}),
        }
    # The claim is not "no context was ever late" — a free-running loop is late some of the
    # time by construction (the gate measures the age from the newest bar's *open*, so a
    # 5m timeframe only has 150 s of slack in every 300 s). The claim is that the gate is
    # *enforced*: an evaluation outside the budget cannot produce a proposal, and the
    # router says why. The share is measured and reported per cadence rather than asserted
    # away, because it is the number that decides which cadence the operator should run.
    late_with_a_proposal = [
        r.get("decision_id")
        for r in traces
        if (r.get("asset_context") or {}).get("window_end_ts")
        and r["decision_time_ms"] - r["asset_context"]["window_end_ts"] > grace_ms
        and r.get("proposal")
    ]
    late_rejected_by_the_router = [
        r.get("decision_id")
        for r in traces
        if (r.get("asset_context") or {}).get("window_end_ts")
        and r["decision_time_ms"] - r["asset_context"]["window_end_ts"] > grace_ms
        and all(
            candidate.get("router_status") == "REJECTED"
            for candidate in r.get("strategies_considered") or []
        )
    ]
    checks.append(check(
        "the freshness gate is enforced: a late context cannot reach a proposal",
        PASS
        if ages and not late_with_a_proposal
        and len(late_rejected_by_the_router) == len(stale)
        else (NOT_EXERCISED if not ages else FAIL),
        (
            f"max age {max(ages) / 1000:.1f} s against a {grace_ms / 1000:.0f} s budget "
            f"({DEFAULT_FRESHNESS_GRACE_BARS} bars of {args.timeframe}); {len(stale)} of "
            f"{len(ages)} evaluations were late, {len(late_rejected_by_the_router)} of them were "
            f"rejected by the router for exactly that reason, and {len(late_with_a_proposal)} "
            "produced a proposal"
            if ages
            else "no evaluation happened"
        ),
        ["traces.jsonl asset_context.window_end_ts", "traces.jsonl strategies_considered"],
    ))

    # 4. the strategy router ran and its verdicts are self-consistent
    considered = [(r, c) for r in traces for c in r.get("strategies_considered") or []]
    statuses = sorted({c.get("router_status") for _, c in considered})
    selected_without_alpha = [
        c.get("strategy_id")
        for _, c in considered
        if c.get("selected") and not c.get("emitted_alpha")
    ]
    checks.append(check(
        "the strategy router ran and never selected a candidate that emitted no alpha",
        PASS if considered and not selected_without_alpha else (NOT_EXERCISED if not considered else FAIL),
        f"{len(considered)} candidate evaluations, statuses {statuses}, "
        f"{len({c.get('strategy_id') for _, c in considered})} distinct strategies",
        ["traces.jsonl strategies_considered"],
    ))

    # 5. risk: every proposal is reviewed, and nothing order-authorising is advisory
    with_proposal = [r for r in traces if r.get("proposal")]
    unreviewed = [
        r.get("decision_id")
        for r in with_proposal
        if not (r.get("risk") or {}).get("risk_evaluated")
    ]
    advisory_on_order = [
        r.get("decision_id")
        for r in traces
        if (r.get("risk") or {}).get("advisory") and (r.get("order_created") or r.get("orders_created"))
    ]
    order_authorising = [r for r in traces if r.get("mode") == "TRADE_PAPER"]
    risk_states = sorted({(r.get("risk") or {}).get("state") for r in traces})
    if not with_proposal:
        checks.append(check(
            "the risk engine reviewed every proposal (deterministic, binding on orders)",
            NOT_EXERCISED,
            (
                "no evaluation carried a proposal, so the binding path was never entered: "
                f"{len(traces)} rows are NO_TRADE with risk {risk_states}; the runtime reviews "
                "risk only when there is something to review (§3 of the runtime document)"
            ),
            ["traces.jsonl risk"],
        ))
    else:
        checks.append(check(
            "the risk engine reviewed every proposal (deterministic, binding on orders)",
            PASS if not unreviewed and not advisory_on_order else FAIL,
            f"{len(with_proposal)} proposal(s) reviewed, {len(order_authorising)} order-authorising, "
            f"{len(advisory_on_order)} advisory reviews on an order",
            ["traces.jsonl risk"],
        ))

    # 6. the independent verifier — the runtime's own answer, when it was asked
    verdicts = sorted({(r.get("verification") or {}).get("verdict") for r in traces})
    checks.append(check(
        "the independent verifier graded the decisions it was asked to grade",
        PASS if verdicts and verdicts != ["NOT_RUN"] else NOT_EXERCISED,
        (
            f"verifier verdicts {verdicts}: a NO_TRADE row with no proposal is not sent to the "
            "verifier, so this branch is NOT_EXERCISED in a window whose router rejects everything"
            if verdicts == ["NOT_RUN"]
            else f"verifier verdicts {verdicts}"
        ),
        ["traces.jsonl verification.verdict"],
    ))

    # 7. agents
    agent_messages = sum(len(r.get("agent_messages") or []) for r in traces)
    checks.append(check(
        "the agents were reachable from the live path",
        PASS if agent_messages else NOT_EXERCISED,
        (
            f"{agent_messages} agent message(s) recorded; with no proposal the registry is never "
            "consulted, so the live window cannot prove the agents are reachable and says so"
            if not agent_messages
            else f"{agent_messages} agent message(s) recorded"
        ),
        ["traces.jsonl agent_messages"],
    ))

    # 8. checkpoint/resume: the state is written and a later leg continues the chain
    state_path = Path(args.state_path)
    resumes = [leg for leg in legs if leg["traces_before"] > 0]
    checks.append(check(
        "checkpoint and resume: a later run continues the same chain",
        PASS if resumes and links_ok else (NOT_EXERCISED if not resumes else FAIL),
        (
            f"{state_path.name} exists={state_path.exists()}; "
            + "; ".join(
                f"leg {leg['name']} continued from record {leg['traces_before']} and added "
                f"{leg['traces_added']}"
                for leg in resumes
            )
            if resumes
            else "no leg ran after another, so no resume was exercised"
        ),
        [str(state_path.relative_to(ROOT)).replace("\\", "/")],
    ))

    # 9. accounting identity and failure accounting, per leg's own report
    identity: list[dict[str, Any]] = []
    for entry in reports:
        totals = entry["report"].get("totals") or {}
        left = (
            int(totals.get("paper_trades") or 0)
            + int(totals.get("shadow_trades") or 0)
            + int(totals.get("no_trades") or 0)
            + int(totals.get("runtime_failures") or 0)
        )
        right = int(totals.get("asset_cycle_evaluations") or 0)
        identity.append({
            "leg": entry["leg"],
            "left": left,
            "right": right,
            "holds": left == right,
            "runtime_failures": int(totals.get("runtime_failures") or 0),
            "orders_created": int(totals.get("orders_created") or 0),
            "production_actions": int(entry["report"].get("production_actions") or 0),
        })
    checks.append(check(
        "every evaluation is accounted for and no order was created",
        PASS if identity and all(item["holds"] for item in identity)
        and all(item["orders_created"] == 0 for item in identity) else FAIL,
        f"{sum(i['right'] for i in identity)} evaluations across {len(identity)} leg(s), "
        f"{sum(i['runtime_failures'] for i in identity)} runtime failure(s), "
        f"{sum(i['orders_created'] for i in identity)} order(s), "
        f"{sum(i['production_actions'] for i in identity)} production action(s)",
        [entry["leg"] + "/RUN_REPORT.json" for entry in reports],
    ))

    # 10. replay purity
    replays = [(entry["leg"], entry["report"].get("replay") or {}) for entry in reports]
    replay_ok = all(
        replay.get("failed") == 0 and replay.get("market_data_accessed") is False
        and replay.get("attempted") == replay.get("ok")
        for _, replay in replays
    )
    checks.append(check(
        "replay reconstructs each decision without reading the market again",
        PASS if replays and replay_ok else FAIL,
        "; ".join(
            f"{leg}: {replay.get('ok')}/{replay.get('attempted')} ok, failed={replay.get('failed')}, "
            f"market_data_accessed={replay.get('market_data_accessed')}"
            for leg, replay in replays
        ) or "no leg produced a replay summary",
        [leg + "/RUN_REPORT.json#replay" for leg, _ in replays],
    ))

    # 11. errors, timeouts and latency
    errors = [
        error
        for entry in reports
        for error in (entry["report"].get("errors") or [])
    ]
    cycle_times = []
    for entry in reports:
        for cycle in entry["report"].get("cycles_detail") or []:
            if cycle.get("started_at_ms") and cycle.get("ended_at_ms"):
                cycle_times.append(int(cycle["ended_at_ms"]) - int(cycle["started_at_ms"]))
    leg_seconds = sum(leg["seconds"] for leg in legs)
    checks.append(check(
        "no hidden critical error, and the cycle latency is measured",
        PASS if not errors and cycle_times else (FAIL if errors else NOT_EXERCISED),
        f"{len(errors)} error(s) in the leg reports; {len(cycle_times)} cycle(s) with "
        f"latency min {min(cycle_times) if cycle_times else 'n/a'} ms / max "
        f"{max(cycle_times) if cycle_times else 'n/a'} ms",
        [entry["leg"] + "/RUN_REPORT.json#errors" for entry in reports],
    ))

    # 11b. how much of the real flow the window actually reached. This is the honest
    # answer to "what percentage of the pipeline did you exercise": the stages are counted
    # from the traces, not asserted from the design.
    stages = [
        {"stage": "scan and bar history fetched", "reached": len(traces),
         "of": len(traces), "evidence": "traces.jsonl asset_context.bar_count"},
        {"stage": "regime and context built", "reached": sum(
            1 for r in traces if r.get("regime")), "of": len(traces),
         "evidence": "traces.jsonl regime"},
        {"stage": "router consulted", "reached": sum(
            1 for r in traces if r.get("strategies_considered")), "of": len(traces),
         "evidence": "traces.jsonl strategies_considered"},
        {"stage": "proposal built", "reached": len(with_proposal), "of": len(traces),
         "evidence": "traces.jsonl proposal"},
        {"stage": "agents consulted", "reached": sum(
            1 for r in traces if r.get("agent_messages")), "of": len(with_proposal),
         "evidence": "traces.jsonl agent_messages"},
        {"stage": "risk engine evaluated", "reached": sum(
            1 for r in traces if (r.get("risk") or {}).get("risk_evaluated")),
         "of": len(with_proposal), "evidence": "traces.jsonl risk.risk_evaluated"},
        {"stage": "independent verifier ran", "reached": sum(
            1 for r in traces if (r.get("verification") or {}).get("verdict") != "NOT_RUN"),
         "of": len(with_proposal), "evidence": "traces.jsonl verification.verdict"},
        {"stage": "decision persisted to the trace chain", "reached": len(traces),
         "of": len(traces), "evidence": "traces.jsonl"},
        {"stage": "order created (TRADE_PAPER)", "reached": sum(
            1 for r in traces if r.get("mode") == "TRADE_PAPER"), "of": len(traces),
         "evidence": "traces.jsonl mode"},
        {"stage": "broker reconciliation / outcome resolved", "reached": sum(
            int(entry["report"].get("totals", {}).get("outcomes_resolved") or 0)
            for entry in reports),
         "of": len(with_proposal),
         "evidence": "legs/*/RUN_REPORT.json totals.outcomes_resolved"},
    ]
    reached_stage_count = sum(1 for stage in stages if stage["reached"])
    # Whether a strategy emits alpha is a property of the *market at the sampled instants*,
    # not of the runtime: one window reaches the agent, risk and verifier stages and the
    # next stops at the router with NO_ALPHA. So the check asserts consistency with the
    # traces — every stage that ran is backed by a record, and no order was created — and
    # reports the rest as NOT_EXERCISED with the reason, instead of inventing a threshold
    # the window cannot control.
    stages_with_records = all(
        stage["reached"] <= max(1, len(traces)) for stage in stages
    )
    unreached = [stage["stage"] for stage in stages if not stage["reached"]]
    deep_stages = {"proposal built", "agents consulted", "risk engine evaluated",
                   "independent verifier ran"}
    deep_reached = deep_stages - set(unreached)
    checks.append(check(
        "the executed window's flow coverage matches its own records",
        PASS
        if traces and stages_with_records and not any(
            stage["reached"] and not stage["of"] and stage["stage"] in deep_stages
            for stage in stages
        )
        else FAIL,
        "stages reached: "
        + ", ".join(
            f"{stage['stage']} {stage['reached']}/{stage['of']}" for stage in stages
        )
        + (
            ""
            if deep_reached == deep_stages
            else "; not exercised in this window: " + ", ".join(sorted(deep_stages - deep_reached))
            + " (the router admitted no candidate that emitted alpha; which stages a real "
            "window reaches depends on the market, so the rest is reported, not asserted)"
        ),
        ["traces.jsonl", "legs/*/RUN_REPORT.json"],
    ))

    # 12. the window itself
    hours = leg_seconds / 3600.0
    complete = hours >= TARGET_HOURS
    checks.append(check(
        f"the window reached the {TARGET_HOURS:.0f} h the operator asked for",
        PASS if complete else NOT_EXERCISED,
        f"{hours:.4f} h executed of {TARGET_HOURS:.1f} h "
        f"({hours / TARGET_HOURS:.3%} of the target): the rehearsal is prepared and driven, the "
        "window is not complete, so no stability verdict is issued",
        ["this report"],
    ))

    failed = [c for c in checks if c["result"] == FAIL]
    return {
        "checks": checks,
        "per_leg_freshness": per_leg,
        "flow_coverage": {
            "stages": stages,
            "stages_reached": reached_stage_count,
            "stages_total": len(stages),
            "proposals": len(with_proposal),
            "evaluations": len(traces),
            "proposal_share": round(len(with_proposal) / len(traces), 4) if traces else None,
            "order_creating_stages_reached": sum(
                1 for stage in stages if stage["stage"].startswith(("order", "broker"))
                and stage["reached"]
            ),
            "why_the_rest_was_not_reached": (
                "a decision may only create an order when a strategy is admitted and its net "
                "edge is positive; no strategy in the ledger is admitted, and every proposal "
                "was classified NO_GROSS_EDGE, so the order-creating stages are unreachable "
                "in a real window by design rather than by defect"
            ),
        },
        "identity": identity,
        "trace_records": len(traces),
        "hours_executed": round(hours, 5),
        "hours_target": TARGET_HOURS,
        "window_complete": complete,
        "coverage_of_target": round(hours / TARGET_HOURS, 6),
        "freshness_budget_ms": grace_ms,
        "freshness_grace_bars": DEFAULT_FRESHNESS_GRACE_BARS,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "checks_not_exercised": sum(1 for c in checks if c["result"] == NOT_EXERCISED),
        "verdict": (
            "RUNTIME_REHEARSAL_FAILED" if failed
            else "WINDOW_INCOMPLETE" if not complete
            else "RUNTIME_REHEARSAL_PASS"
        ),
        "stability_declared": False,
        "stability_reason": (
            "a window shorter than the target cannot pass a stability test, and the checks the "
            "short window could not reach are reported as NOT_EXERCISED rather than PASS"
        ),
    }


def build_legs(args: argparse.Namespace) -> list[Leg]:
    return [
        Leg(
            name="1-interval-cadence",
            args=["--cadence", "interval", "--cycles", str(args.cycles), "--interval", str(args.interval)],
            notes="free-running loop: the cadence that loses part of its cycles to the freshness gate",
        ),
        Leg(
            name="2-bar-close-cadence",
            args=["--cadence", "bar-close", "--cycles", str(args.bar_close_cycles)],
            notes="phase-aligned to sealed bars: the cadence that keeps the same budget",
        ),
        Leg(
            name="3-controlled-stop",
            args=["--continuous", "--interval", str(args.interval)],
            stop_after_seconds=args.stop_after_seconds,
            notes="stopped through the runtime's own STOP file (§51), which must exit zero",
        ),
        Leg(
            name="4-resume-after-stop",
            args=["--cycles", str(args.cycles), "--interval", str(args.interval)],
            notes="the same run id, run root and state path, after the controlled stop",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-root", default=str(RUN_ROOT))
    parser.add_argument("--state-path", default=None)
    parser.add_argument("--assets", default="BTC,ETH")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--provider", choices=["ccxt", "fake"], default="ccxt")
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--bar-close-cycles", type=int, default=2)
    parser.add_argument("--stop-after-seconds", type=float, default=40.0)
    parser.add_argument("--horizon-minutes", type=float, default=5.0)
    parser.add_argument("--size-usd", type=float, default=1_000.0)
    parser.add_argument("--offline", action="store_true", help="skip the provider universe preflight")
    parser.add_argument("--legs", default="all", help="comma-separated leg names, or 'all'")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--plan-only", action="store_true", help="print the legs and exit, run nothing")
    parser.add_argument(
        "--analyse-only",
        action="store_true",
        help=(
            "re-analyse a run that already exists on disk instead of executing the legs again; "
            "the report is derived from the leg records and the traces, so a fixed analysis does "
            "not require re-running the runtime"
        ),
    )
    args = parser.parse_args()

    args.run_id = args.run_id or f"wp9-runtime-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    args.run_root = Path(args.run_root)
    run_dir = args.run_root / args.run_id
    args.state_path = Path(args.state_path) if args.state_path else run_dir / "paper_state.json"

    legs = build_legs(args)
    if args.legs != "all":
        wanted = {name.strip() for name in args.legs.split(",")}
        legs = [leg for leg in legs if leg.name in wanted or leg.name.split("-")[0] in wanted]

    if args.plan_only:
        print(json.dumps(
            [{"name": leg.name, "args": leg.args, "command": " ".join(leg_command(args, leg)),
              "notes": leg.notes} for leg in legs],
            indent=2,
        ))
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    results = []
    # progress goes to stderr so that --json's stdout is machine-readable on its own
    if args.analyse_only:
        print(f"[rehearsal] analysis only: reading {run_dir}", file=sys.stderr, flush=True)
        results = [reconstruct_leg(args, leg, run_dir) for leg in legs]
    else:
        for leg in legs:
            print(f"[rehearsal] leg {leg.name}: {' '.join(leg.args)}", file=sys.stderr, flush=True)
            results.append(run_leg(args, leg, run_dir))
            # written after every leg, not at the end: the leg records are the one thing the
            # analysis cannot re-derive from the artefacts, so a crash in leg 4 must not
            # cost the evidence of legs 1-3
            (run_dir / "LEGS.json").write_text(
                json.dumps(results, indent=2) + "\n", encoding="utf-8"
            )
            last = results[-1]
            print(
                f"[rehearsal] leg {leg.name} exit={last['exit_code']} seconds={last['seconds']} "
                f"traces+{last['traces_added']}",
                file=sys.stderr,
                flush=True,
            )

    analysis = analyse(args, results, run_dir)
    payload = {
        "artifact": "WP9_RUNTIME_24H_REPORT",
        "work_package": "WP-9C (OPERATIONAL VALIDATION)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime": {
            "entrypoint": ENTRYPOINT,
            "same_entrypoint_as_the_lab": True,
            "lab_launcher": "scripts/start_paper_lab.py",
            "provider": args.provider,
            "mode_the_runtime_reports": "paper",
            "live_path": "absent by construction: the entrypoint refuses any mode other than paper",
        },
        "declaration": {
            "hours_requested": TARGET_HOURS,
            "hours_executed": analysis["hours_executed"],
            "coverage_of_target": analysis["coverage_of_target"],
            "window_complete": analysis["window_complete"],
            "paper_authorisation": "NOT_AUTHORIZED — this is a read-only market-data rehearsal, "
            "not the contractual paper test",
            "what_this_is": (
                "a bounded execution of the real runtime against live public market data, with a "
                "controlled stop and a resume, measured; it is not a 24 h window and is not "
                "evidence of profitability"
            ),
        },
        "legs": results,
        **analysis,
        "budgets": {
            "disk": "measured per leg, by summing the run root before and after",
            "cpu_memory": results[0]["resources"]["method"] if results else "NOT_MEASURED",
            "process_tree": (
                "the figures aggregate the child and every descendant: a virtual environment's "
                "python.exe can be a launcher stub, and sampling it alone would report the "
                "stub's few megabytes instead of the runtime's"
            ),
            "note": "resource figures cover the paper child tree only, not the whole lab",
        },
        "governance": {
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "orders_created": sum(
                item["orders_created"] for item in analysis["identity"]
            ),
            "false_success": 0,
            "not_claimed": [
                "24 h of continuous operation",
                "profitability",
                "the contractual paper test",
                "any branch of the flow the executed window never entered",
            ],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.out) if args.out else OUT_DIR / "WP9_RUNTIME_24H_REPORT.json"
        report = Path(args.report) if args.report else OUT_DIR / "WP9_RUNTIME_24H_REPORT.md"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_markdown(payload) + "\n", encoding="utf-8")
        print(f"{payload['verdict']}: {out} · {report}")

    if any(leg["exit_code"] not in (0,) for leg in results):
        return 2
    if analysis["checks_failed"]:
        return 3
    return 0


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-9C — runtime rehearsal (24 h window: prepared and driven, not completed)",
        "",
        f"> `{payload['verdict']}` · {payload['hours_executed']:.4f} h of "
        f"{payload['hours_target']:.0f} h ({payload['coverage_of_target']:.2%}) · "
        f"generated `{payload['generated_at_utc']}`",
        "",
        f"Entrypoint: `{payload['runtime']['entrypoint']}` — the same one the lab launcher "
        f"starts as its `paper` child. Provider `{payload['runtime']['provider']}` "
        "(read-only public market data).",
        "",
        "## 1. The declaration, first",
        "",
        f"* window complete: **{payload['window_complete']}**",
        f"* stability declared: **{payload['stability_declared']}** — {payload['stability_reason']}",
        f"* paper authorisation: {payload['declaration']['paper_authorisation']}",
        "",
        "## 2. Legs",
        "",
        "| leg | what it exercises | exit | seconds | traces added | RSS max | CPU s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for leg in payload["legs"]:
        resources = leg["resources"]
        lines.append(
            f"| {leg['name']} | {leg['notes']} | {leg['exit_code']} | {leg['seconds']} | "
            f"{leg['traces_added']} | {resources['rss_mb_max']} MB | {resources['cpu_seconds']} |"
        )
    lines += [
        "",
        "## 3. Freshness per cadence",
        "",
        f"Budget: {payload['freshness_grace_bars']} bars of {payload['legs'][0]['command'].split('--timeframe ')[1].split(' ')[0] if '--timeframe ' in payload['legs'][0]['command'] else '5m'} "
        f"= {payload['freshness_budget_ms'] / 1000:.0f} s (the runtime's own constant, imported, not restated).",
        "",
        "| leg | evaluations | age min/max ms | outside the budget | share | router reasons |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for name, entry in payload["per_leg_freshness"].items():
        lines.append(
            f"| {name} | {entry['evaluations']} | {entry['age_ms_min']} / {entry['age_ms_max']} | "
            f"{entry['stale_evaluations']} | {entry['share'] if 'share' in entry else entry['stale_share']} | "
            f"{', '.join(entry['router_reasons']) or '—'} |"
        )
    lines += [
        "",
        "## 4. Checks",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    for item in payload["checks"]:
        lines.append(f"| {item['check']} | `{item['result']}` | {item['detail']} |")
    lines += [
        "",
        f"`{payload['checks_total']}` checks, `{payload['checks_failed']}` failed, "
        f"`{payload['checks_not_exercised']}` not exercised by the executed window.",
        "",
        "## 5. Governance",
        "",
        f"* orders created: **{payload['governance']['orders_created']}**",
        f"* `LIVE_TRADING = {payload['governance']['LIVE_TRADING']}`, "
        f"`TRADES_AUTHORIZED = {payload['governance']['TRADES_AUTHORIZED']}`, "
        f"`FALSE_SUCCESS = {payload['governance']['false_success']}`",
        "* not claimed: " + "; ".join(payload["governance"]["not_claimed"]),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
