# WP-TDM-13 — FINAL REPORT

**RFC:** RFC-TDM-013 · **Fecha:** 2026-10-25 · **Rama:** `evidence/tdm13`
**Commit auditado:** `a96e9c80` · **Baseline declarada:** `504256ec` (padre inmediato, comprobado)
**Worktree aislado** desde `a96e9c80`; checkout compartido intacto (`e67194e7`, 17 modificaciones ajenas)

## VEREDICTO

> ### `VERIFIED_REPRODUCIBLE`
> Los insumos están sellados y son recuperables desde un clon limpio; la integridad Git y las
> cifras se re-derivan con código propio; el replay en clon limpio devuelve los mismos números y el
> mismo veredicto; 6/6 controles negativos rechazan la corrupción.
> ### `INDEPENDENCE_NOT_DEMONSTRATED` (identidad) — ruta de código propia, mismo operador.
> ### Decisión de mercado **intacta**: `NO_ELIGIBLE_CANDIDATE`, `REJECTED_ALPHA`, sin PAPER/LIVE.

## 1. Lo comprobado, con su fuente

| Comprobación | Resultado | Evidencia |
| --- | --- | --- |
| `a96e9c80` existe, es commit, padre = `504256ec`, en `evidence/tdm12` | **PASS** | `GIT_AND_CLAIMS_AUDIT.json → git.identity` |
| Entregables de RFC-TDM-12 §8 | **14/14** | `GIT_AND_CLAIMS_AUDIT.json → git.deliverables` |
| Campos obligatorios de `RUN_REPORT.json` | **17/17** | idem → `required_fields` |
| Digests de evidencia y scripts vs blobs del commit | **16/16** | idem → `digests` |
| Cifras del cierre re-derivadas (no leídas del informe) | **16/16** | idem → `claims.rows` |
| Bytes sellados vs hashes declarados | **26/26** | `DATASET_MANIFEST.json`, `tdm13_inputs.py verify` |
| Klines vs procedencia de TDM-11 | **24/24** | `GIT_AND_CLAIMS_AUDIT.json → dataset_cross_check` |
| Manifiestos de split vs hashes de TDM-12 | **2/2** | idem → `tdm12_manifest_hashes_match` |
| Restore en clon limpio (sin untracked ocultos) | **26/26** sin discrepancias | `REPLAY_REPORT.json → inputs` |
| Replay del pipeline en clon limpio | **PASS**, 10/10 comparaciones | `REPLAY_REPORT.json` |
| Controles negativos | **6/6** demostrados | `NEGATIVE_CONTROLS.json` |
| Tests nuevos del verificador | **16 passed** | `RUN_REPORT.json → tests` |
| Archivos existentes modificados | **0** de `src/`, `tests/`, `data/` o TDM-12 | `GIT_AND_CLAIMS_AUDIT.json → git.scope` |
| Órdenes | `paper_orders=0`, `live_orders=0` | `RUN_REPORT.json` |

**Cómo se re-derivó cada cifra, no cómo se copió:** los 115 trades y el neto de −36,3676 bps se
recalculan desde `RETROSPECTIVE_LEDGER.csv` (media de `gross_bps` menos 23,7906 bps de coste); las 24
celdas medidas y las 30 filas del registro se cuentan en `CANDIDATE_REGISTRY.json`; la elegibilidad
se **recalcula** con la regla del registro (neto positivo en HOLD **y** DEV **y** potencia
suficiente) en vez de aceptar la lista publicada. Ninguna llamada a `tdm12_publish.py --verify`.

## 2. El replay, y el defecto que encontró

Clon limpio `git clone --no-local` fijado a `a96e9c80`, modelos de datos restaurados desde el bundle
sellado, `tdm12_review.py` y `tdm12_inventory.py` **sin modificar**.

| Intento | Resultado | Detalle |
| --- | --- | --- |
| 1 | **FAIL** — 24 diferencias | `rows[*].parameter_hash` distinto en las 24 celdas medidas; todo lo demás idéntico |
| 2 (justificado) | **PASS** — 10/10 | tras alinear los bytes del checkout, `parameter_hash` reproduce exacto |

**Causa del intento 1 (defecto `D-01` de TDM-12, no de este paquete):** `tdm12_inventory.py` calcula
`parameter_hash` como `sha256` de los bytes **del archivo en disco** (`module.__file__`), no del blob.
El clon heredó `core.autocrlf=true` y escribió CRLF; el checkout original tenía `false` y LF. Mismo
contenido versionado (`git hash-object` idéntico: `03fbb1bf…`), bytes distintos en disco → huella
distinta. Con `autocrlf=false` los bytes coinciden (4 640 bytes) y la huella vuelve a ser la publicada.

Medido: [EOL_FINGERPRINT_FINDING.json](evidence/tdm/wp-tdm-13/EOL_FINGERPRINT_FINDING.json) · intento
fallido conservado en [REPLAY_ATTEMPT1.json](evidence/tdm/wp-tdm-13/REPLAY_ATTEMPT1.json).

**Qué significa:** ninguna métrica, gate ni veredicto cambia. Pero un identificador que depende del
formato de checkout no sirve como huella de configuración. Arreglarlo es trabajo de quien mantiene
`tdm12_inventory.py`; aquí solo se documenta, se prueba y se recomienda usar el blob id.

## 3. Insumos: el hueco que TDM-12 dejó abierto

`data/tdm08` y `data/tdm10` no estaban en Git, así que un clon no podía re-ejecutar nada. Ahora viajan
sellados en el paquete: **26 archivos, 10 310 475 bytes**, con SHA-256 por archivo, procedencia y
regla de sellado, y una restauración de un comando ([DATASET_RESTORE.md](evidence/tdm/wp-tdm-13/DATASET_RESTORE.md)).
Son klines públicas sin credenciales ni datos personales; se versionan porque el repo ya versiona
árboles de datos sellados (`data/rfc049`, `data/recovery/wp7|wp8`).

## 4. Controles negativos

| ID | Inyección | Exit | Control que disparó |
| --- | --- | --- | --- |
| NC-01 | un byte invertido en un dataset | 1 | `FAIL` de SHA-256 |
| NC-02 | dataset requerido borrado | 1 | `missing` |
| NC-03 | `net_mean` alterado en `RUN_REPORT.json` | 1 | `net_mean_matches_manifest` |
| NC-04 | baseline declarada no-ancestro | 1 | `target_parent_is_baseline` |
| NC-05 | blob de evidencia alterado | 1 | nombre del archivo con digest distinto |
| NC-06 | fase colgada con timeout 2 s | 1 | `TIMEOUT` → replay `INCOMPLETE` (nunca `PASS`) |

Los seis corren en copias temporales destruidas al terminar; ninguno toca el worktree ni la baseline.

## 5. Defectos encontrados en este trabajo

| ID | Qué | Estado |
| --- | --- | --- |
| `D-01` | `parameter_hash` depende del fin de línea del checkout (TDM-12) | **abierto**, fuera del alcance de escritura de este RFC |
| `E-01` | mi verificador dio un falso FAIL de linaje (`git branch --contains` prefija `+`) | corregido |
| `E-02` | todos los controles negativos salían `PROVEN` (token buscado dentro de un blob que lo contenía) | corregido, con test |
| `E-03` | un replay falso dio 10/10 (comparaba artefactos restaurados por el checkout, no regenerados) | corregido: se borran antes de ejecutar |
| `E-04` | la fase de inventario moría en 0,1 s (`--reuse` dentro de la ruta del script) | corregido |

Los tres últimos los encontró la propia verificación, no una revisión a ojo; cada uno tiene su test o
su registro en `RUN_REPORT.json → errors`.

## 6. Límites que este informe NO supera

1. **Independencia de identidad `NOT_DEMONSTRATED`.** La ruta de código es propia —no importa ni
   ejecuta el verificador del constructor—, pero la escribió el mismo operador. No se inventa un
   segundo autor: se declara.
2. **Reproducibilidad ≠ corrección.** Que los números vuelvan a salir no dice que el pipeline mida lo
   que cree medir, ni que la estrategia tenga alpha.
3. **Insumos:** licencia y endpoint de captura `UNKNOWN`; re-descargar hoy no garantiza los mismos
   bytes que la copia sellada.
4. **Coste del corto, fills y funding** siguen `UNVERIFIED`; el spread sigue estimado a 1 bp. Nada de
   eso lo arregla una auditoría de hashes.
5. **Una sola ventana retrospectiva** y cero operaciones PAPER/LIVE.
6. **Segundo intento del replay** reutiliza el `review.json` y las métricas por celda ya calculados en
   el primero (recomputarlos completos no aporta información nueva y cuesta ~12 min); el registro de
   candidatos sí se regeneró desde cero. Queda dicho, no escondido.

## 7. Siguiente paso habilitado

Con `VERIFIED_REPRODUCIBLE`, la investigación de alpha puede apoyarse en insumos que viajan con la
evidencia y en un verificador que otro puede repetir. Lo que **no** habilita: promover ninguna
estrategia existente (`NO_ELIGIBLE_CANDIDATE` se mantiene), ni abrir PAPER/LIVE, ni reabrir la ventana
confirmatoria. El defecto `D-01` debería arreglarse antes de que cualquier artefacto futuro use
`parameter_hash` como identidad de configuración.
