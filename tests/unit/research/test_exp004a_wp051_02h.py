"""WP-051-02H adversarial suite: the watchdog, the audit arithmetic, and the verifier.

The three programs under test are loaded by path rather than by import, because none of
them is part of the ``trading_bot`` package: the watchdog deliberately imports nothing from
it, and the audit and the verifier read files rather than the lane.

What is *not* tested here, on purpose: a real tick. A tick needs the venue and the main
checkout's generated artefacts, and the package reports those runs separately, with their
exit codes, in ``RUN_REPORT.md``. A unit test that faked a tick would be the simulation the
mission forbids counting as the requirement.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = _load("edge04_watchdog_02h", "edge04_watchdog.py")
audit = _load("wp051_02h_audit", "exp004a_wp051_02h_audit.py")
verifier = _load("wp051_02h_verify", "exp004a_wp051_02h_verify.py")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def write_runs(state_root: Path, rows: list[dict]) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "runs.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )


def tick(started: datetime, *, ended_seconds: int = 35, outcome: str = "OBSERVED", new_bars: int = 0, **extra):
    row = {
        "run_id": f"FWD-EDGE04-{started.strftime('%Y%m%dT%H%M%SZ')}",
        "slot_key": _stamp(started)[:16] + "Z",
        "started_at_utc": _stamp(started),
        "finished_at_utc": _stamp(started + timedelta(seconds=ended_seconds)),
        "outcome": outcome,
        "exit_code": 0,
        "new_bars": new_bars,
    }
    row.update(extra)
    return row


def bar(open_ms: int, fetched_ms: int, *, closed: bool = True) -> dict:
    return {
        "ts": open_ms,
        "fetched_at_ms": fetched_ms,
        "closed": closed,
        "interval": "1h",
        "source": "BINANCE_PUBLIC_REST:/api/v3/klines",
        "payload_sha256": "0" * 64,
    }


HOUR = 3_600_000
DAY = 24 * HOUR


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# the watchdog
# --------------------------------------------------------------------------- #
def test_a_healthy_observer_yields_ok_and_no_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=4), new_bars=3)])
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 50, 50 * 1024**3))
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "OK"
    assert result["exit_code"] == 0
    assert result["reasons"] == []
    state = watchdog.persist(tmp_path, result)
    assert state["marker"] == "ABSENT"
    assert not (tmp_path / "ATTENTION_REQUIRED.txt").exists()
    assert json.loads((tmp_path / "WATCHDOG.json").read_text(encoding="utf-8"))["status"] == "OK"
    assert not list(tmp_path.glob("*.part"))


def test_silence_longer_than_three_intervals_is_stale_and_raises_the_marker(tmp_path: Path, monkeypatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=50), new_bars=1)])
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 50, 50 * 1024**3))
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "STALE"
    assert result["exit_code"] == 9
    state = watchdog.persist(tmp_path, result)
    assert state["marker"] == "RAISED"
    marker = (tmp_path / "ATTENTION_REQUIRED.txt").read_text(encoding="utf-8")
    assert "STALE" in marker
    assert any("minutes" in reason for reason in result["reasons"])


def test_a_next_healthy_run_lowers_the_marker(tmp_path: Path):
    stale = {
        "generated_at_utc": "2026-10-23T05:00:00Z",
        "status": "STALE",
        "exit_code": 9,
        "reasons": ["no tick"],
    }
    healthy = {
        "generated_at_utc": "2026-10-23T05:15:00Z",
        "status": "OK",
        "exit_code": 0,
        "reasons": [],
    }
    watchdog.persist(tmp_path, stale)
    assert (tmp_path / "ATTENTION_REQUIRED.txt").exists()
    watchdog.persist(tmp_path, healthy)
    assert not (tmp_path / "ATTENTION_REQUIRED.txt").exists()


def test_disk_under_the_critical_floor_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=2), new_bars=3)])
    monkeypatch.setattr(
        watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100 * 1024**3, 99 * 1024**3, 1 * 1024**3)
    )
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "BLOCKED"
    assert result["exit_code"] == 8
    assert "floor" in " ".join(result["reasons"]).lower()


def test_disk_between_the_floors_is_degraded_not_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=2), new_bars=3)])
    monkeypatch.setattr(
        watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100 * 1024**3, 97 * 1024**3, 3 * 1024**3)
    )
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "DEGRADED"
    assert result["exit_code"] == 1


def test_an_empty_state_root_is_unreadable_rather_than_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 50, 50 * 1024**3))
    result = watchdog.check(state_root=tmp_path, now_dt=datetime(2026, 10, 23, 6, 0, tzinfo=UTC))
    assert result["status"] == "UNREADABLE"
    assert result["exit_code"] == 2


def test_consecutive_refusals_are_counted_from_the_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    rows = [
        tick(now_dt - timedelta(minutes=40), new_bars=3),
        tick(now_dt - timedelta(minutes=30), outcome="DISK_BUDGET_EXCEEDED", exit_code=5),
        tick(now_dt - timedelta(minutes=15), outcome="DISK_BUDGET_EXCEEDED", exit_code=5),
        tick(now_dt - timedelta(minutes=2), outcome="DISK_BUDGET_EXCEEDED", exit_code=5),
    ]
    write_runs(tmp_path, rows)
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 50, 50 * 1024**3))
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["consecutive_blocked_ticks"] == 3
    assert result["status"] == "BLOCKED"
    assert result["exit_code"] == 8


def test_a_corrupt_line_is_counted_not_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=2), new_bars=3)])
    with (tmp_path / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 50, 50 * 1024**3))
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["corrupt_lines_examined"] == 1
    assert result["status"] == "DEGRADED"


# --------------------------------------------------------------------------- #
# the audit arithmetic
# --------------------------------------------------------------------------- #
def test_a_day_with_every_bar_on_time_is_complete():
    day = datetime(2026, 10, 20, tzinfo=UTC)
    verdicts = {
        ms(day) + k * HOUR: audit.bar_verdicts(
            [bar(ms(day) + k * HOUR, ms(day) + k * HOUR + HOUR + 60_000)],
            bound_ms=7_200_000,
            effective_from_ms=0,
            store_ms=ms(day) + DAY + HOUR,
        )[ms(day) + k * HOUR]
        for k in range(24)
    }
    row = audit.day_rows(verdicts, day_start_ms=ms(day), bound_ms=7_200_000, closed_before_ms=ms(day) + DAY + 1)
    assert row["classification"] == audit.DAY_COMPLETE
    assert row["admissible"] == 24
    assert row["lost"] is False


def test_one_late_bar_quarantines_the_whole_day():
    day = datetime(2026, 10, 23, tzinfo=UTC)
    verdicts = {}
    for k in range(24):
        lag = HOUR + 60_000
        if k == 3:
            lag = HOUR + 3 * HOUR  # three hours late
        verdicts[ms(day) + k * HOUR] = audit.bar_verdicts(
            [bar(ms(day) + k * HOUR, ms(day) + k * HOUR + lag)],
            bound_ms=7_200_000,
            effective_from_ms=0,
            store_ms=ms(day) + DAY + HOUR,
        )[ms(day) + k * HOUR]
    row = audit.day_rows(verdicts, day_start_ms=ms(day), bound_ms=7_200_000, closed_before_ms=ms(day) + DAY + HOUR)
    assert row["classification"] == audit.DAY_QUARANTINED
    assert row["lost"] is True
    assert [item["open_utc"] for item in row["inadmissible"]] == [audit.iso(ms(day) + 3 * HOUR)]


def test_an_open_day_holding_a_late_bar_is_already_doomed():
    day = datetime(2026, 10, 23, tzinfo=UTC)
    verdicts = {}
    for k in range(3):
        lag = HOUR + 5 * HOUR if k == 0 else HOUR + 60_000
        verdicts[ms(day) + k * HOUR] = audit.bar_verdicts(
            [bar(ms(day) + k * HOUR, ms(day) + k * HOUR + lag)],
            bound_ms=7_200_000,
            effective_from_ms=0,
            store_ms=ms(day) + 6 * HOUR,
        )[ms(day) + k * HOUR]
    row = audit.day_rows(verdicts, day_start_ms=ms(day), bound_ms=7_200_000, closed_before_ms=ms(day) + 6 * HOUR)
    assert row["classification"] == audit.DAY_OPEN_DOOMED
    assert row["lost"] is True


def test_an_open_day_with_nothing_wrong_is_not_yet_decided():
    day = datetime(2026, 10, 23, tzinfo=UTC)
    verdicts = {
        ms(day): audit.bar_verdicts(
            [bar(ms(day), ms(day) + HOUR + 60_000)],
            bound_ms=7_200_000,
            effective_from_ms=0,
            store_ms=ms(day) + 6 * HOUR,
        )[ms(day)]
    }
    row = audit.day_rows(verdicts, day_start_ms=ms(day), bound_ms=7_200_000, closed_before_ms=ms(day) + 6 * HOUR)
    assert row["classification"] == audit.DAY_NOT_CLOSED
    assert row["lost"] is False


def test_a_bar_before_the_effective_instant_is_not_admissible():
    instant = ms(datetime(2026, 10, 20, tzinfo=UTC))
    verdicts = audit.bar_verdicts(
        [bar(instant, instant + HOUR + 60_000)],
        bound_ms=7_200_000,
        effective_from_ms=instant + DAY,
        store_ms=instant + 2 * DAY,
    )
    assert verdicts[instant]["admissible"] is False
    assert "BEFORE_EFFECTIVE_FROM" in verdicts[instant]["reasons"]


def test_negative_lag_is_named_a_forgery(tmp_path: Path):
    instant = ms(datetime(2026, 10, 20, tzinfo=UTC))
    verdicts = audit.bar_verdicts(
        [bar(instant, instant + 60_000)],  # fetched before the bar closed
        bound_ms=7_200_000,
        effective_from_ms=0,
        store_ms=instant + DAY,
    )
    assert "NEGATIVE_LAG" in verdicts[instant]["reasons"]


def test_the_census_names_a_silence_longer_than_three_intervals(tmp_path: Path):
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base),
        tick(base + timedelta(minutes=15)),
        tick(base + timedelta(minutes=150)),
    ]
    census = audit.tick_census(rows, since_ms=ms(base) - 1)
    assert census["ticks"] == 3
    assert len(census["silences"]) == 1
    assert census["silences"][0]["minutes"] == pytest.approx(135.0)


def test_two_seals_in_one_slot_are_a_duplicate_and_two_attempts_are_not():
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, outcome="OBSERVED", new_bars=3, slot_sealed=True),
        tick(base + timedelta(minutes=10), outcome="ALREADY_OBSERVED", slot_sealed=False),
    ]
    census = audit.tick_census(rows, since_ms=0)
    assert census["slot_integrity"]["sealed_twice"] == []
    assert census["slot_integrity"]["lease_refusals"] == 0

    # the second attempt lands in the *same* scheduled slot, which is what makes it a duplicate
    rows[1]["slot_key"] = rows[0]["slot_key"]
    rows[1]["slot_sealed"] = True
    census = audit.tick_census(rows, since_ms=0)
    assert census["slot_integrity"]["sealed_twice"] == [rows[0]["slot_key"]]


def test_the_store_silence_is_measured_from_the_last_tick_that_added_bars():
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, outcome="OBSERVED", new_bars=3),
        tick(base + timedelta(minutes=15), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.4}),
        tick(base + timedelta(minutes=30), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.2}),
        tick(base + timedelta(minutes=195), outcome="OBSERVED", new_bars=9),
    ]
    boundary = audit.recovery_boundary(rows, audit_ms=ms(base) + 4 * HOUR, since_ms=ms(base) - 1)
    worst = boundary["worst_episode"]
    assert worst["blocked_ticks"] == 2
    assert worst["store_silence_minutes"] == pytest.approx(195.0)
    assert worst["recovery_latency_seconds"] == pytest.approx(165 * 60, rel=1e-6)


def test_an_open_episode_does_not_erase_the_closed_one_it_followed():
    """A tick refused ten minutes ago must not refute a resume that happened hours ago.

    The package's finding is about the hole that is over. Once a newer refusal episode opens
    and has no resume yet, its silence and latency are not numbers; anchoring the finding to it
    would mean the next refused tick invalidates the audit, which is what 06:40:57Z did before
    this control existed.
    """
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, outcome="OBSERVED", new_bars=3),
        tick(base + timedelta(minutes=15), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.2}),
        tick(base + timedelta(minutes=30), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.1}),
        tick(base + timedelta(minutes=45), outcome="OBSERVED", new_bars=6),
        tick(base + timedelta(minutes=60), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.05}),
    ]
    boundary = audit.recovery_boundary(rows, audit_ms=ms(base) + 90 * 60_000, since_ms=0)
    assert boundary["episode_in_progress"] is True
    assert boundary["open_episode"]["blocked_ticks"] == 1
    assert boundary["open_episode"]["resumed"] is False
    # the audited episode is the closed one, and its numbers stay its own
    assert boundary["resume"]["run_id"] == rows[3]["run_id"]
    assert boundary["recovery_latency_seconds"] == 900.0
    assert boundary["store_silence_minutes"] == pytest.approx(45.0)
    assert boundary["block_episode"]["blocked_ticks"] == 2


def test_a_log_whose_last_episode_closed_has_nothing_held_open():
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, outcome="OBSERVED", new_bars=3),
        tick(base + timedelta(minutes=15), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.2}),
        tick(base + timedelta(minutes=30), outcome="OBSERVED", new_bars=6),
    ]
    boundary = audit.recovery_boundary(rows, audit_ms=ms(base) + 60 * 60_000, since_ms=0)
    assert boundary["episode_in_progress"] is False
    assert boundary["open_episode"] is None
    assert boundary["store_silence_minutes"] == pytest.approx(30.0)


def test_the_ceiling_removes_only_the_days_that_are_already_lost():
    impact_rows = 2160
    lost = ["2026-10-23"]
    reachable = 3 * (impact_rows - 24 * len(lost))
    assert reachable == 6408
    assert reachable / 6480 < 1.0


# --------------------------------------------------------------------------- #
# the verifier
# --------------------------------------------------------------------------- #
def _verifier_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """A miniature package, state root, store and declaration the verifier will judge."""
    repo = tmp_path / "repo"
    package = repo / "docs/agentic/exp004a/wp051_02h"
    state = repo / "data/forward/edge04"
    store = repo / "data/forward/edge03"
    for path in (package, state, store / "1h", repo / "scripts"):
        path.mkdir(parents=True, exist_ok=True)
    # the verifier reads the two programs it judges out of the repo it is given
    for name in ("exp004a_wp051_02h_audit.py", "edge04_watchdog.py"):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)

    start = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    now_dt = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    rows = [
        tick(start + timedelta(minutes=5), outcome="OBSERVED", new_bars=12),
        tick(start + timedelta(minutes=10), outcome="DISK_BUDGET_EXCEEDED", exit_code=5,
             disk={"free_gib": 0.3}),
        tick(start + timedelta(minutes=25), outcome="OBSERVED", new_bars=12),
        tick(now_dt - timedelta(minutes=5), outcome="OBSERVED", new_bars=3),
    ]
    write_runs(state, rows)

    # BTC holds one late bar in the declared day; the other assets are clean once stored
    for asset in ("BTC", "ETH", "SOL"):
        lines = []
        for k in range(6):
            opened = ms(start) + k * HOUR
            lag = 5 * HOUR if (asset == "BTC" and k == 0) else 60_000
            lines.append(json.dumps(bar(opened, opened + HOUR + lag)))
        (store / "1h" / f"{asset}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    declaration = {
        "declaration_id": "TEST/v1",
        "effective_from_utc": "2026-10-23T00:00:00Z",
        "capture_window": {"start_utc": "2026-10-23T00:00:00Z", "end_utc": "2027-01-21T00:00:00Z", "days": 90},
        "lag_policy": {"bound_ms": 7_200_000},
        "coverage": {"required_fraction": 0.9},
        "entries": [{"row_count": 2160}, {"row_count": 2160}, {"row_count": 2160}],
    }
    (repo / "config/preregistrations").mkdir(parents=True, exist_ok=True)
    (repo / "config/preregistrations/EXP-004A.datasets.phase3.json").write_text(
        json.dumps(declaration), encoding="utf-8"
    )

    recovery = {
        "observer": {
            "runs_log_lines": len(rows),
            "last_tick_age_seconds": 300.0,
        },
        "tick_census": {
            "since_utc": "2026-10-23T00:00:00Z",
            "ticks": len(rows),
            "blocked": {"count": 1, "min_free_gib": 0.3},
        },
        "store": {"1h:BTC": {"last_open_utc": "2026-10-23T05:00:00.000Z"}},
        "recovered_observation": {"run_id": rows[2]["run_id"]},
        "verdict": "OBSERVER_RUNNING",
    }
    gap = {
        "declaration": {"sha256": "0" * 64},
        "phase_impact": {
            "lost_days_by_asset": {"BTC": ["2026-10-23"], "ETH": [], "SOL": []},
            "lost_days_any_asset": ["2026-10-23"],
            "rows_still_reachable": 6456,
            "fraction_still_reachable": 0.996296,
            "complete_rule": "admissible == declared",
            "status_now": "CEILING_BELOW_DECLARED",
            "coverage_complete_reachable": False,
        },
        "recovery_boundary": {
            "block_episode": {
                "first_blocked_start_utc": rows[1]["started_at_utc"],
                "last_blocked_start_utc": rows[1]["started_at_utc"],
            },
            "store_silence_minutes": 20.0,
            "recovery_latency_seconds": 900.0,
        },
    }
    continuity = {"requirements": []}
    root = {"claims": []}
    for name, payload in (
        ("RECOVERY_REPORT.json", recovery),
        ("COVERAGE_GAP_REPORT.json", gap),
        ("CONTINUITY_REPORT.json", continuity),
        ("ROOT_CAUSE.json", root),
    ):
        (package / name).write_text(json.dumps(payload), encoding="utf-8")
    return repo, package, state, store


def test_the_verifier_recomputes_the_ceiling_from_the_bars(tmp_path: Path):
    repo, package, state, store = _verifier_fixture(tmp_path)
    verdict, _detail = verifier.verify(repo, package, state, store)
    names = {check.name: check for check in verdict.checks}
    assert names["COVERAGE_CEILING"].ok is True
    assert names["LOST_DAYS_RECOMPUTED"].ok is True
    assert names["STORE_SILENCE_REPRODUCED"].ok is True


def test_the_verifier_fails_a_claim_that_hides_a_lost_day(tmp_path: Path):
    repo, package, state, store = _verifier_fixture(tmp_path)
    gap = json.loads((package / "COVERAGE_GAP_REPORT.json").read_text(encoding="utf-8"))
    gap["phase_impact"]["lost_days_by_asset"] = {"BTC": [], "ETH": [], "SOL": []}
    (package / "COVERAGE_GAP_REPORT.json").write_text(json.dumps(gap), encoding="utf-8")
    verdict, _detail = verifier.verify(repo, package, state, store)
    assert "LOST_DAYS_RECOMPUTED" in verdict.failed


def test_the_verifier_fails_a_ceiling_that_rounds_a_shortfall_away(tmp_path: Path):
    repo, package, state, store = _verifier_fixture(tmp_path)
    gap = json.loads((package / "COVERAGE_GAP_REPORT.json").read_text(encoding="utf-8"))
    gap["phase_impact"]["rows_still_reachable"] = 6480
    gap["phase_impact"]["fraction_still_reachable"] = 1.0
    (package / "COVERAGE_GAP_REPORT.json").write_text(json.dumps(gap), encoding="utf-8")
    verdict, _detail = verifier.verify(repo, package, state, store)
    assert "COVERAGE_CEILING" in verdict.failed


def test_the_verifier_keeps_the_recovery_claim_when_a_newer_refusal_is_open(tmp_path: Path):
    """A refusal after the last observation must not make the earlier recovery unnameable."""
    repo, package, state, store = _verifier_fixture(tmp_path)
    with (state / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                tick(
                    datetime(2026, 10, 23, 6, 10, tzinfo=UTC),
                    outcome="DISK_BUDGET_EXCEEDED",
                    exit_code=5,
                    disk={"free_gib": 0.2},
                ),
                sort_keys=True,
            )
            + "\n"
        )
    verdict, _detail = verifier.verify(repo, package, state, store)
    names = {check.name: check for check in verdict.checks}
    assert names["RECOVERY_CLAIM"].ok is True
    assert names["STORE_SILENCE_REPRODUCED"].ok is True


def test_the_verifier_does_not_import_what_it_judges():
    tree = __import__("ast").parse((SCRIPTS / "exp004a_wp051_02h_verify.py").read_text(encoding="utf-8"))
    imported = set()
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, __import__("ast").ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"trading_bot", "autonomous", "edge03", "incremental"})


def test_the_watchdog_imports_nothing_from_the_lane():
    tree = __import__("ast").parse((SCRIPTS / "edge04_watchdog.py").read_text(encoding="utf-8"))
    imported = set()
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, __import__("ast").ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"trading_bot", "autonomous", "edge03"})


def test_the_watchdog_names_no_way_to_trade():
    text = (SCRIPTS / "edge04_watchdog.py").read_text(encoding="utf-8")
    for token in ("place_order", "create_order", "submit_order", "api_secret", "live_trading=True"):
        assert token not in text
