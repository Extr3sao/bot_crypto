# RUN REPORT — EXP-003N (gross-first strategy discovery)

- Experimento: `EXP-003N-GROSS-FIRST-DISCOVERY-001`
- Diseño congelado: 2026-10-20T18:38:16Z sobre `9800925`
- Screening: 2026-10-20T19:32:34Z · validación: 2026-10-20T19:37:05Z
- Verificación: 2026-10-20T22:12:10Z · veredicto `PASS`
- Modo: research offline. Órdenes reales: **0**. Holdout `2026-08-06 → 2026-08-20`: **cerrado**.

## Pregunta

Does any mechanism that already exists in this repository produce a gross income per signal that covers its own round-trip cost on valid, point-in-time bars?

EXP-003M measured that 5m/mean_reversion's most generous fill model still earns 0.2669 USDT per closed trade against a 0.75 USDT fee floor. Modelling fills more carefully cannot create gross income; only a different gross can.

## Preregistración — y su límite

El protocolo completo está en `design/PREREGISTRATION.md` y `design/DESIGN.json`. Se congeló
en disco a las 2026-10-20T18:38:16Z y el screening corrió después, pero **entró en Git
después de que existiera el análisis**: el congelamiento está anclado por contenido
(`SCREENING.json` guarda el `design_sha256` con el que se ejecutó y el verificador lo
compara), no por tiempo. Por tanto este análisis es **retrospectivo con protocolo
declarado**, no prospectivo, y así se cita en todo el informe.

## Universo de estrategias

- Clases con forma de estrategia inventariadas: `EXPERIMENTAL` = 3, `RESEARCH_ONLY` = 6, `RUNTIME_REACHABLE` = 6, `TEST_ONLY` = 1
- **`RUNTIME_AUTHORITATIVE` no aparece en el inventario derivado.** El criterio es «importada
  o instanciada desde un entrypoint», y las seis AlphaFamilies se construyen en
  `scripts/autonomous_paper.py` pero su señal pasa después por router, admisión, riesgo y
  decisión antes de ejecutarse: eso las deja en `RUNTIME_REACHABLE`. El mapa de autoridad
  del propio repositorio (`docs/runtime/runtime_authority_map.md`) las lista como
  `RUNTIME_AUTHORITATIVE`. La diferencia es de vocabulario, no de medida: en ambos casos son
  las mismas seis clases y las mismas señales, y ninguna puerta económica depende de la
  etiqueta. Se deja visible en lugar de reconciliarse por decreto.
- `screened_here = no` en las clases `*Machine` de `pit15.py` quiere decir que la celda se
  midió por familia (lane B), no por clase: la unidad de este experimento es la familia, no
  el objeto Python que la implementa. Las tres familias de lane B se ejecutan con esas
  máquinas a través de `run_family`.

## Suelo de costes con el que se compara todo

- Comisión spot VIP0: **10.0 bps** por lado.
- Suelo comparable (ida y vuelta): **20.0 bps**; con descuento BNB **15.0 bps**.
- Coste completo aplicado por símbolo (comisión + medio spread + slippage + impacto, dos patas, 500 USDT):

| símbolo | tier | ida y vuelta (bps) | solo precio por lado (bps) |
| --- | --- | ---: | ---: |
| `BTCUSDT` | `TIER1` | 24.79 | 2.393 |
| `ETHUSDT` | `TIER1` | 24.79 | 2.393 |
| `SOLUSDT` | `MAJOR` | 27.31 | 3.655 |

## Qué se ejecutó

| etapa | comando | salida |
| --- | --- | --- |
| inventario + congelación | `scripts/exp_003n_preregister.py` | `design/` |
| protocolo legible | `design/PREREGISTRATION.md` | hipótesis, particiones, puertas y su límite de procedencia |
| screening | `scripts/exp_003n_screen.py` | `analysis/SCREENING.json`, `analysis/SIGNALS.jsonl.gz`, `ECONOMIC_SCREENING.csv` |
| validación | `scripts/exp_003n_validate.py` | `analysis/VALIDATION.json`, `analysis/DECISION.json` |
| verificación | `scripts/exp_003n_verify.py --negative-controls` | `analysis/VERIFICATION.json` |
| tests | `pytest tests/unit/vision tests/unit/paper tests/unit/reports/test_exp_003n_screen.py` | `analysis/TESTS.json`, `evidence/*.log` |
| informe | `scripts/exp_003n_report.py` | estos documentos |
| sello | `scripts/exp_003n_pipeline.py seal` | `SHA256SUMS.txt`, `SEAL.json` |

## Muestra

| lane | celda | señales RESEARCH | señales IS | señales VAL | señales/día |
| --- | --- | ---: | ---: | ---: | ---: |
| `lane_a` | `breakout@1h` | 164 | 68 | 52 | 14.43 |
| `lane_a` | `breakout@4h` | 22 | 1 | 15 | 2.07 |
| `lane_a` | `breakout@5m` | 2131 | 961 | 653 | 184.91 |
| `lane_a` | `ema_crossover@1h` | 2667 | 1022 | 961 | 235.33 |
| `lane_a` | `ema_crossover@4h` | 499 | 109 | 230 | 46.18 |
| `lane_a` | `ema_crossover@5m` | 34424 | 14911 | 11179 | 2,996.80 |
| `lane_a` | `mean_reversion@1h` | 106 | 44 | 36 | 9.27 |
| `lane_a` | `mean_reversion@4h` | 18 | 4 | 10 | 1.62 |
| `lane_a` | `mean_reversion@5m` | 1408 | 581 | 506 | 122.57 |
| `lane_a` | `momentum@1h` | 1797 | 779 | 576 | 156.60 |
| `lane_a` | `momentum@4h` | 432 | 74 | 224 | 40.21 |
| `lane_a` | `momentum@5m` | 6704 | 3929 | 1617 | 555.26 |
| `lane_a` | `trend@1h` | 970 | 512 | 343 | 80.01 |
| `lane_a` | `trend@4h` | 297 | 85 | 140 | 26.59 |
| `lane_a` | `trend@5m` | 942 | 701 | 121 | 74.50 |
| `lane_a` | `volatility@1h` | 29 | 7 | 16 | 2.59 |
| `lane_a` | `volatility@4h` | 4 | 3 | 1 | 0.30 |
| `lane_a` | `volatility@5m` | 155 | 71 | 50 | 13.34 |
| `lane_b` | `mean_reversion_vol_liq@1h` | 7 | 0 | 4 | 0.69 |
| `lane_b` | `mean_reversion_vol_liq@4h` | 0 | 0 | 0 | 0.00 |
| `lane_b` | `trend_pullback@1h` | 30 | 10 | 17 | 2.56 |
| `lane_b` | `trend_pullback@4h` | 2 | 0 | 0 | 0.23 |
| `lane_b` | `vol_regime_breakout@1h` | 0 | 0 | 0 | 0.00 |
| `lane_b` | `vol_regime_breakout@4h` | 0 | 0 | 0 | 0.00 |

## Warm-up frente a ventana (lane B)

Las familias de WP-EDGE-015 se parametrizan en horas, y su ventana de percentiles consume
historia antes de poder decidir. Si el warm-up se come la muestra, un cero no es ausencia
de ventaja: es ausencia de datos. Esta tabla lo hace explícito.

| familia | warm-up requerido (h) | IS (h) | VAL (h) | TEST (h) | veredicto |
| --- | ---: | ---: | ---: | ---: | --- |
| `vol_regime_breakout` | 720 | 480 | 360 | 264 | `INSUFFICIENT_EVIDENCE` |
| `trend_pullback` | 200 | 480 | 360 | 264 | `INSUFFICIENT_EVIDENCE` |
| `mean_reversion_vol_liq` | 720 | 480 | 360 | 264 | `INSUFFICIENT_EVIDENCE` |

Cuando el warm-up requerido supera la ventana de VAL, el cero se reporta como
`INSUFFICIENT_EVIDENCE` y nunca como `REJECT`: no se puede refutar lo que no se midió.

## Reparto de veredictos

| veredicto | celdas |
| --- | ---: |
| `EXPERIMENT` | 1 |
| `INSUFFICIENT_EVIDENCE` | 10 |
| `REJECT` | 13 |

Veredicto del experimento: **`NO_VIABLE_CANDIDATES`**.

## Reproducción desde checkout limpio

- Commit reproducido: `cd3fc31` en un worktree `--detach`, sin cambios
  locales antes de ejecutar (0 líneas en `git status`).
- Dataset: 3/3 digests iguales a los que fija el diseño.
- Screening re-ejecutado: 24/24 celdas idénticas (`NO_VIABLE_CANDIDATES`).
- Validación re-ejecutada: 24/24 celdas idénticas.
- Verificación independiente en el worktree: 12 comprobaciones, 10 controles negativos, veredicto `PASS`.
- Tests en el worktree: 20 pasan, 0 fallan.

Lo que esta reproducción **no** prueba:

- no order was placed and no fill is observed: this reproduces the arithmetic, not the market
- the reproduction writes into <worktree>/repro-out, so the checkout stays as committed; what is compared is the numbers, not the bytes
- the frozen bars were copied in after their digests matched, not re-downloaded here; EXP-003M's rehearsal already re-downloaded this same window byte-identically from the venue
- lane B cells with no sample stay INSUFFICIENT_EVIDENCE: a reproduction cannot create sample

## Defectos encontrados y reparados

| id | defecto | impacto | reparación |
| --- | --- | --- | --- |
| `DEF-003N-01` | `exp_003n_screen.py` imprimía `target.relative_to(REPO)` y lanzaba `ValueError` cuando `--out` apuntaba fuera del repositorio (el worktree llegaba en forma corta 8.3) | el fallo ocurría **después** de escribir `SCREENING.json`, `SIGNALS.jsonl.gz` y `ECONOMIC_SCREENING.csv`: un llamador que solo mira el código de salida habría tirado un resultado bueno | la línea de diagnóstico usa la ruta absoluta si el destino está fuera del repo; no se tocó código de medida |

`DEF-003N-01` lo encontró la reproducción desde checkout limpio, no el constructor: es la
razón por la que esa reproducción existe. Los defectos heredados de `EXP-003M` (`R1` CRLF en
el sello, `R2` tests que dependían de un árbol no commiteado) están en
`evidence/CLEAN_CHECKOUT_REHEARSAL.json` con su commit de reparación.

## Gobernanza

```
LIVE_TRADING=DISABLED
TRADES_AUTHORIZED=0
PAPER_PROMOTION=NOT_AUTHORIZED
OOS_HOLDOUT=CLOSED
FALSE_SUCCESS=0
```
