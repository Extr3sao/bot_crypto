"""Independent verifier for G-4 — paper routes without authority.

The verifier does not import the worktree's ``src`` by accident. It exports the
requested revision to a private directory, runs every probe and every test with
``PYTHONPATH`` pinned to that export, and fails if the imported package is not
under it. Re-derives the acceptance criteria from the artefact, not from the
report that claims them.

    uv run --frozen python scripts/audit/verify_g4.py
    uv run --frozen python scripts/audit/verify_g4.py --rev <sha> --json out.json

Exit status: 0 only when every check passes. A skipped check is a failure;
there is no third state.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HOT_STOP_REL = "src/trading_bot/autonomous/hot_stop.py"
HOT_STOP_BASELINE_REV = "a072da90"
APP_REL = "src/trading_bot/app.py"
CYCLE_REL = "src/trading_bot/paper/paper_cycle.py"
LAUNCHER_REL = "scripts/start_paper_trading.py"

TARGET_TESTS: tuple[str, ...] = (
    "tests/unit/paper/test_g4_paper_hot_stop.py",
    "tests/unit/paper",
    "tests/unit/cert/test_paper_smoke_decision_path.py",
    "tests/unit/test_app_demo.py",
    "tests/unit/test_app_cli_contract.py",
    "tests/integration/test_paper_e2e_001.py",
    "tests/integration/test_paper_e2e_002.py",
    "tests/integration/test_paper_e2e_003.py",
)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _export(rev: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "tree.tar"
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "-o", str(archive), rev],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive {rev} failed: {completed.stderr[-800:]}")
    tree = destination / "tree"
    tree.mkdir()
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(tree, filter="data")
        except TypeError:
            tar.extractall(tree)
    return tree


def _env(src: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    # A verifier must not inherit a host stop that makes the positive control
    # look like a bypass. The probe creates its own switch.
    for name in ("KILL_SWITCH", "KILL_SWITCH_ENV"):
        env.pop(name, None)
    return env


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})


def _probe(tree: Path, src: Path, scenario: str, *, attach_gate: bool) -> dict[str, Any]:
    fd, raw_path = tempfile.mkstemp(prefix=f"g4-probe-{scenario}-", suffix=".json")
    os.close(fd)
    path = Path(raw_path)
    try:
        cmd = [
            sys.executable,
            "scripts/audit/g4_route_probe.py",
            "--scenario",
            scenario,
            "--json",
            str(path),
        ]
        if attach_gate:
            cmd.append("--attach-gate")
        completed = _run(cmd, cwd=tree, env=_env(src))
        if completed.returncode != 0:
            return {
                "_error": completed.stderr[-1200:],
                "_stdout": completed.stdout[-1200:],
            }
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "_error": f"probe result is not readable JSON: {exc}",
                "_stdout": completed.stdout[-1200:],
            }
    finally:
        path.unlink(missing_ok=True)


def _ast_checks(tree: Path) -> tuple[bool, str]:
    """The dispatch is lexically inside ``order_boundary``; demo has no sink."""
    cycle_tree = ast.parse((tree / CYCLE_REL).read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(cycle_tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    dispatch_ok = False
    for node in ast.walk(cycle_tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute_signal"
        ):
            continue
        cursor: ast.AST | None = node
        while cursor is not None:
            if isinstance(cursor, ast.With):
                for item in cursor.items:
                    ctx = item.context_expr
                    if (
                        isinstance(ctx, ast.Call)
                        and isinstance(ctx.func, ast.Attribute)
                        and ctx.func.attr == "order_boundary"
                    ):
                        dispatch_ok = True
            cursor = parents.get(cursor)

    app_tree = ast.parse((tree / APP_REL).read_text(encoding="utf-8"))
    forbidden = {"PaperCycleEngine", "PaperBroker", "execute_signal"}
    found = sorted(
        {
            node.id
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Name) and node.id in forbidden
        }
    )
    return dispatch_ok and not found, (
        f"dispatch_inside_order_boundary={dispatch_ok}; app_forbidden_names={found}"
    )


def _launcher_checks(tree: Path) -> tuple[bool, str]:
    source = (tree / LAUNCHER_REL).read_text(encoding="utf-8")
    module = ast.parse(source)
    builds_gate = "HotStopGate(" in source
    engine_call_has_hot_stop = False
    for node in ast.walk(module):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "PaperCycleEngine" and "PaperCycleEngine(" in source:
            engine_call_has_hot_stop = any(kw.arg == "hot_stop" for kw in node.keywords)
    main_builds_with_run_dir = "run_dir=run_dir" in source and "run_dir.mkdir" in source
    return builds_gate and engine_call_has_hot_stop and main_builds_with_run_dir, (
        f"HotStopGate={builds_gate}; engine_hot_stop={engine_call_has_hot_stop}; "
        f"main_run_dir={main_builds_with_run_dir}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--json", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    report: dict[str, Any] = {
        "tool": "verify_g4",
        "checkout": str(REPO_ROOT),
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": [],
    }
    checks: list[dict[str, Any]] = report["checks"]
    tmp = Path(tempfile.mkdtemp(prefix="g4-verify-"))
    try:
        rev = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", args.rev],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if rev.returncode != 0:
            raise RuntimeError(f"git rev-parse {args.rev} failed: {rev.stderr[-400:]}")
        report["rev"] = rev.stdout.strip()
        tree = _export(report["rev"], tmp)
        src = tree / "src"
        report["app_sha256"] = hashlib.sha256((tree / APP_REL).read_bytes()).hexdigest()
        report["cycle_sha256"] = hashlib.sha256((tree / CYCLE_REL).read_bytes()).hexdigest()

        # TEST_TARGET == RUNTIME_TARGET: import the export, never the worktree.
        preflight = _run(
            [
                sys.executable,
                "-c",
                "import trading_bot; print(trading_bot.__file__)",
            ],
            cwd=tree,
            env=_env(src),
        )
        imported = Path(preflight.stdout.strip()).resolve() if preflight.returncode == 0 else None
        _check(
            checks,
            "TEST_TARGET == RUNTIME_TARGET",
            bool(imported) and (src / "trading_bot").resolve() in imported.parents,
            f"imported={imported}; interpreter={sys.executable}",
        )

        # ACC-G4-01/02 — demo is a scan, not an execution route.
        demo = _probe(tree, src, "demo-paper", attach_gate=False)
        demo_auto = _probe(tree, src, "demo-live-flag", attach_gate=False)
        demo_ok = (
            demo.get("exit_code") == 0
            and demo_auto.get("exit_code") == 0
            and all(v == 0 for v in (demo.get("calls") or {}).values())
            and all(v == 0 for v in (demo_auto.get("calls") or {}).values())
        )
        _check(
            checks,
            "ACC-G4-01/02 demo reaches no sink and no exchange client",
            demo_ok,
            json.dumps(
                {
                    "demo": demo.get("calls", demo.get("_error")),
                    "demo_autotrade": demo_auto.get("calls", demo_auto.get("_error")),
                    "exits": [demo.get("exit_code"), demo_auto.get("exit_code")],
                },
                sort_keys=True,
            ),
        )

        # ACC-G4-03/04/08 — marker, clean control and process authority.
        marker = _probe(tree, src, "paper-marker", attach_gate=True)
        clean = _probe(tree, src, "paper-clean", attach_gate=True)
        process = _probe(tree, src, "paper-process-stop", attach_gate=True)
        _check(
            checks,
            "ACC-G4-03 marker blocks the paper entry",
            marker.get("orders_created") == 0
            and marker.get("broker_execute_calls") == 0
            and marker.get("hot_stop_blocked") == 1
            and marker.get("gate_engaged") is True,
            json.dumps(marker, sort_keys=True, default=str)[:1200],
        )
        _check(
            checks,
            "ACC-G4-04 clean paper path still trades exactly once",
            clean.get("orders_created") == 1
            and clean.get("broker_execute_calls") == 1
            and clean.get("hot_stop_blocked") == 0,
            json.dumps(clean, sort_keys=True, default=str)[:1200],
        )
        _check(
            checks,
            "ACC-G4-08 process switch blocks without a marker",
            process.get("orders_created") == 0
            and process.get("broker_execute_calls") == 0
            and process.get("hot_stop_blocked") == 1,
            json.dumps(process, sort_keys=True, default=str)[:1200],
        )

        # ACC-G4-11 — the shared stop is not modified.
        baseline = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "show",
                f"{HOT_STOP_BASELINE_REV}:{HOT_STOP_REL}",
            ],
            capture_output=True,
            timeout=60,
        )
        current = (tree / HOT_STOP_REL).read_bytes()
        hot_stop_ok = baseline.returncode == 0 and baseline.stdout == current
        _check(
            checks,
            "ACC-G4-11 hot_stop.py is byte-identical to a072da90",
            hot_stop_ok,
            f"current={hashlib.sha256(current).hexdigest()} baseline={HOT_STOP_BASELINE_REV}",
        )

        ast_ok, ast_detail = _ast_checks(tree)
        _check(checks, "ACC-G4-03/10 dispatch and demo AST", ast_ok, ast_detail)
        launcher_ok, launcher_detail = _launcher_checks(tree)
        _check(checks, "ACC-G4-10 launcher wires a gate", launcher_ok, launcher_detail)

        # ACC-G4-05/06/07 — adversarial cases live in the test file.
        completed = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                *TARGET_TESTS,
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            cwd=tree,
            env=_env(src),
        )
        report["pytest_tail"] = completed.stdout[-2500:]
        _check(
            checks,
            "ACC-G4-05/06/07/12 adversarial and regression suites",
            completed.returncode == 0,
            completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "no output",
        )

        contract = tree / "docs/audit/G-4.md"
        backlog = tree / "docs/audit/AUDIT_BACKLOG.yaml"
        contract_text = contract.read_text(encoding="utf-8") if contract.is_file() else ""
        backlog_text = backlog.read_text(encoding="utf-8") if backlog.is_file() else ""
        _check(
            checks,
            "ACC-G4-13/14 contract, backlog and no-go declarations",
            "LIVE_NO_GO" in contract_text
            and "PRODUCTION_READY = false" in contract_text
            and "id: G-4" in backlog_text
            and "status: done" in backlog_text,
            f"contract={contract.is_file()}; backlog={backlog.is_file()}",
        )
    finally:
        if args.keep:
            report["temp"] = str(tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    report["checks_total"] = len(checks)
    report["checks_passed"] = sum(1 for c in checks if c["ok"])
    report["false_success"] = report["checks_total"] - report["checks_passed"]
    report["verdict"] = (
        "G4_VERIFIED_SCOPED" if report["false_success"] == 0 else "G4_VERIFICATION_FAILED"
    )
    report["duration_s"] = round(time.time() - started, 1)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["false_success"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
