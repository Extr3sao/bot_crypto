"""El feed de 1 minuto: qué puede probar y qué se niega a firmar.

``ContinuousFeed`` en ``test_open_phase_causality.py`` demuestra que el carril acepta una
prueba de cobertura; no demuestra que exista una fuente capaz de producirla. Estos tests
usan klines reales de Binance (1 minuto, públicas, sin credenciales) para cubrir esa mitad:

* cobertura de una hora ausente sólo si los 60 minutos existen y son consecutivos;
* rechazo —no aproximación— cuando falta un minuto, cuando el intervalo no es de minutos
  o cuando el símbolo no está en el feed;
* ninguna cotización anterior al instante pedido;
* el carril ejecuta el hueco con el feed y lo sigue rechazando sin él.

El fichero de datos se versiona con su sha256 en ``SOURCE_MANIFEST.json``; si alguien lo
sustituye, el test de integridad falla antes que cualquier conclusión.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.execution import BAR_OPEN_SOURCE, CoverageProof, Quote, schedule
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import (
    FEED_NAME,
    MINUTE_MS,
    MinuteBarQuoteFeed,
    MinuteSeries,
    QuoteFeedIntegrityError,
)
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "quote-feed-1m"
#: Lunes 2021-01-04 00:00 UTC: el primer lunes del dataset de 1 h que usa el Bloque C.
START_MS = int(datetime(2021, 1, 4, tzinfo=UTC).timestamp() * 1000)
HOUR_MS = 3_600_000
SYMBOL = "UNI/USDT"
FILE_SYMBOL = "UNIUSDT"

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":1.0,'
    '"invalidation":null,"rationale":"Continuation."}'
)


def feed(**kwargs: object) -> MinuteBarQuoteFeed:
    return MinuteBarQuoteFeed.from_directory(
        DATA, aliases={FILE_SYMBOL: SYMBOL}, symbols=[SYMBOL], **kwargs  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------- integrity


def test_the_committed_minutes_are_the_bytes_the_manifest_names():
    manifest = json.loads((DATA / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    record = manifest["symbols"][FILE_SYMBOL]
    path = DATA / record["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["file_sha256"]
    loaded = MinuteSeries.from_rows(
        SYMBOL, json.loads(path.read_text(encoding="utf-8"))
    )
    assert len(loaded.bars) == record["rows"]
    assert loaded.digest == record["series_sha256"]
    assert int(loaded.bars[0].ts_ms) == record["first_minute_ms"]
    assert int(loaded.bars[-1].ts_ms) == record["last_minute_ms"]


def test_the_feed_is_not_the_replays_own_bar_source():
    """Una prueba que se llama ``bar_open`` no es independiente y el contrato la rechaza."""

    proof = CoverageProof(
        symbol=SYMBOL,
        missing_bar_open_ms=START_MS,
        source=BAR_OPEN_SOURCE,
        quotes=(Quote(SYMBOL, START_MS + MINUTE_MS, 1.0), Quote(SYMBOL, START_MS + 2 * MINUTE_MS, 1.0)),
        venue_open=True,
    )
    accepted, reason = proof.covers(HOUR_MS)
    assert not accepted and "other than" in reason
    assert feed().name != BAR_OPEN_SOURCE


def test_an_unsorted_or_duplicated_series_is_corrupt_not_sparse():
    rows = [
        [START_MS, 1.0, 1.1, 0.9, 1.0, 10.0],
        [START_MS + MINUTE_MS, 1.0, 1.1, 0.9, 1.0, 10.0],
        [START_MS + MINUTE_MS, 1.0, 1.1, 0.9, 1.0, 10.0],
    ]
    with pytest.raises(QuoteFeedIntegrityError, match="unsorted or duplicated"):
        MinuteSeries.from_rows(SYMBOL, rows)


def test_ohlc_must_be_inside_its_own_range():
    rows = [[START_MS, 1.0, 0.5, 0.4, 1.0, 10.0]]
    with pytest.raises(QuoteFeedIntegrityError, match="outside its own high/low"):
        MinuteSeries.from_rows(SYMBOL, rows)


def test_a_symbol_absent_from_the_feed_is_not_answered_by_another():
    with pytest.raises(KeyError, match="would prove the wrong thing"):
        feed().series("BTC/USDT")


# -------------------------------------------------------------------- coverage


def test_a_real_missing_hour_is_proven_by_its_sixty_real_minutes():
    missing = START_MS + 21 * HOUR_MS
    quote_feed = feed()
    proof = quote_feed.prove_coverage(SYMBOL, missing, HOUR_MS)
    assert proof is not None
    assert proof.source == FEED_NAME
    assert proof.venue_open is True
    assert len(proof.quotes) == 60
    assert proof.quotes[0].ts_ms == missing
    assert proof.quotes[-1].ts_ms == missing + 59 * MINUTE_MS
    assert all(quote.ts_ms < missing + HOUR_MS for quote in proof.quotes)
    accepted, _ = proof.covers(HOUR_MS)
    assert accepted


def test_one_missing_minute_is_not_coverage():
    """Rechazo, no interpolación: la prueba exige la rejilla completa."""

    missing = START_MS + 21 * HOUR_MS
    series = feed().series(SYMBOL)
    holed = MinuteSeries(
        symbol=SYMBOL,
        bars=tuple(bar for bar in series.bars if int(bar.ts_ms) != missing + 30 * MINUTE_MS),
    )
    quote_feed = MinuteBarQuoteFeed({SYMBOL: holed})
    covered, reason = quote_feed.explain_coverage(SYMBOL, missing, HOUR_MS)
    assert not covered and "59/60" in reason
    assert quote_feed.prove_coverage(SYMBOL, missing, HOUR_MS) is None


def test_an_interval_that_is_not_whole_minutes_cannot_be_proven():
    covered, reason = feed().explain_coverage(SYMBOL, START_MS, HOUR_MS + 1)
    assert not covered and "not a whole number of minutes" in reason
    assert feed().prove_coverage(SYMBOL, START_MS, 90_000) is None


def test_an_hour_outside_the_archive_is_not_proven():
    quote_feed = feed()
    assert quote_feed.prove_coverage(SYMBOL, START_MS + 5000 * HOUR_MS, HOUR_MS) is None


# ---------------------------------------------------------------- first quote


def test_the_first_quote_is_never_older_than_the_instant_asked_for():
    quote_feed = feed()
    target = START_MS + 21 * HOUR_MS + 30 * MINUTE_MS + 1
    quote = quote_feed.first_quote_at_or_after(SYMBOL, target, horizon_ms=HOUR_MS)
    assert quote is not None
    assert quote.ts_ms >= target
    assert quote.ts_ms - target <= MINUTE_MS
    assert quote.price > 0
    assert quote.source == FEED_NAME


def test_the_horizon_is_respected_and_zero_is_not_an_unbounded_window():
    quote_feed = feed()
    assert quote_feed.first_quote_at_or_after(SYMBOL, START_MS, horizon_ms=MINUTE_MS) is not None
    assert quote_feed.first_quote_at_or_after(
        SYMBOL, quote_feed.series(SYMBOL).stamps[-1] + 1, horizon_ms=HOUR_MS
    ) is None
    with pytest.raises(ValueError, match="not 'any horizon'"):
        quote_feed.first_quote_at_or_after(SYMBOL, START_MS, horizon_ms=0)


# ------------------------------------------------------------------ lane wiring


#: Cuatro horas aisladas, no contiguas: un hueco de una sola barra es el único que el
#: contrato acepta probar (dos seguidas no son una interrupción puntual). Con cadencia 1
#: caen en el camino de cuatro opiniones distintas.
EXPECTED_FILL_BARS = (21, 26, 31, 36)


def flat_hours(*, count: int = 40, remove: tuple[int, ...] = ()) -> list[Bar]:
    bars = [
        Bar(
            ts_ms=START_MS + index * HOUR_MS,
            open=100.0,
            high=100.1,
            low=99.9,
            close=100.0,
            volume=10.0,
        )
        for index in range(count)
    ]
    return [bar for index, bar in enumerate(bars) if index not in set(remove)]


class ScriptedProvider(ReplayProvider):
    def __init__(self, latency_ms: int = 0) -> None:
        super().__init__(lambda request: LONG % request.chart.symbol)
        self._latency_ms = latency_ms

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        return replace(super().analyze(request), latency_ms=self._latency_ms)


def vision_config(**overrides: object):
    base = load_vision_config(env={})
    lane = base.lane.__class__(
        timeframe="1h",
        window_bars=20,
        decision_every_bars=1,
        max_calls_per_run=200,
        max_estimated_spend_usd=10.0,
        **overrides,  # type: ignore[arg-type]
    )
    return base.__class__(provider=base.provider, lane=lane)


def run_lane(
    path: Path, *, series: list[Bar], quote_feed=None, latency_ms: int = 0, **overrides: object
):
    lane = VisionLane(
        series={SYMBOL: series},
        provider=ScriptedProvider(latency_ms=latency_ms),
        config=vision_config(**overrides),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=path / "decisions.jsonl",
        quote_feed=quote_feed,
    )
    summary = lane.run()
    rows = [
        dict(line["entry"], seq=line["seq"])
        for line in read_entries(path / "decisions.jsonl")
    ]
    return summary, rows


def test_the_lane_still_refuses_the_hole_without_a_feed(tmp_path):
    #: 900 ms, no cero: con latencia cero la primera opinión rellena en la apertura de su
    #: propia vela y el hueco nunca llega a estar en el camino. La latencia es lo que hace
    #: que la barra esperada sea la ausente.
    summary, rows = run_lane(
        tmp_path, series=flat_hours(remove=EXPECTED_FILL_BARS), latency_ms=900
    )
    rejects = [
        row
        for row in rows
        if row.get("kind") == "GUARD_REJECT" and row.get("code") == "DATA_GAP"
    ]
    assert rejects and rejects[0]["missing_bar_open_ms"] == START_MS + 21 * HOUR_MS
    #: DEF-RUN-016: esta prueba afirmaba `fills == 0`, y ese cero no medía el guard: medía
    #: el defecto. Con cadencia 1, toda opinión era sustituida en el cierre siguiente antes
    #: de que su apertura fuese leída, así que ninguna operación podía existir. La propiedad
    #: que importa es la que sigue: ninguna posición se abre en un camino que cruce un
    #: hueco. Un relleno en un tramo contiguo es legítimo y no necesita feed que lo firme.
    fills = [row for row in rows if row.get("kind") == "FILL"]
    assert summary["fills"] == len(fills)
    holes = {START_MS + index * HOUR_MS for index in EXPECTED_FILL_BARS}
    for fill in fills:
        opened_after_decision = int(fill["decision_bar_open_ms"]) + HOUR_MS
        crossed = [
            stamp for stamp in holes if opened_after_decision <= stamp <= int(fill["quote_ts_ms"])
        ]
        assert crossed == [], f"fill at {fill['quote_ts_ms']} crosses the hole(s) {crossed}"


def test_the_real_feed_unlocks_the_holes_it_proves(tmp_path):
    #: La ventana es de **dos** barras a propósito. Un hueco cuesta exactamente una barra de
    #: edad de la opinión: su primer precio posible pasa a ser el siguiente que existe. Con
    #: la ventana de una barra el veredicto honesto es la expiración
    #: (``test_a_covered_hole_still_obeys_the_opinion_window``); lo que este test mide es la
    #: otra mitad: cuando la ventana lo absorbe, el feed convierte el hueco en operación.
    summary, rows = run_lane(
        tmp_path,
        series=flat_hours(remove=EXPECTED_FILL_BARS),
        quote_feed=feed(),
        latency_ms=900,
        max_opinion_age_ms=2 * HOUR_MS,
    )
    fills = [row for row in rows if row.get("kind") == "FILL"]
    assert summary["fills"] == len(fills) >= 1
    for fill in fills:
        assert fill["quote_ts_ms"] >= fill["received_at_ms"]
        assert fill["data_gap_covered_by"] == FEED_NAME
        assert fill["data_gap_missing_bar_open_ms"] in {
            START_MS + index * HOUR_MS for index in EXPECTED_FILL_BARS
        }
    assert not [
        row for row in rows if row.get("kind") == "GUARD_REJECT" and row.get("code") == "DATA_GAP"
    ]


def test_a_proven_hole_still_costs_one_bar_of_opinion_age(tmp_path):
    """La cobertura ejecuta el hueco; no lo abarata.

    Una orden cuyo primer precio posible es el que **sigue** al hueco llega dos barras
    después de su decisión. Con la ventana de una barra el veredicto es la expiración: el
    feed demuestra que el mercado siguió cotizando, no que la opinión siga siendo actual.
    Se comprueba en el carril para que el aplazamiento no pueda confundirse con una
    sustitución silenciosa ni con un relleno a precio viejo.
    """

    _, rows = run_lane(
        tmp_path,
        series=flat_hours(remove=EXPECTED_FILL_BARS),
        quote_feed=feed(),
        latency_ms=900,
    )

    expired = [
        row
        for row in rows
        if row.get("kind") == "GUARD_REJECT" and row.get("code") == "LATE_RESPONSE"
    ]
    assert expired, "the order held behind the hole must expire with a row, not vanish"
    assert all(int(row["opinion_age_ms"]) > int(row["max_opinion_age_ms"]) for row in expired)
    holes = {START_MS + index * HOUR_MS for index in EXPECTED_FILL_BARS}
    for fill in (row for row in rows if row.get("kind") == "FILL"):
        crossed = [
            hole
            for hole in holes
            if int(fill["decision_bar_open_ms"]) + HOUR_MS <= hole <= int(fill["quote_ts_ms"])
        ]
        assert crossed == [], f"an expired opinion cannot reappear as a fill on {crossed}"
    assert not [row for row in rows if row.get("code") == "DATA_GAP"], (
        "the feed did prove this hole; the refusal it earns is the clock's, not the guard's"
    )


def test_the_lane_never_uses_the_minute_feed_as_an_entry_price(tmp_path):
    """El feed prueba continuidad; la cotización sigue siendo una apertura de vela."""

    _, rows = run_lane(
        tmp_path,
        series=flat_hours(remove=EXPECTED_FILL_BARS),
        quote_feed=feed(),
        latency_ms=900,
        max_opinion_age_ms=2 * HOUR_MS,
    )
    fill = next(row for row in rows if row.get("kind") == "FILL")
    assert fill["quote_source"] == "bar_open"
    assert fill["quote_ts_ms"] == fill["data_gap_missing_bar_open_ms"] + HOUR_MS


def test_a_feed_without_that_hour_does_not_unlock_it(tmp_path):
    """Un feed real pero ciego a esa hora no puede convertir el hueco en operación."""

    series = flat_hours(remove=EXPECTED_FILL_BARS)
    shifted = [
        Bar(ts_ms=bar.ts_ms + 5000 * HOUR_MS, open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume)
        for bar in series
    ]
    summary, rows = run_lane(tmp_path, series=shifted, quote_feed=feed())
    assert summary["fills"] == 0
    assert [row for row in rows if row.get("code") == "DATA_GAP"]


def test_a_covered_hole_still_obeys_the_opinion_window(tmp_path):
    """Cubrir el hueco no autoriza una respuesta rancia: el reloj sigue mandando."""

    quote_feed = feed()
    quote = quote_feed.first_quote_at_or_after(
        SYMBOL, START_MS + 21 * HOUR_MS + HOUR_MS + 1, horizon_ms=2 * HOUR_MS
    )
    assert quote is not None
    decision_ts = START_MS + 21 * HOUR_MS
    outcome = schedule(
        quote,
        received_at_ms=decision_ts + HOUR_MS,
        decision_ts_ms=decision_ts,
        max_age_ms=HOUR_MS,
    )
    assert outcome.status == "EXPIRED"
