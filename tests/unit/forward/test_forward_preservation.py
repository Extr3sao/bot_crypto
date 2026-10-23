"""§7-§13 — data preservation: what must survive before raw may be deleted.

The policy question these tests answer is not "is there an aggregate file" but
"can the preregistered hypothesis still be measured after the raw rows are gone".
Two derivations are compared for that: one from the raw rows, one from the
compact artifact, both at the resolution the preregistration records
(M-03 at 1/5 m, M-07 at 5/15/30 m).

A mismatch must refuse the deletion by name, and a window whose rows cannot
support the comparison at all must refuse too — "nothing to compare" is not
evidence that everything matches.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from trading_bot.research.forward.contract import (
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.preservation import (
    M03,
    M07,
    PRESERVED,
    RAW_NOT_DELETABLE_FOR_M03,
    RAW_NOT_DELETABLE_FOR_M07,
    PreservationPolicy,
    preservation_for_window,
)
from trading_bot.research.forward.retention import (
    LOSSLESS,
    LOSSY,
    PRESERVATION_ROOT,
    RAW_ROOT,
    RetentionPolicy,
    apply_retention,
    compact_window,
    tier_plan,
)
from trading_bot.research.forward.storage import SegmentWriter, iter_segment_rows

RUN_ID = "run-preservation"
ROTATION = 60
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
#: A window that is comfortably in the past, so "sealed" is checkable.
WINDOW_START_MS = (1_800_000_000_000 // (ROTATION * 1000)) * (ROTATION * 1000)


def _book_checkpoint(
    ts_ms: int, *, spread: str, imbalance: str, microprice: str, health: str = "HEALTHY"
) -> RawEvent:
    return RawEvent(
        event_type=EventType.BOOK_CHECKPOINT,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="book_checkpoint",
        transport=Transport.WS,
        run_id=RUN_ID,
        exchange_event_time=ts_ms,
        receive_time=ts_ms,
        process_time=ts_ms + 1,
        sequence=SequenceRange(last=ts_ms),
        bid="100.0",
        ask="100.1",
        bid_qty="3",
        ask_qty="4",
        detail={
            "health": health,
            "depth_n": 10,
            "mid": "100.05",
            "spread_bps": spread,
            "depth_imbalance": imbalance,
            "microprice": microprice,
        },
    )


def _trade(ts_ms: int, *, agg_id: int, quantity: str, side: str) -> RawEvent:
    return RawEvent(
        event_type=EventType.AGG_TRADE,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@aggTrade",
        transport=Transport.WS,
        run_id=RUN_ID,
        exchange_event_id=str(agg_id),
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 20,
        process_time=ts_ms + 21,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price="100.0",
        quantity=quantity,
        aggressor_side=side,
    )


def _open_interest(ts_ms: int, value: str) -> RawEvent:
    return RawEvent(
        event_type=EventType.OPEN_INTEREST,
        symbol="BTCUSDT",
        market=Market.PERP,
        stream="openInterest",
        transport=Transport.REST_POLL,
        run_id=RUN_ID,
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 50,
        process_time=ts_ms + 51,
        open_interest=value,
    )


def _mark_price(ts_ms: int, mark: str, index: str) -> RawEvent:
    return RawEvent(
        event_type=EventType.MARK_PRICE,
        symbol="BTCUSDT",
        market=Market.PERP,
        stream="markPrice",
        transport=Transport.REST_POLL,
        run_id=RUN_ID,
        exchange_event_time=ts_ms,
        receive_time=ts_ms + 50,
        process_time=ts_ms + 51,
        mark_price=mark,
        index_price=index,
    )


def _policy(**overrides: object) -> RetentionPolicy:
    options: dict[str, object] = {
        "rotation_seconds": ROTATION,
        "raw_hot_hours": 0.0,
        "sealed_grace_seconds": 0,
    }
    options.update(overrides)
    return RetentionPolicy(**options)  # type: ignore[arg-type]


def _write_window(root: Path, *, window_start_ms: int) -> None:
    """One real minute of the three things the hypotheses need."""
    writer = SegmentWriter(root, rotation_seconds=ROTATION, run_id=RUN_ID)
    try:
        for minute in range(6):
            stamp = window_start_ms + minute * 10_000
            writer.write(
                _book_checkpoint(
                    stamp,
                    spread=f"0.01{minute}",
                    imbalance=f"0.{minute}5",
                    microprice=f"100.0{minute}",
                )
            )
            writer.write(
                _trade(
                    stamp + 1_000,
                    agg_id=minute * 2 + 1,
                    quantity="1.5",
                    side="buy" if minute % 2 == 0 else "sell",
                )
            )
        writer.write(_open_interest(window_start_ms + 5_000, "12345.6"))
        writer.write(_open_interest(window_start_ms + 45_000, "12350.0"))
        writer.write(_mark_price(window_start_ms + 45_000, "100.2", "100.1"))
    finally:
        writer.close()


def _window_files(root: Path) -> list[Path]:
    return sorted((root / RAW_ROOT).rglob("*.jsonl.gz"))


def _compact(root: Path, policy: RetentionPolicy) -> None:
    compact_window(
        root,
        policy,
        RUN_ID,
        WINDOW_START_MS,
        WINDOW_START_MS + ROTATION * 1000,
        _window_files(root),
        now_ms=WINDOW_START_MS + HOUR_MS,
    )


def _aggregate_path(root: Path) -> Path:
    files = sorted((root / "aggregated" / RUN_ID).glob("*.json.gz"))
    assert len(files) == 1, files
    return files[0]


# ------------------------------------------------------------------------ tiers


def test_the_tier_plan_separates_lossless_from_lossy() -> None:
    """§10 — "compact" must not be one word for two different things."""
    tiers = {spec.tier: spec for spec in tier_plan(_policy())}
    assert set(tiers) == {"TIER 0", "TIER 1", "TIER 2", "TIER 3"}
    assert tiers["TIER 0"].kind == LOSSLESS
    assert tiers["TIER 1"].kind == LOSSY
    assert tiers["TIER 2"].kind == LOSSLESS  # lineage: audit trail, not a sample
    assert "M-03" in " ".join(tiers["TIER 1"].serves)
    assert "M-07" in " ".join(tiers["TIER 1"].serves)
    assert tiers["TIER 0"].measured_share_of_bytes == 1.0


# ------------------------------------------------------------------ preservation


def test_compaction_preserves_the_preregistered_m03_and_m07_series(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()
    _compact(root, policy)

    report = preservation_for_window(
        root,
        RUN_ID,
        WINDOW_START_MS,
        _window_files(root),
        policy=PreservationPolicy(),
    )

    assert report.verdicts[M03] == PRESERVED, report.as_dict()
    assert report.verdicts[M07] == PRESERVED, report.as_dict()
    assert report.deletion_allowed is True
    # What is *not* preserved is named rather than implied.
    payload = report.as_dict()
    assert any("book_ticker" in item for item in payload["not_covered_without_raw_quotes"])
    # One minute of rows is one bucket, so the comparison is small but exhaustive:
    # 4 book fields, 2 flow fields (imbalance + trade count) and 4 open-interest
    # fields, each compared for the one bucket the test writes.
    compared = {comparison.feature: comparison.compared for comparison in report.comparisons}
    assert compared == {
        "M-03 book series": 4,
        "M-03 trade flow": 2,
        "M-07 open interest x price": 4,
    }


def test_a_module_level_import_is_not_required_for_the_verdict() -> None:
    """The raw reader is a plain JSONL reader: the comparison does not need the runtime."""
    from trading_bot.research.forward import preservation

    assert preservation.__name__.endswith("preservation")


def test_a_tampered_aggregate_refuses_the_deletion_by_name(tmp_path: Path) -> None:
    """§12 — a compact tier that no longer matches the raw is not a replacement."""
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()
    _compact(root, policy)

    path = _aggregate_path(root)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        envelope = json.load(handle)
    key = next(iter(envelope["aggregation"]["book"]))
    envelope["aggregation"]["book"][key][0]["spread_bps_mean"] = "999.99"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(envelope, handle)

    report = preservation_for_window(
        root,
        RUN_ID,
        WINDOW_START_MS,
        _window_files(root),
        policy=PreservationPolicy(),
    )
    assert report.verdicts[M03] == RAW_NOT_DELETABLE_FOR_M03
    assert report.deletion_allowed is False
    assert any("M-03" in reason for reason in report.reasons)


def test_asking_for_sub_minute_m03_refuses_the_deletion(tmp_path: Path) -> None:
    """The knob exists and it fails closed: quote-level microstructure needs raw."""
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()
    _compact(root, policy)

    report = preservation_for_window(
        root,
        RUN_ID,
        WINDOW_START_MS,
        _window_files(root),
        policy=PreservationPolicy(m03_min_resolution_minutes=0),
    )
    assert report.verdicts[M03] == RAW_NOT_DELETABLE_FOR_M03
    assert report.deletion_allowed is False
    assert any("sub-minute" in reason for reason in report.reasons)


def test_a_window_without_the_rows_cannot_demonstrate_preservation(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    root.mkdir(parents=True)
    policy = _policy()
    # A window of heartbeats only: nothing at all to compare for either hypothesis.
    writer = SegmentWriter(root, rotation_seconds=ROTATION, run_id=RUN_ID)
    try:
        writer.write(
            RawEvent(
                event_type=EventType.HEARTBEAT,
                symbol="GLOBAL",
                market=Market.SPOT,
                stream="heartbeat",
                transport=Transport.WS,
                run_id=RUN_ID,
                exchange_event_time=WINDOW_START_MS,
                receive_time=WINDOW_START_MS,
                process_time=WINDOW_START_MS + 1,
            )
        )
    finally:
        writer.close()
    _compact(root, policy)

    report = preservation_for_window(
        root,
        RUN_ID,
        WINDOW_START_MS,
        _window_files(root),
        policy=PreservationPolicy(),
    )
    assert report.verdicts[M03] == RAW_NOT_DELETABLE_FOR_M03
    assert report.verdicts[M07] == RAW_NOT_DELETABLE_FOR_M07
    assert report.deletion_allowed is False


def test_a_missing_compact_artifact_refuses_the_deletion(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    report = preservation_for_window(
        root,
        RUN_ID,
        WINDOW_START_MS,
        _window_files(root),
        policy=PreservationPolicy(),
    )
    assert report.deletion_allowed is False
    assert report.verdicts[M03] == RAW_NOT_DELETABLE_FOR_M03
    assert "no compact artifact" in report.reasons[0]


# ------------------------------------------------------- retention integration


def test_retention_deletes_only_when_preservation_allows_it(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()

    run = apply_retention(
        root,
        policy,
        RUN_ID,
        allow_delete=True,
        preservation=PreservationPolicy(),
        now_ms=WINDOW_START_MS + HOUR_MS,
    )
    assert run.compacted, "the window should have been compacted first"
    assert run.deleted, "preservation was satisfied, so the raw should be gone"
    assert run.preservation and run.preservation[0]["deletion_allowed"] is True
    # §11 — the verdict is written down, not just computed.
    written = sorted((root / PRESERVATION_ROOT / RUN_ID).glob("*.json"))
    assert written, "the preservation verdict must be an artifact"
    assert json.loads(written[0].read_text(encoding="utf-8"))["deletion_allowed"] is True
    assert not _window_files(root)


def test_retention_keeps_the_raw_when_preservation_refuses(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()

    run = apply_retention(
        root,
        policy,
        RUN_ID,
        allow_delete=True,
        preservation=PreservationPolicy(m03_min_resolution_minutes=0),
        now_ms=WINDOW_START_MS + HOUR_MS,
    )
    assert run.compacted
    assert run.deleted == []
    assert _window_files(root), "verified-unpreserved raw must not be deleted"
    assert any(RAW_NOT_DELETABLE_FOR_M03 in str(entry.get("reason")) for entry in run.refused)
    assert run.preservation[0]["deletion_allowed"] is False


def test_without_a_preservation_policy_nothing_changes(tmp_path: Path) -> None:
    """The previous behaviour stays available, and stays explicit."""
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    policy = _policy()
    run = apply_retention(
        root,
        policy,
        RUN_ID,
        allow_delete=True,
        gaps=None,
        now_ms=WINDOW_START_MS + HOUR_MS,
    )
    assert run.deleted
    assert run.preservation == []


def test_the_raw_reader_sees_every_row_it_is_given(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    _write_window(root, window_start_ms=WINDOW_START_MS)
    rows = [
        row
        for path in _window_files(root)
        for row, _complete in iter_segment_rows(path)
        if row is not None
    ]
    types = {str(row["event_type"]) for row in rows}
    assert types == {"book_checkpoint", "agg_trade", "open_interest", "mark_price"}
