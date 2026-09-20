"""ARC02 V3 builder crosscheck (work order §20/§21).

Runs the real authoritative entrypoints under the real ambient contamination and
writes every V3 evidence artifact into
docs/external-audit-01/arc02-prereg-v3-repair-01/.

This is BUILDER-side evidence only — it is never independent verification.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
MAIN_REPO = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
MAIN_SRC = MAIN_REPO / "src"
CERTIFIED_DATA_ROOT = MAIN_REPO / ".research" / "arc02-candidate-design-01"
PY = str(MAIN_REPO / ".venv" / "Scripts" / "python.exe")
ART = WORKTREE / "docs" / "external-audit-01" / "arc02-prereg-v3-repair-01"

V1_COMMIT = "3ebf5f54bba84300663a9de7f6b05c5b583bc9c6"
V2_COMMIT = "6df96c66ac4ea2fe5413cf896befc1ce997cd6e5"
V2_VERIFY_COMMIT = "00063237de21e3ed9273d84293f129f75003f126"
SPEC_SHA = "ef5d76196943b7498f2ed70757e0405acc2a07a4c80a66b71eaba548950afc40"
MANIFEST_SHA = "9a7499813bde088ebde517e77bf9089148d0c4c875d1d719fd4f8c0754827e88"
DATASET_SHA = "03f227d0ae18efdc8e3d84831283c4e3f7a333bf0fea8b944f55a9144cc164d5"

CONTAMINATED = {**os.environ, "PYTHONPATH": str(MAIN_SRC)}


def git(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd or WORKTREE), text=True
    ).strip()


def child(code: str, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-c", code], cwd=str(cwd), env=env,
                          capture_output=True, text=True)


def json_line(proc: subprocess.CompletedProcess) -> dict | None:
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    return None


def write(name: str, payload: dict) -> Path:
    ART.mkdir(parents=True, exist_ok=True)
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("WROTE", p.name)
    return p


BOOT_BY_PATH = """
import json, importlib.util
spec = importlib.util.spec_from_file_location("arc02_boot", {boot!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ev = m.bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
"""

WRONG_PRELOAD = """
import json, sys
import trading_bot
sys.path.insert(0, {worktree!r})
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02(target_root={worktree!r}, expected_commit={commit!r})
    print("JSON:" + json.dumps({{"result": "PASS"}}))
except Exception as exc:
    print("JSON:" + json.dumps({{"result": "FAIL_CLOSED", "error": str(exc)[:300]}}))
"""


# ------------------------------------------------------------------ 1. import authority
def import_authority_evidence() -> dict:
    head = git(["rev-parse", "HEAD"])
    cwd_home = Path.home()
    proc = child(BOOT_BY_PATH.format(boot=str(WORKTREE / "scripts" / "arc02_import_bootstrap.py")),
                 cwd=cwd_home, env=CONTAMINATED)
    d = json_line(proc) or {}
    ok = proc.returncode == 0 and d.get("package_within_target") is True \
        and d.get("critical_all_within_target") is True and d.get("git_head") == head

    # editable .pth attack: prove the contaminant exists in the ambient venv
    pth = MAIN_REPO / ".venv" / "Lib" / "site-packages" / "__editable__.crypto_scalping_agentic_bot-0.1.0.pth"
    pth_present = pth.exists() and str(MAIN_SRC) in pth.read_text(encoding="utf-8", errors="replace")

    # preloaded wrong module attack (import-order attack, §11)
    wp = child(WRONG_PRELOAD.format(worktree=str(WORKTREE), commit=head),
               cwd=cwd_home, env=CONTAMINATED)
    wpd = json_line(wp) or {}

    return {
        "artifact": "ARC02_V3_IMPORT_AUTHORITY",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "python_executable": PY,
        "target_root": d.get("target_root"),
        "target_commit": head,
        "git_head": d.get("git_head"),
        "cwd_used": str(cwd_home),
        "resolved_package_root": d.get("package_file"),
        "critical_module_files": d.get("critical_module_files"),
        "sys_path_removed": d.get("sys_path_removed"),
        "data_root": str(CERTIFIED_DATA_ROOT),
        "contamination_present": {
            "editable_pth_path": str(pth),
            "editable_pth_points_at_main_src": pth_present,
            "PYTHONPATH_main_src": str(MAIN_SRC),
        },
        "PYTHON_IMPORT_AUTHORITY": "PASS" if ok else "FAIL",
        "TEST_TARGET_AUDITED_TARGET": "PASS" if d.get("target_root") == str(WORKTREE).replace("\\", "/") else "FAIL",
        "EDITABLE_PTH_ATTACK": "PASS" if (pth_present and ok) else "FAIL",
        "PRELOADED_WRONG_MODULE_ATTACK": "PASS" if wpd.get("result") == "FAIL_CLOSED" else "FAIL",
        "preloaded_wrong_module_result": wpd,
        "runtime_bootstrap_returncode": proc.returncode,
        "runtime_bootstrap_stderr_tail": (proc.stderr[-1500:] if proc.stderr else None),
    }


# ------------------------------------------------------------------ 2. pytest authority
PYTEST_FILES = (
    "tests/unit/research/test_arc02_import_authority_v3.py "
    "tests/unit/research/test_arc02_prereg.py "
    "tests/unit/research/test_arc02_data_authority.py"
)


def pytest_authority_evidence() -> dict:
    head = git(["rev-parse", "HEAD"])
    r = subprocess.run(
        [PY, "-m", "pytest", *PYTEST_FILES.split(), "-q", "--no-header"],
        cwd=str(WORKTREE), env=CONTAMINATED, capture_output=True, text=True,
    )
    tail = (r.stdout or "")[-1200:]

    # §12: pytest must FAIL CLOSED when the authority contract is violated
    wrong = {**CONTAMINATED, "ARC02_EXPECTED_COMMIT": "0" * 40}
    wf = subprocess.run(
        [PY, "-m", "pytest", "tests/unit/research/test_arc02_prereg.py", "-q", "--no-header"],
        cwd=str(WORKTREE), env=wrong, capture_output=True, text=True,
    )
    combined = ((wf.stdout or "") + (wf.stderr or ""))
    fail_closed = wf.returncode != 0 and "PYTEST_AUTHORITY_FAIL_CLOSED" in combined

    return {
        "artifact": "ARC02_V3_PYTEST_AUTHORITY",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "pytest_invocation": f"python -m pytest {PYTEST_FILES} -q",
        "cwd": str(WORKTREE),
        "env_pythonpath": str(MAIN_SRC),
        "expected_commit": head,
        "pytest_returncode": r.returncode,
        "pytest_output_tail": tail,
        "PYTEST_AUTHORITY": "PASS" if r.returncode == 0 else "FAIL",
        "PYTEST_WRONG_IMPORT_FAIL_CLOSED": "PASS" if fail_closed else "FAIL",
        "wrong_commit_probe_returncode": wf.returncode,
        "wrong_commit_probe_output_head": combined[:800],
    }


# ------------------------------------------------------------------ 3. subprocess authority
def subprocess_authority_evidence_standalone() -> dict:
    head = git(["rev-parse", "HEAD"])
    # (a) contaminated parent -> child with explicit authority env -> target only
    child_ok = """
import json, os, sys
sys.path.insert(0, os.environ["ARC02_TARGET_ROOT"])
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02()
import trading_bot
d = ev.to_dict()
d["post_import_file"] = getattr(trading_bot, "__file__", None)
print("JSON:" + json.dumps(d))
"""
    env = {**CONTAMINATED, "ARC02_TARGET_ROOT": str(WORKTREE), "ARC02_EXPECTED_COMMIT": head}
    a = child(child_ok, cwd=Path(tempfile.gettempdir()), env=env)
    ad = json_line(a) or {}
    a_ok = a.returncode == 0 and ad.get("package_within_target") is True

    # (b) contaminated parent -> child preloads wrong module -> FAIL CLOSED
    child_bad = """
import json, os, sys
import trading_bot
sys.path.insert(0, os.environ["ARC02_TARGET_ROOT"])
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02()
    print("JSON:" + json.dumps({"result": "PASS"}))
except Exception:
    print("JSON:" + json.dumps({"result": "FAIL_CLOSED"}))
"""
    b = child(child_bad, cwd=Path(tempfile.gettempdir()), env=env)
    bd = json_line(b) or {}

    return {
        "artifact": "ARC02_V3_SUBPROCESS_AUTHORITY",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "parent_env_pythonpath": str(MAIN_SRC),
        "child_authority_channel": {"ARC02_TARGET_ROOT": str(WORKTREE), "ARC02_EXPECTED_COMMIT": head},
        "case_parent_contaminated_child_target": {
            "returncode": a.returncode,
            "package_file": ad.get("package_file"),
            "post_import_file": ad.get("post_import_file"),
            "package_within_target": ad.get("package_within_target"),
            "SUBPROCESS_IMPORT_AUTHORITY": "PASS" if a_ok else "FAIL",
        },
        "case_parent_contaminated_child_preload_fails_closed": {
            "returncode": b.returncode,
            "result": bd.get("result"),
            "FAIL_CLOSED": bd.get("result") == "FAIL_CLOSED",
        },
        "SUBPROCESS_IMPORT_AUTHORITY": "PASS" if (a_ok and bd.get("result") == "FAIL_CLOSED") else "FAIL",
    }


# ------------------------------------------------------------------ 4. portability
def portability_evidence() -> dict:
    head = git(["rev-parse", "HEAD"])
    cases: dict[str, dict] = {}

    for label, cwd in (("cwd_home", Path.home()), ("cwd_temp", Path(tempfile.gettempdir())),
                       ("cwd_c_root", Path("C:/").resolve())):
        p = child(BOOT_BY_PATH.format(boot=str(WORKTREE / "scripts" / "arc02_import_bootstrap.py")),
                  cwd=cwd, env=CONTAMINATED)
        d = json_line(p) or {}
        cases[label] = {
            "cwd": str(cwd),
            "returncode": p.returncode,
            "package_within_target": d.get("package_within_target"),
            "PASS": p.returncode == 0 and d.get("package_within_target") is True,
        }

    # fresh byte-copy of the V3 tree (pre-commit form of §14 fresh checkout)
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "fresh-v3-copy"
        subprocess.run([sys.executable, "-c",
                        f"import shutil; shutil.copytree({str(WORKTREE)!r}, {str(copy)!r}, symlinks=True)"],
                       check=True, capture_output=True)
        p = child(BOOT_BY_PATH.format(boot=str(copy / "scripts" / "arc02_import_bootstrap.py")),
                  cwd=Path(tempfile.gettempdir()), env=CONTAMINATED)
        d = json_line(p) or {}
        cases["fresh_v3_tree"] = {
            "root": str(copy),
            "returncode": p.returncode,
            "package_within_target": d.get("package_within_target"),
            "git_head": d.get("git_head"),
            "PASS": p.returncode == 0 and d.get("package_within_target") is True and d.get("git_head") == head,
        }

    all_ok = all(c["PASS"] for c in cases.values())
    return {
        "artifact": "ARC02_V3_PORTABILITY",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "ambient_contamination": {"PYTHONPATH": str(MAIN_SRC), "editable_pth": True},
        "cases": cases,
        "PORTABILITY": "PASS" if all_ok else "FAIL",
    }


# ------------------------------------------------------------------ 5. semantic diff
ECON_CONST_FILES = (
    "src/trading_bot/research/arc02/arc02_authority.py",
    "src/trading_bot/research/arc02/arc02_normalize.py",
    "src/trading_bot/research/arc02/arc02_pit.py",
)


def _literal_constants(source: str) -> dict:
    tree = ast.parse(source)
    out: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper() and "_" not in name:
            continue
        try:
            out[name] = ast.literal_eval(node.value)
        except Exception:
            continue
    return out


def semantic_diff_evidence() -> dict:
    commits = {"V1": V1_COMMIT, "V2": V2_COMMIT, "V3_worktree": None}
    spec_blobs: dict[str, str] = {}
    manifest_blobs: dict[str, str] = {}
    constants: dict[str, dict] = {}

    import hashlib

    for label, commit in commits.items():
        if commit is None:
            spec_bytes = (WORKTREE / "docs" / "arc02-prereg-01" / "ARC02_SPEC_V1.json").read_bytes()
            manifest_bytes = (WORKTREE / "docs" / "arc02-prereg-01" / "ARC02_MANIFEST_V1.json").read_bytes()
            consts: dict[str, object] = {}
            for rel in ECON_CONST_FILES:
                consts.update(_literal_constants((WORKTREE / rel).read_text(encoding="utf-8")))
        else:
            spec_bytes = subprocess.check_output(["git", "show", f"{commit}:docs/arc02-prereg-01/ARC02_SPEC_V1.json"], cwd=str(WORKTREE))
            manifest_bytes = subprocess.check_output(["git", "show", f"{commit}:docs/arc02-prereg-01/ARC02_MANIFEST_V1.json"], cwd=str(WORKTREE))
            consts = {}
            for rel in ECON_CONST_FILES:
                src = subprocess.check_output(["git", "show", f"{commit}:{rel}"], cwd=str(WORKTREE)).decode("utf-8")
                consts.update(_literal_constants(src))
        spec_blobs[label] = hashlib.sha256(spec_bytes).hexdigest()
        manifest_blobs[label] = hashlib.sha256(manifest_bytes).hexdigest()
        constants[label] = consts

    spec_equal = len(set(spec_blobs.values())) == 1
    manifest_equal = len(set(manifest_blobs.values())) == 1
    consts_equal = constants["V1"] == constants["V2"] == constants["V3_worktree"]

    dataset_manifest = json.loads(
        (WORKTREE / "docs" / "arc02-prereg-01" / "ARC02_MANIFEST_V1.json").read_text(encoding="utf-8")
    )
    dataset_recorded = dataset_manifest["data_binding"]["dataset_sha256"]

    econ_diff = 0 if (spec_equal and manifest_equal and consts_equal and dataset_recorded == DATASET_SHA) else 1

    return {
        "artifact": "ARC02_V3_SEMANTIC_DIFF",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "compared": {
            "V1_COMMIT": V1_COMMIT,
            "V2_COMMIT": V2_COMMIT,
            "V3_WORKTREE_CONTENT": "(uncommitted worktree content at evidence time)",
        },
        "SPEC_SHA256": spec_blobs,
        "SPEC_SHA256_V3_EFFECTIVE": spec_blobs["V3_worktree"],
        "SPEC_SHA256_REQUIRED": SPEC_SHA,
        "SPEC_IDENTITY_ACROSS_V1_V2_V3": spec_equal,
        "MANIFEST_SHA256": manifest_blobs,
        "MANIFEST_SHA256_V3_EFFECTIVE": manifest_blobs["V3_worktree"],
        "MANIFEST_SHA256_REQUIRED": MANIFEST_SHA,
        "MANIFEST_IDENTITY_ACROSS_V1_V2_V3": manifest_equal,
        "DATASET_SHA256_RECORDED": dataset_recorded,
        "DATASET_SHA256_REQUIRED": DATASET_SHA,
        "FROZEN_ECON_CONSTANTS_IDENTICAL": consts_equal,
        "frozen_constant_comparison": {},
        "frozen_constants_digest_across_v1_v2_v3": {
            label: hashlib.sha256(
                json.dumps(constants[label], sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            for label in constants
        },
        "ECONOMIC_DIFF_COUNT": econ_diff,
        "verdict": "ECONOMIC_IDENTITY_PRESERVED" if econ_diff == 0 else "ECONOMIC_DRIFT",
    }


# ------------------------------------------------------------------ 6. data binding
def data_binding_evidence() -> dict:
    out_tmp = Path(tempfile.gettempdir()) / "arc02_v3_data_binding_tmp.json"
    r = subprocess.run(
        [PY, "scripts/verify_arc02_data_authority.py",
         "--target", str(WORKTREE), "--data-root", str(CERTIFIED_DATA_ROOT),
         "--skip-git", "--out", str(out_tmp)],
        cwd=str(WORKTREE), env=CONTAMINATED, capture_output=True, text=True,
    )
    report = {}
    if out_tmp.exists():
        try:
            report = json.loads(out_tmp.read_text(encoding="utf-8"))
        except Exception:
            report = {"raw_head": out_tmp.read_text(encoding="utf-8", errors="replace")[:2000]}
    checks = {c["check"]: c["pass"] for c in report.get("checks", [])}
    return {
        "artifact": "ARC02_V3_DATA_BINDING",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "certified_explicit_data_root": str(CERTIFIED_DATA_ROOT),
        "audited_target": str(WORKTREE),
        "verifier_returncode": r.returncode,
        "verdict": report.get("verdict"),
        "checks": checks,
        "checks_failed": report.get("failed_checks"),
        "full_report": report,
        "DATA_BINDING": "PASS" if report.get("verdict") == "PASS" else "FAIL",
        "WRONG_DATA_ROOT_FAIL_CLOSED": "PASS" if checks.get("WRONG_ROOT_FAILS_CLOSED") else "FAIL",
        "EMPTY_DATA_ROOT_FAIL_CLOSED": "PASS" if checks.get("EMPTY_ROOT_FAILS_CLOSED") else "FAIL",
        "PIT_TARGET_AUTHORITY": "PASS" if (
            checks.get("PIT_BATTERY") and checks.get("PYTHON_IMPORT_AUTHORITY")
            and checks.get("TEST_TARGET_EQUALS_AUDITED")
        ) else "FAIL",
        "stderr_tail": (r.stderr[-1500:] if r.stderr else None),
    }


# ------------------------------------------------------------------ 7. Track B regression (§18)
def track_b_evidence() -> dict:
    r = subprocess.run(
        [PY, "-m", "pytest",
         "tests/unit/research/test_discovery_view.py",
         "tests/unit/research/test_discovery_execution.py",
         "-q", "--no-header"],
        cwd=str(WORKTREE), env=CONTAMINATED, capture_output=True, text=True,
    )
    tail = (r.stdout or "")[-400:]
    return {
        "artifact": "ARC02_V3_TRACK_B_REGRESSION",
        "builder_role": "BUILDER_CROSSCHECK_NOT_INDEPENDENT_VERIFICATION",
        "scope": "existing Track B components only - no expansion, no new capability",
        "components": [
            "StrategyFailureDiagnostics", "HypothesisGenerator", "ResearchBudget",
            "ExternalStrategyIntake", "MarketIntelligenceProvider",
        ],
        "test_files": ["tests/unit/research/test_discovery_view.py",
                       "tests/unit/research/test_discovery_execution.py"],
        "returncode": r.returncode,
        "output_tail": tail,
        "TRACK_B_REGRESSION": "PASS" if r.returncode == 0 else "FAIL",
    }


# ------------------------------------------------------------------ main
def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    results["import_authority"] = import_authority_evidence()
    write("ARC02_V3_IMPORT_AUTHORITY.json", results["import_authority"])

    results["pytest"] = pytest_authority_evidence()
    write("ARC02_V3_PYTEST_AUTHORITY.json", results["pytest"])

    results["subprocess"] = subprocess_authority_evidence_standalone()
    write("ARC02_V3_SUBPROCESS_AUTHORITY.json", results["subprocess"])

    results["portability"] = portability_evidence()
    write("ARC02_V3_PORTABILITY.json", results["portability"])

    results["semantic"] = semantic_diff_evidence()
    write("ARC02_V3_SEMANTIC_DIFF.json", results["semantic"])

    results["data_binding"] = data_binding_evidence()
    write("ARC02_V3_DATA_BINDING.json", results["data_binding"])

    results["track_b"] = track_b_evidence()
    write("ARC02_V3_TRACK_B_REGRESSION.json", results["track_b"])

    gates = {
        "PYTHON_IMPORT_AUTHORITY": results["import_authority"]["PYTHON_IMPORT_AUTHORITY"],
        "TEST_TARGET_AUDITED_TARGET": results["import_authority"]["TEST_TARGET_AUDITED_TARGET"],
        "EDITABLE_PTH_ATTACK": results["import_authority"]["EDITABLE_PTH_ATTACK"],
        "PRELOADED_WRONG_MODULE_ATTACK": results["import_authority"]["PRELOADED_WRONG_MODULE_ATTACK"],
        "PYTEST_AUTHORITY": results["pytest"]["PYTEST_AUTHORITY"],
        "PYTEST_WRONG_IMPORT_FAIL_CLOSED": results["pytest"]["PYTEST_WRONG_IMPORT_FAIL_CLOSED"],
        "SUBPROCESS_IMPORT_AUTHORITY": results["subprocess"]["SUBPROCESS_IMPORT_AUTHORITY"],
        "ARBITRARY_CWD": "PASS" if all(
            c["PASS"] for k, c in results["portability"]["cases"].items() if k.startswith("cwd_")
        ) else "FAIL",
        "PORTABILITY": results["portability"]["PORTABILITY"],
        "DATA_BINDING": results["data_binding"]["DATA_BINDING"],
        "WRONG_DATA_ROOT_FAIL_CLOSED": results["data_binding"]["WRONG_DATA_ROOT_FAIL_CLOSED"],
        "EMPTY_DATA_ROOT_FAIL_CLOSED": results["data_binding"]["EMPTY_DATA_ROOT_FAIL_CLOSED"],
        "PIT_TARGET_AUTHORITY": results["data_binding"]["PIT_TARGET_AUTHORITY"],
        "TRACK_B_REGRESSION": results["track_b"]["TRACK_B_REGRESSION"],
        "ECONOMIC_DIFF_COUNT": results["semantic"]["ECONOMIC_DIFF_COUNT"],
    }
    write("ARC02_V3_BUILDER_CROSSCHECK_GATES.json", gates)

    failed = [k for k, v in gates.items() if v not in ("PASS", 0)]
    print(json.dumps(gates, indent=2))
    print("FAILED_GATES:", failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
