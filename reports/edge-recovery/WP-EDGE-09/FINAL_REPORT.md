# WP-EDGE-09 — final report

*One reading of the whole package at `2026-10-15T05:28:45Z` (`EDGE09-REPORT-20261015T052845Z`). Every figure comes from that reading; the documents are rendered from one dictionary.*

## 1. The verdict

**`NO_ECONOMIC_EDGE_FOUND`** — the forward quote data is real and usable, but no measured structure covers the 23-24 bps round trip: the best long-only gross is 1.582703 bps, the tape offers no barrier-clearing move at a 1 or 5 second horizon, and the cheapest registered venue still costs more than the measured gross

Adoption decision: **`DO_NOT_ADOPT`**. nothing measured here is adopted: no strategy, no parameter set and no venue change leaves this package. The RFC's success criterion is a better-founded research decision, and the founded decision is to adopt none of these arms.

The objective was economic: find an edge that survives the real cost barrier, the real liquidity and the real frequency, or say clearly that there is none. The answer is the second one, and it is measured rather than asserted.

| Question | Answer |
| --- | --- |
| What does one round trip cost on this venue? | 22.99-24.08 bps |
| How much of it is the fee? | 85.9% of the barrier |
| What is the best gross move the book's own imbalance ever measured? | 1.582703 bps |
| How often does the tape offer a barrier-clearing move at 1/5/60 s? | 1s: 0.0/day; 5s: 0.0/day; 60s: 48.018/day; 900s: 179.619/day; 3600s: 11.553/day |
| How often does the measured imbalance selector extract one? | 1s: 0.0/day long-only; 5s: 0.0/day long-only; 60s: 144.061/day long-only |
| Does a cheaper venue save it? | no: MEXC_SPOT_TAKER is the cheapest at 12.9866 bps, still above the best gross 1.582703 |
| Can the measured book absorb the quoted size? | yes for perp at the quoted size, spot rests on 3 snapshots only |

## 2. Why this is not a strategy failure

The gap is arithmetic at the short clock and informational at the long one. The barrier is 23-24 bps round trip and the fee alone is 20 of them; the best microstructure signal measured here is 1.582703 bps, and even at the cheapest registered schedule (MEXC_SPOT_TAKER) the round trip stays above it. At 1 and 5 seconds the tape itself never moves that far, so no selector could help there. At 60 seconds the tape does offer barrier-clearing moves, but the selector measured here extracts 1s: 0.0/day long-only; 5s: 0.0/day long-only; 60s: 144.061/day long-only, and its gross stays at 1.582703 bps against the same barrier: the long clock is not short of movement, it is short of a measured way to know which movement it is.

## 3. The data this rests on

- 10 streams, 95913 one-second rows, 16626886 quote events, 287946 trades.
- 10.14 h of forward capture held by this repository, 10 of 21 runs declaring lossy continuity.
- The perp trade flow was never captured in this environment: the stream delivered zero messages and the absence is declared, not substituted (SRC-15, SRC-18, re-probed here).

## 4. What would have to change for a next phase to have a chance

- a signal whose gross move is at least 35 bps at a horizon this tape can actually deliver, or
- a venue whose round trip is below the measured gross with the fee schedule confirmed rather than promotional, or
- a product this runtime can execute with a materially lower cost (which spot cannot offer at VIP0, since maker equals taker and the maker gate already failed).

## 5. Open items

- no microstructure signal measured here approaches the barrier; the gap is arithmetic (fee 20 of 23-24 bps), so the next attempt needs a different product or a different venue, not another indicator — *quant-researcher: product and venue, not parameters*
- the perp trade flow was never captured in this environment; any hypothesis that needs it stays unmeasurable until the environment delivers that stream — *observability-engineer: capture capability, declared as unavailable*
- spot depth snapshots are rare in the current capture (3-4 per symbol), so the spot capacity claim is thin and should be re-measured with a denser snapshot cadence — *observability-engineer: snapshot cadence*
- no maker fill model exists, so the passive side of every venue stays unscored; with maker below taker only outside Binance, that is where a cost advantage would have to come from — *execution-engineer: a measured maker model*

## 6. What this does not do

- profitability of any book: promotion is NONE and no order is sent
- anything about liquidity outside the 4.16 h the forward capture covers
- anything about the perp trade flow: this environment delivered zero perp aggTrade messages (SRC-15/SRC-18) and the absence is declared, never substituted
- anything about realised maker fills: no venue in this project has a measured fill model
- anything about markets the runtime excludes (derivatives are information, not product)
- the capture spans hours across a handful of days, so a rate per day is an extrapolation from a short sample and is reported with its span
- no venue in this project has a measured maker fill model, so a passive product cannot be scored here at all

`promotion: NONE`, `order_sent: False`, `FALSE_SUCCESS: 0`.
