"""V3 fail-closed import authority for checkout-isolated ARC-02 runs.

Contract (work order §8):

    FIRST_PARTY_IMPORT_ROOT == AUDITED_WORKTREE/src

for plain python, pytest, subprocess, PIT verifier, data verifier, portable
verifier and clean-worktree validation. Every first-party module used by ARC-02
must resolve inside ``<target_worktree>/src``; anything else FAILS CLOSED.

V3 mechanism-level repairs over V2 (see ARC02_V3_IMPORT_ROOT_CAUSE.md):

* RC-1  path identity is canonical: ``Path.resolve()`` + forward-slash text only
        for *reporting*; containment always via ``pathlib.is_relative_to``.
* RC-2  a wrong first-party module already present in ``sys.modules`` is an
        error (fail closed). V2 silently purged-and-replaced it; V3 never
        replaces already-imported wrong first-party modules.
* RC-3  all *resolvable* first-party contaminant entries are removed from
        ``sys.path`` (authority by absence, not by ordering). Entries that do
        not exist on disk are kept in place - CPython imports nothing from
        them, but independent auditors can still see the ambient environment.
* RC-4  (see conftest) pytest authority is established at session start and
        re-verified during collection; evidence-producing tests cannot run on
        wrong first-party sources.
* RC-5  authoritative subprocesses receive explicit ``target_root`` and
        ``expected_commit`` (see bootstrap + env contract).

Third-party dependencies remain available. A wrong checkout is an error, never
a fallback.
"""
from __future__ import annotations

import importlib
import os
import site
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable

#: First-party import roots that are not the target (kept for reporting).
_AMBIENT_FIRST_PARTY: tuple[str, ...] = tuple()


class FrozenInstanceError(AttributeError):
    """Raised when a frozen authority class is mutated."""


class ImportAuthorityError(RuntimeError):
    """Raised when first-party imports cannot be proven checkout-authoritative."""


def canonical(path: str | Path) -> Path:
    """Resolve a path without ever touching the filesystem cwd (RC-1)."""
    return Path(path).resolve()


def norm(path: str | Path) -> str:
    """Canonical *text* form for reports: resolved + forward slashes (RC-1)."""
    return str(Path(path).resolve()).replace("\\", "/")


def within(path: str | Path, root: str | Path) -> bool:
    """Separator-aware containment test. Never uses string prefixes (RC-1)."""
    p = Path(path).resolve()
    r = Path(root).resolve()
    if p == r:
        return False  # a file is never its own container root
    try:
        p.relative_to(r)
        return True
    except ValueError:
        return False


class ImportAuthorityEvidence:
    """Immutable authority evidence with canonical path text (RC-1)."""

    __slots__ = (
        "_target_root",
        "_expected_commit",
        "_git_head",
        "_python_executable",
        "_cwd",
        "_sys_path",
        "_sys_path_removed",
        "_site_paths",
        "_package_file",
        "_critical_module_files",
        "_purged_ambient_first_party",
    )

    def __init__(
        self,
        *,
        target_root: str,
        expected_commit: str,
        git_head: str,
        python_executable: str,
        cwd: str,
        sys_path: tuple[str, ...],
        sys_path_removed: tuple[str, ...],
        site_paths: tuple[str, ...],
        package_file: str,
        critical_module_files: tuple[str, ...],
        purged_ambient_first_party: tuple[str, ...],
    ) -> None:
        object.__setattr__(self, "_target_root", target_root)
        object.__setattr__(self, "_expected_commit", expected_commit)
        object.__setattr__(self, "_git_head", git_head)
        object.__setattr__(self, "_python_executable", python_executable)
        object.__setattr__(self, "_cwd", cwd)
        object.__setattr__(self, "_sys_path", sys_path)
        object.__setattr__(self, "_sys_path_removed", sys_path_removed)
        object.__setattr__(self, "_site_paths", site_paths)
        object.__setattr__(self, "_package_file", package_file)
        object.__setattr__(self, "_critical_module_files", critical_module_files)
        object.__setattr__(self, "_purged_ambient_first_party", purged_ambient_first_party)

    def __setattr__(self, name: str, value: object) -> None:
        raise FrozenInstanceError(
            f"cannot set attribute {name!r} on frozen authority class {self.__class__.__name__!r}"
        )

    def __delattr__(self, name: str) -> None:
        raise FrozenInstanceError(
            f"cannot delete attribute {name!r} on frozen authority class {self.__class__.__name__!r}"
        )

    @property
    def target_root(self) -> str:
        return self._target_root

    @property
    def expected_commit(self) -> str:
        return self._expected_commit

    @property
    def git_head(self) -> str:
        return self._git_head

    @property
    def python_executable(self) -> str:
        return self._python_executable

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def sys_path(self) -> tuple[str, ...]:
        return self._sys_path

    @property
    def sys_path_removed(self) -> tuple[str, ...]:
        return self._sys_path_removed

    @property
    def site_paths(self) -> tuple[str, ...]:
        return self._site_paths

    @property
    def package_file(self) -> str:
        return self._package_file

    @property
    def critical_module_files(self) -> tuple[str, ...]:
        return self._critical_module_files

    @property
    def purged_ambient_first_party(self) -> tuple[str, ...]:
        return self._purged_ambient_first_party

    def to_dict(self) -> dict[str, object]:
        return {
            "target_root": self.target_root,
            "expected_commit": self.expected_commit,
            "git_head": self.git_head,
            "python_executable": self.python_executable,
            "cwd": self.cwd,
            "sys_path": list(self.sys_path),
            "sys_path_removed": list(self.sys_path_removed),
            "site_paths": list(self.site_paths),
            "package_file": self.package_file,
            "critical_module_files": list(self.critical_module_files),
            "purged_ambient_first_party": list(self.purged_ambient_first_party),
            "package_within_target": within(self.package_file, self.target_root + "/src"),
            "critical_all_within_target": all(
                within(p, self.target_root + "/src") for p in self.critical_module_files
            ),
        }


class CheckoutImportAuthority:
    """Prove that a package and critical modules come from one target checkout."""

    __slots__ = (
        "_target_root",
        "_expected_commit",
        "_package_name",
        "_critical_modules",
    )

    def __init__(
        self,
        *,
        target_root: Path,
        expected_commit: str,
        package_name: str = "trading_bot",
        critical_modules: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "_target_root", Path(target_root).resolve())
        object.__setattr__(self, "_expected_commit", expected_commit)
        object.__setattr__(self, "_package_name", package_name)
        object.__setattr__(self, "_critical_modules", tuple(critical_modules))
        if not expected_commit:
            raise ValueError("expected_commit is required")
        if not package_name:
            raise ValueError("package_name is required")

    def __setattr__(self, name: str, value: object) -> None:
        raise FrozenInstanceError(
            f"cannot set attribute {name!r} on frozen authority class {self.__class__.__name__!r}"
        )

    def __delattr__(self, name: str) -> None:
        raise FrozenInstanceError(
            f"cannot delete attribute {name!r} on frozen authority class {self.__class__.__name__!r}"
        )

    @property
    def target_root(self) -> Path:
        return object.__getattribute__(self, "_target_root")

    @property
    def expected_commit(self) -> str:
        return object.__getattribute__(self, "_expected_commit")

    @property
    def package_name(self) -> str:
        return object.__getattribute__(self, "_package_name")

    @property
    def critical_modules(self) -> tuple[str, ...]:
        return object.__getattribute__(self, "_critical_modules")

    @property
    def source_root(self) -> Path:
        return self.target_root / "src"

    # ------------------------------------------------------------------ RC-2
    def _audit_preloaded_first_party(self) -> None:
        """Wrong preloaded first-party modules FAIL CLOSED; never replaced."""
        prefix = self.package_name + "."
        offenders: list[str] = []
        for name, module in list(sys.modules.items()):
            if name != self.package_name and not name.startswith(prefix):
                continue
            # the authority contract module itself is exempt (it is loaded by
            # file location and lives inside the target src anyway)
            if name.startswith("_arc02") or name.startswith("_pytest_checkout"):
                continue
            file = getattr(module, "__file__", None)
            if file is None:
                # namespace fragment or partially-initialized package: if it is
                # not importable from the target it must not stay bound
                offenders.append(name)
                continue
            if not within(file, self.source_root):
                offenders.append(name)
        if offenders:
            sample = ", ".join(offenders[:5])
            raise ImportAuthorityError(
                "PRELOADED_WRONG_FIRST_PARTY_MODULE: "
                f"{len(offenders)} module(s) of package {self.package_name!r} were "
                f"already imported from outside {self.source_root} "
                f"(e.g. {sample}). Fail-closed per contract: wrong first-party "
                "imports are an error, never silently replaced. Restart the "
                "process and run the authority bootstrap before importing "
                f"{self.package_name!r}."
            )

    # ------------------------------------------------------------------ RC-3
    def _purge_ambient_first_party_from_sys_path(self) -> tuple[str, ...]:
        """Remove every resolvable sys.path entry that carries the first-party
        package but is NOT the target src. Nonexistent entries are kept (they
        resolve to nothing) so ambient evidence stays visible to auditors."""
        removed: list[str] = []
        kept: list[str] = []
        target_text = norm(self.source_root)
        for entry in list(sys.path):
            try:
                p = Path(entry).resolve() if entry else Path.cwd()
            except OSError:
                kept.append(entry)
                continue
            if not p.is_dir():
                kept.append(entry)  # nonexistent: cannot serve imports
                continue
            if not (p / self.package_name / "__init__.py").is_file():
                kept.append(entry)  # does not carry the first-party package
                continue
            if norm(p) == target_text:
                kept.append(entry)  # the target itself
                continue
            removed.append(str(p))
        sys.path[:] = kept
        return tuple(removed)

    def prepare(self) -> tuple[str, ...]:
        """Establish authority: RC-2 audit, RC-3 purge, then insert target src.

        Returns the removed (contaminant) entries. The target src is inserted at
        position 0 AFTER the purge so the audited source is the only resolvable
        first-party import root (authority by absence + explicit establishment).
        """
        if not self.source_root.is_dir():
            raise ImportAuthorityError(f"missing target source root: {self.source_root}")
        self._audit_preloaded_first_party()
        removed = self._purge_ambient_first_party_from_sys_path()
        source = str(self.source_root)
        if source in sys.path:
            sys.path.remove(source)
        sys.path.insert(0, source)
        return removed

    def verify_commit_identity(self) -> str:
        """Prove the target checkout is at the expected commit (fail closed)."""
        head = _git_head(self.target_root)
        if head != self.expected_commit:
            raise ImportAuthorityError(
                f"git HEAD mismatch: expected {self.expected_commit}, observed {head}"
            )
        return head

    def evidence(self) -> ImportAuthorityEvidence:
        removed = self.prepare()
        head = self.verify_commit_identity()
        package = importlib.import_module(self.package_name)
        package_file = _module_file(package, self.package_name)
        modules: list[str] = []
        for name in self.critical_modules:
            module = importlib.import_module(name)
            modules.append(_module_file(module, name))
        if not within(package_file, self.source_root):
            raise ImportAuthorityError(f"package outside target source: {package_file}")
        if any(not within(p, self.source_root) for p in modules):
            raise ImportAuthorityError("critical module outside target source")
        return ImportAuthorityEvidence(
            target_root=norm(self.target_root),
            expected_commit=self.expected_commit,
            git_head=head,
            python_executable=norm(Path(sys.executable)),
            cwd=norm(Path.cwd()),
            sys_path=tuple(norm(p) if str(p).strip() else p for p in sys.path),
            sys_path_removed=tuple(removed),
            site_paths=tuple(norm(p) for p in site.getsitepackages() + [site.getusersitepackages()]),
            package_file=package_file,
            critical_module_files=tuple(modules),
            purged_ambient_first_party=tuple(norm(p) for p in removed),
        )

    def assert_authority(self) -> ImportAuthorityEvidence:
        return self.evidence()

    # ------------------------------------------------- post-hoc session check
    def verify_loaded_state(self) -> dict[str, object]:
        """Re-check every loaded first-party module still resolves in-target.

        Used by the pytest guard during collection (RC-4). Raises
        ImportAuthorityError on any drift. Returns a small summary dict.
        """
        checked = 0
        prefix = self.package_name + "."
        for name, module in list(sys.modules.items()):
            if name != self.package_name and not name.startswith(prefix):
                continue
            if name.startswith("_arc02") or name.startswith("_pytest_checkout"):
                continue
            file = getattr(module, "__file__", None)
            if file is None:
                continue  # namespace package without a file is not evidence
            if not within(file, self.source_root):
                raise ImportAuthorityError(
                    f"SESSION DRIFT: loaded module {name!r} resolved outside the "
                    f"target source: {file}"
                )
            checked += 1
        return {"modules_checked": checked, "target_root": norm(self.target_root)}


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ImportAuthorityError(f"cannot determine git HEAD for {root}: {exc}") from exc


def _module_file(module: ModuleType, name: str) -> str:
    path = getattr(module, "__file__", None)
    if not path:
        raise ImportAuthorityError(f"module has no file authority: {name}")
    return norm(Path(path))


def _iter_py_files(root: Path) -> Iterable[Path]:
    return root.rglob("*.py")


__all__ = [
    "CheckoutImportAuthority",
    "ImportAuthorityError",
    "ImportAuthorityEvidence",
    "canonical",
    "norm",
    "within",
]


# --------------------------------------------------------------------- RC-5
#: Environment variables that carry explicit authority into subprocesses.
ENV_TARGET_ROOT = "ARC02_TARGET_ROOT"
ENV_EXPECTED_COMMIT = "ARC02_EXPECTED_COMMIT"


def subprocess_authority_env(
    *, target_root: Path, expected_commit: str, base: dict[str, str] | None = None
) -> dict[str, str]:
    """Return an env dict that pins a child process to this authority contract.

    Per §13, authoritative subprocesses must receive explicit target_root,
    target src and expected commit; they must never rely on inherited ambient
    state. The child must call ``bootstrap_arc02()`` (scripts/arc02_import_bootstrap.py)
    *before* importing the first-party package.
    """
    env = dict(base if base is not None else os.environ)
    env[ENV_TARGET_ROOT] = str(Path(target_root).resolve())
    env[ENV_EXPECTED_COMMIT] = expected_commit
    # Contaminated parents are allowed; the child's bootstrap establishes and
    # proves authority. PYTHONPATH is intentionally NOT cleaned here so that
    # the child is exercised under the same attack it must defend against.
    return env


__all__ += ["ENV_TARGET_ROOT", "ENV_EXPECTED_COMMIT", "subprocess_authority_env"]
