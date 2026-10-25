"""RFC-048 provenance integrity (WP-TDM-07).

The historical bundle pinned digests computed over CRLF bytes that the repository
never stores, so ``sha256(file) != recorded`` for every JSON source and two tests
failed at HEAD. WP-TDM-07 diagnosed the drift, kept v1 byte-identical and added a
versioned v2 bundle that pins the bytes as delivered.

These tests are what makes the new bundle evidence rather than assertion:

* v2 digests equal the digest of the file **and** of the git blob;
* v1 is still present, unchanged, and its defect is reproducible (not erased);
* the v2 evidence bundle matches its own manifest;
* corrupting a payload is still detected — the fix does not blunt the check.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from trading_bot.risk.futures_verification import (
    authoritative_evidence_dir,
    load_fixtures,
    run_verification,
    verify_decision,
)

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "rfc048"
PROVENANCE_V2 = DATA / "provenance" / "PROVENANCE@v2.json"
EVIDENCE_V2 = DATA / "provenance" / "evidence-v2"

pytestmark = pytest.mark.unit


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob(relative: str) -> bytes:
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{relative}"],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def crlf(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def test_v2_is_the_authoritative_generation() -> None:
    assert PROVENANCE_V2.is_file(), "v2 provenance must exist"
    fixtures = load_fixtures(EVIDENCE_V2)
    assert fixtures.provenance_version == "v2"
    assert fixtures.provenance["schema_version"] == "rfc048-provenance-v2"


def test_v2_records_the_digest_of_the_bytes_git_delivers() -> None:
    """The whole point: the recorded digest must be reproducible from the repo."""
    provenance = json.loads(PROVENANCE_V2.read_text(encoding="utf-8"))
    for key, entry in provenance["sources"].items():
        path = REPO / entry["file"]
        payload = path.read_bytes()
        assert entry["sha256"] == sha256(payload), f"{key}: digest does not match the file"
        assert entry["bytes"] == len(payload), f"{key}: byte count does not match the file"
        blob = git_blob(entry["file"])
        assert blob == payload, f"{key}: working tree differs from the committed blob"
        assert sha256(blob) == entry["sha256"]


def test_the_historical_v1_bundle_is_preserved_untouched() -> None:
    provenance_v2 = json.loads(PROVENANCE_V2.read_text(encoding="utf-8"))
    supersedes = provenance_v2["supersedes"]
    assert sha256((DATA / "PROVENANCE.json").read_bytes()) == supersedes["sha256"]
    v2_instruments = json.loads((DATA / "provenance" / "INSTRUMENTS@v2.json").read_text("utf-8"))
    assert sha256((DATA / "INSTRUMENTS.json").read_bytes()) == v2_instruments["provenance"][
        "supersedes"
    ]["sha256"]
    # v1 must still carry its original (CRLF-based) digests: history is not rewritten.
    v1 = json.loads((DATA / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert v1["sources"]["leverage_brackets"]["sha256"] == provenance_v2["sources"][
        "leverage_brackets"
    ]["v1_sha256"]


def test_the_v1_defect_is_reproducible_and_explained() -> None:
    """v1 digests describe the CRLF form of the same payload — that is the diagnosis."""
    provenance_v2 = json.loads(PROVENANCE_V2.read_text(encoding="utf-8"))
    relations = provenance_v2["defect_in_v1"]["relation_counts"]
    assert relations["UNEXPLAINED"] == 0
    assert relations["crlf_normalized"] >= 6
    for key, entry in provenance_v2["sources"].items():
        payload = (REPO / entry["file"]).read_bytes()
        if entry["v1_relation"] == "crlf_normalized":
            assert sha256(crlf(payload)) == entry["v1_sha256"], key
        else:
            assert entry["v1_relation"] == "as_stored"
            assert sha256(payload) == entry["v1_sha256"], key


def test_the_v2_evidence_bundle_matches_its_manifest() -> None:
    manifest = json.loads((EVIDENCE_V2 / "GENERATION.json").read_text(encoding="utf-8"))
    for relative, row in manifest["files"].items():
        path = EVIDENCE_V2 / relative
        assert path.is_file(), f"missing {relative}"
        payload = path.read_bytes()
        assert sha256(payload) == row["sha256"], relative
        assert len(payload) == row["bytes"], relative


def test_corrupting_a_payload_is_still_detected(tmp_path: Path) -> None:
    """The provenance fix must not blunt the verifier: one byte is enough."""
    bundle = tmp_path / "rfc048"
    shutil.copytree(EVIDENCE_V2, bundle)
    target = bundle / "raw" / "binance_usdm_leverage_brackets_btcusdt.json"
    payload = bytearray(target.read_bytes())
    payload[10] ^= 0x01
    target.write_bytes(bytes(payload))

    fixtures = load_fixtures(bundle)
    cases = json.loads((bundle / "RISK_SCENARIOS.json").read_text(encoding="utf-8"))["cases"]
    checks, _numbers = verify_decision(cases[0], fixtures)
    failed = [c.name for c in checks if not c.passed]
    assert "bracket_provenance" in failed


def test_truncated_evidence_fails_loudly_instead_of_verifying(tmp_path: Path) -> None:
    """A half-written payload must raise, never yield a clean verdict."""
    bundle = tmp_path / "rfc048"
    shutil.copytree(EVIDENCE_V2, bundle)
    target = bundle / "MARKET_SNAPSHOT.json"
    target.write_bytes(target.read_bytes()[: len(target.read_bytes()) // 2])

    with pytest.raises(json.JSONDecodeError):
        load_fixtures(bundle)


def test_an_empty_bundle_cannot_be_verified(tmp_path: Path) -> None:
    """No evidence is not nothing to check: the loader refuses."""
    empty = tmp_path / "rfc048"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        load_fixtures(empty)


def test_a_gutted_scenario_file_runs_no_checks(tmp_path: Path) -> None:
    """An emptied decision list must not read as a pass (``all([]) is True``)."""
    bundle = tmp_path / "rfc048"
    shutil.copytree(EVIDENCE_V2, bundle)
    (bundle / "RISK_SCENARIOS.json").write_text('{"cases": []}\n', encoding="utf-8")

    result = run_verification({"decisions": []}, load_fixtures(bundle))
    assert result["verdict"] != "VERIFIED"
    assert result["decisions_verified"] == 0


def test_the_historical_bundle_is_still_readable_as_v1() -> None:
    """Keeping v1 usable is what makes the correction auditable, not a rewrite."""
    fixtures = load_fixtures(DATA, generation="v1")
    assert fixtures.provenance_version == "v1"
    # And its digests still describe the CRLF form, exactly as they did in 2026-09.
    raw = (DATA / "raw" / "binance_usdm_leverage_brackets_btcusdt.json").read_bytes()
    assert fixtures.provenance["sources"]["leverage_brackets"]["sha256"] == sha256(crlf(raw))
    assert authoritative_evidence_dir(DATA) == EVIDENCE_V2


def test_asking_for_v2_never_silently_degrades_to_v1(tmp_path: Path) -> None:
    legacy = tmp_path / "rfc048"
    legacy.mkdir()
    shutil.copy(DATA / "PROVENANCE.json", legacy / "PROVENANCE.json")
    shutil.copy(DATA / "INSTRUMENTS.json", legacy / "INSTRUMENTS.json")
    with pytest.raises(FileNotFoundError):
        load_fixtures(legacy, generation="v2")
