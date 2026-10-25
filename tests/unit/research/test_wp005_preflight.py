"""Contract tests for the WP-005 preflight (``scripts/wp005_preflight.py``).

The preflight exists to stop a checkout from being described as economically
evaluated when nothing was executed. So the things held to their claims here are
its refusals:

* presence is not execution - an aggregate whose families all record zero trades
  is the exact artefact ``multi_family_backtest.py`` writes when its dataset glob
  matched nothing, and it has to be a blocker;
* a family module that does not exist is a blocker, not a missing detail;
* there is no PASS state at all, whatever the tree contains;
* the observation may not be written inside the tree it observes;
* the artefacts are byte-stable (LF, no clock in the payload that decides
  anything) so a re-run is comparable.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def preflight():
    return load_script("wp005_preflight")


def bar(ts: int, close: float = 100.0) -> dict:
    return {"ts": ts, "open": close, "high": close + 1.0, "low": close - 1.0,
            "close": close, "volume": 10.0}


def make_tree(tmp_path: Path, preflight) -> Path:
    """A minimal tree that satisfies every presence criterion the preflight has."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "data" / "recovery").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "trading_bot" / "research" / "families").mkdir(parents=True)
    (root / "reports" / "strategy-baseline" / "data").mkdir(parents=True)
    (root / preflight.LEDGER).write_text(
        json.dumps({"_schema_version": "strategy-admission-ledger-v1",
                    "strategies": {"ema_crossover": {"admitted_for_paper": False}}}),
        encoding="utf-8")
    (root / preflight.COST).write_text(json.dumps({"schema": "cost-barrier-explorer"}), encoding="utf-8")
    (root / preflight.AUDIT).write_text(json.dumps({"schema": "active-economic-audit"}), encoding="utf-8")
    (root / preflight.ENTRY).write_text("# entrypoint placeholder\n", encoding="utf-8")
    for fam in preflight.FAMILIES:
        (root / preflight.FAMILY_MODULE.format(family=fam)).write_text("# family\n", encoding="utf-8")
    (root / preflight.DATA_DIR / "BTCUSDT_W1.json").write_text(
        json.dumps([bar(1_600_000_000_000), bar(1_600_000_300_000, 101.0)]), encoding="utf-8")
    return root


def init_git(root: Path) -> None:
    """A tree without a commit has no verifiable HEAD, and that is a blocker."""
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,
                                    capture_output=True, text=True)
    run("init", "-q")
    run("-c", "user.email=wp005@example.invalid", "-c", "user.name=WP-005",
        "commit", "-q", "--allow-empty", "-m", "fixture")


def results_payload(trades_by_family: dict[str, int]) -> dict:
    return {fam: {sc: {"totals": {"trades": n, "net": 0.0 if n == 0 else 1.0}}
                  for sc in ("BASE", "2X_COST", "STRESSED_SLIPPAGE", "ZERO_COST")}
            for fam, n in trades_by_family.items()}


def write_aggregate(root: Path, preflight, trades_by_family: dict[str, int]) -> None:
    (root / preflight.AGGREGATE).write_text(
        json.dumps(results_payload(trades_by_family)), encoding="utf-8")


def observation(root: Path, preflight) -> dict:
    return preflight.build_observation(root, with_git=False)


# --------------------------------------------------------------------------- #
# presence is not execution


def test_an_all_zero_aggregate_is_a_blocker_not_a_result(tmp_path, preflight):
    """"The file exists" must not survive an aggregate that traded nothing."""
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 0 for fam in preflight.FAMILIES})
    observed = observation(root, preflight)
    assert any(b.startswith("ZERO_TRADE_RESULT:") for b in observed["blockers"]), observed["blockers"]
    assert observed["result_coverage"]["families_with_zero_trades"] == sorted(preflight.FAMILIES)
    # Presence is recorded, but never upgraded to an execution claim.
    assert observed["economic_execution"] == "NOT_RUN"
    assert observed["economic_result"] == "INCONCLUSIVE"


def test_one_traded_family_only_clears_that_family(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    counts = {fam: 0 for fam in preflight.FAMILIES}
    counts["trend"] = 42
    write_aggregate(root, preflight, counts)
    observed = observation(root, preflight)
    zero = observed["result_coverage"]["families_with_zero_trades"]
    assert "trend" not in zero
    assert set(zero) == set(preflight.FAMILIES) - {"trend"}
    assert any(b.startswith("ZERO_TRADE_RESULT:") for b in observed["blockers"])


# --------------------------------------------------------------------------- #
# the artifact convention the entrypoint actually has


def test_a_single_full_run_aggregate_satisfies_coverage(tmp_path, preflight):
    """A full run writes ONE file keyed by family; demanding six files would misjudge it."""
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 7 for fam in preflight.FAMILIES})
    observed = observation(root, preflight)
    assert observed["result_coverage"]["aggregate_present"] is True
    assert observed["result_coverage"]["families_missing"] == []
    assert observed["result_coverage"]["families_with_zero_trades"] == []
    assert not [b for b in observed["blockers"] if b.startswith(("ZERO_TRADE", "RESULT_FAMILY"))]


def test_per_family_files_also_satisfy_coverage(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    for fam in preflight.FAMILIES:
        (root / preflight.RESULT_DIR / f"{preflight.RESULT_PREFIX}{fam}.json").write_text(
            json.dumps(results_payload({fam: 3})), encoding="utf-8")
    observed = observation(root, preflight)
    assert observed["result_coverage"]["aggregate_present"] is False
    assert observed["result_coverage"]["families_missing"] == []


def test_missing_results_block(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    observed = observation(root, preflight)
    assert "NO_MULTI_FAMILY_RESULTS" in observed["blockers"]


def test_partial_coverage_names_the_missing_families(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {"momentum": 5})
    observed = observation(root, preflight)
    blocker = next(b for b in observed["blockers"] if b.startswith("RESULT_FAMILY_COVERAGE_INCOMPLETE:"))
    assert "trend" in blocker and "momentum" not in blocker


# --------------------------------------------------------------------------- #
# structural refusals


def test_a_missing_family_module_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 4 for fam in preflight.FAMILIES})
    (root / preflight.FAMILY_MODULE.format(family="breakout")).unlink()
    observed = observation(root, preflight)
    assert any(b.startswith("FAMILY_MODULE_MISSING:") and "breakout" in b for b in observed["blockers"])


def test_no_datasets_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 4 for fam in preflight.FAMILIES})
    (root / preflight.DATA_DIR / "BTCUSDT_W1.json").unlink()
    observed = observation(root, preflight)
    assert "NO_DATASETS_IN_CANONICAL_INPUT_PATH" in observed["blockers"]


@pytest.mark.parametrize(
    "bars",
    [
        [bar(2), bar(2)],                        # duplicate timestamp
        [bar(2), bar(1)],                        # descending
        [{**bar(1), "high": 90.0}],              # high below open/close
        [{**bar(1), "volume": -1.0}],            # negative volume
        [{"ts": 1, "open": 1.0}],                # missing OHLCV fields
        [],                                      # empty
    ],
)
def test_a_bad_dataset_is_flagged(tmp_path, preflight, bars):
    root = make_tree(tmp_path, preflight)
    (root / preflight.DATA_DIR / "BTCUSDT_W1.json").write_text(json.dumps(bars), encoding="utf-8")
    observed = observation(root, preflight)
    assert "INVALID_DATASET_SCHEMA" in observed["blockers"]


def test_a_missing_ledger_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 4 for fam in preflight.FAMILIES})
    (root / preflight.LEDGER).unlink()
    observed = observation(root, preflight)
    assert any(b.startswith("GOVERNANCE_INPUT_MISSING:") and b.endswith(preflight.LEDGER)
               for b in observed["blockers"])


def test_an_unknown_schema_version_is_published_not_hidden(tmp_path, preflight):
    """The preflight reports the ledger's identity; it does not reinterpret it."""
    root = make_tree(tmp_path, preflight)
    (root / preflight.LEDGER).write_text(
        json.dumps({"_schema_version": "something-else", "strategies": {}}), encoding="utf-8")
    observed = observation(root, preflight)
    assert observed["inputs"][preflight.LEDGER]["schema_version"] == "something-else"


# --------------------------------------------------------------------------- #
# the CLI: no PASS, an external output, byte-stable artefacts


def test_nothing_the_tree_contains_can_produce_a_pass(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 9 for fam in preflight.FAMILIES})
    init_git(root)
    out = tmp_path / "out"
    assert preflight.main(["--repo", str(root), "--out", str(out)]) == 0
    text = (out / "WP005_PREFLIGHT_OBSERVATION.json").read_text(encoding="utf-8")
    observed = json.loads(text)
    assert observed["blockers"] == []
    assert "PASS" not in (out / "WP005_PREFLIGHT_OBSERVATION.md").read_text(encoding="utf-8").split("\n")[2]
    assert observed["economic_execution"] == "NOT_RUN"
    assert observed["independent_economic_verification"] == "NOT_RUN"
    assert observed["economic_result"] == "INCONCLUSIVE"
    assert observed["paper"] == "NOT_AUTHORIZED"
    assert observed["false_success_observed"] == 0


def test_an_output_inside_the_repo_is_refused(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    before = sorted(p.name for p in root.rglob("*"))
    assert preflight.main(["--repo", str(root), "--out", str(root / "obs")]) == 2
    assert not (root / "obs").exists()
    assert sorted(p.name for p in root.rglob("*")) == before


def test_a_blocked_tree_exits_two_and_says_so(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    init_git(root)
    out = tmp_path / "out"
    assert preflight.main(["--repo", str(root), "--out", str(out)]) == 2
    observed = json.loads((out / "WP005_PREFLIGHT_OBSERVATION.json").read_text(encoding="utf-8"))
    assert "NO_MULTI_FAMILY_RESULTS" in observed["blockers"]
    assert observed["economic_result"] == "INCONCLUSIVE"
    assert (out / "WP005_PREFLIGHT_OBSERVATION.md").read_text(encoding="utf-8").count("BLOCKED") >= 1


def test_the_observation_depends_on_the_tree_and_not_the_host(tmp_path, preflight):
    """Two runs over the same tree differ only in the observation timestamp."""
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, {fam: 2 for fam in preflight.FAMILIES})
    init_git(root)
    paths = []
    for name in ("a", "b"):
        out = tmp_path / name
        preflight.main(["--repo", str(root), "--out", str(out)])
        paths.append(out / "WP005_PREFLIGHT_OBSERVATION.json")
    first, second = (json.loads(p.read_text(encoding="utf-8")) for p in paths)
    for payload in (first, second):
        payload.pop("observed_at_utc")
    assert first == second
    for p in paths:
        assert b"\r\n" not in p.read_bytes(), "the observation must be written with LF"
