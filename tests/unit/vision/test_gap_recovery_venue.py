"""WP-PAPER-QUOTE-GAP-002 — el contrato de evidencia contra minutos reales del venue.

Los tests de `test_gap_recovery.py` usan minutos construidos para que cada caso sea
inequívoco. Éstos hacen la misma pregunta sobre el archivo que el proyecto ya versiona
(`data/quote-feed-1m`, klines públicas de Binance con su sha256 en el manifiesto):

* una hora completa y real se declara limpia cuando ninguna barrera cae dentro de ella;
* la vela que el archivo **de verdad** no tiene se declara no cubierta, nombrando el minuto
  que falta — no se rellena ni se aproxima;
* un stop calculado con los precios reales de la hora se sitúa en el minuto real cuyo rango
  lo contiene, y el mismo cálculo para el take-profit.

El nivel se deriva del propio archivo (mínimo, máximo, primer open), nunca de una constante
elegida a mano: si el archivo cambia, el test sigue preguntando lo mismo sobre los datos
nuevos, y los tests de integridad del feed fallan antes si el cambio fue una sustitución.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from trading_bot.paper.broker import PaperPosition
from trading_bot.vision.gap_recovery import (
    INTACT,
    MINUTE_MS,
    RECONSTRUCTIBLE,
    VERDICT_BLOCKED,
    VERDICT_CLEAR,
    VERDICT_RECONSTRUCT,
    GapWindow,
    assess_gap,
    stop_price,
)
from trading_bot.vision.quotes import MinuteBarQuoteFeed

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "quote-feed-1m"
SYMBOL = "UNI/USDT"
FILE_SYMBOL = "UNIUSDT"
HOUR_MS = 3_600_000
BAR_MS = 300_000
START_MS = int(datetime(2021, 1, 4, tzinfo=UTC).timestamp() * 1000)


@pytest.fixture(scope="module")
def feed() -> MinuteBarQuoteFeed:
    return MinuteBarQuoteFeed.from_directory(
        DATA,
        aliases={FILE_SYMBOL: SYMBOL},
        symbols=[SYMBOL],
    )


def _position(*, entry: float, stop_pct: float, take_pct: float) -> dict:
    return PaperPosition(
        symbol=SYMBOL,
        side="buy",
        entry_price=entry,
        quantity=1.0,
        notional_usdt=entry,
        stop_loss_pct=stop_pct,
        take_profit_pct=take_pct,
        opened_at=(START_MS - HOUR_MS) / 1000.0,
        position_id="pos-venue-0001",
    ).to_row()


def _stop_pct(entry: float, level: float) -> float:
    """Distancia positiva que hace que la fórmula del bróker dé ``level`` por debajo."""

    return (1.0 - level / entry) * 100.0


def _take_pct(entry: float, level: float) -> float:
    """Distancia positiva que hace que la fórmula del bróker dé ``level`` por encima."""

    return (level / entry - 1.0) * 100.0


def _window_from_bar(bar_ms: int) -> GapWindow:
    return GapWindow(barrier_ms=bar_ms - BAR_MS, resume_ms=bar_ms + BAR_MS, interval_ms=BAR_MS)


def _real_hole(feed: MinuteBarQuoteFeed) -> int:
    """El primer minuto que el archivo no tiene, descubierto y no asumido."""

    for left, right in pairwise(feed.series(SYMBOL).stamps):
        if right - left != MINUTE_MS:
            return left + MINUTE_MS
    raise AssertionError("el archivo ya no tiene el hueco que estos tests documentan")


def test_a_real_hour_is_clear_when_no_level_falls_inside_it(
    feed: MinuteBarQuoteFeed,
) -> None:
    start, end = START_MS + 4 * HOUR_MS, START_MS + 5 * HOUR_MS
    bars = feed.minute_bars_between(SYMBOL, start, end)
    assert len(bars) == 60
    entry = float(bars[0].open)
    lowest = min(float(bar.low) for bar in bars)
    highest = max(float(bar.high) for bar in bars)
    #: Un 10 % más allá de lo que la hora imprimió: la barrera no puede estar dentro.
    assessment = assess_gap(
        window=GapWindow(barrier_ms=start - BAR_MS, resume_ms=end, interval_ms=BAR_MS),
        positions=[
            _position(
                entry=entry,
                stop_pct=_stop_pct(entry, lowest * 0.9),
                take_pct=_take_pct(entry, highest * 1.1),
            )
        ],
        feed=feed,
    )

    assert assessment.verdict == VERDICT_CLEAR, assessment.detail
    assert assessment.positions[0].status == INTACT
    assert assessment.positions[0].minutes_observed == 60
    evidence = assessment.evidence["symbols"][SYMBOL]
    assert evidence["first_minute_ms"] == start
    assert evidence["last_minute_ms"] == end - MINUTE_MS
    assert len(str(evidence["window_sha256"])) == 64


def test_the_bar_the_archive_does_not_have_is_refused_with_its_minute(
    feed: MinuteBarQuoteFeed,
) -> None:
    missing = _real_hole(feed)
    bar = missing - ((missing - START_MS) % BAR_MS)
    assessment = assess_gap(
        window=_window_from_bar(bar),
        positions=[_position(entry=5.0, stop_pct=1.0, take_pct=1.0)],
        feed=feed,
    )

    assert assessment.verdict == VERDICT_BLOCKED
    assert assessment.code == "GAP_NOT_COVERED"
    evidence = assessment.evidence["symbols"][SYMBOL]
    assert missing in evidence["missing_minutes"]
    assert evidence["minutes_observed"] < evidence["minutes_expected"]
    #: El hueco se nombra minuto a minuto; no se redondea a "casi".
    assert "minutes observed in the hole" in assessment.detail


def test_a_stop_derived_from_real_prices_lands_on_the_real_minute(
    feed: MinuteBarQuoteFeed,
) -> None:
    """El nivel se calcula con la fórmula del bróker y el archivo dice qué minuto lo tocó."""

    start, end = START_MS + 6 * HOUR_MS, START_MS + 7 * HOUR_MS
    bars = feed.minute_bars_between(SYMBOL, start, end)
    entry = float(bars[0].open)
    lowest = min(bars, key=lambda bar: float(bar.low))
    stop_pct = _stop_pct(entry, float(lowest.low))
    assessment = assess_gap(
        window=GapWindow(barrier_ms=start - BAR_MS, resume_ms=end, interval_ms=BAR_MS),
        positions=[
            _position(
                entry=entry,
                stop_pct=stop_pct,
                #: Un take-profit al 100 % de la entrada no puede caer dentro de la hora.
                take_pct=_take_pct(entry, float(lowest.low) * 2.0),
            )
        ],
        feed=feed,
    )

    status = assessment.positions[0]
    assert assessment.verdict == VERDICT_RECONSTRUCT, assessment.detail
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "stop_loss"
    assert status.exit_minute_ms == int(lowest.ts_ms)
    assert status.exit_price == pytest.approx(stop_price("buy", entry, stop_pct), abs=1e-12)
    assert status.stop_touch is not None
    assert status.stop_touch.low == pytest.approx(float(lowest.low))
    assert status.stop_touch.low <= status.stop_price


def test_a_take_profit_derived_from_real_prices_is_placed_the_same_way(
    feed: MinuteBarQuoteFeed,
) -> None:
    start, end = START_MS + 9 * HOUR_MS, START_MS + 10 * HOUR_MS
    bars = feed.minute_bars_between(SYMBOL, start, end)
    entry = float(bars[0].open)
    highest = max(bars, key=lambda bar: float(bar.high))
    #: El objetivo es el máximo impreso, un pelo por debajo: el redondeo de la fórmula no
    #: puede convertir un toque real en un "casi".
    take_pct = _take_pct(entry, float(highest.high) * (1.0 - 1e-9))
    assessment = assess_gap(
        window=GapWindow(barrier_ms=start - BAR_MS, resume_ms=end, interval_ms=BAR_MS),
        positions=[
            _position(
                entry=entry,
                stop_pct=_stop_pct(entry, float(highest.high) * 0.5),
                take_pct=take_pct,
            )
        ],
        feed=feed,
    )

    status = assessment.positions[0]
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "take_profit"
    assert status.exit_minute_ms == int(highest.ts_ms)
    assert status.take_profit_touch is not None
    assert status.take_profit_touch.high >= status.take_profit_price
