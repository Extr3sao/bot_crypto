# WP-EDGE-07 Track B — the fixed-target trend book, validated on a window nobody had read

*Run at `2026-10-14T09:02:56Z` (`EDGE07-VALIDATION-20261014T090256Z`). Parameters frozen by the pre-registration, committed before the holdout was fetched.*

## 1. The verdict

**`REJECT`** — decisive criterion failed on NEW_HOLDOUT: P2, P3, P4, P5, P6, R1, R2

Parameters under test: `9ceb20fc7d4500c3…`, the registered value (`9ceb20fc7d4500c3…`) — match: `True`.

| # | Criterion | Value | Passed |
| --- | --- | --- | --- |
| P1 | trades >= 30 | 65 | True |
| P2 | net > 0 at BASE | -140.3041 | False |
| P3 | expectancy > 0 at BASE | -2.1585 | False |
| P4 | net > 0 at 2X_FEES | -205.2287 | False |
| P5 | largest single trade <= 50% of the net | None | False |
| P6 | at least one positive regime | 0 | False |
| R1 | net still > 0 with the largest winner removed | -170.085 | False |
| R2 | net > 0 in at least 2 of 3 time blocks | 1 | False |
| S1 | DEV gross > 0 | 1746.0725 | True |

The frozen admission gate, applied to the new window for comparability: **REJECT** — oos net -140.30 USDT <= 0 after costs; oos expectancy -2.1585 USDT/trade <= 0; oos has 0 profitable regime(s), fewer than the required 1; oos net turns negative under 2x fees (-205.23 USDT): no cost margin.

## 2. The new window, and what it is

- Range: `{'start': 1772323200000, 'end': 1791964800000}` — fetched `2026-10-14T08:56:16Z` from public Binance REST, digest `196884f9e719315e…`, gaps `0`.
- 4h coverage after aggregation: {'BTC': 1363, 'ETH': 1363, 'SOL': 1363} (minimum declared 300).

## 3. Every window, BASE and the cost stress

| Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps | Largest share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEV | BASE | 584 | 1746.0725 | 579.8793 | 109.9037 | **1056.2895** | 1.8087 | 1.1966 | 4.0367 | 0.7219 | 23.8579 | 0.0743 |
| DEV | 2X_FEES | 503 | 1194.7167 | 996.1046 | 94.3951 | **104.2169** | 0.2072 | 1.0205 | 4.9759 | 0.0889 | 43.8875 | 0.7245 |
| DEV | ADVERSE | 495 | 1232.2937 | 979.4476 | 229.4777 | **23.3684** | 0.0472 | 1.0046 | 4.9225 | 0.0307 | 49.473 | 3.1948 |
| VAL | BASE | 136 | 15.2337 | 135.6697 | 25.7133 | **-146.1493** | -1.0746 | 0.869 | 3.5367 | -0.575 | 23.7887 | None |
| VAL | 2X_FEES | 136 | 15.4922 | 271.3223 | 25.7116 | **-281.5418** | -2.0702 | 0.7677 | 4.1803 | -1.0965 | 43.7873 | None |
| VAL | ADVERSE | 136 | 15.7768 | 271.2276 | 63.5466 | **-318.9974** | -2.3456 | 0.7424 | 4.3574 | -1.2409 | 49.3543 | None |
| OOS_CONSULTED | BASE | 113 | 364.8426 | 113.3434 | 21.4818 | **230.0174** | 2.0356 | 1.321 | 1.5329 | 0.9585 | 23.8629 | 0.2219 |
| OOS_CONSULTED | 2X_FEES | 113 | 364.8426 | 226.6867 | 21.4818 | **116.674** | 1.0325 | 1.1477 | 1.7626 | 0.4887 | 43.9236 | 0.4284 |
| OOS_CONSULTED | ADVERSE | 113 | 364.7408 | 226.6233 | 53.0963 | **85.0213** | 0.7524 | 1.105 | 1.8279 | 0.3587 | 49.5079 | 0.5843 |
| NEW_HOLDOUT | BASE | 65 | -63.0744 | 64.9246 | 12.3051 | **-140.3041** | -2.1585 | 0.671 | 2.1413 | -1.2461 | 23.763 | None |
| NEW_HOLDOUT | 2X_FEES | 65 | -63.0744 | 129.8492 | 12.3051 | **-205.2287** | -3.1574 | 0.5707 | 2.4995 | -1.7838 | 43.7398 | None |
| NEW_HOLDOUT | ADVERSE | 65 | -63.0568 | 129.8131 | 30.4142 | **-223.2841** | -3.4351 | 0.5465 | 2.5973 | -1.9353 | 49.3007 | None |

## 4. The four added readings, on the new window

- Bootstrap (90 %, 1000 resamples of 20 trades, seed 20261014): expectancy -2.1585 USDT, CI [-5.1501, 1.0015]; net CI [-334.7546, 65.097].
- Time blocks: 1 of 3 positive — block 1 (2026-03-01…2026-05-15) 23 trades, net -123.4348; block 2 (2026-05-15…2026-07-30) 9 trades, net -67.6398; block 3 (2026-07-30…2026-10-14) 33 trades, net 50.7705.
- Serial dependence: lag-1 autocorrelation 0.5073 against a ±0.2481 band; runs 11 against 21.8 expected (z=-4.2574).

| Asset | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BTC | 16 | -0.8085 | -0.0505 |
| ETH | 27 | -117.666 | -4.358 |
| SOL | 22 | -21.8296 | -0.9923 |

| Market context | Trades | Net | Expectancy |
| --- | --- | --- | --- |
| BEAR | 39 | -67.0807 | -1.72 |
| BULL | 17 | -59.3066 | -3.4886 |
| SIDEWAYS | 9 | -13.9167 | -1.5463 |

## 5. Was the new window read with the same instrument?

Re-derived consulted-window figures against the artefacts that published them: **all equal** (10 figures checked).

| Figure | Mine | Published | Equal | Source |
| --- | --- | --- | --- | --- |
| `DEV/BASE` | 584 trades, 1056.2895 USDT | 584 trades, 1056.2895 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `DEV/2X_FEES` | 503 trades, 104.2169 USDT | 503 trades, 104.2169 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `DEV/ADVERSE` | 495 trades, 23.3684 USDT | 495 trades, 23.3684 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `VAL/BASE` | 136 trades, -146.1493 USDT | 136 trades, -146.1493 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `VAL/2X_FEES` | 136 trades, -281.5418 USDT | 136 trades, -281.5418 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `VAL/ADVERSE` | 136 trades, -318.9974 USDT | 136 trades, -318.9974 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `OOS_CONSULTED/BASE` | 113 trades, 230.0174 USDT | 113 trades, 230.0174 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `OOS_CONSULTED/2X_FEES` | 113 trades, 116.674 USDT | 113 trades, 116.674 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `OOS_CONSULTED/ADVERSE` | 113 trades, 85.0213 USDT | 113 trades, 85.0213 USDT | True | `reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json` |
| `TRAILING_OOS_CONSULTED/BASE` | 52 trades, 208.0056 USDT | 52 trades, 208.0056 USDT | True | `reports/edge-recovery/WP-EDGE-01/STRATEGY_RESULTS.json` |

## 6. The comparison arm: the same window, the trailing exit

| Book | Trades | Net | Expectancy | PF | DD % | Largest share | Exits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fixed 3xATR target | 65 | -140.3041 | -2.1585 | 0.671 | 2.1413 | None | {'stop_loss': 52, 'target': 13} |
| frozen trailing | 28 | 61.0046 | 2.1787 | 1.1905 | 2.0939 | 2.2373 | {'stop_loss': 16, 'trailing_stop': 12} |

same corpus, same window, same costs, same risk policy, same simulator; the only difference is the exit rule, which is what the comparison is for.

## 7. What this does not do

- It promotes nothing: `promotion: NONE`, `order_sent: false`, no capital, no orders. An
  `ADMIT_PAPER` verdict is an admission to a paper lane, and the risk-manager's and the
  release gate's own conditions still apply to it.
- It tunes nothing: the parameters are the pre-registered bytes, and the holdout window
  is read once. A parameter that would have helped is a proposal for a new registration.
- The continuity windows were read before this work package; the only unread window here
  is `NEW_HOLDOUT`, and every claim above that rests on `NEW_HOLDOUT` says so.
