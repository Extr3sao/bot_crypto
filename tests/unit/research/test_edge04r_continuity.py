"""WP-EDGE-04R — the audit's arithmetic, its attribution, and the probes that price it.

These tests are about the audit being *able to be wrong*: each one either feeds it a
case whose right answer is known independently, or feeds it the case that would make a
weaker implementation agree with itself (a boot before a shutdown, an instant a tick
already answered, a day whose columns must add up, a "sleep" cause with no sleep record).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from trading_bot.research.edge04r import continuity, os_evidence, session

INTERVAL = 900
INTERVAL_MS = INTERVAL * 1000
PHASE = 656_000


def _iso(ms: int) -> str:
    return continuity.stamp(ms)


def _tick(
    ms: int,
    *,
    outcome: str = "OBSERVED",
    mode: str = "SCHEDULED",
    exit_code: int = 0,
    free_gib: float = 8.0,
    disk_status: str = "HEALTHY",
) -> dict[str, object]:
    return {
        "run_id": f"FWD-{_iso(ms)}",
        "started_at_ms": ms,
        "finished_at_ms": ms + 30_000,
        "started_at_utc": _iso(ms),
        "finished_at_utc": _iso(ms + 30_000),
        "mode": mode,
        "outcome": outcome,
        "exit_code": exit_code,
        "slot_key": _iso(ms)[:16] + "Z",
        "duration_seconds": 30.0,
        "disk_after": {
            "status": disk_status,
            "free_bytes": int(free_gib * 1024**3),
            "critical_free_bytes": 2 * 1024**3,
            "warning_free_bytes": 5 * 1024**3,
        },
        "order_sent": False,
        "hypothetical": True,
        "promotion": "NONE",
    }


def _write_runs(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "runs.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _evidence(
    *,
    boots: list[int] = (),
    shutdowns: list[int] = (),
    logons: list[int] = (),
    logoffs: list[int] = (),
    sleeps: list[int] = (),
    resumes: list[int] = (),
    volumes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": os_evidence.EVIDENCE_SCHEMA_VERSION,
        "supported": True,
        "errors": [],
        "host": {"name": "TESTHOST", "collected_at_utc": "2026-01-01T00:00:00Z"},
        "boots": [{"at": _iso(ms), "id": 12} for ms in boots],
        "shutdowns": [{"at": _iso(ms), "id": 13} for ms in shutdowns],
        "power": [{"at": _iso(ms), "id": 42} for ms in sleeps]
        + [{"at": _iso(ms), "id": 107} for ms in resumes],
        "sessions": [{"at": _iso(ms), "id": 21} for ms in logons]
        + [{"at": _iso(ms), "id": 23} for ms in logoffs],
        "winlogon": [],
        "volumes": volumes or [],
        "physical_disks": [],
        "autologon": {"auto_admin_logon": "0", "default_user_name": "tester"},
        "task": {},
        "task_history": {"enabled": False, "record_count": 0},
    }


def _audit(tmp_path: Path, rows: list[dict[str, object]], evidence: dict[str, object], **kwargs):
    runs = _write_runs(tmp_path, rows)
    defaults = {
        "runs_path": runs,
        "slots_path": None,
        "evidence": evidence,
        "interval_seconds": INTERVAL,
        "until_ms": int(rows[-1]["started_at_ms"]) + INTERVAL_MS,  # type: ignore[arg-type]
        "lane_bytes": 11_000_000,
        "lane_budget_bytes": 268_435_456,
        "critical_bytes": 2 * 1024**3,
        "warning_bytes": 5 * 1024**3,
        "coverage_required": 0.9,
        "forward_days_required": 60,
        "current_drive": "C:",
    }
    defaults.update(kwargs)
    return continuity.audit(**defaults)  # type: ignore[arg-type]


# -- the phase and the instants ------------------------------------------------- #


def test_the_phase_is_measured_from_the_launches_not_assumed():
    """A task re-registered at another minute moves the phase; the instants follow it."""
    base = 1_792_000_000_000
    ticks = [
        continuity.Tick(
            run_id="a",
            started_ms=base,
            finished_ms=base + 1000,
            mode="SCHEDULED",
            outcome="OBSERVED",
            exit_code=0,
            slot_key="s",
            duration_seconds=1.0,
            disk_status="HEALTHY",
            disk_free_bytes=1,
        ),
        continuity.Tick(
            run_id="b",
            started_ms=base + INTERVAL_MS,
            finished_ms=base + INTERVAL_MS + 1000,
            mode="SCHEDULED",
            outcome="OBSERVED",
            exit_code=0,
            slot_key="s2",
            duration_seconds=1.0,
            disk_status="HEALTHY",
            disk_free_bytes=1,
        ),
    ]
    offset = continuity.phase_offset_ms(ticks, INTERVAL_MS)
    assert offset is not None
    assert 0 <= offset < INTERVAL_MS
    instants = continuity.expected_instants(base, base + 3 * INTERVAL_MS, INTERVAL_MS, offset)
    assert len(instants) == 4
    assert instants[1] - instants[0] == INTERVAL_MS
    assert all(instant % INTERVAL_MS == offset for instant in instants)


def test_every_instant_carries_the_measured_phase():
    instants = continuity.expected_instants(2 * INTERVAL_MS, 6 * INTERVAL_MS, INTERVAL_MS, PHASE)
    assert instants
    assert all(instant % INTERVAL_MS == PHASE for instant in instants)


# -- attribution ---------------------------------------------------------------- #


def test_an_instant_inside_a_shutdown_is_host_down_and_outranks_a_session():
    availability = {
        "host_down": [(1000, 2000, "shutdown and boot")],
        "session_absent": [(500, 5000, "logoff with no sign-in")],
        "sleep": [],
    }
    assert continuity.attribute_instant(1500, availability, until_ms=9000) == os_evidence.HOST_DOWN
    assert continuity.attribute_instant(2500, availability, until_ms=9000) == os_evidence.NO_SESSION
    assert (
        continuity.attribute_instant(8000, availability, until_ms=9000)
        == continuity.SILENT_UNATTRIBUTABLE
    )


def test_a_sleep_cause_needs_a_sleep_record():
    """The hypothesis this audit exists to refuse: a local guess that nobody wrote down."""
    ruled_out = {"host_down": [], "session_absent": [], "sleep": []}
    assert continuity.attribute_instant(1234, ruled_out, until_ms=9999) == (
        continuity.SILENT_UNATTRIBUTABLE
    )
    with_sleep = {"host_down": [], "session_absent": [], "sleep": [(1000, 2000, "42/107")]}
    assert continuity.attribute_instant(1500, with_sleep, until_ms=9999) == os_evidence.SLEEP


def test_an_open_window_ends_at_the_reading_instant_not_at_infinity():
    availability = {"host_down": [], "session_absent": [(1000, 0, "logoff")], "sleep": []}
    assert continuity.attribute_instant(10_000, availability, until_ms=5000) == (
        continuity.SILENT_UNATTRIBUTABLE
    )
    assert continuity.attribute_instant(4000, availability, until_ms=5000) == os_evidence.NO_SESSION


def test_a_boot_is_never_paired_with_a_shutdown_that_came_before_it():
    """The bug this audit shipped and fixed: two lists walked separately invent downtime."""
    # An early boot, then a shutdown, then the boot that ends it. Walking the boot list
    # against a growing pending-shutdown would have opened downtime at the FIRST boot.
    evidence = _evidence(boots=[1_000_000, 3_000_000], shutdowns=[1_500_000])
    windows = os_evidence.windows(evidence)
    assert windows["host_down"] == [(1_500_000, 3_000_000, windows["host_down"][0][2])]
    # A shutdown with no boot after it is an open window, reported rather than dropped.
    open_window = os_evidence.windows(_evidence(boots=[1_000_000], shutdowns=[1_500_000]))
    assert open_window["host_down"] == [(1_500_000, 0, open_window["host_down"][0][2])]


def test_a_reboot_with_no_sign_in_is_absence_not_downtime():
    evidence = _evidence(
        boots=[2_000_000], shutdowns=[1_900_000], logoffs=[1_800_000], logons=[4_000_000]
    )
    windows = os_evidence.windows(evidence)
    assert windows["host_down"]
    assert windows["session_absent"] == [(1_800_000, 4_000_000, windows["session_absent"][0][2])]
    assert windows["counts"]["sleep_resume_pairs"] == 0


# -- matching ticks to instants -------------------------------------------------- #


def test_each_instant_takes_at_most_one_tick_and_each_tick_one_instant():
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    instants = [start, start + INTERVAL_MS]
    ticks = [
        continuity.Tick(
            run_id="first",
            started_ms=start + 1000,
            finished_ms=start + 2000,
            mode="SCHEDULED",
            outcome="OBSERVED",
            exit_code=0,
            slot_key="a",
            duration_seconds=1.0,
            disk_status="HEALTHY",
            disk_free_bytes=1,
        ),
        # A retry 5 minutes later must not be counted as a second trigger firing.
        continuity.Tick(
            run_id="retry",
            started_ms=start + 5 * 60 * 1000,
            finished_ms=start + 5 * 60 * 1000,
            mode="SCHEDULED",
            outcome="ALREADY_RUNNING",
            exit_code=2,
            slot_key="a",
            duration_seconds=1.0,
            disk_status="HEALTHY",
            disk_free_bytes=1,
        ),
    ]
    result = continuity.classify_instants(
        instants,
        ticks,
        {"host_down": [], "session_absent": [], "sleep": []},
        until_ms=start + 2 * INTERVAL_MS,
        tolerance_ms=continuity.match_tolerance_ms(INTERVAL_MS),
    )
    assert result["matched"] == 1
    assert result["expected"] == 2
    assert len(result["unmatched"]) == 1
    assert len(result["ticks_without_instant"]) == 1
    assert result["ticks_without_instant"][0]["run_id"] == "retry"


def test_a_retry_cannot_answer_the_next_trigger():
    """A fixed ten-minute window would let a retry stand in for the next instant."""
    assert continuity.match_tolerance_ms(INTERVAL_MS) < INTERVAL_MS // 2
    assert continuity.match_tolerance_ms(INTERVAL_MS) > 2 * 60 * 1000
    assert continuity.match_tolerance_ms(0) == continuity.MATCH_TOLERANCE_MS


def test_a_manual_tick_is_not_an_answer_to_a_trigger():
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    manual = continuity.Tick(
        run_id="manual",
        started_ms=start,
        finished_ms=start + 1,
        mode="MANUAL",
        outcome="OBSERVED",
        exit_code=0,
        slot_key="a",
        duration_seconds=1.0,
        disk_status="HEALTHY",
        disk_free_bytes=1,
    )
    result = continuity.classify_instants(
        [start], [manual], {"host_down": [], "session_absent": [], "sleep": []}, until_ms=start
    )
    assert result["matched"] == 0
    assert result["unmatched"] == [start]


# -- the whole reading ----------------------------------------------------------- #


def test_a_lost_trigger_inside_an_absence_is_attributed_and_the_days_reconcile(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    ticks = [
        _tick(
            start, disk_status="CRITICAL", free_gib=1.0, outcome="DISK_BUDGET_EXCEEDED", exit_code=5
        ),
        _tick(start + 3 * INTERVAL_MS),
        _tick(start + 4 * INTERVAL_MS),
    ]
    # The session is absent for the middle two instants only.
    evidence = _evidence(logoffs=[start + INTERVAL_MS], logons=[start + 3 * INTERVAL_MS])
    audit = _audit(tmp_path, ticks, evidence, until_ms=start + 4 * INTERVAL_MS)
    assert audit["trigger_loss"]["expected"] == 5
    assert audit["trigger_loss"]["causes"] == {os_evidence.NO_SESSION: 2}
    assert audit["trigger_loss"]["refused_after_firing"] == 1
    assert audit["trigger_loss"]["total_lost"] == 3
    assert audit["ticks"]["refusals_by_outcome"] == {"DISK_BUDGET_EXCEEDED": 1}
    for day in audit["daily"]:
        assert day["unaccounted"] == 0, day
        assert (
            day["consumed"]
            + day["refused"]
            + day["no_session"]
            + day["host_down"]
            + day["sleep"]
            + day["silent"]
            == day["expected"]
        )


def test_a_host_with_no_sleep_record_loses_no_trigger_to_sleep(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    ticks = [_tick(start), _tick(start + 4 * INTERVAL_MS)]
    audit = _audit(tmp_path, ticks, _evidence())
    assert audit["trigger_loss"]["causes"].get(os_evidence.SLEEP, 0) == 0
    assert audit["availability"]["windows"]["counts"]["sleep_resume_pairs"] == 0
    check = next(
        item
        for item in audit["checks"]
        if item["name"] == "sleep_cause_is_claimed_only_with_a_sleep_record"
    )
    assert check["passed"] is True


def test_the_audit_fails_its_own_checks_when_a_tick_claims_an_order(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    rows = [_tick(start)]
    rows[0]["order_sent"] = True
    audit = _audit(tmp_path, rows, _evidence())
    check = next(item for item in audit["checks"] if item["name"] == "no_tick_claims_an_order")
    assert check["passed"] is False
    assert audit["verdict"] == "AUDIT_FAIL"


def test_the_window_is_measured_between_the_first_and_last_launch(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    audit = _audit(tmp_path, [_tick(start), _tick(start + 2 * INTERVAL_MS)], _evidence())
    assert audit["window"]["from_utc"] == _iso(start)
    assert audit["window"]["phase_offset_ms"] == PHASE


# -- storage --------------------------------------------------------------------- #


def _volume(
    letter: str, fs: str, free_gib: float, capacity_gib: float = 237.5
) -> dict[str, object]:
    return {
        "drive_letter": letter,
        "file_system": fs,
        "label": "",
        "drive_type": 3,
        "capacity_bytes": int(capacity_gib * 1024**3),
        "free_bytes": int(free_gib * 1024**3),
    }


def test_a_cloud_mount_and_the_current_volume_are_not_relocation_targets(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    evidence = _evidence(
        volumes=[
            _volume("C:", "NTFS", 7.0),
            _volume("G:", "FAT32", 7.0),
            _volume("D:", "NTFS", 120.0),
        ]
    )
    audit = _audit(tmp_path, [_tick(start)], evidence)
    estate = audit["storage"]["estate"]
    assert estate["verdict"] == "RELOCATION_AVAILABLE"
    assert [row["drive_letter"] for row in estate["relocatable_candidates"]] == ["D:"]
    by_letter = {row["drive_letter"]: row for row in estate["volumes"]}
    assert "already lives on" in str(by_letter["C:"]["exclusion_reason"])
    assert "not NTFS" in str(by_letter["G:"]["exclusion_reason"])


def test_with_no_other_volume_the_verdict_is_that_there_is_none(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    evidence = _evidence(volumes=[_volume("C:", "NTFS", 7.0), _volume("G:", "FAT32", 7.0)])
    audit = _audit(tmp_path, [_tick(start)], evidence)
    assert audit["storage"]["estate"]["verdict"] == "NO_VOLUME_WITH_CAPACITY"
    assert audit["storage"]["estate"]["relocatable_candidates"] == []


def test_disk_pressure_is_read_from_the_lanes_own_measurements(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    rows = [
        _tick(
            start, disk_status="CRITICAL", free_gib=1.5, outcome="DISK_BUDGET_EXCEEDED", exit_code=5
        ),
        _tick(start + INTERVAL_MS, disk_status="WARNING", free_gib=3.0),
        _tick(start + 2 * INTERVAL_MS, disk_status="HEALTHY", free_gib=8.0),
    ]
    audit = _audit(tmp_path, rows, _evidence())
    pressure = audit["storage"]["pressure"]
    assert pressure["minimum_free_gib"] == pytest.approx(1.5, abs=0.01)
    assert pressure["refused_ticks"] == 1
    assert pressure["seconds_in_critical"] == INTERVAL
    assert pressure["seconds_in_warning"] == INTERVAL


# -- the invariants --------------------------------------------------------------- #


def test_the_invariants_are_read_from_the_records(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    rows = [_tick(start)]
    rows[0]["ruleset"] = {"params_hash": "deadbeef"}
    audit = _audit(tmp_path, rows, _evidence())
    invariants = audit["invariants"]
    assert invariants["coverage_required"] == 0.9
    assert invariants["forward_days_required"] == 60
    assert "deadbeef" in invariants["ruleset"]["hashes_recorded_by_ticks"]
    assert invariants["ruleset"]["ticks_agree"] is False
    assert invariants["promotion"] == {"NONE": 1}


def test_the_ruleset_re_derivation_agrees_with_the_campaign_publication(tmp_path):
    base = 1_792_000_000_000
    start = base - (base - PHASE) % INTERVAL_MS + INTERVAL_MS
    audit = _audit(tmp_path, [_tick(start)], _evidence())
    ruleset = audit["invariants"]["ruleset"]
    assert ruleset["agrees"] is True, ruleset
    assert ruleset["params_hash"] == ruleset["imported_params_hash"]
    assert ruleset["published_params_hash"] == ruleset["params_hash"]


# -- the session probes ----------------------------------------------------------- #


def test_the_task_definition_carries_both_triggers_and_the_witness_first():
    xml = session.build_task_xml(
        user_id="DOMAIN\\tester",
        command="python.exe",
        arguments='"observer.py" --scheduled --due',
        working_dir="C:\\repo",
        witness_path=Path("C:\\scratch\\witness.log"),
    )
    assert "<LogonTrigger>" in xml and "<TimeTrigger>" in xml
    assert "<Delay>PT60S</Delay>" in xml
    assert xml.index("witness") < xml.index("observer.py")
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "WakeToRun>false<" in xml


def test_the_task_definition_can_ask_for_s4u_and_wake_to_run():
    xml = session.build_task_xml(
        user_id="DOMAIN\\tester",
        command="python.exe",
        arguments="x",
        working_dir="C:\\repo",
        witness_path=Path("C:\\scratch\\witness.log"),
        logon_type="S4U",
        wake_to_run=True,
    )
    assert "<LogonType>S4U</LogonType>" in xml
    assert "WakeToRun>true<" in xml


def test_wake_to_run_is_called_inapplicable_only_with_no_sleep_record():
    with_sleep = session.classify([], autologon={"auto_admin_logon": "0"}, sleep_pairs=2)
    assert "WAKE_TO_RUN" not in with_sleep["mechanisms"]
    without = session.classify([], autologon={"auto_admin_logon": "0"}, sleep_pairs=0)
    assert without["mechanisms"]["WAKE_TO_RUN"]["verdict"] == session.NOT_APPLICABLE


def test_a_mechanism_that_was_not_exercised_is_not_called_viable():
    classification = session.classify(
        [{"mechanism": session.S4U, "verdict": session.NEEDS_ELEVATION}],
        autologon={"auto_admin_logon": "0"},
        sleep_pairs=0,
    )
    assert session.S4U not in classification["viable"]
    assert session.S4U in classification["blocked"]


def test_the_recommendation_is_priced_from_the_audit():
    audit = {
        "trigger_loss": {"causes": {"NO_SESSION": 24, "SILENT_UNATTRIBUTABLE": 1}},
        "availability": {
            "recovery": [{"ends_at_a_sign_in": True, "recovery_latency_seconds": 321.41}]
        },
    }
    classification = session.classify(
        [
            {"mechanism": session.SESSION, "verdict": session.VIABLE},
            {"mechanism": "WITNESS_ACTION", "verdict": session.VIABLE},
        ],
        autologon={"auto_admin_logon": "0"},
        sleep_pairs=0,
    )
    recommendation = session.recommendation(audit=audit, probes=classification, task_name="T")
    assert recommendation["no_session_triggers_lost"] == 24
    assert recommendation["worst_recovery_latency_seconds"] == 321.41
    assert "24" in recommendation["what_s4u_would_buy"]
    assert "not_applied" in recommendation


# -- the operating-system evidence reader ----------------------------------------- #


def test_powershell_absence_is_an_error_and_never_an_empty_answer(monkeypatch):
    monkeypatch.setattr(os_evidence.shutil, "which", lambda _name: None)
    payload = os_evidence.collect()
    assert payload["supported"] is False
    assert payload["errors"]
    assert payload["host"] == {}


def test_unreadable_instants_are_dropped_rather_than_guessed():
    assert os_evidence.parse_instant("not-a-date") is None
    assert os_evidence.parse_instant(None) is None
    assert os_evidence.parse_instant("2026-10-15T04:50:54Z") is not None


# -- the definition this package would apply -------------------------------------- #

ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str):
    """Import a script by path: the reading commands are the ones a reader runs."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def continuity_script():
    return _load_script("edge04r_continuity")


def _registered_task(**overrides: object) -> dict[str, object]:
    """The lane's registration as the host reports it, including its string booleans."""
    task: dict[str, object] = {
        "task_name": "TradingAgentic-EDGE04-Forward",
        "user_id": "tester",
        "logon_type": "Interactive",
        "wake_to_run": "False",
        "execution_time_limit": "PT1H",
        "multiple_instances": "IgnoreNew",
        "state": "Ready",
        "actions": [
            {
                "execute": "C:\\repo\\.venv\\Scripts\\python.exe",
                "arguments": '"C:/repo/scripts/edge04_observer.py" --scheduled --due',
                "working_directory": "C:\\repo",
            }
        ],
        "triggers": [
            {
                "type": "MSFT_TaskTimeTrigger",
                "enabled": "True",
                "interval": "PT15M",
                "duration": "P3650D",
                "start_boundary": "2026-10-13T13:25:53",
                "delay": "",
            }
        ],
        "xml": (
            "<Task><RegistrationInfo><Date>2026-10-13T13:24:53</Date></RegistrationInfo></Task>"
        ),
    }
    task.update(overrides)
    return task


WITNESS = Path("C:\\scratch\\forward-witness.txt")


def _proposal(task: dict[str, object] | None = None) -> dict[str, object]:
    evidence = _evidence()
    evidence["task"] = task or _registered_task()
    return session.proposal_from_evidence(evidence, witness_path=WITNESS)


def test_the_proposal_carries_the_registration_and_adds_only_the_two_things():
    """Applying it has to change which instants can start, and nothing about what runs."""
    proposal = _proposal()
    xml = str(proposal["xml"])
    carried = proposal["carried_over_from_the_registration"]
    assert carried["command"] == "C:\\repo\\.venv\\Scripts\\python.exe"
    assert carried["arguments"] == '"C:/repo/scripts/edge04_observer.py" --scheduled --due'
    assert carried["working_directory"] == "C:\\repo"
    assert carried["logon_type"] == "InteractiveToken"
    assert carried["interval_minutes"] == 15
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<StartBoundary>2026-10-13T13:25:53</StartBoundary>" in xml
    assert "<Interval>PT15M</Interval>" in xml
    assert xml.count("<LogonTrigger>") == 1 and xml.count("<TimeTrigger>") == 1
    assert xml.index("witness") < xml.index("edge04_observer.py")
    assert len(proposal["added"]) == 2


def test_the_proposal_is_a_function_of_the_registration_not_of_the_clock():
    """A definition that stamps itself with the clock cannot be reviewed by digest."""
    first = _proposal()
    second = _proposal()
    assert first["xml"] == second["xml"]
    assert "<Date>2026-10-13T13:24:53</Date>" in str(first["xml"])


def test_a_reported_setting_is_read_as_a_boolean_and_not_as_a_nonempty_string():
    """``bool("False")`` is ``True``: reading a setting that way flips it silently."""
    assert session._as_bool("False") is False
    assert session._as_bool("True") is True
    assert session._as_bool(False) is False
    assert session._as_bool(None) is False
    assert "<WakeToRun>false</WakeToRun>" in str(_proposal()["xml"])
    awake = _proposal(_registered_task(wake_to_run="True"))
    assert "<WakeToRun>true</WakeToRun>" in str(awake["xml"])
    assert awake["carried_over_from_the_registration"]["wake_to_run"] is True  # type: ignore[index]


def test_the_rehearsal_difference_is_measured_and_it_is_the_action_payload():
    evidence = _evidence()
    evidence["task"] = _registered_task()
    proposal = session.proposal_from_evidence(evidence, witness_path=WITNESS)
    rehearsal = session.proposal_from_evidence(
        evidence,
        witness_path=WITNESS,
        command=session.INERT_COMMAND,
        arguments=session.INERT_ARGUMENTS,
    )
    moved = [
        (left, right)
        for left, right in zip(
            str(proposal["xml"]).splitlines(), str(rehearsal["xml"]).splitlines(), strict=True
        )
        if left != right
    ]
    assert len(moved) == 2
    assert any(session.INERT_ARGUMENTS in line for _, line in moved)
    assert session.INERT_COMMAND in str(rehearsal["xml"])


# -- the reading commands ---------------------------------------------------------- #


def test_a_declared_path_is_read_from_the_repository_root(continuity_script):
    """A relative path taken from the caller's cwd lands somewhere else inside the task."""
    root = continuity_script.REPO_ROOT
    assert continuity_script._repo_path("reports/x") == root / "reports" / "x"
    assert continuity_script._repo_path(Path("C:/already/absolute")) == Path("C:/already/absolute")


def test_an_offline_reading_takes_its_instant_from_the_record_it_re_derives(
    tmp_path, continuity_script
):
    """Defaulting to the clock here grows the window by however long the reader took."""
    record = tmp_path / "EDGE04R_CONTINUITY_AUDIT.json"
    record.write_text(json.dumps({"window": {"to_utc": "2026-10-15T18:31:46Z"}}), encoding="utf-8")
    read_back = continuity_script._until_ms(None, offline=True, audit_path=record)
    assert read_back == int(datetime.fromisoformat("2026-10-15T18:31:46+00:00").timestamp() * 1000)
    declared = continuity_script._until_ms("2026-01-02T03:04:05Z", offline=True, audit_path=record)
    assert declared == int(datetime.fromisoformat("2026-01-02T03:04:05+00:00").timestamp() * 1000)
    assert continuity_script._until_ms(None, offline=True, audit_path=tmp_path / "none.json") > 0


def test_an_offline_reading_does_not_read_the_lane_or_rewrite_the_snapshot(
    tmp_path, continuity_script
):
    """The published way to check a reading must be a reading of the committed inputs."""
    from datetime import UTC

    frozen = int(datetime(2026, 10, 15, 18, 31, 46, tzinfo=UTC).timestamp() * 1000)
    last = frozen - 900_000
    rows = [_tick(last)]
    report = tmp_path / "report"
    (report / "evidence").mkdir(parents=True)
    evidence = _evidence()
    evidence["task"] = _registered_task()
    (report / "evidence" / "OS_CONTINUITY_EVIDENCE.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    (report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json").write_text(
        json.dumps({"window": {"to_utc": "2026-10-15T18:31:46Z"}}), encoding="utf-8"
    )
    frozen_rows = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    (report / "evidence" / "RUN_LOG_SNAPSHOT.jsonl").write_bytes(frozen_rows)
    (report / "evidence" / "SLOT_LEDGER_SNAPSHOT.jsonl").write_bytes(b"")
    (report / "evidence" / "SNAPSHOT.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    # A lane that has kept ticking: reading it would move the window past the record's instant.
    lane = tmp_path / "lane"
    lane.mkdir()
    _write_runs(lane, [*rows, _tick(frozen + 3_600_000), _tick(frozen + 4_500_000)])
    assert (
        continuity_script.main(["--offline", "--reports", str(report), "--state-root", str(lane)])
        == 0
    )
    audit = json.loads((report / "evidence" / "EDGE04R_CONTINUITY_AUDIT.json").read_text())
    assert audit["window"]["to_utc"] == "2026-10-15T18:31:46Z"
    assert audit["ticks"]["total"] == len(rows)
    assert (report / "evidence" / "RUN_LOG_SNAPSHOT.jsonl").read_bytes() == frozen_rows
