"""WP-EDGE-016 — the adversarial scenarios, one test per way to break causality.

``trading_bot.research.economic_recovery.causality`` defines each scenario once and
this module requires every one of them to be *caught* on every holdout symbol. The
published ``CAUSALITY_ADVERSARIAL.json`` is produced by ``scripts/edge16_adversarial.py``
from the same rows, so a scenario that stops being caught fails here and shows up
there rather than quietly changing meaning in one place.

Each scenario carries an injection and an expectation. A test that merely checks the
new code runs would pass on the old code too; these are written so that the WP-EDGE-015
behaviour fails them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_bot.research.economic_recovery import alpha15 as A
from trading_bot.research.economic_recovery.causality import adversarial_rows
from trading_bot.research.economic_recovery.experiments import Bar, load_ohlcv
from trading_bot.research.economic_recovery.pit15 import audit_trade

REPO = Path(__file__).resolve().parents[3]
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SERIES: dict[str, list[Bar]] = {
    symbol: load_ohlcv(REPO / "data" / "edge07" / "holdout-1h" / f"{symbol}_holdout2026.json")[
        -2000:
    ]
    for symbol in UNIVERSE
}

SCENARIOS = (
    "SAME_BAR_CLOSE_TO_OPEN_EXIT",
    "FUTURE_OUTCOME_IN_A_PROPOSAL",
    "TERMINAL_BAR_IS_A_MARK",
    "GAP_IN_THE_SERIES",
    "DELAYED_BAR_RECEIPT",
    "BARS_OUT_OF_ORDER",
    "SAME_INSTANT_REENTRY",
)


@pytest.mark.parametrize("symbol", UNIVERSE)
def test_every_adversarial_scenario_is_caught(symbol: str) -> None:
    rows = adversarial_rows(SERIES[symbol])
    assert {row["scenario"] for row in rows} == set(SCENARIOS)
    uncaught = [row for row in rows if not row["caught"]]
    assert not uncaught, f"{symbol}: {[(row['scenario'], row['observed']) for row in uncaught]}"


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("symbol", UNIVERSE)
def test_scenario_by_name(scenario: str, symbol: str) -> None:
    row = next(row for row in adversarial_rows(SERIES[symbol]) if row["scenario"] == scenario)
    assert row["caught"], f"{scenario}/{symbol}: {row['observed']}"


def test_the_causality_module_has_no_scenario_the_runner_forgot() -> None:
    """A new scenario with no test here would be published as caught without being asserted."""
    names = {row["scenario"] for row in adversarial_rows(SERIES["BTCUSDT"])}
    assert names == set(SCENARIOS), f"untested scenarios: {sorted(names - set(SCENARIOS))}"


def test_the_pre_pit_runners_are_the_ones_these_scenarios_condemn() -> None:
    """The injected fault is not hypothetical: it is what the 015 runners did, on real bars."""
    bars = SERIES["BTCUSDT"]
    index_of = {bar.ts_ms: index for index, bar in enumerate(bars)}
    caught = 0
    checked = 0
    for family in A.SINGLE_ASSET_FAMILIES:
        for trade in A.PRE_PIT_RUNNERS[family.name](bars, family.parameters):
            checked += 1
            exit_index = index_of[trade["exit_ts_ms"]]
            fabricated = {
                "entry_ts_ms": trade["entry_ts_ms"],
                "exit_ts_ms": trade["exit_ts_ms"],
                "entry_data_available_ms": trade["entry_ts_ms"],
                "exit_data_available_ms": trade["exit_ts_ms"],
                "entry_earliest_fill_ms": trade["entry_ts_ms"],
                "exit_earliest_fill_ms": trade["exit_ts_ms"],
                "entry_fill_index": index_of[trade["entry_ts_ms"]],
                "exit_fill_index": exit_index,
                "entry_signal_index": index_of[trade["entry_ts_ms"]] - 1,
                "exit_signal_index": exit_index,
                "is_mark": False,
                "exit_rule": "PRE_PIT_SAME_BAR",
            }
            if any("same-bar" in item for item in audit_trade(fabricated)):
                caught += 1
    assert checked > 0, "no pre-repair trade was audited, so this proves nothing"
    assert caught == checked, f"only {caught}/{checked} pre-repair exits were condemned"
