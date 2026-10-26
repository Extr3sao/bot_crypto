"""Storage retention tests: nothing is deleted before it has been replaced (§5-§11).

The dangerous operation in this subsystem is deletion, so these tests attack it:
a raw segment must survive every failure mode of the aggregate that is supposed
to replace it, and the capacity arithmetic must never claim a disk is bigger
than it is.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.research.forward.contract import (
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.retention import (
    AGGREGATED_ROOT,
    COMPACTION_MARKED,
    EXTERNAL_STORAGE_REQUIRED,
    LINEAGE_ROOT,
    RAW_ROOT,
    REPORT_ROOT,
    RETENTION_POLICY_VERSION,
    VIABLE,
    RetentionPolicy,
    apply_retention,
    capacity_report,
    compact_window,
    lineage_path,
    plan_retention,
    policy_for_host,
    read_compaction_markers,
    verify_sealed_segment,
)
from trading_bot.research.forward.storage import SegmentWriter, StorageError, sha256_file

RUN_ID = "run-retention-1"
MINUTE_MS = 60_000
ROTATION = 900


def _trade(*, ts_ms: int, price: str = "100.5", qty: str = "2", agg_id: int = 1) -> RawEvent:
    return RawEvent(
        event_type=EventType.AGG_TRADE,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@aggTrade",
        transport=Transport.WS,
        run_id=RUN_ID,
        exchange_event_id=str(agg_id),
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 25,
        process_time=ts_ms + 26,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price=price,
        quantity=qty,
        aggressor_side="buy",
    )


def _capture_window(root: Path, *, bucket_start_ms: int, trades: int = 5) -> Path:
    """Write one sealed raw segment and return its path."""
    writer = SegmentWriter(root, rotation_seconds=ROTATION, run_id=RUN_ID)
    for index in range(trades):
        writer.write(_trade(ts_ms=bucket_start_ms + index * MINUTE_MS, agg_id=index + 1))
    writer.close()
    files = sorted((root / RAW_ROOT).rglob("*.jsonl.gz"))
    assert len(files) == 1, files
    return files[0]


def _policy(**changes: object) -> RetentionPolicy:
    base = RetentionPolicy(
        rotation_seconds=ROTATION,
        raw_hot_hours=1.0,
        sealed_grace_seconds=0,
    )
    return replace(base, **changes) if changes else base  # type: ignore[arg-type]


def _window_start_ms() -> int:
    """A real, rotation-aligned window start just before now.

    The sealing check compares file mtime against the caller's ``now_ms``, so a
    synthetic date in the past would make every freshly written segment look
    "still warm".
    """
    now_ms = int(time.time() * 1000)
    width = ROTATION * 1000
    return (now_ms // width) * width


# --------------------------------------------------------------------- sealing


def test_a_sealed_segment_is_proven_sealed(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    path = _capture_window(tmp_path, bucket_start_ms=bucket)
    ok, reason = verify_sealed_segment(path, grace_seconds=0, now_ms=bucket + 10_000_000)
    assert ok, reason
    assert "sealed" in reason


def test_a_recently_written_segment_is_not_considered_sealed(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    path = _capture_window(tmp_path, bucket_start_ms=bucket)
    ok, reason = verify_sealed_segment(path, grace_seconds=86_400, now_ms=bucket)
    assert not ok
    assert "still warm" in reason


def test_a_truncated_segment_is_never_sealed(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    path = _capture_window(tmp_path, bucket_start_ms=bucket)
    payload = path.read_bytes()
    path.write_bytes(payload[:-12])  # strip the gzip trailer
    ok, reason = verify_sealed_segment(path, grace_seconds=0, now_ms=bucket + 10_000_000)
    assert not ok
    assert "gzip" in reason or "partial" in reason


# ------------------------------------------------------------------ compaction


def test_compaction_records_full_lineage_and_marks_the_window(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket, trades=7)
    policy = _policy()
    result = compact_window(
        tmp_path, policy, RUN_ID, bucket, bucket + ROTATION * 1000, [segment]
    )
    record = result.lineage
    digest, size = sha256_file(segment)
    assert record.policy_version == RETENTION_POLICY_VERSION
    assert record.run_id == RUN_ID
    assert record.timeframes_minutes == (1, 5, 15, 30)
    assert record.output_rows >= 5
    assert record.sources[0].sha256 == digest
    assert record.sources[0].bytes == size
    assert record.sources[0].rows == 7
    assert record.sources[0].stream == "spot/BTCUSDT/agg_trade"
    assert record.window_start_ms == bucket
    assert record.window_end_ms == bucket + ROTATION * 1000

    # The lineage is beside the aggregate *and* inside it (§9).
    assert lineage_path(tmp_path, RUN_ID, bucket).exists()
    envelope = json.loads(gzip.decompress((tmp_path / record.output_path).read_bytes()))
    assert envelope["lineage_id"] == record.lineage_id
    assert envelope["sources"][0]["sha256"] == digest
    assert envelope["aggregation"]["run_id"] == RUN_ID
    assert envelope["aggregation"]["trades"]
    assert envelope["aggregation"]["derived"]

    markers = read_compaction_markers(tmp_path, RUN_ID)
    assert len(markers) == 1
    assert markers[0]["status"] == COMPACTION_MARKED
    assert markers[0]["output_sha256"] == record.output_sha256
    assert markers[0]["source_paths"] == [record.sources[0].path]


def test_compaction_is_idempotent(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy()
    first = compact_window(tmp_path, policy, RUN_ID, bucket, bucket + ROTATION * 1000, [segment])
    second = compact_window(tmp_path, policy, RUN_ID, bucket, bucket + ROTATION * 1000, [segment])
    assert second.already_present is True
    assert second.lineage.output_sha256 == first.lineage.output_sha256
    assert first.lineage.output_sha256 == second.lineage.output_sha256


def test_aggregation_output_is_byte_for_byte_deterministic(tmp_path: Path) -> None:
    """The output hash is evidence, so compressing twice must give the same bytes."""
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy()
    first = compact_window(tmp_path, policy, RUN_ID, bucket, bucket + ROTATION * 1000, [segment])
    other_root = tmp_path / "second"
    copy = other_root / segment.relative_to(tmp_path)
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(segment.read_bytes())
    second = compact_window(
        other_root, policy, RUN_ID, bucket, bucket + ROTATION * 1000, [copy]
    )
    assert second.lineage.output_sha256 == first.lineage.output_sha256
    assert second.lineage.output_bytes == first.lineage.output_bytes


def test_an_unsealed_segment_is_refused_by_compaction(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    with pytest.raises(StorageError, match="unsealed"):
        compact_window(
            tmp_path,
            _policy(sealed_grace_seconds=86_400),
            RUN_ID,
            bucket,
            bucket + ROTATION * 1000,
            [segment],
            now_ms=bucket,
        )


# -------------------------------------------------------------------- planning


def test_raw_inside_the_hot_window_is_kept(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    _capture_window(tmp_path, bucket_start_ms=bucket)
    plan = plan_retention(
        tmp_path, _policy(raw_hot_hours=24.0), RUN_ID, now_ms=bucket + ROTATION * 1000
    )
    assert not plan.compactable
    assert not plan.deletable
    assert len(plan.retained_raw) == 1


def test_raw_outside_the_hot_window_becomes_compactable(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    _capture_window(tmp_path, bucket_start_ms=bucket)
    plan = plan_retention(
        tmp_path, _policy(raw_hot_hours=1.0), RUN_ID, now_ms=bucket + 10 * 3_600_000
    )
    assert len(plan.compactable) == 1
    assert plan.compactable[0][0] == bucket


def test_a_misaligned_segment_is_skipped_not_deleted(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    stray = segment.parent / "000123.jsonl.gz"
    stray.write_bytes(segment.read_bytes())
    plan = plan_retention(
        tmp_path, _policy(raw_hot_hours=1.0), RUN_ID, now_ms=bucket + 10 * 3_600_000
    )
    assert any("not aligned" in entry["reason"] for entry in plan.skipped)
    assert all(str(stray) not in str(path) for path, _ in plan.deletable)


# ------------------------------------------------------------------- deletion


def test_deletion_requires_allow_delete(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy(raw_hot_hours=1.0, sealed_grace_seconds=0)
    now = bucket + 10 * 3_600_000
    run = apply_retention(tmp_path, policy, RUN_ID, allow_delete=False, now_ms=now)
    assert run.compacted
    assert run.deleted == []
    assert segment.exists()


def test_raw_is_deleted_only_after_a_verified_aggregate_exists(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy(raw_hot_hours=1.0)
    now = bucket + 10 * 3_600_000
    run = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    assert len(run.deleted) == 1
    assert not segment.exists()
    assert run.freed_bytes > 0
    lineage = json.loads(lineage_path(tmp_path, RUN_ID, bucket).read_text(encoding="utf-8"))
    aggregate = tmp_path / lineage["output_path"]
    assert aggregate.exists(), "the aggregate must survive the raw it replaced"
    digest, size = sha256_file(aggregate)
    assert digest == lineage["output_sha256"]
    assert size == lineage["output_bytes"]


def test_a_tampered_aggregate_blocks_the_deletion(tmp_path: Path) -> None:
    """§6 — the one case that must never delete: replaced by something corrupt."""
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy(raw_hot_hours=1.0)
    now = bucket + 10 * 3_600_000
    apply_retention(tmp_path, policy, RUN_ID, allow_delete=False, now_ms=now)
    lineage = json.loads(lineage_path(tmp_path, RUN_ID, bucket).read_text(encoding="utf-8"))
    aggregate = tmp_path / lineage["output_path"]
    # One extra compressed byte is enough: the hash is the only claim that the
    # aggregate still is what the lineage says it is.
    aggregate.write_bytes(aggregate.read_bytes() + b"\x00")

    run = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    assert run.deleted == []
    assert segment.exists()
    assert any("hash changed" in entry.get("reason", "") for entry in run.refused)


def test_a_missing_aggregate_blocks_the_deletion(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    segment = _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy(raw_hot_hours=1.0)
    now = bucket + 10 * 3_600_000
    apply_retention(tmp_path, policy, RUN_ID, allow_delete=False, now_ms=now)
    lineage = json.loads(lineage_path(tmp_path, RUN_ID, bucket).read_text(encoding="utf-8"))
    (tmp_path / lineage["output_path"]).unlink()
    run = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    assert run.deleted == []
    assert segment.exists()


def test_deletion_is_idempotent(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    _capture_window(tmp_path, bucket_start_ms=bucket)
    policy = _policy(raw_hot_hours=1.0)
    now = bucket + 10 * 3_600_000
    first = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    second = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    assert len(first.deleted) == 1
    assert second.deleted == []
    assert first.freed_bytes == first.freed_bytes


def test_reports_layer_is_never_touched(tmp_path: Path) -> None:
    bucket = _window_start_ms()
    _capture_window(tmp_path, bucket_start_ms=bucket)
    report = tmp_path / REPORT_ROOT / "FORWARD_QUALITY.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}", encoding="utf-8")
    policy = _policy(raw_hot_hours=1.0)
    now = bucket + 10 * 3_600_000
    run = apply_retention(tmp_path, policy, RUN_ID, allow_delete=True, now_ms=now)
    assert run.deleted
    assert report.exists()
    assert (tmp_path / AGGREGATED_ROOT).exists()
    assert (tmp_path / LINEAGE_ROOT).exists()


# -------------------------------------------------------------------- capacity


def test_capacity_says_external_storage_when_the_disk_cannot_hold_the_policy() -> None:
    report = capacity_report(
        free_bytes=int(2.257e9),
        policy=RetentionPolicy(raw_hot_hours=24.0, reserve_bytes=512 * 1024 * 1024),
        compressed_bytes_per_day=8.598e9,
    )
    assert report.verdict == EXTERNAL_STORAGE_REQUIRED
    assert report.headroom_bytes < 0
    assert report.estimated_operating_days == 0.0


def test_capacity_is_viable_when_the_hot_window_fits_the_reserve_it_keeps() -> None:
    report = capacity_report(
        free_bytes=int(2.257e9),
        policy=RetentionPolicy(raw_hot_hours=4.0, reserve_bytes=384 * 1024 * 1024),
        compressed_bytes_per_day=8.598e9,
        aggregate_bytes_per_day=20e6,
    )
    assert report.verdict == VIABLE
    assert report.raw_hot_steady_state_bytes < 2.0e9
    assert report.hours_until_guard_without_compaction > 0
    assert report.estimated_operating_days is not None
    assert report.estimated_operating_days >= 7


def test_capacity_is_unbounded_when_aggregates_do_not_grow() -> None:
    report = capacity_report(
        free_bytes=int(2.257e9),
        policy=RetentionPolicy(raw_hot_hours=4.0, reserve_bytes=64 * 1024 * 1024),
        compressed_bytes_per_day=8.598e9,
    )
    assert report.verdict == VIABLE
    assert report.estimated_operating_days is None


def test_policy_for_host_never_invents_a_window_larger_than_the_disk() -> None:
    policy = policy_for_host(
        free_bytes=int(2.257e9),
        compressed_bytes_per_day=8.598e9,
        reserve_bytes=384 * 1024 * 1024,
    )
    assert 1.0 <= policy.raw_hot_hours <= 24.0
    report = capacity_report(
        free_bytes=int(2.257e9),
        policy=policy,
        compressed_bytes_per_day=8.598e9,
    )
    assert report.verdict == VIABLE
    # The invariant that matters: the chosen window leaves the reserve intact.
    assert policy.raw_hot_hours * (8.598e9 / 24.0) + policy.reserve_bytes <= int(2.257e9)


def test_policy_for_host_keeps_a_safety_margin_for_the_disk_guard() -> None:
    """Half the spare space, so a stalled compaction still has hours to spare."""
    free = int(2.257e9)
    reserve = 384 * 1024 * 1024
    policy = policy_for_host(
        free_bytes=free,
        compressed_bytes_per_day=8.598e9,
        aggregate_bytes_per_day=20e6,
        reserve_bytes=reserve,
        fill_fraction=0.5,
    )
    steady_state = policy.raw_hot_hours * (8.598e9 / 24.0)
    assert steady_state <= 0.5 * (free - reserve)
    report = capacity_report(
        free_bytes=free,
        policy=policy,
        compressed_bytes_per_day=8.598e9,
        aggregate_bytes_per_day=20e6,
    )
    assert report.verdict == VIABLE
    # The guard is not reached for hours even if compaction never runs again.
    assert report.hours_until_guard_without_compaction >= 2.0


def test_policy_for_host_rejects_a_nonsense_fill_fraction() -> None:
    with pytest.raises(ValueError, match="fill_fraction"):
        policy_for_host(
            free_bytes=int(2e9), compressed_bytes_per_day=8.598e9, fill_fraction=1.5
        )


def test_policy_for_host_floors_at_one_hour_when_nothing_fits() -> None:
    policy = policy_for_host(
        free_bytes=int(0.5e9),
        compressed_bytes_per_day=8.598e9,
        reserve_bytes=384 * 1024 * 1024,
    )
    assert policy.raw_hot_hours == 1.0
    report = capacity_report(
        free_bytes=int(0.5e9),
        policy=policy,
        compressed_bytes_per_day=8.598e9,
    )
    assert report.verdict == EXTERNAL_STORAGE_REQUIRED


def test_policy_is_explicit_about_every_retention_rule() -> None:
    payload = RetentionPolicy().as_dict()
    assert payload["raw_retention"].startswith("RAW HOT")
    assert payload["aggregate_retention"] == "indefinite"
    assert payload["report_retention"] == "indefinite"
    assert payload["aggregate_timeframes_minutes"] == [1, 5, 15, 30]
