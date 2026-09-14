"""H6 V4 — CLEAN WORKTREE self-verification (checkpoint section 34).

Creates a fresh git worktree from the final V4 builder package, explicitly bootstraps
import authority, and re-runs the critical gates there.

This is BUILDER evidence only. It does NOT satisfy INDEPENDENT_EXTERNAL_VERIFICATION_V4.

No economics.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs/external-audit-01" / "h6-v4-repair"
PY = sys.executable


def _main_repo_root() -> Path:
    """The MAIN checkout, not this worktree.

    The clean worktree must be created at the canonical ``<main>/.worktrees/<name>``
    depth. Nesting it inside this worktree would make the shared-data-root fallback
    look one level too shallow and would not represent a realistic verifier layout.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=str(REPO), capture_output=True, text=True
    )
    common = Path(out.stdout.strip())
    if not common.is_absolute():
        common = (REPO / common).resolve()
    return common.parent if common.name == ".git" else REPO.parents[1]


CLEAN = _main_repo_root() / ".worktrees" / "h6-v4-clean-self-verify"


def _rel_to_main(path: Path) -> str:
    try:
        return str(path.relative_to(_main_repo_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
NT = "tests/unit/research"


def _default_data_root() -> str:
    env = os.environ.get("TRADING_AGENTIC_DATA_ROOT")
    if env:
        return env
    main = _main_repo_root()
    for cand in (main / "data", REPO / "data"):
        try:
            if (cand / "processed" / "oi_full_history_v2").is_dir() or (
                cand / "raw" / "binance_um" / "metrics"
            ).is_dir():
                return str(cand.resolve())
        except Exception:
            continue
    for cand in (main / "data", REPO / "data"):
        if cand.is_dir():
            return str(cand.resolve())
    return str((main / "data").resolve())


DATA_ROOT = _default_data_root()


def git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def main() -> int:
    started = datetime.now(timezone.utc)
    t0 = time.time()

    if CLEAN.exists():
        git("worktree", "remove", "--force", str(CLEAN))
        shutil.rmtree(CLEAN, ignore_errors=True)

    head = git("rev-parse", "HEAD").stdout.strip()
    git("worktree", "prune")
    add = git("worktree", "add", "--detach", str(CLEAN), head)
    if add.returncode != 0:
        print("worktree add failed:", add.stderr)
        return 2

    src = CLEAN / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    env["PYTHONHASHSEED"] = "0"
    env["TZ"] = "UTC"
    env["TRADING_AGENTIC_DATA_ROOT"] = DATA_ROOT
    # Sub-gate results are written into the audited worktree's evidence dir, not into the
    # disposable clean worktree and not into the frozen V3 audit records.
    env["H6_EVIDENCE_DIR"] = str(OUT)

    gates: list[dict] = []

    def run(name: str, cmd: list[str], *, timeout: int = 1800) -> dict:
        p = subprocess.run(cmd, cwd=str(CLEAN), capture_output=True, text=True, env=env, timeout=timeout)
        lines = (p.stdout or "").strip().splitlines()
        gates.append({
            "gate": name,
            "command": " ".join(cmd),
            "returncode": p.returncode,
            "status": "PASS" if p.returncode == 0 else "FAIL",
            "stdout_tail": lines[-12:],
            "stderr_tail": (p.stderr or "").strip().splitlines()[-8:],
        })
        print(f"  {gates[-1]['status']:5s} {name}", flush=True)
        return gates[-1]

    print("=== CLEAN WORKTREE SELF VERIFICATION ===")
    run("PYTHON_IMPORT_AUTHORITY", [PY, "scripts/verify_python_import_authority.py", "--json"])
    run("WHITELIST_ATTACKS", [PY, "-m", "pytest", f"{NT}/test_h6_v4_whitelist_authority.py", "-q"])
    run("RUNTIME_REACHABILITY", [PY, "-m", "pytest", f"{NT}/test_h6_v4_whitelist_authority.py", "-q", "-k", "reachable or injection"])
    run("HOUR_AGGREGATION", [PY, "-m", "pytest", f"{NT}/test_h6_v4_hour_aggregation.py", "-q"])
    run("AUTHORITY_BINDING", [PY, "-m", "pytest", f"{NT}/test_h6_v4_authority_binding.py", "-q"])
    run("V4_SPEC_COMPLETE_AND_SEMANTIC_DIFF", [PY, "docs/external-audit-01/h6-v4-repair/h6_v4_validate.py"])
    run("DATA_AUTHORITY", [PY, "scripts/verify_h6_data_authority.py", "--data-root", DATA_ROOT])
    # The full A/B proof costs ~2.5 h per run (5,691 files re-normalized twice) and its result
    # cannot depend on which worktree executes it, so it is REUSED under an explicit
    # commit+data-root binding. The layout-sensitive half -- resolving the shared data root
    # through the shipped resolver and recomputing the authority fingerprint from actual
    # bytes -- IS re-executed here. See scripts/verify_h6_v4_clean_worktree_determinism.py.
    run("DATASET_DETERMINISM", [PY, "scripts/verify_h6_v4_clean_worktree_determinism.py"])
    run("PRICE_AUTHORITY_OVERLAP", [PY, "scripts/verify_price_overlap_v3.py", "--data-root", DATA_ROOT])
    run("CONFIRMATION_SHADOW_ISOLATION", [PY, "-m", "pytest", f"{NT}/test_h6_confirmation_isolation.py", f"{NT}/test_h6_v3_test_isolation.py", f"{NT}/test_confirmation_ledger_lock.py", "-q"])
    run("PERFORMANCE_CONTAMINATION", [PY, "-m", "pytest", f"{NT}/test_data_admission.py", f"{NT}/test_h5_orderflow.py", "-q"])
    run("POST_FREEZE_IMMUTABILITY", [PY, "scripts/verify_h6_v4_post_freeze_immutability.py"])

    # dashboard 20x
    dash_ok = 0
    dash_test = "tests/unit/paper_dashboard/test_server.py::test_non_get_methods_are_405"
    for _ in range(20):
        p = subprocess.run(
            [PY, "-m", "pytest", "-p", "no:cacheprovider", "-q", dash_test],
            cwd=str(CLEAN), capture_output=True, text=True, env=env,
        )
        dash_ok += 1 if p.returncode == 0 else 0
    gates.append({"gate": "DASHBOARD_REPEAT_20", "command": dash_test, "returncode": 0 if dash_ok == 20 else 1,
                  "status": "PASS" if dash_ok == 20 else "FAIL", "stdout_tail": [f"{dash_ok}/20"], "stderr_tail": []})
    print(f"  {'PASS' if dash_ok == 20 else 'FAIL':5s} DASHBOARD_REPEAT_20 ({dash_ok}/20)", flush=True)

    # one full hermetic run from the clean worktree
    p = subprocess.run(
        [PY, "scripts/run_regression_hermetic.py", "-p", "no:cacheprovider", "-q"],
        cwd=str(CLEAN), capture_output=True, text=True, env=env, timeout=3600,
    )
    lines = (p.stdout or "").strip().splitlines()
    passed = failed = skipped = None
    for line in reversed(lines):
        m_pass, m_fail = re.search(r"(\d+) passed", line), re.search(r"(\d+) failed", line)
        if m_pass or m_fail:
            passed = int(m_pass.group(1)) if m_pass else 0
            failed = int(m_fail.group(1)) if m_fail else 0
            m_skip = re.search(r"(\d+) skipped", line)
            skipped = int(m_skip.group(1)) if m_skip else 0
            break
    gates.append({"gate": "FULL_HERMETIC_CLEAN_WORKTREE", "command": "run_regression_hermetic.py",
                  "returncode": p.returncode, "status": "PASS" if p.returncode == 0 else "FAIL",
                  "stdout_tail": lines[-8:], "stderr_tail": (p.stderr or "").strip().splitlines()[-6:],
                  "passed": passed, "failed": failed, "skipped": skipped})
    print(f"  {'PASS' if p.returncode == 0 else 'FAIL':5s} FULL_HERMETIC_CLEAN_WORKTREE "
          f"(passed={passed} failed={failed} skipped={skipped})", flush=True)

    failed_gates = [g["gate"] for g in gates if g["status"] != "PASS"]
    report = {
        "artifact": "H6_V4_CLEAN_WORKTREE_SELF_VERIFICATION",
        "checkpoint": "H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01",
        "independence": "BUILDER_SELF_VERIFICATION_V4",
        "does_not_satisfy": "INDEPENDENT_EXTERNAL_VERIFICATION_V4",
        # The clean worktree lives under the MAIN checkout, not under this worktree (the
        # canonical layout removed in [H6-V4-06]); report it relative to the main root so the
        # path stays readable without assuming nesting inside REPO.
        "clean_worktree": _rel_to_main(CLEAN),
        "source_commit": head,
        "base_commit": "a548716",
        "python_executable": PY,
        "module_path_authority": str(src),
        "data_root": DATA_ROOT,
        "timestamp_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_s": round(time.time() - t0, 2),
        "gates": gates,
        "failed_gates": failed_gates,
        "CLEAN_WORKTREE_SELF_VERIFICATION": "PASS" if not failed_gates else "FAIL",
        "H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False,
    }
    (OUT / "H6_V4_CLEAN_WORKTREE_SELF_VERIFICATION.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )

    if os.environ.get("KEEP_CLEAN_WORKTREE") != "1":
        git("worktree", "remove", "--force", str(CLEAN))
        shutil.rmtree(CLEAN, ignore_errors=True)

    print()
    print("CLEAN_WORKTREE_SELF_VERIFICATION =", report["CLEAN_WORKTREE_SELF_VERIFICATION"])
    if failed_gates:
        print("FAILED:", ", ".join(failed_gates))
    return 0 if not failed_gates else 1


if __name__ == "__main__":
    raise SystemExit(main())
