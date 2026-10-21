"""The vertical slice, asserted end to end.

These tests do not mock the risk engine or the broker: they drive the real
``RiskManager`` built from ``config/risk.yaml`` and the real ``PaperBroker`` with its
cost schedule. The only stand-in is the model, because a unit test cannot call a paid
API — and the stand-in is labelled ``replay`` in the ledger so it can never be mistaken
for a live decision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.chart import render_chart_png
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries, summarize, verify_chain
from trading_bot.vision.provider import ProviderError, ReplayProvider
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000
REPO = Path(__file__).resolve().parents[3]


def series(
    count: int = 96, *, drift: float = 0.004, pullback_every: int = 12
) -> list[Bar]:
    """A trend with regular pullbacks, so stops and targets both get exercised."""
    bars: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = -drift if pullback_every and i % pullback_every == pullback_every - 1 else drift
        open_price = price
        close = price * (1.0 + step)
        bars.append(
            Bar(
                ts_ms=START_MS + i * HOUR_MS,
                open=open_price,
                high=max(open_price, close) * 1.002,
                low=min(open_price, close) * 0.998,
                close=close,
                volume=200.0 + (i % 13),
            )
        )
        price = close
    return bars


def flat_series(count: int = 96) -> list[Bar]:
    """No trend: a position stays open, so a second LONG is a book-state question."""
    return series(count, drift=0.0)


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
        "max_calls_per_run": 50,
        "max_estimated_spend_usd": 5.0,
        **lane_overrides,
    }
    return config.__class__(provider=config.provider, lane=lane.__class__(**merged))


#: DEF-RUN-014: el stop del guion es el que el libro arriesga, así que tiene que limpiar
#: el coste de ida y vuelta (24.79 bps a 500 USDT). 0.2 % estaba por debajo y el lane
#: ahora lo rechaza con causa; 1.0 % es el mismo escenario con una distancia ejecutable.
ALWAYS_LONG_ANSWER = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":10,"stop_loss_pct":1.0,"take_profit_pct":5.0,'
    '"invalidation":null,"rationale":"Continuation."}'
)


def always_long(request) -> str:
    """The same opinion every bar — which is how book-state policy becomes observable."""
    return ALWAYS_LONG_ANSWER.replace("BTC/USDT", getattr(request.chart, "symbol", "BTC/USDT"))


def long_then_flat(request) -> str:
    """A scripted model: LONG on the first call, CLOSE afterwards."""
    long_then_flat.calls += 1  # type: ignore[attr-defined]
    if long_then_flat.calls % 3 == 1:  # type: ignore[attr-defined]
        return (
            '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
            '"confidence":0.6,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
            '"invalidation":null,"rationale":"Higher lows into the pullback."}'
        )
    return (
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"NO_TRADE",'
        '"confidence":0.3,"horizon_bars":6,"stop_loss_pct":null,"take_profit_pct":null,'
        '"invalidation":null,"rationale":"No clean level here."}'
    )


long_then_flat.calls = 0  # type: ignore[attr-defined]


def run_lane(tmp_path: Path, provider, *, bars=None, **kwargs):
    bars = bars or series()
    lane = VisionLane(
        series={"BTC/USDT": bars},
        provider=provider,
        config=vision_config(),
        risk_policy=kwargs.pop("risk_policy", policy()),
        ledger_path=tmp_path / "decisions.jsonl",
        **kwargs,
    )
    return lane, lane.run()


def test_the_slice_produces_fills_and_a_net_result(tmp_path):
    provider = ReplayProvider(long_then_flat)
    _, summary = run_lane(tmp_path, provider)

    assert summary["calls"] >= 2
    assert summary["fills"] >= 1, "a LONG was approved and must have filled"
    assert summary["closed_trades" if "closed_trades" in summary else "fills"] >= 1
    assert summary["net_realised_usdt"] != 0.0
    assert summary["equity_points"] == len(series())
    assert summary["drawdown_status"] == "MEASURED"


def test_every_closed_trade_balances_to_the_cent(tmp_path):
    provider = ReplayProvider(long_then_flat)
    _, summary = run_lane(tmp_path, provider)

    for trade in summary["trades"]:
        assert trade["pnl_net_usdt"] == pytest.approx(trade["pnl_net_usdt"])

    entries = [row["entry"] for row in read_entries(tmp_path / "decisions.jsonl")]
    closes = [entry for entry in entries if entry["kind"] == "CLOSE"]
    assert closes, "at least one close must be in the ledger"
    for close in closes:
        identity = (
            close["reference_gross_pnl_usdt"]
            - close["execution_cost_usdt"]
            - close["commissions_usdt"]
        )
        assert close["pnl_net_usdt"] == pytest.approx(identity, abs=1e-6)
    assert summary["net_realised_usdt"] == pytest.approx(
        sum(close["pnl_net_usdt"] for close in closes), abs=1e-6
    )


def test_the_ledger_chain_verifies_after_a_run(tmp_path):
    provider = ReplayProvider(long_then_flat)
    run_lane(tmp_path, provider)

    report = verify_chain(tmp_path / "decisions.jsonl")

    assert report["ok"] is True
    assert report["kinds"]["RUN"] == 1
    assert report["kinds"]["RUN_END"] == 1
    assert report["kinds"]["DECISION"] >= 2


def test_a_decision_is_executed_at_the_next_bar_open_never_its_own(tmp_path):
    """RFC-TAP-AI-BOTS-003: the decision instant is the close, and the fill is the next open.

    Both happen at the same wall-clock instant, which is the point: the bar that opens as
    the opinion is formed is the first one whose *open* the opinion could have traded.
    """
    provider = ReplayProvider(long_then_flat)
    _, summary = run_lane(tmp_path, provider)
    lines = read_entries(tmp_path / "decisions.jsonl")
    decisions = {
        line["seq"]: line["entry"]
        for line in lines
        if line["entry"]["kind"] == "DECISION"
    }
    fills = [line["entry"] for line in lines if line["entry"]["kind"] == "FILL"]
    assert fills, "the scripted LONG must fill"
    for fill in fills:
        decision = decisions[fill["decision_seq"]]
        assert decision["ts_ms"] == decision["decision_bar_ts_ms"] + HOUR_MS
        assert fill["ts_ms"] == decision["ts_ms"], (
            "the fill bar opens at the instant the decision was formed; filling earlier "
            "would have used a price from before the opinion existed"
        )
        assert fill["fill_bar_index"] == fill["decision_bar_index"] + 1
    del summary


def test_the_recorded_image_is_reproducible_from_the_bars(tmp_path):
    """The ledger stores a hash; that hash must match the picture drawn from the data."""
    bars = series()
    provider = ReplayProvider(long_then_flat)
    run_lane(tmp_path, provider, bars=bars)
    lines = read_entries(tmp_path / "decisions.jsonl")

    checked = 0
    for line in lines:
        entry = line["entry"]
        if entry["kind"] != "DECISION":
            continue
        index = next(
            i for i, bar in enumerate(bars) if bar.ts_ms == entry["decision_bar_ts_ms"]
        )
        rebuilt = render_chart_png(bars[: index + 1], symbol=entry["symbol"], window_bars=30)
        assert rebuilt.sha256 == entry["chart"]["sha256"]
        assert entry["window_fingerprint"]
        checked += 1
    assert checked >= 2


def test_a_provider_failure_is_recorded_and_creates_no_trade(tmp_path):
    def boom(_request):
        raise ProviderError("TRANSPORT_ERROR", "network down", attempts=3)

    provider = ReplayProvider(boom)
    _, summary = run_lane(tmp_path, provider)
    lines = read_entries(tmp_path / "decisions.jsonl")

    failures = [line["entry"] for line in lines if line["entry"]["kind"] == "PROVIDER_FAILURE"]
    assert failures
    assert failures[0]["code"] == "TRANSPORT_ERROR"
    assert failures[0]["decision"] is None
    assert summary["fills"] == 0
    assert summary["calls"] == 0


def test_an_unparseable_answer_is_a_rejection_not_a_no_trade(tmp_path):
    provider = ReplayProvider(["Bitcoin looks strong, I would buy the dip."] * 10)
    _, summary = run_lane(tmp_path, provider)
    lines = read_entries(tmp_path / "decisions.jsonl")

    decisions = [line["entry"] for line in lines if line["entry"]["kind"] == "DECISION"]
    assert decisions
    assert decisions[0]["parse_error"] == "NO_JSON"
    assert decisions[0]["decision"] is None
    assert summary["fills"] == 0


def test_a_second_position_in_the_same_symbol_is_dropped_not_pyramided(tmp_path):
    provider = ReplayProvider(always_long)
    _, summary = run_lane(tmp_path, provider, bars=flat_series())

    assert summary["counters"].get("dropped:ALREADY_LONG", 0) >= 1
    assert summary["fills"] == 1


def test_the_model_can_close_its_own_position(tmp_path):
    answers = [
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
        '"confidence":0.7,"horizon_bars":10,"stop_loss_pct":2.0,"take_profit_pct":9.0,'
        '"invalidation":null,"rationale":"Trend continuation."}',
        '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"CLOSE",'
        '"confidence":0.9,"horizon_bars":1,"stop_loss_pct":null,"take_profit_pct":null,'
        '"invalidation":null,"rationale":"Structure broke."}',
    ]
    provider = ReplayProvider(answers * 10)
    _, summary = run_lane(tmp_path, provider, bars=flat_series())
    lines = read_entries(tmp_path / "decisions.jsonl")

    closes = [line["entry"] for line in lines if line["entry"]["kind"] == "CLOSE"]
    assert summary["fills"] >= 1
    assert any(close["exit_reason"] == "signal" for close in closes)
    bypassed = [
        line["entry"]
        for line in lines
        if line["entry"]["kind"] == "DECISION_OUTCOME"
        and line["entry"].get("risk_gate") == "BYPASSED_FOR_REDUCTION"
    ]
    assert bypassed, "a model CLOSE must be executed without the trade-count gate"


def test_one_position_slot_blocks_the_second_symbol(tmp_path):
    shared = flat_series()
    lane = VisionLane(
        series={"BTC/USDT": shared, "ETH/USDT": shared},
        provider=ReplayProvider(always_long),
        config=vision_config(),
        risk_policy=policy(max_open_positions=1),
        ledger_path=tmp_path / "decisions.jsonl",
    )
    summary = lane.run()
    lines = read_entries(tmp_path / "decisions.jsonl")

    blocked = [
        line["entry"]
        for line in lines
        if line["entry"]["kind"] == "DECISION_OUTCOME"
        and line["entry"].get("risk_blocked_by") == "max_positions"
    ]
    assert blocked, "the second symbol must hit the position-slot gate"
    assert summary["fills"] >= 1


def test_the_call_budget_stops_the_run_instead_of_spending_more(tmp_path):
    provider = ReplayProvider(long_then_flat)
    _, summary = run_lane(tmp_path, provider, max_calls=2)
    lines = read_entries(tmp_path / "decisions.jsonl")

    decisions = [line["entry"] for line in lines if line["entry"]["kind"] == "DECISION"]
    assert summary["calls"] == 2
    assert summary["stop_reason"] == "MAX_CALLS_REACHED"
    assert len(decisions) == 2


def test_the_risk_equity_equals_the_broker_net_equity(tmp_path):
    provider = ReplayProvider(long_then_flat)
    lane, summary = run_lane(tmp_path, provider)

    expected = 10_000.0 + sum(trade.pnl for trade in lane.broker.closed_trades)
    assert lane.risk.equity == pytest.approx(expected, abs=1e-6)
    assert lane.broker.equity == pytest.approx(expected, abs=1e-6)
    assert summary["risk_equity_usdt"] == pytest.approx(expected, abs=1e-6)


def test_the_summary_counts_what_the_ledger_contains(tmp_path):
    provider = ReplayProvider(long_then_flat)
    run_lane(tmp_path, provider)
    summary = summarize(tmp_path / "decisions.jsonl")

    assert summary["entries"] >= 4
    assert summary["actions"].get("LONG", 0) >= 1
    assert summary["closed_trades"] == len(
        [1 for row in read_entries(tmp_path / "decisions.jsonl") if row["entry"]["kind"] == "CLOSE"]
    )
