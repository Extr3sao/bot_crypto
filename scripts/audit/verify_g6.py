"""G-6 independent verifier — re-run the REAL crash matrix from a clean export.

The verifier is deliberately separate from the evidence scripts.  It exports
the requested commit with ``git archive``, runs the crash matrix twice inside
that export (starting real child processes and force-killing them), and
re-derives every acceptance property from the resulting JSON.

It does not import the working tree's implementation to answer its own checks.
PROCEDURALLY SEPARATED, not a second person.
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
EVIDENCE_REL = Path("scripts/audit/g6_crash_e2e.py")
HOT_STOP_SHA256 = "76cfca23d1e7758607c466eea4ff5c0a9411cb812d433eb7ca16dfb45cfdf8b1"
G5_CODE_COMMIT = "05b361f7bd26a4fb9d470d9ba5c68d7f967846c9"
G5_EVIDENCE_COMMIT = "12267039"


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


def _evidence(tree: Path, out: Path, *, run_label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{tree / 'src'}{os.pathsep}{tree}"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PAPER_CRASH_POINT", None)
    env.pop("PAPER_CRASH_MARKER", None)
    started = time.time()
    completed = _run(
        [
            sys.executable,
            str(tree / EVIDENCE_REL),
            "--out",
            str(out),
            "--ledger",
            str(tree / "docs/audit/fixtures/g6_paper_ledger.json"),
        ],
        cwd=tree,
        env=env,
    )
    elapsed = round(time.time() - started, 2)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{run_label} evidence command exited {completed.returncode}: "
            f"{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}"
        )
    payload = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    return payload, {
        "run": run_label,
        "exit_code": completed.returncode,
        "seconds": elapsed,
        "stdout_tail": completed.stdout[-800:],
        "stderr_tail": completed.stderr[-800:],
    }


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any = None) -> None:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def _safe(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _result(scenario: dict[str, Any], key: str = "restart") -> dict[str, Any]:
    return _safe(scenario, key, "result", default={}) or {}


def _state(scenario: dict[str, Any], key: str) -> dict[str, Any]:
    return _safe(scenario, key, default={}) or {}


def _projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Volatile-free projection that must match across the two runs."""

    keep_cycle = (
        "orders_created",
        "duplicate_intents",
        "hot_stop_blocked",
        "risk_accepted",
        "same_side_skips",
        "signals_generated",
    )
    keep_state = (
        "exists",
        "open_positions",
        "closed_trades",
        "sent_intents",
        "order_statuses",
        "equity_identity",
    )
    scenarios: dict[str, Any] = {}
    for name, scenario in payload.get("scenarios", {}).items():
        row: dict[str, Any] = {}
        if "crash" in scenario:
            crash = scenario["crash"]
            row["crash"] = {
                "point": _safe(crash, "marker", "point"),
                "forced": crash.get("terminated_by_forced_kill"),
                "nonzero": crash.get("returncode") not in (0, None),
            }
            row["state_after_crash"] = {
                key: _safe(scenario, "state_after_crash", key) for key in keep_state
            }
        for key in ("restart", "restart_1", "restart_2"):
            if key not in scenario:
                continue
            result = _result(scenario, key)
            row[key] = {
                "reconciliation": _safe(result, "reconciliation", "status"),
                "materialized": _safe(result, "reconciliation", "materialized_orders"),
                "blocked": len(_safe(result, "reconciliation", "blocked_intents", default=[])),
                "cycle": {field: _safe(result, "cycle", field) for field in keep_cycle},
                "positions": len(result.get("positions", []) or []),
                "closed": len(result.get("closed_trades", []) or []),
                "identities": tuple(
                    sorted((_safe(result, "accounting", "identities", default={}) or {}).items())
                ),
            }
            state_key = "state_after_restart" if key == "restart" else f"state_after_{key}"
            row[state_key] = {field: _safe(scenario, state_key, field) for field in keep_state}
        scenarios[name] = row
    return scenarios


def _hot_stop_hash(tree: Path) -> str:
    return hashlib.sha256(
        (tree / "src/trading_bot/autonomous/hot_stop.py").read_bytes()
    ).hexdigest()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(REPO_ROOT), *args], cwd=REPO_ROOT, env=dict(os.environ))


def verify(payload: dict[str, Any], *, tree: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    scenarios = payload.get("scenarios", {})

    _check(
        checks,
        "PAPER_ONLY",
        payload.get("execution_class") == "PAPER_ONLY_SYNTHETIC_FIXTURE"
        and payload.get("live") is False
        and payload.get("credentials_used") is False
        and payload.get("order_sent") is False
        and payload.get("exchange_clients_constructed") is False,
        {
            "class": payload.get("execution_class"),
            "live": payload.get("live"),
            "credentials": payload.get("credentials_used"),
            "order_sent": payload.get("order_sent"),
            "clients": payload.get("exchange_clients_constructed"),
        },
    )
    _check(
        checks,
        "CONTROLLED_LEDGER_LABELLED",
        "CONTROLLED_TEST_FIXTURE" in payload.get("ledger_claim", "")
        and "not a production admission" in payload.get("ledger_claim", ""),
        payload.get("ledger_claim"),
    )

    expected_points = {
        "before_intent": "before_intent_persist",
        "after_intent": "after_intent_persist_before_order",
        "after_order": "after_order_record_before_accounting",
        "after_accounting": "after_accounting_commit_before_cycle",
    }
    kill_details = {}
    kill_ok = True
    for name, point in expected_points.items():
        crash = _safe(scenarios, name, "crash", default={}) or {}
        marker_point = _safe(crash, "marker", "point")
        killed = (
            marker_point == point
            and crash.get("terminated_by_forced_kill") is True
            and crash.get("returncode") not in (0, None)
            and isinstance(_safe(crash, "kill", "command"), list)
        )
        kill_ok = kill_ok and killed
        kill_details[name] = {
            "point": marker_point,
            "forced": crash.get("terminated_by_forced_kill"),
            "returncode": crash.get("returncode"),
            "kill": _safe(crash, "kill", "method"),
            "wrapper_pid": crash.get("pid"),
            "worker_pid": crash.get("worker_pid"),
        }
    _check(checks, "FOUR_REAL_FORCED_TERMINATIONS", kill_ok, kill_details)

    before = scenarios.get("before_intent", {})
    before_crash = _state(before, "state_after_crash")
    before_result = _result(before)
    _check(
        checks,
        "BEFORE_INTENT_NOTHING_DURABLE",
        before_crash.get("exists") is False
        and before_crash.get("sent_intents") == 0
        and before_crash.get("order_statuses") == []
        and _safe(before_result, "cycle", "orders_created") == 1
        and len(before_result.get("positions", []) or []) == 1,
        {
            "crash_state": before_crash,
            "restart_orders": _safe(before_result, "cycle", "orders_created"),
            "restart_positions": len(before_result.get("positions", []) or []),
        },
    )

    after_intent = scenarios.get("after_intent", {})
    intent_crash = _state(after_intent, "state_after_crash")
    intent_result = _result(after_intent)
    _check(
        checks,
        "PREPARED_INTENT_BLOCKED_NOT_RESENT",
        intent_crash.get("order_statuses") == ["PREPARED"]
        and intent_crash.get("open_positions") == 0
        and intent_crash.get("sent_intents") == 1
        and _safe(intent_result, "reconciliation", "status") == "RECOVERED"
        and _safe(intent_result, "reconciliation", "materialized_orders") == 0
        and len(_safe(intent_result, "reconciliation", "blocked_intents", default=[])) == 1
        and _safe(intent_result, "cycle", "orders_created") == 0
        and _safe(intent_result, "cycle", "duplicate_intents") == 1
        and intent_result.get("positions") == []
        and _state(after_intent, "state_after_restart").get("order_statuses")
        == ["BLOCKED_UNKNOWN"],
        {
            "crash_state": intent_crash,
            "reconciliation": _safe(intent_result, "reconciliation"),
            "cycle": _safe(intent_result, "cycle"),
            "positions": intent_result.get("positions"),
        },
    )

    after_order = scenarios.get("after_order", {})
    order_crash = _state(after_order, "state_after_crash")
    order_result = _result(after_order)
    _check(
        checks,
        "FILLED_ORDER_MATERIALIZED_ONCE",
        order_crash.get("order_statuses") == ["FILLED"]
        and order_crash.get("open_positions") == 0
        and order_crash.get("sent_intents") == 1
        and _safe(order_result, "reconciliation", "status") == "RECOVERED"
        and _safe(order_result, "reconciliation", "materialized_orders") == 1
        and _safe(order_result, "reconciliation", "recovery_persisted") is True
        and _safe(order_result, "cycle", "orders_created") == 0
        and _safe(order_result, "cycle", "duplicate_intents") == 1
        and len(order_result.get("positions", []) or []) == 1
        and _state(after_order, "state_after_restart").get("order_statuses") == ["ACCOUNTED"],
        {
            "crash_state": order_crash,
            "reconciliation": _safe(order_result, "reconciliation"),
            "cycle": _safe(order_result, "cycle"),
            "positions": order_result.get("positions"),
        },
    )

    after_accounting = scenarios.get("after_accounting", {})
    acc_crash = _state(after_accounting, "state_after_crash")
    acc_result = _result(after_accounting)
    _check(
        checks,
        "ACCOUNTED_BOOK_RESTORED_WITHOUT_NEW_ORDER",
        acc_crash.get("order_statuses") == ["ACCOUNTED"]
        and acc_crash.get("open_positions") == 1
        and acc_crash.get("sent_intents") == 1
        and _safe(acc_result, "reconciliation", "status") == "RECOVERED"
        and _safe(acc_result, "reconciliation", "materialized_orders") == 0
        and _safe(acc_result, "cycle", "orders_created") == 0
        and _safe(acc_result, "cycle", "duplicate_intents") == 1
        and len(acc_result.get("positions", []) or []) == 1,
        {
            "crash_state": acc_crash,
            "reconciliation": _safe(acc_result, "reconciliation"),
            "cycle": _safe(acc_result, "cycle"),
        },
    )

    two = scenarios.get("two_restarts", {})
    first = _result(two, "restart_1")
    second = _result(two, "restart_2")
    state_first = _state(two, "state_after_restart_1")
    state_second = _state(two, "state_after_restart_2")
    _check(
        checks,
        "TWO_RESTARTS_IDEMPOTENT",
        all(
            _safe(result, "reconciliation", "status") == "RECOVERED"
            and _safe(result, "cycle", "orders_created") == 0
            and _safe(result, "cycle", "duplicate_intents") == 1
            and len(result.get("positions", []) or []) == 1
            for result in (first, second)
        )
        and state_first.get("open_positions") == 1
        and state_second.get("open_positions") == 1
        and state_first.get("sent_intents") == 1
        and state_second.get("sent_intents") == 1
        and state_first.get("order_statuses") == ["ACCOUNTED"]
        and state_second.get("order_statuses") == ["ACCOUNTED"],
        {
            "first": _safe(first, "cycle"),
            "second": _safe(second, "cycle"),
            "state_first": state_first,
            "state_second": state_second,
        },
    )

    inconsistent = _result(scenarios.get("inconsistent", {}))
    _check(
        checks,
        "INCONSISTENT_STATE_FAILS_CLOSED",
        inconsistent.get("status") == "FATAL"
        and _safe(inconsistent, "reconciliation", "status") == "FATAL"
        and any(
            "no restored position" in detail
            for detail in _safe(inconsistent, "reconciliation", "details", default=[])
        ),
        _safe(inconsistent, "reconciliation", default={}),
    )

    corrupt_scenario = scenarios.get("corrupt", {})
    corrupt = _result(corrupt_scenario)
    _check(
        checks,
        "CORRUPT_STATE_FAILS_CLOSED",
        corrupt.get("status") == "FATAL"
        and _safe(corrupt, "reconciliation", "status") == "FATAL"
        and corrupt_scenario.get("corrupt_backup_exists") is True,
        {
            "status": corrupt.get("status"),
            "backup": corrupt_scenario.get("corrupt_backup_exists"),
            "reconciliation": _safe(corrupt, "reconciliation", "details"),
        },
    )

    stop_scenario = scenarios.get("kill_switch", {})
    stop = _result(stop_scenario)
    _check(
        checks,
        "KILL_SWITCH_DURING_RECOVERY_BLOCKS_BROKER",
        _safe(stop, "reconciliation", "status") == "RECOVERED"
        and _safe(stop, "cycle", "hot_stop_blocked") == 1
        and _safe(stop, "cycle", "orders_created") == 0
        and _safe(stop, "cycle", "risk_accepted") == 1
        and _safe(stop, "broker_calls", "execute_signal") == 0
        and any(
            rejection.get("stage") == "hot_stop"
            for rejection in _safe(stop, "cycle", "rejections", default=[])
        ),
        {"cycle": _safe(stop, "cycle"), "calls": stop.get("broker_calls")},
    )

    close_scenario = scenarios.get("recovery_close", {})
    close = _result(close_scenario)
    close_state = _state(close_scenario, "state_after_restart")
    _check(
        checks,
        "RECOVERED_POSITION_CLOSES_EXACTLY_ONCE",
        _safe(close, "reconciliation", "status") == "RECOVERED"
        and len(close.get("positions", []) or []) == 0
        and len(close.get("closed_trades", []) or []) == 1
        and close.get("closed_trades", [{}])[0].get("exit_reason") == "take_profit"
        and close_state.get("closed_trades") == 1
        and close_state.get("equity_identity") is True,
        {
            "closed": close.get("closed_trades"),
            "state": close_state,
            "identities": _safe(close, "accounting", "identities"),
        },
    )

    identity_results: dict[str, Any] = {}
    for name, scenario in scenarios.items():
        for key in ("restart", "restart_1", "restart_2"):
            identities = _safe(_result(scenario, key), "accounting", "identities", default={})
            if identities:
                identity_results[f"{name}:{key}"] = identities
    identities_ok = bool(identity_results) and all(
        len(identities) == 5 and all(bool(value) for value in identities.values())
        for identities in identity_results.values()
    )
    _check(
        checks,
        "FIVE_ACCOUNTING_IDENTITIES",
        identities_ok,
        {name: identities for name, identities in identity_results.items()},
    )

    order_claims_ok = True
    for _name, scenario in scenarios.items():
        for key in ("restart", "restart_1", "restart_2"):
            result = _result(scenario, key)
            orders = _safe(result, "cycle", "orders_created")
            calls = _safe(result, "broker_calls", "execute_signal")
            if isinstance(orders, int) and isinstance(calls, int) and orders > 0:
                order_claims_ok = order_claims_ok and calls > 0
    _check(checks, "NO_ORDER_CLAIMED_WITHOUT_BROKER_CALL", order_claims_ok)

    _check(
        checks,
        "HOT_STOP_UNCHANGED",
        _hot_stop_hash(tree) == HOT_STOP_SHA256,
        {"sha256": _hot_stop_hash(tree), "expected": HOT_STOP_SHA256},
    )

    g5_code = _git("cat-file", "-e", f"{G5_CODE_COMMIT}^{{commit}}").returncode == 0
    g5_evidence = _git("cat-file", "-e", f"{G5_EVIDENCE_COMMIT}^{{commit}}").returncode == 0
    g5_code_ancestor = _git("merge-base", "--is-ancestor", G5_CODE_COMMIT, "HEAD").returncode == 0
    g5_evidence_ancestor = (
        _git("merge-base", "--is-ancestor", G5_EVIDENCE_COMMIT, "HEAD").returncode == 0
    )
    g5_manifest = _git(
        "show",
        f"{G5_EVIDENCE_COMMIT}:docs/audit/runs/run-20261025T131004Z-G-5/EVIDENCE.sha256",
    )
    _check(
        checks,
        "G5_DEFINITIVE_COMMITS_PRESENT",
        g5_code
        and g5_evidence
        and g5_code_ancestor
        and g5_evidence_ancestor
        and g5_manifest.returncode == 0
        and len(g5_manifest.stdout.strip().splitlines()) == 33,
        {
            "g5_code_commit": G5_CODE_COMMIT,
            "g5_evidence_commit": G5_EVIDENCE_COMMIT,
            "code_present": g5_code,
            "evidence_present": g5_evidence,
            "code_ancestor": g5_code_ancestor,
            "evidence_ancestor": g5_evidence_ancestor,
            "manifest_lines": len(g5_manifest.stdout.strip().splitlines()),
        },
    )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-6 independent verification.")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/audit/runs/g6-crash-recovery/verification.json"),
    )
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="g6-verify-"))
    checks: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    verdict = "G6_NOT_VERIFIED"
    resolved = _git("rev-parse", args.rev)
    resolved_rev = resolved.stdout.strip() if resolved.returncode == 0 else args.rev
    try:
        tree = _export(args.rev, tmp)
        first, first_meta = _evidence(tree, tmp / "run1", run_label="first")
        second, second_meta = _evidence(tree, tmp / "run2", run_label="second")
        runs = [first_meta, second_meta]
        checks = verify(first, tree=tree)
        _check(
            checks,
            "DETERMINISTIC_REPLAY",
            _projection(first) == _projection(second),
            {
                "first_sha256": first.get("evidence_sha256"),
                "second_sha256": second.get("evidence_sha256"),
                "note": "pids, timestamps and hashes are excluded from the projection",
            },
        )
        passed = [check for check in checks if check["passed"]]
        verdict = "G6_VERIFIED" if len(passed) == len(checks) else "G6_NOT_VERIFIED"
        payload = {
            "schema_version": "g6-verification/v1",
            "verdict": verdict,
            "requested_rev": args.rev,
            "rev": resolved_rev,
            "checks": checks,
            "checks_passed": len(passed),
            "checks_total": len(checks),
            "false_success": 0 if verdict == "G6_VERIFIED" else None,
            "runs": runs,
            "seconds": round(time.time() - started, 2),
        }
    except Exception as exc:
        payload = {
            "schema_version": "g6-verification/v1",
            "verdict": "G6_NOT_VERIFIED",
            "requested_rev": args.rev,
            "rev": resolved_rev,
            "checks": checks,
            "checks_passed": sum(1 for check in checks if check["passed"]),
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
    return 0 if payload["verdict"] == "G6_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
