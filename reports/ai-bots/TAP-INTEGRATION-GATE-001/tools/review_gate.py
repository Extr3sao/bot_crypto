"""Independent review of a TAP integration gate run.

``BUILDER != VERIFIER``.  This program imports nothing from ``scripts/tap_integration_gate.py``
and nothing from ``scripts/tap_gate_campaign_audit.py``: it reads the evidence directory,
recomputes every hash, re-walks both campaigns with its own chain verifier, and derives the
verdict itself.  A gate that returns exit 0 is not accepted for that reason alone.

It also runs eight negative controls, each hermetic (a temporary copy, never the original):

``N0`` another delivery's evidence is refused;
``N1`` evidence carrying a different commit is refused even when its manifest is intact;
``N2`` a commit that moves while a command runs is caught by the gate's probe;
``N3`` a campaign missing one ``RECOVERY.json`` fails the campaign audit;
``N4`` edited evidence without a matching manifest is refused;
``N5`` a shortened campaign declared complete still fails the audit;
``N6`` a weakened verifier report with a rebuilt manifest is refused by re-judgement;
``N7`` one failing verifier sinks the verdict even when every other step passed.

A control passes only when the gate rejects what it must reject.  A control that errors out
for the wrong reason is reported as failed, with the output that shows why.

    python reports/ai-bots/TAP-INTEGRATION-GATE-001/tools/review_gate.py \
        --evidence <gate evidence dir> --out <REVIEW.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
GATE = REPO / "scripts" / "tap_integration_gate.py"
AUDITOR = REPO / "scripts" / "tap_gate_campaign_audit.py"
WORKFLOW = REPO / ".github" / "workflows" / "integration-gate.yml"
LEGACY_EVIDENCE = REPO / "reports" / "ai-bots" / "TAP-SUPERVISOR-INTEGRATION-002" / "evidence"
SCHEMA = "TAP_INTEGRATION_GATE_REVIEW_V1"
MANIFEST = "EVIDENCE_MANIFEST.json"
GENESIS = "0" * 64
SEPARATORS = (",", ":")

#: Same floors as the gate, restated here on purpose: a reviewer that imported them could not
#: notice the gate lowering them.
MIN_SUPERVISOR_CHECKS = 31
MIN_LOCK_CHECKS = 32
MIN_SUPERVISOR_MUTATIONS = 8
MIN_LOCK_MUTATIONS = 9
LOCK_ITERATIONS = 6
LOCK_RACES = 2

#: The delivery commit may add the evidence the run produced; it may not change code.
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


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    ).stdout.strip()


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=SEPARATORS, ensure_ascii=False)


def chain_of(stream: Path) -> dict[str, Any]:
    if not stream.is_file():
        return {"ok": False, "reason": "MISSING", "lines": 0, "entries": []}
    prev = GENESIS
    entries: list[dict[str, Any]] = []
    lines = 0
    for raw in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        lines += 1
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": f"BAD_JSON_AT_{lines}", "lines": lines, "entries": []}
        if int(row.get("seq", -1)) != lines or str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_AT_{lines}", "lines": lines, "entries": entries}
        digest = hashlib.sha256(
            canonical({"seq": lines, "prev_sha256": prev, "entry": row.get("entry")}).encode()
        ).hexdigest()
        if digest != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_AT_{lines}", "lines": lines, "entries": entries}
        prev = digest
        entry = row.get("entry")
        entries.append(entry if isinstance(entry, dict) else {})
    return {"ok": True, "reason": "INTACT", "lines": lines, "head": prev, "entries": entries}


def check(identifier: str, statement: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "statement": statement,
        "status": "UNKNOWN",
        "detail": "",
        "problems": [],
    }


def locks(root: Path) -> list[str]:
    session = root / "session"
    if not session.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in session.rglob("*.lock"))


def rewrite_manifest(evidence: Path, commit: str) -> None:
    files: dict[str, str] = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != MANIFEST:
            files[path.relative_to(evidence).as_posix()] = sha256_file(path)
    write_json(
        evidence / MANIFEST,
        {
            "schema": "TAP_INTEGRATION_GATE_EVIDENCE_MANIFEST_V1",
            "commit": commit,
            "count": len(files),
            "files": files,
        },
    )


# --------------------------------------------------------------------------- checks


def manifest_check(evidence: Path) -> dict[str, Any]:
    out = check("R2_MANIFEST", "the manifest hashes every artefact and nothing else")
    payload = read_json(evidence / MANIFEST)
    recorded = {str(k): str(v) for k, v in (payload.get("files") or {}).items()}
    actual: dict[str, str] = {}
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != MANIFEST:
            actual[path.relative_to(evidence).as_posix()] = sha256_file(path)
    missing = sorted(set(recorded) - set(actual))
    extra = sorted(set(actual) - set(recorded))
    changed = sorted(name for name in set(recorded) & set(actual) if recorded[name] != actual[name])
    if not payload:
        out["problems"].append("manifest missing")
    elif missing or extra or changed:
        out["problems"].append(f"missing={missing} extra={extra} changed={changed}")
    out["detail"] = f"{len(recorded)} recorded, {len(actual)} on disk"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def verdict_check(report: dict[str, Any]) -> dict[str, Any]:
    out = check("R3_VERDICT", "the verdict follows from the step statuses, and only PASS certifies")
    steps = report.get("steps") or {}
    statuses = [str(step.get("status")) for step in steps.values()]
    if "BLOCKED" in statuses:
        derived = "BLOCKED"
    elif "FAIL" in statuses:
        derived = "FAIL"
    elif "NOT_TESTED" in statuses:
        derived = "NOT_TESTED"
    else:
        derived = "PASS"
    if not steps:
        out["problems"].append("no steps recorded")
    if derived != report.get("verdict"):
        out["problems"].append(f"recorded {report.get('verdict')} derived {derived}")
    if derived != "PASS":
        failing = {
            identifier: step.get("status")
            for identifier, step in steps.items()
            if step.get("status") != "PASS"
        }
        out["problems"].append(f"not a pass: {failing}")
    if report.get("certifies") is not True:
        out["problems"].append("certifies is not true")
    out["detail"] = f"derived={derived} recorded={report.get('verdict')} steps={len(steps)}"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def binding_check(report: dict[str, Any], evidence: Path, repo: Path) -> dict[str, Any]:
    out = check("R4_BINDING", "every artefact names the commit the campaigns ran on")
    candidate = str(report.get("commit") or "")
    head = git(repo, "rev-parse", "HEAD")
    if candidate != head:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", candidate, head],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        changed = [
            line for line in git(repo, "diff", "--name-only", candidate, head).splitlines() if line
        ]
        offending = sorted(path for path in changed if not path.startswith(EVIDENCE_ONLY_PREFIXES))
        if ancestor.returncode != 0:
            out["problems"].append(f"{candidate[:12]} is not an ancestor of HEAD {head[:12]}")
        elif offending:
            out["problems"].append(f"code changed since the run: {offending[:6]}")
        out["detail"] = f"descendant: {len(changed)} evidence-only file(s)"
    for name, path in (
        ("supervisor", evidence / "campaigns" / "supervisor" / "CAMPAIGN.json"),
        ("lock", evidence / "campaigns" / "lock" / "CAMPAIGN.json"),
    ):
        recorded = str(read_json(path).get("commit") or "")
        if recorded != candidate:
            out["problems"].append(f"{name} campaign {recorded[:12]} != {candidate[:12]}")
    for name, path in (
        ("supervisor", evidence / "SUPERVISOR_VERIFICATION.json"),
        ("lock", evidence / "LOCK_CAMPAIGN_VERIFICATION.json"),
    ):
        recorded = str(read_json(path).get("verifier_commit") or "")
        if recorded != candidate:
            out["problems"].append(f"{name} verifier {recorded[:12]} != {candidate[:12]}")
    if candidate == head:
        out["detail"] = f"candidate={candidate[:12]} is HEAD"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def lock_facts_check(evidence: Path) -> dict[str, Any]:
    out = check("R5_LOCK_FACTS", "the lock campaign on disk has the shape and the facts claimed")
    root = evidence / "campaigns" / "lock"
    campaign = read_json(root / "CAMPAIGN.json")
    chain = chain_of(root / "session" / "STREAM.jsonl")
    entries = chain.get("entries") or []
    iterations = campaign.get("iterations") or []
    recovery = sorted(root.glob("iterations/iteration-*/RECOVERY.json"))
    mixes = [
        sorted({int(lock.get("fence", 0)) for lock in (row.get("locks") or [])})
        for row in entries
        if entry_is_reclaim(row)
    ]
    fences = [group[0] if len(group) == 1 else -1 for group in mixes]
    cycles = [entry.get("cycle") for entry in entries if entry.get("kind") == "CYCLE"]
    live = [
        int(entry.get("live_orders", 0) or 0)
        for entry in entries
        if entry.get("kind") == "CYCLE" or "live_orders" in entry
    ]
    problems = out["problems"]
    if not campaign:
        problems.append("CAMPAIGN.json missing")
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if len(iterations) != LOCK_ITERATIONS:
        problems.append(f"{len(iterations)} iterations, contract is {LOCK_ITERATIONS}")
    if len(recovery) != LOCK_ITERATIONS:
        problems.append(f"{len(recovery)} RECOVERY.json, contract is {LOCK_ITERATIONS}")
    for index, path in enumerate(recovery, start=1):
        row = read_json(path)
        if row.get("exit_code") != 0:
            problems.append(f"iteration {index} resume exit {row.get('exit_code')}")
        if row.get("locks_after"):
            problems.append(f"iteration {index} left locks")
    if len(mixes) != len(iterations):
        problems.append(f"{len(mixes)} reclaim rows for {len(iterations)} iterations")
    if -1 in fences or fences != sorted(set(fences)):
        problems.append(f"fences do not advance cleanly: {fences}")
    if len([row for row in iterations if row.get("concurrency") is not None]) != LOCK_RACES:
        problems.append("the campaign did not race two reclaimers at two iterations")
    if len(cycles) != len(set(cycles)) or cycles != sorted(cycles):
        problems.append(f"cycle numbering {cycles}")
    if locks(root):
        problems.append(f"locks still on disk: {locks(root)}")
    if any(live):
        problems.append("a live order was recorded")
    if int(campaign.get("live_orders") or 0) != 0:
        problems.append("the campaign reports live orders")
    out["detail"] = (
        f"iterations={len(iterations)} recovery={len(recovery)} cycles={len(cycles)} "
        f"fences={fences} rows={chain.get('lines')}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def entry_is_reclaim(row: dict[str, Any]) -> bool:
    return row.get("kind") == "LOCK_RECLAIMED"


def supervisor_facts_check(evidence: Path) -> dict[str, Any]:
    out = check("R6_SUPERVISOR_FACTS", "the supervisor campaign on disk recovered without a lock")
    root = evidence / "campaigns" / "supervisor"
    campaign = read_json(root / "CAMPAIGN.json")
    final = campaign.get("final") or {}
    chain = chain_of(root / "session" / "STREAM.jsonl")
    entries = chain.get("entries") or []
    cycles = [entry.get("cycle") for entry in entries if entry.get("kind") == "CYCLE"]
    live = [
        int(entry.get("live_orders", 0) or 0)
        for entry in entries
        if entry.get("kind") == "CYCLE" or "live_orders" in entry
    ]
    scenarios = read_json(root / "scenarios" / "SCENARIOS.json").get("scenarios") or {}
    problems = out["problems"]
    if not campaign:
        problems.append("CAMPAIGN.json missing")
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if len(cycles) < 2:
        problems.append(f"{len(cycles)} cycles, a multi-cycle campaign needs two")
    if cycles != sorted(cycles) or len(cycles) != len(set(cycles)):
        problems.append(f"cycle numbering {cycles}")
    if final.get("state") != "RECOVERED":
        problems.append(f"final state {final.get('state')}")
    if final.get("cycles") != cycles:
        problems.append("CAMPAIGN.final.cycles does not match the stream")
    if locks(root):
        problems.append(f"locks still on disk: {locks(root)}")
    if any(live):
        problems.append("a live order was recorded")
    if int(campaign.get("live_orders") or 0) != 0:
        problems.append("the campaign reports live orders")
    if set(scenarios) != {"corrupt", "budget"}:
        problems.append(f"negative scenarios {sorted(scenarios)}")
    out["detail"] = (
        f"cycles={cycles} state={final.get('state')} rows={chain.get('lines')} "
        f"scenarios={sorted(scenarios)}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def verifier_floors_check(evidence: Path) -> dict[str, Any]:
    out = check("R7_VERIFIER_FLOORS", "both verifier reports are truthful at their published size")
    for name, path, root, min_checks, min_mutants in (
        (
            "supervisor",
            evidence / "SUPERVISOR_VERIFICATION.json",
            evidence / "campaigns" / "supervisor",
            MIN_SUPERVISOR_CHECKS,
            MIN_SUPERVISOR_MUTATIONS,
        ),
        (
            "lock",
            evidence / "LOCK_CAMPAIGN_VERIFICATION.json",
            evidence / "campaigns" / "lock",
            MIN_LOCK_CHECKS,
            MIN_LOCK_MUTATIONS,
        ),
    ):
        report = read_json(path)
        if not report:
            out["problems"].append(f"{name} report missing")
            continue
        judgement = report.get("judgement") or {}
        checks = judgement.get("checks") or {}
        failed = sorted(key for key, value in checks.items() if value is False)
        applicable = [row for row in report.get("adversarial") or [] if row.get("applicable", True)]
        undetected = [row.get("mutation") for row in applicable if not row.get("detected")]
        not_applicable = report.get("not_applicable_checks") or judgement.get(
            "not_applicable_checks"
        )
        bad = sorted(
            key
            for key, digest in (report.get("artifacts") or {}).items()
            if sha256_file(root / key) != digest
        )
        if report.get("verdict") != "PASS":
            out["problems"].append(f"{name} verdict {report.get('verdict')}")
        if failed:
            out["problems"].append(f"{name} checks false {failed}")
        if len(checks) < min_checks:
            out["problems"].append(f"{name} checks {len(checks)} < {min_checks}")
        if not_applicable:
            out["problems"].append(f"{name} not applicable {not_applicable}")
        if len(applicable) < min_mutants:
            out["problems"].append(f"{name} mutations {len(applicable)} < {min_mutants}")
        if undetected:
            out["problems"].append(f"{name} undetected {undetected}")
        if report.get("false_success") != 0:
            out["problems"].append(f"{name} false_success {report.get('false_success')}")
        if bad:
            out["problems"].append(f"{name} artefact hashes {bad}")
    out["detail"] = f"{len(out['problems'])} disagreement(s)"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def audit_check(evidence: Path) -> dict[str, Any]:
    out = check("R8_AUDIT_CLAIMS", "the independent audit passed all five claims")
    payload = read_json(evidence / "CAMPAIGN_AUDIT.json")
    claims = payload.get("claims") or {}
    if not payload:
        out["problems"].append("audit report missing")
    if payload.get("verdict") != "PASS":
        out["problems"].append(f"audit verdict {payload.get('verdict')}")
    if set(claims) != {"C1", "L1", "S1", "S2", "V1"}:
        out["problems"].append(f"claims {sorted(claims)}")
    for identifier, row in claims.items():
        if row.get("status") != "PASS":
            out["problems"].append(f"{identifier} {row.get('status')} {row.get('problems')}")
    if payload.get("false_success") != 0:
        out["problems"].append(f"audit false_success {payload.get('false_success')}")
    out["detail"] = f"{len(claims)} claims, false_success={payload.get('false_success')}"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def stability_check(report: dict[str, Any]) -> dict[str, Any]:
    out = check("R9_STABILITY", "the tree was clean and the commit never moved")
    tree = report.get("tree") or {}
    stability = report.get("commit_stability") or {}
    step = (report.get("steps") or {}).get("S1_COMMIT_STABLE") or {}
    if tree.get("clean_before") is not True or tree.get("clean_after") is not True:
        out["problems"].append("the tree was not clean at both ends")
    if stability.get("head_before") != stability.get("head_after"):
        out["problems"].append("HEAD changed during the run")
    if stability.get("head_before") != report.get("commit"):
        out["problems"].append("the stability record and the report disagree on the commit")
    moved = [sha for sha in stability.get("observed_commits") or [] if sha != report.get("commit")]
    if moved:
        out["problems"].append(f"a poll saw another commit: {moved}")
    if step.get("status") != "PASS":
        out["problems"].append(f"S1_COMMIT_STABLE is {step.get('status')}")
    out["detail"] = (
        f"clean={tree.get('clean_before')}/{tree.get('clean_after')} "
        f"observed={len(stability.get('observed_commits') or [])}"
    )
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


def ci_wiring_check() -> dict[str, Any]:
    out = check("R10_CI_WIRING", "CI invokes the gate and no step can swallow a failure")
    if not WORKFLOW.is_file():
        out["problems"].append(f"{WORKFLOW.relative_to(REPO)} missing")
        out["status"] = "FAIL"
        return out
    raw = WORKFLOW.read_text(encoding="utf-8")
    #: Comments may name the things the workflow forbids; only executable lines count.
    text = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    if "tap_integration_gate.py" not in text:
        out["problems"].append("the workflow does not invoke the gate")
    if "review_gate.py" not in text:
        out["problems"].append("the workflow does not invoke the reviewer")
    if "continue-on-error" in text:
        out["problems"].append("the workflow softens a step with continue-on-error")
    if "preflight" in text and "--skip" in text:
        out["problems"].append("the workflow can skip a campaign")
    out["detail"] = f"{WORKFLOW.relative_to(REPO).as_posix()}"
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


# --------------------------------------------------------------------------- controls


def run_gate_verify(evidence: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "verify", "--evidence", str(evidence), "--repo", str(REPO)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def control(
    identifier: str,
    statement: str,
    expectation: str,
    result: subprocess.CompletedProcess[str],
    needles: tuple[str, ...],
) -> dict[str, Any]:
    output = (result.stdout or "") + (result.stderr or "")
    found = [needle for needle in needles if needle in output]
    passed = result.returncode != 0 and (not needles or bool(found))
    return {
        "id": identifier,
        "statement": statement,
        "expectation": expectation,
        "exit_code": result.returncode,
        "matched": found,
        "passed": passed,
        "detail": "rejected as required" if passed else "the gate accepted what it must refuse",
        "output_tail": output.strip().splitlines()[-6:],
    }


def controls(evidence: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        candidate = str(read_json(evidence / "GATE_REPORT.json").get("commit") or "")

        # N0 — another delivery's evidence, copied so the original is untouched.
        if LEGACY_EVIDENCE.is_dir():
            legacy = tmp / "n0"
            shutil.copytree(LEGACY_EVIDENCE, legacy)
            results.append(
                control(
                    "N0_LEGACY_EVIDENCE",
                    "evidence from TAP-SUPERVISOR-INTEGRATION-002 is not this gate's evidence",
                    "refused because it carries no gate report",
                    run_gate_verify(legacy),
                    ("GATE_REPORT.json missing",),
                )
            )

        # N1 — same evidence, another commit, manifest rebuilt so only the binding can fail.
        stale = tmp / "n1"
        shutil.copytree(evidence, stale)
        report = read_json(stale / "GATE_REPORT.json")
        report["commit"] = "0" * 40
        write_json(stale / "GATE_REPORT.json", report)
        rewrite_manifest(stale, "0" * 40)
        results.append(
            control(
                "N1_STALE_COMMIT",
                "evidence whose commit is not this commit is refused even with a valid manifest",
                "COMMIT_MISMATCH",
                run_gate_verify(stale),
                ("COMMIT_MISMATCH",),
            )
        )

        # N2 — a real repository whose HEAD moves while the probe watches.
        repo = tmp / "n2"
        repo.mkdir()
        for argv in (
            ("init", "-q"),
            ("config", "user.email", "gate@example.invalid"),
            ("config", "user.name", "gate"),
        ):
            git(repo, *argv)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        git(repo, "add", "f.txt")
        git(repo, "commit", "-q", "-m", "start")
        mover = (
            "import subprocess,time;time.sleep(0.6);"
            "subprocess.run(['git','-c','user.email=g@e.invalid','-c','user.name=g',"
            "'commit','--allow-empty','-m','move'],check=True)"
        )
        moved = subprocess.run(
            [
                sys.executable,
                str(GATE),
                "commit-probe",
                "--repo",
                str(repo),
                "--interval-s",
                "0.05",
                "--",
                sys.executable,
                "-c",
                mover,
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        results.append(
            control(
                "N2_HEAD_MOVED",
                "a commit that moves while a command runs is a failure, not a footnote",
                "commit-probe exits non-zero and says HEAD moved",
                moved,
                ("HEAD moved",),
            )
        )

        # N3 — one iteration's recovery record removed from a copy of the campaign.
        absent = tmp / "n3"
        absent.mkdir()
        shutil.copytree(evidence / "campaigns" / "lock", absent / "lock")
        (absent / "lock" / "iterations" / "iteration-03" / "RECOVERY.json").unlink()
        audited = subprocess.run(
            [
                sys.executable,
                str(AUDITOR),
                "--supervisor",
                str(evidence / "campaigns" / "supervisor"),
                "--lock",
                str(absent / "lock"),
                "--supervisor-report",
                str(evidence / "SUPERVISOR_VERIFICATION.json"),
                "--lock-report",
                str(evidence / "LOCK_CAMPAIGN_VERIFICATION.json"),
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        results.append(
            control(
                "N3_ABSENT_RECOVERY",
                "a campaign missing one RECOVERY.json is not a recovered campaign",
                "the audit exits non-zero and names the recovery count",
                audited,
                ("RECOVERY.json",),
            )
        )

        # N4 — edited evidence, manifest left alone.
        mutated = tmp / "n4"
        shutil.copytree(evidence, mutated)
        edited = read_json(mutated / "LOCK_CAMPAIGN_VERIFICATION.json")
        edited["false_success"] = 7
        write_json(mutated / "LOCK_CAMPAIGN_VERIFICATION.json", edited)
        results.append(
            control(
                "N4_MUTATED_EVIDENCE",
                "an edited report is refused when the manifest no longer matches",
                "MANIFEST_MISMATCH",
                run_gate_verify(mutated),
                ("MANIFEST_MISMATCH",),
            )
        )

        # N5 — a campaign shortened and still declared complete.
        partial = tmp / "n5"
        partial.mkdir()
        shutil.copytree(evidence / "campaigns" / "lock", partial / "lock")
        shortened = read_json(partial / "lock" / "CAMPAIGN.json")
        shortened["iterations"] = (shortened.get("iterations") or [])[:-1]
        write_json(partial / "lock" / "CAMPAIGN.json", shortened)
        shutil.rmtree(partial / "lock" / "iterations" / "iteration-06")
        partial_audit = subprocess.run(
            [
                sys.executable,
                str(AUDITOR),
                "--supervisor",
                str(evidence / "campaigns" / "supervisor"),
                "--lock",
                str(partial / "lock"),
                "--supervisor-report",
                str(evidence / "SUPERVISOR_VERIFICATION.json"),
                "--lock-report",
                str(evidence / "LOCK_CAMPAIGN_VERIFICATION.json"),
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        results.append(
            control(
                "N5_PARTIAL_CAMPAIGN",
                "five iterations declared complete is not six",
                "the audit exits non-zero and names the iteration contract",
                partial_audit,
                ("contract is 6",),
            )
        )

        # N6 — a weakened verifier report with a rebuilt manifest.
        weakened = tmp / "n6"
        shutil.copytree(evidence, weakened)
        report = read_json(weakened / "LOCK_CAMPAIGN_VERIFICATION.json")
        report["adversarial"] = (report.get("adversarial") or [])[:5]
        checks = list((report.get("judgement") or {}).get("checks", {}).items())[:20]
        report.setdefault("judgement", {})["checks"] = dict(checks)
        report["false_success"] = 0
        report["undetected_mutations"] = []
        write_json(weakened / "LOCK_CAMPAIGN_VERIFICATION.json", report)
        rewrite_manifest(weakened, candidate)
        results.append(
            control(
                "N6_WEAKENED_REPORT",
                "a smaller report with the same PASS verdict is not a smaller campaign",
                "re-judgement disagrees with the recorded step",
                run_gate_verify(weakened),
                ("STEP_DISAGREEMENT", "CONTRACT"),
            )
        )

        # N7 — one verifier fails while every other step passes.
        failing = tmp / "n7"
        shutil.copytree(evidence, failing)
        report = read_json(failing / "LOCK_CAMPAIGN_VERIFICATION.json")
        report.setdefault("judgement", {}).setdefault("checks", {})["stream_chain_intact"] = False
        report["verdict"] = "FAIL"
        report["false_success"] = 1
        write_json(failing / "LOCK_CAMPAIGN_VERIFICATION.json", report)
        rewrite_manifest(failing, candidate)
        results.append(
            control(
                "N7_SINGLE_VERIFIER_FAILURE",
                "one failing verifier sinks the verdict although the rest passed",
                "verify exits non-zero and reports a derived failure",
                run_gate_verify(failing),
                ("VERDICT",),
            )
        )
    return results


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent review of an integration gate run")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--skip-controls",
        action="store_true",
        help="diagnostic only: skipping controls cannot produce a passing review",
    )
    args = parser.parse_args(argv)

    evidence = Path(args.evidence).resolve()
    repo = Path(args.repo).resolve()
    report = read_json(evidence / "GATE_REPORT.json")
    checks = [
        manifest_check(evidence),
        verdict_check(report),
        binding_check(report, evidence, repo),
        lock_facts_check(evidence),
        supervisor_facts_check(evidence),
        verifier_floors_check(evidence),
        audit_check(evidence),
        stability_check(report),
        ci_wiring_check(),
    ]
    controls_run = [] if args.skip_controls else controls(evidence)
    control_failures = [row["id"] for row in controls_run if not row["passed"]]
    failing = [row["id"] for row in checks if row["status"] != "PASS"]
    if not controls_run:
        failing.append("CONTROLS_NOT_RUN")
    if control_failures:
        failing.append("CONTROLS_FAILED")

    verdict = "PASS" if not failing else "FAIL"
    payload = {
        "schema": SCHEMA,
        "reviewed_at_utc": utc_now(),
        "reviewer": HERE.relative_to(REPO).as_posix(),
        "commit": report.get("commit"),
        "evidence": str(evidence),
        "checks": checks,
        "controls": controls_run,
        "control_failures": control_failures,
        "summary": {
            "checks": len(checks),
            "checks_passed": sum(1 for row in checks if row["status"] == "PASS"),
            "controls": len(controls_run),
            "controls_passed": sum(1 for row in controls_run if row["passed"]),
        },
        "failing": failing,
        "false_success": 0 if verdict == "PASS" else len(failing),
        "verdict": verdict,
    }
    if args.out:
        write_json(Path(args.out), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
