# WP-EDGE-06 — what the frozen books earned, and where the intraday loss comes from

*Read at `2026-10-14T08:07:11Z`, from the WP-EDGE-01 campaign artefacts at `params_hash d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77`.*

## 1. The books, as measured by the campaign that owns them

| Book | Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Cost bps/trade | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge_intra_01` | DEV | BASE | 290 | -151.71 | 289.79 | 54.92 | **-496.43** | -1.7118 | 0.3224 | 5.04 | 23.77 | `REJECT` |
| `edge_intra_01` | OOS | BASE | 63 | -19.91 | 62.97 | 11.93 | **-94.81** | -1.5049 | 0.3028 | 0.95 | 23.78 | `REJECT` |
| `edge_intra_01` | VAL | BASE | 344 | -70.15 | 343.86 | 65.17 | **-479.18** | -1.3930 | 0.3722 | 4.83 | 23.78 | `REJECT` |
| `edge_intra_02` | DEV | BASE | 135 | -29.36 | 134.95 | 25.58 | **-189.88** | -1.4065 | 0.4434 | 2.12 | 23.78 | `REJECT` |
| `edge_intra_02` | OOS | BASE | 14 | 4.03 | 14.00 | 2.65 | **-12.63** | -0.9020 | 0.5454 | 0.31 | 23.79 | `REJECT` |
| `edge_intra_02` | VAL | BASE | 72 | -16.97 | 71.97 | 13.64 | **-102.58** | -1.4247 | 0.4155 | 1.22 | 23.78 | `REJECT` |
| `edge_intra_02_no_fvg` | DEV | BASE | 270 | -179.93 | 269.77 | 51.13 | **-500.83** | -1.8549 | 0.2930 | 5.02 | 23.77 | `REJECT` |
| `edge_intra_02_no_fvg` | OOS | BASE | 45 | -15.60 | 44.98 | 8.52 | **-69.10** | -1.5355 | 0.2776 | 0.73 | 23.78 | `REJECT` |
| `edge_intra_02_no_fvg` | VAL | BASE | 207 | -42.87 | 206.92 | 39.22 | **-289.00** | -1.3961 | 0.3487 | 2.94 | 23.78 | `REJECT` |
| `edge_trend_01_4h` | DEV | BASE | 223 | 2,128.91 | 174.63 | 33.10 | **1,921.18** | 8.6152 | 1.7782 | 4.28 | 24.08 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_4h` | OOS | BASE | 52 | 264.32 | 47.34 | 8.97 | **208.01** | 4.0001 | 1.3312 | 2.57 | 23.92 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_4h` | VAL | BASE | 58 | 62.52 | 48.75 | 9.24 | **4.53** | 0.0780 | 1.0068 | 4.10 | 23.82 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_1d` | DEV | BASE | 39 | 943.79 | 14.53 | 2.75 | **926.51** | 23.7566 | 3.9338 | 1.17 | 25.44 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_1d` | OOS | BASE | 13 | -110.74 | 6.61 | 1.25 | **-118.60** | -9.1231 | 0.4192 | 1.76 | 23.39 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_1d` | VAL | BASE | 20 | 95.55 | 7.58 | 1.44 | **86.54** | 4.3269 | 1.2740 | 2.94 | 24.09 | `INSUFFICIENT_EVIDENCE` |

Costs are not re-derived from a curve: each row is the sum of the `fees` and `price_costs` the simulator wrote per trade.

## 2. The intraday book, decomposed

| Window:scenario | Trades | Gross | Costs | Net | Gross bps/trade | Cost bps/trade | Cost share of the loss |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `edge_intra_01` DEV:BASE | 290 | -151.71 | 344.72 | **-496.43** | -10.46 | 23.77 | 69.4 % |
| `edge_intra_01` DEV:2X_FEES | 197 | -70.62 | 431.10 | **-501.72** | -7.17 | 43.77 | 85.9 % |
| `edge_intra_01` DEV:ADVERSE | 169 | -79.37 | 416.80 | **-496.17** | -9.39 | 49.33 | 84.0 % |
| `edge_intra_01` VAL:BASE | 344 | -70.15 | 409.04 | **-479.18** | -4.08 | 23.78 | 85.4 % |
| `edge_intra_01` VAL:2X_FEES | 230 | -5.43 | 503.48 | **-508.92** | -0.47 | 43.78 | 98.9 % |
| `edge_intra_01` VAL:ADVERSE | 209 | 10.90 | 515.72 | **-504.82** | 1.04 | 49.35 | 102.2 % |
| `edge_intra_01` OOS:BASE | 63 | -19.91 | 74.90 | **-94.81** | -6.32 | 23.78 | 79.0 % |
| `edge_intra_01` OOS:2X_FEES | 52 | -19.41 | 113.79 | **-133.20** | -7.47 | 43.77 | 85.4 % |
| `edge_intra_01` OOS:ADVERSE | 46 | -11.56 | 113.47 | **-125.04** | -5.03 | 49.34 | 90.8 % |

### What the arithmetic says

- `edge_intra_01` — **NO_GROSS_EDGE**. the gross expectation is negative in every window measured, before a single fee is charged: DEV:BASE -151.71 USDT over 290 trades (-10.46 bps/trade); OOS:BASE -19.91 USDT over 63 trades (-6.32 bps/trade); VAL:BASE -70.15 USDT over 344 trades (-4.08 bps/trade). Costs are the larger part of the net loss, but they are not the cause: a book that needed only a fee cut would show a positive gross against a negative net. Lowering fees cannot move a negative expectancy across zero — only a different setup, a different entry, or a longer hold can.

### The same book by asset, entry trend state and market context (DEV, BASE)

| Split | Trades | Gross | Costs | Net | Gross bps/trade |
| --- | --- | --- | --- | --- | --- |
| asset: `BTC` | 109 | -28.35 | 129.60 | -157.95 | -5.20 |
| asset: `ETH` | 83 | -59.13 | 98.64 | -157.78 | -14.25 |
| asset: `SOL` | 98 | -64.23 | 116.48 | -180.71 | -13.11 |
| entry trend state: `UP` | 290 | -151.71 | 344.72 | -496.43 | -10.46 |
| market context: `BULL` | 290 | -151.71 | 344.72 | -496.43 | -10.46 |
| exit reason: `invalidation` | 73 | -131.73 | 86.66 | -218.39 | -36.09 |
| exit reason: `stop_loss` | 130 | -306.16 | 154.25 | -460.40 | -47.10 |
| exit reason: `target` | 40 | 258.47 | 47.88 | 210.59 | 129.23 |
| exit reason: `trailing_stop` | 47 | 27.71 | 55.93 | -28.22 | 11.79 |

## 3. Where these numbers come from

| Artefact | sha256 |
| --- | --- |
| `reports/edge-recovery/WP-EDGE-01/STRATEGY_RESULTS.json` | `4c4e9a19aa4dcd0a39535a0001f960ee85c7a35199125cce2165bab5f2b308b4` |
| `reports/edge-recovery/WP-EDGE-01/TRADES.csv` | `36eb8f34dfd5f3e47375da0f4b83a3bc0c49c0c83fc1b9396ee16676ee5f5d1d` |

*`run_id`: `EDGE06-ECON-20261014T080711Z`. This audit measures nothing new: it restates the frozen campaign's own fields, and the digests above are what makes that checkable.*

Nothing here promotes a strategy, sizes an order or touches a limit: `promotion: NONE`, `order_sent: false`.
