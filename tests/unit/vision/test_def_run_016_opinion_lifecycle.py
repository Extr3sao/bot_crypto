"""DEF-RUN-016 — una opinión que aún puede ejecutarse no se sustituye por otra que no.

El defecto observado en la sesión real ``model-20261020T170635Z``: 12 decisiones, 6
accionables y **0 rellenos**. Cinco de esas seis opiniones murieron con
``SUPERSEDED_BY_NEWER_OPINION`` y la sexta la paró el guard de coste. El pipeline no tenía
un problema de umbrales: destruía su propia señal un instante antes de poder usarla.

La causa es de orden, no de política. Una opinión formada en el cierre de la vela *k*
responde en ``cierre + latencia``, así que su primera cotización ejecutable es la apertura
de la vela *k+1*. En ese mismo instante —``close_ms``— el carril formaba la decisión
siguiente y sustituía la orden en espera **antes** de que la apertura fuese leída. La
opinión que sí podía pagar ese precio se destruía con otra cuya respuesta llega *después*
de ese mismo precio y que, por tanto, nunca podría usarlo.

Estos tests fijan el contrato que lo impide y, a la vez, los límites que no se relajan:

1. una opinión cuya primera apertura ejecutable es este instante **aplaza** la decisión
   (no se paga, no se cuenta como opinión) y se ejecuta en esa apertura;
2. el relleno sigue pagando un precio ``>= received_at`` y con edad ``<= TTL``: aplazar no
   es comprar datos viejos, y un TTL corto sigue venciendo la opinión en la apertura;
3. cuando la orden en espera **no** puede ejecutarse en este instante (hueco en los
   datos), la sustitución por una opinión nueva sigue ocurriendo como antes, y el camino
   que cruza el hueco se rechaza con ``DATA_GAP``;
4. la contabilidad del ciclo de vida cuadra: cada opinión generada termina en relleno,
   bloqueo de riesgo, expiración, sustitución o pendiente al final — ni una más, ni una
   menos — y las latencias por etapa se publican con sus muestras.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.execution import Quote, QuoteRange
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import MINUTE_MS
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
START_MS = 1_792_500_000_000
MINUTE = MINUTE_MS

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
    '"invalidation":null,"rationale":"Continuation."}'
)
NO_TRADE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"NO_TRADE",'
    '"confidence":0.5,"horizon_bars":8,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"Nothing to do."}'
)


class LatencyProvider(ReplayProvider):
    """Respuestas guionizadas con la latencia declarada en el reloj del proveedor."""

    def __init__(self, answers: list[str], *, latency_ms: int) -> None:
        super().__init__(list(answers))
        self._latency_ms = latency_ms
        self.answered = 0

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        self.answered += 1
        response: VisionResponse = super().analyze(request)  # type: ignore[arg-type]
        return replace(response, latency_ms=self._latency_ms)


class Minutes:
    """Feed de 1 minuto con el contrato real, para que el test sea del carril."""

    name = "def_run_016_minutes"

    def __init__(self, bars: list[Bar]) -> None:
        self._minutes: list[Bar] = []
        for bar in bars:
            for minute in range(60):
                self._minutes.append(
                    Bar(
                        ts_ms=int(bar.ts_ms) + minute * MINUTE,
                        open=float(bar.open),
                        high=float(bar.open),
                        low=float(bar.open),
                        close=float(bar.open),
                        volume=1.0,
                    )
                )

    def first_quote_at_or_after(
        self, symbol: str, ts_ms: int, *, horizon_ms: int
    ) -> Quote | None:
        for bar in self._minutes:
            if int(bar.ts_ms) >= int(ts_ms):
                if int(bar.ts_ms) - int(ts_ms) > int(horizon_ms):
                    return None
                return Quote(symbol=symbol, ts_ms=int(bar.ts_ms), price=float(bar.open), source=self.name)
        return None

    def range_between(self, symbol: str, after_ms: int, until_ms: int) -> QuoteRange | None:
        rows = [b for b in self._minutes if int(after_ms) < int(b.ts_ms) < int(until_ms)]
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


def bars(*, count: int = 40, remove: tuple[int, ...] = (), interval_ms: int = MINUTE) -> list[Bar]:
    out: list[Bar] = []
    for index in range(count):
        if index in set(remove):
            continue
        opened = 100.0 + index * 0.01
        out.append(
            Bar(
                ts_ms=START_MS + index * interval_ms,
                open=opened,
                high=opened * 1.0005,
                low=opened * 0.9995,
                close=opened,
                volume=10.0,
            )
        )
    return out


def policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def vision_config(
    *,
    timeframe: str = "1m",
    window_bars: int = 10,
    decision_every_bars: int = 1,
    max_opinion_age_ms: int = 0,
    data_delay_ms: int = 0,
):
    base = load_vision_config(env={})
    lane = base.lane.__class__(
        timeframe=timeframe,
        window_bars=window_bars,
        decision_every_bars=decision_every_bars,
        max_calls_per_run=200,
        max_estimated_spend_usd=10.0,
        max_opinion_age_ms=max_opinion_age_ms,
        data_delay_ms=data_delay_ms,
    )
    return base.__class__(provider=base.provider, lane=lane)


def run_lane(
    tmp_path: Path,
    *,
    series: list[Bar],
    latency_ms: int,
    answers: list[str] | None = None,
    feed: bool = True,
    **config: object,
):
    provider = LatencyProvider(answers or [LONG] * 400, latency_ms=latency_ms)
    lane = VisionLane(
        series={SYMBOL: series},
        provider=provider,
        config=vision_config(**config),  # type: ignore[arg-type]
        risk_policy=policy(),
        ledger_path=tmp_path / "decisions.jsonl",
        quote_feed=Minutes(series) if feed else None,
        subbar_entries=True,
    )
    summary = lane.run()
    rows = [
        dict(line["entry"], seq=line["seq"])
        for line in read_entries(tmp_path / "decisions.jsonl")
    ]
    return summary, rows, provider


def of_kind(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row.get("kind") == kind]


# -- 1. la opinión ejecutable no se sustituye por una que aún no existe -------------


def test_a_waiting_opinion_gets_the_open_instead_of_being_superseded(tmp_path):
    """La sesión real: latencia 30 s sobre velas de 60 s, cadencia 1, cero rellenos."""
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)

    assert summary["fills"] >= 1, (
        "with 30 s of latency on a 60 s grid the opinion's first executable open is the "
        f"next one; the lane must price it instead of replacing it; counters={summary['counters']}"
    )
    assert of_kind(rows, "OPINION_DEFERRED"), (
        "the slot that was spent waiting must be recorded, not silently skipped"
    )
    assert of_kind(rows, "GUARD_REJECT") == [] or not [
        row for row in of_kind(rows, "GUARD_REJECT")
        if row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ], "an opinion that can still be priced is not superseded by one that cannot"


def test_the_deferral_names_the_instant_the_order_will_be_priced(tmp_path):
    _, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)

    deferred = of_kind(rows, "OPINION_DEFERRED")
    fills = of_kind(rows, "FILL")
    assert deferred and fills

    by_decision = {int(row["decision_seq"]): row for row in fills}
    matched = [
        row
        for row in deferred
        if int(row["decision_seq"]) in by_decision
        and by_decision[int(row["decision_seq"])]["quote_ts_ms"]
        == int(row["next_executable_open_ms"])
    ]
    assert matched, (
        "the row must name the open the order was actually priced at, not an estimate"
    )
    for row in deferred:
        assert row["reason"] == "OPINION_IN_FLIGHT"
        assert int(row["next_executable_open_ms"]) >= int(row["received_at_ms"]), (
            "the named open is the first price at or after the answer"
        )
        assert row["pending_deferrals"] >= 1


def test_a_deferred_slot_is_not_paid_for(tmp_path):
    summary, rows, provider = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)

    decisions = of_kind(rows, "DECISION")
    assert provider.answered == len(decisions) == summary["calls"], (
        "a slot that is deferred must not make a paid call"
    )
    assert summary["execution"]["opinions"]["deferred_slots"] == len(
        of_kind(rows, "OPINION_DEFERRED")
    )


def test_no_trade_decision_does_not_block_the_next_slot(tmp_path):
    """Una opinión no accionable no está en vuelo: no puede aplazar nada."""
    answers = [LONG, NO_TRADE, LONG, NO_TRADE] + [LONG] * 400
    summary, rows, _ = run_lane(
        tmp_path, series=bars(count=40), latency_ms=30_000, answers=answers
    )

    assert summary["fills"] >= 1
    for row in of_kind(rows, "OPINION_DEFERRED"):
        assert int(row["decision_seq"]) in {int(d["seq"]) for d in of_kind(rows, "DECISION")}


# -- 2. aplazar no es relajar el TTL ------------------------------------------------


def test_the_deferred_opinion_still_pays_a_quote_after_its_answer(tmp_path):
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)

    assert summary["fills"] >= 1
    for fill in of_kind(rows, "FILL"):
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
        assert int(fill["quote_ts_ms"]) > int(fill["decision_ts_ms"])
        assert int(fill["opinion_age_ms"]) <= int(
            summary["execution"]["max_opinion_age_ms"]
        )
        assert int(fill["quote_lag_ms"]) == int(fill["quote_ts_ms"]) - int(
            fill["received_at_ms"]
        )


def test_the_ttl_boundary_is_the_only_thing_that_decides_whether_it_waits(tmp_path):
    """El aplazamiento no compra tiempo: el TTL se mide desde la decisión, al milisegundo."""
    at_the_edge = tmp_path / "edge"
    at_the_edge.mkdir()
    summary, rows, _ = run_lane(
        at_the_edge,
        series=bars(count=40),
        latency_ms=45_000,
        max_opinion_age_ms=60_000,
    )
    assert summary["fills"] >= 1
    fill = of_kind(rows, "FILL")[0]
    assert int(fill["opinion_age_ms"]) == 60_000 == summary["execution"]["max_opinion_age_ms"]

    one_ms_short = tmp_path / "short"
    one_ms_short.mkdir()
    summary, rows, _ = run_lane(
        one_ms_short,
        series=bars(count=40),
        latency_ms=45_000,
        max_opinion_age_ms=59_999,
    )
    assert summary["fills"] == 0, (
        "one millisecond of TTL short of the wait is not a license to trade a stale view"
    )
    assert of_kind(rows, "FILL") == []
    assert of_kind(rows, "OPINION_DEFERRED") == [], (
        "an opinion that is already outside its window is not worth deferring a slot for"
    )


# -- 3. la sustitución legítima sigue existiendo ------------------------------------


def test_within_the_ttl_a_slow_answer_is_waited_for_not_replaced(tmp_path):
    """45 s de latencia sobre velas de 60 s: la apertura siguiente sigue dentro del TTL."""
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=45_000)

    assert summary["fills"] >= 1, (
        "the waiting opinion is still the freshest *existing* view at its quote; it must "
        f"be priced, not replaced; counters={summary['counters']}"
    )
    fill = of_kind(rows, "FILL")[0]
    assert int(fill["quote_ts_ms"]) - int(fill["received_at_ms"]) == 15_000
    assert int(fill["opinion_age_ms"]) <= summary["execution"]["max_opinion_age_ms"]
    assert of_kind(rows, "OPINION_DEFERRED")


def test_a_model_slower_than_its_ttl_cannot_trade_and_does_not_starve_the_slot(tmp_path):
    """90 s de latencia con TTL de 60 s: ninguna opinión es ejecutable y no se retiene."""
    summary, rows, provider = run_lane(tmp_path, series=bars(count=40), latency_ms=90_000)

    assert summary["fills"] == 0, "an opinion older than its window must not be filled"
    superseded = [
        row
        for row in of_kind(rows, "GUARD_REJECT")
        if row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ]
    assert superseded, "the waiting opinion is replaced, and the row says why"
    judged = [row for row in superseded if row["opinion_age_at_next_open_ms"] is not None]
    assert judged, "at least one row must carry the age that made the order obsolete"
    for row in judged:
        assert int(row["opinion_age_at_next_open_ms"]) > int(row["max_opinion_age_ms"]), (
            "the row carries the age that made it obsolete, not a generic verdict"
        )
    assert provider.answered > 3, (
        "a model that cannot trade in time must not freeze the decision slot: the newest "
        "view is still asked for"
    )
    assert not of_kind(rows, "OPINION_DEFERRED"), (
        "an opinion that is already too old is obsolete at birth; deferring decisions for "
        "it would starve the pipeline"
    )


def test_a_fill_never_crosses_a_hole_without_proof(tmp_path):
    """Una orden cuyo camino cruza un hueco no rellena: se rechaza con DATA_GAP."""
    answers = [NO_TRADE, NO_TRADE, LONG] + [NO_TRADE] * 400
    series = bars(count=40, remove=(12,))
    summary, rows, _ = run_lane(
        tmp_path, series=series, latency_ms=30_000, answers=answers, feed=False
    )

    gaps = [row for row in of_kind(rows, "GUARD_REJECT") if row.get("code") == "DATA_GAP"]
    assert gaps, "the hole on the path must be refused, and named"
    assert gaps[0]["missing_bar_open_ms"] == START_MS + 12 * MINUTE
    assert summary["fills"] == 0
    opinions = summary["execution"]["opinions"]
    assert opinions["rejected"].get("DATA_GAP", 0) == len(gaps), (
        "a DATA_GAP termina la opinión, así que tiene que estar en la identidad; si no, "
        "la opinión desaparece del recuento en vez de morir con nombre"
    )
    assert opinions["generated"] == (
        opinions["executed_openings"]
        + opinions["closed_by_intent"]
        + opinions["blocked_by_risk"]
        + opinions["gated"]
        + sum(opinions["rejected"].values())
    ), f"an opinion that ends in DATA_GAP still has to reach a terminal class: {opinions}"
    for fill in of_kind(rows, "FILL"):
        after_decision = int(fill["decision_bar_open_ms"]) + MINUTE
        assert not (
            after_decision <= int(gaps[0]["missing_bar_open_ms"]) <= int(fill["quote_ts_ms"])
        )


# -- 4. contabilidad del ciclo de vida ---------------------------------------------


def test_every_generated_opinion_has_one_terminal_event(tmp_path):
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)
    opinions = summary["execution"]["opinions"]

    assert opinions["generated"] == len(
        [
            row
            for row in of_kind(rows, "DECISION")
            if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}
        ]
    )
    #: Las clases terminales son disjuntas y suman: relleno, cierre por señal, bloqueo del
    #: riesgo, puerta posterior a la aprobación y **todo** ``GUARD_REJECT``. ``expired``,
    #: ``superseded`` y ``pending_at_end`` son vistas de ``rejected``, no sumandos extra.
    terminal = (
        opinions["executed_openings"]
        + opinions["closed_by_intent"]
        + opinions["blocked_by_risk"]
        + opinions["gated"]
        + sum(opinions["rejected"].values())
    )
    assert terminal == opinions["generated"], (
        "an opinion that is born and never reaches a terminal row is the defect this "
        f"block exists to make visible; opinions={opinions}"
    )
    assert opinions["rejected"].get("LATE_RESPONSE", 0) == opinions["expired"]
    assert (
        opinions["rejected"].get("SUPERSEDED_BY_NEWER_OPINION", 0)
        == opinions["superseded"]
    )
    assert (
        opinions["rejected"].get("RUN_ENDED_WITH_ORDER_PENDING", 0)
        == opinions["pending_at_end"]
    )
    assert opinions["blocked_by_risk"] >= 0 and opinions["pending_at_end"] in {0, 1}


def test_a_broker_that_refuses_an_approved_order_still_leaves_a_terminal_row(tmp_path):
    """Aprobada por el riesgo y rechazada por el broker: la opinión muere con nombre.

    Sin fila terminal la opinión desaparecía del ledger, y la identidad se rompía
    precisamente en el caso que un verificador no puede reconstruir desde los bytes.
    """

    series = bars(count=24)
    lane = VisionLane(
        series={SYMBOL: series},
        provider=LatencyProvider([LONG] * 400, latency_ms=0),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / "decisions.jsonl",
        quote_feed=Minutes(series),
        subbar_entries=True,
    )
    lane.broker.execute_signal = lambda signal: None  # type: ignore[method-assign]
    summary = lane.run()
    rows = [
        dict(line["entry"], seq=line["seq"])
        for line in read_entries(tmp_path / "decisions.jsonl")
    ]

    refused = [
        row
        for row in of_kind(rows, "DECISION_OUTCOME")
        if row.get("risk_gate") == "BROKER_REJECTED"
    ]
    assert refused, "the refusal must be a row, not just a counter"
    assert all(row["approved"] is True and row["executed"] is False for row in refused)
    opinions = summary["execution"]["opinions"]
    assert opinions["gated"] == len(refused) == summary["counters"]["broker_rejected"]
    assert opinions["generated"] == (
        opinions["executed_openings"]
        + opinions["closed_by_intent"]
        + opinions["blocked_by_risk"]
        + opinions["gated"]
        + sum(opinions["rejected"].values())
    ), f"a refused order is still a terminal class: {opinions}"


def test_stage_latencies_are_published_with_their_samples(tmp_path):
    summary, _, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)
    stages = summary["execution"]["stage_latency_ms"]

    for name in ("data_to_decision", "decision_to_received", "received_to_quote", "decision_to_quote"):
        block = stages[name]
        assert block["samples"] >= 1, f"{name} has no measured fill to describe"
        assert block["samples"] == summary["fills"]
        assert block["p50"] <= block["p95"] <= block["p99"] <= block["max"]
    assert stages["decision_to_received"]["p50"] == 30_000
    assert stages["received_to_quote"]["p50"] >= 0, (
        "the price is never older than the answer"
    )
    values = [int(fill["quote_ts_ms"]) - int(fill["decision_ts_ms"]) for fill in []]
    assert values == []


def test_the_lifecycle_is_stable_across_a_zero_latency_replay(tmp_path):
    """Control: sin latencia no hay colisión de fases y el aplazamiento no aparece."""
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=0)

    assert summary["fills"] >= 1
    assert of_kind(rows, "OPINION_DEFERRED") == []
    assert summary["execution"]["opinions"]["deferred_slots"] == 0


def test_no_entry_skips_the_risk_verdict(tmp_path):
    """Cada relleno tiene detrás una fila de riesgo aprobada: la puerta no se puede omitir."""
    _, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)
    verdicts = {
        int(row["decision_seq"]): row for row in of_kind(rows, "DECISION_OUTCOME")
    }

    fills = of_kind(rows, "FILL")
    assert fills
    for fill in fills:
        verdict = verdicts.get(int(fill["decision_seq"]))
        assert verdict is not None, "a fill without a risk row is a fill nobody approved"
        assert verdict["risk_gate"] == "check_signal"
        assert verdict["approved"] is True
        assert verdict.get("notional_usdt") == fill.get("notional_usdt")


def test_no_trade_is_a_valid_decision_and_creates_no_order(tmp_path):
    summary, rows, _ = run_lane(
        tmp_path,
        series=bars(count=40),
        latency_ms=30_000,
        answers=[NO_TRADE] * 400,
    )

    assert summary["fills"] == 0
    assert summary["closed_trades"] == 0
    assert of_kind(rows, "FILL") == []
    assert of_kind(rows, "OPINION_DEFERRED") == []
    assert summary["execution"]["opinions"]["generated"] == 0
    assert summary["execution"]["opinions"]["pending_at_end"] == 0
    assert summary["counters"]["action:NO_TRADE"] >= 1


def test_a_one_hour_grid_with_sub_bar_latency_fills_on_the_next_open(tmp_path):
    """El caso de las sesiones de 1 h: 900 ms de latencia ya no destruyen la opinión."""
    series = bars(count=16, interval_ms=3_600_000)
    summary, rows, _ = run_lane(
        tmp_path,
        series=series,
        latency_ms=900,
        timeframe="1h",
        window_bars=10,
        feed=False,
    )

    assert summary["fills"] >= 1, (
        "a sub-bar latency must cost time, not the trade; "
        f"counters={summary['counters']} fills={summary['fills']}"
    )
    assert not [
        row
        for row in of_kind(rows, "GUARD_REJECT")
        if row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ]
    for fill in of_kind(rows, "FILL"):
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
        assert int(fill["received_at_ms"]) - int(fill["decision_ts_ms"]) == 900


def test_the_median_fill_delay_is_the_one_the_clock_declares(tmp_path):
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=30_000)
    delays = [
        int(fill["quote_ts_ms"]) - int(fill["decision_ts_ms"]) for fill in of_kind(rows, "FILL")
    ]
    assert delays
    assert summary["execution"]["stage_latency_ms"]["decision_to_quote"]["p50"] == int(
        statistics.median(delays)
    )
    assert all(delay == 60_000 for delay in delays), (
        "one bar of delay is the declared cost of a sub-bar latency on a minute grid"
    )


@pytest.mark.parametrize("latency", [1, 15_000, 45_000, 59_000])
def test_any_sub_bar_latency_reaches_the_next_open(tmp_path, latency: int):
    summary, rows, _ = run_lane(tmp_path, series=bars(count=40), latency_ms=latency)

    assert summary["fills"] >= 1
    for fill in of_kind(rows, "FILL"):
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
