"""Contract tests for the WP-005 preflight (``scripts/wp005_preflight.py``).

The preflight exists to stop a checkout from being described as economically
evaluated when nothing was executed. So the things held to their claims here are
its refusals:

* presence is not execution - an aggregate whose families all record zero trades
  is the exact artefact the old entrypoint wrote when its dataset glob matched
  nothing, and it has to be a blocker;
* a family module that does not exist is a blocker, not a missing detail;
* there is no PASS state at all, whatever the tree contains;
* the observation may not be written inside the tree it observes;
* the artefact is byte-stable (LF) so a re-run is comparable.

WP-006 added a manifest at ``data/economic/w006/MANIFEST.json`` and a results
envelope (``{"results": {family: ...}}``). Both are covered here, because a
preflight that misreads either shape reports a false blocker.
"""
from __future__ import annotations

import hashlib
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


def make_tree(tmp_path: Path, preflight, with_manifest: bool = False) -> Path:
    """A minimal tree that satisfies every presence criterion the preflight has."""
    root = tmp_path / "repo"
    for d in ("config", "data/recovery", "scripts", "src/trading_bot/research/families",
              "reports/strategy-baseline"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / preflight.LEDGER).write_text(
        json.dumps({"_schema_version": "strategy-admission-ledger-v1",
                    "strategies": {"ema_crossover": {"admitted_for_paper": False}}}),
        encoding="utf-8")
    (root / preflight.COST).write_text(json.dumps({"schema": "cost-barrier-explorer"}), encoding="utf-8")
    (root / preflight.AUDIT).write_text(json.dumps({"schema": "active-economic-audit"}), encoding="utf-8")
    (root / preflight.ENTRY).write_text("# entrypoint placeholder\n", encoding="utf-8")
    for fam in preflight.FAMILIES:
        (root / preflight.FAMILY_MODULE.format(family=fam)).write_text("# family\n", encoding="utf-8")
    if with_manifest:
        data = root / preflight.MANIFEST
        (data.parent / "datasets").mkdir(parents=True, exist_ok=True)
        payload = json.dumps([bar(1_600_000_000_000), bar(1_600_000_300_000, 101.0)],
                             separators=(",", ":")).encode() + b"\n"
        (data.parent / "datasets" / "SYM_5m.json").write_bytes(payload)
        data.write_text(json.dumps({
            "schema": "W006_MARKET_DATA_MANIFEST_V1",
            "fetched_at_utc": "2026-10-25T00:00:00+00:00",
            "datasets": {"SYM": {"path": "datasets/SYM_5m.json",
                                 "sha256": hashlib.sha256(payload).hexdigest(),
                                 "bars": 2}}}), encoding="utf-8")
    else:
        (root / preflight.DATA_DIR).mkdir(parents=True, exist_ok=True)
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


def legacy_payload(trades_by_family: dict[str, int]) -> dict:
    return {fam: {sc: {"totals": {"trades": n, "net": 0.0 if n == 0 else 1.0}}
                  for sc in ("BASE", "2X_COST", "STRESSED_SLIPPAGE", "ZERO_COST")}
            for fam, n in trades_by_family.items()}


def v2_payload(trades_by_family: dict[str, int]) -> dict:
    return {"schema": "MULTI_FAMILY_RESULTS_V2", "status": "OK",
            "results": legacy_payload(trades_by_family)}


def write_aggregate(root: Path, preflight, payload: dict) -> None:
    (root / preflight.AGGREGATE).write_text(json.dumps(payload), encoding="utf-8")


def observation(root: Path, preflight) -> dict:
    return preflight.build_observation(root, with_git=False)


# --------------------------------------------------------------------------- #
# presence is not execution


def test_an_all_zero_aggregate_is_a_blocker_not_a_result(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, legacy_payload({fam: 0 for fam in preflight.FAMILIES}))
    observed = observation(root, preflight)
    assert any(b.startswith("ZERO_TRADE_RESULT:") for b in observed["blockers"]), observed["blockers"]
    assert observed["result_coverage"]["families_with_zero_trades"] == sorted(preflight.FAMILIES)
    assert observed["economic_execution"] == "NOT_RUN"
    assert observed["economic_result"] == "INCONCLUSIVE"


def test_one_traded_family_only_clears_that_family(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    counts = {fam: 0 for fam in preflight.FAMILIES}
    counts["trend"] = 42
    write_aggregate(root, preflight, legacy_payload(counts))
    zero = observation(root, preflight)["result_coverage"]["families_with_zero_trades"]
    assert "trend" not in zero
    assert set(zero) == set(preflight.FAMILIES) - {"trend"}


# --------------------------------------------------------------------------- #
# artefact shapes


def test_a_single_full_run_aggregate_satisfies_coverage(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, legacy_payload({fam: 7 for fam in preflight.FAMILIES}))
    coverage = observation(root, preflight)["result_coverage"]
    assert coverage["aggregate_present"] is True
    assert coverage["families_missing"] == []
    assert coverage["families_with_zero_trades"] == []


def test_the_v2_results_envelope_is_read_as_families(tmp_path, preflight):
    """WP-006 wraps the results; reading the envelope as a family is a false blocker."""
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 11 for fam in preflight.FAMILIES}))
    observed = observation(root, preflight)
    assert observed["result_coverage"]["families_missing"] == []
    assert observed["result_coverage"]["families_with_zero_trades"] == []
    assert not [b for b in observed["blockers"] if b.startswith(("ZERO_TRADE", "RESULT_FAMILY"))]


def test_per_family_files_also_satisfy_coverage(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    for fam in preflight.FAMILIES:
        (root / preflight.RESULT_DIR / f"{preflight.RESULT_PREFIX}{fam}.json").write_text(
            json.dumps(legacy_payload({fam: 3})), encoding="utf-8")
    coverage = observation(root, preflight)["result_coverage"]
    assert coverage["aggregate_present"] is False
    assert coverage["families_missing"] == []


def test_missing_results_block(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    assert "NO_MULTI_FAMILY_RESULTS" in observation(root, preflight)["blockers"]


def test_partial_coverage_names_the_missing_families(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, legacy_payload({"momentum": 5}))
    blocker = next(b for b in observation(root, preflight)["blockers"]
                   if b.startswith("RESULT_FAMILY_COVERAGE_INCOMPLETE:"))
    assert "trend" in blocker and "momentum" not in blocker


# --------------------------------------------------------------------------- #
# data sources


def test_the_manifest_is_preferred_over_the_legacy_directory(tmp_path, preflight):
    root = make_tree(tmp_path, preflight, with_manifest=True)
    write_aggregate(root, preflight, v2_payload({fam: 4 for fam in preflight.FAMILIES}))
    observed = observation(root, preflight)
    assert observed["datasets_source"] == preflight.MANIFEST
    assert [d["symbol"] for d in observed["datasets"]] == ["SYM"]
    assert observed["datasets"][0]["manifest_digest_match"] is True
    assert observed["datasets"][0]["validation"] == "BASIC_SCHEMA_PASS"


def test_a_manifest_dataset_with_the_wrong_digest_is_invalid(tmp_path, preflight):
    root = make_tree(tmp_path, preflight, with_manifest=True)
    write_aggregate(root, preflight, v2_payload({fam: 4 for fam in preflight.FAMILIES}))
    dataset = root / preflight.MANIFEST.rsplit("/", 1)[0] / "datasets" / "SYM_5m.json"
    dataset.write_bytes(dataset.read_bytes().replace(b"101.0", b"999.0", 1))
    observed = observation(root, preflight)
    assert observed["datasets"][0]["manifest_digest_match"] is False
    assert "INVALID_DATASET_SCHEMA" in observed["blockers"]


def test_no_datasets_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 4 for fam in preflight.FAMILIES}))
    (root / preflight.DATA_DIR / "BTCUSDT_W1.json").unlink()
    assert "NO_DATASETS_IN_CANONICAL_INPUT_PATH" in observation(root, preflight)["blockers"]


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
    assert "INVALID_DATASET_SCHEMA" in observation(root, preflight)["blockers"]


# --------------------------------------------------------------------------- #
# structural refusals


def test_a_missing_family_module_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 4 for fam in preflight.FAMILIES}))
    (root / preflight.FAMILY_MODULE.format(family="breakout")).unlink()
    assert any(b.startswith("FAMILY_MODULE_MISSING:") and "breakout" in b
               for b in observation(root, preflight)["blockers"])


def test_a_missing_ledger_blocks(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 4 for fam in preflight.FAMILIES}))
    (root / preflight.LEDGER).unlink()
    assert any(b.startswith("GOVERNANCE_INPUT_MISSING:") and b.endswith(preflight.LEDGER)
               for b in observation(root, preflight)["blockers"])


def test_an_unknown_schema_version_is_published_not_hidden(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    (root / preflight.LEDGER).write_text(
        json.dumps({"_schema_version": "something-else", "strategies": {}}), encoding="utf-8")
    observed = observation(root, preflight)
    assert observed["inputs"][preflight.LEDGER]["schema_version"] == "something-else"


# --------------------------------------------------------------------------- #
# the CLI: no PASS, an external output, byte-stable artefacts


def test_nothing_the_tree_contains_can_produce_a_pass(tmp_path, preflight):
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 9 for fam in preflight.FAMILIES}))
    init_git(root)
    out = tmp_path / "out"
    assert preflight.main(["--repo", str(root), "--out", str(out)]) == 0
    observed = json.loads((out / "WP005_PREFLIGHT_OBSERVATION.json").read_text(encoding="utf-8"))
    assert observed["blockers"] == []
    assert "PASS" not in (out / "WP005_PREFLIGHT_OBSERVATION.md").read_text(
        encoding="utf-8").split("\n")[2]
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
    assert "BLOCKED" in (out / "WP005_PREFLIGHT_OBSERVATION.md").read_text(encoding="utf-8")


def test_the_observation_depends_on_the_tree_and_not_the_host(tmp_path, preflight):
    """Two runs over the same tree differ only in the observation timestamp."""
    root = make_tree(tmp_path, preflight)
    write_aggregate(root, preflight, v2_payload({fam: 2 for fam in preflight.FAMILIES}))
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
