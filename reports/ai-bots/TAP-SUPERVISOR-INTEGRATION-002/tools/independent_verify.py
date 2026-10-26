"""Independent verification of TAP-SUPERVISOR-INTEGRATION-002.

``BUILDER != VERIFIER``.  This script imports nothing from ``trading_bot`` and nothing
from ``scripts/paper_supervisor_verify.py``: it re-reads the artefacts, recomputes the
hashes and the chain with its own copy of the canonicalisation rule, parses the pytest
logs, and checks Git state.  A claim is ``PASS`` only when the artefact says so, ``FAIL``
when it contradicts it, and ``UNKNOWN`` when the evidence is missing.

It also runs a **self-control**: the campaign claim is evaluated against a deliberately
tampered copy.  If the checker still reports PASS there, the checker is blind and the
run records a ``false_success`` — the same standard it applies to the builder.

    python reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-002/tools/independent_verify.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPORTS = HERE.parents[1]
REPO = HERE.parents[4]
EVIDENCE = REPORTS / "evidence"
CAMPAIGN = Path("C:/Users/GVLLFR0035/Downloads/ff-campaign-002")
CONTROLS = Path("C:/Users/GVLLFR0035/Downloads/ff-campaign-002-controls")
LOCK_CAMPAIGN = EVIDENCE / "LOCK_CAMPAIGN_FULL2"
GENESIS = "0" * 64
CANONICAL_SEPARATORS = (",", ":")


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=CANONICAL_SEPARATORS, ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def chain_of(stream: Path) -> dict[str, Any]:
    """Recompute the hash chain without importing the ledger that wrote it."""

    if not stream.is_file():
        return {"ok": False, "reason": "MISSING", "lines": 0, "entries": []}
    prev = GENESIS
    entries: list[dict[str, Any]] = []
    lines = 0
    for raw in stream.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        lines += 1
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "reason": f"BAD_JSON_AT_{lines}",
                "lines": lines,
                "entries": entries,
            }
        if int(row.get("seq", -1)) != lines:
            return {"ok": False, "reason": f"SEQ_AT_{lines}", "lines": lines, "entries": entries}
        if str(row.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"LINK_AT_{lines}", "lines": lines, "entries": entries}
        digest = sha256_bytes(
            canonical({"seq": lines, "prev_sha256": prev, "entry": row.get("entry")}).encode()
        )
        if digest != str(row.get("sha256")):
            return {"ok": False, "reason": f"SHA_AT_{lines}", "lines": lines, "entries": entries}
        prev = digest
        entries.append(row.get("entry") or {})
    return {"ok": True, "reason": "INTACT", "lines": lines, "head": prev, "entries": entries}


# --------------------------------------------------------------------------- checks


def claim(identifier: str, statement: str, method: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "claim": statement,
        "method": method,
        "status": "UNKNOWN",
        "detail": "",
        "evidence": [],
    }


def route_manifest_claim() -> dict[str, Any]:
    out = claim(
        "R1",
        "every migrated route is byte-identical to the lane blob it came from, except the declared edits",
        "recompute sha256 of each destination and compare with ROUTE_MANIFEST.json",
    )
    manifest = read_json(REPORTS / "ROUTE_MANIFEST.json")
    routes = manifest.get("routes") or []
    edits = manifest.get("post_migration_edits") or {}
    if not routes:
        out["detail"] = "ROUTE_MANIFEST.json missing or empty"
        return out
    mismatched, edited, missing = [], [], []
    for row in routes:
        path = row["path"]
        dest = REPO / path
        digest = sha256_file(dest)
        if digest is None:
            missing.append(path)
            continue
        if digest == row.get("lane_sha256"):
            continue
        if path in edits:
            edited.append(path)
        else:
            mismatched.append({"path": path, "expected": row.get("lane_sha256"), "actual": digest})
    out["detail"] = (
        f"{len(routes)} routes; {len(missing)} missing; {len(mismatched)} mismatched; "
        f"{len(edited)} declared edits"
    )
    out["evidence"] = [f"edited: {sorted(edited)}"]
    out["status"] = "PASS" if not missing and not mismatched else "FAIL"
    return out


def campaign_claim(root: Path = CAMPAIGN) -> dict[str, Any]:
    out = claim(
        "C1",
        "the PAPER campaign ran multiple cycles, recovered from a crash, left no lock and sent no live order",
        "re-hash session/STREAM.jsonl, read CAMPAIGN.json, list *.lock, scan live_orders",
    )
    campaign = read_json(root / "CAMPAIGN.json")
    final = campaign.get("final") or {}
    chain = chain_of(root / "session" / "STREAM.jsonl")
    locks = (
        sorted(p.relative_to(root).as_posix() for p in (root / "session").rglob("*.lock"))
        if (root / "session").is_dir()
        else []
    )
    entries = chain.get("entries") or []
    cycles = [e.get("cycle") for e in entries if e.get("kind") == "CYCLE"]
    live = [int(e.get("live_orders", 0) or 0) for e in entries if "live_orders" in e]
    run_meta = read_json(root / "session" / "RUN_META.json")
    result = read_json(root / "supervisor" / "SUPERVISOR_RESULT.json")

    problems = []
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if not cycles:
        problems.append("no cycles")
    if final.get("cycles") != cycles:
        problems.append(f"CAMPAIGN.final.cycles {final.get('cycles')} != stream {cycles}")
    if final.get("state") != "RECOVERED":
        problems.append(f"final state {final.get('state')}")
    if locks:
        problems.append(f"leftover locks {locks}")
    if any(live):
        problems.append("a live_order is non-zero")
    if result.get("action") != "STOP_COMPLETED":
        problems.append(f"supervisor action {result.get('action')}")
    if run_meta.get("mode") != "PAPER" or run_meta.get("live_enabled") is not False:
        problems.append(
            f"run meta mode={run_meta.get('mode')} live_enabled={run_meta.get('live_enabled')}"
        )
    if len(cycles) < 2:
        problems.append("fewer than two cycles: not a multi-cycle campaign")

    out["detail"] = (
        f"cycles={cycles} lines={chain['lines']} state={final.get('state')} "
        f"locks={locks} live_orders={sorted(set(live))} action={result.get('action')}"
    )
    out["evidence"] = [f"chain head {chain.get('head')}", f"problems: {problems}"]
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def lock_campaign_claim(root: Path = LOCK_CAMPAIGN) -> dict[str, Any]:
    """The lock campaign, judged from its own stream rather than from its verifier.

    ``paper_lock_campaign_verify.py`` is the builder's verifier; this claim does not read
    its verdict to decide anything.  It re-walks the six iterations on disk, recounts the
    stream, and only then compares the verifier's numbers with its own as an *agreement*
    check: a verifier that reports a different campaign is a failure, not corroboration.
    """

    out = claim(
        "L1",
        "six crash sites were each reclaimed once, every resume exited 0, no lock survived and no order was live",
        "re-hash STREAM.jsonl, recount rows and cycles, stat every iteration, list *.lock",
    )
    campaign = read_json(root / "CAMPAIGN.json")
    if not campaign:
        out["detail"] = "CAMPAIGN.json missing"
        return out
    chain = chain_of(root / "session" / "STREAM.jsonl")
    entries = chain.get("entries") or []
    kinds: list[str] = [str(e.get("kind")) for e in entries]
    cycles = [e.get("cycle") for e in entries if e.get("kind") == "CYCLE"]
    iterations = campaign.get("iterations") or []
    recovery_files = sorted(root.glob("iterations/iteration-*/RECOVERY.json"))
    resumes = [read_json(path) for path in recovery_files]
    reclaims = [e for e in entries if e.get("kind") == "LOCK_RECLAIMED"]
    #: One reclaim takes over every lock of a dead owner at the *same* fence: the fences
    #: must advance from one reclaim to the next, not between the locks of one reclaim.
    row_fences = [
        sorted({int(lock.get("fence", 0)) for lock in (row.get("locks") or [])}) for row in reclaims
    ]
    fences = [group[0] if len(group) == 1 else group for group in row_fences]
    live = [
        int(e.get("live_orders", 0) or 0)
        for e in entries
        if e.get("kind") == "CYCLE" or "live_orders" in e
    ]
    locks = (
        sorted(p.relative_to(root).as_posix() for p in (root / "session").rglob("*.lock"))
        if (root / "session").is_dir()
        else []
    )
    report = read_json(EVIDENCE / "LOCK_CAMPAIGN_VERIFICATION_FULL.json")
    judged = (report.get("judgement") or {}).get("counts") or {}
    mine = {
        "cycles": len(cycles),
        "iterations": len(iterations),
        "reclaim_rows": len(reclaims),
        "rows": chain.get("lines", 0),
        "starts": kinds.count("SESSION_START"),
    }

    problems: list[str] = []
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if len(iterations) != 6:
        problems.append(f"{len(iterations)} iterations, contract is 6")
    if len(recovery_files) != len(iterations) or any(not row for row in resumes):
        problems.append(f"{len(recovery_files)} RECOVERY.json for {len(iterations)} iterations")
    for index, row in enumerate(resumes, start=1):
        if row.get("exit_code") != 0:
            problems.append(f"iteration {index} resume exit {row.get('exit_code')}")
        if row.get("locks_after"):
            problems.append(f"iteration {index} left {len(row['locks_after'])} lock(s)")
    for index, row in enumerate(iterations, start=1):
        if row.get("failure") or (row.get("after") or {}).get("exit_code") != 0:
            problems.append(f"iteration {index} failure={row.get('failure')}")
    if len(cycles) != len(set(cycles)) or cycles != sorted(cycles):
        problems.append(f"cycle numbering {cycles}")
    if len(reclaims) != len(iterations):
        problems.append(f"{len(reclaims)} reclaim rows for {len(iterations)} crashes")
    mixed = [group for group in row_fences if len(group) != 1]
    if mixed:
        problems.append(f"a reclaim mixed fences: {mixed}")
    if fences != sorted(set(fences)):
        problems.append(f"reclaim fences do not advance: {fences}")
    if locks:
        problems.append(f"lock files still on disk: {locks}")
    if any(live):
        problems.append("a live_order is non-zero")
    if kinds.count("SESSION_END") != len(iterations):
        problems.append(f"{kinds.count('SESSION_END')} SESSION_END rows")
    for index, row in enumerate(iterations, start=1):
        race = row.get("concurrency")
        if race is not None and race.get("reclaimers") != 1:
            problems.append(f"iteration {index} race winners={race.get('reclaimers')}")
    if not report:
        problems.append("LOCK_CAMPAIGN_VERIFICATION_FULL.json missing")
    else:
        if report.get("verdict") != "PASS" or report.get("false_success") not in (0, None):
            problems.append(f"verifier verdict {report.get('verdict')}")
        disagreement = {k: (mine[k], judged.get(k)) for k in mine if judged.get(k) != mine[k]}
        if disagreement:
            problems.append(f"verifier counts disagree (mine, theirs): {disagreement}")
        failed = sorted(
            name
            for name, value in (report.get("judgement") or {}).get("checks", {}).items()
            if value is False
        )
        if failed:
            problems.append(f"verifier checks false: {failed}")

    out["detail"] = (
        f"iterations={len(iterations)} cycles={cycles} reclaims={len(reclaims)} "
        f"fences={fences} rows={chain.get('lines')} locks={locks} live_orders={sorted(set(live))}"
    )
    out["evidence"] = [f"chain head {chain.get('head')}", f"problems: {problems}"]
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def lock_self_control_claim() -> dict[str, Any]:
    out = claim(
        "S2",
        "the lock-campaign check is not blind: removing one iteration's recovery must fail it",
        "delete iterations/iteration-03/RECOVERY.json in a temporary copy and re-evaluate L1",
    )
    if not LOCK_CAMPAIGN.is_dir():
        out["detail"] = "the campaign copy is absent; the self-control cannot run"
        return out
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "campaign"
        shutil.copytree(LOCK_CAMPAIGN, copy)
        (copy / "iterations" / "iteration-03" / "RECOVERY.json").unlink()
        verdict = lock_campaign_claim(copy)
    out["detail"] = f"tampered campaign evaluated as {verdict['status']} ({verdict['detail']})"
    out["evidence"] = verdict["evidence"][1:]
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


def verifier_report_claim() -> dict[str, Any]:
    out = claim(
        "V1",
        "the campaign verifier's report is truthful: PASS, every applicable mutation detected, no false success",
        "recompute every artefact hash, re-check the verdict fields and the mutation lists",
    )
    report = read_json(EVIDENCE / "REAL_CAMPAIGN_VERIFICATION.json")
    if not report:
        out["detail"] = "REAL_CAMPAIGN_VERIFICATION.json missing"
        return out
    artefacts = report.get("artifacts") or {}
    bad = {
        name: digest for name, digest in artefacts.items() if sha256_file(CAMPAIGN / name) != digest
    }
    judgement = report.get("judgement") or {}
    mutants = report.get("adversarial") or []
    applicable = [m for m in mutants if m.get("applicable", True)]
    undetected = [m["mutation"] for m in applicable if not m.get("detected")]
    checks = judgement.get("checks") or {}
    failed_checks = sorted(name for name, value in checks.items() if value is False)
    problems = []
    if bad:
        problems.append(f"artefact hashes disagree: {sorted(bad)}")
    if report.get("verdict") != "PASS":
        problems.append(f"verdict {report.get('verdict')}")
    if judgement.get("verdict") != "PASS":
        problems.append(f"judgement {judgement.get('verdict')}")
    if failed_checks:
        problems.append(f"failed checks {failed_checks}")
    if report.get("false_success") != 0 or undetected:
        problems.append(f"false_success {report.get('false_success')} undetected {undetected}")
    if len(applicable) < 8:
        problems.append(f"only {len(applicable)} applicable mutations")
    out["detail"] = (
        f"artifacts={len(artefacts)} hashed; checks={len(checks)} failed={failed_checks}; "
        f"applicable mutations={len(applicable)} undetected={undetected}"
    )
    out["evidence"] = [f"not applicable: {report.get('not_applicable_mutations')}"]
    out["status"] = "PASS" if not problems else "FAIL"
    out["_problems"] = problems
    return out


def controls_claim() -> dict[str, Any]:
    out = claim(
        "V2",
        "the verifier rejects absent, tampered and leftover-lock campaigns",
        "re-run the verifier on four constructed copies and require FAIL",
    )
    cases = {
        "absent": "seq_continuous",
        "live_order": "stream_chain_intact",
        "residual_lock": "no_lock_remaining_now",
        "broken_chain": "stream_chain_intact",
    }
    results = {}
    for name, expected in cases.items():
        target = EVIDENCE / f"CONTROL_{name}.json"
        payload = read_json(target)
        failed = sorted(
            k for k, v in (payload.get("judgement", {}).get("checks") or {}).items() if v is False
        )
        results[name] = {
            "verdict": payload.get("verdict"),
            "expected_check_failed": expected in failed,
            "failed_checks": failed,
        }
    ok = all(row["verdict"] == "FAIL" and row["expected_check_failed"] for row in results.values())
    out["detail"] = json.dumps({k: v["verdict"] for k, v in results.items()})
    out["evidence"] = [json.dumps(results, sort_keys=True)[:1200]]
    out["status"] = "PASS" if ok else "FAIL"
    return out


def self_control_claim() -> dict[str, Any]:
    out = claim(
        "S1",
        "this checker is not blind: the campaign claim must fail on a tampered chain",
        "evaluate C1's own method against CONTROL_broken_chain",
    )
    tampered = CONTROLS / "broken_chain"
    if not tampered.is_dir():
        out["detail"] = "the tampered copy is absent; the self-control cannot run"
        return out
    verdict = campaign_claim(tampered)
    out["detail"] = f"tampered campaign evaluated as {verdict['status']} ({verdict['detail']})"
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


def tests_claim() -> dict[str, Any]:
    out = claim(
        "T1",
        "the pytest logs support the numbers this report quotes",
        "parse the summary line of each log",
    )
    expected = {
        "PYTEST_paper_risk_after_tests.log": (2, 220),
        "PYTEST_paper_risk_main_baseline.log": (6, 170),
    }
    results = {}
    for name, (failed, passed) in expected.items():
        text = (
            (EVIDENCE / name).read_text(encoding="utf-8", errors="replace")
            if (EVIDENCE / name).is_file()
            else ""
        )
        match = re.search(r"(\d+) failed, (\d+) passed", text)
        if not match:
            results[name] = "UNKNOWN"
            continue
        results[name] = (
            "PASS"
            if (int(match.group(1)), int(match.group(2))) == (failed, passed)
            else f"FAIL {match.groups()}"
        )
    ok = all(value == "PASS" for value in results.values())
    out["detail"] = json.dumps(results)
    out["status"] = "PASS" if ok else "FAIL"
    return out


def git_claim() -> dict[str, Any]:
    out = claim(
        "G1",
        "the work happened on a branch derived from main, and main itself did not move",
        "git rev-parse / rev-list / merge-base",
    )
    main_tip = git("rev-parse", "main")
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    base = git("merge-base", "main", "HEAD")
    commits = int(git("rev-list", "--count", "main..HEAD"))
    lane_tip = git("rev-parse", "codepaper/supervisor-001")
    lane_merged = git("rev-list", "--count", "main..HEAD", "--merges")
    problems = []
    if main_tip != "e67194e79a42aef2a2ded3aca21ac4a0ea3689c5":
        problems.append(f"main moved to {main_tip}")
    if base != "e67194e79a42aef2a2ded3aca21ac4a0ea3689c5":
        problems.append(f"merge base {base}")
    if branch != "integ/supervisor-002":
        problems.append(f"branch {branch}")
    if commits > 8:
        problems.append(f"{commits} commits: this is not a slice")
    out["detail"] = (
        f"branch={branch} head={head[:8]} main={main_tip[:8]} base={base[:8]} "
        f"commits main..HEAD={commits} merge-commits={lane_merged} lane={lane_tip[:8]}"
    )
    out["status"] = "PASS" if not problems else "FAIL"
    out["evidence"] = problems
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(EVIDENCE / "INDEPENDENT_VERIFICATION.json"))
    args = parser.parse_args()

    claims = [
        git_claim(),
        route_manifest_claim(),
        campaign_claim(),
        lock_campaign_claim(),
        verifier_report_claim(),
        controls_claim(),
        self_control_claim(),
        lock_self_control_claim(),
        tests_claim(),
    ]
    false_success = sum(1 for item in claims if item["status"] == "PASS" and item.get("_problems"))
    for item in claims:
        item.pop("_problems", None)
    payload = {
        "schema_version": "TAP_SUPERVISOR_INTEGRATION_INDEPENDENT_VERIFICATION_V1",
        "verifier": "reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-002/tools/independent_verify.py",
        "imports_from_src": False,
        "head": git("rev-parse", "HEAD"),
        "claims": claims,
        "summary": {
            "pass": sum(1 for item in claims if item["status"] == "PASS"),
            "fail": sum(1 for item in claims if item["status"] == "FAIL"),
            "unknown": sum(1 for item in claims if item["status"] == "UNKNOWN"),
        },
        "false_success": false_success,
        "verdict": "PASS"
        if all(item["status"] == "PASS" for item in claims) and false_success == 0
        else "FAIL",
    }
    Path(args.out).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({item["id"]: item["status"] for item in claims}, indent=2))
    print(json.dumps(payload["summary"]), payload["verdict"])
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
