"""WP-TDM-06 §C — negative controls for the independent verifier.

A verifier that only ever says PASS proves nothing. This harness corrupts a real
run in seven specific ways, serves each corrupted copy through its own monitor
instance and requires ``scripts/tdm_verify.py`` to FAIL on the check that owns
that defect — with ``false_success`` still 0.

The positive control (an unmodified copy) is included so the harness cannot pass
by failing everything.

    PYTHONPATH=src python scripts/tdm06_negative_controls.py \
        --run-dir reports/trading-decision-monitor/WP-TDM-06/runtime-runs/tdm06-live-...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".tmp" / "tdm06-negative"
OUT_DIR = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-06" / "verification"
BASE_PORT = 8801


# ---------------------------------------------------------------------------
# ledger mutation helpers (operate on the copied run only)
# ---------------------------------------------------------------------------


def canonical(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hash_row(row: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(row).encode("utf-8")).hexdigest()


def read_rows(run_dir: Path) -> list[dict[str, Any]]:
    text = (run_dir / "traces.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def write_rows(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    (run_dir / "traces.jsonl").write_text(body + "\n", encoding="utf-8")


def reseal(rows: list[dict[str, Any]]) -> None:
    """Recompute the hash chain so a mutation cannot hide behind a broken link."""
    previous = "genesis"
    for row in rows:
        row["prev_hash"] = previous
        row["trace_hash"] = hash_row(row)
        previous = row["trace_hash"]


def mutate_chain_tamper(run_dir: Path) -> None:
    rows = read_rows(run_dir)
    rows[0]["reason"] = (rows[0].get("reason") or "") + " [tampered]"
    write_rows(run_dir, rows)


def mutate_truncated(run_dir: Path) -> None:
    path = run_dir / "traces.jsonl"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: max(10, len(text) // 2)], encoding="utf-8")


def mutate_future_market_data(run_dir: Path) -> None:
    rows = read_rows(run_dir)
    rows[0]["market_time_ms"] = int(rows[0].get("decision_time_ms") or 0) + 60_000
    reseal(rows)
    write_rows(run_dir, rows)


def mutate_invented_fill(run_dir: Path) -> None:
    rows = read_rows(run_dir)
    report_path = run_dir / "RUN_REPORT.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload.setdefault("executions", []).append(
        {
            "decision_id": rows[0]["decision_id"],
            "run_id": run_dir.name,
            "symbol": rows[0].get("symbol"),
            "asset": rows[0].get("asset"),
            "strategy_id": "ema_crossover@5m",
            "mode": "TRADE_PAPER",
            "notional_usdt": 1_000.0,
            "cloid": "INVENTED-FILL-WITHOUT-EVIDENCE",
        }
    )
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mutate_status_lie(run_dir: Path) -> None:
    rows = read_rows(run_dir)
    rows[0]["mode"] = "SHADOW_TRADE"
    reseal(rows)
    write_rows(run_dir, rows)


def mutate_empty_ledger(run_dir: Path) -> None:
    (run_dir / "traces.jsonl").write_text("", encoding="utf-8")


CASES: list[dict[str, Any]] = [
    {
        "case": "positive_control",
        "expect_status": ["PASS", "PASS_LIMITED"],
        "expected_checks": [],
        "mutate": None,
        "why": "unmodified copy must still verify",
    },
    {
        "case": "chain_tamper",
        "expect_status": ["FAIL"],
        "expected_checks": ["V1"],
        "mutate": mutate_chain_tamper,
        "why": "a row edited without resealing breaks the hash chain",
    },
    {
        "case": "truncated_ledger",
        "expect_status": ["FAIL"],
        "expected_checks": ["V1"],
        "mutate": mutate_truncated,
        "why": "a half-written JSONL line must be reported, not crash or skip",
    },
    {
        "case": "future_market_data",
        "expect_status": ["FAIL"],
        "expected_checks": ["V7"],
        "mutate": mutate_future_market_data,
        "why": "sealed chain but market data after the decision (look-ahead)",
    },
    {
        "case": "invented_fill",
        "expect_status": ["FAIL"],
        "expected_checks": ["V4", "V5"],
        # Either check is a correct detection: V4 catches the ledger/API mismatch
        # when the monitor refuses the fill, V5 catches it if the fill is shown.
        "any_of": True,
        "mutate": mutate_invented_fill,
        "why": "an execution row attached to a NO_TRADE decision",
    },
    {
        "case": "status_lie",
        "expect_status": ["FAIL"],
        "expected_checks": ["V3"],
        "mutate": mutate_status_lie,
        "why": "mode changed and resealed, so only the served status can catch it",
    },
    {
        "case": "empty_ledger",
        "expect_status": ["FAIL"],
        "expected_checks": ["V1"],
        "mutate": mutate_empty_ledger,
        "why": "an empty ledger must never be a vacuous PASS",
    },
]


def wait_for_health(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/monitor/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    return False


def run_case(case: dict[str, Any], source: Path, port: int, python: str) -> dict[str, Any]:
    case_root = SCRATCH / str(case["case"])
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True)
    target = case_root / source.name
    shutil.copytree(source, target)
    mutate: Callable[[Path], None] | None = case["mutate"]
    if mutate is not None:
        mutate(target)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    log_path = SCRATCH / f"{case['case']}.server.log"
    log = log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [
            python,
            str(REPO_ROOT / "scripts" / "trading_decision_monitor.py"),
            "--runs-root",
            str(case_root),
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    result: dict[str, Any] = {"case": case["case"], "why": case["why"], "port": port}
    out_dir = SCRATCH / f"{case['case']}-report"
    try:
        if not wait_for_health(port):
            result["error"] = "monitor did not become healthy"
            return result
        proc = subprocess.run(
            [
                python,
                str(REPO_ROOT / "scripts" / "tdm_verify.py"),
                "--base-url",
                f"http://127.0.0.1:{port}",
                "--runs-root",
                str(case_root),
                "--out",
                str(out_dir),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        report_path = out_dir / "verifier_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        failed = [c["id"] for c in report.get("checks", []) if c.get("status") == "FAIL"]
        result.update(
            {
                "verifier_exit": proc.returncode,
                "status": report.get("status"),
                "false_success": report.get("false_success"),
                "failed_checks": failed,
                "expected_checks": case["expected_checks"],
                "stdout_tail": proc.stdout.strip().splitlines()[-3:],
            }
        )
        match = (
            any(check in failed for check in case["expected_checks"])
            if case.get("any_of")
            else all(check in failed for check in case["expected_checks"])
        )
        detected = report.get("status") in case["expect_status"] and match
        result["detected_correctly"] = bool(detected)
        result["false_success_is_zero"] = report.get("false_success") == 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            server.kill()
        log.close()
    return result


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    source = Path(args.run_dir)
    if not source.is_absolute():
        source = REPO_ROOT / source
    if not (source / "traces.jsonl").exists():
        print(f"[neg] missing traces.jsonl in {source}")
        return 2

    SCRATCH.mkdir(parents=True, exist_ok=True)
    results = [
        run_case(case, source, BASE_PORT + index, args.python)
        for index, case in enumerate(CASES)
    ]

    failed = [r for r in results if not r.get("detected_correctly")]
    zero = all(r.get("false_success_is_zero") for r in results)
    payload = {
        "schema": "wp-tdm-06-negative-controls-v1",
        "source_run": _display_path(source),
        "cases": results,
        "all_detected": not failed,
        "false_success_zero_in_every_case": zero,
        "verdict": "PASS" if not failed and zero else "FAIL",
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "negative_controls.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Verifier negative controls (WP-TDM-06 §C)",
        "",
        f"Source run: `{payload['source_run']}`",
        "",
        f"**Verdict: {payload['verdict']}** · cases={len(results)} · failures={len(failed)}",
        "",
        "| case | expected | observed status | failed checks | detected | false_success |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['case']} | {', '.join(r.get('expected_checks') or ['PASS*'])} | "
            f"{r.get('status')} | {', '.join(r.get('failed_checks') or []) or '—'} | "
            f"{'yes' if r.get('detected_correctly') else 'NO'} | {r.get('false_success')} |"
        )
    lines.append("")
    (out_dir / "negative_controls.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for r in results:
        print(
            f"[neg] {r['case']:<18} status={r.get('status'):<12} "
            f"failed={r.get('failed_checks')} detected={r.get('detected_correctly')} "
            f"false_success={r.get('false_success')}"
        )
    print(f"[neg] verdict={payload['verdict']}")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
