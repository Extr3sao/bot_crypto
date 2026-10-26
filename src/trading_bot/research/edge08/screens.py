"""WP-EDGE-08 — the gross screen (C0) on the known universe, and the frequency it reaches.

The screen asks one question before the cross-section is touched: **does the setup make money
before any fee?** A book that loses gross cannot be repaired by costs, so measuring it on unread
data would only spend the cross-section — the rule WP-EDGE-07 Track C wrote down and this package
inherits. C0 is registered in ``PREREGISTRATION.json`` with that consequence spelled out.

The frequency reading is the mission's own number, on the same rows: trades per day across the
universe, per asset, and the mean holding time. It is reported for every book on every window, is
decisive for ACTIVE (three trades a day) and a floor for QUALITY (one trade per asset every twenty
days), and it is never a reason to force a trade.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge01.campaign import _Corpus
from trading_bot.research.edge08.analysis import extras
from trading_bot.research.edge08.registration import FREQUENCY_TARGETS, GROSS_SCREEN
from trading_bot.research.edge08.runner import run_arm

__all__ = ["DEFECTS_FIXED", "screen_arm", "screen_row", "screen_verdict"]

#: Defects found by RUNNING the screen, fixed before the registration was committed and before a
#: single bar of the cross-section was aggregated or measured. Each entry names the superseded
#: parameter hash, so a reader can see exactly what moved and why — and the verifier re-checks that
#: a superseded hash is not the hash of any book under test.
DEFECTS_FIXED: list[dict[str, object]] = [
    {
        "id": "DEF-EDGE08-01",
        "symptom": (
            "two registered QUALITY books produced no trades at all on the screening ground: "
            "edge08_quality_pullback_daily and edge08_quality_reversion_daily could not fire, the "
            "second of them on any bar of a three-year corpus."
        ),
        "cause": (
            "the frozen cost_gate applies max(min_rr, cost_margin) as its reward/risk floor, so a "
            "book whose registered min_rr (1.2 and 0.5) sits below its declared cost_margin (1.5) "
            "carries a requirement that is unsatisfiable by construction — the same defect class "
            "DEF-EDGE01-01 recorded for the frozen campaign, where a candidate printed signals and "
            "never traded one of them."
        ),
        "fix": (
            "the reward/risk of both books was made satisfiable by design rather than by weakening "
            "a gate: Q-2 moved to a 2.0 ATR stop against a 3.0 ATR objective (R:R 1.5) and Q-3 to "
            "an ATR-denominated dislocation (entry at least 3.0 ATR below the 20-day mean, 2.0 "
            "ATR stop, objective the mean), both with min_rr = cost_margin = 1.5, so the gate "
            "judges each setup instead of refusing the book."
        ),
        "superseded_params_hashes": {
            "edge08_quality_pullback_daily": (
                "7d2c5f5c2fba5e969197f3847feee48f72e37be3043817f6ecd42aef3dd8b750"
            ),
            "edge08_quality_reversion_daily": (
                "c44e61e2745b5d5b1f688084da702875078102b1b7e22aa2888e4220fa5d1d10"
            ),
        },
        "found": (
            "by running the screen, before the registration was committed and before any bar of "
            "the cross-section was aggregated or measured"
        ),
        "what_did_not_happen": (
            "no criterion, window, cost scenario or risk limit moved; the two books' signals are "
            "what changed, and the cross-section had not been touched when they did"
        ),
        "evidence": (
            "the per-arm funnels of both affected arms (zero trades and zero refusals on DEV, VAL "
            "and OOS before the fix) and the hashes above, absent from every book under test"
        ),
    }
]


def screen_arm(
    *,
    arm_id: str,
    book: Any,
    corpus: _Corpus,
    window: dict[str, int],
    timeframe: str,
    horizon_minutes: float,
    scenario: str = "BASE",
) -> dict[str, Any]:
    """One arm on one window of the screening ground, with its added readings."""
    run = run_arm(
        arm_id=arm_id,
        book=book,
        corpus=corpus,
        window=window,
        scenario=scenario,
        timeframe=timeframe,
        horizon_minutes=horizon_minutes,
    )
    metrics = run["metrics"]
    trades = run["trades"]
    readings = extras(
        trades=trades,
        window=window,
        n_assets=len(corpus.bars_by_asset),
        timeframe=timeframe,
    )
    return {
        "arm": arm_id,
        "window": run["window"],
        "scenario": scenario,
        "timeframe": timeframe,
        "metrics": metrics,
        "extras": readings,
        "funnel": run["funnel"],
        "bars_evaluated": run["bars_evaluated"],
        "warmup_bars": run["warmup_bars"],
        "signals_printed": run["signals_printed"],
        "plane": run["plane"],
        "trades": trades,
    }


def screen_row(screen: dict[str, Any], *, track: str) -> dict[str, Any]:
    """The row a reader sees: money first, then the frequency it was earned at."""
    metrics = screen["metrics"]
    readings = screen["extras"]
    frequency = readings["frequency"]
    trades = int(metrics.get("trades") or 0)
    gross = float(metrics.get("gross_usdt") or 0.0)
    return {
        "arm": screen["arm"],
        "track": track,
        "window": screen["window"],
        "scenario": screen["scenario"],
        "timeframe": screen["timeframe"],
        "trades": trades,
        "gross_usdt": metrics.get("gross_usdt"),
        "fees_usdt": metrics.get("fees_usdt"),
        "price_costs_usdt": metrics.get("price_costs_usdt"),
        "net_usdt": metrics.get("net_usdt"),
        "gross_expectancy_usdt": round(gross / trades, 4) if trades else None,
        "expectancy_usdt": metrics.get("expectancy_usdt"),
        "profit_factor": metrics.get("profit_factor"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe_annualised": metrics.get("sharpe_annualised"),
        "total_cost_bps_per_trade": metrics.get("total_cost_bps_per_trade"),
        "mean_bps_per_trade": readings.get("mean_bps_per_trade"),
        "largest_trade_share_of_net": metrics.get("largest_trade_share_of_net"),
        "trades_per_day_universe": frequency["trades_per_day_universe"],
        "trades_per_day_per_asset": frequency["trades_per_day_per_asset"],
        "mean_hold_hours": frequency["mean_hold_hours"],
        "frequency_target": FREQUENCY_TARGETS.get(track),
        "frequency_target_met": (
            frequency["trades_per_day_universe"] >= FREQUENCY_TARGETS[track]
            if track in FREQUENCY_TARGETS
            else None
        ),
        "expectancy_ci_90_usdt": readings["expectancy_ci_90_usdt"],
        "positive_time_blocks": readings["positive_time_blocks"],
        "exit_reason_mix": metrics.get("exit_reason_mix"),
        "by_asset": metrics.get("by_asset"),
        "by_market_context": metrics.get("by_market_context"),
        "funnel": screen["funnel"],
    }


def screen_verdict(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Apply C0 to one arm's DEV reading, and say what the consequence was.

    The statement is deliberately narrow: C0 is a *gross* test on a window every earlier work
    package has read. Passing it is not evidence of an edge; failing it is evidence of no edge,
    and it is the only thing that stops the cross-section from being read.
    """
    dev = rows.get("DEV") or {}
    gross_expectancy = dev.get("gross_expectancy_usdt")
    trades = int(dev.get("trades") or 0)
    passed = gross_expectancy is not None and float(gross_expectancy) > 0 and trades > 0
    return {
        "screen": GROSS_SCREEN["id"],
        "statement": GROSS_SCREEN["statement"],
        "arm": dev.get("arm"),
        "dev_trades": trades,
        "dev_gross_expectancy_usdt": gross_expectancy,
        "dev_net_usdt": dev.get("net_usdt"),
        "dev_expectancy_usdt": dev.get("expectancy_usdt"),
        "dev_trades_per_day_universe": dev.get("trades_per_day_universe"),
        "passed": passed,
        "consequence": (
            "read on the cross-section (the screen does not itself admit anything)"
            if passed
            else GROSS_SCREEN["consequence"]
        ),
        "verdict_if_failed": None if passed else "REJECT_NO_GROSS_EDGE",
    }
