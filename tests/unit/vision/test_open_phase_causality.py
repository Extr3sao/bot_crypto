"""La apertura es un instante, no la primera mitad del cierre.

El Bloque B cerró el reloj y la cotización, pero dejó el P0 escrito y sin arreglar: en
``VisionLane.run`` los rellenos de entrada al OPEN se ejecutan **antes** de que el broker
reconozca los stops que ese mismo OPEN ya cruzó, porque la comprobación de stops corre al
CLOSE. Consecuencias, todas medidas en este fichero:

* una posición que abrió el hueco de su stop sigue en el libro de riesgo mientras la misma
  apertura acepta riesgo nuevo (C-01/C-02);
* el hueco se disfraza de salida intrabar y pierde su instante real (C-03);
* la vela de entrada se comprueba sólo si el orden de las fases lo permite (C-04);
* el orden de iteración de los símbolos decide qué operación cabe (C-05);
* un hueco en los datos se convierte en una cotización posterior "válida" (C-06);
* sin una fuente de precios independiente no hay forma de distinguir un hueco de una
  caída del proveedor (C-06/C-11).

Cada test ataca ``VisionLane.run`` con el ``RiskManager`` y el ``PaperBroker`` de
producción: ``TEST_TARGET == RUNTIME_TARGET``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.paper.broker import BrokerCost, PaperBroker
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.strategies.types import Signal
from trading_bot.vision.execution import CoverageProof, Quote, schedule
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ProviderError, ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
MINUTE_MS = 60_000
#: Viernes 2026-03-06 00:00 UTC: la barra 72 es lunes 00:00, frontera de día **y** de
#: semana, que es justo lo que C-09 necesita del calendario.
START_MS = int(datetime(2026, 3, 6, tzinfo=UTC).timestamp() * 1000)
REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
PEER = "ETH/USDT"
GAP_INDEX = 72


def at(index: int, *, step_ms: int = HOUR_MS) -> int:
    return START_MS + index * step_ms


LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":1.0,'
    '"invalidation":null,"rationale":"Continuation."}'
)
SHORT = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"SHORT",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":1.0,'
    '"invalidation":null,"rationale":"Breakdown."}'
)
NO_TRADE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"NO_TRADE",'
    '"confidence":0.3,"horizon_bars":6,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"No level."}'
)
CLOSE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"CLOSE",'
    '"confidence":0.9,"horizon_bars":1,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"Structure broke."}'
)


def answer(template: str, symbol: str) -> str:
    return template % symbol


# --------------------------------------------------------------- series builders


Shape = Callable[[float], tuple[float, float, float, float]]


def flat_bars(
    *,
    count: int = 48,
    step_ms: int = HOUR_MS,
    patches: dict[int, Shape] | None = None,
    start: int = START_MS,
) -> list[Bar]:
    """Precio plano con huecos opcionales.

    Plano a propósito: con stop al 1 % y objetivo al 1 %, ninguna vela normal toca
    ninguno de los dos niveles (high/low a ±0,1 %), así que la única salida posible es la
    que el test provoca. Una serie con deriva cambiaría el nivel del stop con cada vela y
    convertiría el escenario en una lotería.
    """

    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        opened = price
        close = price
        high = price * 1.001
        low = price * 0.999
        if patches and index in patches:
            opened, high, low, close = patches[index](price)
        bars.append(
            Bar(
                ts_ms=start + index * step_ms,
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
        price = close
    return bars


def gap(index: int, *, pct: float, wick: float | None = None) -> dict[int, Shape]:
    """Un hueco adverso en la apertura de ``index``.

    ``wick`` ensancha el rango de la vela para probar que la apertura no mira el
    high/low: un stop es un hecho de la apertura, no del rango que vino después.
    """

    def shape(natural: float) -> tuple[float, float, float, float]:
        opened = natural * (1.0 + pct)
        high = opened * (1.0 + (wick or 0.001))
        low = opened * (1.0 - (wick or 0.001))
        return (opened, high, low, opened)

    return {index: shape}


def pierce(index: int, *, low_at: float) -> dict[int, Shape]:
    """Una vela de entrada que perfora el stop dentro de su rango."""

    def shape(natural: float) -> tuple[float, float, float, float]:
        return (natural, natural * 1.001, natural * low_at, natural)

    return {index: shape}


# ------------------------------------------------------------------- providers


class ScriptedProvider(ReplayProvider):
    """Responde según ``(símbolo, instante de la decisión)`` y declara su latencia."""

    def __init__(
        self,
        script: Callable[[str, int], str],
        *,
        latency_ms: int = 0,
    ) -> None:
        super().__init__(lambda request: script(request.chart.symbol, int(request.decision_ts_ms)))
        self._latency_ms = latency_ms

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        response = super().analyze(request)
        return replace(response, latency_ms=self._latency_ms)


class RefusingProvider(ReplayProvider):
    """Un proveedor que cancela: hay petición, no hay recibo ni respuesta."""

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        raise ProviderError("CANCELLED", "client aborted before the answer", attempts=1)


class ContinuousFeed:
    """Una fuente de precios independiente del OHLC, declarada como tal."""

    def __init__(self, *, venue_open: bool = True, step_ms: int = MINUTE_MS) -> None:
        self.name = "independent_1m_feed"
        self._venue_open = venue_open
        self._step_ms = step_ms

    def prove_coverage(
        self, symbol: str, missing_bar_open_ms: int, interval_ms: int
    ) -> CoverageProof | None:
        step = self._step_ms
        stamps = list(range(missing_bar_open_ms + step, missing_bar_open_ms + interval_ms, step))
        quotes = tuple(
            Quote(symbol=symbol, ts_ms=stamp, price=100.0, source=self.name, bar_open_ms=stamp)
            for stamp in stamps
        )
        return CoverageProof(
            symbol=symbol,
            missing_bar_open_ms=missing_bar_open_ms,
            source=self.name,
            quotes=quotes,
            venue_open=self._venue_open,
        )


# --------------------------------------------------------------------- harness


def policy(**overrides):
    risk = load_settings(config_dir=REPO / "config", env_file=None).risk
    return risk.model_copy(update=overrides) if overrides else risk


def vision_config(**lane_overrides):
    base = load_vision_config(env={})
    lane = base.lane
    merged = {
        "timeframe": "1h",
        "window_bars": 20,
        "decision_every_bars": 1,
        "max_calls_per_run": 200,
        "max_estimated_spend_usd": 10.0,
        **lane_overrides,
    }
    return base.__class__(provider=base.provider, lane=lane.__class__(**merged))


def run_lane(
    tmp_path: Path,
    *,
    series: dict[str, list[Bar]],
    script: Callable[[str, int], str],
    latency_ms: int = 0,
    risk_policy=None,
    quote_feed=None,
    **lane_overrides,
):
    lane = VisionLane(
        series=series,
        provider=ScriptedProvider(script, latency_ms=latency_ms),
        config=vision_config(**lane_overrides),
        risk_policy=risk_policy or policy(),
        ledger_path=tmp_path / "decisions.jsonl",
        quote_feed=quote_feed,
    )
    summary = lane.run()
    #: ``seq`` lives on the chain line, so it is lifted into the entry: the ordering of
    #: two rows at the same instant is the thing several of these tests are about.
    rows = [
        dict(line["entry"], seq=line["seq"])
        for line in read_entries(tmp_path / "decisions.jsonl")
    ]
    return lane, summary, rows


def of_kind(rows: Sequence[dict], kind: str) -> list[dict]:
    return [row for row in rows if row.get("kind") == kind]


def closes_at(rows: Sequence[dict], ts_ms: int) -> list[dict]:
    return [row for row in of_kind(rows, "CLOSE") if row["ts_ms"] == ts_ms]


def gap_left(scenario: str, *, latency_ms: int = 0, policy_overrides=None, peer_symbol=PEER):
    """Escenario base de C-01/C-02/C-03/C-09: posición antigua + hueco + propuesta nueva.

    ``BTC/USDT`` entra al OPEN de la barra 20 (decisión de la 19) y su stop queda al 1 %.
    En la barra 72 la apertura salta el 3 %. La propuesta del segundo activo se forma en
    el cierre de la 71, así que su relleno y el hueco comparten **el mismo instante**.
    """

    def shape(natural: float) -> tuple[float, float, float, float]:
        opened = natural * (1.03 if scenario == "short" else 0.97)
        return (opened, opened * 1.001, opened * 0.999, opened)

    target_shape = gap_through_target_shape(scenario)
    patches: dict[int, Shape] = {GAP_INDEX: target_shape or shape}
    bars = flat_bars(count=GAP_INDEX + 4, patches=patches)

    def script(symbol: str, decision_ts_ms: int) -> str:
        if symbol == SYMBOL:
            return answer(SHORT if scenario == "short" else LONG, symbol)
        if decision_ts_ms == at(GAP_INDEX):
            return answer(SHORT if scenario == "short" else LONG, peer_symbol)
        return answer(NO_TRADE, peer_symbol)

    return {
        "series": {SYMBOL: bars, peer_symbol: list(bars)},
        "script": script,
        "latency_ms": latency_ms,
        "risk_policy": policy(**(policy_overrides or {})),
    }


def gap_through_target_shape(scenario: str) -> Shape | None:
    """El hueco de C-03, con un rango absurdo que no debe mirarse en la apertura."""

    if scenario != "target_and_stop":
        return None

    def shape(natural: float) -> tuple[float, float, float, float]:
        opened = natural * 0.97
        return (opened, natural * 1.10, opened * 0.999, natural)

    return shape


# ---------------------------------------------------------------- C-01 / C-02


def test_a_long_gapped_through_its_stop_is_settled_before_the_entry_at_that_open(tmp_path):
    """C-01: la pérdida existe antes de que la misma apertura apruebe riesgo nuevo."""

    scenario = gap_left("long", policy_overrides={"max_daily_loss_pct": 0.05})
    lane, summary, rows = run_lane(tmp_path, **scenario)

    closes = [row for row in of_kind(rows, "CLOSE") if row["symbol"] == SYMBOL]
    assert len(closes) == 1, f"the gapped position must close once: {closes}"
    close = closes[0]
    assert close["exit_reason"] == "stop_loss"
    assert close["exit_ts_resolution"] == "OPEN_GAP"
    assert close["gap_price_source"] == "bar_open"
    assert close["ts_ms"] == at(GAP_INDEX), "a gap exit happens at the open, not at the close"
    assert close["exit_ts_lower_bound_ms"] == close["exit_ts_upper_bound_ms"] == at(GAP_INDEX)
    assert close["exit_reference_price"] < close["stop_loss_price"], (
        "the first tradable price was the gap open, not the stop level"
    )

    peer = [row for row in of_kind(rows, "DECISION_OUTCOME") if row["symbol"] == PEER]
    assert peer, "the second asset's proposal must reach the risk gate"
    blocked = peer[-1]
    assert blocked["ts_ms"] == at(GAP_INDEX)
    assert blocked["approved"] is False
    assert blocked["risk_blocked_by"] == "daily_loss_limit", (
        "the gate must see the loss the same open produced: "
        f"blocked_by={blocked['risk_blocked_by']}"
    )

    assert close["seq"] < blocked["seq"], (
        "the stop must be recorded before the entry at the same instant: "
        f"close seq {close['seq']} vs outcome seq {blocked['seq']}"
    )
    assert not [row for row in of_kind(rows, "FILL") if row["symbol"] == PEER]
    assert summary["fills"] == 1, "only the pre-existing entry filled"
    assert lane.risk.equity == pytest.approx(
        10_000.0 + close["pnl_net_usdt"], abs=1e-6
    ), "the risk engine must carry the gap loss"


def test_a_short_gapped_through_its_stop_is_settled_before_the_entry_at_that_open(tmp_path):
    """C-02: simétrico. Un corto sufre un hueco al alza y el riesgo lo ve primero."""

    scenario = gap_left("short", policy_overrides={"max_daily_loss_pct": 0.05})
    lane, summary, rows = run_lane(tmp_path, **scenario)

    closes = [row for row in of_kind(rows, "CLOSE") if row["symbol"] == SYMBOL]
    assert len(closes) == 1
    close = closes[0]
    assert close["side"] == "sell"
    assert close["exit_reason"] == "stop_loss"
    assert close["exit_ts_resolution"] == "OPEN_GAP"
    assert close["ts_ms"] == at(GAP_INDEX)
    assert close["exit_reference_price"] > close["stop_loss_price"], (
        "a short that gaps up exits above its stop, at the first price that existed"
    )
    assert close["pnl_net_usdt"] < 0

    peer = [row for row in of_kind(rows, "DECISION_OUTCOME") if row["symbol"] == PEER]
    assert peer and peer[-1]["risk_blocked_by"] == "daily_loss_limit"
    assert close["seq"] < peer[-1]["seq"]
    assert not [row for row in of_kind(rows, "FILL") if row["symbol"] == PEER]
    assert summary["fills"] == 1
    del lane


# ---------------------------------------------------------------------- C-03


def test_an_open_gap_never_reads_the_range_of_the_bar_it_opened(tmp_path):
    """C-03: el stop cruzado por la apertura se paga en la apertura.

    La vela del hueco tiene un high un 10 % por encima del cierre anterior — por encima
    del objetivo. Si la fase de apertura mirase el rango de la vela, la posición podría
    "salir en objetivo" a un precio que sólo existió después del hueco. La única salida
    coherente es la del stop, al precio de la apertura.
    """

    scenario = gap_left("target_and_stop", policy_overrides={"max_daily_loss_pct": 0.05})
    _, _, rows = run_lane(tmp_path, **scenario)

    closes = [row for row in of_kind(rows, "CLOSE") if row["symbol"] == SYMBOL]
    assert len(closes) == 1, f"exactly one exit, and it must be the stop: {closes}"
    close = closes[0]
    assert close["exit_reason"] == "stop_loss"
    assert not [row for row in closes if row["exit_reason"] == "take_profit"], (
        "a high that happened after the gap cannot redeem a position the gap closed"
    )
    assert close["exit_ts_resolution"] == "OPEN_GAP"
    assert close["exit_reference_price"] == pytest.approx(97.0, abs=0.5), (
        "the exit price is the gap open, not the stop and never the bar high"
    )
    assert close["exit_ts_lower_bound_ms"] == close["exit_ts_upper_bound_ms"]


# ---------------------------------------------------------------------- C-04


def test_the_bar_a_position_opens_on_is_checked_at_its_close_not_before(tmp_path):
    """C-04: la vela de entrada se evalúa al cierre y con una ventana declarada."""

    bars = flat_bars(patches=pierce(20, low_at=0.985))
    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: bars},
        script=lambda symbol, ts: answer(LONG, symbol),
    )

    fill = of_kind(rows, "FILL")[0]
    close = next(
        row for row in of_kind(rows, "CLOSE") if row["exit_reason"] == "stop_loss"
    )
    assert close["position_id"] == fill["position_id"], "the stop belongs to the entry it checks"
    assert summary["fills"] >= 1
    assert close["exit_ts_resolution"] == "BAR_WINDOW"
    assert close["ts_ms"] == at(21), "the outcome is knowable only when the bar ends"
    assert close["exit_ts_lower_bound_ms"] == fill["quote_ts_ms"]
    assert close["exit_ts_upper_bound_ms"] == at(21)
    assert close["exit_reference_price"] == pytest.approx(
        fill["stop_loss_price"], rel=1e-6
    ), "an intrabar touch fills at the level, not at the bar's open"
    assert fill["seq"] < close["seq"], "a stop cannot be booked before the entry exists"
    assert not [
        row for row in of_kind(rows, "CLOSE") if row["ts_ms"] == fill["quote_ts_ms"]
    ], "the entry bar's open may not host an exit"


# ---------------------------------------------------------------------- C-05


def economic_events(rows: Sequence[dict]) -> list[tuple]:
    out: list[tuple] = []
    for row in rows:
        kind = row["kind"]
        if kind == "FILL":
            out.append(
                (
                    kind,
                    row["ts_ms"],
                    row["symbol"],
                    row["side"],
                    row["position_id"],
                    row["decision_seq"],
                )
            )
        elif kind == "DECISION_OUTCOME":
            out.append(
                (
                    kind,
                    row["ts_ms"],
                    row["symbol"],
                    row.get("intent"),
                    row.get("approved"),
                    row.get("risk_blocked_by"),
                    row["decision_seq"],
                )
            )
        elif kind == "CLOSE":
            out.append(
                (kind, row["ts_ms"], row["symbol"], row["exit_reason"], row["position_id"])
            )
    return out


def test_the_insertion_order_of_the_series_cannot_change_what_fills(tmp_path):
    """C-05: con un solo hueco de posición, el mismo activo gana siempre."""

    shared = flat_bars()
    script = lambda symbol, ts: answer(LONG, symbol)  # noqa: E731
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    _, one, rows_one = run_lane(
        first,
        series={SYMBOL: shared, PEER: list(shared)},
        script=script,
        risk_policy=policy(max_open_positions=1),
    )
    _, two, rows_two = run_lane(
        second,
        series={PEER: list(shared), SYMBOL: shared},
        script=script,
        risk_policy=policy(max_open_positions=1),
    )

    fills_one = [(row["ts_ms"], row["symbol"]) for row in of_kind(rows_one, "FILL")]
    assert fills_one and fills_one[0] == (at(20), SYMBOL), (
        "the slot must go to a deterministic symbol, not to dict insertion order: "
        f"{fills_one[:3]}"
    )
    assert economic_events(rows_one) == economic_events(rows_two)
    assert one["fills"] == two["fills"]
    assert one["final_equity_usdt"] == two["final_equity_usdt"]
    assert one["counters"] == two["counters"]
    assert any(
        row.get("risk_blocked_by") == "max_positions"
        for row in of_kind(rows_one, "DECISION_OUTCOME")
    )


# ---------------------------------------------------------------------- C-06


def missing_expected_bar() -> list[Bar]:
    """La barra 21 —el relleno esperado de la decisión de la 20— no existe."""

    bars = flat_bars(count=40)
    return [bar for index, bar in enumerate(bars) if index != 21]


def test_a_missing_bar_is_not_a_price_however_late_the_next_quote_is(tmp_path):
    """C-06: fail-closed. Un timestamp posterior no demuestra continuidad."""

    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: missing_expected_bar()},
        script=lambda symbol, ts: answer(LONG, symbol),
        decision_every_bars=4,
    )

    rejects = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "DATA_GAP"]
    assert rejects, "the hole must be named, not executed"
    assert rejects[0]["stage"] == "EXECUTION"
    assert rejects[0]["missing_bar_open_ms"] == at(21)
    assert rejects[0]["missing_bars"] == 1
    assert rejects[0]["decision_seq"] is not None
    assert not [
        row for row in of_kind(rows, "FILL") if row["decision_seq"] == rejects[0]["decision_seq"]
    ], "the decision that met the hole cannot fill later at a different price"
    assert summary["counters"].get("guard:DATA_GAP", 0) >= 1


def test_a_trusted_quote_feed_can_prove_the_venue_was_open_during_the_hole(tmp_path):
    """C-06: el único camino permitido a través de un hueco es evidencia independiente."""

    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: missing_expected_bar()},
        script=lambda symbol, ts: answer(LONG, symbol),
        quote_feed=ContinuousFeed(),
        decision_every_bars=4,
    )

    assert not [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "DATA_GAP"]
    fills = of_kind(rows, "FILL")
    assert fills, "a covered hole is executable"
    fill = fills[0]
    assert fill["quote_ts_ms"] >= fill["received_at_ms"]
    assert fill["quote_source"] == "bar_open"
    assert fill["data_gap_covered_by"] == "independent_1m_feed"
    assert fill["data_gap_missing_bar_open_ms"] == at(21)
    assert fill["quote_ts_ms"] == at(22), "the price is a real bar open, never a retroactive one"
    assert summary["fills"] == len(fills) == 1


def test_a_feed_that_reports_the_venue_closed_does_not_cover_the_hole(tmp_path):
    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: missing_expected_bar()},
        script=lambda symbol, ts: answer(LONG, symbol),
        quote_feed=ContinuousFeed(venue_open=False),
        decision_every_bars=4,
    )

    rejects = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "DATA_GAP"]
    assert rejects and "closed" in rejects[0]["coverage_reason"]
    assert not [
        row for row in of_kind(rows, "FILL") if row["decision_seq"] == rejects[0]["decision_seq"]
    ]
    assert summary["counters"].get("guard:DATA_GAP", 0) >= 1


# ---------------------------------------------------------------------- C-07


def test_a_one_minute_stream_fills_at_the_first_quote_after_the_answer(tmp_path):
    """C-07: 30 s de latencia en una rejilla de 1 m compran el siguiente minuto."""

    bars = flat_bars(count=200, step_ms=MINUTE_MS)
    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: bars},
        script=lambda symbol, ts: answer(LONG, symbol),
        latency_ms=30_000,
        timeframe="1m",
        decision_every_bars=4,
    )

    fills = of_kind(rows, "FILL")
    assert summary["fills"] == len(fills) >= 1
    for fill in fills:
        assert fill["quote_ts_ms"] >= fill["received_at_ms"]
        assert fill["quote_lag_ms"] < MINUTE_MS, "the first available quote, not a later one"
        assert fill["quote_ts_ms"] - fill["decision_ts_ms"] == MINUTE_MS
    assert summary["counters"].get("requote:WAITING_FOR_QUOTE", 0) >= 1


# ---------------------------------------------------------------------- C-08


def test_the_opinion_window_is_inclusive_and_says_so_without_a_zero_default():
    """C-08: exactamente en el límite se rellena; un milisegundo más, no."""

    quote = Quote(symbol=SYMBOL, ts_ms=START_MS + HOUR_MS, price=100.0)

    at_limit = schedule(
        quote,
        received_at_ms=START_MS,
        decision_ts_ms=START_MS,
        max_age_ms=HOUR_MS,
    )
    assert at_limit.status == "FILL"
    assert at_limit.age_ms == HOUR_MS

    over = schedule(
        quote,
        received_at_ms=START_MS,
        decision_ts_ms=START_MS - 1,
        max_age_ms=HOUR_MS,
    )
    assert over.status == "EXPIRED"
    assert over.age_ms == HOUR_MS + 1

    with pytest.raises(ValueError):
        schedule(quote, received_at_ms=START_MS, decision_ts_ms=START_MS, max_age_ms=0)


def test_the_lane_uses_the_same_boundary(tmp_path):
    bars = flat_bars(count=40)
    at_limit = tmp_path / "limit"
    at_limit.mkdir()
    _, summary, rows = run_lane(
        at_limit,
        series={SYMBOL: bars},
        script=lambda symbol, ts: answer(LONG, symbol),
        latency_ms=HOUR_MS,
        decision_every_bars=4,
    )
    assert summary["fills"] == 1, rows
    assert of_kind(rows, "FILL")[0]["opinion_age_ms"] == HOUR_MS

    over = tmp_path / "over"
    over.mkdir()
    _, summary, rows = run_lane(
        over,
        series={SYMBOL: bars},
        script=lambda symbol, ts: answer(LONG, symbol),
        latency_ms=HOUR_MS + 1,
        decision_every_bars=4,
    )
    assert summary["fills"] == 0
    expired = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "LATE_RESPONSE"]
    assert expired and expired[0]["opinion_age_ms"] > expired[0]["max_opinion_age_ms"]


# ---------------------------------------------------------------------- C-09


def test_a_gap_at_monday_open_lands_in_the_active_day_and_week(tmp_path):
    """C-09: la pérdida entra en la ventana de calendario que la puerta va a mirar."""

    scenario = gap_left("long", policy_overrides={"max_daily_loss_pct": 0.05})
    lane, _, rows = run_lane(tmp_path, **scenario)
    close = next(row for row in of_kind(rows, "CLOSE") if row["symbol"] == SYMBOL)

    assert close["day_utc"] == "2026-03-09", "the gap is a Monday 00:00 event"
    assert close["risk_daily_pnl_after"] == pytest.approx(close["pnl_net_usdt"], abs=1e-6)
    assert close["risk_weekly_pnl_after"] == pytest.approx(close["pnl_net_usdt"], abs=1e-6)
    assert lane.risk.daily_pnl == pytest.approx(close["pnl_net_usdt"], abs=1e-6)
    assert lane.risk.weekly_pnl == pytest.approx(close["pnl_net_usdt"], abs=1e-6)
    assert lane.risk.trades_today == 1, "the day boundary reset the counter before the loss"

    blocked = [
        row
        for row in of_kind(rows, "DECISION_OUTCOME")
        if row["symbol"] == PEER and row["ts_ms"] == at(GAP_INDEX)
    ]
    assert blocked and blocked[0]["risk_blocked_by"] == "daily_loss_limit"


# ---------------------------------------------------------------------- C-10


def test_a_missing_mark_for_another_open_asset_vetoes_new_risk(tmp_path):
    """C-10: si el patrimonio del libro es ambiguo, no se abre riesgo nuevo."""

    peer_bars = [bar for index, bar in enumerate(flat_bars()) if index != 30]
    bitcoin = flat_bars()

    def script(symbol: str, decision_ts_ms: int) -> str:
        if symbol == SYMBOL:
            return answer(LONG, symbol) if decision_ts_ms == at(30) else answer(NO_TRADE, symbol)
        return answer(LONG, symbol)

    lane, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: bitcoin, PEER: peer_bars},
        script=script,
    )

    assert [row for row in of_kind(rows, "FILL") if row["symbol"] == PEER], (
        "the peer position is the one whose mark goes missing"
    )
    vetoes = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "STALE_VALUATION"]
    assert vetoes, "an unmarked open position must block new risk"
    assert vetoes[0]["symbol"] == SYMBOL
    assert vetoes[0]["ts_ms"] == at(30)
    assert vetoes[0]["stale_marks"] == [PEER]
    assert not [row for row in of_kind(rows, "FILL") if row["symbol"] == SYMBOL]
    assert summary["counters"].get("veto:STALE_VALUATION", 0) >= 1

    point = next(row for row in lane.equity_curve if row["ts_ms"] == at(31))
    assert point["stale_marks"] == [PEER], (
        "the curve must declare that one mark was carried over, not pretend it was fresh"
    )


# ---------------------------------------------------------------------- C-11


def test_a_cancelled_answer_and_a_missing_price_are_states_not_crashes(tmp_path):
    bars = flat_bars(count=40)
    lane = VisionLane(
        series={SYMBOL: bars},
        provider=RefusingProvider([]),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / "cancel.jsonl",
    )
    summary = lane.run()
    rows = [row["entry"] for row in read_entries(tmp_path / "cancel.jsonl")]

    failures = of_kind(rows, "PROVIDER_FAILURE")
    assert failures and failures[0]["code"] == "CANCELLED"
    assert failures[0]["attempts"] == 1
    assert failures[0]["decision"] is None
    assert summary["fills"] == 0
    assert summary["counters"].get("provider_failure:CANCELLED", 0) >= 1

    zeroed = flat_bars(count=40, patches={20: lambda natural: (0.0, natural, 0.0, natural)})
    lane = VisionLane(
        series={SYMBOL: zeroed},
        provider=ScriptedProvider(lambda symbol, ts: answer(LONG, symbol)),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / "zero.jsonl",
    )
    summary = lane.run()
    rows = [
        dict(line["entry"], seq=line["seq"])
        for line in read_entries(tmp_path / "zero.jsonl")
    ]

    rejects = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "NO_EXECUTABLE_PRICE"]
    assert rejects, "a zero open is not a price; it must be a named rejection"
    assert rejects[0]["quote_bar_open_ms"] == at(20)
    assert rejects[0]["stage"] == "EXECUTION"
    assert rejects[0]["decision_seq"] is not None
    assert not [
        row for row in of_kind(rows, "FILL") if row["decision_seq"] == rejects[0]["decision_seq"]
    ], "the decision that met the zero open cannot fill at another bar's price"
    assert summary["counters"].get("guard:NO_EXECUTABLE_PRICE", 0) >= 1


# ---------------------------------------------------------------------- C-12


def legacy_broker() -> PaperBroker:
    broker = PaperBroker(
        equity=10_000.0,
        slippage_bps=1.0,
        commission_bps=5.0,
        book_id="legacy-test",
        clock=lambda: 1_770_000_000.0,
        cost_schedule=lambda symbol, notional: BrokerCost(
            commission_bps=5.0, half_spread_bps=0.5, slippage_bps=1.0
        ),
    )
    broker.execute_signal(
        Signal(
            symbol=SYMBOL,
            side="buy",
            strategy_name="legacy",
            timeframe="1h",
            confidence=0.5,
            price=100.0,
            stop_loss_pct=1.0,
            take_profit_pct=2.0,
            metadata={"notional_usdt": 500.0},
        )
    )
    return broker


def test_the_legacy_gap_policy_still_fills_at_the_stop_level():
    """C-12: el comportamiento histórico del broker no cambia por defecto."""

    broker = legacy_broker()
    stop = broker.positions[SYMBOL].stop_loss_price
    trade = broker.check_positions_ohlc({SYMBOL: (90.0, 91.0, 89.0, 90.5)})[0]

    assert trade.exit_reason == "stop_loss"
    assert trade.reference_exit_price == pytest.approx(stop), (
        "the default policy credits the stop level; only the lane opts into open_on_gap"
    )


def test_the_open_gap_primitive_only_touches_the_positions_the_open_crossed():
    broker = legacy_broker()
    peer = broker.execute_signal(
        Signal(
            symbol=PEER,
            side="buy",
            strategy_name="legacy",
            timeframe="1h",
            confidence=0.5,
            price=100.0,
            stop_loss_pct=1.0,
            take_profit_pct=2.0,
            metadata={"notional_usdt": 500.0},
        )
    )
    assert peer is not None

    closed = broker.exit_on_open_gap(SYMBOL, 90.0)

    assert closed is not None
    assert closed.reference_exit_price == pytest.approx(90.0)
    assert SYMBOL not in broker.positions, "the crossed position is closed at the open"
    assert PEER in broker.positions, "a position the open did not cross is untouched"
    assert broker.exit_on_open_gap(PEER, 99.5) is None


# ------------------------------------------------------------------ reduce-only


def test_a_close_cannot_reverse_the_book_or_be_blocked_by_an_entry_gate(tmp_path):
    """Un CLOSE reduce-only: cierra, no abre el contrario, y no pasa por el gate."""

    script = lambda symbol, ts: (  # noqa: E731
        answer(CLOSE, symbol) if ts >= at(24) else answer(LONG, symbol)
    )
    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: flat_bars(count=40)},
        script=script,
        risk_policy=policy(kill_switch_enabled=True),
    )

    closes = [row for row in of_kind(rows, "CLOSE") if row["exit_reason"] == "signal"]
    assert closes, "the model's CLOSE must execute"
    close = closes[0]
    assert close["side"] == "buy", "the trade that closed is the long, not a new short"
    assert close["exit_ts_lower_bound_ms"] == close["exit_ts_upper_bound_ms"]
    assert close["exit_ts_resolution"] == "QUOTE"
    assert not summary["open_positions_at_end"], "reduce-only leaves the symbol flat"
    assert not [
        row
        for row in of_kind(rows, "FILL")
        if row["symbol"] == SYMBOL and row["ts_ms"] >= close["ts_ms"]
    ], "a reduction must never be followed by an entry it did not ask for"
    assert any(
        row.get("risk_gate") == "BYPASSED_FOR_REDUCTION"
        for row in of_kind(rows, "DECISION_OUTCOME")
    )


def test_a_close_with_nothing_open_does_nothing(tmp_path):
    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: flat_bars(count=40)},
        script=lambda symbol, ts: answer(CLOSE, symbol),
    )

    assert summary["fills"] == 0
    assert not of_kind(rows, "CLOSE")
    decisions = of_kind(rows, "DECISION")
    assert decisions and decisions[0]["coherence_reason"] == "NO_POSITION_TO_CLOSE"


def test_an_opposite_call_never_reverses_through_the_broker(tmp_path):
    def script(symbol: str, decision_ts_ms: int) -> str:
        return answer(LONG, symbol) if decision_ts_ms < at(24) else answer(SHORT, symbol)

    _, summary, rows = run_lane(
        tmp_path,
        series={SYMBOL: flat_bars(count=40)},
        script=script,
    )

    assert summary["fills"] == 1
    assert summary["open_positions_at_end"][SYMBOL]["side"] == "buy"
    reasons = [row.get("coherence_reason") for row in of_kind(rows, "DECISION")]
    assert "OPPOSITE_LONG_OPEN" in reasons
    assert not [row for row in of_kind(rows, "FILL") if row["side"] == "sell"]
