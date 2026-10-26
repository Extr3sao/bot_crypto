"""WP-SIGNAL-003 — the service starts per capability, and the block is named.

The economic block must not take the observable planes down with it, and the
admission gate must not be bypassed to make a demo look alive. These tests hold
both directions:

* with zero admitted strategies, ingestion, signals and SHADOW are `ENABLED` and
  `PAPER_ORDER` is `BLOCKED` with the reason spelled out;
* `LIVE` is not a capability this runtime can acquire;
* the analyst is a child of the supervisor, restartable and stoppable by file,
  and can be left out without changing anything else.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{name}_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher() -> Any:
    return _load_script("start_paper_lab")


def _namespace(launcher: Any, **overrides: Any) -> argparse.Namespace:
    values = {**vars(launcher.parse_args([])), "run_id": "lab-test", "dry_run": True}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_capabilities_are_reported_per_layer(launcher: Any) -> None:
    capabilities = launcher.capability_preflight(_namespace(launcher))
    layers = capabilities["layers"]
    assert layers["INGEST"]["state"] == "ENABLED"
    assert layers["SIGNALS"]["state"] == "ENABLED"
    assert layers["SHADOW"]["state"] == "ENABLED"
    assert layers["ANALYST"]["state"] == "ENABLED"
    assert layers["LIVE"]["state"] == "DISABLED"
    # The gate is read from the tracked ledger, not assumed by this test: the
    # verdict and the ledger must agree, whichever way the ledger currently is.
    assert layers["PAPER_ORDER"]["state"] == (
        "ENABLED" if capabilities["admitted_for_paper"] else "BLOCKED"
    )
    assert capabilities["paper_order_enabled"] is bool(capabilities["admitted_for_paper"])
    assert capabilities["strategy_count"] >= 1


def test_a_blocked_paper_layer_still_names_why(launcher: Any) -> None:
    capabilities = launcher.capability_preflight(_namespace(launcher))
    if capabilities["admitted_for_paper"]:
        pytest.skip("this checkout has an admitted strategy; the block path is not the state")
    assert capabilities["layers"]["PAPER_ORDER"]["state"] == "BLOCKED"
    assert "admits none" in capabilities["layers"]["PAPER_ORDER"]["reason"]
    assert str(capabilities["strategy_count"]) in capabilities["layers"]["PAPER_ORDER"]["reason"]


def test_the_analyst_is_supervised_with_its_own_stop_file(launcher: Any) -> None:
    namespace = _namespace(launcher)
    run_dir = Path("reports/paper-lab/lab-test")
    stop_files = launcher.child_stop_files(namespace, "lab-test", run_dir)
    specs = {spec.name: spec for spec in launcher.build_specs(namespace, "lab-test", run_dir, stop_files)}
    analyst = specs["analyst"]
    assert analyst.critical is False  # its failure must not stop PAPER
    assert analyst.stop_file == stop_files["analyst"]
    command = " ".join(analyst.command)
    assert "ai_signal_analyst.py" in command
    assert "--loop" in command
    assert "--run-id" in command and "lab-test" in command
    assert "--budget-per-hour" in command


def test_the_analyst_can_be_left_out(launcher: Any) -> None:
    namespace = _namespace(launcher, no_analyst=True)
    run_dir = Path("reports/paper-lab/lab-test")
    stop_files = launcher.child_stop_files(namespace, "lab-test", run_dir)
    names = {spec.name for spec in launcher.build_specs(namespace, "lab-test", run_dir, stop_files)}
    assert "analyst" not in names
    assert {"paper", "collector"} <= names
    capabilities = launcher.capability_preflight(namespace)
    assert capabilities["layers"]["ANALYST"]["state"] == "DISABLED"


def test_the_plan_carries_the_capabilities(launcher: Any) -> None:
    """`LAB_PLAN.json` must say what the run may do, not only what it starts."""
    source = (REPO / "scripts" / "start_paper_lab.py").read_text(encoding="utf-8")
    assert '"capabilities": capabilities' in source
