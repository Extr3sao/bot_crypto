# COST-BARRIER EXPLORER - per venue and per horizon

- generated `2026-10-11T09:11:06Z` · head `dfeb140f2572` · branch `main`
- mode: OFFLINE read-only: no keys, no orders, no capital, no live path
- cells: 24 · venue configurations: 120 · checks: 24/24 pass

## 1. Headline

- best structural edge (zero-cost gross): **8.912 bps**
- cheapest round trip **without** any assumed component: **12.1768 bps** (BINANCE_USDM_PERP_TAKER, taker, 200 USD, deep)
- cheapest line **anywhere** in the model: **1.25 bps** (MEXC_SPOT_TAKER, maker)
- cells reachable on an observed-only line: **0** of 24
- cells reachable once assumed maker-fill components are admitted: **7** of 24

The whole cost surface is therefore split in two: execution that is *priced* by observed components cannot carry any cell, and the only lines that can carry a cell are the ones whose honesty depends on an unmodelled maker fill / adverse-selection assumption.

## 2. Horizon: what holding time does to the barrier

**Model horizon - HORIZON_INVARIANT_AT_ZERO_FUNDING.** Measured on 20 (scenario, execution mode) pairs across 5m 15m 25m 60m 120m 240m 480m 1440m:

- all 20 pairs are exactly flat: max - min = 0.0 bps

The round trip is a per-execution quantity: with a zero funding rate the model's price does not move across five minutes or a day. Horizon enters the barrier in exactly one place, and it is not a strategy parameter.

**Funding horizon - perpetuals only** (funding interval 480 min, derived from the model, not typed). Carry = rate x horizon / interval, verified against the model on 96 rows.

| scenario | mode | rate (bps/8h) | horizon | carry bps | round trip bps |
| --- | --- | --- | --- | --- | --- |
| BINANCE_USDM_PERP_MAKER | taker | 0.25 | 240m | 0.125 | 13.4786 |
| BINANCE_USDM_PERP_MAKER | taker | 0.25 | 1440m | 0.75 | 14.1036 |
| BINANCE_USDM_PERP_MAKER | taker | 1.0 | 240m | 0.5 | 13.8536 |
| BINANCE_USDM_PERP_MAKER | taker | 1.0 | 1440m | 3 | 16.3536 |
| BINANCE_USDM_PERP_MAKER | taker | 3.0 | 240m | 1.5 | 14.8536 |
| BINANCE_USDM_PERP_MAKER | taker | 3.0 | 1440m | 9 | 22.3536 |
| BINANCE_USDM_PERP_MAKER | maker | 0.25 | 240m | 0.125 | 9.375 |
| BINANCE_USDM_PERP_MAKER | maker | 0.25 | 1440m | 0.75 | 10 |
| BINANCE_USDM_PERP_MAKER | maker | 1.0 | 240m | 0.5 | 9.75 |
| BINANCE_USDM_PERP_MAKER | maker | 1.0 | 1440m | 3 | 12.25 |
| BINANCE_USDM_PERP_MAKER | maker | 3.0 | 240m | 1.5 | 10.75 |
| BINANCE_USDM_PERP_MAKER | maker | 3.0 | 1440m | 9 | 18.25 |
| BINANCE_USDM_PERP_TAKER | taker | 0.25 | 240m | 0.125 | 13.4786 |
| BINANCE_USDM_PERP_TAKER | taker | 0.25 | 1440m | 0.75 | 14.1036 |
| BINANCE_USDM_PERP_TAKER | taker | 1.0 | 240m | 0.5 | 13.8536 |
| BINANCE_USDM_PERP_TAKER | taker | 1.0 | 1440m | 3 | 16.3536 |
| BINANCE_USDM_PERP_TAKER | taker | 3.0 | 240m | 1.5 | 14.8536 |
| BINANCE_USDM_PERP_TAKER | taker | 3.0 | 1440m | 9 | 22.3536 |
| BINANCE_USDM_PERP_TAKER | maker | 0.25 | 240m | 0.125 | 9.375 |
| BINANCE_USDM_PERP_TAKER | maker | 0.25 | 1440m | 0.75 | 10 |
| BINANCE_USDM_PERP_TAKER | maker | 1.0 | 240m | 0.5 | 9.75 |
| BINANCE_USDM_PERP_TAKER | maker | 1.0 | 1440m | 3 | 12.25 |
| BINANCE_USDM_PERP_TAKER | maker | 3.0 | 240m | 1.5 | 10.75 |
| BINANCE_USDM_PERP_TAKER | maker | 3.0 | 1440m | 9 | 18.25 |

Holding budget: how long the best measured edge survives funding carry on a perpetual

| funding rate (bps/8h) | hours until carry alone consumes 8.912 bps |
| --- | --- |
| 0.25 | 285.18 |
| 1.0 | 71.3 |
| 3.0 | 23.77 |

**Market horizon - how long the market itself needs to move the cost line.** Source definition: *bars_to_X = median bars for a move equal to X bps*.

| timeframe | asset | median bar move (bps) | bars to BASE | hours to BASE | bars to 2X | hours to 2X |
| --- | --- | --- | --- | --- | --- | --- |
| 5m | BTC | 6.83 | 1.8 | 0.15 | 3.5 | 0.29 |
| 5m | ETH | 8.6 | 1.4 | 0.12 | 2.8 | 0.23 |
| 5m | SOL | 10.45 | 1.1 | 0.09 | 2.2 | 0.18 |
| 15m | BTC | 9.38 | 1.3 | 0.32 | 2.6 | 0.64 |
| 15m | ETH | 11.67 | 1.0 | 0.26 | 2.1 | 0.51 |
| 15m | SOL | 14.0 | 0.8 | 0.21 | 1.7 | 0.42 |
| 30m | BTC | 13.26 | 0.9 | 0.45 | 1.8 | 0.9 |
| 30m | ETH | 15.99 | 0.7 | 0.37 | 1.5 | 0.75 |
| 30m | SOL | 19.74 | 0.6 | 0.3 | 1.2 | 0.6 |
| 1h | BTC | 18.62 | 0.6 | 0.64 | 1.3 | 1.29 |
| 1h | ETH | 23.21 | 0.5 | 0.52 | 1.0 | 1.03 |
| 1h | SOL | 27.51 | 0.4 | 0.43 | 0.9 | 0.86 |

Worst-asset median bar move by timeframe: 15m=9.38, 1h=18.62, 30m=13.26, 5m=6.83 bps. The base line is 12.0 bps, so the market's own amplitude only reaches it from 30m upward; at 5m and 15m the median bar does not pay a single round trip. Published medians that exceed the cheapest *executable* line: 15m/SOL, 1h/BTC, 1h/ETH, 1h/SOL, 30m/BTC, 30m/ETH, 30m/SOL. Amplitude is therefore not the free variable - capture per execution is.

## 3. Venue frontier

One row per (scenario, execution mode, size). `bps` columns are the round trip by liquidity regime; `reach@1x` columns are how many of the 24 cells that exact line carries.

| scenario | mode | size | deep bps | normal bps | thin bps | class | reach@1x deep | reach@1x normal | reach@1x thin |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BINANCE_SPOT_BNB_MAKER | taker | 200 | 17.1768 | 18.3536 | 21.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_MAKER | taker | 1000 | 17.3953 | 18.7906 | 22.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_MAKER | maker | 200 | 31.25 | 31.25 | 31.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_MAKER | maker | 1000 | 31.25 | 31.25 | 31.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_TAKER | taker | 200 | 17.1768 | 18.3536 | 21.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_TAKER | taker | 1000 | 17.3953 | 18.7906 | 22.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_TAKER | maker | 200 | 31.25 | 31.25 | 31.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_BNB_TAKER | maker | 1000 | 31.25 | 31.25 | 31.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_MAKER | taker | 200 | 22.1768 | 23.3536 | 26.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_MAKER | taker | 1000 | 22.3953 | 23.7906 | 27.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_MAKER | maker | 200 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_MAKER | maker | 1000 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_TAKER | taker | 200 | 22.1768 | 23.3536 | 26.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_TAKER | taker | 1000 | 22.3953 | 23.7906 | 27.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_TAKER | maker | 200 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_SPOT_STANDARD_TAKER | maker | 1000 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_MAKER | taker | 200 | 12.1768 | 13.3536 | 16.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_MAKER | taker | 1000 | 12.3953 | 13.7906 | 17.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_MAKER | maker | 200 | 9.25 | 9.25 | 9.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_MAKER | maker | 1000 | 9.25 | 9.25 | 9.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_TAKER | taker | 200 | 12.1768 | 13.3536 | 16.8839 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_TAKER | taker | 1000 | 12.3953 | 13.7906 | 17.9764 | ESTIMATED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_TAKER | maker | 200 | 9.25 | 9.25 | 9.25 | ASSUMED | 0 | 0 | 0 |
| BINANCE_USDM_PERP_TAKER | maker | 1000 | 9.25 | 9.25 | 9.25 | ASSUMED | 0 | 0 | 0 |
| BYBIT_SPOT_TAKER | taker | 200 | 22.1768 | 23.3536 | 26.8839 | ESTIMATED | 0 | 0 | 0 |
| BYBIT_SPOT_TAKER | taker | 1000 | 22.3953 | 23.7906 | 27.9764 | ESTIMATED | 0 | 0 | 0 |
| BYBIT_SPOT_TAKER | maker | 200 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| BYBIT_SPOT_TAKER | maker | 1000 | 41.25 | 41.25 | 41.25 | ASSUMED | 0 | 0 | 0 |
| KRAKENPRO_SPOT_TAKER | taker | 200 | 82.1768 | 83.3536 | 86.8839 | ESTIMATED | 0 | 0 | 0 |
| KRAKENPRO_SPOT_TAKER | taker | 1000 | 82.3953 | 83.7906 | 87.9764 | ESTIMATED | 0 | 0 | 0 |
| KRAKENPRO_SPOT_TAKER | maker | 200 | 101.25 | 101.25 | 101.25 | ASSUMED | 0 | 0 | 0 |
| KRAKENPRO_SPOT_TAKER | maker | 1000 | 101.25 | 101.25 | 101.25 | ASSUMED | 0 | 0 | 0 |
| MEXC_SPOT_TAKER | taker | 200 | 16.1768 | 17.3536 | 20.8839 | ESTIMATED | 0 | 0 | 0 |
| MEXC_SPOT_TAKER | taker | 1000 | 16.3953 | 17.7906 | 21.9764 | ESTIMATED | 0 | 0 | 0 |
| MEXC_SPOT_TAKER | maker | 200 | 1.25 | 1.25 | 1.25 | ASSUMED | 7 | 7 | 7 |
| MEXC_SPOT_TAKER | maker | 1000 | 1.25 | 1.25 | 1.25 | ASSUMED | 7 | 7 | 7 |
| OKX_SPOT_TAKER | taker | 200 | 22.1768 | 23.3536 | 26.8839 | ESTIMATED | 0 | 0 | 0 |
| OKX_SPOT_TAKER | taker | 1000 | 22.3953 | 23.7906 | 27.9764 | ESTIMATED | 0 | 0 | 0 |
| OKX_SPOT_TAKER | maker | 200 | 33.25 | 33.25 | 33.25 | ASSUMED | 0 | 0 | 0 |
| OKX_SPOT_TAKER | maker | 1000 | 33.25 | 33.25 | 33.25 | ASSUMED | 0 | 0 | 0 |

Post-only direction, measured per venue:

| scenario | taker bps | maker bps | maker - taker | direction |
| --- | --- | --- | --- | --- |
| BINANCE_SPOT_BNB_MAKER | 18.3536 | 31.25 | 12.8964 | maker_dearer |
| BINANCE_SPOT_BNB_TAKER | 18.3536 | 31.25 | 12.8964 | maker_dearer |
| BINANCE_SPOT_STANDARD_MAKER | 23.3536 | 41.25 | 17.8964 | maker_dearer |
| BINANCE_SPOT_STANDARD_TAKER | 23.3536 | 41.25 | 17.8964 | maker_dearer |
| BINANCE_USDM_PERP_MAKER | 13.3536 | 9.25 | -4.1036 | maker_cheaper |
| BINANCE_USDM_PERP_TAKER | 13.3536 | 9.25 | -4.1036 | maker_cheaper |
| BYBIT_SPOT_TAKER | 23.3536 | 41.25 | 17.8964 | maker_dearer |
| KRAKENPRO_SPOT_TAKER | 83.3536 | 101.25 | 17.8964 | maker_dearer |
| MEXC_SPOT_TAKER | 17.3536 | 1.25 | -16.1036 | maker_cheaper |
| OKX_SPOT_TAKER | 23.3536 | 33.25 | 9.8964 | maker_dearer |

## 4. Cells

| cell | ledger | gross bps | verdict | cheapest line cleared | best configuration |
| --- | --- | --- | --- | --- | --- |
| breakout@15m | NO_GROSS_EDGE | -1.822 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.072 bps) |
| breakout@1h | NO_GROSS_EDGE | -0.222 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-1.472 bps) |
| breakout@30m | NO_GROSS_EDGE | -1.792 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.042 bps) |
| breakout@5m | NO_GROSS_EDGE | -0.084 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-1.334 bps) |
| ema_crossover@15m | NO_GROSS_EDGE | -1.122 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-2.372 bps) |
| ema_crossover@1h | NO_GROSS_EDGE | -0.964 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-2.214 bps) |
| ema_crossover@30m | NO_GROSS_EDGE | -0.726 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-1.976 bps) |
| ema_crossover@5m | NO_GROSS_EDGE | -4.5608 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-5.8108 bps) |
| mean_reversion@15m | COST_KILLED | 2.714 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (1.464 bps) |
| mean_reversion@1h | NO_GROSS_EDGE | -2.226 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.476 bps) |
| mean_reversion@30m | COST_KILLED | 5.472 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (4.222 bps) |
| mean_reversion@5m | COST_KILLED | 1.4854 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (0.2354 bps) |
| momentum@15m | NO_GROSS_EDGE | -3.972 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-5.222 bps) |
| momentum@1h | NO_GROSS_EDGE | -2.334 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.584 bps) |
| momentum@30m | NO_GROSS_EDGE | -2.612 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.862 bps) |
| momentum@5m | NO_GROSS_EDGE | -1.8835 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-3.1335 bps) |
| trend@15m | COST_KILLED | 1.284 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (0.034 bps) |
| trend@1h | NO_GROSS_EDGE | -1.252 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-2.502 bps) |
| trend@30m | COST_KILLED | 2.206 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (0.956 bps) |
| trend@5m | NO_GROSS_EDGE | -1.6448 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-2.8948 bps) |
| volatility@15m | NO_GROSS_EDGE | -7.064 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-8.314 bps) |
| volatility@1h | COST_KILLED | 6.276 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (5.026 bps) |
| volatility@30m | COST_KILLED | 8.912 | REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL | 1.25 | MEXC_SPOT_TAKER/maker/2 USD/deep (7.662 bps) |
| volatility@5m | NO_GROSS_EDGE | -4.7354 | NOT_REACHABLE_AT_ANY_MODELED_VENUE | n/a | MEXC_SPOT_TAKER/maker/2 USD/deep (-5.9854 bps) |

## 5. What the 3-operations-per-day objective costs

| line | round trip bps | trips/yr | annual cost bps | annual cost % of stake |
| --- | --- | --- | --- | --- |
| campaign_runtime_admission | 23.3536 | 1095 | 25572.1 | 255.72 |
| research_base | 12 | 1095 | 13140 | 131.4 |
| cheapest_taker_observed | 12.1768 | 1095 | 13333.6 | 133.34 |
| cheapest_any_assumed | 1.25 | 1095 | 1368.8 | 13.69 |

## 6. Checks and governance

**24/24 checks pass; checks_failed = 0.**

- `PASS` audit:payload_sha256_reproduces - recomputed 355d018b34a05a7c vs stored 355d018b34a05a7c
- `PASS` sources:all_present - data/recovery/ACTIVE_ECONOMIC_AUDIT.json=ok, reports/strategy-baseline/COST_BARRIER.json=ok, config/strategy_admission.json=ok, docs/COST_MODEL_V3.json=ok, src/trading_bot/research/microstructure/cost_model_v3.py=ok
- `PASS` cells:count_matches_audit - 24 cells vs strategy_count 24
- `PASS` cells:gross_positive_set_matches_audit_aggregates - derived ['mean_reversion@15m', 'mean_reversion@30m', 'mean_reversion@5m', 'trend@15m', 'trend@30m', 'volatility@1h', 'volatility@30m'] vs declared ['mean_reversion@15m', 'mean_reversion@30m', 'mean_reversion@5m', 'trend@15m', 'trend@30m', 'volatility@1h', 'volatility@30m']
- `PASS` cells:no_gross_invented - every cell gross is the audit's own published value, compared exactly
- `PASS` campaign:cost_line_reproduces - derived 23.353553390593273 vs frozen 23.353553391 vs audit 23.353553390593273
- `PASS` campaign:stress_line_reproduces - derived 35.03033008588991 vs frozen 35.030330086
- `PASS` source:research_base_agrees_across_sources - COST_BARRIER BASE=12.0 and every audit cell agree on 12.0
- `PASS` horizon:zero_funding_is_flat - every scenario is exactly flat across the horizon grid: max-min = 0.0 bps
- `PASS` horizon:funding_is_only_ever_passed_to_perpetuals - funding-applicable scenarios ['BINANCE_USDM_PERP_MAKER', 'BINANCE_USDM_PERP_TAKER']; probe: a spot scenario given a funding rate would add 3.0 bps of carry (model_guarded=False), so the caller is the guard
- `PASS` horizon:funding_carry_matches_analytic_form - max |model - rate*horizon/480.0| = 0.0 bps over 96 rows
- `PASS` horizon:market_time_to_cover_covers_every_cell_timeframe - cells timeframes ['15m', '1h', '30m', '5m'] vs published ['15m', '1h', '30m', '5m']
- `PASS` monotonic:cost_non_decreasing_in_size - round trip at 1000 USD >= at 200 USD for every scenario, mode and liquidity regime
- `PASS` monotonic:cost_non_decreasing_as_liquidity_worsens - deep <= normal <= thin for every scenario, mode and size
- `PASS` scenarios:taker_maker_spec_pairs_are_cost_identical_for_equal_order_types - 3 spec pair(s) differ only in the fee the execution mode does not use, so the grid carries 36 distinct lines across 120 configurations
- `PASS` structure:maker_price_direction_is_measured_not_assumed - both directions occur across the 9 scenarios (BINANCE_SPOT_BNB_MAKER=maker_dearer, BINANCE_SPOT_BNB_TAKER=maker_dearer, BINANCE_SPOT_STANDARD_MAKER=maker_dearer, BINANCE_SPOT_STANDARD_TAKER=maker_dearer, BINANCE_USDM_PERP_MAKER=maker_cheaper, BINANCE_USDM_PERP_TAKER=maker_cheaper, BYBIT_SPOT_TAKER=maker_dearer, KRAKENPRO_SPOT_TAKER=maker_dearer, MEXC_SPOT_TAKER=maker_cheaper, OKX_SPOT_TAKER=maker_dearer)
- `PASS` barrier:no_cell_reachable_on_a_line_without_assumed_components - cheapest line without an assumed component 12.176776695296637 bps (BINANCE_USDM_PERP_TAKER/taker/deep if observed else '') vs best cell gross 8.912 bps
- `PASS` barrier:reachable_set_equals_gross_above_the_cheapest_line - 7 reachable vs the count implied by the cheapest line 1.25 bps
- `PASS` barrier:taker_execution_clears_nothing - best gross 8.912 bps < cheapest taker round trip 12.176776695296637 bps (BINANCE_USDM_PERP_TAKER)
- `PASS` consistency:campaign_line_reaches_no_cell - reachable at the campaign line: 0; audit net_positive_count 0
- `PASS` amplitude:median_bar_move_covers_the_base_line_only_from_30m_up - worst-asset median bar move by timeframe: 15m=9.38, 1h=18.62, 30m=13.26, 5m=6.83 bps vs base line 12.0 bps
- `PASS` amplitude:only_one_published_median_move_reaches_the_campaign_line - cells above the campaign line 23.353553390593273 bps: ['1h/SOL']
- `PASS` amplitude:the_executable_line_is_a_multiple_of_the_best_edge - cheapest observed-only line 12.1768 bps = 1.366x the best cell's entire edge (8.912 bps), so the best cell must improve its capture or the line must fall by 3.2648 bps
- `PASS` governance:no_promotion_or_rentability_claimed - the explorer reduces the barrier to a measured configuration set; it authorizes nothing and claims no strategy is RENTABLE, CERTIFIED or PRODUCTION_READY

- claims: {"authorization_state": "NOT_AUTHORIZED", "certified_claimed": false, "false_success": 0, "production_ready_claimed": false, "promotion_claimed": false, "rentable_claimed": false, "trades_authorized": 0}
- payload_sha256: `da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6`

Nothing here declares a strategy RENTABLE, CERTIFIED or PRODUCTION_READY. The map shows where a barrier could be cleared and under which assumptions; the assumptions that would have to be earned (a forward maker fill model, observed spreads) are named, not granted.
