# STRATEGY_PERFORMANCE_OOS — separación temporal y evidencia OOS (§17, §24)

## Definición de splits (sin leakage)

- Ventanas W1-W4 (2026-03→06): DEVELOPMENT — incluye el período de diseño
  histórico de la familia
- W5-W6 (2026-07→08): VALIDATION
- W7 (2026-09-01→24): OUT-OF-SAMPLE — estrictamente posterior
- El día del paper run (2026-09-25) queda fuera de todas las ventanas:
  el paper V2 es OOS puro respecto del histórico

## OOS (W7) — 168 trades

| Métrica | Valor |
| --- | ---: |
| Net PnL | −152.60 |
| Profit factor | 0.41 |
| Win rate | 19.64% |
| Payoff | 1.67 |
| Expectancy | −0.91/trade |

## Paper V2 (19 trades) vs histórico — comparación honesta (§24)

| Métrica | Paper V2 | Histórico (1723) | OOS (168) |
| --- | ---: | ---: | ---: |
| Win rate | 42.1% (ex-DEF-205) | 28.6% | 19.6% |
| Payoff | ~0.23 (TP 3.75 vs SL) | 1.43 | 1.67 |
| PF | 0.051 (0.32 ex-DEF-205) | 0.57 | 0.41 |
| Expectancia | negativa | −0.68 | −0.91 |

**Clasificación: CONSISTENT en dirección** (negativo en ambos), con
desviaciones de tamaño esperables: 19 trades vs 1723, el único trade
DEF-205 (−500) domina el PF del paper, y el sizing clamp del paper
(notional fijo 500 con SL estrecho) amplifica la pérdida unitaria vs el
backtest (equity decreciente). Ninguna contradicción: el runtime ejecuta
fielmente el contrato que el histórico ya condena.

## Conclusión

La evidencia OOS no rescató la estrategia: empeoró (PF 0.63→0.47→0.41).
El resultado del paper V2 es consistente con el histórico. No hay señal
de que el runtime distorsione la performance; hay señal de que la
estrategia no tiene edge en 5m crypto 2026.
