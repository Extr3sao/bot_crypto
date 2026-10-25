"""WP-TAP-EVIDENCE-004F — the five residual defects, each pinned by a test.

Each test here failed before the repair it guards.  They are grouped by the audit
claim they close, so a regression names the defect it reopened:

E4-01  two hash domains over one origin (raw bytes vs LF-normalised text)
E4-02  text equivalence narrated as byte identity
E4-03  a narrative claim that counts nine attempts as nine executions
E4-04  a verification artefact that only reads in the root that produced it
E4-05  deleting the previous projection before the new one is published
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import evidence004_generate as generate  # noqa: E402
import evidence004_ledger as ledger  # noqa: E402
import evidence004_verify as verify  # noqa: E402

PACKAGE = REPO / verify.PACKAGE_REL
TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".csv", ".txt", ".py"})


def _as_crlf(path: Path) -> None:
    raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes(raw)


def _copy_package(tmp_path: Path, endings: str = "LF") -> Path:
    root = tmp_path / f"root-{endings}"
    shutil.copytree(PACKAGE, root / verify.PACKAGE_REL)
    if endings == "CRLF":
        for path in (root / verify.PACKAGE_REL).rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                _as_crlf(path)
    return root


def _synthetic_root(tmp_path: Path, endings: str) -> Path:
    root = tmp_path / f"synth-{endings}"
    rea = root.joinpath(*ledger.PACKAGE_REL_PARTS) / "rea"
    rea.mkdir(parents=True)
    rows = [
        {
            "timestamp": "2026-10-18T01:00:00Z",
            "operation": "analyze_javascript_application",
            "target_id": "T-X",
            "exit_code": 0,
            "evidence_id": "ev_" + "a" * 64,
        },
        {
            "timestamp": "2026-10-18T01:05:00Z",
            "operation": "compare-source-to-bundle",
            "target_id": "T-X",
            "exit_code": 0,
            "result": "NOT_EXECUTED_INVALID_INPUT",
        },
    ]
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    if endings == "CRLF":
        payload = payload.replace(b"\n", b"\r\n")
    (rea / "REA_COMMAND_LOG.jsonl").write_bytes(payload)
    return root


# ------------------------------------------------------------------------- E4-01


def test_the_same_log_hashes_the_same_way_in_lf_and_crlf(tmp_path: Path) -> None:
    """One origin, one identity: the rule that failed was raw bytes vs LF text."""

    lf = ledger.build_ledger(root=_synthetic_root(tmp_path, "LF"))
    crlf = ledger.build_ledger(root=_synthetic_root(tmp_path, "CRLF"))

    assert lf["ledger_sha256"] == crlf["ledger_sha256"]
    assert lf["source_files"] == crlf["source_files"]
    assert lf["counts"] == crlf["counts"]


def test_a_semantic_change_still_moves_the_hash(tmp_path: Path) -> None:
    root = _synthetic_root(tmp_path, "LF")
    before = ledger.build_ledger(root=root)["ledger_sha256"]
    log = root.joinpath(*ledger.PACKAGE_REL_PARTS) / "rea" / "REA_COMMAND_LOG.jsonl"
    log.write_bytes(log.read_bytes().replace(b'"exit_code": 0', b'"exit_code": 1', 1))

    after = ledger.build_ledger(root=root)["ledger_sha256"]

    assert before != after


def test_every_source_file_pin_names_its_hash_domain() -> None:
    payload = ledger.build_ledger()
    entries = payload["source_files"]

    assert entries, "a pin set with no entries proves nothing"
    for entry in entries:
        assert entry["hash_domain"] in {"TEXT_CANONICAL_LF", "BINARY_RAW"}
        assert len(entry["content_sha256"]) == 64
        if Path(entry["path"]).suffix.lower() in TEXT_SUFFIXES:
            assert entry["hash_domain"] == "TEXT_CANONICAL_LF"
        else:
            assert entry["hash_domain"] == "BINARY_RAW"


def test_the_canonical_object_keeps_a_span_the_verifier_can_recheck() -> None:
    """The published span list was empty, so 'spans match their bytes' proved nothing."""

    canonical = generate.build_canonical()
    spans = [
        span
        for event in canonical["events"]
        for span in event.get("sources", [])
        if span.get("content_sha256")
    ]

    assert spans, "the canonical object must publish the spans it was built from"
    assert len({span["path"] for span in spans}) >= 5


# ------------------------------------------------------------------------- E4-02


def test_the_supersession_manifest_declares_the_identity_it_pins() -> None:
    manifest = json.loads(
        (REPO / verify.EVIDENCE_REL / "SUPERSESSION_MANIFEST.json").read_text(encoding="utf-8")
    )

    assert "hash_domains" in manifest, "the manifest must name each domain and its authority"
    for record in manifest["documents"]:
        preservation = record["preservation"]
        assert preservation["hash_domain"] in {"TEXT_CANONICAL_LF", "BINARY_RAW"}
        # A text document has no byte identity across checkouts, so it cannot claim one.
        if Path(str(record["path"])).suffix.lower() in TEXT_SUFFIXES:
            assert record.get("preserved_bytes") is not True


def test_claiming_byte_identity_for_a_text_document_is_caught(copied_root: Path) -> None:
    manifest = copied_root / verify.EVIDENCE_REL / "SUPERSESSION_MANIFEST.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["documents"][0]["preserved_bytes"] = True
    payload["documents"][0]["preservation"]["hash_domain"] = "BINARY_RAW"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    verdict = verify.verify_package(copied_root)

    assert any(
        failure["name"] == "supersession_declares_the_identity_it_pins"
        for failure in verdict.failures
    ), verdict.failures


# ------------------------------------------------------------------------- E4-03


def test_a_free_text_claim_that_says_nine_ran_is_refused() -> None:
    canonical = generate.build_canonical()
    claims = [
        {
            "claim_id": "C-01",
            "kind": "COUNTER",
            "pointer": "counts.phase_v31.work.operations",
            "expected": 9,
            "text": "This iteration ran 9 REA work operations.",
        }
    ]

    with pytest.raises(generate.GenerationError, match="digit"):
        generate.verify_claims(canonical, claims)


def test_a_narrative_claim_that_reports_attempts_must_report_the_refusals() -> None:
    canonical = generate.build_canonical()
    claims = [
        {
            "claim_id": "C-01",
            "kind": "NARRATIVE",
            "template": "This iteration registered {operations} REA work operations.",
            "counters": {"operations": "counts.phase_v31.work.operations"},
        }
    ]

    with pytest.raises(generate.GenerationError, match="not_executed"):
        generate.verify_claims(canonical, claims)


def test_a_hardcoded_number_in_a_template_is_refused() -> None:
    canonical = generate.build_canonical()
    claims = [
        {
            "claim_id": "C-01",
            "kind": "NARRATIVE",
            "template": "9 REA work operations were registered and {not_executed} did not run.",
            "counters": {"not_executed": "counts.phase_v31.work.not_executed"},
        }
    ]

    with pytest.raises(generate.GenerationError, match="9"):
        generate.verify_claims(canonical, claims)


def test_the_published_claims_render_nine_registered_seven_executed_two_refused() -> None:
    canonical = generate.build_canonical()
    claims = json.loads(generate.CLAIMS_PATH.read_text(encoding="utf-8"))
    resolved = generate.verify_claims(canonical, claims)
    rendered = " ".join(str(claim.get("rendered", "")) for claim in resolved)

    assert "9 REA work operations were registered" in rendered
    assert "7 executed and returned an evidence_id" in rendered
    assert "2 did not execute" in rendered
    assert "ran 9" not in rendered.lower()


def test_the_package_report_does_not_claim_it_left_the_tests_alone() -> None:
    text = (REPO / verify.EVIDENCE_REL / "FINAL_REPORT.md").read_text(encoding="utf-8")

    assert "Cero cambios en `src/`, `tests/`" not in text
    assert "tres módulos de pruebas" in text.lower() or "3 módulos" in text


# ------------------------------------------------------------------------- E4-04


def test_two_roots_at_different_line_endings_verify_to_the_same_bytes(
    tmp_path: Path,
) -> None:
    lf = _copy_package(tmp_path, "LF")
    crlf = _copy_package(tmp_path, "CRLF")

    lf_payload = verify.render_payload(verify.build_payload(lf))
    crlf_payload = verify.render_payload(verify.build_payload(crlf))

    assert lf_payload == crlf_payload


def test_the_verification_artefact_carries_no_absolute_path(tmp_path: Path) -> None:
    root = _copy_package(tmp_path, "CRLF")
    rendered = verify.render_payload(verify.build_payload(root))

    assert str(tmp_path).replace("\\", "/") not in rendered
    assert str(root) not in rendered
    assert "C:\\\\" not in rendered and "C:/" not in rendered


def test_a_crlf_checkout_verifies_without_complaint(tmp_path: Path) -> None:
    root = _copy_package(tmp_path, "CRLF")

    verdict = verify.verify_package(root)

    assert verdict.failures == [], verdict.failures


# ------------------------------------------------------------------------- E4-05


def _fail_on_call(patch_target: str, bang_at: int) -> Any:
    """Make the ``bang_at``-th call raise ENOSPC, letting earlier calls succeed."""

    real = getattr(generate, patch_target)
    state = {"calls": 0}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == bang_at:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    return wrapper


def test_a_disk_full_mid_publish_keeps_the_previous_projection(tmp_path: Path) -> None:
    root = _copy_package(tmp_path, "LF")
    evidence = root / verify.EVIDENCE_REL
    manifest_before = (evidence / "CURRENT_MANIFEST.json").read_bytes()
    canonical_before = (evidence / "canonical" / "CANONICAL_RUN.json").read_bytes()
    documents_before = sorted(p.name for p in (evidence / "derived").iterdir() if p.is_dir())

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(generate, "write_atomic", _fail_on_call("write_atomic", 3))
        with pytest.raises(OSError, match="No space left"):
            generate.generate(layout=ledger.Layout(root))

    assert (evidence / "CURRENT_MANIFEST.json").read_bytes() == manifest_before
    assert (evidence / "canonical" / "CANONICAL_RUN.json").read_bytes() == canonical_before
    assert sorted(p.name for p in (evidence / "derived").iterdir() if p.is_dir()) == documents_before
    assert verify.verify_package(root).failures == []


def test_an_orphan_projection_is_only_pruned_after_a_successful_publish(
    tmp_path: Path,
) -> None:
    root = _copy_package(tmp_path, "LF")
    orphan = root / verify.EVIDENCE_REL / "derived" / "000000000000"
    orphan.mkdir()
    (orphan / "RUN_REPORT.md").write_text("crashed run\n", encoding="utf-8")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(generate, "write_atomic", _fail_on_call("write_atomic", 2))
        with pytest.raises(OSError):
            generate.generate(layout=ledger.Layout(root))
    assert orphan.is_dir(), "a failed publish must not clean up"

    generate.generate(layout=ledger.Layout(root))
    assert not orphan.is_dir()


def test_publishing_keeps_the_previous_projection_until_it_is_recorded(
    tmp_path: Path,
) -> None:
    root = _copy_package(tmp_path, "LF")
    evidence = root / verify.EVIDENCE_REL
    before = json.loads((evidence / "CURRENT_MANIFEST.json").read_text(encoding="utf-8"))

    # A changed raw log produces a different ledger, so a second projection appears.
    log = root / verify.PACKAGE_REL / "rea" / "REA_COMMAND_LOG.jsonl"
    rows = log.read_text(encoding="utf-8").splitlines()
    rows.append(
        json.dumps(
            {
                "timestamp": "2026-10-18T02:00:00Z",
                "operation": "capture_web_screenshot",
                "target_id": "T-QR-SIGNAL",
                "exit_code": 0,
                "evidence_id": "ev_" + "b" * 64,
            }
        )
    )
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")

    generate.generate(layout=ledger.Layout(root))

    previous = root / str(before["derived_dir"])
    assert previous.is_dir(), "the superseded projection must survive the publish"
    record = json.loads((evidence / "SUPERSEDED_PROJECTIONS.json").read_text(encoding="utf-8"))
    assert any(row["ledger_sha256"] == before["ledger_sha256"] for row in record["projections"])


@pytest.fixture()
def copied_root(tmp_path: Path) -> Path:
    return _copy_package(tmp_path, "LF")
