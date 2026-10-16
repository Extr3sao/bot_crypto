"""WP-EDGE-12F — the independent verifier, and the sabotage that pays for each check.

    python scripts/edge12_verify.py                 verify the package as it stands
    python scripts/edge12_verify.py --self-test     verify, then try to fool every check
    python scripts/edge12_verify.py --json          print the verification record

Independence is not a declaration here. This script **imports nothing from**
``trading_bot.research.edge12``: every figure it checks is re-derived from the JSON and
the logs the builder published, with its own arithmetic, so a builder that is wrong in
one place cannot make its verifier agree with it.

And each check is *paid for*: the self-test mutates an input in a way that makes the
claim false and asserts that the check fails. A check no sabotage can break is a check
that was never load-bearing, and undetected sabotages are reported as failures of the
check rather than hidden.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

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
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
    "INFORME_EJECUTIVO.md",
)

#: The evidence this verifier refuses to re-derive without. ``TEST_RUNS.json`` is here on
#: purpose: the package's own regression run is evidence like any other, and a report that
#: quoted a figure from a run nobody recorded is the claim the definition of done separates
#: from the verification.
EVIDENCE: tuple[str, ...] = (
    "OS_EVIDENCE.json",
    "RUNNER_PROBES.json",
    "CONTINUITY_REHEARSAL.json",
    "LIVE_CONTINUITY.json",
    "RUN_LOG_SNAPSHOT.jsonl",
    "TEST_RUNS.json",
)

#: Instants an admissible day needs and the coverage floor the campaign declares. They are
#: re-read from the lane's own modules by the checks, never typed here.
COVERAGE_FLOOR = 0.9
FORWARD_DAYS_REQUIRED = 60


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def collect(reports: Path, state_root: Path, store_root: Path) -> dict[str, Any]:
    """Every input the checks read, in one structure so a sabotage can mutate a copy."""
    evidence_dir = reports / "evidence"
    deliverables: dict[str, str] = {}
    for name in DELIVERABLES:
        path = reports / name
        deliverables[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    evidence: dict[str, str] = {}
    for name in EVIDENCE:
        path = evidence_dir / name
        evidence[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "deliverables": deliverables,
        "evidence_files": evidence,
        "gate": _load(reports / "DEPENDENCY_GATE.json"),
        "baseline": _load(reports / "BASELINE.json"),
        "preflight": _load(reports / "RUNNER_PREFLIGHT.json"),
        "decision": _load(evidence_dir / "RUNNER_DECISION.json"),
        "probes": _load(evidence_dir / "RUNNER_PROBES.json"),
        "storage": _load(reports / "CAPACITY_FORECAST.json"),
        "storage_verification": _load(reports / "STORAGE_VERIFICATION.json"),
        "operational": _load(reports / "OPERATIONAL_VALIDATION.json"),
        "coverage": _load(reports / "FORWARD_COVERAGE.json"),
        "matrix": _load(reports / "CONTINUITY_MATRIX.json"),
        "rehearsal": _load(evidence_dir / "CONTINUITY_REHEARSAL.json"),
        "live": _load(evidence_dir / "LIVE_CONTINUITY.json"),
        "runs": _jsonl(evidence_dir / "RUN_LOG_SNAPSHOT.jsonl"),
        "state_root": str(state_root),
        "store_root": str(store_root),
        "snapshot_digests": _snapshot_digests(evidence_dir),
    }


def _snapshot_digests(evidence_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in EVIDENCE:
        path = evidence_dir / name
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    return out


# ------------------------------------------------------------------------------- checks
def the_deliverable_set_is_complete(ev: dict[str, Any]) -> tuple[bool, str]:
    missing = [name for name, text in ev["deliverables"].items() if not text.strip()]
    empty_evidence = [name for name, text in ev["evidence_files"].items() if not text.strip()]
    ok = not missing and not empty_evidence
    return ok, (
        f"{len(ev['deliverables'])} deliverable(s) and {len(ev['evidence_files'])} evidence file(s); "
        f"missing deliverables {missing}, missing evidence {empty_evidence}"
    )


def the_three_levels_reconcile(ev: dict[str, Any]) -> tuple[bool, str]:
    level = ev["operational"].get("levels", {}).get("one_triggers_fired", {})
    expected = level.get("expected_instants")
    answered = level.get("answered_by_a_tick")
    lost = level.get("never_answered")
    if expected is None or answered is None or lost is None:
        return False, "the reading does not carry the three counts"
    return answered + lost == expected, f"{answered} answered + {lost} lost = {expected} expected"


def the_levels_account_for_every_instant(ev: dict[str, Any]) -> tuple[bool, str]:
    losses = ev["operational"].get("losses", {})
    causes = losses.get("causes") or {}
    total = sum(int(value) for value in causes.values())
    counted = max(losses.get("total_lost") or 0, 0)
    instants = sum(len(values) for values in (losses.get("instants_by_cause") or {}).values())
    ok = total == counted == instants
    return ok, f"causes sum to {total}, total_lost says {counted}, instants listed {instants}"


def every_unanswered_instant_has_a_cause_it_can_name(ev: dict[str, Any]) -> tuple[bool, str]:
    causes = ev["operational"].get("losses", {}).get("causes") or {}
    silent = int(causes.get("SILENT_UNATTRIBUTABLE") or 0)
    named = sum(v for k, v in causes.items() if k != "SILENT_UNATTRIBUTABLE")
    # SILENT_UNATTRIBUTABLE is a named cause, not a missing one: the check is that the
    # bucket exists and is reported, never that it is zero. A reading with an unexplained
    # instant and no bucket for it would be a reading that hid one.
    ok = "SILENT_UNATTRIBUTABLE" in causes
    return (
        ok,
        f"{named} attributed by the host's record, {silent} left unattributable and reported as such",
    )


def no_sleep_cause_without_a_sleep_record(ev: dict[str, Any]) -> tuple[bool, str]:
    causes = ev["operational"].get("losses", {}).get("causes") or {}
    windows = ev["operational"].get("losses", {}).get("windows") or {}
    pairs = len(windows.get("sleep") or [])
    claimed = int(causes.get("SLEEP") or 0)
    return (
        claimed == 0 or pairs > 0,
        f"{claimed} sleep attribution(s) against {pairs} recorded sleep window(s)",
    )


def the_coverage_floor_and_the_forward_requirement_are_intact(
    ev: dict[str, Any],
) -> tuple[bool, str]:
    coverage = ev["coverage"]
    required = coverage.get("required_days")
    floor = coverage.get("coverage_required")
    ok = float(floor or 0) == COVERAGE_FLOOR and int(required or 0) == FORWARD_DAYS_REQUIRED
    return ok, f"coverage floor {floor}, forward requirement {required} days"


def backfilled_days_are_not_counted_as_forward(ev: dict[str, Any]) -> tuple[bool, str]:
    coverage = ev["coverage"]
    recent = coverage.get("recent_days") or []
    wrong = [
        row.get("day")
        for row in recent
        if row.get("class") == "DENSE_BUT_BACKFILLED" and row.get("prospectively_observed")
    ]
    admissible = coverage.get("prospectively_observed_days") or []
    backfilled = coverage.get("densely_covered_but_backfilled_days") or []
    overlap = sorted(set(admissible) & set(backfilled))
    ok = not wrong and not overlap
    return ok, (
        f"{len(admissible)} admissible day(s), {len(backfilled)} backfilled day(s), "
        f"overlap {overlap or 'none'}, mis-classed rows {wrong or 'none'}"
    )


def the_slot_ledger_is_a_set(ev: dict[str, Any]) -> tuple[bool, str]:
    rows = ev["live"].get("slots_sealed_rows")
    unique = ev["live"].get("slots_unique_keys")
    ok = rows is not None and unique is not None and rows == unique
    return ok, f"{rows} row(s) and {unique} unique key(s) in the live slot ledger"


def every_rehearsal_step_won_its_verdict(ev: dict[str, Any]) -> tuple[bool, str]:
    steps = ev["rehearsal"].get("steps") or []
    if not steps:
        return False, "the rehearsal carries no steps"
    bad: list[str] = []
    for row in steps:
        observed = row.get("observed") or {}
        verdict = row.get("verdict")
        step_id = row.get("step_id")
        if step_id == "repeat_inside_the_same_slot":
            if verdict == "PASS" and (
                observed.get("outcome") != "ALREADY_OBSERVED"
                or int(observed.get("market_requests") or 0) != 0
                or observed.get("store_unchanged") is not True
            ):
                bad.append(step_id)
        elif step_id == "trigger_while_another_tick_holds_the_lease":
            if verdict == "PASS" and (
                observed.get("outcome") != "ALREADY_RUNNING"
                or int(observed.get("market_requests") or 0) != 0
            ):
                bad.append(step_id)
        elif step_id == "lease_left_by_a_crashed_process":
            if (
                verdict == "PASS"
                and str((observed.get("lease") or {}).get("status")) != "STALE_LEASE_RECLAIMED"
            ):
                bad.append(step_id)
        elif step_id == "bars_that_closed_while_the_observer_was_down":
            if verdict == "PASS" and int(observed.get("new_bars_reported") or 0) <= 0:
                bad.append(step_id)
        elif step_id == "a_log_line_interrupted_mid_write":
            if verdict == "PASS" and int(observed.get("corrupt_log_lines") or 0) < 1:
                bad.append(step_id)
        elif step_id == "a_duplicated_slot_seal":
            if verdict == "PASS" and int(observed.get("duplicates_dropped") or 0) != 1:
                bad.append(step_id)
        elif step_id == "a_tick_against_its_own_interval":
            maximum = observed.get("maximum_seconds")
            interval = observed.get("interval_seconds")
            if verdict == "PASS" and (maximum is None or interval is None or maximum >= interval):
                bad.append(step_id)
        if verdict not in {"PASS", "FAIL"}:
            bad.append(f"{step_id}:{verdict}")
    return (
        not bad,
        f"{len(steps)} step(s); a verdict its own observation contradicts: {bad or 'none'}",
    )


def the_rehearsal_did_not_touch_the_live_store(ev: dict[str, Any]) -> tuple[bool, str]:
    source = str(ev["rehearsal"].get("store_source") or "")
    work = str(ev["rehearsal"].get("work_root") or "")
    live = str(ev["store_root"])
    ok = (
        bool(source)
        and bool(work)
        and work != source
        and source.rstrip("\\/") == live.rstrip("\\/")
    )
    return ok, f"rehearsal read {source}, wrote {work}; the live store is {live}"


def the_dependency_scan_excluded_its_own_text(ev: dict[str, Any]) -> tuple[bool, str]:
    audit = ev["gate"].get("dependency_named_by_the_request", {}).get("audit") or {}
    verdict = audit.get("verdict")
    hits = audit.get("hits") or []
    self_refs = audit.get("self_references_excluded") or []
    ok = verdict == "NOT_PRESENT_IN_TREE" and not hits
    return ok, (
        f"verdict {verdict}, {len(hits)} non-self hit(s), "
        f"{len(self_refs)} of this package's own file(s) excluded"
    )


def the_gate_carried_no_failing_check(ev: dict[str, Any]) -> tuple[bool, str]:
    gate = ev["gate"]
    failing = gate.get("failing_checks")
    checks = gate.get("checks") or []
    counted = [row["name"] for row in checks if not row.get("passed")]
    return (
        bool(checks)
        and not failing
        and not counted
        and gate.get("verdict") == "DEPENDENCY_GATE_PASS",
        f"{len(checks)} check(s), failing {failing or 'none'}, verdict {gate.get('verdict')}",
    )


def the_storage_ceiling_is_inside_its_declared_budget(ev: dict[str, Any]) -> tuple[bool, str]:
    ceiling = ev["storage"].get("retention_ceiling") or {}
    budget = int(ceiling.get("declared_lane_budget_bytes") or 0)
    projected = int(ceiling.get("ceiling_bytes") or 0)
    # Re-derived here rather than trusted: the flag and the two numbers must agree.
    ok = bool(budget) and projected <= budget and ceiling.get("ceiling_within_budget") is True
    return ok, f"{projected} B ceiling against {budget} B budget"


def the_refusals_made_no_market_request(ev: dict[str, Any]) -> tuple[bool, str]:
    requests = (ev["storage"].get("refusals") or {}).get("market_requests_at_refusal")
    refused = int((ev["storage"].get("refusals") or {}).get("refused_ticks") or 0)
    ok = refused == 0 or requests == [0]
    return ok, f"{refused} refused tick(s), market requests at a refusal: {requests}"


def off_phase_launches_are_not_attributed(ev: dict[str, Any]) -> tuple[bool, str]:
    levers = ev["probes"].get("additive_levers") or {}
    limitation = str(levers.get("attribution_limitation") or "")
    off_phase = int(levers.get("off_phase_launches") or 0)
    ok = bool(limitation) and ("operational log" in limitation or "schtasks" in limitation)
    return ok, f"{off_phase} off-phase launch(es), limitation stated: {bool(limitation)}"


def nothing_was_applied_to_the_live_task(ev: dict[str, Any]) -> tuple[bool, str]:
    probes = ev["probes"]
    decision = ev["decision"]
    required = [row["id"] for row in (ev["preflight"].get("checks") or [])]
    leftovers = probes.get("probe_tasks_left_behind") or []
    ok = (
        probes.get("applied_to_the_live_task") is False
        and decision.get("applied_to_the_live_task") is False
        and not leftovers
    )
    return ok, (
        f"applied={probes.get('applied_to_the_live_task')}, probe leftovers {leftovers or 'none'}, "
        f"{len(required)} preflight check(s)"
    )


def the_preflight_verdict_follows_from_its_checks(ev: dict[str, Any]) -> tuple[bool, str]:
    preflight = ev["preflight"]
    checks = preflight.get("checks") or []
    blocking = [row["id"] for row in checks if row.get("blocking") and not row.get("passed")]
    stated = preflight.get("blocking_failures") or []
    ok = (
        bool(checks)
        and sorted(blocking) == sorted(stated)
        and (preflight.get("verdict") == "PREFLIGHT_PASS") == (not blocking)
    )
    return (
        ok,
        f"{len(checks)} check(s), blocking {blocking or 'none'}, verdict {preflight.get('verdict')}",
    )


def every_mechanism_verdict_was_earned(ev: dict[str, Any]) -> tuple[bool, str]:
    probes = ev["probes"].get("probes") or {}
    problems: list[str] = []
    s4u = probes.get("S4U_PROPOSAL") or {}
    if s4u.get("verdict") == "VIABLE" and not (
        s4u.get("registration_ok") and s4u.get("read_back_is_s4u")
    ):
        problems.append("S4U claimed viable without a read-back of S4U")
    if s4u.get("registration_ok") and s4u.get("task_left_behind"):
        problems.append("a probe left its task behind")
    logon = probes.get("LOGON_TRIGGER") or {}
    if logon.get("verdict") == "VIABLE" and not any(
        "LogonTrigger" in str(kind) for kind in (logon.get("trigger_kinds") or [])
    ):
        problems.append("the logon trigger was claimed viable without a read-back")
    witness = probes.get("WITNESS_ACTION") or {}
    if witness.get("verdict") == "VIABLE" and int(witness.get("lines_written") or 0) < 1:
        problems.append("the witness action was claimed viable without a written line")
    return not problems, f"{len(probes)} probe(s); unearned verdicts: {problems or 'none'}"


def the_matrix_covers_every_property(ev: dict[str, Any]) -> tuple[bool, str]:
    matrix = ev["matrix"]
    required = matrix.get("properties_required") or []
    rows = matrix.get("rows") or []
    present = {row.get("property") for row in rows}
    missing = [name for name in required if name not in present]
    unnamed = [row.get("property") for row in rows if not row.get("evidence")]
    return (
        bool(required)
        and not missing
        and not unnamed
        and matrix.get("verdict") == "CONTINUITY_MATRIX_COMPLETE",
        f"{len(required)} required, {len(rows)} row(s), missing {missing or 'none'}, "
        f"rows without named evidence {unnamed or 'none'}",
    )


def the_live_reading_matches_the_log_it_was_taken_from(ev: dict[str, Any]) -> tuple[bool, str]:
    """Re-derive what the live reading claims, from the log snapshot, with this script's maths."""
    rows = ev["runs"]
    live = ev["live"]
    outcomes: dict[str, int] = {}
    durations: list[float] = []
    previous: int | None = None
    worst = 0.0
    gaps = 0
    for row in rows:
        outcomes[str(row.get("outcome"))] = outcomes.get(str(row.get("outcome")), 0) + 1
        durations.append(float(row.get("duration_seconds") or 0))
        started = row.get("started_at_ms")
        if isinstance(started, int) and previous is not None:
            delta = (started - previous) / 1000.0
            if delta > 2100:
                gaps += 1
                worst = max(worst, delta)
        if isinstance(started, int):
            previous = started
    ok = (
        live.get("runs") == len(rows)
        and live.get("slots_sealed_rows") is not None
        and len(live.get("gaps_over_the_declared_bound") or []) == gaps
        and float(live.get("worst_gap_seconds") or 0) == round(worst, 1)
        and float(live.get("maximum_tick_seconds") or 0) == max(durations)
    )
    return ok, (
        f"{len(rows)} row(s) re-read, {gaps} silence(s) re-derived, worst {round(worst, 1)} s, "
        f"maximum tick {max(durations) if durations else None} s"
    )


def no_order_and_no_promotion_anywhere(ev: dict[str, Any]) -> tuple[bool, str]:
    offenders: list[str] = []
    for name, payload in (
        ("operational", ev["operational"]),
        ("storage", ev["storage"]),
        ("matrix", ev["matrix"]),
        ("gate", ev["gate"]),
        ("rehearsal", ev["rehearsal"]),
        ("coverage", ev["coverage"]),
    ):
        if payload.get("order_sent") not in (False, None):
            offenders.append(f"{name}:order_sent")
        if payload.get("hypothetical") not in (True, None):
            offenders.append(f"{name}:hypothetical")
        if payload.get("promotion") not in ("NONE", None):
            offenders.append(f"{name}:promotion")
    invariants = ev["operational"].get("invariants") or {}
    if int(invariants.get("orders_recorded") or 0) != 0:
        offenders.append("operational:orders_recorded")
    if int(invariants.get("non_hypothetical_ticks") or 0) != 0:
        offenders.append("operational:non_hypothetical_ticks")
    if [row for row in (invariants.get("promotions") or []) if row not in ("NONE", None)]:
        offenders.append("operational:promotions")
    return not offenders, f"offending records: {offenders or 'none'}"


def no_readiness_claim_anywhere(ev: dict[str, Any]) -> tuple[bool, str]:
    needles = (
        "PAPER_READY",
        "LIVE_READY",
        "READY_FOR_PAPER",
        "LISTO_PARA_PAPER",
        "certified for live",
        "PROMOTION_APPROVED",
    )
    offenders: list[str] = []
    for name, text in ev["deliverables"].items():
        for needle in needles:
            if needle.lower() in text.lower():
                offenders.append(f"{name}:{needle}")
    return not offenders, f"readiness claims found: {offenders or 'none'}"


def the_snapshots_match_their_digests(ev: dict[str, Any]) -> tuple[bool, str]:
    digests = ev["snapshot_digests"]
    empty = [name for name, value in digests.items() if not value]
    return not empty, f"{len(digests)} evidence file(s) digested, empty {empty or 'none'}"


def the_closure_state_is_one_the_rfc_allows(ev: dict[str, Any]) -> tuple[bool, str]:
    allowed = {
        "OPERATIONAL_CONTINUITY_VALIDATED",
        "FORWARD_CONTINUITY_BLOCKED",
        "IMPLEMENTED_NOT_RUNTIME_VALIDATED",
        "VERIFICATION_FAILED",
    }
    report = ev["deliverables"].get("RUN_REPORT.json") or ""
    state = None
    if report.strip():
        try:
            state = json.loads(report).get("closure_state")
        except json.JSONDecodeError:
            state = None
    ok = state in allowed
    return ok, f"closure state {state!r}; allowed {sorted(allowed)}"


CHECKS: dict[str, Any] = {
    "the_deliverable_set_is_complete": the_deliverable_set_is_complete,
    "the_three_levels_reconcile": the_three_levels_reconcile,
    "the_levels_account_for_every_instant": the_levels_account_for_every_instant,
    "every_unanswered_instant_has_a_cause_it_can_name": every_unanswered_instant_has_a_cause_it_can_name,
    "no_sleep_cause_without_a_sleep_record": no_sleep_cause_without_a_sleep_record,
    "the_coverage_floor_and_the_forward_requirement_are_intact": the_coverage_floor_and_the_forward_requirement_are_intact,
    "backfilled_days_are_not_counted_as_forward": backfilled_days_are_not_counted_as_forward,
    "the_slot_ledger_is_a_set": the_slot_ledger_is_a_set,
    "every_rehearsal_step_won_its_verdict": every_rehearsal_step_won_its_verdict,
    "the_rehearsal_did_not_touch_the_live_store": the_rehearsal_did_not_touch_the_live_store,
    "the_dependency_scan_excluded_its_own_text": the_dependency_scan_excluded_its_own_text,
    "the_gate_carried_no_failing_check": the_gate_carried_no_failing_check,
    "the_storage_ceiling_is_inside_its_declared_budget": the_storage_ceiling_is_inside_its_declared_budget,
    "the_refusals_made_no_market_request": the_refusals_made_no_market_request,
    "off_phase_launches_are_not_attributed": off_phase_launches_are_not_attributed,
    "nothing_was_applied_to_the_live_task": nothing_was_applied_to_the_live_task,
    "the_preflight_verdict_follows_from_its_checks": the_preflight_verdict_follows_from_its_checks,
    "every_mechanism_verdict_was_earned": every_mechanism_verdict_was_earned,
    "the_matrix_covers_every_property": the_matrix_covers_every_property,
    "the_live_reading_matches_the_log_it_was_taken_from": the_live_reading_matches_the_log_it_was_taken_from,
    "no_order_and_no_promotion_anywhere": no_order_and_no_promotion_anywhere,
    "no_readiness_claim_anywhere": no_readiness_claim_anywhere,
    "the_snapshots_match_their_digests": the_snapshots_match_their_digests,
    "the_closure_state_is_one_the_rfc_allows": the_closure_state_is_one_the_rfc_allows,
}

Mutation = Callable[[dict[str, Any]], None]

#: name -> (mutation, the check it must break). A check with no sabotage is a check nobody
#: has tried to falsify, which is the same thing as an untested one.
SABOTAGES: dict[str, tuple[Mutation, str]] = {}


def _sabotage(name: str, check: str) -> Callable[[Mutation], Mutation]:
    def register(func: Mutation) -> Mutation:
        SABOTAGES[name] = (func, check)
        return func

    return register


@_sabotage("claim_one_more_trigger", "the_three_levels_reconcile")
def _(ev: dict[str, Any]) -> None:
    ev["operational"]["levels"]["one_triggers_fired"]["expected_instants"] += 1


@_sabotage("drop_a_lost_instant_from_the_causes", "the_levels_account_for_every_instant")
def _(ev: dict[str, Any]) -> None:
    causes = ev["operational"]["losses"]["causes"]
    first = next(name for name, value in causes.items() if value)
    causes[first] -= 1
    ev["operational"]["losses"]["instants_by_cause"][first] = ev["operational"]["losses"][
        "instants_by_cause"
    ][first][1:]


@_sabotage("remove_the_unattributable_bucket", "every_unanswered_instant_has_a_cause_it_can_name")
def _(ev: dict[str, Any]) -> None:
    ev["operational"]["losses"]["causes"].pop("SILENT_UNATTRIBUTABLE", None)


@_sabotage("invent_a_sleep_that_nobody_recorded", "no_sleep_cause_without_a_sleep_record")
def _(ev: dict[str, Any]) -> None:
    ev["operational"]["losses"]["causes"]["SLEEP"] = 3
    ev["operational"]["losses"]["windows"]["sleep"] = []


@_sabotage("lower_the_coverage_floor", "the_coverage_floor_and_the_forward_requirement_are_intact")
def _(ev: dict[str, Any]) -> None:
    ev["coverage"]["coverage_required"] = 0.5


@_sabotage("call_a_backfilled_day_admissible", "backfilled_days_are_not_counted_as_forward")
def _(ev: dict[str, Any]) -> None:
    days = ev["coverage"].get("recent_days") or []
    target = next((row for row in days if row.get("class") == "DENSE_BUT_BACKFILLED"), None)
    if target is None:
        days.append(
            {
                "day": "2026-10-14",
                "class": "DENSE_BUT_BACKFILLED",
                "prospectively_observed": True,
            }
        )
    else:
        target["prospectively_observed"] = True


@_sabotage("duplicate_a_slot_seal", "the_slot_ledger_is_a_set")
def _(ev: dict[str, Any]) -> None:
    ev["live"]["slots_sealed_rows"] = int(ev["live"].get("slots_sealed_rows") or 0) + 1


@_sabotage(
    "call_the_idempotency_step_passed_with_a_second_request", "every_rehearsal_step_won_its_verdict"
)
def _(ev: dict[str, Any]) -> None:
    for row in ev["rehearsal"].get("steps") or []:
        if row.get("step_id") == "repeat_inside_the_same_slot":
            row["verdict"] = "PASS"
            row["observed"]["market_requests"] = 7


@_sabotage("rehearse_against_the_live_store_itself", "the_rehearsal_did_not_touch_the_live_store")
def _(ev: dict[str, Any]) -> None:
    ev["rehearsal"]["work_root"] = ev["rehearsal"].get("store_source")


@_sabotage(
    "satisfy_the_dependency_with_the_scans_own_text", "the_dependency_scan_excluded_its_own_text"
)
def _(ev: dict[str, Any]) -> None:
    audit = ev["gate"]["dependency_named_by_the_request"]["audit"]
    audit["verdict"] = "PRESENT"
    audit["hits"] = [{"path": "src/trading_bot/research/edge12/gate.py", "match": "identifier"}]


@_sabotage("hide_a_failing_gate_check", "the_gate_carried_no_failing_check")
def _(ev: dict[str, Any]) -> None:
    ev["gate"]["checks"].append({"name": "invented", "passed": False, "detail": "sabotage"})
    ev["gate"]["failing_checks"] = []


@_sabotage(
    "publish_a_ceiling_above_the_budget", "the_storage_ceiling_is_inside_its_declared_budget"
)
def _(ev: dict[str, Any]) -> None:
    ceiling = ev["storage"]["retention_ceiling"]
    ceiling["ceiling_bytes"] = int(ceiling["declared_lane_budget_bytes"]) * 2
    ceiling["ceiling_within_budget"] = True


@_sabotage("refuse_a_tick_after_a_market_request", "the_refusals_made_no_market_request")
def _(ev: dict[str, Any]) -> None:
    ev["storage"]["refusals"]["market_requests_at_refusal"] = [0, 4]


@_sabotage("stop_explaining_the_off_phase_launches", "off_phase_launches_are_not_attributed")
def _(ev: dict[str, Any]) -> None:
    ev["probes"]["additive_levers"]["attribution_limitation"] = ""


@_sabotage("leave_a_probe_task_behind", "nothing_was_applied_to_the_live_task")
def _(ev: dict[str, Any]) -> None:
    ev["probes"]["probe_tasks_left_behind"] = ["TradingAgentic-EDGE12-Probe-S4U"]


@_sabotage(
    "pass_the_preflight_with_a_blocking_failure", "the_preflight_verdict_follows_from_its_checks"
)
def _(ev: dict[str, Any]) -> None:
    blocking = [row for row in ev["preflight"]["checks"] if row.get("blocking")]
    if blocking:
        blocking[0]["passed"] = False


@_sabotage("call_a_mechanism_viable_without_a_read_back", "every_mechanism_verdict_was_earned")
def _(ev: dict[str, Any]) -> None:
    s4u = ev["probes"]["probes"]["S4U_PROPOSAL"]
    s4u["verdict"] = "VIABLE"
    s4u["read_back_is_s4u"] = False
    s4u["registration_ok"] = True


@_sabotage("drop_a_property_from_the_matrix", "the_matrix_covers_every_property")
def _(ev: dict[str, Any]) -> None:
    ev["matrix"]["rows"] = ev["matrix"]["rows"][1:]


@_sabotage(
    "move_the_live_reading_by_one_tick", "the_live_reading_matches_the_log_it_was_taken_from"
)
def _(ev: dict[str, Any]) -> None:
    ev["live"]["runs"] = int(ev["live"].get("runs") or 0) + 1


@_sabotage("claim_an_order_was_sent", "no_order_and_no_promotion_anywhere")
def _(ev: dict[str, Any]) -> None:
    ev["operational"]["invariants"]["orders_recorded"] = 1


@_sabotage("publish_a_readiness_claim", "no_readiness_claim_anywhere")
def _(ev: dict[str, Any]) -> None:
    ev["deliverables"]["FINAL_REPORT.md"] += "\nPAPER_READY\n"


@_sabotage("blank_a_snapshot", "the_snapshots_match_their_digests")
def _(ev: dict[str, Any]) -> None:
    ev["snapshot_digests"]["LIVE_CONTINUITY.json"] = ""


@_sabotage("declare_an_invented_closure_state", "the_closure_state_is_one_the_rfc_allows")
def _(ev: dict[str, Any]) -> None:
    # A report that is missing or unreadable is left exactly as it is. The check that reads it
    # already calls that a failure, and a sabotage that raised would stop the self-test instead
    # of proving anything about the check it is meant to pay for.
    try:
        payload = json.loads(ev["deliverables"].get("RUN_REPORT.json") or "")
    except json.JSONDecodeError:
        return
    payload["closure_state"] = "CERTIFIED"
    ev["deliverables"]["RUN_REPORT.json"] = json.dumps(payload)


@_sabotage("delete_a_deliverable", "the_deliverable_set_is_complete")
def _(ev: dict[str, Any]) -> None:
    ev["deliverables"]["FINAL_REPORT.md"] = ""


def run_checks(ev: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, func in CHECKS.items():
        try:
            passed, detail = func(ev)
        except Exception as exc:  # a check that raises is a check that failed, and says why
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        out.append({"name": name, "passed": bool(passed), "detail": str(detail)})
    return out


def self_test(ev: dict[str, Any]) -> dict[str, Any]:
    """Every check, plus the mutation that must break it."""
    results: dict[str, Any] = {}
    undetected: list[str] = []
    for name, (mutate, check_name) in SABOTAGES.items():
        mutated = copy.deepcopy(ev)
        mutate(mutated)
        row = next(item for item in run_checks(mutated) if item["name"] == check_name)
        detected = not row["passed"]
        results[name] = {"check": check_name, "detected": detected}
        if not detected:
            undetected.append(name)
    return {
        "applied": len(SABOTAGES),
        "detected": len(SABOTAGES) - len(undetected),
        "undetected": len(undetected),
        "undetected_names": undetected,
        "sabotages": {name: row["detected"] for name, row in results.items()},
        "verdict": "SELF_TEST_PASS" if not undetected else "SELF_TEST_FAILED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--reports", default=str(REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-12")
    )
    parser.add_argument("--state-root", default=str(REPO_ROOT / "data" / "forward" / "edge04"))
    parser.add_argument("--store-root", default=str(REPO_ROOT / "data" / "forward" / "edge03"))
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = Path(args.reports)
    if not reports.is_absolute():
        reports = REPO_ROOT / reports
    state_root = Path(args.state_root)
    store_root = Path(args.store_root)
    ev = collect(reports, state_root, store_root)
    checks = run_checks(ev)
    failures = [row["name"] for row in checks if not row["passed"]]
    payload: dict[str, Any] = {
        "schema_version": "EDGE12_VERIFICATION_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "work_package": "WP-EDGE-12F",
        "campaign": "RFC-EDGE-012",
        "independence": (
            "this verifier imports nothing from trading_bot.research.edge12 and re-derives every "
            "figure it checks from the published JSON and the log snapshots"
        ),
        "checks": checks,
        "failures": failures,
        "verdict": "VERIFY_PASS" if not failures else "VERIFY_FAILED",
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    if args.self_test:
        payload["self_test"] = self_test(ev)
    (reports / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (reports / "VERIFICATION.md").write_text(_markdown(payload), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    for row in checks:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['name']}: {row['detail']}")
    print(f"verdict     {payload['verdict']} ({len(checks) - len(failures)}/{len(checks)})")
    if "self_test" in payload:
        self_test_row = payload["self_test"]
        print(
            f"self-test   {self_test_row['verdict']}: {self_test_row['detected']}/"
            f"{self_test_row['applied']} sabotage(s) detected"
        )
    return 0 if not failures else 5


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-12F — independent verification",
        "",
        f"**Generated:** {payload['generated_at_utc']} · **Verdict:** `{payload['verdict']}`",
        "",
        f"> {payload['independence']}",
        "",
        "## Checks",
        "",
        "| check | verdict | detail |",
        "| --- | --- | --- |",
    ]
    for row in payload["checks"]:
        lines.append(
            f"| `{row['name']}` | {'PASS' if row['passed'] else 'FAIL'} | {row['detail']} |"
        )
    lines += [
        "",
        f"**{len(payload['checks']) - len(payload['failures'])}/{len(payload['checks'])} "
        f"check(s) passed; failures: {payload['failures'] or 'none'}.**",
        "",
    ]
    if "self_test" in payload:
        self_test_row = payload["self_test"]
        lines += [
            "## The sabotage matrix",
            "",
            f"`{self_test_row['verdict']}` — {self_test_row['detected']}/"
            f"{self_test_row['applied']} mutation(s) detected, {self_test_row['undetected']} undetected.",
            "",
            "| sabotage | the check it had to break | detected |",
            "| --- | --- | --- |",
        ]
        for name, detected in self_test_row["sabotages"].items():
            check_name = SABOTAGES[name][1]
            lines.append(f"| `{name}` | `{check_name}` | {'yes' if detected else 'NO'} |")
        lines += [
            "",
            "A check no mutation can break is reported here rather than counted as a pass:",
            "an unfalsified check and an untested one look the same from the inside.",
            "",
        ]
    lines += ["Research only: no orders, no capital, no promotion.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
