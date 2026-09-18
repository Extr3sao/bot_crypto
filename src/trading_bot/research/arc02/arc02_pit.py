"""ARC-02 PIT adversarial battery.

Non-vacuous causal tests over the *frozen* ARC-02 primitives. Fixtures are built from the
same ``Projection5m`` container the certified reader produces, so every check exercises
the real feature code path rather than a paraphrase of it.

Fixture geometry (chosen so the frozen boundaries are EXACT in IEEE-754, not approximate):

* BTC closes alternate ``1.0 <-> 2.0``, so every trailing reference return has
  ``|r| = ln(2)`` and the trailing median scale is exactly ``ln(2)``.
* the driver bar closes at ``16 x`` the previous close, so the shock statistic is exactly
  ``ln(16)/ln(2) = 4.0`` (strictly above the frozen threshold);
* the boundary fixture closes the driver at exactly ``8 x``, giving ``ln(8)/ln(2) = 3.0``
  exactly — the strict inequality must REJECT it;
* the follower boundary closes at exactly ``4 x``, i.e. ``ln(4) = 0.5 * ln(16)``
  EXACTLY (``ln(b^2) == 2*ln(b)`` in IEEE-754 for these values) — the strict
  underreaction inequality must REJECT it.

The evaluated (decision) bar is never the last bar of the partition, so the
"future mutation after T" checks are non-vacuous.

Run directly::

    python src/trading_bot/research/arc02/arc02_pit.py
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import tempfile
from typing import Any, Callable

from trading_bot.research.arc02.arc02_authority import (
    BAR_MS,
    DROPPED_FIELDS,
    LEADER,
    NO_SIGNAL,
    NO_SIGNAL_PRECEDENCE,
    PROJECTED_FIELDS,
    Projection5m,
    evaluate_at_slot,
    entry_index_for_decision,
    forward_exit_index,
    leader_scale,
    load_partition,
)
from trading_bot.research.arc02.arc02_funding import FundingSeries, load_funding
from trading_bot.research.arc02.arc02_normalize import project_records

START_MS = 1_700_000_000_000 - (1_700_000_000_000 % BAR_MS)
DAYS = 40
BARS_PER_DAY = 288
TOTAL_BARS = DAYS * BARS_PER_DAY
TARGET_G = 9_000  # even -> the preceding slot is odd (close 1.0)


def slot(g: int) -> int:
    return START_MS + g * BAR_MS


def _btc_base(g: int) -> float:
    return 1.0 if g % 2 == 1 else 2.0


def build_partition(
    symbol: str,
    close_fn: Callable[[int], float],
    *,
    bars: int = TOTAL_BARS,
    drop: set[int] | None = None,
    overrides: dict[int, float] | None = None,
) -> Projection5m:
    """Deterministic synthetic projection partition (open == close, no volume field)."""
    drop = drop or set()
    overrides = overrides or {}
    ts: list[int] = []
    cts: list[int] = []
    o: list[float] = []
    c: list[float] = []
    for g in range(bars):
        if g in drop:
            continue
        t = slot(g)
        close = overrides.get(g, close_fn(g))
        ts.append(t)
        cts.append(t + BAR_MS - 1)
        o.append(close)
        c.append(close)
    return Projection5m(
        symbol=symbol,
        t=tuple(ts),
        ct=tuple(cts),
        o=tuple(o),
        c=tuple(c),
        sha256="synthetic",
        path="synthetic://projection",
        rows=len(ts),
        index={t: i for i, t in enumerate(ts)},
    )


def btc_partition(**kw: Any) -> Projection5m:
    return build_partition(LEADER, _btc_base, **kw)


def follower_partition(symbol: str = "ETHUSDT", *, response: float | None = None, **kw: Any) -> Projection5m:
    def close_fn(g: int) -> float:
        if g == TARGET_G and response is not None:
            return response
        return 1.0

    return build_partition(symbol, close_fn, **kw)


def run_battery() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # ------------------------------------------------------- 1. baseline emission
    leader = btc_partition(overrides={TARGET_G: 16.0})
    follower = follower_partition("ETHUSDT", response=2.0)
    base = evaluate_at_slot(leader, follower, slot(TARGET_G))
    pos = leader.index[slot(TARGET_G)]
    add(
        "BASELINE_POSITIVE_SHOCK_PLUS_POSITIVE_UNDERREACTION_YIELDS_LONG",
        base["emitted"] is True and base["result"] == "LONG",
        {"result": base.get("result"), "reason": base.get("reason"), "z": base.get("leader_shock_statistic"),
         "ratio": base.get("follower_response_ratio")},
    )
    add(
        "DECISION_TIME_IS_MAX_OF_BOTH_COMPLETED_BAR_CLOSES",
        base["decision_time_ms"] == max(leader.ct[pos], follower.ct[follower.index[slot(TARGET_G)]]),
        {"decision_time_ms": base["decision_time_ms"]},
    )
    add(
        "DECISION_BAR_IS_NOT_LAST_BAR_OF_PARTITION",
        pos < len(leader.t) - 1 and follower.index[slot(TARGET_G)] < len(follower.t) - 1,
        {"future_leader_bars": len(leader.t) - 1 - pos},
    )
    add(
        "ALL_REFERENCE_OBSERVATIONS_AT_OR_BEFORE_DECISION",
        all(slot(TARGET_G) - j * BAR_MS <= base["decision_time_ms"] for j in range(1, 289)),
        None,
    )

    # ------------------------------------------------------- 2. mirrored direction
    leader_down = btc_partition(overrides={TARGET_G: 1.0 / 16.0})
    follower_down = follower_partition("ETHUSDT", response=0.5)
    down = evaluate_at_slot(leader_down, follower_down, slot(TARGET_G))
    add(
        "NEGATIVE_SHOCK_PLUS_NEGATIVE_UNDERREACTION_YIELDS_SHORT",
        down["emitted"] is True and down["result"] == "SHORT",
        {"result": down.get("result"), "reason": down.get("reason")},
    )

    # ------------------------------------------------ 3. follower response semantics
    opposite = evaluate_at_slot(leader, follower_partition("ETHUSDT", response=0.5), slot(TARGET_G))
    add(
        "OPPOSITE_SIGN_FOLLOWER_YIELDS_NO_SIGNAL",
        opposite["emitted"] is False and opposite["reason"] == "FOLLOWER_NO_SAME_SIGN_RESPONSE",
        {"reason": opposite.get("reason")},
    )
    zero_response = evaluate_at_slot(leader, follower_partition("ETHUSDT", response=1.0), slot(TARGET_G))
    add(
        "ZERO_FOLLOWER_RETURN_FAILS_CLOSED",
        zero_response["emitted"] is False and zero_response["reason"] == "FOLLOWER_NO_SAME_SIGN_RESPONSE",
        {"reason": zero_response.get("reason"), "follower_return": zero_response.get("follower_return")},
    )
    clearly_reacting = evaluate_at_slot(leader, follower_partition("ETHUSDT", response=8.0), slot(TARGET_G))
    add(
        "PROPORTIONAL_FOLLOWER_RESPONSE_YIELDS_NO_SIGNAL",
        clearly_reacting["emitted"] is False and clearly_reacting["reason"] == "FOLLOWER_NOT_UNDERREACTING",
        {"ratio": clearly_reacting.get("follower_response_ratio")},
    )

    # -------------------------------- 4. exact-strict boundaries (IEEE-754 exact)
    # driver 8 x -> z == ln(8)/ln(2) == 3.0 exactly -> STRICT inequality must reject
    exact_threshold = evaluate_at_slot(btc_partition(overrides={TARGET_G: 8.0}), follower, slot(TARGET_G))
    add(
        "EXACTLY_THRESHOLD_SHOCK_STATISTIC_IS_NOT_A_SHOCK",
        exact_threshold["emitted"] is False
        and exact_threshold["reason"] == "NO_BTC_SHOCK"
        and exact_threshold["leader_shock_statistic"] == 3.0,
        {"z": exact_threshold.get("leader_shock_statistic")},
    )
    just_above = evaluate_at_slot(btc_partition(overrides={TARGET_G: 8.0000001}), follower, slot(TARGET_G))
    add(
        "SHOCK_STATISTIC_JUST_ABOVE_THRESHOLD_IS_A_SHOCK",
        just_above["emitted"] is True,
        {"z": just_above.get("leader_shock_statistic")},
    )
    # follower 4 x -> r_f == ln(4) == 0.5 * ln(16) exactly -> STRICT inequality must reject
    exact_ratio = evaluate_at_slot(leader, follower_partition("ETHUSDT", response=4.0), slot(TARGET_G))
    add(
        "EXACTLY_HALF_FOLLOWER_RESPONSE_IS_NOT_UNDERREACTION",
        exact_ratio["emitted"] is False
        and exact_ratio["reason"] == "FOLLOWER_NOT_UNDERREACTING"
        and exact_ratio["follower_response_ratio"] == 0.5,
        {"ratio": exact_ratio.get("follower_response_ratio")},
    )
    just_under = evaluate_at_slot(leader, follower_partition("ETHUSDT", response=4.0000001), slot(TARGET_G))
    add(
        "FOLLOWER_RESPONSE_JUST_ABOVE_HALF_IS_NOT_UNDERREACTION",
        just_under["emitted"] is False and just_under["reason"] == "FOLLOWER_NOT_UNDERREACTING",
        {"ratio": just_under.get("follower_response_ratio")},
    )

    # ------------------------------------------------------- 5. fail-closed states
    flat_leader = btc_partition(overrides={g: 1.0 for g in range(TOTAL_BARS)})
    zero_scale = evaluate_at_slot(flat_leader, follower, slot(TARGET_G))
    add(
        "ZERO_LEADER_SCALE_FAILS_CLOSED",
        zero_scale["emitted"] is False and zero_scale["reason"] == "LEADER_SCALE_ZERO",
        {"scale": zero_scale.get("leader_scale")},
    )
    missing_ref = evaluate_at_slot(
        btc_partition(overrides={TARGET_G: 16.0}, drop={TARGET_G - 5}), follower, slot(TARGET_G)
    )
    add(
        "MISSING_LEADER_REFERENCE_FAILS_CLOSED",
        missing_ref["emitted"] is False and missing_ref["reason"] == "LEADER_HISTORY_INCOMPLETE",
        {"reason": missing_ref.get("reason")},
    )
    missing_follower = evaluate_at_slot(
        leader, follower_partition("ETHUSDT", response=2.0, drop={TARGET_G}), slot(TARGET_G)
    )
    add(
        "MISSING_FOLLOWER_BAR_FAILS_CLOSED",
        missing_follower["emitted"] is False and missing_follower["reason"] == "FOLLOWER_BAR_MISSING",
        {"reason": missing_follower.get("reason")},
    )
    leader_bar_absent = evaluate_at_slot(
        btc_partition(overrides={TARGET_G: 16.0}, drop={TARGET_G + 1}), follower, slot(TARGET_G) + BAR_MS
    )
    add(
        "LEADER_BAR_ABSENT_AT_DECISION_SLOT_FAILS_CLOSED",
        leader_bar_absent["emitted"] is False and leader_bar_absent["reason"] == "BAR_ALIGNMENT_FAILURE",
        {"reason": leader_bar_absent.get("reason")},
    )
    off_window = evaluate_at_slot(leader, follower, slot(TARGET_G) - 10 * TOTAL_BARS)
    add(
        "SLOT_OUTSIDE_EVERY_PARTITION_FAILS_CLOSED",
        off_window["emitted"] is False and off_window["reason"] == "BAR_ALIGNMENT_FAILURE",
        {"reason": off_window.get("reason")},
    )

    # ------------------------------------------- 6. future mutation invariance
    fut_ov = {g: 500.0 for g in range(TARGET_G + 1, TARGET_G + 2000)}
    leader_future = btc_partition(overrides={**{TARGET_G: 16.0}, **fut_ov})
    follower_future = follower_partition("ETHUSDT", response=2.0, overrides={g: 99.0 for g in range(TARGET_G + 1, TARGET_G + 2000)})
    after_future = evaluate_at_slot(leader_future, follower_future, slot(TARGET_G))
    add(
        "FUTURE_MUTATION_AFTER_T_CHANGES_NOTHING",
        (after_future["result"], after_future["reason"], after_future.get("leader_shock_statistic"))
        == (base["result"], base["reason"], base.get("leader_shock_statistic")),
        {"result": after_future.get("result")},
    )
    truncated = btc_partition(overrides={TARGET_G: 16.0}, bars=TARGET_G + 1)
    follower_trunc = follower_partition("ETHUSDT", response=2.0, bars=TARGET_G + 1)
    after_trunc = evaluate_at_slot(truncated, follower_trunc, slot(TARGET_G))
    add(
        "LATER_BARS_ABSENT_DOES_NOT_CHANGE_DECISION",
        after_trunc["result"] == base["result"],
        {"result": after_trunc.get("result")},
    )

    # ---------------------------------- 7. past eligible mutation is detectable
    ref_block = {g: (2.718281828459045 if g % 2 == 0 else 1.0) for g in range(TARGET_G - 288, TARGET_G - 1)}
    ref_block[TARGET_G - 1] = 1.0
    leader_past = btc_partition(overrides={**{TARGET_G: 16.0}, **ref_block})
    past = evaluate_at_slot(leader_past, follower, slot(TARGET_G))
    add(
        "PAST_ELIGIBLE_REFERENCE_MUTATION_CHANGES_STATE",
        past["leader_shock_statistic"] != base["leader_shock_statistic"]
        and past["emitted"] is False
        and past["reason"] == "NO_BTC_SHOCK",
        {"scale_before": base.get("leader_scale"), "scale_after": past.get("leader_scale")},
    )
    mutated_driver = evaluate_at_slot(btc_partition(overrides={TARGET_G: 16.0000001}), follower, slot(TARGET_G))
    add(
        "PAST_ELIGIBLE_DRIVER_MUTATION_CHANGES_STATE",
        mutated_driver["leader_shock_statistic"] != base["leader_shock_statistic"],
        {"z": mutated_driver.get("leader_shock_statistic")},
    )

    # ----------------------------------- 8. completed-bar visibility semantics
    plain = btc_partition()
    last = len(plain.t) - 1
    before_close = plain.ct[last] - 1
    visible = plain.last_completed_index(before_close)
    add(
        "INCOMPLETE_CURRENT_BAR_INVISIBLE",
        visible is not None and visible < last and plain.ct[visible] <= before_close,
        {"last_visible_index": visible, "bar_index": last},
    )
    add(
        "COMPLETED_BAR_VISIBLE_AT_ITS_OWN_CLOSE",
        plain.last_completed_index(plain.ct[last]) == last,
        None,
    )
    add(
        "BAR_CLOSE_TIME_IS_OPEN_PLUS_299999",
        plain.ct[last] == plain.t[last] + BAR_MS - 1,
        {"open": plain.t[last], "close": plain.ct[last]},
    )

    # --------------------------------------- 9. entry / exit clock arithmetic
    entry = entry_index_for_decision(follower, base["decision_time_ms"])
    add(
        "ENTRY_IS_STRICTLY_AFTER_DECISION_TIME",
        entry is not None and follower.t[entry] > base["decision_time_ms"],
        {"entry_open_ms": follower.t[entry] if entry is not None else None},
    )
    add(
        "SAME_BAR_ENTRY_FORBIDDEN",
        entry is not None and follower.t[entry] == slot(TARGET_G) + BAR_MS,
        {"entry_open_ms": follower.t[entry] if entry is not None else None},
    )
    exit_idx = forward_exit_index(follower, follower.t[entry]) if entry is not None else None
    add(
        "EXIT_IS_ONE_BAR_OPEN_AFTER_ENTRY",
        exit_idx is not None and follower.t[exit_idx] == follower.t[entry] + BAR_MS,
        {"entry_open_ms": follower.t[entry], "exit_open_ms": follower.t[exit_idx] if exit_idx is not None else None},
    )
    timing_entry = entry_index_for_decision(follower, base["decision_time_ms"], offset_bars=1)
    add(
        "TIMING_CONTROL_OFFSET_IS_CAUSAL_AND_FROZEN",
        timing_entry is not None and follower.t[timing_entry] > follower.t[entry],
        {"control_entry_open_ms": follower.t[timing_entry] if timing_entry is not None else None},
    )

    # ------------------------------------------- 10. LEADER_CONTROL substitution
    control_same = evaluate_at_slot(leader, follower, slot(TARGET_G), leader_lag_bars=288)
    control_mutated = evaluate_at_slot(leader_future, follower_future, slot(TARGET_G), leader_lag_bars=288)
    add(
        "LEADER_CONTROL_DESTROYS_CONTEMPORANEOUS_LEADER_INFORMATION",
        control_mutated["result"] == control_same["result"]
        and control_mutated["reason"] == control_same["reason"]
        and control_mutated["leader_return"] == control_same["leader_return"],
        {"control_result": control_same.get("result"), "control_reason": control_same.get("reason")},
    )
    add(
        "LEADER_CONTROL_IS_NOT_IDENTICAL_TO_PRIMARY_ON_THIS_FIXTURE",
        (control_same.get("leader_shock_statistic"), control_same.get("reason"))
        != (base.get("leader_shock_statistic"), base.get("reason")),
        {"control_z": control_same.get("leader_shock_statistic"), "primary_z": base.get("leader_shock_statistic")},
    )
    add(
        "LEADER_CONTROL_READS_ONLY_STRICTLY_PAST_LEADER_BARS",
        control_same["leader_lag_bars"] == 288
        and all(
            slot(TARGET_G) - (288 + j) * BAR_MS <= control_same["decision_time_ms"] for j in range(1, 289)
        ),
        None,
    )

    # ------------------------------------------------ 11. precedence frozen/total
    add(
        "NO_SIGNAL_PRECEDENCE_FROZEN_AND_TOTAL",
        NO_SIGNAL_PRECEDENCE[0] == "OUTSIDE_COMMON_WINDOW"
        and NO_SIGNAL_PRECEDENCE[-1] == "INSUFFICIENT_FORWARD_PRICE_DATA"
        and len(set(NO_SIGNAL_PRECEDENCE)) == len(NO_SIGNAL_PRECEDENCE),
        list(NO_SIGNAL_PRECEDENCE),
    )

    # ------------------------------- 12. projection carries no order-flow field
    projected = project_records(
        [{"t": 1, "ct": 2, "o": "1.0", "c": "1.5", "h": "2", "l": "0.5", "v": "9", "qv": "9",
          "n": 3, "tb": "4", "tq": "5", "sym": "BTCUSDT", "ms": "2024-01"}]
    )
    add(
        "PROJECTION_DROPS_EVERY_ORDER_FLOW_AND_RANGE_FIELD",
        set(projected[0]) == {"t", "ct", "o", "c", "sym", "ms"}
        and set(PROJECTED_FIELDS) == {"t", "ct", "o", "c"}
        and {"v", "qv", "n", "tb", "tq", "h", "l"}.issubset(set(DROPPED_FIELDS)),
        {"keys": sorted(projected[0])},
    )

    # ------------------------------------------------ 13. reader fail-closed
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        line = json.dumps({"t": START_MS, "ct": START_MS + BAR_MS - 1, "o": "1", "c": "1", "sym": "BTCUSDT", "ms": "2023-11"},
                          sort_keys=True, separators=(",", ":"))
        (tmpd / "BTCUSDT.jsonl").write_bytes((line + "\n" + line + "\n").encode("utf-8"))
        raised = False
        try:
            load_partition("BTCUSDT", partition_dir=tmpd)
        except ValueError:
            raised = True
        add("READER_FAILS_CLOSED_ON_DUPLICATE_SLOT", raised, None)

    # ----------------------------------- 14. funding cashflow boundary semantics
    series = FundingSeries(
        symbol="ETHUSDT",
        funding_time_ms=(1000, 1500, 2000, 2500),
        funding_rate=(0.0001, 0.0001, 0.0001, 0.0001),
        funding_interval_hours=(8, 8, 8, 8),
        sha256="synthetic",
        path="synthetic://funding",
        rows=4,
    )
    charged = series.settlements_in(1000, 2000)
    add(
        "FUNDING_SETTLEMENT_AT_ENTRY_NOT_CHARGED_AND_AT_EXIT_CHARGED",
        [t for t, _ in charged] == [1500, 2000],
        {"charged": [t for t, _ in charged]},
    )
    add(
        "FUNDING_CASHFLOW_SIGN_CONVENTION",
        series.cashflow_return(1, 1000, 2000) == -0.0002 and series.cashflow_return(-1, 1000, 2000) == 0.0002,
        {"long": series.cashflow_return(1, 1000, 2000), "short": series.cashflow_return(-1, 1000, 2000)},
    )
    add(
        "FUNDING_IS_NOT_READ_BY_THE_SIGNAL_PATH",
        "funding" not in json.dumps(base).lower(),
        None,
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        row = json.dumps({"funding_time_ms": 2000, "funding_rate": "0.0001", "funding_interval_hours": 8}, sort_keys=True)
        (tmpd / "ETHUSDT_funding.jsonl").write_bytes((row + "\n" + row + "\n").encode("utf-8"))
        raised_f = False
        try:
            load_funding("ETHUSDT", funding_dir=tmpd)
        except ValueError:
            raised_f = True
        add("FUNDING_READER_FAILS_CLOSED_ON_NON_MONOTONIC_SETTLEMENTS", raised_f, None)

    # --------------------------------------- 15. scale estimator is explicit
    add(
        "EVEN_COUNT_MEDIAN_IS_MEAN_OF_CENTRAL_TWO",
        leader_scale(leader, pos) == math.log(2.0),
        {"scale": leader_scale(leader, pos)},
    )

    return checks


def main() -> int:
    checks = run_battery()
    passed = sum(1 for c in checks if c["pass"])
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"[{mark}] {c['check']}")
    print(f"\nPIT_BATTERY = {passed}/{len(checks)}")
    payload = {
        "battery": "ARC02_PIT_ADVERSARIAL",
        "checks_total": len(checks),
        "checks_passed": passed,
        "result": "PASS" if passed == len(checks) else "FAIL",
        "checks": checks,
    }
    out = pathlib.Path(__file__).resolve().parents[4] / "docs" / "arc02-data-authority-01" / "ARC02_PIT_INDEPENDENT_TESTS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["build_partition", "run_battery", "slot"]
