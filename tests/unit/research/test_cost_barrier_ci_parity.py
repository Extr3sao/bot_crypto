"""Activation-contract tests for the cost-barrier CI (WP-7D, attack 14).

A gate that CI cannot trigger is decoration: the cheapest way to neuter a status
check is to move the dependency it watches to a path nobody filters on. Nothing
in any digest changes when that happens, so the only defence is a contract test
that reads the workflow the way GitHub does and compares it with what the gate
declares it depends on.

The workflow is parsed with PyYAML here, independently of the line scanner inside
the gate, so the two implementations have to agree - and the gate's own scanner is
held to the same conclusion in ``test_cost_barrier_gate.py``. PyYAML resolves the
bare key ``on`` to the boolean ``True`` under YAML 1.1, so the loader below keeps
those scalars as strings rather than hiding the trigger block behind a try/except.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "cost-barrier-gate.yml"
GATE = ROOT / "scripts" / "cost_barrier_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("cost_barrier_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cost_barrier_gate"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def string_loader() -> type:
    """A SafeLoader that does not turn ``on``/``off``/``yes``/``no`` into booleans."""
    base = yaml.SafeLoader

    class Loader(base):  # type: ignore[misc, valid-type]
        pass

    Loader.yaml_implicit_resolvers = {
        key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
        for key, resolvers in base.yaml_implicit_resolvers.items()
    }
    return Loader


def workflow() -> dict[str, Any]:
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=string_loader())
    assert isinstance(document, dict)
    return document


def triggers(document: dict[str, Any]) -> dict[str, Any]:
    block = document.get("on")
    assert isinstance(block, dict), f"the workflow has no readable `on:` block: {block!r}"
    return block


def filtered_paths(trigger: str) -> list[str]:
    block = triggers(workflow())[trigger]
    paths = block.get("paths")
    assert isinstance(paths, list) and paths, f"{trigger} carries no paths filter"
    return [str(item) for item in paths]


def steps() -> list[dict[str, Any]]:
    jobs = workflow()["jobs"]
    assert isinstance(jobs, dict)
    rows: list[dict[str, Any]] = []
    for job in jobs.values():
        rows.extend(job.get("steps") or [])
    return rows


def test_the_workflow_fires_on_both_triggers_with_identical_filters():
    push = filtered_paths("push")
    pull = filtered_paths("pull_request")
    assert set(push) == set(pull), set(push) ^ set(pull)
    assert triggers(workflow())["pull_request"]["branches"] == ["main"]


def test_every_path_the_gate_depends_on_can_activate_the_workflow():
    gate = load_gate()
    push = filtered_paths("push")
    missing = [
        rel for rel in gate.CI_WATCHED if not any(fnmatch.fnmatch(rel, pattern) for pattern in push)
    ]
    assert missing == [], f"a change to {missing} would not run the gate"
    # The independent parser and the gate's own scanner must agree.
    assert gate.workflow_coverage_failures()[0] == []


def test_the_declared_inputs_and_the_pinned_artefacts_are_watched():
    gate = load_gate()
    push = filtered_paths("push")
    for rel in (
        *(rel for rel, _role, _pinned in gate.DECLARED_INPUTS),
        gate.EXPLORER,
        gate.VERIFICATION,
        gate.PRODUCER_PINS_PATH,
    ):
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in push), rel


def test_the_gate_runs_in_full_mode_with_materialized_inputs():
    text = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert "cost_barrier_evidence.py" in code and "--materialize" in code
    assert "cost_barrier_gate.py" in code
    # The gate is invoked without --check, so the job cannot settle for a partial run.
    assert "--check" not in code


def test_the_adversarial_suite_and_the_certifier_run_and_evidence_is_kept():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cost_barrier_adversarial.py" in text
    assert "cost_barrier_certify.py" in text
    assert "actions/upload-artifact@v4" in text
    upload = next(row for row in steps() if "upload-artifact" in str(row.get("uses", "")))
    assert upload.get("if") == "always()", "the evidence must be kept even when a step fails"
    assert upload["with"]["if-no-files-found"] == "error"


def test_no_step_can_be_softened():
    text = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert "continue-on-error" not in code
    for row in steps():
        assert row.get("continue-on-error") is not True, row
        assert "|| true" not in str(row.get("run", "")), row


def test_the_workflow_does_not_claim_to_be_a_required_gate():
    # quality/release-gates.md Bloque 6 pins four required checks; this workflow is
    # additive and must not pretend otherwise.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Not a required status check" in text


LANE_SCRIPTS: tuple[str, ...] = (
    "cost_barrier_gate",
    "cost_barrier_evidence",
    "cost_barrier_adversarial",
    "cost_barrier_certify",
    "cost_barrier_explorer",
    "cost_barrier_verify",
)


def project_files() -> list[str]:
    """Tracked files plus untracked-but-not-ignored ones: the tree a checkout sees."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.splitlines()


def test_tests_ci_and_the_runtime_all_run_the_same_bytes():
    """TEST_TARGET == RUNTIME_TARGET, checked rather than assumed.

    One tracked copy of each lane script, in ``scripts/``, invoked by the workflow
    under that same path and imported by the tests from that same path. A second
    copy (a vendored duplicate, an installed variant, a stale fork in the tree)
    would let CI and the tests exercise different code while both looked green.
    """
    files = project_files()
    for name in LANE_SCRIPTS:
        matches = sorted(rel for rel in files if rel.rsplit("/", 1)[-1] == f"{name}.py")
        assert matches == [f"scripts/{name}.py"], matches
        assert (ROOT / matches[0]).exists()

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "cost_barrier_gate",
        "cost_barrier_evidence",
        "cost_barrier_adversarial",
        "cost_barrier_certify",
    ):
        assert f"scripts/{name}.py" in workflow_text, name

    gate = load_gate()
    for rel in (gate.BUILDER, gate.VERIFIER, gate.CHECKER):
        assert rel in files and rel.startswith("scripts/")


def test_the_gitignored_evidence_copy_survives_a_checkout_in_the_pinned_form():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "data/recovery/wp7/evidence/** -text" in attributes


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def git_blob(rel: str) -> bytes:
    """The bytes git stores for a path - what a checkout on any platform starts from."""
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def load_evidence():
    return _load(ROOT / "scripts" / "cost_barrier_evidence.py")


def test_the_producer_pins_survive_a_checkout_that_rewrites_line_endings():
    """The defect a clean-checkout rehearsal found, held shut.

    ``core.autocrlf`` rewrites line endings on checkout without touching content,
    so the same commit presents different bytes in a clean worktree than in the
    tree a pin was written in. Pinning the raw digest of the authoring tree made
    three producers look edited on every clean checkout, and the manifest now
    records the LF and CRLF content forms as its authorities.
    """
    evidence = load_evidence()
    manifest = json.loads((ROOT / evidence.PRODUCER_PINS).read_text(encoding="utf-8"))
    rows = manifest["producers"]
    assert rows, "the manifest pins no producers"
    for row in rows:
        blob = git_blob(row["path"])
        lf = blob.replace(b"\r\n", b"\n")
        assert row["sha256_lf"] == evidence.sha256_bytes(lf), row["path"]
        assert row["sha256_crlf"] == evidence.sha256_bytes(lf.replace(b"\n", b"\r\n")), row["path"]
        for data in (lf, lf.replace(b"\n", b"\r\n")):
            status = evidence.eol_status(row["sha256"], data)
            assert evidence.admissible(status), (row["path"], status)
        # Content drift is still drift, whichever convention it arrives in.
        changed = lf[: len(lf) // 2] + b"\n# edited by an attacker\n" + lf[len(lf) // 2 :]
        assert evidence.eol_status(row["sha256"], changed) == evidence.PIN_DRIFT, row["path"]
        assert not evidence.admissible(evidence.PIN_DRIFT)


def test_the_gate_and_the_evidence_bundle_agree_on_what_a_producer_drift_is():
    # Two implementations of the same judgement; a mismatch would let CI and the
    # gate disagree about whether a pin held.
    gate = load_gate()
    evidence = load_evidence()
    lf = b"alpha\nbeta\n"
    for data in (lf, b"alpha\r\nbeta\r\n", b"alpha\nbeta"):
        pin = evidence.sha256_bytes(lf)
        assert gate.pin_status(pin, data) == evidence.eol_status(pin, data), data
        assert evidence.admissible(evidence.eol_status(pin, data)) is (
            gate.pin_status(pin, data) != gate.PIN_DRIFT
        ), data
