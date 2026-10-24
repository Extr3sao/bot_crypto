"""Separate verifier for P0 — enforcement of LiveTradingGate on LIVE entry.

This script does not import the test module and does not read its assertions. It
exports the commit under review, re-derives the structural property from the
exported source, and drives each entrypoint in its own process with its own
scenarios. It also asks the exported package directly (a small ``python -c``)
for the verdict on a legal configuration, on high-severity failures and on a
short report — cases a critical-only reading of the gate would let through.

What that buys, and what it does not
------------------------------------
- It is a **different artefact** from the suite: a broken test cannot make it
  pass, and its scenarios are written against ``docs/audit/P0-LIVE-GATE.md``.
- It is **not** independent of the instrumentation: the recording clients come
  from ``scripts/audit/p0_live_gate_probe.py``, written by the same author. A
  probe that never recorded anything would fail V-3 (the positive control must
  show exactly one call), but the verifier cannot prove the real HTTP client
  would have been called — only that the path reaches the call site.
- It is **not** an organisational separation: same author. The verdict is
  therefore ``PROCEDURALLY_SEPARATED / VERIFIED_SCOPED``, never "independently
  audited".

Usage
-----
    uv run --frozen python scripts/audit/verify_p0_live_gate.py --rev <sha> --json out.json
    uv run --frozen python scripts/audit/verify_p0_live_gate.py --source worktree

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

#: G-1's gate. P0 must reuse it, not rewrite it.
BASELINE_REV = "a072da90ebedac71a11e8e301f3c6db3e0401733"
HOT_STOP_REL = "src/trading_bot/autonomous/hot_stop.py"
APP_REL = "src/trading_bot/app.py"
GATE_REL = "src/trading_bot/execution/live_gate.py"

GATE_IDS: tuple[str, ...] = tuple(f"GATE-{index:03d}" for index in range(1, 11))
ENTRY_POINTS: tuple[str, ...] = (
    "place-order-futures",
    "place-order-spot",
    "run-futures",
    "run-spot",
)
REDUCTION_POINTS: tuple[str, ...] = (
    "close-position",
    "set-tpsl",
    "place-order-futures-close",
    "place-order-spot-sell",
)

LIVE_SINKS = (
    "create_order",
    "place_order",
    "place_spot_order",
    "flash_close_position",
    "place_position_tpsl",
)

REGRESSION_SUITES = (
    "tests/unit/test_live_gate_enforcement.py",
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

#: Re-derives, inside the exported package, the three verdict properties that a
#: critical-only implementation would miss.
_VERDICT_PROBE = r"""
import json
from trading_bot import app
from trading_bot.execution.live_gate import GateReport, GateResult, LiveTradingGate
from trading_bot.market_data.fake import build_demo_settings

def legal():
    s = build_demo_settings(mode="live")
    return s.model_copy(update={
        "exchange": s.exchange.model_copy(update={"id": "bitunix", "sandbox": False,
                                                  "api_key": "k", "api_secret": "s"}),
        "risk": s.risk.model_copy(update={"kill_switch_enabled": True, "live_trading_enabled": False}),
        "runtime": s.runtime.model_copy(update={"mode": "live", "live_trading_enabled": True,
                                                "exchange_id": "bitunix"}),
    })

report = LiveTradingGate(legal(), credentials=("k", "s")).validate()
high = legal().model_copy(update={"risk": legal().risk.model_copy(update={"live_trading_enabled": True})})
db = legal().model_copy(update={"runtime": legal().runtime.model_copy(
    update={"storage": legal().runtime.storage.model_copy(
        update={"database_url": "sqlite:///p0-verifier-missing/db.sqlite"})})})
short_results = [GateResult(gate_id=f"GATE-{i:03d}", name="passing", passed=True,
                            severity="critical", message="ok") for i in range(1, 10)]
short = GateReport(all_passed=True, total_gates=9, passed_gates=9, failed_gates=0,
                   critical_failures=[], results=short_results)
original = LiveTradingGate.validate
LiveTradingGate.validate = lambda self: short
short_verdict = app._evaluate_live_gate(legal())
LiveTradingGate.validate = original
print(json.dumps({
    "gate_ids": [r.gate_id for r in report.results],
    "total_gates": report.total_gates,
    "all_passed": report.all_passed,
    "legal_allowed": app._evaluate_live_gate(legal()).allowed,
    "high_allowed": app._evaluate_live_gate(high).allowed,
    "high_failed": list(app._evaluate_live_gate(high).failed_gate_ids),
    "db_allowed": app._evaluate_live_gate(db).allowed,
    "db_failed": list(app._evaluate_live_gate(db).failed_gate_ids),
    "short_allowed": short_verdict.allowed,
    "short_reason": short_verdict.reason,
}))
"""


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
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _env(tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src"), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["P0_APP_SRC"] = str(tree / "src")
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
            str(tree / "scripts" / "audit" / "p0_live_gate_probe.py"),
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
    payload: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    payload["_returncode"] = completed.returncode
    return payload


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


def _no_false_success(payload: dict[str, Any]) -> bool:
    stdout = str(payload.get("stdout_tail") or "")
    markers = ("LIVE_ORDER_OK", "FUTURES_ORDER_OK", '"success": true', '"success":true')
    return not any(marker in stdout for marker in markers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0 independent re-derivation.")
    parser.add_argument("--rev", default=None)
    parser.add_argument("--source", choices=["archive", "worktree"], default="archive")
    parser.add_argument("--json", default=None)
    parser.add_argument("--report", default=None, help="RUN_REPORT.json whose hashes to check")
    parser.add_argument("--mutations", default=None, help="mutation matrix JSON")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    checks: list[Check] = []
    tmp = Path(tempfile.mkdtemp(prefix="p0-verify-"))
    head = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    branch = _run(["git", "branch", "--show-current"], cwd=REPO_ROOT).stdout.strip()
    dirty = [
        line
        for line in _run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.splitlines()
        if line.strip()
    ]
    dirty_source = [line for line in dirty if "src/" in line or "tests/" in line or "scripts/" in line]

    def add(check: Check) -> None:
        checks.append(check)

    try:
        tree = _export(args.rev, tmp / "tree", args.source)
        src_app = tree / APP_REL
        src_gate = tree / GATE_REL

        rev = args.rev or (head if args.source == "worktree" else "HEAD")
        add(
            Check(
                "V-1",
                "ACC-P0-14",
                "identity: commit, branch, no dirty source",
                src_app.is_file() and src_gate.is_file() and not dirty_source,
                f"rev={rev} branch={branch} dirty={len(dirty)} dirty_source={len(dirty_source)}",
                {
                    "rev": rev,
                    "head": head,
                    "branch": branch,
                    "dirty_paths": dirty,
                    "app_sha256": _sha(src_app) if src_app.is_file() else "",
                    "gate_sha256": _sha(src_gate) if src_gate.is_file() else "",
                },
            )
        )

        # V-2 — the structural property: every sink inside the boundary, every
        # boundary call declaring both its risk classification and its settings.
        app_tree = ast.parse(src_app.read_text(encoding="utf-8"))
        sinks = [
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LIVE_SINKS
        ]
        unguarded = [node.lineno for node in sinks if not _guarded(app_tree, node)]
        boundaries = [
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_live_order_boundary"
        ]
        incomplete = [
            node.lineno
            for node in boundaries
            if {"opens_risk", "settings"} - {keyword.arg for keyword in node.keywords}
        ]
        add(
            Check(
                "V-2",
                "ACC-P0-09/10",
                "7 sinks inside the boundary; 7 boundaries declare opens_risk and settings",
                len(sinks) == 7 and not unguarded and len(boundaries) == 7 and not incomplete,
                f"sinks={len(sinks)} unguarded={unguarded} boundaries={len(boundaries)} "
                f"incomplete={incomplete}",
                {"sinks": len(sinks), "boundaries": len(boundaries)},
            )
        )

        # V-3 — positive controls: a legal configuration still reaches the broker.
        control = _probe(tree, "place-order-futures", tmp / "ctl-entry")
        loop_control = _probe(tree, "run-futures", tmp / "ctl-loop")
        add(
            Check(
                "V-3",
                "ACC-P0-01",
                "legal config: place-order and run each send exactly one order",
                control.get("broker_calls") == 1
                and control.get("exit_code") == 0
                and loop_control.get("broker_calls") == 1
                and loop_control.get("exit_code") == 0,
                f"cli calls={control.get('broker_calls')} exit={control.get('exit_code')} "
                f"loop calls={loop_control.get('broker_calls')} exit={loop_control.get('exit_code')}",
                {"cli": control, "loop": loop_control},
            )
        )
        add(
            Check(
                "V-3b",
                "ACC-P0-15",
                "the probe loaded this export's app and the real gate module",
                control.get("app_file") == str(src_app.resolve())
                and control.get("gate_file") == str(src_gate.resolve())
                and control.get("patched", {}).get("futures") == "FakeFutures",
                f"app={control.get('app_file')} gate={control.get('gate_file')}",
                {"patched": control.get("patched")},
            )
        )

        # V-4 — each of the ten checks, rejected, stops the order.
        gate_results: list[dict[str, Any]] = []
        for gate_id in GATE_IDS:
            payload = _probe(tree, "place-order-futures", tmp / f"gate-{gate_id}", "--break", gate_id)
            gate_results.append(
                {
                    "gate": gate_id,
                    "calls": payload.get("broker_calls"),
                    "exit": payload.get("exit_code"),
                    "validations": payload.get("gate_validations"),
                    "named": gate_id in str(payload.get("stderr_tail") or ""),
                    "no_false_success": _no_false_success(payload),
                }
            )
        add(
            Check(
                "V-4",
                "ACC-P0-02/08",
                "a rejecting gate sends 0 orders, exits 2, names the gate and reports no success",
                all(
                    row["calls"] == 0
                    and row["exit"] == 2
                    and (row["validations"] or 0) >= 1
                    and row["named"]
                    and row["no_false_success"]
                    for row in gate_results
                ),
                "; ".join(
                    f"{row['gate']}=calls:{row['calls']}/exit:{row['exit']}"
                    f"/named:{row['named']}"
                    for row in gate_results
                ),
                {"rows": gate_results},
            )
        )

        # V-5 — every entrypoint that can open risk is covered.
        entry_results = [
            {
                "entrypoint": entrypoint,
                **{
                    key: value
                    for key, value in _probe(
                        tree, entrypoint, tmp / f"entry-{entrypoint}", "--break", "GATE-003"
                    ).items()
                    if key in {"broker_calls", "exit_code", "gate_validations", "stdout_tail"}
                },
            }
            for entrypoint in ENTRY_POINTS
        ]
        add(
            Check(
                "V-5",
                "ACC-P0-03",
                "all four entrypoints send 0 orders and exit 2 with a rejecting gate",
                all(
                    row["broker_calls"] == 0
                    and row["exit_code"] == 2
                    and (row.get("gate_validations") or 0) >= 1
                    for row in entry_results
                ),
                "; ".join(
                    f"{row['entrypoint']}=calls:{row['broker_calls']}/exit:{row['exit_code']}"
                    for row in entry_results
                ),
                {"rows": entry_results},
            )
        )

        # V-6 — reduction and protection are not trapped.
        reduction_results = [
            {
                "entrypoint": entrypoint,
                **{
                    key: value
                    for key, value in _probe(
                        tree, entrypoint, tmp / f"reduce-{entrypoint}", "--break", "GATE-004"
                    ).items()
                    if key in {"broker_calls", "exit_code", "gate_validations"}
                },
            }
            for entrypoint in REDUCTION_POINTS
        ]
        add(
            Check(
                "V-6",
                "ACC-P0-07",
                "close-position, set-tpsl, CLOSE and spot sell still reach the broker",
                all(
                    row["broker_calls"] == 1
                    and row["exit_code"] == 0
                    and (row.get("gate_validations") or 0) == 0
                    for row in reduction_results
                ),
                "; ".join(
                    f"{row['entrypoint']}=calls:{row['broker_calls']}/exit:{row['exit_code']}"
                    for row in reduction_results
                ),
                {"rows": reduction_results},
            )
        )

        # V-7 — fail closed on missing settings and on a gate that raises.
        settings_failures = [
            _probe(tree, entrypoint, tmp / f"badcfg-{entrypoint}", "--settings-error")
            for entrypoint in ("place-order-futures", "run-futures")
        ]
        crash_failures = [
            _probe(tree, entrypoint, tmp / f"crash-{entrypoint}", "--gate-crash")
            for entrypoint in ("place-order-spot", "run-spot")
        ]
        add(
            Check(
                "V-7",
                "ACC-P0-05",
                "unreadable settings and a crashing gate both send 0 orders and exit 2",
                all(
                    payload.get("broker_calls") == 0 and payload.get("exit_code") == 2
                    for payload in settings_failures + crash_failures
                ),
                "; ".join(
                    f"{payload.get('entrypoint')}=calls:{payload.get('broker_calls')}"
                    f"/exit:{payload.get('exit_code')}"
                    for payload in settings_failures + crash_failures
                ),
                {"settings": settings_failures, "crash": crash_failures},
            )
        )

        # V-8 — KILL_SWITCH keeps priority over the gate.
        priority_dir = tmp / "priority"
        priority_dir.mkdir(parents=True)
        (priority_dir / "KILL_SWITCH").write_text("p0 verifier\n", encoding="utf-8")
        priority = _probe(tree, "place-order-futures", priority_dir, "--break", "GATE-004")
        stderr = str(priority.get("stderr_tail") or "")
        add(
            Check(
                "V-8",
                "ACC-P0-06",
                "with a marker and a rejecting gate, the refusal names the stop, not the gate",
                priority.get("broker_calls") == 0
                and priority.get("exit_code") == 2
                and "kill_switch_engaged_hot" in stderr
                and "live_gate_blocked" not in stderr,
                f"calls={priority.get('broker_calls')} exit={priority.get('exit_code')} "
                f"stderr={stderr[-160:]!r}",
                {"stderr_tail": stderr[-400:]},
            )
        )

        # V-9 — the verdict properties a critical-only reading would miss.
        verdict_run = _run(
            [sys.executable, "-c", _VERDICT_PROBE],
            cwd=tree,
            env=_env(tree),
        )
        try:
            verdict = json.loads(verdict_run.stdout)
        except json.JSONDecodeError:
            verdict = {}
        add(
            Check(
                "V-9",
                "ACC-P0-02/05",
                "ten checks; legal passes; GATE-006/008 and a short report are refusals",
                verdict.get("gate_ids") == list(GATE_IDS)
                and verdict.get("total_gates") == 10
                and verdict.get("legal_allowed") is True
                and verdict.get("high_allowed") is False
                and "GATE-008" in (verdict.get("high_failed") or [])
                and verdict.get("db_allowed") is False
                and "GATE-006" in (verdict.get("db_failed") or [])
                and verdict.get("short_allowed") is False
                and str(verdict.get("short_reason", "")).startswith("live_gate_incomplete:"),
                f"verdict={verdict}",
                {"verdict": verdict, "stderr": verdict_run.stderr[-400:]},
            )
        )

        # V-11 — G-1's gate untouched; the hot stop is the one G-3 verified.
        baseline = subprocess.run(
            ["git", "show", f"{BASELINE_REV}:{HOT_STOP_REL}"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        current = (tree / HOT_STOP_REL).read_bytes()
        add(
            Check(
                "V-11",
                "ACC-P0-11",
                "hot_stop.py is byte-identical to the G-1 baseline",
                baseline.returncode == 0 and baseline.stdout == current,
                f"baseline_exit={baseline.returncode} equal={baseline.returncode == 0 and baseline.stdout == current}",
                {"sha256": hashlib.sha256(current).hexdigest()},
            )
        )

        # V-12 — no live trading enabled by the shipped configuration.
        runtime_yaml = (tree / "config" / "runtime.yaml").read_text(encoding="utf-8")
        risk_yaml = (tree / "config" / "risk.yaml").read_text(encoding="utf-8")
        add(
            Check(
                "V-12",
                "ACC-P0-13",
                "shipped config still declares live_trading_enabled: false",
                "live_trading_enabled: false" in runtime_yaml
                and "live_trading_enabled: false" in risk_yaml,
                "runtime/risk configuration",
            )
        )

        # V-13 — regressions (P0, G-3, CLI, autonomy).
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
                "V-13",
                "ACC-P0-12",
                "P0 + G-3 + CLI + autonomy suites pass on the export",
                reg.returncode == 0,
                summary[-1] if summary else reg.stdout[-300:],
                {
                    "failed_tests": [
                        line for line in reg.stdout.splitlines() if line.startswith("FAILED")
                    ][:10]
                },
            )
        )

        # V-14 — the mutation matrix, if supplied.
        if args.mutations:
            mutations = json.loads(Path(args.mutations).read_text(encoding="utf-8"))
            variants = mutations.get("variants", [])
            mutated = [v for v in variants if v.get("variant") != "baseline"]
            killed = [v for v in mutated if v.get("killed")]
            matrix_app = mutations.get("app_sha256")
            add(
                Check(
                    "V-14",
                    "ACC-P0-12",
                    "mutation matrix: baseline green, every mutant killed, same app.py",
                    bool(mutations.get("baseline_green"))
                    and bool(mutated)
                    and len(killed) == len(mutated)
                    and matrix_app == _sha(src_app),
                    f"{len(killed)}/{len(mutated)} killed; same_app={matrix_app == _sha(src_app)}",
                    {"variants": [v.get("variant") for v in mutated]},
                )
            )
        else:
            add(
                Check(
                    "V-14",
                    "ACC-P0-12",
                    "mutation matrix supplied",
                    False,
                    "no --mutations given; sensitivity of the suite was not verified",
                )
            )

        # V-15 — artefact hashes, when a report is offered.
        if args.report:
            report = json.loads(Path(args.report).read_text(encoding="utf-8"))
            declared = report.get("artifacts", {})
            mismatched = [
                rel
                for rel, expected in declared.items()
                if not (REPO_ROOT / rel).is_file() or _sha(REPO_ROOT / rel) != expected
            ]
            add(
                Check(
                    "V-15",
                    "ACC-P0-14",
                    "reported artefact hashes match the files on disk",
                    bool(declared) and not mismatched,
                    f"{len(declared) - len(mismatched)}/{len(declared)} match",
                    {"mismatched": mismatched},
                )
            )
        else:
            add(
                Check(
                    "V-15",
                    "ACC-P0-14",
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

    verdict = "P0_VERIFIED_SCOPED" if all(check.passed for check in checks) else "P0_PARTIAL"
    payload = {
        "tool": "verify_p0_live_gate",
        "verdict": verdict,
        "independence": "PROCEDURALLY_SEPARATED (same author; different artefact)",
        "checkout": str(REPO_ROOT),
        "rev": args.rev or head,
        "branch": branch,
        "checks": [check.__dict__ for check in checks],
        "passed": sum(1 for check in checks if check.passed),
        "total": len(checks),
        "total_seconds": round(time.time() - started, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    text = json.dumps(payload, indent=2, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8")

    for check in checks:
        print(f"{check.check_id:<5} {'PASS' if check.passed else 'FAIL':<5} {check.criterion:<12} {check.detail}")
    print(f"\n{payload['passed']}/{payload['total']} checks — {verdict} in {payload['total_seconds']}s")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
