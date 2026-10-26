# RFC-046 ECONOMIC FEASIBILITY — RETAIL SPOT WITH 200 USDT

generated_at_utc = 2026-10-08T14:13:48Z (computed, not authored)
head_at_run = 04fa741ab3dd6fb27a7fc44d42ed4e1e439a27b5
scope_recommendation = **VIABLE_COST_PROFILE_IDENTIFIED**
not_an_edge_claim = **True** (no edge, profit or production capability is claimed)
false_success = 0

## 1. What the authorized runtime actually is

- venue/product: **binance / spot**, account type `spot`, sandbox True
- direction: long/cash only (spot cannot short; derivatives are excluded)
- excluded markets (config): Leveraged Tokens, Derivatives, Options
- default order posture (config): post_only=True, TIF=GTC
- reference capital: **200 USDT**

## 2. Verified costs (COST_MODEL_V3 reused, not rebuilt)

| scenario | order types | size | round trip bps | knowledge |
| --- | --- | --- | --- | --- |
| BINANCE_SPOT_STANDARD_TAKER | market / market | 1,000 USD | 23.790569415 | ESTIMATED |
| BINANCE_SPOT_STANDARD_TAKER | market / market | **200 USDT** | 23.353553391 | ESTIMATED |
| BINANCE_SPOT_STANDARD_MAKER | limit_post_only / limit_post_only | 1,000 USD | 41.25 | ASSUMED |
| BINANCE_SPOT_STANDARD_MAKER | limit_post_only / limit_post_only | 200 USDT | 41.25 | ASSUMED |

### The decomposition of the 200 USDT round trip

| component | bps | knowledge | source |
| --- | --- | --- | --- |
| exchange_fee_entry | 10.0 | KNOWN | SRC-01 |
| exchange_fee_exit | 10.0 | KNOWN | SRC-01 |
| spread | 1.0 | ESTIMATED | SRC-07 |
| slippage | 2.282842712 | ESTIMATED | MODEL-V3 |
| market_impact | 0.070710678 | ESTIMATED | MODEL-V3 |

Exchange fees are **85.6%** of the toll (20.0 of 23.353553391 bps). Spread, slippage and size-driven impact together are 3.35355339 bps. The toll is a fee schedule with a small execution term attached.

### Applicability of each assumption

| assumption | verdict | why |
| --- | --- | --- |
| Binance Spot VIP0 fee, 10 bps per leg, paid in the quote asset | **CONFIRMED** | published schedule for our tier; the runtime's venue and account type match the scenario |
| majors' taker spread 1.0 bps (2 legs x half-spread) | **UNKNOWN** | SRC-07 has no historical endpoint: the estimate comes from a single bookTicker observation and cannot be re-verified for a past period |
| base slippage 1.0 bps and size/impact constants | **UNKNOWN** | the model's own constants block labels them ASSUMED/ESTIMATED modelling constants, not observations |
| size term 1 + sqrt(size / 10,000) | **UNKNOWN** | a documented modelling choice, never fitted to our fills |
| maker adverse selection 0.5 bps per leg and fill probability 0.5 | **NOT_APPLICABLE** | no usable fill evidence exists; EXECUTION_MODEL_V1.json is EXECUTION_MODEL_REQUIRED — the maker path is barred from admission |
| BNB fee discount (-25%) | **POSSIBLE** | the rate is published, but applicability to our account is unconfirmed |
| derivative scenarios (USDⓈ-M perpetual, 9.25 bps maker) | **NOT_APPLICABLE** | excluded from the runtime by config/exchange.yaml (Derivatives) and by the RFC-046 scope rules |
| other spot venues (MEXC 17.79, Bybit/OKX 23.79, Kraken 83.79 bps) | **NOT_APPLICABLE** | not the authorized runtime venue, and their spreads are ASSUMED rather than observed (caveat in VENUE_EXECUTION_MATRIX_V1.json) |
| min notional 5 USD | **CONFIRMED** | published instrument filter present in the frozen model's venue specs |

Declared caveats:

- a forward collection is required before any realised-cost comparison, and this is the component a cost overrun would most likely arrive in
- no measured slippage exists for our order flow
- it moves the bar by only 0.32 bps between the two reference sizes, because the fee term dominates and is size-invariant — the model's precision is spent on a small term
- the frozen model forbids treating a discount as CONFIRMED without a governance decision, so it cannot lower today's bar

Conflicts with the authorized runtime:

- the runtime is configured sandbox: true, so a testnet fill does not reproduce live-account fees — the fee arithmetic is a live-account property
- the runtime's own default order posture is post_only (config), and at VIP0 the maker fee equals the taker fee, so the configured default buys no fee saving while adding fill risk the model charges for
- the cheapest documented scenario in the whole model is therefore unreachable today
- no venue switch is available as a cost-side rescue without a new measurement and a governance decision
- at 200 USDT the smallest legal position is 2.5% of the account, so any size below that cannot be executed at all — a granularity floor, not a cash cost

## 3. Break-even at 200 USDT

| quantity | value |
| --- | --- |
| minimum gross move per round trip | **23.353553 bps** = 0.467071068 USDT |
| minimum expectancy to be net positive | > 23.353553 bps |
| required gross edge at 1.5x stress | 35.030330 bps = 0.700606602 USDT |
| frozen campaign figure (1,000 USD reference) | 23.790600 bps; stress threshold 35.685900 bps |
| maker round trip at 200 USDT | 41.250000 bps (size-invariant, and inadmissible: no fill evidence) |

### Three round trips a day, illustrative only

- cost per round trip: **0.467071068 USDT**
- three a day: **1.401213203 USDT/day** = 0.70% of capital per day
- a year at that cadence: 511.442819254 USDT = **2.56x the account** in gross trading profit just to pay the venue

### Sensitivity to size

| size USDT | round trip bps | cost per round trip USDT | fees share |
| --- | --- | --- | --- |
| 25 | 23.125 | 0.0578125 | 86.5% |
| 50 | 23.176776695 | 0.115883883 | 86.3% |
| 100 | 23.25 | 0.2325 | 86.0% |
| 200 | 23.353553391 | 0.467071068 | 85.6% |
| 500 | 23.559016994 | 1.17795085 | 84.9% |
| 1000 | 23.790569415 | 2.379056942 | 84.1% |

The rate is nearly flat in size (23.35 → 23.79 bps from 200 to 1,000 USDT) because fees dominate; only the absolute bill scales. A smaller account gets a smaller bill, not a better rate.

### Sensitivity to turnover — the operating-cost impact on the business

Target used: +20% net annual (40 USDT/year), the figure already documented in the operating model. These are requirements, not forecasts.

| round trips/day | cost/year USDT | cost/year vs capital | net margin needed bps/trade | gross needed bps/trade | margin share of gross | cost overrun that erases the target |
| --- | --- | --- | --- | --- | --- | --- |
| 0.2 | 34.10 | 17.0% | 27.40 | 50.75 | 54.0% | 27.40 bps |
| 1.0 | 170.48 | 85.2% | 5.48 | 28.83 | 19.0% | 5.48 bps |
| 3.0 | 511.44 | 255.7% | 1.83 | 25.18 | 7.3% | 1.83 bps |
| 10.0 | 1704.81 | 852.4% | 0.55 | 23.90 | 2.3% | 0.55 bps |

the thinner the net margin over the toll, the more the business depends on the cost model being right: at high turnover the margin is a few percent of the gross move and any realised-cost overrun erases the year.

## 4. What the toll costs a strategy by horizon (measured, signal-free)

non-overlapping windows on the open of the 5-minute bars: |open[i+k]/open[i] - 1| in bps, k set by the horizon; four majors pooled; no signal, no direction and no parameter is generated.

| horizon | windows | median move bps | p75 bps | p90 bps |
| --- | --- | --- | --- | --- |
| 5m | 848433 | 8.588957 | 17.220544 | 30.422037 |
| 15m | 282809 | 15.08965 | 29.764365 | 52.325906 |
| 1h | 70700 | 29.381129 | 59.027778 | 105.284392 |
| 4h | 17672 | 60.466783 | 122.415987 | 217.628747 |
| 8h | 8836 | 89.265721 | 178.64175 | 308.174706 |
| 24h | 2944 | 164.801314 | 322.182344 | 555.72085 |
| 72h | 980 | 309.317526 | 583.685339 | 937.192361 |
| 168h | 420 | 496.629154 | 942.435286 | 1493.35295 |

### Family classification

cost_verdict is derived, never authored: median move <= toll -> NOT_COST_COMPATIBLE; toll >= 50% of the median move -> COST_BOUNDARY; otherwise COST_COMPATIBLE. Only the *representative* horizon (the shortest one the family trades) decides, because that is where the toll bites hardest.

| family | horizon | median move bps | capture required | cost verdict | edge existence | windows below cost |
| --- | --- | --- | --- | --- | --- | --- |
| scalping | 5m | 8.588957 | 271.9% | **NOT_COST_COMPATIBLE** | NOT_DEMONSTRATED | 84.0% |
| intraday | 1h | 29.381129 | 79.5% | **COST_BOUNDARY** | NOT_DEMONSTRATED | 42.0% |
| mean_reversion | 4h | 60.466783 | 38.6% | **COST_COMPATIBLE** | NOT_DEMONSTRATED | 23.0% |
| momentum | 24h | 164.801314 | 14.2% | **COST_COMPATIBLE** | NOT_DEMONSTRATED | 9.8% |
| swing_trading | 72h | 309.317526 | 7.5% | **COST_COMPATIBLE** | NOT_DEMONSTRATED | 4.4% |
| trend_following | 168h | 496.629154 | 4.7% | **COST_COMPATIBLE** | NOT_DEMONSTRATED | 1.2% |

**A family that can cover commissions is not thereby validated.** no family has passed PROFITABILITY_GATE_V1 and none is claimed to have an edge; the three mechanisms RFC-046 tested produced +4.5306, -25.4580 and an unmeasured zero gross bps per trade.

## 5. RFC-046 evidence review (confirmations only)

| claim | confirmed | evidence |
| --- | --- | --- |
| CAND-046-001 has no gross edge out of sample | True | the aggregate positive gross is confined to development; the OOS leg is negative, so there is no gross edge to harvest out of sample |
| CAND-046-002 loses before costs | True | negative gross in every partition: an economic rejection, not a cost rejection |
| CAND-046-003 stays zero sample | True | unmeasured, neither disproved nor supported |

OOS reused for selection: False; frozen specs unchanged: True (n=3, hashes match the campaign record); new hypotheses generated: 0; second campaign: **NOT_AUTHORIZED**.

## 6. Decision

**VIABLE_COST_PROFILE_IDENTIFIED** — a cost profile exists under which the toll is small relative to the typical move available at the strategy's own horizon; it is a *cost* finding and says nothing about whether any edge exists.

| profile field | value |
| --- | --- |
| venue | BINANCE_SPOT_STANDARD_TAKER |
| product | Binance Spot, long/cash only |
| execution | market/taker on both legs (the cheapest permitted posture at VIP0) |
| round_trip_bps_at_200_usdt | 23.353553391 |
| minimum_gross_edge_bps | 23.353553391 |
| required_gross_edge_bps_at_1p5x | 35.030330086 |
| horizon_region | holding periods from about one day upwards, where the measured median move is at least seven times the toll |
| turnover_region | low: each round trip costs 0.467071068 USDT at full deployment, so the annual toll is roughly 0.852 x capital per round trip per day |

- cost-compatible families: mean_reversion, momentum, swing_trading, trend_following
- at the boundary: intraday
- not cost-compatible: scalping
- edge status: **NOT_DEMONSTRATED** — the recommendation bounds *economics*, it does not assert an edge

This recommendation is violated if:

- realised round-trip cost exceeds the modelled toll: every extra bps of realised cost is an extra bps of required gross edge, and ST-6 halts the campaign on exactly that
- the forward spread measurement contradicts the modelled 1.0 bps (SRC-07 has no historical endpoint, so the estimate is unverified until then)
- a candidate's holding horizon is shorter than its own measured cost-compatible region

## 7. Standing state (unchanged)

```text
DISCOVERY_CAMPAIGN_FAILED = True
NEXT_CAMPAIGN = NOT_AUTHORIZED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = FALSE
LIVE_TRADING = DISABLED
G_BUSINESS_REENTRY = NOT_PASS
RISK_ENGINE = DETERMINISTIC
FALSE_SUCCESS = 0
```

This artefact does not license: a second campaign or any new hypothesis; paper or live trading; any statement that an edge, a profit or a production capability exists; a cost-side change to the frozen model without a new measurement and a governance decision.
