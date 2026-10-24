"""Separate verifier for G-3 — the hot stop on LIVE execution paths.

This script does not import the test module and does not read its assertions.
It exports the commit under review, re-derives the structural property from the
exported source, and drives each entrypoint in its own process with its own
scenarios: it writes the markers itself, with the real operator CLI.

What that buys, and what it does not
------------------------------------
- It is a **different artefact** from the suite: a broken test cannot make it
  pass, and its scenarios are written against `docs/audit/G-3.md`.
- It is **not** independent of the instrumentation: the recording clients come
  from `scripts/audit/g3_live_probe.py`, which the same author wrote. A probe
  that never recorded anything would fail V-3 (the positive control must show
  one call), but the verifier cannot prove the real HTTP client would have been
  called — only that the code path reaches the point where it is invoked.
- It is **not** an organisational separation: same author. The verdict is
  therefore `PROCEDURALLY_SEPARATED / VERIFIED_SCOPED`, never "independently
  audited".

Usage
-----
    uv run --frozen python scripts/audit/verify_g3.py --rev <sha> --json out.json
    uv run --frozen python scripts/audit/verify_g3.py --source worktree

Exit status: 0 only when every check passes.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The commit G-1 closed on. G-3 must not have touched the gate it reuses.
BASELINE_REV = "a072da90ebedac71a11e8e301f3c6db3e0401733"
HOT_STOP_REL = "src/trading_bot/autonomous/hot_stop.py"
APP_REL = "src/trading_bot/app.py"

LIVE_SINKS = (
    "create_order",
    "place_order",
    "place_spot_order",
    "flash_close_position",
    "place_position_tpsl",
)

REGRESSION_SUITES = (
    "tests/unit/test_live_hot_stop_coverage.py",
    "tests/unit/test_app_cli_contract.py",
    "tests/unit/test_app_demo.py",
    "tests/unit/autonomous/",
)

_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".tmp",
)


@dataclass
class Check:
    check_id: str
    criterion: str
    description: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1800
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def _env(tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src"), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["G3_APP_SRC"] = str(tree / "src")
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("TRADING_BOT_KILL_SWITCH", None)
    return env


def _export(rev: str | None, destination: Path, source: str) -> Path:
    if source == "worktree":
        shutil.copytree(REPO_ROOT, destination, symlinks=True, ignore=_COPY_IGNORE)
        return destination
    archive = destination.parent / "tree.tar"
    completed = _run(
        ["git", "archive", "--format=tar", "-o", str(archive), rev or "HEAD"], cwd=REPO_ROOT
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive failed: {completed.stderr[-400:]}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(destination, filter="data")
        except TypeError:
            tar.extractall(destination)
    return destination


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe(tree: Path, entrypoint: str, run_dir: Path, *extra: str) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "probe.json"
    completed = _run(
        [
            sys.executable,
            str(tree / "scripts" / "audit" / "g3_live_probe.py"),
            "--entrypoint",
            entrypoint,
            "--run-dir",
            str(run_dir),
            *extra,
            "--json",
            str(out),
        ],
        cwd=tree,
        env=_env(tree),
    )
    if not out.is_file():
        return {"error": "probe produced no json", "stderr": completed.stderr[-1500:]}
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["_returncode"] = completed.returncode
    return payload


def _engage(tree: Path, run_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            "-m",
            "trading_bot.app",
            "kill-switch",
            "--run-dir",
            str(run_dir),
            "--engage",
            "--reason",
            "g3 verifier",
        ],
        cwd=tree,
        env=_env(tree),
    )


def _sink_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LIVE_SINKS
    ]


def _guarded(tree: ast.AST, target: ast.AST) -> bool:
    chain: list[ast.AST] = []

    def walk(node: ast.AST, stack: list[ast.AST]) -> None:
        if node is target:
            chain.extend(stack)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, [*stack, node])

    walk(tree, [])
    return any(
        isinstance(ancestor, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "_live_order_boundary"
            for item in ancestor.items
        )
        for ancestor in chain
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G-3 independent re-derivation.")
    parser.add_argument("--rev", default=None)
    parser.add_argument("--source", choices=["archive", "worktree"], default="archive")
    parser.add_argument("--json", default=None)
    parser.add_argument("--report", default=None, help="RUN_REPORT.json whose hashes to check")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    checks: list[Check] = []
    tmp = Path(tempfile.mkdtemp(prefix="g3-verify-"))
    head = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    branch = _run(["git", "branch", "--show-current"], cwd=REPO_ROOT).stdout.strip()
    dirty = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.strip()

    def add(check: Check) -> None:
        checks.append(check)

    try:
        tree = _export(args.rev, tmp / "tree", args.source)
        src_app = tree / APP_REL

        # V-1 — identity of what is being verified.
        resolved_rev = args.rev or (head if args.source == "worktree" else "HEAD")
        add(
            Check(
                "V-1",
                "ACC-G3-13",
                "identity: commit, branch, tree state",
                bool(src_app.is_file()),
                f"rev={resolved_rev} branch={branch} dirty={'yes' if dirty else 'no'}",
                {
                    "rev": resolved_rev,
                    "head": head,
                    "branch": branch,
                    "dirty": bool(dirty),
                    "checkout": str(REPO_ROOT),
                    "app_sha256": _sha(src_app) if src_app.is_file() else "",
                },
            )
        )

        # V-2 — the structural property, re-derived from the exported source.
        tree_ast = ast.parse(src_app.read_text(encoding="utf-8"))
        sinks = _sink_calls(tree_ast)
        unguarded = [s.lineno for s in sinks if not _guarded(tree_ast, s)]
        add(
            Check(
                "V-2",
                "ACC-G3-08",
                "every live sink is lexically inside _live_order_boundary",
                len(sinks) == 7 and not unguarded,
                f"{len(sinks)} sink call(s), unguarded={unguarded}",
                {"sinks": len(sinks), "unguarded_lines": unguarded},
            )
        )

        # V-3 — positive control: the path really reaches the broker.
        control = _probe(tree, "place-order-futures", tmp / "ctl")
        add(
            Check(
                "V-3",
                "ACC-G3-01",
                "without a marker the futures entry sends exactly one order",
                control.get("broker_calls") == 1 and control.get("exit_code") == 0,
                f"calls={control.get('broker_calls')} exit={control.get('exit_code')}",
                control,
            )
        )
        add(
            Check(
                "V-3b",
                "ACC-G3-14",
                "the probe loaded this export's trading_bot.app and the fake clients",
                control.get("app_file") == str(src_app.resolve())
                and control.get("patched", {}).get("futures") == "FakeFutures",
                f"app_file={control.get('app_file')} patched={control.get('patched')}",
            )
        )

        # V-4 — a marker written by the real CLI blocks the next process.
        blocked = tmp / "blocked"
        blocked.mkdir(parents=True)
        engaged = _engage(tree, blocked)
        run_blocked = _probe(tree, "run-futures", blocked)
        cli_blocked = _probe(tree, "place-order-futures", blocked)
        add(
            Check(
                "V-4",
                "ACC-G3-02/03",
                "operator CLI marker blocks the loop and the CLI entry",
                engaged.returncode == 0
                and run_blocked.get("broker_calls") == 0
                and cli_blocked.get("broker_calls") == 0
                and cli_blocked.get("exit_code") == 2,
                f"engage={engaged.returncode} run_calls={run_blocked.get('broker_calls')} "
                f"cli_calls={cli_blocked.get('broker_calls')} cli_exit={cli_blocked.get('exit_code')}",
                {"run": run_blocked, "cli": cli_blocked, "engage_exit": engaged.returncode},
            )
        )

        # V-5 — restart over the same directory inherits the stop.
        second = _probe(tree, "place-order-futures", blocked)
        audit_path = blocked / "kill_switch_events.jsonl"
        events = (
            [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if audit_path.is_file()
            else []
        )
        add(
            Check(
                "V-5",
                "ACC-G3-04",
                "a second process over the same run_dir boots engaged",
                second.get("broker_calls") == 0
                and any(e.get("event") == "restored" for e in events),
                f"calls={second.get('broker_calls')} events={[e.get('event') for e in events]}",
                {"calls": second.get("broker_calls"), "events": events[:5]},
            )
        )

        # V-6 — unreadable marker.
        corrupt = tmp / "corrupt"
        (corrupt / "KILL_SWITCH").mkdir(parents=True)
        corrupt_result = _probe(tree, "place-order-spot", corrupt)
        add(
            Check(
                "V-6",
                "ACC-G3-05",
                "a marker that cannot be read refuses entry",
                corrupt_result.get("broker_calls") == 0 and corrupt_result.get("exit_code") == 2,
                f"calls={corrupt_result.get('broker_calls')} exit={corrupt_result.get('exit_code')}",
            )
        )

        # V-7 — the boot switch, with no marker.
        env_dir = tmp / "envswitch"
        env_result = _probe(tree, "place-order-futures", env_dir, "--env-kill-switch", "halted")
        add(
            Check(
                "V-7",
                "ACC-G3-06",
                "KILL_SWITCH_ENV blocks entry and is not persisted",
                env_result.get("broker_calls") == 0
                and env_result.get("exit_code") == 2
                and env_result.get("marker_present") is False,
                f"calls={env_result.get('broker_calls')} exit={env_result.get('exit_code')} "
                f"marker={env_result.get('marker_present')}",
            )
        )

        # V-8 — reduction is not trapped.
        reduce_dir = tmp / "reduce"
        reduce_dir.mkdir(parents=True)
        (reduce_dir / "KILL_SWITCH").write_text("verifier\n", encoding="utf-8")
        close_result = _probe(tree, "close-position", reduce_dir)
        add(
            Check(
                "V-8",
                "ACC-G3-07",
                "close-position still reaches the broker while stopped",
                close_result.get("broker_calls") == 1 and close_result.get("exit_code") == 0,
                f"calls={close_result.get('broker_calls')} exit={close_result.get('exit_code')}",
            )
        )

        # V-9 — disarm remains refused.
        disarm = _run(
            [
                sys.executable,
                "-m",
                "trading_bot.app",
                "kill-switch",
                "--run-dir",
                str(tmp),
                "--disarm",
            ],
            cwd=tree,
            env=_env(tree),
        )
        add(
            Check(
                "V-9",
                "ACC-G3-10",
                "kill-switch --disarm exits 2 and does nothing",
                disarm.returncode == 2 and not (tmp / "KILL_SWITCH").exists(),
                f"exit={disarm.returncode}",
            )
        )

        # V-10 — G-1's gate is byte-identical: G-3 reused it, did not rewrite it.
        baseline = _run(["git", "show", f"{BASELINE_REV}:{HOT_STOP_REL}"], cwd=REPO_ROOT)
        current = (tree / HOT_STOP_REL).read_text(encoding="utf-8")
        add(
            Check(
                "V-10",
                "ACC-G3-10",
                "hot_stop.py is unchanged from the G-1 baseline",
                baseline.returncode == 0 and baseline.stdout == current,
                f"baseline_exit={baseline.returncode} equal={baseline.stdout == current}",
                {"sha256": hashlib.sha256(current.encode()).hexdigest()},
            )
        )

        # V-11 — regressions (G-1, G-2, CLI, focal).
        reg = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                *REGRESSION_SUITES,
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            cwd=tree,
            env=_env(tree),
        )
        summary = [line for line in reg.stdout.splitlines() if "passed" in line or "failed" in line]
        add(
            Check(
                "V-11",
                "ACC-G3-11",
                "focal + G-1/G-2/CLI suites pass on the exported tree",
                reg.returncode == 0,
                summary[-1] if summary else reg.stdout[-300:],
                {
                    "failed_tests": [
                        line for line in reg.stdout.splitlines() if line.startswith("FAILED")
                    ][:10]
                },
            )
        )

        # V-12 — the mutation matrix, if supplied, must show every property guarded.
        if args.report:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            variants = report.get("variants", [])
            killed = [v for v in variants if v.get("variant") != "baseline" and v.get("killed")]
            mutated = [v for v in variants if v.get("variant") != "baseline"]
            add(
                Check(
                    "V-12",
                    "ACC-G3-12",
                    "mutation matrix: baseline green, every mutant killed",
                    bool(report.get("baseline_green"))
                    and bool(mutated)
                    and len(killed) == len(mutated),
                    f"{len(killed)}/{len(mutated)} killed",
                    {"variants": [v.get("variant") for v in mutated]},
                )
            )
            # V-12b — the matrix must have run against this code, even when its
            # commit differs from the verified one (tools commit vs. code commit).
            matrix_rev = str(report.get("rev") or "")
            matrix_app = (
                _run(["git", "show", f"{matrix_rev}:{APP_REL}"], cwd=REPO_ROOT)
                if matrix_rev
                else None
            )
            tree_text = src_app.read_text(encoding="utf-8")
            same = bool(
                matrix_app
                and matrix_app.returncode == 0
                and hashlib.sha256(matrix_app.stdout.encode()).hexdigest()
                == hashlib.sha256(tree_text.encode()).hexdigest()
            )
            add(
                Check(
                    "V-12b",
                    "ACC-G3-12",
                    "the matrix ran against byte-identical app.py",
                    same,
                    f"matrix_rev={matrix_rev} same_app={same}",
                    {"matrix_rev": matrix_rev},
                )
            )
        else:
            add(
                Check(
                    "V-12",
                    "ACC-G3-12",
                    "mutation matrix supplied",
                    False,
                    "no --report given; the sensitivity of the suite was not verified",
                )
            )

        # V-13 — artefact hashes, when a report is offered.
        if args.report:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            declared = report.get("artifacts", {})
            mismatched: list[str] = []
            for rel, expected in declared.items():
                path = REPO_ROOT / rel
                if not path.is_file() or _sha(path) != expected:
                    mismatched.append(rel)
            add(
                Check(
                    "V-13",
                    "ACC-G3-13",
                    "reported artefact hashes match the files on disk",
                    bool(declared) and not mismatched,
                    f"{len(declared) - len(mismatched)}/{len(declared)} match",
                    {"mismatched": mismatched},
                )
            )
        else:
            add(
                Check(
                    "V-13",
                    "ACC-G3-13",
                    "artefact hashes supplied",
                    False,
                    "no --report given",
                )
            )
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    verdict = "G3_VERIFIED_SCOPED" if all(c.passed for c in checks) else "G3_PARTIAL"
    payload = {
        "tool": "verify_g3",
        "verdict": verdict,
        "independence": "PROCEDURALLY_SEPARATED (same author; different artefact)",
        "checkout": str(REPO_ROOT),
        "rev": args.rev or head,
        "branch": branch,
        "checks": [c.__dict__ for c in checks],
        "passed": sum(1 for c in checks if c.passed),
        "total": len(checks),
        "total_seconds": round(time.time() - started, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    text = json.dumps(payload, indent=2, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8")

    for check in checks:
        print(
            f"{check.check_id:<5} {'PASS' if check.passed else 'FAIL':<5} {check.criterion:<12} {check.detail}"
        )
    print(
        f"\n{payload['passed']}/{payload['total']} checks — {verdict} in {payload['total_seconds']}s"
    )
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
