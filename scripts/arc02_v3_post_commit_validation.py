"""ARC02 V3 post-commit validation (work order §24).

Creates a brand-new DETACHED worktree at V3_PREREG_COMMIT, runs the full
builder-side non-economic acceptance under the intentionally contaminated
ambient environment, records CLEAN_WORKTREE_BUILDER_CROSSCHECK and
POST_FREEZE_ARTIFACT_DRIFT, then REMOVES the temporary worktree.

Usage: python scripts/arc02_v3_post_commit_validation.py <V3_PREREG_COMMIT>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
MAIN_REPO = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
MAIN_SRC = MAIN_REPO / "src"
PY = str(MAIN_REPO / ".venv" / "Scripts" / "python.exe")
ART = WORKTREE / "docs" / "external-audit-01" / "arc02-prereg-v3-repair-01"
CONTAMINATED = {**os.environ, "PYTHONPATH": str(MAIN_SRC)}

SPEC_SHA = "ef5d76196943b7498f2ed70757e0405acc2a07a4c80a66b71eaba548950afc40"
MANIFEST_SHA = "9a7499813bde088ebde517e77bf9089148d0c4c875d1d719fd4f8c0754827e88"


def git(args: list[str], cwd: Path | str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: arc02_v3_post_commit_validation.py <V3_PREREG_COMMIT>", file=sys.stderr)
        return 2
    v3_commit = sys.argv[1]

    with tempfile.TemporaryDirectory(prefix="arc02-v3-fresh-") as td:
        fresh = Path(td) / "arc02-v3-fresh-wt"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(fresh), v3_commit],
            cwd=str(WORKTREE), check=True, capture_output=True, text=True,
        )
        try:
            results: dict[str, object] = {"v3_prereg_commit": v3_commit}

            # 1. plain Python authority (from an arbitrary cwd)
            boot = str(fresh / "scripts" / "arc02_import_bootstrap.py")
            code = f"""
import json, importlib.util
spec = importlib.util.spec_from_file_location("b", {boot!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ev = m.bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
"""
            r = subprocess.run([PY, "-c", code], cwd=str(os.environ.get("TEMP", td)),
                               env=CONTAMINATED, capture_output=True, text=True)
            d = {}
            for line in r.stdout.splitlines():
                if line.startswith("JSON:"):
                    d = json.loads(line[5:])
            results["plain_python_authority"] = {
                "returncode": r.returncode,
                "target_root": d.get("target_root"),
                "package_file": d.get("package_file"),
                "package_within_target": d.get("package_within_target"),
                "critical_all_within_target": d.get("critical_all_within_target"),
                "PASS": r.returncode == 0 and d.get("package_within_target") is True
                        and d.get("critical_all_within_target") is True
                        and d.get("git_head") == v3_commit,
            }

            # 2. pytest authority + Track B regression inside the fresh worktree
            pr = subprocess.run(
                [PY, "-m", "pytest",
                 "tests/unit/research/test_arc02_import_authority_v3.py",
                 "tests/unit/research/test_discovery_view.py",
                 "tests/unit/research/test_discovery_execution.py",
                 "-q", "--no-header"],
                cwd=str(fresh), env=CONTAMINATED, capture_output=True, text=True,
            )
            results["pytest_authority_fresh"] = {
                "returncode": pr.returncode,
                "output_tail": (pr.stdout or "")[-300:],
                "PASS": pr.returncode == 0,
            }

            # 3. subprocess authority from contaminated parent
            sub_code = """
import json, os, sys
sys.path.insert(0, os.environ["ARC02_TARGET_ROOT"])
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
"""
            env = {**CONTAMINATED, "ARC02_TARGET_ROOT": str(fresh), "ARC02_EXPECTED_COMMIT": v3_commit}
            sr = subprocess.run([PY, "-c", sub_code], cwd=str(os.environ.get("TEMP", td)),
                                env=env, capture_output=True, text=True)
            sd = {}
            for line in sr.stdout.splitlines():
                if line.startswith("JSON:"):
                    sd = json.loads(line[5:])
            results["subprocess_authority_fresh"] = {
                "returncode": sr.returncode,
                "package_within_target": sd.get("package_within_target"),
                "PASS": sr.returncode == 0 and sd.get("package_within_target") is True,
            }

            # 4. data binding + PIT target authority against the certified root
            certified = MAIN_REPO / ".research" / "arc02-candidate-design-01"
            out_tmp = Path(td) / "data_binding.json"
            dr = subprocess.run(
                [PY, "scripts/verify_arc02_data_authority.py",
                 "--target", str(fresh), "--data-root", str(certified),
                 "--skip-git", "--out", str(out_tmp)],
                cwd=str(fresh), env=CONTAMINATED, capture_output=True, text=True,
            )
            rep = json.loads(out_tmp.read_text(encoding="utf-8")) if out_tmp.exists() else {}
            results["data_binding_fresh"] = {
                "returncode": dr.returncode,
                "verdict": rep.get("verdict"),
                "PYTHON_IMPORT_AUTHORITY": {c["check"]: c["pass"] for c in rep.get("checks", [])}.get("PYTHON_IMPORT_AUTHORITY"),
                "PIT_BATTERY": {c["check"]: c["pass"] for c in rep.get("checks", [])}.get("PIT_BATTERY"),
                "PASS": rep.get("verdict") == "PASS",
            }

            # 5. post-freeze artifact drift on the FRESH tree (target docs only)
            import hashlib

            frozen = [
                "docs/arc02-prereg-01/ARC02_SPEC_V1.json",
                "docs/arc02-prereg-01/ARC02_MANIFEST_V1.json",
            ]
            drift: dict[str, dict[str, str]] = {}
            for rel in frozen:
                b = (fresh / rel).read_bytes()
                drift[rel] = {"sha256": hashlib.sha256(b).hexdigest()}
            drift_ok = (
                drift[frozen[0]]["sha256"] == SPEC_SHA
                and drift[frozen[1]]["sha256"] == MANIFEST_SHA
            )
            results["post_freeze_artifact_drift"] = {
                "artifacts": drift,
                "POST_FREEZE_ARTIFACT_DRIFT": 0 if drift_ok else 1,
                "required": {"SPEC": SPEC_SHA, "MANIFEST": MANIFEST_SHA},
            }

            gates = {
                "PLAIN_PYTHON_AUTHORITY": "PASS" if results["plain_python_authority"]["PASS"] else "FAIL",
                "PYTEST_AUTHORITY_FRESH": "PASS" if results["pytest_authority_fresh"]["PASS"] else "FAIL",
                "SUBPROCESS_AUTHORITY_FRESH": "PASS" if results["subprocess_authority_fresh"]["PASS"] else "FAIL",
                "DATA_BINDING_FRESH": "PASS" if results["data_binding_fresh"]["PASS"] else "FAIL",
                "POST_FREEZE_ARTIFACT_DRIFT": results["post_freeze_artifact_drift"]["POST_FREEZE_ARTIFACT_DRIFT"],
            }
            results["gates"] = gates
            failed = [k for k, v in gates.items() if v not in ("PASS", 0)]
            results["CLEAN_WORKTREE_BUILDER_CROSSCHECK"] = "PASS" if not failed else "FAIL"
            results["failed_gates"] = failed

            ART.mkdir(parents=True, exist_ok=True)
            out = ART / "ARC02_V3_POST_COMMIT_VALIDATION.json"
            out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("WROTE", out)
            print(json.dumps(gates, indent=2, default=str))
            print("CLEAN_WORKTREE_BUILDER_CROSSCHECK:", results["CLEAN_WORKTREE_BUILDER_CROSSCHECK"])
            return 0 if not failed else 1
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(fresh)],
                           cwd=str(WORKTREE), capture_output=True, text=True)


if __name__ == "__main__":
    raise SystemExit(main())
