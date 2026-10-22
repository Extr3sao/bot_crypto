# ROBUSTEZ DE TENDENCIA 4h — WP-EDGE-02A

| | |
|---|---|
| experimento | `ROB-EDGE01-TREND-4H` |
| responde a | `H3` |
| candidato congelado | `edge_trend_01` (4h) |
| ventana de decision | `OOS` |
| HEAD al ejecutar | `87f23577e0937c95a190187f23728a7b56349065` |
| params_hash | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| veredicto | **`INSUFFICIENT_EVIDENCE`** |

WP-EDGE-01 refused the frozen 4h trend ruleset for one reason: the largest winning trade was 0.7987 of the OOS net against a 0.50 limit. Beyond that single number — how much of the OOS reading survives dropping the largest winner (and the three largest), which asset and which regime carry it, does it survive the adverse cost plane, and what interval does the sample support once the trades' own autocorrelation is taken into account?

## Reproduccion del cierre anterior

- comparado con `reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json`: **identico** (16 comparaciones)

## Veredicto

- **`INSUFFICIENT_EVIDENCE`** — the edge is not contradicted but the declared requirements are not met: concentration_within_limit: largest trade is 0.7987 of the OOS net (limit 0.5, unchanged from WP-EDGE-01)
- `oos_trades_floor`: **PASS** — 52 OOS trades vs floor 30
- `oos_net_positive`: **PASS** — OOS net 208.0056 USDT
- `oos_net_positive_per_dropping_largest_winner`: **PASS** — OOS net without the largest winner 41.8740 USDT (removed 166.1317)
- `concentration_within_limit`: **FAIL** — largest trade is 0.7987 of the OOS net (limit 0.5, unchanged from WP-EDGE-01)
- `assets_positive`: **PASS** — 2/3 single-asset OOS books positive (BTC, ETH) vs required 2
- `periods_positive`: **PASS** — 2/3 OOS periods positive (2025H1, 2025H2) vs required 2
- `adverse_cost_plane_positive`: **PASS** — OOS net under the ADVERSE plane (fees x2, slippage/impact x3) 146.8908 USDT
- `hac_interval_upper_end_positive`: **PASS** — 95% HAC interval on expectancy [-9.273542, 17.273759] (lag 3)
- `drawdown_below_buy_and_hold`: **PASS** — OOS max drawdown 2.5670% vs the deepest buy & hold drawdown 73.2008%

### Intervalos de incertidumbre

- `DEV:BASE`: HAC [2.4224, 14.8079] con lag 4; bootstrap [2.7683, 14.3655] sobre 5000 remuestreos
- `VAL:BASE`: HAC [-10.4540, 10.6101] con lag 3; bootstrap [-9.4843, 10.6886] sobre 5000 remuestreos
- `OOS:BASE`: HAC [-9.2735, 17.2738] con lag 3; bootstrap [-6.7735, 15.6310] sobre 5000 remuestreos
- `OOS:2X_FEES`: HAC [-10.1570, 16.3367] con lag 3; bootstrap [-7.6606, 14.6925] sobre 5000 remuestreos
- `OOS:ADVERSE`: HAC [-10.3781, 16.0277] con lag 3; bootstrap [-7.8881, 14.4110] sobre 5000 remuestreos

## Cartera por ventana y escenario

| ventana | escenario | operaciones | neto | expectativa | PF | drawdown | Sharpe | exposicion | mayor operacion / neto |
|---|---|---|---|---|---|---|---|---|---|
| `DEV` | `BASE` | 223 | 1,921.1792 | 8.6152 | 1.7782 | 4.2793% | 1.2243 | 24.5997% | 0.0673 |
| `VAL` | `BASE` | 58 | 4.5253 | 0.0780 | 1.0068 | 4.1002% | 0.0301 | 29.0259% | 27.5248 |
| `OOS` | `BASE` | 52 | 208.0056 | 4.0001 | 1.3312 | 2.5670% | 0.6658 | 19.4641% | 0.7987 |
| `OOS` | `2X_FEES` | 52 | 160.6723 | 3.0899 | 1.2461 | 2.7025% | 0.5139 | 19.4641% | 1.0267 |
| `OOS` | `ADVERSE` | 52 | 146.8908 | 2.8248 | 1.2231 | 2.7312% | 0.4716 | 19.4641% | 1.1205 |

## Sensibilidad: sin las mayores ganadoras

### `DEV:BASE`

| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |
|---|---|---|---|---|---|---|
| 0 (base) | 223 | 1,921.1792 | 0.0000 | 8.6152 | n/a | 0.0673 |
| 1 | 222 | 1,791.8199 | 129.3592 | 8.0713 | 1.7258 | 0.0713 |
| 3 | 220 | 1,543.5448 | 377.6344 | 7.0161 | 1.6252 | 0.0737 |

### `VAL:BASE`

| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |
|---|---|---|---|---|---|---|
| 0 (base) | 58 | 4.5253 | 0.0000 | 0.0780 | n/a | 27.5248 |
| 1 | 57 | -120.0341 | 124.5594 | -2.1059 | 0.8195 | n/a |
| 3 | 55 | -266.0739 | 270.5992 | -4.8377 | 0.5998 | n/a |

### `OOS:BASE`

| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |
|---|---|---|---|---|---|---|
| 0 (base) | 52 | 208.0056 | 0.0000 | 4.0001 | n/a | 0.7987 |
| 1 | 51 | 41.8740 | 166.1317 | 0.8211 | 1.0667 | 3.7009 |
| 3 | 49 | -221.3291 | 429.3347 | -4.5169 | 0.6476 | n/a |

### `OOS:2X_FEES`

| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |
|---|---|---|---|---|---|---|
| 0 (base) | 52 | 160.6723 | 0.0000 | 3.0899 | n/a | 1.0267 |
| 1 | 51 | -4.2921 | 164.9644 | -0.0842 | 0.9934 | n/a |
| 3 | 49 | -264.9675 | 425.6398 | -5.4075 | 0.5942 | n/a |

### `OOS:ADVERSE`

| k | operaciones | neto | retirado | expectativa | PF | mayor restante / neto |
|---|---|---|---|---|---|---|
| 0 (base) | 52 | 146.8908 | 0.0000 | 2.8248 | n/a | 1.1205 |
| 1 | 51 | -17.7020 | 164.5928 | -0.3471 | 0.9731 | n/a |
| 3 | 49 | -276.3397 | 423.2305 | -5.6396 | 0.5803 | n/a |

## Contribucion en la ventana de decision

### `OOS:BASE`

| libro | operaciones | neto | expectativa | win rate | drawdown | retorno/drawdown |
|---|---|---|---|---|---|---|
| `BTC` (libro propio) | 18 | 3.0607 | 0.1700 | 50.0000% | 0.9159% | 0.0334 |
| `ETH` (libro propio) | 16 | 281.6015 | 17.6001 | 43.7500% | 0.9499% | 2.9645 |
| `SOL` (libro propio) | 18 | -75.5490 | -4.1972 | 38.8889% | 1.3010% | -0.5807 |

| contexto de benchmark | operaciones | neto | win rate |
|---|---|---|---|
| `BEAR` | 7 | -58.8791 | 42.8571% |
| `BULL` | 41 | 177.4313 | 41.4634% |
| `SIDEWAYS` | 4 | 89.4535 | 75.0000% |

| periodo | operaciones | neto | expectativa | win rate |
|---|---|---|---|---|
| `2025H1` | 24 | 22.7467 | 0.9478 | 37.5000% |
| `2025H2` | 21 | 244.1381 | 11.6256 | 52.3810% |
| `2026Q1` | 7 | -58.8791 | -8.4113 | 42.8571% |

### `OOS:2X_FEES`

| libro | operaciones | neto | expectativa | win rate | drawdown | retorno/drawdown |
|---|---|---|---|---|---|---|
| `BTC` (libro propio) | 18 | -14.6785 | -0.8155 | 50.0000% | 0.9856% | -0.1489 |
| `ETH` (libro propio) | 16 | 266.7926 | 16.6745 | 43.7500% | 0.9780% | 2.7279 |
| `SOL` (libro propio) | 18 | -90.1035 | -5.0058 | 33.3333% | 1.4215% | -0.6338 |

| contexto de benchmark | operaciones | neto | win rate |
|---|---|---|---|
| `BEAR` | 7 | -65.6619 | 42.8571% |
| `BULL` | 41 | 140.7384 | 39.0244% |
| `SIDEWAYS` | 4 | 85.5958 | 75.0000% |

| periodo | operaciones | neto | expectativa | win rate |
|---|---|---|---|---|
| `2025H1` | 24 | 1.6775 | 0.0699 | 37.5000% |
| `2025H2` | 21 | 224.6567 | 10.6979 | 47.6190% |
| `2026Q1` | 7 | -65.6619 | -9.3803 | 42.8571% |

### `OOS:ADVERSE`

| libro | operaciones | neto | expectativa | win rate | drawdown | retorno/drawdown |
|---|---|---|---|---|---|---|
| `BTC` (libro propio) | 18 | -19.5234 | -1.0846 | 50.0000% | 1.0048% | -0.1943 |
| `ETH` (libro propio) | 16 | 261.8386 | 16.3649 | 43.7500% | 0.9822% | 2.6659 |
| `SOL` (libro propio) | 18 | -94.0407 | -5.2245 | 33.3333% | 1.4492% | -0.6489 |

| contexto de benchmark | operaciones | neto | win rate |
|---|---|---|---|
| `BEAR` | 7 | -67.3982 | 42.8571% |
| `BULL` | 41 | 130.0024 | 39.0244% |
| `SIDEWAYS` | 4 | 84.2866 | 75.0000% |

| periodo | operaciones | neto | expectativa | win rate |
|---|---|---|---|---|
| `2025H1` | 24 | -4.6477 | -0.1937 | 37.5000% |
| `2025H2` | 21 | 218.9367 | 10.4256 | 47.6190% |
| `2026Q1` | 7 | -67.3982 | -9.6283 | 42.8571% |

## Comparacion ajustada al riesgo

| ventana:escenario | neto | retorno | drawdown | Sharpe | MAR | retorno/drawdown | mejor b&h retorno/drawdown | mas profundo b&h |
|---|---|---|---|---|---|---|---|---|
| `DEV:BASE` | 1,921.1792 | 19.2118% | 4.2793% | 1.2243 | 4.4895 | 4.4895 | 34.0509 | 96.5988% |
| `VAL:BASE` | 4.5253 | 0.0453% | 4.1002% | 0.0301 | 0.0110 | 0.0110 | 3.9413 | 45.3218% |
| `OOS:BASE` | 208.0056 | 2.0801% | 2.5670% | 0.6658 | 0.8103 | 0.8103 | -0.5990 | 73.2008% |
| `OOS:2X_FEES` | 160.6723 | 1.6067% | 2.7025% | 0.5139 | 0.5945 | 0.5945 | -0.6018 | 73.2008% |
| `OOS:ADVERSE` | 146.8908 | 1.4689% | 2.7312% | 0.4716 | 0.5378 | 0.5378 | -0.6026 | 73.2008% |

## Periodos adicionales

- corpus congelado: ultima barra `2026-02-28T20:00:00+00:00`
- fin de la ventana de diseno: `2026-02-28T00:00:00+00:00`
- barras sin usar despues del diseno: `{'BTC': 5, 'ETH': 5, 'SOL': 5}`
- periodos independientes adicionales disponibles: **no** — the design windows (DEV 2019-2023, VAL 2024, OOS 2025-01 -> 2026-02-28) consume the frozen 4h corpus to its last complete bar; the only bars left are 5 mop-up bars (0.83 days), far below the declared 30-day minimum for a usable extra period, so no unused independent sample exists inside this corpus

## Regla de decision congelada

- `decision_window`: OOS
- `min_oos_trades`: 30
- `concentration_criterion_pct_of_net`: 0.5
- `concentration_criterion_unchanged_from`: WP-EDGE-01 OOS_TREND_DECISION.max_single_trade_share_of_net
- `min_positive_assets`: 2
- `min_positive_periods`: 2
- `uncertainty`: {'confidence': 0.95, 'hac': 'Newey-West (Bartlett-weighted) standard error of the mean trade net, with lag = floor(4 * (n/100)^(2/9)) declared here; two-sided 95% interval from the Student-t critical value by the Cornish-Fisher expansion', 'bootstrap': 'stationary block bootstrap over the trades in time order: a new block starts with probability 1/block_length, block_length = 5, 5000 resamples, xorshift64* PRNG from a declared seed, percentile interval of the mean'}
- `decisive_failures`: a powered sample in which the edge is CONTRADICTED: OOS net <= 0, or the net after dropping the single largest winner <= 0 (the reading is one trade), or fewer than min_positive_assets single-asset books positive, or the HAC interval's upper end <= 0 (the sample says the expectancy is not positive)
- `inconclusive_failures`: a powered sample in which the declared requirements are not met but the edge is not contradicted: concentration above the 0.50 limit while the leave-one-out net stays positive, an interval that contains 0, the adverse cost plane below 0 while the base plane is above it, fewer than min_positive_periods positive periods, or a candidate drawdown that is not below buy & hold
- `meaning`: {'ADMIT_PAPER': 'every declared requirement met on OOS, including the concentration limit', 'REJECT': 'a powered sample in which the edge is contradicted', 'INSUFFICIENT_EVIDENCE': 'a powered sample the requirements cannot decide, or an unpowered one'}
- `not_claimed`: PAPER here means the evidence supports wiring the frozen ruleset into the paper pipeline; it is not a profitability claim, not a live-trading authorisation and not a certification. No capital is at risk in this experiment.
- propuesta NO aplicada: a size-aware concentration criterion (e.g. the share measured against the sum of the top-k winners, or against gross profit instead of net) — a proposal for a NEW pre-registered experiment with its own corpus split; it is NOT applied to this run, and the run is judged against 0.50

## Limites

- the ruleset is untuned and frozen and VAL/OOS were already read for it in WP-EDGE-01, so this is a decomposition and a sensitivity analysis of the published run, not a second independent sample
- the concentration criterion is the same 0.50 WP-EDGE-01 froze; relaxing it is proposed as a new experiment and is deliberately NOT applied here
- the frozen corpus ends at the last bar of the OOS window (2026-02-28), so no unused independent period exists: an additional period needs a new corpus, which the 15m feed could supply but only as a new pre-registered experiment
- the HAC interval is asymptotic and the block bootstrap resamples 52 trades: both widen the reading honestly, neither turns 52 observations into a large sample
- the candidate risks a fixed share of equity per trade while buy & hold is fully invested, so the comparison is on the same window and cost plane, not on the same capital utilisation
- long side only (spot); no historical order book; nothing is wired into PAPER
