"""WP-051-02I adversarial suite: the storage auditor, its verifier, and the watchdog's V2.

The pressure tests here never fill a real volume. The watchdog and the auditor both measure
free space through ``shutil.disk_usage``, so a test replaces *that* function with a reading it
controls and drives the state machine through every threshold: 1.9 GiB, 2.0 GiB, 4.9 GiB,
5.0 GiB, and the recovery on the other side. That is the same code path a real full volume
takes, with none of the risk -- and it is the only honest way to test "the disk filled" on a
host whose disk must keep working.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"

GIB = 1024**3


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = _load("edge04_watchdog_02i", "edge04_watchdog.py")
storage = _load("wp051_02i_storage", "exp004a_wp051_02i_storage.py")
verifier = _load("wp051_02i_verify", "exp004a_wp051_02i_verify.py")


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def tick(
    started: datetime,
    *,
    outcome: str = "OBSERVED",
    new_bars: int = 3,
    free: int | None = None,
    exit_code: int = 0,
) -> dict:
    row = {
        "run_id": f"FWD-EDGE04-{started.strftime('%Y%m%dT%H%M%SZ')}",
        "started_at_ms": ms(started),
        "started_at_utc": _stamp(started),
        "finished_at_utc": _stamp(started + timedelta(seconds=35)),
        "outcome": outcome,
        "exit_code": exit_code,
        "new_bars": new_bars,
    }
    if free is not None:
        row["disk"] = {"free_bytes": free}
        row["disk_after"] = {"free_bytes": free}
    return row


def write_runs(state_root: Path, rows: list[dict]) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "runs.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )


def disk(free_gib: float):
    total = 238 * GIB
    used = total - int(free_gib * GIB)
    return shutil._ntuple_diskusage(total, used, int(free_gib * GIB))


# --------------------------------------------------------------------------- #
# the watchdog: velocity and forecast
# --------------------------------------------------------------------------- #
def test_history_needs_three_days_before_it_reports_a_rate(tmp_path: Path):
    base = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    rows = [tick(base + timedelta(minutes=15 * i), free=4 * GIB) for i in range(8)]
    stats = watchdog.history_stats(watchdog.free_space_series(tmp_path / "none")["samples"])
    assert stats["status"] == "INSUFFICIENT_HISTORY"
    assert "required before a rate is reported" in stats["reason"]
    write_runs(tmp_path, rows)
    series = watchdog.free_space_series(tmp_path)
    assert len(series["samples"]) == 8
    assert watchdog.history_stats(series["samples"])["status"] == "INSUFFICIENT_HISTORY"


def test_the_forecast_uses_the_worst_day_not_the_average(tmp_path: Path):
    days = [
        (datetime(2026, 10, 19, tzinfo=UTC), [8.0] + [7.0] * 3),
        (datetime(2026, 10, 20, tzinfo=UTC), [7.0] + [3.0] * 3),
        (datetime(2026, 10, 21, tzinfo=UTC), [3.0] + [2.6] * 3),
    ]
    rows = []
    for start, values in days:
        rows.extend(
            tick(start + timedelta(minutes=15 * i), free=int(value * GIB))
            for i, value in enumerate(values)
        )
    write_runs(tmp_path, rows)
    series = watchdog.free_space_series(tmp_path)
    stats = watchdog.history_stats(series["samples"])
    assert stats["status"] == "MEASURED"
    assert stats["max_daily_drawdown_bytes"] == int(4.0 * GIB)
    ahead = watchdog.forecast({"free_bytes": int(4 * GIB)}, stats)
    assert ahead["label"] == "AT_RISK"
    # (4 GiB free - 2 GiB floor) / (4 GiB per day / 24 h) = 12 h
    assert ahead["hours_to_critical"] == pytest.approx(12.0, abs=0.01)


def test_the_forecast_is_unknown_rather_than_invented(tmp_path: Path):
    ahead = watchdog.forecast(
        {"free_bytes": int(4 * GIB)},
        {"status": "INSUFFICIENT_HISTORY", "reason": "one day", "max_daily_drawdown_bytes": None},
    )
    assert ahead["label"] == "UNKNOWN"
    assert ahead["hours_to_critical"] is None


# --------------------------------------------------------------------------- #
# the watchdog: states, events, and a volume that is already full
# --------------------------------------------------------------------------- #
def test_recovery_is_its_own_state_and_lowers_the_marker(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: disk(50))
    now_dt = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=3), free=int(1.0 * GIB))])
    watchdog.persist(
        tmp_path,
        {
            "generated_at_utc": "2026-10-23T11:45:00Z",
            "status": "BLOCKED",
            "exit_code": 8,
            "reasons": ["under the floor"],
        },
    )
    assert (tmp_path / "ATTENTION_REQUIRED.txt").exists()
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "RECOVERED"
    assert result["exit_code"] == 0
    assert result["recovered_from"] == "BLOCKED"
    state = watchdog.persist(tmp_path, result)
    assert state["marker"] == "ABSENT"
    assert not (tmp_path / "ATTENTION_REQUIRED.txt").exists()
    events = (tmp_path / "WATCHDOG_EVENTS.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(events[-1])["status"] == "RECOVERED"


def test_a_blocked_volume_is_blocked_whatever_the_tick_says(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: disk(1.9))
    now_dt = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=2), free=int(1.9 * GIB))])
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "BLOCKED"
    assert result["exit_code"] == 8


def test_a_degraded_volume_is_not_blocked_and_not_ok(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watchdog.shutil, "disk_usage", lambda _p: disk(4.9))
    now_dt = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    write_runs(tmp_path, [tick(now_dt - timedelta(minutes=2), free=int(4.9 * GIB))])
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "DEGRADED"
    assert result["exit_code"] == 1


def test_the_event_log_rotates_so_the_alarm_cannot_fill_the_disk(tmp_path: Path):
    events = tmp_path / watchdog.EVENTS_FILE
    events.write_text("x" * (watchdog.EVENTS_MAX_BYTES + 10), encoding="utf-8")
    state = watchdog.append_event(
        tmp_path,
        {
            "generated_at_utc": "2026-10-23T12:00:00Z",
            "status": "BLOCKED",
            "previous_status": "OK",
            "exit_code": 8,
            "reasons": ["under the floor"],
            "disk": {"free_gib": 1.5},
        },
    )
    assert state == "APPENDED"
    assert (tmp_path / "WATCHDOG_EVENTS.jsonl.1").exists()
    assert events.stat().st_size < 2048


def test_a_full_volume_does_not_turn_persist_into_a_traceback(tmp_path: Path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", refuse)
    state = watchdog.persist(
        tmp_path,
        {
            "generated_at_utc": "2026-10-23T12:00:00Z",
            "status": "BLOCKED",
            "previous_status": "OK",
            "exit_code": 8,
            "reasons": ["under the floor"],
        },
    )
    assert state["verdict_state"].startswith("ERROR")
    assert state["marker"].startswith("ERROR")


def test_escalation_records_a_refused_channel_instead_of_claiming_delivery(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv(watchdog.WEBHOOK_ENV, raising=False)
    monkeypatch.setattr(watchdog, "run", lambda *a, **k: (1, "", "Acceso denegado"))
    channels = watchdog.escalate(
        {
            "generated_at_utc": "2026-10-23T12:00:00Z",
            "status": "BLOCKED",
            "exit_code": 8,
            "reasons": ["under the floor"],
            "persisted": {"marker": "RAISED"},
        }
    )
    by_name = {item["channel"]: item for item in channels}
    assert by_name["scheduler_exit_code"]["effective"] is True
    assert by_name["marker_file"]["effective"] is True
    assert by_name["windows_event_log"]["effective"] is False
    assert "denegado" in by_name["windows_event_log"]["detail"].lower()
    assert by_name["webhook"]["effective"] is False
    assert watchdog.WEBHOOK_ENV in by_name["webhook"]["detail"]


def test_a_webhook_is_used_only_when_it_is_configured(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(watchdog.WEBHOOK_ENV, "https://example.invalid/hook")
    monkeypatch.setattr(watchdog, "run", lambda *a, **k: (0, "", ""))

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response())
    channels = watchdog.escalate({"status": "BLOCKED", "reasons": ["x"], "persisted": {}})
    webhook = next(item for item in channels if item["channel"] == "webhook")
    assert webhook["effective"] is True
    assert webhook["detail"] == "HTTP 204"


# --------------------------------------------------------------------------- #
# the auditor: episodes, sweep scope, and the projection
# --------------------------------------------------------------------------- #
def test_a_healthy_reading_ends_a_breach_episode(tmp_path: Path):
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    samples = [
        {"ts_ms": ms(base), "free_bytes": int(1.5 * GIB), "outcome": "DISK_BUDGET_EXCEEDED"},
        {"ts_ms": ms(base + timedelta(minutes=15)), "free_bytes": int(1.4 * GIB), "outcome": "DISK_BUDGET_EXCEEDED"},
        {"ts_ms": ms(base + timedelta(minutes=30)), "free_bytes": int(3.0 * GIB), "outcome": "OBSERVED"},
        {"ts_ms": ms(base + timedelta(minutes=45)), "free_bytes": int(1.9 * GIB), "outcome": "DISK_BUDGET_EXCEEDED"},
    ]
    breaches = storage.breach_episodes(samples)
    assert breaches["free_space_episode_count"] == 2
    assert breaches["refused_ticks"] == 3
    assert breaches["refusal_episode_count"] == 2


def test_a_volume_that_has_refused_is_insufficient_even_when_free_looks_fine():
    projection = storage.project(
        own_bytes_per_day=1_000_000,
        bytes_per_row=314.5,
        max_daily_drawdown_bytes=10 * GIB,
        current_free=100 * GIB,
        breaches={"refused_ticks": 1},
    )
    assert projection["verdict"] == "INSUFFICIENT"
    assert any("refused" in reason for reason in projection["verdict_reasons"])


def test_a_projection_that_ignores_the_drawdown_is_caught():
    generous = storage.project(
        own_bytes_per_day=1_000_000,
        bytes_per_row=314.5,
        max_daily_drawdown_bytes=0,
        current_free=3 * GIB,
        breaches={"refused_ticks": 0},
    )
    honest = storage.project(
        own_bytes_per_day=1_000_000,
        bytes_per_row=314.5,
        max_daily_drawdown_bytes=8 * GIB,
        current_free=3 * GIB,
        breaches={"refused_ticks": 0},
    )
    assert generous["verdict"] == "SUFFICIENT"
    assert honest["verdict"] == "INSUFFICIENT"
    assert honest["required_free_bytes"] - generous["required_free_bytes"] == 8 * GIB


def test_the_sweep_is_a_dry_run_until_it_is_applied(tmp_path: Path):
    cache = tmp_path / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"x" * 1024)
    dry = storage.sweep(tmp_path, apply=False)
    assert cache.exists()
    assert dry["reclaimable_bytes"] >= 1024
    assert dry["removed"] == []
    applied = storage.sweep(tmp_path, apply=True)
    assert not cache.exists()
    assert [item["path"] for item in applied["removed"]] == ["pkg/__pycache__"]


def _git_repo(root: Path) -> bool:
    for argv in (
        ["git", "init", "-q"],
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "add", "-A"],
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "seed"],
    ):
        completed = subprocess.run(argv, cwd=str(root), capture_output=True, text=True)
        if completed.returncode != 0:
            return False
    return True


def test_the_sweep_refuses_a_cache_that_git_tracks(tmp_path: Path):
    if not _git_repo(tmp_path):
        pytest.skip("git is not usable here")
    tracked = tmp_path / "tracked" / "__pycache__"
    tracked.mkdir(parents=True)
    (tracked / "kept.pyc").write_bytes(b"y" * 512)
    untracked = tmp_path / "loose" / "__pycache__"
    untracked.mkdir(parents=True)
    (untracked / "gone.pyc").write_bytes(b"z" * 512)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "add", str(tracked)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    result = storage.sweep(tmp_path, apply=True)
    assert tracked.exists(), "a tracked cache is evidence, not scratch"
    assert not untracked.exists()
    excluded = [item for item in result["candidates"] if not item["eligible"]]
    assert excluded and "Git tracks" in excluded[0]["excluded_because"]


# --------------------------------------------------------------------------- #
# the verifier: it has to be able to fail
# --------------------------------------------------------------------------- #
def test_the_verifier_fails_a_report_that_hides_a_refusal(tmp_path: Path):
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, outcome="DISK_BUDGET_EXCEEDED", new_bars=0, exit_code=5, free=int(1.2 * GIB)),
    ]
    write_runs(tmp_path, rows)
    parsed, _corrupt = verifier.lane_rows(tmp_path)
    report = {
        "history": {"last_at_utc": _stamp(base + timedelta(minutes=30))},
        "breaches": {"refused_ticks": 0, "refusal_episode_count": 0, "free_space_episode_count": 0},
    }
    checks = {item["id"]: item for item in verifier.check_refusals(report, parsed)}
    assert checks["REFUSALS_RECOMPUTED"]["status"] == "FAIL"


def test_the_verifier_fails_a_refusal_that_claims_bars(tmp_path: Path):
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [tick(base, outcome="DISK_BUDGET_EXCEEDED", new_bars=3, exit_code=5)]
    write_runs(tmp_path, rows)
    parsed, _ = verifier.lane_rows(tmp_path)
    report = {"breaches": {"refused_ticks": 1, "refusal_episode_count": 1}}
    checks = {item["id"]: item for item in verifier.check_refusals(report, parsed)}
    assert checks["A_REFUSAL_IS_NOT_A_CAPTURE"]["status"] == "FAIL"


def test_the_verifier_does_not_mistake_a_growing_log_for_a_mismatch(tmp_path: Path):
    base = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    rows = [
        tick(base, free=int(1.5 * GIB), outcome="DISK_BUDGET_EXCEEDED", new_bars=0, exit_code=5),
        tick(base + timedelta(minutes=15), free=int(1.4 * GIB), outcome="DISK_BUDGET_EXCEEDED", new_bars=0, exit_code=5),
        # written after the report was sealed:
        tick(base + timedelta(hours=2), free=int(1.0 * GIB), outcome="DISK_BUDGET_EXCEEDED", new_bars=0, exit_code=5),
    ]
    write_runs(tmp_path, rows)
    parsed, _ = verifier.lane_rows(tmp_path)
    report = {
        "history": {"last_at_utc": _stamp(base + timedelta(minutes=20))},
        "breaches": {"refused_ticks": 1, "refusal_episode_count": 1, "free_space_episode_count": 1},
    }
    # The third row arrived after the report's own last reading. With the window applied the
    # recomputation sees 2 refusals (so the report's 1 is wrong); without it, it would see 3
    # and the verifier would be measuring the lane's normal operation as a defect.
    checks = {item["id"]: item for item in verifier.check_refusals(report, parsed)}
    assert checks["REFUSALS_RECOMPUTED"]["status"] == "FAIL"
    assert "the tick log holds 2" in checks["REFUSALS_RECOMPUTED"]["detail"]


def test_the_verifier_counts_a_volatile_tree_separately(tmp_path: Path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "one.bin").write_bytes(b"a" * 4096)
    report = {
        "consumers": [
            {
                "id": "temp",
                "volatile": True,
                "measured": {"path": str(shared), "exists": True, "bytes": 4096},
            }
        ]
    }
    (shared / "two.bin").write_bytes(b"b" * 4096)  # somebody else is writing here
    checks = verifier.check_consumers(report)
    assert checks[0]["status"] == "PASS"
    assert checks[0]["evidence"]["volatile"][0]["growth"] > 0
