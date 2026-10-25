"""exp_003n_validate — turn every surviving signal into a closed trade and price it.

    ./.venv/Scripts/python.exe scripts/exp_003n_validate.py

The screen answers "does the signal know something?" in basis points of forward return per
signal. This script answers the question a broker asks: "what does one closed trade earn,
after both commissions and the spread, slippage and impact of both legs?"

Every candidate cell is priced, not only the survivors — a rejection that has no closed-trade
number is an opinion. The exit policy is the one frozen in the design before the screen ran:
an ATR(14) stop at 2.0x, a horizon exit after 12 bars, ``stop_first`` inside a bar, and
nothing else. It is deliberately mechanism-neutral: it does not know what the family knows,
so it cannot flatter one family over another.

Cost scenarios, each labelled for what it is:

``fee_floor``      the 20 bps of spot VIP0 taker fees (15 with the BNB discount). A gross
                   below this cannot be traded at any venue, by any executor.
``full_cost``      fee + half spread + slippage + impact on both legs at a 500 USDT stake,
                   the same model EXP-003L and EXP-003M priced.
``2x`` / ``3x``    the full model with every traded component doubled/tripled: the adverse
                   sensitivity a candidate has to survive rather than merely pass.

Sensitivity to the exit parameters is reported for the cells that survive the screen. It is
reported, never selected on: a configuration is not promoted because 3.0x ATR happened to
look better after the fact.

Writes ``analysis/VALIDATION.json`` and ``analysis/DECISION.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
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
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003n_screen import (  # noqa: E402
    TIMEFRAME_MS,
    aggregate,
    assert_holdout_closed,
    atr_series,
    block_bootstrap,
    head,
    load_minute,
    read_signals,
)

from trading_bot.research.economic_recovery.alpha15 import cost_for  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
SCHEMA = "AI_BOTS_003N_VALIDATION_V1"
DECISION_SCHEMA = "AI_BOTS_003N_DECISION_V1"

SURVIVING = {"ADVANCE_TO_VALIDATION", "EXPERIMENT"}


def _parse_utc(text: str) -> int:
    from datetime import datetime as _datetime

    return int(_datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def trade_net_bps(
    series: Any,
    atr: FloatArray,
    index: int,
    direction: str,
    *,
    horizon: int,
    stop_multiple: float,
    price_bps_per_side: float,
    fee_bps_per_side: float,
    cost_multiplier: float = 1.0,
) -> dict[str, Any] | None:
    """One closed trade: entry at the next open, ATR stop, horizon exit, all-in costs."""

    entry_index = index + 1
    if entry_index + horizon >= len(series.stamps):
        return None
    atr_value = float(atr[index]) if np.isfinite(atr[index]) else None
    if atr_value is None or atr_value <= 0:
        return None
    price_bps = price_bps_per_side * cost_multiplier
    adverse = 1.0 + price_bps / 10_000.0
    reference = float(series.open[entry_index])
    entry = reference * adverse if direction == "LONG" else reference / adverse
    stop = (
        entry - stop_multiple * atr_value
        if direction == "LONG"
        else entry + stop_multiple * atr_value
    )
    exit_price: float | None = None
    exit_reason = "horizon"
    for step in range(1, horizon + 1):
        bar = entry_index + step
        if direction == "LONG":
            if float(series.low[bar]) <= stop:
                exit_price = min(stop, float(series.open[bar]))
                exit_reason = "stop"
                break
        elif float(series.high[bar]) >= stop:
            exit_price = max(stop, float(series.open[bar]))
            exit_reason = "stop"
            break
    if exit_price is None:
        exit_price = float(series.open[entry_index + horizon])
    exit_price = exit_price / adverse if direction == "LONG" else exit_price * adverse
    move = (exit_price - entry) / entry * 10_000.0
    gross = move if direction == "LONG" else -move
    fees = 2.0 * fee_bps_per_side * cost_multiplier
    return {
        "net_bps": gross - fees,
        "gross_bps": gross,
        "fees_bps": fees,
        "exit_reason": exit_reason,
        "ts_ms": int(series.stamps[index]),
        "direction": direction,
    }


def summarise(values: list[float], times: list[int], bootstrap: dict[str, Any]) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    if not array.size:
        return {"trades": 0}
    wins = array[array > 0]
    losses = array[array <= 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    return {
        "trades": int(array.size),
        "mean_bps": float(array.mean()),
        "median_bps": float(np.median(array)),
        "p05_bps": float(np.quantile(array, 0.05)),
        "p95_bps": float(np.quantile(array, 0.95)),
        "stdev_bps": float(array.std(ddof=1)) if array.size > 1 else None,
        "win_rate": float((array > 0).mean()),
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "total_bps": float(array.sum()),
        "bootstrap": block_bootstrap(
            array,
            np.asarray(times, dtype=np.int64),
            resamples=int(bootstrap["resamples"]),
            seed=int(bootstrap["seed"]),
            block_days=int(bootstrap["block_days"]),
        ),
    }


def equity_path(values: list[float], times: list[int], stake: float, equity0: float = 10_000.0) -> dict[str, Any]:
    if not values:
        return {"trades": 0}
    order = np.argsort(np.asarray(times))
    ordered = np.asarray(values, dtype=float)[order]
    curve = equity0 + np.cumsum(ordered / 10_000.0 * stake)
    peaks = np.maximum.accumulate(np.concatenate(([equity0], curve)))
    drawdown = (peaks - np.concatenate(([equity0], curve))) / peaks
    return {
        "trades": int(ordered.size),
        "final_equity_usdt": round(float(curve[-1]), 6),
        "max_drawdown_pct": round(float(drawdown.max()) * 100.0, 6),
        "best_trade_bps": round(float(ordered.max()), 4),
        "worst_trade_bps": round(float(ordered.min()), 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)

    design = _read_json(out / "design" / "DESIGN.json")
    screening = _read_json(out / "analysis" / "SCREENING.json")
    signals_doc = read_signals(out / "analysis" / "SIGNALS.jsonl.gz")
    target = out / "analysis" / "VALIDATION.json"
    if target.exists():
        print(f"[003n-validate] REFUSED — {target} exists", file=sys.stderr)
        return 3

    TIMEFRAME_MS.clear()
    TIMEFRAME_MS.update({name: int(ms) for name, ms in design["timeframes"].items()})
    holdout_ms = _parse_utc(design["holdout"]["start_utc"])
    partitions = {
        name: (_parse_utc(block["start_utc"]), _parse_utc(block["end_utc"]))
        for name, block in design["partitions"].items()
    }
    bootstrap = design["statistics"]["bootstrap"]
    policy = design["exit_policy"]
    horizon = int(policy["horizon_bars"])
    stop_multiple = float(policy["stop_atr_multiple"])
    stake = float(design["cost_model"]["stake_usdt"])
    fee_bps_per_side = float(design["cost_model"]["fee_bps_per_side"])

    symbols = list(design["candidates"]["symbols"])
    minute = {symbol: load_minute(symbol) for symbol in symbols}
    series: dict[tuple[str, str], Any] = {}
    atrs: dict[tuple[str, str], FloatArray] = {}
    for timeframe, interval in design["timeframes"].items():
        for symbol in symbols:
            bars = head(aggregate(minute[symbol], int(interval)), holdout_ms)
            assert_holdout_closed(bars, holdout_ms)
            series[(timeframe, symbol)] = bars
            atrs[(timeframe, symbol)] = atr_series(bars, int(policy["atr_period"]))

    indexed: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in signals_doc["signals"]:
        key = (row["family"], row["timeframe"], row["symbol"], str(row["direction"]).upper())
        indexed.setdefault(key, []).append(row)

    cells = {cell["key"]: cell for cell in screening["decisions"]}
    results: list[dict[str, Any]] = []

    for key, cell in sorted(cells.items()):
        family, timeframe = cell["family"], cell["timeframe"]
        lane = cell["lane"]
        block: dict[str, Any] = {
            "key": key,
            "lane": lane,
            "family": family,
            "timeframe": timeframe,
            "screen_verdict": cell["verdict"],
            "best_horizon_bars": cell["best_horizon"],
            "full_cost_bps": None,
            "partitions": {},
            "scenarios": {},
            "per_symbol": {},
            "sensitivity": None,
        }
        for symbol in symbols:
            cost = cost_for(symbol, stake_usdt=stake)
            block["full_cost_bps"] = max(
                float(block["full_cost_bps"] or 0.0), float(cost.round_trip_bps())
            )

        samples: list[dict[str, Any]] = []
        for name, (start, end) in partitions.items():
            trades: dict[str, list[float]] = {}
            times: dict[str, list[int]] = {}
            for symbol in symbols:
                bars = series[(timeframe, symbol)]
                price_bps = float(
                    cost_for(symbol, stake_usdt=stake).half_spread_bps
                    + cost_for(symbol, stake_usdt=stake).slippage_bps_per_side
                    + cost_for(symbol, stake_usdt=stake).impact_bps_per_side
                )
                if lane == "lane_b":
                    rows = [
                        row
                        for row in signals_doc["signals"]
                        if row["family"] == family
                        and row["timeframe"] == timeframe
                        and row["symbol"] == symbol
                    ]
                    for row in rows:
                        ts = int(row["ts_ms"])
                        if not (start <= ts < end):
                            continue
                        gross = float(row["gross_bps"])
                        net = gross - 2.0 * fee_bps_per_side
                        trades.setdefault(symbol, []).append(net)
                        times.setdefault(symbol, []).append(ts)
                    continue
                rows = indexed.get((family, timeframe, symbol, "LONG"), []) + indexed.get(
                    (family, timeframe, symbol, "SHORT"), []
                )
                lookup = {int(bar_ts): position for position, bar_ts in enumerate(bars.stamps)}
                for row in rows:
                    ts = int(row["ts_ms"])
                    if not (start <= ts < end):
                        continue
                    index = lookup.get(ts)
                    if index is None:
                        raise SystemExit(
                            f"[003n-validate] FAIL — signal at {_utc(ts)} has no bar in {symbol}/{timeframe}"
                        )
                    trade = trade_net_bps(
                        bars,
                        atrs[(timeframe, symbol)],
                        index,
                        str(row["direction"]).upper(),
                        horizon=horizon,
                        stop_multiple=stop_multiple,
                        price_bps_per_side=price_bps,
                        fee_bps_per_side=fee_bps_per_side,
                    )
                    if trade is None:
                        continue
                    trades.setdefault(symbol, []).append(float(trade["net_bps"]))
                    times.setdefault(symbol, []).append(int(trade["ts_ms"]))
                    if name == "VAL" and len(samples) < 5:
                        #: Republished so the verifier can recompute a closed trade itself
                        #: instead of trusting this summary.
                        samples.append(
                            {
                                "symbol": symbol,
                                "ts_ms": int(trade["ts_ms"]),
                                "direction": str(trade["direction"]),
                                "net_bps": float(trade["net_bps"]),
                            }
                        )
            flat_values = [value for values in trades.values() for value in values]
            flat_times = [value for values in times.values() for value in values]
            block["partitions"][name] = {
                "summary": summarise(flat_values, flat_times, bootstrap),
                "equity": equity_path(flat_values, flat_times, stake),
            }
            if name == "VAL":
                for symbol, values in trades.items():
                    block["per_symbol"][symbol] = summarise(values, times[symbol], bootstrap)

        block["sample_trades"] = sorted(samples, key=lambda row: row["ts_ms"])
        val_mean = (block["partitions"].get("VAL", {}).get("summary") or {}).get("mean_bps")
        full_cost = float(block["full_cost_bps"] or 0.0)
        block["scenarios"] = {
            "fee_floor_no_bnb": {
                "cost_bps": float(design["cost_model"]["fee_floor_bps_no_bnb"]),
                "net_val_bps": round(val_mean - float(design["cost_model"]["fee_floor_bps_no_bnb"]), 4)
                if val_mean is not None
                else None,
            },
            "fee_floor_bnb": {
                "cost_bps": float(design["cost_model"]["fee_floor_bps_bnb"]),
                "net_val_bps": round(val_mean - float(design["cost_model"]["fee_floor_bps_bnb"]), 4)
                if val_mean is not None
                else None,
            },
            "full_cost": {
                "cost_bps": round(full_cost, 4),
                "net_val_bps": round(val_mean - full_cost, 4) if val_mean is not None else None,
            },
            "full_cost_2x": {
                "cost_bps": round(full_cost * 2.0, 4),
                "net_val_bps": round(val_mean - full_cost * 2.0, 4) if val_mean is not None else None,
            },
            "full_cost_3x": {
                "cost_bps": round(full_cost * 3.0, 4),
                "net_val_bps": round(val_mean - full_cost * 3.0, 4) if val_mean is not None else None,
            },
        }

        if cell["verdict"] in SURVIVING:
            block["sensitivity"] = sensitivity(
                family,
                timeframe,
                lane,
                series,
                atrs,
                indexed,
                signals_doc,
                cost_for,
                stake,
                fee_bps_per_side,
                partitions,
                bootstrap,
                design,
            )
        results.append(block)
        val = block["partitions"].get("VAL", {}).get("summary", {})
        print(
            f"[003n-validate] {key}: VAL trades={val.get('trades', 0)} "
            f"mean={_fmt(val.get('mean_bps'))} bps net(full)={_fmt(block['scenarios']['full_cost']['net_val_bps'])}",
            flush=True,
        )

    decision = decide(design, screening, results)
    payload = {
        "schema_version": SCHEMA,
        "experiment": design["experiment"],
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exit_policy": policy,
        "stake_usdt": stake,
        "holdout_opened": False,
        "cells": results,
        "decision": decision,
    }
    _write_json(target, payload)
    _write_json(out / "analysis" / "DECISION.json", decision)
    print(f"[003n-validate] verdict={decision['verdict']}")
    return 0


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def sensitivity(
    family: str,
    timeframe: str,
    lane: str,
    series: dict[tuple[str, str], Any],
    atrs: dict[tuple[str, str], FloatArray],
    indexed: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    signals_doc: dict[str, Any],
    cost_for_fn: Any,
    stake: float,
    fee_bps_per_side: float,
    partitions: dict[str, tuple[int, int]],
    bootstrap: dict[str, Any],
    design: dict[str, Any],
    *,
    horizons: tuple[int, ...] = (6, 12, 24),
    multiples: tuple[float, ...] = (1.5, 2.0, 3.0),
) -> dict[str, Any]:
    """Exit-parameter sensitivity on VAL and TEST. Reported, never selected on."""

    out: dict[str, Any] = {}
    start, end = partitions.get("VAL", (0, 0))
    test_start, test_end = partitions.get("TEST", (0, 0))
    for horizon in horizons:
        for multiple in multiples:
            values: list[float] = []
            times: list[int] = []
            for symbol in design["candidates"]["symbols"]:
                bars = series[(timeframe, symbol)]
                cost = cost_for_fn(symbol, stake_usdt=stake)
                price_bps = (
                    cost.half_spread_bps + cost.slippage_bps_per_side + cost.impact_bps_per_side
                )
                lookup = {int(bar_ts): position for position, bar_ts in enumerate(bars.stamps)}
                if lane == "lane_b":
                    rows = [
                        row
                        for row in signals_doc["signals"]
                        if row["family"] == family
                        and row["timeframe"] == timeframe
                        and row["symbol"] == symbol
                        and (start <= int(row["ts_ms"]) < end or test_start <= int(row["ts_ms"]) < test_end)
                    ]
                else:
                    rows = [
                        row
                        for row in indexed.get((family, timeframe, symbol, "LONG"), [])
                        + indexed.get((family, timeframe, symbol, "SHORT"), [])
                        if (start <= int(row["ts_ms"]) < end or test_start <= int(row["ts_ms"]) < test_end)
                    ]
                for row in rows:
                    index = lookup.get(int(row["ts_ms"]))
                    if index is None:
                        continue
                    trade = trade_net_bps(
                        bars,
                        atrs[(timeframe, symbol)],
                        index,
                        str(row["direction"]).upper(),
                        horizon=horizon,
                        stop_multiple=multiple,
                        price_bps_per_side=price_bps,
                        fee_bps_per_side=fee_bps_per_side,
                    )
                    if trade is None:
                        continue
                    values.append(float(trade["net_bps"]))
                    times.append(int(trade["ts_ms"]))
            summary = summarise(values, times, bootstrap)
            out[f"h{horizon}_m{multiple:g}"] = {
                "trades": summary.get("trades", 0),
                "mean_net_bps": summary.get("mean_bps"),
            }
    positives = sum(
        1 for row in out.values() if row["mean_net_bps"] is not None and row["mean_net_bps"] > 0
    )
    return {
        "grid": out,
        "configurations": len(out),
        "positive": positives,
        "stable": positives == len(out) and len(out) > 0,
        "note": (
            "VAL+TEST net per closed trade after full cost; a cell is not promoted because one "
            "corner of this grid is positive"
        ),
    }


def decide(
    design: dict[str, Any], screening: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, Any]:
    by_key = {cell["key"]: cell for cell in results}
    rows: list[dict[str, Any]] = []
    for cell in screening["decisions"]:
        validation = by_key.get(cell["key"], {})
        val = (validation.get("partitions", {}).get("VAL", {}) or {}).get("summary", {})
        full = (validation.get("scenarios", {}) or {}).get("full_cost", {})
        net_full = full.get("net_val_bps")
        verdict = cell["verdict"]
        reason = cell["reason"]
        if verdict == "ADVANCE_TO_VALIDATION":
            closed_ok = net_full is not None and net_full > 0
            verdict = "ADVANCE_TO_VALIDATION" if closed_ok else "EXPERIMENT"
            reason = (
                "the forward return clears costs, but the frozen exit policy's closed trades do not: "
                f"{_fmt(net_full)} bps net in VAL"
                if not closed_ok
                else "gross clears the full round trip in the signal view and in closed trades"
            )
        rows.append(
            {
                "key": cell["key"],
                "lane": cell["lane"],
                "family": cell["family"],
                "timeframe": cell["timeframe"],
                "signals_per_day": cell["signals_per_day"],
                "is_mean_bps": cell["is_mean_bps"],
                "val_mean_bps": cell["val_mean_bps"],
                "cost_full_bps": (validation.get("scenarios", {}) or {}).get("full_cost", {}).get("cost_bps"),
                "net_val_signal_bps": cell["net_val_bps"],
                "closed_trades_val": val.get("trades", 0),
                "closed_mean_net_bps": val.get("mean_bps"),
                "closed_net_full_bps": net_full,
                "closed_win_rate": val.get("win_rate"),
                "closed_profit_factor": val.get("profit_factor"),
                "sensitivity_positive": (validation.get("sensitivity") or {}).get("positive"),
                "sensitivity_configurations": (validation.get("sensitivity") or {}).get("configurations"),
                "verdict": verdict,
                "reason": reason,
            }
        )
    verdicts = [row["verdict"] for row in rows]
    return {
        "schema_version": DECISION_SCHEMA,
        "experiment": design["experiment"],
        "holdout_opened": False,
        "verdict": "NO_VIABLE_CANDIDATES"
        if "ADVANCE_TO_VALIDATION" not in verdicts
        else "CANDIDATE_FOUND",
        "counts": {label: verdicts.count(label) for label in sorted(set(verdicts))},
        "candidates": sorted(rows, key=lambda row: (row["closed_net_full_bps"] is None, -(row["closed_net_full_bps"] or 0.0))),
        "not_promoted": {
            "paper_promotion": "NOT_AUTHORIZED",
            "live_trading": "DISABLED",
            "trades_authorized": 0,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
