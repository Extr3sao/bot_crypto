r"""AST-based cross-file producer/consumer validator for pytest-bdd step_defs.

Solves 3 false-positive classes + 1 architecture bug in a regex-based check:

    False-positive A: implicit pytest fixtures (capsys / tmp_path / monkeypatch
                      / request / recwarn / cache / pytester / doctest_namespace
                      / record_xml_attribute / line_matcher / warning_checker)
                      show up as MISSING CONSUMER under a name-based allowlist.
    False-positive B: module-level helpers (no @given/@when/@then decorator)
                      have params a regex mis-classifies as fixture consumers.
                      Also nested class-method helpers are out of scope: pytest-bdd
                      binds steps at module level, so tree.body-only walking
                      is the canonical semantics.
    False-positive C: same-name collision \u2014 the regex treats the LHS of
                      ``@given(target_fixture="foo")`` and the param name "foo"
                      equally, conflating producer + consumer.
    Architecture bug:  the regex is per-file. pytest-bdd has no file scoping
                      for target_fixture; fixtures cross files freely.

Usage:
    .\.venv\Scripts\python.exe scripts/check_bdd_fixtures.py
    .\.venv\Scripts\python.exe scripts/check_bdd_fixtures.py tests/bdd/

Exit codes:
    0 \u2014 all steps resolve to a producer (or implicit pytest fixture)
    1 \u2014 at least one MISSING CONSUMER detected
    2 \u2014 parse error in a step_defs file
"""

from __future__ import annotations

import ast
import glob
import re
import sys
from pathlib import Path
from typing import TypedDict

# Public surface for any future importer (currently the script is invoked
# via ``python scripts/check_bdd_fixtures.py``; exposing ``main`` + ``StepInfo``
# is enough to wrap as a pytest plugin if the project later wants that).
__all__ = ["StepInfo", "main"]

# ----------------------------------------------------------------------
# pytest built-in fixtures \u2014 matched via conservative regex
# (instead of an exhaustive frozenset; future-proof against new pytest builds)
# ----------------------------------------------------------------------
PYTEST_FIXTURE_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:"
    r"capsys|capfd|capfdbinary|capsysbinary"  # capture streams
    r"|tmp_path|tmp_path_factory|tmpdir|tmpdir_factory"  # temp dirs
    r"|cache"  # session cache
    r"|request|pytestconfig|pytester"  # test infra
    r"|monkeypatch"  # patching
    r"|recwarn|doctest_namespace|warning_checker"  # warnings / doctest
    r"|record_(?:property|testsuite_property|xml_attribute)"  # reporting
    r"|line_matcher"  # pytester matcher
    r")$",
    re.IGNORECASE,
)

BDD_DECORATOR_NAMES: frozenset[str] = frozenset({"given", "when", "then"})


class StepInfo(TypedDict):
    """Typed shape of a single BDD step inside the file_steps registry.

    Replaces the previous ``dict[str, object]`` annotation so mypy strict-mode
    no longer needs ``# type: ignore[union-attr]`` on ``step["params"]`` access.
    """

    name: str
    lineno: int
    text: str | None
    params: list[str]
    produces: str | None


def _is_pytest_implicit(name: str) -> bool:
    """True if ``name`` matches a pytest built-in fixture pattern."""
    return PYTEST_FIXTURE_PATTERN.fullmatch(name) is not None


def _decorator_name(decorator: ast.expr) -> str | None:
    """Return 'given' / 'when' / 'then' if the decorator is a BDD directive."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _target_fixture(decorator: ast.expr) -> str | None:
    """Extract target_fixture='...' from a decorator Call (None if absent)."""
    if not isinstance(decorator, ast.Call):
        return None
    for kw in decorator.keywords:
        if kw.arg == "target_fixture" and isinstance(kw.value, ast.Constant):
            value = kw.value.value
            if isinstance(value, str):
                return value
    return None


def _step_text(decorator: ast.expr) -> str | None:
    """Extract the first positional string arg of the decorator Call."""
    if not isinstance(decorator, ast.Call):
        return None
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _is_bdd_step(node: ast.FunctionDef) -> bool:
    """True only if the function has at least one @given/@when/@then decorator."""
    return any(_decorator_name(d) in BDD_DECORATOR_NAMES for d in node.decorator_list)


def _step_params(node: ast.FunctionDef) -> list[str]:
    """Return clean param names (skip self/cls + implicit pytest fixtures)."""
    names: list[str] = []
    for arg in node.args.args:
        name = arg.arg
        if name in {"self", "cls"}:
            continue
        if _is_pytest_implicit(name):
            continue
        names.append(name)
    return names


def _scan_step_defs(
    root: str,
) -> tuple[
    dict[str, list[tuple[str, str | None, int]]],
    dict[str, list[StepInfo]],
]:
    """Walk step_defs/*.py (top-level only), return (project_producers, file_steps).

    project_producers : fixture_name -> [(file, step_text_or_fn_name, lineno), ...]
    file_steps       : file -> [StepInfo(...)]
    """
    project_producers: dict[str, list[tuple[str, str | None, int]]] = {}
    file_steps: dict[str, list[StepInfo]] = {}

    for path in sorted(glob.glob(f"{root}/step_defs/*.py")):
        src = Path(path).read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as exc:
            raise SystemExit(f"PARSE ERROR in {path}: {exc}") from exc

        per_file: list[StepInfo] = []
        # tree.body only (NOT ast.walk): pytest-bdd binds steps at module
        # level; nested class-method helpers would otherwise be mis-classified.
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _is_bdd_step(node):
                continue  # skip helpers (no @given/@when/@then)
            bdd_dec = next(
                d for d in node.decorator_list if _decorator_name(d) in BDD_DECORATOR_NAMES
            )
            produces = _target_fixture(bdd_dec)
            text = _step_text(bdd_dec)
            params = _step_params(node)
            per_file.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "text": text,
                    "params": params,
                    "produces": produces,
                }
            )
            if produces:
                project_producers.setdefault(produces, []).append(
                    (path, text or node.name, node.lineno)
                )
        file_steps[path] = per_file

    return project_producers, file_steps


def _print_banner(total_steps: int, file_count: int, root: str) -> None:
    """Print a scanned-files banner so 0-file case is visible."""
    print("=" * 70)
    print(
        f"Scanned {total_steps} BDD step(s) across {file_count} file(s) from {root}/step_defs/*.py"
    )
    print("=" * 70)


def _print_registry(
    project_producers: dict[str, list[tuple[str, str | None, int]]],
) -> None:
    print()
    print("=" * 70)
    print("CROSS-FILE PRODUCER REGISTRY (target_fixtures across all step_defs)")
    print("=" * 70)
    if not project_producers:
        print("  (no producer fixtures declared)")
        return
    for name, sources in sorted(project_producers.items()):
        print(f"  target_fixture={name!r}: produced by {len(sources)} step(s)")
        for f, t, ln in sources:
            display = (t[:58] + "\u2026") if t and len(t) > 60 else t
            print(f"    - {f}:{ln}: {display}")


def _print_missing_consumers(
    project_producers: dict[str, list[tuple[str, str | None, int]]],
    file_steps: dict[str, list[StepInfo]],
) -> int:
    print()
    print("=" * 70)
    print("MISSING-CONSUMER CHECK (cross-file aware)")
    print("=" * 70)
    red_count = 0
    for path in sorted(file_steps):
        for step in file_steps[path]:
            produces = step["produces"]
            lineno = step["lineno"]
            for param in step["params"]:
                # 1) implicit pytest fixture \u2014 skip
                if _is_pytest_implicit(param):
                    continue
                # 2) chain pattern: same step consumes prior fixture AND
                #    updates it for downstream steps (e.g. @when(foo) -> foo).
                if param == produces:
                    continue
                # 3) some producer in the project makes this name \u2014 OK
                if param in project_producers:
                    continue
                print(
                    f"  [RED] {path}:{lineno}::{step['name']}({param}) "
                    f"\u2014 no producer anywhere (not a pytest built-in either)"
                )
                red_count += 1
    if red_count == 0:
        print("  \u2713 all consumers resolve (cross-file)")
    print(f"\nTotal MISSING-CONSUMER flags: {red_count}")
    return red_count


def _print_orphaned_producers(
    project_producers: dict[str, list[tuple[str, str | None, int]]],
    file_steps: dict[str, list[StepInfo]],
) -> None:
    print()
    print("=" * 70)
    print("PRODUCER-NEVER-CONSUMED (informational, may be intentional)")
    print("=" * 70)
    all_consumed: set[str] = set()
    for steps in file_steps.values():
        for step in steps:
            all_consumed.update(step["params"])
    orphans = sorted(set(project_producers) - all_consumed)
    if not orphans:
        print("  \u2713 every producer is consumed")
        return
    for name in orphans:
        sources = project_producers[name]
        print(f"  [INFO] target_fixture={name!r} produced but never consumed:")
        for f, t, ln in sources:
            display = (t[:58] + "\u2026") if t and len(t) > 60 else t
            print(f"    - {f}:{ln}: {display}")


def main(argv: list[str]) -> int:
    root = argv[1] if len(argv) > 1 else "tests/bdd"
    project_producers, file_steps = _scan_step_defs(root)
    total_steps = sum(len(steps) for steps in file_steps.values())
    _print_banner(total_steps, len(file_steps), root)
    _print_registry(project_producers)
    red = _print_missing_consumers(project_producers, file_steps)
    _print_orphaned_producers(project_producers, file_steps)
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
