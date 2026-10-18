"""EVIDENCE-004 — the classifier, tested where the false success used to live.

The historical dataset is exercised as-is (7 evidenced + 2 not executed in this
phase, 12 distinct ids across all dossiers) and a synthetic dataset proves the two
rules that made the old numbers wrong: an exit code of zero is not completion, and a
local key is not an evidence id REA emitted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import evidence004_ledger as ledger  # noqa: E402


def _write_log(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_the_refused_operation_with_exit_zero_is_not_counted_as_executed() -> None:
    events = ledger.load_events()
    refused = [event for event in events if event.operation == "compare-source-to-bundle"]

    assert len(refused) == 1
    assert refused[0].exit_code == 0
    assert refused[0].execution_class == ledger.REFUSED_INVALID_INPUT
    assert refused[0].completed is False


def test_the_phase_counter_is_seven_evidenced_and_two_not_executed() -> None:
    counts = ledger.build_counts(ledger.load_events())
    work = counts["phase_v31"]["work"]

    assert work["operations"] == 9
    assert work["executed_with_evidence_id"] == 7
    assert work["not_executed"] == 2
    assert work["executed_with_verified_artifact"] == 2
    assert work["executed_evidence_declared_unverified"] == 5


def test_the_dossier_counter_is_twelve_ids_and_is_not_the_same_counter() -> None:
    counts = ledger.build_counts(ledger.load_events())

    assert counts["all_dossiers"]["distinct_evidence_ids"] == 12
    assert counts["phase_v31"]["distinct_evidence_ids"] == 8
    assert "not the same counter" in counts["conflation_warning"]


def test_a_readiness_operation_is_not_smuggled_into_the_work_counter() -> None:
    counts = ledger.build_counts(ledger.load_events())
    work = counts["phase_v31"]["work"]

    readiness = counts["phase_v31"]["readiness"]
    assert readiness["operations"] == 1
    assert work["operations"] + readiness["operations"] != 9


def test_an_executed_operation_without_evidence_is_not_called_evidenced() -> None:
    event = ledger.LedgerEvent(
        event_key="k",
        target_id="T-X",
        operation="analyze_javascript_application",
        operation_family="TARGET_ANALYSIS",
        timestamp="2026-10-18T00:00:00Z",
        exit_code=0,
        result="ok",
        execution_class=ledger.EXECUTED_NO_EVIDENCE,
        command="rea analyze",
        evidence=ledger.EvidenceState(None, "NONE", None, None, False, ledger.EVIDENCE_ABSENT),
        duration_s=1.0,
        warnings=(),
        sources=(),
    )
    counts = ledger.build_counts([event])

    assert counts["phase_v31"]["work"]["executed_with_evidence_id"] == 0
    assert counts["phase_v31"]["work"]["not_executed"] == 0


def test_a_local_key_is_never_read_as_an_rea_id(tmp_path: Path) -> None:
    package = tmp_path / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
    target = package / "rea" / "targets" / "T-X"
    _write_log(
        target / "REA_COMMAND_LOG.jsonl",
        [
            {
                "timestamp": "2026-10-18T01:00:00Z",
                "operation": "doctor",
                "exit_code": 1,
                "evidence_id": "rea-doctor-2026-10-17",
            }
        ],
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ledger, "REA_DIR", package / "rea")
        events = ledger.load_events()
        inventory = ledger.evidence_inventory(events)

    assert events[0].evidence.id_kind == "LOCAL_KEY"
    assert inventory["rea_native_id_count"] == 0
    assert inventory["local_keys_misplaced_in_evidence_id"][0]["value"] == "rea-doctor-2026-10-17"


def test_a_truncated_log_is_refused_instead_of_silently_shortened(tmp_path: Path) -> None:
    package = tmp_path / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
    log = package / "rea" / "REA_COMMAND_LOG.jsonl"
    _write_log(
        log,
        [{"timestamp": "2026-10-18T01:00:00Z", "operation": "doctor", "target_id": "T-X", "exit_code": 1}],
    )
    raw = log.read_bytes()
    log.write_bytes(raw[:-5])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ledger, "REA_DIR", package / "rea")
        with pytest.raises(ledger.LedgerError, match="truncated"):
            ledger.load_events()


def test_two_copies_of_one_event_must_agree(tmp_path: Path) -> None:
    package = tmp_path / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
    row = {
        "timestamp": "2026-10-18T01:00:00Z",
        "operation": "capture_web_screenshot",
        "target_id": "T-X",
        "exit_code": 0,
    }
    _write_log(package / "rea" / "REA_COMMAND_LOG.jsonl", [row])
    _write_log(
        package / "rea" / "targets" / "T-X" / "REA_COMMAND_LOG.jsonl",
        [{**row, "exit_code": 1}],
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ledger, "REA_DIR", package / "rea")
        with pytest.raises(ledger.LedgerError, match="disagrees"):
            ledger.load_events()


def test_a_verified_artefact_is_distinguished_from_a_declared_id() -> None:
    events = {event.event_key: event for event in ledger.load_events()}
    verified = [event for event in events.values() if event.evidence.status == ledger.EVIDENCE_VERIFIED]

    assert verified, "at least one screenshot must be verified against its declared digest"
    assert all(event.evidence.digest_matched_path for event in verified)
    declared = [
        event
        for event in events.values()
        if event.evidence.status == ledger.EVIDENCE_CORROBORATED
    ]
    assert declared, "ids corroborated only by a dossier must not be reported as verified"
    assert all(event.evidence.digest_matched_path is None for event in declared)
