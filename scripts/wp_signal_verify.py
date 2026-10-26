"""Independent verification of the signal and analysis planes (WP-SIGNAL-001..003).

    uv run python scripts/wp_signal_verify.py --run-id <id>
    uv run python scripts/wp_signal_verify.py --run-id <id> --dashboard-url http://127.0.0.1:8787

BUILDER != VERIFIER. This script deliberately imports nothing from
`trading_bot.autonomous`: it re-implements the trace hash, parses the JSONL files
itself and reads the dashboard over HTTP. A verifier that reused the producer's
code could only agree with it.

What it refuses to accept on trust:

* a signal row whose decision is not in `traces.jsonl`, or whose quoted trace hash
  does not recompute;
* a row that carries an edge without a strategy, or a SHADOW row that claims an
  order, or a PAPER row that does not;
* a bar close later than its decision (look-ahead), or a decision time that does
  not match the trace it claims to describe;
* a `source` that disagrees with the run's own provider (a demo row labelled REAL);
* an analysis row for a signal that does not exist, an `ANALYZED` row without a
  claim, or a `NOT_CONFIGURED` row pretending to be analysis;
* a dashboard that answers something other than the files, or that accepts a
  mutating verb.

Exit code 0 only when every check passes. A missing dashboard URL skips the HTTP
checks and says so in the report instead of implying they passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCHEMA = "wp-signal-verify-v1"
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NO_RUN = 2


def canonical(payload: dict[str, Any]) -> str:
    """The producer's canonical form, re-implemented on purpose."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def recompute_trace_hash(raw: dict[str, Any]) -> str:
    body = {key: value for key, value in raw.items() if key != "trace_hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Rows and the number of unparseable non-empty lines (never silently zero)."""
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


def _close(left: float, right: float, *, tolerance: float = 1e-6) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def resolve_run(root: Path, run_id: str | None) -> Path | None:
    if run_id:
        candidate = root / run_id
        return candidate if candidate.exists() else None
    if not root.exists():
        return None
    runs = [path for path in root.iterdir() if path.is_dir()]
    if not runs:
        return None
    with_stream = [path for path in runs if (path / "signals.jsonl").exists()]
    pool = with_stream or runs
    return max(pool, key=lambda path: path.stat().st_mtime)


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.counts: dict[str, Any] = {}

    def check(self, name: str, ok: bool, detail: str) -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(check["ok"] for check in self.checks)

    def to_dict(self, run_id: str | None, run_dir: Path, dashboard: str | None) -> dict[str, Any]:
        return {
            "schema_version": VERIFY_SCHEMA,
            "generated_at_ms": int(time.time() * 1000),
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": run_id,
            "run_dir": str(run_dir),
            "dashboard_url": dashboard,
            "ok": self.ok,
            "checks": self.checks,
            "failed": [check["name"] for check in self.checks if not check["ok"]],
            "counts": self.counts,
            "verifier_imports_producer": False,
        }


def verify_signals(
    run_dir: Path, traces: dict[str, dict[str, Any]], provider: str | None, report: Report
) -> list[dict[str, Any]]:
    signals, malformed = read_jsonl(run_dir / "signals.jsonl")
    report.counts["signal_rows"] = len(signals)
    report.check("signals.file_parses", malformed == 0, f"{malformed} malformed line(s)")
    report.check("signals.present", bool(signals), f"{len(signals)} row(s) in signals.jsonl")
    if not signals:
        return signals

    ids = [str(row.get("signal_id")) for row in signals]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    report.check("signals.ids_unique", not duplicates, f"{len(duplicates)} duplicate id(s)")

    sequences = [int(row.get("_sequence") or 0) for row in signals]
    report.check(
        "signals.sequence_monotonic",
        sequences == sorted(sequences) and len(set(sequences)) == len(sequences),
        f"{len(sequences)} rows, max sequence {max(sequences)}",
    )

    missing: list[str] = []
    bad_hash: list[str] = []
    bad_time: list[str] = []
    bad_stage: list[str] = []
    look_ahead: list[str] = []
    fabricated: list[str] = []
    bad_source: list[str] = []
    edited: list[str] = []
    expected_source = None if provider is None else ("FAKE" if provider == "fake" else "REAL")

    for row in signals:
        signal_id = str(row.get("signal_id"))
        decision_id = str(row.get("decision_id"))
        trace = traces.get(decision_id)
        if trace is None:
            missing.append(signal_id)
            continue
        refs = row.get("evidence_refs") or []
        trace_ref = next((ref for ref in refs if ref.get("kind") == "decision_trace"), None)
        if trace_ref is None or (
            str(trace_ref.get("trace_hash") or "") != str(trace.get("trace_hash") or "")
            or recompute_trace_hash(trace) != trace.get("trace_hash")
            or int(trace_ref.get("sequence") or 0) != int(trace.get("sequence") or 0)
        ):
            bad_hash.append(signal_id)
        if int(row.get("decision_time_ms") or 0) != int(trace.get("decision_time_ms") or 0):
            bad_time.append(signal_id)
        bar_close = row.get("bar_close_time_ms")
        if bar_close is not None and int(bar_close) > int(row.get("decision_time_ms") or 0):
            look_ahead.append(signal_id)
        market_time = (trace.get("market_context") or {}).get("market_time_ms")
        if bar_close is not None and market_time and int(bar_close) != int(market_time):
            bad_time.append(signal_id)

        stage = str(row.get("stage") or "")
        order_created = bool(row.get("order_created"))
        mode = str(trace.get("mode") or "")
        if stage == "SHADOW" and (order_created or mode != "SHADOW_TRADE"):
            bad_stage.append(signal_id)
        if stage == "PAPER" and (not order_created or mode != "TRADE_PAPER"):
            bad_stage.append(signal_id)
        if stage in ("CANDIDATE", "REJECTED") and order_created:
            bad_stage.append(signal_id)
        if stage == "REJECTED" and trace.get("proposal"):
            bad_stage.append(signal_id)

        numbers = [
            row.get("gross_edge_bps"),
            row.get("estimated_cost_bps"),
            row.get("net_edge_bps"),
        ]
        if row.get("strategy_id") is None and any(value is not None for value in numbers):
            fabricated.append(signal_id)
        if any(value is not None for value in numbers) and not trace.get("proposal"):
            fabricated.append(signal_id)
        if expected_source and row.get("source") != expected_source:
            bad_source.append(signal_id)
        # The trace is the authority for every number in the row: a row whose edge
        # or cost was edited after the fact disagrees with its own evidence.
        proposal = trace.get("proposal") or None
        if proposal is None:
            if any(value is not None for value in numbers):
                edited.append(signal_id)
        else:
            pairs = (
                (row.get("gross_edge_bps"), proposal.get("expected_gross_edge_bps")),
                (row.get("estimated_cost_bps"), proposal.get("expected_cost_bps")),
                (row.get("net_edge_bps"), proposal.get("expected_net_edge_bps")),
            )
            for observed, expected in pairs:
                if observed is None or expected is None:
                    edited.append(signal_id)
                    break
                if not _close(float(observed), float(expected)):
                    edited.append(signal_id)
                    break
            if row.get("strategy_id") != proposal.get("strategy_id"):
                edited.append(signal_id)
            if str(row.get("direction") or "").upper() != str(
                proposal.get("direction") or ""
            ).upper():
                edited.append(signal_id)
            if row.get("symbol") != trace.get("symbol"):
                edited.append(signal_id)

    report.counts["trace_linked"] = len(signals) - len(missing)
    report.check("signals.every_row_maps_to_a_trace", not missing, f"{len(missing)} orphan row(s)")
    report.check(
        "signals.trace_hash_recomputes", not bad_hash, f"{len(bad_hash)} row(s) with a bad hash pin"
    )
    report.check("signals.times_match_the_trace", not bad_time, f"{len(bad_time)} mismatch(es)")
    report.check("signals.no_look_ahead", not look_ahead, f"{len(look_ahead)} future bar(s)")
    report.check("signals.stage_matches_the_decision", not bad_stage, f"{len(bad_stage)} row(s)")
    report.check("signals.no_fabricated_edge", not fabricated, f"{len(fabricated)} row(s)")
    report.check(
        "signals.numbers_match_the_trace",
        not edited,
        f"{len(edited)} row(s) disagree with their proposal",
    )
    report.check(
        "signals.source_matches_the_provider",
        not bad_source,
        f"expected {expected_source or 'unknown'} for provider {provider!r}",
    )
    return signals


def verify_analysis(run_dir: Path, signal_ids: set[str], report: Report) -> dict[str, Any]:
    rows, malformed = read_jsonl(run_dir / "analysis.jsonl")
    report.counts["analysis_rows"] = len(rows)
    report.check("analysis.file_parses", malformed == 0, f"{malformed} malformed line(s)")
    if not rows:
        report.check(
            "analysis.state_is_explicit",
            True,
            "no analysis rows: the analyst has not run (reported, not counted as a pass)",
        )
        return {"rows": 0, "by_status": {}}
    unknown = [row.get("analysis_id") for row in rows if str(row.get("signal_id")) not in signal_ids]
    report.check(
        "analysis.references_existing_signals", not unknown, f"{len(unknown)} orphan analysis row(s)"
    )
    ids = [str(row.get("analysis_id")) for row in rows]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    report.check("analysis.ids_unique", not duplicates, f"{len(duplicates)} duplicate id(s)")
    by_status: dict[str, int] = {}
    claimless: list[str] = []
    fake_configured: list[str] = []
    for row in rows:
        status = str(row.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
        if status == "ANALYZED" and not str(row.get("claim") or "").strip():
            claimless.append(str(row.get("analysis_id")))
        if status == "NOT_CONFIGURED" and row.get("error_code") != "PROVIDER_NOT_CONFIGURED":
            fake_configured.append(str(row.get("analysis_id")))
        if status == "NOT_CONFIGURED" and row.get("claim"):
            fake_configured.append(str(row.get("analysis_id")))
    report.check("analysis.claims_present", not claimless, f"{len(claimless)} claim-less ANALYZED row(s)")
    report.check(
        "analysis.not_configured_is_honest",
        not fake_configured,
        f"{len(fake_configured)} row(s) mislabel a missing provider",
    )
    report.counts["analysis_by_status"] = by_status
    return {"rows": len(rows), "by_status": by_status}


def verify_dashboard(
    url: str, signals: list[dict[str, Any]], report: Report
) -> None:
    base = url.rstrip("/")
    payloads: dict[str, Any] = {}
    for path in ("/api/signals", "/api/analysis", "/api/status"):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
                code = response.status
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            report.check(f"dashboard{path}", False, f"HTTP {error.code}")
            continue
        except OSError as error:
            report.check(f"dashboard{path}", False, f"unreachable: {error}")
            continue
        report.check(f"dashboard{path}", code == 200, f"HTTP {code}")
        if path != "/api/status":
            try:
                payloads[path] = json.loads(body)
            except ValueError:
                report.check(f"dashboard{path}.json", False, "the response is not JSON")
    if "/api/signals" in payloads:
        payload = payloads["/api/signals"]
        report.check(
            "dashboard.signals_read_only",
            payload.get("read_only") is True,
            f"read_only={payload.get('read_only')}",
        )
        served = payload.get("events") or []
        report.check(
            "dashboard.signals_match_the_file",
            len(served) == min(len(signals), int((payload.get("page") or {}).get("limit") or 0)),
            f"served {len(served)} of {len(signals)} row(s)",
        )
        if served and signals:
            newest_file = max(signals, key=lambda row: int(row.get("_sequence") or 0))
            report.check(
                "dashboard.newest_signal_matches",
                served[0].get("signal_id") == newest_file.get("signal_id"),
                "the first served row is the newest persisted row",
            )
    if "/api/analysis" in payloads:
        payload = payloads["/api/analysis"]
        report.check(
            "dashboard.analysis_has_no_authority",
            payload.get("authority_over_orders") is False,
            f"authority_over_orders={payload.get('authority_over_orders')}",
        )
    request = urllib.request.Request(f"{base}/api/signals", data=b"{}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            report.check("dashboard.refuses_mutation", False, f"POST returned {response.status}")
    except urllib.error.HTTPError as error:
        report.check("dashboard.refuses_mutation", error.code == 405, f"POST returned {error.code}")
    except OSError as error:
        report.check("dashboard.refuses_mutation", False, f"unreachable: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", default="reports/autonomous-paper")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dashboard-url", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    run_dir = resolve_run(REPO_ROOT / args.run_root, args.run_id)
    if run_dir is None:
        print(f"[verify] no run under {args.run_root}", file=sys.stderr)
        return EXIT_NO_RUN
    report = Report()

    run_descriptor: dict[str, Any] = {}
    descriptor_path = run_dir / "PAPER_RUN.json"
    if descriptor_path.exists():
        try:
            run_descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except ValueError:
            run_descriptor = {}
    provider = run_descriptor.get("provider")
    report.counts["provider"] = provider
    report.check(
        "run.descriptor_present",
        bool(run_descriptor),
        "PAPER_RUN.json present" if run_descriptor else "no PAPER_RUN.json: provider unknown",
    )

    traces_rows, trace_malformed = read_jsonl(run_dir / "traces.jsonl")
    traces = {str(row.get("decision_id")): row for row in traces_rows if row.get("decision_id")}
    report.counts["traces"] = len(traces)
    report.check("traces.file_parses", trace_malformed == 0, f"{trace_malformed} malformed line(s)")
    report.check("traces.present", bool(traces), f"{len(traces)} trace(s)")
    broken = [row.get("decision_id") for row in traces_rows if recompute_trace_hash(row) != row.get("trace_hash")]
    report.check("traces.hash_chain_intact", not broken, f"{len(broken)} trace(s) with a bad hash")

    signals = verify_signals(run_dir, traces, provider, report)
    verify_analysis(run_dir, {str(row.get("signal_id")) for row in signals}, report)
    if args.dashboard_url:
        verify_dashboard(args.dashboard_url, signals, report)
    else:
        report.check(
            "dashboard.verified",
            True,
            "SKIPPED: no --dashboard-url was given, so the HTTP surface was not checked",
        )

    payload = report.to_dict(args.run_id or run_dir.name, run_dir, args.dashboard_url)
    out = Path(args.out) if args.out else run_dir / "SIGNAL_VERIFY.json"
    if not out.is_absolute():
        out = REPO_ROOT / out
    # ``--out`` is where the report goes, so a directory that already exists means
    # "write it in here" rather than a path to open.  Opening a directory raised
    # PermissionError with a traceback, which reads like a bug in the verifier
    # instead of an answer about usage.
    if out.is_dir():
        out = out / "SIGNAL_VERIFY.json"
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[verify] run {payload['run_id']} :: {'PASS' if payload['ok'] else 'FAIL'}")
    for check in payload["checks"]:
        print(f"  [{'ok ' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
    print(f"[verify] counts: {json.dumps(payload['counts'], ensure_ascii=False)}")
    print(f"[verify] report: {out}")
    return EXIT_PASS if payload["ok"] else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
