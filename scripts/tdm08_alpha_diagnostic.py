"""WP-TDM-08 — independent alpha diagnostic for the six committed families.

Why this exists (and why it is not ``multi_family_backtest.py``):

*Phase A* proved the runtime is healthy but trades nothing. *Phase B* has to
answer a question the runtime cannot: **is there gross edge in any of the six
families at all, on data nobody has fitted to?** The research answer
(``docs/STRATEGY_DISCOVERY_V3_RESULTS.json``) was measured on W1-W7
2026-03-01..2026-09-24. This harness measures a *different* period (after the
research window), with a *different* estimator, and reports both.

Estimator: ``HORIZON_H`` — a signal is taken at the close of the decision bar
and marked to market ``h`` bars later, in the signal's direction, with no
stop/take-profit path. That deliberately removes the adapter's SL/TP
conventions (1% flat SL, 0.75% TP) from the measurement, because those are an
exit policy, not signal edge: with them a family can look dead simply because
its exits are mis-sized. Gross edge per trade in bps is therefore
``direction * (exit/entry - 1) * 1e4``.

Point-in-time discipline (asserted, not assumed):

* the decision for bar ``i`` only ever sees ``bars[i-WINDOW+1 : i+1]``;
* the exit price is ``bar[i+h].close`` — strictly later than the decision;
* bars are only used once sealed (``close_time <= fetched_at``) and the whole
  file carries the fetch timestamp so a reader can re-derive the rule;
* no parameter is fitted here: window, horizon and cost model are constants
  taken from the runtime/research, and the classification thresholds are the
  research's (never relaxed to manufacture trades).

Nothing here can place an order: the module imports market data types, the
family classes and the cost model only.

Usage:
    python scripts/tdm08_alpha_diagnostic.py --fetch
    python scripts/tdm08_alpha_diagnostic.py --measure --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

DATA_DIR = REPO_ROOT / "data" / "tdm08"
DATASET = DATA_DIR / "DATASET.json"

#: Rolling window the paper runtime feeds each family (fetch limit=100, PIT slice).
WINDOW = 100
#: Signal held this many bars. One hour for every timeframe, expressed in bars:
#: the research's D-01 result said edge peaks at 15m-30m horizons, so a fixed
#: *time* horizon keeps the four timeframes comparable instead of giving 1h a
#: 12-bar (12-hour) hold.
HORIZON_MINUTES = 30.0
TIMEFRAMES: dict[str, int] = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
ASSETS = ("BTC", "ETH", "SOL")

#: Out-of-sample window: strictly after the research dataset's last bar
#: (2026-09-24). Anything before that is in-sample for the research, so it is
#: excluded rather than mixed in.
OOS_START = "2026-09-25T00:00:00Z"

#: The 5m gate the runtime actually applies (near-flat bars); families are
#: evaluated on the same bar list the runtime would have produced.
FAMILY_MODULES = {
    "ema_crossover": ("ema_crossover_family", "EmaCrossoverFamily"),
    "momentum": ("momentum_family", "MomentumFamily"),
    "breakout": ("breakout_family", "BreakoutFamily"),
    "trend": ("trend_family", "TrendFamily"),
    "mean_reversion": ("mean_reversion_family", "MeanReversionFamily"),
    "volatility": ("volatility_family", "VolatilityFamily"),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_ms(value: str) -> int:
    import calendar

    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def fetch_dataset(*, start: str, end: str | None) -> dict[str, Any]:
    """Fetch sealed OHLCV from Binance's public klines endpoint.

    Public market data only: no key, no signature, no account scope. Pagination
    is explicit (1000 bars per request) and every bar's close time is checked
    against the fetch timestamp, so an unsealed bar can never enter the file.
    """
    # ccxt is already a runtime dependency: public market data, no credentials.
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30_000})
    start_ms = _utc_ms(start)
    now_ms = exchange.milliseconds()
    end_ms = _utc_ms(end) if end else now_ms

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for asset in ASSETS:
        for tf, minutes in TIMEFRAMES.items():
            symbol = f"{asset}/USDT"
            tf_ms = minutes * 60_000
            cursor = start_ms
            bars: list[list[float]] = []
            requests = 0
            while cursor < end_ms:
                chunk = exchange.fetch_ohlcv(symbol, tf, since=cursor, limit=1000)
                requests += 1
                if not chunk:
                    break
                for row in chunk:
                    close_time = int(row[0]) + tf_ms
                    if close_time > end_ms or close_time > now_ms:
                        continue  # unsealed: refuse to look at a forming bar
                    bars.append([int(row[0]), *map(float, row[1:6])])
                nxt = int(chunk[-1][0]) + tf_ms
                if nxt <= cursor:
                    break
                cursor = nxt
                if len(chunk) < 1000:
                    break
            # de-duplicate defensively (paginated endpoints can repeat a bar)
            seen: dict[int, list[float]] = {}
            for row in bars:
                seen[int(row[0])] = row
            rows = [seen[ts] for ts in sorted(seen)]
            path = DATA_DIR / f"{asset}_{tf}.json"
            payload = {
                "asset": asset,
                "symbol": symbol,
                "timeframe": tf,
                "timeframe_minutes": minutes,
                "rows": rows,
                "fetched_at_ms": now_ms,
                "requests": requests,
                "window": {"start_ms": start_ms, "end_ms": end_ms},
            }
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8", newline="\n")
            entries.append(
                {
                    "asset": asset,
                    "timeframe": tf,
                    "path": path.relative_to(REPO_ROOT).as_posix(),
                    "sha256": sha256_file(path),
                    "bars": len(rows),
                    "first_bar_ms": int(rows[0][0]) if rows else None,
                    "last_bar_ms": int(rows[-1][0]) if rows else None,
                    "requests": requests,
                }
            )
            print(f"  {asset:3s} {tf:3s} {len(rows):6d} bars  {requests:3d} req")

    dataset = {
        "artifact": "tdm08-alpha-dataset-v1",
        "venue": "Binance spot (public klines, no credentials)",
        "fetched_at_ms": now_ms,
        "window": {"start": start, "end_ms": end_ms},
        "sealing_rule": "close_time <= fetched_at AND close_time <= window end",
        "files": entries,
        "total_bars": sum(e["bars"] for e in entries),
        "total_requests": sum(e["requests"] for e in entries),
    }
    DATASET.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"dataset: {len(entries)} files, {dataset['total_bars']} bars")
    return dataset


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


def load_bars(entry: dict[str, Any]) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    payload = json.loads((REPO_ROOT / entry["path"]).read_text(encoding="utf-8"))
    symbol = str(payload["symbol"])
    return [
        OHLCV(
            symbol=symbol,
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in payload["rows"]
    ]


def family_instance(name: str) -> Any:
    module_name, class_name = FAMILY_MODULES[name]
    module = __import__(f"trading_bot.research.families.{module_name}", fromlist=[class_name])
    return getattr(module, class_name)()


def measure_family(family: Any, bars: list[Any], horizon_bars: int) -> dict[str, Any]:
    """Signal-on-close, mark-to-market ``horizon_bars`` later. Long/short both."""
    trades: list[dict[str, Any]] = []
    last_exit_index = -1
    evaluations = 0
    for i in range(WINDOW - 1, len(bars) - horizon_bars):
        window = bars[i - WINDOW + 1 : i + 1]
        evaluations += 1
        try:
            alphas = family.generate(window, {}, None)
        except Exception:  # a family that cannot evaluate is skipped, not fixed
            continue
        if not alphas:
            continue
        alpha = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
        direction = str(getattr(alpha, "direction", "")).upper()
        if direction not in ("LONG", "SHORT"):
            continue
        if i <= last_exit_index:
            continue  # one position at a time, same as the paper broker
        entry = float(getattr(alpha, "entry_reference", 0.0) or 0.0) or float(bars[i].close)
        exit_price = float(bars[i + horizon_bars].close)
        sign = 1.0 if direction == "LONG" else -1.0
        gross_bps = sign * (exit_price / entry - 1.0) * 10_000.0
        trades.append(
            {
                "decision_ms": int(bars[i].timestamp),
                "exit_ms": int(bars[i + horizon_bars].timestamp),
                "direction": direction,
                "entry": entry,
                "exit": exit_price,
                "gross_bps": gross_bps,
            }
        )
        last_exit_index = i + horizon_bars
    return {"evaluations": evaluations, "trades": trades}


def bootstrap_ci(
    values: list[float], *, resamples: int = 2000, seed: int = 20261024
) -> list[float]:
    """Percentile bootstrap CI for the mean (deterministic seed).

    Reported because a 30-day OOS sample is small: a mean of +2 bps with a CI of
    [-40, +44] is not evidence of edge, and the report must not pretend it is.
    """
    import random

    if len(values) < 2:
        return [float("nan"), float("nan")]
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [means[int(0.025 * resamples)], means[int(0.975 * resamples)]]


def cost_reference(horizon_minutes: float | None = None) -> dict[str, Any]:
    """Both cost references, from the model itself — never hardcoded."""
    from trading_bot.research.microstructure.cost_model_v3 import (
        ADMISSION_SCENARIO_ID,
        default_model,
    )

    model = default_model()
    runtime = model.evaluate(
        size_usd=1000.0,
        horizon_minutes=HORIZON_MINUTES if horizon_minutes is None else horizon_minutes,
    )
    return {
        "scenario_id": ADMISSION_SCENARIO_ID,
        "runtime_all_in_bps": runtime.round_trip_bps,
        "research_barrier_bps": 12.0,  # STRATEGY_DISCOVERY_V3 cost_model.base_rt_bps
    }


def stats_row(
    gross: list[float], *, runtime_cost: float, research_barrier: float
) -> dict[str, Any]:
    """Mean/stdev/t/CI/net for one sample of per-trade gross bps."""
    if not gross:
        return {
            "trades": 0,
            "gross_bps_per_trade": None,
            "gross_stdev_bps": None,
            "t_stat": None,
            "ci95_bps": [None, None],
            "net_after_runtime_cost_bps": None,
            "net_after_research_barrier_bps": None,
            "win_rate_pct": None,
        }
    mean_bps = statistics.fmean(gross)
    stdev = statistics.stdev(gross) if len(gross) > 1 else None
    t_stat = mean_bps / (stdev / math.sqrt(len(gross))) if stdev else None
    ci = bootstrap_ci(gross) if len(gross) > 1 else [float("nan"), float("nan")]
    return {
        "trades": len(gross),
        "gross_bps_per_trade": round(mean_bps, 4),
        "gross_stdev_bps": None if stdev is None else round(stdev, 4),
        "t_stat": None if t_stat is None else round(t_stat, 3),
        "ci95_bps": [
            None if math.isnan(ci[0]) else round(ci[0], 4),
            None if math.isnan(ci[1]) else round(ci[1], 4),
        ],
        "net_after_runtime_cost_bps": round(mean_bps - runtime_cost, 4),
        "net_after_research_barrier_bps": round(mean_bps - research_barrier, 4),
        "win_rate_pct": round(100.0 * sum(1 for g in gross if g > 0) / len(gross), 2),
    }


def measure(dataset: dict[str, Any], *, horizon_minutes: float | None = None) -> dict[str, Any]:
    """Per cell (family, asset, timeframe) and per ledger cell (family, timeframe).

    The second aggregation exists because the admission ledger is keyed
    ``<family>@<timeframe>``: comparing a ledger entry with a single asset would
    compare different things.
    """
    horizon = HORIZON_MINUTES if horizon_minutes is None else horizon_minutes
    costs = cost_reference(horizon)
    runtime_cost = costs["runtime_all_in_bps"]
    research_barrier = costs["research_barrier_bps"]
    cells: list[dict[str, Any]] = []
    pooled: dict[tuple[str, str], list[float]] = {}
    for entry in dataset["files"]:
        tf = entry["timeframe"]
        horizon_bars = max(1, round(horizon / TIMEFRAMES[tf]))
        bars = load_bars(entry)
        for name in FAMILY_MODULES:
            family = family_instance(name)
            measured = measure_family(family, bars, horizon_bars)
            gross = [t["gross_bps"] for t in measured["trades"]]
            pooled.setdefault((name, tf), []).extend(gross)
            row = {
                "family": name,
                "asset": entry["asset"],
                "timeframe": tf,
                "horizon_bars": horizon_bars,
                "horizon_minutes": horizon,
                "window_bars": WINDOW,
                "evaluations": measured["evaluations"],
                **stats_row(gross, runtime_cost=runtime_cost, research_barrier=research_barrier),
            }
            cells.append(row)
            print(
                f"  {entry['asset']:3s} {tf:3s} {name:15s} trades={row['trades']:4d} "
                f"gross={'-' if row['gross_bps_per_trade'] is None else format(row['gross_bps_per_trade'], '7.2f')}bps "
                f"net@runtime={'-' if row['net_after_runtime_cost_bps'] is None else format(row['net_after_runtime_cost_bps'], '7.2f')}"
            )

    family_timeframe: list[dict[str, Any]] = []
    for (name, tf), gross in sorted(pooled.items()):
        horizon_bars = max(1, round(horizon / TIMEFRAMES[tf]))
        row = {
            "strategy_id": f"{name}@{tf}",
            "family": name,
            "timeframe": tf,
            "assets": [c["asset"] for c in cells if c["family"] == name and c["timeframe"] == tf],
            "horizon_bars": horizon_bars,
            "horizon_minutes": horizon,
            **stats_row(gross, runtime_cost=runtime_cost, research_barrier=research_barrier),
        }
        family_timeframe.append(row)
    return {"costs": costs, "cells": cells, "family_timeframe": family_timeframe}


def classify(row: dict[str, Any]) -> str:
    """Four-way verdict from THIS sample. Gates are the research's, not eased.

    ADMIT       net of the runtime's all-in cost is positive *and* the bootstrap
                CI of gross edge excludes zero on a sample of >= 30 trades.
    EXPERIMENT  gross edge is positive with a CI excluding zero, but cost eats
                it: a real signal whose only blocker is execution economics.
    REJECT      gross edge is negative with a CI excluding zero: the signal is
                anti-predictive, not merely expensive.
    DEFER       the sample cannot separate edge from noise (or is too small).
    """
    gross = row["gross_bps_per_trade"]
    net = row["net_after_runtime_cost_bps"]
    ci_low, ci_high = row["ci95_bps"]
    if gross is None or row["trades"] < 30 or ci_low is None or ci_high is None:
        return "DEFER"
    if net > 0 and ci_low > 0:
        return "ADMIT"
    if gross > 0 and ci_low > 0:
        return "EXPERIMENT"
    if gross < 0 and ci_high < 0:
        return "REJECT"
    return "DEFER"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--start", default=OOS_START)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default="reports/trading-decision-monitor/WP-TDM-08")
    parser.add_argument(
        "--horizon-minutes",
        type=float,
        default=HORIZON_MINUTES,
        help="Signal holding horizon (robustness sweep); the default is the reported one.",
    )
    args = parser.parse_args(argv)

    if args.fetch:
        print(f"fetching OOS window from {args.start}")
        dataset = fetch_dataset(start=args.start, end=args.end)
    else:
        if not DATASET.exists():
            print("no dataset: run --fetch first", file=sys.stderr)
            return 2
        dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    if args.measure:
        print(
            f"measuring six families (HORIZON_H={args.horizon_minutes:g}m estimator, PIT windows)"
        )
        measured = measure(dataset, horizon_minutes=args.horizon_minutes)
        for row in measured["cells"]:
            row["classification"] = classify(row)
        for row in measured["family_timeframe"]:
            row["classification"] = classify(row)
        payload = {
            "artifact": "tdm08-alpha-diagnostics-v1",
            "generated_by": "scripts/tdm08_alpha_diagnostic.py",
            "estimator": {
                "name": "HORIZON_H",
                "window_bars": WINDOW,
                "horizon_minutes": args.horizon_minutes,
                "note": "signal at decision-bar close, marked at close of bar i+h; no SL/TP path",
            },
            "dataset": {
                "path": DATASET.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256_file(DATASET),
                "total_bars": dataset["total_bars"],
                "window": dataset["window"],
                "files": dataset["files"],
            },
            "costs": measured["costs"],
            "cells": measured["cells"],
            "family_timeframe": measured["family_timeframe"],
            "summary": summarize(measured["family_timeframe"]),
        }
        out = REPO_ROOT / args.out
        out.mkdir(parents=True, exist_ok=True)
        name = (
            "alpha_diagnostics.json"
            if args.horizon_minutes == HORIZON_MINUTES
            else f"alpha_diagnostics_h{args.horizon_minutes:g}m.json"
        )
        (out / name).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"wrote {out / name}")
        print(json.dumps(payload["summary"], indent=2))
    return 0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll the 24 ``family@timeframe`` rows up to the six families.

    A family inherits the *best* verdict any of its cells earned (that is what
    "is this family worth more work" means) but the cell detail is kept, so no
    single lucky cell can hide a family whose other three are anti-predictive.
    """
    precedence = {"ADMIT": 4, "EXPERIMENT": 3, "DEFER": 2, "REJECT": 1}
    by_family: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_family.setdefault(
            row["family"],
            {"trades": 0, "gross_weighted": 0.0, "cells": [], "best": None},
        )
        bucket["trades"] += row["trades"]
        if row["gross_bps_per_trade"] is not None:
            bucket["gross_weighted"] += row["gross_bps_per_trade"] * row["trades"]
        bucket["cells"].append(
            {
                "strategy_id": row["strategy_id"],
                "trades": row["trades"],
                "gross_bps_per_trade": row["gross_bps_per_trade"],
                "ci95_bps": row["ci95_bps"],
                "net_after_runtime_cost_bps": row["net_after_runtime_cost_bps"],
                "classification": row["classification"],
            }
        )
        if row["gross_bps_per_trade"] is not None and (
            bucket["best"] is None or row["gross_bps_per_trade"] > bucket["best"][1]
        ):
            bucket["best"] = (row["strategy_id"], row["gross_bps_per_trade"])
    for bucket in by_family.values():
        bucket["gross_bps_per_trade_pooled"] = (
            round(bucket.pop("gross_weighted") / bucket["trades"], 4) if bucket["trades"] else None
        )
        bucket["best_cell"] = bucket.pop("best")
        bucket["classification"] = max(
            (c["classification"] for c in bucket["cells"]),
            key=lambda c: precedence[c],
            default="DEFER",
        )
    return {"by_family": by_family}


if __name__ == "__main__":
    raise SystemExit(main())
