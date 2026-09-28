"""Collector ingest, replay and runtime-isolation tests (§30, §31, §54).

These tests never open a socket. The collector's ingest path is driven directly
through ``handle_message`` and ``install_snapshot`` so hostile inputs — duplicate
ids, id jumps, future timestamps, malformed payloads — can be asserted
deterministically instead of waiting for a venue to misbehave on its own.
"""

from __future__ import annotations

import ast
import asyncio
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
    assert report["readiness"]["M-03"]["available"]["healthy_books"]
    assert report["readiness"]["M-07"]["verdict"] == "NOT_READY"
    assert _contains_no_profitability_vocabulary(report)


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
