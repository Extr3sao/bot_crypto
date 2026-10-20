# REJECTED CANDIDATES — EXP-003N

23 de 72 celdas no llegan a la fase de validación. Cada
rechazo cita la medida que lo produce; ninguno cita una impresión.

## Por familia

| familia | tf | veredicto | señales IS | bruto/señal IS (bps) | IC95 inf. (bps) | suelo (bps) | déficit (bps) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `breakout` | `1h` | `REJECT` | 68 | 26.53 | -97.26 | 20.00 | -6.53 |
| `breakout` | `4h` | `INSUFFICIENT_EVIDENCE` | 1 | 250.22 | — | 20.00 | -230.22 |
| `breakout` | `5m` | `REJECT` | 961 | 0.96 | -2.45 | 20.00 | 19.04 |
| `ema_crossover` | `1h` | `REJECT` | 1022 | 8.36 | -68.87 | 20.00 | 11.64 |
| `ema_crossover` | `4h` | `REJECT` | 109 | -6.41 | -14.24 | 20.00 | 26.41 |
| `ema_crossover` | `5m` | `REJECT` | 14911 | -0.18 | -0.80 | 20.00 | 20.18 |
| `mean_reversion` | `1h` | `REJECT` | 44 | 45.28 | -4.19 | 20.00 | -25.28 |
| `mean_reversion` | `4h` | `INSUFFICIENT_EVIDENCE` | 4 | 203.69 | — | 20.00 | -183.69 |
| `mean_reversion` | `5m` | `REJECT` | 581 | 1.89 | -19.15 | 20.00 | 18.11 |
| `mean_reversion_vol_liq` | `1h` | `INSUFFICIENT_EVIDENCE` | 0 | — | — | 20.00 | — |
| `mean_reversion_vol_liq` | `4h` | `INSUFFICIENT_EVIDENCE` | 0 | — | — | 20.00 | — |
| `momentum` | `1h` | `REJECT` | 779 | 4.42 | -72.21 | 20.00 | 15.58 |
| `momentum` | `4h` | `REJECT` | 74 | 25.64 | -257.04 | 20.00 | -5.64 |
| `momentum` | `5m` | `REJECT` | 3929 | 0.44 | -4.51 | 20.00 | 19.56 |
| `trend` | `1h` | `REJECT` | 512 | 46.75 | -219.33 | 20.00 | -26.75 |
| `trend` | `5m` | `REJECT` | 701 | -0.51 | -10.95 | 20.00 | 20.51 |
| `trend_pullback` | `1h` | `INSUFFICIENT_EVIDENCE` | 10 | 72.66 | — | 20.00 | -52.66 |
| `trend_pullback` | `4h` | `INSUFFICIENT_EVIDENCE` | 0 | — | — | 20.00 | — |
| `vol_regime_breakout` | `1h` | `INSUFFICIENT_EVIDENCE` | 0 | — | — | 20.00 | — |
| `vol_regime_breakout` | `4h` | `INSUFFICIENT_EVIDENCE` | 0 | — | — | 20.00 | — |
| `volatility` | `1h` | `INSUFFICIENT_EVIDENCE` | 7 | 33.52 | — | 20.00 | -13.52 |
| `volatility` | `4h` | `INSUFFICIENT_EVIDENCE` | 3 | 53.83 | — | 20.00 | -33.83 |
| `volatility` | `5m` | `REJECT` | 71 | 17.07 | -57.37 | 20.00 | 2.93 |

## Hipótesis refutadas

Estas frases son lo que el experimento deja cerrado en esta lane, con su número:

- **`breakout`**: mejor horizonte `24` a `1h` — bruto **26.53 bps** por señal, IC95 inferior **-97.26 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.
- **`ema_crossover`**: mejor horizonte `24` a `1h` — bruto **8.36 bps** por señal, IC95 inferior **-68.87 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.
- **`mean_reversion`**: mejor horizonte `6` a `1h` — bruto **45.28 bps** por señal, IC95 inferior **-4.19 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.
- **`mean_reversion_vol_liq`**: ninguna celda pasa la puerta de muestra; no se refuta nada, queda `INSUFFICIENT_EVIDENCE` con el tamaño medido en la tabla de arriba.
- **`momentum`**: mejor horizonte `48` a `4h` — bruto **25.64 bps** por señal, IC95 inferior **-257.04 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.
- **`trend`**: mejor horizonte `48` a `1h` — bruto **46.75 bps** por señal, IC95 inferior **-219.33 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.
- **`trend_pullback`**: ninguna celda pasa la puerta de muestra; no se refuta nada, queda `INSUFFICIENT_EVIDENCE` con el tamaño medido en la tabla de arriba.
- **`vol_regime_breakout`**: ninguna celda pasa la puerta de muestra; no se refuta nada, queda `INSUFFICIENT_EVIDENCE` con el tamaño medido en la tabla de arriba.
- **`volatility`**: mejor horizonte `48` a `5m` — bruto **17.07 bps** por señal, IC95 inferior **-57.37 bps** frente a un suelo de **20.00 bps**. Motivo del rechazo: hay información, pero por debajo del peaje.

## Los ceros de lane B no son ausencia de ventaja

WP-EDGE-015 exige ventanas de percentiles de hasta 720 horas antes de decidir. Sobre una
muestra de 46 días, ese warm-up consume la mayor parte de la ventana: las celdas con 0
operaciones se declaran `INSUFFICIENT_EVIDENCE` con el warm-up medido en `RUN_REPORT.md`,
nunca `REJECT`. Un cero por falta de datos no refuta una hipótesis; la deja sin probar.

## Por qué re-ejecutar el ejecutor no cambia nada

Un fill mejor, una cola más corta o una comisión con descuento BNB mueven el coste en
puntos básicos. Ninguno de ellos crea ingreso bruto. Las celdas de esta tabla fallan en la
medida *antes* del ejecutor: el retorno forward del que la señal informa. Por eso el
veredicto de EXP-003M (`5m/mean_reversion` no cubre ni el suelo de comisiones) no se
repara aquí con un modelo de fills distinto, y por eso esta lane no abre un experimento de
ejecución nuevo.

## Ancla con EXP-003M

`5m/mean_reversion` se midió aquí con **6.33 bps** de bruto
por señal en VAL y **-51.82 bps** netos por operación
cerrada, con el holdout cerrado y sin reutilizar los fills de 003M. Dos métodos
distintos (cinta observada allí, retorno forward y salida congelada aquí) coinciden en
el signo y en el orden de magnitud de la insuficiencia.
