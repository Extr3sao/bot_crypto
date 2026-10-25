# WP-TDM-12 — FINAL REPORT

**RFC:** RFC-TDM-012 v1.0 · **Fecha:** 2026-10-25 · **Commit de cierre:** ver `RUN_REPORT.json`
**Worktree aislado** desde `504256ec` · checkout compartido intacto (`e67194e7`, 17 modificaciones ajenas)

## VEREDICTO

> ### `NO_ELIGIBLE_CANDIDATE`
> Ninguna de las 24 estrategias existentes alcanza expectativa neta positiva en ninguna de las dos
> ventanas disponibles. **No se emite `PREREG_CANDIDATE`.** No se abre PAPER ni LIVE.
> ### TDM-11: `REJECTED_ALPHA` — confirmado, con una corrección de redacción.
> ### `REVIEW_PARTIAL` · `INDEPENDENCE_NOT_DEMONSTRATED` · `FALSE_SUCCESS = 0` (dentro de lo comprobado)

---

## 1. Evidencia comprobada (no heredada)

Todo lo siguiente se midió en esta sesión, contra blobs versionados y datos sellados:

| Hecho | Medición |
| --- | --- |
| Los 17 hashes del manifiesto TDM-11 resuelven a objetos de `HEAD` | **10/10 evidencias + 7/7 scripts**, 0 ausentes, 0 discrepancias, 0 hashes circulares |
| El ledger de TDM-11 se rederiva de las barras | **115/115 filas**, 0 discrepancias, bruto **−12,577**, neto **−36,368** |
| Los trades no son IID | 49/115 (42,6 %) solapan con otro activo; **26 días** clúster; máx. **13** trades/día |
| El rechazo sobrevive a esa dependencia | IC por día-clúster bruto [−23,22, **−3,10**] → neto superior **−26,89**; bloques de 2/5/10 días: −26,70 / −29,44 / −31,53 |
| El control de look-ahead reproduce | −12,577 → **+17,0538** bps con 12 barras de futuro (**+29,63** de ventaja artificial) |
| El arnés de triaje mide lo mismo que TDM-10 | `volatility@5m` +7,0531 · `breakout@1h` DEV +11,2977 · `ema_crossover@5m` 3 511 trades |
| Ninguna celda gana | **0/24** netas positivas en HOLD, **0/24** en DEV |
| Nada está admitido para paper | ledger: 24 entradas, 17 `NO_GROSS_EDGE` + 7 `COST_KILLED`, **0 admitidas** |
| El árbol está donde dice | HEAD `504256ec`, 0 modificaciones; compartido en `e67194e7` con 17 modificaciones intactas |

## 2. Declaraciones heredadas que NO se verificaron como propias

| Declaración | Estado en este WP |
| --- | --- |
| Cifras de TDM-10 por celda/horizonte (96 combinaciones) | **reutilizadas**; solo se reprodujeron las dos de cabecera y el recuento de trades |
| "TDM-11 se ejecutó en un worktree aislado" | **verificado** (el commit y su árbol lo sostienen) |
| Coste del lado corto | **`UNVERIFIED`**: funding perp no cobrado, fill maker p=0,5, spread estimado a 1 bp |
| Independencia de TDM-11 | **`INDEPENDENCE_NOT_DEMONSTRATED`** — el revisor es el mismo autor |
| API del runtime (`AutonomousPaperRuntime`) | **leída, no ejecutada**: no se arrancó el bucle de paper |

## 3. Corrección F-01 — la cifra "3 de 6" dependía del corte

TDM-11 publicó que la premisa "5 de 6 cubetas SHORT en bajista" se reproduce como **3 de 6**. Esta revisión
encuentra que el número **depende de cómo se ordene**:

| Corte | Resultado |
| --- | --- |
| Solo cubetas `trend=down`, n ≥ 4 | **5 de 6** mayoritariamente cortas (el 5/6 original **sí** se reproduce) |
| Todas las cubetas de régimen (como `regime_table.csv`) | **3 de 6** (lo que reportó TDM-11) |

Ninguna de las dos es una estadística estable, y cinco de las seis cubetas del primer corte tienen n ≤ 32
(dos con n=4 y n=7). Lo que **sí** sigue en pie de TDM-11: el artefacto publicado no tenía columna de
dirección, así que la atribución nunca fue un dato. **El veredicto `NO_GO_ALPHA` no cambia**: se apoya en
el rendimiento de la regla, no en el recuento de cubetas. No se reescribe la evidencia anterior; la
corrección queda en `TDM11_CLOSURE_DECISION.json → contradictory_findings.F-01`.

## 4. Inventario: lo que existe de verdad

| Clase | Nº | Detalle |
| --- | --- | --- |
| `RUNTIME_AUTHORITATIVE` | **0** | ninguna estrategia admitida |
| `RUNTIME_REACHABLE` | **24** | 6 familias × 4 timeframes, instanciadas por el runtime de paper |
| `ORPHAN` | **6** | `EmaCrossoverStrategy` (implementa el protocolo, ningún entrypoint la usa) + 5 estrategias declaradas en `config/strategies.yaml` **sin implementación** |
| `TEST_ONLY` / `EXPERIMENTAL` / `LEGACY` / `DEAD_CODE` | no inventariadas | cobertura declarada, no exhaustiva |

**Hallazgo de inventario:** el catálogo de estrategias del proyecto (`config/strategies.yaml`, 5 entradas)
no coincide con el código que existe. Esas cinco están en `research`/`disabled`, `enabled: false`, y
ninguna tiene clase que las ejecute. El runtime real usa las seis familias de `research/families`.

## 5. Triaje: por qué no hay candidato

1. **El patrón es "bruto ≈ 0, neto ≈ −coste".** 20 de 24 celdas quedan entre −4 y +3 bps brutos. Están
   bien medidas y no tienen edge: es una moneda justa menos comisiones.
2. **Dos celdas son consistentes y aun así pierden**: `trend@1h` (+2,65 HOLD / +1,59 DEV) y
   `mean_reversion@15m` (+2,32 / +2,01). A ~21 bps del umbral. Consistencia no es rentabilidad.
3. **`breakout@1h` es la trampa**: +11,30 en DEV, −6,76 en HOLD. Un candidato si solo se mira DEV.
4. **`ema_crossover` está falsificado**: 3 511 operaciones en 30 días, bruto −0,70; los datos excluyen que
   pague.
5. **La frecuencia no es el problema**: 20/24 celdas ya hacen ≥3 trades/día (hasta 119,9). Ninguna gana.
   Forzar frecuencia sería el error que el RFC prohíbe.
6. **Ninguna celda tiene coste verificado** y ninguna gana ni con coste cero en ambas ventanas: el
   obstáculo es la señal, no la tarifa.

## 6. Qué falta — `NOT_RUN` y `UNVERIFIED`, explícitos

| Elemento | Estado |
| --- | --- |
| Órdenes PAPER / SHADOW / CANARY / LIVE | **NOT_RUN** (0 órdenes) |
| Ventana confirmatoria | **NOT_RUN** — sellada desde `2026-10-24T16:00Z`, ~1 operación/día esperada |
| Suite de tests del repo | **NOT_RUN** — ningún archivo de `src/` o `tests/` modificado |
| Evidencia de fills / funding reales | **UNVERIFIED** — no hay datos de ejecución |
| Spread observado | **UNVERIFIED** — 1 bp estimado en todos los datasets |
| Independencia de autor | **NO DEMOSTRADA** — revisor de implementación, no de identidad |
| Cobertura total del repositorio | **PARCIAL** — acotada a los entrypoints investigados |

## 7. Qué se conserva y qué se descarta

**Se descarta:** las 24 celdas como candidatas a promoción; `ema_crossover` en cualquier timeframe;
cualquier lectura direccional de las cubetas de régimen como señal; las 5 estrategias declaradas sin código
como "estrategias existentes".

**Se conserva:** el arnés de verificación (hashes contra blobs, rederivación de ledger, IC por día-clúster,
control de look-ahead de 12 barras), el ledger de admisión como fuente de verdad de ejecutabilidad, y el
registro de ventanas con etiquetas de contaminación.

## 8. Próximo gate

Un RFC nuevo, con hipótesis específica derivada de estos obstáculos medibles:

1. una entrada con **bruto > 23,79 bps** (o > 9,25 en perp maker) en **dos ventanas independientes**; el
   máximo observado es +7,05;
2. **spread observado** y **funding/fills** modelados antes de cualquier PASS;
3. una **muestra confirmatoria** posterior al corte, hoy inexistente;
4. un **revisor de identidad distinta** para elevar cualquier resultado de `REVIEW_PARTIAL` a
   `REVIEW_VERIFIED`.

No se inicia otro WP. **Nada de este documento autoriza PAPER, LIVE, ni cambios de parámetros.**
`FALSE_SUCCESS = 0` dentro de lo comprobado; los gates no ejecutados figuran como `NOT_RUN`, no como PASS.
