"""Tests unitarios para ``src/trading_bot/scanner/filters.py``.

Estrategia:
- Tests deterministas sin red: ``FakeMarketDataSource`` satisface
  ``MarketDataSourceProtocol`` con valores canned; cada test fija
  inputs y verifica el ``FilterOutcome`` mapeando exactamente el
  ``RejectionReason`` del ADR-lock catalog.
- Async ejecutado via ``asyncio.run()`` para no introducir
  dependencia ``pytest-asyncio`` (no listado en
  ``[dependency-groups].dev`` de ``pyproject.toml``; podria anadirse
  en PR posterior si conviene).
- Velas OHLCV: usa el dataclass real ``trading_bot.market_data.types.OHLCV``
  para tighter coupling entre test y produccion (cualquier cambio en
  la forma del dataclass se propaga al test inmediatamente, evita
  el riesgo de _FakeOHLCV divergente).

Cobertura esperada per DoD F2: 22 sentinels (Volume 8 + Spread 4 +
Atr 6 + helper privado 4).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.filters import (
    VALID_MODES,
    AtrFilter,
    SpreadFilter,
    VolumeFilter,
    _compute_atr_pct,
)
from trading_bot.scanner.protocols import MarketDataSourceProtocol


# ---------------------------------------------------------------------------
# FakeMarketDataSource: stub sincronico/async que satisface el Protocol.
# Los retornos se manejan como ``Optional[...]`` con un valor por
# defecto para distinguir "no fetcheado" de "fetcheado a un valor negativo".
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeMarketDataSource:
    """Stub que simula ``MarketDataSourceProtocol`` con respuestas canned.

    Si un campo se deja en ``None``, el metodo correspondiente levanta
    ``RuntimeError`` para pinear que el filtro toco la fuente equivocada.
    Pine contract: los filtros solo llaman a UN metodo de la fuente,
    segun su necesidad.

    Implementar los 3 metodos async directamente (no usar MagicMock
    porque mypy strict + Protocol structural requiere firmas declaradas).
    """

    volume: Optional[float] = None
    spread_bps: Optional[float] = None
    candles: Optional[list[OHLCV]] = None

    async def fetch_recent(
        self, symbol: str, limit: int = 100
    ) -> list[OHLCV]:
        if self.candles is None:
            raise RuntimeError(
                "FakeMarketDataSource no configurado con `candles`; "
                "el filtro en test no deberia llamar fetch_recent."
            )
        # Truncar a ``limit`` para emular el comportamiento real.
        return list(self.candles[:limit])

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        if self.volume is None:
            raise RuntimeError(
                "FakeMarketDataSource no configurado con `volume`; "
                "el filtro en test no deberia llamar fetch_24h_volume_usdt."
            )
        return self.volume

    async def fetch_spread_bps(self, symbol: str) -> float:
        if self.spread_bps is None:
            raise RuntimeError(
                "FakeMarketDataSource no configurado con `spread_bps`; "
                "el filtro en test no deberia llamar fetch_spread_bps."
            )
        return self.spread_bps


# ---------------------------------------------------------------------------
# Helpers de fixture.
# ---------------------------------------------------------------------------


def _run(coro: object) -> object:
    """Helper que ejecuta una coroutina con ``asyncio.run``.

    Encapsula la necesidad de ``asyncio.run`` para tests sync que
    invocan funciones async de los filtros. No es pytest-asyncio; es
    deliberado para no extender la dependencia dev de momento.
    """
    return asyncio.run(coro)  # type: ignore[arg-type]


def _constant_candles(
    n: int, *, last_close: float = 100.0, daily_range: float = 1.0
) -> list[OHLCV]:
    """Genera ``n`` velas con poca variacion para ATR bajo."""
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1672531200000 + i * 60_000,
            open=last_close,
            high=last_close + daily_range,
            low=last_close - daily_range,
            close=last_close,
            volume=1000.0,
        )
        for i in range(n)
    ]


def _vol_candles(
    n: int, *, last_close: float = 100.0, swing: float = 10.0
) -> list[OHLCV]:
    """Genera ``n`` velas con swings fuertes para ATR alto."""
    candles: list[OHLCV] = []
    for i in range(n):
        # Alternar close alto/bajo para True Range significativo.
        close = last_close + swing if i % 2 == 0 else last_close - swing
        candles.append(
            OHLCV(
                symbol="BTC/USDT",
                timestamp=1672531200000 + i * 60_000,
                open=close,
                high=close + swing,
                low=close - swing,
                close=close,
                volume=1000.0,
            )
        )
    return candles


# ===========================================================================
# VolumeFilter (D1-A del thinker: mode en constructor; ADR lock reason map).
# ===========================================================================


def test_volume_paper_min_pass_when_volume_above_threshold() -> None:
    """Volume > min_usdt en modo paper -> ``passed=True``, reason=None."""
    f = VolumeFilter(min_usdt=5_000_000, mode="paper")
    source = FakeMarketDataSource(volume=10_000_000)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is True
    assert outcome.reason is None


def test_volume_paper_min_fail_emits_volume_below_threshold() -> None:
    """Volume < min_usdt en modo paper -> motivo catalog exacto."""
    f = VolumeFilter(min_usdt=5_000_000, mode="paper")
    source = FakeMarketDataSource(volume=4_999_999)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "volume_below_threshold"


def test_volume_live_pass_when_volume_above_live_threshold() -> None:
    """Volume > live_min_usdt en modo live -> pass."""
    f = VolumeFilter(min_usdt=5_000_000, mode="live", live_min_usdt=10_000_000)
    source = FakeMarketDataSource(volume=15_000_000)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is True
    assert outcome.reason is None


def test_volume_live_endures_emits_live_specific_reason() -> None:
    """Volume entre min_usdt y live_min_usdt en live -> motivo live (ADR lock).

    Caso del BDD scenario "Modo live endurece filtro volumen a 10M USDT":
    volume=7M, min_usdt=5M (paper bastaria), live_min_usdt=10M, mode=live.
    """
    f = VolumeFilter(min_usdt=5_000_000, mode="live", live_min_usdt=10_000_000)
    source = FakeMarketDataSource(volume=7_000_000)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "volume_below_threshold_for_live_min_10M"


def test_volume_live_falls_back_to_min_when_live_min_unset() -> None:
    """En live sin ``live_min_usdt`` -> usa ``min_usdt`` como fallback."""
    f = VolumeFilter(min_usdt=5_000_000, mode="live", live_min_usdt=None)
    source = FakeMarketDataSource(volume=4_000_000)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "volume_below_threshold"


def test_volume_constructor_validates_arguments() -> None:
    """3 validaciones: min_usdt negativo, live_min_usdt < min_usdt, mode invalido."""
    mins = pytest.raises(ValueError, match=r"min_usdt")
    with mins:
        VolumeFilter(min_usdt=-1, mode="paper")  # type: ignore[arg-type]

    lax_live = pytest.raises(ValueError, match=r"live_min_usdt")
    with lax_live:
        VolumeFilter(min_usdt=10_000_000, mode="live", live_min_usdt=5_000_000)

    bad_mode = pytest.raises(ValueError, match=r"mode invalido")
    with bad_mode:
        VolumeFilter(min_usdt=5_000_000, mode="prod")  # type: ignore[arg-type]


def test_volume_name_is_volume_class_level_attribute() -> None:
    """Sentinel del Protocol estructural: ``name`` atributo de clase."""
    f = VolumeFilter(min_usdt=5_000_000, mode="paper")
    assert f.name == "volume"
    assert type(f).name == "volume"


def test_volume_valid_modes_constant_is_complete() -> None:
    """Pinea que ``VALID_MODES`` contiene los 4 modos del runtime."""
    assert VALID_MODES == frozenset({"research", "backtest", "paper", "live"})


# ===========================================================================
# SpreadFilter (max_bps en bps; spread en bps).
# ===========================================================================


def test_spread_pass_when_spread_below_max_bps() -> None:
    """spread < max_bps -> pass."""
    f = SpreadFilter(max_bps=30.0)
    source = FakeMarketDataSource(spread_bps=12.0)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is True


@pytest.mark.parametrize(
    ("spread_bps", "max_bps"),
    [
        (30.01, 30.0),   # apenas encima -> fail
        (80.0, 30.0),    # ancho, fail representativo BDD
        (200.0, 30.0),   # extremo
    ],
)
def test_spread_fail_emits_spread_above_threshold(spread_bps: float, max_bps: float) -> None:
    """Parametrizado: spread > max_bps -> motivo catalog exacto."""
    f = SpreadFilter(max_bps=max_bps)
    source = FakeMarketDataSource(spread_bps=spread_bps)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "spread_above_threshold"


def test_spread_exact_match_is_pass_not_fail() -> None:
    """Spread == max_bps (en el borde) cuenta como pass (no estricto)."""
    f = SpreadFilter(max_bps=30.0)
    source = FakeMarketDataSource(spread_bps=30.0)
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is True


def test_spread_invalid_max_bps_raises() -> None:
    """max_bps < 0 -> ValueError."""
    with pytest.raises(ValueError, match=r"max_bps"):
        SpreadFilter(max_bps=-1.0)  # type: ignore[arg-type]


# ===========================================================================
# AtrFilter (min_pct, max_pct, min_history).
# ===========================================================================


def test_atr_insufficient_history_emits_canonical_reason() -> None:
    """fetch_recent retorna N < min_history -> motivo ``insufficient_history``."""
    f = AtrFilter(min_pct=0.5, max_pct=5.0, min_history=100)
    source = FakeMarketDataSource(candles=_constant_candles(50))
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "insufficient_history"


def test_atr_out_of_range_low_emits_atr_out_of_range() -> None:
    """ATR calculado < min_pct -> motivo ``atr_out_of_range``."""
    f = AtrFilter(min_pct=10.0, max_pct=20.0, min_history=10)
    source = FakeMarketDataSource(candles=_constant_candles(20))
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "atr_out_of_range"


def test_atr_out_of_range_high_emits_atr_out_of_range() -> None:
    """ATR calculado > max_pct -> motivo ``atr_out_of_range``."""
    f = AtrFilter(min_pct=0.0, max_pct=0.5, min_history=10)
    source = FakeMarketDataSource(candles=_vol_candles(20, swing=50.0))
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is False
    assert outcome.reason == "atr_out_of_range"


def test_atr_pass_when_in_range() -> None:
    """ATR calculado dentro de [min_pct, max_pct] -> pass."""
    f = AtrFilter(min_pct=0.0, max_pct=10.0, min_history=10)
    source = FakeMarketDataSource(candles=_vol_candles(20, swing=2.0))
    outcome = _run(f.apply("BTC/USDT", source))
    assert outcome.passed is True


def test_atr_constructor_validates_arguments() -> None:
    """3 validaciones: bounds negativos, max < min, min_history < 1."""
    with pytest.raises(ValueError, match=r"ATR percent bounds"):
        AtrFilter(min_pct=-1.0, max_pct=5.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"max_pct"):
        AtrFilter(min_pct=10.0, max_pct=5.0)
    with pytest.raises(ValueError, match=r"min_history"):
        AtrFilter(min_pct=0.5, max_pct=5.0, min_history=0)


def test_atr_name_is_atr_class_level_attribute() -> None:
    """Sentinel del Protocol estructural: ``name`` atributo de clase."""
    f = AtrFilter(min_pct=0.5, max_pct=5.0)
    assert f.name == "atr"
    assert type(f).name == "atr"


# ===========================================================================
# Helper privado ``_compute_atr_pct`` (4 sentinels de boundary).
# ===========================================================================


def test_compute_atr_pct_returns_zero_for_empty_or_single_candle() -> None:
    """< 2 velas -> 0.0 (defensivo)."""
    assert _compute_atr_pct([]) == 0.0
    assert _compute_atr_pct([_constant_candles(1)[0]]) == 0.0


def test_compute_atr_pct_returns_zero_for_non_positive_last_close() -> None:
    """last_close <= 0 -> 0.0 (defensivo contra input invalido)."""
    bad = OHLCV(
        symbol="BTC/USDT",
        timestamp=1672531200000,
        open=0.0,
        high=0.0,
        low=0.0,
        close=0.0,
        volume=0.0,
    )
    assert _compute_atr_pct([bad, bad]) == 0.0


def test_compute_atr_pct_matches_close_range_for_constant_candles() -> None:
    """Con velas constantes, ATR% ~= daily_range / last_close * 100."""
    candles = _constant_candles(50, last_close=100.0, daily_range=1.0)
    atr = _compute_atr_pct(candles)
    # daily_range=1 (high es close+1, low es close-1, prev close es close)
    # TR = max(|high-low|=2, |high-prev|=1, |low-prev|=1) = 2
    # ATR = 2 / 100 * 100 = 2.0%
    assert atr == pytest.approx(2.0, rel=1e-6)


def test_compute_atr_pct_grows_with_swing() -> None:
    """Mayor swing -> mayor ATR (no cero, monotono)."""
    low_swing = _vol_candles(20, swing=1.0)
    high_swing = _vol_candles(20, swing=20.0)
    assert _compute_atr_pct(high_swing) > _compute_atr_pct(low_swing)
