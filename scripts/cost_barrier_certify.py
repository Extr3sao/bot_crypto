"""CERTIFICATION GATE for the cost-barrier lane (WP-7F).

Certifying is not the same as passing one check. This gate requires, in order,
that a candidate satisfies all of:

1. **contracts and tests PASS** - the lane's contract tests are re-run here;
2. **input integrity** - the evidence bundle verifies: the digest-pinned copy of
   the gitignored input reproduces the digest the published artefact recorded,
   and the producer digests match the manifest;
3. **full reproduction on the candidate** - the drift gate re-runs the builder
   and the independent verifier and reaches ``FULL_REPRODUCTION_PASS``;
4. **independent verification** - that same run attests the artefact, with zero
   missed mutation controls and ``false_success`` 0;
5. **required adversarial controls** - the adversarial suite reports zero escapes
   and zero failed legs;
6. **persistent, identifiable evidence** - the record carries the commit, the
   environment and the digest of every artefact it rests on;
7. **zero hidden errors or blockers** - any non-zero step, any integrity failure
   and any blocked input refuses certification loudly.

Only ``FULL_REPRODUCTION_PASS`` satisfies the certification requirement, so a
``--check`` run can never be promoted into one, and a partial result can never
certify an economic result or promote a strategy. Nothing here authorizes
trading: ``NOT_AUTHORIZED``, zero trades, no live path - the lane stays read-only.

Read-only with respect to the repository: it writes only its own record (default
``data/recovery/wp7/COST_BARRIER_CERTIFICATION.json``), plus whatever
``scripts/cost_barrier_evidence.py --materialize`` places at the gitignored input
path, which is never a published artefact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

GATE = "scripts/cost_barrier_gate.py"
EVIDENCE = "scripts/cost_barrier_evidence.py"
ADVERSARIAL = "scripts/cost_barrier_adversarial.py"
CERTIFICATION = "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json"

LANE_TESTS: tuple[str, ...] = (
    "tests/unit/research/test_cost_barrier_explorer.py",
    "tests/unit/research/test_cost_barrier_gate.py",
    "tests/unit/research/test_cost_barrier_adversarial.py",
    "tests/unit/research/test_cost_barrier_ci_parity.py",
    # WP-ECONOMIC-RECOVERY-004: the ledger's identity contract is one of the things this
    # record certifies, so its tests belong to the gate that certifies it.
    "tests/unit/research/test_ledger_identity_contract.py",
)

# Everything the record rests on. Digests make the record identifiable; the
# watched set is what has to be clean for the record to describe a commit rather
# than a working copy.
EVIDENCE_PATHS: tuple[str, ...] = (
    "data/recovery/COST_BARRIER_EXPLORER.json",
    "data/recovery/COST_BARRIER_VERIFICATION.json",
    "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
    "data/recovery/wp7/evidence/COST_BARRIER.json",
    "data/recovery/wp7/evidence/INPUT_EVIDENCE.json",
    "data/recovery/wp7/evidence/PRODUCER_PINS.json",
    GATE,
    EVIDENCE,
    ADVERSARIAL,
    "scripts/cost_barrier_explorer.py",
    "scripts/cost_barrier_verify.py",
    ".github/workflows/cost-barrier-gate.yml",
)

CERTIFIED = "CERTIFIED"
PARTIAL = "PARTIAL"
BLOCKED = "BLOCKED_MISSING_INPUT"
FAILED = "FAILED"

CERTIFYING_STATUSES: tuple[str, ...] = (CERTIFIED,)

EXIT_CODES: dict[str, int] = {CERTIFIED: 0, PARTIAL: 2, BLOCKED: 3, FAILED: 4}


def content_digest(rel: str) -> str | None:
    """The digest that identifies an artefact's *content*, not a checkout's bytes.

    ``core.autocrlf`` rewrites line endings on checkout, so a raw-byte digest
    makes the same commit fingerprint differently on a CI runner than on the
    machine that wrote the record that travels with it - a difference that looks
    like changed evidence and is not. Line endings are normalised to LF, which is
    what git itself stores; a content change still moves the digest either way.
    """
    path = ROOT / rel
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha256_file(rel: str) -> str | None:
    path = ROOT / rel
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def git_value(*argv: str) -> str:
    out = subprocess.run(
        ["git", *argv], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_step(name: str, argv: list[str], timeout: int = 1800) -> dict[str, Any]:
    completed = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    return {
        "step": name,
        "command": " ".join(argv),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout_tail": (completed.stdout or "").strip()[-600:],
        "stderr_tail": (completed.stderr or "").strip()[-600:],
    }


def evaluate(
    *,
    gate_report: dict[str, Any] | None,
    contract_tests: dict[str, Any] | None,
    adversarial: dict[str, Any] | None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The certification decision, as a pure function so it can be tested.

    Every criterion is checked on the evidence handed in, and anything missing
    counts against certification: a record that cannot show its inputs did not
    verify them.
    """
    reasons: list[str] = []
    blocked_reasons: list[str] = []
    gate_status = (gate_report or {}).get("status")

    if integrity is None:
        reasons.append(
            "the evidence bundle was not verified for this candidate, so the inputs the "
            "reproduction consumed are not accounted for"
        )
    elif integrity.get("status") != "VERIFIED":
        if integrity.get("status") == "BLOCKED_MISSING_INPUT":
            blocked_reasons.append(
                f"the evidence bundle is incomplete: {(integrity.get('message') or '')[:200]}"
            )
        else:
            reasons.append(
                "the evidence bundle failed verification: "
                + "; ".join((integrity.get("failures") or ["no detail"])[:3])
            )

    if gate_report is None:
        reasons.append("there is no gate report to certify against")
    else:
        if gate_status == BLOCKED:
            blocked_reasons.append(
                "the drift gate could not start because a required input was missing: "
                + "; ".join((gate_report.get("blocked") or ["no detail"])[:2])
            )
        elif gate_status == PARTIAL or gate_status in ("CHECK_ONLY_PASS", "CHECK_ONLY_WITH_ADVISORIES"):
            reasons.append(
                f"the gate ran in {gate_report.get('mode')!r} mode and ended "
                f"{gate_status!r}: a check-only run is useful evidence and is never a full "
                "reproduction, so it cannot satisfy certification"
            )
        elif gate_status == "FULL_REPRODUCTION_FAIL":
            reasons.append(
                "the full reproduction did not hold: "
                + "; ".join((gate_report.get("failures") or ["no detail"])[:3])
            )
        elif gate_status == "INTEGRITY_FAILURE":
            reasons.append(
                "the run ended in INTEGRITY_FAILURE: "
                + "; ".join((gate_report.get("integrity_failures") or ["no detail"])[:3])
            )
        elif gate_status != "FULL_REPRODUCTION_PASS":
            reasons.append(f"unrecognised gate status {gate_status!r}")
        else:
            if gate_report.get("mode") != "full":
                reasons.append(
                    f"a FULL_REPRODUCTION_PASS report claims mode {gate_report.get('mode')!r}"
                )
            if gate_report.get("exit_code") != 0:
                reasons.append(
                    f"the report claims a full reproduction while carrying exit code "
                    f"{gate_report.get('exit_code')!r}"
                )
            if gate_report.get("checks_failed"):
                reasons.append(f"{gate_report['checks_failed']} check(s) failed")
            if gate_report.get("integrity_failures"):
                reasons.append("the report carries integrity failures")
            if gate_report.get("controls_missed"):
                reasons.append(f"{gate_report['controls_missed']} mutation control(s) missed")
            if (gate_report.get("claims") or {}).get("false_success") != 0:
                reasons.append("the report does not state false_success 0")

    if contract_tests is None:
        reasons.append("the contract tests were not run for this candidate")
    elif not contract_tests.get("passed"):
        reasons.append(
            f"the contract tests failed (exit {contract_tests.get('exit_code')}): "
            f"{(contract_tests.get('stderr_tail') or contract_tests.get('stdout_tail') or '')[:200]}"
        )

    if adversarial is None:
        reasons.append("the adversarial suite was not run for this candidate")
    else:
        escapes = adversarial.get("attacks_evaded")
        legs = adversarial.get("legs_failed") or []
        # A sweep without its substrate reports degenerations ('the gate was
        # already blocked') as detections, so its rate is not evidence at all.
        sweep_status = adversarial.get("status")
        substrate_present = (adversarial.get("substrate") or {}).get("present")
        if sweep_status != "EVALUATED":
            reasons.append(
                f"the adversarial suite reports status {sweep_status!r}, not 'EVALUATED': its "
                "substrate must be materialized before a detection rate counts as evidence"
                + (
                    f" - {(adversarial.get('substrate') or {}).get('why')}"
                    if adversarial.get("substrate") else ""
                )
            )
        elif substrate_present is not True:
            reasons.append(
                "the adversarial report does not attest that its substrate was present, so its "
                "detection rate is vacuous and cannot support a certification requirement"
            )
        if escapes:
            reasons.append(f"{escapes} adversarial attack(s) escaped the gate")
        if adversarial.get("escapes"):
            # A report may name escapes as rows or as bare ids; both have to be
            # readable, because a criterion that raises is a criterion that is
            # not applied.
            names = [
                row.get("attack_id") if isinstance(row, dict) else row
                for row in adversarial["escapes"]
            ]
            reasons.append("escapes: " + ", ".join(str(name) for name in names)[:200])
        if legs:
            reasons.append(f"{len(legs)} adversarial leg(s) failed: {legs[:3]}")
        if adversarial.get("attacks_total") in (None, 0):
            reasons.append("the adversarial suite reports no attacks, so it proves nothing")

    # A blocked input names a concrete blocker and can never be a pass either way,
    # so it outranks the softer "only a partial verification happened" outcome.
    if blocked_reasons:
        status = BLOCKED
    elif reasons:
        status = PARTIAL if gate_status in (
            "CHECK_ONLY_PASS", "CHECK_ONLY_WITH_ADVISORIES", PARTIAL
        ) else FAILED
    else:
        status = CERTIFIED

    return {
        "status": status,
        "satisfies_full_certification": status in CERTIFYING_STATUSES,
        "reasons": reasons + blocked_reasons,
        "gate_status": gate_status,
        "authorizes_promotion": False,
        "authorizes_live_trading": False,
    }


def dirty_watched() -> list[str]:
    """Watched paths modified relative to HEAD - a record describes a commit."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--", *EVIDENCE_PATHS],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def committed_record(path: Path) -> dict[str, Any] | None:
    """The record this run replaces, read from HEAD rather than from the working tree.

    The supersession anchor has to be the *commit's* record: reading the local file would
    let a second run of this certifier see its own previous attempt, and the supersession
    would quietly disappear the moment the tool ran twice - exactly the kind of silent
    history loss this block exists to prevent.
    """
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - the record always lives in the repository
        return None
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=False)
    if out.returncode != 0:
        return None
    try:
        document = json.loads(out.stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def build_record(
    *,
    steps: dict[str, dict[str, Any]],
    adversarial_report: dict[str, Any] | None,
    integrity: dict[str, Any] | None,
    gate_report: dict[str, Any] | None,
    out_path: Path,
    supersession_reason: str | None = None,
) -> dict[str, Any]:
    decision = evaluate(
        gate_report=gate_report,
        contract_tests=steps.get("contract_tests"),
        adversarial=adversarial_report if adversarial_report is not None
        else (steps.get("adversarial") or {}),
        integrity=integrity,
    )
    digests = {rel: content_digest(rel) for rel in EVIDENCE_PATHS}
    fingerprint = hashlib.sha256(
        json.dumps(
            {"head": git_value("rev-parse", "HEAD"), "digests": digests},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    dirty = dirty_watched()
    advisories: list[str] = []
    if dirty:
        advisories.append(
            "the watched paths were not clean when this record was produced, so it describes a "
            "working tree as much as a commit: " + ", ".join(dirty[:6])
        )
    gate_advisories = list((gate_report or {}).get("advisories") or [])
    advisories.extend(f"gate advisory: {item}" for item in gate_advisories)

    # WP-8D: this record fingerprints an artefact another work package regenerated, so it is
    # re-issued. A re-issue that dropped the previous identity would be indistinguishable
    # from a certification that always said the new thing.
    previous = committed_record(out_path)
    previous_supersession = (previous or {}).get("supersession") if isinstance(previous, dict) else None
    supersession: dict[str, Any] | None = None
    if isinstance(previous_supersession, dict):
        # the committed record already names what it replaced and this run reproduced the same
        # identity: the trail is carried forward, so re-running the tool cannot erase it
        supersession = {
            **previous_supersession,
            "reproduced": True,
            "note": "this run reproduced the same identity, so the supersession recorded here still "
                    "stands; re-running the certifier may not erase it",
        }
    if isinstance(previous, dict) and previous.get("evidence_fingerprint") not in (None, fingerprint):
        supersession = {
            "previous_fingerprint": previous["evidence_fingerprint"],
            "previous_candidate_head": (previous.get("candidate") or {}).get("head"),
            "previous_status": previous.get("status"),
            "previous_evidence_digests_sha256": hashlib.sha256(
                json.dumps(previous.get("evidence_digests"), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "reason": supersession_reason or (
                "the fingerprinted evidence changed, so this record is re-issued; the previous "
                "record's identity is preserved here instead of being overwritten silently"
            ),
            "how": "the record file is replaced, but the previous fingerprint, candidate head and a "
                   "digest of its evidence table are kept here, so a reader can see that the "
                   "certification was re-issued and what it replaced",
            "superseded_chain": previous_supersession,
        }
    return {
        "artifact": "COST_BARRIER_CERTIFICATION",
        "work_package": "WP-7F certification gate for the cost-barrier lane",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate": {
            "head": git_value("rev-parse", "HEAD"),
            "branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_watched_paths": dirty,
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "executable": sys.executable,
            },
        },
        "requirements": {
            "1_contracts_and_tests": steps.get("contract_tests", {}).get("passed"),
            "2_input_integrity": (integrity or {}).get("status"),
            "3_full_reproduction": (gate_report or {}).get("status"),
            "4_independent_verification": {
                "attested": (gate_report or {}).get("status") == "FULL_REPRODUCTION_PASS",
                "checks_failed": (gate_report or {}).get("checks_failed"),
                "controls_missed": (gate_report or {}).get("controls_missed"),
                "false_success": ((gate_report or {}).get("claims") or {}).get("false_success"),
            },
            "5_adversarial_controls": {
                "status": (adversarial_report or {}).get("status"),
                "substrate_present": (
                    (adversarial_report or {}).get("substrate") or {}
                ).get("present"),
                "attacks_total": (adversarial_report or {}).get("attacks_total"),
                "attacks_evaded": (adversarial_report or {}).get("attacks_evaded"),
                "legs_failed": (adversarial_report or {}).get("legs_failed"),
            },
            "6_identifiable_evidence": fingerprint,
            "7_no_hidden_errors": not decision["reasons"],
        },
        "steps": steps,
        "decision": decision,
        "status": decision["status"],
        "exit_code": EXIT_CODES[decision["status"]],
        "evidence_digests": digests,
        "evidence_digest_convention": (
            "sha256 over the artefact's content with line endings normalised to LF: a checkout "
            "rewrites line endings without touching content, so the same commit must fingerprint "
            "the same on a runner as on the machine that produced the record"
        ),
        "evidence_fingerprint": fingerprint,
        "supersession": supersession,
        "adversarial_summary": {
            "status": (adversarial_report or {}).get("status"),
            "substrate_present": (
                (adversarial_report or {}).get("substrate") or {}
            ).get("present"),
            "attacks_total": (adversarial_report or {}).get("attacks_total"),
            "attacks_detected": (adversarial_report or {}).get("attacks_detected"),
            "attacks_evaded": (adversarial_report or {}).get("attacks_evaded"),
            "escapes": [
                row.get("attack_id") for row in (adversarial_report or {}).get("escapes") or []
            ],
        },
        "advisories": advisories,
        "claims": {
            "promotion_claimed": False,
            "rentable_claimed": False,
            "certified_claimed": False,
            "production_ready_claimed": False,
            "authorization_state": "NOT_AUTHORIZED",
            "trades_authorized": 0,
            "false_success": 0,
        },
        "scope": (
            "certification that the published cost-barrier artefacts reproduce from their declared "
            "inputs on this candidate, and that the gate detects the tampering in the adversarial "
            "contract. It is not a claim of profitability, and it authorizes nothing: no promotion, "
            "no paper or live execution, no capital, no order path"
        ),
        "record_path": str(out_path),
    }


def render(record: dict[str, Any]) -> str:
    decision = record["decision"]
    lines = [
        f"cost-barrier certification: {record['status']} (exit {record['exit_code']})",
        f"  candidate {record['candidate']['head'][:12]} "
        f"({record['candidate']['branch']}), dirty watched paths "
        f"{len(record['candidate']['dirty_watched_paths'])}",
        f"  full certification satisfied: {decision['satisfies_full_certification']}",
        f"  gate status {decision['gate_status']}  ·  evidence {record['evidence_fingerprint'][:16]}",
    ]
    for name, row in record["steps"].items():
        lines.append(f"  [{'PASS' if row.get('passed') else 'FAIL'}] {name} - {row['command']}")
    for reason in decision["reasons"]:
        lines.append(f"  REFUSED: {reason}")
    for advisory in record["advisories"]:
        lines.append(f"  advisory: {advisory}")
    return "\n".join(lines)


def read_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        document = read_json(path)
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=CERTIFICATION, help="where to write the record")
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    parser.add_argument("--workdir", default=None,
                        help="keep the intermediate reports here instead of a temporary directory")
    parser.add_argument("--supersedes-reason", default=None,
                        help="why this record replaces the one committed at HEAD, if it does")
    args = parser.parse_args(argv)

    temporary = args.workdir is None
    workdir = Path(tempfile.mkdtemp(prefix="cost_barrier_certify_")) if temporary \
        else Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    steps: dict[str, dict[str, Any]] = {}
    steps["contract_tests"] = run_step(
        "contract tests",
        [sys.executable, "-m", "pytest", "-q", *LANE_TESTS],
    )
    steps["materialize_inputs"] = run_step(
        "materialize the declared inputs",
        [sys.executable, str(ROOT / EVIDENCE), "--materialize"],
    )

    integrity_path = workdir / "integrity.json"
    steps["input_integrity"] = run_step(
        "input integrity (evidence bundle)",
        [sys.executable, str(ROOT / EVIDENCE), "--report", str(integrity_path)],
    )
    integrity = read_report(integrity_path)
    if integrity is None:
        integrity = {
            "status": "BLOCKED_MISSING_INPUT"
            if steps["input_integrity"].get("exit_code") == 3
            else "INTEGRITY_FAILURE",
            "failures": ["the evidence tool produced no readable report"],
        }

    gate_report_path = workdir / "gate_report.json"
    steps["full_reproduction"] = run_step(
        "full reproduction",
        [sys.executable, str(ROOT / GATE), "--json", "--report", str(gate_report_path)],
    )
    gate_report = read_report(gate_report_path)

    adversarial_path = workdir / "adversarial.json"
    steps["adversarial"] = run_step(
        "adversarial suite",
        [sys.executable, str(ROOT / ADVERSARIAL), "--out", str(adversarial_path)],
    )
    adversarial_report = read_report(adversarial_path)

    record = build_record(
        steps=steps,
        adversarial_report=adversarial_report,
        integrity=integrity,
        gate_report=gate_report,
        out_path=Path(args.out),
        supersession_reason=args.supersedes_reason,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": the record's bytes are part of the evidence chain, not of this host.
    Path(args.out).write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(render(record))
    if args.json:
        print(json.dumps(record, indent=2))
    if temporary:
        shutil.rmtree(workdir, ignore_errors=True)
    return int(record["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
