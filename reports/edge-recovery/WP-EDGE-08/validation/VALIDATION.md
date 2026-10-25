# WP-EDGE-08E — the verdicts, on the cross-section nobody had read

*Read at `2026-10-14T20:37:22Z` (`EDGE08_V1`). Ground: the cross-section: AAVEUSDT, UNIUSDT, KSMUSDT, SNXUSDT, CRVUSDT, SUSHIUSDT — never the input of a committed measurement in this repository before this reading.*

Corpus digest `fb32470f5bc6329e…`, from `data/edge08/universe-1h`.

## 1. Coverage of the decisive window

| Clock | Floor bars/asset | Bars/asset | Enough |
| --- | --- | --- | --- |
| 1d | 400 | {'AAVE': 651, 'CRV': 651, 'KSM': 651, 'SNX': 651, 'SUSHI': 651, 'UNI': 651} | True (none below floor) |
| 1h | 8000 | {'AAVE': 15633, 'CRV': 15633, 'KSM': 15633, 'SNX': 15633, 'SUSHI': 15633, 'UNI': 15633} | True (none below floor) |
| 4h | 1500 | {'AAVE': 3909, 'CRV': 3909, 'KSM': 3909, 'SNX': 3909, 'SUSHI': 3909, 'UNI': 3909} | True (none below floor) |

## 2. The registered verdicts

| Arm | Track | Verdict | Failed criteria | Trades (OOS) | Net (OOS) | Net @2x fees | Trades/day | Frozen gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge06_trend_fixed` | CURRENT | **NOT_APPLICABLE** | — | 144 | -415.825 | None | 0.2211 | REJECT |
| `edge07_active_thrust` | CURRENT | **NOT_APPLICABLE** | — | 196 | -350.7431 | None | 0.3009 | REJECT |
| `edge08_active_daybreak_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, P6, R1, R2, F1 | 103 | -474.0861 | -433.8269 | 0.1581 | REJECT |
| `edge08_active_multiday_range_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, R1, R2, S1, F1 | 128 | -494.7063 | -491.0226 | 0.1965 | REJECT |
| `edge08_active_stretch_revert_1h` | ACTIVE | **REJECT_NO_GROSS_EDGE** | C0 | None | None | None | None | None |
| `edge08_quality_breakout_daily` | QUALITY | **REJECT** | P2, P3, P4, P5, P6, R1, R2, S1, F2 | 30 | -166.6146 | -178.1426 | 0.0461 | REJECT |
| `edge08_quality_pullback_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | None | None | None | None | None |
| `edge08_quality_reversion_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | None | None | None | None | None |
| `edge_trend_01_4h` | CURRENT | **NOT_APPLICABLE** | — | 126 | -215.8994 | None | 0.1934 | REJECT |

Read on the cross-section: ['edge08_quality_breakout_daily', 'edge08_active_daybreak_1h', 'edge08_active_multiday_range_1h']. Not read (the screen stopped them before the cross-section): ['edge08_quality_pullback_daily', 'edge08_quality_reversion_daily', 'edge08_active_stretch_revert_1h'].

## 3. Every criterion, per arm that was read

### `edge06_trend_fixed` — NOT_APPLICABLE

a CURRENT arm: already registered and measured by an earlier work package, read here as the baseline of the comparison; it answers to no criterion of this package

### `edge07_active_thrust` — NOT_APPLICABLE

a CURRENT arm: already registered and measured by an earlier work package, read here as the baseline of the comparison; it answers to no criterion of this package

### `edge08_active_daybreak_1h` — **REJECT**

decisive criterion failed on the cross-section: P2, P3, P4, P5, P6, R1, R2, F1; a decisive criterion failed with power on the cross-section; the family is reported with its numbers and is not tuned and re-run on the same window

| # | Criterion | Value | Passed |
| --- | --- | --- | --- |
| P1 | trades >= 30 on the decisive window | 103 | True |
| P2 | net > 0 at BASE | -474.0861 | False |
| P3 | expectancy > 0 at BASE | -4.6028 | False |
| P4 | net > 0 at 2X_FEES | -433.8269 | False |
| P5 | largest single trade <= 50% of the net | None | False |
| P6 | at least one positive market context | 0 | False |
| R1 | net still > 0 with the largest winner removed | -522.5599 | False |
| R2 | net > 0 in at least 2 of the 3 equal time blocks | 0 | False |
| S1 | DEV gross > 0 on the cross-section: the entry, not the exit, carries it | 205.8053 | True |
| F1 | ACTIVE only: trades/day across the universe >= 3.0 | 0.1581 | False |

Decisive window readings: 103 trades, net -474.0861 USDT, expectancy -4.6028, PF 0.5392, DD 5.448 %, expectancy interval {'low': -6.2137, 'high': -3.3273, 'point': -4.6028}.

Per market context: {'BEAR': {'trades': 21, 'net_usdt': -22.0857, 'expectancy_usdt': -1.0517}, 'BULL': {'trades': 64, 'net_usdt': -327.4132, 'expectancy_usdt': -5.1158}, 'SIDEWAYS': {'trades': 18, 'net_usdt': -124.5871, 'expectancy_usdt': -6.9215}}; exits {'ema_invalidation': 23, 'target': 19, 'trailing_stop': 15, 'stop_loss': 46}; serial dependence {'observations': 103, 'statistic': 'per-trade return in bps', 'lag1_autocorrelation': 0.0918, 'band_2_over_sqrt_n': 0.1971, 'runs': 38, 'expected_runs': 36.7282, 'runs_z': 0.3647}.

### `edge08_active_multiday_range_1h` — **REJECT**

decisive criterion failed on the cross-section: P2, P3, P4, P5, R1, R2, S1, F1; a decisive criterion failed with power on the cross-section; the family is reported with its numbers and is not tuned and re-run on the same window

| # | Criterion | Value | Passed |
| --- | --- | --- | --- |
| P1 | trades >= 30 on the decisive window | 128 | True |
| P2 | net > 0 at BASE | -494.7063 | False |
| P3 | expectancy > 0 at BASE | -3.8649 | False |
| P4 | net > 0 at 2X_FEES | -491.0226 | False |
| P5 | largest single trade <= 50% of the net | None | False |
| P6 | at least one positive market context | 1 | True |
| R1 | net still > 0 with the largest winner removed | -555.8935 | False |
| R2 | net > 0 in at least 2 of the 3 equal time blocks | 0 | False |
| S1 | DEV gross > 0 on the cross-section: the entry, not the exit, carries it | -217.9078 | False |
| F1 | ACTIVE only: trades/day across the universe >= 3.0 | 0.1965 | False |

Decisive window readings: 128 trades, net -494.7063 USDT, expectancy -3.8649, PF 0.6504, DD 5.1288 %, expectancy interval {'low': -7.4629, 'high': -1.2861, 'point': -3.8649}.

Per market context: {'BEAR': {'trades': 18, 'net_usdt': -226.6496, 'expectancy_usdt': -12.5916}, 'BULL': {'trades': 95, 'net_usdt': -343.6966, 'expectancy_usdt': -3.6179}, 'SIDEWAYS': {'trades': 15, 'net_usdt': 75.6399, 'expectancy_usdt': 5.0427}}; exits {'ema_invalidation': 22, 'stop_loss': 60, 'trailing_stop': 23, 'target': 23}; serial dependence {'observations': 128, 'statistic': 'per-trade return in bps', 'lag1_autocorrelation': 0.2681, 'band_2_over_sqrt_n': 0.1768, 'runs': 33, 'expected_runs': 52.75, 'runs_z': -4.3431}.

### `edge08_active_stretch_revert_1h` — REJECT_NO_GROSS_EDGE

the gross screen (C0) failed on the known universe: a setup that loses before any fee cannot be repaired by a fee, so the cross-section was not read with it. the book lost money before any fee on the known universe, so the cross-section was not read with it

### `edge08_quality_breakout_daily` — **REJECT**

decisive criterion failed on the cross-section: P2, P3, P4, P5, P6, R1, R2, S1, F2; a decisive criterion failed with power on the cross-section; the family is reported with its numbers and is not tuned and re-run on the same window

| # | Criterion | Value | Passed |
| --- | --- | --- | --- |
| P1 | trades >= 30 on the decisive window | 30 | True |
| P2 | net > 0 at BASE | -166.6146 | False |
| P3 | expectancy > 0 at BASE | -5.5538 | False |
| P4 | net > 0 at 2X_FEES | -178.1426 | False |
| P5 | largest single trade <= 50% of the net | None | False |
| P6 | at least one positive market context | 0 | False |
| R1 | net still > 0 with the largest winner removed | -240.7207 | False |
| R2 | net > 0 in at least 2 of the 3 equal time blocks | 1 | False |
| S1 | DEV gross > 0 on the cross-section: the entry, not the exit, carries it | -457.4527 | False |
| F2 | QUALITY only: trades/day across the universe >= 0.05 (about one trade per asset every twenty days), reported and decisive as a floor on viability | 0.0461 | False |

Decisive window readings: 30 trades, net -166.6146 USDT, expectancy -5.5538, PF 0.6885, DD 3.0648 %, expectancy interval {'low': -5.5538, 'high': 0.9827, 'point': -5.5538}.

Per market context: {'BEAR': {'trades': 3, 'net_usdt': -68.976, 'expectancy_usdt': -22.992}, 'BULL': {'trades': 21, 'net_usdt': -70.3899, 'expectancy_usdt': -3.3519}, 'SIDEWAYS': {'trades': 6, 'net_usdt': -27.2486, 'expectancy_usdt': -4.5414}}; exits {'stop_loss': 16, 'target': 5, 'ema_invalidation': 2, 'trailing_stop': 5, 'end_of_data': 2}; serial dependence {'observations': 30, 'statistic': 'per-trade return in bps', 'lag1_autocorrelation': 0.1056, 'band_2_over_sqrt_n': 0.3651, 'runs': 9, 'expected_runs': 9.3333, 'runs_z': -0.2296}.

### `edge08_quality_pullback_daily` — REJECT_NO_GROSS_EDGE

the gross screen (C0) failed on the known universe: a setup that loses before any fee cannot be repaired by a fee, so the cross-section was not read with it. the book lost money before any fee on the known universe, so the cross-section was not read with it

### `edge08_quality_reversion_daily` — REJECT_NO_GROSS_EDGE

the gross screen (C0) failed on the known universe: a setup that loses before any fee cannot be repaired by a fee, so the cross-section was not read with it. the book lost money before any fee on the known universe, so the cross-section was not read with it

### `edge_trend_01_4h` — NOT_APPLICABLE

a CURRENT arm: already registered and measured by an earlier work package, read here as the baseline of the comparison; it answers to no criterion of this package

## 4. CURRENT vs PROPOSED on the cross-section

### DEV

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 254 | -53.8317 | -0.2119 | 0.9835 | 5.0058 | 0.232 |
| PROPOSED | `edge08_active_multiday_range_1h` | 170 | -390.7462 | -2.2985 | 0.8295 | 5.401 | 0.1553 |
| PROPOSED | `edge08_quality_breakout_daily` | 25 | -466.7034 | -18.6681 | 0.1505 | 5.1731 | 0.0228 |
| CURRENT | `edge06_trend_fixed` | 39 | -246.5951 | -6.323 | 0.684 | 4.8653 | 0.0356 |
| CURRENT | `edge07_active_thrust` | 91 | -367.8105 | -4.0419 | 0.6757 | 5.086 | 0.0831 |
| CURRENT | `edge_trend_01_4h` | 79 | -384.5606 | -4.8679 | 0.586 | 5.0579 | 0.0721 |

### VAL

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 126 | -371.6063 | -2.9493 | 0.654 | 5.1321 | 0.3443 |
| PROPOSED | `edge08_active_multiday_range_1h` | 119 | -431.63 | -3.6271 | 0.6647 | 5.3071 | 0.3252 |
| PROPOSED | `edge08_quality_breakout_daily` | 34 | 141.0336 | 4.148 | 1.2688 | 3.7281 | 0.0929 |
| CURRENT | `edge06_trend_fixed` | 48 | -496.3485 | -10.3406 | 0.3088 | 5.0347 | 0.1312 |
| CURRENT | `edge07_active_thrust` | 229 | -473.2268 | -2.0665 | 0.5845 | 5.2904 | 0.6258 |
| CURRENT | `edge_trend_01_4h` | 82 | 25.9231 | 0.3161 | 1.0291 | 4.1793 | 0.2241 |

### OOS

| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PROPOSED | `edge08_active_daybreak_1h` | 103 | -474.0861 | -4.6028 | 0.5392 | 5.448 | 0.1581 |
| PROPOSED | `edge08_active_multiday_range_1h` | 128 | -494.7063 | -3.8649 | 0.6504 | 5.1288 | 0.1965 |
| PROPOSED | `edge08_quality_breakout_daily` | 30 | -166.6146 | -5.5538 | 0.6885 | 3.0648 | 0.0461 |
| CURRENT | `edge06_trend_fixed` | 144 | -415.825 | -2.8877 | 0.7735 | 4.7715 | 0.2211 |
| CURRENT | `edge07_active_thrust` | 196 | -350.7431 | -1.7895 | 0.706 | 5.0552 | 0.3009 |
| CURRENT | `edge_trend_01_4h` | 126 | -215.8994 | -1.7135 | 0.8462 | 4.9436 | 0.1934 |

same corpus, same windows, same costs, same risk policy, same simulator; the CURRENT arms are already-closed registrations carried as the baseline and they change no verdict.

## 5. What these verdicts are not

- They are not a permission to trade: `promotion: NONE`, `order_sent: false`. An `ADMIT_PAPER` verdict means a paper lane and nothing else, and the risk-manager's and the release gate's own conditions still apply to it.
- They are not tuned: the parameters are the registered bytes (hashes in `PREREGISTRATION.json`), and a book that failed is reported with its numbers rather than re-parameterised and re-run on this window.
- Six symbols are six symbols: a transfer measured on them is evidence about them.
