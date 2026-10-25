# ABLACION DE MECANISMO - H4 (filtro de volatilidad de entrada)

| | |
|---|---|
| experimento | `ABL-EDGE01-H4` |
| pregunta | EDGE-TREND-01 has no separate volatility entry filter: volatility only reaches it through the ATR-scaled stop, so it trades quiet and violent regimes alike. Does refusing the least volatile breakouts help on DEV? |
| candidato congelado | `edge_trend_01` (4h) |
| campo cambiado | `min_atr_pct` |
| split / ventana | `trend` / `DEV` |
| desde / hasta | `2019-01-01T00:00:00+00:00` .. `2023-12-31T00:00:00+00:00` |
| dias | 1825.0 |
| escenario | `BASE` |
| HEAD al ejecutar | `ce42ca42c297fe2b6a6594a49b385ed811442666` |
| huella del codigo ejecutado (sha256) | `616a86fa7258fa9efe2faf1d3b333a87722944aef9796bfa228417014c178c5a` |
| params_hash (candidato congelado) | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| veredicto | **`FILTER_NOT_JUSTIFIED_ON_DEV`** |

Las cuatro ramas son el MISMO candidato congelado; la baseline no anade
ningun campo y cada rama de umbral anade exactamente uno,
`min_atr_pct` (ATR/close en porcentaje). La rejilla no se elige mirando
resultados: son los percentiles declarados de la distribucion de ATR/close de
las barras de DEV.

## Rejilla de umbrales

Percentiles de atr/close en DEV — nearest rank: index = ceil(pct/100 * n) - 1 over the ascending atr/close values of every DEV bar with a defined atr_period ATR, all assets pooled.

| rama | umbral min_atr_pct |
|---|---|
| `baseline` | sin filtro |
| `p25` | 1.5519 |
| `p50` | 2.2392 |
| `p75` | 3.3307 |

- muestra: 29,206 barras de DEV con ATR definido; minimo 0.2530, mediana 2.2392, maximo 27.2657

## Resultado en DEV

| rama | min_atr_pct | operaciones | bruto | bruto/op | coste | neto | expectativa | drawdown % | rechazos por volatilidad |
|---|---|---|---|---|---|---|---|---|---|
| `baseline` | sin filtro | 223 | 2,128.91 | 9.55 | 207.73 | 1,921.18 | 8.62 | 4.28% | 0 |
| `p25` | 1.5519 | 188 | 1,758.69 | 9.35 | 163.16 | 1,595.54 | 8.49 | 3.98% | 366 |
| `p50` | 2.2392 | 131 | 1,084.28 | 8.28 | 90.61 | 993.67 | 7.59 | 3.20% | 794 |
| `p75` | 3.3307 | 58 | 527.33 | 9.09 | 27.35 | 499.98 | 8.62 | 1.94% | 1,243 |

- ranking por neto de DEV (solo ramas con al menos 30 operaciones): `baseline`, `p25`, `p50`, `p75`
- veredicto: **`FILTER_NOT_JUSTIFIED_ON_DEV`** — the best DEV arm is baseline with 1,921.18 USDT against 1,921.18 for the unfiltered baseline (+0 USDT); share of the winner's net in its single largest trade: 0.0673
- umbral congelado: ninguno
- VAL/OOS leidos: **False** — the frozen threshold goes through VAL and then OOS in a NEW pre-registered run; nothing here is wired into any ruleset

## Que significa el veredicto

- **`FILTER_NOT_JUSTIFIED_ON_DEV`** — no threshold beats the baseline on DEV, or the arm that does is carried by a single trade or is not profitable itself: the filter is NOT added to the ruleset, because a filter chosen after the outcome is not evidence

## Artefactos de este experimento

- `VOL_FILTER.json` — comparacion completa, rejilla, regla congelada y veredicto
- `VOL_FILTER_TRADES.csv` — operaciones de las cuatro ramas
- `VOL_FILTER_REFUSALS.csv` — rechazos crudos, con el atr_pct que los provoco
- `VOL_FILTER_SIGNALS.csv` — senales de cada rama, con su atr_pct
- `VOL_FILTER_ATR.csv` — la muestra de atr/close de DEV con la que se situa la rejilla
- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion
- verificado por `scripts/edge01_mechanism_ablation_verify.py --experiment h4` en un proceso aparte

## Limites

- picking one of four arms on DEV is itself a selection: the winner is frozen, not promoted, and its VAL/OOS behaviour is unknown
- the grid comes from the DEV input distribution of atr/close, so a different window would place the thresholds elsewhere; the rule and the percentile definition are published so the placement is auditable
- the gate refuses entries only (it does not size down and does not change the exit): it cannot rescue a position it would not have opened
- removing less volatile breakouts removes a population, not a per-trade outcome; the arms are different equity trajectories, so the comparison is between two books, not two versions of one trade
- single DEV window; no historical order book; long side only (spot)
