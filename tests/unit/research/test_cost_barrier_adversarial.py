"""Contract tests for the adversarial harness and the certification gate (WP-7D/7F).

Two things are held to what they claim:

* the harness's verdict policy. It has to understand both vocabularies (the WP-7
  six-state contract and the older PASS/PASS_WITH_ADVISORIES/FAIL) because its
  baseline run drives the pre-hardening gate; it has to distinguish "the gate
  flagged this" from "the gate came out clean" in both; and it must refuse to
  call an unchanged tree an attack - a mutation that happens to equal the
  published value proves nothing, and the fingerprint check is what catches it;
* the certifier's refusal. Only a full reproduction may satisfy a full
  certification requirement, so a check-only report dressed up as a full one, a
  missing input, an escaped attack or a failed contract test each have to end in
  a refusal that names the reason.

A small end-to-end subset of the attacks is exercised here (A01, A06, A11) so the
sandbox machinery itself is covered; the full sweep is
``scripts/cost_barrier_adversarial.py``, run by CI and recorded in
``data/recovery/wp7/COST_BARRIER_ADVERSARIAL_REPORT.json``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return load_script("cost_barrier_adversarial")


@pytest.fixture(scope="module")
def certifier():
    return load_script("cost_barrier_certify")


def attack(harness, attack_id: str) -> dict:
    return next(row for row in harness.ATTACKS if row["attack_id"] == attack_id)


# --------------------------------------------------------------------------- #
# the verdict policy
# --------------------------------------------------------------------------- #


def contract(**kwargs) -> dict:
    base = {
        "vocabulary": "contract",
        "status": "FULL_REPRODUCTION_PASS",
        "exit_code": 0,
        "certification": {"satisfies_full_certification": True},
    }
    base.update(kwargs)
    return base


def test_flagged_means_the_run_did_not_come_out_clean(harness):
    h = harness
    assert h.verdict("FLAGGED", contract(status="INTEGRITY_FAILURE", exit_code=5)) is True
    assert h.verdict("FLAGGED", contract(status="FULL_REPRODUCTION_FAIL", exit_code=4)) is True
    assert h.verdict("FLAGGED", contract(status="BLOCKED_MISSING_INPUT", exit_code=3)) is True
    assert h.verdict("FLAGGED", contract(status="CHECK_ONLY_PASS", exit_code=2)) is False
    assert h.verdict("FLAGGED", contract(status="FULL_REPRODUCTION_PASS")) is False
    # Legacy vocabulary: the pre-hardening gate only had an exit code.
    legacy = {"vocabulary": "legacy", "status": "FAIL", "exit_code": 1}
    assert h.verdict("FLAGGED", legacy) is True
    assert h.verdict("FLAGGED", {"vocabulary": "legacy", "status": "PASS", "exit_code": 0}) is False


def partial(status: str) -> dict:
    """A check-only run as the gate actually publishes it: partial, not certifying."""
    return {
        "vocabulary": "contract",
        "status": status,
        "exit_code": 2,
        "certification": {"satisfies_full_certification": False, "is_partial": True},
    }


def test_clean_and_partial_are_distinguished(harness):
    assert harness.verdict("CLEAN", contract()) is True
    assert harness.verdict("CLEAN", partial("CHECK_ONLY_PASS")) is False
    assert harness.verdict("PARTIAL", partial("CHECK_ONLY_PASS")) is True
    assert harness.verdict("PARTIAL", partial("CHECK_ONLY_WITH_ADVISORIES")) is True
    assert harness.verdict("PARTIAL", contract()) is False
    # A partial run that claims to satisfy full certification is not partial, it is a lie.
    dressed = contract(
        status="CHECK_ONLY_PASS",
        exit_code=2,
        certification={"satisfies_full_certification": True},
    )
    assert harness.verdict("PARTIAL", dressed) is False


def test_blocked_is_its_own_state(harness):
    assert harness.verdict("BLOCKED", contract(status="BLOCKED_MISSING_INPUT", exit_code=3)) is True
    assert harness.verdict("BLOCKED", contract(status="FULL_REPRODUCTION_PASS")) is False
    assert (
        harness.verdict("BLOCKED", {"vocabulary": "legacy", "status": "FAIL", "exit_code": 1})
        is True
    )


def test_an_unknown_expectation_is_an_error_not_a_pass(harness):
    with pytest.raises(ValueError):
        harness.verdict("LOOKS_FINE_TO_ME", contract())


# --------------------------------------------------------------------------- #
# the harness's own vacuity control
# --------------------------------------------------------------------------- #


def test_the_tree_fingerprint_notices_a_change(harness, tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    before = harness.tree_fingerprint(tmp_path)
    (tmp_path / "b.txt").write_text("two", encoding="utf-8")
    assert harness.tree_fingerprint(tmp_path) != before
    (tmp_path / "b.txt").unlink()
    assert harness.tree_fingerprint(tmp_path) == before


def test_every_attack_mutates_and_declares_how_it_is_expected_to_be_seen(harness):
    assert len(harness.ATTACKS) >= 16
    seen = set()
    for row in harness.ATTACKS:
        assert row["attack_id"] not in seen
        seen.add(row["attack_id"])
        assert set(row["expect"]) == {"full", "check"}
        for expectation in row["expect"].values():
            assert expectation in {"FLAGGED", "CLEAN", "PARTIAL", "BLOCKED"}
        assert row["input"] and row["how"] and callable(row["mutate"])


def test_the_required_attack_matrix_is_covered(harness):
    # The fifteen attacks the work package names, plus two extras.
    required = {f"A{index:02d}" for index in range(1, 16)}
    present = {row["attack_id"] for row in harness.ATTACKS}
    assert required <= present, required - present
    assert {"A16", "A17"} <= present


# --------------------------------------------------------------------------- #
# the sandbox, end to end
# --------------------------------------------------------------------------- #


def test_the_sandbox_carries_everything_the_gate_reads(harness, tmp_path):
    missing = harness.build_sandbox(tmp_path, None)
    assert missing == [], f"the sandbox is incomplete: {missing}"
    gate = load_script("cost_barrier_gate")
    for rel, _role, _pinned in gate.DECLARED_INPUTS:
        assert (tmp_path / rel).exists(), rel


def run_attack_in_tmp(harness, tmp_path, attack_id: str) -> dict:
    return harness.run_attack(
        attack(harness, attack_id),
        workdir=tmp_path,
        gate_source=None,
        sandbox_files_missing=[],
    )


def test_a_moved_number_without_a_rehash_is_detected(harness, tmp_path):
    row = run_attack_in_tmp(harness, tmp_path, "A01")
    assert row["valid_mutation"] is True
    assert row["detected"] is True
    assert row["missed_in"] == []
    assert "zero_cost_gross_bps" in row["evidence"] or "payload_sha256" in row["evidence"]


def test_a_removed_required_input_blocks_in_full_mode_and_stays_partial_in_check(harness, tmp_path):
    row = run_attack_in_tmp(harness, tmp_path, "A06")
    assert row["valid_mutation"] is True
    assert row["detected"] is True, row["counter_evidence"]
    observed = {item["mode"]: item["status"] for item in row["observed"]}
    assert observed["full"] == "BLOCKED_MISSING_INPUT"
    assert observed["check"] == "CHECK_ONLY_WITH_ADVISORIES"


def test_a_line_ending_only_change_is_not_a_finding(harness, tmp_path):
    row = run_attack_in_tmp(harness, tmp_path, "A11")
    assert row["valid_mutation"] is True
    assert row["detected"] is True, row["counter_evidence"]
    observed = {item["mode"]: item["status"] for item in row["observed"]}
    assert observed["full"] == "FULL_REPRODUCTION_PASS"


def test_a_sweep_without_its_substrate_refuses_to_report_a_rate(harness, tmp_path, monkeypatch):
    """A clean checkout has no materialized input, and that must not read as detection.

    Without the gitignored input every full-reproduction attack degenerates into
    "the gate was already blocked", which the harness would otherwise count as
    the attack being caught. The sweep has to say NOT_EVALUABLE instead, and the
    mutation that could not land is recorded as invalid rather than detected.
    """
    monkeypatch.setattr(harness, "MARKET_HORIZON", "reports/strategy-baseline/absent.json")
    report = harness.run_all(
        workdir=tmp_path, gate_source=None, gate_label="no substrate", only="A06"
    )
    assert report["status"] == "NOT_EVALUABLE"
    assert report["substrate"]["present"] is False
    assert report["attacks_invalid"] == 1
    assert report["attacks_detected"] == 0
    assert "materialize" in report["substrate"]["why"]


# --------------------------------------------------------------------------- #
# the certifier's refusal
# --------------------------------------------------------------------------- #

FULL_REPORT = {
    "status": "FULL_REPRODUCTION_PASS",
    "mode": "full",
    "exit_code": 0,
    "checks_failed": 0,
    "integrity_failures": [],
    "controls_missed": 0,
    "claims": {"false_success": 0},
}
INTEGRITY_OK = {"status": "VERIFIED"}
TESTS_OK = {"passed": True, "exit_code": 0}
ADVERSARIAL_OK = {
    "status": "EVALUATED",
    "substrate": {"path": "reports/strategy-baseline/COST_BARRIER.json", "present": True},
    "attacks_total": 17,
    "attacks_evaded": 0,
    "legs_failed": [],
    "escapes": [],
}


def test_a_complete_candidate_certifies(certifier):
    outcome = certifier.evaluate(
        gate_report=FULL_REPORT,
        contract_tests=TESTS_OK,
        adversarial=ADVERSARIAL_OK,
        integrity=INTEGRITY_OK,
    )
    assert outcome["status"] == certifier.CERTIFIED
    assert outcome["satisfies_full_certification"] is True
    assert outcome["reasons"] == []
    assert outcome["authorizes_promotion"] is False


def test_a_check_only_report_dressed_as_full_is_refused(certifier):
    dressed = {**FULL_REPORT, "mode": "check"}
    outcome = certifier.evaluate(
        gate_report=dressed,
        contract_tests=TESTS_OK,
        adversarial=ADVERSARIAL_OK,
        integrity=INTEGRITY_OK,
    )
    assert outcome["satisfies_full_certification"] is False
    assert any("mode" in reason for reason in outcome["reasons"])


def test_a_partial_run_cannot_certify(certifier):
    outcome = certifier.evaluate(
        gate_report={"status": "CHECK_ONLY_PASS", "mode": "check", "exit_code": 2},
        contract_tests=TESTS_OK,
        adversarial=ADVERSARIAL_OK,
        integrity=INTEGRITY_OK,
    )
    assert outcome["status"] == certifier.PARTIAL
    assert outcome["satisfies_full_certification"] is False
    assert any("check-only" in reason for reason in outcome["reasons"])


def test_a_blocked_input_is_blocked_not_failed(certifier):
    outcome = certifier.evaluate(
        gate_report={
            "status": "BLOCKED_MISSING_INPUT",
            "mode": "full",
            "blocked": ["reports/strategy-baseline/COST_BARRIER.json absent"],
        },
        contract_tests=TESTS_OK,
        adversarial=ADVERSARIAL_OK,
        integrity={"status": "BLOCKED_MISSING_INPUT", "message": "bundle incomplete"},
    )
    assert outcome["status"] == certifier.BLOCKED
    assert outcome["satisfies_full_certification"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_tests": {"passed": False, "exit_code": 1, "stderr_tail": "1 failed"}},
        {"adversarial": {**ADVERSARIAL_OK, "attacks_evaded": 1, "escapes": [{"attack_id": "A07"}]}},
        {"adversarial": {**ADVERSARIAL_OK, "legs_failed": ["A13:leg"]}},
        {"adversarial": {"attacks_total": 0, "attacks_evaded": 0, "legs_failed": []}},
        {
            "adversarial": {
                **ADVERSARIAL_OK,
                "status": "NOT_EVALUABLE",
                "substrate": {
                    "path": "reports/strategy-baseline/COST_BARRIER.json",
                    "present": False,
                    "why": "materialize first",
                },
            }
        },
        {"adversarial": {**ADVERSARIAL_OK, "substrate": {"present": False}}},
        {"adversarial": {**ADVERSARIAL_OK, "substrate": None}},
        {"integrity": {"status": "INTEGRITY_FAILURE", "failures": ["the copy drifted"]}},
        {"integrity": None},
        {"gate_report": {**FULL_REPORT, "integrity_failures": ["a pin drifted"]}},
        {"gate_report": {**FULL_REPORT, "checks_failed": 1}},
        {"gate_report": {**FULL_REPORT, "controls_missed": 1}},
        {"gate_report": None},
    ],
)
def test_every_missing_criterion_refuses_certification(certifier, overrides):
    arguments = {
        "gate_report": FULL_REPORT,
        "contract_tests": TESTS_OK,
        "adversarial": ADVERSARIAL_OK,
        "integrity": INTEGRITY_OK,
    }
    arguments.update(overrides)
    outcome = certifier.evaluate(**arguments)
    assert outcome["satisfies_full_certification"] is False
    assert outcome["reasons"], "a refusal must name its reason"


def test_the_gate_under_test_is_identified_by_content_not_by_the_checkout(harness, tmp_path):
    """A checkout rewrites line endings; the digest must name the code, not the tree."""
    source = tmp_path / "gate.py"
    source.write_bytes(b"a = 1\r\nb = 2\r\n")
    assert harness.content_digest(source) == harness.sha256_bytes(b"a = 1\nb = 2\n")
    assert harness.sha256_file(source) != harness.content_digest(source)
    assert harness.content_digest(tmp_path / "absent.py") is None


def test_the_certification_record_digests_content_not_a_checkout(harness, certifier):
    import hashlib

    record_path = RECOVERY / "wp7" / "COST_BARRIER_CERTIFICATION.json"
    if not record_path.exists():
        pytest.skip("the certification record has not been produced in this checkout")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "LF" in str(record.get("evidence_digest_convention"))
    digests = record["evidence_digests"]
    assert digests, "the record identifies nothing"
    for rel, digest in digests.items():
        expected = hashlib.sha256((ROOT / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert digest == expected, rel


def test_the_record_fingerprint_follows_from_its_own_head_and_digests():
    """The fingerprint has to be derivable from what the record publishes.

    A digest nobody can recompute is decoration: it looks like identification and
    is not. The record names its candidate head and its digests, so the
    fingerprint is recomputed here from exactly those two fields - no reliance on
    the tree this test happens to run in. The digest convention is checked
    separately; this is the composition.
    """
    import hashlib

    record_path = RECOVERY / "wp7" / "COST_BARRIER_CERTIFICATION.json"
    if not record_path.exists():
        pytest.skip("the certification record has not been produced in this checkout")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    recomputed = hashlib.sha256(
        json.dumps(
            {"head": record["candidate"]["head"], "digests": record["evidence_digests"]},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert recomputed == record["evidence_fingerprint"]
    assert record["candidate"]["head"] and len(record["candidate"]["head"]) == 40


def test_a_reissued_record_names_what_it_replaced():
    """WP-8D: a re-issued record keeps the identity of the one it replaces.

    The audit artefact this record fingerprints can legitimately be regenerated by another
    work package. When that happens the record is re-issued, and a re-issue that silently
    dropped the previous fingerprint would be indistinguishable from a record that had
    always described the new evidence.
    """
    record_path = RECOVERY / "wp7" / "COST_BARRIER_CERTIFICATION.json"
    if not record_path.exists():
        pytest.skip("the certification record has not been produced in this checkout")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "supersession" in record, "the record must say whether it replaced an earlier one"
    supersession = record["supersession"]
    if supersession is None:
        return
    assert len(supersession["previous_fingerprint"]) == 64
    assert supersession["previous_fingerprint"] != record["evidence_fingerprint"]
    assert supersession["reason"], "a re-issue must say why it happened"
    assert len(supersession["previous_evidence_digests_sha256"]) == 64


def test_the_committed_certification_record_refuses_or_reports_a_full_run():
    record_path = RECOVERY / "wp7" / "COST_BARRIER_CERTIFICATION.json"
    if not record_path.exists():
        pytest.skip("the certification record has not been produced in this checkout")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    decision = record["decision"]
    assert decision["authorizes_promotion"] is False
    assert decision["authorizes_live_trading"] is False
    assert record["claims"]["trades_authorized"] == 0
    assert (record["status"] == "CERTIFIED") == decision["satisfies_full_certification"]
    assert record["evidence_fingerprint"]
