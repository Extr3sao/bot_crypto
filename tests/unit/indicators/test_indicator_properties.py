"""Property-based tests for the indicator engine (TSK-204).

Estrategia:

- Hypothesis property tests sobre series sinteticas generadas con
  ``st.floats`` (closes positivos, volumenes positivos). Cobertura
  pineada por sprint-003 (Foundations table nota: "Hypothesis property
  tests sobre series sinteticas; mirror de F3 pattern").
- Patron F3 mirror: ``@settings(max_examples=1000, deadline=None)``
  replica la pine contract de ``scoring.py`` (TSK-103.3.2). Esto
  garantiza que la calidad de los property tests sea homogenea entre
  scoring e indicators; cualquier regresion del F3 contract es visible
  via code review.
- Invariantes cubiertos:
    * No-negatividad (ATR, VWAP, spread, volatility, volume_relative).
    * Acotacion por ventana de input (EMA bounded por window,
      Bollinger ordenado, OBI en [-1, 1], VWAP bounded por typical).
    * Identidad algebraica (MACD histogram == macd - signal,
      Spread formula directa contra spec).
    * Determinismo bit-exact (mismos inputs -> mismo output).
    * Signo consistente con la direccion del precio (momentum, OBI).
- Helpers:
    * ``_candles_from_closes`` para tests que solo dependen de
      ``close`` (EMA, RSI, Bollinger, volatility, momentum, MACD).
    * ``ohlcv_with_ranges`` (composite strategy) para tests que
      necesitan True Range o typical_price variados (ATR, VWAP).
      high/low/close/volume se generan independientemente para que
      las invariantes no sean triviales (evita TR lockeado a 2.0
      o typical == close).

Cobertura esperada per DoD TSK-204: property tests sobre las 11
indicators built-in (TSK-201/202/203). Pine contract: el modulo NO
importa ``market_data.*`` directo, ``scoring.*``, etc. (cross-layer
enforcement via AST en ``test_cross_layer.py``; ya pineado para
``storage.*`` en TSK-103.4.9).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.indicators import (
    AtrIndicator,
    BollingerBandsIndicator,
    EmaIndicator,
    MacdIndicator,
    MomentumIndicator,
    OrderBookImbalanceIndicator,
    RsiIndicator,
    SpreadIndicator,
    VolatilityIndicator,
    VolumeRelativeIndicator,
    VwapIndicator,
)
from trading_bot.market_data.types import OHLCV


def _candles_from_closes(closes: list[float]) -> list[OHLCV]:
    """Genera OHLCV sinteticos con high/low lockeados a close ± 1.

    Pine contract: suficiente para tests que solo consumen ``close``
    (EMA, RSI, Bollinger, volatility, momentum, MACD). No usar para
    tests de ATR/VWAP/OBI que dependen de high/low/volume.
    """
    return [
        OHLCV(
            symbol="BTC/USDT",
            timestamp=1_700_000_000_000 + index * 60_000,
            open=close,
            high=close + 1.0,
            low=max(close - 1.0, 0.0001),
            close=close,
            volume=100.0 + index,
        )
        for index, close in enumerate(closes)
    ]


@st.composite
def ohlcv_with_ranges(draw: st.DrawFn, min_size: int = 6, max_size: int = 40) -> list[OHLCV]:
    """Genera OHLCV con high/low/close/volume independientes.

    Pine contract:
    - ``close >= 1.0`` (evita 0/0 en momentum o volume_relative).
    - ``high >= close``, ``low <= close`` con offsets no-negativos.
    - ``high > low`` se cumple siempre (high = close + up, low = close - down,
      up/down >= 0, y high - low = up + down >= 0; si ambos = 0, high == low == close).
    - ``volume > 0`` para evitar ZeroDivisionError en VWAP/volume_relative.
    - Variacion independiente de up/down/close/volume para que ATR reciba
      True Ranges no-constantes y VWAP reciba typical_prices variados.

    El floor ``low = max(close - down, 0.0001)`` evita ``low <= 0``
    cuando ``close - down`` se vuelve negativo (estrategia permite
    ``down > close``). ``close >= 1.0`` garantiza que el floor queda
    siempre por debajo de close; por tanto ``low < close`` se mantiene
    como invariante del bar (no se rompe ``high >= close >= low``).
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    candles: list[OHLCV] = []
    for index in range(n):
        close = draw(
            st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False)
        )
        up = draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
        down = draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
        volume = draw(
            st.floats(min_value=0.1, max_value=10_000.0, allow_nan=False, allow_infinity=False)
        )
        candles.append(
            OHLCV(
                symbol="BTC/USDT",
                timestamp=1_700_000_000_000 + index * 60_000,
                open=close,
                high=close + up,
                # 0.0001 floor: ver docstring de la strategy.
                low=max(close - down, 0.0001),
                close=close,
                volume=volume,
            )
        )
    return candles


positive_closes = st.lists(
    st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    min_size=6,
    max_size=40,
)

# MACD tradicional (fast=12, slow=26, signal=9) requiere al menos
# slow + signal - 1 = 34 velas. Strategy dedicado con min_size=35.
macd_closes = st.lists(
    st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    min_size=35,
    max_size=80,
)


# ===========================================================================
# F3 mirror: invariantes cubiertos con @settings(max_examples=1000, deadline=None).
# ===========================================================================


@given(
    start=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    step=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_ema_is_bounded_by_latest_window_values(start: float, step: float) -> None:
    closes = [start + step * index for index in range(8)]
    candles = _candles_from_closes(closes)
    period = 5
    first = EmaIndicator().compute(candles, {"period": period})
    second = EmaIndicator().compute(candles, {"period": period})
    window = closes[-period:]
    assert min(window) <= first <= max(window)
    assert first == second


@given(positive_closes)
@settings(max_examples=1000, deadline=None)
def test_rsi_stays_in_closed_interval(closes: list[float]) -> None:
    first = RsiIndicator().compute(_candles_from_closes(closes), {"period": 5})
    second = RsiIndicator().compute(_candles_from_closes(closes), {"period": 5})
    assert 0.0 <= first <= 100.0
    assert first == second


@given(positive_closes)
@settings(max_examples=1000, deadline=None)
def test_bollinger_bands_are_ordered(closes: list[float]) -> None:
    first = BollingerBandsIndicator().compute(
        _candles_from_closes(closes),
        {"period": 5, "std_dev": 2.0},
    )
    assert first["lower"] <= first["middle"] <= first["upper"]


@given(positive_closes)
@settings(max_examples=1000, deadline=None)
def test_volatility_is_non_negative_and_deterministic(closes: list[float]) -> None:
    candles = _candles_from_closes(closes)
    params = {"lookback": 5, "method": "stddev"}
    first = VolatilityIndicator().compute(candles, params)
    second = VolatilityIndicator().compute(candles, params)
    assert first >= 0.0
    assert first == second


@given(
    base=st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    current_volume=st.floats(
        min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=1000, deadline=None)
def test_volume_relative_is_non_negative(base: float, current_volume: float) -> None:
    candles = _candles_from_closes([10.0, 10.5, 11.0, 11.5])
    candles[0] = replace(candles[0], volume=base)
    candles[1] = replace(candles[1], volume=base)
    candles[2] = replace(candles[2], volume=base)
    candles[3] = replace(candles[3], volume=current_volume)
    first = VolumeRelativeIndicator().compute(candles, {"lookback": 3})
    assert first >= 0.0


@given(
    start=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    end=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_momentum_sign_matches_price_direction(start: float, end: float) -> None:
    candles = _candles_from_closes([start, start, start, end])
    result = MomentumIndicator().compute(candles, {"lookback": 3})
    if end > start:
        assert result > 0.0
    elif end < start:
        assert result < 0.0
    else:
        assert result == 0.0


@given(
    bid_1=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    bid_2=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    ask_1=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    ask_2=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_order_book_imbalance_stays_in_unit_interval(
    bid_1: float,
    bid_2: float,
    ask_1: float,
    ask_2: float,
) -> None:
    result = OrderBookImbalanceIndicator().compute(
        [],
        {
            "feature_enabled": True,
            "bids": [[100.0, bid_1], [99.5, bid_2]],
            "asks": [[100.5, ask_1], [101.0, ask_2]],
        },
    )
    assert -1.0 <= result <= 1.0


# Pine contract OBI: imbalance > 0 cuando bid_volume > ask_volume,
# < 0 cuando ask domina, == 0 cuando iguales. Pine contract del
# F3 mirror: ademas del rango unitario, el signo debe coincidir con
# la dominancia de volumen. Esto pinea la semantica del "imbalance
# metric" y atrapa regresiones de sign-flip en el computo.
@given(
    bid_volume=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    ask_volume=st.floats(min_value=0.1, max_value=1_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_order_book_imbalance_sign_matches_volume_dominance(
    bid_volume: float, ask_volume: float
) -> None:
    result = OrderBookImbalanceIndicator().compute(
        [],
        {
            "feature_enabled": True,
            "bids": [[100.0, bid_volume], [99.5, bid_volume]],
            "asks": [[100.5, ask_volume], [101.0, ask_volume]],
        },
    )
    # Tolerancia para FP: cuando bid_volume == ask_volume, bid_volume - ask_volume == 0
    # produce OBI = 0; cuando diff es despreciable, el signo sigue siendo 0.
    if bid_volume > ask_volume:
        assert result > 0.0
    elif bid_volume < ask_volume:
        assert result < 0.0
    else:
        assert result == 0.0


def test_order_book_imbalance_is_zero_when_bid_and_ask_volumes_are_equal() -> None:
    """Sentinel: OBI == 0 cuando bid_volume == ask_volume.

    Pine contract: el branch ``else: assert result == 0.0`` del property
    test es dead code con floats (la igualdad exacta es ~0% con
    ``st.floats``). Este sentinel hace explicito el contrato en un
    caso conocido y atrapa sign-flip regressions de un solo bit.
    """
    result = OrderBookImbalanceIndicator().compute(
        [],
        {
            "feature_enabled": True,
            "bids": [[100.0, 42.0], [99.5, 42.0]],
            "asks": [[100.5, 42.0], [101.0, 42.0]],
        },
    )
    assert result == 0.0


# ===========================================================================
# New TSK-204 property tests: ATR, VWAP, MACD, Spread.
# ===========================================================================


@given(ohlcv_with_ranges())
@settings(max_examples=1000, deadline=None)
def test_atr_is_non_negative_and_deterministic(candles: list[OHLCV]) -> None:
    """ATR (Wilder's smoothed True Range) es siempre >= 0 y bit-exact.

    Pine contract:
    - True Range = max(high-low, |high-prev_close|, |low-prev_close|) >= 0
      por construccion, asi que el ATR acumulado no puede ser negativo.
    - Determinismo: sin fuentes de no-determinismo (sin random, sin
      clock), dos calls con mismos inputs producen el mismo float.
    - Strategy ``ohlcv_with_ranges`` genera True Range no-constante
      (offsets de high/low independientes de close) para que el
      smoothing Wilder se ejerza sobre TRs variados.
    - ATR requiere al menos period + 1 velas; la strategy pinea
      ``min_size=6`` > 5 = period + 1.
    """
    params = {"period": 5}
    first = AtrIndicator().compute(candles, params)
    second = AtrIndicator().compute(candles, params)
    assert first >= 0.0
    assert first == second


@given(ohlcv_with_ranges())
@settings(max_examples=1000, deadline=None)
def test_vwap_is_bounded_by_typical_prices(candles: list[OHLCV]) -> None:
    """VWAP de sesion esta acotado por [min(typical), max(typical)].

    Pine contract:
    - typical_price = (high + low + close) / 3 >= 0 si todos los inputs
      son positivos. Strategy ``ohlcv_with_ranges`` varia high y low
      independientemente de close, asi que typical_price varia
      (no es trivialmente igual a close como en
      ``_candles_from_closes``).
    - VWAP = sum(typical * volume) / sum(volume) es una media
      ponderada de los typical_prices, asi que cae dentro del rango
      [min, max] del conjunto (media acotada por min/max de la
      poblacion).
    - Strategy pinea volume > 0, asi que no hay ZeroDivisionError path.
    - Tolerancia 1e-9 para absorber FP rounding al borde.
    - Determinismo: dos calls con mismos inputs -> mismo output.
    """
    first = VwapIndicator().compute(candles, {"anchor": "session"})
    second = VwapIndicator().compute(candles, {"anchor": "session"})
    typicals = [(c.high + c.low + c.close) / 3.0 for c in candles]
    assert min(typicals) - 1e-9 <= first <= max(typicals) + 1e-9
    assert first == second


@given(
    candles=ohlcv_with_ranges(min_size=30, max_size=80),
    rolling_period=st.integers(min_value=5, max_value=20),
)
@settings(max_examples=1000, deadline=None)
def test_vwap_rolling_matches_session_on_slice(candles: list[OHLCV], rolling_period: int) -> None:
    """VWAP rolling(N) sobre candles == VWAP session sobre las ultimas N velas.

    Pine contract: anchor=rolling toma las ultimas ``rolling_period``
    velas y computa VWAP de sesion sobre ese subset. Por tanto, el
    resultado debe ser identico al de anchor=session sobre el mismo
    subset (modulo bit-exact; el computo no introduce fuentes de
    no-determinismo). F3 mirror: max_examples=1000 (alineado con el
    resto de la suite; el peso extra del composite strategy sigue
    siendo aceptable).
    """
    rolling_result = VwapIndicator().compute(
        candles, {"anchor": "rolling", "rolling_period": rolling_period}
    )
    session_result = VwapIndicator().compute(candles[-rolling_period:], {"anchor": "session"})
    assert rolling_result == session_result


@given(macd_closes)
@settings(max_examples=1000, deadline=None)
def test_macd_histogram_is_exactly_macd_minus_signal(closes: list[float]) -> None:
    """``histogram == macd - signal`` bit-exact + 3 keys presentes.

    Pine contract:
    - El computo es algebraicamente cerrado; histogram es siempre
      igual a macd - signal sin perdida de precision.
    - El output siempre tiene exactamente las 3 keys ("macd", "signal",
      "histogram"); no hay keys faltantes ni extras.
    - Determinismo: dos calls con mismos inputs -> mismo dict.
    - Necesita al menos slow + signal - 1 = 26 + 9 - 1 = 34 velas;
      ``macd_closes`` strategy pinea min_size=35.
    """
    candles = _candles_from_closes(closes)
    params = {"fast": 12, "slow": 26, "signal": 9}
    first = MacdIndicator().compute(candles, params)
    second = MacdIndicator().compute(candles, params)
    assert set(first) == {"macd", "signal", "histogram"}
    assert first["histogram"] == first["macd"] - first["signal"]
    assert second == first


@given(
    best_bid=st.floats(min_value=0.1, max_value=10_000.0, allow_nan=False, allow_infinity=False),
    best_ask=st.floats(min_value=0.1, max_value=10_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_spread_matches_spec_formula(best_bid: float, best_ask: float) -> None:
    """Spread = ((ask - bid) / midpoint) * 10000 vs spec directo.

    Pine contract: la spec define el computo canonico en terminos de
    ``((best_ask - best_bid) / midpoint) * 10000`` donde
    ``midpoint = (best_bid + best_ask) / 2``. El test verifica
    contra esa formula directamente (NO contra simplificaciones
    algebraicas) para que cualquier drift entre la impl y la spec
    sea atrapado por el property test.

    La validacion interna de ``builtin.py`` rechaza ``ask < bid``
    con ``IndicatorError``. Para no perder el 50% de los draws
    generados por ``st.floats``, se ordena el par bid/ask al
    inicio (``sorted``), normalizando el dominio a ``ask >= bid``.
    La formula spec es no-negativa por construccion solo cuando
    ``ask >= bid``; al forzar este orden el test verifica el
    computo en su dominio valido sin introducir sesgo en los
    inputs (el swap es interno, los parametros son equivalentes).
    """
    best_bid, best_ask = sorted([best_bid, best_ask])
    first = SpreadIndicator().compute([], {"best_bid": best_bid, "best_ask": best_ask})
    second = SpreadIndicator().compute([], {"best_bid": best_bid, "best_ask": best_ask})
    midpoint = (best_bid + best_ask) / 2.0
    expected = ((best_ask - best_bid) / midpoint) * 10_000.0
    assert first >= 0.0
    assert first == pytest.approx(expected, rel=1e-9)
    assert second == first


def test_spread_returns_zero_when_bid_equals_ask() -> None:
    """Spread computado es exactamente 0 cuando best_bid == best_ask.

    Pine contract: trivialmente (0/midpoint)*10000 = 0. Se cubre
    con casos puntuales (no hypothesis) porque la formula no tiene
    variacion aleatoria relevante.
    """
    assert SpreadIndicator().compute([], {"best_bid": 100.0, "best_ask": 100.0}) == 0.0
    assert SpreadIndicator().compute([], {"best_bid": 1.0, "best_ask": 1.0}) == 0.0


def test_spread_explicit_bps_mode_echoes_input() -> None:
    """Modo explicito (``spread_bps`` en params) hace bypass del computo.

    Pine contract: si ``spread_bps`` esta en params, ``builtin.py``
    lo retorna tal cual sin tocar best_bid/best_ask. Esto es
    independiente del computo y se testea puntualmente.
    """
    assert SpreadIndicator().compute([], {"spread_bps": 12.5}) == 12.5
    assert SpreadIndicator().compute([], {"spread_bps": 0.0}) == 0.0
    assert SpreadIndicator().compute([], {"spread_bps": 999.99}) == 999.99
