# WP-051-02E — RUN REPORT

**Run**: `wp051-02e/EXP-004A/2026-10-21`
**RFC**: `RFC-EXP004A-051-02E` (`docs/agentic/exp004a/wp051_02e/RFC_EXP004A_051_02E.md`)
**Resultado del work package**: `WP_051_02E = PENDING_WINDOW`
**Captura prospectiva realizada**: **no**. La ventana declarada no ha abierto.
**Ejecuciones económicas**: 0.

---

## 1. Qué se pidió y qué se entregó

El RFC pide la primera captura prospectiva real de EXP-004A y su verificación independiente, y
admite explícitamente el cierre como `PENDING_WINDOW` si la ventana aún no ha abierto. Ese es el
caso: a las `2026-10-21T19:25:58Z` faltaban **16 441 s (4 h 34 min)** para
`2026-10-22T00:00:00Z`.

Lo que sí se ha ejecutado, contra el runtime real y no contra un fixture:

| Paso | Comando real | Exit | Efecto observable |
| --- | --- | --- | --- |
| preflight | `python scripts/exp004a_wp051_02e_preflight.py --attempt` | `0` | `READY_FOR_WINDOW`, 10/10 controles |
| captura BTC | `python scripts/exp004a_capture.py --slice 1h:BTC` | `3` | cero bytes; `data/exp004a` intacto |
| captura ETH | `python scripts/exp004a_capture.py --slice 1h:ETH` | `3` | cero bytes |
| captura SOL | `python scripts/exp004a_capture.py --slice 1h:SOL` | `3` | cero bytes |
| tape | `python scripts/exp004a_capture.py --slice st6:tape` | `2` | rechazado por contrato |

Los tres comandos se ejecutaron **tal como la declaración los nombra**, sin `--source`, sin `--out`
alternativo y sin banderas añadidas. Devolvieron `3` (*empty slice is not a dataset*) porque ninguna
barra del store abre dentro de la ventana. Un `3` es un rechazo, no una captura: el informe de
captura lo clasifica como `PENDING_WINDOW` y `datasets_published` está vacío.

## 2. Ventana, activos y límites — leídos de los artefactos, no del RFC

La autoridad es `config/preregistrations/EXP-004A.datasets.phase2.json`
(`EXP-004A.datasets.phase2/v1`, commit `a179ed0d74bfc5fd00383b2d575c9949ca6e1f95`, sha256
`eb27cedc…`), no la descripción del RFC.

| Campo | Valor declarado |
| --- | --- |
| `capture_window` | `2026-10-22T00:00:00Z` → `2027-01-20T00:00:00Z` (90 días) |
| `effective_from_utc` | `2026-10-21T16:00:00Z` |
| `issued_at_utc` | `2026-10-21T15:20:56Z` |
| Activos con contrato de slice | `1h:BTC`, `1h:ETH`, `1h:SOL` |
| `st6:tape` | declarado, **sin** contrato de slice → rechazado |
| `lag_bound_ms` | 7 200 000 (2 h) |
| `coverage_required` | 0.9 |
| `row_count` declarado | 2160 por serie |

## 3. Estado del freeze (comprobado por objetos de Git)

| Objeto | Identificador | Estado |
| --- | --- | --- |
| Declaración phase 1 | sha256 `8946f871…`, blob `43c9deea…` | intacta, sin cambios en el worktree |
| Declaración phase 2 | commit `a179ed0`, anterior a la apertura | válida, sin cambios |
| Generador | commit `fc036d9`, sha256 `af1ab7cc…`, blob `052832c2…` | el fichero que se ejecutaría es el blob declarado |
| Paquete sellado 02D | 19 artefactos | 19/19 con el mismo digest; 0 drift |

El informe de 02D sigue siendo válido: este WP **no ha modificado** ninguno de sus 19 artefactos, ni
`admission.py`, ni `C-004`, ni el modelo de costes, ni las declaraciones.

## 4. Por qué no hay captura (y por qué no se ha fabricado una)

1. **La ventana no está abierta.** El reloj del host, no una fecha escrita en un documento, dice
   `2026-10-21T19:26Z`; la ventana abre a `2026-10-22T00:00Z`.
2. **El store no contiene ninguna barra de la ventana.** 5 634 barras por serie, la última abre a
   `2026-10-21T17:00Z`, almacenada a `18:10:58Z`. Barras que abren dentro de la ventana: **0**.
3. **No se ha usado una fuente alternativa.** `--source` existe para ensayos y se ha usado solo en
   directorios temporales; el comando declarado no lo pasa.
4. **No se ha declarado válido nada obtenido antes de la vigencia.** Cualquier barra anterior a
   `effective_from_utc` se rechaza con `5`: reproducido en
   `WP_051_02E_INDEPENDENT_VERIFICATION.json` (`V-PROV-03`).

El store está vivo pero **no se ha demostrado que lo esté en el instante de la captura futura**: la
última escritura tenía 71 min (dentro del límite declarado de 2 h), y la barra de `18:00Z` todavía no
estaba almacenada cuando se ejecutó este informe. Eso no es un fallo, es una condición a revalidar
justo antes de capturar.

## 5. Verificación independiente

`scripts/exp004a_wp051_02e_verify.py` escribe
`WP_051_02E_INDEPENDENT_VERIFICATION.json`. No importa `trading_bot` ni ningún script del builder
(comprobado por AST en `V-POL-01`). Recalcula los anclajes desde constantes propias — no los aprende
del documento que inspecciona — y re-ejecuta cada rechazo en directorios temporales.

| Control | Checks | Qué prueba |
| --- | --- | --- |
| `TECHNICAL_VERIFICATION` | 6 | commit, digest, blob y ventana son los anclados; la declaración precede a la ventana |
| `PROVENANCE_VERIFICATION` | 9 | `exit 0/2/3/4/5`, cero bytes en cada rechazo, verbatim, declaración adulterada |
| `TEMPORAL_VERIFICATION` | 5 | el estado `BEFORE_WINDOW` es el real; `external_timestamp: UNAVAILABLE`; `C-013` débil |
| `ARTIFACT_INTEGRITY` | 5 | digests de los informes, ausencia de dataset, ledgers de admisión intactos |
| `POLICY_COMPLIANCE` | 6 | sin auto-certificación, gates intactos, limitación declarada = limitación observada |

Veredicto: ver §9 y `WP_051_02E_INDEPENDENT_VERIFICATION.json`.

## 6. Pruebas

201 pruebas, 1 skip preexistente (symlinks), todas con exit 0. Detalle en
`evidence/TEST_RUNS.json` y en `evidence/pytest_*.log`.

| Suite | Resultado | Exit |
| --- | --- | --- |
| `test_exp004a_capture.py` + `test_exp004a_provenance.py` | 46 passed, 27.91 s | 0 |
| `test_exp004a_wp051_02e.py` (nueva) | 30 passed, 41.68 s | 0 |
| `test_exp004a_verify_adversarial.py` | 20 passed, 5.24 s | 0 |
| `test_prospective_admission.py` | 36 passed, 1.59 s | 0 |
| `test_prereg_gate*.py` | 69 passed, 1 skipped, 107.63 s | 0 |
| `ruff check` (3 ficheros tocados) | All checks passed | 0 |

**No ejecutado**: `tests/unit/research` completo. WP-051-02C agotó 600 s sin terminarlo; repetirlo
aquí sería declarar un timeout como cobertura. Se declara `NOT_RUN`.

## 7. Defectos y limitaciones

**L-01 / DEF-02E-01 — el extractor acepta una barra con `fetched_at_ms` en el futuro.**
Reproducido por el verificador: una barra que abre dentro de la ventana y declara haberse almacenado
una hora *después* del instante de la captura se acepta con exit `0` y `eligible: true`. No se ha
corregido, y no por descuido: `scripts/exp004a_capture.py` está fijado por la declaración phase 2
(`generator.blob_sha256`), así que cualquier edición convierte **toda** captura en `exit 2`
(`GENERATOR_FILE_DIFFERS_FROM_DECLARED`). Cerrar el hueco exige una declaración sucesora phase 3 que
fije un commit nuevo del generador y se commitee **antes** de la ventana que gobierne — una decisión
de gobernanza, no un parche que este WP pueda tomar por su cuenta. Mitigación vigente: `C-013` sigue
`TIME_PROOF_WEAK` y `CERTIFICATION` sigue bloqueada, de modo que una captura de store forjado no puede
convertirse en certificación.

**L-02 — no hay scheduler.** El repositorio no tiene ningún proceso que ejecute los comandos
declarados al abrirse la ventana. `WP_051_02E_PREFLIGHT.json` publica la invocación exacta y dice
explícitamente que ni un operador ni un scheduler la han ejecutado. Este informe no promete una
ejecución futura automática.

**L-03 — la prueba temporal es débil por construcción.** Sin attestation externa,
`external_timestamp` es `UNAVAILABLE` en cada registro. Git demuestra orden, no tiempo de tercero.

## 8. Estado de los gates

| Gate | Estado | Comentario |
| --- | --- | --- |
| `C-004` | `PASS` | no tocado; `admission.py` sin cambios |
| `C-013` | `TIME_PROOF_WEAK` | sin attestation externa; no se ha inventado una |
| `C-015` | `PASS` (procedencia) | la declaración y el generador siguen encadenados; sin captura |
| `C-016` | `UNREACHABLE_UNDER_DECLARED_COST_MODEL` | fuera de alcance |
| `PAPER_VALIDATION` | `NOT_PASS` | no hay datos prospectivos |
| `CERTIFICATION` | `BLOCKED` | no hay captura que certificar |
| `PROMOTION` | `NO_PROMOTION` | — |
| `WP_051_02E` | **`PENDING_WINDOW`** | no es PASS de captura ni FAIL |

## 9. Qué haría falta para convertir esto en `PASS`

1. Esperar a `2026-10-22T00:00:00Z` o después, con el observador escribiendo barras de la ventana.
2. Re-ejecutar el preflight justo antes (`READY_FOR_WINDOW` de nuevo, y `bars_opening_in_window > 0`).
3. Ejecutar los tres comandos declarados y solo esos.
4. Volver a ejecutar el verificador sobre la captura resultante: `CAPTURED` exige dataset, y el
   verificador re-deriva ventana, integridad y cobertura antes de aceptarlo.

Nada de esto se ha hecho ni se ha simulado.
