# WP-016A — auditoría de admisión de las 24 estrategias

> Generado por `scripts/tdm16_admission_audit.py` desde los artefactos commiteados. Cada número se recalcula aquí; nada se copia de un informe previo.

## Respuesta

**0/24 admitidas.** 7 celdas tienen gross > 0 y 17 no. El techo de gross es **8.912 bps/trade** (`volatility@30m`), frente a una línea medida de **12.177 bps RT** y una línea maker de futuros **asumida** de **9.250 bps RT**.

Distancias del mejor caso: **-3.265 bps** contra la línea medida y **-0.338 bps** contra la maker asumida. Ambas negativas ⇒ ningún slippage ni tasa de acierto salva una celda: la resta no cierra antes de ejecutar nada.

## Líneas de coste

| Línea | bps RT | Clase | Depende de componente asumido |
| --- | ---: | --- | --- |
| `BINANCE_USDM_PERP_TAKER` (cheapest_measured) | 12.177 | ESTIMATED | no |
| `BINANCE_USDM_PERP_MAKER` (assumed_futures_maker) | 9.250 | ASSUMED | sí |
| `MEXC_SPOT_TAKER` (cheapest_any) | 1.250 | ASSUMED | sí |

## Las 24 celdas

| Estrategia | Trades (explorer) | Gross bps | Estado | Causa del rechazo | Neto máximo vs línea medida | vs maker asumida |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| `volatility@30m` | 194 | +8.910 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -3.265 | -0.338 |
| `volatility@1h` | 96 | +6.280 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -5.901 | -2.974 |
| `mean_reversion@30m` | 934 | +5.470 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -6.705 | -3.778 |
| `mean_reversion@15m` | 1579 | +2.710 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -9.463 | -6.536 |
| `trend@30m` | 1562 | +2.210 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -9.971 | -7.044 |
| `mean_reversion@5m` | 3190 | +1.490 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, PREREGISTERED_CRITERIA_FAILED | -10.691 | -7.765 |
| `trend@15m` | 1616 | +1.280 | COST_KILLED | GROSS_BELOW_CHEAPEST_MEASURED_LINE, FAMILY_NOT_IN_MATRIX_PAPER_CANDIDATES, NO_NET_OOS_DRAWDOWN_MEASURED_ON_THIS_TIMEFRAME, FAMILY_CRITERIA_FAILED_AT_5M, SAMPLE_UNPROVEN_IN_LEDGER | -10.893 | -7.966 |
| `breakout@5m` | 2426 | -0.110 | NO_GROSS_EDGE | NO_GROSS_EDGE | -12.261 | -9.334 |
| `breakout@1h` | 710 | -0.220 | NO_GROSS_EDGE | NO_GROSS_EDGE | -12.399 | -9.472 |
| `ema_crossover@30m` | 3214 | -0.730 | NO_GROSS_EDGE | NO_GROSS_EDGE | -12.903 | -9.976 |
| `ema_crossover@1h` | 2620 | -0.960 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.141 | -10.214 |
| `ema_crossover@15m` | 2913 | -1.120 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.299 | -10.372 |
| `trend@1h` | 1405 | -1.250 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.429 | -10.502 |
| `trend@5m` | 1291 | -1.650 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.822 | -10.895 |
| `breakout@30m` | 1281 | -1.790 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.969 | -11.042 |
| `breakout@15m` | 2042 | -1.820 | NO_GROSS_EDGE | NO_GROSS_EDGE | -13.999 | -11.072 |
| `momentum@5m` | 2526 | -1.880 | NO_GROSS_EDGE | NO_GROSS_EDGE | -14.060 | -11.133 |
| `mean_reversion@1h` | 448 | -2.230 | NO_GROSS_EDGE | NO_GROSS_EDGE | -14.403 | -11.476 |
| `momentum@1h` | 2304 | -2.330 | NO_GROSS_EDGE | NO_GROSS_EDGE | -14.511 | -11.584 |
| `momentum@30m` | 2957 | -2.610 | NO_GROSS_EDGE | NO_GROSS_EDGE | -14.789 | -11.862 |
| `momentum@15m` | 3003 | -3.970 | NO_GROSS_EDGE | NO_GROSS_EDGE | -16.149 | -13.222 |
| `ema_crossover@5m` | 1725 | -4.560 | NO_GROSS_EDGE | NO_GROSS_EDGE | -16.738 | -13.811 |
| `volatility@5m` | 520 | -4.730 | NO_GROSS_EDGE | NO_GROSS_EDGE | -16.912 | -13.985 |
| `volatility@15m` | 277 | -7.060 | NO_GROSS_EDGE | NO_GROSS_EDGE | -19.241 | -16.314 |

## Criterios pre-registrados por familia (c1..c8)

| Familia | c1 | c2 | c3 | c4 | c5 | c6 | c7 | c8 | Net BASE | PF BASE | PF 2X | OOS net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `breakout` | sí | no | no | no | no | — | no | — | -1427.46 | 0.6612 | 0.4801 | -138.81 |
| `ema_crossover` | sí | no | no | no | no | — | no | — | -1266.16 | 0.5017 | 0.3422 | -144.38 |
| `mean_reversion` | sí | no | no | no | no | — | no | — | -1514.34 | 0.6746 | 0.4685 | -169.88 |
| `momentum` | sí | no | no | no | no | — | no | — | -1679.33 | 0.6462 | 0.4729 | -205.41 |
| `trend` | sí | no | no | no | no | — | no | — | -876.83 | 0.7226 | 0.5589 | -17.35 |
| `volatility` | sí | no | no | no | no | — | no | — | -428.79 | 0.6175 | 0.4587 | -52.11 |

## Checks de la propia auditoría

14/14 verdes. Los fallos aparecen como fallos, no se filtran.
- **PASS** `A01` — the ledger enumerates 24 strategies
- **PASS** `A02` — none of the 24 is admitted for paper
- **PASS** `A03` — the matrix lists no paper candidates (the gate the rule needs)
- **PASS** `A04` — every ledger status is reproduced by the published rule
- **PASS** `A05` — the ledger's recorded source hashes still match the files on disk
- **PASS** `A06` — every ledger gross edge matches the explorer cell, or diverges only by an amount that changes neither the sign of the edge nor which side of the cost line the cell sits on
- **PASS** `A07` — every ledger gross edge matches its measurement artifact
- **PASS** `A08` — 7 cells have positive gross and 17 do not (sanity of the split)
- **PASS** `A09` — no cell clears the cheapest measured cost line
- **PASS** `A10` — no cell clears the cheapest assumed futures-maker line
- **PASS** `A11` — the only line that would clear cells is an assumed, fill-unmodelled one
- **PASS** `A12` — 18 of 24 ledger entries declare an unproven sample (provenance gap, not a data gap)
- **PASS** `A13` — c6 (drawdown) and c8 (window dominance) are unmeasured in every 5m family
- **PASS** `A14` — the verdict is ECONOMIC_BLOCKED because no strategy is admitted

## Veredicto

- `economic_status`: **ECONOMIC_BLOCKED**
- admitidas: ninguna
- razón decisiva: max measured gross edge 8.912 bps/trade is below the cheapest measured round trip 12.177 bps, and below the cheapest assumed futures-maker line 9.250 bps: every cell is negative even with zero slippage and a perfect fill.
- qué cambiaría el veredicto: a measured round-trip line below the gross of at least one cell, i.e. a maker fill rate measured from the tape (EXP-COST-LINE-001).

