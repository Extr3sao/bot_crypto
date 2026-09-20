"""Fail-closed import authority for checkout-isolated research runs.

Third-party dependencies remain available. Only first-party package resolution is
pinned to the explicitly audited checkout; a wrong checkout is an error, never a
fallback.

This module intentionally avoids runtime dataclass processing so it can be loaded
with importlib.util.exec_module under contaminated environments.
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


class FrozenInstanceError(AttributeError):
    """Raised when a frozen authority class is mutated."""


class ImportAuthorityError(RuntimeError):
    """Raised when first-party imports cannot be proven checkout-authoritative."""


class ImportAuthorityEvidence:
    """Immutable authority evidence with explicit field names."""

    __slots__ = (
        "_target_root",
        "_expected_commit",
        "_git_head",
        "_python_executable",
        "_cwd",
        "_sys_path",
        "_site_paths",
        "_package_file",
        "_critical_module_files",
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
        site_paths: tuple[str, ...],
        package_file: str,
        critical_module_files: tuple[str, ...],
    ) -> None:
        object.__setattr__(self, "_target_root", target_root)
        object.__setattr__(self, "_expected_commit", expected_commit)
        object.__setattr__(self, "_git_head", git_head)
        object.__setattr__(self, "_python_executable", python_executable)
        object.__setattr__(self, "_cwd", cwd)
        object.__setattr__(self, "_sys_path", sys_path)
        object.__setattr__(self, "_site_paths", site_paths)
        object.__setattr__(self, "_package_file", package_file)
        object.__setattr__(self, "_critical_module_files", critical_module_files)

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
    def site_paths(self) -> tuple[str, ...]:
        return self._site_paths

    @property
    def package_file(self) -> str:
        return self._package_file

    @property
    def critical_module_files(self) -> tuple[str, ...]:
        return self._critical_module_files

    def to_dict(self) -> dict[str, object]:
        return {
            "target_root": self.target_root,
            "expected_commit": self.expected_commit,
            "git_head": self.git_head,
            "python_executable": self.python_executable,
            "cwd": self.cwd,
            "sys_path": list(self.sys_path),
            "site_paths": list(self.site_paths),
            "package_file": self.package_file,
            "critical_module_files": list(self.critical_module_files),
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
        object.__setattr__(self, "_target_root", target_root)
        object.__setattr__(self, "_expected_commit", expected_commit)
        object.__setattr__(self, "_package_name", package_name)
        object.__setattr__(self, "_critical_modules", critical_modules)
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

    @property
    def source_root(self) -> Path:
        return self.target_root / "src"

    def prepare(self) -> None:
        """Make target src authoritative and purge already-loaded wrong modules."""
        if not self.source_root.is_dir():
            raise ImportAuthorityError(f"missing target source root: {self.source_root}")
        source = str(self.source_root)
        sys.path[:] = [p for p in sys.path if _resolved(p) != self.source_root]
        sys.path.insert(0, source)
        for name, module in list(sys.modules.items()):
            if name == self.package_name or name.startswith(self.package_name + "."):
                path = getattr(module, "__file__", None)
                if path is None or not _within(Path(path), self.source_root):
                    del sys.modules[name]

    def evidence(self) -> ImportAuthorityEvidence:
        self.prepare()
        head = _git_head(self.target_root)
        if head != self.expected_commit:
            raise ImportAuthorityError(
                f"git HEAD mismatch: expected {self.expected_commit}, observed {head}"
            )
        package = importlib.import_module(self.package_name)
        package_file = _module_file(package, self.package_name)
        modules: list[str] = []
        for name in self.critical_modules:
            module = importlib.import_module(name)
            modules.append(_module_file(module, name))
        paths = tuple(_normal_path(p) for p in sys.path)
        sites = tuple(_normal_path(p) for p in site.getsitepackages() + [site.getusersitepackages()])
        evidence = ImportAuthorityEvidence(
            target_root=_normal_path(self.target_root),
            expected_commit=self.expected_commit,
            git_head=head,
            python_executable=_normal_path(Path(sys.executable)),
            cwd=_normal_path(Path.cwd()),
            sys_path=paths,
            site_paths=sites,
            package_file=package_file,
            critical_module_files=tuple(modules),
        )
        if not _within(Path(package_file), self.source_root):
            raise ImportAuthorityError(f"package outside target source: {package_file}")
        if any(not _within(Path(path), self.source_root) for path in modules):
            raise ImportAuthorityError("critical module outside target source")
        return evidence

    def assert_authority(self) -> ImportAuthorityEvidence:
        return self.evidence()


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
    return _normal_path(Path(path))


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolved(value: str) -> Path:
    return Path(value or os.getcwd()).resolve()


def _normal_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


__all__ = [
    "CheckoutImportAuthority",
    "ImportAuthorityError",
    "ImportAuthorityEvidence",
]

