"""WP-PAPER-REAL-DATA-001 — independent verification of the delivered evidence.

Builder != verifier. This file imports nothing from the builders and re-derives
every claim from the artefacts plus the public endpoint:

* the trace hash chain is recomputed with its own canonical-JSON implementation;
* the PIT invariant (``market_time_ms <= decision_time_ms``, verifier verdict,
  window vs decision time) is re-checked per decision;
* the budget / fee / PnL arithmetic is recomputed from the broker's rows;
* the 120-bar PIT window digest is re-fetched from ``api.binance.com`` and
  compared with the one the data-quality artefact recorded;
* the committed admission ledger and the EXP004A block are re-read, so a
  silently swapped pin or a quietly admitted strategy shows up here;
* the "no venue session / no credentials" claim is checked against the process
  logs and the environment, not against a label.

Nothing here writes to a run directory. Output: ``VERIFIER.json``.

Usage::

    uv run python scripts/wp_prd001_verify.py --evidence <evidence dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
GENESIS = "genesis"


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def trace_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def iso(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(name: str, passed: bool, **detail: Any) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), **detail}


def verify_chain(path: Path) -> dict[str, Any]:
    """Recompute the append-only chain from the raw JSONL."""
    if not path.is_file():
        return _row("trace_chain", False, detail="traces.jsonl missing")
    prev = GENESIS
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        count += 1
        if raw.get("prev_hash") != prev:
            return _row("trace_chain", False, records=count, detail="prev_hash break")
        if trace_hash(raw) != raw.get("trace_hash"):
            return _row("trace_chain", False, records=count, detail="trace_hash mismatch")
        prev = str(raw["trace_hash"])
    return _row("trace_chain", count > 0, records=count)


def verify_run(run_dir: Path, *, ledger: dict[str, Any], expect_orders: bool) -> list[dict[str, Any]]:
    """Per-run decision checks, recomputed from the traces."""
    traces_path = run_dir / "traces.jsonl"
    checks: list[dict[str, Any]] = [verify_chain(traces_path)]
    if not traces_path.is_file():
        return checks
    traces = [json.loads(line) for line in traces_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    pit_ok, pit_detail = True, []
    reason_ok = True
    verdict_ok = True
    admission_ok = True
    trace_proposal_ok = True
    orders = 0
    modes: dict[str, int] = {}
    for trace in traces:
        modes[trace["mode"]] = modes.get(trace["mode"], 0) + 1
        orders += int(trace.get("orders_created") or 0)
        if int(trace["market_time_ms"]) > int(trace["decision_time_ms"]):
            pit_ok = False
            pit_detail.append(f"{trace['decision_id']}:market_time>decision_time")
        if trace["mode"] == "NO_TRADE" and not str(trace.get("reason") or "").strip():
            reason_ok = False
        verdict = str(trace["verification"].get("verdict"))
        check_names = {c.get("name") for c in trace["verification"].get("checks", [])}
        if verdict != "PASS" or "pit_slice_exact" not in check_names:
            verdict_ok = False
            pit_detail.append(f"{trace['decision_id']}:verifier={verdict}")
        proposal = trace.get("proposal")
        if proposal is not None:
            entry = ledger.get("strategies", {}).get(proposal["strategy_id"], {})
            if bool(entry.get("admitted_for_paper")) != bool(
                next(
                    (
                        r["admitted_for_paper"]
                        for r in trace["strategies_considered"]
                        if r["strategy_id"] == proposal["strategy_id"]
                    ),
                    False,
                )
            ):
                admission_ok = False
            if entry and abs(float(proposal["expected_gross_edge_bps"]) - float(
                entry.get("expected_gross_edge_bps", 0.0)
            )) > 1e-9:
                trace_proposal_ok = False

    checks.append(_row("pit_ordering", pit_ok, detail=pit_detail or "every decision used closed bars only"))
    checks.append(_row("no_trade_reasons", reason_ok, decided=len(traces)))
    checks.append(_row("independent_verifier_pass", verdict_ok))
    checks.append(_row("admission_matches_committed_ledger", admission_ok))
    checks.append(_row("proposal_edge_matches_ledger", trace_proposal_ok))

    # The run report must agree with the traces (a summary that inflates would die here).
    report_path = run_dir / "RUN_REPORT.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        totals = report.get("totals") or report.get("summary", {}).get("totals") or {}
        reported_orders = int(totals.get("orders_created", -1))
        checks.append(
            _row(
                "run_report_agrees_with_traces",
                reported_orders == orders,
                reported_orders=reported_orders,
                trace_orders=orders,
            )
        )
    checks.append(
        _row(
            "order_expectation",
            (orders > 0) if expect_orders else (orders == 0),
            orders=orders,
            modes=modes,
        )
    )
    return checks


def verify_data_quality(path: Path) -> list[dict[str, Any]]:
    """Re-derive the window digest from the public endpoint, then audit the record."""
    if not path.is_file():
        return [_row("data_quality_artefact", False, detail="DATA_QUALITY.json missing")]
    payload = json.loads(path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = [_row("data_quality_verdict", payload.get("verdict") == "DATA_QUALITY_PASS")]
    per_symbol_ok = all(s.get("ok") for s in payload.get("symbols_detail", []))
    checks.append(_row("all_symbols_ok", per_symbol_ok))

    for symbol in payload.get("symbols_detail", []):
        pair = symbol["pair"]
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={pair}&interval=1h&limit=200"
        )
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                rows = json.loads(response.read())
        except Exception as exc:  # network failure is reported, never assumed away
            checks.append(_row("window_refetch", False, symbol=pair, detail=type(exc).__name__))
            continue
        # Rebuild the window by its RECORDED BOUNDS, not by "last N": a bar that
        # sealed after the artefact was written must not make a stable window
        # look tampered with.
        first_open = int(symbol["pit_window_first_open_ms"])
        last_open = int(symbol["pit_window_last_open_ms"])
        closed = [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in rows
            if first_open <= int(r[0]) <= last_open
        ]
        closed.sort(key=lambda row: row[0])
        digest = hashlib.sha256(
            json.dumps(closed, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        checks.append(
            _row(
                "window_bar_count_matches",
                len(closed) == int(symbol["pit_window_bars"]),
                symbol=pair,
                refetched=len(closed),
                recorded=symbol["pit_window_bars"],
            )
        )
        checks.append(
            _row(
                "window_refetch_matches",
                digest == symbol.get("pit_window_sha256"),
                symbol=pair,
                refetched=digest[:16],
                recorded=str(symbol.get("pit_window_sha256"))[:16],
            )
        )
    return checks


def verify_data_access(path: Path) -> list[dict[str, Any]]:
    """The fetch journal must show public, unauthenticated reads only."""
    if not path.is_file():
        return [_row("data_access_journal", False, detail="journal missing")]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    unauth = [r for r in rows if r.get("authenticated") is not False]
    providers = sorted({str(r.get("provider")) for r in rows})
    maybe = [r for r in rows if r.get("kind") == "fetch_recent" and int(r.get("bars") or 0) <= 0]
    return [
        _row("data_access_journal", len(rows) > 0, entries=len(rows)),
        _row("journal_unauthenticated", not unauth, offenders=len(unauth)),
        _row("journal_public_provider", providers == ["binance-public-rest"], providers=providers),
        _row("no_empty_fetch", not maybe, empties=len(maybe)),
    ]


def verify_controlled_exec(path: Path) -> list[dict[str, Any]]:
    """Re-do the money arithmetic from the broker's own rows."""
    if not path.is_file():
        return [_row("controlled_exec_artefact", False, detail="CONTROLLED_EXEC.json missing")]
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades = payload.get("closed_trades", [])
    fee_ok, pnl_ok, errors = True, True, []
    for trade in trades:
        notional = float(trade.get("notional_usdt") or 0.0)
        for key in ("entry_commission", "exit_commission"):
            if abs(float(trade.get(key) or 0.0) - notional * 5e-4) > 1e-6:
                fee_ok = False
                errors.append(f"{trade.get('symbol')}:{key}")
        net = float(trade.get("pnl") or 0.0)
        gross = float(trade.get("gross_pnl") or 0.0)
        if abs(net - (gross - float(trade.get("entry_commission") or 0.0) - float(trade.get("exit_commission") or 0.0))) > 1e-6:
            pnl_ok = False
            errors.append(f"{trade.get('symbol')}:net_pnl")
    realized = sum(float(t.get("pnl") or 0.0) for t in trades)
    equity_delta = float(payload.get("detail", {}).get("equity_delta") or 0.0)
    disclosure = payload.get("disclosure", {})
    return [
        _row("controlled_exec_labelled", payload.get("label") == "TEST_EXECUTION"),
        _row("controlled_exec_verdict", payload.get("verdict") == "TEST_EXECUTION_PASS"),
        _row("controlled_exec_fees", fee_ok, errors=errors),
        _row("controlled_exec_pnl", pnl_ok),
        _row("controlled_exec_equity_matches_pnl", abs(equity_delta - realized) <= 1e-6,
             equity_delta=equity_delta, realized=realized),
        _row("controlled_exec_discloses_fixtures",
             "FIXTURE" in str(disclosure.get("signal_source"))
             and "REAL" in str(disclosure.get("market_data"))
             and "TEST" in str(disclosure.get("forced_exit_price"))),
        _row("controlled_exec_no_live_orders", int(disclosure.get("live_orders", -1)) == 0),
    ]


def verify_scope(*, logs: list[Path]) -> list[dict[str, Any]]:
    """Committed configuration, EXP004A block, and the absence of a venue session."""
    checks: list[dict[str, Any]] = []

    ledger = json.loads((REPO_ROOT / "config/strategy_admission.json").read_text(encoding="utf-8"))
    admitted = [k for k, v in ledger["strategies"].items() if v.get("admitted_for_paper")]
    checks.append(_row("committed_ledger_admits_nothing", admitted == [], admitted=admitted))

    corpus = REPO_ROOT / "data/raw/alpha003"
    checks.append(_row("exp004a_corpus_still_absent", not corpus.exists(), path=str(corpus)))

    diff = subprocess.run(
        ["git", "status", "--porcelain", "--", "config/strategy_admission.json", "config/realdata"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks.append(
        _row(
            "config_untouched",
            diff.stdout.strip() == "",
            detail=diff.stdout.strip() or "config/strategy_admission.json and config/realdata unchanged",
        )
    )

    env_keys = [k for k in os.environ if "API_KEY" in k.upper() or "SECRET" in k.upper()]
    checks.append(_row("no_credential_env_vars", not env_keys, keys=env_keys))

    venue_calls, connector_resolves = 0, 0
    for log in logs:
        if not log.is_file():
            continue
        text = log.read_text(encoding="utf-8", errors="ignore")
        venue_calls += text.count("multi_exchange.call.")
        connector_resolves += text.count("multi_exchange.connector.resolve")
    checks.append(
        _row(
            "no_venue_session",
            venue_calls == 0 and connector_resolves == 0,
            multi_exchange_calls=venue_calls,
            connector_resolves=connector_resolves,
        )
    )

    live_markers = 0
    for log in logs:
        if not log.is_file():
            continue
        text = log.read_text(encoding="utf-8", errors="ignore")
        for marker in ("LIVE order", "create_order(", "live_trading_enabled: true"):
            live_markers += text.count(marker)
    checks.append(_row("no_live_markers", live_markers == 0, markers=live_markers))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence", default=str(REPO_ROOT / "docs/agentic/paper_reald/WP-PAPER-REAL-DATA-001")
    )
    args = parser.parse_args(argv)
    evidence = Path(args.evidence)
    raw = evidence / "raw"

    ledger = json.loads((REPO_ROOT / "config/strategy_admission.json").read_text(encoding="utf-8"))
    logs = [
        raw / "run_a.stdout.txt",
        raw / "run_b.stdout.txt",
        raw / "run_c.stdout.txt",
    ]

    checks: list[dict[str, Any]] = []
    checks.append(_row("run_a_artifacts", (raw / "runs/run-a-1h/traces.jsonl").is_file()))
    checks.extend(verify_run(raw / "runs/run-a-1h", ledger=ledger, expect_orders=False))
    checks.append(_row("run_b_artifacts", (raw / "runs/run-b-5m/traces.jsonl").is_file()))
    checks.extend(verify_run(raw / "runs/run-b-5m", ledger=ledger, expect_orders=False))
    checks.extend(verify_data_quality(raw / "DATA_QUALITY.json"))
    checks.extend(verify_data_access(raw / "DATA_ACCESS_run_a.jsonl"))
    checks.extend(verify_controlled_exec(raw / "CONTROLLED_EXEC.json"))
    checks.extend(verify_scope(logs=logs))

    failed = [c["check"] for c in checks if not c["passed"]]
    payload = {
        "wp": "WP-PAPER-REAL-DATA-001",
        "verified_at": iso(int(time.time() * 1000)),
        "verifier": "scripts/wp_prd001_verify.py (independent: no builder imports)",
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "checks": checks,
        "totals": {"checks": len(checks), "passed": len(checks) - len(failed), "failed": len(failed)},
        "failed_checks": failed,
        "false_success": 0 if not failed else len(failed),
        "verdict": "EVIDENCE_CONSISTENT" if not failed else "EVIDENCE_INCONSISTENT",
    }
    path = evidence / "VERIFIER.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["totals"], indent=2))
    if failed:
        print("FAILED: " + ", ".join(failed))
    print(f"[verify] {payload['verdict']} -> {path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
