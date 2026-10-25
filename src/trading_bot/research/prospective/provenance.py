"""Which declaration authorised a capture, which code ran it, and when it became binding.

``config/preregistrations/EXP-004A.datasets.json`` is phase 1 of the two-phase freeze and it will
never be edited: its ``generator_code_commit`` is the zero SHA because the code did not exist when it
was committed, and rewriting that field now would be the retroactive correction RFC-050 forbids. The
consequence is a declaration that cannot identify the code its own captures will run.

This module is the successor declaration's contract, and nothing else:

* **supersession by reference** — a successor names the original by path and by the SHA-256 of its
  bytes. The original is never opened for writing, and :func:`validate` refuses a successor whose
  recorded digest no longer matches the file it claims to succeed (ACC-01).
* **a full commit, not a prefix** — ``daa7bde`` is a convenience for humans; a seven-character prefix
  is not an identifier and is rejected (ACC-03). The commit must resolve, and the blob at that commit
  must hash to the same bytes as the extractor on disk (ACC-04).
* **time with an ordering, not a date** — three instants are kept apart: when the document was
  issued, when it became effective, and when the capture window opens. Eligibility is decided
  against the *bar's own* ``fetched_at_ms``, which is written into the store at ingest time and is not
  part of the declaration anyone could edit afterwards. A capture whose bars were fetched before the
  declaration became effective is ``NOT_ELIGIBLE``, never "probably fine" (ACC-05, ACC-06).

What this module deliberately does **not** claim is external notarisation. The strongest chronology
available in this repository is Git: the declaration's own commit must be an ancestor of ``HEAD`` and
must precede the window it governs. That is repository-verifiable and it survives any later edit as a
hash change, but it is not a trusted timestamp, so every record this module emits says so instead of
borrowing authority it does not have. C-013 stays ``TIME_PROOF_WEAK``.

Read-only with respect to market data, the original declaration and every sealed artefact. It shells
out to ``git`` for read-only plumbing only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "3.0"
GENERATOR_PATH = "scripts/exp004a_capture.py"
ORIGINAL_DECLARATION = "config/preregistrations/EXP-004A.datasets.json"
SUCCESSOR_DECLARATION = "config/preregistrations/EXP-004A.datasets.phase2.json"
GOVERNANCE_STATUS = "AUTHORIZED_FOR_CAPTURE"

#: Fields of the successor document itself. The dataset entries keep the phase-1 schema exactly, so
#: the prereg gate can read this file as a registry without learning a second dialect.
REQUIRED_FIELDS = (
    "declaration_id",
    "experiment_id",
    "phase",
    "schema_version",
    "supersedes",
    "generator",
    "capture_window",
    "effective_from_utc",
    "issued_at_utc",
    "governance_status",
    "entries",
)
SUPERSEDES_FIELDS = ("path", "sha256", "git_blob", "declared_generator_code_commit")
GENERATOR_FIELDS = ("path", "commit", "blob_sha256", "contract")
WINDOW_FIELDS = ("start_utc", "end_utc")
#: The one field a successor may change in an entry. Everything else — asset, venue, window, source,
#: lag bound, coverage, declared row count — is what the freeze fixed, and drift there is refused by
#: name rather than by a generic "differs".
MUTABLE_ENTRY_FIELD = "generator_code_commit"


class DeclarationError(RuntimeError):
    """The declaration cannot authorise a capture. Carries every defect, not just the first."""

    def __init__(self, defects: Sequence[Defect], *, eligibility: bool = False) -> None:
        self.defects = tuple(defects)
        self.eligibility = eligibility
        codes = ", ".join(defect.code for defect in self.defects) or "UNKNOWN"
        super().__init__(f"declaration refused: {codes}")

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(defect.code for defect in self.defects)


@dataclass(frozen=True, slots=True)
class Defect:
    """One failed control, in a shape that can be written into a report unchanged."""

    code: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc(value: Any, field_name: str) -> datetime:
    """A governance instant must say ``Z``. A naive string is not a time, it is a wish."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} requires an explicit UTC Z timestamp")
    try:
        moment = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field_name} is not ISO-8601: {value!r}") from error
    if moment.utcoffset() != UTC.utcoffset(moment):
        raise ValueError(f"{field_name} must be UTC")
    return moment


def to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ms_from_iso(value: Any, field_name: str) -> int:
    return to_ms(parse_utc(value, field_name))


def git(repo: Path, *args: str) -> tuple[bool, bytes]:
    """Run one read-only git command. Bytes, because a blob hash is over bytes."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        timeout=120,
    )
    return completed.returncode == 0, completed.stdout if completed.returncode == 0 else completed.stderr


def resolve_commit(repo: Path, ref: str) -> str | None:
    ok, output = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return output.decode("ascii").strip() if ok else None


def commit_epoch(repo: Path, ref: str) -> int | None:
    ok, output = git(repo, "log", "-1", "--format=%ct", ref)
    if not ok:
        return None
    text = output.decode("ascii").strip()
    return int(text) if text.isdigit() else None


def file_bytes_at(repo: Path, commit: str, path: str) -> bytes | None:
    ok, output = git(repo, "cat-file", "blob", f"{commit}:{path}")
    return output if ok else None


def last_commit_for_path(repo: Path, path: str) -> str | None:
    ok, output = git(repo, "log", "-1", "--format=%H", "--", path)
    if not ok:
        return None
    text = output.decode("ascii").strip()
    return text or None


def is_ancestor(repo: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    ok, _ = git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return ok


def path_is_dirty(repo: Path, path: str) -> bool:
    """True when the working tree differs from ``HEAD`` *at that path*."""
    ok, output = git(repo, "status", "--porcelain", "--", path)
    return bool(ok and output.decode("utf-8", "replace").strip())


def worktree_blob_id(repo: Path, path: str) -> str | None:
    """The object id Git would store for the file on disk, end-of-line policy applied.

    Comparing bytes directly would call a CRLF checkout of an LF blob a modification. What has to
    match is the file Git would commit, and that is exactly what ``hash-object`` answers.
    """
    ok, output = git(repo, "hash-object", "--", path)
    return output.decode("ascii").strip() if ok else None


def committed_blob_id(repo: Path, commit: str, path: str) -> str | None:
    ok, output = git(repo, "rev-parse", f"{commit}:{path}")
    return output.decode("ascii").strip() if ok else None


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Declaration:
    """A successor declaration, parsed but not yet trusted. :func:`validate` decides trust."""

    path: Path
    document: Mapping[str, Any]

    @property
    def declaration_id(self) -> str:
        return str(self.document.get("declaration_id") or "")

    @property
    def experiment_id(self) -> str:
        return str(self.document.get("experiment_id") or "")

    @property
    def phase(self) -> Any:
        return self.document.get("phase")

    @property
    def schema_version(self) -> str:
        return str(self.document.get("schema_version") or "")

    @property
    def governance_status(self) -> str:
        return str(self.document.get("governance_status") or "")

    @property
    def supersedes(self) -> Mapping[str, Any]:
        raw = self.document.get("supersedes")
        return raw if isinstance(raw, Mapping) else {}

    @property
    def generator(self) -> Mapping[str, Any]:
        raw = self.document.get("generator")
        return raw if isinstance(raw, Mapping) else {}

    @property
    def window(self) -> Mapping[str, Any]:
        raw = self.document.get("capture_window")
        return raw if isinstance(raw, Mapping) else {}

    @property
    def entries(self) -> list[Mapping[str, Any]]:
        raw = self.document.get("entries")
        return [row for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []

    @property
    def generator_path(self) -> str:
        return str(self.generator.get("path") or "")

    @property
    def generator_commit(self) -> str:
        return str(self.generator.get("commit") or "")

    @property
    def effective_from_ms(self) -> int:
        return _ms_from_iso(self.document.get("effective_from_utc"), "effective_from_utc")

    @property
    def issued_at_ms(self) -> int:
        return _ms_from_iso(self.document.get("issued_at_utc"), "issued_at_utc")

    @property
    def window_start_ms(self) -> int:
        return _ms_from_iso(self.window.get("start_utc"), "capture_window.start_utc")

    @property
    def window_end_ms(self) -> int:
        return _ms_from_iso(self.window.get("end_utc"), "capture_window.end_utc")

    def entry(self, dataset_id: str) -> Mapping[str, Any] | None:
        for row in self.entries:
            if row.get("dataset_id") == dataset_id:
                return row
        return None


def load(path: Path) -> Declaration:
    """Read a declaration from disk. Absence is a block, not an empty default."""
    if not Path(path).is_file():
        raise DeclarationError([Defect("DECLARATION_MISSING", f"{path} does not exist")])
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeclarationError([Defect("DECLARATION_UNREADABLE", f"{path}: {error}")]) from error
    if not isinstance(document, dict):
        raise DeclarationError([Defect("DECLARATION_UNREADABLE", f"{path} holds no object")])
    return Declaration(path=Path(path), document=document)


def _require(mapping: Mapping[str, Any], fields: Iterable[str], prefix: str, defects: list[Defect]) -> None:
    for name in fields:
        value = mapping.get(name)
        if value is None or value == "":
            defects.append(Defect(f"{prefix}.{name}.MISSING", f"{prefix}.{name} is absent"))


def validate(
    declaration: Declaration,
    *,
    repo: Path,
    original_path: Path | None = None,
    generator_path: Path | None = None,
    verify_git: bool = True,
) -> list[Defect]:
    """Every control that must pass before a slice may be produced. Empty list means eligible.

    ``verify_git=False`` exists for schema rehearsal against fixtures that are not a repository. It
    never skips a check that a committed run depends on: the generator hash, the supersession digest
    and the temporal ordering are all still computed from bytes.
    """
    repo = Path(repo)
    original_path = original_path or repo / ORIGINAL_DECLARATION
    generator_path = generator_path or repo / GENERATOR_PATH
    defects: list[Defect] = []

    _require(declaration.document, REQUIRED_FIELDS, "declaration", defects)
    _require(declaration.supersedes, SUPERSEDES_FIELDS, "supersedes", defects)
    _require(declaration.generator, GENERATOR_FIELDS, "generator", defects)
    _require(declaration.window, WINDOW_FIELDS, "capture_window", defects)
    if defects:
        return defects

    if declaration.schema_version != SCHEMA_VERSION:
        defects.append(
            Defect(
                "DECLARATION_SCHEMA_MISMATCH",
                f"schema_version {declaration.schema_version!r} != {SCHEMA_VERSION!r}",
            )
        )
    if declaration.phase != 2:
        defects.append(Defect("DECLARATION_PHASE_NOT_2", f"phase {declaration.phase!r}"))
    if declaration.experiment_id != "EXP-004A":
        defects.append(Defect("DECLARATION_EXPERIMENT_MISMATCH", declaration.experiment_id))
    if declaration.governance_status != GOVERNANCE_STATUS:
        defects.append(
            Defect("DECLARATION_NOT_AUTHORIZED", f"governance_status {declaration.governance_status!r}")
        )
    if Path(str(declaration.supersedes.get("path"))).as_posix() == declaration.path.as_posix():
        defects.append(Defect("DECLARATION_SELF_SUPERSEDES", "a successor cannot succeed itself"))

    # --- ACC-01: the original keeps its bytes --------------------------------- #
    if not original_path.is_file():
        defects.append(Defect("ORIGINAL_DECLARATION_MISSING", str(original_path)))
        original: Mapping[str, Any] = {}
    else:
        actual = sha256_file(original_path)
        declared = str(declaration.supersedes.get("sha256") or "")
        blob = str(declaration.supersedes.get("git_blob") or "")
        if verify_git:
            last = last_commit_for_path(repo, _relative(repo, original_path))
            committed = file_bytes_at(repo, last, _relative(repo, original_path)) if last else None
            if committed is None:
                defects.append(Defect("ORIGINAL_DECLARATION_NOT_COMMITTED", str(original_path)))
            else:
                if actual != declared and sha256_bytes(committed) != declared:
                    defects.append(
                        Defect(
                            "ORIGINAL_DECLARATION_SHA256_MISMATCH",
                            f"{original_path.name} is {actual}, the successor cites {declared}",
                        )
                    )
                if _git_blob_id(committed) != blob:
                    defects.append(
                        Defect(
                            "ORIGINAL_DECLARATION_BLOB_MISMATCH",
                            "the committed blob is not the file this checkout holds",
                        )
                    )
                if path_is_dirty(repo, _relative(repo, original_path)):
                    defects.append(
                        Defect(
                            "ORIGINAL_DECLARATION_MODIFIED_IN_WORKTREE",
                            f"{original_path.name} has uncommitted changes; its hash no longer "
                            "describes what was frozen",
                        )
                    )
        elif actual != declared:
            defects.append(
                Defect(
                    "ORIGINAL_DECLARATION_SHA256_MISMATCH",
                    f"{original_path.name} is {actual}, the successor cites {declared}",
                )
            )
        try:
            original = json.loads(original_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            original = {}

    # --- ACC-03/04: the generator is a commit and its bytes -------------------- #
    commit = declaration.generator_commit
    if not commit or set(commit) == {"0"}:
        defects.append(Defect("GENERATOR_COMMIT_ZERO", "the zero SHA identifies no code"))
    elif len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        defects.append(
            Defect(
                "GENERATOR_COMMIT_NOT_FULL_SHA",
                f"{commit!r} is not a 40-character lowercase SHA; a prefix is not an identifier",
            )
        )
    elif verify_git:
        resolved = resolve_commit(repo, commit)
        if resolved is None:
            defects.append(Defect("GENERATOR_COMMIT_UNKNOWN", f"{commit} is not in this repository"))
        elif resolved != commit:
            defects.append(Defect("GENERATOR_COMMIT_UNKNOWN", f"{commit} resolves to {resolved}"))
        else:
            rel = _relative(repo, generator_path)
            at_commit = file_bytes_at(repo, commit, rel)
            if at_commit is None:
                defects.append(Defect("GENERATOR_ABSENT_AT_COMMIT", f"{rel} is not in {commit}"))
            elif sha256_bytes(at_commit) != str(declaration.generator.get("blob_sha256") or ""):
                defects.append(
                    Defect(
                        "GENERATOR_BLOB_MISMATCH",
                        f"{rel} at {commit} hashes to {sha256_bytes(at_commit)}",
                    )
                )
    if not generator_path.is_file():
        defects.append(Defect("GENERATOR_FILE_MISSING", str(generator_path)))
    elif verify_git:
        rel = _relative(repo, generator_path)
        would_run = worktree_blob_id(repo, rel)
        declared_blob = committed_blob_id(repo, commit, rel) if commit and len(commit) == 40 else None
        if would_run is None:
            defects.append(Defect("GENERATOR_WORKTREE_UNREADABLE", rel))
        elif declared_blob is not None and would_run != declared_blob:
            defects.append(
                Defect(
                    "GENERATOR_FILE_DIFFERS_FROM_DECLARED",
                    f"the file that would run is blob {would_run}; {commit} holds {declared_blob}",
                )
            )
        if path_is_dirty(repo, rel):
            defects.append(
                Defect(
                    "GENERATOR_WORKTREE_DIRTY",
                    f"{rel} has uncommitted changes; the declared commit is not what would run",
                )
            )
    else:
        on_disk = sha256_file(generator_path)
        if on_disk != str(declaration.generator.get("blob_sha256") or ""):
            defects.append(
                Defect(
                    "GENERATOR_FILE_DIFFERS_FROM_DECLARED",
                    f"the file that would run hashes to {on_disk}, the declaration names "
                    f"{declaration.generator.get('blob_sha256')}",
                )
            )
    if str(declaration.generator.get("path")) != _relative(repo, generator_path):
        defects.append(Defect("GENERATOR_PATH_MISMATCH", str(declaration.generator.get("path"))))

    # --- ACC-05/06: the ordering that makes a capture prospective -------------- #
    try:
        issued = declaration.issued_at_ms
        effective = declaration.effective_from_ms
        start = declaration.window_start_ms
        end = declaration.window_end_ms
    except ValueError as error:
        defects.append(Defect("DECLARATION_TIME_UNREADABLE", str(error)))
    else:
        if end <= start:
            defects.append(Defect("DECLARATION_WINDOW_EMPTY", "the window ends before it starts"))
        if issued > effective:
            defects.append(
                Defect("TEMPORAL_ISSUED_AFTER_EFFECTIVE", "issue cannot follow effect")
            )
        if effective > start:
            defects.append(
                Defect(
                    "TEMPORAL_EFFECTIVE_AFTER_WINDOW_START",
                    f"effective {to_iso(_from_ms(effective))} is after the window opens "
                    f"{to_iso(_from_ms(start))}; capture would begin unauthorised",
                )
            )

    # --- ACC-02: the successor is itself versioned ---------------------------- #
    if verify_git:
        rel = _relative(repo, declaration.path)
        declaration_commit = last_commit_for_path(repo, rel)
        if declaration_commit is None:
            defects.append(
                Defect(
                    "DECLARATION_NOT_COMMITTED",
                    f"{rel} is not in Git; an authored timestamp alone proves nothing",
                )
            )
        else:
            if path_is_dirty(repo, rel):
                defects.append(
                    Defect(
                        "DECLARATION_WORKTREE_DIRTY",
                        f"{rel} differs from its last commit {declaration_commit}",
                    )
                )
            stamp = commit_epoch(repo, declaration_commit)
            if stamp is None:
                defects.append(Defect("DECLARATION_COMMIT_TIME_UNKNOWN", declaration_commit))
            elif stamp * 1000 >= declaration.window_start_ms:
                defects.append(
                    Defect(
                        "DECLARATION_COMMITTED_AFTER_WINDOW_START",
                        f"commit {declaration_commit} is dated after the capture window opened",
                    )
                )
            if not is_ancestor(repo, declaration_commit):
                defects.append(
                    Defect("DECLARATION_COMMIT_NOT_ANCESTOR", f"{declaration_commit} is not behind HEAD")
                )

    # --- entries: only the commit may move ------------------------------------ #
    if not declaration.entries:
        defects.append(Defect("DECLARATION_NO_ENTRIES", "a declaration with no dataset is not one"))
    original_entries = {
        str(row.get("dataset_id")): row
        for row in (original.get("entries") or [])
        if isinstance(row, Mapping)
    }
    for entry in declaration.entries:
        name = str(entry.get("dataset_id") or "<unnamed>")
        if entry.get("generator_code_commit") != declaration.generator_commit:
            defects.append(
                Defect(
                    "ENTRY_GENERATOR_COMMIT_MISMATCH",
                    f"{name} cites {entry.get('generator_code_commit')!r}, the declaration "
                    f"cites {declaration.generator_commit!r}",
                )
            )
        counterpart = original_entries.get(name)
        if counterpart is None:
            defects.append(Defect("ENTRY_NOT_IN_ORIGINAL", name))
            continue
        for key in sorted(set(counterpart) | set(entry)):
            if key == MUTABLE_ENTRY_FIELD:
                continue
            if counterpart.get(key) != entry.get(key):
                defects.append(
                    Defect(
                        "ENTRY_DRIFT",
                        f"{name}.{key} changed from {counterpart.get(key)!r} to {entry.get(key)!r}",
                    )
                )
        if entry.get("slice_contract") is not None:
            defects.append(
                Defect(
                    "ENTRY_INVENTS_SLICE_CONTRACT",
                    f"{name} declares a slice contract the freeze never fixed",
                )
            )
    return defects


def _git_blob_id(payload: bytes) -> str:
    """The SHA-1 Git names a blob by. Used to bind to the committed object, not to a copy."""
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # Git's object id, not a signature


def _relative(repo: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, UTC)


# --------------------------------------------------------------------------- #
# eligibility: the bar's own clock decides
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """What every capture writes beside its bytes, so the chain can be rebuilt later."""

    declaration_id: str
    declaration_path: str
    declaration_sha256: str
    declaration_commit: str | None
    generator_path: str
    generator_commit: str
    generator_sha256: str
    supersedes_path: str
    supersedes_sha256: str
    effective_from_ms: int
    window_start_ms: int
    window_end_ms: int
    external_timestamp: str = "UNAVAILABLE"
    temporal_basis: str = "GIT_ANCESTRY_PLUS_INGEST_CLOCK"

    def as_dict(self) -> dict[str, Any]:
        return {
            "declaration_id": self.declaration_id,
            "declaration_path": self.declaration_path,
            "declaration_sha256": self.declaration_sha256,
            "declaration_commit": self.declaration_commit,
            "generator": {
                "path": self.generator_path,
                "commit": self.generator_commit,
                "sha256": self.generator_sha256,
            },
            "supersedes": {
                "path": self.supersedes_path,
                "sha256": self.supersedes_sha256,
            },
            "temporal": {
                "effective_from_utc": to_iso(_from_ms(self.effective_from_ms)),
                "capture_window": {
                    "start_utc": to_iso(_from_ms(self.window_start_ms)),
                    "end_utc": to_iso(_from_ms(self.window_end_ms)),
                },
                "basis": self.temporal_basis,
                "external_timestamp": self.external_timestamp,
                "reading": (
                    "eligible captures must open at or after the declared window and must have been "
                    "fetched at or after the declaration's effective instant; the declaration's "
                    "commit must be an ancestor of the capture's commit"
                ),
            },
        }


def authorize(
    path: Path | None = None,
    *,
    repo: Path | None = None,
    generator_path: Path | None = None,
) -> ProvenanceRecord:
    """Validate a successor declaration and return the record a capture embeds.

    Raises :class:`DeclarationError` with every defect found. There is no lenient mode: an
    unauthorised declaration is a block, not a warning (RFC §7).
    """
    repo = Path(repo) if repo is not None else _repo_root()
    path = Path(path) if path is not None else repo / SUCCESSOR_DECLARATION
    declaration = load(path)
    defects = validate(declaration, repo=repo, generator_path=generator_path)
    if defects:
        raise DeclarationError(defects)
    stamp = commit_epoch(repo, resolve_commit(repo, declaration.generator_commit) or "")
    if stamp is None:  # pragma: no cover - validate() has already resolved it
        raise DeclarationError([Defect("GENERATOR_COMMIT_UNKNOWN", declaration.generator_commit)])
    committed_generator = file_bytes_at(
        repo, declaration.generator_commit, declaration.generator_path
    )
    return ProvenanceRecord(
        declaration_id=declaration.declaration_id,
        declaration_path=_relative(repo, declaration.path),
        declaration_sha256=sha256_file(declaration.path),
        declaration_commit=last_commit_for_path(repo, _relative(repo, declaration.path)),
        generator_path=declaration.generator_path,
        generator_commit=declaration.generator_commit,
        generator_sha256=sha256_bytes(committed_generator or b""),
        supersedes_path=str(declaration.supersedes.get("path")),
        supersedes_sha256=str(declaration.supersedes.get("sha256")),
        effective_from_ms=declaration.effective_from_ms,
        window_start_ms=declaration.window_start_ms,
        window_end_ms=declaration.window_end_ms,
    )


def eligibility_defects(
    record: ProvenanceRecord, bars: Iterable[tuple[int, int]]
) -> list[Defect]:
    """``(open_ms, fetched_at_ms)`` per bar; a bar fetched before effect is not eligible.

    The extractor keeps late bars on purpose, so that *admission* can reject their day. This is a
    different question and it is decided first: was this bar collected under an authorised
    declaration at all?
    """
    before = 0
    outside = 0
    earliest_fetch: int | None = None
    for open_ms, fetched_ms in bars:
        if earliest_fetch is None or fetched_ms < earliest_fetch:
            earliest_fetch = fetched_ms
        if fetched_ms < record.effective_from_ms:
            before += 1
        if not record.window_start_ms <= open_ms < record.window_end_ms:
            outside += 1
    defects: list[Defect] = []
    if before:
        defects.append(
            Defect(
                "CAPTURE_BEFORE_EFFECTIVE",
                f"{before} bar(s) were fetched before "
                f"{to_iso(_from_ms(record.effective_from_ms))}; earliest fetch "
                f"{to_iso(_from_ms(earliest_fetch or 0))}",
            )
        )
    if outside:
        defects.append(
            Defect("CAPTURE_OUTSIDE_DECLARED_WINDOW", f"{outside} bar(s) open outside the window")
        )
    return defects


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
