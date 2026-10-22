"""WP-EDGE-08 — the registered verdicts, computed on the unread cross-section.

The decision device is ``PREREGISTRATION.json`` and nothing else. For each arm that cleared the
gross screen, the criteria in :mod:`registration` are evaluated on the cross-section's decisive
window, and the verdict is the one those criteria produce:

* ``ADMIT_PAPER`` — every decisive criterion passed. Admission to **paper only**: no live trading,
  no capital, no promotion beyond a paper lane;
* ``REJECT`` — a decisive criterion failed with power. The family is reported with its numbers and
  is *not* tuned and re-run on the same window;
* ``INSUFFICIENT_EVIDENCE`` — an unpowered sample with everything else non-negative, one trade
  carrying the net, or coverage below the declared floor;
* ``REJECT_NO_GROSS_EDGE`` — the book lost money before any fee on the known universe, so the
  cross-section was never read with it. Its holdout rows are absent, not zero.

The frozen admission gate is reported next to each verdict for comparability. ``promotion`` stays
``NONE`` and ``order_sent`` stays ``false`` for every arm, whatever the verdict says.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge08.registration import (
    COVERAGE_FLOOR_BARS,
    CRITERIA,
    MIN_TRADES,
    MULTIPLICITY,
    VERDICTS,
)

__all__ = [
    "coverage_reading",
    "criteria_reading",
    "decide",
    "verdict_payload",
]


def coverage_reading(*, bars_per_asset: dict[str, int], timeframe: str) -> dict[str, Any]:
    """Is the decisive window's cross-section deep enough to carry a verdict at all?"""
    floor = COVERAGE_FLOOR_BARS[timeframe]
    short = {asset: count for asset, count in bars_per_asset.items() if count < floor}
    return {
        "timeframe": timeframe,
        "floor_bars_per_asset": floor,
        "bars_per_asset": bars_per_asset,
        "assets_below_floor": short,
        "enough": not short,
    }


def criteria_reading(*, cells: dict[str, dict[str, Any]], track: str) -> dict[str, Any]:
    """Evaluate every registered criterion that applies to ``track`` on the decisive window."""
    decisive = cells.get("OOS", {}).get("BASE") or {}
    stress = cells.get("OOS", {}).get("2X_FEES") or {}
    dev = cells.get("DEV", {}).get("BASE") or {}
    share = decisive.get("largest_trade_share_of_net")
    positive_contexts = sum(
        1
        for value in (decisive.get("by_market_context_detail") or {}).values()
        if float(value.get("net_usdt") or 0) > 0
    )
    frequency = decisive.get("frequency") or {}
    per_day = float(frequency.get("trades_per_day_universe") or 0.0)
    checks: list[dict[str, Any]] = [
        {
            "id": "P1",
            "statement": CRITERIA["P1"]["statement"],
            "value": decisive.get("trades"),
            "passed": int(decisive.get("trades") or 0) >= MIN_TRADES,
        },
        {
            "id": "P2",
            "statement": CRITERIA["P2"]["statement"],
            "value": decisive.get("net_usdt"),
            "passed": float(decisive.get("net_usdt") or 0.0) > 0,
        },
        {
            "id": "P3",
            "statement": CRITERIA["P3"]["statement"],
            "value": decisive.get("expectancy_usdt"),
            "passed": float(decisive.get("expectancy_usdt") or 0.0) > 0,
        },
        {
            "id": "P4",
            "statement": CRITERIA["P4"]["statement"],
            "value": stress.get("net_usdt"),
            "passed": float(stress.get("net_usdt") or 0.0) > 0,
        },
        {
            "id": "P5",
            "statement": CRITERIA["P5"]["statement"],
            "value": share,
            "passed": share is not None and float(share) <= 0.5,
        },
        {
            "id": "P6",
            "statement": CRITERIA["P6"]["statement"],
            "value": positive_contexts,
            "passed": positive_contexts >= 1,
        },
        {
            "id": "R1",
            "statement": CRITERIA["R1"]["statement"],
            "value": (decisive.get("with_the_largest_winner_removed") or {}).get("net_usdt"),
            "passed": float(
                (decisive.get("with_the_largest_winner_removed") or {}).get("net_usdt") or 0.0
            )
            > 0,
        },
        {
            "id": "R2",
            "statement": CRITERIA["R2"]["statement"],
            "value": decisive.get("positive_time_blocks"),
            "passed": int(decisive.get("positive_time_blocks") or 0) >= 2,
        },
        {
            "id": "S1",
            "statement": CRITERIA["S1"]["statement"],
            "value": dev.get("gross_usdt"),
            "passed": float(dev.get("gross_usdt") or 0.0) > 0,
        },
    ]
    if track == "ACTIVE":
        checks.append(
            {
                "id": "F1",
                "statement": CRITERIA["F1"]["statement"],
                "value": per_day,
                "passed": per_day >= 3.0,
            }
        )
    else:
        checks.append(
            {
                "id": "F2",
                "statement": CRITERIA["F2"]["statement"],
                "value": per_day,
                "passed": per_day >= 0.05,
            }
        )
    decisive_checks = [
        check
        for check in checks
        if CRITERIA[check["id"]]["decisive"] and track in CRITERIA[check["id"]]["tracks"]
    ]
    failed = [check["id"] for check in decisive_checks if not check["passed"]]
    return {
        "track": track,
        "checks": checks,
        "decisive_ids": [check["id"] for check in decisive_checks],
        "failed": failed,
        "powered": int(decisive.get("trades") or 0) >= MIN_TRADES,
    }


def decide(*, reading: dict[str, Any], net_usdt: float | None) -> tuple[str, str]:
    """Turn a criteria reading into one of the four registered verdicts."""
    passed = {check["id"]: bool(check["passed"]) for check in reading["checks"]}
    failed = reading["failed"]
    if not failed:
        return (
            "ADMIT_PAPER",
            (
                "every decisive criterion passes on the cross-section's decisive window: "
                + VERDICTS["ADMIT_PAPER"]
            ),
        )
    if "P1" in failed and passed.get("P2", False) and passed.get("P4", False):
        return (
            "INSUFFICIENT_EVIDENCE",
            (
                f"unpowered sample on the cross-section with the rest non-negative "
                f"({reading['checks'][0]['value']} trades < {MIN_TRADES}); "
                + VERDICTS["INSUFFICIENT_EVIDENCE"]
            ),
        )
    if "P5" in failed and passed.get("P2", False):
        return (
            "INSUFFICIENT_EVIDENCE",
            "one trade carries the net: the concentration criterion failed; "
            + VERDICTS["INSUFFICIENT_EVIDENCE"],
        )
    return (
        "REJECT",
        f"decisive criterion failed on the cross-section: {', '.join(failed)}; {VERDICTS['REJECT']}",
    )


def verdict_payload(
    *,
    arm_id: str,
    track: str,
    screen_verdict: dict[str, Any],
    cells: dict[str, dict[str, Any]] | None,
    coverage: dict[str, Any] | None,
    gate: dict[str, Any] | None,
) -> dict[str, Any]:
    """One arm's registered outcome, with every reading the verdict rests on."""
    payload: dict[str, Any] = {
        "arm": arm_id,
        "track": track,
        "screen": {
            "id": screen_verdict.get("screen"),
            "passed": screen_verdict.get("passed"),
            "dev_gross_expectancy_usdt": screen_verdict.get("dev_gross_expectancy_usdt"),
            "dev_trades": screen_verdict.get("dev_trades"),
        },
        "multiplicity": dict(MULTIPLICITY),
        "promotion": "NONE",
        "order_sent": False,
    }
    if not screen_verdict.get("passed"):
        payload.update(
            {
                "verdict": "REJECT_NO_GROSS_EDGE",
                "why": (
                    "the gross screen (C0) failed on the known universe: a setup that loses before "
                    "any fee cannot be repaired by a fee, so the cross-section was not read with "
                    "it. " + VERDICTS["REJECT_NO_GROSS_EDGE"]
                ),
                "read_on_the_cross_section": False,
                "checks": [],
                "failed": ["C0"],
                "gate_status": None,
                "coverage": None,
            }
        )
        return payload
    assert cells is not None and coverage is not None
    reading = criteria_reading(cells=cells, track=track)
    decisive = cells.get("OOS", {}).get("BASE") or {}
    verdict, why = decide(reading=reading, net_usdt=decisive.get("net_usdt"))
    if not coverage.get("enough"):
        verdict, why = (
            "INSUFFICIENT_EVIDENCE",
            "the cross-section's coverage is below the declared floor: "
            f"{coverage.get('assets_below_floor')} against {coverage.get('floor_bars_per_asset')} "
            "bars per asset; " + VERDICTS["INSUFFICIENT_EVIDENCE"],
        )
        reading["failed"] = ["coverage"]
    payload.update(
        {
            "verdict": verdict,
            "why": why,
            "read_on_the_cross_section": True,
            "checks": reading["checks"],
            "failed": reading["failed"],
            "decisive_ids": reading["decisive_ids"],
            "powered": reading["powered"],
            "coverage": coverage,
            "gate_status": gate,
            "decisive_window": {
                "label": "OOS",
                "trades": decisive.get("trades"),
                "net_usdt": decisive.get("net_usdt"),
                "expectancy_usdt": decisive.get("expectancy_usdt"),
                "profit_factor": decisive.get("profit_factor"),
                "max_drawdown_pct": decisive.get("max_drawdown_pct"),
                "trades_per_day_universe": (decisive.get("frequency") or {}).get(
                    "trades_per_day_universe"
                ),
                "net_at_2x_fees_usdt": (
                    (cells.get("OOS", {}).get("2X_FEES") or {}).get("net_usdt")
                ),
                "net_at_adverse_usdt": (
                    (cells.get("OOS", {}).get("ADVERSE") or {}).get("net_usdt")
                ),
                "expectancy_ci_90_usdt": decisive.get("expectancy_ci_90_usdt"),
                "by_asset_detail": decisive.get("by_asset_detail"),
                "by_market_context_detail": decisive.get("by_market_context_detail"),
                "serial_dependence": decisive.get("serial_dependence"),
                "with_the_largest_winner_removed": decisive.get("with_the_largest_winner_removed"),
                "exit_reason_mix": decisive.get("exit_reason_mix"),
            },
        }
    )
    return payload
