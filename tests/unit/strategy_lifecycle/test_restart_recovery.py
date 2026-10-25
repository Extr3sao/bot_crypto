"""Real-process restart recovery — GATE STRAT-PERSIST-003 §17.

Persistence and recovery happen in **different OS processes** (via
`_restart_child.py`), which is what makes this restart evidence and not an
in-memory round-trip. Covers clean shutdown, abrupt shutdown, and no promotion on
recovery.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHILD = Path(__file__).with_name("_restart_child.py")


def _run(mode: str, path: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CHILD), mode, str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"child {mode} failed: {proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_real_process_restart_preserves_every_state(tmp_path: Path) -> None:
    state = tmp_path / "lifecycle_state.json"
    before = _run("save", state)
    after = _run("load", state)

    assert before["state_hash"] == after["state_hash"]
    assert before["states"] == after["states"]
    assert before["active"] == after["active"] == ["s-active"]
    # Mixed lifecycle states survive exactly.
    assert after["states"] == {
        "s-shadow": "SHADOW",
        "s-eligible": "ELIGIBLE",
        "s-active": "ACTIVE",
        "s-degraded": "DEGRADED",
        "s-throttled": "THROTTLED",
        "s-paused": "PAUSED",
        "s-retired": "RETIRED",
    }


def test_no_promotion_because_of_restart(tmp_path: Path) -> None:
    state = tmp_path / "s.json"
    _run("save", state)
    after = _run("load", state)
    assert after["active"] == ["s-active"]  # nothing new became ACTIVE
    assert after["states"]["s-shadow"] == "SHADOW"


def test_abrupt_shutdown_then_restart(tmp_path: Path) -> None:
    state = tmp_path / "s.json"
    before = _run("save-abrupt", state)
    after = _run("load", state)
    assert before["state_hash"] == after["state_hash"]
    assert after["states"]["s-active"] == "ACTIVE"
    assert after["states"]["s-throttled"] == "THROTTLED"
