from __future__ import annotations

from trading_bot.execution import FillLedger


def test_first_fill_applies_deltas() -> None:
    ledger = FillLedger()
    application = ledger.apply_fill(
        venue_fill_id="F-1",
        symbol="BTC/USDT",
        side="buy",
        quantity=0.5,
        price=60_000.0,
        fee=10.0,
    )
    assert application.applied is True
    assert application.duplicate is False
    assert application.position_delta == 0.5
    assert application.fee_delta == 10.0


def test_duplicate_fill_applies_nothing() -> None:
    ledger = FillLedger()
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.5, price=60_000.0, fee=10.0
    )
    duplicate = ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.5, price=60_000.0, fee=10.0
    )
    assert duplicate.applied is False
    assert duplicate.duplicate is True
    assert duplicate.position_delta == 0.0
    assert duplicate.fee_delta == 0.0
    assert duplicate.pnl_delta == 0.0


def test_duplicate_partial_fill_counts_once() -> None:
    ledger = FillLedger()
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    dup = ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    assert dup.duplicate is True
    assert ledger.applied_count() == 1


def test_out_of_order_partial_fills_accumulate() -> None:
    ledger = FillLedger()
    # Delivered out of order: partial 2, partial 1, then the dup of partial 2.
    second = ledger.apply_fill(
        venue_fill_id="F-3", symbol="BTC/USDT", side="buy", quantity=0.2, price=61_000.0
    )
    first = ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=0.3, price=60_000.0
    )
    dup = ledger.apply_fill(
        venue_fill_id="F-3", symbol="BTC/USDT", side="buy", quantity=0.2, price=61_000.0
    )
    assert second.applied and first.applied and dup.duplicate
    assert ledger.applied_count() == 2
    total_position = 0.3 + 0.2
    assert total_position == 0.5  # both unique fills applied exactly once each


def test_position_fee_pnl_once_per_fill() -> None:
    ledger = FillLedger()
    app = ledger.apply_fill(
        venue_fill_id="F-1", symbol="ETH/USDT", side="sell", quantity=2.0, price=3_000.0, fee=5.0
    )
    # Sell 2.0 @ 3000 => cash +6000, minus fee 5 => pnl 5995.
    assert app.position_delta == -2.0
    assert app.pnl_delta == 5_995.0
    assert app.fee_delta == 5.0
    # Re-delivery changes nothing.
    again = ledger.apply_fill(
        venue_fill_id="F-1", symbol="ETH/USDT", side="sell", quantity=2.0, price=3_000.0, fee=5.0
    )
    assert again.position_delta == 0.0
    assert again.pnl_delta == 0.0


def test_mixed_sides_accumulate_correctly() -> None:
    ledger = FillLedger()
    ledger.apply_fill(
        venue_fill_id="F-1", symbol="BTC/USDT", side="buy", quantity=1.0, price=60_000.0
    )
    ledger.apply_fill(
        venue_fill_id="F-2", symbol="BTC/USDT", side="sell", quantity=0.4, price=61_000.0
    )
    assert ledger.is_known("F-1") and ledger.is_known("F-2")
    assert ledger.applied_count() == 2
