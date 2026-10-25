# WP-10 PHASE 1 — REAL ECONOMIC BASELINE

> `2026-10-11T22:35:56Z` · head `5348fcd55ab9ef404c676d8aada8daa8c85b9785` · **PARTIAL**

Period rebuilt from: `W1-W7 2026-03-01..2026-09-24` (207 days). The ledger is the register; the research artefacts are the values; nothing is copied.

## 1. The six headline numbers, rebuilt

| figure | published | rebuilt | agrees |
| --- | ---: | ---: | --- |
| strategies | 24 | 24 | True |
| admitted for paper | 0 | 0 | True |
| primary NO_GROSS_EDGE | 17 | 17 | True |
| primary COST_KILLED | 7 | 7 | True |
| best gross edge bps | 8.912 | 8.912 | True |
| admission round trip bps | 23.353553391 | 23.353553391 | True |

Best cell: `volatility@30m`. Positive zero-cost cells: 7 — `volatility@30m`, `volatility@1h`, `mean_reversion@30m`, `mean_reversion@15m`, `trend@30m`, `mean_reversion@5m`, `trend@15m`.

## 2. Common cost model versus each cell's own costs

* common model: **23.353553 bps**, one scenario applied to all 24 cells
  * `exchange_fee_entry` = 10.0000 bps (KNOWN)
  * `exchange_fee_exit` = 10.0000 bps (KNOWN)
  * `spread` = 1.0000 bps (ESTIMATED)
  * `slippage` = 2.2828 bps (ESTIMATED)
  * `market_impact` = 0.0707 bps (ESTIMATED)
* cells reporting their own fees: 24/24, fees range [9.9933, 10.0048] bps per trade
* cells reporting an implied slippage: range [1.276, 3.784] bps per trade
* cells publishing a drawdown: 0
* cells publishing an observed spread: 0

## 3. Every cell

| strategy | family | tf | status | gross bps | base net bps | fees bps | implied slip bps | trades | per day | CI95 half width bps |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `breakout@15m` | breakout | 15m | NO_GROSS_EDGE | -1.822 | -13.858 | 9.9999 | 2.036 | 2058 | 9.942 | 3.168101 |
| `breakout@1h` | breakout | 1h | NO_GROSS_EDGE | -0.222 | -12.068 | 10.0048 | 1.842 | 714 | 3.449 | 6.444677 |
| `breakout@30m` | breakout | 30m | NO_GROSS_EDGE | -1.792 | -13.068 | 9.9998 | 1.276 | 1285 | 6.208 | 4.430577 |
| `breakout@5m` | breakout | 5m | NO_GROSS_EDGE | -0.084007 | -12.544 | 9.9996 | None | 2426 | 11.72 | — |
| `ema_crossover@15m` | ema_crossover | 15m | NO_GROSS_EDGE | -1.122 | -13.282 | 9.9996 | 2.16 | 3166 | 15.295 | 2.367062 |
| `ema_crossover@1h` | ema_crossover | 1h | NO_GROSS_EDGE | -0.964 | -12.638 | 10.0002 | 1.674 | 2641 | 12.758 | 3.279934 |
| `ema_crossover@30m` | ema_crossover | 30m | NO_GROSS_EDGE | -0.726 | -12.176 | 9.9999 | 1.448 | 3233 | 15.618 | 2.685637 |
| `ema_crossover@5m` | ema_crossover | 5m | NO_GROSS_EDGE | -4.560812 | -16.222 | 9.9987 | None | 1725 | 8.333 | — |
| `mean_reversion@15m` | mean_reversion | 15m | COST_KILLED | 2.714 | -8.906 | 10.0004 | 1.62 | 1604 | 7.749 | 3.591391 |
| `mean_reversion@1h` | mean_reversion | 1h | NO_GROSS_EDGE | -2.226 | -14.398 | 9.9933 | 2.178 | 448 | 2.164 | 8.692807 |
| `mean_reversion@30m` | mean_reversion | 30m | COST_KILLED | 5.472 | -5.884 | 9.9989 | 1.356 | 935 | 4.517 | 5.272215 |
| `mean_reversion@5m` | mean_reversion | 5m | COST_KILLED | 1.485392 | -10.586 | 9.9992 | None | 3190 | 15.411 | — |
| `momentum@15m` | momentum | 15m | NO_GROSS_EDGE | -3.972 | -15.68 | 9.9995 | 1.708 | 3163 | 15.28 | 2.593819 |
| `momentum@1h` | momentum | 1h | NO_GROSS_EDGE | -2.334 | -14.026 | 10.0 | 1.692 | 2315 | 11.184 | 3.674085 |
| `momentum@30m` | momentum | 30m | NO_GROSS_EDGE | -2.612 | -14.516 | 10.0003 | 1.904 | 3001 | 14.498 | 2.931925 |
| `momentum@5m` | momentum | 5m | NO_GROSS_EDGE | -1.883531 | -13.788 | 9.9999 | None | 2526 | 12.203 | — |
| `trend@15m` | trend | 15m | COST_KILLED | 1.284 | -10.79 | 10.0012 | 2.074 | 1625 | 7.85 | 4.52761 |
| `trend@1h` | trend | 1h | NO_GROSS_EDGE | -1.252 | -12.742 | 9.9953 | 1.494 | 1407 | 6.797 | 5.370709 |
| `trend@30m` | trend | 30m | COST_KILLED | 2.206 | -9.458 | 9.9982 | 1.666 | 1575 | 7.609 | 4.771974 |
| `trend@5m` | trend | 5m | NO_GROSS_EDGE | -1.644771 | -13.616 | 10.0006 | None | 1291 | 6.237 | — |
| `volatility@15m` | volatility | 15m | NO_GROSS_EDGE | -7.064 | -18.908 | 10.0036 | 1.84 | 277 | 1.338 | 9.374829 |
| `volatility@1h` | volatility | 1h | COST_KILLED | 6.276 | -7.508 | 10.0 | 3.784 | 96 | 0.464 | 18.564808 |
| `volatility@30m` | volatility | 30m | COST_KILLED | 8.912 | -2.538 | 10.0041 | 1.444 | 196 | 0.947 | 12.009576 |
| `volatility@5m` | volatility | 5m | NO_GROSS_EDGE | -4.735385 | -16.524 | 10.0008 | None | 520 | 2.512 | — |

## 4. What the samples can resolve

A gross edge quoted to three decimals from a few hundred trades is not yet evidence. Using each cell's own win rate, average win and average loss, the two-point envelope gives the interval half width and the trade count a 23.35 bps effect would need:

| strategy | gross bps | CI95 half width bps | trades now | trades for 80 % power on 23.35 bps |
| --- | ---: | ---: | ---: | ---: |
| `volatility@1h` | 6.276 | 18.564808 | 96 | 124 |
| `volatility@30m` | 8.912 | 12.009576 | 196 | 106 |
| `volatility@15m` | -7.064 | 9.374829 | 277 | 92 |
| `mean_reversion@1h` | -2.226 | 8.692807 | 448 | 127 |
| `breakout@1h` | -0.222 | 6.444677 | 714 | 112 |
| `trend@1h` | -1.252 | 5.370709 | 1407 | 153 |
| `mean_reversion@30m` | 5.472 | 5.272215 | 935 | 98 |
| `trend@30m` | 2.206 | 4.771974 | 1575 | 135 |
| `trend@15m` | 1.284 | 4.52761 | 1625 | 125 |
| `breakout@30m` | -1.792 | 4.430577 | 1285 | 95 |
| `momentum@1h` | -2.334 | 3.674085 | 2315 | 118 |
| `mean_reversion@15m` | 2.714 | 3.591391 | 1604 | 78 |
| `ema_crossover@1h` | -0.964 | 3.279934 | 2641 | 107 |
| `breakout@15m` | -1.822 | 3.168101 | 2058 | 78 |
| `momentum@30m` | -2.612 | 2.931925 | 3001 | 97 |
| `ema_crossover@30m` | -0.726 | 2.685637 | 3233 | 88 |
| `momentum@15m` | -3.972 | 2.593819 | 3163 | 80 |
| `ema_crossover@15m` | -1.122 | 2.367062 | 3166 | 67 |

Cells whose 95 % interval is wider than their own measured edge: 16 of 18.

## 5. Declared discrepancies

| strategy | field | ledger | primary | source |
| --- | --- | ---: | ---: | --- |
| `breakout@5m` | expected_gross_edge_bps | -0.11 | -0.084007 | docs/STRATEGY_DISCOVERY_V3_RESULTS.json |
| `trend@5m` | expected_gross_edge_bps | -1.65 | -1.644771 | docs/STRATEGY_DISCOVERY_V3_RESULTS.json |
| `volatility@5m` | expected_gross_edge_bps | -4.73 | -4.735385 | docs/STRATEGY_DISCOVERY_V3_RESULTS.json |

Stake used: **500 USD**, recovered from the primary artefacts (per-trade USD / published bps, on cells that publish both); implied stakes 498.415605 – 500.939169 USD. the gross edge is linear in the stake, so the 0.5 % spread in the recovery moves the best cell by ~0.05 bps — two orders of magnitude below that cell's own sampling error.
The ledger's own bps figures imply a stake of 381.84816 – 500.333214 – 504.545455 USD: the ledger's own bps figures imply one stake to within its two-decimal rounding; the spread is a rounding artefact of the ledger, not a disagreement about the underlying measurement.

## 6. Checks and limitations

* [x] 24 cells rebuilt from the ledger
* [x] 0 admitted
* [x] 17 NO_GROSS_EDGE and 7 COST_KILLED re-derived, not copied
* [x] best gross edge rebuilt as 8.912 bps
* [x] admission round trip rebuilt as 23.3536 bps
* [x] the ledger's status of every cell equals the sign of its primary source value
* [x] every published headline number agrees with the rebuilt one
* [x] no frozen artefact is modified

* the gross edges are zero-cost research diagnostics over W1-W7 2026-03-01..2026-09-24; they are HISTORICAL_ESTIMATE, not forward evidence
* no cell publishes a drawdown or an observed spread, so two of the operator's requested columns are reported absent rather than filled
* the resolution envelope assumes a two-point win/loss model; it is an envelope for 'can this sample resolve the effect', never a measured dispersion
* admission checks c1..c9 were never applied at 15m/30m/1h, so the ledger's status is a cost classification, not a full admission verdict

