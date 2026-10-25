"""Ejecución sub-bar: el primer minuto posterior a la respuesta, sin mirar hacia atrás.

El Bloque C dejó probado que el carril no puede rellenar en un precio anterior a la
respuesta y que, con una rejilla de 1 h, una latencia real cuesta una barra entera de
espera. El WP-003D añadió el feed de 1 minuto, pero sólo como **prueba de cobertura**: la
entrada seguía pagando la apertura de 1 h. Este bloque cierra la mitad que faltaba.

Cuatro defectos, cada uno con su test:

* **S-01** una respuesta de 900 ms sigue esperando 59 minutos porque el único precio
  ejecutable era una apertura de vela;
* **S-02** sin `subbar_entries=True` el comportamiento publicado no debe cambiar: la
  capacidad es opt-in y el default sigue intacto;
* **S-03** si se rellena dentro de una vela, el rango de *esa* vela no puede usarse
  entero: el high/low anterior al relleno es look-ahead. El rango del stop se limita a
  los minutos **posteriores** al relleno;
* **S-04** un feed que devuelve un precio anterior a la respuesta no se usa: se rechaza
  con `FEED_CONTRACT_VIOLATION` en vez de rellenar antes de que la pregunta existiera.

Se ataca el runtime real (`VisionLane.run`, `RiskManager` y `PaperBroker` de producción);
el único doble es la fuente de datos, que es lo que se está probando.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.execution import Quote, QuoteRange
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import MINUTE_MS, MinuteBarQuoteFeed
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "quote-feed-1m"
HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000
SYMBOL = "BTC/USDT"

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":0.5,"take_profit_pct":0.75,'
    '"invalidation":null,"rationale":"Continuation."}'
)

#: La primera decisión con `decision_every=15` y `window_bars=30` cae en el índice 30 y
#: se ejecuta en la barra 31. Con latencia de 900 ms, el instante de respuesta es la
#: apertura de la barra 31 más 900 ms: el primer minuto posterior es el minuto 1.
DECISION_BAR = 30
FILL_BAR = 31
LATENCY_MS = 900


class LatencyProvider(ReplayProvider):
    def __init__(self, answers: list[str], *, latency_ms: int) -> None:
        super().__init__(list(answers))
        self._latency_ms = latency_ms

    def analyze(self, request):  # type: ignore[override]
        response: VisionResponse = super().analyze(request)  # type: ignore[arg-type]
        from dataclasses import replace

        return replace(response, latency_ms=self._latency_ms)


MinutePatch = Callable[[int, int, tuple[float, float, float, float]], tuple[float, float, float, float]]


class SyntheticMinutes:
    """Un feed de 1 minuto declarado, con OHLC por minuto que el test controla.

    No sustituye al contrato del runtime: implementa ``first_quote_at_or_after`` y
    ``range_between`` exactamente como el feed real, para que la prueba sea del carril y
    no del doble.
    """

    name = "synthetic_minute_feed"

    def __init__(self, series: dict[str, list[Bar]], patches: dict[tuple[int, int], MinutePatch] | None = None) -> None:
        self._bars: dict[str, list[Bar]] = {}
        self._patches = patches or {}
        for symbol, hours in series.items():
            minutes: list[Bar] = []
            for hour_index, bar in enumerate(hours):
                for minute in range(60):
                    quadruple = (float(bar.open), float(bar.open), float(bar.open), float(bar.open))
                    patch = self._patches.get((hour_index, minute))
                    if patch is not None:
                        quadruple = patch(hour_index, minute, quadruple)
                    open_price, high, low, close = quadruple
                    minutes.append(
                        Bar(
                            ts_ms=int(bar.ts_ms) + minute * MINUTE_MS,
                            open=open_price,
                            high=high,
                            low=low,
                            close=close,
                            volume=1.0,
                        )
                    )
            self._bars[symbol] = minutes

    def first_quote_at_or_after(self, symbol: str, ts_ms: int, *, horizon_ms: int) -> Quote | None:
        for bar in self._bars[symbol]:
            if int(bar.ts_ms) >= int(ts_ms):
                if int(bar.ts_ms) - int(ts_ms) > int(horizon_ms):
                    return None
                return Quote(
                    symbol=symbol,
                    ts_ms=int(bar.ts_ms),
                    price=float(bar.open),
                    source=self.name,
                )
        return None

    def range_between(self, symbol: str, after_ms: int, until_ms: int) -> QuoteRange | None:
        rows = [b for b in self._bars[symbol] if int(after_ms) < int(b.ts_ms) < int(until_ms)]
        if not rows:
            return None
        return QuoteRange(
            symbol=symbol,
            after_ms=int(after_ms),
            until_ms=int(until_ms),
            minutes=len(rows),
            high=max(float(b.high) for b in rows),
            low=min(float(b.low) for b in rows),
            last=float(rows[-1].close),
            source=self.name,
        )


def build_series(*, count: int = 96, patch: dict[int, tuple] | None = None) -> list[Bar]:
    """Tendencia suave; el test decide qué barras tienen forma hostil o benigna."""

    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = open_price * 1.0002
        high = max(open_price, close) * 1.001
        low = min(open_price, close) * 0.999
        if patch and index in patch:
            open_price, high, low, close = patch[index]
        bars.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=200.0,
            )
        )
        price = close
    return bars


def policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def vision_config():
    base = load_vision_config(env={})
    lane = base.lane.__class__(
        timeframe="1h",
        window_bars=30,
        decision_every_bars=15,
        max_calls_per_run=20,
        max_estimated_spend_usd=5.0,
    )
    return base.__class__(provider=base.provider, lane=lane)


def run_lane(
    tmp_path: Path,
    *,
    bars: list[Bar],
    feed=None,
    subbar: bool = True,
    latency_ms: int = LATENCY_MS,
    name: str = "sub-bar",
):
    lane = VisionLane(
        series={SYMBOL: bars},
        provider=LatencyProvider([LONG] * 40, latency_ms=latency_ms),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / f"{name}.jsonl",
        book_id=f"ai-vision-paper-{name}",
        quote_feed=feed,
        subbar_entries=subbar,
    )
    summary = lane.run()
    rows = [dict(row["entry"], seq=row["seq"]) for row in read_entries(tmp_path / f"{name}.jsonl")]
    return summary, rows


def of_kind(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row.get("kind") == kind]


# -- S-01: el relleno ocurre en el primer minuto posterior a la respuesta -----------


def test_a_sub_bar_latency_fills_at_the_first_minute_after_the_answer(tmp_path):
    bars = build_series()
    feed = SyntheticMinutes({SYMBOL: bars})
    summary, rows = run_lane(tmp_path, bars=bars, feed=feed)

    fills = of_kind(rows, "FILL")
    assert fills, summary
    first = fills[0]
    assert first["quote_source"] == feed.name
    assert first["entry_quote_source"] == feed.name
    assert first["quote_ts_ms"] >= first["received_at_ms"]
    #: El instante de respuesta es la apertura de la barra 30 + 900 ms; el primer minuto
    #: posterior es el minuto 1 de esa hora.
    assert first["quote_ts_ms"] == bars[FILL_BAR].ts_ms + MINUTE_MS
    assert first["quote_lag_ms"] < MINUTE_MS
    report = summary["execution"]
    assert report["entry_quote_sources"] == {feed.name: len(fills)}
    assert report["sub_bar_fills"] == len(fills)
    assert summary["reconciliation"]["identities"]["every_fill_pays_at_or_after_its_answer"]


# -- S-02: el default publicado no cambia -------------------------------------------


def test_without_the_flag_the_published_bar_open_behaviour_is_unchanged(tmp_path):
    bars = build_series()
    feed = SyntheticMinutes({SYMBOL: bars})
    summary, rows = run_lane(tmp_path, bars=bars, feed=feed, subbar=False, name="bar-open")

    fills = of_kind(rows, "FILL")
    assert fills, summary
    first = fills[0]
    assert first["quote_source"] == "bar_open"
    assert first["entry_quote_source"] == "bar_open"
    #: La apertura de la barra de relleno precede a la respuesta (por eso espera); la
    #: primera apertura posterior es la de la barra siguiente.
    assert first["quote_ts_ms"] == bars[FILL_BAR + 1].ts_ms
    assert summary["execution"]["sub_bar_fills"] == 0
    assert summary["execution"]["entry_quote_sources"] == {"bar_open": len(fills)}


# -- S-03: el rango de la vela de entrada empieza en el relleno ----------------------


def test_a_pre_fill_low_does_not_stop_a_position_that_opened_later_in_the_bar(tmp_path):
    """El minuto 0 de la barra de relleno clava el stop; los minutos posteriores no.

    Un motor que use el low completo de la barra cerraría la posición con un precio que
    ocurrió **antes** de que la posición existiera. El carril debe usar sólo los minutos
    posteriores al relleno y declarar de dónde salió el rango.
    """

    hostile_minute_zero = (100.0, 100.0, 98.0, 100.0)
    benign_after = (100.0, 100.2, 99.9, 100.0)

    def patch(hour_index: int, minute: int, quad: tuple[float, float, float, float]):
        if hour_index != FILL_BAR:
            return quad
        return hostile_minute_zero if minute == 0 else benign_after

    bars = build_series(
        patch={
            FILL_BAR: (100.0, 100.2, 98.0, 100.0),
            FILL_BAR + 1: (100.0, 100.2, 99.9, 100.1),
        }
    )
    feed = SyntheticMinutes({SYMBOL: bars}, patches={(FILL_BAR, m): patch for m in range(60)})
    summary, rows = run_lane(tmp_path, bars=bars, feed=feed)

    fills = of_kind(rows, "FILL")
    assert fills and fills[0]["quote_ts_ms"] == bars[FILL_BAR].ts_ms + MINUTE_MS
    fill = fills[0]
    assert fill["entry_bar_range_from_ms"] == fill["quote_ts_ms"]
    #: El minuto 0 (low 98) queda fuera: el rango declarado es el de los minutos 2..59.
    assert fill["entry_bar_range_minutes"] == 58
    assert fill["entry_bar_range_low"] == pytest.approx(99.9)
    assert fill["entry_bar_range_high"] == pytest.approx(100.2)
    closed_on_that_bar = [
        row
        for row in of_kind(rows, "CLOSE")
        if row["exit_ts_lower_bound_ms"] == bars[FILL_BAR].ts_ms
    ]
    assert closed_on_that_bar == [], closed_on_that_bar
    assert summary["reconciliation"]["identities"]["every_fill_pays_at_or_after_its_answer"]


def test_a_post_fill_low_still_stops_the_position(tmp_path):
    """La exclusión del minuto de relleno no puede convertirse en inmunidad al stop."""

    def patch(hour_index: int, minute: int, quad: tuple[float, float, float, float]):
        if hour_index != FILL_BAR:
            return quad
        if minute <= 1:
            return (100.0, 100.1, 99.9, 100.0)
        return (100.0, 100.1, 99.0, 99.2)

    bars = build_series(patch={FILL_BAR: (100.0, 100.1, 99.0, 99.2), FILL_BAR + 1: (99.2, 99.5, 99.0, 99.3)})
    feed = SyntheticMinutes({SYMBOL: bars}, patches={(FILL_BAR, m): patch for m in range(60)})
    summary, rows = run_lane(tmp_path, bars=bars, feed=feed, name="stop")

    closes = of_kind(rows, "CLOSE")
    assert closes, summary
    stop_closes = [row for row in closes if row["exit_reason"] == "stop_loss"]
    assert stop_closes, closes
    closed = stop_closes[0]
    assert closed["exit_ts_resolution"] == "BAR_WINDOW"
    assert closed["exit_ts_lower_bound_ms"] == bars[FILL_BAR].ts_ms


# -- S-04: un feed que miente hacia atrás se rechaza, no se usa ----------------------


class LyingMinutes(SyntheticMinutes):
    """Devuelve un precio anterior al instante pedido: el contrato lo prohíbe."""

    def first_quote_at_or_after(self, symbol: str, ts_ms: int, *, horizon_ms: int) -> Quote | None:
        return Quote(
            symbol=symbol,
            ts_ms=int(ts_ms) - MINUTE_MS,
            price=100.0,
            source=self.name,
        )


def test_a_feed_that_answers_before_the_question_is_rejected(tmp_path):
    bars = build_series()
    feed = LyingMinutes({SYMBOL: bars})
    summary, rows = run_lane(tmp_path, bars=bars, feed=feed, name="lying")

    fills = of_kind(rows, "FILL")
    assert all(row["quote_ts_ms"] >= row["received_at_ms"] for row in fills)
    assert summary["counters"].get("guard:FEED_CONTRACT_VIOLATION", 0) >= 1
    rejected = [row for row in rows if row.get("code") == "FEED_CONTRACT_VIOLATION"]
    assert rejected, rows[:3]


# -- el contrato del feed real, no un doble ------------------------------------------


def test_the_real_feed_range_excludes_the_fill_minute_and_reads_only_after():
    feed = MinuteBarQuoteFeed.from_directory(
        DATA, aliases={"UNIUSDT": "UNI/USDT"}, symbols=["UNI/USDT"]
    )
    series = feed.series("UNI/USDT")
    start = int(series.bars[100].ts_ms)
    span = feed.range_between("UNI/USDT", start, start + 3 * MINUTE_MS)
    assert span is not None
    assert span.minutes == 2
    assert span.high == max(float(series.bars[101].high), float(series.bars[102].high))
    assert span.low == min(float(series.bars[101].low), float(series.bars[102].low))
    assert span.last == float(series.bars[102].close)
    empty = feed.range_between("UNI/USDT", start, start + MINUTE_MS)
    assert empty is None
