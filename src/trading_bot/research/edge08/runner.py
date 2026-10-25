"""WP-EDGE-08 — one runner, so every arm is measured by the same instrument.

The point of this module is that a screen taken on the known universe and a verdict taken on the
cross-section cannot differ by accounting: both go through the frozen campaign's risk policy, cost
plane, simulator and metric definitions (``edge01.simulator.run_portfolio`` and
``edge01.campaign._metrics``), and the only things that change are the corpus, the window, the cost
scenario and the book.

Three rules:

* the cost plane is the frozen ``COST_MODEL_V3`` evaluated at the arm's **declared** horizon, then
  scaled into ``BASE`` / ``2X_FEES`` / ``ADVERSE`` from the plane's own components;
* the market-context label is applied *after* the run, as of each decision instant, and is never an
  input to a signal;
* nothing is resized: ``config/risk.yaml`` sizes every position.
"""

from __future__ import annotations

from typing import Any

from trading_bot.research.edge01.campaign import _Corpus, _metrics, load_risk_policy
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import OHLCVBar
from trading_bot.research.edge01.features import ema
from trading_bot.research.edge01.simulator import run_portfolio
from trading_bot.research.edge08.registry import regime_at

__all__ = [
    "COST_SCENARIOS",
    "exit_ema_series",
    "plane_for",
    "refusal_funnel",
    "run_arm",
]

COST_SCENARIOS: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE")


def plane_for(*, horizon_minutes: float, scenario: str) -> Any:
    """The frozen cost plane for one declared horizon, scaled into one declared scenario."""
    base = cost_plane(size_usd=1000.0, horizon_minutes=horizon_minutes)
    return base if scenario == "BASE" else base.scaled(scenario)


def exit_ema_series(
    book: Any, bars_by_asset: dict[str, list[OHLCVBar]]
) -> dict[str, list[float | None]] | None:
    """The exit EMA each asset needs, computed only when the book declares one.

    The simulator's ``exit_ema`` map is indexed by the asset's own bar index, so it has to be
    built from the same bars the simulation walks; a book that declares no ``exit_ema`` gets
    ``None`` and the simulator's EMA invalidation branch stays off.
    """
    period = book.params.get("exit_ema")
    if not period:
        return None
    return {
        asset: ema([bar.close for bar in bars], int(period))
        for asset, bars in bars_by_asset.items()
    }


def refusal_funnel(refusals: list[dict[str, Any]]) -> dict[str, int]:
    """How many setups were considered and refused, by reason."""
    funnel: dict[str, int] = {}
    for refusal in refusals:
        reason = str(refusal.get("reason") or "UNKNOWN")
        funnel[reason] = funnel.get(reason, 0) + 1
    return dict(sorted(funnel.items(), key=lambda item: (-item[1], item[0])))


def run_arm(
    *,
    arm_id: str,
    book: Any,
    corpus: _Corpus,
    window: dict[str, int],
    scenario: str,
    timeframe: str,
    horizon_minutes: float,
) -> dict[str, Any]:
    """Run one book over one corpus, one window and one cost scenario."""
    bars_by_asset = corpus.bars_by_asset
    policy = load_risk_policy()
    plane = plane_for(horizon_minutes=horizon_minutes, scenario=scenario)
    window_minutes = (window["end"] - window["start"]) / 60_000.0
    # The book object is reused across windows and scenarios (its per-series feature state is
    # cached by identity, which is where most of the time goes), so its counters are read as
    # deltas: a run must report what IT considered, not everything the process ever considered.
    evaluated_before = book.bars_evaluated
    warmup_before = book.warmup_bars
    result = run_portfolio(
        candidate=book,
        bars_by_asset=bars_by_asset,
        plane=plane,
        policy=policy,
        context=None,
        exit_ema=exit_ema_series(book, bars_by_asset),
        window_start_ts=window["start"],
        window_end_ts=window["end"],
    )
    for trade in result.trades:
        trade["market_context"] = regime_at(int(trade["decision_ts"]))
    metrics = _metrics(
        trades=result.trades,
        equity_curve=result.equity_curve,
        start_equity=policy.start_equity,
        window_minutes=window_minutes,
        timeframe=timeframe,
        n_assets=len(bars_by_asset),
    )
    return {
        "arm": arm_id,
        "scenario": scenario,
        "timeframe": timeframe,
        "window": dict(window),
        "trades": result.trades,
        "metrics": metrics,
        "plane": plane.to_dict(),
        "funnel": refusal_funnel(result.refusals),
        "signals_printed": len(result.signals),
        "bars_seen": result.bars_seen,
        "per_asset_bars": dict(result.per_asset_bars),
        "bars_evaluated": book.bars_evaluated - evaluated_before,
        "warmup_bars": book.warmup_bars - warmup_before,
    }
