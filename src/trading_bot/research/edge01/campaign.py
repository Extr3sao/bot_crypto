"""EDGE-01 campaign — pre-registered splits, cost scenarios, metrics, gate.

Everything that could be used to flatter a result is fixed here BEFORE the run:
the split dates, the cost scenarios, the metric definitions and the admission
thresholds. The gate can only return ``ADMIT``, ``REJECT`` or
``INSUFFICIENT_EVIDENCE``; there is no path that turns a losing out-of-sample
window into a pass, and "no trades" is reported as insufficient evidence rather
than as a strategy that avoided losses.

Splits
------
* intraday (15m corpus, 2024-10-01 -> 2026-10-07):
  DEV 2024-10-01..2025-06-30, VAL 2025-07-01..2025-12-31, OOS 2026-01-01..2026-10-07
* trend (1h-derived 4h/1d corpus, 2019-01-01 -> 2026-02-28):
  DEV 2019-01-01..2023-12-31, VAL 2024-01-01..2024-12-31, OOS 2025-01-01..2026-02-28

The OOS window is measured once, at the end, and is never used to pick a
parameter: the rulesets are frozen in ``candidates.FROZEN_PARAMS``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .candidates import (
    FROZEN_PARAMS,
    PARAMS_HASH,
    build_candidates,
    build_context,
)
from .costs import ADMISSION_SCENARIO as ADMISSION_SCENARIO_LABEL
from .costs import COST_SCENARIOS, CostPlane, cost_plane
from .data import ASSETS, REPO, OHLCVBar, load_1h, load_15m, resample
from .simulator import RiskPolicy, buy_and_hold
from .simulator import run_portfolio as run_portfolio_sim

__all__ = [
    "ADMISSION_CRITERIA",
    "CANDIDATE_SCOPES",
    "SPLITS",
    "load_risk_policy",
    "run_campaign",
]

RISK_CONFIG = REPO / "config" / "risk.yaml"


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


#: Pre-registered windows. Written down before the campaign ran.
SPLITS: dict[str, dict[str, dict[str, int]]] = {
    "intraday": {
        "DEV": {"start": _ms(2024, 10, 1), "end": _ms(2025, 6, 30)},
        "VAL": {"start": _ms(2025, 7, 1), "end": _ms(2025, 12, 31)},
        "OOS": {"start": _ms(2026, 1, 1), "end": _ms(2026, 10, 7)},
    },
    "trend": {
        "DEV": {"start": _ms(2019, 1, 1), "end": _ms(2023, 12, 31)},
        "VAL": {"start": _ms(2024, 1, 1), "end": _ms(2024, 12, 31)},
        "OOS": {"start": _ms(2025, 1, 1), "end": _ms(2026, 2, 28)},
    },
}

#: Which candidate runs on which corpus, with the timeframe its clock uses.
CANDIDATE_SCOPES: dict[str, dict[str, Any]] = {
    "edge_intra_01": {"split": "intraday", "timeframe": "15m", "horizon_minutes": 240.0},
    "edge_intra_02": {"split": "intraday", "timeframe": "15m", "horizon_minutes": 240.0},
    "edge_intra_02_no_fvg": {
        "split": "intraday",
        "timeframe": "15m",
        "horizon_minutes": 240.0,
    },
    "edge_trend_01_4h": {"split": "trend", "timeframe": "4h", "horizon_minutes": 1440.0},
    "edge_trend_01_1d": {"split": "trend", "timeframe": "1d", "horizon_minutes": 4320.0},
}

#: Bars per year per timeframe, used to annualise Sharpe. Declared, not guessed.
BARS_PER_YEAR: dict[str, float] = {
    "15m": 4 * 24 * 365,
    "4h": 6 * 365,
    "1d": 365,
}

#: Admission rule instantiated from RFC §7 for this WP. Fixed BEFORE measuring.
ADMISSION_CRITERIA: dict[str, Any] = {
    "min_oos_trades": 30,
    "require_oos_net_positive": True,
    "require_oos_expectancy_positive": True,
    "require_oos_base_scenario_positive": True,
    "max_single_trade_share_of_net": 0.5,
    "require_min_positive_regimes": 1,
    "require_oos_cost_stress_positive": True,
    "note": (
        "Initial thresholds for WP-EDGE-01, recorded before the campaign ran. "
        "They are NOT an approved profitability bar; they are the minimum "
        "evidence needed to avoid calling noise an edge. The cost-stress "
        "criterion (OOS net still positive at 2x fees) is stated here rather "
        "than inferred from the measured results."
    ),
}


#: Defects found by RUNNING the campaign and fixed inside this WP. Each one is a
#: measurement bug, not a tuning choice: results moved because the book or the
#: bookkeeping was wrong, never because a limit was relaxed to flatter a result.
DEFECTS_FIXED: list[dict[str, str]] = [
    {
        "id": "DEF-EDGE01-01",
        "symptom": "EDGE-TREND-01 printed signals and never traded one of them.",
        "cause": (
            "A candidate exiting on a trailing stop has no fixed objective, so the "
            "reward/risk gate compared the modelled objective with the very stop "
            "distance it is derived from: unsatisfiable by construction."
        ),
        "fix": (
            "min_rr=None for that candidate; it is judged by whether its modelled "
            "objective clears cost, which is the only promise its exit rule makes."
        ),
        "evidence": "scripts/edge01_verify.py check EDGE_TREND_01_TRADES_PRESENT",
    },
    {
        "id": "DEF-EDGE01-02",
        "symptom": (
            "Every long window was truncated by the 5% drawdown kill switch after "
            "its first trade; the equity curve jumped up on entry and fell on exit."
        ),
        "cause": (
            "Opening a position never debited cash, while equity added the position's "
            "mark-to-market value: an open position was counted twice (once as cash, "
            "once as exposure), so the recorded peak equity was fake."
        ),
        "fix": (
            "Entry debits qty x fill, exit credits proceeds net of exit fees, and the "
            "trade's net is the difference; final_equity == start + sum(net) holds to "
            "the cent."
        ),
        "evidence": (
            "scripts/edge01_verify.py checks EQUITY_CONSERVATION and "
            "EQUITY_CURVE_MATCHES_TRADES"
        ),
    },
    {
        "id": "DEF-EDGE01-03",
        "symptom": (
            "With three assets on one clock, a pending breakout on one asset could be "
            "aged, expired or fired by another asset's bars."
        ),
        "cause": "One candidate object was reused across assets with a single state slot.",
        "fix": (
            "Per-series state keyed by the identity of the bar list the caller walked; "
            "prepare() is idempotent."
        ),
        "evidence": "tests/unit/research/test_edge01_pit.py::test_state_is_per_series",
    },
    {
        "id": "DEF-EDGE01-04",
        "symptom": (
            "A verdict could not be told apart from an unpowered measurement: the gate "
            "returned on the first failing criterion."
        ),
        "cause": "Single-reason early return, no sample-size statement.",
        "fix": (
            "Every reason is collected; REJECT needs either a powered sample or a net "
            "that is negative in all three windows; the verdict carries power and "
            "evidence fields."
        ),
        "evidence": "tests/unit/research/test_edge01_gate_and_artifacts.py",
    },
    {
        "id": "DEF-EDGE01-05",
        "symptom": "STRATEGY_RESULTS.json and RUN_REPORT.json were ~86 MB each.",
        "cause": (
            "Per-bar working buffers (buy & hold bar returns, the equity curve) were "
            "serialised into the published JSON."
        ),
        "fix": "_public() strips private keys recursively; the buffers stay in memory.",
        "evidence": "artefact inventory (bytes) in RUN_REPORT.json",
    },
    {
        "id": "DEF-EDGE01-06",
        "symptom": (
            "The 1h trend filter of the two intraday candidates read a 1h bar whose "
            "close had not happened yet: up to 45 minutes of look-ahead."
        ),
        "cause": (
            "OHLCVBar.ts is the bar's OPEN time, but the as-of read compared it "
            "directly with the decision instant instead of with the bar's close "
            "(open + duration)."
        ),
        "fix": (
            "last_closed_index takes the context bar's own span and requires "
            "ts + span <= decision_ts; ContextSeries passes the span of its "
            "timeframe."
        ),
        "evidence": (
            "tests/unit/research/test_edge01_pit.py::"
            "test_context_bar_is_unreadable_until_it_closes"
        ),
    },
    {
        "id": "DEF-EDGE01-08",
        "symptom": (
            "A position still open when the window ended was settled at the last bar "
            "of the whole corpus: a 2023 DEV decision could be closed with a 2026 "
            "price, and the equity curve (which stops with the window) no longer "
            "matched the sum of the trade results."
        ),
        "cause": (
            "The end-of-window settlement used bars[-1] instead of the last bar inside "
            "the measured window."
        ),
        "fix": (
            "The simulator resolves the last in-window bar per asset before walking "
            "the timeline and settles there, keeping exit_ts inside the window."
        ),
        "evidence": (
            "scripts/edge01_verify.py check EQUITY_CONSERVATION; "
            "tests/unit/research/test_edge01_pit.py::test_end_of_window_settlement_stays_in_the_window"
        ),
    },
    {
        "id": "DEF-EDGE01-07",
        "symptom": (
            "In TRADES.csv the ablation and the 4h/1d runs were indistinguishable: "
            "every row of edge_intra_02_no_fvg said edge_intra_02, and both trend "
            "runs said edge_trend_01, so a reader grouping by that column merged "
            "runs that must be compared, not merged."
        ),
        "cause": (
            "The candidate id inside the signal was unpacked AFTER the run key, so "
            "it overwrote it."
        ),
        "fix": (
            "The run key is written last and the id that printed the signal is "
            "kept in its own ``strategy`` column."
        ),
        "evidence": "scripts/edge01_verify.py check EQUITY_CONSERVATION (grouped by run key)",
    },
]

#: Stated before the numbers are read, so they cannot be softened afterwards.
LIMITATIONS: list[str] = [
    "The 15m corpus spans 2024-10-01..2026-10-07 and the 1h corpus 2019-01-01.."
    "2026-02-28; there is no data outside those windows, so no candidate is "
    "measured through 2018 or the 2021 top on 15m.",
    "No historical order book: the spread is the project's modelled default for the "
    "venue, not an observed one. Only the fee component is contractual.",
    "Slippage and impact come from COST_MODEL_V3 at a fixed 1000 USDT intent; the "
    "positions are capped at 500 USDT, so the realised cost is at most the declared "
    "one. Both are reported per trade.",
    "The 4h and 1d corpora are aggregated from 1h, so a full 1-day bar exists only "
    "where 24 contiguous 1h bars exist; partial days are dropped, not interpolated.",
    "Regime labels are computed from the same close series the candidates trade, "
    "with no look-ahead, but they are a research taxonomy, not the runtime's.",
    "Long-only: the runtime trades Binance spot, so no short side was simulated for "
    "any candidate even where a down-breakout would be symmetric.",
    "No parameter was tuned on VAL or OOS; the rulesets are frozen in "
    "candidates.FROZEN_PARAMS with a recorded hash. This also means the candidates "
    "are untuned, and an untuned first iteration is expected to lose.",
    "Nothing here is real money, live performance, or a promise of profitability.",
]

#: PAPER integration is conditional on admission, which nothing passed.
PAPER_STATUS: dict[str, Any] = {
    "integrated": False,
    "reason": (
        "No candidate reached ADMIT. Wiring a rejected candidate into the PAPER "
        "runtime would have made the runtime execute rules whose only measured "
        "property is losing money after costs."
    ),
    "runtime_untouched": (
        "src/trading_bot/autonomous/** and the paper pipeline were not modified by "
        "this WP: the runtime remains the authority for PAPER and keeps its "
        "deterministic risk and execution behaviour."
    ),
}

#: What the next iteration should test, derived from the refusal funnel.
NEXT_HYPOTHESES: list[dict[str, str]] = [
    {
        "id": "H1",
        "hypothesis": (
            "The intraday funnel is dominated by trend_filter_fail (>=2000 refusals "
            "per window against ~60 trades): the 1h trend filter, not the breakout, is "
            "what decides participation."
        ),
        "test": (
            "Re-run the frozen EDGE-INTRA-01 with the trend filter removed as an "
            "ablation and compare on DEV only; a candidate whose edge lives in a "
            "filter must be visible there before VAL is touched."
        ),
    },
    {
        "id": "H2",
        "hypothesis": (
            "Gross is negative in DEV/VAL/OOS for the breakouts, so the loss is not "
            "only cost: the entry is late relative to the level it breaks."
        ),
        "test": (
            "Measure the post-entry MFE/MAE distribution by distance from the broken "
            "level. If MFE is already spent at entry, the entry rule has to move "
            "earlier (retest or limit at the level), not the stop."
        ),
    },
    {
        "id": "H3",
        "hypothesis": (
            "EDGE-TREND-01 4h is positive in DEV (+2,140 USDT) and in OOS (+208), but "
            "the OOS net is 80% one trade, so it may be a fat tail rather than an edge."
        ),
        "test": (
            "Re-run it on the 1h corpus over 2019-2026 with the same rules and check "
            "whether the positive tail repeats across calendar years, with the "
            "single-trade share reported per year."
        ),
    },
]


def load_risk_policy(*, start_equity: float = 10_000.0) -> RiskPolicy:
    """Read the runtime's own risk limits; nothing here is chosen by the model."""
    payload = yaml.safe_load(RISK_CONFIG.read_text(encoding="utf-8"))["risk"]
    return RiskPolicy(
        risk_per_trade_pct=float(payload["max_risk_per_trade_pct"]),
        max_open_positions=int(payload["max_open_positions"]),
        max_total_exposure_pct=float(payload["max_total_exposure_pct"]),
        max_asset_exposure_pct=float(payload["max_asset_exposure_pct"]),
        min_notional_usdt=float(payload["min_order_notional_usdt"]),
        max_notional_usdt=float(payload["max_order_notional_usdt"]),
        drawdown_halt_pct=float(payload["max_total_drawdown_pct"]),
        max_consecutive_losses=int(payload["max_consecutive_losses"]),
        consecutive_loss_cooldown_minutes=float(payload["consecutive_loss_cooldown_minutes"]),
        max_trades_per_day=int(payload["max_trades_per_day"]),
        start_equity=start_equity,
    )


@dataclass(frozen=True, slots=True)
class _Corpus:
    bars_by_asset: dict[str, list[OHLCVBar]]
    context: Any
    provenance: dict[str, Any]


def _load_corpus(split_name: str, candidate_id: str) -> _Corpus:
    scope = CANDIDATE_SCOPES[candidate_id]
    timeframe = str(scope["timeframe"])
    bars_by_asset: dict[str, list[OHLCVBar]] = {}
    provenance: dict[str, Any] = {}
    context = None
    if timeframe in ("15m",):
        for asset in ASSETS:
            corpus = load_15m(asset)
            bars_by_asset[asset] = list(corpus.bars)
            provenance[asset] = corpus.to_dict()
        context_bars = list(load_1h("BTC").bars)
        context = build_context(context_bars, timeframe="1h", fast=50, slow=200)
    else:
        base = load_1h("BTC")
        for asset in ASSETS:
            corpus = resample(load_1h(asset), timeframe)
            bars_by_asset[asset] = list(corpus.bars)
            provenance[asset] = corpus.to_dict()
        provenance["aggregated_from_1h"] = base.to_dict()
    return _Corpus(bars_by_asset=bars_by_asset, context=context, provenance=provenance)


def _metrics(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[tuple[int, float]],
    start_equity: float,
    window_minutes: float,
    timeframe: str,
    n_assets: int,
) -> dict[str, Any]:
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    total_net = sum(nets)
    peak = start_equity
    max_dd = 0.0
    for _ts, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    rets = [
        equity_curve[i][1] / equity_curve[i - 1][1] - 1
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1][1] > 0
    ]
    sharpe = None
    if len(rets) > 100:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        sd = math.sqrt(var)
        sharpe = (
            round(mean / sd * math.sqrt(BARS_PER_YEAR[timeframe]), 4) if sd > 0 else None
        )
    exposure = (
        sum(t["duration_min"] for t in trades) / (window_minutes * n_assets) * 100.0
        if window_minutes > 0
        else 0.0
    )
    by_asset: dict[str, Any] = {}
    for asset in sorted({t["asset"] for t in trades}):
        subset = [t for t in trades if t["asset"] == asset]
        by_asset[asset] = {
            "trades": len(subset),
            "net": round(sum(t["net"] for t in subset), 4),
            "win_rate": round(
                100.0 * sum(1 for t in subset if t["net"] > 0) / len(subset), 4
            )
            if subset
            else None,
        }
    by_regime: dict[str, Any] = {}
    for regime in sorted({t["regime"] or "UNKNOWN" for t in trades}):
        subset = [t for t in trades if (t["regime"] or "UNKNOWN") == regime]
        by_regime[regime] = {
            "trades": len(subset),
            "net": round(sum(t["net"] for t in subset), 4),
            "win_rate": round(
                100.0 * sum(1 for t in subset if t["net"] > 0) / len(subset), 4
            )
            if subset
            else None,
        }
    exit_mix: dict[str, int] = {}
    for trade in trades:
        exit_mix[trade["exit_reason"]] = exit_mix.get(trade["exit_reason"], 0) + 1
    largest = max(nets, default=0.0)
    return {
        "trades": len(trades),
        "gross_usdt": round(sum(t["gross"] for t in trades), 4),
        "fees_usdt": round(sum(t["fees"] for t in trades), 4),
        "price_costs_usdt": round(sum(t["price_costs"] for t in trades), 4),
        "net_usdt": round(total_net, 4),
        "return_pct": round(total_net / start_equity * 100.0, 4),
        "final_equity": round(start_equity + total_net, 4),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 4) if trades else None,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "expectancy_usdt": round(total_net / len(trades), 4) if trades else None,
        "avg_win_usdt": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss_usdt": round(sum(losses) / len(losses), 4) if losses else None,
        "payoff_ratio": (
            round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 4)
            if wins and losses
            else None
        ),
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_annualised": sharpe,
        "sharpe_convention": (
            f"per-{timeframe} equity returns, annualised with {BARS_PER_YEAR[timeframe]:.0f} "
            f"bars/year; None when fewer than 100 observations"
        ),
        "exposure_pct_of_time": round(exposure, 4),
        "total_cost_bps_per_trade": (
            round(
                (sum(t["fees"] + t["price_costs"] for t in trades))
                / sum(t["notional"] for t in trades)
                * 10_000.0,
                4,
            )
            if trades and sum(t["notional"] for t in trades) > 0
            else None
        ),
        "largest_trade_share_of_net": (
            round(largest / total_net, 4) if total_net > 0 else None
        ),
        "by_asset": by_asset,
        "by_regime": by_regime,
        "exit_reason_mix": exit_mix,
        "avg_duration_min": (
            round(sum(t["duration_min"] for t in trades) / len(trades), 2) if trades else None
        ),
    }


def _gate(*, splits: dict[str, Any], criteria: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered admission rule and report every reason.

    Labels are kept honest in both directions:

    * ``REJECT`` — the pre-registered requirement failed with enough evidence to
      say so: either a powered OOS sample (>= ``min_oos_trades``) with net <= 0,
      or a net that is negative in *every* window (DEV/VAL/OOS). The latter is
      still evidence — three disjoint periods losing money is a result, not a
      small sample — so it rejects rather than hiding behind ``INSUFFICIENT``.
    * ``INSUFFICIENT_EVIDENCE`` — the measurement cannot support a conclusion:
      a small OOS sample that is not negative in every window, a positive net
      driven by one trade, or an unpowered positive result. Not a pass.
    * ``ADMIT`` — every criterion met. Requires the minimum sample.

    ``power`` states the sample size against the pre-registered minimum, so a
    rejection on few trades is never read as a powered one.
    """
    oos = splits["OOS"]["BASE"]
    reasons: list[str] = []
    net = float(oos.get("net_usdt") or 0.0)
    trades = int(oos.get("trades") or 0)
    min_trades = int(criteria["min_oos_trades"])
    expectancy = oos.get("expectancy_usdt")

    if criteria["require_oos_net_positive"] and net <= 0:
        reasons.append(f"oos net {net:.2f} USDT <= 0 after costs")
    if criteria["require_oos_expectancy_positive"] and (expectancy or 0) <= 0:
        reasons.append(f"oos expectancy {expectancy} USDT/trade <= 0")
    share = oos.get("largest_trade_share_of_net")
    if share is not None and share > float(criteria["max_single_trade_share_of_net"]):
        reasons.append(f"the largest single trade is {share:.2f} of the oos net")
    positive_regimes = sum(
        1 for value in (oos.get("by_regime") or {}).values() if float(value.get("net") or 0) > 0
    )
    if positive_regimes < int(criteria["require_min_positive_regimes"]):
        reasons.append(
            f"oos has {positive_regimes} profitable regime(s), "
            f"fewer than the required {criteria['require_min_positive_regimes']}"
        )
    stress = float(splits["OOS"].get("2X_FEES", {}).get("net_usdt") or 0.0)
    if criteria["require_oos_cost_stress_positive"] and stress <= 0:
        reasons.append(f"oos net turns negative under 2x fees ({stress:.2f} USDT): no cost margin")

    window_nets = {
        name: float(splits[name]["BASE"].get("net_usdt") or 0.0)
        for name in ("DEV", "VAL", "OOS")
        if name in splits
    }
    every_window_negative = bool(window_nets) and all(
        value <= 0 for value in window_nets.values()
    )
    if every_window_negative:
        reasons.append(
            "net negative in every window "
            f"({', '.join(f'{k}={v:.2f}' for k, v in window_nets.items())} USDT)"
        )
    if trades < min_trades:
        reasons.append(f"oos trades {trades} < required {min_trades} (unpowered sample)")

    if net <= 0 and (trades >= min_trades or every_window_negative):
        verdict = "REJECT"
    elif reasons:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "ADMIT"
    if verdict == "ADMIT":
        reasons.append("oos net positive after costs, sample powered, no single trade carries it")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "power": (
            f"powered (oos n={trades} >= {min_trades})"
            if trades >= min_trades
            else f"underpowered (oos n={trades} < {min_trades})"
        ),
        "evidence": {
            "window_net_usdt": {k: round(v, 4) for k, v in window_nets.items()},
            "oos_trades": trades,
            "min_oos_trades": min_trades,
            "oos_net_usdt": round(net, 4),
            "oos_2x_fees_net_usdt": round(stress, 4),
            "positive_regimes_oos": positive_regimes,
        },
    }


def run_campaign(*, scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE")) -> dict[str, Any]:
    """Run every candidate over every split, in every cost scenario."""
    policy = load_risk_policy()
    results: dict[str, Any] = {}
    corpus_cache: dict[str, _Corpus] = {}
    for candidate_id, scope in CANDIDATE_SCOPES.items():
        split_name = str(scope["split"])
        timeframe = str(scope["timeframe"])
        if candidate_id not in corpus_cache:
            corpus_cache[candidate_id] = _load_corpus(split_name, candidate_id)
        corpus = corpus_cache[candidate_id]
        window = SPLITS[split_name]
        horizon = float(scope["horizon_minutes"])
        base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)
        candidate_results: dict[str, Any] = {
            "scope": {
                "split": split_name,
                "timeframe": timeframe,
                "assets": list(ASSETS),
                "params_hash": PARAMS_HASH,
                "frozen_params": FROZEN_PARAMS[
                    candidate_id.replace("_no_fvg", "").replace("_4h", "").replace("_1d", "")
                ]
                if candidate_id.replace("_no_fvg", "").replace("_4h", "").replace("_1d", "")
                in FROZEN_PARAMS
                else FROZEN_PARAMS["edge_trend_01"],
                "provenance": corpus.provenance,
            },
            "splits": {},
        }
        for split, bounds in window.items():
            start, end = int(bounds["start"]), int(bounds["end"])
            window_minutes = (end - start) / 60_000.0
            split_results: dict[str, Any] = {}
            for scenario in scenarios:
                plane: CostPlane = base_plane.scaled(scenario)
                candidate = build_candidates()[candidate_id]
                sim = run_portfolio_sim(
                    candidate=candidate,
                    bars_by_asset=corpus.bars_by_asset,
                    plane=plane,
                    policy=policy,
                    context=corpus.context,
                    window_start_ts=start,
                    window_end_ts=end,
                )
                metrics = _metrics(
                    trades=sim.trades,
                    equity_curve=sim.equity_curve,
                    start_equity=policy.start_equity,
                    window_minutes=window_minutes,
                    timeframe=timeframe,
                    n_assets=len(ASSETS),
                )
                refusal_mix: dict[str, int] = {}
                for refusal in sim.refusals:
                    key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
                    refusal_mix[key] = refusal_mix.get(key, 0) + 1
                split_results[scenario] = {
                    **metrics,
                    "plane": plane.to_dict(),
                    "candidate_refusals": refusal_mix,
                    "signals_printed": len(sim.signals),
                    "buy_and_hold": {
                        asset: buy_and_hold(
                            bars=corpus.bars_by_asset[asset],
                            plane=plane,
                            start_equity=policy.start_equity,
                            window_start_ts=start,
                            window_end_ts=end,
                        )
                        for asset in ASSETS
                    },
                    "trade_rows": sim.trades,
                    "equity_curve_len": len(sim.equity_curve),
                    "_equity_curve": sim.equity_curve
                    if scenario == "BASE"
                    else [],
                }
            candidate_results["splits"][split] = split_results
        gate = _gate(splits=candidate_results["splits"], criteria=ADMISSION_CRITERIA)
        candidate_results["verdict"] = gate["verdict"]
        candidate_results["verdict_reasons"] = gate["reasons"]
        candidate_results["verdict_power"] = gate["power"]
        candidate_results["verdict_evidence"] = gate["evidence"]
        results[candidate_id] = candidate_results
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "params_hash": PARAMS_HASH,
        "frozen_params": FROZEN_PARAMS,
        "splits": {
            name: {
                split: {
                    "start_utc": datetime.fromtimestamp(v["start"] / 1000, tz=UTC).isoformat(),
                    "end_utc": datetime.fromtimestamp(v["end"] / 1000, tz=UTC).isoformat(),
                }
                for split, v in window.items()
            }
            for name, window in SPLITS.items()
        },
        "cost_scenarios": COST_SCENARIOS,
        "admission_criteria": ADMISSION_CRITERIA,
        "risk_policy": policy.to_dict(),
        "candidates": results,
    }


def write_artifacts(campaign: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the six required artefacts plus the machine-readable summary."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trades_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    for candidate_id, payload in campaign["candidates"].items():
        for split, scenarios in payload["splits"].items():
            for scenario, data in scenarios.items():
                for trade in data["trade_rows"]:
                    # The trade row carries the candidate that PRINTED the signal
                    # (``edge_intra_02`` for its own ablation too). The run key must
                    # win, or two runs become indistinguishable in the CSV and the
                    # ablation gets merged into the candidate it ablates
                    # (DEF-EDGE01-07).
                    row = dict(trade)
                    row["strategy"] = trade.get("candidate")
                    row["candidate"] = candidate_id
                    row["split"] = split
                    row["scenario"] = scenario
                    trades_rows.append(row)
                if scenario == "BASE":
                    for ts, equity in data.get("_equity_curve", []):
                        equity_rows.append(
                            {
                                "candidate": candidate_id,
                                "split": split,
                                "ts": ts,
                                "iso_utc": datetime.fromtimestamp(ts / 1000, tz=UTC).isoformat(),
                                "equity": round(equity, 6),
                            }
                        )

    trades_path = outdir / "TRADES.csv"
    _write_csv(trades_path, trades_rows)
    written["TRADES.csv"] = trades_path

    equity_path = outdir / "EQUITY_CURVE.csv"
    _write_csv(equity_path, equity_rows)
    written["EQUITY_CURVE.csv"] = equity_path

    summary = _summary(campaign)
    results_json = outdir / "STRATEGY_RESULTS.json"
    results_json.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written["STRATEGY_RESULTS.json"] = results_json

    results_md = outdir / "STRATEGY_RESULTS.md"
    results_md.write_text(_results_markdown(campaign, summary), encoding="utf-8")
    written["STRATEGY_RESULTS.md"] = results_md

    run_md = outdir / "RUN_REPORT.md"
    run_md.write_text(_run_markdown(campaign, summary), encoding="utf-8")
    written["RUN_REPORT.md"] = run_md

    # RUN_REPORT.json is written last on purpose: it is the only artefact that can
    # carry the digests of all the others, so the inventory is complete except
    # for its own file (which it states).
    inventory = {
        name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for name, path in written.items()
    }
    run_json = outdir / "RUN_REPORT.json"
    run_json.write_text(
        json.dumps(
            {
                "run_id": "wp-edge-01-campaign",
                "params_hash": campaign["params_hash"],
                "generated_at_utc": campaign["generated_at_utc"],
                "git": _git_state(),
                "mode": (
                    "deterministic backtest over local historical corpora; "
                    "0 orders, 0 credentials, 0 network calls"
                ),
                "entrypoint": "scripts/edge01_run.py",
                "verifier": "scripts/edge01_verify.py",
                "cost_scenarios": campaign["cost_scenarios"],
                "admission_criteria": campaign["admission_criteria"],
                "risk_policy": campaign["risk_policy"],
                "splits": campaign["splits"],
                "provenance": {
                    candidate_id: payload["scope"]["provenance"]
                    for candidate_id, payload in campaign["candidates"].items()
                },
                "results": summary["candidates"],
                "defects_fixed_in_this_wp": DEFECTS_FIXED,
                "limitations": LIMITATIONS,
                "paper_status": PAPER_STATUS,
                "next_hypotheses": NEXT_HYPOTHESES,
                "test_target_equals_runtime_target": {
                    "status": "PASS" if not _runtime_diff() else "FAIL",
                    "detail": (
                        "the tests and the runner import the same package "
                        "(trading_bot.research.edge01); the verifier imports nothing "
                        "and reads only the artefacts"
                    ),
                    "runtime_files_changed_by_this_wp": _runtime_diff(),
                },
                "artifacts": inventory,
                "artifact_note": (
                    "digests cover every artefact except RUN_REPORT.json itself, "
                    "which is the file carrying them"
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    written["RUN_REPORT.json"] = run_json
    return written


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state() -> dict[str, Any]:
    """HEAD, branch and dirtiness, plus a digest of the code that was executed.

    A run performed before its own commit must not claim the commit as its
    provenance, so the dirty flag and the source digest are recorded next to
    HEAD and the report states which one identifies the run.
    """
    import hashlib
    import subprocess

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()

    source = hashlib.sha256()
    for path in sorted((REPO / "src" / "trading_bot" / "research" / "edge01").glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    for script in (REPO / "scripts" / "edge01_run.py", REPO / "scripts" / "edge01_verify.py"):
        if script.exists():
            source.update(script.name.encode())
            source.update(script.read_bytes())
    try:
        state: dict[str, Any] = {
            "head_commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_dirty": bool(_git("status", "--porcelain")),
        }
    except Exception:  # pragma: no cover - a tree without git is reported, not guessed
        state = {"head_commit": "UNKNOWN", "branch": "UNKNOWN", "worktree_dirty": None}
    state["source_sha256"] = source.hexdigest()
    return state


def _git_commit() -> str:
    return str(_git_state()["head_commit"])


#: The runtime the research must not have edited to accommodate itself.
RUNTIME_PATHS: tuple[str, ...] = (
    "src/trading_bot/autonomous",
    "src/trading_bot/risk",
    "src/trading_bot/execution",
    "src/trading_bot/paper",
    "src/trading_bot/strategy_lifecycle",
    "src/trading_bot/observability",
    "scripts/autonomous_paper.py",
    "config/risk.yaml",
)


def _runtime_diff() -> list[str]:
    """Runtime files this WP changed. Must be empty.

    ``TEST_TARGET == RUNTIME_TARGET`` means the tests exercise the same modules the
    entrypoint runs. Here it also has to mean the runtime was not quietly edited to
    accommodate the research, so the scope is the runtime package and the PAPER
    entrypoint, not the whole tree (other threads work in this checkout).
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", *RUNTIME_PATHS],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except Exception:  # pragma: no cover - a tree without git is reported, not guessed
        return ["UNKNOWN: git unavailable"]
    return [line.strip() for line in out.splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _public(value: Any) -> Any:
    """Recursively drop private keys so in-memory helpers never reach an artefact.

    ``_equity_curve`` and ``_bar_returns`` are working buffers (the second one is
    per-bar and would add tens of megabytes of buy & hold returns to the JSON for
    nothing). Only the named metrics are published (DEF-EDGE01-05).
    """
    if isinstance(value, dict):
        return {
            key: _public(item)
            for key, item in value.items()
            if not str(key).startswith("_") and key != "trade_rows"
        }
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _summary(campaign: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"params_hash": campaign["params_hash"], "candidates": {}}
    for candidate_id, payload in campaign["candidates"].items():
        entry: dict[str, Any] = {
            "verdict": payload["verdict"],
            "verdict_reasons": payload["verdict_reasons"],
            "verdict_power": payload.get("verdict_power"),
            "verdict_evidence": payload.get("verdict_evidence"),
            "timeframe": payload["scope"]["timeframe"],
            "frozen_params": payload["scope"]["frozen_params"],
            "params_hash": payload["scope"]["params_hash"],
            "provenance": payload["scope"]["provenance"],
            "splits": {},
        }
        for split, scenarios in payload["splits"].items():
            entry["splits"][split] = {
                scenario: _public(data) for scenario, data in scenarios.items()
            }
        out["candidates"][candidate_id] = entry
    return out


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def _results_markdown(campaign: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# STRATEGY RESULTS - WP-EDGE-01",
        "",
        "- run_id: `wp-edge-01-campaign`",
        f"- params_hash: `{campaign['params_hash']}`",
        f"- generated (UTC): {campaign['generated_at_utc']}",
        f"- commit: `{_git_commit()}`",
        "- data: local corpora only (15m: `data/raw/alpha003/price`, 1h: "
        "`reports/alpha-expansion-v1/data`, aggregated to 4h/1d)",
        "",
        "## Cost scenarios",
        "",
        "| scenario | fee x | slippage/impact x |",
        "|---|---|---|",
    ]
    for name, mult in campaign["cost_scenarios"].items():
        lines.append(f"| {name} | {mult[0]} | {mult[1]} |")
    lines += [
        "",
        "## Verdicts",
        "",
        "| candidate | timeframe | OOS trades | OOS net (BASE) | OOS expectancy | verdict | reasons |",
        "|---|---|---|---|---|---|---|",
    ]
    for candidate_id, payload in campaign["candidates"].items():
        oos = payload["splits"]["OOS"]["BASE"]
        evidence = payload.get("verdict_evidence") or {}
        window_net = ", ".join(
            f"{k}={v:,.2f}" for k, v in (evidence.get("window_net_usdt") or {}).items()
        )
        lines.append(
            f"| {candidate_id} | {payload['scope']['timeframe']} | {oos['trades']} | "
            f"{_num(oos['net_usdt'])} | {_num(oos['expectancy_usdt'])} | "
            f"**{payload['verdict']}** ({payload.get('verdict_power')}; net por ventana: "
            f"{window_net or 'n/a'}) | {'; '.join(payload['verdict_reasons'])} |"
        )
    lines += ["", "## Per split and scenario", ""]
    for candidate_id, payload in campaign["candidates"].items():
        lines += [
            f"### {candidate_id} ({payload['scope']['timeframe']})",
            "",
            "| split | scenario | trades | gross | costs (fees+price) | net | win rate | "
            "profit factor | expectancy | max DD | Sharpe | exposure |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for split in ("DEV", "VAL", "OOS"):
            for scenario in campaign["cost_scenarios"]:
                data = payload["splits"][split][scenario]
                costs = (data["fees_usdt"] or 0) + (data["price_costs_usdt"] or 0)
                lines.append(
                    f"| {split} | {scenario} | {data['trades']} | {_num(data['gross_usdt'])} | "
                    f"{_num(costs)} | {_num(data['net_usdt'])} | {_pct(data['win_rate_pct'])} | "
                    f"{_num(data['profit_factor'])} | {_num(data['expectancy_usdt'])} | "
                    f"{_pct(data['max_drawdown_pct'])} | {_num(data['sharpe_annualised'])} | "
                    f"{_pct(data['exposure_pct_of_time'])} |"
                )
        lines += ["", "Exit reasons (OOS/BASE): " + _exit_mix(payload), ""]
        lines += ["Refusals (OOS/BASE, top): " + _refusal_mix(payload), ""]
        lines += ["Buy & hold over the same OOS window: " + _buy_hold(payload), ""]
    lines += [
        "## Honesty notes",
        "",
        "- `net` is after fees, spread, slippage and impact: the plan it was sized "
        "against is printed per scenario above.",
        "- A candidate with fewer than the pre-registered minimum OOS trades is "
        "`INSUFFICIENT_EVIDENCE`, never `ADMIT`.",
        "- `REJECT` needs either a powered OOS sample or a net that is negative in "
        "all three windows; a small sample that is merely unprofitable stays "
        "`INSUFFICIENT_EVIDENCE`, and every reason is listed so the reader can "
        "re-judge it.",
        "- Nothing in this table is a profitability claim: no candidate reached "
        "`ADMIT`, and a positive net carried by one trade is reported as such.",
        "- Buy & hold uses the same window and the same cost plane, and trades once.",
        f"- Admission criteria (fixed before measuring): {json.dumps(campaign['admission_criteria'])}",
        "",
    ]
    return "\n".join(lines)


def _exit_mix(payload: dict[str, Any]) -> str:
    mix = payload["splits"]["OOS"]["BASE"]["exit_reason_mix"]
    return ", ".join(f"{k}={v}" for k, v in sorted(mix.items())) or "no trades"


def _refusal_mix(payload: dict[str, Any]) -> str:
    mix = payload["splits"]["OOS"]["BASE"]["candidate_refusals"]
    top = sorted(mix.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return ", ".join(f"{k}={v}" for k, v in top) or "none"


def _buy_hold(payload: dict[str, Any], split: str = "OOS") -> str:
    bh = payload["splits"][split]["BASE"]["buy_and_hold"]
    parts = [f"{_pct(v.get('return_pct'))}" for _asset, v in sorted(bh.items())]
    return " / ".join(parts)


def _run_markdown(campaign: dict[str, Any], summary: dict[str, Any]) -> str:
    git = _git_state()
    lines = [
        "# RUN REPORT - WP-EDGE-01 (estrategias operativas y resultados economicos)",
        "",
        "| | |",
        "|---|---|",
        "| run_id | `wp-edge-01-campaign` |",
        f"| HEAD al ejecutar | `{git['head_commit']}` |",
        f"| rama | `{git['branch']}` |",
        f"| arbol sucio al ejecutar | `{git['worktree_dirty']}` |",
        f"| huella del c\u00f3digo ejecutado (sha256) | `{git['source_sha256']}` |",
        f"| params_hash | `{campaign['params_hash']}` |",
        "| modo | backtest determinista sobre datos hist\u00f3ricos locales; 0 \u00f3rdenes, 0 claves, 0 red |",
        "| entrypoint | `scripts/edge01_run.py` |",
        f"| generado | {campaign['generated_at_utc']} |",
        "",
        "> El `HEAD` de arriba es lo que la m\u00e1quina ten\u00eda al medir; cuando el \u00e1rbol\n"
        "> est\u00e1 sucio el identificador de esta medida es la **huella del c\u00f3digo**\n"
        "> (sha256 de los m\u00f3dulos de `research/edge01` y sus dos entrypoints), no el commit.\n",
        "",
        "## 1. Qu\u00e9 se ejecut\u00f3",
        "",
        "Tres candidatos del RFC m\u00e1s una ablaci\u00f3n, sobre los corpus locales del repo,\n"
        "con los costes del modelo del propio proyecto (`COST_MODEL_V3`, escenario\n"
        "admission de Binance spot taker), splits preinscritos DEV/VAL/OOS y tres\n"
        "escenarios de coste derivados del mismo plano (BASE, 2X_FEES, ADVERSE).",
        "",
        "## 2. Datos y procedencia",
        "",
        "| candidato | timeframe | barras | desde | hasta | sha256 del corpus |",
        "|---|---|---|---|---|---|",
    ]
    lines += _provenance_rows(campaign)
    lines += [
        "",
        "## 3. M\u00e9todo",
        "",
        "- Splits fijados antes de medir: "
        + "; ".join(
            f"**{name}** " + ", ".join(f"{split} {bounds['start_utc'][:10]}..{bounds['end_utc'][:10]}"
                                       for split, bounds in windows.items())
            for name, windows in campaign["splits"].items()
        ),
        f"- Reglas congeladas: `params_hash={campaign['params_hash']}`; ning\u00fan par\u00e1metro se\n"
        "  ajust\u00f3 sobre VAL ni OOS.",
        "- Costes: plano del modelo del proyecto, escenario `"
        + str(ADMISSION_SCENARIO_LABEL)
        + "`; el componente contractual es la comisi\u00f3n y el resto es modelo de microestructura.",
        "- Tama\u00f1o: l\u00edmites de `config/risk.yaml` tal cual (riesgo por operaci\u00f3n, tope por\n"
        "  activo, exposici\u00f3n total, n\u00f3tional m\u00edn/m\u00e1x, m\u00e1ximo de operaciones diarias,\n"
        "  cooldown por p\u00e9rdidas consecutivas y kill switch por drawdown).",
        "- Baseline: buy & hold del mismo activo, misma ventana, mismo plano de coste, una\n"
        "  sola operaci\u00f3n (entrada en el primer open, salida en el \u00faltimo close).",
        "- Causalidad: las decisiones se toman con el cierre de la barra y se ejecutan al\n"
        "  open de la barra siguiente; el pivote/FVG s\u00f3lo se usa una vez confirmado.",
        "",
        "## 4. Resultados por candidato",
        "",
        "| candidato | split | trades | net (BASE) | net (ADVERSE) | veredicto | potencia |",
        "|---|---|---|---|---|---|---|",
    ]
    for candidate_id, payload in campaign["candidates"].items():
        for split in ("DEV", "VAL", "OOS"):
            base = payload["splits"][split]["BASE"]
            adverse = payload["splits"][split]["ADVERSE"]
            lines.append(
                f"| {candidate_id} | {split} | {base['trades']} | {_num(base['net_usdt'])} | "
                f"{_num(adverse['net_usdt'])} | "
                f"{payload['verdict'] if split == 'OOS' else '-'} | "
                f"{payload.get('verdict_power') if split == 'OOS' else '-'} |"
            )
    lines += ["", "### Veredictos y por qu\u00e9", ""]
    for candidate_id, payload in campaign["candidates"].items():
        evidence = payload.get("verdict_evidence") or {}
        lines += [
            f"- **{candidate_id}** \u2192 `{payload['verdict']}` ({payload.get('verdict_power')}). "
            "Net por ventana (BASE): "
            + ", ".join(f"{k}={v}" for k, v in (evidence.get("window_net_usdt") or {}).items())
            + "."
        ]
        for reason in payload["verdict_reasons"]:
            lines.append(f"  - {reason}")
    lines += [
        "",
        "## 5. Por qu\u00e9 no oper\u00f3 (motivos de rechazo, OOS/BASE)",
        "",
        "El embudo completo, del universo a la orden. Un motivo listado aqu\u00ed es una\n"
        "decisi\u00f3n del candidato o del riesgo, no un error de datos.",
        "",
    ]
    for candidate_id, payload in campaign["candidates"].items():
        lines.append(f"- {candidate_id}: {_refusal_mix(payload)}")
    lines += [
        "",
        "Se\u00f1ales impresas por el candidato (antes de riesgo y ejecuci\u00f3n): "
        + ", ".join(
            f"{candidate_id}={payload['splits']['OOS']['BASE']['signals_printed']}"
            for candidate_id, payload in campaign["candidates"].items()
        ),
        "",
        "## 6. Comparaci\u00f3n con el baseline",
        "",
        "| candidato | ventana | net estrategia (BASE) | retorno de la estrategia | buy & hold BTC / ETH / SOL |",
        "|---|---|---|---|---|",
    ]
    for candidate_id, payload in campaign["candidates"].items():
        for split in ("DEV", "VAL", "OOS"):
            base = payload["splits"][split]["BASE"]
            lines.append(
                f"| {candidate_id} | {split} | {_num(base['net_usdt'])} | "
                f"{_pct(base['return_pct'])} | {_buy_hold(payload, split)} |"
            )
    lines += [
        "",
        "## 7. Defectos encontrados al ejecutar (y corregidos aqu\u00ed)",
        "",
        "| id | s\u00edntoma | causa | correcci\u00f3n | evidencia |",
        "|---|---|---|---|---|",
    ]
    for defect in DEFECTS_FIXED:
        lines.append(
            f"| `{defect['id']}` | {defect['symptom']} | {defect['cause']} | "
            f"{defect['fix']} | {defect['evidence']} |"
        )
    lines += [
        "",
        "## 8. Verificaci\u00f3n",
        "",
        "Reproducir esta medida (sin red, sin claves):",
        "",
        "```bash",
        ".venv/Scripts/python.exe scripts/edge01_run.py --outdir reports/edge-recovery/WP-EDGE-01",
        ".venv/Scripts/python.exe scripts/edge01_verify.py --dir reports/edge-recovery/WP-EDGE-01",
        ".venv/Scripts/python.exe -m pytest tests/unit/research/test_edge01_pit.py \\",
        "    tests/unit/research/test_edge01_gate_and_artifacts.py -q",
        "```",
        "",
        "- Verificador independiente: `scripts/edge01_verify.py`. Proceso aparte, no\n"
        "  importa `trading_bot.research.edge01`: re-deriva las m\u00e9tricas desde\n"
        "  `TRADES.csv` y `EQUITY_CURVE.csv` y aplica sus propios controles negativos\n"
        "  (incluye mutaciones al CSV para comprobar que cada chequeo puede fallar).",
        "- Tests de causalidad y contabilidad: `tests/unit/research/test_edge01_pit.py`\n"
        "  (look-ahead en pivotes y FVG, estado por serie, identidad de caja).",
        "- Tests del veredicto y de los artefactos:\n"
        "  `tests/unit/research/test_edge01_gate_and_artifacts.py`.",
        "- Cada artefacto lleva su sha256 y su tama\u00f1o en `RUN_REPORT.json`.\n"
        "  El backtester no comparte c\u00f3digo de decisi\u00f3n con el runtime.",
        "- `INDEPENDENT_VERIFICATION.json` lo produce el verificador DESPU\u00c9S de esta "
        "medida, as\u00ed que no est\u00e1 en el inventario de integridad de arriba: es el "
        "resultado de comprobar los otros cinco, no una medida m\u00e1s.",
        "- `TEST_TARGET == RUNTIME_TARGET`: "
        + str(_runtime_diff() or "el WP no ha tocado ning\u00fan fichero del runtime")
        + ". Los tests y el runner importan el mismo paquete "
        "(`trading_bot.research.edge01`) y el verificador no importa nada del proyecto.",
        "",
        "## 9. PAPER",
        "",
        f"- Integrado: `{PAPER_STATUS['integrated']}` \u2014 {PAPER_STATUS['reason']}",
        f"- Runtime: {PAPER_STATUS['runtime_untouched']}",
        "- No se activa dinero real: 0 \u00f3rdenes en este WP.",
        "",
        "## 10. Hip\u00f3tesis para la siguiente iteraci\u00f3n",
        "",
    ]
    for item in NEXT_HYPOTHESES:
        lines.append(f"- **{item['id']}**: {item['hypothesis']} \u2014 *Test:* {item['test']}")
    lines += [
        "",
        "## 11. Limitaciones",
        "",
    ]
    lines += [f"- {item}" for item in LIMITATIONS]
    lines += [
        "",
        "## 12. Artefactos",
        "",
        "| artefacto | contenido |",
        "|---|---|",
        "| `STRATEGY_RESULTS.md` | veredictos y m\u00e9tricas por candidato, split y escenario |",
        "| `STRATEGY_RESULTS.json` | lo mismo en JSON, m\u00e1s scope, params congelados y procedencia |",
        "| `TRADES.csv` | una fila por operaci\u00f3n cerrada, con costes desglosados y R m\u00faltiple |",
        "| `EQUITY_CURVE.csv` | curva de capital por candidato y split (escenario BASE) |",
        "| `RUN_REPORT.json` | metadatos de la medida, integridad (sha256/tama\u00f1o) y veredictos |",
        "",
    ]
    return "\n".join(lines)


def _provenance_rows(campaign: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for candidate_id, payload in campaign["candidates"].items():
        provenance = payload["scope"]["provenance"]
        for asset in ASSETS:
            entry = provenance.get(asset) or {}
            rows.append(
                f"| {candidate_id} | {payload['scope']['timeframe']} | {entry.get('bars')} | "
                f"{_iso(entry.get('first_ts'))} | {_iso(entry.get('last_ts'))} | "
                f"`{str(entry.get('sha256'))[:16]}\u2026` |"
            )
    return rows


def _iso(ts: Any) -> str:
    if not isinstance(ts, int):
        return "n/a"
    return datetime.fromtimestamp(ts / 1000, tz=UTC).date().isoformat()
