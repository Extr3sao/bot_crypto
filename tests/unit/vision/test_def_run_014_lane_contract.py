"""DEF-RUN-014 en el lane de producción — modelo → riesgo → orden → ledger.

El defecto vivía en ``VisionLane._execute``: el ``Signal`` que llegaba al
``RiskManager`` no llevaba ``stop_loss_pct``, así que el manager aplicaba el default de
política y el stop del modelo se quedaba en una columna informativa. Estos tests ejecutan
``VisionLane.run`` con el ``PaperBroker`` y el ``RiskManager`` reales
(``TEST_TARGET == RUNTIME_TARGET``) y comprueban la cadena completa desde los bytes del
ledger:

* el stop efectivo de la fila ``FILL`` es el que declaró el modelo;
* el precio de stop del libro es exactamente ``entry × (1 ∓ pct/100)``;
* la fila publica origen, motivo, distancia, coste de ida y vuelta y dinero en riesgo;
* un stop más corto que su propio coste no abre nada (``NO_TRADE`` con causa);
* dos corridas idénticas escriben el mismo ledger.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 10, 19, tzinfo=UTC).timestamp() * 1000)
REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"

#: 100 bps: limpia el coste de ida y vuelta del modelo de costes (24.79 bps a 500 USDT).
WIDE_STOP = 1.0
WIDE_TAKE = 2.0
#: 20 bps: por debajo del coste de ida y vuelta. No es un límite de pérdida ejecutable.
TIGHT_STOP = 0.2


def _answer(symbol: str, action: str, stop: float, take: float) -> str:
    return (
        f'{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
        f'"confidence":0.6,"horizon_bars":6,"stop_loss_pct":{stop},"take_profit_pct":{take},'
        '"invalidation":null,"rationale":"DEF-RUN-014 contract."}'
    )


class FirstLongThenFlat(ReplayProvider):
    def __init__(self, *, stop: float, take: float) -> None:
        self.stop = stop
        self.take = take
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request: Any) -> str:
        self.seen += 1
        action = "LONG" if self.seen == 1 else "NO_TRADE"
        return _answer(request.chart.symbol, action, self.stop, self.take)

    def analyze(self, request: Any) -> VisionResponse:
        return replace(super().analyze(request), latency_ms=0)


def _bars(path: list[tuple[float, float]]) -> list[Bar]:
    out: list[Bar] = []
    for index, (opened, closed) in enumerate(path):
        pad = 0.0005
        out.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=opened,
                high=max(opened, closed) * (1.0 + pad),
                low=min(opened, closed) * (1.0 - pad),
                close=closed,
                volume=100.0 + index,
            )
        )
    return out


FLAT = [(100.0, 100.0)] * 21
UP = [*FLAT, (100.0, 101.0), (101.0, 101.2)]


def _config() -> Any:
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1h",
            window_bars=20,
            decision_every_bars=1,
            max_calls_per_run=50,
            max_estimated_spend_usd=1.0,
            data_delay_ms=0,
        ),
    )


def _run(tmp_path: Path, *, stop: float, take: float, name: str = "book"):
    ledger = tmp_path / f"{name}.jsonl"
    lane = VisionLane(
        series={SYMBOL: _bars(UP)},
        provider=FirstLongThenFlat(stop=stop, take=take),
        config=_config(),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        equity=10_000.0,
        book_id="def-run-014-book",
        decision_every_bars=1,
    )
    summary = lane.run()
    return lane, summary, [row["entry"] for row in read_entries(ledger)]


def _only(entries: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    rows = [entry for entry in entries if entry.get("kind") == kind]
    assert len(rows) == 1, f"expected exactly one {kind} row, got {len(rows)}"
    return rows[0]


def _outcome(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        entry
        for entry in entries
        if entry.get("kind") == "DECISION_OUTCOME" and entry.get("risk_gate") == "check_signal"
    ]
    assert rows, "no check_signal outcome was written"
    return rows[0]


def test_the_fill_carries_the_model_stop_not_the_policy_default(tmp_path):
    lane, summary, entries = _run(tmp_path, stop=WIDE_STOP, take=WIDE_TAKE)

    assert summary["fills"] == 1
    fill = _only(entries, "FILL")
    assert fill["stop_loss_pct"] == pytest.approx(WIDE_STOP)
    assert fill["take_profit_pct"] == pytest.approx(WIDE_TAKE)
    assert fill["stop_source"] == "SIGNAL"
    assert fill["requested_stop_loss_pct"] == pytest.approx(WIDE_STOP)
    #: El defecto dejaba 0.5 aquí mientras el modelo había pedido 0.2/1.0.
    assert fill["stop_loss_pct"] != pytest.approx(0.5)

    position = lane.broker.positions[SYMBOL]
    assert position.stop_loss_pct == pytest.approx(WIDE_STOP)
    assert position.stop_loss_price == pytest.approx(position.entry_price * (1.0 - WIDE_STOP / 100.0))
    assert fill["stop_loss_price"] == pytest.approx(position.stop_loss_price)


def test_the_ledger_publishes_the_whole_stop_contract(tmp_path):
    _, _, entries = _run(tmp_path, stop=WIDE_STOP, take=WIDE_TAKE)
    outcome = _outcome(entries)

    assert outcome["requested_stop_loss_pct"] == pytest.approx(WIDE_STOP)
    assert outcome["effective_stop_loss_pct"] == pytest.approx(WIDE_STOP)
    assert outcome["stop_source"] == "SIGNAL"
    assert outcome["stop_reason"]
    assert outcome["stop_distance_bps"] == pytest.approx(WIDE_STOP * 100.0)
    assert outcome["round_trip_cost_bps"] > 0
    assert outcome["stop_clears_costs"] is True
    assert outcome["tick_size_check"] == "NOT_AVAILABLE"
    #: El dinero realmente en riesgo es notional × stop, no el presupuesto de riesgo.
    assert outcome["risk_at_stop_usdt"] == pytest.approx(
        outcome["notional_usdt"] * WIDE_STOP / 100.0, rel=1e-6
    )
    assert outcome["sizing_basis"] in {
        "RISK_BUDGET",
        "MAX_ORDER_NOTIONAL_CLAMP",
        "EXPOSURE_CLAMP",
        "ASSET_EXPOSURE_CLAMP",
    }
    assert outcome["model_stop_loss_pct"] == pytest.approx(WIDE_STOP)
    assert outcome["policy_stop_loss_pct"] == pytest.approx(WIDE_STOP)


def test_a_stop_inside_its_round_trip_opens_nothing(tmp_path):
    lane, summary, entries = _run(tmp_path, stop=TIGHT_STOP, take=WIDE_TAKE)

    assert summary["fills"] == 0
    assert lane.broker.positions == {}
    outcome = _outcome(entries)
    assert outcome["approved"] is False
    assert outcome["risk_blocked_by"] == "stop_inside_costs"
    assert outcome["stop_clears_costs"] is False
    assert outcome["round_trip_cost_bps"] > outcome["stop_distance_bps"]
    assert not [entry for entry in entries if entry.get("kind") == "FILL"]


#: ``recorded_at_utc`` is when the row was written, not what it says: two identical
#: replays differ there by construction and the comparison must skip it rather than be
#: weakened into "roughly the same".
VOLATILE = {"recorded_at_utc"}


def _stable(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key not in VOLATILE}


def test_the_same_inputs_write_the_same_ledger(tmp_path):
    _, _, first = _run(tmp_path, stop=WIDE_STOP, take=WIDE_TAKE, name="a")
    _, _, second = _run(tmp_path, stop=WIDE_STOP, take=WIDE_TAKE, name="b")

    assert [entry.get("kind") for entry in first] == [entry.get("kind") for entry in second]
    for left, right in zip(first, second, strict=True):
        if left.get("kind") in {"DECISION", "DECISION_OUTCOME", "FILL"}:
            assert _stable(left) == _stable(right)
