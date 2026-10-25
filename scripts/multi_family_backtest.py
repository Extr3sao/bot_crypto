#!/usr/bin/env python3
"""Multi-family strategy evaluation on real bars (WP-006 rewrite).

PARITY: the productive family classes (``trading_bot.research.families.*``) and each
family's own ``_compute_indicators`` are driven over a trailing 100-bar window, the
same shape the paper runtime feeds. Signal logic is not reimplemented here.

What changed in WP-006, and why:

D1  No data means no result. With no dataset the runner writes a *run record* with
    status ``NO_DATA`` and exits 2. It never writes a results artifact and never
    exits 0 on an empty evaluation.
D2  A family exception is preserved: type, message, bar timestamp and traceback are
    recorded, the family is aborted after ``MAX_FAMILY_FAILURES`` and marked
    ``ERROR``. The run status becomes ``INCOMPLETE`` and the exit code is 3; no
    ``MULTI_FAMILY_RESULTS.json`` is written for an incomplete run.
D3  PnL is decomposed per trade: ``gross_pnl`` (at reference prices), ``spread_cost``,
    ``slippage_cost``, ``fees`` and ``net_pnl``, with the identity
    ``net = gross - spread - slippage - fees`` asserted per trade and per aggregate.
    No component is counted twice.
D4  Partitions are chronological, computed from timestamps over the pooled coverage,
    and published with their ISO boundaries. Filenames carry no meaning.
D5  A signal decided at the close of bar ``i`` is filled at the **open of bar i+1**.
    Nothing is filled at the price that produced the signal, and no bar is consulted
    before it exists.
D6  Equity is marked to market every bar, including open positions and the cost of
    closing them; ``max_dd_pct_mtm`` and the Sharpe proxy use that curve. The
    realised-only drawdown is published beside it for comparison, not for admission.

Cost model per leg (``bps`` of notional at the reference price):
    fill = ref * (1 +/- (half_spread_bps + slippage_bps) / 1e4),  fees on ref*qty
    spread_cost = notional * half_spread_bps / 1e4   (one side, per leg)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from trading_bot.market_data.types import OHLCV
from trading_bot.research.families.breakout_family import BreakoutFamily
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.research.families.mean_reversion_family import MeanReversionFamily
from trading_bot.research.families.momentum_family import MomentumFamily
from trading_bot.research.families.trend_family import TrendFamily
from trading_bot.research.families.volatility_family import VolatilityFamily

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_MANIFEST = REPO / "data" / "economic" / "w006" / "MANIFEST.json"
DEFAULT_OUT = REPO / "reports" / "economic" / "w006"

WINDOW = 100
START_EVAL = 60
TP_PCT = 0.75
RISK_PCT = 0.25
MIN_NOTIONAL, MAX_NOTIONAL = 25.0, 500.0
MAX_TRADES_DAY = 20
COOLDOWN_LOSSES = 3
DAILY_LOSS_PCT = 1.0
START_EQUITY = 10_000.0
BAR_MS = 300_000
MAX_FAMILY_FAILURES = 3

FAMILIES: dict[str, Any] = {
    "ema_crossover": EmaCrossoverFamily(),
    "momentum": MomentumFamily(),
    "breakout": BreakoutFamily(),
    "trend": TrendFamily(),
    "mean_reversion": MeanReversionFamily(),
    "volatility": VolatilityFamily(),
}
MIN_BARS = {"ema_crossover": 22, "momentum": 36, "breakout": 21,
            "trend": 56, "mean_reversion": 22, "volatility": 33}

# name -> (fees multiplier, slippage multiplier, spread multiplier)
SCENARIOS: dict[str, tuple[float, float, float]] = {
    "BASE": (1.0, 1.0, 1.0),
    "2X_COST": (2.0, 1.0, 2.0),
    "STRESSED_SLIPPAGE": (1.0, 5.0, 1.0),
    "ZERO_COST": (0.0, 0.0, 0.0),  # diagnostic only, never an admission basis
}
ADMISSION_SCENARIOS = ("BASE", "2X_COST", "STRESSED_SLIPPAGE")


@dataclass(frozen=True)
class CostModel:
    """Per-leg cost in basis points of notional at the reference price."""

    fees_bps: float = 5.0
    slippage_bps: float = 1.0
    half_spread_bps: float = 0.0
    name: str = "BASE"

    def scaled(self, factors: tuple[float, float, float], name: str) -> "CostModel":
        f, s, sp = factors
        return CostModel(self.fees_bps * f, self.slippage_bps * s, self.half_spread_bps * sp, name)

    def leg(self, ref_price: float, qty: float, direction: int) -> dict[str, float]:
        """Execution price and the cost components of one leg."""
        notional = ref_price * qty
        spread = notional * self.half_spread_bps / 1e4
        slippage = notional * self.slippage_bps / 1e4
        fees = notional * self.fees_bps / 1e4
        fill = ref_price * (1 + direction * (self.half_spread_bps + self.slippage_bps) / 1e4)
        return {"fill": fill, "spread": spread, "slippage": slippage, "fees": fees,
                "notional": notional}

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "fees_bps": self.fees_bps,
                "slippage_bps": self.slippage_bps, "half_spread_bps": self.half_spread_bps}


# --------------------------------------------------------------------------- #
# data


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DataError(RuntimeError):
    """Raised when the inputs cannot support an evaluation. Never silent."""


def load_datasets(manifest_path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load and *verify* the datasets named by the manifest.

    A dataset whose digest does not match the manifest, or whose bars are not
    strictly ascending on a uniform step, is a hard failure: an evaluation over
    unverified bars would be indistinguishable from one over verified bars.
    """
    if not manifest_path.is_file():
        raise DataError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("datasets") or {}
    if not entries:
        raise DataError("manifest declares no datasets")

    datasets: dict[str, list[dict[str, Any]]] = {}
    audit: dict[str, Any] = {}
    for symbol, entry in sorted(entries.items()):
        path = manifest_path.parent / entry["path"]
        if not path.is_file():
            raise DataError(f"{symbol}: dataset file missing: {path}")
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise DataError(f"{symbol}: digest mismatch against manifest "
                            f"({digest[:12]} != {entry['sha256'][:12]})")
        bars = json.loads(path.read_text(encoding="utf-8"))
        if len(bars) < WINDOW + START_EVAL:
            raise DataError(f"{symbol}: {len(bars)} bars is below the {WINDOW + START_EVAL} "
                            f"minimum for a windowed evaluation")
        steps = {b["ts"] - a["ts"] for a, b in zip(bars, bars[1:])}
        if steps != {BAR_MS}:
            raise DataError(f"{symbol}: irregular bar spacing {sorted(steps)[:5]}")
        for a, b in zip(bars, bars[1:]):
            if b["ts"] <= a["ts"]:
                raise DataError(f"{symbol}: timestamps are not strictly ascending at {a['ts']}")
        datasets[symbol] = bars
        audit[symbol] = {"path": entry["path"], "sha256": digest, "bars": len(bars),
                         "start_ts": bars[0]["ts"], "end_ts": bars[-1]["ts"],
                         "step_ms": BAR_MS}
    if not datasets:
        raise DataError("no dataset could be verified")
    return datasets, {"manifest": str(manifest_path), "manifest_sha256": sha256_file(manifest_path),
                      "datasets": audit}


def compute_partitions(datasets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Chronological partitions over the pooled coverage: 50% DEV, 25% VAL, 25% OOS.

    Filenames are irrelevant by construction, and the boundaries are published so a
    reader can verify that OOS starts after VAL ends and that no bar falls in two
    partitions.
    """
    t0 = min(b[0]["ts"] for b in datasets.values())
    t1 = max(b[-1]["ts"] for b in datasets.values()) + BAR_MS
    span = t1 - t0
    dev_end = t0 + int(span * 0.50)
    val_end = t0 + int(span * 0.75)

    def classify(ts: int) -> str:
        if ts < dev_end:
            return "DEV"
        if ts < val_end:
            return "VAL"
        return "OOS"

    coverage_mismatch = {
        symbol: {"start_ts": bars[0]["ts"], "end_ts": bars[-1]["ts"]}
        for symbol, bars in datasets.items()
        if bars[0]["ts"] > t0 or bars[-1]["ts"] + BAR_MS < t1
    }
    return {"t0": t0, "dev_end": dev_end, "val_end": val_end, "t1": t1,
            "classify": classify, "coverage_mismatch": coverage_mismatch,
            "boundaries": {"dev": [t0, dev_end], "val": [dev_end, val_end],
                           "oos": [val_end, t1]}}


def to_ohlcv(bars: list[dict[str, Any]]) -> list[OHLCV]:
    return [OHLCV(symbol="X", timestamp=b["ts"], open=b["open"], high=b["high"],
                  low=b["low"], close=b["close"], volume=b["volume"]) for b in bars]


# --------------------------------------------------------------------------- #
# simulation


def precompute_signals(fam_id: str, symbol: str, bars: list[dict[str, Any]],
                       family: Any | None = None) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]], str]:
    """Signals depend only on the bars and the family, so they are computed once.

    Costs do not enter here, which is what makes a cost scenario a pure replay of the
    same decisions. An exception is recorded and abortable (D2), never swallowed.
    """
    fam = family if family is not None else FAMILIES[fam_id]
    min_bars = MIN_BARS[fam_id]
    signals: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for i in range(START_EVAL, len(bars)):
        window = bars[max(0, i - WINDOW + 1):i + 1]
        if len(window) < min_bars:
            continue
        try:
            ohlcv = to_ohlcv(window)
            indicators = fam._compute_indicators(ohlcv)
            alphas = fam.generate(ohlcv, indicators, None)
        except Exception as exc:
            failures.append({"family": fam_id, "symbol": symbol, "bar_ts": bars[i]["ts"],
                             "bar_index": i, "error_type": type(exc).__name__,
                             "error": str(exc), "traceback": traceback.format_exc(limit=8)})
            if len(failures) >= MAX_FAMILY_FAILURES:
                return signals, failures, "ERROR"
            continue
        alpha = alphas[-1] if alphas else None
        if alpha is None:
            continue
        direction = 1 if str(alpha.direction).upper() == "LONG" else -1
        entry_ref = float(alpha.entry_reference)
        stop = float(getattr(alpha, "effective_stop", 0.0) or 0.0) or float(
            getattr(alpha, "structural_stop", 0.0) or 0.0)
        sl_pct = abs(entry_ref - stop) / entry_ref * 100.0 if 0 < stop < entry_ref else 1.0
        signals[i] = {"direction": direction, "side": "buy" if direction == 1 else "sell",
                      "sl_pct": sl_pct if sl_pct > 0 else 1.0, "signal_ts": bars[i]["ts"]}
    return signals, failures, "OK"


def simulate_family(fam_id: str, symbol: str, bars: list[dict[str, Any]], cost: CostModel,
                    partitions: dict[str, Any], family: Any | None = None,
                    signals: dict[int, dict[str, Any]] | None = None,
                    precomputed_status: str = "OK",
                    precomputed_failures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Replay precomputed signals under one cost model. Deterministic; no clock, no randomness."""
    min_bars = MIN_BARS[fam_id]
    classify: Callable[[int], str] = partitions["classify"]
    if signals is None:
        signals, failures, status = precompute_signals(fam_id, symbol, bars, family)
    else:
        failures = list(precomputed_failures or [])
        status = precomputed_status

    trades: list[dict[str, Any]] = []
    equity_xy: list[tuple[int, float]] = []
    realized_curve: list[float] = []
    realized_total = 0.0

    pos: dict[str, Any] | None = None
    pending_entry: dict[str, Any] | None = None
    pending_exit: dict[str, Any] | None = None
    consec_losses = 0
    cooldown_day = -1
    trades_today = 0
    cur_day = -1
    daily_start = START_EQUITY
    locked = False
    unfilled = 0

    def close_position(exit_ref: float, ts: int, reason: str, bar_index: int) -> None:
        nonlocal pos, realized_total, consec_losses
        p = pos
        assert p is not None
        leg = cost.leg(exit_ref, p["qty"], -p["direction"])
        gross = p["direction"] * p["qty"] * (exit_ref - p["entry_ref"])
        spread = p["entry_costs"]["spread"] + leg["spread"]
        slippage = p["entry_costs"]["slippage"] + leg["slippage"]
        fees = p["entry_costs"]["fees"] + leg["fees"]
        net = gross - spread - slippage - fees
        assert abs(net - (gross - spread - slippage - fees)) < 1e-12
        realized_total += net
        consec_losses = 0 if net > 0 else consec_losses + 1
        entry_ref = p["entry_ref"]
        trades.append({
            "family": fam_id, "symbol": symbol, "side": p["side"], "direction": p["direction"],
            "partition": classify(p["entry_ts"]),
            "entry_signal_ts": p["signal_ts"], "entry_bar_ts": p["entry_ts"],
            "exit_bar_ts": ts, "entry_index": p["entry_index"], "exit_index": bar_index,
            "entry_ref": round(entry_ref, 8), "entry_fill": round(p["entry_fill"], 8),
            "exit_ref": round(exit_ref, 8), "exit_fill": round(leg["fill"], 8),
            "qty": round(p["qty"], 10), "notional": round(p["notional"], 4),
            "gross_pnl": round(gross, 6), "spread_cost": round(spread, 6),
            "slippage_cost": round(slippage, 6), "fees": round(fees, 6),
            "net_pnl": round(net, 6), "reason": reason,
            "mfe_pct": round(p["mfe"] / entry_ref * 100.0, 4),
            "mae_pct": round(p["mae"] / entry_ref * 100.0, 4),
            "duration_min": round((ts - p["entry_ts"]) / 60_000, 1),
            "hold_bars": bar_index - p["entry_index"],
        })
        pos = None

    def unrealized(close_price: float) -> float:
        if pos is None:
            return 0.0
        p = pos
        leg = cost.leg(close_price, p["qty"], -p["direction"])
        gross = p["direction"] * p["qty"] * (close_price - p["entry_ref"])
        return (gross - p["entry_costs"]["spread"] - p["entry_costs"]["slippage"]
                - p["entry_costs"]["fees"] - leg["spread"] - leg["slippage"] - leg["fees"])

    for i in range(START_EVAL, len(bars)):
        bar = bars[i]
        ts, op, hi, lo, cl = bar["ts"], bar["open"], bar["high"], bar["low"], bar["close"]
        day = ts // 86_400_000
        if day != cur_day:
            cur_day, trades_today, daily_start, locked = day, 0, START_EQUITY + realized_total, False

        # 1. decisions taken on the previous close execute at this open (D5)
        if pending_exit is not None and pos is not None:
            close_position(op, ts, "signal_flip", i)
            pending_exit = None
        if pending_entry is not None and pos is None:
            if not locked and trades_today < MAX_TRADES_DAY and not (
                    consec_losses >= COOLDOWN_LOSSES and day <= cooldown_day):
                sig = pending_entry
                direction = sig["direction"]
                entry_ref = op
                qty = sig["notional"] / entry_ref
                leg = cost.leg(entry_ref, qty, direction)
                # Stop and target are anchored to the reference price the strategy saw,
                # not to the fill: a cost scenario must change costs, not which trades
                # the stop produces, otherwise gross PnL would not be comparable across
                # scenarios and D3 could not be tested at all.
                stop_dist = entry_ref * sig["sl_pct"] / 100.0
                pos = {"side": sig["side"], "direction": direction, "entry_ref": entry_ref,
                       "entry_fill": leg["fill"], "qty": qty, "notional": leg["notional"],
                       "sl": entry_ref - direction * stop_dist,
                       "tp": entry_ref * (1 + direction * TP_PCT / 100.0),
                       "entry_costs": {"spread": leg["spread"], "slippage": leg["slippage"],
                                       "fees": leg["fees"]},
                       "entry_ts": ts, "entry_index": i, "signal_ts": sig["signal_ts"],
                       "mfe": 0.0, "mae": 0.0}
                trades_today += 1
                if consec_losses >= COOLDOWN_LOSSES:
                    cooldown_day = day
            else:
                unfilled += 1
            pending_entry = None

        # 2. intrabar exits of an open position; a gap through the level exits at the open
        if pos is not None:
            p = pos
            if p["direction"] == 1:
                p["mfe"] = max(p["mfe"], hi - p["entry_ref"])
                p["mae"] = max(p["mae"], p["entry_ref"] - lo)
                sl_hit, tp_hit = lo <= p["sl"], hi >= p["tp"]
                sl_price = min(p["sl"], op) if sl_hit else p["sl"]
            else:
                p["mfe"] = max(p["mfe"], p["entry_ref"] - lo)
                p["mae"] = max(p["mae"], hi - p["entry_ref"])
                sl_hit, tp_hit = hi >= p["sl"], lo <= p["tp"]
                sl_price = max(p["sl"], op) if sl_hit else p["sl"]
            if sl_hit:  # stop first on ambiguity: the conservative reading
                close_position(sl_price, ts, "stop_loss", i)
            elif tp_hit:
                close_position(p["tp"], ts, "take_profit", i)

        # 3. mark to market at the close, then gate on that equity (D6)
        mtm = START_EQUITY + realized_total + unrealized(cl)
        if not locked and (daily_start - mtm) / daily_start * 100.0 >= DAILY_LOSS_PCT:
            locked = True
        equity_xy.append((ts, mtm))
        realized_curve.append(START_EQUITY + realized_total)

        # 4. the signal for this close was computed once; it can only act at i+1 (D5)
        sig = signals.get(i)
        if sig is not None:
            notional = min(MAX_NOTIONAL,
                           max(MIN_NOTIONAL, (START_EQUITY + realized_total)
                               * (RISK_PCT / 100.0) / (sig["sl_pct"] / 100.0)))
            if pos is None and pending_entry is None:
                pending_entry = {**sig, "notional": notional}
            elif pos is not None and sig["direction"] != pos["direction"]:
                pending_exit = {"signal_ts": sig["signal_ts"]}

    if pos is not None:
        # an open position at the end of the data is closed at the last close so no
        # unrealised PnL is silently dropped from the totals
        close_position(bars[-1]["close"], bars[-1]["ts"], "end_of_data", len(bars) - 1)

    return summarize(fam_id, symbol, trades, failures, status, equity_xy, realized_curve, unfilled)


def simulate_family_legacy(fam_id: str, symbol: str, bars: list[dict[str, Any]],
                           cost_mult: float = 1.0, slip_mult: float = 1.0) -> dict[str, Any]:
    """Evaluate one family with the pre-WP-006 multiplier signature and result shape.

    ``scripts/multi_tf_backtest.py`` and ``scripts/strategy_dynamic_experiment.py``
    call the simulator with ``(cost_mult, slip_mult)`` and read ``net``/``entry_ts``.
    Those callers keep working through this adapter, which runs the repaired engine
    under the same cost multipliers and maps the decomposed result back to the old
    key names. ``gross`` here is the pre-cost PnL, which is stricter than the old
    field it replaces: it no longer hides slippage.
    """
    cost = CostModel(fees_bps=5.0 * cost_mult, slippage_bps=1.0 * slip_mult,
                     half_spread_bps=0.0, name="LEGACY")
    partitions = compute_partitions({symbol: bars})
    res = simulate_family(fam_id, symbol, bars, cost, partitions)
    trades = [{
        "asset": symbol, "side": t["side"], "reason": t["reason"],
        "net": round(t["net_pnl"], 4), "gross": round(t["gross_pnl"], 4),
        "fees": round(t["fees"], 4), "spread": round(t["spread_cost"], 4),
        "slippage": round(t["slippage_cost"], 4),
        "entry": t["entry_ref"], "exit": t["exit_ref"],
        "entry_ts": t["entry_bar_ts"], "exit_ts": t["exit_bar_ts"],
        "entry_signal_ts": t["entry_signal_ts"],
        "mfe_pct": t["mfe_pct"], "mae_pct": t["mae_pct"], "notional": t["notional"],
        "duration_min": t["duration_min"], "partition": t["partition"],
    } for t in res["trades"]]
    return {"trades": trades, "final_equity": res["final_equity"],
            "max_dd_pct": res["max_dd_pct_mtm"], "sharpe_proxy": res["sharpe_proxy_mtm"],
            "eval_bars": res["eval_bars"], "status": res["status"],
            "failures": res["failures"], "unfilled_signals": res["unfilled_signals"]}


def summarize(fam_id: str, symbol: str, trades: list[dict[str, Any]],
              failures: list[dict[str, Any]], status: str,
              equity_xy: list[tuple[int, float]], realized_curve: list[float],
              unfilled: int) -> dict[str, Any]:
    peak = START_EQUITY
    max_dd = 0.0
    for _, eq in equity_xy:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100.0 if peak else 0.0)
    peak_r = START_EQUITY
    max_dd_realized = 0.0
    for eq in realized_curve:
        peak_r = max(peak_r, eq)
        max_dd_realized = max(max_dd_realized, (peak_r - eq) / peak_r * 100.0 if peak_r else 0.0)
    sharpe = sortino = None
    eqs = [eq for _, eq in equity_xy]
    rets = [(eqs[i] / eqs[i - 1] - 1) for i in range(1, len(eqs)) if eqs[i - 1] > 0]
    if len(rets) > 100:
        mu = mean(rets)
        sd = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5
        downside = (sum(min(r, 0.0) ** 2 for r in rets) / len(rets)) ** 0.5
        ann = ((60.0 / 5.0) * 24 * 365) ** 0.5
        sharpe = round(mu / sd * ann, 3) if sd > 0 else None
        sortino = round(mu / downside * ann, 3) if downside > 0 else None
    return {"family": fam_id, "symbol": symbol, "status": status, "failures": failures,
            "unfilled_signals": unfilled, "trades": trades,
            "equity_curve": equity_xy,  # returned for verification; not serialised in results
            "final_equity": round(eqs[-1], 2) if eqs else START_EQUITY,
            "max_dd_pct_mtm": round(max_dd, 4),
            "max_dd_pct_realized": round(max_dd_realized, 4),
            "sharpe_proxy_mtm": sharpe, "sortino_proxy_mtm": sortino,
            "eval_bars": len(eqs)}


def aggregate(trades: list[dict[str, Any]], eval_bars: int = 0) -> dict[str, Any]:
    """Pooled metrics with an explicit reconciliation of the PnL identity."""
    nets = [t["net_pnl"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gross = round(sum(t["gross_pnl"] for t in trades), 6)
    spread = round(sum(t["spread_cost"] for t in trades), 6)
    slippage = round(sum(t["slippage_cost"] for t in trades), 6)
    fees = round(sum(t["fees"] for t in trades), 6)
    net = round(sum(nets), 6)
    residual = round(net - (gross - spread - slippage - fees), 9)
    n = len(trades)
    gw, gl = sum(wins), abs(sum(losses))
    return {
        "trades": n, "gross_pnl": gross, "spread_cost": spread, "slippage_cost": slippage,
        "fees": fees, "net_pnl": net, "reconciliation_residual": residual,
        "reconciled": abs(residual) < 1e-6,
        "expectancy_gross": round(mean([t["gross_pnl"] for t in trades]), 6) if n else 0.0,
        "expectancy_net": round(mean(nets), 6) if n else 0.0,
        "cost_per_trade": round(mean([t["spread_cost"] + t["slippage_cost"] + t["fees"]
                                     for t in trades]), 6) if n else 0.0,
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / n, 2) if n else 0.0,
        "avg_win": round(mean(wins), 6) if wins else 0.0,
        "avg_loss": round(mean(losses), 6) if losses else 0.0,
        "payoff": round(mean(wins) / abs(mean(losses)), 4) if wins and losses else None,
        "profit_factor": round(gw / gl, 4) if gl else None,
        "avg_mfe_pct": round(mean([t["mfe_pct"] for t in trades]), 4) if n else 0.0,
        "avg_mae_pct": round(mean([t["mae_pct"] for t in trades]), 4) if n else 0.0,
        "avg_duration_min": round(mean([t["duration_min"] for t in trades]), 1) if n else 0.0,
        "median_duration_min": round(median([t["duration_min"] for t in trades]), 1) if n else 0.0,
        "exposure_pct": round(100.0 * sum(t["duration_min"] for t in trades)
                              / (eval_bars * 5.0), 3) if n and eval_bars else None,
        "exit_mix": {"stop": sum(1 for t in trades if t["reason"] == "stop_loss"),
                     "tp": sum(1 for t in trades if t["reason"] == "take_profit"),
                     "flip": sum(1 for t in trades if t["reason"] == "signal_flip"),
                     "end": sum(1 for t in trades if t["reason"] == "end_of_data")},
    }


# --------------------------------------------------------------------------- #
# runner


def iso(ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(manifest_path: Path, out_dir: Path, families: list[str] | None = None,
        scenarios: tuple[str, ...] = tuple(SCENARIOS), symbols: list[str] | None = None,
        dump_trades: bool = False, base_cost: CostModel | None = None) -> dict[str, Any]:
    """Evaluate and write artifacts. Returns the run record; the caller decides the exit code."""
    base = base_cost or CostModel()
    record: dict[str, Any] = {"schema": "MULTI_FAMILY_RUN_V2", "status": "UNKNOWN",
                              "manifest": str(manifest_path), "out_dir": str(out_dir),
                              "cost_model_base": base.as_dict(), "scenarios": list(scenarios),
                              "families": {}, "failures": [], "data": None, "partitions": None}
    try:
        datasets, audit = load_datasets(manifest_path)
    except DataError as exc:
        record.update({"status": "NO_DATA", "reason": str(exc)})
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "MULTI_FAMILY_RUN.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return record

    symbols = symbols or sorted(datasets)
    partitions = compute_partitions({s: datasets[s] for s in symbols})
    record["data"] = audit
    record["partitions"] = {
        "boundaries_utc": {k: [iso(v[0]), iso(v[1])] for k, v in partitions["boundaries"].items()},
        "boundaries_ms": partitions["boundaries"],
        "coverage_mismatch": partitions["coverage_mismatch"],
        "rule": "chronological over pooled coverage: DEV 50%, VAL 25%, OOS 25%",
    }
    fam_ids = families or list(FAMILIES)
    results: dict[str, Any] = {}
    trades_by_scenario: dict[str, list[dict[str, Any]]] = {s: [] for s in scenarios}
    incomplete = False

    for fam_id in fam_ids:
        results[fam_id] = {}
        # signals are cost-independent: compute once, replay under every scenario
        precomputed: dict[str, tuple[dict[int, dict[str, Any]], list[dict[str, Any]], str]] = {}
        for symbol in symbols:
            precomputed[symbol] = precompute_signals(fam_id, symbol, datasets[symbol])
            if precomputed[symbol][2] != "OK":
                record["failures"].extend(precomputed[symbol][1])
        for scenario in scenarios:
            cost = base.scaled(SCENARIOS[scenario], scenario)
            per_symbol: list[dict[str, Any]] = []
            pooled: list[dict[str, Any]] = []
            eval_bars = 0
            status = "OK"
            for symbol in symbols:
                sig, fails, st = precomputed[symbol]
                res = simulate_family(fam_id, symbol, datasets[symbol], cost, partitions,
                                      signals=sig, precomputed_status=st,
                                      precomputed_failures=fails)
                per_symbol.append(res)
                pooled.extend(res["trades"])
                eval_bars += res["eval_bars"]
                if res["status"] != "OK":
                    status = "ERROR"
                    record["failures"].extend(res["failures"])
            trades_by_scenario[scenario].extend({**t, "scenario": scenario} for t in pooled)
            by_partition = {p: aggregate([t for t in pooled if t["partition"] == p], eval_bars)
                            for p in ("DEV", "VAL", "OOS")}
            results[fam_id][scenario] = {
                "status": status, "cost_model": cost.as_dict(),
                "totals": aggregate(pooled, eval_bars),
                "DEV": by_partition["DEV"], "VAL": by_partition["VAL"], "OOS": by_partition["OOS"],
                "per_symbol": {res["symbol"]: {
                    "status": res["status"], "failures": len(res["failures"]),
                    "totals": aggregate(res["trades"], res["eval_bars"]),
                    "final_equity": res["final_equity"],
                    "max_dd_pct_mtm": res["max_dd_pct_mtm"],
                    "max_dd_pct_realized": res["max_dd_pct_realized"],
                    "sharpe_proxy_mtm": res["sharpe_proxy_mtm"],
                    "eval_bars": res["eval_bars"], "unfilled_signals": res["unfilled_signals"],
                } for res in per_symbol},
            }
            record["families"][fam_id] = {"status": status}
            if status != "OK":
                incomplete = True

    out_dir.mkdir(parents=True, exist_ok=True)
    record["status"] = "INCOMPLETE" if incomplete else "OK"
    (out_dir / "MULTI_FAMILY_RUN.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if incomplete:
        return record  # D2: an incomplete run publishes no results artifact

    payload = {"schema": "MULTI_FAMILY_RESULTS_V2", "status": "OK",
               "manifest_sha256": record["data"]["manifest_sha256"],
               "partitions": record["partitions"], "scenarios": list(scenarios),
               "cost_model_base": base.as_dict(), "results": results}
    (out_dir / "MULTI_FAMILY_RESULTS.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    if dump_trades:
        cols = ["family", "scenario", "symbol", "partition", "side", "entry_signal_ts",
                "entry_bar_ts", "exit_bar_ts", "entry_ref", "entry_fill", "exit_ref",
                "exit_fill", "qty", "notional", "gross_pnl", "spread_cost", "slippage_cost",
                "fees", "net_pnl", "reason", "mfe_pct", "mae_pct", "duration_min", "hold_bars"]
        with (out_dir / "TRADES.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for scenario in scenarios:
                w.writerows(trades_by_scenario[scenario])
    return record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--families", nargs="*", default=None)
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--scenarios", nargs="*", default=list(SCENARIOS))
    p.add_argument("--dump-trades", action="store_true")
    p.add_argument("--fees-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--half-spread-bps", type=float, default=0.0)
    args = p.parse_args(argv)

    record = run(args.manifest, args.out, args.families, tuple(args.scenarios), args.symbols,
                 args.dump_trades,
                 CostModel(args.fees_bps, args.slippage_bps, args.half_spread_bps, "BASE"))
    if record["status"] == "NO_DATA":
        print(f"NO_DATA: {record['reason']}", file=sys.stderr)
        return 2
    results_path = args.out / "MULTI_FAMILY_RESULTS.json"
    if record["status"] != "OK":
        print(f"INCOMPLETE: {len(record['failures'])} family failure(s); no results artifact written",
              file=sys.stderr)
        for f in record["failures"][:5]:
            print(f"  {f['family']}/{f['symbol']} @ {f['bar_ts']}: "
                  f"{f['error_type']}: {f['error']}", file=sys.stderr)
        return 3
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    for fam_id, scenarios in payload["results"].items():
        for scenario, block in scenarios.items():
            t = block["totals"]
            print(f"{fam_id:15s} [{scenario:18s}] trades={t['trades']:4d} "
                  f"gross={t['gross_pnl']:9.2f} costs={t['spread_cost'] + t['slippage_cost'] + t['fees']:8.2f} "
                  f"net={t['net_pnl']:9.2f} PF={t['profit_factor']} "
                  f"WR={t['win_rate']:5.2f} | DEV={block['DEV']['net_pnl']:8.2f} "
                  f"VAL={block['VAL']['net_pnl']:8.2f} OOS={block['OOS']['net_pnl']:8.2f}")
    print(f"-> {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
