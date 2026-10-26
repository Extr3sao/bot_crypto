"""Drilldown + deterministic replay (WP-TDM-04).

Replay must reconstruct a decision **from the persisted trace alone** and must
never consult market data. Both properties are asserted here: the first by
comparing the monitor's replay with the runtime store's own replay, the second
by wiring a candle source that fails loudly if it is ever used.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.unit.monitor import helpers as h
from tests.unit.monitor.test_api import get
from trading_bot.autonomous.contracts import DecisionMode
from trading_bot.autonomous.trace import trace_hash
from trading_bot.monitor.api import MonitorConfig, build_server
from trading_bot.monitor.candles import CandleUnavailable


class ExplodingCandleSource:
    """Any call is a failure: drilldown/replay must not need market data."""

    name = "exploding"
    fixture = False

    def fetch(self, **kwargs: Any) -> list[Any]:
        raise CandleUnavailable("market data must not be touched by replay")


def _run(tmp_path: Path) -> Path:
    return h.write_run(
        tmp_path,
        [
            h.make_trace("dec-1", proposal_payload=h.proposal(gross_bps=-4.56)),
            h.make_trace(
                "dec-2",
                mode=DecisionMode.TRADE_PAPER,
                classification="PAPER_ADMITTED",
                reason="admitted_candidate_with_positive_net_edge",
                no_trade_kind=None,
                proposal_payload=h.proposal(gross_bps=30.0, cost_bps=10.0),
                risk_payload=h.risk("PASS", advisory=False),
                decision_time_ms=h.TS0 + h.BAR_MS,
            ),
        ],
        executions=[],
    )


@contextmanager
def serve(root: Path, **config_kwargs: Any) -> Iterator[str]:
    config = MonitorConfig(
        runs_root=root, candle_source=ExplodingCandleSource(), **config_kwargs
    )
    server, _app = build_server(config, port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_drilldown_matches_the_runtime_replay(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions/dec-1")
    assert status == 200
    from trading_bot.autonomous.trace import DecisionTraceStore

    expected = DecisionTraceStore(run_dir).replay("dec-1").to_dict()
    assert body["trace"]["replay"] == expected


def test_drilldown_replay_does_not_touch_market_data(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        status, body, _ = get(base, "/api/monitor/decisions/dec-2")
    assert status == 200, "a candle outage must not break the drilldown"
    assert body["trace"]["replay"]["ok"] is True
    assert body["trace"]["replay"]["status"] == "PARTIAL"  # no outcome yet


def test_replay_reports_every_invariant_it_checked(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, body, _ = get(base, "/api/monitor/decisions/dec-1")
    names = {check["name"] for check in body["trace"]["replay"]["checks"]}
    assert {
        "pit_ordering",
        "trace_hash",
        "shadow_purity",
        "proposal_round_trip",
        "outcome_after_decision",
    } <= names
    assert all(check["passed"] for check in body["trace"]["replay"]["checks"])


def test_trace_hash_survives_the_projection(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    row = json.loads((run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert trace_hash(row) == row["trace_hash"]
    with serve(tmp_path) as base:
        _, body, _ = get(base, "/api/monitor/decisions/dec-1")
    assert body["trace"]["trace_hash"] == row["trace_hash"]
    assert body["trace"]["trace"]["trace_hash"] == row["trace_hash"]


def test_not_recorded_expands_only_where_the_state_requires_it(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, detail_no_trade, _ = get(base, "/api/monitor/decisions/dec-1")
        _, detail_accepted, _ = get(base, "/api/monitor/decisions/dec-2")
    fields_no_trade = {item["field"] for item in detail_no_trade["not_recorded"]}
    fields_accepted = {item["field"] for item in detail_accepted["not_recorded"]}
    assert "order_submitted" not in fields_no_trade
    assert "order_submitted" in fields_accepted


def test_historical_read_is_byte_stable_across_calls(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        first = get(base, "/api/monitor/decisions/dec-1?")[1]
        second = get(base, "/api/monitor/decisions/dec-1?")[1]
    first.pop("generated_at", None)
    second.pop("generated_at", None)
    assert first == second


def test_replay_clock_truncates_the_stream(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path, replay_as_of_ms=h.TS0) as base:
        _, decisions, _ = get(base, "/api/monitor/decisions")
        _, health, _ = get(base, "/api/monitor/health")
    assert [item["decision_id"] for item in decisions["items"]] == ["dec-1"]
    assert decisions["connection_state"] == "REPLAY"
    assert health["runs"][0]["connection_state"] == "REPLAY"


def test_replay_clock_is_reported_as_an_iso_instant(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path, replay_as_of_ms=h.TS0) as base:
        _, decisions, _ = get(base, "/api/monitor/decisions")
    assert decisions["as_of"] == "2026-10-24T07:15:35.240Z"


@pytest.mark.parametrize("decision_id", ["dec-1", "dec-2"])
def test_every_decision_links_back_to_its_trace(tmp_path: Path, decision_id: str) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, body, _ = get(base, f"/api/monitor/decisions/{decision_id}")
    assert body["trace"]["recorded"] is True
    assert body["trace"]["trace"]["decision_id"] == decision_id
    assert body["trace"]["trace"]["sequence"] >= 1
    assert body["trace"]["chain_ok"] is True


def test_run_trace_lists_the_chain_and_the_digests(tmp_path: Path) -> None:
    _run(tmp_path)
    with serve(tmp_path) as base:
        _, body, _ = get(base, "/api/monitor/runs/run-a/trace")
    assert body["chain"] == {"ok": True, "records": 2, "broken_at": None, "detail": "hash chain intact"}
    assert body["duplicate_decision_ids"] == []
    assert set(body["artifact_digests"]) >= {"traces.jsonl", "RUN_REPORT.json"}
