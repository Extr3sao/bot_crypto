#!/usr/bin/env python
"""INDEPENDENT ARC-03 clean-worktree verification (verifier-owned).

Creates a throwaway DETACHED worktree at the exact frozen prereg commit, proves it starts
clean, and from that pristine checkout re-runs the verifier's own critical checks against the
explicit certified data root:

  1. import authority (trading_bot and every ARC-03 module resolve inside the throwaway tree)
  2. the ARC-03 prereg contract tests (synthetic fixtures, performance-blind)
  3. the verifier's independent data-binding re-derivation
  4. the verifier's independent PIT adversarial battery

Then the throwaway worktree is removed. Writes
docs/external-audit-01/arc03-prereg-verification-01/ARC03_CLEAN_WORKTREE_VERIFICATION.json

Read-only w.r.t. the frozen artifacts. No economic quantity is computed.

Usage:
    python verifier_clean_worktree.py --repo REPO --verifier-dir DIR --target-commit SHA \
        --data-root ABS
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def run(args: list[str], cwd: pathlib.Path, timeout: int = 1200) -> tuple[int, str]:
    p = subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False
    )
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--verifier-dir", required=True, help="verifier artifact directory")
    ap.add_argument("--target-commit", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    vdir = pathlib.Path(args.verifier_dir).resolve()
    scratch = repo / ".research" / "arc03-verifier-clean-scratch"
    commit = args.target_commit

    run(["git", "worktree", "prune"], repo)
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    rc, out = run(["git", "worktree", "add", "-q", "--detach", str(scratch), commit], repo)
    if rc != 0:
        print(json.dumps({"error": "worktree add failed", "detail": out}))
        return 1

    report: dict = {
        "schema": "ARC03_CLEAN_WORKTREE_VERIFICATION/1.0.0",
        "target_commit": commit,
        "scratch_worktree": str(scratch),
        "checks": {},
    }
    try:
        rc_h, head = run(["git", "rev-parse", "HEAD"], scratch)
        _, porcelain = run(["git", "status", "--porcelain"], scratch)
        report["head"] = head
        report["worktree_clean_at_start"] = porcelain == "" and head == commit
        report["checks"]["TARGET_COMMIT_MATERIALISED"] = "PASS" if head == commit else "FAIL"
        report["checks"]["CLEAN_AT_START"] = "PASS" if porcelain == "" else "FAIL"

        # 1. import authority from the pristine checkout
        prog = (
            "import json,sys,pathlib;"
            "sys.path.insert(0,str(pathlib.Path('src').resolve()));"
            "import trading_bot;"
            "from trading_bot.research.arc03 import arc03_authority as a;"
            "from trading_bot.research.arc03 import arc03_funding as f;"
            "print(json.dumps({'tb':str(pathlib.Path(trading_bot.__file__).resolve()),"
            "'arc03_authority':str(pathlib.Path(a.__file__).resolve()),"
            "'arc03_funding':str(pathlib.Path(f.__file__).resolve())}))"
        )
        rc_i, out_i = run([sys.executable, "-c", prog], scratch)
        # json.dumps escapes backslashes, so match on the unique scratch directory NAME
        # (the drive-letter prefix is also accepted if present) rather than the raw path.
        marker = scratch.name
        inside = rc_i == 0 and marker in out_i
        report["checks"]["PYTHON_IMPORT_AUTHORITY"] = "PASS" if inside else "FAIL"
        report["import_authority_output"] = out_i

        # 2. ARC-03 prereg contract tests (synthetic, fast)
        rc_t, out_t = run(
            [sys.executable, "-m", "pytest", "-q", "tests/unit/research/test_arc03_prereg.py"],
            scratch,
        )
        report["checks"]["PREREG_CONTRACT_TESTS"] = "PASS" if rc_t == 0 else "FAIL"
        report["prereg_tests_tail"] = out_t[-600:]

        # 3. independent data binding from the pristine checkout
        rc_b, out_b = run(
            [
                sys.executable,
                str(vdir / "verifier_independent_data_binding.py"),
                "--data-root",
                str(pathlib.Path(args.data_root).resolve()),
                "--out",
                str(vdir / ".clean-data-binding.json"),
            ],
            scratch,
        )
        binding_ok = rc_b == 0
        if binding_ok:
            try:
                binding_ok = json.loads(out_b.splitlines()[-1]).get("DATA_BINDING") == "PASS"
            except Exception:
                binding_ok = "\"DATA_BINDING\": \"PASS\"" in out_b
        report["checks"]["DATA_BINDING_FROM_CLEAN_WORKTREE"] = "PASS" if binding_ok else "FAIL"
        report["data_binding_tail"] = out_b[-400:]

        # 4. independent PIT battery from the pristine checkout
        rc_p, out_p = run(
            [
                sys.executable,
                str(vdir / "verifier_independent_pit.py"),
                "--data-root",
                str(pathlib.Path(args.data_root).resolve()),
                "--out",
                str(vdir / ".clean-pit.json"),
            ],
            scratch,
        )
        pit_ok = rc_p == 0
        if pit_ok:
            try:
                pit_ok = json.loads(out_p.splitlines()[-1]).get("PIT_INDEPENDENT") == "PASS"
            except Exception:
                pit_ok = "\"PIT_INDEPENDENT\": \"PASS\"" in out_p
        report["checks"]["PIT_INDEPENDENT_FROM_CLEAN_WORKTREE"] = "PASS" if pit_ok else "FAIL"
        report["pit_tail"] = out_p[-400:]

        _, porcelain_after = run(["git", "status", "--porcelain"], scratch)
        # Running pytest creates interpreter caches (__pycache__/, .pytest_cache/). Those are
        # not frozen artifacts; what matters is that no TRACKED file changed and no new
        # non-cache path appeared.
        cache_entries = [
            line for line in porcelain_after.splitlines()
            if "__pycache__" in line or ".pytest_cache" in line or line.strip().endswith(".pyc")
        ]
        substantive = [
            line for line in porcelain_after.splitlines() if line not in cache_entries
        ]
        report["porcelain_after_checks"] = porcelain_after
        report["cache_only_entries"] = cache_entries
        report["substantive_changes_after_checks"] = substantive
        report["worktree_still_clean_after_checks"] = not substantive
        report["checks"]["TEST_TARGET_EQUALS_AUDITED_TARGET"] = (
            "PASS" if report["checks"]["PYTHON_IMPORT_AUTHORITY"] == "PASS" else "FAIL"
        )

        all_pass = all(v == "PASS" for v in report["checks"].values())
        report["CLEAN_WORKTREE_VERIFICATION"] = "PASS" if all_pass and report["worktree_clean_at_start"] else "FAIL"
    finally:
        for f in (".clean-data-binding.json", ".clean-pit.json"):
            p = vdir / f
            if p.exists():
                p.unlink()
        run(["git", "worktree", "remove", "--force", str(scratch)], repo)
        run(["git", "worktree", "prune"], repo)

    out_path = vdir / "ARC03_CLEAN_WORKTREE_VERIFICATION.json"
    out_path.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({k: report.get(k) for k in ("CLEAN_WORKTREE_VERIFICATION", "checks")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
