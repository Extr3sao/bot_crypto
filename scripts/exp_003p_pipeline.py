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


def run_checkout_check(out: Path) -> int:
    """Try to reproduce the rehearsal from a clean worktree at HEAD.

    The work of this experiment is uncommitted by design (the user decides when to commit),
    so a worktree at HEAD cannot contain it. That is recorded as NOT_PERFORMED with the
    exact command to run afterwards — never as a pass.
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
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), head],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    dataset_target = worktree / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
    dataset_target.mkdir(parents=True, exist_ok=True)
    source = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
    for path in sorted(source.glob("*.jsonl.gz")):
        (dataset_target / path.name).write_bytes(path.read_bytes())
    completed = subprocess.run(
        [PYTHON, str(worktree / "scripts" / "exp_003p_rehearsal.py"), "--out",
         str(worktree / "reports" / "ai-bots" / "EXP-003P-PAPER-EXECUTION-001"),
         "--checkout-check"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=False,
    )
    reproduced = worktree / "reports" / "ai-bots" / "EXP-003P-PAPER-EXECUTION-001" / "DIGESTS.json"
    published = read_json(out / "DIGESTS.json")
    payload.update(
        {
            "worktree": str(worktree),
            "rehearsal_exit_code": completed.returncode,
            "rehearsal_tail": completed.stdout.strip().splitlines()[-2:],
            "run_digest_published": published.get("run_digest"),
            "run_digest_reproduced": (
                read_json(reproduced).get("run_digest") if reproduced.exists() else None
            ),
        }
    )
    identical = payload["run_digest_published"] == payload["run_digest_reproduced"]
    payload["verdict"] = "REPRODUCED" if (completed.returncode == 0 and identical) else "FAILED"
    write_json(evidence / "CLEAN_CHECKOUT_REPRODUCTION.json", payload)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[003p-pipeline] checkout {payload['verdict']}")
    return 0 if payload["verdict"] == "REPRODUCED" else 5


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
        return run_checkout_check(out)
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
