"""Evidence-integrity tests — GATE STRAT-HARDEN-002 §7-§10.

These encode the defect the independent verifier found: the committed
EXP-STRAT-DYNAMIC-001 result said DO_NOT_PROMOTE while the retained exp.log said
PROMOTE_CANDIDATE, and the artifact was not byte-reproducible. Every test here
asserts that such a contradiction is now impossible to emit or to re-validate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.experiment_evidence import (
    NON_DETERMINISTIC_FIELDS,
    RUN_FILES,
    EvidenceConflictError,
    EvidenceImmutabilityError,
    EvidenceIntegrityError,
    assert_evidence_coherent,
    build_manifest,
    canonical_json,
    deterministic_view,
    extract_log_decision,
    extract_result_decision,
    fingerprint_files,
    make_run_id,
    sha256_file,
    sha256_text,
    validate_run,
    write_run,
)

ROOT = Path(__file__).resolve().parents[3]


def _result(decision: str = "DO_NOT_PROMOTE") -> dict[str, object]:
    return {
        "run_id": "EXP-STRAT-DYNAMIC-001-20261001T000000Z-deadbeef",
        "decision": decision,
        "net_pnl": -74.92,
    }


# --------------------------------------------------------------------------- #
# Canonical serialization
# --------------------------------------------------------------------------- #


def test_canonical_json_is_sorted_and_whitespace_free() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    # key order in the input must not change the bytes
    assert canonical_json({"a": 2, "b": 1}) == canonical_json({"b": 1, "a": 2})


def test_canonical_json_is_byte_stable() -> None:
    payload = {"z": [1, 2, 3], "a": {"nested": True}, "f": 0.1}
    assert (
        canonical_json(payload).encode("utf-8")
        == canonical_json(payload).encode("utf-8")
        == json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    )


def test_deterministic_view_strips_run_only_fields() -> None:
    manifest = {k: 1 for k in NON_DETERMINISTIC_FIELDS}
    manifest["stable"] = "value"
    assert deterministic_view(manifest) == {"stable": "value"}


# --------------------------------------------------------------------------- #
# Manifest completeness
# --------------------------------------------------------------------------- #


def test_manifest_carries_every_required_field(tmp_path: Path) -> None:
    script = tmp_path / "exp.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    manifest = build_manifest(
        experiment_id="EXP-X",
        run_id="EXP-X-run1",
        script_path=script,
        repo=ROOT,
        config={"a": 1},
        dataset_fingerprint="abc",
        seed=7,
        started_at="2026-10-01T00:00:00Z",
        completed_at="2026-10-01T00:10:00Z",
        result={"decision": "DO_NOT_PROMOTE"},
        decision="DO_NOT_PROMOTE",
    )
    for field in (
        "run_id",
        "experiment_id",
        "commit_sha",
        "dirty_tree",
        "script_sha256",
        "config_sha256",
        "dataset_fingerprint",
        "started_at",
        "completed_at",
        "seed",
        "result",
        "decision",
        "artifact_version",
    ):
        assert field in manifest, field
    assert manifest["script_sha256"] == sha256_file(script)
    assert len(sha256_text("abc")) == 64


def test_fingerprint_ignores_scan_order(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    assert fingerprint_files([a, b]) == fingerprint_files([b, a])


def test_make_run_id_is_filename_safe() -> None:
    rid = make_run_id("EXP-X", commit_sha="deadbeefcafebabe")
    assert rid.startswith("EXP-X-")
    assert rid.endswith("-deadbeef")
    assert "/" not in rid and " " not in rid


# --------------------------------------------------------------------------- #
# Decision-coherence guard (§10)
# --------------------------------------------------------------------------- #


def test_coherent_run_passes() -> None:
    assert_evidence_coherent(_result("DO_NOT_PROMOTE"), "FINAL_DECISION=DO_NOT_PROMOTE\n")


def test_disagreeing_stdout_is_an_evidence_conflict() -> None:
    with pytest.raises(EvidenceConflictError):
        assert_evidence_coherent(
            _result("DO_NOT_PROMOTE"),
            "FINAL_DECISION=PROMOTE_CANDIDATE\n",
        )


def test_legacy_verdict_log_is_also_checked() -> None:
    # exactly the stale exp.log shape: a printed verdict, no FINAL_DECISION mark
    with pytest.raises(EvidenceConflictError):
        assert_evidence_coherent(
            _result("DO_NOT_PROMOTE"),
            json.dumps({"dynamic_improved": True, "verdict": "PROMOTE_CANDIDATE"}),
        )


def test_log_without_a_decision_is_not_a_conflict() -> None:
    assert_evidence_coherent(_result("DO_NOT_PROMOTE"), "no decision printed here\n")


def test_log_decision_with_no_result_decision_is_invalid() -> None:
    with pytest.raises(EvidenceIntegrityError):
        assert_evidence_coherent({"net_pnl": 1.0}, "FINAL_DECISION=X\n")


def test_extractors() -> None:
    assert extract_result_decision({"verdict": "V"}) == "V"
    assert extract_result_decision({}) is None
    assert extract_log_decision("a\nFINAL_DECISION=Z\n") == "Z"
    assert extract_log_decision("verdict: 'A'\nverdict: B\n") == "B"


# --------------------------------------------------------------------------- #
# Immutable run dirs + pointer
# --------------------------------------------------------------------------- #


def _write(reports_root: Path, run_id: str = "EXP-X-run1") -> Path:
    script = reports_root / "s.py"
    script.write_text("x", encoding="utf-8")
    manifest = build_manifest(
        experiment_id="EXP-X",
        run_id=run_id,
        script_path=script,
        repo=ROOT,
        config={"a": 1},
        dataset_fingerprint="abc",
        seed=1,
        started_at="2026-10-01T00:00:00Z",
        completed_at="2026-10-01T00:10:00Z",
        result={"run_id": run_id, "decision": "DO_NOT_PROMOTE"},
        decision="DO_NOT_PROMOTE",
    )
    return write_run(
        reports_root=reports_root,
        experiment_id="EXP-X",
        manifest=manifest,
        result={"run_id": run_id, "decision": "DO_NOT_PROMOTE"},
        stdout_text="FINAL_DECISION=DO_NOT_PROMOTE\n",
        report_markdown="# run\n",
    )


def test_write_run_creates_all_files_and_a_non_evidence_pointer(tmp_path: Path) -> None:
    run_dir = _write(tmp_path)
    for name in RUN_FILES:
        assert (run_dir / name).exists(), name
    pointer = json.loads((tmp_path / "EXP-X" / "LATEST.json").read_text(encoding="utf-8"))
    assert pointer["_marker"] == "POINTER / NON-EVIDENCE"
    assert pointer["non_evidence"] is True


def test_run_is_immutable_per_run_id(tmp_path: Path) -> None:
    _write(tmp_path)
    with pytest.raises(EvidenceImmutabilityError):
        _write(tmp_path)


def test_conflicting_run_writes_nothing(tmp_path: Path) -> None:
    script = tmp_path / "s.py"
    script.write_text("x", encoding="utf-8")
    manifest = build_manifest(
        experiment_id="EXP-Y",
        run_id="EXP-Y-run1",
        script_path=script,
        repo=ROOT,
        config={},
        dataset_fingerprint="d",
        seed=1,
        started_at="t0",
        completed_at="t1",
        result={"run_id": "EXP-Y-run1", "decision": "PROMOTE_CANDIDATE"},
        decision="PROMOTE_CANDIDATE",
    )
    with pytest.raises(EvidenceConflictError):
        write_run(
            reports_root=tmp_path,
            experiment_id="EXP-Y",
            manifest=manifest,
            result={"run_id": "EXP-Y-run1", "decision": "PROMOTE_CANDIDATE"},
            stdout_text="FINAL_DECISION=DO_NOT_PROMOTE\n",
            report_markdown="# run\n",
        )
    assert not (tmp_path / "EXP-Y").exists()


def test_validate_run_detects_a_tampered_stale_log(tmp_path: Path) -> None:
    run_dir = _write(tmp_path)
    # A stale/contradicting log must never be accepted as current evidence.
    (run_dir / "stdout.log").write_text("FINAL_DECISION=PROMOTE_CANDIDATE\n", encoding="utf-8")
    with pytest.raises(EvidenceConflictError):
        validate_run(run_dir)


def test_validate_run_accepts_a_clean_run(tmp_path: Path) -> None:
    run_dir = _write(tmp_path)
    record = validate_run(run_dir)
    assert record["valid"] is True
    assert record["decision"] == "DO_NOT_PROMOTE"
