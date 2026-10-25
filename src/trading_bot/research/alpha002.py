"""ALPHA-002 — the preregistered hypothesis registry for the derivatives campaign.

ALPHA-001 tested twelve OHLCV-derived hypotheses and closed
``ALPHA_ECONOMICALLY_TOO_SMALL`` with the binding constraint measured to be the
effect size rather than the cost.  ALPHA-002 therefore does not re-tune price
signals; it asks whether **information about market participants** — open
interest, aggressor-side flow, funding and published positioning — carries an
effect that price alone did not.

What this module is: the frozen half of the campaign.  Three hypotheses, one per
economic mechanism, each expressed as a mechanical rule over a declared feature
row so that no interpretation happens after the results are seen.  Thresholds are
chosen from market-structure reasoning (round, economically meaningful levels),
never from a search.

What this module is not: no data access, no strategy, no order path.  The builder
lives in ``scripts/`` and the statistics are ALPHA-001's, unchanged.

Discipline it enforces:

* **One campaign, three mechanisms.**  Not one hundred indicator combinations.
* **The rule is the hash.**  ``preregistration_hash`` covers the declarative
  registry; the executable signals are separately asserted to implement it, so a
  silent divergence between text and code is a test failure rather than a finding.
* **Non-traded arms are declared, not discovered.**  The short-covering and
  exhaustion branches are stated here as comparators that are reported but never
  traded, so they cannot be promoted after the fact.
* **The cost model is inherited.**  ``COST_BPS_V3`` is imported from
  ``alpha001`` — one number, one source, no second opinion.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from trading_bot.research.alpha001 import COST_BPS_V3

__all__ = [
    "COST_BPS_V3",
    "ENTRY_TIMEFRAMES",
    "FEATURES",
    "FORWARD_BARS",
    "HYPOTHESES",
    "NON_TRADED_ARMS",
    "PREREGISTRATION",
    "REGIME_TIMEFRAME",
    "SIGNALS",
    "THRESHOLDS",
    "UNIVERSE",
    "h1_breakout_confirmation",
    "h1_short_covering_arm",
    "h2_crowded_reversal",
    "h3_exhaustion_arm",
    "h3_flow_continuation",
    "preregistration_hash",
]

#: Same four assets as the capture job.  Small on purpose: a new information source
#: is validated narrowly before it is widened.
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

#: Primary entry timeframe, with 15m kept as the declared replication.
ENTRY_TIMEFRAMES = ("5m", "15m")

#: The regime filter runs on a slower clock than the entry.
REGIME_TIMEFRAME = "1h"

#: Forward horizon in entry bars.  One bar, so overlapping-sample effects stay
#: negligible and the effective sample size is close to the raw count.
FORWARD_BARS = 1

#: The feature row every signal is allowed to read.  Each entry is computed causally
#: from data available at the decision instant; percentiles use a trailing window
#: only.  Anything not listed here may not be used by a hypothesis.
FEATURES: tuple[dict[str, str], ...] = (
    {"name": "ret_z", "definition": "bar return divided by ATR over the same bar"},
    {"name": "atr_pct", "definition": "ATR divided by price, the local volatility level"},
    {"name": "oi_chg", "definition": "per-bar proportional change in open interest"},
    {"name": "oi_accel", "definition": "per-bar change in oi_chg, i.e. the second difference"},
    {
        "name": "taker_imbalance",
        "definition": "(takerBuyVolume - takerSellVolume) / (takerBuyVolume + takerSellVolume)",
    },
    {"name": "funding", "definition": "most recent settled funding rate, as a decimal"},
    {
        "name": "ls_global_pctile",
        "definition": "trailing percentile of the global long/short account ratio",
    },
    {
        "name": "ls_top_position_pctile",
        "definition": "trailing percentile of the top-trader position long/short ratio",
    },
    {
        "name": "momentum_delta",
        "definition": "change in short-horizon price momentum, the deterioration term",
    },
    {"name": "vol_regime", "definition": "1h volatility regime: +1 expanding, -1 contracting"},
)

#: Frozen thresholds.  Round, economically meaningful levels — not fitted values.
#: ``ret_z`` of 1.0 is a one-ATR bar; a 5% volume imbalance is a visible aggressor
#: skew; 3 bps per funding interval is a stretched carry; the 90th percentile is the
#: conventional crowding cut.
THRESHOLDS: dict[str, float] = {
    "breakout_ret_z": 1.0,
    "oi_expanding": 0.0,
    "taker_imbalance_confirm": 0.05,
    "funding_extreme_abs": 0.0003,
    "funding_elevated": 0.0001,
    "crowding_pctile": 0.90,
    "momentum_deteriorating": 0.0,
}

#: The declarative registry.  ``preregistration_hash`` covers exactly this object,
#: so any change to a rule, a threshold, a timeframe or the universe changes the
#: hash and invalidates the campaign.
PREREGISTRATION: dict[str, Any] = {
    "campaign": "ALPHA-002",
    "title": "Derivatives Positioning & Order-Flow Alpha",
    "question": (
        "Does adding information about market participants produce an out-of-sample effect "
        "large enough to clear the economic hurdle?"
    ),
    "parent": {
        "campaign": "ALPHA-001",
        "verdict": "ALPHA_ECONOMICALLY_TOO_SMALL",
        "binding_constraint": "EFFECT_SIZE_NOT_COST",
        "not_reopened": "no OHLCV hypothesis, threshold or horizon from ALPHA-001 is re-tested",
    },
    "universe": list(UNIVERSE),
    "entry_timeframes": list(ENTRY_TIMEFRAMES),
    "regime_timeframe": REGIME_TIMEFRAME,
    "forward_bars": FORWARD_BARS,
    "features": [dict(item) for item in FEATURES],
    "thresholds": dict(THRESHOLDS),
    "cost_model": {
        "name": "COST_MODEL_V3",
        "cost_bps": COST_BPS_V3,
        "inherited_from": "trading_bot.research.alpha001.COST_BPS_V3",
        "retuned": False,
    },
    "statistical_gate": {
        "inherited_from": "ALPHA-001",
        "admission_rule": (
            "gross mean per trade must clear cost + 25% execution uncertainty + the RFC-023 "
            "winner's-curse buffer + z_{0.975} * sigma / sqrt(n_effective), with every term "
            "frozen before any result is observed"
        ),
        "multiplicity": "Benjamini-Hochberg at q = 0.10 and Holm at alpha = 0.10",
        "selection_null": "best-of-3 permutation null, 1000 draws",
        "concentration_gate": "top-1 trade share > 0.25 or net excluding the best trade < 0 is FRAGILE",
        "stability_gate": "gross mean must keep its sign across four sub-windows",
        "underpowered_is_not_negative": True,
    },
    "hypotheses": (
        {
            "hypothesis_id": "A2-H01",
            "family_id": "G1_POSITIONING_CONFIRMATION",
            "name": "BREAKOUT_CONFIRMATION",
            "mechanism": (
                "a breakout accompanied by rising open interest is new positioning rather than "
                "short covering, and aggressive buyers confirm it, so the move continues"
            ),
            "direction_rule": (
                "LONG when ret_z > breakout_ret_z and oi_chg > oi_expanding and "
                "taker_imbalance > taker_imbalance_confirm and |funding| <= funding_extreme_abs"
            ),
            "expected_regime": "volatility expanding (vol_regime = +1)",
            "invalidation": (
                "no forward continuation on average, or the effect is carried by one trade, or "
                "the sign does not survive the four sub-windows"
            ),
            "timeframes": ["5m", "15m"],
            "regime_timeframe": REGIME_TIMEFRAME,
            "traded": True,
        },
        {
            "hypothesis_id": "A2-H02",
            "family_id": "G2_CROWDED_REVERSAL",
            "name": "CROWDED_POSITION_REVERSAL",
            "mechanism": (
                "when published positioning is crowded long and the carry is stretched, the "
                "marginal buyer is already in and the move mean-reverts when momentum fades"
            ),
            "direction_rule": (
                "SHORT when max(ls_global_pctile, ls_top_position_pctile) >= crowding_pctile and "
                "funding > funding_elevated and momentum_delta < momentum_deteriorating"
            ),
            "expected_regime": "any; crowding is the conditioning variable",
            "invalidation": (
                "positioning normalises without a reversal, or the reversal is symmetric (the "
                "mirror long arm is not tested, so a symmetric result is not an edge)"
            ),
            "timeframes": ["5m", "15m"],
            "regime_timeframe": REGIME_TIMEFRAME,
            "traded": True,
        },
        {
            "hypothesis_id": "A2-H03",
            "family_id": "G3_FLOW_CONTINUATION",
            "name": "FLOW_CONTINUATION_VS_EXHAUSTION",
            "mechanism": (
                "a strong move with expanding open interest and aligned aggressor flow is new "
                "risk being taken, while the same move with collapsing open interest is "
                "positions being closed and carries no continuation"
            ),
            "direction_rule": (
                "LONG if ret_z > breakout_ret_z, SHORT if ret_z < -breakout_ret_z, in both cases "
                "only when oi_chg > oi_expanding and taker_imbalance aligns with the sign of ret_z "
                "by more than taker_imbalance_confirm"
            ),
            "expected_regime": "any; open-interest expansion is the conditioning variable",
            "invalidation": (
                "the expansion subset does not out-return the collapse subset, or the effect is "
                "driven by a single directional episode"
            ),
            "timeframes": ["5m", "15m"],
            "regime_timeframe": REGIME_TIMEFRAME,
            "traded": True,
        },
    ),
    "non_traded_arms": (
        {
            "arm_id": "A2-NT-01",
            "hypothesis_id": "A2-H01",
            "name": "SHORT_COVERING_CONTRAST",
            "rule": "ret_z > breakout_ret_z and oi_chg < oi_expanding",
            "role": (
                "the declared comparator for H1: it is reported as a differential and may never "
                "be promoted into a traded hypothesis"
            ),
        },
        {
            "arm_id": "A2-NT-02",
            "hypothesis_id": "A2-H03",
            "name": "EXHAUSTION_CONTRAST",
            "rule": "|ret_z| > breakout_ret_z and oi_chg < oi_expanding",
            "role": (
                "the declared comparator for H3: declared NO_TRADE, reported as a differential "
                "and never promoted"
            ),
        },
    ),
    "prohibitions": (
        "no parameter search",
        "no threshold tuning after results are seen",
        "no adding or removing a hypothesis after results are seen",
        "no re-use of the ALPHA-001 holdout for an ALPHA-001 question",
        "no change to COST_MODEL_V3",
    ),
}


def preregistration_hash(preregistration: Mapping[str, Any] | None = None) -> str:
    """SHA-256 over the canonical form of the declarative registry."""
    payload = dict(preregistration if preregistration is not None else PREREGISTRATION)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# executable signals — asserted (in tests) to implement the rules above
# --------------------------------------------------------------------------- #


def h1_breakout_confirmation(row: Mapping[str, float]) -> int:
    """A2-H01: continuation LONG on a flow-confirmed, carry-neutral breakout."""
    if row["ret_z"] <= THRESHOLDS["breakout_ret_z"]:
        return 0
    if row["oi_chg"] <= THRESHOLDS["oi_expanding"]:
        return 0
    if row["taker_imbalance"] <= THRESHOLDS["taker_imbalance_confirm"]:
        return 0
    if abs(row["funding"]) > THRESHOLDS["funding_extreme_abs"]:
        return 0
    return 1


def h1_short_covering_arm(row: Mapping[str, float]) -> bool:
    """A2-NT-01: the declared, non-traded short-covering comparator."""
    return (
        row["ret_z"] > THRESHOLDS["breakout_ret_z"] and row["oi_chg"] < THRESHOLDS["oi_expanding"]
    )


def h2_crowded_reversal(row: Mapping[str, float]) -> int:
    """A2-H02: mean-reversion SHORT against crowded long positioning."""
    crowding = max(row["ls_global_pctile"], row["ls_top_position_pctile"])
    if crowding < THRESHOLDS["crowding_pctile"]:
        return 0
    if row["funding"] <= THRESHOLDS["funding_elevated"]:
        return 0
    if row["momentum_delta"] >= THRESHOLDS["momentum_deteriorating"]:
        return 0
    return -1


def h3_flow_continuation(row: Mapping[str, float]) -> int:
    """A2-H03: trade a strong move in its own direction, but only on OI expansion."""
    if abs(row["ret_z"]) <= THRESHOLDS["breakout_ret_z"]:
        return 0
    if row["oi_chg"] <= THRESHOLDS["oi_expanding"]:
        return 0
    direction = 1 if row["ret_z"] > 0 else -1
    if direction * row["taker_imbalance"] <= THRESHOLDS["taker_imbalance_confirm"]:
        return 0
    return direction


def h3_exhaustion_arm(row: Mapping[str, float]) -> bool:
    """A2-NT-02: the declared NO_TRADE arm — a strong move on collapsing OI."""
    return (
        abs(row["ret_z"]) > THRESHOLDS["breakout_ret_z"]
        and row["oi_chg"] < THRESHOLDS["oi_expanding"]
    )


#: Every declared traded hypothesis must appear here, and nothing else may.  A test
#: enforces the correspondence in both directions.
SIGNALS: dict[str, Callable[[Mapping[str, float]], int]] = {
    "A2-H01": h1_breakout_confirmation,
    "A2-H02": h2_crowded_reversal,
    "A2-H03": h3_flow_continuation,
}

#: The non-traded arms, and the predicate that identifies each.
NON_TRADED_ARMS: dict[str, Callable[[Mapping[str, float]], bool]] = {
    "A2-NT-01": h1_short_covering_arm,
    "A2-NT-02": h3_exhaustion_arm,
}

#: The frozen hypothesis tuples, in registry order.
HYPOTHESES: tuple[dict[str, Any], ...] = tuple(dict(item) for item in PREREGISTRATION["hypotheses"])
