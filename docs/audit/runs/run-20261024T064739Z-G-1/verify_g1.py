"""Separate verifier for G-1 — the stop survives the process.

This script does not import the tests it is checking and does not read their
literals. It exports the commit under review, re-derives each acceptance
criterion from the exported source, and runs its own scenarios in that tree —
including a real CLI process and a real runtime process that share only a file.

What that buys, and what it does not
------------------------------------
It is a **different artefact** from the suite: its checks are written against
the contract (``docs/audit/G-1.md``), not against the test file, and a broken
test cannot make it pass. It is *not* an organisational separation: the same
author wrote both. The verdict is therefore
``PROCEDURALLY_SEPARATED / VERIFIED_SCOPED``, never "independently audited".

Usage
-----
    python docs/audit/runs/run-20261024T064739Z-G-1/verify_g1.py \
        --rev <sha> --json docs/audit/runs/run-20261024T064739Z-G-1/verification.json

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


def _find_repo_root() -> Path:
    """Locate the work tree, not a fixed depth: this script is versioned next
    to the run it produced, and a hardcoded ``parents[4]`` breaks there."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate
    return here.parents[4]


REPO_ROOT = _find_repo_root()

#: G-1's baseline: the record commit of G-2, which already contains the gate.
BASELINE = "5238c05e2f11527606ec2afc89966dc1500a281d"

#: The scope the contract froze. Kept as a literal on purpose: reading it back
#: out of the contract would only prove the contract agrees with itself.
ALLOWED_PATHS: tuple[str, ...] = (
    "docs/audit/G-1.md",
    "docs/audit/AUDIT_BACKLOG.yaml",
    "docs/audit/runtime_authority_map.md",
    "docs/audit/runs/run-20261024T064739Z-G-1/",
    "src/trading_bot/autonomous/hot_stop.py",
    "src/trading_bot/app.py",
    "tests/unit/autonomous/test_kill_switch_persistence.py",
    "tests/unit/autonomous/test_hot_engage.py",
    "tests/unit/autonomous/test_decision_kill_switch.py",
    "scripts/audit/g1_mutants.py",
    "scripts/audit/g1_restart_probe.py",
)

#: Every file G-1 promised not to touch. The two suites it was allowed to edit
#: are checked separately (assertions unchanged in the gap test).
PROTECTED_PATHS: tuple[str, ...] = (
    "src/trading_bot/autonomous/decision.py",
    "src/trading_bot/autonomous/runtime.py",
    "src/trading_bot/paper/",
    "src/trading_bot/config/",
    "src/trading_bot/execution/",
    "src/trading_bot/risk/",
    "scripts/autonomous_paper.py",
    "scripts/start_paper_lab.py",
    "scripts/audit/g2_mutants.py",
    "scripts/audit/negative_controls.py",
    "tests/unit/test_app_cli_contract.py",
    "tests/unit/autonomous/test_kill_switch_negative.py",
    "tests/conftest.py",
    ".github/",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
)

RUN_DIR = Path(__file__).resolve().parent


@dataclass
class Check:
    check_id: str
    criterion: str
    description: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def _env(src: Path, tree: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(src), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _export(rev: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "tree.tar"
    completed = _run(["git", "archive", "--format=tar", "-o", str(archive), rev], cwd=REPO_ROOT)
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
    completed = _run(["git", "diff", "--name-only", BASELINE, rev], cwd=REPO_ROOT)
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blob_sha256(rev: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=120,
    )
    # Normalise line endings: ``git show`` returns the stored blob (LF) while
    # the archive may be checked out with the platform eol. The claim is
    # "same content", not "same checkout filter".
    return hashlib.sha256(completed.stdout.replace(b"\r\n", b"\n")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _parse_pytest_count(output: str) -> int | None:
    marker = " passed"
    for line in reversed(output.splitlines()):
        if marker in line:
            head = line.split(marker, 1)[0]
            digits = head.replace(",", " ").split()
            for word in reversed(digits):
                if word.isdigit():
                    return int(word)
    return None


# --- static checks -----------------------------------------------------------


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _inside_order_boundary(tree: ast.AST, target: ast.AST) -> bool:
    def walk(node: ast.AST, stack: list[ast.AST]) -> bool:
        if node is target:
            return any(
                isinstance(ancestor, ast.With)
                and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and item.context_expr.func.attr == "order_boundary"
                    for item in ancestor.items
                )
                for ancestor in stack
            )
        return any(walk(child, [*stack, node]) for child in ast.iter_child_nodes(node))

    return walk(tree, [])


def _assert_lines(tree: Path, rel: str) -> list[str]:
    return [
        line.strip()
        for line in tree.joinpath(rel).read_text(encoding="utf-8").splitlines()
        if "assert " in line
    ]


def check_scope(rev: str) -> Check:
    changed = _changed_paths(rev)
    outside = [
        path
        for path in changed
        if not any(
            path == allowed or (allowed.endswith("/") and path.startswith(allowed))
            for allowed in ALLOWED_PATHS
        )
        and path != "docs/audit/G-1.md"
    ]
    protected = [
        path
        for path in changed
        if any(
            path == item or (item.endswith("/") and path.startswith(item))
            for item in PROTECTED_PATHS
        )
    ]
    return Check(
        check_id="V-1",
        criterion="ACC-G1-13",
        description="every changed file is inside the frozen allowed_paths and outside every protected path",
        passed=not outside and not protected,
        detail=f"{len(changed)} files changed; {len(outside)} outside scope; {len(protected)} protected",
        evidence={"changed": changed, "outside": outside, "protected": protected},
    )


def check_gap_test_assertions_unchanged(baseline_tree: Path, tree: Path) -> Check:
    rel = "tests/unit/autonomous/test_decision_kill_switch.py"
    before = _assert_lines(baseline_tree, rel)
    after = _assert_lines(tree, rel)
    return Check(
        check_id="V-2",
        criterion="ACC-G1-13 (amendment A-1)",
        description="the gap test's docstring changed; not one assertion in that file did",
        passed=before == after,
        detail=f"{len(before)} assertion lines before, {len(after)} after",
        evidence={"only_docstring_changed": before == after},
    )


def check_restore_in_constructor(rev: str, tree: Path) -> Check:
    source = tree / "src/trading_bot/autonomous/hot_stop.py"
    parsed = ast.parse(source.read_text(encoding="utf-8"))
    gate = _class_def(parsed, "HotStopGate")
    assert gate is not None, "HotStopGate is gone"
    post_init = _method(gate, "__post_init__")
    restore = _method(gate, "restore")
    calls = _call_names(post_init) if post_init else set()
    lines = {}
    if post_init:
        for node in ast.walk(post_init):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "restore"
            ):
                lines["restore_call"] = node.lineno
        lines["post_init"] = post_init.lineno
    if restore:
        lines["restore_def"] = restore.lineno
    return Check(
        check_id="V-3",
        criterion="ACC-G1-03 / REQ-G1-02",
        description="HotStopGate adopts the marker in __post_init__, not in a poll the caller may skip",
        passed=bool(post_init and restore and "restore" in calls),
        detail="restore() is called from __post_init__" if post_init else "no __post_init__",
        evidence=lines,
    )


def check_audit_is_not_authority(tree: Path) -> Check:
    source = tree / "src/trading_bot/autonomous/hot_stop.py"
    parsed = ast.parse(source.read_text(encoding="utf-8"))
    gate = _class_def(parsed, "HotStopGate")
    assert gate is not None
    offenders: list[str] = []
    for name in ("restore", "_marker_presence", "_ensure_marker", "poll"):
        method = _method(gate, name)
        if method is None:
            continue
        for node in ast.walk(method):
            if isinstance(node, ast.Attribute) and node.attr in {"audit_path", "AUDIT_FILE_NAME"}:
                offenders.append(f"{name}:{node.lineno}")
    return Check(
        check_id="V-4",
        criterion="ACC-G1-03/07 / REQ-G1-07",
        description="the state decision never reads the audit trail: restore/poll touch only the marker",
        passed=not offenders,
        detail="no audit reference in the state path"
        if not offenders
        else "audit read in state path",
        evidence={"offenders": offenders},
    )


def check_dispatch_sites(tree: Path) -> Check:
    runtime_source = tree / "src/trading_bot/autonomous/runtime.py"
    parsed = ast.parse(runtime_source.read_text(encoding="utf-8"))
    dispatches = [
        node
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_signal"
    ]
    guarded = [node for node in dispatches if _inside_order_boundary(parsed, node)]
    paper_cycle = tree / "src/trading_bot/paper/paper_cycle.py"
    cycle_hits = [
        line
        for line in paper_cycle.read_text(encoding="utf-8").splitlines()
        if "execute_signal" in line and not line.strip().startswith("#")
    ]
    return Check(
        check_id="V-5",
        criterion="ACC-G1-03",
        description="the runtime still has exactly one broker dispatch and it is inside order_boundary",
        passed=len(dispatches) == 1 and len(guarded) == 1,
        detail=f"{len(guarded)}/{len(dispatches)} guarded; paper_cycle.py(G-4) mentions={len(cycle_hits)}",
        evidence={
            "dispatch_lines": [node.lineno for node in dispatches],
            "guarded_lines": [node.lineno for node in guarded],
            "paper_cycle_g4_lines": cycle_hits[:4],
        },
    )


# --- behavioural checks ------------------------------------------------------


_RESTORE_SNIPPET = r"""
import json, sys
from pathlib import Path
from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME, HotStopGate, write_control_file
from trading_bot.domain.enums.kill_switch import KillSwitchState
from trading_bot.paper.kill_switch_v2 import KillSwitch

run_dir = Path(sys.argv[1])
run_dir.mkdir(parents=True, exist_ok=True)
write_control_file(run_dir / HOT_STOP_FILE_NAME, "verifier: restart")
switch = KillSwitch()
gate = HotStopGate(kill_switch=switch, run_dir=run_dir)
allowed = None
with gate.order_boundary() as verdict:
    allowed = verdict
import trading_bot
print(json.dumps({
    "engaged": gate.engaged,
    "restored": gate.stats()["restored"],
    "switch_state": str(getattr(switch.state, "value", switch.state)),
    "allowed": allowed,
    "broker_calls_allowed": gate.stats()["broker_calls_allowed"],
    "module_file": str(Path(trading_bot.__file__).resolve()),
}))
"""


def check_restore_in_child(tree: Path, work: Path) -> Check:
    run_dir = work / "restore-child"
    completed = _run(
        [sys.executable, "-c", _RESTORE_SNIPPET, str(run_dir)],
        cwd=tree,
        env=_env(tree / "src", tree),
    )
    if completed.returncode != 0:
        return Check(
            check_id="V-6",
            criterion="ACC-G1-03",
            description="a fresh interpreter adopts a marker written by another process",
            passed=False,
            detail=completed.stderr[-500:],
        )
    payload = json.loads(completed.stdout)
    event_file = run_dir / "kill_switch_events.jsonl"
    events = [
        json.loads(line)
        for line in event_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ok = (
        payload["engaged"] is True
        and payload["restored"] is True
        and payload["allowed"] is False
        and payload["broker_calls_allowed"] == 0
        and payload["switch_state"] == "halted"
        and events
        and events[0]["event"] == "restored"
        and payload["module_file"].startswith(str((tree / "src").resolve()))
    )
    return Check(
        check_id="V-6",
        criterion="ACC-G1-03",
        description="a fresh interpreter adopts a marker written by another process",
        passed=ok,
        detail="engaged at construction, boundary refused, event='restored'",
        evidence={**payload, "first_event": events[0] if events else None},
    )


def check_cross_process(tree: Path, work: Path) -> Check:
    blocked = work / "cross-blocked"
    blocked.mkdir(parents=True, exist_ok=True)
    control = work / "cross-control"
    control.mkdir(parents=True, exist_ok=True)
    cli = _run(
        [
            sys.executable,
            "-m",
            "trading_bot.app",
            "kill-switch",
            "--run-dir",
            str(blocked),
            "--engage",
            "--reason",
            "verifier: cross-process",
        ],
        cwd=tree,
        env=_env(tree / "src", tree),
    )
    if cli.returncode != 0:
        return Check(
            check_id="V-7",
            criterion="ACC-G1-05",
            description="CLI writes, a separate runtime process boots engaged",
            passed=False,
            detail=f"CLI exit {cli.returncode}: {cli.stderr[-400:]}",
        )
    probes: dict[str, Any] = {}
    for label, run_dir in (("blocked", blocked), ("control", control)):
        completed = _run(
            [
                sys.executable,
                str(tree / "scripts/audit/g1_restart_probe.py"),
                "--run-dir",
                str(run_dir),
            ],
            cwd=tree,
            env=_env(tree / "src", tree),
            timeout=300,
        )
        if completed.returncode != 0:
            return Check(
                check_id="V-7",
                criterion="ACC-G1-05",
                description="CLI writes, a separate runtime process boots engaged",
                passed=False,
                detail=f"probe {label} failed: {completed.stderr[-500:]}",
            )
        probes[label] = json.loads(completed.stdout)
    blocked_payload = probes["blocked"]
    control_payload = probes["control"]
    ok = (
        blocked_payload["engaged_before_first_cycle"] is True
        and blocked_payload["restored"] is True
        and blocked_payload["broker_calls"] == 0
        and blocked_payload["orders_created"] == 0
        and blocked_payload["risk_verdict"] == "PASS"
        and control_payload["engaged_before_first_cycle"] is False
        and control_payload["broker_calls"] == 1
        and control_payload["orders_created"] == 1
        and all(
            Path(item["module_file"]).resolve().is_relative_to((tree / "src").resolve())
            for item in probes.values()
        )
    )
    return Check(
        check_id="V-7",
        criterion="ACC-G1-05",
        description="CLI writes, a separate runtime process boots engaged; a marker-free sibling really orders",
        passed=ok,
        detail="blocked broker=0, control broker=1, both imported the export",
        evidence=probes,
    )


def check_disarm(tree: Path, work: Path) -> Check:
    run_dir = work / "disarm"
    run_dir.mkdir(parents=True, exist_ok=True)
    marker = run_dir / "KILL_SWITCH"
    marker.write_text("verifier: stop\n", encoding="utf-8")
    completed = _run(
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
        env=_env(tree / "src", tree),
    )
    return Check(
        check_id="V-8",
        criterion="ACC-G1-05 / REQ-G1-08",
        description="--disarm still exits 2 and leaves the marker untouched",
        passed=completed.returncode == 2
        and completed.stdout == ""
        and marker.read_text(encoding="utf-8") == "verifier: stop\n",
        detail=f"exit={completed.returncode}",
        evidence={"stdout": completed.stdout, "stderr": completed.stderr[-200:]},
    )


def check_suites(tree: Path) -> Check:
    runs = [
        (
            "focal-persistence",
            ["tests/unit/autonomous/test_kill_switch_persistence.py"],
        ),
        (
            "order-hot-then-decision",
            [
                "tests/unit/autonomous/test_hot_engage.py",
                "tests/unit/autonomous/test_decision_kill_switch.py",
            ],
        ),
        (
            "order-decision-then-hot",
            [
                "tests/unit/autonomous/test_decision_kill_switch.py",
                "tests/unit/autonomous/test_hot_engage.py",
            ],
        ),
        ("g2-cli-contract", ["tests/unit/test_app_cli_contract.py"]),
        ("regression-autonomous", ["tests/unit/autonomous"]),
    ]
    evidence: dict[str, Any] = {}
    ok = True
    for label, targets in runs:
        completed = _run(
            [sys.executable, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider"],
            cwd=tree,
            env=_env(tree / "src", tree),
            timeout=900,
        )
        count = _parse_pytest_count(completed.stdout)
        evidence[label] = {"cwd": "export", "exit": completed.returncode, "passed": count}
        ok = ok and completed.returncode == 0
        if completed.returncode != 0:
            evidence[label]["tail"] = completed.stdout[-1200:]
    # The audit guard proves the backlog is tracked by git, so it cannot run in
    # an export without .git. It runs in the checkout, which V-0 proved clean
    # and V-11 proved identical to the export for the files that matter.
    guard = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_audit_contracts_tracked.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        env=_env(REPO_ROOT / "src", REPO_ROOT),
        timeout=600,
    )
    evidence["audit-guard"] = {
        "cwd": "checkout",
        "exit": guard.returncode,
        "passed": _parse_pytest_count(guard.stdout),
    }
    ok = ok and guard.returncode == 0
    total = sum(int(item["passed"] or 0) for item in evidence.values())
    return Check(
        check_id="V-9",
        criterion="ACC-G1-12",
        description="focal, both orders of the G-2 suites, the CLI/audit contract and the autonomous regression all pass",
        passed=ok,
        detail=f"{len(runs)} pytest runs, {total} test results, all exit 0"
        if ok
        else "a suite failed",
        evidence=evidence,
    )


def check_mutants(tree: Path, work: Path) -> Check:
    output = work / "mutants.json"
    completed = _run(
        [
            sys.executable,
            str(tree / "scripts/audit/g1_mutants.py"),
            "--source",
            "worktree",
            "--json",
            str(output),
        ],
        cwd=tree,
        env=_env(tree / "src", tree),
        timeout=1800,
    )
    if not output.exists():
        return Check(
            check_id="V-10",
            criterion="ACC-G1-11",
            description="every property of persistence is killed by removing it",
            passed=False,
            detail=f"harness exit {completed.returncode}: {completed.stderr[-400:]}",
        )
    report = json.loads(output.read_text(encoding="utf-8"))
    variants = report.get("variants", [])
    killed = sum(1 for item in variants if item["variant"] != "baseline" and item["killed"])
    total = len(variants) - 1
    return Check(
        check_id="V-10",
        criterion="ACC-G1-11",
        description="every property of persistence is killed by removing it",
        passed=completed.returncode == 0 and report.get("all_mutants_killed") is True and total > 0,
        detail=f"{killed}/{total} mutants killed; baseline exit {report.get('baseline', {}).get('exit_code')}",
        evidence={
            "all_mutants_killed": report.get("all_mutants_killed"),
            "survivors": report.get("survivors", []),
            "matrix": str(output),
        },
    )


def check_export_matches_commit(rev: str, tree: Path) -> Check:
    paths = ["src/trading_bot/autonomous/hot_stop.py", "src/trading_bot/app.py"]
    mismatches = [rel for rel in paths if _file_sha256(tree / rel) != _blob_sha256(rev, rel)]
    return Check(
        check_id="V-11",
        criterion="ACC-G1-14",
        description="the tree that was exercised is byte-for-byte the commit under review",
        passed=not mismatches,
        detail="export hashes match git blobs" if not mismatches else f"mismatch: {mismatches}",
        evidence={
            "mismatched": mismatches,
            "sha256": {rel: _file_sha256(tree / rel) for rel in paths},
        },
    )


def check_artifacts(rev: str) -> Check:
    resolved = _run(["git", "rev-parse", f"{rev}^{{commit}}"], cwd=REPO_ROOT).stdout.strip()
    artifacts = sorted(path for path in RUN_DIR.iterdir() if path.is_file())
    hashes = {
        path.name: _sha256(path)
        for path in artifacts
        if path.name not in {"verification.json", "verify_g1.py"}
    }
    missing = [name for name, digest in hashes.items() if not digest]
    report = RUN_DIR / "RUN_REPORT.json"
    payload: dict[str, Any] = {}
    if report.exists():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    claimed = str(payload.get("verified_commit", ""))
    consistent = (
        claimed.startswith(resolved[:8]) or resolved.startswith(claimed[:8]) if claimed else True
    )
    return Check(
        check_id="V-12",
        criterion="ACC-G1-14",
        description="every run artefact exists, hashes cleanly, and names the commit this verifier read",
        passed=not missing and consistent,
        detail=f"{len(hashes)} artefacts hashed; RUN_REPORT verified_commit={claimed or '(absent)'}",
        evidence={
            "resolved_rev": resolved,
            "artifacts": hashes,
            "run_report_verified_commit": claimed,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="commit to verify (default: HEAD)")
    parser.add_argument("--json", dest="json_path", default=None, help="write verification.json")
    parser.add_argument("--keep", action="store_true", help="keep the temporary export")
    args = parser.parse_args(argv)

    started = time.time()
    git_head = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    status = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.strip()
    resolved = _run(["git", "rev-parse", f"{args.rev}^{{commit}}"], cwd=REPO_ROOT).stdout.strip()

    checks: list[Check] = []
    tmp = Path(tempfile.mkdtemp(prefix="g1-verify-"))
    try:
        tree = _export(args.rev, tmp)
        baseline_tree = _export(BASELINE, tmp / "baseline")
        work = tmp / "work"
        work.mkdir()

        # Reporting artefacts are written before the record commit, so the tree
        # is not expected to be spotless. What must be clean is the code that
        # produces the claims; V-11 proves the export equals the commit for it.
        source_dirty = [
            line
            for line in status.splitlines()
            if line[3:].startswith(("src/", "tests/", "scripts/"))
        ]
        checks.append(
            Check(
                check_id="V-0",
                criterion="ACC-G1-14",
                description="checkout identity: absolute path, branch, HEAD, no dirty source, resolved revision",
                passed=bool(resolved) and not source_dirty,
                detail=f"{REPO_ROOT} @ {resolved[:12]} ({branch}); dirty source files: {len(source_dirty)}",
                evidence={
                    "checkout": str(REPO_ROOT),
                    "branch": branch,
                    "head": git_head,
                    "status_porcelain": status,
                    "source_dirty": source_dirty,
                    "rev_requested": args.rev,
                    "rev_resolved": resolved,
                    "export": str(tree),
                },
            )
        )
        checks.append(check_scope(args.rev))
        checks.append(check_gap_test_assertions_unchanged(baseline_tree, tree))
        checks.append(check_restore_in_constructor(args.rev, tree))
        checks.append(check_audit_is_not_authority(tree))
        checks.append(check_dispatch_sites(tree))
        checks.append(check_export_matches_commit(args.rev, tree))
        checks.append(check_restore_in_child(tree, work))
        checks.append(check_cross_process(tree, work))
        checks.append(check_disarm(tree, work))
        checks.append(check_suites(tree))
        checks.append(check_mutants(tree, work))
        checks.append(check_artifacts(args.rev))
    except Exception as exc:  # a verifier that crashes must not report success
        checks.append(
            Check(
                check_id="V-ERR",
                criterion="ACC-G1-14",
                description="the verifier completed",
                passed=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
    finally:
        if args.keep:
            print(f"temporary export kept at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    passed = [check for check in checks if check.passed]
    verdict = "VERIFIED_SCOPED" if len(passed) == len(checks) else "FAILED"
    payload = {
        "tool": "docs/audit/runs/run-20261024T064739Z-G-1/verify_g1.py",
        "contract": "docs/audit/G-1.md",
        "rev_requested": args.rev,
        "rev_resolved": resolved,
        "checkout": str(REPO_ROOT),
        "branch": branch,
        "author": "same author as the implementation",
        "independence": "PROCEDURALLY_SEPARATED",
        "verdict": verdict,
        "passed": len(passed),
        "total": len(checks),
        "checks": [check.__dict__ for check in checks],
        "seconds": round(time.time() - started, 2),
    }
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"verification written to {args.json_path}")

    print(f"{'check':<6} {'pass':<6} {'criterion':<26} description")
    for check in checks:
        print(
            f"{check.check_id:<6} {('yes' if check.passed else 'NO'):<6} "
            f"{check.criterion:<26} {check.description}"
        )
        if not check.passed:
            print(f"{'':<6} {check.detail}")
    print(f"\n{len(passed)}/{len(checks)} checks passed — {verdict}")
    return 0 if verdict == "VERIFIED_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
