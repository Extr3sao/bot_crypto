"""003J — the experimental signal source must be real, point-in-time and reversible.

The tests target the adapter that the PAPER session actually builds (not a copy), and
each one names the claim it holds:

* the window is cut at the bar the chart closed on, and bars after it cannot change the
  answer (point-in-time);
* a bar that had not closed by the decision instant is refused, not trimmed
  (look-ahead);
* every failure is a typed ``NO_TRADE``, never the scripted rotation (no fallback);
* the answer for one asset does not depend on the order assets are evaluated in
  (per-asset independence);
* the two indicator paths agree, so the numbers in the trace are the numbers the family
  used (tested implementation == runtime implementation);
* the default source is still the legacy script, and the experimental one refuses a
  non-PAPER mode (rollback stays a flag flip).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.vision.chart import ChartImage
from trading_bot.vision.prompt import PromptBundle
from trading_bot.vision.provider import VisionRequest
from trading_bot.vision.signal_sources import (
    DECLARED_CONFIDENCE,
    SIGNAL_SOURCE_LEGACY,
    STRATEGY_EMA_CROSSOVER,
    SignalSourceConfigError,
    StrategySignalProvider,
    build_signal_provider,
    compute_indicators,
    point_in_time_window,
)

BAR_MS = 300_000
T0 = 1_800_000_000_000 - (1_800_000_000_000 % BAR_MS)


def _bar(index: int, price: float, *, symbol: str = "BTC/USDT") -> Bar:
    return Bar(
        ts_ms=T0 + index * BAR_MS,
        open=price,
        high=price * 1.0009,
        low=price * 0.9991,
        close=price * 1.0002,
        volume=10.0 + index,
    )


def _series(count: int = 80, *, start: float = 100.0, rising: bool = True) -> list[Bar]:
    step = 0.35 if rising else -0.35
    return [_bar(index, start + index * step) for index in range(count)]


def _request(
    *,
    symbol: str,
    last_index: int,
    decision_ts_ms: int | None = None,
) -> VisionRequest:
    last_open = T0 + last_index * BAR_MS
    chart = ChartImage(
        png=b"",
        sha256=f"chart-{symbol}-{last_open}",
        symbol=symbol,
        timeframe="5m",
        bar_count=60,
        first_ts_ms=T0,
        last_ts_ms=last_open,
    )
    prompt = PromptBundle(system="s", user="u", version="test-prompt/1")
    return VisionRequest(
        chart=chart,
        prompt=prompt,
        decision_ts_ms=int(decision_ts_ms if decision_ts_ms is not None else last_open + BAR_MS),
        detail="high",
    )


def _provider(
    series: dict[str, list[Bar]],
    *,
    trace_path: Path | None = None,
    window_bars: int = 60,
) -> StrategySignalProvider:
    return StrategySignalProvider(
        series=series,
        timeframe="5m",
        interval_ms=BAR_MS,
        window_bars=window_bars,
        trace_path=trace_path,
    )


def _payload(response: object) -> dict[str, object]:
    return json.loads(response.text)


# --------------------------------------------------------------------------- PIT


def test_window_is_cut_at_the_bar_the_chart_closed_on() -> None:
    bars = _series(80)
    window = point_in_time_window(
        {"BTC/USDT": bars},
        "BTC/USDT",
        last_open_ms=bars[40].ts_ms,
        interval_ms=BAR_MS,
        decision_ts_ms=bars[40].ts_ms + BAR_MS,
        limit=60,
    )
    assert window.last_open_ms == bars[40].ts_ms
    assert all(bar.ts_ms <= bars[40].ts_ms for bar in window.bars)
    assert len(window.bars) == 41


def test_future_bars_cannot_change_the_answer(tmp_path: Path) -> None:
    """The sharpest PIT test: rewrite everything after the decision and re-ask."""

    bars = _series(80)
    provider = _provider({"BTC/USDT": bars}, trace_path=tmp_path / "trace.jsonl")
    request = _request(symbol="BTC/USDT", last_index=50)
    first = _payload(provider.analyze(request))

    mutated = [bar for bar in bars[:51]] + [
        Bar(
            ts_ms=bar.ts_ms,
            open=bar.close * 0.5,
            high=bar.close * 3.0,
            low=bar.close * 0.25,
            close=bar.close * 2.0,
            volume=1e9,
        )
        for bar in bars[51:]
    ]
    second = _payload(_provider({"BTC/USDT": mutated}).analyze(request))
    assert first == second

    trace = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert trace[0]["max_input_data_time_ms"] <= request.decision_ts_ms
    assert trace[0]["market_data_fingerprint"]


def test_a_bar_that_had_not_closed_is_refused_not_trimmed() -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars})
    # Decision stamped one millisecond before the bar's close: the bar cannot inform it.
    request = _request(
        symbol="BTC/USDT", last_index=50, decision_ts_ms=bars[50].ts_ms + BAR_MS - 1
    )
    payload = _payload(provider.analyze(request))
    assert payload["action"] == "NO_TRADE"
    assert str(payload["rationale"]).startswith("BAR_CLOSED_AFTER_DECISION")
    assert provider.blocked == 1


def test_a_chart_about_a_bar_the_series_does_not_have_is_refused() -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars})
    request = _request(symbol="BTC/USDT", last_index=90)
    payload = _payload(provider.analyze(request))
    assert payload["action"] == "NO_TRADE"
    assert str(payload["rationale"]).startswith("DECISION_BAR_NOT_IN_SERIES")


# ------------------------------------------------------------------- decisions


def test_a_rising_window_produces_a_long_with_a_structural_stop() -> None:
    bars = _series(80, rising=True)
    payload = _payload(_provider({"BTC/USDT": bars}).analyze(_request(symbol="BTC/USDT", last_index=70)))
    assert payload["action"] == "LONG"
    assert payload["stop_loss_pct"] is not None
    assert float(payload["stop_loss_pct"]) > 0.0
    # No take-profit is invented: the policy's target is the only target.
    assert payload["take_profit_pct"] is None
    assert payload["confidence"] == DECLARED_CONFIDENCE


def test_a_falling_window_produces_a_short() -> None:
    bars = _series(80, rising=False)
    payload = _payload(_provider({"BTC/USDT": bars}).analyze(_request(symbol="BTC/USDT", last_index=70)))
    assert payload["action"] == "SHORT"


def test_a_short_window_is_a_typed_no_trade_not_an_opinion() -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars}, window_bars=60)
    # A window of 21 bars is below the family's own 22-candle guard.
    request = _request(symbol="BTC/USDT", last_index=20)
    payload = _payload(provider.analyze(request))
    assert payload["action"] == "NO_TRADE"
    assert str(payload["rationale"]).startswith("INSUFFICIENT_WINDOW")


def test_a_missing_asset_never_falls_back_to_the_scripted_rotation() -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars})
    payload = _payload(provider.analyze(_request(symbol="ETH/USDT", last_index=70)))
    assert payload["action"] == "NO_TRADE"
    assert str(payload["rationale"]).startswith("ASSET_NOT_IN_SERIES")


def test_the_same_request_twice_gives_the_same_bytes() -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars})
    request = _request(symbol="BTC/USDT", last_index=70)
    assert provider.analyze(request).text == provider.analyze(request).text


def test_the_adapter_never_claims_to_have_sent_an_image() -> None:
    bars = _series(80)
    response = _provider({"BTC/USDT": bars}).analyze(_request(symbol="BTC/USDT", last_index=70))
    assert response.image_sha256_in_request == ""
    assert response.provider == "strategy-signal"
    assert response.cost_usd is None


# ----------------------------------------------------------------- independence


def test_asset_order_does_not_change_any_answer() -> None:
    btc = _series(80, start=100.0, rising=True)
    eth = _series(80, start=2_000.0, rising=False)
    sol = _series(80, start=50.0, rising=True)
    symbols = {"BTC/USDT": btc, "ETH/USDT": eth, "SOL/USDT": sol}

    forward = {}
    provider = _provider(symbols)
    for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        forward[symbol] = provider.analyze(_request(symbol=symbol, last_index=70)).text

    backward = {}
    provider = _provider(dict(reversed(list(symbols.items()))))
    for symbol in ("SOL/USDT", "ETH/USDT", "BTC/USDT"):
        backward[symbol] = provider.analyze(_request(symbol=symbol, last_index=70)).text

    assert forward == backward


def test_each_symbol_gets_its_own_fingerprint() -> None:
    symbols = {
        "BTC/USDT": _series(80, start=100.0, rising=True),
        "ETH/USDT": _series(80, start=2_000.0, rising=False),
    }
    provider = _provider(symbols)
    a = provider.analyze(_request(symbol="BTC/USDT", last_index=70))
    b = provider.analyze(_request(symbol="ETH/USDT", last_index=70))
    assert json.loads(a.text)["symbol"] != json.loads(b.text)["symbol"]
    assert json.loads(a.text)["action"] != json.loads(b.text)["action"]


# --------------------------------------------------------------- tested == shown


def test_the_traced_indicators_are_the_ones_the_family_uses() -> None:
    candles = [_candle(bar) for bar in _series(80)]
    assert compute_indicators(candles) == EmaCrossoverFamily._compute_indicators(candles)


def _candle(bar: Bar) -> object:
    from trading_bot.market_data.types import OHLCV

    return OHLCV(
        symbol="BTC/USDT",
        timestamp=int(bar.ts_ms),
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=float(bar.volume),
    )


def test_the_trace_row_carries_every_field_the_rfc_names(tmp_path: Path) -> None:
    bars = _series(80)
    provider = _provider({"BTC/USDT": bars}, trace_path=tmp_path / "trace.jsonl")
    provider.analyze(_request(symbol="BTC/USDT", last_index=70))
    row = json.loads((tmp_path / "trace.jsonl").read_text().splitlines()[0])
    for key in (
        "asset",
        "timeframe",
        "strategy_id",
        "strategy_version",
        "strategy_classification",
        "decision_time_utc",
        "max_input_data_time_utc",
        "market_data_fingerprint",
        "action",
        "proposal_id",
        "evidence_refs",
        "counter_evidence_refs",
        "invalidation",
        "reason_code",
        "quality_status",
    ):
        assert key in row, key
    assert row["strategy_id"] == STRATEGY_EMA_CROSSOVER
    assert row["strategy_classification"] == "RUNTIME_REACHABLE"


# --------------------------------------------------------------------- factory


def test_the_default_source_is_still_the_legacy_script() -> None:
    assert SIGNAL_SOURCE_LEGACY == "legacy_parity"
    provider = build_signal_provider(
        SIGNAL_SOURCE_LEGACY,
        series={},
        timeframe="5m",
        interval_ms=BAR_MS,
        window_bars=60,
    )
    assert provider.name == "paper-script"
    actions = [
        json.loads(provider.analyze(_request(symbol="BTC/USDT", last_index=70)).text)["action"]
        for _ in range(4)
    ]
    assert actions == ["LONG", "NO_TRADE", "SHORT", "NO_TRADE"]


def test_an_unknown_source_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(SignalSourceConfigError):
        build_signal_provider(
            "market_opinion",
            series={},
            timeframe="5m",
            interval_ms=BAR_MS,
            window_bars=60,
        )


def test_the_experimental_source_refuses_a_non_paper_mode() -> None:
    with pytest.raises(SignalSourceConfigError):
        StrategySignalProvider(
            series={},
            timeframe="5m",
            interval_ms=BAR_MS,
            window_bars=60,
            mode="LIVE",
        )


def test_an_unadmitted_strategy_id_is_refused() -> None:
    with pytest.raises(SignalSourceConfigError):
        StrategySignalProvider(
            series={},
            timeframe="5m",
            interval_ms=BAR_MS,
            window_bars=60,
            strategy_id="macd_regime",
        )


def test_a_window_below_the_family_guard_is_refused_at_construction() -> None:
    with pytest.raises(SignalSourceConfigError):
        StrategySignalProvider(
            series={}, timeframe="5m", interval_ms=BAR_MS, window_bars=10
        )
