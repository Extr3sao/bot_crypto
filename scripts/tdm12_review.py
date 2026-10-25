"""WP-TDM-12A — independent review of the WP-TDM-11 evidence package.

Third implementation of the rule, written against the sealed bars rather than
against the TDM-11 scripts. It answers five questions and records the answers
instead of assuming them:

R-01  is the working tree the committed one, and is the shared checkout intact?
R-02  does every hash in the TDM-11 manifest resolve to a **committed blob**?
R-03  does the committed ledger re-derive from the raw bars, row by row?
R-04  are the 115 trades independent enough for the reported interval, and what
      happens to the interval under day-clustered resampling?
R-05  does the look-ahead control reproduce (~+17 bps), and the 3/6 directional
      claim?

No confirmatory bar is read: the loader refuses any timestamp at or after the
TDM-11 cutoff.

Usage::  python scripts/tdm12_review.py
Writes ``.tdm12/review.json`` and ``.tdm12/review.log``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ART = REPO_ROOT / ".tdm12"
TDM11 = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"
DEV_DIR = REPO_ROOT / "data" / "tdm10"
HOLD_DIR = REPO_ROOT / "data" / "tdm08"
SHARED = REPO_ROOT.parent / "bot freebuff"

CUTOFF_MS = 1_792_857_600_000
DEV_START_MS = 1_782_345_600_000
DEV_END_MS = 1_790_294_400_000
HOLD_END_MS = 1_792_857_524_550
HORIZON_BARS = 6
WINDOW = 100
COST_BPS = 23.7906
TIMEFRAMES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
ASSETS = ("BTC", "ETH", "SOL")
FAMILIES = ("ema_crossover", "momentum", "breakout", "trend", "mean_reversion", "volatility")
FAMILY_MODULES = {
    "ema_crossover": ("ema_crossover_family", "EmaCrossoverFamily"),
    "momentum": ("momentum_family", "MomentumFamily"),
    "breakout": ("breakout_family", "BreakoutFamily"),
    "trend": ("trend_family", "TrendFamily"),
    "mean_reversion": ("mean_reversion_family", "MeanReversionFamily"),
    "volatility": ("volatility_family", "VolatilityFamily"),
}
SEED = 20261025


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def blob_sha(path_in_repo: str, rev: str = "HEAD") -> str | None:
    proc = subprocess.run(
        ["git", "cat-file", "-p", f"{rev}:{path_in_repo}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


# ---------------------------------------------------------------------------
# rule, third implementation
# ---------------------------------------------------------------------------


def bars(path: Path) -> list[list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [[float(v) for v in row] for row in payload["rows"]]
    if rows and rows[-1][0] >= CUTOFF_MS:
        raise SystemExit("refusing to run: confirmatory bar present in dataset")
    return rows


def zscore(closes: list[float]) -> list[float]:
    n = len(closes)
    out = [0.0] * n
    lr = [0.0] + [
        math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0 for i in range(1, n)
    ]
    for i in range(199, n):
        window = lr[i - 198 : i + 1]
        mean = sum(window) / 199
        var = sum((x - mean) ** 2 for x in window) / 199
        if var <= 0:
            continue
        out[i] = sum(window) / (math.sqrt(var) * math.sqrt(200))
    return out


def is_down(z: float, i: int) -> bool:
    return i >= 199 and z != 0.0 and z < -1.5


def atr_pct(series: list[list[float]], period: int = 14) -> list[float]:
    out = [0.0] * len(series)
    for i in range(1, len(series)):
        lo = max(1, i - period + 1)
        trs = []
        for k in range(lo, i + 1):
            high, low, prev = series[k][2], series[k][3], series[k - 1][4]
            trs.append(max(high - low, abs(high - prev), abs(low - prev)))
        close = series[i][4]
        out[i] = (sum(trs) / len(trs)) / close * 10_000.0 if close > 0 else 0.0
    return out


def rolling_median(values: list[float], window: int = 500) -> list[float]:
    import bisect

    out = [0.0] * len(values)
    buf: list[float] = []
    for i, v in enumerate(values):
        bisect.insort(buf, v)
        if i >= window:
            del buf[bisect.bisect_left(buf, values[i - window])]
        out[i] = buf[len(buf) // 2]
    return out


def momentum_signals(series: list[list[float]]) -> dict[int, str]:
    from trading_bot.research.families.momentum_family import MomentumFamily

    family = MomentumFamily()
    from trading_bot.market_data.types import OHLCV

    out: dict[int, str] = {}
    for i in range(WINDOW - 1, len(series)):
        chunk = series[i - WINDOW + 1 : i + 1]
        candles = [
            OHLCV(
                symbol="X",
                timestamp=int(r[0]),
                open=r[1],
                high=r[2],
                low=r[3],
                close=r[4],
                volume=r[5],
            )
            for r in chunk
        ]
        try:
            alphas = family.generate(candles, {}, None)
        except Exception:
            continue
        if not alphas:
            continue
        best = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
        direction = str(getattr(best, "direction", "")).upper()
        if direction in ("LONG", "SHORT"):
            out[i] = direction
    return out


def derive_ledger(
    *, shorts_only: bool = True, lookahead: int = 0, same_bar: bool = False
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        series = bars(DEV_DIR / f"{asset}_5m.json")
        z = zscore([r[4] for r in series])
        signals = momentum_signals(series)
        last_exit = -1
        for i in sorted(signals):
            direction = signals[i]
            if shorts_only and direction != "SHORT":
                continue
            j = i + lookahead
            if j >= len(series) or not is_down(z[j], j):
                continue
            entry_i = i if same_bar else i + 1
            exit_i = entry_i + HORIZON_BARS
            if exit_i >= len(series) or entry_i <= last_exit:
                continue
            decision_ms = int(series[i][0])
            if not (DEV_START_MS <= decision_ms < DEV_END_MS):
                continue
            entry = series[entry_i][4] if same_bar else series[entry_i][1]
            if entry <= 0:
                continue
            sign = 1.0 if direction == "LONG" else -1.0
            rows.append(
                {
                    "asset": asset,
                    "decision_ms": decision_ms,
                    "entry_ms": int(series[entry_i][0]),
                    "exit_ms": int(series[exit_i][0]),
                    "direction": direction,
                    "gross_bps": sign * (series[exit_i][4] / entry - 1.0) * 10_000.0,
                }
            )
            last_exit = exit_i
    rows.sort(key=lambda r: (r["decision_ms"], r["asset"]))
    return rows


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def day_key(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def clustered_bootstrap(
    rows: list[dict[str, Any]], *, block_days: float, resamples: int = 4000
) -> dict[str, float]:
    """Resample contiguous day-blocks; every trade inside a day moves together."""
    import numpy as np

    days: dict[str, list[float]] = {}
    for row in rows:
        days.setdefault(day_key(int(row["decision_ms"])), []).append(float(row["gross_bps"]))
    keys = sorted(days)
    if len(keys) < 2:
        return {"se": float("nan"), "lo": float("nan"), "hi": float("nan")}
    rng = np.random.default_rng(SEED)
    block = max(1, round(block_days))
    n_blocks = math.ceil(len(keys) / block)
    means = np.empty(resamples, dtype=np.float64)
    for r in range(resamples):
        starts = rng.integers(0, len(keys), size=n_blocks)
        picked: list[str] = []
        for s in starts:
            picked.extend(keys[(s + k) % len(keys)] for k in range(block))
        values = [v for d in picked for v in days[d]]
        means[r] = float(np.mean(values)) if values else float("nan")
    ordered = np.sort(means)
    return {
        "se": float(means.std(ddof=1)),
        "lo": float(ordered[int(0.025 * means.size)]),
        "hi": float(ordered[int(0.975 * means.size)]),
        "days": len(keys),
    }


def overlap_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    spans = sorted((int(r["entry_ms"]), int(r["exit_ms"]), r["asset"]) for r in rows)
    overlapping = 0
    for idx, (_start, end, asset) in enumerate(spans):
        for other_start, _other_end, other_asset in spans[idx + 1 :]:
            if other_start >= end:
                break
            if other_asset != asset:
                overlapping += 1
                break
    per_day: dict[str, int] = {}
    for row in rows:
        key = day_key(int(row["decision_ms"]))
        per_day[key] = per_day.get(key, 0) + 1
    return {
        "trades_with_concurrent_other_asset": overlapping,
        "share": round(overlapping / len(rows), 4) if rows else None,
        "active_days": len(per_day),
        "max_trades_per_day": max(per_day.values()) if per_day else 0,
        "mean_trades_per_active_day": round(len(rows) / len(per_day), 3) if per_day else None,
    }


# ---------------------------------------------------------------------------
# R-05: directional claim, recomputed independently
# ---------------------------------------------------------------------------


def hold_trades() -> dict[str, list[dict[str, Any]]]:
    """One pass over the holdout: every cell's trades, with direction and trend."""
    from trading_bot.market_data.types import OHLCV

    per_cell: dict[str, list[dict[str, Any]]] = {}
    for tf, minutes in TIMEFRAMES.items():
        horizon = max(1, round(30 / minutes))
        for asset in ASSETS:
            series = bars(HOLD_DIR / f"{asset}_{tf}.json")
            z = zscore([r[4] for r in series])
            atr = atr_pct(series)
            med = rolling_median(atr)
            for family_name in FAMILIES:
                module_name, class_name = FAMILY_MODULES[family_name]
                module = __import__(
                    f"trading_bot.research.families.{module_name}", fromlist=[class_name]
                )
                family = getattr(module, class_name)()
                cell = f"{family_name}@{tf}"
                last_exit = -1
                for i in range(WINDOW - 1, len(series)):
                    try:
                        alphas = family.generate(
                            [
                                OHLCV(
                                    symbol="X",
                                    timestamp=int(r[0]),
                                    open=r[1],
                                    high=r[2],
                                    low=r[3],
                                    close=r[4],
                                    volume=r[5],
                                )
                                for r in series[i - WINDOW + 1 : i + 1]
                            ],
                            {},
                            None,
                        )
                    except Exception:
                        continue
                    if not alphas:
                        continue
                    best = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
                    direction = str(getattr(best, "direction", "")).upper()
                    if direction not in ("LONG", "SHORT"):
                        continue
                    decision_ms = int(series[i][0])
                    if not (DEV_END_MS <= decision_ms < HOLD_END_MS):
                        continue
                    exit_i = i + horizon
                    if exit_i >= len(series) or i <= last_exit:
                        continue
                    if int(series[exit_i][0]) >= HOLD_END_MS:
                        continue
                    entry = float(getattr(best, "entry_reference", 0.0) or 0.0) or series[i][4]
                    sign = 1.0 if direction == "LONG" else -1.0
                    vol = "unclassified"
                    if (
                        (is_down(z[i], i) or (i >= 199 and z[i] != 0.0))
                        and med[i] > 0
                        and atr[i] > 0
                    ):
                        vol = "high_vol" if atr[i] / med[i] > 1.3 else "low_vol"
                    per_cell.setdefault(cell, []).append(
                        {
                            "asset": asset,
                            "direction": direction,
                            "trend": (
                                "down"
                                if is_down(z[i], i)
                                else "up"
                                if (i >= 199 and z[i] > 1.5)
                                else "flat"
                                if (i >= 199 and z[i] != 0.0)
                                else "unclassified"
                            ),
                            "vol": vol,
                            "gross_bps": sign * (series[exit_i][4] / entry - 1.0) * 10_000.0,
                        }
                    )
                    last_exit = exit_i
    return per_cell


def _bucket(trades: list[dict[str, Any]], key: str, value: str) -> list[dict[str, Any]]:
    return [t for t in trades if t[key] == value]


def claim_check(per_cell: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Rank the best *pooled-direction* regime buckets under two slicings.

    The historical sentence ("5 of 6 best buckets are the short side in
    downtrends") does not say which ranking produced the six. Both are computed
    here, because the answer depends on it and that dependence is the finding.
    """
    if per_cell is None:
        per_cell = hold_trades()

    down_buckets: list[dict[str, Any]] = []
    mixed_buckets: list[dict[str, Any]] = []
    for cell, trades in per_cell.items():
        for axis, labels in (
            ("trend", ("down", "up", "flat", "unclassified")),
            ("vol", ("high_vol", "low_vol", "unclassified")),
        ):
            for label in labels:
                bucket = _bucket(trades, axis, label)
                if len(bucket) < 4:
                    continue
                record = {
                    "cell": cell,
                    "axis": axis,
                    "label": label,
                    "n": len(bucket),
                    "gross": round(statistics.fmean([t["gross_bps"] for t in bucket]), 4),
                    "short_share": round(
                        sum(1 for t in bucket if t["direction"] == "SHORT") / len(bucket), 3
                    ),
                }
                mixed_buckets.append(record)
                if axis == "trend" and label == "down":
                    down_buckets.append(record)

    down_top = sorted(down_buckets, key=lambda b: b["gross"], reverse=True)[:6]
    mixed_top = sorted(mixed_buckets, key=lambda b: b["gross"], reverse=True)[:6]
    return {
        "cells": len(per_cell),
        "hold_trades": sum(len(v) for v in per_cell.values()),
        "slicing_a_down_only": {
            "definition": "rank only trend=down buckets, n>=4, pooled directions",
            "top6": down_top,
            "short_majority_count": sum(1 for b in down_top if b["short_share"] > 0.5),
        },
        "slicing_b_mixed_axis": {
            "definition": "rank every regime bucket (trend and vol), n>=4, pooled directions",
            "top6": mixed_top,
            "short_in_downtrend_count": sum(
                1
                for b in mixed_top
                if b["axis"] == "trend" and b["label"] == "down" and b["short_share"] > 0.5
            ),
        },
        "slicing_dependent": (
            sum(1 for b in down_top if b["short_share"] > 0.5)
            != sum(
                1
                for b in mixed_top
                if b["axis"] == "trend" and b["label"] == "down" and b["short_share"] > 0.5
            )
        ),
    }


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--claim-only",
        action="store_true",
        help="recompute only the directional claim and merge it into review.json",
    )
    args = parser.parse_args(argv)
    ART.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if args.claim_only:
        payload = json.loads((ART / "review.json").read_text(encoding="utf-8"))
        payload["claim"] = claim_check()
        payload["claim_recomputed_at_ms"] = int(time.time() * 1000)
        (ART / "review.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload["claim"], indent=1))
        return 0
    out: dict[str, Any] = {"generated_at_ms": int(time.time() * 1000)}

    # R-01 preflight
    dirty = [
        line[3:] for line in git("status", "--porcelain").splitlines() if not line.startswith("??")
    ]
    shared_dirty = [
        line[3:]
        for line in git("status", "--porcelain", cwd=SHARED).splitlines()
        if not line.startswith("??")
    ]
    out["preflight"] = {
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "worktree": str(REPO_ROOT),
        "tracked_dirty": dirty,
        "worktree_clean": not dirty,
        "shared_head": git("rev-parse", "HEAD", cwd=SHARED),
        "shared_tracked_dirty_count": len(shared_dirty),
        "shared_files": shared_dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    print(f"R-01 preflight clean={not dirty} shared_dirty={len(shared_dirty)}", flush=True)

    # R-02 hashes against committed blobs
    run = json.loads((TDM11 / "RUN_REPORT.json").read_text(encoding="utf-8"))
    mismatched: list[str] = []
    missing: list[str] = []
    for name, meta in run["evidence_sha256"].items():
        blob = blob_sha(meta["path"])
        if blob is None:
            missing.append(name)
        elif blob != meta["sha256"]:
            mismatched.append(name)
    code_bad: list[str] = []
    for name, meta in run["code_sha256"].items():
        blob = blob_sha(f"scripts/{name}")
        if blob != meta["sha256"]:
            code_bad.append(name)
    out["provenance"] = {
        "evidence_checked": len(run["evidence_sha256"]),
        "evidence_missing": missing,
        "evidence_mismatched": mismatched,
        "code_checked": len(run["code_sha256"]),
        "code_mismatched": code_bad,
        "manifest_self_reference": "RUN_REPORT.json is excluded from its own map (no circular hash)",
        "prereg_sha_in_manifest": run["preregistration_sha256"],
    }
    print(f"R-02 provenance missing={missing} mismatched={mismatched}", flush=True)

    # R-03 ledger re-derivation
    derived = derive_ledger()
    committed = list(csv.DictReader((TDM11 / "RETROSPECTIVE_LEDGER.csv").open(encoding="utf-8")))
    row_problems: list[str] = []
    if len(derived) != len(committed):
        row_problems.append(f"count {len(derived)} != {len(committed)}")
    for mine, theirs in zip(derived, committed, strict=False):
        if (
            int(theirs["decision_ms"]) != mine["decision_ms"]
            or theirs["asset"] != mine["asset"]
            or theirs["direction"] != mine["direction"]
        ):
            row_problems.append(f"identity mismatch at {mine['decision_ms']}")
            continue
        if not math.isclose(float(theirs["gross_bps"]), mine["gross_bps"], abs_tol=1e-3):
            row_problems.append(f"gross mismatch at {mine['decision_ms']}")
    gross = [r["gross_bps"] for r in derived]
    net = [g - COST_BPS for g in gross]
    out["ledger"] = {
        "derived_trades": len(derived),
        "committed_trades": len(committed),
        "problems": row_problems[:10],
        "problem_count": len(row_problems),
        "gross_mean": round(statistics.fmean(gross), 4) if gross else None,
        "gross_sd": round(statistics.stdev(gross), 4) if len(gross) > 1 else None,
        "net_mean": round(statistics.fmean(net), 4) if net else None,
        "reproduced": not row_problems,
    }
    print(f"R-03 ledger derived={len(derived)} problems={len(row_problems)}", flush=True)

    # R-04 dependence and interval sensitivity
    by_day = clustered_bootstrap(derived, block_days=1)
    sensitivity = {
        f"{bd}d": {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in clustered_bootstrap(derived, block_days=bd).items()
        }
        for bd in (1, 2, 5, 10)
    }
    per_asset: dict[str, Any] = {}
    for asset in ASSETS:
        sub = [r["gross_bps"] for r in derived if r["asset"] == asset]
        if sub:
            per_asset[asset] = {
                "trades": len(sub),
                "gross_mean": round(statistics.fmean(sub), 4),
                "share": round(len(sub) / len(derived), 3),
            }
    out["dependence"] = {
        "overlap": overlap_stats(derived),
        "day_clustered_ci95_gross": {
            "lo": round(by_day["lo"], 4),
            "hi": round(by_day["hi"], 4),
            "se": round(by_day["se"], 4),
            "day_clusters": by_day["days"],
        },
        "block_sensitivity_days": sensitivity,
        "per_asset": per_asset,
        "net_upper_bound_by_method": {
            f"{k}": round(v["hi"] - COST_BPS, 4) for k, v in sensitivity.items()
        },
    }
    print(f"R-04 clustered gross CI hi={by_day['hi']:.3f}", flush=True)

    # R-05 controls and the directional claim
    look = derive_ledger(lookahead=12)
    same = derive_ledger(same_bar=True)
    out["controls"] = {
        "pit_trades": len(derived),
        "pit_gross_mean": round(statistics.fmean(gross), 4),
        "lookahead_trades": len(look),
        "lookahead_gross_mean": round(statistics.fmean([r["gross_bps"] for r in look]), 4)
        if look
        else None,
        "same_bar_trades": len(same),
        "same_bar_gross_mean": round(statistics.fmean([r["gross_bps"] for r in same]), 4)
        if same
        else None,
    }
    out["controls"]["lookahead_advantage_bps"] = round(
        (out["controls"]["lookahead_gross_mean"] or 0.0)
        - (out["controls"]["pit_gross_mean"] or 0.0),
        4,
    )
    print(f"R-05 lookahead mean={out['controls']['lookahead_gross_mean']}", flush=True)

    try:
        claim = claim_check()
    except Exception as exc:  # a failure is a finding, not a crash
        claim = {"error": f"{type(exc).__name__}: {exc}", "claim_3_of_6_reproduced": None}
    out["claim"] = claim
    print(f"R-05 claim 3/6 reproduced={claim.get('claim_3_of_6_reproduced')}", flush=True)

    out["independence"] = {
        "reviewer": "same operator, third implementation",
        "status": "INDEPENDENCE_NOT_DEMONSTRATED",
        "detail": (
            "the review is a separate implementation and a separate execution context, but not a "
            "separate author; no third-party actor is available in this workspace"
        ),
    }
    out["elapsed_s"] = round(time.time() - started, 1)
    (ART / "review.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote review.json in {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
