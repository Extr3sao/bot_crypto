"""Tests for the ST-6 autonomous observation layer.

The layer exists so that fourteen days of declared sampling happen without an operator, so the tests
that matter are the ones about *restraint*: one measurement per slot, nothing at all when nothing is
due, a second writer refusing to run, a missed slot written down instead of invented, a non-zero
status when a tick cannot do its job, and a period that closes instead of extending.

The live tests here are deliberately cheap and idempotent: they run the unattended tick in the slot
the host is already in, where the scheduler would have run it anyway.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "st6"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
RUN_LOG = DATA / "ST6_RUNS.jsonl"
MISSED_LOG = DATA / "ST6_MISSED_WINDOWS.jsonl"
CLOSURE = DATA / "ST6_PERIOD_CLOSURE.json"
HEALTH_STATUS = DATA / "ST6_HEALTH_STATUS.json"
SCHEDULER_REPORT = DATA / "ST6_SCHEDULER_REPORT.json"
SCHEDULER_VERIFICATION = DATA / "ST6_SCHEDULER_VERIFICATION.json"
TASK_XML = DATA / "ST6_TASK_DEFINITION.xml"
TICK = REPO / "scripts" / "st6_forward_regime.py"
HEALTH_SCRIPT = REPO / "scripts" / "st6_health_check.py"
SCHEDULER_VERIFIER = REPO / "scripts" / "st6_scheduler_verify.py"
#: The interpreter that runs these tests is the interpreter the tick must be exercised with.
#: It used to be spelled ``REPO/.venv/Scripts/python.exe``, which only exists on Windows and only
#: after someone has synced this particular checkout: in a fresh clone the subprocess raised
#: ``FileNotFoundError`` before the tick could refuse anything, and the failure said nothing about
#: the layer under test.
PYTHON = Path(sys.executable)
TASK_NAME = "TradingAgentic-ST6-Forward"

RUN_EVENT_FIELDS = (
    "run_id",
    "scheduled_slot_utc",
    "slot_key",
    "actual_start_utc",
    "actual_end_utc",
    "result",
    "market_requests",
    "data_freshness",
    "raw_evidence_hash",
    "verifier_status",
    "errors",
    "exit_code",
)
RESULT_EXIT_CODES = {
    "COLLECTED": 0,
    "SKIPPED_NO_WINDOW_DUE": 0,
    "ALREADY_RUNNING": 2,
    "PERIOD_ENDED_CONSOLIDATED": 3,
    "COLLECTION_INCOMPLETE": 4,
    "REFUSED_INVALID_ARGUMENTS": 1,
    "REPORT_ONLY": 0,
    # the token the first report-only invocations carried, kept so the append-only log stays
    # readable instead of being rewritten to look tidier
    "UNKNOWN": 0,
}
ROLLUP_KEYS = (
    "by_asset",
    "by_session",
    "by_volatility_regime",
    "checks",
    "day_detail",
    "model_comparison",
    "coverage",
    "statistics",
)


def load_module(name: str, relative: str) -> object:
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@pytest.fixture(scope="module")
def tick() -> object:
    return load_module("st6_tick", "scripts/st6_forward_regime.py")


@pytest.fixture(scope="module")
def health() -> object:
    return load_module("st6_health", "scripts/st6_health_check.py")


@pytest.fixture(scope="module")
def scheduler_verifier() -> object:
    return load_module("st6_scheduler_verifier", "scripts/st6_scheduler_verify.py")


def run_tick(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), str(TICK), *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )


def run_tick_in_an_isolated_lease_root(root: Path, *extra: str) -> subprocess.CompletedProcess:
    """The same tick, with its single-instance lease redirected away from the campaign's.

    A test that has to hold the lease in order to be refused must not hold the one the installed
    task uses: the real schedule wakes every fifteen minutes, and blocking it would make a test the
    cause of a refused tick.  The root is passed to the child as well, so both writers contend for
    the same private lock and the campaign's is never taken nor contended for.
    """
    return subprocess.run(
        [str(PYTHON), str(TICK), *extra],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "ST6_LOCK_ROOT": str(root)},
    )


LEASE = DATA / "scheduler_lock" / "CAMPAIGN_LOCK.json"


def wait_for_a_free_lease(timeout_seconds: int = 300) -> None:
    """The Windows task holds the lease while it collects, and it wakes every fifteen minutes.

    A collision with the schedule is not the behaviour these tests are about, so they wait for the
    scheduler to finish rather than racing it.  The wait is bounded, and a lease that never frees
    is raised as a failure — a stuck lease is a real defect, not something to skip past.
    """
    deadline = time.monotonic() + timeout_seconds
    while LEASE.exists():
        try:
            holder = json.loads(LEASE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            holder = None
        if holder is None:
            return
        age = int(datetime.now(UTC).timestamp()) - int(holder.get("renewed_at", 0))
        if age > int(holder.get("stale_after_seconds", 0)):
            return  # stale: the tick itself reclaims it, which is what the lease is for
        if time.monotonic() > deadline:
            raise AssertionError(
                f"{holder.get('campaign_id')} lease held by pid {holder.get('pid')} for more than "
                f"{timeout_seconds} s without being renewed or released: {holder}"
            )
        time.sleep(5)


def run_tick_without_a_collision(*extra: str) -> subprocess.CompletedProcess:
    """The same as ``run_tick``, except that a scheduled tick is waited out rather than raced."""
    completed = run_tick(*extra)
    for _ in range(2):
        if completed.returncode != 2:
            return completed
        wait_for_a_free_lease()
        completed = run_tick(*extra)
    raise AssertionError(
        "the scheduled tick took the lease twice while this test waited: LIVE_TICK_CONTENTION, "
        f"last run said {completed.stdout.strip()[:200]!r}"
    )


# ------------------------------------------------------------------ registration and definition


def test_the_task_definition_matches_the_repository_and_the_host() -> None:
    assert TASK_XML.exists(), "the task definition is not even committed"
    root = ElementTree.fromstring(TASK_XML.read_text(encoding="utf-16").lstrip("\ufeff"))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    action = root.find("t:Actions/t:Exec", ns)
    assert action is not None
    command = action.findtext("t:Command", default="", namespaces=ns)
    arguments = action.findtext("t:Arguments", default="", namespaces=ns)
    working_directory = action.findtext("t:WorkingDirectory", default="", namespaces=ns)
    assert Path(command).name.lower() == "python.exe"
    assert str(REPO).lower() in command.lower()
    assert "--due" in arguments and "--scheduled" in arguments
    assert str(TICK) in arguments
    assert Path(working_directory) == REPO
    settings = root.find("t:Settings", ns)
    assert settings is not None
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert settings.findtext("t:ExecutionTimeLimit", namespaces=ns) == "PT1H"
    assert settings.findtext("t:StartWhenAvailable", namespaces=ns) == "true"
    assert (
        root.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns) == "PT15M"
    )
    # and the host agrees with the committed definition
    queried = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/xml"], capture_output=True, text=True
    )
    if queried.returncode != 0:
        pytest.skip("this host cannot query the task (running outside Windows Task Scheduler)")
    live = ElementTree.fromstring(queried.stdout.lstrip("\ufeff"))
    live_action = live.find("t:Actions/t:Exec", ns)
    assert live_action is not None
    assert live_action.findtext("t:Arguments", default="", namespaces=ns) == arguments
    assert (
        live_action.findtext("t:WorkingDirectory", default="", namespaces=ns) == working_directory
    )


def test_the_task_cannot_carry_a_credential() -> None:
    source = TASK_XML.read_text(encoding="utf-16")
    for token in ("password", "Password", "secret", "api_key", "apikey", "token"):
        assert token not in source, token
    assert "LogonType>InteractiveToken" in source  # the signed-in user, never a stored password


# ------------------------------------------------------------------ the run log and its restraint


def test_the_run_log_is_compact_self_consistent_and_unique() -> None:
    if not RUN_LOG.exists():
        # The log is host runtime evidence, written by the tick and never versioned. In a fresh
        # clone there is nothing to inspect, and whether this host has ever ticked is not a
        # property of the repository — asserting "it has ticked" there made the test depend on
        # another test in the same session having run a tick first.
        pytest.skip(
            "no ST-6 run log in this checkout: it is produced by scripts/st6_forward_regime.py "
            "--due/--collect on this host and is not versioned"
        )
    runs = read_jsonl(RUN_LOG)
    assert runs, "the run log exists but is empty"
    ids = [run["run_id"] for run in runs]
    assert len(set(ids)) == len(ids)
    for run in runs:
        assert set(RUN_EVENT_FIELDS).issubset(run), sorted(set(RUN_EVENT_FIELDS) - set(run))
        for key in ROLLUP_KEYS:
            assert key not in run, f"{key} is a rollup duplicated inside an event"
        expected = RESULT_EXIT_CODES[run["result"]]
        assert run["exit_code"] == expected, (run["result"], run["exit_code"], expected)
        assert run["actual_end_utc"] >= run["actual_start_utc"]
        if run["result"] == "SKIPPED_NO_WINDOW_DUE":
            assert run["market_requests"] == 0, run


def test_no_slot_was_ever_measured_twice() -> None:
    windows = read_jsonl(WINDOWS)
    keys = [f"{row['day']}#{row['slot_index']}" for row in windows]
    assert len(set(keys)) == len(keys), keys
    collected = [run for run in read_jsonl(RUN_LOG) if run["result"] == "COLLECTED"]
    slots = [run["slot_key"] for run in collected]
    assert len(set(slots)) == len(slots), slots


def test_every_ended_slot_is_accounted_for_and_nothing_is_reconstructed(tick: object) -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    windows = read_jsonl(WINDOWS)
    missed = read_jsonl(MISSED_LOG)
    now = datetime.now(UTC)
    observed = {f"{row['day']}#{row['slot_index']}" for row in windows}
    recorded = {row["slot_key"] for row in missed}
    ended = [
        entry
        for entry in tick.declared_slots_upto(period, now)
        if tick._parse(entry["ends_at_utc"]) <= now
    ]
    for entry in ended:
        assert entry["key"] in observed or entry["key"] in recorded, entry["key"]
    for row in missed:
        assert row["status"] == "MISSED_WINDOW"
        assert row["reconstructed"] is False
        assert row["reason"]
        assert row["slot_key"] not in observed


def test_a_lost_slot_is_written_down_and_never_invented(tick: object, tmp_path: Path) -> None:
    """The rule that matters on a host that sleeps: a slot that passed with no tick is a loss."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tick, "MISSED_LOG", tmp_path / "missed.jsonl")
    monkeypatch.setattr(tick, "RUN_LOG", tmp_path / "runs.jsonl")
    try:
        lost = {
            "artifact": "ST6_OBSERVATION_PERIOD",
            "started_at_utc": "2026-09-01T00:00:00Z",
            "ends_at_utc": "2026-09-03T00:00:00Z",
            # the declared plan is part of the period contract: two days of six slots, twelve windows
            "period_days": 2,
            "slots_per_day": 6,
        }
        recorded = tick.sync_missed_windows(lost, [], datetime(2026, 9, 3, 1, 0, tzinfo=UTC))
        assert recorded, "a lost slot was not recorded at all"
        assert all(entry["status"] == "MISSED_WINDOW" for entry in recorded)
        assert all(entry["reconstructed"] is False for entry in recorded)
        # the reason is no longer a generic sentence: the run log here is empty, so the honest
        # answer is not "no run collected this slot" but "the evidence cannot speak for it"
        assert all(
            entry["attendance"]["classification"] == "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"
            for entry in recorded
        )
        assert all(
            entry["reason"].startswith("ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED") for entry in recorded
        )
        assert all(entry["attendance"]["basis"] for entry in recorded)
        assert all(entry["attendance"]["policy"] for entry in recorded)
        assert all(entry["attendance"]["evidence_lifetime"] for entry in recorded)
        # the slots the window covers are the declared grid, not an invented one
        assert {entry["slot"] for entry in recorded} == {
            "00:00-04:00 UTC",
            "04:00-08:00 UTC",
            "08:00-12:00 UTC",
            "12:00-16:00 UTC",
            "16:00-20:00 UTC",
            "20:00-24:00 UTC",
        }
        # a second pass is idempotent: nothing is recorded twice
        again = tick.sync_missed_windows(lost, [], datetime(2026, 9, 3, 1, 0, tzinfo=UTC))
        assert again == []
        # and a slot that was observed is not called a loss
        observed = [{"day": "2026-09-01", "slot_index": 1}]
        fresh = tick.sync_missed_windows(lost, observed, datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
        assert fresh == []
    finally:
        monkeypatch.undo()


def complete_coverage(launches: int = 0) -> dict:
    """An external record that covers a slot whole, naming this many scheduler launches inside it."""
    return {
        "status": "EXTERNAL_COVERAGE_COMPLETE",
        "external_samples_in_slot": 60,
        "scheduler_engine_launch_count": launches,
        "scheduler_engine_launches_reported_in_slot": [f"launch-{index}" for index in range(launches)],
        "reading": "the witness covered the slot",
    }


def test_the_attendance_of_a_lost_slot_is_proven_rather_than_assumed(tick: object) -> None:
    """A slot nobody attended and a slot the tick visited without measuring are different losses.

    The two sources carry different weights, and the tests below are the two halves of that: the
    tick's own log can prove that a run happened, and it can never prove that none did.  An absence
    is therefore reachable only through the external record — and where the two disagree the slot is
    carried as a conflict, because one of them is wrong and this program may not choose which.
    """
    slot = {
        "key": "2026-09-02#2",
        "starts_at_utc": "2026-09-02T08:00:00Z",
        "ends_at_utc": "2026-09-02T12:00:00Z",
    }
    earlier = {
        "slot_key": "2026-09-02#1",
        "actual_start_utc": "2026-09-02T06:30:00Z",
        "invocation": "SCHEDULED",
        "result": "SKIPPED_NO_WINDOW_DUE",
        "market_requests": 0,
        "errors": None,
    }
    quiet = {
        **earlier,
        "slot_key": slot["key"],
        "actual_start_utc": "2026-09-02T08:30:00Z",
        "result": "SKIPPED_DATA_STALE",
    }
    failing = {**quiet, "market_requests": 4, "errors": "the exchange refused the request"}
    by_hand = {**quiet, "invocation": "MANUAL"}
    later = {**earlier, "slot_key": "2026-09-02#3", "actual_start_utc": "2026-09-02T12:10:00Z"}

    # the run log is silent about the slot and reaches back past it — but the run log is written by
    # the tick, so its silence is not evidence: without external coverage the class is UNKNOWN
    quiet_log = tick.slot_attendance([earlier], slot)
    assert quiet_log["classification"] == "ATTENDANCE_UNKNOWN"
    assert quiet_log["log_covers_whole_slot"] is True
    assert quiet_log["scheduled_runs_in_slot"] == 0
    assert quiet_log["external_evidence_status"] == "SCHEDULER_EVIDENCE_UNAVAILABLE"
    assert "not proof that nothing ran" in quiet_log["basis"]

    # with the external record covering the whole slot and naming no run, the absence is carried
    unattended = tick.slot_attendance([earlier], slot, complete_coverage(0))
    assert unattended["classification"] == "UNATTENDED_NO_RUN_EVENT"
    assert unattended["absence_requires_external_coverage"] is True
    assert "covers every instant of the slot" in unattended["basis"]

    # the external record names a run the log knows nothing about: the two contradict each other
    conflicting = tick.slot_attendance([earlier], slot, complete_coverage(3))
    assert conflicting["classification"] == "ATTENDANCE_EVIDENCE_CONFLICT"
    assert conflicting["conflict"]["internal_claim"]
    assert conflicting["conflict"]["external_claim"]

    # the other direction: the log declares a tick the scheduler's own record never named
    undeclared = tick.slot_attendance([earlier, quiet], slot, complete_coverage(0))
    assert undeclared["classification"] == "ATTENDANCE_EVIDENCE_CONFLICT"

    attended = tick.slot_attendance([earlier, quiet], slot)
    assert attended["classification"] == "ATTENDED_NOT_COLLECTED"
    assert attended["scheduled_runs_in_slot"] == 1
    assert attended["results_in_slot"] == {"SKIPPED_DATA_STALE": 1}
    # and a corroborated launch agrees with the log instead of contradicting it
    corroborated = tick.slot_attendance([earlier, quiet], slot, complete_coverage(1))
    assert corroborated["classification"] == "ATTENDED_NOT_COLLECTED"

    refused = tick.slot_attendance([earlier, failing], slot)
    assert refused["classification"] == "ATTENDED_REQUEST_FAILED"
    assert refused["market_requests_in_slot"] == 4
    assert refused["last_error_in_slot"] == "the exchange refused the request"

    # a run that declares itself manual is not the schedule: a slot only visited by hand still went
    # unattended, and the record says so instead of counting the visit as attendance
    only_by_hand = tick.slot_attendance([earlier, by_hand], slot)
    assert only_by_hand["classification"] == "ATTENDANCE_UNKNOWN"
    assert only_by_hand["manual_runs_in_slot"] == 1
    assert only_by_hand["scheduled_runs_in_slot"] == 0
    # a manual visit is not the schedule even when the external record covers the slot
    still_by_hand = tick.slot_attendance([earlier, by_hand], slot, complete_coverage(0))
    assert still_by_hand["classification"] == "UNATTENDED_NO_RUN_EVENT"
    assert still_by_hand["manual_runs_in_slot"] == 1

    # the log is bounded: once its oldest retained event starts after this slot began, the absence of
    # an event can no longer be told apart from one that was pruned, and nothing is claimed
    truncated = tick.slot_attendance([later], slot)
    assert truncated["classification"] == "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED"
    assert truncated["log_covers_whole_slot"] is False
    assert "cannot speak for" in truncated["basis"]

    # a corrupt counter must not stop the accounting: it is read as unreadable, never as a crash
    corrupt = tick.slot_attendance([earlier, {**quiet, "market_requests": "many"}], slot)
    assert corrupt["market_requests_in_slot"] == 0
    assert corrupt["classification"] == "ATTENDED_NOT_COLLECTED"


def test_the_health_check_audits_the_stated_cause_of_a_missed_slot(health: object) -> None:
    """The record's cause is re-derived from the run events: the checker must be able to disagree."""
    period = {
        "started_at_utc": "2026-09-01T00:00:00Z",
        "ends_at_utc": "2026-09-02T00:00:00Z",
        "period_days": 1,
        "slots_per_day": 6,
    }
    slot_key = "2026-09-01#1"  # 04:00 -> 08:00 UTC
    earlier = {
        "slot_key": "2026-09-01#0",
        "actual_start_utc": "2026-09-01T03:50:00Z",
        "invocation": "SCHEDULED",
        "market_requests": 0,
        "errors": None,
    }
    inside = {
        **earlier,
        "slot_key": slot_key,
        "actual_start_utc": "2026-09-01T04:30:00Z",
    }
    bounds = {"starts_at_utc": "2026-09-01T04:00:00Z", "ends_at_utc": "2026-09-01T08:00:00Z"}
    attendance = {
        "classification": "ATTENDED_NOT_COLLECTED",
        "scheduled_runs_in_slot": 1,
        "manual_runs_in_slot": 0,
        "market_requests_in_slot": 0,
        "log_covers_whole_slot": True,
    }
    honest = {"slot_key": slot_key, **bounds, "attendance": dict(attendance)}

    clean = health.audit_missed_attendance(period, [honest], [earlier, inside], [], None)
    assert clean["unsupported"] == []
    assert clean["by_classification"] == {"ATTENDED_NOT_COLLECTED": 1}

    lying = {
        **honest,
        "attendance": {
            **attendance,
            "classification": "UNATTENDED_NO_RUN_EVENT",
            "scheduled_runs_in_slot": 0,
        },
    }
    caught = health.audit_missed_attendance(period, [lying], [earlier, inside], [], None)
    assert caught["unsupported"], "a record that blames the schedule was not caught"
    assert any("while the run log says" in finding for finding in caught["unsupported"])

    bare = health.audit_missed_attendance(
        period, [{"slot_key": slot_key, **bounds}], [earlier], [], None
    )
    assert bare["unsupported"] and "no attendance evidence" in bare["unsupported"][0]

    unsupported_class = {
        **honest,
        "attendance": {**attendance, "classification": "NOT_A_DECLARED_CAUSE"},
    }
    assert health.audit_missed_attendance(period, [unsupported_class], [earlier], [], None)[
        "unsupported"
    ]

    wrong_bounds = {**honest, "ends_at_utc": "2026-09-01T09:00:00Z"}
    drifted = health.audit_missed_attendance(period, [wrong_bounds], [earlier, inside], [], None)
    assert any("not the declared ones" in finding for finding in drifted["unsupported"])

    # an absence is the heavy claim: with no external record covering the slot, the checker must
    # refuse it — the tick's own log can never prove that nothing ran
    silenced = {
        **honest,
        "attendance": {
            **attendance,
            "classification": "UNATTENDED_NO_RUN_EVENT",
            "scheduled_runs_in_slot": 0,
        },
    }
    without_coverage = health.audit_missed_attendance(period, [silenced], [earlier], [], None)
    assert without_coverage["unsupported"], "an absence claim without external coverage passed"
    assert without_coverage["unattended_slots"] == []

    # the same slot, with a witness that sampled it throughout and named no launch: now the class
    # is the record's own, and the checker agrees with it
    def covering_samples() -> list[dict]:
        start = datetime(2026, 9, 1, 3, 59, tzinfo=UTC)
        rows = []
        for step in range(0, 25):
            moment = start + timedelta(minutes=10 * step)
            rows.append(
                {
                    "sample_id": f"fixture-{moment.strftime('%H%M')}",
                    "sampled_at_utc": moment.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "scheduler_reported_last_run_utc": None,
                }
            )
        return rows

    supported = {
        **silenced,
        "attendance": {
            **silenced["attendance"],
            "external_evidence_status": "EXTERNAL_COVERAGE_COMPLETE",
            "external_evidence": {
                "status": "EXTERNAL_COVERAGE_COMPLETE",
                "scheduler_engine_launch_count": 0,
            },
        },
    }
    audited = health.audit_missed_attendance(
        period,
        [supported],
        [earlier],
        covering_samples(),
        None,
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    assert audited["unsupported"] == [], audited["unsupported"]
    assert audited["unattended_slots"] == [slot_key]
    # and the same coverage that names a run turns the claim into a conflict, not a verdict
    conflicting = health.audit_missed_attendance(
        period,
        [supported],
        [earlier],
        [
            *covering_samples(),
            {
                "sample_id": "fixture-launch",
                "sampled_at_utc": "2026-09-01T05:00:00.000Z",
                "scheduler_reported_last_run_utc": "2026-09-01T04:30:00Z",
            },
        ],
        None,
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    assert conflicting["unsupported"], "a slot the scheduler ran was accepted as unattended"

    unprovable = {
        **honest,
        "attendance": {
            **attendance,
            "classification": "ATTENDANCE_UNKNOWN_RUN_LOG_TRUNCATED",
            "scheduled_runs_in_slot": 0,
            "log_covers_whole_slot": False,
        },
    }
    pruned = health.audit_missed_attendance(
        period,
        [unprovable],
        [{**earlier, "slot_key": "2026-09-01#2", "actual_start_utc": "2026-09-01T09:00:00Z"}],
        [],
        None,
    )
    assert pruned["unsupported"] == []
    assert pruned["unknown_slots"] == [slot_key]
    assert pruned["unattended_slots"] == []
    assert pruned["policy_version"] == 2


def test_an_observed_slot_costs_nothing_to_re_tick() -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    slot_index = now.hour // 4
    today = now.strftime("%Y-%m-%d")
    observed = {f"{row['day']}#{row['slot_index']}" for row in read_jsonl(WINDOWS)}
    if f"{today}#{slot_index}" not in observed:
        pytest.skip(
            "this slot has no window yet: the tick would have to collect and this test is not a sampler"
        )
    before = len(read_jsonl(WINDOWS))
    first = run_tick_without_a_collision("--due", "--scheduled")
    second = run_tick_without_a_collision("--due", "--scheduled")
    after = len(read_jsonl(WINDOWS))
    assert first.returncode == 0 and second.returncode == 0
    assert after == before, "a tick in an already observed slot collected another window"
    tails = read_jsonl(RUN_LOG)[-2:]
    assert all(event["result"] == "SKIPPED_NO_WINDOW_DUE" for event in tails)
    assert all(event["market_requests"] == 0 for event in tails)
    assert period["period_days"] == 14


def test_a_second_writer_refuses_and_makes_no_market_request(
    tick: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusal is proven in a private lock root: the test is never the campaign's blocking writer."""
    isolated = tmp_path / "scheduler_lock"
    monkeypatch.setattr(tick, "LOCK_ROOT", isolated)
    lease = tick.run_lease()
    acquired = lease.acquire(now=int(datetime.now(UTC).timestamp()))
    assert acquired["acquired"] is True, acquired
    assert (isolated / "CAMPAIGN_LOCK.json").exists(), "the held lease is not the isolated one"
    try:
        # launched by this test, not by the schedule: the event it leaves must not declare itself
        # the schedule's own tick, so the second writer carries no --scheduled flag
        result = run_tick_in_an_isolated_lease_root(isolated, "--due")
    finally:
        lease.release()
    assert result.returncode == 2
    refusals = [run for run in read_jsonl(RUN_LOG) if run["result"] == "ALREADY_RUNNING"]
    assert refusals, "the refusal left no trace in the run log"
    assert refusals[-1]["market_requests"] == 0
    assert refusals[-1]["errors"]
    assert refusals[-1]["invocation"].upper() != "SCHEDULED"


def test_the_lease_root_is_the_campaign_s_unless_a_test_asks_for_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The installed task must keep using the campaign's lock; an isolated root must be opt-in.

    This is what lets a test hold a lease without becoming the writer the real schedule contends
    with: if the opt-in silently stopped working, the test suite would start refusing real ticks
    again, and it would do so invisibly.
    """
    default = load_module("st6_tick_default_root", "scripts/st6_forward_regime.py")
    assert Path(default.LOCK_ROOT) == DATA / "scheduler_lock", default.LOCK_ROOT
    monkeypatch.setenv("ST6_LOCK_ROOT", str(tmp_path / "isolated"))
    isolated = load_module("st6_tick_isolated_root", "scripts/st6_forward_regime.py")
    assert Path(isolated.LOCK_ROOT) == tmp_path / "isolated", isolated.LOCK_ROOT
    assert Path(isolated.LOCK_ROOT) != DATA / "scheduler_lock"


def test_an_impossible_cadence_refuses_with_a_non_zero_status() -> None:
    # by run identity and not by list length: the run log is bounded and front-truncated, so once it
    # holds its bound an appended event removes one from the front and a difference of lengths would
    # report no event at all while one had just been written
    before = {event.get("run_id") for event in read_jsonl(RUN_LOG)}
    result = run_tick_without_a_collision("--collect", "--rounds", "0")
    fresh = [
        event for event in read_jsonl(RUN_LOG) if event.get("run_id") not in before
    ]
    assert result.returncode == 1
    assert fresh and fresh[-1]["result"] == "REFUSED_INVALID_ARGUMENTS"
    assert fresh[-1]["exit_code"] == 1
    assert fresh[-1]["market_requests"] == 0


def test_the_closure_guard_dominates_the_collection() -> None:
    verifier = load_module("st6_scheduler_verifier", "scripts/st6_scheduler_verify.py")
    guard = verifier.closure_guard_structure()
    assert guard["status"] == "PASS", guard
    assert guard["period_ended_statement_index"] < guard["collection_statement_index"]
    assert guard["guard_branch_index"] < guard["collection_statement_index"]


# ------------------------------------------------------------------ the period closes instead of extending


def test_the_closure_consolidates_and_never_extends(tick: object) -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    windows = read_jsonl(WINDOWS)
    observations = read_jsonl(OBSERVATIONS)
    coverage = tick.coverage_document(period, windows, observations)
    statistics_ = tick.regime_statistics(observations)
    drift = tick.drift_document(period, windows, observations, statistics_)
    past = {
        **period,
        "started_at_utc": "2026-09-01T00:00:00Z",
        "ends_at_utc": "2026-09-15T00:00:00Z",
    }
    document = tick.close_period(
        past,
        coverage,
        drift,
        statistics_,
        windows,
        observations,
        datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
    )
    assert document["artifact"] == "ST6_PERIOD_CLOSURE"
    assert document["auto_extended"] is False
    assert "not prolonged automatically" in document["extension_policy"]
    assert document["eco_2"] == "UNKNOWN_NOT_RESOLVABLE_OFFLINE"
    assert document["standing_state"]["NEXT_CAMPAIGN"] == "NOT_AUTHORIZED"
    assert document["coverage_total"]["completed_windows"] == len(windows)
    assert document["raw_evidence"] and all(
        entry["uncompressed_sha256"] for entry in document["raw_evidence"]
    )
    assert document["limitations"]
    assert document["missed_windows"] == read_jsonl(MISSED_LOG)
    assert tick.period_ended(past, datetime(2026, 9, 16, tzinfo=UTC)) is True
    assert tick.period_ended(period, datetime(2026, 10, 9, tzinfo=UTC)) is False
    assert tick.period_ended(period, datetime(2026, 10, 23, tzinfo=UTC)) is True
    assert document["statistics"] == statistics_


def test_the_consolidation_builder_writes_nothing() -> None:
    """Only the closing command writes the consolidation: a rehearsal cannot overwrite the artefact."""
    before = CLOSURE.read_bytes() if CLOSURE.exists() else None
    tick = load_module("st6_tick_writer", "scripts/st6_forward_regime.py")
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    windows = read_jsonl(WINDOWS)
    observations = read_jsonl(OBSERVATIONS)
    coverage = tick.coverage_document(period, windows, observations)
    statistics_ = tick.regime_statistics(observations)
    drift = tick.drift_document(period, windows, observations, statistics_)
    tick.close_period(
        {**period, "started_at_utc": "2026-09-01T00:00:00Z", "ends_at_utc": "2026-09-15T00:00:00Z"},
        coverage,
        drift,
        statistics_,
        windows,
        observations,
        datetime(2026, 9, 15, 1, 0, tzinfo=UTC),
    )
    after = CLOSURE.read_bytes() if CLOSURE.exists() else None
    assert after == before, "the builder touched the shipped consolidation"


def test_the_plan_is_bounded_by_the_declaration_not_by_the_clock(
    tick: object, health: object
) -> None:
    """Fourteen days of six windows: the partial slot the period ends inside is not a window."""
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    planned = period["period_days"] * period["slots_per_day"]
    declared = tick.declared_slots_upto(period, datetime(2026, 10, 22, 16, 21, 20, tzinfo=UTC))
    mirrored = health.declared_slots_upto(period, datetime(2026, 10, 22, 16, 21, 20, tzinfo=UTC))
    assert planned == 84
    assert len(declared) == planned and len(mirrored) == planned
    assert [slot["key"] for slot in declared] == [slot["key"] for slot in mirrored]
    assert declared[0]["key"] == "2026-10-08#4"  # the slot the period opened inside
    assert declared[-1]["key"] == "2026-10-22#3"  # 12:00-16:00 UTC, the last window it can take
    assert all(slot["ends_at_utc"] <= period["ends_at_utc"] for slot in declared)
    # the boundary slot the period closes inside is never expected, so it can never be a penalty
    for clock in (
        datetime(2026, 10, 22, 16, 21, 20, tzinfo=UTC),
        datetime(2026, 10, 23, tzinfo=UTC),
    ):
        assert "2026-10-22#4" not in {
            slot["key"] for slot in health.declared_slots_upto(period, clock)
        }


def test_a_consolidation_is_read_by_identity_not_by_existence(
    health: object, scheduler_verifier: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closure of another period must never stand in for this period's consolidation."""
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    foreign = tmp_path / "ST6_PERIOD_CLOSURE.json"
    foreign.write_text(
        json.dumps(
            {
                "artifact": "ST6_PERIOD_CLOSURE",
                "period": {
                    "started_at_utc": "2026-09-01T00:00:00Z",
                    "ends_at_utc": "2026-09-15T00:00:00Z",
                },
                "auto_extended": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "CLOSURE", foreign)
    monkeypatch.setattr(scheduler_verifier, "CLOSURE", foreign)
    for reader in (
        health.closure_of_declared_period,
        scheduler_verifier.closure_for_declared_period,
    ):
        document, reading = reader(period)
        assert document is None and "another period" in reading, reading
        matched, reading = reader(
            {
                **period,
                "started_at_utc": "2026-09-01T00:00:00Z",
                "ends_at_utc": "2026-09-15T00:00:00Z",
            }
        )
        assert matched is not None and reading == "belongs to the declared period", reading
    foreign.unlink()
    for reader in (
        health.closure_of_declared_period,
        scheduler_verifier.closure_for_declared_period,
    ):
        absent, reading = reader(period)
        assert absent is None and reading == "absent", reading


# ------------------------------------------------------------------ health and the artefacts


def test_the_health_checker_uses_its_declared_vocabulary(health: object) -> None:
    assert health.STATES == ("HEALTHY", "WARNING", "CRITICAL", "PERIOD_COMPLETED")
    assert (
        health.EXIT_HEALTHY,
        health.EXIT_WARNING,
        health.EXIT_CRITICAL,
        health.EXIT_PERIOD_COMPLETED,
        health.EXIT_CHECK_FAILED,
    ) == (0, 10, 20, 30, 40)
    assert health.consecutive_failures([{"errors": None}, {"errors": "x"}, {"errors": "y"}]) == 2
    assert health.consecutive_failures([{"errors": "x"}, {"errors": None}]) == 0
    windows = read_jsonl(WINDOWS)
    state = health.raw_evidence_state(windows)
    assert state["windows"] == len(windows)
    assert state["missing"] == [] and state["mismatched"] == []


def test_the_health_status_is_declared_and_not_a_heartbeat() -> None:
    document = json.loads(HEALTH_STATUS.read_text(encoding="utf-8"))
    assert document["status"] in (
        "HEALTHY",
        "WARNING",
        "CRITICAL",
        "PERIOD_COMPLETED",
        "CHECK_FAILED",
    )
    assert document["heartbeat_is_not_evidence"] is True
    assert "not" in document["reading"] or "never" in document["reading"]
    if document["status"] == "HEALTHY":
        assert document["evidence"]["unaccounted_slots"] == []
        assert document["evidence"]["missed_fraction_of_ended_slots"] is None or (
            document["evidence"]["missed_fraction_of_ended_slots"] <= 0.2
        )
        assert document["evidence"]["scheduler"]["installed"] is True


def test_the_scheduler_report_agrees_with_its_verification() -> None:
    report = json.loads(SCHEDULER_REPORT.read_text(encoding="utf-8"))
    verification = json.loads(SCHEDULER_VERIFICATION.read_text(encoding="utf-8"))
    live = verification["live_tests"]
    assert report["REAL_EXECUTION_TEST"] == live["real_execution"]
    assert report["DUE_IDEMPOTENCY"] == live["due_idempotency"]
    assert report["CONCURRENCY_TEST"] == live["concurrency"]
    active = (
        report["SCHEDULER_INSTALLED"]
        and report["SCHEDULER_ENABLED"] is True
        and live["real_execution"] == "PASS"
        and live["due_idempotency"] == "PASS"
        and live["concurrency"] == "PASS"
    )
    assert report["autonomous_collection_active"] is active
    assert report["result_status"] == (
        "ST6_AUTONOMOUS_COLLECTION_ACTIVE" if active else "SCHEDULER_INSTALLED_NOT_YET_VERIFIED"
    )
    assert report["FALSE_SUCCESS"] == 0
    assert report["standing_state"]["LIVE_TRADING"] == "DISABLED"
    assert report["standing_state"]["TRADES_AUTHORIZED"] == 0
    assert report["MARKET_REQUESTS_ON_SKIPPED_RUNS"] == 0
    assert report["PLANNED_WINDOWS"] == 84
    assert report["COMPLETED_WINDOWS"] == len(read_jsonl(WINDOWS))
    assert report["MISSED_WINDOWS"] == len(read_jsonl(MISSED_LOG))


def test_the_verification_is_not_the_builder_and_reports_its_checks() -> None:
    verification = json.loads(SCHEDULER_VERIFICATION.read_text(encoding="utf-8"))
    assert verification["builder"] == "scripts/st6_forward_regime.py"
    assert verification["verifier"] == "scripts/st6_scheduler_verify.py"
    assert verification["builder_equals_verifier"] is False
    assert verification["checks_total"] > 60
    assert (
        verification["checks_passed"] + verification["mismatches"] == verification["checks_total"]
    )
    assert verification["false_success"] == verification["mismatches"]
    assert verification["false_success"] == 0
    for name, status in verification["live_tests"].items():
        assert status in ("PASS", "FAIL", "NOT_RUN"), (name, status)
    assert isinstance(verification["live_test_detail"]["real_execution"], dict)
    assert verification["live_test_detail"]["real_execution"].get("detail")


def test_none_of_the_new_programs_can_reach_an_order_or_a_credential() -> None:
    verifier = load_module("st6_scheduler_verifier_scan", "scripts/st6_scheduler_verify.py")
    for path in (TICK, HEALTH_SCRIPT, SCHEDULER_VERIFIER):
        source = path.read_text(encoding="utf-8")
        assert verifier.order_path_tokens(source) == [], path.name
    # the two programs that touch the network must not even name a credential or a live mode; the
    # verifier names them because naming them is what it checks
    for path in (TICK, HEALTH_SCRIPT):
        source = path.read_text(encoding="utf-8")
        for token in ("ccxt", "TRADING_MODE", "api_secret"):
            assert token not in source, (path.name, token)
    # the scan is not vacuous: it does fire on a call that passes one of the tokens
    assert verifier.order_path_tokens('client.create_order(symbol, "create_order")') == [
        "create_order"
    ]
    assert verifier.order_path_tokens('FORBIDDEN = ("api_key", "create_order")') == []
    assert not (DATA / "ST6_TASK_DEFINITION.xml").read_text(encoding="utf-16").count("password")


def test_the_evidence_of_the_period_still_reproduces() -> None:
    for window in read_jsonl(WINDOWS):
        raw = Path(window["raw"]["path"])
        if not raw.is_absolute():
            raw = REPO / raw
        assert raw.exists()
        with gzip.open(raw, "rb") as handle:
            import hashlib

            assert hashlib.sha256(handle.read()).hexdigest() == window["raw"]["uncompressed_sha256"]
        assert window["orders_sent"] == 0
        assert window["credentials_used"] == 0
    assert (
        not CLOSURE.exists()
        or json.loads(CLOSURE.read_text(encoding="utf-8"))["auto_extended"] is False
    )
    assert sys.version_info >= (3, 11)


# ------------------------------------------------------------------ the isolated close replay

REPLAY_SCRIPT = REPO / "scripts" / "st6_close_replay.py"


def test_the_close_replay_is_isolated_and_passes_on_the_shipped_state(tmp_path: Path) -> None:
    """The close is proven on a copy of the state with an injected clock, before its date arrives."""
    import hashlib

    out_json = tmp_path / "replay.json"
    completed = subprocess.run(
        [
            str(PYTHON),
            str(REPLAY_SCRIPT),
            "--out-json",
            str(out_json),
            "--out-md",
            str(tmp_path / "replay.md"),
            "--sandbox-root",
            str(tmp_path / "sandbox"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["close_mechanics_verdict"] == "PASS", report["summary"]
    assert report["summary"]["failed"] == 0
    # the replay is exercised, not trusted: it moved nothing it cannot explain and reached no
    # market and no scheduler
    assert report["isolation"]["unexplained_changes"] == []
    assert report["isolation"]["real_market_requests"] == 0
    assert report["isolation"]["real_scheduler_calls"] == 0
    assert report["isolation"]["subprocess_attempts"] == []
    assert report["isolation"]["sandbox_outside_repository"] is True
    assert report["tick_sha256"] == hashlib.sha256(TICK.read_bytes()).hexdigest()
    assert {deviation["id"] for deviation in report["boundary_deviations"]} == {
        "BOUNDARY-SLOT-DUE-RULE",
        "EXTENSION-FLAG-INERT",
    }
    close = next(entry for entry in report["scenarios"] if entry["scenario"].startswith("3."))
    assert close["closure_outcome"] in (
        "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
        "COST_MODEL_DRIFT_DETECTED",
        "INSUFFICIENT_REGIME_COVERAGE",
        "DATA_QUALITY_FAILED",
    )
    # the terminal state is idempotent and the denominator stays the declared plan
    repeat = next(entry for entry in report["scenarios"] if entry["scenario"].startswith("4."))
    assert all(repeat["checks"].values()), repeat["checks"]
    missed = next(entry for entry in report["scenarios"] if entry["scenario"].startswith("6."))
    assert missed["declared_windows"] == 84
    assert missed["missed_windows"] == 84 - missed["observed_windows"]


# ------------------------------------------------- who invoked the tick, and what that means

SNAPSHOT_SCRIPT = REPO / "scripts" / "st6_state_snapshot.py"
PROVENANCE_VOCABULARY = ("SCHEDULED", "MANUAL")


def test_the_run_log_records_who_invoked_the_tick() -> None:
    """The log is append-only and shared with the fixtures, so the caller must be recorded.

    Rows written before the field existed carry no provenance and are left alone; every row that
    does carry one must use the declared vocabulary.
    """
    if not RUN_LOG.exists():
        pytest.skip(
            "no ST-6 run log in this checkout: the provenance of its rows cannot be asserted "
            "where the rows do not exist"
        )
    rows = read_jsonl(RUN_LOG)
    assert rows
    for run in rows:
        if "invocation" in run:
            assert run["invocation"] in PROVENANCE_VOCABULARY, run
    assert {run["invocation"] for run in rows if run.get("invocation") == "SCHEDULED"} <= set(
        PROVENANCE_VOCABULARY
    )


def test_a_manual_invocation_is_neither_a_failure_nor_a_heartbeat(health: object) -> None:
    """A verification fixture must not be able to trip the live monitor or keep it looking alive."""
    assert health.is_manual({"invocation": "MANUAL"}) is True
    assert health.is_manual({"invocation": "SCHEDULED"}) is False
    assert health.is_manual({}) is False
    runs = [
        {"invocation": "SCHEDULED", "errors": None, "actual_end_utc": "2026-10-08T21:00:00Z"},
        {"invocation": "MANUAL", "errors": "rounds=0", "actual_end_utc": "2026-10-08T21:10:00Z"},
        {"invocation": "MANUAL", "errors": "rounds=0", "actual_end_utc": "2026-10-08T21:20:00Z"},
        {"errors": "a real failure", "actual_end_utc": "2026-10-08T21:30:00Z"},
    ]
    kept = [run for run in runs if not health.is_manual(run)]
    # the fixtures are dropped, the unrecorded row is kept: dropping it could hide a real failure
    assert health.consecutive_failures(kept) == 1
    # unfiltered, the two fixtures would have turned one recorded error into a CRITICAL streak
    assert health.consecutive_failures(runs) == 3
    assert health.consecutive_failures(kept) < health.CONSECUTIVE_FAILURES_CRITICAL
    assert health.run_provenance(runs) == {"SCHEDULED": 1, "MANUAL": 2, "UNRECORDED": 1}
    # the heartbeat follows the schedule, not the newest line in the file
    assert kept[-1]["actual_end_utc"] == "2026-10-08T21:30:00Z"


def test_a_fixture_refusal_is_not_reported_as_the_campaign_failing(health: object) -> None:
    """The newest event can be a fixture: the error that describes the programme is the schedule's."""
    quiet = {"invocation": "SCHEDULED", "result": "SKIPPED_NO_WINDOW_DUE", "errors": None}
    schedule_failed = {
        "invocation": "SCHEDULED",
        "result": "COLLECTION_INCOMPLETE",
        "errors": "the probe failed",
    }
    fixture_failed = {
        "invocation": "MANUAL",
        "result": "REFUSED_INVALID_ARGUMENTS",
        "errors": "rounds=0, spacing=5.0",
    }
    unrecorded_failed = {"result": "COLLECTION_INCOMPLETE", "errors": "no provenance at all"}

    # a fixture's refusal raises nothing: it is information about the harness, not a verdict
    assert health.error_warnings([quiet, fixture_failed]) == []
    information = health.provenance_information([quiet, fixture_failed])
    assert information["manual_invocations"] == 1
    assert information["manual_invocations_with_errors"] == 1
    assert information["newest_event_is_manual"] is True
    assert "rounds=0" in information["last_manual_error"]

    both = health.error_warnings([quiet, schedule_failed, fixture_failed])
    assert len(both) == 1 and "last scheduled run recorded an error" in both[0]
    assert "the probe failed" in both[0]

    # a row written before the provenance field existed is kept: it may be the schedule failing
    kept = health.error_warnings([quiet, unrecorded_failed])
    assert kept and "last scheduled run recorded an error" in kept[0]


def test_every_snapshot_describes_the_copies_it_wrote() -> None:
    """A manifest must describe bytes that exist, on a host whose tick rewrites five files every 15m.

    The first pass hashed the live file and copied it in two separate reads, so a snapshot taken
    while the tick was writing (07:33:09Z) recorded five digests for versions that were nowhere on
    disk.  Every later manifest hashes the copy it wrote, and the live file it saw move is named.
    """
    import hashlib

    manifests = sorted((DATA / "snapshots").glob("ST6_LIVE_STATE_*.json"))
    assert manifests, "no snapshot exists to check"
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in manifests]
    expected = 0
    for manifest_path, manifest in zip(manifests, documents, strict=True):
        assert manifest["copy_root"].endswith(manifest_path.stem)
        present = [e for e in manifest["classification"]["LIVE_RUNTIME_STATE"] if e.get("present")]
        assert len(present) == len(manifest["copied_live_files"])
        expected += len(present)
        for entry in present:
            copy = (
                DATA
                / "snapshots"
                / manifest_path.stem
                / Path(entry["path"]).relative_to("data/st6")
            )
            assert copy.exists(), f"{entry['path']} has no copy in {manifest_path.stem}"
            actual = hashlib.sha256(copy.read_bytes()).hexdigest()
            assert actual == entry["sha256"], (manifest_path.name, entry["path"], actual)
            if "live_moved_during_the_copy" in entry:
                assert entry["live_moved_during_the_copy"] == (
                    entry["live_sha256_before_the_copy"] != entry["live_sha256_after_the_copy"]
                )
    assert expected >= 13 * len(manifests)


def test_the_snapshot_check_separates_drift_from_corruption(tmp_path: Path) -> None:
    """The snapshot must stay verifiable for fourteen days while the tick rewrites the live state."""
    import hashlib
    import shutil

    snapshot = load_module("st6_state_snapshot_check", "scripts/st6_state_snapshot.py")
    # one live file, copied into the snapshot under its own name: the copy is the original
    # (the snapshot stores the live files flat, without the data/st6 prefix)
    copy_root = tmp_path / "copy"
    copy_root.mkdir(parents=True)
    live_name = "ST6_PERIOD.json"
    original = tmp_path / "original-bytes"
    original.write_bytes(b'{"artifact": "ST6_PERIOD", "frozen": true}\n')
    shutil.copy2(original, copy_root / live_name)
    entry = {
        "path": f"data/st6/{live_name}",
        "present": True,
        "bytes": original.stat().st_size,
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "git_blob_sha1": None,
    }
    manifest = tmp_path / "ST6_LIVE_STATE_20261008T000000Z.json"
    manifest.write_text(
        json.dumps(
            {
                "artifact": snapshot.SNAPSHOT_VERSION,
                "snapshot_id": manifest.stem,
                "hash_algorithm": snapshot.HASH_ALGORITHM,
                "copy_root": str(copy_root),
                "classification": {
                    "LIVE_RUNTIME_STATE": [entry],
                    "IMMUTABLE_EVIDENCE": [],
                    "VERSIONED_IMPLEMENTATION": [],
                },
            }
        ),
        encoding="utf-8",
    )
    # the live file has moved on (the tick rewrote it): drift, reported and not fatal
    result = snapshot.check_snapshot(manifest)
    assert result["status"] == "PASS", result["findings"]
    assert result["checks"] == 1
    assert result["live_state_drift_count"] == 1
    assert result["live_state_moved_since_snapshot"][0]["path"] == entry["path"]
    # the snapshot's own bytes are tampered with: integrity, and it must fail
    (copy_root / live_name).write_bytes(b'{"artifact": "ST6_PERIOD"}\n')
    tampered = snapshot.check_snapshot(manifest)
    assert tampered["status"] == "FAIL"
    assert any("inside the snapshot copy" in finding for finding in tampered["findings"])
    # a record that has disappeared is a failure too, not drift
    (copy_root / live_name).unlink()
    missing = snapshot.check_snapshot(manifest)
    assert missing["status"] == "FAIL"
    assert any("missing from the snapshot copy" in finding for finding in missing["findings"])
    # and a manifest that is not ours is refused before anything is believed
    manifest.write_text(json.dumps({"artifact": "SOMETHING_ELSE"}), encoding="utf-8")
    refused = snapshot.check_snapshot(manifest)
    assert refused["status"] == "FAIL" and refused["checks"] == 0


# ------------------------------- the external record, and what it is allowed to carry

LEDGER_SCRIPT = REPO / "scripts" / "st6_slot_ledger.py"
WITNESS_SCRIPT = REPO / "scripts" / "st6_scheduler_witness.py"


@pytest.fixture(scope="module")
def evidence(tick: object) -> object:
    return load_module("st6_external_evidence", "scripts/st6_scheduler_evidence.py")


@pytest.fixture(scope="module")
def ledger_module(tick: object) -> object:
    return load_module("st6_slot_ledger", "scripts/st6_slot_ledger.py")


def witness_samples(
    start: str,
    end: str,
    step_minutes: int = 10,
    launches: tuple[str, ...] = (),
    boot_utc: str | None = None,
) -> list[dict]:
    """Synthetic witness samples over an interval, with the boot instant of a fixture host."""
    rows: list[dict] = []
    moment = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    stop = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    while moment <= stop:
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        named = max((item for item in launches if item <= stamp), default=None)
        rows.append(
            {
                "artifact": "ST6_SCHEDULER_WITNESS_SAMPLE",
                "sample_id": f"fixture-{stamp}",
                "sampled_at_utc": stamp,
                "scheduler_reported_last_run_utc": named,
                "scheduler_reported_last_result": 0,
                "system_local_offset_minutes": 120,
                "system_last_boot_utc": boot_utc,
            }
        )
        moment += timedelta(minutes=step_minutes)
    return rows


SLOT_START = "2026-09-02T08:00:00Z"
SLOT_END = "2026-09-02T12:00:00Z"
SLOT_AFTER = datetime(2026, 9, 2, 13, 0, tzinfo=UTC)


def a_slot() -> dict:
    return {"key": "2026-09-02#2", "starts_at_utc": SLOT_START, "ends_at_utc": SLOT_END}


def test_the_external_record_covers_a_slot_only_when_it_saw_the_whole_of_it(
    evidence: object,
) -> None:
    """Coverage is arithmetic, not sentiment: a slot is covered only across its whole length."""
    start = datetime.strptime(SLOT_START, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    end = datetime.strptime(SLOT_END, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    whole = witness_samples("2026-09-02T07:50:00Z", SLOT_END)
    covered = evidence.slot_external_coverage(start, end, whole, None, SLOT_AFTER)
    assert covered["status"] == "EXTERNAL_COVERAGE_COMPLETE"
    assert covered["external_samples_in_slot"] > 0

    # the witness started inside the slot: a trigger before its first sample could have run unseen
    late = witness_samples("2026-09-02T09:00:00Z", SLOT_END)
    partial = evidence.slot_external_coverage(start, end, late, None, SLOT_AFTER)
    assert partial["status"] == "EXTERNAL_COVERAGE_PARTIAL"

    # the witness log holds nothing from inside the slot and the slot has ended: the witness never
    # reached it, so no external record covers it and no claim may rest on it
    pruned = evidence.slot_external_coverage(
        start, end, witness_samples("2026-09-02T07:55:00Z", "2026-09-02T07:56:00Z"), None, SLOT_AFTER
    )
    assert pruned["status"] == "SCHEDULER_EVIDENCE_UNAVAILABLE"
    gone = evidence.slot_external_coverage(start, end, [], None, SLOT_AFTER)
    assert gone["status"] == "SCHEDULER_EVIDENCE_UNAVAILABLE"
    # a slot that is still running is partial: the rest of it has not happened yet
    running = evidence.slot_external_coverage(
        start,
        end,
        witness_samples("2026-09-02T09:00:00Z", "2026-09-02T09:30:00Z"),
        None,
        datetime(2026, 9, 2, 9, 40, tzinfo=UTC),
    )
    assert running["status"] == "EXTERNAL_COVERAGE_PARTIAL"

    # a gap wider than a declared tick is not coverage, even with samples on both sides
    gapped = [
        row
        for row in witness_samples("2026-09-02T07:50:00Z", SLOT_END)
        if not row["sampled_at_utc"].startswith(("2026-09-02T09", "2026-09-02T10"))
    ]
    holed = evidence.slot_external_coverage(start, end, gapped, None, SLOT_AFTER)
    assert holed["status"] == "EXTERNAL_COVERAGE_PARTIAL"
    assert holed["largest_sample_gap_s"] > holed["max_gap_tolerated_s"]

    # a slot that has not begun is not covered by anything
    future = evidence.slot_external_coverage(
        datetime(2026, 9, 3, 0, 0, tzinfo=UTC),
        datetime(2026, 9, 3, 4, 0, tzinfo=UTC),
        whole,
        None,
        SLOT_AFTER,
    )
    assert future["status"] == "EXTERNAL_COVERAGE_NOT_YET_STARTED"


def test_a_machine_restart_inside_a_slot_stops_the_record_carrying_an_absence(
    evidence: object, tick: object
) -> None:
    """A host that was down cannot prove that nothing was due: the restart is a discontinuity."""
    start = datetime.strptime(SLOT_START, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    end = datetime.strptime(SLOT_END, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    rows = witness_samples("2026-09-02T07:50:00Z", SLOT_END, boot_utc="2026-09-02T09:30:00Z")
    coverage = evidence.slot_external_coverage(start, end, rows, None, SLOT_AFTER)
    assert coverage["system_restart_inside_slot"] is True
    assert coverage["status"] == "EXTERNAL_COVERAGE_PARTIAL"
    assert "restarted inside the slot" in coverage["reading"]
    # and the rule follows: no absence is carried, the slot is unknown
    earlier = {
        "slot_key": "2026-09-02#1",
        "actual_start_utc": "2026-09-02T06:30:00Z",
        "invocation": "SCHEDULED",
        "result": "SKIPPED_NO_WINDOW_DUE",
        "market_requests": 0,
        "errors": None,
    }
    attendance = tick.slot_attendance([earlier], a_slot(), coverage)
    assert attendance["classification"] == "ATTENDANCE_UNKNOWN"


def test_the_launch_instants_the_scheduler_named_are_the_only_external_launch_evidence(
    evidence: object,
) -> None:
    """A sample names the scheduler's most recent run, so the instants it reports are dates too."""
    start = datetime.strptime(SLOT_START, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    end = datetime.strptime(SLOT_END, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    launches = ("2026-09-02T08:30:00Z", "2026-09-02T09:15:00Z")
    rows = witness_samples("2026-09-02T07:50:00Z", SLOT_END, launches=launches)
    coverage = evidence.slot_external_coverage(start, end, rows, None, SLOT_AFTER)
    assert coverage["scheduler_engine_launch_count"] == 2
    assert coverage["scheduler_engine_launches_reported_in_slot"] == list(launches)
    # a run instant from before the slot belongs to the previous slot, not to this one
    before = witness_samples("2026-09-02T07:50:00Z", SLOT_END, launches=("2026-09-02T07:30:00Z",))
    earlier_only = evidence.slot_external_coverage(start, end, before, None, SLOT_AFTER)
    assert earlier_only["scheduler_engine_launch_count"] == 0
    assert earlier_only["scheduler_engine_launches_outside_the_slot_count"] == 1


def test_a_run_is_attributed_to_the_scheduler_only_when_its_own_record_says_so(
    evidence: object,
) -> None:
    """The event's own declaration is the weakest evidence there is; the report says which it is."""
    rows = witness_samples("2026-09-02T07:50:00Z", SLOT_END, launches=("2026-09-02T08:30:00Z",))
    event = {
        "run_id": "fixture-run",
        "actual_start_utc": "2026-09-02T08:30:02Z",
        "invocation": "SCHEDULED",
    }
    corroborated = evidence.corroborate_run(event, rows, boundary_local="2026-09-02T08:18:00")
    assert corroborated["status"].startswith("CORROBORATED")
    assert corroborated["matches"][0]["delta_s"] <= 120
    assert corroborated["declared_grid"]["status"] in ("ON_DECLARED_GRID", "OFF_DECLARED_GRID")
    # nothing outside the run log corroborates an old event: the scheduler keeps only its last run
    unrecorded = evidence.corroborate_run(
        {**event, "actual_start_utc": "2026-09-02T08:05:00Z"}, rows
    )
    assert unrecorded["status"] == "UNATTRIBUTED"
    # a contradictory or missing instant is not attributed to anything
    assert evidence.corroborate_run({"run_id": "x"}, rows)["status"] == "UNATTRIBUTED"
    assert evidence.corroborate_run({**event, "actual_start_utc": "yesterday"}, rows)[
        "status"
    ] == "UNATTRIBUTED"


def test_a_run_event_from_a_slot_with_a_window_but_no_corroboration_is_labelled(
    ledger_module: object,
) -> None:
    """A window is evidence of a measurement; it is not evidence that the schedule asked for it."""
    slot = {
        "slot_id": "2026-09-02#2",
        "day": "2026-09-02",
        "slot_index": 2,
        "slot_utc": "08:00-12:00 UTC",
        "starts_at": datetime(2026, 9, 2, 8, 0, tzinfo=UTC),
        "starts_at_utc": SLOT_START,
        "ends_at": datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
        "ends_at_utc": SLOT_END,
    }
    window = {
        "window_id": "20260902T083000Z",
        "day": "2026-09-02",
        "slot_index": 2,
        "raw": {"path": "data/st6/raw/none.json.gz", "uncompressed_sha256": "0" * 64},
        "freshness": {"observation_path_latency_ok": True},
    }
    runs = [
        {
            "run_id": "20260902T083000Z-fixture",
            "slot_key": "2026-09-02#2",
            "actual_start_utc": "2026-09-02T08:30:00Z",
            "actual_end_utc": "2026-09-02T08:30:09Z",
            "invocation": "SCHEDULED",
            "result": "COLLECTED",
            "exit_code": 0,
            "market_requests": 18,
            "errors": None,
        },
        {  # a second run inside the same slot, overlapping the first: counted, never doubled
            "run_id": "20260902T083000Z-fixture-b",
            "slot_key": "2026-09-02#2",
            "actual_start_utc": "2026-09-02T08:30:05Z",
            "actual_end_utc": "2026-09-02T08:30:12Z",
            "invocation": "SCHEDULED",
            "result": "SKIPPED_NO_WINDOW_DUE",
            "exit_code": 0,
            "market_requests": 0,
            "errors": None,
        },
    ]
    grid = {"interval_minutes": 15, "start_boundary_local": "2026-09-02T08:18:00"}
    entry = ledger_module.build_slot_entry(
        slot,
        {"started_at_utc": SLOT_START, "ends_at_utc": "2026-09-03T08:00:00Z"},
        {"2026-09-02#2": window},
        runs,
        {},
        [],
        None,
        grid,
        {"20260902T083000Z-fixture": {"reason": "a live test"}},
        SLOT_AFTER,
    )
    assert entry["state"] == "COLLECTED"
    assert entry["collection_window_id"] == "20260902T083000Z"
    assert entry["concurrent_runs_in_slot"] == 2
    origins = {row["internal_run_id"]: row["origin"] for row in entry["runs"]}
    # the run the verifier caused is labelled as its own; the other is only a declaration
    assert origins["20260902T083000Z-fixture"] == "INDUCED_BY_THE_VERIFIER"
    assert origins["20260902T083000Z-fixture-b"] == "SELF_DECLARED_UNVERIFIED"
    assert entry["expected_trigger"]["expected_triggers_in_slot"] == 16
    assert entry["expected_trigger"]["trigger_type_observable"] is False
    # the raw path of the fixture does not exist, so its hash is not claimed to reproduce
    assert entry["raw_evidence"]["present"] is False
    assert entry["verifier_status"] == "HASH_MISMATCH"


def test_a_manual_run_never_counts_as_attendance(ledger_module: object) -> None:
    slot = {
        "slot_id": "2026-09-02#2",
        "day": "2026-09-02",
        "slot_index": 2,
        "slot_utc": "08:00-12:00 UTC",
        "starts_at": datetime(2026, 9, 2, 8, 0, tzinfo=UTC),
        "starts_at_utc": SLOT_START,
        "ends_at": datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
        "ends_at_utc": SLOT_END,
    }
    by_hand = {
        "run_id": "by-hand",
        "slot_key": "2026-09-02#2",
        "actual_start_utc": "2026-09-02T08:30:00Z",
        "actual_end_utc": "2026-09-02T08:31:00Z",
        "invocation": "MANUAL",
        "result": "REPORT_ONLY",
        "exit_code": 0,
        "market_requests": 0,
        "errors": None,
    }
    entry = ledger_module.build_slot_entry(
        slot,
        {"started_at_utc": SLOT_START, "ends_at_utc": "2026-09-03T08:00:00Z"},
        {},
        [by_hand],
        {},
        [],
        None,
        {"interval_minutes": 15},
        {},
        SLOT_AFTER,
    )
    assert entry["runs"][0]["origin"] == "MANUAL"
    assert entry["state"] == "LOST_NO_WINDOW" or entry["state"] == "UNACCOUNTED"
    assert entry["attendance_classification"] is None  # nothing was recorded for this slot here


def test_a_corrupt_or_duplicated_ledger_is_refused_rather_than_read_as_empty(
    ledger_module: object,
) -> None:
    assert ledger_module.reconcile_with_ledger(None)["readable"] is False
    assert ledger_module.reconcile_with_ledger({"slots": "not a list"})["readable"] is False
    duplicated = ledger_module.reconcile_with_ledger(
        {"slots": [{"slot_id": "a"}, {"slot_id": "a"}], "generated_at_utc": "now"}
    )
    assert duplicated["readable"] is True and duplicated["duplicate_slot_ids"] == ["a"]
    malformed = ledger_module.reconcile_with_ledger({"slots": [{"slot_id": "a"}, "nonsense"]})
    assert malformed["malformed_entries"]


def test_a_raw_hash_that_does_not_reproduce_is_a_mismatch_not_a_pass(
    ledger_module: object, tmp_path: Path
) -> None:
    """The ledger quotes hashes, so it re-derives them; a hash that does not reproduce is a finding."""
    payload = b'{"artifact": "ST6_FIXTURE"}\n'
    path = tmp_path / "window.json.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(payload)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    good = {"raw": {"path": str(path), "uncompressed_sha256": digest}}
    assert ledger_module.raw_evidence_ok(good)["reproduces"] is True
    bad = {"raw": {"path": str(path), "uncompressed_sha256": "0" * 64}}
    assert ledger_module.raw_evidence_ok(bad)["reproduces"] is False
    absent = {"raw": {"path": str(tmp_path / "gone.json.gz"), "uncompressed_sha256": digest}}
    assert ledger_module.raw_evidence_ok(absent)["present"] is False


def test_the_ledger_keeps_what_a_bounded_log_has_already_forgotten(ledger_module: object) -> None:
    """The run log and the witness log are bounded: the ledger must not lose ground when they roll."""
    run = {
        "internal_run_id": "old-run",
        "process_start_utc": "2026-09-02T08:30:00Z",
        "origin": "SELF_DECLARED_UNVERIFIED",
    }
    previous = {
        "slot_id": "2026-09-02#2",
        "read_at_utc": "2026-09-02T13:00:00Z",
        "runs": [run],
        "external_evidence": {
            "status": "EXTERNAL_COVERAGE_COMPLETE",
            "scheduler_engine_launch_count": 0,
        },
        "attendance_evidence": {"classification": "UNATTENDED_NO_RUN_EVENT"},
        "attendance_classification": "UNATTENDED_NO_RUN_EVENT",
        "failure_reason": "UNATTENDED_NO_RUN_EVENT: nothing ran",
    }
    # the current read sees neither the run nor any coverage: the ledger keeps what it had
    current = {
        "slot_id": "2026-09-02#2",
        "read_at_utc": "2026-09-03T13:00:00Z",
        "runs": [],
        "external_evidence": {"status": "SCHEDULER_EVIDENCE_UNAVAILABLE"},
        "external_evidence_status": "SCHEDULER_EVIDENCE_UNAVAILABLE",
        "attendance_evidence": None,
        "attendance_classification": None,
        "failure_reason": None,
    }
    merged, carried = ledger_module.carry_forward(current, previous)
    assert merged["runs"] == [run]
    assert merged["external_evidence_status"] == "EXTERNAL_COVERAGE_COMPLETE"
    assert merged["attendance_classification"] == "UNATTENDED_NO_RUN_EVENT"
    assert sorted(carried) == [
        "attendance_classification",
        "attendance_evidence",
        "external_evidence",
        "failure_reason",
        "runs",
    ]
    assert merged["first_recorded_at_utc"] == "2026-09-02T13:00:00Z"
    # a stronger statement is never replaced by a weaker one, and a fresh one is never reverted
    live = {
        **current,
        "runs": [
            {
                "internal_run_id": "new-run",
                "process_start_utc": "2026-09-03T08:30:00Z",
                "origin": "CORROBORATED_ENGINE_LAUNCH",
            }
        ],
        "external_evidence": {"status": "EXTERNAL_COVERAGE_COMPLETE"},
        "external_evidence_status": "EXTERNAL_COVERAGE_COMPLETE",
    }
    merged_live, carried_live = ledger_module.carry_forward(live, previous)
    assert carried_live == ["runs"]
    assert [row["internal_run_id"] for row in merged_live["runs"]] == ["old-run", "new-run"]


def test_the_witness_records_what_the_host_says_and_never_hides_a_failure(monkeypatch) -> None:
    """An unreadable system is a recorded finding: the witness does not fall back on a program."""
    witness = load_module("st6_witness_probe", "scripts/st6_scheduler_witness.py")

    def broken(script: str, timeout: int = 60) -> dict:
        return {"exit_code": 1, "stdout": "", "stderr": "access denied", "error": "access denied"}

    monkeypatch.setattr(witness, "powershell", broken)
    channels = witness.channel_state()
    operational = channels["channels"]["Microsoft-Windows-TaskScheduler/Operational"]
    assert operational["enabled"] is None
    assert operational["query_error"] == "access denied"
    assert channels["security_log_readable"] is False
    evidence_document = witness.build_evidence()
    assert evidence_document["per_run_external_evidence"]["status"] == "SCHEDULER_EVIDENCE_UNAVAILABLE"
    assert evidence_document["task_registration"]["error"] == "access denied"
    assert evidence_document["remediation"]["authorised"] is False
    # and a channel that is disabled is unavailable even when it answers normally
    assert "never recorded" in evidence_document["per_run_external_evidence"]["reason"]


def test_an_unreadable_event_log_is_not_an_empty_one(monkeypatch) -> None:
    """Case 7 of the declared negative tests: a source that cannot be read is recorded as such."""
    witness = load_module("st6_witness_unreadable", "scripts/st6_scheduler_witness.py")

    def unreachable(*arguments: str) -> dict:
        return {
            "stdout": "",
            "stderr": "access denied",
            "exit_code": None,
            "error": "PermissionError: access denied",
            "reachable": False,
        }

    monkeypatch.setattr(witness, "wevtutil", unreachable)
    depth = witness.channel_depth("Microsoft-Windows-TaskScheduler/Operational")
    assert depth["reachable"] is False
    assert depth["answers_nothing"] is True, "an unreadable channel is not reported as readable"
    assessment = witness.rotation_assessment(
        {
            "channels": {
                "Microsoft-Windows-TaskScheduler/Operational": {
                    "depth": depth,
                    "retention_is_archive": False,
                    "max_size_bytes": 10485760,
                }
            }
        }
    )
    entry = assessment["channels"]["Microsoft-Windows-TaskScheduler/Operational"]
    assert entry["state"] == "EXTERNAL_RECORD_NOT_READABLE", entry
    assert entry["error"], "the reason the source could not be read is not kept"


def test_the_event_date_read_from_the_log_is_converted_to_utc(monkeypatch) -> None:
    """The tool prints a local instant with a Z on it: keeping that as UTC would misdate the log."""
    witness = load_module("st6_witness_clock", "scripts/st6_scheduler_witness.py")

    def answer(*arguments: str) -> dict:
        stdout = (
            "fileSize: 1048576\n"
            "numberOfLogRecords: 2268\n"
            "oldestRecordNumber: 440\n"
        )
        if arguments[0] == "qe":
            stdout = "Event[0]\n  Log Name: any\n  Date: 2026-10-09T18:24:57.8700000Z\n"
        return {
            "stdout": stdout,
            "stderr": "",
            "exit_code": 0,
            "error": None,
            "reachable": True,
        }

    monkeypatch.setattr(witness, "wevtutil", answer)
    depth = witness.channel_depth("any channel")
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    expected = (datetime(2026, 10, 9, 18, 24, 57, tzinfo=UTC) - offset).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert depth["oldest_retained_event_utc"] == expected, depth
    assert depth["oldest_retained_event_raw"].startswith("2026-10-09T18:24:57")
    assert depth["host_utc_offset_minutes"] == int(offset.total_seconds() // 60)
    assert depth["records_no_longer_present_before_the_oldest"] == 439


def test_the_rotation_of_a_log_is_recorded_as_loss_not_as_absence() -> None:
    """Case 8 of the declared negative tests: records a log has evicted are loss, not proof."""
    witness = load_module("st6_witness_rotation", "scripts/st6_scheduler_witness.py")

    def channel(depth: dict) -> dict:
        return {"depth": depth, "retention_is_archive": False, "max_size_bytes": 1048576}

    assessment = witness.rotation_assessment(
        {
            "channels": {
                "circular and full": channel(
                    {
                        "reachable": True,
                        "answers_nothing": False,
                        "records_held": 2268,
                        "file_size_bytes": 1048576,
                        "oldest_record_number": 440,
                        "records_no_longer_present_before_the_oldest": 439,
                        "oldest_retained_event_utc": "2025-11-02T04:30:31Z",
                        "newest_retained_event_utc": "2026-10-09T15:23:26Z",
                    }
                ),
                "never recorded": channel(
                    {
                        "reachable": True,
                        "answers_nothing": True,
                        "records_held": None,
                        "file_size_bytes": None,
                        "oldest_record_number": None,
                        "records_no_longer_present_before_the_oldest": None,
                        "oldest_retained_event_utc": None,
                        "newest_retained_event_utc": None,
                    }
                ),
                "empty and readable": channel(
                    {
                        "reachable": True,
                        "answers_nothing": False,
                        "records_held": 0,
                        "file_size_bytes": 0,
                        "oldest_record_number": 1,
                        "records_no_longer_present_before_the_oldest": 0,
                        "oldest_retained_event_utc": None,
                        "newest_retained_event_utc": None,
                    }
                ),
            }
        }
    )
    assert assessment["status"] == "EXTERNAL_RECORD_ROTATION_LOSS_RECORDED"
    rotated = assessment["channels"]["circular and full"]
    assert rotated["state"] == "RECORDS_ROTATED_OUT"
    assert rotated["records_no_longer_present_before_the_oldest"] == 439
    assert rotated["full"] is True and rotated["circular"] is True
    assert assessment["channels"]["never recorded"]["state"] == "NEVER_RECORDED"
    assert "empty and readable" not in assessment["channels"], (
        "an empty log that answers is neither a rotation loss nor an unreadable source"
    )
    assert "cannot be repaired" in assessment["does_not_authorise"]


def test_the_declared_slot_grid_is_eighty_four_and_never_a_partial_slot(ledger_module: object) -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    slots = ledger_module.declared_slots(period)
    assert len(slots) == 84
    assert slots[0]["slot_id"] == "2026-10-08#4"
    assert slots[-1]["slot_id"] == "2026-10-22#3"
    assert slots[-1]["ends_at_utc"] == "2026-10-22T16:00:00Z"
    # the period closes inside the next slot, and that slot is not a planned window
    assert all(slot["slot_id"] != "2026-10-22#4" for slot in slots)
    assert len({slot["slot_id"] for slot in slots}) == 84


def test_the_shipped_ledger_accounts_for_every_declared_slot(ledger_module: object) -> None:
    """The durable record must cover the plan, agree with the index, and never invent a slot."""
    document = json.loads((DATA / "ST6_SLOT_LEDGER.json").read_text(encoding="utf-8"))
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    declared = {slot["slot_id"]: slot for slot in ledger_module.declared_slots(period)}
    rows = {row["slot_id"]: row for row in document["slots"]}
    assert set(rows) == set(declared)
    windows = {f"{row['day']}#{row['slot_index']}": row for row in read_jsonl(WINDOWS)}
    for slot_id, row in rows.items():
        assert row["slot_start_utc"] == declared[slot_id]["starts_at_utc"]
        assert row["state"] in ("COLLECTED", "LOST_NO_WINDOW", "PENDING", "UNACCOUNTED")
        if slot_id in windows:
            assert row["state"] == "COLLECTED"
            assert row["collection_window_id"] == windows[slot_id]["window_id"]
            assert row["raw_evidence_hash"] == windows[slot_id]["raw"]["uncompressed_sha256"]
            assert row["raw_evidence"]["reproduces"] is True
        classification = row.get("attendance_classification")
        if classification == "UNATTENDED_NO_RUN_EVENT":
            assert row["external_evidence_status"] == "EXTERNAL_COVERAGE_COMPLETE"
    assert document["summary"]["states"].get("UNACCOUNTED", 0) == 0
