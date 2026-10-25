"""WP-TDM-11B — preregistration numbers for the single SHORT-bearish rule.

Everything computed here comes from the **exposed** development window
(2026-06-25 .. 2026-09-25) and from the exposed holdout only for the selection
evidence, which is labelled as such. No bar after the last exposed bar is read.

The rule is fixed before the numbers are read, from the repo's own frozen family
parameters::

    momentum@5m, SHORT only, regime_trend == "down" at the decision bar
    decision at the close of bar i, entry at the OPEN of bar i+1 (latency),
    exit at the close of bar i+1+6 (30 minutes), one position at a time

Power is pre-computed from the DEV dispersion only: the confirmatory sample size
may not be renegotiated after the new window is opened.

Usage::

    python scripts/tdm11_prereg.py

Writes ``.tdm11/prereg.json``.
"""

from __future__ import annotations

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
DEV_DIR = REPO_ROOT / "data" / "tdm10"
HOLD_DIR = REPO_ROOT / "data" / "tdm08"

# --- frozen experiment design (do not edit after preregistration) -----------
HYPOTHESIS_ID = "TDM11-H1"
FAMILY = "momentum"
TIMEFRAME = "5m"
TIMEFRAME_MINUTES = 5
DIRECTION = "SHORT"
REGIME_TREND = "down"
HOLD_MINUTES = 30
HORIZON_BARS = HOLD_MINUTES // TIMEFRAME_MINUTES
WINDOW = 100
SIGNAL_LATENCY_BARS = 1  # entry at the next bar's open, never the decision bar's close
ASSETS = ("BTC", "ETH", "SOL")
DEV_START_MS = 1_782_345_600_000  # 2026-06-25T00:00:00Z
DEV_END_MS = 1_790_294_400_000  # 2026-09-25T00:00:00Z
HOLD_END_MS = 1_792_857_524_550
COST_BPS = 23.7906  # BINANCE_SPOT_STANDARD_TAKER, 1k USD, 30 min (G0-5)
ALPHA = 0.05
POWER = 0.80
Z_ALPHA = 1.6448536269514722  # one-sided 95%
Z_POWER = 0.8416212335729143  # 80%
BLOCK_TRADES = 1  # overwritten with round(trades/day)

FAMILY_MODULES = {
    "momentum": ("momentum_family", "MomentumFamily"),
}


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


def family_instance(name: str) -> Any:
    import importlib

    module_name, class_name = FAMILY_MODULES[name]
    module = importlib.import_module(f"trading_bot.research.families.{module_name}")
    return getattr(module, class_name)()


# --- regime labels (same frozen definition as G0, recomputed here) ----------


def atr_series(bars: list[Any], period: int = 14) -> list[float]:
    n = len(bars)
    closes = [float(b.close) for b in bars]
    trs = [0.0] * n
    for k in range(1, n):
        high, low, prev = float(bars[k].high), float(bars[k].low), closes[k - 1]
        trs[k] = max(high - low, abs(high - prev), abs(low - prev))
    out = [0.0] * n
    for i in range(1, n):
        lo = max(1, i - period + 1)
        chunk = trs[lo : i + 1]
        if chunk and closes[i] > 0:
            out[i] = (sum(chunk) / len(chunk)) / closes[i] * 10_000.0
    return out


def rolling_median(values: list[float], window: int) -> list[float]:
    import bisect

    out = [0.0] * len(values)
    buf: list[float] = []
    for i, v in enumerate(values):
        bisect.insort(buf, v)
        if i >= window:
            del buf[bisect.bisect_left(buf, values[i - window])]
        out[i] = buf[len(buf) // 2]
    return out


def trend_z(closes: list[float], window: int = 200) -> list[float]:
    n = len(closes)
    logret = [0.0] * n
    for k in range(1, n):
        logret[k] = math.log(closes[k] / closes[k - 1]) if closes[k - 1] > 0 else 0.0
    run = [0.0] * n
    run_sq = [0.0] * n
    for i in range(1, n):
        run[i] = run[i - 1] + logret[i]
        run_sq[i] = run_sq[i - 1] + logret[i] * logret[i]
    out = [0.0] * n
    span = window - 1
    for i in range(span, n):
        first = i - span
        total = run[i] - run[first]
        total_sq = run_sq[i] - run_sq[first]
        mean = total / span
        var = max(0.0, total_sq / span - mean * mean)
        sigma = math.sqrt(var)
        if sigma <= 0:
            continue
        out[i] = total / (sigma * math.sqrt(window))
    return out


def regime_trend_at(bars: list[Any], i: int) -> str:
    if not bars:
        return "unclassified"
    return _LABELS[id(bars)].trend(i)


class Labels:
    def __init__(self, bars: list[Any]) -> None:
        self.z = trend_z([float(b.close) for b in bars])
        self.atr = atr_series(bars)
        self.median_atr = rolling_median(self.atr, 500)

    def trend(self, i: int) -> str:
        if i < 199 or self.z[i] == 0.0:
            return "unclassified"
        return "up" if self.z[i] > 1.5 else "down" if self.z[i] < -1.5 else "flat"


_LABELS: dict[int, Labels] = {}


def signals_for(bars: list[Any]) -> list[dict[str, Any]]:
    family = family_instance(FAMILY)
    out: list[dict[str, Any]] = []
    for i in range(WINDOW - 1, len(bars)):
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
        out.append({"index": i, "direction": direction})
    return out


def build(
    *,
    start_ms: int,
    end_ms: int,
    direction_filter: str | None,
    regime_filter: str | None,
) -> list[dict[str, Any]]:
    """Chronological, one position at a time, entry at the next bar's open."""
    trades: list[dict[str, Any]] = []
    for asset in ASSETS:
        bars = load_bars(
            (DEV_DIR if end_ms == DEV_END_MS else HOLD_DIR) / f"{asset}_{TIMEFRAME}.json"
        )
        labels = Labels(bars)
        _LABELS[id(bars)] = labels
        last_exit = -1
        for sig in signals_for(bars):
            i = int(sig["index"])
            decision_ms = int(bars[i].timestamp)
            if decision_ms < start_ms or decision_ms >= end_ms:
                continue
            entry_index = i + SIGNAL_LATENCY_BARS
            exit_index = entry_index + HORIZON_BARS
            if exit_index >= len(bars):
                continue
            exit_ms = int(bars[exit_index].timestamp)
            if exit_ms >= end_ms or entry_index <= last_exit:
                continue
            if direction_filter and sig["direction"] != direction_filter:
                continue
            if regime_filter and labels.trend(i) != regime_filter:
                continue
            entry = float(bars[entry_index].open)
            exit_price = float(bars[exit_index].close)
            if entry <= 0:
                continue
            sign = 1.0 if sig["direction"] == "LONG" else -1.0
            trades.append(
                {
                    "asset": asset,
                    "decision_ms": decision_ms,
                    "entry_ms": int(bars[entry_index].timestamp),
                    "exit_ms": exit_ms,
                    "direction": sig["direction"],
                    "gross_bps": sign * (exit_price / entry - 1.0) * 10_000.0,
                    "regime_trend": labels.trend(i),
                }
            )
            last_exit = exit_index
    trades.sort(key=lambda t: (int(t["decision_ms"]), t["asset"]))
    return trades


# --- statistics ------------------------------------------------------------


def required_n(sd: float, effect_bps: float, *, power: float = POWER) -> int:
    if effect_bps <= 0:
        raise ValueError("effect must be positive")
    z_beta = statistics.NormalDist().inv_cdf(power)
    return math.ceil(((Z_ALPHA + z_beta) * sd / effect_bps) ** 2)


def block_bootstrap_se(
    values: list[float], block: int, *, resamples: int = 4000, seed: int = 20261025
) -> float:
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    n = arr.size
    if n < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    n_blocks = math.ceil(n / block)
    means = np.empty(resamples, dtype=np.float64)
    for r in range(resamples):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).reshape(-1) % n
        means[r] = arr[idx[:n]].mean()
    return float(means.std(ddof=1))


def day_span(trades: list[dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    return (
        max(int(t["decision_ms"]) for t in trades) - min(int(t["decision_ms"]) for t in trades)
    ) / 86_400_000.0


def describe(trades: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    gross = [float(t["gross_bps"]) for t in trades]
    if not gross:
        return {"label": label, "trades": 0}
    sd = statistics.stdev(gross) if len(gross) > 1 else float("nan")
    days = day_span(trades)
    tpd = len(gross) / days if days > 0 else float("nan")
    se_iid = sd / math.sqrt(len(gross))
    se_block = block_bootstrap_se(gross, max(1, round(tpd)))
    return {
        "label": label,
        "trades": len(gross),
        "days": round(days, 2),
        "trades_per_day": round(tpd, 3),
        "gross_bps_mean": round(statistics.fmean(gross), 4),
        "gross_bps_median": round(statistics.median(gross), 4),
        "gross_bps_sd": round(sd, 4),
        "se_iid_bps": round(se_iid, 4),
        "se_block_bps": round(se_block, 4),
        "autocorr_inflation": round(se_block / se_iid, 4) if se_iid else None,
        "ci95_low_iid": round(statistics.fmean(gross) - Z_ALPHA * se_iid, 4),
        "ci95_low_block": round(statistics.fmean(gross) - Z_ALPHA * se_block, 4),
        "net_bps_mean": round(statistics.fmean(gross) - COST_BPS, 4),
        "net_ci95_low_block": round(statistics.fmean(gross) - COST_BPS - Z_ALPHA * se_block, 4),
    }


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    primary = build(
        start_ms=DEV_START_MS,
        end_ms=DEV_END_MS,
        direction_filter=DIRECTION,
        regime_filter=REGIME_TREND,
    )
    comparator_all_dirs = build(
        start_ms=DEV_START_MS, end_ms=DEV_END_MS, direction_filter=None, regime_filter=REGIME_TREND
    )
    comparator_no_regime = build(
        start_ms=DEV_START_MS, end_ms=DEV_END_MS, direction_filter=DIRECTION, regime_filter=None
    )
    hold_selection = build(
        start_ms=DEV_END_MS,
        end_ms=HOLD_END_MS,
        direction_filter=DIRECTION,
        regime_filter=REGIME_TREND,
    )

    dev = describe(primary, label="DEV primary (SHORT + trend=down)")
    dev_cmp1 = describe(comparator_all_dirs, label="DEV comparator (both directions + trend=down)")
    dev_cmp2 = describe(comparator_no_regime, label="DEV comparator (SHORT, no regime filter)")
    hold = describe(hold_selection, label="HOLD selection evidence (exposed)")

    sd = float(dev["gross_bps_sd"])
    tpd = float(dev["trades_per_day"])
    block_se_ratio = float(dev["autocorr_inflation"] or 1.0)

    def n_for(effect: float) -> int:
        return required_n(sd * block_se_ratio, effect)

    power = {
        "sd_bps": round(sd, 4),
        "block_inflation": round(block_se_ratio, 4),
        "required_n_at_cost_effect": n_for(COST_BPS),
        "required_n_at_observed_dev_effect": n_for(
            abs(statistics.fmean([t["gross_bps"] for t in primary]))
        )
        if primary
        else None,
        "required_n_at_10bps": n_for(10.0),
        "required_n_at_15bps": n_for(15.0),
        "required_days_at_cost_effect": round(n_for(COST_BPS) / tpd, 1) if tpd else None,
        "required_days_at_observed_effect": None,
        "expected_trades_per_day": round(tpd, 3),
        "detectable_effect_at_n_1000": round(
            (Z_ALPHA + Z_POWER) * sd * block_se_ratio / math.sqrt(1000), 2
        )
        if sd
        else None,
        "formula": "n = ((z_0.95 + z_0.80) * sd_block / effect)^2, one-sided alpha=0.05, power=0.80",
    }
    if primary:
        obs = abs(statistics.fmean([t["gross_bps"] for t in primary]))
        power["required_days_at_observed_effect"] = (
            round(n_for(obs) / tpd, 1) if tpd and obs > 0 else None
        )

    elapsed_days = (int(time.time() * 1000) - HOLD_END_MS) / 86_400_000.0
    payload = {
        "hypothesis_id": HYPOTHESIS_ID,
        "rule": {
            "family": FAMILY,
            "timeframe": TIMEFRAME,
            "direction": DIRECTION,
            "regime_filter": f"regime_trend == '{REGIME_TREND}' (trailing 200-bar z < -1.5)",
            "entry": "open of bar i+1 after a decision at the close of bar i",
            "exit": f"close of bar i+1+{HORIZON_BARS} ({HOLD_MINUTES} min)",
            "position": "one at a time, sequential, no pyramiding",
            "assets": list(ASSETS),
        },
        "cost_bps": COST_BPS,
        "dev": dev,
        "dev_comparators": [dev_cmp1, dev_cmp2],
        "hold_selection_evidence": hold,
        "power": power,
        "availability": {
            "last_exposed_bar_ms": HOLD_END_MS,
            "elapsed_since_exposed_days": round(elapsed_days, 2),
            "expected_trades_available_now": round(tpd * elapsed_days, 2) if tpd else None,
            "required_trades": power["required_n_at_cost_effect"],
            "shortfall_trades": (
                power["required_n_at_cost_effect"] - round(tpd * elapsed_days, 2) if tpd else None
            ),
        },
        "generated_at_ms": int(time.time() * 1000),
    }
    (ART / "prereg.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
