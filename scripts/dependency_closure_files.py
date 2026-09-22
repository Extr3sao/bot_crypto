"""CP-PO-003 Phase 1/2 — file-granularity dependency closure (read-only).

Run in a tree where the full source inventory exists on disk (primary or
repair-with-staged-files). Walks imports of every TRACKED .py root under
src/, scripts/, tests/ to a fixed point, resolving intra-package relative
imports and absolute trading_bot.* imports to FILES. Reports:

  REACHABLE_TRACKED   — needed and already in Git
  REACHABLE_UNTRACKED — needed but MISSING_FROM_GIT (candidates to add)
  DYNAMIC_IMPORTS     — importlib targets found in reachable files
Never modifies anything.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# Optional argv[1]: repo root to analyze (default: the tree containing this script).
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SRC = REPO / "src"


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return set(out.stdout.splitlines())


def on_disk_py() -> set[str]:
    """All .py files under src/, as REPO-RELATIVE posix keys."""
    return {p.relative_to(REPO).as_posix() for p in SRC.rglob("*.py")}


def mod_candidates(mod: str) -> list[str]:
    parts = mod.split(".")
    base = "src/" + "/".join(parts)
    return [base + ".py", base + "/__init__.py"]


def resolve_file(mod: str, universe: set[str]) -> str | None:
    """Longest-prefix file resolution for a dotted trading_bot name."""
    parts = mod.split(".")
    while parts:
        for cand in mod_candidates(".".join(parts)):
            if cand in universe:
                return cand
        parts = parts[:-1]
    return None


def imports_of(path: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (runtime static, TYPE_CHECKING-only static, dynamic literals)."""
    static: set[str] = set()
    typing_only: set[str] = set()
    dynamic: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return static, typing_only, dynamic

    def in_type_checking(node: ast.stmt) -> bool:
        for _parent in ast.walk(tree):  # cheap: find If whose test is TYPE_CHECK
            pass
        return False

    # identify TYPE_CHECKING blocks by scanning top-level and nested If nodes
    tc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            t = node.test
            names = []
            if isinstance(t, ast.Name):
                names = [t.id]
            elif isinstance(t, ast.Attribute):
                names = [t.attr]
            if any(n in {"TYPE_CHECKING", "typing", "t"} for n in names):
                for sub in ast.walk(node):
                    tc_nodes.add(id(sub))

    for node in ast.walk(tree):
        is_tc = id(node) in tc_nodes
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("trading_bot"):
                    (typing_only if is_tc else static).add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mods: set[str] = set()
            if node.level and node.level > 0:
                if node.module:
                    mods.add(node.module)
                else:
                    mods.update(a.name for a in node.names)
            elif node.module and node.module.startswith("trading_bot"):
                mods.add(node.module)
                mods.update(f"{node.module}.{a.name}" for a in node.names if a.name.isidentifier())
            for m in mods:
                (typing_only if is_tc else static).add(m)
        elif isinstance(node, ast.Call):
            fn = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if fn in {"import_module", "__import__"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        dynamic.add(arg.value)
    return static, typing_only, dynamic


def main() -> None:
    tracked = tracked_files()
    universe = on_disk_py()  # files that physically exist in src/ (this tree)
    roots = sorted(
        f
        for f in tracked
        if (f.startswith("src/") or f.startswith("scripts/") or f.startswith("tests/"))
        and f.endswith(".py")
    )
    worklist = list(roots)
    seen: set[str] = set()
    dynamic_all: set[str] = set()
    unresolved_runtime: dict[str, set[str]] = {}
    unresolved_typing: set[str] = set()
    while worklist:
        rel = worklist.pop()
        if rel in seen:
            continue
        seen.add(rel)
        static, typing_only, dynamic = imports_of(REPO / rel)
        dynamic_all |= dynamic
        for mod in static:
            f = resolve_file(mod, universe)
            if f:
                if f not in seen:
                    worklist.append(f)
            else:
                unresolved_runtime.setdefault(mod, set()).add(rel)
        for mod in typing_only:
            if not resolve_file(mod, universe):
                unresolved_typing.add(mod)

    reachable_tracked = sorted(f for f in seen if f in tracked and f.startswith("src/"))
    reachable_untracked = sorted(f for f in seen if f not in tracked and f.startswith("src/"))
    print(f"files walked: {len(seen)}  (roots incl. tests)")
    print(f"REACHABLE_TRACKED src files:   {len(reachable_tracked)}")
    print(f"REACHABLE_UNTRACKED src files: {len(reachable_untracked)}")
    print("\n=== MISSING_FROM_GIT (needed by tracked code, not in git) ===")
    for f in reachable_untracked:
        print("  ", f)
    print("\n=== DYNAMIC import targets found ===")
    for m in sorted(dynamic_all):
        print("  ", m)
    print("\n=== UNRESOLVED RUNTIME imports (no file anywhere) ===")
    for m, importers in sorted(unresolved_runtime.items()):
        print(f"  {m}   <- {sorted(importers)[:2]}")
    print("\n=== UNRESOLVED TYPE_CHECKING imports (runtime-safe) ===")
    for m in sorted(unresolved_typing):
        print("  ", m)


if __name__ == "__main__":
    main()
