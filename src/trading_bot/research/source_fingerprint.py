"""Canonical, versioned source fingerprints — the fix for defect D-01.

The historical scheme (``v1``) hashed the bytes a module happened to have on disk
after checkout filters ran. Two checkouts of the same commit that differ only in
``core.autocrlf`` therefore produced two different identities for the same code
(4.640 LF bytes vs 4.776 CRLF bytes, same Git blob ``03fbb1bf…``).

``v2`` hashes the **Git blob** of the source file at the commit that is being
executed, so the identity follows the content Git stores, not the checkout:

* line endings are handled by the one mechanism that is allowed to handle them —
  Git itself, through the blob;
* a different checkout path cannot change the digest;
* a file that is *not* the committed file (untracked, modified, staged, absent,
  or unreadable) is refused by the preflight instead of being hashed anyway. The
  failure is explicit and fail-closed: no fingerprint is returned.

What a ``v2`` fingerprint does **not** cover, stated here so nobody has to infer
it from the name: only the named file. Not the strategy parameters a family
happens to read, not its transitive imports, not the data it consumes, not the
rest of the repository. ``source_commit`` is recorded next to the digest as
provenance but is deliberately excluded from the digest itself, so identical
content stays identical across commits.

Backwards compatibility is a read-only adapter, never a silent rewrite: a
historical artefact carries ``v1`` with no scheme marker, is read as ``v1`` and is
left untouched, and comparing a ``v1`` identity with a ``v2`` identity raises
:class:`IncompatibleFingerprintScheme` instead of quietly returning "equal" or
"different".
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "FINGERPRINT_SCHEME_V1",
    "FINGERPRINT_SCHEME_V2",
    "FingerprintError",
    "GitUnavailableError",
    "IncompatibleFingerprintScheme",
    "SourceFingerprint",
    "SourceNotCommittedError",
    "WorkingTreeDirtyError",
    "assert_comparable",
    "compute_source_fingerprint",
    "git_blob_bytes",
    "git_blob_oid",
    "legacy_working_tree_fingerprint",
    "read_fingerprint",
    "verify_fingerprint",
    "working_tree_deviations",
]

FINGERPRINT_SCHEME_V1: Final[str] = "v1"
FINGERPRINT_SCHEME_V2: Final[str] = "v2"

#: ``v1`` truncated its digest to 16 hex characters when publishing it. The width
#: is part of the published contract, so ``v2`` keeps the same width for the
#: compatibility field while publishing the full digest separately.
LEGACY_TRUNCATION: Final[int] = 16


class FingerprintError(RuntimeError):
    """Base class: the fingerprint could not be established."""


class GitUnavailableError(FingerprintError):
    """Git could not be invoked, or refused to answer."""


class SourceNotCommittedError(FingerprintError):
    """The source file is absent from the commit, so it has no blob to hash."""


class WorkingTreeDirtyError(FingerprintError):
    """The source file differs from the commit that is being executed."""


class IncompatibleFingerprintScheme(FingerprintError):
    """Two fingerprints use different schemes and are not comparable."""


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
    except OSError as exc:  # git missing, permissions, broken worktree
        raise GitUnavailableError(f"cannot run git in {repo_root}: {exc}") from exc


def git_blob_bytes(repo_root: Path, commit: str, relpath: str) -> bytes:
    """Raw bytes of ``<commit>:<relpath>`` exactly as Git stores them."""
    proc = _git(repo_root, "cat-file", "blob", f"{commit}:{relpath}")
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip() or "no such object"
        raise SourceNotCommittedError(f"{relpath} is not committed at {commit}: {message}")
    return proc.stdout


def git_blob_oid(repo_root: Path, commit: str, relpath: str) -> str:
    """The blob id Git assigns to the committed content of ``relpath``."""
    proc = _git(repo_root, "rev-parse", "--verify", f"{commit}:{relpath}")
    oid = proc.stdout.decode("ascii", "replace").strip()
    if proc.returncode != 0 or len(oid) < 40:
        message = proc.stderr.decode("utf-8", "replace").strip() or "unresolvable path"
        raise SourceNotCommittedError(f"{relpath} has no blob at {commit}: {message}")
    return oid


def legacy_working_tree_fingerprint(path: Path) -> str:
    """The historical ``v1`` algorithm, kept only to read and reproduce old artefacts.

    It hashes the bytes on disk. That is the whole defect: it answers a question
    about the checkout, not about the code.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def working_tree_deviations(repo_root: Path, commit: str, relpath: str, oid: str) -> list[str]:
    """Every way the checkout can disagree with ``<commit>:<relpath>``, or ``[]``.

    ``git status --porcelain`` is deliberately **not** the oracle here. On a file
    that Git's own checkout wrote with CRLF, the index stat cache can be stale, and
    status then reports `` M path`` forever even though the content is identical:
    measured on git 2.51.1, ``git status`` says `` M m.py`` while
    ``git diff HEAD -- m.py`` exits 0 and ``git hash-object --path=m.py m.py``
    returns exactly ``HEAD:m.py``. Using status would refuse the very checkout the
    RFC tells us to accept, and using it the other way round would accept a real
    edit: both failure modes are wrong.

    So the test is content, through Git's own filters:

    * the path must be tracked (``ls-files --error-unmatch``);
    * the index must carry the commit's blob (``diff-index --cached --quiet``);
    * the file must exist and, hashed *with its path's filters*, must reproduce
      that same blob id. Which is precisely "if you committed this now, you would
      commit the same bytes Git already stores".
    """
    problems: list[str] = []

    tracked = _git(repo_root, "ls-files", "--error-unmatch", "--", relpath)
    if tracked.returncode != 0:
        problems.append("untracked in the working tree")

    staged = _git(repo_root, "diff-index", "--cached", "--quiet", commit, "--", relpath)
    if staged.returncode == 1:
        problems.append(f"index differs from {commit} (staged change)")
    elif staged.returncode != 0:
        message = staged.stderr.decode("utf-8", "replace").strip() or "diff-index failed"
        raise GitUnavailableError(f"cannot compare index with {commit}: {message}")

    path = repo_root / relpath
    if not path.is_file():
        problems.append("missing from the working tree")
        return problems

    hashed = _git(repo_root, "hash-object", f"--path={relpath}", "--", relpath)
    if hashed.returncode != 0:
        message = hashed.stderr.decode("utf-8", "replace").strip() or "hash-object failed"
        raise GitUnavailableError(f"cannot hash {relpath} through its filters: {message}")
    actual = hashed.stdout.decode("ascii", "replace").strip()
    if actual != oid:
        problems.append(f"working-tree content hashes to {actual} but {commit}:{relpath} is {oid}")
    return problems


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """One identity for one source file, with the evidence that backs it."""

    fingerprint_scheme: str
    source_fingerprint: str
    source_relpath: str
    source_commit: str | None
    source_blob_oid: str | None
    working_tree_clean_verified: bool
    bytes_hashed: int
    algorithm: str

    def __post_init__(self) -> None:
        if self.fingerprint_scheme not in (FINGERPRINT_SCHEME_V1, FINGERPRINT_SCHEME_V2):
            raise FingerprintError(f"unknown fingerprint scheme {self.fingerprint_scheme!r}")
        if not self.source_fingerprint:
            raise FingerprintError("empty fingerprint")
        if self.fingerprint_scheme == FINGERPRINT_SCHEME_V2:
            if self.source_commit is None or self.source_blob_oid is None:
                raise FingerprintError(
                    "a v2 fingerprint requires source_commit and source_blob_oid as provenance"
                )
            if not self.working_tree_clean_verified:
                raise FingerprintError(
                    "a v2 fingerprint must not be issued for a dirty or unverified working tree"
                )

    @property
    def legacy_parameter_hash(self) -> str:
        """The 16-character field historical artefacts called ``parameter_hash``."""
        return self.source_fingerprint[:LEGACY_TRUNCATION]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint_scheme": self.fingerprint_scheme,
            "source_fingerprint": self.source_fingerprint,
            "parameter_hash": self.legacy_parameter_hash,
            "source_relpath": self.source_relpath,
            "source_commit": self.source_commit,
            "source_blob_oid": self.source_blob_oid,
            "working_tree_clean_verified": self.working_tree_clean_verified,
            "bytes_hashed": self.bytes_hashed,
            "algorithm": self.algorithm,
        }


def compute_source_fingerprint(
    repo_root: Path,
    relpath: str,
    *,
    commit: str = "HEAD",
    require_clean: bool = True,
) -> SourceFingerprint:
    """Fingerprint ``relpath`` from its committed blob, refusing anything else.

    Fail-closed conditions, each with its own error:

    * the file is not committed at ``commit`` → :class:`SourceNotCommittedError`;
    * the working tree path deviates from that commit (staged, unstaged or
      untracked) → :class:`WorkingTreeDirtyError`;
    * Git cannot answer → :class:`GitUnavailableError`.

    A checkout whose physical bytes differ but which Git itself maps back to the
    same blob (CRLF under ``core.autocrlf=true``) is accepted: that is the one
    tolerated transformation, and it is tolerated because Git proves the content
    equivalent through its own filters, not because this module guesses it.
    """
    posix = relpath.replace("\\", "/").lstrip("./")
    root = repo_root.resolve()
    blob = git_blob_bytes(root, commit, posix)
    oid = git_blob_oid(root, commit, posix)

    changes = working_tree_deviations(root, commit, posix, oid) if require_clean else []
    if changes:
        raise WorkingTreeDirtyError(f"{posix} deviates from {commit}: " + "; ".join(changes))

    return SourceFingerprint(
        fingerprint_scheme=FINGERPRINT_SCHEME_V2,
        source_fingerprint=hashlib.sha256(blob).hexdigest(),
        source_relpath=posix,
        source_commit=commit,
        source_blob_oid=oid,
        working_tree_clean_verified=require_clean,
        bytes_hashed=len(blob),
        algorithm="sha256(git_cat_file_blob:<commit>:<relpath>)",
    )


def verify_fingerprint(
    declared: SourceFingerprint,
    repo_root: Path,
    *,
    commit: str | None = None,
) -> SourceFingerprint:
    """Recompute ``declared`` from the repository and require the same identity."""
    if declared.fingerprint_scheme == FINGERPRINT_SCHEME_V1:
        raise IncompatibleFingerprintScheme(
            f"{declared.source_relpath}: v1 fingerprints are a checkout artefact and cannot be "
            "re-derived canonically; re-derive with v2 instead"
        )
    recomputed = compute_source_fingerprint(
        repo_root,
        declared.source_relpath,
        commit=commit or declared.source_commit or "HEAD",
    )
    assert_comparable(declared, recomputed)
    if declared.source_fingerprint != recomputed.source_fingerprint:
        raise FingerprintError(
            f"{declared.source_relpath}: declared {declared.source_fingerprint} but the blob at "
            f"{recomputed.source_commit} hashes to {recomputed.source_fingerprint}"
        )
    return recomputed


def read_fingerprint(payload: dict[str, Any], *, relpath: str | None = None) -> SourceFingerprint:
    """Read a fingerprint from a published row, honouring the scheme it declares.

    A row without ``fingerprint_scheme`` predates ``v2``; it is read as ``v1`` and
    left exactly as it is. Reading never rewrites the source artefact.
    """
    scheme = str(payload.get("fingerprint_scheme") or FINGERPRINT_SCHEME_V1)
    digest = payload.get("source_fingerprint") or payload.get("parameter_hash")
    if not isinstance(digest, str) or not digest:
        raise FingerprintError(f"no fingerprint in payload for {relpath or '<unknown>'}")
    if scheme == FINGERPRINT_SCHEME_V1:
        return SourceFingerprint(
            fingerprint_scheme=FINGERPRINT_SCHEME_V1,
            source_fingerprint=digest,
            source_relpath=str(payload.get("source_relpath") or relpath or ""),
            source_commit=payload.get("source_commit"),
            source_blob_oid=None,
            working_tree_clean_verified=False,
            bytes_hashed=0,
            algorithm="sha256(working_tree_bytes) [historical]",
        )
    if scheme != FINGERPRINT_SCHEME_V2:
        raise IncompatibleFingerprintScheme(f"unknown fingerprint scheme {scheme!r}")
    return SourceFingerprint(
        fingerprint_scheme=FINGERPRINT_SCHEME_V2,
        source_fingerprint=digest,
        source_relpath=str(payload.get("source_relpath") or relpath or ""),
        source_commit=payload.get("source_commit"),
        source_blob_oid=payload.get("source_blob_oid"),
        working_tree_clean_verified=bool(payload.get("working_tree_clean_verified")),
        bytes_hashed=int(payload.get("bytes_hashed") or 0),
        algorithm=str(payload.get("algorithm") or "sha256(git_cat_file_blob)"),
    )


def assert_comparable(left: SourceFingerprint, right: SourceFingerprint) -> None:
    """Refuse to compare identities produced by different schemes."""
    if left.fingerprint_scheme != right.fingerprint_scheme:
        raise IncompatibleFingerprintScheme(
            f"{left.source_relpath or '<left>'} is {left.fingerprint_scheme} but "
            f"{right.source_relpath or '<right>'} is {right.fingerprint_scheme}: a checkout byte "
            "digest and a blob digest are different identities, not two values of one"
        )
