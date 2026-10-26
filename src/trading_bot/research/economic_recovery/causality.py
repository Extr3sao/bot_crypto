"""Adversarial point-in-time scenarios for the WP-EDGE-016 families.

Each scenario takes a tape or a trade row, injects one specific way the ordering
could be violated, and reports whether the guard that exists for it noticed. They
are defined **once**, here, so the pytest module and the published
``CAUSALITY_ADVERSARIAL.json`` cannot drift apart: the test asserts every scenario
is caught, and the artifact records exactly what the test asserted.

A scenario that is *not* caught is a finding, not a flake — ``caught`` is False and
the row keeps the observed behaviour next to the expectation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .alpha15 import FAMILY_BY_NAME, SINGLE_ASSET_FAMILIES
from .experiments import Bar
from .pit15 import OutOfOrderBar, audit_trade, machine_for, run_family

#: Fields a proposal may never contain: each one would have to come from the future.
FUTURE_FIELDS = ("exit_price", "exit_ts_ms", "gross_bps", "net_pnl", "realised_pnl", "outcome")


def _scenario(name: str, injected: str, expectation: str, observed: str, caught: bool) -> dict[str, Any]:
    return {
        "scenario": name,
        "injected": injected,
        "expectation": expectation,
        "observed": observed,
        "caught": bool(caught),
    }


def _synthetic_trade(bars: Sequence[Bar], *, signal_index: int, fill_index: int) -> dict[str, Any]:
    """A trade row of the shape ``run_family`` emits, for the mutants to start from."""
    return {
        "entry_ts_ms": bars[fill_index].ts_ms,
        "exit_ts_ms": bars[fill_index].ts_ms,
        "entry_signal_ts_ms": bars[signal_index].ts_ms,
        "exit_signal_ts_ms": bars[signal_index].ts_ms,
        "entry_data_available_ms": bars[signal_index].ts_ms + 3_600_000,
        "exit_data_available_ms": bars[signal_index].ts_ms + 3_600_000,
        "entry_earliest_fill_ms": bars[fill_index].ts_ms,
        "exit_earliest_fill_ms": bars[fill_index].ts_ms,
        "entry_price": bars[fill_index].open,
        "exit_price": bars[fill_index].open,
        "gross_bps": 0.0,
        "bars_held": 0,
        "direction": "long",
        "entry_rule": "SYNTHETIC",
        "exit_rule": "SYNTHETIC",
        "is_mark": False,
        "entry_signal_index": signal_index,
        "exit_signal_index": signal_index,
        "entry_fill_index": fill_index,
        "exit_fill_index": fill_index,
    }


def same_bar_close_to_open_exit(bars: Sequence[Bar], family: str = "vol_regime_breakout") -> dict[str, Any]:
    """The defect WP-EDGE-016 was opened for: exit decided on a close, filled at that bar's open."""
    trade = _synthetic_trade(bars, signal_index=500, fill_index=501)
    trade["exit_signal_index"] = 500
    trade["exit_fill_index"] = 500  # the price that preceded the information
    trade["exit_ts_ms"] = bars[500].ts_ms
    trade["exit_earliest_fill_ms"] = bars[500].ts_ms
    trade["exit_data_available_ms"] = bars[500].ts_ms + 3_600_000
    violations = audit_trade(trade)
    return _scenario(
        "SAME_BAR_CLOSE_TO_OPEN_EXIT",
        f"an exit read off bar 500's close and filled at bar 500's open ({family})",
        "audit_trade reports the same-bar close-to-open exploit",
        "; ".join(violations) or "no violation reported",
        any("same-bar" in item for item in violations),
    )


def future_outcome_in_a_proposal(bars: Sequence[Bar]) -> dict[str, Any]:
    """A decision message must not carry the outcome it is deciding about."""
    machine = machine_for("vol_regime_breakout", dict(FAMILY_BY_NAME["vol_regime_breakout"].parameters))
    payload: dict[str, Any] = {}
    for index, bar in enumerate(bars[:1200]):
        decision = machine.on_closed_bar(index, bar, in_position=False)
        if decision is not None:
            payload = dict(decision.detail)
            payload.update({"rule": decision.rule})
            break
    leaked = [field for field in FUTURE_FIELDS if field in payload]
    honest = not leaked
    poisoned = dict(payload, exit_price=bars[1199].close)
    still_leaked = [field for field in FUTURE_FIELDS if field in poisoned]
    return _scenario(
        "FUTURE_OUTCOME_IN_A_PROPOSAL",
        "an exit price attached to a real entry proposal",
        "a real proposal carries nothing from the future, and the detector notices when one does",
        f"real proposal fields {sorted(payload)}; injected payload flags {still_leaked}",
        honest and bool(still_leaked),
    )


def terminal_bar_is_a_mark(bars: Sequence[Bar]) -> dict[str, Any]:
    """A position still open at the last closed bar is marked, never filled.

    The window is not guaranteed to end mid-position, so the tape is cut at the last
    bar that leaves one open — otherwise the scenario would prove nothing.
    """
    marks: list[dict[str, Any]] = []
    violations: list[str] = []
    cut = len(bars)
    found: tuple[int, list[dict[str, Any]]] | None = None
    for candidate in range(len(bars) - 1, max(len(bars) - 240, 1), -1):
        for family in SINGLE_ASSET_FAMILIES:
            trades = run_family(family.name, bars[:candidate], family.parameters)
            open_at_end = [trade for trade in trades if trade["is_mark"]]
            if open_at_end:
                found = (candidate, open_at_end)
                break
        if found is not None:
            break
    if found is not None:
        cut, marks = found
        for trade in marks:
            violations.extend(audit_trade(trade))
            if int(trade["exit_fill_index"]) != cut - 1:
                violations.append("a mark that is not at the last bar")
            if trade["exit_rule"] != "TERMINAL_MARK_AT_LAST_CLOSE":
                violations.append("a mark under another rule's name")
    return _scenario(
        "TERMINAL_BAR_IS_A_MARK",
        f"the tape cut at bar {cut} of {len(bars)}, while a position was still open",
        "the open position is marked at the last close, flagged is_mark, and audits clean",
        f"{len(marks)} mark(s) at cut {cut}, {len(violations)} violation(s)",
        found is not None and not violations,
    )


def gap_in_the_series(bars: Sequence[Bar]) -> dict[str, Any]:
    """An hour nobody recorded must not become an invented bar or a fill inside the hole."""
    holdout = list(bars)
    missing = [index for index in range(600, 604)]
    holed = [bar for index, bar in enumerate(holdout) if index not in missing]
    present = {bar.ts_ms for bar in holed}
    removed = {holdout[index].ts_ms for index in missing}
    problems: list[str] = []
    checked = 0
    for family in SINGLE_ASSET_FAMILIES:
        for trade in run_family(family.name, holed, family.parameters):
            checked += 1
            if int(trade["entry_ts_ms"]) in removed or int(trade["exit_ts_ms"]) in removed:
                problems.append(f"{family.name}: a fill inside the gap")
            if int(trade["entry_ts_ms"]) not in present or int(trade["exit_ts_ms"]) not in present:
                problems.append(f"{family.name}: a fill that is not a bar on the tape")
            if int(trade["entry_ts_ms"]) <= int(trade["entry_signal_ts_ms"]):
                problems.append(f"{family.name}: an entry at or before its own signal bar")
    return _scenario(
        "GAP_IN_THE_SERIES",
        f"{len(missing)} consecutive hours removed from the tape",
        "the next present bar is used, nothing is invented, and no fill lands in the hole",
        f"{checked} trades on the holed tape, {len(problems)} problem(s)",
        checked > 0 and not problems,
    )


def delayed_bar_receipt(bars: Sequence[Bar]) -> dict[str, Any]:
    """A bar whose data arrives late pushes the fill to the next bar that opens after it."""
    late_ms = bars[800].ts_ms + 3_600_000 + 900_000  # the close, then 15 minutes of receipt lag
    trade = _synthetic_trade(bars, signal_index=800, fill_index=802)
    trade["exit_rule"] = "STOP_LOSS_ON_CLOSE"
    trade["exit_signal_index"] = 800
    trade["exit_fill_index"] = 802
    trade["exit_ts_ms"] = bars[802].ts_ms
    trade["exit_earliest_fill_ms"] = bars[802].ts_ms
    trade["exit_data_available_ms"] = late_ms
    clean = audit_trade(trade) == []

    # the same decision filled at the next bar's open would precede the late data
    early = dict(
        trade,
        exit_fill_index=801,
        exit_ts_ms=bars[801].ts_ms,
        exit_earliest_fill_ms=bars[801].ts_ms,
    )
    caught = [item for item in audit_trade(early) if "precedes" in item]
    return _scenario(
        "DELAYED_BAR_RECEIPT",
        "a bar whose data is only available 15 minutes after its close",
        "the decision waits for the late data, and the too-early fill is refused",
        f"fill at the next bar after the late data clears ({clean}); "
        f"fill at the immediate next open: {caught[:1] or 'not refused'}",
        clean and bool(caught),
    )


def bars_arriving_out_of_order(bars: Sequence[Bar]) -> dict[str, Any]:
    """A shuffled tape must be refused, not quietly decided on."""
    machine = machine_for("trend_pullback", dict(FAMILY_BY_NAME["trend_pullback"].parameters))
    forward = 0
    refused = False
    for index, bar in enumerate(bars[:600]):
        machine.on_closed_bar(index, bar, in_position=False)
        forward += 1
    try:
        machine.on_closed_bar(300, bars[300], in_position=False)
    except OutOfOrderBar:
        refused = True
    return _scenario(
        "BARS_OUT_OF_ORDER",
        f"bar 300 re-delivered after {forward} bars had already been decided on",
        "the machine refuses a bar older than one it has already seen",
        "OutOfOrderBar raised" if refused else "the machine accepted the older bar",
        refused,
    )


def same_instant_reentry(bars: Sequence[Bar]) -> dict[str, Any]:
    """An entry filling at the instant of the previous exit would double the exposure."""
    overlaps: list[str] = []
    checked = 0
    for family in SINGLE_ASSET_FAMILIES:
        previous_exit: int | None = None
        for trade in run_family(family.name, bars, family.parameters):
            checked += 1
            entry, exit_index = int(trade["entry_fill_index"]), int(trade["exit_fill_index"])
            if previous_exit is not None and entry <= previous_exit:
                overlaps.append(f"{family.name}: entry at {entry} on exit {previous_exit}")
            previous_exit = exit_index
    return _scenario(
        "SAME_INSTANT_REENTRY",
        "a rule that would re-enter on the very bar its previous exit filled",
        "the re-entry is dropped, so one lane never holds two positions at once",
        f"{checked} trades checked, {len(overlaps)} overlap(s)",
        checked > 0 and not overlaps,
    )


def adversarial_rows(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    """Every scenario, in the order the report lists them."""
    return [
        same_bar_close_to_open_exit(bars),
        future_outcome_in_a_proposal(bars),
        terminal_bar_is_a_mark(bars),
        gap_in_the_series(bars),
        delayed_bar_receipt(bars),
        bars_arriving_out_of_order(bars),
        same_instant_reentry(bars),
    ]
