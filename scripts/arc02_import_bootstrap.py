"""Standalone V3 bootstrap used by ARC-02 scripts before first-party imports.

Contract:

* MUST be invoked before ``import trading_bot`` in any authoritative process.
* Fails closed on: wrong preloaded first-party modules, missing target src,
  commit mismatch, package or critical modules resolving outside the target.
* Never depends on cwd: the target root is derived from this file's location
  or passed explicitly (work order §9).
* Works under ambient contamination: editable ``.pth`` files, PYTHONPATH
  entries and site-packages editable metadata pointing at the main checkout
  are purged from resolution for first-party imports (§10); third-party
  dependencies remain available.
* Subprocess authority (§13): pass ``target_root``/``expected_commit``
  explicitly (see ``subprocess_authority_env``) or set
  ``ARC02_TARGET_ROOT``/``ARC02_EXPECTED_COMMIT`` in the child environment.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ENV_TARGET_ROOT = "ARC02_TARGET_ROOT"
ENV_EXPECTED_COMMIT = "ARC02_EXPECTED_COMMIT"

CRITICAL_MODULES: tuple[str, ...] = (
    "trading_bot.research.arc02.arc02_authority",
    "trading_bot.research.arc02.arc02_normalize",
    "trading_bot.research.arc02.arc02_pit",
)


def _default_target_root() -> Path:
    # scripts/ lives directly under the worktree root: never rely on cwd.
    return Path(__file__).resolve().parents[1]


def _load_authority_contract(target_root: Path):
    helper = target_root / "src" / "trading_bot" / "research" / "import_authority.py"
    if not helper.is_file():
        raise RuntimeError(f"cannot load import authority contract: {helper}")
    spec = importlib.util.spec_from_file_location("_arc02_import_authority", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import authority contract: {helper}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_expected_commit(target_root: Path, expected_commit: str | None) -> str:
    if expected_commit:
        return expected_commit
    env = os.environ.get(ENV_EXPECTED_COMMIT)
    if env:
        return env
    import subprocess

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(target_root), text=True
    ).strip()


def bootstrap_arc02(
    target_root: Path | str | None = None,
    expected_commit: str | None = None,
):
    """Establish and prove checkout import authority. Returns evidence.

    Raises (fail closed) instead of repairing a wrong environment silently.
    """
    root = Path(target_root).resolve() if target_root is not None else _default_target_root()
    contract = _load_authority_contract(root)
    commit = _resolve_expected_commit(root, expected_commit)
    authority = contract.CheckoutImportAuthority(
        target_root=root,
        expected_commit=commit,
        package_name="trading_bot",
        critical_modules=CRITICAL_MODULES,
    )
    evidence = authority.assert_authority()
    os.environ[ENV_TARGET_ROOT] = str(root)
    os.environ[ENV_EXPECTED_COMMIT] = commit
    return evidence


def main() -> int:
    try:
        ev = bootstrap_arc02()
    except Exception as exc:  # fail closed with a clear, nonzero exit
        print(f"ARC02_IMPORT_AUTHORITY=FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    d = ev.to_dict()
    print("ARC02_IMPORT_AUTHORITY=PASS")
    print(f"target_root={d['target_root']}")
    print(f"git_head={d['git_head']}")
    print(f"package_file={d['package_file']}")
    for m in d["critical_module_files"]:
        print(f"critical_module={m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["bootstrap_arc02", "CRITICAL_MODULES", "ENV_TARGET_ROOT", "ENV_EXPECTED_COMMIT"]
