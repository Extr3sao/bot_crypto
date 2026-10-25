# WP-EDGE-09E — experiments

*Run at `2026-10-15T05:16:14Z`. Streams: 10. `promotion: NONE`, `order_sent: False`.*

## 1. E-01 — quote imbalance against the measured barrier

`gross` is the **long-only** mean forward move of the high-imbalance quartile, the only direction this runtime's spot product can take.

| Market | Symbol | Horizon (s) | n | IC | Long-only gross (bps) | Spread (bps) | Hit rate | Barrier (bps) | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| perp | BTCUSDT | 1 | 14597 | 0.487104 | 0.218105 | 0.441023 | 0.396547 | 23.1104 | **COST_KILLED** |
| perp | BTCUSDT | 5 | 14593 | 0.414245 | 0.432744 | 0.903422 | 0.57648 | 23.1104 | **COST_KILLED** |
| perp | BTCUSDT | 60 | 14539 | 0.136487 | 0.608791 | 1.276453 | 0.569345 | 23.1104 | **COST_KILLED** |
| perp | ETHUSDT | 1 | 14603 | 0.469459 | 0.277095 | 0.578686 | 0.42137 | 23.1512 | **COST_KILLED** |
| perp | ETHUSDT | 5 | 14598 | 0.366445 | 0.505996 | 1.067329 | 0.576322 | 23.1512 | **COST_KILLED** |
| perp | ETHUSDT | 60 | 14543 | 0.105068 | 0.538565 | 1.113225 | 0.548556 | 23.1512 | **COST_KILLED** |
| spot | BTCUSDT | 1 | 14547 | 0.451048 | 0.161799 | 0.336216 | 0.262376 | 23.0968 | **COST_KILLED** |
| spot | BTCUSDT | 5 | 14543 | 0.511442 | 0.426979 | 0.873074 | 0.470702 | 23.0968 | **COST_KILLED** |
| spot | BTCUSDT | 60 | 14488 | 0.229057 | 0.817203 | 1.747184 | 0.556875 | 23.0968 | **COST_KILLED** |
| spot | ETHUSDT | 1 | 14242 | 0.430489 | 0.279383 | 0.544143 | 0.31882 | 23.1508 | **COST_KILLED** |
| spot | ETHUSDT | 5 | 14238 | 0.386354 | 0.557456 | 1.08789 | 0.518685 | 23.1508 | **COST_KILLED** |
| spot | ETHUSDT | 60 | 14184 | 0.130924 | 0.614868 | 1.472731 | 0.545121 | 23.1508 | **COST_KILLED** |
| perp | BTCUSDT | 1 | 5903 | 0.509842 | 0.282763 | 0.577735 | 0.484746 | 23.1104 | **COST_KILLED** |
| perp | BTCUSDT | 5 | 5898 | 0.385919 | 0.599402 | 1.147747 | 0.614654 | 23.1104 | **COST_KILLED** |
| perp | BTCUSDT | 60 | 5852 | 0.097206 | 0.620064 | 1.497108 | 0.548872 | 23.1104 | **COST_KILLED** |
| perp | ETHUSDT | 1 | 5917 | 0.507102 | 0.342407 | 0.678655 | 0.54023 | 23.1512 | **COST_KILLED** |
| perp | ETHUSDT | 5 | 5913 | 0.343951 | 0.685527 | 1.266418 | 0.640054 | 23.1512 | **COST_KILLED** |
| perp | ETHUSDT | 60 | 5867 | 0.15202 | 1.148407 | 2.264231 | 0.576398 | 23.1512 | **COST_KILLED** |
| perp | SOLUSDT | 1 | 5835 | 0.428714 | 0.456474 | 0.947943 | 0.379973 | 24.0731 | **COST_KILLED** |
| perp | SOLUSDT | 5 | 5831 | 0.342055 | 0.844975 | 1.732418 | 0.546328 | 24.0731 | **COST_KILLED** |
| perp | SOLUSDT | 60 | 5785 | 0.152669 | 1.582703 | 3.238128 | 0.569156 | 24.0731 | **COST_KILLED** |
| spot | BTCUSDT | 1 | 6827 | 0.496633 | 0.27319 | 0.562237 | 0.382181 | 23.0968 | **COST_KILLED** |
| spot | BTCUSDT | 5 | 6823 | 0.472269 | 0.61634 | 1.278824 | 0.570088 | 23.0968 | **COST_KILLED** |
| spot | BTCUSDT | 60 | 6768 | 0.168363 | 0.706983 | 2.158955 | 0.539598 | 23.0968 | **COST_KILLED** |
| spot | ETHUSDT | 1 | 6770 | 0.502687 | 0.361029 | 0.735045 | 0.4013 | 23.1508 | **COST_KILLED** |
| spot | ETHUSDT | 5 | 6766 | 0.429073 | 0.719139 | 1.509923 | 0.575991 | 23.1508 | **COST_KILLED** |
| spot | ETHUSDT | 60 | 6712 | 0.140261 | 0.827246 | 1.841072 | 0.550656 | 23.1508 | **COST_KILLED** |
| spot | SOLUSDT | 1 | 6657 | 0.376647 | 0.409573 | 0.880025 | 0.323918 | 24.0813 | **COST_KILLED** |
| spot | SOLUSDT | 5 | 6653 | 0.293986 | 0.720178 | 1.509811 | 0.488274 | 24.0813 | **COST_KILLED** |
| spot | SOLUSDT | 60 | 6598 | 0.142395 | 1.46279 | 2.891098 | 0.586416 | 24.0813 | **COST_KILLED** |

## 2. E-07 — negative control (the same pipeline, feature destroyed)

| Market | Symbol | Horizon (s) | IC | Long-only gross (bps) | Verdict |
| --- | --- | ---: | ---: | ---: | --- |
| perp | BTCUSDT | 1 | 0.000284 | -0.002019 | **NO_INFORMATION** |
| perp | BTCUSDT | 5 | 0.000641 | -0.018224 | **NO_INFORMATION** |
| perp | BTCUSDT | 60 | -0.012684 | -0.135367 | **NO_GROSS_EDGE** |
| perp | ETHUSDT | 1 | -0.003031 | -0.007125 | **NO_INFORMATION** |
| perp | ETHUSDT | 5 | 0.004618 | -0.009508 | **NO_INFORMATION** |
| perp | ETHUSDT | 60 | -0.001979 | -0.127971 | **NO_INFORMATION** |
| spot | BTCUSDT | 1 | -0.009509 | -0.006573 | **NO_INFORMATION** |
| spot | BTCUSDT | 5 | 0.001201 | 0.003202 | **NO_INFORMATION** |
| spot | BTCUSDT | 60 | 0.018457 | -0.013197 | **NO_GROSS_EDGE** |
| spot | ETHUSDT | 1 | -0.000902 | -0.007062 | **NO_INFORMATION** |
| spot | ETHUSDT | 5 | 0.003946 | -0.001195 | **NO_INFORMATION** |
| spot | ETHUSDT | 60 | -0.001571 | -0.072323 | **NO_INFORMATION** |
| perp | BTCUSDT | 1 | -0.004199 | -0.009405 | **NO_INFORMATION** |
| perp | BTCUSDT | 5 | 0.016604 | -0.058476 | **NO_GROSS_EDGE** |
| perp | BTCUSDT | 60 | 0.011843 | 0.010712 | **COST_KILLED** |
| perp | ETHUSDT | 1 | -0.00258 | 0.010396 | **NO_INFORMATION** |
| perp | ETHUSDT | 5 | 0.000721 | -0.004436 | **NO_INFORMATION** |
| perp | ETHUSDT | 60 | 0.00974 | 0.195002 | **NO_INFORMATION** |
| perp | SOLUSDT | 1 | 0.005818 | 0.028995 | **NO_INFORMATION** |
| perp | SOLUSDT | 5 | 0.01432 | -0.017354 | **NO_GROSS_EDGE** |
| perp | SOLUSDT | 60 | 0.006035 | 0.02509 | **NO_INFORMATION** |
| spot | BTCUSDT | 1 | 0.001153 | 0.000423 | **NO_INFORMATION** |
| spot | BTCUSDT | 5 | 0.005647 | -0.036566 | **NO_INFORMATION** |
| spot | BTCUSDT | 60 | -0.00768 | -0.405189 | **NO_INFORMATION** |
| spot | ETHUSDT | 1 | 0.006042 | 0.028707 | **NO_INFORMATION** |
| spot | ETHUSDT | 5 | 0.000665 | 0.010585 | **NO_INFORMATION** |
| spot | ETHUSDT | 60 | 0.00659 | 0.057622 | **NO_INFORMATION** |
| spot | SOLUSDT | 1 | -0.003034 | 0.000602 | **NO_INFORMATION** |
| spot | SOLUSDT | 5 | -0.023996 | -0.039802 | **NO_GROSS_EDGE** |
| spot | SOLUSDT | 60 | 0.007241 | -0.018368 | **NO_INFORMATION** |

## 3. E-05 — opportunities per day against the ACTIVE objective

`long-only` counts moves a spot book could take; `any direction` also counts downward moves, which this runtime cannot execute and which are reported only for the record. Each row is the sum over streams of a per-day rate that was extrapolated from hours of capture, so it is an upper bound and not a day count.

| Horizon (s) | Streams | Span (h, min-max) | Long-only opp/day | Any-direction opp/day | ACTIVE target | Meets it |
| ---: | ---: | --- | ---: | ---: | ---: | :-: |
| 1 | 10 | 1.999-4.155 | 0.0 | 0.0 | 3.0 | False |
| 5 | 10 | 1.999-4.155 | 0.0 | 0.0 | 3.0 | False |
| 60 | 10 | 1.999-4.155 | 144.061 | 312.121 | 3.0 | True |

| Market | Symbol | Horizon (s) | Selector | Selected/day | Clearing/day (long-only) |
| --- | --- | ---: | --- | ---: | ---: |
| perp | BTCUSDT | 1 | \|imbalance\| >= 0.9588 (q90) | 8439.556 | 0.0 |
| perp | BTCUSDT | 5 | \|imbalance\| >= 0.9588 (q90) | 8439.556 | 0.0 |
| perp | BTCUSDT | 60 | \|imbalance\| >= 0.9584 (q90) | 8404.897 | 0.0 |
| perp | ETHUSDT | 1 | \|imbalance\| >= 0.9611 (q90) | 8445.347 | 0.0 |
| perp | ETHUSDT | 5 | \|imbalance\| >= 0.9611 (q90) | 8439.57 | 0.0 |
| perp | ETHUSDT | 60 | \|imbalance\| >= 0.961 (q90) | 8410.687 | 0.0 |
| spot | BTCUSDT | 1 | \|imbalance\| >= 0.972 (q90) | 8410.395 | 0.0 |
| spot | BTCUSDT | 5 | \|imbalance\| >= 0.972 (q90) | 8410.395 | 0.0 |
| spot | BTCUSDT | 60 | \|imbalance\| >= 0.9719 (q90) | 8375.737 | 0.0 |
| spot | ETHUSDT | 1 | \|imbalance\| >= 0.9382 (q90) | 8237.35 | 0.0 |
| spot | ETHUSDT | 5 | \|imbalance\| >= 0.9383 (q90) | 8231.573 | 0.0 |
| spot | ETHUSDT | 60 | \|imbalance\| >= 0.9378 (q90) | 8202.69 | 0.0 |
| perp | BTCUSDT | 1 | \|imbalance\| >= 0.9776 (q90) | 7105.981 | 0.0 |
| perp | BTCUSDT | 5 | \|imbalance\| >= 0.9776 (q90) | 7093.977 | 0.0 |
| perp | BTCUSDT | 60 | \|imbalance\| >= 0.978 (q90) | 7045.964 | 0.0 |
| perp | ETHUSDT | 1 | \|imbalance\| >= 0.9843 (q90) | 7118.932 | 0.0 |
| perp | ETHUSDT | 5 | \|imbalance\| >= 0.9842 (q90) | 7118.932 | 0.0 |
| perp | ETHUSDT | 60 | \|imbalance\| >= 0.9843 (q90) | 7058.907 | 0.0 |
| perp | SOLUSDT | 1 | \|imbalance\| >= 0.8856 (q90) | 7022.891 | 0.0 |
| perp | SOLUSDT | 5 | \|imbalance\| >= 0.8856 (q90) | 7010.886 | 0.0 |
| perp | SOLUSDT | 60 | \|imbalance\| >= 0.8842 (q90) | 6962.866 | 84.035 |
| spot | BTCUSDT | 1 | \|imbalance\| >= 0.9653 (q90) | 8210.275 | 0.0 |
| spot | BTCUSDT | 5 | \|imbalance\| >= 0.9652 (q90) | 8210.275 | 0.0 |
| spot | BTCUSDT | 60 | \|imbalance\| >= 0.9651 (q90) | 8138.255 | 0.0 |
| spot | ETHUSDT | 1 | \|imbalance\| >= 0.976 (q90) | 8139.554 | 0.0 |
| spot | ETHUSDT | 5 | \|imbalance\| >= 0.976 (q90) | 8139.554 | 0.0 |
| spot | ETHUSDT | 60 | \|imbalance\| >= 0.9761 (q90) | 8079.528 | 0.0 |
| spot | SOLUSDT | 1 | \|imbalance\| >= 0.8219 (q90) | 8007.499 | 0.0 |
| spot | SOLUSDT | 5 | \|imbalance\| >= 0.8219 (q90) | 8007.499 | 0.0 |
| spot | SOLUSDT | 60 | \|imbalance\| >= 0.8219 (q90) | 7935.467 | 60.026 |

## 4. E-06 — what a taker actually pays

| Market | Symbol | Observations | Median shortfall (bps) | Mean (bps) | p90 (bps) |
| --- | --- | ---: | ---: | ---: | ---: |
| perp | BTCUSDT | 0 | None | None | None |
| perp | ETHUSDT | 0 | None | None | None |
| spot | BTCUSDT | 12219 | 0.000599 | 0.20553 | 0.742398 |
| spot | ETHUSDT | 8976 | 0.018736 | 0.474932 | 1.469595 |
| perp | BTCUSDT | 0 | None | None | None |
| perp | ETHUSDT | 0 | None | None | None |
| perp | SOLUSDT | 0 | None | None | None |
| spot | BTCUSDT | 6305 | 0.000591 | 0.322162 | 1.14623 |
| spot | ETHUSDT | 4831 | 0.129279 | 0.544427 | 1.64446 |
| spot | SOLUSDT | 4139 | 0.423639 | 1.103225 | 2.118554 |

## 5. E-04 — price against open interest (5-minute clock)

| Symbol | States | PRICE_DOWN_OI_UP n / mean (bps) | PRICE_UP_OI_UP n / mean |
| --- | ---: | --- | --- |
| BTCUSDT | 36 | 6 / -8.195912 | 10 / 7.258408 |
| ETHUSDT | 38 | 14 / -8.015351 | 9 / 9.536183 |
| BTCUSDT | 17 | 2 / -8.55394 | 6 / 5.381638 |
| ETHUSDT | 16 | 4 / -10.422376 | 4 / 8.961501 |
| SOLUSDT | 11 | 1 / -27.037303 | 3 / 18.088642 |

## 6. E-02 — is the fee schedule what blocks the edge?

| Scenario | Venue | Assets | Cheapest round trip (bps) | Net at best gross | Clears cost |
| --- | --- | ---: | ---: | ---: | :-: |
| `BINANCE_SPOT_STANDARD_TAKER` | Binance | 10 | 22.9866 | -21.403897 | False |
| `MEXC_SPOT_TAKER` | MEXC | 10 | 12.9866 | -11.403897 | False |
| `OKX_SPOT_TAKER` | OKX | 10 | 22.9866 | -21.403897 | False |
| `KRAKENPRO_SPOT_TAKER` | Kraken Pro | 10 | 82.9866 | -81.403897 | False |

## 7. E-03 — capacity at the quoted size

| Market | Symbol | Snapshots | Median notional within 5 bps (USD) | Absorbs 1,000 USD |
| --- | --- | ---: | ---: | :-: |
| perp | BTCUSDT | 123 | 391074.9372 | True |
| perp | ETHUSDT | 124 | 312455.2294 | True |
| perp | SOLUSDT | 119 | 957722.9294 | True |
| spot | BTCUSDT | 4 | 125441.138 | True |
| spot | ETHUSDT | 4 | 41478.1355 | True |
| spot | SOLUSDT | 3 | 234023.5061 | True |

## 8. Verdicts

| Hypothesis | Track | Classification | Failed filter | Why |
| --- | --- | --- | --- | --- |
| `E-01` | ACTIVE | **COST_KILLED** | F2 | best measured cell perp/SOLUSDT h=60s gross 1.582703 bps vs 24.0731 bps barrier — gross 1.5827 bps is below the measured round trip 24.0731 bps (cells: {'COST_KILLED': 30}) |
| `E-02` | CROSS-VENUE | **COST_KILLED** | F2 | the cheapest registered schedule (MEXC_SPOT_TAKER at 12.9866 bps) still exceeds the best measured gross (1.582703 bps): the fee schedule is not the only constraint |
| `E-03` | ACTIVE | **OBSERVED** | F4 | spot depth snapshots are rare in this capture, so a spot capacity claim rests on a small number of observations and is reported as such |
| `E-04` | QUALITY | **INSUFFICIENT_SAMPLE** | — | PRICE_DOWN_OI_UP n=14 mean=-8.015351 bps against a barrier of 23.1512 bps |
| `E-05` | ACTIVE | **OBSERVED** | — | the tape clears the barrier at h=60s at 144.061 long-only opportunities/day (upper bound, long-only, extrapolated from 1.999-4.155 h of capture), so the ACTIVE frequency target is not what blocks the book at those horizons |
| `E-06` | EXECUTION | **OBSERVED** | — | median measured taker shortfall 0.0187 bps against the modelled spread+impact components |
| `E-07` | GUARD | **NO_GROSS_EDGE** | — | negative control verdicts: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION'] |

`FALSE_SUCCESS` guard: the negative control ended **['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION']**; `false_success = 0`.

`promotion: NONE`, `order_sent: False`.
