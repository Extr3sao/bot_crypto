"""P1 — the writer's latency telemetry must be bounded, not per-event (§2, §3).

``StreamStats.network_delays`` used to append one integer per observed event and
was never read: dead state that grew without limit, which is fatal to the
"run continuously" requirement even though it changed no number anybody saw.

These tests hold the replacement to the property that actually matters — memory
does **not** grow with the number of events — at the three volumes the brief
names (10k / 100k / 1M), and check that the quantiles it reports are still the
quantiles the read-side report would compute.
"""

from __future__ import annotations

import sys
import tracemalloc
from itertools import pairwise

import pytest

from trading_bot.research.forward.contract import (
    BACKFILL_ORIGIN,
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from trading_bot.research.forward.storage import (
    LATENCY_BUCKETS,
    LATENCY_LADDER_MS,
    LATENCY_STEP,
    LatencyHistogram,
    StorageError,
    StreamStats,
    merge_latency_histograms,
)

VOLUMES = (10_000, 100_000, 1_000_000)


def _event(
    *,
    delay_ms: int | None,
    detail: dict[str, object] | None = None,
    agg_id: int = 1,
) -> RawEvent:
    receive_time = 1_000_000
    return RawEvent(
        event_type=EventType.AGG_TRADE,
        symbol="BTCUSDT",
        market=Market.SPOT,
        stream="btcusdt@aggTrade",
        transport=Transport.WS,
        run_id="run-1",
        exchange_event_id=str(agg_id),
        exchange_event_time=None if delay_ms is None else receive_time - delay_ms,
        receive_time=receive_time,
        process_time=receive_time + 1,
        sequence=SequenceRange(first=agg_id, last=agg_id),
        price="100.5",
        quantity="2",
        aggressor_side="buy",
        detail=detail,
    )


def _histogram_bytes(histogram: LatencyHistogram) -> int:
    """Shallow size of the whole histogram: counters, bounds and scalars."""
    return sys.getsizeof(histogram.counts) + sum(sys.getsizeof(count) for count in histogram.counts)


# ------------------------------------------------------------------ boundedness


@pytest.mark.parametrize("volume", VOLUMES)
def test_latency_state_is_a_fixed_number_of_counters(volume: int) -> None:
    """The counter array is the same size at 10k, 100k and 1M events."""
    histogram = LatencyHistogram()
    for index in range(volume):
        histogram.observe(index % 997)
    assert len(histogram.counts) == LATENCY_BUCKETS
    assert histogram.samples == volume


@pytest.mark.parametrize("volume", VOLUMES)
def test_one_stream_holds_a_constant_amount_of_memory(volume: int) -> None:
    """A stream's retained memory is a function of the geometry, not the volume."""
    stats = StreamStats(market="spot", symbol="BTCUSDT", event_type="agg_trade", transport="ws")
    for index in range(volume):
        stats.observe(_event(delay_ms=index % 997, agg_id=index))

    # Every counter is a small int, so this per-bucket ceiling cannot be beaten
    # by a bigger count; the point is that it never grows with the event count.
    per_bucket_ceiling = 64
    assert _histogram_bytes(stats.latency) <= per_bucket_ceiling * LATENCY_BUCKETS
    assert len(stats.latency.counts) == LATENCY_BUCKETS
    assert stats.latency.samples == volume


def test_memory_does_not_grow_between_one_hundred_thousand_and_one_million() -> None:
    """The measured allocation delta from 100k to 1M events is negligible.

    The comparison is against what the *old* representation would have retained,
    which is the reason the fix exists.
    """
    tracemalloc.start()
    try:
        small = LatencyHistogram()
        for index in range(100_000):
            small.observe(index % 997)
        after_100k, _ = tracemalloc.get_traced_memory()

        for index in range(100_000, 1_000_000):
            small.observe(index % 997)
        after_1m, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    growth = after_1m - after_100k
    # 900k further observations must not retain anything close to a list of them.
    assert growth < 4_096, f"retained {growth} bytes while observing 900k more events"
    assert peak < 2_000_000
    # The previous design held one pointer per sample; this one holds none.
    would_have_retained = 900_000 * 8
    assert would_have_retained > 1_000 * max(growth, 1)


def test_the_statistics_dict_reports_no_per_event_state() -> None:
    """Nothing in the emitted telemetry is proportional to the event count."""
    histogram = LatencyHistogram()
    for index in range(50_000):
        histogram.observe(index % 100)
    payload = histogram.as_dict()
    assert len(payload["counts"]) <= LATENCY_BUCKETS
    assert sys.getsizeof(str(payload)) < 20_000


# ------------------------------------------------------------------ correctness


def test_quantiles_track_the_exact_distribution_within_the_ladder_step() -> None:
    samples = [index % 500 for index in range(100_000)]
    histogram = LatencyHistogram()
    for value in samples:
        histogram.observe(value)

    ordered = sorted(samples)

    def exact(fraction: float) -> float:
        index = min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))
        return float(ordered[index])

    for fraction in (0.50, 0.95, 0.99):
        reported = histogram.quantile(fraction)
        assert reported is not None
        expected = exact(fraction)
        # Buckets are upper bounds one ladder step wide, so the estimate may only
        # exceed the exact percentile by that step.
        assert reported >= expected
        assert reported <= expected * LATENCY_STEP + 1


def test_negative_and_overflow_delays_are_still_counted() -> None:
    histogram = LatencyHistogram()
    for _ in range(100):
        histogram.observe(-5)
    for _ in range(100):
        histogram.observe(700_000)
    assert histogram.samples == 200
    assert histogram.min_ms == -5
    assert histogram.max_ms == 700_000
    # The overflow bucket reports the observed maximum rather than the ceiling.
    assert max(histogram.distribution()) == 700_000
    assert histogram.quantile(0.99) == 700_000


def test_merging_two_histograms_matches_observing_both() -> None:
    left = LatencyHistogram()
    right = LatencyHistogram()
    for index in range(5_000):
        left.observe(index % 40)
        right.observe((index % 40) + 100)
    merged = merge_latency_histograms([left, right])
    combined = LatencyHistogram()
    for index in range(5_000):
        combined.observe(index % 40)
        combined.observe((index % 40) + 100)
    assert merged.samples == combined.samples == 10_000
    assert merged.distribution() == combined.distribution()
    assert merged.quantile(0.95) == combined.quantile(0.95)


def test_a_histogram_of_the_wrong_geometry_is_rejected() -> None:
    """Geometry is part of the contract: a foreign bucket count fails closed."""
    with pytest.raises(StorageError, match="exactly"):
        LatencyHistogram(counts=[0, 0, 0])


# -------------------------------------------------------------- writer wiring


def test_recovered_rows_are_kept_out_of_the_latency_distribution() -> None:
    """A backfilled row's delay is an outage width, not network latency.

    The read-side report already excludes them; the writer must agree, or the two
    would publish different latency distributions for the same capture.
    """
    stats = StreamStats(market="spot", symbol="BTCUSDT", event_type="agg_trade", transport="ws")
    stats.observe(_event(delay_ms=10, agg_id=1))
    stats.observe(_event(delay_ms=90_000, detail={"origin": BACKFILL_ORIGIN}, agg_id=2))
    assert stats.events == 2
    assert stats.latency.samples == 1
    assert stats.latency.max_ms == 10


def test_stats_without_event_time_report_no_latency_samples() -> None:
    stats = StreamStats(market="spot", symbol="BTCUSDT", event_type="book_ticker", transport="ws")
    stats.observe(_event(delay_ms=None))
    assert stats.events == 1
    assert stats.latency.samples == 0
    assert stats.latency.quantile(0.99) is None
    assert stats.as_dict()["network_delay_ms"]["samples"] == 0


def test_bounded_telemetry_survives_a_long_virtual_capture() -> None:
    """One million events across many streams still costs a bounded footprint."""
    stats_by_stream: dict[str, StreamStats] = {}
    for index in range(1_000_000):
        key = f"s{index % 60}"
        stats = stats_by_stream.get(key)
        if stats is None:
            stats = StreamStats(market="spot", symbol=key, event_type="agg_trade", transport="ws")
            stats_by_stream[key] = stats
        stats.observe(_event(delay_ms=index % 300, agg_id=index))

    merged = merge_latency_histograms(stats.latency for stats in stats_by_stream.values())
    assert merged.samples == 1_000_000
    assert _histogram_bytes(merged) <= 64 * LATENCY_BUCKETS
    assert len(LATENCY_LADDER_MS) + 2 == LATENCY_BUCKETS


def test_the_ladder_is_strictly_increasing_and_reaches_the_ceiling() -> None:
    assert all(lower < upper for lower, upper in pairwise(LATENCY_LADDER_MS))
    assert LATENCY_LADDER_MS[-1] == 600_000
    assert len(LATENCY_LADDER_MS) + 2 == LATENCY_BUCKETS
