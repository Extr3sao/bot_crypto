"""G-5 independent verifier — re-run the paper evidence from a clean export.

This script is deliberately separate from the evidence runner: it exports the
requested commit with ``git archive``, runs the evidence command inside that
export, and re-derives every acceptance property from the resulting JSON. It
does not import the working tree's implementation to answer its own checks.

The verification is PROCEDURALLY SEPARATED (different script, same author),
not a second person. It reports ``G5_VERIFIED`` only when every check passes.
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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_REL = Path("scripts/audit/g5_paper_e2e.py")
HOT_STOP_SHA256 = "76cfca23d1e7758607c466eea4ff5c0a9411cb812d433eb7ca16dfb45cfdf8b1"


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 180
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


def _evidence(tree: Path, out: Path, *, run_label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{tree / 'src'}{os.pathsep}{tree}"
    env["PYTHONHASHSEED"] = "0"
    env["CERT_HERMETIC"] = "1"
    started = time.time()
    completed = _run(
        [
            sys.executable,
            str(tree / EVIDENCE_REL),
            "--out",
            str(out),
            "--ledger",
            str(tree / "docs/audit/fixtures/g5_paper_ledger.json"),
        ],
        cwd=tree,
        env=env,
    )
    elapsed = round(time.time() - started, 2)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{run_label} evidence command exited {completed.returncode}: "
            f"{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    payload = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    return payload, {
        "run": run_label,
        "exit_code": completed.returncode,
        "seconds": elapsed,
        "stdout_tail": completed.stdout[-500:],
        "stderr_tail": completed.stderr[-500:],
    }


def _projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Fields that must be identical across two runs of the same export."""
    keep = (
        "orders_created",
        "signals_generated",
        "risk_accepted",
        "risk_rejected",
        "hot_stop_blocked",
        "router_no_trade",
        "same_side_skips",
    )
    scenarios: dict[str, Any] = {}
    for name, scenario in payload["scenarios"].items():
        scenarios[name] = {
            "cycle": {k: scenario["cycle"].get(k) for k in keep},
            "broker_calls": scenario["broker_calls"],
            "positions": [
                {k: p.get(k) for k in ("symbol", "side", "quantity", "notional_usdt")}
                for p in scenario["positions"]
            ],
            "closed_trades": [
                {k: t.get(k) for k in ("symbol", "side", "pnl", "exit_reason")}
                for t in scenario["closed_trades"]
            ],
            "equity": round(float(scenario["equity"]), 9),
            "state_after": scenario["state_after"],
            "reconciliation": scenario["reconciliation_before"]["status"],
            "reasons": sorted(r.get("reason", "") for r in scenario["cycle"].get("rejections", [])),
        }
    return scenarios


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any = None) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def verify(payload: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    scenarios = payload["scenarios"]
    summary = payload["summary"]

    _check(
        checks,
        "PAPER_ONLY",
        payload["execution_class"] == "PAPER_ONLY_SYNTHETIC_FIXTURE"
        and payload["live"] is False
        and payload["credentials_used"] is False
        and payload["order_sent"] is False,
        {
            "execution_class": payload["execution_class"],
            "live": payload["live"],
            "credentials_used": payload["credentials_used"],
            "order_sent": payload["order_sent"],
        },
    )
    _check(
        checks,
        "CONTROLLED_LEDGER_LABELLED",
        "CONTROLLED_TEST_FIXTURE" in payload["ledger_claim"]
        and "not a production admission" in payload["ledger_claim"],
        payload["ledger_claim"],
    )

    trade = scenarios["trade"]
    trade_identity = all(trade["accounting"]["identities"].values())
    _check(
        checks,
        "TRADE_ONE_ORDER_ONE_POSITION",
        trade["cycle"].get("orders_created") == 1
        and trade["status"]["last_session_metrics"].get("fills_opened") == 1
        and len(trade["positions"]) == 1
        and trade["broker_calls"] == {"execute_signal": 1, "close_position": 0}
        and trade["state_bytes"] > 0
        and trade["state_after"]["open_positions"] == 1
        and trade["state_after"]["sent_intents"] == 1
        and trade_identity,
        {
            "cycle": trade["cycle"],
            "positions": len(trade["positions"]),
            "calls": trade["broker_calls"],
            "state": trade["state_after"],
            "identities": trade["accounting"]["identities"],
        },
    )

    restart = scenarios["restart"]
    before = restart["reconciliation_before"]
    closed = restart["closed_trades"]
    _check(
        checks,
        "RESTART_RECOVERS_AND_RECONCILES",
        before["status"] == "RECOVERED"
        and before["restored_open_positions"] == 1
        and before["restored_intents"] == 1
        and len(restart["positions_after_reconcile"]) == 1
        and restart["cycle"].get("orders_created") == 0
        and restart["cycle"].get("same_side_skips") == 1
        and restart["broker_calls"]["execute_signal"] == 0
        and len(closed) == 1
        and closed[0]["exit_reason"] == "take_profit"
        and closed[0]["position_id"] == restart["positions_after_reconcile"][0]["position_id"]
        and restart["realized_pnl_matches_equity"] is True
        and restart["state_after"]["open_positions"] == 0
        and restart["state_after"]["closed_trades"] == 1
        and all(restart["accounting"]["identities"].values()),
        {
            "before": before,
            "cycle": restart["cycle"],
            "closed": closed,
            "state": restart["state_after"],
        },
    )

    no_trade = scenarios["no_trade"]
    _check(
        checks,
        "NO_TRADE_ZERO_ORDERS",
        no_trade["cycle"].get("orders_created") == 0
        and no_trade["cycle"].get("signals_generated") == 0
        and no_trade["broker_calls"]["execute_signal"] == 0
        and any(
            r.get("reason") == "no_alpha_in_direction:ANY"
            for r in no_trade["cycle"].get("rejections", [])
        ),
        {"cycle": no_trade["cycle"]},
    )

    stale = scenarios["stale"]
    _check(
        checks,
        "STALE_ZERO_ORDERS",
        stale["cycle"].get("orders_created") == 0
        and stale["cycle"].get("router_no_trade") == 1
        and stale["broker_calls"]["execute_signal"] == 0
        and any(
            r.get("reason") == "NO_TRADE:stale_context"
            for r in stale["cycle"].get("rejections", [])
        ),
        {"cycle": stale["cycle"]},
    )

    stopped = scenarios["kill_switch"]
    _check(
        checks,
        "KILL_SWITCH_ZERO_BROKER_CALLS",
        stopped["cycle"].get("orders_created") == 0
        and stopped["cycle"].get("hot_stop_blocked") == 1
        and stopped["cycle"].get("risk_accepted") == 1
        and stopped["broker_calls"] == {"execute_signal": 0, "close_position": 0}
        and any(
            r.get("stage") == "hot_stop" and "kill_switch_active" in r.get("reason", "")
            for r in stopped["cycle"].get("rejections", [])
        ),
        {"cycle": stopped["cycle"], "calls": stopped["broker_calls"]},
    )

    failed = scenarios["provider_exception"]
    _check(
        checks,
        "PROVIDER_EXCEPTION_ZERO_ORDERS",
        failed["cycle"].get("orders_created") == 0
        and failed["broker_calls"]["execute_signal"] == 0
        and failed["status"]["last_session_metrics"].get("scanner_errors") == 1
        and failed["status"]["last_session_metrics"].get("total_snapshots") == 0,
        {
            "cycle": failed["cycle"],
            "metrics": failed["status"]["last_session_metrics"],
        },
    )

    _check(
        checks,
        "SUMMARY_MATCHES_SCENARIOS",
        summary["trade_orders"] == trade["cycle"].get("orders_created")
        and summary["restart_closed_trades"] == len(closed)
        and summary["no_trade_orders"] == no_trade["cycle"].get("orders_created")
        and summary["stale_orders"] == stale["cycle"].get("orders_created")
        and summary["kill_switch_orders"] == stopped["cycle"].get("orders_created")
        and summary["exception_orders"] == failed["cycle"].get("orders_created"),
        summary,
    )

    _check(
        checks,
        "NO_ORDER_CLAIMED_WITH_ZERO_BROKER_CALL",
        all(
            not (scenario["cycle"].get("orders_created", 0) > 0)
            or scenario["broker_calls"]["execute_signal"] > 0
            for scenario in scenarios.values()
        ),
        {name: s["broker_calls"] for name, s in scenarios.items()},
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-5 independent verification.")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/audit/runs/g5-paper-e2e/verification.json"),
    )
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="g5-verify-"))
    checks: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    verdict = "G5_NOT_VERIFIED"
    resolved = _run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", args.rev],
        cwd=REPO_ROOT,
        env=dict(os.environ),
    )
    resolved_rev = resolved.stdout.strip() if resolved.returncode == 0 else args.rev
    try:
        tree = _export(args.rev, tmp)
        hot_stop = tree / "src/trading_bot/autonomous/hot_stop.py"
        hot_stop_hash = hashlib.sha256(hot_stop.read_bytes()).hexdigest()
        _check(
            checks,
            "HOT_STOP_UNCHANGED",
            hot_stop_hash == HOT_STOP_SHA256,
            {"sha256": hot_stop_hash, "expected": HOT_STOP_SHA256},
        )

        first, first_meta = _evidence(tree, tmp / "run1", run_label="first")
        second, second_meta = _evidence(tree, tmp / "run2", run_label="second")
        runs = [first_meta, second_meta]
        for check in verify(first):
            checks.append(check)
        _check(
            checks,
            "DETERMINISTIC_REPLAY",
            _projection(first) == _projection(second),
            {
                "first_sha256": first.get("evidence_sha256"),
                "second_sha256": second.get("evidence_sha256"),
                "note": "session ids and timestamps are excluded; counters and economic results must match",
            },
        )
        passed = [c for c in checks if c["passed"]]
        verdict = "G5_VERIFIED" if len(passed) == len(checks) else "G5_NOT_VERIFIED"
        payload = {
            "schema_version": "g5-verification/v1",
            "verdict": verdict,
            "requested_rev": args.rev,
            "rev": resolved_rev,
            "export_tree": str(tree),
            "checks": checks,
            "checks_passed": len(passed),
            "checks_total": len(checks),
            "false_success": 0 if verdict == "G5_VERIFIED" else None,
            "runs": runs,
            "seconds": round(time.time() - started, 2),
        }
    except Exception as exc:
        payload = {
            "schema_version": "g5-verification/v1",
            "verdict": "G5_NOT_VERIFIED",
            "requested_rev": args.rev,
            "rev": resolved_rev,
            "checks": checks,
            "checks_passed": sum(1 for c in checks if c["passed"]),
            "checks_total": len(checks),
            "error": f"{type(exc).__name__}: {exc}",
            "runs": runs,
            "seconds": round(time.time() - started, 2),
        }
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": payload["checks_total"]}, indent=2))
    print(f"verification written to {out}")
    return 0 if payload["verdict"] == "G5_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
