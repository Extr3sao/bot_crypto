"""The preregistration gate must be reusable, and must refuse rather than warn.

Three things are being pinned here, in this order:

* **positive** — a preregistration that is genuinely complete, frozen, committed and backed by real
  bytes *is* authorised, and the mode in which it is authorised is the only mode that returns exit
  ``0``. A gate that never opens is as useless as one that never closes;
* **negative** — every defect the gate claims to catch is produced by a test that breaks exactly that
  one thing in an otherwise authorising fixture, so no defect can pass by riding on another;
* **adversarial** — the ways somebody would *get past* it: filling the nulls after seeing results,
  dropping the list of consumed holdouts, disagreeing with its own ledger, pointing a path outside
  the checkout, or reusing an identifier that already has a published run.

The fixture identifier is ``EXP-900A``. It is deliberately not any identifier this repository has
used, so a test that passes cannot be passing because of a run directory that happens to exist.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import prereg_gate as gate

EXPERIMENT = "EXP-900A"


# --------------------------------------------------------------------------- #
# fixture
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=120)


def _commit(repo: Path, message: str = "fixture") -> str:
    _git(repo, "-c", "core.autocrlf=false", "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "user.name=fixture",
        "-c",
        "core.autocrlf=false",
        "commit",
        "-q",
        "-m",
        message,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def _commit_staged(repo: Path, message: str) -> None:
    """Commit exactly what is staged, without ``add -A`` re-adding a file that was just dropped."""
    _git(
        repo,
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "user.name=fixture",
        "-c",
        "core.autocrlf=false",
        "commit",
        "-q",
        "-m",
        message,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(experiment: str = EXPERIMENT, code_commit: str = "0" * 40) -> dict[str, Any]:
    return {
        "experiment_id": experiment,
        "schema_version": "1.0",
        "status": "FROZEN",
        "origin": "author_drafted_before_results",
        "hypothesis": {
            "null": "the candidate earns no more than its round trip after costs",
            "alternative": "the candidate earns more than its round trip after costs",
            "candidate_id": "fixture/1h/NOASSET",
            "candidate_family": "fixture",
            "candidate_code_commit": code_commit,
            "baseline_id": "NO_TRADE",
            "baseline_config_path": "config/universe.yaml",
            "candidate_config_path": "config/universe.yaml",
            "expected_mechanism": "a stated mechanism, not a fitted one",
        },
        "design": {
            "primary_metric": "net_usdt_per_completed_trade",
            "secondary_metrics": ["profit_factor", "max_drawdown_usdt"],
            "statistical_method": "stationary bootstrap, one-sided 95% lower bound",
            "bootstrap_seed": 20260101,
            "bootstrap_iterations": 5000,
            "multiple_comparisons_plan": "benjamini-hochberg at q=0.10",
            "baseline": "NO_TRADE",
            "sample_selection_predefined": True,
            "embargo_minutes": 60,
            "splits": {
                "discovery": {"start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-03-01T00:00:00Z"},
                "validation": {"start_utc": "2026-03-02T00:00:00Z", "end_utc": "2026-05-01T00:00:00Z"},
                "holdout": {"start_utc": "2026-05-02T00:00:00Z", "end_utc": "2026-06-30T00:00:00Z"},
            },
            "holdout_past_consumed_exclusion": ["2026-08-06/2026-08-20"],
        },
        "economics": {
            "venue": "fixture-venue",
            "instrument_type": "spot",
            "fee_schedule_source": "published schedule, quoted in the registry",
            "maker_fee_bps_per_side": 2.0,
            "taker_fee_bps_per_side": 5.0,
            "slippage_bps_per_side": 1.0,
            "latency_ms": 250,
            "queue_assumptions": "no queue priority for a taker order",
            "post_only_rejections": "rejected order counts as unfilled, never as a fill",
            "partial_fill_policy": "partials carried, remainder cancelled at the horizon",
            "unfilled_orders_policy": "excluded from the trade count, reported separately",
            "adverse_selection_model": "one tick against the taker on every entry",
            "minimum_notional_usdt": 10.0,
            "tick_size_source": "venue instrument metadata, frozen in the registry",
            "lot_size_source": "venue instrument metadata, frozen in the registry",
            "max_leverage": 1,
            "max_position_notional_usdt": 100.0,
            "risk_rejection_policy": "rejection is logged and the bar is skipped",
        },
        "acceptance": {
            "min_oos_completed_trades": 100,
            "min_oos_trading_days": 20,
            "max_drawdown_usdt": 50.0,
            "min_profit_factor": 1.2,
            "stop_conditions": ["holdout loss greater than 5% of equity"],
            "require_positive_lower_95ci": True,
            "reject_if_any_data_lookahead": True,
            "reject_on_missing_realistic_costs": True,
        },
        "controls": {
            "point_in_time_join_policy": "join on bar close, decide on the next bar open",
            "lookahead_test_path": "tests/fixture_lookahead.py",
            "leakage_test_path": "tests/fixture_leakage.py",
            "future_mutation_test_path": "tests/fixture_mutation.py",
            "execution_command": "python -m trading_bot.research.prereg_gate --mode inspect",
            "builder_identity": "builder-agent",
            "independent_verifier_identity": "verifier-agent",
            "independent_verification_command": "python scripts/fixture_verify.py",
            "preexisting_runs_ledger_path": "config/prior_runs_ledger.json",
            "code_scope_paths": ["src/fixture/module.py"],
            "data_time_not_after_decision_time": True,
            "no_retune_on_holdout": True,
            "execution_mode": "OFFLINE_ONLY",
            "holdout_opened": False,
            "previous_results_exist": False,
            "previous_run_marker_paths": ["data/fixture/RUN_MARKER.json"],
        },
    }


def _ledger(experiment: str = EXPERIMENT) -> dict[str, Any]:
    return {
        "experiment_id": experiment,
        "inventory_completed": True,
        "inventory_method": "walked reports/, scripts/ and the git log",
        "inventory_utc": "2026-10-21T00:00:00Z",
        "executions": {experiment: 0},
        "runs": [],
    }


class Fixture:
    """A throwaway repository that the gate should authorise, and that tests then break."""

    def __init__(self, root: Path, experiment: str = EXPERIMENT) -> None:
        self.root = root
        self.experiment = experiment
        (root / "config").mkdir(parents=True)
        (root / "tests").mkdir(parents=True)
        for name in ("lookahead", "leakage", "mutation"):
            (root / "tests" / f"fixture_{name}.py").write_text(
                f"def test_{name}():\n    assert True\n", encoding="utf-8"
            )
        (root / "data" / "fixture").mkdir(parents=True)
        (root / "reports" / "ai-bots").mkdir(parents=True)
        (root / "src" / "fixture").mkdir(parents=True)
        (root / "src" / "fixture" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "config" / "universe.yaml").write_text("symbols: []\n", encoding="utf-8")
        dataset = root / "data" / "fixture" / "NOASSET.1m.jsonl.gz"
        dataset.write_bytes(b'{"ts":1,"close":2.0}\n')
        self.dataset = dataset
        self.manifest = _manifest(experiment)
        self.registry: dict[str, Any] = {"experiment_id": experiment, "entries": [self._entry()]}
        self.ledger = _ledger(experiment)
        self.write()
        subprocess.run(
            ["git", "init", "-q", "--initial-branch=main", str(root)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        self.code_commit = _commit(root, "fixture: complete frozen prereg")
        self.manifest["hypothesis"]["candidate_code_commit"] = self.code_commit
        self.write()
        self.head = _commit(root, "fixture: bind the candidate commit")

    def _entry(self) -> dict[str, Any]:
        digest = _sha(self.dataset) if hasattr(self, "dataset") else hashlib.sha256(
            b'{"ts":1,"close":2.0}\n'
        ).hexdigest()
        return {
            "dataset_id": "NOASSET-1M",
            "asset": "NOASSET",
            "venue": "fixture-venue",
            "instrument_type": "spot",
            "timeframe": "1m",
            "provider": "fixture",
            "source_url": "https://example.invalid/NOASSET-1m",
            "period_start_utc": "2026-01-01T00:00:00Z",
            "period_end_utc": "2026-06-30T23:59:00Z",
            "raw_file": "data/fixture/NOASSET.1m.jsonl.gz",
            "raw_sha256": digest,
            "normalized_file": "data/fixture/NOASSET.1m.jsonl.gz",
            "normalized_sha256": digest,
            "generator_command": "fixture-build --symbol NOASSET",
            "generator_parameters": {"timeframe": "1m"},
            "generator_code_commit": "1" * 40,
            "row_count": 1,
            "reproduction_status": "VERIFIED_LOCALLY",
        }

    # -- mutators ---------------------------------------------------------- #
    def write(self) -> None:
        (self.root / "config" / "preregistration.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )
        (self.root / "config" / "dataset_registry.json").write_text(
            json.dumps(self.registry, indent=2), encoding="utf-8"
        )
        (self.root / "config" / "prior_runs_ledger.json").write_text(
            json.dumps(self.ledger, indent=2), encoding="utf-8"
        )

    def freeze(self, message: str = "fixture: freeze") -> None:
        self.write()
        self.head = _commit(self.root, message)

    def evaluate(self, **kwargs: Any) -> dict[str, Any]:
        options: dict[str, Any] = {
            "repo": self.root,
            "experiment_id": self.experiment,
            "mode": "authorize",
        }
        options.update(kwargs)
        return gate.evaluate(**options)

    def run_dir(self, name: str) -> Path:
        path = self.root / "reports" / "ai-bots" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "FINAL_REPORT.md").write_text("# published\n", encoding="utf-8")
        return path


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path / "repo")


# --------------------------------------------------------------------------- #
# positive
# --------------------------------------------------------------------------- #
def test_complete_frozen_prereg_is_authorized(fx: Fixture) -> None:
    result = fx.evaluate()
    assert result["errors"] == []
    assert result["decision"] == gate.AUTHORIZED
    assert result["exit_code"] == 0
    assert result["economic_executions"] == 0
    assert result["runtime_earning_or_execution_validated"] is False
    assert f"IDENTIFIER_UNSPENT:{EXPERIMENT}" in result["checks"]
    assert "OFFLINE_PREFLIGHT_ONLY_NO_ECONOMIC_EXECUTION" in result["checks"]


def test_inspection_is_never_an_authorization(fx: Fixture) -> None:
    result = fx.evaluate(mode="inspect")
    assert result["errors"] == []
    assert result["decision"] == gate.INSPECTION_ONLY
    assert result["exit_code"] == 3, "a clean inspection must not exit 0"


def test_cli_exit_status_contract(fx: Fixture, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(fx.root)
    assert gate.main(["--repo", root, "--experiment-id", EXPERIMENT, "--mode", "authorize"]) == 0
    assert gate.main(["--repo", root, "--experiment-id", EXPERIMENT, "--mode", "inspect"]) == 3
    fx.manifest["controls"]["execution_mode"] = "LIVE"
    fx.write()
    assert gate.main(["--repo", root, "--experiment-id", EXPERIMENT, "--mode", "authorize"]) == 2
    assert "EXECUTION_NOT_OFFLINE_ONLY" in capsys.readouterr().err


def test_identifier_is_a_parameter_not_a_constant(tmp_path: Path) -> None:
    """The same fixture under a different identifier authorises with no code change."""
    other = Fixture(tmp_path / "other", experiment="EXP-777Z")
    result = other.evaluate(experiment_id="EXP-777Z")
    assert result["errors"] == []
    assert result["decision"] == gate.AUTHORIZED
    assert "EXP-003N" not in json.dumps(result), "the old identifier must not appear anywhere"


def test_manifest_must_name_the_requested_identifier(fx: Fixture) -> None:
    result = fx.evaluate(experiment_id="EXP-777Z")
    assert "EXPERIMENT_ID_MISMATCH_PREREG" in result["errors"]
    assert "EXPERIMENT_ID_MISMATCH_REGISTRY" in result["errors"]


# --------------------------------------------------------------------------- #
# negative — each defect alone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda m: m.__setitem__("status", "DRAFT_UNFROZEN"),
            {"PREREG_NOT_READY_TO_FREEZE", "PREREG_NOT_FROZEN"},
        ),
        (
            lambda m: m["hypothesis"].__setitem__("candidate_id", None),
            {"hypothesis.candidate_id.MISSING"},
        ),
        (
            lambda m: m["design"].__setitem__("splits", {}),
            {"SPLIT_DISCOVERY_MISSING", "SPLIT_VALIDATION_MISSING", "SPLIT_HOLDOUT_MISSING"},
        ),
        (
            lambda m: m["design"]["splits"]["validation"].__setitem__(
                "start_utc", "2026-03-01T00:00:00Z"
            ),
            {"SPLIT_VALIDATION_OVERLAP_OR_EMBARGO"},
        ),
        (
            lambda m: m["design"]["splits"]["holdout"].__setitem__(
                "start_utc", "2026-05-02T00:00:00+02:00"
            ),
            {"SPLIT_HOLDOUT_INVALID_UTC"},
        ),
        (
            lambda m: m["design"]["splits"]["holdout"].update(
                {"start_utc": "2026-08-07T00:00:00Z", "end_utc": "2026-08-19T00:00:00Z"}
            ),
            {"REUSED_PREVIOUSLY_INSPECTED_HOLDOUT"},
        ),
        (
            lambda m: m["design"].__setitem__("embargo_minutes", -1),
            {"SPLIT_EMBARGO_NOT_FROZEN"},
        ),
        (
            lambda m: m["design"].__setitem__("bootstrap_iterations", 100),
            {"BOOTSTRAP_ITERATIONS_INSUFFICIENT"},
        ),
        (
            lambda m: m["design"].__setitem__("sample_selection_predefined", False),
            {"SAMPLE_SELECTION_NOT_PREDEFINED"},
        ),
        (
            lambda m: m["economics"].__setitem__("maker_fee_bps_per_side", -3),
            {"INVALID_ECONOMIC_VALUE_maker_fee_bps_per_side"},
        ),
        (
            lambda m: m["acceptance"].__setitem__("require_positive_lower_95ci", False),
            {"MISSING_POSITIVE_CI_GATE"},
        ),
        (
            lambda m: m["acceptance"].__setitem__("reject_if_any_data_lookahead", False),
            {"MISSING_SAFETY_GATE_reject_if_any_data_lookahead"},
        ),
        (
            lambda m: m["controls"].__setitem__("execution_mode", "LIVE"),
            {"EXECUTION_NOT_OFFLINE_ONLY"},
        ),
        (
            lambda m: m["controls"].__setitem__("builder_identity", "same-agent")
            or m["controls"].__setitem__("independent_verifier_identity", "same-agent"),
            {"BUILDER_EQUALS_VERIFIER"},
        ),
        (
            lambda m: m["controls"].__setitem__("holdout_opened", True),
            {"HOLDOUT_NOT_SEALED"},
        ),
        (
            lambda m: m["controls"].__setitem__("no_retune_on_holdout", False),
            {"INVALID_CONTROL_no_retune_on_holdout"},
        ),
        (
            lambda m: m["controls"].__setitem__("execution_command", ""),
            {"controls.execution_command.MISSING"},
        ),
    ],
)
def test_each_defect_blocks_on_its_own(fx: Fixture, mutate: Any, expected: set[str]) -> None:
    assert fx.evaluate()["errors"] == [], "the fixture must authorise before it is broken"
    mutate(fx.manifest)
    fx.freeze("fixture: one defect")
    errors = set(fx.evaluate()["errors"])
    assert expected <= errors, errors
    assert fx.evaluate()["exit_code"] == 2


def test_tampered_dataset_bytes_block(fx: Fixture) -> None:
    assert fx.evaluate()["errors"] == []
    fx.dataset.write_bytes(b'{"ts":1,"close":2.1}\n')
    errors = fx.evaluate()["errors"]
    assert "DATASET_0_RAW_SHA256_MISMATCH" in errors
    assert "DATASET_0_NORMALIZED_SHA256_MISMATCH" in errors


def test_unverified_dataset_provenance_blocks(fx: Fixture) -> None:
    fx.registry["entries"][0]["reproduction_status"] = "NOT_VERIFIED"
    fx.freeze()
    assert "DATASET_0_PROVENANCE_NOT_VERIFIED" in fx.evaluate()["errors"]


def test_no_datasets_blocks(fx: Fixture) -> None:
    fx.registry["entries"] = []
    fx.freeze()
    assert "NO_DATASETS_REGISTERED" in fx.evaluate()["errors"]


def test_untracked_prereg_cannot_authorize(fx: Fixture) -> None:
    _git(fx.root, "rm", "--cached", "-q", "config/preregistration.json")
    _commit_staged(fx.root, "fixture: drop the manifest from the index")
    assert (fx.root / "config" / "preregistration.json").is_file()
    assert "GIT_NOT_TRACKED:config/preregistration.json" in fx.evaluate()["errors"]


def test_dirty_prereg_cannot_authorize(fx: Fixture) -> None:
    fx.manifest["design"]["bootstrap_seed"] = 999
    fx.ledger["inventory_method"] = "edited after the fact"
    fx.write()
    errors = fx.evaluate()["errors"]
    assert "GIT_DIRTY:config/preregistration.json" in errors
    assert "GIT_DIRTY:config/prior_runs_ledger.json" in errors


def test_candidate_commit_must_be_an_ancestor(fx: Fixture) -> None:
    fx.manifest["hypothesis"]["candidate_code_commit"] = "f" * 40
    fx.freeze()
    assert "CODE_COMMIT_NOT_ANCESTOR" in fx.evaluate()["errors"]


def test_dirty_runtime_code_blocks_authorization(fx: Fixture) -> None:
    assert fx.evaluate()["errors"] == []
    (fx.root / "src" / "fixture" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert "RUNTIME_CODE_DIRTY:src/fixture/module.py" in fx.evaluate()["errors"]


def test_code_scope_that_scopes_nothing_blocks(fx: Fixture) -> None:
    fx.manifest["controls"]["code_scope_paths"] = ["src/fixture/absent.py"]
    fx.freeze()
    assert "RUNTIME_CODE_SCOPE_MISSING:src/fixture/absent.py" in fx.evaluate()["errors"]


def test_missing_declared_paths_block(fx: Fixture) -> None:
    fx.manifest["controls"]["lookahead_test_path"] = "tests/does_not_exist.py"
    fx.freeze()
    assert "EVIDENCE_PATH_MISSING_lookahead_test_path" in fx.evaluate()["errors"]


# --------------------------------------------------------------------------- #
# adversarial — attempts to get past it
# --------------------------------------------------------------------------- #
def test_filling_nulls_after_authorization_is_caught(fx: Fixture) -> None:
    """The failure mode the whole gate exists for: complete the prereg after seeing the numbers."""
    assert fx.evaluate()["decision"] == gate.AUTHORIZED
    fx.manifest["hypothesis"]["candidate_id"] = "fixture/1h/NOASSET-chosen-after-results"
    fx.write()
    assert "GIT_DIRTY:config/preregistration.json" in fx.evaluate()["errors"]


def test_dropping_the_consumed_holdout_list_is_caught(fx: Fixture) -> None:
    fx.manifest["design"]["holdout_past_consumed_exclusion"] = []
    fx.freeze()
    errors = fx.evaluate()["errors"]
    assert "HOLDOUT_EXCLUSIONS_NOT_DECLARED" in errors
    assert "REUSED_PREVIOUSLY_INSPECTED_HOLDOUT" not in errors, "the list was emptied, not violated"


def test_consumed_holdout_may_be_empty_only_on_positive_assertion(fx: Fixture) -> None:
    fx.manifest["design"]["holdout_past_consumed_exclusion"] = []
    fx.manifest["controls"]["no_previously_consumed_holdout"] = True
    fx.freeze()
    assert "HOLDOUT_EXCLUSIONS_NOT_DECLARED" not in fx.evaluate()["errors"]


def test_ledger_inventory_must_be_completed(fx: Fixture) -> None:
    fx.ledger["inventory_completed"] = False
    fx.freeze()
    assert "PRIOR_RUNS_INVENTORY_NOT_COMPLETED" in fx.evaluate()["errors"]


def test_ledger_prior_run_blocks_even_when_written_in_the_legacy_shape(fx: Fixture) -> None:
    fx.ledger["executions"] = {}
    fx.ledger["exp_900a_executions"] = 1
    fx.freeze()
    errors = fx.evaluate()["errors"]
    assert f"PRIOR_RUNS_FOUND_{gate.normalise_id(EXPERIMENT)}_RETROSPECTIVE_ONLY" in errors


def test_ledger_prior_run_blocks_when_written_as_a_run_list(fx: Fixture) -> None:
    fx.ledger["executions"] = {EXPERIMENT: 0}
    fx.ledger["runs"] = [{"experiment_id": EXPERIMENT, "run_id": "any"}]
    fx.freeze()
    assert f"PRIOR_RUNS_FOUND_{gate.normalise_id(EXPERIMENT)}_RETROSPECTIVE_ONLY" in (
        fx.evaluate()["errors"]
    )


def test_ledger_that_disagrees_with_itself_is_read_pessimistically(fx: Fixture) -> None:
    fx.ledger["executions"] = {EXPERIMENT: 0}
    fx.ledger["exp_900a_executions"] = 3
    fx.freeze()
    assert f"PRIOR_RUNS_FOUND_{gate.normalise_id(EXPERIMENT)}_RETROSPECTIVE_ONLY" in (
        fx.evaluate()["errors"]
    )


def test_identifier_normalisation_cannot_hide_a_prior_run(fx: Fixture) -> None:
    fx.ledger["executions"] = {"exp_900a": 2}
    fx.freeze()
    assert f"PRIOR_RUNS_FOUND_{gate.normalise_id(EXPERIMENT)}_RETROSPECTIVE_ONLY" in (
        fx.evaluate()["errors"]
    )


def test_ledger_for_another_experiment_blocks(fx: Fixture) -> None:
    fx.ledger["experiment_id"] = "EXP-777Z"
    fx.freeze()
    assert "PRIOR_RUNS_LEDGER_WRONG_EXPERIMENT" in fx.evaluate()["errors"]


def test_a_published_run_directory_makes_the_identifier_spent(fx: Fixture) -> None:
    assert fx.evaluate()["decision"] == gate.AUTHORIZED
    fx.run_dir(f"{EXPERIMENT}-FIXTURE-001")
    errors = fx.evaluate()["errors"]
    assert f"SPENT_EXPERIMENT_IDENTIFIER:{EXPERIMENT}-FIXTURE-001" in errors


def test_a_neighbour_identifier_is_not_this_identifier(fx: Fixture) -> None:
    fx.run_dir("EXP-900AB-OTHER-001")
    assert fx.evaluate()["errors"] == [], "a boundary-safe match must not block a neighbour"


def test_run_directory_match_survives_case_and_separators(fx: Fixture) -> None:
    fx.run_dir("exp_900a_lowercase_001")
    assert any(
        error.startswith("SPENT_EXPERIMENT_IDENTIFIER:") for error in fx.evaluate()["errors"]
    )


def test_declared_marker_path_present_blocks(fx: Fixture) -> None:
    (fx.root / "data" / "fixture" / "RUN_MARKER.json").write_text("{}\n", encoding="utf-8")
    fx.freeze()
    assert "EXISTING_RUN_MARKER:data/fixture/RUN_MARKER.json" in fx.evaluate()["errors"]


def test_path_traversal_is_refused(fx: Fixture) -> None:
    outside = fx.root.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    fx.manifest["controls"]["preexisting_runs_ledger_path"] = "../outside.json"
    fx.freeze()
    assert "EVIDENCE_PATH_MISSING_preexisting_runs_ledger_path" in fx.evaluate()["errors"]
    assert gate.safely_under_repo(fx.root, "../outside.json") is None
    assert gate.safely_under_repo(fx.root, str(outside)) is None


def test_symlink_escape_is_refused(fx: Fixture) -> None:
    outside = fx.root.parent / "secret.json"
    outside.write_text('{"experiment_id": "EXP-900A"}', encoding="utf-8")
    link = fx.root / "config" / "ledger-link.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
        pytest.skip("symlinks unavailable in this environment")
    assert gate.safely_under_repo(fx.root, "config/ledger-link.json") is None


def test_previous_results_flag_in_any_shape_blocks(fx: Fixture) -> None:
    del fx.manifest["controls"]["previous_results_exist"]
    fx.manifest["controls"]["previous_exp900a_results_exists"] = True
    fx.freeze()
    assert "PREVIOUS_RESULTS_UNRESOLVED_OR_EXISTS" in fx.evaluate()["errors"]


def test_missing_previous_results_flag_blocks(fx: Fixture) -> None:
    del fx.manifest["controls"]["previous_results_exist"]
    fx.freeze()
    assert "PREVIOUS_RESULTS_UNRESOLVED_OR_EXISTS" in fx.evaluate()["errors"]


def test_gate_reads_nothing_from_the_repository_it_cannot_name(fx: Fixture) -> None:
    """A missing manifest is a block, not an exception and not a pass."""
    result = gate.evaluate(
        repo=fx.root,
        experiment_id=EXPERIMENT,
        manifest_path="config/absent.json",
        mode="authorize",
    )
    assert "PREREG_NOT_ACCESSIBLE" in result["errors"]
    assert result["decision"] == gate.BLOCKED


def test_authorization_does_not_mutate_the_repository(fx: Fixture) -> None:
    before = subprocess.run(
        ["git", "-C", str(fx.root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    fx.evaluate()
    after = subprocess.run(
        ["git", "-C", str(fx.root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    assert before == after


def test_unknown_mode_is_refused(fx: Fixture) -> None:
    with pytest.raises(ValueError):
        fx.evaluate(mode="authorize-anyway")


def test_fixture_cleanup_is_not_required_but_paths_are_inside(fx: Fixture) -> None:
    """Every declared path in the fixture resolves inside the fixture checkout."""
    for key in ("baseline_config_path", "candidate_config_path"):
        assert gate.safely_under_repo(fx.root, fx.manifest["hypothesis"][key]) is not None
    shutil.rmtree(fx.root / "reports" / "ai-bots", ignore_errors=True)
    assert gate.discover_existing_runs(fx.root, EXPERIMENT) == []
