"""WP-PAPER-QUOTE-GAP-002 — lo que un feed de 1 minuto puede demostrar sobre un hueco.

Estos tests no tocan el lane ni el libro: fijan el contrato de la *evidencia*. La pregunta
que responden es estrecha y por eso se puede contestar sin ambigüedad:

* ¿estaba observado cada minuto del hueco, en orden y sin repetir?
* ¿algún minuto contiene el stop o el take-profit de una posición abierta?
* si lo contiene, ¿el orden entre las dos barreras es un hecho (minutos distintos) o una
  incógnita (el mismo minuto)?

Lo que se exige del veredicto:

1. sin toque no hay salida posible, y eso es una observación, no una suposición;
2. un toque en un minuto concreto sitúa la salida en ese minuto, al precio de la barrera;
3. stop y take-profit dentro del mismo minuto **bloquean**: el OHLC de un minuto no dice
   qué extremo se imprimió antes, y elegir uno sería inventar el PnL;
4. cobertura parcial, serie corrupta o símbolo ausente bloquean; nunca se redondea hacia
   "suficiente";
5. una opinión en vuelo que podía llenarse dentro del hueco bloquea la reanudación: los
   minutos pueden poner precio a un fill, no decir qué posición habría existido después.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from trading_bot.paper.broker import PaperPosition
from trading_bot.vision.gap_recovery import (
    AMBIGUOUS,
    INTACT,
    MINUTE_MS,
    RECONSTRUCTIBLE,
    VERDICT_BLOCKED,
    VERDICT_CLEAR,
    VERDICT_RECONSTRUCT,
    GapWindow,
    assess_gap,
    stop_price,
    take_profit_price,
)
from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries

BAR_MS = 300_000
T0 = 1_792_000_800_000
BARRIER = T0
RESUME = T0 + 3 * BAR_MS  #: dos velas de 5 minutos perdidas
WINDOW = GapWindow(barrier_ms=BARRIER, resume_ms=RESUME, interval_ms=BAR_MS)
START = BARRIER + BAR_MS
SYMBOL = "BTC/USDT"


def _series(
    symbol: str,
    *,
    lows: float = 99.6,
    highs: float = 100.4,
    overrides: dict[int, tuple[float, float, float, float]] | None = None,
    missing: Sequence[int] = (),
) -> MinuteSeries:
    rows = []
    for index in range(WINDOW.minutes_expected):
        stamp = START + index * MINUTE_MS
        if stamp in missing:
            continue
        if overrides and stamp in overrides:
            opened, high, low, close = overrides[stamp]
        else:
            opened, high, low, close = 100.0, highs, lows, 100.0
        rows.append([stamp, opened, high, low, close, 10.0])
    return MinuteSeries.from_rows(symbol, rows)


def _feed(**series: MinuteSeries) -> MinuteBarQuoteFeed:
    return MinuteBarQuoteFeed({item.symbol: item for item in series.values()})


def _position(
    *,
    symbol: str = SYMBOL,
    side: str = "buy",
    entry: float = 100.0,
    stop_pct: float = 0.5,
    take_pct: float = 1.0,
    quantity: float = 2.0,
    position_id: str = "pos-gap-0001",
) -> dict:
    return PaperPosition(
        symbol=symbol,
        side=side,
        entry_price=entry,
        quantity=quantity,
        notional_usdt=entry * quantity,
        stop_loss_pct=stop_pct,
        take_profit_pct=take_pct,
        opened_at=(BARRIER - BAR_MS) / 1000.0,
        position_id=position_id,
    ).to_row()


def _assess(positions: list[dict], feed: object, **over: object):  # type: ignore[no-untyped-def]
    kwargs: dict[str, object] = {
        "window": WINDOW,
        "positions": positions,
        "feed": feed,
    }
    kwargs.update(over)
    return assess_gap(**kwargs)  # type: ignore[arg-type]


# -- 0. las barreras son las del bróker -----------------------------------------


def test_the_levels_are_the_brokers_own_formulas() -> None:
    """Una segunda definición de stop que derive de la primera es como no tener ninguna."""

    for side, stop_pct, take_pct in (("buy", 0.5, 1.0), ("sell", 0.35, 0.8)):
        reference = PaperPosition(
            symbol=SYMBOL,
            side=side,
            entry_price=100.0,
            quantity=1.0,
            notional_usdt=100.0,
            stop_loss_pct=stop_pct,
            take_profit_pct=take_pct,
        )
        assert stop_price(side, 100.0, stop_pct) == pytest.approx(reference.stop_loss_price)
        assert take_profit_price(side, 100.0, take_pct) == pytest.approx(
            reference.take_profit_price
        )


# -- 1. el hueco limpio ---------------------------------------------------------


def test_a_hole_nobody_touched_is_clear_and_that_is_an_observation() -> None:
    assessment = _assess([_position()], _feed(btc=_series(SYMBOL)))

    assert assessment.verdict == VERDICT_CLEAR
    assert assessment.ok and assessment.code is None
    status = assessment.positions[0]
    assert status.status == INTACT
    assert status.stop_touch is None and status.take_profit_touch is None
    assert status.minutes_observed == WINDOW.minutes_expected
    #: El rango que el hueco imprimió se publica igual: es lo que el mark pudo ver.
    assert status.worst_price == pytest.approx(99.6)
    assert status.best_price == pytest.approx(100.4)
    assert status.worst_unrealised_usdt == pytest.approx((99.6 - 100.0) * 2.0)


def test_the_evidence_names_the_bytes_it_used() -> None:
    feed = _feed(btc=_series(SYMBOL))
    assessment = _assess([_position()], feed)

    evidence = assessment.evidence["symbols"][SYMBOL]
    assert evidence["feed"] == feed.name
    assert evidence["minutes_observed"] == WINDOW.minutes_expected
    assert evidence["first_minute_ms"] == START
    assert evidence["last_minute_ms"] == RESUME - MINUTE_MS
    assert len(str(evidence["window_sha256"])) == 64
    assert evidence["series_sha256"] == feed.series_digest(SYMBOL)
    #: Una serie distinta tiene que producir evidencia distinta, o el digest no nombra nada.
    other = _assess([_position()], _feed(btc=_series(SYMBOL, lows=99.7)))
    assert (
        other.evidence["symbols"][SYMBOL]["window_sha256"]
        != evidence["window_sha256"]
    )


# -- 2. una barrera cruzada -----------------------------------------------------


def test_a_stop_crossed_inside_the_hole_is_placed_at_its_minute() -> None:
    hit = START + 4 * MINUTE_MS
    feed = _feed(
        btc=_series(SYMBOL, overrides={hit: (100.0, 100.2, 99.4, 99.45)}),
    )
    assessment = _assess([_position()], feed)

    assert assessment.verdict == VERDICT_RECONSTRUCT
    status = assessment.positions[0]
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "stop_loss"
    assert status.exit_minute_ms == hit
    assert status.exit_price == pytest.approx(99.5)
    assert status.stop_touch is not None and status.stop_touch.low == 99.4


def test_a_take_profit_crossed_inside_the_hole_is_placed_the_same_way() -> None:
    hit = START + 2 * MINUTE_MS
    feed = _feed(btc=_series(SYMBOL, overrides={hit: (100.0, 101.2, 99.9, 101.1)}))
    assessment = _assess([_position()], feed)

    status = assessment.positions[0]
    assert assessment.verdict == VERDICT_RECONSTRUCT
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "take_profit"
    assert status.exit_minute_ms == hit
    assert status.exit_price == pytest.approx(101.0)


def test_across_minutes_the_order_is_a_fact_and_the_earlier_one_wins() -> None:
    stop_at = START + MINUTE_MS
    take_at = START + 5 * MINUTE_MS
    feed = _feed(
        btc=_series(
            SYMBOL,
            overrides={
                stop_at: (100.0, 100.1, 99.4, 99.5),
                take_at: (99.5, 101.3, 99.4, 101.2),
            },
        )
    )
    assessment = _assess([_position()], feed)

    status = assessment.positions[0]
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "stop_loss"
    assert status.exit_minute_ms == stop_at
    #: El take-profit también se tocó, y se declara: la razón de salida es el primero.
    assert status.take_profit_touch is not None
    assert status.take_profit_touch.minute_ms == take_at


def test_the_take_profit_can_come_first() -> None:
    take_at = START + MINUTE_MS
    stop_at = START + 7 * MINUTE_MS
    feed = _feed(
        btc=_series(
            SYMBOL,
            overrides={
                take_at: (100.0, 101.4, 99.9, 101.2),
                stop_at: (101.2, 101.2, 99.2, 99.3),
            },
        )
    )
    status = _assess([_position()], feed).positions[0]

    assert status.exit_reason == "take_profit"
    assert status.exit_minute_ms == take_at


# -- 3. la ambigüedad bloquea ---------------------------------------------------


def test_stop_and_take_profit_in_one_minute_blocks_instead_of_choosing() -> None:
    """El bróker tiene `stop_first` para una vela viva; una recuperación no puede usarlo.

    Ese convenio es una decisión de modelado sobre un instante que no se observó. Aplicarlo
    aquí publicaría un PnL cuya magnitud y signo dependen de qué extremo se imprimió antes,
    y eso es justo lo que un libro en recuperación no puede afirmar.
    """

    both = START + 3 * MINUTE_MS
    feed = _feed(btc=_series(SYMBOL, overrides={both: (100.0, 101.2, 99.3, 100.0)}))
    assessment = _assess([_position()], feed)

    assert assessment.verdict == VERDICT_BLOCKED
    assert assessment.code == "GAP_EXIT_AMBIGUOUS"
    assert not assessment.ok
    status = assessment.positions[0]
    assert status.status == AMBIGUOUS
    assert status.ambiguous_minute_ms == both
    assert status.exit_minute_ms is None and status.exit_reason is None
    #: El rango sigue publicado: el operador ve entre qué dos precios está la verdad.
    assert status.worst_price == pytest.approx(99.3)
    assert status.best_price == pytest.approx(101.2)


# -- 4. cobertura: nada se redondea ---------------------------------------------


def test_a_missing_minute_is_not_rounded_up_to_coverage() -> None:
    absent = START + 6 * MINUTE_MS
    feed = _feed(btc=_series(SYMBOL, missing=[absent]))
    assessment = _assess([_position()], feed)

    assert assessment.verdict == VERDICT_BLOCKED
    assert assessment.code == "GAP_NOT_COVERED"
    assert "9/10 minutes" in assessment.detail
    assert absent in assessment.evidence["symbols"][SYMBOL]["missing_minutes"]
    assert assessment.positions[0].status == "UNCOVERED"


def test_a_grid_that_stops_before_the_resume_bar_blocks() -> None:
    series = _series(SYMBOL)
    truncated = MinuteSeries(symbol=SYMBOL, bars=series.bars[:-1])
    assessment = _assess([_position()], _feed(btc=truncated))

    assert assessment.code == "GAP_NOT_COVERED"
    assert "9/10" in assessment.detail


def test_a_symbol_absent_from_the_feed_is_not_answered_by_another() -> None:
    feed = _feed(eth=_series("ETH/USDT"))
    assessment = _assess([_position()], feed)

    assert assessment.code == "GAP_NOT_COVERED"
    assert "BTC/USDT is not in" in assessment.detail


def test_a_corrupt_series_never_becomes_a_verdict() -> None:
    """Desordenada o duplicada es corrupción, y el feed se niega antes de opinar."""

    from trading_bot.vision.quotes import QuoteFeedIntegrityError

    rows = [[START, 100.0, 100.1, 99.9, 100.0, 1.0]] * 3
    with pytest.raises(QuoteFeedIntegrityError, match="unsorted or duplicated"):
        MinuteSeries.from_rows(SYMBOL, rows)


def test_the_feed_may_not_be_the_replayed_bar_source() -> None:
    class OwnBars:
        name = "bar_open"

        def has(self, symbol: str) -> bool:
            return True

        def minute_bars_between(self, symbol: str, start_ms: int, end_ms: int):  # type: ignore[no-untyped-def]
            return _series(SYMBOL).bars

        def series_digest(self, symbol: str) -> str:
            return "x"

    assessment = _assess([_position()], OwnBars())
    assert assessment.code == "GAP_FEED_NOT_INDEPENDENT"


def test_no_feed_at_all_is_a_block_not_a_guess() -> None:
    assessment = _assess([_position()], None)
    assert assessment.code == "GAP_NOT_COVERED"
    assert "no independent 1-minute feed" in assessment.detail


# -- 5. la opinión en vuelo -----------------------------------------------------


def test_an_opinion_that_could_have_filled_inside_the_hole_blocks() -> None:
    assessment = _assess(
        [_position()],
        _feed(btc=_series(SYMBOL)),
        pending={SYMBOL: {"received_at_ms": START - 30_000}},
        max_opinion_age_ms=BAR_MS,
    )

    assert assessment.code == "GAP_PENDING_OPINION"
    assert "would have produced inside the hole" in assessment.detail


def test_an_opinion_already_expired_before_the_hole_does_not_block() -> None:
    assessment = _assess(
        [_position()],
        _feed(btc=_series(SYMBOL)),
        pending={SYMBOL: {"received_at_ms": START - BAR_MS - MINUTE_MS}},
        max_opinion_age_ms=BAR_MS,
    )

    assert assessment.verdict == VERDICT_CLEAR


# -- 6. dos símbolos, dos series ------------------------------------------------


def test_a_minute_from_one_symbol_is_never_used_to_judge_another() -> None:
    """Un hueco en el que ETH se lleva el stop no dice nada de la posición de SOL.

    Usar el rango de ETH para juzgar SOL sería una observación fabricada, y el veredicto
    saldría con la misma pinta que uno real.
    """

    eth_hit = START + 2 * MINUTE_MS
    feed = _feed(
        eth=_series("ETH/USDT", overrides={eth_hit: (100.0, 100.2, 90.0, 90.5)}),
        sol=_series("SOL/USDT"),
    )
    assessment = _assess(
        [
            _position(symbol="ETH/USDT", position_id="pos-eth"),
            _position(symbol="SOL/USDT", position_id="pos-sol"),
        ],
        feed,
    )

    by_id = {item.position_id: item for item in assessment.positions}
    assert by_id["pos-eth"].status == RECONSTRUCTIBLE
    assert by_id["pos-eth"].exit_price == pytest.approx(99.5)
    assert by_id["pos-sol"].status == INTACT
    assert by_id["pos-sol"].worst_price == pytest.approx(99.6)


def test_a_short_position_reads_the_levels_from_the_other_side() -> None:
    hit = START + MINUTE_MS
    feed = _feed(btc=_series(SYMBOL, overrides={hit: (100.0, 100.6, 99.2, 100.4)}))
    status = _assess([_position(side="sell")], feed).positions[0]

    assert status.stop_price == pytest.approx(100.5)
    assert status.take_profit_price == pytest.approx(99.0)
    assert status.status == RECONSTRUCTIBLE
    assert status.exit_reason == "stop_loss"
    assert status.exit_price == pytest.approx(100.5)
    #: Para un corto el precio adverso es el alto, no el bajo.
    assert status.worst_price == pytest.approx(100.6)
    assert status.worst_unrealised_usdt == pytest.approx((100.0 - 100.6) * 2.0)


def test_no_position_and_no_opinion_is_clear_without_owing_coverage() -> None:
    """Sin exposición ni opinión en vuelo, el hueco no puede haber producido nada.

    No se exige cobertura de un símbolo que nadie tiene: la razón del veredicto es la
    ausencia de exposición, y se declara como tal en vez de fingir una comprobación.
    """

    verdict = _assess([], _feed(btc=_series(SYMBOL)))
    assert verdict.verdict == VERDICT_CLEAR
    assert "no position is open" in verdict.detail
    assert [check["check"] for check in verdict.checks][-1] == "exposure_present"

    #: ...pero si algo podía llenarse, el mismo hueco bloquea:
    assert (
        _assess(
            [],
            _feed(btc=_series(SYMBOL)),
            pending={SYMBOL: {"received_at_ms": START - MINUTE_MS}},
            max_opinion_age_ms=BAR_MS,
        ).code
        == "GAP_PENDING_OPINION"
    )


def test_the_window_refuses_a_hole_that_is_not_there() -> None:
    with pytest.raises(ValueError, match="the window is empty"):
        GapWindow(barrier_ms=T0, resume_ms=T0 + BAR_MS, interval_ms=BAR_MS)
