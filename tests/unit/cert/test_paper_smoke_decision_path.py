"""RUN-OP-004 — PAPER smoke decision-path contract (FALSE-PASS regression).

Invariant:

    SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED

A canonical PAPER smoke is only VERIFIED when the decision layer actually
executed:

    contexts_built    > 0
    router_invocations > 0
    strategy_invocations > 0

``exit_code == 0`` alone (or 0 contexts) is NOT proof the strategy path ran
(DEF-OP-003-ENTRYPOINT-ASSETS + DEF-OP-003-FAKE-EPOCH both produced
exit 0 with a dead decision cycle).

FAIL BEFORE FIX (baseline): the real smoke exits 0 with contexts_built=0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "scripts" / "start_paper_trading.py").exists():
    _REPO_ROOT = _REPO_ROOT.parent
    if _REPO_ROOT.parent == _REPO_ROOT:
        raise RuntimeError("repo root not found")


def decision_path_verified(status: dict) -> bool:
    """Fail-closed gate: exit 0 with a dead decision cycle must NOT pass."""
    cycle = status.get("cycle") or {}
    return bool(
        status.get("mode") == "paper"
        and cycle.get("contexts_built", 0) > 0
        and cycle.get("router_invocations", 0) > 0
        and cycle.get("strategy_invocations", 0) > 0
    )


def test_exit_zero_without_contexts_is_not_strategy_path_verified() -> None:
    """The permanent invariant: exit 0 + empty decision cycle can never pass."""
    dead_status = {
        "mode": "paper",
        "cycle": {
            "contexts_built": 0,
            "router_invocations": 0,
            "strategy_invocations": 0,
            "orders_created": 0,
        },
    }
    assert decision_path_verified(dead_status) is False


def test_partial_cycle_never_passes() -> None:
    """Each mandatory counter is independently required."""
    base = {
        "mode": "paper",
        "cycle": {"contexts_built": 1, "router_invocations": 1, "strategy_invocations": 1},
    }
    assert decision_path_verified(base) is True
    for key in ("contexts_built", "router_invocations", "strategy_invocations"):
        broken = {**base, "cycle": {**base["cycle"], key: 0}}
        assert decision_path_verified(broken) is False, f"gate passed with {key}=0"


def test_canonical_smoke_exercises_decision_path() -> None:
    """Run the REAL entrypoint (hermetic fake provider) and prove the
    decision layer executed: contexts, router and runtime strategy calls."""
    env = dict(os.environ)
    env["CERT_HERMETIC"] = "1"
    cmd = [
        sys.executable,
        str(_REPO_ROOT / "scripts" / "start_paper_trading.py"),
        "--assets",
        "BTC,ETH,SOL",
        "--provider",
        "fake",
        "--max-cycles",
        "1",
        "--interval",
        "0",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    stdout = proc.stdout
    assert proc.returncode == 0, (
        f"smoke exit {proc.returncode}: {stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )

    marker = "Paper trading loop stopped."
    assert marker in stdout, "entrypoint did not complete; no status emitted"
    tail = stdout.split(marker, 1)[1].lstrip()
    status = json.loads(tail)

    cycle = status.get("cycle") or {}
    assert cycle.get("contexts_built", 0) > 0, f"contexts_built=0: {cycle}"
    assert cycle.get("router_invocations", 0) > 0, f"router_invocations=0: {cycle}"
    assert cycle.get("strategy_invocations", 0) > 0, f"strategy_invocations=0: {cycle}"
    assert status.get("mode") == "paper"
    # orders MAY be 0 for the flat fake feed; decision path is mandatory.
    assert decision_path_verified(status) is True
