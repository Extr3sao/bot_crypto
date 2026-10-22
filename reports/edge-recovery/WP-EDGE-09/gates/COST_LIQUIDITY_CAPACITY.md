# WP-EDGE-09D — cost, liquidity, capacity and frequency

*Measured on `10` streams of the forward capture, 1 s grid. Cost model: V4 over the V3 venue specs. `promotion: NONE`.*

## 1. What the tape itself costs — measured spread

| Run | Market | Symbol | Observations | Median (bps) | Mean (bps) | p90 (bps) |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `paper-lab-continuous-02` | perp | BTCUSDT | 14599 | 0.011986 | 0.013356 | 0.012 |
| `paper-lab-continuous-02` | perp | ETHUSDT | 14604 | 0.037425 | 0.03838 | 0.037487 |
| `paper-lab-continuous-02` | spot | BTCUSDT | 14548 | 0.001198 | 0.001666 | 0.001199 |
| `paper-lab-continuous-02` | spot | ETHUSDT | 14244 | 0.037406 | 0.039625 | 0.037468 |
| `paper-strategy-lifecycle-shadow-02` | perp | BTCUSDT | 5904 | 0.011799 | 0.015267 | 0.011821 |
| `paper-strategy-lifecycle-shadow-02` | perp | ETHUSDT | 5918 | 0.037049 | 0.040117 | 0.037114 |
| `paper-strategy-lifecycle-shadow-02` | perp | SOLUSDT | 5836 | 0.845201 | 0.847527 | 0.84814 |
| `paper-strategy-lifecycle-shadow-02` | spot | BTCUSDT | 6829 | 0.001179 | 0.003148 | 0.001182 |
| `paper-strategy-lifecycle-shadow-02` | spot | ETHUSDT | 6772 | 0.037034 | 0.038752 | 0.0371 |
| `paper-strategy-lifecycle-shadow-02` | spot | SOLUSDT | 6659 | 0.844916 | 0.849442 | 0.847709 |

## 2. The barrier, per asset and market, on every registered venue

| Market | Symbol | Scenario | Spread meas. | Round trip (bps) | Required 1.5x (bps) | Fee share |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| perp | BTCUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 14599 | 23.0045 | 34.5068 | 86.9% |
| perp | BTCUSDT | `MEXC_SPOT_TAKER` | 14599 | 13.0045 | 19.5068 | 76.9% |
| perp | BTCUSDT | `OKX_SPOT_TAKER` | 14599 | 23.0045 | 34.5068 | 86.9% |
| perp | BTCUSDT | `KRAKENPRO_SPOT_TAKER` | 14599 | 83.0045 | 124.5068 | 96.4% |
| perp | ETHUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 14604 | 23.0646 | 34.5969 | 86.7% |
| perp | ETHUSDT | `MEXC_SPOT_TAKER` | 14604 | 13.0646 | 19.5969 | 76.5% |
| perp | ETHUSDT | `OKX_SPOT_TAKER` | 14604 | 23.0646 | 34.5969 | 86.7% |
| perp | ETHUSDT | `KRAKENPRO_SPOT_TAKER` | 14604 | 83.0646 | 124.5969 | 96.3% |
| spot | BTCUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 14548 | 22.9866 | 34.48 | 87.0% |
| spot | BTCUSDT | `MEXC_SPOT_TAKER` | 14548 | 12.9866 | 19.48 | 77.0% |
| spot | BTCUSDT | `OKX_SPOT_TAKER` | 14548 | 22.9866 | 34.48 | 87.0% |
| spot | BTCUSDT | `KRAKENPRO_SPOT_TAKER` | 14548 | 82.9866 | 124.48 | 96.4% |
| spot | ETHUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 14244 | 23.059 | 34.5886 | 86.7% |
| spot | ETHUSDT | `MEXC_SPOT_TAKER` | 14244 | 13.059 | 19.5886 | 76.6% |
| spot | ETHUSDT | `OKX_SPOT_TAKER` | 14244 | 23.059 | 34.5886 | 86.7% |
| spot | ETHUSDT | `KRAKENPRO_SPOT_TAKER` | 14244 | 83.059 | 124.5886 | 96.3% |
| perp | BTCUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 5904 | 23.1104 | 34.6656 | 86.5% |
| perp | BTCUSDT | `MEXC_SPOT_TAKER` | 5904 | 13.1104 | 19.6656 | 76.3% |
| perp | BTCUSDT | `OKX_SPOT_TAKER` | 5904 | 23.1104 | 34.6656 | 86.5% |
| perp | BTCUSDT | `KRAKENPRO_SPOT_TAKER` | 5904 | 83.1104 | 124.6656 | 96.3% |
| perp | ETHUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 5918 | 23.1512 | 34.7268 | 86.4% |
| perp | ETHUSDT | `MEXC_SPOT_TAKER` | 5918 | 13.1512 | 19.7268 | 76.0% |
| perp | ETHUSDT | `OKX_SPOT_TAKER` | 5918 | 23.1512 | 34.7268 | 86.4% |
| perp | ETHUSDT | `KRAKENPRO_SPOT_TAKER` | 5918 | 83.1512 | 124.7268 | 96.2% |
| perp | SOLUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 5836 | 24.0731 | 36.1096 | 83.1% |
| perp | SOLUSDT | `MEXC_SPOT_TAKER` | 5836 | 14.0731 | 21.1096 | 71.1% |
| perp | SOLUSDT | `OKX_SPOT_TAKER` | 5836 | 24.0731 | 36.1096 | 83.1% |
| perp | SOLUSDT | `KRAKENPRO_SPOT_TAKER` | 5836 | 84.0731 | 126.1096 | 95.2% |
| spot | BTCUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 6829 | 23.0968 | 34.6452 | 86.6% |
| spot | BTCUSDT | `MEXC_SPOT_TAKER` | 6829 | 13.0968 | 19.6452 | 76.4% |
| spot | BTCUSDT | `OKX_SPOT_TAKER` | 6829 | 23.0968 | 34.6452 | 86.6% |
| spot | BTCUSDT | `KRAKENPRO_SPOT_TAKER` | 6829 | 83.0968 | 124.6452 | 96.3% |
| spot | ETHUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 6772 | 23.1508 | 34.7262 | 86.4% |
| spot | ETHUSDT | `MEXC_SPOT_TAKER` | 6772 | 13.1508 | 19.7262 | 76.0% |
| spot | ETHUSDT | `OKX_SPOT_TAKER` | 6772 | 23.1508 | 34.7262 | 86.4% |
| spot | ETHUSDT | `KRAKENPRO_SPOT_TAKER` | 6772 | 83.1508 | 124.7262 | 96.2% |
| spot | SOLUSDT | `BINANCE_SPOT_STANDARD_TAKER` | 6659 | 24.0813 | 36.122 | 83.1% |
| spot | SOLUSDT | `MEXC_SPOT_TAKER` | 6659 | 14.0813 | 21.122 | 71.0% |
| spot | SOLUSDT | `OKX_SPOT_TAKER` | 6659 | 24.0813 | 36.122 | 83.1% |
| spot | SOLUSDT | `KRAKENPRO_SPOT_TAKER` | 6659 | 84.0813 | 126.122 | 95.1% |

## 3. Capacity: what the captured book actually offers

Order size quoted at **1000 USD**; the runtime's own floor for an order is 20 USDT.

| Market | Symbol | Snapshots | Levels | Top of book (USD) | 5 bps band (USD) | 25 bps band (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| perp | BTCUSDT | 123 | 10 | 882698.40 | 391074.94 | 391074.94 |
| perp | ETHUSDT | 124 | 10 | 637621.88 | 312455.23 | 312455.23 |
| perp | SOLUSDT | 119 | 10 | 198464.13 | 957722.93 | 1894649.80 |
| spot | BTCUSDT | 4 | 10 | 687134.90 | 125441.14 | 125441.14 |
| spot | ETHUSDT | 4 | 10 | 196102.15 | 41478.14 | 41478.14 |
| spot | SOLUSDT | 3 | 10 | 77774.10 | 234023.51 | 347365.00 |

## 4. Frequency: the tape's own upper bound

How often the mid itself moves by at least the admission barrier in the horizon. No predictor can exceed this: a trade whose move does not clear the barrier cannot pay for itself. The span column is the capture the per-day rate was extrapolated from, in hours: this is a rate, not a day count.

| Horizon (s) | Span (h, min-max) | Streams summed | Barrier-clearing per day | ACTIVE target | Meets it |
| ---: | --- | ---: | ---: | ---: | :-: |
| 1 | 1.999-4.155 | 10 | 0.0 | 3.0 | False |
| 5 | 1.999-4.155 | 10 | 0.0 | 3.0 | False |
| 60 | 1.999-4.155 | 10 | 48.018 | 3.0 | True |
| 900 | 1.999-4.155 | 10 | 179.619 | 3.0 | True |
| 3600 | 1.999-4.155 | 10 | 11.553 | 3.0 | True |

## 5. The bar the barrier sets, per stream and horizon

| Market | Symbol | Horizon (s) | Clearing per day | Barrier (bps) |
| --- | --- | ---: | ---: | ---: |
| perp | BTCUSDT | 1 | 0.0 | 23.1104 |
| perp | BTCUSDT | 5 | 0.0 | 23.1104 |
| perp | BTCUSDT | 60 | 0.0 | 23.1104 |
| perp | BTCUSDT | 900 | 5.777 | 23.1104 |
| perp | BTCUSDT | 3600 | 5.777 | 23.1104 |
| perp | ETHUSDT | 1 | 0.0 | 23.1512 |
| perp | ETHUSDT | 5 | 0.0 | 23.1512 |
| perp | ETHUSDT | 60 | 0.0 | 23.1512 |
| perp | ETHUSDT | 900 | 0.0 | 23.1512 |
| perp | ETHUSDT | 3600 | 0.0 | 23.1512 |
| spot | BTCUSDT | 1 | 0.0 | 23.0968 |
| spot | BTCUSDT | 5 | 0.0 | 23.0968 |
| spot | BTCUSDT | 60 | 0.0 | 23.0968 |
| spot | BTCUSDT | 900 | 5.776 | 23.0968 |
| spot | BTCUSDT | 3600 | 5.776 | 23.0968 |
| spot | ETHUSDT | 1 | 0.0 | 23.1508 |
| spot | ETHUSDT | 5 | 0.0 | 23.1508 |
| spot | ETHUSDT | 60 | 0.0 | 23.1508 |
| spot | ETHUSDT | 900 | 0.0 | 23.1508 |
| spot | ETHUSDT | 3600 | 0.0 | 23.1508 |
| perp | BTCUSDT | 1 | 0.0 | 23.1104 |
| perp | BTCUSDT | 5 | 0.0 | 23.1104 |
| perp | BTCUSDT | 60 | 12.003 | 23.1104 |
| perp | BTCUSDT | 900 | 12.003 | 23.1104 |
| perp | BTCUSDT | 3600 | 0.0 | 23.1104 |
| perp | ETHUSDT | 1 | 0.0 | 23.1512 |
| perp | ETHUSDT | 5 | 0.0 | 23.1512 |
| perp | ETHUSDT | 60 | 0.0 | 23.1512 |
| perp | ETHUSDT | 900 | 24.01 | 23.1512 |
| perp | ETHUSDT | 3600 | 0.0 | 23.1512 |
| perp | SOLUSDT | 1 | 0.0 | 24.0731 |
| perp | SOLUSDT | 5 | 0.0 | 24.0731 |
| perp | SOLUSDT | 60 | 24.01 | 24.0731 |
| perp | SOLUSDT | 900 | 48.02 | 24.0731 |
| perp | SOLUSDT | 3600 | 0.0 | 24.0731 |
| spot | BTCUSDT | 1 | 0.0 | 23.0968 |
| spot | BTCUSDT | 5 | 0.0 | 23.0968 |
| spot | BTCUSDT | 60 | 0.0 | 23.0968 |
| spot | BTCUSDT | 900 | 24.007 | 23.0968 |
| spot | BTCUSDT | 3600 | 0.0 | 23.0968 |
| spot | ETHUSDT | 1 | 0.0 | 23.1508 |
| spot | ETHUSDT | 5 | 0.0 | 23.1508 |
| spot | ETHUSDT | 60 | 0.0 | 23.1508 |
| spot | ETHUSDT | 900 | 24.01 | 23.1508 |
| spot | ETHUSDT | 3600 | 0.0 | 23.1508 |
| spot | SOLUSDT | 1 | 0.0 | 24.0813 |
| spot | SOLUSDT | 5 | 0.0 | 24.0813 |
| spot | SOLUSDT | 60 | 12.005 | 24.0813 |
| spot | SOLUSDT | 900 | 36.016 | 24.0813 |
| spot | SOLUSDT | 3600 | 0.0 | 24.0813 |
