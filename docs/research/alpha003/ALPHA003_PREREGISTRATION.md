# ALPHA-003 — PREREGISTRATION (frozen before any result)

`PREREGISTRATION_HASH = db43ad5283cad875ac014a622dc7acae423d0e44c5f64c473a039e3f9ed1c4c8`
`FEATURE_VERSION = 98fffdda8a6109cd1c76e00cefc95ef796ee3960cb7336103ab945e3d7126b66`

- campaign: **ALPHA-003 — Cross-Asset / Relative Strength / Lead-Lag**
- question: Does information from another asset improve the prediction of the target's forward return beyond what the target's own history already explains?
- central question: does knowing what BTC has done add usable information about what SOL will do, after controlling for what SOL was already doing?
- status: **FROZEN_AWAITING_RESULT**
- universe: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- entry timeframes: 5m, 15m · context: 1h · forward horizon: 1 bar
- leader -> target pairs: BTCUSDT->ETHUSDT, BTCUSDT->SOLUSDT, BTCUSDT->XRPUSDT, ETHUSDT->SOLUSDT, ETHUSDT->XRPUSDT
- lead ladder: [1, 2] entry bars
- cells: **36** declared, and no cell outside this list is reported
- cost model: COST_MODEL_V3 at 23.790569 bps, inherited and not retuned
- machine learning used: **False** (prohibited: XGBoost, LightGBM, neural networks, Transformers, LLM prediction)

## Relationship to the parent campaigns

### alpha001

- verdict: ALPHA_ECONOMICALLY_TOO_SMALL
- binding_constraint: EFFECT_SIZE_NOT_COST
- family_overlap: F2_CROSS_ASSET_LEAD_LAG (A1-H03/A1-H04) tested BTC -> alt BASKET at 1D
- difference: ALPHA-003 is intraday, per asset, symmetric in sign, over a declared pair set with a lag ladder and, decisively, with an own-history baseline that must be beaten; A1-H03/H04 had no own-asset control and no per-pair structure
- not_reopened: no ALPHA-001 threshold, horizon or asset is re-used as a signal input

### alpha002

- verdict: NO_ALPHA_WITH_UNTESTED_HYPOTHESES
- note: derivatives positioning added nothing over the price condition it was built on

## The incremental definition (the whole campaign)

incremental_delta_bps = gross_bps(cross-asset arm) - gross_bps(the same hypothesis's own-history baseline arm); a cross-asset arm is only interesting if this is positive

A cross-asset arm that merely replicates ordinary own-asset momentum is a failure of
this campaign, and the arithmetic is written to say so.

## Hypotheses

### A3-H01 — LEAD_LAG_CONTINUATION (L1_LEAD_LAG_CONTINUATION)

- mechanism: the leader makes a large directional move, the target has already moved the same way but materially less, and the un-repriced remainder is worked off during the next bar
- direction rule: `direction = sign(leader_ret_z); fire only when |leader_ret_z| > leader_ret_z and direction * target_ret_z >= 0 and direction * (leader_ret_z - target_ret_z) >= lag_gap`
- baseline arm (incremental measured against): `A3-B1_OWN_MOMENTUM_SAME_LAG`
- expected regime: any; the lead is expected to be strongest when volatility is contracting and the market is moving together
- invalidation: no forward continuation on average, or the incremental delta over the own-history baseline is not positive, or the sign does not survive the four sub-windows
- timeframes: 5m, 15m

### A3-H02 — RELATIVE_STRENGTH_PERSISTENCE (L2_RELATIVE_STRENGTH_PERSISTENCE)

- mechanism: an asset that is outperforming the equal-weight market over a trailing window keeps outperforming, because relative strength is funded flow rotating into it rather than a stochastic spread
- direction rule: `direction = sign(relative_z) when |relative_z| > relative_strength_z, where relative_z is the target R-bar return minus the equal-weight market R-bar return in ATR units`
- baseline arm (incremental measured against): `A3-B1_OWN_MOMENTUM_R`
- expected regime: any; relative strength is the conditioning variable
- invalidation: the own-history momentum arm does at least as well, or the effect is carried by a single asset or a single window
- timeframes: 5m, 15m

### A3-H03 — DISPERSION_CONVERGENCE (L3_DISPERSION_CONVERGENCE)

- mechanism: correlated assets move together; when the market moves and one asset diverges abnormally against it, the spread closes and the diverging asset catches up
- direction rule: `direction = sign(market_ret_z); fire only when |market_ret_z| > market_ret_z and |relative_z| > convergence_relative_z and market_ret_z * relative_z < 0 (the target diverged AGAINST the market)`
- baseline arm (incremental measured against): `A3-B1_OWN_MOMENTUM_R`
- expected regime: the mechanism needs a market move, so it is expected to be exercised in trending and high-volatility windows
- invalidation: the diverging asset keeps diverging more often than it converges, or the incremental delta over own-history momentum is not positive
- timeframes: 5m, 15m

- direction note: CONVERGENCE is the single preregistered direction, fixed before any result; the opposite reading (relative weakness persists) is not tested here and may not be selected after the fact

## Declared baselines

- **A3-B0_UNCONDITIONAL_LONG**: `always long` — the unconditional return of the target
- **A3-B1_OWN_MOMENTUM_SAME_LAG**: `direction = sign(target_ret_z) when |target_ret_z| > leader_ret_z — the target's own move at the hypothesis's own horizon, with no cross-asset term` — the own-history baseline for A3-H01
- **A3-B1_OWN_MOMENTUM_R**: `direction = sign(target R-bar ATR-z) when the magnitude exceeds relative_strength_z` — the own-history baseline for A3-H02 and A3-H03
- **A3-B2_PERMUTATION**: `the cross-asset arm measured with the leader/relative series circularly shifted` — would an equally-sized random signal of the same shape reproduce the result?
- **A3-B3_MARKET_DIRECTION**: `direction = sign(market_ret_z) when |market_ret_z| > leader_ret_z` — the common-factor baseline: trade the target on the market, using no pair at all

## Declared non-traded arms

- **A3-NT-01** (A3-H01) LEADER_ONLY_CONTRAST: `|leader_ret_z| > leader_ret_z, direction = sign(leader_ret_z), with no target condition`
  - the declared comparator for H1: the cross-asset effect with the target-lag condition removed.  Reported as a differential and never promoted into a traded hypothesis
- **A3-NT-02** (A3-H01) TARGET_EXTENDED_CONTRAST: `|leader_ret_z| > leader_ret_z and direction * (leader_ret_z - target_ret_z) <= 0`
  - the declared NO_TRADE arm: the target already repriced at least as much as the leader.  Declared so that the 'lag' side of the trade cannot be chosen after the fact, and never promoted

## Frozen thresholds (ATR units)

| threshold | value |
| --- | --- |
| convergence_relative_z | 1.5 |
| lag_gap | 0.5 |
| leader_ret_z | 1.0 |
| market_ret_z | 1.0 |
| relative_strength_z | 1.0 |

## Features (the only inputs a hypothesis may read)

- `leader_ret_z`: the leader's lag-window return divided by the leader's ATR, signed
- `target_ret_z`: the target's lag-window return divided by the target's ATR, signed
- `target_mom_z`: the target's R-bar return divided by the target's own ATR, signed
- `relative_z`: target_mom_z minus the equal-weight cross-sectional market R-bar return expressed in the target's ATR units: relative strength against peers
- `market_ret_z`: equal-weight cross-sectional R-bar return expressed in the target's ATR units, signed; the common market factor

## Context statistics (reported, never inputs)

- `corr_market`: trailing causal correlation of the target's 1h returns with the market's 1h returns, window 96 1h bars, reported by regime and by asset
- `beta_market`: trailing causal OLS beta of the target's 1h returns on the market's 1h returns, window 96 1h bars, never a full-sample regression

## Feature construction constants

| key | value |
| --- | --- |
| atr_window | 14 |
| clock | decision_ms = entry bar open + period; every symbol is addressed by the same open |
| contiguity_policy | a window is used only when every bar it needs is present; otherwise the feature is undefined, never forward-filled across a gap |
| leader_availability | with lag L the leader window ends at decision_ms - (L - 1) * period, so it is never later than the decision instant |
| market_definition | equal-weight mean of the universe's raw window returns; the common factor, expressed in the target's ATR units when read by a hypothesis |
| min_vol_regime_observations | 72 |
| missing_observation_policy | a row missing a required source is dropped for that arm, never imputed |
| price_availability | available = bar open + period (a bar is knowable at its close) |
| relative_definition | target_mom_z - market_ret_z; both normalised by the target's own ATR |
| relative_window | 12 |
| vol_regime_baseline_window | 168 |
| vol_regime_short_window | 24 |
| zero_denominator_policy | a feature whose ATR denominator is zero is undefined, not zero |

## Statistical gate

- inherited_from: ALPHA-001
- admission_rule: gross mean per trade must clear cost + 25% execution uncertainty + the RFC-023 winner's-curse buffer + z_{0.975} * sigma / sqrt(n_effective), with every term frozen before any result is observed
- multiplicity: Benjamini-Hochberg at q = 0.10 and Holm at alpha = 0.10 across every cell
- selection_null: best-of-N permutation null over every cell, 1000 draws, by circularly shifting the leader/relative signal against the returns — an equally-sized random signal of the same shape must not reproduce the apparent result
- concentration_gate: top-1 trade share > 0.25 or net excluding the best trade < 0 is FRAGILE
- stability_gate: gross mean must keep its sign across four sub-windows
- underpowered_is_not_negative: True

## Frozen split

- rule: a calendar split of the common price span, identical for every asset, pair, lag and timeframe, with the final fifth reserved and never read by development
- discovery_fraction: 0.6
- validation_fraction: 0.2
- holdout_fraction: 0.2
- holdout_lock: HOLDOUT LOCKED during ALPHA-003 development

- not started: the registry, the thresholds, the feature construction constants and the split rule below are frozen before any cross-asset result is computed

## Disk at freeze time

- total_gib: 237.53
- used_gib: 237.0
- free_gib: 0.53
- used_fraction: 0.9978
- note: the research dataset is generated under data/raw/alpha003 (gitignored); no existing data is removed

## Prohibitions

- no parameter search
- no threshold tuning after results are seen
- no adding or removing a hypothesis, pair, lag or timeframe after results are seen
- no machine learning of any kind in this campaign
- no re-use of the ALPHA-001 or ALPHA-002 holdout for an ALPHA-001/002 question
- no reading the ALPHA-003 holdout during development
- no change to COST_MODEL_V3
