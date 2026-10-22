# FINAL_REPORT — RFC-TAP-AI-BOTS-003H

**Veredicto:** `PARTIAL`
**Puertas H1-H5, H7:** PASS · **H6:** PASS (671 passed, exit 0) · **H8:** `INSUFFICIENT_SAMPLE`
**Independencia:** `INDEPENDENT_VERIFICATION_PENDING`
**LIVE:** no habilitado (sin ruta de orden) · **`REAL_MODEL_CALLED=false`** · **`FALSE_SUCCESS=0`**

---

## 1. Qué se ha corregido

El defecto D5 de 003G ya no existe como ambigüedad: una sesión PAPER que termina con una
posición abierta **publica lo que esa posición debe**, lo prueba con identidades y un verificador
externo lo recalcula desde la fila `FILL` y el JSONL de 1 minuto.

Medido en la sesión de este WP (`smoke`, 10 ciclos, 09:03:19Z→09:45):

| | Antes (003G) | Ahora (003H) |
| --- | --- | --- |
| `costs_usdt` | 0 | 0 (semántica intacta) |
| Comisión devengada de la posición abierta | **invisible** | `entry_commissions_accrued_open_usdt = 0,5` |
| Coste total | no existía | `costs_total_usdt = 0,5` |
| PnL no realizado | no existía | `pnl_unrealised_usdt = +0,49443125` (neto de la comisión) |
| Equity marcado | 9 998,37 en reconciliación, 10 000,0 en resumen | `marked_equity_usdt = 10 000,49443125`, reconstruible desde el minuto crudo |
| Identidades | 6 | **11** (5 nuevas, incluida la disjunción abierto/cerrado) |
| Verificación | no cubría posición abierta | checks 26-30, con el devengo recalculado |

## 2. Puertas

| Puerta | Umbral | Medido | Estado |
| --- | --- | --- | --- |
| H1 contabilidad | totales cuadran contra bytes crudos | 0,5 = 0,5; equity marcado reconstruido desde el cierre 1 m | **PASS** |
| H2 sin doble conteo | 0 posiciones en ambas listas | 1 `position_id`, 0 solapes; identidad `true` | **PASS** |
| H3 instantes | 4 instantes ordenados, 2 esperas distintas | `received ≤ quote_ts`; `quote_lag` 21 538 ms y `opinion_age` 51 538 ms recomputados | **PASS** |
| H4 settle | 0 minutos en vivo guardados antes de `close + settle_ms` | 62 minutos, mínimo 2 544 ms ≥ 2 500 | **PASS** |
| H5 proyección | resumen de sesión = ledger | `SUMMARY.json.accounting` = `RUN_END` | **PASS** |
| H6 regresión | 0 fallos nuevos | 671 passed, exit 0; el test del dashboard (antes rojo) pasa ahora con escritor concurrente | **PASS** |
| H7 LIVE | 0 órdenes y 0 rutas | checks 5/23 + `--mode LIVE` rechazado | **PASS** |
| H8 economía | ≥ 30 cierres | 1 relleno, 0 cierres | **INSUFFICIENT_SAMPLE** |

**La rama de cierre no se ha ejercitado en esta sesión** (0 cierres). Está probada por test
(`test_a_close_moves_the_commission_from_accrued_to_realised_once`: la comisión pasa de devengada
a realizada exactamente una vez y `costs_total` no se duplica). No se presenta como medida en
vivo.

## 3. Por qué `PARTIAL` y no `PASS`

1. `INDEPENDENT_VERIFICATION_PENDING`: el verificador de 33 checks lo escribió el mismo agente
   que el código. Sobre la sesión de 003G falla 5 checks (4 de contrato + el drift de runtime),
   lo que demuestra que no es vacuo, pero no sustituye a un revisor tercero.
2. H8: sin muestra económica no se declara rentabilidad.

Nada de esto invalida la corrección contable: está medida, versionada y reproducible.

## 4. Defectos de este WP

| ID | Defecto | Tratamiento |
| --- | --- | --- |
| 003H-D1 | `costs_usdt` omitía la comisión devengada; la fila `FILL` no llevaba comisión | **Corregido** (`paper-accounting/2`, tests, checks 26-30) |
| 003H-D2 | El test del dashboard hasheaba `reports/` compartido y fallaba con un escritor ajeno | **Reproducido** (1 fichero de 7 845) y **corregido** aislando el sujeto; 14/14 con escritor activo |
| 003H-D3 | `--full-store` escribía en `session/compare/`, sobrescribiendo la comparación prospectiva | **Corregido**: un directorio por ámbito |
| 003H-D4 | El resumen de sesión no publicaba contabilidad | **Corregido**: proyección + check 33 |
| 003H-D5 | El verificador de 003G falla 1/25 sobre su propia sesión | **Declarado** (drift de runtime por los cambios de 003H) |
| 003H-D6 | Una re-ejecución del verificador de 003G **sobrescribió** su `VERIFICATION.json|md` (25 → 24 PASS) | **Declarado**; `--out-dir` añadido a ambos verificadores; texto original en `PRESERVED_003G_VERIFICATION.md` como transcripción, no como artefacto restaurado |

D6 es el episodio que más importa declarar: la herramienta de verificación escribía dentro de la
sesión verificada y, al re-verificar evidencia congelada, la modificó. La propiedad que faltaba
—«verificar no es escribir»— es ahora una opción explícita.

## 5. Viabilidad de una campaña PAPER continua de 24–72 h

**Respuesta corta: técnicamente viable, pero no todavía, y no con este objetivo económico.**
Medido en este WP:

**Lo que ya aguanta**

- El bucle prospectivo corre en cadencia de 5 m sin perderse ciclos: 10/10 ciclos, 0 bloqueos,
  0 lecturas stale, 0 desviaciones de prefijo y `data_time ≤ decision_time` en 10/10.
- El coste de recursos es pequeño: ~286 minutos por símbolo en 45 min → ~2 × 1 440 filas/día
  (~0,7 MB/día), stream y ledgers de unos pocos MB; cada ciclo tarda segundos.
- No existe ruta de orden: una campaña de 72 h es PAPER por construcción.
- La contabilidad ahora dice la verdad al final de cualquier ventana, incluso con posiciones
  vivas — que es precisamente el caso de una campaña larga.

**Lo que hay que resolver antes de lanzarla** (por orden de riesgo medido)

1. **Bloqueo permanente por vela revisada.** En 003G el venue revisó una vela 78 s después del
   cierre y el símbolo quedó bloqueado el resto de la sesión (31 eventos `DUPLICATE_CONFLICT`).
   En 45 min de este WP no ocurrió ninguno, pero la probabilidad crece con el tiempo: una
   campaña de 24–72 h casi seguro vivirá el caso. Hace falta una política de **revalidación**
   (re-leer con `settle`, reconciliar dentro de una ventana acotada y registrar el hecho) o un
   desbloqueo operado con evidencia; sin ella la campaña se degrada a «no operar» en silencio.
2. **Sin supervisor ni reanudación.** Si el proceso muere, la sesión muere; además el runner
   **borra** `STREAM.jsonl` al arrancar en el mismo directorio, así que un reinicio destruiría la
   traza anterior. Para 24–72 h: lanzador sin ventana (`ops/windowless.py`), directorio por
   tramo, heartbeat y reinicio con directorio nuevo.
3. **Observabilidad de bloqueo.** `BLOCKED`/`STALE`/`CLOCK_SKEW` deben alertar; hoy sólo quedan
   en el stream. Un panel o un fichero de estado por ciclo es suficiente.
4. **Host que no duerma.** Si el equipo suspende, se pierden ciclos sin que el sistema lo diga.

**Lo que no se puede prometer**

- La puerta económica (≥ 30 cierres) probablemente **no** se alcanza en 24–72 h: 1 relleno en
  45 min, con stop al 0,5 % y una posición que bloquea su símbolo mientras vive. Una campaña de
  ese tamaño sirve para *soak* operativo y validación contable, no para un veredicto de
  rentabilidad. Para economía hace falta otra cosa (más símbolos, más tiempo, o un proveedor
  real), y sigue bloqueada por la revisión de un tercero.

**Recomendación:** no lanzarla automáticamente. Primero un *soak* de 24 h con los puntos 1–4
resueltos, midiendo cuántos bloqueos por revisión aparecen y cómo se recuperan; después, y con
verificación independiente hecha, una campaña de 72 h.

## 6. Índice

- [RFC-TAP-AI-BOTS-003H.md](../../../RFC-TAP-AI-BOTS-003H.md)
- [RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json)
- [INDEPENDENT_VERIFICATION.md](INDEPENDENT_VERIFICATION.md) · [VERIFICATION.json](VERIFICATION.json) · [smoke/VERIFICATION_003H.md](smoke/VERIFICATION_003H.md)
- [STATE_AUDIT.md](STATE_AUDIT.md) · [PRESERVED_003G_VERIFICATION.md](PRESERVED_003G_VERIFICATION.md)
- Sesión: [smoke/SUMMARY.json](smoke/SUMMARY.json) · [smoke/STREAM.jsonl](smoke/STREAM.jsonl)
- Comparaciones: [smoke/compare/COMPARISON.json](smoke/compare/COMPARISON.json) · [smoke/compare-full/COMPARISON.json](smoke/compare-full/COMPARISON.json)
