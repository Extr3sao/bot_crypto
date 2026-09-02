"""CP-PO-003 Phase 1 — compute the full transitive internal-import closure.

Roots: every tracked .py file under src/, scripts/, tests/ of THIS worktree
(the committed tree). Recursively resolve every ``trading_bot.*`` import to a
file in the worktree until fixed point. Output the sets required by the phase:

    DIRECT_REQUIRED_MODULES / TRANSITIVE_REQUIRED_MODULES
    MISSING_FROM_GIT / ALREADY_TRACKED

Also collects dynamic-import string literals (importlib/import_module/__import__
arguments) containing 'trading_bot'.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return set(out.stdout.splitlines())


def module_to_paths(mod: str) -> list[str]:
    parts = mod.split(".")
    base = "src/" + "/".join(parts)
    return [base + ".py", base + "/__init__.py"]


def resolve(mod: str, tracked: set[str]) -> str | None:
    for cand in module_to_paths(mod):
        if cand in tracked:
            return cand
    # untracked but present on disk (repair worktree staging area)
    for cand in module_to_paths(mod):
        if (REPO / cand).exists():
            return cand
    return None


def parse_imports(path: Path) -> tuple[set[str], set[str]]:
    """Return (static trading_bot modules, dynamic string literals)."""
    static: set[str] = set()
    dynamic: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return static, dynamic
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("trading_bot"):
                    static.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("trading_bot"):
                static.add(node.module)
            for a in node.names:
                if node.module and node.module.startswith("trading_bot"):
                    static.add(f"{node.module}.{a.name}")
        elif isinstance(node, ast.Call):
            fname = ""
            if isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            elif isinstance(node.func, ast.Name):
                fname = node.func.id
            if fname in {"import_module", "__import__", "importlib_import_module"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.startswith("trading_bot"):
                            dynamic.add(arg.value)
    return static, dynamic


def main() -> None:
    tracked = tracked_files()
    roots_py = sorted(
        f for f in tracked
        if (f.startswith("src/") or f.startswith("scripts/") or f.startswith("tests/"))
        and f.endswith(".py")
    )
    print(f"roots: {len(roots_py)} tracked .py files under src/ scripts/ tests/")

    direct: set[str] = set()
    transitive: set[str] = set()
    missing: dict[str, list[str]] = {}  # module -> importers
    dynamic_missing: set[str] = set()

    worklist = list(roots_py)
    seen: set[str] = set()
    while worklist:
        rel = worklist.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = REPO / rel
        static, dynamic = parse_imports(path)
        for mod in static:
            base_mod = mod
            # record direct imports from roots only
            direct.add(base_mod)
            resolved = resolve(mod, tracked)
            if resolved is None:
                missing.setdefault(mod, []).append(rel)
                continue
            transitive.add(mod)
            if resolved not in seen:
                worklist.append(resolved)
        for mod in dynamic:
            resolved = resolve(mod, tracked)
            if resolved is None:
                dynamic_missing.add(mod)

    # classify
    already = sorted(m for m in transitive if module_to_paths(m)[0] in tracked)
    print("\n=== DIRECT_REQUIRED_MODULES (unique, from all files incl. transitive) ===")
    print(f"{len(direct)}")
    print("\n=== TRANSITIVE_REQUIRED_MODULES (resolved) ===")
    print(f"{len(transitive)}")
    print("\n=== MISSING_FROM_GIT (imported by tracked code, untracked and absent) ===")
    for m in sorted(missing):
        print(f"  {m}   <- {sorted(set(missing[m]))[:3]}")
    print(f"total missing: {len(missing)}")
    if dynamic_missing:
        print("\n=== DYNAMIC IMPORTS MISSING ===")
        for m in sorted(dynamic_missing):
            print("  ", m)

    # Which tracked files exist but are NOT reachable? (informational)
    print("\n=== summary ===")
    print(f"files walked: {len(seen)}")
    print(f"tracked py in closure: {len([f for f in seen if f.startswith('src/')])}")


if __name__ == "__main__":
    main()
