"""ARC02_V3 defect reproduction (pre-repair).

Reproduces the independently demonstrated V2 import-authority failure using the
committed verifier evidence as the authority for what "failed" means:

  F1  plain python under ambient contamination resolves trading_bot to the MAIN
      checkout (V2_CONTAMINATION_DEFENCE = FAIL as recorded in
      ARC02_V2_IMPORT_AUTHORITY_AUDIT.json).
  F2  the V2 bootstrap SILENTLY REPLACES an already-imported wrong first-party
      module and continues as PASS (violates the never-replace contract).
  F3  V2 path-identity comparison is not canonical: the V2 evidence emitter
      normalizes to forward slashes while V2 recomputation helpers compare with
      ``str.startswith(str(Path(...).resolve()))`` (backslash form on Windows),
      so equivalent TARGET paths recompute as OUTSIDE the target - exactly the
      committed contradiction authority_package_within_target=false with a
      target-resident authority_package_file.

This script is builder-side evidence collection only. It does NOT import
trading_bot in its own process; all contaminated imports happen in child
processes.

Output: docs/external-audit-01/arc02-prereg-v3-repair-01/ARC02_V3_IMPORT_DEFECT_REPRODUCTION.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
MAIN_REPO = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
MAIN_SRC = MAIN_REPO / "src"
BASE_COMMIT = "6df96c66ac4ea2fe5413cf896befc1ce997cd6e5"
ART_DIR = WORKTREE / "docs" / "external-audit-01" / "arc02-prereg-v3-repair-01"

VENV = MAIN_REPO / ".venv" / "Scripts" / "python.exe"
PY = str(VENV) if VENV.exists() else sys.executable


def site_packages() -> list[str]:
    out = subprocess.run(
        [PY, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return [out]


def pth_inventory(site_dirs: list[str]) -> list[dict[str, object]]:
    inv: list[dict[str, object]] = []
    for d in site_dirs:
        sdir = Path(d)
        if not sdir.is_dir():
            continue
        for pth in sorted(sdir.glob("*.pth")):
            entry: dict[str, object] = {
                "path": str(pth),
                "content_head": pth.read_text(encoding="utf-8", errors="replace")[:400],
            }
            if pth.name.startswith("__editable__"):
                entry["kind"] = "editable"
                first_line = pth.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                entry["injects_first_party"] = bool(first_line) and "src" in first_line[0]
            inv.append(entry)
    return inv


CHILD_F1 = r"""
import json, os, sys
import importlib
m = importlib.import_module("trading_bot")
f = getattr(m, "__file__", None)
out = {
    "child_cwd": os.getcwd(),
    "child_pythonpath": os.environ.get("PYTHONPATH"),
    "trading_bot_file": f,
    "sys_path": sys.path,
}
print("JSON:" + json.dumps(out))
"""

CHILD_F2 = r"""
import json, os, sys
from pathlib import Path
# Import-order attack: import trading_bot BEFORE the ARC-02 bootstrap is invoked.
# With PYTHONPATH=main_src, this binds the MAIN checkout package into sys.modules.
import trading_bot
from pathlib import Path
target_root = Path(os.environ["V3_TARGET_ROOT"]).resolve()
main_src = Path(os.environ["V3_MAIN_SRC"]).resolve()
before = getattr(sys.modules.get("trading_bot"), "__file__", None)
result = {"preloaded_trading_bot_file": before, "preloaded_is_main": False}
if before:
    result["preloaded_is_main"] = Path(before).resolve() == (main_src / "trading_bot" / "__init__.py").resolve()
sys.path.insert(0, str(target_root))
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    ev = bootstrap_arc02(target_root=target_root, expected_commit=os.environ["V3_EXPECTED_COMMIT"])
    after = getattr(sys.modules.get("trading_bot"), "__file__", None)
    result.update({
        "bootstrap_result": "PASS",
        "post_bootstrap_trading_bot_file": after,
        "silently_replaced_wrong_preload": bool(before) and str(Path(before).resolve()) != str(Path(after).resolve()) if after else None,
        "package_file": ev.package_file,
        "critical_module_files": list(ev.critical_module_files),
        "sys_path_after": sys.path,
    })
except Exception as exc:
    result.update({"bootstrap_result": "FAIL_CLOSED", "error": f"{type(exc).__name__}: {exc}"})
print("JSON:" + json.dumps(result))
"""

CHILD_F3 = r"""
import json, os, sys
from pathlib import Path
target_root = Path(os.environ["V3_TARGET_ROOT"]).resolve()
sys.path.insert(0, str(target_root))
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02(target_root=target_root, expected_commit=os.environ["V3_EXPECTED_COMMIT"])
pkg = ev.package_file
# V2 helper-script idiom: naive string startswith against Path.resolve() text
v2_style_startswith = str(pkg).startswith(str(target_root))
# pathlib-native containment (separator-aware)
v3_style_pathlib = Path(pkg).resolve().is_relative_to(target_root.resolve())
out = {
    "package_file_emitted": pkg,
    "target_root_resolved": str(target_root),
    "v2_style_startswith": v2_style_startswith,
    "v3_style_pathlib_is_relative_to": v3_style_pathlib,
    "separator_of_emitted": ("\\" in pkg),
    "separator_of_resolved_target": ("\\" in str(target_root)),
}
print("JSON:" + json.dumps(out))
"""


def run_child(code: str, env_extra: dict[str, str], cwd: Path) -> tuple[int, str, str]:
    env = {**os.environ, **env_extra}
    env.pop("PYTHONPATH", None) if env_extra.get("PYTHONPATH") is None else None
    r = subprocess.run([PY, "-c", code], cwd=str(cwd), env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def extract_json(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    return None


def main() -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    site_dirs = site_packages()
    user_site = subprocess.run(
        [PY, "-c", "import site; print(site.getusersitepackages())"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    env_record = {
        "python_executable": PY,
        "repro_cwd": str(WORKTREE),
        "base_commit_under_repair": BASE_COMMIT,
        "sys_path_parent": sys.path,
        "site_packages": site_dirs,
        "user_site_packages": user_site,
        "pth_files": pth_inventory(site_dirs),
        "pythonpath_env_at_parent": os.environ.get("PYTHONPATH"),
    }

    # ---------------- F1: plain python, contaminated, no bootstrap
    f1_env = {"PYTHONPATH": str(MAIN_SRC)}
    rc, out, err = run_child(CHILD_F1, f1_env, WORKTREE)
    f1 = extract_json(out) or {"stdout_head": out[:800], "stderr_tail": err[-800:]}
    f1["returncode"] = rc
    f1["env_pythonpath"] = str(MAIN_SRC)
    f1["resolves_to_main_checkout"] = bool(
        f1.get("trading_bot_file")
        and Path(str(f1["trading_bot_file"])).resolve() == (MAIN_SRC / "trading_bot" / "__init__.py").resolve()
    )

    # F1b: arbitrary cwd (defect must be cwd-independent)
    rc, out, err = run_child(CHILD_F1, f1_env, Path(os.environ.get("TEMP", str(WORKTREE))).resolve())
    f1b = extract_json(out) or {}
    f1b["returncode"] = rc
    f1b["resolves_to_main_checkout"] = bool(
        f1b.get("trading_bot_file")
        and Path(str(f1b["trading_bot_file"])).resolve() == (MAIN_SRC / "trading_bot" / "__init__.py").resolve()
    )

    # ---------------- F2: wrong module preloaded, then V2 bootstrap (silent replace?)
    f2_env = {
        "PYTHONPATH": str(MAIN_SRC),
        "V3_TARGET_ROOT": str(WORKTREE),
        "V3_MAIN_SRC": str(MAIN_SRC),
        "V3_EXPECTED_COMMIT": BASE_COMMIT,
    }
    rc, out, err = run_child(CHILD_F2, f2_env, WORKTREE)
    f2 = extract_json(out) or {"stdout_head": out[:1200], "stderr_tail": err[-1500:]}
    f2["returncode"] = rc

    # ---------------- F3: canonical-comparison contradiction on V2 evidence
    rc, out, err = run_child(CHILD_F3, f2_env, WORKTREE)
    f3 = extract_json(out) or {"stdout_head": out[:1200], "stderr_tail": err[-1500:]}
    f3["returncode"] = rc

    defect_reproduced = bool(
        f1.get("resolves_to_main_checkout")
        and f1b.get("resolves_to_main_checkout")
        and f2.get("bootstrap_result") == "PASS"
        and f2.get("silently_replaced_wrong_preload") is True
        and f3.get("v2_style_startswith") is False
        and f3.get("v3_style_pathlib_is_relative_to") is True
    )

    artifact = {
        "artifact": "ARC02_V3_IMPORT_DEFECT_REPRODUCTION",
        "prerepair": True,
        "authority": {
            "v2_verifier_evidence_commit": "00063237de21e3ed9273d84293f129f75003f126",
            "v2_verdict": "FAIL_INDEPENDENT_PREREG_VERIFICATION_V2",
            "v2_recorded": {
                "V2_CONTAMINATION_DEFENCE": "FAIL",
                "PYTHON_IMPORT_AUTHORITY": "FAIL",
            },
        },
        "environment": env_record,
        "F1_plain_python_contaminated": f1,
        "F1b_plain_python_contaminated_arbitrary_cwd": f1b,
        "F2_v2_bootstrap_silent_replace": f2,
        "F3_v2_path_identity_comparison": f3,
        "DEFECT_REPRODUCED": defect_reproduced,
        "notes": [
            "F1+F1b reproduce the committed V2 verifier observation: plain python under "
            "ambient contamination imports trading_bot from the MAIN checkout.",
            "F2 demonstrates the V2 mechanism silently REPLACES an already-imported wrong "
            "first-party module and continues as PASS.",
            "F3 demonstrates the V2 path-identity comparison defect: the V2 evidence emitter "
            "canonicalizes to forward slashes while V2 helper recomputation used naive "
            "startswith against Path.resolve() text (backslashes on Windows), so an "
            "equivalent TARGET path recomputes as outside-target. This matches the committed "
            "verifier contradiction authority_package_within_target=false with a "
            "target-resident authority_package_file.",
        ],
    }
    out_path = ART_DIR / "ARC02_V3_IMPORT_DEFECT_REPRODUCTION.json"
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("WROTE", out_path)
    print("F1 resolves_to_main_checkout:", f1.get("resolves_to_main_checkout"))
    print("F1b arbitrary_cwd resolves_to_main_checkout:", f1b.get("resolves_to_main_checkout"))
    print("F2 bootstrap_result:", f2.get("bootstrap_result"), "| silently_replaced:", f2.get("silently_replaced_wrong_preload"))
    print("F3 v2_style_startswith:", f3.get("v2_style_startswith"), "| pathlib:", f3.get("v3_style_pathlib_is_relative_to"))
    print("DEFECT_REPRODUCED:", defect_reproduced)
    return 0 if defect_reproduced else 1


if __name__ == "__main__":
    raise SystemExit(main())
