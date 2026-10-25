# ALPHA-002 — PREREGISTRATION (frozen before any result)

`PREREGISTRATION_HASH = 8b09f608256a31722b366f10e52513e9a347405d078138a9c350df1ad2439f6b`

- campaign: **ALPHA-002 — Derivatives Positioning & Order-Flow Alpha**
- question: Does adding information about market participants produce an out-of-sample effect large enough to clear the economic hurdle?
- status: **FROZEN_AWAITING_DATA**
- universe: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- entry timeframes: 5m, 15m · regime: 1h · forward horizon: 1 bar
- cost model: COST_MODEL_V3 at 23.790569 bps, inherited and not retuned

- parent campaign: ALPHA-001, verdict **ALPHA_ECONOMICALLY_TOO_SMALL**, binding constraint **EFFECT_SIZE_NOT_COST**
- no OHLCV hypothesis, threshold or horizon from ALPHA-001 is re-tested

## Hypotheses

### A2-H01 — BREAKOUT_CONFIRMATION (G1_POSITIONING_CONFIRMATION)

- mechanism: a breakout accompanied by rising open interest is new positioning rather than short covering, and aggressive buyers confirm it, so the move continues
- direction rule: `LONG when ret_z > breakout_ret_z and oi_chg > oi_expanding and taker_imbalance > taker_imbalance_confirm and |funding| <= funding_extreme_abs`
- expected regime: volatility expanding (vol_regime = +1)
- invalidation: no forward continuation on average, or the effect is carried by one trade, or the sign does not survive the four sub-windows
- timeframes: 5m, 15m (regime 1h)

### A2-H02 — CROWDED_POSITION_REVERSAL (G2_CROWDED_REVERSAL)

- mechanism: when published positioning is crowded long and the carry is stretched, the marginal buyer is already in and the move mean-reverts when momentum fades
- direction rule: `SHORT when max(ls_global_pctile, ls_top_position_pctile) >= crowding_pctile and funding > funding_elevated and momentum_delta < momentum_deteriorating`
- expected regime: any; crowding is the conditioning variable
- invalidation: positioning normalises without a reversal, or the reversal is symmetric (the mirror long arm is not tested, so a symmetric result is not an edge)
- timeframes: 5m, 15m (regime 1h)

### A2-H03 — FLOW_CONTINUATION_VS_EXHAUSTION (G3_FLOW_CONTINUATION)

- mechanism: a strong move with expanding open interest and aligned aggressor flow is new risk being taken, while the same move with collapsing open interest is positions being closed and carries no continuation
- direction rule: `LONG if ret_z > breakout_ret_z, SHORT if ret_z < -breakout_ret_z, in both cases only when oi_chg > oi_expanding and taker_imbalance aligns with the sign of ret_z by more than taker_imbalance_confirm`
- expected regime: any; open-interest expansion is the conditioning variable
- invalidation: the expansion subset does not out-return the collapse subset, or the effect is driven by a single directional episode
- timeframes: 5m, 15m (regime 1h)

## Declared non-traded arms

- **A2-NT-01** (A2-H01) SHORT_COVERING_CONTRAST: `ret_z > breakout_ret_z and oi_chg < oi_expanding`
  - the declared comparator for H1: it is reported as a differential and may never be promoted into a traded hypothesis
- **A2-NT-02** (A2-H03) EXHAUSTION_CONTRAST: `|ret_z| > breakout_ret_z and oi_chg < oi_expanding`
  - the declared comparator for H3: declared NO_TRADE, reported as a differential and never promoted

## Frozen thresholds

| threshold | value |
| --- | --- |
| breakout_ret_z | 1.0 |
| crowding_pctile | 0.9 |
| funding_elevated | 0.0001 |
| funding_extreme_abs | 0.0003 |
| momentum_deteriorating | 0.0 |
| oi_expanding | 0.0 |
| taker_imbalance_confirm | 0.05 |

## Features (the only inputs a hypothesis may read)

- `ret_z`: bar return divided by ATR over the same bar
- `atr_pct`: ATR divided by price, the local volatility level
- `oi_chg`: per-bar proportional change in open interest
- `oi_accel`: per-bar change in oi_chg, i.e. the second difference
- `taker_imbalance`: (takerBuyVolume - takerSellVolume) / (takerBuyVolume + takerSellVolume)
- `funding`: most recent settled funding rate, as a decimal
- `ls_global_pctile`: trailing percentile of the global long/short account ratio
- `ls_top_position_pctile`: trailing percentile of the top-trader position long/short ratio
- `momentum_delta`: change in short-horizon price momentum, the deterioration term
- `vol_regime`: 1h volatility regime: +1 expanding, -1 contracting

## Statistical gate

- inherited_from: ALPHA-001
- admission_rule: gross mean per trade must clear cost + 25% execution uncertainty + the RFC-023 winner's-curse buffer + z_{0.975} * sigma / sqrt(n_effective), with every term frozen before any result is observed
- multiplicity: Benjamini-Hochberg at q = 0.10 and Holm at alpha = 0.10
- selection_null: best-of-3 permutation null, 1000 draws
- concentration_gate: top-1 trade share > 0.25 or net excluding the best trade < 0 is FRAGILE
- stability_gate: gross mean must keep its sign across four sub-windows
- underpowered_is_not_negative: True

## Data status

- series captured: **84** (274835 rows, gaps: **0**)
- derivatives span captured: **29.00 days**
- funding history captured: **2583.67 days**
- capture scheduler: TradingAgentic-ALPHA002-Capture (every 15 minutes)
- the venue retains these series for 30 days only, so a missed day is a day of information destroyed and no later run can recover it
- Binance retains /futures/data/* for 30 days at every granularity; fundingRate is full history. A day without a capture run is a day of information destroyed.

## Frozen split

- rule: a calendar split of the captured span, identical for every series, with the final fifth reserved and never read by discovery
- discovery_fraction: 0.6
- validation_fraction: 0.2
- holdout_fraction: 0.2
- blocked_until: at least 30 days of continuous capture have accrued, so that the discovery and validation slices are both covered by real observations rather than by a retention edge

- not started: the derivatives series only began existing on 2026-10-07, and the preregistered split is defined below before any result is observed


## Prohibitions

- no parameter search
- no threshold tuning after results are seen
- no adding or removing a hypothesis after results are seen
- no re-use of the ALPHA-001 holdout for an ALPHA-001 question
- no change to COST_MODEL_V3
