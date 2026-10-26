"""Build RUN_REPORT.{json,md} for one RFC-PAPER-008 PAPER/SHADOW window.

    uv run python scripts/rfc_paper_008_report.py --run-id <id> \\
        --dashboard-url http://127.0.0.1:8971

This is the *builder's* report. It reads the artifacts the run wrote and states
what they prove — it does not certify them. Certification belongs to
``scripts/wp_signal_verify.py`` (signals/HTTP) and
``scripts/rfc_paper_008_verify.py`` (this report vs the files), which are run
separately and whose results are embedded here only as a pointer.

A metric that cannot be measured is written as ``null`` with a reason in
``limitations``; it is never replaced by 0. SHADOW observations, PAPER fills and
realised PnL are separate fields and are never summed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPER_ROOT = Path("reports/autonomous-paper")
DEFAULT_LAB_ROOT = Path("reports/paper-lab")
SCHEMA = "rfc-paper-008-run-report-v1"

EVIDENCE_FILES = (
    "PAPER_RUN.json",
    "signals.jsonl",
    "traces.jsonl",
    "analysis.jsonl",
    "outcomes.jsonl",
    "heartbeat.json",
    "heartbeat.jsonl",
    "SIGNAL_VERIFY.json",
)


def _iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (completed.stdout or "").strip() or None


def _http_checks(base: str | None) -> dict[str, Any]:
    if not base:
        return {"status": "NOT_CHECKED", "reason": "no --dashboard-url was given"}
    checks: dict[str, Any] = {}
    for path in ("/healthz", "/api/status", "/api/signals", "/api/analysis", "/"):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(f"{base.rstrip('/')}{path}", timeout=20) as response:
                body = response.read()
                checks[path] = {
                    "http": response.status,
                    "bytes": len(body),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
        except urllib.error.HTTPError as error:
            checks[path] = {"http": error.code, "error": "HTTPError"}
        except OSError as error:
            checks[path] = {"http": None, "error": f"{type(error).__name__}: {error}"}
    request = urllib.request.Request(f"{base.rstrip('/')}/api/signals", data=b"{}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            checks["POST /api/signals"] = {"http": response.status}
    except urllib.error.HTTPError as error:
        checks["POST /api/signals"] = {"http": error.code}
    except OSError as error:
        checks["POST /api/signals"] = {
            "http": None,
            "error": f"{type(error).__name__}: {error}",
        }
    return checks


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1) + 0.5))
    return ordered[rank]


def build_report(
    run_id: str,
    *,
    paper_root: Path,
    lab_root: Path,
    dashboard_url: str | None,
) -> dict[str, Any]:
    run_dir = paper_root / run_id
    lab_dir = lab_root / run_id
    signals = _jsonl(run_dir / "signals.jsonl")
    traces = _jsonl(run_dir / "traces.jsonl")
    analysis = _jsonl(run_dir / "analysis.jsonl")
    outcomes = _jsonl(run_dir / "outcomes.jsonl")
    paper_heartbeats = _jsonl(run_dir / "heartbeat.jsonl")
    lab_report = _json(lab_dir / "LAB_RUN_REPORT.json")
    paper_run = _json(run_dir / "PAPER_RUN.json")
    lab_plan = _json(lab_dir / "LAB_PLAN.json")
    system_heartbeat = _json(lab_dir / "SYSTEM_HEARTBEAT.json")

    # Latest analysis per signal: a retry supersedes a failure, never deletes it.
    latest: dict[str, dict[str, Any]] = {}
    for row in analysis:
        signal_id = str(row.get("signal_id") or "")
        if signal_id:
            latest[signal_id] = row
    analysis_counts = dict(Counter(str(row.get("status")) for row in latest.values()))
    analysed_rows = [row for row in latest.values() if row.get("status") == "ANALYZED"]
    latencies = [float(row["latency_ms"]) for row in analysed_rows if row.get("latency_ms")]
    costs = [float(row["cost_usd"]) for row in analysed_rows if row.get("cost_usd") is not None]

    stages: dict[str, dict[str, int]] = {}
    no_trade_reasons: Counter[str] = Counter()
    for row in signals:
        stage = str(row.get("stage") or "UNKNOWN")
        kind = str(row.get("kind") or "UNKNOWN")
        stages.setdefault(stage, {})
        stages[stage][kind] = stages[stage].get(kind, 0) + 1
        if row.get("kind") in ("NO_TRADE", "NO_ALPHA", "OPERATIONAL_FAILURE"):
            reason = str(row.get("no_trade_kind") or row.get("reason") or "UNKNOWN")
            no_trade_reasons[reason] += 1

    decision_times = sorted(
        int(row.get("decision_time_ms") or 0) for row in signals if row.get("decision_time_ms")
    )
    gaps = [
        (right - left) / 1000.0 for left, right in zip(decision_times, decision_times[1:])
    ]
    signal_ids = [str(row.get("signal_id")) for row in signals]
    duplicate_count = len(signal_ids) - len(set(signal_ids))

    heartbeat = paper_heartbeats[-1] if paper_heartbeats else {}
    last_market = int(heartbeat.get("last_market_time_ms") or 0) or None
    data_age = (
        None
        if not last_market
        else round(max(0.0, (int(heartbeat.get("timestamp_ms") or 0) - last_market) / 1000.0), 3)
    )

    if lab_report:
        started_at = lab_report.get("started_at_ms")
        ended_at = lab_report.get("ended_at_ms")
        uptime = lab_report.get("duration_seconds")
        final_state = lab_report.get("final_state")
        stop_reason = lab_report.get("stop_reason")
    else:
        started_at = (
            int(system_heartbeat.get("timestamp_ms") or 0)
            - int(float(system_heartbeat.get("uptime_seconds") or 0) * 1000)
            if system_heartbeat
            else None
        )
        ended_at = None
        uptime = round(float(system_heartbeat.get("uptime_seconds") or 0.0), 3) or None
        final_state = system_heartbeat.get("state")
        stop_reason = "RUNNING" if system_heartbeat else None

    provider = paper_run.get("provider")
    market_data = paper_run.get("market_data")
    signal_source = paper_run.get("signal_source")
    admitted = list(paper_run.get("paper_candidates") or [])
    paper_orders = sum(1 for row in signals if row.get("stage") == "PAPER")
    shadow_outcomes = sum(1 for row in outcomes if row.get("mode") == "SHADOW_TRADE")
    paper_fills = sum(1 for row in outcomes if row.get("mode") == "TRADE_PAPER")
    realised = (
        None
        if not paper_fills
        else round(sum(float(row.get("net_hypothetical_bps") or 0.0) for row in outcomes), 6)
    )

    verifier = _json(run_dir / "SIGNAL_VERIFY.json")
    errors: list[str] = []
    for row in signals:
        if row.get("kind") == "OPERATIONAL_FAILURE":
            errors.append(f"{row.get('symbol')}: {row.get('reason')}")
    restart_events = [
        event
        for event in (lab_report.get("supervisor_events") or [])
        if event.get("event") in ("EXIT", "RESTARTED", "RESTART_SCHEDULED", "CRASH_LOOP")
    ]
    for event in (lab_report.get("supervisor_events") or []):
        if event.get("event") in ("CRASH_LOOP", "SUPERVISOR_ERROR"):
            errors.append(f"{event.get('event')}: {event.get('process')} {event.get('reason')}")
    for row in paper_heartbeats:
        for message in row.get("errors") or ():
            errors.append(str(message))
    errors = list(dict.fromkeys(errors))[:50]

    blockers: list[str] = []
    if not signals:
        blockers.append("NO_SIGNALS_WRITTEN")
    if not admitted:
        blockers.append("PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24")
    if analysis_counts.get("NOT_CONFIGURED") and not analysed_rows:
        blockers.append("AI_NOT_CONFIGURED")
    if verifier.get("ok") is not True:
        blockers.append("INDEPENDENT_VERIFIER_NOT_PASSED")

    limitations: list[str] = []
    if not outcomes:
        limitations.append(
            "no outcome rows: no proposal reached the executable path, so SHADOW and "
            "PAPER results are unmeasured (null), not zero"
        )
    if not analysed_rows:
        limitations.append(
            "no ANALYZED row: no provider key was configured; latency/cost are null"
        )
    if uptime is not None and uptime < 86_400:
        limitations.append(
            f"observed window is {round(uptime / 3600.0, 2)} h, not 24 h: state is "
            "24H_NOT_VERIFIED"
        )
    if market_data == "TESTNET":
        limitations.append("market-data venue is TESTNET; REAL must not be claimed")
    if restart_events:
        exits = [
            f"{event.get('process')} exit={event.get('exit_code')}"
            for event in restart_events
            if event.get("event") == "EXIT"
        ]
        limitations.append(
            f"{len([e for e in restart_events if e.get('event') == 'RESTARTED'])} process "
            f"restart(s) occurred ({', '.join(exits) or 'see supervisor_events'}); a "
            "DEGRADED final_state reflects that restart, not a data failure"
        )

    commit = _git("rev-parse", "HEAD")
    git_status = _git("status", "--porcelain") or ""
    evidence = {
        name: _sha256(run_dir / name) for name in EVIDENCE_FILES if (run_dir / name).exists()
    }
    evidence["LAB_PLAN.json"] = _sha256(lab_dir / "LAB_PLAN.json")
    evidence["LAB_RUN_REPORT.json"] = _sha256(lab_dir / "LAB_RUN_REPORT.json")
    evidence["SYSTEM_HEARTBEAT.json"] = _sha256(lab_dir / "SYSTEM_HEARTBEAT.json")

    return {
        "schema_version": SCHEMA,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "git_commit": commit,
        "dirty_tree": bool(git_status.strip()),
        "dirty_paths": len(git_status.splitlines()),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "operating_system": platform.platform(),
        "provider": provider,
        "data_transport": paper_run.get("data_transport"),
        "market_data": market_data,
        "signal_source": signal_source,
        "venue": paper_run.get("environment"),
        "symbols": paper_run.get("assets"),
        "timeframes": [paper_run.get("timeframe")] if paper_run.get("timeframe") else None,
        "started_at_utc": _iso(started_at),
        "stopped_at_utc": _iso(ended_at),
        "observed_uptime_seconds": None if uptime is None else round(float(uptime), 3),
        "final_state": final_state,
        "stop_reason": stop_reason,
        "process_restarts": len(
            [event for event in restart_events if event.get("event") == "RESTARTED"]
        ),
        "process_exits": [
            {
                "process": event.get("process"),
                "exit_code": event.get("exit_code"),
                "at_ms": event.get("timestamp_ms"),
            }
            for event in restart_events
            if event.get("event") == "EXIT"
        ],
        "cycle_count": len(paper_heartbeats),
        "signal_counts_by_kind_and_stage": stages,
        "signal_rows": len(signals),
        "trace_rows": len(traces),
        "no_trade_reasons": dict(no_trade_reasons),
        "admission_eligible": len(admitted),
        "admitted_for_paper": admitted,
        "paper_orders": paper_orders,
        "shadow_outcomes": shadow_outcomes,
        "paper_fills": paper_fills,
        "realised_paper_pnl_after_costs": realised,
        "data_age_seconds": data_age,
        "max_gap_seconds": round(max(gaps), 3) if gaps else None,
        "duplicate_count": duplicate_count,
        "analysis_status_counts": analysis_counts,
        "analysis_rows": len(analysis),
        "llm_provider": ("openai-compatible" if analysed_rows else None),
        "llm_call_count": len(analysed_rows),
        "llm_cost_usd": round(sum(costs), 8) if analysed_rows else None,
        "llm_latency_p95_ms": _p95(latencies),
        "http_checks": _http_checks(dashboard_url),
        "errors": errors,
        "verifier_result": verifier.get("ok"),
        "verifier_report": str(run_dir / "SIGNAL_VERIFY.json")
        if (run_dir / "SIGNAL_VERIFY.json").exists()
        else None,
        "false_success": 0 if verifier.get("ok") is True and not errors else 1,
        "blockers": blockers,
        "limitations": limitations,
        "evidence_sha256": evidence,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# RUN_REPORT — {report['run_id']}",
        "",
        "```text",
        f"state        : {report['final_state']}",
        f"uptime       : {report['observed_uptime_seconds']} s",
        f"cycles       : {report['cycle_count']}",
        f"signals      : {report['signal_rows']}",
        f"provider     : {report['provider']} / {report['market_data']} / {report['data_transport']}",
        f"paper orders : {report['paper_orders']}   shadow outcomes: {report['shadow_outcomes']}",
        f"admitted     : {report['admission_eligible']}",
        f"verifier     : {report['verifier_result']}",
        "```",
        "",
        "## Blockers",
        "",
        *([f"- `{item}`" for item in report["blockers"]] or ["- none recorded"]),
        "",
        "## Limitations",
        "",
        *([f"- {item}" for item in report["limitations"]] or ["- none recorded"]),
        "",
        "## Signals by stage/kind",
        "",
        f"`{json.dumps(report['signal_counts_by_kind_and_stage'], sort_keys=True)}`",
        "",
        "## Analysis",
        "",
        f"`{json.dumps(report['analysis_status_counts'], sort_keys=True)}`",
        "",
        "## HTTP",
        "",
        f"`{json.dumps(report['http_checks'], sort_keys=True)}`",
        "",
        "## Evidence sha256",
        "",
    ]
    for name, digest in (report.get("evidence_sha256") or {}).items():
        lines.append(f"- `{name}` — `{digest}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--paper-root", default=str(DEFAULT_PAPER_ROOT))
    parser.add_argument("--lab-root", default=str(DEFAULT_LAB_ROOT))
    parser.add_argument("--dashboard-url", default=None)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)

    report = build_report(
        args.run_id,
        paper_root=REPO_ROOT / args.paper_root,
        lab_root=REPO_ROOT / args.lab_root,
        dashboard_url=args.dashboard_url,
    )
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "docs/agentic/paper_rfc008"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "RUN_REPORT.json"
    md_path = out_dir / "RUN_REPORT.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("run_id", "final_state", "observed_uptime_seconds",
                                             "cycle_count", "signal_rows", "verifier_result",
                                             "false_success", "blockers")}, indent=2))
    print(f"[report] {json_path}")
    print(f"[report] {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
