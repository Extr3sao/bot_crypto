"""Separate verifier for G-2 — hot activation of the kill switch.

This script does not import the tests it is checking and does not read their
literals. It exports the commit under review, re-derives each acceptance
criterion from the exported source, and runs its own scenarios in that tree.

What that buys, and what it does not
------------------------------------
It is a **different artefact** from the suite: its checks are written against
the contract (`docs/audit/G-2.md`), not against the test file, and a broken test
cannot make it pass. It is *not* an organisational separation: the same author
wrote both. The verdict is therefore `PROCEDURALLY_SEPARATED / VERIFIED_SCOPED`,
never "independently audited".

Usage
-----
    python reports/multiagent-audit/tools/verify_g2.py --rev <sha> --json out.json

Exit status: 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any



def _find_repo_root() -> Path:
    """Locate the work tree, not a fixed depth: this script is also versioned
    next to the run it produced, and a hardcoded ``parents[3]`` breaks there."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate
    return here.parents[3]


REPO_ROOT = _find_repo_root()

#: The scope the contract froze. Kept as a literal on purpose: reading it back
#: out of the contract would only prove the contract agrees with itself.
ALLOWED_PATHS: tuple[str, ...] = (
    "docs/audit/G-2.md",
    "docs/audit/AUDIT_BACKLOG.yaml",
    "docs/audit/runtime_authority_map.md",
    "docs/audit/runs/",
    "src/trading_bot/autonomous/hot_stop.py",
    "src/trading_bot/autonomous/runtime.py",
    "src/trading_bot/app.py",
    "tests/unit/autonomous/test_hot_engage.py",
    "tests/unit/test_app_cli_contract.py",
    "scripts/audit/g2_mutants.py",
)

#: Files the implementation was forbidden to touch, including the two suites that
#: already carried MT-0003/MT-0004-R1.
PROTECTED_PATHS: tuple[str, ...] = (
    "src/trading_bot/autonomous/decision.py",
    "src/trading_bot/paper/kill_switch_v2.py",
    "src/trading_bot/paper/paper_cycle.py",
    "tests/unit/autonomous/test_decision_kill_switch.py",
    "tests/unit/autonomous/test_kill_switch_negative.py",
    "scripts/audit/negative_controls.py",
)


@dataclass
class Check:
    check_id: str
    criterion: str
    description: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def _env(src: Path, tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(src), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _export(rev: str, destination: Path) -> Path:
    archive = destination / "tree.tar"
    completed = _run(
        ["git", "archive", "--format=tar", "-o", str(archive), rev], cwd=REPO_ROOT
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive failed: {completed.stderr[-400:]}")
    tree = destination / "tree"
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(tree, filter="data")
        except TypeError:
            tar.extractall(tree)
    return tree


def _changed_paths(rev: str) -> list[str]:
    completed = _run(
        ["git", "show", "--pretty=format:", "--name-only", rev], cwd=REPO_ROOT
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _ancestor_chain(tree_root: ast.AST, target: ast.AST) -> list[ast.AST]:
    chain: list[ast.AST] = []

    def walk(node: ast.AST, stack: list[ast.AST]) -> None:
        if node is target:
            chain.extend(stack)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, [*stack, node])

    walk(tree_root, [])
    return chain


def _calls(node: ast.AST, attr: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    )


def _inside_order_boundary(tree_root: ast.AST, target: ast.AST) -> bool:
    for ancestor in _ancestor_chain(tree_root, target):
        if isinstance(ancestor, ast.With):
            for item in ancestor.items:
                if _calls(item.context_expr, "order_boundary"):
                    return True
    return False


def _find_function(tree_root: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree_root):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _has_release_in_finally(function: ast.FunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Try):
            continue
        for statement in node.finalbody:
            for inner in ast.walk(statement):
                if _calls(inner, "release"):
                    return True
    return False


def _has_call(function: ast.FunctionDef, attr: str) -> bool:
    return any(_calls(node, attr) for node in ast.walk(function))


def _scenario(tree: Path, scenario: str) -> tuple[int, dict[str, Any]]:
    """Run one behaviour scenario against the exported tree, in a child process."""
    src = tree / "src"
    tmp = Path(tempfile.mkdtemp(prefix="g2-scenario-"))
    script = {
        "engage": r"""
import json, pathlib
from trading_bot.autonomous.hot_stop import HotStopGate, HOT_STOP_FILE_NAME
from trading_bot.paper.kill_switch_v2 import KillSwitch
run_dir = pathlib.Path(r"{d}")
switch = KillSwitch()
gate = HotStopGate(kill_switch=switch, run_dir=run_dir, now_ms=lambda: 1)
(run_dir / HOT_STOP_FILE_NAME).write_text("stop now", encoding="utf-8")
engaged = gate.poll(run_id="r1")
with gate.order_boundary() as allowed:
    first = allowed
ack = gate.engage("again")
with gate.order_boundary() as allowed_again:
    second = allowed_again
(run_dir / HOT_STOP_FILE_NAME).unlink()
after_delete = gate.poll(run_id="r2")
print(json.dumps(dict(engaged=engaged, dispatch_allowed=first, state=switch.state.value,
                      repeated=ack.repeated, after_second=second,
                      after_delete=after_delete, engaged_after=gate.engaged)))
""",
        "failclosed": r"""
import json, pathlib
from trading_bot.autonomous.hot_stop import HotStopGate
from trading_bot.paper.kill_switch_v2 import KillSwitch
run_dir = pathlib.Path(r"{d}")
gate = HotStopGate(kill_switch=KillSwitch(), run_dir=run_dir, control_path=run_dir, now_ms=lambda: 1)
engaged = gate.poll()
with gate.order_boundary() as allowed:
    dispatch = allowed
print(json.dumps(dict(engaged=engaged, dispatch_allowed=dispatch)))
""",
        "open": r"""
import json, pathlib
from trading_bot.autonomous.hot_stop import HotStopGate
from trading_bot.paper.kill_switch_v2 import KillSwitch
run_dir = pathlib.Path(r"{d}")
switch = KillSwitch()
gate = HotStopGate(kill_switch=switch, run_dir=run_dir, now_ms=lambda: 1)
polled = gate.poll()
with gate.order_boundary() as allowed:
    dispatch = allowed
print(json.dumps(dict(polled=polled, dispatch_allowed=dispatch, state=switch.state.value)))
""",
    }[scenario].format(d=str(tmp).replace("\\", "\\\\"))
    completed = _run([sys.executable, "-c", script], cwd=tree, env=_env(src, tree))
    if completed.returncode != 0:
        return completed.returncode, {"stderr": completed.stderr[-600:]}
    return 0, json.loads(completed.stdout.strip().splitlines()[-1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", required=True, help="commit to verify")
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    checks: list[Check] = []
    tmp = Path(tempfile.mkdtemp(prefix="g2-verify-"))
    report: dict[str, Any] = {
        "tool": "reports/multiagent-audit/tools/verify_g2.py",
        "contract": "docs/audit/G-2.md",
        "rev_requested": args.rev,
        "author": "same author as the implementation",
        "independence": "PROCEDURALLY_SEPARATED",
    }
    try:
        rev = _run(["git", "rev-parse", f"{args.rev}^{{commit}}"], cwd=REPO_ROOT).stdout.strip()
        report["rev_resolved"] = rev
        tree = _export(rev, tmp)
        src = tree / "src"

        # -- V-1 scope -------------------------------------------------------
        changed = _changed_paths(rev)
        outside = [
            path
            for path in changed
            if not any(
                path == allowed or (allowed.endswith("/") and path.startswith(allowed))
                for allowed in ALLOWED_PATHS
            )
        ]
        touched_protected = [
            path for path in changed if path in PROTECTED_PATHS
        ]
        checks.append(
            Check(
                "V-1",
                "ACC-G2-12",
                "every changed file is inside the frozen allowed_paths",
                not outside and not touched_protected,
                f"{len(changed)} files changed",
                {"outside": outside, "protected": touched_protected, "changed": changed},
            )
        )

        # -- V-2 one dispatch site, inside the boundary -----------------------
        runtime_src = (src / "trading_bot" / "autonomous" / "runtime.py").read_text("utf-8")
        runtime_tree = ast.parse(runtime_src)
        dispatches = [
            node
            for node in ast.walk(runtime_tree)
            if _calls(node, "execute_signal")
        ]
        guarded = [node for node in dispatches if _inside_order_boundary(runtime_tree, node)]
        checks.append(
            Check(
                "V-2",
                "ACC-G2-02",
                "every broker dispatch in the runtime is lexically inside order_boundary",
                bool(dispatches) and len(guarded) == len(dispatches),
                f"{len(guarded)}/{len(dispatches)} dispatches guarded",
                {"dispatch_line": [getattr(n, "lineno", None) for n in dispatches]},
            )
        )

        # -- V-3 the lock spans the dispatch ---------------------------------
        hot_src = (src / "trading_bot" / "autonomous" / "hot_stop.py").read_text("utf-8")
        hot_tree = ast.parse(hot_src)
        boundary_fn = _find_function(hot_tree, "order_boundary")
        engage_fn = _find_function(hot_tree, "engage")
        lock_checks = {
            "boundary_acquires": bool(boundary_fn) and _has_call(boundary_fn, "acquire"),
            "boundary_releases_in_finally": bool(boundary_fn)
            and _has_release_in_finally(boundary_fn),
            "engage_acquires": bool(engage_fn) and _has_call(engage_fn, "acquire"),
            "engage_releases_in_finally": bool(engage_fn) and _has_release_in_finally(engage_fn),
            "shared_lock_attribute": hot_src.count("self._lock.acquire") >= 2,
        }
        checks.append(
            Check(
                "V-3",
                "ACC-G2-04",
                "engage and dispatch take the same lock, released in finally",
                all(lock_checks.values()),
                "linearization is structural",
                lock_checks,
            )
        )

        # -- V-4 behaviour: engaged closes, delete does not reopen -----------
        code, out = _scenario(tree, "engage")
        engage_ok = (
            code == 0
            and out.get("engaged") is True
            and out.get("dispatch_allowed") is False
            and out.get("state") == "halted"
            and out.get("after_second") is False
            and out.get("after_delete") is True
            and out.get("engaged_after") is True
        )
        checks.append(
            Check(
                "V-4",
                "ACC-G2-01/03/07",
                "control file engages; second engage is a repeat; deleting it does not rearm",
                engage_ok,
                "own scenario, exported tree",
                out,
            )
        )
        repeated_flag = out.get("repeated") is True
        checks.append(
            Check(
                "V-5",
                "ACC-G2-03",
                "a repeated engage is reported as repeated, not as a new transition",
                repeated_flag,
                "",
                {"repeated": out.get("repeated")},
            )
        )

        # -- V-6 fail closed --------------------------------------------------
        code, out = _scenario(tree, "failclosed")
        closed_ok = (
            code == 0
            and out.get("engaged") is True
            and out.get("dispatch_allowed") is False
        )
        checks.append(
            Check(
                "V-6",
                "ACC-G2-05",
                "an unreadable control path engages and refuses the dispatch",
                closed_ok,
                "own scenario, exported tree",
                out,
            )
        )

        # -- V-7 the control does not fire ------------------------------------
        code, out = _scenario(tree, "open")
        open_ok = (
            code == 0
            and out.get("polled") is False
            and out.get("dispatch_allowed") is True
            and out.get("state") == "normal"
        )
        checks.append(
            Check(
                "V-7",
                "ACC-G2-10",
                "with no control file the gate is open (so V-4/V-6 are not vacuous)",
                open_ok,
                "",
                out,
            )
        )

        # -- V-8 CLI --------------------------------------------------------
        run_dir = Path(tempfile.mkdtemp(prefix="g2-cli-"))
        cli = _run(
            [
                sys.executable,
                "-m",
                "trading_bot.app",
                "kill-switch",
                "--run-dir",
                str(run_dir),
                "--engage",
                "--reason",
                "verifier",
            ],
            cwd=tree,
            env=_env(src, tree),
        )
        disarm = _run(
            [
                sys.executable,
                "-m",
                "trading_bot.app",
                "kill-switch",
                "--run-dir",
                str(run_dir),
                "--engage",
                "--disarm",
            ],
            cwd=tree,
            env=_env(src, tree),
        )
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(cli.stdout)
        except json.JSONDecodeError:
            payload = {}
        cli_ok = (
            cli.returncode == 0
            and payload.get("status") == "REQUESTED"
            and payload.get("enforced") is False
            and disarm.returncode == 2
            and (run_dir / "KILL_SWITCH").exists()
        )
        checks.append(
            Check(
                "V-8",
                "ACC-G2-01/07",
                "CLI writes the request, refuses to disarm, and does not claim enforcement",
                cli_ok,
                f"engage exit {cli.returncode}, disarm exit {disarm.returncode}",
                payload,
            )
        )

        # -- V-9 an independent offline reproduction --------------------------
        traces = sorted(tree.glob("docs/audit/runs/*-G-2/offline_trace.py"))
        trace_ok = False
        trace_detail = "no trace script in the export"
        trace_payload: dict[str, Any] = {}
        if len(traces) == 1:
            out_path = Path(tempfile.mkdtemp(prefix="g2-trace-")) / "trace.json"
            trace_run = _run(
                [
                    sys.executable,
                    str(traces[0]),
                    "--run-dir",
                    str(Path(tempfile.mkdtemp(prefix="g2-tracedir-"))),
                    "--json",
                    str(out_path),
                ],
                cwd=tree,
                env=_env(src, tree),
            )
            if out_path.exists():
                trace_payload = json.loads(out_path.read_text("utf-8"))
            steps = trace_payload.get("steps", [])
            trace_ok = (
                trace_run.returncode == 0
                and trace_payload.get("verdict") == "OPERATIONAL_THEN_ENGAGED_NO_NEW_ORDER"
                and len(steps) == 3
                and steps[0]["broker_calls"] == 1
                and steps[1]["broker_calls"] == 1
                and steps[2]["broker_calls"] == 1
            )
            trace_detail = trace_payload.get("verdict", f"exit {trace_run.returncode}")
        checks.append(
            Check(
                "V-9",
                "ACC-G2-11",
                "operational -> engaged -> NO_ORDER reproduced offline on one runtime",
                trace_ok,
                trace_detail,
                {"steps": trace_payload.get("steps", [])},
            )
        )

        # -- V-10 the suite, in the exported tree ----------------------------
        pytest_run = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/autonomous/test_hot_engage.py",
                "tests/unit/test_app_cli_contract.py",
                "-q",
                "--tb=no",
                "-p",
                "no:cacheprovider",
            ],
            cwd=tree,
            env=_env(src, tree),
        )
        checks.append(
            Check(
                "V-10",
                "ACC-G2-10",
                "the focal suites pass in the exported tree",
                pytest_run.returncode == 0,
                (pytest_run.stdout.strip().splitlines() or ["<no output>"])[-1],
                {},
            )
        )

    finally:
        if args.keep:
            print(f"export kept at {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for check in checks if check.passed)
    report["checks"] = [check.__dict__ for check in checks]
    report["passed"] = passed
    report["total"] = len(checks)
    report["total_seconds"] = round(time.time() - started, 2)
    report["verdict"] = (
        "VERIFIED_SCOPED" if passed == len(checks) and checks else "FAILED"
    )

    for check in checks:
        print(
            f"[{'PASS' if check.passed else 'FAIL'}] {check.check_id} "
            f"({check.criterion}) {check.description} — {check.detail}"
        )
    print(f"\n{passed}/{len(checks)} — {report['verdict']} (PROCEDURALLY_SEPARATED)")

    if args.json_path:
        Path(args.json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_path).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(f"report written to {args.json_path}")
    return 0 if report["verdict"] == "VERIFIED_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
