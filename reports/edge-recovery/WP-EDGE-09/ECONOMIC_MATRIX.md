# WP-EDGE-09 — economic matrix

*What would have to be true for each measured stream to pay, on the admission scenario (Binance spot VIP0 taker) and on every registered venue schedule.*

| Market | Symbol | Round trip (bps) | Required 1.5x | Fee share | Best horizon (s) | Best gross (bps) | Net (bps) | IC | n | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| perp | BTCUSDT | 23.1104 | 34.6656 | 86.5% | 60 | 0.620064 | -22.490336 | 0.097206 | 5852 | **COST_KILLED** |
| perp | ETHUSDT | 23.1512 | 34.7268 | 86.4% | 60 | 1.148407 | -22.002793 | 0.15202 | 5867 | **COST_KILLED** |
| perp | SOLUSDT | 24.0731 | 36.1096 | 83.1% | 60 | 1.582703 | -22.490397 | 0.152669 | 5785 | **COST_KILLED** |
| spot | BTCUSDT | 23.0968 | 34.6452 | 86.6% | 60 | 0.817203 | -22.279597 | 0.229057 | 14488 | **COST_KILLED** |
| spot | ETHUSDT | 23.1508 | 34.7262 | 86.4% | 60 | 0.827246 | -22.323554 | 0.140261 | 6712 | **COST_KILLED** |
| spot | SOLUSDT | 24.0813 | 36.122 | 83.1% | 60 | 1.46279 | -22.61851 | 0.142395 | 6598 | **COST_KILLED** |

## Venue comparison

| Scenario | Venue | Cheapest round trip (bps) | Fee (bps) | Net at best gross | Clears cost |
| --- | --- | ---: | ---: | ---: | :-: |
| `BINANCE_SPOT_STANDARD_TAKER` | Binance | 22.9866 | 20.0 | -21.403897 | False |
| `MEXC_SPOT_TAKER` | MEXC | 12.9866 | 10.0 | -11.403897 | False |
| `OKX_SPOT_TAKER` | OKX | 22.9866 | 20.0 | -21.403897 | False |
| `KRAKENPRO_SPOT_TAKER` | Kraken Pro | 82.9866 | 80.0 | -81.403897 | False |

## Frequency the tape offers, per horizon

| Horizon (s) | Streams | Barrier-clearing windows per day (non-overlapping) | ACTIVE target | Meets it |
| ---: | ---: | ---: | ---: | :-: |
| 1 | 10 | 0.0 | 3.0 | False |
| 5 | 10 | 0.0 | 3.0 | False |
| 60 | 10 | 48.018 | 3.0 | True |
| 900 | 10 | 179.619 | 3.0 | True |
| 3600 | 10 | 11.553 | 3.0 | True |

## Capacity

| Market | Symbol | Snapshots | Median notional inside 5 bps (USD) | Absorbs the 1,000 USD quote |
| --- | --- | ---: | ---: | :-: |
| perp | BTCUSDT | 123 | 391074.9372 | True |
| perp | ETHUSDT | 124 | 312455.2294 | True |
| perp | SOLUSDT | 119 | 957722.9294 | True |
| spot | BTCUSDT | 4 | 125441.138 | True |
| spot | ETHUSDT | 4 | 41478.1355 | True |
| spot | SOLUSDT | 3 | 234023.5061 | True |
