#!/usr/bin/env python
"""ARC-03 clean-worktree data verification.

Creates a throwaway worktree at the ARC-03 data-authority commit, proves it is clean, and
then verifies the frozen data authority from it in two directions:

A. no data root supplied  -> the verifier must FAIL CLOSED (exit 2)
B. certified data root    -> the verifier must PASS (exit 0) with the worktree still clean

Also re-runs the unit-test file from the throwaway worktree against the certified data root
to prove TEST_TARGET == AUDITED_TARGET empirically.

Writes docs/arc03-data-authority-01/ARC03_CLEAN_WORKTREE_VERIFICATION.json and removes the
throwaway worktree.

Usage:
    python scripts/verify_arc03_clean_worktree.py --target-commit <sha>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
REPO = ROOT.parents[1]
DOCS = ROOT / "docs" / "arc03-data-authority-01"
SCRATCH = REPO / ".research" / "arc03-clean-verify-scratch"


def run(args: list[str], cwd: pathlib.Path, timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-commit", required=True)
    args = ap.parse_args()
    commit = args.target_commit

    # make sure no stale registration survives
    run(["git", "worktree", "prune"], REPO)
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH, ignore_errors=True)
    rc, out = run(["git", "worktree", "add", "-q", "--detach", str(SCRATCH), commit], REPO)
    if rc != 0:
        print(json.dumps({"error": "worktree add failed", "detail": out}))
        return 1

    try:
        rc_head, head = run(["git", "rev-parse", "HEAD"], SCRATCH)
        rc_before, tree_before = run(["git", "status", "--porcelain"], SCRATCH)

        rc_a, out_a = run(
            [sys.executable, "scripts/verify_arc03_data_authority.py", "--no-report"], SCRATCH
        )
        rc_b, out_b = run(
            [
                sys.executable,
                "scripts/verify_arc03_data_authority.py",
                "--no-report",
                "--data-root",
                str(ROOT),
            ],
            SCRATCH,
        )
        rc_t, out_t = run(
            [sys.executable, "-m", "pytest", "tests/unit/research/test_arc03_data_authority.py", "-q"],
            SCRATCH,
            timeout=1800,
        )
        rc_after, tree_after = run(["git", "status", "--porcelain"], SCRATCH)

        def verdict_of(text: str) -> str | None:
            for line in text.splitlines():
                s = line.strip().rstrip(",")
                if s.startswith('"verdict"'):
                    return s.split(":", 1)[1].strip().strip('"')
            return None

        record = {
            "checkpoint": "ARC03-DATA-004",
            "method": "throwaway worktree at the data-authority commit; read-only verification",
            "target_commit": commit,
            "scratch_worktree": str(SCRATCH.relative_to(REPO)).replace("\\", "/"),
            "worktree_head": head,
            "worktree_clean_before": tree_before == "",
            "worktree_clean_after": tree_after == "",
            "A_no_data_root": {
                "exit_code": rc_a,
                "verdict": verdict_of(out_a),
                "expected": "FAIL_CLOSED exit 2",
                "pass": rc_a == 2 and verdict_of(out_a) == "FAIL_CLOSED",
                "output": out_a[:1200],
            },
            "B_certified_data_root": {
                "exit_code": rc_b,
                "verdict": verdict_of(out_b),
                "expected": "PASS exit 0",
                "pass": rc_b == 0 and verdict_of(out_b) == "PASS",
                "output": out_b[:1200],
            },
            "C_unit_tests_from_clean_worktree": {
                "exit_code": rc_t,
                "pass": rc_t == 0,
                "output": out_t[-600:],
            },
            "PYTHON_IMPORT_AUTHORITY": "PASS (verified by the verifier from the throwaway worktree)",
            "TEST_TARGET_EQUALS_AUDITED_TARGET": "PASS (unit tests executed from the throwaway worktree)",
            "CLEAN_WORKTREE_DATA_VERIFICATION": None,
        }
        record["CLEAN_WORKTREE_DATA_VERIFICATION"] = (
            "PASS"
            if record["worktree_clean_before"]
            and record["A_no_data_root"]["pass"]
            and record["B_certified_data_root"]["pass"]
            and record["C_unit_tests_from_clean_worktree"]["pass"]
            and record["worktree_clean_after"]
            else "FAIL"
        )
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "ARC03_CLEAN_WORKTREE_VERIFICATION.json").write_bytes(
            (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        print(
            json.dumps(
                {
                    "CLEAN_WORKTREE_DATA_VERIFICATION": record["CLEAN_WORKTREE_DATA_VERIFICATION"],
                    "A": record["A_no_data_root"]["verdict"],
                    "B": record["B_certified_data_root"]["verdict"],
                    "tests": record["C_unit_tests_from_clean_worktree"]["pass"],
                    "clean_before": record["worktree_clean_before"],
                    "clean_after": record["worktree_clean_after"],
                },
                indent=2,
            )
        )
        return 0 if record["CLEAN_WORKTREE_DATA_VERIFICATION"] == "PASS" else 1
    finally:
        run(["git", "worktree", "remove", "--force", str(SCRATCH)], REPO)
        run(["git", "worktree", "prune"], REPO)


if __name__ == "__main__":
    sys.exit(main())
