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

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True, cwd=REPO)
    return set(out.stdout.splitlines())


def test_all_imported_internal_modules_are_tracked() -> None:
    """Every loaded trading_bot.* module must live inside the repo and be tracked."""
    tracked = _tracked_files()
    offenders_outside: list[str] = []
    offenders_untracked: list[str] = []

    for name, mod in sorted(sys.modules.items()):
        if not name.startswith("trading_bot"):
            continue
        f = getattr(mod, "__file__", None)
        if f is None:  # namespace package stub
            continue
        path = Path(f).resolve()
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            offenders_outside.append(f"{name} -> {path}")
            continue
        if rel not in tracked:
            offenders_untracked.append(f"{name} -> {rel}")

    assert not offenders_outside, (
        "Internal modules resolved OUTSIDE the repository:\n  " + "\n  ".join(offenders_outside)
    )
    assert not offenders_untracked, (
        "Internal modules imported but NOT tracked by Git (clean checkouts "
        "cannot reproduce this tree):\n  " + "\n  ".join(offenders_untracked)
    )


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
        modules.append(rel[len("src/"):-3].replace("/", "."))

    failures: list[str] = []
    for mod in sorted(set(modules)):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            failures.append(f"{mod} -> {exc}")

    assert not failures, (
        "Tracked module(s) fail to import under the declared environment "
        "(dependency closure is NOT tracked/complete — a clean checkout "
        "cannot reproduce this tree):\n  "
        + "\n  ".join(failures)
    )
