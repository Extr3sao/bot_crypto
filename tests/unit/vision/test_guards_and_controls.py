"""Matriz AIV: los ataques que el RFC exige responder con un NO_TRADE etiquetado.

Cubre, por código de rechazo: AIV-02 (activo cambiado), AIV-03 (PIT), AIV-04 (imagen
stale), AIV-05 (nivel inventado), AIV-06 (campo prohibido), AIV-10 (fin de semana),
AIV-11 (coste ausente) y el kill switch. Cada rechazo queda en el ledger con su código y
no produce ninguna orden.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.paper.broker import BrokerCost
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision import lane as lane_module
from trading_bot.vision.chart import render_chart_png
from trading_bot.vision.clock import timeframe_ms
from trading_bot.vision.guards import (
    OpinionRejected,
    assert_asset,
    assert_causal,
    assert_fresh,
    assert_level_inside_market,
    assert_tradeable_window,
    check_costs,
    is_weekend,
)
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
REPO = Path(__file__).resolve().parents[3]
#: 2026-03-07 00:00 UTC — a Saturday, so the weekend policy can be seen at work.
SATURDAY_MS = int(datetime(2026, 3, 7, tzinfo=UTC).timestamp() * 1000)
WEEKDAY_MS = int(datetime(2026, 3, 3, tzinfo=UTC).timestamp() * 1000)


def bars(count: int = 96, *, start: int = WEEKDAY_MS, drift: float = 0.004) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = -drift if i % 12 == 11 else drift
        close = price * (1.0 + step)
        out.append(
            Bar(
                ts_ms=start + i * HOUR_MS,
                open=price,
                high=max(price, close) * 1.002,
                low=min(price, close) * 0.998,
                close=close,
                volume=200.0,
            )
        )
        price = close
    return out


def policy(**overrides):
    risk = load_settings(config_dir=REPO / "config", env_file=None).risk
    return risk.model_copy(update=overrides) if overrides else risk


def vision_config(**lane_overrides):
    config = load_vision_config(env={})
    lane = config.lane
    merged = {
        "timeframe": lane.timeframe,
        "window_bars": 30,
        "decision_every_bars": 15,
        "max_calls_per_run": 40,
        "max_estimated_spend_usd": 5.0,
        **lane_overrides,
    }
    return config.__class__(provider=config.provider, lane=lane.__class__(**merged))


LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.7,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
    '"invalidation":null,"rationale":"Higher lows."}'
)


def run(tmp_path: Path, provider, *, series=None, risk_policy=None, **kwargs):
    resolved = series or bars()
    lane = VisionLane(
        series={"BTC/USDT": resolved},
        provider=provider,
        config=vision_config(),
        risk_policy=risk_policy or policy(),
        ledger_path=tmp_path / "d.jsonl",
        **kwargs,
    )
    return lane, lane.run()


def entries(path: Path) -> list[dict]:
    """Read the ledger whether the caller passes the file or its directory."""
    target = path if path.suffix == ".jsonl" else path / "d.jsonl"
    return [row["entry"] for row in read_entries(target)]


# ---------------------------------------------------------------- guards (unit)


def test_AIV_03_a_bar_that_had_not_closed_is_a_pit_violation():
    """AIV-03: `ts_ms` is the open, so the instant must be the close (BOT-03).

    The old version of this test asked whether a bar's *open* was after the decision
    instant, which every decision taken on that bar's close satisfies. It now asks what
    it meant to ask: had the last bar in the picture closed by then?
    """
    series = bars(20)
    interval = timeframe_ms("1h")

    # The close of the last bar is knowable, so every bar in the window has closed.
    assert_causal(series, series[-1].ts_ms + interval, bar_interval_ms=interval)
    # The instant the old code stamped on the decision: the last bar is still forming.
    with pytest.raises(OpinionRejected) as caught:
        assert_causal(series, series[-1].ts_ms, bar_interval_ms=interval)
    assert caught.value.code == "PIT_VIOLATION"


def test_AIV_04_a_chart_from_another_bar_is_stale():
    assert_fresh(1_000, 1_000)
    with pytest.raises(OpinionRejected) as caught:
        assert_fresh(1_000, 4_600_000)
    assert caught.value.code == "STALE_CHART"


def test_AIV_02_a_chart_of_another_asset_is_refused():
    assert_asset("BTC/USDT", "btc/usdt")
    with pytest.raises(OpinionRejected) as caught:
        assert_asset("BTC/USDT", "ETH/USDT")
    assert caught.value.code == "ASSET_MISMATCH"


def test_AIV_05_a_level_outside_the_market_is_invented():
    series = bars(30)
    inside = (series[-1].high + series[0].low) / 2
    assert_level_inside_market(inside, series)
    assert_level_inside_market(None, series)
    with pytest.raises(OpinionRejected) as caught:
        assert_level_inside_market(series[-1].high * 1.5, series)
    assert caught.value.code == "INVENTED_LEVEL"
    with pytest.raises(OpinionRejected) as caught:
        assert_level_inside_market(series[0].low * 0.5, series)
    assert caught.value.code == "INVENTED_LEVEL"


def test_AIV_11_a_zero_cost_model_is_unavailable_unless_declared():
    zero = BrokerCost(commission_bps=0.0, half_spread_bps=0.0, slippage_bps=0.0)
    real = BrokerCost(commission_bps=4.2, half_spread_bps=1.1, slippage_bps=0.8)

    assert check_costs(real).measured is True
    assert check_costs(zero, declared_frictionless=True).reason == "FRICTIONLESS_DECLARED"
    with pytest.raises(OpinionRejected) as caught:
        check_costs(zero)
    assert caught.value.code == "COST_UNAVAILABLE"
    with pytest.raises(OpinionRejected) as caught:
        check_costs(None)
    assert caught.value.code == "COST_UNAVAILABLE"


def test_AIV_10_the_weekend_policy_is_read_not_assumed():
    assert_tradeable_window(WEEKDAY_MS, weekend_trading=False)
    assert_tradeable_window(SATURDAY_MS, weekend_trading=True)
    with pytest.raises(OpinionRejected) as caught:
        assert_tradeable_window(SATURDAY_MS, weekend_trading=False)
    assert caught.value.code == "WEEKEND_BLOCK"


# ---------------------------------------------------------------- lane (integration)


def test_a_stale_chart_stops_the_run_before_the_paid_call(tmp_path, monkeypatch):
    """The image must belong to the decision bar; otherwise no call and no order."""
    real = lane_module.render_chart_png

    def stale(bars_seen, **kwargs):
        return real(bars_seen[:-1], **kwargs)  # one bar behind the decision

    monkeypatch.setattr(lane_module, "render_chart_png", stale)
    _lane, summary = run(tmp_path, ReplayProvider([LONG] * 40))
    ledger = entries(tmp_path)

    assert summary["fills"] == 0
    assert summary["calls"] == 0, "a stale chart must not be sent to a paid provider"
    assert any(row["kind"] == "GUARD_REJECT" and row["code"] == "STALE_CHART" for row in ledger)
    assert not any(row["kind"] == "FILL" for row in ledger)


def test_AIV_06_an_answer_that_sets_leverage_trades_nothing(tmp_path):
    payload = (
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
        '"confidence":0.9,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
        '"rationale":"sure thing","leverage":100,"quantity":5}'
    )
    _, summary = run(tmp_path, ReplayProvider([payload] * 20))
    ledger = entries(tmp_path)

    decisions = [row for row in ledger if row["kind"] == "DECISION"]
    assert decisions and decisions[0]["parse_error"] == "SCHEMA_FORBIDDEN_FIELD"
    assert "leverage" in decisions[0]["parse_detail"]
    assert summary["fills"] == 0


def test_AIV_05_an_invented_invalidation_price_trades_nothing(tmp_path):
    payload = (
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
        '"confidence":0.9,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
        '"invalidation_price":99999.0,"invalidation":"below that","rationale":"level"}'
    )
    _, summary = run(tmp_path, ReplayProvider([payload] * 20))
    ledger = entries(tmp_path)

    assert any(row["kind"] == "GUARD_REJECT" and row["code"] == "INVENTED_LEVEL" for row in ledger)
    assert summary["fills"] == 0


def test_AIV_10_no_fill_lands_inside_the_weekend_window(tmp_path):
    """The series spans Sat→Tue, so the gate must block the first two days and trade after.

    Asserting "zero fills in the whole run" would have been wrong: the same run has to
    prove that the market reopens. What matters is that no fill happens on a weekend bar.
    """
    _, summary = run(tmp_path, ReplayProvider([LONG] * 40), series=bars(start=SATURDAY_MS))
    ledger = entries(tmp_path)

    assert policy().blocks.weekend_trading is False, "the policy must forbid weekend entries"
    assert summary["counters"].get("gate:WEEKEND_BLOCK", 0) >= 1
    fills = [row for row in ledger if row["kind"] == "FILL"]
    assert fills, "the run must still trade once the week opens"
    for fill in fills:
        assert not is_weekend(fill["ts_ms"]), (
            f"a fill landed on a weekend bar: {fill['ts_ms']}"
        )
    blocked = [
        row for row in ledger if row.get("risk_blocked_by") == "WEEKEND_BLOCK"
    ]
    assert blocked and all(is_weekend(row["ts_ms"]) for row in blocked)
    assert any(row["kind"] == "DECISION" for row in ledger), "the model was still asked"


def test_the_kill_switch_blocks_entries_through_the_canonical_risk_manager(tmp_path):
    _, summary = run(
        tmp_path, ReplayProvider([LONG] * 40), risk_policy=policy(kill_switch_enabled=False)
    )
    ledger = entries(tmp_path)

    assert summary["fills"] == 0
    blocked = [
        row
        for row in ledger
        if row["kind"] == "DECISION_OUTCOME" and row.get("risk_blocked_by") == "kill_switch"
    ]
    assert blocked, "check_signal must be the gate that refuses, not a lane convention"


def test_a_hole_in_the_data_never_becomes_a_price_before_the_answer(tmp_path):
    """Un hueco no puede producir un relleno con un precio anterior a la respuesta.

    Este test afirmaba `STALE_EXECUTION`: el carril exigía que la cotización fuese
exactamente la vela siguiente, y con un hueco descartaba la opinión. Esa regla no era la
    que protegía el PIT — descartar por índice no distingue un hueco de una latencia real,
    y con latencia real descartaba *todo*. La condición que ahora se comprueba es la que
    de verdad impide operar a un precio no descrito: lo pagado es una cotización que
    existía en o después de la respuesta, y su espera queda declarada en la fila.
    """
    series = [bar for index, bar in enumerate(bars()) if index != 31]
    _, summary = run(tmp_path, ReplayProvider([LONG] * 40), series=series)
    ledger = entries(tmp_path)

    assert summary["fills"] >= 1, "a one-bar hole is inside the opinion's window"
    for fill in (row for row in ledger if row["kind"] == "FILL"):
        assert fill["quote_ts_ms"] >= fill["received_at_ms"]
        assert fill["quote_ts_ms"] >= fill["decision_ts_ms"]
        assert fill["quote_lag_ms"] == fill["quote_ts_ms"] - fill["received_at_ms"]
        assert fill["fill_bar_index"] > fill["decision_bar_index"], (
            "the fill can never be stamped on the bar whose close it read"
        )


def test_a_frictionless_run_must_declare_itself(tmp_path):
    """cost_multiplier=0 is the only way to price at zero, and it says so."""
    _, summary = run(tmp_path, ReplayProvider([LONG] * 40), cost_multiplier=0.0)

    assert summary["fills"] >= 1
    assert summary["counters"].get("gate:COST_UNAVAILABLE", 0) == 0


def test_the_window_fingerprint_in_the_ledger_matches_the_bars_drawn(tmp_path):
    series = bars()
    run(tmp_path, ReplayProvider([LONG] * 40), series=series)
    from trading_bot.vision.chart import window_fingerprint

    for row in entries(tmp_path):
        if row["kind"] != "DECISION":
            continue
        # The decision instant is the bar's close, so the row names the bar it was
        # formed on explicitly instead of leaving it to be inferred from the clock.
        assert "decision_bar_ts_ms" in row
        index = next(i for i, bar in enumerate(series) if bar.ts_ms == row["decision_bar_ts_ms"])
        expected = window_fingerprint(series[: index + 1], window_bars=30)
        assert row["window_fingerprint"] == expected
        rebuilt = render_chart_png(series[: index + 1], symbol="BTC/USDT", window_bars=30)
        assert row["chart"]["sha256"] == rebuilt.sha256
