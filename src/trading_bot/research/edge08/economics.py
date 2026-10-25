"""WP-EDGE-08 — the economic matrix: every arm, every window, every cost scenario.

One table, rendered from one reading per cell, so no reader has to reconcile two documents:

* **arms** — the six proposed books (three QUALITY, three ACTIVE) and the three CURRENT books the
  comparison needs;
* **windows** — ``DEV``, ``VAL`` and ``OOS`` of the corpus being read, all three declared before
  anything ran;
* **scenarios** — ``BASE``, ``2X_FEES`` and ``ADVERSE`` from ``COST_MODEL_V3``'s own components.

Alongside the money it carries the readings a verdict is computed from: the block-bootstrap
interval, the three time blocks, the per-asset and per-market-context breakdowns, leave-out-largest
and the serial-dependence pair. Cost sensitivity is its own reading: the net at ``BASE`` against the
net at ``2X_FEES`` and ``ADVERSE``, and how many basis points of margin each trade kept.

Research only: nothing here sizes a position, promotes a book or touches a risk limit.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge01.campaign import ADMISSION_CRITERIA, _Corpus, _gate
from trading_bot.research.edge08.analysis import extras, leave_out_largest, refusal_funnel_of
from trading_bot.research.edge08.registration import MIN_TRADES, WINDOW_ORDER
from trading_bot.research.edge08.runner import COST_SCENARIOS, run_arm

__all__ = [
    "arm_matrix",
    "cost_sensitivity",
    "gate_status",
    "matrix_row",
]


def matrix_row(*, run: dict[str, Any], track: str, corpus: _Corpus) -> dict[str, Any]:
    """One cell of the matrix: the money, the robustness readings, and where the loss came from."""
    metrics = run["metrics"]
    trades = run["trades"]
    readings = extras(
        trades=trades,
        window=run["window"],
        n_assets=len(corpus.bars_by_asset),
        timeframe=run["timeframe"],
    )
    start_equity = 10_000.0
    return {
        "arm": run["arm"],
        "track": track,
        "window_label": run["window_label"],
        "scenario": run["scenario"],
        "timeframe": run["timeframe"],
        "trades": metrics.get("trades"),
        "gross_usdt": metrics.get("gross_usdt"),
        "fees_usdt": metrics.get("fees_usdt"),
        "price_costs_usdt": metrics.get("price_costs_usdt"),
        "net_usdt": metrics.get("net_usdt"),
        "expectancy_usdt": metrics.get("expectancy_usdt"),
        "profit_factor": metrics.get("profit_factor"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "payoff_ratio": metrics.get("payoff_ratio"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe_annualised": metrics.get("sharpe_annualised"),
        "exposure_pct_of_time": metrics.get("exposure_pct_of_time"),
        "total_cost_bps_per_trade": metrics.get("total_cost_bps_per_trade"),
        "mean_bps_per_trade": readings["mean_bps_per_trade"],
        "mean_notional_usdt": readings["mean_notional_usdt"],
        "largest_trade_share_of_net": metrics.get("largest_trade_share_of_net"),
        "frequency": readings["frequency"],
        "expectancy_ci_90_usdt": readings["expectancy_ci_90_usdt"],
        "net_ci_90_usdt": readings["net_ci_90_usdt"],
        "bootstrap": readings["bootstrap"],
        "time_blocks": readings["time_blocks"],
        "positive_time_blocks": readings["positive_time_blocks"],
        "by_asset_detail": readings["by_asset_detail"],
        "by_regime_detail": readings["by_regime_detail"],
        "by_market_context_detail": readings["by_market_context_detail"],
        "serial_dependence": readings["serial_dependence"],
        "with_the_largest_winner_removed": leave_out_largest(
            trades=trades, start_equity=start_equity
        ),
        "exit_reason_mix": metrics.get("exit_reason_mix"),
        "funnel": refusal_funnel_of([]) if not metrics.get("trades") else run["funnel"],
        "bars_evaluated": run["bars_evaluated"],
        "warmup_bars": run["warmup_bars"],
        "signals_printed": run["signals_printed"],
        "plane": run["plane"],
        "trade_rows": trades,
    }


def run_arm_cells(
    *,
    arm_id: str,
    track: str,
    book: Any,
    corpus: _Corpus,
    timeframe: str,
    horizon_minutes: float,
    windows: dict[str, dict[str, int]],
    scenarios: tuple[str, ...] = COST_SCENARIOS,
    labels: tuple[str, ...] = WINDOW_ORDER,
) -> dict[str, dict[str, Any]]:
    """Every window and every scenario for one arm on one corpus: the matrix's column.

    The book object is reused across cells: its per-series feature state is cached by the identity
    of the bar list, which is the same object for every cell, so the cost of a matrix is the
    simulation and not the indicators.
    """
    cells: dict[str, dict[str, Any]] = {}
    for window in labels:
        if window not in windows:
            continue
        cells[window] = {}
        for scenario in scenarios:
            run = run_arm(
                arm_id=arm_id,
                book=book,
                corpus=corpus,
                window=windows[window],
                scenario=scenario,
                timeframe=timeframe,
                horizon_minutes=horizon_minutes,
            )
            run["window_label"] = window
            cells[window][scenario] = matrix_row(run=run, track=track, corpus=corpus)
    return cells


def arm_matrix(
    *,
    arm_id: str,
    track: str,
    books: dict[str, Any],
    corpora: dict[str, _Corpus],
    timeframes: dict[str, str],
    horizons: dict[str, float],
    window_label: str,
    windows: dict[str, dict[str, int]],
    scenarios: tuple[str, ...] = COST_SCENARIOS,
) -> dict[str, Any]:
    """One arm's cells plus the label of the corpus they were taken on."""
    cells = run_arm_cells(
        arm_id=arm_id,
        track=track,
        book=books[arm_id],
        corpus=corpora[timeframes[arm_id]],
        timeframe=timeframes[arm_id],
        horizon_minutes=horizons[arm_id],
        windows=windows,
        scenarios=scenarios,
    )
    return {"arm": arm_id, "track": track, "window_label": window_label, "cells": cells}


def compare_arms(
    *, matrices: dict[str, dict[str, Any]], proposed: tuple[str, ...], current: tuple[str, ...]
) -> dict[str, Any]:
    """CURRENT vs PROPOSED on whatever corpus the matrices were taken on.

    Same corpus, same windows, same costs, same risk policy, same simulator; the only difference
    is the book. The comparison is reported, never decisive: the CURRENT arms are already-closed
    registrations and the PROPOSED arms answer to the criteria in ``validation``.
    """
    out: dict[str, Any] = {}
    for window in WINDOW_ORDER:
        rows: list[dict[str, Any]] = []
        for group, arms in (("PROPOSED", proposed), ("CURRENT", current)):
            for arm in arms:
                cells = (matrices.get(arm) or {}).get("cells") or {}
                base = (cells.get(window) or {}).get("BASE") or {}
                if not base:
                    continue
                rows.append(
                    {
                        "group": group,
                        "arm": arm,
                        "trades": base.get("trades"),
                        "net_usdt": base.get("net_usdt"),
                        "expectancy_usdt": base.get("expectancy_usdt"),
                        "profit_factor": base.get("profit_factor"),
                        "max_drawdown_pct": base.get("max_drawdown_pct"),
                        "trades_per_day_universe": (base.get("frequency") or {}).get(
                            "trades_per_day_universe"
                        ),
                        "cost_bps_per_trade": base.get("total_cost_bps_per_trade"),
                    }
                )
        out[window] = {
            "rows": rows,
            "best_proposed_by_net": max(
                (row for row in rows if row["group"] == "PROPOSED"),
                key=lambda row: float(row["net_usdt"] or 0.0),
                default=None,
            ),
        }
    out["note"] = (
        "same corpus, same windows, same costs, same risk policy, same simulator; the CURRENT arms "
        "are already-closed registrations carried as the baseline and they change no verdict"
    )
    return out


def cost_sensitivity(cells_by_window: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What each scenario cost the arm on the decisive window, and what margin was left.

    ``cells_by_window`` is one arm's whole matrix (window -> scenario -> row); the sensitivity is
    read on ``OOS`` when it exists, because that is the window a verdict is computed from.
    """
    decisive = cells_by_window.get("OOS") or next(iter(cells_by_window.values()), {})
    cells = decisive
    out: dict[str, Any] = {}
    for scenario, row in cells.items():
        out[scenario] = {
            "net_usdt": row.get("net_usdt"),
            "expectancy_usdt": row.get("expectancy_usdt"),
            "total_cost_bps_per_trade": row.get("total_cost_bps_per_trade"),
            "mean_bps_per_trade": row.get("mean_bps_per_trade"),
        }
    base = cells.get("BASE", {})
    stress = cells.get("2X_FEES", {})
    adverse = cells.get("ADVERSE", {})
    base_net = float(base.get("net_usdt") or 0.0)
    margin = {
        "base_net_usdt": base_net,
        "two_x_fees_net_usdt": stress.get("net_usdt"),
        "adverse_net_usdt": adverse.get("net_usdt"),
        "base_cost_bps_per_trade": base.get("total_cost_bps_per_trade"),
        "two_x_fees_cost_bps_per_trade": stress.get("total_cost_bps_per_trade"),
        "net_per_trade_left_at_base_usdt": base.get("expectancy_usdt"),
        "survives_two_x_fees": bool(float(stress.get("net_usdt") or 0.0) > 0),
        "survives_adverse": bool(float(adverse.get("net_usdt") or 0.0) > 0),
        "trades": int(base.get("trades") or 0),
    }
    return {
        "window": "OOS" if "OOS" in cells_by_window else "unknown",
        "scenarios": out,
        "margin": margin,
    }


def gate_status(*, cells: dict[str, dict[str, Any]], window_label: str) -> dict[str, Any]:
    """The frozen admission gate, applied to this arm with ``OOS`` := the decisive window.

    It is carried beside the RFC-EDGE-008 verdict for comparability: earlier work packages were
    judged by this gate, and a reader should be able to see whether the cross-section reading would
    have passed it too. It changes nothing.
    """
    splits = {
        "DEV": {"BASE": cells.get("DEV", {}).get("BASE", {})},
        "VAL": {"BASE": cells.get("VAL", {}).get("BASE", {})},
        "OOS": {
            "BASE": cells.get("OOS", {}).get("BASE", {}),
            "2X_FEES": cells.get("OOS", {}).get("2X_FEES", {}),
        },
    }
    reading = _gate(splits=splits, criteria=ADMISSION_CRITERIA)
    return {
        "window_label": window_label,
        "min_oos_trades": MIN_TRADES,
        "verdict": reading.get("verdict"),
        "reasons": reading.get("reasons"),
        "power": reading.get("power"),
        "evidence": reading.get("evidence"),
        "disclosure": (
            "the frozen gate is reported with OOS := the cross-section's decisive window; the "
            "verdict of this work package is the one RFC-EDGE-008's registered criteria define"
        ),
    }
