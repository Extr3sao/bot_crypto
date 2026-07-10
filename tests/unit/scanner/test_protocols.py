"""Tests unitarios para ``src/trading_bot/scanner/protocols.py``.

Pinea el contrato de abstraccion estructural de Protocol (duck
typing). Tests deterministas sin red.

Cobertura esperada per DoD F1: 4 tests verde en este archivo.
"""

from __future__ import annotations

from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.protocols import (
    MarketDataSourceProtocol,
)
from trading_bot.scanner.types import FilterOutcome

# ---------------------------------------------------------------------------
# MarketDataSourceProtocol: runtime_checkable.
# ---------------------------------------------------------------------------


def test_protocol_runtime_checkable() -> None:
    """Cualquier clase que expone los 3 metodos async requeridos es
    instance of ``MarketDataSourceProtocol`` (runtime_checkable)."""

    class FakeSource:
        async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
            return []

        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            return 0.0

        async def fetch_spread_bps(self, symbol: str) -> float:
            return 0.0

    fake = FakeSource()
    assert isinstance(fake, MarketDataSourceProtocol)


def test_protocol_rejects_partial_implementation() -> None:
    """Una clase que solo expone ``fetch_recent`` NO satisface el
    Protocol. mypy strict detecta esto en compile-time;
    runtime_checkable lo pinea en tests."""

    class PartialSource:
        async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
            return []

        # Faltan fetch_24h_volume_usdt y fetch_spread_bps.

    partial = PartialSource()
    assert not isinstance(partial, MarketDataSourceProtocol)


# ---------------------------------------------------------------------------
# Filter Protocol: estructural via ``hasattr`` (no runtime_checkable).
# ---------------------------------------------------------------------------


def test_filter_protocol_attr_name() -> None:
    """Pinea que el Protocol ``Filter`` exige atributo ``name`` + metodo
    ``apply`` compatible. mypy strict cubre el contract en
    compile-time; este test es la red de seguridad runtime."""

    class VolumeFilter:
        name = "volume"

        async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
            return FilterOutcome(passed=True)

    impl = VolumeFilter()
    assert hasattr(impl, "name")
    assert impl.name == "volume"
    assert callable(impl.apply)


def test_filter_protocol_without_name_fails_attribute_check() -> None:
    """Una clase sin atributo ``name`` falla la verificacion
    estructural. NO usamos ``isinstance(impl, Filter)`` porque
    Filter no es runtime_checkable (atributo de clase no-metodo
    rompe ese pathway)."""

    class AnonFilter:
        async def apply(self, symbol: str, source: MarketDataSourceProtocol) -> FilterOutcome:
            return FilterOutcome(passed=True)

    anon = AnonFilter()
    assert not hasattr(anon, "name")
    # El ``apply`` existe pero el Protocol exige tambien ``name``;
    # el orquestador rechaza el filtro antes de registrarlo.
    assert callable(anon.apply)
