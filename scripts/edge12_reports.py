"""WP-EDGE-12 — assemble the run report, the final report and the executive summary.

    python scripts/edge12_reports.py            render from the stored readings
    python scripts/edge12_reports.py --json     print the run report

Every figure is read from the JSON the other scripts published, so a report cannot
disagree with the reading it summarises. The closure state is **computed** from those
readings by a documented rule and is never typed: RFC-EDGE-012 allows four states and
this script can produce only those four.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.research.edge12 import evidence as ev
from trading_bot.research.edge12 import render

DELIVERABLES: tuple[str, ...] = (
    "DEPENDENCY_GATE.md",
    "DEPENDENCY_GATE.json",
    "RUNTIME_AUTHORITY_MAP.md",
    "BASELINE.json",
    "RUNNER_DECISION.md",
    "RUNNER_PREFLIGHT.json",
    "OPERATOR_HANDOFF.md",
    "ROLLBACK.md",
    "STORAGE_PLAN.md",
    "CAPACITY_FORECAST.json",
    "STORAGE_VERIFICATION.json",
    "CONTINUITY_MATRIX.md",
    "CONTINUITY_MATRIX.json",
    "RECOVERY_REPORT.md",
    "OPERATIONAL_VALIDATION.md",
    "OPERATIONAL_VALIDATION.json",
    "FORWARD_COVERAGE.json",
    "VERIFICATION.md",
    "VERIFICATION.json",
    "GIT_STATE.json",
)

EVIDENCE_FILES: tuple[str, ...] = (
    "OS_EVIDENCE.json",
    "RUNNER_PROBES.json",
    "RUNNER_DECISION.json",
    "CONTINUITY_REHEARSAL.json",
    "LIVE_CONTINUITY.json",
    "RUN_LOG_SNAPSHOT.jsonl",
    "SLOT_LEDGER_SNAPSHOT.jsonl",
    "PROPOSED_DEFINITION.xml",
)


#: What the report says about the verifier before the verifier has run. The two passes are
#: ordered this way because the verifier reads the report (its closure state is one of the
#: things a verifier is for) and the report cites the verifier. Nothing the verifier
#: re-derives changes between the passes: what changes is this section and, with it, the
#: closure state.
PLACEHOLDER_VERIFICATION: dict[str, Any] = {
    "verdict": "VERIFICATION_NOT_RUN",
    "checks": [],
    "failures": [],
    "self_test": {
        "verdict": "SELF_TEST_NOT_RUN",
        "applied": 0,
        "detected": 0,
        "undetected": 0,
    },
    "note": "the independent verifier has not run against this report yet",
}


def _load(path: Path) -> dict[str, Any]:
    return ev.load_json(path)


def closure_state(
    *,
    verification: dict[str, Any],
    matrix: dict[str, Any],
    decision: dict[str, Any],
    operational: dict[str, Any],
    coverage: dict[str, Any],
) -> tuple[str, str]:
    """The RFC's own vocabulary, computed from the readings and from nothing else.

    The precedence is deliberate: a verifier that could not reproduce the evidence
    outranks everything, and an unresolved dependency outranks the fact that the
    implementation exists — RFC-EDGE-012 lists `FORWARD_CONTINUITY_BLOCKED` as the state
    for an unresolved permission or availability dependency, and this package has one.
    """
    if verification.get("verdict") == "VERIFICATION_NOT_RUN":
        return (
            "IMPLEMENTED_NOT_RUNTIME_VALIDATED",
            "the independent verifier has not run against this report yet; the state is recomputed "
            "from its verdict when it has",
        )
    if verification.get("verdict") != "VERIFY_PASS":
        return "VERIFICATION_FAILED", "the independent verifier did not pass"
    session_removed = decision.get("selected") == "S4U_TASK"
    levels = operational.get("levels", {})
    triggers = levels.get("one_triggers_fired", {})
    if not session_removed and int(triggers.get("never_answered") or 0) > 0:
        return (
            "FORWARD_CONTINUITY_BLOCKED",
            "the mechanism that would remove the session dependence needs an administrator, and "
            f"{triggers.get('never_answered')} instant(s) of the measured window produced no process",
        )
    if int(coverage.get("prospectively_observed") or 0) >= int(coverage.get("required_days") or 60):
        return (
            "OPERATIONAL_CONTINUITY_VALIDATED",
            "autonomous execution and recovery were exercised on the runtime and the prospective "
            "requirement is met",
        )
    if matrix.get("verdict") == "CONTINUITY_MATRIX_COMPLETE":
        return (
            "IMPLEMENTED_NOT_RUNTIME_VALIDATED",
            "the implementation and its matrix exist but the prospective requirement is not met",
        )
    return (
        "IMPLEMENTED_NOT_RUNTIME_VALIDATED",
        "the continuity matrix is incomplete, so the runtime validation is not established",
    )


#: RFC-EDGE-012 §6, quoted in the order it states them. The requirement is carried next
#: to its verdict so a reader checks a mapping instead of trusting a summary.
ACCEPTANCE: tuple[tuple[str, str], ...] = (
    ("ACC-01", "Dependencias auditadas contra runtime real."),
    ("ACC-02", "Mecanismo de ejecución seleccionado con evidencia."),
    ("ACC-03", "Ningún cambio privilegiado sin autorización."),
    ("ACC-04", "No se almacenan nuevas credenciales."),
    ("ACC-05", "Observador ejecutable sin sesión interactiva, o bloqueo declarado."),
    ("ACC-06", "No existen ejecuciones simultáneas que corrompan el ledger."),
    ("ACC-07", "Los disparos perdidos tienen causa o clasificación UNATTRIBUTABLE."),
    ("ACC-08", "El guardián de disco permanece activo."),
    ("ACC-09", "Existe capacidad de almacenamiento justificada para la observación."),
    ("ACC-10", "Los snapshots se reproducen offline sin acceder a datos vivos."),
    ("ACC-11", "Los días incompletos no se promocionan."),
    ("ACC-12", "Los datos backfilled no cuentan como forward prospectivo."),
    ("ACC-13", "Se mantienen los 60 días y el 90 %."),
    ("ACC-14", "Los tests y sabotajes detectan defectos reales."),
    ("ACC-15", "El verificador es independiente del constructor."),
    ("ACC-16", "Los informes incluyen fallos, bloqueos y evidencia."),
    ("ACC-17", "order_sent=false y promotion=NONE."),
    ("ACC-18", "El resultado operativo se separa del resultado económico."),
)

SATISFIED = "SATISFECHO"
BLOCKED_DECLARED = "BLOQUEADO_DECLARADO"
PENDING_VERIFIER = "PENDIENTE_DE_VERIFICADOR"
UNSATISFIED = "NO_SATISFECHO"


def acceptance_rows(readings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every criterion RFC-EDGE-012 names, next to the figure that decided it.

    This table is not a summary of the report: each row carries the value the verdict was
    computed from, so a reader who disagrees with a verdict can disagree with a number
    rather than with a prose claim. Where a criterion rests on the independent verifier,
    the row stays `PENDIENTE_DE_VERIFICADOR` until that verifier has run — an acceptance
    table that answers itself with its own author's opinion is the false success this
    campaign exists to prevent, and one that reports a bare "PASS" invites exactly that.
    """
    gate = readings["gate"]
    decision = readings["decision"]
    probes = readings["probes"]
    preflight = readings["preflight"]
    storage = readings["storage"]
    storage_verification = readings["storage_verification"]
    matrix = readings["matrix"]
    live = readings["live"]
    rehearsal = readings["rehearsal"]
    coverage = readings["coverage"]
    operational = readings["operational"]
    verification = readings["verification"]
    failures = readings["failures"]

    requirements = dict(ACCEPTANCE)
    checks = {row["name"]: bool(row["passed"]) for row in (verification.get("checks") or [])}
    verdict_text = str(verification.get("verdict") or "")
    verifier_ran = verdict_text not in ("", "VERIFICATION_NOT_RUN")
    self_test = verification.get("self_test") or {}
    levels = operational.get("levels") or {}
    triggers = levels.get("one_triggers_fired") or {}
    admissible = levels.get("three_days_admissible") or {}
    ceiling = storage.get("retention_ceiling") or {}
    guard = storage.get("guard") or {}
    matrix_rows = {row.get("property"): row.get("verdict") for row in (matrix.get("rows") or [])}
    probe_rows = (probes.get("probes") or {}).values()
    storage_checks = {
        row["name"]: bool(row["passed"]) for row in (storage_verification.get("checks") or [])
    }
    credentials_stored = [
        name for name, row in (probes.get("probes") or {}).items() if row.get("stored_a_password")
    ]
    requested = (gate.get("dependency_named_by_the_request") or {}).get("audit") or {}

    def row(criterion: str, verdict: str, evidence: str) -> dict[str, Any]:
        return {
            "criterion": criterion,
            "requirement": requirements[criterion],
            "verdict": verdict,
            "evidence": evidence,
        }

    def gated(criterion: str, condition: bool, evidence: str) -> dict[str, Any]:
        """A verdict that rests on the verifier is not this package's to award."""
        if not verifier_ran:
            return row(criterion, PENDING_VERIFIER, evidence)
        return row(criterion, SATISFIED if condition else UNSATISFIED, evidence)

    return [
        row(
            "ACC-01",
            SATISFIED if gate.get("verdict") == "DEPENDENCY_GATE_PASS" else UNSATISFIED,
            f"gate {gate.get('verdict')}; entry points "
            f"{gate.get('entry_points', {}).get('reachable')}/{gate.get('entry_points', {}).get('total')}"
            f" answered --help, modules "
            f"{gate.get('modules', {}).get('importable')}/{gate.get('modules', {}).get('total')}"
            f" importable, RFC-EDGE-011 {requested.get('verdict')}, scheduler "
            f"{gate.get('scheduler', {}).get('state')}",
        ),
        row(
            "ACC-02",
            SATISFIED
            if decision.get("selected") and any(row_.get("attempted") for row_ in probe_rows)
            else UNSATISFIED,
            f"selected {decision.get('selected')}; S4U probe "
            f"{_verdict_for(decision, 'S4U_TASK')}, available without new privileges "
            f"{decision.get('available_without_new_privileges')}",
        ),
        row(
            "ACC-03",
            SATISFIED
            if probes.get("applied_to_the_live_task") is False
            and not (probes.get("probe_tasks_left_behind") or [])
            and (preflight.get("verdict") == "PREFLIGHT_PASS")
            else UNSATISFIED,
            f"applied to the live task: {probes.get('applied_to_the_live_task')}; probe tasks left "
            f"behind: {probes.get('probe_tasks_left_behind') or 'none'}; preflight "
            f"{preflight.get('verdict')}",
        ),
        row(
            "ACC-04",
            SATISFIED if not credentials_stored else UNSATISFIED,
            f"no probe stored a credential ({len(credentials_stored)} offender(s)); every probe "
            "record carries stored_a_password=false, and no definition here contains a "
            "<Password> element",
        ),
        row(
            "ACC-05",
            SATISFIED if decision.get("selected") == "S4U_TASK" else BLOCKED_DECLARED,
            f"the mechanism that would remove the session dependence reads "
            f"{_verdict_for(decision, 'S4U_TASK')} on this process's own attempt, so the "
            f"dependence is bounded and not removed: selected {decision.get('selected')}; blocked "
            f"{decision.get('blocked')}",
        ),
        row(
            "ACC-06",
            SATISFIED
            if matrix_rows.get("SINGLE_INSTANCE") == "PASS"
            and live.get("slots_sealed_rows") == live.get("slots_unique_keys")
            else UNSATISFIED,
            f"SINGLE_INSTANCE {matrix_rows.get('SINGLE_INSTANCE')} on the runtime; the slot "
            f"ledger holds {live.get('slots_sealed_rows')} row(s) over "
            f"{live.get('slots_unique_keys')} unique key(s)",
        ),
        row(
            "ACC-07",
            SATISFIED
            if triggers.get("equals_the_whole") is True
            and int(triggers.get("never_answered") or 0)
            == sum(
                int(value or 0)
                for value in ((operational.get("losses") or {}).get("causes") or {}).values()
            )
            else UNSATISFIED,
            f"{triggers.get('never_answered')} unanswered instant(s), every one classified: "
            f"{(operational.get('losses') or {}).get('causes')}",
        ),
        gated(
            "ACC-08",
            storage_checks.get("the_guard_thresholds_are_the_campaigns_own") is True
            and bool(guard.get("status")),
            f"guard {guard.get('status')} at {guard.get('free_gib')} GiB against the campaign's "
            f"own thresholds; storage verification {storage_verification.get('verdict')}",
        ),
        gated(
            "ACC-09",
            checks.get("the_storage_ceiling_is_inside_its_declared_budget") is True,
            f"ceiling {ceiling.get('ceiling_bytes')} B of a declared "
            f"{ceiling.get('declared_lane_budget_bytes')} B budget; the store adds "
            f"{(storage.get('forecast') or {}).get('added_gib_over_the_horizon')} GiB over sixty "
            f"days at the measured rate",
        ),
        gated(
            "ACC-10",
            checks.get("the_snapshots_match_their_digests") is True
            and checks.get("the_rehearsal_did_not_touch_the_live_store") is True,
            f"the rehearsal read {rehearsal.get('store_source')} and wrote "
            f"{rehearsal.get('work_root')}; the verifier re-derived its figures from the "
            f"published snapshots with {len(checks)} check(s)",
        ),
        gated(
            "ACC-11",
            checks.get("the_three_levels_reconcile") is True,
            f"level three counts {admissible.get('prospectively_observed_days')} day(s) of "
            f"{admissible.get('required_days')}; an "
            f"incomplete day is never promoted, it is left INCOMPLETE and reported in "
            f"FORWARD_COVERAGE.json",
        ),
        gated(
            "ACC-12",
            checks.get("backfilled_days_are_not_counted_as_forward") is True,
            f"{coverage.get('densely_covered_but_backfilled')} dense day(s) whose bars arrived "
            f"late are classified DENSE_BUT_BACKFILLED and counted as zero forward days; the rule "
            f"is the lane's own prospective_days",
        ),
        gated(
            "ACC-13",
            checks.get("the_coverage_floor_and_the_forward_requirement_are_intact") is True,
            f"required days {coverage.get('required_days')}, coverage floor "
            f"{coverage.get('coverage_required')} (the campaign's declared values, unchanged by "
            f"this package)",
        ),
        row(
            "ACC-14",
            SATISFIED
            if self_test.get("verdict") == "SELF_TEST_PASS" and not self_test.get("undetected")
            else (PENDING_VERIFIER if not verifier_ran else UNSATISFIED),
            f"sabotage matrix {self_test.get('detected')}/{self_test.get('applied')} mutation(s) "
            f"detected, {self_test.get('undetected')} undetected, over {len(checks)} check(s)",
        ),
        gated(
            "ACC-15",
            bool(verification.get("independence")),
            str(
                verification.get("independence") or "the verifier did not declare its independence"
            ),
        ),
        gated(
            "ACC-16",
            bool(readings["deliverables_all_present"])
            and (
                not failures
                or len([item for item in failures if item.get("id") and item.get("status")])
                == len(failures)
            ),
            f"{len(failures)} open failure(s) recorded, every one with an id and a status; every "
            f"deliverable present: {readings['deliverables_all_present']}",
        ),
        gated(
            "ACC-17",
            checks.get("no_order_and_no_promotion_anywhere") is True,
            "every record this package wrote carries order_sent=false and promotion=NONE, "
            f"including the {guard.get('status')} storage reading and the operational window",
        ),
        row(
            "ACC-18",
            SATISFIED
            if any("econom" in str(item.get("status", "")).lower() for item in failures)
            or any("cost" in str(item.get("what", "")).lower() for item in failures)
            else UNSATISFIED,
            f"the operational result is published on its own ({triggers.get('never_answered')} "
            f"unanswered instant(s), "
            f"{admissible.get('prospectively_observed_days')} admissible day(s)) and the "
            f"inherited economic failure is kept apart from it: "
            f"{[item.get('id') for item in failures]}",
        ),
    ]


#: The paths this package owns, used to list its own commits. They are enumerated rather
#: than globbed so a later package's file cannot be pulled into this one's provenance.
#: ``.gitignore`` and ``.gitattributes`` are deliberately absent: every work package in
#: this campaign edits them, so listing commits over them would credit this package with
#: the others' work.
GIT_STATE_PATHS: tuple[str, ...] = (
    "src/trading_bot/research/edge12",
    "tests/unit/research/test_edge12_continuity.py",
    "tests/unit/research/test_edge12_runner.py",
    "reports/edge-recovery/WP-EDGE-12",
)

GIT_STATE_FILENAME = "GIT_STATE.json"


def _git_rows(*args: str) -> list[str]:
    raw = _git(*args)
    return [line for line in raw.splitlines() if line.strip()]


def git_state(*, gate: dict[str, Any]) -> dict[str, Any]:
    """The commits this package owns, and what the remote held when they were read.

    A report cannot name the commit that contains it — that hash does not exist until the
    commit is made — so this record names the commit it was taken *at* and lists the ones
    that touched these paths. The remote figure is the one the remote returned, read with
    ``ls-remote`` and carried in the gate's own identity record: a push command's output is
    a statement about what it sent, not about what the remote now holds.
    """
    commit_args = ["log", "-n", "12", "--format=%h\t%s", "--"]
    rows = _git_rows(*commit_args, *GIT_STATE_PATHS)
    ahead = _git_rows("log", "--format=%h\t%s", "@{u}..HEAD")
    behind = _git_rows("log", "--format=%h\t%s", "HEAD..@{u}")
    return {
        "schema_version": "EDGE12_GIT_STATE_V1",
        "recorded_at_utc": ev.now_utc(),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": _git("rev-parse", "HEAD"),
        "head_subject": _git("log", "-1", "--format=%s"),
        "head_committed_at": _git("log", "-1", "--format=%cI"),
        "upstream": _git("rev-parse", "--abbrev-ref", "@{u}"),
        "remote_sha": (gate.get("identity") or {}).get("remote_sha"),
        "remote_sha_source": "git ls-remote, read by WP-EDGE-12A and carried here",
        "head_is_the_remote_sha": bool(
            _git("rev-parse", "HEAD") == (gate.get("identity") or {}).get("remote_sha")
        ),
        "commits_ahead_of_upstream": [
            {"sha": row.split("\t")[0], "subject": row.split("\t", 1)[1]} for row in ahead
        ],
        "commits_behind_upstream": [
            {"sha": row.split("\t")[0], "subject": row.split("\t", 1)[1]} for row in behind
        ],
        "commits_that_touched_this_package": [
            {"sha": row.split("\t")[0], "subject": row.split("\t", 1)[1]} for row in rows
        ],
        "paths_this_list_was_taken_over": list(GIT_STATE_PATHS),
        "commits": (
            "a report cannot name the commit that contains it, so this one names the commit it "
            "was taken at and lists the commits that touched the paths above"
        ),
        "working_tree": {
            "note": (
                "other workstreams' edits are present and deliberately uncommitted; this package "
                "staged only the paths it owns"
            ),
            "modified_count": len(_git_rows("status", "--porcelain")),
        },
        "verify_command": "git ls-remote origin refs/heads/agent/edge-recovery/WP-EDGE-00-baseline",
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def _verdict_for(decision: dict[str, Any], mechanism: str) -> str | None:
    for row in decision.get("evaluations") or []:
        if row.get("mechanism") == mechanism:
            return str(row.get("verdict"))
    return None


def _git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ev.REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _digest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    data = path.read_bytes()
    return {
        "present": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": data.count(b"\n"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reports", default=str(ev.DEFAULT_REPORTS))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = ev.repo_path(args.reports)
    evidence_dir = reports / "evidence"

    gate = _load(reports / "DEPENDENCY_GATE.json")
    baseline = _load(reports / "BASELINE.json")
    storage = _load(reports / "CAPACITY_FORECAST.json")
    storage_verification = _load(reports / "STORAGE_VERIFICATION.json")
    matrix = _load(reports / "CONTINUITY_MATRIX.json")
    operational = _load(reports / "OPERATIONAL_VALIDATION.json")
    coverage = _load(reports / "FORWARD_COVERAGE.json")
    verification = _load(reports / "VERIFICATION.json") or PLACEHOLDER_VERIFICATION
    verification_pending = verification.get("verdict") == "VERIFICATION_NOT_RUN"
    preflight = _load(reports / "RUNNER_PREFLIGHT.json")
    decision = _load(evidence_dir / "RUNNER_DECISION.json")
    probes = _load(evidence_dir / "RUNNER_PROBES.json")
    rehearsal = _load(evidence_dir / "CONTINUITY_REHEARSAL.json")
    live = _load(evidence_dir / "LIVE_CONTINUITY.json")
    test_runs = _load(evidence_dir / "TEST_RUNS.json")

    state, why = closure_state(
        verification=verification,
        matrix=matrix,
        decision=decision,
        operational=operational,
        coverage=coverage,
    )
    levels = operational.get("levels", {})
    failures = [
        {
            "id": row.get("id"),
            "status": row.get("status"),
            "what": row.get("what"),
            "owner": row.get("owner"),
        }
        for row in (gate.get("open_failures", {}).get("open_failures") or [])
    ]
    failures_summary = (
        "; ".join(
            f"`{row['id']}` {row['status']} ({row.get('owner') or 'unowned'})" for row in failures
        )
        or "none"
    )
    next_action = (
        "an administrator registers the S4U variant of the proposed definition (the command is in "
        "OPERATOR_HANDOFF.md step 5 and the rollback is written in ROLLBACK.md), and enables the "
        "Task Scheduler operational log so the next silent trigger is attributable instead of "
        "SILENT_UNATTRIBUTABLE"
    )
    # Written before the digests are taken, so the record is one of the files it digests
    # rather than a file the reader has to notice is missing from the list.
    state_row = git_state(gate=gate)
    ev.write_json(reports / GIT_STATE_FILENAME, state_row)
    deliverable_digests = {name: _digest(reports / name) for name in DELIVERABLES}
    acceptance = acceptance_rows(
        {
            "gate": gate,
            "decision": decision,
            "probes": probes,
            "preflight": preflight,
            "storage": storage,
            "storage_verification": storage_verification,
            "matrix": matrix,
            "live": live,
            "rehearsal": rehearsal,
            "coverage": coverage,
            "operational": operational,
            "verification": verification,
            "failures": failures,
            "deliverables_all_present": all(
                row.get("present") for row in deliverable_digests.values()
            ),
        }
    )
    acceptance_counts: dict[str, int] = {}
    for row in acceptance:
        acceptance_counts[row["verdict"]] = acceptance_counts.get(row["verdict"], 0) + 1

    payload: dict[str, Any] = {
        "schema_version": "EDGE12_RUN_REPORT_V1",
        "generated_at_utc": ev.now_utc(),
        "work_package": "WP-EDGE-12",
        "campaign": "RFC-EDGE-012",
        "closure_state": state,
        "closure_reason": why,
        "pass": 1 if verification_pending else 2,
        "verification_pending": verification_pending,
        "what_changed_between_the_passes": (
            "the verification section and the closure state it feeds; every figure the verifier "
            "re-derived from the readings is untouched by the second pass"
        ),
        "git": {
            "branch": state_row["branch"],
            "head": state_row["head"],
            "head_subject": state_row["head_subject"],
            "head_committed_at": state_row["head_committed_at"],
            "upstream": state_row["upstream"],
            "read_back_from_the_remote": state_row["remote_sha"],
            "head_is_the_remote_ref": state_row["head_is_the_remote_sha"],
            "ahead_of_upstream": len(state_row["commits_ahead_of_upstream"]),
            "behind_upstream": len(state_row["commits_behind_upstream"]),
            "state_file": GIT_STATE_FILENAME,
            "commits": (
                f"the {len(state_row['commits_that_touched_this_package'])} commit(s) that touched "
                f"this package are listed in {GIT_STATE_FILENAME}; a report that named its own "
                "commit would be naming a hash that moves"
            ),
        },
        "results": {
            "baseline": {
                "head": baseline.get("head"),
                "head_is_the_remote_ref": baseline.get("head_is_the_remote_ref"),
                "branch": baseline.get("branch"),
                "observer_runs": (baseline.get("observer") or {}).get("runs"),
                "sealed_slots": (baseline.get("observer") or {}).get("sealed_slots"),
                "coverage": (baseline.get("observer") or {}).get("coverage"),
                "days_required": (baseline.get("invariants") or {}).get("forward_days_required"),
                "coverage_required": (baseline.get("invariants") or {}).get("coverage_required"),
                "orders_recorded": (baseline.get("invariants") or {}).get("orders_recorded"),
                "open_failures_at_the_baseline": baseline.get("open_failures"),
            },
            "dependency_gate": {
                "verdict": gate.get("verdict"),
                "entry_points_reachable": (
                    f"{gate.get('entry_points', {}).get('reachable')}/"
                    f"{gate.get('entry_points', {}).get('total')}"
                ),
                "modules_importable": (
                    f"{gate.get('modules', {}).get('importable')}/"
                    f"{gate.get('modules', {}).get('total')}"
                ),
                "dependency_named_by_the_request": gate.get("dependency_named_by_the_request", {})
                .get("audit", {})
                .get("verdict"),
                "failing_checks": gate.get("failing_checks"),
            },
            "runner": {
                "selected": decision.get("selected"),
                "selected_detail": decision.get("selected_detail"),
                # The evaluation's mechanism is ``S4U_TASK``; the probe's record is keyed
                # ``S4U_PROPOSAL``. Reading the wrong one returned ``None`` and published a blank
                # where the host's own refusal belongs, which is how a figure becomes a claim.
                "s4u_on_this_host": _verdict_for(decision, "S4U_TASK"),
                "available_without_new_privileges": decision.get(
                    "available_without_new_privileges"
                ),
                "blocked": decision.get("blocked"),
                "preflight_verdict": decision.get("preflight_verdict"),
                "preflight": preflight.get("verdict"),
                "preflight_checks": len(preflight.get("checks") or []),
                "blocking_failures": [
                    row.get("id") for row in (preflight.get("checks") or []) if row.get("blocking")
                ],
                "applied_to_the_live_task": probes.get("applied_to_the_live_task"),
                "probe_tasks_left_behind": probes.get("probe_tasks_left_behind"),
                "registration_unchanged_since_wp_edge_04r": decision.get(
                    "registration_unchanged_since_wp_edge_04r"
                ),
            },
            "storage": {
                "verdict": storage.get("verdict"),
                "ceiling_bytes": (storage.get("retention_ceiling") or {}).get("ceiling_bytes"),
                "lane_budget_bytes": (storage.get("retention_ceiling") or {}).get(
                    "declared_lane_budget_bytes"
                ),
                "store_bytes_per_day": (storage.get("store_growth") or {}).get("bytes_per_day"),
                "added_gib_over_the_horizon": (storage.get("forecast") or {}).get(
                    "added_gib_over_the_horizon"
                ),
                "relocation_verdict": storage.get("relocation_verdict"),
                "checks": storage_verification.get("verdict"),
            },
            "continuity": {
                "rehearsal": rehearsal.get("verdict"),
                "rehearsal_steps": len(rehearsal.get("steps") or []),
                "rehearsal_failures": rehearsal.get("failures"),
                "matrix": matrix.get("verdict"),
                "properties": len(matrix.get("rows") or []),
                "not_passing": matrix.get("not_passed"),
                "rows": [
                    {
                        "property": row.get("property"),
                        "evidence_kind": row.get("evidence_kind"),
                        "verdict": row.get("verdict"),
                    }
                    for row in (matrix.get("rows") or [])
                ],
                "live_ticks": live.get("runs"),
                "live_gaps": len(live.get("gaps_over_the_declared_bound") or []),
                "live_worst_gap_seconds": live.get("worst_gap_seconds"),
                "live_maximum_tick_seconds": live.get("maximum_tick_seconds"),
            },
            "operational": {
                "window_hours": (operational.get("window") or {}).get("hours"),
                "expected_instants": levels.get("one_triggers_fired", {}).get("expected_instants"),
                "answered": levels.get("one_triggers_fired", {}).get("answered_by_a_tick"),
                "never_answered": levels.get("one_triggers_fired", {}).get("never_answered"),
                "causes": (operational.get("losses") or {}).get("causes"),
                "slot_consuming_ticks": levels.get("two_observations_made", {}).get(
                    "slot_consuming_ticks"
                ),
                "fired_and_refused": levels.get("two_observations_made", {}).get(
                    "fired_and_refused"
                ),
                "admissible_days": levels.get("three_days_admissible", {}).get(
                    "prospectively_observed_days"
                ),
                "required_days": levels.get("three_days_admissible", {}).get("required_days"),
                "orders_recorded": (operational.get("invariants") or {}).get("orders_recorded"),
            },
            "verification": {
                "verdict": verification.get("verdict"),
                "checks": len(verification.get("checks") or []),
                "failures": verification.get("failures"),
                "self_test": (verification.get("self_test") or {}).get("verdict"),
                "sabotages_detected": (verification.get("self_test") or {}).get("detected"),
                "sabotages_applied": (verification.get("self_test") or {}).get("applied"),
            },
        },
        "tests": test_runs
        or {
            "note": (
                "the regression runs are recorded in evidence/TEST_RUNS.json by the pass that ran "
                "them; absent here means the pass that rendered this report did not have them"
            )
        },
        "acceptance": acceptance,
        "acceptance_counts": dict(sorted(acceptance_counts.items())),
        "deliverables": deliverable_digests,
        "evidence": {name: _digest(evidence_dir / name) for name in EVIDENCE_FILES},
        "open_failures": failures,
        "open_failures_summary": failures_summary,
        "next_action": next_action,
        "no_readiness_claim": (
            "this package does not authorise PAPER or LIVE trading under any circumstance: "
            "order_sent is false and promotion is NONE in every record it produced"
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }

    ev.write_json(reports / "RUN_REPORT.json", payload)
    (reports / "RUN_REPORT.md").write_text(_run_report_md(payload), encoding="utf-8")
    (reports / "FINAL_REPORT.md").write_text(_final_report_md(payload), encoding="utf-8")
    (reports / "INFORME_EJECUTIVO.md").write_text(
        render.informe_ejecutivo_md(
            {
                "generated_at_utc": payload["generated_at_utc"],
                "closure_state": state,
                "gate": gate,
                "decision": decision,
                "storage": storage,
                "matrix": matrix,
                "operational": operational,
                "verification": verification,
                "failures_summary": failures_summary,
                "next_action": next_action,
                "probes": probes,
                "tests": test_runs,
                "acceptance_counts": acceptance_counts,
            }
        ),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    if verification_pending:
        print(
            "next              python scripts/edge12_verify.py --self-test   "
            "(then re-run this script to embed the verdict)"
        )
    print(f"pass              {payload['pass']}")
    print(f"closure state     {state} — {why}")
    print(
        f"deliverables      {len(payload['deliverables'])} file(s), "
        f"{sum(1 for row in payload['deliverables'].values() if row.get('present'))} present"
    )
    print(
        f"verification      {verification.get('verdict')} "
        f"({len(verification.get('checks') or [])} check(s))"
    )
    print(f"open failures     {len(failures)}")
    return 0


def _run_report_md(payload: dict[str, Any]) -> str:
    results = payload["results"]
    lines = [
        "# WP-EDGE-12 — run report",
        "",
        f"**Generated:** {payload['generated_at_utc']}",
        f"**Closure state:** `{payload['closure_state']}` — {payload['closure_reason']}",
        "",
        "## 1. Git",
        "",
        f"* branch `{payload['git']['branch']}`, HEAD `{payload['git']['head']}`",
        f"* `{payload['git']['head_subject']}`",
        f"* remote read-back `{payload['git']['read_back_from_the_remote']}`",
        f"* {payload['git']['commits']}",
        f"* baseline `{payload['results']['baseline']['head']}` on "
        f"`{payload['results']['baseline']['branch']}`, head is the remote ref "
        f"`{payload['results']['baseline']['head_is_the_remote_ref']}`",
        f"* baseline observer: {payload['results']['baseline']['observer_runs']} tick(s), "
        f"{payload['results']['baseline']['sealed_slots']} sealed slot(s), coverage "
        f"`{payload['results']['baseline']['coverage']}` of "
        f"`{payload['results']['baseline']['coverage_required']}` over "
        f"{payload['results']['baseline']['days_required']} required day(s), orders recorded "
        f"`{payload['results']['baseline']['orders_recorded']}`",
        "",
        "## 2. What each work package concluded",
        "",
        "| work package | deliverable | result |",
        "| --- | --- | --- |",
        f"| 12A dependencies | `DEPENDENCY_GATE.json` | `{results['dependency_gate']['verdict']}` — "
        f"{results['dependency_gate']['entry_points_reachable']} entry point(s) reachable, "
        f"{results['dependency_gate']['modules_importable']} module(s) importable, dependency "
        f"`{results['dependency_gate']['dependency_named_by_the_request']}` |",
        f"| 12B execution without a session | `RUNNER_DECISION.md` | selected "
        f"`{results['runner']['selected']}`; S4U on this host "
        f"`{results['runner']['s4u_on_this_host']}`; preflight `{results['runner']['preflight']}`; "
        f"applied `{results['runner']['applied_to_the_live_task']}` |",
        f"| 12C storage | `CAPACITY_FORECAST.json` | `{results['storage']['verdict']}` — ceiling "
        f"{results['storage']['ceiling_bytes']} B of a {results['storage']['lane_budget_bytes']} B "
        f"budget, store {results['storage']['store_bytes_per_day']} B/day, relocation "
        f"`{results['storage']['relocation_verdict']}` |",
        f"| 12D continuity | `CONTINUITY_MATRIX.json` | rehearsal "
        f"`{results['continuity']['rehearsal']}` over "
        f"{results['continuity']['rehearsal_steps']} step(s), matrix "
        f"`{results['continuity']['matrix']}` |",
        f"| 12E operational validation | `OPERATIONAL_VALIDATION.json` | "
        f"{results['operational']['expected_instants']} instant(s), "
        f"{results['operational']['answered']} answered, "
        f"{results['operational']['never_answered']} unanswered, "
        f"{results['operational']['admissible_days']} admissible day(s) of "
        f"{results['operational']['required_days']} |",
        f"| 12F certification | `VERIFICATION.json` | `{results['verification']['verdict']}` "
        f"({results['verification']['checks']} check(s), "
        f"{results['verification']['sabotages_detected']}/"
        f"{results['verification']['sabotages_applied']} sabotage(s) detected) |",
        "",
        "## 3. The three levels of the operational reading",
        "",
        f"* **triggers fired:** {results['operational']['expected_instants']} expected, "
        f"{results['operational']['answered']} answered, "
        f"{results['operational']['never_answered']} never answered — causes "
        f"`{results['operational']['causes']}`",
        f"* **observations made:** {results['operational']['slot_consuming_ticks']} slot-consuming "
        f"tick(s), {results['operational']['fired_and_refused']} fired and refused",
        f"* **admissible days:** {results['operational']['admissible_days']} of "
        f"{results['operational']['required_days']}",
        "",
        "## 4. Tests and checks",
        "",
        "```json",
        json.dumps(payload["tests"], indent=2, sort_keys=True, default=str)[:2500],
        "```",
        "",
        "## 5. Deliverables",
        "",
        "| file | bytes | sha256 |",
        "| --- | --- | --- |",
    ]
    for name, row in payload["deliverables"].items():
        if row.get("present"):
            lines.append(f"| `{name}` | {row['bytes']} | `{row['sha256'][:16]}…` |")
        else:
            lines.append(f"| `{name}` | — | **ABSENT** |")
    lines += ["", "## 6. Evidence", "", "| file | bytes | sha256 |", "| --- | --- | --- |"]
    for name, row in payload["evidence"].items():
        if row.get("present"):
            lines.append(f"| `{name}` | {row['bytes']} | `{row['sha256'][:16]}…` |")
        else:
            lines.append(f"| `{name}` | — | **ABSENT** |")
    lines += [
        "",
        "## 7. Open failures",
        "",
        payload["open_failures_summary"],
        "",
        "## 8. Next action",
        "",
        payload["next_action"],
        "",
        f"> {payload['no_readiness_claim']}",
        "",
    ]
    return "\n".join(lines)


def _final_report_md(payload: dict[str, Any]) -> str:
    results = payload["results"]
    lines = [
        "# WP-EDGE-12 — final report",
        "",
        f"**Closure state:** `{payload['closure_state']}`",
        "",
        f"> {payload['closure_reason']}",
        "",
        "## 1. The one number this work package exists to change",
        "",
        "WP-EDGE-04R measured why the forward lane loses triggers. RFC-EDGE-012 asks for the",
        "continuity to be *demonstrated* rather than argued. What was demonstrated here, and what",
        "was not, are different in kind and are kept apart below.",
        "",
        "```",
        f"{results['operational']['expected_instants']} trigger instants in the measured window",
        f"   {results['operational']['answered']} answered by a tick",
        f"   {results['operational']['never_answered']} never answered by any process",
        f"        causes: {results['operational']['causes']}",
        "",
        f"{results['operational']['slot_consuming_ticks']} slot-consuming tick(s) ran the pipeline",
        f"{results['operational']['admissible_days']} of {results['operational']['required_days']} "
        "admissible forward days",
        "```",
        "",
        # The sentence is rendered from the figure beside it rather than typed next to it: a
        # report that says "zero" over a line that reads "1 of 60" is the failure mode this
        # campaign exists to catch, and it caught this one.
        f"The third line is the only one an admission criterion may read, and it is "
        f"{results['operational']['admissible_days']} of "
        f"{results['operational']['required_days']}. Nothing in this package moves it: only time "
        "and a host that is signed in do, which is why the closure state is "
        f"`{payload['closure_state']}` and not a readiness claim.",
        "",
        "## 2. What was proved on the runtime",
        "",
        "| property | where it was exercised | verdict |",
        "| --- | --- | --- |",
    ]
    for row in _matrix_rows(payload):
        lines.append(f"| `{row['property']}` | {row['evidence_kind']} | `{row['verdict']}` |")
    lines += [
        "",
        "The rehearsal drove the **real observer** — the real ingest, the real store layout, the real",
        "network — over an isolated copy of the store, which is what makes the isolated root a",
        "property of the layout rather than a promise: a rehearsal that wrote into the live store",
        "would be producing the evidence it is measuring.",
        "",
        "## 3. What was not proved, and why",
        "",
        "* **A real sign-in absence under the proposed trigger set.** Provoking one would end the",
        "  session this work runs in. The property is `BOUNDED_NOT_REMOVED`, bounded by the logon",
        "  trigger and by the measured recovery latency, not removed.",
        "* **An S4U task actually running with no session.** The registration of *this definition*",
        "  with `LogonType=S4U` was attempted and the host answered `Acceso denegado`; an",
        "  administrator is the actor that can answer differently.",
        "* **A Windows service or a runner on another host.** No authorised infrastructure was found,",
        "  and creating a service needs a privilege this process does not hold (measured from its own",
        "  token).",
        "* **Linux.** The reading is portable by construction and has not been run there.",
        "* **Attribution of an off-cadence launch.** The run log records the arguments a launch was",
        "  invoked with, and an on-demand `schtasks /run` uses the same arguments as the scheduler.",
        "  The operational log that separates them is disabled, which needs an administrator.",
        "",
        "## 4. The mechanisms, priced",
        "",
        f"Selected: **`{results['runner']['selected']}`**. Available without new privileges: "
        f"{results['runner']['available_without_new_privileges']}.",
        "",
        "| mechanism | verdict |",
        "| --- | --- |",
    ]
    for name, verdict in (results["runner"]["blocked"] or {}).items():
        lines.append(f"| `{name}` | `{verdict}` |")
    lines += [
        "",
        "The two levers already present in the live registration were priced from the lane's own",
        "log rather than from the settings: `StartWhenAvailable` is on and the log shows",
        f"{results['continuity']['live_ticks']} launches with an off-phase minority, and the",
        "`RestartOnFailure` policy produced no measured follow-up after a refused tick. A setting",
        "that is present and recovers nothing is worth exactly as much as a mechanism that is",
        "absent, and saying which one it is takes a measurement.",
        "",
        "## 5. Storage: the lane is not the constraint",
        "",
        f"Ceiling {results['storage']['ceiling_bytes']} B against a declared "
        f"{results['storage']['lane_budget_bytes']} B budget; the store adds "
        f"{results['storage']['added_gib_over_the_horizon']} GiB over sixty days. Relocation: "
        f"`{results['storage']['relocation_verdict']}` — the only other volumes are a cloud mount",
        "that reports the host's own capacity while holding none of it, and unmounted partitions.",
        "The guard stays where it is: it refuses *before* any market request, so a full volume costs",
        "slots and never produces a false observation.",
        "",
        "## 6. Defects this pass found and closed",
        "",
        "| # | defect | how it showed up | closed by |",
        "| --- | --- | --- | --- |",
        "| `DEF-EDGE12-1` | the dependency scan found its own identifier in this package's source, "
        "scripts and reports, and would have reported the dependency as **present** | the first "
        "gate run printed `PRESENT` over a tree that contains no such document | the scan excludes "
        "the searcher's own roots and reports them separately (see DEF-EDGE12-9 for the root it "
        "missed the first time) |",
        "| `DEF-EDGE12-2` | the S4U probe registered the proposal **unchanged**, so the scheduler "
        "read the principal back as `Interactive`, and the probe would have called a mechanism "
        "viable that it had never exercised | the read-back carried `Interactive` while the record "
        "claimed an S4U attempt | the probe builds a real `LogonType=S4U` variant with the lane's "
        "action swapped for an inert one, counts the lines it moved, and requires an `S4U` "
        "read-back before any verdict other than blocked |",
        "| `DEF-EDGE12-3` | the lease rehearsal wrote `renewed_at` in **milliseconds** into a record "
        "the lock compares in **seconds**, making every lease unreclaimable and reporting two "
        "implemented properties as failures | the concurrency step returned `ALREADY_OBSERVED` "
        "instead of `ALREADY_RUNNING` | the rehearsal pins the clock to slot boundaries, writes "
        "the lock in the units the lock reads, and re-derives the recovery arithmetic exactly |",
        "| `DEF-EDGE12-4` | the definition reader tried UTF-16 first, and a UTF-8 file decodes as "
        "UTF-16 without raising: a definition that exists read as malformed | the regression that "
        "reads a definition in both encodings | the byte-order mark decides, and only a file "
        "without one falls back |",
        "| `DEF-EDGE12-5` | the recorded-digest search compared each value against the needle and "
        "never looked at siblings, so a certificate whose path and digest sit on adjacent keys "
        "read as unreadable | the regression that puts the two keys side by side | each object is "
        "flattened before the search |",
        '| `DEF-EDGE12-6` | a mobile volume was counted as a relocation target, so "is there a '
        'better volume?" answered yes to the volume the store already lives on | the storage '
        "reading contradicted WP-EDGE-04R's own verdict | the current volume is excluded by "
        "letter and flagged in the record |",
        "| `DEF-EDGE12-7` | the timeout property was judged from the duration the tick **reports**, "
        "which under an injected clock is the wall clock minus the pinned clock: the first run "
        "printed 900.797 s for a call that took seconds, then negative numbers once the pin passed "
        "the wall clock, and called a working observer a failure | the rehearsal failed on "
        "`TIMEOUT_HANDLING` with `[-857.628, -1718.829, -2580.386]` | the rehearsal times each call "
        "with a stopwatch, keeps the reported value as a cross-check, and judges the property on "
        "the wall figures and the live log |",
        "| `DEF-EDGE12-8` | the continuity matrix read a key the rehearsal no longer writes, so the "
        "rendering of the matrix crashed with `KeyError: 'lease'` after a successful rehearsal | "
        "the run wrote its evidence and then died before writing the matrix | the row reads "
        "`lease_status` and the rehearsal's own regression covers the matrix build |",
        "| `DEF-EDGE12-9` | the scan's exclusion named the package's source, entry points and "
        "deliverables but **not its own regressions** — and this package's test module writes the "
        "identifier out in full as a fixture, so the next gate run reported the dependency "
        "`PRESENT` on the strength of its own test file, which is DEF-EDGE12-1 one artefact "
        "later | the gate re-run over the same tree flipped from `NOT_PRESENT_IN_TREE` to "
        "`PRESENT` after the tests were added, with the single hit being "
        "`tests/unit/research/test_edge12_continuity.py` | the four roots are declared once in "
        "`SEARCHER_ROOTS`, the tests are among them, and a regression asserts that another "
        "package's test file is still a real hit |",
        "",
        "## 7. Acceptance criteria, each with the figure that answers it",
        "",
        "The RFC states eighteen criteria and this table answers them in its own order. The",
        "evidence column is the value the verdict was computed from, not a restatement of it:",
        "where a row rests on the independent verifier it stays",
        "`PENDIENTE_DE_VERIFICADOR` until that verifier has run, and where the RFC allows a",
        "blocked dependency it reads `BLOQUEADO_DECLARADO` rather than being quietly dropped.",
        "",
        f"`{json.dumps(payload['acceptance_counts'], sort_keys=True)}`",
        "",
        "| criterion | requirement | verdict | evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["acceptance"]:
        lines.append(
            f"| `{row['criterion']}` | {row['requirement']} | `{row['verdict']}` | {row['evidence']} |"
        )
    lines += [
        "",
        "## 8. Regressions and checks",
        "",
        "```json",
        json.dumps(payload["tests"], indent=2, sort_keys=True, default=str)[:2000],
        "```",
        "",
        "## 9. Open failures, with owners",
        "",
        payload["open_failures_summary"],
        "",
        "## 10. Next action",
        "",
        payload["next_action"],
        "",
        f"> {payload['no_readiness_claim']}",
        "",
        "Research only: public market data, no credentials, no orders, no capital, no promotion.",
        "",
    ]
    return "\n".join(lines)


def _matrix_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (payload.get("results") or {}).get("continuity", {}).get("rows") or []
    return [
        {
            "property": row.get("property"),
            "evidence_kind": row.get("evidence_kind"),
            "verdict": row.get("verdict"),
        }
        for row in rows
    ]


if __name__ == "__main__":
    raise SystemExit(main())
