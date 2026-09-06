"""EDGE-RESEARCH-002 hypothesis executor.

Runs every pre-registered hypothesis exactly once against the DISCOVERY
slice of the current window using the certified R1 simulation semantics.
Conditioning is gate-only (``bar_filter``); classification uses the
unchanged pre-registered acceptance rule. Determinism is verified by the
caller via double execution.
"""

from __future__ import annotations

import json
from typing import Any

from trading_bot.discovery.criteria import FreezeCriteria
from trading_bot.discovery.runner import run_discovery
from trading_bot.discovery.split import SplitAccessor
from trading_bot.edge_research.hypotheses import (
    Hypothesis,
    atr_labeler,
    cross_sectional_rs_labeler,
    htf_pullback_labeler,
    htf_trend_labeler,
    preregistered_hypotheses,
)

SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")


def _family_instances(names: tuple[str, ...] | None) -> list[Any]:
    from trading_bot.discovery.runner import FAMILIES

    if names is None:
        return [cls() for cls in FAMILIES]
    return [cls() for cls in FAMILIES if cls().family_name in set(names)]


def _bar_filters_for(
    hyp: Hypothesis, datasets: dict[str, Any], accessor: SplitAccessor
) -> dict[str, Any]:
    """Bind the pre-registered conditioning gate per symbol."""
    candles_by_symbol = {sym: list(ds.candles) for sym, ds in datasets.items()}
    if hyp.hypothesis_id == "H-A-MTF-CONTEXT":
        return {
            sym: htf_trend_labeler(candles_by_symbol[sym], fast_factor=3, slow_factor=12)
            for sym in SYMBOLS
        }
    if hyp.hypothesis_id == "H-B-VOL-MID-BUCKET":
        return {
            sym: atr_labeler(
                accessor.read(sym, "discovery"), period=288, low_q=0.33, high_q=0.66
            )
            for sym in SYMBOLS
        }
    if hyp.hypothesis_id == "H-C-MEAN-REVERSION-FADE":
        return {}
    if hyp.hypothesis_id == "H-D-TREND-PULLBACK":
        return {
            sym: htf_pullback_labeler(candles_by_symbol[sym], factor=3, want="down")
            for sym in SYMBOLS
        }
    if hyp.hypothesis_id == "H-E-CROSS-SECTIONAL-RS":
        closes_by_symbol = {
            sym: {c.timestamp: c.close for c in candles}
            for sym, candles in candles_by_symbol.items()
        }
        return {
            sym: cross_sectional_rs_labeler(closes_by_symbol, target=sym, lookback_bars=288)
            for sym in SYMBOLS
        }
    if hyp.hypothesis_id == "H-F-US-SESSION":
        return {sym: hyp.bar_filter for sym in SYMBOLS}
    raise ValueError(f"unregistered hypothesis: {hyp.hypothesis_id}")


def execute_hypotheses(
    accessor: SplitAccessor, datasets: dict[str, Any], criteria: FreezeCriteria
) -> tuple[list[dict[str, Any]], list[Any], list[Any], int]:
    """Run every pre-registered hypothesis exactly once.

    Returns (results, runs, ledgers, total_passers). One execution per
    configuration: the caller may invoke this twice to prove determinism,
    but the recorded evidence is from the first pass.
    """
    results: list[dict[str, Any]] = []
    runs_all: list[Any] = []
    ledgers_all: list[Any] = []

    for hyp in preregistered_hypotheses():
        bar_filters = _bar_filters_for(hyp, datasets, accessor)
        instances = _family_instances(hyp.family_names)
        directions: tuple[str, ...] = (
            ("LONG",) if hyp.hypothesis_id == "H-E-CROSS-SECTIONAL-RS" else ("LONG", "SHORT")
        )

        hypothesis_runs: list[Any] = []
        hypothesis_ledgers: list[Any] = []
        for sym in SYMBOLS:
            result = run_discovery(
                accessor,
                symbols=(sym,),
                regime_filters=("ALL",),
                directions=directions,
                min_trades=30,
                bar_filter=bar_filters.get(sym),
                run_instances=instances,
            )
            hypothesis_runs.extend(result.runs)
            hypothesis_ledgers.extend(result.ledgers)

        passers: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        for run in hypothesis_runs:
            if run.trades < 30:
                rejections.append(
                    {
                        "family": run.family,
                        "symbol": run.symbol,
                        "direction": run.direction,
                        "reason": "trades<30",
                        "trades": run.trades,
                        "net_expectancy_r": round(run.net_expectancy_r, 6),
                        "net_pf": round(run.net_pf, 6) if run.net_pf == run.net_pf else None,
                    }
                )
                continue
            passed, failures = criteria.evaluate(run)
            entry = {
                "family": run.family,
                "symbol": run.symbol,
                "direction": run.direction,
                "trades": run.trades,
                "net_expectancy_r": round(run.net_expectancy_r, 6),
                "net_pf": round(run.net_pf, 6) if run.net_pf == run.net_pf else None,
                "failures": failures,
            }
            (passers if passed else rejections).append(entry)

        results.append(
            {
                "hypothesis_id": hyp.hypothesis_id,
                "config_sha256": hyp.config_sha256,
                "runs": [r.to_dict() for r in hypothesis_runs],
                "passers": passers,
                "rejections": rejections,
                "runs_total": len(hypothesis_runs),
                "runs_ge_30_trades": sum(1 for r in hypothesis_runs if r.trades >= 30),
            }
        )
        runs_all.extend(hypothesis_runs)
        ledgers_all.extend(hypothesis_ledgers)

    total_passers = sum(len(r["passers"]) for r in results)
    return results, runs_all, ledgers_all, total_passers


def results_digest(results: list[dict[str, Any]]) -> str:
    """Stable digest used for the determinism comparison."""
    return json.dumps(results, sort_keys=True, default=str)
