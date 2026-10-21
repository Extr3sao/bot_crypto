"""exp_003p_pipeline — the ordered entry points of EXP-003P.

Each phase is also a script of its own; this module fixes the order and records what each
one actually did. ``all`` refuses to skip a failing phase: a green report built on a red
step is the failure mode this experiment exists to make impossible.

    python scripts/exp_003p_pipeline.py status
    python scripts/exp_003p_pipeline.py all
    python scripts/exp_003p_pipeline.py tests
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003p_contract import OUT, RUN_ID, git, read_json, sha256_file, write_json  # noqa: E402

PYTHON = sys.executable
ARTEFACTS = (
    "BASELINE.md",
    "runtime_authority_map.md",
    "WORK_PACKAGES.md",
    "RFC-EXP-003P-PAPER-EXECUTION.md",
    "design/PROTOCOL.json",
    "design/PREREGISTRATION.md",
    "design/DESIGN.sha256",
    "design/PAPER_INTEGRATION_PLAN.md",
    "ORDER_EVENT_SCHEMA.md",
    "ORDER_EVENT_SCHEMA.json",
    "STATE_MACHINE.md",
    "EXECUTION_TRACE.jsonl",
    "SCENARIO_TRACE.jsonl",
    "ORDER_LIFECYCLE.csv",
    "ORDER_LIFECYCLE.json",
    "RECONCILIATION.json",
    "METRICS.json",
    "NEGATIVE_CONTROLS.json",
    "INDEPENDENCE_AUDIT.json",
    "INDEPENDENCE_AUDIT.md",
    "VERIFICATION.json",
    "DIGESTS.json",
    "REHEARSAL.json",
    "evidence/BASELINE.json",
    "evidence/TESTS.json",
    "evidence/CLEAN_CHECKOUT_REPRODUCTION.json",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "SHA256SUMS.txt",
)

RUFF_TARGETS = (
    "src/trading_bot/paper/lifecycle",
    "scripts/exp_003p_baseline.py",
    "scripts/exp_003p_preregister.py",
    "scripts/exp_003p_schema.py",
    "scripts/exp_003p_rehearsal.py",
    "scripts/exp_003p_controls.py",
    "scripts/exp_003p_verify.py",
    "scripts/exp_003p_report.py",
    "scripts/exp_003p_contract.py",
    "scripts/exp_003p_pipeline.py",
    "scripts/exp_003p_checkout_compare.py",
    "tests/unit/paper/test_execution_lifecycle.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/vision/lane.py",
)


def _run(args: list[str], *, label: str) -> int:
    print(f"[003p-pipeline] {label}: {Path(args[0]).name} {' '.join(args[1:])}".rstrip())
    completed = subprocess.run([PYTHON, *args], cwd=str(REPO), check=False)
    if completed.returncode != 0:
        print(f"[003p-pipeline] FAIL — {label} exited {completed.returncode}", file=sys.stderr)
    return int(completed.returncode)


def _capture(command: list[str], *, log: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(REPO), capture_output=True, text=True, check=False)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        completed.stdout + "\n" + completed.stderr, encoding="utf-8", newline="\n"
    )
    tail = [
        line for line in (completed.stdout.strip().splitlines() or [""]) if line.strip()
    ][-3:]
    return {"command": " ".join(command), "exit_code": completed.returncode, "tail": tail}


def run_tests(out: Path) -> int:
    """The suites and gates that matter, with their real exit codes."""

    evidence = out / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "executed_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "suites": [
            "tests/unit/paper",
            "tests/unit/reports",
        ],
    }
    commands = {
        "pytest_paper": [
            PYTHON,
            "-m",
            "pytest",
            "tests/unit/paper",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        "pytest_reports": [
            PYTHON,
            "-m",
            "pytest",
            "tests/unit/reports",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        "ruff": [PYTHON, "-m", "ruff", "check", *RUFF_TARGETS],
        "mypy": [PYTHON, "-m", "mypy", "--strict", "src/trading_bot/paper/lifecycle"],
    }
    failed: list[str] = []
    collected: dict[str, Any] = {}
    for name, command in commands.items():
        result = _capture(command, log=evidence / f"{name}.log")
        collected[name] = result
        if result["exit_code"] != 0:
            failed.append(name)
    tests = {
        **results,
        "state": "PASS" if not failed else "FAIL",
        "failed": failed,
        "results": collected,
    }
    write_json(evidence / "TESTS.json", tests)
    print(
        "[003p-pipeline] tests "
        f"{tests['state']} "
        + json.dumps(
            {name: value["exit_code"] for name, value in collected.items()}
        )
    )
    return 0 if not failed else 4


def run_checkout_check(
    out: Path, install_command: str = "not recorded", requirements: str | None = None
) -> int:
    """Reproduce the run from a detached worktree at HEAD and compare the two directories.

    The rehearsal is executed *in the checkout* by the checkout's own interpreter, and the
    verdict comes from `exp_003p_checkout_compare.py` reading both trees — never from this
    process comparing a file it just wrote with itself. A worktree that cannot carry the
    code is recorded as NOT_PERFORMED, not as a pass.
    """

    evidence = out / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{head}:src/trading_bot/paper/lifecycle/store.py"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    present_at_head = probe.returncode == 0
    payload: dict[str, Any] = {
        "schema_version": "AI_BOTS_003P_CHECKOUT_REPRODUCTION_V1",
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": head,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_lines": len([line for line in git("status", "--porcelain").splitlines() if line.strip()]),
        "lifecycle_modules_present_at_head": present_at_head,
    }
    if not present_at_head:
        payload["verdict"] = "NOT_PERFORMED"
        payload["detail"] = (
            "HEAD does not contain the 003P modules: the experiment's code is in the working "
            "tree and has not been committed. A clean checkout would reproduce nothing."
        )
        payload["substitute_evidence"] = {
            "two_runs_identical": (
                read_json(out / "DIGESTS.json").get("run_digest")
                == read_json(out / "runs" / "run-2" / "DIGESTS.json").get("run_digest")
            ),
            "run_digest": read_json(out / "DIGESTS.json").get("run_digest"),
            "second_run_digest": read_json(out / "runs" / "run-2" / "DIGESTS.json").get(
                "run_digest"
            ),
        }
        payload["reports_ignored_by"] = ".gitignore:463 'reports/ai-bots/*'"
        payload["artifact_note"] = (
            "artifacts under reports/ai-bots are git-ignored; publishing them needs "
            "'git add -f', and the worktree check needs them force-added to HEAD"
        )
        payload["commands_after_commit"] = [
            "git add -f reports/ai-bots/EXP-003P-PAPER-EXECUTION-001",
            "git worktree add --detach ../003p-checkout HEAD",
            "cp -r reports/ai-bots/EXP-003K-CANDIDATE-001/dataset ../003p-checkout/reports/"
            "ai-bots/EXP-003K-CANDIDATE-001/",
            "cd ../003p-checkout && python scripts/exp_003p_rehearsal.py --checkout-check",
            "compare DIGESTS.json run_digest with this run",
        ]
        write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
        print(
            "[003p-pipeline] checkout NOT_PERFORMED — HEAD lacks the 003P modules "
            f"({head[:12]}); two-run determinism substituted and declared"
        )
        return 0
    worktree = REPO.parent / "003p-checkout"
    if worktree.resolve() == REPO.resolve():
        # Executed from inside the checkout: the "worktree" is the tree we are standing in,
        # so the rehearsal would overwrite the published artifacts and the digest comparison
        # would compare a file with itself. That is a green verdict for reproducing nothing.
        payload["verdict"] = "REFUSED_SELF_COMPARISON"
        payload["detail"] = (
            "this process runs inside the checkout path it would have created; comparing it "
            "with itself proves nothing. Run the gate from the publishing tree, or compare "
            "two directories with scripts/exp_003p_checkout_compare.py."
        )
        write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
        print("[003p-pipeline] REFUSED — this is the checkout itself, not a copy of it")
        return 7
    added = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), head],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        # Reuse an existing checkout only when it already sits on the commit under test;
        # anything else reproduces a different tree and must not be compared.
        there = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
        )
        if there.returncode != 0 or there.stdout.strip() != head:
            payload["verdict"] = "FAILED"
            payload["detail"] = (
                f"worktree {worktree} exists but is not at {head}: {added.stderr.strip()}"
            )
            write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
            print("[003p-pipeline] checkout FAILED — the worktree exists at another commit")
            return 5
    python = worktree / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")
    if not python.exists():
        payload["verdict"] = "FAILED"
        payload["detail"] = (
            f"no interpreter at {python}: install the checkout's dependencies first (the "
            "committed uv.lock cannot satisfy `uv sync --locked`, see FINAL_REPORT), then "
            "re-run this phase"
        )
        write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
        print("[003p-pipeline] checkout FAILED — the worktree has no environment")
        return 5

    reproduced_out = worktree / "reports" / "ai-bots" / out.name
    phases: tuple[list[str], ...] = (
        ["scripts/exp_003p_baseline.py", "--out", str(reproduced_out)],
        ["scripts/exp_003p_preregister.py"],
        ["scripts/exp_003p_schema.py", "--out", str(reproduced_out)],
        ["scripts/exp_003p_rehearsal.py", "--out", str(reproduced_out)],
        [
            "scripts/exp_003p_rehearsal.py",
            "--out",
            str(reproduced_out / "runs" / "run-2"),
        ],
        [
            "scripts/exp_003p_controls.py",
            "--out",
            str(reproduced_out / "NEGATIVE_CONTROLS.json"),
        ],
        ["scripts/exp_003p_verify.py", "--out", str(reproduced_out)],
    )
    executed: list[dict[str, Any]] = []
    for phase in phases:
        done = subprocess.run(
            [str(python), *phase], cwd=str(worktree), capture_output=True, text=True, check=False
        )
        executed.append({"script": phase[0], "exit_code": done.returncode})
        if done.returncode != 0:
            payload["verdict"] = "FAILED"
            payload["detail"] = f"{phase[0]} exited {done.returncode} inside the checkout"
            payload["phases"] = executed
            payload["stderr_tail"] = done.stderr.strip().splitlines()[-6:]
            write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
            print(f"[003p-pipeline] checkout FAILED — {phase[0]} exited {done.returncode}")
            return 5

    comparison = subprocess.run(
        [
            PYTHON,
            str(REPO / "scripts" / "exp_003p_checkout_compare.py"),
            "--published",
            str(out),
            "--reproduced",
            str(reproduced_out),
            "--out",
            str(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json"),
            "--worktree",
            str(worktree),
            "--checkout-commit",
            head,
            "--install-command",
            install_command,
        ]
        + (["--requirements", requirements] if requirements else []),
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    payload["phases"] = executed
    print(
        "[003p-pipeline] checkout "
        f"{'REPRODUCED' if comparison.returncode == 0 else 'FAILED'} "
        f"worktree={worktree} (kept for inspection)"
    )
    if comparison.returncode != 0:
        print(comparison.stdout.strip() or comparison.stderr.strip())
    return 0 if comparison.returncode == 0 else 5


def rehearse(out: Path) -> int:
    first = _run(
        [str(REPO / "scripts" / "exp_003p_rehearsal.py"), "--out", str(out)], label="rehearsal-1"
    )
    if first != 0:
        return first
    second_out = out / "runs" / "run-2"
    second = _run(
        [str(REPO / "scripts" / "exp_003p_rehearsal.py"), "--out", str(second_out)],
        label="rehearsal-2",
    )
    if second != 0:
        return second
    keys = (
        "execution_trace_sha256",
        "scenario_trace_sha256",
        "lifecycle_csv_sha256",
        "ledger_digest_runtime",
        "ledger_digest_scenario",
        "run_digest",
    )
    a = read_json(out / "DIGESTS.json")
    b = read_json(second_out / "DIGESTS.json")
    differences = [key for key in keys if a.get(key) != b.get(key)]
    print(
        f"[003p-pipeline] determinism {'PASS' if not differences else 'FAIL'} "
        f"differences={differences} run_digest={a['run_digest'][:18]}…"
    )
    return 0 if not differences else 6


def status(out: Path) -> int:
    print(
        f"[003p-pipeline] run={out.name} branch={git('rev-parse', '--abbrev-ref', 'HEAD')} "
        f"head={git('rev-parse', '--short', 'HEAD')}"
    )
    for name in ARTEFACTS:
        path = out / name
        if path.exists():
            print(f"[003p-pipeline]   present  {name:46s} {sha256_file(path)[:16]}…")
        else:
            print(f"[003p-pipeline]   MISSING  {name}")
    if (out / "VERIFICATION.json").exists():
        verdict = read_json(out / "VERIFICATION.json")
        print(
            f"[003p-pipeline]   checks={verdict['checks_passed']}/{verdict['checks_total']} "
            f"technical={verdict['technical_execution_validation']} "
            f"paper={verdict['paper_validation']}"
        )
    if (out / "RUN_REPORT.json").exists():
        report = read_json(out / "RUN_REPORT.json")
        print(f"[003p-pipeline]   status={report['status']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P pipeline")
    parser.add_argument(
        "phase",
        choices=(
            "status",
            "baseline",
            "preregister",
            "schema",
            "rehearse",
            "controls",
            "verify",
            "tests",
            "checkout",
            "report",
            "seal",
            "all",
        ),
    )
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--install-command",
        default="not recorded",
        help="how the checkout's environment was built; copied into the reproduction evidence",
    )
    parser.add_argument(
        "--requirements",
        default=None,
        help="frozen freeze file the checkout's environment was synced from (hashed)",
    )
    args = parser.parse_args(argv)
    out = Path(args.out)
    scripts = REPO / "scripts"

    if args.phase == "status":
        return status(out)
    if args.phase == "baseline":
        return _run([str(scripts / "exp_003p_baseline.py"), "--out", str(out)], label="baseline")
    if args.phase == "preregister":
        return _run([str(scripts / "exp_003p_preregister.py")], label="preregister")
    if args.phase == "schema":
        return _run([str(scripts / "exp_003p_schema.py"), "--out", str(out)], label="schema")
    if args.phase == "rehearse":
        return rehearse(out)
    if args.phase == "controls":
        return _run(
            [str(scripts / "exp_003p_controls.py"), "--out", str(out / "NEGATIVE_CONTROLS.json")],
            label="controls",
        )
    if args.phase == "verify":
        return _run([str(scripts / "exp_003p_verify.py"), "--out", str(out)], label="verify")
    if args.phase == "tests":
        return run_tests(out)
    if args.phase == "checkout":
        return run_checkout_check(out, args.install_command, args.requirements)
    if args.phase == "report":
        return _run([str(scripts / "exp_003p_report.py"), "--out", str(out)], label="report")
    if args.phase == "seal":
        return _run(
            [str(scripts / "exp_003p_report.py"), "--out", str(out), "--seal"], label="seal"
        )
    if args.phase == "all":
        for phase in (
            "baseline",
            "preregister",
            "schema",
            "rehearse",
            "controls",
            "verify",
            "tests",
            "checkout",
            "report",
            "seal",
        ):
            code = main([phase, "--out", str(out)])
            if code != 0:
                return code
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
