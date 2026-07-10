from __future__ import annotations

from pathlib import Path

from trading_bot.app import (
    _create_futures_trade_case,
    _mark_trade_case_closed_from_position,
    _reconcile_missing_open_trade_cases,
    _reconcile_open_trade_cases_with_positions,
)
from trading_bot.market_data.bitunix_futures import BitunixFuturesPosition
from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.types import MarketSnapshot
from trading_bot.trade_journal import TradeJournalStore


class FakeMarketClient:
    def fetch_recent_ohlcv(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        return [
            OHLCV(symbol, 1, 100, 103, 99, 102, 100),
            OHLCV(symbol, 2, 102, 105, 101, 104, 110),
            OHLCV(symbol, 3, 104, 106, 95, 96, 120),
            OHLCV(symbol, 4, 96, 99, 94, 98, 130),
            OHLCV(symbol, 5, 98, 103, 97, 102, 140),
            OHLCV(symbol, 6, 102, 104, 100, 101, 150),
            OHLCV(symbol, 7, 101, 103, 100, 102, 160),
        ]


def test_create_futures_trade_case_persists_thesis_and_snapshot(tmp_path: Path) -> None:
    journal_url = f"sqlite:///{tmp_path}/trade_journal.db"
    snapshot_dir = tmp_path / "snapshots"
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        last_price=101,
        volume_24h_usdt=20_000_000,
        spread_bps=2.5,
        atr_pct=0.4,
        volatility_pct=None,
        active=True,
        rejection_reason=None,
        timestamp=10,
        rank_score=0.91,
    )

    trade_case_id, snapshot_path = _create_futures_trade_case(
        snap=snap,
        direction="LONG",
        direction_reason="unit_test_entry",
        qty=0.001,
        tp_price=104,
        sl_price=98,
        market_client=FakeMarketClient(),  # type: ignore[arg-type]
        journal_url=journal_url,
        snapshot_dir=snapshot_dir,
    )

    assert Path(snapshot_path).exists()
    with TradeJournalStore(journal_url) as store:
        case = store.get_case(trade_case_id)

    assert case is not None
    assert case.status == "pending_order"
    assert case.entry_thesis is not None
    assert case.entry_thesis.entry_reason == "unit_test_entry"
    assert case.entry_thesis.indicators["planned_qty"] == 0.001
    assert case.chart_snapshot is not None
    assert case.chart_snapshot.path == snapshot_path


def test_mark_trade_case_closed_from_position_persists_outcome(tmp_path: Path) -> None:
    journal_url = f"sqlite:///{tmp_path}/trade_journal.db"
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        last_price=101,
        volume_24h_usdt=20_000_000,
        spread_bps=2.5,
        atr_pct=0.4,
        volatility_pct=None,
        active=True,
        rejection_reason=None,
        timestamp=10,
        rank_score=0.91,
    )
    trade_case_id, _ = _create_futures_trade_case(
        snap=snap,
        direction="LONG",
        direction_reason="unit_test_entry",
        qty=0.001,
        tp_price=104,
        sl_price=98,
        market_client=FakeMarketClient(),  # type: ignore[arg-type]
        journal_url=journal_url,
        snapshot_dir=tmp_path / "snapshots",
    )
    with TradeJournalStore(journal_url) as store:
        store.update_case_status(
            trade_case_id,
            status="open",
            position_id="pos-1",
            updated_at=20,
        )

    closed_trade_case_id = _mark_trade_case_closed_from_position(
        symbol="BTC/USDT",
        position_id="pos-1",
        side="BUY",
        qty=0.001,
        avg_open_price=101,
        pnl_net=0.5,
        close_reason="signal_direction_flipped",
        journal_url=journal_url,
    )

    with TradeJournalStore(journal_url) as store:
        case = store.get_case(trade_case_id)

    assert closed_trade_case_id == trade_case_id
    assert case is not None
    assert case.status == "closed"
    assert case.outcome is not None
    assert case.outcome.win_loss == "win"
    assert "signal_direction_flipped" in case.outcome.post_trade_diagnosis


def test_reconcile_missing_open_trade_cases_closes_orphan_case(tmp_path: Path) -> None:
    journal_url = f"sqlite:///{tmp_path}/trade_journal.db"
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        last_price=101,
        volume_24h_usdt=20_000_000,
        spread_bps=2.5,
        atr_pct=0.4,
        volatility_pct=None,
        active=True,
        rejection_reason=None,
        timestamp=10,
        rank_score=0.91,
    )
    trade_case_id, _ = _create_futures_trade_case(
        snap=snap,
        direction="LONG",
        direction_reason="unit_test_entry",
        qty=0.001,
        tp_price=104,
        sl_price=98,
        market_client=FakeMarketClient(),  # type: ignore[arg-type]
        journal_url=journal_url,
        snapshot_dir=tmp_path / "snapshots",
    )
    with TradeJournalStore(journal_url) as store:
        store.update_case_status(
            trade_case_id,
            status="open",
            position_id="pos-missing",
            updated_at=20,
        )

    reconciled = _reconcile_missing_open_trade_cases(
        open_symbols=set(),
        journal_url=journal_url,
    )

    with TradeJournalStore(journal_url) as store:
        case = store.get_case(trade_case_id)

    assert reconciled == [trade_case_id]
    assert case is not None
    assert case.status == "closed"
    assert case.outcome is not None
    assert case.outcome.exit_reason == "position_missing_on_reconcile"


def test_reconcile_open_trade_cases_closes_direction_mismatch_and_attaches_position(tmp_path: Path) -> None:
    journal_url = f"sqlite:///{tmp_path}/trade_journal.db"
    snap = MarketSnapshot(
        symbol="BTC/USDT",
        last_price=101,
        volume_24h_usdt=20_000_000,
        spread_bps=2.5,
        atr_pct=0.4,
        volatility_pct=None,
        active=True,
        rejection_reason=None,
        timestamp=10,
        rank_score=0.91,
    )
    long_case_id, _ = _create_futures_trade_case(
        snap=snap,
        direction="LONG",
        direction_reason="old_long",
        qty=0.001,
        tp_price=104,
        sl_price=98,
        market_client=FakeMarketClient(),  # type: ignore[arg-type]
        journal_url=journal_url,
        snapshot_dir=tmp_path / "snapshots",
    )
    short_case_id, _ = _create_futures_trade_case(
        snap=snap,
        direction="SHORT",
        direction_reason="current_short",
        qty=0.001,
        tp_price=98,
        sl_price=104,
        market_client=FakeMarketClient(),  # type: ignore[arg-type]
        journal_url=journal_url,
        snapshot_dir=tmp_path / "snapshots",
    )
    with TradeJournalStore(journal_url) as store:
        store.update_case_status(long_case_id, status="open", updated_at=20)
        store.update_case_status(short_case_id, status="open", updated_at=21)

    reconciled = _reconcile_open_trade_cases_with_positions(
        positions=[
            BitunixFuturesPosition(
                position_id="pos-short",
                symbol="BTCUSDT",
                qty=0.001,
                side="SELL",
                margin_mode="CROSS",
                position_mode="HEDGE",
                leverage=20,
                margin=1.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                avg_open_price=101,
                liquidation_price=999,
            )
        ],
        journal_url=journal_url,
    )

    with TradeJournalStore(journal_url) as store:
        long_case = store.get_case(long_case_id)
        short_case = store.get_case(short_case_id)

    assert reconciled == [long_case_id]
    assert long_case is not None
    assert long_case.status == "closed"
    assert long_case.outcome is not None
    assert long_case.outcome.exit_reason == "position_direction_mismatch_on_reconcile"
    assert short_case is not None
    assert short_case.status == "open"
    assert short_case.position_id == "pos-short"
