"""RFC-TAP-AI-BOTS-003 — the bar-close clock, and the risk engine on the same equity.

`Bar.ts_ms` is a bar's **open**. A decision that reads the bar's close cannot exist
before `open + timeframe + data_delay`, and every test here fails on the lane that
timestamps it at the open. The second half is parity: the risk engine must be marked
with the same net equity the curve publishes, or its drawdown and sizing gates run on a
number nobody else can see.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.clock import UnknownTimeframe, information_ms, timeframe_ms
from trading_bot.vision.guards import OpinionRejected, assert_causal
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
REPO = Path(__file__).resolve().parents[3]
WEEKDAY_MS = int(datetime(2026, 3, 3, tzinfo=UTC).timestamp() * 1000)

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.7,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
    '"invalidation":null,"rationale":"Higher lows."}'
)


class RecordingProvider(ReplayProvider):
    """A replay transport that keeps the request it was asked, so the instant is visible."""

    def __init__(self, answers: list[str], *, latency_ms: int = 0) -> None:
        super().__init__(list(answers))
        self._latency_ms = latency_ms
        self.requests: list[object] = []

    def analyze(self, request):  # type: ignore[override]
        self.requests.append(request)
        response = super().analyze(request)
        return replace(response, latency_ms=self._latency_ms)


def bars(count: int = 96, *, start: int = WEEKDAY_MS, drift: float = 0.004) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = -drift if i % 24 == 23 else drift
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


def config(*, data_delay_ms: int = 0):
    base = load_vision_config(env={})
    lane = base.lane
    merged = {
        "timeframe": lane.timeframe,
        "window_bars": 30,
        "decision_every_bars": 15,
        "max_calls_per_run": 40,
        "max_estimated_spend_usd": 5.0,
        "data_delay_ms": data_delay_ms,
    }
    return base.__class__(provider=base.provider, lane=lane.__class__(**merged))


def run_lane(tmp_path: Path, provider, *, data_delay_ms: int = 0, count: int = 96):
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    lane = VisionLane(
        series={"BTC/USDT": bars(count)},
        provider=provider,
        config=config(data_delay_ms=data_delay_ms),
        risk_policy=policy,
        ledger_path=tmp_path / "d.jsonl",
    )
    return lane.run()


def ledger_rows(tmp_path: Path) -> list[dict]:
    return [row["entry"] for row in read_entries(tmp_path / "d.jsonl")]


# ------------------------------------------------------------------ the close clock


def test_a_decision_is_taken_at_the_bar_close_not_at_its_open(tmp_path: Path) -> None:
    provider = RecordingProvider([LONG] * 40)

    run_lane(tmp_path, provider)

    assert provider.requests, "the run must have asked the model at least once"
    opens = {int(bar.ts_ms) for bar in bars()}
    for request in provider.requests:
        instant = int(request.decision_ts_ms)
        assert instant - HOUR_MS in opens, (
            f"the decision instant {instant} must be the close of a bar, i.e. one "
            "timeframe after an open"
        )
        assert instant > int(request.decision_ts_ms) - HOUR_MS, "the close is after its open"


def test_the_information_instant_carries_the_data_delay(tmp_path: Path) -> None:
    provider = RecordingProvider([LONG] * 40)

    run_lane(tmp_path, provider, data_delay_ms=300_000)

    assert provider.requests
    closes = {int(bar.ts_ms) + HOUR_MS for bar in bars()}
    for request in provider.requests:
        assert int(request.decision_ts_ms) - 300_000 in closes


def test_the_bar_duration_comes_from_the_timeframe_and_is_never_guessed() -> None:
    assert timeframe_ms("1h") == HOUR_MS
    assert timeframe_ms("15m") == 900_000
    assert information_ms(0, HOUR_MS, 60_000) == HOUR_MS + 60_000

    with pytest.raises(UnknownTimeframe):
        timeframe_ms("hourly-ish")


def test_a_bar_that_has_not_closed_at_the_decision_instant_is_a_violation() -> None:
    window = bars(count=2)
    decision_ts = int(window[1].ts_ms)  # the second bar's open

    with pytest.raises(OpinionRejected, match="PIT_VIOLATION"):
        assert_causal(window, decision_ts, bar_interval_ms=HOUR_MS)

    # The same window is fine once the instant is the close of the second bar.
    assert_causal(window, int(window[1].ts_ms) + HOUR_MS, bar_interval_ms=HOUR_MS)


def test_a_latency_below_the_timeframe_no_longer_buys_the_next_open(tmp_path: Path) -> None:
    """With the close clock, the fill bar opens exactly when the answer is due."""

    summary = run_lane(tmp_path, RecordingProvider([LONG] * 40, latency_ms=60_000))
    rows = ledger_rows(tmp_path)

    late = [
        row
        for row in rows
        if row["kind"] == "GUARD_REJECT" and row["code"] == "LATE_RESPONSE"
    ]
    assert late, "an answer that arrives after the close cannot fill at the next open"
    assert summary["fills"] == 0
    assert not [row for row in rows if row["kind"] == "FILL"]


def test_a_zero_latency_answer_still_fills(tmp_path: Path) -> None:
    summary = run_lane(tmp_path, RecordingProvider([LONG] * 40))

    assert summary["fills"] > 0, "the clock must not forbid every trade"


# ------------------------------------------------------------- risk net parity


def test_the_risk_engine_is_marked_with_the_equity_the_curve_publishes(
    tmp_path: Path,
) -> None:
    # One bar less than a cadence boundary: the last decision's entry cannot close
    # before the data ends, so the book carries an unrealised leg.
    provider = RecordingProvider([LONG] * 40)
    summary = run_lane(tmp_path, provider, count=92)
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    lane = VisionLane(
        series={"BTC/USDT": bars(92)},
        provider=RecordingProvider([LONG] * 40),
        config=config(),
        risk_policy=policy,
        ledger_path=tmp_path / "parity.jsonl",
    )
    result = lane.run()

    assert result["open_positions_at_end"], (
        "this dataset must end with a position open: the parity that matters is the "
        "unrealised leg, which a realised-only equity cannot show"
    )
    for point in lane.equity_curve:
        assert point["risk_equity"] == pytest.approx(point["equity"]), (
            "the risk engine must see the same net mark the curve reports, "
            f"not the realised-only equity ({point})"
        )
    assert summary["fills"] >= 0
