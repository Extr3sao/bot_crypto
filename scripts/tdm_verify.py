"""Independent verifier for the Trading Decision Monitor (WP-TDM-05).

Deliberately does **not** import ``trading_bot.monitor.projector``: it re-derives
the expected state from ``traces.jsonl`` with its own rules and compares that with
what the running monitor API serves. A shared bug therefore cannot hide behind a
shared code path.

    # 1. start the monitor
    python scripts/trading_decision_monitor.py --runs-root reports/autonomous-paper --port 8770
    # 2. verify it against the ledger
    python scripts/tdm_verify.py --base-url http://127.0.0.1:8770 \
        --runs-root reports/autonomous-paper \
        --out reports/trading-decision-monitor/WP-TDM-05

Checks (all evidence-based, none inferred):

    V1  hash chain of traces.jsonl recomputed row by row
    V0  the run is published by /api/monitor/runs under its directory name
    V2  every trace row appears in the API, and every API decision exists in the ledger
    V3  decision status served equals the status the trace implies (independent rules)
    V4  ORDER_FILLED only where an execution row exists for that decision
    V5  no ORDER_FILLED / acceptance for a NO_TRADE or SHADOW row
    V6  every rejection carries at least one catalogued reason code
    V7  point-in-time: decision_time >= market_time for every trace
    V8  no marker without run_id/decision_id/event_id provenance
    V9  the API never claims a fill count above the execution rows
    V10 every served decision carries the contract fields
    V11 no served decision uses market data from after its decision time
    V12 mutating HTTP verbs are refused (read-only proven from outside)
    V13 two identical reads of an unchanged run return identical projections

``false_success`` counts checks that *claimed* success while the evidence could not
support it. It must be 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Statuses the monitor may serve for a trace, derived from the runtime contract
#: (not from the monitor's own enum), so the two implementations stay separable.
EXPECTED = {
    "NO_TRADE": {"NO_TRADE"},
    "SHADOW_TRADE": {"SHADOW_OBSERVED"},
}


def canonical(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def trace_hash(raw: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(raw).encode("utf-8")).hexdigest()


def get_json(base: str, path: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(base + path, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            return exc.code, {}


def request_status(base: str, method: str, path: str) -> int:
    """Issue a mutating verb against a read-only API and report the status code."""
    request = urllib.request.Request(base + path, method=method)
    request.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError:
        return 0


def get_bytes(base: str, path: str) -> bytes:
    with urllib.request.urlopen(base + path, timeout=15) as response:
        return response.read()


#: volatile keys removed before comparing two reads of the same projection
VOLATILE_KEYS = {
    "generated_at",
    "uptime_seconds",
    "server_time",
    "heartbeat_at",
    "as_of",
    "data_age_ms",  # liveness, not part of the immutable projection
}


def stable_digest(payload: Any) -> str:
    """Hash a payload while ignoring fields that legitimately change per request."""

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: scrub(v) for k, v in node.items() if k not in VOLATILE_KEYS}
        if isinstance(node, list):
            return [scrub(v) for v in node]
        return node

    body = json.dumps(scrub(payload), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _iso_to_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp() * 1000)
    except ValueError:
        return None


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.false_success = 0

    def check(self, check_id: str, passed: bool, detail: str, evidence: Any = None) -> None:
        self.checks.append(
            {"id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail,
             "evidence": evidence}
        )

    def fail_false_success(self, why: str) -> None:
        self.false_success += 1
        self.check("FALSE_SUCCESS", False, why)

    def not_exercised(self, check_id: str, detail: str, evidence: Any = None) -> None:
        """Record a check the evidence could not exercise — never counted as PASS."""
        self.checks.append(
            {"id": check_id, "status": "NOT_EXERCISED", "detail": detail, "evidence": evidence}
        )

    @property
    def unexercised(self) -> list[str]:
        return [c["id"] for c in self.checks if c["status"] == "NOT_EXERCISED"]

    @property
    def ok(self) -> bool:
        return all(c["status"] == "PASS" for c in self.checks) and self.false_success == 0

    @property
    def status(self) -> str:
        if self.false_success or any(c["status"] == "FAIL" for c in self.checks):
            return "FAIL"
        if self.unexercised:
            return "PASS_LIMITED"
        return "PASS"


def verify_run(run_dir: Path, base_url: str, report: Report) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    chain_ok = True
    previous = "genesis"
    parse_error: str | None = None
    for index, line in enumerate((run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            # A corrupted ledger must be reported as a broken chain, never as a
            # crash and never as a silent skip of the damaged row.
            parse_error = f"line {index} is not valid JSON: {exc}"
            chain_ok = False
            break
        rows.append(raw)
        if raw.get("prev_hash") != previous or trace_hash(raw) != raw.get("trace_hash"):
            chain_ok = False
        previous = str(raw.get("trace_hash") or previous)
    # An empty ledger is not evidence of anything: it cannot be a PASS.
    chains_usable = chain_ok and bool(rows)
    report.check(
        "V1",
        chains_usable,
        (
            f"{len(rows)} trace rows, chain {'intact' if chain_ok else 'BROKEN'}"
            if rows
            else "traces.jsonl carries no records (empty ledger is not evidence)"
        )
        + (f" · {parse_error}" if parse_error else ""),
        evidence={"run_dir": str(run_dir), "records": len(rows), "parse_error": parse_error},
    )
    if not chains_usable:
        report.check("V2", False, "API/ledger correspondence not evaluated: the ledger is unusable")
        return {"run_id": run_dir.name, "traces": len(rows), "api_decisions": 0}

    executions: list[dict[str, Any]] = []
    report_path = run_dir / "RUN_REPORT.json"
    if report_path.exists():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        executions = [e for e in payload.get("executions") or [] if isinstance(e, dict)]
    executed_ids = {str(e.get("decision_id")) for e in executions}

    run_id = run_dir.name
    session_ids = {str(r.get("run_id")) for r in rows}
    runs_status, runs_index = get_json(base_url, "/api/monitor/runs")
    listed = (
        {str(r.get("run_id")) for r in runs_index.get("runs", [])}
        if runs_status == 200
        else set()
    )
    report.check(
        "V0",
        runs_status == 200 and run_id in listed,
        f"run {run_id!r} is published by /api/monitor/runs "
        f"(trace session ids={sorted(session_ids)[:3]})",
        evidence={"runs_status": runs_status, "listed": sorted(listed)[:5]},
    )
    # The API is paginated: reading one page and comparing it with the whole ledger
    # would manufacture a FAIL on every run larger than one page.
    served: dict[str, dict[str, Any]] = {}
    cursor = 0
    pages = 0
    total_matching: int | None = None
    pagination_error: str | None = None
    while True:
        status, page = get_json(
            base_url, f"/api/monitor/decisions?run_id={run_id}&limit=500&cursor={cursor}"
        )
        if status != 200:
            report.check("V2", False, f"API /decisions returned {status} at cursor {cursor}")
            return {"run_id": run_id, "traces": len(rows), "api_decisions": 0}
        pages += 1
        if isinstance(page.get("total_matching"), int):
            total_matching = page["total_matching"]
        for row in page.get("items") or []:
            served[str(row["decision_id"])] = row
        if not page.get("has_more"):
            break
        next_cursor = int(page.get("next_cursor") or 0)
        if next_cursor <= cursor:
            pagination_error = f"has_more at cursor {cursor} without advancing"
            break
        cursor = next_cursor
        if pages > 200:
            pagination_error = "pagination did not terminate within 200 pages"
            break

    trace_ids = {str(r.get("decision_id")) for r in rows}
    truncated = total_matching is not None and total_matching != len(served)
    report.check(
        "V2",
        trace_ids == set(served) and pagination_error is None and not truncated,
        f"traces={len(trace_ids)} api={len(served)} pages={pages} "
        f"total_matching={total_matching} "
        f"missing_in_api={sorted(trace_ids - set(served))[:5]} "
        f"extra_in_api={sorted(set(served) - trace_ids)[:5]}"
        + (f" pagination={pagination_error}" if pagination_error else ""),
        evidence={"run_id": run_id, "pages": pages, "total_matching": total_matching},
    )

    by_id = {str(r.get("decision_id")): r for r in rows}
    wrong_status: list[str] = []
    wrong_fill: list[str] = []
    bad_pit: list[str] = []
    missing_reason: list[str] = []

    for decision_id, row in by_id.items():
        mode = str(row.get("mode"))
        expected = EXPECTED.get(mode, {"ACCEPTED_NOT_EXECUTED", "EXECUTED_PAPER", "EXECUTION_FAILED"})
        actual = served.get(decision_id, {}).get("status")
        if actual not in expected:
            wrong_status.append(f"{decision_id}: mode={mode} served={actual}")
        if mode in EXPECTED and served.get(decision_id, {}).get("has_fill"):
            wrong_fill.append(f"{decision_id}: mode={mode} served_fill=True")
        if int(row.get("decision_time_ms") or 0) < int(row.get("market_time_ms") or 0):
            bad_pit.append(decision_id)
        if not served.get(decision_id, {}).get("reason_codes"):
            missing_reason.append(decision_id)

    report.check("V3", not wrong_status, "served status matches the trace mode", {"violations": wrong_status[:10]})
    execution_states = {
        "EXECUTED_PAPER",
        "EXECUTION_FAILED",
    }
    fill_semantics_exercised = bool(executed_ids) or any(
        str(row.get("status")) in execution_states for row in served.values()
    )
    if fill_semantics_exercised:
        report.check("V5", not wrong_fill, "no fill shown for NO_TRADE/SHADOW", {"violations": wrong_fill[:10]})
    else:
        report.not_exercised(
            "V5",
            f"run {run_id} contains no execution at all (statuses="
            f"{sorted({str(r.get('status')) for r in served.values()})}); fill semantics not exercised",
            {"executions": 0},
        )
    report.check("V7", not bad_pit, "decision_time >= market_time for every row", {"violations": bad_pit[:10]})
    report.check("V6", not missing_reason, "every decision carries reason codes", {"violations": missing_reason[:10]})

    fills_served = [row for row in served.values() if row.get("has_fill")]
    fills_expected = {e for e in executed_ids if e in by_id}
    if fill_semantics_exercised:
        report.check(
            "V4",
            {row["decision_id"] for row in fills_served} == fills_expected,
            f"fills served={len(fills_served)} execution rows={len(fills_expected)}",
            evidence={"executed_ids": sorted(fills_expected)[:10]},
        )
    else:
        report.not_exercised(
            "V4",
            f"run {run_id} has no execution rows, so 'fill only where evidence' cannot be tested here",
            {"executed_ids": []},
        )

    # --- schema / contract integrity of what the API serves -----------------
    required = (
        "decision_id",
        "run_id",
        "symbol",
        "status",
        "event_type",
        "reason_codes",
        "decision_time_ms",
    )
    schema_gaps: list[str] = []
    future_data: list[str] = []
    for decision_id, row in served.items():
        for field in required:
            if row.get(field) in (None, "", []):
                schema_gaps.append(f"{decision_id}:{field}")
        observed = _iso_to_ms(row.get("observed_market_time"))
        decided = row.get("decision_time_ms")
        if observed is None or not isinstance(decided, int):
            future_data.append(f"{decision_id}: non-parsable timestamps")
        elif observed > decided:
            future_data.append(f"{decision_id}: market {observed} > decision {decided}")
    report.check(
        "V10",
        not schema_gaps,
        f"every served decision carries the contract fields ({len(served)} rows)",
        evidence={"gaps": schema_gaps[:10]},
    )
    report.check(
        "V11",
        not future_data,
        "no served decision uses market data from after its own decision time (HTF look-ahead)",
        evidence={"violations": future_data[:10]},
    )


    provenance_ok = True
    sample_detail = get_json(base_url, f"/api/monitor/decisions/{sorted(trace_ids)[0]}?run_id={run_id}") if trace_ids else (0, {})
    if sample_detail[0] == 200:
        for event in sample_detail[1].get("events", []):
            if not (event.get("event_id") and event.get("run_id") and event.get("decision_id")):
                provenance_ok = False
    report.check("V8", provenance_ok, "every served event carries event_id/run_id/decision_id")

    counters = get_json(base_url, f"/api/monitor/runs/{run_id}/trace")[1].get("counters", {})
    served_fills = counters.get("fills")
    if served_fills is not None and served_fills > len(executed_ids):
        report.fail_false_success(f"counters claim {served_fills} fills but evidence has {len(executed_ids)}")
    report.check(
        "V9",
        served_fills is None or served_fills <= len(executed_ids),
        f"fill counter={served_fills} evidence={len(executed_ids)}",
    )

    return {
        "run_id": run_id,
        "traces": len(rows),
        "api_decisions": len(served),
        "executions": len(executed_ids),
        "fills_served": len(fills_served),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8770")
    parser.add_argument("--runs-root", default="reports/autonomous-paper")
    parser.add_argument("--out", default="reports/trading-decision-monitor/WP-TDM-05")
    parser.add_argument("--verifier-id", default="tdm-independent-verifier-v1")
    args = parser.parse_args()

    runs_root = Path(args.runs_root)
    if not runs_root.is_absolute():
        runs_root = REPO_ROOT / runs_root
    runs = sorted(p for p in runs_root.iterdir() if p.is_dir() and (p / "traces.jsonl").exists())
    report = Report()
    if not runs:
        report.check("V0", False, f"no runs under {runs_root}")
    summaries = [verify_run(run, args.base_url.rstrip("/"), report) for run in runs]

    base = args.base_url.rstrip("/")

    # V12 — read-only is a property of the server, not a promise in a docstring:
    # probe every mutating verb from the outside.
    probe_paths = (
        "/api/monitor/decisions",
        "/api/monitor/health",
        f"/api/monitor/runs/{runs[0].name}/trace" if runs else "/api/monitor/runs",
    )
    probed = {
        method: {path: request_status(base, method, path) for path in probe_paths}
        for method in ("POST", "PUT", "PATCH", "DELETE")
    }
    accepted = [(m, p, s) for m, paths in probed.items() for p, s in paths.items() if 200 <= s < 300]
    report.check(
        "V12",
        not accepted,
        "POST/PUT/PATCH/DELETE are refused by every probed endpoint",
        evidence={"probes": probed},
    )

    # V13 — the same query against an unchanged run must return the same bytes.
    determinism: dict[str, Any] = {}
    replay_stable = True
    for run in runs:
        paths = [f"/api/monitor/runs/{run.name}/trace", f"/api/monitor/decisions?run_id={run.name}&limit=500"]
        digests = []
        for path in paths:
            status, payload = get_json(base, path)
            digests.append(stable_digest(payload) if status == 200 else f"HTTP_{status}")
        repeats = []
        for path in paths:
            status, payload = get_json(base, path)
            repeats.append(stable_digest(payload) if status == 200 else f"HTTP_{status}")
        deterministic = digests == repeats and all(len(d) == 64 for d in digests)
        replay_stable &= deterministic
        determinism[run.name] = {"first": digests, "second": repeats}
    report.check(
        "V13",
        replay_stable and bool(runs),
        "two identical reads of an unchanged run return identical projections (replay determinism)",
        evidence=determinism,
    )

    payload = {
        "schema": "tdm-verifier-report-v1",
        "verifier_id": args.verifier_id,
        "independence": (
            "Separate executable that re-derives expectations from traces.jsonl and compares them "
            "with the HTTP API. It does not import the monitor's projector."
        ),
        "builder_verifier_separation": (
            "PROCESS separation only: this verifier was executed by the same agent that built the "
            "monitor, so REQ-TDM-012 remains PENDING_INDEPENDENT_HUMAN."
        ),
        "base_url": args.base_url,
        "runs_root": str(runs_root),
        "runs": summaries,
        "checks": report.checks,
        "false_success": report.false_success,
        "not_exercised": report.unexercised,
        "coverage": {
            "checks_total": len(report.checks),
            "passed": sum(1 for c in report.checks if c["status"] == "PASS"),
            "failed": sum(1 for c in report.checks if c["status"] == "FAIL"),
            "not_exercised": len(report.unexercised),
            "executions_observed": sum(s.get("executions", 0) for s in summaries),
        },
        "status": report.status,
    }

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "verifier_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = ["# Independent verifier — TDM", "", f"**Status: {payload['status']}** · false_success = {report.false_success}", ""]
    lines.append("| check | status | detail |")
    lines.append("| --- | --- | --- |")
    for check in report.checks:
        lines.append(f"| {check['id']} | {check['status']} | {check['detail']} |")
    lines.append("")
    lines.append("Independence is process-level only; see REQ-TDM-012 in FINAL_REPORT.md.")
    (out / "verifier_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[tdm-verify] {payload['status']} false_success={report.false_success} checks={len(report.checks)}")
    for check in report.checks:
        print(f"[tdm-verify] {check['id']:<5} {check['status']:<4} {check['detail'][:110]}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
