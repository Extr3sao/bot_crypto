"""Independent audit of the two PAPER campaigns an integration gate run produced.

``BUILDER != VERIFIER``.  This program imports nothing from ``trading_bot``, nothing from
``scripts/paper_supervisor_verify.py`` or ``scripts/paper_lock_campaign_verify.py``, and
nothing from ``scripts/tap_integration_gate.py``.  It re-reads the campaign directories,
recomputes the hash chain with its own copy of the canonicalisation rule, and decides every
claim from the bytes on disk.

Claim ids are the ones ``TAP-SUPERVISOR-INTEGRATION-002`` used, so the two deliveries can be
compared claim by claim:

``C1``  the supervisor campaign ran several cycles, recovered from its crash, left no lock
        and sent no live order;
``L1``  the lock campaign reclaimed each of its six crashed iterations exactly once, every
        resume exited 0, fences advance, no lock survived and no order was live;
``S1``  self-control: ``C1`` must fail on a copy whose chain is broken;
``S2``  self-control: ``L1`` must fail when one iteration's ``RECOVERY.json`` is removed;
``V1``  the two campaign verifiers' reports are truthful and agree with the bytes.

A claim is ``PASS`` only when the artefact supports it, ``FAIL`` when the artefact
contradicts it, and ``UNKNOWN`` when the evidence is missing.  ``UNKNOWN`` never counts as a
pass, and a self-control that cannot run is a ``FAIL``: a checker that cannot be shown to
reject a tampered campaign is a checker nobody has shown to work.

    python scripts/tap_gate_campaign_audit.py \
        --supervisor <out>/campaigns/supervisor \
        --lock <out>/campaigns/lock \
        --supervisor-report <out>/SUPERVISOR_VERIFICATION.json \
        --lock-report <out>/LOCK_CAMPAIGN_VERIFICATION.json \
        --out <out>/CAMPAIGN_AUDIT.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "TAP_INTEGRATION_GATE_CAMPAIGN_AUDIT_V1"
GENESIS = "0" * 64
CANONICAL_SEPARATORS = (",", ":")

#: The lock campaign's published contract (``paper_lock_campaign.py`` defaults as exercised by
#: TAP-SUPERVISOR-INTEGRATION-002 and pinned by ``paper_lock_campaign_verify.py``): six crash
#: iterations, two of which also race two independent reclaimers over the abandoned lock.
LOCK_ITERATIONS = 6
LOCK_RACES = 2

#: Floors taken from the two verifiers as published, not chosen here: the supervisor verifier
#: defines 33 checks and 14 mutations (31/12 applicable on a campaign without the negative
#: scenarios); the lock verifier defines 32 checks and 9 mutations.  A report below the floor
#: is a weakened report, not a smaller campaign.
MIN_SUPERVISOR_CHECKS = 31
MIN_LOCK_CHECKS = 32
MIN_SUPERVISOR_MUTATIONS = 8
MIN_LOCK_MUTATIONS = 9


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


def chain_of(stream: Path) -> dict[str, Any]:
    """Recompute the ledger hash chain without importing the ledger that wrote it."""

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
        entry = row.get("entry")
        entries.append(entry if isinstance(entry, dict) else {})
    return {"ok": True, "reason": "INTACT", "lines": lines, "head": prev, "entries": entries}


def claim(identifier: str, statement: str, method: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "claim": statement,
        "method": method,
        "status": "UNKNOWN",
        "detail": "",
        "evidence": [],
        "problems": [],
    }


def _locks(root: Path) -> list[str]:
    session = root / "session"
    if not session.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in session.rglob("*.lock"))


def supervisor_claim(root: Path) -> dict[str, Any]:
    out = claim(
        "C1",
        "the PAPER campaign ran several cycles, recovered from its crash, left no lock and "
        "sent no live order",
        "re-hash session/STREAM.jsonl, read CAMPAIGN.json and the supervisor result, list "
        "*.lock, scan live_orders",
    )
    campaign = read_json(root / "CAMPAIGN.json")
    if not campaign:
        out["detail"] = f"CAMPAIGN.json missing under {root}"
        return out
    final = campaign.get("final") or {}
    chain = chain_of(root / "session" / "STREAM.jsonl")
    entries = chain.get("entries") or []
    cycles = [entry.get("cycle") for entry in entries if entry.get("kind") == "CYCLE"]
    live = [int(entry.get("live_orders", 0) or 0) for entry in entries if "live_orders" in entry]
    run_meta = read_json(root / "session" / "RUN_META.json")
    result = read_json(root / "supervisor" / "SUPERVISOR_RESULT.json")
    scenarios = read_json(root / "scenarios" / "SCENARIOS.json").get("scenarios") or {}
    locks = _locks(root)

    problems: list[str] = []
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if not cycles:
        problems.append("no cycles")
    if len(cycles) < 2:
        problems.append(f"{len(cycles)} cycle(s): not a multi-cycle campaign")
    if len(cycles) != len(set(cycles)):
        problems.append(f"cycle numbering repeats: {cycles}")
    if final.get("cycles") != cycles:
        problems.append(f"CAMPAIGN.final.cycles {final.get('cycles')} != stream {cycles}")
    if final.get("state") != "RECOVERED":
        problems.append(f"final state {final.get('state')}")
    if locks:
        problems.append(f"leftover locks {locks}")
    if any(live):
        problems.append(f"a live_order is non-zero: {sorted(set(live))}")
    if result.get("action") != "STOP_COMPLETED":
        problems.append(f"supervisor action {result.get('action')}")
    if run_meta.get("mode") != "PAPER" or run_meta.get("live_enabled") is not False:
        problems.append(
            f"run meta mode={run_meta.get('mode')} live_enabled={run_meta.get('live_enabled')}"
        )
    if set(scenarios) != {"corrupt", "budget"}:
        problems.append(f"negative scenarios {sorted(scenarios)} != ['budget', 'corrupt']")

    out["detail"] = (
        f"cycles={cycles} lines={chain.get('lines')} state={final.get('state')} "
        f"locks={locks} live_orders={sorted(set(live))} action={result.get('action')} "
        f"scenarios={sorted(scenarios)}"
    )
    out["evidence"] = [f"chain head {chain.get('head')}"]
    out["problems"] = problems
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def lock_claim(root: Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    """The lock campaign, judged from its own stream rather than from its verifier."""

    out = claim(
        "L1",
        "six crash iterations were each reclaimed once, every resume exited 0, no lock "
        "survived and no order was live",
        "re-hash STREAM.jsonl, recount rows and cycles, stat every iteration, list *.lock",
    )
    campaign = read_json(root / "CAMPAIGN.json")
    if not campaign:
        out["detail"] = f"CAMPAIGN.json missing under {root}"
        return out
    chain = chain_of(root / "session" / "STREAM.jsonl")
    entries = chain.get("entries") or []
    kinds = [str(entry.get("kind")) for entry in entries]
    cycles = [entry.get("cycle") for entry in entries if entry.get("kind") == "CYCLE"]
    iterations = campaign.get("iterations") or []
    recovery_files = sorted(root.glob("iterations/iteration-*/RECOVERY.json"))
    resumes = [read_json(path) for path in recovery_files]
    reclaims = [entry for entry in entries if entry.get("kind") == "LOCK_RECLAIMED"]
    #: One reclaim takes over every lock of a dead owner at the *same* fence: the fences must
    #: advance from one reclaim to the next, not between the locks of one reclaim.
    row_fences = [
        sorted({int(lock.get("fence", 0)) for lock in (row.get("locks") or [])}) for row in reclaims
    ]
    fences = [group[0] if len(group) == 1 else group for group in row_fences]
    live = [
        int(entry.get("live_orders", 0) or 0)
        for entry in entries
        if entry.get("kind") == "CYCLE" or "live_orders" in entry
    ]
    locks = _locks(root)
    races = [row for row in iterations if row.get("concurrency") is not None]

    problems: list[str] = []
    if not chain["ok"]:
        problems.append(f"chain {chain['reason']}")
    if len(iterations) != LOCK_ITERATIONS:
        problems.append(f"{len(iterations)} iterations, contract is {LOCK_ITERATIONS}")
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
        problems.append(f"a live_order is non-zero: {sorted(set(live))}")
    if kinds.count("SESSION_END") != len(iterations):
        problems.append(f"{kinds.count('SESSION_END')} SESSION_END rows")
    if len(races) != LOCK_RACES:
        problems.append(f"{len(races)} instant(s) raced two reclaimers, contract is {LOCK_RACES}")
    for index, row in enumerate(iterations, start=1):
        race = row.get("concurrency")
        if race is not None and race.get("reclaimers") != 1:
            problems.append(f"iteration {index} race winners={race.get('reclaimers')}")
    sites = {str(row.get("crash_site")) for row in iterations}
    if not {"AFTER_CYCLE", "BEFORE_CYCLE"} <= sites:
        problems.append(f"crash sites do not cover both windows: {sorted(sites)}")

    mine = {
        "cycles": len(cycles),
        "iterations": len(iterations),
        "reclaim_rows": len(reclaims),
        "rows": chain.get("lines", 0),
        "starts": kinds.count("SESSION_START"),
    }
    if report is not None:
        if report.get("verdict") != "PASS" or report.get("false_success") not in (0, None):
            problems.append(f"verifier verdict {report.get('verdict')}")
        judged = (report.get("judgement") or {}).get("counts") or {}
        disagreement = {
            key: (mine[key], judged.get(key)) for key in mine if judged.get(key) != mine[key]
        }
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
        f"fences={fences} races={len(races)} rows={chain.get('lines')} locks={locks} "
        f"live_orders={sorted(set(live))}"
    )
    out["evidence"] = [f"chain head {chain.get('head')}", f"counts {mine}"]
    out["problems"] = problems
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def _artefact_problems(root: Path, report: dict[str, Any]) -> list[str]:
    artefacts = report.get("artifacts") or {}
    bad = sorted(name for name, digest in artefacts.items() if sha256_file(root / name) != digest)
    return [f"artefact hashes disagree: {bad}"] if bad else []


def verifier_reports_claim(
    supervisor_root: Path,
    supervisor_report: dict[str, Any],
    lock_root: Path,
    lock_report: dict[str, Any],
) -> dict[str, Any]:
    out = claim(
        "V1",
        "both campaign verifiers report the campaign that is on disk, with no undetected "
        "mutation and no false success",
        "recompute every artefact hash, re-check the verdict fields, the mutation lists and "
        "the check counts against their published floors",
    )
    problems: list[str] = []
    for name, root, report, min_checks, min_mutants in (
        (
            "supervisor",
            supervisor_root,
            supervisor_report,
            MIN_SUPERVISOR_CHECKS,
            MIN_SUPERVISOR_MUTATIONS,
        ),
        ("lock", lock_root, lock_report, MIN_LOCK_CHECKS, MIN_LOCK_MUTATIONS),
    ):
        if not report:
            problems.append(f"{name} verifier report missing")
            continue
        judgement = report.get("judgement") or {}
        checks = judgement.get("checks") or {}
        failed = sorted(check for check, value in checks.items() if value is False)
        mutants = report.get("adversarial") or []
        applicable = [row for row in mutants if row.get("applicable", True)]
        undetected = [row.get("mutation") for row in applicable if not row.get("detected")]
        not_applicable = report.get("not_applicable_checks") or judgement.get(
            "not_applicable_checks"
        )
        problems.extend(_artefact_problems(root, report))
        if report.get("verdict") != "PASS":
            problems.append(f"{name} verdict {report.get('verdict')}")
        if judgement.get("verdict") != "PASS":
            problems.append(f"{name} judgement {judgement.get('verdict')}")
        if failed:
            problems.append(f"{name} checks false: {failed}")
        if len(checks) < min_checks:
            problems.append(f"{name} reports {len(checks)} checks, floor is {min_checks}")
        if not_applicable:
            problems.append(f"{name} checks not applicable: {not_applicable}")
        if report.get("false_success") != 0 or undetected:
            problems.append(
                f"{name} false_success {report.get('false_success')} undetected {undetected}"
            )
        if len(applicable) < min_mutants:
            problems.append(
                f"{name} reports {len(applicable)} applicable mutations, floor is {min_mutants}"
            )
        if report.get("invalid_mutations"):
            problems.append(f"{name} invalid mutations {report.get('invalid_mutations')}")

    supervisor_commit = str(read_json(supervisor_root / "CAMPAIGN.json").get("commit") or "")
    lock_commit = str(read_json(lock_root / "CAMPAIGN.json").get("commit") or "")
    for name, report, campaign_commit in (
        ("supervisor", supervisor_report, supervisor_commit),
        ("lock", lock_report, lock_commit),
    ):
        if not report:
            continue
        recorded = str(report.get("verifier_commit") or "")
        if not recorded:
            problems.append(f"{name} report records no verifier_commit")
        elif campaign_commit and recorded != campaign_commit:
            problems.append(
                f"{name} verifier_commit {recorded[:12]} != campaign commit {campaign_commit[:12]}"
            )

    supervisor_artefacts = len(supervisor_report.get("artifacts") or {})
    lock_artefacts = len(lock_report.get("artifacts") or {})
    supervisor_checks = len((supervisor_report.get("judgement") or {}).get("checks") or {})
    lock_checks = len((lock_report.get("judgement") or {}).get("checks") or {})
    out["detail"] = (
        f"supervisor checks={supervisor_checks} "
        f"mutations={len(supervisor_report.get('adversarial') or [])}; "
        f"lock checks={lock_checks} mutations={len(lock_report.get('adversarial') or [])}"
    )
    out["evidence"] = [
        f"supervisor artefacts={supervisor_artefacts}",
        f"lock artefacts={lock_artefacts}",
        f"campaign commits: supervisor={supervisor_commit[:12]} lock={lock_commit[:12]}",
    ]
    out["problems"] = problems
    out["status"] = "PASS" if not problems else "FAIL"
    return out


def self_control_supervisor(root: Path) -> dict[str, Any]:
    """S1: the checker is not blind — a broken chain must be judged FAIL."""

    out = claim(
        "S1",
        "the supervisor check is not blind: breaking one stream line must fail C1",
        "rewrite one STREAM.jsonl row in a temporary copy without recomputing its sha256 and "
        "re-evaluate C1",
    )
    stream = root / "session" / "STREAM.jsonl"
    if not stream.is_file():
        out["detail"] = "the campaign has no stream; the self-control cannot run"
        out["status"] = "FAIL"
        out["problems"] = ["no stream to tamper with"]
        return out
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "campaign"
        shutil.copytree(root, copy)
        target = copy / "session" / "STREAM.jsonl"
        rows = target.read_text(encoding="utf-8").splitlines()
        middle = max(0, len(rows) // 2)
        payload = json.loads(rows[middle])
        entry = payload.get("entry")
        entry = entry if isinstance(entry, dict) else {}
        entry["live_orders"] = int(entry.get("live_orders", 0) or 0) + 1
        payload["entry"] = entry
        rows[middle] = json.dumps(payload, sort_keys=True)
        target.write_text("\n".join(rows) + "\n", encoding="utf-8")
        verdict = supervisor_claim(copy)
    out["detail"] = f"tampered campaign evaluated as {verdict['status']} ({verdict['detail']})"
    out["evidence"] = [f"problems: {verdict['problems']}"]
    out["problems"] = [] if verdict["status"] == "FAIL" else ["the tampered copy still passed"]
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


def self_control_lock(root: Path) -> dict[str, Any]:
    """S2: removing one iteration's recovery record must fail L1."""

    out = claim(
        "S2",
        "the lock check is not blind: removing one iteration's recovery must fail it",
        "delete iterations/iteration-03/RECOVERY.json in a temporary copy and re-evaluate L1",
    )
    target = root / "iterations" / "iteration-03" / "RECOVERY.json"
    if not target.is_file():
        out["detail"] = "the campaign has no iteration-03 recovery record to remove"
        out["status"] = "FAIL"
        out["problems"] = ["no recovery record to remove"]
        return out
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "campaign"
        shutil.copytree(root, copy)
        (copy / "iterations" / "iteration-03" / "RECOVERY.json").unlink()
        verdict = lock_claim(copy)
    out["detail"] = f"tampered campaign evaluated as {verdict['status']} ({verdict['detail']})"
    out["evidence"] = [f"problems: {verdict['problems']}"]
    out["problems"] = [] if verdict["status"] == "FAIL" else ["the tampered copy still passed"]
    out["status"] = "PASS" if verdict["status"] == "FAIL" else "FAIL"
    return out


def audit(
    supervisor_root: Path,
    lock_root: Path,
    supervisor_report: dict[str, Any],
    lock_report: dict[str, Any],
) -> dict[str, Any]:
    claims = [
        supervisor_claim(supervisor_root),
        lock_claim(lock_root, lock_report),
        self_control_supervisor(supervisor_root),
        self_control_lock(lock_root),
        verifier_reports_claim(supervisor_root, supervisor_report, lock_root, lock_report),
    ]
    by_id = {row["id"]: row for row in claims}
    false_success = int(
        (by_id["C1"]["status"] == "PASS" and by_id["S1"]["status"] != "PASS")
        or (by_id["L1"]["status"] == "PASS" and by_id["S2"]["status"] != "PASS")
    )
    passed = sum(1 for row in claims if row["status"] == "PASS")
    supervisor_commit = str(read_json(supervisor_root / "CAMPAIGN.json").get("commit") or "")
    lock_commit = str(read_json(lock_root / "CAMPAIGN.json").get("commit") or "")
    return {
        "schema": SCHEMA,
        "campaigns": {"supervisor": str(supervisor_root), "lock": str(lock_root)},
        "commits": {"supervisor": supervisor_commit, "lock": lock_commit},
        "claims": by_id,
        "summary": {
            "claims": len(claims),
            "pass": passed,
            "fail": sum(1 for row in claims if row["status"] == "FAIL"),
            "unknown": sum(1 for row in claims if row["status"] == "UNKNOWN"),
        },
        "false_success": false_success,
        "verdict": "PASS" if passed == len(claims) and false_success == 0 else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent audit of the gate's campaigns")
    parser.add_argument("--supervisor", required=True, help="supervisor campaign directory")
    parser.add_argument("--lock", required=True, help="lock campaign directory")
    parser.add_argument("--supervisor-report", required=True)
    parser.add_argument("--lock-report", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    payload = audit(
        Path(args.supervisor),
        Path(args.lock),
        read_json(Path(args.supervisor_report)),
        read_json(Path(args.lock_report)),
    )
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
