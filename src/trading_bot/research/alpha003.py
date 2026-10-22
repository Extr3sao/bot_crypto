"""ALPHA-003 — the preregistered hypothesis registry for the cross-asset campaign.

ALPHA-001 tested twelve OHLCV-derived hypotheses over the asset's *own* history and
closed ``ALPHA_ECONOMICALLY_TOO_SMALL`` with the binding constraint measured to be the
effect size rather than the cost.  ALPHA-002 asked whether *market-participant*
information (open interest, aggressor flow, funding, published positioning) added an
effect that price alone did not, and closed ``NO_ALPHA_WITH_UNTESTED_HYPOTHESES``.

ALPHA-003 asks a third, narrower and different question:

    Does knowing what another asset has done add usable information about what the
    target asset will do next, *after controlling for what the target was already
    doing*?

That control is the whole campaign.  A rule that trades the target on the leader's
move is not evidence unless the *same* rule, with the cross-asset term removed, does
worse.  So every hypothesis here is declared together with the own-history baseline it
is measured against, and the campaign's headline number is the **incremental delta**,
never a raw gross return:

    incremental_delta_bps = cross_asset_arm.gross_bps - own_baseline_arm.gross_bps

Relationship to ALPHA-001's ``F2_CROSS_ASSET_LEAD_LAG`` (A1-H03/A1-H04).  Those were
**daily**, over a **basket**, with **no own-asset control**: ``BTC 1d return ->
alt basket forward return``.  ALPHA-003 is **intraday** (5m/15m), **per asset**,
symmetric in sign, over a **declared pair set**, with a **lag ladder** and, crucially,
with an **own-history baseline that must be beaten**.  It is a different question on
the same broad family, not a re-tuning of A1-H03; no threshold, horizon or asset from
ALPHA-001 or ALPHA-002 is reused as a signal input here.

What this module is: the frozen half of the campaign.  Three mechanisms — lead-lag
continuation, relative-strength persistence and dispersion convergence — each written
as a mechanical rule over *derived, dimensionless* feature values so that no
interpretation happens after the results are seen.  Thresholds are conventional,
round, economically meaningful numbers chosen before any result.

What this module is not: no data access, no strategy, no order path.  The builder lives
in ``scripts/`` and the statistics are ALPHA-001's, unchanged.

Discipline it enforces:

* **One campaign, three mechanisms.**  Not one hundred pair/timeframe/lag combinations
  searched until one glows.  The pair set and the lag ladder are enumerated here.
* **The rule is the hash.**  ``preregistration_hash`` covers the declarative registry;
  the executable signals are separately asserted (in tests) to implement it, so a
  silent divergence between text and code is a test failure rather than a finding.
* **Non-traded arms are declared, not discovered.**  The leader-only and
  target-extended branches are stated here as comparators that are reported but never
  traded, so they cannot be promoted after the fact.
* **The rule may not use machine learning.**  There is no fitted parameter, no model
  and no learned coefficient anywhere in this campaign; if a simple relation is not
  there, a flexible model would only fit the noise.
* **The cost model is inherited.**  ``COST_BPS_V3`` is imported from ``alpha001`` —
  one number, one source, no second opinion, never retuned.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from trading_bot.research.alpha001 import COST_BPS_V3

__all__ = [
    "CONTEXT_STATISTICS",
    "CONTEXT_TIMEFRAME",
    "COST_BPS_V3",
    "ENTRY_TIMEFRAMES",
    "FEATURES",
    "FORWARD_BARS",
    "HYPOTHESES",
    "LEADER_TARGET_PAIRS",
    "LEAD_LAGS",
    "NON_TRADED_ARMS",
    "PREREGISTRATION",
    "SIGNALS",
    "THRESHOLDS",
    "UNIVERSE",
    "h1_lead_lag_continuation",
    "h1_leader_only_contrast",
    "h1_target_extended_contrast",
    "h2_relative_strength_persistence",
    "h3_dispersion_convergence",
    "preregistration_hash",
]

#: The traded universe.  Same four assets as ALPHA-002 on purpose: the campaign is
#: about relationships *between* assets, and widening the universe would widen the
#: multiple-testing surface before a single relationship has been shown to exist.
UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

#: Entry timeframes.  Intraday, because a lead-lag that only exists at 1d has already
#: been tested and closed (A1-H03/H04) and because the runtime this research serves
#: decides intraday.
ENTRY_TIMEFRAMES = ("5m", "15m")

#: A slower clock used only for causal volatility-regime tagging (context reported
#: beside a result, never a filter on one).
CONTEXT_TIMEFRAME = "1h"

#: Forward horizon in entry bars.  One bar, so overlapping-sample effects stay
#: negligible and the effective sample size is close to the raw count.
FORWARD_BARS = 1

#: The preregistered lag ladder, in entry bars, for the lead-lag mechanism only.
#: Two lags, not a search: ``lag = 1`` is the one-bar lead and ``lag = 2`` asks whether
#: the lead survives being measured one bar earlier.
LEAD_LAGS = (1, 2)

#: The declared leader -> target pairs.  Small and mechanism-driven: BTC is the market
#: leader, ETH is the second-most-liquid asset.  The list is exhausted, not extended.
LEADER_TARGET_PAIRS = (
    ("BTCUSDT", "ETHUSDT"),
    ("BTCUSDT", "SOLUSDT"),
    ("BTCUSDT", "XRPUSDT"),
    ("ETHUSDT", "SOLUSDT"),
    ("ETHUSDT", "XRPUSDT"),
)

#: The derived feature every signal is allowed to read.  Each is dimensionless (a
#: return in ATR units, or a difference of such), computed causally from bars that had
#: closed by the decision instant.  Anything not listed here may not be used by a
#: hypothesis.  The two correlation/beta columns are context: reported, never inputs.
FEATURES: tuple[dict[str, str], ...] = (
    {
        "name": "leader_ret_z",
        "definition": "the leader's lag-window return divided by the leader's ATR, signed",
    },
    {
        "name": "target_ret_z",
        "definition": "the target's lag-window return divided by the target's ATR, signed",
    },
    {
        "name": "target_mom_z",
        "definition": "the target's R-bar return divided by the target's own ATR, signed",
    },
    {
        "name": "relative_z",
        "definition": (
            "target_mom_z minus the equal-weight cross-sectional market R-bar return expressed in "
            "the target's ATR units: relative strength against peers"
        ),
    },
    {
        "name": "market_ret_z",
        "definition": (
            "equal-weight cross-sectional R-bar return expressed in the target's ATR units, signed; "
            "the common market factor"
        ),
    },
)

#: Descriptive statistics computed and reported beside the results.  They are NOT
#: inputs: no hypothesis may read them, which is why they are declared separately from
#: the feature list above.
CONTEXT_STATISTICS: tuple[dict[str, str], ...] = (
    {
        "name": "corr_market",
        "definition": (
            "trailing causal correlation of the target's 1h returns with the market's 1h "
            "returns, window 96 1h bars, reported by regime and by asset"
        ),
    },
    {
        "name": "beta_market",
        "definition": (
            "trailing causal OLS beta of the target's 1h returns on the market's 1h returns, "
            "window 96 1h bars, never a full-sample regression"
        ),
    },
)

#: Frozen thresholds.  Round, economically meaningful levels expressed in ATR units,
#: chosen from market-structure reasoning and not fitted to any series.
#: ``leader_ret_z`` of 1.0 is a one-ATR move; a half-ATR ``lag_gap`` is a visibly
#: un-repriced target; a one-ATR ``relative_strength_z`` is a visible cross-sectional
#: lead; the 1.5-ATR ``convergence_relative_z`` is deliberately stricter because a
#: convergence bet needs a genuine divergence, not ordinary cross-sectional noise.
THRESHOLDS: dict[str, float] = {
    "leader_ret_z": 1.0,
    "lag_gap": 0.5,
    "relative_strength_z": 1.0,
    "convergence_relative_z": 1.5,
    "market_ret_z": 1.0,
}

#: The declarative registry.  ``preregistration_hash`` covers exactly this object, so
#: any change to a rule, a threshold, a timeframe, the pair set or the lag ladder
#: changes the hash and invalidates the campaign.
PREREGISTRATION: dict[str, Any] = {
    "campaign": "ALPHA-003",
    "title": "Cross-Asset / Relative Strength / Lead-Lag",
    "question": (
        "Does information from another asset improve the prediction of the target's "
        "forward return beyond what the target's own history already explains?"
    ),
    "central_question": (
        "does knowing what BTC has done add usable information about what SOL will do, "
        "after controlling for what SOL was already doing?"
    ),
    "parent": {
        "alpha001": {
            "verdict": "ALPHA_ECONOMICALLY_TOO_SMALL",
            "binding_constraint": "EFFECT_SIZE_NOT_COST",
            "family_overlap": "F2_CROSS_ASSET_LEAD_LAG (A1-H03/A1-H04) tested BTC -> alt BASKET at 1D",
            "difference": (
                "ALPHA-003 is intraday, per asset, symmetric in sign, over a declared pair set "
                "with a lag ladder and, decisively, with an own-history baseline that must be "
                "beaten; A1-H03/H04 had no own-asset control and no per-pair structure"
            ),
            "not_reopened": "no ALPHA-001 threshold, horizon or asset is re-used as a signal input",
        },
        "alpha002": {
            "verdict": "NO_ALPHA_WITH_UNTESTED_HYPOTHESES",
            "note": "derivatives positioning added nothing over the price condition it was built on",
        },
    },
    "universe": list(UNIVERSE),
    "entry_timeframes": list(ENTRY_TIMEFRAMES),
    "context_timeframe": CONTEXT_TIMEFRAME,
    "forward_bars": FORWARD_BARS,
    "lead_lags": list(LEAD_LAGS),
    "leader_target_pairs": [list(pair) for pair in LEADER_TARGET_PAIRS],
    "features": [dict(item) for item in FEATURES],
    "context_statistics": [dict(item) for item in CONTEXT_STATISTICS],
    "thresholds": dict(THRESHOLDS),
    "cost_model": {
        "name": "COST_MODEL_V3",
        "cost_bps": COST_BPS_V3,
        "inherited_from": "trading_bot.research.alpha001.COST_BPS_V3",
        "retuned": False,
    },
    "machine_learning": {
        "used": False,
        "prohibited": ["XGBoost", "LightGBM", "neural networks", "Transformers", "LLM prediction"],
        "why": (
            "a flexible model cannot answer whether a simple cross-asset relation exists; if the "
            "simple relation is absent, more capacity only fits the noise"
        ),
    },
    "incremental_definition": (
        "incremental_delta_bps = gross_bps(cross-asset arm) - gross_bps(the same hypothesis's "
        "own-history baseline arm); a cross-asset arm is only interesting if this is positive"
    ),
    "statistical_gate": {
        "inherited_from": "ALPHA-001",
        "admission_rule": (
            "gross mean per trade must clear cost + 25% execution uncertainty + the RFC-023 "
            "winner's-curse buffer + z_{0.975} * sigma / sqrt(n_effective), with every term "
            "frozen before any result is observed"
        ),
        "multiplicity": "Benjamini-Hochberg at q = 0.10 and Holm at alpha = 0.10 across every cell",
        "selection_null": (
            "best-of-N permutation null over every cell, 1000 draws, by circularly shifting the "
            "leader/relative signal against the returns — an equally-sized random signal of the "
            "same shape must not reproduce the apparent result"
        ),
        "concentration_gate": "top-1 trade share > 0.25 or net excluding the best trade < 0 is FRAGILE",
        "stability_gate": "gross mean must keep its sign across four sub-windows",
        "underpowered_is_not_negative": True,
    },
    "hypotheses": (
        {
            "hypothesis_id": "A3-H01",
            "family_id": "L1_LEAD_LAG_CONTINUATION",
            "name": "LEAD_LAG_CONTINUATION",
            "mechanism": (
                "the leader makes a large directional move, the target has already moved the same "
                "way but materially less, and the un-repriced remainder is worked off during the "
                "next bar"
            ),
            "direction_rule": (
                "direction = sign(leader_ret_z); fire only when |leader_ret_z| > leader_ret_z and "
                "direction * target_ret_z >= 0 and direction * (leader_ret_z - target_ret_z) >= lag_gap"
            ),
            "baseline_arm": "A3-B1_OWN_MOMENTUM_SAME_LAG",
            "expected_regime": (
                "any; the lead is expected to be strongest when volatility is contracting and the "
                "market is moving together"
            ),
            "invalidation": (
                "no forward continuation on average, or the incremental delta over the own-history "
                "baseline is not positive, or the sign does not survive the four sub-windows"
            ),
            "pairs": [list(pair) for pair in LEADER_TARGET_PAIRS],
            "lags": list(LEAD_LAGS),
            "timeframes": list(ENTRY_TIMEFRAMES),
            "traded": True,
        },
        {
            "hypothesis_id": "A3-H02",
            "family_id": "L2_RELATIVE_STRENGTH_PERSISTENCE",
            "name": "RELATIVE_STRENGTH_PERSISTENCE",
            "mechanism": (
                "an asset that is outperforming the equal-weight market over a trailing window keeps "
                "outperforming, because relative strength is funded flow rotating into it rather "
                "than a stochastic spread"
            ),
            "direction_rule": (
                "direction = sign(relative_z) when |relative_z| > relative_strength_z, where "
                "relative_z is the target R-bar return minus the equal-weight market R-bar return "
                "in ATR units"
            ),
            "baseline_arm": "A3-B1_OWN_MOMENTUM_R",
            "expected_regime": "any; relative strength is the conditioning variable",
            "invalidation": (
                "the own-history momentum arm does at least as well, or the effect is carried by a "
                "single asset or a single window"
            ),
            "pairs": [],
            "lags": [],
            "timeframes": list(ENTRY_TIMEFRAMES),
            "traded": True,
        },
        {
            "hypothesis_id": "A3-H03",
            "family_id": "L3_DISPERSION_CONVERGENCE",
            "name": "DISPERSION_CONVERGENCE",
            "mechanism": (
                "correlated assets move together; when the market moves and one asset diverges "
                "abnormally against it, the spread closes and the diverging asset catches up"
            ),
            "direction_rule": (
                "direction = sign(market_ret_z); fire only when |market_ret_z| > market_ret_z and "
                "|relative_z| > convergence_relative_z and market_ret_z * relative_z < 0 (the "
                "target diverged AGAINST the market)"
            ),
            "direction_note": (
                "CONVERGENCE is the single preregistered direction, fixed before any result; the "
                "opposite reading (relative weakness persists) is not tested here and may not be "
                "selected after the fact"
            ),
            "baseline_arm": "A3-B1_OWN_MOMENTUM_R",
            "expected_regime": (
                "the mechanism needs a market move, so it is expected to be exercised in trending "
                "and high-volatility windows"
            ),
            "invalidation": (
                "the diverging asset keeps diverging more often than it converges, or the "
                "incremental delta over own-history momentum is not positive"
            ),
            "pairs": [],
            "lags": [],
            "timeframes": list(ENTRY_TIMEFRAMES),
            "traded": True,
        },
    ),
    "baselines": (
        {
            "baseline_id": "A3-B0_UNCONDITIONAL_LONG",
            "rule": "always long",
            "role": "the unconditional return of the target",
        },
        {
            "baseline_id": "A3-B1_OWN_MOMENTUM_SAME_LAG",
            "rule": (
                "direction = sign(target_ret_z) when |target_ret_z| > leader_ret_z — the target's "
                "own move at the hypothesis's own horizon, with no cross-asset term"
            ),
            "role": "the own-history baseline for A3-H01",
        },
        {
            "baseline_id": "A3-B1_OWN_MOMENTUM_R",
            "rule": "direction = sign(target R-bar ATR-z) when the magnitude exceeds relative_strength_z",
            "role": "the own-history baseline for A3-H02 and A3-H03",
        },
        {
            "baseline_id": "A3-B2_PERMUTATION",
            "rule": "the cross-asset arm measured with the leader/relative series circularly shifted",
            "role": "would an equally-sized random signal of the same shape reproduce the result?",
        },
        {
            "baseline_id": "A3-B3_MARKET_DIRECTION",
            "rule": "direction = sign(market_ret_z) when |market_ret_z| > leader_ret_z",
            "role": "the common-factor baseline: trade the target on the market, using no pair at all",
        },
    ),
    "non_traded_arms": (
        {
            "arm_id": "A3-NT-01",
            "hypothesis_id": "A3-H01",
            "name": "LEADER_ONLY_CONTRAST",
            "rule": "|leader_ret_z| > leader_ret_z, direction = sign(leader_ret_z), with no target condition",
            "role": (
                "the declared comparator for H1: the cross-asset effect with the target-lag condition "
                "removed.  Reported as a differential and never promoted into a traded hypothesis"
            ),
        },
        {
            "arm_id": "A3-NT-02",
            "hypothesis_id": "A3-H01",
            "name": "TARGET_EXTENDED_CONTRAST",
            "rule": "|leader_ret_z| > leader_ret_z and direction * (leader_ret_z - target_ret_z) <= 0",
            "role": (
                "the declared NO_TRADE arm: the target already repriced at least as much as the "
                "leader.  Declared so that the 'lag' side of the trade cannot be chosen after the "
                "fact, and never promoted"
            ),
        },
    ),
    "prohibitions": (
        "no parameter search",
        "no threshold tuning after results are seen",
        "no adding or removing a hypothesis, pair, lag or timeframe after results are seen",
        "no machine learning of any kind in this campaign",
        "no re-use of the ALPHA-001 or ALPHA-002 holdout for an ALPHA-001/002 question",
        "no reading the ALPHA-003 holdout during development",
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


def h1_lead_lag_continuation(row: Mapping[str, float]) -> int:
    """A3-H01: continuation in the leader's direction while the target lags it."""
    leader = row["leader_ret_z"]
    if abs(leader) <= THRESHOLDS["leader_ret_z"]:
        return 0
    direction = 1 if leader > 0 else -1
    if direction * row["target_ret_z"] < 0.0:
        return 0
    if direction * (leader - row["target_ret_z"]) < THRESHOLDS["lag_gap"]:
        return 0
    return direction


def h1_leader_only_contrast(row: Mapping[str, float]) -> bool:
    """A3-NT-01: the declared, non-traded leader-only comparator."""
    return abs(row["leader_ret_z"]) > THRESHOLDS["leader_ret_z"]


def h1_target_extended_contrast(row: Mapping[str, float]) -> bool:
    """A3-NT-02: the declared NO_TRADE arm — the target already repriced."""
    leader = row["leader_ret_z"]
    if abs(leader) <= THRESHOLDS["leader_ret_z"]:
        return False
    direction = 1 if leader > 0 else -1
    return direction * (leader - row["target_ret_z"]) <= 0.0


def h2_relative_strength_persistence(row: Mapping[str, float]) -> int:
    """A3-H02: continue the target's return relative to the equal-weight market."""
    relative = row["relative_z"]
    if abs(relative) <= THRESHOLDS["relative_strength_z"]:
        return 0
    return 1 if relative > 0 else -1


def h3_dispersion_convergence(row: Mapping[str, float]) -> int:
    """A3-H03: fade an abnormal divergence of the target against a moving market."""
    market = row["market_ret_z"]
    relative = row["relative_z"]
    if abs(market) <= THRESHOLDS["market_ret_z"]:
        return 0
    if abs(relative) <= THRESHOLDS["convergence_relative_z"]:
        return 0
    if market * relative >= 0.0:
        return 0
    return 1 if market > 0 else -1


#: Every declared traded hypothesis must appear here, and nothing else may.  A test
#: enforces the correspondence in both directions.
SIGNALS: dict[str, Callable[[Mapping[str, float]], int]] = {
    "A3-H01": h1_lead_lag_continuation,
    "A3-H02": h2_relative_strength_persistence,
    "A3-H03": h3_dispersion_convergence,
}

#: The non-traded arms, and the predicate that identifies each.
NON_TRADED_ARMS: dict[str, Callable[[Mapping[str, float]], bool]] = {
    "A3-NT-01": h1_leader_only_contrast,
    "A3-NT-02": h1_target_extended_contrast,
}

#: The frozen hypothesis tuples, in registry order.
HYPOTHESES: tuple[dict[str, Any], ...] = tuple(dict(item) for item in PREREGISTRATION["hypotheses"])
