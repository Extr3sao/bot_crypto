import importlib, os, subprocess, sys
from pathlib import Path
import json

ROOT = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-v2-repair-01').resolve()
MAIN_SRC = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/src').resolve()


def git_head(root: Path) -> str:
    return subprocess.check_output(['git','rev-parse','HEAD'], cwd=str(root), text=True).strip()


env_git_head = git_head(ROOT)

# 1. defect reproduction still observable without bootstrap
prep = {"cwd": str(ROOT), "expected_commit": env_git_head}
if "trading_bot" in sys.modules:
    del sys.modules["trading_bot"]
m = importlib.import_module("trading_bot")
prep["trading_bot_file"] = getattr(m, "__file__", None)
prep["resolves_to_worktree_before_bootstrap"] = str(Path(m.__file__).resolve()) == str((ROOT / "src" / "trading_bot" / "__init__.py").resolve())
prep["resolves_to_main_before_bootstrap"] = str(Path(m.__file__).resolve()) == str(MAIN_SRC / "trading_bot" / "__init__.py")

# 2. after bootstrap, authority must hold even with PYTHONPATH contaminated
env = os.environ.copy()
env["PYTHONPATH"] = str(MAIN_SRC)
env["ARC02_EXPECTED_COMMIT"] = env_git_head
r = subprocess.run(
    [sys.executable, "-c", """
import os, sys
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02()
print('PKG', ev.package_file)
print('HEAD', ev.git_head)
for m in ev.critical_module_files:
    print('MOD', m)
"""],
    cwd=str(ROOT), env=env, text=True, capture_output=True,
)

bootstrap_out = {}
if r.returncode == 0:
    for line in r.stdout.splitlines():
        if line.startswith("PKG "): bootstrap_out["pkg"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "): bootstrap_out["head"] = line.split(" ", 1)[1]
        elif line.startswith("MOD "): bootstrap_out.setdefault("mods", []).append(line.split(" ", 1)[1])

post = {
    "bootstrap_returncode": r.returncode,
    "bootstrap_stderr_tail": r.stderr[-1500:] if r.stderr else None,
    **bootstrap_out,
    "bootstrap_pkg_within_target": False,
    "bootstrap_mods_within_target": [],
}

if "pkg" in bootstrap_out:
    pkg = Path(bootstrap_out["pkg"]).resolve()
    target_root = ROOT.resolve()
    post["bootstrap_pkg_within_target"] = pkg.is_relative_to(target_root)
    post["bootstrap_mods_within_target"] = [
        Path(m).resolve().is_relative_to(target_root)
        for m in bootstrap_out.get("mods", [])
    ]

# 3. fail-closed wrong-commit
wrong = subprocess.run(
    [sys.executable, "-c", """
import os
os.environ["ARC02_EXPECTED_COMMIT"] = "0" * 40
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02()
    print("UNEXPECTED_OK")
except Exception as e:
    print("EXPECTED_FAIL", type(e).__name__, str(e)[:300])
"""],
    cwd=str(ROOT),
    env={**os.environ, "PYTHONPATH": str(MAIN_SRC)},
    text=True,
    capture_output=True,
)
post["wrong_commit_returncode"] = wrong.returncode
post["wrong_commit_output"] = wrong.stdout.strip()
post["wrong_commit_error_tail"] = wrong.stderr[-1500:] if wrong.stderr else None

result = {
    "defect_reproduction_before_bootstrap": prep,
    "authority_after_bootstrap_under_contamination": post,
}

Path("ARC02_TEST_TARGET_AUTHORITY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print("WROTE ARC02_TEST_TARGET_AUTHORITY.json")
print("defect_reproduced_before_bootstrap", prep["resolves_to_main_before_bootstrap"] or (not prep["resolves_to_worktree_before_bootstrap"]))
print("bootstrap_returncode", post["bootstrap_returncode"])
print("pkg_within_target", post["bootstrap_pkg_within_target"])
print("mods_within_target", post["bootstrap_mods_within_target"])
print("wrong_commit_returncode", post["wrong_commit_returncode"])
print("wrong_commit_expected_fail", post["wrong_commit_output"].startswith("EXPECTED_FAIL"))
