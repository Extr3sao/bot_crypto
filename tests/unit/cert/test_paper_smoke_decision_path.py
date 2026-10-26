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

DEF-AUTO-4 note: the launcher no longer declares every family ``CONFIRMED``;
its strategy map comes from the admission ledger and the router keeps its
confirmation gate on. The full strategy path is therefore exercised with a
**fixture ledger that admits one strategy**, which is what a real admission
looks like — and the second test here proves the other half: a strategy that
research rejected cannot trade, however promising the feed is.
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


ADMITTED_LEDGER: dict[str, object] = {
    "_schema_version": "strategy-admission-ledger-v1",
    "_generated_by": "tests/unit/cert/test_paper_smoke_decision_path.py (CONTROLLED TEST)",
    "_claim": "a controlled fixture, not market evidence",
    "_sources": [
        {
            "path": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "sha256": "fixture",
        }
    ],
    "strategies": {
        "ema_crossover@5m": {
            "family": "ema_crossover",
            "status": "PAPER_CANDIDATE",
            "admitted_for_paper": True,
            "expected_gross_edge_bps": 12.0,
            "edge_evidence": {
                "source_doc": "CONTROLLED TEST fixture",
                "metric": "fixture.reachability",
                "value_bps": 12.0,
                "knowledge": "ASSUMED",
                "sample_trades": 1,
                "note": "reachability fixture only: this is NOT market evidence",
                "evidence_class": "CONTROLLED_TEST_FIXTURE",
                "period": "n/a",
                "timeframe": "5m",
                "status": "PAPER_CANDIDATE",
            },
            "source_doc": "CONTROLLED TEST fixture",
            "rationale": "CONTROLLED TEST: exercises the decision path to the broker boundary",
            "timeframe": "5m",
            "known": True,
        }
    },
}

REJECTED_LEDGER: dict[str, object] = {
    "_schema_version": "strategy-admission-ledger-v1",
    "_generated_by": "tests/unit/cert/test_paper_smoke_decision_path.py (CONTROLLED TEST)",
    "_claim": "every family research rejected must stay unable to trade",
    "strategies": {
        "ema_crossover@5m": {
            "family": "ema_crossover",
            "status": "NO_GROSS_EDGE",
            "admitted_for_paper": False,
            "expected_gross_edge_bps": -4.56,
            "edge_evidence": None,
            "source_doc": "CONTROLLED TEST fixture",
            "rationale": "research classification NO_GROSS_EDGE",
            "timeframe": "5m",
            "known": True,
        }
    },
}


def _run_smoke(tmp: Path, ledger: dict[str, object]) -> tuple[int, str, str]:
    ledger_path = tmp / "strategy_admission.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    env = dict(os.environ)
    env["CERT_HERMETIC"] = "1"
    env["PAPER_STATE_PATH"] = str(tmp / "paper_state.json")
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
        "--ledger",
        str(ledger_path),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_canonical_smoke_exercises_decision_path() -> None:
    """Run the REAL entrypoint (hermetic fake provider) and prove the
    decision layer executed: contexts, router and runtime strategy calls.

    Hermetic wrt durable paper state too: the subprocess writes its state
    file to a private temp dir (PAPER_STATE_PATH), never to the host's
    data/storage (GAP-R1 hardening must not make certification depend on
    residual host state).

    The strategy that reaches the family is admitted by the fixture ledger, so
    the path is proven through the real admission gate rather than around it.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        returncode, stdout, stderr = _run_smoke(Path(tmpdir), ADMITTED_LEDGER)
    assert returncode == 0, f"smoke exit {returncode}: {stdout[-2000:]}\n{stderr[-2000:]}"
    assert "[registry] paper-executable on 5m: ['ema_crossover@5m']" in stdout, stdout[-2000:]

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


def test_a_rejected_strategy_never_reaches_the_family() -> None:
    """DEF-AUTO-4 / §59 — the same smoke, with research having said no.

    Before the fix the launcher declared every family CONFIRMED, so this run
    would have looked identical to the admitted one. It must now stop at the
    router: contexts and router calls happen, no strategy is invoked, and no
    order exists.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        returncode, stdout, stderr = _run_smoke(Path(tmpdir), REJECTED_LEDGER)
    assert returncode == 0, f"smoke exit {returncode}: {stdout[-2000:]}\n{stderr[-2000:]}"
    assert "[registry] paper-executable on 5m: NONE" in stdout, stdout[-2000:]
    assert "CONFIRMED" not in stdout, "a rejected strategy was described as CONFIRMED"

    marker = "Paper trading loop stopped."
    tail = stdout.split(marker, 1)[1].lstrip()
    status = json.loads(tail)
    cycle = status.get("cycle") or {}
    assert cycle.get("contexts_built", 0) > 0, f"contexts_built=0: {cycle}"
    assert cycle.get("router_invocations", 0) > 0, f"router_invocations=0: {cycle}"
    assert cycle.get("strategy_invocations", 0) == 0, f"a rejected strategy was invoked: {cycle}"
    assert cycle.get("orders_created", 0) == 0, f"a rejected strategy traded: {cycle}"
