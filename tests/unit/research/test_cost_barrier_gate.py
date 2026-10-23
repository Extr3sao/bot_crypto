"""Contract tests for the COST-BARRIER DRIFT GATE (WP-6 follow-on, hardened in WP-7).

The gate is held to what it claims:

* on the committed state it reproduces every published number - the builder
  rebuilds the explorer bit for bit and the verifier stays PASS with 13/13
  mutation controls;
* a published number that moved, even with the self-hash recomputed honestly, is
  a visible failure naming the exact field;
* a zeroed self-hash, a rewritten verification verdict and a flipped governance
  flag are each caught without re-running the builder;
* a cited input whose content changed is content drift and fails the gate (the
  artefact must be regenerated), while a line-ending-only difference is not;
* the published market-horizon section is re-derived here from the pinned source,
  which is the only thing standing between an honestly re-hashed derived number
  and a silent pass in check mode;
* the four producers that had no pin are held to the digest manifest, and the
  manifest may not pin the checker itself;
* the CI activation contract still covers every declared input, the gate and the
  materializer - a dependency moved under an unwatched path would make the whole
  thing decorative;
* the six-state contract is total: only FULL_REPRODUCTION_PASS satisfies a
  full-certification requirement, one distinct exit code per state, and a
  check-only run is partial by construction;
* the gate never writes to the published artefacts or the inputs it watches;
* the gate's own six controls detect every tamper - a vacuous comparison cannot
  pass;
* advisories are escalated only under --strict.

Tampering is always performed on copies in ``tmp_path``: the published artefacts
are never modified by these tests. Where a test needs a tree that the gate treats
as its root (producer pins, the CI workflow), it builds one and points the
module's ``ROOT`` at it rather than touching the real one.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"
GATE = ROOT / "scripts" / "cost_barrier_gate.py"
WORKFLOW = ROOT / ".github" / "workflows" / "cost-barrier-gate.yml"
EVIDENCE_DIR = RECOVERY / "wp7" / "evidence"
PRODUCER_PINS = EVIDENCE_DIR / "PRODUCER_PINS.json"
PRODUCER_PINS_REL = "data/recovery/wp7/evidence/PRODUCER_PINS.json"
PRODUCERS = (
    "scripts/active_economic_audit.py",
    "scripts/cost_barrier.py",
    "scripts/cost_barrier_explorer.py",
    "scripts/cost_barrier_verify.py",
)


def load_gate():
    spec = importlib.util.spec_from_file_location("cost_barrier_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cost_barrier_gate"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def args_for(
    gate,
    explorer: str | None = None,
    verification: str | None = None,
    check: bool = False,
    strict: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        check=check,
        strict=strict,
        explorer=explorer if explorer is not None else gate.EXPLORER,
        verification=verification if verification is not None else gate.VERIFICATION,
        json=False,
        report=None,
    )


def copy_explorer(tmp_path: Path) -> tuple[dict, Path]:
    doc = json.loads((RECOVERY / "COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8"))
    path = tmp_path / "COST_BARRIER_EXPLORER.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return doc, path


def copy_verification(tmp_path: Path) -> tuple[dict, Path]:
    doc = json.loads((RECOVERY / "COST_BARRIER_VERIFICATION.json").read_text(encoding="utf-8"))
    path = tmp_path / "COST_BARRIER_VERIFICATION.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return doc, path


def rehash(gate, doc: dict) -> None:
    """Recompute the self-hash the way the artefact defines it."""
    doc["payload_sha256"] = gate.payload_hash(doc)


def check_by_name(report: dict, name: str) -> dict:
    rows = [row for row in report["checks"] if row["check"] == name]
    assert rows, f"no check named {name} in {[row['check'] for row in report['checks']]}"
    return rows[0]


# --------------------------------------------------------------------------- #
# the committed state
# --------------------------------------------------------------------------- #


def test_the_gate_reproduces_the_committed_state_in_full_mode():
    gate = load_gate()
    report = gate.build_report(args_for(gate))
    assert report["status"] == gate.FULL_REPRODUCTION_PASS, report["failures"]
    assert report["exit_code"] == 0
    assert report["certification"]["satisfies_full_certification"] is True
    assert report["checks_failed"] == 0
    assert report["controls_missed"] == 0
    assert check_by_name(report, "reproduce:explorer_rebuilds_identically")["result"] == "PASS"
    assert check_by_name(report, "reproduce:verifier_passes")["result"] == "PASS"
    assert check_by_name(report, "reproduce:verification_document_unchanged")["result"] == "PASS"
    assert (
        check_by_name(report, "inputs:published_pins_match_the_declared_sources")["result"]
        == "PASS"
    )


def test_check_mode_is_partial_and_says_so():
    gate = load_gate()
    report = gate.build_report(args_for(gate, check=True))
    assert report["status"] == gate.CHECK_ONLY_PASS, report["failures"]
    assert report["exit_code"] == gate.EXIT_PARTIAL
    assert report["certification"]["satisfies_full_certification"] is False
    assert report["certification"]["is_partial"] is True
    names = {row["check"] for row in report["checks"]}
    assert "reproduce:explorer_rebuilds_identically" not in names
    assert "reproduce:verifier_passes" in names


def test_the_cli_has_one_exit_code_per_state(tmp_path):
    # A partial run is not a pass: the exit code says so, distinctly.
    clean_check = subprocess.run(
        [sys.executable, str(GATE), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert clean_check.returncode == 2, clean_check.stdout + clean_check.stderr

    full = subprocess.run([sys.executable, str(GATE)], cwd=ROOT, capture_output=True, text=True)
    assert full.returncode == 0, full.stdout + full.stderr

    doc, path = copy_explorer(tmp_path)
    doc["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    tampered = subprocess.run(
        [sys.executable, str(GATE), "--check", "--explorer", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert tampered.returncode == 5
    assert "INTEGRITY_FAILURE" in tampered.stdout


# --------------------------------------------------------------------------- #
# negative controls (tampered copies only)
# --------------------------------------------------------------------------- #


def test_a_moved_number_with_an_honest_rehash_is_caught(tmp_path):
    """The artefact is edited *after* it was verified, and says so.

    WP-7 made this land on INTEGRITY_FAILURE rather than
    FULL_REPRODUCTION_FAIL, and that is the stricter answer: the published
    verification document cross-pins the artefact's payload hash, so an edited
    copy is not merely a failed re-run, it is a document that no longer attests
    what it claims to attest. Either way nothing here can satisfy certification.
    """
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["cells"][0]["zero_cost_gross_bps"] += 5.0
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path)))
    assert report["status"] in (gate.INTEGRITY_FAILURE, gate.FULL_REPRODUCTION_FAIL)
    assert report["certification"]["satisfies_full_certification"] is False
    failure = check_by_name(report, "reproduce:explorer_rebuilds_identically")
    assert failure["result"] == "FAIL"
    assert "zero_cost_gross_bps" in failure["detail"]
    assert any("zero_cost_gross_bps" in item for item in report["failures"])


def test_a_reproduction_divergence_is_its_own_state_when_nothing_is_contradictory():
    """FULL_REPRODUCTION_FAIL exists for exactly this case, and is not a pass."""
    gate = load_gate()
    status = gate.decide_status(
        mode="full",
        integrity=[],
        reproduction=["the rebuild differed"],
        blocked=[],
        advisories=[],
    )
    assert status == gate.FULL_REPRODUCTION_FAIL
    assert status not in gate.FULL_CERTIFICATION_STATUSES
    assert gate.exit_code(status) == gate.EXIT_REPRODUCTION_FAIL


def test_a_zeroed_self_hash_is_caught_without_any_rerun(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    assert check_by_name(report, "artifact:explorer_self_hash_and_checks")["result"] == "FAIL"


def test_a_rewritten_verification_verdict_is_caught(tmp_path):
    gate = load_gate()
    doc, path = copy_verification(tmp_path)
    doc["status"] = "FAIL"
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, verification=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    assert check_by_name(report, "artifact:verification_attests_the_explorer")["result"] == "FAIL"


def test_a_flipped_governance_flag_is_caught(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["claims"]["rentable_claimed"] = True
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    check = check_by_name(report, "artifact:explorer_governance_flags_unchanged")
    assert check["result"] == "FAIL"
    assert "rentable_claimed" in check["detail"]


def test_a_foreign_pin_is_content_drift_and_fails_the_gate(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    target = "src/trading_bot/research/microstructure/cost_model_v3.py"
    for row in doc["sources"]:
        if row["path"] == target:
            row["sha256"] = "0" * 64  # the cited input no longer matches what was built from
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    check = check_by_name(report, "inputs:published_pins_match_the_declared_sources")
    assert check["result"] == "FAIL"
    assert "content drift" in check["detail"]
    assert any("regenerated" in item for item in report["failures"])


# --------------------------------------------------------------------------- #
# the market-horizon section, re-derived from the pinned source
# --------------------------------------------------------------------------- #


def test_the_published_market_horizon_section_reproduces_from_the_pinned_source():
    gate = load_gate()
    explorer = json.loads((RECOVERY / "COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8"))
    barrier = json.loads((ROOT / gate.MARKET_HORIZON_SOURCE).read_text(encoding="utf-8"))
    assert gate.market_horizon_failures(explorer, barrier) == []
    rows = gate.market_horizon_rows(barrier)
    assert len(rows) == 12  # four timeframes x three assets


def test_a_moved_market_horizon_row_is_caught_by_the_re_derivation(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["horizon"]["market_horizon"]["rows"][0]["hours_to_BASE"] = 99.0
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    check = check_by_name(report, "source:market_horizon_rows_match_the_pinned_source")
    assert check["result"] == "FAIL"
    assert "hours_to_BASE" in check["detail"]


def test_a_moved_published_lines_block_is_caught(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["horizon"]["market_horizon"]["published_lines_bps"]["BASE"] = 11.0
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")
    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    assert (
        "published_lines_bps"
        in check_by_name(report, "source:market_horizon_rows_match_the_pinned_source")["detail"]
    )


# --------------------------------------------------------------------------- #
# the drift rule itself
# --------------------------------------------------------------------------- #


def test_pin_candidates_tell_line_endings_apart_from_content_drift():
    gate = load_gate()
    crlf_pin = gate.sha256_bytes(b"alpha\r\nbeta\r\n")
    lf_pin = gate.sha256_bytes(b"alpha\nbeta\n")
    assert gate.pin_status(crlf_pin, b"alpha\nbeta\n") == gate.PIN_EOL
    assert gate.pin_status(lf_pin, b"alpha\r\nbeta\r\n") == gate.PIN_EOL
    assert gate.pin_status(crlf_pin, b"alpha\r\nbeta\r\n") == gate.PIN_EXACT
    assert gate.pin_status(crlf_pin, b"alpha\r\nGAMMA\r\n") == gate.PIN_DRIFT
    assert gate.pin_status(None, b"anything") == gate.PIN_NOT_PINNED


def test_the_state_contract_is_total_and_only_one_state_certifies():
    gate = load_gate()
    assert set(gate.EXIT_CODES) == set(gate.STATUS_CONTRACT)
    assert gate.FULL_CERTIFICATION_STATUSES == (gate.FULL_REPRODUCTION_PASS,)
    # One code per outcome, with the two check-only states deliberately sharing the
    # partial code - and neither of them being zero.
    assert gate.exit_code(gate.FULL_REPRODUCTION_PASS) == 0
    assert (
        gate.exit_code(gate.CHECK_ONLY_PASS)
        == gate.exit_code(gate.CHECK_ONLY_WITH_ADVISORIES)
        == gate.EXIT_PARTIAL
        != 0
    )
    assert len({gate.exit_code(name) for name in gate.STATUS_CONTRACT}) == 5

    common = {"advisories": []}
    assert (
        gate.decide_status(mode="full", integrity=[], reproduction=[], blocked=[], **common)
        == gate.FULL_REPRODUCTION_PASS
    )
    assert (
        gate.decide_status(mode="full", integrity=[], reproduction=["a"], blocked=[], **common)
        == gate.FULL_REPRODUCTION_FAIL
    )
    assert (
        gate.decide_status(mode="check", integrity=[], reproduction=[], blocked=[], **common)
        == gate.CHECK_ONLY_PASS
    )
    assert (
        gate.decide_status(
            mode="check", integrity=[], reproduction=[], blocked=[], advisories=["absent"]
        )
        == gate.CHECK_ONLY_WITH_ADVISORIES
    )
    assert (
        gate.decide_status(mode="full", integrity=[], reproduction=[], blocked=["absent"], **common)
        == gate.BLOCKED_MISSING_INPUT
    )
    assert (
        gate.decide_status(
            mode="check", integrity=["tampered"], reproduction=[], blocked=[], **common
        )
        == gate.INTEGRITY_FAILURE
    )
    # An integrity failure outranks everything, and no run that leaves anything
    # unresolved can reach the one state that certifies.
    assert (
        gate.decide_status(
            mode="full", integrity=["tampered"], reproduction=[], blocked=["absent"], **common
        )
        == gate.INTEGRITY_FAILURE
    )
    for status in (
        gate.decide_status(mode="check", integrity=[], reproduction=[], blocked=[], **common),
        gate.decide_status(
            mode="check", integrity=[], reproduction=[], blocked=["absent"], **common
        ),
        gate.decide_status(mode="check", integrity=["t"], reproduction=[], blocked=[], **common),
        gate.decide_status(mode="full", integrity=[], reproduction=["r"], blocked=[], **common),
        gate.decide_status(mode="full", integrity=[], reproduction=[], blocked=["a"], **common),
    ):
        assert status not in gate.FULL_CERTIFICATION_STATUSES


def test_advisories_are_escalated_only_under_strict():
    gate = load_gate()
    assert (
        gate.decide_status(
            mode="check", integrity=[], reproduction=[], blocked=[], advisories=[], strict=False
        )
        == gate.CHECK_ONLY_PASS
    )
    assert (
        gate.decide_status(
            mode="check", integrity=[], reproduction=[], blocked=[], advisories=["x"], strict=False
        )
        == gate.CHECK_ONLY_WITH_ADVISORIES
    )
    assert (
        gate.decide_status(
            mode="check", integrity=[], reproduction=[], blocked=[], advisories=["x"], strict=True
        )
        == gate.INTEGRITY_FAILURE
    )
    assert (
        gate.decide_status(
            mode="full", integrity=[], reproduction=[], blocked=[], advisories=["x"], strict=True
        )
        == gate.FULL_REPRODUCTION_FAIL
    )


def test_a_missing_required_input_blocks_rather_than_fails(monkeypatch):
    gate = load_gate()
    monkeypatch.setattr(
        gate,
        "DECLARED_INPUTS",
        (*gate.DECLARED_INPUTS, ("does/not/exist.json", "a required input", False)),
    )
    report = gate.build_report(args_for(gate))
    assert report["status"] == gate.BLOCKED_MISSING_INPUT
    assert report["exit_code"] == gate.EXIT_BLOCKED
    assert (
        "does/not/exist.json" in check_by_name(report, "inputs:declared_inputs_present")["detail"]
    )


# --------------------------------------------------------------------------- #
# producer pins and the CI activation contract
# --------------------------------------------------------------------------- #


def fake_tree(tmp_path: Path) -> Path:
    """A tree the gate can be pointed at, with real producers and the real manifest."""
    for rel in PRODUCERS:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    pin_target = tmp_path / PRODUCER_PINS_REL
    pin_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PRODUCER_PINS, pin_target)
    return tmp_path


def test_the_pinned_producers_match_their_manifest():
    gate = load_gate()
    manifest, defects = gate.load_producer_pins()
    assert manifest is not None
    assert defects == []
    rows, row_defects = gate.producer_rows(manifest)
    assert row_defects == []
    assert [row["path"] for row in rows] == list(gate.PRODUCERS)
    assert all(row["pin_status"] == gate.PIN_EXACT for row in rows)


def test_a_changed_producer_is_a_named_failure(tmp_path, monkeypatch):
    gate = load_gate()
    tree = fake_tree(tmp_path)
    monkeypatch.setattr(gate, "ROOT", tree)
    manifest, _ = gate.load_producer_pins()

    clean_rows, clean_defects = gate.producer_rows(manifest)
    assert clean_defects == []
    assert all(row["pin_status"] == gate.PIN_EXACT for row in clean_rows)

    edited = tree / "scripts" / "cost_barrier.py"
    edited.write_text(
        edited.read_text(encoding="utf-8") + "\n# an unrecorded edit\n", encoding="utf-8"
    )
    rows, defects = gate.producer_rows(manifest)
    drifted = [row for row in rows if row["pin_status"] == gate.PIN_DRIFT]
    assert defects == []
    assert [row["path"] for row in drifted] == ["scripts/cost_barrier.py"]


def test_the_manifest_may_not_pin_the_checker_itself(tmp_path, monkeypatch):
    gate = load_gate()
    tree = fake_tree(tmp_path)
    pin_path = tree / gate.PRODUCER_PINS_PATH
    manifest = json.loads(pin_path.read_text(encoding="utf-8"))
    manifest["producers"].append({"path": gate.CHECKER, "sha256": "0" * 64})
    pin_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tree)

    loaded, _defects = gate.load_producer_pins()
    _, row_defects = gate.producer_rows(loaded)
    assert any("vacuous" in item for item in row_defects)


def test_a_missing_manifest_is_a_failure_not_a_silent_pass(tmp_path, monkeypatch):
    gate = load_gate()
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    manifest, defects = gate.load_producer_pins()
    assert manifest is None
    assert defects and "missing" in defects[0]


def test_the_workflow_covers_every_declared_input_and_is_not_softened():
    gate = load_gate()
    failures, filters = gate.workflow_coverage_failures()
    assert failures == [], failures
    assert set(filters) == {"push", "pull_request"}
    assert set(filters["push"]) == set(filters["pull_request"])
    assert len(gate.CI_WATCHED) >= 20
    for rel in gate.CI_WATCHED:
        assert any(fnmatch.fnmatch(rel, pattern) for pattern in filters["push"]), rel


def test_a_pruned_workflow_filter_is_caught(tmp_path, monkeypatch):
    gate = load_gate()
    target = tmp_path / gate.WORKFLOW_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = WORKFLOW.read_text(encoding="utf-8")
    pruned = "\n".join(
        line for line in text.splitlines(keepends=True) if "cost_model_v3.py" not in line
    )
    target.write_text(pruned, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    failures, _ = gate.workflow_coverage_failures()
    assert any("would not activate the workflow" in item for item in failures)


def test_a_softened_workflow_step_is_caught(tmp_path, monkeypatch):
    gate = load_gate()
    target = tmp_path / gate.WORKFLOW_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        WORKFLOW.read_text(encoding="utf-8").replace(
            "      - name: Sync dependencies\n        run: uv sync --all-extras --dev\n",
            "      - name: Sync dependencies\n        continue-on-error: true\n"
            "        run: uv sync --all-extras --dev\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    failures, _ = gate.workflow_coverage_failures()
    assert any("continue-on-error" in item for item in failures)


def test_an_absent_workflow_fails_closed(tmp_path, monkeypatch):
    gate = load_gate()
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    failures, filters = gate.workflow_coverage_failures()
    assert filters == {}
    assert failures and "absent" in failures[0]


# --------------------------------------------------------------------------- #
# the gate's own controls and its read-only posture
# --------------------------------------------------------------------------- #


def test_all_six_self_controls_detect_a_tamper():
    gate = load_gate()
    explorer = json.loads((RECOVERY / "COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8"))
    verification = json.loads(
        (RECOVERY / "COST_BARRIER_VERIFICATION.json").read_text(encoding="utf-8")
    )
    controls = gate.self_controls(explorer, verification)
    assert len(controls) == 6
    missed = [row for row in controls if not row["detected"]]
    assert not missed, missed
    assert all(row["signal"] for row in controls)


def test_a_gate_run_leaves_the_published_artefacts_and_inputs_byte_identical():
    gate = load_gate()
    watched = [
        RECOVERY / "COST_BARRIER_EXPLORER.json",
        RECOVERY / "COST_BARRIER_VERIFICATION.json",
        RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json",
        EVIDENCE_DIR / "COST_BARRIER.json",
        EVIDENCE_DIR / "PRODUCER_PINS.json",
        ROOT / gate.BUILDER,
        ROOT / gate.VERIFIER,
    ]
    before = {str(path): path.read_bytes() for path in watched}
    report = gate.build_report(args_for(gate))
    assert report["status"] == gate.FULL_REPRODUCTION_PASS
    after = {str(path): path.read_bytes() for path in watched}
    assert before == after
    assert check_by_name(report, "read_only:no_published_file_changed")["result"] == "PASS"


def test_the_report_claims_nothing_and_names_its_own_bytes():
    gate = load_gate()
    report = gate.build_report(args_for(gate, check=True))
    claims = report["claims"]
    assert claims["authorization_state"] == "NOT_AUTHORIZED"
    assert claims["trades_authorized"] == 0
    assert claims["false_success"] == 0
    for flag in (
        "promotion_claimed",
        "rentable_claimed",
        "certified_claimed",
        "production_ready_claimed",
    ):
        assert claims[flag] is False
    assert report["gate_sha256"] == hashlib.sha256(GATE.read_bytes()).hexdigest()
    assert report["environment"]["python"]
    certification = report["certification"]
    assert certification["satisfies_full_certification"] is False
    assert certification["is_partial"] is True
    assert certification["partial_result_may_promote_strategies"] is False
    assert certification["partial_result_may_certify_economic_results"] is False


@pytest.mark.parametrize(
    "name",
    [
        "artifact:explorer_self_hash_and_checks",
        "producers:digests_match_the_pinned_manifest",
        "ci:activation_contract_covers_every_declared_input",
        "source:market_horizon_rows_match_the_pinned_source",
    ],
)
def test_integrity_checks_are_tagged_as_such(name):
    gate = load_gate()
    report = gate.build_report(args_for(gate, check=True))
    row = check_by_name(report, name)
    assert row["severity"] == gate.SEVERITY_INTEGRITY


def test_missing_subjects_are_an_integrity_failure_and_a_named_check(tmp_path):
    gate = load_gate()
    report = gate.build_report(args_for(gate, explorer=str(tmp_path / "absent.json"), check=True))
    assert report["status"] == gate.INTEGRITY_FAILURE
    assert report["exit_code"] == gate.EXIT_INTEGRITY_FAILURE
    assert check_by_name(report, "subjects:present")["severity"] == gate.SEVERITY_INTEGRITY
