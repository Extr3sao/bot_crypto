"""Tracked internal dependency guard (CP-PO-003 Phase 6).

Permanent anti-false-success gate: every ``trading_bot.*`` module loaded by
the test process MUST

    1. resolve to a source file INSIDE the current repository, and
    2. be TRACKED by Git.

If a tracked module imports an internal module that exists only as an
untracked file (or, worse, from outside the repository), certification would
silently validate a tree that no clean checkout can reproduce. This guard
runs AFTER the whole suite has imported, so it sees the complete closure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True, cwd=REPO)
    return set(out.stdout.splitlines())


#: Propósito: importar la CLOSURE del árbol de fuentes rastreado en un
#: intérprete FRESCO y reportar cualquier módulo interno que resuelva fuera del
#: repositorio o que no esté rastreado. Que corra en un subproceso es lo que
#: hace la comprobación INDEPENDIENTE DEL ORDEN: sólo ve la closure alcanzable
#: desde módulos RASTREADOS, nunca la contaminación incidental que un fichero de
#: test NO rastreado haya dejado en ``sys.modules`` del proceso llamante.
_CLOSURE_PROBE = r"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

repo = Path.cwd()
sys.path.insert(0, str(repo / "src"))
tracked = set(
    subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True, cwd=repo
    ).stdout.splitlines()
)
for mod in json.loads(sys.argv[1]):
    try:
        importlib.import_module(mod)
    except Exception:  # noqa: BLE001 - a genuinely unimportable module is
        pass          # reported by test_every_tracked_module_imports_*

offenders_outside: list[str] = []
offenders_untracked: list[str] = []
for name, mod in sorted(sys.modules.items()):
    if not name.startswith("trading_bot"):
        continue
    f = getattr(mod, "__file__", None)
    if f is None:
        continue
    p = Path(f).resolve()
    try:
        rel = p.relative_to(repo).as_posix()
    except ValueError:
        offenders_outside.append(f"{name} -> {p}")
        continue
    if rel not in tracked:
        offenders_untracked.append(f"{name} -> {rel}")
print("__CLOSURE__" + json.dumps({"outside": offenders_outside, "untracked": offenders_untracked}))
"""


def _closure_offenders() -> dict[str, list[str]]:
    """Offenders of the tracked-source closure, derived from a fresh import."""
    tracked = _tracked_files()
    src_modules = sorted(
        rel[len("src/") : -3].replace("/", ".")
        for rel in tracked
        if rel.startswith("src/trading_bot/") and rel.endswith(".py")
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CLOSURE_PROBE, json.dumps(src_modules)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
    )
    marker = "__CLOSURE__"
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(marker)), None)
    assert line is not None, f"closure probe produced no result:\n{proc.stdout}\n{proc.stderr}"
    payload: dict[str, list[str]] = json.loads(line[len(marker) :])
    return payload


def test_all_imported_internal_modules_are_tracked() -> None:
    """Every trading_bot.* module in the TRACKED closure must be tracked.

    DEF-CLOSURE-001: the previous implementation inspected this process's
    global ``sys.modules`` *after the whole suite had imported*, so a single
    untracked test file importing untracked modules made the guard fail (and
    only when that test ran first) — an order-dependent false positive on
    code that a clean checkout would never load. The check now imports the
    tracked source tree in a fresh interpreter, which is order-independent and
    still fails loudly if a TRACKED module pulls in an untracked internal one.
    """
    offenders = _closure_offenders()
    assert not offenders["outside"], (
        "Internal modules resolved OUTSIDE the repository:\n  " + "\n  ".join(offenders["outside"])
    )
    assert not offenders["untracked"], (
        "Internal modules imported but NOT tracked by Git (clean checkouts "
        "cannot reproduce this tree):\n  " + "\n  ".join(offenders["untracked"])
    )


def test_closure_guard_is_order_independent_under_module_pollution() -> None:
    """Regression for DEF-CLOSURE-001.

    An untracked module injected into THIS process's ``sys.modules`` (the exact
    shape of the pollution that produced the order-dependent failure) must NOT
    make the closure guard fail: the guard derives its verdict from a fresh
    import of the tracked tree, not from mutable global state.
    """
    name = "trading_bot.research.experimental._pollution_probe"
    assert name not in _tracked_files()
    stub = types.ModuleType(name)
    stub.__file__ = str(REPO / "src" / "trading_bot" / "research" / "experimental" / "_probe.py")
    sys.modules[name] = stub
    try:
        offenders = _closure_offenders()
        assert offenders["untracked"] == [], offenders["untracked"]
        assert offenders["outside"] == [], offenders["outside"]
    finally:
        sys.modules.pop(name, None)


def test_runtime_entry_points_importable() -> None:
    """The L5 paper runtime entry chain must import from committed files only."""
    import importlib

    for mod in (
        "trading_bot.paper.paper_cycle",
        "trading_bot.paper.paper_orchestrator",
        "trading_bot.paper.harness",
        "trading_bot.paper.snapshot_context",
        "trading_bot.paper.snapshot_history",
        "trading_bot.execution.idempotency",
        "trading_bot.risk.manager",
        "trading_bot.research.asset_intelligence.registry",
        "trading_bot.research.strategy_router",
        "trading_bot.research.families",
    ):
        importlib.import_module(mod)


def test_every_tracked_module_imports_under_declared_environment() -> None:
    """Permanent anti-false-success closure gate (CERT-PO-L5-001 root cause).

    Imports EVERY tracked ``src/trading_bot/*.py`` module (excluding __init__
    stubs, which are exercised transitively) with the real Python runtime and
    fails on any ModuleNotFoundError. This is deliberately NOT a path-string
    mapping: importlib resolution reflects the exact import semantics a clean
    checkout would experience. Regresses the six bindings that previously made
    the certified candidate unimportable (cost_model, candle_filter,
    scanner_bridge, observability.journal, paper.signal_types,
    domain.enums.kill_switch) and any future missing-transitive-module of the
    same class.
    """

    import importlib
    import subprocess

    repo = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True, cwd=repo
    ).stdout.splitlines()

    modules: list[str] = []
    for rel in tracked:
        if not rel.startswith("src/trading_bot/") or not rel.endswith(".py"):
            continue
        if rel.endswith("__init__.py"):
            continue  # exercised transitively by every submodule import
        modules.append(rel[len("src/") : -3].replace("/", "."))

    failures: list[str] = []
    for mod in sorted(set(modules)):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            failures.append(f"{mod} -> {exc}")

    assert not failures, (
        "Tracked module(s) fail to import under the declared environment "
        "(dependency closure is NOT tracked/complete — a clean checkout "
        "cannot reproduce this tree):\n  " + "\n  ".join(failures)
    )
