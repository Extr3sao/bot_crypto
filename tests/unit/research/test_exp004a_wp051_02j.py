"""WP-051-02J adversarial suite: classification, the lost day, the budget and the alarm.

The alert tests never put a notification on the operator's screen: the toast is a subprocess, so
it is replaced with a controlled answer and the *logic* is what gets tested -- dedup, receipt
handling, and what the watchdog does when the channel refuses. The one real end-to-end delivery
is evidence, recorded in ``ALERT_LEDGER.jsonl`` and re-read by the verifier, not something a unit
test fakes.
"""

from __future__ import annotations

import importlib.util
import json
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


recovery = _load("wp051_02j_recovery", "exp004a_wp051_02j_recovery.py")
watchdog = _load("edge04_watchdog_02j", "edge04_watchdog.py")


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
def test_only_this_packages_own_tree_is_ever_safe_owned(tmp_path: Path):
    path = tmp_path / "someone-elses-tree"
    path.mkdir()
    classification, why = recovery.classify(path=path, newest_age_h=500.0, hits=[], own=False)
    assert classification == recovery.REQUIRES_APPROVAL
    assert "not this package's" in why
    own, _ = recovery.classify(path=path, newest_age_h=500.0, hits=[], own=True)
    assert own == recovery.SAFE_OWNED


def test_a_process_holding_a_tree_beats_its_age(tmp_path: Path):
    path = tmp_path / "held"
    path.mkdir()
    hits = [{"name": "python.exe", "pid": "1234"}]
    classification, why = recovery.classify(path=path, newest_age_h=100.0, hits=hits, own=False)
    assert classification == recovery.ACTIVE_OR_PROTECTED
    assert "python.exe(1234)" in why


def test_a_recent_write_is_active_and_a_missing_mtime_is_unknown(tmp_path: Path):
    path = tmp_path / "recent"
    path.mkdir()
    fresh, _ = recovery.classify(path=path, newest_age_h=0.2, hits=[], own=False)
    assert fresh == recovery.ACTIVE_OR_PROTECTED
    unknown, why = recovery.classify(path=path, newest_age_h=None, hits=[], own=False)
    assert unknown == recovery.UNKNOWN
    assert "cannot be established" in why


# --------------------------------------------------------------------------- #
# the lost day
# --------------------------------------------------------------------------- #
def _write_store(root: Path, asset: str, rows: list[dict]) -> None:
    directory = root / "data" / "forward" / "edge03" / "1h"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{asset}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


def test_the_lost_day_counts_admissible_rows_and_never_invents_them(tmp_path: Path):
    day0 = int(datetime(2026, 10, 23, tzinfo=UTC).timestamp() * 1000)
    rows = []
    for hour in range(4):
        stamp = day0 + hour * 3_600_000
        rows.append({"ts": stamp, "fetched_at_ms": stamp + 3_600_000 + 5 * 60_000})
    for hour in (10, 11):
        stamp = day0 + hour * 3_600_000
        rows.append({"ts": stamp, "fetched_at_ms": stamp + 3_600_000 + 300 * 60_000})
    for asset in ("BTC", "ETH", "SOL"):
        _write_store(tmp_path, asset, rows)
    (tmp_path / "data" / "forward" / "edge04").mkdir(parents=True, exist_ok=True)
    lost = recovery.lost_rows(tmp_path)
    assert lost["assets"]["BTC"]["admissible"] == 4
    assert lost["assets"]["BTC"]["late_beyond_bound"] == 2
    assert lost["assets"]["BTC"]["missing"] == 18
    assert lost["admissible_rows"] == 12
    assert lost["declared_rows_for_the_day"] == 72
    assert "not repaired" in json.dumps(lost).lower() or lost["not_repaired"]


# --------------------------------------------------------------------------- #
# the budget
# --------------------------------------------------------------------------- #
def _write_runs(state_root: Path, rows: list[dict]) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "runs.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


def _day_rows(day: datetime, free_values: list[int]) -> list[dict]:
    rows = []
    for index, value in enumerate(free_values):
        stamp = day + timedelta(hours=index)
        rows.append(
            {
                "run_id": f"R-{day.date()}-{index}",
                "started_at_ms": int(stamp.timestamp() * 1000),
                "started_at_utc": _stamp(stamp),
                "outcome": "OBSERVED",
                "disk_after": {"free_bytes": value},
            }
        )
    return rows


def test_the_budget_uses_the_p90_drawdown_not_the_worst_day(tmp_path: Path, monkeypatch):
    rows = []
    for offset in range(10):
        day = datetime(2026, 10, 10, tzinfo=UTC) + timedelta(days=offset)
        start = 20 * GIB
        if offset == 0:
            rows.extend(_day_rows(day, [start, 10 * GIB, 10 * GIB]))  # a 10 GiB day
        else:
            rows.extend(_day_rows(day, [start, start - 1 * GIB, start - 1 * GIB]))
    _write_runs(tmp_path, rows)
    monkeypatch.setattr(recovery, "volume_free", lambda _p: {"free_bytes": 2 * GIB, "free_gib": 2.0, "total_bytes": 1, "used_percent": 1.0, "status": "WARNING"})
    plan = recovery.capacity(tmp_path, tmp_path)
    assert plan["drawdown"]["max_bytes"] == 10 * GIB
    assert plan["drawdown"]["p90_bytes"] < plan["drawdown"]["max_bytes"]
    assert plan["required"]["at_p90_bytes"] < plan["required"]["at_worst_bytes"]
    assert plan["verdict"] == "INSUFFICIENT"


def test_a_history_with_one_refusal_is_never_sufficient(tmp_path: Path, monkeypatch):
    day = datetime(2026, 10, 20, tzinfo=UTC)
    rows = _day_rows(day, [50 * GIB, 49 * GIB, 49 * GIB])
    rows[1]["outcome"] = "DISK_BUDGET_EXCEEDED"
    _write_runs(tmp_path, rows)
    monkeypatch.setattr(recovery, "volume_free", lambda _p: {"free_bytes": 60 * GIB, "free_gib": 60.0, "total_bytes": 1, "used_percent": 1.0, "status": "HEALTHY"})
    plan = recovery.capacity(tmp_path, tmp_path)
    assert plan["current_free_bytes"] > plan["required"]["at_worst_bytes"]
    assert plan["verdict"] == "INSUFFICIENT"


# --------------------------------------------------------------------------- #
# the alarm
# --------------------------------------------------------------------------- #
def _result(**overrides):
    base = {
        "generated_at_utc": "2026-10-23T12:00:00Z",
        "status": "BLOCKED",
        "previous_status": "OK",
        "exit_code": 8,
        "reasons": ["free space is under the floor"],
        "last_tick": {"started_at_utc": "2026-10-23T11:55:00Z"},
    }
    base.update(overrides)
    return base


def test_the_alert_id_is_deterministic_and_tag_safe():
    first = watchdog.alert_identity(_result())
    second = watchdog.alert_identity(_result())
    assert first == second
    assert first.startswith("EDGE04-BLOCKED-")
    assert len(first) <= 64
    assert all(character.isalnum() or character in "-_" for character in first)


def test_a_second_identical_condition_is_suppressed_and_recorded(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        payload = json.dumps({"shown": True, "receipt": True, "history": 3, "error": None})
        return 0, payload, ""

    monkeypatch.setattr(watchdog, "run", fake_run)
    first = watchdog.deliver_alert(tmp_path, _result())
    second = watchdog.deliver_alert(tmp_path, _result())
    assert first["receipt"] is True
    assert "suppressed" in second and second["receipt"] is False
    assert len(calls) == 1, "the second attempt must not reach the delivery channel"
    ledger = [json.loads(line) for line in (tmp_path / "ALERT_LEDGER.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(ledger) == 2
    assert ledger[1]["suppressed"]


def test_a_channel_that_cannot_prove_receipt_is_not_delivery(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        watchdog,
        "run",
        lambda *a, **k: (3, json.dumps({"shown": False, "receipt": False, "error": "no session"}), ""),
    )
    entry = watchdog.deliver_alert(tmp_path, _result())
    assert entry["receipt"] is False
    assert entry["channels"][0]["receipt"] is False
    assert "no session" in entry["channels"][0]["error"]


def test_the_supervisor_raises_when_the_watchdog_is_silent(tmp_path: Path, monkeypatch):
    old = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    (tmp_path / "WATCHDOG.json").write_text(
        json.dumps({"generated_at_utc": _stamp(old), "status": "OK"}), encoding="utf-8"
    )
    monkeypatch.setattr(watchdog, "now", lambda: datetime(2026, 10, 23, 12, 0, tzinfo=UTC))
    monkeypatch.setattr(watchdog, "deliver_alert", lambda root, result, force=False: {"alert_id": "X", "receipt": True})
    supervised = watchdog.supervise(tmp_path)
    assert supervised["status"] == "WATCHDOG_SILENT"
    assert supervised["exit_code"] == watchdog.EXIT_WATCHDOG_SILENT
    assert supervised["watchdog_age_seconds"] == pytest.approx(10800, abs=1)
    assert (tmp_path / "SUPERVISOR.json").exists()


def test_the_supervisor_is_quiet_when_the_watchdog_is_alive(tmp_path: Path, monkeypatch):
    recent = datetime(2026, 10, 23, 11, 58, tzinfo=UTC)
    (tmp_path / "WATCHDOG.json").write_text(
        json.dumps({"generated_at_utc": _stamp(recent), "status": "DEGRADED"}), encoding="utf-8"
    )
    monkeypatch.setattr(watchdog, "now", lambda: datetime(2026, 10, 23, 12, 0, tzinfo=UTC))
    supervised = watchdog.supervise(tmp_path)
    assert supervised["status"] == "WATCHDOG_ALIVE"
    assert supervised["exit_code"] == 0
    assert "delivery" not in supervised


def test_a_stale_supervisor_degrades_the_watchdog(tmp_path: Path, monkeypatch):
    now_dt = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    rows = [
        {
            "run_id": "R1",
            "started_at_ms": int((now_dt - timedelta(minutes=3)).timestamp() * 1000),
            "started_at_utc": _stamp(now_dt - timedelta(minutes=3)),
            "finished_at_utc": _stamp(now_dt - timedelta(minutes=3)),
            "outcome": "OBSERVED",
            "new_bars": 3,
            "exit_code": 0,
            "disk_after": {"free_bytes": 40 * GIB},
        }
    ]
    _write_runs(tmp_path, rows)
    (tmp_path / "SUPERVISOR.json").write_text(
        json.dumps({"generated_at_utc": _stamp(now_dt - timedelta(hours=3))}), encoding="utf-8"
    )
    monkeypatch.setattr(
        watchdog,
        "disk_reading",
        lambda _p: {"free_bytes": 40 * GIB, "free_gib": 40.0, "total_bytes": 100 * GIB, "used_percent": 60.0, "status": "HEALTHY"},
    )
    result = watchdog.check(state_root=tmp_path, now_dt=now_dt)
    assert result["status"] == "DEGRADED"
    assert any("supervisor" in reason for reason in result["reasons"])


def test_an_unwritable_ledger_is_reported_not_raised(tmp_path: Path):
    """A full or locked volume must not turn the alarm into a second failure."""
    (tmp_path / "ALERT_LEDGER.jsonl").mkdir()
    status = watchdog._append_ledger(tmp_path, {"alert_id": "X", "receipt": True})
    assert status.startswith("ERROR:"), status


def test_evidence_is_written_atomically_and_reads_back(tmp_path: Path):
    payload = {"schema_version": "X", "value": 1, "nested": {"a": [1, 2, 3]}}
    recovery.write_json(tmp_path / "EVIDENCE.json", payload)
    assert json.loads((tmp_path / "EVIDENCE.json").read_text(encoding="utf-8")) == payload
    assert not list(tmp_path.glob("*.part")), "a partial file survived the write"


def test_cleaning_skips_a_cache_directory_git_tracks(tmp_path: Path, monkeypatch):
    """The clean list is a whitelist of names, not a licence: a tracked cache stays."""
    untracked = tmp_path / "pkg" / "__pycache__"
    untracked.mkdir(parents=True)
    (untracked / "a.pyc").write_bytes(b"x" * 512)
    tracked = tmp_path / "keep" / "__pycache__"
    tracked.mkdir(parents=True)
    (tracked / "keep.pyc").write_bytes(b"y" * 512)

    def fake_git(_cwd, *args):
        if "ls-files" in args and args[-1] == "keep/__pycache__":
            return "keep/__pycache__/keep.pyc"
        return ""

    monkeypatch.setattr(recovery, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(recovery, "git", fake_git)
    monkeypatch.setattr(
        recovery,
        "volume_free",
        lambda _p: {"free_bytes": 10 * GIB, "free_gib": 10.0, "total_bytes": 1, "used_percent": 1.0, "status": "HEALTHY"},
    )
    out = tmp_path / "out"
    out.mkdir()
    payload = recovery.clean_own(out)
    assert not untracked.exists()
    assert tracked.joinpath("keep.pyc").exists()
    assert any("pkg/__pycache__" in item["path"] for item in payload["removed"])
    assert any("keep/__pycache__" in item["path"] for item in payload["kept"])
    assert payload["deleted_bytes"] >= 0
    assert (out / "CLEANUP_EVIDENCE.json").exists()
