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

import dataclasses
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
    TrendFollow,
    build_candidates,
    build_context,
)
from .costs import ADMISSION_SCENARIO as ADMISSION_SCENARIO_LABEL
from .costs import COST_SCENARIOS, CostPlane, cost_plane
from .data import ASSETS, REPO, OHLCVBar, load_1h, load_15m, resample
from .features import (
    MARKET_REGIME_RULE,
    MarketRegimeRow,
    atr,
    market_regime_at,
    market_regime_series,
)
from .simulator import RiskPolicy, buy_and_hold
from .simulator import run_portfolio as run_portfolio_sim

__all__ = [
    "ABLATION",
    "ABLATION_DECISION",
    "ADMISSION_CRITERIA",
    "CANDIDATE_SCOPES",
    "ENTRY_TIMING_H2",
    "ENTRY_TIMING_H2_DECISION",
    "RISK_ABLATION",
    "RISK_ABLATION_DECISION",
    "SPLITS",
    "VOL_FILTER_H4",
    "VOL_FILTER_H4_DECISION",
    "ablation_verdict",
    "load_risk_policy",
    "risk_ablation_verdict",
    "risk_budgets",
    "run_campaign",
    "run_entry_timing_h2",
    "run_risk_budget_ablation",
    "run_trend_filter_ablation",
    "run_vol_filter_h4",
    "write_ablation_artifacts",
    "write_entry_timing_artifacts",
    "write_risk_ablation_artifacts",
    "write_vol_filter_artifacts",
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
#: "1h" was added for WP-EDGE-07 Track C's ACTIVE book (a one-hour clock); the entry is
#: additive, so no frozen lane's Sharpe moves because of it.
BARS_PER_YEAR: dict[str, float] = {
    "15m": 4 * 24 * 365,
    "1h": 24 * 365,
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
        "id": "DEF-EDGE01-09",
        "symptom": (
            "The recorded source digest identified one copy of the code, not the code: "
            "the same commit gave three different digests (working tree, stored blob, "
            "clean checkout) because git rewrites line endings on this machine."
        ),
        "cause": (
            "The digest hashed raw bytes, and ``core.autocrlf`` means the same commit "
            "lands on disk as LF or CRLF depending on how it arrived."
        ),
        "fix": (
            "The digest folds CRLF to LF before hashing and the rule is published next "
            "to the digest in RUN_REPORT.json, so a clean checkout reproduces it."
        ),
        "evidence": (
            "measured: worktree c832d958..., blob a81cb296..., clean checkout "
            "313b140b... for commit ab7be9c before the fix; identical after it"
        ),
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
    {
        "id": "DEF-EDGE01-08",
        "symptom": (
            "A position still open when the window ended was settled at the last bar "
            "of the whole corpus: a 2023 DEV decision could be closed with a 2026 "
            "price, and the equity curve (which stops with the window) no longer "
            "matched the sum of the trade results. Found by the verifier's "
            "EQUITY_CONSERVATION check, not by reading the code."
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
    "The ``regime`` column of a trade is the candidate's OWN entry trend state "
    "(the 1h/4h/1d filter that let the trade through), NOT a market regime: a "
    "candidate that only enters in an uptrend can only ever print one value, so "
    "the pre-registered ``require_min_positive_regimes`` criterion is structurally "
    "one-sided for them and is disclosed as weak rather than presented as proof "
    "of multi-regime coverage. The market coverage question is answered by "
    "``market_context``, a benchmark label independent of every candidate.",
    "``market_context`` is benchmark-relative (BTC daily, see MARKET_CONTEXT rule "
    "in RUN_REPORT.json): it says what the market was doing, not what the asset "
    "traded was doing. It comes from the 1h corpus, which ends 2026-02-28, so the "
    "intraday OOS window is only labelled up to that date and carries UNDEFINED "
    "after it; the count of UNDEFINED decisions is reported instead of being "
    "quietly folded into a neighbouring label.",
    "Long-only: the runtime trades Binance spot, so no short side was simulated for "
    "any candidate even where a down-breakout would be symmetric.",
    "EDGE-TREND-01 has a trend filter (EMA50 > EMA200 and price above EMA200) but "
    "no SEPARATE volatility entry filter: volatility enters the ruleset through the "
    "ATR used for the stop distance, the modelled objective and the trailing exit, "
    "and through the cost-coverage gate, which grows with the volatility it expects "
    "to pay for. Adding a volatility filter now, after seeing the results, would be "
    "exactly the post-hoc adjustment this WP refuses to make; it is stated here and "
    "carried forward as hypothesis H4 instead.",
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
    "trend_4h_oos_review": {
        "decision": "NOT_SUFFICIENT_EVIDENCE",
        "asking": "is there enough out-of-sample evidence to take the frozen 4h trend ruleset to PAPER?",
        "answer": (
            "no. OOS is positive (+208.01 USDT, +160.67 under 2x fees) but one trade "
            "carries 79.87% of the net, only ETH of the three assets is positive, and "
            "VAL is flat; the WP's own admission rule returns INSUFFICIENT_EVIDENCE. "
            "The paper pipeline stays untouched and nothing is certified."
        ),
        "evidence": "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json",
        "verdict_rule": "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json#verdict.decision_rule",
    },
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
        "result": (
            "TESTED on DEV only (scripts/edge01_ablation.py, "
            "reports/edge-recovery/WP-EDGE-01/ablation-h1/, ADR-0028): the answer "
            "is BREAKOUT_IS_THE_CAUSE, not the filter. Both arms consider the same "
            "3,260 DEV setups; removing the 1h gate resolves its 1,097 refusals "
            "into 668 extra signals and 429 refusals at the gates behind it, and "
            "only 23 of those signals survive the risk layer into a trade. The DEV "
            "gross stays negative (-128.96 USDT against -151.71 with the filter), "
            "so the entry rule loses before costs either way. Most of the extra "
            "participation is absorbed by the 5% drawdown kill switch "
            "(risk_drawdown_halt +630), which is a risk-budget statement, not an "
            "edge. No window was opened for the variant and nothing is promoted."
        ),
    },
    {
        "id": "H5",
        "hypothesis": (
            "H1's extra signals were refused by the RISK layer, not by the entry "
            "rules: the 5% peak-to-trough drawdown halt fired on 493 DEV entries and "
            "would have fired on more, which makes the risk budget a candidate "
            "ceiling on intraday frequency."
        ),
        "test": (
            "Run the frozen EDGE-INTRA-01 on DEV with the drawdown halt made inert "
            "(one field apart from config/risk.yaml) and read the marginal trades, "
            "the halt's duty cycle and the drawdown it buys."
        ),
        "result": (
            "TESTED on DEV only (scripts/edge01_risk_ablation.py, "
            "reports/edge-recovery/WP-EDGE-01/risk-budget-h5/, ADR-0029): see the "
            "ablation's own verdict, published with the two budgets, the marginal "
            "numbers and the drawdown cost of removing the protection. The runtime "
            "risk authority is untouched and nothing is promoted."
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
        "result": (
            "TESTED on DEV only (scripts/edge01_mechanism_ablation.py, "
            "reports/edge-recovery/WP-EDGE-01/entry-timing-h2/, ADR-0030): the "
            "answer is ENTRY_IS_LATE. Of the 290 fills the risk budget let through, "
            "236 (81%) land at or past 0.25 ATR above the level the signal itself "
            "names in hard_invalidation, and the 54 that fill closer in carry the "
            "better expectancy (-1.0882 USDT per trade against -1.8545). The near "
            "side is the only one positive BEFORE costs (+5.47 USDT against "
            "-157.18), so the loss is paid on the way in: the next variant is an "
            "entry at the level (limit or retest), not a stop or a cost change. The "
            "diagnostic reads the trades the risk budget allowed, not every signal "
            "(what the budget removed is H5), no window was opened for it and "
            "nothing is promoted. The variant it pointed at is H6 below."
        ),
    },
    {
        "id": "H6",
        "hypothesis": (
            "H2's reading, turned into an entry: if the book pays for the extension, "
            "the same signals entered on a resting limit AT the broken level should "
            "buy back the part of the move the breakout gives away."
        ),
        "test": (
            "Rest the frozen signals as limit buys at the level they broke, let the "
            "bars decide whether they fill, and compare the arm against the frozen "
            "market arm on the same corpus, risk budget and costs. The ruleset is "
            "not touched: only the execution changes."
        ),
        "result": (
            "TESTED on DEV with VAL/OOS as confirmation (scripts/edge01_closure_experiments.py "
            "--experiment h6, reports/edge-recovery/WP-EDGE-01/retest-h6/, ADR-0031): the "
            "answer is RETEST_IMPROVES_NET with VIABLE execution. On DEV the variant "
            "fills 372 of 686 planned orders (54.23%: 128 expire unfilled, 183 are "
            "refused by the risk budget at the moment of the touch, 3 are cancelled "
            "at the end of the window) and books -495.88 USDT against the frozen arm's "
            "-496.4298, with the expectancy per trade improving from -1.7118 to "
            "-1.3330 (+0.3788). The gain repeats outside its design window: VAL +121.74 "
            "USDT (76.86% fills) and OOS +39.10 (81.82% fills). The same plans crossed "
            "at market reproduce the frozen arm exactly (-496.4298 / -1.7118), so the "
            "difference is the execution price and not the signal set. The absolute "
            "net stays negative: the entry improvement does not make the intraday "
            "breakout profitable, and nothing is promoted."
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
        "result": (
            "TESTED on DEV/VAL/OOS without touching a parameter (scripts/"
            "edge01_closure_experiments.py --experiment oos, reports/edge-recovery/"
            "WP-EDGE-01/oos-trend-4h/, ADR-0031): the answer is NOT_SUFFICIENT_EVIDENCE "
            "for PAPER, and the reason is exactly the fat tail H3 named. OOS nets "
            "+208.01 USDT over 52 trades and stays positive under 2x fees (+160.67), "
            "its drawdown (2.57%) is far below buy & hold's, and two of the three "
            "calendar periods are positive, but the largest single trade is 79.87% of "
            "the whole OOS net: the window is one trade. The per-asset books say the "
            "same thing about concentration - OOS BTC +3.06 (and -14.68 under 2x "
            "fees), ETH +281.60, SOL -75.55 - so the only real positive is ETH, and "
            "VAL is essentially flat (+4.53 over 58 trades). The WP's own admission "
            "rule agrees: INSUFFICIENT_EVIDENCE. Nothing goes to PAPER."
        ),
    },
    {
        "id": "H4",
        "hypothesis": (
            "EDGE-TREND-01 has no separate volatility entry filter: volatility only "
            "reaches it through the ATR-scaled stop, so it trades quiet and violent "
            "regimes alike, and the losses may concentrate where a trend starts from "
            "a dead-volatility base."
        ),
        "test": (
            "Declare a small grid of minimum-ATR thresholds BEFORE looking at VAL "
            "or OOS, pick on DEV only, freeze, then measure once. If the filter "
            "cannot be justified on DEV, it does not go in — a filter chosen after "
            "the out-of-sample window has been read proves nothing."
        ),
        "result": (
            "TESTED on DEV only (scripts/edge01_mechanism_ablation.py, "
            "reports/edge-recovery/WP-EDGE-01/vol-filter-h4/, ADR-0030): the "
            "answer is FILTER_NOT_JUSTIFIED_ON_DEV, so the frozen ruleset gains no "
            "min_atr_pct field and its frozen threshold stays null. The grid was "
            "computed from DEV BEFORE any arm ran (nearest rank at the 25th/50th/"
            "75th percentile of atr/close over 29,206 bars: 1.551912 / 2.239198 / "
            "3.330741), every arm is the frozen candidate plus that one field, and "
            "every threshold loses net against the unfiltered baseline (1,921.18 "
            "USDT: p25 1,595.54, p50 993.67, p75 499.98). The filter cuts "
            "participation without improving the quality of a trade, so it is not "
            "adopted. Published with the verdict, not promoted: p75 keeps the "
            "baseline's expectancy on 26% of the trades and less than half the "
            "drawdown, which is a question for a new hypothesis, not a change. VAL "
            "and OOS were not read."
        ),
    },
]


#: H1 ablation — the frozen EDGE-INTRA-01 with its 1h trend filter removed.
#:
#: Measured on DEV ONLY. The variant was designed after VAL and OOS had been read,
#: so reading them again for it would make those windows in-sample: the ablation
#: is only allowed to answer the question "is the loss in the filter or in the
#: breakout?" on DEV, and a result there that survives goes back through the
#: pre-registered process before any window is measured again.
ABLATION: dict[str, Any] = {
    "id": "ABL-EDGE01-H1",
    "hypothesis": "H1",
    "base_candidate": "edge_intra_01",
    "ablation_candidate": "edge_intra_01_no_trend",
    "removed": "use_trend_filter",
    "split": "intraday",
    "window": "DEV",
    "scenario": "BASE",
    "horizon_minutes": 240.0,
}

#: Frozen BEFORE the ablation ran, so the verdict cannot be chosen after the
#: numbers are on screen. ``gross`` is mid-to-mid before spread, slippage, impact
#: and fees: it answers "did the entry pick the right direction" on its own, with
#: financing taken out of the picture.
ABLATION_DECISION: dict[str, Any] = {
    "min_dev_trades": 30,
    "gross_positive_usdt": 0.0,
    "meaning": {
        "BREAKOUT_IS_THE_CAUSE": (
            "the ablation is also non-positive BEFORE costs: removing the filter "
            "does not create a pre-cost edge, so the entry rule itself is what "
            "loses. The filter was not hiding a winner."
        ),
        "FILTER_SUPPRESSED_A_PRECOST_EDGE": (
            "the ablation turns gross-positive while staying net <= 0: the 1h "
            "gate was suppressing trades that chose direction correctly, and the "
            "remaining loss is cost, not the breakout."
        ),
        "FILTER_HARMS_EDGE": (
            "the ablation is positive both before and after costs: the 1h gate "
            "removed genuinely profitable participation, so the filter itself is "
            "what destroyed the result."
        ),
        "INCONCLUSIVE": (
            "one arm has fewer than the minimum DEV trades, or the comparison is "
            "otherwise unpowered: reported as unpowered, never as a direction."
        ),
    },
    "rule": (
        "DEV gross (before costs) of the ablation versus 0, then its net: "
        "<= 0 -> BREAKOUT_IS_THE_CAUSE; > 0 with net <= 0 -> "
        "FILTER_SUPPRESSED_A_PRECOST_EDGE; > 0 with net > 0 -> FILTER_HARMS_EDGE; "
        "either arm below the minimum DEV trades -> INCONCLUSIVE."
    ),
}


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


def _load_corpus(split_name: str, timeframe: str) -> _Corpus:
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
    by_market_context: dict[str, Any] = {}
    for label in sorted({t.get("market_context") or "UNDEFINED" for t in trades}):
        subset = [t for t in trades if (t.get("market_context") or "UNDEFINED") == label]
        by_market_context[label] = {
            "trades": len(subset),
            "net": round(sum(t["net"] for t in subset), 4),
            "win_rate": round(
                100.0 * sum(1 for t in subset if t["net"] > 0) / len(subset), 4
            )
            if subset
            else None,
        }
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
        "by_market_context": by_market_context,
        "by_regime_note": (
            "entry trend state of the candidate's own filter (the value that let the "
            "trade through), NOT a market regime; see by_market_context for the "
            "benchmark-relative one"
        ),
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


def _market_context_series() -> tuple[tuple[MarketRegimeRow, ...], dict[str, Any]]:
    """The benchmark market regime, built once from the longest local corpus.

    The label is a property of the market, computed from BTC alone, so it is the
    same for every candidate and every cost scenario: pairing it with a trade
    cannot be tuned. It is read as-of the decision instant, never later.
    """
    corpus = load_1h("BTC")
    daily = resample(corpus, "1d")
    rows = market_regime_series(list(daily.bars))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.label] = counts.get(row.label, 0) + 1
    meta = {
        "benchmark": "BTC",
        "timeframe": "1d (aggregated from 1h shards; a day exists only when its 24 contiguous hours do)",
        "rule": MARKET_REGIME_RULE,
        "labels": ["BULL", "BEAR", "SIDEWAYS", "UNDEFINED"],
        "sources": list(corpus.sources),
        "source_sha256": corpus.sha256,
        "days": len(rows),
        "first_close_ms": rows[0].close_ms if rows else None,
        "last_close_ms": rows[-1].close_ms if rows else None,
        "label_days": counts,
        "artefact": "MARKET_CONTEXT.csv",
    }
    return rows, meta


def run_campaign(*, scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE")) -> dict[str, Any]:
    """Run every candidate over every split, in every cost scenario."""
    policy = load_risk_policy()
    regime_rows, regime_meta = _market_context_series()
    results: dict[str, Any] = {}
    corpus_cache: dict[str, _Corpus] = {}
    for candidate_id, scope in CANDIDATE_SCOPES.items():
        split_name = str(scope["split"])
        timeframe = str(scope["timeframe"])
        if candidate_id not in corpus_cache:
            corpus_cache[candidate_id] = _load_corpus(split_name, timeframe)
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
                # The market label is attached per trade, as-of the decision
                # instant, from a series no candidate can influence.
                for trade in sim.trades:
                    trade["market_context"] = market_regime_at(
                        regime_rows, int(trade["decision_ts"])
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
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "admission_criteria": ADMISSION_CRITERIA,
        "risk_policy": policy.to_dict(),
        "candidates": results,
    }


def ablation_verdict(base: dict[str, Any], ablation: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered reading of the H1 comparison.

    Pure: no clock, no I/O, no candidate objects — two metric dictionaries in,
    one verdict out, so the same inputs always produce the same label and the
    verifier can recompute it from the published artefacts alone.
    """
    min_trades = int(ABLATION_DECISION["min_dev_trades"])
    threshold = float(ABLATION_DECISION["gross_positive_usdt"])
    base_trades = int(base.get("trades") or 0)
    ab_trades = int(ablation.get("trades") or 0)
    ab_gross = float(ablation.get("gross_usdt") or 0.0)
    ab_net = float(ablation.get("net_usdt") or 0.0)

    if base_trades < min_trades or ab_trades < min_trades:
        verdict = "INCONCLUSIVE"
        reason = (
            f"DEV trades {base_trades} (base) / {ab_trades} (ablation) below the "
            f"pre-registered minimum of {min_trades}: no direction is claimed"
        )
    elif ab_gross <= threshold:
        verdict = "BREAKOUT_IS_THE_CAUSE"
        reason = (
            f"the ablation's DEV gross is {ab_gross:,.2f} USDT before costs, not "
            f"positive: the entry rule loses without the filter's help, so the "
            f"filter was not hiding an edge"
        )
    elif ab_net <= 0:
        verdict = "FILTER_SUPPRESSED_A_PRECOST_EDGE"
        reason = (
            f"the ablation's DEV gross is +{ab_gross:,.2f} USDT before costs while "
            f"its net is {ab_net:,.2f} USDT: the 1h gate was removing trades that "
            f"picked direction correctly, and what is left is a cost problem"
        )
    else:
        verdict = "FILTER_HARMS_EDGE"
        reason = (
            f"the ablation is positive in DEV both before (+{ab_gross:,.2f}) and "
            f"after ({ab_net:,.2f}) costs: the 1h gate removed profitable "
            f"participation"
        )

    gross_per_trade = {
        "base": round(float(base.get("gross_usdt") or 0.0) / base_trades, 4)
        if base_trades
        else None,
        "ablation": round(ab_gross / ab_trades, 4) if ab_trades else None,
    }
    base_signals = int(base.get("signal_count") or 0)
    ab_signals = int(ablation.get("signal_count") or 0)
    return {
        "verdict": verdict,
        "reason": reason,
        "rule": dict(ABLATION_DECISION),
        "gross_per_trade_usdt": gross_per_trade,
        "gross_per_trade_delta_usdt": (
            round(gross_per_trade["ablation"] - gross_per_trade["base"], 4)
            if gross_per_trade["base"] is not None and gross_per_trade["ablation"] is not None
            else None
        ),
        "signal_multiple": round(ab_signals / base_signals, 4) if base_signals else None,
    }


def _funnel(refusals: list[dict[str, Any]]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for refusal in refusals:
        key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
        mix[key] = mix.get(key, 0) + 1
    return mix


def _funnel_delta(base: dict[str, int], ablation: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(base) | set(ablation))
    return {key: ablation.get(key, 0) - base.get(key, 0) for key in keys}


def run_trend_filter_ablation() -> dict[str, Any]:
    """Run H1 on DEV ONLY and compare the funnel and the gross before costs.

    Both arms are the same candidate class, the same corpus, the same DEV window,
    the same BASE cost plane and the same risk policy; the ONLY difference is
    ``use_trend_filter``. No VAL or OOS bar is read.
    """
    split_name = str(ABLATION["split"])
    window_name = str(ABLATION["window"])
    bounds = SPLITS[split_name][window_name]
    start, end = int(bounds["start"]), int(bounds["end"])
    timeframe = "15m"
    scenario = str(ABLATION["scenario"])
    horizon = float(ABLATION["horizon_minutes"])
    corpus = _load_corpus(split_name, timeframe)
    plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon).scaled(scenario)
    policy = load_risk_policy()
    regime_rows, regime_meta = _market_context_series()
    candidates = build_candidates()

    arms: dict[str, Any] = {}
    for role in ("base", "ablation"):
        candidate_id = str(ABLATION[f"{role}_candidate"])
        candidate = candidates[candidate_id]
        if candidate.timeframe != timeframe:  # pragma: no cover - guard
            raise ValueError(f"{candidate_id} is {candidate.timeframe}, expected {timeframe}")
        sim = run_portfolio_sim(
            candidate=candidate,
            bars_by_asset=corpus.bars_by_asset,
            plane=plane,
            policy=policy,
            context=corpus.context,
            window_start_ts=start,
            window_end_ts=end,
        )
        for trade in sim.trades:
            trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        metrics = _metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=(end - start) / 60_000.0,
            timeframe=timeframe,
            n_assets=len(ASSETS),
        )
        arms[role] = {
            "candidate_id": candidate_id,
            "params": dict(candidate.params),
            "use_trend_filter": bool(candidate.params.get("use_trend_filter", True)),
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(sim.signals),
            "_signal_rows": sim.signals,
            "refusals": _funnel(sim.refusals),
            "_trade_rows": sim.trades,
            "_refusal_rows": sim.refusals,
            **metrics,
        }

    verdict = ablation_verdict(arms["base"], arms["ablation"])
    verdict["funnel_delta"] = _funnel_delta(
        arms["base"]["refusals"], arms["ablation"]["refusals"]
    )
    return {
        "run_id": "wp-edge-01-ablation-h1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_state(),
        "source_digest": _source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_ablation.py",
                "scripts/edge01_ablation_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus, DEV window "
            "only; 0 orders, 0 credentials, 0 network calls, no VAL or OOS bar read"
        ),
        "entrypoint": "scripts/edge01_ablation.py",
        "verifier": "scripts/edge01_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "ablation": {
            **{k: v for k, v in ABLATION.items()},
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "assets": list(ASSETS),
            "timeframe": timeframe,
            "scenario": scenario,
            "plane": plane.to_dict(),
            "risk_policy": policy.to_dict(),
            "frozen_params": FROZEN_PARAMS["edge_intra_01"],
            "corpus_provenance": corpus.provenance,
            "market_context_meta": regime_meta,
        },
        "verdict": verdict,
        "arms": arms,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
    }


def write_ablation_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the ablation comparison: four CSVs, the markdown and the JSON digest."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trade_rows: list[dict[str, Any]] = []
    refusal_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    for role in ("base", "ablation"):
        arm = payload["arms"][role]
        for trade in arm["_trade_rows"]:
            row = dict(trade)
            row["run"] = role
            row["strategy"] = trade.get("candidate")
            row["candidate"] = arm["candidate_id"]
            trade_rows.append(row)
        for refusal in arm["_refusal_rows"]:
            refusal_rows.append(
                {
                    "run": role,
                    "candidate": arm["candidate_id"],
                    "source": refusal.get("source", "candidate"),
                    "reason": refusal.get("reason"),
                    "symbol": refusal.get("symbol", ""),
                    "decision_ts": refusal.get("decision_ts"),
                }
            )
        for signal in arm["_signal_rows"]:
            signal_rows.append(
                {
                    "run": role,
                    "candidate": arm["candidate_id"],
                    "symbol": signal.get("symbol", ""),
                    "bar_index": signal.get("bar_index"),
                    "decision_ts": signal.get("decision_ts"),
                    "regime": signal.get("regime"),
                    "risk_reward": signal.get("risk_reward"),
                    "expected_gross_bps": signal.get("expected_gross_bps"),
                    "expected_cost_bps": signal.get("expected_cost_bps"),
                    "expected_net_bps": signal.get("expected_net_bps"),
                }
            )

    trades_path = outdir / "ABLATION_TRADES.csv"
    _write_csv(trades_path, trade_rows)
    written["ABLATION_TRADES.csv"] = trades_path

    refusals_path = outdir / "ABLATION_REFUSALS.csv"
    _write_csv(refusals_path, refusal_rows)
    written["ABLATION_REFUSALS.csv"] = refusals_path

    signals_path = outdir / "ABLATION_SIGNALS.csv"
    _write_csv(signals_path, signal_rows)
    written["ABLATION_SIGNALS.csv"] = signals_path

    # The benchmark label of every trade is republished here with the series it
    # was read from, so the ablation's own verifier can re-derive it instead of
    # taking this folder's word for the market it was measured in.
    context_path = outdir / "MARKET_CONTEXT.csv"
    _write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "ABLATION.md"
    md_path.write_text(_ablation_markdown(payload), encoding="utf-8")
    written["ABLATION.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "ablation": payload["ablation"],
        "market_context": payload["market_context"]["meta"],
        "verdict": payload["verdict"],
        "arms": {
            role: _public({k: v for k, v in arm.items() if not k.startswith("_")})
            for role, arm in payload["arms"].items()
        },
        "artifacts": {
            name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every ablation artefact except ABLATION.json itself, "
            "which is the file carrying them"
        ),
    }
    json_path = outdir / "ABLATION.json"
    json_path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written["ABLATION.json"] = json_path
    return written


def _ablation_markdown(payload: dict[str, Any]) -> str:
    ablation = payload["ablation"]
    base = payload["arms"]["base"]
    ab = payload["arms"]["ablation"]
    verdict = payload["verdict"]
    lines = [
        "# ABLATION H1 — EDGE-INTRA-01 sin el filtro de tendencia de 1h",
        "",
        f"- run_id: `{payload['run_id']}`",
        f"- hipotesis: {ablation['hypothesis']} (removed: `{ablation['removed']}`)",
        f"- ventana: {ablation['window']} "
        f"{ablation['window_start_utc'][:10]}..{ablation['window_end_utc'][:10]} "
        "(SOLO DEV: VAL y OOS no se leen)",
        f"- activos: {', '.join(ablation['assets'])} (spot, long only)",
        f"- escenario de coste: {ablation['scenario']}",
        f"- params_hash (reglas congeladas): `{payload['params_hash']}`",
        f"- huella del codigo medido: `{payload['source_digest']['combined_sha256']}`",
        f"- commit: `{payload['git']['head_commit']}`",
        "",
        "## Veredicto",
        "",
        f"**{verdict['verdict']}** — {verdict['reason']}",
        "",
        "Regla fijada antes de ejecutar:",
        "",
        f"> {verdict['rule']['rule']}",
        "",
        "## Bruto antes de costes (DEV)",
        "",
        "| corrida | filtro 1h | operaciones | senales | bruto (mid-to-mid) | comisiones | "
        "coste de precio | neto | bruto/op |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for role, arm, label in (("base", base, "base"), ("ablation", ab, "ablacion")):
        per_trade = verdict["gross_per_trade_usdt"][role]
        lines.append(
            f"| {label} | {'si' if arm['use_trend_filter'] else 'no'} | {arm['trades']} | "
            f"{arm['signal_count']} | {_num(arm['gross_usdt'])} | {_num(arm['fees_usdt'])} | "
            f"{_num(arm['price_costs_usdt'])} | {_num(arm['net_usdt'])} | {_num(per_trade)} |"
        )
    lines += [
        "",
        "El bruto es el resultado mid-to-mid de cada operacion ya ejecutada: aísla la "
        "direccion elegida de spread, slippage, impacto y comisiones.",
        "",
        "## Embudo de rechazos (DEV)",
        "",
        "| motivo (origen:razon) | base | ablacion | delta |",
        "|---|---|---|---|",
    ]
    keys = sorted(set(base["refusals"]) | set(ab["refusals"]))
    for key in keys:
        b = base["refusals"].get(key, 0)
        a = ab["refusals"].get(key, 0)
        lines.append(f"| {key} | {b:,} | {a:,} | {a - b:+,} |")
    lines += [
        "",
        "| barometro | base | ablacion |",
        "|---|---|---|",
        f"| barras evaluadas | {base['bars_evaluated']:,} | {ab['bars_evaluated']:,} |",
        f"| barras de warm-up | {base['warmup_bars']:,} | {ab['warmup_bars']:,} |",
        f"| senales impresas | {base['signal_count']:,} | {ab['signal_count']:,} |",
        f"| operaciones ejecutadas | {base['trades']:,} | {ab['trades']:,} |",
        "",
        f"Multiplo de senales ablacion/base: {verdict['signal_multiple']}.",
        "",
        "## Contexto de mercado de las operaciones (benchmark BTC, as-of la decision)",
        "",
    ]
    labels_seen: dict[str, int] = {}
    for _role, arm, label in (("base", base, "base"), ("ablation", ab, "ablacion")):
        parts = ", ".join(
            f"{k}={v['trades']} ({_num(v['net'])} USDT)"
            for k, v in sorted((arm.get("by_market_context") or {}).items())
        )
        for key, value in (arm.get("by_market_context") or {}).items():
            labels_seen[key] = labels_seen.get(key, 0) + int(value["trades"])
        lines.append(f"- {label}: {parts or 'sin operaciones'}")
    if len(labels_seen) == 1:
        only = next(iter(labels_seen))
        lines.append(
            f"- Las dos ramas operaron con el benchmark en **{only}** en el 100% de sus "
            f"operaciones: la comparacion cae dentro de una sola etiqueta de mercado y no "
            f"mezcla regimenes, asi que un bruto negativo aqui no se explica por haber "
            f"medido en un mercado adverso."
        )
    lines += [
        "",
        "## Artefactos de esta ablacion",
        "",
        "- `ABLATION.json` — comparacion completa, regla congelada y veredicto",
        "- `ABLATION_TRADES.csv` — operaciones de las dos corridas en DEV",
        "- `ABLATION_REFUSALS.csv` — rechazos crudos (origen y motivo)",
        "- `ABLATION_SIGNALS.csv` — senales impresas por el candidato, antes del riesgo",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark (BTC diario) con la que se etiqueta "
        "cada operacion, reproducida aqui para que el verificador la re-derive",
        "- verificado por `scripts/edge01_ablation_verify.py` en un proceso aparte que "
        "solo lee estos ficheros",
        "",
        "## Limitaciones de esta ablacion",
        "",
        "- Medida SOLO en DEV: al haberse disenado despues de leer VAL y OOS, no puede "
        "usar esas ventanas sin volverlas in-sample.",
        "- Un veredicto de filtro/breakout en DEV no es una conclusion de rentabilidad; "
        "cualquier variante que promueva tendria que pasar de nuevo el proceso "
        "pre-registrado (VAL congelado, luego OOS una sola vez).",
        "- Sin libro de ordenes historico: el bruto mid-to-mid no incluye seleccion "
        "adversa; el coste de precio modelado cubre spread, slippage e impacto.",
        "- Solo lado largo (spot).",
        "",
    ]
    return "\n".join(lines)


def _source_digest(extra_scripts: list[str]) -> dict[str, Any]:
    """sha256 of the package and the named scripts, line endings normalised."""
    import hashlib

    files = sorted((REPO / "src" / "trading_bot" / "research" / "edge01").glob("*.py"))
    files += [p for p in ((REPO / name) for name in extra_scripts) if p.exists()]
    combined = hashlib.sha256()
    per_file: dict[str, str] = {}
    for path in files:
        raw = _normalised(path.read_bytes())
        combined.update(path.name.encode())
        combined.update(raw)
        per_file[str(path.relative_to(REPO)).replace("\\", "/")] = hashlib.sha256(raw).hexdigest()
    return {"combined_sha256": combined.hexdigest(), "files": per_file}


#: H5 — the RISK-BUDGET ablation, formulated AFTER H1 and frozen before it ran.
#:
#: H1 showed the extra intraday signals were not refused by the entry rules but by
#: the risk layer, and specifically by the 5% peak-to-trough drawdown halt. That
#: raises a separate question the candidate cannot answer about itself: was the halt
#: the real ceiling on intraday participation, and were the trades it refused worth
#: taking?
#:
#: The variant budget is a RESEARCH INSTRUMENT, not a policy change. The runtime's
#: risk authority (``config/risk.yaml``, read verbatim for the base arm) is not
#: modified, the variant is never wired into PAPER, and the experiment is DEV only
#: because the halt's behaviour in VAL/OOS has already been observed in the WP run.
RISK_ABLATION: dict[str, Any] = {
    "id": "ABL-EDGE01-H5",
    "hypothesis": "H5",
    "candidate": "edge_intra_01",
    "base_budget": "config/risk.yaml verbatim (the runtime's own authority)",
    "variant_budget": (
        "the same budget with the peak-to-trough drawdown halt made inert "
        "(drawdown_halt_pct=100), so the halt can never fire"
    ),
    "changed_field": "drawdown_halt_pct",
    "inert_halt_pct": 100.0,
    "split": "intraday",
    "window": "DEV",
    "scenario": "BASE",
    "horizon_minutes": 240.0,
}

#: Frozen BEFORE the variant ran. ``min_extra_trades`` is the sample floor below
#: which "the halt was not binding" is the honest reading, not a direction.
RISK_ABLATION_DECISION: dict[str, Any] = {
    "min_extra_trades": 20,
    "marginal_net_positive_usdt": 0.0,
    "meaning": {
        "INCONCLUSIVE": (
            "the halt is inert in the variant but barely any more trades execute: "
            "it was not binding on realised trades, so nothing is claimed"
        ),
        "RISK_NOT_BINDING_ON_PROFITABILITY": (
            "the halt blocked real participation, and the trades it blocked were "
            "NET NEGATIVE: the halt was doing risk work, and intraday frequency is "
            "not viable at this entry quality whatever the budget allows"
        ),
        "RISK_BUDGET_WAS_THE_CONSTRAINT": (
            "the extra trades are net positive but the variant is still net "
            "negative: the budget is one real ceiling, but removing it is not "
            "enough to make the frequency pay"
        ),
        "FREQUENCY_VIABLE": (
            "the variant is net positive: with the halt inert the intraday "
            "frequency pays after costs on DEV, which is a hypothesis to take back "
            "through the pre-registered process, not a promotion"
        ),
    },
    "rule": (
        "extra_trades = variant.trades - base.trades. Fewer than min_extra_trades "
        "-> INCONCLUSIVE; else marginal_net = variant.net - base.net: <= 0 -> "
        "RISK_NOT_BINDING_ON_PROFITABILITY; > 0 with the variant still net <= 0 -> "
        "RISK_BUDGET_WAS_THE_CONSTRAINT; > 0 and the variant net > 0 -> "
        "FREQUENCY_VIABLE."
    ),
}


def _halt_refusals(refusals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in refusals if r.get("reason") == "risk_drawdown_halt"]


def risk_ablation_verdict(base: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered reading of the H5 comparison. Pure: no I/O, no clock."""
    min_extra = int(RISK_ABLATION_DECISION["min_extra_trades"])
    threshold = float(RISK_ABLATION_DECISION["marginal_net_positive_usdt"])
    base_trades = int(base.get("trades") or 0)
    var_trades = int(variant.get("trades") or 0)
    extra_trades = var_trades - base_trades
    base_net = float(base.get("net_usdt") or 0.0)
    var_net = float(variant.get("net_usdt") or 0.0)
    marginal_net = var_net - base_net

    if extra_trades < min_extra:
        verdict = "INCONCLUSIVE"
        reason = (
            f"the budget change added only {extra_trades} trades on DEV (floor "
            f"{min_extra}): the halt was not binding on realised trades"
        )
    elif marginal_net <= threshold:
        verdict = "RISK_NOT_BINDING_ON_PROFITABILITY"
        reason = (
            f"the halt refused {int(base.get('halt_refusals') or 0)} entries in the "
            f"base arm and releasing it added {extra_trades} trades worth "
            f"{marginal_net:,.2f} USDT net: the trades it refused were not worth "
            f"taking, so the budget is not what makes intraday unprofitable"
        )
    elif var_net <= 0:
        verdict = "RISK_BUDGET_WAS_THE_CONSTRAINT"
        reason = (
            f"the extra {extra_trades} trades added {marginal_net:,.2f} USDT net, "
            f"but the variant is still net negative at {var_net:,.2f} USDT: the "
            f"budget is one ceiling, not the only one"
        )
    else:
        verdict = "FREQUENCY_VIABLE"
        reason = (
            f"with the halt inert the strategy is net positive on DEV "
            f"({var_net:,.2f} USDT over {var_trades} trades): a hypothesis to take "
            f"back through the pre-registered process, never a promotion"
        )

    return {
        "verdict": verdict,
        "reason": reason,
        "rule": dict(RISK_ABLATION_DECISION),
        "extra_trades": extra_trades,
        "marginal_gross_usdt": round(
            float(variant.get("gross_usdt") or 0.0) - float(base.get("gross_usdt") or 0.0), 4
        ),
        "marginal_net_usdt": round(marginal_net, 4),
        "marginal_expectancy_usdt": round(marginal_net / extra_trades, 4) if extra_trades else None,
        "drawdown_delta_pct": round(
            float(variant.get("max_drawdown_pct") or 0.0)
            - float(base.get("max_drawdown_pct") or 0.0),
            4,
        ),
    }


def risk_budgets() -> dict[str, RiskPolicy]:
    """The two budgets of the H5 experiment: the runtime's, and it minus the halt.

    Split out so the one-field-apart property is a unit test on its own, rather than
    something only a full DEV run can demonstrate. The base budget is
    ``config/risk.yaml`` read verbatim; the variant is that object with a single
    field replaced, so no limit can drift into the variant by accident.
    """
    base = load_risk_policy()
    return {
        "base": base,
        "variant": dataclasses.replace(
            base, drawdown_halt_pct=float(RISK_ABLATION["inert_halt_pct"])
        ),
    }


def run_risk_budget_ablation() -> dict[str, Any]:
    """Run H5 on DEV ONLY: the same candidate, two risk budgets, one field apart."""
    split_name = str(RISK_ABLATION["split"])
    window_name = str(RISK_ABLATION["window"])
    bounds = SPLITS[split_name][window_name]
    start, end = int(bounds["start"]), int(bounds["end"])
    timeframe = "15m"
    scenario = str(RISK_ABLATION["scenario"])
    horizon = float(RISK_ABLATION["horizon_minutes"])
    candidate_id = str(RISK_ABLATION["candidate"])
    corpus = _load_corpus(split_name, timeframe)
    plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon).scaled(scenario)
    regime_rows, regime_meta = _market_context_series()

    policies = risk_budgets()

    arms: dict[str, Any] = {}
    for role in ("base", "variant"):
        policy = policies[role]
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
        for trade in sim.trades:
            trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        metrics = _metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=(end - start) / 60_000.0,
            timeframe=timeframe,
            n_assets=len(ASSETS),
        )
        halt = _halt_refusals(sim.refusals)
        arms[role] = {
            "candidate_id": candidate_id,
            "policy": policy.to_dict(),
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(sim.signals),
            "refusals": _funnel(sim.refusals),
            "halt_refusals": len(halt),
            "halt_days": len({int(r["decision_ts"]) // 86_400_000 for r in halt}),
            "_trade_rows": sim.trades,
            "_refusal_rows": sim.refusals,
            "_signal_rows": sim.signals,
            **metrics,
        }
        trade_count = int(arms[role]["trades"])
        arms[role]["gross_per_trade_usdt"] = (
            round(arms[role]["gross_usdt"] / trade_count, 4) if trade_count else None
        )

    verdict = risk_ablation_verdict(arms["base"], arms["variant"])
    verdict["funnel_delta"] = _funnel_delta(
        arms["base"]["refusals"], arms["variant"]["refusals"]
    )
    window_days = max((end - start) / 86_400_000.0, 1e-9)
    for role in ("base", "variant"):
        arms[role]["halt_days_pct_of_window"] = round(
            100.0 * arms[role]["halt_days"] / window_days, 4
        )
    return {
        "run_id": "wp-edge-01-risk-ablation-h5",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_state(),
        "source_digest": _source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_risk_ablation.py",
                "scripts/edge01_risk_ablation_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus, DEV window "
            "only; 0 orders, 0 credentials, 0 network calls, no VAL or OOS bar read"
        ),
        "entrypoint": "scripts/edge01_risk_ablation.py",
        "verifier": "scripts/edge01_risk_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "risk_ablation": {
            **RISK_ABLATION,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": round(window_days, 4),
            "assets": list(ASSETS),
            "timeframe": timeframe,
            "plane": plane.to_dict(),
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": _sha256(RISK_CONFIG),
            "risk_config_used_verbatim_for_base": True,
            "runtime_untouched": (
                "this budget is a research instrument: config/risk.yaml is read, "
                "never written, and nothing here is wired into the PAPER runtime"
            ),
            "corpus_provenance": corpus.provenance,
        },
        "verdict": verdict,
        "arms": arms,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
    }


def write_risk_ablation_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the risk-budget comparison: four CSVs, the markdown and the JSON."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trade_rows: list[dict[str, Any]] = []
    refusal_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    for role in ("base", "variant"):
        arm = payload["arms"][role]
        for trade in arm["_trade_rows"]:
            row = dict(trade)
            row["run"] = role
            row["strategy"] = trade.get("candidate")
            row["candidate"] = arm["candidate_id"]
            trade_rows.append(row)
        for refusal in arm["_refusal_rows"]:
            refusal_rows.append(
                {
                    "run": role,
                    "candidate": arm["candidate_id"],
                    "source": refusal.get("source", "candidate"),
                    "reason": refusal.get("reason"),
                    "symbol": refusal.get("symbol", ""),
                    "decision_ts": refusal.get("decision_ts"),
                }
            )
        for signal in arm["_signal_rows"]:
            signal_rows.append(
                {
                    "run": role,
                    "candidate": arm["candidate_id"],
                    "symbol": signal.get("symbol", ""),
                    "bar_index": signal.get("bar_index"),
                    "decision_ts": signal.get("decision_ts"),
                    "regime": signal.get("regime"),
                    "risk_reward": signal.get("risk_reward"),
                    "expected_gross_bps": signal.get("expected_gross_bps"),
                    "expected_cost_bps": signal.get("expected_cost_bps"),
                    "expected_net_bps": signal.get("expected_net_bps"),
                }
            )

    for name, rows in (
        ("RISK_TRADES.csv", trade_rows),
        ("RISK_REFUSALS.csv", refusal_rows),
        ("RISK_SIGNALS.csv", signal_rows),
    ):
        path = outdir / name
        _write_csv(path, rows)
        written[name] = path

    context_path = outdir / "MARKET_CONTEXT.csv"
    _write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "RISK_ABLATION.md"
    md_path.write_text(_risk_ablation_markdown(payload), encoding="utf-8")
    written["RISK_ABLATION.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "risk_ablation": payload["risk_ablation"],
        "market_context": payload["market_context"]["meta"],
        "verdict": payload["verdict"],
        "arms": {
            role: _public({k: v for k, v in arm.items() if not k.startswith("_")})
            for role, arm in payload["arms"].items()
        },
        "artifacts": {
            name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every risk-ablation artefact except RISK_ABLATION.json "
            "itself, which is the file carrying them"
        ),
    }
    json_path = outdir / "RISK_ABLATION.json"
    json_path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written["RISK_ABLATION.json"] = json_path
    return written


def _risk_ablation_markdown(payload: dict[str, Any]) -> str:
    abl = payload["risk_ablation"]
    base = payload["arms"]["base"]
    var = payload["arms"]["variant"]
    verdict = payload["verdict"]
    lines = [
        "# RIESGO H5 — EDGE-INTRA-01 con el kill switch de drawdown inerte (SOLO DEV)",
        "",
        f"- run_id: `{payload['run_id']}`",
        f"- candidato: `{abl['candidate']}` (reglas congeladas, sin cambios)",
        f"- presupuesto base: {abl['base_budget']}",
        f"- presupuesto variante: {abl['variant_budget']}",
        f"- unico campo distinto: `{abl['changed_field']}` = {abl['inert_halt_pct']}",
        f"- ventana: {abl['window']} {abl['window_start_utc'][:10]}..{abl['window_end_utc'][:10]} "
        "(SOLO DEV: VAL y OOS no se leen)",
        f"- activos: {', '.join(abl['assets'])} (spot, long only)",
        f"- escenario de coste: {abl['scenario']}",
        f"- config de riesgo leida tal cual: `{abl['risk_config_path']}` "
        f"(sha256 `{abl['risk_config_sha256'][:12]}`)",
        f"- params_hash de las reglas: `{payload['params_hash']}`",
        f"- huella del codigo medido: `{payload['source_digest']['combined_sha256'][:16]}`",
        "",
        "## Veredicto",
        "",
        f"**{verdict['verdict']}** — {verdict['reason']}",
        "",
        "Regla fijada antes de ejecutar:",
        "",
        f"> {verdict['rule']['rule']}",
        "",
        "## Los dos presupuestos",
        "",
        "| campo | base (config/risk.yaml) | variante |",
        "|---|---|---|",
    ]
    for field in sorted(base["policy"]):
        left = base["policy"][field]
        right = var["policy"][field]
        mark = "**" if left != right else ""
        lines.append(f"| `{field}` | {mark}{left}{mark} | {mark}{right}{mark} |")
    lines += [
        "",
        "## Efecto sobre el embudo y sobre la cuenta (DEV)",
        "",
        "| metrica | base | variante | delta |",
        "|---|---|---|---|",
    ]
    for label, key in (
        ("senales impresas", "signal_count"),
        ("operaciones ejecutadas", "trades"),
        ("bruto (mid-to-mid)", "gross_usdt"),
        ("bruto por operacion", "gross_per_trade_usdt"),
        ("comisiones", "fees_usdt"),
        ("coste de precio", "price_costs_usdt"),
        ("neto", "net_usdt"),
        ("expectancy por operacion (neto/op)", "expectancy_usdt"),
        ("max drawdown %", "max_drawdown_pct"),
        ("exposicion % del tiempo", "exposure_pct_of_time"),
        ("rechazos por kill switch", "halt_refusals"),
        ("dias con el kill switch activo", "halt_days"),
        ("% de la ventana con el kill switch activo", "halt_days_pct_of_window"),
    ):
        left, right = base[key], var[key]
        numeric = isinstance(left, (int, float)) and isinstance(right, (int, float))
        delta = _signed(right - left) if numeric else "n/a"
        lines.append(f"| {label} | {_count(left)} | {_count(right)} | {delta} |")
    lines += [
        "",
        "## Embudo de rechazos (DEV)",
        "",
        "| motivo (origen:razon) | base | variante | delta |",
        "|---|---|---|---|",
    ]
    for key in sorted(set(base["refusals"]) | set(var["refusals"])):
        b, v = base["refusals"].get(key, 0), var["refusals"].get(key, 0)
        lines.append(f"| {key} | {b:,} | {v:,} | {v - b:+,} |")
    lines += [
        "",
        "## Lectura marginal",
        "",
        f"- operaciones extra: **{verdict['extra_trades']}**"
        + (
            f" (expectancy marginal {_num(verdict['marginal_expectancy_usdt'])} USDT/op)"
            if verdict["marginal_expectancy_usdt"] is not None
            else ""
        ),
        f"- bruto marginal: {_num(verdict['marginal_gross_usdt'])} USDT sobre el neto "
        f"marginal {_num(verdict['marginal_net_usdt'])} USDT",
        f"- bruto por operacion: {_num(base.get('gross_per_trade_usdt'))} -> "
        f"{_num(var.get('gross_per_trade_usdt'))} USDT (la entrada marginal elige "
        f"direccion algo mejor, pero sigue sin pagar su coste de ida y vuelta)",
        f"- drawdown: {_num(base['max_drawdown_pct'])}% -> {_num(var['max_drawdown_pct'])}% "
        f"({_num(verdict['drawdown_delta_pct'])} puntos)",
        "",
        "Las dos ramas son **dos trayectorias de capital distintas**: el tamano de cada "
        "operacion se deriva del equity del momento, asi que la diferencia mide el "
        "efecto del presupuesto, no una atribucion operacion a operacion. Lo que si es "
        "una medida directa de si el riesgo dominaba el embudo es el ciclo de trabajo "
        "del kill switch (dias y rechazos) y la expectancy marginal de arriba.",
        "",
        "## Contexto de mercado de las operaciones",
        "",
    ]
    labels_seen: dict[str, int] = {}
    for role, arm in (("base", base), ("variant", var)):
        parts = ", ".join(
            f"{k}={v['trades']} ({_num(v['net'])} USDT)"
            for k, v in sorted((arm.get("by_market_context") or {}).items())
        )
        for key, value in (arm.get("by_market_context") or {}).items():
            labels_seen[key] = labels_seen.get(key, 0) + int(value["trades"])
        lines.append(f"- {role}: {parts or 'sin operaciones'}")
    if labels_seen:
        lines.append(
            "- etiquetas de benchmark presentes en la comparacion: "
            + ", ".join(f"{k}={v}" for k, v in sorted(labels_seen.items()))
        )
    censored = sorted(set(var.get("by_market_context") or {}) - set(base.get("by_market_context") or {}))
    if censored:
        lines.append(
            f"- El kill switch **censuro la cobertura**: la variante opera en "
            f"{', '.join(censored)}, etiquetas que la corrida base no llega a tocar en toda "
            f"la ventana. Un limite de riesgo que se dispara no solo reduce operaciones: "
            f"cambia el mercado que se mide, asi que la muestra base no es una version "
            f"mas pequena de la variante sino una muestra truncada."
        )
    lines += [
        "",
        "## Artefactos de esta ablacion de riesgo",
        "",
        "- `RISK_ABLATION.json` — comparacion completa, regla congelada y veredicto",
        "- `RISK_TRADES.csv` — operaciones de las dos corridas",
        "- `RISK_REFUSALS.csv` — rechazos crudos (origen y motivo)",
        "- `RISK_SIGNALS.csv` — senales del candidato antes del riesgo",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion",
        "- verificado por `scripts/edge01_risk_ablation_verify.py` en un proceso aparte",
        "",
        "## Limites",
        "",
        "- El presupuesto variante es un **instrumento de investigacion**, no una "
        "politica: `config/risk.yaml` se lee, nunca se escribe, y nada de esto se "
        "cablea en el runtime PAPER.",
        "- Medido SOLO en DEV. El comportamiento del kill switch en VAL/OOS ya se "
        "observo en la corrida del WP, asi que volver a tocarlo ahi no seria fuera "
        "de muestra.",
        "- Quitar el kill switch es quitar una proteccion, no solo un limite: el "
        "drawdown de la variante se publica arriba para que la comparacion no se lea "
        "como una mejora gratuita.",
        "- Sin libro de ordenes historico y solo lado largo (spot).",
        "",
    ]
    return "\n".join(lines)


# ===================================================================== #
# Mechanism experiments: H2 (entry timing) and H4 (entry volatility).
#
# Both reuse the frozen pattern of H1 and H5: a declaration written down
# BEFORE the run, a pre-registered decision rule, a DEV-only window, its own
# artefacts and its own independent verifier. A mechanism question gets its
# own experiment so a result is never attributed to the wrong cause:
#
# * H2 is a DIAGNOSTIC, not an ablation: it changes no rule. It re-runs the
#   frozen candidate under the runtime's own budget and splits the trades the
#   budget let through by how far past the broken level they were filled,
#   because "gross is negative" can mean the entry is late, not that the edge
#   is absent.
# * H4 is an ABLATION with a declared GRID: the same frozen candidate plus a
#   minimum ATR/close entry gate, four arms, selected on DEV and FROZEN. It
#   never reads VAL or OOS; the frozen threshold must be measured once by a
#   new pre-registered run, exactly like every other hypothesis.
# ===================================================================== #


def _rule_sha256(rule: dict[str, Any]) -> str:
    """Fingerprint of a decision rule, so the artefacts can name the one used."""

    import hashlib

    payload = json.dumps(rule, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 6)
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 6)


def _bucket_labels(edges: list[float]) -> list[str]:
    """Bucket keys in ascending order, derived from the declared edges."""

    labels: list[str] = []
    previous: float | None = None
    for edge in edges:
        labels.append(f"<{edge:g}" if previous is None else f"{previous:g}-{edge:g}")
        previous = edge
    labels.append(f">={edges[-1]:g}")
    return labels


def _distance_bucket(edges: list[float], distance: float) -> str:
    """The bucket a distance falls in. Half-open on the upper edge."""

    previous: float | None = None
    for edge in edges:
        if distance < edge:
            return f"<{edge:g}" if previous is None else f"{previous:g}-{edge:g}"
        previous = edge
    return f">={edges[-1]:g}"


ENTRY_TIMING_H2: dict[str, Any] = {
    "id": "ABL-EDGE01-H2",
    "hypothesis": "H2",
    "kind": "diagnostic",
    "question": (
        "gross is negative in DEV, VAL and OOS for the intraday breakout, so the "
        "loss is not only cost: is the entry LATE relative to the level it breaks?"
    ),
    "candidate": "edge_intra_01",
    "split": "intraday",
    "window": "DEV",
    "scenario": "BASE",
    "timeframe": "15m",
    "horizon_minutes": 240.0,
    "bucket_edges_atr": [0.25, 0.5, 1.0],
    "distance_definition": (
        "distance_atr = (entry_mid - level) / atr, where level is the broken "
        "resistance the signal itself names in hard_invalidation, atr is the "
        "signal's own atr_period ATR and entry_mid is the mid the simulator filled "
        "at. 0 means the fill happened at the level; 1 means one ATR above it."
    ),
    "changed_rule": None,
    "changed_rule_note": (
        "none: this experiment answers a question about the frozen rule, it does "
        "not compare two rules. Same candidate, same DEV window, same BASE scenario "
        "and the runtime's own risk budget as the WP run."
    ),
}

#: Frozen BEFORE the diagnostic ran. The rule reads expectancy (net per trade),
#: because the question is economic; the MFE/MAE medians are published as the
#: supporting evidence of whether the excursion exists AFTER the fill or was
#: already spent getting there.
ENTRY_TIMING_H2_DECISION: dict[str, Any] = {
    "min_trades_per_side": 25,
    "meaning": {
        "INCONCLUSIVE": (
            "one side of the split holds fewer than min_trades_per_side trades, so "
            "the DEV sample cannot separate near from far and nothing is claimed"
        ),
        "ENTRY_IS_LATE": (
            "the majority of the fills happen at least one bucket edge past the "
            "level AND the minority that fills closest to the level carries the "
            "better expectancy: the edge is being paid away on the way in, so the "
            "entry rule has to move earlier (limit at or retest of the level), not "
            "the stop and not the cost model"
        ),
        "ENTRY_NOT_THE_PROBLEM": (
            "expectancy does not live on the side that fills closest to the level: "
            "the late fill is not what makes the intraday gross negative, and moving "
            "the entry earlier would not be supported by DEV either"
        ),
    },
    "rule": (
        "near = trades whose distance_atr is below the first declared edge; far = "
        "the rest. Fewer than min_trades_per_side on either side -> INCONCLUSIVE. "
        "ENTRY_IS_LATE when far carries at least as many trades as near AND "
        "near.expectancy_usdt > far.expectancy_usdt. Otherwise "
        "ENTRY_NOT_THE_PROBLEM. Both sides of the comparison are computed from the "
        "published trade rows, so the reading can be recomputed by anyone."
    ),
}


def _join_signal_fills(
    trades: list[dict[str, Any]], signals: list[dict[str, Any]], edges: list[float]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join each executed trade to the signal that printed it (PURE).

    The level is not re-derived from the price series: it is the one the frozen
    candidate wrote into its own signal, which is what makes the distance an
    entry-timing measurement of THAT rule rather than of a new hypothesis.
    """

    by_key = {(s["symbol"], int(s["bar_index"])): s for s in signals}
    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for trade in trades:
        key = (trade["asset"], int(trade["signal_bar"]))
        signal = by_key.get(key)
        if signal is None:
            unmatched.append({"asset": key[0], "signal_bar": key[1], "why": "no signal"})
            continue
        level = signal.get("hard_invalidation")
        atr_value = (signal.get("evidence") or {}).get("atr")
        if level is None or not atr_value:
            unmatched.append(
                {
                    "asset": key[0],
                    "signal_bar": key[1],
                    "why": "signal names no level or no atr",
                }
            )
            continue
        entry_mid = float(trade["entry_mid"])
        distance = (entry_mid - float(level)) / float(atr_value)
        rows.append(
            {
                "asset": trade["asset"],
                "signal_bar": int(trade["signal_bar"]),
                "decision_ts": int(trade["decision_ts"]),
                "entry_ts": int(trade["entry_ts"]),
                "exit_ts": int(trade["exit_ts"]),
                "level": round(float(level), 8),
                "atr": round(float(atr_value), 8),
                "entry_reference": round(float(signal["entry_reference"]), 8),
                "entry_mid": round(entry_mid, 8),
                "entry_fill": round(float(trade["entry_fill"]), 8),
                "distance_atr": round(distance, 6),
                "bucket": _distance_bucket(edges, distance),
                "mfe_bps": round(float(trade["mfe_bps"]), 6),
                "mae_bps": round(float(trade["mae_bps"]), 6),
                "mfe": round(float(trade["mfe"]), 8),
                "mae": round(float(trade["mae"]), 8),
                "notional": round(float(trade["notional"]), 6),
                "gross": round(float(trade["gross"]), 6),
                "fees": round(float(trade["fees"]), 6),
                "price_costs": round(float(trade["price_costs"]), 6),
                "net": round(float(trade["net"]), 6),
                "cost_bps_realised": float(trade["cost_bps_realised"]),
                "duration_min": round(float(trade["duration_min"]), 6),
                "exit_reason": trade["exit_reason"],
                "market_context": trade.get("market_context"),
            }
        )
    return rows, unmatched


def _bucket_stats(rows: list[dict[str, Any]], edges: list[float]) -> dict[str, Any]:
    """Per-bucket aggregates, computed only from the joined rows (PURE)."""

    stats: dict[str, Any] = {}
    for bucket in _bucket_labels(edges):
        subset = [row for row in rows if row["bucket"] == bucket]
        nets = [float(row["net"]) for row in subset]
        contexts: dict[str, Any] = {}
        for label in sorted({str(row.get("market_context") or "UNDEFINED") for row in subset}):
            group = [row for row in subset if str(row.get("market_context") or "UNDEFINED") == label]
            contexts[label] = {
                "trades": len(group),
                "net_usdt": round(sum(float(row["net"]) for row in group), 4),
            }
        stats[bucket] = {
            "trades": len(subset),
            "net_usdt": round(sum(nets), 4),
            "gross_usdt": round(sum(float(row["gross"]) for row in subset), 4),
            "fees_usdt": round(sum(float(row["fees"]) for row in subset), 4),
            "price_costs_usdt": round(sum(float(row["price_costs"]) for row in subset), 4),
            "cost_usdt": round(
                sum(float(row["fees"]) + float(row["price_costs"]) for row in subset), 4
            ),
            "expectancy_usdt": round(sum(nets) / len(subset), 4) if subset else None,
            "win_rate_pct": (
                round(100.0 * sum(1 for net in nets if net > 0) / len(subset), 4)
                if subset
                else None
            ),
            "median_distance_atr": _median([float(row["distance_atr"]) for row in subset]),
            "median_mfe_bps": _median([float(row["mfe_bps"]) for row in subset]),
            "median_mae_bps": _median([float(row["mae_bps"]) for row in subset]),
            "median_duration_min": _median([float(row["duration_min"]) for row in subset]),
            "by_market_context": contexts,
        }
    return stats


def _merge_buckets(buckets: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """One aggregate over the named buckets, so near and far are comparable."""

    subset = [buckets[key] for key in keys]
    trades = sum(int(entry["trades"]) for entry in subset)
    net = sum(float(entry["net_usdt"]) for entry in subset)
    gross = sum(float(entry["gross_usdt"]) for entry in subset)
    return {
        "buckets": list(keys),
        "trades": trades,
        "net_usdt": round(net, 4),
        "gross_usdt": round(gross, 4),
        "expectancy_usdt": round(net / trades, 4) if trades else None,
    }


def entry_timing_verdict(rows: list[dict[str, Any]], buckets: dict[str, Any]) -> dict[str, Any]:
    """Apply H2's pre-registered rule to the published rows. Reads the rule (PURE)."""

    rule = ENTRY_TIMING_H2_DECISION
    labels = _bucket_labels([float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]])
    near_key = labels[0]
    near = _merge_buckets(buckets, [near_key])
    far = _merge_buckets(buckets, labels[1:])
    floor = int(rule["min_trades_per_side"])
    if near["trades"] < floor or far["trades"] < floor:
        code = "INCONCLUSIVE"
    elif far["trades"] >= near["trades"] and float(near["expectancy_usdt"] or 0.0) > float(
        far["expectancy_usdt"] or 0.0
    ):
        code = "ENTRY_IS_LATE"
    else:
        code = "ENTRY_NOT_THE_PROBLEM"
    reason = {
        "INCONCLUSIVE": (
            f"near holds {near['trades']} trades and far {far['trades']}; the sample "
            f"floor is {floor} on each side"
        ),
        "ENTRY_IS_LATE": (
            f"{far['trades']} of {far['trades'] + near['trades']} fills land at or past "
            f"{float(ENTRY_TIMING_H2['bucket_edges_atr'][0]):g} ATR above the broken level "
            f"and their expectancy is {far['expectancy_usdt']} USDT per trade against "
            f"{near['expectancy_usdt']} for the fills closer in"
        ),
        "ENTRY_NOT_THE_PROBLEM": (
            f"fills closer than {float(ENTRY_TIMING_H2['bucket_edges_atr'][0]):g} ATR to the "
            f"level carry {near['expectancy_usdt']} USDT per trade against "
            f"{far['expectancy_usdt']} for the rest: moving the entry earlier is not "
            f"supported by DEV"
        ),
    }[code]
    return {
        "verdict": code,
        "rule": {
            "min_trades_per_side": floor,
        },
        "bucket_edges_atr": [float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]],
        "rule_text": str(rule["rule"]),
        "rule_sha256": _rule_sha256(
            {"min_trades_per_side": floor, "edges": ENTRY_TIMING_H2["bucket_edges_atr"]}
        ),
        "meaning": dict(rule["meaning"]),
        "near": near,
        "far": far,
        "median_distance_atr": _median([float(row["distance_atr"]) for row in rows]),
        "reason": reason,
    }


def run_entry_timing_h2() -> dict[str, Any]:
    """Run H2 on DEV ONLY, under the runtime's own risk budget.

    The budget is the one the WP run used, verbatim: H5 is the experiment that
    answers what the budget does to participation, so this one must not also move
    it or the two mechanism questions would be confounded.
    """

    split_name = str(ENTRY_TIMING_H2["split"])
    window_name = str(ENTRY_TIMING_H2["window"])
    timeframe = str(ENTRY_TIMING_H2["timeframe"])
    candidate_id = str(ENTRY_TIMING_H2["candidate"])
    scenario = str(ENTRY_TIMING_H2["scenario"])
    bounds = SPLITS[split_name][window_name]
    start, end = int(bounds["start"]), int(bounds["end"])
    horizon = float(ENTRY_TIMING_H2["horizon_minutes"])
    corpus = _load_corpus(split_name, timeframe)
    plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon).scaled(scenario)
    regime_rows, regime_meta = _market_context_series()
    policy = load_risk_policy()
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
    for trade in sim.trades:
        trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
    edges = [float(edge) for edge in ENTRY_TIMING_H2["bucket_edges_atr"]]
    rows, unmatched = _join_signal_fills(sim.trades, sim.signals, edges)
    buckets = _bucket_stats(rows, edges)
    verdict = entry_timing_verdict(rows, buckets)
    metrics = _metrics(
        trades=sim.trades,
        equity_curve=sim.equity_curve,
        start_equity=policy.start_equity,
        window_minutes=(end - start) / 60_000.0,
        timeframe=timeframe,
        n_assets=len(ASSETS),
    )
    window_days = max((end - start) / 86_400_000.0, 1e-9)
    arm = {
        "role": "diagnostic",
        "candidate_id": candidate_id,
        "params": dict(candidate.params),
        "bars_evaluated": candidate.bars_evaluated,
        "warmup_bars": candidate.warmup_bars,
        "signal_count": len(sim.signals),
        "joined_trades": len(rows),
        "unmatched_trades": len(unmatched),
        "refusals": _funnel(sim.refusals),
        "_trade_rows": sim.trades,
        "_refusal_rows": sim.refusals,
        "_signal_rows": sim.signals,
        "_joined_rows": rows,
        **metrics,
    }
    return {
        "run_id": "wp-edge-01-entry-timing-h2",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_state(),
        "source_digest": _source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_mechanism_ablation.py",
                "scripts/edge01_mechanism_ablation_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus, DEV window "
            "only; 0 orders, 0 credentials, 0 network calls, no VAL or OOS bar read"
        ),
        "entrypoint": "scripts/edge01_mechanism_ablation.py",
        "verifier": "scripts/edge01_mechanism_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **ENTRY_TIMING_H2,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": round(window_days, 4),
            "assets": list(ASSETS),
            "plane": plane.to_dict(),
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": _sha256(RISK_CONFIG),
            "decision_rule": ENTRY_TIMING_H2_DECISION,
            "corpus_provenance": corpus.provenance,
        },
        "verdict": verdict,
        "arms": {"diagnostic": arm},
        "buckets": buckets,
        "unmatched_trades": unmatched,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "limitations": [
            (
                "the diagnostic reads the trades the RISK BUDGET let through, not "
                "every signal the candidate printed; what the budget removed is the "
                "subject of H5"
            ),
            (
                "two trades may share a (asset, signal_bar) key only if the simulator "
                "can re-enter on the same bar; the artefacts publish the join so the "
                "reader can see whether any were unmatched"
            ),
            (
                "the level is the one the frozen candidate wrote into its own signal: "
                "this measures the timing of THIS rule, not of a re-specified breakout"
            ),
            "single DEV window; no historical order book; long side only (spot)",
        ],
    }


def write_entry_timing_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the H2 diagnostic: the join table, four CSVs, the markdown and the JSON."""

    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    rows = payload["arms"]["diagnostic"]["_joined_rows"]
    by_trade = {(row["asset"], row["signal_bar"]): row for row in rows}
    trade_rows: list[dict[str, Any]] = []
    for trade in payload["arms"]["diagnostic"]["_trade_rows"]:
        joined = by_trade.get((trade["asset"], int(trade["signal_bar"])), {})
        trade_rows.append(
            {
                **trade,
                "run": "diagnostic",
                "candidate": payload["arms"]["diagnostic"]["candidate_id"],
                "strategy": trade.get("candidate"),
                "level": joined.get("level"),
                "atr": joined.get("atr"),
                "distance_atr": joined.get("distance_atr"),
                "distance_bucket": joined.get("bucket"),
            }
        )
    signal_rows: list[dict[str, Any]] = []
    for signal in payload["arms"]["diagnostic"]["_signal_rows"]:
        signal_rows.append(
            {
                "run": "diagnostic",
                "candidate": payload["arms"]["diagnostic"]["candidate_id"],
                "asset": signal.get("symbol"),
                "bar_index": signal.get("bar_index"),
                "decision_ts": signal.get("decision_ts"),
                "regime": signal.get("regime"),
                "entry_reference": signal.get("entry_reference"),
                "stop": signal.get("stop"),
                "hard_invalidation": signal.get("hard_invalidation"),
                "level": signal.get("hard_invalidation"),
                "atr": (signal.get("evidence") or {}).get("atr"),
                "atr_pct": (signal.get("evidence") or {}).get("atr_pct"),
                "risk_reward": signal.get("risk_reward"),
                "expected_gross_bps": signal.get("expected_gross_bps"),
                "expected_cost_bps": signal.get("expected_cost_bps"),
                "expected_net_bps": signal.get("expected_net_bps"),
            }
        )
    refusal_rows: list[dict[str, Any]] = []
    for refusal in payload["arms"]["diagnostic"]["_refusal_rows"]:
        refusal_rows.append(
            {
                "run": "diagnostic",
                "candidate": payload["arms"]["diagnostic"]["candidate_id"],
                "source": refusal.get("source", "candidate"),
                "reason": refusal.get("reason"),
                "symbol": refusal.get("symbol", ""),
                "decision_ts": refusal.get("decision_ts"),
            }
        )

    for name, table in (
        ("ENTRY_TIMING_TRADES.csv", trade_rows),
        ("ENTRY_TIMING_LEVELS.csv", rows),
        ("ENTRY_TIMING_SIGNALS.csv", signal_rows),
        ("ENTRY_TIMING_REFUSALS.csv", refusal_rows),
    ):
        path = outdir / name
        _write_csv(path, table)
        written[name] = path

    context_path = outdir / "MARKET_CONTEXT.csv"
    _write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "ENTRY_TIMING.md"
    md_path.write_text(_entry_timing_markdown(payload), encoding="utf-8")
    written["ENTRY_TIMING.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "experiment": payload["experiment"],
        "market_context": payload["market_context"]["meta"],
        "verdict": payload["verdict"],
        "buckets": payload["buckets"],
        "unmatched_trades": payload["unmatched_trades"],
        "limitations": payload["limitations"],
        "arms": {
            role: _public({k: v for k, v in arm.items() if not k.startswith("_")})
            for role, arm in payload["arms"].items()
        },
        "artifacts": {
            name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every entry-timing artefact except ENTRY_TIMING.json "
            "itself, which is the file carrying them"
        ),
    }
    json_path = outdir / "ENTRY_TIMING.json"
    json_path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written["ENTRY_TIMING.json"] = json_path
    return written


def _entry_timing_markdown(payload: dict[str, Any]) -> str:
    exp = payload["experiment"]
    verdict = payload["verdict"]
    buckets = payload["buckets"]
    labels = _bucket_labels([float(edge) for edge in exp["bucket_edges_atr"]])
    git = _git_state()
    lines = [
        "# ABLACION DE MECANISMO - H2 (timing de entrada)",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{exp['id']}` |",
        f"| pregunta | {exp['question']} |",
        f"| candidato congelado | `{exp['candidate']}` |",
        f"| split / ventana | `{exp['split']}` / `{exp['window']}` |",
        f"| desde / hasta | `{exp['window_start_utc']}` .. `{exp['window_end_utc']}` |",
        f"| dias | {exp['window_days']} |",
        f"| escenario | `{exp['scenario']}` |",
        f"| HEAD al ejecutar | `{git['head_commit']}` |",
        f"| huella del codigo ejecutado (sha256) | `{git['source_sha256']}` |",
        f"| params_hash | `{payload['params_hash']}` |",
        f"| regla congelada (sha256) | `{verdict['rule_sha256']}` |",
        f"| veredicto | **`{verdict['verdict']}`** |",
        "",
        "H2 no cambia ninguna regla: es un diagnostico sobre las operaciones que el",
        "presupuesto de riesgo del runtime dejo pasar. `distance_atr` mide cuanto mas",
        "arriba del nivel roto se ejecuto la entrada, en unidades de ATR del propio",
        "candidato (el nivel es el que la senal nombra en `hard_invalidation`).",
        "",
        f"- `near` (rellenos por debajo de {labels[0]}) frente a `far` (el resto).",
        f"- {verdict['reason']}",
        "",
        "## Rellenos por distancia al nivel",
        "",
        "| bucket (ATR sobre el nivel) | operaciones | neto | bruto | expectativa | win % | MFE mediana (bps) | MAE mediana (bps) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label in labels:
        entry = buckets[label]
        lines.append(
            f"| `{label}` | {_count(entry['trades'])} | {_num(entry['net_usdt'])} | "
            f"{_num(entry['gross_usdt'])} | {_num(entry['expectancy_usdt'])} | "
            f"{_pct(entry['win_rate_pct'])} | {_num(entry['median_mfe_bps'])} | "
            f"{_num(entry['median_mae_bps'])} |"
        )
    lines += [
        "",
        f"- buckets: {', '.join('`' + label + '`' for label in labels)}; la primera "
        "es semiabierta por arriba e incluye cualquier relleno en o por debajo del nivel.",
        f"- distancia mediana de entrada: {_num(verdict['median_distance_atr'])} ATR sobre el nivel.",
        f"- `near`: {_count(verdict['near']['trades'])} operaciones, "
        f"{_num(verdict['near']['expectancy_usdt'])} USDT por operacion.",
        f"- `far`: {_count(verdict['far']['trades'])} operaciones, "
        f"{_num(verdict['far']['expectancy_usdt'])} USDT por operacion.",
        "",
        "## Que significa el veredicto",
        "",
        f"- **`{verdict['verdict']}`** — {verdict['meaning'][verdict['verdict']]}",
        "",
        "## Artefactos de este experimento",
        "",
        "- `ENTRY_TIMING.json` — diagnostico completo, regla congelada y veredicto",
        "- `ENTRY_TIMING_LEVELS.csv` — tabla del join: nivel, ATR y distancia de cada operacion",
        "- `ENTRY_TIMING_TRADES.csv` — operaciones ejecutadas, con su distancia y su bucket",
        "- `ENTRY_TIMING_SIGNALS.csv` — senales del candidato antes de la capa de riesgo",
        "- `ENTRY_TIMING_REFUSALS.csv` — rechazos crudos (origen y motivo)",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion",
        "- verificado por `scripts/edge01_mechanism_ablation_verify.py --experiment h2` en un proceso aparte",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines.append("")
    return "\n".join(lines)


#: H4 — the ENTRY VOLATILITY FILTER, formulated from H4's own text and frozen
#: before the arms ran. The grid is derived from the DEV INPUT distribution, never
#: from a result: it is fixed before any arm is executed, and the rule that picks a
#: threshold is fixed with it.
VOL_FILTER_H4: dict[str, Any] = {
    "id": "ABL-EDGE01-H4",
    "hypothesis": "H4",
    "kind": "ablation",
    "question": (
        "EDGE-TREND-01 has no separate volatility entry filter: volatility only "
        "reaches it through the ATR-scaled stop, so it trades quiet and violent "
        "regimes alike. Does refusing the least volatile breakouts help on DEV?"
    ),
    "candidate": "edge_trend_01",
    "profile": "4h",
    "split": "trend",
    "window": "DEV",
    "scenario": "BASE",
    "timeframe": "4h",
    "horizon_minutes": 1440.0,
    "changed_field": "min_atr_pct",
    "baseline_threshold_pct": None,
    "grid_percentiles": [25.0, 50.0, 75.0],
    "percentile_rule": (
        "nearest rank: index = ceil(pct/100 * n) - 1 over the ascending atr/close "
        "values of every DEV bar with a defined atr_period ATR, all assets pooled"
    ),
    "gate_placement": (
        "the gate is the FIRST entry gate after the breakout: a bar that does not "
        "break the prior extreme is never even counted as a volatility refusal"
    ),
    "changed_rule_note": (
        "every arm is the frozen candidate plus exactly one field, min_atr_pct, set "
        "to a grid value; the baseline arm adds no field at all"
    ),
}

#: Frozen BEFORE any arm ran. Selecting one of four arms on DEV is itself a
#: selection, so the winner is only FROZEN here: it must be measured once on
#: VAL/OOS by a new pre-registered run before it can be promoted.
VOL_FILTER_H4_DECISION: dict[str, Any] = {
    "min_dev_trades": 30,
    "min_improvement_usdt": 0.0,
    "max_single_trade_share_of_net": 0.5,
    "meaning": {
        "INCONCLUSIVE": (
            "the unfiltered baseline itself has fewer than min_dev_trades DEV trades: "
            "the DEV window cannot read a volatility filter on this candidate at all"
        ),
        "FILTER_NOT_JUSTIFIED_ON_DEV": (
            "no threshold beats the baseline on DEV, or the arm that does is carried "
            "by a single trade or is not profitable itself: the filter is NOT added to "
            "the ruleset, because a filter chosen after the outcome is not evidence"
        ),
        "FILTER_FROZEN_FOR_VALIDATION": (
            "one threshold clears the sample floor, improves DEV net by more than "
            "min_improvement_usdt and is not a single trade: it is FROZEN here and "
            "must be measured once on VAL/OOS by a new pre-registered run. This "
            "experiment does not read them and the threshold is not promoted on DEV"
        ),
    },
    "rule": (
        "Among the arms with at least min_dev_trades DEV trades, take the highest DEV "
        "net (ties broken by the LOWEST threshold). INCONCLUSIVE when the baseline "
        "does not clear the floor. FILTER_NOT_JUSTIFIED_ON_DEV when the winner is the "
        "baseline, or its improvement over the baseline is <= min_improvement_usdt, or "
        "its net is not positive, or any single trade carries more than "
        "max_single_trade_share_of_net of it (or of the baseline's net when the "
        "baseline is the winner). Otherwise FILTER_FROZEN_FOR_VALIDATION."
    ),
}


def _atr_pct_sample(
    bars_by_asset: dict[str, list[OHLCVBar]], start: int, end: int, atr_period: int
) -> list[float]:
    """atr/close over every DEV bar, bar by bar, before any arm runs (PURE).

    The sample must cover the whole corpus the arms will trade: a grid read off
    a subset of the assets would silently be a different experiment, so a missing
    asset is an error rather than a smaller sample.
    """

    values: list[float] = []
    for asset in ASSETS:
        bars = bars_by_asset.get(asset)
        if bars is None:
            raise KeyError(f"the ATR sample must cover {asset}, not just {sorted(bars_by_asset)}")
        for index, bar in enumerate(bars):
            if not (start <= bar.ts <= end) or bar.close <= 0:
                continue
            value = atr(bars, index, atr_period)
            if value is None:
                continue
            values.append(round(value / bar.close * 100.0, 6))
    return values


def _nearest_rank_percentile(ascending: list[float], pct: float) -> float:
    """Nearest-rank percentile of an ASCENDING list. Declared, not assumed."""

    if not ascending:
        raise ValueError("no values to take a percentile of")
    rank = math.ceil(pct / 100.0 * len(ascending))
    index = min(max(rank - 1, 0), len(ascending) - 1)
    return float(ascending[index])


def vol_filter_grid(sample: list[float]) -> dict[str, Any]:
    """The declared grid, read off the DEV input distribution (PURE)."""

    ascending = sorted(sample)
    values = {
        f"p{int(pct)}": _nearest_rank_percentile(ascending, float(pct))
        for pct in VOL_FILTER_H4["grid_percentiles"]
    }
    return {
        "percentiles": [float(pct) for pct in VOL_FILTER_H4["grid_percentiles"]],
        "percentile_rule": str(VOL_FILTER_H4["percentile_rule"]),
        "values_pct": values,
        "sample": {
            "bars_with_atr": len(ascending),
            "assets": list(ASSETS),
            "atr_period": int(FROZEN_PARAMS["edge_trend_01"]["atr_period"]),
            "min_atr_pct": ascending[0] if ascending else None,
            "median_atr_pct": _median(ascending),
            "max_atr_pct": ascending[-1] if ascending else None,
        },
    }


def _params_delta(base: dict[str, Any], arm: dict[str, Any]) -> dict[str, list[str]]:
    """Which fields an arm adds, removes or retunes against the baseline (PURE)."""

    return {
        "added": sorted(set(arm) - set(base)),
        "removed": sorted(set(base) - set(arm)),
        "changed": sorted(k for k in set(base) & set(arm) if base[k] != arm[k]),
    }


def vol_filter_verdict(arms: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    """Apply H4's pre-registered rule to the DEV arms. Reads the rule (PURE)."""

    rule = VOL_FILTER_H4_DECISION
    floor = int(rule["min_dev_trades"])
    ceiling = float(rule["max_single_trade_share_of_net"])
    baseline = arms["baseline"]
    eligible = {
        name: arm for name, arm in arms.items() if int(arm.get("trades") or 0) >= floor
    }
    ranking = sorted(
        eligible.items(),
        key=lambda item: (
            -float(item[1].get("net_usdt") or 0.0),
            float(item[1].get("min_atr_pct") or 0.0),
        ),
    )
    declared = {"rule": {key: rule[key] for key in rule if key.startswith(("min_", "max_"))}}
    if "baseline" not in eligible:
        code = "INCONCLUSIVE"
        return {
            "verdict": code,
            **declared,
            "frozen_threshold_pct": None,
            "ranking": [name for name, _ in ranking],
            "meaning": dict(rule["meaning"]),
            "rule_text": str(rule["rule"]),
            "reason": (
                f"the unfiltered baseline prints {baseline.get('trades')} DEV trades, "
                f"under the {floor} the rule requires"
            ),
        }
    winner_name, winner = ranking[0]
    improvement = float(winner.get("net_usdt") or 0.0) - float(baseline.get("net_usdt") or 0.0)
    share = winner.get("largest_trade_share_of_net")
    carried = share is not None and float(share) > ceiling
    not_justified = (
        winner_name == "baseline"
        or improvement <= float(rule["min_improvement_usdt"])
        or float(winner.get("net_usdt") or 0.0) <= 0.0
        or carried
    )
    code = "FILTER_NOT_JUSTIFIED_ON_DEV" if not_justified else "FILTER_FROZEN_FOR_VALIDATION"
    frozen = (
        float(winner.get("min_atr_pct"))
        if code == "FILTER_FROZEN_FOR_VALIDATION" and winner.get("min_atr_pct") is not None
        else None
    )
    if code == "FILTER_NOT_JUSTIFIED_ON_DEV":
        reason = (
            f"the best DEV arm is {winner_name} with {_num(winner.get('net_usdt'))} USDT "
            f"against {_num(baseline.get('net_usdt'))} for the unfiltered baseline "
            f"({_signed(improvement)} USDT); share of the winner's net in its single "
            f"largest trade: {share}"
        )
    elif code == "FILTER_FROZEN_FOR_VALIDATION":
        reason = (
            f"min_atr_pct={float(winner.get('min_atr_pct')):g} prints "
            f"{_count(winner.get('trades'))} DEV trades for {_num(winner.get('net_usdt'))} "
            f"USDT against {_num(baseline.get('net_usdt'))} unfiltered "
            f"({_signed(improvement)} USDT), and no single trade carries more than "
            f"{ceiling:.0%} of it; the threshold is frozen, NOT promoted"
        )
    else:
        reason = "the baseline does not clear the sample floor"
    return {
        "verdict": code,
        **declared,
        "frozen_threshold_pct": frozen,
        "ranking": [name for name, _ in ranking],
        "grid_values_pct": dict(grid["values_pct"]),
        "improvement_usdt": round(improvement, 4),
        "winner": winner_name,
        "winner_single_trade_share_of_net": share,
        "meaning": dict(rule["meaning"]),
        "rule_text": str(rule["rule"]),
        "val_oos_read": False,
        "next_step": (
            "the frozen threshold goes through VAL and then OOS in a NEW "
            "pre-registered run; nothing here is wired into any ruleset"
        ),
        "reason": reason,
    }


def run_vol_filter_h4() -> dict[str, Any]:
    """Run H4 on DEV ONLY: one frozen candidate, four arms, one field apart."""

    split_name = str(VOL_FILTER_H4["split"])
    window_name = str(VOL_FILTER_H4["window"])
    timeframe = str(VOL_FILTER_H4["timeframe"])
    profile = str(VOL_FILTER_H4["profile"])
    scenario = str(VOL_FILTER_H4["scenario"])
    bounds = SPLITS[split_name][window_name]
    start, end = int(bounds["start"]), int(bounds["end"])
    horizon = float(VOL_FILTER_H4["horizon_minutes"])
    corpus = _load_corpus(split_name, timeframe)
    plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon).scaled(scenario)
    regime_rows, regime_meta = _market_context_series()
    policy = load_risk_policy()
    base_params = dict(FROZEN_PARAMS["edge_trend_01"])
    atr_period = int(base_params["atr_period"])
    sample = _atr_pct_sample(corpus.bars_by_asset, start, end, atr_period)
    grid = vol_filter_grid(sample)

    arm_plan: list[tuple[str, float | None]] = [("baseline", None)]
    for name, value in grid["values_pct"].items():
        arm_plan.append((name, float(value)))

    arms: dict[str, Any] = {}
    for name, threshold in arm_plan:
        params = dict(base_params) if threshold is None else {**base_params, "min_atr_pct": threshold}
        candidate = TrendFollow(profile, params)
        sim = run_portfolio_sim(
            candidate=candidate,
            bars_by_asset=corpus.bars_by_asset,
            plane=plane,
            policy=policy,
            context=corpus.context,
            window_start_ts=start,
            window_end_ts=end,
        )
        for trade in sim.trades:
            trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        metrics = _metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=(end - start) / 60_000.0,
            timeframe=timeframe,
            n_assets=len(ASSETS),
        )
        funnel = _funnel(sim.refusals)
        held = sum(
            1 for signal in sim.signals if float((signal.get("evidence") or {}).get("atr_pct") or 0.0)
            < (float(threshold) if threshold is not None else 0.0)
        )
        arms[name] = {
            "role": name,
            "candidate_id": str(candidate.id),
            "min_atr_pct": threshold,
            "params": dict(candidate.params),
            "params_delta": _params_delta(base_params, dict(candidate.params)),
            "bars_evaluated": candidate.bars_evaluated,
            "warmup_bars": candidate.warmup_bars,
            "signal_count": len(sim.signals),
            "vol_refusals": int(funnel.get("candidate:volatility_filter_fail", 0)),
            "signals_below_threshold": held,
            "refusals": funnel,
            "_trade_rows": sim.trades,
            "_refusal_rows": sim.refusals,
            "_signal_rows": sim.signals,
            **metrics,
        }
        trade_count = int(arms[name]["trades"])
        arms[name]["gross_per_trade_usdt"] = (
            round(arms[name]["gross_usdt"] / trade_count, 4) if trade_count else None
        )

    verdict = vol_filter_verdict(arms, grid)
    window_days = max((end - start) / 86_400_000.0, 1e-9)
    return {
        "run_id": "wp-edge-01-volatility-filter-h4",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": _git_state(),
        "source_digest": _source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_mechanism_ablation.py",
                "scripts/edge01_mechanism_ablation_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus, DEV window "
            "only; 0 orders, 0 credentials, 0 network calls, no VAL or OOS bar read"
        ),
        "entrypoint": "scripts/edge01_mechanism_ablation.py",
        "verifier": "scripts/edge01_mechanism_ablation_verify.py",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **VOL_FILTER_H4,
            "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
            "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
            "window_start_ms": start,
            "window_end_ms": end,
            "window_days": round(window_days, 4),
            "assets": list(ASSETS),
            "frozen_params_baseline": base_params,
            "plane": plane.to_dict(),
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": _sha256(RISK_CONFIG),
            "decision_rule": VOL_FILTER_H4_DECISION,
            "corpus_provenance": corpus.provenance,
        },
        "verdict": verdict,
        "arms": arms,
        "grid": grid,
        "_atr_sample": sample,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "limitations": [
            (
                "picking one of four arms on DEV is itself a selection: the winner is "
                "frozen, not promoted, and its VAL/OOS behaviour is unknown"
            ),
            (
                "the grid comes from the DEV input distribution of atr/close, so a "
                "different window would place the thresholds elsewhere; the rule and "
                "the percentile definition are published so the placement is auditable"
            ),
            (
                "the gate refuses entries only (it does not size down and does not "
                "change the exit): it cannot rescue a position it would not have opened"
            ),
            (
                "removing less volatile breakouts removes a population, not a "
                "per-trade outcome; the arms are different equity trajectories, so the "
                "comparison is between two books, not two versions of one trade"
            ),
            "single DEV window; no historical order book; long side only (spot)",
        ],
    }


def write_vol_filter_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the H4 experiment: the ATR sample, four CSVs, the markdown and the JSON."""

    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trade_rows: list[dict[str, Any]] = []
    refusal_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    for name, arm in payload["arms"].items():
        for trade in arm["_trade_rows"]:
            trade_rows.append(
                {
                    **trade,
                    "run": name,
                    "candidate": arm["candidate_id"],
                    "strategy": trade.get("candidate"),
                    "min_atr_pct": arm["min_atr_pct"],
                }
            )
        for refusal in arm["_refusal_rows"]:
            detail = refusal.get("detail") or {}
            refusal_rows.append(
                {
                    "run": name,
                    "candidate": arm["candidate_id"],
                    "source": refusal.get("source", "candidate"),
                    "reason": refusal.get("reason"),
                    "symbol": refusal.get("symbol", ""),
                    "bar_index": refusal.get("bar_index"),
                    "decision_ts": refusal.get("decision_ts"),
                    "atr_pct": detail.get("atr_pct"),
                    "min_atr_pct": detail.get("min_atr_pct"),
                }
            )
        for signal in arm["_signal_rows"]:
            evidence = signal.get("evidence") or {}
            signal_rows.append(
                {
                    "run": name,
                    "candidate": arm["candidate_id"],
                    "min_atr_pct": arm["min_atr_pct"],
                    "asset": signal.get("symbol"),
                    "bar_index": signal.get("bar_index"),
                    "decision_ts": signal.get("decision_ts"),
                    "regime": signal.get("regime"),
                    "atr": evidence.get("atr"),
                    "atr_pct": evidence.get("atr_pct"),
                    "breakout_level": evidence.get("breakout_level"),
                    "entry_reference": signal.get("entry_reference"),
                    "stop": signal.get("stop"),
                    "risk_reward": signal.get("risk_reward"),
                    "expected_gross_bps": signal.get("expected_gross_bps"),
                    "expected_cost_bps": signal.get("expected_cost_bps"),
                    "expected_net_bps": signal.get("expected_net_bps"),
                }
            )

    for name, table in (
        ("VOL_FILTER_TRADES.csv", trade_rows),
        ("VOL_FILTER_REFUSALS.csv", refusal_rows),
        ("VOL_FILTER_SIGNALS.csv", signal_rows),
    ):
        path = outdir / name
        _write_csv(path, table)
        written[name] = path

    sample = sorted(float(value) for value in payload["_atr_sample"])
    atr_path = outdir / "VOL_FILTER_ATR.csv"
    _write_csv(
        atr_path,
        [
            {"atr_pct": value, "rank": index + 1, "of": len(sample)}
            for index, value in enumerate(sample)
        ],
    )
    written["VOL_FILTER_ATR.csv"] = atr_path

    context_path = outdir / "MARKET_CONTEXT.csv"
    _write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "VOL_FILTER.md"
    md_path.write_text(_vol_filter_markdown(payload), encoding="utf-8")
    written["VOL_FILTER.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "experiment": payload["experiment"],
        "market_context": payload["market_context"]["meta"],
        "grid": payload["grid"],
        "verdict": payload["verdict"],
        "limitations": payload["limitations"],
        "arms": {
            role: _public({k: v for k, v in arm.items() if not k.startswith("_")})
            for role, arm in payload["arms"].items()
        },
        "artifacts": {
            name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every volatility-filter artefact except VOL_FILTER.json "
            "itself, which is the file carrying them"
        ),
    }
    json_path = outdir / "VOL_FILTER.json"
    json_path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written["VOL_FILTER.json"] = json_path
    return written


def _vol_filter_markdown(payload: dict[str, Any]) -> str:
    exp = payload["experiment"]
    verdict = payload["verdict"]
    grid = payload["grid"]
    arms = payload["arms"]
    git = _git_state()
    lines = [
        "# ABLACION DE MECANISMO - H4 (filtro de volatilidad de entrada)",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{exp['id']}` |",
        f"| pregunta | {exp['question']} |",
        f"| candidato congelado | `{exp['candidate']}` ({exp['profile']}) |",
        f"| campo cambiado | `{exp['changed_field']}` |",
        f"| split / ventana | `{exp['split']}` / `{exp['window']}` |",
        f"| desde / hasta | `{exp['window_start_utc']}` .. `{exp['window_end_utc']}` |",
        f"| dias | {exp['window_days']} |",
        f"| escenario | `{exp['scenario']}` |",
        f"| HEAD al ejecutar | `{git['head_commit']}` |",
        f"| huella del codigo ejecutado (sha256) | `{git['source_sha256']}` |",
        f"| params_hash (candidato congelado) | `{payload['params_hash']}` |",
        f"| veredicto | **`{verdict['verdict']}`** |",
        "",
        "Las cuatro ramas son el MISMO candidato congelado; la baseline no anade",
        "ningun campo y cada rama de umbral anade exactamente uno,",
        "`min_atr_pct` (ATR/close en porcentaje). La rejilla no se elige mirando",
        "resultados: son los percentiles declarados de la distribucion de ATR/close de",
        "las barras de DEV.",
        "",
        "## Rejilla de umbrales",
        "",
        f"Percentiles de atr/close en DEV — {grid['percentile_rule']}.",
        "",
        "| rama | umbral min_atr_pct |",
        "|---|---|",
        "| `baseline` | sin filtro |",
    ]
    for name, value in grid["values_pct"].items():
        lines.append(f"| `{name}` | {float(value):.4f} |")
    lines += [
        "",
        f"- muestra: {_count(grid['sample']['bars_with_atr'])} barras de DEV con ATR definido; "
        f"minimo {grid['sample']['min_atr_pct']:.4f}, mediana "
        f"{grid['sample']['median_atr_pct']:.4f}, maximo {grid['sample']['max_atr_pct']:.4f}",
        "",
        "## Resultado en DEV",
        "",
        "| rama | min_atr_pct | operaciones | bruto | bruto/op | coste | neto | expectativa | drawdown % | rechazos por volatilidad |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in arms.items():
        threshold = arm["min_atr_pct"]
        lines.append(
            f"| `{name}` | {'sin filtro' if threshold is None else f'{float(threshold):.4f}'} | "
            f"{_count(arm['trades'])} | {_num(arm['gross_usdt'])} | "
            f"{_num(arm['gross_per_trade_usdt'])} | "
            f"{_num(float(arm['fees_usdt']) + float(arm['price_costs_usdt']))} | "
            f"{_num(arm['net_usdt'])} | {_num(arm['expectancy_usdt'])} | "
            f"{_pct(arm['max_drawdown_pct'])} | {_count(arm['vol_refusals'])} |"
        )
    lines += [
        "",
        f"- ranking por neto de DEV (solo ramas con al menos "
        f"{verdict['rule']['min_dev_trades']} operaciones): "
        + ", ".join(f"`{name}`" for name in verdict["ranking"]),
        f"- veredicto: **`{verdict['verdict']}`** — {verdict['reason']}",
        "- umbral congelado: "
        + (
            f"`{float(verdict['frozen_threshold_pct']):.4f}`"
            if verdict["frozen_threshold_pct"] is not None
            else "ninguno"
        ),
        f"- VAL/OOS leidos: **{verdict['val_oos_read']}** — {verdict['next_step']}",
        "",
        "## Que significa el veredicto",
        "",
        f"- **`{verdict['verdict']}`** — {verdict['meaning'][verdict['verdict']]}",
        "",
        "## Artefactos de este experimento",
        "",
        "- `VOL_FILTER.json` — comparacion completa, rejilla, regla congelada y veredicto",
        "- `VOL_FILTER_TRADES.csv` — operaciones de las cuatro ramas",
        "- `VOL_FILTER_REFUSALS.csv` — rechazos crudos, con el atr_pct que los provoco",
        "- `VOL_FILTER_SIGNALS.csv` — senales de cada rama, con su atr_pct",
        "- `VOL_FILTER_ATR.csv` — la muestra de atr/close de DEV con la que se situa la rejilla",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion",
        "- verificado por `scripts/edge01_mechanism_ablation_verify.py --experiment h4` en un proceso aparte",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines.append("")
    return "\n".join(lines)

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

    context_path = outdir / "MARKET_CONTEXT.csv"
    _write_csv(context_path, campaign["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

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
                "market_context": campaign["market_context"]["meta"],
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


def _normalised(raw: bytes) -> bytes:
    """Line endings stripped before hashing, so the digest identifies the CODE.

    This checkout has ``core.autocrlf`` set, so the same committed content lands
    on disk as LF or CRLF depending on how it arrived: the working tree, the
    stored blob and a fresh checkout of the same commit produced three different
    digests for byte-identical code (DEF-EDGE01-09). Normalising makes the
    recorded provenance reproducible from a clean checkout instead of tying it
    to one machine's checkout state.
    """
    return raw.replace(b"\r\n", b"\n")


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
        source.update(_normalised(path.read_bytes()))
    for script in (REPO / "scripts" / "edge01_run.py", REPO / "scripts" / "edge01_verify.py"):
        if script.exists():
            source.update(script.name.encode())
            source.update(_normalised(script.read_bytes()))
    try:
        state: dict[str, Any] = {
            "head_commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_dirty": bool(_git("status", "--porcelain")),
        }
    except Exception:  # pragma: no cover - a tree without git is reported, not guessed
        state = {"head_commit": "UNKNOWN", "branch": "UNKNOWN", "worktree_dirty": None}
    state["source_sha256"] = source.hexdigest()
    state["source_digest_rule"] = (
        "sha256 over name+bytes of src/trading_bot/research/edge01/*.py, "
        "scripts/edge01_run.py and scripts/edge01_verify.py, with CRLF folded to LF "
        "so the digest does not depend on the checkout's line endings"
    )
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
            "evaluated": {
                "assets": list(payload["scope"]["assets"]),
                "side": "LONG only (spot)",
                "timeframe": payload["scope"]["timeframe"],
                "split_family": payload["scope"]["split"],
                "windows": {
                    name: {
                        "start_utc": bounds["start_utc"],
                        "end_utc": bounds["end_utc"],
                    }
                    for name, bounds in (
                        campaign["splits"].get(str(payload["scope"]["split"]), {}) or {}
                    ).items()
                },
                "cost_scenarios": list(campaign["cost_scenarios"]),
            },
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


def _count(value: Any) -> str:
    """Counts are counts: 290 trades, not 290.00 trades."""
    if value is None:
        return "n/a"
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def _signed(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{int(value):+,}" if float(value).is_integer() else f"{value:+,.2f}"


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
        scope = payload["scope"]
        windows = campaign["splits"].get(str(scope["split"]), {})
        period = "; ".join(
            f"{name} {bounds['start_utc'][:10]}..{bounds['end_utc'][:10]}"
            for name, bounds in windows.items()
        )
        measured = {}
        for split_scenarios in payload["splits"].values():
            for data in split_scenarios.values():
                measured["trades"] = measured.get("trades", 0) + int(data["trades"])
        lines += [
            f"### {candidate_id} ({scope['timeframe']})",
            "",
            f"- evaluated assets: {', '.join(scope['assets'])} (spot, long only)",
            f"- evaluated period: {period or 'n/a'}",
            f"- evaluated combinations: {len(windows)} splits x "
            f"{len(campaign['cost_scenarios'])} cost scenarios = "
            f"{measured.get('trades', 0)} measured trade instances (the same rule set "
            f"re-priced per scenario, not extra evidence)",
            "",
            "Costs are split the way the model charges them: the fee is the "
            "contractual component and the price cost is spread + slippage + impact, "
            "charged half on each leg. `cost_bps_realised` per trade reconciles with "
            "the plane printed here (the verifier re-checks it fill by fill).",
            "",
            "| split | scenario | trades | gross | fees | price costs | fee bps | "
            "spread bps | slip bps | impact bps | net | win rate | profit factor | "
            "expectancy | max DD | Sharpe | exposure |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for split in ("DEV", "VAL", "OOS"):
            for scenario in campaign["cost_scenarios"]:
                data = payload["splits"][split][scenario]
                plane = data.get("plane") or {}
                lines.append(
                    f"| {split} | {scenario} | {data['trades']} | {_num(data['gross_usdt'])} | "
                    f"{_num(data['fees_usdt'])} | {_num(data['price_costs_usdt'])} | "
                    f"{_num(plane.get('fee_bps'))} | {_num(plane.get('spread_bps'))} | "
                    f"{_num(plane.get('slippage_bps'))} | {_num(plane.get('impact_bps'))} | "
                    f"{_num(data['net_usdt'])} | {_pct(data['win_rate_pct'])} | "
                    f"{_num(data['profit_factor'])} | {_num(data['expectancy_usdt'])} | "
                    f"{_pct(data['max_drawdown_pct'])} | {_num(data['sharpe_annualised'])} | "
                    f"{_pct(data['exposure_pct_of_time'])} |"
                )
        lines += ["", "Exit reasons (OOS/BASE): " + _exit_mix(payload), ""]
        lines += ["Refusals (OOS/BASE, top): " + _refusal_mix(payload), ""]
        lines += ["Buy & hold over the same OOS window: " + _buy_hold(payload), ""]
        meta = campaign["market_context"]["meta"]
        lines += [
            f"Market context at ENTRY (BASE scenario), from the benchmark only "
            f"(`{meta['benchmark']}`, daily, as-of each decision, rule in "
            f"`RUN_REPORT.json#market_context`). This is what the market was doing, "
            f"independently of the candidate; `UNDEFINED` means the benchmark could "
            f"not be read yet (no day closed, or the label falls after "
            f"{_iso(meta['last_close_ms'])}).",
            "",
            "| split | market context | trades | net | win rate |",
            "|---|---|---|---|---|",
        ]
        for split in ("DEV", "VAL", "OOS"):
            context = payload["splits"][split]["BASE"].get("by_market_context") or {}
            if not context:
                lines.append(f"| {split} | (no trades) | 0 | n/a | n/a |")
            for label in sorted(context):
                bucket = context[label]
                lines.append(
                    f"| {split} | {label} | {bucket['trades']} | {_num(bucket['net'])} | "
                    f"{_pct(bucket['win_rate'])} |"
                )
        lines += [
            "",
            "Entry trend state of the candidate's own filter (the `regime` column of "
            "TRADES.csv, which is NOT a market regime): "
            + json.dumps(payload["splits"]["OOS"]["BASE"].get("by_regime") or {}),
            "",
        ]
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
        "- `market_context` is the benchmark (BTC) regime at the entry instant, read "
        "as-of and never later; it is independent of every candidate. The `regime` "
        "column instead records the entry trend state of the candidate's own "
        "filter, so a filtered candidate reports a single value there by "
        "construction — which is why the market coverage question is answered by "
        "`market_context` and not by that column.",
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
        "## 7. Contexto de mercado al entrar (benchmark)",
        "",
        "La pregunta del WP es si los candidatos se probaron en mercado alcista,\n"
        "bajista y lateral. La respuesta no puede venir de la columna `regime` de\n"
        "`TRADES.csv`: esa columna es el estado del FILTRO DE TENDENCIA del propio\n"
        "candidato en el momento de entrar (es el valor que dej\u00f3 pasar la operaci\u00f3n), y\n"
        "un candidato que s\u00f3lo entra en tendencia alcista s\u00f3lo puede escribir un\n"
        "valor. Por eso cada operaci\u00f3n lleva adem\u00e1s `market_context`, calculado\n"
        "sobre el benchmark y le\u00eddo *as-of* el instante de la decisi\u00f3n:\n"
        "",
        f"- benchmark: `{campaign['market_context']['meta']['benchmark']}`, diario "
        f"({campaign['market_context']['meta']['timeframe']})",
        f"- regla: {campaign['market_context']['meta']['rule']}",
        f"- d\u00edas etiquetados: {campaign['market_context']['meta']['days']} "
        f"({_iso(campaign['market_context']['meta']['first_close_ms'])}.."
        f"{_iso(campaign['market_context']['meta']['last_close_ms'])}); "
        f"reparto: `{json.dumps(campaign['market_context']['meta']['label_days'])}`",
        "- fichero: `MARKET_CONTEXT.csv` (una fila por d\u00eda, con su sha256 en "
        "`RUN_REPORT.json`); el verificador comprueba que cada `market_context` "
        "de `TRADES.csv` es el \u00faltimo d\u00eda cerrado antes de su `decision_ts`.",
        "",
        "Operaciones por contexto de mercado (BASE):",
        "",
        "| candidato | split | BULL | BEAR | SIDEWAYS | UNDEFINED |",
        "|---|---|---|---|---|---|",
    ]
    for candidate_id, payload in campaign["candidates"].items():
        for split in ("DEV", "VAL", "OOS"):
            context = payload["splits"][split]["BASE"].get("by_market_context") or {}
            cells = [str((context.get(label) or {}).get("trades", 0)) for label in
                     ("BULL", "BEAR", "SIDEWAYS", "UNDEFINED")]
            lines.append(f"| {candidate_id} | {split} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "`UNDEFINED` no es un rango: significa que el benchmark no pod\u00eda leerse "
        "(a\u00fan no hab\u00eda cerrado ning\u00fan d\u00eda, o la fecha cae despu\u00e9s del final del "
        "corpus de 1h). Se cuenta en su propia columna en vez de repartirse entre "
        "las etiquetas vecinas.",
        "",
        "## 8. Defectos encontrados al ejecutar (y corregidos aqu\u00ed)",
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
        "## 9. Verificaci\u00f3n",
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
        "  `tests/unit/research/test_edge01_gate_and_artifacts.py`.\n"
        "- El verificador comprueba adem\u00e1s, desde los artefactos solos, que el\n"
        "  `market_context` de cada operaci\u00f3n es el del \u00faltimo d\u00eda del benchmark\n"
        "  cerrado antes de su decisi\u00f3n (`MARKET_CONTEXT_ATTRIBUTION`).",
        "- Cada artefacto lleva su sha256 y su tama\u00f1o en `RUN_REPORT.json`.\n"
        "  El backtester no comparte c\u00f3digo de decisi\u00f3n con el runtime.",
        "- `INDEPENDENT_VERIFICATION.json` lo produce el verificador DESPU\u00c9S de esta "
        "medida, as\u00ed que no est\u00e1 en el inventario de integridad de arriba: es el "
        "resultado de comprobar el resto, no una medida m\u00e1s.",
        "- `TEST_TARGET == RUNTIME_TARGET`: "
        + str(_runtime_diff() or "el WP no ha tocado ning\u00fan fichero del runtime")
        + ". Los tests y el runner importan el mismo paquete "
        "(`trading_bot.research.edge01`) y el verificador no importa nada del proyecto.",
        "",
        "## 10. PAPER",
        "",
        f"- Integrado: `{PAPER_STATUS['integrated']}` \u2014 {PAPER_STATUS['reason']}",
        f"- Runtime: {PAPER_STATUS['runtime_untouched']}",
        "- No se activa dinero real: 0 \u00f3rdenes en este WP.",
        "",
        "## 11. Hip\u00f3tesis para la siguiente iteraci\u00f3n",
        "",
    ]
    for item in NEXT_HYPOTHESES:
        lines.append(f"- **{item['id']}**: {item['hypothesis']} \u2014 *Test:* {item['test']}")
    lines += [
        "",
        "## 12. Limitaciones",
        "",
    ]
    lines += [f"- {item}" for item in LIMITATIONS]
    lines += [
        "",
        "## 13. Artefactos",
        "",
        "| artefacto | contenido |",
        "|---|---|",
        "| `STRATEGY_RESULTS.md` | veredictos y m\u00e9tricas por candidato, split y escenario |",
        "| `STRATEGY_RESULTS.json` | lo mismo en JSON, m\u00e1s scope, params congelados y procedencia |",
        "| `TRADES.csv` | una fila por operaci\u00f3n cerrada, con costes desglosados y R m\u00faltiple |",
        "| `EQUITY_CURVE.csv` | curva de capital por candidato y split (escenario BASE) |",
        "| `MARKET_CONTEXT.csv` | r\u00e9gimen del benchmark por d\u00eda, con la regla declarada; base del `market_context` de cada operaci\u00f3n |",
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
