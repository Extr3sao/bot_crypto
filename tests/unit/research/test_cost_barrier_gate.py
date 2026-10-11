"""Contract tests for the COST-BARRIER DRIFT GATE (WP-6 governance follow-on).

The gate is held to what it claims:

* on the committed state it reproduces every published number - the builder
  rebuilds the explorer bit for bit and the verifier stays PASS with 13/13
  mutation controls;
* a published number that moved, even with the self-hash recomputed honestly,
  is a visible failure naming the exact field;
* a zeroed self-hash, a rewritten verification verdict and a flipped governance
  flag are each caught without re-running the builder;
* a cited input whose content changed is content drift and fails the gate (the
  artefact must be regenerated), while a line-ending-only difference is not;
* the gate never writes to the published artefacts or the inputs it watches;
* the gate's own six controls detect every tamper - a vacuous comparison cannot
  pass;
* advisories are escalated only under --strict.

Tampering is always performed on copies in ``tmp_path``: the published artefacts
are never modified by these tests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECOVERY = ROOT / "data" / "recovery"
GATE = ROOT / "scripts" / "cost_barrier_gate.py"


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
    assert report["status"] == "PASS", report["failures"]
    assert report["checks_failed"] == 0
    assert report["controls_missed"] == 0
    assert check_by_name(report, "reproduce:explorer_rebuilds_identically")["result"] == "PASS"
    assert check_by_name(report, "reproduce:verifier_passes")["result"] == "PASS"
    assert check_by_name(report, "reproduce:verification_document_unchanged")["result"] == "PASS"
    assert check_by_name(report, "inputs:published_pins_match_the_declared_sources")["result"] == "PASS"


def test_check_mode_reproduces_the_numbers_without_running_the_builder():
    gate = load_gate()
    report = gate.build_report(args_for(gate, check=True))
    assert report["status"] == "PASS", report["failures"]
    names = {row["check"] for row in report["checks"]}
    assert "reproduce:explorer_rebuilds_identically" not in names
    assert "reproduce:verifier_passes" in names


def test_the_cli_exits_zero_on_the_committed_state_and_nonzero_on_a_tampered_copy(tmp_path):
    clean = subprocess.run(
        [sys.executable, str(GATE), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr

    doc, path = copy_explorer(tmp_path)
    doc["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    tampered = subprocess.run(
        [sys.executable, str(GATE), "--check", "--explorer", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert tampered.returncode == 1
    assert "FAIL" in tampered.stdout


# --------------------------------------------------------------------------- #
# negative controls (tampered copies only)
# --------------------------------------------------------------------------- #


def test_a_moved_number_with_an_honest_rehash_is_caught_by_full_reproduction(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["cells"][0]["zero_cost_gross_bps"] += 5.0
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path)))
    assert report["status"] == "FAIL"
    failure = check_by_name(report, "reproduce:explorer_rebuilds_identically")
    assert failure["result"] == "FAIL"
    assert "zero_cost_gross_bps" in failure["detail"]
    assert any("zero_cost_gross_bps" in item for item in report["failures"])


def test_a_zeroed_self_hash_is_caught_without_any_rerun(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == "FAIL"
    assert check_by_name(report, "artifact:explorer_self_hash_and_checks")["result"] == "FAIL"


def test_a_rewritten_verification_verdict_is_caught(tmp_path):
    gate = load_gate()
    doc, path = copy_verification(tmp_path)
    doc["status"] = "FAIL"
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, verification=str(path), check=True))
    assert report["status"] == "FAIL"
    assert check_by_name(report, "artifact:verification_attests_the_explorer")["result"] == "FAIL"


def test_a_flipped_governance_flag_is_caught(tmp_path):
    gate = load_gate()
    doc, path = copy_explorer(tmp_path)
    doc["claims"]["rentable_claimed"] = True
    rehash(gate, doc)
    path.write_text(json.dumps(doc), encoding="utf-8")

    report = gate.build_report(args_for(gate, explorer=str(path), check=True))
    assert report["status"] == "FAIL"
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
    assert report["status"] == "FAIL"
    check = check_by_name(report, "inputs:published_pins_match_the_declared_sources")
    assert check["result"] == "FAIL"
    assert "content drift" in check["detail"]
    assert any("regenerated" in item for item in report["failures"])


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


def test_advisories_are_escalated_only_under_strict():
    gate = load_gate()
    assert gate.decide_status([], [], strict=False) == "PASS"
    assert gate.decide_status([], ["an absent generated input"], strict=False) == "PASS_WITH_ADVISORIES"
    assert gate.decide_status([], ["an absent generated input"], strict=True) == "FAIL"
    assert gate.decide_status(["a moved number"], [], strict=False) == "FAIL"


# --------------------------------------------------------------------------- #
# the gate's own controls and its read-only posture
# --------------------------------------------------------------------------- #


def test_all_six_self_controls_detect_a_tamper():
    gate = load_gate()
    explorer = json.loads((RECOVERY / "COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8"))
    verification = json.loads((RECOVERY / "COST_BARRIER_VERIFICATION.json").read_text(encoding="utf-8"))
    controls = gate.self_controls(explorer, verification)
    assert len(controls) == 6
    missed = [row for row in controls if not row["detected"]]
    assert not missed, missed
    assert all(row["signal"] for row in controls)


def test_a_gate_run_leaves_the_published_artefacts_and_inputs_byte_identical():
    gate = load_gate()
    watched = [RECOVERY / "COST_BARRIER_EXPLORER.json",
               RECOVERY / "COST_BARRIER_VERIFICATION.json",
               RECOVERY / "ACTIVE_ECONOMIC_AUDIT.json",
               ROOT / gate.BUILDER, ROOT / gate.VERIFIER]
    before = {str(path): path.read_bytes() for path in watched}
    report = gate.build_report(args_for(gate))
    assert report["status"] == "PASS"
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
    for flag in ("promotion_claimed", "rentable_claimed", "certified_claimed",
                 "production_ready_claimed"):
        assert claims[flag] is False
    assert report["gate_sha256"] == hashlib.sha256(GATE.read_bytes()).hexdigest()
