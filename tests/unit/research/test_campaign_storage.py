"""CAP-004C — the campaign's storage contract must stay BOUNDED.

The failure this file pins down is operational, not scientific: the campaign was
writing a full snapshot of itself every cycle, so each record was an order of
magnitude larger than the previous one.  On 2026-10-07 that consumed ~7 GiB/day,
filled the host, and then *aborted a real cycle inside the reader* — a 7.9 GiB
journal with GiB-sized lines was being loaded with ``read_text().splitlines()``.
The campaign kept producing heartbeats while producing no evidence at all.

So these tests assert the properties that make a long campaign survivable:

* one cycle writes O(1) bytes, and 1000 cycles are still small (no amplification);
* the journal is read with a hard per-line cap, so a legacy or corrupt line can
  never again abort a cycle that is in the middle of a real settlement;
* the daily projection aggregates a day instead of embedding it;
* segmentation preserves the journal's hash chain, and every segment carries its
  own digest in a manifest;
* a crash during rotation or during a projection update cannot destroy the
  previous state (atomic rename, never truncate-and-rebuild);
* the disk guard reports an honest forecast (a number only when the measured rate
  is stable) and refuses NEW decisions — never settlements — when critical.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research import campaign_reporting as cr
from trading_bot.research import disk_space as ds

REPO = Path(__file__).resolve().parents[3]

#: Per-cycle bound derived from the compact contract: the largest event the
#: contract can produce is ~1 KiB, so 4 KiB per NOOP cycle is a generous ceiling
#: that still fails loudly if anyone re-introduces whole-state snapshots.
MAX_BYTES_PER_NOOP_CYCLE = 4096

#: A day of cycles at the campaign's 15-minute cadence.
CYCLES_PER_DAY = 96


def _load_runner() -> Any:
    path = REPO / "scripts" / "cap004_campaign_runner.py"
    spec = importlib.util.spec_from_file_location("cap004_campaign_runner_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cycle_record(cycle: int, *, day: str = "2026-10-07", errors: list | None = None) -> dict[str, Any]:
    return {
        "cycle": cycle,
        "campaign_id": "CAP004-REAL-DECISIONS-V1",
        "day": day,
        "started_at": 1_791_388_800 + cycle * 900,
        "started_at_utc": "2026-10-07T16:00:00Z",
        "finished_at": 1_791_388_900 + cycle * 900,
        "modes": ["seal", "settle", "score", "verify"],
        "seal": {"sealed": []},
        "settle": {"settled": []},
        "counters": {"evaluated_decisions": 0, "sealed_decisions": 4, "pending_decisions": 4},
        "chain": {"status": "INTACT"},
        "drift": {"status": "NO_DRIFT"},
        "verify": {"status": "PASS", "passed": 192, "total": 192, "mismatches": 0, "false_success": 0},
        "errors": list(errors or []),
    }


class _StubLedger:
    """The daily projection only reads the three ledgers; nothing else is used."""

    def decisions(self) -> list[dict[str, Any]]:
        return []

    def outcomes(self) -> list[dict[str, Any]]:
        return []

    def evaluations(self) -> list[dict[str, Any]]:
        return []


# --------------------------------------------------------------------------- #
# the compact event contract
# --------------------------------------------------------------------------- #


def test_cycle_event_matches_the_declared_contract() -> None:
    event = cr.cycle_event(_cycle_record(3), previous_hash=cr.CYCLE_GENESIS_HASH)
    assert set(event) == set(cr.CYCLE_EVENT_KEYS)
    assert event["event_version"] == cr.CYCLE_JOURNAL_VERSION
    assert event["previous_event_hash"] == cr.CYCLE_GENESIS_HASH
    assert event["cycle"] == 3
    assert event["actions_due"] == ["seal", "settle", "score", "verify"]
    assert event["verifier_result"]["status"] == "PASS"
    # The event carries the delta, not the population it was derived from.
    assert event["sealed_count_delta"] == 0
    assert "counters" not in json.dumps(event)


def test_cycle_event_does_not_grow_with_the_payload_it_projects() -> None:
    """A record carrying megabytes of state must still produce a ~1 KiB event."""
    record = _cycle_record(4)
    record["daily"] = {"cycles": ["x" * 4_000_000]}
    record["counters"]["decision_states"] = [{"state": "DECISION_SEALED"}] * 5_000
    event = cr.cycle_event(record, previous_hash=cr.CYCLE_GENESIS_HASH)
    size = len(json.dumps(event, sort_keys=True))
    assert size < 4096, f"compact event grew to {size} bytes"


def test_journal_is_bounded_over_a_thousand_noop_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAP-004C §31: 1000 cycles have a derived upper bound, and it holds."""
    monkeypatch.setattr(cr, "CYCLE_SEGMENT_MAX_BYTES", 8 * 1024)
    for cycle in range(1000):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle))
    total = sum(
        path.stat().st_size
        for path in [*cr.cycle_journal_segments(tmp_path), tmp_path / cr.CYCLE_JOURNAL_FILENAME]
        if path.is_file()
    )
    assert total <= 1000 * MAX_BYTES_PER_NOOP_CYCLE, f"{total} bytes for 1000 noop cycles"
    # Segmented, not one file that grows forever.
    segments = cr.cycle_journal_segments(tmp_path)
    assert segments, "a 1000-cycle journal must have been segmented"
    assert (tmp_path / cr.CYCLE_SEGMENT_DIRNAME / "manifest.json").is_file()


def test_noop_cycle_writes_only_operational_minimum(tmp_path: Path) -> None:
    """§32: a cycle that seals/settles/evaluates nothing is small."""
    before = sum(
        path.stat().st_size
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    cr.write_cycle_record(tmp_path, _cycle_record(1))
    after = sum(
        path.stat().st_size
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert after - before <= MAX_BYTES_PER_NOOP_CYCLE


# --------------------------------------------------------------------------- #
# bounded reads — the defect that aborted a real cycle
# --------------------------------------------------------------------------- #


def test_journal_read_skips_a_giant_line_without_exhausting_memory(tmp_path: Path) -> None:
    """DEF-CAMPAIGN-STORAGE-001: a multi-MiB line must be skipped, not loaded."""
    good = cr.cycle_event(_cycle_record(7), previous_hash=cr.CYCLE_GENESIS_HASH)
    path = tmp_path / cr.CYCLE_JOURNAL_FILENAME
    with path.open("wb") as handle:
        handle.write(json.dumps(good).encode("utf-8") + b"\n")
        handle.write(b'{"cycle": 8, "daily": "' + b"z" * (4 << 20) + b'"}\n')
        handle.write(json.dumps(good).encode("utf-8") + b"\n")
    events = cr.read_cycle_journal(tmp_path)
    assert [event["cycle"] for event in events] == [7, 7]
    diagnostics = cr.journal_read_diagnostics(tmp_path)
    assert diagnostics["oversized_lines"] == 1
    assert diagnostics["lines"] == 2


def test_journal_tail_and_day_filters_do_not_require_the_whole_history(tmp_path: Path) -> None:
    for cycle in range(10):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle, day=f"2026-10-{5 + cycle % 2:02d}"))
    assert len(cr.read_cycle_journal(tmp_path)) == 10
    assert len(cr.read_cycle_journal(tmp_path, limit=3)) == 3
    assert cr.read_cycle_journal(tmp_path, limit=3)[-1]["cycle"] == 9
    filtered = cr.read_cycle_journal(tmp_path, day="2026-10-05")
    assert filtered and {item["day"] for item in filtered} == {"2026-10-05"}


def test_unparsable_line_is_counted_and_never_hides_the_rest(tmp_path: Path) -> None:
    path = tmp_path / cr.CYCLE_JOURNAL_FILENAME
    path.write_text("{not json}\n", encoding="utf-8")
    cr.write_cycle_record(tmp_path, _cycle_record(1))
    assert [event["cycle"] for event in cr.read_cycle_journal(tmp_path)] == [1]
    assert cr.journal_read_diagnostics(tmp_path)["unparsable_lines"] == 1


# --------------------------------------------------------------------------- #
# bounded daily projection
# --------------------------------------------------------------------------- #


def test_daily_projection_stays_bounded_across_a_full_day(tmp_path: Path) -> None:
    """§33: many cycles of the same day must not make the projection grow."""
    for cycle in range(CYCLES_PER_DAY):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle))
    events = cr.read_cycle_journal(tmp_path, day="2026-10-07")
    payload = cr.daily_report(
        day="2026-10-07",
        ledger=_StubLedger(),
        cycles=events,
        chain={"status": "INTACT"},
        drift={"status": "NO_DRIFT", "drifted": []},
    )
    size = len(json.dumps(payload, sort_keys=True))
    assert payload["cycle_count"] == CYCLES_PER_DAY
    assert payload["cycles_omitted"] == CYCLES_PER_DAY - cr.DAILY_CYCLE_TAIL
    assert len(payload["cycles_tail"]) == cr.DAILY_CYCLE_TAIL
    assert size < 64 * 1024, f"daily projection grew to {size} bytes"


def test_daily_projection_counts_deltas_and_keeps_failure_codes(tmp_path: Path) -> None:
    cr.write_cycle_record(tmp_path, _cycle_record(1))
    cr.write_cycle_record(tmp_path, _cycle_record(2, errors=[{"code": "DATA_BLOCKED", "detail": "x"}]))
    payload = cr.daily_report(
        day="2026-10-07",
        ledger=_StubLedger(),
        cycles=cr.read_cycle_journal(tmp_path, day="2026-10-07"),
        chain={"status": "INTACT"},
        drift={"status": "NO_DRIFT", "drifted": []},
    )
    assert payload["report_version"] == cr.DAILY_REPORT_VERSION
    assert payload["failure_count"] == 1
    assert payload["failures"][0]["error_codes"] == ["DATA_BLOCKED"]
    assert payload["failures"][0]["cycle"] == 2


# --------------------------------------------------------------------------- #
# segmentation, hash chain, crash safety
# --------------------------------------------------------------------------- #


def test_rotation_preserves_the_chain_and_records_each_segment_digest(tmp_path: Path) -> None:
    for cycle in range(5):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle))
    assert cr.rotate_cycle_journal(tmp_path, force=True)["status"] == "ROTATED"
    # Growing further must continue the chain from the closed segment.
    for cycle in range(5, 8):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle))
    chain = cr.verify_cycle_chain(tmp_path)
    assert chain["status"] == "INTACT"
    assert chain["events"] == 8
    manifest = cr.read_segment_manifest(tmp_path)
    assert len(manifest["segments"]) == 1
    entry = manifest["segments"][0]
    assert entry["records"] == 5
    assert entry["first_cycle"] == 0
    assert entry["last_cycle"] == 4
    import hashlib

    digest = hashlib.sha256(
        (tmp_path / cr.CYCLE_SEGMENT_DIRNAME / entry["segment"]).read_bytes()
    ).hexdigest()
    assert entry["sha256"] == digest
    assert len(cr.read_cycle_journal(tmp_path)) == 8


def test_crash_during_rotation_leaves_the_journal_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§34: a crash while rolling must leave either state, never neither."""
    for cycle in range(3):
        cr.write_cycle_record(tmp_path, _cycle_record(cycle))

    real_replace = os.replace

    def explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("simulated crash during rotation")

    monkeypatch.setattr(cr.os, "replace", explode)
    with pytest.raises(OSError):
        cr.rotate_cycle_journal(tmp_path, force=True)
    monkeypatch.setattr(cr.os, "replace", real_replace)
    assert [event["cycle"] for event in cr.read_cycle_journal(tmp_path)] == [0, 1, 2]
    assert cr.verify_cycle_chain(tmp_path)["status"] == "INTACT"
    assert cr.rotate_cycle_journal(tmp_path, force=True)["status"] == "ROTATED"
    assert len(cr.read_cycle_journal(tmp_path)) == 3


def test_crash_during_projection_update_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§15: write temp + verify + atomic rename, never truncate then rebuild."""
    target = tmp_path / "daily" / "2026-10-07.json"
    cr.write_daily_report(tmp_path, {"day": "2026-10-07", "cycle_count": 1})
    original = target.read_text(encoding="utf-8")

    def explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("simulated crash during projection update")

    monkeypatch.setattr(cr.os, "replace", explode)
    with pytest.raises(OSError):
        cr.write_daily_report(tmp_path, {"day": "2026-10-07", "cycle_count": 2})
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == original
    assert json.loads(original)["cycle_count"] == 1


def test_interrupted_append_cannot_half_write_a_line(tmp_path: Path) -> None:
    """A torn tail is skipped by the reader instead of poisoning the journal."""
    cr.write_cycle_record(tmp_path, _cycle_record(1))
    path = tmp_path / cr.CYCLE_JOURNAL_FILENAME
    with path.open("ab") as handle:
        handle.write(b'{"cycle": 2, "event_ve')
    events = cr.read_cycle_journal(tmp_path)
    assert [event["cycle"] for event in events] == [1]  # the torn tail is skipped
    assert cr.journal_read_diagnostics(tmp_path)["unparsable_lines"] == 1


# --------------------------------------------------------------------------- #
# disk guard
# --------------------------------------------------------------------------- #


def test_disk_status_thresholds_are_the_documented_ones(tmp_path: Path) -> None:
    report = ds.disk_report(tmp_path)
    free = report["free_bytes"]
    expected = (
        ds.HEALTHY
        if free >= ds.HEALTHY_FREE_BYTES
        else ds.WARNING
        if free >= ds.CRITICAL_FREE_BYTES
        else ds.CRITICAL
    )
    assert report["status"] == expected
    assert report["warning_free_bytes"] == ds.HEALTHY_FREE_BYTES
    assert report["critical_free_bytes"] == ds.CRITICAL_FREE_BYTES


def test_guard_refuses_new_decisions_only_when_critical(tmp_path: Path) -> None:
    healthy = ds.DiskSpaceGuard(tmp_path)
    allowed, code = healthy.allows_new_decision()
    assert isinstance(allowed, bool) and (code is None or code == "NO_NEW_DECISION_DISK_CRITICAL")
    impossible = ds.DiskSpaceGuard(tmp_path, warning_bytes=10**18, critical_bytes=10**18 - 1)
    allowed, code = impossible.allows_new_decision()
    assert allowed is False and code == "NO_NEW_DECISION_DISK_CRITICAL"


def test_growth_rate_is_reported_only_when_it_is_stable() -> None:
    assert ds.growth_rate([])["status"] == "UNKNOWN"
    stable = [ds.GrowthSample(timestamp=1_791_388_800 + day * 86_400, bytes=day * 100 * 86_400) for day in range(6)]
    measured = ds.growth_rate(stable)
    assert measured["status"] == "MEASURED"
    assert measured["bytes_per_day"] == pytest.approx(100 * 86_400, rel=1e-6)
    volatile = [
        ds.GrowthSample(timestamp=1_791_388_800, bytes=0),
        ds.GrowthSample(timestamp=1_791_388_800 + 300, bytes=3 * 1024**3),
        ds.GrowthSample(timestamp=1_791_388_800 + 600, bytes=0),
    ]
    unstable = ds.growth_rate(volatile)
    assert unstable["status"] == "VOLATILE"
    assert unstable["bytes_per_day"] is None


def test_estimate_days_to_threshold_is_none_without_a_rate() -> None:
    assert (
        ds.estimate_days_to_threshold(free_bytes=10**12, threshold_bytes=10**9, growth_bytes_per_day=None)
        is None
    )
    assert ds.estimate_days_to_threshold(
        free_bytes=10**12, threshold_bytes=10**9, growth_bytes_per_day=10**9
    ) == pytest.approx(999.0)
    assert (
        ds.estimate_days_to_threshold(
            free_bytes=10**9, threshold_bytes=10**9, growth_bytes_per_day=10**9
        )
        == 0.0
    )


def test_transition_events_are_exactly_once_per_transition() -> None:
    report = {"free_bytes": 1, "free_gib": 0.0, "warning_free_bytes": 2, "critical_free_bytes": 3}
    first = ds.transition_event(previous_status=ds.HEALTHY, status=ds.WARNING, report=report, timestamp=10)
    assert first is not None and first["event"] == "DISK_WARNING"
    repeat = ds.transition_event(previous_status=ds.WARNING, status=ds.WARNING, report=report, timestamp=20)
    assert repeat is None
    critical = ds.transition_event(previous_status=ds.WARNING, status=ds.CRITICAL, report=report, timestamp=30)
    assert critical is not None and critical["event"] == "DISK_CRITICAL"
    recovered = ds.transition_event(previous_status=ds.CRITICAL, status=ds.HEALTHY, report=report, timestamp=40)
    assert recovered is not None and recovered["event"] == "DISK_RECOVERED"
    assert (
        ds.transition_event(previous_status=ds.HEALTHY, status=ds.HEALTHY, report=report, timestamp=50) is None
    )


def test_guard_forecast_uses_the_measured_rate(tmp_path: Path) -> None:
    now = 1_791_388_800
    samples = [
        ds.GrowthSample(timestamp=now - 86_400, bytes=0),
        ds.GrowthSample(timestamp=now, bytes=1024**3),
    ]
    report = ds.DiskSpaceGuard(tmp_path).report(samples=samples)
    rate = report["growth"]
    assert rate["status"] in {"MEASURED", "VOLATILE"}
    if rate["status"] == "MEASURED":
        assert report["estimated_days_to_warning"] == pytest.approx(
            max(0.0, (report["free_bytes"] - ds.HEALTHY_FREE_BYTES) / rate["bytes_per_day"]), abs=0.01
        )


# --------------------------------------------------------------------------- #
# per-cycle storage accounting (runner helpers)
# --------------------------------------------------------------------------- #


def test_storage_sample_measures_the_campaign_tree(tmp_path: Path) -> None:
    runner = _load_runner()
    report_root = tmp_path / "reports" / "cap004"
    ledger_root = tmp_path / "evidence"
    report_root.mkdir(parents=True)
    ledger_root.mkdir(parents=True)
    (report_root / "blob.json").write_bytes(b"x" * 1234)
    (ledger_root / "decisions.jsonl").write_bytes(b"y" * 10)
    sample = runner.storage_sample(report_root=report_root, ledger_root=ledger_root, now=1_791_388_800)
    assert sample["reports_cap004_bytes"] == 1234
    assert sample["evidence_bytes"] == 10
    assert sample["repo_bytes"] == 1244
    assert sample["free_bytes"] > 0
    assert sample["day"] == "2026-10-07"


def test_storage_samples_are_a_bounded_ring_buffer(tmp_path: Path) -> None:
    runner = _load_runner()
    for index in range(runner.STORAGE_SAMPLE_LIMIT + 5):
        samples = runner.append_storage_sample(tmp_path, {"timestamp": index, "reports_cap004_bytes": index})
    assert len(samples) == runner.STORAGE_SAMPLE_LIMIT
    assert samples[-1]["timestamp"] == runner.STORAGE_SAMPLE_LIMIT + 4
    assert len(runner.load_storage_samples(tmp_path)) == runner.STORAGE_SAMPLE_LIMIT


def test_forecast_never_spans_a_certified_migration(tmp_path: Path) -> None:
    """The compaction step must not be reported as negative growth.

    Real series: 20 GiB, 20 GiB + 300 KiB/day, then a migration drops the tree to
    1 GiB, then it keeps growing at 300 KiB/day.  Without the boundary the rate is
    dominated by the drop (VOLATILE, `None`); with it the post-migration growth is
    the one measured.
    """
    runner = _load_runner()
    start = 1_791_388_800
    per_day = 300 * 1024
    samples = [
        {"timestamp": start, "reports_cap004_bytes": 20 * 1024**3},
        {"timestamp": start + 900, "reports_cap004_bytes": 20 * 1024**3 + per_day // 96},
        {"timestamp": start + 1800, "reports_cap004_bytes": 1024**3},
        {"timestamp": start + 2700, "reports_cap004_bytes": 1024**3 + per_day // 96},
        {"timestamp": start + 3600, "reports_cap004_bytes": 1024**3 + 2 * (per_day // 96)},
    ]
    mixed = ds.growth_rate(runner.growth_samples(samples))
    assert mixed["status"] == "VOLATILE" and mixed["bytes_per_day"] is None

    archive = tmp_path / "archive" / "legacy-20261007T1556Z"
    archive.mkdir(parents=True)
    (archive / runner.MIGRATION_MANIFEST_FILENAME).write_text(
        json.dumps({"migration_version": "CAP004C_STORAGE_MIGRATION_V1", "timestamp": start + 1800}),
        encoding="utf-8",
    )
    assert runner.storage_discontinuities(tmp_path) == start + 1800
    post = ds.growth_rate(runner.growth_samples(samples), after=start + 1800)
    assert post["status"] == "MEASURED"
    assert post["bytes_per_day"] == pytest.approx(per_day, rel=1e-6)
    assert post["discarded_samples"] == 3  # the boundary sample itself belongs to the old series
    assert post["since"] == start + 1800


def test_a_missing_or_broken_manifest_never_invents_a_boundary(tmp_path: Path) -> None:
    runner = _load_runner()
    assert runner.storage_discontinuities(tmp_path) is None
    archive = tmp_path / "archive" / "legacy-broken"
    archive.mkdir(parents=True)
    (archive / runner.MIGRATION_MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    assert runner.storage_discontinuities(tmp_path) is None
