"""The permanent integration gate for Trading Agentic Portable.

Why this exists: a ``PASS`` written by hand can name a commit that never ran, a campaign that
was a fixture, or a verifier whose report was never re-read.  This program turns the two
verified PAPER campaigns into one command that cannot do any of those things:

1. capture the candidate commit and refuse to run on a dirty tree, so the result is a claim
   about a commit and not about a workstation;
2. run the supervisor campaign (crash, resume, negative scenarios) on that commit;
3. run the lock campaign with its six crash sites and its two reclaim races;
4. run both campaign verifiers over what those campaigns actually wrote;
5. run an independent campaign audit (``C1``, ``L1`` and its own ``S1``/``S2`` self-controls);
6. judge every report against the published contract floors -- never against its own verdict;
7. re-read the commit after the work and fail if HEAD moved while a campaign was running;
8. write one consolidated report plus a SHA-256 manifest of everything it used.

Verdicts are ``PASS``, ``FAIL``, ``BLOCKED`` and ``NOT_TESTED``; only ``PASS`` certifies, and
nothing here can turn a missing or skipped check into one.  ``verify`` re-validates a previous
run: it recomputes the manifest, the contract hashes and the judgements, so evidence from
another commit or from an edited report is refused rather than trusted.

BUILDER != VERIFIER: this is the builder's half.  ``reports/ai-bots/TAP-INTEGRATION-GATE-001/
tools/review_gate.py`` is the review that must accept it, and that review is what runs the
negative controls and refuses to take this script's word for it.

    python scripts/tap_integration_gate.py run --out <dir outside the repository>
    python scripts/tap_integration_gate.py verify --evidence <dir>
    python scripts/tap_integration_gate.py preflight
    python scripts/tap_integration_gate.py commit-probe --repo <dir> -- <command>
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GATE_SCHEMA = "TAP_INTEGRATION_GATE_REPORT_V1"
MANIFEST_NAME = "EVIDENCE_MANIFEST.json"

#: The code whose behaviour the evidence certifies.  ``verify`` refuses evidence when any of
#: these files changed, because a report about a different contract is a report about another
#: candidate wearing the same commit message.
CONTRACT_FILES = (
    "scripts/paper_supervisor_campaign.py",
    "scripts/paper_supervisor_verify.py",
    "scripts/paper_lock_campaign.py",
    "scripts/paper_lock_campaign_verify.py",
    "scripts/tap_gate_campaign_audit.py",
    "scripts/tap_integration_gate.py",
)
SUPERVISOR_CAMPAIGN = "scripts/paper_supervisor_campaign.py"
SUPERVISOR_VERIFIER = "scripts/paper_supervisor_verify.py"
LOCK_CAMPAIGN = "scripts/paper_lock_campaign.py"
LOCK_VERIFIER = "scripts/paper_lock_campaign_verify.py"
AUDITOR = "scripts/tap_gate_campaign_audit.py"

#: The lock campaign contract as published by TAP-SUPERVISOR-INTEGRATION-002: six crash
#: iterations including one that dies before it persists a cycle, and two of them racing two
#: independent reclaimers.  Passed explicitly so a changed script default cannot silently
#: shrink the campaign behind the gate's back.
LOCK_MODES = (
    "after_cycle",
    "after_cycle",
    "before_cycle",
    "after_cycle",
    "after_cycle",
    "after_cycle",
)
LOCK_RACE_ITERATIONS = (2, 5)
SUPERVISOR_CRASHES = 1

#: Verifier floors, taken from the two verifiers as published -- not invented here.  The
#: supervisor verifier defines 33 checks and 14 mutations (31/12 applicable without the
#: negative scenarios); the lock verifier defines 32 checks and 9 mutations.  A report below
#: a floor is a weakened report, not a smaller campaign.
MIN_SUPERVISOR_CHECKS = 31
MIN_LOCK_CHECKS = 32
MIN_SUPERVISOR_MUTATIONS = 8
MIN_LOCK_MUTATIONS = 9

TIMEOUTS = {
    "supervisor_campaign": 2700.0,
    "supervisor_scenarios": 1200.0,
    "lock_campaign": 3600.0,
    "verifier": 1800.0,
    "audit": 900.0,
    "entrypoint": 300.0,
}

LANE_TIP = "integ/supervisor-002"

#: Evidence may be delivered in a later commit than the one the campaigns ran on, because the
#: run produces the report that the delivery commit then contains.  That is allowed only while
#: the diff between the two commits touches nothing but this delivery's reports: a change to
#: code, configuration or contract invalidates the evidence, and so does a commit that is not
#: an ancestor of HEAD.
EVIDENCE_ONLY_PREFIXES = ("reports/ai-bots/TAP-INTEGRATION-GATE-001/",)


# --------------------------------------------------------------------------- primitives


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def contract_hashes(repo: Path) -> dict[str, str]:
    return {name: sha256_file(repo / name) for name in CONTRACT_FILES if (repo / name).is_file()}


def tree_state(repo: Path) -> dict[str, Any]:
    porcelain = [line for line in git(repo, "status", "--porcelain").splitlines() if line.strip()]
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "porcelain": porcelain,
        "clean": not porcelain,
    }


class CommitWatcher:
    """Poll HEAD while a campaign runs, so a mid-run commit cannot go unnoticed."""

    def __init__(self, repo: Path, interval_s: float = 2.0) -> None:
        self.repo = repo
        self.interval_s = max(0.05, interval_s)
        self.observed: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll(self) -> None:
        while not self._stop.wait(self.interval_s):
            head = git(self.repo, "rev-parse", "HEAD")
            if head and (not self.observed or self.observed[-1] != head):
                self.observed.append(head)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None


@dataclass
class Step:
    id: str
    statement: str
    status: str = "NOT_TESTED"
    detail: str = ""
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    duration_s: float = 0.0
    log: str | None = None
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class Runner:
    """Run one step, keep its output, and never hide its exit status."""

    def __init__(self, out: Path, repo: Path) -> None:
        self.out = out
        self.repo = repo
        self.logs = out / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)

    def execute(
        self, step: Step, argv: Sequence[str], timeout_s: float, cwd: Path | None = None
    ) -> Step:
        step.command = list(argv)
        started = time.monotonic()
        try:
            result = subprocess.run(
                list(argv),
                cwd=str(cwd or self.repo),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            step.duration_s = round(time.monotonic() - started, 2)
            step.status = "FAIL"
            step.detail = f"timeout after {timeout_s:.0f}s"
            return step
        step.duration_s = round(time.monotonic() - started, 2)
        step.exit_code = code
        log = self.logs / f"{step.id}.log"
        log.write_text(
            f"$ {' '.join(argv)}\nexit={code}\n\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n",
            encoding="utf-8",
        )
        step.log = log.relative_to(self.out).as_posix()
        step.status = "PASS" if code == 0 else "FAIL"
        if code != 0:
            tail = (stderr or stdout).strip().splitlines()[-4:]
            step.detail = f"exit {code}: " + " | ".join(tail)
        return step


def verdict_of(statuses: Sequence[str]) -> str:
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "NOT_TESTED" in statuses:
        return "NOT_TESTED"
    return "PASS"


def entrypoint(name: str) -> list[str]:
    return [sys.executable, str(REPO / name)]


# --------------------------------------------------------------------------- judgements


def judge_verifier(kind: str, report: dict[str, Any]) -> tuple[str, str, list[str]]:
    if not report:
        return "FAIL", "verifier report missing or unreadable", ["report missing"]
    if kind == "supervisor":
        min_checks, min_mutants = MIN_SUPERVISOR_CHECKS, MIN_SUPERVISOR_MUTATIONS
    else:
        min_checks, min_mutants = MIN_LOCK_CHECKS, MIN_LOCK_MUTATIONS
    judgement = report.get("judgement") or {}
    checks = judgement.get("checks") or {}
    failed = sorted(name for name, value in checks.items() if value is False)
    mutants = report.get("adversarial") or []
    applicable = [row for row in mutants if row.get("applicable", True)]
    undetected = [row.get("mutation") for row in applicable if not row.get("detected")]
    not_applicable = report.get("not_applicable_checks") or judgement.get("not_applicable_checks")

    problems: list[str] = []
    if report.get("verdict") != "PASS":
        problems.append(f"verdict {report.get('verdict')}")
    if judgement.get("verdict") != "PASS":
        problems.append(f"judgement {judgement.get('verdict')}")
    if failed:
        problems.append(f"checks false: {failed}")
    if len(checks) < min_checks:
        problems.append(f"{len(checks)} checks, contract floor {min_checks}")
    if not_applicable:
        problems.append(f"checks not applicable: {not_applicable}")
    if report.get("false_success") != 0:
        problems.append(f"false_success {report.get('false_success')}")
    if undetected:
        problems.append(f"undetected mutations: {undetected}")
    if len(applicable) < min_mutants:
        problems.append(f"{len(applicable)} applicable mutations, floor {min_mutants}")
    if report.get("invalid_mutations"):
        problems.append(f"invalid mutations: {report.get('invalid_mutations')}")
    detail = (
        f"verdict={report.get('verdict')} checks={len(checks)} "
        f"mutations={len(applicable)} undetected={len(undetected)} "
        f"false_success={report.get('false_success')}"
    )
    return ("PASS" if not problems else "FAIL"), detail, problems


def judge_audit(report: dict[str, Any]) -> tuple[str, str, list[str]]:
    if not report:
        return "FAIL", "campaign audit missing or unreadable", ["report missing"]
    claims = report.get("claims") or {}
    not_pass = {
        cid: {"status": row.get("status"), "problems": row.get("problems")}
        for cid, row in claims.items()
        if row.get("status") != "PASS"
    }
    problems: list[str] = []
    if report.get("verdict") != "PASS":
        problems.append(f"verdict {report.get('verdict')}")
    if report.get("false_success") != 0:
        problems.append(f"false_success {report.get('false_success')}")
    if set(claims) != {"C1", "L1", "S1", "S2", "V1"}:
        problems.append(f"claims {sorted(claims)} != C1/L1/S1/S2/V1")
    if not_pass:
        problems.append(f"claims not PASS: {not_pass}")
    summary = report.get("summary") or {}
    detail = (
        f"claims={summary.get('pass')}/{summary.get('claims')} "
        f"fail={summary.get('fail')} unknown={summary.get('unknown')} "
        f"false_success={report.get('false_success')}"
    )
    return ("PASS" if not problems else "FAIL"), detail, problems


def judge_binding(
    candidate: str,
    supervisor_root: Path,
    lock_root: Path,
    supervisor_report: dict[str, Any],
    lock_report: dict[str, Any],
) -> tuple[str, str, list[str]]:
    problems: list[str] = []
    rows: list[str] = []
    for name, root in (("supervisor", supervisor_root), ("lock", lock_root)):
        recorded = str(read_json(root / "CAMPAIGN.json").get("commit") or "")
        rows.append(f"{name}.campaign={recorded[:12]}")
        if not recorded:
            problems.append(f"{name} campaign records no commit")
        elif recorded != candidate:
            problems.append(
                f"{name} campaign ran at {recorded[:12]}, candidate is {candidate[:12]}"
            )
    for name, report in (("supervisor", supervisor_report), ("lock", lock_report)):
        recorded = str(report.get("verifier_commit") or "")
        rows.append(f"{name}.verifier={recorded[:12]}")
        if not recorded:
            problems.append(f"{name} verifier records no commit")
        elif recorded != candidate:
            problems.append(
                f"{name} verifier ran at {recorded[:12]}, candidate is {candidate[:12]}"
            )
    return ("PASS" if not problems else "FAIL"), " ".join(rows), problems


def judge_shape(
    supervisor_root: Path, lock_root: Path, lock_report: dict[str, Any]
) -> tuple[str, str, list[str]]:
    lock_campaign = read_json(lock_root / "CAMPAIGN.json")
    iterations = lock_campaign.get("iterations") or []
    races = [row for row in iterations if row.get("concurrency") is not None]
    sites = [str(row.get("crash_site")) for row in iterations]
    supervisor = read_json(supervisor_root / "CAMPAIGN.json")
    final = supervisor.get("final") or {}
    problems: list[str] = []
    if len(iterations) != len(LOCK_MODES):
        problems.append(f"{len(iterations)} lock iterations, contract is {len(LOCK_MODES)}")
    if len(races) != len(LOCK_RACE_ITERATIONS):
        problems.append(f"{len(races)} reclaim races, contract is {len(LOCK_RACE_ITERATIONS)}")
    if not {"AFTER_CYCLE", "BEFORE_CYCLE"} <= set(sites):
        problems.append(f"crash sites {sorted(set(sites))} do not cover both windows")
    if lock_campaign.get("mode") != "PAPER":
        problems.append(f"lock campaign mode {lock_campaign.get('mode')}")
    if int(lock_campaign.get("live_orders") or 0) != 0:
        problems.append("lock campaign recorded a live order")
    if lock_campaign.get("final_locks"):
        problems.append(f"lock campaign finished with {len(lock_campaign['final_locks'])} lock(s)")
    if len(supervisor.get("episodes") or []) < SUPERVISOR_CRASHES:
        problems.append(f"{len(supervisor.get('episodes') or [])} supervisor episodes")
    if len(final.get("cycles") or []) < 2:
        problems.append("supervisor campaign did not run several cycles")
    if final.get("state") != "RECOVERED":
        problems.append(f"supervisor final state {final.get('state')}")
    if int(supervisor.get("live_orders") or 0) != 0:
        problems.append("supervisor campaign recorded a live order")
    if not (supervisor_root / "scenarios" / "SCENARIOS.json").is_file():
        problems.append("negative scenarios were not produced")
    detail = (
        f"lock iterations={len(iterations)} races={len(races)} sites={sorted(set(sites))}; "
        f"supervisor episodes={len(supervisor.get('episodes') or [])} "
        f"cycles={len(final.get('cycles') or [])} state={final.get('state')}"
    )
    if lock_report.get("verdict") != "PASS":
        problems.append("lock verifier did not pass the campaign it was given")
    return ("PASS" if not problems else "FAIL"), detail, problems


def judge_stability(recorded: dict[str, Any]) -> tuple[str, str, list[str]]:
    problems: list[str] = []
    if not recorded.get("tree_clean_before"):
        problems.append("the tree was dirty before the campaigns")
    if not recorded.get("tree_clean_after"):
        problems.append("the tree was dirty after the campaigns")
    if recorded.get("head_before") != recorded.get("head_after"):
        problems.append(
            f"HEAD moved from {recorded.get('head_before')} to {recorded.get('head_after')}"
        )
    if recorded.get("head_before") != recorded.get("commit"):
        problems.append("the recorded commit is not the commit the campaigns started on")
    moved = [sha for sha in recorded.get("observed_commits") or [] if sha != recorded.get("commit")]
    if moved:
        problems.append(f"a watcher saw HEAD at {sorted(set(moved))}")
    detail = (
        f"head={str(recorded.get('commit'))[:12]} observed={len(recorded.get('observed_commits') or [])} "
        f"clean={recorded.get('tree_clean_before')}/{recorded.get('tree_clean_after')}"
    )
    return ("PASS" if not problems else "FAIL"), detail, problems


# --------------------------------------------------------------------------- report


def summary_of(steps: dict[str, Step]) -> dict[str, Any]:
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_TESTED": 0}
    for step in steps.values():
        counts[step.status] = counts.get(step.status, 0) + 1
    return {"steps": len(steps), **counts}


def count_false_success(
    supervisor_report: dict[str, Any], lock_report: dict[str, Any], audit: dict[str, Any]
) -> int:
    failures = 0
    for report in (supervisor_report, lock_report):
        checks = (report.get("judgement") or {}).get("checks") or {}
        undetected = [
            row
            for row in report.get("adversarial") or []
            if row.get("applicable", True) and not row.get("detected")
        ]
        if report.get("verdict") == "PASS" and (
            any(value is False for value in checks.values())
            or undetected
            or report.get("false_success") not in (0, None)
        ):
            failures += 1
    claims = audit.get("claims") or {}
    if (
        claims.get("C1", {}).get("status") == "PASS"
        and claims.get("S1", {}).get("status") != "PASS"
    ):
        failures += 1
    if (
        claims.get("L1", {}).get("status") == "PASS"
        and claims.get("S2", {}).get("status") != "PASS"
    ):
        failures += 1
    return failures


def write_manifest(root: Path, commit: str) -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        files[relative] = sha256_file(path)
    payload = {
        "schema": "TAP_INTEGRATION_GATE_EVIDENCE_MANIFEST_V1",
        "commit": commit,
        "count": len(files),
        "files": files,
    }
    write_json(root / MANIFEST_NAME, payload)
    return payload


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Integration gate report",
        "",
        f"- **Commit:** `{report['commit']}`",
        f"- **Branch:** `{report['branch']}`",
        f"- **Generated:** {report['generated_at_utc']}",
        f"- **Label:** {report.get('label') or 'local'}",
        f"- **Verdict:** `{report['verdict']}` (certifies: {report['certifies']})",
        f"- **False success:** {report['false_success']}",
        "",
        "## Steps",
        "",
        "| Step | Status | Exit | Duration | Detail |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for step in report["steps"].values():
        detail = str(step["detail"]).replace("|", "\\|")[:220]
        lines.append(
            f"| `{step['id']}` | {step['status']} | {step['exit_code']} | "
            f"{step['duration_s']}s | {detail} |"
        )
    lines += [
        "",
        "## In one sentence",
        "",
        report["conclusion"],
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in report["limitations"]]
    lines += [
        "",
        "A `PASS` here certifies that both PAPER campaigns, their verifiers, the independent",
        "campaign audit and the commit-stability check ran on this commit and agreed. It does",
        "not certify profitability, does not authorise PAPER admission and does not make this",
        "workflow a required status check.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- run


def run_gate(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    if inside(out, REPO):
        print(
            json.dumps(
                {
                    "verdict": "BLOCKED",
                    "reason": "OUT_INSIDE_REPOSITORY",
                    "detail": f"{out} is inside {REPO}; the gate refuses to dirty the tree it judges",
                },
                indent=2,
            )
        )
        return 2

    out.mkdir(parents=True, exist_ok=True)
    runner = Runner(out, REPO)
    steps: dict[str, Step] = {}

    def add(step: Step) -> Step:
        steps[step.id] = step
        return step

    contract = contract_hashes(REPO)
    before = tree_state(REPO)
    candidate = before["head"]
    entry = add(Step("G0_ENTRYPOINTS", "every campaign and verifier entrypoint is present"))
    missing = [name for name in CONTRACT_FILES if not (REPO / name).is_file()]
    entry.status = "PASS" if not missing else "BLOCKED"
    entry.detail = "all present" if not missing else f"missing {missing}"

    tree = add(Step("G1_TREE", "the execution tree is clean before anything runs"))
    if not candidate:
        tree.status = "BLOCKED"
        tree.detail = "this is not a readable git work tree"
    elif not before["clean"]:
        tree.status = "BLOCKED"
        tree.detail = f"dirty tree: {before['porcelain'][:6]}"
    else:
        tree.status = "PASS"
        tree.detail = f"clean at {candidate[:12]} on {before['branch']}"

    if entry.status == "BLOCKED" or tree.status == "BLOCKED":
        statuses = [step.status for step in steps.values()]
        report = base_report(args, candidate, before, before, contract, steps, [])
        report["verdict"] = verdict_of(statuses)
        report["certifies"] = False
        report["conclusion"] = "The gate did not start: a precondition failed before any campaign."
        report["false_success"] = 0
        write_json(out / "GATE_REPORT.json", report)
        (out / "GATE_REPORT.md").write_text(render_markdown(report), encoding="utf-8")
        write_manifest(out, candidate)
        print(json.dumps({"verdict": report["verdict"], "steps": summary_of(steps)}, indent=2))
        return 2 if report["verdict"] == "BLOCKED" else 1

    campaigns = out / "campaigns"
    supervisor_root = campaigns / "supervisor"
    lock_root = campaigns / "lock"
    supervisor_report_path = out / "SUPERVISOR_VERIFICATION.json"
    lock_report_path = out / "LOCK_CAMPAIGN_VERIFICATION.json"
    audit_path = out / "CAMPAIGN_AUDIT.json"

    watcher = CommitWatcher(REPO, interval_s=args.interval_s)
    watcher.start()
    try:
        campaign = add(
            Step("C1_SUPERVISOR_CAMPAIGN", "the supervisor campaign runs on this commit")
        )
        runner.execute(
            campaign,
            [
                *entrypoint(SUPERVISOR_CAMPAIGN),
                "run",
                "--out",
                str(supervisor_root),
                "--crashes",
                str(SUPERVISOR_CRASHES),
            ],
            TIMEOUTS["supervisor_campaign"],
        )
        if campaign.status != "PASS":
            add(
                Step("C2_SUPERVISOR_SCENARIOS", "the negative scenarios run")
            ).detail = "not run: the campaign did not finish"
            add(
                Step("V1_SUPERVISOR_VERIFIER", "the supervisor verifier judges the campaign")
            ).detail = "not run: the campaign did not finish"
        else:
            scenarios = add(
                Step(
                    "C2_SUPERVISOR_SCENARIOS", "corrupt evidence and exhausted budget are exercised"
                )
            )
            runner.execute(
                scenarios,
                [
                    *entrypoint(SUPERVISOR_CAMPAIGN),
                    "scenarios",
                    "--out",
                    str(supervisor_root),
                    "--source-session",
                    str(supervisor_root / "session"),
                ],
                TIMEOUTS["supervisor_scenarios"],
            )
            verifier = add(
                Step("V1_SUPERVISOR_VERIFIER", "the supervisor verifier judges the campaign")
            )
            runner.execute(
                verifier,
                [
                    *entrypoint(SUPERVISOR_VERIFIER),
                    "--campaign",
                    str(supervisor_root),
                    "--out",
                    str(supervisor_report_path),
                ],
                TIMEOUTS["verifier"],
            )

        lock = add(
            Step("C3_LOCK_CAMPAIGN", "six crash sites and two reclaim races, on this commit")
        )
        runner.execute(
            lock,
            [
                *entrypoint(LOCK_CAMPAIGN),
                "run",
                "--out",
                str(lock_root),
                "--modes",
                *LOCK_MODES,
                "--race-iterations",
                *[str(value) for value in LOCK_RACE_ITERATIONS],
            ],
            TIMEOUTS["lock_campaign"],
        )
        lock_verifier = add(Step("V2_LOCK_VERIFIER", "the lock verifier judges the campaign"))
        if lock.status == "PASS":
            runner.execute(
                lock_verifier,
                [
                    *entrypoint(LOCK_VERIFIER),
                    "--campaign",
                    str(lock_root),
                    "--out",
                    str(lock_report_path),
                ],
                TIMEOUTS["verifier"],
            )
        else:
            lock_verifier.detail = "not run: the campaign did not finish"

        audit = add(Step("A1_CAMPAIGN_AUDIT", "an independent audit re-derives both campaigns"))
        if supervisor_root.is_dir() and lock_root.is_dir():
            runner.execute(
                audit,
                [
                    *entrypoint(AUDITOR),
                    "--supervisor",
                    str(supervisor_root),
                    "--lock",
                    str(lock_root),
                    "--supervisor-report",
                    str(supervisor_report_path),
                    "--lock-report",
                    str(lock_report_path),
                    "--out",
                    str(audit_path),
                ],
                TIMEOUTS["audit"],
            )
        else:
            audit.detail = "not run: a campaign directory is absent"
    finally:
        watcher.stop()

    after = tree_state(REPO)
    supervisor_report = read_json(supervisor_report_path)
    lock_report = read_json(lock_report_path)
    audit_payload = read_json(audit_path)

    verdicts = {
        "J1_SUPERVISOR_CONTRACT": judge_verifier("supervisor", supervisor_report),
        "J2_LOCK_CONTRACT": judge_verifier("lock", lock_report),
        "J3_AUDIT_CLAIMS": judge_audit(audit_payload),
        "J4_CANDIDATE_BINDING": judge_binding(
            candidate, supervisor_root, lock_root, supervisor_report, lock_report
        ),
        "J5_CAMPAIGN_SHAPE": judge_shape(supervisor_root, lock_root, lock_report),
    }
    statements = {
        "J1_SUPERVISOR_CONTRACT": "the supervisor verifier's report satisfies its contract",
        "J2_LOCK_CONTRACT": "the lock verifier's report satisfies its contract",
        "J3_AUDIT_CLAIMS": "C1, L1 and the two self-controls all pass",
        "J4_CANDIDATE_BINDING": "every artefact is bound to the candidate commit",
        "J5_CAMPAIGN_SHAPE": "the campaigns have the shape the contract requires",
    }
    for identifier, (status, detail, problems) in verdicts.items():
        step = add(Step(identifier, statements[identifier]))
        step.status = status
        step.detail = detail
        step.evidence = [f"problems: {problems}"] if problems else []

    recorded = {
        "commit": candidate,
        "head_before": before["head"],
        "head_after": after["head"],
        "tree_clean_before": before["clean"],
        "tree_clean_after": after["clean"],
        "observed_commits": watcher.observed,
    }
    stability = add(Step("S1_COMMIT_STABLE", "the commit did not move while the gate ran"))
    status, detail, problems = judge_stability(recorded)
    stability.status = status
    stability.detail = detail
    stability.evidence = [f"problems: {problems}"] if problems else []

    manifest_step = add(Step("M1_MANIFEST", "every artefact is hashed into a manifest"))
    mandatory = [
        supervisor_report_path,
        lock_report_path,
        audit_path,
        supervisor_root / "CAMPAIGN.json",
        lock_root / "CAMPAIGN.json",
    ]
    absent = [path.relative_to(out).as_posix() for path in mandatory if not path.is_file()]
    manifest_step.status = "PASS" if not absent else "FAIL"
    manifest_step.detail = "all mandatory artefacts present" if not absent else f"absent {absent}"

    statuses = [step.status for step in steps.values()]
    report = base_report(args, candidate, before, after, contract, steps, watcher.observed)
    report["verdict"] = verdict_of(statuses)
    report["certifies"] = report["verdict"] == "PASS"
    report["false_success"] = count_false_success(supervisor_report, lock_report, audit_payload)
    report["conclusion"] = conclusion_for(report, steps)
    write_json(out / "GATE_REPORT.json", report)
    (out / "GATE_REPORT.md").write_text(render_markdown(report), encoding="utf-8")
    manifest = write_manifest(out, candidate)

    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "commit": candidate,
                "steps": summary_of(steps),
                "false_success": report["false_success"],
                "manifest": f"{manifest['count']} files",
                "evidence": str(out),
            },
            indent=2,
        )
    )
    return 0 if report["certifies"] else 1


def conclusion_for(report: dict[str, Any], steps: dict[str, Step]) -> str:
    if report["verdict"] == "PASS":
        return (
            "Both PAPER campaigns ran on this commit, their verifiers and an independent audit "
            "accepted what they wrote, and HEAD did not move while they ran."
        )
    failing = [step.id for step in steps.values() if step.status in ("FAIL", "BLOCKED")]
    untested = [step.id for step in steps.values() if step.status == "NOT_TESTED"]
    parts = [f"The gate returned {report['verdict']}."]
    if failing:
        parts.append(f"Failed or blocked: {failing}.")
    if untested:
        parts.append(f"Not executed: {untested}.")
    if report["verdict"] == "NOT_TESTED":
        parts.append("A check that did not run is not a pass.")
    return " ".join(parts)


def base_report(
    args: argparse.Namespace,
    candidate: str,
    before: dict[str, Any],
    after: dict[str, Any],
    contract: dict[str, str],
    steps: dict[str, Step],
    observed: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema": GATE_SCHEMA,
        "task": "TAP-INTEGRATION-GATE-001",
        "generated_at_utc": utc_now(),
        "label": getattr(args, "label", None),
        "commit": candidate,
        "branch": before["branch"],
        "lane": {"tip": LANE_TIP, "merged_into_main": False},
        "contract": contract,
        "tree": {
            "clean_before": before["clean"],
            "clean_after": after["clean"],
            "porcelain_before": before["porcelain"],
            "porcelain_after": after["porcelain"],
        },
        "commit_stability": {
            "commit": candidate,
            "head_before": before["head"],
            "head_after": after["head"],
            "observed_commits": list(observed),
        },
        "campaigns": {
            "supervisor": {
                "producer": SUPERVISOR_CAMPAIGN,
                "verifier": SUPERVISOR_VERIFIER,
                "crashes": SUPERVISOR_CRASHES,
            },
            "lock": {
                "producer": LOCK_CAMPAIGN,
                "verifier": LOCK_VERIFIER,
                "modes": list(LOCK_MODES),
                "race_iterations": list(LOCK_RACE_ITERATIONS),
            },
            "auditor": AUDITOR,
        },
        "steps": {identifier: step.as_dict() for identifier, step in steps.items()},
        "summary": summary_of(steps),
        "verdict": "NOT_TESTED",
        "certifies": False,
        "false_success": 0,
        "invariants": {
            "paper_admission": "NO_GO",
            "live_orders": 0,
            "g1": "OPEN_SIGNOFF",
            "risk_policy_changed": False,
            "lane_merged": False,
        },
        "imposition": {
            "required_check": False,
            "state": "GOVERNANCE_BLOCKED",
            "note": (
                "the workflow exists, but turning it into a required status check needs a "
                "repository administrator; nothing in the repository can impose it"
            ),
        },
        "limitations": [
            "a PASS certifies the campaigns and the commit, not profitability or PAPER admission",
            "the gate runs on one host at a time; a second host is a second data point, not a substitute",
            "G1 stays OPEN_SIGNOFF: the gate does not sign a risk-policy change",
        ],
    }


# --------------------------------------------------------------------------- verify


def recompute_judgements(evidence: Path) -> dict[str, tuple[str, str, list[str]]]:
    supervisor_root = evidence / "campaigns" / "supervisor"
    lock_root = evidence / "campaigns" / "lock"
    supervisor_report = read_json(evidence / "SUPERVISOR_VERIFICATION.json")
    lock_report = read_json(evidence / "LOCK_CAMPAIGN_VERIFICATION.json")
    audit_path = evidence / "CAMPAIGN_AUDIT.json"
    candidate = str(read_json(evidence / "GATE_REPORT.json").get("commit") or "")
    audit_payload = read_json(audit_path)
    return {
        "J1_SUPERVISOR_CONTRACT": judge_verifier("supervisor", supervisor_report),
        "J2_LOCK_CONTRACT": judge_verifier("lock", lock_report),
        "J3_AUDIT_CLAIMS": judge_audit(audit_payload),
        "J4_CANDIDATE_BINDING": judge_binding(
            candidate, supervisor_root, lock_root, supervisor_report, lock_report
        ),
        "J5_CAMPAIGN_SHAPE": judge_shape(supervisor_root, lock_root, lock_report),
    }


def commit_binding(repo: Path, recorded: str, head: str) -> tuple[bool, str]:
    if not recorded:
        return False, "the report names no commit"
    if recorded == head:
        return True, "the report is bound to HEAD"
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", recorded, head],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestor.returncode != 0:
        return False, f"{recorded[:12]} is not an ancestor of {head[:12]}"
    changed = [
        line for line in git(repo, "diff", "--name-only", recorded, head).splitlines() if line
    ]
    offending = sorted(path for path in changed if not path.startswith(EVIDENCE_ONLY_PREFIXES))
    if offending:
        return False, f"{recorded[:12]}..{head[:12]} changed {offending[:6]}"
    return True, f"{recorded[:12]}..{head[:12]} touched only evidence ({len(changed)} files)"


def verify_evidence(evidence: Path, repo: Path) -> int:
    problems: list[str] = []
    report = read_json(evidence / "GATE_REPORT.json")
    if not report:
        print(json.dumps({"verdict": "FAIL", "problems": ["GATE_REPORT.json missing"]}, indent=2))
        return 1
    head = git(repo, "rev-parse", "HEAD")
    commit = str(report.get("commit") or "")
    bound, binding = commit_binding(repo, commit, head)
    if not bound:
        problems.append(f"COMMIT_MISMATCH {binding}")
    current = contract_hashes(repo)
    if report.get("contract") != current:
        changed = sorted(
            name
            for name in set(current) | set(report.get("contract") or {})
            if (report.get("contract") or {}).get(name) != current.get(name)
        )
        problems.append(f"CONTRACT_MISMATCH {changed}")

    manifest = read_json(evidence / MANIFEST_NAME)
    recorded_files = {str(k): str(v) for k, v in (manifest.get("files") or {}).items()}
    actual: dict[str, str] = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != MANIFEST_NAME:
            actual[path.relative_to(evidence).as_posix()] = sha256_file(path)
    missing = sorted(set(recorded_files) - set(actual))
    extra = sorted(set(actual) - set(recorded_files))
    changed = sorted(
        name for name in set(recorded_files) & set(actual) if recorded_files[name] != actual[name]
    )
    if not manifest:
        problems.append("MANIFEST_MISSING")
    elif missing or extra or changed:
        problems.append(f"MANIFEST_MISMATCH missing={missing} extra={extra} changed={changed}")

    recomputed = recompute_judgements(evidence)
    recorded_steps = report.get("steps") or {}
    disagreements = {
        identifier: {"recorded": recorded_steps.get(identifier, {}).get("status"), "now": status}
        for identifier, (status, _, _) in recomputed.items()
        if recorded_steps.get(identifier, {}).get("status") != status
    }
    if disagreements:
        problems.append(f"STEP_DISAGREEMENT {disagreements}")

    statuses = [
        str(step.get("status"))
        for identifier, step in recorded_steps.items()
        if identifier not in recomputed
    ] + [status for status, _, _ in recomputed.values()]
    derived = verdict_of(statuses)
    if derived != report.get("verdict"):
        problems.append(f"VERDICT_MISMATCH recorded={report.get('verdict')} derived={derived}")
    if derived != "PASS":
        failing = {
            identifier: (status, detail)
            for identifier, (status, detail, _) in recomputed.items()
            if status != "PASS"
        }
        problems.append(f"VERDICT {derived} {failing}")
    if report.get("certifies") is not True and derived == "PASS":
        problems.append("CERTIFIES_FLAG the report does not certify what it derived")

    verdict = "PASS" if not problems else "FAIL"
    print(
        json.dumps(
            {
                "verdict": verdict,
                "commit": commit,
                "head": head,
                "binding": binding,
                "manifest_files": len(recorded_files),
                "recomputed": {key: value[0] for key, value in recomputed.items()},
                "problems": problems,
            },
            indent=2,
        )
    )
    return 0 if verdict == "PASS" else 1


# --------------------------------------------------------------------------- preflight


def preflight(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []

    def record(identifier: str, ok: bool, detail: str) -> None:
        checks.append({"id": identifier, "status": "PASS" if ok else "FAIL", "detail": detail})

    state = tree_state(REPO)
    record("P0_GIT", bool(state["head"]), f"HEAD {state['head'][:12]} on {state['branch']}")
    record(
        "P1_TREE",
        state["clean"],
        "clean" if state["clean"] else f"dirty: {state['porcelain'][:6]}",
    )
    for name in CONTRACT_FILES:
        record(f"P2_{name.rsplit('/', 1)[-1]}", (REPO / name).is_file(), name)
    for name in (SUPERVISOR_CAMPAIGN, SUPERVISOR_VERIFIER, LOCK_CAMPAIGN, LOCK_VERIFIER, AUDITOR):
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(REPO / name), "--help"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUTS["entrypoint"],
            check=False,
        )
        record(
            f"P3_{name.rsplit('/', 1)[-1]}",
            result.returncode == 0,
            f"--help exit {result.returncode} in {time.monotonic() - started:.1f}s",
        )
    lock_help = subprocess.run(
        [sys.executable, str(REPO / LOCK_CAMPAIGN), "run", "--help"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUTS["entrypoint"],
        check=False,
    ).stdout
    for flag in ("--modes", "--race-iterations"):
        record(f"P4_lock{flag}", flag in lock_help, f"lock campaign accepts {flag}")
    if args.out:
        out = Path(args.out).resolve()
        record(
            "P5_OUTSIDE_TREE",
            not inside(out, REPO),
            f"{out} {'inside' if inside(out, REPO) else 'outside'} the repository",
        )

    failing = [check["id"] for check in checks if check["status"] != "PASS"]
    payload = {
        "schema": "TAP_INTEGRATION_GATE_PREFLIGHT_V1",
        "generated_at_utc": utc_now(),
        "commit": state["head"],
        "branch": state["branch"],
        "checks": checks,
        "verdict": "PASS" if not failing else "FAIL",
        "certifies": False,
        "note": (
            "a preflight runs neither campaign and cannot certify integration; only `run` can"
        ),
        "failing": failing,
    }
    if args.out:
        write_json(Path(args.out) / "PREFLIGHT.json", payload)
    print(json.dumps(payload, indent=2))
    return 0 if not failing else 1


# --------------------------------------------------------------------------- commit probe


def commit_probe(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    before = git(repo, "rev-parse", "HEAD")
    payload: dict[str, Any] = {"repo": str(repo), "before": before}
    if not before:
        payload.update({"verdict": "BLOCKED", "detail": "not a readable git repository"})
        print(json.dumps(payload, indent=2))
        return 2
    watcher = CommitWatcher(repo, interval_s=args.interval_s)
    watcher.start()
    try:
        result = subprocess.run(list(args.command_to_run), cwd=str(repo), check=False)
    finally:
        watcher.stop()
    after = git(repo, "rev-parse", "HEAD")
    moved = before != after or any(sha != before for sha in watcher.observed)
    payload.update(
        {
            "after": after,
            "observed_commits": watcher.observed,
            "command_exit": result.returncode,
            "moved": moved,
            "verdict": "FAIL" if moved else "PASS",
            "detail": "HEAD moved during the command" if moved else "HEAD stayed put",
        }
    )
    print(json.dumps(payload, indent=2))
    return 0 if not moved else 1


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Permanent TAP integration gate")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run both campaigns and certify the commit")
    run.add_argument("--out", required=True, help="evidence directory, outside the repository")
    run.add_argument("--label", default=None, help="free-form label recorded in the report")
    run.add_argument("--interval-s", type=float, default=2.0, help="HEAD poll interval")
    run.set_defaults(func=run_gate)

    verify = sub.add_parser("verify", help="re-validate a previous run against this tree")
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--repo", default=str(REPO))
    verify.set_defaults(
        func=lambda args: verify_evidence(Path(args.evidence), Path(args.repo).resolve())
    )

    fast = sub.add_parser("preflight", help="fast readiness check; never a certification")
    fast.add_argument("--out", default=None)
    fast.set_defaults(func=preflight)

    probe = sub.add_parser("commit-probe", help="run a command and fail if HEAD moves")
    probe.add_argument("--repo", required=True)
    probe.add_argument("--interval-s", type=float, default=0.2)
    probe.add_argument("argv_rest", nargs=argparse.REMAINDER)
    probe.set_defaults(func=commit_probe)

    args = parser.parse_args(argv)
    if args.command == "commit-probe":
        command = list(args.argv_rest)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("commit-probe needs a command after --")
        args.command_to_run = command
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
