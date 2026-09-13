"""Portable PYTHON IMPORT AUTHORITY guard (V4 repair for V3-IMPORT-001).

The shared virtualenv ships an editable install whose ``.pth`` pins the **main**
checkout's ``src`` directory by absolute path. Inside a git worktree a bare
``import trading_bot`` therefore silently resolves to the main checkout's code, so
every test or script run there would verify the WRONG tree.

This script asserts that ``trading_bot`` (and the critical H6 modules) resolve inside
the *current git worktree*, and it can bootstrap a correct resolution without
modifying the shared venv.

Usage::

    python scripts/verify_python_import_authority.py            # check
    python scripts/verify_python_import_authority.py --bootstrap # exec a child with a clean PYTHONPATH

Exit code 0 means PYTHON_IMPORT_AUTHORITY = PASS.

No economics.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CRITICAL_MODULES = (
    "trading_bot.research.h6",
    "trading_bot.research.h6.whitelist",
    "trading_bot.research.h6.feature_authority",
    "trading_bot.research.h6.preparation",
    "trading_bot.research.h6.frozen_contract_snapshot",
    "trading_bot.research.oi_dataset_v2",
)


def _git_toplevel(start: Path) -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(start), capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise SystemExit("verify_python_import_authority: not a git worktree")
    return Path(out.stdout.strip()).resolve()


def _git_commit(root: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=30
    )
    return out.stdout.strip() if out.returncode == 0 else "UNKNOWN"


def check() -> dict:
    repo_root = _git_toplevel(Path(__file__).resolve().parent)
    expected_src = (repo_root / "src").resolve()

    import importlib
    import trading_bot

    report = {
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "python_executable": sys.executable,
        "repo_root": str(repo_root),
        "git_commit": _git_commit(repo_root),
        "expected_src": str(expected_src),
        "trading_bot_file": str(Path(trading_bot.__file__).resolve()),
        "modules": {},
        "sys_path": sys.path[:10],
    }

    failures: list[str] = []
    tb_file = Path(trading_bot.__file__).resolve()
    if expected_src not in tb_file.parents:
        failures.append(
            f"trading_bot resolves OUTSIDE this worktree: {tb_file} (expected under {expected_src})"
        )

    for name in CRITICAL_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            report["modules"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            failures.append(f"{name} failed to import: {type(exc).__name__}")
            continue
        path = Path(mod.__file__).resolve()
        inside = expected_src in path.parents
        report["modules"][name] = {"ok": inside, "file": str(path)}
        if not inside:
            failures.append(f"{name} resolves OUTSIDE this worktree: {path}")

    report["failures"] = failures
    report["PYTHON_IMPORT_AUTHORITY"] = "PASS" if not failures else "FAIL"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument(
        "--bootstrap",
        metavar="CMD",
        nargs=argparse.REMAINDER,
        help="run CMD with PYTHONPATH forced to this worktree's src",
    )
    args = ap.parse_args()

    repo_root = _git_toplevel(Path(__file__).resolve().parent)

    if args.bootstrap:
        env = dict(os.environ)
        env["PYTHONPATH"] = str((repo_root / "src").resolve())
        return subprocess.call(args.bootstrap, env=env)

    report = check()
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"PYTHON_IMPORT_AUTHORITY = {report['PYTHON_IMPORT_AUTHORITY']}")
        print(f"  python       = {report['python_executable']}")
        print(f"  repo_root    = {report['repo_root']}")
        print(f"  git_commit   = {report['git_commit']}")
        print(f"  trading_bot  = {report['trading_bot_file']}")
        for failure in report["failures"]:
            print(f"  FAIL: {failure}")
        if report["PYTHON_IMPORT_AUTHORITY"] == "PASS":
            print("  every critical module resolves inside this worktree")
    return 0 if report["PYTHON_IMPORT_AUTHORITY"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
