"""Unit tests for ``src/trading_bot/market_data/fake.py``.

Closes the 88% coverage gap on the module by exercising the public
helpers (``FakeMarketDataSource``, ``make_flat_ohlcv``,
``make_high_volatility_ohlcv``, ``build_demo_settings``,
``build_demo_fetcher``, ``assert_called_once_per_symbol``) across
all their branches.

Why a dedicated file (vs. extending the existing
``tests/unit/market_data/test_ccxt_connector.py``):
- ``fake.py`` is the production home of the demo data source, used by
  ``app.py scan --demo`` and (via re-export) by
  ``tests/unit/scanner/conftest.py`` + ``tests/bdd/conftest.py``.
- It has its own public surface (5 functions + 1 class + 1 helper)
  distinct from the CCXT connector's; lumping them would obscure
  intent and inflate the CCXT test file beyond the 90% coverage gate.
- Per ADR-0011: tests mirror ``src/`` layout. ``fake.py`` lives in
  ``market_data/`` so its test lives in
  ``tests/unit/market_data/test_fake.py``.
"""

from __future__ import annotations

import pytest

from trading_bot.market_data.fake import (
    FakeMarketDataSource,
    assert_called_once_per_symbol,
    build_demo_fetcher,
    build_demo_settings,
    make_flat_ohlcv,
    make_high_volatility_ohlcv,
)
from trading_bot.market_data.types import OHLCV


# ===========================================================================
# make_flat_ohlcv
# ===========================================================================


def test_make_flat_ohlcv_returns_correct_count() -> None:
    """make_flat_ohlcv returns exactly ``n`` velas."""
    rows = make_flat_ohlcv("BTC/USDT", 50, last_close=100.0)
    assert len(rows) == 50


def test_make_flat_ohlcv_high_low_range_is_one() -> None:
    """Pine contract: high - low = 1 (daily range = 1 unit)."""
    rows = make_flat_ohlcv("BTC/USDT", 10, last_close=100.0)
    for row in rows:
        assert row.high - row.low == 1.0
        assert row.open == 100.0
        assert row.close == 100.0


def test_make_flat_ohlcv_uses_symbol_for_every_row() -> None:
    """Cada vela lleva el ``symbol`` inyectado (P1 round-2: PK compuesta)."""
    rows = make_flat_ohlcv("ETH/USDT", 5, last_close=200.0)
    for row in rows:
        assert row.symbol == "ETH/USDT"


def test_make_flat_ohlcv_timestamps_monotonic() -> None:
    """Los timestamps crecen 1 minuto entre velas consecutivas."""
    rows = make_flat_ohlcv("BTC/USDT", 5, last_close=100.0)
    for prev, curr in zip(rows, rows[1:]):
        assert curr.timestamp - prev.timestamp == 60_000


def test_make_flat_ohlcv_returns_ohlcv_instances() -> None:
    """Todas las velas son instancias de ``OHLCV`` (dataclass frozen)."""
    rows = make_flat_ohlcv("BTC/USDT", 3, last_close=100.0)
    assert all(isinstance(r, OHLCV) for r in rows)


# ===========================================================================
# make_high_volatility_ohlcv (R5-LATENT test idiom).
# ===========================================================================


def test_make_high_volatility_ohlcv_returns_correct_count() -> None:
    """make_high_volatility_ohlcv returns exactly ``n`` velas."""
    rows = make_high_volatility_ohlcv(
        "BTC/USDT", 100, close=100.0, daily_pct=0.12
    )
    assert len(rows) == 100


def test_make_high_volatility_ohlcv_daily_range_matches_pct() -> None:
    """Pine contract: high - low = daily_pct * close (12% diario)."""
    close = 100.0
    daily_pct = 0.12
    rows = make_high_volatility_ohlcv(
        "BTC/USDT", 50, close=close, daily_pct=daily_pct
    )
    expected_range = close * daily_pct  # 12.0
    for row in rows:
        assert row.high - row.low == expected_range


def test_make_high_volatility_ohlcv_uses_symbol_for_every_row() -> None:
    """Cada vela lleva el ``symbol`` inyectado (PK compuesta persistence)."""
    rows = make_high_volatility_ohlcv(
        "SOL/USDT", 5, close=50.0, daily_pct=0.08
    )
    for row in rows:
        assert row.symbol == "SOL/USDT"


def test_make_high_volatility_ohlcv_close_equals_input() -> None:
    """Cada vela tiene ``open=high=low=close=close`` (vela con todo al close)."""
    rows = make_high_volatility_ohlcv(
        "BTC/USDT", 10, close=200.0, daily_pct=0.10
    )
    for row in rows:
        assert row.close == 200.0
        # half = 200 * 0.10 / 2 = 10 -> high=210, low=190
        assert row.high == 210.0
        assert row.low == 190.0


def test_make_high_volatility_ohlcv_small_daily_pct() -> None:
    """daily_pct muy chico (0.5%) produce velas casi planas."""
    rows = make_high_volatility_ohlcv(
        "BTC/USDT", 5, close=1000.0, daily_pct=0.005
    )
    for row in rows:
        assert row.high - row.low == 5.0  # 0.5% of 1000


# ===========================================================================
# build_demo_settings
# ===========================================================================


def test_build_demo_settings_default_pairs() -> None:
    """Default 5 pares USDT (BTC/ETH/SOL/AVAX/MATIC) en paper mode."""
    settings = build_demo_settings()
    symbols = [p.symbol for p in settings.universe.pairs]
    assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "MATIC/USDT"]
    assert settings.runtime.mode.value == "paper"
    assert all(p.enabled for p in settings.universe.pairs)


def test_build_demo_settings_custom_pairs() -> None:
    """El caller puede override los pares via el kwarg ``pairs``."""
    settings = build_demo_settings(
        pairs=[("DOGE/USDT", True), ("XRP/USDT", False)],
        kill_switch_enabled=False,
    )
    symbols = [p.symbol for p in settings.universe.pairs]
    assert symbols == ["DOGE/USDT", "XRP/USDT"]
    enabled = [p.enabled for p in settings.universe.pairs]
    assert enabled == [True, False]
    # kill_switch propagado al risk block.
    assert settings.risk.kill_switch_enabled is False


def test_build_demo_settings_custom_filters_propagate() -> None:
    """Los filtros custom (volume/spread/atr) se inyectan en universe.filters."""
    settings = build_demo_settings(
        min_volume_usdt=10_000_000,
        max_spread_bps=20,
        min_atr_percent=0.10,
        max_atr_percent=5.0,
    )
    assert settings.universe.filters.min_24h_volume_usdt == 10_000_000
    assert settings.universe.filters.max_spread_bps == 20
    assert settings.universe.filters.min_atr_percent == 0.10
    assert settings.universe.filters.max_atr_percent == 5.0


def test_build_demo_settings_other_modes() -> None:
    """``mode`` parameter acepta research/backtest/paper (no live por design)."""
    for mode in ("research", "backtest", "paper"):
        settings = build_demo_settings(mode=mode)
        assert settings.runtime.mode.value == mode


# ===========================================================================
# build_demo_fetcher (5 default branches + else + disabled-skip)
# ===========================================================================


def test_build_demo_fetcher_seeds_btc_with_high_volume() -> None:
    """BTC/USDT pre-poblado: 50M volume, 5 bps spread, 100 OHLCV flat."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert source.volume_by_symbol["BTC/USDT"] == 50_000_000.0
    assert source.spread_by_symbol["BTC/USDT"] == 5.0
    assert len(source.ohlcv_by_symbol["BTC/USDT"]) == 100


def test_build_demo_fetcher_seeds_eth() -> None:
    """ETH/USDT pre-poblado: 30M volume, 8 bps spread, 100 OHLCV."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert source.volume_by_symbol["ETH/USDT"] == 30_000_000.0
    assert source.spread_by_symbol["ETH/USDT"] == 8.0
    assert len(source.ohlcv_by_symbol["ETH/USDT"]) == 100


def test_build_demo_fetcher_seeds_sol() -> None:
    """SOL/USDT pre-poblado: 8M volume (pasa paper 5M threshold), 12 bps spread."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert source.volume_by_symbol["SOL/USDT"] == 8_000_000.0
    assert source.spread_by_symbol["SOL/USDT"] == 12.0
    assert len(source.ohlcv_by_symbol["SOL/USDT"]) == 100


def test_build_demo_fetcher_seeds_avax_low_volume() -> None:
    """AVAX/USDT: 1M volume (rechaza VolumeFilter de 5M default)."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert source.volume_by_symbol["AVAX/USDT"] == 1_000_000.0
    # Spread dentro del threshold (no spread-reject, solo volume-reject).
    assert source.spread_by_symbol["AVAX/USDT"] == 5.0


def test_build_demo_fetcher_seeds_matic_high_spread() -> None:
    """MATIC/USDT: 50 bps spread (rechaza SpreadFilter de 30 default)."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert source.spread_by_symbol["MATIC/USDT"] == 50.0
    # Volume dentro del threshold (no volume-reject, solo spread-reject).
    assert source.volume_by_symbol["MATIC/USDT"] == 20_000_000.0


def test_build_demo_fetcher_unknown_symbol_uses_default() -> None:
    """Un par no listado en la whitelist del demo usa el fallback del else branch.

    Cubre la rama ``else`` de ``build_demo_fetcher`` (cubre line ~ del
    match para symbols fuera de los 5 hardcodeados: 10M volume, 10 bps,
    100 velas).
    """
    settings = build_demo_settings(
        pairs=[("DOGE/USDT", True)],
        kill_switch_enabled=False,
    )
    source = build_demo_fetcher(settings)
    assert source.volume_by_symbol["DOGE/USDT"] == 10_000_000.0
    assert source.spread_by_symbol["DOGE/USDT"] == 10.0
    assert len(source.ohlcv_by_symbol["DOGE/USDT"]) == 100


def test_build_demo_fetcher_skips_disabled_pairs() -> None:
    """Pares con ``enabled=False`` no se pre-pueblan (cubre el branch ``continue``)."""
    settings = build_demo_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", False)],
        kill_switch_enabled=False,
    )
    source = build_demo_fetcher(settings)
    assert "BTC/USDT" in source.volume_by_symbol
    assert "ETH/USDT" not in source.volume_by_symbol
    assert "ETH/USDT" not in source.spread_by_symbol
    assert "ETH/USDT" not in source.ohlcv_by_symbol


def test_build_demo_fetcher_returns_fake_market_data_source_instance() -> None:
    """El tipo de retorno es ``FakeMarketDataSource`` (no Protocol)."""
    settings = build_demo_settings()
    source = build_demo_fetcher(settings)
    assert isinstance(source, FakeMarketDataSource)


# ===========================================================================
# FakeMarketDataSource._touch + call_counts behavior
# ===========================================================================


def test_fake_market_data_source_touch_increments_counter() -> None:
    """``_touch`` incrementa el counter ``(method, symbol)`` en 1 cada call."""
    import asyncio

    source = FakeMarketDataSource(
        ohlcv_by_symbol={"BTC/USDT": make_flat_ohlcv("BTC/USDT", 5, last_close=100.0)}
    )
    assert ("fetch_recent", "BTC/USDT") not in source.call_counts
    asyncio.run(source.fetch_recent("BTC/USDT", 5))
    assert source.call_counts[("fetch_recent", "BTC/USDT")] == 1
    asyncio.run(source.fetch_recent("BTC/USDT", 5))
    assert source.call_counts[("fetch_recent", "BTC/USDT")] == 2


def test_fake_market_data_source_missing_symbol_returns_default() -> None:
    """Symbol no presente en los by_symbol -> defaults (volume=0.0, spread=0.0, ohlcv=[])."""
    import asyncio

    source = FakeMarketDataSource()
    assert asyncio.run(source.fetch_24h_volume_usdt("UNKNOWN/USDT")) == 0.0
    assert asyncio.run(source.fetch_spread_bps("UNKNOWN/USDT")) == 0.0
    assert asyncio.run(source.fetch_recent("UNKNOWN/USDT", 10)) == []


def test_fake_market_data_source_fetch_recent_respects_limit() -> None:
    """``fetch_recent(symbol, limit)`` retorna maximo ``limit`` velas."""
    import asyncio

    ohlcv = make_flat_ohlcv("BTC/USDT", 100, last_close=100.0)
    source = FakeMarketDataSource(ohlcv_by_symbol={"BTC/USDT": ohlcv})

    rows_10 = asyncio.run(source.fetch_recent("BTC/USDT", 10))
    assert len(rows_10) == 10

    rows_500 = asyncio.run(source.fetch_recent("BTC/USDT", 500))
    assert len(rows_500) == 100  # capped at available ohlcv


# ===========================================================================
# assert_called_once_per_symbol
# ===========================================================================


def test_assert_called_once_per_symbol_passes_when_exactly_one_call() -> None:
    """No-op cuando ``call_counts[(method, symbol)] == 1``."""
    import asyncio

    source = FakeMarketDataSource(
        ohlcv_by_symbol={"BTC/USDT": make_flat_ohlcv("BTC/USDT", 5, last_close=100.0)}
    )
    asyncio.run(source.fetch_recent("BTC/USDT", 5))
    # Should not raise.
    assert_called_once_per_symbol(source, "fetch_recent", "BTC/USDT")


def test_assert_called_once_per_symbol_fails_when_zero_calls() -> None:
    """``AssertionError`` descriptivo cuando NO se llamo al metodo."""
    source = FakeMarketDataSource()
    with pytest.raises(AssertionError, match="Esperaba 1 call a fetch_spread_bps"):
        assert_called_once_per_symbol(source, "fetch_spread_bps", "BTC/USDT")


def test_assert_called_once_per_symbol_fails_when_two_calls() -> None:
    """``AssertionError`` descriptivo cuando se llamo 2 veces (gotcha #1 dedup roto)."""
    import asyncio

    source = FakeMarketDataSource(
        ohlcv_by_symbol={"BTC/USDT": make_flat_ohlcv("BTC/USDT", 5, last_close=100.0)}
    )
    asyncio.run(source.fetch_recent("BTC/USDT", 5))
    asyncio.run(source.fetch_recent("BTC/USDT", 5))
    with pytest.raises(AssertionError, match="got 2"):
        assert_called_once_per_symbol(source, "fetch_recent", "BTC/USDT")
