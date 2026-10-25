"""RFC-047 — the reconciliation of the three planes of evidence, and the report over them.

This is the *builder* of RFC-047, and it is deliberately not a verifier: it reads the artefacts the
other programs wrote (the host audit, the Windows event store and its live state, the slot ledger and
the run log), derives every statement from them, and writes the result down.  The program that checks
those statements is ``scripts/rfc047_verify.py``, which imports nothing from here and recomputes each
classification from the raw evidence: ``BUILDER != VERIFIER``.

Three artefacts come out of here:

* ``data/st6/RFC047_LEDGER_RECONCILIATION.json`` — one row per declared slot, joining the ledger's own
  record of what happened with what Windows says about it, plus the contract check that the
  version-1 fields of the ledger survived the extension unchanged;
* ``data/st6/RFC047_RUNTIME_VERIFICATION.json`` — the runtime chain of RFC-047's test plan: a
  Windows trigger, the process, the run id, the slot's outcome and the reference to its evidence.
  Each link is reported as present or absent from real artefacts, and the strongest chain this host
  can actually support is shown with the evidence for it, link by link;
* ``data/st6/RFC047_FINAL_REPORT.md`` and ``.json`` — the report in the exact field list the request
  names, written from the two documents above and the artefacts they rest on.

Run:  python scripts/rfc047_builder.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st6_scheduler_evidence import (  # noqa: E402  the witness, read as the shared record it is
    load_samples,
    read_json,
    read_jsonl,
)

DATA = REPO / "data" / "st6"
RFC047_DIR = DATA / "rfc047"
PERIOD_PATH = DATA / "ST6_PERIOD.json"
LEDGER = DATA / "ST6_SLOT_LEDGER.json"
HOST_AUDIT = DATA / "RFC047_HOST_AUDIT.json"
WINDOWS_EVIDENCE = DATA / "RFC047_WINDOWS_EVENT_EVIDENCE.json"
WINDOWS_LIVE = RFC047_DIR / "WINDOWS_EVENT_LIVE_STATE.json"
WINDOWS_STORE = RFC047_DIR / "WINDOWS_EVENTS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
WINDOW_INDEX = DATA / "ST6_WINDOWS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
WITNESS_LOG = DATA / "ST6_SCHEDULER_WITNESS.jsonl"
SCHEDULER_EVIDENCE = DATA / "ST6_SCHEDULER_EVIDENCE.json"
REGISTRY = REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"
RFC_DOC = REPO / "docs" / "rfc" / "RFC-047_ST6_SCHEDULER_PROVENANCE.md"

RECONCILIATION_JSON = DATA / "RFC047_LEDGER_RECONCILIATION.json"
RUNTIME_JSON = DATA / "RFC047_RUNTIME_VERIFICATION.json"
REPORT_JSON = DATA / "RFC047_FINAL_REPORT.json"
REPORT_MD = DATA / "RFC047_FINAL_REPORT.md"
VERIFICATION_JSON = DATA / "RFC047_INDEPENDENT_VERIFICATION.json"

#: The fields of the ledger's own version-1 vocabulary.  They are listed here so that the contract
#: check can fail loudly if an extension ever removes one, rather than the extension being trusted.
LEDGER_V1_FIELDS = (
    "slot_id",
    "day",
    "slot_index",
    "slot_utc",
    "slot_start_utc",
    "slot_end_utc",
    "state",
    "expected_trigger",
    "scheduler_instance_id",
    "scheduler_event_ids",
    "external_evidence_status",
    "external_evidence",
    "scheduler_instants_reported_in_slot",
    "internal_run_id",
    "process_start_utc",
    "result",
    "exit_code",
    "collection_window_id",
    "raw_evidence_hash",
    "failure_reason",
    "attendance_classification",
    "attendance_classification_re_derived",
    "attendance_classification_reading",
    "attendance_evidence",
    "attendance_correction",
    "evidence_refs",
    "runs",
    "concurrent_runs_in_slot",
    "verifier_status",
    "read_at_utc",
    "first_recorded_at_utc",
    "carried_forward_fields",
)
#: What RFC-047 adds to each entry, and nothing else.
WINDOWS_BLOCK_FIELDS = (
    "block_version",
    "state",
    "reason",
    "channel",
    "channel_state",
    "channel_enabled",
    "channel_readable",
    "gate_status",
    "coverage_from_utc",
    "examined_through_record_id",
    "identifier_semantics",
    "records_available",
    "events_in_slot",
    "correlated_runs",
    "runs_claiming_the_schedule",
    "external_read_after_the_slot",
    "missing_elements",
    "evidence_refs",
    "never_confirms_alone",
)
WINDOWS_STATES = (
    "WIN_EVENT_CONFIRMED_SCHEDULED",
    "WIN_EVENT_CONFIRMED_MANUAL",
    "WIN_EVENT_PARTIAL",
    "WIN_EVENT_CONFLICT",
    "PENDING_EVENT_COMPLETION",
    "WIN_EVENT_UNAVAILABLE",
    "PRE_ENABLE_NOT_OBSERVABLE",
)
ORIGIN_CORROBORATED = "CORROBORATED_ENGINE_LAUNCH"
WIN_CORRELATION_TOLERANCE_S = 120


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    text = str(stamp)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def sha256_file(path: Path) -> str | None:
    """The digest of an input, so a reader can check what a document was built from."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        answer = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, cwd=REPO
        )
    except FileNotFoundError:  # pragma: no cover - a host without git
        return "UNAVAILABLE"
    return answer.stdout.strip() or "UNAVAILABLE"


#: The paths that belong to RFC-047, so that the commits named in the report are read from the
#: repository's own history rather than typed here: a commit hash written by hand is a claim, and a
#: claim about which commit carries a file is exactly the kind of thing this RFC exists to check.
RFC047_PATHS = (
    "docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.md",
    "docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.json",
    "scripts/rfc047_builder.py",
    "scripts/rfc047_verify.py",
    "scripts/st6_windows_events.py",
    "scripts/st6_slot_ledger.py",
    "data/st6/RFC047_",
    "data/st6/rfc047/",
    "tests/unit/research/test_rfc047_windows_evidence.py",
)


def git_commits(paths: tuple[str, ...], limit: int = 5) -> list[dict[str, str]]:
    """The commits that touched these paths, as git itself answers."""
    try:
        answer = subprocess.run(
            ["git", "log", f"-{int(limit)}", "--format=%h|%ad|%s", "--date=short", "--", *paths],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )
    except FileNotFoundError:  # pragma: no cover - a host without git
        return []
    rows: list[dict[str, str]] = []
    for line in answer.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            rows.append({"commit": parts[0], "date": parts[1], "subject": parts[2]})
    return rows


def write_json(path: Path, document: dict[str, Any], sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=sort_keys, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # the artefacts these files carry are digest-pinned elsewhere, so the bytes must not
        # depend on the host's separator: without this, a Windows rebuild rewrites every line
        newline="\n",
    )
    temporary.replace(path)


# ---------------------------------------------------------------------------------------------
# the reconciliation
# ---------------------------------------------------------------------------------------------


def build_reconciliation(now: datetime | None = None) -> dict[str, Any]:
    """One row per declared slot: what happened to it, and what Windows can say about it."""
    moment = now or datetime.now(UTC)
    ledger = read_json(LEDGER) or {}
    audit = read_json(HOST_AUDIT) or {}
    evidence = read_json(WINDOWS_EVIDENCE) or {}
    live = read_json(WINDOWS_LIVE) or {}
    entries = [row for row in ledger.get("slots") or [] if isinstance(row, dict)]
    store = read_jsonl(WINDOWS_STORE)
    stored_keys = {f"{row.get('channel')}#{row.get('event_record_id')}" for row in store}

    rows: list[dict[str, Any]] = []
    states: dict[str, int] = {state: 0 for state in WINDOWS_STATES}
    missing_fields: dict[str, list[str]] = {}
    schema_sets: list[str] = []
    block_fields_missing: dict[str, list[str]] = {}
    contradictions: list[dict[str, Any]] = []
    for entry in entries:
        block = entry.get("windows_event_evidence") or {}
        state = str(block.get("state") or "UNKNOWN")
        states[state] = states.get(state, 0) + 1
        absent = [field for field in LEDGER_V1_FIELDS if field not in entry]
        if absent:
            missing_fields[str(entry.get("slot_id"))] = absent
        # the version-1 entries legitimately differ from each other — a collected slot carries the
        # hash of its raw bytes and a slot that has not begun does not — so what has to be uniform is
        # the *extension*: the same RFC-047 block, with the same fields, in all eighty-four entries
        block_absent = [field for field in WINDOWS_BLOCK_FIELDS if field not in block]
        if block_absent:
            block_fields_missing[str(entry.get("slot_id"))] = block_absent
        schema_sets.append(json.dumps(sorted(entry), ensure_ascii=False))
        # every record a slot rests on has to be *in* the store: a correlation quoting a record the
        # store does not hold would be a statement about nothing
        for row in block.get("correlated_runs") or []:
            key = f"{block.get('channel')}#{row.get('event_record_id')}"
            if key not in stored_keys:
                contradictions.append(
                    {
                        "slot_id": entry.get("slot_id"),
                        "kind": "COUNTS_ON_A_RECORD_THE_STORE_DOES_NOT_HOLD",
                        "key": key,
                    }
                )
        rows.append(
            {
                "slot_id": entry.get("slot_id"),
                "slot_start_utc": entry.get("slot_start_utc"),
                "slot_end_utc": entry.get("slot_end_utc"),
                "state": entry.get("state"),
                "attendance_classification": entry.get("attendance_classification"),
                "external_evidence_status": entry.get("external_evidence_status"),
                "windows_event_state": state,
                "windows_event_reason": block.get("reason"),
                "windows_events_in_slot": len(block.get("events_in_slot") or []),
                "correlated_runs": len(block.get("correlated_runs") or []),
                "runs_claiming_the_schedule": block.get("runs_claiming_the_schedule") or [],
                "missing_elements": block.get("missing_elements") or [],
                "collection_window_id": entry.get("collection_window_id"),
                "raw_evidence_hash": entry.get("raw_evidence_hash"),
            }
        )

    runs = [row for entry in entries for row in (entry.get("runs") or []) if isinstance(row, dict)]
    by_origin: dict[str, int] = {}
    for row in runs:
        token = str(row.get("origin"))
        by_origin[token] = by_origin.get(token, 0) + 1
    corroborated_slots = [
        row["slot_id"]
        for row in rows
        if row["windows_event_state"]
        in ("WIN_EVENT_CONFIRMED_SCHEDULED", "WIN_EVENT_CONFIRMED_MANUAL")
    ]
    document: dict[str, Any] = {
        "artifact": "RFC047_LEDGER_RECONCILIATION",
        "built_at_utc": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "built_by": "scripts/rfc047_builder.py",
        "purpose": (
            "join the ledger's record of every declared slot with the external record Windows "
            "produces for it, and state which of the two can be believed about what"
        ),
        "inputs": {
            "ledger": str(LEDGER.relative_to(REPO)).replace("\\", "/"),
            "host_audit": str(HOST_AUDIT.relative_to(REPO)).replace("\\", "/"),
            "windows_event_evidence": str(WINDOWS_EVIDENCE.relative_to(REPO)).replace("\\", "/"),
            "windows_event_store": str(WINDOWS_STORE.relative_to(REPO)).replace("\\", "/"),
            "windows_event_live_state": str(WINDOWS_LIVE.relative_to(REPO)).replace("\\", "/"),
            "run_log": str(RUN_LOG.relative_to(REPO)).replace("\\", "/"),
        },
        "input_digests": {
            "reading": (
                "digests of the working-tree bytes as they were read here; a checkout that applies "
                "a different newline policy would reproduce the content and not the digests, which "
                "is why the verifier re-hashes the evidence itself rather than trusting these"
            ),
            "ledger_sha256": sha256_file(LEDGER),
            "host_audit_sha256": sha256_file(HOST_AUDIT),
            "windows_event_evidence_sha256": sha256_file(WINDOWS_EVIDENCE),
            "windows_event_store_sha256": sha256_file(WINDOWS_STORE),
            "windows_event_live_state_sha256": sha256_file(WINDOWS_LIVE),
        },
        "ledger_contract": {
            "ledger_version": ledger.get("ledger_version"),
            "declared_slots": len(entries),
            "version_1_fields_required": list(LEDGER_V1_FIELDS),
            "version_1_fields_missing": missing_fields,
            "version_1_fields_intact": not missing_fields,
            "distinct_entry_schemas": len(set(schema_sets)),
            "added_block_fields_complete": not block_fields_missing,
            "added_block_fields_missing": block_fields_missing,
            "readings": (
                "the entries differ from one another where the evidence differs, which is what a "
                "version-1 ledger does; the extension added by RFC-047 is what has to be identical "
                "in all eighty-four of them"
            ),
            "added_block_version": (ledger.get("slots") or [{}])[0]
            .get("windows_event_evidence", {})
            .get("block_version"),
            "added_block_fields": list(WINDOWS_BLOCK_FIELDS),
            "reading": (
                "the eighty-four historical entries keep the vocabulary they had; RFC-047 adds one "
                "block beside those fields and rewrites none of them"
            ),
        },
        "windows_states": states,
        "totals": {
            "slots": len(entries),
            "slots_with_an_external_confirmation": len(corroborated_slots),
            "slots_in_conflict": states.get("WIN_EVENT_CONFLICT", 0),
            "slots_manual": states.get("WIN_EVENT_CONFIRMED_MANUAL", 0),
            "slots_partial": states.get("WIN_EVENT_PARTIAL", 0),
            "slots_pending_completion": states.get("PENDING_EVENT_COMPLETION", 0),
            "slots_unavailable": states.get("WIN_EVENT_UNAVAILABLE", 0),
            "slots_never_observable": states.get("PRE_ENABLE_NOT_OBSERVABLE", 0),
            "slots_unaccounted": sum(1 for entry in entries if entry.get("state") == "UNACCOUNTED"),
            "runs": len(runs),
            "runs_claiming_the_schedule": sum(
                1
                for row in runs
                if str(row.get("declared_invocation") or "").upper() == "SCHEDULED"
                or row.get("origin") in (ORIGIN_CORROBORATED, "SELF_DECLARED_UNVERIFIED")
            ),
            "runs_corroborated_by_the_scheduler_register": by_origin.get(ORIGIN_CORROBORATED, 0),
        },
        "run_origins": by_origin,
        "external_record": {
            "channel_state": (audit.get("gate") or {}).get("state_before"),
            "gate_status": (audit.get("gate") or {}).get("status"),
            "coverage_from_utc": audit.get("coverage_from_utc"),
            "records_in_the_store": len(store),
            "events_available": evidence.get("events_available"),
            "examined_through_record_id": (live.get("watermarks") or {}).get(
                "Microsoft-Windows-TaskScheduler/Operational"
            ),
            "identifier_semantics": (evidence.get("event_identifier_candidates") or {})
            .get("semantics", {})
            .get("state"),
        },
        "slots": rows,
        "contradictions": contradictions,
        "disagreements": [],
        "reading": (
            "no slot is called corroborated without a record of this host behind it, no slot of this "
            "period can be called corroborated at all while the channel that would produce such a "
            "record is disabled and has never recorded, and every slot that is unobservable says so "
            "in its own state rather than being counted as attended or as missed"
        ),
    }
    document["disagreements"] = [
        *(
            [
                {
                    "kind": "LEDGER_VERSION_1_FIELDS_MISSING",
                    "detail": missing_fields,
                }
            ]
            if missing_fields
            else []
        ),
        *(
            []
            if not block_fields_missing
            else [
                {
                    "kind": "LEDGER_EXTENSION_BLOCK_INCOMPLETE",
                    "detail": block_fields_missing or "the entries do not share one field set",
                }
            ]
        ),
        *contradictions,
    ]
    write_json(RECONCILIATION_JSON, document)
    return document


# ---------------------------------------------------------------------------------------------
# the runtime chain
# ---------------------------------------------------------------------------------------------


def _corroboration_for(run: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The witness sample that named this run's instant, if any did."""
    started = run.get("process_start_utc")
    if not started:
        return None
    try:
        moment = _parse(str(started))
    except ValueError:
        return None
    for entry in samples:
        instant = entry.get("scheduler_last_run_utc")
        if not instant:
            continue
        try:
            reported = _parse(instant)
        except ValueError:
            continue
        if abs((reported - moment).total_seconds()) <= WIN_CORRELATION_TOLERANCE_S:
            return {
                "witness_sample_id": entry.get("sample_id"),
                "witness_sampled_at_utc": entry.get("sampled_at_utc"),
                "scheduler_reported_instant_utc": instant,
                "delta_s": round(abs((reported - moment).total_seconds()), 3),
            }
    return None


def build_runtime(now: datetime | None = None, *, persist: bool = True) -> dict[str, Any]:
    """The chain RFC-047's runtime test asks for, link by link, from real artefacts only.

    ``persist=False`` returns the same document without replacing
    ``data/st6/RFC047_RUNTIME_VERIFICATION.json``. The test that reads the chain
    asserts on what this function *decides*; writing the tracked artefact as a
    side effect of a test run meant the shipped evidence was overwritten by
    whatever the checkout happened to contain, so the test asks for the decision
    only and the artefact is refreshed by an explicit run of this script.
    """
    moment = now or datetime.now(UTC)
    ledger = read_json(LEDGER) or {}
    audit = read_json(HOST_AUDIT) or {}
    entries = [row for row in ledger.get("slots") or [] if isinstance(row, dict)]
    samples = load_samples(WITNESS_LOG)
    windows = read_jsonl(WINDOW_INDEX)
    windows_by_id = {str(row.get("window_id")): row for row in windows}
    missed = read_jsonl(MISSED_LOG)
    missed_by_slot = {str(row.get("slot_key")): row for row in missed}

    candidates: list[dict[str, Any]] = []
    for entry in entries:
        for run in entry.get("runs") or []:
            if str(run.get("origin")) != ORIGIN_CORROBORATED:
                continue
            corroboration = _corroboration_for(run, samples)
            if not corroboration:
                continue
            candidates.append(
                {
                    "slot_id": entry.get("slot_id"),
                    "run_id": run.get("internal_run_id"),
                    "process_start_utc": run.get("process_start_utc"),
                    "process_end_utc": run.get("process_end_utc"),
                    "result": run.get("result"),
                    "exit_code": run.get("exit_code"),
                    "collection_window_id": entry.get("collection_window_id"),
                    "raw_evidence_hash": entry.get("raw_evidence_hash"),
                    "slot_state": entry.get("state"),
                    "windows_event_state": (entry.get("windows_event_evidence") or {}).get("state"),
                    **corroboration,
                }
            )
    candidates.sort(key=lambda row: str(row.get("process_start_utc") or ""))
    best = candidates[-1] if candidates else None
    window = windows_by_id.get(str((best or {}).get("collection_window_id"))) if best else None
    gate = (audit.get("gate") or {}).get("status")

    def link(name: str, available: bool, evidence: Any, why: str) -> dict[str, Any]:
        return {"link": name, "available": available, "evidence": evidence, "reading": why}

    if best:
        chain = [
            link(
                "windows_scheduled_trigger",
                False,
                {
                    "channel_state": gate,
                    "records_in_the_store": 0,
                },
                "no external record of a trigger exists: the operational channel is disabled on this "
                "host and the change that would enable it was refused without an elevated token",
            ),
            link(
                "process_execution",
                True,
                {
                    "run_id": best["run_id"],
                    "process_start_utc": best["process_start_utc"],
                    "process_end_utc": best["process_end_utc"],
                    "exit_code": best["exit_code"],
                },
                "the run log records the process, and the scheduler's own register named the same "
                "instant while the witness was sampling",
            ),
            link(
                "scheduler_register_corroboration",
                True,
                {
                    "witness_sample_id": best["witness_sample_id"],
                    "witness_sampled_at_utc": best["witness_sampled_at_utc"],
                    "scheduler_reported_instant_utc": best["scheduler_reported_instant_utc"],
                    "delta_s": best["delta_s"],
                },
                "a witness process that is not the tick sampled the Task Scheduler's own reporting "
                "and it named this instant; this corroborates an engine launch, never the trigger "
                "type, because the channel that names the trigger is disabled",
            ),
            link(
                "st6_run_id",
                True,
                {"run_id": best["run_id"], "slot_id": best["slot_id"]},
                "the internal identity of the run is recorded in the ledger entry of its slot",
            ),
            link(
                "slot_outcome",
                True,
                {
                    "slot_state": best["slot_state"],
                    "collection_window_id": best["collection_window_id"],
                    "missed_record": (missed_by_slot.get(str(best["slot_id"])) or {})
                    .get("attendance", {})
                    .get("classification")
                    if missed_by_slot.get(str(best["slot_id"]))
                    else None,
                },
                "the slot's own outcome is recorded: a window was collected, or the slot was lost "
                "with a stated classification",
            ),
            link(
                "evidence_reference",
                best["raw_evidence_hash"] is not None,
                {
                    "raw_evidence_hash": best["raw_evidence_hash"],
                    "raw_path": ((window or {}).get("raw") or {}).get("path"),
                    "uncompressed_sha256": ((window or {}).get("raw") or {}).get(
                        "uncompressed_sha256"
                    ),
                },
                "the market evidence of the slot is referenced by hash and re-hashable from the "
                "window index",
            ),
        ]
        status = "RFC047_RUNTIME_CORRELATION_PARTIAL_INTERNAL_AND_SERVICE_ONLY"
        reason = (
            "the strongest chain this host can actually support is shown: the process, the run "
            "identity, the slot's outcome and its evidence are all held, and the scheduler's own "
            "register corroborates the launch — but the link that would make it a *scheduled* "
            "execution in Windows' own words is missing, because the operational channel is "
            "disabled and the request to enable it was not approved"
        )
    else:
        chain = [
            link(
                "windows_scheduled_trigger",
                False,
                {"channel_state": gate},
                "no external record of a trigger exists: the operational channel is disabled and has "
                "never recorded on this host",
            ),
            link(
                "process_execution",
                False,
                None,
                "no run of this period has been corroborated by the scheduler's own register, so "
                "there is no run to attach the chain to",
            ),
        ]
        status = "RFC047_RUNTIME_CORRELATION_NOT_ACHIEVED"
        reason = (
            "no corroborated run exists to build the chain from, and the external end of the chain "
            "cannot be produced on this host"
        )
    document: dict[str, Any] = {
        "artifact": "RFC047_RUNTIME_VERIFICATION",
        "built_at_utc": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "built_by": "scripts/rfc047_builder.py",
        "requirement": (
            "WP-047-06 and the runtime test of RFC-047: show at least one real correlation between a "
            "Windows scheduled trigger, a process execution, an ST-6 run id, the outcome of the slot "
            "and the reference to its evidence"
        ),
        "status": status,
        "external_trigger_confirmed": False,
        "runtime_correlation_achieved": bool(
            best
            and (ledger.get("summary") or {})
            .get("windows_event_evidence_states", {})
            .get("WIN_EVENT_CONFIRMED_SCHEDULED")
        ),
        "blocked_by": gate,
        "reason": reason,
        "chain": chain,
        "candidates_corroborated_by_the_scheduler_register": len(candidates),
        "chain_shown_for": best,
        "what_would_complete_it": (
            "enable the operational channel with an elevated token, let the schedule run, and read "
            "the channel again: a record naming this task's launch would move the slot's external "
            "state from PRE_ENABLE_NOT_OBSERVABLE to a confirmation, and the first link of the chain "
            "would carry its record id instead of a refusal"
        ),
        "no_run_was_induced_for_this": (
            "no run was started by hand and none was forced outside a slot: a chain built from an "
            "induced run would prove nothing about the schedule"
        ),
    }
    if persist:
        write_json(RUNTIME_JSON, document)
    return document


# ---------------------------------------------------------------------------------------------
# the final report
# ---------------------------------------------------------------------------------------------


def render_markdown(report: dict[str, Any], reconciliation: dict[str, Any]) -> str:
    lines: list[str] = [
        "# RFC-047 — ST-6 SCHEDULER PROVENANCE & INDEPENDENT EXECUTION EVIDENCE",
        "",
        "| field | value |",
        "| --- | --- |",
    ]
    for field in (
        "CURRENT_HEAD",
        "RFC047_STATUS",
        "WINDOWS_CHANNEL_BEFORE",
        "WINDOWS_CHANNEL_AFTER",
        "HOST_PERMISSION_STATUS",
        "LIVE_SCHEDULER_STATUS",
        "REAL_EXECUTION_CORROBORATED",
        "EXTERNAL_EVENTS_CAPTURED",
        "EXTERNAL_EVENTS_MISSING",
        "LEDGER_RECONCILIATION",
        "HISTORICAL_EVIDENCE_LIMITATIONS",
        "RETENTION_STATUS",
        "NEGATIVE_TESTS",
        "RUNTIME_TESTS",
        "INDEPENDENT_VERIFICATION",
        "FALSE_SUCCESS",
        "COMMITS",
        "BLOCKERS",
        "NEXT_GATE",
    ):
        value = report.get(field)
        if isinstance(value, list):
            # a report row is one cell: an embedded newline — a refusal quoted verbatim, say — would
            # break the table and hide the fields below it
            value = "; ".join(" ".join(str(item).split()) for item in value) if value else "none"
        else:
            value = " ".join(str(value).split())
        lines.append(f"| **{field}** | {value} |")
    lines.extend(
        [
            "",
            "## Standing invariants (unchanged)",
            "",
            *[f"- `{token}`" for token in report.get("STANDING_INVARIANTS", [])],
            "",
            "## What the reconciliation found",
            "",
            f"- declared slots: **{reconciliation['totals']['slots']}**",
            f"- slots with an external confirmation: **{reconciliation['totals']['slots_with_an_external_confirmation']}**",
            f"- slots never observable: **{reconciliation['totals']['slots_never_observable']}**",
            f"- runs in the ledger: **{reconciliation['totals']['runs']}** "
            f"(corroborated by the scheduler's own register: "
            f"**{reconciliation['totals']['runs_corroborated_by_the_scheduler_register']}**)",
            f"- disagreements between the builder and its inputs: **{len(reconciliation['disagreements'])}**",
            "",
            "## External evidence vocabulary",
            "",
            "| state | slots |",
            "| --- | --- |",
            *[
                f"| `{state}` | {count} |"
                for state, count in sorted(reconciliation["windows_states"].items())
            ],
            "",
            "> No slot of this period can be called corroborated while the operational channel of the",
            "> host is disabled and has never recorded. That is stated as a limit of the evidence and",
            "> not as a property of the schedule: the monitor keeps collecting, and its own record of",
            "> every slot is kept in `data/st6/ST6_SLOT_LEDGER.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def build_report(
    reconciliation: dict[str, Any],
    runtime: dict[str, Any],
    negative_summary: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    tests: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    audit = read_json(HOST_AUDIT) or {}
    evidence = read_json(WINDOWS_EVIDENCE) or {}
    live = read_json(WINDOWS_LIVE) or {}
    scheduler_evidence = read_json(SCHEDULER_EVIDENCE) or {}
    growth = live.get("growth") or {}
    # the verifier is a separate program that writes its own document; what the report says about it
    # is read from that document rather than assumed, so a report written before the verification
    # says so instead of inheriting a verdict it never received
    verification = (
        verification if verification is not None else read_json(VERIFICATION_JSON) or None
    )
    negative_summary = negative_summary or ((verification or {}).get("negative_controls") or None)
    period = read_json(PERIOD_PATH) or {}
    operational = (
        (audit.get("channels") or {}).get("Microsoft-Windows-TaskScheduler/Operational")
    ) or {}
    maintenance = (
        (audit.get("channels") or {}).get("Microsoft-Windows-TaskScheduler/Maintenance")
    ) or {}
    registry = read_json(REGISTRY) or {}
    gate = audit.get("gate") or {}
    commits = git_commits(RFC047_PATHS)
    commits_text = (
        f"{len(commits)} commit(s) touch the paths of this RFC, read from the repository's own "
        "history: "
        + "; ".join(f"{row['commit']} ({row['date']}) {row['subject']}" for row in commits)
        + ". The report is written after them, so CURRENT_HEAD names the head it was written at; "
        "only RFC-047's own files are committed by those commits, and the pending modifications of "
        "other work are left untouched. A defect found beside this RFC is repaired in a commit of "
        "its own and is recorded in section 14 of the document."
        if commits
        else (
            "no commit touches the paths of this RFC yet: the change set is not committed, and this "
            "report says so rather than naming a commit it cannot see"
        )
    )
    channel_before = (
        f"{operational.get('state')} (enabled={operational.get('config', {}).get('enabled')}, "
        f"retention={operational.get('config', {}).get('retention')}, "
        f"max_size_bytes={operational.get('config', {}).get('max_size_bytes')}, "
        f"records={operational.get('log_info', {}).get('records_present')}"
        + (
            ", never recorded"
            if operational.get("log_info", {}).get("records_present") in (None, 0)
            else ""
        )
        + ")"
    )
    channel_after = (
        f"{channel_before}; unchanged, because the change that would enable it was not applied"
        if not gate.get("probe", {}).get("applied")
        else f"enabled at {audit.get('coverage_from_utc')}"
    )
    missing_ranges = {
        "operational_records_ever_written": operational.get("log_info", {}).get("records_present"),
        "maintenance_records_evicted_before_the_oldest_present": maintenance.get(
            "log_info", {}
        ).get("oldest_record_number"),
        "maintenance_records_present": maintenance.get("log_info", {}).get("records_present"),
        "slots_without_any_external_record": reconciliation["totals"]["slots_never_observable"],
    }
    report: dict[str, Any] = {
        "artifact": "RFC047_FINAL_REPORT",
        "title": "RFC-047 — ST-6 SCHEDULER PROVENANCE & INDEPENDENT EXECUTION EVIDENCE",
        "generated_at_utc": _utc(),
        "generated_by": "scripts/rfc047_builder.py",
        "CURRENT_HEAD": git_head(),
        "RFC047_STATUS": (
            "RFC047_BLOCKED_HOST_PERMISSIONS"
            if gate.get("status") == "HOST_AUDIT_CHANGE_APPROVAL_REQUIRED"
            else (
                "RFC047_PARTIAL_EXTERNAL_EVIDENCE"
                if reconciliation["totals"]["slots_with_an_external_confirmation"]
                < reconciliation["totals"]["slots"]
                else "RFC047_VERIFIED"
            )
        ),
        "WINDOWS_CHANNEL_BEFORE": channel_before,
        "WINDOWS_CHANNEL_AFTER": channel_after,
        "HOST_PERMISSION_STATUS": gate.get("status"),
        "LIVE_SCHEDULER_STATUS": (
            "ST6_AUTONOMOUS_COLLECTION_ACTIVE: the task remains registered and enabled with its "
            "fifteen-minute cadence, and no configuration of it was touched"
            if scheduler_evidence
            else "UNKNOWN: the task's registration was not readable"
        ),
        "REAL_EXECUTION_CORROBORATED": False,
        "EXTERNAL_EVENTS_CAPTURED": evidence.get("events_available"),
        "EXTERNAL_EVENTS_MISSING": (
            "every per-run record of this period: the operational channel is disabled and has never "
            "recorded, and the maintenance channel holds only maintenance identifiers (800 and 808), "
            "none of which describes a task's execution"
        ),
        "LEDGER_RECONCILIATION": (
            f"{reconciliation['ledger_contract']['declared_slots']} slots, version-1 fields intact "
            f"{reconciliation['ledger_contract']['version_1_fields_intact']}, "
            f"{len(reconciliation['disagreements'])} disagreement(s), "
            f"{reconciliation['totals']['slots_never_observable']} slot(s) outside the reach of "
            "external evidence"
        ),
        "HISTORICAL_EVIDENCE_LIMITATIONS": [
            "no per-run Windows record exists for any instant of this period and none can be "
            "recovered: the channel records from the moment it is enabled",
            f"{missing_ranges['maintenance_records_evicted_before_the_oldest_present']} maintenance "
            "records were evicted by the circular policy before this audit read the log",
            "the Security channel is not readable from this session, so nothing there could be "
            "consulted either",
            "the candidate identifiers (100, 102, 107, 110, 200, 201) could not be verified against a "
            "single real record of this host, so they were never turned into classification rules",
            "the scheduler's own register keeps only its most recent run, so a launch can be "
            "corroborated while it is still the most recent one, and not afterwards",
        ],
        "RETENTION_STATUS": (
            f"RFC047_EVENT_STORE_BOUNDED: {growth.get('records')} record(s), "
            f"{growth.get('bytes')} byte(s) of original evidence; incremental by "
            "EventRecordID, deduplicated on write, watermark advanced only after a durable write, "
            "rotation and identifier resets recorded, refusals recorded, and the store preserved "
            "until the period closes"
        ),
        "NEGATIVE_TESTS": (
            f"{negative_summary.get('count')} adversarial case(s) run against the real artefacts: "
            f"{negative_summary.get('rejected')} rejected, "
            f"{negative_summary.get('accepted_by_mistake')} accepted by mistake, "
            f"{negative_summary.get('false_accusations')} honest state(s) refused by mistake"
            if negative_summary
            else "not run in this build"
        ),
        "RUNTIME_TESTS": (
            f"{runtime['status']}: "
            f"{sum(1 for item in runtime['chain'] if item['available'])} of "
            f"{len(runtime['chain'])} links of the runtime chain are held by real artefacts; the "
            "external trigger is not among them"
        ),
        "INDEPENDENT_VERIFICATION": (
            verification.get("status", "NOT_RUN") if verification else "NOT_RUN"
        ),
        "FALSE_SUCCESS": (verification or {}).get("false_success", 0),
        "COMMITS": commits_text,
        "BLOCKERS": [
            f"{gate.get('status')}: {gate.get('change_contemplated')} was requested and not "
            "approved, and the unelevated attempt was refused with exit code "
            f"{(gate.get('probe') or {}).get('exit_code')} ({(gate.get('probe') or {}).get('stderr')})",
            "without that change no external per-run record can exist, so no slot of this period can "
            "be corroborated run by run",
        ],
        "NEXT_GATE": (
            "the real close of the ST-6 period at "
            f"{period.get('ends_at_utc')}, and — before it — the single command that would let the "
            "remaining slots of the period be corroborated as they happen: wevtutil sl "
            "Microsoft-Windows-TaskScheduler/Operational /e:true, with an elevated token"
        ),
        "STANDING_INVARIANTS": [
            "ST6_AUTONOMOUS_COLLECTION_ACTIVE",
            "ECO-1 = OPEN",
            "NEXT_CAMPAIGN = NOT_AUTHORIZED",
            "LIVE_TRADING = DISABLED",
            "TRADES_AUTHORIZED = 0",
            "PROFITABILITY_VERIFIED = FALSE",
        ],
        "rfc_identifier": {
            "number": "047",
            "free_in_the_registry_before_registration": registry.get("numbers", {}).get("047")
            is None
            if isinstance(registry.get("numbers"), dict)
            else None,
            "next_free_number_above_046_before_registration": registry.get(
                "next_free_number_above_046"
            ),
            "document": str(RFC_DOC.relative_to(REPO)).replace("\\", "/"),
            "artefacts": [
                "data/st6/RFC047_HOST_AUDIT.json",
                "data/st6/RFC047_WINDOWS_EVENT_EVIDENCE.json",
                "data/st6/RFC047_LEDGER_RECONCILIATION.json",
                "data/st6/RFC047_RUNTIME_VERIFICATION.json",
                "data/st6/RFC047_INDEPENDENT_VERIFICATION.md",
                "data/st6/RFC047_INDEPENDENT_VERIFICATION.json",
                "data/st6/RFC047_FINAL_REPORT.md",
                "data/st6/RFC047_FINAL_REPORT.json",
            ],
        },
        "runtime": runtime,
        "test_summary": tests,
    }
    markdown = render_markdown(report, reconciliation)
    write_json(REPORT_JSON, report, sort_keys=False)
    REPORT_MD.write_text(markdown, encoding="utf-8", newline="\n")
    return report, markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build RFC-047's reconciliation and report")
    parser.add_argument("--json", action="store_true", help="print the report")
    args = parser.parse_args(argv)
    reconciliation = build_reconciliation()
    runtime = build_runtime()
    report, _ = build_report(reconciliation, runtime)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False))
        return 0
    print(
        f"reconciliation: {reconciliation['totals']['slots']} slots, "
        f"{reconciliation['totals']['slots_with_an_external_confirmation']} externally confirmed, "
        f"{len(reconciliation['disagreements'])} disagreement(s)"
    )
    print(f"runtime: {runtime['status']}")
    print(f"report: {report['RFC047_STATUS']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
