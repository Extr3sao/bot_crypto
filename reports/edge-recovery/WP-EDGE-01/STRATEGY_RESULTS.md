# STRATEGY RESULTS - WP-EDGE-01

- run_id: `wp-edge-01-campaign`
- params_hash: `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77`
- generated (UTC): 2026-10-12T13:02:28.395619+00:00
- commit: `042947cf58b25d3b706b28fde81b4be6986c6c2f`
- data: local corpora only (15m: `data/raw/alpha003/price`, 1h: `reports/alpha-expansion-v1/data`, aggregated to 4h/1d)

## Cost scenarios

| scenario | fee x | slippage/impact x |
|---|---|---|
| BASE | 1.0 | 1.0 |
| 2X_FEES | 2.0 | 1.0 |
| ADVERSE | 2.0 | 3.0 |

## Verdicts

| candidate | timeframe | OOS trades | OOS net (BASE) | OOS expectancy | verdict | reasons |
|---|---|---|---|---|---|---|
| edge_intra_01 | 15m | 63 | -94.81 | -1.50 | **REJECT** (powered (oos n=63 >= 30); net por ventana: DEV=-496.43, VAL=-479.18, OOS=-94.81) | oos net -94.81 USDT <= 0 after costs; oos expectancy -1.5049 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-133.20 USDT): no cost margin; net negative in every window (DEV=-496.43, VAL=-479.18, OOS=-94.81 USDT) |
| edge_intra_02 | 15m | 14 | -12.63 | -0.90 | **REJECT** (underpowered (oos n=14 < 30); net por ventana: DEV=-189.88, VAL=-102.58, OOS=-12.63) | oos net -12.63 USDT <= 0 after costs; oos expectancy -0.902 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-31.50 USDT): no cost margin; net negative in every window (DEV=-189.88, VAL=-102.58, OOS=-12.63 USDT); oos trades 14 < required 30 (unpowered sample) |
| edge_intra_02_no_fvg | 15m | 45 | -69.10 | -1.54 | **REJECT** (powered (oos n=45 >= 30); net por ventana: DEV=-500.83, VAL=-289.00, OOS=-69.10) | oos net -69.10 USDT <= 0 after costs; oos expectancy -1.5355 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-82.83 USDT): no cost margin; net negative in every window (DEV=-500.83, VAL=-289.00, OOS=-69.10 USDT) |
| edge_trend_01_4h | 4h | 52 | 208.01 | 4.00 | **INSUFFICIENT_EVIDENCE** (powered (oos n=52 >= 30); net por ventana: DEV=1,921.18, VAL=4.53, OOS=208.01) | the largest single trade is 0.80 of the oos net |
| edge_trend_01_1d | 1d | 13 | -118.60 | -9.12 | **INSUFFICIENT_EVIDENCE** (underpowered (oos n=13 < 30); net por ventana: DEV=926.51, VAL=86.54, OOS=-118.60) | oos net -118.60 USDT <= 0 after costs; oos expectancy -9.1231 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-125.16 USDT): no cost margin; oos trades 13 < required 30 (unpowered sample) |

## Per split and scenario

### edge_intra_01 (15m)

Costs are split the way the model charges them: the fee is the contractual component and the price cost is spread + slippage + impact, charged half on each leg. `cost_bps_realised` per trade reconciles with the plane printed here (the verifier re-checks it fill by fill).

| split | scenario | trades | gross | fees | price costs | fee bps | spread bps | slip bps | impact bps | net | win rate | profit factor | expectancy | max DD | Sharpe | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 290 | -151.71 | 289.79 | 54.92 | 20.00 | 1.00 | 2.63 | 0.16 | -496.43 | 19.31% | 0.32 | -1.71 | 5.04% | -6.23 | 1.57% |
| DEV | 2X_FEES | 197 | -70.62 | 393.78 | 37.32 | 40.00 | 1.00 | 2.63 | 0.16 | -501.72 | 18.78% | 0.23 | -2.55 | 5.10% | -6.34 | 1.14% |
| DEV | ADVERSE | 169 | -79.37 | 337.68 | 79.12 | 40.00 | 1.00 | 7.90 | 0.47 | -496.17 | 17.75% | 0.19 | -2.94 | 5.04% | -6.40 | 1.08% |
| VAL | BASE | 344 | -70.15 | 343.86 | 65.17 | 20.00 | 1.00 | 2.63 | 0.16 | -479.18 | 18.31% | 0.37 | -1.39 | 4.83% | -7.39 | 2.97% |
| VAL | 2X_FEES | 230 | -5.43 | 459.90 | 43.58 | 40.00 | 1.00 | 2.63 | 0.16 | -508.92 | 16.09% | 0.26 | -2.21 | 5.09% | -8.46 | 2.09% |
| VAL | ADVERSE | 209 | 10.90 | 417.83 | 97.89 | 40.00 | 1.00 | 7.90 | 0.47 | -504.82 | 15.79% | 0.25 | -2.42 | 5.05% | -8.65 | 1.87% |
| OOS | BASE | 63 | -19.91 | 62.97 | 11.93 | 20.00 | 1.00 | 2.63 | 0.16 | -94.81 | 17.46% | 0.30 | -1.50 | 0.95% | -3.48 | 0.24% |
| OOS | 2X_FEES | 52 | -19.41 | 103.94 | 9.85 | 40.00 | 1.00 | 2.63 | 0.16 | -133.20 | 17.31% | 0.18 | -2.56 | 1.33% | -4.29 | 0.23% |
| OOS | ADVERSE | 46 | -11.56 | 91.93 | 21.54 | 40.00 | 1.00 | 7.90 | 0.47 | -125.04 | 19.57% | 0.18 | -2.72 | 1.25% | -4.07 | 0.17% |

Exit reasons (OOS/BASE): invalidation=28, stop_loss=21, target=11, trailing_stop=3

Refusals (OOS/BASE, top): candidate:trend_filter_fail=2282, candidate:volume_filter_fail=309, candidate:level_already_traded=102, candidate:rr_below_minimum=10, risk:risk_loss_cooldown=8, candidate:stop_too_wide=5, candidate:reward_below_cost=2

Buy & hold over the same OOS window: -2.60% / -9.39% / -3.49%

Market context at ENTRY (BASE scenario), from the benchmark only (`BTC`, daily, as-of each decision, rule in `RUN_REPORT.json#market_context`). This is what the market was doing, independently of the candidate; `UNDEFINED` means the benchmark could not be read yet (no day closed, or the label falls after 2026-03-01).

| split | market context | trades | net | win rate |
|---|---|---|---|---|
| DEV | BULL | 290 | -496.43 | 19.31% |
| VAL | BEAR | 40 | -107.58 | 10.00% |
| VAL | BULL | 304 | -371.60 | 19.41% |
| OOS | BEAR | 63 | -94.81 | 17.46% |

Entry trend state of the candidate's own filter (the `regime` column of TRADES.csv, which is NOT a market regime): {"UP": {"trades": 63, "net": -94.8077, "win_rate": 17.4603}}

### edge_intra_02 (15m)

Costs are split the way the model charges them: the fee is the contractual component and the price cost is spread + slippage + impact, charged half on each leg. `cost_bps_realised` per trade reconciles with the plane printed here (the verifier re-checks it fill by fill).

| split | scenario | trades | gross | fees | price costs | fee bps | spread bps | slip bps | impact bps | net | win rate | profit factor | expectancy | max DD | Sharpe | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 135 | -29.36 | 134.95 | 25.58 | 20.00 | 1.00 | 2.63 | 0.16 | -189.88 | 21.48% | 0.44 | -1.41 | 2.12% | -3.71 | 1.17% |
| DEV | 2X_FEES | 111 | -15.05 | 221.93 | 21.03 | 40.00 | 1.00 | 2.63 | 0.16 | -258.01 | 22.52% | 0.32 | -2.32 | 2.77% | -4.72 | 1.09% |
| DEV | ADVERSE | 103 | -2.75 | 205.90 | 48.24 | 40.00 | 1.00 | 7.90 | 0.47 | -256.89 | 24.27% | 0.31 | -2.49 | 2.76% | -4.73 | 1.02% |
| VAL | BASE | 72 | -16.97 | 71.97 | 13.64 | 20.00 | 1.00 | 2.63 | 0.16 | -102.58 | 22.22% | 0.42 | -1.42 | 1.22% | -3.85 | 0.72% |
| VAL | 2X_FEES | 67 | -18.00 | 133.94 | 12.69 | 40.00 | 1.00 | 2.63 | 0.16 | -164.63 | 19.40% | 0.26 | -2.46 | 1.74% | -5.53 | 0.68% |
| VAL | ADVERSE | 61 | -21.42 | 121.90 | 28.56 | 40.00 | 1.00 | 7.90 | 0.47 | -171.88 | 18.03% | 0.23 | -2.82 | 1.80% | -5.75 | 0.64% |
| OOS | BASE | 14 | 4.03 | 14.00 | 2.65 | 20.00 | 1.00 | 2.63 | 0.16 | -12.63 | 42.86% | 0.55 | -0.90 | 0.31% | -0.90 | 0.18% |
| OOS | 2X_FEES | 13 | -3.05 | 25.99 | 2.46 | 40.00 | 1.00 | 2.63 | 0.16 | -31.50 | 23.08% | 0.22 | -2.42 | 0.40% | -2.00 | 0.16% |
| OOS | ADVERSE | 12 | -1.20 | 23.99 | 5.62 | 40.00 | 1.00 | 7.90 | 0.47 | -30.80 | 25.00% | 0.21 | -2.57 | 0.38% | -1.95 | 0.16% |

Exit reasons (OOS/BASE): invalidation=4, stop_loss=4, target=4, trailing_stop=2

Refusals (OOS/BASE, top): candidate:trend_filter_fail=2264, candidate:volume_filter_fail=307, candidate:retest_not_confirmed=171, candidate:no_confirmed_fvg=118, candidate:level_already_traded=86, candidate:no_retest_confirmed=64, candidate:rr_below_minimum=4, candidate:reward_below_cost=3

Buy & hold over the same OOS window: -2.60% / -9.39% / -3.49%

Market context at ENTRY (BASE scenario), from the benchmark only (`BTC`, daily, as-of each decision, rule in `RUN_REPORT.json#market_context`). This is what the market was doing, independently of the candidate; `UNDEFINED` means the benchmark could not be read yet (no day closed, or the label falls after 2026-03-01).

| split | market context | trades | net | win rate |
|---|---|---|---|---|
| DEV | BEAR | 8 | 8.26 | 37.50% |
| DEV | BULL | 119 | -178.74 | 21.01% |
| DEV | SIDEWAYS | 8 | -19.40 | 12.50% |
| VAL | BEAR | 6 | -24.97 | 0.00% |
| VAL | BULL | 66 | -77.61 | 24.24% |
| OOS | BEAR | 14 | -12.63 | 42.86% |

Entry trend state of the candidate's own filter (the `regime` column of TRADES.csv, which is NOT a market regime): {"UP": {"trades": 14, "net": -12.6286, "win_rate": 42.8571}}

### edge_intra_02_no_fvg (15m)

Costs are split the way the model charges them: the fee is the contractual component and the price cost is spread + slippage + impact, charged half on each leg. `cost_bps_realised` per trade reconciles with the plane printed here (the verifier re-checks it fill by fill).

| split | scenario | trades | gross | fees | price costs | fee bps | spread bps | slip bps | impact bps | net | win rate | profit factor | expectancy | max DD | Sharpe | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 270 | -179.93 | 269.77 | 51.13 | 20.00 | 1.00 | 2.63 | 0.16 | -500.83 | 14.44% | 0.29 | -1.85 | 5.02% | -7.04 | 1.32% |
| DEV | 2X_FEES | 169 | -132.47 | 337.67 | 32.00 | 40.00 | 1.00 | 2.63 | 0.16 | -502.14 | 13.02% | 0.16 | -2.97 | 5.03% | -8.34 | 0.82% |
| DEV | ADVERSE | 156 | -117.12 | 311.62 | 73.01 | 40.00 | 1.00 | 7.90 | 0.47 | -501.75 | 13.46% | 0.15 | -3.22 | 5.02% | -8.35 | 0.80% |
| VAL | BASE | 207 | -42.87 | 206.92 | 39.22 | 20.00 | 1.00 | 2.63 | 0.16 | -289.00 | 20.29% | 0.35 | -1.40 | 2.94% | -6.96 | 1.56% |
| VAL | 2X_FEES | 173 | -28.41 | 345.88 | 32.78 | 40.00 | 1.00 | 2.63 | 0.16 | -407.07 | 19.08% | 0.22 | -2.35 | 4.10% | -8.85 | 1.46% |
| VAL | ADVERSE | 161 | -50.12 | 321.75 | 75.38 | 40.00 | 1.00 | 7.90 | 0.47 | -447.25 | 16.15% | 0.18 | -2.78 | 4.50% | -9.51 | 1.39% |
| OOS | BASE | 45 | -15.60 | 44.98 | 8.52 | 20.00 | 1.00 | 2.63 | 0.16 | -69.10 | 22.22% | 0.28 | -1.54 | 0.73% | -2.84 | 0.35% |
| OOS | 2X_FEES | 31 | -15.00 | 61.96 | 5.87 | 40.00 | 1.00 | 2.63 | 0.16 | -82.83 | 16.13% | 0.17 | -2.67 | 0.87% | -3.18 | 0.28% |
| OOS | ADVERSE | 29 | -13.20 | 57.95 | 13.58 | 40.00 | 1.00 | 7.90 | 0.47 | -84.72 | 17.24% | 0.15 | -2.92 | 0.88% | -3.22 | 0.28% |

Exit reasons (OOS/BASE): invalidation=14, stop_loss=21, target=7, trailing_stop=3

Refusals (OOS/BASE, top): candidate:trend_filter_fail=2273, candidate:volume_filter_fail=310, candidate:retest_not_confirmed=119, candidate:level_already_traded=81, candidate:no_retest_confirmed=33, candidate:rr_below_minimum=27, candidate:reward_below_cost=16, risk:risk_loss_cooldown=3

Buy & hold over the same OOS window: -2.60% / -9.39% / -3.49%

Market context at ENTRY (BASE scenario), from the benchmark only (`BTC`, daily, as-of each decision, rule in `RUN_REPORT.json#market_context`). This is what the market was doing, independently of the candidate; `UNDEFINED` means the benchmark could not be read yet (no day closed, or the label falls after 2026-03-01).

| split | market context | trades | net | win rate |
|---|---|---|---|---|
| DEV | BEAR | 4 | -10.54 | 0.00% |
| DEV | BULL | 264 | -483.89 | 14.77% |
| DEV | SIDEWAYS | 2 | -6.40 | 0.00% |
| VAL | BEAR | 21 | -53.89 | 14.29% |
| VAL | BULL | 186 | -235.11 | 20.97% |
| OOS | BEAR | 45 | -69.10 | 22.22% |

Entry trend state of the candidate's own filter (the `regime` column of TRADES.csv, which is NOT a market regime): {"UP": {"trades": 45, "net": -69.0987, "win_rate": 22.2222}}

### edge_trend_01_4h (4h)

Costs are split the way the model charges them: the fee is the contractual component and the price cost is spread + slippage + impact, charged half on each leg. `cost_bps_realised` per trade reconciles with the plane printed here (the verifier re-checks it fill by fill).

| split | scenario | trades | gross | fees | price costs | fee bps | spread bps | slip bps | impact bps | net | win rate | profit factor | expectancy | max DD | Sharpe | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 223 | 2,128.91 | 174.63 | 33.10 | 20.00 | 1.00 | 2.63 | 0.16 | 1,921.18 | 56.95% | 1.78 | 8.62 | 4.28% | 1.22 | 24.60% |
| DEV | 2X_FEES | 223 | 2,119.56 | 347.80 | 32.96 | 40.00 | 1.00 | 2.63 | 0.16 | 1,738.80 | 54.71% | 1.69 | 7.80 | 4.45% | 1.11 | 24.60% |
| DEV | ADVERSE | 223 | 2,110.77 | 346.59 | 81.20 | 40.00 | 1.00 | 7.90 | 0.47 | 1,682.98 | 54.26% | 1.66 | 7.55 | 4.49% | 1.07 | 24.60% |
| VAL | BASE | 58 | 62.52 | 48.75 | 9.24 | 20.00 | 1.00 | 2.63 | 0.16 | 4.53 | 48.28% | 1.01 | 0.08 | 4.10% | 0.03 | 29.03% |
| VAL | 2X_FEES | 58 | 62.20 | 97.41 | 9.23 | 40.00 | 1.00 | 2.63 | 0.16 | -44.44 | 46.55% | 0.94 | -0.77 | 4.39% | -0.13 | 29.03% |
| VAL | ADVERSE | 58 | 61.21 | 97.20 | 22.77 | 40.00 | 1.00 | 7.90 | 0.47 | -58.76 | 46.55% | 0.92 | -1.01 | 4.46% | -0.17 | 29.03% |
| OOS | BASE | 52 | 264.32 | 47.34 | 8.97 | 20.00 | 1.00 | 2.63 | 0.16 | 208.01 | 44.23% | 1.33 | 4.00 | 2.57% | 0.67 | 19.46% |
| OOS | 2X_FEES | 52 | 264.25 | 94.61 | 8.97 | 40.00 | 1.00 | 2.63 | 0.16 | 160.67 | 42.31% | 1.25 | 3.09 | 2.70% | 0.51 | 19.46% |
| OOS | ADVERSE | 52 | 263.45 | 94.43 | 22.13 | 40.00 | 1.00 | 7.90 | 0.47 | 146.89 | 42.31% | 1.22 | 2.82 | 2.73% | 0.47 | 19.46% |

Exit reasons (OOS/BASE): stop_loss=29, trailing_stop=23

Refusals (OOS/BASE, top): candidate:trend_filter_fail=205

Buy & hold over the same OOS window: -29.85% / -42.48% / -56.92%

Market context at ENTRY (BASE scenario), from the benchmark only (`BTC`, daily, as-of each decision, rule in `RUN_REPORT.json#market_context`). This is what the market was doing, independently of the candidate; `UNDEFINED` means the benchmark could not be read yet (no day closed, or the label falls after 2026-03-01).

| split | market context | trades | net | win rate |
|---|---|---|---|---|
| DEV | BEAR | 26 | 16.47 | 46.15% |
| DEV | BULL | 159 | 1,339.69 | 57.86% |
| DEV | SIDEWAYS | 14 | 77.01 | 64.29% |
| DEV | UNDEFINED | 24 | 488.01 | 58.33% |
| VAL | BULL | 57 | -0.18 | 47.37% |
| VAL | SIDEWAYS | 1 | 4.71 | 100.00% |
| OOS | BEAR | 7 | -58.88 | 42.86% |
| OOS | BULL | 41 | 177.43 | 41.46% |
| OOS | SIDEWAYS | 4 | 89.45 | 75.00% |

Entry trend state of the candidate's own filter (the `regime` column of TRADES.csv, which is NOT a market regime): {"UP": {"trades": 52, "net": 208.0056, "win_rate": 44.2308}}

### edge_trend_01_1d (1d)

Costs are split the way the model charges them: the fee is the contractual component and the price cost is spread + slippage + impact, charged half on each leg. `cost_bps_realised` per trade reconciles with the plane printed here (the verifier re-checks it fill by fill).

| split | scenario | trades | gross | fees | price costs | fee bps | spread bps | slip bps | impact bps | net | win rate | profit factor | expectancy | max DD | Sharpe | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 39 | 943.79 | 14.53 | 2.75 | 20.00 | 1.00 | 2.63 | 0.16 | 926.51 | 69.23% | 3.93 | 23.76 | 1.17% | 1.31 | 20.31% |
| DEV | 2X_FEES | 39 | 943.15 | 29.04 | 2.75 | 40.00 | 1.00 | 2.63 | 0.16 | 911.37 | 69.23% | 3.85 | 23.37 | 1.18% | 1.29 | 20.31% |
| DEV | ADVERSE | 39 | 941.13 | 28.97 | 6.79 | 40.00 | 1.00 | 7.90 | 0.47 | 905.38 | 69.23% | 3.83 | 23.21 | 1.19% | 1.28 | 20.31% |
| VAL | BASE | 20 | 95.55 | 7.58 | 1.44 | 20.00 | 1.00 | 2.63 | 0.16 | 86.54 | 35.00% | 1.27 | 4.33 | 2.94% | 0.42 | 45.66% |
| VAL | 2X_FEES | 20 | 95.55 | 15.15 | 1.44 | 40.00 | 1.00 | 2.63 | 0.16 | 78.96 | 35.00% | 1.25 | 3.95 | 2.99% | 0.39 | 45.66% |
| VAL | ADVERSE | 20 | 95.06 | 15.11 | 3.54 | 40.00 | 1.00 | 7.90 | 0.47 | 76.40 | 35.00% | 1.24 | 3.82 | 2.99% | 0.37 | 45.66% |
| OOS | BASE | 13 | -110.74 | 6.61 | 1.25 | 20.00 | 1.00 | 2.63 | 0.16 | -118.60 | 38.46% | 0.42 | -9.12 | 1.76% | -0.92 | 17.49% |
| OOS | 2X_FEES | 13 | -110.69 | 13.21 | 1.25 | 40.00 | 1.00 | 2.63 | 0.16 | -125.16 | 38.46% | 0.40 | -9.63 | 1.81% | -0.96 | 17.49% |
| OOS | ADVERSE | 13 | -110.32 | 13.17 | 3.09 | 40.00 | 1.00 | 7.90 | 0.47 | -126.57 | 38.46% | 0.39 | -9.74 | 1.82% | -0.97 | 17.49% |

Exit reasons (OOS/BASE): stop_loss=8, trailing_stop=5

Refusals (OOS/BASE, top): candidate:trend_filter_fail=27

Buy & hold over the same OOS window: -28.60% / -41.28% / -55.55%

Market context at ENTRY (BASE scenario), from the benchmark only (`BTC`, daily, as-of each decision, rule in `RUN_REPORT.json#market_context`). This is what the market was doing, independently of the candidate; `UNDEFINED` means the benchmark could not be read yet (no day closed, or the label falls after 2026-03-01).

| split | market context | trades | net | win rate |
|---|---|---|---|---|
| DEV | BULL | 36 | 785.52 | 69.44% |
| DEV | SIDEWAYS | 2 | 166.39 | 100.00% |
| DEV | UNDEFINED | 1 | -25.40 | 0.00% |
| VAL | BULL | 17 | -12.08 | 29.41% |
| VAL | SIDEWAYS | 3 | 98.62 | 66.67% |
| OOS | BULL | 12 | -137.68 | 33.33% |
| OOS | SIDEWAYS | 1 | 19.08 | 100.00% |

Entry trend state of the candidate's own filter (the `regime` column of TRADES.csv, which is NOT a market regime): {"UP": {"trades": 13, "net": -118.6003, "win_rate": 38.4615}}

## Honesty notes

- `net` is after fees, spread, slippage and impact: the plan it was sized against is printed per scenario above.
- A candidate with fewer than the pre-registered minimum OOS trades is `INSUFFICIENT_EVIDENCE`, never `ADMIT`.
- `REJECT` needs either a powered OOS sample or a net that is negative in all three windows; a small sample that is merely unprofitable stays `INSUFFICIENT_EVIDENCE`, and every reason is listed so the reader can re-judge it.
- Nothing in this table is a profitability claim: no candidate reached `ADMIT`, and a positive net carried by one trade is reported as such.
- Buy & hold uses the same window and the same cost plane, and trades once.
- `market_context` is the benchmark (BTC) regime at the entry instant, read as-of and never later; it is independent of every candidate. The `regime` column instead records the entry trend state of the candidate's own filter, so a filtered candidate reports a single value there by construction — which is why the market coverage question is answered by `market_context` and not by that column.
- Admission criteria (fixed before measuring): {"min_oos_trades": 30, "require_oos_net_positive": true, "require_oos_expectancy_positive": true, "require_oos_base_scenario_positive": true, "max_single_trade_share_of_net": 0.5, "require_min_positive_regimes": 1, "require_oos_cost_stress_positive": true, "note": "Initial thresholds for WP-EDGE-01, recorded before the campaign ran. They are NOT an approved profitability bar; they are the minimum evidence needed to avoid calling noise an edge. The cost-stress criterion (OOS net still positive at 2x fees) is stated here rather than inferred from the measured results."}
