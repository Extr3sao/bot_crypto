"""Independent check of RUN_REPORT.json against the files it describes.

    uv run python scripts/rfc_paper_008_verify.py \\
        --report docs/agentic/paper_rfc008/RUN_REPORT.json \\
        --dashboard-url http://127.0.0.1:8971

BUILDER != VERIFIER. This script imports nothing from ``trading_bot`` and does
not call the report generator: it recounts the JSONL streams, recomputes the
evidence hashes, re-reads the dashboard over HTTP and compares every claim.

It fails when the report:

* overstates a metric (a count that the files do not contain);
* hides a blocker behind zero (PAPER rows, fills, admission, analysis coverage);
* declares a 24 h window when the observed uptime is shorter;
* points at a verifier that did not pass, or at a file outside its run;
* carries a stale hash, or lists a file that does not exist.

A missing measurement (``null``) is accepted only together with a stated
limitation; ``0`` where the files hold no evidence is a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "rfc-paper-008-run-report-v1"
VERIFY_SCHEMA = "rfc-paper-008-verify-v1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    if not path.exists():
        return rows, 0
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


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def http(url: str) -> tuple[int | None, bytes, float]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status, response.read(), (time.monotonic() - started) * 1000.0
    except urllib.error.HTTPError as error:
        return error.code, b"", (time.monotonic() - started) * 1000.0
    except OSError:
        return None, b"", (time.monotonic() - started) * 1000.0


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.counts: dict[str, Any] = {}

    def check(self, name: str, ok: bool, detail: str) -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(row["ok"] for row in self.checks)


def verify_report(report_path: Path, dashboard_url: str | None, out: Path) -> Report:
    result = Report()
    report = read_json(report_path)
    result.check("report.present", bool(report), f"read {report_path}")
    result.check(
        "report.schema", report.get("schema_version") == SCHEMA, str(report.get("schema_version"))
    )
    run_dir = Path(str(report.get("run_dir") or ""))
    result.check("report.run_dir", run_dir.is_dir(), str(run_dir))
    if not run_dir.is_dir():
        return result

    signals, signal_bad = read_jsonl(run_dir / "signals.jsonl")
    traces, trace_bad = read_jsonl(run_dir / "traces.jsonl")
    analysis, analysis_bad = read_jsonl(run_dir / "analysis.jsonl")
    outcomes, outcome_bad = read_jsonl(run_dir / "outcomes.jsonl")
    heartbeats, heartbeat_bad = read_jsonl(run_dir / "heartbeat.jsonl")
    paper_run = read_json(run_dir / "PAPER_RUN.json")
    verify_doc = read_json(run_dir / "SIGNAL_VERIFY.json")
    result.counts.update(
        {
            "signals": len(signals),
            "traces": len(traces),
            "analysis": len(analysis),
            "outcomes": len(outcomes),
            "heartbeats": len(heartbeats),
            "malformed": signal_bad + trace_bad + analysis_bad + outcome_bad + heartbeat_bad,
        }
    )
    result.check(
        "files.parse",
        signal_bad + trace_bad + analysis_bad + outcome_bad + heartbeat_bad == 0,
        f"{signal_bad + trace_bad + analysis_bad + outcome_bad + heartbeat_bad} malformed line(s)",
    )

    result.check(
        "report.signal_rows", report.get("signal_rows") == len(signals),
        f"report={report.get('signal_rows')} files={len(signals)}",
    )
    result.check(
        "report.trace_rows", report.get("trace_rows") == len(traces),
        f"report={report.get('trace_rows')} files={len(traces)}",
    )
    result.check(
        "report.cycle_count", report.get("cycle_count") == len(heartbeats),
        f"report={report.get('cycle_count')} files={len(heartbeats)}",
    )

    stages: dict[str, dict[str, int]] = {}
    for row in signals:
        stage = str(row.get("stage") or "UNKNOWN")
        kind = str(row.get("kind") or "UNKNOWN")
        stages.setdefault(stage, {})
        stages[stage][kind] = stages[stage].get(kind, 0) + 1
    result.check(
        "report.stage_counts", report.get("signal_counts_by_kind_and_stage") == stages,
        json.dumps(stages, sort_keys=True),
    )

    paper_rows = sum(1 for row in signals if row.get("stage") == "PAPER")
    result.check(
        "report.paper_orders", report.get("paper_orders") == paper_rows,
        f"report={report.get('paper_orders')} files={paper_rows}",
    )
    shadow = sum(1 for row in outcomes if row.get("mode") == "SHADOW_TRADE")
    fills = sum(1 for row in outcomes if row.get("mode") == "TRADE_PAPER")
    result.check(
        "report.shadow_outcomes", report.get("shadow_outcomes") == shadow,
        f"report={report.get('shadow_outcomes')} files={shadow}",
    )
    result.check(
        "report.paper_fills", report.get("paper_fills") == fills,
        f"report={report.get('paper_fills')} files={fills}",
    )
    admitted = list(paper_run.get("paper_candidates") or [])
    result.check(
        "report.admission_eligible", report.get("admission_eligible") == len(admitted),
        f"report={report.get('admission_eligible')} descriptor={len(admitted)}",
    )
    if paper_rows == 0:
        result.check(
            "report.no_order_without_admission",
            len(admitted) == 0 and report.get("paper_orders") == 0,
            f"admitted={len(admitted)} paper_rows={paper_rows}",
        )

    ids = [str(row.get("signal_id")) for row in signals]
    duplicates = len(ids) - len(set(ids))
    result.check(
        "report.duplicate_count", report.get("duplicate_count") == duplicates,
        f"report={report.get('duplicate_count')} files={duplicates}",
    )
    decision_times = sorted(int(row.get("decision_time_ms") or 0) for row in signals if row.get("decision_time_ms"))
    gaps = [(b - a) / 1000.0 for a, b in zip(decision_times, decision_times[1:])]
    expected_gap = round(max(gaps), 3) if gaps else None
    result.check(
        "report.max_gap", report.get("max_gap_seconds") == expected_gap,
        f"report={report.get('max_gap_seconds')} files={expected_gap}",
    )

    latest: dict[str, dict[str, Any]] = {}
    for row in analysis:
        if row.get("signal_id"):
            latest[str(row["signal_id"])] = row
    statuses = dict(Counter(str(row.get("status")) for row in latest.values()))
    result.check(
        "report.analysis_counts", report.get("analysis_status_counts") == statuses,
        json.dumps(statuses, sort_keys=True),
    )
    uncovered = max(0, len(signals) - len(latest))
    result.counts["analysis_uncovered"] = uncovered

    stored = report.get("evidence_sha256") or {}
    stale: list[str] = []
    for name, digest in stored.items():
        candidates = [
            run_dir / name,
            run_dir.parent.parent / "paper-lab" / run_dir.name / name,
        ]
        path = next((item for item in candidates if item.exists()), None)
        if path is None or sha256(path) != digest:
            stale.append(name)
    result.check("report.evidence_hashes", not stale, f"stale/missing: {stale}")
    result.check(
        "report.evidence_complete",
        {"signals.jsonl", "traces.jsonl", "PAPER_RUN.json"} <= set(stored),
        f"{len(stored)} file(s) hashed",
    )

    verifier_ok = verify_doc.get("ok") is True
    result.check("report.verifier_passed", verifier_ok, f"SIGNAL_VERIFY.ok={verify_doc.get('ok')}")
    result.check(
        "report.verifier_result_matches",
        report.get("verifier_result") == verify_doc.get("ok"),
        f"report={report.get('verifier_result')} file={verify_doc.get('ok')}",
    )
    verifier_path = report.get("verifier_report")
    if verifier_path:
        result.check(
            "report.verifier_path_is_inside_run",
            Path(verifier_path).resolve().is_relative_to(run_dir.resolve()),
            verifier_path,
        )

    provenance_ok = (
        paper_run.get("signal_source") == "REAL"
        and paper_run.get("market_data") == "MAINNET"
        and paper_run.get("market_data_sandbox") is False
        and paper_run.get("provider") not in (None, "fake")
    )
    result.check(
        "report.real_provenance",
        provenance_ok,
        f"{paper_run.get('provider')} {paper_run.get('market_data')} {paper_run.get('signal_source')}",
    )
    result.check(
        "report.signal_source_honest",
        all(row.get("source") == "REAL" for row in signals) if signals else False,
        json.dumps(dict(Counter(str(row.get("source")) for row in signals))),
    )

    uptime = report.get("observed_uptime_seconds")
    limitations = " ".join(str(item) for item in report.get("limitations") or [])
    long_enough = isinstance(uptime, (int, float)) and uptime >= 86_400
    result.check(
        "report.duration_honest",
        long_enough or "24H_NOT_VERIFIED" in limitations,
        f"uptime={uptime} limitations_mention_24h={'24H_NOT_VERIFIED' in limitations}",
    )
    result.check(
        "report.uptime_is_a_measurement",
        isinstance(uptime, (int, float)) and float(uptime) > 0,
        f"{uptime}",
    )

    blockers = list(report.get("blockers") or [])
    if len(admitted) == 0:
        result.check(
            "report.blocker_admission",
            any("ADMISSION" in str(item) for item in blockers),
            json.dumps(blockers),
        )
    if statuses.get("NOT_CONFIGURED") and not statuses.get("ANALYZED"):
        result.check(
            "report.blocker_ai",
            any("AI" in str(item) for item in blockers),
            json.dumps(blockers),
        )

    if dashboard_url:
        base = dashboard_url.rstrip("/")
        checks: dict[str, Any] = {}
        for path in ("/healthz", "/api/status", "/api/signals", "/api/analysis", "/"):
            code, body, elapsed = http(f"{base}{path}")
            checks[path] = {"http": code, "bytes": len(body), "ms": round(elapsed, 1)}
        result.check(
            "dashboard.gets",
            all(checks[path]["http"] == 200 for path in checks),
            json.dumps(checks, sort_keys=True),
        )
        try:
            request = urllib.request.Request(f"{base}/api/signals", data=b"{}", method="POST")
            with urllib.request.urlopen(request, timeout=20) as response:
                post = response.status
        except urllib.error.HTTPError as error:
            post = error.code
        except OSError:
            post = None
        result.check("dashboard.refuses_mutation", post == 405, f"POST={post}")
        code, body, _ = http(f"{base}/api/analysis")
        payload = {}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        result.check(
            "dashboard.analysis_has_no_authority",
            code == 200 and payload.get("authority_over_orders") is False,
            f"http={code} authority={payload.get('authority_over_orders')}",
        )
        code, body, _ = http(f"{base}/api/signals")
        served = {}
        try:
            served = json.loads(body)
        except ValueError:
            served = {}
        result.check(
            "dashboard.serves_the_run",
            served.get("run_id") == run_dir.name,
            f"dashboard={served.get('run_id')} run={run_dir.name}",
        )
        result.check(
            "dashboard.signal_total_matches",
            (served.get("summary") or {}).get("events") in (None, len(signals)),
            f"dashboard={(served.get('summary') or {}).get('events')} files={len(signals)}",
        )
        result.check(
            "dashboard.analysis_coverage_matches",
            (served.get("analysis") or {}).get("covered") in (None, len(latest)),
            f"signals payload analysis={served.get('analysis')}",
        )
    else:
        result.check(
            "dashboard.verified",
            False,
            "no --dashboard-url: the HTTP surface was not checked, so this is not a pass",
        )

    result.check(
        "report.false_success",
        report.get("false_success") == 0 and result.ok,
        f"report.false_success={report.get('false_success')}",
    )
    payload = {
        "schema_version": VERIFY_SCHEMA,
        "generated_at_ms": int(time.time() * 1000),
        "report": str(report_path),
        "run_id": report.get("run_id"),
        "ok": result.ok,
        "checks": result.checks,
        "failed": [row["name"] for row in result.checks if not row["ok"]],
        "counts": result.counts,
        "verifier_imports_producer": False,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[rfc008-verify] {payload['run_id']} :: {'PASS' if payload['ok'] else 'FAIL'}")
    for check in result.checks:
        print(f"  [{'ok ' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="docs/agentic/paper_rfc008/RUN_REPORT.json")
    parser.add_argument("--dashboard-url", default=None)
    parser.add_argument(
        "--out", default="docs/agentic/paper_rfc008/VERIFY_RUN_REPORT.json"
    )
    args = parser.parse_args(argv)
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    result = verify_report(report_path, args.dashboard_url, out)
    print(f"[rfc008-verify] report: {out}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
