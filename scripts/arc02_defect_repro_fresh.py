import importlib, os, subprocess, sys
from pathlib import Path

worktree = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-v2-repair-01').resolve()
main_src = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/src').resolve()

out = {
    "cwd": str(worktree),
    "expected_commit": "3ebf5f54bba84300663a9de7f6b05c5b583bc9c6",
    "main_src": str(main_src),
    "worktree_src": str(worktree / "src"),
    "sys_path_has_main_src": str(main_src) in sys.path,
    "sys_path_has_worktree_src": str(worktree / "src") in sys.path,
}

if "trading_bot" in sys.modules:
    del sys.modules["trading_bot"]

m = importlib.import_module("trading_bot")
out["trading_bot_file"] = getattr(m, "__file__", None)
out["resolves_to_worktree"] = str(Path(m.__file__).resolve()) == str((worktree / "src" / "trading_bot" / "__init__.py").resolve())
out["resolves_to_main"] = str(Path(m.__file__).resolve()) == str(main_src / "trading_bot" / "__init__.py")
out["defect_reproduced"] = out["resolves_to_main"] or (not out["resolves_to_worktree"] and str(main_src) in sys.path)

Path("ARC02_IMPORT_CONTAMINATION_REPRODUCTION.json").write_text(
    __import__("json").dumps(out, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print("DEFECT_REPRODUCED", out["defect_reproduced"])
print("trading_bot_file", out["trading_bot_file"])
print("resolves_to_main", out["resolves_to_main"])
print("resolves_to_worktree", out["resolves_to_worktree"])
