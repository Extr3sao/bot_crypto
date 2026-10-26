"""RFC-TDM-015 / WP-TDM-015-OPS — D-06: a closed run still says what produced it.

The PAPER entrypoint writes ``PAPER_RUN.json`` twice: at launch (provider, mode,
environment, universe preflight, registry counts) and at shutdown (state,
cycles, totals). The shutdown rewrite used to write a *fresh* object over the
launch one, so a closed run declared ``provider: null`` and the independent
signal verifier — whose whole job is telling a REAL-ccxt signal from a FAKE one —
silently skipped the check it exists for.

Invariant enforced here:

    close = launch payload MERGED with the shutdown payload

never "shutdown payload replaces launch payload". Reproducer against the old
behaviour: the closed descriptor had no ``provider`` key at all.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

LAUNCH = {
    "run_id": "tdm15-descriptor",
    "pid": 4242,
    "mode": "PAPER",
    "continuous": True,
    "assets": ["BTC", "ETH", "SOL"],
    "timeframe": "5m",
    "provider": "ccxt",
    "environment": "ccxt:binance",
    "paper_candidates": [],
    "registry_counts": {"PAPER": 0, "SHADOW": 2},
    "universe_preflight": {"ok": True, "blocking_reason": None},
    "stop_signals_installed": ["SIGINT"],
    "started_at_ms": 1_793_000_000_000,
}


def _load_entrypoint() -> Any:
    spec = importlib.util.spec_from_file_location(
        "autonomous_paper_descriptor_under_test", REPO / "scripts" / "autonomous_paper.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["autonomous_paper_descriptor_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _read(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "PAPER_RUN.json").read_text(encoding="utf-8"))


def test_closing_the_descriptor_keeps_the_launch_provenance(tmp_path: Path) -> None:
    entry = _load_entrypoint()
    entry.write_run_descriptor(tmp_path, dict(LAUNCH))
    launched = _read(tmp_path)
    assert launched["provider"] == "ccxt"
    assert launched["schema_version"] == entry.DESCRIPTOR_SCHEMA

    entry.close_run_descriptor(
        tmp_path,
        {
            "run_id": "tdm15-descriptor",
            "pid": 4242,
            "state": "STOPPED",
            "stop_reason": "STOP file",
            "cycles": 3,
            "totals": {"paper_trades": 0, "orders_created": 0},
            "ended_at_ms": 1_793_000_600_000,
        },
    )
    closed = _read(tmp_path)

    # D-06: everything the launch declared about *what this run was* survives.
    for key in (
        "provider",
        "environment",
        "assets",
        "timeframe",
        "mode",
        "universe_preflight",
        "registry_counts",
        "paper_candidates",
        "started_at_ms",
        "continuous",
    ):
        assert closed[key] == LAUNCH[key], key
    # ... and the shutdown result is what the close added.
    assert closed["state"] == "STOPPED"
    assert closed["cycles"] == 3
    assert closed["totals"] == {"paper_trades": 0, "orders_created": 0}
    assert closed["ended_at_ms"] == 1_793_000_600_000
    assert closed["launch_descriptor_preserved"] is True


def test_a_close_with_no_launch_descriptor_still_writes_an_honest_one(tmp_path: Path) -> None:
    entry = _load_entrypoint()
    entry.close_run_descriptor(tmp_path, {"run_id": "orphan", "state": "FAILED"})
    payload = _read(tmp_path)
    assert payload["state"] == "FAILED"
    # No provenance is invented: the file says it never saw a launch descriptor.
    assert payload["launch_descriptor_preserved"] is False
    assert "provider" not in payload


def test_a_corrupt_launch_descriptor_is_not_a_reason_to_lose_the_close(tmp_path: Path) -> None:
    entry = _load_entrypoint()
    (tmp_path / "PAPER_RUN.json").write_text("{not json", encoding="utf-8")
    entry.close_run_descriptor(tmp_path, {"run_id": "broken", "state": "STOPPED", "cycles": 1})
    payload = _read(tmp_path)
    assert payload["run_id"] == "broken"
    assert payload["launch_descriptor_preserved"] is False


def test_the_shutdown_payload_may_deliberately_restate_a_launch_key(tmp_path: Path) -> None:
    """A key the close names on purpose wins, and the merge says which ones it was."""
    entry = _load_entrypoint()
    entry.write_run_descriptor(tmp_path, dict(LAUNCH))
    entry.close_run_descriptor(
        tmp_path,
        {"run_id": "tdm15-descriptor", "state": "STOPPED", "provider": "ccxt", "timeframe": "5m"},
    )
    payload = _read(tmp_path)
    assert payload["provider"] == "ccxt"
    assert "provider" not in payload["launch_keys"]
    assert payload["launch_keys"] == sorted(
        (set(LAUNCH) | {"schema_version"}) - {"run_id", "provider", "timeframe"}
    )
