# FINAL REPORT — EXP-003N

## Respuesta: `NO_VIABLE_CANDIDATES`

Ningún mecanismo que exista hoy en el repositorio produce, con muestra suficiente para
medirlo y con el coste completo aplicado, una expectativa económica positiva por
operación cerrada. No es un problema de ejecución: es un problema de ingreso bruto.

El único neto positivo del barrido es una celda con **una** operación cerrada. Se
publica, no se promociona: una operación no es una muestra, y por eso figura como
`INSUFFICIENT_EVIDENCE` y no como candidato.

## Naturaleza del análisis

Protocolo congelado en disco a las 2026-10-20T18:38:16Z (`design/DESIGN.json`,
`design/PREREGISTRATION.md`), screening posterior, pero **publicación en Git posterior al
análisis**. El congelamiento está anclado por contenido y no por tiempo: esto es un
**análisis retrospectivo con protocolo declarado**, no una predicción prospectiva. Ninguna
cifra de este informe se presenta como validación fuera de muestra de una regla que se
eligió mirando el futuro: `VAL` no participó en la elección del horizonte y `TEST` no se usó
para decidir, pero ambos ya habían ocurrido cuando se congeló el protocolo.

Reproducción desde checkout limpio (`cd3fc31`): 24/24 celdas idénticas, 24/24 en validación, veredicto `REPRODUCED`. Los números se re-derivan; el mercado, no.

## El número que decide

- Mejor celda por **operación cerrada** (el criterio de la tabla): `momentum@1h` (lane_a), **-37.58 bps** netos con 576 cierre(s) en VAL, acierto 42.5 % y PF 0.80.
- La misma celda por **señal**: bruto **23.49 bps** frente a coste completo **27.31 bps** → neto **-3.82 bps**.
- El déficit **por señal** más pequeño es otro: `breakout@1h` (24.48 bps brutos menos 27.31 bps = -2.83 bps). Se publican las dos lecturas
porque el orden depende de la unidad y ninguna de las dos cubre el peaje.
- Celdas con neto positivo tras coste completo: **1** de **24**.

## Qué se descartó estructuralmente

- `5m/mean_reversion` (el candidato de 003L/003M): no se rehabilita. Aquí se mide con un
  método distinto y vuelve a quedar por debajo del suelo de 20.00 bps.
- Las familias de WP-EDGE-015 se re-miden en un universo y un periodo nuevos (majors,
  junio-agosto) sin reutilizar la corpora anterior; el resultado se suma a su historial, no
  lo sustituye.

### Por familia, con la muestra que la sostiene

Solo cuentan las celdas que pasan la puerta de muestra: una familia con cuatro señales no
queda refutada, queda sin medir, y así se dice.

| familia | celdas con muestra | mejor bruto/señal (bps) | IC95 inf. (bps) | ¿cubre el suelo? |
| --- | ---: | ---: | ---: | --- |
| `breakout` | 2 | 26.53 | -97.26 | no |
| `ema_crossover` | 3 | 8.36 | -68.87 | no |
| `mean_reversion` | 2 | 45.28 | -4.19 | no |
| `mean_reversion_vol_liq` | 0 | — | — | no medida: ninguna celda pasa la muestra |
| `momentum` | 3 | 25.64 | -257.04 | no |
| `trend` | 3 | 46.75 | -219.33 | no |
| `trend_pullback` | 0 | — | — | no medida: ninguna celda pasa la muestra |
| `vol_regime_breakout` | 0 | — | — | no medida: ninguna celda pasa la muestra |
| `volatility` | 1 | 17.07 | -57.37 | no |

## Lo que el experimento no dice

- No dice que no exista ventaja en el mercado: dice que ninguna de las que este repositorio
  implementa hoy la tiene en esta muestra.
- No dice nada sobre el holdout `2026-08-06 → 2026-08-20`: sigue cerrado y sin usar.
- No convierte un bruto en una ganancia: el escenario favorable de fills de 003M ya
  demostró que un toque no es un fill, y aquí no se modela fill alguno.
- El bootstrap sobre 5 días asume estacionariedad local; 46 días son cinco a nueve bloques,
  y eso acota lo que un intervalo puede afirmar.

## Verificación

- `12/12` comprobaciones y `10/10` controles negativos, `false_success=0`.
- El verificador no comparte código con el constructor y recalcula desde las barras.

## Gobernanza

```
LIVE_TRADING=DISABLED
TRADES_AUTHORIZED=0
PAPER_PROMOTION=NOT_AUTHORIZED
OOS_HOLDOUT=CLOSED
RISK_LIMITS_CHANGED=0
```

Todo lo anterior se sostiene sobre los artefactos de este directorio, sellados por
`SHA256SUMS.txt` y verificados por un programa distinto del que los escribió.
