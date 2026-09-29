"""Collector ingest, replay and runtime-isolation tests (§30, §31, §54).

These tests never open a socket. The collector's ingest path is driven directly
through ``handle_message`` and ``install_snapshot`` so hostile inputs — duplicate
ids, id jumps, future timestamps, malformed payloads — can be asserted
deterministically instead of waiting for a venue to misbehave on its own.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.forward.collector import (
    CollectorConfig,
    ForwardCollector,
    provider_stream_status,
    subscriptions_for,
)
from trading_bot.research.forward.contract import EventType, Market, Transport
from trading_bot.research.forward.replay import ForwardReplay, replay_microstructure_dataset
from trading_bot.research.forward.reporting import (
    build_aggregation,
    build_quality_report,
    build_readiness,
    save_aggregation,
)

FORWARD_PACKAGE = (
    Path(__file__).resolve().parents[3] / "src" / "trading_bot" / "research" / "forward"
)

#: §3: the trading runtime this phase must never touch.
FORBIDDEN_IMPORT_PREFIXES = (
    "trading_bot.risk",
    "trading_bot.paper",
    "trading_bot.execution",
    "trading_bot.autonomous",
    "trading_bot.portfolio",
    "trading_bot.strategies",
    "trading_bot.scanner",
    "trading_bot.backtesting",
    "trading_bot.feedback",
    "trading_bot.market_structure",
)

SPOT_PLAN = subscriptions_for(("BTCUSDT",))


def _collector(tmp_path: Path, **overrides: Any) -> ForwardCollector:
    options: dict[str, Any] = {
        "root": tmp_path,
        "symbols": ("BTCUSDT",),
        "markets": (Market.SPOT,),
        "keep_raw": False,
        "rotation_seconds": 3600,
        # Synthetic event clocks are ancient relative to the wall clock, so the
        # staleness window is widened. It travels in the manifest, so replay uses
        # the same value and the books stay comparable.
        "stale_after_ms": 10**15,
    }
    options.update(overrides)
    return ForwardCollector(CollectorConfig(**options))


# ------------------------------------------------------- graceful stop (§51)


def test_a_stop_file_ends_the_wait_without_a_signal(tmp_path: Path) -> None:
    """The portable stop: a file, because Windows cannot deliver SIGTERM."""
    stop_file = tmp_path / "STOP"
    collector = _collector(tmp_path / "capture", stop_file=stop_file)

    async def scenario() -> None:
        waiting = asyncio.create_task(collector._wait_until_stopped())
        await asyncio.sleep(0.05)
        assert not waiting.done()
        stop_file.write_text("stop requested\n", encoding="utf-8")
        await asyncio.wait_for(waiting, timeout=10.0)

    asyncio.run(scenario())
    assert collector.stop_reason == "stop file"
    assert collector._stop_file_present() is True


def test_the_reason_a_capture_ended_is_recorded(tmp_path: Path) -> None:
    """A capture stopped by its duration must not claim it was stopped by an operator."""
    collector = _collector(tmp_path / "capture", duration_seconds=0.05)
    asyncio.run(collector._wait_until_stopped())
    assert collector.stop_reason == "duration reached"


def test_a_first_reason_wins_and_no_stop_file_means_no_request(tmp_path: Path) -> None:
    collector = _collector(tmp_path / "capture")
    assert collector.stop_reason is None
    assert collector._stop_file_present() is False
    collector.stop("disk budget")
    collector.stop("signal")
    assert collector.stop_reason == "disk budget"


def test_the_manifest_carries_the_stop_reason(tmp_path: Path) -> None:
    """The manifest is where the operator reads why the capture ended."""
    collector = _collector(tmp_path / "capture", stop_file=tmp_path / "STOP")
    collector.stop("stop file")
    payload = collector.finalise().as_dict()
    assert payload["stop_reason"] == "stop file"
    assert payload["stopped_on_disk_budget"] is False


def _rows(collector: ForwardCollector) -> list[dict[str, Any]]:
    rows, _ = ForwardReplay(collector.root, collector.run_id).load_rows()
    return rows


def _send(
    collector: ForwardCollector,
    payload: dict[str, Any],
    stream: str,
    ts: int,
    market: Market = Market.SPOT,
) -> None:
    collector.handle_message(market, SPOT_PLAN, payload, ts, 1, stream)


def _trade(
    collector: ForwardCollector,
    agg_id: int,
    *,
    trade_time: int = 1_000,
    receive_time: int | None = None,
    buyer_maker: bool = False,
) -> None:
    _send(
        collector,
        {
            "e": "aggTrade",
            "E": trade_time,
            "s": "BTCUSDT",
            "a": agg_id,
            "p": "100.00",
            "q": "1",
            "f": 10,
            "l": 10,
            "T": trade_time,
            "m": buyer_maker,
        },
        "btcusdt@aggTrade",
        trade_time if receive_time is None else receive_time,
    )


def _depth_payload(
    first: int, last: int, *, ts: int, qty: str = "1", price: str = "100.00"
) -> dict[str, Any]:
    return {
        "e": "depthUpdate",
        "E": ts,
        "s": "BTCUSDT",
        "U": first,
        "u": last,
        "b": [[price, qty]],
        "a": [["101.00", qty]],
    }


# ----------------------------------------------------------------------- ingest


def test_a_clean_trade_is_persisted_with_all_three_clocks(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100, trade_time=1_000)
    rows = _rows(collector)
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "agg_trade"
    assert row["aggressor_side"] == "buy"
    assert row["exchange_event_time"] == 1_000
    assert row["receive_time"] == 1_000
    assert isinstance(row["process_time"], int)
    assert row["market"] == "spot"
    assert row["transport"] == "ws"
    assert row["sequence"] == {"first": 100, "last": 100, "prev": None}
    assert row["trade_count"] == 1
    assert row["schema_version"] == "forward-event-v1"


def test_buyer_maker_flag_maps_to_the_aggressor_not_the_maker(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 1, buyer_maker=True)
    assert _rows(collector)[0]["aggressor_side"] == "sell"


def test_a_missing_aggregate_trade_id_is_measured_not_guessed(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _trade(collector, 104, trade_time=1_001)
    assert collector.stats["spot|BTCUSDT|agg_trade"].sequence_gaps == 1
    gap = next(g for g in collector.gaps if g.reason == "AGG_TRADE_ID_JUMP")
    assert gap.estimated_lost_events == 3
    assert gap.data_lost is True
    assert gap.recovered is False


def test_a_duplicate_aggregate_trade_id_does_not_move_the_chain(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _trade(collector, 100)
    assert collector.stats["spot|BTCUSDT|agg_trade"].duplicates == 1
    assert collector.stats["spot|BTCUSDT|agg_trade"].sequence_gaps == 0
    assert collector.last_agg_trade_id["spot|BTCUSDT"] == 100


def test_an_out_of_order_aggregate_trade_id_is_counted(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _trade(collector, 99)
    assert collector.stats["spot|BTCUSDT|agg_trade"].out_of_order == 1
    assert collector.last_agg_trade_id["spot|BTCUSDT"] == 100


def test_a_future_exchange_timestamp_is_quarantined_not_stored(tmp_path: Path) -> None:
    collector = _collector(tmp_path, max_event_skew_ms=50)
    _trade(collector, 1, trade_time=10_000, receive_time=9_000)
    rows = _rows(collector)
    assert collector.clock_violations == 1
    assert [row["event_type"] for row in rows] == ["violation"]
    assert rows[0]["detail"]["kind"] == "TEMPORAL_GUARANTEE"
    assert collector._evaluate_state(10_000) == "FAILED"


def test_timestamp_regression_shows_up_as_a_negative_network_delay(tmp_path: Path) -> None:
    """A trade whose venue clock goes backwards must stay visible, not be smoothed."""
    collector = _collector(tmp_path, max_event_skew_ms=100_000)
    _trade(collector, 1, trade_time=2_000, receive_time=2_000)
    _trade(collector, 2, trade_time=1_000, receive_time=500)
    rows = [row for row in _rows(collector) if row["event_type"] == "agg_trade"]
    assert [row["network_delay_ms"] for row in rows] == [0, -500]


@pytest.mark.parametrize(
    "payload",
    [
        {"e": "aggTrade", "a": "not-an-int", "T": 1, "p": "1", "q": "1", "m": False},
        {"e": "aggTrade", "a": 1, "T": 1, "p": 1, "q": "1", "m": False},
        {"e": "aggTrade", "a": 1, "T": 1, "p": "1", "q": "1"},
        {"e": "aggTrade", "a": 1, "T": 1, "p": "1", "q": "1", "m": False, "f": 5, "l": 4},
    ],
)
def test_a_malformed_trade_payload_produces_a_violation_and_no_data_row(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    collector = _collector(tmp_path)
    _send(collector, payload, "btcusdt@aggTrade", 1)
    rows = _rows(collector)
    assert rows
    assert {row["event_type"] for row in rows} == {"violation"}
    assert rows[0]["detail"]["kind"] == "MALFORMED_PAYLOAD"


def test_a_malformed_book_ticker_produces_a_violation(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _send(collector, {"u": 1, "s": "BTCUSDT", "b": "100", "a": "101"}, "btcusdt@bookTicker", 1)
    assert _rows(collector)[0]["detail"]["kind"] == "MALFORMED_PAYLOAD"


def test_spot_book_ticker_documents_that_it_has_no_event_time(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _send(
        collector,
        {"u": 7, "s": "BTCUSDT", "b": "100.00", "B": "1", "a": "101.00", "A": "2"},
        "btcusdt@bookTicker",
        5_000,
    )
    row = _rows(collector)[0]
    assert row["exchange_event_time"] is None
    assert row["network_delay_ms"] is None
    assert row["detail"]["event_time_available"] is False


def test_an_unknown_stream_is_ignored_rather_than_guessed(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _send(collector, {"e": "aggTrade"}, "unknown@stream", 1)
    assert _rows(collector) == []


def test_depth_diffs_are_persisted_even_while_the_book_is_not_usable(tmp_path: Path) -> None:
    """Raw evidence outranks derived state: a broken book must not lose the feed."""
    collector = _collector(tmp_path)
    _send(collector, _depth_payload(10, 20, ts=1_000), "btcusdt@depth@100ms", 1_000)
    syncer = collector.books["spot|BTCUSDT"]
    assert syncer.book.last_update_id is None
    assert syncer.buffered_updates == 1
    row = _rows(collector)[0]
    assert row["event_type"] == "depth_diff"
    assert row["detail"]["disposition"] == "BUFFERED"
    assert row["detail"]["book_health"] == "RECOVERING"


def test_a_depth_sequence_break_records_a_gap_and_invalidates_the_book(
    tmp_path: Path,
) -> None:
    collector = _collector(tmp_path)
    collector.install_snapshot(
        Market.SPOT,
        "BTCUSDT",
        last_update_id=100,
        bids_raw=[["99.90", "5"]],
        asks_raw=[["101.10", "5"]],
        receive_time=1_000,
        stream="depth",
    )
    _send(collector, _depth_payload(101, 105, ts=1_001), "btcusdt@depth@100ms", 1_001)
    assert collector.books["spot|BTCUSDT"].is_live
    _send(collector, _depth_payload(200, 205, ts=1_100), "btcusdt@depth@100ms", 1_100)
    assert collector.books["spot|BTCUSDT"].health(1_100).value == "INVALID"
    assert any(gap.reason == "DEPTH_SEQUENCE_BREAK" for gap in collector.gaps)
    assert collector.stats["spot|BTCUSDT|depth_diff"].sequence_gaps == 1


def test_an_unbridgeable_snapshot_is_recorded_as_a_gap(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    _send(collector, _depth_payload(1_100, 1_105, ts=1_100), "btcusdt@depth@100ms", 1_100)
    outcome = collector.install_snapshot(
        Market.SPOT,
        "BTCUSDT",
        last_update_id=1_000,
        bids_raw=[["99.90", "5"]],
        asks_raw=[["101.10", "5"]],
        receive_time=1_100,
        stream="depth",
    )
    assert outcome is not None and outcome.value == "GAP"
    assert any(g.reason == "SNAPSHOT_CANNOT_BRIDGE_BUFFER" for g in collector.gaps)


def test_a_snapshot_without_an_update_id_is_a_violation_not_a_live_book(
    tmp_path: Path,
) -> None:
    collector = _collector(tmp_path)
    outcome = collector.install_snapshot(
        Market.SPOT,
        "BTCUSDT",
        last_update_id=None,
        bids_raw=[["99.90", "5"]],
        asks_raw=[["101.10", "5"]],
        receive_time=1_000,
        stream="depth",
    )
    assert outcome is None
    assert collector.resnapshots_failed == 1
    assert not collector.books["spot|BTCUSDT"].is_live


def test_a_silent_websocket_stream_is_reported_as_no_data(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    assert provider_stream_status(collector.stats)["spot/BTCUSDT/agg_trade"]["verdict"] == "NO_DATA"
    assert provider_stream_status(collector.stats)["spot/BTCUSDT/agg_trade"]["lossless"] is True
    _trade(collector, 1)
    assert provider_stream_status(collector.stats)["spot/BTCUSDT/agg_trade"]["verdict"] == (
        "OBSERVED"
    )


def test_spot_has_no_open_interest_stream_to_subscribe_to(tmp_path: Path) -> None:
    collector = _collector(tmp_path, markets=(Market.SPOT, Market.PERP))
    verdicts = provider_stream_status(collector.stats)
    assert "spot/BTCUSDT/open_interest" not in verdicts
    assert verdicts["perp/BTCUSDT/open_interest"]["verdict"] == "NO_DATA"


def test_stream_selection_is_explicit_and_nonsense_is_rejected(tmp_path: Path) -> None:
    collector = _collector(tmp_path, streams=("agg_trade",))
    assert sorted(subscriptions_for(("BTCUSDT",), collector.config.streams)) == ["btcusdt@aggTrade"]
    assert collector._active_event_types() == (EventType.AGG_TRADE,)
    assert "spot|BTCUSDT|book_ticker" not in collector.stats
    with pytest.raises(ValueError):
        subscriptions_for(("BTCUSDT",), ("not_a_stream",))


def test_every_lossless_stream_travels_over_websocket(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    assert collector.stats["spot|BTCUSDT|agg_trade"].transport == Transport.WS.value
    assert collector.stats["spot|BTCUSDT|depth_diff"].transport == Transport.WS.value
    assert collector.stats["spot|BTCUSDT|book_ticker"].transport == Transport.WS.value


def test_resume_records_the_downtime_as_a_documented_gap(tmp_path: Path) -> None:
    first = _collector(tmp_path, run_id="run-resume")
    _trade(first, 1)
    first._save_state()

    resumed = _collector(tmp_path, run_id="run-resume", resume=True)
    resumed._load_resume()
    assert resumed.last_agg_trade_id == {"spot|BTCUSDT": 1}
    restart_gaps = [gap for gap in resumed.gaps if gap.reason == "COLLECTOR_RESTART"]
    assert restart_gaps
    assert all(gap.data_lost for gap in restart_gaps)
    assert all(not gap.recovered for gap in restart_gaps)


# ----------------------------------------------------------------------- replay


def _build_dataset(tmp_path: Path) -> tuple[Path, str]:
    """Build a dataset through the production ingest path, then finalise it."""
    collector = _collector(tmp_path / "dataset", run_id="run-replay")
    _send(collector, _depth_payload(101, 105, ts=1_000), "btcusdt@depth@100ms", 1_000)
    _send(collector, _depth_payload(106, 110, ts=1_100), "btcusdt@depth@100ms", 1_100)
    collector.install_snapshot(
        Market.SPOT,
        "BTCUSDT",
        last_update_id=100,
        bids_raw=[["99.90", "5"], ["99.80", "5"]],
        asks_raw=[["101.10", "5"], ["101.20", "5"]],
        receive_time=1_200,
        stream="depth",
    )
    collector.checkpoint_books()
    _send(
        collector,
        _depth_payload(111, 115, ts=1_300, price="100.20"),
        "btcusdt@depth@100ms",
        1_300,
    )
    for index in range(3):
        _trade(collector, 500 + index, trade_time=1_300 + index)
    collector.checkpoint_books()
    manifest = collector.finalise()
    return collector.root, manifest.run_id


def test_replay_reconstructs_counts_books_and_fingerprints(tmp_path: Path) -> None:
    root, run_id = _build_dataset(tmp_path)
    verification = replay_microstructure_dataset(root, run_id)
    assert verification.errors == []
    assert verification.internet_access is False
    assert verification.rows > 0
    assert verification.partial_tails == 0
    assert verification.event_count_match is True
    assert verification.event_count_differences == []
    assert verification.trade_sequence_ok is True
    assert verification.book_match is True
    assert verification.books
    assert all(book.ok for book in verification.books)
    assert verification.books[0].checkpoints > 0
    assert verification.fingerprints_match is True
    assert verification.fingerprint_checks == verification.fingerprint_matches
    assert verification.deterministic is True
    assert verification.aggregation_digest == verification.second_pass_digest


def test_replay_detects_a_segment_changed_after_the_capture(tmp_path: Path) -> None:
    root, run_id = _build_dataset(tmp_path)
    segment = sorted(root.rglob("*.jsonl.gz"))[0]
    payload = segment.read_bytes()
    segment.write_bytes(payload[:-8] + b"\x00" * 8)

    verification = replay_microstructure_dataset(root, run_id)
    assert verification.fingerprints_match is False
    assert any(
        mismatch["reason"] == "sha256_changed" for mismatch in verification.fingerprint_mismatches
    )
    assert verification.ok is False


def test_a_segment_extended_after_the_capture_is_detected(tmp_path: Path) -> None:
    """A row appended after the manifest was written must not pass verification."""
    root, run_id = _build_dataset(tmp_path)
    segment = sorted(root.rglob("*.jsonl.gz"))[0]
    with segment.open("ab") as handle:
        handle.write(b'{"schema_version":"forward-event-v1"}\n')
    verification = replay_microstructure_dataset(root, run_id)
    assert verification.fingerprints_match is False
    assert verification.partial_tails + len(verification.fingerprint_mismatches) > 0
    assert verification.ok is False


def test_replay_never_touches_the_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, run_id = _build_dataset(tmp_path)

    def _forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("replay attempted network access")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    verification = replay_microstructure_dataset(root, run_id)
    assert verification.internet_access is False


def test_the_recorded_aggregation_digest_lets_replay_prove_feature_equality(
    tmp_path: Path,
) -> None:
    root, run_id = _build_dataset(tmp_path)
    resolved, aggregation = build_aggregation(root, run_id)
    assert resolved == run_id
    assert aggregation.event_counts.get("agg_trade") == 3
    save_aggregation(root, run_id, aggregation)

    verification = replay_microstructure_dataset(root, run_id)
    assert verification.recorded_aggregation_digest is not None
    assert verification.feature_match is True
    assert verification.ok is True


def test_the_feature_digest_is_a_function_of_the_rows_not_the_manifest(
    tmp_path: Path,
) -> None:
    """§32 — the digest must not be seeded from the artifact that describes the run.

    The manifest is a second document about the same bytes. Seeding the replay's
    aggregation from it made the digest depend on which call site had tallied the
    rows, so the real capture reported a feature mismatch that was only an inputs
    disagreement. Moving one stream counter must therefore leave the digest
    comparison intact while the manifest reconciliation catches the drift.
    """
    root, run_id = _build_dataset(tmp_path)
    _resolved, aggregation = build_aggregation(root, run_id)
    save_aggregation(root, run_id, aggregation)

    manifest_path = root / "manifest" / f"{run_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["streams"][0]["events"] += 1
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    verification = replay_microstructure_dataset(root, run_id)
    assert verification.feature_match is True
    assert verification.aggregation_digest == verification.recorded_aggregation_digest
    assert verification.event_count_match is False
    assert verification.event_count_differences
    assert verification.ok is False


def test_a_bucket_is_only_complete_when_the_whole_window_was_captured(
    tmp_path: Path,
) -> None:
    root, run_id = _build_dataset(tmp_path)
    _resolved, aggregation = build_aggregation(root, run_id)
    trades = aggregation.as_dict()["trades"]["spot/BTCUSDT"]
    assert trades
    # The capture is a couple of seconds long, so no 1m bucket is whole.
    assert all(bucket["complete"] is False for bucket in trades)
    assert all(bucket["available_at_ms"] == bucket["close_time_ms"] for bucket in trades)
    assert all(bucket["available_at_ms"] > bucket["open_time_ms"] for bucket in trades)


def test_quality_report_never_claims_a_higher_frequency_source_than_reality(
    tmp_path: Path,
) -> None:
    root, run_id = _build_dataset(tmp_path)
    report = build_quality_report(root, run_id)
    assert report["totals"]["rows_on_disk"] > 0
    assert report["cases"]["rest_polling_used_for_high_frequency_trades"] is False
    # Infrastructure is fine but the sample is a fraction of a second: the only
    # honest verdict is "still collecting", never "ready".
    assert report["readiness"]["M-03"]["verdict"] == "COLLECTING"
    m03 = report["readiness"]["M-03"]["available"]
    assert m03["books_healthy_at_a_checkpoint"]
    assert m03["healthy_checkpoint_ratio"]
    assert report["readiness"]["M-07"]["verdict"] == "NOT_READY"
    assert _contains_no_profitability_vocabulary(report)


#: §24 — the commit that produced the certified capture.
CERTIFIED_CAPTURE_COMMIT = "7fb9429e765dbf0d520e6a58df3dabacc05dbbde"

#: Paths whose bytes must match that commit, because they are what the capture
#: executed. ``storage.py`` is deliberately absent: it gained one streaming reader
#: that the writer never imports, which the independent verifier proves
#: unreachable rather than assuming. Read-side reporting lives in
#: ``scripts/forward_report.py`` so that the capture entry point does not have to
#: change to gain a reporting flag.
CAPTURE_CRITICAL_PATHS = (
    "scripts/forward_collector.py",
    "src/trading_bot/research/forward/collector.py",
    "src/trading_bot/research/forward/orderbook.py",
    "src/trading_bot/research/forward/contract.py",
)


def test_the_capture_code_still_matches_the_certified_commit() -> None:
    """A capture certificate is only as good as the code that produced it.

    Editing the collector, the book, the contract or the capture CLI after the
    fact is not forbidden — but it silently invalidates the equality between the
    captured dataset and the tree that claims to explain it, so it has to be a
    deliberate decision (a new capture, or an explicit re-certification) instead
    of a side effect of adding a flag.
    """
    import subprocess

    root = FORWARD_PACKAGE.parents[2]
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{CERTIFIED_CAPTURE_COMMIT}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("the certified capture commit is not in this clone")
    for relative in CAPTURE_CRITICAL_PATHS:
        result = subprocess.run(
            ["git", "diff", "--quiet", CERTIFIED_CAPTURE_COMMIT, "--", relative],
            cwd=root,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{relative} differs from the commit that produced the certified "
            "capture; the dataset can no longer be explained by this tree without "
            "a re-run"
        )


def _readiness_fixture(book: dict[str, Any]) -> dict[str, Any]:
    return {
        "books": {"perp/BTCUSDT": book},
        "streams": {"perp/BTCUSDT/depth_diff": {"sequence_gaps": 0}},
        "totals": {
            "book_update_events": 1,
            "book_checkpoint_events": 118,
            "open_interest_events": 0,
        },
        "capture": {"duration_seconds": 60.0},
    }


def test_a_book_that_ends_the_capture_stale_is_still_usable_history() -> None:
    """§9 — the writer's health is sticky, so the last checkpoint is not the run.

    A capture that stops seconds after a reconnect ends STALE even when nearly every
    checkpoint was HEALTHY. Treating that as "no book ever reached HEALTHY" would
    call usable book history unusable and would misstate why a phase is blocked.
    """
    report = _readiness_fixture(
        {"healthy": 114, "usable_ratio": 0.966102, "final_health": "STALE", "crossed_book_events": 0}
    )
    readiness = build_readiness(report, {"gaps": [], "integrity": {}})
    available = readiness["M-03"]["available"]
    assert available["books_healthy_at_a_checkpoint"] == ["perp/BTCUSDT"]
    assert available["books_ending_healthy"] == []
    assert not [reason for reason in readiness["M-03"]["blocking"] if "no book" in reason]
    assert readiness["M-03"]["verdict"] == "COLLECTING"


def test_a_book_never_healthy_at_a_checkpoint_is_not_infrastructure() -> None:
    report = _readiness_fixture(
        {"healthy": 0, "usable_ratio": 0.0, "final_health": "INVALID", "crossed_book_events": 0}
    )
    readiness = build_readiness(report, {"gaps": [], "integrity": {}})
    assert readiness["M-03"]["available"]["books_healthy_at_a_checkpoint"] == []
    assert any("no book was observed HEALTHY" in r for r in readiness["M-03"]["blocking"])
    assert readiness["M-03"]["verdict"] == "NOT_READY"


def _contains_no_profitability_vocabulary(payload: object) -> bool:
    banned = ("profit", "paper_candidate", "live_ready", "profitable")
    text = json.dumps(payload, default=str).lower()
    return not any(token in text for token in banned)


def test_manifest_records_the_contract_and_the_selected_streams(tmp_path: Path) -> None:
    _root, run_id = _build_dataset(tmp_path)
    collector_manifest = ForwardReplay(tmp_path / "dataset", run_id).manifest
    assert collector_manifest["contract_version"] == "FORWARD-DATA-CONTRACT-V1"
    assert collector_manifest["schema_version"] == "forward-event-v1"
    assert collector_manifest["integrity"]["streams_selected"] == [
        "agg_trade",
        "depth",
        "book_ticker",
    ]
    assert collector_manifest["provider_stream_status"]["spot/BTCUSDT/agg_trade"]["verdict"] == (
        "OBSERVED"
    )


# -------------------------------------------------------------- runtime isolation


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_forward_package_does_not_import_the_trading_runtime() -> None:
    """§3/§40/§55: the collector cannot change a decision, a risk check or an order."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(FORWARD_PACKAGE.glob("*.py")):
        bad = [
            module
            for module in _imported_modules(path)
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            )
        ]
        if bad:
            offenders[path.name] = sorted(bad)
    assert not offenders, f"forward package imports the trading runtime: {offenders}"


def test_forward_package_only_imports_itself_from_trading_bot() -> None:
    for path in sorted(FORWARD_PACKAGE.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith("trading_bot"):
                assert module.startswith("trading_bot.research.forward"), (
                    f"{path.name} reaches outside the discovery plane: {module}"
                )


def test_forward_source_holds_no_credentials_or_order_endpoints() -> None:
    """Docstrings may *say* "no secret"; the code must not contain one."""
    forbidden = (
        "api_key",
        "apikey",
        "x-mbx-apikey",
        "/api/v3/order",
        "/fapi/v1/order",
        "listenkey",
        "withdraw",
        "privatekey",
    )
    for path in sorted(FORWARD_PACKAGE.glob("*.py")):
        code = _strip_docstrings(path.read_text(encoding="utf-8")).lower()
        for token in forbidden:
            assert token not in code, f"{path.name} mentions {token!r}"


def _strip_docstrings(source: str) -> str:
    """Remove triple-quoted blocks so prose cannot satisfy or trip a scan."""
    import re

    return re.sub(r'""".*?"""', "", source, flags=re.DOTALL)


def test_the_collector_only_speaks_to_public_market_data_endpoints() -> None:
    from trading_bot.research.forward.collector import PERP_REST, PERP_WS, SPOT_REST, SPOT_WS

    assert SPOT_REST == "https://api.binance.com"
    assert PERP_REST == "https://fapi.binance.com"
    assert SPOT_WS.startswith("wss://stream.binance.com")
    assert PERP_WS == "wss://fstream.binance.com"


# ------------------------------------------- trade recovery and state (§26, §29)


def _agg_row(agg_id: int, *, trade_time: int = 1_000) -> dict[str, Any]:
    return {
        "e": "aggTrade",
        "E": trade_time,
        "T": trade_time,
        "s": "BTCUSDT",
        "a": agg_id,
        "p": "100.00",
        "q": "1",
        "f": agg_id,
        "l": agg_id,
        "m": False,
    }


def _fake_index(
    collector: ForwardCollector,
    monkeypatch: pytest.MonkeyPatch,
    *,
    last_id: int,
    fail: bool = False,
) -> list[dict[str, Any]]:
    """A stand-in for the public aggregate-trade index with real ``fromId`` paging.

    Ids ``1..last_id`` exist, ``fromId`` starts the page at that id, and ``limit``
    caps its size — the same contract the venue documents, so a paging bug shows
    up here instead of against the live venue.
    """
    calls: list[dict[str, Any]] = []

    async def _get(
        _session: Any, _market: Market, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        calls.append({"path": path, "params": dict(params)})
        if fail:
            raise RuntimeError("HTTP 418 from the trade index")
        first = int(params["fromId"])
        limit = int(params["limit"])
        stop = min(first + limit, last_id + 1)
        return [_agg_row(agg_id) for agg_id in range(first, stop)]

    monkeypatch.setattr(collector, "_session", object())
    monkeypatch.setattr(collector, "_rest_get", _get)
    return calls


def _trades(collector: ForwardCollector) -> list[dict[str, Any]]:
    return [row for row in _rows(collector) if row["event_type"] == "agg_trade"]


def test_the_public_trade_index_closes_a_post_connect_hole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _trade(collector, 101)
    calls = _fake_index(collector, monkeypatch, last_id=104)
    asyncio.run(
        collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 6_000, "websocket CLOSED")
    )
    rows = _trades(collector)
    assert [row["exchange_event_id"] for row in rows] == ["100", "101", "102", "103", "104"]
    # A recovered row is still a row of the sequenced WS stream; what marks it
    # as repaired is its origin, not a transport label that would break §55.
    assert {row["transport"] for row in rows} == {"ws"}
    assert [row["detail"]["origin"] for row in rows] == [
        "ws",
        "ws",
        "agg_trade_backfill",
        "agg_trade_backfill",
        "agg_trade_backfill",
    ]
    assert calls[0]["path"] == "/api/v3/aggTrades"
    # The first unknown id is the one after the last one we actually saw.
    assert calls[0]["params"]["fromId"] == 102
    gap = next(g for g in collector.gaps if g.reason == "WS_DISCONNECT")
    assert gap.status == "RECOVERED_COMPLETE"
    assert gap.recovered is True
    assert gap.data_lost is False
    assert gap.recovered_events == 3
    assert collector.backfill_gaps_closed == 1


def test_a_recovered_trade_is_never_written_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _fake_index(collector, monkeypatch, last_id=102)
    asyncio.run(collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 6_000, None))
    # The live stream now replays the same ids it already received from REST.
    _trade(collector, 101, trade_time=1_900)
    _trade(collector, 102, trade_time=1_900)
    _trade(collector, 103, trade_time=1_900)
    rows = _trades(collector)
    assert [row["exchange_event_id"] for row in rows] == ["100", "101", "102", "103"]
    assert collector.stats["spot|BTCUSDT|agg_trade"].duplicates == 2
    assert collector.last_agg_trade_id["spot|BTCUSDT"] == 103


def test_an_unreachable_trade_index_leaves_the_hole_as_real_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    _fake_index(collector, monkeypatch, last_id=999, fail=True)
    asyncio.run(
        collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 6_000, "websocket CLOSED")
    )
    gap = next(g for g in collector.gaps if g.reason == "WS_DISCONNECT")
    assert gap.status == "UNRECOVERABLE"
    assert gap.recovered is False
    assert gap.data_lost is True
    assert collector.backfill_failures == 1
    assert collector.backfill_gaps_closed == 0
    counts = {row["event_type"] for row in _rows(collector)}
    assert "violation" in counts


def test_a_hole_wider_than_the_page_cap_stays_unrecovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trading_bot.research.forward.collector import BACKFILL_MAX_PAGES, BACKFILL_PAGE_LIMIT

    collector = _collector(tmp_path)
    _trade(collector, 0)
    # Seven times the page budget of ids is missing: the walk cannot finish.
    _fake_index(collector, monkeypatch, last_id=BACKFILL_MAX_PAGES * BACKFILL_PAGE_LIMIT * 7)
    asyncio.run(collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 6_000, None))
    gap = next(g for g in collector.gaps if g.reason == "WS_DISCONNECT")
    assert gap.status == "RECOVERED_PARTIAL"
    assert gap.recovered is False
    assert gap.data_lost is True
    assert gap.recovered_events == BACKFILL_MAX_PAGES * BACKFILL_PAGE_LIMIT
    assert collector.backfilled_events == BACKFILL_MAX_PAGES * BACKFILL_PAGE_LIMIT
    assert collector.backfill_partial == 1


def test_an_immediate_close_is_not_a_gap_because_no_window_was_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _collector(tmp_path)
    _trade(collector, 100)
    calls = _fake_index(collector, monkeypatch, last_id=100)
    asyncio.run(collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 5_000, None))
    gap = next(g for g in collector.gaps if g.reason == "WS_DISCONNECT")
    assert gap.data_lost is False
    assert calls == []


def test_the_id_window_stays_bounded_over_a_long_capture() -> None:
    from trading_bot.research.forward.collector import RECENT_ID_WINDOW, _IdWindow

    window = _IdWindow(8)
    for value in range(1_000):
        window.add(value)
    assert 999 in window
    assert 999 - RECENT_ID_WINDOW not in window
    window.add(999)
    assert len(window._order) == 8


def test_a_recoverable_disconnect_is_degraded_and_a_dead_market_is_failed(
    tmp_path: Path,
) -> None:
    collector = _collector(tmp_path, markets=(Market.SPOT, Market.PERP))
    collector.connected = {"spot": True, "perp": True}
    collector._started_ms = 0
    _trade(collector, 1, receive_time=1_000)
    # The perp socket closed a moment ago: the reconnect is still in flight.
    collector.connected["perp"] = False
    collector._market_down_since["perp"] = time.time()
    assert collector._evaluate_state(10_000) == "DEGRADED"
    # A socket that never comes back is not a condition to keep writing through.
    collector._market_down_since["perp"] = time.time() - 120.0
    assert collector._evaluate_state(10_000) == "FAILED"


def test_a_book_that_never_converges_fails_but_a_recovered_one_does_not(
    tmp_path: Path,
) -> None:
    collector = _collector(tmp_path)
    collector._started_ms = 0
    _trade(collector, 1, receive_time=1_000)
    collector.connected = {"spot": True}
    key = "spot|BTCUSDT"
    collector._book_unavailable_since[key] = time.time()
    assert collector._evaluate_state(10_000) == "DEGRADED"
    collector._book_unavailable_since[key] = time.time() - 400.0
    assert collector._evaluate_state(10_000) == "FAILED"
    # A book that has been healthy before is being reconciled, not abandoned.
    collector._book_ever_healthy.add(key)
    assert collector._evaluate_state(10_000) == "DEGRADED"


def test_repeated_reconciliation_failures_fail_the_collector(tmp_path: Path) -> None:
    from trading_bot.research.forward.collector import BOOK_IRRECOVERABLE_FAILURES

    collector = _collector(tmp_path)
    _trade(collector, 1, receive_time=1_000)
    collector.connected = {"spot": True}
    collector.resnapshots_failed = BOOK_IRRECOVERABLE_FAILURES - 1
    assert collector._evaluate_state(10_000) != "FAILED"
    collector.resnapshots_failed = BOOK_IRRECOVERABLE_FAILURES
    assert collector._evaluate_state(10_000) == "FAILED"


def test_the_disk_budget_stops_the_capture_gracefully(tmp_path: Path) -> None:
    """§8 — the guard stops, seals and finalises instead of filling the volume."""
    collector = _collector(tmp_path, max_total_bytes=1, maintenance_seconds=0.01)
    _trade(collector, 1, receive_time=1_000)

    async def _scenario() -> None:
        task = asyncio.create_task(collector._maintenance_loop())
        for _ in range(500):
            if collector._stopping:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())
    assert collector._stopping is True
    assert collector.stopped_on_disk_budget is True
    lifecycle = [row for row in _rows(collector) if row.get("event_type") == "lifecycle"]
    assert any(
        isinstance(row.get("detail"), dict) and row["detail"].get("kind") == "DISK_LIMIT_REACHED"
        for row in lifecycle
    )
    manifest = collector.finalise()
    assert manifest.stopped_on_disk_budget is True
    assert manifest.max_total_bytes == 1
    # A guard that left a half-written file behind would be worse than no guard.
    assert manifest.fingerprints
    assert all(entry.partial_tail is False for entry in manifest.fingerprints)


def test_a_live_id_jump_is_recovered_and_the_gap_records_its_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2, §11 — a measured hole is closed, and both phases are on disk."""
    collector = _collector(tmp_path)
    _fake_index(collector, monkeypatch, last_id=110)

    async def _scenario() -> None:
        _trade(collector, 100)
        _trade(collector, 110, trade_time=1_100)  # 101..109 were never seen live
        tasks = list(collector._backfill_tasks.values())
        assert tasks
        await asyncio.gather(*tasks)

    asyncio.run(_scenario())
    gap = next(g for g in collector.gaps if g.reason == "AGG_TRADE_ID_JUMP")
    assert gap.status == "RECOVERED_COMPLETE"
    assert gap.recovered is True
    assert gap.data_lost is False
    assert gap.recovered_events == 9
    assert gap.remaining_missing == 0

    ids = [int(row["exchange_event_id"]) for row in _trades(collector)]
    # Physical order is process order: the live 110 landed before the repaired
    # 101..109. Logical order is by id, and that is what a consumer must sort on.
    assert ids.index(110) < ids.index(101)
    assert sorted(ids) == list(range(100, 111))

    phases = [
        row["detail"]["phase"]
        for row in _rows(collector)
        if row.get("event_type") == "gap" and row["detail"]["gap_id"] == gap.gap_id
    ]
    assert phases == ["GAP_DETECTED", "RECOVERY_RESOLVED"]


def test_the_storage_footprint_is_measured_from_the_files_not_assumed(
    tmp_path: Path,
) -> None:
    """§9, §42 — GB/day has to come from bytes, or it is a guess."""
    from trading_bot.research.forward.reporting import build_resource_report

    root, run_id = _build_dataset(tmp_path)
    report = build_resource_report(root, run_id)
    footprint = report["footprint"]
    assert footprint["segments"] > 0
    assert footprint["stored_bytes"] > 0
    assert footprint["uncompressed_bytes"] >= footprint["stored_bytes"]
    assert footprint["compression_ratio"] is not None
    assert footprint["stored_gb_per_day"] is not None
    assert footprint["raw_gb_per_day"] >= footprint["stored_gb_per_day"]
    assert report["disk_guard"]["enabled"] is False  # this dataset had no budget
    assert report["disk_guard"]["stopped_on_disk_budget"] is False


def test_a_budgeted_capture_reports_its_guard_in_the_manifest(tmp_path: Path) -> None:
    collector = _collector(tmp_path, max_total_bytes=4096)
    _trade(collector, 1, receive_time=1_000)
    manifest = collector.finalise()
    assert manifest.max_total_bytes == 4096
    assert manifest.stopped_on_disk_budget is False
    assert manifest.uncompressed_bytes_written > 0
    saved = json.loads(
        (tmp_path / "manifest" / f"{collector.run_id}.json").read_text(encoding="utf-8")
    )
    assert saved["max_total_bytes"] == 4096


def test_row_streaming_matches_a_materialised_load(tmp_path: Path) -> None:
    """§34 — the analysis path must stream, and must not change the answer.

    A forward hour of one busy stream is a single segment of ~10^6 rows, so the
    analysis path may never hold a run in memory. Streaming is only acceptable if
    it is equivalent, so the two paths are compared row by row and aggregate by
    aggregate.
    """
    from trading_bot.research.forward.aggregation import aggregate_dataset

    root, run_id = _build_dataset(tmp_path)
    replay = ForwardReplay(root, run_id)

    materialised, partial_tails = replay.load_rows()
    streamed = [row for row, _ in replay.iter_rows()]
    assert partial_tails == 0
    assert json.dumps(streamed, sort_keys=True, default=str) == json.dumps(
        materialised, sort_keys=True, default=str
    )

    # A callable source lets the aggregation re-read the run instead of holding it.
    by_stream = aggregate_dataset(replay.iter_events, run_id=run_id)
    by_list = aggregate_dataset(list(replay.iter_events()), run_id=run_id)
    assert json.dumps(by_stream.as_dict(), sort_keys=True, default=str) == json.dumps(
        by_list.as_dict(), sort_keys=True, default=str
    )


def test_health_accounting_returns_to_healthy_after_a_recovered_disconnect() -> None:
    """§6 — DEGRADED -> reconcile -> HEALTHY, and only real loss stays unhealthy.

    The writer's own state is sticky, so the live view is derived from the
    recorded windows instead. A recoverable disconnect must show up as degraded
    *time* and then stop being degraded, while an unrecoverable hole must keep
    its seconds counted and stay visible as permanent loss.
    """
    from trading_bot.research.forward.reporting import build_health_accounting

    start = 1_800_000_000_000
    manifest = {
        "started_at": "2027-01-15T08:00:00+00:00",
        "ended_at": "2027-01-15T08:00:10+00:00",
        "duration_seconds": 10.0,
        "integrity": {"failures": None},
        # Exactly what the writer produces: one transition, and never back to
        # HEALTHY, because a recorded gap is never erased.
        "degradation_events": [
            {"at_ms": start + 500, "from": "HEALTHY", "to": "DEGRADED"},
        ],
        "gaps": [
            # A one-second hole on the stream the public index can repair.
            {
                "market": "spot",
                "symbol": "BTCUSDT",
                "event_type": "agg_trade",
                "start_ms": start,
                "end_ms": start + 1_000,
                "reason": "WS_DISCONNECT",
                "recovered": True,
                "data_lost": False,
                "recovered_events": 12,
                "estimated_lost_events": 12,
            },
            # A two-second hole nothing can repair.
            {
                "market": "perp",
                "symbol": "BTCUSDT",
                "event_type": "depth_diff",
                "start_ms": start + 4_000,
                "end_ms": start + 6_000,
                "reason": "WS_DISCONNECT",
                "recovered": False,
                "data_lost": True,
                "recovered_events": 0,
                "estimated_lost_events": None,
            },
            # A hole that exists but has no width: it costs no wall-clock time.
            {
                "market": "perp",
                "symbol": "ETHUSDT",
                "event_type": "depth_diff",
                "start_ms": start + 7_000,
                "end_ms": start + 7_000,
                "reason": "DEPTH_SEQUENCE_BREAK",
                "recovered": False,
                "data_lost": True,
                "recovered_events": 0,
                "estimated_lost_events": 5,
            },
        ],
    }
    # The socket-level downtime is wider than the loss window, so it must widen
    # the degraded time rather than be hidden inside a "healthy" second.
    lifecycle = [
        {"kind": "WS_DISCONNECTED", "market": "perp", "receive_time": start + 3_500},
        {"kind": "WS_CONNECTED", "market": "perp", "receive_time": start + 6_000},
    ]
    health = build_health_accounting(manifest, lifecycle)
    live = health["live"]

    # Degraded = [0, 1000) from the recovered disconnect, [3500, 6000) from the
    # reconnect, unioned with the [4000, 6000) unrecoverable window.
    assert live["degraded_seconds"] == 3.5
    assert live["healthy_seconds"] == 6.5
    assert live["failed_seconds"] == 0.0
    assert round(live["degraded_fraction"], 4) == 0.35
    assert live["degraded_episodes"] == 2
    assert live["episodes_returning_to_healthy"] == 2
    assert live["episodes_with_permanent_loss"] == 1
    assert live["instantaneous_loss_events"] == 1
    assert health["reconnect_downtime"]["cycles"] == 1
    assert health["reconnect_downtime"]["downtime_seconds_total"] == 2.5
    assert health["failed_run"] is False
    # The writer's sticky state is reported next to the live one, not instead:
    # it says 9.5 s degraded even though the data was healthy after 6 s.
    assert health["collector_state"]["sticky"] is True
    assert health["collector_state"]["seconds_by_state"] == {
        "DEGRADED": 9.5,
        "HEALTHY": 0.5,
    }


def test_a_fatal_run_reports_failed_time_instead_of_healthy_time() -> None:
    """§6 — FAILED is reserved for a condition the collector could not work around."""
    from trading_bot.research.forward.reporting import build_health_accounting

    manifest = {
        "started_at": "2027-01-15T08:00:00+00:00",
        "ended_at": "2027-01-15T08:00:10+00:00",
        "duration_seconds": 10.0,
        "integrity": {"failures": "storage failure: no space left on device"},
        "degradation_events": [],
        "gaps": [],
    }
    health = build_health_accounting(manifest, [])
    assert health["failed_run"] is True
    assert health["live"]["failed_seconds"] == 10.0
    assert health["live"]["healthy_seconds"] == 0.0


def test_a_hole_inside_a_recovered_page_never_restarts_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5 — a hole seen *inside* a backfill page is recorded, never re-walked.

    Recovery walks the public trade index. If a hole discovered while walking
    that very index scheduled another walk, the recovery would not terminate:
    the walk would keep re-entering itself. The bound must be deterministic, so
    the page is asserted to have been requested exactly once, the hole asserted
    to stay visible, and the deferral counted rather than hidden.
    """
    collector = _collector(tmp_path)
    _trade(collector, 100)
    calls: list[dict[str, Any]] = []

    async def _get(
        _session: Any, _market: Market, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        calls.append({"path": path, "params": dict(params)})
        first = int(params["fromId"])
        limit = int(params["limit"])
        # The index itself is missing id 103: no walk can close that hole.
        ids = [agg_id for agg_id in range(first, min(first + limit, 106)) if agg_id != 103]
        return [_agg_row(agg_id) for agg_id in ids]

    monkeypatch.setattr(collector, "_session", object())
    monkeypatch.setattr(collector, "_rest_get", _get)
    asyncio.run(
        collector._recover_agg_trade_gap(Market.SPOT, "BTCUSDT", 5_000, 6_000, "websocket CLOSED")
    )

    # The walk requested one page and did not re-enter the index for the hole it
    # found inside its own page.
    assert [call["params"]["fromId"] for call in calls] == [101]
    assert not collector._backfill_tasks
    assert collector.backfill_deferred == 1
    assert collector.backfill_failures == 0

    # The inner hole is real, visible and still open — it is not laundered into
    # the recovered prefix by the outer recovery succeeding.
    inner = [gap for gap in collector.gaps if gap.reason == "AGG_TRADE_ID_JUMP"]
    assert len(inner) == 1
    assert inner[0].estimated_lost_events == 1
    assert inner[0].remaining_missing == 1
    assert inner[0].status == "UNRECOVERABLE"
    assert inner[0].data_lost is True

    # Ids are unique on disk: the page and the live stream never both win.
    rows = _trades(collector)
    assert [row["exchange_event_id"] for row in rows] == ["100", "101", "102", "104", "105"]
    outer = next(g for g in collector.gaps if g.reason == "WS_DISCONNECT")
    assert outer.status == "RECOVERED_COMPLETE"
    assert outer.recovered_events == 4


def test_a_repaired_trade_is_not_a_chain_violation_but_a_regression_is(
    tmp_path: Path,
) -> None:
    """§12 — replay must not call a legitimate repair a broken chain.

    A row restored from the public index is written when the index answers, which
    is *after* the live stream already moved past that id. Judged in write order
    it looks like the chain went backwards; the chain that must be monotone is the
    live one, and a live row that regresses is still corruption.
    """
    from trading_bot.research.forward.contract import BACKFILL_ORIGIN

    collector = _collector(tmp_path / "repaired", run_id="run-repaired")
    _trade(collector, 100, trade_time=1_000)
    _trade(collector, 105, trade_time=1_100)  # ids 101..104 never observed live
    collector._handle_agg_trade(
        Market.SPOT, "BTCUSDT", _agg_row(101, trade_time=1_000), 1_200, 0, origin=BACKFILL_ORIGIN
    )
    collector.finalise()

    verification = replay_microstructure_dataset(collector.root, "run-repaired")
    assert verification.trade_sequence_ok is True
    assert verification.trade_sequence_violations == []
    assert verification.repaired_trade_rows == 1
    assert verification.deterministic is True

    # A live row that goes backwards is still a violation: that is corruption, not
    # a repair, and it must not be excused by the repair tolerance.
    regressed = _collector(tmp_path / "regressed", run_id="run-regressed")
    _trade(regressed, 100, trade_time=1_000)
    _trade(regressed, 99, trade_time=1_100)
    regressed.finalise()

    regressed_verification = replay_microstructure_dataset(regressed.root, "run-regressed")
    assert regressed_verification.trade_sequence_ok is False
    assert regressed_verification.repaired_trade_rows == 0
    assert "not > previous" in regressed_verification.trade_sequence_violations[0]


def test_a_forward_walk_repair_is_not_a_chain_violation(tmp_path: Path) -> None:
    """§4, §12 — a socket outage walks the index *forward*, past the live head.

    Recovery from a disconnect restores the trades the outage swallowed by
    walking ``fromId`` from the last known id up to the head of the public index,
    so the repaired ids are newer than every live id persisted so far. The live
    stream for those ids arrives later and is suppressed by the collector's id
    window, which is exactly the "WS gap → REST recovery → persistence → later WS
    overlap → dedup → one logical event" chain this phase has to show. Judged in
    write order it looks like a chain that ran forward; it must not be reported as
    a violation.
    """
    from trading_bot.research.forward.contract import BACKFILL_ORIGIN

    collector = _collector(tmp_path / "forward-walk", run_id="run-forward-walk")
    _trade(collector, 100, trade_time=1_000)
    _trade(collector, 101, trade_time=1_001)
    for agg_id in (102, 103, 104):
        collector._handle_agg_trade(
            Market.SPOT,
            "BTCUSDT",
            _agg_row(agg_id, trade_time=1_002),
            1_500,
            0,
            origin=BACKFILL_ORIGIN,
        )
    # The live stream then delivers a trade that the repair already accounted for;
    # the id window must swallow it rather than persist a second row.
    _trade(collector, 103, trade_time=1_003, receive_time=1_600)
    collector.finalise()

    verification = replay_microstructure_dataset(collector.root, "run-forward-walk")
    assert verification.repaired_trade_rows == 3
    assert verification.trade_sequence_violation_count == 0
    assert verification.trade_sequence_violations == []
    assert verification.trade_sequence_ok is True
    assert verification.trade_unresolved_holes == 0
    assert verification.trade_hole_tracker_saturated is False
    assert verification.trade_chains["spot/BTCUSDT"]["live_head"] == 101
    assert verification.trade_chains["spot/BTCUSDT"]["resolved_hi"] == 104
    assert verification.deterministic is True

    ids = [row["exchange_event_id"] for row in _trades(collector)]
    assert ids == ["100", "101", "102", "103", "104"], ids


def test_the_trade_chain_flags_a_colliding_repair_and_keeps_holes_visible() -> None:
    """The id-space invariant, exercised where a repair collides with the chain."""
    from trading_bot.research.forward.replay import _TradeChain

    chain = _TradeChain()
    assert chain.on_live(10) is None
    assert chain.on_live(14) is None  # ids 11..13 were never seen live
    assert chain.on_repaired(12) is None  # a repair inside the recorded hole
    assert chain.on_repaired(12) is not None  # the same id twice is a duplicate
    assert chain.on_repaired(15) is None  # a forward walk past the live head
    assert chain.on_live(16) is None  # the live stream catches up
    assert chain.resolved_hi == 16
    # Two ids of the hole were filled and two were not: the remainder stays counted.
    assert chain.holes == [[11, 11], [13, 13]]
    # A live row that regresses is corruption, not a repair.
    assert "not > previous" in str(chain.on_live(15))
    assert chain.live_head == 16

    # An id the live chain never skipped and no repair filled stays an open hole;
    # it is reported, never silently presumed lost.
    sparse = _TradeChain()
    sparse.on_live(1)
    sparse.on_live(5)
    assert sparse.holes == [[2, 4]]


def test_the_quality_report_is_produced_from_one_streaming_pass(tmp_path: Path) -> None:
    from trading_bot.research.forward.reporting import _scan_rows, _stream_rows

    root, run_id = _build_dataset(tmp_path)
    replay = ForwardReplay(root, run_id)
    rows, box = _stream_rows(replay)
    scan = _scan_rows(rows)
    materialised, _ = replay.load_rows()
    assert sum(entry.events for entry in scan.scans.values()) == len(materialised)
    assert set(scan.scans) == {
        f"{row['market']}/{row['symbol']}/{row['event_type']}" for row in materialised
    }
    assert box[0] == 0  # a sealed dataset has no truncated tail
