"""ALPHA-003 — the development driver over real, cached cross-asset price.

Pipeline, exactly as the campaign contract states it:

    real OHLCV (ccxt Binance USDT-M perpetual, cached append-only)
        -> synchronised point-in-time cross-asset frame (``alpha003_features``)
        -> derived per-cell feature rows
        -> frozen hypotheses (``alpha003.SIGNALS``)
        -> development experiment on the DISCOVERY slice
        -> own-history baselines and the incremental delta between them
        -> statistics (``alpha001`` primitives) + multiplicity + selection null
        -> cost evaluation (COST_MODEL_V3, inherited, never retuned)
        -> ALPHA-003 development report

The holdout is never read.  The validation slice is not read either during development: an
ALPHA-003 development candidate would have to be taken to a separate ALPHA-003 OOS block, and
this driver stops at the development decision.

Market: one venue (Binance USDT-M perpetual) and one instrument type for every asset, so the
cross-asset comparison is not silently comparing a spot bar with a perpetual bar.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha003 as a3
from trading_bot.research import alpha003_experiment as ax
from trading_bot.research import alpha003_features as af

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "data" / "raw" / "alpha003"
PRICE_DIR = DATA_DIR / "price"
REPORT_DIR = REPO / "reports" / "alpha003"
DOCS_DIR = REPO / "docs" / "research" / "alpha003"

CAMPAIGN = "ALPHA003-DEV-001"
ENTRY_TIMEFRAMES = a3.ENTRY_TIMEFRAMES
PRIMARY_TIMEFRAME = "5m"
CONTEXT_TIMEFRAME = a3.CONTEXT_TIMEFRAME

#: The requested history.  Two years, so the frozen split covers several crypto regimes rather
#: than one trend; the split rule then derives the actual boundaries from the span the venue
#: actually serves.
PRICE_SINCE = "2024-10-01T00:00:00Z"

#: Binance USDT-M perpetual symbols for the preregistered universe.
CCXT_SYMBOL = {
    "BTCUSDT": "BTC/USDT:USDT",
    "ETHUSDT": "ETH/USDT:USDT",
    "SOLUSDT": "SOL/USDT:USDT",
    "XRPUSDT": "XRP/USDT:USDT",
}

#: Rolling window, in 1h bars, for the context correlation and beta.
CONTEXT_WINDOW = 96


# --------------------------------------------------------------------------- #
# price
# --------------------------------------------------------------------------- #


def _price_path(symbol: str, timeframe: str) -> Path:
    return PRICE_DIR / f"{symbol}_{timeframe}.json"


def fetch_ohlcv(symbol: str, timeframe: str, since_iso: str) -> list[list[float]]:
    import ccxt

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    since = exchange.parse8601(since_iso)
    out: list[list[float]] = []
    while True:
        batch = exchange.fetch_ohlcv(CCXT_SYMBOL[symbol], timeframe, since=since, limit=1000)
        if not batch:
            break
        out.extend(batch)
        since = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000.0)
    return out


def load_price(symbol: str, timeframe: str, *, refresh: bool) -> list[list[float]]:
    path = _price_path(symbol, timeframe)
    if path.is_file() and not refresh:
        loaded: list[list[float]] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    rows = fetch_ohlcv(symbol, timeframe, PRICE_SINCE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def price_digest(bars: Sequence[Sequence[float]]) -> str:
    """Content digest of a stored series, computed the same way the verifier computes it."""
    payload = json.dumps(
        [[int(bar[0]), *(round(float(value), 8) for value in bar[1:6])] for bar in bars],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# frames
# --------------------------------------------------------------------------- #


def load_frames(
    *, refresh: bool
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[list[float]]], list[dict[str, Any]]]:
    """One synchronised frame per entry timeframe, plus the 1h context series."""
    context = {
        symbol: load_price(symbol, CONTEXT_TIMEFRAME, refresh=refresh) for symbol in a3.UNIVERSE
    }
    frames: dict[str, list[dict[str, Any]]] = {}
    meta: list[dict[str, Any]] = []
    for timeframe in ENTRY_TIMEFRAMES:
        bars = {symbol: load_price(symbol, timeframe, refresh=refresh) for symbol in a3.UNIVERSE}
        frame = af.build_frame(
            timeframe=timeframe,
            bars_by_symbol=bars,
            windows=tuple(a3.LEAD_LAGS),
            regime_bars_by_symbol=context,
            context_timeframe=CONTEXT_TIMEFRAME,
        )
        frames[timeframe] = frame
        meta.append(
            {
                "timeframe": timeframe,
                "rows": len(frame),
                "first_decision_ms": int(frame[0]["decision_ms"]) if frame else None,
                "last_decision_ms": int(frame[-1]["decision_ms"]) if frame else None,
                "point_in_time_ok_rows": sum(1 for row in frame if row["point_in_time_ok"]),
                "per_symbol": {
                    symbol: {
                        "bars": len(bars[symbol]),
                        "first_open_ms": int(bars[symbol][0][0]) if bars[symbol] else None,
                        "last_open_ms": int(bars[symbol][-1][0]) if bars[symbol] else None,
                        "digest": price_digest(bars[symbol]),
                    }
                    for symbol in a3.UNIVERSE
                },
            }
        )
        del bars
    return frames, context, meta


# --------------------------------------------------------------------------- #
# the evaluation cache
# --------------------------------------------------------------------------- #


class Experiment:
    """Discovery rows, per-target labels and per-arm directions, each computed exactly once.

    The frame is shared across cells by construction; recomputing a direction series per
    report would be both slow and a chance for two reports to disagree, so every series is
    memoised here and every report reads the same object.
    """

    def __init__(self, discovery: Mapping[str, list[dict[str, Any]]], *, hurdle_bps: float) -> None:
        self.discovery = discovery
        self.hurdle_bps = hurdle_bps
        self._forwards: dict[tuple[str, str], list[float | None]] = {}
        self._directions: dict[tuple[str, str], list[int | None]] = {}

    def rows(self, timeframe: str) -> list[dict[str, Any]]:
        return self.discovery[timeframe]

    def forwards(self, target: str, timeframe: str) -> list[float | None]:
        key = (target, timeframe)
        if key not in self._forwards:
            self._forwards[key] = [
                af.forward_return_for(row, target) for row in self.discovery[timeframe]
            ]
        return self._forwards[key]

    def directions(self, cell: str, arm_id: str) -> list[int | None]:
        key = (cell, arm_id)
        if key not in self._directions:
            spec = ax.parse_cell(cell)
            target = str(spec["target"])
            leader = spec["leader"]
            lag = spec["lag"]
            self._directions[key] = [
                ax.arm_direction(
                    arm_id, af.cell_row(row, target=target, leader=leader, lag=lag)
                )
                for row in self.discovery[str(spec["timeframe"])]
            ]
        return self._directions[key]

    def summary(self, cell: str, arm_id: str) -> dict[str, Any]:
        spec = ax.parse_cell(cell)
        return ax.evaluate_directions(
            self.directions(cell, arm_id),
            self.forwards(str(spec["target"]), str(spec["timeframe"])),
            hurdle_bps=self.hurdle_bps,
        )

    def pooled_summary(self, arm_id: str, hypothesis_id: str, timeframe: str) -> dict[str, Any]:
        """A hypothesis's cells pooled within a timeframe, evaluated as one arm."""
        directions: list[int | None] = []
        forwards: list[float | None] = []
        for cell in ax.cell_ids():
            spec = ax.parse_cell(cell)
            if spec["hypothesis_id"] != hypothesis_id or spec["timeframe"] != timeframe:
                continue
            directions.extend(self.directions(cell, arm_id))
            forwards.extend(self.forwards(str(spec["target"]), timeframe))
        return ax.evaluate_directions(directions, forwards, hurdle_bps=self.hurdle_bps)


def _strip(summary: Mapping[str, Any]) -> dict[str, Any]:
    """A summary without the per-trade contribution vector, for the report artifacts."""
    return {key: value for key, value in summary.items() if key != "contributions"}


def _active_pairs(
    directions: Sequence[int | None], forwards: Sequence[float | None], rows: Sequence[Mapping[str, Any]]
) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for direction, forward, row in zip(directions, forwards, rows, strict=True):
        if direction is None or forward is None or direction == 0:
            continue
        out.append((int(row["decision_ms"]), int(direction) * float(forward) * 1e4))
    return out


def _quarter(ms: int) -> str:
    moment = dt.datetime.fromtimestamp(ms / 1000.0, dt.UTC)
    return f"{moment.year}Q{(moment.month - 1) // 3 + 1}"


def temporal_breakdown(pairs: Sequence[tuple[int, float]]) -> dict[str, Any]:
    """Per-quarter gross mean and the share of total gross carried by the best quarter."""
    if not pairs:
        return {"quarters": {}, "best_quarter": None, "best_quarter_gross_share": None}
    buckets: dict[str, list[float]] = {}
    for decision_ms, contribution in pairs:
        buckets.setdefault(_quarter(decision_ms), []).append(contribution)
    quarters = {
        name: {"n": len(values), "gross_bps": round(a1.mean(values), 6)}
        for name, values in sorted(buckets.items())
    }
    totals = {name: sum(values) for name, values in buckets.items()}
    grand = sum(totals.values())
    best = max(totals, key=lambda name: totals[name])
    share = (totals[best] / grand) if grand != 0.0 else None
    return {
        "quarters": quarters,
        "best_quarter": best,
        "best_quarter_gross_share": None if share is None else round(share, 6),
    }


def regime_breakdown(
    rows: Sequence[Mapping[str, Any]],
    directions: Sequence[int | None],
    forwards: Sequence[float | None],
    *,
    target: str,
    hurdle_bps: float,
) -> dict[str, Any]:
    """The cell's gross mean inside each causal context volatility regime, in one pass."""
    buckets: dict[str, tuple[list[int | None], list[float | None]]] = {
        "EXPANDING": ([], []),
        "CONTRACTING": ([], []),
        "UNKNOWN": ([], []),
    }
    for direction, forward, row in zip(directions, forwards, rows, strict=True):
        regime = row.get(f"vol_regime_{target}")
        label = "UNKNOWN" if regime is None else ("EXPANDING" if regime > 0 else "CONTRACTING")
        bucket = buckets[label]
        bucket[0].append(direction)
        bucket[1].append(forward)
    out: dict[str, Any] = {}
    for label, (local_directions, local_forwards) in buckets.items():
        summary = ax.evaluate_directions(local_directions, local_forwards, hurdle_bps=hurdle_bps)
        out[label] = {key: summary[key] for key in ("n", "gross_bps", "net_bps", "p_raw")}
    return out


def evaluate_cells(experiment: Experiment) -> dict[str, Any]:
    """Every declared cell on the discovery slice, with its own-history baseline."""
    cells: dict[str, Any] = {}
    for cell in ax.cell_ids():
        spec = ax.parse_cell(cell)
        hypothesis_id = str(spec["hypothesis_id"])
        target = str(spec["target"])
        full = experiment.summary(cell, hypothesis_id)
        baseline_arm = ax.INCREMENTAL_BASELINE[hypothesis_id]
        baseline = experiment.summary(cell, baseline_arm)
        incremental = round(float(full["gross_bps"]) - float(baseline["gross_bps"]), 6)
        rows = experiment.rows(str(spec["timeframe"]))
        pairs = _active_pairs(
            experiment.directions(cell, hypothesis_id),
            experiment.forwards(target, str(spec["timeframe"])),
            rows,
        )
        cells[cell] = {
            "cell": cell,
            **_strip(full),
            "baseline_arm": baseline_arm,
            "baseline_gross_bps": baseline["gross_bps"],
            "baseline_n": baseline["n"],
            "incremental_delta_bps": incremental,
            "regime": regime_breakdown(
                rows,
                experiment.directions(cell, hypothesis_id),
                experiment.forwards(target, str(spec["timeframe"])),
                target=target,
                hurdle_bps=experiment.hurdle_bps,
            ),
            "temporal": temporal_breakdown(pairs),
        }
    return cells


def evaluate_families(experiment: Experiment) -> dict[str, Any]:
    """Pooled per hypothesis and timeframe: the family-level view, for context only."""
    families: dict[str, Any] = {}
    for hypothesis_id in a3.SIGNALS:
        for timeframe in ENTRY_TIMEFRAMES:
            baseline_arm = ax.INCREMENTAL_BASELINE[hypothesis_id]
            full = experiment.pooled_summary(hypothesis_id, hypothesis_id, timeframe)
            baseline = experiment.pooled_summary(baseline_arm, hypothesis_id, timeframe)
            families[f"{hypothesis_id}|{timeframe}"] = {
                **_strip(full),
                "baseline_gross_bps": baseline["gross_bps"],
                "incremental_delta_bps": round(
                    float(full["gross_bps"]) - float(baseline["gross_bps"]), 6
                ),
            }
    return families


#: Baselines that read a pair: they are meaningless without a leader and a lag, so they are
#: pooled over the declared leader -> target pairs and the declared lag ladder instead of over
#: the targets alone.  Evaluating them without a pair yields N = 0 and would misreport the
#: baseline as unused.
PAIR_CONTEXT_BASELINES = frozenset({"A3-B1_OWN_MOMENTUM_SAME_LAG", "A3-B4_LEADER_ONLY"})


def evaluate_baselines(experiment: Experiment) -> dict[str, Any]:
    """Each declared baseline pooled over the context in which it is defined."""
    out: dict[str, Any] = {}
    for timeframe in ENTRY_TIMEFRAMES:
        rows = experiment.rows(timeframe)
        for label in ax.BASELINES:
            directions: list[int | None] = []
            forwards: list[float | None] = []
            if label in PAIR_CONTEXT_BASELINES:
                for cell in ax.cell_ids():
                    spec = ax.parse_cell(cell)
                    if spec["hypothesis_id"] != "A3-H01" or spec["timeframe"] != timeframe:
                        continue
                    leader, target, lag = spec["leader"], str(spec["target"]), spec["lag"]
                    for row, forward in zip(
                        rows, experiment.forwards(target, timeframe), strict=True
                    ):
                        directions.append(
                            ax.arm_direction(
                                label, af.cell_row(row, target=target, leader=leader, lag=lag)
                            )
                        )
                        forwards.append(forward)
            else:
                for target in a3.UNIVERSE:
                    for row, forward in zip(
                        rows, experiment.forwards(target, timeframe), strict=True
                    ):
                        directions.append(ax.arm_direction(label, af.cell_row(row, target=target)))
                        forwards.append(forward)
            summary = ax.evaluate_directions(
                directions, forwards, hurdle_bps=experiment.hurdle_bps
            )
            out[f"{label}|{timeframe}"] = _strip(summary)
    return out


def ablation_cells() -> list[str]:
    """One declared cell per hypothesis and timeframe, in registry order — never selected by
    its result."""
    chosen: list[str] = []
    for hypothesis_id in a3.SIGNALS:
        for timeframe in ENTRY_TIMEFRAMES:
            for cell in ax.cell_ids():
                spec = ax.parse_cell(cell)
                if spec["hypothesis_id"] == hypothesis_id and spec["timeframe"] == timeframe:
                    chosen.append(cell)
                    break
    return chosen


def evaluate_ablations(experiment: Experiment) -> dict[str, Any]:
    """Per-cell attribution arms: the frozen rule against the same rule with one term removed."""
    out: dict[str, Any] = {}
    for cell in ablation_cells():
        hypothesis_id = str(ax.parse_cell(cell)["hypothesis_id"])
        variants: dict[str, Any] = {}
        for label in ax.ABLATIONS[hypothesis_id]:
            arm_id = (
                hypothesis_id if label == "FULL" else label
            )
            variants[label] = _strip(experiment.summary(cell, arm_id))
        out[cell] = variants
    return out


def evaluate_nontraded(experiment: Experiment) -> dict[str, Any]:
    """The declared contrast arms: reported as a differential, never promoted."""
    out: dict[str, Any] = {}
    for timeframe in ENTRY_TIMEFRAMES:
        rows = experiment.rows(timeframe)
        for arm_id in a3.NON_TRADED_ARMS:
            for target in a3.UNIVERSE:
                values: list[float] = []
                for row in rows:
                    features = af.cell_row(
                        row, target=target, leader="BTCUSDT", lag=a3.LEAD_LAGS[0]
                    )
                    forward = af.forward_return_for(row, target)
                    if forward is None:
                        continue
                    if ax.nontraded_flag(arm_id, features) is True:
                        values.append(forward * 1e4)
                out[f"{arm_id}|{target}|{timeframe}"] = {
                    "n": len(values),
                    "mean_forward_bps": round(a1.mean(values), 6) if values else 0.0,
                }
    return out


def lead_lag_matrix(cells: Mapping[str, Any]) -> dict[str, Any]:
    """The descriptive leader -> target x lag x timeframe table."""
    rows: list[dict[str, Any]] = []
    for cell, summary in cells.items():
        spec = ax.parse_cell(cell)
        if spec["hypothesis_id"] != "A3-H01":
            continue
        rows.append(
            {
                "leader": spec["leader"],
                "target": spec["target"],
                "lag": spec["lag"],
                "timeframe": spec["timeframe"],
                "n": summary["n"],
                "gross_bps": summary["gross_bps"],
                "baseline_gross_bps": summary["baseline_gross_bps"],
                "incremental_delta_bps": summary["incremental_delta_bps"],
                "ic": summary["ic"],
                "p_raw": summary["p_raw"],
            }
        )
    rows.sort(
        key=lambda item: (
            str(item["leader"]),
            str(item["target"]),
            int(item["lag"]),
            str(item["timeframe"]),
        )
    )
    return {"campaign": CAMPAIGN, "cells": rows}


def context_statistics(context: Mapping[str, list[list[float]]]) -> dict[str, Any]:
    """Trailing causal 1h correlation and beta of each asset to the market, reported only."""
    returns: dict[str, list[float | None]] = {}
    for symbol, bars in context.items():
        closes = [float(bar[4]) for bar in bars]
        returns[symbol] = [
            (closes[index] / closes[index - 1] - 1.0)
            if index >= 1 and closes[index - 1] > 0.0
            else None
            for index in range(len(closes))
        ]
    out: dict[str, Any] = {}
    for symbol in a3.UNIVERSE:
        asset = returns[symbol]
        corr_values: list[float] = []
        beta_values: list[float] = []
        for index in range(CONTEXT_WINDOW, len(asset)):
            window_asset: list[float] = []
            window_market: list[float] = []
            complete = True
            for position in range(index - CONTEXT_WINDOW + 1, index + 1):
                own = asset[position]
                others = [returns[other][position] for other in a3.UNIVERSE]
                if own is None or any(value is None for value in others):
                    complete = False
                    break
                window_asset.append(float(own))
                window_market.append(
                    sum(float(value) for value in others if value is not None) / len(a3.UNIVERSE)
                )
            if not complete:
                continue
            mean_asset = a1.mean(window_asset)
            mean_market = a1.mean(window_market)
            variance = a1.mean([(value - mean_market) ** 2 for value in window_market])
            if variance <= 0.0:
                continue
            covariance = a1.mean(
                [
                    (window_asset[i] - mean_asset) * (window_market[i] - mean_market)
                    for i in range(len(window_asset))
                ]
            )
            corr_values.append(a1.pearson(window_asset, window_market))
            beta_values.append(covariance / variance)
        out[symbol] = {
            "observations": len(corr_values),
            "mean_corr_market": round(a1.mean(corr_values), 6) if corr_values else None,
            "mean_beta_market": round(a1.mean(beta_values), 6) if beta_values else None,
            "window_1h_bars": CONTEXT_WINDOW,
            "note": "trailing window only; never a full-sample regression",
        }
    return out


def dataset_storage() -> dict[str, Any]:
    """Persisted dataset size, so growth is observable rather than assumed."""
    files = 0
    total = 0
    if DATA_DIR.exists():
        for path in DATA_DIR.rglob("*.json"):
            files += 1
            total += path.stat().st_size
    return {"files": files, "mib": round(total / (1024 * 1024), 3)}


def disk_status() -> dict[str, Any]:
    import shutil

    usage = shutil.disk_usage(REPO)
    return {
        "total_gib": round(usage.total / (1024**3), 2),
        "used_gib": round(usage.used / (1024**3), 2),
        "free_gib": round(usage.free / (1024**3), 2),
        "used_fraction": round(usage.used / usage.total, 4),
    }


def write_json(name: str, payload: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def write_text(name: str, text: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ALPHA-003 development driver")
    parser.add_argument("--refresh-price", action="store_true")
    args = parser.parse_args(argv)

    frames, context, meta = load_frames(refresh=args.refresh_price)

    starts = [int(item["first_decision_ms"]) for item in meta if item["first_decision_ms"]]
    ends = [int(item["last_decision_ms"]) for item in meta if item["last_decision_ms"]]
    common_start = max(starts)
    common_end = min(ends)
    boundaries = ax.calendar_boundaries(common_start, common_end)

    discovery = {
        timeframe: [
            row for row in frame if ax.in_window(int(row["decision_ms"]), boundaries["discovery"])
        ]
        for timeframe, frame in frames.items()
    }
    design_n = max(1, len(discovery[PRIMARY_TIMEFRAME]))
    hurdle = a1.min_gross_hurdle_bps(n_effective=design_n, sigma_trade_bps=ax.DESIGN_SIGMA_BPS)
    hurdle_bps = float(hurdle["min_gross_alpha_hurdle_bps"])

    experiment = Experiment(discovery, hurdle_bps=hurdle_bps)
    cells = evaluate_cells(experiment)
    families = evaluate_families(experiment)
    baselines = evaluate_baselines(experiment)
    ablations = evaluate_ablations(experiment)
    nontraded = evaluate_nontraded(experiment)

    # multiplicity across every declared cell, at every timeframe
    ordered = ax.cell_ids()
    pvalues = [float(cells[cell]["p_raw"]) for cell in ordered]
    bh = a1.benjamini_hochberg(pvalues, q=ax.BH_Q)
    holm = a1.holm(pvalues, alpha=ax.HOLM_ALPHA)
    multiplicity: dict[str, dict[str, Any]] = {
        cell: {
            "p_raw": round(pvalues[index], 8),
            "bh_pass": bool(bh[index]),
            "holm_pass": bool(holm[index]),
        }
        for index, cell in enumerate(ordered)
    }

    # the family-level selection null: every declared cell's signal, circularly shifted
    null_arms = {
        cell: (
            experiment.directions(cell, str(ax.parse_cell(cell)["hypothesis_id"])),
            experiment.forwards(
                str(ax.parse_cell(cell)["target"]), str(ax.parse_cell(cell)["timeframe"])
            ),
        )
        for cell in ordered
    }
    null = ax.permutation_null(null_arms)
    p_null = float(null.get("p_null_best_ge_observed", 1.0))

    decisions: dict[str, Any] = {}
    for cell in ordered:
        summary = cells[cell]
        gate = ax.promotion_gate(
            summary=summary,
            incremental_delta_bps=float(summary["incremental_delta_bps"]),
            bh_pass=multiplicity[cell]["bh_pass"],
            holm_pass=multiplicity[cell]["holm_pass"],
            p_null_best_ge_observed=p_null,
        )
        decisions[cell] = {
            **multiplicity[cell],
            "incremental_delta_bps": summary["incremental_delta_bps"],
            **gate,
        }

    candidates = sorted(
        cell
        for cell, decision in decisions.items()
        if decision["verdict"] == "VALIDATION_CANDIDATE"
    )
    raw_positive = [cell for cell in ordered if float(cells[cell]["gross_bps"]) > 0.0]
    incrementally_positive = [
        cell for cell in ordered if float(cells[cell]["incremental_delta_bps"]) > 0.0
    ]
    supported = [
        cell
        for cell in ordered
        if float(cells[cell]["p_raw"]) < 0.05 and multiplicity[cell]["bh_pass"]
    ]
    economically_admissible = [cell for cell in ordered if bool(cells[cell]["gross_above_hurdle"])]
    best_gross = max(ordered, key=lambda cell: float(cells[cell]["gross_bps"]))
    best_incremental = max(
        ordered, key=lambda cell: float(cells[cell]["incremental_delta_bps"])
    )

    dataset_report: dict[str, Any] = {
        "campaign": CAMPAIGN,
        "market": "Binance USDT-M perpetual (ccxt binanceusdm), one venue and one instrument type",
        "requested_since": PRICE_SINCE,
        "universe": list(a3.UNIVERSE),
        "context_timeframe": CONTEXT_TIMEFRAME,
        "context_statistics": context_statistics(context),
        "storage": dataset_storage(),
        "frames": meta,
        "calendar": {
            "common_start_ms": common_start,
            "common_end_ms": common_end,
            "common_span_days": round((common_end - common_start) / 86_400_000.0, 3),
            "boundaries": {key: list(value) for key, value in boundaries.items()},
        },
        "discovery_rows_by_timeframe": {tf: len(rows) for tf, rows in discovery.items()},
        "holdout_read": False,
    }

    feature_report: dict[str, Any] = {
        "campaign": CAMPAIGN,
        "feature_version": af.feature_version(),
        "feature_config": af.FEATURE_CONFIG,
        "feature_names": list(af.FEATURE_NAMES),
        "required_features": {arm: list(names) for arm, names in af.REQUIRED_FEATURES.items()},
        "point_in_time_rows": {item["timeframe"]: item["point_in_time_ok_rows"] for item in meta},
    }

    development_results: dict[str, Any] = {
        "campaign": CAMPAIGN,
        "preregistration_hash": a3.preregistration_hash(),
        "feature_version": af.feature_version(),
        "cost_model": {"name": "COST_MODEL_V3", "cost_bps": a1.COST_BPS_V3, "retuned": False},
        "hurdle": hurdle,
        "hurdle_bps": hurdle_bps,
        "design_n": design_n,
        "cells": cells,
        "families": families,
        "multiplicity": multiplicity,
        "permutation_null": null,
        "nontraded_arms": nontraded,
        "decisions": decisions,
        "oos_candidates": candidates,
        "counts": {
            "cells": len(ordered),
            "raw_positive": len(raw_positive),
            "incrementally_positive": len(incrementally_positive),
            "statistically_supported": len(supported),
            "economically_admissible": len(economically_admissible),
        },
        "best_gross_cell": best_gross,
        "best_incremental_cell": best_incremental,
        "holdout_read": False,
        "validation_read": False,
        "split": {key: list(value) for key, value in boundaries.items()},
    }

    baseline_report: dict[str, Any] = {
        "campaign": CAMPAIGN,
        "baselines": baselines,
        "baseline_definition": {
            "A3-B0_UNCONDITIONAL_LONG": "always long — the unconditional return of the target",
            "A3-B1_OWN_MOMENTUM_SAME_LAG": "the target's own move at the hypothesis's own horizon",
            "A3-B1_OWN_MOMENTUM_R": "the target's own relative-window momentum, no cross-asset term",
            "A3-B3_MARKET_DIRECTION": "trade the target on the common market factor, no pair at all",
            "A3-B4_LEADER_ONLY": "the frozen H1 rule with the target-lag condition removed",
            "A3-B2_PERMUTATION": "the cross-asset signal circularly shifted against the returns",
        },
        "incremental_baseline_by_hypothesis": dict(ax.INCREMENTAL_BASELINE),
        "pair_context_baselines": sorted(PAIR_CONTEXT_BASELINES),
        "pair_context_note": (
            "a baseline that reads a pair is pooled over the declared pairs and lags rather than"
            " over targets alone, because it has no meaning without a leader and a lag"
        ),
        "nontraded_note": (
            "the declared contrast arms are counted per target; for the BTCUSDT target the declared"
            " BTCUSDT leader degenerates to a self-pair, which is reported for completeness rather"
            " than hidden"
        ),
        "ablation_cells": ablation_cells(),
        "ablations": ablations,
    }

    run_report: dict[str, Any] = {
        "campaign": CAMPAIGN,
        "preregistration_hash": a3.preregistration_hash(),
        "feature_version": af.feature_version(),
        "cost_model": {"name": "COST_MODEL_V3", "cost_bps": a1.COST_BPS_V3, "retuned": False},
        "statistical_gate": a3.PREREGISTRATION["statistical_gate"],
        "assets": list(a3.UNIVERSE),
        "entry_timeframes": list(ENTRY_TIMEFRAMES),
        "lead_lags": list(a3.LEAD_LAGS),
        "pairs": [list(pair) for pair in a3.LEADER_TARGET_PAIRS],
        "hypotheses": [item["hypothesis_id"] for item in a3.HYPOTHESES],
        "hurdle_bps": hurdle_bps,
        "design_n": design_n,
        "cells": {
            cell: {key: value for key, value in summary.items() if key not in ("regime", "temporal")}
            for cell, summary in cells.items()
        },
        "decisions": {
            cell: {key: value for key, value in decision.items() if key != "checks"}
            for cell, decision in decisions.items()
        },
        "counts": development_results["counts"],
        "best_gross_cell": best_gross,
        "best_incremental_cell": best_incremental,
        "oos_candidates": candidates,
        "holdout_read": False,
        "validation_read": False,
        "errors": [],
        "prohibitions": list(a3.PREREGISTRATION["prohibitions"]),
        "disk": disk_status(),
        "data_adequacy": {
            "common_span_days": dataset_report["calendar"]["common_span_days"],
            "required_months": 12,
            "clause": (
                "the frozen split needs at least twelve months of synchronised bars so that the"
                " discovery and validation slices each cover more than one market regime"
            ),
            "consequence": (
                "the requested span is honoured by the venue up to the cached span reported above,"
                " and no hypothesis, threshold, pair, lag or split was changed to fit it"
            ),
        },
    }

    write_json("ALPHA003_DATASET_REPORT.json", dataset_report)
    write_text("ALPHA003_DATASET_REPORT.md", _dataset_md(dataset_report))
    write_json("ALPHA003_FEATURE_REPORT.json", feature_report)
    write_text("ALPHA003_FEATURE_REPORT.md", _feature_md(feature_report))
    write_json("ALPHA003_DEVELOPMENT_RESULTS.json", development_results)
    write_text("ALPHA003_DEVELOPMENT_RESULTS.md", _development_md(development_results))
    write_json("ALPHA003_BASELINE_COMPARISON.json", baseline_report)
    write_text("ALPHA003_BASELINE_COMPARISON.md", _baseline_md(baseline_report))
    matrix = lead_lag_matrix(cells)
    write_json("ALPHA003_LEAD_LAG_MATRIX.json", matrix)
    write_text("ALPHA003_LEAD_LAG_MATRIX.md", _lead_lag_md(matrix))
    regime = _regime_report(development_results)
    write_json("ALPHA003_REGIME_REPORT.json", regime)
    write_text("ALPHA003_REGIME_REPORT.md", _regime_md(regime))
    write_json("RUN_REPORT.json", run_report)
    write_text("RUN_REPORT.md", _run_md(run_report))
    write_json("FINAL_REPORT.json", run_report)
    write_text("FINAL_REPORT.md", _final_md(run_report))

    for name in ("ALPHA003_PREREGISTRATION.md", "ALPHA003_PREREGISTRATION.json"):
        source = DOCS_DIR / name
        if source.is_file():
            write_text(name, source.read_text(encoding="utf-8"))

    print(f"cells evaluated: {len(ordered)}")
    print(f"design_n: {design_n} · hurdle: {hurdle_bps} bps")
    print(f"best gross cell: {best_gross} = {cells[best_gross]['gross_bps']} bps")
    print(
        f"best incremental cell: {best_incremental} = "
        f"{cells[best_incremental]['incremental_delta_bps']} bps"
    )
    print(f"counts: {development_results['counts']}")
    print(f"validation candidates: {candidates or 'none'}")
    print("reports written to", REPORT_DIR)
    return 0


def _regime_report(development: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "campaign": CAMPAIGN,
        "regimes": {cell: summary["regime"] for cell, summary in development["cells"].items()},
        "definition": "causal context volatility regime from the most recent closed 1h bar",
    }


# --------------------------------------------------------------------------- #
# markdown renderers
# --------------------------------------------------------------------------- #


def _table(rows: Sequence[Sequence[Any]], header: Sequence[str]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def _dataset_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — DATASET REPORT",
        "",
        f"- campaign: **{report['campaign']}**",
        f"- market: {report['market']}",
        f"- requested since: {report['requested_since']}",
        f"- universe: {', '.join(report['universe'])} · context: {report['context_timeframe']}",
        f"- holdout read: **{report['holdout_read']}**",
        f"- persisted dataset: {report['storage']['mib']} MiB across "
        f"{report['storage']['files']} files",
        f"- common span: {report['calendar']['common_span_days']} days",
        "",
        "## Split (calendar, identical for every asset, pair, lag and timeframe)",
        "",
    ]
    lines += _table(
        [
            [name, value[0], value[1]]
            for name, value in sorted(report["calendar"]["boundaries"].items())
        ],
        ["slice", "from (ms)", "to (ms)"],
    )
    lines += ["", "## Frames", ""]
    lines += _table(
        [
            [
                item["timeframe"],
                item["rows"],
                item["point_in_time_ok_rows"],
                item["first_decision_ms"],
                item["last_decision_ms"],
            ]
            for item in report["frames"]
        ],
        ["timeframe", "rows", "pit ok", "first decision", "last decision"],
    )
    lines += ["", "## Per symbol (bars and content digest)", ""]
    lines += _table(
        [
            [item["timeframe"], symbol, values["bars"], values["digest"][:16]]
            for item in report["frames"]
            for symbol, values in sorted(item["per_symbol"].items())
        ],
        ["timeframe", "symbol", "bars", "digest"],
    )
    lines += ["", "## Context statistics (reported, never inputs)", ""]
    lines += _table(
        [
            [
                symbol,
                values["observations"],
                values["mean_corr_market"],
                values["mean_beta_market"],
            ]
            for symbol, values in sorted(report["context_statistics"].items())
        ],
        ["asset", "1h windows", "mean corr vs market", "mean beta vs market"],
    )
    return "\n".join(lines) + "\n"


def _feature_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — FEATURE REPORT",
        "",
        f"- feature_version: `{report['feature_version']}`",
        f"- features: {', '.join('`' + name + '`' for name in report['feature_names'])}",
        "",
        "## Construction constants (frozen before any result)",
        "",
    ]
    lines += _table(
        [[key, value] for key, value in sorted(report["feature_config"].items())],
        ["key", "value"],
    )
    lines += ["", "## Required features per arm", ""]
    lines += _table(
        [
            [arm, ", ".join(names) or "(none)"]
            for arm, names in sorted(report["required_features"].items())
        ],
        ["arm", "required features"],
    )
    lines += ["", "## Point-in-time rows per timeframe", ""]
    lines += _table(
        [[tf, rows] for tf, rows in sorted(report["point_in_time_rows"].items())],
        ["timeframe", "rows with available_ms <= decision_ms"],
    )
    return "\n".join(lines) + "\n"


def _development_md(report: Mapping[str, Any]) -> str:
    decisions = report["decisions"]
    lines = [
        "# ALPHA-003 — DEVELOPMENT RESULTS",
        "",
        f"- campaign: **{report['campaign']}**",
        f"- preregistration_hash: `{report['preregistration_hash']}`",
        f"- cost model: {report['cost_model']['name']} at {report['cost_model']['cost_bps']} bps "
        f"(retuned: {report['cost_model']['retuned']})",
        f"- design_n: {report['design_n']} · hurdle: {report['hurdle_bps']} bps",
        f"- holdout read: **{report['holdout_read']}** · validation read: "
        f"**{report['validation_read']}**",
        f"- counts: {report['counts']}",
        f"- validation candidates: **{report['oos_candidates'] or 'none'}**",
        "",
        "## Decision table",
        "",
    ]
    rows: list[list[Any]] = []
    for cell in sorted(report["cells"]):
        summary = report["cells"][cell]
        decision = decisions[cell]
        mult = report["multiplicity"][cell]
        rows.append(
            [
                cell,
                summary["n"],
                summary["gross_bps"],
                summary["net_bps"],
                summary["baseline_gross_bps"],
                summary["incremental_delta_bps"],
                summary["p_raw"],
                "PASS" if mult["bh_pass"] and mult["holm_pass"] else "no",
                "PASS" if summary["gross_above_hurdle"] else "FAIL",
                decision["verdict"],
            ]
        )
    lines += _table(
        rows,
        [
            "cell",
            "N",
            "gross bps",
            "net bps",
            "own baseline bps",
            "incremental delta bps",
            "p_raw",
            "multiple testing",
            "economic gate",
            "verdict",
        ],
    )
    lines += ["", "## Family view (pooled across the hypothesis's cells)", ""]
    lines += _table(
        [
            [
                name,
                summary["n"],
                summary["gross_bps"],
                summary["baseline_gross_bps"],
                summary["incremental_delta_bps"],
                summary["p_raw"],
                summary["power_class"],
            ]
            for name, summary in sorted(report["families"].items())
        ],
        ["family", "N", "gross bps", "own baseline bps", "incremental delta bps", "p_raw", "power"],
    )
    lines += ["", "## Selection null", ""]
    null = report["permutation_null"]
    arms = null.get("arms")
    lines.append(f"- best arm under the observed data: `{null.get('best_arm')}`")
    lines.append(f"- observed best gross: {null.get('observed_best_bps')} bps")
    lines.append(f"- p(best null >= observed best): {null.get('p_null_best_ge_observed')}")
    lines.append(f"- arms used: {len(arms) if isinstance(arms, list) else arms}")
    lines += ["", "## Declared non-traded arms (reported, never promoted)", ""]
    lines += _table(
        [
            [name, value["n"], value["mean_forward_bps"]]
            for name, value in sorted(report["nontraded_arms"].items())
        ],
        ["arm | target | timeframe", "N", "mean forward bps"],
    )
    return "\n".join(lines) + "\n"


def _baseline_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — BASELINE COMPARISON",
        "",
        "The campaign's question is the *difference* between a cross-asset arm and its own-history",
        "baseline, so the baselines are reported in full rather than as a footnote.",
        "",
    ]
    lines += _table(
        [
            [name, summary["n"], summary["gross_bps"], summary["net_bps"], summary["p_raw"]]
            for name, summary in sorted(report["baselines"].items())
        ],
        ["baseline", "N", "gross bps", "net bps", "p_raw"],
    )
    lines += ["", "## Incremental baseline per hypothesis", ""]
    for hypothesis_id, arm in sorted(report["incremental_baseline_by_hypothesis"].items()):
        lines.append(f"- {hypothesis_id}: `{arm}`")
    lines += ["", "## Ablations (attribution only; never used to promote a candidate)", ""]
    for cell, variants in sorted(report["ablations"].items()):
        lines.append(f"### {cell}")
        lines.append("")
        lines += _table(
            [
                [label, summary["n"], summary["gross_bps"], summary["net_bps"]]
                for label, summary in variants.items()
            ],
            ["variant", "N", "gross bps", "net bps"],
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _lead_lag_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — LEAD-LAG MATRIX",
        "",
        "Descriptive: every declared leader -> target pair, lag and timeframe, with the arm's",
        "own-history baseline beside it.  A positive incremental delta is the only interesting",
        "column.",
        "",
    ]
    lines += _table(
        [
            [
                item["leader"],
                item["target"],
                item["lag"],
                item["timeframe"],
                item["n"],
                item["gross_bps"],
                item["baseline_gross_bps"],
                item["incremental_delta_bps"],
                item["ic"],
                item["p_raw"],
            ]
            for item in report["cells"]
        ],
        [
            "leader",
            "target",
            "lag",
            "tf",
            "N",
            "gross bps",
            "own baseline bps",
            "incremental delta bps",
            "IC",
            "p_raw",
        ],
    )
    return "\n".join(lines) + "\n"


def _regime_md(report: Mapping[str, Any]) -> str:
    lines = ["# ALPHA-003 — REGIME REPORT", "", f"- definition: {report['definition']}", ""]
    for cell, regimes in sorted(report["regimes"].items()):
        lines.append(f"### {cell}")
        lines.append("")
        lines += _table(
            [
                [label, values["n"], values["gross_bps"], values["net_bps"], values["p_raw"]]
                for label, values in regimes.items()
            ],
            ["regime", "N", "gross bps", "net bps", "p_raw"],
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def _run_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — RUN REPORT",
        "",
        f"- campaign: **{report['campaign']}**",
        f"- preregistration_hash: `{report['preregistration_hash']}`",
        f"- feature_version: `{report['feature_version']}`",
        f"- cost model: {report['cost_model']['name']} at {report['cost_model']['cost_bps']} bps "
        f"(retuned: {report['cost_model']['retuned']})",
        f"- assets: {', '.join(report['assets'])}",
        f"- entry timeframes: {', '.join(report['entry_timeframes'])} · lead lags: "
        f"{report['lead_lags']}",
        f"- pairs: {', '.join(f'{a}->{b}' for a, b in report['pairs'])}",
        f"- hurdle: {report['hurdle_bps']} bps over design_n = {report['design_n']}",
        f"- holdout read: **{report['holdout_read']}** · validation read: "
        f"**{report['validation_read']}**",
        f"- validation candidates: **{report['oos_candidates'] or 'none'}**",
        f"- counts: {report['counts']}",
        f"- best gross cell: `{report['best_gross_cell']}`",
        f"- best incremental cell: `{report['best_incremental_cell']}`",
        f"- errors: {report['errors'] or 'none'}",
        f"- disk: {report['disk']}",
        "",
        "## Data adequacy",
        "",
        f"- common span: {report['data_adequacy']['common_span_days']} days (required >= "
        f"{report['data_adequacy']['required_months']} months)",
        f"- clause: {report['data_adequacy']['clause']}",
        f"- consequence: {report['data_adequacy']['consequence']}",
        "",
        "## Prohibited (unchanged)",
        "",
    ]
    lines.extend(f"- {item}" for item in report["prohibitions"])
    return "\n".join(lines) + "\n"


def _final_md(report: Mapping[str, Any]) -> str:
    decisions = report["decisions"]
    rejected = [cell for cell, decision in decisions.items() if decision["verdict"] == "REJECT"]
    inconclusive = [
        cell for cell, decision in decisions.items() if decision["verdict"] == "INCONCLUSIVE"
    ]
    if report["oos_candidates"]:
        decision = "VALIDATION_CANDIDATE"
    elif len(rejected) == len(decisions):
        decision = "NO_ALPHA"
    else:
        decision = "NO_ALPHA_WITH_UNTESTED_HYPOTHESES"
    lines = [
        "# ALPHA-003 — FINAL REPORT",
        "",
        f"`DECISION = {decision}`",
        "",
        "## Decision table",
        "",
    ]
    lines += _table(
        [
            [
                cell,
                summary["n"],
                summary["gross_bps"],
                summary["net_bps"],
                summary["incremental_delta_bps"],
                decisions[cell]["verdict"],
            ]
            for cell, summary in sorted(report["cells"].items())
        ],
        ["cell", "N", "gross bps", "net bps", "incremental delta bps", "verdict"],
    )
    lines += [
        "",
        f"- rejected: {len(rejected)} / {len(decisions)}",
        f"- inconclusive: {inconclusive or 'none'}",
        f"- validation candidates: {report['oos_candidates'] or 'none'}",
        f"- holdout read: {report['holdout_read']}",
        "",
        "## What it tells the system",
        "",
        "The campaign's question is whether another asset's information adds usable predictive",
        "value about the target's forward return after controlling for the target's own history.",
        "The answer is read from the incremental delta column above: an arm that merely replicates",
        "own-asset momentum is a failure of this campaign, not a candidate.",
        "",
        "## Prohibited (unchanged)",
        "",
    ]
    lines.extend(f"- {item}" for item in report["prohibitions"])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
