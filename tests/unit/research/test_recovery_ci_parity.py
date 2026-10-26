"""Activation and content contract for the recovery-lane CI (WP-8E).

WP-8E requires the clean-checkout rehearsal to be **executable from CI**, and the
rehearsal itself distinguishes a GitHub runner from a workstation (``runner:
GITHUB_ACTIONS`` vs ``runner: LOCAL``). A workflow that exists but never fires, or
that drops the rehearsal when it is edited, would make that a comment rather than a
capability, so it is read here the way GitHub reads it: triggers, path filters and
the step bodies.

The workflow is parsed with PyYAML, independently of any string search inside the
lane's scripts. PyYAML resolves the bare key ``on`` to the boolean ``True`` under
YAML 1.1, so the loader below keeps such scalars as strings instead of hiding the
trigger block behind a try/except.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "recovery-determinism.yml"

REQUIRED_COMMANDS = (
    # the input authority is verified before anything is rebuilt from it
    "scripts/recovery_input_evidence.py --verify",
    # the repair's economic invariance is re-derived, not asserted
    "scripts/recovery_economic_invariance.py --check",
    # the lane's contract tests and the determinism regressions, including the
    # rehearsal and the two sabotage tests
    "tests/unit/research/test_active_recovery_wp.py",
    "tests/unit/research/test_recovery_determinism.py",
    # the rehearsal itself, in full scope
    "scripts/clean_checkout_rehearsal.py --scope full",
    # and the independent verifier on the artefacts the rehearsal published
    "scripts/recovery_verify.py",
)

REQUIRED_WATCHED = (
    "scripts/campaign_state_view.py",
    "scripts/active_economic_audit.py",
    "scripts/recovery_input_evidence.py",
    "scripts/clean_checkout_rehearsal.py",
    "data/recovery/CAMPAIGN_STATE_VIEW.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "PAPER_DATA_24H_REPORT.json",
    "config/strategy_admission.json",
    "tasks/decisions.md",
    ".github/workflows/recovery-determinism.yml",
)


def string_loader() -> type:
    """A SafeLoader that does not turn ``on``/``off``/``yes``/``no`` into booleans.

    The resolver table is copied before it is edited: ``SafeLoader`` inherits it from
    ``Resolver``, so mutating it in place would change YAML parsing for every other
    test in the session.
    """

    class Loader(yaml.SafeLoader):
        pass

    Loader.yaml_implicit_resolvers = {
        key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
        for key, resolvers in Loader.yaml_implicit_resolvers.items()
    }
    return Loader


def workflow() -> dict[str, Any]:
    assert WORKFLOW.exists(), f"the recovery workflow is missing: {WORKFLOW}"
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=string_loader())


def triggers(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.get("on") or doc.get(True) or {}


def steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return doc["jobs"]["recovery-determinism"]["steps"]


def run_commands(doc: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in steps(doc))


def test_the_workflow_fires_on_push_pull_request_and_dispatch():
    doc = workflow()
    fired = triggers(doc)
    assert set(fired) >= {"push", "pull_request", "workflow_dispatch"}, sorted(fired)
    for trigger in ("push", "pull_request"):
        filters = set(fired[trigger]["paths"])
        assert set(REQUIRED_WATCHED) <= filters, sorted(set(REQUIRED_WATCHED) - filters)
    assert triggers(doc)["push"]["branches"] == ["main"]


def test_every_step_the_rehearsal_needs_actually_runs():
    doc = workflow()
    commands = run_commands(doc)
    missing = [fragment for fragment in REQUIRED_COMMANDS if fragment not in commands]
    assert missing == [], missing


def test_the_rehearsal_runs_in_full_scope_and_is_not_replaced_by_a_subset():
    doc = workflow()
    commands = run_commands(doc)
    assert "--scope full" in commands
    assert "--no-report" not in commands, "a rehearsal that writes no report leaves nothing to check"
    # the sabotage side of the rehearsal is exercised through the determinism suite, which
    # this workflow runs; the workflow must not filter those tests away
    assert "-k " not in commands, "a filtered test run would silently drop the rehearsal tests"
    assert "not slow" not in commands, "the rehearsal tests are marked slow on purpose"


def test_the_evidence_is_kept_even_when_a_step_fails():
    doc = workflow()
    uploads = [step for step in steps(doc) if step.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads, "a green run has to leave an identifiable artefact behind"
    assert any(step.get("if") == "always()" for step in uploads), [step.get("if") for step in uploads]
    kept = str(uploads[0]["with"]["path"])
    assert "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json" in kept
    assert "data/recovery/INDEPENDENT_VERIFICATION.json" in kept


def test_no_step_can_be_softened():
    doc = workflow()
    for step in steps(doc):
        assert "continue-on-error" not in step, step.get("name")
        assert "|| true" not in str(step.get("run", "")), step.get("name")
        # the only tolerated conditional is the evidence upload: a failing run is exactly
        # the one whose evidence matters
        assert step.get("if") in (None, "always()"), (step.get("name"), step.get("if"))
    job = doc["jobs"]["recovery-determinism"]
    assert "continue-on-error" not in job
    assert job["timeout-minutes"] <= 30


def test_the_rehearsal_runs_against_a_commit_and_not_the_checked_out_tree():
    doc = workflow()
    checkout = next(step for step in steps(doc) if step.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0, "the rehearsal walks history to find the rehearsed commit"
    commands = run_commands(doc)
    assert "--commit" not in commands, "the default (HEAD of the checkout) is the commit under test"


def test_the_workflow_does_not_claim_to_be_a_required_gate():
    """A workflow cannot make itself required; claiming it would be a false assurance."""

    text = WORKFLOW.read_text(encoding="utf-8").lower()
    for claim in ("protected branch", "branch protection", "required status check", "required-check"):
        assert claim not in text, claim


def test_the_rehearsal_script_it_invokes_exists_and_refuses_a_dirty_tree():
    import importlib.util

    spec = importlib.util.spec_from_file_location("clean_checkout_rehearsal",
                                                  ROOT / "scripts" / "clean_checkout_rehearsal.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["clean_checkout_rehearsal"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.EXIT_REFUSED == 4
    covered = set(module.COVERED_PATHS)
    for rel in ("scripts/campaign_state_view.py", "scripts/active_economic_audit.py",
                "data/recovery/CAMPAIGN_STATE_VIEW.json", "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"):
        assert rel in covered, rel
    # the workflow is not among the paths under test: it is not an input of any artefact
    assert ".github/workflows/recovery-determinism.yml" not in covered
