"""WP-TDM-10 — offline economic validation of alpha (builder side).

Frozen spec: ``reports/trading-decision-monitor/WP-TDM-10/EXPERIMENT_SPEC.md``.
This module implements §2-§8 of that spec and nothing else. It cannot place an
order: it imports market-data types, the six research families and the cost
model, and writes files.

Phases
------
``--fetch-dev``      fetch D1+D2 (2026-06-25..2026-09-24) and hash it
``--verify-data``    re-hash DEV + the sealed TDM-08 holdout against their manifests
``--measure``        signals once per (asset, timeframe, family), then every horizon
``--controls``       planted-edge and pure-noise synthetic series (FALSE_SUCCESS guard)
``--all``            verify-data -> measure -> controls
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_DIR = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-10"
SPEC = OUT_DIR / "EXPERIMENT_SPEC.md"
ART = REPO_ROOT / ".tdm10"
DEV_DIR = REPO_ROOT / "data" / "tdm10"
DEV_MANIFEST = DEV_DIR / "DATASET_DEV.json"
HOLD_DIR = REPO_ROOT / "data" / "tdm08"
HOLD_MANIFEST = HOLD_DIR / "DATASET.json"

WINDOW = 100
TIMEFRAMES: dict[str, int] = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
ASSETS = ("BTC", "ETH", "SOL")
FAMILIES = (
    "ema_crossover",
    "momentum",
    "breakout",
    "trend",
    "mean_reversion",
    "volatility",
)
FAMILY_MODULES = {
    "ema_crossover": ("ema_crossover_family", "EmaCrossoverFamily"),
    "momentum": ("momentum_family", "MomentumFamily"),
    "breakout": ("breakout_family", "BreakoutFamily"),
    "trend": ("trend_family", "TrendFamily"),
    "mean_reversion": ("mean_reversion_family", "MeanReversionFamily"),
    "volatility": ("volatility_family", "VolatilityFamily"),
}

PRIMARY_HORIZON = 30.0
HORIZONS = (30.0, 15.0, 60.0, 240.0)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261025
MIN_TRADES_FOR_VERDICT = 30
ALPHA = 0.05

BACKTEST_START = "2026-06-25T00:00:00Z"
WINDOWS: dict[str, tuple[str, str]] = {
    "D1": ("2026-06-25T00:00:00Z", "2026-08-26T00:00:00Z"),
    "D2": ("2026-08-26T00:00:00Z", "2026-09-25T00:00:00Z"),
    "HOLD": ("2026-09-25T00:00:00Z", "2026-10-25T00:00:00Z"),
}
WINDOW_ROLE = {
    "D1": "development/stability",
    "D2": "inner OOS (no choice made on it)",
    "HOLD": "verdict window (outer OOS; measured before by WP-TDM-08)",
    "ALL": "D1+D2 pooled (development evidence)",
}

CSV_COLUMNS = [
    "window",
    "window_role",
    "scope",
    "strategy_id",
    "family",
    "timeframe",
    "asset",
    "trades",
    "trades_per_day",
    "evaluations",
    "gross_bps_per_trade",
    "gross_stdev_bps",
    "t_stat",
    "ci95_low",
    "ci95_high",
    "cost_bps",
    "net_bps_per_trade",
    "expectancy_bps",
    "profit_factor",
    "max_drawdown_bps",
    "sharpe_per_trade",
    "win_rate_pct",
    "breakeven_cost_bps",
    "headroom_bps",
    "trades_above_cost_pct",
    "regime_up_net",
    "regime_down_net",
    "regime_flat_net",
    "vol_high_net",
    "vol_low_net",
    "first_half_net",
    "second_half_net",
    "holm_p",
    "bootstrap_p",
    "classification",
    "fail_reason",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_ms(value: str) -> int:
    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000


def iso(ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def r4(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), 4)


def cost_engine() -> Any:
    from trading_bot.autonomous.costs import CostEngine

    return CostEngine()


def base_cost_bps() -> float:
    """The runtime's own all-in cost for its own default intent (§5)."""
    return float(
        cost_engine().evaluate(size_usd=1000.0, horizon_minutes=PRIMARY_HORIZON).round_trip_bps
    )


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def fetch_dev() -> dict[str, Any]:
    """Fetch D1+D2 from Binance public klines. Bars are sealed against fetch time."""
    import ccxt

    if DEV_DIR.exists() and any(DEV_DIR.glob("*.json")) and not FORCE_REFETCH[0]:
        raise SystemExit(
            "data/tdm10 already populated: refusing to refetch (use --force-refetch to invalidate)"
        )
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30_000})
    start_ms = utc_ms(BACKTEST_START)
    end_ms = utc_ms("2026-09-25T00:00:00Z")
    now_ms = exchange.milliseconds()
    entries: list[dict[str, Any]] = []
    for asset in ASSETS:
        for tf, minutes in TIMEFRAMES.items():
            symbol = f"{asset}/USDT"
            tf_ms = minutes * 60_000
            cursor = start_ms
            bars: dict[int, list[float]] = {}
            requests = 0
            while cursor < end_ms:
                chunk = exchange.fetch_ohlcv(symbol, tf, since=cursor, limit=1000)
                requests += 1
                if not chunk:
                    break
                for row in chunk:
                    close_time = int(row[0]) + tf_ms
                    if close_time > end_ms or close_time > now_ms:
                        continue  # unsealed bar
                    bars[int(row[0])] = [int(row[0]), *map(float, row[1:6])]
                nxt = int(chunk[-1][0]) + tf_ms
                if nxt <= cursor:
                    break
                cursor = nxt
                if len(chunk) < 1000:
                    break
            rows = [bars[ts] for ts in sorted(bars)]
            path = DEV_DIR / f"{asset}_{tf}.json"
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
            print(f"  {asset:3s} {tf:3s} {len(rows):6d} bars {requests:4d} req", flush=True)
    manifest = {
        "artifact": "tdm10-dev-dataset-v1",
        "venue": "Binance spot (public klines, no credentials)",
        "fetched_at_ms": now_ms,
        "window": {"start": BACKTEST_START, "end": "2026-09-25T00:00:00Z", "end_ms": end_ms},
        "sealing_rule": "close_time <= fetched_at AND close_time <= window end",
        "files": entries,
        "total_bars": sum(e["bars"] for e in entries),
    }
    DEV_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"dev dataset: {len(entries)} files, {manifest['total_bars']} bars", flush=True)
    return manifest


def verify_datasets() -> dict[str, Any]:
    """Both manifests must match byte-for-byte, or the run is BLOCKED."""
    result: dict[str, Any] = {"checked": [], "mismatches": [], "missing": []}
    for manifest_path, label in ((DEV_MANIFEST, "DEV"), (HOLD_MANIFEST, "HOLD")):
        if not manifest_path.exists():
            raise SystemExit(f"BLOCKED: missing manifest {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            path = REPO_ROOT / entry["path"]
            if not path.exists():
                result["missing"].append(entry["path"])
                continue
            digest = sha256_file(path)
            ok = digest == entry["sha256"]
            result["checked"].append(
                {"dataset": label, "path": entry["path"], "sha256": digest, "match": ok}
            )
            if not ok:
                result["mismatches"].append(
                    {"path": entry["path"], "expected": entry["sha256"], "actual": digest}
                )
    if result["mismatches"] or result["missing"]:
        result["status"] = "FAIL"
        raise SystemExit(
            f"BLOCKED: dataset integrity failed: {result['mismatches']} missing={result['missing']}"
        )
    result["status"] = "PASS"
    return result


def load_bars(path: Path) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        OHLCV(
            symbol=str(payload["symbol"]),
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in payload["rows"]
    ]


# ---------------------------------------------------------------------------
# signals and trades
# ---------------------------------------------------------------------------


def family_instance(name: str) -> Any:
    module_name, class_name = FAMILY_MODULES[name]
    module = __import__(f"trading_bot.research.families.{module_name}", fromlist=[class_name])
    return getattr(module, class_name)()


def compute_signals(
    family: Any, bars: list[Any], *, max_index: int | None = None
) -> dict[int, dict[str, Any]]:
    """One PIT call per bar; only the strongest signal per bar is kept.

    ``signal at i`` uses ``bars[i-WINDOW+1 .. i]`` and nothing later (§4).
    """
    signals: dict[int, dict[str, Any]] = {}
    limit = len(bars) if max_index is None else min(max_index, len(bars))
    for i in range(WINDOW - 1, limit):
        window = bars[i - WINDOW + 1 : i + 1]
        try:
            alphas = family.generate(window, {}, None)
        except Exception:
            continue
        if not alphas:
            continue
        alpha = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
        direction = str(getattr(alpha, "direction", "")).upper()
        if direction not in ("LONG", "SHORT"):
            continue
        entry = float(getattr(alpha, "entry_reference", 0.0) or 0.0) or float(bars[i].close)
        signals[i] = {"direction": direction, "entry": entry}
    return signals


class Series:
    """Bars plus the trailing indicators the regime labels and vol-aware cost need.

    Computed once per (asset, timeframe); every value at index ``i`` uses bars
    ``<= i`` only.
    """

    def __init__(self, bars: list[Any], *, period: int = 14) -> None:
        self.bars = bars
        self.closes = [float(b.close) for b in bars]
        self.atr = self._atr_series(period)
        self.logret = [0.0] + [
            math.log(self.closes[k] / self.closes[k - 1]) if self.closes[k - 1] > 0 else 0.0
            for k in range(1, len(self.closes))
        ]
        self.median_atr = self._rolling_median(500)
        self.trend = self._rolling_trend(200)

    def _rolling_median(self, window: int) -> list[float]:
        """Median ATR% over the trailing window, O(n log w) via a sorted buffer."""
        import bisect

        n = len(self.atr)
        out = [0.0] * n
        buf: list[float] = []
        for i in range(n):
            bisect.insort(buf, self.atr[i])
            if i >= window:
                del buf[bisect.bisect_left(buf, self.atr[i - window])]
            out[i] = buf[len(buf) // 2]
        return out

    def _rolling_trend(self, window: int) -> list[float]:
        """Trend z-score of the trailing window: drift / (sigma * sqrt(window))."""
        n = len(self.closes)
        out = [0.0] * n
        span = window - 1
        running = [0.0] * n
        running_sq = [0.0] * n
        for i in range(1, n):
            x = self.logret[i]
            running[i] = running[i - 1] + x
            running_sq[i] = running_sq[i - 1] + x * x
        for i in range(span, n):
            first = i - span
            total = running[i] - running[first]
            total_sq = running_sq[i] - running_sq[first]
            mean = total / span
            var = max(0.0, total_sq / span - mean * mean)
            sigma = math.sqrt(var)
            if sigma <= 0:
                continue
            trend_bps = total * 10_000.0
            out[i] = trend_bps / (sigma * math.sqrt(window) * 10_000.0)
        return out

    def _atr_series(self, period: int) -> list[float]:
        n = len(self.bars)
        out = [0.0] * n
        trs = [0.0] * n
        for k in range(1, n):
            high = float(self.bars[k].high)
            low = float(self.bars[k].low)
            prev = float(self.bars[k - 1].close)
            trs[k] = max(high - low, abs(high - prev), abs(low - prev))
        for i in range(1, n):
            lo = max(1, i - period + 1)
            window = trs[lo : i + 1]
            if not window or self.closes[i] <= 0:
                continue
            out[i] = (sum(window) / len(window)) / self.closes[i] * 10_000.0
        return out

    def regime(self, i: int) -> tuple[str, str]:
        """§7: scale-free trend and volatility labels from bars <= i."""
        if i < 199:
            return "unclassified", "unclassified"
        z = self.trend[i]
        if z == 0.0:
            return "unclassified", "unclassified"
        trend = "up" if z > 1.5 else "down" if z < -1.5 else "flat"

        here = self.atr[i]
        med = self.median_atr[i]
        if med <= 0 or here <= 0:
            return trend, "unclassified"
        vol = "high_vol" if here / med > 1.3 else "low_vol"
        return trend, vol


def build_trades(
    series: Series,
    signals: dict[int, dict[str, Any]],
    *,
    horizon_bars: int,
    start_ms: int,
    end_ms: int,
    annotate: bool = False,
) -> list[dict[str, Any]]:
    """Sequential, one position at a time, inside ``[start_ms, end_ms)``."""
    bars = series.bars
    trades: list[dict[str, Any]] = []
    last_exit_index = -1
    for i in sorted(signals):
        decision_ms = int(bars[i].timestamp)
        if decision_ms < start_ms or decision_ms >= end_ms:
            continue
        if i + horizon_bars >= len(bars):
            continue
        exit_ms = int(bars[i + horizon_bars].timestamp)
        if exit_ms >= end_ms:
            continue
        if i <= last_exit_index:
            continue
        sig = signals[i]
        entry = float(sig["entry"])
        exit_price = float(bars[i + horizon_bars].close)
        if entry <= 0:
            continue
        sign = 1.0 if sig["direction"] == "LONG" else -1.0
        trade = {
            "decision_ms": decision_ms,
            "exit_ms": exit_ms,
            "direction": sig["direction"],
            "entry": entry,
            "exit": exit_price,
            "gross_bps": sign * (exit_price / entry - 1.0) * 10_000.0,
        }
        if annotate:
            trend, vol = series.regime(i)
            trade["regime_trend"] = trend
            trade["regime_vol"] = vol
            trade["atr_bps"] = series.atr[i]
        trades.append(trade)
        last_exit_index = i + horizon_bars
    return trades


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def _bootstrap_means(values: list[float], *, resamples: int, seed: int) -> Any:
    """Resampled means, vectorised (chunked so memory stays bounded).

    The spec fixes the resample count, the seed and the percentiles; the PRNG is
    numpy's PCG64 (recorded in the results' ``estimator`` block).
    """
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    n = arr.size
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=np.float64)
    chunk = 250
    for start in range(0, resamples, chunk):
        k = min(chunk, resamples - start)
        idx = rng.integers(0, n, size=(k, n))
        means[start : start + k] = arr[idx].mean(axis=1)
    return means


def bootstrap_ci(
    values: list[float], *, resamples: int = BOOTSTRAP_RESAMPLES
) -> tuple[float, float]:
    if len(values) < 2:
        return float("nan"), float("nan")
    import numpy as np

    means = np.sort(_bootstrap_means(values, resamples=resamples, seed=BOOTSTRAP_SEED))
    return float(means[int(0.025 * resamples)]), float(means[int(0.975 * resamples)])


def bootstrap_p(values: list[float], *, resamples: int = BOOTSTRAP_RESAMPLES) -> float:
    """One-sided bootstrap p-value for H0: mean <= 0."""
    if len(values) < 2:
        return 1.0
    means = _bootstrap_means(values, resamples=resamples, seed=BOOTSTRAP_SEED + 1)
    hits = int((means <= 0.0).sum())
    return (hits + 1) / (resamples + 1)


def max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    worst = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def profit_factor(net: list[float]) -> tuple[float | None, bool]:
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    if losses == 0:
        return (None if gains == 0 else float("inf")), gains > 0
    return gains / losses, False


def summarise(
    trades: list[dict[str, Any]],
    *,
    cost_bps: float,
    days: float,
    evaluations: int,
    cost_fn: Callable[[dict[str, Any]], float] | None = None,
    with_error_bars: bool = True,
) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "trades_per_day": 0.0,
            "evaluations": evaluations,
            "gross_bps_per_trade": None,
            "gross_stdev_bps": None,
            "t_stat": None,
            "ci95_bps": [None, None],
            "cost_bps": r4(cost_bps),
            "net_bps_per_trade": None,
            "profit_factor": None,
            "max_drawdown_bps": None,
            "sharpe_per_trade": None,
            "win_rate_pct": None,
            "breakeven_cost_bps": None,
            "headroom_bps": None,
            "trades_above_cost_pct": None,
            "regime": {},
            "halves": [None, None],
        }
    gross = [t["gross_bps"] for t in trades]
    net = [t["gross_bps"] - (cost_fn(t) if cost_fn else cost_bps) for t in trades]
    n = len(gross)
    mean = statistics.fmean(gross)
    stdev = statistics.stdev(gross) if n > 1 else None
    t_stat = mean / (stdev / math.sqrt(n)) if stdev else None
    ci = bootstrap_ci(gross) if (with_error_bars and n > 1) else (float("nan"), float("nan"))
    pf, pf_inf = profit_factor(net)
    half = n // 2
    halves = [
        statistics.fmean(net[:half]) if half else None,
        statistics.fmean(net[half:]) if n - half else None,
    ]
    regimes: dict[str, dict[str, float]] = {}
    for key in ("regime_trend", "regime_vol"):
        buckets: dict[str, list[float]] = {}
        for trade, net_value in zip(trades, net, strict=True):
            label = str(trade.get(key, "unclassified"))
            buckets.setdefault(label, []).append(net_value)
        regimes[key] = {
            label: r4(statistics.fmean(v)) or 0.0 for label, v in sorted(buckets.items())
        }
        regimes[key + "_count"] = {label: len(v) for label, v in sorted(buckets.items())}  # type: ignore[assignment]
    return {
        "trades": n,
        "trades_per_day": round(n / days, 4) if days > 0 else None,
        "evaluations": evaluations,
        "gross_bps_per_trade": r4(mean),
        "gross_stdev_bps": r4(stdev),
        "t_stat": r4(t_stat),
        "ci95_bps": [r4(ci[0]), r4(ci[1])],
        "cost_bps": r4(cost_bps),
        "net_bps_per_trade": r4(statistics.fmean(net)),
        "profit_factor": None if pf is None else r4(pf),
        "profit_factor_infinite": pf_inf,
        "max_drawdown_bps": r4(max_drawdown(net)),
        "sharpe_per_trade": r4(statistics.fmean(net) / statistics.stdev(net))
        if n >= MIN_TRADES_FOR_VERDICT and statistics.stdev(net) > 0
        else None,
        "sharpe_withheld": None if n >= MIN_TRADES_FOR_VERDICT else "n<30",
        "win_rate_pct": r4(100.0 * sum(1 for v in net if v > 0) / n),
        "breakeven_cost_bps": r4(mean),
        "headroom_bps": r4(mean - base_cost_bps()),
        "trades_above_cost_pct": r4(100.0 * sum(1 for g in gross if g > base_cost_bps()) / n),
        "regime": regimes,
        "halves": [r4(halves[0]), r4(halves[1])],
    }


# ---------------------------------------------------------------------------
# cost sensitivity grid (§5)
# ---------------------------------------------------------------------------


def cost_variants() -> dict[str, tuple[float, Callable[[dict[str, Any]], float] | None]]:
    """name -> (label cost bps, per-trade override or None)."""
    engine = cost_engine()
    base = base_cost_bps()
    variants: dict[str, tuple[float, Callable[[dict[str, Any]], float] | None]] = {
        "base": (base, None),
        "mult_1.25": (base * 1.25, None),
        "mult_1.50": (base * 1.50, None),
        "mult_2.00": (base * 2.00, None),
    }
    for size in (10_000.0, 50_000.0):
        cost = float(engine.evaluate(size_usd=size, horizon_minutes=PRIMARY_HORIZON).round_trip_bps)
        variants[f"size_{int(size)}"] = (cost, None)
    for liq in ("deep", "thin"):
        cost = float(
            engine.evaluate(
                size_usd=1000.0, horizon_minutes=PRIMARY_HORIZON, liquidity_regime=liq
            ).round_trip_bps
        )
        variants[f"liquidity_{liq}"] = (cost, None)
    maker = float(
        engine.evaluate(
            size_usd=1000.0,
            horizon_minutes=PRIMARY_HORIZON,
            entry_order_type="limit_post_only",
            exit_order_type="limit_post_only",
        ).round_trip_bps
    )
    variants["maker_post_only"] = (maker, None)
    vol_aware_cost = base
    variants["vol_aware"] = (vol_aware_cost, None)  # replaced per trade by _vol_aware_cost

    futures = None
    try:
        from trading_bot.autonomous.costs import CostEngine

        fut_engine = CostEngine(scenario_id="BINANCE_USDM_PERP_TAKER")
        futures = float(
            fut_engine.evaluate(
                size_usd=1000.0,
                horizon_minutes=PRIMARY_HORIZON,
                funding_rate_bps_per_interval=1.0,  # ASSUMED-STRESS, declared in the spec
            ).round_trip_bps
        )
        variants["futures_taker_funding1bp"] = (futures, None)
    except Exception:
        pass
    return variants


def vol_aware_cost(trade: dict[str, Any]) -> float:
    """Base model re-evaluated with this trade's PIT ATR as the volatility input."""
    engine = cost_engine()
    atr = float(trade.get("atr_bps") or 0.0)
    return float(
        engine.evaluate(
            size_usd=1000.0, horizon_minutes=PRIMARY_HORIZON, volatility_bps=atr
        ).round_trip_bps
    )


# ---------------------------------------------------------------------------
# classification (§8)
# ---------------------------------------------------------------------------


def holm(pvalues: dict[str, float], alpha: float = ALPHA) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(ordered):
        value = min(1.0, (m - rank) * p)
        running = max(running, value)
        adjusted[key] = running
    return adjusted


def classify_cell(
    hold: dict[str, Any],
    *,
    d1: dict[str, Any],
    d2: dict[str, Any],
    holm_p: float | None,
    stress_net: float | None,
) -> tuple[str, str]:
    """Returns (classification, fail_reason). Rules are §8, verbatim."""
    trades = hold["trades"]
    if trades < MIN_TRADES_FOR_VERDICT:
        return "INSUFFICIENT_SAMPLE", f"holdout trades={trades} < {MIN_TRADES_FOR_VERDICT}"
    gross = hold["gross_bps_per_trade"]
    net = hold["net_bps_per_trade"]
    ci_low = (hold.get("ci95_bps") or [None, None])[0]
    ci_high = (hold.get("ci95_bps") or [None, None])[1]
    if net is None or gross is None:
        return "INCONCLUSIVE_CELL", "no measurable mean"
    reasons: list[str] = []
    if net <= 0:
        reasons.append(f"net {net} <= 0")
    if ci_low is None or ci_low <= 0:
        reasons.append(f"ci95_low(gross) {ci_low} <= 0")
    if not (d1["gross_bps_per_trade"] or 0) > 0:
        reasons.append(f"D1 gross {d1['gross_bps_per_trade']} <= 0")
    if not (d2["gross_bps_per_trade"] or 0) > 0:
        reasons.append(f"D2 gross {d2['gross_bps_per_trade']} <= 0")
    if stress_net is None or stress_net <= 0:
        reasons.append(f"net at x1.25 cost {stress_net} <= 0")
    if not reasons:
        return "GO_RESEARCH_CELL", ""
    if net <= 0 and ci_high is not None and ci_high < 0:
        return "NO_GO_CELL", "; ".join(reasons) + "; gross CI excludes zero on the negative side"
    if net <= 0 and trades >= 100:
        return "NO_GO_CELL", "; ".join(reasons) + "; >=100 trades of power with no edge"
    return "INCONCLUSIVE_CELL", "; ".join(reasons)


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


def measure() -> dict[str, Any]:
    started = time.time()
    if not SPEC.exists():
        raise SystemExit("BLOCKED: EXPERIMENT_SPEC.md missing")
    spec_hash = sha256_file(SPEC)

    data_status = verify_datasets()
    primary_cost = base_cost_bps()
    variants = cost_variants()

    days = {
        key: (utc_ms(end) - utc_ms(start)) / 86_400_000.0 for key, (start, end) in WINDOWS.items()
    }
    days["ALL"] = days["D1"] + days["D2"]

    # signals are computed once per (asset, timeframe, family) and reused by every horizon
    signals_dev: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    series_dev: dict[tuple[str, str], Any] = {}
    series_hold: dict[tuple[str, str], Any] = {}
    signals_hold: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}

    for asset in ASSETS:
        for tf in TIMEFRAMES:
            dev_path = DEV_DIR / f"{asset}_{tf}.json"
            hold_path = HOLD_DIR / f"{asset}_{tf}.json"
            series_dev[(asset, tf)] = Series(load_bars(dev_path))
            series_hold[(asset, tf)] = Series(load_bars(hold_path))
            for family_name in FAMILIES:
                family = family_instance(family_name)
                t0 = time.time()
                signals_dev[(asset, tf, family_name)] = compute_signals(
                    family, series_dev[(asset, tf)].bars
                )
                signals_hold[(asset, tf, family_name)] = compute_signals(
                    family_instance(family_name), series_hold[(asset, tf)].bars
                )
                print(
                    f"  signals {asset:3s} {tf:3s} {family_name:14s} "
                    f"dev={len(signals_dev[(asset, tf, family_name)]):5d} "
                    f"hold={len(signals_hold[(asset, tf, family_name)]):5d} "
                    f"{time.time() - t0:5.1f}s",
                    flush=True,
                )

    results: dict[str, Any] = {
        "artifact": "tdm10-economic-matrix-v1",
        "generated_by": "scripts/tdm10_experiment.py",
        "spec": {"path": SPEC.relative_to(REPO_ROOT).as_posix(), "sha256": spec_hash},
        "data": {
            "dev_manifest": DEV_MANIFEST.relative_to(REPO_ROOT).as_posix(),
            "dev_manifest_sha256": sha256_file(DEV_MANIFEST),
            "hold_manifest": HOLD_MANIFEST.relative_to(REPO_ROOT).as_posix(),
            "hold_manifest_sha256": sha256_file(HOLD_MANIFEST),
            "integrity": data_status["status"],
            "files_checked": len(data_status["checked"]),
        },
        "cost_reference": {
            "scenario_id": "BINANCE_SPOT_STANDARD_TAKER",
            "all_in_bps": primary_cost,
            "components": cost_engine()
            .evaluate(size_usd=1000.0, horizon_minutes=PRIMARY_HORIZON)
            .components,
            "variants": {name: r4(c[0]) for name, c in variants.items()},
        },
        "estimator": {
            "name": "HORIZON_H",
            "window_bars": WINDOW,
            "primary_horizon_minutes": PRIMARY_HORIZON,
            "horizons_swept": list(HORIZONS),
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_rng": "numpy.random.default_rng (PCG64), chunked index resampling",
        },
        "windows": {
            k: {"start": v[0], "end": v[1], "days": r4(days[k])} for k, v in WINDOWS.items()
        },
    }

    matrix_rows: list[dict[str, Any]] = []
    per_window: dict[str, dict[str, dict[str, Any]]] = {}
    sweep_rows: list[dict[str, Any]] = []
    trades_dump: dict[str, Any] = {}

    for tf, tf_minutes in TIMEFRAMES.items():
        horizon_bars = max(1, round(PRIMARY_HORIZON / tf_minutes))
        effective = horizon_bars * tf_minutes
        for family_name in FAMILIES:
            cell = f"{family_name}@{tf}"
            windows_trades: dict[str, list[dict[str, Any]]] = {}
            evaluations: dict[str, int] = {}
            for window_name, (start, end) in list(WINDOWS.items())[:3]:
                start_ms, end_ms = utc_ms(start), utc_ms(end)
                pooled: list[dict[str, Any]] = []
                evals = 0
                per_asset: dict[str, list[dict[str, Any]]] = {}
                for asset in ASSETS:
                    if window_name == "HOLD":
                        series = series_hold[(asset, tf)]
                        signals = signals_hold[(asset, tf, family_name)]
                    else:
                        series = series_dev[(asset, tf)]
                        signals = signals_dev[(asset, tf, family_name)]
                    bars = series.bars
                    trades = build_trades(
                        series,
                        signals,
                        horizon_bars=horizon_bars,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        annotate=True,
                    )
                    for trade in trades:
                        trade["asset"] = asset
                    per_asset[asset] = trades
                    pooled.extend(trades)
                    evals += sum(
                        1
                        for i in signals
                        if start_ms <= int(bars[i].timestamp) < end_ms
                        and i + horizon_bars < len(bars)
                    )
                pooled.sort(key=lambda t: t["decision_ms"])
                windows_trades[window_name] = pooled
                evaluations[window_name] = evals
                per_window.setdefault(cell, {})[window_name] = {
                    "pooled": pooled,
                    "per_asset": per_asset,
                    "evaluations": evals,
                }
            all_trades = sorted(
                windows_trades["D1"] + windows_trades["D2"], key=lambda t: t["decision_ms"]
            )
            windows_trades["ALL"] = all_trades
            evaluations["ALL"] = evaluations["D1"] + evaluations["D2"]

            # --- primary-horizon summaries for every window/scope -----------
            summaries: dict[tuple[str, str], dict[str, Any]] = {}
            for window_name in ("D1", "D2", "HOLD", "ALL"):
                days_here = days[window_name]
                trades = windows_trades[window_name]
                summaries[(window_name, "POOLED")] = summarise(
                    trades,
                    cost_bps=primary_cost,
                    days=days_here,
                    evaluations=evaluations[window_name],
                )
                if trades:
                    for asset in ASSETS:
                        asset_trades = [t for t in trades if t.get("asset") == asset]
                        summaries[(window_name, asset)] = summarise(
                            asset_trades,
                            cost_bps=primary_cost,
                            days=days_here,
                            evaluations=evaluations[window_name],
                        )

            # --- verdict inputs (§8) ---------------------------------------
            hold = summaries[("HOLD", "POOLED")]
            d1 = summaries[("D1", "POOLED")]
            d2 = summaries[("D2", "POOLED")]
            hold_trades = [t for t in windows_trades["HOLD"]]
            stress = summarise(
                hold_trades,
                cost_bps=primary_cost * 1.25,
                days=days["HOLD"],
                evaluations=evaluations["HOLD"],
                with_error_bars=False,
            )
            p_boot = bootstrap_p([t["gross_bps"] for t in hold_trades]) if hold_trades else 1.0
            results.setdefault("bootstrap_pvalues", {})[cell] = r4(p_boot)
            results.setdefault("_raw", {})[cell] = {
                "hold": hold,
                "d1": d1,
                "d2": d2,
                "stress_net_x1.25": stress["net_bps_per_trade"],
            }
            # classification is filled after the Holm step so `holm_p` can be reported
            trades_dump[cell] = {
                "horizon_bars": horizon_bars,
                "effective_minutes": effective,
                "hold": [
                    [
                        t["decision_ms"],
                        t["exit_ms"],
                        t["direction"],
                        t["entry"],
                        t["exit"],
                        r4(t["gross_bps"]),
                    ]
                    for t in windows_trades["HOLD"]
                ],
            }

            # --- horizon sweep (descriptive only) ---------------------------
            for horizon in HORIZONS:
                h_bars = max(1, round(horizon / tf_minutes))
                eff = h_bars * tf_minutes
                sweep_hold: list[dict[str, Any]] = []
                for asset in ASSETS:
                    sweep_hold.extend(
                        build_trades(
                            series_hold[(asset, tf)],
                            signals_hold[(asset, tf, family_name)],
                            horizon_bars=h_bars,
                            start_ms=utc_ms(WINDOWS["HOLD"][0]),
                            end_ms=utc_ms(WINDOWS["HOLD"][1]),
                        )
                    )
                sweep_hold.sort(key=lambda t: t["decision_ms"])
                summary = summarise(
                    sweep_hold,
                    cost_bps=primary_cost,
                    days=days["HOLD"],
                    evaluations=evaluations["HOLD"],
                    with_error_bars=False,
                )
                sweep_rows.append(
                    {
                        "strategy_id": cell,
                        "horizon_minutes_requested": horizon,
                        "horizon_minutes_effective": eff,
                        "horizon_matches_request": eff == horizon,
                        "trades": summary["trades"],
                        "gross_bps_per_trade": summary["gross_bps_per_trade"],
                        "net_bps_per_trade": summary["net_bps_per_trade"],
                    }
                )

            # --- cost sensitivity, on HOLD --------------------------------
            sensitivity: dict[str, Any] = {}
            for name in variants:
                if name == "vol_aware":
                    summary = summarise(
                        hold_trades,
                        cost_bps=primary_cost,
                        days=days["HOLD"],
                        evaluations=evaluations["HOLD"],
                        cost_fn=vol_aware_cost,
                        with_error_bars=False,
                    )
                else:
                    summary = summarise(
                        hold_trades,
                        cost_bps=variants[name][0],
                        days=days["HOLD"],
                        evaluations=evaluations["HOLD"],
                        with_error_bars=False,
                    )
                sensitivity[name] = {
                    "cost_bps": summary["cost_bps"],
                    "net_bps_per_trade": summary["net_bps_per_trade"],
                }
            results.setdefault("sensitivity", {})[cell] = sensitivity

            # keep the summaries for CSV + classification
            for (window_name, scope), summary in summaries.items():
                summary["_cell"] = cell
                summary["_window"] = window_name
                summary["_scope"] = scope
                summary["_family"] = family_name
                summary["_timeframe"] = tf
                matrix_rows.append(summary)

    # Holm over the 24 pooled HOLD cells
    hold_p = {
        cell: float(results["bootstrap_pvalues"][cell]) for cell in results["bootstrap_pvalues"]
    }
    adjusted = holm(hold_p)
    results["holm"] = {"method": "holm", "family_size": len(hold_p), "adjusted": adjusted}

    verdict_inputs = results.pop("_raw")
    verdicts: dict[str, Any] = {}
    for cell, payload in verdict_inputs.items():
        classification, reason = classify_cell(
            payload["hold"],
            d1=payload["d1"],
            d2=payload["d2"],
            holm_p=adjusted.get(cell),
            stress_net=payload["stress_net_x1.25"],
        )
        verdicts[cell] = {
            "classification": classification,
            "fail_reason": reason,
            "holdout_net_bps": payload["hold"]["net_bps_per_trade"],
            "holdout_gross_bps": payload["hold"]["gross_bps_per_trade"],
            "holdout_trades": payload["hold"]["trades"],
            "d1_gross_bps": payload["d1"]["gross_bps_per_trade"],
            "d2_gross_bps": payload["d2"]["gross_bps_per_trade"],
            "stress_net_x1.25": payload["stress_net_x1.25"],
            "bootstrap_p": hold_p.get(cell),
            "holm_p": adjusted.get(cell),
        }
    results["verdicts"] = verdicts

    # attach classification to the CSV rows
    for row in matrix_rows:
        cell = row.pop("_cell")
        window_name = row.pop("_window")
        scope = row.pop("_scope")
        row.pop("_family")
        row.pop("_timeframe")
        if window_name == "HOLD" and scope == "POOLED":
            row["classification"] = verdicts[cell]["classification"]
            row["fail_reason"] = verdicts[cell]["fail_reason"]
        else:
            row["classification"] = "DESCRIPTIVE"
            row["fail_reason"] = WINDOW_ROLE.get(window_name, "")
        row["holm_p"] = adjusted.get(cell) if window_name == "HOLD" and scope == "POOLED" else None
        row["bootstrap_p"] = (
            hold_p.get(cell) if window_name == "HOLD" and scope == "POOLED" else None
        )
        row["_cell"] = cell
        row["_window"] = window_name
        row["_scope"] = scope
        # traceability of the asset a scoped row belongs to
        row["_asset"] = None if scope == "POOLED" else scope

    # tags used by the CSV writer (popped there)
    for row in matrix_rows:
        row["asset"] = row.pop("_asset")
        row["strategy_id"] = row.pop("_cell")
        row["window"] = row.pop("_window")
        row["scope"] = row.pop("_scope")

    results["windows_disjoint"] = assert_disjoint(series_dev, series_hold)
    results["reproduction_of_tdm08"] = reproduce_tdm08(verdicts)
    results["aggregate_verdict"] = aggregate_verdict(verdicts)
    results["duration_seconds"] = r4(time.time() - started)
    results["complete"] = True

    ART.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_matrix(matrix_rows, OUT_DIR / "ALPHA_ECONOMIC_MATRIX.csv")
    write_sweep(sweep_rows, ART / "horizon_sweep.csv")
    (ART / "trades_hold.json").write_text(
        json.dumps(trades_dump, indent=0) + "\n", encoding="utf-8", newline="\n"
    )
    (ART / "results.json").write_text(
        json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(results["aggregate_verdict"], indent=2), flush=True)
    return results


def assert_disjoint(
    series_dev: dict[tuple[str, str], Any], series_hold: dict[tuple[str, str], Any]
) -> dict[str, Any]:
    """D1/D2/HOLD must not share a single bar (§2). Fails the run if they do."""
    report: dict[str, Any] = {"pairs": [], "status": "PASS"}
    d1_end = utc_ms(WINDOWS["D1"][1])
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            dev_ts = {int(b.timestamp) for b in series_dev[(asset, tf)].bars}
            hold_ts = {int(b.timestamp) for b in series_hold[(asset, tf)].bars}
            overlap = dev_ts & hold_ts
            d1 = [t for t in dev_ts if utc_ms(WINDOWS["D1"][0]) <= t < d1_end]
            d2 = [t for t in dev_ts if d1_end <= t < utc_ms(WINDOWS["D2"][1])]
            ok = not overlap and not (set(d1) & set(d2))
            report["pairs"].append(
                {
                    "asset": asset,
                    "timeframe": tf,
                    "dev_bars": len(dev_ts),
                    "hold_bars": len(hold_ts),
                    "d1_bars": len(d1),
                    "d2_bars": len(d2),
                    "overlap_bars": len(overlap),
                    "hold_first": iso(min(hold_ts)) if hold_ts else None,
                    "dev_last": iso(max(dev_ts)) if dev_ts else None,
                    "disjoint": ok,
                }
            )
            if not ok:
                report["status"] = "FAIL"
    if report["status"] != "PASS":
        raise SystemExit("BLOCKED: dataset windows overlap")
    return report


def reproduce_tdm08(verdicts: dict[str, Any]) -> dict[str, Any]:
    """The builder must reproduce WP-TDM-08's holdout cells exactly.

    Same data, same estimator, same cost constant: any deviation is a builder
    defect, not a finding. Tolerance is 1 row of the JSON's own rounding.
    """
    reference_path = (
        REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-08" / "alpha_diagnostics.json"
    )
    out: dict[str, Any] = {
        "reference": reference_path.relative_to(REPO_ROOT).as_posix(),
        "reference_sha256": sha256_file(reference_path),
        "comparisons": [],
        "status": "PASS",
    }
    if not reference_path.exists():
        out["status"] = "NOT_RUN"
        out["reason"] = "WP-TDM-08 alpha_diagnostics.json not found"
        return out
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    ref_rows = {row["strategy_id"]: row for row in reference["family_timeframe"]}
    tolerance = 1.5e-3
    for cell, row in sorted(verdicts.items()):
        ref = ref_rows.get(cell)
        if ref is None:
            out["comparisons"].append({"cell": cell, "status": "NO_REFERENCE"})
            out["status"] = "FAIL"
            continue
        trades_match = int(ref["trades"]) == int(row["holdout_trades"])
        gross_match = (
            row["holdout_gross_bps"] is not None
            and ref["gross_bps_per_trade"] is not None
            and abs(float(ref["gross_bps_per_trade"]) - float(row["holdout_gross_bps"]))
            <= tolerance
        )
        ok = trades_match and gross_match
        out["comparisons"].append(
            {
                "cell": cell,
                "reference_trades": ref["trades"],
                "builder_trades": row["holdout_trades"],
                "reference_gross_bps": ref["gross_bps_per_trade"],
                "builder_gross_bps": row["holdout_gross_bps"],
                "trades_match": trades_match,
                "gross_match": gross_match,
                "status": "PASS" if ok else "FAIL",
            }
        )
        if not ok:
            out["status"] = "FAIL"
    out["cells_compared"] = len(out["comparisons"])
    out["cells_matching"] = sum(1 for c in out["comparisons"] if c.get("status") == "PASS")
    return out


def aggregate_verdict(verdicts: dict[str, Any]) -> dict[str, Any]:
    go = sorted(c for c, v in verdicts.items() if v["classification"] == "GO_RESEARCH_CELL")
    eligible = {c: v for c, v in verdicts.items() if v["classification"] != "INSUFFICIENT_SAMPLE"}
    positive = sorted(c for c, v in eligible.items() if (v["holdout_gross_bps"] or 0.0) > 0.0)
    if go:
        verdict = "GO_RESEARCH"
    elif not positive:
        verdict = "NO_GO_ALPHA"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "verdict": verdict,
        "cells_go_research": go,
        "cells_with_positive_holdout_gross": positive,
        "cells_evaluated": len(verdicts),
        "cells_insufficient_sample": sorted(
            c for c, v in verdicts.items() if v["classification"] == "INSUFFICIENT_SAMPLE"
        ),
        "cells_no_go": sorted(
            c for c, v in verdicts.items() if v["classification"] == "NO_GO_CELL"
        ),
        "note": "GO_RESEARCH authorises offline research only; not PAPER, LIVE, sizing or cost changes.",
    }


def write_matrix(rows: list[dict[str, Any]], path: Path) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            regime = row.pop("regime") or {}
            trend = regime.get("regime_trend", {})
            vol = regime.get("regime_vol", {})
            halves = row.pop("halves") or [None, None]
            ci = row.get("ci95_bps") or [None, None]
            record = dict(row)
            record["ci95_low"] = ci[0]
            record["ci95_high"] = ci[1]
            record["expectancy_bps"] = row.get("net_bps_per_trade")
            record["window_role"] = WINDOW_ROLE.get(str(row.get("window")), "")
            record["regime_up_net"] = trend.get("up")
            record["regime_down_net"] = trend.get("down")
            record["regime_flat_net"] = trend.get("flat")
            record["vol_high_net"] = vol.get("high_vol")
            record["vol_low_net"] = vol.get("low_vol")
            record["first_half_net"] = halves[0]
            record["second_half_net"] = halves[1]
            writer.writerow({k: record.get(k) for k in CSV_COLUMNS})


def write_sweep(rows: list[dict[str, Any]], path: Path) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["strategy_id"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# controls (FALSE_SUCCESS guard)
# ---------------------------------------------------------------------------


class _StubFamily:
    """Test-only family: direction from trailing 3-bar momentum, no future data."""

    def __init__(self, *, invert: bool = False) -> None:
        self.invert = invert

    def generate(self, candles: list[Any], *_: Any) -> list[Any]:
        from trading_bot.research.types import AlphaSignal

        if len(candles) < 5:
            return []
        a, b = float(candles[-4].close), float(candles[-1].close)
        direction = "LONG" if b > a else "SHORT"
        if self.invert:
            direction = "SHORT" if direction == "LONG" else "LONG"
        close = float(candles[-1].close)
        return [
            AlphaSignal(
                family="stub",
                symbol=str(candles[-1].symbol),
                timestamp=int(candles[-1].timestamp),
                direction=direction,
                entry_reference=close,
                structural_stop=close * 0.98,
                timeframe="5m",
            )
        ]


def _synthetic_bars(*, regime: str, seed: int) -> list[Any]:
    import random

    from trading_bot.market_data.types import OHLCV

    rng = random.Random(seed)
    price = 100.0
    bars: list[Any] = []
    start = utc_ms("2026-09-25T00:00:00Z")
    for i in range(4000):
        drift = 0.0
        if regime == "planted":
            # 60-bar blocks with a deterministic drift; the stub's 3-bar momentum
            # is predictive of the next block, so a correct pipeline must find it.
            drift = 0.0012 if (i // 60) % 2 == 0 else -0.0012
        price *= math.exp(drift + rng.gauss(0, 0.0008))
        bars.append(
            OHLCV(
                symbol="SYN/USDT",
                timestamp=start + i * 300_000,
                open=price,
                high=price * 1.0004,
                low=price * 0.9996,
                close=price,
                volume=1.0,
            )
        )
    return bars


def controls() -> dict[str, Any]:
    out: dict[str, Any] = {"checks": []}
    cost = base_cost_bps()
    for name, regime, invert in (
        ("planted_edge", "planted", False),
        ("planted_edge_inverted", "planted", True),
        ("pure_noise", "noise", False),
    ):
        bars = _synthetic_bars(regime=regime, seed=777 if regime == "planted" else 778)
        signals = compute_signals(_StubFamily(invert=invert), bars)
        trades = build_trades(
            Series(bars),
            signals,
            horizon_bars=6,
            start_ms=int(bars[0].timestamp),
            end_ms=int(bars[-1].timestamp) + 1,
        )
        summary = summarise(
            trades, cost_bps=cost, days=4000 * 5 / 1440.0, evaluations=len(bars) - WINDOW
        )
        detected = bool(
            summary["gross_bps_per_trade"] is not None
            and summary["net_bps_per_trade"] is not None
            and summary["net_bps_per_trade"] > 0
            and (summary["ci95_bps"][0] or -1) > 0
        )
        expected = name == "planted_edge"
        out["checks"].append(
            {
                "control": name,
                "expected_detection": expected,
                "detected_profitable": detected,
                "pass": detected == expected,
                "trades": summary["trades"],
                "gross_bps": summary["gross_bps_per_trade"],
                "net_bps": summary["net_bps_per_trade"],
                "ci95_low": summary["ci95_bps"][0],
            }
        )
    out["all_pass"] = all(c["pass"] for c in out["checks"])
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "controls.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(out, indent=2), flush=True)
    return out


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

FORCE_REFETCH = [False]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-dev", action="store_true")
    parser.add_argument("--force-refetch", action="store_true")
    parser.add_argument("--verify-data", action="store_true")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--controls", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    FORCE_REFETCH[0] = args.force_refetch

    if args.fetch_dev:
        fetch_dev()
    if args.verify_data or args.all:
        status = verify_datasets()
        print(f"dataset integrity: {status['status']} ({len(status['checked'])} files)", flush=True)
        ART.mkdir(parents=True, exist_ok=True)
        (ART / "data_integrity.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    if args.measure or args.all:
        measure()
    if args.controls or args.all:
        result = controls()
        if not result["all_pass"]:
            print("CONTROLS FAILED", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
