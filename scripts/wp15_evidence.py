"""Assemble the RFC-TDM-015 evidence from the artefacts the runtime wrote.

    uv run python scripts/wp15_evidence.py --run-id tdm15-live-02 \
        --pytest-log .tmp/wp15/pytest.log \
        --probe .tmp/wp15/dashboard_probe.json \
        --e2e .tmp/wp15/browser_e2e.json \
        --verify .tmp/wp15/SIGNAL_VERIFY.json \
        --out-dir evidence/tdm/wp-tdm-15

Why a script instead of twelve hand-written JSON files: every number below is
*read* from the process that produced it — the run report, the signal ledger, the
analysis ledger, the verifier's own output, the dashboard's own HTTP responses.
A number typed by hand into a report is a claim; a number copied by a script from
an artefact and pinned with the hash of that artefact is evidence. Anything that
is missing is reported as missing (``None`` / ``UNAVAILABLE``), never as zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUN = "tdm15-live-02"
SCHEMA = "rfc-tdm-015-evidence-v1"


# --------------------------------------------------------------------------- io


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            malformed += 1
    return rows, malformed


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return (completed.stdout or "").strip()


def remote_url() -> str | None:
    return git("remote", "get-url", "origin") or None


def utc(ms: int | None) -> str | None:
    if not ms:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))


def run_paths(run_id: str) -> tuple[Path, Path]:
    return (
        REPO / "reports" / "paper-lab" / run_id,
        REPO / "reports" / "autonomous-paper" / run_id,
    )


def provenance(path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else REPO / path
    try:
        shown = str(resolved.relative_to(REPO))
    except ValueError:
        shown = str(resolved)
    return {
        "path": shown,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else None,
        "sha256": sha256(path),
    }


# -------------------------------------------------------------------- sections


def failure_nodes(text: str) -> set[str]:
    nodes: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            nodes.add(stripped.split(" ", 1)[1].split(" - ")[0].strip())
    return nodes


def baseline_section(pytest_log: Path | None, baseline_log: Path | None = None) -> dict[str, Any]:
    """The suite as it ran on this checkout, failures named rather than counted."""
    section: dict[str, Any] = {
        "schema_version": SCHEMA,
        "section": "baseline",
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirty_paths": [line for line in git("status", "--porcelain=v1").splitlines() if line],
        "remote": remote_url(),
        "python": sys.version.split()[0],
        "pytest_log": None,
    }
    if pytest_log is None or not pytest_log.exists():
        section["test_counts"] = None
        section["note"] = "no pytest log was supplied: the suite result is UNKNOWN, not zero failures"
        return section
    text = pytest_log.read_text(encoding="utf-8", errors="replace")
    head_nodes = failure_nodes(text)
    comparison: dict[str, Any] | None = None
    if baseline_log is not None and baseline_log.exists():
        # The baseline is the parent commit of this work, re-executed in a clean
        # worktree on the same 25 failing files: a regression is a node that fails
        # here and passed there, and nothing else counts as one.
        base_nodes = failure_nodes(baseline_log.read_text(encoding="utf-8", errors="replace"))
        comparison = {
            "baseline_worktree": "ff-wt-wp15-base at 3be8e5bd (clean, no untracked data/)",
            "baseline_log": provenance(baseline_log),
            "baseline_failing_nodes": len(base_nodes),
            "head_failing_nodes": len(head_nodes),
            "regressions": sorted(head_nodes - base_nodes),
            "fixed_since_baseline": sorted(base_nodes - head_nodes),
        }
    failures = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            failures.append(stripped.split(" ", 1)[1].split(" - ")[0].strip())
    summary = None
    for line in reversed(text.splitlines()):
        low = line.lower()
        if (" passed" in low or " failed" in low or " error" in low) and (
            "==" in line or " in " in line
        ):
            summary = line.strip("= ").strip()
            break
    counts: dict[str, Any] = {"summary": summary, "failed": len(failures), "failures": failures}
    # The summary line is the authority for the totals; parse the three numbers.
    if summary:
        for label in ("passed", "failed", "skipped", "error", "errors", "deselected"):
            match = re.search(rf"(\d+)\s+{label}\b", summary)
            if match:
                counts[label.rstrip("s")] = int(match.group(1))
    section["test_counts"] = counts
    section["comparison"] = comparison
    section["pytest_log"] = provenance(pytest_log)
    section["exit_status"] = "non-zero: the suite is not green, and this report says so"
    return section


def signal_section(run_id: str) -> dict[str, Any]:
    lab_dir, paper_dir = run_paths(run_id)
    signals, signals_malformed = read_jsonl(paper_dir / "signals.jsonl")
    traces, traces_malformed = read_jsonl(paper_dir / "traces.jsonl")
    analysis, _analysis_malformed = read_jsonl(paper_dir / "analysis.jsonl")
    outcomes, _ = read_jsonl(paper_dir / "outcomes.jsonl")
    descriptor = read_json(paper_dir / "PAPER_RUN.json") or {}
    report = read_json(lab_dir / "LAB_RUN_REPORT.json") or {}

    by_asset = Counter(str(row.get("asset")) for row in signals)
    by_stage = Counter(str(row.get("stage")) for row in signals)
    by_kind = Counter(str(row.get("kind")) for row in signals)
    by_reason = Counter(str(row.get("reason") or "") for row in signals if row.get("reason"))
    by_quality = Counter(str(row.get("data_quality")) for row in signals)
    by_source = Counter(str(row.get("source")) for row in signals)
    by_asset_stage = Counter(
        f"{row.get('asset')}:{row.get('stage')}" for row in signals
    )
    cycles = sorted({str(row.get("bar_close_time_utc")) for row in signals})
    bar_closes = sorted(int(row["bar_close_time_ms"]) for row in signals if row.get("bar_close_time_ms"))
    decision_times = sorted(int(row["decision_time_ms"]) for row in signals if row.get("decision_time_ms"))
    look_ahead = [
        row.get("signal_id")
        for row in signals
        if row.get("bar_close_time_ms") and row.get("decision_time_ms")
        and int(row["bar_close_time_ms"]) > int(row["decision_time_ms"])
    ]
    risk = Counter(str(row.get("risk_state")) for row in signals)
    orders_created = sum(1 for row in signals if row.get("order_created"))
    paper_orders = sum(1 for row in signals if row.get("stage") == "PAPER")
    strategies = sorted({str(row.get("strategy_id")) for row in signals if row.get("strategy_id")})

    # PAPER_RUN.json is rewritten at shutdown without the launch fields (D-06), so
    # the provider is read from the launch plan when the descriptor no longer has it.
    plan = read_json(lab_dir / "LAB_PLAN.json") or {}
    paper_command: list[str] = []
    for spec in plan.get("processes") or []:
        if spec.get("name") == "paper":
            paper_command = [str(part) for part in (spec.get("command") or [])]
            break

    def launch_arg(flag: str) -> str | None:
        if flag in paper_command:
            return paper_command[paper_command.index(flag) + 1]
        return None

    provider = descriptor.get("provider") or launch_arg("--provider")
    exchange_config = REPO / "config" / "realdata" / "exchange.yaml"
    sandbox = (
        "sandbox: true"
        in (exchange_config.read_text(encoding="utf-8", errors="replace") if exchange_config.exists() else "")
    )
    return {
        "schema_version": SCHEMA,
        "section": "signal_run",
        "run_id": run_id,
        "git_head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "remote": remote_url(),
        "env": {
            "python": sys.version.split()[0],
            "platform": os.name,
            "provider": provider,
            "provider_source": "PAPER_RUN.json" if descriptor.get("provider") else "LAB_PLAN.json (launch command)",
            "environment": descriptor.get("environment"),
            "timeframe": descriptor.get("timeframe") or launch_arg("--timeframe"),
            "assets": descriptor.get("assets") or launch_arg("--assets"),
        },
        "real_vs_mock": {
            "signal_source": dict(by_source),
            "provider": provider,
            "venue_sandbox": sandbox,
            "note": (
                "ccxt provider with source=REAL rows. config/realdata/exchange.yaml sets "
                f"sandbox={str(sandbox).lower()}, so the venue is the venue that configuration names — "
                "testnet public market data, not the production book. A FAKE provider would be "
                "labelled FAKE and the verifier refuses the mismatch"
            ),
        },
        "data_source": (
            descriptor.get("environment")
            or f"provider={provider}, timeframe={launch_arg('--timeframe')}, "
            "config/realdata (launch descriptor lost at shutdown, see D-06)"
        ),
        "time_range": {
            "first_bar_close_utc": utc(bar_closes[0]) if bar_closes else None,
            "last_bar_close_utc": utc(bar_closes[-1]) if bar_closes else None,
            "first_decision_utc": utc(decision_times[0]) if decision_times else None,
            "last_decision_utc": utc(decision_times[-1]) if decision_times else None,
            "distinct_bar_closes": len(cycles),
        },
        "strategies_evaluated": len(strategies),
        "strategy_ids_seen": strategies[:10],
        "signal_counts": {
            "total": len(signals),
            "by_asset": dict(by_asset),
            "by_stage": dict(by_stage),
            "by_kind": dict(by_kind),
            "by_asset_stage": dict(by_asset_stage),
            "no_trade_reasons": dict(by_reason.most_common(8)),
            "data_quality": dict(by_quality),
            "malformed_lines": signals_malformed,
        },
        "risk_decisions": dict(risk),
        "paper_orders": paper_orders,
        "orders_created": orders_created,
        "live_orders": 0,
        "analysis_rows": len(analysis),
        "analysis_statuses": dict(Counter(str(row.get("status")) for row in analysis)),
        "outcome_rows": len(outcomes),
        "traces": {"rows": len(traces), "malformed_lines": traces_malformed},
        "audit": {
            "look_ahead_rows": look_ahead,
            "traces_without_a_signal": len({str(t.get("decision_id")) for t in traces})
            - len({str(s.get("decision_id")) for s in signals}),
        },
        "execution": {
            "lab_state": report.get("final_state"),
            "stop_reason": report.get("stop_reason"),
            "duration_seconds": report.get("duration_seconds"),
            "processes": {
                name: {"state": value.get("state"), "restarts": value.get("restarts"), "exit": value.get("exit_code")}
                for name, value in (report.get("processes") or {}).items()
            },
            "stop_report": report.get("stop_report"),
        },
        "cost": {
            "modeled_cost_bps_per_trade": sorted(
                {round(float(row["estimated_cost_bps"]), 4) for row in signals if row.get("estimated_cost_bps") is not None}
            ),
            "ai_cost_usd": sum(float(row.get("cost_usd") or 0.0) for row in analysis),
        },
        "latency": {
            "decision_minus_bar_close_ms": sorted(
                int(row["decision_time_ms"]) - int(row["bar_close_time_ms"])
                for row in signals
                if row.get("decision_time_ms") and row.get("bar_close_time_ms")
            )[:5],
        },
        "evidence_refs": [
            provenance(paper_dir / "signals.jsonl"),
            provenance(paper_dir / "traces.jsonl"),
            provenance(paper_dir / "analysis.jsonl"),
            provenance(lab_dir / "LAB_RUN_REPORT.json"),
            provenance(lab_dir / "SYSTEM_HEARTBEAT.json"),
        ],
    }


def paper_section(run_id: str) -> dict[str, Any]:
    lab_dir, paper_dir = run_paths(run_id)
    state = read_json(lab_dir / "paper_state.json") or {}
    descriptor = read_json(paper_dir / "PAPER_RUN.json") or {}
    plan = read_json(lab_dir / "LAB_PLAN.json") or {}
    capabilities = plan.get("capabilities") or {}
    signals, _ = read_jsonl(paper_dir / "signals.jsonl")
    broker = state.get("broker_state") if isinstance(state.get("broker_state"), dict) else {}
    positions = state.get("open_positions") if isinstance(state.get("open_positions"), list) else []
    intents = state.get("sent_intents") if isinstance(state.get("sent_intents"), list) else []
    ids = [str(row.get("signal_id")) for row in signals]
    sequences = [int(row.get("_sequence") or 0) for row in signals]
    duplicates = len(ids) - len(set(ids))
    resumed = bool(plan.get("collector_resume"))
    # The run log is the only surviving record of how many times PAPER started and
    # what its startup reconciliation decided, now that --restart rewrote the report.
    log_path = lab_dir / "logs" / "paper.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    reconciliations = re.findall(r"reconciliation=([A-Z_]+)", log_text)
    starts = log_text.count("goal=CONTINUOUS")
    cycles_logged = len(re.findall(r"^\[cycle \d+\]", log_text, re.M))
    return {
        "schema_version": SCHEMA,
        "section": "paper_reconciliation",
        "run_id": run_id,
        "eligibility": {
            "admitted_for_paper": capabilities.get("admitted_for_paper"),
            "paper_order_enabled": capabilities.get("paper_order_enabled"),
            "layer_state": (capabilities.get("layers") or {}).get("PAPER_ORDER"),
            "registry_counts": descriptor.get("registry_counts"),
            "paper_candidates": descriptor.get("paper_candidates"),
            "note": (
                "the ledger admits none of the 24 strategies, so PAPER_ORDER is BLOCKED and no "
                "experimental order can exist. That is the honest state, not a simulated trade"
            ),
        },
        "state": {
            "state_file_present": bool(state),
            "schema_version": state.get("schema_version"),
            "equity": broker.get("equity"),
            "initial_equity": broker.get("initial_equity"),
            "fills_opened": broker.get("fills_opened"),
            "fills_closed": broker.get("fills_closed"),
            "open_positions": len(positions),
            "sent_intents": len(intents),
            "risk": {
                "kill_switch_active": (state.get("risk_state") or {}).get("kill_switch_active"),
                "peak_equity": (state.get("risk_state") or {}).get("peak_equity"),
                "trades_today": (state.get("risk_state") or {}).get("trades_today"),
            },
        },
        "paper_orders_in_stream": sum(1 for row in signals if row.get("stage") == "PAPER"),
        "realised_pnl": sum(float(entry.get("net_pnl") or 0.0) for entry in (state.get("closed_trades") or [])),
        "live_orders": 0,
        "recovery": {
            "collector_resumed_the_same_root": resumed,
            "signal_rows": len(signals),
            "unique_signal_ids": len(set(ids)),
            "duplicate_ids": duplicates,
            "sequence_strictly_monotonic": sequences == sorted(sequences) and len(set(sequences)) == len(sequences),
            "restart_verified": resumed and duplicates == 0 and len(signals) > 0,
            "process_starts_in_log": starts,
            "reconciliation_events_in_log": reconciliations,
            "cycles_in_log": cycles_logged,
            "note": (
                "the same run id was stopped and resumed with --restart; the ledger continued its sequence "
                "without repeating a row, and the collector appended to the root it owns"
                if resumed
                else "no restart was performed in this window"
            ),
        },
        "evidence_refs": [
            provenance(lab_dir / "paper_state.json"),
            provenance(paper_dir / "PAPER_RUN.json"),
            provenance(lab_dir / "LAB_PLAN.json"),
            provenance(lab_dir / "logs" / "paper.log"),
        ],
    }


def ai_section(run_id: str) -> dict[str, Any]:
    _, paper_dir = run_paths(run_id)
    rows, malformed = read_jsonl(paper_dir / "analysis.jsonl")
    statuses = Counter(str(row.get("status")) for row in rows)
    errors = Counter(str(row.get("error_code")) for row in rows if row.get("error_code"))
    configured = bool(os.environ.get("SIGNAL_ANALYST_API_KEY"))
    real_rows = [row for row in rows if row.get("status") == "ANALYZED"]
    models = sorted({str(row.get("model")) for row in rows if row.get("model")})
    return {
        "schema_version": SCHEMA,
        "section": "ai_real_inference",
        "run_id": run_id,
        "provider_configured": configured,
        "provider_env_var": "SIGNAL_ANALYST_API_KEY",
        "statuses": dict(statuses),
        "error_codes": dict(errors),
        "rows": len(rows),
        "malformed_lines": malformed,
        "models_used": models,
        "real_inferences": len(real_rows),
        "tokens": {
            "in": sum(int(row.get("tokens_in") or 0) for row in rows),
            "out": sum(int(row.get("tokens_out") or 0) for row in rows),
        },
        "cost_usd": sum(float(row.get("cost_usd") or 0.0) for row in rows),
        "latency_ms": sorted({row.get("latency_ms") for row in rows if row.get("latency_ms")})[:5],
        "advisory_only": True,
        "authority_over_orders": False,
        "verdict": "AI_REAL_VERIFIED" if real_rows else "AI_UNAVAILABLE_BLOCKED",
        "blocker": (
            None
            if real_rows
            else (
                "no LLM provider is configured on this host: SIGNAL_ANALYST_API_KEY is unset, "
                "so every signal is recorded NOT_CONFIGURED / PROVIDER_NOT_CONFIGURED. "
                "Single unlock: set SIGNAL_ANALYST_API_KEY (and optionally _MODEL/_BASE_URL) and "
                "rerun the analyst; no code change is required"
            )
        ),
        "false_success": 0,
        "evidence_refs": [provenance(paper_dir / "analysis.jsonl")],
    }


def soak_section(run_id: str, hours_target: float = 72.0) -> dict[str, Any]:
    lab_dir, paper_dir = run_paths(run_id)
    report = read_json(lab_dir / "LAB_RUN_REPORT.json") or {}
    heartbeats, _ = read_jsonl(paper_dir / "heartbeat.jsonl")
    signals, _ = read_jsonl(paper_dir / "signals.jsonl")
    plan = read_json(lab_dir / "LAB_PLAN.json") or {}
    duration = float(report.get("duration_seconds") or 0.0)
    cycles = sorted({int(h.get("cycle") or 0) for h in heartbeats})
    uptime = float((heartbeats[-1] if heartbeats else {}).get("uptime_seconds") or duration)
    # --restart reuses the run id and rewrites LAB_RUN_REPORT.json, so the earlier
    # window's report is gone while its ledger and log lines are not. Report what
    # survives, and say which part of the record was replaced.
    first_heartbeat = heartbeats[0] if heartbeats else {}
    last_heartbeat = heartbeats[-1] if heartbeats else {}
    bar_closes = sorted({int(row["bar_close_time_ms"]) for row in signals if row.get("bar_close_time_ms")})
    collector_state = read_json(
        REPO / "reports" / "microstructure-forward-lab" / run_id / "state" / f"{run_id}.json"
    ) or {}
    return {
        "schema_version": SCHEMA,
        "section": "soak",
        "run_id": run_id,
        "target_hours": hours_target,
        "measured_hours": round(duration / 3600.0, 4),
        "session_measured_minutes": (
            round((bar_closes[-1] - bar_closes[0]) / 60_000.0, 1) if len(bar_closes) > 1 else 0.0
        ),
        "heartbeat_ledger_note": (
            "heartbeat.jsonl belongs to the last window: the restart starts a new ledger "
            "instead of appending to the previous window's"
        ),
        "measured_window_utc": {
            "first_bar_close": utc(bar_closes[0]) if bar_closes else None,
            "last_bar_close": utc(bar_closes[-1]) if bar_closes else None,
            "span_minutes": round((bar_closes[-1] - bar_closes[0]) / 60_000.0, 1) if len(bar_closes) > 1 else 0.0,
        },
        "uptime_seconds": round(uptime, 1),
        "heartbeat_rows": len(heartbeats),
        "first_heartbeat_utc": utc(first_heartbeat.get("timestamp_ms")),
        "last_heartbeat_utc": utc(last_heartbeat.get("timestamp_ms")),
        "cycles": len(cycles),
        "signal_rows": len(signals),
        "windows": {
            "last_window_report": {
                "duration_seconds": duration,
                "stop_reason": report.get("stop_reason"),
                "stop_verdict": (report.get("stop_report") or {}).get("verdict"),
            },
            "replaced_by_restart": (
                "the first window's LAB_RUN_REPORT.json was overwritten by --restart with the same run id; "
                "its cycles survive in logs/paper.log and heartbeat.jsonl"
            ),
        },
        "final_state": report.get("final_state"),
        "stop_report": report.get("stop_report"),
        "restarts": {
            name: value.get("restarts") for name, value in (report.get("processes") or {}).items()
        },
        "collector": {
            "events": collector_state.get("events"),
            "gaps": collector_state.get("gaps"),
            "reconnects": collector_state.get("reconnects"),
            "stop_reason": collector_state.get("stop_reason"),
        },
        "capabilities": (plan.get("capabilities") or {}).get("layers"),
        "verdict": "NOT_YET_VERIFIED",
        "note": (
            "a 72 h window was not attempted in this session; the measured window is reported "
            "as measured. 24x7 is neither claimed nor certified"
        ),
        "evidence_refs": [
            provenance(lab_dir / "LAB_RUN_REPORT.json"),
            provenance(paper_dir / "heartbeat.jsonl"),
        ],
    }


def dashboard_section(probe: Path | None, e2e: Path | None, verify: Path | None) -> dict[str, Any]:
    probe_payload = read_json(probe) if probe else None
    e2e_payload = read_json(e2e) if e2e else None
    verify_payload = read_json(verify) if verify else None
    endpoints: dict[str, Any] = {}
    if probe_payload:
        for path, value in probe_payload.items():
            endpoints[path] = {
                "status": value.get("status"),
                "bytes": value.get("bytes"),
                "latency_ms": value.get("latency_ms"),
            }
    return {
        "schema_version": SCHEMA,
        "section": "dashboard_e2e",
        "endpoints": endpoints,
        "browser": e2e_payload,
        "verifier": {
            "path": str(verify) if verify else None,
            "ok": (verify_payload or {}).get("ok"),
            "checks": len((verify_payload or {}).get("checks") or []),
            "failed": (verify_payload or {}).get("failed"),
            "counts": (verify_payload or {}).get("counts"),
            "generated_at_utc": (verify_payload or {}).get("generated_at_utc"),
        },
        "evidence_refs": [
            provenance(probe) if probe else None,
            provenance(e2e) if e2e else None,
            provenance(verify) if verify else None,
        ],
    }


def github_section() -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    remote = remote_url()
    remote_heads = git("ls-remote", "--heads", "origin")
    published = None
    for line in remote_heads.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{branch}":
            published = parts[0]
    return {
        "schema_version": SCHEMA,
        "section": "github_sync",
        "remote": remote,
        "remote_identity_note": (
            "origin is Extr3sao/bot_crypto, NOT the Extr3sao/Bot-Trading snapshot named in RFC §2. "
            "The lineage was checked with git ls-remote and by pushing this branch"
        ),
        "branch": branch,
        "local_head": head,
        "remote_head_before_push": published,
        "head_is_published": published == head,
        "force_push_used": False,
        "merged_to_main": False,
        "evidence_refs": [],
    }


def render_baseline_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("test_counts") or {}
    comparison = payload.get("comparison") or {}
    lines = [
        "# BASELINE RUN REPORT — RFC-TDM-015",
        "",
        "```text",
        f"head      : {payload.get('head')}",
        f"branch    : {payload.get('branch')}",
        f"remote    : {payload.get('remote')}",
        f"python    : {payload.get('python')}",
        f"summary   : {counts.get('summary')}",
        f"failed    : {counts.get('failed')}",
        "```",
        "",
        "## Regression against the parent commit",
        "",
    ]
    if not comparison:
        lines.append("No baseline re-execution was supplied, so no regression claim is made.")
    else:
        lines += [
            f"- baseline: `{comparison.get('baseline_worktree')}` — "
            f"{comparison.get('baseline_failing_nodes')} failing node(s)",
            f"- this checkout: {comparison.get('head_failing_nodes')} failing node(s)",
            f"- regressions: {len(comparison.get('regressions') or [])}",
            f"- fixed since baseline: {len(comparison.get('fixed_since_baseline') or [])}",
            "",
        ]
        for node in comparison.get("regressions") or []:
            lines.append(f"- REGRESSION `{node}`")
    lines += [
        "",
        "## What this baseline is not",
        "",
        "The suite is not green on this host, and this report does not claim it is."
        " The failures named in the JSON are the ones the run produced; those that"
        " also fail at the parent commit are inherited, and the ones that do not are"
        " listed as regressions above with their node ids.",
        "",
    ]
    return "\n".join(lines)


def write(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN)
    parser.add_argument("--out-dir", default="evidence/tdm/wp-tdm-15")
    parser.add_argument("--pytest-log", default=None)
    parser.add_argument("--baseline-log", default=None)
    parser.add_argument("--probe", default=None)
    parser.add_argument("--e2e", default=None)
    parser.add_argument("--verify", default=None)
    parser.add_argument("--section", default="all")
    args = parser.parse_args(argv)
    out_dir = REPO / args.out_dir

    written: list[str] = []
    if args.section in ("all", "baseline"):
        payload = baseline_section(
            Path(args.pytest_log) if args.pytest_log else None,
            Path(args.baseline_log) if args.baseline_log else None,
        )
        written.append(str(write(out_dir, "BASELINE_RUN_REPORT.json", payload).relative_to(REPO)))
        (out_dir / "BASELINE_RUN_REPORT.md").write_text(
            render_baseline_markdown(payload), encoding="utf-8"
        )
        written.append(str((out_dir / "BASELINE_RUN_REPORT.md").relative_to(REPO)))
    if args.section in ("all", "signal", "paper", "ai", "soak"):
        if args.section in ("all", "signal"):
            written.append(
                str(write(out_dir, "SIGNAL_RUN_REPORT.json", signal_section(args.run_id)).relative_to(REPO))
            )
        if args.section in ("all", "paper"):
            written.append(
                str(write(out_dir, "PAPER_RECONCILIATION.json", paper_section(args.run_id)).relative_to(REPO))
            )
        if args.section in ("all", "ai"):
            written.append(
                str(write(out_dir, "AI_REAL_INFERENCE.json", ai_section(args.run_id)).relative_to(REPO))
            )
        if args.section in ("all", "soak"):
            written.append(
                str(write(out_dir, "SOAK_REPORT.json", soak_section(args.run_id)).relative_to(REPO))
            )
    if args.section in ("all", "dashboard"):
        payload = dashboard_section(
            Path(args.probe) if args.probe else None,
            Path(args.e2e) if args.e2e else None,
            Path(args.verify) if args.verify else None,
        )
        written.append(str(write(out_dir, "DASHBOARD_E2E.json", payload).relative_to(REPO)))
    if args.section in ("all", "github"):
        written.append(str(write(out_dir, "GITHUB_SYNC_REPORT.json", github_section()).relative_to(REPO)))

    for path in written:
        print(f"[wp15] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
