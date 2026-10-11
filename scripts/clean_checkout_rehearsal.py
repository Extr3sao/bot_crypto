"""Clean-checkout rehearsal for the recovery lanes (WP-8E).

WP-7 proved its CI suite in a throwaway shell script kept in a gitignored directory.
That is exactly how the defect it found stayed hidden for a commit: a rehearsal that
lives outside the repository cannot be run by anyone else, and nothing fails when it
stops being run.

This is the same sequence, versioned, with the two properties that make a rehearsal
worth having:

* it runs against a **commit**, in a brand-new ``git worktree``, not against the tree
  it was invoked from - so "it passes" means "that commit reproduces", and the tree it
  ran in cannot be the reason it passed;
* it can be **sabotaged on purpose** (``--sabotage``): an input is altered inside the
  clean checkout and the rehearsal has to notice. A rehearsal that cannot fail is
  decoration, and the sabotage is what distinguishes the two.

Sequence (``--scope full``; ``--scope recovery`` stops after the recovery lane):

1. refuse to rehearse when the paths under test are dirty - a green run would otherwise
   describe a working copy rather than a commit;
2. create a detached worktree of the commit;
3. verify the input bundles (WP-8B and WP-7E): every input a finding rests on resolves
   from the commit, which is the only thing a CI runner can rely on;
4. run the producers and the lane's contract and determinism tests;
5. compare the regenerated artefacts with the committed ones by content digest, and
   report every other tracked path the run moved;
6. run the independent verifier *after* the comparison report exists, because the
   verifier is required to check that report;
7. fail on an absent or unverified dependency rather than on a missing file later.

Two distinctions the report keeps explicit:

* **run records** (the verifier's own record) are allowed to differ: they describe the
  run, not the state. They are listed separately from the artefacts that must be
  reproduced byte for byte.
* **runner**: ``GITHUB_ACTIONS`` when the environment says so, otherwise ``LOCAL``. A
  local pass is a claim about this machine's checkout; a CI pass is the same sequence on
  a fresh one, and the report says which it was.

Exit codes: 0 expected outcome (pass, or a sabotage detected), 2 integrity failure,
3 blocked missing input, 4 refused (dirty paths under test), 5 sabotage NOT detected,
6 reproduction failure.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recovery_input_evidence import content_forms  # noqa: E402  (a sibling module)

REPORT_JSON = "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json"
REPORT_MD = "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.md"

# What the rehearsal is about. If any of these is dirty, the commit is not what would be
# rehearsed, and saying "PASS" would be a claim nobody can check.
COVERED_PATHS: tuple[str, ...] = (
    "scripts/clean_checkout_rehearsal.py",
    "scripts/recovery_input_evidence.py",
    "scripts/campaign_state_view.py",
    "scripts/active_economic_audit.py",
    "scripts/recovery_verify.py",
    "scripts/cost_barrier_evidence.py",
    "scripts/cost_barrier_gate.py",
    "scripts/cost_barrier_adversarial.py",
    "tests/unit/research/test_active_recovery_wp.py",
    "tests/unit/research/test_recovery_determinism.py",
    "data/recovery/CAMPAIGN_STATE_VIEW.json",
    "data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.md",
    # the verifier's record is deliberately *not* here: it is an output of this sequence and
    # it describes the run, so requiring it to be clean would be requiring it not to be run
    "data/recovery/wp8/evidence",
    "data/recovery/wp8/RECOVERY_RUNTIME_AUTHORITY_MAP.md",
    "data/recovery/wp8/CAMPAIGN_STATE_DETERMINISM_AUDIT.md",
    "data/recovery/wp8/ACTIVE_RECOVERY_REPRODUCIBILITY.md",
    "data/recovery/wp8/RUN_REPORT.md",
    "data/recovery/wp8/RUN_REPORT.json",
    "data/recovery/wp8/FINAL_REPORT.md",
    "PAPER_DATA_24H_REPORT.json",
)

# The derived artefacts: a clean checkout must reproduce these byte for byte (up to line
# endings, which is a checkout's business, not the state's).
ARTIFACTS: tuple[str, ...] = (
    "data/recovery/CAMPAIGN_STATE_VIEW.json",
    "data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.md",
)

# Records of a run rather than descriptions of the state: they legitimately differ from
# one run to the next (they carry the moment and the run's own inputs), and the verifier's
# record also has to be able to mention this rehearsal report. Declared, not ignored.
RUN_RECORDS: tuple[str, ...] = (
    "data/recovery/INDEPENDENT_VERIFICATION.json",
)

EXIT_OK = 0
EXIT_INTEGRITY = 2
EXIT_BLOCKED = 3
EXIT_REFUSED = 4
EXIT_NOT_DETECTED = 5
EXIT_REPRODUCTION = 6

SABOTAGE_TARGETS = ("evidence_copy", "committed_input")


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd or ROOT), capture_output=True, text=True, check=False)


def runner_kind() -> str:
    return "GITHUB_ACTIONS" if os.environ.get("GITHUB_ACTIONS") else "LOCAL"


def dirty_covered_paths() -> list[str]:
    out = git("status", "--porcelain", "--", *COVERED_PATHS)
    return [line for line in out.stdout.splitlines() if line.strip()]


def step(name: str, command: list[str], cwd: Path, expected_exit: int = 0) -> dict[str, Any]:
    out = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    combined = f"{out.stdout}\n{out.stderr}"
    return {
        "step": name,
        "command": " ".join(command),
        "exit_code": out.returncode,
        "expected_exit": expected_exit,
        "result": "PASS" if out.returncode == expected_exit else "FAIL",
        "stdout_tail": "\n".join(out.stdout.strip().splitlines()[-6:]),
        "stderr_tail": "\n".join(out.stderr.strip().splitlines()[-4:]),
        "eol_only_difference_reported": any(token in combined for token in
                                            ("EOL_ONLY", "line-ending-only", "one of them")),
    }


def artifact_state(root: Path) -> dict[str, Any]:
    """The published artefacts as they stand in ``root``, by content digest."""
    out: dict[str, Any] = {}
    for rel in ARTIFACTS:
        path = root / rel
        if not path.exists():
            out[rel] = {"exists": False}
            continue
        data = path.read_bytes()
        document: dict[str, Any] = {}
        if rel.endswith(".json"):
            try:
                document = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                document = {}
        out[rel] = {
            "exists": True,
            "sha256_lf": content_forms(data)["sha256_lf"],
            "payload_sha256": document.get("payload_sha256"),
            "status": document.get("status"),
            "checks_failed": document.get("checks_failed"),
        }
    return out


def compare(published: dict[str, Any], regenerated: dict[str, Any]) -> dict[str, Any]:
    return {
        rel: {
            "published": published.get(rel),
            "regenerated": regenerated.get(rel),
            "identical": published.get(rel) == regenerated.get(rel),
        }
        for rel in ARTIFACTS
    }


def sabotage(worktree: Path, target: str) -> dict[str, Any]:
    """Alter one input inside the clean checkout. The rehearsal must notice; the caller
    decides which step is expected to be the one that does."""
    if target == "evidence_copy":
        victim = worktree / "data/recovery/wp8/evidence/inputs/TIMEFRAME_AUDIT.json"
        data = json.loads(victim.read_text(encoding="utf-8"))
        data.setdefault("sabotage", {})["injected"] = "one extra key that no published digest covers"
        victim.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return {
            "target": target,
            "path": str(victim.relative_to(worktree)).replace("\\", "/"),
            "mutation": "added a key to the evidence copy of the timeframe audit",
            "expected_detector": "the input bundle verify step",
        }
    victim = worktree / "tasks/decisions.md"
    text = victim.read_text(encoding="utf-8")
    victim.write_text(text + "\n## ADR-9999 - sabotage rehearsal\n\n`NEXT_CAMPAIGN = AUTHORIZED`\n",
                      encoding="utf-8")
    return {
        "target": target,
        "path": str(victim.relative_to(worktree)).replace("\\", "/"),
        "mutation": "appended an ADR that authorizes a campaign",
        "expected_detector": "the artefact comparison",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# CLEAN CHECKOUT REHEARSAL REPORT (WP-8E)",
        "",
        f"- rehearsed commit `{report['rehearsed_commit'][:12]}` · runner `{report['runner']}` · "
        f"scope `{report['scope']}`",
        f"- **status: {report['status']}**",
        f"- started `{report['started_at_utc']}` · finished `{report['finished_at_utc']}`",
        "",
        "The sequence runs in a detached worktree of the commit, never in the tree it was invoked",
        "from: a pass here is a claim about the commit.",
        "",
        "## Steps",
        "",
        "| step | expected exit | actual | result |",
        "| --- | ---: | ---: | --- |",
    ]
    for item in report["steps"]:
        lines.append(f"| `{item['step']}` | {item['expected_exit']} | {item['exit_code']} | **{item['result']}** |")
    lines += ["", "## Artefacts (must be reproduced byte for byte)", "",
              "| artefact | published | regenerated | identical |", "| --- | --- | --- | --- |"]
    for rel, entry in report["artifacts"].items():
        published = entry["published"] or {}
        regenerated = entry["regenerated"] or {}
        lines.append(f"| `{rel}` | `{str(published.get('sha256_lf'))[:12]}` | "
                     f"`{str(regenerated.get('sha256_lf'))[:12]}` | {entry['identical']} |")
    lines += ["", "## What moved", ""]
    lines.append(f"- published artefacts modified by the run: {report['published_paths_moved'] or 'none'}")
    lines.append(f"- run records that legitimately differ: {report['run_records_changed'] or 'none'}")
    lines.append(f"- line-ending-only differences encountered: {report['line_endings']['eol_only_encountered']}")
    if report.get("sabotage"):
        lines += ["", "## Sabotage", ""]
        lines.append("```json")
        lines.append(json.dumps(report["sabotage"], indent=2, ensure_ascii=False))
        lines.append("```")
    if report.get("limitations"):
        lines += ["", "## Limitations", ""]
        lines += [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def rehearse(commit: str | None, scope: str, sabotage_target: str | None,
             keep_worktree: bool, note_report: bool = True) -> tuple[dict[str, Any], int]:
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = (git("rev-parse", "HEAD").stdout or "").strip()
    target_commit = commit or head
    report: dict[str, Any] = {
        "artifact": "CLEAN_CHECKOUT_REHEARSAL_REPORT",
        "work_package": "WP-8E: the rehearsal is a versioned script, not a note in a log",
        "runner": runner_kind(),
        "started_at_utc": started,
        "rehearsed_commit": target_commit,
        "invoked_from_commit": head,
        "scope": scope,
        "steps": [],
        "published": artifact_state(ROOT),
        "regenerated": {},
        "artifacts": {},
        "published_paths_moved": [],
        "run_records_changed": [],
        "line_endings": {"eol_only_encountered": False,
                         "note": "a line-ending-only difference is a checkout artefact, not a finding: "
                                 "the digests are content digests and an EOL difference is an advisory"},
        "sabotage": None,
        "limitations": [],
    }
    dirty = dirty_covered_paths()
    if dirty:
        report["status"] = "REFUSED_DIRTY_PATHS"
        report["dirty_paths"] = dirty[:12]
        report["finished_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        report["limitations"].append(
            "the paths under test are dirty, so a green run would describe a working copy, not the commit")
        return report, EXIT_REFUSED

    worktree = Path(tempfile.mkdtemp(prefix="recovery-rehearsal-")) / "checkout"
    created = git("worktree", "add", "--detach", str(worktree).replace("\\", "/"), target_commit)
    if created.returncode != 0:
        report["status"] = "BLOCKED_MISSING_INPUT"
        report["failures"] = [created.stderr.strip()]
        report["finished_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return report, EXIT_BLOCKED
    report["worktree"] = str(worktree)
    outcome = EXIT_OK
    try:
        python = sys.executable
        if sabotage_target:
            report["sabotage"] = {**sabotage(worktree, sabotage_target), "detected": None, "detected_by": None}
        # 3. the input bundles: what the commit carries must be what every finding rests on
        report["steps"].append(step("verify_recovery_input_bundle",
                                    [python, "scripts/recovery_input_evidence.py", "--verify"], worktree))
        cost_barrier = [
            ("verify_cost_barrier_bundle", [python, "scripts/cost_barrier_evidence.py"]),
            ("materialize_cost_barrier_input", [python, "scripts/cost_barrier_evidence.py", "--materialize"]),
        ]
        producers = [
            ("run_active_economic_audit", [python, "scripts/active_economic_audit.py"]),
            ("run_campaign_state_view", [python, "scripts/campaign_state_view.py"]),
            ("run_contract_tests", [python, "-m", "pytest",
                                    "tests/unit/research/test_active_recovery_wp.py", "-q", "-p", "no:cacheprovider"]),
            # the determinism regressions, minus the three rehearsal tests themselves: a
            # rehearsal that spawns the rehearsal again is a fork bomb, not a proof
            ("run_determinism_tests", [python, "-m", "pytest",
                                       "tests/unit/research/test_recovery_determinism.py", "-q",
                                       "-p", "no:cacheprovider", "-k", "not rehearsal and not sabotaged"]),
        ]
        full = [
            ("run_cost_barrier_gate", [python, "scripts/cost_barrier_gate.py"]),
            ("run_adversarial_sweep", [python, "scripts/cost_barrier_adversarial.py"]),
        ]
        # 4. run everything, then 5. compare
        for name, command in [*cost_barrier, *producers, *([] if scope == "recovery" else full)]:
            report["steps"].append(step(name, command, worktree))
        report["regenerated"] = artifact_state(worktree)
        report["artifacts"] = compare(report["published"], report["regenerated"])
        status = git("status", "--porcelain", cwd=worktree)
        changed = [line for line in status.stdout.splitlines() if not line.startswith("??")]
        report["untracked_after_the_run"] = [line for line in status.stdout.splitlines() if line.startswith("??")]
        report["run_records_changed"] = [line.strip() for line in changed
                                         if line.split()[-1] in RUN_RECORDS]
        report["published_paths_moved"] = [line.strip() for line in changed
                                           if line.split()[-1] not in RUN_RECORDS
                                           and not line.split()[-1].startswith("data/recovery/wp8/")]
        report["line_endings"]["eol_only_encountered"] = any(
            item["eol_only_difference_reported"] for item in report["steps"])

        def settle() -> tuple[str, int]:
            """The verdict from the facts gathered so far.

            Called twice: once before the verifier runs (so the report the verifier is asked to
            confirm exists and states the conclusion) and once after, when the verifier's own
            result counts too.
            """
            failed = [item for item in report["steps"] if item["result"] != "PASS"]
            reproduction = bool(report["published_paths_moved"]) or any(
                entry["identical"] is False for entry in report["artifacts"].values())
            if report["sabotage"]:
                detected, detected_by = False, None
                if report["sabotage"]["target"] == "evidence_copy" and any(
                        item["step"] == "verify_recovery_input_bundle" and item["result"] == "FAIL"
                        for item in failed):
                    detected, detected_by = True, "the input bundle verify step rejected the altered copy"
                if report["sabotage"]["target"] == "committed_input" and reproduction:
                    detected, detected_by = True, "the artefact comparison saw a published artefact move"
                report["sabotage"].update({"detected": detected, "detected_by": detected_by})
                if not detected and "was NOT detected" not in " ".join(report["limitations"]):
                    report["limitations"].append(
                        "a deliberate mutation of a declared input was NOT detected: the rehearsal is "
                        "not measuring what it claims to")
                return (("SABOTAGE_DETECTED" if detected else "SABOTAGE_NOT_DETECTED"),
                        EXIT_OK if detected else EXIT_NOT_DETECTED)
            if reproduction:
                return "REPRODUCTION_FAILED", EXIT_REPRODUCTION
            if failed:
                blocked = any(item["step"].startswith("verify_") for item in failed)
                report["failed_steps"] = [item["step"] for item in failed]
                return (("BLOCKED_MISSING_INPUT" if blocked else "FAILED"),
                        EXIT_BLOCKED if blocked else EXIT_INTEGRITY)
            return "PASS", EXIT_OK

        # 6. the report exists inside the clean checkout before the verifier is asked to check
        # it: the verifier is required to confirm this rehearsal, so the order matters
        report["status"], outcome = settle()
        if note_report:
            (worktree / REPORT_JSON).parent.mkdir(parents=True, exist_ok=True)
            (worktree / REPORT_JSON).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
        report["steps"].append(step("run_independent_verifier", [python, "scripts/recovery_verify.py"], worktree))
        report["status"], outcome = settle()
        if report["status"] == "PASS":
            report["limitations"].append(
                "this run proves the commit reproduces in a clean checkout and that the input authority "
                "resolves from the commit; it does not prove the derivation is correct - that is the "
                "verifier's and the contract tests' job")
            report["limitations"].append(
                "the rehearsal was executed on one operating system; the cross-platform claim rests on "
                "the content digests, which are taken over LF-normalised content, and not on this run")
    finally:
        if not keep_worktree:
            git("worktree", "remove", "--force", str(worktree).replace("\\", "/"))
        report["finished_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return report, outcome


def write_report(report: dict[str, Any], root: Path) -> None:
    json_path = root / REPORT_JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / REPORT_MD).write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse a commit in a clean checkout.")
    parser.add_argument("--commit", default=None, help="commit to rehearse (default HEAD)")
    parser.add_argument("--scope", choices=("recovery", "full"), default="full")
    parser.add_argument("--sabotage", choices=SABOTAGE_TARGETS, default=None,
                        help="alter an input inside the clean checkout and require the rehearsal to notice")
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--no-report", action="store_true", help="do not write the report artefact")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report, code = rehearse(args.commit, args.scope, args.sabotage, args.keep_worktree)
    if not args.no_report:
        write_report(report, ROOT)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": report["status"], "commit": report["rehearsed_commit"][:12],
                          "runner": report["runner"], "steps_failed": report.get("failed_steps", []),
                          "published_paths_moved": report["published_paths_moved"],
                          "run_records_changed": report["run_records_changed"],
                          "sabotage": report.get("sabotage")}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
