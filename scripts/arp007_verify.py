"""ARP-007 INDEPENDENT VERIFIER — EXP-ARP-008 from-scratch reproduction.

BUILDER != VERIFIER. This program was written by the independent verifier and does
NOT call the builder's driver or result parser. It reads the raw 1d shards directly,
re-implements the frozen EXP-ARP-008 contract from the SPEC text, re-derives the cost
model from the live CostEngine, and recomputes every reported surface:

DEV · VALIDATION · cost stress · 11 robustness perturbations · temporal · regime ·
concentration · long-bias · passive baselines · PIT.

Outputs a single JSON summary consumed by the §26 evidence files. Research-only; no
runtime authority, no Risk, no lifecycle, no promotion, no OOS read.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp007_verify.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.autonomous.costs import CostEngine  # noqa: E402
from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.regime import RegimeEngine  # noqa: E402

CORPUS = REPO / "reports/alpha-diversified-v1/data"
OUT = REPO / "reports/exp-arp-008-oos-verification"

MS_PER_DAY = 86_400_000
BPS = 10_000.0
NOTIONAL = 500.0

_2019 = 1_546_300_800_000
_2024 = 1_704_067_200_000
_2025_07 = 1_751_328_000_000
_2026_03 = 1_772_323_200_000
SPLITS: dict[str, tuple[int, int]] = {
    "DEV": (_2019, _2024),
    "VALIDATION": (_2024, _2025_07),
    "OOS_LOCK": (_2025_07, _2026_03),
}
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
LOOKBACK = 30
MAX_HOLD = 20


def cost_model_v3_rt_bps() -> float:
    return float(CostEngine().evaluate(size_usd=500.0, horizon_minutes=30.0).round_trip_bps)


def load_bars(symbol: str, start: int, end: int) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = json.loads((CORPUS / f"{symbol}.json").read_text(encoding="utf-8"))
    return [b for b in raw if start <= int(b["ts"]) < end]


def sim_exp008(
    bars: Sequence[dict[str, Any]], *, lookback: int, max_hold: int, cost_bps_rt: float,
    entry_delay: int = 0,
) -> list[dict[str, Any]]:
    """Independent reimplementation of the frozen long-only TSMOM contract.

    Signal on a closed bar i (close[i] > close[i-lookback]); act at the next open;
    exit on the next open after the signal turns false; a max-hold force-close at
    the close of the max_hold-th held bar; one position at a time; fixed notional.
    """
    n = len(bars)
    if n <= lookback + 1:
        return []
    closes = [float(b["close"]) for b in bars]
    fee = NOTIONAL * cost_bps_rt / BPS
    trades: list[dict[str, Any]] = []

    def sig(i: int) -> bool:
        return i >= lookback and closes[i] > closes[i - lookback]

    def emit(ei: int, epx: float, xi: int, xpx: float, ts: int, reason: str,
             peak: float, trough: float) -> None:
        gross = NOTIONAL * (xpx / epx - 1.0)
        trades.append({
            "entry_i": ei, "exit_i": xi, "entry_ts": int(bars[ei]["ts"]), "exit_ts": ts,
            "entry": epx, "exit": xpx, "reason": reason,
            "mfe_pct": (peak - epx) / epx * 100.0, "mae_pct": (epx - trough) / epx * 100.0,
            "gross": gross, "fees": fee, "net": gross - fee,
        })

    open_i: int | None = None
    open_px = 0.0
    peak = trough = 0.0
    pending_entry = False
    pending_due = 0
    pending_exit = False
    for i in range(n):
        bar = bars[i]
        op = float(bar["open"])
        if open_i is not None and pending_exit:
            emit(open_i, open_px, i, op, int(bar["ts"]), "signal_flip", peak, trough)
            open_i, pending_exit = None, False
        if open_i is None and pending_entry and i >= pending_due:
            open_i, open_px, peak, trough = i, op, op, op
            pending_entry = False
        if open_i is not None:
            peak = max(peak, float(bar["high"]))
            trough = min(trough, float(bar["low"]))
            if i - open_i >= max_hold:
                emit(open_i, open_px, i, float(bar["close"]), int(bar["ts"]),
                     "window_expiry", peak, trough)
                open_i, pending_exit = None, False
        if i >= n - 1:
            break
        if open_i is None and not pending_entry and sig(i):
            due = i + 1 + entry_delay
            if due <= n - 1:
                pending_entry, pending_due = True, due
        elif open_i is not None and not pending_exit and not sig(i):
            pending_exit = True
    if open_i is not None:
        emit(open_i, open_px, n - 1, float(bars[-1]["close"]), int(bars[-1]["ts"]),
             "window_expiry", peak, trough)
    return trades


def summarize(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "gross_usd": 0.0, "net_usd": 0.0, "expectancy_gross_bps": None,
                "expectancy_net_bps": None, "profit_factor": None, "win_rate": None,
                "payoff": None, "max_drawdown_bps": None, "avg_mfe_pct": None,
                "avg_mae_pct": None, "avg_hold_days": None}
    g = sum(t["gross"] for t in trades)
    net = sum(t["net"] for t in trades)
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    eq = peak = worst = 0.0
    for t in trades:
        eq += t["net"]
        peak = max(peak, eq)
        worst = max(worst, peak - eq)
    return {
        "trades": n,
        "gross_usd": round(g, 4),
        "net_usd": round(net, 4),
        "expectancy_gross_bps": round(g / n / NOTIONAL * BPS, 3),
        "expectancy_net_bps": round(net / n / NOTIONAL * BPS, 3),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        "win_rate": round(len(wins) / n, 4),
        "payoff": round(statistics.fmean(wins) / abs(statistics.fmean(losses)), 4)
        if wins and losses else None,
        "max_drawdown_bps": round(worst / NOTIONAL * BPS, 3),
        "avg_mfe_pct": round(statistics.fmean([t["mfe_pct"] for t in trades]), 4),
        "avg_mae_pct": round(statistics.fmean([t["mae_pct"] for t in trades]), 4),
        "avg_hold_days": round(statistics.fmean([t["exit_i"] - t["entry_i"] for t in trades]), 2),
    }


def run(split: str, *, cost: float, lookback: int = LOOKBACK, max_hold: int = MAX_HOLD,
        entry_delay: int = 0, assets: Sequence[str] = ASSETS) -> list[dict[str, Any]]:
    start, end = SPLITS[split]
    out: list[dict[str, Any]] = []
    for sym in assets:  # BTC, ETH, SOL order (matches the builder's ledger ordering)
        bars = load_bars(sym, start, end)
        for t in sim_exp008(bars, lookback=lookback, max_hold=max_hold, cost_bps_rt=cost,
                            entry_delay=entry_delay):
            t["symbol"] = sym
            out.append(t)
    return out


# ------------------------------------------------------------------ derived surfaces


def pnl_by_year(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    from datetime import UTC, datetime
    by: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        by[datetime.fromtimestamp(t["exit_ts"] / 1000, tz=UTC).year].append(t["net"])
    return {str(y): {"trades": len(v), "net_usd": round(sum(v), 2),
                     "expectancy_net_bps": round(sum(v) / len(v) / NOTIONAL * BPS, 3)}
            for y, v in sorted(by.items())}


def pnl_by_asset(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by[t["symbol"]].append(t["net"])
    return {s: {"trades": len(v), "net_usd": round(sum(v), 2),
                "expectancy_net_bps": round(sum(v) / len(v) / NOTIONAL * BPS, 3)}
            for s, v in sorted(by.items())}


def concentration(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    nets = [t["net"] for t in trades]
    pos = sorted((x for x in nets if x > 0), reverse=True)
    tot = sum(pos)
    if not pos or tot <= 0:
        return {}
    from datetime import UTC, datetime
    by_asset: dict[str, float] = defaultdict(float)
    by_year: dict[int, float] = defaultdict(float)
    for t in trades:
        if t["net"] > 0:
            by_asset[t["symbol"]] += t["net"]
            by_year[datetime.fromtimestamp(t["exit_ts"] / 1000, tz=UTC).year] += t["net"]
    return {
        "trades": len(trades),
        "top1_trade_share": round(pos[0] / tot, 4),
        "top5_trade_share": round(sum(pos[:5]) / tot, 4),
        "top_asset_share": round(max(by_asset.values()) / tot, 4),
        "top_asset": max(by_asset, key=lambda k: by_asset[k]),
        "distinct_assets": len(by_asset),
        "top_period_share": round(max(by_year.values()) / tot, 4),
        "top_period": max(by_year, key=lambda k: by_year[k]),
        "distinct_periods": len(by_year),
    }


def regime_labels(benchmark: Sequence[OHLCV], *, lookback: int = 60) -> dict[int, str]:
    engine = RegimeEngine()
    out: dict[int, str] = {}
    for i in range(len(benchmark)):
        if i + 1 < lookback:
            continue
        snap = engine.detect(list(benchmark[i + 1 - lookback: i + 1]))
        primary = snap.primary_regime or "UNKNOWN"
        if snap.is_active("BULL"):
            primary = "BULL"
        elif snap.is_active("BEAR"):
            primary = "BEAR"
        elif snap.is_active("HIGH_VOL"):
            primary = "HIGH_VOL"
        elif snap.is_active("LOW_VOL"):
            primary = "LOW_VOL"
        out[benchmark[i].timestamp] = primary
    return out


def to_ohlcv(bars: Sequence[dict[str, Any]]) -> list[OHLCV]:
    return [OHLCV(symbol="BTCUSDT", timestamp=int(b["ts"]), open=float(b["open"]),
                  high=float(b["high"]), low=float(b["low"]), close=float(b["close"]),
                  volume=float(b["volume"])) for b in bars]


def regime_pnl(trades: Sequence[dict[str, Any]], labels: dict[int, str]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        day = (t["entry_ts"] // MS_PER_DAY) * MS_PER_DAY
        buckets[labels.get(day, "UNKNOWN")].append(t["net"])
    return {r: {"trades": len(v), "net_usd": round(sum(v), 2),
                "expectancy_net_bps": round(sum(v) / len(v) / NOTIONAL * BPS, 3)}
            for r, v in sorted(buckets.items())}


def exposure(trades: Sequence[dict[str, Any]], total_bars: int) -> float:
    held = sum(t["exit_i"] - t["entry_i"] for t in trades)
    return round(held / total_bars, 4) if total_bars else 0.0


def buy_and_hold(symbol: str, start: int, end: int) -> dict[str, Any]:
    bars = load_bars(symbol, start, end)
    if len(bars) < 2:
        return {"symbol": symbol, "ret_bps": None, "max_dd_bps": None}
    entry = float(bars[0]["open"])
    closes = [float(b["close"]) for b in bars]
    eq = peak = worst = 0.0
    for c in closes:
        r = c / entry - 1.0
        eq = r
        peak = max(peak, eq)
        worst = max(worst, peak - eq)
    return {"symbol": symbol,
            "ret_bps": round((closes[-1] / entry - 1.0) * BPS, 2),
            "max_dd_bps": round(worst * BPS, 2)}


def corpus_audit() -> dict[str, Any]:
    """Independently re-derive the corpus manifest: digest, shas, completeness."""
    import hashlib
    shards = sorted(p for p in CORPUS.glob("*.json") if not p.name.startswith("_"))

    def sha(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()

    comb = hashlib.sha256()
    for p in shards:
        comb.update(sha(p).encode())
    man = json.loads((CORPUS / "_FETCH_MANIFEST.json").read_text(encoding="utf-8"))
    bad_sha = [s for s, m in man["symbols"].items() if sha(CORPUS / m["file"]) != m["sha256"]]
    bars = dup = misaligned = 0
    listings: dict[str, int] = {}
    for p in shards:
        raw = json.loads(p.read_text(encoding="utf-8"))
        ts = [int(b["ts"]) for b in raw]
        bars += len(ts)
        dup += len(ts) - len(set(ts))
        misaligned += sum(1 for t in ts if t % MS_PER_DAY != 0)
        listings[p.stem] = ts[0]
    return {
        "shards": len(shards), "bars": bars, "duplicate_bars": dup,
        "non_utc_aligned_ts": misaligned,
        "digest_recomputed": comb.hexdigest(),
        "digest_matches_manifest": comb.hexdigest() == man.get("corpus_digest"),
        "per_symbol_sha_mismatches": len(bad_sha),
        "listing_time_first": min(listings.values()),
        "listing_time_last": max(listings.values()),
        "traded_asset_listings": {s: listings.get(s) for s in ASSETS},
    }


def pit_audit() -> dict[str, Any]:
    """Prove data_time <= decision_time <= fill_time for every trade, per split."""
    violations: list[str] = []
    checks = 0
    for split in ("DEV", "VALIDATION"):
        start, end = SPLITS[split]
        for sym in ASSETS:
            bars = load_bars(sym, start, end)
            closes = [float(b["close"]) for b in bars]
            for t in sim_exp008(bars, lookback=LOOKBACK, max_hold=MAX_HOLD, cost_bps_rt=0.0):
                ei, xi = t["entry_i"], t["exit_i"]
                si = ei - 1  # signal bar for a next-open fill
                checks += 1
                if si < LOOKBACK or not (closes[si] > closes[si - LOOKBACK]):
                    violations.append(f"{split}/{sym} entry {ei}: no valid prior signal")
                if not (int(bars[ei]["ts"]) > int(bars[si]["ts"])):
                    violations.append(f"{split}/{sym} entry {ei}: fill not after signal")
                if float(t["entry"]) != float(bars[ei]["open"]):
                    violations.append(f"{split}/{sym} entry {ei}: entry price != open")
                if int(bars[xi]["ts"]) < int(bars[ei]["ts"]):
                    violations.append(f"{split}/{sym} exit {xi}: before entry")
                if t["reason"] == "signal_flip" and xi > 0 and closes[xi - 1] > closes[xi - 1 - LOOKBACK]:
                    violations.append(f"{split}/{sym} exit {xi}: signal still true")
    return {"trades_checked": checks, "violations": len(violations),
            "examples": violations[:5]}


def survivorship() -> dict[str, Any]:
    """§9: classify the delisted-market survivorship limitation for EXP-ARP-008."""
    man = json.loads((CORPUS / "_FETCH_MANIFEST.json").read_text(encoding="utf-8"))
    traded = {s: man["symbols"].get(s) for s in ASSETS}
    all_present = all(v is not None for v in traded.values())
    return {
        "traded_assets": list(ASSETS),
        "traded_assets_present_and_continuous": all_present,
        "corpus_limitation": man.get("survivorship_limitation"),
        "classification": "NOT_APPLICABLE",
        "reason": (
            "EXP-ARP-008 trades exactly BTCUSDT/ETHUSDT/SOLUSDT, none of which is a "
            "delisted market; the corpus' exchangeInfo survivorship gap therefore "
            "cannot remove or insert any traded episode. Residual caveat: the three "
            "names are survivors selected a priori in the frozen SPEC, so a "
            "condition on survival is acknowledged but is not a data-driven bias."
        ),
        "traded_asset_listing_times": {s: (traded[s] or {}).get("listing_time") for s in ASSETS},
    }


def ema(values: Sequence[float], span: int) -> list[float]:
    k = 2.0 / (span + 1.0)
    out: list[float] = []
    prev = values[0]
    for v in values:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def trend_baseline(split_start: int, split_end: int, *, cost: float) -> dict[str, Any]:
    """Existing trend-family proxy at the daily horizon: long while EMA20 > EMA50,
    next-open fills, same cost. NOT a declared experiment — a reference baseline."""
    all_trades: list[dict[str, Any]] = []
    for sym in ASSETS:
        bars = load_bars(sym, split_start, split_end)
        closes = [float(b["close"]) for b in bars]
        if len(bars) < 51:
            continue
        f, s = ema(closes, 20), ema(closes, 50)
        fee = NOTIONAL * cost / BPS
        open_i: int | None = None
        open_px = 0.0
        pending_in = pending_out = False

        def add(ei: int, xi: int, g: float, fee_usd: float, symbol: str) -> None:
            all_trades.append({"entry_i": ei, "exit_i": xi, "gross": g, "net": g - fee_usd,
                               "mfe_pct": 0.0, "mae_pct": 0.0, "symbol": symbol})

        for i in range(len(bars)):
            op = float(bars[i]["open"])
            if open_i is not None and pending_out:
                add(open_i, i, NOTIONAL * (op / open_px - 1.0), fee, sym)
                open_i, pending_out = None, False
            if open_i is None and pending_in:
                open_i, open_px, pending_in = i, op, False
            if i >= len(bars) - 1:
                break
            want = f[i] > s[i]
            if want and open_i is None:
                pending_in = True
            elif not want and open_i is not None:
                pending_out = True
        if open_i is not None:
            add(open_i, len(bars) - 1,
                NOTIONAL * (float(bars[-1]["close"]) / open_px - 1.0), fee, sym)
    return summarize(all_trades)


def recompute_code_hash() -> dict[str, Any]:
    import hashlib
    files = (
        "src/trading_bot/research/diversified/__init__.py",
        "src/trading_bot/research/diversified/data.py",
        "src/trading_bot/research/diversified/universe.py",
        "src/trading_bot/research/diversified/daily.py",
        "src/trading_bot/research/diversified/xsec.py",
        "src/trading_bot/research/diversified/analytics.py",
        "src/trading_bot/research/alpha_expansion/xsec.py",
        "src/trading_bot/research/alpha_expansion/strategies.py",
        "src/trading_bot/research/alpha_recovery/metrics.py",
        "scripts/alpha_diversified_v1.py",
    )
    h = hashlib.sha256()
    for rel in files:
        p = REPO / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    return {"code_hash": h.hexdigest(), "files": len(files)}


def main() -> None:
    cost = cost_model_v3_rt_bps()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tmp").mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"verifier": "ARP-007", "cost_bps_rt": cost,
                              "cost_model": "COST_MODEL_V3"}

    dev_tr = run("DEV", cost=cost)
    val_tr = run("VALIDATION", cost=cost)
    report["DEV"] = summarize(dev_tr)
    report["VALIDATION"] = summarize(val_tr)
    report["DEV"]["concentration"] = concentration(dev_tr)
    report["VALIDATION"]["concentration"] = concentration(val_tr)

    # cost stress: gross expectation minus m * cost (cost scales linearly on notional)
    gross_dev = report["DEV"]["expectancy_gross_bps"]
    report["cost_stress"] = {
        f"{m}x": {"cost_bps_rt": round(cost * m, 4),
                  "expectancy_net_bps": round(gross_dev - cost * m, 4),
                  "positive": gross_dev - cost * m > 0}
        for m in (0.5, 1.0, 1.25, 1.5, 2.0)
    }

    # robustness: 11 perturbations, each on VALIDATION (per the builder's harness)
    rob: dict[str, Any] = {}
    rob["lookback_24"] = summarize(run("VALIDATION", cost=cost, lookback=24))
    rob["lookback_40"] = summarize(run("VALIDATION", cost=cost, lookback=40))
    rob["hold_12"] = summarize(run("VALIDATION", cost=cost, max_hold=12))
    rob["hold_28"] = summarize(run("VALIDATION", cost=cost, max_hold=28))
    rob["execution_delay_1d"] = summarize(run("VALIDATION", cost=cost, entry_delay=1))
    for m in (1.25, 1.5, 2.0):
        rob[f"cost_{m}x"] = summarize(run("VALIDATION", cost=cost * m))
    for sym in ASSETS:
        rob[f"asset_{sym}"] = summarize(run("VALIDATION", cost=cost, assets=(sym,)))
    positives = [v["expectancy_net_bps"] for v in rob.values()
                 if v["expectancy_net_bps"] is not None]
    report["robustness"] = rob
    report["robustness_summary"] = {
        "perturbations": len(positives),
        "positive": sum(1 for v in positives if v > 0),
        "all_positive": all(v > 0 for v in positives),
    }

    # DEV+VALIDATION full window surfaces (contiguous 2019-01-01..2025-07-01, the
    # builder's own basis: no warm-up reset at the internal DEV/VALIDATION boundary)
    full: list[dict[str, Any]] = []
    for sym in ASSETS:
        for t in sim_exp008(load_bars(sym, _2019, _2025_07), lookback=LOOKBACK,
                            max_hold=MAX_HOLD, cost_bps_rt=cost):
            t["symbol"] = sym
            full.append(t)
    report["temporal"] = pnl_by_year(full)
    report["by_asset"] = pnl_by_asset(full)
    report["concentration_full"] = concentration(full)
    bench = to_ohlcv(load_bars("BTCUSDT", _2019, _2025_07))
    labels = regime_labels(bench)
    report["regime"] = regime_pnl(full, labels)
    report["regime_sample_warning"] = [
        r for r, v in report["regime"].items() if v["trades"] < 10
    ]

    # exposure / long-bias
    report["exposure"] = {
        "DEV": exposure(dev_tr, sum(len(load_bars(s, _2019, _2024)) for s in ASSETS)),
        "VALIDATION": exposure(val_tr, sum(len(load_bars(s, _2024, _2025_07)) for s in ASSETS)),
    }

    # baselines over DEV+VALIDATION (identical span)
    report["baselines"] = {
        "NO_TRADE": {"ret_bps": 0.0, "exposure": 0.0},
        "buy_and_hold": {s: buy_and_hold(s, _2019, _2025_07) for s in ASSETS},
        "strategy_net_usd": round(sum(t["net"] for t in full), 2),
        "strategy_trades": len(full),
        "strategy_exposure": round(
            sum(t["exit_i"] - t["entry_i"] for t in full)
            / sum(len(load_bars(s, _2019, _2025_07)) for s in ASSETS), 4),
    }

    # §14 long-bias + §15 baselines (reference only; no subjective winner)
    report["long_bias"] = {
        "exposure_full": report["baselines"]["strategy_exposure"],
        "direction": "LONG_OR_FLAT_ONLY (no short capability, frozen)",
        "regime_expectancy_bps": {r: v["expectancy_net_bps"] for r, v in report["regime"].items()},
        "bull_share_of_positive_net": round(
            report["regime"].get("BULL", {}).get("net_usd", 0.0)
            / max(1.0, sum(max(0.0, v["net_usd"]) for v in report["regime"].values())), 4),
    }
    report["baselines"]["trend_ema20_50"] = trend_baseline(_2019, _2025_07, cost=cost)
    report["code_hash_recomputed"] = recompute_code_hash()

    # §3 corpus / §8 PIT / §9 survivorship
    report["corpus"] = corpus_audit()
    report["pit"] = pit_audit()
    report["survivorship"] = survivorship()

    # §5 cross-check the builder's own RESULTS.json (read-only; the verifier does
    # NOT use it to compute anything)
    builder = json.loads((REPO / "reports/alpha-diversified-v1/RESULTS.json").read_text(encoding="utf-8"))
    b8 = builder["experiments"]["EXP-ARP-008"]
    report["cross_check"] = {
        "DEV_match": b8["DEV"]["trades"] == report["DEV"]["trades"]
        and b8["DEV"]["expectancy_gross_bps"] == report["DEV"]["expectancy_gross_bps"]
        and b8["DEV"]["expectancy_net_bps"] == report["DEV"]["expectancy_net_bps"]
        and b8["DEV"]["profit_factor"] == report["DEV"]["profit_factor"],
        "VALIDATION_match": b8["VALIDATION"]["expectancy_net_bps"] == report["VALIDATION"]["expectancy_net_bps"]
        and b8["VALIDATION"]["trades"] == report["VALIDATION"]["trades"],
        "builder_code_hash": builder["code_hash"],
        "builder_cost_bps_rt": builder["cost_bps_rt"],
    }

    (OUT / "tmp/independent_verify.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({"DEV": report["DEV"], "VALIDATION": report["VALIDATION"],
                      "robustness_summary": report["robustness_summary"],
                      "concentration_full": report["concentration_full"]},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
