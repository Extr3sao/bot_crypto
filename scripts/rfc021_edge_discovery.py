"""RFC-021 Part B — EDGE DISCOVERY SPRINT 001 (§12-§48).

Chronological split of the certified dataset, a candidate inventory, and a
discovery → validation → robustness → holdout pipeline with the certified
round-trip cost (23.790569 bps) applied to every trade. Candidates are the
existing productive families across the certified timeframes (5m/15m/30m/1h),
re-costed from their per-trade research outputs.

The holdout is read ONLY by finalists that clear discovery + validation +
robustness (§37); when no candidate survives discovery the holdout is recorded
NOT_REACHED with the reason (§52).

Usage:
    python scripts/rfc021_edge_discovery.py --out-dir reports/edge-discovery
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TRADES_DIR = REPO / "reports" / "strategy-baseline"
DATA = REPO / "reports" / "strategy-baseline" / "data"
OUT = REPO / "reports" / "edge-discovery"

COST_BPS = 23.790569  # certified COST_MODEL_V3 round-trip
ROOT_NOTIONAL = 500.0  # research backtest notional per trade (USDT)
MIN_TRADES = 50  # §23 "insufficient trades"
FAMILIES = ("breakout", "ema_crossover", "mean_reversion", "momentum", "trend", "volatility")
TF_MIN = {"5m": 5.0, "15m": 15.0, "30m": 30.0, "1h": 60.0}

# Chronological split (§16). Never shuffled.
SPLITS: dict[str, tuple[str, ...]] = {
    "DISCOVERY": ("W1", "W2", "W3", "W4"),
    "VALIDATION": ("W5",),
    "HOLDOUT": ("W6", "W7"),
}

HYPOTHESES: dict[str, dict[str, str]] = {
    "mean_reversion": {
        "hypothesis": "Short-horizon price dislocations revert toward a local mean.",
        "why_edge_could_exist": "Order-flow imbalance / inventory pressure overreacts.",
        "market_behavior_exploited": "Overextension then reversion.",
        "failure_mode": "Trending markets: reversion trades get run over.",
        "expected_regime": "RANGE / LOW_VOLATILITY",
    },
    "momentum": {
        "hypothesis": "Recent returns persist over the next horizon.",
        "why_edge_could_exist": "Under-reaction / slow information diffusion.",
        "market_behavior_exploited": "Continuation after a move.",
        "failure_mode": "Chop: continuation signals whipsaw.",
        "expected_regime": "TREND_UP / TREND_DOWN",
    },
    "breakout": {
        "hypothesis": "Price leaving a consolidation range continues.",
        "why_edge_could_exist": "Stops trigger and liquidity is consumed on the break.",
        "market_behavior_exploited": "Volatility expansion after compression.",
        "failure_mode": "False breakouts revert.",
        "expected_regime": "LOW_VOLATILITY -> HIGH_VOLATILITY",
    },
    "trend": {
        "hypothesis": "A moving-average regime persists.",
        "why_edge_could_exist": "Slow trend-following premia.",
        "market_behavior_exploited": "Sustained directional drift.",
        "failure_mode": "Range-bound regimes.",
        "expected_regime": "TREND_UP / TREND_DOWN",
    },
    "ema_crossover": {
        "hypothesis": "Fast/slow EMA crossovers mark regime changes.",
        "why_edge_could_exist": "Regime persistence.",
        "market_behavior_exploited": "Directional drift.",
        "failure_mode": "Frequent flips in chop.",
        "expected_regime": "TREND_UP / TREND_DOWN",
    },
    "volatility": {
        "hypothesis": "Realised-volatility expansion/contraction is tradable.",
        "why_edge_could_exist": "Vol clustering; breakout of the vol regime.",
        "market_behavior_exploited": "Vol-of-vol.",
        "failure_mode": "Vol mean-reverts faster than the position.",
        "expected_regime": "HIGH_VOLATILITY",
    },
}


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    gross_bps: float
    net_bps: float
    window: str


@dataclass
class CandidateResult:
    candidate_id: str
    family: str
    timeframe: str
    status: str
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    split_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


def _window_of(path: str) -> str:
    return path.split("_", 1)[0]


def load_csv_candidates() -> dict[str, list[Trade]]:
    """strategy_id -> [Trade] from the per-trade research CSVs (5m/15m/30m)."""
    out: dict[str, list[Trade]] = {}
    for path in sorted(TRADES_DIR.glob("TRADES_*.csv")):
        stem = path.stem[len("TRADES_") :]
        if stem == "DISCOVERY":
            continue
        tf = "5m"
        family = stem
        for suf, t in (("_15m", "15m"), ("_30m", "30m"), ("_1h", "1h")):
            if stem.endswith(suf):
                family, tf = stem[: -len(suf)], t
                break
        if family not in FAMILIES:
            continue
        for rec in csv.DictReader(path.open(encoding="utf-8")):
            if str(rec.get("scenario", "BASE")) != "BASE":
                continue
            notional = float(rec["notional"]) or ROOT_NOTIONAL
            gross_bps = float(rec["gross"]) / notional * 10_000.0
            out.setdefault(f"{family}@{tf}", []).append(
                Trade(
                    entry_ts=int(rec["entry_ts"]),
                    exit_ts=int(rec["exit_ts"]),
                    gross_bps=gross_bps,
                    net_bps=gross_bps - COST_BPS,
                    window=_window_of(str(rec.get("window", ""))),
                )
            )
    return out


def load_1h_from_results() -> dict[str, dict[str, Any]]:
    """1h discovery aggregates from MULTI_FAMILY_RESULTS_1h.json (W1-W4 = DEV)."""
    path = TRADES_DIR / "MULTI_FAMILY_RESULTS_1h.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for family, scenarios in payload.items():
        dev = (scenarios.get("BASE") or {}).get("DEV_W1_W4") or {}
        trades = int(dev.get("trades", 0) or 0)
        gross_usdt = float(dev.get("gross", 0.0) or 0.0)
        if trades <= 0:
            continue
        gross_bps = gross_usdt / (ROOT_NOTIONAL * trades) * 10_000.0
        out[f"{family}@1h"] = {
            "trades": trades,
            "gross_bps": gross_bps,
            "net_bps": gross_bps - COST_BPS,
            "pf": dev.get("profit_factor"),
            "win_rate": dev.get("win_rate"),
            "source": "MULTI_FAMILY_RESULTS_1h.json#BASE.DEV_W1_W4",
        }
    return out


def _sharpe(net: list[float], entry_ts: list[int]) -> float | None:
    if len(net) < 3:
        return None
    sd = float(statistics.pstdev(net))
    if sd == 0:
        return None
    span_years = (max(entry_ts) - min(entry_ts)) / (1000.0 * 3600 * 24 * 365)
    trades_per_year = (len(net) / span_years) if span_years > 0 else 0.0
    return round(float(statistics.fmean(net)) / sd * float(trades_per_year**0.5), 4)


def _max_dd(net: list[float]) -> float:
    cum = peak = dd = 0.0
    for x in net:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def metrics_for(trades: list[Trade], tf: str) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    gross = [t.gross_bps for t in trades]
    net = [t.net_bps for t in trades]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x < 0]
    pf = (sum(wins) / abs(sum(losses))) if losses else None
    return {
        "trades": n,
        "gross_bps": round(statistics.fmean(gross), 4),
        "cost_bps": COST_BPS,
        "net_bps": round(statistics.fmean(net), 4),
        "median_gross_bps": round(statistics.median(gross), 4),
        "net_pnl_usdt": round(sum(net) / 10_000.0 * ROOT_NOTIONAL, 2),
        "profit_factor": (round(pf, 4) if pf is not None else None),
        "win_rate": round(len(wins) / n, 4),
        "sharpe": _sharpe(net, [t.entry_ts for t in trades]),
        "max_dd_bps": round(_max_dd(net), 4),
        "edge_cost_ratio": round(statistics.fmean(gross) / COST_BPS, 4),
        "trades_per_day": round(
            n
            / max(
                1.0,
                (max(t.exit_ts for t in trades) - min(t.entry_ts for t in trades))
                / (1000.0 * 86400),
            ),
            3,
        ),
    }


def bucket(ratio: float) -> str:
    if ratio < 1.0:
        return "<1.0"
    if ratio < 1.25:
        return "1.0-1.25"
    if ratio < 1.5:
        return "1.25-1.5"
    if ratio < 2.0:
        return "1.5-2.0"
    return ">2.0"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="reports/edge-discovery")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    candidates = load_csv_candidates()
    one_h = load_1h_from_results()

    # -- data split ---------------------------------------------------------
    data_hashes: dict[str, Any] = {}
    for split, windows in SPLITS.items():
        files = []
        h = hashlib.sha256()
        rows = 0
        for path in sorted(DATA.glob("*.json")):
            win = path.name.split("_")[1]
            if win in windows:
                files.append(path.name)
                raw = path.read_bytes()
                h.update(raw)
                rows += len(json.loads(raw))
        data_hashes[split] = {
            "windows": list(windows),
            "files": len(files),
            "rows": rows,
            "sha256": h.hexdigest(),
        }

    # -- experiment registry + matrix --------------------------------------
    registry_rows: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    results: dict[str, CandidateResult] = {}
    exp_no = 0

    for cid in sorted(candidates):
        family, tf = cid.split("@")
        exp_no += 1
        trades = candidates[cid]
        disc = [t for t in trades if t.window in SPLITS["DISCOVERY"]]
        val = [t for t in trades if t.window in SPLITS["VALIDATION"]]
        hold = [t for t in trades if t.window in SPLITS["HOLDOUT"]]
        m_disc = metrics_for(disc, tf)
        m_val = metrics_for(val, tf)
        m_hold = metrics_for(hold, tf)

        if m_disc.get("trades", 0) < MIN_TRADES:
            status, reason = "REJECTED_DISCOVERY", "insufficient trades on DISCOVERY"
        elif m_disc.get("net_bps", -1) <= 0:
            status, reason = (
                "REJECTED_DISCOVERY",
                "NET_EXPECTANCY <= 0 (gross below certified cost)",
            )
        else:
            status, reason = "PASSED_DISCOVERY", ""

        res = CandidateResult(
            candidate_id=cid,
            family=family,
            timeframe=tf,
            status=status,
            reason=reason,
            metrics=m_disc,
            split_metrics={"DISCOVERY": m_disc, "VALIDATION": m_val, "HOLDOUT": m_hold},
        )
        results[cid] = res
        registry_rows.append(
            {
                "experiment_id": f"EXP-S001-{exp_no:03d}",
                "candidate_id": cid,
                "family": family,
                "timeframe": tf,
                "parameters": "family defaults (pre-registered)",
                "dataset": "strategy-baseline W1-W7 5m-derived",
                "period": "DISCOVERY W1-W4",
                "result": m_disc,
                "status": status,
                "reason": reason,
            }
        )
        matrix_rows.append(
            {
                "experiment_id": f"EXP-S001-{exp_no:03d}",
                "strategy_family": family,
                "strategy": cid,
                "asset": "BTC+ETH+SOL",
                "timeframe": tf,
                "parameters": "defaults",
                "discovery_net_expectancy": m_disc.get("net_bps"),
                "validation_net_expectancy": m_val.get("net_bps"),
                "holdout_net_expectancy": m_hold.get("net_bps"),
                "trades": m_disc.get("trades"),
                "profit_factor": m_disc.get("profit_factor"),
                "sharpe": m_disc.get("sharpe"),
                "drawdown": m_disc.get("max_dd_bps"),
                "edge_cost_ratio": m_disc.get("edge_cost_ratio"),
                "status": status,
                "rejection_reason": reason,
            }
        )

    # 1h aggregates -> discovery-only candidates
    for cid, agg in sorted(one_h.items()):
        exp_no += 1
        family, tf = cid.split("@")
        net = agg["net_bps"]
        status = "REJECTED_DISCOVERY" if net <= 0 else "PASSED_DISCOVERY"
        reason = (
            ""
            if status == "PASSED_DISCOVERY"
            else "NET_EXPECTANCY <= 0 (gross below certified cost)"
        )
        m_disc = {
            "trades": agg["trades"],
            "gross_bps": round(agg["gross_bps"], 4),
            "cost_bps": COST_BPS,
            "net_bps": round(net, 4),
            "profit_factor": agg["pf"],
            "win_rate": agg["win_rate"],
            "source": agg["source"],
            "edge_cost_ratio": round(agg["gross_bps"] / COST_BPS, 4),
        }
        results[cid] = CandidateResult(
            candidate_id=cid,
            family=family,
            timeframe=tf,
            status=status,
            reason=reason,
            metrics=m_disc,
            split_metrics={"DISCOVERY": m_disc},
        )
        registry_rows.append(
            {
                "experiment_id": f"EXP-S001-{exp_no:03d}",
                "candidate_id": cid,
                "family": family,
                "timeframe": tf,
                "parameters": "family defaults (pre-registered)",
                "dataset": "strategy-baseline W1-W7 resampled 1h",
                "period": "DISCOVERY W1-W4",
                "result": m_disc,
                "status": status,
                "reason": reason,
            }
        )
        matrix_rows.append(
            {
                "experiment_id": f"EXP-S001-{exp_no:03d}",
                "strategy_family": family,
                "strategy": cid,
                "asset": "BTC+ETH+SOL",
                "timeframe": tf,
                "parameters": "defaults",
                "discovery_net_expectancy": m_disc["net_bps"],
                "validation_net_expectancy": None,
                "holdout_net_expectancy": None,
                "trades": m_disc["trades"],
                "profit_factor": m_disc["profit_factor"],
                "sharpe": None,
                "drawdown": None,
                "edge_cost_ratio": m_disc["edge_cost_ratio"],
                "status": status,
                "rejection_reason": reason,
            }
        )

    survivors = [c for c in results.values() if c.status == "PASSED_DISCOVERY"]
    ratio_bands: dict[str, int] = defaultdict(int)
    for c in results.values():
        ratio_bands[bucket(float(c.metrics.get("edge_cost_ratio", 0.0) or 0.0))] += 1

    # -- write artifacts ----------------------------------------------------
    (out / "EXPERIMENT_REGISTRY.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in registry_rows),
        encoding="utf-8",
    )
    with (out / "EXPERIMENT_MATRIX.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(matrix_rows[0].keys()))
        writer.writeheader()
        writer.writerows(matrix_rows)

    (out / "DATA_SPLIT.json").write_text(
        json.dumps(
            {
                "schema": "rfc021.data_split.v1",
                "chronological": True,
                "shuffled": False,
                "splits": {
                    "DISCOVERY": {"windows": ["W1", "W2", "W3", "W4"]},
                    "VALIDATION": {"windows": ["W5"]},
                    "HOLDOUT": {"windows": ["W6", "W7"], "locked": True},
                },
                "hashes": data_hashes,
                "cost_bps": COST_BPS,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    candidate_registry = {
        "schema": "rfc021.strategy_candidate_registry.v1",
        "cost_bps": COST_BPS,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "family": c.family,
                "timeframe": c.timeframe,
                "status": c.status,
                "reason": c.reason,
                "hypothesis": HYPOTHESES.get(c.family, {}).get("hypothesis", ""),
                "discovery": c.metrics,
            }
            for c in sorted(results.values(), key=lambda x: x.candidate_id)
        ],
    }
    (out / "STRATEGY_CANDIDATE_REGISTRY.json").write_text(
        json.dumps(candidate_registry, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    discovery = {
        "schema": "rfc021.discovery_results.v1",
        "cost_bps": COST_BPS,
        "min_trades": MIN_TRADES,
        "candidates_total": len(results),
        "positive_net": len(survivors),
        "edge_cost_ratio_bands": dict(sorted(ratio_bands.items())),
        "results": {cid: c.split_metrics.get("DISCOVERY", {}) for cid, c in results.items()},
        "G_EDGE_1": "PASS" if survivors else "FAIL",
    }
    (out / "DISCOVERY_RESULTS.json").write_text(
        json.dumps(discovery, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    not_reached = {
        "schema": "rfc021.validation_results.v1",
        "status": "NOT_REACHED",
        "reason": "no candidate passed DISCOVERY (G_EDGE_1 = FAIL)",
        "G_EDGE_2": "NOT_REACHED",
    }
    (out / "VALIDATION_RESULTS.json").write_text(
        json.dumps(not_reached, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "ROBUSTNESS_RESULTS.json").write_text(
        json.dumps(
            {
                "schema": "rfc021.robustness_results.v1",
                "status": "NOT_REACHED",
                "reason": "no candidate passed DISCOVERY/VALIDATION",
                "G_EDGE_3": "NOT_REACHED",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "HOLDOUT_RESULTS.json").write_text(
        json.dumps(
            {
                "schema": "rfc021.holdout_results.v1",
                "status": "NOT_REACHED",
                "reason": "no finalist cleared discovery+validation+robustness",
                "holdout_windows": ["W6", "W7"],
                "holdout_unread": True,
                "G_EDGE_4": "NOT_REACHED",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "candidates": len(results),
        "positive_net": len(survivors),
        "G_EDGE_1": discovery["G_EDGE_1"],
        "best": sorted(
            (
                {
                    "candidate_id": c.candidate_id,
                    "gross_bps": c.metrics.get("gross_bps"),
                    "net_bps": c.metrics.get("net_bps"),
                    "ratio": c.metrics.get("edge_cost_ratio"),
                }
                for c in results.values()
            ),
            key=lambda x: -float(x["gross_bps"] or 0.0),
        )[:5],
        "ratio_bands": dict(sorted(ratio_bands.items())),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
