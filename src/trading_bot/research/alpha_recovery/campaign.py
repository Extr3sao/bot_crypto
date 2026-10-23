"""ARP-002 experiment campaign runner (tracked, research-only, deterministic).

Runs EXP-ARP-001/002/003/005 over the frozen 5-minute corpus, split into
DEV (W1-W4), VALIDATION (W5-W6) and a LOCKED OOS (W7). It performs no selection:
every metric is produced from the frozen parameters supplied by the caller.

Cost authority: the round-trip basis point figure comes from the runtime
``COST_MODEL_V3`` (``trading_bot.autonomous.costs.CostEngine``), never a literal.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV

from .experiments import (
    Exp001Config,
    Exp001PullbackContinuation,
    Exp002Config,
    Exp002VoidRetest,
    Exp003Config,
    Exp003RelativeStrength,
    Exp005Config,
    Exp005PivotFade,
)
from .metrics import summarize
from .simulate import Trade, simulate

__all__ = [
    "PAIRS",
    "SPLIT_WINDOWS",
    "SYMBOLS",
    "corpus_digest",
    "cost_model_v3_rt_bps",
    "dataset_fingerprints",
    "experiment_code_hash",
    "load_bars",
    "regime_labels",
    "robustness_variants",
    "run_experiment",
    "summarize_run",
]

# ``src/trading_bot/research/alpha_recovery/campaign.py`` -> parents[4] == repo root.
REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "reports/strategy-baseline/data"

SYMBOLS: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
PAIRS: dict[str, tuple[str, str]] = {
    "BTC_leader-ETH_laggard": ("BTCUSDT", "ETHUSDT"),
    "SOL_leader-BTC_laggard": ("SOLUSDT", "BTCUSDT"),
}
SPLIT_WINDOWS: dict[str, tuple[str, ...]] = {
    "DEV": ("W1_2026-03", "W2_2026-04", "W3_2026-05", "W4_2026-06"),
    "VALIDATION": ("W5_2026-07", "W6_2026-08"),
    "OOS_LOCK": ("W7_2026-09",),
}

REGIME_VOL_WINDOW = 100
REGIME_MEDIAN_WINDOW = 720

#: Tracked implementation files whose bytes define the frozen experiment code.
CODE_FILES: tuple[str, ...] = (
    "src/trading_bot/research/alpha_recovery/__init__.py",
    "src/trading_bot/research/alpha_recovery/series.py",
    "src/trading_bot/research/alpha_recovery/simulate.py",
    "src/trading_bot/research/alpha_recovery/experiments.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "src/trading_bot/research/alpha_recovery/campaign.py",
)


# ------------------------------------------------------------------ fingerprints


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lf_digest(path: Path) -> str:
    """sha256 of a file's content with CRLF normalised to LF.

    Git checks out CRLF on Windows, so hashing raw bytes would make ``code_hash``
    depend on the checkout's line endings. Normalising makes the frozen manifest
    hash identical on any machine.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def experiment_code_hash() -> str:
    combined = hashlib.sha256()
    for rel in CODE_FILES:
        combined.update(_lf_digest(REPO / rel).encode())
    return combined.hexdigest()


def _window_files() -> list[Path]:
    if not CORPUS.exists():
        return []
    return sorted(
        p
        for p in CORPUS.glob("*.json")
        if "_5m_" not in p.name  # 5m base files only
    )


def corpus_digest() -> str:
    combined = hashlib.sha256()
    for path in _window_files():
        combined.update(sha256_file(path).encode())
    return combined.hexdigest()


def dataset_fingerprints() -> dict[str, Any]:
    files = _window_files()
    entries = []
    for path in files:
        bars = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            {
                "file": path.name,
                "sha256": sha256_file(path),
                "rows": len(bars),
                "start_ms": bars[0]["ts"],
                "end_ms": bars[-1]["ts"],
            }
        )
    return {"files": entries, "dataset_fingerprint": corpus_digest()}


# ------------------------------------------------------------------ data / cost


def load_bars(symbol: str, window: str) -> list[OHLCV]:
    path = CORPUS / f"{symbol}_{window}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        OHLCV(
            symbol=symbol,
            timestamp=int(b["ts"]),
            open=float(b["open"]),
            high=float(b["high"]),
            low=float(b["low"]),
            close=float(b["close"]),
            volume=float(b["volume"]),
        )
        for b in raw
    ]


def cost_model_v3_rt_bps(size_usd: float = 500.0, horizon_minutes: float = 30.0) -> float:
    """Authoritative COST_MODEL_V3 round-trip basis points (never hardcoded)."""
    from trading_bot.autonomous.costs import CostEngine

    breakdown = CostEngine().evaluate(size_usd=size_usd, horizon_minutes=horizon_minutes)
    return float(breakdown.round_trip_bps)


# ------------------------------------------------------------------ regime


def _rolling_pstdev(values: Sequence[float], window: int) -> list[float | None]:
    """Rolling population stdev with the same window shape as ARP-001 (O(n))."""
    n = len(values)
    out: list[float | None] = [None] * n
    total = 0.0
    sq = 0.0
    for i, v in enumerate(values):
        total += v
        sq += v * v
        if i >= window:
            old = values[i - window]
            total -= old
            sq -= old * old
        count = window if i >= window else i + 1
        if count > 1:
            mean = total / count
            out[i] = math.sqrt(max(0.0, sq / count - mean * mean))
    return out


@lru_cache(maxsize=64)
def _regime_index(symbol: str, window: str) -> tuple[tuple[int, ...], tuple[float | None, ...]]:
    """(timestamps, 101-bar rolling volatility) for one symbol/window, cached."""
    bars = load_bars(symbol, window)
    if not bars:
        return ((), ())
    closes = [b.close for b in bars]
    rets = [0.0]
    for a, b in pairwise(closes):
        prev = a or 1.0
        rets.append((b - prev) / prev * 100.0)
    vols = _rolling_pstdev(rets, REGIME_VOL_WINDOW + 1)
    return (tuple(b.timestamp for b in bars), tuple(vols))


def regime_labels(bars: Sequence[OHLCV]) -> list[str]:
    """PIT regime label per bar (vol100 vs trailing-720 median), ARP-001 windows."""
    closes = [b.close for b in bars]
    rets = [0.0]
    for a, b in pairwise(closes):
        prev = a or 1.0
        rets.append((b - prev) / prev * 100.0)
    vols = _rolling_pstdev(rets, REGIME_VOL_WINDOW + 1)
    labels: list[str] = []
    for i in range(len(bars)):
        if i < REGIME_MEDIAN_WINDOW:
            labels.append("UNKNOWN")
            continue
        seg = [v for v in vols[i - REGIME_MEDIAN_WINDOW : i + 1] if v is not None]
        cur = vols[i]
        if not seg or cur is None:
            labels.append("UNKNOWN")
        else:
            labels.append("HIGH" if cur > statistics.median(seg) else "LOW")
    return labels


# ------------------------------------------------------------------ running


Runner = Callable[[], Any]


def _run_single_asset(
    factory: Runner, split: str, cost_bps_rt: float, entry_delay: int
) -> dict[str, list[Trade]]:
    out: dict[str, list[Trade]] = {}
    for key, sym in SYMBOLS.items():
        trades: list[Trade] = []
        for window in SPLIT_WINDOWS[split]:
            bars = load_bars(sym, window)
            if not bars:
                continue
            trades.extend(
                simulate(
                    factory(), bars, cost_bps_rt=cost_bps_rt, entry_delay_bars=entry_delay
                ).trades
            )
        out[key] = trades
    return out


def _run_exp003(
    config: Exp003Config, split: str, cost_bps_rt: float, entry_delay: int
) -> dict[str, list[Trade]]:
    out: dict[str, list[Trade]] = {}
    for key, (leader, laggard) in PAIRS.items():
        trades: list[Trade] = []
        for window in SPLIT_WINDOWS[split]:
            lb = load_bars(leader, window)
            gb = load_bars(laggard, window)
            if not lb or not gb:
                continue
            strategy = Exp003RelativeStrength(lb, config)
            trades.extend(
                simulate(strategy, gb, cost_bps_rt=cost_bps_rt, entry_delay_bars=entry_delay).trades
            )
        out[key] = trades
    return out


def run_experiment(
    experiment_id: str,
    params: dict[str, Any],
    split: str,
    *,
    cost_bps_rt: float,
    entry_delay: int = 0,
) -> dict[str, list[Trade]]:
    """Run one experiment on one split. Returns trades keyed by asset/pair label."""
    if experiment_id == "EXP-ARP-001":
        cfg001 = Exp001Config(**params)
        return _run_single_asset(
            lambda: Exp001PullbackContinuation(cfg001), split, cost_bps_rt, entry_delay
        )
    if experiment_id == "EXP-ARP-002":
        cfg002 = Exp002Config(**params)
        return _run_single_asset(lambda: Exp002VoidRetest(cfg002), split, cost_bps_rt, entry_delay)
    if experiment_id == "EXP-ARP-003":
        cfg003 = Exp003Config(**params)
        return _run_exp003(cfg003, split, cost_bps_rt, entry_delay)
    if experiment_id == "EXP-ARP-005":
        cfg005 = Exp005Config(**params)
        return _run_single_asset(lambda: Exp005PivotFade(cfg005), split, cost_bps_rt, entry_delay)
    raise KeyError(f"unknown experiment {experiment_id!r}")


def _regime_bucket(trades: Sequence[Trade], symbol: str) -> dict[str, dict[str, Any]]:
    """Net PnL per regime for one symbol, using the symbol's own corpus bars.

    Only the entry bars need a regime label, so the trailing-720-bar median is
    computed per *trade* (hundreds) rather than per bar (millions) — the same
    ARP-001 definition and windows, without the quadratic cost.
    """
    by_regime: dict[str, list[float]] = defaultdict(list)
    index: dict[int, tuple[tuple[float | None, ...], int]] = {}
    for window in SPLIT_WINDOWS["DEV"] + SPLIT_WINDOWS["VALIDATION"]:  # OOS stays locked
        stamps, vols = _regime_index(symbol, window)
        for i, ts in enumerate(stamps):
            index[ts] = (vols, i)
    for t in trades:
        found = index.get(t.entry_ts)
        if found is None:
            by_regime["UNKNOWN"].append(t.net)
            continue
        vols, i = found
        if i < REGIME_MEDIAN_WINDOW:
            label = "UNKNOWN"
        else:
            seg = [v for v in vols[i - REGIME_MEDIAN_WINDOW : i + 1] if v is not None]
            cur = vols[i]
            if not seg or cur is None:
                label = "UNKNOWN"
            else:
                label = "HIGH" if cur > statistics.median(seg) else "LOW"
        by_regime[label].append(t.net)
    return {lab: {"n": len(v), "net_usd": round(sum(v), 2)} for lab, v in sorted(by_regime.items())}


def summarize_run(
    trades_by_key: dict[str, list[Trade]],
    *,
    cost_bps_rt: float,
    key_to_symbol: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Combined + per-key metrics, plus a regime matrix where a symbol is known."""
    combined = [t for trades in trades_by_key.values() for t in trades]
    out: dict[str, Any] = {
        "combined": summarize(combined, cost_bps_rt=cost_bps_rt),
        "by_key": {
            key: summarize(trades, cost_bps_rt=cost_bps_rt)
            for key, trades in sorted(trades_by_key.items())
        },
    }
    if key_to_symbol:
        out["by_regime"] = {
            key: _regime_bucket(trades_by_key[key], sym)
            for key, sym in sorted(key_to_symbol.items())
        }
    return out


# ------------------------------------------------------------------ robustness


def robustness_variants(experiment_id: str) -> dict[str, dict[str, Any]]:
    """Frozen §16 perturbations (declared BEFORE results; one-point optimum check)."""
    if experiment_id == "EXP-ARP-001":
        return {
            "ma_fast_18": {"fast": 18},
            "ma_fast_22": {"fast": 22},
            "ma_mid_38": {"mid": 38},
            "ma_mid_42": {"mid": 42},
            "cross_lookback_45": {"cross_lookback": 45},
            "cross_lookback_75": {"cross_lookback": 75},
            "measured_move_target": {"variant": "measured_move"},
        }
    if experiment_id == "EXP-ARP-002":
        return {
            "void_bars_2": {"void_bars": 2},
            "void_bars_4": {"void_bars": 4},
            "void_atr_mult_1_75": {"void_atr_mult": 1.75},
            "void_atr_mult_2_25": {"void_atr_mult": 2.25},
            "retest_window_36": {"retest_window": 36},
            "retest_window_60": {"retest_window": 60},
        }
    if experiment_id == "EXP-ARP-003":
        return {
            "divergence_window_18": {"divergence_window": 18},
            "divergence_window_30": {"divergence_window": 30},
            "atr_period_10": {"atr_period": 10},
            "atr_period_20": {"atr_period": 20},
        }
    if experiment_id == "EXP-ARP-005":
        return {
            "stop_atr_mult_0_375": {"stop_atr_mult": 0.375},
            "stop_atr_mult_0_625": {"stop_atr_mult": 0.625},
            "atr_period_10": {"atr_period": 10},
            "atr_period_20": {"atr_period": 20},
        }
    raise KeyError(f"unknown experiment {experiment_id!r}")


@dataclass(frozen=True, slots=True)
class ExpandedVariant:
    variant: str
    params: dict[str, Any]


def expand_variants(experiment_id: str, base: dict[str, Any]) -> list[ExpandedVariant]:
    """Base plus each single-parameter perturbation (one factor at a time)."""
    out = [ExpandedVariant("base", dict(base))]
    for name, delta in robustness_variants(experiment_id).items():
        merged = dict(base)
        merged.update(delta)
        out.append(ExpandedVariant(name, merged))
    return out
