# WP-TDM-12A — INDEPENDENT REVIEW OF WP-TDM-11

**Paquete revisado:** `evidence/tdm/wp-tdm-11/` en `504256ec`
**Revisor:** tercera implementación del mismo operador · **Evidencia:** `.tdm12/review.json`
**Resultado global:** **`REVIEW_PARTIAL`** · **Independencia:** **`INDEPENDENCE_NOT_DEMONSTRATED`**
**Veredicto sobre la hipótesis:** `REJECTED_ALPHA` (sin cambios)

---

## 1. Resumen

| Pregunta | Respuesta | Base |
| --- | --- | --- |
| ¿Está el árbol donde dice? | **sí** | HEAD `504256ec`, 0 modificaciones; checkout compartido intacto (17 heredadas) |
| ¿Los hashes resuelven a objetos versionados? | **sí** | 10/10 evidencias + 7/7 scripts contra blobs de `HEAD` |
| ¿El ledger se rederiva de las barras? | **sí** | 115/115 filas, 0 discrepancias, bruto −12,577 |
| ¿Los 115 trades son independientes? | **no del todo** | 49/115 (42,6 %) solapan con otro activo; 26 días-clúster; máx. 13 trades/día |
| ¿El rechazo sobrevive a la dependencia? | **sí** | IC por día [−23,22, −3,10] bruto → neto superior −26,89 |
| ¿El control de look-ahead reproduce? | **sí** | +17,0538 bps con 12 barras de futuro vs −12,577 PIT (ventaja **29,63 bps**) |
| ¿La premisa direccional reproduce? | **depende del corte** | 3/6 con ranking mixto; **5/6** con ranking solo-bajista → ver F-01 |
| ¿Hay independencia de autor? | **no** | mismo operador; no existe actor separado en este workspace |

## 2. Integridad contra objetos versionados (R-02)

`RUN_REPORT.json` de TDM-11 declara 10 artefactos y 7 scripts. Los 17 hashes se comprobaron con
`git cat-file -p HEAD:<path>`, **no** contra el directorio de trabajo:

| Comprobación | Resultado |
| --- | --- |
| Evidencias ausentes | 0 |
| Evidencias con hash distinto del blob | 0 |
| Scripts con hash distinto del blob | 0 |
| Hashes circulares (archivo que se lista a sí mismo) | **ninguno** — `RUN_REPORT.json` se excluye de su propio mapa |

No se encontró ni un hash huérfano ni un artefacto declarado que no exista. El mecanismo de sellado de
TDM-11 es sólido.

## 3. Reproducción del ledger (R-03)

Reimplementación **tercera** (no las de TDM-10 ni TDM-11): carga de barras, z-score trailing, señales de
la familia, ventana, latencia y hold, escritos desde cero.

| Comprobación | Resultado |
| --- | --- |
| Operaciones derivadas / declaradas | 115 / 115 |
| Filas con identidad distinta (timestamp, activo, dirección) | 0 |
| Filas con bruto distinto (> 1e-3 bps) | 0 |
| Bruto medio rederivado | **−12,577 bps** |
| Neto medio | **−36,368 bps** |

El ledger de TDM-11 es reproducible desde los datos sellados por un tercer camino de código.

## 4. Dependencia estadística (R-04) — la parte que TDM-11 no había medido

TDM-11 reportó un IC de bootstrap de bloques y lo llamó conservador. Aquí se mide cuánta dependencia hay
realmente:

| Hecho medido | Valor |
| --- | --- |
| Días con actividad | **26** (no 115 unidades independientes) |
| Trades que solapan en el tiempo con otro activo | **49 / 115 (42,6 %)** |
| Máximo de trades en un día | **13** |
| Media por día activo | 4,42 |
| Concentración por activo | BTC 31,3 % · ETH 30,4 % · SOL 38,3 % |

Con esa estructura, el bootstrap de trades IID es demasiado optimista. El intervalo correcto remuestrea
**días completos** y arrastra todos los trades de cada día:

| Esquema | IC95 bruto | Cota superior neta |
| --- | --- | --- |
| Día-clúster (primario aquí) | [−23,22, **−3,10**] | **−26,89** |
| Bloques contiguos de 2 días | [−23,83, −2,90] | −26,70 |
| Bloques contiguos de 5 días | [−20,84, −5,65] | −29,44 |
| Bloques contiguos de 10 días | [−17,61, −7,74] | −31,53 |

**El rechazo sobrevive a la dependencia**: en los cuatro esquemas la cota superior del neto está entre
−26,7 y −31,5 bps. El intervalo de TDM-11 era más estrecho de lo que la estructura permite, y aun así
concluía lo mismo. La conclusión es robusta; el IC reportado era **algo optimista**, no erróneo en signo.

Detalle por activo (bruto, no neto): BTC −8,19 · ETH −19,28 · SOL −10,84. Los tres negativos también en
esta implementación.

## 5. Hallazgo contradictorio F-01 — la cifra "3 de 6" depende del corte

TDM-11 afirmó que la premisa del RFC anterior ("5 de 6 mejores cubetas SHORT en bajista") se reproduce
como **3 de 6**. Esta revisión encuentra que **ambas cifras son correctas bajo su propio ranking**, y que
el número no es una estadística estable:

| Corte | Definición | Resultado |
| --- | --- | --- |
| **A — solo bajista** | ordenar únicamente cubetas `trend=down` con n ≥ 4 | **5 de 6** mayoritariamente cortas |
| **B — eje mixto** | ordenar todas las cubetas de régimen (tendencia y volatilidad), como hace `regime_table.csv` | **3 de 6** son "down + mayoritariamente corta" |

Top-6 del corte A: `breakout@1h` (n=7, 100 % short) · `volatility@5m` (n=4, 25 %) ·
`ema_crossover@1h` (n=32, 90,6 %) · `breakout@30m` (n=12, 75 %) · `momentum@5m` (n=74, 77 %) ·
`breakout@15m` (n=24, 91,7 %).

**Qué significa:** la frase del RFC anterior se reproduce literalmente si se condiciona a tendencia
bajista (5/6), y se reduce a 3/6 si se rankean todos los regímenes. TDM-11 eligió el corte B y lo presentó
como *la* recomputación; eso sobrevende una cifra que depende del criterio de ordenación. Lo que **sí**
sigue en pie de TDM-11: `regime_table.csv` no tiene columna de dirección, así que ninguna de las dos
cifras estaba publicada como dato, y cinco de las seis cubetas del corte A tienen n ≤ 32 (dos con n=4 y
n=7), de modo que ninguna soporta una afirmación direccional.

**Efecto sobre el veredicto de TDM-11:** **ninguno**. `NO_GO_ALPHA` se apoya en el rendimiento de la regla
(−36,37 bps netos, IC −48,06/−24,18), no en el recuento de cubetas. El hallazgo se registra como
`F-01` en `TDM11_CLOSURE_DECISION.json` y **no** se reescribe la evidencia anterior, tal como exige A5.

## 6. Controles reproducidos (R-05)

| Control | TDM-11 | Esta revisión |
| --- | --- | --- |
| PIT (regla real) | −12,577 bps | **−12,577 bps** |
| Look-ahead 12 barras | +17,05 bps | **+17,0538 bps** |
| Ventaja artificial | 29,63 bps | **29,6308 bps** |
| Entrada en la barra de decisión | −11,98 bps | **−11,9809 bps** |

Coincidencia exacta. El premio de mirar 12 barras al futuro sigue siendo ~30 bps: suficiente para
fabricar un candidato y por eso el control está en el arnés, no en un anexo.

## 7. Independencia (A3, T-03)

No existe en este workspace un actor distinto del constructor. La revisión usa **implementación separada**
(tercera), **contexto de ejecución separado** (worktree y proceso nuevos) y **verificación contra blobs
versionados** — pero el autor es el mismo.

Por eso:
- el resultado es **`REVIEW_PARTIAL`**, no `REVIEW_VERIFIED`;
- el estado de independencia es **`INDEPENDENCE_NOT_DEMONSTRATED`**;
- no se emite ningún certificado, y este documento no debe citarse como revisión de terceros.

Un revisor realmente distinto podría ejecutar `scripts/tdm12_review.py` sin leerlo y comparar
`review.json` con lo aquí publicado; mientras eso no ocurra, la etiqueta no cambia. **No** se puede
"demostrar" independencia cambiando el prompt del mismo autor.

## 8. Límites de esta revisión

1. No verifica la integridad histórica del proveedor de datos: solo que los archivos no cambiaron y que su
   uso es causal.
2. No puede certificar el coste del lado corto (funding, fills): no hay datos de ejecución.
3. No evalúa la ventana confirmatoria: está sellada y sin adquirir.
4. `F-01` es una corrección de redacción estadística, no un cambio de veredicto.

## 9. Dictamen

`integrity_status = VERIFIED` · `reproduction_status = REPRODUCED` ·
`independence_status = INDEPENDENCE_NOT_DEMONSTRATED` · `review_result = REVIEW_PARTIAL` ·
`alpha_status = REJECTED_ALPHA` · `can_promote = false`.

Siguiente paso para elevar a `REVIEW_VERIFIED`: un revisor de identidad distinta ejecutando la misma
comprobación y firmando el resultado. Nada del código ni de los datos necesita cambiar para ello.
