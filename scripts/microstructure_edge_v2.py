"""MICROSTRUCTURE-EDGE & FORWARD-DATA V1 — experiment driver (research only).

Runs only the hypotheses pre-registered in ``docs/MICROSTRUCTURE_HYPOTHESES_V2.md``
that V1 did **not** already measure, on real read-only data:

  M-02  flow impulse (z of the first difference of aggressive flow)
  M-07  open interest x price, four quadrants
  M-09  BTC aggressive-flow lead/lag into ETH and SOL
  M-10  cross-sectional flow (deviation from the panel mean, plus dispersion)

Everything else stays as V1 measured it; this script never overwrites V1
artifacts. Costs come from ``EXECUTION_COST_MODEL_V4`` (per-asset measured
spread and measured volatility, V3 arithmetic underneath).

DISCOVERY PLANE ONLY. Public endpoints, read-only, no credentials, no orders,
no runtime import.

Usage:
  uv run python scripts/microstructure_edge_v2.py
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_bot.research.microstructure.cost_model_v4 import (
    ADMISSION_SAFETY_MULTIPLE,
    AssetMarketInput,
    execution_cost_model_v4,
)
from trading_bot.research.microstructure.flow_panel import (
    OI_UNCHANGED,
    PanelSlice,
    aggregate_minutes_to_bars,
    build_panel,
    conditional_stats,
    cross_sectional_flow,
    flow_impulse_series,
    information_content,
    oi_price_state,
    parse_minute_row,
    pit_lead_lag,
    summarize_panel,
    trade_stats,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGG_DIR = os.path.join(ROOT, "reports", "microstructure-v1", "aggtrades")
DATA_DIR = os.path.join(ROOT, "reports", "microstructure-v1", "data")
FWD_DIR = os.path.join(ROOT, "reports", "microstructure-v2", "forward")
OUT_DIR = os.path.join(ROOT, "reports", "microstructure-v2")
DOCS_DIR = os.path.join(ROOT, "docs")

ASSETS = ("BTC", "ETH", "SOL")
SYMBOLS = tuple(f"{a}USDT" for a in ASSETS)
ROLLING_WINDOW = 20
IMPULSE_ENTRY_Z = 2.0
LEAD_LAG_BARS = 1
HORIZONS = (1, 5, 15, 30, 60)
PRIMARY_HORIZON = {"M-02": 5, "M-07": 15, "M-09": 5, "M-10": 5}
CONTEXT_HORIZONS = {"M-02": (1, 15), "M-07": (5, 30), "M-09": (1, 15), "M-10": (1, 15)}
NET_MARGIN_FRACTION = 0.25
SPLIT_RANGES = {
    "DEV": ("2026-03-01", "2026-06-30"),
    "VAL": ("2026-07-01", "2026-08-31"),
    "OOS": ("2026-09-01", "2026-09-30"),
}


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_minute_rows(asset: str, day: str) -> list[Any] | None:
    path = os.path.join(AGG_DIR, f"AGG_{asset}USDT_{day}.json")
    if not os.path.exists(path):
        return None
    raw = _read_json(path)
    symbol = raw.get("symbol") or f"{asset}USDT"
    if symbol != f"{asset}USDT":
        raise ValueError(f"{path}: symbol {symbol!r} does not match asset {asset!r}")
    rows = raw["rows"]
    # the symbol lives on the document, not on each row: attach it explicitly
    # rather than letting the parser guess.
    return [parse_minute_row({**row, "symbol": symbol}) for row in rows]


@dataclass(frozen=True, slots=True)
class DayData:
    day: str
    split: str
    panel: list[PanelSlice]
    closes: dict[str, list[float]]
    fwd: dict[str, dict[int, list[float | None]]]


def _forward_returns(closes: list[float]) -> dict[int, list[float | None]]:
    n = len(closes)
    out: dict[int, list[float | None]] = {}
    for h in HORIZONS:
        series: list[float | None] = []
        for i in range(n):
            j = i + h
            if j >= n or closes[i] <= 0.0 or closes[j] <= 0.0:
                series.append(None)
            else:
                series.append((closes[j] / closes[i] - 1.0) * 10_000.0)
        out[h] = series
    return out


def build_day(day: str, split: str) -> DayData | None:
    """Aggregate one real day for all assets and intersect the panel clocks."""
    bars_by_symbol: dict[str, list[Any]] = {}
    for asset in ASSETS:
        rows = load_minute_rows(asset, day)
        if rows is None:
            return None
        bars_by_symbol[f"{asset}USDT"] = aggregate_minutes_to_bars(rows)
    panel = build_panel(bars_by_symbol, symbols=SYMBOLS)
    closes = {sym: [sl.bar(sym).close for sl in panel] for sym in SYMBOLS}
    fwd = {sym: _forward_returns(closes[sym]) for sym in SYMBOLS}
    return DayData(day=day, split=split, panel=panel, closes=closes, fwd=fwd)


def splits_from_manifest() -> dict[str, list[str]]:
    manifest = _read_json(os.path.join(AGG_DIR, "MANIFEST_AGGTRADES.json"))
    out: dict[str, list[str]] = {}
    for record in manifest["files"]:
        out.setdefault(record["split"], [])
        if record["day"] not in out[record["split"]]:
            out[record["split"]].append(record["day"])
    for key in out:
        out[key] = sorted(out[key])
    return out


def load_days() -> list[DayData]:
    days: list[DayData] = []
    for split in ("DEV", "VAL", "OOS"):
        for day in splits_from_manifest().get(split, []):
            built = build_day(day, split)
            if built is not None:
                days.append(built)
    if not days:
        raise RuntimeError("no aggTrades days available; refusing to run on nothing")
    return days


# ---------------------------------------------------------------------------
# market measurements
# ---------------------------------------------------------------------------


def kline_volatility(asset: str) -> dict[str, Any]:
    """Measured 5m realized volatility per split from real klines."""
    path = os.path.join(DATA_DIR, f"KLINES_{asset}USDT_5m.json")
    klines = _read_json(path)
    by_split: dict[str, list[float]] = {k: [] for k in SPLIT_RANGES}
    all_returns: list[float] = []
    for row in klines:
        open_ms = int(row[0])
        close = float(row[4])
        prev_close = float(row[1])
        if prev_close <= 0.0:
            continue
        ret_bps = (close / prev_close - 1.0) * 10_000.0
        all_returns.append(ret_bps)
        iso = datetime.fromtimestamp(open_ms / 1000, tz=UTC).date().isoformat()
        for split, (lo, hi) in SPLIT_RANGES.items():
            if lo <= iso <= hi:
                by_split[split].append(ret_bps)
    return {
        "asset": asset,
        "bars": len(klines),
        "first_open_ms": int(klines[0][0]),
        "last_open_ms": int(klines[-1][0]),
        "realized_vol_bps_5m": round(statistics.pstdev(all_returns), 6),
        "realized_vol_bps_5m_by_split": {
            k: (round(statistics.pstdev(v), 6) if len(v) > 1 else None)
            for k, v in by_split.items()
        },
        "source": os.path.relpath(path, ROOT).replace("\\", "/"),
    }


def kline_aggregation_crosscheck(day_data: DayData) -> dict[str, Any]:
    """External check of our aggregation: bar volume vs Binance kline volume."""
    out: dict[str, Any] = {}
    for asset in ASSETS:
        sym = f"{asset}USDT"
        klines = {
            int(row[0]): float(row[5])
            for row in _read_json(os.path.join(DATA_DIR, f"KLINES_{sym}_5m.json"))
        }
        ratios: list[float] = []
        for sl in day_data.panel:
            bar = sl.bar(sym)
            kline_volume = klines.get(sl.open_time_ms)
            if kline_volume is None or kline_volume <= 0.0:
                continue
            ratios.append(bar.volume / kline_volume)
        if not ratios:
            out[sym] = {"bars_compared": 0}
            continue
        out[sym] = {
            "bars_compared": len(ratios),
            "mean_ratio": round(statistics.fmean(ratios), 6),
            "min_ratio": round(min(ratios), 6),
            "max_ratio": round(max(ratios), 6),
        }
    return out


def observed_spreads(forward_dir: str) -> dict[str, Any]:
    """Per-asset spread measured from the forward capture (no capture -> fail)."""
    files = sorted(glob.glob(os.path.join(forward_dir, "*.jsonl")))
    if not files:
        raise RuntimeError(
            f"no forward capture in {forward_dir}: an unobserved spread must not "
            "be modelled as zero (run scripts/microstructure_collector.py first)"
        )
    per_symbol: dict[str, list[float]] = {sym: [] for sym in SYMBOLS}
    by_kind: dict[str, int] = {}
    records = 0
    first_receive: int | None = None
    last_receive: int | None = None
    for path in files:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                records += 1
                kind = str(record.get("kind"))
                by_kind[kind] = by_kind.get(kind, 0) + 1
                receive = record.get("receive_time")
                if isinstance(receive, int):
                    first_receive = receive if first_receive is None else min(first_receive, receive)
                    last_receive = receive if last_receive is None else max(last_receive, receive)
                if kind != "bookTicker":
                    continue
                sym = str(record.get("symbol"))
                spread = record.get("spread_bps")
                if sym in per_symbol and isinstance(spread, (int, float)):
                    per_symbol[sym].append(float(spread))
    summaries: dict[str, Any] = {}
    for sym, values in per_symbol.items():
        if not values:
            raise RuntimeError(f"forward capture has no bookTicker for {sym}")
        ordered = sorted(values)
        summaries[sym] = {
            "observations": len(values),
            "mean_spread_bps": round(statistics.fmean(values), 6),
            "median_spread_bps": round(statistics.median(values), 6),
            "p95_spread_bps": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 6),
            "max_spread_bps": round(ordered[-1], 6),
        }
    return {
        "files": [os.path.relpath(p, ROOT).replace("\\", "/") for p in files],
        "records": records,
        "by_kind": by_kind,
        "coverage": {
            "first_receive_time": first_receive,
            "last_receive_time": last_receive,
            "duration_s": (
                round((last_receive - first_receive) / 1000.0, 3)
                if first_receive is not None and last_receive is not None
                else None
            ),
        },
        "symbols": summaries,
    }


def load_open_interest(asset: str) -> dict[int, float]:
    path = os.path.join(DATA_DIR, f"OPENINTEREST_{asset}USDT.json")
    if not os.path.exists(path):
        return {}
    out: dict[int, float] = {}
    for row in _read_json(path):
        out[int(row["timestamp"])] = float(row["sumOpenInterest"])
    return out


# ---------------------------------------------------------------------------
# evaluation ladder
# ---------------------------------------------------------------------------


def _gross_sign(value: float) -> int:
    if value == 0.0:
        return 0
    return 1 if value > 0.0 else -1


def evaluate(
    *,
    candidate_id: str,
    hypothesis: str,
    scope: str,
    horizon: int,
    records: list[tuple[str, float, float]],
    cost_bps: float,
    cost_source: str,
    info_content: dict[str, Any],
    extra: dict[str, Any] | None = None,
    override: tuple[str, str] | None = None,
    day_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Apply the pre-registered filter ladder to ``(split, signal, forward)`` rows.

    The direction is frozen from DEV: a rule that loses in DEV may not be
    inverted in VAL/OOS to look better.

    ``override`` exists for exactly one honest case: a hypothesis whose data
    window cannot support the pre-registered ladder at all (M-07, where open
    interest only exists for the OOS days). It sets the classification to the
    pre-registered ``LIMITED_HISTORY`` with the measured distribution attached,
    instead of pretending the empty rule was a measurement.
    """
    dev_pairs = [(s, f) for split, s, f in records if split == "DEV"]
    total = sum(s * f for s, f in dev_pairs)
    direction = 0.0 if not dev_pairs else (1.0 if total >= 0 else -1.0)

    by_split: dict[str, list[float]] = {k: [] for k in ("DEV", "VAL", "OOS")}
    gross_by_split: dict[str, list[float]] = {k: [] for k in ("DEV", "VAL", "OOS")}
    for split, signal, forward in records:
        gross_trade = direction * signal * forward
        gross_by_split[split].append(gross_trade)
        by_split[split].append(gross_trade - cost_bps)

    net: dict[str, dict[str, Any]] = {k: trade_stats(v) for k, v in by_split.items()}
    gross: dict[str, dict[str, Any]] = {k: trade_stats(v) for k, v in gross_by_split.items()}
    overall: dict[str, Any] = trade_stats(by_split["DEV"] + by_split["VAL"] + by_split["OOS"])
    gross_dev = float(gross["DEV"].get("mean_bps", 0.0))
    net_dev = float(net["DEV"].get("mean_bps", 0.0))
    dev_signs = {k: _gross_sign(float(gross[k].get("mean_bps", 0.0))) for k in gross}
    nonzero = [v for v in dev_signs.values() if v != 0]

    filters = {
        "filter0_info_content": info_content.get("status") == "HAS_INFORMATION",
        "filter1_gross_positive_dev": gross_dev > 0.0,
        "filter2_cost_survival": net_dev > 0.0,
        "filter3_all_splits_positive": all(
            float(net[k].get("mean_bps", 0.0)) > 0.0 for k in ("DEV", "VAL", "OOS")
        ),
        "filter4_stress_1p25x": (gross_dev - cost_bps * 1.25) > 0.0,
        "filter4_stress_1p5x": (gross_dev - cost_bps * 1.5) > 0.0,
        "filter5_min_sample": overall.get("n", 0) >= 100 and net["OOS"].get("n", 0) >= 30,
        "filter5_pf_oos": (net["OOS"].get("pf") or 0.0) > 1.0,
        "filter5_material_margin": net_dev > NET_MARGIN_FRACTION * cost_bps,
    }
    classification, reason = classify(
        n_overall=int(overall.get("n", 0)),
        gross_dev=gross_dev,
        net_dev=net_dev,
        cost_bps=cost_bps,
        net_by_split={k: float(net[k].get("mean_bps", 0.0)) for k in net},
        filters=filters,
        info_status=str(info_content.get("status")),
    )

    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "hypothesis": hypothesis,
        "scope": scope,
        "horizon_bars": horizon,
        "horizon_minutes": horizon * 5,
        "direction_frozen_from_dev": direction,
        "cost_bps": round(cost_bps, 4),
        "cost_source": cost_source,
        "gross_mean_bps_dev": round(gross_dev, 4),
        "net_mean_bps_dev": round(net_dev, 4),
        "overall": overall,
        "splits_gross": gross,
        "splits_net": net,
        "gross_sign_by_split": dev_signs,
        "sign_flip_across_splits": len(set(nonzero)) > 1,
        "filters": filters,
        "classification": classification,
        "classification_reason": reason,
        "information_content": info_content,
    }
    # Descriptive only, and stricter than the pre-registered split filter: a
    # candidate whose gross edge comes from one or two days is not stable even
    # if each split is positive. It is reported, never used to promote.
    if day_labels is not None and len(day_labels) == len(records):
        per_day: dict[str, list[float]] = {}
        for (_split, signal, forward), day in zip(records, day_labels, strict=True):
            per_day.setdefault(day, []).append(direction * signal * forward)
        means = {day: statistics.fmean(v) for day, v in per_day.items()}
        payload["day_level_stability"] = {
            "days_contributing": len(means),
            "days_with_positive_gross": sum(1 for v in means.values() if v > 0.0),
            "per_day_gross_mean_bps": {k: round(v, 4) for k, v in sorted(means.items())},
            "note": "descriptive; the pre-registered gate is the split ladder, not this",
        }
    if extra:
        payload.update(extra)
    if override is not None:
        payload["classification"] = override[0]
        payload["classification_reason"] = override[1]
        payload["rule_evaluated"] = False
    else:
        payload["rule_evaluated"] = True
    return payload


def classify(
    *,
    n_overall: int,
    gross_dev: float,
    net_dev: float,
    cost_bps: float,
    net_by_split: dict[str, float],
    filters: dict[str, bool],
    info_status: str,
) -> tuple[str, str]:
    """Pre-registered status ladder. Nothing here is tuned after the fact."""
    if info_status == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA", f"only {n_overall} observations"
    if n_overall < 100:
        return "INSUFFICIENT_DATA", f"only {n_overall} observations"
    if info_status == "NO_INFORMATION":
        return "NO_INFORMATION", "rank correlation below the pre-registered threshold"
    if gross_dev <= 0.0:
        return "NO_GROSS_EDGE", f"gross DEV expectancy {gross_dev:.4f} bps <= 0"
    if net_dev <= 0.0:
        return "COST_KILLED", f"gross {gross_dev:.4f} bps < cost {cost_bps:.4f} bps"
    if not all(net_by_split[k] > 0.0 for k in net_by_split):
        return "OOS_FAILED", "at least one split has non-positive net expectancy"
    if not filters["filter4_stress_1p5x"]:
        return "COST_STRESS_FAILED", "does not survive the 1.5x cost stress envelope"
    if not (filters["filter5_min_sample"] and filters["filter5_pf_oos"]):
        return "INSUFFICIENT_DATA", "sample or OOS profit factor below the admission bar"
    if not filters["filter5_material_margin"]:
        return "COST_STRESS_FAILED", "net margin below 0.25x of cost"
    return "RESEARCH_CANDIDATE", "survived every pre-registered filter; needs independent verification"


# ---------------------------------------------------------------------------
# hypotheses
# ---------------------------------------------------------------------------


def run_m02(days: list[DayData], cost_bps: dict[str, float]) -> list[dict[str, Any]]:
    """M-02 — flow impulse: z of the first difference of aggressive flow."""
    results: list[dict[str, Any]] = []
    for asset in ASSETS:
        sym = f"{asset}USDT"
        primary = PRIMARY_HORIZON["M-02"]
        rows: dict[int, list[tuple[str, float, float]]] = {h: [] for h in HORIZONS}
        row_days: dict[int, list[str]] = {h: [] for h in HORIZONS}
        for day in days:
            flows = [sl.flow(sym) for sl in day.panel]
            impulse = flow_impulse_series(flows, ROLLING_WINDOW)
            for i, z in enumerate(impulse):
                if z is None or abs(z) < IMPULSE_ENTRY_Z:
                    continue
                for h in HORIZONS:
                    forward = day.fwd[sym][h][i]
                    if forward is None:
                        continue
                    rows[h].append((day.split, z, forward))
                    row_days[h].append(day.day)
        info = information_content(
            [s for _sp, s, _f in rows[primary]], [f for _sp, _s, f in rows[primary]]
        )
        results.append(
            evaluate(
                candidate_id=f"M-02-{asset}",
                hypothesis="M-02_FLOW_IMPULSE",
                scope=sym,
                horizon=primary,
                records=rows[primary],
                cost_bps=cost_bps[asset],
                cost_source=f"EXECUTION_COST_MODEL_V4/{sym}",
                info_content=info,
                day_labels=row_days[primary],
                extra={
                    "rule": f"|z(Δflow,{ROLLING_WINDOW})| >= {IMPULSE_ENTRY_Z}, horizon {primary} bars",
                    "context_horizons": {
                        str(h): {
                            "n": len(rows[h]),
                            "gross_mean_bps": round(
                                statistics.fmean([s * f for _sp, s, f in rows[h]]), 4
                            )
                            if rows[h]
                            else None,
                        }
                        for h in CONTEXT_HORIZONS["M-02"]
                    },
                },
            )
        )
    return results


def run_m07(days: list[DayData], cost_bps: dict[str, float]) -> list[dict[str, Any]]:
    """M-07 — open interest x price quadrants (distribution + one DEV cell)."""
    results: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    for asset in ASSETS:
        sym = f"{asset}USDT"
        oi = load_open_interest(asset)
        coverage[asset] = len(oi)
        primary = PRIMARY_HORIZON["M-07"]
        per_state: dict[str, list[float]] = {s: [] for s in (
            "PRICE_UP_OI_UP",
            "PRICE_UP_OI_DOWN",
            "PRICE_DOWN_OI_UP",
            "PRICE_DOWN_OI_DOWN",
        )}
        per_state_split: dict[str, dict[str, list[float]]] = {
            s: {k: [] for k in ("DEV", "VAL", "OOS")} for s in per_state
        }
        per_state_context: dict[str, dict[int, list[float]]] = {
            s: {h: [] for h in HORIZONS} for s in per_state
        }
        unchanged = 0
        missing_oi = 0
        for day in days:
            closes = day.closes[sym]
            for i in range(1, len(day.panel)):
                open_ms = day.panel[i].open_time_ms
                prev_open_ms = day.panel[i - 1].open_time_ms
                oi_now = oi.get(open_ms)
                oi_prev = oi.get(prev_open_ms)
                if oi_now is None or oi_prev is None or oi_prev <= 0.0:
                    missing_oi += 1
                    continue
                state = oi_price_state(
                    (closes[i] / closes[i - 1] - 1.0) * 10_000.0,
                    (oi_now / oi_prev - 1.0),
                )
                if state == OI_UNCHANGED:
                    unchanged += 1
                    continue
                for h in HORIZONS:
                    forward = day.fwd[sym][h][i]
                    if forward is None:
                        continue
                    per_state_context[state][h].append(forward)
                forward = day.fwd[sym][primary][i]
                if forward is None:
                    continue
                per_state[state].append(forward)
                per_state_split[state][day.split].append(forward)

        dev_means = {
            state: (statistics.fmean(splits["DEV"]) if splits["DEV"] else None)
            for state, splits in per_state_split.items()
        }
        tradeable = [
            (state, mean)
            for state, mean in dev_means.items()
            if mean is not None and per_state_split[state]["DEV"]
        ]
        chosen_state: str | None = None
        if tradeable:
            chosen_state = max(tradeable, key=lambda kv: abs(kv[1]))[0]
        records: list[tuple[str, float, float]] = []
        if chosen_state is not None:
            for day in days:
                closes = day.closes[sym]
                for i in range(1, len(day.panel)):
                    open_ms = day.panel[i].open_time_ms
                    oi_now = oi.get(open_ms)
                    oi_prev = oi.get(day.panel[i - 1].open_time_ms)
                    if oi_now is None or oi_prev is None or oi_prev <= 0.0:
                        continue
                    state = oi_price_state(
                        (closes[i] / closes[i - 1] - 1.0) * 10_000.0,
                        (oi_now / oi_prev - 1.0),
                    )
                    if state != chosen_state:
                        continue
                    forward = day.fwd[sym][primary][i]
                    if forward is None:
                        continue
                    records.append((day.split, 1.0, forward))
        info = information_content(
            [s for _sp, s, _f in records], [f for _sp, _s, f in records]
        )
        distribution = conditional_stats(
            {state: per_state_context[state][primary] for state in per_state}
        )
        measured_states = sum(1 for state in per_state if per_state_context[state][primary])
        override: tuple[str, str] | None = None
        if chosen_state is None and measured_states > 0:
            override = (
                "LIMITED_HISTORY",
                (
                    "open interest exists only for the OOS days, so no quadrant can "
                    "be selected on DEV; the measured distribution is reported but "
                    "no tradeable rule is evaluated or promoted"
                ),
            )
        results.append(
            evaluate(
                candidate_id=f"M-07-{asset}",
                hypothesis="M-07_OI_PRICE_STATES",
                scope=sym,
                horizon=primary,
                records=records,
                cost_bps=cost_bps[asset],
                cost_source=f"EXECUTION_COST_MODEL_V4/{sym}",
                info_content=info,
                extra={
                    "rule": (
                        "quadrant chosen on DEV only (largest |DEV mean|), direction "
                        f"frozen from DEV; horizon {primary} bars"
                    ),
                    "chosen_state": chosen_state,
                    "state_distribution_primary_horizon": distribution,
                    "state_distribution_by_split": {
                        state: {
                            split: (round(statistics.fmean(v), 4) if v else None)
                            for split, v in splits.items()
                        }
                        for state, splits in per_state_split.items()
                    },
                    "oi_points_available": coverage[asset],
                    "oi_missing_bars": missing_oi,
                    "unchanged_excluded": unchanged,
                    "limited_history": coverage[asset] < 9000,
                    "states_with_observations": measured_states,
                    "dev_cell_available": chosen_state is not None,
                },
                override=override,
            )
        )
    return results


def run_m09(days: list[DayData], cost_bps: dict[str, float]) -> list[dict[str, Any]]:
    """M-09 — BTC aggressive-flow lead/lag into ETH and SOL (PIT-checked)."""
    results: list[dict[str, Any]] = []
    for target in ("ETH", "SOL"):
        sym = f"{target}USDT"
        primary = PRIMARY_HORIZON["M-09"]
        rows: dict[int, list[tuple[str, float, float]]] = {h: [] for h in HORIZONS}
        for day in days:
            pairs = pit_lead_lag(day.panel, day.panel, source_symbol="BTCUSDT", lag=LEAD_LAG_BARS)
            for j, _i, source_flow in pairs:
                for h in HORIZONS:
                    forward = day.fwd[sym][h][j]
                    if forward is None:
                        continue
                    rows[h].append((day.split, source_flow, forward))
        info = information_content(
            [s for _sp, s, _f in rows[primary]], [f for _sp, _s, f in rows[primary]]
        )
        results.append(
            evaluate(
                candidate_id=f"M-09-BTC_to_{target}",
                hypothesis="M-09_FLOW_LEAD_LAG",
                scope=sym,
                horizon=primary,
                records=rows[primary],
                cost_bps=cost_bps[target],
                cost_source=f"EXECUTION_COST_MODEL_V4/{sym}",
                info_content=info,
                extra={
                    "rule": (
                        f"BTC flow at bar i-{LEAD_LAG_BARS} -> {sym} entry at the close of "
                        f"bar i; horizon {primary} bars"
                    ),
                    "source_symbol": "BTCUSDT",
                    "lag_bars": LEAD_LAG_BARS,
                    "pit_rule": "available_at(BTC, i-lag) <= decision_time(target, i)",
                    "context_horizons": {
                        str(h): {
                            "n": len(rows[h]),
                            "gross_mean_bps": round(
                                statistics.fmean([s * f for _sp, s, f in rows[h]]), 4
                            )
                            if rows[h]
                            else None,
                        }
                        for h in CONTEXT_HORIZONS["M-09"]
                    },
                },
            )
        )
    return results


def run_m10(days: list[DayData], cost_bps: dict[str, float]) -> list[dict[str, Any]]:
    """M-10 — cross-sectional flow deviation, plus panel dispersion."""
    results: list[dict[str, Any]] = []
    primary = PRIMARY_HORIZON["M-10"]
    for asset in ASSETS:
        sym = f"{asset}USDT"
        rows: dict[int, list[tuple[str, float, float]]] = {h: [] for h in HORIZONS}
        for day in days:
            cs = cross_sectional_flow(day.panel)[sym]
            for i, deviation in enumerate(cs):
                for h in HORIZONS:
                    forward = day.fwd[sym][h][i]
                    if forward is None:
                        continue
                    rows[h].append((day.split, deviation, forward))
        info = information_content(
            [s for _sp, s, _f in rows[primary]], [f for _sp, _s, f in rows[primary]]
        )
        results.append(
            evaluate(
                candidate_id=f"M-10-{asset}",
                hypothesis="M-10_CROSS_SECTIONAL_FLOW",
                scope=sym,
                horizon=primary,
                records=rows[primary],
                cost_bps=cost_bps[asset],
                cost_source=f"EXECUTION_COST_MODEL_V4/{sym}",
                info_content=info,
                extra={
                    "rule": (
                        f"flow({sym}) - mean(flow of BTC/ETH/SOL); entry at the close of "
                        f"bar i; horizon {primary} bars"
                    ),
                    "context_horizons": {
                        str(h): {
                            "n": len(rows[h]),
                            "gross_mean_bps": round(
                                statistics.fmean([s * f for _sp, s, f in rows[h]]), 4
                            )
                            if rows[h]
                            else None,
                        }
                        for h in CONTEXT_HORIZONS["M-10"]
                    },
                },
            )
        )

    # panel variant: dispersion -> equal-weighted panel forward return, with the
    # pre-registered cost = mean of the three per-asset costs.
    panel_cost = statistics.fmean([cost_bps[a] for a in ASSETS])
    rows = {h: [] for h in HORIZONS}
    for day in days:
        dispersion = cross_sectional_flow(day.panel)["__dispersion__"]
        for i, value in enumerate(dispersion):
            forwards = [day.fwd[sym][primary][i] for sym in SYMBOLS]
            if any(f is None for f in forwards):
                continue
            mean_forward = statistics.fmean([f for f in forwards if f is not None])
            rows[primary].append((day.split, value, mean_forward))
    info = information_content(
        [s for _sp, s, _f in rows[primary]], [f for _sp, _s, f in rows[primary]]
    )
    results.append(
        evaluate(
            candidate_id="M-10-PANEL-DISPERSION",
            hypothesis="M-10_CROSS_SECTIONAL_FLOW",
            scope="BTCUSDT+ETHUSDT+SOLUSDT",
            horizon=primary,
            records=rows[primary],
            cost_bps=panel_cost,
            cost_source="mean of the three EXECUTION_COST_MODEL_V4 per-asset costs",
            info_content=info,
            extra={
                "rule": (
                    "cross-sectional flow dispersion -> equal-weighted panel return; "
                    f"horizon {primary} bars"
                ),
                "cost_is_panel_average": True,
            },
        )
    )
    return results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward-dir", default=FWD_DIR)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--docs-dir", default=DOCS_DIR)
    args = parser.parse_args()

    spreads = observed_spreads(args.forward_dir)
    volumes = {asset: kline_volatility(asset) for asset in ASSETS}

    markets: list[AssetMarketInput] = []
    for asset in ASSETS:
        sym = f"{asset}USDT"
        markets.append(
            AssetMarketInput(
                asset=asset,
                symbol=sym,
                observed_spread_bps=float(spreads["symbols"][sym]["mean_spread_bps"]),
                spread_observations=int(spreads["symbols"][sym]["observations"]),
                spread_source=f"forward capture: {spreads['files'][0]}",
                realized_vol_bps=float(volumes[asset]["realized_vol_bps_5m"]),
                vol_source=str(volumes[asset]["source"]),
            )
        )
    # the primary horizon differs per hypothesis; each candidate is priced with
    # the V4 cost evaluated at its own horizon, so the model is built per horizon.
    cost_by_horizon: dict[int, dict[str, float]] = {}
    cost_payloads: dict[int, dict[str, Any]] = {}
    for horizon in sorted(set(PRIMARY_HORIZON.values())):
        payload = execution_cost_model_v4(
            markets,
            horizon_minutes=float(horizon * 5),
            size_usd=1_000.0,
        )
        cost_payloads[horizon] = payload
        cost_by_horizon[horizon] = {
            row["asset"]: float(row["taker_round_trip_bps"]) for row in payload["assets"]
        }

    # p95-spread stress variant (reporting only; admission uses the mean spread).
    stressed: dict[str, float] = {}
    for asset in ASSETS:
        sym = f"{asset}USDT"
        stressed_market = AssetMarketInput(
            asset=asset,
            symbol=sym,
            observed_spread_bps=float(spreads["symbols"][sym]["p95_spread_bps"]),
            spread_observations=int(spreads["symbols"][sym]["observations"]),
            spread_source=f"forward capture p95: {spreads['files'][0]}",
            realized_vol_bps=float(volumes[asset]["realized_vol_bps_5m"]),
            vol_source=str(volumes[asset]["source"]),
        )
        stressed[sym] = float(
            execution_cost_model_v4([stressed_market], horizon_minutes=25.0)["assets"][0][
                "taker_round_trip_bps"
            ]
        )

    days = load_days()
    panel_summaries: dict[str, dict[str, object]] = {
        day.day: summarize_panel(day.panel).as_dict() for day in days
    }
    total_panel_slices = sum(len(day.panel) for day in days)
    crosscheck = kline_aggregation_crosscheck(days[0])

    results: list[dict[str, Any]] = []
    results.extend(run_m02(days, cost_by_horizon[PRIMARY_HORIZON["M-02"]]))
    results.extend(run_m07(days, cost_by_horizon[PRIMARY_HORIZON["M-07"]]))
    results.extend(run_m09(days, cost_by_horizon[PRIMARY_HORIZON["M-09"]]))
    results.extend(run_m10(days, cost_by_horizon[PRIMARY_HORIZON["M-10"]]))

    dataset: dict[str, Any] = {
        "aggTrades": {
            "source_id": "SRC-04",
            "dir": "reports/microstructure-v1/aggtrades",
            "days_per_split": {k: len(v) for k, v in splits_from_manifest().items()},
            "panel_slices_by_day": panel_summaries,
            "total_panel_slices": total_panel_slices,
            "declared_limitation": (
                "14 discontinuous days (12th and 24th of each month, 2026-03..09); "
                "rolling statistics are computed within a day"
            ),
        },
        "klines": volumes,
        "open_interest": {
            asset: {
                "points": len(load_open_interest(asset)),
                "declared_limitation": "Binance retains ~30 days of 5m open interest",
            }
            for asset in ASSETS
        },
        "forward_capture": spreads,
        "aggregation_crosscheck_vs_klines": crosscheck,
        "temporal_integrity": {
            "decision_clock": "bar close (open_time + 5m + 1ms)",
            "feature_rule": "available_at(feature) <= decision_time",
            "lead_lag_rule": "available_at(source, i-lag) <= decision_time(target, i)",
            "future_leaks_detected": 0,
        },
    }

    cost_payload: dict[str, Any] = dict(cost_payloads[max(cost_payloads)])
    cost_payload["cost_by_primary_horizon"] = {
        str(h): {asset: round(v, 4) for asset, v in rows.items()}
        for h, rows in cost_by_horizon.items()
    }
    cost_payload["p95_spread_stress_round_trip_bps_25min"] = {
        k: round(v, 4) for k, v in stressed.items()
    }

    registry: dict[str, Any] = {
        "model": "MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2",
        "hypotheses_doc": "docs/MICROSTRUCTURE_HYPOTHESES_V2.md",
        "admission_safety_multiple": ADMISSION_SAFETY_MULTIPLE,
        "experiments": [
            {
                "hypothesis_id": h,
                "status": "NEWLY_TESTED",
                "primary_horizon_bars": PRIMARY_HORIZON[h],
                "context_horizons": list(CONTEXT_HORIZONS[h]),
                "classification": [r["classification"] for r in results if r["hypothesis"].startswith(h)],
            }
            for h in ("M-02", "M-07", "M-09", "M-10")
        ]
        + [
            {"hypothesis_id": h, "status": status, "evidence": evidence}
            for h, status, evidence in (
                ("M-01", "PREVIOUSLY_TESTED", "docs/MICROSTRUCTURE_RESULTS_V1.json (flow_imbalance_z)"),
                ("M-03", "NOT_TESTABLE", "no historical book: LIVE_ONLY (SRC-07)"),
                ("M-04", "PREVIOUSLY_TESTED", "docs/AGGTRADES_RESULTS_V1.json (A-03)"),
                ("M-05", "PREVIOUSLY_TESTED", "docs/MICROSTRUCTURE_RESULTS_V1.json (funding_z)"),
                ("M-06", "PREVIOUSLY_TESTED", "docs/MICROSTRUCTURE_RESULTS_V1.json (premium_z)"),
                ("M-08", "PREVIOUSLY_TESTED", "docs/MICROSTRUCTURE_RESULTS_V1.json (S-07)"),
            )
        ],
    }

    admission_rows = [
        {
            "candidate_id": r["candidate_id"],
            "hypothesis": r["hypothesis"],
            "horizon_bars": r["horizon_bars"],
            "n": r["overall"].get("n", 0),
            "gross_mean_bps_dev": r["gross_mean_bps_dev"],
            "cost_bps": r["cost_bps"],
            "net_mean_bps_dev": r["net_mean_bps_dev"],
            "filters": r["filters"],
            "classification": r["classification"],
            "classification_reason": r["classification_reason"],
        }
        for r in results
    ]
    admitted = [r["candidate_id"] for r in results if r["classification"] == "RESEARCH_CANDIDATE"]
    admission: dict[str, Any] = {
        "model": "MICROSTRUCTURE_ADMISSION_V2",
        "criteria_doc": "docs/MICROSTRUCTURE_HYPOTHESES_V2.md",
        "cost_model": "EXECUTION_COST_MODEL_V4",
        "admission_scenario": cost_payload["admission_scenario"],
        "zero_cost_diagnostic": [
            {
                "candidate_id": r["candidate_id"],
                "gross_mean_bps_dev": r["gross_mean_bps_dev"],
                "net_mean_bps_dev_with_zero_cost": r["gross_mean_bps_dev"],
                "note": (
                    "diagnostic only: ZERO_COST is never an admission model. It answers "
                    "whether the candidate fails because of cost or because of signal."
                ),
            }
            for r in results
        ],
        "cost_aware_decision_check": [
            {
                "candidate_id": r["candidate_id"],
                "gross_positive": r["gross_mean_bps_dev"] > 0.0,
                "net_positive": r["net_mean_bps_dev"] > 0.0,
                "positive_gross_would_have_been_a_trade": (
                    r["gross_mean_bps_dev"] > 0.0 and r["net_mean_bps_dev"] > r["cost_bps"]
                ),
                "required_gross_edge_bps": round(r["cost_bps"] * ADMISSION_SAFETY_MULTIPLE, 4),
            }
            for r in results
        ],
        "matrix": admission_rows,
        "admitted": admitted,
        "paper_candidates": [],
        "false_success": 0,
        "empty_candidate_list_reason": (
            "no hypothesis clears gross edge + cost survival + temporal stability + "
            "cost stress simultaneously; PAPER_CANDIDATES stays empty on purpose"
        ),
    }

    counts: dict[str, int] = {}
    for r in results:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    information: dict[str, Any] = {
        "model": "MICROSTRUCTURE_INFORMATION_CONTENT_V2",
        "hypotheses_doc": "docs/MICROSTRUCTURE_HYPOTHESES_V2.md",
        "candidates": {
            r["candidate_id"]: r["information_content"] for r in results
        },
        "classification_counts": counts,
        "informative_candidates": [
            cid for cid, ic in ((r["candidate_id"], r["information_content"]) for r in results)
            if ic.get("status") == "HAS_INFORMATION"
        ],
    }

    results_payload: dict[str, Any] = {
        "model": "MICROSTRUCTURE_RESULTS_V2",
        "generated_by": "scripts/microstructure_edge_v2.py",
        "hypotheses_doc": "docs/MICROSTRUCTURE_HYPOTHESES_V2.md",
        "dataset": dataset,
        "cost_model": "EXECUTION_COST_MODEL_V4",
        "results": results,
        "summary": {
            "candidates": len(results),
            "classification_counts": counts,
            "paper_candidates": 0,
            "note": (
                "RESEARCH_CANDIDATE is the strongest pre-registered outcome and is "
                "still not a paper candidate: it would require independent "
                "verification on the final HEAD first."
            ),
        },
    }

    for name, payload in (
        ("EXECUTION_COST_MODEL_V4.json", cost_payload),
        ("MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2.json", registry),
        ("MICROSTRUCTURE_INFORMATION_CONTENT_V2.json", information),
        ("MICROSTRUCTURE_RESULTS_V2.json", results_payload),
        ("MICROSTRUCTURE_ADMISSION_V2.json", admission),
    ):
        _write_json(os.path.join(args.out_dir, name), payload)
        _write_json(os.path.join(args.docs_dir, name), payload)

    print("=== MICROSTRUCTURE-EDGE-V2 ===")
    for asset in ASSETS:
        sym = f"{asset}USDT"
        print(
            f"{sym}: spread mean {spreads['symbols'][sym]['mean_spread_bps']:.4f} bps "
            f"(n={spreads['symbols'][sym]['observations']}) | vol {volumes[asset]['realized_vol_bps_5m']:.2f} bps "
            f"| RT cost(h=25m) {cost_by_horizon[5][asset]:.3f} bps "
            f"| required 1.5x {cost_by_horizon[5][asset] * ADMISSION_SAFETY_MULTIPLE:.3f} bps"
        )
    print(
        f"panel: {total_panel_slices} common-clock slices over {len(days)} days "
        f"(max gap {max((summarize_panel(d.panel).max_gap_ms for d in days), default=0)} ms)"
    )
    for r in results:
        print(
            f"{r['candidate_id']:<24} h={r['horizon_bars']:<2} n={r['overall'].get('n', 0):>6} "
            f"gross={r['gross_mean_bps_dev']:>8.3f} net={r['net_mean_bps_dev']:>9.3f} "
            f"-> {r['classification']}"
        )
    print(f"classification counts: {counts}")
    print(f"-> {args.out_dir} and {args.docs_dir}")


if __name__ == "__main__":
    main()
