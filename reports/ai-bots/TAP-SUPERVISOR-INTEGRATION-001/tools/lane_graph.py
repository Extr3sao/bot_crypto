"""Static reachability of the supervisor lane, read from Git objects (no checkout needed).

The audit has to answer "what does the supervisor actually need at runtime?" without
confusing "its tests pass" with "something calls it".  So this walks imports from the
entry points that the lane documents, resolves only ``trading_bot`` modules, and stops at
the standard library and third-party packages.  A module is *reachable* when an entry point
can import it by following imports, nothing more: a docstring calling it "production" is
not evidence.

    python reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/tools/lane_graph.py --json OUT

Every fact it prints is a Git read; the JSON is the artefact the audit cites.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from collections import defaultdict
from pathlib import Path

LANE = "codepaper/supervisor-001"
MAIN = "main"
BASE = "1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22"

#: The scripts the lane's own documentation tells an operator to run.  Anything reached
#: only from a test or from another script is not part of this closure.
SEEDS = (
    # The supervisor's own default child: omitting it would have hidden the whole session
    # runtime (``vision/prospective.py``) behind a script nobody listed.
    "scripts/def_run_019_prospective_run.py",
    "scripts/paper_supervisor.py",
    "scripts/paper_supervisor_campaign.py",
    "scripts/paper_supervisor_verify.py",
    "scripts/paper_lock_campaign.py",
    "scripts/paper_lock_campaign_verify.py",
    "scripts/paper_session_status.py",
    "scripts/start_paper_trading.py",
)

_cache: dict[tuple[str, str], str] = {}


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=Path(__file__).resolve().parents[4], capture_output=True, check=False)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def blob(ref: str, path: str) -> str:
    key = (ref, path)
    if key not in _cache:
        _cache[key] = git("show", f"{ref}:{path}")
    return _cache[key]


def tree(ref: str) -> list[str]:
    return [p for p in git("ls-tree", "-r", "--name-only", ref).splitlines() if p]


def module_map(paths: list[str]) -> dict[str, str]:
    """``src/trading_bot/a/b.py`` → ``trading_bot.a.b``."""

    mapping: dict[str, str] = {}
    for path in paths:
        if not path.startswith("src/") or not path.endswith(".py"):
            continue
        rel = path[len("src/") : -3].replace("/", ".")
        mapping[rel[: -len(".__init__")] if rel.endswith(".__init__") else rel] = path
    return mapping


def imports_of(path: str, source: str, modules: dict[str, str]) -> set[str]:
    """Internal imports of one file, with relative imports resolved properly.

    The package of ``a/b/c.py`` and of ``a/b/__init__.py`` is the same ``a.b``; a
    ``from .x import y`` (level 1) therefore means ``a.b.x`` in both.  An earlier version
    counted the module itself as the base, silently dropped every relative import, and
    under-reported the runtime delta by one module (``economic_recovery/costs.py``) — the
    import smoke on the migrated tree is what caught it.
    """

    parts = path[len("src/") :].split("/")[:-1] if path.startswith("src/") else []
    package_parts = parts
    found: set[str] = set()
    try:
        tree_ = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    found.add(modules[alias.name])
        elif isinstance(node, ast.ImportFrom):
            if node.level and package_parts:
                up = node.level - 1
                base_parts = package_parts[: len(package_parts) - up] if up else package_parts
                base = ".".join(base_parts)
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if target in modules:
                found.add(modules[target])
            for alias in node.names:
                sub = f"{target}.{alias.name}"
                if sub in modules:
                    found.add(modules[sub])
    return found


def closure(seeds: list[str], modules: dict[str, str], paths: set[str]) -> set[str]:
    seen: set[str] = set()
    queue = [s for s in seeds if s in paths]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for dep in imports_of(path, blob(LANE, path), modules):
            if dep not in seen:
                queue.append(dep)
    return seen


def test_importers(modules: dict[str, str], paths: set[str]) -> dict[str, list[str]]:
    """Which test files import each module — the difference between used and exercised."""

    by_module: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if not path.startswith("tests/") or not path.endswith(".py"):
            continue
        for dep in imports_of(path, blob(LANE, path), modules):
            by_module[dep].append(path)
    return by_module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_out", default=None)
    parser.add_argument(
        "--broad",
        action="store_true",
        help="seed from every scripts/*.py, not only the supervisor entry points",
    )
    args = parser.parse_args()

    lane_paths = set(tree(LANE))
    main_paths = set(tree(MAIN))
    modules = module_map(sorted(lane_paths))

    #: A module reachable from *some* script is research tooling; reachable from the
    #: supervisor's own entry points is runtime.  The two closures are measured apart so
    #: "unreachable" means "no script imports it", not "not in my shortlist".
    seeds = sorted(p for p in lane_paths if p.startswith("scripts/") and p.endswith(".py")) if args.broad else list(SEEDS)
    reachable = closure(seeds, modules, lane_paths)
    reachable_modules = {modules[m] for m in modules if modules[m] in reachable}
    imported_by_tests = test_importers(modules, lane_paths)

    present_in_main, missing_from_main, differs = [], [], []
    for path in sorted(reachable):
        if path not in main_paths:
            missing_from_main.append(path)
        elif blob(MAIN, path) != blob(LANE, path):
            differs.append(path)
        else:
            present_in_main.append(path)

    lane_only_py = sorted(
        p for p in lane_paths - main_paths if p.endswith(".py")
    )
    unreachable_lane_only = [
        p for p in lane_only_py if p not in reachable and modules.get(
            p[len("src/") : -3].replace("/", ".") if p.startswith("src/") else "", ""
        ) not in {modules[m] for m in modules if modules[m] in reachable}
        and not imported_by_tests.get(modules.get(p[len("src/") : -3].replace("/", "."), ""), [])
    ]

    payload = {
        "lane": LANE,
        "main": MAIN,
        "merge_base": BASE,
        "seeds": seeds,
        "counts": {
            "lane_python_files": len([p for p in lane_paths if p.endswith(".py")]),
            "main_python_files": len([p for p in main_paths if p.endswith(".py")]),
            "reachable_files": len(reachable),
            "reachable_modules": len(reachable_modules),
            "reachable_present_in_main": len(present_in_main),
            "reachable_missing_from_main": len(missing_from_main),
            "reachable_differs_in_main": len(differs),
            "lane_only_python_files": len(lane_only_py),
            "lane_only_python_unreachable_and_untested": len(unreachable_lane_only),
        },
        "reachable": sorted(reachable),
        "reachable_missing_from_main": missing_from_main,
        "reachable_differs_in_main": differs,
        "reachable_present_identical_in_main": present_in_main,
        "lane_only_python_unreachable_and_untested": unreachable_lane_only,
        "tests_per_module": {k: sorted(set(v)) for k, v in sorted(imported_by_tests.items())},
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
