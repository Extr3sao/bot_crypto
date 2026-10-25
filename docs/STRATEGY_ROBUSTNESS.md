# STRATEGY_ROBUSTNESS — ema_crossover neighborhood + regimes (§20-23)

> ROBUSTNESS_VARIANTS.json (machine-readable) en docs/. Sin optimización:
> solo vecindario del contrato actual + atribución por régimen.

## Vecindario de parámetros (§20)

| Variante | Trades | Net | PF | WR |
| --- | ---: | ---: | ---: | ---: |
| BASE 9/21 TP0.75 SL1.5ATR | 1723 | −1177.61 | 0.57 | 28.6% |
| TP 1.50% | 1129 | −789.82 | 0.62 | 16.7% |
| SL 2.0×ATR | 2232 | −1562.48 | 0.62 | 35.9% |
| EMA 12/26 | 1742 | −1165.79 | 0.58 | 29.1% |

Las 4 variantes son negativas con PF 0.57-0.62: **no es un punto afortunado,
es una meseta negativamente robusta**. Ningún vecino salva la estrategia.

## Walk-forward simple (§21)

La progresión temporal por ventanas ya constituye el walk-forward mínimo:
DEV (W1-W4) PF 0.63 → VAL (W5-W6) PF 0.47 → OOS (W7) PF 0.41.
Ningún período explica el resultado: TODOS son negativos (−242, −133, −114,
−203, −167, −166, −153 por ventana, en orden temporal). La performance NO
persiste porque nunca fue positiva.

## Performance por régimen (§22)

Clasificación por retorno/vol de BTC por ventana:

| Régimen | Ventanas | Net acumulado | Trades |
| --- | --- | ---: | ---: |
| RANGE_MIDVOL | W1 | −242.25 | 237 |
| UP_LOWVOL | W2, W5, W6, W7 | −618.28 | 861 |
| DOWN_LOWVOL | W3 | −113.78 | 217 |
| DOWN_MIDVOL | W4 (crash −20.6%) | −203.28 | 408 |

**Negativo en las 6 clases de régimen**. Incluso en tendencias alcistas
fuertes (W6: BTC +24.8%) pierde — el TP 0.75% corta las ganancias antes de
que compensen los stops.

## Por activo (§23)

Negativo en los tres: la debilidad es de la señal en 5m, no de un activo.

## Conclusión

La estrategia no es frágil-en-un-punto: es consistentemente perdedora en
todas las variantes, ventanas, regímenes y activos. `REJECT_AS_CURRENT_
PRODUCTION_CANDIDATE` queda reforzado por robustez negativa.
