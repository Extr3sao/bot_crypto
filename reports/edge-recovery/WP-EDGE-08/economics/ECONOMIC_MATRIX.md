# WP-EDGE-08D — the economic matrix

*Read at `2026-10-14T20:33:53Z` (`EDGE08_V1`). Ground: the known universe (BTC/ETH/SOL) — read many times; this is the estate reading.*

Cost model `COST_MODEL_V3`, scenarios BASE, 2X_FEES, ADVERSE
 — derived from the plane's own components, never from fresh assumptions.

## 1. The whole matrix, one line per arm and window

| Arm | Track | Window | Trades | Gross | Net | Expectancy | Net @2x fees | Net @adverse | PF | DD % | Sharpe | Cost bps/trade | Trades/day |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge06_trend_fixed` | CURRENT | DEV | 354 | 884.1622 | **470.1555** | 1.3281 | -230.8013 | -280.3373 | 1.1282 | 4.1573 | 0.4838 | 23.8466 | 0.3233 |
| `edge06_trend_fixed` | CURRENT | VAL | 136 | 15.2337 | **-146.1493** | -1.0746 | -281.5418 | -318.9974 | 0.869 | 3.5367 | -0.5743 | 23.7887 | 0.3716 |
| `edge06_trend_fixed` | CURRENT | OOS | 113 | 364.8426 | **230.0174** | 2.0356 | 116.674 | 85.0213 | 1.321 | 1.5329 | 0.9576 | 23.8629 | 0.1735 |
| `edge07_active_thrust` | CURRENT | DEV | 274 | -117.4645 | **-440.9027** | -1.6091 | -440.6493 | -457.5488 | 0.7682 | 5.0023 | -1.0627 | 23.7758 | 0.2502 |
| `edge07_active_thrust` | CURRENT | VAL | 367 | -59.0474 | **-495.4514** | -1.35 | -501.2525 | -497.9834 | 0.6493 | 5.0715 | -3.1209 | 23.7822 | 1.0028 |
| `edge07_active_thrust` | CURRENT | OOS | 381 | -34.9352 | **-488.0181** | -1.2809 | -500.9138 | -492.0973 | 0.66 | 5.0255 | -2.8546 | 23.7839 | 0.585 |
| `edge08_active_daybreak_1h` | ACTIVE | DEV | 554 | 654.5252 | **18.9021** | 0.0341 | -225.4896 | -249.3957 | 1.0041 | 5.0844 | 0.0355 | 23.8152 | 0.506 |
| `edge08_active_daybreak_1h` | ACTIVE | VAL | 314 | -30.9289 | **-403.0569** | -1.2836 | -454.63 | -459.6383 | 0.791 | 4.96 | -1.3037 | 23.7837 | 0.858 |
| `edge08_active_daybreak_1h` | ACTIVE | OOS | 167 | -116.9139 | **-314.8222** | -1.8852 | -354.9277 | -351.0447 | 0.7194 | 5.1076 | -1.2265 | 23.7694 | 0.2564 |
| `edge08_active_multiday_range_1h` | ACTIVE | DEV | 205 | 473.8715 | **238.7233** | 1.1645 | 41.3429 | -13.2477 | 1.1539 | 2.3346 | 0.4281 | 23.8432 | 0.1872 |
| `edge08_active_multiday_range_1h` | ACTIVE | VAL | 71 | 382.2841 | **297.7967** | 4.1943 | 226.7126 | 206.6899 | 1.8287 | 0.8048 | 1.7584 | 23.9148 | 0.194 |
| `edge08_active_multiday_range_1h` | ACTIVE | OOS | 83 | 75.1417 | **-23.6598** | -0.2851 | -106.7192 | -129.8612 | 0.9528 | 2.1508 | -0.1437 | 23.8076 | 0.1274 |
| `edge08_active_stretch_revert_1h` | ACTIVE | DEV | 132 | -164.9428 | **-314.0392** | -2.3791 | -314.5608 | -346.635 | 0.8133 | 5.2001 | -0.482 | 23.7548 | 0.1206 |
| `edge08_active_stretch_revert_1h` | ACTIVE | VAL | 238 | -124.446 | **-406.7751** | -1.7091 | -524.9201 | -540.5218 | 0.7715 | 5.084 | -1.1886 | 23.7736 | 0.6503 |
| `edge08_active_stretch_revert_1h` | ACTIVE | OOS | 141 | -359.6194 | **-526.1891** | -3.7318 | -506.9122 | -500.7877 | 0.5505 | 5.2619 | -1.9495 | 23.7251 | 0.2165 |
| `edge08_quality_breakout_daily` | QUALITY | DEV | 52 | 958.7812 | **924.1688** | 17.7725 | 893.9126 | 883.42 | 2.4865 | 2.5776 | 1.3481 | 24.5964 | 0.0475 |
| `edge08_quality_breakout_daily` | QUALITY | VAL | 31 | 317.8406 | **295.1323** | 9.5204 | 275.8378 | 269.0777 | 1.7572 | 2.2886 | 1.0583 | 24.1887 | 0.0847 |
| `edge08_quality_breakout_daily` | QUALITY | OOS | 17 | -45.1579 | **-57.8012** | -3.4001 | -68.3961 | -71.3345 | 0.8014 | 2.1158 | -0.3013 | 23.6854 | 0.0261 |
| `edge08_quality_pullback_daily` | QUALITY | DEV | 165 | -308.7333 | **-378.976** | -2.2968 | -383.1134 | -393.4097 | 0.5474 | 5.0301 | -0.9375 | 23.6624 | 0.1507 |
| `edge08_quality_pullback_daily` | QUALITY | VAL | 115 | -150.5451 | **-212.8136** | -1.8506 | -264.4004 | -277.8099 | 0.6502 | 3.3742 | -1.1933 | 23.7179 | 0.3142 |
| `edge08_quality_pullback_daily` | QUALITY | OOS | 127 | 96.5923 | **27.5484** | 0.2169 | -30.2964 | -46.3499 | 1.0519 | 1.5924 | 0.1444 | 23.8257 | 0.195 |
| `edge08_quality_reversion_daily` | QUALITY | DEV | 0 | 0 | **0** | None | 0 | 0 | None | 0.0 | None | None | 0.0 |
| `edge08_quality_reversion_daily` | QUALITY | VAL | 0 | 0 | **0** | None | 0 | 0 | None | 0.0 | None | None | 0.0 |
| `edge08_quality_reversion_daily` | QUALITY | OOS | 0 | 0 | **0** | None | 0 | 0 | None | 0.0 | None | None | 0.0 |
| `edge_trend_01_4h` | CURRENT | DEV | 183 | 726.5095 | **572.9393** | 3.1308 | 443.492 | 406.9959 | 1.3563 | 3.9146 | 0.663 | 23.9207 | 0.1671 |
| `edge_trend_01_4h` | CURRENT | VAL | 67 | 124.0095 | **56.1217** | 0.8376 | -1.4873 | -17.9647 | 1.1052 | 3.0133 | 0.2187 | 23.8379 | 0.1831 |
| `edge_trend_01_4h` | CURRENT | OOS | 62 | 220.1668 | **152.9961** | 2.4677 | 96.8625 | 81.1806 | 1.2583 | 2.1988 | 0.5362 | 23.8791 | 0.0952 |

`ECONOMIC_TRADES.csv` carries every BASE trade of every cell, with its asset, its regime,
its cost components and its exit reason.

## 2. Cost sensitivity, per arm

| Arm | Base net | 2x fees | Adverse | Survives 2x | Survives adverse | Cost bps/trade
 (base → 2x) | Margin left/trade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `edge06_trend_fixed` | 230.0174 | 116.674 | 85.0213 | True | True | 23.8629 → 43.9236 | 2.0356 |
| `edge07_active_thrust` | -488.0181 | -500.9138 | -492.0973 | False | False | 23.7839 → 43.7548 | -1.2809 |
| `edge08_active_daybreak_1h` | -314.8222 | -354.9277 | -351.0447 | False | False | 23.7694 → 43.7186 | -1.8852 |
| `edge08_active_multiday_range_1h` | -23.6598 | -106.7192 | -129.8612 | False | False | 23.8076 → 43.8219 | -0.2851 |
| `edge08_active_stretch_revert_1h` | -526.1891 | -506.9122 | -500.7877 | False | False | 23.7251 → 43.6184 | -3.7318 |
| `edge08_quality_breakout_daily` | -57.8012 | -68.3961 | -71.3345 | False | False | 23.6854 → 43.5971 | -3.4001 |
| `edge08_quality_pullback_daily` | 27.5484 | -30.2964 | -46.3499 | False | False | 23.8257 → 43.8553 | 0.2169 |
| `edge08_quality_reversion_daily` | 0.0 | 0 | 0 | False | False | None → None | None |
| `edge_trend_01_4h` | 152.9961 | 96.8625 | 81.1806 | True | True | 23.8791 → 43.9539 | 2.4677 |

## 3. Robustness readings, per arm (BASE, on the decisive window)

### `edge06_trend_fixed` — WP-EDGE-06's fixed 3xATR target, REJECT on WP-EDGE-07's unread window

- Clock `4h`, horizon 1440 min.
- Expectancy interval (90 %, block bootstrap): {'low': -0.117, 'high': 3.7242, 'point': 2.0356}; net interval: {'low': -13.2195, 'high': 420.8309, 'point': 230.0174}.
- Time blocks: 2 of 3 positive — block 1 73 trades, net 119.2933; block 2 40 trades, net 110.7241; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 112, 'net_usdt': 178.9786, 'expectancy_usdt': 1.598, 'return_pct_of_start_equity': 1.7898, 'removed_trade_net_usdt': 51.0388}.
- Serial dependence: lag-1 0.1146 against a ±0.1881 band; runs z=-1.6906.
- Exits: {'target': 39, 'stop_loss': 74}; frequency 0.1735 trades/day across the universe, mean hold 21.4513 h.
- Frozen gate with OOS := this window: INSUFFICIENT_EVIDENCE — oos has 0 profitable regime(s), fewer than the required 1

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 37 | 12.6669 | 0.3423 |
| ETH | 39 | 228.4072 | 5.8566 |
| SOL | 37 | -11.0567 | -0.2988 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 11 | -36.726 | -3.3387 |
| BULL | 97 | 236.7847 | 2.4411 |
| SIDEWAYS | 5 | 29.9587 | 5.9917 |

### `edge07_active_thrust` — WP-EDGE-07's ACTIVE thrust book, REJECT_NO_GROSS_EDGE on the known universe

- Clock `1h`, horizon 1440 min.
- Expectancy interval (90 %, block bootstrap): {'low': -1.9214, 'high': -0.5648, 'point': -1.2809}; net interval: {'low': -732.0361, 'high': -215.1709, 'point': -488.0181}.
- Time blocks: 0 of 3 positive — block 1 381 trades, net -488.0181; block 2 0 trades, net 0; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 380, 'net_usdt': -516.2328, 'expectancy_usdt': -1.3585, 'return_pct_of_start_equity': -5.1623, 'removed_trade_net_usdt': 28.2147}.
- Serial dependence: lag-1 0.1654 against a ±0.1025 band; runs z=-3.9587.
- Exits: {'stop_loss': 234, 'target': 147}; frequency 0.585 trades/day across the universe, mean hold 3.1785 h.
- Frozen gate with OOS := this window: REJECT — oos net -488.02 USDT <= 0 after costs; oos expectancy -1.2809 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-500.91 USDT): no cost margin; net negative in every window (DEV=-440.90, VAL=-495.45, OOS=-488.02 USDT)

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 125 | -218.1726 | -1.7454 |
| ETH | 126 | -81.0265 | -0.6431 |
| SOL | 130 | -188.8191 | -1.4525 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 50 | -156.9893 | -3.1398 |
| BULL | 285 | -298.4752 | -1.0473 |
| SIDEWAYS | 46 | -32.5537 | -0.7077 |

### `edge08_active_daybreak_1h` — A-1: can a day-high break held for days reach three trades a day and pay?

- Clock `1h`, horizon 1440 min, params hash `d1ed6bbe8a016018…`.
- Expectancy interval (90 %, block bootstrap): {'low': -4.55, 'high': 1.3057, 'point': -1.8852}; net interval: {'low': -759.8534, 'high': 218.056, 'point': -314.8222}.
- Time blocks: 0 of 3 positive — block 1 167 trades, net -314.8222; block 2 0 trades, net 0; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 166, 'net_usdt': -364.4384, 'expectancy_usdt': -2.1954, 'return_pct_of_start_equity': -3.6444, 'removed_trade_net_usdt': 49.6162}.
- Serial dependence: lag-1 0.3263 against a ±0.1548 band; runs z=-3.16.
- Exits: {'target': 42, 'stop_loss': 74, 'ema_invalidation': 30, 'trailing_stop': 21}; frequency 0.2564 trades/day across the universe, mean hold 13.5988 h.
- Frozen gate with OOS := this window: REJECT — oos net -314.82 USDT <= 0 after costs; oos expectancy -1.8852 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-354.93 USDT): no cost margin

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 58 | -137.077 | -2.3634 |
| ETH | 56 | -95.7677 | -1.7101 |
| SOL | 53 | -81.9775 | -1.5467 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 27 | -126.8391 | -4.6977 |
| BULL | 122 | -227.1585 | -1.862 |
| SIDEWAYS | 18 | 39.1755 | 2.1764 |

### `edge08_active_multiday_range_1h` — A-3: does a compressed three-day range pay when it breaks?

- Clock `1h`, horizon 1440 min, params hash `5c9c1f4e9e25257a…`.
- Expectancy interval (90 %, block bootstrap): {'low': -5.2389, 'high': 4.4991, 'point': -0.2851}; net interval: {'low': -434.8247, 'high': 373.428, 'point': -23.6598}.
- Time blocks: 1 of 3 positive — block 1 45 trades, net -72.9627; block 2 38 trades, net 49.3029; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 82, 'net_usdt': -58.3413, 'expectancy_usdt': -0.7115, 'return_pct_of_start_equity': -0.5834, 'removed_trade_net_usdt': 34.6815}.
- Serial dependence: lag-1 0.169 against a ±0.2195 band; runs z=0.1427.
- Exits: {'target': 22, 'stop_loss': 32, 'trailing_stop': 15, 'ema_invalidation': 14}; frequency 0.1274 trades/day across the universe, mean hold 18.5783 h.
- Frozen gate with OOS := this window: REJECT — oos net -23.66 USDT <= 0 after costs; oos expectancy -0.2851 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-106.72 USDT): no cost margin

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 27 | -52.2079 | -1.9336 |
| ETH | 30 | 60.6987 | 2.0233 |
| SOL | 26 | -32.1506 | -1.2366 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 23 | -91.9654 | -3.9985 |
| BULL | 57 | 76.0232 | 1.3337 |
| SIDEWAYS | 3 | -7.7177 | -2.5726 |

### `edge08_active_stretch_revert_1h` — A-2: is the dislocation the frequent side, and does it pay the round trip?

- Clock `1h`, horizon 1440 min, params hash `d625bd8129fed25e…`.
- Expectancy interval (90 %, block bootstrap): {'low': -5.6573, 'high': -1.9472, 'point': -3.7318}; net interval: {'low': -797.6756, 'high': -274.5555, 'point': -526.1891}.
- Time blocks: 0 of 3 positive — block 1 141 trades, net -526.1891; block 2 0 trades, net 0; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 140, 'net_usdt': -594.3273, 'expectancy_usdt': -4.2452, 'return_pct_of_start_equity': -5.9433, 'removed_trade_net_usdt': 68.1382}.
- Serial dependence: lag-1 0.2583 against a ±0.1684 band; runs z=-3.745.
- Exits: {'stop_loss': 114, 'target': 27}; frequency 0.2165 trades/day across the universe, mean hold 11.5319 h.
- Frozen gate with OOS := this window: REJECT — oos net -526.19 USDT <= 0 after costs; oos expectancy -3.7318 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-506.91 USDT): no cost margin; net negative in every window (DEV=-314.04, VAL=-406.78, OOS=-526.19 USDT)

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 47 | -46.9661 | -0.9993 |
| ETH | 44 | -203.1085 | -4.6161 |
| SOL | 50 | -276.1146 | -5.5223 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 25 | -95.9553 | -3.8382 |
| BULL | 100 | -389.4355 | -3.8944 |
| SIDEWAYS | 16 | -40.7983 | -2.5499 |

### `edge08_quality_breakout_daily` — Q-1: does the daily breakout pay its own round trip on a cross-section?

- Clock `1d`, horizon 4320 min, params hash `576a457a58e9fc79…`.
- Expectancy interval (90 %, block bootstrap): {'low': -3.4001, 'high': -3.4001, 'point': -3.4001}; net interval: {'low': -57.8012, 'high': -57.8012, 'point': -57.8012}.
- Time blocks: 1 of 3 positive — block 1 10 trades, net 99.8217; block 2 7 trades, net -157.6229; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 16, 'net_usdt': -132.2417, 'expectancy_usdt': -8.2651, 'return_pct_of_start_equity': -1.3224, 'removed_trade_net_usdt': 74.4405}.
- Serial dependence: lag-1 -0.0851 against a ±0.4851 band; runs z=-0.0841.
- Exits: {'stop_loss': 9, 'ema_invalidation': 2, 'target': 3, 'trailing_stop': 3}; frequency 0.0261 trades/day across the universe, mean hold 381.1765 h.
- Frozen gate with OOS := this window: INSUFFICIENT_EVIDENCE — oos net -57.80 USDT <= 0 after costs; oos expectancy -3.4001 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-68.40 USDT): no cost margin; oos trades 17 < required 30 (unpowered sample)

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 5 | -3.3445 | -0.6689 |
| ETH | 7 | 19.9893 | 2.8556 |
| SOL | 5 | -74.4461 | -14.8892 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BULL | 16 | -131.3965 | -8.2123 |
| SIDEWAYS | 1 | 73.5953 | 73.5953 |

### `edge08_quality_pullback_daily` — Q-2: is the cheaper entry into an uptrend the one that survives costs?

- Clock `1d`, horizon 4320 min, params hash `2ba39edfc34f04df…`.
- Expectancy interval (90 %, block bootstrap): {'low': -1.9962, 'high': 2.9578, 'point': 0.2169}; net interval: {'low': -253.5179, 'high': 375.6361, 'point': 27.5484}.
- Time blocks: 1 of 3 positive — block 1 59 trades, net 101.6117; block 2 68 trades, net -74.0633; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 126, 'net_usdt': -9.5085, 'expectancy_usdt': -0.0755, 'return_pct_of_start_equity': -0.0951, 'removed_trade_net_usdt': 37.0569}.
- Serial dependence: lag-1 0.2784 against a ±0.1775 band; runs z=-1.9511.
- Exits: {'ema_invalidation': 111, 'target': 8, 'stop_loss': 6, 'trailing_stop': 2}; frequency 0.195 trades/day across the universe, mean hold 24.9449 h.
- Frozen gate with OOS := this window: INSUFFICIENT_EVIDENCE — the largest single trade is 1.35 of the oos net; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-30.30 USDT): no cost margin

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 45 | 62.2608 | 1.3836 |
| ETH | 36 | -40.3636 | -1.1212 |
| SOL | 46 | 5.6511 | 0.1229 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 22 | -16.0576 | -0.7299 |
| BULL | 74 | 18.3804 | 0.2484 |
| SIDEWAYS | 31 | 25.2255 | 0.8137 |

### `edge08_quality_reversion_daily` — Q-3: does a band stretch inside a range regime pay after costs?

- Clock `1d`, horizon 4320 min, params hash `988137f4e8dbaf64…`.
- Expectancy interval (90 %, block bootstrap): {'low': None, 'high': None, 'point': None}; net interval: {'low': None, 'high': None, 'point': None}.
- Time blocks: 0 of 3 positive — block 1 0 trades, net 0; block 2 0 trades, net 0; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 0, 'net_usdt': 0.0, 'expectancy_usdt': None}.
- Serial dependence: lag-1 None against a ±None band; runs z=None.
- Exits: {}; frequency 0.0 trades/day across the universe, mean hold None h.
- Frozen gate with OOS := this window: REJECT — oos net 0.00 USDT <= 0 after costs; oos expectancy None USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (0.00 USDT): no cost margin; net negative in every window (DEV=0.00, VAL=0.00, OOS=0.00 USDT); oos trades 0 < required 30 (unpowered sample)

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |

### `edge_trend_01_4h` — the frozen WP-EDGE-01 ruleset: 4h trend with a 3xATR trailing exit

- Clock `4h`, horizon 1440 min.
- Expectancy interval (90 %, block bootstrap): {'low': -0.3279, 'high': 5.6948, 'point': 2.4677}; net interval: {'low': -20.3293, 'high': 353.0781, 'point': 152.9961}.
- Time blocks: 1 of 3 positive — block 1 39 trades, net 167.3262; block 2 23 trades, net -14.3301; block 3 0 trades, net 0.
- Largest winner removed: {'trades': 61, 'net_usdt': -13.1356, 'expectancy_usdt': -0.2153, 'return_pct_of_start_equity': -0.1314, 'removed_trade_net_usdt': 166.1317}.
- Serial dependence: lag-1 0.1771 against a ±0.254 band; runs z=-0.4896.
- Exits: {'trailing_stop': 24, 'stop_loss': 12, 'ema_invalidation': 26}; frequency 0.0952 trades/day across the universe, mean hold 68.6452 h.
- Frozen gate with OOS := this window: INSUFFICIENT_EVIDENCE — the largest single trade is 1.09 of the oos net; oos has 0 profitable regime(s), fewer than the required 1

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 20 | 7.1688 | 0.3584 |
| ETH | 21 | 207.0702 | 9.8605 |
| SOL | 21 | -61.2428 | -2.9163 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 7 | -42.5873 | -6.0839 |
| BULL | 51 | 196.4692 | 3.8523 |
| SIDEWAYS | 4 | -0.8858 | -0.2215 |

## 4. CURRENT vs PROPOSED

### DEV

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day | Cost bps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 554 | 18.9021 | 0.0341 | 1.0041 | 5.0844 | 0.506 | 23.8152 |
| PROPOSED | `edge08_active_multiday_range_1h` | 205 | 238.7233 | 1.1645 | 1.1539 | 2.3346 | 0.1872 | 23.8432 |
| PROPOSED | `edge08_active_stretch_revert_1h` | 132 | -314.0392 | -2.3791 | 0.8133 | 5.2001 | 0.1206 | 23.7548 |
| PROPOSED | `edge08_quality_breakout_daily` | 52 | 924.1688 | 17.7725 | 2.4865 | 2.5776 | 0.0475 | 24.5964 |
| PROPOSED | `edge08_quality_pullback_daily` | 165 | -378.976 | -2.2968 | 0.5474 | 5.0301 | 0.1507 | 23.6624 |
| PROPOSED | `edge08_quality_reversion_daily` | 0 | 0 | None | None | 0.0 | 0.0 | None |
| CURRENT | `edge06_trend_fixed` | 354 | 470.1555 | 1.3281 | 1.1282 | 4.1573 | 0.3233 | 23.8466 |
| CURRENT | `edge07_active_thrust` | 274 | -440.9027 | -1.6091 | 0.7682 | 5.0023 | 0.2502 | 23.7758 |
| CURRENT | `edge_trend_01_4h` | 183 | 572.9393 | 3.1308 | 1.3563 | 3.9146 | 0.1671 | 23.9207 |

### VAL

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day | Cost bps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 314 | -403.0569 | -1.2836 | 0.791 | 4.96 | 0.858 | 23.7837 |
| PROPOSED | `edge08_active_multiday_range_1h` | 71 | 297.7967 | 4.1943 | 1.8287 | 0.8048 | 0.194 | 23.9148 |
| PROPOSED | `edge08_active_stretch_revert_1h` | 238 | -406.7751 | -1.7091 | 0.7715 | 5.084 | 0.6503 | 23.7736 |
| PROPOSED | `edge08_quality_breakout_daily` | 31 | 295.1323 | 9.5204 | 1.7572 | 2.2886 | 0.0847 | 24.1887 |
| PROPOSED | `edge08_quality_pullback_daily` | 115 | -212.8136 | -1.8506 | 0.6502 | 3.3742 | 0.3142 | 23.7179 |
| PROPOSED | `edge08_quality_reversion_daily` | 0 | 0 | None | None | 0.0 | 0.0 | None |
| CURRENT | `edge06_trend_fixed` | 136 | -146.1493 | -1.0746 | 0.869 | 3.5367 | 0.3716 | 23.7887 |
| CURRENT | `edge07_active_thrust` | 367 | -495.4514 | -1.35 | 0.6493 | 5.0715 | 1.0028 | 23.7822 |
| CURRENT | `edge_trend_01_4h` | 67 | 56.1217 | 0.8376 | 1.1052 | 3.0133 | 0.1831 | 23.8379 |

### OOS

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day | Cost bps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 167 | -314.8222 | -1.8852 | 0.7194 | 5.1076 | 0.2564 | 23.7694 |
| PROPOSED | `edge08_active_multiday_range_1h` | 83 | -23.6598 | -0.2851 | 0.9528 | 2.1508 | 0.1274 | 23.8076 |
| PROPOSED | `edge08_active_stretch_revert_1h` | 141 | -526.1891 | -3.7318 | 0.5505 | 5.2619 | 0.2165 | 23.7251 |
| PROPOSED | `edge08_quality_breakout_daily` | 17 | -57.8012 | -3.4001 | 0.8014 | 2.1158 | 0.0261 | 23.6854 |
| PROPOSED | `edge08_quality_pullback_daily` | 127 | 27.5484 | 0.2169 | 1.0519 | 1.5924 | 0.195 | 23.8257 |
| PROPOSED | `edge08_quality_reversion_daily` | 0 | 0 | None | None | 0.0 | 0.0 | None |
| CURRENT | `edge06_trend_fixed` | 113 | 230.0174 | 2.0356 | 1.321 | 1.5329 | 0.1735 | 23.8629 |
| CURRENT | `edge07_active_thrust` | 381 | -488.0181 | -1.2809 | 0.66 | 5.0255 | 0.585 | 23.7839 |
| CURRENT | `edge_trend_01_4h` | 62 | 152.9961 | 2.4677 | 1.2583 | 2.1988 | 0.0952 | 23.8791 |

same corpus, same windows, same costs, same risk policy, same simulator; the CURRENT arms are already-closed registrations carried as the baseline and they change no verdict.

## 5. What this matrix is not

- It is not evidence: the ground is a universe every earlier work package has read. The evidence of this work package is the cross-section, read once, in `validation/`.
- It promotes nothing: `promotion: NONE`, `order_sent: false`.
- The frozen gate shown per arm is the yardstick earlier work packages were judged by, reported for comparability with `OOS` := this corpus's OOS window.
