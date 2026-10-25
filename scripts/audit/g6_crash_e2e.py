"""G-6 — real forced-termination matrix for the PAPER runtime.

Each crash scenario starts ``g6_crash_worker.py`` in a separate process.  The
worker parks at a durable boundary; this driver kills that exact PID with
``taskkill /F`` (Windows) or ``SIGKILL`` (POSIX), then starts a NEW process over
the same state file.  No exception injection, no object recreation and no
graceful ``finally`` path is used to simulate the crash.

PAPER_ONLY.  Market data and clock are controlled fixtures; the decision path,
risk manager, durable broker, state store and startup reconciler are the
repository's own components.  No exchange client or credential is created.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

WORKER_REL = Path("scripts/audit/g6_crash_worker.py")
DEFAULT_LEDGER = REPO_ROOT / "docs" / "audit" / "fixtures" / "g6_paper_ledger.json"


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "sha256": None,
            "bytes": 0,
            "open_positions": 0,
            "closed_trades": 0,
            "sent_intents": 0,
            "orders": [],
            "order_statuses": [],
            "equity": 0.0,
            "equity_identity": True,
        }
    raw = path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "exists": True,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "parse_error": f"{type(exc).__name__}: {exc}",
        }
    broker = dict(doc.get("broker_state", {}) or {})
    closed = [dict(row) for row in doc.get("closed_trades", [])]
    orders = [dict(row) for row in doc.get("orders", [])]
    initial = float(broker.get("initial_equity", 0.0) or 0.0)
    realized = sum(float(row.get("pnl", 0.0) or 0.0) for row in closed)
    equity = float(broker.get("equity", 0.0) or 0.0)
    return {
        "exists": True,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "open_positions": len(doc.get("open_positions", []) or []),
        "closed_trades": len(closed),
        "sent_intents": len(doc.get("sent_intents", []) or []),
        "orders": orders,
        "order_statuses": [str(row.get("status", "")) for row in orders],
        "equity": equity,
        "initial_equity": initial,
        "realized_pnl": realized,
        "equity_identity": abs(equity - (initial + realized)) <= 1e-9,
        "run_id": doc.get("run_id", ""),
        "updated_at_ms": doc.get("updated_at_ms", 0),
    }


def _read_result(log_path: Path) -> dict[str, Any] | None:
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if line.startswith("WORKER_RESULT "):
            try:
                return json.loads(line[len("WORKER_RESULT ") :])
            except json.JSONDecodeError:
                return None
    return None


def _kill(pid: int) -> dict[str, Any]:
    if os.name == "nt":
        command = ["taskkill", "/F", "/T", "/PID", str(pid)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return {
            "method": "taskkill /F /T",
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    os.kill(pid, signal.SIGKILL)
    return {"method": "SIGKILL", "command": ["kill", "-9", str(pid)], "exit_code": 0}


def _spawn(
    *,
    state: Path,
    run_dir: Path,
    crash_at: str | None = None,
    marker: Path | None = None,
    bars: str = "rising",
    offset_bars: int = 0,
    kill_switch: bool = False,
    ledger: Path = DEFAULT_LEDGER,
    wait_for_marker: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    state.parent.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"worker-{time.time_ns()}.log"
    if marker is not None and marker.exists():
        marker.unlink()
    command = [
        sys.executable,
        str(REPO_ROOT / WORKER_REL),
        "--state",
        str(state),
        "--run-dir",
        str(run_dir),
        "--ledger",
        str(ledger),
        "--bars",
        bars,
        "--clock-offset-bars",
        str(offset_bars),
    ]
    if crash_at:
        command += ["--crash-at", crash_at]
    if marker is not None:
        command += ["--marker", str(marker)]
    if kill_switch:
        command += ["--kill-switch"]
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PAPER_CRASH_POINT", None)
    env.pop("PAPER_CRASH_MARKER", None)
    started = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        marker_payload: dict[str, Any] | None = None
        kill: dict[str, Any] | None = None
        if wait_for_marker:
            assert marker is not None
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if marker.exists():
                    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.02)
            if marker_payload is None:
                if proc.poll() is None:
                    kill = _kill(proc.pid)
                proc.wait(timeout=10)
                raise RuntimeError(
                    f"worker never reached {crash_at!r} (exit {proc.returncode}): "
                    f"{log_path.read_text(encoding='utf-8', errors='replace')[-1500:]}"
                )
            # Windows venv ``python.exe`` is a launcher: ``Popen.pid`` is the
            # wrapper and the interpreter's ``os.getpid()`` is its child.  The
            # marker carries the real worker PID; the forced kill targets the
            # wrapper's TREE, so both die.  Keep both identities in the record.
            kill = _kill(proc.pid)
            worker_pid = marker_payload.get("pid")
            if isinstance(worker_pid, int) and worker_pid != proc.pid:
                kill["worker_pid"] = worker_pid
        proc.wait(timeout=timeout)
    elapsed = round(time.monotonic() - started, 3)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "pid": proc.pid,
        "worker_pid": None if marker_payload is None else marker_payload.get("pid"),
        "returncode": proc.returncode,
        "seconds": elapsed,
        "command": command,
        "log": str(log_path),
        "log_sha256": _sha256(log_path),
        "stdout_tail": text[-3000:],
        "marker": marker_payload,
        "kill": kill,
        "terminated_by_forced_kill": bool(
            kill is not None and kill.get("exit_code") == 0 and proc.returncode != 0
        ),
        "result": _read_result(log_path),
    }


def _copy_state(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _crash_scenario(
    *,
    name: str,
    out_dir: Path,
    point: str,
    ledger: Path,
) -> tuple[dict[str, Any], Path]:
    base = out_dir / "scenarios" / name
    state = base / "paper_state.json"
    run_dir = base / "crash-run"
    marker = base / "crash.marker.json"
    crash = _spawn(
        state=state,
        run_dir=run_dir,
        crash_at=point,
        marker=marker,
        ledger=ledger,
        wait_for_marker=True,
    )
    return crash, state


def _restart(
    *,
    state: Path,
    run_dir: Path,
    bars: str = "rising",
    offset_bars: int = 0,
    kill_switch: bool = False,
    ledger: Path,
) -> dict[str, Any]:
    return _spawn(
        state=state,
        run_dir=run_dir,
        bars=bars,
        offset_bars=offset_bars,
        kill_switch=kill_switch,
        ledger=ledger,
    )


def run_matrix(out_dir: Path, ledger: Path = DEFAULT_LEDGER) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios: dict[str, Any] = {}

    # 1. Crash before the intent is durable: nothing should exist.
    crash, state = _crash_scenario(
        name="before_intent", out_dir=out_dir, point="before_intent_persist", ledger=ledger
    )
    crash_state = _state_summary(state)
    restart = _restart(
        state=state,
        run_dir=out_dir / "scenarios/before_intent/restart-run",
        ledger=ledger,
    )
    scenarios["before_intent"] = {
        "crash": crash,
        "state_after_crash": crash_state,
        "restart": restart,
        "state_after_restart": _state_summary(state),
    }

    # 2. Crash after the intent is durable, before the broker is called.
    crash, state = _crash_scenario(
        name="after_intent",
        out_dir=out_dir,
        point="after_intent_persist_before_order",
        ledger=ledger,
    )
    crash_state = _state_summary(state)
    restart = _restart(
        state=state,
        run_dir=out_dir / "scenarios/after_intent/restart-run",
        ledger=ledger,
    )
    scenarios["after_intent"] = {
        "crash": crash,
        "state_after_crash": crash_state,
        "restart": restart,
        "state_after_restart": _state_summary(state),
    }

    # 3. Crash after the fill is recorded, before accounting is persisted.
    crash, state = _crash_scenario(
        name="after_order",
        out_dir=out_dir,
        point="after_order_record_before_accounting",
        ledger=ledger,
    )
    crash_state = _state_summary(state)
    restart = _restart(
        state=state,
        run_dir=out_dir / "scenarios/after_order/restart-run",
        ledger=ledger,
    )
    scenarios["after_order"] = {
        "crash": crash,
        "state_after_crash": crash_state,
        "restart": restart,
        "state_after_restart": _state_summary(state),
    }

    # 4. Crash after the durable economic commit, before cycle confirmation.
    crash, state = _crash_scenario(
        name="after_accounting",
        out_dir=out_dir,
        point="after_accounting_commit_before_cycle",
        ledger=ledger,
    )
    crash_state = _state_summary(state)
    restart = _restart(
        state=state,
        run_dir=out_dir / "scenarios/after_accounting/restart-run",
        ledger=ledger,
    )
    scenarios["after_accounting"] = {
        "crash": crash,
        "state_after_crash": crash_state,
        "restart": restart,
        "state_after_restart": _state_summary(state),
    }

    # 5. Two consecutive restarts over the same committed ledger.
    two_state = out_dir / "scenarios/two_restarts/paper_state.json"
    _copy_state(state, two_state)
    first = _restart(
        state=two_state,
        run_dir=out_dir / "scenarios/two_restarts/restart-1",
        ledger=ledger,
    )
    state_after_first = _state_summary(two_state)
    second = _restart(
        state=two_state,
        run_dir=out_dir / "scenarios/two_restarts/restart-2",
        ledger=ledger,
    )
    scenarios["two_restarts"] = {
        "source": "after_accounting/paper_state.json",
        "restart_1": first,
        "state_after_restart_1": state_after_first,
        "restart_2": second,
        "state_after_restart_2": _state_summary(two_state),
    }

    # 6. Inconsistent persistence: ACCOUNTED order without its position.
    inconsistent_state = out_dir / "scenarios/inconsistent/paper_state.json"
    _copy_state(state, inconsistent_state)
    doc = json.loads(inconsistent_state.read_text(encoding="utf-8"))
    doc["open_positions"] = []
    inconsistent_state.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    inconsistent = _restart(
        state=inconsistent_state,
        run_dir=out_dir / "scenarios/inconsistent/restart-run",
        ledger=ledger,
    )
    scenarios["inconsistent"] = {
        "tamper": "ACCOUNTED order retained, open_positions removed",
        "restart": inconsistent,
        "state_after_restart": _state_summary(inconsistent_state),
    }

    # 7. Incomplete persistence: truncated JSON must fail closed.
    corrupt_state = out_dir / "scenarios/corrupt/paper_state.json"
    corrupt_state.parent.mkdir(parents=True, exist_ok=True)
    corrupt_state.write_bytes(b'{"schema_version":1,"broker_state":')
    corrupt = _restart(
        state=corrupt_state,
        run_dir=out_dir / "scenarios/corrupt/restart-run",
        ledger=ledger,
    )
    scenarios["corrupt"] = {
        "restart": corrupt,
        "state_after_restart": _state_summary(corrupt_state),
        "corrupt_backup_exists": corrupt_state.with_suffix(
            corrupt_state.suffix + ".corrupt"
        ).exists(),
    }

    # 8. A recovered position must still be closable exactly once.
    close_state = out_dir / "scenarios/recovery_close/paper_state.json"
    _copy_state(state, close_state)
    close = _restart(
        state=close_state,
        run_dir=out_dir / "scenarios/recovery_close/restart-run",
        bars="spike",
        offset_bars=1,
        ledger=ledger,
    )
    scenarios["recovery_close"] = {
        "source": "after_accounting/paper_state.json",
        "restart": close,
        "state_after_restart": _state_summary(close_state),
    }

    # 9. Kill switch engaged during recovery.  Start from the closed book so a
    # NEW bar produces a new intent; the stop must block it before the broker.
    killed_state = out_dir / "scenarios/kill_switch/paper_state.json"
    _copy_state(close_state, killed_state)
    kill_switch = _restart(
        state=killed_state,
        run_dir=out_dir / "scenarios/kill_switch/restart-run",
        offset_bars=2,
        kill_switch=True,
        ledger=ledger,
    )
    scenarios["kill_switch"] = {
        "source": "recovery_close/paper_state.json",
        "restart": kill_switch,
        "state_after_restart": _state_summary(killed_state),
    }

    payload = {
        "schema_version": "g6-crash-evidence/v1",
        "generated_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "execution_class": "PAPER_ONLY_SYNTHETIC_FIXTURE",
        "live": False,
        "credentials_used": False,
        "exchange_clients_constructed": False,
        "order_sent": False,
        "platform": platform.platform(),
        "python": sys.version,
        "ledger": str(ledger),
        "ledger_claim": (
            "CONTROLLED_TEST_FIXTURE — not market evidence, not a production admission"
        ),
        "worker_sha256": _sha256(REPO_ROOT / WORKER_REL),
        "scenarios": scenarios,
        "summary": {
            "forced_kills": sum(
                1
                for scenario in scenarios.values()
                if scenario.get("crash", {}).get("terminated_by_forced_kill")
            ),
            "recovery_orders": {
                name: ((scenario.get("restart") or {}).get("result") or {})
                .get("cycle", {})
                .get("orders_created", 0)
                for name, scenario in scenarios.items()
                if "restart" in scenario
            },
        },
    }
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-6 PAPER crash matrix.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/audit/runs/g6-crash-recovery"),
    )
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    payload = run_matrix(out_dir, Path(args.ledger))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evidence.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2, default=str))
    print(f"evidence written to {out_dir / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
