"""A universe exclusion is a DECISION, not a data outage (DEF-WP00-01).

The runtime skips ``get_ohlcv`` for an inactive snapshot, so an asset the
universe filters refused reached the decision layer with no bars, the context
build failed, and the refusal was reported as ``CONTEXT_ERROR`` /
``NO_TRADE_DATA``. An asset excluded for insufficient volume is not an
unreadable market: the scanner decided not to offer it, and the record must say
so. These tests fix both directions of the boundary, because making the fix
silently absorb genuine data errors would be worse than the defect:

* ``volume_below_threshold`` (selection)  -> ``NO_TRADE_UNIVERSE``
* ``insufficient_history``  (data)        -> ``NO_TRADE_DATA`` unchanged
* an ACTIVE asset with no history (data)  -> ``NO_TRADE_DATA`` unchanged
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from trading_bot.autonomous.contracts import (
    DecisionMode,
    NoTradeKind,
    RuntimeFailureKind,
)
from trading_bot.autonomous.decision import (
    UNIVERSE_FILTERED,
    UNIVERSE_REJECTION_REASONS,
    classification_for_scanner_rejection,
    no_trade_kind_for,
    unclassified_scanner_rejections,
)

from .helpers import (
    TS0,
    FakeSnapshot,
    bars,
    make_ledger,
    make_runtime,
)

# -- taxonomy level ---------------------------------------------------------


def test_a_universe_exclusion_is_not_a_data_no_trade() -> None:
    assert no_trade_kind_for(UNIVERSE_FILTERED) is NoTradeKind.NO_TRADE_UNIVERSE
    assert NoTradeKind.NO_TRADE_UNIVERSE is not NoTradeKind.NO_TRADE_DATA


def test_the_taxonomy_classifies_the_whole_scanner_catalogue() -> None:
    """A reason added to the scanner must be classified here, not defaulted.

    The scanner publishes ``RejectionReason`` as a closed Literal. If one is
    added without deciding whether it describes a selection or a data shortfall,
    this fails instead of letting the runtime guess on the operator's behalf.
    """
    assert unclassified_scanner_rejections() == frozenset()


@pytest.mark.parametrize(
    "reason",
    [
        "not_whitelisted",
        "volume_below_threshold",
        "volume_below_threshold_for_live_min_10M",
        "spread_above_threshold",
        "atr_out_of_range",
        "price_below_threshold",
    ],
)
def test_selection_reasons_are_universe_decisions(reason: str) -> None:
    assert reason in UNIVERSE_REJECTION_REASONS
    assert classification_for_scanner_rejection(reason) == UNIVERSE_FILTERED


def test_unreadable_history_stays_a_data_no_trade() -> None:
    """The one catalogue reason that IS a data shortfall is not reclassified."""
    assert classification_for_scanner_rejection("insufficient_history") == "NO_MARKET_DATA"
    assert no_trade_kind_for("NO_MARKET_DATA") is NoTradeKind.NO_TRADE_DATA


def test_an_unknown_reason_defaults_to_the_selection_class() -> None:
    """A non-catalogue reason (another adapter) still names what is known."""
    assert classification_for_scanner_rejection("some_future_filter") == UNIVERSE_FILTERED
    assert classification_for_scanner_rejection(None) == UNIVERSE_FILTERED


# -- runtime level ----------------------------------------------------------


def _run(runtime: Any, **kwargs: Any) -> Any:
    return asyncio.run(runtime.run(**kwargs))


def _rows(summary: Any) -> dict[str, Any]:
    return {row.asset: row for row in summary.cycle_reports[0].assets}


def test_an_inactive_asset_is_reported_as_a_universe_no_trade(tmp_path: Path) -> None:
    """SOL-shaped: the snapshot says inactive, and there are no bars for it."""
    runtime, _scanner, broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        history={"BTC/USDT": bars("BTC/USDT", 80)},
        snapshots=[
            FakeSnapshot(symbol="BTC/USDT", timestamp=bars("BTC/USDT", 80)[-1].timestamp + 300_000),
            FakeSnapshot(
                symbol="ETH/USDT",
                active=False,
                rejection_reason="volume_below_threshold",
                last_price=0.0,
                volume_24h_usdt=0.0,
                rank_score=0.0,
                timestamp=TS0,
            ),
        ],
    )
    summary = _run(runtime, cycles=1)
    row = _rows(summary)["ETH"]

    assert row.mode is DecisionMode.NO_TRADE
    assert row.classification == "UNIVERSE_FILTERED"
    assert row.no_trade_kind == NoTradeKind.NO_TRADE_UNIVERSE.value
    # A selection is not an incident: no order, and not a runtime failure.
    assert row.order_created is False
    assert row.failure_kind is None
    assert broker.positions == {}

    totals = summary.totals()
    assert totals["no_trade_NO_TRADE_UNIVERSE"] == 1
    assert totals["no_trade_NO_TRADE_DATA"] == 0
    assert totals["runtime_failures"] == 0
    assert totals["orders_created"] == 0

    trace = next(t for t in runtime.trace_store.read() if t.asset == "ETH")
    assert trace.classification == "UNIVERSE_FILTERED"
    assert trace.no_trade_kind == NoTradeKind.NO_TRADE_UNIVERSE.value
    assert "volume_below_threshold" in trace.reason
    # The scanner's verdict travels with the decision, not just in a log line.
    assert trace.market_context["active"] is False
    assert trace.market_context["rejection_reason"] == "volume_below_threshold"


def test_insufficient_history_is_still_a_data_no_trade(tmp_path: Path) -> None:
    """The negative control: a real data shortfall must not be renamed."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        history={"BTC/USDT": bars("BTC/USDT", 80)},
        snapshots=[
            FakeSnapshot(symbol="BTC/USDT", timestamp=bars("BTC/USDT", 80)[-1].timestamp + 300_000),
            FakeSnapshot(
                symbol="ETH/USDT",
                active=False,
                rejection_reason="insufficient_history",
                timestamp=TS0,
            ),
        ],
    )
    summary = _run(runtime, cycles=1)
    row = _rows(summary)["ETH"]

    assert row.classification == "NO_MARKET_DATA"
    assert row.no_trade_kind == NoTradeKind.NO_TRADE_DATA.value
    assert row.failure_kind is None
    totals = summary.totals()
    assert totals["no_trade_NO_TRADE_DATA"] == 1
    assert totals["no_trade_NO_TRADE_UNIVERSE"] == 0


def test_an_active_asset_with_no_history_is_still_a_data_no_trade(tmp_path: Path) -> None:
    """The second negative control: the fix must not mask a context failure.

    An ACTIVE asset whose provider returns nothing is a genuine unreadable
    market, and it must keep its CONTEXT_ERROR / NO_TRADE_DATA record.
    """
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        history={"BTC/USDT": bars("BTC/USDT", 80)},
        snapshots=[
            FakeSnapshot(symbol="BTC/USDT", timestamp=bars("BTC/USDT", 80)[-1].timestamp + 300_000),
            FakeSnapshot(symbol="ETH/USDT", timestamp=TS0),
        ],
    )
    summary = _run(runtime, cycles=1)
    row = _rows(summary)["ETH"]

    assert row.classification == "CONTEXT_ERROR"
    assert row.no_trade_kind == NoTradeKind.NO_TRADE_DATA.value
    assert row.failure_kind is None  # a data no-decision, not an incident
    assert summary.totals()["no_trade_NO_TRADE_UNIVERSE"] == 0


def test_a_provider_outage_on_an_active_asset_is_still_an_incident(tmp_path: Path) -> None:
    """Fail-closed precedence: the incident is not excused by the new branch."""
    from .helpers import BoomReader

    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        reader=BoomReader(),
    )
    summary = _run(runtime, cycles=1)
    row = summary.cycle_reports[0].assets[0]
    assert row.failure_kind == RuntimeFailureKind.PROVIDER_FAILURE.value
    assert row.no_trade_kind is None
    assert summary.totals()["no_trade_NO_TRADE_UNIVERSE"] == 0


def test_the_universe_branch_never_reaches_a_strategy(tmp_path: Path) -> None:
    """An excluded asset is not evaluated: no context, no router, no calls."""
    runtime, _scanner, _broker = make_runtime(
        run_dir=tmp_path,
        ledger=make_ledger(gross_bps=4.0),
        assets=("BTC", "ETH"),
        history={"BTC/USDT": bars("BTC/USDT", 80)},
        snapshots=[
            FakeSnapshot(symbol="BTC/USDT", timestamp=bars("BTC/USDT", 80)[-1].timestamp + 300_000),
            FakeSnapshot(
                symbol="ETH/USDT",
                active=False,
                rejection_reason="spread_above_threshold",
                timestamp=TS0,
            ),
        ],
    )
    calls: list[str] = []
    original = runtime._registry_obj.build_context

    def spy(asset: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(asset)
        return original(asset, *args, **kwargs)

    runtime._registry_obj.build_context = spy  # type: ignore[method-assign]
    _run(runtime, cycles=1)

    assert calls == ["BTC"], f"an excluded asset was evaluated: {calls}"
    trace = next(t for t in runtime.trace_store.read() if t.asset == "ETH")
    assert trace.asset_context == {}
    assert trace.proposal is None
    assert "spread_above_threshold" in trace.reason
