"""WP-EDGE-09D — the cost, liquidity, capacity and frequency gates.

Every number here is either *measured* on the panel built from the forward
capture or *taken from the authoritative cost model* (V3/V4) with the measured
spread and volatility substituted for the model's assumptions. Nothing is
assumed, and a missing measurement is reported as missing.

The three questions the gate answers:

* **Cost.** What does one round trip cost, per asset and market, on this venue
  and on every venue this project has registered a fee schedule for?
* **Capacity.** How much notional the captured book offers inside a
  barrier-implied band, so the modelled impact is not a fiction?
* **Frequency.** How many opportunities per day the tape itself offers — an
  upper bound that no predictor can beat, and the comparison against the
  registered ACTIVE objective of three executed trades a day.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from .panel import PanelMap, PanelSeries, read_depth, read_oi, read_panel_map
from .registration import (
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    FREQUENCY_HORIZONS_SECONDS,
    GRID_SECONDS,
    HORIZONS_SECONDS,
    SCENARIOS_COMPARED,
    UNIVERSE,
)

#: The size a cost is quoted at. Same as the frozen admission scenario.
QUOTE_SIZE_USD = 1_000.0

#: The runtime's own floor for an order; a capacity claim below it is not usable.
MIN_ORDER_NOTIONAL_USDT = 20.0


def spread_stats(series_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measured relative spread of one stream, in bps."""
    spreads = sorted(row["spread_bps"] for row in series_rows if row["spread_bps"] > 0)
    if not spreads:
        return {"observations": 0, "median_bps": None, "mean_bps": None, "p90_bps": None}
    return {
        "observations": len(spreads),
        "median_bps": round(statistics.median(spreads), 6),
        "mean_bps": round(statistics.fmean(spreads), 6),
        "p90_bps": round(spreads[int(0.9 * (len(spreads) - 1))], 6),
        "min_bps": round(spreads[0], 6),
        "max_bps": round(spreads[-1], 6),
    }


def realized_vol_bps(series: PanelSeries, horizon_seconds: int) -> dict[str, Any]:
    """Realized volatility of the mid over the horizon, in bps, gap-aware."""
    returns = [
        value
        for index in range(len(series))
        if (value := series.forward_return_bps(index, horizon_seconds)) is not None
    ]
    if len(returns) < 2:
        return {"observations": len(returns), "stdev_bps": None, "mean_abs_bps": None}
    return {
        "observations": len(returns),
        "stdev_bps": round(statistics.stdev(returns), 6),
        "mean_abs_bps": round(statistics.fmean(abs(value) for value in returns), 6),
        "mean_bps": round(statistics.fmean(returns), 6),
    }


def barrier_rows(
    series_map: PanelMap,
) -> list[dict[str, Any]]:
    """One row per (market, symbol, venue scenario) with the measured cost."""
    from trading_bot.research.microstructure.cost_model_v4 import (
        AssetMarketInput,
        asset_cost_v4,
    )

    rows: list[dict[str, Any]] = []
    for (run, market, symbol), series in sorted(series_map.items()):
        spread = spread_stats(series.rows)
        if not spread["observations"]:
            continue
        vol = realized_vol_bps(series, horizon_seconds=HORIZONS_SECONDS[-1])
        if vol["stdev_bps"] is None:
            continue
        market_input = AssetMarketInput(
            asset=symbol.replace("USDT", ""),
            symbol=symbol,
            observed_spread_bps=spread["median_bps"],
            spread_observations=spread["observations"],
            spread_source=f"EDGE-09 panel, {run} {market}, quote level, 1 s grid",
            realized_vol_bps=vol["stdev_bps"],
            vol_source=f"EDGE-09 panel, {run} {market}, {HORIZONS_SECONDS[-1]} s horizon",
        )
        for scenario in SCENARIOS_COMPARED:
            try:
                cost = asset_cost_v4(
                    market_input,
                    scenario_id=scenario,
                    size_usd=QUOTE_SIZE_USD,
                    horizon_minutes=HORIZONS_SECONDS[-1] / 60.0,
                )
            except (KeyError, ValueError) as exc:  # pragma: no cover - registered ids only
                rows.append(
                    {
                        "run": run,
                        "market": market,
                        "symbol": symbol,
                        "scenario": scenario,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            payload = cost.as_dict()
            rows.append(
                {
                    "run": run,
                    "market": market,
                    "symbol": symbol,
                    "scenario": scenario,
                    "venue": payload["venue"],
                    "product": payload["product"],
                    "liquidity_regime": payload["liquidity_regime"],
                    "observed_spread_bps": payload["observed_spread_bps"],
                    "realized_vol_bps": payload["realized_vol_bps"],
                    "components_bps": payload["components_bps"],
                    "round_trip_bps": payload["taker_round_trip_bps"],
                    "break_even_bps": payload["minimum_gross_edge_bps"],
                    "required_bps": payload["required_gross_edge_bps"],
                    "stress_bps": payload["stress_bps"],
                    "maker_round_trip_bps_theoretical": payload["maker_round_trip_bps_bps"]
                    if "maker_round_trip_bps_bps" in payload
                    else payload["maker_round_trip_bps_theoretical"],
                    "maker_status": payload["maker_status"],
                    "spread_observations": spread["observations"],
                    "knowledge_class": payload["knowledge_class"],
                }
            )
    return rows


def capacity_rows(
    depth_rows: list[dict[str, Any]], bands_bps: tuple[float, ...]
) -> list[dict[str, Any]]:
    """Notional offered inside a band around the mid, from the captured book."""
    grouped: dict[tuple[str, str, str, int], dict[str, list[tuple[float, float]]]] = {}
    for row in depth_rows:
        key = (row["run"], row["market"], row["symbol"], row["ts_ms"])
        grouped.setdefault(key, {"bid": [], "ask": []})[row["side"]].append(
            (row["price"], row["qty"])
        )
    rows: list[dict[str, Any]] = []
    for (run, market, symbol, ts_ms), sides in sorted(grouped.items()):
        bids = sorted(sides["bid"], key=lambda item: -item[0])
        asks = sorted(sides["ask"], key=lambda item: item[0])
        if not bids or not asks:
            continue
        mid = (bids[0][0] + asks[0][0]) / 2.0
        entry: dict[str, Any] = {
            "run": run,
            "market": market,
            "symbol": symbol,
            "ts_ms": ts_ms,
            "mid": round(mid, 8),
            "levels_kept": max(len(bids), len(asks)),
            "top_of_book_usd": round(bids[0][0] * bids[0][1] + asks[0][0] * asks[0][1], 4),
        }
        for band in bands_bps:
            limit = mid * band / 10_000.0
            entry[f"bid_notional_within_{band}bps_usd"] = round(
                sum(price * qty for price, qty in bids if mid - price <= limit), 4
            )
            entry[f"ask_notional_within_{band}bps_usd"] = round(
                sum(price * qty for price, qty in asks if price - mid <= limit), 4
            )
        rows.append(entry)
    return rows


def frequency_rows(
    series_map: PanelMap, barriers_bps: dict[tuple[str, str], float]
) -> list[dict[str, Any]]:
    """How often the tape itself offers a move that clears the barrier.

    This is an *upper bound* on how many positive-edge trades a perfect selector
    could take: a trade that does not clear the barrier on the tape cannot pay
    for itself, whatever the model believed at the decision instant.
    """
    rows: list[dict[str, Any]] = []
    for (run, market, symbol), series in sorted(series_map.items()):
        barrier = barriers_bps.get((market, symbol))
        span_days = series.span_seconds() / 86_400.0
        if span_days <= 0:
            continue
        for horizon in FREQUENCY_HORIZONS_SECONDS:
            hits = 0
            measured = 0
            for index in range(len(series)):
                value = series.forward_return_bps(index, horizon)
                if value is None:
                    continue
                measured += 1
                if barrier is not None and abs(value) >= barrier:
                    hits += 1
            #: Overlapping windows describe how often a move of that size is
            #: *present*, which at a long horizon counts the same move thousands
            #: of times. The opportunity count is the non-overlapping one: a
            #: window is only taken if the previous one has closed.
            stride_taken = 0
            stride_clearing = 0
            last_ms: int | None = None
            for index, row in enumerate(series.rows):
                if last_ms is not None and row["decision_time"] < last_ms + horizon * 1000:
                    continue
                value = series.forward_return_bps(index, horizon)
                if value is None:
                    continue
                last_ms = row["decision_time"]
                stride_taken += 1
                if barrier is not None and abs(value) >= barrier:
                    stride_clearing += 1
            rows.append(
                {
                    "run": run,
                    "market": market,
                    "symbol": symbol,
                    "horizon_seconds": horizon,
                    "span_days": round(span_days, 5),
                    "measured_windows": measured,
                    "windows_clearing_barrier": hits,
                    "windows_per_day": round(measured / span_days, 1) if span_days else None,
                    "fraction_of_windows_clearing": round(hits / measured, 8) if measured else None,
                    "clearing_windows_per_day_overlapping": round(hits / span_days, 3)
                    if span_days
                    else None,
                    "non_overlapping_windows": stride_taken,
                    "non_overlapping_clearing": stride_clearing,
                    "clearing_per_day": round(stride_clearing / span_days, 3)
                    if span_days
                    else None,
                    "barrier_bps": barrier,
                    "is_upper_bound": True,
                    "counts_overlapping_windows": True,
                }
            )
    return rows


def aggregate_frequency(rows: list[dict[str, Any]], horizon_seconds: int) -> dict[str, Any]:
    """The pooled upper bound across the aggregate universe, per day.

    Every stream is an independent symbol/market pair the aggregate universe can
    trade, and each stream's rate is already per day, so the pooled bound is the
    sum over streams. The denominator of each rate is that stream's own span,
    which the row carries; the two spans here differ by a few seconds.
    """
    selected = [row for row in rows if row["horizon_seconds"] == horizon_seconds]
    if not selected:
        return {"horizon_seconds": horizon_seconds, "clearing_per_day": None}
    spans = sorted({row["span_days"] for row in selected})
    if not spans or spans[-1] <= 0:
        return {"horizon_seconds": horizon_seconds, "clearing_per_day": None}
    total = sum(row["clearing_per_day"] or 0.0 for row in selected)
    per_stream = {f"{row['market']}|{row['symbol']}": row["clearing_per_day"] for row in selected}
    positive = {key: value for key, value in per_stream.items() if value}
    return {
        "horizon_seconds": horizon_seconds,
        "span_days_min": round(spans[0], 5),
        "span_days_max": round(spans[-1], 5),
        "hours_min": round(spans[0] * 24.0, 3),
        "hours_max": round(spans[-1] * 24.0, 3),
        "rate_extrapolated_from_hours": True,
        "streams_summed": len(selected),
        "clearing_per_day": round(total, 3),
        "per_stream_per_day": per_stream,
        "streams_with_any_clearing": positive,
        "active_target_per_day": ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
        "meets_target": total >= ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
        "is_upper_bound": True,
    }


def build(panel_dir: Path) -> dict[str, Any]:
    """Read the panel and produce the whole gate payload."""
    series_map = read_panel_map(panel_dir / "PANEL_SECONDS.csv")
    depth_rows = (
        read_depth(panel_dir / "DEPTH_SNAPSHOTS.csv")
        if (panel_dir / "DEPTH_SNAPSHOTS.csv").is_file()
        else []
    )
    oi_rows = (
        read_oi(panel_dir / "OI_SAMPLES.csv") if (panel_dir / "OI_SAMPLES.csv").is_file() else []
    )
    barriers = barrier_rows(series_map)
    #: The admission scenario sets the barrier the experiments are judged by.
    admission = {
        (row["market"], row["symbol"]): row["round_trip_bps"]
        for row in barriers
        if row.get("scenario") == SCENARIOS_COMPARED[0]
    }
    frequency = frequency_rows(series_map, admission)
    return {
        "spread_by_stream": [
            {
                "run": run,
                "market": market,
                "symbol": symbol,
                **spread_stats(series.rows),
            }
            for (run, market, symbol), series in sorted(series_map.items())
        ],
        "volatility_by_stream": [
            {
                "run": run,
                "market": market,
                "symbol": symbol,
                "horizon_seconds": horizon,
                **realized_vol_bps(series, horizon),
            }
            for (run, market, symbol), series in sorted(series_map.items())
            for horizon in HORIZONS_SECONDS
        ],
        "barriers": barriers,
        "admission_barrier_bps": {
            f"{market}|{symbol}": value for (market, symbol), value in admission.items()
        },
        "capacity": capacity_rows(depth_rows, bands_bps=(1.0, 5.0, 10.0, 25.0)),
        "capacity_bands_bps": [1.0, 5.0, 10.0, 25.0],
        "min_order_notional_usdt": MIN_ORDER_NOTIONAL_USDT,
        "quote_size_usd": QUOTE_SIZE_USD,
        "frequency": frequency,
        "frequency_pooled": [
            aggregate_frequency(frequency, horizon) for horizon in FREQUENCY_HORIZONS_SECONDS
        ],
        "oi_samples": len(oi_rows),
        "universe": list(UNIVERSE),
        "grid_seconds": GRID_SECONDS,
        "streams": len(series_map),
    }


__all__ = [
    "MIN_ORDER_NOTIONAL_USDT",
    "QUOTE_SIZE_USD",
    "aggregate_frequency",
    "barrier_rows",
    "build",
    "capacity_rows",
    "frequency_rows",
    "realized_vol_bps",
    "spread_stats",
]
