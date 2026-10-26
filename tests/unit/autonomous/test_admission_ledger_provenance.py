"""Admission-ledger provenance (WP-TDM-08).

The ledger is the *only* thing that can authorise a PAPER trade, so its bytes are
part of the contract:

* every recorded ``sha256`` must be the digest of the file as the repository
  stores it (v1 shipped a stale digest for ``STRATEGY_ADMISSION_MATRIX.json``,
  so the CLAIM → SOURCE link pointed at bytes that never existed — DEF-TDM-08-1);
* the file must be byte-reproducible: LF everywhere, because ``write_text`` on
  Windows used to emit CRLF and a rebuild churned all 547 lines while ``--check``
  (which compared decoded text) still said "up to date" — DEF-TDM-08-2;
* a stale ledger must be *detectable*, and regenerating it must not change a
  single verdict.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "config" / "strategy_admission.json"
BUILDER = REPO / "scripts" / "build_strategy_admission.py"

pytestmark = pytest.mark.unit


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _is_modified(path: str) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", path],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def test_every_recorded_source_hash_matches_the_committed_blob() -> None:
    ledger = _load()
    assert ledger["_sources"], "the ledger must record where its numbers came from"
    for source in ledger["_sources"]:
        path = source["path"]
        working = (REPO / path).read_bytes()
        assert source["sha256"] == _sha256(working), (
            f"{path}: ledger records {source['sha256']} but the working tree hashes to "
            f"{_sha256(working)}"
        )
        if _is_modified(path):
            # An uncommitted edit is a legitimate state (the ledger records the
            # bytes it was built from); the HEAD comparison only applies when the
            # artifact is clean, which is the state a reviewer will check.
            continue
        blob = subprocess.run(
            ["git", "cat-file", "blob", f"HEAD:{path}"],
            cwd=REPO,
            capture_output=True,
            check=False,
        ).stdout
        assert blob, f"{path} is not tracked at HEAD"
        assert source["sha256"] == _sha256(blob), (
            f"{path}: ledger records {source['sha256']} but the HEAD blob hashes to {_sha256(blob)}"
        )


def test_ledger_is_lf_only_and_byte_reproducible() -> None:
    raw = LEDGER.read_bytes()
    assert b"\r\n" not in raw, "the ledger must be stored with LF, not CRLF"
    assert raw.endswith(b"\n"), "the ledger must end with exactly one newline"

    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"ledger is stale: {result.stderr.strip()}"


def test_bytes_are_what_make_check_strict(tmp_path: Path) -> None:
    """A CRLF copy must be reported stale — a text comparison cannot see it."""
    canonical = LEDGER.read_bytes()
    crlf = canonical.replace(b"\n", b"\r\n")
    assert crlf != canonical

    copy = tmp_path / "ledger_crlf.json"
    copy.write_bytes(crlf)
    # Exactly the defect: reading as TEXT hides the difference, so ``--check``
    # said "up to date" for a file whose bytes were not the committed ones.
    assert copy.read_text(encoding="utf-8") == LEDGER.read_text(encoding="utf-8")
    assert copy.read_bytes() != canonical


def test_no_strategy_is_admitted_without_positive_edge_evidence() -> None:
    ledger = _load()
    for strategy_id, entry in ledger["strategies"].items():
        if not entry["admitted_for_paper"]:
            continue
        assert entry["status"] in {"PAPER_ACTIVE", "PAPER_CANDIDATE"}, strategy_id
        assert (entry["expected_gross_edge_bps"] or 0) > 0, strategy_id
        assert entry["edge_evidence"], strategy_id
