"""Read-only local PAPER lab dashboard (§53, §57, §58).

    uv run python scripts/paper_lab_dashboard.py            # http://127.0.0.1:8787

One page that answers "is it running, what has it done, and is the disk going to
run out", served from the artifacts the lab already writes. No database, no
build step, no JavaScript framework: the Python standard library, one HTML page,
and a JSON endpoint the page refreshes.

Two design decisions worth stating, because they are the difference between a
console and a liability:

* **It is read-only.** There is no endpoint that starts, stops, restarts, changes
  risk, admits a strategy, or touches a child process. The operator controls are
  *named on the page as commands to copy*, and the server refuses every non-GET
  request. A dashboard that can kill the lab is a second way for the lab to die.
* **It binds to loopback only.** The host is validated against the loopback
  addresses and anything else is refused at startup, so the page cannot be reached
  from the network by accident.

There is no LIVE control because there is no LIVE path: the payload reports
``live_control: false`` because every plane under it is PAPER or read-only market
data. A stale heartbeat is rendered as stale — never as healthy.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.autonomous.analysis import AnalysisStatus, AnalysisStore  # noqa: E402
from trading_bot.autonomous.observability import (  # noqa: E402
    allow_tolerant_console_output,
    build_status,
)
from trading_bot.autonomous.signals import (  # noqa: E402
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    SignalLedger,
)
from trading_bot.autonomous.supervisor import DiskThresholds  # noqa: E402

REPO = REPO_ROOT
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_PORT = 8787
SIGNALS_VIEW_SCHEMA = "paper-signals-view-v1"

#: The run directory a signal belongs to is the PAPER child's, not the lab's: the
#: lab supervises, the PAPER runtime decides. Both are named by the same run id.
SIGNAL_FILE = "signals.jsonl"
ANALYSIS_FILE = "analysis.jsonl"
OUTCOME_FILE = "outcomes.jsonl"

#: The page states the controls it deliberately does not have.
CONTROL_POLICY: dict[str, Any] = {
    "read_only": True,
    "mutating_endpoints": [],
    "start": "python scripts/start_paper_lab.py --run-id <id>",
    "status": "python scripts/paper_lab_status.py",
    "stop": "python scripts/start_paper_lab.py --stop reports/paper-lab/<id>",
    "restart": "python scripts/start_paper_lab.py --restart --run-id <id>",
    "why": (
        "the dashboard is an observability surface: a stop it could trigger is a "
        "stop a bug could trigger, and the lab must have exactly one operator path"
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lab-root", default="reports/paper-lab")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--paper-root", default="reports/autonomous-paper")
    parser.add_argument("--refresh-seconds", type=int, default=15)
    parser.add_argument("--disk-warning-gb", type=float, default=1.5)
    parser.add_argument("--disk-critical-gb", type=float, default=0.8)
    parser.add_argument("--disk-stop-gb", type=float, default=0.3)
    parser.add_argument(
        "--once",
        action="store_true",
        help="render the page to stdout and exit (used by tests and by --check)",
    )
    return parser.parse_args(argv)


def status_payload(
    args: argparse.Namespace, filters: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """The whole console state, with the signal board filtered by the request.

    ``filters`` is the parsed query string of the page request. Passing it here is
    what makes the ``filter`` button do what it says: the board is rendered by the
    server, so a submit that only changes the URL used to keep showing every row
    until the next auto-refresh replaced it (observed on 2026-10-26, 18 rows shown
    for ``?symbol=BTC/USDT`` whose own fragment had 6).
    """
    payload = build_status(
        lab_root=REPO / args.lab_root,
        run_id=args.run_id,
        paper_root=REPO / args.paper_root,
        thresholds=DiskThresholds(
            warning_bytes=int(args.disk_warning_gb * 1e9),
            critical_bytes=int(args.disk_critical_gb * 1e9),
            stop_bytes=int(args.disk_stop_gb * 1e9),
        ),
        quality_path=REPO / "docs" / "FORWARD_DATA_QUALITY_REPORT.json",
        preregistration_path=REPO / "config" / "microstructure_preregistration.json",
    )
    payload["controls"] = CONTROL_POLICY
    payload["dashboard"] = {
        "host": args.host,
        "port": args.port,
        "auto_refresh_seconds": args.refresh_seconds,
        "live_control": False,
    }
    # The page and /api/status both carry the signal view, computed once here so
    # the two cannot show different numbers in the same refresh.
    payload["signals_view"] = signals_payload(args, filters or {}, status=payload)
    payload["analysis_view"] = analysis_payload(args, {}, status=payload)
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Tolerant JSONL read: a torn line costs that line, never the page."""
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


def resolve_signal_run_dir(args: argparse.Namespace, status: dict[str, Any]) -> Path | None:
    """Which PAPER run the signal stream is read from.

    The lab's run id *is* the PAPER child's run id, so a lab run resolves directly.
    Without one, the newest PAPER run directory is used — a stream that exists but
    is no longer supervised is still worth reading, and is reported as DOWN rather
    than hidden.
    """
    run_id = status.get("run_id") or args.run_id
    paper_root = REPO / args.paper_root
    if run_id:
        candidate = paper_root / str(run_id)
        if candidate.exists():
            return candidate
    if not paper_root.exists():
        return None
    runs = [path for path in paper_root.iterdir() if path.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda path: path.stat().st_mtime)


def _outcome_index(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Each decision's realised hypothetical outcome, keyed by decision id.

    Read from the outcomes ledger rather than merged into the signal rows: the
    signal stream is append-only, and an outcome that arrives later must not
    rewrite a row that was already published.
    """
    index: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(run_dir / OUTCOME_FILE):
        decision_id = row.get("decision_id")
        if not decision_id:
            continue
        index[str(decision_id)] = {
            "mode": row.get("mode"),
            "horizon_minutes": row.get("horizon_minutes"),
            "net_hypothetical_bps": row.get("net_hypothetical_bps"),
            "gross_hypothetical_bps": row.get("gross_hypothetical_bps"),
            "outcome_time_ms": row.get("outcome_time_ms"),
            "evaluated_at_ms": row.get("created_at_ms"),
        }
    return index


def _analysis_index(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest analysis per signal (WP-SIGNAL-002 writes this file)."""
    index: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(run_dir / ANALYSIS_FILE):
        signal_id = row.get("signal_id")
        if signal_id:
            index[str(signal_id)] = row
    return index


def _signal_state(events: list[dict[str, Any]], status: dict[str, Any]) -> tuple[str, str]:
    """LIVE / STALE / DOWN / ABSENT, decided from evidence rather than optimism."""
    if not events:
        return "ABSENT", "no signal events have been written for this run yet"
    newest_ms = max(int(event.get("decision_time_ms") or 0) for event in events)
    age_seconds = max(0.0, time.time() - newest_ms / 1000.0)
    system = status.get("system") or {}
    if not system.get("running"):
        return "DOWN", "the lab is not running; the stream is the last one written"
    if system.get("heartbeat_is_stale"):
        return "STALE", "the supervisor heartbeat is stale"
    timeframe = next((e.get("timeframe") for e in reversed(events) if e.get("timeframe")), None)
    bar_seconds = 300.0
    if timeframe:
        try:
            minutes = int(str(timeframe).rstrip("m")) if str(timeframe).endswith("m") else None
            bar_seconds = float(minutes) * 60.0 if minutes else bar_seconds
        except ValueError:
            bar_seconds = 300.0
    if age_seconds > bar_seconds * 3:
        return "STALE", f"the newest signal is {age_seconds / 60:.1f} min old"
    return "LIVE", f"the newest signal is {age_seconds:.0f}s old"


def signals_payload(
    args: argparse.Namespace,
    query: dict[str, list[str]] | None = None,
    *,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only projection of the signal stream, bounded and filterable.

    Nothing here writes, takes a lock or starts anything: the page can only ever
    read what the runtime already persisted.
    """
    query = query or {}

    def one(key: str) -> str | None:
        values = query.get(key) or []
        value = values[0] if values else None
        return value or None

    def number(key: str, default: int | None = None) -> int | None:
        raw = one(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    status = status if status is not None else status_payload(args)
    run_dir = resolve_signal_run_dir(args, status)
    payload: dict[str, Any] = {
        "schema_version": SIGNALS_VIEW_SCHEMA,
        "generated_at_ms": int(time.time() * 1000),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "read_only": True,
        "run_id": None if run_dir is None else run_dir.name,
        "run_dir": None if run_dir is None else str(run_dir),
        "available": False,
        "state": "ABSENT",
        "state_reason": "no PAPER run directory was found",
        "events": [],
        "page": {"limit": DEFAULT_PAGE_LIMIT, "returned": 0, "total_matched": 0, "next_cursor": None},
        "stats": {
            "by_stage": {},
            "by_kind": {},
            "by_symbol": {},
            "by_source": {},
            "records": 0,
        },
        "outcomes": {"resolved": 0, "pending": 0, "by_mode": {}, "net_bps_mean_by_mode": {}},
        "filters": {},
        "limit_bounds": {"default": DEFAULT_PAGE_LIMIT, "max": MAX_PAGE_LIMIT},
        "retention": None,
    }
    if run_dir is None or not (run_dir / SIGNAL_FILE).exists():
        return payload

    ledger = SignalLedger(run_dir)
    page = ledger.read(
        limit=number("limit", DEFAULT_PAGE_LIMIT) or DEFAULT_PAGE_LIMIT,
        cursor=number("cursor"),
        symbol=one("symbol"),
        strategy=one("strategy"),
        timeframe=one("timeframe"),
        stage=one("stage"),
        kind=one("kind"),
    )
    outcomes = _outcome_index(run_dir)
    analyses = _analysis_index(run_dir)
    events: list[dict[str, Any]] = []
    for event in page.events:
        row = event.to_dict()
        row["outcome"] = outcomes.get(event.decision_id)
        analysis = analyses.get(event.signal_id)
        row["analysis"] = None if analysis is None else {
            "status": analysis.get("status"),
            "claim": analysis.get("claim"),
            "regime_assessment": analysis.get("regime_assessment"),
            "analysis_time_utc": analysis.get("analysis_time_utc"),
            "model": analysis.get("model"),
            "latency_ms": analysis.get("latency_ms"),
            "cost_usd": analysis.get("cost_usd"),
            "error_code": analysis.get("error_code"),
            "error_message": analysis.get("error_message"),
            "analysis_id": analysis.get("analysis_id"),
        }
        events.append(row)

    all_rows = [row for row in ledger.iter_rows()]
    by_stage: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in all_rows:
        by_stage[str(row.get("stage"))] = by_stage.get(str(row.get("stage")), 0) + 1
        by_kind[str(row.get("kind"))] = by_kind.get(str(row.get("kind")), 0) + 1
        by_symbol[str(row.get("symbol"))] = by_symbol.get(str(row.get("symbol")), 0) + 1
        by_source[str(row.get("source"))] = by_source.get(str(row.get("source")), 0) + 1

    # RFC-PAPER-008 — SHADOW observations and PAPER fills are different facts and
    # are counted separately. Only decisions the runtime actually evaluated have
    # an outcome; the rest are pending, not zero and not a loss.
    outcomes = _read_jsonl(run_dir / OUTCOME_FILE)
    signal_decisions = {
        str(row.get("decision_id")) for row in all_rows if row.get("decision_id")
    }
    by_mode: dict[str, int] = {}
    net_by_mode: dict[str, list[float]] = {}
    resolved_decisions: set[str] = set()
    for row in outcomes:
        decision_id = str(row.get("decision_id") or "")
        if not decision_id:
            continue
        resolved_decisions.add(decision_id)
        mode = str(row.get("mode") or "UNKNOWN")
        by_mode[mode] = by_mode.get(mode, 0) + 1
        net = row.get("net_hypothetical_bps")
        if net is not None:
            with contextlib.suppress(TypeError, ValueError):
                net_by_mode.setdefault(mode, []).append(float(net))
    outcome_summary = {
        "resolved": len(resolved_decisions & signal_decisions),
        "pending": len(signal_decisions - resolved_decisions),
        "by_mode": by_mode,
        "net_bps_mean_by_mode": {
            mode: round(sum(values) / len(values), 3)
            for mode, values in net_by_mode.items()
            if values
        },
        "scanned_rows": len(outcomes),
    }

    state, reason = _signal_state(all_rows, status)
    integrity = ledger.verify()
    payload.update(
        {
            "available": True,
            "state": state,
            "state_reason": reason,
            "events": events,
            "page": {
                "limit": page.limit,
                "returned": page.returned,
                "total_matched": page.total_matched,
                "next_cursor": page.next_cursor,
            },
            "stats": {
                "by_stage": by_stage,
                "by_kind": by_kind,
                "by_symbol": by_symbol,
                "by_source": by_source,
                "records": len(all_rows),
            },
            "outcomes": outcome_summary,
            "filters": page.filters,
            "integrity": {
                "ok": integrity["ok"],
                "duplicates": len(integrity["duplicates"]),
                "malformed": integrity["malformed"],
                "pit_violations": len(integrity["pit_violations"]),
            },
            "retention": integrity["retention"],
        }
    )
    return payload


def analysis_payload(
    args: argparse.Namespace,
    query: dict[str, list[str]] | None = None,
    *,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only view of the AI sidecar: coverage, cost, latency and failures.

    `NOT_CONFIGURED` is surfaced as its own state, with the count of signals it
    covers, because "the model never ran" and "the model said nothing useful" are
    different facts and collapsing them is how a missing key starts to look like
    analysis.
    """
    query = query or {}
    try:
        limit = int((query.get("limit") or [DEFAULT_PAGE_LIMIT])[0])
    except ValueError:
        limit = DEFAULT_PAGE_LIMIT
    limit = max(1, min(limit, MAX_PAGE_LIMIT))
    status = status if status is not None else status_payload(args)
    run_dir = resolve_signal_run_dir(args, status)
    payload: dict[str, Any] = {
        "schema_version": "paper-analysis-view-v1",
        "generated_at_ms": int(time.time() * 1000),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "read_only": True,
        "authority_over_orders": False,
        "run_id": None if run_dir is None else run_dir.name,
        "available": False,
        "state": "ABSENT",
        "signals_total": 0,
        "coverage": {},
        "records": [],
        "page": {"limit": limit, "returned": 0},
        "heartbeat": None,
    }
    if run_dir is None:
        return payload
    store = AnalysisStore(run_dir)
    latest = store.latest_by_signal()
    signals_total = 0
    if (run_dir / SIGNAL_FILE).exists():
        signals_total = sum(1 for _ in SignalLedger(run_dir).iter_rows())
    by_status: dict[str, int] = {}
    latencies: list[int] = []
    cost = 0.0
    for record in latest.values():
        by_status[record.status] = by_status.get(record.status, 0) + 1
        if record.latency_ms:
            latencies.append(int(record.latency_ms))
        if record.cost_usd:
            cost += float(record.cost_usd)
    analysed = by_status.get(AnalysisStatus.ANALYZED.value, 0)
    records = sorted(
        (record.to_dict() for record in latest.values()),
        key=lambda row: int(row.get("analysis_time_ms") or 0),
        reverse=True,
    )[:limit]
    heartbeat = None
    heartbeat_path = run_dir / "AI_ANALYST_HEARTBEAT.json"
    if heartbeat_path.exists():
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except ValueError:
            heartbeat = None
    configured = None if heartbeat is None else bool(heartbeat.get("provider_configured"))
    if configured is False:
        state = "NOT_CONFIGURED"
    elif not latest and not signals_total:
        state = "ABSENT"
    elif heartbeat is not None:
        age = max(0.0, time.time() - float(heartbeat.get("passed_at_ms") or 0) / 1000.0)
        state = "LIVE" if age <= 900 else "STALE"
    else:
        # No heartbeat file: the sidecar has never run against this stream. That is
        # a different fact from "it ran and found nothing", and it is said plainly.
        state = "NOT_RUN"
    p95 = None
    if latencies:
        ordered = sorted(latencies)
        # Nearest-rank p95 over what actually ran; with one sample it is that sample.
        rank = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1) + 0.5))
        p95 = ordered[rank]
    payload.update(
        {
            "available": True,
            "state": state,
            "provider_configured": configured,
            "signals_total": signals_total,
            "coverage": {
                "signals": signals_total,
                "covered": len(latest),
                "analysed": analysed,
                "not_configured": by_status.get(AnalysisStatus.NOT_CONFIGURED.value, 0),
                "failed": by_status.get(AnalysisStatus.FAILED.value, 0),
                # ``pending`` is a *record* status; ``uncovered`` is the number of
                # signals with no row at all yet. Reporting only the former read as
                # "nothing pending" while four signals had never been looked at.
                "pending": by_status.get(AnalysisStatus.PENDING.value, 0),
                "uncovered": max(0, signals_total - len(latest)),
                "by_status": by_status,
                "coverage_pct": (
                    None if not signals_total else round(100.0 * len(latest) / signals_total, 1)
                ),
            },
            "economics": {
                "cost_usd_total": round(cost, 6),
                "cost_usd_per_analysis": (
                    None if not analysed else round(cost / analysed, 6)
                ),
                "latency_ms_p95": p95,
                "latency_ms_max": max(latencies) if latencies else None,
            },
            "records": records,
            "page": {"limit": limit, "returned": len(records)},
            "heartbeat": heartbeat,
        }
    )
    return payload


def render_analysis_card(payload: dict[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    economics = payload.get("economics") or {}
    state = str(payload.get("state") or "UNKNOWN")
    tone = "ok" if state == "LIVE" else ("bad" if state == "STALE" else "warn")
    return _card(
        "IA (read-only)",
        [
            ("state", state),
            ("provider configured", payload.get("provider_configured")),
            ("coverage", f"{coverage.get('covered')}/{coverage.get('signals')} ({coverage.get('coverage_pct')}%)"),
            ("analysed", coverage.get("analysed")),
            ("not configured", coverage.get("not_configured")),
            ("failed", coverage.get("failed")),
            ("pending", coverage.get("pending")),
            ("uncovered", coverage.get("uncovered")),
            ("cost (USD)", economics.get("cost_usd_total")),
            ("latency p95 (ms)", economics.get("latency_ms_p95")),
            ("authority over orders", payload.get("authority_over_orders")),
            ("last error", (payload.get("heartbeat") or {}).get("last_error")),
        ],
        tone=tone,
    )


def _bps(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return "—"


def render_signals_section(payload: dict[str, Any]) -> str:
    """The chronological signal board: what fired, what did not, and why."""
    state = str(payload.get("state") or "ABSENT")
    tone = {"LIVE": "ok", "STALE": "warn", "DOWN": "bad", "ABSENT": "warn"}.get(state, "")
    stats = payload.get("stats") or {}
    filters = payload.get("filters") or {}
    page = payload.get("page") or {}
    rows_html: list[str] = []
    for event in payload.get("events") or []:
        analysis = event.get("analysis") or {}
        outcome = event.get("outcome") or {}
        if analysis:
            detail = analysis.get("claim") or analysis.get("error_code") or ""
            ai = (
                f"{_escape(analysis.get('status') or '—')}"
                f"<div class='small'>{_escape(detail)}</div>"
            )
        else:
            ai = "<span class='small'>no analysis</span>"
        evidence = json.dumps(event.get("evidence_refs") or [], ensure_ascii=True)
        candidates = json.dumps(event.get("candidates") or [], ensure_ascii=True)
        outcomes = json.dumps(outcome, ensure_ascii=True) if outcome else "no outcome yet"
        rows_html.append(
            "<tr>"
            f"<td class='small'>{_escape(event.get('decision_time_utc') or '—')}</td>"
            f"<td>{_escape(event.get('symbol'))}</td>"
            f"<td>{_escape(event.get('strategy_id') or '—')}"
            + (
                f"<div class='small'>{_escape(event['strategy_version'])}</div>"
                if event.get("strategy_version")
                and event.get("strategy_version") != event.get("strategy_id")
                else ""
            )
            + "</td>"
            f"<td><b>{_escape(event.get('stage'))}</b><div class='small'>{_escape(event.get('kind'))}</div></td>"
            f"<td>{_escape(event.get('direction') or '—')}</td>"
            f"<td class='num'>{_bps(event.get('gross_edge_bps'))}</td>"
            f"<td class='num'>{_bps(event.get('estimated_cost_bps'))}</td>"
            f"<td class='num'>{_bps(event.get('net_edge_bps'))}</td>"
            f"<td class='small'>{_escape(event.get('risk_state') or '—')}</td>"
            f"<td class='small'>{_escape(event.get('data_quality'))}</td>"
            f"<td class='small'>{_escape(event.get('reason'))}"
            f"<details><summary>evidence</summary><pre class='small'>{_escape(evidence)}</pre>"
            f"<pre class='small'>{_escape(candidates)}</pre>"
            f"<pre class='small'>{_escape(outcomes)}</pre></details></td>"
            f"<td class='small'>{ai}</td>"
            "</tr>"
        )
    table = (
        "<div class='table-wrap'><table>"
        "<tr><th>decision (UTC)</th><th>symbol</th><th>strategy</th><th>stage</th>"
        "<th>dir</th><th>gross bps</th><th>cost bps</th><th>net bps</th><th>risk</th>"
        "<th>data</th><th>motivo / evidencia</th><th>IA</th></tr>"
        + ("".join(rows_html) or "<tr><td colspan='12'>no signal events in this page</td></tr>")
        + "</table></div>"
    )
    stage_summary = ", ".join(
        f"{key}={value}" for key, value in sorted((stats.get("by_stage") or {}).items())
    ) or "—"
    kind_summary = ", ".join(
        f"{key}={value}" for key, value in sorted((stats.get("by_kind") or {}).items())
    ) or "—"
    source_summary = ", ".join(
        f"{key}={value}" for key, value in sorted((stats.get("by_source") or {}).items())
    ) or "—"
    options = "".join(
        f"<option value='{_escape(key)}'>{_escape(key)} ({_escape(count)} )</option>"
        for key, count in sorted((stats.get("by_stage") or {}).items())
    )
    cursor = page.get("next_cursor")
    query = "&".join(
        f"{key}={_escape(value)}"
        for key, value in {
            "symbol": filters.get("symbol"),
            "strategy": filters.get("strategy"),
            "stage": filters.get("stage"),
            "limit": page.get("limit"),
        }.items()
        if value
    )
    next_link = (
        f"<a href='/?{query}&cursor={cursor}#signals' style='color:#7fb2ff'>older →</a>"
        if cursor
        else ""
    )
    return f"""<div id="signals" class="panel">
<h2 style="font-size:13px;letter-spacing:.08em;color:#8b93a1;margin:0 0 6px">SIGNALS — {_escape(payload.get('run_id') or 'no run')}</h2>
<div class="banner {tone}">{_escape(state)} — {_escape(payload.get('state_reason'))}</div>
<div class="small">events {_escape(stats.get('records'))} · source {_escape(source_summary)} · stage {_escape(stage_summary)} · kind {_escape(kind_summary)} · showing {_escape(page.get('returned'))}/{_escape(page.get('total_matched'))} · outcomes {_escape(payload.get('outcomes'))} · retention {_escape(payload.get('retention'))} · <a href="/api/signals?limit={int(page.get('limit') or DEFAULT_PAGE_LIMIT)}" style="color:#7fb2ff">raw JSON</a> · <a href="/api/analysis" style="color:#7fb2ff">AI JSON</a> {next_link}</div>
<form method="get" action="/#signals" class="filters">
 <input name="symbol" placeholder="BTC/USDT" value="{_escape(filters.get('symbol') or '')}">
 <input name="strategy" placeholder="strategy_id" value="{_escape(filters.get('strategy') or '')}">
 <select name="stage"><option value="">all stages</option>{options}</select>
 <input name="limit" type="number" min="1" max="{MAX_PAGE_LIMIT}" value="{int(page.get('limit') or DEFAULT_PAGE_LIMIT)}">
 <button type="submit">filter</button>
 <a href="/#signals" style="color:#7fb2ff">reset</a>
</form>
{table}
</div>"""


def _card(title: str, rows: list[tuple[str, Any]], *, tone: str = "") -> str:
    body = "".join(
        f"<div class='row'><span class='k'>{_escape(label)}</span>"
        f"<span class='v'>{_escape(_format(value))}</span></div>"
        for label, value in rows
    )
    return (
        f"<section class='card {tone}'><h2>{_escape(title)}</h2>{body}</section>"
    )


def _escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ", ".join(f"{key}={val}" for key, val in value.items()) or "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)


def _tone(value: Any) -> str:
    if value is True:
        return "ok"
    if value is False:
        return "bad"
    return ""


def render_page(payload: dict[str, Any]) -> str:
    """One self-contained page. No external assets, no framing, no scripts but ours."""
    system = payload.get("system") or {}
    disk = payload.get("disk") or {}
    paper = payload.get("paper") or {}
    collector = payload.get("collector") or {}
    lab = payload.get("strategy_lab") or {}
    readiness = payload.get("readiness") or {}
    flags = payload.get("readiness_flags") or {}
    errors = payload.get("errors") or []
    controls = payload.get("controls") or {}
    dashboard = payload.get("dashboard") or {}
    signals = payload.get("signals_view") or {}
    analysis = payload.get("analysis_view") or {}

    state = system.get("state") or "UNKNOWN"
    tone = "ok" if state in ("HEALTHY",) and not system.get("heartbeat_is_stale") else (
        "bad" if state == "FAILED" else "warn"
    )
    # §6.6 — the economic verdict travels with the console, not with a footnote. A
    # page that shows live signals but not that no strategy is admitted reads as a
    # validated product; the banner says the opposite in the operator's face.
    admitted = lab.get("admitted_for_paper")
    eligibility = "" if admitted else (
        '<div class="banner bad" id="eligibility">REJECTED_ALPHA — EXPERIMENTAL PAPER, NOT VALIDATED'
        " · no strategy is admitted for paper, so this lab can create no order</div>"
    )
    cards = [
        _card(
            "SYSTEM",
            [
                ("state", state),
                ("running", system.get("running")),
                ("uptime", _duration(system.get("uptime_seconds"))),
                ("heartbeat age", _duration(system.get("heartbeat_age_seconds"))),
                ("heartbeat stale", system.get("heartbeat_is_stale")),
                ("restarts", system.get("restarts")),
                ("mode", payload.get("mode")),
                ("live control", payload.get("live_control")),
                ("run id", payload.get("run_id")),
            ],
            tone=tone,
        ),
        _card(
            "DISK",
            [
                ("free", f"{disk.get('free_gb')} GB"),
                ("level", disk.get("level")),
                ("thresholds", disk.get("thresholds")),
                (
                    "observed rate",
                    (
                        f"{disk.get('consumption_gb_per_day')} GB/day"
                        if disk.get("consumption_gb_per_day") is not None
                        else None
                    ),
                ),
                ("estimated hours left", disk.get("estimated_hours_remaining")),
                ("guidance", disk.get("guidance")),
            ],
            tone="bad" if disk.get("level") in ("STOP", "CRITICAL") else ("warn" if disk.get("level") == "WARNING" else "ok"),
        ),
        _card(
            "PAPER",
            [
                ("cycle", paper.get("cycle")),
                ("uptime", _duration(paper.get("uptime_seconds"))),
                ("assets", paper.get("assets")),
                ("timeframe", paper.get("timeframe")),
                ("strategies evaluated", paper.get("strategies_evaluated")),
                ("decisions", paper.get("decisions")),
                ("no trade", paper.get("no_trade")),
                ("no trade kinds", paper.get("no_trade_kinds")),
                ("paper trades", paper.get("paper_trades")),
                ("shadow trades", paper.get("shadow_trades")),
                ("last bar (UTC)", paper.get("last_market_time_utc")),
                ("data age", _duration(paper.get("data_age_seconds"))),
                ("last signal (UTC)", paper.get("last_decision_time_utc")),
                ("signals appended (cycle)", paper.get("signals_appended")),
                ("outcomes resolved", paper.get("outcomes_resolved")),
                ("outcomes pending", paper.get("outcomes_pending")),
                ("risk vetoes", paper.get("risk_vetoes")),
                ("runtime failures", paper.get("runtime_failures")),
                ("storage failures survived", paper.get("storage_failures")),
                ("paper candidates", paper.get("paper_candidates")),
                ("heartbeat age", _duration(paper.get("heartbeat_age_seconds"))),
            ],
            tone="bad" if paper.get("runtime_failures") else "ok",
        ),
        _card(
            "COLLECTOR",
            [
                ("available", collector.get("available")),
                ("root", collector.get("root")),
                ("events", collector.get("events")),
                ("gaps", collector.get("gaps")),
                ("reconnects", collector.get("reconnects")),
                ("resnapshots", collector.get("resnapshots")),
                ("segments", collector.get("segments_on_disk")),
                ("raw on disk", f"{collector.get('segment_gb')} GB"),
                ("state age", _duration(collector.get("state_age_seconds"))),
                ("stop reason", collector.get("stop_reason")),
                ("fatal failure", collector.get("fatal_failure")),
                ("manifest", collector.get("manifest")),
            ],
            tone="bad" if collector.get("fatal_failure") else "ok",
        ),
        _card(
            "RETENTION",
            [
                ("deletion enabled", (collector.get("retention") or {}).get("deletion_enabled")),
                ("compacted windows", (collector.get("retention") or {}).get("compacted_windows")),
                ("deleted segments", (collector.get("retention") or {}).get("deleted_segments")),
                ("freed", (collector.get("retention") or {}).get("freed_bytes")),
            ],
        ),
        _card(
            "STRATEGIES",
            [
                ("total", lab.get("strategies_total")),
                ("histogram", lab.get("status_histogram")),
                ("lifecycle", lab.get("lifecycle")),
                ("admitted for paper", lab.get("admitted_for_paper")),
                ("paper candidates", lab.get("paper_candidates")),
                ("not paper executable", lab.get("strategies_not_paper_executable")),
                ("checks ok", lab.get("all_checks_ok")),
            ],
        ),
        _card(
            "PROVENANCE",
            [
                ("provider", (payload.get("provenance") or {}).get("provider")),
                ("environment", (payload.get("provenance") or {}).get("environment")),
                ("market data", (payload.get("provenance") or {}).get("market_data")),
                ("sandbox", (payload.get("provenance") or {}).get("market_data_sandbox")),
                ("signal source", (payload.get("provenance") or {}).get("signal_source")),
                ("timeframe", (payload.get("provenance") or {}).get("timeframe")),
                ("assets", (payload.get("provenance") or {}).get("assets")),
            ],
            tone="bad" if (payload.get("provenance") or {}).get("market_data") == "TESTNET" else "ok",
        ),
        _card(
            "READINESS",
            [
                ("M-03", (readiness.get("M-03") or {}).get("verdict")),
                ("M-03 state", (readiness.get("M-03") or {}).get("state")),
                ("M-07", (readiness.get("M-07") or {}).get("verdict")),
                ("M-07 state", (readiness.get("M-07") or {}).get("state")),
                ("preregistration", readiness.get("preregistration_version")),
                ("not yet run", readiness.get("not_yet_run")),
            ],
        ),
        render_analysis_card(analysis),
        _card(
            "ERRORS",
            [("open findings", errors)] if errors else [("open findings", "none")],
            tone="bad" if errors else "ok",
        ),
    ]

    children = "".join(
        f"<tr><td>{_escape(name)}</td><td>{_escape(child.get('state'))}</td>"
        f"<td>{_escape(child.get('pid'))}</td><td>{_escape(child.get('alive'))}</td>"
        f"<td>{_escape(_duration(child.get('uptime_seconds')))}</td>"
        f"<td>{_escape(child.get('restarts'))}</td>"
        f"<td>{_escape(child.get('exit_code'))}</td>"
        f"<td class='small'>{_escape(child.get('last_error'))}</td></tr>"
        for name, child in sorted((payload.get("children") or {}).items())
    )
    flags_html = "".join(
        f"<span class='flag {_tone(value)}'>{_escape(key)}: {_escape(_format(value))}</span>"
        for key, value in flags.items()
        if isinstance(value, bool)
    )
    stop_report = payload.get("stop_report") or {}
    run_report = payload.get("run_report") or {}
    plan = payload.get("plan") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PAPER lab — {_escape(payload.get('run_id') or 'no run')}</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin:0; padding:24px; background:#0f1115; color:#e6e8eb;
       font:14px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }}
h1 {{ font-size:18px; margin:0 0 4px; }}
.sub {{ color:#8b93a1; margin-bottom:18px; }}
.banner {{ padding:8px 12px; border-radius:6px; margin-bottom:16px; display:inline-block; }}
.banner.ok {{ background:#12331f; color:#8ff0a4; }}
.banner.warn {{ background:#3a2f10; color:#ffd479; }}
.banner.bad {{ background:#3d1518; color:#ff9aa2; }}
.flags {{ margin-bottom:16px; display:flex; gap:8px; flex-wrap:wrap; }}
.flag {{ padding:4px 8px; border-radius:999px; background:#1b1f27; color:#c7cdd6; }}
.flag.ok {{ background:#12331f; color:#8ff0a4; }}
.flag.bad {{ background:#3d1518; color:#ff9aa2; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(330px, 1fr)); gap:14px; }}
.card {{ background:#161a21; border:1px solid #232833; border-radius:8px; padding:12px; }}
.card.ok {{ border-color:#1f5233; }}
.card.warn {{ border-color:#6b5a1e; }}
.card.bad {{ border-color:#6d2429; }}
.card h2 {{ font-size:13px; letter-spacing:.08em; color:#8b93a1; margin:0 0 8px; }}
.row {{ display:flex; justify-content:space-between; gap:12px; padding:2px 0; }}
.k {{ color:#8b93a1; }}
.v {{ text-align:right; word-break:break-word; max-width:60%; }}
table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #232833; }}
th {{ color:#8b93a1; font-weight:400; }}
.small {{ color:#8b93a1; }}
.panel {{ background:#12161d; border:1px solid #232833; border-radius:8px; padding:12px; margin-top:18px; }}
.filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }}
.filters input, .filters select, .filters button {{ background:#1b1f27; color:#e6e8eb; border:1px solid #2b3240; border-radius:5px; padding:5px 8px; font:inherit; }}
.filters button {{ cursor:pointer; }}
td.num {{ text-align:right; }}
details summary {{ cursor:pointer; color:#7fb2ff; }}
pre {{ white-space:pre-wrap; word-break:break-word; margin:4px 0; }}
.table-wrap {{ overflow-x:auto; }}
table {{ min-width:1100px; }}
footer {{ margin-top:20px; color:#8b93a1; }}
code {{ background:#1b1f27; padding:2px 6px; border-radius:4px; }}
</style></head>
<body>
<h1>PAPER LAB — {_escape(payload.get('run_id') or 'no run')}</h1>
<div class="sub">generated {_escape(payload.get('generated_at_iso'))} · mode {_escape(payload.get('mode'))}
 · read-only · auto-refresh {_escape(dashboard.get('auto_refresh_seconds'))}s ·
 <a href="/api/status" style="color:#7fb2ff">raw JSON</a></div>
<div class="banner {tone}">{_escape(state)}{' — STALE HEARTBEAT' if system.get('heartbeat_is_stale') else ''}</div>
{eligibility}
<div class="flags">{flags_html}</div>
<div class="grid">{''.join(cards)}</div>
<h2 style="font-size:13px;letter-spacing:.08em;color:#8b93a1;margin-top:22px">CHILD PROCESSES</h2>
<table><tr><th>process</th><th>state</th><th>pid</th><th>alive</th><th>uptime</th><th>restarts</th><th>exit</th><th>last error</th></tr>
{children or "<tr><td colspan='8'>no children reported</td></tr>"}</table>
{render_signals_section(signals)}
<div class="grid" style="margin-top:14px">
{_card("STOP REPORT", [("verdict", stop_report.get("verdict")), ("escalated", stop_report.get("escalated")), ("failed children", stop_report.get("failed_children")), ("exit codes", stop_report.get("exit_codes"))])}
{_card("RUN REPORT", [("final state", run_report.get("final_state")), ("stop reason", run_report.get("stop_reason")), ("duration", run_report.get("duration_seconds"))])}
{_card("PLAN", [("duration hours", plan.get("duration_hours")), ("retention", plan.get("retention")), ("collector resume", plan.get("collector_resume")), ("no live path", plan.get("no_live_path"))])}
{_card("CONTROLS", [("read only", controls.get("read_only")), ("mutating endpoints", controls.get("mutating_endpoints")), ("start", controls.get("start")), ("status", controls.get("status")), ("stop", controls.get("stop")), ("restart", controls.get("restart"))])}
</div>
<footer>No LIVE control is presented because no LIVE path exists: every plane is PAPER or read-only market data.
Controls are commands, not endpoints — <code>{_escape(controls.get('why'))}</code></footer>
<script>
async function refreshSignals() {{
  const target = document.getElementById('signals');
  if (!target) return;
  // The section is rendered by the server, so the browser and a refresh can
  // never disagree about how a row is formatted.
  try {{
    const response = await fetch('/signals' + window.location.search, {{cache: 'no-store'}});
    if (response.ok) target.outerHTML = await response.text();
  }} catch (error) {{ /* keep the last good table */ }}
}}
async function refresh() {{
  await refreshSignals();
  setTimeout(refresh, {int(dashboard.get('auto_refresh_seconds') or 15) * 1000});
}}
setTimeout(refresh, {int(dashboard.get('auto_refresh_seconds') or 15) * 1000});
// The cards come from /api/status. Refreshing only the table left the health
// panel frozen at the state it was born with: after a supervisor restart the
// console still advertised the previous DEGRADED state and stale uptime. A
// full reload is bounded and skipped while the operator is typing in a filter
// (the query string already survives a reload).
const STATUS_REFRESH_MS = 60000;
setInterval(function () {{
  const el = document.activeElement;
  const editing = el && ['INPUT', 'SELECT', 'TEXTAREA'].indexOf(el.tagName) >= 0;
  if (!editing && document.visibilityState === 'visible') window.location.reload();
}}, STATUS_REFRESH_MS);
</script>
</body></html>
"""


def _duration(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds < 120:
        return f"{seconds:.1f}s"
    if seconds < 7200:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def make_handler(args: argparse.Namespace) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "paper-lab-dashboard/1.0"

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=False)
            if path in ("/", "/index.html"):
                payload = status_payload(args, query)
                self._send(200, render_page(payload).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/signals":
                section = render_signals_section(signals_payload(args, query))
                self._send(200, section.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/analysis":
                payload = analysis_payload(args, query)
                self._send(
                    200,
                    (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/api/signals":
                payload = signals_payload(args, query)
                self._send(
                    200,
                    (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/api/status":
                payload = status_payload(args)
                self._send(
                    200,
                    (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/healthz":
                payload = status_payload(args)
                self._send(
                    200,
                    (
                        json.dumps(
                            {
                                "ok": True,
                                "state": (payload.get("system") or {}).get("state"),
                                "read_only": True,
                            }
                        )
                        + "\n"
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
                return
            self._send(404, b'{"error":"not found"}\n', "application/json; charset=utf-8")

        def _refuse(self) -> None:
            self._send(
                405,
                b'{"error":"this dashboard is read-only","allowed":["GET"]}\n',
                "application/json; charset=utf-8",
            )

        do_POST = _refuse
        do_PUT = _refuse
        do_DELETE = _refuse
        do_PATCH = _refuse

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[dashboard] {self.address_string()} {format % args}", file=sys.stderr)

    return Handler


def resolve_host(host: str) -> str:
    """Fail closed: only loopback, so the page cannot be reached from a network."""
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"refusing to bind {host!r}: the dashboard serves live process state and "
            "is loopback-only (use 127.0.0.1 or ::1)"
        )
    return host


def main(argv: list[str] | None = None) -> int:
    allow_tolerant_console_output()
    args = parse_args(argv)
    resolve_host(args.host)
    if args.once:
        print(render_page(status_payload(args)))
        return 0
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args))
    print(f"[dashboard] read-only PAPER lab console on http://{args.host}:{args.port}")
    print("[dashboard] no LIVE control, no mutating endpoints; Ctrl-C to exit")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[dashboard] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
