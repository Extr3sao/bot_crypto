"""Contract tests for the CLI surface: a subcommand that does nothing must fail.

MT-0002.  ``kill-switch`` and ``status`` were shipped as placeholders that
printed ``[stub] ...`` and returned 0.  Any operator, wrapper, cron job or
agent that trusts the exit code concludes that the system halted, or that it
reported its state, when neither happened (OB-02: the highest-consequence
false success in the product surface).

These tests drive the **real entrypoint** — ``python -m trading_bot.app`` in a
subprocess, the same thing a human types — rather than importing ``main`` and
calling it, so they also cover the ``if __name__ == "__main__"`` exit
propagation.  Three properties are pinned:

1. Every subcommand declared unimplemented exits non-zero and says so, with an
   empty stdout so no consumer can read a success message.
2. The set of unimplemented subcommands is explicit and complete: it is a
   subset of the commands argparse accepts, and no dispatch branch in ``main``
   silently prints and returns 0.
3. Commands that *are* implemented keep their previous contract; the refusal
   is not a blanket failure.

Property 2 is deliberately expressed as an AST scan of ``main`` and not as a
list of names: the defect was a shape of code (``print(...)`` then
``return 0``), so the guard matches the shape.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from trading_bot import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = Path(app_module.__file__)

#: The two commands MT-0002 was opened for.  ``MT-0003``/``MT-0004`` will give
#: them real behaviour; until then the contract is "refuse loudly".
DECLARED_UNIMPLEMENTED = frozenset({"kill-switch", "status"})


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    """Execute the real CLI entry point the way an operator would."""
    return subprocess.run(
        [sys.executable, "-m", "trading_bot.app", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _subcommands() -> dict[str, str]:
    """Every command argparse accepts, mapped to its help string."""
    parser = app_module._build_parser()
    for action in parser._actions:
        if getattr(action, "dest", None) == "command":
            return {name: sub.description or "" for name, sub in action.choices.items()}
    raise AssertionError("the CLI has no subcommand action at all")


def _main_tree() -> ast.FunctionDef:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("app.py has no module-level main()")


def _silent_success_branches() -> list[str]:
    """Branches of ``main`` that print something and still return success.

    Matches the exact shape of the MT-0002 defect: a statement that writes to
    stdout (``print`` or ``sys.stdout.write``) followed by ``return 0`` inside
    the same block.  A branch that refuses, raises or delegates does not match.
    """
    offenders: list[str] = []
    for node in ast.walk(_main_tree()):
        if not isinstance(node, ast.If):
            continue
        guard = ast.unparse(node.test)
        prints = False
        returns_zero = False
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                func = statement.value.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name in {"print", "write"}:
                    prints = True
            if isinstance(statement, ast.Return):
                value = statement.value
                if isinstance(value, ast.Constant) and value.value in (0, None):
                    returns_zero = True
        if prints and returns_zero:
            offenders.append(guard)
    return offenders


# --- 1. the declared set is explicit, complete and answerable to argparse ----


def test_the_declared_unimplemented_set_is_the_expected_one() -> None:
    """Adding a third placeholder must be a deliberate, reviewed edit."""
    assert app_module.NOT_IMPLEMENTED_SUBCOMMANDS == DECLARED_UNIMPLEMENTED


def test_every_declared_command_is_a_real_subcommand() -> None:
    """A typo in the guard would otherwise disable the refusal silently."""
    declared = set(app_module.NOT_IMPLEMENTED_SUBCOMMANDS)
    assert declared <= set(_subcommands())
    assert declared, "the guard must not be empty while the stubs exist"


# --- 2. an unimplemented command cannot return success -----------------------


@pytest.mark.parametrize("command", sorted(DECLARED_UNIMPLEMENTED))
def test_unimplemented_subcommand_exits_non_zero(command: str) -> None:
    completed = _run(command)
    assert completed.returncode != 0, (
        f"{command!r} exited 0 after doing nothing (OB-02); stdout={completed.stdout!r}"
    )
    assert completed.returncode == 2, (
        "the repo convention for a refused action is exit 2 "
        f"(scan --no-demo, place-order without --confirm-live); got {completed.returncode}"
    )


@pytest.mark.parametrize("command", sorted(DECLARED_UNIMPLEMENTED))
def test_unimplemented_subcommand_says_so_on_stderr(command: str) -> None:
    completed = _run(command)
    message = _normalise(completed.stderr)
    assert "ERROR" in message
    assert f"'{command}'" in message
    assert "no esta implementado" in message
    assert "no se ha ejecutado ninguna accion" in message


@pytest.mark.parametrize("command", sorted(DECLARED_UNIMPLEMENTED))
def test_unimplemented_subcommand_writes_nothing_to_stdout(command: str) -> None:
    """A success-looking banner on stdout is how the false success travelled."""
    completed = _run(command)
    assert _normalise(completed.stdout) == ""
    assert "[stub]" not in _normalise(completed.stdout) + _normalise(completed.stderr)


@pytest.mark.parametrize("command", sorted(DECLARED_UNIMPLEMENTED))
def test_unimplemented_subcommand_has_no_side_effects(command: str, tmp_path: Path) -> None:
    """Nothing may be created, even in a scratch cwd.

    The environment is inherited on purpose.  Stripping it down to
    ``PYTHONPATH`` alone makes the interpreter itself fail to start on Windows
    (``import asyncio`` dies without the system root), and the test would then
    pass because *no* process ran -- the same false success it exists to
    catch, one level down.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "trading_bot.app", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert "no esta implementado" in _normalise(completed.stderr), (
        "the child never reached the refusal path: " + _normalise(completed.stderr)[-400:]
    )
    assert completed.returncode != 0
    assert list(tmp_path.iterdir()) == []


# --- 3. the guard cannot rot -------------------------------------------------


def test_no_dispatch_branch_prints_and_returns_zero() -> None:
    """The defect's shape, searched for in the whole of ``main``.

    This is the test that would have failed before MT-0002 and will fail again
    if any future placeholder is added the same way.
    """
    offenders = _silent_success_branches()
    assert offenders == [], (
        "these branches of main() print something and still return success: " + repr(offenders)
    )


def test_every_subcommand_is_dispatched_or_declared() -> None:
    """No command may fall through to the help text while claiming success.

    A command is accounted for when ``main`` compares it by name (``==``) or
    when it is a member of the declared unimplemented set.  Both are explicit
    branches; the failure mode this guards against is neither, where argparse
    accepts the command and ``main`` only prints help before returning 1.
    """
    commands = set(_subcommands())
    dispatched_by_equality = {
        node.test.comparators[0].value
        for node in ast.walk(_main_tree())
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.comparators[0], ast.Constant)
        and isinstance(node.test.comparators[0].value, str)
    }
    declared = set(app_module.NOT_IMPLEMENTED_SUBCOMMANDS)
    unaccounted = commands - (dispatched_by_equality | declared)
    message = "subcommands accepted by argparse but never dispatched: " + repr(unaccounted)
    assert unaccounted == set(), message
    assert dispatched_by_equality & declared == set(), (
        "a declared-unimplemented command also has a real branch: "
        + repr(dispatched_by_equality & declared)
    )


# --- 4. implemented commands keep their contract -----------------------------


def test_implemented_refusal_still_reaches_its_handler() -> None:
    """``place-order`` without ``--confirm-live`` refuses; it must keep doing so."""
    completed = _run(
        "place-order",
        "--symbol",
        "BTC/USDT",
        "--side",
        "buy",
        "--order-type",
        "market",
        "--amount",
        "0.001",
    )
    message = _normalise(completed.stderr)
    assert completed.returncode == 2
    assert "falta --confirm-live" in message
    assert "no esta implementado" not in message


def test_implemented_subcommands_still_parse() -> None:
    """``--help`` exits 0 for every command that is not declared unimplemented."""
    for command in sorted(set(_subcommands()) - DECLARED_UNIMPLEMENTED):
        completed = _run(command, "--help")
        assert completed.returncode == 0, f"{command} --help exited {completed.returncode}"
        assert "usage:" in _normalise(completed.stdout).lower()


def test_the_cli_still_reports_its_version() -> None:
    """A cheap proof that the parser and the module-level guard still load."""
    completed = _run("--version")
    assert completed.returncode == 0
    assert "trading-bot" in _normalise(completed.stdout)
