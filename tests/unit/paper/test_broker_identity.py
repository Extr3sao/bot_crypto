"""WP-EDGE-015/P0.3-P0.4 — the broker's own behaviour, not its reports.

The defect this file pins down was found in WP-EDGE-14R: an opening was
identified from *outside* the broker by ``(symbol, opened_at, entry_price)``, and
because ``opened_at`` is a wall-clock instant, two fills of the same symbol that
landed inside one clock tick could share it. The identifier was then a
collision, and a reconciler that deduped on it silently dropped real positions.

The broker now mints ``position_id`` / ``entry_order_id`` / ``exit_order_id`` /
``trade_id`` itself. These tests exercise the broker directly — open, close,
restore, mark — rather than reading a report about it, so a regression fails
here instead of in a downstream artefact.
"""

from __future__ import annotations

import time

import pytest

from trading_bot.paper.broker import PaperBroker, PaperPosition
from trading_bot.strategies.types import Signal


def _buy(symbol: str = "BTC/USDT", price: float = 100.0, notional: float = 1_000.0) -> Signal:
    return Signal(
        symbol=symbol,
        side="buy",
        strategy_name="identity_test",
        timeframe="1h",
        confidence=0.9,
        price=price,
        metadata={"notional_usdt": notional},
    )


def test_two_fills_in_the_same_clock_tick_cannot_share_an_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 14R collision, reproduced and closed.

    ``time.time`` is frozen, so both openings carry an identical ``opened_at``
    *and* an identical entry price: exactly the pair the old external identity
    used. The broker's own identifiers must still differ.
    """
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    broker = PaperBroker(equity=10_000.0, slippage_bps=0.0, book_id="TESTBOOK")
    broker.execute_signal(_buy(price=100.0))
    first = broker.positions["BTC/USDT"]
    broker.check_positions({"BTC/USDT": 105.0})  # take profit-ish close
    broker.execute_signal(_buy(price=100.0))
    second = broker.positions["BTC/USDT"]

    assert first.opened_at == second.opened_at  # the collision is real
    assert first.entry_price == second.entry_price
    assert first.position_id != second.position_id
    assert first.entry_order_id != second.entry_order_id
    assert first.position_id.startswith("pos-TESTBOOK-")
    assert first.entry_order_id.startswith("ord-TESTBOOK-")


def test_a_close_names_the_position_and_the_orders_it_settled() -> None:
    broker = PaperBroker(equity=10_000.0, book_id="TESTBOOK")
    position = broker.execute_signal(_buy())
    assert isinstance(position, PaperPosition)
    closed = broker.check_positions({"BTC/USDT": 90.0})  # SL is 1% below a 100 entry
    assert len(closed) == 1
    trade = closed[0]

    assert trade.position_id == position.position_id
    assert trade.entry_order_id == position.entry_order_id
    assert trade.exit_order_id
    assert trade.trade_id.startswith("trd-TESTBOOK-")
    # Identity here means traceability: the close names the opening it settled.
    assert trade.position_id.startswith("pos-TESTBOOK-")
    assert trade.entry_order_id.startswith("ord-TESTBOOK-")
    # And no two *events* of one book share an identifier.
    minted = {
        "position": position.position_id,
        "entry_order": position.entry_order_id,
        "trade": trade.trade_id,
        "exit_order": trade.exit_order_id,
    }
    assert len(set(minted.values())) == len(minted)


def test_the_reported_net_pnl_is_rebuildable_from_its_legs() -> None:
    broker = PaperBroker(equity=10_000.0, slippage_bps=1.0, commission_bps=5.0, book_id="TESTBOOK")
    broker.execute_signal(_buy(price=100.0, notional=1_000.0))
    trade = broker.check_positions({"BTC/USDT": 90.0})[0]
    assert trade.gross_pnl != 0.0
    assert trade.entry_commission > 0.0
    assert trade.exit_commission > 0.0
    assert trade.pnl == pytest.approx(
        trade.gross_pnl - trade.entry_commission - trade.exit_commission, abs=1e-12
    )


def test_realised_unrealised_cash_and_equity_stay_apart_with_a_position_open() -> None:
    """The four quantities the brief asks to be distinguished, with an open book."""
    broker = PaperBroker(equity=10_000.0, slippage_bps=0.0, commission_bps=10.0, book_id="TESTBOOK")
    broker.execute_signal(_buy(price=100.0, notional=1_000.0))
    snapshot = broker.accounting_snapshot({"BTC/USDT": 110.0})

    assert snapshot["realised_pnl"] == 0.0  # nothing has closed
    assert snapshot["cash"] == pytest.approx(10_000.0)
    assert snapshot["unrealised_pnl"] == pytest.approx(100.0)  # 10% on 1 000
    assert snapshot["accrued_entry_commissions"] == pytest.approx(1.0)  # 10 bps of 1 000
    assert snapshot["unrealised_pnl_net"] == pytest.approx(99.0)
    assert snapshot["equity_mark_to_market"] == pytest.approx(10_099.0)
    # The legacy single number omitted the commission still owed on entry.
    assert broker.mark_to_market_equity({"BTC/USDT": 110.0}) == pytest.approx(10_099.0)
    assert all(snapshot["identities"].values()), snapshot["identities"]
    assert snapshot["open_positions"][0]["position_id"] == broker.positions["BTC/USDT"].position_id

    # Close it: the same money moves from unrealised into realised, minus the
    # exit commission, and every identity still closes.
    broker.check_positions({"BTC/USDT": 110.0})  # take profit at +10%
    after = broker.accounting_snapshot({"BTC/USDT": 110.0})
    assert after["open_positions"] == []
    assert after["unrealised_pnl"] == 0.0
    assert after["accrued_entry_commissions"] == 0.0
    assert after["realised_pnl"] == pytest.approx(99.0 - 1.0)  # net of the exit leg too
    assert after["cash"] == pytest.approx(10_000.0 + 98.0)
    assert after["equity_mark_to_market"] == pytest.approx(after["cash"])
    assert all(after["identities"].values()), after["identities"]


def test_restore_continues_the_identifier_sequence() -> None:
    """A recovered book must never mint an identifier it already used."""
    first = PaperBroker(equity=10_000.0, book_id="TESTBOOK")
    first.execute_signal(_buy())
    first.check_positions({"BTC/USDT": 90.0})
    rows = first.closed_trades_rows()
    ids_before = {rows[0]["trade_id"], rows[0]["exit_order_id"], rows[0]["entry_order_id"]}

    recovered = PaperBroker(equity=first.equity, book_id="TESTBOOK")
    recovered.restore(
        equity=first.equity,
        initial_equity=10_000.0,
        fills_opened=1,
        fills_closed=1,
        open_positions=[],
        closed_trades=rows,
    )
    recovered.execute_signal(_buy(price=100.0))
    recovered.check_positions({"BTC/USDT": 90.0})
    ids_after = set()
    for row in recovered.closed_trades_rows()[1:]:
        ids_after |= {
            row["trade_id"],
            row["position_id"],
            row["entry_order_id"],
            row["exit_order_id"],
        }
    assert ids_after
    assert not (ids_before & ids_after), (
        f"identifier reused after restore: {ids_before & ids_after}"
    )
    assert recovered.accounting_snapshot()["identities"]["cash_equals_initial_plus_realised"]


def test_a_row_written_before_identity_existed_still_restores() -> None:
    """Backward compatibility: older persisted books have no ids, and they load."""
    broker = PaperBroker(equity=10_000.0, book_id="TESTBOOK")
    legacy_row = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "entry_price": 100.0,
        "exit_price": 101.0,
        "quantity": 10.0,
        "pnl": 9.98,
        "exit_reason": "take_profit",
        "opened_at": 1.0,
        "closed_at": 2.0,
        "strategy_name": "legacy",
        "a_field_from_the_future": "ignored",
    }
    broker.restore(
        equity=10_009.98,
        initial_equity=10_000.0,
        fills_opened=1,
        fills_closed=1,
        open_positions=[],
        closed_trades=[legacy_row],
    )
    restored = broker.closed_trades[0]
    assert restored.pnl == pytest.approx(9.98)
    assert restored.trade_id == ""  # never had one; not invented
    # And the book keeps working.
    broker.execute_signal(_buy(price=200.0))
    assert broker.positions["BTC/USDT"].position_id
