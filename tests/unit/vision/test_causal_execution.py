"""El motor de ejecución causal: dónde se puede rellenar una opinión y hasta cuándo.

El Bloque A arregló el **reloj de la información**: la decisión ya no se sella en la
apertura de la vela cuyo cierre leyó. Este bloque arregla la consecuencia, que el Bloque A
dejó a la vista y sin resolver: si la respuesta llega 90 segundos después del cierre de la
vela, el motor antiguo pedía el precio de la apertura de una vela que **ya había abierto**
antes de que la respuesta existiera, y lo llamaba «tarde» y descartaba la operación. Con un
proveedor real —que nunca tarda cero— el carril devolvía `NO_TRADE` para siempre.

Cinco defectos, cada uno con su test:

* **B-01** la ejecución no tiene cotización posterior a la respuesta: o se rellena en un
  precio anterior a la respuesta, o no se rellena nunca;
* **B-02** el precio ejecutable se construye a partir de OHLC sin resolución: el motor
  podría inventar un precio entre apertura y cierre de una vela, que no existe;
* **B-03** la vela en la que se entra **nunca** se comprueba contra el stop, porque la
  comprobación corre antes del relleno;
* **B-04** un hueco a través del stop se rellena en el nivel del stop, no en la apertura
  del hueco, lo que infravalora la pérdida y hace que el riesgo medido sea menor que el
  real;
* **B-05** no hay reconciliación neta: el PnL, la equidad del broker, la curva y la
  equidad que ve el motor de riesgo no tienen una identidad comprobada.

Se ataca el runtime real (`VisionLane.run`), no un simulador paralelo: `TEST_TARGET ==
RUNTIME_TARGET`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000
REPO = Path(__file__).resolve().parents[3]

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":0.5,"take_profit_pct":0.75,'
    '"invalidation":null,"rationale":"Continuation."}'
)


class LatencyProvider(ReplayProvider):
    """The replay transport, with a declared round-trip the lane cannot ignore."""

    def __init__(self, answers: list[str], *, latency_ms: int) -> None:
        super().__init__(list(answers))
        self._latency_ms = latency_ms

    def analyze(self, request):  # type: ignore[override]
        response: VisionResponse = super().analyze(request)
        return _with_latency(response, self._latency_ms)


def _with_latency(response: VisionResponse, latency_ms: int) -> VisionResponse:
    from dataclasses import replace

    return replace(response, latency_ms=latency_ms)


Shape = Callable[[float], tuple[float, float, float, float]]


def build_series(
    *,
    count: int = 96,
    step: float = 0.002,
    patches: dict[int, Shape] | None = None,
) -> list[Bar]:
    """A gentle uptrend with optional per-bar overrides.

    A patch receives the bar's *natural* open (the previous close) and returns
    ``(open, high, low, close)``. Indices are fixed so the test knows exactly which bar a
    decision lands on: ``decision_every_bars=15`` and ``window_bars=30`` put the first
    decision on index 29, whose close is the open of index 30.
    """

    bars: list[Bar] = []
    price = 100.0
    for i in range(count):
        natural = price
        open_price = natural
        close = open_price * (1.0 + step)
        high = max(open_price, close) * 1.001
        low = min(open_price, close) * 0.999
        if patches and i in patches:
            open_price, high, low, close = patches[i](natural)
        bars.append(
            Bar(
                ts_ms=START_MS + i * HOUR_MS,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=200.0 + (i % 5),
            )
        )
        price = close
    return bars


def policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def vision_config(**overrides):
    base = load_vision_config(env={})
    lane = base.lane
    merged = {
        "timeframe": "1h",
        "window_bars": 30,
        "decision_every_bars": 15,
        "max_calls_per_run": 20,
        "max_estimated_spend_usd": 5.0,
        **overrides,
    }
    return base.__class__(provider=base.provider, lane=lane.__class__(**merged))


def run_lane(tmp_path: Path, *, bars: list[Bar], latency_ms: int):
    lane = VisionLane(
        series={"BTC/USDT": bars},
        provider=LatencyProvider([LONG] * 40, latency_ms=latency_ms),
        config=vision_config(),
        risk_policy=policy(),
        ledger_path=tmp_path / "decisions.jsonl",
    )
    summary = lane.run()
    rows = [row["entry"] for row in read_entries(tmp_path / "decisions.jsonl")]
    return summary, rows


def of_kind(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row["kind"] == kind]


# -- B-01: la cotización tiene que existir después de la respuesta -----------------


def test_a_sub_bar_latency_still_reaches_a_fill(tmp_path):
    """90 s de ida y vuelta es un proveedor rápido, no una respuesta inservible.

    El motor antiguo pedía la apertura de la vela que abrió *antes* de la respuesta, veía
    un precio anterior a ella y la descartaba: con latencia real, cero operaciones para
    siempre. El precio honesto es el primer precio que existe en o después de la respuesta.
    """

    summary, rows = run_lane(tmp_path, bars=build_series(), latency_ms=90_000)

    assert summary["fills"] > 0, (
        "a 90 s round trip must still be tradable: the quote is the next bar's open, "
        f"not the one that preceded the answer; counters={summary['counters']}"
    )
    late = [row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "LATE_RESPONSE"]
    assert late == [], "90 s is inside one bar, so no opinion has expired"


def test_every_fill_quotes_a_price_that_existed_after_the_answer(tmp_path):
    summary, rows = run_lane(tmp_path, bars=build_series(), latency_ms=90_000)
    fills = of_kind(rows, "FILL")

    assert fills, "nothing to check would make this test vacuous"
    for fill in fills:
        assert fill["quote_ts_ms"] >= fill["received_at_ms"], (
            "the fill price must be a quote that existed at or after the answer arrived"
        )
        assert fill["quote_ts_ms"] >= fill["decision_ts_ms"]
        assert fill["quote_source"] == "bar_open", (
            "only bar opens are executable prices in this replay; a price inside the bar "
            "is not knowable from OHLC"
        )
        assert fill["quote_lag_ms"] == fill["quote_ts_ms"] - fill["received_at_ms"]
        assert fill["quote_lag_ms"] >= 0
    assert summary["counters"].get("requote:WAITING_FOR_QUOTE", 0) >= 1, (
        "the order had to wait for the next quote, and that wait must be visible"
    )


def test_an_opinion_older_than_its_execution_window_expires(tmp_path):
    """Control del Bloque A: dos horas de latencia no pueden comprar un precio viejo."""

    summary, rows = run_lane(tmp_path, bars=build_series(), latency_ms=2 * HOUR_MS)

    assert summary["fills"] == 0
    expired = [
        row for row in of_kind(rows, "GUARD_REJECT") if row["code"] == "LATE_RESPONSE"
    ]
    assert expired, "the rejection must name the late answer, not a generic staleness"
    assert all(row["stage"] == "EXECUTION" for row in expired)
    assert all(
        row["opinion_age_ms"] > row["max_opinion_age_ms"] for row in expired
    ), "the row must carry the age that made it expire, not just the verdict"


def test_the_execution_window_is_declared_in_the_run_row(tmp_path):
    _, rows = run_lane(tmp_path, bars=build_series(), latency_ms=90_000)
    run = of_kind(rows, "RUN")[0]

    assert run["lane"]["max_opinion_age_ms"] == HOUR_MS
    assert run["lane"]["stop_coverage"] == "entry_at_open_full_bar"


# -- B-02: no se inventan precios dentro de una vela -----------------------------


def test_a_price_inside_a_bar_is_refused_as_insufficient_resolution():
    from trading_bot.vision.execution import InsufficientResolution, quote_at

    bars = build_series(count=4)

    at_open = quote_at("BTC/USDT", bars, bars[1].ts_ms)
    assert at_open is not None and at_open.price == bars[1].open
    assert at_open.source == "bar_open"

    with pytest.raises(InsufficientResolution):
        quote_at("BTC/USDT", bars, bars[1].ts_ms + 60_000)
    with pytest.raises(InsufficientResolution):
        quote_at("BTC/USDT", bars, bars[1].ts_ms + HOUR_MS - 1)


def test_the_scheduler_waits_then_expires_instead_of_guessing():
    from trading_bot.vision.execution import Quote, schedule

    quote = Quote(
        symbol="BTC/USDT", ts_ms=START_MS + HOUR_MS, price=101.0, source="bar_open",
        bar_open_ms=START_MS + HOUR_MS,
    )

    waiting = schedule(quote, received_at_ms=START_MS + HOUR_MS + 90_000, decision_ts_ms=START_MS, max_age_ms=HOUR_MS)
    assert waiting.status == "WAIT"

    filled = schedule(quote, received_at_ms=START_MS + 90_000, decision_ts_ms=START_MS, max_age_ms=HOUR_MS)
    assert filled.status == "FILL" and filled.lag_ms == HOUR_MS - 90_000

    expired = schedule(
        quote,
        received_at_ms=START_MS + HOUR_MS,
        decision_ts_ms=START_MS - HOUR_MS,
        max_age_ms=HOUR_MS,
    )
    assert expired.status == "EXPIRED"


# -- B-03: la vela de entrada se comprueba contra el stop ------------------------


def entry_bar_stop_series() -> list[Bar]:
    """La única vela que perfora el stop es la de la entrada.

    La primera decisión cae en el índice 30 y, con 90 s de latencia, su cotización es la
    apertura del índice 32 (el 31 abre *antes* de que llegue la respuesta). Esa vela baja
    un 1 % — el stop está al 0,5 % — y recupera dentro de la misma vela; después el precio
    sólo sube, así que ninguna vela posterior vuelve a tocar el stop.
    """

    def pierce(natural: float) -> tuple[float, float, float, float]:
        return (natural, natural * 1.002, natural * 0.990, natural * 1.001)

    return build_series(patches={32: pierce})


def test_the_bar_a_position_is_opened_on_is_checked_for_stops(tmp_path):
    summary, rows = run_lane(tmp_path, bars=entry_bar_stop_series(), latency_ms=90_000)
    closes = of_kind(rows, "CLOSE")
    stops = [row for row in closes if row["exit_reason"] == "stop_loss"]

    assert stops, (
        "the entry bar's low pierced the stop and the check must run after the fill; "
        f"fills={summary['fills']} closes={[(r['exit_reason'], r['exit_price']) for r in closes]}"
    )
    fill = of_kind(rows, "FILL")[0]
    assert stops[0]["exit_ts_lower_bound_ms"] == fill["quote_ts_ms"], (
        "the exit happened inside the entry bar, so its known window starts at the entry"
    )
    assert stops[0]["exit_ts_resolution"] == "bar"


# -- B-04: un hueco se rellena en la apertura, no en el nivel del stop -----------


def gap_through_stop_series() -> list[Bar]:
    """Entrada en el 32 y hueco a la baja del 3 % en la apertura del 33."""

    def entry(natural: float) -> tuple[float, float, float, float]:
        return (natural, natural * 1.002, natural * 0.999, natural * 1.000)

    def gap(natural: float) -> tuple[float, float, float, float]:
        open_price = natural * 0.97
        return (open_price, open_price * 1.004, open_price * 0.996, open_price * 1.002)

    return build_series(patches={32: entry, 33: gap})


def test_a_gap_through_the_stop_fills_at_the_gap_not_at_the_stop(tmp_path):
    _, rows = run_lane(tmp_path, bars=gap_through_stop_series(), latency_ms=90_000)
    fills = of_kind(rows, "FILL")
    stops = [row for row in of_kind(rows, "CLOSE") if row["exit_reason"] == "stop_loss"]

    assert fills and stops, "the scenario must produce the stop it is about"
    entry_price = fills[0]["entry_price"]
    stop_level = fills[0]["stop_loss_price"]
    assert entry_price > 0 and stop_level < entry_price
    assert stops[0]["exit_price"] < stop_level, (
        "filling at the stop after gapping through it understates the loss: the first "
        f"tradable quote was the gap open; exit={stops[0]['exit_price']} stop={stop_level}"
    )
    assert stops[0]["exit_price"] <= fills[0]["entry_price"] * 0.98


# -- B-05: reconciliación neta ---------------------------------------------------


def test_the_run_reconciles_cash_pnl_costs_and_the_risk_engine(tmp_path):
    summary, rows = run_lane(tmp_path, bars=build_series(), latency_ms=90_000)
    reconciliation = summary.get("reconciliation")

    assert reconciliation is not None, "a run without reconciliation cannot be audited"
    assert reconciliation["identities"]["cash_rebuilds_from_realised_pnl"] is True
    assert reconciliation["identities"]["net_pnl_nets_every_named_cost"] is True
    assert reconciliation["identities"]["risk_equity_matches_marked_equity"] is True
    assert reconciliation["identities"]["curve_ends_at_final_equity"] is True

    assert reconciliation["initial_equity_usdt"] == 10_000.0
    assert reconciliation["final_equity_usdt"] == pytest.approx(
        10_000.0 + reconciliation["net_realised_usdt"], abs=1e-6
    )
    assert summary["risk_equity_usdt"] == pytest.approx(reconciliation["marked_equity_usdt"], abs=1e-6)
    assert of_kind(rows, "RUN")


def test_every_close_starts_at_or_after_the_quote_that_opened_it(tmp_path):
    _, rows = run_lane(tmp_path, bars=entry_bar_stop_series(), latency_ms=90_000)
    closes = of_kind(rows, "CLOSE")

    assert closes, "a run with no closed trade cannot prove an ordering"
    for close in closes:
        assert close["entry_quote_ts_ms"] is not None
        assert close["ts_ms"] >= close["entry_quote_ts_ms"], (
            "an exit cannot precede the quote that opened the position"
        )
        assert close["ts_ms"] >= close["entry_received_at_ms"], (
            "nor can it precede the answer that produced the entry"
        )
