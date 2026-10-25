# WP-TDM-12 — RUN REPORT

**RFC:** RFC-TDM-012 v1.0 · **WPs:** 12A (revisión y cierre) + 12B (inventario y triaje)
**Commit base:** `504256ec` · **Rama:** `evidence/tdm12` · **Worktree aislado**
**Resultado:** **`NO_ELIGIBLE_CANDIDATE`** · TDM-11: **`REJECTED_ALPHA`** · `FALSE_SUCCESS = 0`
**Órdenes:** PAPER **0** · LIVE **0**

---

## 1. Qué se ejecutó realmente

| Paso | Comando | Duración | Salida | Estado |
| --- | --- | --- | --- | --- |
| Preflight + revisión 12A | `python scripts/tdm12_review.py` | ~331 s | `.tdm12/review.json` | exit 0 |
| Recálculo del claim (2 cortes) | `python scripts/tdm12_review.py --claim-only` | ~40 s | `review.json::claim` | exit 0 |
| Inventario + triaje 12B | `python scripts/tdm12_inventory.py` | ~274 s | `CANDIDATE_REGISTRY.*`, `DATA_WINDOW_REGISTRY.json`, `.tdm12/triage.json` | exit 0 |
| Publicación | `python scripts/tdm12_publish.py` | <1 s | `TDM11_CLOSURE_DECISION.json`, `DECISION_REGISTER.json`, `RUN_REPORT.json` | exit 0 |

Rutas descubiertas, no supuestas: entrypoints, config y ledger se localizaron en el árbol
(`git ls-files`, glob, AST) y se registran con su SHA en `CANDIDATE_REGISTRY.json`.

## 2. Qué NO se ejecutó

| Actividad | Estado | Motivo |
| --- | --- | --- |
| Órdenes PAPER / SHADOW / CANARY / LIVE | **NOT_RUN** | fuera de alcance; 0 órdenes |
| Evaluación en ventana confirmatoria | **NOT_RUN** | no existe muestra (sealed desde 2026-10-24T16:00Z) |
| Suite de tests del repositorio | **NOT_RUN** | ningún archivo de `src/` o `tests/` fue modificado |
| Prueba de ejecución real (fills) | **NOT_RUN** | sin datos de ejecución; coste del corto `UNVERIFIED` |
| Cambios en estrategias, riesgo, costes, ejecución | **NOT_RUN** | prohibido por el RFC |
| Escaneo de `tests/**` como candidatos | **NOT_RUN** | irrelevante para ejecutabilidad; declarado en la cobertura |

Ninguno de estos `NOT_RUN` se convierte en PASS en ningún documento.

## 3. Resultados de 12A

| Comprobación | Resultado |
| --- | --- |
| HEAD / rama / árbol | `504256ec` / `evidence/tdm12` / limpio; compartido `e67194e7` con 17 modificaciones intactas |
| Hashes de TDM-11 contra blobs versionados | **10/10 evidencias + 7/7 scripts**, 0 ausentes, 0 discrepancias |
| Rederivación del ledger | **115/115** filas, 0 problemas, bruto −12,577, neto −36,368 |
| Dependencia | 49/115 trades concurrentes con otro activo; 26 días-clúster; máx. 13/día |
| IC por día-clúster | bruto [−23,22, −3,10] → **neto superior −26,89** |
| Sensibilidad a bloques (2/5/10 días) | neto superior −26,70 / −29,44 / −31,53 (**todos negativos**) |
| Look-ahead 12 barras | −12,577 → **+17,0538** (ventaja 29,63 bps) |
| Premisa direccional | **depende del corte: 5/6 (solo bajista) vs 3/6 (eje mixto)** |
| Independencia de autor | **`INDEPENDENCE_NOT_DEMONSTRATED`** |

Veredicto: `REVIEW_PARTIAL`. Integridad y reproducción verificadas; autoría no separada.

## 4. Resultados de 12B

| Métrica | Valor |
| --- | --- |
| Filas de registro | **30** (24 medidas + 1 implementación huérfana + 5 declaradas sin código) |
| Estrategias `RUNTIME_AUTHORITATIVE` | **0** (ledger: 0 admitidas de 24) |
| Estrategias `RUNTIME_REACHABLE` | 24 celdas (6 familias × 4 tf) |
| Netas positivas en HOLD | **0/24** |
| Netas positivas en DEV | **0/24** |
| Mejor bruto HOLD | +7,05 bps (`volatility@5m`, n=58) |
| Mejor bruto DEV | +11,30 bps (`breakout@1h`, n=290) |
| Celdas con potencia suficiente | 23/24 |
| Celdas con coste verificado | **0/24** |
| Celdas ≥3 trades/día | 20/24 — **ninguna rentable** |
| Candidatos elegibles | **0** |

Decisión: `NO_ELIGIBLE_CANDIDATE`, sin `PREREG_CANDIDATE`.

## 5. Errores del propio WP

| ID | Error | Causa | Arreglo |
| --- | --- | --- | --- |
| E1 | El inventario listaba el `Protocol` `Strategy` como candidato (31 filas) | el escaneo AST encontró su `evaluate()` stub | excluir `protocols.py` y la clase `Strategy` → **30 filas** |
| E2 | La primera versión del claim usaba cubetas por activo (n=2) | slicing distinto del histórico | se reescribió para rankear por celda y se reportan **los dos cortes** |

`E2` no fue un bug de código sino de método: el primer corte daba 3/6 "por casualidad" con cubetas de dos
operaciones. Se sustituyó por la comparación explícita de los dos rankings, que es la que produce F-01.

## 6. Evidencia y hashes

Manifiesto completo en `RUN_REPORT.json` (`evidence`, `code_sha256`, `inputs`), con hashes calculados sobre
los archivos publicados y **revalidados contra los blobs del commit de cierre** (no solo contra el
directorio de trabajo). `RUN_REPORT.json` excluye su propio hash.

## 7. Límites

1. Inventario acotado a los entrypoints investigados; no exhaustivo del repositorio.
2. `INDEPENDENCE_NOT_DEMONSTRATED`: revisión de implementación, no de autor.
3. Coste del corto no verificado (funding/fills) y spread estimado.
4. Sin ventana confirmatoria: cualquier hipótesis futura espera datos.
5. Las cifras de TDM-10 se reutilizan como evidencia heredada, reproducidas donde había datos
   (24 celdas, 16 316 trades, dos cifras de cabecera).
