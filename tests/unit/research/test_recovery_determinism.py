"""WP-8F — determinism and provenance regressions for the ACTIVE recovery lane.

These hold the WP-8 repairs to their claims. Each test names the defect it would catch
if it came back, because a regression test whose failure mode nobody remembers is a
test nobody dares change:

* a later ADR supersedes an earlier one without rewriting it, and two records at the
  same level still contradict each other;
* a CRLF checkout is the same commit (content digests, not raw bytes) and a real
  content change is still drift;
* an untracked ``data/rfcNNN/`` directory cannot move a certified RFC occupancy;
* an uncommitted edit to a committed, attested document cannot move the view's
  identity, because committed content is read from the commit;
* repeated reproduction is byte-identical, and the external inputs a finding rests on
  are all committed with a digest that answers to a published authority;
* the clean-checkout rehearsal passes on this commit, and a deliberate sabotage of an
  input inside that clean checkout is detected.

The rehearsal tests run ``scripts/clean_checkout_rehearsal.py`` in a throwaway
``git worktree`` and are marked ``slow``: they are the only tests here that prove the
sequence end to end rather than one rule at a time.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"
ATTESTED_DOCUMENT = "docs/governance/DISCOVERY_STOP_RULES.md"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def state_view():
    return load_script("campaign_state_view")


@pytest.fixture(scope="module")
def audit():
    return load_script("active_economic_audit")


@pytest.fixture(scope="module")
def authority():
    return load_script("recovery_input_evidence")


@pytest.fixture(scope="module")
def view_payload(state_view) -> dict[str, Any]:
    return state_view.build()


@pytest.fixture(scope="module")
def audit_payload(audit) -> dict[str, Any]:
    return audit.build()


# --------------------------------------------------------------------------- #
# precedence: a later ADR supersedes, it does not rewrite
# --------------------------------------------------------------------------- #


def test_a_later_adr_supersedes_an_earlier_one_without_rewriting_it(state_view):
    text = (
        "## ADR-0100 - first decision\n"
        "`NEXT_CAMPAIGN = AUTHORIZED`\n"
        "## ADR-0101 - the decision that supersedes it\n"
        "`NEXT_CAMPAIGN = NOT_AUTHORIZED`\n"
    )
    adrs = state_view.parse_adrs(text)
    assert [adr["adr"] for adr in adrs] == ["ADR-0100", "ADR-0101"]

    facts = [{"field": "NEXT_CAMPAIGN", "role": "P4_frozen_declaration", "value": "FROZEN", "present": True,
              "source": "frozen.json", "pointer": "gate", "priority": 4}]
    resolution = state_view.resolve_field("C", "NEXT_CAMPAIGN", facts, adrs)
    assert resolution["effective"] == "NOT_AUTHORIZED"
    assert resolution["decided_by"]["source"].endswith("ADR-0101")
    # the superseded value is kept, not erased: the trail is the point
    assert {entry["value"] for entry in resolution["superseded"]} == {"AUTHORIZED", "FROZEN"}
    assert resolution["contradiction"] is None


def test_a_governed_disagreement_resolves_but_an_ungoverned_one_does_not(state_view):
    facts = [
        {"field": "STATE", "role": "P2_campaign_record", "value": "CLOSED", "present": True,
         "source": "a.json", "pointer": "x", "priority": 2},
        {"field": "STATE", "role": "P2_campaign_record", "value": "OPEN", "present": True,
         "source": "b.json", "pointer": "y", "priority": 2},
    ]
    assert state_view.resolve_field("C", "STATE", facts, [])["contradiction"] is not None

    governed = [{"adr": "ADR-0200", "number": 200, "facts": {"STATE": "CLOSED"},
                 "terminal_state_tokens": [], "title": "", "facts_conflicts": {}, "body_chars": 0}]
    resolution = state_view.resolve_field("C", "STATE", facts, governed)
    assert resolution["effective"] == "CLOSED"
    assert resolution["contradiction"] is None


# --------------------------------------------------------------------------- #
# byte conventions: content digests, so a checkout is not a change
# --------------------------------------------------------------------------- #


def test_a_crlf_checkout_is_the_same_content_and_a_content_change_is_drift(authority):
    raw = (ROOT / "config" / "strategy_admission.json").read_bytes()
    lf = authority.eol_forms(raw)["LF"]
    crlf = authority.eol_forms(raw)["CRLF"]
    assert crlf != lf, "the fixture must actually differ in bytes"

    # the two byte conventions of one commit are one state ...
    pin = authority.sha256_bytes(lf)
    assert authority.grade(pin, lf) == authority.VERIFIED
    assert authority.grade(pin, crlf) == authority.VERIFIED
    assert authority.content_grade({"sha256_crlf": authority.sha256_bytes(crlf)}, crlf) == authority.VERIFIED
    # ... which is why a raw-bytes pin (the pre-WP-8 convention) could not be satisfied in both
    assert authority.sha256_bytes(crlf) != authority.sha256_bytes(lf)

    # and a real content change is still drift, in either form
    assert authority.grade(pin, crlf + b" ") == authority.DRIFTED
    assert authority.content_grade({"sha256_lf": pin}, lf + b"\n") == authority.DRIFTED


def test_every_evidence_copy_reproduces_the_published_authority(authority):
    failures = authority.reproduction_evidence_failures()
    assert failures == [], failures
    assert authority.declared_input_failures() == []

    declared = authority.declarations()
    assert {record["class"] for record in declared.values()} == {
        authority.COMMITTED, authority.EXTERNAL_GENERATED, authority.EXTERNAL_LIVE, authority.EXTERNAL_DATASET,
    }
    for rel, record in declared.items():
        if record["class"] == authority.COMMITTED or not record["required_to_reproduce_a_finding"]:
            continue
        assert record["evidence_copy"]["in_head"] is True, rel
        assert record["evidence_copy"]["sha256_lf"], rel


def test_the_inert_external_inputs_do_not_gate_a_finding(authority):
    """The gitignored datasets are graded when present and are not a contradiction when not."""
    datasets = [record for record in authority.declarations().values()
                if record["class"] == authority.EXTERNAL_DATASET]
    assert datasets, "the frozen price series are declared"
    assert all(record["required_to_reproduce_a_finding"] is False for record in datasets)
    # whether the file happens to sit on this machine is an observation, not an invariant
    assert all("evidence_copy" not in record or record["evidence_copy"] is None for record in datasets)
    for observation in authority.observations():
        if observation["class"] == authority.EXTERNAL_DATASET:
            assert observation["resolved_from"] in ("LOCAL_MATERIALIZATION", "ABSENT")


def test_the_observations_are_outside_the_identity(state_view, view_payload):
    assert "local_observations" in state_view.VOLATILE_KEYS
    stripped = {k: v for k, v in view_payload.items() if k != "local_observations"}
    assert state_view.payload_hash(stripped) == state_view.payload_hash(view_payload)
    assert view_payload["local_observations"], "the observations are published, just not certifying"


# --------------------------------------------------------------------------- #
# dirty and absent inputs cannot enter a certified state
# --------------------------------------------------------------------------- #


def test_an_uncommitted_edit_to_a_committed_document_cannot_move_the_identity(state_view):
    """Committed content is read from the commit, so a working-tree edit is not a state."""
    path = ROOT / ATTESTED_DOCUMENT
    original = path.read_bytes()
    before = state_view.payload_hash(state_view.build())
    dirty = subprocess.run(["git", "status", "--porcelain", "--", ATTESTED_DOCUMENT],
                           cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    if dirty:
        pytest.skip(f"{ATTESTED_DOCUMENT} is already modified in this checkout")
    try:
        path.write_bytes(original + b"\n<!-- an uncommitted edit that must not be certified -->\n")
        after = state_view.payload_hash(state_view.build())
    finally:
        path.write_bytes(original)
    assert after == before, "an uncommitted edit changed the certified identity"


def test_an_untracked_data_directory_cannot_move_the_certified_occupancy(state_view, view_payload):
    probe = ROOT / "data" / "rfc050"
    assert not probe.exists(), "the probe directory already exists; pick another number"
    try:
        probe.mkdir()
        (probe / "PROBE.json").write_text("{}\n", encoding="utf-8")
        assert state_view.payload_hash(state_view.build()) == state_view.payload_hash(view_payload)
        fresh = state_view.build()
    finally:
        (probe / "PROBE.json").unlink(missing_ok=True)
        probe.rmdir()
    assert fresh["rfc_numbering"] == view_payload["rfc_numbering"]


def test_repeated_reproduction_is_byte_identical(state_view, audit, view_payload, audit_payload):
    """Everything but the moment (head, branch, timestamp, per-machine observations) repeats."""

    def body(module, payload):
        return json.dumps({k: v for k, v in payload.items() if k not in module.VOLATILE_KEYS},
                          indent=2, ensure_ascii=False, sort_keys=True)

    assert body(state_view, state_view.build()) == body(state_view, view_payload)
    assert audit.payload_hash(audit.build()) == audit.payload_hash(audit_payload)
    assert body(audit, audit.build()) == body(audit, audit_payload)

    # and the published artefacts carry the identity of the state that was just rebuilt
    stored = json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))
    stored_audit = json.loads((RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json").read_text(encoding="utf-8"))
    assert stored["payload_sha256"] == state_view.payload_hash(view_payload)
    assert stored_audit["payload_sha256"] == audit.payload_hash(audit_payload)


def test_the_published_artefacts_report_reproducibility_invariants(view_payload, audit_payload):
    by_id = {item["id"]: item for item in view_payload["invariants"]}
    assert by_id["I7_inputs_are_reproducible"]["result"] == "PASS", by_id["I7_inputs_are_reproducible"]
    assert by_id["I5_governance_mirrors_agree"]["coverage"]["shared_flags"] > 0
    checks = {item["check"]: item for item in audit_payload["checks"]}
    key = "inputs:every_external_input_resolves_from_the_commit"
    assert checks[key]["result"] == "PASS", checks[key]


def test_no_source_of_either_artefact_came_from_the_working_tree(view_payload, audit_payload):
    allowed = {"HEAD", "EVIDENCE_COPY", "LOCAL_MATERIALIZATION"}
    offenders = [
        f"{row['path']}:{row['resolved_from']}"
        for row in [*view_payload["sources"], *audit_payload["sources"]]
        if row.get("resolved_from") not in allowed
    ]
    assert offenders == [], offenders
    assert view_payload["sources_unchanged"] is True


def test_the_repair_moved_no_economic_finding():
    """WP-8D is a provenance repair: the published numbers must be the same numbers.

    The comparison is re-derived here from the two commits (never from the evidence file
    alone), so a changed finding fails this test even if the evidence were regenerated.
    """

    invariance = load_script("recovery_economic_invariance")
    fresh = invariance.compare()
    assert fresh["verdict"] == "IDENTICAL", json.dumps(fresh["audit"]["changed_findings"])
    assert fresh["audit"]["changed_findings"] == []
    assert fresh["state_view"]["campaign_effective_state_identical"] is True
    assert fresh["headline"] == {
        "per_strategy_records_identical": True,
        "aggregates_identical": True,
        "admitted_for_paper_before": 0,
        "admitted_for_paper_after": 0,
        "net_positive_count_before": 0,
        "net_positive_count_after": 0,
    }

    committed = json.loads((RECOVERY / "wp8" / "evidence" / "ECONOMIC_INVARIANCE.json")
                           .read_text(encoding="utf-8"))
    assert committed["generated_by"] == "scripts/recovery_economic_invariance.py"
    assert committed["verdict"] == fresh["verdict"]
    assert committed["before_commit"] == fresh["before_commit"]
    assert committed["after_commit"] == fresh["after_commit"]
    assert committed["headline"] == fresh["headline"]
    for side in ("audit", "state_view"):
        assert committed[side]["identical_findings"] == fresh[side]["identical_findings"]
        assert committed[side]["changed_findings"] == fresh[side]["changed_findings"]
    # the one intended change is declared rather than smoothed away
    assert fresh["state_view"]["changed_findings"] == ["advisories"]
    assert fresh["expected_changes"]


# --------------------------------------------------------------------------- #
# the rehearsal, end to end
# --------------------------------------------------------------------------- #


def run_rehearsal(*extra: str) -> tuple[dict[str, Any], int]:
    rehearsal = load_script("clean_checkout_rehearsal")
    return rehearsal.rehearse(None, "recovery", extra[0] if extra else None, keep_worktree=False)


@pytest.mark.slow
def test_the_clean_checkout_rehearsal_passes_on_this_commit():
    report, code = run_rehearsal()
    assert report["status"] == "PASS", json.dumps(
        {"status": report["status"], "failed": report.get("failed_steps"),
         "moved": report["published_paths_moved"], "steps": report["steps"]}, indent=2)[:2000]
    assert code == 0
    assert report["published_paths_moved"] == []
    assert all(entry["identical"] for entry in report["artifacts"].values()), report["artifacts"]
    # the rehearsal reaches the artefacts from the commit, never from the original inputs
    verify_step = next(item for item in report["steps"] if item["step"] == "verify_recovery_input_bundle")
    assert verify_step["result"] == "PASS"
    for observation in json.loads((RECOVERY / "CAMPAIGN_STATE_VIEW.json").read_text(encoding="utf-8"))[
            "local_observations"]:
        if observation["class"] == "EXTERNAL_GENERATED":
            assert observation["resolved_from"] == "EVIDENCE_COPY"


@pytest.mark.slow
def test_a_sabotaged_evidence_copy_is_detected():
    report, code = run_rehearsal("evidence_copy")
    assert report["status"] == "SABOTAGE_DETECTED", json.dumps(report["sabotage"], indent=2)
    assert report["sabotage"]["detected"] is True
    assert report["sabotage"]["detected_by"]
    assert code == 0


@pytest.mark.slow
def test_a_sabotaged_committed_input_is_detected():
    """A quiet authorization injected into a committed input must move a published artefact."""
    report, code = run_rehearsal("committed_input")
    assert report["status"] == "SABOTAGE_DETECTED", json.dumps(
        {"sabotage": report["sabotage"], "failed": report.get("failed_steps")}, indent=2)
    assert report["sabotage"]["detected"] is True
    assert code == 0
