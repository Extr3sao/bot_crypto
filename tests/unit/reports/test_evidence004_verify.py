"""EVIDENCE-004 — the verifier must disagree with a tampered package.

It re-reads the raw logs itself, so these tests tamper with a throwaway copy of the
package and require the verification to fail.  A verifier that passes a changed
`evidence_id` is not a verifier.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import evidence004_verify as verify  # noqa: E402

PACKAGE = REPO / verify.PACKAGE_REL


@pytest.fixture()
def copied(tmp_path: Path) -> Path:
    shutil.copytree(PACKAGE, tmp_path / verify.PACKAGE_REL)
    return tmp_path


def test_the_package_verifies_as_published() -> None:
    verdict = verify.verify_package(REPO)

    assert verdict.failures == [], verdict.failures
    assert len(verdict.checks) >= 30


def test_a_rewritten_evidence_id_is_caught(copied: Path) -> None:
    log = copied / verify.PACKAGE_REL / "rea" / "targets" / "T-NF-NOF1" / "REA_COMMAND_LOG.jsonl"
    text = log.read_text(encoding="utf-8")
    log.write_text(text.replace("ev_4b2bf9c5", "ev_00000000", 1), encoding="utf-8")

    verdict = verify.verify_package(copied)

    assert verdict.failures
    assert any("event" in failure["name"] for failure in verdict.failures)


def test_a_stale_report_removed_from_the_manifest_is_caught(copied: Path) -> None:
    manifest = copied / verify.EVIDENCE_REL / "SUPERSESSION_MANIFEST.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["documents"] = [
        record for record in payload["documents"] if not record["path"].endswith("REA_FIRST.json")
    ]
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    verdict = verify.verify_package(copied)

    assert any(
        failure["name"] == "historical_report_is_declared_superseded" for failure in verdict.failures
    )


def test_an_extra_report_cannot_be_slipped_in(copied: Path) -> None:
    (copied / verify.PACKAGE_REL / "RUN_REPORT_NEW.json").write_text("{}\n", encoding="utf-8")

    verdict = verify.verify_package(copied)

    assert any(
        failure["name"] == "no_unregistered_report_is_presented_as_current"
        for failure in verdict.failures
    )


def test_an_inflated_counts_block_is_caught(copied: Path) -> None:
    report = copied / verify.PACKAGE_REL / "RUN_REPORT.md"
    text = report.read_text(encoding="utf-8")
    report.write_text(
        text.replace("| `phase_v31.work.not_executed` | 2 |", "| `phase_v31.work.not_executed` | 0 |"),
        encoding="utf-8",
    )

    verdict = verify.verify_package(copied)

    assert any(
        failure["name"] == "every_report_carries_the_same_counts_block" for failure in verdict.failures
    )


def test_the_verifier_does_not_import_the_builder() -> None:
    source = Path(verify.__file__).read_text(encoding="utf-8")

    assert "import evidence004_ledger" not in source
    assert "import evidence004_generate" not in source
