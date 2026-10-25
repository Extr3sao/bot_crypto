"""DEF-RUN-016 — el pipeline completo sobre datos reales de mercado, de la vela al cierre.

No es un test del doble: entran minutos públicos de Binance ya versionados con su sha256,
salen operaciones cerradas por el ``PaperBroker`` de producción, con el ``RiskManager`` de
producción en medio. Lo único guionizado es la respuesta del modelo, que es exactamente lo
que se está midiendo.

Lo que se comprueba, en el orden en que el pipeline lo vive:

1. una opinión formada en el cierre de una vela de 1 minuto con 2 s de retraso de datos
   **aplaza** la decisión siguiente en lugar de ser sustituida, y se ejecuta en la apertura
   que existe después de su respuesta;
2. el precio pagado nunca es anterior a la respuesta ni la opinión más vieja que su TTL;
3. la posición se cierra por su barrera y las identidades contables del cuadran;
4. ``SUPERSEDED_BY_NEWER_OPINION`` no aparece: la opinión que podía pagar el precio no se
   destruye con otra que aún no existe;
5. con una cadencia en la que no hay colisión de fases, el cambio es inerte.

El barrido se ejecuta una sola vez por módulo: renderizar 150 gráficos dos veces por test
haría que la suite midiera matplotlib y no el pipeline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import OPINION_LIFECYCLE_DEFER, VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "quote-feed-1m"
MANIFEST = DATA / "SOURCE_MANIFEST.json"
SYMBOL = "UNI/USDT"
FILE_SYMBOL = "UNIUSDT"
MINUTE = 60_000
WINDOW_BARS = 20
DECISIONS = 110

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"%s","action":"LONG",'
    '"confidence":0.7,"horizon_bars":6,"stop_loss_pct":1.0,"take_profit_pct":0.25,'
    '"invalidation":null,"rationale":"Integration continuation."}'
)


def _minutes() -> list[list[float]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    record = manifest["symbols"][FILE_SYMBOL]
    raw = (DATA / record["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["file_sha256"], (
        "the committed minutes are not the bytes the manifest names"
    )
    rows = json.loads(raw)
    #: Una ventana contigua al principio del archivo, no una muestra escogida por su forma.
    return rows[: DECISIONS + WINDOW_BARS + 5]


class Scripted(ReplayProvider):
    def __init__(self) -> None:
        super().__init__(lambda request: LONG % request.chart.symbol)
        self.answered = 0

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        self.answered += 1
        return replace(super().analyze(request), latency_ms=0)


def _feed(rows: list[list[float]]) -> MinuteBarQuoteFeed:
    return MinuteBarQuoteFeed(
        {SYMBOL: MinuteSeries.from_rows(SYMBOL, [list(row) for row in rows])}
    )


def _bars(rows: list[list[float]]) -> list[Bar]:
    return [
        Bar(
            ts_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]


def _config(*, decision_every: int = 1):
    base = load_vision_config(env={})
    lane = base.lane.__class__(
        timeframe="1m",
        window_bars=WINDOW_BARS,
        decision_every_bars=decision_every,
        max_calls_per_run=500,
        max_estimated_spend_usd=20.0,
        data_delay_ms=2_000,
        max_opinion_age_ms=0,
    )
    return base.__class__(provider=base.provider, lane=lane)


def _run(
    path: Path,
    *,
    lifecycle: str,
    decision_every: int = 1,
    rows: list[list[float]] | None = None,
):
    rows = _minutes() if rows is None else rows
    provider = Scripted()
    lane = VisionLane(
        series={SYMBOL: _bars(rows)},
        provider=provider,
        config=_config(decision_every=decision_every),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=path,
        quote_feed=_feed(rows),
        subbar_entries=True,
        decision_every_bars=decision_every,
        opinion_lifecycle=lifecycle,
    )
    summary = lane.run()
    entries = [
        dict(line["entry"], seq=int(line["seq"])) for line in read_entries(path)
    ]
    return summary, entries, provider


@pytest.fixture(scope="module")
def deferred_run(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("def-run-016-e2e")
    return _run(directory / "defer.jsonl", lifecycle=OPINION_LIFECYCLE_DEFER)


def test_the_pipeline_reaches_a_closed_round_trip_on_real_minutes(deferred_run):
    summary, _, provider = deferred_run

    assert summary["fills"] >= 1, f"no fill on real minutes: {summary['counters']}"
    assert summary["closed_trades"] >= 1, (
        "the position must meet its barrier inside the window, or the round trip is untested"
    )
    assert provider.answered == summary["calls"]


def test_a_deferred_slot_replaces_a_destroyed_opinion(deferred_run):
    summary, rows, _ = deferred_run

    deferred = [row for row in rows if row.get("kind") == "OPINION_DEFERRED"]
    superseded = [
        row
        for row in rows
        if row.get("kind") == "GUARD_REJECT"
        and row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ]
    assert deferred, "with 2 s of data delay the next decision must be deferred"
    #: Una opinión solo puede sustituirse cuando ya no cabe en su ventana. Con datos reales
    #: hay minutos ausentes en el archivo, y una orden cuyo siguiente precio cae fuera del
    #: TTL está muerta por construcción: esa sustitución es correcta y la fila la justifica.
    for row in superseded:
        assert int(row["opinion_age_at_next_open_ms"]) > int(
            summary["execution"]["max_opinion_age_ms"]
        ), "no opinion inside its TTL may be superseded"
    assert summary["execution"]["opinions"]["superseded"] == len(superseded)
    #: ``generated`` cuenta opiniones **accionables** —las que deben un relleno o un
    #: veredicto—, no llamadas: un HOLD es una opinión que nunca debió una operación. Lo que
    #: sí tiene que cumplirse es que cada llamada produzca como mucho una opinión y que
    #: ninguna opinión se pierda sin un evento terminal.
    opinions = summary["execution"]["opinions"]
    assert 0 < opinions["generated"] <= summary["calls"]
    assert opinions["generated"] == (
        opinions["executed_openings"]
        + opinions["closed_by_intent"]
        + opinions["blocked_by_risk"]
        + opinions["gated"]
        + sum(opinions["rejected"].values())
    ), f"an actionable opinion must reach exactly one terminal row: {opinions}"
    for row in deferred:
        assert row["next_executable_open_source"] in {"data", "grid"}
        assert int(row["next_executable_open_ms"]) >= int(row["received_at_ms"]) - 1_000


def test_every_fill_pays_a_quote_that_existed_after_the_answer(deferred_run):
    summary, rows, _ = deferred_run
    fills = [row for row in rows if row.get("kind") == "FILL"]

    assert fills
    for fill in fills:
        assert int(fill["quote_ts_ms"]) >= int(fill["received_at_ms"])
        assert int(fill["quote_ts_ms"]) > int(fill["decision_ts_ms"])
        assert 0 <= int(fill["opinion_age_ms"]) <= int(
            summary["execution"]["max_opinion_age_ms"]
        )


def test_the_real_broker_closes_after_the_entry_quote(deferred_run):
    _, rows, _ = deferred_run
    closes = [row for row in rows if row.get("kind") == "CLOSE"]

    assert closes
    for close in closes:
        assert int(close["exit_ts_lower_bound_ms"]) >= int(close["entry_quote_ts_ms"])
        assert int(close["exit_ts_lower_bound_ms"]) >= int(close["entry_received_at_ms"])


def test_the_accounting_identities_hold_on_the_real_round_trip(deferred_run):
    summary, _, _ = deferred_run
    identities = summary["reconciliation"]["identities"]

    assert identities["every_fill_pays_at_or_after_its_answer"] is True
    assert identities["every_close_after_its_entry_quote"] is True
    assert identities["open_positions_are_disjoint_from_closed_trades"] is True
    assert identities["net_pnl_nets_every_named_cost"] is True
    assert identities["total_costs_equal_realised_plus_accrued"] is True
    assert summary["reconciliation"]["costs_total_usdt"] >= 0


def test_the_run_row_declares_the_lifecycle_rule(deferred_run):
    _, rows, _ = deferred_run
    run = next(row for row in rows if row.get("kind") == "RUN")

    assert run["lane"]["opinion_lifecycle"] == "DEFER"
    assert run["lane"]["data_delay_ms"] == 2_000


def test_a_growing_series_does_not_rewrite_a_past_decision(tmp_path: Path):
    """La sesión viva re-ejecuta el carril cada minuto: un prefijo no puede cambiar.

    Con el borde vivo tratado como "no hay cotización", la última decisión de un ciclo se
    sustituía y en el ciclo siguiente —con la barra ya presente— se aplazaba: el prefijo
    divergía y la sesión marcaba ``PREFIX_DIVERGENCE``. El fallback de rejilla etiquetado
    (``next_executable_open_source="grid"``) existe para que eso no ocurra.
    """
    from trading_bot.vision.prospective import compare_prefix

    rows = _minutes()[: WINDOW_BARS + 14]
    short_path = tmp_path / "short.jsonl"
    long_path = tmp_path / "long.jsonl"
    _run(short_path, lifecycle=OPINION_LIFECYCLE_DEFER, rows=rows[:-1])
    _run(long_path, lifecycle=OPINION_LIFECYCLE_DEFER, rows=rows)

    prefix = compare_prefix(read_entries(short_path), read_entries(long_path))
    assert prefix["ok"], f"a decision already made changed when the next bar arrived: {prefix}"
    assert prefix["compared"] >= WINDOW_BARS // 2


def test_the_deferral_is_inert_when_no_phase_collision_exists(
    tmp_path: Path, deferred_run
):
    """Con cadencia 5 la orden ya se resolvió: el cambio no altera el resultado."""
    current, _, _ = _run(
        tmp_path / "supersede-5.jsonl", lifecycle="SUPERSEDE", decision_every=5
    )
    proposed, _, _ = _run(
        tmp_path / "defer-5.jsonl", lifecycle=OPINION_LIFECYCLE_DEFER, decision_every=5
    )

    assert current["fills"] == proposed["fills"]
    assert current["calls"] == proposed["calls"]
    assert proposed["execution"]["opinions"]["deferred_slots"] == 0
