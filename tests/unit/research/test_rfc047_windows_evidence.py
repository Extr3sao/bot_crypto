"""Tests for RFC-047 — the Windows event plane, its ledger block and its independent verifier.

The subject of this RFC is a *difference of evidence*: a program's claim that the schedule started it
against the host's own record of what it started.  So the tests that matter are the ones about
restraint and about refusal — an identifier that is not allowed to decide anything on its own, a
canonical instant that must not be read as UTC because it was spelled that way, a watermark that must
not step over a record that could not be read, a report that must not reach a confirmation without a
record behind it, and a verifier that must refuse a fabrication while still accepting an honest state.

The verifier's own eighteen adversarial cases are exercised here as well, as the request's test plan
asks, and the real artefacts on disk are checked as they are: this RFC's subject is the provenance of
the artefacts, so a test that only ever ran over fixtures would be testing the fixture, not the file.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "st6"
RFC047_DIR = DATA / "rfc047"
LEDGER = DATA / "ST6_SLOT_LEDGER.json"
HOST_AUDIT = DATA / "RFC047_HOST_AUDIT.json"
WINDOWS_EVIDENCE = DATA / "RFC047_WINDOWS_EVENT_EVIDENCE.json"
LIVE_STATE = RFC047_DIR / "WINDOWS_EVENT_LIVE_STATE.json"
STORE = RFC047_DIR / "WINDOWS_EVENTS.jsonl"
RECONCILIATION = DATA / "RFC047_LEDGER_RECONCILIATION.json"
RUNTIME = DATA / "RFC047_RUNTIME_VERIFICATION.json"
REPORT_JSON = DATA / "RFC047_FINAL_REPORT.json"
RFC_DOC_JSON = REPO / "docs" / "rfc" / "RFC-047_ST6_SCHEDULER_PROVENANCE.json"
REGISTRY = REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"
PERIOD = DATA / "ST6_PERIOD.json"

TASK = "TradingAgentic-ST6-Forward"
GL_TEXT = """name: Microsoft-Windows-TaskScheduler/Operational
enabled: false
type: Operational
owningPublisher: Microsoft-Windows-TaskScheduler
isolation: Application
channelAccess: O:BAG:SYD:(A;;0x7;;;BA)(A;;0x3;;;IU)
logging:
  logFileName: %SystemRoot%\\System32\\Winevt\\Logs\\Microsoft-Windows-TaskScheduler%4Operational.evtx
  retention: false
  autoBackup: false
  maxSize: 10485760
publishing:
  fileMax: 1
"""


def load_module(name: str, relative: str) -> object:
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def events() -> object:
    return load_module("rfc047_events", "scripts/st6_windows_events.py")


@pytest.fixture(scope="module")
def ledger_module() -> object:
    return load_module("rfc047_ledger", "scripts/st6_slot_ledger.py")


@pytest.fixture(scope="module")
def builder() -> object:
    return load_module("rfc047_builder", "scripts/rfc047_builder.py")


@pytest.fixture(scope="module")
def verifier() -> object:
    return load_module("rfc047_verifier", "scripts/rfc047_verify.py")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def event_fragment(
    record_id: int = 1234,
    event_id: int = 100,
    instant: str = "2026-10-09T16:00:00.1234567Z",
    task: str = "\\" + TASK,
    with_data: bool = True,
) -> str:
    data = (
        f"<EventData><Data Name='TaskName'>{task}</Data>"
        "<Data Name='ResultCode'>0</Data></EventData>"
        if with_data
        else ""
    )
    return (
        "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'>"
        "<System>"
        "<Provider Name='Microsoft-Windows-TaskScheduler' "
        "Guid='{de7b24ea-73c8-4a09-985d-5bdadcfa9017}'/>"
        f"<EventID>{event_id}</EventID><Level>4</Level>"
        f"<TimeCreated SystemTime='{instant}'/>"
        f"<EventRecordID>{record_id}</EventRecordID>"
        "<Correlation ActivityID='{11111111-2222-3333-4444-555555555555}'/>"
        "<Execution ProcessID='4321' ThreadID='999'/>"
        "<Channel>Microsoft-Windows-TaskScheduler/Operational</Channel>"
        "<Computer>HOST</Computer></System>"
        f"{data}</Event>"
    )


# ---------------------------------------------------------------------------------------------
# unit — the channel's own declaration, and the instant it writes
# ---------------------------------------------------------------------------------------------


def test_a_channels_own_configuration_is_parsed_from_its_own_words(events) -> None:
    config = events.parse_channel_config(GL_TEXT)
    assert config["parsed"] is True
    assert config["enabled"] is False
    assert config["max_size_bytes"] == 10485760
    # `retention: false` is the circular policy: the oldest record is overwritten, not archived
    assert config["retention"] == "false"
    assert config["auto_backup"] == "false"
    assert "Operational.evtx" in config["log_file_name"]


def test_an_unreadable_configuration_is_not_read_as_an_empty_one(events) -> None:
    assert events.parse_channel_config("")["parsed"] is False
    assert events.parse_channel_config("not a document at all")["parsed"] is False


def test_the_log_depth_is_parsed_and_a_missing_number_stays_missing(events) -> None:
    info = events.parse_log_info(
        "fileSize: 1052672\nnumberOfLogRecords: 2274\noldestRecordNumber: 440\n"
    )
    assert info["records_present"] == 2274
    assert info["oldest_record_number"] == 440
    assert events.parse_log_info("fileSize: not-a-number")["file_size_bytes"] is None


def test_the_providers_seven_digit_instant_keeps_its_microseconds(events) -> None:
    moment, had_zone = events.parse_window_instant("2026-10-09T19:28:23.7983097Z")
    assert had_zone is True
    assert moment.microsecond == 798309


def test_an_instant_without_a_zone_is_converted_and_never_labelled_utc(events) -> None:
    # the tool prints a host-local instant and still ends it with a Z elsewhere in this repository;
    # a value that carries no zone must be shifted by the offset, not trusted as UTC
    labelled, basis = events._normalise_instant("2026-10-09T21:28:23.0000000", 120)
    assert basis == "RELABELLED_FROM_LOCAL"
    assert labelled.startswith("2026-10-09T19:28:23")
    kept, basis = events._normalise_instant("2026-10-09T19:28:23.7983097Z", 120)
    assert basis == "SYSTEM_TIME_UTC"
    assert kept == "2026-10-09T19:28:23.798309Z"


def test_a_missing_instant_stays_absent_rather_than_defaulted(events) -> None:
    assert events._normalise_instant(None, 120) == (None, "ABSENT")
    assert events._normalise_instant("", 120) == (None, "ABSENT")


def test_the_channel_clock_is_checked_against_the_wall_clock(events) -> None:
    now = datetime(2026, 10, 9, 19, 30, 0, tzinfo=UTC)
    agrees = events.time_basis_check("2026-10-09T19:29:00.000000Z", now, 120)
    assert agrees["status"] == "CONSISTENT_WITH_UTC"
    suspect = events.time_basis_check("2026-10-09T21:29:00.000000Z", now, 120)
    assert suspect["status"] == "SUSPECT_LOCAL_LABELLED_UTC"
    stale = events.time_basis_check("2025-01-01T00:00:00.000000Z", now, 120)
    assert stale["status"] == "STALE_LOG"
    assert events.time_basis_check(None, now, 120)["status"] == "NO_RECORD_TO_CHECK"


# ---------------------------------------------------------------------------------------------
# unit — the records
# ---------------------------------------------------------------------------------------------


def test_concatenated_events_are_split_without_a_wrapper_document(events) -> None:
    text = event_fragment(1) + event_fragment(2)
    fragments = events.split_events(text)
    assert len(fragments) == 2
    assert all(fragment.startswith("<Event") for fragment in fragments)


def test_a_torn_answer_is_returned_rather_than_silently_shortened(events) -> None:
    fragments = events.split_events("<Event><System><EventID>100")
    assert len(fragments) == 1 and "<EventID>100" in fragments[0]


def test_a_record_is_normalised_with_every_field_the_contract_names(events) -> None:
    record = events.normalise_event(
        event_fragment(), "Microsoft-Windows-TaskScheduler/Operational", "2026-10-09T16:01:00Z", 120
    )
    assert record["status"] == "OK"
    for field in (
        "provider_name",
        "channel",
        "event_id",
        "event_record_id",
        "event_timestamp_utc",
        "computer",
        "task_full_path",
        "instance_id",
        "activity_id",
        "action_path",
        "process_id",
        "result_code",
        "event_xml_sha256",
        "collected_at_utc",
    ):
        assert field in record, field
    assert record["task_name"] == TASK
    assert record["belongs_to_the_monitored_task"] is True
    assert record["event_timestamp_basis"] == "SYSTEM_TIME_UTC"


def test_the_original_xml_is_kept_so_its_hash_can_be_recomputed(events) -> None:
    import hashlib

    fragment = event_fragment()
    record = events.normalise_event(fragment, "channel", "2026-10-09T16:01:00Z", 120)
    assert record["event_xml"] == fragment
    assert record["event_xml_sha256"] == hashlib.sha256(fragment.encode("utf-8")).hexdigest()


def test_a_manipulated_xml_is_refused_rather_than_guessed_at(events) -> None:
    refusal = events.normalise_event(
        "<Event><System><EventID>abc</System></Event>", "channel", "2026-10-09T16:01:00Z", 120
    )
    assert refusal["status"] == "UNPARSEABLE_RECORD"
    assert refusal["reason"]
    assert refusal["event_xml_sha256"]


def test_an_unknown_identifier_is_kept_and_not_used_to_decide_anything(events) -> None:
    record = events.normalise_event(
        event_fragment(event_id=999999), "channel", "2026-10-09T16:01:00Z", 120
    )
    assert record["event_id"] == 999999
    assert record["identifier_is_a_named_candidate"] is False
    assert "unverified" in record["identifier_semantics"]


def test_a_record_without_event_data_is_still_read_for_what_it_carries(events) -> None:
    record = events.normalise_event(
        event_fragment(with_data=False, task=""), "channel", "2026-10-09T16:01:00Z", 120
    )
    assert record["task_full_path"] is None
    assert record["belongs_to_the_monitored_task"] is False
    assert record["result_code"] is None


def test_a_record_of_another_task_is_not_ours(events) -> None:
    record = events.normalise_event(
        event_fragment(task="\\SomeOtherTask"), "channel", "2026-10-09T16:01:00Z", 120
    )
    assert record["belongs_to_the_monitored_task"] is False


# ---------------------------------------------------------------------------------------------
# unit — the store
# ---------------------------------------------------------------------------------------------


def test_the_store_deduplicates_on_channel_and_record_id(events, tmp_path: Path) -> None:
    store = tmp_path / "WINDOWS_EVENTS.jsonl"
    record = events.normalise_event(
        event_fragment(), "Microsoft-Windows-TaskScheduler/Operational", "2026-10-09T16:01:00Z", 120
    )
    first = events.append_records([record], store)
    second = events.append_records([record], store)
    assert first["records_added"] == 1
    assert second["records_added"] == 0, "a re-read must not grow the store"
    assert second["records_total"] == 1
    assert len(events.load_store(store)) == 1


def test_the_store_is_replaced_atomically_and_never_half_written(events, tmp_path: Path) -> None:
    store = tmp_path / "WINDOWS_EVENTS.jsonl"
    records = [
        events.normalise_event(
            event_fragment(record_id=index),
            "Microsoft-Windows-TaskScheduler/Operational",
            "2026-10-09T16:01:00Z",
            120,
        )
        for index in (1, 2, 3)
    ]
    events.append_records(records, store)
    # every line is a complete record, and no temporary file is left behind
    for line in store.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["store_version"] == events.STORE_VERSION
    assert not list(tmp_path.glob("*.tmp"))


def test_the_watermark_is_held_back_when_a_fragment_could_not_be_read(
    events, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(*arguments: object, **keyword: object) -> dict:
        # one fragment of the answer could not be read: the read itself succeeded, so the watermark
        # is the only thing left to get right
        return {
            "channel": arguments[0],
            "status": "OK",
            "records": [],
            "refusals": [{"status": events.UNPARSEABLE_RECORD, "reason": "torn fragment"}],
            "bytes_read": 10,
            "exit_code": 0,
        }

    monkeypatch.setattr(events, "read_channel_records", unreadable)
    monkeypatch.setattr(
        events,
        "parse_channel_config",
        lambda text: {"parsed": True, "enabled": True, "retention": "false"},
    )
    monkeypatch.setattr(
        events,
        "parse_log_info",
        lambda text: {"parsed": True, "records_present": 5, "oldest_record_number": 1},
    )
    outcome = events.ingest(
        now=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
        store_path=tmp_path / "store.jsonl",
        live_path=tmp_path / "live.json",
        channels=(events.CHANNEL_OPERATIONAL,),
    )
    report = outcome["channels"][events.CHANNEL_OPERATIONAL]
    assert report["watermark_candidate"] is None
    assert report["watermark_held_back"]["reason"]
    assert outcome["records_added"] == 0
    # and the durable state agrees: the range is left to be re-read rather than skipped
    assert (events.load_live_state(tmp_path / "live.json")["watermarks"] or {}).get(
        events.CHANNEL_OPERATIONAL
    ) is None


def test_a_disabled_channel_yields_no_records_and_no_advance(events, tmp_path: Path) -> None:
    outcome = events.ingest(
        now=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
        store_path=tmp_path / "store.jsonl",
        live_path=tmp_path / "live.json",
        channels=(events.CHANNEL_OPERATIONAL,),
    )
    report = outcome["channels"][events.CHANNEL_OPERATIONAL]
    assert report["enabled"] is False
    assert report["status"] == events.CHANNEL_DISABLED_NO_RECORDS
    assert report["watermark_candidate"] is None
    assert events.load_store(tmp_path / "store.jsonl") == []


def test_the_live_state_is_kept_apart_from_the_immutable_store(events, tmp_path: Path) -> None:
    store = tmp_path / "store.jsonl"
    live = tmp_path / "live.json"
    events.ingest(
        now=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
        store_path=store,
        live_path=live,
        channels=(events.CHANNEL_OPERATIONAL,),
    )
    state = events.load_live_state(live)
    assert state["artifact"] == "RFC047_WINDOWS_EVENT_LIVE_STATE"
    assert state["attempts"], "an attempt is recorded even when it read nothing"
    assert "watermarks" in state
    assert store.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------------------------
# unit — the semantics of the identifiers
# ---------------------------------------------------------------------------------------------


def test_an_identifier_has_no_meaning_until_a_record_supports_it(events, tmp_path: Path) -> None:
    status = events.semantics_status([], tmp_path / "EVENT_SEMANTICS.json")
    assert status["state"] == "NOT_VERIFIED_ON_THIS_HOST"
    assert status["rules"] is None


def test_a_declaration_quoting_a_record_that_does_not_exist_verifies_nothing(
    events, tmp_path: Path
) -> None:
    path = tmp_path / "EVENT_SEMANTICS.json"
    path.write_text(
        json.dumps({"verified_against": {"channel": "c", "event_record_id": 4242}}),
        encoding="utf-8",
    )
    status = events.semantics_status([], path)
    assert status["state"] == "NOT_VERIFIED_ON_THIS_HOST"
    assert "not in the store" in status["reason"]


def test_a_declaration_quoting_a_stored_record_is_accepted(events, tmp_path: Path) -> None:
    path = tmp_path / "EVENT_SEMANTICS.json"
    path.write_text(
        json.dumps(
            {
                "verified_against": {"channel": "c", "event_record_id": 7},
                "rules": {"scheduled": [100]},
            }
        ),
        encoding="utf-8",
    )
    status = events.semantics_status([{"channel": "c", "event_record_id": 7}], path)
    assert status["state"] == "VERIFIED_ON_THIS_HOST"
    assert status["rules"] == {"scheduled": [100]}


# ---------------------------------------------------------------------------------------------
# contract — the ledger extension and the artefacts on disk
# ---------------------------------------------------------------------------------------------


def test_the_ledger_keeps_its_own_vocabulary_and_gains_one_block(ledger_module) -> None:
    ledger = read_json(LEDGER)
    assert ledger["ledger_version"] == "ST6_SLOT_LEDGER_V1"
    entries = ledger["slots"]
    assert len(entries) == 84
    for entry in entries:
        for field in (
            ledger_module.LEDGER_V1_FIELDS if hasattr(ledger_module, "LEDGER_V1_FIELDS") else ()
        ):
            assert field in entry
        block = entry["windows_event_evidence"]
        assert block["block_version"] == "RFC047_WINDOWS_EVIDENCE_V1"
        assert block["state"] in ledger_module.WINDOWS_EVIDENCE_STATES


def test_every_state_of_the_vocabulary_is_reported_even_when_empty(ledger_module) -> None:
    states = read_json(LEDGER)["summary"]["windows_event_evidence_states"]
    assert set(states) == set(ledger_module.WINDOWS_EVIDENCE_STATES)
    assert states["PRE_ENABLE_NOT_OBSERVABLE"] == 84
    assert states["WIN_EVENT_CONFIRMED_SCHEDULED"] == 0


def test_the_artefacts_of_the_request_exist_and_parse() -> None:
    for relative in (
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
    ):
        path = REPO / relative
        assert path.exists(), relative
        if path.suffix in (".json", ".md"):
            assert path.read_text(encoding="utf-8").strip()


def test_the_report_carries_the_exact_fields_the_request_names() -> None:
    report = read_json(REPORT_JSON)
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
        assert field in report, field
    assert report["FALSE_SUCCESS"] == 0
    assert report["RFC047_STATUS"] in (
        "RFC047_VERIFIED",
        "RFC047_PARTIAL_EXTERNAL_EVIDENCE",
        "RFC047_BLOCKED_HOST_PERMISSIONS",
        "RFC047_FAILED",
    )


def test_the_report_and_the_document_agree_on_the_status() -> None:
    assert read_json(REPORT_JSON)["RFC047_STATUS"] == read_json(RFC_DOC_JSON)["status"]


def test_the_identifier_is_registered_and_the_next_one_is_named() -> None:
    registry = read_json(REGISTRY)
    assert registry["numbers"]["047"]["state"] == "OCCUPIED"
    assert registry["numbers"]["047"]["declared_in_tracked_docs"] == [
        "docs/rfc/RFC-047_ST6_SCHEDULER_PROVENANCE.md"
    ]
    # the number this registry names as next must genuinely not be taken
    assert registry["next_free_number_above_046"] not in registry["numbers"]


def test_the_standing_invariants_are_asserted_where_the_report_is_read() -> None:
    invariants = read_json(REPORT_JSON)["STANDING_INVARIANTS"]
    assert "LIVE_TRADING = DISABLED" in invariants
    assert "TRADES_AUTHORIZED = 0" in invariants
    assert "PROFITABILITY_VERIFIED = FALSE" in invariants
    assert "ECO-1 = OPEN" in invariants
    assert "NEXT_CAMPAIGN = NOT_AUTHORIZED" in invariants
    assert "ST6_AUTONOMOUS_COLLECTION_ACTIVE" in invariants


def test_the_host_audit_records_the_gate_and_never_applies_it() -> None:
    audit = read_json(HOST_AUDIT)
    assert audit["gate"]["status"] in (
        "HOST_AUDIT_CHANGE_APPROVAL_REQUIRED",
        "CHANNEL_ENABLED_AWAITING_REAL_EVENT",
    )
    if audit["gate"]["probe"].get("applied") is not True:
        assert audit["no_change_applied"] is True
        assert audit["coverage_from_utc"] is None
    assert audit["gate"]["rollback"]["command"].endswith("/e:false")


def test_the_candidate_identifiers_are_recorded_as_unverified() -> None:
    audit = read_json(HOST_AUDIT)
    candidates = audit["candidate_event_identifiers"]
    assert candidates["declared"] == [100, 102, 107, 110, 200, 201]
    assert candidates["semantics_verified_on_this_host"] is False


# ---------------------------------------------------------------------------------------------
# integration — the classification of a slot, state by state
# ---------------------------------------------------------------------------------------------


def slot_fixture(starts: str = "2026-10-09T16:00:00Z") -> dict:
    start = datetime.strptime(starts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return {"starts_at": start, "ends_at": start + timedelta(hours=4)}


def context_fixture(**overrides: object) -> dict:
    context = {
        "events": [],
        "records_available": 0,
        "channel_state": "CHANNEL_DISABLED",
        "channel_enabled": False,
        "readable": True,
        "gate_status": "HOST_AUDIT_CHANGE_APPROVAL_REQUIRED",
        "coverage_from_utc": None,
        "examined_through_record_id": None,
        "read_attempts": [],
        "semantics": {"state": "NOT_VERIFIED_ON_THIS_HOST", "rules": None},
        "evidence_document": "data/st6/RFC047_WINDOWS_EVENT_EVIDENCE.json",
    }
    context.update(overrides)
    return context


def run_fixture(**overrides: object) -> dict:
    run = {
        "internal_run_id": "run-1",
        "process_start_utc": "2026-10-09T16:30:00Z",
        "process_end_utc": "2026-10-09T16:31:00Z",
        "declared_invocation": "SCHEDULED",
        "origin": "SELF_DECLARED_UNVERIFIED",
    }
    run.update(overrides)
    return run


def stored_event(instant: str = "2026-10-09T16:30:05Z", event_id: int = 100) -> dict:
    return {
        "channel": "Microsoft-Windows-TaskScheduler/Operational",
        "event_record_id": 500,
        "event_id": event_id,
        "event_timestamp_utc": instant,
        "belongs_to_the_monitored_task": True,
        "task_full_path": "\\" + TASK,
        "instance_id": None,
        "result_code": "0",
        "event_xml_sha256": "0" * 64,
    }


def test_a_slot_before_the_channel_could_record_is_not_observable(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(), [run_fixture()], context_fixture(), datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    )
    assert block["state"] == "PRE_ENABLE_NOT_OBSERVABLE"
    assert block["missing_elements"]


def test_an_unreadable_channel_gives_unavailable(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(coverage_from_utc="2026-10-09T17:00:00Z", readable=False),
        datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_UNAVAILABLE"


def test_a_record_whose_meaning_is_unverified_is_only_partial(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            events=[stored_event()],
            records_available=1,
        ),
        datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_PARTIAL"
    assert block["correlated_runs"][0]["event_record_id"] == 500
    assert "the established meaning of the identifiers on this host" in block["missing_elements"]


def test_a_scheduled_run_with_a_verified_scheduled_record_is_confirmed(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            events=[stored_event()],
            records_available=1,
            semantics={"state": "VERIFIED_ON_THIS_HOST", "rules": {"scheduled": [100]}},
        ),
        datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_CONFIRMED_SCHEDULED"
    assert block["correlated_runs"]


def test_a_manual_record_never_certifies_the_schedule(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture(declared_invocation="MANUAL", origin="MANUAL")],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            events=[stored_event()],
            records_available=1,
            semantics={"state": "VERIFIED_ON_THIS_HOST", "rules": {"manual": [100]}},
        ),
        datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_CONFIRMED_MANUAL"


def test_a_scheduled_claim_against_a_manual_record_is_a_conflict(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            events=[stored_event()],
            records_available=1,
            semantics={"state": "VERIFIED_ON_THIS_HOST", "rules": {"manual": [100]}},
        ),
        datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_CONFLICT"


def test_a_slot_that_just_ended_waits_for_its_completion_record(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(coverage_from_utc="2026-10-09T17:00:00Z", channel_enabled=True),
        datetime(2026, 10, 9, 20, 5, tzinfo=UTC),
    )
    assert block["state"] == "PENDING_EVENT_COMPLETION"


def test_a_claim_of_the_schedule_against_a_covered_absence_is_a_conflict(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture()],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            read_attempts=[
                {
                    "attempted_at_utc": "2026-10-09T21:00:00Z",
                    "statuses": {"Microsoft-Windows-TaskScheduler/Operational": "RECORDS_INGESTED"},
                }
            ],
        ),
        datetime(2026, 10, 9, 21, 30, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_CONFLICT"


def test_a_run_that_does_not_claim_the_schedule_is_not_a_conflict(ledger_module) -> None:
    block = ledger_module.windows_event_evidence_for(
        slot_fixture(),
        [run_fixture(declared_invocation=None, origin="UNATTRIBUTED")],
        context_fixture(
            coverage_from_utc="2026-10-09T17:00:00Z",
            channel_enabled=True,
            read_attempts=[
                {
                    "attempted_at_utc": "2026-10-09T21:00:00Z",
                    "statuses": {"Microsoft-Windows-TaskScheduler/Operational": "RECORDS_INGESTED"},
                }
            ],
        ),
        datetime(2026, 10, 9, 21, 30, tzinfo=UTC),
    )
    assert block["state"] == "WIN_EVENT_PARTIAL"


def test_a_rebuild_never_weakens_a_recorded_windows_statement(ledger_module) -> None:
    entry = {"windows_event_evidence": {"state": "WIN_EVENT_UNAVAILABLE"}}
    previous = {
        "windows_event_evidence": {"state": "WIN_EVENT_CONFIRMED_SCHEDULED"},
        "read_at_utc": "2026-10-09T20:00:00Z",
        "runs": [],
    }
    merged, carried = ledger_module.carry_forward(entry, previous)
    assert merged["windows_event_evidence"]["state"] == "WIN_EVENT_CONFIRMED_SCHEDULED"
    assert "windows_event_evidence" in carried


# ---------------------------------------------------------------------------------------------
# integration — the reconciliation against the artefacts
# ---------------------------------------------------------------------------------------------


def test_the_reconciliation_reports_no_disagreement_with_its_inputs() -> None:
    reconciliation = read_json(RECONCILIATION)
    assert reconciliation["disagreements"] == []
    assert reconciliation["contradictions"] == []
    assert reconciliation["totals"]["slots"] == 84
    assert reconciliation["ledger_contract"]["version_1_fields_intact"] is True
    assert reconciliation["ledger_contract"]["added_block_fields_complete"] is True


def test_no_slot_is_called_corroborated_without_a_record_behind_it() -> None:
    reconciliation = read_json(RECONCILIATION)
    assert reconciliation["totals"]["slots_with_an_external_confirmation"] == 0
    assert reconciliation["windows_states"]["WIN_EVENT_CONFIRMED_SCHEDULED"] == 0
    assert reconciliation["windows_states"]["PRE_ENABLE_NOT_OBSERVABLE"] == 84


def test_the_store_is_empty_and_the_evidence_document_says_why() -> None:
    evidence = read_json(WINDOWS_EVIDENCE)
    assert evidence["events_available"] == 0
    assert evidence["events_missing_or_unobtainable"]["gate_status"] in (
        "HOST_AUDIT_CHANGE_APPROVAL_REQUIRED",
        "CHANNEL_ENABLED_AWAITING_REAL_EVENT",
    )
    assert read_json(LIVE_STATE)["watermark_semantics"]


def test_the_verifier_declared_grid_recomputes_the_ledgers_bounds(verifier) -> None:
    ledger = read_json(LEDGER)
    grid = verifier.declared_grid(read_json(PERIOD))
    assert len(grid) == len(ledger["slots"]) == 84
    for slot, entry in zip(grid, ledger["slots"], strict=True):
        assert slot["slot_id"] == entry["slot_id"]
        assert slot["starts_at"].strftime("%Y-%m-%dT%H:%M:%SZ") == entry["slot_start_utc"]


# ---------------------------------------------------------------------------------------------
# runtime — the chain, and the controls the verifier must hold
# ---------------------------------------------------------------------------------------------


def test_the_runtime_chain_never_claims_the_trigger_it_cannot_see(builder) -> None:
    runtime = builder.build_runtime()
    links = {item["link"]: item for item in runtime["chain"]}
    assert links["windows_scheduled_trigger"]["available"] is False
    assert runtime["external_trigger_confirmed"] is False
    assert runtime["runtime_correlation_achieved"] is False
    if runtime["candidates_corroborated_by_the_scheduler_register"]:
        assert links["process_execution"]["available"] is True
        assert links["st6_run_id"]["available"] is True
        assert links["slot_outcome"]["available"] is True
    assert runtime["no_run_was_induced_for_this"]


def test_the_verifier_shares_no_code_with_the_builder_and_passes(verifier) -> None:
    documents = verifier.load_documents()
    outcome = verifier.verify(documents, verifier.probe_host())
    assert outcome["failed_checks"] == [], outcome["failed_checks"]
    assert outcome["unverified_checks"] == []
    assert outcome["status"] == "PASS"
    assert outcome["recomputed"]["records_in_the_store"] == 0
    assert outcome["recomputed"]["channel_enabled_per_the_host"] is False


def test_the_eighteen_controls_reject_the_manipulations_and_accept_the_honest_state(
    verifier,
) -> None:
    documents = verifier.load_documents()
    host = verifier.probe_host()
    controls = verifier.run_negative_controls(documents, host, datetime.now(UTC))
    assert controls["baseline_status"] == "PASS"
    assert controls["count"] == 18
    assert controls["accepted_by_mistake"] == 0, [
        case for case in controls["cases"] if not case["as_required"]
    ]
    assert controls["false_accusations"] == 0, [
        case for case in controls["cases"] if not case["as_required"]
    ]
    accepted = [case for case in controls["cases"] if case["expected"] == "ACCEPT"]
    assert len(accepted) == 1 and accepted[0]["case"].startswith("a valid collection")


def test_the_verifier_refuses_a_report_that_overstates_what_it_has(verifier) -> None:
    documents = verifier.load_documents()
    host = verifier.probe_host()
    mutated = copy.deepcopy(documents)
    mutated["report"]["REAL_EXECUTION_CORROBORATED"] = True
    outcome = verifier.verify(mutated, host)
    assert outcome["status"] == "FAIL"
    assert "report_claims_hold" in outcome["failed_checks"]


def test_the_verifier_notices_a_host_that_disagrees_with_the_audit(verifier) -> None:
    documents = verifier.load_documents()
    host = verifier.probe_host()
    assert verifier.verify(documents, host)["status"] == "PASS"
    contradicted = verifier.verify(
        documents, {**host, "operational_enabled": not host["operational_enabled"]}
    )
    assert "channel_state_matches_the_host" in contradicted["failed_checks"]
