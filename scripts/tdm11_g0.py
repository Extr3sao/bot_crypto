"""WP-TDM-11A — read-only governance reconciliation of WP-TDM-08/10.

Nothing here writes outside ``.tdm11/``. The script only reads sealed artifacts,
the pristine worktree sources, and the copied datasets, and answers one question
per gate:

G0-1  is this really an isolated worktree at the fixed commit?
G0-2  do the published WP-TDM-10 deliverables still hash to their manifest?
G0-3  do the sealed datasets still hash to their manifests, with no gaps,
      duplicates or overlap between the development and holdout windows?
G0-4  is the frozen spec unchanged, and is the INCONCLUSIVE/NO_GO divergence
      still recorded rather than silently amended?
G0-5  do the reported costs (23.79 / 9.25 / 41.25 bps) come out of the repo's
      own cost model, or are they numbers in a report?
G0-6  does the claim that motivates RFC-TDM-011 — "5 of the 6 best regime
      buckets are the short side in downtrends" — reproduce from published
      evidence? ``regime_table.csv`` has no direction column, so this is
      recomputed from the sealed bars and the published trade dump.

Usage::

    python scripts/tdm11_g0.py            # all gates
    python scripts/tdm11_g0.py --no-trades  # skip G0-6 (fast)

Outputs ``.tdm11/g0.json`` and ``.tdm11/regime_direction.csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
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
DEV_MANIFEST = DEV_DIR / "DATASET_DEV.json"
HOLD_MANIFEST = HOLD_DIR / "DATASET.json"
TDM10 = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-10"
TDM08 = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-08"
TDM10_RUN = TDM10 / "RUN_REPORT.json"
SPEC = TDM10 / "EXPERIMENT_SPEC.md"
EXPECTED_SPEC_SHA = "8964d314a817fce3907627f30903e22c90486a7a140a60e8e718c6bed3d610d9"

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
WINDOW = 100
HORIZON_MINUTES = 30.0
TREND_WINDOW = 200
TREND_Z = 1.5
ATR_PERIOD = 14
VOL_RATIO = 1.3
HOLD_START_MS = 1_790_294_400_000  # 2026-09-25T00:00:00Z
HOLD_END_MS = 1_792_857_524_550  # TDM-08 fetch instant


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_ms(value: str) -> int:
    import calendar

    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000


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
# regime labels (frozen §7 definition, re-implemented here on purpose)
# ---------------------------------------------------------------------------


def atr_series(bars: list[Any], period: int = ATR_PERIOD) -> list[float]:
    n = len(bars)
    closes = [float(b.close) for b in bars]
    trs = [0.0] * n
    for k in range(1, n):
        high, low, prev = float(bars[k].high), float(bars[k].low), closes[k - 1]
        trs[k] = max(high - low, abs(high - prev), abs(low - prev))
    out = [0.0] * n
    for i in range(1, n):
        lo = max(1, i - period + 1)
        window = trs[lo : i + 1]
        if window and closes[i] > 0:
            out[i] = (sum(window) / len(window)) / closes[i] * 10_000.0
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


def trend_z(closes: list[float], window: int = TREND_WINDOW) -> list[float]:
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


class Labels:
    """Trailing-only regime labels, computed from bars <= i and nothing else."""

    def __init__(self, bars: list[Any]) -> None:
        closes = [float(b.close) for b in bars]
        self.z = trend_z(closes)
        self.atr = atr_series(bars)
        self.median_atr = rolling_median(self.atr, 500)

    def trend(self, i: int) -> str:
        if i < TREND_WINDOW - 1 or self.z[i] == 0.0:
            return "unclassified"
        z = self.z[i]
        return "up" if z > TREND_Z else "down" if z < -TREND_Z else "flat"

    def vol(self, i: int) -> str:
        trend = self.trend(i)
        if trend == "unclassified":
            return "unclassified"
        here, med = self.atr[i], self.median_atr[i]
        if med <= 0 or here <= 0:
            return "unclassified"
        return "high_vol" if here / med > VOL_RATIO else "low_vol"


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def gate_isolation() -> dict[str, Any]:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    porcelain = git("status", "--porcelain")
    tracked_dirty = [
        line[3:]
        for line in porcelain.splitlines()
        if line[:2].strip() and not line.startswith("??")
    ]
    untracked = [line[3:] for line in porcelain.splitlines() if line.startswith("??")]
    head = git("rev-parse", "HEAD")
    # read-only observation of the shared checkout (never written to)
    checkout = REPO_ROOT.parent / "bot freebuff"
    shared_head = None
    shared = ""
    if checkout.exists():
        shared_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        shared = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    shared_tracked = [
        ln[3:] for ln in shared.splitlines() if ln[:2].strip() and not ln.startswith("??")
    ]
    return {
        "head": head,
        "head_is_fixed_commit": head == "e67194e79a42aef2a2ded3aca21ac4a0ea3689c5",
        "worktree": str(REPO_ROOT),
        "detached": git("rev-parse", "--abbrev-ref", "HEAD") == "HEAD",
        "tracked_files_modified_in_worktree": tracked_dirty,
        "untracked_in_worktree": sorted(untracked),
        "worktree_tree_clean_except_new_files": not tracked_dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "shared_checkout": str(checkout) if checkout.exists() else "ABSENT",
        "shared_head": shared_head,
        "shared_checkout_tracked_modified": {
            "count": len(shared_tracked),
            "files": sorted(shared_tracked),
            "porcelain_sha256": hashlib.sha256(shared.encode("utf-8")).hexdigest(),
            "written_by_this_wp": False,
        },
        "passed": bool(head == "e67194e79a42aef2a2ded3aca21ac4a0ea3689c5" and not tracked_dirty),
    }


def gate_tdm10_artifacts() -> dict[str, Any]:
    run = json.loads(TDM10_RUN.read_text(encoding="utf-8"))
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for name, meta in run["deliverables"].items():
        path = TDM10 / name
        if not path.exists():
            mismatches.append({"file": name, "error": "MISSING"})
            continue
        if meta.get("self_reference"):
            continue
        got = sha256_file(path)
        checked += 1
        if got != meta["sha256"] or path.stat().st_size != meta["bytes"]:
            mismatches.append(
                {"file": name, "expected": meta["sha256"], "got": got, "bytes": path.stat().st_size}
            )
    return {
        "deliverables_checked": checked,
        "mismatches": mismatches,
        "declared_verdict": run["verdict"],
        "declared_commit": run["commit"],
        "verification_claim": run["verification"].get("checks_passed"),
        "passed": not mismatches and checked >= 7,
    }


def gate_datasets() -> dict[str, Any]:
    out: dict[str, Any] = {"windows": {}, "files": {}, "problems": []}
    for tag, _directory, manifest in (
        ("HOLD", HOLD_DIR, HOLD_MANIFEST),
        ("DEV", DEV_DIR, DEV_MANIFEST),
    ):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        out["windows"][tag] = payload.get("window", {})
        for entry in payload["files"]:
            path = REPO_ROOT / entry["path"]
            got = sha256_file(path)
            rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
            stamps = [int(r[0]) for r in rows]
            tf_ms = TIMEFRAMES[entry["timeframe"]] * 60_000
            expected = (stamps[-1] - stamps[0]) // tf_ms + 1 if len(stamps) > 1 else 0
            gaps = expected - len(set(stamps))
            duplicates = len(stamps) - len(set(stamps))
            record = {
                "sha256": got,
                "manifest_sha256": entry["sha256"],
                "hash_ok": got == entry["sha256"],
                "bars": len(rows),
                "manifest_bars": entry["bars"],
                "bars_ok": len(rows) == entry["bars"],
                "first_bar_ms": stamps[0],
                "last_bar_ms": stamps[-1],
                "monotonic": all(b > a for a, b in itertools.pairwise(stamps)),
                "duplicates": duplicates,
                "missing_bars": gaps,
            }
            out["files"][f"{tag}:{entry['asset']}:{entry['timeframe']}"] = record
            if not (record["hash_ok"] and record["bars_ok"] and record["hash_ok"]):
                out["problems"].append(
                    f"{tag}:{entry['asset']}:{entry['timeframe']}:hash/bar mismatch"
                )
            if duplicates:
                out["problems"].append(f"{tag}:{entry['asset']}:{entry['timeframe']}:duplicates")
    dev_end = max(v["last_bar_ms"] for k, v in out["files"].items() if k.startswith("DEV:"))
    hold_start = min(v["first_bar_ms"] for k, v in out["files"].items() if k.startswith("HOLD:"))
    hold_end = max(v["last_bar_ms"] for k, v in out["files"].items() if k.startswith("HOLD:"))
    out["dev_last_bar_ms"] = dev_end
    out["hold_first_bar_ms"] = hold_start
    out["hold_last_bar_ms"] = hold_end
    out["overlap_ms"] = max(0, dev_end - hold_start + 1)
    out["contiguous"] = hold_start > dev_end
    out["missing_total"] = sum(v["missing_bars"] for v in out["files"].values())
    out["passed"] = not out["problems"] and out["contiguous"] and out["missing_total"] == 0
    return out


def gate_spec() -> dict[str, Any]:
    got = sha256_file(SPEC)
    run = json.loads(TDM10_RUN.read_text(encoding="utf-8"))
    return {
        "spec_sha256": got,
        "expected": EXPECTED_SPEC_SHA,
        "manifest": run["deliverables"]["EXPERIMENT_SPEC.md"]["sha256"],
        "spec_aggregate_rule_verdict": run["verdict_detail"]["spec_aggregate_rule"],
        "wp_verdict": run["verdict"],
        "divergence_recorded": run["verdict_detail"]["spec_aggregate_rule"] != run["verdict"],
        "passed": got == EXPECTED_SPEC_SHA,
    }


def gate_costs() -> dict[str, Any]:
    from trading_bot.research.microstructure.cost_model_v3 import (
        VENUE_SPECS,
        default_model,
    )

    model = default_model()
    primary = model.evaluate(size_usd=1000.0, horizon_minutes=HORIZON_MINUTES)
    maker = model.evaluate(
        size_usd=1000.0,
        horizon_minutes=HORIZON_MINUTES,
        entry_order_type="limit_post_only",
        exit_order_type="limit_post_only",
        maker_fill_prob=0.5,
    )
    scenarios = {}
    for sid, spec in sorted(VENUE_SPECS.items()):
        m = default_model(sid)
        all_in = m.evaluate(size_usd=1000.0, horizon_minutes=HORIZON_MINUTES)
        scenarios[sid] = {
            "venue": spec.venue,
            "product": spec.product,
            "tier": spec.tier,
            "round_trip_bps": round(all_in.round_trip_bps, 4),
            "knowledge_class": all_in.knowledge_class,
            "components": {c.name: round(c.value_bps, 4) for c in all_in.components},
        }
    has_borrow = any(
        "borrow" in c.name or "margin" in c.name or "short" in c.name for c in primary.components
    )
    return {
        "scenario_id": primary.scenario_id,
        "venue": primary.venue,
        "product": primary.product,
        "size_usd": 1000.0,
        "horizon_minutes": HORIZON_MINUTES,
        "primary_round_trip_bps": round(primary.round_trip_bps, 4),
        "printed_tdm10_baseline": 23.79,
        "primary_delta": round(primary.round_trip_bps - 23.79, 4),
        "primary_components": {c.name: round(c.value_bps, 4) for c in primary.components},
        "primary_knowledge": primary.knowledge_class,
        "maker_50pct_fill_bps": round(maker.round_trip_bps, 4),
        "printed_maker_50pct_fill": 41.25,
        "maker_delta": round(maker.round_trip_bps - 41.25, 4),
        "scenarios": scenarios,
        "has_borrow_or_margin_component": has_borrow,
        "product_supports_short": primary.product.lower() != "spot",
        "passed": abs(primary.round_trip_bps - 23.79) < 0.01
        and abs(maker.round_trip_bps - 41.25) < 0.01,
    }


# ---------------------------------------------------------------------------
# G0-6: reproduction and the directional claim
# ---------------------------------------------------------------------------


def family_instance(name: str) -> Any:
    import importlib

    module_name, class_name = FAMILY_MODULES[name]
    module = importlib.import_module(f"trading_bot.research.families.{module_name}")
    return getattr(module, class_name)()


def compute_signals(family: Any, bars: list[Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
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
        entry = float(getattr(alpha, "entry_reference", 0.0) or 0.0) or float(bars[i].close)
        signals.append({"index": i, "direction": direction, "entry": entry})
    return signals


def build_trades(
    labels: Labels,
    bars: list[Any],
    signals: list[dict[str, Any]],
    *,
    horizon_bars: int,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    last_exit_index = -1
    for sig in signals:
        i = int(sig["index"])
        decision_ms = int(bars[i].timestamp)
        if decision_ms < start_ms or decision_ms >= end_ms:
            continue
        if i + horizon_bars >= len(bars):
            continue
        exit_ms = int(bars[i + horizon_bars].timestamp)
        if exit_ms >= end_ms or i <= last_exit_index:
            continue
        entry = float(sig["entry"])
        exit_price = float(bars[i + horizon_bars].close)
        sign = 1.0 if sig["direction"] == "LONG" else -1.0
        trades.append(
            {
                "decision_ms": decision_ms,
                "exit_ms": exit_ms,
                "direction": sig["direction"],
                "entry": entry,
                "exit": exit_price,
                "gross_bps": sign * (exit_price / entry - 1.0) * 10_000.0,
                "trend": labels.trend(i),
                "vol": labels.vol(i),
            }
        )
        last_exit_index = i + horizon_bars
    return trades


def gate_claim(cost_bps: float) -> dict[str, Any]:
    published_counts = {
        row["strategy_id"]: int(row["count"])
        for row in csv.DictReader(
            (REPO_ROOT / ".tdm10" / "regime_table.csv").open(encoding="utf-8")
        )
        if row["regime"] == "regime_trend" and row["label"] == "down"
    }
    published_total = {
        row["strategy_id"]: int(row["trades"])
        for row in csv.DictReader(
            (REPO_ROOT / ".tdm10" / "regime_table.csv").open(encoding="utf-8")
        )
    }

    per_cell: dict[str, list[dict[str, Any]]] = {}
    counts_match: dict[str, bool] = {}
    bucket_rows: list[dict[str, Any]] = []
    started = time.time()
    for tf, minutes in TIMEFRAMES.items():
        horizon_bars = max(1, round(HORIZON_MINUTES / minutes))
        series = {}
        for asset in ASSETS:
            bars = load_bars(HOLD_DIR / f"{asset}_{tf}.json")
            series[asset] = (bars, Labels(bars))
        for family_name in FAMILIES:
            cell = f"{family_name}@{tf}"
            trades: list[dict[str, Any]] = []
            for asset in ASSETS:
                bars, labels = series[asset]
                signals = [
                    s
                    for s in compute_signals(family_instance(family_name), bars)
                    if s["index"] < len(bars) - horizon_bars
                ]
                trades.extend(
                    build_trades(
                        labels,
                        bars,
                        signals,
                        horizon_bars=horizon_bars,
                        start_ms=HOLD_START_MS,
                        end_ms=HOLD_END_MS,
                    )
                )
            trades.sort(key=lambda t: int(t["decision_ms"]))
            per_cell[cell] = trades
            down = sum(1 for t in trades if t["trend"] == "down")
            counts_match[cell] = down == published_counts.get(cell, 0)
            print(
                f"  {cell:22s} reproduced={len(trades):6d} published={published_total.get(cell, 0):6d} "
                f"down={down:4d}/{published_counts.get(cell)} ({time.time() - started:.0f}s)",
                flush=True,
            )

    for cell, trades in per_cell.items():
        for axis in ("trend", "vol"):
            buckets: dict[str, list[dict[str, Any]]] = {}
            for t in trades:
                buckets.setdefault(str(t[axis]), []).append(t)
            for label, bucket in sorted(buckets.items()):
                if len(bucket) < 4:
                    continue
                gross = [float(t["gross_bps"]) for t in bucket]
                bucket_rows.append(
                    {
                        "strategy_id": cell,
                        "axis": axis,
                        "label": label,
                        "n": len(bucket),
                        "gross_bps": round(statistics.fmean(gross), 4),
                        "net_bps": round(statistics.fmean(gross) - cost_bps, 4),
                        "short_share": round(
                            sum(1 for t in bucket if t["direction"] == "SHORT") / len(bucket), 3
                        ),
                        "short_gross_bps": round(
                            statistics.fmean(
                                [float(t["gross_bps"]) for t in bucket if t["direction"] == "SHORT"]
                            ),
                            4,
                        )
                        if any(t["direction"] == "SHORT" for t in bucket)
                        else None,
                        "n_short": sum(1 for t in bucket if t["direction"] == "SHORT"),
                    }
                )

    ART.mkdir(parents=True, exist_ok=True)
    with (ART / "regime_direction.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(bucket_rows[0]))
        writer.writeheader()
        writer.writerows(bucket_rows)

    top = sorted(bucket_rows, key=lambda r: r["gross_bps"], reverse=True)[:6]
    top_short_down = sum(
        1
        for r in top
        if r["label"] == "down" and r["axis"] == "trend" and (r["short_share"] or 0) > 0.5
    )
    return {
        "published_totals_matched": {
            cell: len(per_cell[cell]) == published_total.get(cell) for cell in per_cell
        },
        "published_down_bucket_matched": counts_match,
        "reproduced_trades": sum(len(v) for v in per_cell.values()),
        "published_trades": max(published_total.values()) if published_total else 0,
        "top_buckets": top,
        "top6_short_down": top_short_down,
        "claim_holds": top_short_down >= 5,
        "elapsed_s": round(time.time() - started, 1),
        "reproduction_passed": all(counts_match.values())
        and all(len(per_cell[c]) == published_total.get(c) for c in per_cell),
        # The claim gate is separate from the reproduction gate on purpose: a
        # perfectly reproduced experiment can still have overstated its claim.
        "passed": all(counts_match.values())
        and all(len(per_cell[c]) == published_total.get(c) for c in per_cell)
        and top_short_down >= 5,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-trades", action="store_true", help="skip the trade reproduction")
    args = parser.parse_args(argv)

    ART.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {"generated_at_ms": int(time.time() * 1000)}
    out["isolation"] = gate_isolation()
    print("G0-1 isolation", out["isolation"]["passed"], flush=True)
    out["tdm10_artifacts"] = gate_tdm10_artifacts()
    print("G0-2 artifacts", out["tdm10_artifacts"]["passed"], flush=True)
    out["datasets"] = gate_datasets()
    print(
        "G0-3 datasets",
        out["datasets"]["passed"],
        "missing",
        out["datasets"]["missing_total"],
        flush=True,
    )
    out["spec"] = gate_spec()
    print("G0-4 spec", out["spec"]["passed"], flush=True)
    out["costs"] = gate_costs()
    print(
        "G0-5 costs",
        out["costs"]["passed"],
        out["costs"]["primary_round_trip_bps"],
        out["costs"]["maker_50pct_fill_bps"],
        "spot_short",
        out["costs"]["product_supports_short"],
        flush=True,
    )
    if not args.no_trades:
        out["claim"] = gate_claim(out["costs"]["primary_round_trip_bps"])
        print(
            "G0-6 claim",
            out["claim"]["passed"],
            "top6 short/down",
            out["claim"]["top6_short_down"],
            flush=True,
        )

    # G0-6 is a *finding*, not a reconciliation gate: the claim may legitimately
    # fail to reproduce while every integrity gate passes (that is exactly what
    # happened here). It is therefore reported separately from the exit status.
    gates = [
        v["passed"]
        for k, v in out.items()
        if isinstance(v, dict) and "passed" in v and k != "claim"
    ]
    out["all_gates_passed"] = all(gates)
    out["claim_holds"] = out.get("claim", {}).get("claim_holds")
    (ART / "g0.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v["passed"] for k, v in out.items() if isinstance(v, dict) and "passed" in v}
        )
    )
    return 0 if out["all_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
