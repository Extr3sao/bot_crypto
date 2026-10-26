"""WP-SIGNAL-001 — the signal stream must be a projection, never an invention.

The claims under test are the ones an operator relies on when watching the board:

* every row is grounded in a persisted decision (``evidence_refs`` + trace hash);
* the row says ``None`` rather than ``0`` when the decision carried no edge, and
  the three states a naive feed conflates (no alpha / a decision / an incident)
  stay separate;
* projecting twice — or restarting the process — never duplicates a row, and a
  body that disagrees with an existing id is refused instead of silently chosen;
* data time never postdates the decision, and a SHADOW row is never an order;
* pagination is bounded at the server and stable while rows are being appended.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.signals import (
    MAX_PAGE_LIMIT,
    DataQuality,
    SignalEvent,
    SignalKind,
    SignalLedger,
    SignalLedgerError,
    SignalSource,
    SignalStage,
    project_trace,
    signal_id_for,
)

from .helpers import (
    BoomReader,
    SilentFamily,
    make_admitted_ledger,
    make_ledger,
    make_runtime,
)


def _rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "signals.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run(runtime: Any, cycles: int = 1) -> Any:
    return asyncio.run(runtime.run(cycles=cycles))


def _event(**overrides: Any) -> SignalEvent:
    base: dict[str, Any] = {
        "signal_id": signal_id_for(
            run_id="run-1",
            decision_id="dec-1",
            strategy_id="ema_crossover@5m",
            stage=SignalStage.SHADOW.value,
            bar_close_ms=1_700_000_000_000,
            direction="LONG",
        ),
        "run_id": "run-1",
        "decision_id": "dec-1",
        "symbol": "BTC/USDT",
        "venue": "binance",
        "timeframe": "5m",
        "strategy_id": "ema_crossover@5m",
        "strategy_version": "ema_crossover@5m",
        "bar_close_time_ms": 1_700_000_000_000,
        "decision_time_ms": 1_700_000_001_000,
        "direction": "LONG",
        "stage": SignalStage.SHADOW.value,
        "kind": SignalKind.ALPHA.value,
        "reason": "NOT_ADMITTED",
        "gross_edge_bps": 4.0,
        "estimated_cost_bps": 23.5,
        "net_edge_bps": -19.5,
        "risk_state": "NOT_EVALUATED",
        "data_quality": DataQuality.OK.value,
        "source": SignalSource.REAL.value,
    }
    base.update(overrides)
    return SignalEvent(**base)


# --------------------------------------------------------------------------- #
# contract


def test_signal_contract_rejects_look_ahead() -> None:
    with pytest.raises(ValueError, match="point-in-time"):
        _event(bar_close_time_ms=1_700_000_002_000)


def test_shadow_row_can_never_be_an_order() -> None:
    with pytest.raises(ValueError, match="SHADOW"):
        _event(order_created=True)


def test_paper_row_must_be_an_order() -> None:
    with pytest.raises(ValueError, match="PAPER"):
        _event(stage=SignalStage.PAPER.value, order_created=False)
    ok = _event(stage=SignalStage.PAPER.value, order_created=True)
    assert ok.stage == "PAPER"


def test_edge_numbers_require_a_strategy() -> None:
    with pytest.raises(ValueError, match="strategy_id"):
        _event(strategy_id=None, strategy_version=None)


def test_signal_id_is_deterministic_and_body_sensitive() -> None:
    a = _event()
    b = _event()
    assert a.signal_id == b.signal_id
    assert a.content_hash == b.content_hash
    other = _event(reason="DIFFERENT WORDING")
    # A wording change must not fork the identity, but must change the body hash:
    # that is how the ledger notices a disagreeing re-projection.
    assert other.signal_id == a.signal_id
    assert other.content_hash != a.content_hash


# --------------------------------------------------------------------------- #
# projection


def test_projection_points_back_at_the_persisted_trace(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0), signal_source="FAKE"
    )
    _run(runtime)
    trace = runtime.trace_store.read()[0]
    event = project_trace(trace, venue="binance", timeframe="5m", source=SignalSource.FAKE)

    ref = event.evidence_refs[0]
    assert ref["kind"] == "decision_trace"
    assert ref["file"] == "traces.jsonl"
    assert ref["decision_id"] == trace.decision_id
    assert ref["sequence"] == trace.sequence
    assert ref["trace_hash"] == trace.trace_hash
    assert runtime.trace_store.verify_chain().ok
    assert event.source == "FAKE"
    assert event.decision_time_ms >= (event.bar_close_time_ms or 0)


def test_terminal_decision_reports_no_edge_instead_of_zero(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(),
        families={"trend": SilentFamily("trend")},
        strategy_map={},
    )
    _run(runtime)
    rows = _rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == SignalStage.REJECTED.value
    assert row["kind"] == SignalKind.NO_ALPHA.value
    assert row["gross_edge_bps"] is None
    assert row["estimated_cost_bps"] is None
    assert row["net_edge_bps"] is None
    assert row["strategy_id"] is None
    assert row["candidates"] == []


def test_provider_outage_is_an_incident_not_a_decision(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(), reader=BoomReader()
    )
    _run(runtime)
    row = _rows(tmp_path)[0]
    assert row["stage"] == SignalStage.REJECTED.value
    assert row["kind"] == SignalKind.OPERATIONAL_FAILURE.value
    # The fixture's snapshot is from 2023 while the decision clock is real, so the
    # row honestly reports the data as STALE rather than pretending it was fresh.
    assert row["data_quality"] == DataQuality.STALE.value
    assert row["classification"] == "CONTEXT_ERROR"
    # The trace is the materialised decision: a terminal one carries no proposal,
    # so no edge and no cost, which is exactly what the row says.
    assert row["net_edge_bps"] is None


def test_no_snapshot_at_all_is_reported_as_missing_data(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(), snapshots=[]
    )
    _run(runtime)
    row = _rows(tmp_path)[0]
    assert row["data_quality"] == DataQuality.MISSING.value
    # The runtime classifies "no snapshot" as NO_TRADE_DATA, a decision, not an
    # incident: the projection must not re-label it.
    assert row["kind"] == SignalKind.NO_TRADE.value
    assert row["reason"] == "no_snapshot_for_symbol"


def test_shadow_trade_row_is_never_an_order(tmp_path: Path) -> None:
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0)
    )
    _run(runtime)
    row = _rows(tmp_path)[0]
    assert row["stage"] == SignalStage.SHADOW.value
    assert row["order_created"] is False
    assert row["strategy_id"] == "ema_crossover@5m"
    assert row["gross_edge_bps"] == pytest.approx(4.0)
    assert row["net_edge_bps"] < 0  # the costs are in the row, not hidden
    assert broker.positions == {}


def test_paper_trade_row_is_an_order(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    _run(runtime)
    row = _rows(tmp_path)[0]
    assert row["stage"] == SignalStage.PAPER.value
    assert row["order_created"] is True
    assert row["kind"] == SignalKind.ALPHA.value


def test_runtime_emits_one_row_per_decision_per_cycle(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0)
    )
    summary = _run(runtime, cycles=2)
    traces = runtime.trace_store.read()
    rows = _rows(tmp_path)
    assert len(rows) == len(traces) == 2
    assert summary.cycle_reports[-1].signals["appended"] == 1
    assert len({row["signal_id"] for row in rows}) == 2
    assert all(row["source"] == "REAL" for row in rows)


# --------------------------------------------------------------------------- #
# idempotency


def test_sync_is_idempotent_and_survives_a_restart(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_ledger(gross_bps=4.0)
    )
    _run(runtime)
    traces = runtime.trace_store.read()

    ledger = SignalLedger(tmp_path)
    stats = ledger.sync(traces, venue=runtime.venue, timeframe="5m")
    assert stats["appended"] == 0
    assert stats["skipped_duplicates"] == 1
    assert stats["conflicts"] == 0

    # A new ledger over the same directory is what a restart looks like.
    restarted = SignalLedger(tmp_path)
    assert restarted.known_ids() == ledger.known_ids()
    assert restarted.sync(traces, venue=runtime.venue, timeframe="5m")["appended"] == 0
    assert len(_rows(tmp_path)) == 1


def test_conflicting_body_under_an_existing_id_is_refused(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path)
    assert ledger.append(_event()) is True
    with pytest.raises(SignalLedgerError):
        ledger.append(_event(reason="A DIFFERENT STORY"))
    assert len(_rows(tmp_path)) == 1
    assert ledger.conflicts and ledger.conflicts[0]["signal_id"] == _event().signal_id


# --------------------------------------------------------------------------- #
# pagination and retention


def _seed(ledger: SignalLedger, count: int) -> None:
    for index in range(count):
        ledger.append(
            _event(
                signal_id=signal_id_for(
                    run_id="run-1",
                    decision_id=f"dec-{index}",
                    strategy_id="ema_crossover@5m",
                    stage=SignalStage.SHADOW.value,
                    bar_close_ms=1_700_000_000_000 + index,
                    direction="LONG",
                ),
                decision_id=f"dec-{index}",
                bar_close_time_ms=1_700_000_000_000 + index,
                decision_time_ms=1_700_000_001_000 + index,
            )
        )


def test_page_limit_is_bounded_by_the_server(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path)
    _seed(ledger, 3)
    page = ledger.read(limit=10_000)
    assert page.limit == MAX_PAGE_LIMIT
    assert page.returned == 3
    assert ledger.read(limit=0).limit == 1


def test_cursor_paging_covers_every_row_exactly_once(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path)
    _seed(ledger, 12)
    seen: list[str] = []
    cursor: int | None = None
    for _ in range(10):
        page = ledger.read(limit=5, cursor=cursor)
        seen.extend(event.signal_id for event in page.events)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert len(seen) == 12
    assert len(set(seen)) == 12

    # New rows arriving between pages must not shift the cursor.
    first = ledger.read(limit=5)
    _seed(SignalLedger(tmp_path), 1)
    second = ledger.read(limit=5, cursor=first.next_cursor)
    assert not ({e.signal_id for e in first.events} & {e.signal_id for e in second.events})


def test_filters_select_by_dimension(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path)
    _seed(ledger, 4)
    ledger.append(_event(signal_id="other" + "0" * 27, decision_id="dec-other", symbol="ETH/USDT"))
    assert ledger.read(symbol="btc/usdt").returned == 4
    assert ledger.read(strategy="no_such_strategy").returned == 0
    assert ledger.read(stage="SHADOW").returned == 5
    assert ledger.read(stage="PAPER").returned == 0


def test_retention_rotates_instead_of_growing_forever(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path, retention_records=5, retention_generations=2)
    _seed(ledger, 23)
    generations = ledger.generations()
    assert len(generations) == 2
    assert len(_rows(tmp_path)) == 3  # 23 = 5 + 5 + 3, the third generation dropped
    assert (tmp_path / "signals.1.jsonl").exists()
    # The newest rows are still the ones a reader sees first.
    newest = ledger.read(limit=1).events[0]
    assert newest.decision_id == "dec-22"


def test_verifier_flags_a_malformed_line(tmp_path: Path) -> None:
    ledger = SignalLedger(tmp_path)
    _seed(ledger, 2)
    with open(tmp_path / "signals.jsonl", "a", encoding="utf-8") as handle:
        handle.write("NOT JSON\n")
    report = ledger.verify()
    assert report["malformed"] == 1
    assert report["ok"] is False


def test_verifier_accepts_a_real_run(tmp_path: Path) -> None:
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path, ledger=make_admitted_ledger(gross_bps=50.0)
    )
    _run(runtime)
    report = runtime.signal_ledger.verify()
    assert report["ok"] is True, report
    assert report["records"] == 1
    assert report["shadow_orders"] == 0
    assert report["pit_violations"] == []
