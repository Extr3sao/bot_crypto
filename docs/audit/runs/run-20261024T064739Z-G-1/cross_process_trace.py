"""G-1 trace — two operating-system processes, one marker, no order.

This is the human-readable reproduction of ACC-G1-05. It does not import the
test suite: it drives the two entrypoints an operator would use.

    1. ``python -m trading_bot.app kill-switch --run-dir <A> --engage``
       (a short-lived process; exits 0 meaning "request on disk", not "stopped")
    2. ``python scripts/audit/g1_restart_probe.py --run-dir <A>``
       (a new interpreter that boots the real runtime over that directory)

and the control: the same probe over a sibling directory with no marker, which
must reach the broker exactly once. Without that control a broken probe would
look like a working stop.

Usage::

    python docs/audit/runs/run-20261024T064739Z-G-1/cross_process_trace.py \
        --out docs/audit/runs/run-20261024T064739Z-G-1/cross_process_trace.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate
    return here.parents[4]


REPO_ROOT = _repo_root()


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=_env(), capture_output=True, text=True, timeout=300
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="write the trace as JSON")
    args = parser.parse_args(argv)

    rev = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="g1-trace-") as raw:
        root = Path(raw)
        blocked_dir = root / "run-blocked"
        control_dir = root / "run-control"
        blocked_dir.mkdir()
        control_dir.mkdir()

        cli = _run(
            [
                sys.executable,
                "-m",
                "trading_bot.app",
                "kill-switch",
                "--run-dir",
                str(blocked_dir),
                "--engage",
                "--reason",
                "operator: trace",
            ]
        )
        probes: dict[str, Any] = {}
        for label, run_dir in (("blocked", blocked_dir), ("control", control_dir)):
            completed = _run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "audit" / "g1_restart_probe.py"),
                    "--run-dir",
                    str(run_dir),
                ]
            )
            if completed.returncode != 0:
                print(completed.stderr[-800:], file=sys.stderr)
                return 1
            probes[label] = json.loads(completed.stdout)

        events_path = blocked_dir / "kill_switch_events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    payload = {
        "checkout": str(REPO_ROOT),
        "rev": rev,
        "process_1_cli": {
            "exit": cli.returncode,
            "stdout": json.loads(cli.stdout) if cli.stdout.strip() else None,
            "stderr": cli.stderr[-400:],
        },
        "process_2_blocked": probes["blocked"],
        "process_2_control": probes["control"],
        "events": events,
        "assertions": {
            "blocked_broker_calls_is_zero": probes["blocked"]["broker_calls"] == 0,
            "blocked_restored_before_cycle": probes["blocked"]["engaged_before_first_cycle"]
            is True,
            "control_broker_calls_is_one": probes["control"]["broker_calls"] == 1,
            "event_is_restored": bool(events) and events[0]["event"] == "restored",
            "cli_did_not_claim_enforcement": (
                (json.loads(cli.stdout).get("enforced") is False) if cli.stdout.strip() else False
            ),
        },
    }
    ok = all(payload["assertions"].values())
    payload["ok"] = ok
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"trace written to {args.out}")
    print(json.dumps(payload["assertions"], indent=2))
    print(
        f"blocked broker_calls={probes['blocked']['broker_calls']} "
        f"control broker_calls={probes['control']['broker_calls']} ok={ok}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
