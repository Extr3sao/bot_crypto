"""G-7 independent verifier — replay real public data from a clean export.

The verifier does not import the builder. It exports the requested commit with
``git archive``, runs the evidence script inside that export twice from the
committed public capture, optionally runs one forward observation against the
public provider, and re-derives the acceptance properties from the resulting
JSON plus the committed builder report.

It also runs the relevant tests **inside the export**, so the verification is
not a claim about the working tree. ``PROCEDURALLY SEPARATED``, not a second
person.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
G6_BASELINE = "d5e599ec"
G5_CODE_COMMIT = "05b361f7bd26a4fb9d470d9ba5c68d7f967846c9"
G5_EVIDENCE_COMMIT = "12267039"
LIVE_GATE_SHA256 = "edabd6d3e5632b8fc2aaf68471dfceba09ad187865b9e0660614487816a27ed8"
HOT_STOP_SHA256 = "76cfca23d1e7758607c466eea4ff5c0a9411cb812d433eb7ca16dfb45cfdf8b1"
EXPECTED_BARS_PER_SYMBOL = 500
EXPECTED_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
EXPECTED_TIMEFRAME_MS = 300_000
MAX_FRESHNESS_BARS = 1.5
TEST_FILES = (
    "tests/unit/market_data/test_public_rest.py",
    "tests/unit/market_data/test_real_data_validation.py",
    "tests/unit/paper/test_real_eligibility.py",
    "tests/integration/test_g7_real_paper_replay.py",
    "tests/integration/test_g5_paper_end_to_end.py",
    "tests/unit/test_live_gate_enforcement.py",
)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def _export(rev: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "tree.tar"
    completed = _run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(archive), rev],
        cwd=REPO_ROOT,
        env=dict(os.environ),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive {rev} failed: {completed.stderr.strip()}")
    tree = destination / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(tree, filter="data")
        except TypeError:  # Python < 3.12
            tar.extractall(tree)
    return tree


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_capture_hash(capture: dict[str, Any]) -> str:
    payload = json.dumps(capture, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(REPO_ROOT), *args], cwd=REPO_ROOT, env=dict(os.environ))


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any = None) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def _run_evidence(
    tree: Path,
    out: Path,
    *,
    capture: Path,
    forward: bool,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{tree / 'src'}{os.pathsep}{tree}"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PAPER_CRASH_POINT", None)
    env.pop("PAPER_CRASH_MARKER", None)
    cmd = [
        sys.executable,
        str(tree / "scripts/audit/g7_real_paper.py"),
        "--out",
        str(out),
        "--capture",
        str(capture),
        "--timeframe",
        "5m",
        "--assets",
        "BTC,ETH,SOL",
    ]
    if not forward:
        cmd.append("--no-forward")
    started = time.time()
    completed = _run(cmd, cwd=tree, env=env)
    elapsed = round(time.time() - started, 2)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} evidence command exited {completed.returncode}: "
            f"{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}"
        )
    payload = json.loads((out / "RUN_REPORT.json").read_text(encoding="utf-8"))
    return payload, {
        "run": label,
        "exit_code": completed.returncode,
        "seconds": elapsed,
        "stdout_tail": completed.stdout[-800:],
        "stderr_tail": completed.stderr[-800:],
    }


def _safe(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _snapshot_projection(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            row.get("symbol"),
            row.get("data_mode"),
            row.get("validation_status"),
            row.get("data_hash"),
            row.get("data_time_ms"),
            row.get("data_close_ms"),
            row.get("decision_time_ms"),
            row.get("freshness_ms"),
            row.get("bar_count"),
        )
        for row in rows
    )


def _state_projection(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": state.get("exists"),
        "open_positions": state.get("open_positions"),
        "closed_trades": state.get("closed_trades"),
        "sent_intents": state.get("sent_intents"),
        "orders": state.get("orders"),
    }


def _session_projection(session: dict[str, Any]) -> dict[str, Any]:
    cycle = session.get("cycle") or {}
    keep_cycle = (
        "contexts_built",
        "context_errors",
        "router_invocations",
        "router_no_trade",
        "strategy_invocations",
        "signals_generated",
        "orders_created",
        "risk_accepted",
        "risk_rejected",
        "duplicate_intents",
        "broker_errors",
    )
    return {
        "label": session.get("label"),
        "decision_outcome": session.get("decision_outcome"),
        "orders_created": session.get("orders_created"),
        "broker_calls": session.get("broker_calls"),
        "reconciliation": _safe(session, "reconciliation", "status"),
        "cycle": {key: cycle.get(key) for key in keep_cycle},
        "state": _state_projection(session.get("state") or {}),
    }


def _replay_projection(payload: dict[str, Any]) -> dict[str, Any]:
    replay = payload.get("replay") or {}
    return {
        "capture_sha256": _safe(payload, "capture", "sha256"),
        "decisions": replay.get("decision_time_ms"),
        "sessions": [_session_projection(s) for s in replay.get("sessions", [])],
        "restart": _session_projection(replay.get("restart") or {}),
        "snapshots": _snapshot_projection(replay.get("snapshots", [])),
        "eligibility": [
            {
                "selected": report.get("selected"),
                "counts": report.get("counts"),
                "rows": [
                    (
                        row.get("strategy_id"),
                        row.get("router_verdict"),
                        row.get("selected"),
                        row.get("validation_status"),
                    )
                    for row in report.get("rows", [])
                ],
            }
            for report in replay.get("eligibility", [])
        ],
        "invalid": {
            name: {
                "status": _safe(item, "validation", "validation_status"),
                "outcome": item.get("decision_outcome"),
            }
            for name, item in (payload.get("invalid") or {}).get("scenarios", {}).items()
        },
        "summary": payload.get("summary"),
    }


def _validate_bars(bars: list[list[Any]], *, captured_at_ms: int) -> list[str]:
    issues: list[str] = []
    if len(bars) != EXPECTED_BARS_PER_SYMBOL:
        issues.append(f"bar count {len(bars)} != {EXPECTED_BARS_PER_SYMBOL}")
    timestamps = [int(row[0]) for row in bars]
    if len(set(timestamps)) != len(timestamps):
        issues.append("duplicate timestamps")
    if timestamps != sorted(timestamps):
        issues.append("timestamps are not ascending")
    for left, right in pairwise(timestamps):
        if int(right) - int(left) != EXPECTED_TIMEFRAME_MS:
            issues.append(f"gap/overlap between {left} and {right}")
            break
    for row in bars:
        timestamp, open_, high, low, close, volume = row[:6]
        if int(timestamp) + EXPECTED_TIMEFRAME_MS > captured_at_ms:
            issues.append(f"bar {timestamp} was not closed at capture")
            break
        if float(high) < max(float(open_), float(close)):
            issues.append(f"bar {timestamp} high below body")
            break
        if float(low) > min(float(open_), float(close)):
            issues.append(f"bar {timestamp} low above body")
            break
        if float(volume) < 0:
            issues.append(f"bar {timestamp} negative volume")
            break
    return issues


def verify_capture(capture: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if capture.get("provider") != "binance-public-rest":
        issues.append(f"provider is {capture.get('provider')!r}")
    if capture.get("schema_version") != "g7-public-capture/v1":
        issues.append("unexpected capture schema")
    if capture.get("timeframe") != "5m":
        issues.append("capture timeframe is not 5m")
    symbols = capture.get("symbols") or {}
    if set(symbols) != set(EXPECTED_SYMBOLS):
        issues.append(f"symbols are {sorted(symbols)}")
    captured_at_ms = int(capture.get("captured_at_ms", 0) or 0)
    for symbol in EXPECTED_SYMBOLS:
        item = symbols.get(symbol)
        if not isinstance(item, dict):
            issues.append(f"{symbol} missing")
            continue
        bars = item.get("bars") or []
        issues.extend(
            f"{symbol}: {issue}" for issue in _validate_bars(bars, captured_at_ms=captured_at_ms)
        )
        quote = item.get("quote") or {}
        if float(quote.get("volume_24h_usdt", 0) or 0) <= 0:
            issues.append(f"{symbol}: missing positive 24h volume")
        if float(quote.get("spread_bps", -1) or -1) < 0:
            issues.append(f"{symbol}: missing spread")
    return issues


def _common_checks(
    checks: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    capture_file: Path,
    capture: dict[str, Any],
    expected_capture_hash: str,
    label: str,
) -> None:
    _check(
        checks,
        f"{label}:PAPER_ONLY",
        payload.get("execution_class") == "PAPER_ONLY_REAL_PUBLIC_DATA"
        and payload.get("live") is False
        and payload.get("credentials_used") is False
        and payload.get("exchange_clients_constructed") is False
        and payload.get("order_sent") is False,
        {
            "class": payload.get("execution_class"),
            "live": payload.get("live"),
            "credentials": payload.get("credentials_used"),
            "clients": payload.get("exchange_clients_constructed"),
            "order_sent": payload.get("order_sent"),
        },
    )
    _check(
        checks,
        f"{label}:CAPTURE_HASH",
        _safe(payload, "capture", "sha256") == expected_capture_hash
        and _safe(payload, "capture", "path") == "market_capture.json"
        and _safe(payload, "capture", "captured_at_ms") == capture.get("captured_at_ms"),
        {
            "fixture_sha256": _sha256_file(capture_file),
            "fixture_canonical_sha256": _canonical_capture_hash(capture),
            "payload_capture_sha256": _safe(payload, "capture", "sha256"),
        },
    )
    _check(
        checks,
        f"{label}:REAL_PUBLIC_DATA",
        payload.get("provider") == "binance-public-rest"
        and payload.get("provider_base_url") == "https://api.binance.com"
        and not verify_capture(capture)
        and _safe(payload, "capture", "captured_at_ms") == capture.get("captured_at_ms"),
        verify_capture(capture),
    )


def _verify_replay(payload: dict[str, Any], capture_file: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    _common_checks(
        checks,
        payload,
        capture_file=capture_file,
        capture=capture,
        expected_capture_hash=_canonical_capture_hash(capture),
        label="replay",
    )
    replay = payload.get("replay") or {}
    snapshots = replay.get("snapshots") or []
    decided = [s for s in snapshots if s.get("validation_status") == "OK"]
    no_future = all(
        int(row.get("data_time_ms", 0)) <= int(row.get("decision_time_ms", 0))
        and int(row.get("data_close_ms", 0)) <= int(row.get("decision_time_ms", 0))
        and int(row.get("freshness_ms", -1)) >= 0
        for row in snapshots
    )
    _check(
        checks,
        "replay:NO_LOOKAHEAD",
        len(snapshots) == 12
        and no_future
        and all(row.get("data_mode") == "HISTORICAL_REPLAY" for row in snapshots)
        and all(row.get("validation_status") == "OK" for row in snapshots)
        and len(decided) == 12,
        {
            "snapshots": len(snapshots),
            "data_modes": sorted({row.get("data_mode") for row in snapshots}),
            "statuses": sorted({row.get("validation_status") for row in snapshots}),
            "no_future": no_future,
        },
    )
    sessions = replay.get("sessions") or []
    restart = replay.get("restart") or {}
    _check(
        checks,
        "replay:THREE_DECISIONS_RESTART",
        len(sessions) == 3
        and all(s.get("decision_outcome") == "NO_TRADE" for s in sessions)
        and all(int(s.get("orders_created", 0)) == 0 for s in sessions)
        and all((s.get("broker_calls") or {}).get("execute_signal") == 0 for s in sessions)
        and restart.get("decision_outcome") == "NO_TRADE"
        and _safe(restart, "reconciliation", "status") == "RECOVERED"
        and int(restart.get("orders_created", 0)) == 0
        and (restart.get("cycle") or {}).get("duplicate_intents") == 0
        and (restart.get("state") or {}).get("sent_intents") == 0
        and (restart.get("state") or {}).get("orders") == [],
        {
            "sessions": [s.get("decision_outcome") for s in sessions],
            "restart": _safe(restart, "reconciliation", "status"),
            "restart_orders": restart.get("orders_created"),
        },
    )
    reports = replay.get("eligibility") or []
    all_rows = [row for report in reports for row in report.get("rows", [])]
    _check(
        checks,
        "replay:NO_ELIGIBLE_STRATEGY",
        len(reports) == 3
        and all(not report.get("selected") for report in reports)
        and all(report.get("counts") == {"NOT_APPLICABLE": 18} for report in reports)
        and len(all_rows) == 54
        and all(row.get("selected") is False for row in all_rows)
        and all(row.get("admitted_for_paper") is False for row in all_rows)
        and all(row.get("eligibility_reason") for row in all_rows),
        {
            "reports": len(reports),
            "selected": [report.get("selected") for report in reports],
            "counts": [report.get("counts") for report in reports],
        },
    )
    invalid = (payload.get("invalid") or {}).get("scenarios") or {}
    _check(
        checks,
        "replay:INVALID_DATA_BLOCKED",
        len(invalid) == 6
        and all(item.get("decision_outcome") == "BLOCKED_DATA" for item in invalid.values())
        and all(int(item.get("orders_created", -1)) == 0 for item in invalid.values())
        and int((payload.get("invalid") or {}).get("blocked", 0)) == 6,
        {name: _safe(item, "validation", "validation_status") for name, item in invalid.items()},
    )
    failure = payload.get("provider_failure") or {}
    _check(
        checks,
        "replay:PROVIDER_FAILURE_CONTAINED",
        int(failure.get("orders_created", -1)) == 0
        and (failure.get("broker_calls") or {}).get("execute_signal") == 0
        and int(_safe(failure, "status", "last_session_metrics", "scanner_errors", default=0)) >= 1
        and int(_safe(failure, "status", "last_session_metrics", "total_snapshots", default=99))
        == 0,
        {
            "scanner_errors": _safe(failure, "status", "last_session_metrics", "scanner_errors"),
            "orders": failure.get("orders_created"),
        },
    )
    return checks


def _verify_builder_forward(payload: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    forward = payload.get("forward") or {}
    snapshots = forward.get("snapshots") or []
    session = forward.get("session") or {}
    received = int(forward.get("received_at_ms", 0) or 0)
    decision = int(forward.get("decision_time_ms", 0) or 0)
    _check(
        checks,
        "builder:FORWARD_EXECUTED",
        forward.get("status") == "EXECUTED"
        and forward.get("data_mode") == "FORWARD"
        and received > 0
        and received <= decision
        and len(snapshots) == 3
        and all(row.get("data_mode") == "FORWARD" for row in snapshots)
        and all(row.get("validation_status") == "OK" for row in snapshots)
        and all(int(row.get("data_time_ms", 0)) <= decision for row in snapshots)
        and all(int(row.get("received_at_ms", 0)) <= decision for row in snapshots)
        and session.get("decision_outcome") == "NO_TRADE"
        and int(session.get("orders_created", -1)) == 0
        and (session.get("broker_calls") or {}).get("execute_signal") == 0,
        {
            "status": forward.get("status"),
            "received_at_ms": received,
            "decision_time_ms": decision,
            "snapshots": len(snapshots),
            "session": session.get("decision_outcome"),
        },
    )
    _check(
        checks,
        "builder:VERDICT_IS_BLOCKED_NOT_PASS",
        _safe(payload, "summary", "verdict") == "G7_BLOCKED_NO_ELIGIBLE_STRATEGY"
        and _safe(payload, "summary", "eligible_count") == 0
        and _safe(payload, "summary", "false_success") == 0
        and _safe(payload, "summary", "live_no_go") is True
        and _safe(payload, "summary", "production_ready") is False
        and _safe(payload, "summary", "duplicate_orders") == 0,
        payload.get("summary"),
    )
    claimed = payload.get("evidence_sha256")
    without_hash = {key: value for key, value in payload.items() if key != "evidence_sha256"}
    actual = hashlib.sha256(
        json.dumps(without_hash, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    _check(
        checks, "builder:EVIDENCE_HASH", claimed == actual, {"claimed": claimed, "actual": actual}
    )
    return checks


def _verify_baseline(tree: Path, rev: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    live_hash = _sha256_file(tree / "src/trading_bot/execution/live_gate.py")
    hot_hash = _sha256_file(tree / "src/trading_bot/autonomous/hot_stop.py")
    _check(
        checks,
        "LIVE_GATE_UNCHANGED",
        live_hash == LIVE_GATE_SHA256
        and _git(
            "diff",
            "--quiet",
            f"{G6_BASELINE}..{rev}",
            "--",
            "src/trading_bot/execution/live_gate.py",
        ).returncode
        == 0,
        {"live_gate_sha256": live_hash, "expected": LIVE_GATE_SHA256},
    )
    _check(
        checks,
        "HOT_STOP_UNCHANGED",
        hot_hash == HOT_STOP_SHA256,
        {"hot_stop_sha256": hot_hash, "expected": HOT_STOP_SHA256},
    )
    g6 = _git("cat-file", "-e", f"{G6_BASELINE}^{{commit}}").returncode == 0
    g5_code = _git("cat-file", "-e", f"{G5_CODE_COMMIT}^{{commit}}").returncode == 0
    g5_evidence = _git("cat-file", "-e", f"{G5_EVIDENCE_COMMIT}^{{commit}}").returncode == 0
    g6_ancestor = _git("merge-base", "--is-ancestor", G6_BASELINE, rev).returncode == 0
    g6_verification = tree / "docs/audit/runs/run-20261025T141859Z-G-6/verification.json"
    g6_verdict = None
    if g6_verification.exists():
        g6_verdict = json.loads(g6_verification.read_text(encoding="utf-8")).get("verdict")
    _check(
        checks,
        "G5_G6_BASELINE",
        g6 and g5_code and g5_evidence and g6_ancestor and g6_verdict == "G6_VERIFIED",
        {
            "g6_baseline": G6_BASELINE,
            "g6_present": g6,
            "g6_ancestor": g6_ancestor,
            "g6_verdict": g6_verdict,
            "g5_code": g5_code,
            "g5_evidence": g5_evidence,
        },
    )
    return checks


def _verify_tests(tree: Path) -> list[dict[str, Any]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{tree / 'src'}{os.pathsep}{tree}"
    env["PYTHONHASHSEED"] = "0"
    started = time.time()
    completed = _run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TEST_FILES],
        cwd=tree,
        env=env,
    )
    tail = (completed.stdout + completed.stderr)[-2500:]
    return [
        {
            "check": "TESTS_IN_EXPORT",
            "passed": completed.returncode == 0,
            "detail": {
                "command": "python -m pytest -q " + " ".join(TEST_FILES),
                "returncode": completed.returncode,
                "seconds": round(time.time() - started, 2),
                "tail": tail,
            },
        }
    ]


def _latest_run(tree: Path) -> Path:
    candidates = sorted(tree.glob("docs/audit/runs/run-*-G-7"))
    if not candidates:
        raise FileNotFoundError("no committed G-7 run directory in the export")
    return candidates[-1]


def verify(
    tree: Path,
    *,
    rev: str,
    builder: dict[str, Any],
    replay_one: dict[str, Any],
    replay_two: dict[str, Any],
    forward_run: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    fixture = tree / "docs/audit/fixtures/g7_market_capture.json"
    checks.extend(_verify_replay(replay_one, fixture))
    checks.extend(_verify_builder_forward(builder))
    if forward_run is not None:
        forward = forward_run.get("forward") or {}
        checks.append(
            {
                "check": "verifier:FORWARD_PROBE",
                "passed": forward.get("status") == "EXECUTED"
                and (forward.get("snapshots") or [{}])[0].get("data_mode") == "FORWARD"
                and int(forward.get("received_at_ms", 0) or 0)
                <= int(forward.get("decision_time_ms", 0) or 0),
                "detail": {
                    "status": forward.get("status"),
                    "received_at_ms": forward.get("received_at_ms"),
                    "decision_time_ms": forward.get("decision_time_ms"),
                },
            }
        )
    checks.append(
        {
            "check": "replay:DETERMINISTIC",
            "passed": _replay_projection(replay_one) == _replay_projection(replay_two),
            "detail": {
                "first": replay_one.get("evidence_sha256"),
                "second": replay_two.get("evidence_sha256"),
                "note": "timestamps, run ids and hashes are excluded from the projection",
            },
        }
    )
    checks.extend(_verify_baseline(tree, rev))
    checks.extend(_verify_tests(tree))
    eligible = _safe(builder, "summary", "eligible_count")
    replay_selected = [
        selected
        for report in _safe(builder, "replay", "eligibility", default=[])
        for selected in report.get("selected", [])
    ]
    order_claims = [
        int(session.get("orders_created", 0))
        for session in _safe(builder, "replay", "sessions", default=[])
    ] + [int(_safe(builder, "forward", "session", "orders_created", default=0))]
    checks.append(
        {
            "check": "FALSE_SUCCESS_ZERO",
            "passed": eligible == 0
            and not replay_selected
            and all(value == 0 for value in order_claims)
            and _safe(builder, "summary", "broker_execute_calls") == 0
            and _safe(builder, "summary", "duplicate_orders") == 0,
            "detail": {
                "eligible": eligible,
                "replay_selected": replay_selected,
                "order_claims": order_claims,
                "broker_calls": _safe(builder, "summary", "broker_execute_calls"),
            },
        }
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-7 independent verification.")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--forward", action="store_true", help="Also run one real forward probe.")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="g7-verify-"))
    checks: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    verdict = "G7_NOT_VERIFIED"
    status = "FAILED"
    resolved = _git("rev-parse", args.rev)
    resolved_rev = resolved.stdout.strip() if resolved.returncode == 0 else args.rev
    builder: dict[str, Any] = {}
    try:
        tree = _export(args.rev, tmp)
        fixture = tree / "docs/audit/fixtures/g7_market_capture.json"
        if not fixture.exists():
            raise FileNotFoundError(f"committed capture not found: {fixture}")
        if args.run_dir:
            candidate = Path(args.run_dir)
            run_dir = candidate if candidate.is_absolute() else tree / candidate
        else:
            run_dir = _latest_run(tree)
        report_path = run_dir / "RUN_REPORT.json"
        if not report_path.exists():
            raise FileNotFoundError(f"builder RUN_REPORT.json not found: {report_path}")
        builder = json.loads(report_path.read_text(encoding="utf-8"))
        first, first_meta = _run_evidence(
            tree, tmp / "replay1", capture=fixture, forward=False, label="replay1"
        )
        second, second_meta = _run_evidence(
            tree, tmp / "replay2", capture=fixture, forward=False, label="replay2"
        )
        runs = [first_meta, second_meta]
        forward_run: dict[str, Any] | None = None
        if args.forward:
            forward_run, forward_meta = _run_evidence(
                tree, tmp / "forward", capture=fixture, forward=True, label="forward"
            )
            runs.append(forward_meta)
        checks = verify(
            tree,
            rev=resolved_rev,
            builder=builder,
            replay_one=first,
            replay_two=second,
            forward_run=forward_run,
        )
        all_passed = all(check["passed"] for check in checks)
        blocked = (
            _safe(builder, "summary", "verdict") == "G7_BLOCKED_NO_ELIGIBLE_STRATEGY"
            and _safe(builder, "summary", "eligible_count") == 0
        )
        if all_passed and blocked:
            verdict = "G7_BLOCKED_NO_ELIGIBLE_STRATEGY"
            status = "BLOCKED"
        elif all_passed:
            verdict = "G7_VERIFIED"
            status = "VERIFIED"
    except Exception as exc:
        checks.append(
            {
                "check": "VERIFIER_EXCEPTION",
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
        verdict = "G7_NOT_VERIFIED"
        status = "FAILED"

    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    payload = {
        "schema_version": "g7-verification/v1",
        "verdict": verdict,
        "status": status,
        "requested_rev": args.rev,
        "rev": resolved_rev,
        "builder_run": str(Path(args.run_dir) if args.run_dir else "auto"),
        "checks": checks,
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "checks_total": len(checks),
        "false_success": 0 if all(check["passed"] for check in checks) else None,
        "live_no_go": True,
        "production_ready": False,
        "runs": runs,
        "seconds": round(time.time() - started, 2),
    }
    out = Path(args.out) if args.out else Path.cwd() / "verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "status": status,
                "checks": f"{payload['checks_passed']}/{payload['checks_total']}",
            },
            indent=2,
        )
    )
    print(f"verification written to {out}")
    return 0 if status in {"VERIFIED", "BLOCKED"} and payload["false_success"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
