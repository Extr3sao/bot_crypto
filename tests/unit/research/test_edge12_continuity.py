"""WP-EDGE-12 — the regressions behind the numbers this campaign publishes.

What is tested here is the arithmetic a reader would have to re-derive by hand, plus
every defect this package found while trying to check its own work:

* the cadence phase decides which quarter-hour the instants fall on, so a reader who
  assumes :00 finds different losses from one who reads the registration's boundary;
* the cause of an unanswered instant is taken by the strength of the record, so a host
  that was down explains a silence that a session absence must not claim;
* a day is admissible only when its bars were stored as they closed, which is the one
  property an admission criterion is allowed to count;
* the identifier scan cannot satisfy a dependency by finding its own text, which is the
  failure mode the whole campaign exists to avoid;
* the scheduler reports booleans as strings, and ``bool("False")`` is ``True``.

The tests never touch the network, the live state root, the live store or the host.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge12 import (  # noqa: E402
    continuity,
    evidence,
    gate,
    operational,
    runner,
    storage,
)

HOUR = 3_600_000
QUARTER = 900_000


# --------------------------------------------------------------------------- the cadence
def test_instants_start_after_the_launch_that_established_the_phase():
    """The launch that shows the phase is not one of its own successors."""
    first = 1_792_000_000_000
    instants = operational.expected_instants(
        first_ms=first, phase_ms=653_000, interval_ms=QUARTER, until_ms=first + 3 * QUARTER
    )
    assert len(instants) == 3
    assert all(instant % QUARTER == 653_000 for instant in instants)
    assert instants[0] > first
    assert instants == sorted(instants)
    assert all(later - earlier == QUARTER for earlier, later in pairwise(instants))


def test_a_different_phase_gives_a_different_set_of_instants():
    first = 1_792_000_000_000
    early = operational.expected_instants(
        first_ms=first, phase_ms=0, interval_ms=QUARTER, until_ms=first + 4 * QUARTER
    )
    late = operational.expected_instants(
        first_ms=first, phase_ms=653_000, interval_ms=QUARTER, until_ms=first + 4 * QUARTER
    )
    assert early != late
    assert all(instant % QUARTER == 0 for instant in early)
    assert all(instant % QUARTER == 653_000 for instant in late)


def test_the_window_ends_where_it_is_declared_to_end():
    first = 1_792_000_000_000
    until = first + 5 * QUARTER
    instants = operational.expected_instants(
        first_ms=first, phase_ms=653_000, interval_ms=QUARTER, until_ms=until
    )
    assert instants and instants[-1] <= until
    assert instants[-1] + QUARTER > until


def test_a_non_positive_interval_is_refused():
    with pytest.raises(ValueError):
        operational.expected_instants(first_ms=0, phase_ms=0, interval_ms=0, until_ms=1_000)


def test_the_phase_is_taken_from_a_mode_and_not_from_a_jitter_sample():
    """The scheduler's jitter is tens of seconds, so a raw mode picks a sample, not the phase.

    The launches below all sit in the same quarter-hour minute (phase 7 min) but land on
    different seconds, and one of them is a jitter sample that no other launch shares: a
    mode over raw milliseconds would pick it and move every expected instant to it.
    """
    jitter = [
        420_000,
        421_400,
        419_800,
        420_900,
        421_100,
        420_300,
        419_000,
        421_900,  # the single sample with this exact value
    ]
    assert operational._mode_of(jitter) == 420_000
    assert operational._mode_of([]) == 0


# --------------------------------------------------------------------- cause attribution
def _evidence(*, boots=(), shutdowns=(), sessions=(), power=()):
    return {
        "boots": [{"at": instant, "id": 12, "provider": "p", "message": ""} for instant in boots],
        "shutdowns": [
            {"at": instant, "id": 13, "provider": "p", "message": ""} for instant in shutdowns
        ],
        "sessions": [
            {"at": instant, "id": event_id, "provider": "p", "message": ""}
            for instant, event_id in sessions
        ],
        "winlogon": [],
        "power": [
            {"at": instant, "id": event_id, "provider": "p", "message": ""}
            for instant, event_id in power
        ],
        "power_troubleshooter": [],
        "volumes": [],
        "physical_disks": [],
        "task": {},
    }


def _stamp(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_host_being_down_explains_a_silence_on_its_own():
    shutdown = 1_792_000_000_000
    boot = shutdown + HOUR
    instant = shutdown + QUARTER
    losses = operational.attributed_losses(
        instants=[instant],
        answered={},
        evidence=_evidence(shutdowns=[_stamp(shutdown)], boots=[_stamp(boot)]),
        until_ms=boot + HOUR,
    )
    assert losses["causes"]["HOST_DOWN"] == 1
    assert losses["causes"]["NO_SESSION"] == 0


def test_a_session_absence_bounds_the_silence_but_does_not_explain_the_host_being_down():
    logoff = 1_792_000_000_000
    logon = logoff + 3 * HOUR
    inside = logoff + HOUR
    after = logon + 2 * HOUR
    losses = operational.attributed_losses(
        instants=[inside, after],
        answered={},
        evidence=_evidence(sessions=[(_stamp(logoff), 23), (_stamp(logon), 21)]),
        until_ms=logon + 3 * HOUR,
    )
    assert losses["causes"]["NO_SESSION"] == 1
    assert losses["causes"]["SILENT_UNATTRIBUTABLE"] == 1
    assert losses["instants_by_cause"]["NO_SESSION"] == [_stamp(inside)]


def test_an_unexplained_instant_stays_unattributable_rather_than_guessed():
    instant = 1_792_000_000_000
    losses = operational.attributed_losses(
        instants=[instant], answered={}, evidence=_evidence(), until_ms=instant + HOUR
    )
    assert losses["causes"] == {
        "HOST_DOWN": 0,
        "NO_SESSION": 0,
        "SLEEP": 0,
        "SILENT_UNATTRIBUTABLE": 1,
    }


def test_sleep_is_only_claimed_when_the_host_recorded_one():
    asleep = 1_792_000_000_000
    resumed = asleep + HOUR
    losses = operational.attributed_losses(
        instants=[asleep + QUARTER],
        answered={},
        evidence=_evidence(power=[(_stamp(asleep), 42), (_stamp(resumed), 107)]),
        until_ms=resumed + HOUR,
    )
    assert losses["causes"]["SLEEP"] == 1

    without = operational.attributed_losses(
        instants=[asleep + QUARTER],
        answered={},
        evidence=_evidence(),
        until_ms=resumed + HOUR,
    )
    assert without["causes"]["SLEEP"] == 0


def test_an_unpaired_sleep_is_still_a_sleep_the_host_recorded():
    """A 42 with no 107 in the collected range is a sleep, reported as an open window.

    The alternative — treating an unpaired event as "no sleep" — would let a host that
    slept near the edge of the collection range have its silences called unattributable,
    which is a cause the host did write down.
    """
    asleep = 1_792_000_000_000
    losses = operational.attributed_losses(
        instants=[asleep + QUARTER],
        answered={},
        evidence=_evidence(power=[(_stamp(asleep), 42)]),
        until_ms=asleep + HOUR,
    )
    assert losses["causes"]["SLEEP"] == 1
    assert losses["windows"]["sleep"][0]["to_utc"] == _stamp(asleep + HOUR)


def test_an_answered_instant_is_not_a_loss():
    instant = 1_792_000_000_000
    losses = operational.attributed_losses(
        instants=[instant],
        answered={instant: "OBSERVED"},
        evidence=_evidence(),
        until_ms=instant + HOUR,
    )
    assert losses["total_lost"] == 0


# ------------------------------------------------------------------ forward coverage rule
def _write_store(root: Path, rows_by_series: dict[str, list[dict[str, object]]]) -> None:
    for key, rows in rows_by_series.items():
        timeframe, symbol = key.split(":")
        path = root / timeframe / f"{symbol}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )


def _hourly_rows(day_start_ms: int, *, bars: int, lag_ms: int) -> list[dict[str, object]]:
    rows = []
    for index in range(bars):
        ts = day_start_ms + index * HOUR
        rows.append({"ts": ts, "fetched_at_ms": ts + HOUR + lag_ms, "close": 1.0})
    return rows


def test_a_dense_day_whose_bars_arrived_late_is_backfilled_and_not_admissible(tmp_path):
    day = 1_792_000_000_000 - (1_792_000_000_000 % (24 * HOUR))
    series = {"1h:BTC": _hourly_rows(day, bars=24, lag_ms=5 * HOUR)}
    _write_store(tmp_path, series)
    reading = operational.forward_coverage(
        store_root=tmp_path,
        series=(("1h", "BTC"),),
        primary_assets=("BTC",),
        coverage_required=0.9,
        forward_days_required=60,
    )
    assert reading["prospectively_observed"] == 0
    assert reading["densely_covered_but_backfilled"] == 1
    assert reading["reached"] is False
    assert reading["remaining_days"] == 60


def test_a_dense_day_whose_bars_arrived_as_they_closed_is_admissible(tmp_path):
    day = 1_792_000_000_000 - (1_792_000_000_000 % (24 * HOUR))
    _write_store(tmp_path, {"1h:BTC": _hourly_rows(day, bars=24, lag_ms=60_000)})
    reading = operational.forward_coverage(
        store_root=tmp_path,
        series=(("1h", "BTC"),),
        primary_assets=("BTC",),
        coverage_required=0.9,
        forward_days_required=60,
    )
    assert reading["prospectively_observed"] == 1
    assert int(reading["remaining_days"]) == 59


def test_a_half_empty_day_is_neither_admissible_nor_dense(tmp_path):
    day = 1_792_000_000_000 - (1_792_000_000_000 % (24 * HOUR))
    _write_store(tmp_path, {"1h:BTC": _hourly_rows(day, bars=5, lag_ms=60_000)})
    reading = operational.forward_coverage(
        store_root=tmp_path,
        series=(("1h", "BTC"),),
        primary_assets=("BTC",),
        coverage_required=0.9,
        forward_days_required=60,
    )
    assert reading["prospectively_observed"] == 0
    assert reading["densely_covered_but_backfilled"] == 0


# ------------------------------------------------------------------------- the gate's scan
def test_the_identifier_scan_excludes_this_packages_own_files(tmp_path):
    """A scan that reads its own text finds every dependency it is asked about."""
    (tmp_path / "src" / "trading_bot" / "research" / "edge12").mkdir(parents=True)
    (tmp_path / "src" / "trading_bot" / "research" / "edge12" / "gate.py").write_text(
        "IDENTIFIER = 'RFC-EDGE-011'\n", encoding="utf-8"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "edge12_verify.py").write_text("RFC-EDGE-011\n", encoding="utf-8")
    (tmp_path / "reports" / "edge-recovery" / "WP-EDGE-12").mkdir(parents=True)
    (tmp_path / "reports" / "edge-recovery" / "WP-EDGE-12" / "RUN_REPORT.md").write_text(
        "RFC-EDGE-011\n", encoding="utf-8"
    )
    scan = gate.reader_scan(tmp_path, "RFC-EDGE-011")
    assert scan["verdict"] == "NOT_PRESENT_IN_TREE"
    assert scan["files_matching"] == 0
    assert len(scan["self_references_excluded"]) == 3


def test_this_packages_own_regressions_are_part_of_the_searcher(tmp_path):
    """The fixtures write the identifier out in full, so a scan that ran after them lied.

    This is the same defect as the source and the reports, one artefact later: the scan
    found ``RFC-EDGE-011`` in this package's own test module and reported the dependency
    present. The tests are therefore excluded, and every other package's tests are not.
    """
    (tmp_path / "tests" / "unit" / "research").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "research" / "test_edge12_continuity.py").write_text(
        "IDENTIFIER = 'RFC-EDGE-011'\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "unit" / "research" / "test_edge11_gate.py").write_text(
        "RFC-EDGE-011\n", encoding="utf-8"
    )
    scan = gate.reader_scan(tmp_path, "RFC-EDGE-011")
    assert scan["self_references_excluded"] == ["tests/unit/research/test_edge12_continuity.py"]
    assert scan["hits"] == [
        {"path": "tests/unit/research/test_edge11_gate.py", "match": "identifier"}
    ]


def test_every_root_the_searcher_owns_is_one_the_identifier_was_seen_in():
    """The exclusion list is the answer to a defect, so it has to name the whole surface."""
    assert gate._is_a_searcher_file("src/trading_bot/research/edge12/gate.py") is True
    assert gate._is_a_searcher_file("scripts/edge12_verify.py") is True
    assert gate._is_a_searcher_file("tests/unit/research/test_edge12_runner.py") is True
    assert gate._is_a_searcher_file("reports/edge-recovery/WP-EDGE-12/RUN_REPORT.md") is True
    assert gate._is_a_searcher_file("docs/RFC-EDGE-011.md") is False
    assert gate._is_a_searcher_file("tests/unit/research/test_edge04r_continuity.py") is False
    assert gate._is_a_searcher_file("reports/edge-recovery/WP-EDGE-12R/RUN_REPORT.md") is False


def test_a_dependency_that_is_really_there_is_reported_present(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "RFC-EDGE-011.md").write_text("RFC-EDGE-011 done\n", encoding="utf-8")
    scan = gate.reader_scan(tmp_path, "RFC-EDGE-011")
    assert scan["verdict"] == "PRESENT"
    assert scan["hits"] == [{"path": "docs/RFC-EDGE-011.md", "match": "identifier"}]


def test_the_scan_records_the_scopes_it_could_not_look_in(tmp_path):
    scan = gate.reader_scan(tmp_path, "RFC-EDGE-011")
    assert set(scan["scopes_absent"]) == set(gate.SEARCH_SCOPE)
    assert scan["files_scanned"] == 0


def test_a_recorded_digest_is_found_beside_the_path_it_belongs_to():
    """The path and its digest are siblings, so a search that only compares values fails."""
    payload = {
        "certificate": {"input": {"path": "data/x.json", "sha256": "a" * 64}},
        "other": {"path": "data/y.json", "sha256": "b" * 64},
    }
    assert gate._find_digest(payload, "data/x.json") == "a" * 64
    assert gate._find_digest(payload, "data/y.json") == "b" * 64
    assert gate._find_digest(payload, "nothing.json") is None


def test_a_volume_that_is_already_the_home_of_the_store_is_not_a_target(tmp_path):
    """Only a volume that is not the current one can qualify as somewhere to move to."""
    (tmp_path / "store").mkdir()
    evidence_row = {
        "volumes": [
            {
                "drive_letter": str(tmp_path.drive),
                "label": "current",
                "file_system": "NTFS",
                "capacity_bytes": 200 * 1024**3,
                "free_bytes": 100 * 1024**3,
            },
            {
                "drive_letter": "Q:",
                "label": "other",
                "file_system": "NTFS",
                "capacity_bytes": 200 * 1024**3,
                "free_bytes": 100 * 1024**3,
            },
        ],
        "physical_disks": [],
        "lane": {"bytes": 0},
    }
    reading = storage.storage_reading(
        repo_root=tmp_path,
        state_root=tmp_path,
        store_root=tmp_path / "store",
        runs=[],
        evidence=evidence_row,
    )
    current = next(row for row in reading["volumes"] if row["is_the_current_volume"])
    other = next(row for row in reading["volumes"] if row["drive_letter"] == "Q:")
    assert current["usable_for_this_store"] is False
    assert other["usable_for_this_store"] is True
    assert reading["relocation_verdict"] == "VOLUME_WITH_CAPACITY_AVAILABLE"


# ------------------------------------------------------- the scheduler's string booleans
def test_a_boolean_that_arrives_as_the_string_false_is_false():
    assert runner._as_bool("False") is False
    assert runner._as_bool("false") is False
    assert runner._as_bool("True") is True
    assert runner._as_bool(True) is True
    assert runner._as_bool(None) is False


def test_a_definition_is_read_whatever_encoding_it_was_written_in(tmp_path):
    xml = "<?xml version='1.0'?><Task><A/></Task>"
    for name, encoding in (("utf16.xml", "utf-16"), ("utf8.xml", "utf-8")):
        path = tmp_path / name
        path.write_text(xml, encoding=encoding)
        assert runner._read_definition(path) == xml
    assert runner._read_definition(tmp_path / "absent.xml") == ""


# ------------------------------------------------------------ the additive levers, read
def _run(started_ms: int, outcome: str, mode: str = "SCHEDULED") -> dict[str, object]:
    from datetime import UTC, datetime

    return {
        "started_at_ms": started_ms,
        "started_at_utc": datetime.fromtimestamp(started_ms / 1000, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "outcome": outcome,
        "mode": mode,
    }


def test_an_off_phase_launch_is_counted_and_not_attributed_to_a_mechanism():
    base = 1_792_000_000_000 - (1_792_000_000_000 % QUARTER)
    evidence_row = {
        "task": {
            "start_when_available": "True",
            "restart_count": "3",
            "restart_interval": "PT5M",
            "multiple_instances": "IgnoreNew",
            "triggers": [{"start_boundary": _boundary(base + 653_000)}],
        }
    }
    runs = [
        _run(base + QUARTER + 653_000, "OBSERVED"),
        _run(base + 2 * QUARTER + 653_000, "OBSERVED"),
        _run(base + 200_000, "OBSERVED"),
    ]
    levers = runner.additive_levers(evidence=evidence_row, runs=runs)
    assert levers["scheduled_launches"] == 3
    assert levers["off_phase_launches"] == 1
    assert "schtasks /run" in levers["attribution_limitation"]


def test_a_restart_policy_shaped_follow_up_is_measured_not_assumed():
    base = 1_792_000_000_000 - (1_792_000_000_000 % QUARTER)
    evidence_row = {"task": {"triggers": [{"start_boundary": _boundary(base)}]}}
    with_follow_up = [
        _run(base, "DISK_BUDGET_EXCEEDED"),
        _run(base + 300_000, "OBSERVED"),
    ]
    without = [
        _run(base, "DISK_BUDGET_EXCEEDED"),
        _run(base + QUARTER, "OBSERVED"),
    ]
    assert (
        runner.additive_levers(evidence=evidence_row, runs=with_follow_up)[
            "restart_policy_shaped_follow_ups"
        ]
        == 1
    )
    assert (
        runner.additive_levers(evidence=evidence_row, runs=without)[
            "restart_policy_shaped_follow_ups"
        ]
        == 0
    )


def _boundary(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------- the matrix itself
def test_every_property_the_rfc_names_has_a_row_and_none_is_missing():
    rehearsal = {
        "verdict": "REHEARSAL_NOT_RUN",
        "steps": [],
        "failures": [],
    }
    live = {
        "worst_gap_seconds": 100.0,
        "slots_sealed_rows": 1,
        "slots_unique_keys": 1,
        "maximum_tick_seconds": 1.0,
        "ticks_over_the_interval": 0,
        "gaps_over_the_declared_bound": [],
        "alerts": {"kinds": {}},
    }
    matrix = continuity.matrix(rehearsal_row=rehearsal, live=live, session_evidence={})
    assert matrix["properties_missing"] == []
    assert matrix["verdict"] == "CONTINUITY_MATRIX_COMPLETE"
    assert len(matrix["rows"]) == len(continuity.PROPERTIES)
    # A property with no rehearsal step must not read as a pass.
    assert "IDEMPOTENT_SLOT" in matrix["not_passed"]


def test_a_rehearsal_step_that_failed_makes_the_property_fail(tmp_path):
    rehearsal = {
        "verdict": "REHEARSAL_FAILED",
        "steps": [
            {
                "step_id": "repeat_inside_the_same_slot",
                "property": "IDEMPOTENT_SLOT",
                "verdict": "FAIL",
                "expected": "no second request",
                "observed": {"outcome": "OBSERVED", "market_requests": 7, "store_unchanged": False},
            }
        ],
        "failures": ["repeat_inside_the_same_slot"],
    }
    live = {
        "worst_gap_seconds": None,
        "slots_sealed_rows": 0,
        "slots_unique_keys": 0,
        "maximum_tick_seconds": None,
        "ticks_over_the_interval": 0,
        "gaps_over_the_declared_bound": [],
        "alerts": {"kinds": {}},
    }
    matrix = continuity.matrix(rehearsal_row=rehearsal, live=live, session_evidence={})
    row = next(item for item in matrix["rows"] if item["property"] == "IDEMPOTENT_SLOT")
    assert row["verdict"] == "FAIL"
    assert "IDEMPOTENT_SLOT" in matrix["not_passed"]


def _live(**overrides):
    live = {
        "worst_gap_seconds": 100.0,
        "slots_sealed_rows": 3,
        "slots_unique_keys": 3,
        "maximum_tick_seconds": 41.2,
        "ticks_over_the_interval": 0,
        "gaps_over_the_declared_bound": [],
        "alerts": {"kinds": {}},
    }
    live.update(overrides)
    return live


def test_the_matrix_reads_a_reclaimed_lease_from_the_key_the_rehearsal_writes():
    """A renamed observation field must not take the matrix down with a `KeyError`.

    This is the shape the rehearsal writes today: the lease step reports `lease_status` and
    the age it used. A matrix that insisted on the older key raised after a *successful*
    rehearsal — the evidence on disk and no matrix rendered from it — so the row is pinned
    to the current shape, and to `.get()` for the rest.
    """
    rehearsal = {
        "verdict": "REHEARSAL_PASS",
        "failures": [],
        "steps": [
            {
                "step_id": "lease_left_by_a_crashed_process",
                "property": "STALE_LEASE_RECLAIM",
                "verdict": "PASS",
                "expected": "the lease is reclaimed by age and the tick proceeds",
                "observed": {
                    "outcome": "NO_NEW_DATA",
                    "lease_status": "STALE_LEASE_RECLAIMED",
                    "lease_age_seconds": 360,
                    "previous_holder_pid": 999999,
                    "wall_seconds": 41.1,
                },
            }
        ],
    }
    matrix = continuity.matrix(rehearsal_row=rehearsal, live=_live(), session_evidence={})
    row = next(item for item in matrix["rows"] if item["property"] == "STALE_LEASE_RECLAIM")
    assert row["verdict"] == "PASS"
    assert "STALE_LEASE_RECLAIMED" in row["detail"]
    assert "360" in row["detail"]


def test_the_timeout_row_is_judged_from_the_stopwatch_and_not_from_the_ticks_own_clock():
    """The fist run of this rehearsal failed a working observer, and the reason is worth a test.

    A tick takes its start from the injected `now_ms` and closes with the wall clock, so the
    duration it reports is the wall clock *minus the pinned clock*: 900.797 s for a call that
    took seconds, then negative numbers once the pin passed the wall clock. The property is
    about the runtime, so it reads the figures a stopwatch produced, and the reported ones
    stay in the record as a cross-check only.
    """
    rehearsal = {
        "verdict": "REHEARSAL_PASS",
        "failures": [],
        "steps": [
            {
                "step_id": "a_tick_against_its_own_interval",
                "property": "TIMEOUT_HANDLING",
                "verdict": "PASS",
                "expected": "every rehearsal tick fits inside the interval",
                "observed": {
                    "wall_seconds": [3.1, 41.2, 0.9],
                    "maximum_seconds": 41.2,
                    "reported_durations_seconds": [900.797, 690.858, -857.628],
                    "interval_seconds": 900,
                    "lease_stale_after_seconds": 300,
                    "lease_shorter_than_the_interval": True,
                },
            }
        ],
    }
    matrix = continuity.matrix(rehearsal_row=rehearsal, live=_live(), session_evidence={})
    row = next(item for item in matrix["rows"] if item["property"] == "TIMEOUT_HANDLING")
    assert row["verdict"] == "PASS"
    assert "41.2" in row["detail"]
    assert "of wall clock" in row["detail"]


def test_a_rehearsal_starts_from_an_empty_state_root_and_a_copy_of_the_store(tmp_path):
    """Neither root may be inherited: the store is evidence, and the ledger is not a fixture.

    The second run of this rehearsal inherited the first one's state root, found its own first
    slot already sealed and failed three properties. This pins the reset that makes two runs of
    the same rehearsal comparable.
    """
    live = tmp_path / "live"
    (live / "1h").mkdir(parents=True)
    (live / "1h" / "BTC.jsonl").write_text('{"ts": 1}\n', encoding="utf-8")
    work = tmp_path / "work"
    (work / "state").mkdir(parents=True)
    (work / "state" / "runs.jsonl").write_text(
        '{"run": "the previous rehearsal"}\n', encoding="utf-8"
    )
    (work / "store" / "1h").mkdir(parents=True)
    (work / "store" / "1h" / "BTC.jsonl").write_text('{"ts": 999}\n', encoding="utf-8")
    rehearsal = continuity._Rehearsal(repo_root=tmp_path, work_root=work, store_source=live)
    rehearsal._reset_roots()
    assert not (work / "state").exists()
    assert (work / "store" / "1h" / "BTC.jsonl").read_text(encoding="utf-8") == '{"ts": 1}\n'


# --------------------------------------------------------------- the stopwatch itself
def test_the_rehearsal_times_a_tick_with_a_stopwatch_rather_than_trusting_the_tick(monkeypatch):
    """`_Rehearsal.tick` wraps the call, so the clock a tick reports is never the timing source."""
    rehearsal = continuity._Rehearsal.__new__(continuity._Rehearsal)

    class _Observer:
        def __init__(self) -> None:
            self.calls = 0

        def tick(self, **kwargs):
            self.calls += 1
            # A tick that lies about its own cost, in the direction the injected clock pushes.
            return {"duration_seconds": -2580.386, "outcome": "NO_NEW_DATA"}

    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(continuity.time, "perf_counter", lambda: next(ticks))
    observer = _Observer()
    result, seconds = rehearsal.tick(observer, observed_at_ms=1, due_only=True)
    assert seconds == 2.5
    assert result["duration_seconds"] == -2580.386
    assert observer.calls == 1


def test_the_summary_lists_every_step_and_its_verdict():
    rehearsal = {
        "verdict": "REHEARSAL_PASS",
        "steps": [
            {"step_id": "a", "property": "P", "verdict": "PASS"},
            {"step_id": "b", "property": "Q", "verdict": "FAIL"},
        ],
        "failures": ["b"],
    }
    summary = continuity.rehearsal_summary(rehearsal)
    assert [row["step_id"] for row in summary["steps"]] == ["a", "b"]
    assert summary["failures"] == ["b"]


# ------------------------------------------------------------- the rehearsal's own inputs
def test_truncating_the_store_removes_exactly_what_was_asked_for(tmp_path):
    rows = [{"ts": index} for index in range(10)]
    (tmp_path / "1h").mkdir()
    path = tmp_path / "1h" / "BTC.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    dropped = continuity._truncate_store(tmp_path, drop_last=3)
    assert dropped["dropped_per_series"] == {"1h:BTC": 3}
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 7


def test_truncating_more_than_the_store_holds_empties_it_without_inventing_bars(tmp_path):
    (tmp_path / "1h").mkdir()
    path = tmp_path / "1h" / "ETH.jsonl"
    path.write_text('{"ts": 1}\n{"ts": 2}\n', encoding="utf-8")
    dropped = continuity._truncate_store(tmp_path, drop_last=5)
    assert dropped["dropped_total"] == 2
    assert path.read_bytes() == b""


# ------------------------------------------------------------------- storage arithmetic
def test_the_store_rate_is_measured_from_the_files_and_not_fitted(tmp_path):
    (tmp_path / "1h").mkdir()
    (tmp_path / "1h" / "BTC.jsonl").write_text(
        "".join(json.dumps({"ts": index, "v": index}) + "\n" for index in range(4)),
        encoding="utf-8",
    )
    growth = storage._store_growth(tmp_path)
    row = next(item for item in growth["series"] if item["series"] == "1h:BTC")
    assert row["rows"] == 4
    assert row["bytes_per_bar"] == pytest.approx(row["bytes"] / 4, rel=1e-6)
    assert row["bytes_per_day"] == pytest.approx(row["bytes_per_bar"] * 24, rel=1e-6)


def test_the_retention_ceiling_is_a_sum_of_bounded_logs_and_not_a_trend(tmp_path):
    from trading_bot.research.edge03 import autonomous

    (tmp_path / "runs.jsonl").write_text(
        "".join(json.dumps({"run_id": index}) + "\n" for index in range(10)), encoding="utf-8"
    )
    ceiling = storage._retention_ceiling(tmp_path)
    runs_row = ceiling["operational_logs"]["runs.jsonl"]
    assert runs_row["rows_now"] == 10
    assert runs_row["rows_kept"] == autonomous.RUNS_KEPT
    assert runs_row["projected_bytes"] > 0
    assert ceiling["ceiling_within_budget"] is True


def test_an_empty_state_root_has_a_zero_ceiling_rather_than_an_error(tmp_path):
    ceiling = storage._retention_ceiling(tmp_path)
    assert ceiling["ceiling_bytes"] == 0
    assert ceiling["ceiling_within_budget"] is True


def test_the_volume_trajectory_refuses_to_speak_from_one_sample():
    trajectory = storage._volume_trajectory([{"disk_after": {"free_gib": 1.0}, "started_at_ms": 1}])
    assert trajectory["verdict"] == "INSUFFICIENT_SAMPLES"
    assert "gib_per_day" not in trajectory


def test_the_volume_trajectory_is_a_slope_of_the_volume_and_says_so():
    runs = [
        {"disk_after": {"free_gib": 10.0, "status": "HEALTHY"}, "started_at_ms": 0},
        {"disk_after": {"free_gib": 8.0, "status": "WARNING"}, "started_at_ms": 86_400_000},
    ]
    trajectory = storage._volume_trajectory(runs)
    assert trajectory["gib_per_day"] == pytest.approx(-2.0)
    assert "the volume holds whatever" in trajectory["reading"]


# ------------------------------------------------------------------- declared-path root
def test_a_declared_path_resolves_against_the_repository_and_not_the_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert evidence.repo_path("reports/x") == evidence.REPO_ROOT / "reports" / "x"
    assert evidence.repo_path(Path("a")) == evidence.REPO_ROOT / "a"


def test_the_repository_root_is_the_checkout_and_not_the_src_directory():
    assert (evidence.REPO_ROOT / "pyproject.toml").is_file()
    assert (evidence.REPO_ROOT / "src" / "trading_bot").is_dir()


# --------------------------------------------------------- the recorded regression run
def _load_script(name: str) -> Any:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tests_script() -> Any:
    return _load_script("edge12_tests")


# ------------------------------------------------------- the acceptance criteria table
def _acceptance_readings(all_checks_pass: list[dict[str, Any]]) -> dict[str, Any]:
    """Readings in which every criterion has something to read, so none fails by absence."""
    return {
        "gate": {
            "verdict": "DEPENDENCY_GATE_PASS",
            "entry_points": {"reachable": 6, "total": 6},
            "modules": {"importable": 9, "total": 9},
            "dependency_named_by_the_request": {
                "audit": {"verdict": "NOT_PRESENT_IN_TREE", "hits": []}
            },
            "scheduler": {"state": "Ready", "logon_type": "InteractiveToken"},
        },
        "decision": {
            "selected": "LOGON_TRIGGER",
            "available_without_new_privileges": ["LOGON_TRIGGER"],
            "blocked": {"S4U_PROPOSAL": "NEEDS_ELEVATION"},
            "evaluations": [{"mechanism": "S4U_TASK", "verdict": "NEEDS_ELEVATION"}],
        },
        "probes": {
            "applied_to_the_live_task": False,
            "probe_tasks_left_behind": [],
            "probes": {"S4U_PROPOSAL": {"verdict": "NEEDS_ELEVATION", "attempted": True}},
        },
        "preflight": {"verdict": "PREFLIGHT_PASS"},
        "storage": {
            "retention_ceiling": {
                "ceiling_bytes": 1,
                "declared_lane_budget_bytes": 2,
                "ceiling_within_budget": True,
            },
            "guard": {"status": "HEALTHY", "free_gib": 7.0},
            "forecast": {"added_gib_over_the_horizon": 0.006},
            "volumes": [],
        },
        "storage_verification": {
            "verdict": "STORAGE_VERIFY_PASS",
            "checks": [{"name": "the_guard_thresholds_are_the_campaigns_own", "passed": True}],
        },
        "matrix": {"rows": [{"property": "SINGLE_INSTANCE", "verdict": "PASS"}]},
        "live": {"slots_sealed_rows": 199, "slots_unique_keys": 199},
        "rehearsal": {"store_source": "live-store", "work_root": "copy"},
        "coverage": {
            "required_days": 60,
            "coverage_required": 0.9,
            "densely_covered_but_backfilled": 228,
        },
        "operational": {
            "levels": {
                "one_triggers_fired": {
                    "expected_instants": 4,
                    "answered_by_a_tick": 4,
                    "never_answered": 0,
                    "equals_the_whole": True,
                },
                "three_days_admissible": {
                    "prospectively_observed_days": 0,
                    "required_days": 60,
                },
            },
            "losses": {"causes": {}},
        },
        "verification": {
            "verdict": "VERIFY_PASS",
            "checks": all_checks_pass,
            "independence": "imports nothing from trading_bot.research.edge12",
            "self_test": {
                "verdict": "SELF_TEST_PASS",
                "detected": 24,
                "applied": 24,
                "undetected": 0,
            },
        },
        "failures": [
            {
                "id": "OPEN-EDGE12-4",
                "status": "INHERITED_AND_UNREPAIRED",
                "what": "the cost-barrier chain that issued the certificate",
            }
        ],
        "deliverables_all_present": True,
    }


def test_every_criterion_the_rfc_states_has_a_row_and_none_is_answered_with_a_blank():
    """A criterion answered with ``None`` is a criterion answered with nothing.

    The S4U verdict was read under the probe's key while the evaluation carries it under the
    mechanism's own name, so two rows published ``None`` where the host's refusal belongs.
    """
    reports_script = _load_script("edge12_reports")
    verify_script = _load_script("edge12_verify")
    readings = _acceptance_readings(
        [{"name": name, "passed": True} for name in verify_script.CHECKS]
    )
    rows = reports_script.acceptance_rows(readings)
    assert [row["criterion"] for row in rows] == [
        criterion for criterion, _requirement in reports_script.ACCEPTANCE
    ]
    assert len(rows) == 18
    offenders = [row["criterion"] for row in rows if "None" in row["evidence"]]
    assert offenders == []
    verdicts = {row["verdict"] for row in rows}
    assert verdicts <= {
        reports_script.SATISFIED,
        reports_script.BLOCKED_DECLARED,
        reports_script.PENDING_VERIFIER,
        reports_script.UNSATISFIED,
    }
    # Every check a row rests on names a check the verifier actually runs: a renamed check
    # would read as ``None`` and quietly turn its criterion into a failure of the reader.
    assert {
        "the_three_levels_reconcile",
        "backfilled_days_are_not_counted_as_forward",
        "the_coverage_floor_and_the_forward_requirement_are_intact",
        "no_order_and_no_promotion_anywhere",
        "the_storage_ceiling_is_inside_its_declared_budget",
        "the_snapshots_match_their_digests",
        "the_rehearsal_did_not_touch_the_live_store",
    } <= set(verify_script.CHECKS)


def test_the_final_report_does_not_state_a_figure_its_own_block_contradicts():
    """A sentence typed next to a computed figure is a sentence that drifts from it.

    The report said "it is zero" over the line that read "1 of 60": the prose was written
    when the reading was zero and stayed there after the reading moved. The figure is now
    rendered from the same value as the line above it, and this reads the published report
    to check the two agree rather than trusting that they do.
    """
    report = ROOT / "reports" / "edge-recovery" / "WP-EDGE-12" / "FINAL_REPORT.md"
    assert report.is_file(), "the final report is a deliverable; it is absent"
    text = report.read_text(encoding="utf-8")
    block = re.search(r"(\d+) of (\d+) \n?admissible forward days", text)
    assert block is not None, "the report no longer prints the admissible-day figure"
    admitted, required = block.group(1), block.group(2)
    assert f"and it is {admitted} of {required}" in text
    assert "admission criterion" in text


def test_a_criterion_is_not_awarded_before_the_verifier_has_run():
    """A table that answers itself with its own author's opinion is the false success."""
    reports_script = _load_script("edge12_reports")
    readings = _acceptance_readings([])
    readings["verification"] = {"verdict": "VERIFICATION_NOT_RUN", "checks": []}
    rows = {row["criterion"]: row["verdict"] for row in reports_script.acceptance_rows(readings)}
    for criterion in ("ACC-08", "ACC-09", "ACC-10", "ACC-11", "ACC-12", "ACC-13", "ACC-17"):
        assert rows[criterion] == reports_script.PENDING_VERIFIER
    # And a mechanism the RFC allows to be blocked is reported as blocked, not dropped.
    assert rows["ACC-05"] == reports_script.BLOCKED_DECLARED


def test_the_regression_figures_come_from_the_run_and_not_from_its_exit_status(tests_script):
    """A report quotes a number; an exit status does not say which number it was."""
    counts = tests_script._pytest_counts(
        {"tail": "..........................................  [100%]\n54 passed in 1.49s"}
    )
    assert counts["passed"] == 54
    assert counts["failed"] is None
    assert counts["errors"] is None


def test_a_run_whose_summary_cannot_be_read_reports_nulls_rather_than_zeros(tests_script):
    """``None`` and ``0`` are different facts, and a report must not print the wrong one."""
    counts = tests_script._pytest_counts({"tail": "nothing was collected"})
    assert counts == {"passed": None, "failed": None, "errors": None, "skipped": None}


def test_a_failing_run_is_recorded_with_both_of_its_figures(tests_script):
    counts = tests_script._pytest_counts({"tail": "1 failed, 53 passed in 2.10s\n2 errors in 0.4s"})
    assert counts["passed"] == 53
    assert counts["failed"] == 1
    assert counts["errors"] == 2


def test_a_skipped_suite_is_not_a_passing_suite(tests_script):
    """The verdict is the subprocess's own status, and a collection that found nothing
    exits non-zero: the count is what the report quotes, not what the verdict rests on."""
    counts = tests_script._pytest_counts({"tail": "no tests ran in 0.01s"})
    assert counts["passed"] is None
    assert tests_script.TEST_MODULES
    assert all(name.startswith("tests/") for name in tests_script.TEST_MODULES)
    assert all((ROOT / name).is_file() for name in tests_script.TEST_MODULES)
