from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from trading_bot.trade_journal import (
    ChartSnapshot,
    EntryThesis,
    TechnicalZone,
    TradeCase,
    TradeJournalStore,
    TradeOutcome,
)
from trading_bot.trade_journal.store import CURRENT_SCHEMA_VERSION


def _zone() -> TechnicalZone:
    return TechnicalZone(
        zone_id="BTC/USDT:1m:support:1",
        symbol="BTC/USDT",
        timeframe="1m",
        kind="support",
        low=99.0,
        high=100.0,
        strength=0.9,
        detected_at=1_700_000_000_000,
        source="test",
        evidence={"touches": 3.0},
    )


def _thesis() -> EntryThesis:
    return EntryThesis(
        trade_case_id="case-1",
        signal_id="signal-1",
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=101.0,
        tp_price=103.0,
        sl_price=99.0,
        timeframe="1m",
        entry_reason="support reclaim",
        criteria_met=("support_nearby", "trend_aligned"),
        criteria_failed=("near_resistance",),
        indicators={"rsi": 52.0, "vwap_reclaimed": True},
        zones=(_zone(),),
        confidence_score=0.72,
        created_at=1_700_000_000_001,
    )


def test_trade_journal_types_are_frozen() -> None:
    zone = _zone()

    with pytest.raises(dataclasses.FrozenInstanceError):
        zone.strength = 0.1  # type: ignore[misc]


def test_store_creates_schema_and_round_trips_case(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/journal.db"
    case = TradeCase(
        trade_case_id="case-1",
        signal_id="signal-1",
        symbol="BTC/USDT",
        direction="LONG",
        status="pending_order",
        created_at=1_700_000_000_001,
        entry_thesis=_thesis(),
    )

    with TradeJournalStore(url) as store:
        store.create_case(case)
        loaded = store.get_case("case-1")

    assert loaded is not None
    assert loaded.trade_case_id == "case-1"
    assert loaded.entry_thesis is not None
    assert loaded.entry_thesis.criteria_met == ("support_nearby", "trend_aligned")
    assert loaded.entry_thesis.zones[0].kind == "support"

    with sqlite3.connect(tmp_path / "journal.db") as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION


def test_store_updates_snapshot_and_outcome(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/journal.db"
    case = TradeCase(
        trade_case_id="case-1",
        signal_id="signal-1",
        symbol="BTC/USDT",
        direction="SHORT",
        status="pending_order",
        created_at=10,
    )
    snapshot = ChartSnapshot(
        snapshot_id="snap-1",
        trade_case_id="case-1",
        provider="local_renderer",
        path="data/chart_snapshots/case-1.png",
        status="fallback",
        captured_at=11,
        overlays={"entry": 100.0, "tp": 98.0, "sl": 101.0},
    )
    outcome = TradeOutcome(
        trade_case_id="case-1",
        position_id="position-1",
        exit_reason="take_profit",
        pnl_net=2.0,
        r_multiple=1.5,
        mfe=2.2,
        mae=0.4,
        win_loss="win",
        closed_at=20,
        post_trade_diagnosis=("resistance_rejected",),
    )

    with TradeJournalStore(url) as store:
        store.create_case(case)
        store.save_chart_snapshot(snapshot)
        store.save_outcome(outcome)
        loaded = store.get_case("case-1")

    assert loaded is not None
    assert loaded.status == "closed"
    assert loaded.chart_snapshot is not None
    assert loaded.chart_snapshot.provider == "local_renderer"
    assert loaded.outcome is not None
    assert loaded.outcome.post_trade_diagnosis == ("resistance_rejected",)


def test_store_lists_cases_by_symbol_and_status(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/journal.db"
    with TradeJournalStore(url) as store:
        store.create_case(
            TradeCase(
                trade_case_id="case-1",
                signal_id="signal-1",
                symbol="BTC/USDT",
                direction="LONG",
                status="pending_order",
                created_at=1,
            )
        )
        store.create_case(
            TradeCase(
                trade_case_id="case-2",
                signal_id="signal-2",
                symbol="ETH/USDT",
                direction="SHORT",
                status="order_rejected",
                created_at=2,
            )
        )

        cases = store.list_cases(symbol="ETH/USDT", status="order_rejected")

    assert [case.trade_case_id for case in cases] == ["case-2"]


def test_store_rejects_secret_like_payload_keys(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/journal.db"
    bad_thesis = EntryThesis(
        trade_case_id="case-1",
        signal_id="signal-1",
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=101.0,
        tp_price=103.0,
        sl_price=99.0,
        timeframe="1m",
        entry_reason="support reclaim",
        criteria_met=("support_nearby",),
        criteria_failed=(),
        indicators={"api_secret": "must-not-persist"},
        zones=(),
        confidence_score=0.72,
        created_at=1,
    )

    with TradeJournalStore(url) as store:
        store.create_case(
            TradeCase(
                trade_case_id="case-1",
                signal_id="signal-1",
                symbol="BTC/USDT",
                direction="LONG",
                status="pending_order",
                created_at=1,
            )
        )
        with pytest.raises(ValueError, match="secret-like key"):
            store.save_entry_thesis(bad_thesis)

