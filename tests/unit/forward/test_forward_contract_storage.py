"""Adversarial tests for the forward data contract and the storage layer (§30).

The forward dataset is only worth the guarantees it can prove, so these tests
attack the contract and the writer rather than exercising the happy path:

* a timestamp that travels backwards in time must be *quarantined*, not stored;
* a periodic REST series must never be able to masquerade as a lossless stream;
* a half-written line must be *visible* as a partial tail, never silently
  dropped into a clean dataset;
* a corrupted manifest must fail loudly instead of yielding a plausible run.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.research.forward.contract import (
    ClockViolation,
    ContractError,
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
    event_stream_name,
    parse_event,
)
from trading_bot.research.forward.storage import (
    CONTINUITY_CONTINUOUS,
    CONTINUITY_INCOMPLETE,
    GLOBAL_SYMBOL,
    GapRecord,
    RunManifest,
    SegmentWriter,
    StorageError,
    fingerprint_segment,
    iter_segment_records,
    load_manifest,
    load_resume_state,
    read_segment,
    rotation_bucket_start,
    save_json,
    save_resume_state,
    segment_relative_path,
    sha256_file,
    stream_key_from_path,
)


def _agg_trade(
    *,
    event_type: EventType = EventType.AGG_TRADE,
    market: Market = Market.SPOT,
    transport: Transport = Transport.WS,
    event_time: int | None = 1_000,
    receive_time: int = 1_050,
    agg_id: int = 1,
    symbol: str = "BTCUSDT",
    price: str = "100.5",
    quantity: str = "2",
) -> RawEvent:
    return RawEvent(
        event_type=event_type,
        symbol=symbol,
        market=market,
        stream="btcusdt@aggTrade",
        transport=transport,
        run_id="run-1",
        exchange_event_id=str(agg_id),
        exchange_event_time=event_time,
        receive_time=receive_time,
        process_time=receive_time + 1,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price=price,
        quantity=quantity,
        aggressor_side="buy",
    )


# --------------------------------------------------------------------- contract


def test_three_clocks_are_kept_separate_and_derived_never_replace_them() -> None:
    event = _agg_trade(event_time=1_000, receive_time=1_050)
    payload = event.to_dict()
    assert payload["exchange_event_time"] == 1_000
    assert payload["receive_time"] == 1_050
    assert payload["process_time"] == 1_051
    assert payload["network_delay_ms"] == 50
    assert payload["processing_delay_ms"] == 1


def test_temporal_guarantee_rejects_a_future_exchange_clock() -> None:
    event = _agg_trade(event_time=1_500, receive_time=1_000)
    with pytest.raises(ClockViolation):
        event.assert_temporal_guarantee(tolerance_ms=100)
    # Within the documented tolerance it is permitted, because venue clocks drift.
    event.assert_temporal_guarantee(tolerance_ms=1_000)


def test_process_time_before_receive_time_is_impossible() -> None:
    with pytest.raises(ClockViolation):
        replace(_agg_trade(), process_time=1_000)


def test_process_time_can_be_set_after_receive_time_only() -> None:
    event = _agg_trade(receive_time=2_000)
    assert event.processing_delay_ms == 1


def test_high_frequency_stream_cannot_travel_over_rest() -> None:
    """§5/§55: REST polling must never be presented as a lossless trade feed."""
    with pytest.raises(ContractError):
        _agg_trade(transport=Transport.REST_POLL)
    with pytest.raises(ContractError):
        _agg_trade(event_type=EventType.DEPTH_DIFF, transport=Transport.REST_BACKFILL)


def test_periodic_series_cannot_claim_to_be_a_websocket_stream() -> None:
    with pytest.raises(ContractError):
        RawEvent(
            event_type=EventType.OPEN_INTEREST,
            symbol="BTCUSDT",
            market=Market.PERP,
            stream="openInterest",
            transport=Transport.WS,
            run_id="run-1",
            exchange_event_time=None,
            receive_time=10,
            process_time=11,
            open_interest="1",
        )


def test_non_numeric_or_negative_quantities_fail_closed() -> None:
    with pytest.raises(ContractError):
        _agg_trade(price="not-a-number")
    with pytest.raises(ContractError):
        _agg_trade(price="-5")
    with pytest.raises(ContractError):
        _agg_trade(quantity="0")


def test_aggressor_side_is_mandatory_for_trades() -> None:
    with pytest.raises(ContractError):
        replace(_agg_trade(), aggressor_side=None)
    with pytest.raises(ContractError):
        replace(_agg_trade(), aggressor_side="maker")


def test_lowercase_symbols_are_rejected() -> None:
    with pytest.raises(ContractError):
        _agg_trade(symbol="btcusdt")


def test_sequence_range_cannot_be_inverted_or_negative() -> None:
    with pytest.raises(ContractError):
        SequenceRange(first=10, last=5)
    with pytest.raises(ContractError):
        SequenceRange(first=-1)


def test_decimal_strings_survive_a_serialise_parse_round_trip_exactly() -> None:
    event = _agg_trade(price="83506.02000000", quantity="0.00092000")
    restored = parse_event(json.loads(event.to_json()))
    assert restored.price == "83506.02000000"
    assert restored.quantity == "0.00092000"
    assert restored.to_json() == event.to_json()


def test_parse_event_fails_closed_on_unknown_enums() -> None:
    payload = json.loads(_agg_trade().to_json())
    payload["event_type"] = "not_a_real_event"
    with pytest.raises(ContractError):
        parse_event(payload)
    payload["event_type"] = "agg_trade"
    payload["market"] = "somewhere_else"
    with pytest.raises(ContractError):
        parse_event(payload)


def test_zero_quantity_is_preserved_exactly_for_depth_deletes() -> None:
    event = RawEvent(
        event_type=EventType.DEPTH_DIFF,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@depth@100ms",
        transport=Transport.WS,
        run_id="run-1",
        exchange_event_time=5,
        receive_time=6,
        process_time=7,
        sequence=SequenceRange(first=1, last=2),
        bids=[["100.10", "0.00000000"]],
        asks=[["100.20", "3"]],
    )
    restored = parse_event(json.loads(event.to_json()))
    assert restored.bids == [["100.10", "0.00000000"]]


def test_depth_diff_without_level_lists_is_rejected() -> None:
    with pytest.raises(ContractError):
        RawEvent(
            event_type=EventType.DEPTH_DIFF,
            symbol="BTCUSDT",
            market=Market.SPOT,
            stream="btcusdt@depth@100ms",
            transport=Transport.WS,
            run_id="run-1",
            exchange_event_time=5,
            receive_time=6,
            process_time=7,
        )


def test_stream_names_are_stable() -> None:
    assert event_stream_name(EventType.AGG_TRADE, "BTCUSDT") == "agg_trade/BTCUSDT"


# ---------------------------------------------------------------------- storage


def test_rotation_and_paths_are_deterministic_functions_of_the_window() -> None:
    assert rotation_bucket_start(1_799_999_999_000, 3600) == 1_799_996_400_000
    first = segment_relative_path("binance", "spot", "BTCUSDT", EventType.AGG_TRADE, 0)
    second = segment_relative_path("binance", "spot", "BTCUSDT", EventType.AGG_TRADE, 0)
    assert first == second
    assert first == "segments/binance/spot/BTCUSDT/agg_trade/1970-01-01/000000.jsonl.gz"
    assert stream_key_from_path(first) == ("spot", "BTCUSDT", "agg_trade")
    with pytest.raises(StorageError):
        stream_key_from_path("nonsense/path.jsonl")
    with pytest.raises(ValueError):
        rotation_bucket_start(0, 0)


def test_writer_rotates_by_bucket_and_fingerprints_match_the_bytes(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=60)
    writer.write(_agg_trade(receive_time=120_000, event_time=119_000))
    writer.write(_agg_trade(receive_time=121_000, event_time=120_000))
    writer.write(_agg_trade(receive_time=181_000, event_time=180_000))
    writer.close()

    fingerprints = writer.fingerprints()
    assert len(fingerprints) == 2
    assert all(f.sealed for f in fingerprints)
    assert not any(f.partial_tail for f in fingerprints)
    assert sum(f.row_count for f in fingerprints) == 3
    for fingerprint in fingerprints:
        digest, size = sha256_file(tmp_path / fingerprint.path)
        assert digest == fingerprint.sha256
        assert size == fingerprint.bytes


def test_compressed_segments_round_trip_through_the_readers(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600, compress=True)
    writer.write(_agg_trade(receive_time=120_000, event_time=119_000))
    writer.close()
    path = tmp_path / writer.fingerprints()[0].path
    assert path.suffix == ".gz"

    rows, partial = iter_segment_records(path)
    assert partial is False
    assert len(rows) == 1
    events, strict_partial = read_segment(path)
    assert strict_partial is False
    assert events[0].price == "100.5"


def test_uncompressed_segments_are_supported_when_explicitly_requested(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600, compress=False)
    writer.write(_agg_trade(receive_time=1_000))
    writer.close()
    path = tmp_path / writer.fingerprints()[0].path
    assert path.suffix == ".jsonl"
    events, partial = read_segment(path)
    assert partial is False
    assert len(events) == 1


def test_a_partial_storage_write_is_reported_not_swallowed(tmp_path: Path) -> None:
    """§30 partial storage write: a truncated line must stay visible."""
    writer = SegmentWriter(tmp_path, rotation_seconds=3600, compress=False)
    writer.write(_agg_trade(receive_time=1_000))
    writer.close()
    path = tmp_path / writer.fingerprints()[0].path
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"schema_version":"forward-event-v1","event_type":"agg_tra')

    rows, partial = iter_segment_records(path)
    assert partial is True
    assert len(rows) == 1  # the good row is still readable
    events, partial2 = read_segment(path)
    assert partial2 is True
    assert len(events) == 1
    with pytest.raises(ValueError):
        read_segment(path, strict=True)


def test_truncated_gzip_member_reads_as_a_partial_tail(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600, compress=True)
    writer.write(_agg_trade(receive_time=1_000))
    writer.write(_agg_trade(receive_time=1_100))
    writer.close()
    path = tmp_path / writer.fingerprints()[0].path
    payload = path.read_bytes()
    path.write_bytes(payload[: len(payload) - 6])  # eat the gzip trailer

    rows, partial = iter_segment_records(path)
    assert partial is True
    assert rows  # complete rows before the damage remain usable


def test_restart_appends_without_duplicating_uncontrolled_rows(tmp_path: Path) -> None:
    first = SegmentWriter(tmp_path, rotation_seconds=3600, run_id="run-a")
    first.write(_agg_trade(receive_time=1_000, agg_id=1))
    first.close()
    # A deliberate resume of the same dataset appends to the same bucket.
    second = SegmentWriter(
        tmp_path, rotation_seconds=3600, run_id="run-a", allow_existing_segments=True
    )
    second.write(_agg_trade(receive_time=1_100, agg_id=2))
    second.close()

    files = sorted((tmp_path / "segments").rglob("*.jsonl.gz"))
    assert len(files) == 1  # same bucket -> same segment, appended
    rows, partial = iter_segment_records(files[0])
    assert partial is False
    assert [row["exchange_event_id"] for row in rows] == ["1", "2"]
    assert [row["write_seq"] for row in rows] == [1, 1]  # per-process counters


def test_write_seq_is_assigned_by_storage_not_by_the_caller(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600)
    writer.write(_agg_trade(receive_time=1_000, agg_id=1))
    writer.write(_agg_trade(receive_time=1_000, agg_id=2))
    writer.close()
    rows, _ = iter_segment_records(next((tmp_path / "segments").rglob("*.jsonl.gz")))
    assert [row["write_seq"] for row in rows] == [1, 2]


def test_a_corrupt_manifest_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "manifest" / "run-1.json"
    save_json(path, {"run_id": "run-1"})
    with pytest.raises(StorageError):
        load_manifest(path)
    save_json(path, ["not", "an", "object"])
    with pytest.raises(StorageError):
        load_manifest(path)


def test_resume_state_round_trips_and_is_absent_for_unknown_runs(tmp_path: Path) -> None:
    save_resume_state(tmp_path, "run-1", {"run_id": "run-1", "last_receive_time": 5})
    assert load_resume_state(tmp_path, "run-1") == {"run_id": "run-1", "last_receive_time": 5}
    assert load_resume_state(tmp_path, "run-2") is None


def test_gap_duration_is_derived_and_negative_windows_collapse_to_zero() -> None:
    forward = GapRecord(
        market="spot",
        symbol="BTCUSDT",
        event_type="agg_trade",
        start_ms=1_000,
        end_ms=3_500,
        reason="WS_DISCONNECT",
        recovered=False,
    )
    assert forward.duration_ms == 2_500
    assert forward.as_dict()["duration_ms"] == 2_500
    backwards = replace(forward, start_ms=3_500, end_ms=1_000)
    assert backwards.duration_ms == 0


def test_run_manifest_serialises_gap_durations(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="run-1",
        collector_version="c",
        contract_version="v",
        schema_version="s",
        provider="binance",
        market="spot,perp",
        commit="deadbeef",
        symbols=["BTCUSDT"],
        markets=["spot"],
        started_at="2026-01-01T00:00:00+00:00",
        ended_at=None,
        duration_seconds=1.0,
        rotation_seconds=3600,
        continuity=CONTINUITY_INCOMPLETE,
        gaps=[
            GapRecord(
                market="spot",
                symbol="BTCUSDT",
                event_type="agg_trade",
                start_ms=10,
                end_ms=40,
                reason="WS_DISCONNECT",
                recovered=True,
                data_lost=True,
            )
        ],
    )
    payload = manifest.as_dict()
    assert payload["gaps"][0]["duration_ms"] == 30
    assert payload["continuity"] == CONTINUITY_INCOMPLETE
    assert payload["contract_version"] == "v"
    path = manifest.save(tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["gaps"][0]["reason"] == "WS_DISCONNECT"


def test_global_streams_are_kept_in_a_sentinel_symbol_directory(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600)
    writer.write(
        RawEvent(
            event_type=EventType.HEARTBEAT,
            symbol=GLOBAL_SYMBOL,
            market=Market.SPOT,
            stream="heartbeat",
            transport=Transport.WS,
            run_id="run-1",
            exchange_event_time=None,
            receive_time=1_000,
            process_time=1_001,
        )
    )
    writer.close()
    relative = writer.fingerprints()[0].path
    assert "/_GLOBAL/heartbeat/" in relative
    assert stream_key_from_path(relative) == ("spot", "_GLOBAL", "heartbeat")


def test_continuity_labels_are_the_only_two_allowed() -> None:
    assert CONTINUITY_CONTINUOUS == "CONTINUOUS_DATA"
    assert CONTINUITY_INCOMPLETE == "INCOMPLETE_DATA"


def test_a_compressed_open_segment_is_still_readable(tmp_path: Path) -> None:
    """Live fingerprints read open segments: sync-flush must keep them decodable."""
    writer = SegmentWriter(tmp_path, rotation_seconds=3600)
    writer.write(_agg_trade(receive_time=1_000))
    live = writer.fingerprints()
    assert len(live) == 1
    assert live[0].sealed is False
    assert live[0].row_count == 1
    writer.close()


def test_gzip_is_actually_smaller_than_the_equivalent_plain_file(tmp_path: Path) -> None:
    plain_root = tmp_path / "plain"
    gz_root = tmp_path / "gz"
    for root, compress in ((plain_root, False), (gz_root, True)):
        writer = SegmentWriter(root, rotation_seconds=3600, compress=compress)
        for index in range(200):
            writer.write(_agg_trade(receive_time=1_000 + index, agg_id=index + 1))
        writer.close()
    plain_bytes = sum(p.stat().st_size for p in plain_root.rglob("*.jsonl"))
    gz_bytes = sum(p.stat().st_size for p in gz_root.rglob("*.jsonl.gz"))
    assert gz_bytes * 3 < plain_bytes
    with gzip.open(next(gz_root.rglob("*.jsonl.gz")), "rb") as handle:
        assert handle.read() != b""


def test_fingerprint_records_schema_and_partial_tail_state(tmp_path: Path) -> None:
    writer = SegmentWriter(tmp_path, rotation_seconds=3600, compress=False)
    writer.write(_agg_trade(receive_time=1_000, event_time=900))
    writer.close()
    path = tmp_path / writer.fingerprints()[0].path
    fingerprint = fingerprint_segment(path, tmp_path, sealed=True)
    assert fingerprint.row_count == 1
    assert fingerprint.first_event_time == 900
    assert fingerprint.last_event_time == 900
    assert fingerprint.first_receive_time == 1_000
    assert fingerprint.schema_version == "forward-event-v1"
    assert fingerprint.partial_tail is False


def test_a_new_run_refuses_to_fuse_itself_into_a_populated_root(tmp_path: Path) -> None:
    """One dataset root belongs to one run: paths are windows, not namespaces."""
    first = SegmentWriter(tmp_path, rotation_seconds=3600, run_id="run-a")
    first.write(_agg_trade(receive_time=1_000, agg_id=1))
    first.close()

    intruder = SegmentWriter(tmp_path, rotation_seconds=3600, run_id="run-b")
    with pytest.raises(StorageError, match="already holds rows from an earlier capture"):
        intruder.write(_agg_trade(receive_time=1_100, agg_id=2))

    files = sorted((tmp_path / "segments").rglob("*.jsonl.gz"))
    rows, _ = iter_segment_records(files[0])
    assert [row["exchange_event_id"] for row in rows] == ["1"]


def test_a_fingerprint_describes_the_file_after_a_resume(tmp_path: Path) -> None:
    first = SegmentWriter(tmp_path, rotation_seconds=3600, run_id="run-a")
    first.write(_agg_trade(receive_time=1_000, agg_id=1))
    first.close()
    second = SegmentWriter(
        tmp_path, rotation_seconds=3600, run_id="run-a", allow_existing_segments=True
    )
    second.write(_agg_trade(receive_time=1_100, agg_id=2))
    fingerprints = second.fingerprints()
    # Rows written by the earlier session are part of this file, so they are
    # part of its fingerprint — a resume must not make a segment look shorter.
    assert len(fingerprints) == 1
    assert fingerprints[0].row_count == 2
    assert fingerprints[0].sealed is False
    second.close()

    files = sorted((tmp_path / "segments").rglob("*.jsonl.gz"))
    sealed = fingerprint_segment(files[0], tmp_path, sealed=True)
    assert sealed.row_count == 2
    assert sealed.sha256 == sha256_file(files[0])[0]
