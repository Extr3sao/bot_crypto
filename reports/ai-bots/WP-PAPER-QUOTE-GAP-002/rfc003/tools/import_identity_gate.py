"""Import-identity gate — fails closed when the package under test is not the one in the checkout.

The failure this exists to catch is silent: a worktree and its sibling share one
interpreter, an editable install points at whichever tree was installed last, and
``pytest`` reports green about code the auditor is not looking at.  So the gate does
not trust ``sys.path``; it spawns a fresh process, scrubs ``PYTHONPATH`` and
``PYTHONHOME``, and asks the child where the package actually came from.

Exit codes:
    0  the origin is inside the expected checkout
    3  the origin is outside it (contamination)
    4  the package is not importable at all
    5  the checkout is not at the expected commit
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROBE = r"""
import importlib.util, json, sys
spec = importlib.util.find_spec("trading_bot")
if spec is None or spec.origin is None:
    print(json.dumps({"found": False, "sys_path": sys.path}))
else:
    print(json.dumps({
        "found": True,
        "origin": spec.origin,
        "sys_path": sys.path,
        "python": sys.executable,
        "version": sys.version,
    }))
"""


def run_git(checkout: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=checkout, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def check(
    checkout: Path,
    expected_commit: str | None,
    extra_pythonpath: str | None,
    python: Path,
) -> dict[str, object]:
    checkout = checkout.resolve()
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    if extra_pythonpath:
        env["PYTHONPATH"] = extra_pythonpath
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    commit_code, commit = run_git(checkout, "rev-parse", "HEAD")
    dirty_code, dirty = run_git(checkout, "status", "--porcelain=v2", "--untracked-files=all")

    proc = subprocess.run(
        [str(python), "-c", PROBE], cwd=checkout, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        probe = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        probe = {"found": False, "error": (proc.stdout + proc.stderr).strip()[:800]}

    verdict: dict[str, object] = {
        "checkout": str(checkout),
        "python": str(python),
        "expected_commit": expected_commit,
        "commit": commit if commit_code == 0 else None,
        "dirty_entries": len([l for l in dirty.splitlines() if l.strip()]),
        "injected_pythonpath": extra_pythonpath,
        "probe": probe,
    }

    if not probe.get("found"):
        verdict.update(status="BLOCKED", code="IMPORT_UNREACHABLE",
                       detail="trading_bot is not importable from this interpreter at all")
        return verdict
    origin = Path(str(probe["origin"]))
    verdict["origin_inside_checkout"] = inside(origin, checkout)
    if expected_commit and commit != expected_commit:
        verdict.update(status="BLOCKED", code="CHECKOUT_NOT_AT_COMMIT",
                       detail=f"checkout is at {commit}, expected {expected_commit}")
        return verdict
    if not inside(origin, checkout):
        verdict.update(status="REFUSED", code="FOREIGN_CHECKOUT",
                       detail=f"trading_bot resolved to {origin}, outside {checkout}")
        return verdict
    verdict.update(status="OK", code=None, detail="package origin is inside the checkout")
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expect-commit", default=None)
    parser.add_argument("--python", type=Path, default=None,
                        help="interpreter to probe (default: <checkout>/.venv)")
    parser.add_argument("--inject-pythonpath", default=None,
                        help="adversarial NEG-01: point PYTHONPATH at a sibling tree")
    parser.add_argument("--expect", choices=["OK", "REFUSED", "BLOCKED"], default="OK")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    python = args.python
    if python is None:
        candidate = args.checkout / ".venv" / "Scripts" / "python.exe"
        if not candidate.exists():
            candidate = args.checkout / ".venv" / "bin" / "python"
        python = candidate
    if not python.exists():
        print(json.dumps({"status": "BLOCKED", "code": "NO_INTERPRETER", "python": str(python)}))
        return 4

    verdict = check(args.checkout, args.expect_commit, args.inject_pythonpath, python)
    verdict["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    verdict["expected_status"] = args.expect

    matches = verdict["status"] == args.expect
    verdict["gate_matches_expectation"] = matches
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")

    if not matches:
        #: The gate was asked to prove a rejection and it did not reject: the suite must not
        #: continue on an identity nobody proved.
        return 6
    return {"OK": 0, "REFUSED": 3, "BLOCKED": 4}[args.expect]


if __name__ == "__main__":
    sys.exit(main())
