# CANDIDATE RANKING — EXP-003N

**Veredicto: `NO_VIABLE_CANDIDATES`** · 24 celdas · holdout abierto: **False**

Orden por expectativa neta por operación cerrada en VAL tras coste completo. La columna
«bruto/señal» es el retorno forward medio en el mejor horizonte de IS; «neto cerrado» es lo
que queda tras la comisión y el spread más el slippage de las dos patas. Un candidato no
sube en esta tabla por rentabilidad agregada: sube por bps por operación.

| # | lane | familia | tf | señales/día | bruto/señal (bps) | coste (bps) | neto/señal (bps) | ops cerradas VAL | neto cerrado (bps) | acierto | PF | veredicto |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `lane_a` | `momentum` | `1h` | 156.60 | 23.49 | 27.31 | -3.82 | 576 | -37.58 | 42.5 % | 0.80 | `REJECT` |
| 2 | `lane_a` | `breakout` | `1h` | 14.43 | 24.48 | 27.31 | -2.83 | 52 | -43.86 | 42.3 % | 0.66 | `REJECT` |
| 3 | `lane_a` | `ema_crossover` | `1h` | 235.33 | -1.26 | 27.31 | -28.57 | 961 | -48.18 | 37.4 % | 0.64 | `REJECT` |
| 4 | `lane_a` | `mean_reversion` | `5m` | 122.57 | 6.33 | 27.31 | -20.98 | 506 | -51.82 | 19.0 % | 0.16 | `REJECT` |
| 5 | `lane_a` | `volatility` | `5m` | 13.34 | -4.60 | 27.31 | -31.91 | 50 | -52.30 | 14.0 % | 0.13 | `REJECT` |
| 6 | `lane_a` | `ema_crossover` | `5m` | 2,996.80 | -0.12 | 27.31 | -27.43 | 11179 | -54.90 | 15.1 % | 0.15 | `REJECT` |
| 7 | `lane_a` | `breakout` | `5m` | 184.91 | 0.21 | 27.31 | -27.10 | 653 | -56.64 | 16.2 % | 0.18 | `REJECT` |
| 8 | `lane_a` | `momentum` | `5m` | 555.26 | -0.52 | 27.31 | -27.83 | 1617 | -58.23 | 20.9 % | 0.20 | `REJECT` |
| 9 | `lane_a` | `trend` | `5m` | 74.50 | -1.79 | 27.31 | -29.10 | 121 | -62.27 | 22.3 % | 0.28 | `REJECT` |
| 10 | `lane_a` | `trend` | `1h` | 80.01 | -183.34 | 27.31 | -210.65 | 343 | -67.66 | 28.9 % | 0.41 | `REJECT` |
| 11 | `lane_a` | `mean_reversion` | `1h` | 9.27 | -12.32 | 27.31 | -39.63 | 36 | -83.60 | 36.1 % | 0.29 | `REJECT` |
| 12 | `lane_a` | `momentum` | `4h` | 40.21 | -49.56 | 27.31 | -76.87 | 224 | -152.68 | 24.6 % | 0.26 | `REJECT` |
| 13 | `lane_a` | `ema_crossover` | `4h` | 46.18 | -5.13 | 27.31 | -32.44 | 230 | -184.47 | 19.1 % | 0.16 | `REJECT` |
| 14 | `lane_a` | `trend` | `4h` | 26.59 | 14.80 | 27.31 | -12.51 | 140 | -186.68 | 19.3 % | 0.18 | `EXPERIMENT` |
| 15 | `lane_a` | `volatility` | `4h` | 0.30 | 72.00 | 27.31 | 44.69 | 1 | 234.90 | 100.0 % | — | `INSUFFICIENT_EVIDENCE` |
| 16 | `lane_a` | `volatility` | `1h` | 2.59 | -41.69 | 27.31 | -69.00 | 16 | -106.01 | 31.2 % | 0.16 | `INSUFFICIENT_EVIDENCE` |
| 17 | `lane_a` | `breakout` | `4h` | 2.07 | 10.78 | 27.31 | -16.53 | 15 | -111.08 | 40.0 % | 0.31 | `INSUFFICIENT_EVIDENCE` |
| 18 | `lane_b` | `trend_pullback` | `1h` | 2.56 | -76.67 | 27.31 | -103.98 | 17 | -123.98 | 0.0 % | 0.00 | `INSUFFICIENT_EVIDENCE` |
| 19 | `lane_a` | `mean_reversion` | `4h` | 1.62 | -26.05 | 27.31 | -53.36 | 10 | -201.20 | 20.0 % | 0.13 | `INSUFFICIENT_EVIDENCE` |
| 20 | `lane_b` | `mean_reversion_vol_liq` | `1h` | 0.69 | — | 27.31 | — | 4 | -203.42 | 25.0 % | 0.08 | `INSUFFICIENT_EVIDENCE` |
| 21 | `lane_b` | `mean_reversion_vol_liq` | `4h` | 0.00 | — | 27.31 | — | 0 | — | 0.0 % | — | `INSUFFICIENT_EVIDENCE` |
| 22 | `lane_b` | `trend_pullback` | `4h` | 0.23 | — | 27.31 | — | 0 | — | 0.0 % | — | `INSUFFICIENT_EVIDENCE` |
| 23 | `lane_b` | `vol_regime_breakout` | `1h` | 0.00 | — | 27.31 | — | 0 | — | 0.0 % | — | `INSUFFICIENT_EVIDENCE` |
| 24 | `lane_b` | `vol_regime_breakout` | `4h` | 0.00 | — | 27.31 | — | 0 | — | 0.0 % | — | `INSUFFICIENT_EVIDENCE` |

Las celdas con `INSUFFICIENT_EVIDENCE` van al final y no compiten por el primer puesto:
una operación cerrada con +235 bps es un número, no un candidato.

## Lectura

La mejor celda es `momentum@1h` con **-37.58 bps** netos por operación cerrada. El suelo de
comisiones es **20.00 bps** sin descuento
BNB y el coste completo que se le aplicó es **27.31 bps**: la
comparación no es contra cero, es contra el peaje entero.

Ninguna celda queda por encima de su propio peaje. La tabla no ordena ganadores:
ordena cuánto le falta a cada mecanismo, y el primero de la lista sigue perdiendo
dinero. Esa es la respuesta del experimento, no un empate técnico.

- Rango de expectativa neta por operación cerrada: **-203.42** a **234.90** bps.
- Celdas con neto positivo: **1** de **20**.
