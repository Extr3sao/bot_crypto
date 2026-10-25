# WP-10 E-1 — EXECUTION COST DISTRIBUTION

> `2026-10-12T06:07:11Z` · head `90ed615b1b2514682bbf9a85834fdd81c45f0774` · **PLANE_OVERSTATES_MICROSTRUCTURE**

Sealed forward window `paper-lab-continuous-02`: 2026-09-29T22:59:18.288000+00:00 → 2026-09-30T03:08:51.773000+00:00 (4.159301 h), status `CONTROLLED_STOP`, stop reason `disk budget`, continuity `INCOMPLETE_DATA`, 67 gaps, replay `ok`.

## 1. The plane under test

`BINANCE_SPOT_STANDARD_TAKER` at 200 USDT = **23.353553 bps**, re-derived in-process from COST_MODEL_V3 and equal to the published frozen value: `True`.

| component | bps | class | what it is |
| --- | ---: | --- | --- |
| `exchange_fee_entry` | 10.0000 | KNOWN | VIP0 (regular user, 30d volume < 1,000,000 USD), pay in quote_asset |
| `exchange_fee_exit` | 10.0000 | KNOWN | VIP0 (regular user, 30d volume < 1,000,000 USD), pay in quote_asset |
| `spread` | 1.0000 | ESTIMATED | 2 taker leg(s) x half-spread |
| `slippage` | 2.2828 | ESTIMATED | base 1.0 bps x liq 1.0 x size 1.141 x vol 1.000 |
| `market_impact` | 0.0707 | ESTIMATED | size-driven displacement above the base slippage |

Under test: **1.0 bps** of spread and **2.353554 bps** of slippage+impact, both `ESTIMATED`; **20.0 bps** of fees are `KNOWN` (85.64 % of the plane).

## 2. The spread that was actually quoted

| book | checkpoints reproduced | spread median | p05 | p95 | max (bps) |
| --- | ---: | ---: | ---: | ---: | ---: |
| spot/BTCUSDT | 496/496 | 0.001198 | 0.001194 | 0.0012 | 0.0012 |
| spot/ETHUSDT | 496/496 | 0.037406 | 0.037237 | 0.037472 | 0.037501 |
| perp/BTCUSDT | 496/496 | 0.011986 | 0.01194 | 0.012002 | 0.01201 |
| perp/ETHUSDT | 496/496 | 0.037427 | 0.037253 | 0.037493 | 0.075008 |

## 3. What a market order would have paid, size by size

Round trip = entry and exit swept through the rebuilt book, both measured against the checkpoint mid; spread legs and walk legs are its two parts.

| book | size | checkpoints | round trip median | p95 | worst | spread legs median | walk legs median | unfillable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| spot/BTCUSDT | 50 | 496 | 0.001198 | 0.0012 | 0.0012 | 0.001198 | 0.0 | 0 |
| spot/BTCUSDT | 200 | 496 | 0.001198 | 0.0012 | 0.0012 | 0.001198 | 0.0 | 0 |
| spot/BTCUSDT | 1000 | 496 | 0.001198 | 0.0012 | 0.037518 | 0.001198 | 0.0 | 0 |
| spot/BTCUSDT | 5000 | 496 | 0.001198 | 0.002158 | 0.228127 | 0.001198 | 0.0 | 0 |
| spot/BTCUSDT | 20000 | 496 | 0.001198 | 0.357218 | 0.679873 | 0.001198 | 0.0 | 0 |
| spot/BTCUSDT | 100000 | 496 | 0.038679 | 0.930928 | 1.406256 | 0.001198 | 0.037486 | 0 |
| spot/ETHUSDT | 50 | 496 | 0.037406 | 0.037472 | 0.070853 | 0.037406 | 0.0 | 0 |
| spot/ETHUSDT | 200 | 496 | 0.037407 | 0.037474 | 0.367989 | 0.037406 | 0.0 | 0 |
| spot/ETHUSDT | 1000 | 496 | 0.037408 | 0.037483 | 0.737891 | 0.037406 | 0.0 | 0 |
| spot/ETHUSDT | 5000 | 496 | 0.037411 | 0.344453 | 1.377934 | 0.037406 | 0.0 | 0 |
| spot/ETHUSDT | 20000 | 496 | 0.037431 | 0.731127 | 1.889046 | 0.037406 | 0.0 | 0 |
| spot/ETHUSDT | 100000 | 496 | 0.685416 | 1.60359 | 2.492082 | 0.037406 | 0.647992 | 0 |
| perp/BTCUSDT | 50 | 496 | 0.011986 | 0.012002 | 0.01201 | 0.011986 | 0.0 | 0 |
| perp/BTCUSDT | 200 | 496 | 0.011986 | 0.012002 | 0.01201 | 0.011986 | 0.0 | 0 |
| perp/BTCUSDT | 1000 | 496 | 0.011986 | 0.012002 | 0.020976 | 0.011986 | 0.0 | 0 |
| perp/BTCUSDT | 5000 | 496 | 0.011986 | 0.012003 | 0.259042 | 0.011986 | 0.0 | 0 |
| perp/BTCUSDT | 20000 | 496 | 0.011987 | 0.040704 | 0.516034 | 0.011986 | 0.0 | 0 |
| perp/BTCUSDT | 100000 | 496 | 0.011991 | 0.478495 | 1.099795 | 0.011986 | 0.0 | 0 |
| perp/ETHUSDT | 50 | 496 | 0.037427 | 0.037493 | 0.075008 | 0.037427 | 0.0 | 0 |
| perp/ETHUSDT | 200 | 496 | 0.037427 | 0.037493 | 0.102666 | 0.037427 | 0.0 | 0 |
| perp/ETHUSDT | 1000 | 496 | 0.037427 | 0.037493 | 0.171619 | 0.037427 | 0.0 | 0 |
| perp/ETHUSDT | 5000 | 496 | 0.037427 | 0.037503 | 0.395395 | 0.037427 | 0.0 | 0 |
| perp/ETHUSDT | 20000 | 496 | 0.037432 | 0.278908 | 0.640033 | 0.037427 | 0.0 | 0 |
| perp/ETHUSDT | 100000 | 496 | 0.037486 | 0.831377 | 1.242005 | 0.037427 | 0.0 | 0 |

## 4. What real takers actually paid

| book | prints joined | effective half spread median | p95 | round trip | print notional median USDT | >1000 USDT | look-ahead violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| spot/BTCUSDT | 91389 | 0.032853 | 1.445401 | 0.065705 | 63.653124 | 18.5777 % | 0 |
| spot/ETHUSDT | 72269 | 0.243592 | 2.29316 | 0.487184 | 35.482538 | 13.6864 % | 0 |

## 5. Conditions of execution

* `perp/BTCUSDT/book_ticker` network delay ms: median 187.0, p95 5151.0, max 23106.0 (n=466290)
* `perp/ETHUSDT/book_ticker` network delay ms: median 162.0, p95 5915.0, max 23105.0 (n=359106)
* `spot/BTCUSDT/agg_trade` network delay ms: median 113.0, p95 381.0, max 22419.0 (n=9392)
* `spot/ETHUSDT/agg_trade` network delay ms: median 116.0, p95 502.65, max 22543.0 (n=7128)
* perp funding bps per interval: median 0.5985, p95 0.850365, max 0.8662 (n=488)
* mark price rows 488, open interest rows 488

## 6. The move the cost has to be paid out of

| book | horizon | independent windows | values (bps) |
| --- | ---: | ---: | --- |
| spot/BTCUSDT | 5 min | 49 | 14.21, 5.21, 8.59, 3.33, 10.26, 3.23, 5.78, 0.64, 6.69, 5.63, 7.42, 2.23, 2.23, 6.10, 7.77, 10.87, 4.29, 12.46, 6.39, 15.65, 1.25, 10.20, 2.54, 7.95, 4.07, 5.27, 3.59, 3.25, 17.40, 22.02, 1.68, 0.48, 11.04, 0.24, 1.20, 3.54, 9.16, 6.08, 0.97, 13.76, 10.75, 7.43, 10.55, 14.87, 5.51, 6.00, 4.07, 5.04, 3.60 |
| spot/BTCUSDT | 30 min | 8 | 17.64, 11.39, 10.24, 15.32, 10.30, 11.94, 6.90, 1.20 |
| spot/ETHUSDT | 5 min | 49 | 15.18, 1.97, 9.76, 11.27, 13.78, 1.16, 7.35, 2.39, 7.58, 5.79, 5.49, 1.12, 2.24, 8.78, 11.59, 7.26, 3.37, 16.19, 10.02, 18.31, 2.13, 7.83, 6.78, 5.99, 0.90, 7.71, 7.22, 0.45, 18.22, 26.71, 0.26, 1.01, 11.72, 1.80, 5.91, 8.27, 3.29, 6.13, 3.22, 12.31, 6.82, 6.70, 5.51, 18.97, 1.95, 11.07, 2.35, 6.13, 4.26 |
| spot/ETHUSDT | 30 min | 8 | 3.28, 11.12, 17.07, 5.50, 7.60, 14.61, 19.07, 22.00 |
| perp/BTCUSDT | 5 min | 49 | 14.11, 5.63, 8.88, 4.93, 10.66, 4.06, 5.98, 1.21, 6.41, 5.66, 8.50, 2.55, 1.39, 7.97, 6.75, 11.04, 3.89, 12.83, 7.12, 15.89, 1.69, 10.52, 2.06, 8.38, 3.15, 4.40, 1.86, 4.41, 18.02, 21.14, 2.88, 0.11, 11.98, 1.45, 0.73, 0.76, 11.19, 5.94, 0.36, 12.64, 10.09, 5.89, 11.77, 15.79, 5.04, 5.60, 5.19, 4.97, 3.42 |
| perp/BTCUSDT | 30 min | 8 | 17.09, 11.48, 10.45, 14.68, 8.19, 7.56, 4.88, 2.03 |
| perp/ETHUSDT | 5 min | 49 | 14.55, 1.01, 9.28, 10.87, 14.64, 0.04, 8.21, 3.40, 8.25, 5.83, 6.27, 1.68, 1.87, 10.16, 10.96, 7.53, 3.22, 15.14, 11.45, 18.17, 1.69, 9.44, 7.31, 7.49, 0.34, 7.19, 4.86, 2.58, 18.72, 24.89, 2.66, 1.27, 12.82, 0.22, 5.43, 4.38, 7.45, 6.55, 3.14, 12.69, 5.96, 4.91, 5.74, 19.32, 2.32, 10.89, 2.50, 6.25, 4.53 |
| perp/ETHUSDT | 30 min | 8 | 2.69, 11.83, 18.60, 3.07, 6.81, 8.05, 14.86, 22.08 |

## 7. Verdict

* state: **PLANE_OVERSTATES_MICROSTRUCTURE**
* observed / estimated microstructure: 0.007364 (0.024697 bps vs 3.353554 bps)
* spread observed / plane: 0.024696; walk observed / plane: 0.0
* worst book p95 0.037493 bps, worst single checkpoint 0.367989 bps — the plane is not uniformly generous
* best gross edge in the 24-strategy ledger: 8.912 bps; clears the KNOWN fee legs alone: `False`

the measured microstructure cost cannot promote a rejected strategy by itself: the two fee legs are KNOWN from the published schedule and on their own exceed the best gross edge in the 24-strategy ledger (8.912 bps). Cheaper execution narrows the bar; it does not clear it

## 8. Fee schedules the measured window did not change

| scenario | source | maker bps | taker bps |
| --- | --- | ---: | ---: |
| `BINANCE_SPOT_STANDARD_TAKER` | SRC-01 | 10.0 | 10.0 |
| `BINANCE_USDM_STANDARD_TAKER` | SRC-02 | 2.0 | 5.0 |

These are published facts, recorded here as context for where a cheaper execution could come from. Moving the admission plane onto one of them is a governance decision, not a measurement result, and E-1 does not make it.

## 9. Checks and limitations

* [x] sealed manifest present for the analysed run
* [x] replay verification ok and network-free
* [x] rebuilt top of book equals every published checkpoint
* [x] no trade was joined to a quote from the future
* [x] the plane re-derives to the published frozen value
* [x] measured cost carries the OBSERVED_FORWARD label and never replaces ESTIMATED without the plane being changed by governance
* [x] no admission, promotion or plane change is performed
* [x] every measured size reports how many checkpoints priced it
* [x] truncated segment tails are reported rather than skipped silently

* one sealed window of 4.159301 h in a single session regime
* BTC and ETH only: no SOL book exists in this seal, so no cross-asset generality
* the seal stopped on its own 800 MB disk valve, not because a measurement ended
* spot book_ticker rows carry no exchange event time, so the quote clock there is the receive clock; that is later than the event, never earlier, so it cannot create look-ahead
* the walked depth is what the venue streamed, not the venue's whole book; a size that clears the last recorded level is reported unfillable rather than extrapolated
* the measured ladder is a static snapshot walk: a real order arrives at a moving book, and the latency in section 5 is the size of that motion
* this is a cost measurement, not a profitability result: RESEARCH_RESULT only

