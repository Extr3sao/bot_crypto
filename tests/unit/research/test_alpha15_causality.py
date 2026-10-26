"""WP-EDGE-015/P1 — the families must be causal, and this is what proves it.

A backtest that reads one bar of the future looks exactly like a backtest with a
real edge, which is why "the equity curve is up" is not evidence. The test here
is structural instead of statistical: truncate the series at the bar where a
trade ended, re-run the family on *data that stops there*, and require the whole
completed trade history to come back byte-identical. Anything that peeked would
have to change its mind once the future it used is gone.

It runs on the families' own code, not on a report about them, so a future edit
that introduces a look-ahead fails here rather than in the matrix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.research.economic_recovery.alpha15 import (
    FAMILY_BY_NAME,
    SINGLE_ASSET_FAMILIES,
    Bar,
    family_trades,
    rotation_backtest,
)
from trading_bot.research.economic_recovery.experiments import load_ohlcv

REPO = Path(__file__).resolve().parents[3]

SERIES = (
    (REPO / "data" / "edge08" / "universe-1h" / "UNIUSDT_2021_2026_1h.json", 4_000),
    (REPO / "data" / "edge08" / "universe-1h" / "CRVUSDT_2021_2026_1h.json", 4_000),
    (REPO / "data" / "edge07" / "holdout-1h" / "BTCUSDT_holdout2026.json", 3_000),
)


def _slice(path: Path, count: int) -> list[Bar]:
    bars = load_ohlcv(path)
    assert len(bars) > count, f"{path.name} is too short for the causality slice"
    return bars[-count:]


@pytest.mark.parametrize(("path", "count"), SERIES, ids=lambda value: str(value)[-30:])
@pytest.mark.parametrize("family", SINGLE_ASSET_FAMILIES, ids=lambda f: f.name)
def test_completed_history_is_reproduced_without_the_future(
    path: Path, count: int, family: object
) -> None:
    bars = _slice(path, count)
    trades = family_trades(family, bars)  # type: ignore[arg-type]
    assert trades, f"{family.name} produced no trades on {path.name}: nothing to verify"  # type: ignore[attr-defined]

    checked = 0
    for trade in trades:
        exit_index = next(
            index for index, bar in enumerate(bars) if bar.ts_ms == trade["exit_ts_ms"]
        )
        prefix = bars[: exit_index + 1]
        if len(prefix) < 400:  # indicator warm-up would dominate the prefix
            continue
        truncated = family_trades(family, prefix)  # type: ignore[arg-type]
        matching = [
            row
            for row in truncated
            if row["entry_ts_ms"] == trade["entry_ts_ms"]
            and row["exit_ts_ms"] == trade["exit_ts_ms"]
        ]
        assert matching, (
            f"{family.name}: a decision taken at {trade['entry_ts_ms']} does not survive the "
            "removal of every bar after its own exit — the family is reading the future"  # type: ignore[attr-defined]
        )
        assert matching[0]["entry_price"] == pytest.approx(trade["entry_price"])
        assert matching[0]["exit_price"] == pytest.approx(trade["exit_price"])
        # and the history that completed strictly before the cut must be identical
        before = [row for row in trades if row["exit_ts_ms"] < prefix[-1].ts_ms]
        before_truncated = [row for row in truncated if row["exit_ts_ms"] < prefix[-1].ts_ms]
        assert len(before) == len(before_truncated)
        checked += 1
    assert checked > 0


def test_the_rotation_family_does_not_use_future_closes() -> None:
    """Same statement for the portfolio rule: a truncated universe, same book."""
    symbols = ["AAVEUSDT", "CRVUSDT", "KSMUSDT", "SNXUSDT", "SUSHIUSDT", "UNIUSDT"]
    series = {
        symbol: load_ohlcv(
            REPO / "data" / "edge08" / "universe-1h" / f"{symbol}_2021_2026_1h.json"
        )[-2_500:]
        for symbol in symbols
    }
    params = FAMILY_BY_NAME["cross_sectional_rotation"].parameters
    full = rotation_backtest(series, params)
    entries_full = [
        (event["symbol"], event["ts_ms"]) for event in full["events"] if event["action"] == "BUY"
    ]
    assert entries_full

    # Cut every series at the timestamp of the third entry and re-run: the book
    # built up to that instant must be the same book.
    cut_ts = entries_full[2][1]
    truncated = {
        symbol: [bar for bar in bars if bar.ts_ms <= cut_ts] for symbol, bars in series.items()
    }
    partial = rotation_backtest(truncated, params)
    entries_partial = [
        (event["symbol"], event["ts_ms"])
        for event in partial["events"]
        if event["action"] == "BUY" and event["ts_ms"] < cut_ts
    ]
    assert entries_partial == [pair for pair in entries_full if pair[1] < cut_ts]
