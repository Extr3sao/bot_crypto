"""WP-TDM-11C/D — retrospective evaluation of the frozen rule on the DEV window.

This is **not** the confirmatory evaluation. It runs the rule exactly as
frozen in ``PREREGISTRATION.md`` against the development window, which lies
*before* the holdout window the rule was selected on. A negative result there
cannot be inflated by selection: selection happened later in time, on other
data. It is reported as ``RETROSPECTIVE_OOS_PRE_SELECTION``.

The script refuses to run unless the preregistration still hashes to the value
frozen before any confirmatory bar was read.

Usage::

    python scripts/tdm11_retro.py            # full DEV evaluation
    python scripts/tdm11_retro.py --verify-only

Writes ``evidence/tdm/wp-tdm-11/RETROSPECTIVE_LEDGER.csv`` and
``.tdm11/retro.json``.
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

ART = REPO_ROOT / ".tdm11"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"
PREREG = EVIDENCE / "PREREGISTRATION.md"
FREEZE = ART / "prereg_freeze.json"
DEV_DIR = REPO_ROOT / "data" / "tdm10"

HYPOTHESIS_ID = "TDM11-H1"
FAMILY = "momentum"
TIMEFRAME = "5m"
HORIZON_BARS = 6
LATENCY_BARS = 1
WINDOW = 100
ASSETS = ("BTC", "ETH", "SOL")
DEV_START_MS = 1_782_345_600_000
DEV_END_MS = 1_790_294_400_000
CONFIRMATORY_START_MS = 1_792_857_600_000
COST_BPS = 23.7906
Z = 1.6448536269514722
SEED = 20261025
RESAMPLES = 10_000


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bars(path: Path) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload["rows"]:
        ts = int(row[0])
        if ts >= CONFIRMATORY_START_MS:
            raise SystemExit(
                "refusing to run: the dataset contains bars at/after the confirmatory start"
            )
        rows.append(
            OHLCV(
                symbol=str(payload["symbol"]),
                timestamp=ts,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )
    return rows


def rolling_trend_z(closes: list[float], window: int = 200) -> list[float]:
    n = len(closes)
    lr = [0.0] * n
    for k in range(1, n):
        lr[k] = math.log(closes[k] / closes[k - 1]) if closes[k - 1] > 0 else 0.0
    out = [0.0] * n
    span = window - 1
    for i in range(span, n):
        chunk = lr[i - span + 1 : i + 1]
        mean = sum(chunk) / span
        var = sum((x - mean) ** 2 for x in chunk) / span
        sd = math.sqrt(var)
        out[i] = (sum(chunk) / (sd * math.sqrt(window))) if sd > 0 else 0.0
    return out


def atr_pct(bars: list[Any], period: int = 14) -> list[float]:
    n = len(bars)
    out = [0.0] * n
    for i in range(1, n):
        lo = max(1, i - period + 1)
        trs = []
        for k in range(lo, i + 1):
            high, low = float(bars[k].high), float(bars[k].low)
            prev = float(bars[k - 1].close)
            trs.append(max(high - low, abs(high - prev), abs(low - prev)))
        close = float(bars[i].close)
        out[i] = (sum(trs) / len(trs)) / close * 10_000.0 if close > 0 else 0.0
    return out


def trend_label(z: list[float], i: int) -> str:
    if i < 199 or z[i] == 0.0:
        return "unclassified"
    return "up" if z[i] > 1.5 else "down" if z[i] < -1.5 else "flat"


def signals(bars: list[Any]) -> list[tuple[int, str]]:
    from trading_bot.research.families.momentum_family import MomentumFamily

    family = MomentumFamily()
    out: list[tuple[int, str]] = []
    for i in range(WINDOW - 1, len(bars)):
        try:
            alphas = family.generate(bars[i - WINDOW + 1 : i + 1], {}, None)
        except Exception:
            continue
        if not alphas:
            continue
        best = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
        d = str(getattr(best, "direction", "")).upper()
        if d in ("LONG", "SHORT"):
            out.append((i, d))
    return out


def trades(shorts_only: bool, regime: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        bars = load_bars(DEV_DIR / f"{asset}_{TIMEFRAME}.json")
        z = rolling_trend_z([float(b.close) for b in bars])
        last_exit = -1
        for i, direction in signals(bars):
            if shorts_only and direction != "SHORT":
                continue
            if regime is not None and trend_label(z, i) != regime:
                continue
            entry_i, exit_i = i + LATENCY_BARS, i + LATENCY_BARS + HORIZON_BARS
            if exit_i >= len(bars):
                continue
            decision_ms = int(bars[i].timestamp)
            if decision_ms < DEV_START_MS or decision_ms >= DEV_END_MS:
                continue
            exit_ms = int(bars[exit_i].timestamp)
            if exit_ms >= DEV_END_MS or entry_i <= last_exit:
                continue
            entry = float(bars[entry_i].open)
            if entry <= 0:
                continue
            sign = 1.0 if direction == "LONG" else -1.0
            rows.append(
                {
                    "asset": asset,
                    "decision_ms": decision_ms,
                    "entry_ms": int(bars[entry_i].timestamp),
                    "exit_ms": exit_ms,
                    "direction": direction,
                    "regime_trend": trend_label(z, i),
                    "entry": entry,
                    "exit": float(bars[exit_i].close),
                    "gross_bps": round(
                        sign * (float(bars[exit_i].close) / entry - 1.0) * 10_000.0, 6
                    ),
                }
            )
            last_exit = exit_i
    rows.sort(key=lambda r: (int(r["decision_ms"]), r["asset"]))
    return rows


def stationary_bootstrap_means(
    values: list[float], *, mean_block: float, resamples: int = RESAMPLES, seed: int = SEED
) -> Any:
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    n = arr.size
    rng = np.random.default_rng(seed)
    p = 1.0 / max(2.0, mean_block)
    means = np.empty(resamples, dtype=np.float64)
    for r in range(resamples):
        idx = np.empty(n, dtype=np.int64)
        pos = int(rng.integers(0, n))
        for k in range(n):
            if k > 0 and rng.random() < p:
                pos = int(rng.integers(0, n))
            else:
                pos = (pos + 1) % n if k > 0 else pos
            idx[k] = pos
        means[r] = arr[idx].mean()
    return means


def block_ci(values: list[float], mean_block: float) -> dict[str, float]:
    means = stationary_bootstrap_means(values, mean_block=mean_block)
    return {
        "se": float(means.std(ddof=1)),
        "lo": float(sorted(means)[int(0.025 * means.size)]),
        "hi": float(sorted(means)[int(0.975 * means.size)]),
    }


def circular_block_ci(values: list[float], block: int = 2) -> dict[str, float]:
    """Fixed-length circular block bootstrap (sensitivity, not the primary)."""
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    n = arr.size
    rng = np.random.default_rng(SEED + 1)
    n_blocks = math.ceil(n / block)
    means = np.empty(RESAMPLES, dtype=np.float64)
    for r in range(RESAMPLES):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).reshape(-1) % n
        means[r] = arr[idx[:n]].mean()
    ordered = np.sort(means)
    return {
        "se": float(means.std(ddof=1)),
        "lo": float(ordered[int(0.025 * means.size)]),
        "hi": float(ordered[int(0.975 * means.size)]),
    }


def analytic_ci(values: list[float]) -> dict[str, float]:
    n = len(values)
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(n)
    return {"se": se, "lo": mean - 1.959963984540054 * se, "hi": mean + 1.959963984540054 * se}


def profit_factor(net: list[float]) -> float | None:
    gain = sum(v for v in net if v > 0)
    loss = -sum(v for v in net if v < 0)
    if loss == 0:
        return None
    return gain / loss


def max_drawdown(net: list[float]) -> float:
    equity = peak = worst = 0.0
    for v in net:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def summarise(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not rows:
        return {"label": label, "trades": 0}
    gross = [float(r["gross_bps"]) for r in rows]
    net = [g - COST_BPS for g in gross]
    days = (rows[-1]["decision_ms"] - rows[0]["decision_ms"]) / 86_400_000.0
    tpd = len(rows) / days if days > 0 else float("nan")
    ci_gross = block_ci(gross, max(2.0, tpd))
    ci_net = block_ci(net, max(2.0, tpd))
    circ_gross = circular_block_ci(gross, 2)
    ana_gross = analytic_ci(gross)
    ana_net = analytic_ci(net)
    half = len(net) // 2
    per_asset = {}
    for asset in ASSETS:
        sub = [float(r["gross_bps"]) - COST_BPS for r in rows if r["asset"] == asset]
        if sub:
            per_asset[asset] = {
                "trades": len(sub),
                "net_mean": round(statistics.fmean(sub), 4),
            }
    return {
        "label": label,
        "trades": len(rows),
        "days": round(days, 2),
        "trades_per_day": round(tpd, 3),
        "gross_mean": round(statistics.fmean(gross), 4),
        "gross_sd": round(statistics.stdev(gross), 4),
        "gross_ci95": [round(ci_gross["lo"], 4), round(ci_gross["hi"], 4)],
        "gross_ci95_upper": round(ci_gross["hi"], 4),
        "gross_ci95_lower": round(ci_gross["lo"], 4),
        "net_mean": round(statistics.fmean(net), 4),
        "net_ci95": [round(ci_net["lo"], 4), round(ci_net["hi"], 4)],
        "net_ci95_lower": round(ci_net["lo"], 4),
        "net_ci95_upper": round(ci_net["hi"], 4),
        # s ensitivity of the interval to the resampling scheme: the verdict must
        # not depend on which one was run.
        "gross_ci95_circular": [round(circ_gross["lo"], 4), round(circ_gross["hi"], 4)],
        "gross_ci95_analytic": [round(ana_gross["lo"], 4), round(ana_gross["hi"], 4)],
        "net_ci95_analytic": [round(ana_net["lo"], 4), round(ana_net["hi"], 4)],
        "ci_upper_max": round(max(ci_net["hi"], ana_net["hi"], ana_gross["hi"]), 4),
        "win_rate_pct": round(100.0 * sum(1 for v in net if v > 0) / len(net), 2),
        "profit_factor": round(profit_factor(net), 4) if profit_factor(net) else None,
        "max_drawdown_bps": round(max_drawdown(net), 2),
        "cumulative_net_bps": round(sum(net), 2),
        "first_half_net": round(statistics.fmean(net[:half]), 4) if half else None,
        "second_half_net": round(statistics.fmean(net[half:]), 4) if half else None,
        "per_asset": per_asset,
        "cost_sensitivity": {
            str(c): {
                "net_mean": round(statistics.fmean(gross) - c, 4),
                "ci_lower": round(ci_gross["lo"] - c, 4),
                "ci_upper": round(ci_gross["hi"] - c, 4),
            }
            for c in (0.0, 9.25, 13.7906, 18.7906, 23.7906, 41.25)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    got = sha256_file(PREREG)
    if got != freeze["preregistration_sha256"]:
        raise SystemExit(
            f"preregistration changed after the freeze: {got} != {freeze['preregistration_sha256']}"
        )
    print(f"preregistration hash verified: {got[:16]}…", flush=True)
    if args.verify_only:
        return 0

    started = time.time()
    primary = trades(shorts_only=True, regime="down")
    c1 = trades(shorts_only=True, regime=None)
    c2 = trades(shorts_only=False, regime="down")
    print(f"primary trades={len(primary)} ({time.time() - started:.1f}s)", flush=True)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    columns = [
        "asset",
        "decision_ms",
        "entry_ms",
        "exit_ms",
        "direction",
        "regime_trend",
        "entry",
        "exit",
        "gross_bps",
    ]
    with (EVIDENCE / "RETROSPECTIVE_LEDGER.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(columns) + "\n")
        for row in primary:
            fh.write(",".join(str(row[c]) for c in columns) + "\n")

    summary = summarise(primary, "DEV retrospective (SHORT + trend=down)")
    payload = {
        "hypothesis_id": HYPOTHESIS_ID,
        "window_role": "RETROSPECTIVE_OOS_PRE_SELECTION",
        "window": {"start_ms": DEV_START_MS, "end_ms": DEV_END_MS},
        "not_confirmatory": True,
        "confirmatory_window_opened": False,
        "preregistration_sha256": got,
        "cost_bps": COST_BPS,
        "primary": summary,
        "comparators": [
            summarise(c1, "C1 SHORT, no regime filter"),
            summarise(c2, "C2 both directions, trend=down"),
        ],
        "cost_independence": {
            "gross_ci95_upper": summary.get("gross_ci95_upper"),
            "below_zero": (summary.get("gross_ci95_upper") or 0.0) < 0.0,
            "note": "if the gross CI upper bound is < 0, H1 is refuted for every non-negative cost",
        },
        "decision": {
            "n_ge_min": (summary.get("trades") or 0) >= 36,
            "min_n": 36,
            "rule": "prereg §7",
            "result": None,
            "reason_code": None,
        },
        "generated_at_ms": int(time.time() * 1000),
        "elapsed_s": round(time.time() - started, 1),
    }
    gross_upper = summary.get("gross_ci95_upper") or 0.0
    net_upper = summary.get("net_ci95_upper") or 0.0
    corrob: list[str] = []
    if gross_upper < 0.0:
        corrob.append("GROSS_CI_UPPER_BELOW_ZERO")
    if (summary.get("gross_ci95_circular") or [0, 0])[1] < 0.0:
        corrob.append("GROSS_CI_UPPER_BELOW_ZERO_CIRCULAR_BLOCK")
    if (summary.get("gross_ci95_analytic") or [0, 0])[1] < 0.0:
        corrob.append("GROSS_CI_UPPER_BELOW_ZERO_ANALYTIC")
    payload["cost_independence"]["corroboration"] = corrob
    payload["cost_independence"]["margin_bps"] = {
        "gross_ci95_upper_stationary": round(gross_upper, 4),
        "gross_ci95_upper_circular": (summary.get("gross_ci95_circular") or [None, None])[1],
        "gross_ci95_upper_analytic": (summary.get("gross_ci95_analytic") or [None, None])[1],
        "net_ci95_upper_stationary": round(net_upper, 4),
        "net_ci95_upper_analytic": (summary.get("net_ci95_analytic") or [None, None])[1],
    }
    if payload["decision"]["n_ge_min"] and net_upper < 0.0:
        payload["decision"]["result"] = "NO_GO_ALPHA"
        payload["decision"]["reason_code"] = "NET_CI_UPPER_BELOW_ZERO"
    elif payload["decision"]["n_ge_min"] and gross_upper < 0.0:
        payload["decision"]["result"] = "NO_GO_ALPHA"
        payload["decision"]["reason_code"] = "GROSS_CI_UPPER_BELOW_ZERO"
    elif not payload["decision"]["n_ge_min"]:
        payload["decision"]["result"] = "INCONCLUSIVE"
        payload["decision"]["reason_code"] = "INSUFFICIENT_SAMPLE"
    else:
        payload["decision"]["result"] = "INCONCLUSIVE"
        payload["decision"]["reason_code"] = "CI_CROSSES_ZERO"

    (ART / "retro.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: summary.get(k)
                for k in (
                    "trades",
                    "gross_mean",
                    "gross_sd",
                    "gross_ci95",
                    "net_mean",
                    "net_ci95",
                    "win_rate_pct",
                    "profit_factor",
                    "max_drawdown_bps",
                    "cumulative_net_bps",
                    "first_half_net",
                    "second_half_net",
                    "per_asset",
                )
            },
            indent=1,
        )
    )
    print("decision:", payload["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
