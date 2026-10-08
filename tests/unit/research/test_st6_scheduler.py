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
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
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
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
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
    runs = read_jsonl(RUN_LOG)
    assert runs, "the autonomous layer has never ticked"
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
        assert all(entry["reason"] == "no scheduled run collected this slot" for entry in recorded)
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
    first = run_tick("--due", "--scheduled")
    second = run_tick("--due", "--scheduled")
    after = len(read_jsonl(WINDOWS))
    assert first.returncode == 0 and second.returncode == 0
    assert after == before, "a tick in an already observed slot collected another window"
    tails = read_jsonl(RUN_LOG)[-2:]
    assert all(event["result"] == "SKIPPED_NO_WINDOW_DUE" for event in tails)
    assert all(event["market_requests"] == 0 for event in tails)
    assert period["period_days"] == 14


def test_a_second_writer_refuses_and_makes_no_market_request(tick: object) -> None:
    lease = tick.run_lease()
    acquired = lease.acquire(now=int(datetime.now(UTC).timestamp()))
    assert acquired["acquired"] is True, acquired
    try:
        result = run_tick("--due", "--scheduled")
    finally:
        lease.release()
    assert result.returncode == 2
    refusals = [run for run in read_jsonl(RUN_LOG) if run["result"] == "ALREADY_RUNNING"]
    assert refusals, "the refusal left no trace in the run log"
    assert refusals[-1]["market_requests"] == 0
    assert refusals[-1]["errors"]


def test_an_impossible_cadence_refuses_with_a_non_zero_status() -> None:
    before = len(read_jsonl(RUN_LOG))
    result = run_tick("--collect", "--rounds", "0")
    fresh = read_jsonl(RUN_LOG)[before:]
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
