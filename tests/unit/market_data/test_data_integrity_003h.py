"""003H — los cuatro instantes de una decisión, cada uno con su nombre.

Una vela tiene **origen** (``open_ms``), **cierre** (``close_ms = open + 60 s``), **reloj del
venue** al responder (``server_time_ms``) y **llegada al host** (``received_at_ms``). Sobre
esos cuatro instantes se definen dos esperas distintas que no son intercambiables:

* ``delivery_latency_ms = received_at_ms - close_ms`` — lo que tardó el dato en llegar;
* ``quote_lag_ms = quote_ts_ms - received_at_ms`` — lo que esperó una orden desde que llegó
  la respuesta hasta que existió un precio que esa respuesta podía tomar.

Sumarlas es ``quote_ts_ms - close_ms``, el retraso total desde el cierre de la vela. Este
fichero fija las definiciones, el rechazo de una vela futura o revisada y el gate de settle
que evita guardar una vela provisional (003G-D2: una vela guardada 1 192 ms después de su
cierre fue revisada 78 s más tarde por el venue).
"""

from __future__ import annotations

from pathlib import Path

from trading_bot.market_data.minute_collector import (
    MINUTE_MS,
    KlinePage,
    MinuteCollector,
)
from trading_bot.vision.clock import bar_close_ms, information_ms
from trading_bot.vision.execution import Quote, schedule

T0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))


def kline(open_ms: int, *, o=100.0, h=101.0, low=99.0, c=100.5, v=10.0) -> list[float]:
    return [open_ms, o, h, low, c, v]


class ScriptedVenue:
    name = "scripted_source"

    def __init__(self, *, server_time_ms: int) -> None:
        self.server_time_ms = int(server_time_ms)
        self.rows: dict[int, list[float]] = {}
        self.received_at_ms: int | None = None

    def add(self, open_ms: int, **kwargs: float) -> ScriptedVenue:
        self.rows[int(open_ms)] = kline(int(open_ms), **kwargs)
        return self

    def fetch(self, symbol, *, start_ms=None, end_ms=None, limit=500) -> KlinePage:
        stamps = sorted(
            stamp
            for stamp in self.rows
            if (start_ms is None or stamp >= int(start_ms))
            and (end_ms is None or stamp <= int(end_ms))
        )
        return KlinePage(
            symbol=symbol,
            rows=tuple(tuple(self.rows[stamp]) for stamp in stamps),
            server_time_ms=self.server_time_ms,
            received_at_ms=int(
                self.server_time_ms if self.received_at_ms is None else self.received_at_ms
            ),
        )

    def server_time(self) -> int:
        return self.server_time_ms


def make_collector(tmp_path: Path, venue: ScriptedVenue, **kwargs) -> MinuteCollector:
    defaults = dict(
        source=venue,
        root=tmp_path / "market",
        symbols=("BTCUSDT",),
        local_clock=lambda: int(venue.server_time_ms),
        settle_ms=0,
    )
    defaults.update(kwargs)
    return MinuteCollector(**defaults).open()


def events(collector: MinuteCollector) -> list[str]:
    return [str(event["kind"]) for event in collector.events]


def test_the_four_instants_are_ordered_and_the_two_waits_are_additive(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 63_000)
    venue.add(T0)
    venue.received_at_ms = T0 + 63_500
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        row = collector.stores["BTCUSDT"].bars()[-1]
        assert row.open_ms == T0
        assert row.close_ms == T0 + MINUTE_MS == bar_close_ms(T0, MINUTE_MS)
        assert row.server_time_ms >= row.close_ms, "una vela futura no es un precio"
        assert row.received_at_ms >= row.close_ms
        # La espera de entrega se mide contra el cierre; la de cotización, contra la llegada.
        assert row.delivery_latency_ms == row.received_at_ms - row.close_ms == 3_500
        assert row.received_at_ms != row.close_ms
    finally:
        collector.close()


def test_a_minute_that_closes_after_the_venue_clock_is_never_stored(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 30_000)
    venue.add(T0)  # cierra en T0+60 000, 30 s por delante del reloj del venue
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 0
        assert "FORMING_BAR_IGNORED" in events(collector)
        assert not (tmp_path / "market" / "BTCUSDT.jsonl").exists()
    finally:
        collector.close()


def test_settle_defers_a_just_closed_minute_until_it_can_no_longer_move(tmp_path: Path) -> None:
    # 003G-D2: se guardó 1 192 ms después del cierre y el venue la revisó después.
    venue = ScriptedVenue(server_time_ms=T0 + MINUTE_MS + 1_192)
    venue.add(T0, o=2_435.46, h=2_435.63, low=2_434.27, c=2_434.28, v=60.3066)
    collector = make_collector(tmp_path, venue, settle_ms=2_500)
    try:
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 0
        assert "SETTLE_DEFERRED" in events(collector)

        venue.server_time_ms = T0 + MINUTE_MS + 3_000
        collector.poll()
        assert len(collector.stores["BTCUSDT"]) == 1
        stored = collector.stores["BTCUSDT"].bars()[-1]
        assert stored.low == 2_434.27 and stored.close == 2_434.28
    finally:
        collector.close()


def test_a_revised_closed_minute_blocks_and_never_rewrites_the_store(tmp_path: Path) -> None:
    venue = ScriptedVenue(server_time_ms=T0 + 2 * MINUTE_MS + 5_000)
    venue.add(T0, o=2_435.46, h=2_435.63, low=2_434.27, c=2_434.28, v=60.3066)
    collector = make_collector(tmp_path, venue)
    try:
        collector.poll()
        store_path = tmp_path / "market" / "BTCUSDT.jsonl"
        before = store_path.read_bytes()
        first = collector.stores["BTCUSDT"].bars()[-1]

        # El mismo minuto llega de nuevo con otro mínimo y otro cierre.
        venue.add(T0, o=2_435.46, h=2_435.63, low=2_434.02, c=2_434.02, v=60.9785)
        venue.server_time_ms = T0 + 3 * MINUTE_MS
        collector.poll()

        after = store_path.read_bytes()
        assert after == before, "un byte distinto sería una historia reescrita"
        assert collector.stores["BTCUSDT"].bars()[-1] == first
        assert "DUPLICATE_CONFLICT" in events(collector)
        assert not collector.health_at(T0 + 3 * MINUTE_MS)["BTCUSDT"].tradeable
    finally:
        collector.close()


def test_the_quote_wait_is_measured_from_the_answer_not_from_the_close() -> None:
    """``quote_lag`` y ``delivery_latency`` miden esperas distintas; sumarlas es el total."""

    close_ms = T0 + MINUTE_MS
    received_at = close_ms + 2_956  # retardo de entrega medido en la sesión 003G
    quote = Quote(symbol="BTC/USDT", ts_ms=close_ms + 30_000, price=82_884.01, source="minute_1m")

    decision = schedule(quote, received_at_ms=received_at, decision_ts_ms=T0 - 1, max_age_ms=300_000)

    assert decision.status == "FILL"
    assert decision.lag_ms == quote.ts_ms - received_at == 27_044
    assert quote.ts_ms - close_ms == decision.lag_ms + 2_956
    assert information_ms(T0, MINUTE_MS, 2_956) == close_ms + 2_956 == received_at


def test_a_quote_from_before_the_answer_waits_instead_of_filling() -> None:
    """La protección no se relaja para conseguir rellenos: sin precio posterior, se espera."""

    quote = Quote(symbol="BTC/USDT", ts_ms=T0, price=100.0, source="minute_1m")
    decision = schedule(
        quote, received_at_ms=T0 + 5_000, decision_ts_ms=T0 - 1_000, max_age_ms=300_000
    )
    assert decision.status == "WAIT"
