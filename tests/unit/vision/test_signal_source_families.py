"""003K — la fuente experimental admite más de una familia, y lo demuestra.

003J probó el adaptador contra **una** familia. 003K abre el registro a las otras cinco que
ya existían en ``research/families``, así que las propiedades que 003J fijó para una tienen
que valer para todas, y una nueva tiene que valer para el registro:

1. toda familia admitida construye, responde y devuelve una decisión del contrato — nunca
   lanza ni se queda sin contestar;
2. el mínimo de velas que exige el adaptador es el de la propia familia, ni uno menos, y una
   ventana corta se rechaza al construir en vez de convertirse en un ``NO_TRADE`` mudo;
3. el motivo tipado distingue "faltan velas" de "la familia no ve dirección";
4. la clasificación de la traza es la de cada estrategia, no una constante;
5. el orden de los activos no cambia ninguna respuesta, tampoco para las familias nuevas;
6. el registro y las clases que nombra no pueden divergir;
7. ``ProspectiveConfig`` admite cada estrategia con su ventana y rechaza la de otra.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.chart import ChartImage
from trading_bot.vision.prompt import PromptBundle
from trading_bot.vision.prospective import ProspectiveConfig
from trading_bot.vision.provider import VisionRequest
from trading_bot.vision.signal_sources import (
    SIGNAL_SOURCE_STRATEGY,
    STRATEGY_SPECS,
    SUPPORTED_STRATEGIES,
    SignalSourceConfigError,
    StrategySignalProvider,
)

BAR_MS = 300_000
T0 = 1_800_000_000_000 - (1_800_000_000_000 % BAR_MS)


def _bar(index: int, price: float) -> Bar:
    return Bar(
        ts_ms=T0 + index * BAR_MS,
        open=price,
        high=price * 1.0012,
        low=price * 0.9988,
        close=price * 1.0004,
        volume=12.0 + index,
    )


def _series(count: int = 90, *, start: float = 100.0, step: float = 0.25) -> list[Bar]:
    return [_bar(index, start + index * step) for index in range(count)]


def _request(symbol: str, last_index: int) -> VisionRequest:
    last_open = T0 + last_index * BAR_MS
    return VisionRequest(
        chart=ChartImage(
            png=b"",
            sha256=f"chart-{symbol}-{last_open}",
            symbol=symbol,
            timeframe="5m",
            bar_count=60,
            first_ts_ms=T0,
            last_ts_ms=last_open,
        ),
        prompt=PromptBundle(system="s", user="u", version="test-prompt/1"),
        decision_ts_ms=last_open + BAR_MS,
        detail="high",
    )


def _provider(
    strategy_id: str,
    series: dict[str, list[Bar]] | None = None,
    *,
    window_bars: int | None = None,
    trace_path: Path | None = None,
) -> StrategySignalProvider:
    spec = STRATEGY_SPECS[strategy_id]
    return StrategySignalProvider(
        series=series if series is not None else {"BTC/USDT": _series()},
        timeframe="5m",
        interval_ms=BAR_MS,
        window_bars=max(spec.min_candles, window_bars or 0, 60),
        strategy_id=strategy_id,
        trace_path=trace_path,
    )


def _payload(response) -> dict:  # type: ignore[no-untyped-def]
    return json.loads(response.text)


def test_the_registry_is_the_closed_set_of_admitted_strategies() -> None:
    assert tuple(STRATEGY_SPECS) == SUPPORTED_STRATEGIES
    assert len(STRATEGY_SPECS) == 6


def test_every_admitted_strategy_is_named_by_the_class_it_wraps() -> None:
    for strategy_id, spec in STRATEGY_SPECS.items():
        family = spec.family_cls()
        assert family.family_name == spec.family_name, strategy_id
        assert spec.min_candles > 0
        assert spec.classification in {"RUNTIME_REACHABLE", "EXPERIMENTAL_PAPER"}
    # Exactly one strategy is the one the canonical runtime already executes.
    runtime = [key for key, spec in STRATEGY_SPECS.items() if spec.classification == "RUNTIME_REACHABLE"]
    assert runtime == ["ema_crossover"]


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_every_admitted_strategy_answers_with_a_decision(strategy_id: str) -> None:
    provider = _provider(strategy_id)
    response = provider.analyze(_request("BTC/USDT", 89))
    payload = _payload(response)

    assert payload["schema_version"] == "ai-vision-decision/1"
    assert payload["action"] in {"LONG", "SHORT", "NO_TRADE"}
    assert payload["rationale"]
    assert provider.calls == 1
    # A directional answer must carry a stop; a refusal must not invent one.
    if payload["action"] == "NO_TRADE":
        assert payload["stop_loss_pct"] is None
    else:
        assert 0.0 < float(payload["stop_loss_pct"]) <= 25.0


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_the_adapter_refuses_one_candle_below_the_family_guard(strategy_id: str) -> None:
    spec = STRATEGY_SPECS[strategy_id]
    with pytest.raises(SignalSourceConfigError):
        StrategySignalProvider(
            series={"BTC/USDT": _series()},
            timeframe="5m",
            interval_ms=BAR_MS,
            window_bars=spec.min_candles - 1,
            strategy_id=strategy_id,
        )
    # ... and accepts exactly the family's own minimum, so the boundary is the family's.
    StrategySignalProvider(
        series={"BTC/USDT": _series()},
        timeframe="5m",
        interval_ms=BAR_MS,
        window_bars=spec.min_candles,
        strategy_id=strategy_id,
    )


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_a_short_series_is_a_typed_refusal_not_a_silent_no_trade(strategy_id: str) -> None:
    provider = _provider(strategy_id, {"BTC/USDT": _series(count=5)})
    payload = _payload(provider.analyze(_request("BTC/USDT", 4)))

    assert payload["action"] == "NO_TRADE"
    assert payload["rationale"].startswith("INSUFFICIENT_WINDOW")
    assert provider.no_trade == 1


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_the_trace_carries_the_strategy_own_classification(
    strategy_id: str, tmp_path: Path
) -> None:
    trace = tmp_path / f"{strategy_id}.jsonl"
    provider = _provider(strategy_id, trace_path=trace)
    provider.analyze(_request("BTC/USDT", 89))

    row = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
    assert row["strategy_id"] == strategy_id
    assert row["strategy_classification"] == STRATEGY_SPECS[strategy_id].classification
    # The trace may only name data that closed at or before the decision instant.
    if row.get("max_input_data_time_ms") is not None:
        assert int(row["max_input_data_time_ms"]) <= int(row["decision_time_ms"])


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_asset_order_does_not_change_any_answer(strategy_id: str) -> None:
    series = {"BTC/USDT": _series(start=100.0, step=0.25), "ETH/USDT": _series(start=50.0, step=-0.15)}

    first = _provider(strategy_id, series)
    forward = [
        _payload(first.analyze(_request(symbol, 89)))["action"]
        for symbol in ("BTC/USDT", "ETH/USDT")
    ]
    second = _provider(strategy_id, series)
    backward = [
        _payload(second.analyze(_request(symbol, 89)))["action"]
        for symbol in ("ETH/USDT", "BTC/USDT")
    ]
    assert forward == list(reversed(backward))


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_SPECS))
def test_a_prospective_session_admits_the_strategy_with_its_own_window(
    strategy_id: str,
) -> None:
    spec = STRATEGY_SPECS[strategy_id]
    config = ProspectiveConfig(
        signal_source=SIGNAL_SOURCE_STRATEGY,
        strategy_id=strategy_id,
        window_bars=spec.min_candles,
    )
    assert config.strategy_id == strategy_id

    if spec.min_candles > 1:
        with pytest.raises(SignalSourceConfigError):
            ProspectiveConfig(
                signal_source=SIGNAL_SOURCE_STRATEGY,
                strategy_id=strategy_id,
                window_bars=spec.min_candles - 1,
            )
