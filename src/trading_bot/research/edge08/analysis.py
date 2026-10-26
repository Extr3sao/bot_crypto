"""WP-EDGE-08 — the readings a screen or a verdict is computed from.

Six of them, all declared in ``PREREGISTRATION.json`` before any of them was computed:

* a **trade-block bootstrap** confidence interval for expectancy and for the window's net
  (1,000 resamples of 20-trade blocks, fixed seed — a block, not a trade, because trades inside a
  window are not independent, which the serial-dependence reading below states rather than assumes);
* **three equal consecutive time blocks**, so a window's net is never a single number;
* **per-asset** and **per-market-context** breakdowns with expectancy;
* **leave-out-largest**, the R1 arm: how much of the net the single best trade carried;
* **serial dependence**: lag-1 autocorrelation of the per-trade return with its own ±2/√n band, and
  a runs test on the sign sequence;
* **frequency**: trades per day across the universe and per asset, and the mean holding time — the
  mission's own number, reported for every book and decisive for the two tracks in the way the
  registration says.

Nothing here decides a verdict by itself: the criteria in ``validation`` read these values.
"""

from __future__ import annotations

import random
import statistics
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "BOOTSTRAP_BLOCK",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "day_count",
    "extras",
    "interval_widths",
    "leave_out_largest",
    "refusal_funnel_of",
    "stamp",
]

BOOTSTRAP_RESAMPLES = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 20_261_014


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_count(window: dict[str, int]) -> float:
    return max(1e-9, (window["end"] - window["start"]) / 86_400_000.0)


def refusal_funnel_of(refusals: list[dict[str, Any]]) -> dict[str, int]:
    funnel: dict[str, int] = {}
    for refusal in refusals:
        reason = str(refusal.get("reason") or "UNKNOWN")
        funnel[reason] = funnel.get(reason, 0) + 1
    return dict(sorted(funnel.items(), key=lambda item: (-item[1], item[0])))


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return round(values[index], 4)


def leave_out_largest(*, trades: list[dict[str, Any]], start_equity: float) -> dict[str, Any]:
    """The R1 arm: the window's net with its single best trade removed."""
    if not trades:
        return {"trades": 0, "net_usdt": 0.0, "expectancy_usdt": None}
    best = max(trades, key=lambda trade: float(trade.get("net") or 0.0))
    kept = [trade for trade in trades if trade is not best]
    values = [float(trade["net"]) for trade in kept]
    return {
        "trades": len(kept),
        "net_usdt": round(sum(values), 4),
        "expectancy_usdt": round(sum(values) / len(values), 4) if values else None,
        "return_pct_of_start_equity": round(sum(values) / start_equity * 100.0, 4),
        "removed_trade_net_usdt": round(sum(float(t["net"]) for t in trades) - sum(values), 4),
    }


def extras(
    *,
    trades: list[dict[str, Any]],
    window: dict[str, int],
    n_assets: int,
    timeframe: str,
) -> dict[str, Any]:
    """Every added reading, computed from the rows the simulator wrote."""
    ordered = sorted(trades, key=lambda trade: trade["decision_ts"])
    nets = [float(trade["net"]) for trade in ordered]
    notionals = [float(trade["notional"]) for trade in ordered]
    bps = [
        net / size * 10_000.0 if size else 0.0 for net, size in zip(nets, notionals, strict=False)
    ]
    days = day_count(window)

    # 1. trade-block bootstrap of expectancy and of the window's net.
    rng = random.Random(BOOTSTRAP_SEED)
    expectancies: list[float] = []
    totals: list[float] = []
    if nets:
        blocks = [nets[i : i + BOOTSTRAP_BLOCK] for i in range(0, len(nets), BOOTSTRAP_BLOCK)]
        for _ in range(BOOTSTRAP_RESAMPLES):
            sample: list[float] = []
            while len(sample) < len(nets):
                sample.extend(blocks[rng.randrange(len(blocks))])
            sample = sample[: len(nets)]
            expectancies.append(sum(sample) / len(sample))
            totals.append(sum(sample))
    expectancies.sort()
    totals.sort()

    # 2. three equal consecutive thirds of the window, by decision instant.
    span = max(1, window["end"] - window["start"])
    thirds: list[dict[str, Any]] = []
    for index in range(3):
        low = window["start"] + span * index // 3
        high = window["start"] + span * (index + 1) // 3
        subset = [t for t in ordered if low <= int(t["decision_ts"]) < high]
        thirds.append(
            {
                "block": index + 1,
                "from_utc": stamp(low),
                "to_utc": stamp(high),
                "trades": len(subset),
                "net_usdt": round(sum(float(t["net"]) for t in subset), 4),
            }
        )

    # 3. per asset and per market context.
    def breakdown(key: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for label in sorted({str(t.get(key) or "UNDEFINED") for t in ordered}):
            subset = [t for t in ordered if str(t.get(key) or "UNDEFINED") == label]
            values = [float(t["net"]) for t in subset]
            out[label] = {
                "trades": len(subset),
                "net_usdt": round(sum(values), 4),
                "expectancy_usdt": round(sum(values) / len(values), 4) if values else None,
            }
        return out

    # 4. serial dependence: lag-1 autocorrelation with its own band, and a runs test.
    dependence: dict[str, Any] = {"observations": len(bps), "statistic": "per-trade return in bps"}
    if len(bps) > 2:
        mean = sum(bps) / len(bps)
        var = sum((value - mean) ** 2 for value in bps)
        band = round(2 / len(bps) ** 0.5, 4)
        dependence["lag1_autocorrelation"] = (
            round(sum((bps[i] - mean) * (bps[i - 1] - mean) for i in range(1, len(bps))) / var, 4)
            if var > 0
            else None
        )
        dependence["band_2_over_sqrt_n"] = band
    runs = 0
    for index, value in enumerate(nets):
        if index == 0 or (value > 0) != (nets[index - 1] > 0):
            runs += 1
    positives = sum(1 for value in nets if value > 0)
    negatives = len(nets) - positives
    expected_runs = (
        2 * positives * negatives / len(nets) + 1 if nets and positives and negatives else None
    )
    sd_runs = None
    if nets and positives and negatives:
        sd_runs = (
            2
            * positives
            * negatives
            * (2 * positives * negatives - len(nets))
            / (len(nets) ** 2 * (len(nets) - 1))
        ) ** 0.5
    dependence["runs"] = runs
    dependence["expected_runs"] = round(expected_runs, 4) if expected_runs else None
    dependence["runs_z"] = (
        round((runs - expected_runs) / sd_runs, 4) if expected_runs and sd_runs else None
    )

    # 5. frequency: the mission's own number, on the same rows.
    durations = [float(t.get("duration_min") or 0.0) for t in ordered]
    frequency = {
        "trades": len(ordered),
        "window_days": round(days, 4),
        "assets": n_assets,
        "timeframe": timeframe,
        "trades_per_day_universe": round(len(ordered) / days, 4),
        "trades_per_day_per_asset": round(len(ordered) / days / max(1, n_assets), 4),
        "mean_hold_minutes": round(statistics.fmean(durations), 2) if durations else None,
        "mean_hold_hours": round(statistics.fmean(durations) / 60.0, 4) if durations else None,
    }

    return {
        "expectancy_ci_90_usdt": {
            "low": _quantile(expectancies, 0.05),
            "high": _quantile(expectancies, 0.95),
            "point": round(sum(nets) / len(nets), 4) if nets else None,
        },
        "net_ci_90_usdt": {
            "low": _quantile(totals, 0.05),
            "high": _quantile(totals, 0.95),
            "point": round(sum(nets), 4) if nets else None,
        },
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "block_trades": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
            "statistic": "expectancy and net, blocks of 20 trades because trades in a window are not independent",
        },
        "time_blocks": thirds,
        "positive_time_blocks": sum(1 for block in thirds if float(block["net_usdt"]) > 0),
        "by_asset_detail": breakdown("asset"),
        "by_regime_detail": breakdown("regime"),
        "by_market_context_detail": breakdown("market_context"),
        "serial_dependence": dependence,
        "frequency": frequency,
        "mean_bps_per_trade": round(statistics.fmean(bps), 4) if bps else None,
        "mean_notional_usdt": round(statistics.fmean(notionals), 4) if notionals else None,
    }


def interval_widths(*, trades: list[dict[str, Any]], days: float) -> dict[str, Any]:
    """The real time actually spanned by the trades (a window can be longer than its sample)."""
    if not trades:
        return {"first_utc": None, "last_utc": None, "span_days": None, "trades_per_day": None}
    stamps = sorted(int(t["decision_ts"]) for t in trades)
    span_days = max(1e-9, (stamps[-1] - stamps[0]) / 86_400_000.0)
    return {
        "first_utc": stamp(stamps[0]),
        "last_utc": stamp(stamps[-1]),
        "span_days": round(span_days, 4),
        "trades_per_day": round(len(trades) / span_days, 4),
        "window_days": round(days, 4),
    }
