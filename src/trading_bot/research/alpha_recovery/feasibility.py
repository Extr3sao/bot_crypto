"""ARP-003 cost-feasibility screen (research-only, deterministic, pure).

Purpose (§7/§8/§9 of ARP-003): estimate, from historical observations only, the
*economic scale* a mechanism would have to capture at a given holding horizon,
and compare it with the authoritative runtime round-trip cost.

This is a **feasibility diagnostic, not evidence of edge**:

* it makes no entry decision and produces no trade, so it cannot promote
  anything;
* it is a pure function of already-closed bars (``data_time <= decision_time``);
* it never reads a locked OOS window — the caller passes only DEV/VALIDATION
  bars;
* no randomness, no wall-clock, no LLM arithmetic.

Vocabulary produced here (ARP-003 §7/§8):

``GROSS_OPPORTUNITY_BPS``
    the typical *available* price move over a holding horizon, in basis points,
    measured as the distribution of ``|close[i+h] / close[i] - 1|``.
``CURRENT_COST_BPS``
    the authoritative ``COST_MODEL_V3`` round-trip figure (never hardcoded).
``OPPORTUNITY_TO_COST_RATIO``
    ``GROSS_OPPORTUNITY_BPS / CURRENT_COST_BPS`` — how much room a *perfect*
    capture of the typical move would leave over cost. A mechanism captures only
    a fraction of the available move, so a ratio near 1 is already hopeless.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "BARS_PER_DAY_5M",
    "HORIZONS_5M",
    "abs_move_bps",
    "frontier_row",
    "horizon_frontier",
    "signed_move_bps",
]

BPS = 10_000.0

#: 5-minute base bars per UTC day (24 * 60 / 5).
BARS_PER_DAY_5M = 288

#: Frozen horizon ladder expressed in 5-minute base bars. Chosen to span an
#: intraday scalp through a weekly swing: 30m, 1h, 2h, 4h, 8h, 1d, 2d, 4d, 7d.
HORIZONS_5M: dict[str, int] = {
    "30m": 6,
    "1h": 12,
    "2h": 24,
    "4h": 48,
    "8h": 96,
    "1d": 288,
    "2d": 576,
    "4d": 1152,
    "7d": 2016,
}


def abs_move_bps(closes: Sequence[float], horizon: int) -> list[float]:
    """Overlapping ``|forward return|`` in bps for every bar that has a horizon-end.

    Overlapping windows are used **only** to describe the magnitude of the move
    that exists over a horizon; they are not treated as independent samples and
    no significance claim is made from them.
    """
    if horizon <= 0:
        raise ValueError("horizon must be > 0")
    out: list[float] = []
    limit = len(closes) - horizon
    for i in range(limit):
        base = closes[i]
        if base <= 0:
            continue
        out.append(abs(closes[i + horizon] / base - 1.0) * BPS)
    return out


def signed_move_bps(closes: Sequence[float], horizon: int, *, non_overlapping: bool = True) -> list[float]:
    """Forward returns in bps.

    ``non_overlapping=True`` (default) takes independent samples every
    ``horizon`` bars — the honest basis for a drift / standard-error estimate.
    ``non_overlapping=False`` returns every overlapping window (magnitude only).
    """
    if horizon <= 0:
        raise ValueError("horizon must be > 0")
    out: list[float] = []
    step = horizon if non_overlapping else 1
    for i in range(0, len(closes) - horizon, step):
        base = closes[i]
        if base <= 0:
            continue
        out.append((closes[i + horizon] / base - 1.0) * BPS)
    return out


def _percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation surprises)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def frontier_row(closes: Sequence[float], horizon_bars: int, cost_bps_rt: float) -> dict[str, Any]:
    """One row of the cost-compatibility frontier for a single series."""
    abs_moves = abs_move_bps(closes, horizon_bars)
    signed = signed_move_bps(closes, horizon_bars, non_overlapping=True)
    n_abs = len(abs_moves)
    if n_abs == 0 or not signed:
        return {
            "horizon_bars": horizon_bars,
            "n_abs": n_abs,
            "n_signed": len(signed),
            "gross_opportunity_bps": None,
            "median_abs_bps": None,
            "p90_abs_bps": None,
            "frac_abs_ge_cost": None,
            "drift_bps": None,
            "drift_stderr_bps": None,
            "opportunity_to_cost_ratio": None,
        }
    mean_abs = statistics.fmean(abs_moves)
    drift = statistics.fmean(signed)
    stderr = (statistics.pstdev(signed) / math.sqrt(len(signed))) if len(signed) > 1 else 0.0
    frac_ge = sum(1 for m in abs_moves if m >= cost_bps_rt) / n_abs
    return {
        "horizon_bars": horizon_bars,
        "n_abs": n_abs,
        "n_signed": len(signed),
        "gross_opportunity_bps": round(mean_abs, 4),
        "median_abs_bps": round(statistics.median(abs_moves), 4),
        "p90_abs_bps": round(_percentile(abs_moves, 0.90), 4),
        "frac_abs_ge_cost": round(frac_ge, 6),
        "drift_bps": round(drift, 4),
        "drift_stderr_bps": round(stderr, 4),
        "opportunity_to_cost_ratio": round(mean_abs / cost_bps_rt, 4) if cost_bps_rt > 0 else None,
    }


def horizon_frontier(
    series_by_key: Mapping[str, Sequence[float]],
    *,
    horizons: dict[str, int] | None = None,
    cost_bps_rt: float,
) -> dict[str, Any]:
    """Aggregate the frontier across every (key, window) series.

    ``series_by_key`` maps a label (``BTCUSDT_W1_2026-03``) to that window's
    closes. Returns a per-horizon aggregate plus a per-asset breakdown so the
    aggregate cannot hide an asset-specific artefact.
    """
    horizons = horizons or HORIZONS_5M
    per_horizon: dict[str, Any] = {}
    for label, bars in horizons.items():
        pooled_abs: list[float] = []
        pooled_signed: list[float] = []
        per_asset: dict[str, Any] = {}
        for key, closes in sorted(series_by_key.items()):
            row = frontier_row(closes, bars, cost_bps_rt)
            asset = key.split("_")[0]
            bucket = per_asset.setdefault(asset, {"abs": [], "signed": []})
            bucket["abs"].extend(abs_move_bps(closes, bars))
            bucket["signed"].extend(signed_move_bps(closes, bars, non_overlapping=True))
            if row["gross_opportunity_bps"] is not None:
                pooled_abs.extend(abs_move_bps(closes, bars))
                pooled_signed.extend(signed_move_bps(closes, bars, non_overlapping=True))
        row_out: dict[str, Any] = {
            "horizon_bars": bars,
            "horizon_wallclock": label,
            "n_abs": len(pooled_abs),
            "n_signed": len(pooled_signed),
            "gross_opportunity_bps": round(statistics.fmean(pooled_abs), 4) if pooled_abs else None,
            "median_abs_bps": round(statistics.median(pooled_abs), 4) if pooled_abs else None,
            "p90_abs_bps": round(_percentile(pooled_abs, 0.90), 4) if pooled_abs else None,
            "frac_abs_ge_cost": round(sum(1 for m in pooled_abs if m >= cost_bps_rt) / len(pooled_abs), 6)
            if pooled_abs
            else None,
            "drift_bps": round(statistics.fmean(pooled_signed), 4) if pooled_signed else None,
            "drift_stderr_bps": round(statistics.pstdev(pooled_signed) / math.sqrt(len(pooled_signed)), 4)
            if len(pooled_signed) > 1
            else None,
            "opportunity_to_cost_ratio": round(statistics.fmean(pooled_abs) / cost_bps_rt, 4)
            if pooled_abs and cost_bps_rt > 0
            else None,
            "by_asset": {
                asset: {
                    "gross_opportunity_bps": round(statistics.fmean(b["abs"]), 4) if b["abs"] else None,
                    "opportunity_to_cost_ratio": round(statistics.fmean(b["abs"]) / cost_bps_rt, 4)
                    if b["abs"] and cost_bps_rt > 0
                    else None,
                }
                for asset, b in sorted(per_asset.items())
            },
        }
        per_horizon[label] = row_out
    return {"cost_bps_rt": round(cost_bps_rt, 4), "per_horizon": per_horizon}
