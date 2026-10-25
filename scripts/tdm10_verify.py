"""WP-TDM-10 — independent verifier.

Deliberately shares as little as possible with ``scripts/tdm10_experiment.py``:

* it re-derives every trade from the raw JSON bars with its **own** loop;
* it prices edge with **log returns** (the builder uses simple returns), so the
  two estimators must agree to second order instead of being the same formula;
* it tests significance with a **sign-flip permutation test** (the builder uses a
  percentile bootstrap), exact enumeration below 16 trades;
* it recomputes profit factor, drawdown, win rate and net from the raw trade
  dump, never from the builder's aggregates.

Every check reports ``PASS`` / ``FAIL`` / ``NOT_RUN``. A check that cannot run is
``NOT_RUN`` — never silently a pass.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import statistics
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

OUT_DIR = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-10"
SPEC = OUT_DIR / "EXPERIMENT_SPEC.md"
MATRIX = OUT_DIR / "ALPHA_ECONOMIC_MATRIX.csv"
ART = REPO_ROOT / ".tdm10"
DEV_MANIFEST = REPO_ROOT / "data" / "tdm10" / "DATASET_DEV.json"
HOLD_MANIFEST = REPO_ROOT / "data" / "tdm08" / "DATASET.json"
BUILDER = REPO_ROOT / "scripts" / "tdm10_experiment.py"

WINDOW = 100
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
TIMEFRAMES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
ASSETS = ("BTC", "ETH", "SOL")
PRIMARY_HORIZON = 30.0
PERMUTATION_DRAWS = 4000
PERMUTATION_SEED = 424242
ALPHA = 0.05

CHECKS: list[dict[str, Any]] = []


def record(check_id: str, name: str, status: str, detail: Any = None) -> None:
    CHECKS.append({"id": check_id, "name": name, "status": status, "detail": detail})
    print(f"[{status:7s}] {check_id} {name}", flush=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_ms(value: str) -> int:
    import calendar

    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000


def iso(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# independent data access (raw JSON, no builder import)
# ---------------------------------------------------------------------------


def raw_rows(path: Path) -> list[list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
        for r in payload["rows"]
    ]


def ohlcv(rows: list[list[float]], symbol: str) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    return [
        OHLCV(
            symbol=symbol,
            timestamp=int(r[0]),
            open=r[1],
            high=r[2],
            low=r[3],
            close=r[4],
            volume=r[5],
        )
        for r in rows
    ]


def make_family(name: str) -> Any:
    module_name, class_name = FAMILY_MODULES[name]
    module = __import__(f"trading_bot.research.families.{module_name}", fromlist=[class_name])
    return getattr(module, class_name)()


def independent_trades(
    bars: list[Any], family: Any, *, horizon_bars: int, start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    """Own signal loop, own bookkeeping: only the family class is shared."""
    trades: list[dict[str, Any]] = []
    blocked_until = -math.inf
    for i in range(WINDOW - 1, len(bars) - horizon_bars):
        decision_ms = int(bars[i].timestamp)
        if decision_ms < start_ms or decision_ms >= end_ms:
            continue
        if i < blocked_until:
            continue
        window = [bars[k] for k in range(i - WINDOW + 1, i + 1)]
        try:
            emitted = family.generate(window, {}, None)
        except Exception:
            continue
        chosen = None
        for candidate in emitted or []:
            if str(getattr(candidate, "direction", "")).upper() in ("LONG", "SHORT"):
                chosen = candidate
                break
        if chosen is None:
            continue
        entry = float(getattr(chosen, "entry_reference", 0.0) or 0.0) or float(bars[i].close)
        exit_price = float(bars[i + horizon_bars].close)
        if entry <= 0 or exit_price <= 0:
            continue
        sign = 1.0 if str(chosen.direction).upper() == "LONG" else -1.0
        trades.append(
            {
                "decision_ms": decision_ms,
                "exit_ms": int(bars[i + horizon_bars].timestamp),
                "direction": str(chosen.direction).upper(),
                "entry": entry,
                "exit": exit_price,
                # LOG returns: a different estimator from the builder's simple returns
                "gross_bps": sign * math.log(exit_price / entry) * 10_000.0,
            }
        )
        blocked_until = i + horizon_bars + 1
    return trades


def simple_gross(trade: dict[str, Any]) -> float:
    sign = 1.0 if trade["direction"] == "LONG" else -1.0
    return sign * (trade["exit"] / trade["entry"] - 1.0) * 10_000.0


# ---------------------------------------------------------------------------
# independent statistics
# ---------------------------------------------------------------------------


def sign_flip_p(values: list[float]) -> float:
    """One-sided H0: mean <= 0. Exact enumeration up to 15 observations."""
    n = len(values)
    if n < 2:
        return 1.0
    observed = statistics.fmean(values)
    if n <= 15:
        total = 0
        hits = 0
        for signs in product((1.0, -1.0), repeat=n):
            total += 1
            if sum(s * v for s, v in zip(signs, values, strict=True)) / n >= observed - 1e-12:
                hits += 1
        return hits / total
    import random

    rng = random.Random(PERMUTATION_SEED)
    hits = 0
    for _ in range(PERMUTATION_DRAWS):
        total = 0.0
        for v in values:
            total += v if rng.getrandbits(1) else -v
        if total / n >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATION_DRAWS + 1)


def holm(pvalues: dict[str, float], alpha: float = ALPHA) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * p))
        out[key] = running
    return out


def profit_factor(net: list[float]) -> float | None:
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    if losses == 0:
        return None
    return gains / losses


def max_drawdown(net: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for v in net:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    started = time.time()
    ART.mkdir(parents=True, exist_ok=True)

    # --- 1. artefacts exist and are unchanged --------------------------------
    spec_hash = sha256_file(SPEC) if SPEC.exists() else None
    results_path = ART / "results.json"
    dump_path = ART / "trades_hold.json"
    if not all(p.exists() for p in (SPEC, MATRIX, results_path, dump_path)):
        record("A1", "builder artefacts present", "FAIL", "a required artefact is missing")
        return 2
    results = json.loads(results_path.read_text(encoding="utf-8"))
    spec_recorded = results["spec"]["sha256"]
    if spec_hash == spec_recorded:
        record("A1", "spec hash unchanged since measurement", "PASS", {"sha256": spec_hash})
    else:
        record(
            "A1",
            "spec hash unchanged since measurement",
            "FAIL",
            {"recorded": spec_recorded, "now": spec_hash},
        )
    if results.get("complete") is True:
        record("A2", "builder run recorded complete", "PASS", results.get("duration_seconds"))
    else:
        record("A2", "builder run recorded complete", "FAIL", results.get("complete"))

    # --- 2. dataset integrity, recomputed here ------------------------------
    integrity_failures: list[dict[str, Any]] = []
    hashed = 0
    for manifest_path, label in ((DEV_MANIFEST, "DEV"), (HOLD_MANIFEST, "HOLD")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            path = REPO_ROOT / entry["path"]
            digest = sha256_file(path)
            hashed += 1
            if digest != entry["sha256"]:
                integrity_failures.append({"dataset": label, "path": entry["path"]})
    record(
        "B1",
        "dataset hashes recomputed from disk",
        "PASS" if not integrity_failures else "FAIL",
        {"files": hashed, "failures": integrity_failures},
    )

    # --- 3. reported cost, recomputed from the model ------------------------
    from trading_bot.autonomous.costs import CostEngine

    breakdown = CostEngine().evaluate(size_usd=1000.0, horizon_minutes=PRIMARY_HORIZON)
    component_sum = sum(float(c["value_bps"]) for c in breakdown.components)
    reported_cost = float(results["cost_reference"]["all_in_bps"])
    cost_ok = (
        abs(component_sum - reported_cost) <= 1e-6
        and abs(float(breakdown.round_trip_bps) - reported_cost) <= 1e-6
    )
    record(
        "C1",
        "all-in cost = sum of components (recomputed)",
        "PASS" if cost_ok else "FAIL",
        {
            "component_sum_bps": round(component_sum, 6),
            "round_trip_bps": round(float(breakdown.round_trip_bps), 6),
            "reported_bps": round(reported_cost, 6),
            "components": {c["name"]: c["value_bps"] for c in breakdown.components},
        },
    )

    # --- 4. rebuild every holdout trade independently -----------------------
    dump = json.loads(dump_path.read_text(encoding="utf-8"))
    matrix_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    with MATRIX.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            matrix_rows[(row["strategy_id"], row["window"], row["scope"])] = row

    hold_start, hold_end = utc_ms("2026-09-25T00:00:00Z"), utc_ms("2026-10-25T00:00:00Z")
    per_cell: dict[str, Any] = {}
    t0 = time.time()
    for tf, minutes in TIMEFRAMES.items():
        horizon_bars = max(1, round(PRIMARY_HORIZON / minutes))
        for family_name in FAMILIES:
            cell = f"{family_name}@{tf}"
            mine: list[dict[str, Any]] = []
            for asset in ASSETS:
                bars = ohlcv(
                    raw_rows(REPO_ROOT / "data" / "tdm08" / f"{asset}_{tf}.json"), f"{asset}/USDT"
                )
                mine.extend(
                    independent_trades(
                        bars,
                        make_family(family_name),
                        horizon_bars=horizon_bars,
                        start_ms=hold_start,
                        end_ms=hold_end,
                    )
                )
            mine.sort(key=lambda t: t["decision_ms"])
            per_cell[cell] = mine
    record(
        "D1",
        "independent trade re-derivation finished",
        "PASS",
        {"cells": len(per_cell), "seconds": round(time.time() - t0, 1)},
    )

    # --- 5. per-trade agreement with the builder dump ----------------------
    builder_by_cell = {
        cell: [
            dict(
                zip(
                    ("decision_ms", "exit_ms", "direction", "entry", "exit", "gross_simple"),
                    row,
                    strict=True,
                )
            )
            for row in rows["hold"]
        ]
        for cell, rows in dump.items()
    }
    mismatched: dict[str, Any] = {}
    counted: dict[str, int] = {}
    max_log_simple_gap = 0.0
    for cell, mine in per_cell.items():
        theirs = builder_by_cell.get(cell, [])
        counted[cell] = {"independent": len(mine), "builder": len(theirs)}
        if len(mine) != len(theirs):
            mismatched[cell] = counted[cell]
            continue
        bad = 0
        for a, b in zip(mine, theirs, strict=True):
            if int(a["decision_ms"]) != int(b["decision_ms"]) or a["direction"] != b["direction"]:
                bad += 1
                continue
            gap = abs(a["gross_bps"] - simple_gross(a))
            max_log_simple_gap = max(max_log_simple_gap, gap)
        if bad:
            mismatched[cell] = {"trade_mismatches": bad}
    record(
        "D2",
        "independent trade list == builder trade list (timestamps, direction, count)",
        "PASS" if not mismatched else "FAIL",
        {
            "cells": len(per_cell),
            "mismatched": mismatched,
            "max_log_vs_simple_gap_bps": round(max_log_simple_gap, 6),
        },
    )

    # --- 6. point-in-time invariants on every independent trade -------------
    pi_violations: list[dict[str, Any]] = []
    for cell, trades in per_cell.items():
        for t in trades:
            if not (t["exit_ms"] > t["decision_ms"]):
                pi_violations.append(
                    {"cell": cell, "decision_ms": t["decision_ms"], "kind": "exit<=decision"}
                )
            if not (hold_start <= int(t["decision_ms"]) < hold_end):
                pi_violations.append(
                    {"cell": cell, "decision_ms": t["decision_ms"], "kind": "outside window"}
                )
    record(
        "D3",
        "exit_time > decision_time on every trade",
        "PASS" if not pi_violations else "FAIL",
        {"violations": pi_violations[:10], "count": len(pi_violations)},
    )

    # --- 7. look-ahead perturbation ----------------------------------------
    from trading_bot.market_data.types import OHLCV

    bars = ohlcv(raw_rows(REPO_ROOT / "data" / "tdm08" / "BTC_5m.json"), "BTC/USDT")
    horizon_bars = 6
    base_signals = independent_trades(
        bars,
        make_family("momentum"),
        horizon_bars=horizon_bars,
        start_ms=hold_start,
        end_ms=hold_end,
    )
    cut_index = int(len(bars) * 0.6)
    cut_ms = int(bars[cut_index].timestamp)
    perturbed = list(bars)
    for k in range(cut_index + horizon_bars + 1, len(bars)):
        shock = 1.0 + 0.05 * math.sin(k)
        perturbed[k] = OHLCV(
            symbol=bars[k].symbol,
            timestamp=bars[k].timestamp,
            open=bars[k].open * shock,
            high=bars[k].high * shock,
            low=bars[k].low * shock,
            close=bars[k].close * shock,
            volume=bars[k].volume,
        )
    after_signals = independent_trades(
        perturbed,
        make_family("momentum"),
        horizon_bars=horizon_bars,
        start_ms=hold_start,
        end_ms=hold_end,
    )
    before = [t for t in base_signals if t["decision_ms"] <= cut_ms]
    after = [t for t in after_signals if t["decision_ms"] <= cut_ms]
    identical = len(before) == len(after) and all(
        int(a["decision_ms"]) == int(b["decision_ms"])
        and abs(a["gross_bps"] - b["gross_bps"]) < 1e-9
        for a, b in zip(before, after, strict=True)
    )
    record(
        "D4",
        "overwriting all bars after decision+h leaves past trades identical",
        "PASS" if identical else "FAIL",
        {"trades_before_cut": len(before), "trades_after_cut": len(after), "identical": identical},
    )

    # --- 8. window disjointness from raw timestamps ------------------------
    overlap_report: list[dict[str, Any]] = []
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            dev = {r[0] for r in raw_rows(REPO_ROOT / "data" / "tdm10" / f"{asset}_{tf}.json")}
            hold = {r[0] for r in raw_rows(REPO_ROOT / "data" / "tdm08" / f"{asset}_{tf}.json")}
            if dev & hold:
                overlap_report.append({"asset": asset, "timeframe": tf, "overlap": len(dev & hold)})
    record(
        "D5",
        "DEV and HOLD share no bar timestamp",
        "PASS" if not overlap_report else "FAIL",
        {"overlaps": overlap_report},
    )

    # --- 9. aggregate agreement with the published matrix ------------------
    aggregate_failures: list[dict[str, Any]] = []
    estimator_gaps: dict[str, float] = {}
    for cell, mine in per_cell.items():
        row = matrix_rows.get((cell, "HOLD", "POOLED"))
        if row is None:
            aggregate_failures.append({"cell": cell, "reason": "row missing from CSV"})
            continue
        gross_simple = statistics.fmean([simple_gross(t) for t in mine]) if mine else None
        gross_log = statistics.fmean([t["gross_bps"] for t in mine]) if mine else None
        net = (
            statistics.fmean([simple_gross(t) - float(breakdown.round_trip_bps) for t in mine])
            if mine
            else None
        )
        pf = (
            profit_factor([simple_gross(t) - float(breakdown.round_trip_bps) for t in mine])
            if mine
            else None
        )
        dd = (
            max_drawdown([simple_gross(t) - float(breakdown.round_trip_bps) for t in mine])
            if mine
            else None
        )
        win = (
            100.0
            * sum(1 for t in mine if simple_gross(t) - float(breakdown.round_trip_bps) > 0)
            / len(mine)
            if mine
            else None
        )
        checks = {
            "trades": (len(mine), int(row["trades"])),
            "gross": (
                gross_simple,
                float(row["gross_bps_per_trade"]) if row["gross_bps_per_trade"] else None,
            ),
            "net": (net, float(row["net_bps_per_trade"]) if row["net_bps_per_trade"] else None),
            "profit_factor": (pf, float(row["profit_factor"]) if row["profit_factor"] else None),
            "max_drawdown": (
                dd,
                float(row["max_drawdown_bps"]) if row["max_drawdown_bps"] else None,
            ),
            "win_rate": (win, float(row["win_rate_pct"]) if row["win_rate_pct"] else None),
        }
        for key, (mine_value, their_value) in checks.items():
            if key == "trades":
                ok = mine_value == their_value
                tol = 0
            else:
                if mine_value is None or their_value is None:
                    ok = mine_value is None and their_value is None
                    tol = 0
                else:
                    tol = 2e-3 if key != "profit_factor" else 1e-2
                    ok = abs(mine_value - their_value) <= tol
            if not ok:
                aggregate_failures.append(
                    {
                        "cell": cell,
                        "metric": key,
                        "independent": mine_value,
                        "published": their_value,
                        "tolerance": tol,
                    }
                )
        # the identity the matrix must satisfy on the base cost
        if row["net_bps_per_trade"] and row["gross_bps_per_trade"]:
            identity_gap = abs(
                float(row["net_bps_per_trade"])
                - (float(row["gross_bps_per_trade"]) - float(breakdown.round_trip_bps))
            )
            if identity_gap > 4e-3:
                aggregate_failures.append(
                    {"cell": cell, "metric": "net==gross-cost", "gap": identity_gap}
                )
        # log vs simple estimator divergence must stay second order
        # Jensen gap between log and simple mean returns is ~½E[r²]; for these
        # horizons it is well under 0.5 bps, so a larger gap means a different
        # estimator, not a rounding convention.
        if (
            gross_simple is not None
            and gross_log is not None
            and (abs(gross_log - gross_simple) > 0.5 or (gross_log > 0) != (gross_simple > 0))
        ):
            aggregate_failures.append(
                {
                    "cell": cell,
                    "metric": "log_vs_simple",
                    "log": gross_log,
                    "simple": gross_simple,
                    "tolerance_bps": 0.5,
                }
            )
        if gross_simple is not None and gross_log is not None:
            estimator_gaps[cell] = round(gross_log - gross_simple, 6)
    record(
        "E1",
        "published aggregates == independently recomputed (trades, gross, net, PF, DD, win rate)",
        "PASS" if not aggregate_failures else "FAIL",
        {
            "cells": len(per_cell),
            "failures": aggregate_failures[:20],
            "failure_count": len(aggregate_failures),
            "max_log_vs_simple_gap_bps": round(
                max((abs(v) for v in estimator_gaps.values()), default=0.0), 6
            ),
            "log_vs_simple_tolerance_bps": 0.5,
        },
    )

    # --- 10. permutation test instead of bootstrap ------------------------
    perm_p = {
        cell: sign_flip_p([t["gross_bps"] for t in trades])
        for cell, trades in per_cell.items()
        if trades
    }
    perm_holm = holm(perm_p)
    builder_p = {cell: float(v) for cell, v in results["bootstrap_pvalues"].items()}
    disagreements: list[dict[str, Any]] = []
    for cell in sorted(perm_p):
        a = perm_p[cell] <= ALPHA
        b = builder_p.get(cell, 1.0) <= ALPHA
        a_h = perm_holm[cell] <= ALPHA
        b_h = float(results["holm"]["adjusted"].get(cell, 1.0)) <= ALPHA
        if a != b:
            disagreements.append(
                {
                    "cell": cell,
                    "permutation_p": round(perm_p[cell], 6),
                    "bootstrap_p": builder_p.get(cell),
                    "permutation_holm": round(perm_holm[cell], 6),
                    "bootstrap_holm": results["holm"]["adjusted"].get(cell),
                    "agree_raw": a == b,
                    "agree_holm": a_h == b_h,
                    "direction": {
                        "permutation": "positive" if a else "not_positive",
                        "bootstrap": "positive" if b else "not_positive",
                    },
                }
            )  # The decision rule is Holm-corrected, so that is what must agree; raw-level
    # disagreements are reported as evidence of fragility, not as a defect.
    holm_disagreements = [d for d in disagreements if not d["agree_holm"]]
    holm_positive_perm = sorted(c for c in perm_holm if perm_holm[c] <= ALPHA)
    holm_positive_boot = sorted(
        c for c in results["holm"]["adjusted"] if float(results["holm"]["adjusted"][c]) <= ALPHA
    )
    record(
        "F1",
        "sign-flip permutation vs bootstrap: same Holm-corrected conclusion",
        "PASS" if not holm_disagreements and holm_positive_perm == holm_positive_boot else "FAIL",
        {
            "method_builder": "percentile bootstrap, 2000 resamples, seed 20261025",
            "method_verifier": f"sign-flip permutation, {PERMUTATION_DRAWS} draws, seed {PERMUTATION_SEED}",
            "raw_disagreements": disagreements,
            "holm_disagreements": holm_disagreements,
            "cells_positive_raw_permutation": sorted(c for c in perm_p if perm_p[c] <= ALPHA),
            "cells_positive_raw_bootstrap": sorted(c for c in builder_p if builder_p[c] <= ALPHA),
            "cells_positive_holm_permutation": holm_positive_perm,
            "cells_positive_holm_bootstrap": holm_positive_boot,
        },
    )

    # --- 11. verdict re-derivation from the matrix -------------------------
    verdict_failures: list[dict[str, Any]] = []
    published_verdicts = results["verdicts"]
    for cell, verdict in published_verdicts.items():
        hold = matrix_rows.get((cell, "HOLD", "POOLED"))
        d1 = matrix_rows.get((cell, "D1", "POOLED"))
        d2 = matrix_rows.get((cell, "D2", "POOLED"))
        if not (hold and d1 and d2):
            verdict_failures.append({"cell": cell, "reason": "missing rows"})
            continue
        trades = int(hold["trades"])
        net = float(hold["net_bps_per_trade"]) if hold["net_bps_per_trade"] else None
        ci_low = float(hold["ci95_low"]) if hold["ci95_low"] else None
        stress = results["sensitivity"][cell]["mult_1.25"]["net_bps_per_trade"]
        d1_gross = float(d1["gross_bps_per_trade"]) if d1["gross_bps_per_trade"] else 0.0
        d2_gross = float(d2["gross_bps_per_trade"]) if d2["gross_bps_per_trade"] else 0.0
        should_go = (
            trades >= 30
            and net is not None
            and net > 0
            and ci_low is not None
            and ci_low > 0
            and d1_gross > 0
            and d2_gross > 0
            and stress is not None
            and stress > 0
        )
        published = verdict["classification"]
        if should_go != (published == "GO_RESEARCH_CELL"):
            verdict_failures.append(
                {
                    "cell": cell,
                    "published": published,
                    "rules_imply_go": should_go,
                    "inputs": {
                        "trades": trades,
                        "net": net,
                        "ci_low": ci_low,
                        "d1": d1_gross,
                        "d2": d2_gross,
                        "stress": stress,
                    },
                }
            )
    record(
        "G1",
        "verdicts re-derived from the published matrix obey §8",
        "PASS" if not verdict_failures else "FAIL",
        {"cells": len(published_verdicts), "failures": verdict_failures},
    )

    # --- summary -----------------------------------------------------------
    failed = [c for c in CHECKS if c["status"] == "FAIL"]
    not_run = [c for c in CHECKS if c["status"] == "NOT_RUN"]
    overall = "PASS" if not failed and not not_run else "FAIL"
    payload = {
        "artifact": "tdm10-independent-verification-v1",
        "generated_by": "scripts/tdm10_verify.py",
        "builder": {
            "path": BUILDER.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256_file(BUILDER),
        },
        "spec": {"path": SPEC.relative_to(REPO_ROOT).as_posix(), "sha256": spec_hash},
        "matrix": {"path": MATRIX.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(MATRIX)},
        "independence": {
            "shares_builder_code": False,
            "estimator": "log returns vs builder simple returns",
            "significance": "sign-flip permutation vs builder percentile bootstrap",
            "verifier_person_independent": False,
            "note": "same author as the builder; independence is of code and method, not of person",
        },
        "checks": CHECKS,
        "overall": overall,
        "failed": [c["id"] for c in failed],
        "not_run": [c["id"] for c in not_run],
        "duration_seconds": round(time.time() - started, 1),
    }
    (ART / "verification.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (ART / "verification_table.md").write_text(
        render_table(payload), encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {"overall": overall, "failed": payload["failed"], "not_run": payload["not_run"]},
            indent=2,
        )
    )
    return 0 if overall == "PASS" else 1


def render_table(payload: dict[str, Any]) -> str:
    lines = [
        "| Check | What it proves | Status | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    names = {
        "A1": "spec hash unchanged since measurement",
        "A2": "builder run reached its end",
        "B1": "dataset bytes match their manifests",
        "C1": "cost == sum of its own components",
        "D1": "independent re-derivation completed",
        "D2": "trade list identical, trade by trade",
        "D3": "exit strictly after entry",
        "D4": "no look-ahead (future overwritten)",
        "D5": "DEV and HOLD disjoint",
        "E1": "published aggregates reproducible",
        "F1": "two significance methods agree",
        "G1": "verdicts follow the frozen rules",
    }
    for check in payload["checks"]:
        detail = check["detail"]
        if isinstance(detail, dict):
            keys = [
                k
                for k in (
                    "files",
                    "cells",
                    "component_sum_bps",
                    "trades_before_cut",
                    "disagreements",
                    "failure_count",
                    "max_log_vs_simple_gap_bps",
                )
                if k in detail
            ]
            short = ", ".join(f"{k}={detail[k]}" for k in keys) or "—"
        else:
            short = "—"
        lines.append(
            f"| `{check['id']}` | {names.get(check['id'], check['name'])} | **{check['status']}** | {short} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
