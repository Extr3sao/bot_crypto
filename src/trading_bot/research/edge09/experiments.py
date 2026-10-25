"""WP-EDGE-09E — the controlled experiments, run only where the gates allow.

Every experiment here answers a registered hypothesis with numbers that the
independent verifier can recompute from the same panel, and every one of them is
classified by :func:`trading_bot.research.edge09.verdict.classify` — the
classification is not written by hand anywhere.

Two honesty rules the code enforces rather than promises:

* **executable means long-only.** This runtime's product is spot; a long/short
  spread is reported for the record but is *not* the quantity the verdict is
  taken on, because the venue's margin short leg has no point-in-time data and
  is not executable here.
* **the negative control is part of the package.** E-07 runs the identical
  pipeline on a feature destroyed on purpose; if it ever comes out positive, the
  package's other results are void and the run says so.
"""

from __future__ import annotations

import statistics
from typing import Any

from .panel import PanelMap, PanelSeries
from .registration import ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY, HORIZONS_SECONDS
from .verdict import classify

#: Fraction of the stream used as the high-imbalance set in the long-only test.
HIGH_FRACTION = 0.25

#: The quantile used by the frequency experiment, registered before running.
SELECTOR_QUANTILE = 0.90


def imbalance(row: dict[str, Any]) -> float | None:
    """Size imbalance at the touch: +1 is all bid, -1 is all ask, None is no data."""
    bid_qty = float(row["bid_qty"])
    ask_qty = float(row["ask_qty"])
    total = bid_qty + ask_qty
    if total <= 0:
        return None
    return (bid_qty - ask_qty) / total


def rank(values: list[float]) -> list[float]:
    """Average ranks, so ties do not create a false order."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation with average ranks, so ties do not create an order."""
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    mean_x = statistics.fmean(rx)
    mean_y = statistics.fmean(ry)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    denom_x = sum((a - mean_x) ** 2 for a in rx) ** 0.5
    denom_y = sum((b - mean_y) ** 2 for b in ry) ** 0.5
    if denom_x == 0.0 or denom_y == 0.0:
        return None
    return float(numerator / (denom_x * denom_y))


def _shuffled(values: list[float], seed: int = 20261014) -> list[float]:
    """A deterministic permutation, so the negative control is reproducible."""
    state = seed
    shuffled = list(values)
    for index in range(len(shuffled) - 1, 0, -1):
        state = (1103515245 * state + 12345) % (2**31)
        swap = state % (index + 1)
        shuffled[index], shuffled[swap] = shuffled[swap], shuffled[index]
    return shuffled


def imbalance_experiment(
    series: PanelSeries,
    *,
    horizon_seconds: int,
    barrier_bps: float | None,
    track: str,
    shuffled_feature: bool = False,
) -> dict[str, Any]:
    """E-01 (and, with ``shuffled_feature``, the E-07 negative control)."""
    features: list[float] = []
    returns: list[float] = []
    lags: list[int] = []
    for index, row in enumerate(series.rows):
        value = imbalance(row)
        if value is None:
            continue
        forward = series.forward_return_bps(index, horizon_seconds)
        if forward is None:
            continue
        partner = series.index_at_or_after(row["decision_time"] + horizon_seconds * 1000)
        if partner is None:  # pragma: no cover - forward_return_bps already excludes it
            continue
        features.append(value)
        returns.append(forward)
        lags.append(
            series.rows[partner]["decision_time"] - (row["decision_time"] + horizon_seconds * 1000)
        )
    if shuffled_feature:
        features = _shuffled(features)
    if len(features) < 3:
        return _cell(series, horizon_seconds, len(features), None, None, barrier_bps, track)
    ordered = sorted(range(len(features)), key=lambda index: features[index])
    cut = max(1, int(len(ordered) * HIGH_FRACTION))
    low_set = [returns[index] for index in ordered[:cut]]
    high_set = [returns[index] for index in ordered[-cut:]]
    ic = spearman(features, returns)
    result = _cell(
        series,
        horizon_seconds,
        len(features),
        ic,
        {
            "long_only_mean_bps": round(statistics.fmean(high_set), 6),
            "low_set_mean_bps": round(statistics.fmean(low_set), 6),
            "spread_bps": round(statistics.fmean(high_set) - statistics.fmean(low_set), 6),
            "high_set_hit_rate": round(
                sum(1 for value in high_set if value > 0) / len(high_set), 6
            ),
            "hop_mid_bps": round(statistics.fmean(abs(value) for value in returns), 6),
        },
        barrier_bps,
        track,
    )
    result["pit"] = {
        "paired_windows": len(lags),
        "min_partner_lag_ms": min(lags) if lags else None,
        "max_partner_lag_ms": max(lags) if lags else None,
        "rule": "partner row is the first whose decision clock is at or after decision+h",
    }
    result["negative_control"] = shuffled_feature
    return result


def _cell(
    series: PanelSeries,
    horizon_seconds: int,
    n: int,
    ic: float | None,
    stats: dict[str, float] | None,
    barrier_bps: float | None,
    track: str,
) -> dict[str, Any]:
    gross = stats["long_only_mean_bps"] if stats else None
    verdict = classify(
        n=n,
        ic=ic,
        gross_bps=gross,
        cost_bps=barrier_bps,
        track=track,
    )
    return {
        "run": series.run,
        "market": series.market,
        "symbol": series.symbol,
        "horizon_seconds": horizon_seconds,
        "n": n,
        "ic": None if ic is None else round(ic, 6),
        "stats": stats,
        "verdict": verdict,
    }


def frequency_experiment(
    series: PanelSeries, *, horizon_seconds: int, barrier_bps: float | None
) -> dict[str, Any]:
    """E-05: how many barrier-clearing opportunities a selector would find.

    Two counts are produced because they mean different things. The *long-only*
    count is what this runtime's spot product could actually execute; the
    any-direction count also counts downward moves, which only a short book could
    take and which is reported for the record, never as an opportunity.

    The rate is per day but the span it is extrapolated from is carried on the
    row: the capture is hours long, so the number is an upper-bound rate and not
    a day count.
    """
    values: list[float] = []
    forward: list[float] = []
    for index, row in enumerate(series.rows):
        value = imbalance(row)
        if value is None:
            continue
        move = series.forward_return_bps(index, horizon_seconds)
        if move is None:
            continue
        values.append(abs(value))
        forward.append(move)
    span_days = series.span_seconds() / 86_400.0
    if not values or span_days <= 0 or barrier_bps is None:
        return {
            "run": series.run,
            "market": series.market,
            "symbol": series.symbol,
            "horizon_seconds": horizon_seconds,
            "opportunities_per_day": None,
            "note": "no measurable span or barrier",
        }
    ordered = sorted(values)
    threshold = ordered[min(len(ordered) - 1, int(SELECTOR_QUANTILE * (len(ordered) - 1)))]
    selected = [move for value, move in zip(values, forward, strict=True) if value >= threshold]
    clearing_long_only = sum(1 for move in selected if move >= barrier_bps)
    clearing_any_direction = sum(1 for move in selected if abs(move) >= barrier_bps)
    return {
        "run": series.run,
        "market": series.market,
        "symbol": series.symbol,
        "horizon_seconds": horizon_seconds,
        "span_days": round(span_days, 5),
        "span_hours": round(span_days * 24.0, 3),
        "selector": f"|imbalance| >= {round(threshold, 4)} (q{int(SELECTOR_QUANTILE * 100)})",
        "selected": len(selected),
        "selected_per_day": round(len(selected) / span_days, 3),
        "clearing": clearing_any_direction,
        "clearing_long_only": clearing_long_only,
        "clearing_any_direction": clearing_any_direction,
        "opportunities_per_day": round(clearing_long_only / span_days, 3),
        "opportunities_per_day_any_direction": round(clearing_any_direction / span_days, 3),
        "barrier_bps": barrier_bps,
        "is_executable_long_only": True,
        "rate_extrapolated_from_hours": True,
    }


def pool_frequency(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pool the per-stream opportunity rates into one row per horizon.

    Each stream's rate is already per day, so the pooled rate is the sum over
    streams, taken separately for each registered horizon: summing across
    horizons would count the same tape several times. The span every rate was
    extrapolated from is carried on the row, because a rate taken from a
    two-hour capture is not a day count.
    """
    rows: list[dict[str, Any]] = []
    for horizon in sorted({cell["horizon_seconds"] for cell in cells}):
        selected = [
            cell
            for cell in cells
            if cell["horizon_seconds"] == horizon
            and cell.get("span_days")
            and cell.get("opportunities_per_day") is not None
        ]
        if not selected:
            rows.append(
                {
                    "horizon_seconds": horizon,
                    "streams_summed": 0,
                    "opportunities_per_day": None,
                    "opportunities_per_day_any_direction": None,
                    "meets_target": None,
                    "note": "no stream carried a measurable span at this horizon",
                }
            )
            continue
        spans = sorted({cell["span_days"] for cell in selected})
        long_only = sum(cell["opportunities_per_day"] for cell in selected)
        any_direction = sum(
            cell.get("opportunities_per_day_any_direction") or 0.0 for cell in selected
        )
        rows.append(
            {
                "horizon_seconds": horizon,
                "streams_summed": len(selected),
                "span_days_min": round(spans[0], 5),
                "span_days_max": round(spans[-1], 5),
                "hours_min": round(spans[0] * 24.0, 3),
                "hours_max": round(spans[-1] * 24.0, 3),
                "opportunities_per_day": round(long_only, 3),
                "opportunities_per_day_any_direction": round(any_direction, 3),
                "active_target_per_day": ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
                "meets_target": long_only >= ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
                "is_upper_bound": True,
                "is_executable_long_only": True,
                "rate_extrapolated_from_hours": True,
            }
        )
    return rows


def frequency_classification(pooled: list[dict[str, Any]]) -> dict[str, Any]:
    """The registered F5 verdict, read from the pooled rows.

    ``FREQUENCY_KILLED`` is claimed only when *every* horizon with a measurable
    span is below the target. One horizon that meets it is reported as such: the
    objective is then a cost-and-information question, not an arithmetic one.
    """
    measured = [row for row in pooled if row.get("opportunities_per_day") is not None]
    meeting = [row for row in measured if row.get("meets_target")]
    if not measured:
        return {
            "classification": "INSUFFICIENT_SAMPLE",
            "failed_filter": "F5",
            "reason": "no horizon carried a measurable span",
            "n": 0,
            "promotion": "NONE",
        }
    hours = sorted({(row["hours_min"], row["hours_max"]) for row in measured})
    span = f"{hours[0][0]}-{hours[-1][1]} h" if hours else "an unstated span"
    if meeting:
        detail = ", ".join(
            f"h={row['horizon_seconds']}s at {row['opportunities_per_day']} long-only "
            f"opportunities/day"
            for row in sorted(meeting, key=lambda row: row["horizon_seconds"])
        )
        return {
            "classification": "OBSERVED",
            "failed_filter": "—",
            "reason": (
                f"the tape clears the barrier at {detail} (upper bound, long-only, "
                f"extrapolated from {span} of capture), so the ACTIVE frequency target is "
                f"not what blocks the book at those horizons"
            ),
            "n": sum(row.get("streams_summed") or 0 for row in meeting),
            "promotion": "NONE",
        }
    below = ", ".join(
        f"h={row['horizon_seconds']}s at {row['opportunities_per_day']}"
        for row in sorted(measured, key=lambda row: row["horizon_seconds"])
    )
    return {
        "classification": "FREQUENCY_KILLED",
        "failed_filter": "F5",
        "reason": (
            f"every measured horizon stays below the ACTIVE target of "
            f"{ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY}/day ({below}; long-only, extrapolated "
            f"from {span} of capture)"
        ),
        "n": sum(row.get("streams_summed") or 0 for row in measured),
        "promotion": "NONE",
    }


def execution_experiment(series: PanelSeries) -> dict[str, Any]:
    """E-06: what a taker actually pays, measured against the mid at the decision."""
    shortfalls: list[float] = []
    delays: list[int] = []
    for index, row in enumerate(series.rows):
        if row["trades"] <= 0 or row["last_trade_price"] <= 0 or row["mid"] <= 0:
            continue
        found = series.first_trade_after(index + 1)
        if found is None:
            continue
        price, delay = found
        shortfalls.append(abs(price - row["mid"]) / row["mid"] * 10_000.0)
        delays.append(delay)
    if not shortfalls:
        return {
            "run": series.run,
            "market": series.market,
            "symbol": series.symbol,
            "observations": 0,
            "note": "no prints after a decision instant in this stream",
        }
    ordered = sorted(shortfalls)
    return {
        "run": series.run,
        "market": series.market,
        "symbol": series.symbol,
        "observations": len(shortfalls),
        "median_shortfall_bps": round(statistics.median(ordered), 6),
        "mean_shortfall_bps": round(statistics.fmean(ordered), 6),
        "p90_shortfall_bps": round(ordered[int(0.9 * (len(ordered) - 1))], 6),
        "median_delay_rows": int(statistics.median(delays)),
    }


def oi_quadrant_experiment(
    series: PanelSeries, oi_samples: list[dict[str, Any]], *, horizon_rows: int = 300
) -> dict[str, Any]:
    """E-04: price against open interest, on the 5-minute clock."""
    if not oi_samples:
        return {
            "run": series.run,
            "market": series.market,
            "symbol": series.symbol,
            "cells": {},
            "states": 0,
            "note": "no forward open-interest samples were captured for this stream",
        }
    #: A settlement grid of 5 minutes, using the panel's own decision clocks.
    grid = [index for index, row in enumerate(series.rows) if row["second_ms"] % 300_000 == 0]
    buckets: dict[str, list[float]] = {
        "PRICE_UP_OI_UP": [],
        "PRICE_UP_OI_DOWN": [],
        "PRICE_DOWN_OI_UP": [],
        "PRICE_DOWN_OI_DOWN": [],
    }
    states = 0
    previous_oi: float | None = None
    oi_by_time = sorted(oi_samples, key=lambda item: item["ts_ms"])
    cursor = 0
    for index in grid:
        row = series.rows[index]
        while cursor < len(oi_by_time) and oi_by_time[cursor]["ts_ms"] <= row["decision_time"]:
            previous_oi = oi_by_time[cursor]["open_interest"]
            cursor += 1
        if previous_oi is None:
            continue
        later_oi = None
        for sample in oi_by_time[cursor : cursor + 40]:
            later_oi = sample["open_interest"]
            break
        if later_oi is None:
            continue
        move = series.forward_return_bps(index, 300)
        if move is None:
            continue
        states += 1
        price_up = move > 0
        oi_up = later_oi > previous_oi
        key = (
            "PRICE_UP_OI_UP"
            if price_up and oi_up
            else "PRICE_UP_OI_DOWN"
            if price_up
            else "PRICE_DOWN_OI_UP"
            if oi_up
            else "PRICE_DOWN_OI_DOWN"
        )
        buckets[key].append(move)
    cells = {
        key: {
            "n": len(values),
            "mean_bps": round(statistics.fmean(values), 6) if values else None,
            "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 6)
            if values
            else None,
        }
        for key, values in buckets.items()
    }
    return {
        "run": series.run,
        "market": series.market,
        "symbol": series.symbol,
        "states": states,
        "cells": cells,
        "grid_rows": len(grid),
    }


def run_all(
    series_map: PanelMap,
    *,
    barriers: dict[tuple[str, str], float],
    oi_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """E-01, E-04, E-05, E-06 and the E-07 negative control, per stream."""
    results: dict[str, list[dict[str, Any]]] = {
        "E-01_imbalance": [],
        "E-04_oi_quadrant": [],
        "E-05_frequency": [],
        "E-06_execution": [],
        "E-07_negative_control": [],
    }
    for (run, market, symbol), series in sorted(series_map.items()):
        barrier = barriers.get((market, symbol))
        for horizon in HORIZONS_SECONDS:
            results["E-01_imbalance"].append(
                imbalance_experiment(
                    series,
                    horizon_seconds=horizon,
                    barrier_bps=barrier,
                    track="ACTIVE",
                )
            )
            results["E-07_negative_control"].append(
                imbalance_experiment(
                    series,
                    horizon_seconds=horizon,
                    barrier_bps=barrier,
                    track="ACTIVE",
                    shuffled_feature=True,
                )
            )
            results["E-05_frequency"].append(
                frequency_experiment(series, horizon_seconds=horizon, barrier_bps=barrier)
            )
        results["E-06_execution"].append(execution_experiment(series))
        if market == "perp":
            stream_oi = [
                sample
                for sample in oi_samples
                if sample["run"] == run and sample["symbol"] == symbol
            ]
            results["E-04_oi_quadrant"].append(oi_quadrant_experiment(series, stream_oi))
    return results


__all__ = [
    "HIGH_FRACTION",
    "SELECTOR_QUANTILE",
    "execution_experiment",
    "frequency_classification",
    "frequency_experiment",
    "imbalance",
    "imbalance_experiment",
    "oi_quadrant_experiment",
    "pool_frequency",
    "rank",
    "run_all",
    "spearman",
]
