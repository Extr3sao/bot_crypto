"""isolation_lab — the adversarial battery for RFC-PAPER-ISOLATION-005.

Each scenario runs in a **new process** that installs the paper policy before it builds
anything, and each one tries to do the thing the policy forbids. The lab's job is not to
say "the guard exists"; it is to make the guard fail if it is wrong, and to keep the
subprocess residual visible as a limitation rather than folding it into a PASS.

    python scripts/isolation_lab.py --out reports/.../lab --json reports/.../LAB.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "scripts" / "isolation_child.py"

RUNTIME_FILES = (
    "src/trading_bot/execution/isolation.py",
    "src/trading_bot/execution/__init__.py",
    "src/trading_bot/market_data/exchange_connector.py",
    "src/trading_bot/market_data/bitunix.py",
    "src/trading_bot/market_data/bitunix_futures.py",
    "src/trading_bot/app.py",
    "scripts/ai_bots_run.py",
    "scripts/ai_vision_lane.py",
)


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _run_child(root: Path, mode: str, timeout: float = 600.0) -> dict[str, Any]:
    case = root / mode
    shutil.rmtree(case, ignore_errors=True)
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(CHILD), "--root", str(case), "--mode", mode],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    seconds = round(time.perf_counter() - started, 2)
    payload_path = case / "child.json"
    payload: dict[str, Any] = {}
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    else:
        payload = {
            "status": "NO_OUTPUT",
            "stderr": proc.stderr[-2000:],
            "stdout": proc.stdout[-2000:],
        }
    payload["returncode"] = proc.returncode
    payload["seconds"] = seconds
    #: The child's own log is the primary evidence of what it tried; keep the rows.
    log = case / "network.jsonl"
    payload["network_log"] = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        if log.exists()
        else []
    )
    return payload


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


def _verdict(checks: list[dict[str, Any]]) -> str:
    return "PASS" if all(row["ok"] for row in checks) else "FAIL"


def scenario_runtime(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    isolation = result.get("isolation") or {}
    policy = isolation.get("policy") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("exit_code", result.get("exit_code") == 0, f"exit={result.get('exit_code')}"),
        _check("report_executed", result.get("report_status") == "EXECUTED", str(result.get("report_status"))),
        _check("policy_paper", policy.get("mode") == "paper", str(policy.get("mode"))),
        _check("orders_denied", policy.get("order_routes") is False, str(policy.get("order_routes"))),
        _check("network_denied", policy.get("external_network") is False, str(policy.get("external_network"))),
        _check("no_attempts", len(child.get("network_log") or []) == 0, f"{len(child.get('network_log') or [])} attempt(s)"),
    ]


def _refused(row: dict[str, Any]) -> bool:
    return row.get("outcome") == "REFUSED" and row.get("code") == "ISO_ORDER_ROUTE"


def scenario_ccxt(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("create_refused", _refused(result.get("create") or {}), str((result.get("create") or {}).get("outcome"))),
        _check("cancel_refused", _refused(result.get("cancel") or {}), str((result.get("cancel") or {}).get("outcome"))),
        _check("venue_untouched", (result.get("venue_calls") or []) == [], str(result.get("venue_calls"))),
    ]


def scenario_futures(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("client_place_refused", _refused(result.get("client_place_order") or {}), str((result.get("client_place_order") or {}).get("outcome"))),
        _check("connector_create_refused", _refused(result.get("connector_create_order") or {}), str((result.get("connector_create_order") or {}).get("outcome"))),
        _check("connector_cancel_refused", _refused(result.get("connector_cancel_order") or {}), str((result.get("connector_cancel_order") or {}).get("outcome"))),
        _check("no_http_request", (result.get("http_requests") or 0) == 0, str(result.get("http_requests"))),
    ]


def scenario_spot(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("create_refused", _refused(result.get("create") or {}), str((result.get("create") or {}).get("outcome"))),
        _check("cancel_refused", _refused(result.get("cancel") or {}), str((result.get("cancel") or {}).get("outcome"))),
        _check("client_untouched", (result.get("client_calls") or 0) == 0, str(result.get("client_calls"))),
    ]


def scenario_app(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("no_confirm_exit", result.get("exit_without_confirm") == 2, str(result.get("exit_without_confirm"))),
        _check("confirm_in_paper_exit", result.get("exit_with_confirm_in_paper") == 2, str(result.get("exit_with_confirm_in_paper"))),
        _check("gate_refused", _refused(result.get("gate_on_command") or {}), str((result.get("gate_on_command") or {}).get("outcome"))),
        _check("no_network", len(child.get("network_log") or []) == 0, f"{len(child.get('network_log') or [])} attempt(s)"),
    ]


def scenario_network(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    hosts = {str(row.get("host")) for row in child.get("network_log") or []}
    checks = [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
    ]
    for name in ("external_connect", "loopback_connect", "external_dns", "loopback_dns"):
        row = result.get(name) or {}
        checks.append(_check(name, row.get("outcome") == "DENIED", str(row.get("outcome"))))
    checks.append(
        _check("host_recorded", "api.binance.com" in hosts, ", ".join(sorted(host for host in hosts if host)))
    )
    return checks


def scenario_http(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("urllib_denied", (result.get("urllib") or {}).get("outcome") == "DENIED", str((result.get("urllib") or {}).get("outcome"))),
        _check("http_client_denied", (result.get("http_client") or {}).get("outcome") == "DENIED", str((result.get("http_client") or {}).get("outcome"))),
    ]


def scenario_ccxt_constructor(child: dict[str, Any]) -> list[dict[str, Any]]:
    constructor = (child.get("result") or {}).get("constructor") or {}
    outcome = constructor.get("outcome")
    fetch = (constructor.get("fetch_after_construction") or {}).get("outcome")
    checks = [_check("ran", child.get("status") == "RAN", str(child.get("status")))]
    if outcome == "DENIED":
        checks.append(_check("constructor_denied", True, "the constructor itself was refused"))
    elif outcome == "CONSTRUCTED":
        #: This ccxt version does not open the session in the constructor; the incident is
        #: then reproduced by the first call, and that call is what must be refused.
        checks.append(
            _check(
                "no_io_survives_construction",
                fetch == "DENIED",
                f"constructed without I/O; first call={fetch}",
            )
        )
    else:
        checks.append(_check("constructor_classified", False, str(constructor)[:160]))
    return checks


def scenario_disarm(child: dict[str, Any]) -> list[dict[str, Any]]:
    result = child.get("result") or {}
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("denied_before", (result.get("before") or {}).get("outcome") == "DENIED", str((result.get("before") or {}).get("outcome"))),
        _check("denied_after_env_flip", (result.get("after_env_flip") or {}).get("outcome") == "DENIED", str((result.get("after_env_flip") or {}).get("outcome"))),
        _check("reinstall_refused", (result.get("reinstall_live") or {}).get("outcome") == "REFUSED", str((result.get("reinstall_live") or {}).get("outcome"))),
        _check("policy_mutation_refused", (result.get("mutated_policy") or {}).get("outcome") == "REFUSED", str((result.get("mutated_policy") or {}).get("outcome"))),
    ]


def scenario_subprocess(child: dict[str, Any]) -> list[dict[str, Any]]:
    """A limitation, by construction: the child proves the hook does not cross processes."""
    result = child.get("result") or {}
    parent_denied = (result.get("parent_attempt") or {}).get("outcome") == "DENIED"
    child_attempted = "ATTEMPTED" in str(result.get("child_output"))
    return [
        _check("ran", child.get("status") == "RAN", str(child.get("status"))),
        _check("parent_denied", parent_denied, str((result.get("parent_attempt") or {}).get("outcome"))),
        _check(
            "child_leaves_the_barrier",
            child_attempted,
            f"child={result.get('child_output')!r}: the hook is per process, not an OS sandbox",
        ),
    ]


SCENARIOS: tuple[tuple[str, str, str, Any], ...] = (
    (
        "ISO-00",
        "the paper runtime runs end to end under the policy",
        "runtime",
        scenario_runtime,
    ),
    ("ISO-01", "CCXT create/cancel refused before the venue object is used", "order-ccxt", scenario_ccxt),
    ("ISO-02", "Bitunix futures client and connector refuse before HTTP", "order-futures", scenario_futures),
    ("ISO-03", "Bitunix spot connector refuses before its client", "order-spot", scenario_spot),
    ("ISO-04", "the documented live CLI route refuses in a paper process", "app-route", scenario_app),
    ("ISO-05", "external connect and DNS are denied and recorded", "network", scenario_network),
    ("ISO-06", "urllib and http.client are denied by the same hook", "network", scenario_http),
    ("ISO-07", "a ccxt venue client cannot complete a call under the policy", "ccxt-constructor", scenario_ccxt_constructor),
    ("ISO-08", "environment and re-installation cannot weaken the policy", "disarm", scenario_disarm),
    ("ISO-09", "a child process is outside the hook: declared limitation", "subprocess", scenario_subprocess),
)

#: Scenario ids whose result is a limitation by design, never a PASS.
LIMITATIONS = {"ISO-09"}


def _hash_runtime() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in RUNTIME_FILES:
        path = REPO / relative
        if path.exists():
            hashes[relative] = _sha(path)
    return hashes


def run(out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "cases", ignore_errors=True)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    for scenario_id, claim, mode, evaluate in SCENARIOS:
        child = _run_child(out / "cases" / mode, mode)
        checks = evaluate(child)
        verdict = _verdict(checks)
        if scenario_id in LIMITATIONS and verdict == "PASS":
            verdict = "LIMITATION"
        children.append(
            {
                "id": scenario_id,
                "mode": mode,
                "status": child.get("status"),
                "returncode": child.get("returncode"),
                "seconds": child.get("seconds"),
                "denied": child.get("denied"),
                "attempts": child.get("attempts") or [],
            }
        )
        rows.append(
            {
                "id": scenario_id,
                "claim": claim,
                "mode": mode,
                "verdict": verdict,
                "checks": checks,
                "observed": child.get("result") or {},
                "child_status": child.get("status"),
                "child_returncode": child.get("returncode"),
                "child_seconds": child.get("seconds"),
                "denied": child.get("denied"),
                "network_log": child.get("network_log") or [],
            }
        )
        print(f"{scenario_id}  {verdict:10} {claim}")
    passed = sum(1 for row in rows if row["verdict"] == "PASS")
    limited = sum(1 for row in rows if row["verdict"] == "LIMITATION")
    failed = sum(1 for row in rows if row["verdict"] == "FAIL")
    payload = {
        "schema": "rfc005-isolation-lab/1",
        "run_id": f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}",
        "generated_at_utc": _utc_now(),
        "source_commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "environment": {
            "os_name": os.name,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": platform.node(),
        },
        "os_sandbox": "NOT_AVAILABLE",
        "residual": (
            "the audit hook lives inside one Python process; a child process, a native "
            "extension or a direct syscall is outside it. ISO-09 measures that boundary "
            "instead of assuming it away."
        ),
        "filesystem_hashes": _hash_runtime(),
        "counts": {"total": len(rows), "passed": passed, "limitations": limited, "failed": failed},
        "scenarios": rows,
        "children": children,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    (out / "ISOLATION_LAB.json").write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="RFC005 isolation battery.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    payload = run(out)
    target = Path(args.json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    counts = payload["counts"]
    print(
        f"{counts['passed']} PASS / {counts['limitations']} LIMITATION / {counts['failed']} FAIL "
        f"in {payload['elapsed_s']}s"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
