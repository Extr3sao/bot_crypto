"""EVIDENCE-004 — the generator refuses to publish what evidence cannot support."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import evidence004_generate as generate  # noqa: E402
import evidence004_ledger as ledger  # noqa: E402


def _claim_inflated() -> list[dict[str, Any]]:
    return [
        {
            "claim_id": "X-1",
            "kind": "COUNTER",
            "text": "nine operations were evidenced",
            "pointer": "counts.phase_v31.work.executed_with_evidence_id",
            "expected": 9,
        }
    ]


def test_a_claim_that_contradicts_the_ledger_stops_the_run() -> None:
    canonical = generate.build_canonical()

    with pytest.raises(generate.GenerationError, match="the ledger says 7"):
        generate.verify_claims(canonical, _claim_inflated())


def test_a_claim_citing_an_id_that_never_existed_stops_the_run() -> None:
    canonical = generate.build_canonical()
    claims = [
        {
            "claim_id": "X-2",
            "kind": "EVIDENCE_ID",
            "text": "fabricated",
            "evidence_id": "ev_" + "a" * 64,
        }
    ]

    with pytest.raises(generate.GenerationError, match="not an evidence_id present"):
        generate.verify_claims(canonical, claims)


def test_the_real_claims_file_resolves_against_the_real_logs() -> None:
    canonical = generate.build_canonical()
    claims = json.loads(generate.CLAIMS_PATH.read_text(encoding="utf-8"))
    resolved = generate.verify_claims(canonical, claims)

    assert len(resolved) == len(claims)
    assert all(claim["verified"] for claim in resolved)
    assert canonical["counter_values"]["phase_v31.work.executed_with_evidence_id"] == 7


def test_generation_is_deterministic_for_the_same_logs() -> None:
    first = generate.generate(dry_run=True)
    second = generate.generate(dry_run=True)

    assert first["canonical_sha256"] == second["canonical_sha256"]
    assert first["derived_dir"] == second["derived_dir"]


def test_a_second_writer_is_refused_while_the_lock_is_held(tmp_path: Path) -> None:
    lock = tmp_path / ".writer.lock"
    with (
        generate.single_writer(lock),
        pytest.raises(generate.WriterConflict, match="another generator is running"),
        generate.single_writer(lock),
    ):
        pass
    assert not lock.exists(), "the lock must be released even when the write fails"


def test_a_failed_atomic_write_leaves_no_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "RUN_REPORT.md"
    target.write_text("original\n", encoding="utf-8")

    def explode(source: object, destination: object) -> None:
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(generate.os, "replace", explode)
        with pytest.raises(OSError, match="disk full"):
            generate.write_atomic(target, "a much longer replacement\n")

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.iterdir()) == [target], "the temporary file must not survive"


def test_the_derived_directory_is_named_by_the_ledger_hash() -> None:
    canonical = generate.build_canonical()
    result = generate.generate(dry_run=True)

    assert canonical["ledger_sha256"][:12] in result["derived_dir"]


def test_phase_and_dossier_counters_are_never_added() -> None:
    canonical = generate.build_canonical()
    values = canonical["counter_values"]

    assert values["phase_v31.work.executed_with_evidence_id"] == 7
    assert values["all_dossiers.distinct_evidence_ids"] == 12
    assert values["all_dossiers.work.executed_with_evidence_id"] == 10
    assert "not the same counter" in canonical["counts"]["conflation_warning"]


def test_the_canonical_object_keeps_exit_codes_away_from_completion() -> None:
    canonical = generate.build_canonical()
    refused = [
        event for event in canonical["events"] if event["execution_class"] == ledger.REFUSED_INVALID_INPUT
    ]

    assert refused and all(event["exit_code"] == 0 and event["completed"] is False for event in refused)
