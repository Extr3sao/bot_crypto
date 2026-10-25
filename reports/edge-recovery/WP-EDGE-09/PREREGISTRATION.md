# WP-EDGE-09C — pre-registration

> Fixed before the cross-section of this package was read, and bound by digest to the code that obeys it. `--check` re-renders this artifact from that code.

## 1. Universe, clock and thresholds

| | |
| --- | --- |
| Universe | BTCUSDT, ETHUSDT, SOLUSDT |
| Markets | spot, perp |
| Decision grid | 1 s |
| Microstructure horizons | [1, 5, 60] s |
| Frequency horizons | [1, 5, 60, 900, 3600] s |
| Minimum observations | 500 |
| Minimum |IC| | 0.01 |
| Admission safety multiple | 1.5x |
| ACTIVE target | 3.0 executed trades/day |
| QUALITY floor | 0.05 trades/day |

## 2. Tracks, kept apart

- **ACTIVE** — 1 s entries with intraday holds; the registered objective is three executed trades a day across the aggregate universe, never forced
- **QUALITY** — 5-minute to daily clock; its own floor is 0.05 trades a day and it is judged separately, never pooled with ACTIVE

## 3. The ladder, applied in order

| Filter | Name | Rule |
| --- | --- | --- |
| F0 | information | the feature must order the forward return (|Spearman IC| >= 0.01, n >= 500) |
| F1 | gross edge | mean gross move in bps must be positive on the pooled sample |
| F2 | cost survival | mean gross >= the measured round-trip cost of the venue/asset, in bps |
| F3 | admission margin | mean gross >= 1.5 x round-trip cost (the frozen safety multiple) |
| F4 | capacity | the measured book must absorb the order size inside the barrier; failing it is CAPACITY_KILLED |
| F5 | frequency | the structure must offer >= 3 executed opportunities per day (ACTIVE); failing it is FREQUENCY_KILLED |

## 4. Hypotheses, with the condition that kills each one

### `E-01` — quote imbalance is big enough to pay a taker round trip (ACTIVE)

- **Statement.** the book's own imbalance (bid vs ask size at the touch, and its change) predicts the mid move over 1/5/60 s by more than the venue's round-trip taker cost, so the prediction is executable by a taker order
- **Falsified if.** the best measured mean gross move at any horizon is below the measured round-trip cost for that asset
- **Data required.** forward book_ticker at quote level (no historical substitute exists)
- **Decided at.** F2/F3 (cost survival, admission margin)
- **Executable under this runtime.** True

### `E-02` — the fee schedule is the binding constraint, not the signal (CROSS-VENUE)

- **Statement.** the same measured gross move clears the barrier at a venue whose taker fee is lower, so the venue choice (not the model) is what blocks the edge
- **Falsified if.** no compared venue brings the round-trip cost at or below the measured gross move, including the venue with the lowest researched taker fee
- **Data required.** measured spread + the published fee schedules already registered
- **Decided at.** F2 (cost survival) with V3 venue scenarios
- **Executable under this runtime.** False
- **Note.** a venue change is a governance decision; this measures, it does not adopt

### `E-03` — the measured book can absorb our order size inside the barrier (ACTIVE)

- **Statement.** at the registered order size the captured book offers enough notional inside the barrier-implied impact, so the modelled cost is not a fiction
- **Falsified if.** the notional available within the barrier-implied price band is below the runtime's minimum order notional
- **Data required.** forward depth snapshots (10 levels) per symbol and market
- **Decided at.** F4 (capacity)
- **Executable under this runtime.** True

### `E-04` — open interest with price is exploitable on a slower clock (QUALITY)

- **Statement.** the quadrant 'price down and open interest up' carries a positive forward move large enough to pay the round trip at a 5-minute horizon
- **Falsified if.** no quadrant cell reaches a positive mean gross move at or above the round-trip cost, or the sample is below the registered floor
- **Data required.** forward open interest + mid at 5-minute resolution
- **Decided at.** F1/F2 with an explicit sample floor
- **Executable under this runtime.** True

### `E-05` — three executed trades a day is reachable by a positive structure (ACTIVE)

- **Statement.** a structure whose expected move clears the barrier occurs at least three times a day across the aggregate universe, so the ACTIVE objective is a strategy question and not an arithmetic impossibility
- **Falsified if.** the measured count of barrier-clearing opportunities per day is below the registered 3.0, no trade being forced to reach it
- **Data required.** the same quote panel, counted without a performance filter
- **Decided at.** F5 (frequency), on the pooled universe
- **Executable under this runtime.** True

### `E-06` — a taker entry pays no more than the measured spread and impact (EXECUTION)

- **Statement.** the price a taker order actually pays, measured against the mid at the decision instant, matches the modelled spread plus impact component, so the cost model is not systematically optimistic
- **Falsified if.** the measured execution shortfall exceeds the modelled spread+impact component by more than the published tolerance
- **Data required.** forward tape (agg_trade with aggressor side) + book_ticker
- **Decided at.** measured, then compared to the model; not an admission filter
- **Executable under this runtime.** True

### `E-07` — negative control: the pipeline does not manufacture an edge (GUARD)

- **Statement.** the identical pipeline, fed a feature destroyed by a deterministic shuffle inside each day, produces no cost-surviving edge
- **Falsified if.** the negative control reaches the positive classification, which would invalidate every other result in this package
- **Data required.** the same panel
- **Decided at.** must end COST_KILLED or NO_GROSS_EDGE or NO_INFORMATION
- **Executable under this runtime.** False
- **Note.** FALSE_SUCCESS guard: a positive control here stops the package

## 5. Holdouts this project has already spent

| Holder | What was spent | Evidence |
| --- | --- | --- |
| WP-EDGE-07 | the pre-registered decisive window of the EDGE-07 thrust book | `reports/edge-recovery/WP-EDGE-07/validation/VALIDATION.json` |
| WP-EDGE-08 | a cross-section of six symbols never measured before — symbols AAVEUSDT, UNIUSDT, KSMUSDT, SNXUSDT, CRVUSDT, SUSHIUSDT, window 2025-01-01..2026-10-14 (the decisive window, bars 1h/4h/1d) | `reports/edge-recovery/WP-EDGE-08/validation/VALIDATION.json` |

## 6. Bound code

| File | SHA-256 |
| --- | --- |
| `src/trading_bot/research/edge09/registration.py` | `bb5e2122c428682f…` |
| `src/trading_bot/research/edge09/panel.py` | `84615ea7a9d1d8dd…` |
| `src/trading_bot/research/edge09/gates.py` | `dd02afad054b4b09…` |
| `src/trading_bot/research/edge09/experiments.py` | `487feefab56b0339…` |
| `src/trading_bot/research/edge09/verdict.py` | `26f92198573edeb5…` |

## 7. What this package cannot say

- profitability of any book: promotion is NONE and no order is sent
- anything about liquidity outside the 4.16 h the forward capture covers
- anything about the perp trade flow: this environment delivered zero perp aggTrade messages (SRC-15/SRC-18) and the absence is declared, never substituted
- anything about realised maker fills: no venue in this project has a measured fill model
- anything about markets the runtime excludes (derivatives are information, not product)

`promotion: NONE`, `order_sent: False`.
