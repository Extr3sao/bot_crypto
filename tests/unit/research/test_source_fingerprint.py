"""Contract tests for the RFC-TDM-014A canonical source fingerprint (WP-14B).

The tests are hermetic: each one builds a throwaway Git repository, commits a
module, and asks the fingerprint for an identity. Nothing here depends on the
working tree of the repository under test, because the whole point of the fix is
that the answer must not depend on the checkout.

The last two tests read the *committed* TDM-12 registry, which is historical
evidence: reading it must not mutate it, and its ``v1`` identity must be refused
as comparable to a ``v2`` one.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research import source_fingerprint as sf  # noqa: E402

MODULE = "module.py"
LF_BODY = "def answer():\n    return 42\n"
CRLF_BODY = LF_BODY.replace("\n", "\r\n")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "tdm14a@example.invalid")
    git(root, "config", "user.name", "TDM-14A test")
    git(root, "config", "core.autocrlf", "false")
    (root / MODULE).write_bytes(LF_BODY.encode("utf-8"))
    git(root, "add", MODULE)
    git(root, "commit", "-m", "add module")
    return root


def blob_oid(repo: Path, relpath: str = MODULE) -> str:
    return git(repo, "rev-parse", f"HEAD:{relpath}")


# ---------------------------------------------------------------------------
# 1. same blob, different EOL -> identical v2 digest
# ---------------------------------------------------------------------------


def test_crlf_and_lf_checkouts_of_the_same_blob_share_one_v2_digest(repo: Path) -> None:
    lf = sf.compute_source_fingerprint(repo, MODULE)
    lf_bytes = (repo / MODULE).read_bytes()

    git(repo, "config", "core.autocrlf", "true")
    (repo / MODULE).write_bytes(CRLF_BODY.encode("utf-8"))
    crlf_bytes = (repo / MODULE).read_bytes()

    # The premise: real byte difference that Git still maps to the same content.
    assert lf_bytes != crlf_bytes
    assert len(crlf_bytes) > len(lf_bytes)
    assert git(repo, "hash-object", f"--path={MODULE}", "--", MODULE) == blob_oid(repo)
    assert git(repo, "diff", "HEAD", "--", MODULE) == ""

    crlf = sf.compute_source_fingerprint(repo, MODULE)

    assert crlf.fingerprint_scheme == sf.FINGERPRINT_SCHEME_V2
    assert crlf.source_fingerprint == lf.source_fingerprint
    assert crlf.source_blob_oid == lf.source_blob_oid == blob_oid(repo)
    # The defect that motivated the RFC is exactly this: v1 hashes what is on disk.
    assert sf.legacy_working_tree_fingerprint(repo / MODULE) != lf.source_fingerprint


def test_v1_still_disagrees_across_line_endings(repo: Path) -> None:
    """D-01 is real: the historical scheme answers about the checkout."""
    git(repo, "config", "core.autocrlf", "true")
    (repo / MODULE).write_bytes(CRLF_BODY.encode("utf-8"))
    v1_crlf = sf.legacy_working_tree_fingerprint(repo / MODULE)
    v2_crlf = sf.compute_source_fingerprint(repo, MODULE)

    git(repo, "config", "core.autocrlf", "false")
    (repo / MODULE).write_bytes(LF_BODY.encode("utf-8"))
    v1_lf = sf.legacy_working_tree_fingerprint(repo / MODULE)
    v2_lf = sf.compute_source_fingerprint(repo, MODULE)

    assert v1_lf != v1_crlf
    assert v2_lf.source_fingerprint == v2_crlf.source_fingerprint


# ---------------------------------------------------------------------------
# 2. same content, different checkout path -> identical digest, audited path
# ---------------------------------------------------------------------------


def test_different_checkout_paths_share_the_digest_and_keep_their_own_path(
    repo: Path, tmp_path: Path
) -> None:
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", str(repo), str(clone)],
        capture_output=True,
        check=True,
    )
    here = sf.compute_source_fingerprint(repo, MODULE)
    there = sf.compute_source_fingerprint(clone, MODULE)

    assert here.source_fingerprint == there.source_fingerprint
    assert here.source_blob_oid == there.source_blob_oid
    # Same code, but each side records the path it actually audited.
    assert here.source_relpath == there.source_relpath == MODULE
    assert sf.verify_fingerprint(here, clone).source_fingerprint == here.source_fingerprint


def test_relative_path_spelling_does_not_change_the_identity(repo: Path) -> None:
    a = sf.compute_source_fingerprint(repo, MODULE)
    b = sf.compute_source_fingerprint(repo, "./" + MODULE)
    assert a.source_fingerprint == b.source_fingerprint
    assert a.source_relpath == b.source_relpath == MODULE


# ---------------------------------------------------------------------------
# 3. a real source change is refused, staged or unstaged
# ---------------------------------------------------------------------------


def test_unstaged_change_is_refused(repo: Path) -> None:
    (repo / MODULE).write_text(LF_BODY + "\n# edited\n", encoding="utf-8")
    with pytest.raises(sf.WorkingTreeDirtyError):
        sf.compute_source_fingerprint(repo, MODULE)


def test_unstaged_change_under_autocrlf_is_still_refused(repo: Path) -> None:
    """The tolerated transformation is line endings, not edits."""
    git(repo, "config", "core.autocrlf", "true")
    (repo / MODULE).write_bytes((LF_BODY + "# edited\n").replace("\n", "\r\n").encode("utf-8"))
    with pytest.raises(sf.WorkingTreeDirtyError):
        sf.compute_source_fingerprint(repo, MODULE)


def test_staged_change_is_refused(repo: Path) -> None:
    (repo / MODULE).write_text(LF_BODY + "\n# staged edit\n", encoding="utf-8")
    git(repo, "add", MODULE)
    with pytest.raises(sf.WorkingTreeDirtyError):
        sf.compute_source_fingerprint(repo, MODULE)


def test_untracked_file_is_refused(repo: Path) -> None:
    with pytest.raises(sf.SourceNotCommittedError):
        sf.compute_source_fingerprint(repo, "not_yet_added.py")


def test_absent_file_is_refused(repo: Path) -> None:
    with pytest.raises(sf.SourceNotCommittedError):
        sf.compute_source_fingerprint(repo, "does_not_exist.py")


def test_a_committed_change_changes_the_digest(repo: Path) -> None:
    before = sf.compute_source_fingerprint(repo, MODULE)
    (repo / MODULE).write_text(LF_BODY + "\n# real change\n", encoding="utf-8")
    git(repo, "commit", "-am", "change module")
    after = sf.compute_source_fingerprint(repo, MODULE)
    assert before.source_fingerprint != after.source_fingerprint
    assert before.source_blob_oid != after.source_blob_oid


def test_git_unavailable_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    (not_a_repo / MODULE).write_text(LF_BODY, encoding="utf-8")

    def explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("git exploded")

    monkeypatch.setattr(sf.subprocess, "run", explode)
    with pytest.raises(sf.GitUnavailableError):
        sf.compute_source_fingerprint(not_a_repo, MODULE)


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    (not_a_repo / MODULE).write_text(LF_BODY, encoding="utf-8")
    with pytest.raises(sf.FingerprintError):
        sf.compute_source_fingerprint(not_a_repo, MODULE)


def test_v2_cannot_be_constructed_without_provenance() -> None:
    with pytest.raises(sf.FingerprintError):
        sf.SourceFingerprint(
            fingerprint_scheme=sf.FINGERPRINT_SCHEME_V2,
            source_fingerprint="a" * 64,
            source_relpath=MODULE,
            source_commit=None,
            source_blob_oid=None,
            working_tree_clean_verified=True,
            bytes_hashed=10,
            algorithm="sha256(git_cat_file_blob)",
        )
    with pytest.raises(sf.FingerprintError):
        sf.SourceFingerprint(
            fingerprint_scheme=sf.FINGERPRINT_SCHEME_V2,
            source_fingerprint="a" * 64,
            source_relpath=MODULE,
            source_commit="0" * 40,
            source_blob_oid="0" * 40,
            working_tree_clean_verified=False,
            bytes_hashed=10,
            algorithm="sha256(git_cat_file_blob)",
        )


# ---------------------------------------------------------------------------
# 5. historical v1 artefacts: read, never rewritten, never silently compared
# ---------------------------------------------------------------------------


def test_historical_row_is_read_as_v1_without_being_rewritten() -> None:
    registry = ROOT / "evidence" / "tdm" / "wp-tdm-12" / "CANDIDATE_REGISTRY.json"
    before = hashlib.sha256(registry.read_bytes()).hexdigest()
    import json

    payload = json.loads(registry.read_text(encoding="utf-8"))
    row = payload["rows"][0]
    assert "fingerprint_scheme" not in row  # it predates the scheme

    read = sf.read_fingerprint(row)
    assert read.fingerprint_scheme == sf.FINGERPRINT_SCHEME_V1
    assert read.source_fingerprint == row["parameter_hash"]
    assert read.working_tree_clean_verified is False
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before


def test_v1_and_v2_are_not_comparable() -> None:
    v1 = sf.read_fingerprint({"parameter_hash": "9825f38950c5b975"})
    v2 = sf.SourceFingerprint(
        fingerprint_scheme=sf.FINGERPRINT_SCHEME_V2,
        source_fingerprint="9825f38950c5b975" + "0" * 48,
        source_relpath="src/x.py",
        source_commit="0" * 40,
        source_blob_oid="0" * 40,
        working_tree_clean_verified=True,
        bytes_hashed=1,
        algorithm="sha256(git_cat_file_blob)",
    )
    with pytest.raises(sf.IncompatibleFingerprintScheme):
        sf.assert_comparable(v1, v2)
    with pytest.raises(sf.IncompatibleFingerprintScheme):
        sf.verify_fingerprint(v1, ROOT)


def test_truncation_alias_keeps_the_published_width() -> None:
    fp = sf.SourceFingerprint(
        fingerprint_scheme=sf.FINGERPRINT_SCHEME_V2,
        source_fingerprint="abcdef0123456789" + "f" * 48,
        source_relpath="src/x.py",
        source_commit="0" * 40,
        source_blob_oid="0" * 40,
        working_tree_clean_verified=True,
        bytes_hashed=1,
        algorithm="sha256(git_cat_file_blob)",
    )
    assert fp.legacy_parameter_hash == "abcdef0123456789"
    assert len(fp.to_dict()["parameter_hash"]) == sf.LEGACY_TRUNCATION
