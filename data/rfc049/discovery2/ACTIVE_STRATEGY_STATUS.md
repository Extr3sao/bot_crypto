# RFC-049 DISCOVERY 2 — ACTIVE STRATEGY STATUS (AUDIT)

- generated: `2026-10-10T16:37:50Z` · head `2d113a0ae82f`
- method: tracked ledger + the live registry code path + the paper lane's own reports; nothing executed.

## What the pipeline admits today

- admission ledger: **24 strategies, 0 admitted for paper** (17 NO_GROSS_EDGE, 7 COST_KILLED).
- live registry: paper-executable on 5m/15m/1h: **NONE**; every refused strategy cites its ledger status.
- best measured family gross edge: **8.91 bps/trade** (zero-cost diagnostics) against a **23.353553391 bps** frozen round trip.

## Signal → proposal → authorization → execution

| stage | definition | current |
| --- | --- | ---: |
| signal generated | strategy evaluations per cycle | 12 |
| proposal | executable intent passing the admission gate | **0** |
| authorized | order authorization after risk review | **0** |
| executed | paper fills | **0** |

- every decision ends `NO_TRADE_STRATEGIC` by construction: the admission gate admits no strategy for paper execution, so every cycle ends in NO_TRADE_STRATEGIC

## Objective: three operations a day

- requirement: 1095 round trips/year at 23.353553391 bps per round trip = **25,572 bps** (255.7% of stake) per year in costs; the gross edge would have to average above 23.353553391 bps per trip.
- assessment: **NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE** — current operations/day: **0**.
- the objective is not a quota: no operation is generated to satisfy a frequency target.

## Low-frequency line

- the operator label `R6 P2 QUALITY` was searched for and **is not present** in the repository; if it denotes the low-frequency liquidity line (RFC-049 candidates: 2.96–6.18 round trips/year), it remains separate from the 3-ops/day objective and is untouched by this campaign.
