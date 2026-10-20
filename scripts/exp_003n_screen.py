"""exp_003n_screen — measure gross edge per signal before any exit policy is chosen.

    ./.venv/Scripts/python.exe scripts/exp_003n_screen.py
    ./.venv/Scripts/python.exe scripts/exp_003n_screen.py --only lane_a

What is measured
    For every frozen candidate cell (family, timeframe, symbol) and every frozen horizon,
    the *signed forward return in bps* from the open of the bar after the decision bar to the
    open h bars later. That number is what the signal knows about the market, before stops,
    before targets, before fills and before fees. A candidate whose gross cannot reach the
    round-trip cost floor at any horizon cannot be rescued by a better executor, a smarter
    exit or a cleverer fill model — those only redistribute an income that has to exist.

How it is measured
    The families are the repository's own classes, called on a point-in-time window that
    ends at the decision bar. Nothing is re-implemented: a signal this script reports is a
    signal the PAPER lane would receive. Lane B uses the WP-EDGE-015 point-in-time machines
    and their own exits, so its gross is per closed trade by construction; terminal marks are
    excluded because a mark is a valuation and not a fill.

What it refuses
    * any bar at or after 2026-08-06 (the closed holdout),
    * a cell with fewer signals than the frozen sample gate (it is reported
      INSUFFICIENT_EVIDENCE, never silently dropped),
    * a pass that comes from costs being left out: the economic gate subtracts the full
      round trip and the fee floor is printed beside it.

Writes ``analysis/SIGNALS.jsonl.gz``, ``analysis/SCREENING.json`` and ``ECONOMIC_SCREENING.csv``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.economic_recovery.alpha15 import cost_for  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.research.economic_recovery.pit15 import run_family  # noqa: E402
from trading_bot.vision.signal_sources import STRATEGY_SPECS  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"
MINUTE_MS = 60_000
DAY_MS = 86_400_000

SCHEMA_SIGNALS = "AI_BOTS_003N_SIGNALS_V1"
SCHEMA_SCREEN = "AI_BOTS_003N_SCREENING_V1"

TIMEFRAME_MS: dict[str, int] = {}


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_signals(path: Path, payload: Any) -> None:
    """Deterministic gzip: no filename, no mtime. 22 MiB of JSON becomes a committable file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with (
        path.open("wb") as handle,
        gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=9, mtime=0) as stream,
    ):
        stream.write(raw)


def read_signals(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Series:
    symbol: str
    stamps: IntArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    volume: FloatArray


def load_minute(symbol: str) -> Series:
    path = DATASET / f"{symbol}.1m.jsonl.gz"
    if not path.exists():
        raise SystemExit(f"[003n-screen] BLOCKED — missing {path}")
    stamps: list[int] = []
    rows: list[list[float]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            stamps.append(int(row[0]))
            rows.append([float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
    array = np.asarray(rows, dtype=float)
    return Series(
        symbol=symbol,
        stamps=np.asarray(stamps, dtype=np.int64),
        open=array[:, 0],
        high=array[:, 1],
        low=array[:, 2],
        close=array[:, 3],
        volume=array[:, 4],
    )


def aggregate(series: Series, interval_ms: int) -> Series:
    """Complete groups only: a partial bar at the end is dropped, never padded."""

    per = int(interval_ms // MINUTE_MS)
    if per < 1 or interval_ms % MINUTE_MS:
        raise ValueError(f"interval {interval_ms} is not a whole number of minutes")
    usable = (len(series.stamps) // per) * per
    if usable == 0:
        raise ValueError("series shorter than one bar")
    return Series(
        symbol=series.symbol,
        stamps=series.stamps[:usable:per],
        open=series.open[:usable].reshape(-1, per)[:, 0],
        high=series.high[:usable].reshape(-1, per).max(axis=1),
        low=series.low[:usable].reshape(-1, per).min(axis=1),
        close=series.close[:usable].reshape(-1, per)[:, -1],
        volume=series.volume[:usable].reshape(-1, per).sum(axis=1),
    )


def head(series: Series, before_ms: int) -> Series:
    """Cut before the holdout so no signal is even computed on a holdout bar."""

    mask = series.stamps < before_ms
    if not bool(mask.any()):
        raise SystemExit(f"[003n-screen] BLOCKED — {series.symbol} has no bar before the holdout")
    return Series(
        symbol=series.symbol,
        stamps=series.stamps[mask],
        open=series.open[mask],
        high=series.high[mask],
        low=series.low[mask],
        close=series.close[mask],
        volume=series.volume[mask],
    )


def assert_holdout_closed(series: Series, holdout_ms: int) -> None:
    if series.stamps.size and int(series.stamps.max()) >= holdout_ms:
        raise SystemExit(
            f"[003n-screen] REFUSED — {series.symbol} contains a bar at "
            f"{_utc(int(series.stamps.max()))}, inside the closed holdout"
        )


def candles(series: Series) -> list[OHLCV]:
    return [
        OHLCV(
            symbol=series.symbol,
            timestamp=int(series.stamps[index]),
            open=float(series.open[index]),
            high=float(series.high[index]),
            low=float(series.low[index]),
            close=float(series.close[index]),
            volume=float(series.volume[index]),
        )
        for index in range(len(series.stamps))
    ]


def atr_series(series: Series, period: int = 14) -> FloatArray:
    high, low, close = series.high, series.low, series.close
    previous = np.concatenate(([close[0]], close[:-1]))
    true_range = np.maximum(high - low, np.maximum(np.abs(high - previous), np.abs(low - previous)))
    out = np.full(len(true_range), np.nan)
    if len(true_range) >= period:
        cumulative = np.concatenate(([0.0], np.cumsum(true_range)))
        out[period - 1 :] = (cumulative[period:] - cumulative[:-period]) / period
    return out


# --------------------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------------------


def block_bootstrap(
    values: FloatArray, stamps: IntArray, *, resamples: int, seed: int, block_days: int = 5
) -> dict[str, Any]:
    """Moving-block bootstrap over time, so overlapping horizons are not treated as iid."""

    count = len(values)
    if count < 10:
        return {
            "mean": float(values.mean()) if count else None,
            "ci_lower": None,
            "ci_upper": None,
            "p_one_sided": None,
            "blocks": 0,
            "resamples": 0,
            "block_days": block_days,
        }
    block_ms = block_days * DAY_MS
    order = np.argsort(stamps)
    stamps_sorted = stamps[order]
    values_sorted = values[order]
    block_ids = ((stamps_sorted - int(stamps_sorted[0])) // block_ms).astype(int)
    blocks = [values_sorted[block_ids == identifier] for identifier in np.unique(block_ids)]
    blocks = [block for block in blocks if block.size]
    if len(blocks) < 2:
        return {
            "mean": float(values.mean()),
            "ci_lower": None,
            "ci_upper": None,
            "p_one_sided": None,
            "blocks": len(blocks),
            "resamples": 0,
            "block_days": block_days,
        }
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for index in range(resamples):
        picks = rng.integers(0, len(blocks), len(blocks))
        sample = np.concatenate([blocks[pick] for pick in picks])
        means[index] = float(sample.mean()) if sample.size else 0.0
    return {
        "mean": float(values.mean()),
        "ci_lower": float(np.quantile(means, 0.025)),
        "ci_upper": float(np.quantile(means, 0.975)),
        "p_one_sided": float(max(1.0 / (resamples + 1), float((means <= 0.0).mean()))),
        "blocks": len(blocks),
        "resamples": resamples,
        "block_days": block_days,
    }


def bh_adjust(pvalues: dict[str, float], q: float) -> dict[str, Any]:
    """Benjamini-Hochberg: which hypotheses survive q, and by what threshold."""

    items = sorted(pvalues.items(), key=lambda pair: pair[1])
    total = len(items)
    surviving: list[str] = []
    cutoff = 0.0
    for rank, (_key, pvalue) in enumerate(items, start=1):
        threshold = q * rank / total
        if pvalue <= threshold:
            surviving = [name for name, _ in items[:rank]]
            cutoff = threshold
    return {
        "family_size": total,
        "q": q,
        "threshold": cutoff,
        "surviving": sorted(surviving),
        "min_p": items[0][1] if items else None,
        "min_p_key": items[0][0] if items else None,
    }


# --------------------------------------------------------------------------------------
# Lane A — the six AlphaFamilies, forward returns
# --------------------------------------------------------------------------------------


def lane_a_signals(family_id: str, series: Series) -> list[tuple[int, str]]:
    """Every bar is a decision instant; the family answers with its own rule."""

    spec = STRATEGY_SPECS[family_id]
    family = spec.family_cls()
    bars = candles(series)
    window = max(int(spec.min_candles) + 1, 80)
    found: list[tuple[int, str]] = []
    for index in range(window - 1, len(bars)):
        start = max(0, index - window + 1)
        signals = family.generate(bars[start : index + 1], {}, None)
        for signal in signals:
            direction = str(getattr(signal, "direction", "")).upper()
            if direction in {"LONG", "SHORT"}:
                found.append((index, direction))
    return found


def forward_bps(series: Series, index: int, direction: str, horizon: int) -> float | None:
    entry = index + 1
    exit_index = entry + horizon
    if exit_index >= len(series.stamps):
        return None
    entry_price = float(series.open[entry])
    exit_price = float(series.open[exit_index])
    if entry_price <= 0 or exit_price <= 0:
        return None
    move = (exit_price - entry_price) / entry_price * 10_000.0
    return move if direction == "LONG" else -move


def lane_a_cell(
    family_id: str,
    timeframe: str,
    series: Series,
    signals: list[tuple[int, str]],
    *,
    horizons: tuple[int, ...],
    partitions: dict[str, tuple[int, int]],
    bootstrap: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    interval = TIMEFRAME_MS[timeframe]
    rows: list[dict[str, Any]] = []
    for index, direction in signals:
        entry_index = index + 1
        row: dict[str, Any] = {
            "family": family_id,
            "timeframe": timeframe,
            "symbol": series.symbol,
            "ts_ms": int(series.stamps[index]),
            "direction": direction,
            "entry_open": float(series.open[entry_index]) if entry_index < len(series.stamps) else None,
        }
        for horizon in horizons:
            row[f"fwd_{horizon}_bps"] = forward_bps(series, index, direction, horizon)
        rows.append(row)

    per_partition: dict[str, Any] = {}
    for name, (start, end) in partitions.items():
        chosen = [row for row in rows if start <= int(row["ts_ms"]) < end]
        horizon_rows: dict[str, Any] = {}
        for horizon in horizons:
            values = [row[f"fwd_{horizon}_bps"] for row in chosen if row[f"fwd_{horizon}_bps"] is not None]
            times = [int(row["ts_ms"]) for row in chosen if row[f"fwd_{horizon}_bps"] is not None]
            array = np.asarray(values, dtype=float)
            horizon_rows[str(horizon)] = {
                "signals": len(chosen),
                "measured": int(array.size),
                "mean_bps": float(array.mean()) if array.size else None,
                "median_bps": float(np.median(array)) if array.size else None,
                "stdev_bps": float(array.std(ddof=1)) if array.size > 1 else None,
                "hit_rate": float((array > 0).mean()) if array.size else None,
                "bootstrap": block_bootstrap(
                    array,
                    np.asarray(times, dtype=np.int64),
                    resamples=int(bootstrap["resamples"]),
                    seed=int(bootstrap["seed"]),
                    block_days=int(bootstrap["block_days"]),
                ),
                "hours": round(horizon * interval / 3_600_000.0, 4),
            }
        per_partition[name] = {
            "signals": len(chosen),
            "signals_per_day": round(len(chosen) / max(1.0, (end - start) / DAY_MS), 4),
            "horizons": horizon_rows,
        }
    return {"signals": per_partition, "total_signals": len(signals)}, rows


# --------------------------------------------------------------------------------------
# Lane B — the WP-EDGE-015 machines and their own exits
# --------------------------------------------------------------------------------------


def lane_b_cell(
    family_name: str,
    timeframe: str,
    series: Series,
    *,
    parameters: dict[str, Any],
    partitions: dict[str, tuple[int, int]],
    bootstrap: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bars = [
        Bar(
            ts_ms=int(series.stamps[index]),
            open=float(series.open[index]),
            high=float(series.high[index]),
            low=float(series.low[index]),
            close=float(series.close[index]),
            volume=float(series.volume[index]),
        )
        for index in range(len(series.stamps))
    ]
    trades = [trade for trade in run_family(family_name, bars, parameters) if not trade.get("is_mark")]
    per_partition: dict[str, Any] = {}
    for name, (start, end) in partitions.items():
        chosen = [trade for trade in trades if start <= int(trade["entry_ts_ms"]) < end]
        gross = np.asarray([float(trade["gross_bps"]) for trade in chosen], dtype=float)
        times = np.asarray([int(trade["entry_ts_ms"]) for trade in chosen], dtype=np.int64)
        per_partition[name] = {
            "signals": len(chosen),
            "signals_per_day": round(len(chosen) / max(1.0, (end - start) / DAY_MS), 4),
            "horizons": {
                "exit_policy": {
                    "signals": len(chosen),
                    "measured": int(gross.size),
                    "mean_bps": float(gross.mean()) if gross.size else None,
                    "median_bps": float(np.median(gross)) if gross.size else None,
                    "stdev_bps": float(gross.std(ddof=1)) if gross.size > 1 else None,
                    "hit_rate": float((gross > 0).mean()) if gross.size else None,
                    "bootstrap": block_bootstrap(
                        gross,
                        times,
                        resamples=int(bootstrap["resamples"]),
                        seed=int(bootstrap["seed"]),
                        block_days=int(bootstrap["block_days"]),
                    ),
                    "hours": None,
                }
            },
        }
    rows = [
        {
            "family": family_name,
            "timeframe": timeframe,
            "symbol": series.symbol,
            "ts_ms": int(trade["entry_ts_ms"]),
            "direction": str(trade.get("direction", "long")).upper(),
            "gross_bps": float(trade["gross_bps"]),
            "bars_held": int(trade.get("bars_held") or 0),
        }
        for trade in trades
    ]
    return {"signals": per_partition, "total_signals": len(trades)}, rows


# --------------------------------------------------------------------------------------
# Gate evaluation
# --------------------------------------------------------------------------------------


def _weighted_mean(values: list[Any], weights: list[Any]) -> float | None:
    pairs = [
        (float(value), float(weight))
        for value, weight in zip(values, weights, strict=False)
        if value is not None and weight
    ]
    if not pairs:
        return None
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total


def merge_cells(cells: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for cell in cells:
        key = f"{cell['lane']}::{cell['family']}::{cell['timeframe']}"
        block = merged.setdefault(
            key,
            {
                "lane": cell["lane"],
                "family": cell["family"],
                "timeframe": cell["timeframe"],
                "symbols": [],
                "cost_round_trip_bps": 0.0,
                "signals": {},
                "horizons": {},
            },
        )
        block["symbols"].append(cell["symbol"])
        block["cost_round_trip_bps"] = max(
            block["cost_round_trip_bps"], float(cell["cost"]["round_trip_bps"])
        )
        for partition, payload in cell["signals"].items():
            target = block["signals"].setdefault(partition, {"signals": 0, "per_day": 0.0})
            target["signals"] += int(payload["signals"])
            target["per_day"] += float(payload["signals_per_day"])
            for horizon, row in payload["horizons"].items():
                block["horizons"].setdefault(horizon, {}).setdefault(partition, []).append(
                    {**row, "symbol": cell["symbol"]}
                )
    return merged


def evaluate(design: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the frozen gates. The arithmetic is the design's, not the author's."""

    sample_gate = {"RESEARCH": 50, "IS": 20, "VAL": 15}
    fee_floor = float(design["cost_model"]["fee_floor_bps_no_bnb"])
    q = float(design["statistics"]["multiple_testing"]["q"])
    merged = merge_cells(cells)

    tests: dict[str, float] = {}
    for key, block in sorted(merged.items()):
        for horizon, partitions in sorted(block["horizons"].items()):
            rows = partitions.get("IS", [])
            pvalue = _pooled_p(rows)
            tests[f"{key}::{horizon}"] = float(pvalue) if pvalue is not None else 1.0
    bh = bh_adjust(tests, q)
    surviving = set(bh["surviving"])

    decisions: list[dict[str, Any]] = []
    for key, block in sorted(merged.items()):
        signals = {name: int(payload["signals"]) for name, payload in block["signals"].items()}
        sample_ok = all(signals.get(name, 0) >= threshold for name, threshold in sample_gate.items())
        best: tuple[float, str, dict[str, list[dict[str, Any]]]] | None = None
        for horizon, partitions in block["horizons"].items():
            mean = _pooled_mean(partitions.get("IS", []))
            if mean is not None and (best is None or mean > best[0]):
                best = (mean, horizon, partitions)

        decision: dict[str, Any] = {
            "key": key,
            "lane": block["lane"],
            "family": block["family"],
            "timeframe": block["timeframe"],
            "symbols": sorted(block["symbols"]),
            "cost_round_trip_bps": round(block["cost_round_trip_bps"], 4),
            "fee_floor_bps": fee_floor,
            "signals": signals,
            "signals_per_day": round(sum(payload["per_day"] for payload in block["signals"].values()), 4),
            "best_horizon": None,
            "is_mean_bps": None,
            "is_ci_lower_bps": None,
            "val_mean_bps": None,
            "test_mean_bps": None,
            "net_val_bps": None,
            "per_symbol": {},
            "gates": {"S0_sample": sample_ok},
            "failed_gates": [],
            "verdict": "REJECT",
            "reason": "",
        }
        if best is not None:
            mean_is, horizon, partitions = best
            ci_lower = _pooled_ci_lower(partitions.get("IS", []))
            val_mean = _pooled_mean(partitions.get("VAL", []))
            test_mean = _pooled_mean(partitions.get("TEST", []))
            decision.update(
                {
                    "best_horizon": horizon,
                    "is_mean_bps": round(float(mean_is), 4),
                    "is_ci_lower_bps": round(ci_lower, 4) if ci_lower is not None else None,
                    "val_mean_bps": round(val_mean, 4) if val_mean is not None else None,
                    "test_mean_bps": round(test_mean, 4) if test_mean is not None else None,
                    "net_val_bps": round(val_mean - block["cost_round_trip_bps"], 4)
                    if val_mean is not None
                    else None,
                    "per_symbol": _per_symbol(partitions),
                }
            )
            decision["gates"]["S1_existence"] = bool(mean_is > 0 and ci_lower is not None and ci_lower > 0)
            decision["gates"]["S2_replication"] = bool(val_mean is not None and val_mean > 0)
            decision["gates"]["S3_economic"] = bool(
                val_mean is not None
                and (val_mean - block["cost_round_trip_bps"]) > 0
                and val_mean >= fee_floor
            )
            decision["gates"]["S4_multiple_testing"] = f"{key}::{horizon}" in surviving
        else:
            decision["gates"].update(
                {
                    "S1_existence": False,
                    "S2_replication": False,
                    "S3_economic": False,
                    "S4_multiple_testing": False,
                }
            )
        decision["failed_gates"] = [name for name, ok in decision["gates"].items() if not ok]

        if not sample_ok:
            decision["verdict"] = "INSUFFICIENT_EVIDENCE"
            decision["reason"] = (
                "fewer signals than the frozen sample gate "
                f"(RESEARCH>={sample_gate['RESEARCH']}, IS>={sample_gate['IS']}, "
                f"VAL>={sample_gate['VAL']}); measured, not passed"
            )
        elif all(
            decision["gates"][name]
            for name in ("S1_existence", "S2_replication", "S3_economic", "S4_multiple_testing")
        ):
            decision["verdict"] = "ADVANCE_TO_VALIDATION"
            decision["reason"] = (
                "gross clears the full round trip in VAL with a positive IS bootstrap bound, after BH"
            )
        elif decision["gates"]["S1_existence"]:
            decision["verdict"] = "EXPERIMENT"
            decision["reason"] = (
                "the signal carries information in IS but does not replicate or does not pay: "
                f"VAL gross {decision['val_mean_bps']} bps against a full round trip of "
                f"{decision['cost_round_trip_bps']} bps"
            )
        else:
            decision["verdict"] = "REJECT"
            decision["reason"] = (
                "the mean forward return in IS is not positive with a positive bootstrap bound: "
                "no exit, fill or fee model can turn it into income"
            )
        decisions.append(decision)

    verdicts = [row["verdict"] for row in decisions]
    return {
        "holdout_opened": False,
        "gates": design["gates"],
        "sample_gate": sample_gate,
        "multiple_testing": bh,
        "test_count": len(tests),
        #: The per-symbol measurements are the payload's ``cells``; this key holds the merged
        #: gate decisions, so a reader cannot mistake one for the other.
        "decisions": decisions,
        "counts": {label: verdicts.count(label) for label in sorted(set(verdicts))},
        "verdict": "NO_VIABLE_CANDIDATES"
        if "ADVANCE_TO_VALIDATION" not in verdicts
        else "CANDIDATE_FOUND",
    }


def _pooled_mean(rows: list[dict[str, Any]]) -> float | None:
    return _weighted_mean(
        [row["bootstrap"]["mean"] for row in rows], [row["measured"] for row in rows]
    )


def _pooled_ci_lower(rows: list[dict[str, Any]]) -> float | None:
    """The weakest symbol's lower bound: a pooled CI would hide a single losing asset."""

    bounds = [row["bootstrap"]["ci_lower"] for row in rows if row["bootstrap"]["ci_lower"] is not None]
    return min(bounds) if bounds else None


def _pooled_p(rows: list[dict[str, Any]]) -> float | None:
    values = [row["bootstrap"]["p_one_sided"] for row in rows if row["bootstrap"]["p_one_sided"] is not None]
    return max(values) if values else None


def _per_symbol(partitions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Each asset's own VAL mean, so a pooled average cannot hide a losing one."""

    out: dict[str, Any] = {}
    for row in partitions.get("VAL", []):
        out[str(row.get("symbol", "pooled"))] = (
            round(float(row["bootstrap"]["mean"]), 4)
            if row["bootstrap"]["mean"] is not None
            else None
        )
    return out


def write_csv(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "lane",
        "family",
        "timeframe",
        "symbols",
        "signals_research",
        "signals_is",
        "signals_val",
        "signals_per_day",
        "best_horizon_bars",
        "is_mean_bps",
        "is_ci_lower_bps",
        "val_mean_bps",
        "test_mean_bps",
        "cost_round_trip_bps",
        "fee_floor_bps",
        "net_val_bps",
        "gates_passed",
        "failed_gates",
        "verdict",
    ]
    lines = [",".join(header)]
    for cell in payload["cells"]:
        row = [
            cell["lane"],
            cell["family"],
            cell["timeframe"],
            "|".join(cell["symbols"]),
            str(cell["signals"].get("RESEARCH", 0)),
            str(cell["signals"].get("IS", 0)),
            str(cell["signals"].get("VAL", 0)),
            f"{cell['signals_per_day']:.4f}",
            str(cell["best_horizon"]),
            _fmt(cell["is_mean_bps"]),
            _fmt(cell["is_ci_lower_bps"]),
            _fmt(cell["val_mean_bps"]),
            _fmt(cell["test_mean_bps"]),
            f"{cell['cost_round_trip_bps']:.4f}",
            f"{cell['fee_floor_bps']:.4f}",
            _fmt(cell["net_val_bps"]),
            str(sum(1 for ok in cell["gates"].values() if ok)),
            "|".join(cell["failed_gates"]),
            cell["verdict"],
        ]
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _fmt(value: Any) -> str:
    return "" if value is None else f"{float(value):.4f}"


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--only", default="all", choices=("all", "lane_a", "lane_b"))
    args = parser.parse_args(argv)
    out = Path(args.out)

    design = _read_json(out / "design" / "DESIGN.json")
    target = out / "analysis" / "SCREENING.json"
    if target.exists():
        print(
            f"[003n-screen] REFUSED — {target} exists; a screening is not re-run in place",
            file=sys.stderr,
        )
        return 3

    TIMEFRAME_MS.clear()
    TIMEFRAME_MS.update({name: int(ms) for name, ms in design["timeframes"].items()})

    holdout_ms = _parse_utc(design["holdout"]["start_utc"])
    partitions = {
        name: (_parse_utc(block["start_utc"]), _parse_utc(block["end_utc"]))
        for name, block in design["partitions"].items()
    }
    #: The union of the three blocks, so the sample gate can require a research-sized
    #: sample without inventing a fourth window.
    partitions["RESEARCH"] = (
        min(start for start, _ in partitions.values()),
        max(end for _, end in partitions.values()),
    )
    if partitions["RESEARCH"][1] > holdout_ms:
        raise SystemExit("[003n-screen] REFUSED — the research partition reaches the holdout")
    horizons = tuple(int(value) for value in design["horizons_bars"])
    bootstrap = design["statistics"]["bootstrap"]
    stake = float(design["cost_model"]["stake_usdt"])
    symbols = list(design["candidates"]["symbols"])

    # The raw minutes are loaded because the file is the only copy; every path below cuts
    # them before the holdout and asserts the cut, so no statistic can cover that window.
    minute = {symbol: load_minute(symbol) for symbol in symbols}

    costs: dict[str, Any] = {}
    for symbol in symbols:
        terms = cost_for(symbol, stake_usdt=stake)
        costs[symbol] = {
            "round_trip_bps": terms.round_trip_bps(),
            "fee_bps_per_side": terms.fee_bps_per_side,
            "price_bps_per_side": terms.half_spread_bps
            + terms.slippage_bps_per_side
            + terms.impact_bps_per_side,
            "tier": terms.tier,
        }

    cells: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []

    if args.only in ("all", "lane_a"):
        for timeframe in design["candidates"]["timeframes_lane_a"]:
            interval = int(design["timeframes"][timeframe])
            for symbol in symbols:
                series = head(aggregate(minute[symbol], interval), holdout_ms)
                assert_holdout_closed(series, holdout_ms)
                for entry in design["candidates"]["lane_a_runtime_families"]:
                    family_id = entry["id"]
                    started = datetime.now(tz=UTC)
                    signals = lane_a_signals(family_id, series)
                    block, rows = lane_a_cell(
                        family_id,
                        timeframe,
                        series,
                        signals,
                        horizons=horizons,
                        partitions=partitions,
                        bootstrap=bootstrap,
                    )
                    raw.extend(rows)
                    block.update(
                        {
                            "lane": "lane_a",
                            "family": family_id,
                            "timeframe": timeframe,
                            "symbol": symbol,
                            "cost": costs[symbol],
                            "elapsed_s": round((datetime.now(tz=UTC) - started).total_seconds(), 2),
                        }
                    )
                    cells.append(block)
                    print(
                        f"[003n-screen] lane_a {timeframe:>2s} {family_id:14s} {symbol}: "
                        f"{block['total_signals']:5d} signals ({block['elapsed_s']}s)",
                        flush=True,
                    )

    if args.only in ("all", "lane_b"):
        for timeframe in design["candidates"]["timeframes_lane_b"]:
            interval = int(design["timeframes"][timeframe])
            for symbol in symbols:
                series = head(aggregate(minute[symbol], interval), holdout_ms)
                assert_holdout_closed(series, holdout_ms)
                for entry in design["candidates"]["lane_b_alpha15_families"]:
                    block, rows = lane_b_cell(
                        entry["family"],
                        timeframe,
                        series,
                        parameters=entry["parameters"],
                        partitions=partitions,
                        bootstrap=bootstrap,
                    )
                    raw.extend(rows)
                    block.update(
                        {
                            "lane": "lane_b",
                            "family": entry["family"],
                            "timeframe": timeframe,
                            "symbol": symbol,
                            "cost": costs[symbol],
                        }
                    )
                    cells.append(block)
                    print(
                        f"[003n-screen] lane_b {timeframe:>2s} {entry['family']:24s} {symbol}: "
                        f"{block['total_signals']:5d} trades",
                        flush=True,
                    )

    screening = evaluate(design, cells)
    payload = {
        "schema_version": SCHEMA_SCREEN,
        "experiment": design["experiment"],
        "design_sha256": _digest(out / "design" / "DESIGN.json"),
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "costs": costs,
        "cells": cells,
        **screening,
    }
    _write_json(target, payload)
    write_signals(
        out / "analysis" / "SIGNALS.jsonl.gz",
        {
            "schema_version": SCHEMA_SIGNALS,
            "experiment": design["experiment"],
            "count": len(raw),
            "signals": sorted(
                raw,
                key=lambda row: (row["family"], row["timeframe"], row["symbol"], int(row["ts_ms"])),
            ),
        },
    )
    write_csv(out / "ECONOMIC_SCREENING.csv", {"cells": screening["decisions"]})
    print(f"[003n-screen] verdict={payload['verdict']} counts={payload['counts']}")
    print(f"[003n-screen] wrote {target.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
