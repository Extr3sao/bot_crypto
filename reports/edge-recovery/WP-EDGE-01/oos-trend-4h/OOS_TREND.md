# REVISION FUERA DE MUESTRA - EDGE-TREND-01 4h

| | |
|---|---|
| experimento | `OOS-EDGE01-TREND-4H` |
| responde a | `H3` |
| pregunta | EDGE-TREND-01 4h is positive on DEV (+1,921.1792 USDT) and positive on OOS, but H3 warned that the OOS net may be one fat trade rather than an edge. Is there enough out-of-sample evidence — per asset, per calendar period, per regime and against buy & hold, before and after cost stress — to justify taking this ruleset to PAPER? |
| candidato congelado | `edge_trend_01` (4h) |
| split | `trend` |
| ventana de decision | `OOS` |
| desde / hasta | `2025-01-01T00:00:00+00:00` .. `2026-02-28T00:00:00+00:00` |
| dias | 423.0 |
| HEAD al ejecutar | `ce42ca42c297fe2b6a6594a49b385ed811442666` |
| huella del codigo ejecutado (sha256) | `616a86fa7258fa9efe2faf1d3b333a87722944aef9796bfa228417014c178c5a` |
| params_hash | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| veredicto | **`NOT_SUFFICIENT_EVIDENCE`** |

Ningun parametro se toca: el ruleset es el mismo diccionario congelado con el que
se publico la campana, y las tres ventanas se miden con el mismo presupuesto de
riesgo, el mismo plano de costes y el mismo corpus.

## Veredicto

- **`NOT_SUFFICIENT_EVIDENCE`**
- no_single_trade_carries_the_net: largest trade is 0.7987 of the OOS net (limit 0.5)
- regla: {'SUFFICIENT_EVIDENCE_FOR_PAPER': 'every requirement above met on OOS, plus the WP gate', 'NOT_SUFFICIENT_EVIDENCE': 'the sample is powered and at least one requirement fails', 'UNPOWERED': 'fewer than the declared minimum OOS trades: nothing is concluded'}
- no reclamado: PAPER here means the evidence supports wiring the frozen ruleset into the paper pipeline; it is not a profitability claim, not a live-trading authorisation and not a certification. No capital is at risk in this experiment.

## Cumplimiento de la regla en `OOS`

| criterio | resultado | detalle |
|---|---|---|
| `oos_net_positive` | **PASS** | OOS net 208.01 USDT |
| `oos_net_positive_under_2x_fees` | **PASS** | OOS net with 2x fees 160.67 USDT |
| `oos_trades_floor` | **PASS** | 52 OOS trades vs floor 30 |
| `no_single_trade_carries_the_net` | **FAIL** | largest trade is 0.7987 of the OOS net (limit 0.5) |
| `assets_positive` | **PASS** | 2/3 single-asset OOS books positive (BTC, ETH) vs required 2 |
| `drawdown_below_buy_and_hold` | **PASS** | OOS max drawdown 2.57% vs the deepest buy & hold drawdown 73.20% |
| `periods_positive` | **PASS** | 2/3 OOS periods positive (2025H1, 2025H2) vs required 2 |

- regla de admision del WP (Initial thresholds for WP-EDGE-01, recorded before the campaign ran): **`INSUFFICIENT_EVIDENCE`** — the largest single trade is 0.80 of the oos net

## Cartera combinada por ventana y escenario

| ventana | escenario | operaciones | neto | expectativa | profit factor | drawdown | exposicion | mayor operacion / neto |
|---|---|---|---|---|---|---|---|---|
| `DEV` | `BASE` | 223 | 1,921.18 | 8.62 | 1.7782 | 4.2793% | 24.5997% | 0.0673 |
| `VAL` | `BASE` | 58 | 4.53 | 0.08 | 1.0068 | 4.1002% | 29.0259% | 27.5248 |
| `OOS` | `BASE` | 52 | 208.01 | 4.00 | 1.3312 | 2.5670% | 19.4641% | 0.7987 |
| `OOS` | `2X_FEES` | 52 | 160.67 | 3.09 | 1.2461 | 2.7025% | 19.4641% | 1.0267 |

## Activos por separado y en conjunto en `OOS` (BASE)

| libro | operaciones | neto | expectativa | win rate | drawdown | exposicion |
|---|---|---|---|---|---|---|
| BTC+ETH+SOL (conjunto) | 52 | 208.01 | 4.00 | 44.2308% | 2.5670% | 19.4641% |
| BTC (libro propio) | 18 | 3.06 | 0.17 | 50.0000% | 0.9159% | 18.8731% |
| ETH (libro propio) | 16 | 281.60 | 17.60 | 43.7500% | 0.9499% | 19.3853% |
| SOL (libro propio) | 18 | -75.55 | -4.20 | 38.8889% | 1.3010% | 20.1340% |

## Contra buy & hold en `OOS` (BASE)

| activo | candidato neto | candidato retorno | candidato drawdown | b&h retorno | b&h drawdown |
|---|---|---|---|---|---|
| BTC | 3.06 | 0.0306% | 0.9159% | -29.8527% | 49.8370% |
| ETH | 281.60 | 2.8160% | 0.9499% | -42.4792% | 62.2243% |
| SOL | -75.55 | -0.7555% | 1.3010% | -56.9247% | 73.2008% |

## Periodos declarados en `OOS` (BASE)

| periodo | operaciones | neto | expectativa | win rate |
|---|---|---|---|---|
| `2025H1` | 24 | 22.75 | 0.95 | 37.5000% |
| `2025H2` | 21 | 244.14 | 11.63 | 52.3810% |
| `2026Q1` | 7 | -58.88 | -8.41 | 42.8571% |

## Regimenes en `OOS` (BASE)

| etiqueta | tipo | operaciones | neto | win rate |
|---|---|---|---|---|
| `UP` | estado de tendencia del candidato | 52 | 208.01 | 44.2308% |
| `BEAR` | contexto de benchmark | 7 | -58.88 | 42.8571% |
| `BULL` | contexto de benchmark | 41 | 177.43 | 41.4634% |
| `SIDEWAYS` | contexto de benchmark | 4 | 89.45 | 75.0000% |

- con el coste estresado (`2X_FEES`) el conjunto da 160.67 USDT en `OOS`

## Artefactos de este experimento

- `OOS_TREND.json` — cartera, libros por activo, periodos, buy & hold y veredicto
- `OOS_TREND_TRADES.csv` — operaciones de la cartera combinada por ventana y escenario
- `OOS_TREND_ASSETS.csv` — metrica por activo y ventana, con libro propio
- `OOS_TREND_PERIODS.csv` — desglose por periodo declarado
- `OOS_TREND_REGIMES.csv` — desglose por estado de tendencia y por contexto de benchmark
- `BUY_AND_HOLD.csv` — la referencia, en la misma ventana y con el mismo plano de costes
- `MARKET_CONTEXT.csv` — la serie de benchmark
- verificado por `scripts/edge01_closure_verify.py --experiment oos` en un proceso aparte

## Limites

- the ruleset is untuned and frozen: VAL and OOS were read for it in the WP campaign already, so the OOS numbers here are a decomposition of the published run, not a second independent sample
- the candidate risks a fixed share of equity per trade and caps the order notional, while buy & hold is fully invested in one asset: the comparison is on the same window and cost plane, not on the same capital utilisation
- the periods are calendar halves declared here; three periods over fourteen months is a decomposition, not a statistical test
- the 4h corpus is aggregated from 1h and ends 2026-02-28, so the last OOS stretch is shorter than a full half-year and no bar exists after that date
- long side only (spot); no historical order book; nothing is wired into PAPER
