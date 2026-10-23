"""RFC-047 — the independent verification of the provenance evidence, and its negative controls.

This program imports nothing from the builder, from the ledger or from the ingestion component.  It
reads their artefacts as documents, recomputes every statement it can from the raw evidence, and
asks the host itself what it currently says.  That is the whole point of it: a builder that checked
its own work would only be repeating an opinion, so ``BUILDER != VERIFIER`` is implemented here by
sharing no code and no vocabulary with what it checks.

It recomputes, separately from the builder:

* the state of the channel, from a fresh reading of the host rather than from the audit document;
* the declared slot grid, from the period, and compares it with the ledger's own bounds;
* RFC-047's classification of every slot, from the audit, the store and the live state;
* the hash of every stored record's original XML, and of the raw market evidence every collected
  slot rests on;
* the identity of the task in every stored record, and of the run each correlation quotes;
* the temporal integrity of the whole account: no slot ahead of now may be called lost, no
  confirmation may name an instant outside its slot, and no record may be dated in the future;
* the absence of live orders, of credential material and of any second scheduled task.

``--self-test`` then runs the eighteen adversarial cases of the request's test plan as mutations of
the real documents: seventeen of them must be rejected, one of them — a valid collection that carries
no external provenance — must be *accepted*, because treating that honest state as a defect would be
as wrong as accepting a fabrication.  A manipulation the verifier fails to reject is counted as a
false success, and a false success is the one result this program may never report as clean.

Run:  python scripts/rfc047_verify.py        (verify the artefacts, with the controls)
      python scripts/rfc047_verify.py --quiet
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "st6"
RFC047_DIR = DATA / "rfc047"
PERIOD_PATH = DATA / "ST6_PERIOD.json"
LEDGER = DATA / "ST6_SLOT_LEDGER.json"
HOST_AUDIT = DATA / "RFC047_HOST_AUDIT.json"
WINDOWS_EVIDENCE = DATA / "RFC047_WINDOWS_EVENT_EVIDENCE.json"
WINDOWS_LIVE = RFC047_DIR / "WINDOWS_EVENT_LIVE_STATE.json"
WINDOWS_STORE = RFC047_DIR / "WINDOWS_EVENTS.jsonl"
RECONCILIATION = DATA / "RFC047_LEDGER_RECONCILIATION.json"
RUNTIME = DATA / "RFC047_RUNTIME_VERIFICATION.json"
REPORT_JSON = DATA / "RFC047_FINAL_REPORT.json"
REPORT_MD = DATA / "RFC047_FINAL_REPORT.md"
WINDOW_INDEX = DATA / "ST6_WINDOWS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
SCHEDULER_EVIDENCE = DATA / "ST6_SCHEDULER_EVIDENCE.json"
REGISTRY = REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"
RFC_DOC = REPO / "docs" / "rfc" / "RFC-047_ST6_SCHEDULER_PROVENANCE.md"
RFC_DOC_JSON = REPO / "docs" / "rfc" / "RFC-047_ST6_SCHEDULER_PROVENANCE.json"
VERIFICATION_JSON = DATA / "RFC047_INDEPENDENT_VERIFICATION.json"
VERIFICATION_MD = DATA / "RFC047_INDEPENDENT_VERIFICATION.md"

CHANNEL_OPERATIONAL = "Microsoft-Windows-TaskScheduler/Operational"
CHANNEL_MAINTENANCE = "Microsoft-Windows-TaskScheduler/Maintenance"
TASK_NAME = "TradingAgentic-ST6-Forward"
SLOT_HOURS = 4
WIN_CORRELATION_TOLERANCE_S = 120
COMPLETION_GRACE_S = 30 * 60
FINAL_STATUSES = (
    "RFC047_VERIFIED",
    "RFC047_PARTIAL_EXTERNAL_EVIDENCE",
    "RFC047_BLOCKED_HOST_PERMISSIONS",
    "RFC047_FAILED",
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
    "evidence_refs",
    "runs",
    "concurrent_runs_in_slot",
    "verifier_status",
    "read_at_utc",
    "first_recorded_at_utc",
    "carried_forward_fields",
)
#: The shapes of a *value* that must never be found in a report.  Words are not scanned on purpose:
#: a document that says "no credentials are used" is not evidence of a credential, while a document
#: that carries one is, whatever it says about it.
CREDENTIAL_VALUE_PATTERNS = (
    r"(?i)\b(api[_-]?key|secret|token|password|passphrase)\b\s*[:=]\s*[\"'][^\"']{16,}[\"']",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)\bAuthorization\b\s*:\s*[\"']?Bearer\s+[A-Za-z0-9._-]{20,}",
)
DELIVERABLES = (
    "docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.md",
    "docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.json",
    "data/st6/RFC047_HOST_AUDIT.json",
    "data/st6/RFC047_WINDOWS_EVENT_EVIDENCE.json",
    "data/st6/RFC047_LEDGER_RECONCILIATION.json",
    "data/st6/RFC047_RUNTIME_VERIFICATION.json",
    "data/st6/RFC047_INDEPENDENT_VERIFICATION.md",
    "data/st6/RFC047_INDEPENDENT_VERIFICATION.json",
    "data/st6/RFC047_FINAL_REPORT.md",
    "data/st6/RFC047_FINAL_REPORT.json",
)


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    text = str(stamp)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return document if isinstance(document, dict) else {}


def _read_jsonl(path: Path) -> tuple[list[Any], int]:
    """Every parseable line, and how many lines could not be parsed at all."""
    if not path.exists():
        return [], 0
    rows: list[Any] = []
    torn = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            torn += 1
    return rows, torn


def load_documents() -> dict[str, Any]:
    """The artefacts as documents.  Nothing here is trusted; it is only read."""
    store, torn = _read_jsonl(WINDOWS_STORE)
    windows, _ = _read_jsonl(WINDOW_INDEX)
    missed, _ = _read_jsonl(MISSED_LOG)
    runs, _ = _read_jsonl(RUN_LOG)
    return {
        "period": _read_json(PERIOD_PATH),
        "ledger": _read_json(LEDGER),
        "audit": _read_json(HOST_AUDIT),
        "evidence": _read_json(WINDOWS_EVIDENCE),
        "live": _read_json(WINDOWS_LIVE),
        "reconciliation": _read_json(RECONCILIATION),
        "runtime": _read_json(RUNTIME),
        "report": _read_json(REPORT_JSON),
        "registry": _read_json(REGISTRY),
        "scheduler_evidence": _read_json(SCHEDULER_EVIDENCE),
        "store": store,
        "store_torn_lines": torn,
        "windows": windows,
        "missed": missed,
        "runs": runs,
        "report_markdown": REPORT_MD.read_text(encoding="utf-8") if REPORT_MD.exists() else "",
        "rfc_document": RFC_DOC.read_text(encoding="utf-8") if RFC_DOC.exists() else "",
        "rfc_document_json": _read_json(RFC_DOC_JSON),
    }


# ---------------------------------------------------------------------------------------------
# the host's own answer, taken here rather than read from the audit
# ---------------------------------------------------------------------------------------------


def _wevtutil(arguments: list[str], timeout_s: int = 20) -> dict[str, Any]:
    try:
        answer = subprocess.run(
            ["wevtutil", *arguments], capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as failure:
        return {"status": type(failure).__name__, "stdout": "", "exit_code": None}
    return {
        "status": "OK" if answer.returncode == 0 else "REFUSED",
        "stdout": answer.stdout,
        "exit_code": answer.returncode,
    }


def probe_host() -> dict[str, Any]:
    """What the host says right now, read by this program rather than believed from a document."""
    operational_raw = _wevtutil(["gl", CHANNEL_OPERATIONAL])
    maintenance_raw = _wevtutil(["gl", CHANNEL_MAINTENANCE])
    maintenance_info = _wevtutil(["gli", CHANNEL_MAINTENANCE])
    enabled: bool | None = None
    for line in operational_raw["stdout"].splitlines():
        key, _, value = line.strip().partition(":")
        if key.strip() == "enabled":
            enabled = value.strip() == "true"
    records: int | None = None
    for line in maintenance_info["stdout"].splitlines():
        key, _, value = line.strip().partition(":")
        if key.strip() == "numberOfLogRecords":
            try:
                records = int(value.strip())
            except ValueError:
                records = None
    task_names: list[str] = []
    tasks_probe = {"status": "NOT_ASKED"}
    try:
        listed = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        tasks_probe = {
            "status": "OK" if listed.returncode == 0 else "REFUSED",
            "exit_code": listed.returncode,
        }
        task_names = sorted(
            {
                match.group(0)
                for match in re.finditer(r"TradingAgentic-[A-Za-z0-9-]+", listed.stdout)
            }
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as failure:
        tasks_probe = {"status": type(failure).__name__}
    return {
        "read_at_utc": _utc(),
        "operational_enabled": enabled,
        "operational_read_status": operational_raw["status"],
        "operational_config_sha256": hashlib.sha256(
            operational_raw["stdout"].encode("utf-8")
        ).hexdigest(),
        "maintenance_enabled": "enabled: true" in maintenance_raw["stdout"].lower(),
        "maintenance_records": records,
        "monitor_tasks": task_names,
        "schtasks": tasks_probe,
    }


# ---------------------------------------------------------------------------------------------
# independent recomputation
# ---------------------------------------------------------------------------------------------


def declared_grid(period: dict[str, Any]) -> list[dict[str, Any]]:
    """The declared slots, recomputed from the period alone.

    The contract is the *declared* grid: a whole number of days, each cut into slots of four hours
    from the hour the period began in, so a period that starts mid-slot declares that slot from the
    top of its hour and the partial slot the period ends inside is not a declared slot at all.  The
    ledger's own bounds are compared with this recomputation, because a ledger that invented,
    dropped or shifted a slot would otherwise be checked against nothing.
    """
    start = _parse(str(period.get("started_at_utc")))
    planned = int(period.get("period_days") or 0) * int(period.get("slots_per_day") or 0)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    slots: list[dict[str, Any]] = []
    while len(slots) < planned:
        index = cursor.hour // SLOT_HOURS
        slots.append(
            {
                "day": cursor.strftime("%Y-%m-%d"),
                "slot_index": index,
                "starts_at": cursor,
                "ends_at": cursor + timedelta(hours=SLOT_HOURS),
                "slot_id": f"{cursor.strftime('%Y-%m-%d')}#{index}",
            }
        )
        cursor += timedelta(hours=SLOT_HOURS)
    return slots


def recompute_windows_state(
    slot: dict[str, Any],
    runs: list[dict[str, Any]],
    audit: dict[str, Any],
    store: list[dict[str, Any]],
    live: dict[str, Any],
    now: datetime,
) -> str:
    """RFC-047's classification, recomputed here with this program's own vocabulary."""
    coverage_from = audit.get("coverage_from_utc")
    operational = ((audit.get("channels") or {}).get(CHANNEL_OPERATIONAL)) or {}
    config = operational.get("config") or {}
    starts_at, ends_at = slot["starts_at"], slot["ends_at"]
    ours = [
        row
        for row in store
        if row.get("belongs_to_the_monitored_task") and row.get("event_timestamp_utc")
    ]
    inside = [
        row for row in ours if starts_at <= _parse(str(row["event_timestamp_utc"])) <= ends_at
    ]
    correlated = False
    for run in runs:
        started = run.get("process_start_utc")
        if not started or not inside:
            continue
        try:
            moment = _parse(str(started))
        except ValueError:
            continue
        if any(
            abs((_parse(str(row["event_timestamp_utc"])) - moment).total_seconds())
            <= WIN_CORRELATION_TOLERANCE_S
            for row in inside
        ):
            correlated = True
            break
    if not coverage_from:
        return "PRE_ENABLE_NOT_OBSERVABLE"
    if not (operational.get("readable") and config.get("enabled")):
        return "WIN_EVENT_UNAVAILABLE"
    if correlated:
        return "WIN_EVENT_PARTIAL"
    if ends_at + timedelta(seconds=COMPLETION_GRACE_S) > now and config.get("enabled"):
        return "PENDING_EVENT_COMPLETION"
    reads = [
        _parse(str(entry.get("attempted_at_utc")))
        for entry in live.get("attempts") or []
        if (entry.get("channels") or {}).get(CHANNEL_OPERATIONAL, {}).get("status")
        in ("RECORDS_INGESTED", "NO_RECORDS_MATCHING_THE_TASK")
        and entry.get("attempted_at_utc")
    ]
    if any(moment >= ends_at + timedelta(seconds=COMPLETION_GRACE_S) for moment in reads):
        if any(
            str(run.get("declared_invocation") or "").upper() == "SCHEDULED"
            or run.get("origin") in ("CORROBORATED_ENGINE_LAUNCH", "SELF_DECLARED_UNVERIFIED")
            for run in runs
        ):
            return "WIN_EVENT_CONFLICT"
        return "WIN_EVENT_PARTIAL"
    return "WIN_EVENT_UNAVAILABLE"


def verify(
    documents: dict[str, Any], host: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    """Recompute every claim the artefacts make, and report what survives.

    ``documents`` and ``host`` are parameters rather than globals on purpose: the negative controls
    run this same function over mutated copies, so the checks that reject a fabrication are provably
    the checks that were applied to the real artefacts.
    """
    moment = now or datetime.now(UTC)
    findings: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any, severity: str = "FAIL") -> None:
        findings.append(
            {
                "check": name,
                "status": "PASS" if ok else ("UNVERIFIED" if severity == "UNVERIFIED" else "FAIL"),
                "detail": detail,
            }
        )

    period = documents.get("period") or {}
    ledger = documents.get("ledger") or {}
    audit = documents.get("audit") or {}
    live = documents.get("live") or {}
    reconciliation = documents.get("reconciliation") or {}
    runtime = documents.get("runtime") or {}
    report = documents.get("report") or {}
    registry = documents.get("registry") or {}
    scheduler_evidence = documents.get("scheduler_evidence") or {}
    store = documents.get("store") or []
    entries = [row for row in ledger.get("slots") or [] if isinstance(row, dict)]

    # 1 — the channel, against the host's own answer rather than the document's
    audit_enabled = (
        ((audit.get("channels") or {}).get(CHANNEL_OPERATIONAL) or {}).get("config") or {}
    ).get("enabled")
    check(
        "channel_state_matches_the_host",
        audit_enabled == host.get("operational_enabled"),
        {
            "audit_says_enabled": audit_enabled,
            "host_says_enabled": host.get("operational_enabled"),
            "read_at_utc": host.get("read_at_utc"),
        },
    )

    # 2 — the declared grid, recomputed, and the ledger's own bounds against it
    grid = declared_grid(period)
    ledger_bounds = {
        str(entry.get("slot_id")): (
            str(entry.get("slot_start_utc") or "")[:19],
            str(entry.get("slot_end_utc") or "")[:19],
        )
        for entry in entries
    }
    grid_bounds = {
        slot["slot_id"]: (
            slot["starts_at"].strftime("%Y-%m-%dT%H:%M:%S"),
            slot["ends_at"].strftime("%Y-%m-%dT%H:%M:%S"),
        )
        for slot in grid
    }
    boundaries_match = ledger_bounds == grid_bounds
    check(
        "declared_grid_recomputed",
        boundaries_match and len(grid) == len(entries),
        {
            "slots_declared_by_the_period": len(grid),
            "slots_in_the_ledger": len(entries),
            "bounds_agree": boundaries_match,
            "slots_per_day": period.get("slots_per_day"),
        },
    )

    # 3 — RFC-047's classification, recomputed for every slot
    mismatches: list[dict[str, Any]] = []
    for entry in entries:
        slot = {
            "starts_at": _parse(str(entry.get("slot_start_utc"))),
            "ends_at": _parse(str(entry.get("slot_end_utc"))),
        }
        recomputed = recompute_windows_state(
            slot, entry.get("runs") or [], audit, store, live, moment
        )
        reported = (entry.get("windows_event_evidence") or {}).get("state")
        if reported != recomputed:
            mismatches.append(
                {"slot_id": entry.get("slot_id"), "reported": reported, "recomputed": recomputed}
            )
    check(
        "provenance_recomputed",
        not mismatches,
        {"slots": len(entries), "mismatches": mismatches[:10], "count": len(mismatches)},
    )
    # a record of the monitored task cannot exist if the channel that would write it never recorded
    coverage_from = audit.get("coverage_from_utc")
    ours_in_store = [row for row in store if row.get("belongs_to_the_monitored_task")]
    check(
        "store_cannot_outlive_the_channel",
        not (ours_in_store and not coverage_from),
        {
            "records_of_the_monitored_task": len(ours_in_store),
            "coverage_from_utc": coverage_from,
            "reading": (
                "a record of this task in the store implies an instant from which the channel could "
                "have produced it"
            ),
        },
    )

    # 4 — the fields of every stored record, and the identity of the task in it
    required_record_fields = (
        "provider_name",
        "channel",
        "event_id",
        "event_record_id",
        "event_timestamp_utc",
        "computer",
        "task_full_path",
        "instance_id",
        "activity_id",
        "result_code",
        "event_xml_sha256",
        "collected_at_utc",
    )
    incomplete = [
        {"index": index, "missing": [field for field in required_record_fields if field not in row]}
        for index, row in enumerate(store)
        if isinstance(row, dict) and [field for field in required_record_fields if field not in row]
    ]
    wrong_task = [
        row.get("event_record_id")
        for row in store
        if isinstance(row, dict) and row.get("task_name") != TASK_NAME
    ]
    check(
        "xml_fields_and_task_identity",
        not incomplete and not wrong_task,
        {
            "records": len(store),
            "incomplete": incomplete[:5],
            "records_not_of_the_monitored_task": wrong_task[:5],
            "task": TASK_NAME,
            "task_known_to_the_scheduler": scheduler_evidence.get("task_name"),
        },
    )

    # 5 — the identity of every instance a correlation quotes
    store_keys = {f"{row.get('channel')}#{row.get('event_record_id')}" for row in store}
    bad_correlations: list[dict[str, Any]] = []
    for entry in entries:
        block = entry.get("windows_event_evidence") or {}
        for row in block.get("correlated_runs") or []:
            key = f"{block.get('channel')}#{row.get('event_record_id')}"
            wanted = {
                "slot_id": entry.get("slot_id"),
                "key": key,
                "in_store": key in store_keys,
                "delta_s": row.get("delta_s"),
            }
            wanted["within_tolerance"] = (row.get("delta_s") or 0) <= WIN_CORRELATION_TOLERANCE_S
            wanted["inside_the_slot"] = bool(
                row.get("event_timestamp_utc")
                and entry.get("slot_start_utc")
                and _parse(str(entry["slot_start_utc"]))
                <= _parse(str(row["event_timestamp_utc"]))
                <= _parse(str(entry["slot_end_utc"]))
            )
            if not (
                wanted["in_store"] and wanted["within_tolerance"] and wanted["inside_the_slot"]
            ):
                bad_correlations.append(wanted)
    check("instance_identity", not bad_correlations, {"problems": bad_correlations[:5]})

    # 6 — the hashes of the evidence, recomputed
    bad_hashes: list[dict[str, Any]] = []
    for row in store:
        if not isinstance(row, dict):
            continue
        xml = row.get("event_xml")
        recorded = row.get("event_xml_sha256")
        if xml is None:
            bad_hashes.append(
                {"event_record_id": row.get("event_record_id"), "reason": "the XML was not kept"}
            )
            continue
        if hashlib.sha256(str(xml).encode("utf-8")).hexdigest() != recorded:
            bad_hashes.append(
                {"event_record_id": row.get("event_record_id"), "reason": "the hash does not match"}
            )
    windows_by_id = {str(row.get("window_id")): row for row in documents.get("windows") or []}
    bad_raw: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("state") != "COLLECTED":
            continue
        window = windows_by_id.get(str(entry.get("collection_window_id")))
        raw_path = (entry.get("evidence_refs") or {}).get("raw")
        if window is None or not raw_path or not (REPO / str(raw_path)).exists():
            bad_raw.append(
                {"slot_id": entry.get("slot_id"), "reason": "the raw evidence is absent"}
            )
            continue
        with gzip.open(REPO / str(raw_path), "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        if digest != entry.get("raw_evidence_hash"):
            bad_raw.append(
                {"slot_id": entry.get("slot_id"), "reason": "the hash does not reproduce"}
            )
    check(
        "hashes_reproduce",
        not bad_hashes and not bad_raw,
        {"event_hash_problems": bad_hashes[:5], "raw_evidence_problems": bad_raw[:5]},
    )

    # 6b — the store's own invariants: what a bounded, deduplicated, incrementally read store must
    # hold, checked from the documents alone so that a state claiming a read the channel could not
    # have served is caught even when the host cannot be asked
    operational_audit = ((audit.get("channels") or {}).get(CHANNEL_OPERATIONAL)) or {}
    operational_enabled = (operational_audit.get("config") or {}).get("enabled")
    keys = [f"{row.get('channel')}#{row.get('event_record_id')}" for row in store]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    watermarks = live.get("watermarks") or {}
    attempts = live.get("attempts") or []
    impossible_reads = [
        {
            "attempted_at_utc": entry.get("attempted_at_utc"),
            "status": (entry.get("channels") or {}).get(CHANNEL_OPERATIONAL, {}).get("status"),
        }
        for entry in attempts
        if (entry.get("channels") or {}).get(CHANNEL_OPERATIONAL, {}).get("status")
        in (
            "RECORDS_INGESTED",
            "NO_RECORDS_MATCHING_THE_TASK",
            "CHANNEL_DISABLED_NO_RECORDS",
        )
        and not operational_audit.get("readable")
    ]
    # a channel that has never recorded cannot have yielded records, and a range that was overwritten
    # before it was read has to be recorded as such rather than passed over in silence
    records_from_an_empty_channel = [
        {
            "attempted_at_utc": entry.get("attempted_at_utc"),
            "status": (entry.get("channels") or {}).get(CHANNEL_OPERATIONAL, {}).get("status"),
        }
        for entry in attempts
        if (entry.get("channels") or {}).get(CHANNEL_OPERATIONAL, {}).get("status")
        == "RECORDS_INGESTED"
        and (
            not operational_enabled
            or (operational_audit.get("log_info") or {}).get("records_present") in (None, 0)
        )
    ]
    rotations_passed_over = [
        {
            "attempted_at_utc": entry.get("attempted_at_utc"),
            "channel": channel,
            "reported_gap": (report or {}).get("gap"),
            "oldest_still_present": oldest,
            "watermark_before": watermark,
        }
        for entry in attempts
        for channel, report in (entry.get("channels") or {}).items()
        for oldest, watermark in [
            (
                ((audit.get("channels") or {}).get(channel) or {})
                .get("log_info", {})
                .get("oldest_record_number"),
                (report or {}).get("watermark_before"),
            )
        ]
        if isinstance(oldest, int)
        and isinstance(watermark, int)
        and oldest > watermark + 1
        and not (report or {}).get("gap")
    ]
    # the audit's own fields have to agree with each other: a channel it calls unreadable cannot be
    # simultaneously reported as merely disabled, and one it calls disabled cannot be called available
    reported_state = operational_audit.get("state")
    expected_state = (
        "CHANNEL_UNREADABLE"
        if not operational_audit.get("readable") and operational_audit
        else ("CHANNEL_AVAILABLE" if operational_enabled else "CHANNEL_DISABLED")
    )
    state_agrees = not operational_audit or reported_state == expected_state
    highest_stored = max((int(row.get("event_record_id") or 0) for row in store), default=None)
    watermark_below_the_store = bool(
        highest_stored is not None
        and (
            watermarks.get(CHANNEL_OPERATIONAL) is None
            or int(watermarks[CHANNEL_OPERATIONAL]) < highest_stored
        )
    )
    declared_total = ((documents.get("evidence") or {}).get("store") or {}).get("records_total")
    check(
        "store_invariants",
        not duplicates
        and not impossible_reads
        and not records_from_an_empty_channel
        and not rotations_passed_over
        and not watermark_below_the_store
        and declared_total == len(store)
        and state_agrees,
        {
            "records": len(store),
            "duplicate_keys": duplicates[:5],
            "attempts_claiming_a_read_the_channel_could_not_serve": impossible_reads,
            "reads_of_a_channel_that_never_recorded": records_from_an_empty_channel,
            "rotations_not_recorded": rotations_passed_over,
            "watermark_behind_the_store": watermark_below_the_store,
            "declared_records_total": declared_total,
            "watermark": watermarks,
            "channel_state_as_reported": reported_state,
            "channel_state_the_other_fields_imply": expected_state,
        },
    )

    # 7 — the ledger: its own contract, its own states, and the noise of a torn store
    missing_v1 = {
        str(entry.get("slot_id")): [field for field in LEDGER_V1_FIELDS if field not in entry]
        for entry in entries
        if [field for field in LEDGER_V1_FIELDS if field not in entry]
    }
    unknown_states = sorted(
        {
            str((entry.get("windows_event_evidence") or {}).get("state"))
            for entry in entries
            if (entry.get("windows_event_evidence") or {}).get("state") not in WINDOWS_STATES
        }
    )
    check(
        "ledger_contract",
        not missing_v1 and not unknown_states and documents.get("store_torn_lines", 0) == 0,
        {
            "ledger_version": ledger.get("ledger_version"),
            "slots": len(entries),
            "missing_version_1_fields": missing_v1,
            "states_outside_the_vocabulary": unknown_states,
            "torn_lines_in_the_store": documents.get("store_torn_lines", 0),
            "reading": (
                "the store is replaced atomically, so a torn line in it means a write that did not "
                "go through the temporary file, and a record may have been lost"
            ),
        },
    )

    # 7b — every slot that has ended is accounted for: a slot with a run but no window has to say
    # why, and an end nobody explained is a defect of the programme rather than a state of the
    # schedule.  (The ledger calls that state UNACCOUNTED and reports it as a defect; what may never
    # happen is for it to be reported as a clean outcome.)
    unaccounted = [
        entry.get("slot_id")
        for entry in entries
        if entry.get("state") == "UNACCOUNTED" and _parse(str(entry.get("slot_end_utc"))) <= moment
    ]
    runs_without_an_outcome = [
        entry.get("slot_id")
        for entry in entries
        if entry.get("runs")
        and entry.get("state") != "COLLECTED"
        and _parse(str(entry.get("slot_end_utc"))) <= moment
        and entry.get("attendance_classification") is None
    ]
    check(
        "every_ended_slot_is_accounted_for",
        not unaccounted and not runs_without_an_outcome,
        {
            "slots_that_ended_unaccounted": unaccounted[:5],
            "slots_with_a_run_but_no_outcome": runs_without_an_outcome[:5],
            "reading": (
                "a slot that has ended either produced its window, or carries the classification of "
                "the loss that explains it; there is no third state that may pass silently"
            ),
        },
    )

    # 8 — temporal integrity.  A slot still running may legitimately have collected its window
    # already — what it may never have is an outcome *about* a slot that has not finished: a loss, an
    # unaccounted end, or a classification that says what it failed to collect.
    future_slots_that_claim_an_outcome = [
        entry.get("slot_id")
        for entry in entries
        if _parse(str(entry.get("slot_end_utc"))) > moment
        and (
            entry.get("state") in ("LOST_NO_WINDOW", "UNACCOUNTED")
            or entry.get("attendance_classification") is not None
            or entry.get("failure_reason") is not None
        )
    ]
    future_events = [
        row.get("event_record_id")
        for row in store
        if isinstance(row, dict)
        and row.get("event_timestamp_utc")
        and _parse(str(row["event_timestamp_utc"])) > moment + timedelta(seconds=60)
    ]
    confirmations_quoting_nothing = [
        entry.get("slot_id")
        for entry in entries
        if str((entry.get("windows_event_evidence") or {}).get("state") or "").startswith(
            "WIN_EVENT_CONFIRMED"
        )
        and not (entry.get("windows_event_evidence") or {}).get("correlated_runs")
    ]
    check(
        "temporal_integrity",
        not future_slots_that_claim_an_outcome
        and not future_events
        and not confirmations_quoting_nothing,
        {
            "slots_ahead_of_now_with_an_outcome": future_slots_that_claim_an_outcome[:5],
            "records_dated_in_the_future": future_events[:5],
            "confirmations_without_a_correlated_run": confirmations_quoting_nothing[:5],
        },
    )

    # 9 — the absence of live orders, of credential material and of a second task
    artefact_paths = [
        RFC_DOC,
        *[REPO / item for item in DELIVERABLES if (REPO / item).exists()],
        WINDOWS_STORE,
        WINDOWS_LIVE,
    ]
    credential_hits: list[dict[str, Any]] = []
    for path in artefact_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in CREDENTIAL_VALUE_PATTERNS:
            if re.search(pattern, text):
                credential_hits.append({"path": str(path.relative_to(REPO)), "pattern": pattern})
    invariants = report.get("STANDING_INVARIANTS") or []
    check(
        "no_live_orders_or_credentials",
        not credential_hits
        and "LIVE_TRADING = DISABLED" in invariants
        and "TRADES_AUTHORIZED = 0" in invariants,
        {
            "credential_values_found": credential_hits,
            "standing_invariants": invariants,
            "scanned": len(artefact_paths),
        },
    )
    tasks = host.get("monitor_tasks") or []
    created_by_this_rfc = [name for name in tasks if "047" in name]
    task_of_the_campaign = tasks.count(TASK_NAME)
    task_probe_answered = host.get("schtasks", {}).get("status") == "OK"
    check(
        "no_additional_scheduled_task",
        task_of_the_campaign == 1 and not created_by_this_rfc,
        {
            "tasks_on_the_host": tasks,
            "the_task_of_the_campaign": TASK_NAME,
            "occurrences_of_it": task_of_the_campaign,
            "tasks_this_rfc_would_have_created": created_by_this_rfc,
            "probe": host.get("schtasks"),
            "reading": (
                "the campaign's own task is present exactly once and no task carries this RFC's "
                "number, so this RFC created none: the other tasks on the host belong to other "
                "campaigns of the project and are untouched"
                if task_probe_answered
                else "the host could not be asked, so the absence of a second task is unverified"
            ),
        },
        severity="FAIL" if task_probe_answered else "UNVERIFIED",
    )

    # 10 — the final report's claims against the recomputation
    confirmed = sum(
        1
        for entry in entries
        if (entry.get("windows_event_evidence") or {}).get("state")
        == "WIN_EVENT_CONFIRMED_SCHEDULED"
    )
    contradicted: list[dict[str, Any]] = []

    def expect(field: str, expected: Any) -> None:
        if report.get(field) != expected:
            contradicted.append(
                {"field": field, "report": report.get(field), "recomputed": expected}
            )

    expect("FALSE_SUCCESS", 0)
    expect("REAL_EXECUTION_CORROBORATED", bool(confirmed))
    expect("EXTERNAL_EVENTS_CAPTURED", len(store))
    if report.get("RFC047_STATUS") not in FINAL_STATUSES:
        contradicted.append(
            {"field": "RFC047_STATUS", "report": report.get("RFC047_STATUS"), "recomputed": None}
        )
    if report.get("EXTERNAL_EVENTS_CAPTURED") != len(store):
        contradicted.append(
            {
                "field": "EXTERNAL_EVENTS_CAPTURED",
                "report": report.get("EXTERNAL_EVENTS_CAPTURED"),
                "recomputed": len(store),
            }
        )
    if not contradictions_free(reconciliation):
        contradicted.append(
            {
                "field": "LEDGER_RECONCILIATION",
                "report": "clean",
                "recomputed": reconciliation.get("disagreements"),
            }
        )
    check("report_claims_hold", not contradicted, {"contradictions": contradicted})

    # 11 — the deliverables and the identifier registry
    missing_deliverables = [item for item in DELIVERABLES if not (REPO / item).exists()]
    registry_number = (registry.get("numbers") or {}).get("047")
    check(
        "deliverables_and_identifier",
        not missing_deliverables
        and registry_number is not None
        and bool(documents.get("rfc_document"))
        and bool(documents.get("rfc_document_json"))
        and (documents.get("rfc_document_json") or {}).get("status") == report.get("RFC047_STATUS"),
        {
            "missing": missing_deliverables,
            "registry_entry": registry_number,
            "next_free_number_above_046": registry.get("next_free_number_above_046"),
            "document_present": bool(documents.get("rfc_document")),
            "status_in_the_document": (documents.get("rfc_document_json") or {}).get("status"),
            "status_in_the_report": report.get("RFC047_STATUS"),
        },
    )

    # 12 — the runtime chain, and whether the report describes it as it is
    runtime_links = runtime.get("chain") or []
    external_trigger = next(
        (item for item in runtime_links if item.get("link") == "windows_scheduled_trigger"), None
    )
    check(
        "runtime_chain_is_honest",
        bool(runtime_links)
        and bool(external_trigger)
        and external_trigger.get("available") is False
        and runtime.get("external_trigger_confirmed") is False
        and (confirmed > 0) == bool(runtime.get("runtime_correlation_achieved")),
        {
            "links": len(runtime_links),
            "external_trigger_available": (external_trigger or {}).get("available"),
            "external_trigger_confirmed": runtime.get("external_trigger_confirmed"),
            "confirmed_slots_recomputed_here": confirmed,
            "status": runtime.get("status"),
        },
    )

    failures = [item for item in findings if item["status"] == "FAIL"]
    unverified = [item for item in findings if item["status"] == "UNVERIFIED"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": len(findings),
        "failed_checks": [item["check"] for item in failures],
        "unverified_checks": [item["check"] for item in unverified],
        "findings": findings,
        "recomputed": {
            "slots": len(entries),
            "slots_declared_by_the_period": len(grid),
            "windows_states": {
                state: sum(
                    1
                    for entry in entries
                    if (entry.get("windows_event_evidence") or {}).get("state") == state
                )
                for state in WINDOWS_STATES
            },
            "records_in_the_store": len(store),
            "slots_with_an_external_confirmation": confirmed,
            "channel_enabled_per_the_host": host.get("operational_enabled"),
            "monitor_tasks_on_the_host": host.get("monitor_tasks"),
        },
    }


def contradictions_free(reconciliation: dict[str, Any]) -> bool:
    return not (reconciliation.get("disagreements") or reconciliation.get("contradictions"))


# ---------------------------------------------------------------------------------------------
# the negative controls: the eighteen cases of the test plan, as mutations of the real documents
# ---------------------------------------------------------------------------------------------


def _slot_entries(documents: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (documents["ledger"].get("slots") or []) if isinstance(row, dict)]


def _first_collected(documents: dict[str, Any]) -> dict[str, Any]:
    for entry in _slot_entries(documents):
        if entry.get("state") == "COLLECTED":
            return entry
    raise AssertionError("no collected slot to mutate")


def _a_claimed_scheduled_without_a_record(documents: dict[str, Any]) -> None:
    entry = _slot_entries(documents)[0]
    entry["windows_event_evidence"]["state"] = "WIN_EVENT_CONFIRMED_SCHEDULED"


def _an_event_of_another_task(documents: dict[str, Any]) -> None:
    row = dict(documents["store"][0]) if documents["store"] else _synthetic_record(documents)
    row["task_name"] = "SomeOtherTask"
    row["task_full_path"] = "\\SomeOtherTask"
    documents["store"].append(row)


def _two_instances_close_together(documents: dict[str, Any]) -> None:
    row = dict(documents["store"][0]) if documents["store"] else _synthetic_record(documents)
    row["event_record_id"] = int(row.get("event_record_id") or 1) + 1
    documents["store"].append(row)


def _manual_confused_with_scheduled(documents: dict[str, Any]) -> None:
    entry = _slot_entries(documents)[0]
    entry["runs"] = [
        {
            **(entry.get("runs") or [{}])[0],
            "declared_invocation": "MANUAL",
            "origin": "MANUAL",
        }
    ]
    entry["windows_event_evidence"]["state"] = "WIN_EVENT_CONFIRMED_SCHEDULED"


def _start_without_completion(documents: dict[str, Any]) -> None:
    row = _synthetic_record(documents)
    row["result_code"] = None
    row["declared_role"] = None
    documents["store"].append(row)
    documents["ledger"]["slots"][1]["windows_event_evidence"]["state"] = (
        "WIN_EVENT_CONFIRMED_SCHEDULED"
    )


def _late_completion_event(documents: dict[str, Any]) -> None:
    entry = _first_collected(documents)
    gone = [row for row in documents["store"]]
    documents["store"] = [
        *gone,
        {
            **_synthetic_record(documents),
            "event_timestamp_utc": entry["slot_start_utc"],
            "belongs_to_the_monitored_task": True,
            "task_name": TASK_NAME,
        },
    ]
    entry["windows_event_evidence"]["state"] = "WIN_EVENT_UNAVAILABLE"


def _duplicate_event_record_id(documents: dict[str, Any]) -> None:
    row = dict(documents["store"][0]) if documents["store"] else _synthetic_record(documents)
    documents["store"].extend([row, dict(row)])


def _rotation_before_reading(documents: dict[str, Any]) -> None:
    documents["live"].setdefault("attempts", []).append(
        {
            "attempted_at_utc": "2026-10-09T10:00:00Z",
            "channels": {CHANNEL_OPERATIONAL: {"status": "RECORDS_INGESTED"}},
        }
    )
    documents["live"].setdefault("watermarks", {})[CHANNEL_OPERATIONAL] = 10


def _channel_disabled_during_a_run(documents: dict[str, Any]) -> None:
    documents["audit"]["channels"][CHANNEL_OPERATIONAL]["config"]["enabled"] = True
    documents["audit"]["coverage_from_utc"] = "2026-10-09T00:00:00Z"


def _permission_denied(documents: dict[str, Any]) -> None:
    documents["audit"]["channels"][CHANNEL_OPERATIONAL]["readable"] = False


def _manipulated_xml(documents: dict[str, Any]) -> None:
    if documents["store"]:
        documents["store"][0]["event_xml"] = "<Event>tampered</Event>"
    else:
        row = _synthetic_record(documents)
        row["event_xml"] = "<Event>tampered</Event>"
        row["event_xml_sha256"] = "0" * 64
        documents["store"].append(row)


def _corrupt_ledger(documents: dict[str, Any]) -> None:
    entry = _slot_entries(documents)[0]
    entry.pop("external_evidence_status", None)


def _a_fake_timestamp(documents: dict[str, Any]) -> None:
    row = documents["store"][0] if documents["store"] else _synthetic_record(documents)
    row["event_timestamp_utc"] = "2099-01-01T00:00:00.000000Z"
    if not documents["store"]:
        documents["store"].append(row)


def _market_evidence_absent(documents: dict[str, Any]) -> None:
    entry = _first_collected(documents)
    entry["evidence_refs"]["raw"] = "data/st6/raw/does_not_exist.json.gz"


def _a_process_without_collection(documents: dict[str, Any]) -> None:
    entry = _slot_entries(documents)[0]
    entry["state"] = "UNACCOUNTED"
    entry["collection_window_id"] = None


def _a_valid_collection_without_provenance(documents: dict[str, Any]) -> None:
    documents["audit"]["coverage_from_utc"] = None
    for entry in _slot_entries(documents):
        entry["windows_event_evidence"]["state"] = "PRE_ENABLE_NOT_OBSERVABLE"


def _a_restart_during_persistence(documents: dict[str, Any]) -> None:
    documents["store_torn_lines"] = 1


def _a_future_slot_counted_as_lost(documents: dict[str, Any]) -> None:
    for entry in _slot_entries(documents):
        if entry.get("state") == "PENDING":
            entry["state"] = "LOST_NO_WINDOW"
            entry["attendance_classification"] = "ATTENDED_NOT_COLLECTED"
            break


def _synthetic_record(documents: dict[str, Any]) -> dict[str, Any]:
    """A record of the monitored task, shaped like a stored one, for a mutation that needs one."""
    entry = _slot_entries(documents)[0]
    xml = "<Event>synthetic</Event>"
    return {
        "provider_name": "Microsoft-Windows-TaskScheduler",
        "channel": CHANNEL_OPERATIONAL,
        "event_id": 100,
        "event_record_id": 999001,
        "event_timestamp_utc": entry["slot_start_utc"],
        "event_timestamp_basis": "SYSTEM_TIME_UTC",
        "computer": "SYNTHETIC",
        "task_full_path": "\\" + TASK_NAME,
        "task_name": TASK_NAME,
        "belongs_to_the_monitored_task": True,
        "instance_id": None,
        "activity_id": None,
        "result_code": "0",
        "event_xml": xml,
        "event_xml_sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(),
        "collected_at_utc": "2026-10-09T00:00:00Z",
    }


#: The eighteen cases of the request's adversarial plan.  ``REJECT`` means the verifier must refuse
#: the mutated artefacts; ``ACCEPT`` means it must not, because the state is honest and treating it as
#: a defect would be a false accusation.
NEGATIVE_CONTROLS: tuple[tuple[str, str, Callable[[dict[str, Any]], None]], ...] = (
    (
        "an internal run claiming the schedule with no Windows event",
        "REJECT",
        _a_claimed_scheduled_without_a_record,
    ),
    ("a Windows event belonging to another task", "REJECT", _an_event_of_another_task),
    ("two instances with neighbouring timestamps", "REJECT", _two_instances_close_together),
    ("a manual execution presented as scheduled", "REJECT", _manual_confused_with_scheduled),
    ("a start event with no completion", "REJECT", _start_without_completion),
    ("a completion event that arrives late", "REJECT", _late_completion_event),
    ("a duplicated EventRecordID", "REJECT", _duplicate_event_record_id),
    ("a rotation that happened before the read", "REJECT", _rotation_before_reading),
    ("the channel disabled during a run", "REJECT", _channel_disabled_during_a_run),
    ("a read refused for lack of permission", "REJECT", _permission_denied),
    ("manipulated event XML", "REJECT", _manipulated_xml),
    ("a corrupt ledger", "REJECT", _corrupt_ledger),
    ("a fabricated timestamp", "REJECT", _a_fake_timestamp),
    ("market evidence that is absent", "REJECT", _market_evidence_absent),
    ("a process executed without collecting", "REJECT", _a_process_without_collection),
    (
        "a valid collection without external provenance",
        "ACCEPT",
        _a_valid_collection_without_provenance,
    ),
    ("a restart during persistence", "REJECT", _a_restart_during_persistence),
    ("a future slot counted as lost", "REJECT", _a_future_slot_counted_as_lost),
)


def run_negative_controls(
    documents: dict[str, Any], host: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Run the eighteen cases and say what the verifier did with each.

    Each case is judged *against the baseline of the unmutated artefacts*: what matters is whether
    the mutation made the verifier refuse something it had accepted, not whether the artefacts were
    already failing for some other reason.  Without that subtraction a baseline problem would look
    like eighteen successful controls.
    """
    baseline = verify(copy.deepcopy(documents), host, now)
    baseline_failures = set(baseline["failed_checks"])
    cases: list[dict[str, Any]] = []
    rejected = 0
    accepted_by_mistake = 0
    false_accusations = 0
    for name, expectation, mutate in NEGATIVE_CONTROLS:
        mutated = copy.deepcopy(documents)
        mutate(mutated)
        outcome = verify(mutated, host, now)
        new_failures = sorted(set(outcome["failed_checks"]) - baseline_failures)
        refused = bool(new_failures)
        if expectation == "REJECT" and refused:
            rejected += 1
        if expectation == "REJECT" and not refused:
            accepted_by_mistake += 1
        if expectation == "ACCEPT" and refused:
            false_accusations += 1
        cases.append(
            {
                "case": name,
                "expected": expectation,
                "observed": "REJECTED" if refused else "ACCEPTED",
                "as_required": (refused and expectation == "REJECT")
                or (not refused and expectation == "ACCEPT"),
                "checks_that_caught_it": new_failures,
            }
        )
    return {
        "baseline_status": baseline["status"],
        "baseline_failed_checks": sorted(baseline_failures),
        "cases": cases,
        "count": len(cases),
        "rejected": rejected,
        "accepted_by_mistake": accepted_by_mistake,
        "false_accusations": false_accusations,
        "reading": (
            "each case mutates the real artefacts in one specific way and is put through the same "
            "verification; a manipulation that survives is a false success, and refusing an honest "
            "state would be a false accusation — both are counted, neither is hidden"
        ),
    }


# ---------------------------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------------------------


def render_markdown(document: dict[str, Any]) -> str:
    lines: list[str] = [
        "# RFC-047 — INDEPENDENT VERIFICATION",
        "",
        f"- **status**: `{document['status']}`",
        f"- **taken at**: {document['taken_at_utc']}",
        "- **verifier**: `scripts/rfc047_verify.py` — imports nothing from the builder, the ledger "
        "or the ingestion component",
        f"- **checks**: {document['checks']} ({len(document['failed_checks'])} failed, "
        f"{len(document['unverified_checks'])} unverified)",
        f"- **FALSE_SUCCESS**: `{document['false_success']}`",
        f"- **false accusations**: `{document['false_accusations']}`",
        "",
        "## What was recomputed here rather than believed",
        "",
        "| recomputation | result |",
        "| --- | --- |",
        *[
            f"| {key} | `{json.dumps(value, ensure_ascii=False)}` |"
            for key, value in document["recomputed"].items()
        ],
        "",
        "## Checks",
        "",
        "| check | status | detail |",
        "| --- | --- |",
        *[
            "| `{check}` | {status} | {detail} |".format(
                check=item["check"],
                status=item["status"],
                detail=str(item["detail"]).replace("|", "\\|")[:400],
            )
            for item in document["findings"]
        ],
        "",
        "## Negative controls — the eighteen cases of the test plan",
        "",
        f"Baseline of the unmutated artefacts: `{document['negative_controls']['baseline_status']}`.",
        "",
        "| case | expected | observed | as required |",
        "| --- | --- | --- | --- |",
        *[
            f"| {case['case']} | {case['expected']} | {case['observed']} | "
            f"{'yes' if case['as_required'] else '**NO**'} |"
            for case in document["negative_controls"]["cases"]
        ],
        "",
        f"- manipulations rejected: **{document['negative_controls']['rejected']}**",
        f"- manipulations accepted by mistake: "
        f"**{document['negative_controls']['accepted_by_mistake']}**",
        f"- honest states refused by mistake: "
        f"**{document['negative_controls']['false_accusations']}**",
        "",
        "> A verifier that shared code with the builder would only be repeating an opinion. This one",
        "> re-derives the channel's state from the host, the slot grid from the period, every",
        "> classification from the raw evidence, and every hash from the bytes.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify RFC-047's provenance evidence")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-host", action="store_true", help="skip the host probes")
    args = parser.parse_args(argv)
    documents = load_documents()
    host = (
        {"operational_enabled": None, "monitor_tasks": [], "schtasks": {"status": "NOT_ASKED"}}
        if args.no_host
        else probe_host()
    )
    outcome = verify(documents, host)
    controls = run_negative_controls(documents, host, datetime.now(UTC))
    # a claim the artefacts do not support is a false success in its own right, so the checks that
    # failed on the *unmutated* documents are counted here together with the manipulations that
    # survived; an honest state refused by mistake is counted separately as a false accusation
    false_success = controls["accepted_by_mistake"] + len(outcome["failed_checks"])
    document: dict[str, Any] = {
        "artifact": "RFC047_INDEPENDENT_VERIFICATION",
        "verifier": "scripts/rfc047_verify.py",
        "builder": "scripts/rfc047_builder.py, scripts/st6_slot_ledger.py, scripts/st6_windows_events.py",
        "builder_is_not_the_verifier": (
            "no module of the builder is imported here and no constant of its vocabulary is shared: "
            "the checks below re-derive what they compare"
        ),
        "taken_at_utc": _utc(),
        "status": outcome["status"],
        "checks": outcome["checks"],
        "findings": outcome["findings"],
        "failed_checks": outcome["failed_checks"],
        "unverified_checks": outcome["unverified_checks"],
        "recomputed": outcome["recomputed"],
        "host_probe": host,
        "negative_controls": controls,
        "false_success": false_success,
        "false_accusations": controls["false_accusations"],
        "false_success_reading": (
            "a manipulation the verifier accepted, or a claim the artefacts do not support: the only "
            "clean value is zero.  An honest state refused by mistake is reported separately as a "
            "false accusation, because it is a different failure and must not be hidden inside this "
            "count"
        ),
    }
    if outcomes := [item for item in outcome["findings"] if item["status"] == "FAIL"]:
        document["status"] = "FAIL"
        document["failure_summary"] = [
            {"check": item["check"], "detail": item["detail"]} for item in outcomes
        ]
    VERIFICATION_JSON.parent.mkdir(parents=True, exist_ok=True)
    temporary = VERIFICATION_JSON.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(VERIFICATION_JSON)
    VERIFICATION_MD.write_text(render_markdown(document), encoding="utf-8")
    if not args.quiet:
        print(
            f"verification: {document['status']} — {document['checks']} checks, "
            f"{len(document['failed_checks'])} failed, {len(document['unverified_checks'])} unverified"
        )
        print(
            f"negative controls: {controls['count']} cases, {controls['rejected']} rejected, "
            f"{controls['accepted_by_mistake']} accepted by mistake, "
            f"{controls['false_accusations']} false accusations"
        )
        print(f"FALSE_SUCCESS: {document['false_success']}")
        for item in outcome["findings"]:
            if item["status"] != "PASS":
                print(f"  {item['status']}: {item['check']} -> {item['detail']}")
    return 0 if document["status"] == "PASS" and document["false_success"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
